"""The model-free reference Track O is read against (phase O-3a).

Track N's near-miss: had its outcome table been written against the weakest
available reference, a mediocre learned walk would have looked like a win. This
script measures every model-free policy on the Track O cells so the O-4 outcome
table can be written against the *frontier* of what needs no learning at all.

Two quantities, because on this generator no policy leads on both:

- **route-completeness** — does the examined set contain complete routes to
  every target (`coverage.route_coverage`, equal to the evaluator's
  `proof_valid`);
- **examined-set precision** — what fraction of the examined edges lie on a
  route. This is what a write operation downstream must adjudicate, and a
  policy that always spends its budget cannot compete on it.

Also reported: the **oracle floor** (out-degree x distinct route-source nodes —
the floor no examined-set policy can beat under whole-node expansion), the
fraction of episodes where that floor fits the budget, and the resulting band
between the best model-free policy and the oracle. Whichever gamma leaves the
widest band is the setting Track O trains at; that rule is fixed here, before
any Track O model exists, and is the same coverage-only discipline that chose
the budget.

Generates episodes in memory. Writes no split, touches no holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hippocampus_foundation.read_run.errors import GenerationError  # noqa: E402
from hippocampus_foundation.read_run.gates import (  # noqa: E402
    coverage_stratum,
    target_hop_distance,
)
from hippocampus_foundation.read_run.generator_v2 import (  # noqa: E402
    CELLS,
    generate_episode_v2,
)
from hippocampus_foundation.read_run.policies_v2 import (  # noqa: E402
    POLICIES,
    oracle_floor,
    pareto_frontier,
    policy_row,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_v2_cell_audit import (  # noqa: E402
    _distribution,
    _fraction,
)

# `greedy.greedy_examined_set` is a frozen v1 module and accepts only the four
# preregistered budget candidates, so the ladder is reported on exactly those.
LADDER_BUDGETS = (16, 32, 64, 128)
PLANNED_BUDGET = 64
GATED = "hops_2_4"
GAMMAS = (0.0, 0.2, 0.4)
_CONTEXT: dict[str, Any] = {}


def _initialise(cell: str, seed_hex: str, count: int, gamma: float) -> None:
    _CONTEXT.update(cell=cell, seed=bytes.fromhex(seed_hex), count=count, gamma=gamma)


def ladder_episode(index: int) -> dict[str, Any] | None:
    """One episode's policy rows, or None when it is not a gated episode."""

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
    except GenerationError:
        return None
    if episode.hidden["abstain"]:
        return None
    if coverage_stratum(target_hop_distance(episode)) != GATED:
        return None

    row: dict[str, Any] = {
        "path_length": len(episode.visible["query_relations"]),
        "oracle_floor": oracle_floor(episode, out_degree=config.out_degree),
        "policies": {},
    }
    for name, policy in POLICIES.items():
        per_budget = {}
        for budget in LADDER_BUDGETS:
            examined = policy(episode.visible, budget)
            per_budget[str(budget)] = policy_row(episode, examined, budget=budget)
        row["policies"][name] = per_budget
    return row


def summarize(rows: list[dict[str, Any]], *, out_degree: int) -> dict[str, Any]:
    n = len(rows)
    policies: dict[str, Any] = {}
    for name in POLICIES:
        per_budget = {}
        for budget in LADDER_BUDGETS:
            cells = [row["policies"][name][str(budget)] for row in rows]
            complete = sum(cell["route_complete"] for cell in cells)
            per_budget[str(budget)] = {
                "route_complete": _fraction(complete, n),
                "precision_mean": sum(cell["precision"] for cell in cells) / n,
                "examined_mean": sum(cell["examined"] for cell in cells) / n,
                "stopped_early_fraction": sum(cell["stopped_early"] for cell in cells)
                / n,
                "precision_given_route_complete": (
                    sum(cell["precision"] for cell in cells if cell["route_complete"])
                    / complete
                )
                if complete
                else 0.0,
            }
        policies[name] = per_budget

    at_planned = {
        name: {
            "route_complete_fraction": policies[name][str(PLANNED_BUDGET)][
                "route_complete"
            ]["fraction"],
            "precision_mean": policies[name][str(PLANNED_BUDGET)]["precision_mean"],
        }
        for name in POLICIES
    }
    frontier = pareto_frontier(at_planned)
    oracle_feasible = {
        str(budget): _fraction(
            sum(1 for row in rows if row["oracle_floor"] <= budget), n
        )
        for budget in LADDER_BUDGETS
    }
    best_complete = max(
        at_planned[name]["route_complete_fraction"] for name in at_planned
    )
    return {
        "gated_non_abstain": n,
        "out_degree": out_degree,
        "oracle_floor": _distribution([row["oracle_floor"] for row in rows]),
        "oracle_feasible": oracle_feasible,
        "policies": policies,
        "at_planned_budget": at_planned,
        "pareto_frontier": frontier,
        "band_above_best_model_free_pp": 100.0
        * (oracle_feasible[str(PLANNED_BUDGET)]["fraction"] - best_complete),
        "best_model_free_route_complete": best_complete,
    }


def run_cell(
    cell: str, *, seed: bytes, count: int, gamma: float, workers: int
) -> dict[str, Any]:
    with multiprocessing.Pool(
        workers, initializer=_initialise, initargs=(cell, seed.hex(), count, gamma)
    ) as pool:
        rows = [
            row
            for row in pool.imap(ladder_episode, range(count), chunksize=8)
            if row is not None
        ]
    return summarize(rows, out_degree=CELLS[cell].out_degree)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", nargs="*", default=sorted(CELLS))
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--gammas", nargs="*", type=float, default=list(GAMMAS))
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--seed-label", default="track-o-v2-policy-ladder")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    seed = hashlib.sha256(args.seed_label.encode()).digest()
    started = datetime.now(UTC).replace(microsecond=0).isoformat()
    cells: dict[str, Any] = {}
    for cell in args.cells:
        cells[cell] = {"config": CELLS[cell].label()}
        for gamma in args.gammas:
            summary = run_cell(
                cell, seed=seed, count=args.count, gamma=gamma, workers=args.workers
            )
            cells[cell][f"gamma_{gamma}"] = summary
            frontier = ", ".join(summary["pareto_frontier"])
            print(
                f"{cell} gamma={gamma}: n={summary['gated_non_abstain']} "
                f"frontier=[{frontier}] "
                f"band={summary['band_above_best_model_free_pp']:+.1f}pp",
                flush=True,
            )

    widest = max(
        (
            (
                cells[cell][f"gamma_{gamma}"]["band_above_best_model_free_pp"],
                cell,
                gamma,
            )
            for cell in args.cells
            for gamma in args.gammas
        ),
    )
    record = {
        "record_kind": "read_run_v2_policy_ladder",
        "started_at": started,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "seed_label": args.seed_label,
        "episodes_per_cell_per_gamma": args.count,
        "gammas": args.gammas,
        "prefix_budgets": list(LADDER_BUDGETS),
        "planned_budget": PLANNED_BUDGET,
        "gated_stratum": GATED,
        "touches_holdout": False,
        "cells": cells,
        "widest_band": {
            "band_pp": widest[0],
            "cell": widest[1],
            "gamma": widest[2],
            "rule": (
                "gamma is fixed at the value leaving the widest band between the "
                "best model-free policy and the oracle floor, measured with no "
                "model in existence"
            ),
        },
    }
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
    print(json.dumps(record["widest_band"], indent=2))


if __name__ == "__main__":
    main()
