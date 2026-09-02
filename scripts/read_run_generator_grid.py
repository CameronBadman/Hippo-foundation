"""The generator-knob grid: where does the relation-prefix ceiling stop fitting?

`ceiling_sweep.json` showed that on the frozen generator every relation-reading
walker is route-complete within 16 examined edges at every gamma, so a learned
arm that saturates at B=128 is right-censored (Amendment 10 §6). This script
measures which generator knobs move that ceiling, as preparation for a harder
generator, and informs nothing in Amendment 10.

It generates episodes under a **public diagnostic seed** (the SHA-256 of a fixed
string, printed in the output) with the module constants `OUT_DEGREE`,
`MAX_PATH_LENGTH` and `MAX_NODES` patched per grid cell in the worker process.
The frozen module is never edited; the patched values are recorded beside every
cell. Nothing here touches a real split, a real seed, or the holdout.

Per cell and gamma it records the generation failure rate with the
generator's own rejection messages (the two-path uniqueness invariant and the
per-state greedy-distractor invariant both depend on out-degree), edges per
episode, the relation-prefix tree size distribution, and DIRECT-pool and greedy
route-completeness at B in {64, 128, 256}. Budget 256 is diagnostic-only, as in
`read_run_ceiling_sweep.py`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path
from typing import Any

from hippocampus_foundation.read_run import generator
from hippocampus_foundation.read_run.coverage import (
    relation_prefix_tree,
    route_coverage,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.generator import GenerationError, generate_episode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_ceiling_sweep import (  # noqa: E402
    _direct_set,
    _distribution,
    _fraction,
    _greedy_set,
    _patch_budget_candidates,
    reachable_edge_ids,
)

DIAGNOSTIC_SEED_LABEL = "hf-read-run generator-grid diagnostic seed"
DIAGNOSTIC_SEED = hashlib.sha256(DIAGNOSTIC_SEED_LABEL.encode()).digest()

OUT_DEGREES = (2, 3, 4, 6)
MAX_PATH_LENGTHS = (6, 8)
MAX_NODE_COUNTS = (256, 512)
GAMMAS = (0.0, 0.4)
BUDGETS = (64, 128, 256)
FROZEN = {
    "OUT_DEGREE": generator.OUT_DEGREE,
    "MAX_PATH_LENGTH": generator.MAX_PATH_LENGTH,
    "MAX_NODES": generator.MAX_NODES,
}

Config = tuple[int, int, int]


def config_key(config: Config) -> str:
    out_degree, max_path_length, max_nodes = config
    return f"deg{out_degree}_len{max_path_length}_nodes{max_nodes}"


def _apply_config(config: Config) -> None:
    """Patch the generator's knobs in this worker only. Diagnostic; never official."""

    generator.OUT_DEGREE, generator.MAX_PATH_LENGTH, generator.MAX_NODES = config


def _episode_row(episode: Any, budgets: tuple[int, ...]) -> dict[str, Any]:
    visible = episode.visible
    tree = relation_prefix_tree(visible)
    tree_cov = route_coverage(episode, sorted(tree))
    row: dict[str, Any] = {
        "failed": False,
        "stratum": coverage_stratum(target_hop_distance(episode)),
        "abstain": episode.hidden["abstain"],
        "path_length": len(visible["query_relations"]),
        "node_count": visible["node_count"],
        "edge_count": len(visible["edges"]),
        "reachable_edge_count": len(reachable_edge_ids(visible)),
        "tree_size": len(tree),
        "tree_route_complete": tree_cov["route_complete"],
        "budgets": {},
    }
    for budget in budgets:
        direct_ids, direct_exhausted = _direct_set(visible, budget)
        greedy_ids, greedy_exhausted = _greedy_set(visible, budget)
        direct_cov = route_coverage(episode, direct_ids)
        greedy_cov = route_coverage(episode, greedy_ids)
        row["budgets"][str(budget)] = {
            "direct": {
                "route_complete": direct_cov["route_complete"],
                "target_node_present": direct_cov["target_node_present"],
                "exhausted": direct_exhausted,
            },
            "greedy": {
                "route_complete": greedy_cov["route_complete"],
                "target_node_present": greedy_cov["target_node_present"],
                "reaches_some_target": greedy_cov["reaches_some_target"],
                "exhausted": greedy_exhausted,
            },
        }
    return row


def _run_chunk(
    spec: tuple[Config, float, int, int, int, tuple[int, ...]],
) -> tuple[Config, float, list[dict[str, Any]]]:
    config, gamma, start, stop, count, budgets = spec
    _apply_config(config)
    rows: list[dict[str, Any]] = []
    for index in range(start, stop):
        try:
            episode = generate_episode(
                DIAGNOSTIC_SEED,
                split="test-fixture",
                index=index,
                count=count,
                gamma=gamma,
            )
        except GenerationError as error:
            rows.append({"failed": True, "message": str(error)})
            continue
        rows.append(_episode_row(episode, budgets))
    return config, gamma, rows


def _dist(values: list[int]) -> dict[str, Any]:
    return _distribution(values) if values else {"n": 0}


def _arm_summary(rows: list[dict[str, Any]], budget: str, arm: str) -> dict[str, Any]:
    cells = [row["budgets"][budget][arm] for row in rows]
    total = len(cells)
    summary = {
        "route_complete": _fraction(
            sum(cell["route_complete"] for cell in cells), total
        ),
        "target_node_present": _fraction(
            sum(cell["target_node_present"] for cell in cells), total
        ),
        "exhausted": sum(cell["exhausted"] for cell in cells),
    }
    if arm == "greedy":
        summary["reaches_some_target"] = _fraction(
            sum(cell["reaches_some_target"] for cell in cells), total
        )
    return summary


def _cell_summary(
    rows: list[dict[str, Any]], budgets: tuple[int, ...]
) -> dict[str, Any]:
    generated = [row for row in rows if not row["failed"]]
    failures = Counter(row["message"] for row in rows if row["failed"])
    gated = [
        row for row in generated if row["stratum"] == "hops_2_4" and not row["abstain"]
    ]
    summary: dict[str, Any] = {
        "attempted": len(rows),
        "generated": len(generated),
        "generation_failures": sum(failures.values()),
        "generation_failure_rate": sum(failures.values()) / len(rows) if rows else None,
        "generation_failure_messages": dict(failures),
        "gated_non_abstain": len(gated),
        "gated_fraction": len(gated) / len(generated) if generated else None,
        "stratum_counts": dict(Counter(row["stratum"] for row in generated)),
        "path_length_counts": {
            str(k): v
            for k, v in sorted(Counter(row["path_length"] for row in generated).items())
        },
        "node_count": _dist([row["node_count"] for row in generated]),
        "edge_count": _dist([row["edge_count"] for row in generated]),
        "reachable_edge_count": _dist(
            [row["reachable_edge_count"] for row in generated]
        ),
        "tree_size_all_strata": _dist([row["tree_size"] for row in generated]),
        "tree_size_gated": _dist([row["tree_size"] for row in gated]),
        "tree_route_complete_all_strata": _fraction(
            sum(row["tree_route_complete"] for row in generated), len(generated)
        ),
        "gated": {},
        "all_strata": {},
    }
    for budget in budgets:
        key = str(budget)
        for label, subset in (("gated", gated), ("all_strata", generated)):
            summary[label][key] = {
                "direct": _arm_summary(subset, key, "direct"),
                "greedy": _arm_summary(subset, key, "greedy"),
                "relation_tree_within_budget": _fraction(
                    sum(row["tree_size"] <= budget for row in subset), len(subset)
                ),
            }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--chunk", type=int, default=100)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rows-output", default=None)
    args = parser.parse_args()

    configs: list[Config] = list(
        product(OUT_DEGREES, MAX_PATH_LENGTHS, MAX_NODE_COUNTS)
    )
    specs = [
        (config, gamma, start, min(start + args.chunk, args.count), args.count, BUDGETS)
        for config in configs
        for gamma in GAMMAS
        for start in range(0, args.count, args.chunk)
    ]
    collected: dict[tuple[Config, float], list[dict[str, Any]]] = {
        (config, gamma): [] for config in configs for gamma in GAMMAS
    }
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=args.workers,
        mp_context=context,
        initializer=_patch_budget_candidates,
        initargs=(BUDGETS,),
    ) as pool:
        for config, gamma, rows in pool.map(_run_chunk, specs):
            collected[(config, gamma)].extend(rows)

    result: dict[str, Any] = {
        "diagnostic_seed_label": DIAGNOSTIC_SEED_LABEL,
        "diagnostic_seed_sha256": hashlib.sha256(DIAGNOSTIC_SEED).hexdigest(),
        "split": "test-fixture",
        "count_per_cell": args.count,
        "gammas": list(GAMMAS),
        "budgets": list(BUDGETS),
        "diagnostic_only_budgets": [
            b for b in BUDGETS if b not in generator.BUDGET_CANDIDATES
        ],
        "frozen_generator_values": FROZEN,
        "frozen_config_key": config_key(
            (FROZEN["OUT_DEGREE"], FROZEN["MAX_PATH_LENGTH"], FROZEN["MAX_NODES"])
        ),
        "cells": {},
    }
    for config in configs:
        out_degree, max_path_length, max_nodes = config
        cell: dict[str, Any] = {
            "OUT_DEGREE": out_degree,
            "MAX_PATH_LENGTH": max_path_length,
            "MAX_NODES": max_nodes,
            "by_gamma": {
                f"{gamma:.1f}": _cell_summary(collected[(config, gamma)], BUDGETS)
                for gamma in GAMMAS
            },
        }
        result["cells"][config_key(config)] = cell

    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True))
    if args.rows_output:
        with Path(args.rows_output).open("w") as handle:
            for (config, gamma), rows in collected.items():
                for index, row in enumerate(rows):
                    handle.write(
                        json.dumps(
                            {
                                "config": config_key(config),
                                "gamma": gamma,
                                "index": index,
                                **row,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
    for key, cell in result["cells"].items():
        for gamma, summary in cell["by_gamma"].items():
            g128 = summary["gated"]["128"]
            print(
                f"{key} g={gamma} fail={summary['generation_failure_rate']:.4f} "
                f"gated={summary['gated_non_abstain']} "
                f"edges={summary['edge_count'].get('median')} "
                f"tree_p95={summary['tree_size_gated'].get('p95')} "
                f"direct128={g128['direct']['route_complete']['fraction']} "
                f"greedy128={g128['greedy']['route_complete']['fraction']}"
            )


if __name__ == "__main__":
    main()
