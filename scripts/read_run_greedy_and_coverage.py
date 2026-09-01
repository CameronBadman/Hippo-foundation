"""Tracks A, B and C of the E1-v2 overnight run, on already-spent v1 screening data.

Computes, per gamma bucket and per arm, on the gated `hops_2_4` stratum:

* route-completeness (`coverage.route_coverage`), the coverage proof-valid
  scoring actually requires, beside gate 7's weaker target-node-present number;
* the greedy baseline's examined set, predicted class and exact-set accuracy,
  which need no model and no GPU;
* an episode-by-episode cross-check of the structural route-completeness
  predicate against the evaluator's own `proof_valid` flag.

Read-only. Screening split only; the holdout is neither opened nor referenced.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from hippocampus_foundation.read_run.coverage import (
    route_coverage,
    summarize_route_coverage,
)
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.generator import structural_bfs_pool
from hippocampus_foundation.read_run.greedy import greedy_predict
from hippocampus_foundation.read_run.io import read_generated_split

# Imported from the probe rather than reimplemented so the bound reported here
# is byte-identical to the one every probe checkpoint was scored with.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_learning_probe import wilson_lower_bound  # noqa: E402

GAMMAS = (0.0, 0.1, 0.2, 0.3, 0.4)


def _episode_row(episode: Any, budget: int) -> dict[str, Any]:
    """Everything measurable about one episode without a trained model."""

    stratum = coverage_stratum(target_hop_distance(episode))
    pool = structural_bfs_pool(episode.visible, budget)
    greedy = greedy_predict(episode, budget)

    direct_cov = route_coverage(episode, pool)
    greedy_cov = route_coverage(episode, greedy["examined_edge_ids"])

    # Cross-check: proof_valid is score-independent (at most one
    # relation-matching route reaches each endpoint), so any score vector
    # exercises the same decoder path. Zeros keep that explicit.
    direct_proof = score_prediction(
        episode,
        predicted_class=0,
        recorded_routes=decode_best_routes(episode.visible, pool, [0.0] * len(pool)),
    )["proof_valid"]
    greedy_scored = score_prediction(
        episode,
        predicted_class=greedy["predicted_class"],
        recorded_routes=decode_best_routes(
            episode.visible, greedy["examined_edge_ids"], greedy["scores"]
        ),
    )

    return {
        "stratum": stratum,
        "abstain": episode.hidden["abstain"],
        "direct_route_complete": direct_cov["route_complete"],
        "direct_target_node_present": direct_cov["target_node_present"],
        "direct_reached_outside": bool(direct_cov["reached_outside_targets"]),
        "direct_proof_valid": direct_proof,
        "greedy_route_complete": greedy_cov["route_complete"],
        "greedy_target_node_present": greedy_cov["target_node_present"],
        "greedy_reaches_some_target": greedy_cov["reaches_some_target"],
        "greedy_reached_outside": bool(greedy_cov["reached_outside_targets"]),
        "greedy_proof_valid": greedy_scored["proof_valid"],
        "greedy_class_correct": greedy_scored["class_correct"],
        "greedy_exact_correct": greedy_scored["exact_correct"],
    }


def _run_bucket(spec: tuple[str, float, int]) -> tuple[float, list[dict[str, Any]]]:
    root, gamma, budget = spec
    episodes = read_generated_split(Path(root))
    return gamma, [_episode_row(episode, budget) for episode in episodes]


def _fraction(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    total = len(rows)
    hits = sum(row[key] for row in rows)
    return {
        "n": total,
        "count": hits,
        "fraction": hits / total if total else None,
        "wilson_lower_bound": wilson_lower_bound(hits, total) if total else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--budget", type=int, default=128)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    specs = [
        (f"{args.screen_root}/screen-g{int(g * 10):02d}", g, args.budget)
        for g in GAMMAS
    ]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=context) as pool:
        collected = dict(pool.map(_run_bucket, specs))

    result: dict[str, Any] = {"budget": args.budget, "by_gamma": {}}
    disagreements: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []

    for gamma in GAMMAS:
        rows = collected[gamma]
        for index, row in enumerate(rows):
            if row["direct_route_complete"] != row["direct_proof_valid"]:
                disagreements.append(
                    {"gamma": gamma, "index": index, "arm": "DIRECT", **row}
                )
            if row["greedy_route_complete"] != row["greedy_proof_valid"]:
                disagreements.append(
                    {"gamma": gamma, "index": index, "arm": "greedy", **row}
                )
            if row["direct_reached_outside"] or row["greedy_reached_outside"]:
                outside.append({"gamma": gamma, "index": index, **row})

        gated = [
            row for row in rows if row["stratum"] == "hops_2_4" and not row["abstain"]
        ]
        result["by_gamma"][f"{gamma:.1f}"] = {
            "episode_count": len(rows),
            "gated_non_abstain": len(gated),
            "direct": {
                "route_complete": _fraction(gated, "direct_route_complete"),
                "target_node_present": _fraction(gated, "direct_target_node_present"),
            },
            "greedy": {
                "route_complete": _fraction(gated, "greedy_route_complete"),
                "target_node_present": _fraction(gated, "greedy_target_node_present"),
                "reaches_some_target": _fraction(gated, "greedy_reaches_some_target"),
                "exact_set_accuracy": _fraction(gated, "greedy_exact_correct"),
                "class_correct": _fraction(gated, "greedy_class_correct"),
            },
            "all_strata_direct_route_complete": summarize_route_coverage(
                [
                    {
                        "route_complete": row["direct_route_complete"],
                        "target_node_present": row["direct_target_node_present"],
                        "reached_outside_targets": [1]
                        if row["direct_reached_outside"]
                        else [],
                    }
                    for row in rows
                ]
            ),
        }

    result["cross_check"] = {
        "route_complete_vs_proof_valid_disagreements": len(disagreements),
        "reached_outside_targets_violations": len(outside),
        "examples": disagreements[:5] + outside[:5],
    }
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
