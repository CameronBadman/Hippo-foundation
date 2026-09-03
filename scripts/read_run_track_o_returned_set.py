"""The returned set: what a Track O traversal asserts is relevant (phase A).

Track O's primary quantities measure the walk — route-completeness, and the
precision of the *examined* set. Examined precision is a **cost**: reaching a
node examines all of its out-edges, so a perfect selector on the hard cell still
pays about 30 edges for about 6 on-route ones, capping precision near 0.20 no
matter how good the policy is (design notes section 2.16).

What a write operation downstream actually adjudicates is the **returned** set —
what the traversal reports as relevant, which need not be everything it looked
at. Nothing forces those to be the same set, and only a narrower report escapes
the examined-precision ceiling. Cameron's point, recorded in section 2.21.

The model already contains the classifier: the edge loss is binary
cross-entropy against "this edge lies on a valid route", so the edge head is a
relevance classifier and its natural decision boundary is a **positive logit** —
the loss's own boundary, not a constant fitted to a screening result, which
`selection.threshold_tuning: false` forbids. This script reports the returned
set at that boundary, plus the full precision-recall curve so no operating point
is chosen at all.

Declared as a descriptive in design notes section 2.17 before any Track O run
reached its read point, so it is preregistered rather than invented afterwards.
Evaluation only: no optimiser, no gradient step, no holdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from read_run_track_o_probe import load_split  # noqa: E402

from hippocampus_foundation.read_run.model import require_torch  # noqa: E402
from hippocampus_foundation.read_run.model_v2 import (  # noqa: E402
    build_read_model_v2,
)

GATED = "hops_2_4"


def _curve(
    scored: list[tuple[float, bool]], on_route_total: int
) -> list[dict[str, Any]]:
    """Precision-recall over every distinct score, so no threshold is chosen."""

    ordered = sorted(scored, key=lambda row: -row[0])
    points: list[dict[str, Any]] = []
    hits = 0
    for index, (score, positive) in enumerate(ordered, start=1):
        hits += int(positive)
        if index == len(ordered) or score != ordered[index][0]:
            points.append(
                {
                    "threshold": score,
                    "returned": index,
                    "precision": hits / index,
                    "recall": hits / on_route_total if on_route_total else 0.0,
                }
            )
    return points


def _average_precision(curve: list[dict[str, Any]]) -> float:
    """Area under the precision-recall curve; no operating point."""

    total = 0.0
    previous_recall = 0.0
    for point in curve:
        total += point["precision"] * (point["recall"] - previous_recall)
        previous_recall = point["recall"]
    return total


def evaluate(
    torch, model, screening, *, budget: int, microbatch: int
) -> dict[str, Any]:
    examined_total = 0
    returned_total = 0
    on_route_total = 0
    returned_on_route = 0
    per_episode_precision: list[float] = []
    per_episode_recall: list[float] = []
    scored: list[tuple[float, bool]] = []
    episodes_counted = 0

    model.eval()
    with torch.no_grad():
        for start in range(0, len(screening), microbatch):
            chunk = screening[start : start + microbatch]
            batch = [episode for episode, _stratum in chunk]
            out = model([episode.visible for episode in batch], budget=budget)
            for slot, (episode, stratum) in enumerate(chunk):
                if episode.hidden["abstain"] or stratum != GATED:
                    continue
                episodes_counted += 1
                examined = out["edge_ids"][slot]
                logits = out["scores"][slot][: len(examined)].tolist()
                on_route = {
                    edge_id
                    for route in episode.hidden["valid_routes"]
                    for edge_id in route
                }
                returned = [
                    edge_id
                    for edge_id, logit in zip(examined, logits, strict=True)
                    if logit > 0.0
                ]
                hit = len(set(returned) & on_route)
                examined_total += len(examined)
                returned_total += len(returned)
                on_route_total += len(on_route)
                returned_on_route += hit
                per_episode_precision.append(hit / len(returned) if returned else 0.0)
                per_episode_recall.append(hit / len(on_route) if on_route else 0.0)
                scored.extend(
                    (float(logit), edge_id in on_route)
                    for edge_id, logit in zip(examined, logits, strict=True)
                )
    curve = _curve(scored, on_route_total)
    mean_precision = (
        sum(per_episode_precision) / len(per_episode_precision)
        if per_episode_precision
        else 0.0
    )
    mean_recall = (
        sum(per_episode_recall) / len(per_episode_recall) if per_episode_recall else 0.0
    )
    return {
        "episodes": episodes_counted,
        "examined_mean": examined_total / max(episodes_counted, 1),
        "returned_mean": returned_total / max(episodes_counted, 1),
        "on_route_mean": on_route_total / max(episodes_counted, 1),
        "examined_precision_micro": returned_on_route / max(examined_total, 1),
        "returned_precision_micro": returned_on_route / max(returned_total, 1),
        "returned_recall_micro": returned_on_route / max(on_route_total, 1),
        "returned_precision_per_episode_mean": mean_precision,
        "returned_recall_per_episode_mean": mean_recall,
        "average_precision": _average_precision(curve),
        "curve_points": len(curve),
        "curve_sample": curve[:: max(1, len(curve) // 24)][:25],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default="private/track-o-v1")
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
    microbatch = int(config["training"]["microbatch_size"])

    cells: dict[str, Any] = {}
    screening_cache: dict[str, Any] = {}
    for directory in sorted(Path(args.runs_root).glob("probe-TRAVV2-*")):
        if not (directory / "checkpoint.pt").exists():
            continue
        name = directory.name[len("probe-TRAVV2-") :]
        cell, seed = name.rsplit("-s", 1)
        if cell not in screening_cache:
            screening_cache[cell] = load_split(
                Path(args.data_root) / f"{cell}-g04" / "screen"
            )
        checkpoint = torch.load(
            directory / "checkpoint.pt", map_location=device, weights_only=False
        )
        model = build_read_model_v2(config).to(device)
        model.load_state_dict(checkpoint["state_dict"])
        row = evaluate(
            torch,
            model,
            screening_cache[cell],
            budget=args.budget,
            microbatch=microbatch,
        )
        cells.setdefault(cell, {})[seed] = row
        print(
            f"{cell} s{seed}: examined {row['examined_mean']:.1f} -> returned "
            f"{row['returned_mean']:.1f}  precision {row['examined_precision_micro']:.3f} -> "
            f"{row['returned_precision_micro']:.3f}  recall {row['returned_recall_micro']:.3f}  "
            f"AP {row['average_precision']:.3f}",
            flush=True,
        )

    Path(args.output).write_text(
        json.dumps(
            {
                "record_kind": "read_run_track_o_returned_set",
                "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "budget": args.budget,
                "gated_stratum": GATED,
                "decision_boundary": "edge logit > 0 (the BCE loss's own boundary)",
                "declared_in": "docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md section 2.17",
                "touches_holdout": False,
                "cells": cells,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
