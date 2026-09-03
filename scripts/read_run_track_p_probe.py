r"""Track P screening probe: a learned stop and an honest expansion cost.

Forked from `read_run_track_o_probe.py`, which keeps working for Track O. Not
preregistered as an arm and deliberately unofficial: it emits no training
receipt, binds no code freeze, and never opens a holdout.

What differs from the Track O probe, and why each difference is forced:

**Training always exhausts.** `stop_rule="exhaust"`, the stop head's own output
ignored, so what the head *learns* is decoupled from what it *does* and every
episode yields decision points on both sides of route-completeness. A walk that
halted at its own prediction would only ever see the states its current
prediction leads to.

**Three losses, three exact labels.** The answer at T\* (the first decision point
whose stop label is 1, teacher-forced from hidden truth so the answer head sees
the same prefix under every supervision source), the edge BCE over the exhausted
examined set, and the stop BCE over the decision points.

**Two stop rules, from the same trained head, reported side by side.** The
primary is `P(stop) > 0.5`, the BCE's own boundary. The secondary is
constant-free: stop when the stop logit exceeds the best remaining frontier edge
logit — "done" is more probable than "the best edge left is on-route". Neither
is tuned; both are read.

**Registration, not set coverage, is the reported completeness.** Design note
2.23: a target's final edge can enter the examined set through an expansion at
another depth while the correct-depth prefix is never popped, so set coverage
credits a stopping policy with a target its walk never registered. Both are
recorded and their disagreement is reported; the gates read registration.

**The returned set is the model's selection, not everything it examined.** A
route is *returned* only when every one of its edges scores above zero — the
edge head's own decision boundary, no tuned threshold. `decode_all_routes` has
no top-two cap, so a returned distractor route is visible to `proof_valid`
rather than being silently truncated away. This is the selective-return
measurement of design notes 2.17 and 2.21: the examined set is the cost, the
returned set is the product, and on v3 data they cannot be the same thing
because exhausting always reaches a distractor endpoint.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from read_run_learning_probe import wilson_lower_bound  # noqa: E402
from read_run_track_o_probe import (  # noqa: E402
    _batches,
    count_split,
    cycle_split,
    load_split,
)

from hippocampus_foundation.read_run.coverage import route_coverage_v3  # noqa: E402
from hippocampus_foundation.read_run.evaluation_v3 import (  # noqa: E402
    decode_all_routes,
    score_prediction_v3,
)
from hippocampus_foundation.read_run.model import require_torch  # noqa: E402
from hippocampus_foundation.read_run.model_v2 import route_prefixes  # noqa: E402
from hippocampus_foundation.read_run.model_v3 import (  # noqa: E402
    STOP_LEARNED,
    STOP_TREE_EXHAUSTED,
    build_read_model_v3,
)
from hippocampus_foundation.read_run.training_v2 import (  # noqa: E402
    edge_targets_ragged,
    labels_v2,
    masked_edge_loss,
)
from hippocampus_foundation.read_run.training_v3 import (  # noqa: E402
    answer_cut_indices,
    stop_labels,
    stop_loss,
    supervision_source_v3,
)

GATED = "hops_2_4"
TRACK_O_PARAMETERS = 10_257_896
STOP_RULES = ("probability", "logit_margin")


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def evaluate(
    torch,
    model,
    screening,
    *,
    microbatch: int,
    rule: str,
) -> dict[str, Any]:
    """Score one stop rule over the screening split, per stratum.

    `probability` halts at `P(stop) > 0.5`; `logit_margin` halts when the stop
    logit beats the best frontier edge logit. Both come from the same trained
    head and neither carries a tuned constant.
    """

    buckets: dict[str, dict[str, Any]] = {}
    model.eval()
    with torch.no_grad():
        for start in range(0, len(screening), microbatch):
            chunk = screening[start : start + microbatch]
            episodes = [episode for episode, _stratum in chunk]
            out = model(
                [episode.visible for episode in episodes],
                stop_rule="learned",
                stop_decision=rule,
            )
            predicted = out["logits"].argmax(dim=-1).tolist()
            for slot, (episode, stratum) in enumerate(chunk):
                if episode.hidden["abstain"]:
                    continue
                reason = out["stop_reason"][slot]
                if reason not in {STOP_LEARNED, STOP_TREE_EXHAUSTED}:
                    raise SystemExit(f"band H: unexpected stop reason {reason!r}")
                bucket = buckets.setdefault(
                    stratum,
                    {
                        "n": 0,
                        "registered": 0,
                        "set_complete": 0,
                        "disagreements": 0,
                        "expansions": [],
                        "expansions_when_registered": [],
                        "overhead": [],
                        "edges": [],
                        "early_stops": 0,
                        "proof_valid": 0,
                        "exact": 0,
                        "returned": [],
                        "returned_edges": [],
                        "returned_precision": [],
                        "returned_recall": [],
                        "distractor_routes_returned": [],
                        "distractor_endpoints": [],
                        "stops": Counter(),
                    },
                )
                examined = out["edge_ids"][slot]
                targets = set(episode.hidden["target_nodes"])
                registered = targets <= set(out["endpoints"][slot])
                coverage = route_coverage_v3(episode, examined)
                # The returned set is what the edge head selects, not what the
                # walk examined. Decoding from the whole examined set with flat
                # scores would return every complete route including the planted
                # distractor, so `proof_valid` could never be 1 on v3 data and
                # the metric would measure nothing.
                scores = out["scores"][slot][: len(examined)].tolist()
                kept = [
                    edge_id
                    for edge_id, score in zip(examined, scores, strict=True)
                    if score > 0.0
                ]
                routes = decode_all_routes(episode.visible, kept, [0.0] * len(kept))
                scored = score_prediction_v3(
                    episode,
                    predicted_class=predicted[slot],
                    recorded_routes=routes,
                )
                bucket["n"] += 1
                bucket["registered"] += int(registered)
                bucket["set_complete"] += int(coverage["route_complete"])
                bucket["disagreements"] += int(
                    bool(coverage["route_complete"]) != registered
                )
                bucket["expansions"].append(out["expansion_count"][slot])
                bucket["edges"].append(len(examined))
                bucket["stops"][reason] += 1
                bucket["early_stops"] += int(reason == STOP_LEARNED and not registered)
                bucket["proof_valid"] += int(scored["proof_valid"])
                bucket["exact"] += int(scored["exact_correct"])
                bucket["returned"].append(scored["routes_returned"])
                on_route = {
                    edge_id
                    for route in episode.hidden["valid_routes"]
                    for edge_id in route
                }
                bucket["returned_edges"].append(len(kept))
                if kept:
                    bucket["returned_precision"].append(
                        len(on_route & set(kept)) / len(kept)
                    )
                bucket["returned_recall"].append(
                    len(on_route & set(kept)) / len(on_route)
                )
                bucket["distractor_routes_returned"].append(
                    scored["distractor_routes_returned"]
                )
                bucket["distractor_endpoints"].append(
                    len(coverage["distractor_endpoints_reached"])
                )
                if registered:
                    bucket["expansions_when_registered"].append(
                        out["expansion_count"][slot]
                    )
                    first = [
                        point.expansions
                        for point in out["decisions"][slot]
                        if targets <= set(point.endpoints)
                    ]
                    if first:
                        bucket["overhead"].append(
                            out["expansion_count"][slot] - first[0]
                        )
    model.train()

    report: dict[str, Any] = {}
    for stratum, bucket in buckets.items():
        n = bucket["n"]
        report[stratum] = {
            "n": n,
            "targets_registered": bucket["registered"] / n,
            "targets_registered_wilson_lower_bound": wilson_lower_bound(
                bucket["registered"], n
            ),
            "set_route_complete": bucket["set_complete"] / n,
            "coverage_disagreements": bucket["disagreements"],
            "expansions_mean": _mean(bucket["expansions"]),
            "expansions_mean_when_registered": _mean(
                bucket["expansions_when_registered"]
            ),
            "overhead_expansions_mean": _mean(bucket["overhead"]),
            "edges_mean": _mean(bucket["edges"]),
            "early_stop_fraction": bucket["early_stops"] / n,
            "proof_valid_fraction": bucket["proof_valid"] / n,
            "exact_set_accuracy": bucket["exact"] / n,
            "routes_returned_mean": _mean(bucket["returned"]),
            "returned_edges_mean": _mean(bucket["returned_edges"]),
            "returned_precision_mean": _mean(bucket["returned_precision"]),
            "returned_recall_mean": _mean(bucket["returned_recall"]),
            "distractor_routes_returned_mean": _mean(
                bucket["distractor_routes_returned"]
            ),
            "distractor_endpoints_reached_mean": _mean(bucket["distractor_endpoints"]),
            "stop_reasons": dict(bucket["stops"]),
        }
    return report


def training_diagnostics(
    torch, out: dict[str, Any], labels: list[list[float]]
) -> dict[str, Any]:
    """What would reveal a labelling bug before 8,000 updates are spent."""

    flat_logits = torch.cat(out["stop_logits"]).detach().float()
    flat_labels = torch.tensor(
        [value for row in labels for value in row], device=flat_logits.device
    )
    probability = torch.sigmoid(flat_logits)
    agreement = ((probability > 0.5).float() == flat_labels).float().mean()
    return {
        "stop_label_agreement": float(agreement),
        "stop_positive_fraction": float(flat_labels.mean()),
        "stop_probability_in_band": float(
            ((probability > 0.4) & (probability < 0.6)).float().mean()
        ),
        "episodes_without_t_star": sum(1 for row in labels if not any(row)),
        "decision_points_mean": sum(len(row) for row in labels) / len(labels),
        "expansions_mean": sum(out["expansion_count"]) / len(out["expansion_count"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--train-root", required=True)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-seed", type=int, required=True)
    parser.add_argument("--gamma", type=float, default=0.4)
    parser.add_argument("--updates", type=int, default=None)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--eval-at", type=int, nargs="*", default=[50, 100, 250])
    parser.add_argument("--save-checkpoint", action="store_true")
    args = parser.parse_args()

    for path in (args.train_root, args.screen_root, args.output):
        if "holdout" in str(path) or "heldout" in str(path):
            raise SystemExit("refusing a holdout path")

    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    training = config["training"]
    updates = (
        args.updates if args.updates is not None else int(training["update_count"])
    )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    torch, _nn, functional = require_torch()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.manual_seed(args.model_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.model_seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = build_read_model_v3(config).to(device)
    parameters = sum(p.numel() for p in model.parameters() if p.requires_grad)
    if parameters != TRACK_O_PARAMETERS:
        raise SystemExit(
            f"band H: capacity drifted from Track O — {parameters} vs "
            f"{TRACK_O_PARAMETERS}"
        )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    microbatch = int(training["microbatch_size"])
    accumulation = int(training["gradient_accumulation_steps"])
    evaluation_microbatch = int(training["evaluation_microbatch_size"])
    use_bf16 = bool(
        device.type == "cuda"
        and hasattr(torch.cuda, "is_bf16_supported")
        and torch.cuda.is_bf16_supported()
    )
    schedule = training["supervision_schedule"]

    screening = load_split(Path(args.screen_root))
    checkpoints = sorted(
        {u for u in args.eval_at if 0 < u <= updates}
        | set(range(args.eval_every, updates + 1, args.eval_every))
        | {updates}
    )

    (output / "probe.json").write_text(
        json.dumps(
            {
                "record_kind": "read_run_track_p_probe_not_preregistered",
                "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "git_head": _git_head(),
                "arm": "TRAVP",
                "generator_cell": args.cell,
                "gamma": args.gamma,
                "cost_unit": "expansions",
                "budget": None,
                "distractor_paths": config["selection"]["distractor_paths"],
                "model_seed": args.model_seed,
                "requested_update_count": updates,
                "config_path": str(config_path),
                "config_sha256": "sha256:"
                + __import__("hashlib").sha256(config_path.read_bytes()).hexdigest(),
                "trainable_parameters": parameters,
                "track_o_parameters": TRACK_O_PARAMETERS,
                "train_root": str(args.train_root),
                "screen_root": str(args.screen_root),
                "train_episode_count": count_split(Path(args.train_root)),
                "screening_episode_count": len(screening),
                "device": device.type,
                "bf16_autocast": use_bf16,
                "evaluation_checkpoints": checkpoints,
                "supervision_schedule": schedule,
                "stop_rules_reported": list(STOP_RULES),
                "training_walk_stop_rule": "exhaust",
                "emits_training_receipt": False,
                "touches_holdout": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    batches = _batches(cycle_split(Path(args.train_root)), microbatch)
    log = (output / "updates.jsonl").open("x", encoding="utf-8")
    screen_log = (output / "screen.jsonl").open("x", encoding="utf-8")
    try:
        model.train()
        for update in range(updates):
            source = supervision_source_v3(update, updates, schedule)
            optimizer.zero_grad(set_to_none=True)
            totals = {"answer": 0.0, "edge": 0.0, "stop": 0.0}
            diagnostics: dict[str, Any] = {}
            for _step in range(accumulation):
                episodes = next(batches)
                supplied = (
                    [
                        route_prefixes(e.visible, e.hidden["valid_routes"])
                        for e in episodes
                    ]
                    if source == "gold"
                    else None
                )
                context = (
                    torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                    if use_bf16
                    else contextlib.nullcontext()
                )
                with context:
                    out = model(
                        [e.visible for e in episodes],
                        stop_rule="exhaust",
                        supplied=supplied,
                    )
                    labels = stop_labels(episodes, out["decisions"])
                    # The answer trains on the examined set at T*, the first
                    # route-complete decision point. T* comes from hidden truth,
                    # so it cannot be computed inside `forward`; re-reading the
                    # answer head at that cut costs no second walk.
                    cuts = answer_cut_indices(
                        episodes, out["decisions"], out["examined_count"]
                    )
                    answer_loss = functional.cross_entropy(
                        model.answer_at_cuts(out, cuts),
                        labels_v2(torch, episodes, device),
                    )
                    targets, mask = edge_targets_ragged(
                        torch, episodes, out["edge_ids"], out["scores"].shape[1], device
                    )
                    edge_loss = masked_edge_loss(
                        torch, functional, out["scores"], targets, mask
                    )
                    stop_term = stop_loss(torch, functional, out["stop_logits"], labels)
                    loss = (
                        float(training["answer_loss_weight"]) * answer_loss
                        + float(training["edge_loss_weight"]) * edge_loss
                        + float(training["stop_loss_weight"]) * stop_term
                    ) / accumulation
                loss.backward()
                totals["answer"] += float(answer_loss.detach()) / accumulation
                totals["edge"] += float(edge_loss.detach()) / accumulation
                totals["stop"] += float(stop_term.detach()) / accumulation
                diagnostics = training_diagnostics(torch, out, labels)
            gradient_norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(), float(training["gradient_clip_norm"])
            )
            optimizer.step()
            log.write(
                json.dumps(
                    {
                        "update": update + 1,
                        "answer_loss": totals["answer"],
                        "edge_loss": totals["edge"],
                        "stop_loss": totals["stop"],
                        "gradient_norm": float(gradient_norm),
                        "supervision": source,
                        **diagnostics,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            log.flush()

            if update + 1 in checkpoints:
                rules = {
                    rule: evaluate(
                        torch,
                        model,
                        screening,
                        microbatch=evaluation_microbatch,
                        rule=rule,
                    )
                    for rule in STOP_RULES
                }
                screen_log.write(
                    json.dumps(
                        {"update": update + 1, "stop_rules": rules},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                screen_log.flush()
                primary = rules["probability"].get(GATED, {})
                print(
                    f"[TRAVP/{args.cell}/s{args.model_seed}] "
                    f"update {update + 1}/{updates} src={source} "
                    f"stop_agree={diagnostics.get('stop_label_agreement'):.3f} "
                    f"reg={primary.get('targets_registered')} "
                    f"exp={primary.get('expansions_mean')} "
                    f"ovh={primary.get('overhead_expansions_mean')} "
                    f"early={primary.get('early_stop_fraction')} "
                    f"proof={primary.get('proof_valid_fraction')}",
                    flush=True,
                )
    finally:
        log.close()
        screen_log.close()
    if args.save_checkpoint:
        torch.save(
            {
                "state_dict": model.state_dict(),
                "arm": "TRAVP",
                "stage": "diagnostic",
                "model_seed": args.model_seed,
                "generator_cell": args.cell,
                "update_count": updates,
            },
            output / "checkpoint.pt",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
