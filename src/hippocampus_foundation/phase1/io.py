"""Bounded, deterministic record and artifact I/O for Phase 1."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_bytes, dump_pretty

from .errors import Phase1IntegrityError, Phase1ValidationError


def file_identity(path: Path) -> dict[str, Any]:
    """Return byte count and SHA-256 while rejecting a changing or unsafe file."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise Phase1IntegrityError(
            f"cannot open artifact safely {path}: {exc}"
        ) from exc
    digest = hashlib.sha256()
    byte_count = 0
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise Phase1IntegrityError(f"artifact is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", buffering=0, closefd=False) as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
                byte_count += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or byte_count != before.st_size:
        raise Phase1IntegrityError(f"artifact changed while hashing: {path}")
    return {"bytes": byte_count, "sha256": f"sha256:{digest.hexdigest()}"}


def file_identity_following_registered_symlink(path: Path) -> dict[str, Any]:
    """Hash a declared encoder asset, allowing content-addressed cache symlinks."""

    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise Phase1IntegrityError(
            f"cannot resolve registered asset {path}: {exc}"
        ) from exc
    if not resolved.is_file():
        raise Phase1IntegrityError(f"registered asset is not a regular file: {path}")
    return file_identity(resolved)


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    suffix = path.suffix.casefold()
    if suffix in {".jsonl", ".ndjson"}:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise Phase1ValidationError(
                            f"invalid JSONL at {path}:{line_number}: {exc.msg}"
                        ) from exc
                    if not isinstance(value, dict):
                        raise Phase1ValidationError(
                            f"record is not an object at {path}:{line_number}"
                        )
                    yield value
        except OSError as exc:
            raise Phase1IntegrityError(f"cannot read {path}: {exc}") from exc
        return
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq  # type: ignore[import-not-found]
        except ImportError as exc:
            raise Phase1ValidationError(
                "Parquet input requires pyarrow in the execution environment"
            ) from exc
        try:
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(batch_size=8192):
                for value in batch.to_pylist():
                    if not isinstance(value, dict):
                        raise Phase1ValidationError("Parquet record is not an object")
                    yield value
        except OSError as exc:
            raise Phase1IntegrityError(f"cannot read Parquet {path}: {exc}") from exc
        return
    raise Phase1ValidationError("record input must use .jsonl, .ndjson, or .parquet")


def _atomic_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json_atomic(path: Path, value: Any, mode: int = 0o644) -> None:
    _atomic_bytes(path, dump_pretty(value).encode("utf-8"), mode=mode)


def write_jsonl_atomic(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    count = 0
    try:
        with os.fdopen(descriptor, "wb") as handle:
            for record in records:
                handle.write(canonical_bytes(record))
                handle.write(b"\n")
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return count
