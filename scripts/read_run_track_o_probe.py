"""Track O screening probe: path-scoped traversal v2 against v1 at equal capacity.

Not preregistered as an arm and deliberately unofficial: it emits no training
receipt, binds no code freeze, and never opens a holdout. It is the Track O
analogue of `read_run_learning_probe.py` and reuses that script's Wilson bound,
entropy, checkpoint schedule, JSONL schema and determinism block.

Two arms run through one harness so the comparison is not confounded by the
runner: `TRAVV2` is `model_v2.build_read_model_v2`, and `TRAVV1` is the frozen
v1 `build_read_model` on the same v2 data at the same budget, which is the
direct control for "did the path-scoped redesign help". v1 always spends its
budget by construction, so its examined-set precision is capped near 0.04 —
that is the measurement, not a defect of the harness.

Screening reports both primary quantities: route-completeness (does the examined
set contain complete routes to every target) and examined-set precision (what
fraction of the examined edges lie on a route), plus the stop-reason mix, read
against the model-free frontier in `policy_ladder.json`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from read_run_learning_probe import (  # noqa: E402
    shannon_entropy,
    wilson_lower_bound,
)

from hippocampus_foundation.read_run.coverage import route_coverage  # noqa: E402
from hippocampus_foundation.read_run.evaluation import (  # noqa: E402
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import (  # noqa: E402
    coverage_stratum,
    target_hop_distance,
)
from hippocampus_foundation.read_run.io_v2 import (  # noqa: E402
    read_generated_split_v2,
    validate_generated_split_artifacts_v2,
)
from hippocampus_foundation.read_run.model import (  # noqa: E402
    build_read_model,
    require_torch,
)
from hippocampus_foundation.read_run.model_v2 import (  # noqa: E402
    build_read_model_v2,
    expected_trainable_parameter_count_v2,
    route_prefixes,
    walker_expansions,
)
from hippocampus_foundation.read_run.training import _batches, _labels  # noqa: E402
from hippocampus_foundation.read_run.training_v2 import (  # noqa: E402
    edge_targets_ragged,
    examined_set_precision,
    labels_v2,
    masked_edge_loss,
    supervision_source,
)

GATED = "hops_2_4"
V1_PARAMETERS = 10_257_937
ARMS = ("TRAVV2", "TRAVV1")


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def load_split(root: Path) -> list[tuple[Any, str]]:
    validate_generated_split_artifacts_v2(root)
    return [
        (episode, coverage_stratum(target_hop_distance(episode)))
        for episode in read_generated_split_v2(root)
    ]


def cycle(pairs: list[tuple[Any, str]]) -> Iterator[Any]:
    while True:
        for episode, _stratum in pairs:
            yield episode


def run_arm(torch, model, episodes, *, arm: str, budget: int, supplied=None):
    """One forward pass for either arm, normalised to the v2 return shape."""

    visible = [episode.visible for episode in episodes]
    if arm == "TRAVV2":
        return model(visible, budget=budget, supplied=supplied)
    output = model(visible, arm="TRAV", budget=budget)
    routes = [
        decode_best_routes(
            episode.visible, output["edge_ids"][slot], output["scores"][slot].tolist()
        )
        for slot, episode in enumerate(episodes)
    ]
    return {
        "logits": output["logits"],
        "scores": output["scores"],
        "score_mask": torch.ones_like(output["scores"], dtype=torch.bool),
        "edge_ids": output["edge_ids"],
        "routes": routes,
        "stop_reason": ["budget_cap"] * len(episodes),
        "examined_count": [len(values) for values in output["edge_ids"]],
    }


def score_screening(torch, model, screening, *, arm: str, budget: int, microbatch: int):
    """Route-completeness, precision, stop mix and exact accuracy, per stratum."""

    buckets: dict[str, dict[str, Any]] = {}
    model.eval()
    with torch.no_grad():
        for start in range(0, len(screening), microbatch):
            chunk = screening[start : start + microbatch]
            episodes = [episode for episode, _stratum in chunk]
            output = run_arm(torch, model, episodes, arm=arm, budget=budget)
            predicted = output["logits"].argmax(dim=-1).tolist()
            precisions = examined_set_precision(episodes, output["edge_ids"])
            for slot, (episode, stratum) in enumerate(chunk):
                if episode.hidden["abstain"]:
                    continue
                bucket = buckets.setdefault(
                    stratum,
                    {
                        "n": 0,
                        "correct": 0,
                        "route_complete": 0,
                        "precision": 0.0,
                        "examined": 0,
                        "stops": Counter(),
                        "classes": Counter(),
                        "by_path_length": {},
                    },
                )
                coverage = route_coverage(episode, output["edge_ids"][slot])
                scored = score_prediction(
                    episode,
                    predicted_class=predicted[slot],
                    recorded_routes=output["routes"][slot],
                )
                bucket["n"] += 1
                bucket["correct"] += int(scored["exact_correct"])
                bucket["route_complete"] += int(coverage["route_complete"])
                bucket["precision"] += precisions[slot]
                bucket["examined"] += output["examined_count"][slot]
                bucket["stops"][output["stop_reason"][slot]] += 1
                bucket["classes"][predicted[slot]] += 1
                length = str(len(episode.visible["query_relations"]))
                per_length = bucket["by_path_length"].setdefault(
                    length, {"n": 0, "route_complete": 0, "correct": 0}
                )
                per_length["n"] += 1
                per_length["route_complete"] += int(coverage["route_complete"])
                per_length["correct"] += int(scored["exact_correct"])
    model.train()
    report = {}
    for stratum, bucket in buckets.items():
        n = bucket["n"]
        report[stratum] = {
            "n": n,
            "correct": bucket["correct"],
            "exact_set_accuracy": bucket["correct"] / n,
            "wilson_lower_bound": wilson_lower_bound(bucket["correct"], n),
            "route_complete": bucket["route_complete"],
            "route_complete_fraction": bucket["route_complete"] / n,
            "route_complete_wilson_lower_bound": wilson_lower_bound(
                bucket["route_complete"], n
            ),
            "precision_mean": bucket["precision"] / n,
            "examined_mean": bucket["examined"] / n,
            "stop_reasons": dict(bucket["stops"]),
            "distinct_classes": len(bucket["classes"]),
            "prediction_entropy_nats": shannon_entropy(bucket["classes"]),
            "modal_fraction": max(bucket["classes"].values()) / n,
            "by_path_length": bucket["by_path_length"],
        }
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=ARMS)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--train-root", required=True)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--config", default="experiments/track_o_v1/training-config.o1.json"
    )
    parser.add_argument("--budget", type=int, default=64)
    parser.add_argument("--gamma", type=float, default=0.4)
    parser.add_argument("--model-seed", type=int, default=1729)
    parser.add_argument("--updates", type=int, default=None)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--eval-at", type=int, nargs="*", default=[100, 250])
    parser.add_argument("--save-checkpoint", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    for path in (args.train_root, args.screen_root, args.output):
        if "holdout" in str(path) or "heldout" in str(path):
            print("refusing a holdout path", file=sys.stderr)
            return 2
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        print("refusing to overwrite a probe run", file=sys.stderr)
        return 2
    output.mkdir(parents=True)
    os.chmod(output, 0o700)

    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    training = config["training"]
    updates = (
        args.updates if args.updates is not None else int(training["update_count"])
    )

    torch, _nn, functional = require_torch()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.manual_seed(args.model_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.model_seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if args.arm == "TRAVV2":
        model = build_read_model_v2(config).to(device)
    else:
        from hippocampus_foundation.read_run.contracts import validate_preregistration

        model = build_read_model(validate_preregistration()["training_config"]).to(
            device
        )
    parameters = sum(p.numel() for p in model.parameters() if p.requires_grad)

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
    schedule = training["supervision_schedule"]

    screening = load_split(Path(args.screen_root))
    train_pairs = load_split(Path(args.train_root))
    checkpoints = sorted(
        {u for u in args.eval_at if 0 < u <= updates}
        | set(range(args.eval_every, updates + 1, args.eval_every))
        | {updates}
    )

    (output / "probe.json").write_text(
        json.dumps(
            {
                "record_kind": "read_run_track_o_probe_not_preregistered",
                "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "git_head": _git_head(),
                "arm": args.arm,
                "generator_cell": args.cell,
                "gamma": args.gamma,
                "budget": args.budget,
                "model_seed": args.model_seed,
                "requested_update_count": updates,
                "config_path": str(config_path),
                "config_sha256": "sha256:"
                + __import__("hashlib").sha256(config_path.read_bytes()).hexdigest(),
                "trainable_parameters": parameters,
                "v1_parameters": V1_PARAMETERS,
                "capacity_relative_difference": abs(parameters - V1_PARAMETERS)
                / V1_PARAMETERS,
                "expected_parameters_closed_form": (
                    expected_trainable_parameter_count_v2(config)
                    if args.arm == "TRAVV2"
                    else None
                ),
                "train_root": str(args.train_root),
                "screen_root": str(args.screen_root),
                "train_episode_count": len(train_pairs),
                "screening_episode_count": len(screening),
                "device": device.type,
                "bf16_autocast": use_bf16,
                "evaluation_checkpoints": checkpoints,
                "supervision_schedule": schedule,
                "emits_training_receipt": False,
                "touches_holdout": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    batches = _batches(cycle(train_pairs), microbatch)
    log = (output / "updates.jsonl").open("x", encoding="utf-8")
    screen_log = (output / "screen.jsonl").open("x", encoding="utf-8")
    try:
        model.train()
        for update in range(updates):
            source = (
                supervision_source(update, updates, schedule)
                if args.arm == "TRAVV2"
                else "on_policy"
            )
            optimizer.zero_grad(set_to_none=True)
            update_answer = 0.0
            update_edge = 0.0
            for _step in range(accumulation):
                episodes = next(batches)
                supplied = None
                if source == "gold":
                    supplied = [
                        route_prefixes(e.visible, e.hidden["valid_routes"])
                        for e in episodes
                    ]
                elif source == "walker":
                    supplied = [
                        walker_expansions(e.visible, args.budget) for e in episodes
                    ]
                context = (
                    torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                    if use_bf16
                    else contextlib.nullcontext()
                )
                with context:
                    out = run_arm(
                        torch,
                        model,
                        episodes,
                        arm=args.arm,
                        budget=args.budget,
                        supplied=supplied,
                    )
                    labels = (
                        labels_v2(torch, episodes, device)
                        if args.arm == "TRAVV2"
                        else _labels(torch, episodes, device)
                    )
                    answer_loss = functional.cross_entropy(out["logits"], labels)
                    width = out["scores"].shape[1]
                    targets, mask = edge_targets_ragged(
                        torch, episodes, out["edge_ids"], width, device
                    )
                    edge_loss = masked_edge_loss(
                        torch, functional, out["scores"], targets, mask
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
                        "supervision": source,
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
                gated = report.get(GATED, {})
                print(
                    f"[{args.arm}/{args.cell}] update {update + 1}/{updates} "
                    f"loss={update_answer:.4f} src={source} "
                    f"rc={gated.get('route_complete_fraction')} "
                    f"prec={gated.get('precision_mean')} "
                    f"examined={gated.get('examined_mean')} "
                    f"acc={gated.get('exact_set_accuracy')}",
                    flush=True,
                )
    finally:
        log.close()
        screen_log.close()
    if args.save_checkpoint:
        torch.save(
            {
                "state_dict": model.state_dict(),
                "arm": args.arm,
                "stage": "diagnostic",
                "model_seed": args.model_seed,
                "budget": args.budget,
                "generator_cell": args.cell,
                "update_count": updates,
            },
            output / "checkpoint.pt",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
