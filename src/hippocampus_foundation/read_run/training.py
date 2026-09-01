"""Fixed-step training and evaluation runners for the READ arms."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import (
    canonical_sha256,
    dump_pretty,
    load_json,
)

from .contracts import validate_preregistration
from .errors import IntegrityGateError, TrainingBlocked
from .evaluation import decode_best_routes, score_prediction, summarize_predictions
from .freeze import load_and_validate_code_freeze
from .gates import select_main_budget
from .generator import GeneratedEpisode
from .io import (
    read_generated_split,
    validate_generated_split_artifacts,
    validate_model_input_fields,
)
from .model import build_read_model, require_torch, trainable_parameter_count


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _exclusive_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        encoded = dump_pretty(value).encode()
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_training_gate(report: dict[str, Any], *, budget: int, stage: str) -> None:
    if report.get("record_kind") != "read_run_p0_report":
        raise TrainingBlocked("training requires a READ-run P0 report")
    authorization_field = (
        "screening_training_authorized"
        if stage == "screening"
        else "training_authorized"
    )
    if not report.get(authorization_field):
        raise TrainingBlocked("all seven READ-run P0 gates must pass before training")
    if stage == "main" and report.get("selected_main_budget") != budget:
        raise TrainingBlocked(
            "requested budget differs from the coverage-selected budget"
        )
    if stage == "screening" and budget not in {16, 32, 64, 128}:
        raise TrainingBlocked("screening budget is not preregistered")
    gates = report.get("gates")
    if (
        not isinstance(gates, list)
        or len(gates) != 7
        or not all(item.get("passed") for item in gates)
    ):
        raise TrainingBlocked("P0 report does not contain seven passed gates")
    pool = [item for item in gates if item.get("gate") == "direct_pool_invariance"]
    if len(pool) != 1:
        raise TrainingBlocked("P0 report lacks one DIRECT-pool gate")
    try:
        reproduced_budget = select_main_budget(pool[0])
    except IntegrityGateError:
        reproduced_budget = None
    if reproduced_budget != report.get("selected_main_budget"):
        raise TrainingBlocked("P0 selected budget is not reproducible from coverage")


def _validate_training_dataset(
    root: Path,
    *,
    p0_report: dict[str, Any],
    expected_seed_commitment: str,
) -> dict[str, Any]:
    _public, manifest, _artifacts = validate_generated_split_artifacts(
        root, expected_seed_commitment=expected_seed_commitment
    )
    if manifest.get("split") != "train":
        raise TrainingBlocked("model fitting accepts only a generated train split")
    if manifest.get("episode_count") != 150_000:
        raise TrainingBlocked("training split does not have the preregistered size")
    gamma_key = f"{float(manifest['requested_gamma']):.1f}"
    expected_binding = (
        p0_report.get("dataset_bindings", {}).get("train", {}).get(gamma_key)
    )
    if expected_binding != canonical_sha256(manifest):
        raise TrainingBlocked("training split is not the exact P0-bound dataset")
    return manifest


def _cycle_episodes(root: Path) -> Iterator[GeneratedEpisode]:
    while True:
        yield from read_generated_split(root)


def _batches(
    iterator: Iterator[GeneratedEpisode], size: int
) -> Iterator[list[GeneratedEpisode]]:
    while True:
        batch = [next(iterator) for _ in range(size)]
        yield batch


def _state_digest(model: Any) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode())
        value = tensor.detach().cpu().contiguous()
        digest.update(str(value.dtype).encode())
        digest.update(str(tuple(value.shape)).encode())
        digest.update(value.numpy().tobytes())
    return f"sha256:{digest.hexdigest()}"


def _labels(torch: Any, episodes: Sequence[GeneratedEpisode], device: Any) -> Any:
    return torch.tensor(
        [
            0 if episode.hidden["abstain"] else episode.hidden["gold_assertion_mask"]
            for episode in episodes
        ],
        dtype=torch.long,
        device=device,
    )


def _edge_targets(
    torch: Any,
    episodes: Sequence[GeneratedEpisode],
    edge_ids: Sequence[Sequence[int]],
    device: Any,
) -> Any:
    rows = []
    for episode, selected in zip(episodes, edge_ids, strict=True):
        positives = {
            edge_id for route in episode.hidden["valid_routes"] for edge_id in route
        }
        rows.append([1.0 if edge_id in positives else 0.0 for edge_id in selected])
    return torch.tensor(rows, dtype=torch.float32, device=device)


def train_arm(
    *,
    arm: str,
    stage: str,
    model_seed: int,
    budget: int,
    train_root: Path,
    p0_report_path: Path,
    code_freeze_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Run the fixed optimizer schedule and retain every update loss."""

    if arm not in {"TRAV", "DIRECT"}:
        raise TrainingBlocked("arm must be TRAV or DIRECT")
    if stage not in {"screening", "main"}:
        raise TrainingBlocked("run stage must be screening or main")
    if model_seed not in {1729, 2718, 3141}:
        raise TrainingBlocked("model seed is not preregistered")
    contracts = validate_preregistration()
    config = contracts["training_config"]
    p0_report = load_json(p0_report_path)
    if not isinstance(p0_report, dict):
        raise TrainingBlocked("P0 report must be an object")
    freeze = load_and_validate_code_freeze(
        code_freeze_path, p0_report_path=p0_report_path
    )
    _validate_training_gate(p0_report, budget=budget, stage=stage)
    dataset_manifest = _validate_training_dataset(
        train_root,
        p0_report=p0_report,
        expected_seed_commitment=contracts["preregistration"]["heldout_seed_sha256"],
    )
    if output_root.exists() or output_root.is_symlink():
        raise TrainingBlocked("refusing to overwrite a training run")

    torch, _nn, functional = require_torch()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.manual_seed(model_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(model_seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_read_model(config).to(device)
    parameter_count = trainable_parameter_count(model)
    initialization_sha256 = _state_digest(model)
    training = config["training"]
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    microbatch = int(training["microbatch_size"])
    accumulation = int(training["gradient_accumulation_steps"])
    update_count = int(training["update_count"])
    episode_iterator = _cycle_episodes(train_root)
    batches = _batches(episode_iterator, microbatch)
    use_bf16 = bool(
        device.type == "cuda"
        and hasattr(torch.cuda, "is_bf16_supported")
        and torch.cuda.is_bf16_supported()
    )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    os.chmod(temporary, 0o700)
    log_path = temporary / "updates.jsonl"
    log = log_path.open("x", encoding="utf-8")
    try:
        model.train()
        for update in range(update_count):
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
                    output = model(
                        [episode.visible for episode in episodes],
                        arm=arm,
                        budget=budget,
                    )
                    answer_loss = functional.cross_entropy(
                        output["logits"], _labels(torch, episodes, device)
                    )
                    edge_loss = functional.binary_cross_entropy_with_logits(
                        output["scores"],
                        _edge_targets(torch, episodes, output["edge_ids"], device),
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
            record = {
                "update": update + 1,
                "answer_loss": update_answer,
                "edge_loss": update_edge,
                "gradient_norm": float(gradient_norm),
            }
            log.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            log.flush()
        os.fsync(log.fileno())
        log.close()
        checkpoint_path = temporary / "checkpoint.pt"
        torch.save(
            {
                "state_dict": model.state_dict(),
                "arm": arm,
                "stage": stage,
                "model_seed": model_seed,
                "budget": budget,
                "training_config_sha256": contracts["training_config_sha256"],
            },
            checkpoint_path,
        )
        receipt = {
            "schema_version": "1.0.0",
            "record_kind": "read_training_receipt",
            "arm": arm,
            "stage": stage,
            "model_seed": model_seed,
            "gamma": dataset_manifest["requested_gamma"],
            "budget": budget,
            "parameter_count": parameter_count,
            "initialization_sha256": initialization_sha256,
            "final_state_sha256": _state_digest(model),
            "checkpoint_sha256": _sha256_path(checkpoint_path),
            "updates_sha256": _sha256_path(log_path),
            "update_count": update_count,
            "training_config_sha256": contracts["training_config_sha256"],
            "p0_report_sha256": canonical_sha256(p0_report),
            "code_freeze_sha256": canonical_sha256(freeze),
            "train_manifest_sha256": canonical_sha256(dataset_manifest),
        }
        _exclusive_json(temporary / "receipt.json", receipt)
        os.replace(temporary, output_root)
        return receipt
    except Exception as exc:
        if not log.closed:
            log.flush()
            log.close()
        failure = {
            "schema_version": "1.0.0",
            "record_kind": "read_training_failure",
            "arm": arm,
            "stage": stage,
            "model_seed": model_seed,
            "gamma": dataset_manifest["requested_gamma"],
            "budget": budget,
            "status": "failed",
            "failure_type": type(exc).__name__,
            "training_config_sha256": contracts["training_config_sha256"],
            "p0_report_sha256": canonical_sha256(p0_report),
            "code_freeze_sha256": canonical_sha256(freeze),
            "train_manifest_sha256": canonical_sha256(dataset_manifest),
        }
        _exclusive_json(temporary / "failure.json", failure)
        failed_root = output_root.parent / f"{output_root.name}.failed"
        if failed_root.exists() or failed_root.is_symlink():
            raise TrainingBlocked(
                "failed-run destination already exists; manual audit required"
            ) from exc
        os.replace(temporary, failed_root)
        raise


def evaluate_checkpoint(
    *,
    checkpoint_path: Path,
    receipt_path: Path,
    dataset_root: Path,
    expected_split: str,
    code_freeze_path: Path | None = None,
    p0_report_path: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contracts = validate_preregistration()
    config = contracts["training_config"]
    receipt = load_json(receipt_path)
    if (
        not isinstance(receipt, dict)
        or receipt.get("record_kind") != "read_training_receipt"
    ):
        raise IntegrityGateError("evaluation requires a training receipt")
    if expected_split not in {"screen", "holdout"}:
        raise IntegrityGateError("evaluation split is not preregistered")
    if code_freeze_path is None or p0_report_path is None:
        raise IntegrityGateError("evaluation requires freeze and P0 evidence")
    p0 = load_json(p0_report_path)
    if not isinstance(p0, dict):
        raise IntegrityGateError("P0 report must be an object")
    freeze = load_and_validate_code_freeze(
        code_freeze_path, p0_report_path=p0_report_path
    )
    _public, manifest, _artifacts = validate_generated_split_artifacts(
        dataset_root,
        expected_seed_commitment=contracts["preregistration"]["heldout_seed_sha256"],
    )
    if manifest.get("split") != expected_split:
        raise IntegrityGateError("evaluation dataset split differs from the request")
    expected_count = 2_000 if expected_split == "screen" else 15_000
    if manifest.get("episode_count") != expected_count:
        raise IntegrityGateError("evaluation dataset has the wrong preregistered size")
    if (
        receipt.get("training_config_sha256") != contracts["training_config_sha256"]
        or receipt.get("p0_report_sha256") != canonical_sha256(p0)
        or receipt.get("code_freeze_sha256") != canonical_sha256(freeze)
    ):
        raise IntegrityGateError("training receipt is bound to another run contract")
    stage = "screening" if expected_split == "screen" else "main"
    if receipt.get("stage") != stage:
        raise IntegrityGateError("training receipt stage differs from evaluation split")
    _validate_training_gate(p0, budget=int(receipt["budget"]), stage=stage)
    train_binding = (
        p0.get("dataset_bindings", {})
        .get("train", {})
        .get(f"{float(receipt['gamma']):.1f}")
    )
    if receipt.get("train_manifest_sha256") != train_binding:
        raise IntegrityGateError("training receipt is bound to another train split")
    if expected_split == "screen":
        screen_binding = (
            p0.get("dataset_bindings", {})
            .get("screen", {})
            .get(f"{float(manifest['requested_gamma']):.1f}")
        )
        if screen_binding != canonical_sha256(manifest):
            raise IntegrityGateError(
                "screening split is not the exact P0-bound dataset"
            )
    if expected_split == "holdout":
        opening = load_json(dataset_root / "holdout-opening.json")
        if not isinstance(opening, dict):
            raise IntegrityGateError("holdout opening evidence must be an object")
        expected_opening = {
            "schema_version",
            "record_kind",
            "opened_at",
            "gamma",
            "code_freeze_sha256",
            "p0_report_sha256",
            "private_manifest_sha256",
            "opened_once",
        }
        if (
            set(opening) != expected_opening
            or opening.get("record_kind") != "read_holdout_opening_receipt"
        ):
            raise IntegrityGateError("holdout opening fields differ")
        if (
            not opening["opened_once"]
            or opening["gamma"] != manifest["requested_gamma"]
            or opening["code_freeze_sha256"] != canonical_sha256(freeze)
            or opening["p0_report_sha256"] != canonical_sha256(p0)
            or opening["private_manifest_sha256"] != canonical_sha256(manifest)
        ):
            raise IntegrityGateError("holdout opening bindings differ")
    if _sha256_path(checkpoint_path) != receipt["checkpoint_sha256"]:
        raise IntegrityGateError("training checkpoint digest changed")
    torch, _nn, _functional = require_torch()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_read_model(config).to(device)
    saved = torch.load(checkpoint_path, map_location=device, weights_only=True)
    if not isinstance(saved, dict) or set(saved) != {
        "state_dict",
        "arm",
        "stage",
        "model_seed",
        "budget",
        "training_config_sha256",
    }:
        raise IntegrityGateError("training checkpoint fields differ")
    for field in ("arm", "stage", "model_seed", "budget", "training_config_sha256"):
        if saved[field] != receipt[field]:
            raise IntegrityGateError(f"checkpoint and receipt disagree on {field}")
    model.load_state_dict(saved["state_dict"])
    model.eval()
    predictions: list[dict[str, Any]] = []
    microbatch = int(config["training"]["microbatch_size"])
    pending: list[GeneratedEpisode] = []

    def score_batch(episodes: list[GeneratedEpisode]) -> None:
        with torch.no_grad():
            output = model(
                [episode.visible for episode in episodes],
                arm=receipt["arm"],
                budget=receipt["budget"],
            )
        classes = output["logits"].argmax(dim=1).detach().cpu().tolist()
        score_rows = output["scores"].detach().float().cpu().tolist()
        for episode, predicted, edge_ids, scores in zip(
            episodes,
            classes,
            output["edge_ids"],
            score_rows,
            strict=True,
        ):
            routes = decode_best_routes(episode.visible, edge_ids, scores)
            result = score_prediction(
                episode, predicted_class=predicted, recorded_routes=routes
            )
            predictions.append(
                {
                    "episode_id": episode.episode_id,
                    "recorded_routes": routes,
                    **result,
                }
            )

    for episode in read_generated_split(dataset_root):
        validate_model_input_fields(episode)
        pending.append(episode)
        if len(pending) == microbatch:
            score_batch(pending)
            pending = []
    if pending:
        score_batch(pending)
    summary = {
        "schema_version": "1.0.0",
        "record_kind": "read_evaluation_summary",
        "arm": receipt["arm"],
        "stage": receipt["stage"],
        "model_seed": receipt["model_seed"],
        "gamma": manifest["requested_gamma"],
        "budget": receipt["budget"],
        "split": manifest["split"],
        "training_receipt_sha256": canonical_sha256(receipt),
        "dataset_manifest_sha256": canonical_sha256(manifest),
        "p0_report_sha256": canonical_sha256(p0),
        "code_freeze_sha256": canonical_sha256(freeze),
        **summarize_predictions(predictions),
    }
    return summary, predictions
