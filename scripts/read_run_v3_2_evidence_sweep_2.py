"""Second evidence sweep for generator v3.2: gamma joins the grid. Rule written first.

**Why a second sweep exists, stated so it is not read as a quiet relaxation.**
The first sweep (`read_run_v3_2_evidence_sweep.py`,
`diagnostics/evidence_sweep_v3_2.json`) held gamma at 0.4 and swept only the
distractor's own rate. It did what it was built to do — identifiability rose
monotonically from v3's 0.229 to 0.807 at `distractor_gamma = 1.0` — and no point
passed its rule: ties were 0.165 against a 0.10 bound. Measured afterwards, 91 %
of those ties are episodes on which the *worst target route has zero promoted
edges*. At gamma = 0.4 a target edge is promoted 0.6 of the time, the branch-node
loser has only L-1 chances, and the gated stratum's median L is 4, so about one
episode in six has a target with no similarity evidence at all. No distractor
design can separate those; only gamma can, and the first sweep's rule fixed it.
So this is a new rule over a wider grid, and both sweeps are cited by the
preregistration.

**The grid.** gamma in {0.2, 0.3, 0.4} (Track O's band-width rule chose 0.4 for
ordering room; lower values keep more evidence on the targets) x
`distractor_gamma` in {0.8, 1.0}, both cells.

**The rule.** Track Q runs at the **largest gamma, and at that gamma the smallest
`distractor_gamma`, such that on the hard cell: identifiability >= 0.80, ties
<= 0.10, `stop_aware` registers both targets on <= 0.90 with Wilson upper
< 0.95, and ordering room (median walker minus median oracle) >= 2.** "Largest
gamma" keeps the ordering task as hard as the evidence constraint allows;
"smallest distractor_gamma" keeps the distractor as evidential as the same
constraint allows. If nothing passes, that is the finding.

Gated `hops_2_4`; abstain included. Generates in memory; writes no split;
touches no holdout.
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
GAMMAS = (0.2, 0.3, 0.4)
DISTRACTOR_GAMMAS = (0.8, 1.0)
BASES = ("deg6_len8_v4_rep-k1", "deg3_len6_v8-k1")
HARD = "deg6_len8_v4_rep-k1"
RULE = {
    "gammas": list(GAMMAS),
    "distractor_gammas": list(DISTRACTOR_GAMMAS),
    "min_identifiability": 0.80,
    "max_ties": 0.10,
    "gate_1_max_stop_aware_registered": 0.90,
    "gate_1_max_wilson_upper": 0.95,
    "min_ordering_room": 2,
    "choose": (
        "largest gamma, then smallest distractor_gamma, satisfying all four on the "
        "hard cell"
    ),
    "first_sweep": "experiments/track_q_v1/diagnostics/evidence_sweep_v3_2.json",
    "first_sweep_outcome": "no point passed at gamma 0.4; ties 0.165 at dg 1.0, "
    "91% of them episodes where the worst target has zero promoted edges",
}
_CONTEXT: dict[str, Any] = {}


def _cell(base: str, dg: float) -> str:
    return f"{base}-b0-dg{int(round(dg * 10)):02d}"


def _initialise(cell: str, seed_hex: str, count: int, gamma: float) -> None:
    _CONTEXT.update(cell=cell, seed=bytes.fromhex(seed_hex), count=count, gamma=gamma)


def sweep_episode(index: int) -> dict[str, Any]:
    try:
        episode = generate_episode_v3_2(
            _CONTEXT["seed"],
            config=CELLS_V32[_CONTEXT["cell"]],
            split="test-fixture",
            index=index,
            count=_CONTEXT["count"],
            gamma=_CONTEXT["gamma"],
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
        "worst_target_zero": worst_target == 0.0,
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
        "worst_target_zero_evidence": sum(r["worst_target_zero"] for r in rows) / n,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--seed-label", default="track-q-v3-2-evidence-sweep-2")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    seed = hashlib.sha256(args.seed_label.encode()).digest()
    started = datetime.now(UTC).replace(microsecond=0).isoformat()

    cells: dict[str, dict[str, Any]] = {}
    for base in BASES:
        cells[base] = {}
        for gamma in GAMMAS:
            for dg in DISTRACTOR_GAMMAS:
                cell = _cell(base, dg)
                with multiprocessing.Pool(
                    args.workers,
                    initializer=_initialise,
                    initargs=(cell, seed.hex(), args.count, gamma),
                ) as pool:
                    results = list(
                        pool.imap(sweep_episode, range(args.count), chunksize=8)
                    )
                summary = summarise(results)
                cells[base][f"gamma_{gamma}_dg_{dg}"] = summary
                print(
                    f"{base} gamma={gamma} dg={dg}: "
                    f"gen={summary['generation_success']['fraction']:.3f} "
                    f"n={summary['gated']} ident={summary['identifiability']:.3f} "
                    f"ties={summary['ties']:.3f} "
                    f"zero_target={summary['worst_target_zero_evidence']:.3f} "
                    f"stop_aware_reg={summary['stop_aware_registered']['fraction']:.3f} "
                    f"room={summary['ordering_room_median']} "
                    f"sim@RC={summary['similarity_expansions_at_rc']['median']} "
                    f"pass={passes(summary)}",
                    flush=True,
                )

    passing = [
        (gamma, dg)
        for gamma in GAMMAS
        for dg in DISTRACTOR_GAMMAS
        if passes(cells[HARD][f"gamma_{gamma}_dg_{dg}"])
    ]
    chosen = max(passing, key=lambda p: (p[0], -p[1])) if passing else None
    record = {
        "record_kind": "read_run_v3_2_evidence_sweep_2",
        "started_at": started,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "seed_label": args.seed_label,
        "episodes_per_point": args.count,
        "gated_stratum": GATED,
        "abstain_included": True,
        "touches_holdout": False,
        "rule": RULE,
        "cells": cells,
        "passing_hard_cell": passing,
        "chosen": {"gamma": chosen[0], "distractor_gamma": chosen[1]}
        if chosen
        else None,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
    print()
    print(json.dumps({"passing": passing, "chosen": record["chosen"]}))


if __name__ == "__main__":
    main()
