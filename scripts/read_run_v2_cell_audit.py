"""Model-free audit of the Track O generator-v2 cell grid (phase O-2).

Generates episodes per cell in memory — no split is written and no holdout is
touched — and measures, for each cell, everything the O-4 preregistration will
need as reference numbers, plus the four launch gates of
`docs/TRACK_O_DESIGN.md` section 5:

1. **Leak identifiability (G1).** Rank-AUC of per-node similarity statistics
   (max and mean over a node's out-edges) for on-route nodes, and of per-edge
   similarity for on-route edges, must sit in [0.45, 0.55]. The edge-level
   statistic is expected to leave the band at gamma = 0 *by design* — that is
   the intended edge-choice signal — so it is reported for both gammas and
   gated only on the node-level statistics, which are the section 1.5 leak.
2. **A walker-insufficient cell exists.** At the planned budget, the model-free
   relation walker must fail to be route-complete on a material fraction of
   gated episodes in at least one cell. The planned budget is 64, chosen by
   the model-free criterion in `oracle_vs_walker` below and fixed before any
   Track O model exists — the same discipline as v1's
   `budget_source: coverage_only_before_screening_accuracy`.
3. **A walker-exact cell exists.** At the same budget, at least one cell where
   the walker is route-complete on every gated episode (the sanity rung).

The audit also reports, per cell and budget, the **oracle floor**: a perfect
selector still expands whole nodes, so it must examine every out-edge of each
node that sources a route edge. The band between "oracle feasible" and "walker
sufficient" is the room a learned traversal has to beat the computed one; it is
what the budget choice is made on, and it is measured with no model.
4. **Zero cross-check disagreements.** `route_coverage(...)["route_complete"]`
   equals the evaluator's `proof_valid` on every examined set audited, and no
   episode reaches an endpoint outside its target set.

Also reported per cell, without gates: generation failure rate, the DIRECT
structural pool's route-completeness at every prefix budget, walker examined-set
sizes and precision, relation-prefix tree sizes, per-path-length breakdowns,
planting-uniformity evidence, rule/schema variability, and the assertion-mask
channel AUCs carried over from the v1 audit.

Read-only with respect to the repository: writes one aggregates JSON. Per-episode
rows go to a private path when asked for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hippocampus_foundation.read_run.coverage import (  # noqa: E402
    node_assertion_masks,
    relation_prefix_tree,
    relation_walker_examined_set,
    route_coverage,
)
from hippocampus_foundation.read_run.errors import GenerationError  # noqa: E402
from hippocampus_foundation.read_run.evaluation import score_prediction  # noqa: E402
from hippocampus_foundation.read_run.gates import (  # noqa: E402
    coverage_stratum,
    target_hop_distance,
)
from hippocampus_foundation.read_run.generator import (  # noqa: E402
    structural_bfs_pool,
)
from hippocampus_foundation.read_run.generator_v2 import (  # noqa: E402
    CELLS,
    edge_satisfies_rule,
    generate_episode_v2,
)

PREFIX_BUDGETS = (8, 16, 32, 64, 128)
PLANNED_BUDGET = 64
GATED = "hops_2_4"
AUC_BAND = (0.45, 0.55)
Z_ONE_SIDED_95 = 1.6448536269514722
WALKER_INSUFFICIENT_MAX_FRACTION = 0.95
_CONTEXT: dict[str, Any] = {}


def wilson_lower_bound(correct: int, total: int) -> float:
    if total == 0:
        return 0.0
    z = Z_ONE_SIDED_95
    point = correct / total
    denominator = 1.0 + z * z / total
    centre = point + z * z / (2.0 * total)
    radius = z * math.sqrt(
        point * (1.0 - point) / total + z * z / (4.0 * total * total)
    )
    return (centre - radius) / denominator


def rank_auc(positives: list[float], negatives: list[float]) -> float | None:
    """Mann-Whitney rank AUC with tie-averaged ranks; None when a side is empty."""

    if not positives or not negatives:
        return None
    both = sorted([(v, 1) for v in positives] + [(v, 0) for v in negatives])
    rank_sum, rank, index = 0.0, 1, 0
    while index < len(both):
        end = index
        while end < len(both) and both[end][0] == both[index][0]:
            end += 1
        average = (2 * rank + (end - index) - 1) / 2
        rank_sum += average * sum(1 for k in range(index, end) if both[k][1] == 1)
        rank += end - index
        index = end
    n1, n0 = len(positives), len(negatives)
    return (rank_sum - n1 * (n1 + 1) / 2) / (n1 * n0)


def _distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "min": ordered[0],
        "p25": ordered[n // 4],
        "median": ordered[n // 2],
        "p75": ordered[(3 * n) // 4],
        "p95": ordered[min(n - 1, int(0.95 * n))],
        "max": ordered[-1],
        "mean": sum(ordered) / n,
    }


def _fraction(count: int, total: int) -> dict[str, Any]:
    return {
        "count": count,
        "n": total,
        "fraction": (count / total) if total else 0.0,
        "wilson_lower_bound": wilson_lower_bound(count, total),
    }


def _initialise(cell: str, seed_hex: str, count: int, gamma: float) -> None:
    _CONTEXT.update(cell=cell, seed=bytes.fromhex(seed_hex), count=count, gamma=gamma)


def audit_episode(index: int) -> dict[str, Any]:
    """One episode's structural audit row. Runs in a worker process."""

    config = CELLS[_CONTEXT["cell"]]
    try:
        episode = generate_episode_v2(
            _CONTEXT["seed"],
            config=config,
            split="test-fixture",
            index=index,
            count=_CONTEXT["count"],
            gamma=_CONTEXT["gamma"],
            gold_mask=None if index % 4 == 0 else 1 + (index % 15),
        )
    except GenerationError as error:
        return {"index": index, "generated": False, "error": str(error)}

    visible, hidden = episode.visible, episode.hidden
    edges = visible["edges"]
    content = [tuple(node["content"]) for node in visible["nodes"]]
    rules = hidden["relation_rules"]
    rule_violations = sum(
        0
        if edge_satisfies_rule(
            (edge["source"], edge["target"], edge["relation"]),
            content=content,
            rules=rules,
        )
        else 1
        for edge in edges
    )

    stratum = coverage_stratum(target_hop_distance(episode))
    on_route_edges = {edge_id for route in hidden["valid_routes"] for edge_id in route}
    on_route_nodes = {edges[edge_id]["source"] for edge_id in on_route_edges}
    targets = set(hidden["target_nodes"])

    pool = structural_bfs_pool(visible, max(PREFIX_BUDGETS))
    walker = relation_walker_examined_set(visible, max(PREFIX_BUDGETS))
    walker_full = relation_walker_examined_set(visible, 1 << 20)
    tree = relation_prefix_tree(visible)
    # A perfect selector expands whole nodes too: every out-edge of every node
    # that sources a route edge. This is the floor no examined-set policy can
    # beat under the model's expansion mechanics.
    route_sources = {edges[edge_id]["source"] for edge_id in on_route_edges}
    oracle_floor = config.out_degree * len(route_sources)

    coverage_rows: dict[str, dict[str, int]] = {}
    disagreements = 0
    outside = 0
    for name, examined in (("pool", pool), ("walker", walker)):
        per_budget = {}
        for budget in PREFIX_BUDGETS:
            prefix = examined[:budget]
            coverage = route_coverage(episode, prefix)
            per_budget[str(budget)] = int(coverage["route_complete"])
            outside += len(coverage["reached_outside_targets"])
            if budget == PLANNED_BUDGET:
                scored = score_prediction(
                    episode,
                    predicted_class=(
                        0 if hidden["abstain"] else hidden["gold_assertion_mask"]
                    ),
                    recorded_routes=[
                        list(route)
                        for route in hidden["valid_routes"]
                        if set(route) <= set(prefix)
                    ],
                )
                disagreements += int(
                    bool(coverage["route_complete"]) != bool(scored["proof_valid"])
                )
        coverage_rows[name] = per_budget

    per_node_similarity: dict[int, list[int]] = defaultdict(list)
    for edge in edges:
        per_node_similarity[edge["source"]].append(edge["query_similarity_ppm"])
    node_stats = [
        {
            "node": node,
            "on_route": node in on_route_nodes,
            "max": max(values),
            "mean": sum(values) / len(values),
        }
        for node, values in per_node_similarity.items()
    ]
    edge_stats = [
        {
            "on_route": edge["edge_id"] in on_route_edges,
            "similarity": edge["query_similarity_ppm"],
        }
        for edge in edges
    ]
    masks = node_assertion_masks(visible)
    mask_stats = [
        {
            "on_route": node in on_route_nodes,
            "is_target": node in targets,
            "mask": masks[node],
            "popcount": bin(masks[node]).count("1"),
        }
        for node in range(visible["node_count"])
    ]

    return {
        "index": index,
        "generated": True,
        "stratum": stratum,
        "abstain": bool(hidden["abstain"]),
        "path_length": len(visible["query_relations"]),
        "node_count": visible["node_count"],
        "edge_count": len(edges),
        "relation_count": visible["relation_count"],
        "content_attribute_count": visible["content_attribute_count"],
        "content_value_count": visible["content_value_count"],
        "query_has_repeats": len(set(visible["query_relations"]))
        < len(visible["query_relations"]),
        "rule_violations": rule_violations,
        "rule_digest": hashlib.sha256(
            json.dumps(rules, sort_keys=True).encode()
        ).hexdigest()[:16],
        "planting_valid_set_sizes": hidden["planting_valid_set_sizes"],
        "greedy_wrong_count": hidden["greedy_wrong_count"],
        "path_step_count": hidden["path_step_count"],
        "tree_size": len(tree),
        "oracle_floor": oracle_floor,
        "walker_size": len(walker),
        "walker_full_size": len(walker_full),
        "walker_precision": len(on_route_edges & set(walker)) / max(len(walker), 1),
        "pool_precision": len(on_route_edges & set(pool)) / len(pool),
        "on_route_edge_count": len(on_route_edges),
        "coverage": coverage_rows,
        "cross_check_disagreements": disagreements,
        "reached_outside_targets": outside,
        "node_similarity": node_stats,
        "edge_similarity": edge_stats,
        "mask_stats": mask_stats,
    }


def summarize(rows: list[dict[str, Any]], attempted: int) -> dict[str, Any]:
    generated = [row for row in rows if row["generated"]]
    gated = [row for row in generated if row["stratum"] == GATED and not row["abstain"]]
    n = len(gated)

    coverage: dict[str, Any] = {}
    for name in ("pool", "walker"):
        overall = {
            str(budget): _fraction(
                sum(row["coverage"][name][str(budget)] for row in gated), n
            )
            for budget in PREFIX_BUDGETS
        }
        by_length: dict[str, Any] = {}
        for length in sorted({row["path_length"] for row in gated}):
            subset = [row for row in gated if row["path_length"] == length]
            by_length[str(length)] = {
                str(budget): _fraction(
                    sum(row["coverage"][name][str(budget)] for row in subset),
                    len(subset),
                )
                for budget in PREFIX_BUDGETS
            }
        coverage[name] = {"overall": overall, "by_path_length": by_length}

    node_pos = [
        s["max"] for row in gated for s in row["node_similarity"] if s["on_route"]
    ]
    node_neg = [
        s["max"] for row in gated for s in row["node_similarity"] if not s["on_route"]
    ]
    mean_pos = [
        s["mean"] for row in gated for s in row["node_similarity"] if s["on_route"]
    ]
    mean_neg = [
        s["mean"] for row in gated for s in row["node_similarity"] if not s["on_route"]
    ]
    edge_pos = [
        s["similarity"]
        for row in gated
        for s in row["edge_similarity"]
        if s["on_route"]
    ]
    edge_neg = [
        s["similarity"]
        for row in gated
        for s in row["edge_similarity"]
        if not s["on_route"]
    ]
    mask_route_pos = [
        s["mask"] for row in gated for s in row["mask_stats"] if s["on_route"]
    ]
    mask_route_neg = [
        s["mask"] for row in gated for s in row["mask_stats"] if not s["on_route"]
    ]
    mask_target_pos = [
        s["mask"] for row in gated for s in row["mask_stats"] if s["is_target"]
    ]
    mask_target_neg = [
        s["mask"] for row in gated for s in row["mask_stats"] if not s["is_target"]
    ]

    steps = sum(row["path_step_count"] for row in generated)
    wrong = sum(row["greedy_wrong_count"] for row in generated)
    planting = [size for row in generated for size in row["planting_valid_set_sizes"]]

    return {
        "attempted": attempted,
        "generated": len(generated),
        "generation_failure_fraction": 1.0 - len(generated) / attempted,
        "non_abstain": sum(1 for row in generated if not row["abstain"]),
        "gated_non_abstain": n,
        "stratum_counts": dict(Counter(row["stratum"] for row in generated)),
        "path_length_counts": {
            str(k): v
            for k, v in sorted(Counter(row["path_length"] for row in gated).items())
        },
        "query_repeat_fraction": (
            sum(row["query_has_repeats"] for row in generated) / len(generated)
        ),
        "measured_gamma": (wrong / steps) if steps else None,
        "rule_violations_total": sum(row["rule_violations"] for row in generated),
        "distinct_rule_digests": len({row["rule_digest"] for row in generated}),
        "distinct_schema_shapes": len(
            {
                (row["content_attribute_count"], row["content_value_count"])
                for row in generated
            }
        ),
        "planting_valid_set_size": _distribution(planting),
        "edge_count": _distribution([row["edge_count"] for row in generated]),
        "tree_size_gated": _distribution([row["tree_size"] for row in gated]),
        "walker_size_gated": _distribution([row["walker_size"] for row in gated]),
        "walker_full_size_gated": _distribution(
            [row["walker_full_size"] for row in gated]
        ),
        "oracle_floor_gated": _distribution([row["oracle_floor"] for row in gated]),
        "oracle_vs_walker": {
            str(budget): {
                "oracle_feasible": _fraction(
                    sum(1 for row in gated if row["oracle_floor"] <= budget), n
                ),
                "walker_sufficient": _fraction(
                    sum(1 for row in gated if row["walker_full_size"] <= budget), n
                ),
                "room_pp": 100.0
                * (
                    sum(1 for row in gated if row["oracle_floor"] <= budget)
                    - sum(1 for row in gated if row["walker_full_size"] <= budget)
                )
                / max(n, 1),
            }
            for budget in PREFIX_BUDGETS
        },
        "on_route_edges_gated": _distribution(
            [row["on_route_edge_count"] for row in gated]
        ),
        "precision_gated": {
            "walker_mean": sum(row["walker_precision"] for row in gated) / max(n, 1),
            "pool_mean": sum(row["pool_precision"] for row in gated) / max(n, 1),
        },
        "coverage_gated": coverage,
        "leak_aucs": {
            "node_max_similarity_on_route": rank_auc(node_pos, node_neg),
            "node_mean_similarity_on_route": rank_auc(mean_pos, mean_neg),
            "edge_similarity_on_route_expected_signal": rank_auc(edge_pos, edge_neg),
        },
        "assertion_mask_aucs": {
            "mask_on_route": rank_auc(mask_route_pos, mask_route_neg),
            "mask_is_target": rank_auc(mask_target_pos, mask_target_neg),
        },
        "cross_checks": {
            "route_complete_vs_proof_valid_disagreements": sum(
                row["cross_check_disagreements"] for row in generated
            ),
            "reached_outside_targets": sum(
                row["reached_outside_targets"] for row in generated
            ),
        },
    }


def audit_cell(
    cell: str, *, seed: bytes, count: int, gamma: float, workers: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with multiprocessing.Pool(
        workers,
        initializer=_initialise,
        initargs=(cell, seed.hex(), count, gamma),
    ) as pool:
        rows = list(pool.imap(audit_episode, range(count), chunksize=8))
    return summarize(rows, count), rows


def evaluate_gates(cells: dict[str, Any]) -> dict[str, Any]:
    low, high = AUC_BAND
    leak_ok = {}
    for name, summary in cells.items():
        aucs = summary["gamma_0.0"]["leak_aucs"]
        leak_ok[name] = all(
            value is not None and low <= value <= high
            for key, value in aucs.items()
            if key.startswith("node_")
        )
    walker_at_budget = {
        name: summary["gamma_0.0"]["coverage_gated"]["walker"]["overall"][
            str(PLANNED_BUDGET)
        ]["fraction"]
        for name, summary in cells.items()
    }
    insufficient = {
        name: value
        for name, value in walker_at_budget.items()
        if value < WALKER_INSUFFICIENT_MAX_FRACTION
    }
    exact = {name: value for name, value in walker_at_budget.items() if value == 1.0}
    disagreements = sum(
        summary[gamma]["cross_checks"]["route_complete_vs_proof_valid_disagreements"]
        + summary[gamma]["cross_checks"]["reached_outside_targets"]
        for summary in cells.values()
        for gamma in summary
        if gamma.startswith("gamma_")
    )
    rule_violations = sum(
        summary[gamma]["rule_violations_total"]
        for summary in cells.values()
        for gamma in summary
        if gamma.startswith("gamma_")
    )
    return {
        "gate_1_leak_aucs_in_band": all(leak_ok.values()),
        "gate_1_by_cell": leak_ok,
        "gate_2_walker_insufficient_cell_exists": bool(insufficient),
        "gate_2_cells": insufficient,
        "gate_3_walker_exact_cell_exists": bool(exact),
        "gate_3_cells": exact,
        "gate_4_zero_disagreements": disagreements == 0,
        "gate_4_disagreements": disagreements,
        "rule_violations_total": rule_violations,
        "walker_route_complete_at_planned_budget": walker_at_budget,
        "planned_budget": PLANNED_BUDGET,
        "walker_insufficient_threshold": WALKER_INSUFFICIENT_MAX_FRACTION,
        "all_gates_pass": (
            all(leak_ok.values())
            and bool(insufficient)
            and bool(exact)
            and disagreements == 0
            and rule_violations == 0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", nargs="*", default=sorted(CELLS))
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--gammas", nargs="*", type=float, default=[0.0, 0.4])
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--seed-label", default="track-o-v2-cell-audit")
    parser.add_argument("--rows", default=None, help="optional private row dump")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    seed = hashlib.sha256(args.seed_label.encode()).digest()
    started = datetime.now(UTC).replace(microsecond=0).isoformat()
    cells: dict[str, Any] = {}
    rows_file = None
    if args.rows:
        rows_path = Path(args.rows)
        rows_path.parent.mkdir(parents=True, exist_ok=True)
        rows_file = rows_path.open("w", encoding="utf-8")
    try:
        for cell in args.cells:
            cells[cell] = {"config": CELLS[cell].label()}
            for gamma in args.gammas:
                summary, rows = audit_cell(
                    cell,
                    seed=seed,
                    count=args.count,
                    gamma=gamma,
                    workers=args.workers,
                )
                cells[cell][f"gamma_{gamma}"] = summary
                if rows_file is not None:
                    for row in rows:
                        rows_file.write(
                            json.dumps(
                                {"cell": cell, "gamma": gamma, **row}, sort_keys=True
                            )
                            + "\n"
                        )
                print(
                    f"{cell} gamma={gamma}: gated {summary['gated_non_abstain']}, "
                    f"walker@{PLANNED_BUDGET} "
                    f"{summary['coverage_gated']['walker']['overall'][str(PLANNED_BUDGET)]['fraction']:.4f}, "
                    f"pool@{PLANNED_BUDGET} "
                    f"{summary['coverage_gated']['pool']['overall'][str(PLANNED_BUDGET)]['fraction']:.4f}, "
                    f"fail {summary['generation_failure_fraction']:.3f}",
                    flush=True,
                )
    finally:
        if rows_file is not None:
            rows_file.close()
            Path(args.rows).chmod(0o600)

    record = {
        "record_kind": "read_run_v2_cell_audit",
        "started_at": started,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "seed_label": args.seed_label,
        "episodes_per_cell_per_gamma": args.count,
        "gammas": args.gammas,
        "prefix_budgets": list(PREFIX_BUDGETS),
        "planned_budget": PLANNED_BUDGET,
        "auc_band": list(AUC_BAND),
        "gated_stratum": GATED,
        "touches_holdout": False,
        "cells": cells,
        "gates": evaluate_gates(cells),
    }
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
    print(json.dumps(record["gates"], indent=2))


if __name__ == "__main__":
    main()
