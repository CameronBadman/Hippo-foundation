"""Budget sweep of the three model-free coverage ceilings, on spent v1 screening data.

For every gamma bucket and every requested budget it measures, per episode:

* DIRECT's fixed structural pool — route-complete, and gate 7's weaker
  target-node-present;
* the similarity-greedy walk — route-complete, reaches-some-target, exact-set
  correct;
* the relation-prefix tree (`coverage.relation_prefix_tree`), whose size is
  the budget at which a relation-following walker with no lookahead is
  route-complete with certainty, whatever the gamma.

Budgets above 128 are outside `BUDGET_CANDIDATES`, and both
`generator.structural_bfs_pool` and `greedy.greedy_examined_set` refuse them.
Neither module is edited: each worker process patches the two module-level
tuples in its initializer. **Diagnostic only.** Nothing here is an admissible
budget for a preregistered run; the preregistered candidates are unchanged.

When a walk exhausts its frontier before spending the budget, its examined set
is the closure of every edge reachable from the start node — both walks expand
every out-edge of every node they visit — so the closure is substituted,
the row is marked `exhausted`, and its coverage is measured rather than
assumed. The route-completeness predicate is cross-checked against the
evaluator's `proof_valid` on every row, exhausted rows included.

Read-only. Screening split only; the holdout is neither opened nor referenced.
Per-episode rows carry hidden-derived fields and go under `private/`.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path
from typing import Any

from hippocampus_foundation.read_run import generator, greedy
from hippocampus_foundation.read_run.coverage import (
    relation_prefix_tree,
    route_coverage,
)
from hippocampus_foundation.read_run.errors import ReadRunError
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.generator import GenerationError
from hippocampus_foundation.read_run.io import read_generated_split

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_learning_probe import wilson_lower_bound  # noqa: E402

GAMMAS = (0.0, 0.1, 0.2, 0.3, 0.4)
DEFAULT_BUDGETS = (16, 32, 64, 128, 256, 384, 512, 768)
GATED_STRATUM = "hops_2_4"
# Captured before any patching so the report names the real preregistered set.
PREREGISTERED_BUDGETS = tuple(generator.BUDGET_CANDIDATES)


def _patch_budget_candidates(budgets: tuple[int, ...]) -> None:
    """Admit the diagnostic budgets in this process only. Never on an official path."""

    admitted = tuple(sorted(set(generator.BUDGET_CANDIDATES) | set(budgets)))
    generator.BUDGET_CANDIDATES = admitted
    greedy.BUDGET_CANDIDATES = admitted


def reachable_edge_ids(visible: dict[str, Any]) -> list[int]:
    """Every edge reachable from the start node: what an exhausted walk examined."""

    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)
    seen = {visible["start_node"]}
    queue = [visible["start_node"]]
    edges: list[int] = []
    while queue:
        node = queue.pop(0)
        for edge in by_source[node]:
            edges.append(edge["edge_id"])
            if edge["target"] not in seen:
                seen.add(edge["target"])
                queue.append(edge["target"])
    return sorted(edges)


def _direct_set(visible: dict[str, Any], budget: int) -> tuple[list[int], bool]:
    try:
        return generator.structural_bfs_pool(visible, budget), False
    except GenerationError as error:
        if "could not expose" not in str(error):
            raise
        return reachable_edge_ids(visible), True


def _greedy_set(visible: dict[str, Any], budget: int) -> tuple[list[int], bool]:
    try:
        return greedy.greedy_examined_set(visible, budget), False
    except ReadRunError as error:
        if "exhausted" not in str(error):
            raise
        return reachable_edge_ids(visible), True


def _arm_row(
    episode: Any, examined: list[int], exhausted: bool, predicted_class: int
) -> dict[str, Any]:
    coverage = route_coverage(episode, examined)
    scored = score_prediction(
        episode,
        predicted_class=predicted_class,
        recorded_routes=decode_best_routes(
            episode.visible, examined, [0.0] * len(examined)
        ),
    )
    return {
        "examined": len(examined),
        "exhausted": exhausted,
        "route_complete": coverage["route_complete"],
        "target_node_present": coverage["target_node_present"],
        "reaches_some_target": coverage["reaches_some_target"],
        "reached_outside": bool(coverage["reached_outside_targets"]),
        "proof_valid": scored["proof_valid"],
        "class_correct": scored["class_correct"],
        "exact_correct": scored["exact_correct"],
    }


def _episode_row(episode: Any, budgets: tuple[int, ...]) -> dict[str, Any]:
    visible = episode.visible
    tree = relation_prefix_tree(visible)
    tree_cov = route_coverage(episode, sorted(tree))
    row: dict[str, Any] = {
        "stratum": coverage_stratum(target_hop_distance(episode)),
        "abstain": episode.hidden["abstain"],
        "path_length": len(visible["query_relations"]),
        "edge_count": len(visible["edges"]),
        "reachable_edge_count": len(reachable_edge_ids(visible)),
        "tree_size": len(tree),
        "tree_route_complete": tree_cov["route_complete"],
        "tree_reached_outside": bool(tree_cov["reached_outside_targets"]),
        "budgets": {},
    }
    for budget in budgets:
        pool, pool_exhausted = _direct_set(visible, budget)
        walk, walk_exhausted = _greedy_set(visible, budget)
        row["budgets"][str(budget)] = {
            "direct": _arm_row(episode, pool, pool_exhausted, 0),
            "greedy": _arm_row(
                episode,
                walk,
                walk_exhausted,
                greedy.greedy_predicted_class(visible, walk),
            ),
        }
    return row


def _run_chunk(
    spec: tuple[str, float, int, int, tuple[int, ...]],
) -> tuple[float, int, list[dict[str, Any]]]:
    root, gamma, start, stop, budgets = spec
    episodes = islice(read_generated_split(Path(root)), start, stop)
    return gamma, start, [_episode_row(episode, budgets) for episode in episodes]


def _fraction(hits: int, total: int) -> dict[str, Any]:
    return {
        "n": total,
        "count": hits,
        "fraction": hits / total if total else None,
        "wilson_lower_bound": wilson_lower_bound(hits, total) if total else None,
    }


def _count(rows: list[dict[str, Any]], predicate: Any) -> dict[str, Any]:
    return _fraction(sum(bool(predicate(row)) for row in rows), len(rows))


def _budget_summary(rows: list[dict[str, Any]], budget: str) -> dict[str, Any]:
    def arm(name: str, key: str) -> Any:
        return lambda row: row["budgets"][budget][name][key]

    return {
        "direct": {
            "route_complete": _count(rows, arm("direct", "route_complete")),
            "target_node_present": _count(rows, arm("direct", "target_node_present")),
            "exhausted": sum(
                row["budgets"][budget]["direct"]["exhausted"] for row in rows
            ),
        },
        "greedy": {
            "route_complete": _count(rows, arm("greedy", "route_complete")),
            "target_node_present": _count(rows, arm("greedy", "target_node_present")),
            "reaches_some_target": _count(rows, arm("greedy", "reaches_some_target")),
            "exact_set_accuracy": _count(rows, arm("greedy", "exact_correct")),
            "class_correct": _count(rows, arm("greedy", "class_correct")),
            "exhausted": sum(
                row["budgets"][budget]["greedy"]["exhausted"] for row in rows
            ),
        },
        "relation_tree_within_budget": _count(
            rows, lambda row: row["tree_size"] <= int(budget)
        ),
    }


def _distribution(values: list[int]) -> dict[str, Any]:
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "min": ordered[0],
        "p25": ordered[n // 4],
        "median": ordered[n // 2],
        "p75": ordered[(3 * n) // 4],
        "p95": ordered[min(n - 1, (95 * n) // 100)],
        "max": ordered[-1],
        "mean": sum(ordered) / n,
    }


def _reproduction_check(result: dict[str, Any], reference: Path) -> dict[str, Any]:
    """B=128 must reproduce the earlier single-budget run exactly, count for count."""

    earlier = json.loads(reference.read_text())
    budget = str(earlier["budget"])
    mismatches = []
    for gamma_key, earlier_cell in earlier["by_gamma"].items():
        cell = result["by_gamma"][gamma_key]
        pairs = {
            "gated_non_abstain": (
                earlier_cell["gated_non_abstain"],
                cell["gated_non_abstain"],
            ),
            "direct_route_complete": (
                earlier_cell["direct"]["route_complete"]["count"],
                cell["gated"][budget]["direct"]["route_complete"]["count"],
            ),
            "greedy_route_complete": (
                earlier_cell["greedy"]["route_complete"]["count"],
                cell["gated"][budget]["greedy"]["route_complete"]["count"],
            ),
            "greedy_exact_set": (
                earlier_cell["greedy"]["exact_set_accuracy"]["count"],
                cell["gated"][budget]["greedy"]["exact_set_accuracy"]["count"],
            ),
        }
        for name, (expected, observed) in pairs.items():
            if expected != observed:
                mismatches.append(
                    {
                        "gamma": gamma_key,
                        "field": name,
                        "reference": expected,
                        "observed": observed,
                    }
                )
    return {
        "reference": str(reference),
        "budget": int(budget),
        "reproduced": not mismatches,
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--budgets", default=",".join(str(b) for b in DEFAULT_BUDGETS))
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--chunk", type=int, default=100)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rows-output", required=True)
    parser.add_argument("--reference", default=None)
    parser.add_argument("--limit", type=int, default=None, help="episodes per bucket")
    args = parser.parse_args()

    budgets = tuple(int(b) for b in args.budgets.split(","))
    _patch_budget_candidates(budgets)
    roots = {g: f"{args.screen_root}/screen-g{int(g * 10):02d}" for g in GAMMAS}
    counts = {g: sum(1 for _ in read_generated_split(Path(roots[g]))) for g in GAMMAS}
    if args.limit:
        counts = {g: min(n, args.limit) for g, n in counts.items()}
    specs = [
        (roots[g], g, start, min(start + args.chunk, counts[g]), budgets)
        for g in GAMMAS
        for start in range(0, counts[g], args.chunk)
    ]

    context = multiprocessing.get_context("spawn")
    collected: dict[float, dict[int, list[dict[str, Any]]]] = defaultdict(dict)
    with ProcessPoolExecutor(
        max_workers=args.workers,
        mp_context=context,
        initializer=_patch_budget_candidates,
        initargs=(budgets,),
    ) as pool:
        for gamma, start, rows in pool.map(_run_chunk, specs):
            collected[gamma][start] = rows

    rows_path = Path(args.rows_output)
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    disagreements: list[dict[str, Any]] = []
    outside = 0
    tree_incomplete = 0
    result: dict[str, Any] = {
        "budgets": list(budgets),
        "preregistered_budget_candidates": list(PREREGISTERED_BUDGETS),
        "gated_stratum": GATED_STRATUM,
        "by_gamma": {},
    }
    with rows_path.open("w") as handle:
        for gamma in GAMMAS:
            rows = [
                row
                for start in sorted(collected[gamma])
                for row in collected[gamma][start]
            ]
            for index, row in enumerate(rows):
                handle.write(json.dumps({"gamma": gamma, "index": index, **row}) + "\n")
                if not row["tree_route_complete"]:
                    tree_incomplete += 1
                if row["tree_reached_outside"]:
                    outside += 1
                for budget, arms in row["budgets"].items():
                    for arm, cell in arms.items():
                        if cell["route_complete"] != cell["proof_valid"]:
                            disagreements.append(
                                {
                                    "gamma": gamma,
                                    "index": index,
                                    "budget": budget,
                                    "arm": arm,
                                }
                            )
                        if cell["reached_outside"]:
                            outside += 1

            gated = [
                row
                for row in rows
                if row["stratum"] == GATED_STRATUM and not row["abstain"]
            ]
            by_length: dict[str, Any] = {}
            for length in sorted({row["path_length"] for row in gated}):
                subset = [row for row in gated if row["path_length"] == length]
                by_length[str(length)] = {
                    "n": len(subset),
                    "tree_size": _distribution([row["tree_size"] for row in subset]),
                    "budgets": {
                        str(b): _budget_summary(subset, str(b)) for b in budgets
                    },
                }
            result["by_gamma"][f"{gamma:.1f}"] = {
                "episode_count": len(rows),
                "gated_non_abstain": len(gated),
                "tree_size": _distribution([row["tree_size"] for row in gated]),
                "tree_size_all_strata": _distribution(
                    [row["tree_size"] for row in rows]
                ),
                "path_length_counts": dict(
                    sorted(Counter(str(row["path_length"]) for row in gated).items())
                ),
                "reachable_edge_count": _distribution(
                    [row["reachable_edge_count"] for row in rows]
                ),
                "gated": {str(b): _budget_summary(gated, str(b)) for b in budgets},
                "all_strata": {str(b): _budget_summary(rows, str(b)) for b in budgets},
                "gated_by_path_length": by_length,
            }

    result["cross_check"] = {
        "route_complete_vs_proof_valid_disagreements": len(disagreements),
        "relation_tree_not_route_complete": tree_incomplete,
        "reached_outside_targets_violations": outside,
        "examples": disagreements[:5],
    }
    if args.reference:
        result["reproduction_check"] = _reproduction_check(result, Path(args.reference))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result["cross_check"], indent=2, sort_keys=True))
    if args.reference:
        print(json.dumps(result["reproduction_check"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
