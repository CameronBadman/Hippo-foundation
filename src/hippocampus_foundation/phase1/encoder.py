"""Frozen GTE encoder identity, text recipe, and optional inference adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256

from .contracts import (
    ENCODER_VERIFICATION_METHOD_V2,
    validate_encoder_spec,
)
from .errors import Phase1IntegrityError, Phase1ValidationError
from .io import file_identity, file_identity_following_registered_symlink


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def render_text(title: str, body: str) -> str:
    if not isinstance(title, str) or not title:
        raise Phase1ValidationError("encoder title must be a non-empty string")
    if not isinstance(body, str):
        raise Phase1ValidationError("encoder body must be a string")
    return f"{title}\n\n{body}" if body else title


def select_context(token_count: int, spec: dict[str, Any]) -> dict[str, Any]:
    """Record the frozen 2048-token choice relative to the 8192-token capacity."""

    validate_encoder_spec(spec)
    if token_count < 0:
        raise Phase1ValidationError("token_count cannot be negative")
    selected = spec["default_context_tokens"]
    maximum = spec["maximum_context_tokens"]
    return {
        "selected_context_tokens": selected,
        "maximum_supported_tokens": maximum,
        "requires_truncation": token_count > selected,
        "exceeds_model_capacity": token_count > maximum,
        "chunking": False,
    }


def _verify_bakeoff(report: dict[str, Any], spec: dict[str, Any]) -> None:
    conclusions = report.get("conclusions", {})
    expected = {
        "default_encoder": "gte-modernbert",
        "default_model_id": spec["model_id"],
        "default_context": "2048",
        "default_dimension": spec["dimension"],
    }
    for field, value in expected.items():
        if conclusions.get(field) != value:
            raise Phase1IntegrityError(
                f"encoder bake-off conclusion mismatch for {field}: "
                f"expected {value!r}, observed {conclusions.get(field)!r}"
            )
    metrics = conclusions.get("context_analysis", {}).get("selected_metrics", {})
    declared = spec["bakeoff_decision"]
    metric_bindings = {
        "graph_distance_auc": declared["adjacent_hop_auc"],
        "graph_neighbour_recall_at_50": declared["neighbour_recall_at_50"],
        "collision_rate": declared["collision_rate"],
    }
    for field, value in metric_bindings.items():
        if metrics.get(field) != value:
            raise Phase1IntegrityError(f"encoder bake-off metric mismatch: {field}")
    if conclusions.get("shortlist_weighted_score") != declared["weighted_score"]:
        raise Phase1IntegrityError("encoder bake-off weighted score mismatch")
    if (
        report.get("experiment", {}).get("experiment", {}).get("sample_size")
        != declared["sample_pages"]
    ):
        raise Phase1IntegrityError("encoder bake-off sample size mismatch")
    metadata = (
        report.get("provenance", {}).get("model_metadata", {}).get("gte-modernbert", {})
    )
    if metadata.get("model_revision") != spec["revision"]:
        raise Phase1IntegrityError("encoder bake-off revision mismatch")
    if metadata.get("training_mode") is not False or metadata.get("frozen") is not True:
        raise Phase1IntegrityError(
            "encoder bake-off was not recorded as frozen inference"
        )


def _verify_snapshot_layout(snapshot: Path, expected_paths: Sequence[str]) -> set[str]:
    """Return the complete file set after rejecting undeclared snapshot entries."""

    if snapshot.is_symlink():
        raise Phase1IntegrityError(f"encoder snapshot root is a symlink: {snapshot}")
    if not snapshot.is_dir():
        raise Phase1IntegrityError(f"encoder snapshot is not a directory: {snapshot}")

    expected_files: set[str] = set()
    expected_directories: set[str] = set()
    for value in expected_paths:
        relative = Path(value)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise Phase1ValidationError(f"unsafe encoder asset path: {relative}")
        rendered = relative.as_posix()
        if rendered in expected_files:
            raise Phase1ValidationError(f"duplicate encoder asset path: {rendered}")
        expected_files.add(rendered)
        expected_directories.update(
            Path(*relative.parts[:index]).as_posix()
            for index in range(1, len(relative.parts))
        )

    observed_files: set[str] = set()
    observed_directories: set[str] = set()
    pending = [snapshot]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise Phase1IntegrityError(
                f"cannot enumerate encoder snapshot {directory}: {exc}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(snapshot).as_posix()
            try:
                if entry.is_symlink():
                    resolved = path.resolve(strict=True)
                    if resolved.is_dir():
                        raise Phase1IntegrityError(
                            f"encoder snapshot contains a directory symlink: {relative}"
                        )
                    if not resolved.is_file():
                        raise Phase1IntegrityError(
                            f"encoder snapshot symlink is not a regular file: {relative}"
                        )
                    observed_files.add(relative)
                elif entry.is_dir(follow_symlinks=False):
                    observed_directories.add(relative)
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    observed_files.add(relative)
                else:
                    raise Phase1IntegrityError(
                        f"encoder snapshot contains a special filesystem entry: {relative}"
                    )
            except OSError as exc:
                raise Phase1IntegrityError(
                    f"cannot inspect encoder snapshot entry {relative}: {exc}"
                ) from exc

    missing_files = sorted(expected_files - observed_files)
    unexpected_files = sorted(observed_files - expected_files)
    missing_directories = sorted(expected_directories - observed_directories)
    unexpected_directories = sorted(observed_directories - expected_directories)
    if (
        missing_files
        or unexpected_files
        or missing_directories
        or unexpected_directories
    ):
        raise Phase1IntegrityError(
            "encoder snapshot asset set mismatch: "
            f"missing_files={missing_files}, unexpected_files={unexpected_files}, "
            f"missing_directories={missing_directories}, "
            f"unexpected_directories={unexpected_directories}"
        )
    return observed_files


def verify_encoder_assets(
    *,
    spec: dict[str, Any],
    snapshot: Path,
    bakeoff_report: Path,
    snapshot_id: str | None = None,
    verified_at: str | None = None,
) -> dict[str, Any]:
    validate_encoder_spec(spec)
    expected_paths = [item["path"] for item in spec["assets"]]
    observed_paths = _verify_snapshot_layout(snapshot, expected_paths)
    report_identity = file_identity(bakeoff_report)
    if report_identity["sha256"] != spec["bakeoff_report_sha256"]:
        raise Phase1IntegrityError("encoder bake-off report digest mismatch")
    try:
        with bakeoff_report.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase1IntegrityError(
            f"cannot read encoder bake-off report: {exc}"
        ) from exc
    if not isinstance(report, dict):
        raise Phase1IntegrityError("encoder bake-off report is not an object")
    _verify_bakeoff(report, spec)
    if file_identity(bakeoff_report) != report_identity:
        raise Phase1IntegrityError("encoder bake-off report changed while verifying")

    observed_assets: list[dict[str, Any]] = []
    for expected in sorted(spec["assets"], key=lambda item: item["path"]):
        relative = Path(expected["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise Phase1ValidationError(f"unsafe encoder asset path: {relative}")
        observed = file_identity_following_registered_symlink(snapshot / relative)
        if observed != {"bytes": expected["bytes"], "sha256": expected["sha256"]}:
            raise Phase1IntegrityError(f"encoder asset mismatch: {relative}")
        observed_assets.append({"path": expected["path"], **observed})

    # Recheck both the byte identities and directory topology so a concurrent
    # mutation cannot make a mixed-time snapshot look like one verified set.
    for expected, observed in zip(
        sorted(spec["assets"], key=lambda item: item["path"]),
        observed_assets,
        strict=True,
    ):
        repeated = file_identity_following_registered_symlink(
            snapshot / expected["path"]
        )
        if repeated != {"bytes": observed["bytes"], "sha256": observed["sha256"]}:
            raise Phase1IntegrityError(
                f"encoder asset changed while verifying: {expected['path']}"
            )
    if _verify_snapshot_layout(snapshot, expected_paths) != observed_paths:
        raise Phase1IntegrityError("encoder snapshot layout changed while verifying")

    executable_code = sorted(path for path in observed_paths if path.endswith(".py"))
    result = {
        "schema_version": "2.0.0",
        "record_kind": "encoder_verification",
        "verification_method": ENCODER_VERIFICATION_METHOD_V2,
        "encoder_id": spec["encoder_id"],
        "spec_sha256": canonical_sha256(spec),
        "snapshot_id": snapshot_id
        or f"huggingface:{spec['model_id']}@{spec['revision']}",
        "revision": spec["revision"],
        "bakeoff_report_sha256": report_identity["sha256"],
        "assets": observed_assets,
        "asset_set_exact": True,
        "executable_model_code_files": executable_code,
        "verified_at": verified_at or _utc_now(),
        "verified": not executable_code,
    }
    # Imported here to keep the frozen v1 contract module independent of the
    # current gate while still validating evidence before it leaves this API.
    from .v2 import validate_encoder_verification_v2

    validate_encoder_verification_v2(result)
    return result


def encode_frozen(
    texts: Sequence[str],
    *,
    spec: dict[str, Any],
    snapshot: Path,
    device: str = "cuda:0",
    batch_size: int = 8,
) -> Any:
    """Run the frozen encoder. Heavy dependencies are imported only on use."""

    validate_encoder_spec(spec)
    if not texts:
        raise Phase1ValidationError("encoder input cannot be empty")
    if batch_size < 1:
        raise Phase1ValidationError("batch_size must be positive")
    try:
        import torch  # type: ignore[import-not-found]
        from sentence_transformers import (
            SentenceTransformer,  # type: ignore[import-not-found]
        )
    except ImportError as exc:
        raise Phase1ValidationError(
            "frozen inference requires torch and sentence-transformers in the execution environment"
        ) from exc
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise Phase1ValidationError(
            "the frozen bake-off execution contract requires a CUDA device with bfloat16"
        )
    model = SentenceTransformer(
        str(snapshot),
        device=device,
        trust_remote_code=False,
        local_files_only=True,
        model_kwargs={"dtype": torch.bfloat16, "attn_implementation": "sdpa"},
    )
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    if int(model.get_embedding_dimension()) != spec["dimension"]:
        raise Phase1IntegrityError("loaded encoder dimension differs from frozen spec")
    prior_context = model.max_seq_length
    model.max_seq_length = spec["default_context_tokens"]
    try:
        with torch.inference_mode():
            values = model.encode(
                list(texts),
                batch_size=batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=False,
            )
    finally:
        model.max_seq_length = prior_context
    if values.shape != (len(texts), spec["dimension"]):
        raise Phase1IntegrityError(f"unexpected encoder output shape: {values.shape}")
    return values
