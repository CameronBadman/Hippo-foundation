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

`--input-ablation no_similarity` (the Track N structural-only screening) holds
`query_similarity_ppm` at `ablation.MASKED_SIMILARITY_PPM` on every training and
screening episode, identically at train and eval time. The default `none` leaves
the probe's behaviour byte-identical to earlier runs; the ablation is recorded in
`probe.json` and in the checkpoint so no scoring script can read a masked model
against unmasked data by accident.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hippocampus_foundation.read_run.ablation import (
    INPUT_ABLATIONS,
    NONE,
    apply_input_ablation,
    mask_query_similarity,
    masked_similarity_ppm,
)
from hippocampus_foundation.read_run.contracts import validate_preregistration
from hippocampus_foundation.read_run.coverage import prefix_route_coverage
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.io import (
    read_generated_split,
    validate_model_input_fields,
)
from hippocampus_foundation.read_run.model import build_read_model, require_torch
from hippocampus_foundation.read_run.training import (
    _batches,
    _cycle_episodes,
    _edge_targets,
    _labels,
)

CHANCE = 1.0 / 15.0
Z_ONE_SIDED_95 = 1.6448536269514722
PREFIX_BUDGETS = (8, 16, 32, 64, 128)


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


def _git_head() -> str | None:
    """The commit the probe was started at, for ordering against a reading rule."""

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_screening(root: Path, input_ablation: str = NONE) -> list[Any]:
    """Read the screening split once and keep it in memory with its strata."""

    episodes = []
    for episode in read_generated_split(root):
        episode = apply_input_ablation(episode, input_ablation)
        validate_model_input_fields(episode)
        episodes.append((episode, coverage_stratum(target_hop_distance(episode))))
    return episodes


def ablated_episodes(episodes: Iterator[Any], input_ablation: str) -> Iterator[Any]:
    """Apply the input ablation to each training episode as it is read.

    In place, which is safe because `_cycle_episodes` re-reads the gzip stream
    every epoch: no masked episode is ever handed out again unmasked.
    """

    constant = masked_similarity_ppm(input_ablation)
    for episode in episodes:
        if constant is not None:
            mask_query_similarity(episode.visible, constant)
        yield episode


def score_screening(
    torch: Any,
    model: Any,
    screening: list[Any],
    *,
    arm: str,
    budget: int,
    microbatch: int,
) -> dict[str, Any]:
    """Exact-set accuracy, the Amendment 04 learner-gate statistics, and route-completeness.

    Route-completeness is `coverage.route_coverage` on the examined edge list at
    the run budget and, because the examined list is prefix-consistent in the
    budget (asserted in `tests/test_read_run_ablation.py`), at each smaller
    prefix budget from the same pass. Abstain episodes are skipped throughout,
    as they always were, so every count here is on the non-abstain stratum.
    """

    buckets: dict[str, dict[str, Any]] = {}
    by_length: dict[str, dict[int, dict[str, Any]]] = {}
    prefix_budgets = tuple(b for b in PREFIX_BUDGETS if b <= budget) + (budget,)

    def new_bucket() -> dict[str, Any]:
        return {
            "n": 0,
            "correct": 0,
            "predicted": Counter(),
            "route_complete_at": dict.fromkeys(prefix_budgets, 0),
            "correct_given_route_complete": 0,
        }

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
            edge_list = list(edge_ids)
            routes = decode_best_routes(episode.visible, edge_list, row)
            result = score_prediction(
                episode, predicted_class=predicted, recorded_routes=routes
            )
            if result["abstain"]:
                continue
            by_budget = prefix_route_coverage(episode, edge_list, prefix_budgets)
            length = len(episode.visible["query_relations"])
            for bucket in (
                buckets.setdefault(stratum, new_bucket()),
                by_length.setdefault(stratum, {}).setdefault(length, new_bucket()),
            ):
                bucket["n"] += 1
                bucket["correct"] += int(result["exact_correct"])
                bucket["predicted"][predicted] += 1
                for b, coverage in by_budget.items():
                    bucket["route_complete_at"][b] += int(coverage["route_complete"])
                if by_budget[budget]["route_complete"]:
                    bucket["correct_given_route_complete"] += int(
                        result["exact_correct"]
                    )
        pending.clear()

    for item in screening:
        pending.append(item)
        if len(pending) == microbatch:
            flush()
    flush()
    if was_training:
        model.train()

    def summarize(bucket: dict[str, Any]) -> dict[str, Any]:
        total = bucket["n"]
        correct = bucket["correct"]
        route_complete = bucket["route_complete_at"][budget]
        return {
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
            "route_complete": route_complete,
            "route_complete_fraction": route_complete / total if total else None,
            "route_complete_at": {
                str(b): count for b, count in bucket["route_complete_at"].items()
            },
            "exact_given_route_complete": (
                bucket["correct_given_route_complete"] / route_complete
                if route_complete
                else None
            ),
        }

    report = {}
    for stratum, bucket in buckets.items():
        report[stratum] = summarize(bucket)
        report[stratum]["by_path_length"] = {
            str(length): summarize(lengths)
            for length, lengths in sorted(by_length[stratum].items())
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
        "--input-ablation",
        choices=list(INPUT_ABLATIONS),
        default=NONE,
        help="model-input ablation applied identically to every training and "
        "screening episode; `no_similarity` holds query_similarity_ppm at a "
        "constant (Track N structural-only screening)",
    )
    parser.add_argument(
        "--save-checkpoint",
        action="store_true",
        help="save model weights at completion for a downstream inference-only "
        "diagnostic; off by default because most probe runs are never inspected "
        "after their loss curve is read",
    )
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

    screening = load_screening(Path(args.screen_root), args.input_ablation)
    checkpoints = sorted(
        {u for u in args.eval_at if 0 < u <= args.updates}
        | set(range(args.eval_every, args.updates + 1, args.eval_every))
        | {args.updates}
    )

    (output / "probe.json").write_text(
        json.dumps(
            {
                "record_kind": "read_run_learning_probe_not_preregistered",
                "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "git_head": _git_head(),
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
                "input_ablation": args.input_ablation,
                "masked_similarity_ppm": masked_similarity_ppm(args.input_ablation),
                "emits_training_receipt": False,
                "touches_holdout": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    batches = _batches(
        ablated_episodes(_cycle_episodes(Path(args.train_root)), args.input_ablation),
        microbatch,
    )
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
                    validate_model_input_fields(episode)
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
                    f"rc={gated.get('route_complete_fraction')} "
                    f"classes={gated.get('distinct_classes')} "
                    f"H={gated.get('prediction_entropy_nats')}",
                    flush=True,
                )
    finally:
        log.close()
        screen_log.close()
    if args.save_checkpoint:
        # Diagnostic-only weights, not an official checkpoint: it carries none
        # of `training.py`'s receipt/freeze/P0 bindings and must never be loaded
        # by `evaluate_checkpoint`, which would refuse it on the missing fields
        # anyway. Shaped closely enough to the real checkpoint (same field
        # names for arm/stage/model_seed/budget) that a diagnostic script can
        # treat it uniformly with an official one if that's ever convenient.
        torch.save(
            {
                "state_dict": model.state_dict(),
                "arm": args.arm,
                "stage": "diagnostic",
                "model_seed": args.model_seed,
                "budget": args.budget,
                "update_count": args.updates,
                "training_config_sha256": contracts["training_config_sha256"],
                "input_ablation": args.input_ablation,
                "masked_similarity_ppm": masked_similarity_ppm(args.input_ablation),
            },
            output / "checkpoint.pt",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
