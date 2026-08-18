"""Bounded, no-follow, deterministic I/O for Phase 2 artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_bytes

from .errors import Phase2IntegrityError, Phase2ValidationError

MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_JSONL_RECORDS = 10_000
MAX_JSONL_LINE_BYTES = 2 * 1024 * 1024


def read_regular_bytes(path: Path, *, maximum: int = MAX_INPUT_BYTES) -> bytes:
    """Read stable regular-file bytes without following a final symlink."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise Phase2IntegrityError(f"cannot open input safely {path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise Phase2IntegrityError(f"input is not a regular file: {path}")
        if before.st_size > maximum:
            raise Phase2IntegrityError(
                f"input exceeds {maximum} byte safety bound: {path}"
            )
        chunks: list[bytes] = []
        observed = 0
        with os.fdopen(descriptor, "rb", buffering=0, closefd=False) as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                chunks.append(chunk)
                observed += len(chunk)
                if observed > maximum:
                    raise Phase2IntegrityError(
                        f"input exceeds {maximum} byte safety bound: {path}"
                    )
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or observed != before.st_size:
        raise Phase2IntegrityError(f"input changed while reading: {path}")
    return b"".join(chunks)


def bytes_identity(data: bytes) -> dict[str, Any]:
    return {
        "bytes": len(data),
        "sha256": f"sha256:{hashlib.sha256(data).hexdigest()}",
    }


def file_identity(path: Path) -> dict[str, Any]:
    return bytes_identity(read_regular_bytes(path))


def load_json_object(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data = read_regular_bytes(path)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase2ValidationError(
            f"cannot read JSON object from {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise Phase2ValidationError(f"expected a JSON object: {path}")
    return value, bytes_identity(data)


def load_jsonl_objects(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = read_regular_bytes(path)
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(data.splitlines(), start=1):
        if not line.strip():
            continue
        if len(line) > MAX_JSONL_LINE_BYTES:
            raise Phase2ValidationError(
                f"JSONL line exceeds {MAX_JSONL_LINE_BYTES} bytes at {path}:{line_number}"
            )
        if len(records) >= MAX_JSONL_RECORDS:
            raise Phase2ValidationError(
                f"JSONL exceeds {MAX_JSONL_RECORDS} record safety bound: {path}"
            )
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Phase2ValidationError(
                f"invalid JSONL at {path}:{line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise Phase2ValidationError(
                f"JSONL record is not an object at {path}:{line_number}"
            )
        records.append(value)
    return records, bytes_identity(data)


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_bytes(value) + b"\n"


def canonical_jsonl_bytes(records: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(canonical_bytes(record) + b"\n" for record in records)


def require_canonical_json(path: Path, value: Any) -> None:
    observed = read_regular_bytes(path)
    expected = canonical_json_bytes(value)
    if observed != expected:
        raise Phase2IntegrityError(
            f"artifact is not canonical JSON plus newline: {path}"
        )


def require_canonical_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    observed = read_regular_bytes(path)
    expected = canonical_jsonl_bytes(records)
    if observed != expected:
        raise Phase2IntegrityError(f"artifact is not canonical JSONL: {path}")


def _prepare_output(path: Path) -> Path:
    if not path.name or path.name in {".", ".."}:
        raise Phase2IntegrityError(f"unsafe output path: {path}")
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Phase2IntegrityError(
            f"cannot create output directory {parent}: {exc}"
        ) from exc
    absolute_parent = parent.absolute()
    if any(
        candidate.is_symlink()
        for candidate in (absolute_parent, *absolute_parent.parents)
    ):
        raise Phase2IntegrityError(f"output path traverses a symbolic link: {parent}")
    if not parent.is_dir():
        raise Phase2IntegrityError(f"output parent is not a direct directory: {parent}")
    if path.exists() or path.is_symlink():
        raise Phase2IntegrityError(f"refusing to overwrite output: {path}")
    return path


def write_artifact_set_exclusive(outputs: Mapping[Path, bytes]) -> None:
    """Stage a set of files and publish each without overwriting any target."""

    if not outputs:
        raise Phase2IntegrityError("artifact set is empty")
    targets = [_prepare_output(Path(path)) for path in outputs]
    aliases = [str(path.parent.resolve() / path.name) for path in targets]
    if len(aliases) != len(set(aliases)):
        raise Phase2IntegrityError("artifact output paths alias one another")

    staged: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for target in targets:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", dir=target.parent
            )
            temporary = Path(temporary_name)
            staged.append((target, temporary))
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(outputs[target])
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o644)
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
        for target, temporary in staged:
            try:
                os.link(temporary, target, follow_symlinks=False)
            except OSError as exc:
                raise Phase2IntegrityError(
                    f"cannot publish output without overwrite {target}: {exc}"
                ) from exc
            published.append(target)
        for parent in sorted({target.parent for target in targets}, key=str):
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            descriptor = os.open(parent, flags)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except BaseException:
        for target in published:
            try:
                target.unlink()
            except OSError:
                pass
        raise
    finally:
        for _target, temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
