"""Mechanically bind exact-scope Drive API identity to the live DriveFS root."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .authority_v4_2 import (
    DRIVE_READONLY_SCOPE,
    DRIVE_ROOT,
    MARKER_FILENAME,
    VerifiedOAuthAuthority,
    validate_oauth_authority_time,
)
from .canonical import canonical_sha256, sha256_bytes
from .errors import IntegrityError, ValidationError
from .v4_2_contracts import validate_v4_2

DRIVE_MOUNT_ROOT = Path("/content/drive")
EXPECTED_ROOT = Path(DRIVE_ROOT)
MAX_ADC_BYTES = 64 * 1024
MAX_MARKER_BYTES = 16 * 1024
MAX_TOKEN_INFO_BYTES = 64 * 1024
TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


@dataclass(frozen=True)
class TokenInfo:
    scopes: frozenset[str]
    authorized_party: str


def _execute_object(request: Any) -> dict[str, Any]:
    value = request.execute(num_retries=3)
    if not isinstance(value, dict):
        raise ValidationError("Drive API response is not an object")
    return value


def _execute_bytes(request: Any) -> bytes:
    value = request.execute(num_retries=3)
    if not isinstance(value, bytes):
        raise ValidationError("Drive API media response is not bytes")
    if len(value) <= 0 or len(value) > MAX_MARKER_BYTES:
        raise ValidationError("Drive identity marker size is invalid")
    return value


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_pairs
        )
    except (UnicodeError, ValueError) as exc:
        raise ValidationError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    return value


def _read_private_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_absolute():
        raise ValidationError(f"{label} path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValidationError(f"{label} is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o077
            or before.st_size <= 0
            or before.st_size > MAX_ADC_BYTES
        ):
            raise ValidationError(f"{label} is not a private regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(MAX_ADC_BYTES + 1)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ValidationError(f"{label} cannot be read") from exc
    finally:
        os.close(descriptor)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if len(raw) > MAX_ADC_BYTES or len(raw) != before.st_size:
        raise ValidationError(f"{label} size changed or exceeded its limit")
    if before_identity != after_identity:
        raise ValidationError(f"{label} changed while it was read")
    return _strict_object(raw, label=label), raw


def make_drive_identity_marker(
    *, marker_id: str, provider_resource_id: str, root_resource_id: str
) -> dict[str, Any]:
    marker = {
        "schema_version": "1.0.0",
        "record_kind": "entor_drive_identity_marker",
        "marker_id": marker_id,
        "provider_resource_id": provider_resource_id,
        "root_resource_id": root_resource_id,
        "contains_evaluation_content": False,
        "training_authorized": False,
    }
    validate_v4_2(marker, "drive-identity-marker.schema.json")
    return marker


def _parse_marker(raw: bytes, authority: VerifiedOAuthAuthority) -> dict[str, Any]:
    marker = _strict_object(raw, label="Drive identity marker")
    validate_v4_2(marker, "drive-identity-marker.schema.json")
    if marker["provider_resource_id"] != authority.receipt["provider_resource_id"]:
        raise ValidationError("Drive marker shared-drive binding mismatch")
    if marker["root_resource_id"] != authority.receipt["root_resource_id"]:
        raise ValidationError("Drive marker root binding mismatch")
    if sha256_bytes(raw) != authority.receipt["marker_sha256"]:
        raise IntegrityError("Drive identity marker digest mismatch")
    return marker


def _decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _mount_identity(mountinfo_text: str) -> str:
    matches: list[dict[str, Any]] = []
    for line in mountinfo_text.splitlines():
        fields = line.split()
        if "-" not in fields or len(fields) < 10:
            continue
        separator = fields.index("-")
        if separator + 3 >= len(fields):
            continue
        mount_point = _decode_mount_field(fields[4])
        if mount_point != str(DRIVE_MOUNT_ROOT):
            continue
        filesystem = fields[separator + 1].casefold()
        source = _decode_mount_field(fields[separator + 2])
        if not any(marker in filesystem for marker in ("fuse", "drive")):
            raise ValidationError("/content/drive is not a DriveFS/FUSE mount")
        matches.append(
            {
                "mount_id": fields[0],
                "parent_id": fields[1],
                "major_minor": fields[2],
                "mount_root": _decode_mount_field(fields[3]),
                "mount_point": mount_point,
                "mount_options": sorted(fields[5].split(",")),
                "filesystem": filesystem,
                "source": source,
            }
        )
    if len(matches) != 1:
        raise ValidationError("/content/drive is not one unique live mount")
    return canonical_sha256(matches[0])


def _read_marker_at(root_fd: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(MARKER_FILENAME, flags, dir_fd=root_fd)
    except OSError as exc:
        raise ValidationError("mounted Drive identity marker is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > MAX_MARKER_BYTES
        ):
            raise ValidationError("mounted Drive identity marker is unsafe")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(MAX_MARKER_BYTES + 1)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ValidationError("mounted Drive identity marker cannot be read") from exc
    finally:
        os.close(descriptor)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if len(raw) > MAX_MARKER_BYTES or len(raw) != before.st_size:
        raise ValidationError("mounted Drive identity marker size changed")
    if before_identity != after_identity:
        raise IntegrityError("mounted Drive identity marker changed while read")
    return raw


def _require_mount_path(root: Path, *, root_fd: int | None = None) -> bytes:
    if root != EXPECTED_ROOT:
        raise ValidationError("Drive root path differs from the frozen lake root")
    current = Path(root.anchor)
    for component in root.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ValidationError(
                f"Drive mount component is unavailable: {current}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError(f"Drive mount component is a symlink: {current}")
    if not root.is_dir() or root.resolve(strict=True) != root:
        raise ValidationError("Drive lake root is not the expected directory")

    owned_fd = root_fd is None
    if owned_fd:
        flags = (
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            root_fd = os.open(root, flags)
        except OSError as exc:
            raise ValidationError("Drive lake root cannot be pinned") from exc
    assert root_fd is not None
    try:
        descriptor_metadata = os.fstat(root_fd)
        path_metadata = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(descriptor_metadata.st_mode):
            raise ValidationError("Drive root descriptor is not a directory")
        if (descriptor_metadata.st_dev, descriptor_metadata.st_ino) != (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ):
            raise IntegrityError("Drive root descriptor no longer names the live path")
        return _read_marker_at(root_fd)
    finally:
        if owned_fd:
            os.close(root_fd)


def _validate_drive_metadata(
    service: Any, authority: VerifiedOAuthAuthority
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]:
    drive_id = authority.receipt["provider_resource_id"]
    root_id = authority.receipt["root_resource_id"]
    marker_id = authority.receipt["marker_file_id"]
    drive = _execute_object(
        service.drives().get(
            driveId=drive_id,
            useDomainAdminAccess=False,
            fields="id,name,hidden,capabilities(canListChildren)",
        )
    )
    if (
        drive.get("id") != drive_id
        or drive.get("name") != "Data"
        or drive.get("hidden") is True
        or drive.get("capabilities", {}).get("canListChildren") is not True
    ):
        raise ValidationError("registered shared Drive metadata is invalid")
    root = _execute_object(
        service.files().get(
            fileId=root_id,
            supportsAllDrives=True,
            fields=(
                "id,name,mimeType,parents,driveId,trashed,version,"
                "capabilities(canListChildren),shortcutDetails"
            ),
        )
    )
    if (
        root.get("id") != root_id
        or root.get("name") != "graph-memory-data-lake"
        or root.get("mimeType") != "application/vnd.google-apps.folder"
        or root.get("parents") != [drive_id]
        or root.get("driveId") != drive_id
        or root.get("trashed") is not False
        or root.get("shortcutDetails") is not None
        or root.get("capabilities", {}).get("canListChildren") is not True
        or not isinstance(root.get("version"), str)
    ):
        raise ValidationError("registered lake root metadata is invalid")
    marker = _execute_object(
        service.files().get(
            fileId=marker_id,
            supportsAllDrives=True,
            fields="id,name,mimeType,parents,driveId,trashed,version,size,md5Checksum",
        )
    )
    if (
        marker.get("id") != marker_id
        or marker.get("name") != MARKER_FILENAME
        or marker.get("mimeType") != "application/json"
        or marker.get("parents") != [root_id]
        or marker.get("driveId") != drive_id
        or marker.get("trashed") is not False
        or not isinstance(marker.get("version"), str)
    ):
        raise ValidationError("registered Drive identity marker metadata is invalid")
    marker_bytes = _execute_bytes(
        service.files().get_media(fileId=marker_id, supportsAllDrives=True)
    )
    expected_md5 = hashlib.md5(marker_bytes, usedforsecurity=False).hexdigest()
    try:
        declared_size = int(marker.get("size", ""))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Drive identity marker size metadata is invalid") from exc
    if declared_size != len(marker_bytes) or marker.get("md5Checksum") != expected_md5:
        raise IntegrityError(
            "Drive identity marker API metadata does not match its bytes"
        )
    return drive, root, marker, marker_bytes


def observe_drive_access_v4_2(
    *,
    service: Any,
    credential_metadata: Mapping[str, Any],
    principal_scopes: set[str],
    token_authorized_party: str,
    authority: VerifiedOAuthAuthority,
    observed_at: str,
    root: Path = EXPECTED_ROOT,
    root_fd: int | None = None,
    mountinfo_text: str | None = None,
) -> dict[str, Any]:
    """Return a proof containing only independently measured v4.2 claims."""

    if principal_scopes != {DRIVE_READONLY_SCOPE}:
        raise ValidationError("Drive credential grant is not exactly drive.readonly")
    if credential_metadata.get("better_colab_scope") != DRIVE_READONLY_SCOPE:
        raise ValidationError("Better Colab ADC does not declare exact Drive scope")
    if (
        credential_metadata.get("better_colab_oauth_config_sha256")
        != authority.receipt["oauth_config_sha256"]
    ):
        raise ValidationError("Better Colab ADC OAuth fingerprint mismatch")
    client_id = credential_metadata.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise ValidationError("Better Colab ADC client ID is unavailable")
    if (
        sha256_bytes(client_id.encode("utf-8"))
        != authority.receipt["oauth_client_id_sha256"]
    ):
        raise ValidationError("Better Colab ADC OAuth client ID mismatch")
    if token_authorized_party != client_id:
        raise ValidationError(
            "Google access-token authorized party differs from the approved client"
        )
    project_number = client_id.split("-", 1)[0]
    if project_number != authority.receipt["cloud_project_number"]:
        raise ValidationError("Better Colab ADC Cloud project mismatch")
    if credential_metadata.get("better_colab_provider_mode") not in {
        "development",
        "production",
    }:
        raise ValidationError("Better Colab ADC provider mode is invalid")

    about = _execute_object(
        service.about().get(fields="user(permissionId,emailAddress)")
    )
    user = about.get("user", {})
    permission_id = user.get("permissionId")
    email = user.get("emailAddress")
    if not isinstance(permission_id, str) or not permission_id:
        raise ValidationError("Drive principal permission ID is unavailable")
    expected_domain = authority.receipt["workspace_domain"]
    if not (
        isinstance(email, str)
        and email.casefold().endswith("@" + expected_domain.casefold())
        and email.rsplit("@", 1)[1].casefold() == expected_domain.casefold()
    ):
        raise ValidationError(
            "Drive principal is outside the approved Workspace domain"
        )
    principal_hash = sha256_bytes(
        b"hf-drive-principal-v1\x00" + permission_id.encode("utf-8")
    )

    drive, folder, marker, api_marker = _validate_drive_metadata(service, authority)
    _parse_marker(api_marker, authority)
    mounted_marker = _require_mount_path(root, root_fd=root_fd)
    _parse_marker(mounted_marker, authority)
    if mounted_marker != api_marker:
        raise IntegrityError("Drive API and mounted identity marker bytes differ")
    if mountinfo_text is None:
        try:
            mountinfo_text = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError("live mount metadata is unavailable") from exc
    mount_identity = _mount_identity(mountinfo_text)

    repeated_drive, repeated_folder, repeated_marker, repeated_bytes = (
        _validate_drive_metadata(service, authority)
    )
    if (drive, folder, marker, api_marker) != (
        repeated_drive,
        repeated_folder,
        repeated_marker,
        repeated_bytes,
    ):
        raise IntegrityError("Drive identity changed during observation")

    proof = {
        "schema_version": "4.2.0",
        "record_kind": "drive_access_proof",
        "observed_at": observed_at,
        "oauth_authority_receipt_sha256": authority.sha256,
        "oauth_config_sha256": authority.receipt["oauth_config_sha256"],
        "oauth_client_id_sha256": authority.receipt["oauth_client_id_sha256"],
        "requested_scope": DRIVE_READONLY_SCOPE,
        "scope_exact": True,
        "workspace_domain_verified": True,
        "same_resource_mechanically_proven": True,
        "principal_permission_id_sha256": principal_hash,
        "provider": "google_drive_shared_drive",
        "provider_resource_id": authority.receipt["provider_resource_id"],
        "root_resource_id": authority.receipt["root_resource_id"],
        "observed_root": DRIVE_ROOT,
        "marker_file_id": authority.receipt["marker_file_id"],
        "marker_sha256": authority.receipt["marker_sha256"],
        "mount_identity_sha256": mount_identity,
        "checks": {
            "exact_scope": True,
            "internal_domain": True,
            "oauth_config_fingerprint": True,
            "oauth_client_id": True,
            "token_authorized_party": True,
            "registered_shared_drive": True,
            "registered_direct_folder": True,
            "folder_not_shortcut": True,
            "api_marker_identity": True,
            "api_mount_marker_equal": True,
            "root_descriptor_bound": True,
            "live_drivefs_mount": True,
            "identity_stable": True,
        },
        "contains_evaluation_content": False,
        "api_drive_write_authorized": False,
        "drive_write_performed": False,
        "training_authorized": False,
    }
    validate_v4_2(proof, "execution-evidence.schema.json")
    return proof


def _token_info(access_token: str) -> TokenInfo:
    request = urllib.request.Request(
        TOKEN_INFO_URL,
        data=urllib.parse.urlencode({"access_token": access_token}).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(MAX_TOKEN_INFO_BYTES + 1)
    except Exception as exc:
        raise ValidationError("Google token-info request failed") from exc
    if len(raw) > MAX_TOKEN_INFO_BYTES:
        raise ValidationError("Google token-info response is too large")
    payload = _strict_object(raw, label="Google token-info response")
    if payload.get("error"):
        raise ValidationError("Google token-info rejected the access token")
    scope = payload.get("scope")
    if not isinstance(scope, str) or not scope:
        raise ValidationError("Google token-info response omits scope")
    authorized_parties = {
        value
        for field in ("azp", "issued_to")
        if isinstance((value := payload.get(field)), str) and value
    }
    if len(authorized_parties) != 1:
        raise ValidationError(
            "Google token-info response has no unique authorized OAuth client"
        )
    return TokenInfo(
        scopes=frozenset(scope.split()),
        authorized_party=authorized_parties.pop(),
    )


def observe_drive_access_from_adc(
    *,
    adc_path: Path,
    authority: VerifiedOAuthAuthority,
    observed_at: str | None = None,
    root_fd: int | None = None,
    tokeninfo_fetcher: Callable[[str], TokenInfo] = _token_info,
) -> dict[str, Any]:
    """Load Better Colab ADC and execute a live v4.2 observation."""

    metadata, _ = _read_private_json(adc_path, label="Better Colab Drive ADC")
    required = {
        "type",
        "client_id",
        "client_secret",
        "refresh_token",
        "better_colab_scope",
        "better_colab_oauth_config_sha256",
        "better_colab_provider_mode",
        "better_colab_created_at",
    }
    if set(metadata) != required or metadata.get("type") != "authorized_user":
        raise ValidationError("Better Colab Drive ADC shape is invalid")
    for secret_field in ("client_id", "client_secret", "refresh_token"):
        if (
            not isinstance(metadata.get(secret_field), str)
            or not metadata[secret_field]
        ):
            raise ValidationError(f"Better Colab Drive ADC {secret_field} is invalid")
    timestamp = observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    validate_oauth_authority_time(authority, evaluated_at=timestamp)
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        credentials, _ = google.auth.load_credentials_from_file(
            str(adc_path), scopes=[DRIVE_READONLY_SCOPE]
        )
        if (
            getattr(credentials, "client_id", metadata["client_id"])
            != metadata["client_id"]
        ):
            raise ValidationError("loaded Drive credential uses another OAuth client")
        if not credentials.valid:
            credentials.refresh(Request())
        token = getattr(credentials, "token", None)
        if not isinstance(token, str) or not token:
            raise ValidationError("Drive ADC did not produce an access token")
        token_info = tokeninfo_fetcher(token)
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Drive ADC dependency or refresh failed") from exc
    return observe_drive_access_v4_2(
        service=service,
        credential_metadata=metadata,
        principal_scopes=set(token_info.scopes),
        token_authorized_party=token_info.authorized_party,
        authority=authority,
        observed_at=timestamp,
        root_fd=root_fd,
    )
