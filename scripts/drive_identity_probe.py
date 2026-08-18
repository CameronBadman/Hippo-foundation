#!/usr/bin/env python3
"""Read-only Google Drive identity probe for the named Colab data lake.

Run only after the user has authenticated and mounted the intended account in
the same Colab runtime.  The script emits one compact JSON object and never
prints credentials, account email, file content, or child names.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"
SHARED_DRIVE_NAME = "Data"
LAKE_FOLDER_NAME = "graph-memory-data-lake"
MOUNT_ROOT = Path("/content/drive")
EXPECTED_ROOT = Path("/content/drive/Shareddrives/Data/graph-memory-data-lake")
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
TOKEN_INFO_TIMEOUT_SEC = 10.0
MAX_TOKEN_INFO_BYTES = 64 * 1024
FALLBACK_DEVNAME = "phase0-drive-readonly"
FALLBACK_RCLONE_SHA256 = (
    "f3f9aff817f9766029e50adf9a7963c169e475b8f10c7927823568a0d9443db7"
)
FALLBACK_STATE_KEYS = frozenset(
    {
        "pid",
        "process_start_time_ticks",
        "executable_sha256",
        "adc_sha256",
        "devname",
        "resolved_resource_id",
    }
)


class ProbeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _execute(request: Any) -> dict[str, Any]:
    value = request.execute(num_retries=3)
    if not isinstance(value, dict):
        raise ProbeError("Drive API response is not an object")
    return value


def _status_code(error: Exception) -> int | None:
    return getattr(getattr(error, "resp", None), "status", None)


def _fully_paginate(
    request_for_page: Callable[[str | None], Any],
    *,
    result_key: str,
    reject_incomplete_search: bool,
) -> list[dict[str, Any]]:
    """Collect all pages; restart once if a non-initial page token is invalid."""

    restarted = False
    while True:
        page_token: str | None = None
        values: list[dict[str, Any]] = []
        try:
            while True:
                response = _execute(request_for_page(page_token))
                if reject_incomplete_search and response.get("incompleteSearch") is True:
                    raise ProbeError("Drive API reported incompleteSearch=true")
                page_values = response.get(result_key, [])
                if not isinstance(page_values, list) or any(
                    not isinstance(value, dict) for value in page_values
                ):
                    raise ProbeError(f"Drive API {result_key} page is malformed")
                values.extend(page_values)
                token = response.get("nextPageToken")
                if token is None:
                    return values
                if not isinstance(token, str) or not token:
                    raise ProbeError("Drive API returned an invalid nextPageToken")
                page_token = token
        except Exception as exc:
            if _status_code(exc) == 400 and page_token is not None and not restarted:
                restarted = True
                continue
            raise


def _require_unique_drive(values: list[dict[str, Any]]) -> dict[str, Any]:
    if len(values) != 1:
        raise ProbeError(f"expected exactly one shared drive named Data; observed {len(values)}")
    drive = values[0]
    if drive.get("name") != SHARED_DRIVE_NAME or not isinstance(drive.get("id"), str):
        raise ProbeError("shared drive identity fields are invalid")
    if drive.get("hidden") is True:
        raise ProbeError("shared drive is hidden")
    if drive.get("capabilities", {}).get("canListChildren") is not True:
        raise ProbeError("shared drive cannot list children")
    return drive


def _require_unique_folder(values: list[dict[str, Any]], drive_id: str) -> dict[str, Any]:
    if len(values) != 1:
        raise ProbeError(
            f"expected exactly one direct graph-memory-data-lake folder; observed {len(values)}"
        )
    folder = values[0]
    required = {
        "name": LAKE_FOLDER_NAME,
        "mimeType": FOLDER_MIME_TYPE,
        "parents": [drive_id],
        "driveId": drive_id,
        "trashed": False,
    }
    for field, expected in required.items():
        if folder.get(field) != expected:
            raise ProbeError(f"lake folder identity mismatch: {field}")
    if folder.get("shortcutDetails") is not None:
        raise ProbeError("lake root is a shortcut rather than a folder")
    if folder.get("capabilities", {}).get("canListChildren") is not True:
        raise ProbeError("lake folder cannot list children")
    if not isinstance(folder.get("id"), str) or not isinstance(folder.get("version"), str):
        raise ProbeError("lake folder lacks a stable string ID/version")
    return folder


def _drive_comparable(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value.get("id"),
        "name": value.get("name"),
        "hidden": value.get("hidden", False),
        "createdTime": value.get("createdTime"),
        "canListChildren": value.get("capabilities", {}).get("canListChildren"),
    }


def _folder_comparable(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value.get("id"),
        "name": value.get("name"),
        "mimeType": value.get("mimeType"),
        "parents": value.get("parents"),
        "driveId": value.get("driveId"),
        "trashed": value.get("trashed"),
        "version": value.get("version"),
    }


def _decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _require_live_drive_mount(*, fallback_devname: str | None = None) -> None:
    for path in (MOUNT_ROOT, EXPECTED_ROOT):
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink():
                raise ProbeError(f"mounted lake path contains a symlink: {current}")
        try:
            if path.resolve(strict=True) != path:
                raise ProbeError(f"mounted lake path resolves elsewhere: {path}")
        except OSError as exc:
            raise ProbeError(f"mounted lake path is unavailable: {path}") from exc
    if not EXPECTED_ROOT.is_dir():
        raise ProbeError("expected mounted lake root is not a directory")

    try:
        mount_lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProbeError("cannot inspect live mount metadata") from exc
    mount_matches: list[tuple[str, str, set[str]]] = []
    for line in mount_lines:
        fields = line.split()
        if "-" not in fields or len(fields) < 7:
            continue
        separator = fields.index("-")
        mount_point = _decode_mount_field(fields[4])
        file_system = fields[separator + 1].casefold()
        source = _decode_mount_field(fields[separator + 2])
        mount_options = set(fields[5].split(","))
        if mount_point == str(MOUNT_ROOT):
            mount_matches.append((file_system, source, mount_options))
    if len(mount_matches) != 1:
        raise ProbeError("/content/drive is not a unique live DriveFS/FUSE mount")
    file_system, source, mount_options = mount_matches[0]
    if fallback_devname is None:
        if not any(marker in file_system for marker in ("fuse", "drive")):
            raise ProbeError("/content/drive is not a unique live DriveFS/FUSE mount")
    elif (
        file_system != "fuse.rclone"
        or source != fallback_devname
        or "ro" not in mount_options
    ):
        raise ProbeError("fallback mount metadata does not match protected state")

    try:
        with os.scandir(EXPECTED_ROOT) as entries:
            next(entries, None)
    except OSError as exc:
        raise ProbeError("mounted lake root is not searchable") from exc


def _token_info_scopes(
    access_token: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> set[str]:
    if not isinstance(access_token, str) or not access_token:
        raise ProbeError("credentials do not expose a current access token")
    request = urllib.request.Request(
        TOKEN_INFO_URL,
        data=urllib.parse.urlencode({"access_token": access_token}).encode("ascii"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=TOKEN_INFO_TIMEOUT_SEC) as response:
            body = response.read(MAX_TOKEN_INFO_BYTES + 1)
    except Exception as exc:
        raise ProbeError("Google token-info request failed") from exc
    if not isinstance(body, bytes):
        raise ProbeError("Google token-info response is malformed")
    if len(body) > MAX_TOKEN_INFO_BYTES:
        raise ProbeError("Google token-info response is too large")
    try:
        payload = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("Google token-info response is malformed") from exc
    if not isinstance(payload, dict):
        raise ProbeError("Google token-info response is malformed")
    scope_text = payload.get("scope")
    if not isinstance(scope_text, str) or not scope_text.strip():
        raise ProbeError("Google token-info response does not contain scopes")
    return set(scope_text.split())


def _credential_scopes(
    credentials: Any,
    *,
    tokeninfo_fetcher: Callable[[str], set[str]] = _token_info_scopes,
) -> set[str]:
    granted = getattr(credentials, "granted_scopes", None)
    if granted is not None:
        return {str(value) for value in granted}
    token = getattr(credentials, "token", None)
    if not isinstance(token, str) or not token:
        raise ProbeError("credentials do not expose a current access token")
    scopes = tokeninfo_fetcher(token)
    if not isinstance(scopes, set) or any(not isinstance(value, str) for value in scopes):
        raise ProbeError("Google token-info scopes are malformed")
    return scopes


def _require_private_file(path: Path, *, label: str) -> None:
    if not path.is_absolute():
        raise ProbeError(f"{label} path must be absolute")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProbeError(f"{label} file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ProbeError(f"{label} path is a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise ProbeError(f"{label} path is not a regular file")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise ProbeError(f"{label} file permissions are unsafe")


def _load_fallback_binding(adc_file: Path, state_file: Path) -> dict[str, Any]:
    _require_private_file(adc_file, label="ADC")
    _require_private_file(state_file, label="fallback state")
    try:
        raw = state_file.read_bytes()
    except OSError as exc:
        raise ProbeError("fallback state is unavailable") from exc
    if len(raw) > MAX_TOKEN_INFO_BYTES:
        raise ProbeError("fallback state is too large")
    try:
        state = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("fallback state is malformed") from exc
    if not isinstance(state, dict) or set(state) != FALLBACK_STATE_KEYS:
        raise ProbeError("fallback state is malformed")
    if not isinstance(state.get("pid"), int) or type(state["pid"]) is not int:
        raise ProbeError("fallback state is malformed")
    if (
        not isinstance(state.get("process_start_time_ticks"), int)
        or type(state["process_start_time_ticks"]) is not int
    ):
        raise ProbeError("fallback state is malformed")
    for key in (
        "executable_sha256",
        "adc_sha256",
        "devname",
        "resolved_resource_id",
    ):
        if not isinstance(state.get(key), str) or not state[key]:
            raise ProbeError("fallback state is malformed")
    if (
        state["devname"] != FALLBACK_DEVNAME
        or state["executable_sha256"] != FALLBACK_RCLONE_SHA256
    ):
        raise ProbeError("fallback state is malformed")
    try:
        adc_digest = hashlib.sha256(adc_file.read_bytes()).hexdigest()
    except OSError as exc:
        raise ProbeError("ADC file is unavailable") from exc
    if state["adc_sha256"] != adc_digest:
        raise ProbeError("fallback ADC digest mismatch")
    return state


def _load_fallback_validator() -> Callable[[Path, Path], dict[str, Any]]:
    path = Path(__file__).with_name("drive_mount_fallback.py")
    specification = importlib.util.spec_from_file_location(
        "_hf_drive_mount_fallback_validation", path
    )
    if specification is None or specification.loader is None:
        raise ProbeError("fallback validator is unavailable")
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
    except Exception as exc:
        raise ProbeError("fallback validator is unavailable") from exc
    validator = getattr(module, "validate_active_mount", None)
    if not callable(validator):
        raise ProbeError("fallback validator is unavailable")
    return validator


def _validate_fallback_runtime(
    adc_file: Path,
    state_file: Path,
    binding: dict[str, Any],
    *,
    validator: Callable[[Path, Path], dict[str, Any]] | None = None,
) -> None:
    selected_validator = validator or _load_fallback_validator()
    try:
        validated = selected_validator(adc_file, state_file)
    except Exception as exc:
        raise ProbeError("fallback runtime validation failed") from exc
    if validated != binding:
        raise ProbeError("fallback protected state changed during validation")


def _require_fallback_result_binding(
    result: dict[str, Any], binding: dict[str, Any]
) -> None:
    if result.get("provider_resource_id") != binding.get("resolved_resource_id"):
        raise ProbeError("fallback resource ID mismatch")


def probe(
    service: Any,
    *,
    principal_scopes: set[str],
    fallback_devname: str | None = None,
) -> dict[str, Any]:
    if DRIVE_READONLY_SCOPE not in principal_scopes:
        raise ProbeError("drive.readonly scope was not granted")
    other_drive_scopes = sorted(
        scope
        for scope in principal_scopes
        if scope.startswith("https://www.googleapis.com/auth/drive")
        and scope != DRIVE_READONLY_SCOPE
    )
    if other_drive_scopes:
        raise ProbeError("a Drive scope other than drive.readonly was granted")
    if os.environ.get("HF_DRIVE_SAME_ACCOUNT_ATTESTED") != "1":
        raise ProbeError("same-account mount/API attestation is missing")

    about = _execute(service.about().get(fields="user(permissionId)"))
    permission_id = about.get("user", {}).get("permissionId")
    if not isinstance(permission_id, str) or not permission_id:
        raise ProbeError("Drive API did not return a principal permission ID")
    permission_hash = "sha256:" + hashlib.sha256(
        b"hf-drive-principal-v1\x00" + permission_id.encode("utf-8")
    ).hexdigest()

    drive_fields = "nextPageToken,drives(id,name,hidden,createdTime,capabilities(canListChildren))"
    drives = _fully_paginate(
        lambda token: service.drives().list(
            q="name = 'Data'",
            pageSize=100,
            pageToken=token,
            useDomainAdminAccess=False,
            fields=drive_fields,
        ),
        result_key="drives",
        reject_incomplete_search=False,
    )
    drive = _require_unique_drive(drives)
    drive_id = drive["id"]
    drive_get_fields = "id,name,hidden,createdTime,capabilities(canListChildren)"
    drive_confirmed = _execute(
        service.drives().get(
            driveId=drive_id,
            useDomainAdminAccess=False,
            fields=drive_get_fields,
        )
    )
    if _drive_comparable(drive) != _drive_comparable(drive_confirmed):
        raise ProbeError("shared drive list/get identity mismatch")

    folder_fields = (
        "nextPageToken,incompleteSearch,"
        "files(id,name,mimeType,parents,driveId,trashed,createdTime,modifiedTime,version,"
        "capabilities(canListChildren),shortcutDetails)"
    )
    folders = _fully_paginate(
        lambda token: service.files().list(
            corpora="drive",
            driveId=drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            spaces="drive",
            pageSize=1000,
            pageToken=token,
            q=(
                f"'{drive_id}' in parents and "
                "name = 'graph-memory-data-lake' and trashed = false"
            ),
            fields=folder_fields,
        ),
        result_key="files",
        reject_incomplete_search=True,
    )
    folder = _require_unique_folder(folders, drive_id)
    folder_id = folder["id"]
    folder_get_fields = (
        "id,name,mimeType,parents,driveId,trashed,createdTime,modifiedTime,version,"
        "capabilities(canListChildren),shortcutDetails"
    )
    folder_confirmed = _execute(
        service.files().get(
            fileId=folder_id,
            supportsAllDrives=True,
            fields=folder_get_fields,
        )
    )
    _require_unique_folder([folder_confirmed], drive_id)
    if _folder_comparable(folder) != _folder_comparable(folder_confirmed):
        raise ProbeError("lake folder list/get identity mismatch")

    _require_live_drive_mount(fallback_devname=fallback_devname)

    drive_repeated = _execute(
        service.drives().get(
            driveId=drive_id,
            useDomainAdminAccess=False,
            fields=drive_get_fields,
        )
    )
    folder_repeated = _execute(
        service.files().get(
            fileId=folder_id,
            supportsAllDrives=True,
            fields=folder_get_fields,
        )
    )
    if _drive_comparable(drive_confirmed) != _drive_comparable(drive_repeated):
        raise ProbeError("shared drive identity drifted during observation")
    if _folder_comparable(folder_confirmed) != _folder_comparable(folder_repeated):
        raise ProbeError("lake folder identity/version drifted during observation")

    return {
        "schema_version": "1.0.0",
        "record_kind": "drive_identity_observation",
        "observed_at": _utc_now(),
        "requested_scope": DRIVE_READONLY_SCOPE,
        "scope_exact": True,
        "same_account_human_attested": True,
        "principal_permission_id_sha256": permission_hash,
        "provider": "google_drive_shared_drive",
        "provider_resource_id": drive_id,
        "root_resource_id": folder_id,
        "observed_root": str(EXPECTED_ROOT),
        "method": "google_drive_api_v3_authenticated",
        "checks": {
            "unique_shared_drive": True,
            "unique_direct_folder": True,
            "folder_not_shortcut": True,
            "list_get_consistent": True,
            "live_drivefs_mount": True,
            "identity_stable": True,
        },
        "contains_evaluation_content": False,
        "api_drive_write_authorized": False,
        "drive_write_performed": False,
        "mount_write_capability_assessed": False,
        "training_authorized": False,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adc-file", type=Path)
    parser.add_argument("--fallback-state-file", type=Path)
    args = parser.parse_args(argv)
    if (args.adc_file is None) != (args.fallback_state_file is None):
        parser.error("--adc-file and --fallback-state-file must be supplied together")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        binding = None
        if args.adc_file is None:
            credentials, _ = google.auth.default(scopes=[DRIVE_READONLY_SCOPE])
        else:
            binding = _load_fallback_binding(
                args.adc_file, args.fallback_state_file
            )
            _validate_fallback_runtime(
                args.adc_file, args.fallback_state_file, binding
            )
            credentials, _ = google.auth.load_credentials_from_file(
                str(args.adc_file), scopes=[DRIVE_READONLY_SCOPE]
            )
        if not credentials.valid:
            credentials.refresh(Request())
        scopes = _credential_scopes(credentials)
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        result = probe(
            service,
            principal_scopes=scopes,
            fallback_devname=None if binding is None else binding["devname"],
        )
        if binding is not None:
            _require_fallback_result_binding(result, binding)
    except Exception as exc:
        safe_error = (
            str(exc)
            if isinstance(exc, ProbeError)
            else "external dependency failure (details suppressed)"
        )
        result = {
            "schema_version": "1.0.0",
            "record_kind": "drive_identity_probe_error",
            "error_type": type(exc).__name__,
            "error": safe_error,
        }
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
