"""Deterministic, split-knowledge-preserving READ-run persistence."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from hippocampus_foundation.phase0.canonical import (
    canonical_bytes,
    dump_pretty,
    load_json,
)

from .errors import GenerationError, IntegrityGateError
from .generator import GeneratedEpisode, generate_split
from .seed import seed_commitment

MAX_JSON_LINE_BYTES = 16 * 1024 * 1024
DATASET_ARTIFACT_NAMES = (
    "visible.jsonl.gz",
    "hidden.jsonl.gz",
    "manifest.public.json",
    "manifest.private.json",
)


def model_input_bytes(episode: GeneratedEpisode) -> bytes:
    """Return the only bytes that either model is permitted to receive."""

    forbidden = {
        "episode_id",
        "paired_world_id",
        "split",
        "requested_gamma",
        "branch_depth",
        "target_nodes",
        "valid_routes",
        "teacher_actions",
        "abstain",
        "gold_assertion_mask",
        "greedy_wrong_count",
        "path_step_count",
        "measured_gamma",
    }
    overlap = forbidden & set(episode.visible)
    if overlap:
        raise IntegrityGateError(
            f"hidden fields entered model-visible payload: {sorted(overlap)}"
        )
    expected = {
        "schema_version",
        "record_kind",
        "router_seed",
        "budget_candidates",
        "node_count",
        "relation_count",
        "start_node",
        "query_relations",
        "nodes",
        "edges",
    }
    if set(episode.visible) != expected:
        raise IntegrityGateError(
            "model-visible payload fields differ from the frozen allowlist"
        )
    return canonical_bytes(episode.visible)


def _write_all(handle: BinaryIO, value: bytes) -> None:
    handle.write(value)
    handle.write(b"\n")


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise GenerationError("dataset output is not a regular file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise GenerationError("dataset output changed while being hashed")
    return total, f"sha256:{digest.hexdigest()}"


def dataset_artifact_sha256s(root: Path) -> dict[str, str]:
    """Rehash every generated split artifact without following symlinks."""

    try:
        return {name: _sha256_file(root / name)[1] for name in DATASET_ARTIFACT_NAMES}
    except OSError as exc:
        raise IntegrityGateError("cannot rehash generated split artifacts") from exc


def validate_generated_split_artifacts(
    root: Path, *, expected_seed_commitment: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """Validate manifests against each other and the exact compressed bytes."""

    public = load_json(root / "manifest.public.json")
    private = load_json(root / "manifest.private.json")
    if not isinstance(public, dict) or not isinstance(private, dict):
        raise IntegrityGateError("generated split manifests must be objects")
    common_fields = {
        "schema_version",
        "record_kind",
        "split",
        "requested_gamma",
        "episode_count",
        "abstain_count",
        "measured_gamma",
        "visible_bytes",
        "visible_sha256",
        "seed_commitment",
        "training_authorized",
    }
    if set(public) != common_fields | {"disclosure"}:
        raise IntegrityGateError("public split manifest fields differ")
    if set(private) != common_fields | {
        "disclosure",
        "hidden_bytes",
        "hidden_sha256",
    }:
        raise IntegrityGateError("private split manifest fields differ")
    if any(public[field] != private[field] for field in common_fields):
        raise IntegrityGateError("public and private split manifests disagree")
    if (
        public["schema_version"] != "1.0.0"
        or public["record_kind"] != "read_split_manifest"
        or public["disclosure"] != "model_visible_only"
        or private["disclosure"] != "private_labels_and_oracle"
        or public["training_authorized"] is not False
    ):
        raise IntegrityGateError("generated split manifest contract differs")
    if (
        expected_seed_commitment is not None
        and public["seed_commitment"] != expected_seed_commitment
    ):
        raise IntegrityGateError("generated split uses another seed commitment")

    try:
        visible_bytes, visible_sha256 = _sha256_file(root / "visible.jsonl.gz")
        hidden_bytes, hidden_sha256 = _sha256_file(root / "hidden.jsonl.gz")
    except OSError as exc:
        raise IntegrityGateError("cannot rehash generated split streams") from exc
    if (
        visible_bytes != public["visible_bytes"]
        or visible_sha256 != public["visible_sha256"]
        or hidden_bytes != private["hidden_bytes"]
        or hidden_sha256 != private["hidden_sha256"]
    ):
        raise IntegrityGateError("generated split bytes differ from their manifests")
    return public, private, dataset_artifact_sha256s(root)


def _open_deterministic_gzip(
    path: Path, *, mode: int
) -> tuple[BinaryIO, gzip.GzipFile]:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    raw = os.fdopen(descriptor, "wb")
    compressed = gzip.GzipFile(
        filename="", mode="wb", compresslevel=6, fileobj=raw, mtime=0
    )
    return raw, compressed


def _write_json_exclusive(path: Path, value: dict[str, Any], *, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        encoded = dump_pretty(value).encode("utf-8")
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise GenerationError("short write while persisting dataset manifest")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_generated_split(
    *,
    master_seed: bytes,
    split: str,
    count: int,
    gamma: float,
    destination: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically write separate visible and hidden deterministic streams."""

    if destination.exists() or destination.is_symlink():
        raise GenerationError("refusing to overwrite a dataset destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    os.chmod(temporary, 0o700)
    visible_path = temporary / "visible.jsonl.gz"
    hidden_path = temporary / "hidden.jsonl.gz"
    visible_raw: BinaryIO | None = None
    hidden_raw: BinaryIO | None = None
    visible_gzip: gzip.GzipFile | None = None
    hidden_gzip: gzip.GzipFile | None = None
    try:
        visible_raw, visible_gzip = _open_deterministic_gzip(visible_path, mode=0o644)
        hidden_raw, hidden_gzip = _open_deterministic_gzip(hidden_path, mode=0o600)
        generated = 0
        abstain_count = 0
        gamma_wrong = 0
        gamma_steps = 0
        for episode in generate_split(
            master_seed, split=split, count=count, gamma=gamma
        ):
            visible_record = {
                "episode_id": episode.episode_id,
                "visible": episode.visible,
            }
            hidden_record = {
                "episode_id": episode.episode_id,
                "hidden": episode.hidden,
            }
            _write_all(visible_gzip, canonical_bytes(visible_record))
            _write_all(hidden_gzip, canonical_bytes(hidden_record))
            generated += 1
            abstain_count += bool(episode.hidden["abstain"])
            gamma_wrong += episode.hidden["greedy_wrong_count"]
            gamma_steps += episode.hidden["path_step_count"]
        visible_gzip.close()
        visible_gzip = None
        hidden_gzip.close()
        hidden_gzip = None
        visible_raw.flush()
        os.fsync(visible_raw.fileno())
        visible_raw.close()
        visible_raw = None
        hidden_raw.flush()
        os.fsync(hidden_raw.fileno())
        hidden_raw.close()
        hidden_raw = None
        visible_bytes, visible_sha256 = _sha256_file(visible_path)
        hidden_bytes, hidden_sha256 = _sha256_file(hidden_path)
        measured_gamma = gamma_wrong / gamma_steps
        common = {
            "schema_version": "1.0.0",
            "record_kind": "read_split_manifest",
            "split": split,
            "requested_gamma": gamma,
            "episode_count": generated,
            "abstain_count": abstain_count,
            "measured_gamma": measured_gamma,
            "visible_bytes": visible_bytes,
            "visible_sha256": visible_sha256,
            "seed_commitment": seed_commitment(master_seed),
            "training_authorized": False,
        }
        public_manifest = {**common, "disclosure": "model_visible_only"}
        private_manifest = {
            **common,
            "disclosure": "private_labels_and_oracle",
            "hidden_bytes": hidden_bytes,
            "hidden_sha256": hidden_sha256,
        }
        _write_json_exclusive(
            temporary / "manifest.public.json", public_manifest, mode=0o644
        )
        _write_json_exclusive(
            temporary / "manifest.private.json", private_manifest, mode=0o600
        )
        directory = os.open(temporary, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        os.replace(temporary, destination)
        parent = os.open(
            destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return public_manifest, private_manifest
    except Exception:
        if visible_gzip is not None:
            visible_gzip.close()
        if hidden_gzip is not None:
            hidden_gzip.close()
        if visible_raw is not None:
            visible_raw.close()
        if hidden_raw is not None:
            hidden_raw.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _read_gzip_records(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with gzip.open(path, "rb") as handle:
            for raw in handle:
                if len(raw) > MAX_JSON_LINE_BYTES:
                    raise IntegrityGateError(
                        "dataset JSON line exceeds the fixed bound"
                    )
                try:
                    value = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise IntegrityGateError(
                        "dataset stream contains invalid JSON"
                    ) from exc
                if not isinstance(value, dict):
                    raise IntegrityGateError("dataset record must be an object")
                yield value
    except OSError as exc:
        raise IntegrityGateError("cannot read deterministic dataset stream") from exc


def read_generated_split(root: Path) -> Iterator[GeneratedEpisode]:
    visible = _read_gzip_records(root / "visible.jsonl.gz")
    hidden = _read_gzip_records(root / "hidden.jsonl.gz")
    count = 0
    while True:
        try:
            public_record = next(visible)
        except StopIteration:
            public_record = None
        try:
            private_record = next(hidden)
        except StopIteration:
            private_record = None
        if public_record is None or private_record is None:
            if public_record is not None or private_record is not None:
                raise IntegrityGateError("visible and hidden stream lengths differ")
            break
        if set(public_record) != {"episode_id", "visible"} or set(private_record) != {
            "episode_id",
            "hidden",
        }:
            raise IntegrityGateError("dataset stream record fields differ")
        if public_record["episode_id"] != private_record["episode_id"]:
            raise IntegrityGateError("visible and hidden stream identities differ")
        episode = GeneratedEpisode(
            episode_id=public_record["episode_id"],
            paired_world_id=private_record["hidden"]["paired_world_id"],
            visible=public_record["visible"],
            hidden=private_record["hidden"],
        )
        model_input_bytes(episode)
        count += 1
        yield episode
    if count == 0:
        raise IntegrityGateError("dataset stream is empty")
