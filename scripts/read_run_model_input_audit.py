#!/usr/bin/env python3
"""Model-input audit for the Track N structural-only screening (Phase 2).

Answers, mechanically and on the frozen v1 data, what a similarity-masked model
is left to work with, and pins the model-free reference numbers the outcome
table is read against. Everything is computed from the data on disk with the
shared `coverage` / `generator` / `gates` helpers — no checkpoint, no model.

1. **Cross-bucket identity.** Once `query_similarity_ppm` is held constant the
   five γ buckets must be byte-identical for the same episode position, so a
   masked run on `screen-g00` is a run on every bucket. Counted, not assumed.
2. **The assertion-mask channel.** With similarity gone the only per-node
   input is the 4-bit assertion mask. Rank AUC of mask value and popcount for
   on-route nodes and for target nodes against the rest; how often the two
   targets share a mask (by construction this is the abstain label); whether
   the answer is simply the modal mask of the graph.
3. **Relation ambiguity.** From each state on a valid route, how often a
   same-relation distractor edge exists, by depth and by (L, relation count);
   the crude "relation is in the query" filter's selectivity; the prefix-tree
   size and the relation walker's examined-set size, 3·|expanded nodes|.
4. **Reference route-completeness** at the prefix budgets, gated non-abstain,
   overall and per path length, for the relation walker
   (`coverage.relation_walker_examined_set`) and the DIRECT pool
   (`generator.structural_bfs_pool`); the pool must reproduce
   `ceiling_sweep.json` exactly.
5. Cross-check: `route_complete` equals the evaluator's `proof_valid` on every
   examined set scored here, and the pool at each smaller budget is a prefix of
   the pool at 128.

Aggregates go to the committed JSON; per-episode rows (which carry hidden
fields) stay under `private/`.
"""

from __future__ import annotations

import argparse
import copy
import json
import multiprocessing
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256
from hippocampus_foundation.read_run.ablation import (
    MASKED_SIMILARITY_PPM,
    mask_query_similarity,
)
from hippocampus_foundation.read_run.coverage import (
    node_assertion_masks,
    prefix_route_coverage,
    relation_prefix_tree,
    relation_walker_examined_set,
)
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.generator import (
    BUDGET_CANDIDATES,
    structural_bfs_pool,
)
from hippocampus_foundation.read_run.io import read_generated_split

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_learning_probe import wilson_lower_bound  # noqa: E402

GATED_STRATUM = "hops_2_4"
PREFIX_BUDGETS = (8, 16, 32, 64, 128)
MASK_VALUES = 16
POPCOUNT_VALUES = 5
AUC_BAND = (0.45, 0.55)
CEILING_SWEEP = Path("experiments/read_run_v1/diagnostics/ceiling_sweep.json")


def _proof_valid(episode: Any, examined: list[int]) -> bool:
    """The evaluator's own predicate on an examined set, with uniform scores."""

    return score_prediction(
        episode,
        predicted_class=0,
        recorded_routes=decode_best_routes(
            episode.visible, examined, [0.0] * len(examined)
        ),
    )["proof_valid"]


def _masked_digest(visible: dict[str, Any]) -> str:
    masked = copy.deepcopy(visible)
    mask_query_similarity(masked, MASKED_SIMILARITY_PPM)
    return canonical_sha256(masked)


# Hidden fields that carry γ by construction: the episode id embeds the bucket
# (`<paired_world_id>-gXX`), `requested_gamma` names it, and the greedy-teacher
# counts are computed from `query_similarity_ppm`. Everything else in the hidden
# payload — targets, valid routes, teacher actions, abstain, gold mask, branch
# depth — is the label a masked model is trained against and must not differ.
GAMMA_TAGGED_HIDDEN_FIELDS = frozenset(
    {"episode_id", "requested_gamma", "greedy_wrong_count", "measured_gamma"}
)


def _label_digest(hidden: dict[str, Any]) -> str:
    return canonical_sha256(
        {k: v for k, v in hidden.items() if k not in GAMMA_TAGGED_HIDDEN_FIELDS}
    )


def audit_episode(item: tuple[str, int, Any]) -> dict[str, Any]:
    """One per-episode row. Runs in a worker; returns only plain data."""

    split, position, episode = item
    visible = episode.visible
    hidden = episode.hidden
    relations = visible["query_relations"]
    length = len(relations)
    by_id = {edge["edge_id"]: edge for edge in visible["edges"]}
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)

    # --- assertion-mask channel -------------------------------------------
    masks = node_assertion_masks(visible)
    route_nodes: set[int] = set()
    for route in hidden["valid_routes"]:
        for edge_id in route:
            route_nodes.add(by_id[edge_id]["source"])
            route_nodes.add(by_id[edge_id]["target"])
    targets = set(hidden["target_nodes"])
    hist = {
        "route_mask": [0] * MASK_VALUES,
        "other_mask": [0] * MASK_VALUES,
        "target_mask": [0] * MASK_VALUES,
        "nontarget_mask": [0] * MASK_VALUES,
        "route_pop": [0] * POPCOUNT_VALUES,
        "other_pop": [0] * POPCOUNT_VALUES,
        "target_pop": [0] * POPCOUNT_VALUES,
        "nontarget_pop": [0] * POPCOUNT_VALUES,
    }
    for node, mask in masks.items():
        pop = bin(mask).count("1")
        hist["route_mask" if node in route_nodes else "other_mask"][mask] += 1
        hist["route_pop" if node in route_nodes else "other_pop"][pop] += 1
        hist["target_mask" if node in targets else "nontarget_mask"][mask] += 1
        hist["target_pop" if node in targets else "nontarget_pop"][pop] += 1
    counts = Counter(masks.values())
    node_count = len(masks)
    random_pair_share = (
        sum(c * (c - 1) for c in counts.values()) / (node_count * (node_count - 1))
        if node_count > 1
        else 0.0
    )
    modal_mask, modal_count = counts.most_common(1)[0]
    target_masks = {masks[node] for node in targets}
    answer_mask = None if hidden["abstain"] else hidden["gold_assertion_mask"]

    # --- relation ambiguity -----------------------------------------------
    # A route state is (node, depth) on any valid route; its route successors
    # are the edges at that depth of every valid route through it; a distractor
    # is any other out-edge carrying the relation the query asks for there.
    successors: dict[tuple[int, int], set[int]] = defaultdict(set)
    for route in hidden["valid_routes"]:
        for depth, edge_id in enumerate(route):
            successors[(by_id[edge_id]["source"], depth)].add(edge_id)
    state_rows = []
    for (node, depth), route_edges in sorted(successors.items()):
        distractors = [
            edge["edge_id"]
            for edge in by_source[node]
            if edge["relation"] == relations[depth]
            and edge["edge_id"] not in route_edges
        ]
        state_rows.append({"depth": depth, "distractors": len(distractors)})
    query_set = set(relations)
    in_query_all = sum(1 for edge in visible["edges"] if edge["relation"] in query_set)

    # --- examined sets ----------------------------------------------------
    tree = relation_prefix_tree(visible)
    walker_full = relation_walker_examined_set(visible, len(visible["edges"]) + 1)
    walker_128 = relation_walker_examined_set(visible, 128)
    expanded = {by_id[edge_id]["source"] for edge_id in walker_full}
    pool_128 = structural_bfs_pool(visible, 128)
    pool_prefix_mismatches = sum(
        structural_bfs_pool(visible, b) != pool_128[:b]
        for b in BUDGET_CANDIDATES
        if b < 128
    )
    in_query_pool = sum(
        1 for edge_id in pool_128 if by_id[edge_id]["relation"] in query_set
    )
    walker_rc = prefix_route_coverage(episode, walker_128, PREFIX_BUDGETS)
    pool_rc = prefix_route_coverage(episode, pool_128, PREFIX_BUDGETS)
    disagreements = 0
    for examined, coverage in ((walker_128, walker_rc), (pool_128, pool_rc)):
        for b, row in coverage.items():
            if row["route_complete"] != _proof_valid(episode, examined[:b]):
                disagreements += 1

    return {
        "split": split,
        "position": position,
        "episode_id": episode.episode_id,
        "paired_world_id": episode.paired_world_id,
        "masked_visible_sha256": _masked_digest(visible),
        "hidden_sha256": canonical_sha256(hidden),
        "label_sha256": _label_digest(hidden),
        "stratum": coverage_stratum(target_hop_distance(episode)),
        "abstain": bool(hidden["abstain"]),
        "path_length": length,
        "relation_count": visible["relation_count"],
        "node_count": node_count,
        "edge_count": len(visible["edges"]),
        "mask_histograms": hist,
        "targets_share_mask": len(target_masks) == 1,
        "random_pair_share_probability": random_pair_share,
        "answer_mask": answer_mask,
        "modal_mask": modal_mask,
        "modal_mask_fraction": modal_count / node_count,
        "answer_is_modal_mask": (
            None if answer_mask is None else answer_mask == modal_mask
        ),
        "route_states": state_rows,
        "in_query_relation_fraction_all_edges": in_query_all / len(visible["edges"]),
        "in_query_relation_fraction_pool_128": in_query_pool / len(pool_128),
        "tree_size": len(tree),
        "walker_size": len(walker_full),
        "expanded_node_count": len(expanded),
        "walker_128_is_prefix_of_full": walker_128 == walker_full[:128],
        "walker_route_complete_at": {
            str(b): bool(row["route_complete"]) for b, row in walker_rc.items()
        },
        "pool_route_complete_at": {
            str(b): bool(row["route_complete"]) for b, row in pool_rc.items()
        },
        "pool_prefix_mismatches": pool_prefix_mismatches,
        "route_complete_vs_proof_valid_disagreements": disagreements,
    }


def masked_digest_item(item: tuple[str, int, Any]) -> dict[str, Any]:
    split, position, episode = item
    return {
        "split": split,
        "position": position,
        "episode_id": episode.episode_id,
        "paired_world_id": episode.paired_world_id,
        "masked_visible_sha256": _masked_digest(episode.visible),
        "hidden_sha256": canonical_sha256(episode.hidden),
        "label_sha256": _label_digest(episode.hidden),
    }


def _labelled(split: str, root: Path, limit: int | None):
    episodes = read_generated_split(root)
    if limit is not None:
        episodes = islice(episodes, limit)
    for position, episode in enumerate(episodes):
        yield (split, position, episode)


def _rank_auc(positive: list[int], negative: list[int]) -> float | None:
    """P(positive value > negative value) with ties counted half, from histograms."""

    total_positive = sum(positive)
    total_negative = sum(negative)
    if not total_positive or not total_negative:
        return None
    wins = 0.0
    below = 0
    for value in range(len(positive)):
        wins += positive[value] * (below + 0.5 * negative[value])
        below += negative[value]
    return wins / (total_positive * total_negative)


def _fraction(count: int, n: int) -> dict[str, Any]:
    return {
        "count": count,
        "n": n,
        "fraction": count / n if n else None,
        "wilson_lower_bound": wilson_lower_bound(count, n) if n else None,
    }


def _distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(values),
        "min": ordered[0],
        "p25": ordered[len(ordered) // 4],
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "p75": ordered[(3 * len(ordered)) // 4],
        "p95": ordered[min(len(ordered) - 1, (95 * len(ordered)) // 100)],
        "max": ordered[-1],
        "histogram": {str(k): v for k, v in sorted(Counter(values).items())},
    }


def _sum_hist(rows: list[dict[str, Any]], key: str, size: int) -> list[int]:
    total = [0] * size
    for row in rows:
        for value, count in enumerate(row["mask_histograms"][key]):
            total[value] += count
    return total


def _reference_block(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Route-completeness at each prefix budget, overall and per path length."""

    n = len(rows)
    overall = {
        str(b): _fraction(sum(row[key][str(b)] for row in rows), n)
        for b in PREFIX_BUDGETS
    }
    by_length: dict[str, Any] = {}
    for length in sorted({row["path_length"] for row in rows}):
        subset = [row for row in rows if row["path_length"] == length]
        by_length[str(length)] = {
            str(b): _fraction(sum(row[key][str(b)] for row in subset), len(subset))
            for b in PREFIX_BUDGETS
        }
    return {"overall": overall, "by_path_length": by_length}


def summarize_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gated = [
        row for row in rows if row["stratum"] == GATED_STRATUM and not row["abstain"]
    ]
    non_abstain = [row for row in rows if not row["abstain"]]

    aucs = {
        "on_route_mask_value": _rank_auc(
            _sum_hist(rows, "route_mask", MASK_VALUES),
            _sum_hist(rows, "other_mask", MASK_VALUES),
        ),
        "on_route_popcount": _rank_auc(
            _sum_hist(rows, "route_pop", POPCOUNT_VALUES),
            _sum_hist(rows, "other_pop", POPCOUNT_VALUES),
        ),
        "is_target_mask_value": _rank_auc(
            _sum_hist(rows, "target_mask", MASK_VALUES),
            _sum_hist(rows, "nontarget_mask", MASK_VALUES),
        ),
        "is_target_popcount": _rank_auc(
            _sum_hist(rows, "target_pop", POPCOUNT_VALUES),
            _sum_hist(rows, "nontarget_pop", POPCOUNT_VALUES),
        ),
    }

    states = [state for row in rows for state in row["route_states"]]
    by_depth: dict[str, Any] = {}
    for depth in sorted({state["depth"] for state in states}):
        subset = [state for state in states if state["depth"] == depth]
        by_depth[str(depth)] = _fraction(
            sum(1 for state in subset if state["distractors"]), len(subset)
        )
    by_cell: dict[str, Any] = {}
    for length, relation_count in sorted(
        {(row["path_length"], row["relation_count"]) for row in rows}
    ):
        subset = [
            state
            for row in rows
            if row["path_length"] == length and row["relation_count"] == relation_count
            for state in row["route_states"]
        ]
        by_cell[f"L{length}_R{relation_count}"] = _fraction(
            sum(1 for state in subset if state["distractors"]), len(subset)
        )

    answer_rows = [row for row in non_abstain if row["answer_mask"] is not None]
    return {
        "episode_count": len(rows),
        "non_abstain_count": len(non_abstain),
        "gated_non_abstain_count": len(gated),
        "path_length_counts": {
            str(k): v
            for k, v in sorted(Counter(row["path_length"] for row in gated).items())
        },
        "assertion_mask_channel": {
            "rank_auc": aucs,
            "targets_share_mask": {
                "all_episodes": _fraction(
                    sum(row["targets_share_mask"] for row in rows), len(rows)
                ),
                "equals_one_minus_abstain_fraction_by_construction": True,
                "random_pair_share_probability_mean": statistics.fmean(
                    row["random_pair_share_probability"] for row in rows
                ),
            },
            "answer_is_modal_mask": {
                "non_abstain": _fraction(
                    sum(bool(row["answer_is_modal_mask"]) for row in answer_rows),
                    len(answer_rows),
                ),
                "modal_mask_fraction_mean": statistics.fmean(
                    row["modal_mask_fraction"] for row in rows
                ),
                "answer_class_counts": {
                    str(k): v
                    for k, v in sorted(
                        Counter(row["answer_mask"] for row in answer_rows).items()
                    )
                },
            },
        },
        "relation_ambiguity": {
            "route_states_with_distractor": _fraction(
                sum(1 for state in states if state["distractors"]), len(states)
            ),
            "episodes_with_any_distractor": _fraction(
                sum(
                    1
                    for row in rows
                    if any(state["distractors"] for state in row["route_states"])
                ),
                len(rows),
            ),
            "distractors_per_state_mean": statistics.fmean(
                state["distractors"] for state in states
            ),
            "by_depth": by_depth,
            "by_path_length_and_relation_count": by_cell,
            "in_query_relation_fraction": {
                "all_edges_mean": statistics.fmean(
                    row["in_query_relation_fraction_all_edges"] for row in rows
                ),
                "pool_128_mean": statistics.fmean(
                    row["in_query_relation_fraction_pool_128"] for row in rows
                ),
            },
        },
        "examined_set_sizes_gated_non_abstain": {
            "tree_size": _distribution([row["tree_size"] for row in gated]),
            "walker_size": _distribution([row["walker_size"] for row in gated]),
            "expanded_node_count": _distribution(
                [row["expanded_node_count"] for row in gated]
            ),
            "walker_size_by_path_length": {
                str(length): _distribution(
                    [
                        row["walker_size"]
                        for row in gated
                        if row["path_length"] == length
                    ]
                )
                for length in sorted({row["path_length"] for row in gated})
            },
            "walker_size_is_three_per_expanded_node": all(
                row["walker_size"] == 3 * row["expanded_node_count"] for row in rows
            ),
        },
        "reference_route_completeness_gated_non_abstain": {
            "relation_walker": _reference_block(gated, "walker_route_complete_at"),
            "direct_pool": _reference_block(gated, "pool_route_complete_at"),
        },
        "cross_checks": {
            "route_complete_vs_proof_valid_disagreements": sum(
                row["route_complete_vs_proof_valid_disagreements"] for row in rows
            ),
            "pool_prefix_mismatches": sum(
                row["pool_prefix_mismatches"] for row in rows
            ),
            "walker_128_not_prefix_of_full": sum(
                not row["walker_128_is_prefix_of_full"] for row in rows
            ),
        },
    }


def compare_buckets(
    reference: list[dict[str, Any]], other: list[dict[str, Any]]
) -> dict[str, Any]:
    """Position-by-position comparison of one γ bucket against the reference.

    `episode_id` and the full hidden digest differ in *every* pair by
    construction (the id embeds the bucket; the hidden payload carries the
    requested γ and the greedy-teacher counts), so those two counts are reported
    as a sanity check on the comparison itself, not gated. What must agree is
    the paired world id, the masked visible payload, and the label digest.
    """

    pairs = list(zip(reference, other, strict=False))
    return {
        "compared": len(pairs),
        "length_mismatch": len(reference) != len(other),
        "paired_world_id_mismatches": sum(
            a["paired_world_id"] != b["paired_world_id"] for a, b in pairs
        ),
        "masked_visible_mismatches": sum(
            a["masked_visible_sha256"] != b["masked_visible_sha256"] for a, b in pairs
        ),
        "label_mismatches": sum(
            a["label_sha256"] != b["label_sha256"] for a, b in pairs
        ),
        "gamma_tagged_hidden_fields_excluded": sorted(GAMMA_TAGGED_HIDDEN_FIELDS),
        "episode_id_mismatches_expected_all": sum(
            a["episode_id"] != b["episode_id"] for a, b in pairs
        ),
        "full_hidden_mismatches_expected_all": sum(
            a["hidden_sha256"] != b["hidden_sha256"] for a, b in pairs
        ),
    }


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "log", "-1", "--format=%H %cI %s"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--other-screen-roots", nargs="*", default=[])
    parser.add_argument("--train-root", required=True)
    parser.add_argument("--train-limit", type=int, default=10_000)
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--rows", required=True, help="per-episode rows (private)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--ceiling-sweep", default=str(CEILING_SWEEP))
    args = parser.parse_args()

    started = datetime.now(UTC).replace(microsecond=0).isoformat()
    rows_path = Path(args.rows)
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    screen_rows: list[dict[str, Any]] = []
    train_rows: list[dict[str, Any]] = []
    with (
        multiprocessing.Pool(args.workers) as pool,
        rows_path.open("w", encoding="utf-8") as rows_file,
    ):
        for split, root, limit, sink in (
            ("screen", Path(args.screen_root), None, screen_rows),
            ("train", Path(args.train_root), args.train_limit, train_rows),
        ):
            for row in pool.imap(
                audit_episode, _labelled(split, root, limit), chunksize=16
            ):
                sink.append(row)
                rows_file.write(json.dumps(row, sort_keys=True) + "\n")
        bucket_reports = {}
        for other in args.other_screen_roots:
            digests = list(
                pool.imap(
                    masked_digest_item,
                    _labelled(Path(other).name, Path(other), None),
                    chunksize=32,
                )
            )
            bucket_reports[Path(other).name] = compare_buckets(screen_rows, digests)
    rows_path.chmod(0o600)

    screen_summary = summarize_split(screen_rows)
    train_summary = summarize_split(train_rows)

    reference = json.loads(Path(args.ceiling_sweep).read_text())
    reference_gated = reference["by_gamma"]["0.0"]
    expected_pool = {
        str(b): reference_gated["gated"][str(b)]["direct"]["route_complete"]["count"]
        for b in BUDGET_CANDIDATES
    }
    measured_pool = {
        str(b): screen_summary["reference_route_completeness_gated_non_abstain"][
            "direct_pool"
        ]["overall"][str(b)]["count"]
        for b in BUDGET_CANDIDATES
    }
    expected_pool_by_length = {
        length: {
            str(b): block["budgets"][str(b)]["direct"]["route_complete"]["count"]
            for b in BUDGET_CANDIDATES
        }
        for length, block in reference_gated["gated_by_path_length"].items()
    }
    measured_pool_by_length = {
        length: {str(b): block[str(b)]["count"] for b in BUDGET_CANDIDATES}
        for length, block in screen_summary[
            "reference_route_completeness_gated_non_abstain"
        ]["direct_pool"]["by_path_length"].items()
    }
    aucs = screen_summary["assertion_mask_channel"]["rank_auc"]
    walker_128 = screen_summary["reference_route_completeness_gated_non_abstain"][
        "relation_walker"
    ]["overall"]["128"]
    gates = {
        "cross_bucket_identity_exact": bool(bucket_reports)
        and all(
            report["masked_visible_mismatches"] == 0
            and report["label_mismatches"] == 0
            and report["paired_world_id_mismatches"] == 0
            and not report["length_mismatch"]
            and report["episode_id_mismatches_expected_all"] == report["compared"]
            for report in bucket_reports.values()
        ),
        "mask_aucs_in_band": all(
            value is not None and AUC_BAND[0] <= value <= AUC_BAND[1]
            for value in aucs.values()
        ),
        "pool_reproduced": (
            screen_summary["gated_non_abstain_count"]
            == reference_gated["gated_non_abstain"]
            and measured_pool == expected_pool
            and measured_pool_by_length == expected_pool_by_length
        ),
        "walker_route_complete_128_gated_fraction": walker_128["fraction"],
        "walker_route_complete_128_is_100_percent": walker_128["count"]
        == walker_128["n"],
        "disagreements_zero": (
            screen_summary["cross_checks"][
                "route_complete_vs_proof_valid_disagreements"
            ]
            == 0
            and train_summary["cross_checks"][
                "route_complete_vs_proof_valid_disagreements"
            ]
            == 0
        ),
        "pool_prefix_consistent": (
            screen_summary["cross_checks"]["pool_prefix_mismatches"] == 0
            and train_summary["cross_checks"]["pool_prefix_mismatches"] == 0
        ),
    }
    report = {
        "record_kind": "read_run_model_input_audit",
        "started_at": started,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "git_head": _git_head(),
        "screen_root": args.screen_root,
        "train_root": args.train_root,
        "train_limit": args.train_limit,
        "masked_similarity_ppm": MASKED_SIMILARITY_PPM,
        "prefix_budgets": list(PREFIX_BUDGETS),
        "auc_band": list(AUC_BAND),
        "cross_bucket_identity": bucket_reports,
        "screen": screen_summary,
        "train": train_summary,
        "pool_reference": {
            "source": args.ceiling_sweep,
            "expected_gated_non_abstain": reference_gated["gated_non_abstain"],
            "expected_route_complete_counts": expected_pool,
            "measured_route_complete_counts": measured_pool,
            "expected_by_path_length": expected_pool_by_length,
            "measured_by_path_length": measured_pool_by_length,
        },
        "launch_gates": gates,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(gates, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
