"""GPG sealing and locally hash-chained access logs with optional external anchors."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, canonical_sha256, sha256_bytes
from .errors import SealError, ValidationError
from .validation import validate_instance

ALLOWED_ACCESS_DETAIL_KEYS = frozenset(
    {"receipt_id", "report_id", "request_id", "ticket_id"}
)
ACCESS_DETAIL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _path_without_symlinks(path: Path, description: str) -> Path:
    """Return an absolute path after rejecting every existing symlink component."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SealError(
                f"cannot inspect {description} path {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise SealError(f"{description} path contains a symlink: {current}")
    return absolute


def _validate_access_details(details: dict[str, Any]) -> None:
    for key, value in details.items():
        if key not in ALLOWED_ACCESS_DETAIL_KEYS:
            raise SealError(f"sensitive access-log field forbidden: details/{key}")
        if not isinstance(value, str) or not ACCESS_DETAIL_ID.fullmatch(value):
            raise SealError(
                f"access-log detail must be a bounded identifier: details/{key}"
            )


def _validate_access_event(event: dict[str, Any]) -> None:
    try:
        validate_instance(event, "access-event.schema.json")
    except ValidationError as exc:
        raise SealError(f"invalid access event: {exc}") from exc
    _validate_access_details(event["details"])


def resolve_public_key_fingerprint(recipient: str) -> str:
    command = [
        "gpg",
        "--no-options",
        "--batch",
        "--with-colons",
        "--fingerprint",
        "--list-keys",
        recipient,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise SealError(
            f"cannot resolve GPG recipient {recipient!r}: {result.stderr.strip()}"
        )
    keys: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    expecting_primary_fingerprint = False
    for line in result.stdout.splitlines():
        fields = line.split(":")
        record_type = fields[0]
        if record_type == "pub":
            current = {
                "fingerprint": None,
                "can_encrypt": len(fields) > 11 and "e" in fields[11].casefold(),
            }
            keys.append(current)
            expecting_primary_fingerprint = True
        elif record_type == "sub" and current is not None:
            current["can_encrypt"] = current["can_encrypt"] or (
                len(fields) > 11 and "e" in fields[11].casefold()
            )
            expecting_primary_fingerprint = False
        elif (
            record_type == "fpr"
            and len(fields) > 9
            and expecting_primary_fingerprint
            and current is not None
        ):
            current["fingerprint"] = fields[9].upper()
            expecting_primary_fingerprint = False
    keys = [item for item in keys if item["fingerprint"]]
    if not keys:
        raise SealError(f"GPG recipient has no fingerprint: {recipient!r}")
    if len(keys) != 1:
        raise SealError(f"GPG recipient is ambiguous across {len(keys)} primary keys")
    if not keys[0]["can_encrypt"]:
        raise SealError(f"GPG recipient has no encryption-capable key: {recipient!r}")
    return str(keys[0]["fingerprint"])


def encrypt_canonical_bundle(
    bundle: Any, output_path: Path, recipient: str
) -> tuple[str, str]:
    """Encrypt canonical bytes through stdin; no plaintext file is created."""

    output_path = _path_without_symlinks(output_path, "seal output")
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_path = _path_without_symlinks(output_path, "seal output")
    if output_path.exists() or output_path.is_symlink():
        raise SealError(f"refusing to overwrite seal output: {output_path}")
    fingerprint = resolve_public_key_fingerprint(recipient)
    plaintext = canonical_bytes(bundle)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".partial", dir=output_path.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, 0o600)
        command = [
            "gpg",
            "--no-options",
            "--batch",
            "--yes",
            "--trust-model",
            "always",
            "--recipient",
            fingerprint,
            "--output",
            str(temporary_path),
            "--encrypt",
        ]
        result = subprocess.run(
            command, input=plaintext, check=False, capture_output=True
        )
        if result.returncode != 0:
            raise SealError(
                f"GPG encryption failed: {result.stderr.decode('utf-8', errors='replace').strip()}"
            )
        with temporary_path.open("rb") as handle:
            ciphertext = handle.read()
        if not ciphertext:
            raise SealError("GPG produced empty ciphertext")
        os.replace(temporary_path, output_path)
        return fingerprint, sha256_bytes(ciphertext)
    finally:
        plaintext = b""
        if temporary_path.exists():
            temporary_path.unlink()


def make_seal_receipt(
    *,
    seal_id: str,
    evaluation_class: str,
    ciphertext_sha256: str,
    artifact_hashes: Iterable[str],
    public_key_fingerprint: str,
    custodian: str,
    record_count: int,
) -> dict[str, Any]:
    if record_count < 1:
        raise SealError("a seal cannot represent an empty evaluation set")
    return {
        "schema_version": "1.0.0",
        "seal_id": seal_id,
        "evaluation_class": evaluation_class,
        "ciphertext_sha256": ciphertext_sha256,
        "artifact_hashes": sorted(set(artifact_hashes)),
        "public_key_fingerprint": public_key_fingerprint.upper(),
        "created_at": utc_now(),
        "custodian": custodian,
        "record_count": record_count,
        "state": "sealed",
    }


def verify_ciphertext(path: Path, receipt: dict[str, Any]) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SealError(f"ciphertext is missing or unsafe: {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SealError(f"ciphertext is not a regular file: {path}")
        digest_state = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest_state.update(chunk)
        digest = f"sha256:{digest_state.hexdigest()}"
    finally:
        os.close(descriptor)
    if digest != receipt["ciphertext_sha256"]:
        raise SealError(
            f"ciphertext digest mismatch: expected {receipt['ciphertext_sha256']}, got {digest}"
        )


def make_access_event(
    *,
    seal_id: str,
    action: str,
    actor: str,
    previous_hash: str | None,
    details: dict[str, Any] | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    detail_values = details or {}
    _validate_access_details(detail_values)
    event = {
        "schema_version": "1.0.0",
        "seal_id": seal_id,
        "action": action,
        "actor": actor,
        "at": at or utc_now(),
        "previous_hash": previous_hash,
        "details": detail_values,
    }
    event["event_hash"] = canonical_sha256(event)
    _validate_access_event(event)
    return event


def verify_access_chain(
    events: Iterable[dict[str, Any]],
    *,
    expected_head: str | None = None,
    expected_count: int | None = None,
) -> None:
    if expected_head is not None and not SHA256.fullmatch(expected_head):
        raise SealError("expected access-log head is not a SHA-256 digest")
    if expected_count is not None and expected_count < 0:
        raise SealError("expected access-log count cannot be negative")
    previous: str | None = None
    count = 0
    for position, event in enumerate(events):
        _validate_access_event(event)
        recorded = event.get("event_hash")
        payload = {key: value for key, value in event.items() if key != "event_hash"}
        calculated = canonical_sha256(payload)
        if recorded != calculated:
            raise SealError(f"access event {position} hash mismatch")
        if payload.get("previous_hash") != previous:
            raise SealError(f"access event {position} chain mismatch")
        previous = recorded
        count += 1
    if expected_count is not None and count != expected_count:
        raise SealError(
            f"access-log count mismatch: expected {expected_count}, observed {count}"
        )
    if expected_head is not None and previous != expected_head:
        raise SealError(
            f"access-log head mismatch: expected {expected_head}, observed {previous}"
        )


def consumes_evaluation(action: str) -> bool:
    return action in {
        "decrypt",
        "inspect_labels",
        "report_confirmatory_result",
        "tune_from_result",
        "consume",
        "retire",
    }


def append_access_event(
    *,
    log_path: Path,
    seal_id: str,
    action: str,
    actor: str,
    details: dict[str, Any] | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Lock, verify, and append one canonical event to a private JSONL log."""

    # Reject invalid caller data before creating a log or directory.
    make_access_event(
        seal_id=seal_id,
        action=action,
        actor=actor,
        previous_hash=None,
        details=details,
        at=at,
    )
    log_path = _path_without_symlinks(log_path, "access log")
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_path = _path_without_symlinks(log_path, "access log")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(log_path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SealError(f"access log is not a regular file: {log_path}")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise SealError(f"access log permissions are not private: {log_path}")
        with os.fdopen(descriptor, "r+", encoding="utf-8", closefd=False) as handle:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            handle.seek(0)
            events: list[dict[str, Any]] = []
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SealError(
                        f"invalid access-log JSON at line {line_number}: {exc.msg}"
                    ) from exc
                if not isinstance(value, dict):
                    raise SealError(f"access-log line {line_number} is not an object")
                events.append(value)
            verify_access_chain(events)
            if any(event.get("seal_id") != seal_id for event in events):
                raise SealError("access log contains a different seal_id")
            previous = events[-1]["event_hash"] if events else None
            event = make_access_event(
                seal_id=seal_id,
                action=action,
                actor=actor,
                previous_hash=previous,
                details=details,
                at=at,
            )
            handle.seek(0, os.SEEK_END)
            handle.write(canonical_bytes(event).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(descriptor)
            return event
    finally:
        os.close(descriptor)


def read_access_events(
    log_path: Path,
    *,
    expected_head: str | None = None,
    expected_count: int | None = None,
) -> list[dict[str, Any]]:
    log_path = _path_without_symlinks(log_path, "access log")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(log_path, flags)
    except OSError as exc:
        raise SealError(f"access log is missing or unsafe: {log_path}: {exc}") from exc
    events: list[dict[str, Any]] = []
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SealError(f"access log is not a regular file: {log_path}")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise SealError(f"access log permissions are not private: {log_path}")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise SealError(f"access-log line {line_number} is not an object")
                events.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise SealError(f"cannot read access log {log_path}: {exc}") from exc
    finally:
        os.close(descriptor)
    verify_access_chain(
        events, expected_head=expected_head, expected_count=expected_count
    )
    return events
