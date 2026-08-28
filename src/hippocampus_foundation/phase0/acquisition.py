"""Resumable immutable raw acquisition; this module never transforms data."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from .canonical import canonical_bytes
from .errors import IntegrityError

DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
IdentityCheck = Callable[[str, int], dict[str, Any]]
MAX_RESUME_BINDING_BYTES = 4096


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
            raise IntegrityError(
                f"cannot inspect destination path {current}: {exc}"
            ) from exc
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
    if (
        0 < offset < expected_bytes
        and str(metadata.get("accept_ranges", "")).casefold() != "bytes"
    ):
        raise IntegrityError(
            "remote source does not advertise byte-range resume support"
        )

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
                    expected_range = (
                        f"bytes {offset}-{expected_bytes - 1}/{expected_bytes}"
                    )
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


def _validate_download_inputs(
    *,
    expected_bytes: int,
    expected_checksums: dict[str, str],
    minimum_free_bytes: int,
) -> dict[str, str]:
    if expected_bytes <= 0:
        raise IntegrityError("expected byte count must be positive")
    if minimum_free_bytes < 0:
        raise IntegrityError("minimum free-byte reserve cannot be negative")
    if not expected_checksums:
        raise IntegrityError("at least one publisher checksum is required")
    normalized: dict[str, str] = {}
    lengths = {"md5": 32, "sha1": 40, "sha256": 64}
    for algorithm, expected in expected_checksums.items():
        if algorithm not in lengths:
            raise IntegrityError(f"unsupported checksum algorithm: {algorithm}")
        value = expected.lower()
        if len(value) != lengths[algorithm] or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise IntegrityError(f"invalid {algorithm} checksum")
        normalized[algorithm] = value
    if not ({"sha1", "sha256"} & normalized.keys()):
        raise IntegrityError("a SHA-1 or SHA-256 publisher checksum is required")
    return normalized


def _stat_at(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise IntegrityError(
            f"cannot inspect rooted destination {name}: {exc}"
        ) from exc


def _hash_at(directory_fd: int, name: str, algorithm: str) -> str:
    digest = hashlib.new(algorithm, usedforsecurity=(algorithm == "sha256"))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise IntegrityError(
            f"cannot open rooted checksum target {name}: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise IntegrityError(f"rooted checksum target is not regular: {name}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while chunk := handle.read(DOWNLOAD_CHUNK_BYTES):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _read_regular_at(
    directory_fd: int, name: str, *, maximum_bytes: int, label: str
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise IntegrityError(f"cannot open {label}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise IntegrityError(f"{label} is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise IntegrityError(f"cannot read {label}: {exc}") from exc
    finally:
        os.close(descriptor)
    if len(raw) > maximum_bytes or len(raw) != before.st_size:
        raise IntegrityError(f"{label} size changed or exceeded its limit")
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
    ):
        raise IntegrityError(f"{label} changed while it was read")
    return raw


def _resume_binding_bytes(
    *,
    authorization_sha256: str,
    url: str,
    filename: str,
    expected_bytes: int,
    expected_checksums: dict[str, str],
) -> bytes:
    if (
        not authorization_sha256.startswith("sha256:")
        or len(authorization_sha256) != 71
        or any(
            character not in "0123456789abcdef"
            for character in authorization_sha256.removeprefix("sha256:")
        )
    ):
        raise IntegrityError("resume authorization digest is invalid")
    return canonical_bytes(
        {
            "schema_version": "1.0.0",
            "record_kind": "source_acquisition_resume_binding",
            "authorization_sha256": authorization_sha256,
            "source_url_sha256": "sha256:"
            + hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "destination_filename": filename,
            "expected_bytes": expected_bytes,
            "expected_checksums": expected_checksums,
            "training_authorized": False,
        }
    )


def _create_resume_binding_at(directory_fd: int, name: str, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except OSError as exc:
        raise IntegrityError(
            f"cannot create acquisition resume binding: {exc}"
        ) from exc
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise IntegrityError(
                    "acquisition resume binding write made no progress"
                )
            view = view[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise IntegrityError(f"cannot write acquisition resume binding: {exc}") from exc
    finally:
        os.close(descriptor)
    os.fsync(directory_fd)


def _open_relative_parent(root_fd: int, components: tuple[str, ...]) -> int:
    """Open/create a relative directory chain without following symlinks."""

    current = os.dup(root_fd)
    try:
        for component in components:
            try:
                os.mkdir(component, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            except OSError as exc:
                raise IntegrityError(
                    f"cannot create rooted acquisition directory {component}: {exc}"
                ) from exc
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                child = os.open(component, flags, dir_fd=current)
            except OSError as exc:
                raise IntegrityError(
                    f"rooted acquisition directory is unsafe: {component}"
                ) from exc
            if not stat.S_ISDIR(os.fstat(child).st_mode):
                os.close(child)
                raise IntegrityError(
                    f"rooted acquisition component is not a directory: {component}"
                )
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def download_resumable_at(
    *,
    url: str,
    root: Path,
    filename: str,
    expected_bytes: int,
    expected_checksums: dict[str, str],
    minimum_free_bytes: int,
    resume_authorization_sha256: str,
    identity_check: IdentityCheck,
) -> dict[str, Any]:
    """Download relative to one pinned root descriptor and recheck before promote."""

    relative = PurePosixPath(filename)
    if (
        not filename
        or not relative.parts
        or relative.is_absolute()
        or relative.as_posix() != filename
        or "\\" in filename
        or any(component in {"", ".", ".."} for component in relative.parts)
    ):
        raise IntegrityError("destination must be a safe relative registry path")
    normalized = _validate_download_inputs(
        expected_bytes=expected_bytes,
        expected_checksums=expected_checksums,
        minimum_free_bytes=minimum_free_bytes,
    )
    resume_binding = _resume_binding_bytes(
        authorization_sha256=resume_authorization_sha256,
        url=url,
        filename=filename,
        expected_bytes=expected_bytes,
        expected_checksums=normalized,
    )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, flags)
    except OSError as exc:
        raise IntegrityError(f"cannot pin acquisition root {root}: {exc}") from exc
    leaf = relative.name
    partial = leaf + ".partial"
    resume_metadata = partial + ".authorization.json"
    parent_fd: int | None = None
    try:
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            raise IntegrityError("acquisition root descriptor is not a directory")
        pre_identity = identity_check("before_download", root_fd)
        if not isinstance(pre_identity, dict):
            raise IntegrityError("acquisition identity check did not return evidence")

        parent_fd = _open_relative_parent(root_fd, relative.parts[:-1])

        if _stat_at(parent_fd, leaf) is not None:
            raise IntegrityError(
                f"refusing to overwrite immutable artifact: {filename}"
            )
        partial_metadata = _stat_at(parent_fd, partial)
        if partial_metadata is not None and not stat.S_ISREG(partial_metadata.st_mode):
            raise IntegrityError("partial acquisition target is not a regular file")
        binding_metadata = _stat_at(parent_fd, resume_metadata)
        if binding_metadata is not None and not stat.S_ISREG(binding_metadata.st_mode):
            raise IntegrityError("acquisition resume binding is not a regular file")
        if partial_metadata is not None and binding_metadata is None:
            raise IntegrityError("partial artifact has no signed-authorization binding")
        if binding_metadata is None:
            _create_resume_binding_at(parent_fd, resume_metadata, resume_binding)
        elif (
            _read_regular_at(
                parent_fd,
                resume_metadata,
                maximum_bytes=MAX_RESUME_BINDING_BYTES,
                label="acquisition resume binding",
            )
            != resume_binding
        ):
            raise IntegrityError("partial artifact belongs to another authorization")
        partial_exists = partial_metadata is not None
        offset = partial_metadata.st_size if partial_metadata is not None else 0
        if offset > expected_bytes:
            raise IntegrityError("partial artifact exceeds expected size")
        try:
            file_system = os.fstatvfs(root_fd)
        except OSError as exc:
            raise IntegrityError("cannot inspect rooted free space") from exc
        free = file_system.f_bavail * file_system.f_frsize
        required = (expected_bytes - offset) + minimum_free_bytes
        if free < required:
            raise IntegrityError(
                f"insufficient free space: require {required}, observed {free}"
            )

        metadata = remote_metadata(url)
        if metadata["status"] != 200:
            raise IntegrityError(f"unexpected remote status: {metadata['status']}")
        if metadata["content_length"] != expected_bytes:
            raise IntegrityError(
                "remote size mismatch: "
                f"expected {expected_bytes}, observed {metadata['content_length']}"
            )
        if metadata["final_url"] != url:
            raise IntegrityError(
                f"source redirected: expected {url}, observed {metadata['final_url']}"
            )
        if (
            0 < offset < expected_bytes
            and str(metadata.get("accept_ranges", "")).casefold() != "bytes"
        ):
            raise IntegrityError(
                "remote source does not advertise byte-range resume support"
            )

        if offset < expected_bytes:
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    expected_status = 206 if offset else 200
                    if response.status != expected_status:
                        raise IntegrityError(
                            "resume status mismatch: "
                            f"expected {expected_status}, observed {response.status}"
                        )
                    if response.url != url:
                        raise IntegrityError(
                            f"download redirected: expected {url}, observed {response.url}"
                        )
                    if offset:
                        expected_range = (
                            f"bytes {offset}-{expected_bytes - 1}/{expected_bytes}"
                        )
                        if response.headers.get("Content-Range") != expected_range:
                            raise IntegrityError(
                                "resume Content-Range mismatch: "
                                f"expected {expected_range}, observed "
                                f"{response.headers.get('Content-Range')}"
                            )
                    response_length = response.headers.get("Content-Length")
                    remaining = expected_bytes - offset
                    if (
                        response_length is not None
                        and int(response_length) != remaining
                    ):
                        raise IntegrityError(
                            "download response size mismatch: "
                            f"expected {remaining}, observed {response_length}"
                        )
                    open_flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
                    if partial_exists:
                        open_flags |= os.O_APPEND
                    else:
                        open_flags |= os.O_CREAT | os.O_EXCL
                    descriptor = os.open(partial, open_flags, 0o600, dir_fd=parent_fd)
                    with os.fdopen(
                        descriptor, "ab" if partial_exists else "wb"
                    ) as handle:
                        while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                            handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
            except (OSError, urllib.error.URLError) as exc:
                raise IntegrityError(f"download interrupted: {exc}") from exc

        completed_metadata = _stat_at(parent_fd, partial)
        if completed_metadata is None or completed_metadata.st_size != expected_bytes:
            measured = (
                None if completed_metadata is None else completed_metadata.st_size
            )
            raise IntegrityError(
                f"download incomplete: expected {expected_bytes}, observed {measured}"
            )
        measured_checksums: dict[str, str] = {}
        for algorithm, expected in normalized.items():
            measured_checksums[algorithm] = _hash_at(parent_fd, partial, algorithm)
            if measured_checksums[algorithm] != expected:
                raise IntegrityError(
                    f"{algorithm} mismatch: expected {expected}, "
                    f"observed {measured_checksums[algorithm]}"
                )
        measured_checksums["sha256"] = measured_checksums.get("sha256") or _hash_at(
            parent_fd, partial, "sha256"
        )

        post_identity = identity_check("before_promote", root_fd)
        if not isinstance(post_identity, dict):
            raise IntegrityError(
                "final acquisition identity check did not return evidence"
            )
        os.replace(partial, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.unlink(resume_metadata, dir_fd=parent_fd)
        os.fsync(parent_fd)
        os.fsync(root_fd)
        return {
            "destination": str(root / filename),
            "destination_filename": filename,
            "bytes": expected_bytes,
            "checksums": measured_checksums,
            "remote": metadata,
            "pre_identity": pre_identity,
            "post_identity": post_identity,
        }
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)
