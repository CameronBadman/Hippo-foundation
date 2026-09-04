"""Choose generator v3.2's distractor evidence rate, by a rule written before it runs.

`read_run_v3_gamma_sweep.py` established that on v3 data the planted similarity
signal cannot separate a target route from its distractor at any gamma
(identifiability <= 0.38, ties >= 0.61), for two structural reasons: the
distractor shares the target's promoted prefix, and the two targets' branch node
promotes exactly one continuation, leaving one target with an unpromoted edge that
a late-branching distractor ties. Generator v3.2 removes both — distractors leave
from the start node, and their interior nodes are promoted at their own rate
`1 - distractor_gamma`.

This sweep measures, at gamma = 0.4 (fixed by Track O's band-width rule), for
each `distractor_gamma` in the preregistered grid and each cell:

1. **Identifiability** — fraction of episodes on which the worst target route
   out-ranks the best distractor route by promoted-edge fraction; and ties.
2. **Ladder gate 1** — `stop_aware` registers both targets on <= 0.90 of episodes,
   so the constant-2 stop remains a real decision (Track P's premise).
3. **Ordering room** — median blind-walker minus median oracle expansions
   (gate 2, >= 2), and similarity-following expansions at registration.

**The rule.** Track Q runs at the **smallest `distractor_gamma`** — the hardest
setting, nearest the target rate — **with identifiability >= 0.80, ties <= 0.10,
gate 1 passing, and ordering room >= 2, all on the hard cell.** If none passes,
that is the finding and Track Q does not run on v3.2 until the generator is
revisited. Gated `hops_2_4`; abstain included (nothing here reads a mask).
Generates in memory; writes no split; touches no holdout.
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
    wilson_upper_bound,
)
from hippocampus_foundation.read_run.generator_v2 import (  # noqa: E402
    SIMILARITY_WINNER_PPM,
)
from hippocampus_foundation.read_run.generator_v3_2 import (  # noqa: E402
    CELLS_V32,
    DISTRACTOR_GAMMA_GRID,
    generate_episode_v3_2,
)
from hippocampus_foundation.read_run.policies_v3 import (  # noqa: E402
    blind_exhaust_trace,
    oracle_trace,
    policy_row_v3,
    similarity_exhaust_trace,
    stop_aware_trace,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_v2_cell_audit import _distribution, _fraction  # noqa: E402

GATED = "hops_2_4"
GAMMA = 0.4
BASES = ("deg6_len8_v4_rep-k1", "deg3_len6_v8-k1")
HARD = "deg6_len8_v4_rep-k1"
RULE = {
    "gamma": GAMMA,
    "min_identifiability": 0.80,
    "max_ties": 0.10,
    "gate_1_max_stop_aware_registered": 0.90,
    "gate_1_max_wilson_upper": 0.95,
    "min_ordering_room": 2,
    "choose": "smallest distractor_gamma satisfying all four on the hard cell",
}
_CONTEXT: dict[str, Any] = {}


def _cell(base: str, dg: float) -> str:
    return f"{base}-b0-dg{int(round(dg * 10)):02d}"


def _initialise(cell: str, seed_hex: str, count: int) -> None:
    _CONTEXT.update(cell=cell, seed=bytes.fromhex(seed_hex), count=count)


def sweep_episode(index: int) -> dict[str, Any] | None:
    try:
        episode = generate_episode_v3_2(
            _CONTEXT["seed"],
            config=CELLS_V32[_CONTEXT["cell"]],
            split="test-fixture",
            index=index,
            count=_CONTEXT["count"],
            gamma=GAMMA,
            gold_mask=None if index % 4 == 0 else 1 + (index % 15),
        )
    except GenerationError:
        return {"generated": False}
    if coverage_stratum(target_hop_distance(episode)) != GATED:
        return {"generated": True, "gated": False}
    by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}

    def promoted(route: list[int]) -> float:
        return sum(
            by_id[e]["query_similarity_ppm"] == SIMILARITY_WINNER_PPM for e in route
        ) / len(route)

    worst_target = min(promoted(r) for r in episode.hidden["valid_routes"])
    best_distractor = max(promoted(r) for r in episode.hidden["distractor_routes"])
    similarity = policy_row_v3(episode, similarity_exhaust_trace(episode.visible))
    stop_aware = policy_row_v3(episode, stop_aware_trace(episode.visible))
    return {
        "generated": True,
        "gated": True,
        "separates": worst_target > best_distractor,
        "tie": worst_target == best_distractor,
        "stop_aware_registered": bool(stop_aware["targets_registered"]),
        "stop_aware_expansions": stop_aware["expansions"],
        "walker_expansions": policy_row_v3(
            episode, blind_exhaust_trace(episode.visible)
        )["expansions"],
        "oracle_expansions": policy_row_v3(episode, oracle_trace(episode))[
            "expansions"
        ],
        "similarity_expansions_at_rc": (
            similarity["expansions_at_rc"]
            if similarity["expansions_at_rc"] is not None
            else similarity["expansions"]
        ),
    }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    generated = sum(r["generated"] for r in results)
    rows = [r for r in results if r.get("gated")]
    n = len(rows)
    walker = _distribution([r["walker_expansions"] for r in rows])
    oracle = _distribution([r["oracle_expansions"] for r in rows])
    registered = sum(r["stop_aware_registered"] for r in rows)
    return {
        "generation_success": _fraction(generated, len(results)),
        "gated": n,
        "identifiability": sum(r["separates"] for r in rows) / n,
        "ties": sum(r["tie"] for r in rows) / n,
        "stop_aware_registered": _fraction(registered, n),
        "stop_aware_registered_wilson_upper": wilson_upper_bound(registered, n),
        "stop_aware_expansions": _distribution(
            [r["stop_aware_expansions"] for r in rows]
        ),
        "walker_expansions": walker,
        "oracle_expansions": oracle,
        "ordering_room_median": walker["median"] - oracle["median"],
        "similarity_expansions_at_rc": _distribution(
            [r["similarity_expansions_at_rc"] for r in rows]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--seed-label", default="track-q-v3-2-evidence-sweep")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    seed = hashlib.sha256(args.seed_label.encode()).digest()
    started = datetime.now(UTC).replace(microsecond=0).isoformat()

    cells: dict[str, dict[str, Any]] = {}
    for base in BASES:
        cells[base] = {}
        for dg in DISTRACTOR_GAMMA_GRID:
            cell = _cell(base, dg)
            with multiprocessing.Pool(
                args.workers,
                initializer=_initialise,
                initargs=(cell, seed.hex(), args.count),
            ) as pool:
                results = list(pool.imap(sweep_episode, range(args.count), chunksize=8))
            summary = summarise(results)
            cells[base][f"dg_{dg}"] = summary
            print(
                f"{cell}: gen={summary['generation_success']['fraction']:.3f} "
                f"n={summary['gated']} ident={summary['identifiability']:.3f} "
                f"ties={summary['ties']:.3f} "
                f"stop_aware_reg={summary['stop_aware_registered']['fraction']:.3f} "
                f"room={summary['ordering_room_median']} "
                f"(walker {summary['walker_expansions']['median']}, "
                f"oracle {summary['oracle_expansions']['median']}, "
                f"sim@RC {summary['similarity_expansions_at_rc']['median']})",
                flush=True,
            )

    def passes(summary: dict[str, Any]) -> bool:
        return (
            summary["identifiability"] >= RULE["min_identifiability"]
            and summary["ties"] <= RULE["max_ties"]
            and summary["stop_aware_registered"]["fraction"]
            <= RULE["gate_1_max_stop_aware_registered"]
            and summary["stop_aware_registered_wilson_upper"]
            < RULE["gate_1_max_wilson_upper"]
            and summary["ordering_room_median"] >= RULE["min_ordering_room"]
        )

    passing = [dg for dg in DISTRACTOR_GAMMA_GRID if passes(cells[HARD][f"dg_{dg}"])]
    chosen = min(passing) if passing else None
    record = {
        "record_kind": "read_run_v3_2_evidence_sweep",
        "started_at": started,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "seed_label": args.seed_label,
        "episodes_per_cell_per_point": args.count,
        "distractor_gamma_grid": list(DISTRACTOR_GAMMA_GRID),
        "gated_stratum": GATED,
        "abstain_included": True,
        "touches_holdout": False,
        "rule": RULE,
        "cells": cells,
        "passing_hard_cell": passing,
        "chosen_distractor_gamma": chosen,
        "v3_reference": {
            "identifiability_at_gamma_0_4": 0.229,
            "ties_at_gamma_0_4": 0.662,
            "source": "experiments/track_q_v1/diagnostics/gamma_sweep_v3.json",
        },
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
    print()
    print(json.dumps({"passing": passing, "chosen_distractor_gamma": chosen}))


if __name__ == "__main__":
    main()
