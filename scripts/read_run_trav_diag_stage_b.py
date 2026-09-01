"""Stage B of the TRAV edge-selection diagnostic: everything that needs an
actual trained TRAV checkpoint -- sections 1, 2, TRAV's column of 3/4, 5, 6.

Diagnostic only. Reuses `score_prediction`/`decode_best_routes` from
evaluation.py and `build_read_model`/`require_torch` from model.py exactly as
the official evaluator does; the only departure from the official path is
that this loads a diagnostic checkpoint.pt directly rather than going through
`evaluate_checkpoint`'s receipt/freeze/P0 binding checks, because this run has
none of those and must not pretend to.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from read_run_trav_diag_common import (  # noqa: E402
    FEATURES,
    bucket,
    episode_index,
    features,
    fit_edge_probe,
    kl_divergence,
    probe_report,
    score_edge_probe,
    total_variation,
)

from hippocampus_foundation.read_run.contracts import (
    validate_preregistration,  # noqa: E402
)
from hippocampus_foundation.read_run.evaluation import (  # noqa: E402
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.io import read_generated_split  # noqa: E402
from hippocampus_foundation.read_run.model import (  # noqa: E402
    build_read_model,
    require_torch,
)

BUDGET = 128
MICROBATCH = 16


def run_trav(torch, model, episodes, device, *, ablate_query=False):
    """One inference pass. Returns per-episode (edge_ids, exact_correct)."""

    out = []
    original_query = model._query
    if ablate_query:
        hidden = model.state_dict()["state_cell.weight_hh"].shape[1]

        def zero_query(visible_batch):
            return torch.zeros(len(visible_batch), hidden, device=device)

        model._query = zero_query
    try:
        for start in range(0, len(episodes), MICROBATCH):
            chunk = episodes[start : start + MICROBATCH]
            with torch.no_grad():
                output = model([e.visible for e in chunk], arm="TRAV", budget=BUDGET)
            classes = output["logits"].argmax(dim=1).detach().cpu().tolist()
            score_rows = output["scores"].detach().float().cpu().tolist()
            for episode, predicted, edge_ids, scores in zip(
                chunk, classes, output["edge_ids"], score_rows, strict=True
            ):
                routes = decode_best_routes(episode.visible, edge_ids, scores)
                result = score_prediction(
                    episode, predicted_class=predicted, recorded_routes=routes
                )
                out.append((episode, list(edge_ids), result))
    finally:
        model._query = original_query
    return out


def reroute_seed(episode, salt: str):
    """A copy of the episode with a different router_seed -- re-randomizes
    every node's outgoing-edge serialization order (both TRAV's expansion
    order and DIRECT's pool order derive from it) while leaving the graph,
    query, target, and budget untouched."""

    shuffled = copy.deepcopy(episode)
    shuffled.visible["router_seed"] = episode.visible["router_seed"] + salt
    return shuffled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--device", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    torch, _nn, _functional = require_torch()
    contracts = validate_preregistration()
    config = contracts["training_config"]
    device = torch.device(
        args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    model = build_read_model(config).to(device)
    saved = torch.load(args.checkpoint, map_location=device, weights_only=True)
    model.load_state_dict(saved["state_dict"])
    model.eval()

    episodes = list(read_generated_split(Path(args.screen_root)))
    if args.limit:
        episodes = episodes[: args.limit]

    baseline = run_trav(torch, model, episodes, device)
    indexes = {id(episode): episode_index(episode) for episode, _e, _r in baseline}

    result: dict[str, Any] = {"n_episodes": len(episodes)}

    # --- section 1: on-path fraction of chosen edges, correct vs incorrect ---
    on_path_fracs = {"correct": [], "incorrect": []}
    for episode, edge_ids, r in baseline:
        idx = indexes[id(episode)]
        if r["abstain"]:
            continue
        frac = sum(1 for e in edge_ids if e in idx["on_path"]) / len(edge_ids)
        on_path_fracs["correct" if r["exact_correct"] else "incorrect"].append(frac)

    def summarize(values):
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        return {
            "n": n,
            "mean": sum(s) / n,
            "min": s[0],
            "p25": s[n // 4],
            "median": s[n // 2],
            "p75": s[(3 * n) // 4],
            "max": s[-1],
        }

    result["section_1_on_path_fraction"] = {
        k: summarize(v) for k, v in on_path_fracs.items()
    }

    # --- section 2: step at which the target first enters the examined set,
    # for correct non-abstain episodes only ---
    first_steps = []
    for episode, edge_ids, r in baseline:
        if r["abstain"] or not r["exact_correct"]:
            continue
        idx = indexes[id(episode)]
        step = next(
            (i for i, e in enumerate(edge_ids) if idx["is_target_assertion"][e]),
            None,
        )
        if step is not None:
            first_steps.append(step)
    result["section_2_first_target_step"] = {
        "n_correct_episodes": sum(
            1 for _e, _i, r in baseline if r["exact_correct"] and not r["abstain"]
        ),
        "n_with_a_target_assertion_examined": len(first_steps),
        "distribution": summarize(first_steps),
        "fraction_within_first_16": (
            sum(1 for s in first_steps if s < 16) / len(first_steps)
            if first_steps
            else None
        ),
    }

    # --- sections 3/4: TRAV's chosen-edge population ---
    dist_trav = {name: Counter() for name in FEATURES}
    dist_available = {name: Counter() for name in FEATURES}
    for episode, edge_ids, _r in baseline:
        idx = indexes[id(episode)]
        for edge_id in idx["by_id"]:
            feats = features(idx, edge_id)
            for name in FEATURES:
                dist_available[name][bucket(name, feats[name])] += 1
        for edge_id in edge_ids:
            feats = features(idx, edge_id)
            for name in FEATURES:
                dist_trav[name][bucket(name, feats[name])] += 1

    result["section_3_trav_vs_available_divergence"] = {
        name: {
            "total_variation": total_variation(dist_trav[name], dist_available[name]),
            "kl_divergence": kl_divergence(dist_trav[name], dist_available[name]),
        }
        for name in FEATURES
    }

    half = len(baseline) // 2
    fit_rows, score_rows = [], []
    for i, (episode, edge_ids, _r) in enumerate(baseline):
        idx = indexes[id(episode)]
        target = fit_rows if i < half else score_rows
        for edge_id in edge_ids:
            target.append((idx, edge_id, idx["is_target_assertion"][edge_id]))
    base_rate = sum(1 for *_r, label in score_rows if label) / len(score_rows)
    probes = {}
    for name in FEATURES:
        model_probe, default, bucket_rates = fit_edge_probe(fit_rows, name)
        correct, total = score_edge_probe(score_rows, name, model_probe, default)
        probes[name] = probe_report(correct, total, base_rate, bucket_rates)
    result["section_4_trav_chosen_probe"] = {
        "fit_edges": len(fit_rows),
        "score_edges": len(score_rows),
        "target_assertion_base_rate": base_rate,
        "probes": probes,
    }

    # --- section 5: shuffled serialization control ---
    shuffled_episodes = [
        reroute_seed(e, "-diagnostic-shuffle") for e, _i, _r in baseline
    ]
    shuffled = run_trav(torch, model, shuffled_episodes, device)
    non_abstain = [r for _e, _i, r in baseline if not r["abstain"]]
    non_abstain_shuffled = [r for _e, _i, r in shuffled if not r["abstain"]]
    result["section_5_shuffled_serialization"] = {
        "baseline_exact_set_accuracy": sum(r["exact_correct"] for r in non_abstain)
        / len(non_abstain),
        "shuffled_exact_set_accuracy": sum(
            r["exact_correct"] for r in non_abstain_shuffled
        )
        / len(non_abstain_shuffled),
        "n": len(non_abstain),
    }

    # --- section 6: ablated-query control ---
    ablated = run_trav(
        torch, model, [e for e, _i, _r in baseline], device, ablate_query=True
    )
    non_abstain_ablated = [r for _e, _i, r in ablated if not r["abstain"]]
    abstain_base_rate = sum(1 for _e, _i, r in baseline if r["abstain"]) / len(baseline)
    result["section_6_ablated_query"] = {
        "baseline_exact_set_accuracy": sum(r["exact_correct"] for r in non_abstain)
        / len(non_abstain),
        "ablated_exact_set_accuracy": sum(
            r["exact_correct"] for r in non_abstain_ablated
        )
        / len(non_abstain_ablated),
        "abstain_base_rate_for_reference": abstain_base_rate,
        "n": len(non_abstain),
    }

    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True))
    print("wrote", args.output)
    print(json.dumps(result, indent=2, sort_keys=True)[:2000])


if __name__ == "__main__":
    main()
