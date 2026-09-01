#!/usr/bin/env python3
"""Diagnostic learnability probe for the READ-run arms.

This is **not** a preregistered run. It emits no training receipt, no code
freeze binding, and no gate evidence, and it never opens or reads a holdout
split. Its only purpose is to locate the update count at which each arm leaves
uniform prediction, so that `update_count` for a retry can be chosen by the rule
written down in `PREREGISTRATION_AMENDMENT_04.md` §4 rather than guessed.

The optimizer loop is `training.train_arm`'s loop, reproduced field for field
from the frozen `training-config.v1.json`. The single deliberate difference is
that `update_count` comes from the command line. Everything that could change a
gradient -- model construction, optimizer, learning rate, weight decay,
microbatch size, accumulation, loss weights, gradient clipping, autocast, the
determinism flags, and the episode order -- is taken from the shared modules the
official runner uses.

Periodic scoring is on the **screening** split only, and is stratified by
`gates.coverage_stratum` so that the `hops_2_4` cell the decision rules attach to
can be read directly.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from hippocampus_foundation.read_run.contracts import validate_preregistration
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.io import model_input_bytes, read_generated_split
from hippocampus_foundation.read_run.model import build_read_model, require_torch
from hippocampus_foundation.read_run.training import (
    _batches,
    _cycle_episodes,
    _edge_targets,
    _labels,
)

CHANCE = 1.0 / 15.0
Z_ONE_SIDED_95 = 1.6448536269514722


def wilson_lower_bound(correct: int, total: int) -> float:
    """One-sided 95% Wilson lower bound, as used elsewhere in this experiment."""

    if total == 0:
        return 0.0
    z = Z_ONE_SIDED_95
    point = correct / total
    denominator = 1.0 + z * z / total
    centre = point + z * z / (2.0 * total)
    radius = z * math.sqrt(
        point * (1.0 - point) / total + z * z / (4.0 * total * total)
    )
    return (centre - radius) / denominator


def shannon_entropy(counts: Counter[int]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((v / total) * math.log(v / total) for v in counts.values())


def load_screening(root: Path) -> list[Any]:
    """Read the screening split once and keep it in memory with its strata."""

    episodes = []
    for episode in read_generated_split(root):
        model_input_bytes(episode)
        episodes.append((episode, coverage_stratum(target_hop_distance(episode))))
    return episodes


def score_screening(
    torch: Any,
    model: Any,
    screening: list[Any],
    *,
    arm: str,
    budget: int,
    microbatch: int,
) -> dict[str, Any]:
    """Exact-set accuracy and the Amendment 04 learner-gate statistics."""

    buckets: dict[str, dict[str, Any]] = {}
    was_training = model.training
    model.eval()
    pending: list[Any] = []

    def flush() -> None:
        if not pending:
            return
        with torch.no_grad():
            output = model(
                [episode.visible for episode, _ in pending], arm=arm, budget=budget
            )
        classes = output["logits"].argmax(dim=1).detach().cpu().tolist()
        scores = output["scores"].detach().float().cpu().tolist()
        for (episode, stratum), predicted, edge_ids, row in zip(
            pending, classes, output["edge_ids"], scores, strict=True
        ):
            routes = decode_best_routes(episode.visible, edge_ids, row)
            result = score_prediction(
                episode, predicted_class=predicted, recorded_routes=routes
            )
            if result["abstain"]:
                continue
            bucket = buckets.setdefault(
                stratum, {"n": 0, "correct": 0, "predicted": Counter()}
            )
            bucket["n"] += 1
            bucket["correct"] += int(result["exact_correct"])
            bucket["predicted"][predicted] += 1
        pending.clear()

    for item in screening:
        pending.append(item)
        if len(pending) == microbatch:
            flush()
    flush()
    if was_training:
        model.train()

    report = {}
    for stratum, bucket in buckets.items():
        total = bucket["n"]
        correct = bucket["correct"]
        report[stratum] = {
            "n": total,
            "correct": correct,
            "exact_set_accuracy": correct / total if total else None,
            "wilson_lower_bound": wilson_lower_bound(correct, total),
            "distinct_classes": len(bucket["predicted"]),
            "prediction_entropy_nats": shannon_entropy(bucket["predicted"]),
            "modal_class": (
                bucket["predicted"].most_common(1)[0][0] if total else None
            ),
            "modal_fraction": (
                bucket["predicted"].most_common(1)[0][1] / total if total else None
            ),
        }
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=["TRAV", "DIRECT"])
    parser.add_argument("--updates", required=True, type=int)
    parser.add_argument("--train-root", required=True)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--budget", type=int, default=128)
    parser.add_argument("--model-seed", type=int, default=1729)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument(
        "--eval-at",
        type=int,
        nargs="*",
        default=[100, 250],
        help="extra early update counts to score at",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        print("refusing to overwrite a probe run", file=sys.stderr)
        return 2
    output.mkdir(parents=True)
    os.chmod(output, 0o700)

    contracts = validate_preregistration()
    config = contracts["training_config"]
    training = config["training"]

    torch, _nn, functional = require_torch()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.manual_seed(args.model_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.model_seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_read_model(config).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    microbatch = int(training["microbatch_size"])
    accumulation = int(training["gradient_accumulation_steps"])
    use_bf16 = bool(
        device.type == "cuda"
        and hasattr(torch.cuda, "is_bf16_supported")
        and torch.cuda.is_bf16_supported()
    )

    screening = load_screening(Path(args.screen_root))
    checkpoints = sorted(
        {u for u in args.eval_at if 0 < u <= args.updates}
        | set(range(args.eval_every, args.updates + 1, args.eval_every))
        | {args.updates}
    )

    (output / "probe.json").write_text(
        json.dumps(
            {
                "record_kind": "read_run_learning_probe_not_preregistered",
                "arm": args.arm,
                "budget": args.budget,
                "model_seed": args.model_seed,
                "requested_update_count": args.updates,
                "frozen_update_count": int(training["update_count"]),
                "train_root": str(args.train_root),
                "screen_root": str(args.screen_root),
                "screening_episode_count": len(screening),
                "training_config_sha256": contracts["training_config_sha256"],
                "device": device.type,
                "bf16_autocast": use_bf16,
                "evaluation_checkpoints": checkpoints,
                "emits_training_receipt": False,
                "touches_holdout": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    batches = _batches(_cycle_episodes(Path(args.train_root)), microbatch)
    log = (output / "updates.jsonl").open("x", encoding="utf-8")
    screen_log = (output / "screen.jsonl").open("x", encoding="utf-8")
    try:
        model.train()
        for update in range(args.updates):
            optimizer.zero_grad(set_to_none=True)
            update_answer = 0.0
            update_edge = 0.0
            for _ in range(accumulation):
                episodes = next(batches)
                for episode in episodes:
                    model_input_bytes(episode)
                context = (
                    torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                    if use_bf16
                    else contextlib.nullcontext()
                )
                with context:
                    output_batch = model(
                        [episode.visible for episode in episodes],
                        arm=args.arm,
                        budget=args.budget,
                    )
                    answer_loss = functional.cross_entropy(
                        output_batch["logits"], _labels(torch, episodes, device)
                    )
                    edge_loss = functional.binary_cross_entropy_with_logits(
                        output_batch["scores"],
                        _edge_targets(
                            torch, episodes, output_batch["edge_ids"], device
                        ),
                    )
                    loss = (
                        float(training["answer_loss_weight"]) * answer_loss
                        + float(training["edge_loss_weight"]) * edge_loss
                    ) / accumulation
                loss.backward()
                update_answer += float(answer_loss.detach()) / accumulation
                update_edge += float(edge_loss.detach()) / accumulation
            gradient_norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(), float(training["gradient_clip_norm"])
            )
            optimizer.step()
            log.write(
                json.dumps(
                    {
                        "update": update + 1,
                        "answer_loss": update_answer,
                        "edge_loss": update_edge,
                        "gradient_norm": float(gradient_norm),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            log.flush()
            if update + 1 in checkpoints:
                report = score_screening(
                    torch,
                    model,
                    screening,
                    arm=args.arm,
                    budget=args.budget,
                    microbatch=microbatch,
                )
                screen_log.write(
                    json.dumps(
                        {"update": update + 1, "strata": report},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                screen_log.flush()
                gated = report.get("hops_2_4", {})
                print(
                    f"[{args.arm}] update {update + 1}/{args.updates} "
                    f"loss={update_answer:.4f} "
                    f"hops_2_4 acc={gated.get('exact_set_accuracy')} "
                    f"classes={gated.get('distinct_classes')} "
                    f"H={gated.get('prediction_entropy_nats')}",
                    flush=True,
                )
    finally:
        log.close()
        screen_log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
