"""Resumable immutable raw acquisition; this module never transforms data."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import IntegrityError

DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024


def _safe_absolute_path(path: Path) -> Path:
    """Normalize lexically and reject every existing symlink component."""

    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise IntegrityError(f"cannot inspect destination path {current}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError(f"destination symlink is forbidden: {current}")
    return absolute


def preflight_space(destination: Path, required_free_bytes: int) -> dict[str, int]:
    usage = shutil.disk_usage(destination.parent)
    if usage.free < required_free_bytes:
        raise IntegrityError(
            f"insufficient free space: require {required_free_bytes}, observed {usage.free}"
        )
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def remote_metadata(url: str) -> dict[str, Any]:
    if urlsplit(url).scheme != "https":
        raise IntegrityError("source URL must use HTTPS")
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            length = response.headers.get("Content-Length")
            return {
                "status": response.status,
                "content_length": int(length) if length is not None else None,
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "accept_ranges": response.headers.get("Accept-Ranges"),
                "final_url": response.url,
            }
    except urllib.error.URLError as exc:
        raise IntegrityError(f"cannot inspect remote artifact {url}: {exc}") from exc


def _hash(path: Path, algorithm: str) -> str:
    if algorithm not in {"md5", "sha1", "sha256"}:
        raise IntegrityError(f"unsupported checksum algorithm: {algorithm}")
    digest = hashlib.new(algorithm, usedforsecurity=(algorithm == "sha256"))
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise IntegrityError(f"cannot open checksum target {path}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise IntegrityError(f"checksum target is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while chunk := handle.read(DOWNLOAD_CHUNK_BYTES):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def download_resumable(
    *,
    url: str,
    destination: Path,
    expected_bytes: int,
    expected_checksums: dict[str, str],
    minimum_free_bytes: int,
) -> dict[str, Any]:
    """Resume into a partial file and promote only after full verification."""

    if expected_bytes <= 0:
        raise IntegrityError("expected byte count must be positive")
    if minimum_free_bytes < 0:
        raise IntegrityError("minimum free-byte reserve cannot be negative")
    if not expected_checksums:
        raise IntegrityError("at least one publisher checksum is required")
    normalized_checksums: dict[str, str] = {}
    checksum_lengths = {"md5": 32, "sha1": 40, "sha256": 64}
    for algorithm, expected in expected_checksums.items():
        if algorithm not in checksum_lengths:
            raise IntegrityError(f"unsupported checksum algorithm: {algorithm}")
        value = expected.lower()
        if len(value) != checksum_lengths[algorithm] or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise IntegrityError(f"invalid {algorithm} checksum")
        normalized_checksums[algorithm] = value
    if not ({"sha1", "sha256"} & normalized_checksums.keys()):
        raise IntegrityError("a SHA-1 or SHA-256 publisher checksum is required")

    destination = _safe_absolute_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _safe_absolute_path(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise IntegrityError(f"refusing to overwrite immutable artifact: {destination}")
    partial = destination.with_name(destination.name + ".partial")
    if partial.is_symlink():
        raise IntegrityError(f"partial path is a symlink: {partial}")
    partial_exists = partial.exists()
    offset = partial.stat().st_size if partial_exists else 0
    if offset > expected_bytes:
        raise IntegrityError("partial artifact exceeds expected size")
    preflight_space(destination, (expected_bytes - offset) + minimum_free_bytes)
    metadata = remote_metadata(url)
    if metadata["status"] != 200:
        raise IntegrityError(f"unexpected remote status: {metadata['status']}")
    if metadata["content_length"] != expected_bytes:
        raise IntegrityError(
            f"remote size mismatch: expected {expected_bytes}, observed {metadata['content_length']}"
        )
    if metadata["final_url"] != url:
        raise IntegrityError(
            f"source redirected: expected {url}, observed {metadata['final_url']}"
        )
    if 0 < offset < expected_bytes and str(
        metadata.get("accept_ranges", "")
    ).casefold() != "bytes":
        raise IntegrityError("remote source does not advertise byte-range resume support")

    if offset < expected_bytes:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                expected_status = 206 if offset else 200
                if response.status != expected_status:
                    raise IntegrityError(
                        f"resume status mismatch: expected {expected_status}, observed {response.status}"
                    )
                if response.url != url:
                    raise IntegrityError(
                        f"download redirected: expected {url}, observed {response.url}"
                    )
                if offset:
                    expected_range = f"bytes {offset}-{expected_bytes - 1}/{expected_bytes}"
                    if response.headers.get("Content-Range") != expected_range:
                        raise IntegrityError(
                            "resume Content-Range mismatch: "
                            f"expected {expected_range}, observed "
                            f"{response.headers.get('Content-Range')}"
                        )
                response_length = response.headers.get("Content-Length")
                expected_response_bytes = expected_bytes - offset
                if (
                    response_length is not None
                    and int(response_length) != expected_response_bytes
                ):
                    raise IntegrityError(
                        "download response size mismatch: "
                        f"expected {expected_response_bytes}, observed {response_length}"
                    )
                # A zero-byte partial is still an existing resume target. Opening it
                # exclusively would fail before the first byte was written.
                flags = os.O_WRONLY
                if partial_exists:
                    flags |= os.O_APPEND
                else:
                    flags |= os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(partial, flags, 0o600)
                with os.fdopen(descriptor, "ab" if partial_exists else "wb") as handle:
                    while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
        except (OSError, urllib.error.URLError) as exc:
            raise IntegrityError(f"download interrupted: {exc}") from exc
    measured_bytes = partial.stat().st_size
    if measured_bytes != expected_bytes:
        raise IntegrityError(
            f"download incomplete: expected {expected_bytes}, observed {measured_bytes}"
        )
    measured: dict[str, str] = {}
    for algorithm, expected in normalized_checksums.items():
        measured[algorithm] = _hash(partial, algorithm)
        if measured[algorithm] != expected:
            raise IntegrityError(
                f"{algorithm} mismatch: expected {expected}, observed {measured[algorithm]}"
            )
    measured["sha256"] = measured.get("sha256") or _hash(partial, "sha256")
    os.replace(partial, destination)
    directory_descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return {
        "destination": str(destination),
        "bytes": measured_bytes,
        "checksums": measured,
        "remote": metadata,
    }
