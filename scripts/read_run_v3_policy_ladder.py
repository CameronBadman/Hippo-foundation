"""The model-free reference Track P is read against, and the gate that fixes K.

Track O's ladder (`read_run_v2_policy_ladder.py`) measured its policies under an
edge budget. Track P removes the budget and counts expansions, so every policy
is re-measured under `policies_v3`'s shared mechanics — no budget, cost in node
expansions, endpoints registered at examination, frontier keyed by
`(edge_id, depth)` — on generator-v3 data with K planted distractor paths.

Four gates, stated here before any model exists, decide whether the experiment
can be run at all and at which K:

1. **The hard-coded stop is a real decision.** `stop_aware` — relation-gated
   similarity with a stop at two endpoints, the strongest v2 policy — must fail
   to register both targets on a material fraction of hard-cell episodes:
   fraction at most 0.90 with a Wilson upper bound below 0.95. On v2 data it is
   exact, so a learned stop there would learn the constant 2. The gate reads the
   *walk-based* quantity (`targets_registered`) rather than set-based coverage,
   because the two differ: a target's final edge can enter the examined set
   through an expansion at another depth while the walk stops before popping
   the correct-depth prefix. Set-based coverage over-credits a stop policy;
   registration is what a stop decision can see. Both are recorded.
2. **There is room to order.** The oracle (expand only route source states) must
   need at least 2 fewer expansions than the exhausted blind walker at the
   median, on the hard cell.
3. **The easy cell stays a sanity rung.** At the chosen K the easy cell must
   generate with success at least 0.5, and the exhausted walker must be
   route-complete on every gated episode there.
4. **The two coverage implementations agree.** `coverage.route_coverage_v3`'s
   `route_complete` must equal "both target routes are decodable from the
   examined set" (`evaluation_v3.decode_all_routes`) on every policy and every
   episode, with zero disagreements.

K is fixed as the **smallest K passing gates 1-3**; gate 4 must hold everywhere.
That rule is structural and is written down here, not chosen after the fact.

Generates episodes in memory. Writes no split, touches no holdout. Per-episode
records are aggregated before writing; nothing hidden-derived is stored per
episode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hippocampus_foundation.read_run.coverage import route_coverage_v3  # noqa: E402
from hippocampus_foundation.read_run.errors import GenerationError  # noqa: E402
from hippocampus_foundation.read_run.evaluation_v3 import (
    decode_all_routes,  # noqa: E402
)
from hippocampus_foundation.read_run.gates import (  # noqa: E402
    coverage_stratum,
    target_hop_distance,
    wilson_upper_bound,
)
from hippocampus_foundation.read_run.generator_v3 import (  # noqa: E402
    CELLS_V3,
    generate_episode_v3,
)
from hippocampus_foundation.read_run.policies_v3 import (  # noqa: E402
    POLICIES_V3,
    oracle_trace,
    policy_row_v3,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_v2_cell_audit import _distribution, _fraction  # noqa: E402

GATED = "hops_2_4"
GATE_1_MAX_RC = 0.90
GATE_1_MAX_UPPER = 0.95
GATE_2_MIN_ROOM = 2
GATE_3_MIN_SUCCESS = 0.5
BASE_CELLS = ("deg3_len6_v8", "deg6_len8_v4_rep")
HARD, EASY = "deg6_len8_v4_rep", "deg3_len6_v8"
_CONTEXT: dict[str, Any] = {}


def _cell_name(base: str, k: int) -> str:
    return base if k == 0 else f"{base}-k{k}"


def _initialise(cell: str, seed_hex: str, count: int, gamma: float) -> None:
    _CONTEXT.update(cell=cell, seed=bytes.fromhex(seed_hex), count=count, gamma=gamma)


def ladder_episode(index: int) -> dict[str, Any]:
    """One episode's policy rows; `generated`/`gated` flags for the denominators."""

    config = CELLS_V3[_CONTEXT["cell"]]
    try:
        episode = generate_episode_v3(
            _CONTEXT["seed"],
            config=config,
            split="test-fixture",
            index=index,
            count=_CONTEXT["count"],
            gamma=_CONTEXT["gamma"],
            gold_mask=None if index % 4 == 0 else 1 + (index % 15),
        )
    except GenerationError:
        return {"generated": False, "gated": False}
    if episode.hidden["abstain"]:
        return {"generated": True, "gated": False}
    if coverage_stratum(target_hop_distance(episode)) != GATED:
        return {"generated": True, "gated": False}

    targets = {tuple(route) for route in episode.hidden["valid_routes"]}
    policies: dict[str, Any] = {}
    disagreements = 0
    for name, policy in POLICIES_V3.items():
        trace = policy(episode.visible)
        row = policy_row_v3(episode, trace)
        decoded = {
            tuple(route)
            for route in decode_all_routes(
                episode.visible, trace.examined, [0.0] * len(trace.examined)
            )
        }
        coverage = route_coverage_v3(episode, trace.examined)["route_complete"]
        disagreements += coverage != (targets <= decoded)
        policies[name] = row
    oracle = policy_row_v3(episode, oracle_trace(episode))
    return {
        "generated": True,
        "gated": True,
        "path_length": len(episode.visible["query_relations"]),
        "policies": policies,
        "oracle_expansions": oracle["expansions"],
        "gate4_disagreements": disagreements,
    }


def _summarise_policy(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    cells = [row["policies"][name] for row in rows]
    n = len(cells)
    complete = [cell for cell in cells if cell["route_complete"]]
    registered = [cell for cell in cells if cell["targets_registered"]]
    return {
        # Set-based: both target routes lie inside the examined set.
        "route_complete": _fraction(len(complete), n),
        # Walk-based: both targets were registered along a correct-depth
        # prefix — what a stop decision can actually see. The gates use this.
        "targets_registered": _fraction(len(registered), n),
        "targets_registered_wilson_upper": wilson_upper_bound(len(registered), n),
        "complete_but_unregistered": _fraction(
            sum(cell["complete_but_unregistered"] for cell in cells), n
        ),
        "expansions": _distribution([cell["expansions"] for cell in cells]),
        "expansions_at_rc": _distribution(
            [cell["expansions_at_rc"] for cell in registered]
        ),
        "overhead_expansions_mean": (
            sum(cell["overhead_expansions"] for cell in registered) / len(registered)
            if registered
            else None
        ),
        "edges_examined_mean": sum(cell["edges_examined"] for cell in cells) / n,
        "precision_mean": sum(cell["precision"] for cell in cells) / n,
        "registered_only_targets": _fraction(
            sum(cell["registered_only_targets"] for cell in cells), n
        ),
        "distractor_endpoints_reached_mean": (
            sum(cell["distractor_endpoints_reached"] for cell in cells) / n
        ),
        "endpoints_registered_mean": (
            sum(cell["endpoints_registered"] for cell in cells) / n
        ),
        "stop_reasons": dict(Counter(cell["stop_reason"] for cell in cells)),
    }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    generated = sum(r["generated"] for r in results)
    rows = [r for r in results if r["gated"]]
    n = len(rows)
    policies = {name: _summarise_policy(rows, name) for name in POLICIES_V3}
    oracle = _distribution([row["oracle_expansions"] for row in rows])
    walker_median = policies["blind_exhaust"]["expansions"].get("median")
    stop_aware_median = policies["stop_aware"]["expansions_at_rc"].get("median")
    return {
        "generation_success": _fraction(generated, len(results)),
        "gated_non_abstain": n,
        "path_length": _distribution([row["path_length"] for row in rows]),
        "policies": policies,
        "oracle_expansions": oracle,
        "room_walker_minus_oracle_median": (
            walker_median - oracle["median"] if n else None
        ),
        "room_stop_aware_minus_oracle_median": (
            stop_aware_median - oracle["median"]
            if n and stop_aware_median is not None
            else None
        ),
        "gate4_disagreements": sum(row["gate4_disagreements"] for row in rows),
    }


def run_cell(
    cell: str, *, seed: bytes, count: int, gamma: float, workers: int
) -> dict[str, Any]:
    with multiprocessing.Pool(
        workers, initializer=_initialise, initargs=(cell, seed.hex(), count, gamma)
    ) as pool:
        results = list(pool.imap(ladder_episode, range(count), chunksize=8))
    return summarise(results)


def evaluate_gates(cells: dict[str, Any], ks: list[int]) -> dict[str, Any]:
    per_k: dict[str, Any] = {}
    for k in ks:
        if k == 0:
            continue
        hard = cells[_cell_name(HARD, k)]
        easy = cells[_cell_name(EASY, k)]
        stop_rc = hard["policies"]["stop_aware"]["targets_registered"]["fraction"]
        stop_upper = hard["policies"]["stop_aware"]["targets_registered_wilson_upper"]
        room = hard["room_walker_minus_oracle_median"]
        easy_success = easy["generation_success"]["fraction"]
        easy_walker_rc = easy["policies"]["blind_exhaust"]["route_complete"]["fraction"]
        gates = {
            "gate_1_stop_is_a_decision": (
                stop_rc <= GATE_1_MAX_RC and stop_upper < GATE_1_MAX_UPPER
            ),
            "gate_2_room_to_order": room is not None and room >= GATE_2_MIN_ROOM,
            "gate_3_easy_is_sane": (
                easy_success >= GATE_3_MIN_SUCCESS and easy_walker_rc == 1.0
            ),
            "gate_4_coverage_agrees": (
                hard["gate4_disagreements"] == 0 and easy["gate4_disagreements"] == 0
            ),
        }
        per_k[str(k)] = {
            **gates,
            "stop_aware_rc_hard": stop_rc,
            "stop_aware_rc_upper_hard": stop_upper,
            "room_hard": room,
            "easy_success": easy_success,
            "passes_1_to_3": all(
                gates[g]
                for g in (
                    "gate_1_stop_is_a_decision",
                    "gate_2_room_to_order",
                    "gate_3_easy_is_sane",
                )
            ),
        }
    passing = [int(k) for k, v in per_k.items() if v["passes_1_to_3"]]
    gate4_everywhere = all(v["gate_4_coverage_agrees"] for v in per_k.values())
    return {
        "per_k": per_k,
        "chosen_k": min(passing) if passing else None,
        "gate_4_everywhere": gate4_everywhere,
        "rule": (
            "K is the smallest value passing gates 1-3; gate 4 must hold at every K. "
            f"Gate 1: stop_aware RC <= {GATE_1_MAX_RC} and Wilson upper < "
            f"{GATE_1_MAX_UPPER} on the hard cell. Gate 2: median(blind_exhaust "
            f"expansions) - median(oracle expansions) >= {GATE_2_MIN_ROOM} on the "
            f"hard cell. Gate 3: easy-cell generation success >= {GATE_3_MIN_SUCCESS} "
            "and blind_exhaust route-complete on every gated easy episode."
        ),
    }


def _print_table(cells: dict[str, Any]) -> None:
    print(
        f"{'cell':22s} {'gen':>5s} {'n':>5s} | {'policy':18s} {'RC':>6s} "
        f"{'exp':>5s} {'exp@RC':>6s} {'ovh':>5s} {'onlyT':>6s} {'dist':>5s} {'prec':>5s}"
    )
    for cell, summary in cells.items():
        first = True
        for name, p in summary["policies"].items():
            lead = (
                f"{cell:22s} {summary['generation_success']['fraction']:5.2f} "
                f"{summary['gated_non_abstain']:5d}"
                if first
                else " " * 34
            )
            first = False
            ovh = p["overhead_expansions_mean"]
            print(
                f"{lead} | {name:18s} {p['route_complete']['fraction']:6.3f} "
                f"{p['expansions'].get('median', 0):5d} "
                f"{p['expansions_at_rc'].get('median', 0):6d} "
                f"{(ovh if ovh is not None else 0):5.1f} "
                f"{p['registered_only_targets']['fraction']:6.3f} "
                f"{p['distractor_endpoints_reached_mean']:5.2f} "
                f"{p['precision_mean']:5.3f}"
            )
        print(
            f"{' ' * 34} | {'oracle':18s} {'1.000':>6s} "
            f"{summary['oracle_expansions'].get('median', 0):5d}   room="
            f"{summary['room_walker_minus_oracle_median']}  "
            f"gate4_disagreements={summary['gate4_disagreements']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", nargs="*", default=list(BASE_CELLS))
    parser.add_argument("--ks", nargs="*", type=int, default=[0, 1, 2, 4])
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--gamma", type=float, default=0.4)
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--seed-label", default="track-p-v3-policy-ladder")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    seed = hashlib.sha256(args.seed_label.encode()).digest()
    started = datetime.now(UTC).replace(microsecond=0).isoformat()
    cells: dict[str, Any] = {}
    for base in args.cells:
        for k in args.ks:
            cell = _cell_name(base, k)
            summary = run_cell(
                cell,
                seed=seed,
                count=args.count,
                gamma=args.gamma,
                workers=args.workers,
            )
            summary["config"] = CELLS_V3[cell].label()
            cells[cell] = summary
            print(
                f"{cell}: gen={summary['generation_success']['fraction']:.3f} "
                f"n={summary['gated_non_abstain']} "
                f"stop_aware RC={summary['policies']['stop_aware']['route_complete']['fraction']:.3f} "
                f"room={summary['room_walker_minus_oracle_median']}",
                flush=True,
            )
    gates = evaluate_gates(cells, args.ks) if set(BASE_CELLS) <= set(args.cells) else {}
    record = {
        "record_kind": "read_run_v3_policy_ladder",
        "started_at": started,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "seed_label": args.seed_label,
        "episodes_per_cell": args.count,
        "gamma": args.gamma,
        "ks": args.ks,
        "gated_stratum": GATED,
        "cost_unit": "expansions",
        "budget": None,
        "touches_holdout": False,
        "cells": cells,
        "gates": gates,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
    print()
    _print_table(cells)
    if gates:
        print()
        print(json.dumps({k: v for k, v in gates.items() if k != "rule"}, indent=1))


if __name__ == "__main__":
    main()
