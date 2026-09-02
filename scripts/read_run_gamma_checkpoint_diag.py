"""Per-checkpoint descriptives for the γ-sweep screening report (Amendment 10 §8).

Loads one diagnostic TRAV checkpoint written by `read_run_learning_probe.py`
and re-scores it on its own screening bucket three ways:

1. **baseline** — the probe's own scoring path (`model.eval()`, `no_grad`, the
   frozen microbatch, deterministic algorithms), extended with
   `coverage.route_coverage` per stratum and the route-complete ≡ proof_valid
   cross-check. Its gated exact-set accuracy must equal the probe's final
   `screen.jsonl` row; the script records whether it does.
2. **shuffled serialization** — every `router_seed` salted (Amendment 10 §7.1
   on screening): the graph, query, targets and budget are unchanged, only the
   per-node outgoing-edge order is re-randomised. Reported as Δ exact-set
   accuracy on the gated non-abstain stratum against the 1 pp line.
3. **flattened similarity** — every `query_similarity_ppm` set to the same
   constant, the Stage C ablation of `trav_edge_selection_stage_c.json`: does
   this checkpoint still collapse when the similarity channel carries nothing?

Diagnostic only: no receipt, no freeze binding, screening split only. The
checkpoint is loaded directly because `evaluate_checkpoint` would (rightly)
refuse a probe checkpoint. Everything here is descriptive under Amendment 10
§8 and moves no decision rule.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from hippocampus_foundation.read_run.contracts import validate_preregistration
from hippocampus_foundation.read_run.coverage import route_coverage
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.io import read_generated_split
from hippocampus_foundation.read_run.model import build_read_model, require_torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_learning_probe import shannon_entropy, wilson_lower_bound  # noqa: E402

GATED_STRATUM = "hops_2_4"
CONSTANT_SIMILARITY_PPM = 500_000  # Stage C's midpoint of the ppm range
DEFAULT_SALT = "amendment-10-shuffled-serialization"
CONCERNING_DELTA_PP = 1.0


def reroute_seed(episode: Any, salt: str) -> Any:
    """A copy with a different `router_seed`: same graph, query, targets, budget."""

    shuffled = copy.deepcopy(episode)
    shuffled.visible["router_seed"] = episode.visible["router_seed"] + salt
    return shuffled


def flatten_similarity(episode: Any, constant: int) -> Any:
    flattened = copy.deepcopy(episode)
    for edge in flattened.visible["edges"]:
        edge["query_similarity_ppm"] = constant
    return flattened


def score_variant(
    torch: Any,
    model: Any,
    episodes: list[tuple[Any, str]],
    *,
    budget: int,
    microbatch: int,
) -> dict[str, Any]:
    """Score one variant of the screening split with the probe's own path."""

    buckets: dict[str, dict[str, Any]] = {}
    disagreements = 0
    for start in range(0, len(episodes), microbatch):
        chunk = episodes[start : start + microbatch]
        with torch.no_grad():
            output = model(
                [episode.visible for episode, _ in chunk], arm="TRAV", budget=budget
            )
        classes = output["logits"].argmax(dim=1).detach().cpu().tolist()
        scores = output["scores"].detach().float().cpu().tolist()
        for (episode, stratum), predicted, edge_ids, row in zip(
            chunk, classes, output["edge_ids"], scores, strict=True
        ):
            edge_list = list(edge_ids)
            coverage = route_coverage(episode, edge_list)
            result = score_prediction(
                episode,
                predicted_class=predicted,
                recorded_routes=decode_best_routes(episode.visible, edge_list, row),
            )
            if coverage["route_complete"] != result["proof_valid"]:
                disagreements += 1
            key = f"{stratum}{'_abstain' if result['abstain'] else ''}"
            bucket = buckets.setdefault(
                key,
                {
                    "n": 0,
                    "exact_correct": 0,
                    "class_correct": 0,
                    "proof_valid": 0,
                    "route_complete": 0,
                    "target_node_present": 0,
                    "predicted_abstain": 0,
                    "predicted": Counter(),
                },
            )
            bucket["n"] += 1
            bucket["exact_correct"] += int(result["exact_correct"])
            bucket["class_correct"] += int(result["class_correct"])
            bucket["proof_valid"] += int(result["proof_valid"])
            bucket["route_complete"] += int(coverage["route_complete"])
            bucket["target_node_present"] += int(coverage["target_node_present"])
            bucket["predicted_abstain"] += int(predicted == 0)
            bucket["predicted"][predicted] += 1

    report: dict[str, Any] = {}
    for key, bucket in sorted(buckets.items()):
        n = bucket["n"]
        predicted = bucket["predicted"]
        report[key] = {
            "n": n,
            "exact_correct": bucket["exact_correct"],
            "exact_set_accuracy": bucket["exact_correct"] / n,
            "wilson_lower_bound": wilson_lower_bound(bucket["exact_correct"], n),
            "class_correct_fraction": bucket["class_correct"] / n,
            "proof_valid_fraction": bucket["proof_valid"] / n,
            "route_complete_fraction": bucket["route_complete"] / n,
            "target_node_present_fraction": bucket["target_node_present"] / n,
            "predicted_abstain_fraction": bucket["predicted_abstain"] / n,
            "distinct_classes": len(predicted),
            "prediction_entropy_nats": shannon_entropy(predicted),
            "modal_class": predicted.most_common(1)[0][0],
            "modal_fraction": predicted.most_common(1)[0][1] / n,
        }
    return {
        "by_stratum": report,
        "route_complete_vs_proof_valid_disagreements": disagreements,
    }


def _probe_final_row(probe_dir: Path) -> dict[str, Any] | None:
    screen_log = probe_dir / "screen.jsonl"
    if not screen_log.exists():
        return None
    rows = [json.loads(line) for line in screen_log.read_text().splitlines() if line]
    return rows[-1] if rows else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--budget", type=int, default=128)
    parser.add_argument("--shuffle-salt", default=DEFAULT_SALT)
    parser.add_argument(
        "--constant-similarity", type=int, default=CONSTANT_SIMILARITY_PPM
    )
    parser.add_argument("--limit", type=int, default=None, help="smoke tests only")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    torch, _nn, _f = require_torch()
    torch.use_deterministic_algorithms(True)
    contracts = validate_preregistration()
    config = contracts["training_config"]
    microbatch = int(config["training"]["microbatch_size"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_read_model(config).to(device)
    saved = torch.load(args.checkpoint, map_location=device, weights_only=True)
    model.load_state_dict(saved["state_dict"])
    model.eval()

    episodes = [
        (episode, coverage_stratum(target_hop_distance(episode)))
        for episode in read_generated_split(Path(args.screen_root))
    ]
    if args.limit:
        episodes = episodes[: args.limit]
    shuffled = [(reroute_seed(e, args.shuffle_salt), s) for e, s in episodes]
    flattened = [
        (flatten_similarity(e, args.constant_similarity), s) for e, s in episodes
    ]

    variants = {
        "baseline": score_variant(
            torch, model, episodes, budget=args.budget, microbatch=microbatch
        ),
        "shuffled_serialization": score_variant(
            torch, model, shuffled, budget=args.budget, microbatch=microbatch
        ),
        "flattened_similarity": score_variant(
            torch, model, flattened, budget=args.budget, microbatch=microbatch
        ),
    }

    base = variants["baseline"]["by_stratum"][GATED_STRATUM]
    shuf = variants["shuffled_serialization"]["by_stratum"][GATED_STRATUM]
    flat = variants["flattened_similarity"]["by_stratum"][GATED_STRATUM]
    delta_pp = 100.0 * (shuf["exact_set_accuracy"] - base["exact_set_accuracy"])

    checkpoint_path = Path(args.checkpoint)
    probe_row = _probe_final_row(checkpoint_path.parent)
    probe_gated = (probe_row or {}).get("strata", {}).get(GATED_STRATUM)
    report = {
        "record_kind": "read_run_gamma_checkpoint_diagnostic",
        "checkpoint": str(checkpoint_path),
        "screen_root": args.screen_root,
        "budget": args.budget,
        "microbatch": microbatch,
        "episode_limit": args.limit,
        "device": device.type,
        "checkpoint_meta": {
            k: v
            for k, v in saved.items()
            if k != "state_dict" and not hasattr(v, "shape")
        },
        "shuffle_salt": args.shuffle_salt,
        "constant_similarity_ppm": args.constant_similarity,
        "variants": variants,
        "gated_summary": {
            "baseline_exact_set_accuracy": base["exact_set_accuracy"],
            "baseline_route_complete_fraction": base["route_complete_fraction"],
            "probe_final_row": probe_gated,
            "baseline_matches_probe_final_row": (
                probe_gated is not None
                and probe_gated["correct"] == base["exact_correct"]
                and probe_gated["n"] == base["n"]
            ),
            "shuffled_exact_set_accuracy": shuf["exact_set_accuracy"],
            "shuffled_delta_pp": delta_pp,
            "shuffled_route_complete_fraction": shuf["route_complete_fraction"],
            "shuffled_control": (
                "concerning" if abs(delta_pp) >= CONCERNING_DELTA_PP else "clean"
            ),
            "flattened_exact_set_accuracy": flat["exact_set_accuracy"],
            "flattened_route_complete_fraction": flat["route_complete_fraction"],
            "flattened_drop_pp": 100.0
            * (base["exact_set_accuracy"] - flat["exact_set_accuracy"]),
        },
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report["gated_summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
