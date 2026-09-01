"""TRAV's route-completeness at gamma=0, for track C2's second assertion.

Diagnostic. Loads the probe checkpoint directly rather than through
`evaluate_checkpoint`, which this run has no receipt or freeze binding for.
Screening split only.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from hippocampus_foundation.read_run.contracts import validate_preregistration
from hippocampus_foundation.read_run.coverage import route_coverage
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.io import read_generated_split
from hippocampus_foundation.read_run.model import build_read_model, require_torch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--budget", type=int, default=128)
    parser.add_argument("--microbatch", type=int, default=16)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    torch, _nn, _f = require_torch()
    contracts = validate_preregistration()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_read_model(contracts["training_config"]).to(device)
    saved = torch.load(args.checkpoint, map_location=device, weights_only=True)
    model.load_state_dict(saved["state_dict"])
    model.eval()

    episodes = list(read_generated_split(Path(args.screen_root)))
    buckets: dict[str, Counter] = {}
    disagreements = 0

    for start in range(0, len(episodes), args.microbatch):
        chunk = episodes[start : start + args.microbatch]
        with torch.no_grad():
            out = model([e.visible for e in chunk], arm="TRAV", budget=args.budget)
        classes = out["logits"].argmax(dim=1).detach().cpu().tolist()
        rows = out["scores"].detach().float().cpu().tolist()
        for episode, predicted, edge_ids, scores in zip(
            chunk, classes, out["edge_ids"], rows, strict=True
        ):
            cov = route_coverage(episode, list(edge_ids))
            result = score_prediction(
                episode,
                predicted_class=predicted,
                recorded_routes=decode_best_routes(episode.visible, edge_ids, scores),
            )
            if cov["route_complete"] != result["proof_valid"]:
                disagreements += 1
            stratum = coverage_stratum(target_hop_distance(episode))
            key = f"{stratum}{'_abstain' if result['abstain'] else ''}"
            counter = buckets.setdefault(key, Counter())
            counter["n"] += 1
            counter["route_complete"] += int(cov["route_complete"])
            counter["target_node_present"] += int(cov["target_node_present"])
            counter["exact_correct"] += int(result["exact_correct"])

    report = {
        "budget": args.budget,
        "route_complete_vs_proof_valid_disagreements": disagreements,
        "by_stratum": {
            key: {
                "n": c["n"],
                "route_complete": c["route_complete"],
                "route_complete_fraction": c["route_complete"] / c["n"],
                "target_node_present_fraction": c["target_node_present"] / c["n"],
                "exact_correct": c["exact_correct"],
                "exact_set_accuracy": c["exact_correct"] / c["n"],
            }
            for key, c in sorted(buckets.items())
        },
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
