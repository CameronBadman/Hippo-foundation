"""The untrained TRAVV2 reference line (phase O-3, before O-4).

The Track O architecture carries two of `policies_v2.stop_aware_examined_set`'s
mechanics in its structure rather than in its weights: the frontier admits only
relation-matching edges, and the walk stops once both endpoints are reached. So
an untrained model with random scores already behaves like a shuffled
`stop_aware`, and a trained model that merely matches it has learned nothing.

That makes "TRAVV2 at update 0" a reference line the outcome table needs, not a
curiosity. It is measured here, per seed, before any training run starts, and it
is what separates *the architecture works* from *training worked*.

Evaluation only: no optimiser, no gradient step, no holdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from read_run_track_o_probe import load_split, score_screening  # noqa: E402

from hippocampus_foundation.read_run.model import require_torch  # noqa: E402
from hippocampus_foundation.read_run.model_v2 import (  # noqa: E402
    build_read_model_v2,
)

GATED = "hops_2_4"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cells", nargs="*", default=["deg3_len6_v8", "deg6_len8_v4_rep"]
    )
    parser.add_argument("--seeds", nargs="*", type=int, default=[1729, 2718, 3141])
    parser.add_argument("--data-root", default="private/track-o-v1/data")
    parser.add_argument(
        "--config", default="experiments/track_o_v1/training-config.o1.json"
    )
    parser.add_argument("--budget", type=int, default=64)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    torch, _nn, _functional = require_torch()
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    cells = {}
    for cell in args.cells:
        screening = load_split(Path(args.data_root) / f"{cell}-g04" / "screen")
        per_seed = {}
        for seed in args.seeds:
            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
            model = build_read_model_v2(config).to(device)
            report = score_screening(
                torch,
                model,
                screening,
                arm="TRAVV2",
                budget=args.budget,
                microbatch=int(config["training"]["microbatch_size"]),
            )
            gated = report[GATED]
            per_seed[str(seed)] = gated
            print(
                f"{cell} seed {seed}: rc={gated['route_complete_fraction']:.4f} "
                f"prec={gated['precision_mean']:.4f} "
                f"examined={gated['examined_mean']:.1f} "
                f"acc={gated['exact_set_accuracy']:.4f}",
                flush=True,
            )
        cells[cell] = {
            "screening_episode_count": len(screening),
            "per_seed": per_seed,
            "route_complete_fraction_range": [
                min(v["route_complete_fraction"] for v in per_seed.values()),
                max(v["route_complete_fraction"] for v in per_seed.values()),
            ],
            "precision_mean_range": [
                min(v["precision_mean"] for v in per_seed.values()),
                max(v["precision_mean"] for v in per_seed.values()),
            ],
        }

    Path(args.output).write_text(
        json.dumps(
            {
                "record_kind": "read_run_track_o_untrained_reference",
                "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "budget": args.budget,
                "gamma": 0.4,
                "gated_stratum": GATED,
                "note": (
                    "TRAVV2 at update 0. The architecture carries stop_aware's "
                    "frontier restriction and stop rule structurally, so this is "
                    "the line training must beat, not the model-free policies alone."
                ),
                "touches_holdout": False,
                "cells": cells,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
