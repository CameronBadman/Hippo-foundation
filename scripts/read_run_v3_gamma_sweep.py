"""Choose Track Q's gamma for identifiability, by a rule written before the sweep runs.

Track O fixed gamma = 0.4 by the widest ordering band between the best model-free
policy and the oracle. That rule was about ordering room. It says nothing about
whether the two target routes are *identifiable* from a planted distractor route,
and Track P measured that at 0.4 they largely are not: ranking routes by the
generator's own promoted-edge fraction puts the worst target route above the best
distractor route on 24.8 % of episodes with 63.3 % ties, and simulation puts the
ceiling at 0.47 even with distractor promotion forced to zero, because a target
edge is itself promoted only 1 - gamma = 0.6 of the time.

This sweep measures, per gamma bucket and per cell, on generator-v3 data:

1. **Identifiability** — the fraction of episodes on which the worst target route
   out-ranks the best distractor route by promoted-edge fraction, and the tie
   rate. Model-free: it is the planted signal itself, and it is what gamma
   changes. (A first draft of this plan proposed a trained model's route-mean
   rule; no model exists at other gammas, so that cannot be the sweep's quantity.)
2. **Ordering room** — median `blind_exhaust` expansions minus median oracle
   expansions, the ladder's gate 2. At low gamma similarity-following approaches
   the oracle and the ordering experiment collapses, so this bounds the sweep from
   the other side.
3. **Similarity-following expansions at registration**, the same fact seen from
   the policy's side.

**The rule.** Track Q runs at the **largest gamma with identifiability >= 0.80 and
ties <= 0.10 that keeps ordering room >= 2**. "Largest" keeps the task as hard as
the identifiability constraint allows. If no bucket satisfies both, the
generator's two difficulty axes cannot be set independently; Track Q then runs at
gamma = 0.4 with the 0.47 ceiling stated as the known bound, and the sweep is
reported as that finding.

Gated `hops_2_4` as the ladder was. Abstain episodes are **included**: nothing
here reads an assertion mask, and excluding them is what created Track P's
gameable selection subset. Generates in memory; writes no split; touches no
holdout.
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
from hippocampus_foundation.read_run.generator import GAMMA_BUCKETS  # noqa: E402
from hippocampus_foundation.read_run.generator_v2 import (  # noqa: E402
    SIMILARITY_WINNER_PPM,
)
from hippocampus_foundation.read_run.generator_v3 import (  # noqa: E402
    CELLS_V3,
    generate_episode_v3,
)
from hippocampus_foundation.read_run.policies_v3 import (  # noqa: E402
    blind_exhaust_trace,
    oracle_trace,
    policy_row_v3,
    similarity_exhaust_trace,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_v2_cell_audit import _distribution  # noqa: E402

GATED = "hops_2_4"
CELLS = ("deg6_len8_v4_rep-k1", "deg3_len6_v8-k1")
HARD = "deg6_len8_v4_rep-k1"
RULE = {
    "min_identifiability": 0.80,
    "max_ties": 0.10,
    "min_ordering_room": 2,
    "choose": "largest gamma satisfying all three on the hard cell",
    "fallback": "gamma 0.4 with the 0.47 ceiling stated",
}
_CONTEXT: dict[str, Any] = {}


def _initialise(cell: str, seed_hex: str, count: int, gamma: float) -> None:
    _CONTEXT.update(cell=cell, seed=bytes.fromhex(seed_hex), count=count, gamma=gamma)


def sweep_episode(index: int) -> dict[str, Any] | None:
    try:
        episode = generate_episode_v3(
            _CONTEXT["seed"],
            config=CELLS_V3[_CONTEXT["cell"]],
            split="test-fixture",
            index=index,
            count=_CONTEXT["count"],
            gamma=_CONTEXT["gamma"],
            gold_mask=None if index % 4 == 0 else 1 + (index % 15),
        )
    except GenerationError:
        return None
    if coverage_stratum(target_hop_distance(episode)) != GATED:
        return None
    by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}

    def promoted(route: list[int]) -> float:
        return sum(
            by_id[e]["query_similarity_ppm"] == SIMILARITY_WINNER_PPM for e in route
        ) / len(route)

    worst_target = min(promoted(r) for r in episode.hidden["valid_routes"])
    best_distractor = max(promoted(r) for r in episode.hidden["distractor_routes"])
    similarity = policy_row_v3(episode, similarity_exhaust_trace(episode.visible))
    return {
        "separates": worst_target > best_distractor,
        "tie": worst_target == best_distractor,
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


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    walker = _distribution([r["walker_expansions"] for r in rows])
    oracle = _distribution([r["oracle_expansions"] for r in rows])
    return {
        "gated": n,
        "identifiability": sum(r["separates"] for r in rows) / n,
        "ties": sum(r["tie"] for r in rows) / n,
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
    parser.add_argument("--seed-label", default="track-q-v3-gamma-sweep")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    seed = hashlib.sha256(args.seed_label.encode()).digest()
    started = datetime.now(UTC).replace(microsecond=0).isoformat()

    cells: dict[str, dict[str, Any]] = {}
    for cell in CELLS:
        cells[cell] = {}
        for gamma in GAMMA_BUCKETS:
            with multiprocessing.Pool(
                args.workers,
                initializer=_initialise,
                initargs=(cell, seed.hex(), args.count, gamma),
            ) as pool:
                rows = [
                    r
                    for r in pool.imap(sweep_episode, range(args.count), chunksize=8)
                    if r is not None
                ]
            summary = summarise(rows)
            cells[cell][f"gamma_{gamma}"] = summary
            print(
                f"{cell} gamma={gamma}: n={summary['gated']} "
                f"identifiability={summary['identifiability']:.3f} "
                f"ties={summary['ties']:.3f} "
                f"room={summary['ordering_room_median']} "
                f"(walker {summary['walker_expansions']['median']}, "
                f"oracle {summary['oracle_expansions']['median']}, "
                f"similarity@RC {summary['similarity_expansions_at_rc']['median']})",
                flush=True,
            )

    passing = [
        gamma
        for gamma in GAMMA_BUCKETS
        if cells[HARD][f"gamma_{gamma}"]["identifiability"]
        >= RULE["min_identifiability"]
        and cells[HARD][f"gamma_{gamma}"]["ties"] <= RULE["max_ties"]
        and cells[HARD][f"gamma_{gamma}"]["ordering_room_median"]
        >= RULE["min_ordering_room"]
    ]
    chosen = max(passing) if passing else None
    record = {
        "record_kind": "read_run_v3_gamma_sweep",
        "started_at": started,
        "finished_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "seed_label": args.seed_label,
        "episodes_per_cell_per_gamma": args.count,
        "gamma_buckets": list(GAMMA_BUCKETS),
        "gated_stratum": GATED,
        "abstain_included": True,
        "touches_holdout": False,
        "rule": RULE,
        "cells": cells,
        "passing_gammas_hard_cell": passing,
        "chosen_gamma": chosen,
        "fallback_applies": chosen is None,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
    print()
    print(
        json.dumps(
            {"passing": passing, "chosen_gamma": chosen, "fallback": chosen is None}
        )
    )


if __name__ == "__main__":
    main()
