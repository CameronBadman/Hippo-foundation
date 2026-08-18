#!/usr/bin/env python3
"""Gated, read-only rclone fallback for the Phase 0 Drive mount.

The fallback never writes a persistent rclone configuration.  It accepts only
one explicitly named, private ADC file, requires a matching desktop OAuth
client file, resolves the shared-drive resource through the Drive API, and
binds the running FUSE process and mount metadata to private local state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable, NamedTuple
import urllib.parse
import urllib.request
import zipfile


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"
RCLONE_VERSION = "1.75.0"
RCLONE_ARCHIVE_URL = (
    "https://downloads.rclone.org/v1.75.0/"
    "rclone-v1.75.0-linux-amd64.zip"
)
RCLONE_ARCHIVE_SHA256 = (
    "aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa"
)
RCLONE_BINARY_SHA256 = (
    "f3f9aff817f9766029e50adf9a7963c169e475b8f10c7927823568a0d9443db7"
)
RCLONE_LICENCE_URL = (
    "https://raw.githubusercontent.com/rclone/rclone/v1.75.0/COPYING"
)
RCLONE_LICENCE_SHA256 = (
    "8cd2e9e750b90a04b7d82dbbca3930c696ae0309d7c10464f90a44f45754cd04"
)
RCLONE_ARCHIVE_PREFIX = "rclone-v1.75.0-linux-amd64"
RCLONE_DEVNAME = "phase0-drive-readonly"
MOUNT_ROOT = Path("/content/drive")
SHARED_DRIVE_NAME = "Data"
TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
TOKEN_INFO_TIMEOUT_SEC = 10.0
DOWNLOAD_TIMEOUT_SEC = 30.0
MOUNT_START_TIMEOUT_SEC = 20.0
MAX_JSON_BYTES = 1024 * 1024
MAX_TOKEN_INFO_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_LICENCE_BYTES = 64 * 1024
MAX_EXTRACTED_BINARY_BYTES = 256 * 1024 * 1024
STATE_KEYS = frozenset(
    {
        "pid",
        "process_start_time_ticks",
        "executable_sha256",
        "adc_sha256",
        "devname",
        "resolved_resource_id",
    }
)
RUNTIME_FILENAMES = frozenset(
    {"rclone", "COPYING", "rclone.zip", "rclone.zip.part"}
)
RCLONE_ENV_PASSTHROUGH = frozenset(
    {
        "HOME",
        "PATH",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)


class FallbackError(RuntimeError):
    """A deliberately detail-free local fallback failure."""

    def __init__(self, code: str):
        super().__init__(f"Drive fallback failed: {code}")
        self.code = code


class MountEntry(NamedTuple):
    file_system: str
    source: str
    mount_options: frozenset[str]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise FallbackError("file_digest_failed") from exc
    return digest.hexdigest()


def _require_supported_platform(*, system: str, machine: str) -> None:
    if system != "Linux" or machine.casefold() not in {"x86_64", "amd64"}:
        raise FallbackError("unsupported_platform")


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise FallbackError("unsafe_path") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise FallbackError("unsafe_symlink")


def _require_private_file(path: Path, *, label: str) -> None:
    del label
    if not path.is_absolute():
        raise FallbackError("path_not_absolute")
    _reject_symlink_components(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FallbackError("private_file_unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise FallbackError("unsafe_symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise FallbackError("not_regular_file")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise FallbackError("unsafe_permissions")


def _require_private_directory(path: Path) -> None:
    if not path.is_absolute():
        raise FallbackError("path_not_absolute")
    _reject_symlink_components(path)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FallbackError("private_directory_unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise FallbackError("not_directory")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o777 != 0o700:
        raise FallbackError("unsafe_permissions")


def _prepare_state_directory(state_file: Path) -> None:
    if not state_file.is_absolute() or state_file.name in {"", ".", ".."}:
        raise FallbackError("state_path_invalid")
    parent = state_file.parent
    _reject_symlink_components(parent)
    if not parent.exists():
        try:
            parent.mkdir(mode=0o700, parents=False)
        except OSError as exc:
            raise FallbackError("state_directory_create_failed") from exc
    _require_private_directory(parent)


def _read_private_bytes(path: Path, *, maximum: int) -> bytes:
    _require_private_file(path, label="private")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            value = handle.read(maximum + 1)
    except OSError as exc:
        raise FallbackError("private_file_read_failed") from exc
    if len(value) > maximum:
        raise FallbackError("private_file_too_large")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            _read_private_bytes(path, maximum=MAX_JSON_BYTES).decode(
                "utf-8", errors="strict"
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FallbackError("private_json_malformed") from exc
    if not isinstance(value, dict):
        raise FallbackError("private_json_malformed")
    return value


def _validate_oauth_binding(adc_file: Path, client_id_file: Path) -> None:
    adc = _read_json(adc_file)
    client_document = _read_json(client_id_file)
    installed = client_document.get("installed")
    if not isinstance(installed, dict) or "web" in client_document:
        raise FallbackError("desktop_oauth_prerequisite_missing")
    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")
    if not all(isinstance(value, str) and value for value in (client_id, client_secret)):
        raise FallbackError("desktop_oauth_prerequisite_missing")
    if (
        adc.get("type") != "authorized_user"
        or not isinstance(adc.get("refresh_token"), str)
        or not adc["refresh_token"]
    ):
        raise FallbackError("user_adc_required")
    if adc.get("client_id") != client_id or adc.get("client_secret") != client_secret:
        raise FallbackError("oauth_binding_mismatch")


def _require_readonly_scope(scopes: set[str]) -> None:
    if DRIVE_READONLY_SCOPE not in scopes:
        raise FallbackError("readonly_scope_missing")
    other_drive_scopes = {
        scope
        for scope in scopes
        if scope.startswith("https://www.googleapis.com/auth/drive")
        and scope != DRIVE_READONLY_SCOPE
    }
    if other_drive_scopes:
        raise FallbackError("broader_drive_scope")


def _token_info_scopes(access_token: str) -> set[str]:
    if not isinstance(access_token, str) or not access_token:
        raise FallbackError("access_token_unavailable")
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
        with urllib.request.urlopen(
            request, timeout=TOKEN_INFO_TIMEOUT_SEC
        ) as response:
            body = response.read(MAX_TOKEN_INFO_BYTES + 1)
    except Exception as exc:
        raise FallbackError("token_info_failed") from exc
    if not isinstance(body, bytes) or len(body) > MAX_TOKEN_INFO_BYTES:
        raise FallbackError("token_info_invalid")
    try:
        value = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FallbackError("token_info_invalid") from exc
    scope_text = value.get("scope") if isinstance(value, dict) else None
    if not isinstance(scope_text, str) or not scope_text.strip():
        raise FallbackError("token_info_invalid")
    return set(scope_text.split())


def _credential_scopes(credentials: Any) -> set[str]:
    granted = getattr(credentials, "granted_scopes", None)
    if granted is not None:
        return {str(value) for value in granted}
    return _token_info_scopes(getattr(credentials, "token", None))


def _execute(request: Any) -> dict[str, Any]:
    try:
        value = request.execute(num_retries=3)
    except Exception as exc:
        raise FallbackError("drive_api_failed") from exc
    if not isinstance(value, dict):
        raise FallbackError("drive_api_invalid")
    return value


def _drive_comparable(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value.get("id"),
        "name": value.get("name"),
        "hidden": value.get("hidden", False),
        "createdTime": value.get("createdTime"),
        "canListChildren": value.get("capabilities", {}).get("canListChildren"),
    }


def _require_unique_shared_drive(values: list[dict[str, Any]]) -> dict[str, Any]:
    if len(values) != 1:
        raise FallbackError("drive_match_count")
    drive = values[0]
    if (
        drive.get("name") != SHARED_DRIVE_NAME
        or not isinstance(drive.get("id"), str)
        or not drive["id"]
        or drive.get("hidden") is True
        or drive.get("capabilities", {}).get("canListChildren") is not True
    ):
        raise FallbackError("drive_identity_invalid")
    return drive


def _resolve_shared_drive_id(service: Any) -> str:
    fields = (
        "nextPageToken,drives(id,name,hidden,createdTime,"
        "capabilities(canListChildren))"
    )
    token: str | None = None
    values: list[dict[str, Any]] = []
    while True:
        page = _execute(
            service.drives().list(
                q="name = 'Data'",
                pageSize=100,
                pageToken=token,
                useDomainAdminAccess=False,
                fields=fields,
            )
        )
        page_values = page.get("drives", [])
        if not isinstance(page_values, list) or any(
            not isinstance(value, dict) for value in page_values
        ):
            raise FallbackError("drive_api_invalid")
        values.extend(page_values)
        next_token = page.get("nextPageToken")
        if next_token is None:
            break
        if not isinstance(next_token, str) or not next_token:
            raise FallbackError("drive_api_invalid")
        token = next_token
    drive = _require_unique_shared_drive(values)
    confirmed = _execute(
        service.drives().get(
            driveId=drive["id"],
            useDomainAdminAccess=False,
            fields="id,name,hidden,createdTime,capabilities(canListChildren)",
        )
    )
    _require_unique_shared_drive([confirmed])
    if _drive_comparable(drive) != _drive_comparable(confirmed):
        raise FallbackError("drive_identity_drift")
    return drive["id"]


def _load_drive_context(adc_file: Path) -> tuple[Any, str]:
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        credentials, _ = google.auth.load_credentials_from_file(
            str(adc_file), scopes=[DRIVE_READONLY_SCOPE]
        )
        if not credentials.valid:
            credentials.refresh(Request())
        _require_readonly_scope(_credential_scopes(credentials))
        service = build(
            "drive", "v3", credentials=credentials, cache_discovery=False
        )
        return credentials, _resolve_shared_drive_id(service)
    except FallbackError:
        raise
    except Exception as exc:
        raise FallbackError("drive_context_failed") from exc


def _download_bounded(
    url: str,
    destination: Path,
    *,
    accept: str,
    maximum: int,
    too_large_code: str,
    failed_code: str,
) -> None:
    request = urllib.request.Request(
        url,
        headers={"Accept": accept, "User-Agent": "hf-phase0-fallback"},
        method="GET",
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    total = 0
    try:
        descriptor = os.open(destination, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(
            request, timeout=DOWNLOAD_TIMEOUT_SEC
        ) as response:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > maximum:
                    raise FallbackError(too_large_code)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except FallbackError:
        raise
    except Exception as exc:
        raise FallbackError(failed_code) from exc


def _download_archive(url: str, destination: Path) -> None:
    _download_bounded(
        url,
        destination,
        accept="application/zip",
        maximum=MAX_ARCHIVE_BYTES,
        too_large_code="archive_too_large",
        failed_code="archive_download_failed",
    )


def _download_licence(url: str, destination: Path) -> None:
    _download_bounded(
        url,
        destination,
        accept="text/plain",
        maximum=MAX_LICENCE_BYTES,
        too_large_code="licence_too_large",
        failed_code="licence_download_failed",
    )


def _extract_member(
    archive: zipfile.ZipFile,
    member: str,
    destination: Path,
    *,
    maximum: int,
    mode: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    total = 0
    try:
        descriptor = os.open(destination, flags, mode)
        with os.fdopen(descriptor, "wb") as output, archive.open(member, "r") as source:
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > maximum:
                    raise FallbackError("archive_member_too_large")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        destination.chmod(mode)
    except FallbackError:
        raise
    except Exception as exc:
        raise FallbackError("archive_extract_failed") from exc


def _install_rclone(
    runtime_dir: Path,
    *,
    archive_downloader: Callable[[str, Path], None] = _download_archive,
    licence_downloader: Callable[[str, Path], None] = _download_licence,
) -> Path:
    archive_path = runtime_dir / "rclone.zip"
    binary_path = runtime_dir / "rclone"
    licence_path = runtime_dir / "COPYING"
    archive_downloader(RCLONE_ARCHIVE_URL, archive_path)
    if _sha256_file(archive_path) != RCLONE_ARCHIVE_SHA256:
        raise FallbackError("archive_checksum_mismatch")
    binary_member = f"{RCLONE_ARCHIVE_PREFIX}/rclone"
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = set(archive.namelist())
            if binary_member not in names:
                raise FallbackError("archive_layout_invalid")
            _extract_member(
                archive,
                binary_member,
                binary_path,
                maximum=MAX_EXTRACTED_BINARY_BYTES,
                mode=0o500,
            )
    except FallbackError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise FallbackError("archive_invalid") from exc
    if _sha256_file(binary_path) != RCLONE_BINARY_SHA256:
        raise FallbackError("binary_checksum_mismatch")
    licence_downloader(RCLONE_LICENCE_URL, licence_path)
    if _sha256_file(licence_path) != RCLONE_LICENCE_SHA256:
        raise FallbackError("licence_checksum_mismatch")
    try:
        licence_path.chmod(0o400)
        archive_path.unlink()
    except OSError as exc:
        raise FallbackError("archive_cleanup_failed") from exc
    return binary_path


def _rclone_environment(
    adc_file: Path,
    drive_id: str,
    *,
    base_environment: dict[str, str] | os._Environ[str] | None = None,
) -> dict[str, str]:
    source = os.environ if base_environment is None else base_environment
    environment = {
        key: value
        for key, value in source.items()
        if key in RCLONE_ENV_PASSTHROUGH
    }
    environment.update(
        {
            "GOOGLE_APPLICATION_CREDENTIALS": str(adc_file),
            "RCLONE_CONFIG": "/dev/null",
            "RCLONE_CONFIG_PHASE0_DATA_TYPE": "drive",
            "RCLONE_CONFIG_PHASE0_DATA_ENV_AUTH": "true",
            "RCLONE_CONFIG_PHASE0_DATA_SCOPE": "drive.readonly",
            "RCLONE_CONFIG_PHASE0_DATA_TEAM_DRIVE": drive_id,
            "RCLONE_CONFIG_PHASE0_SHARED_TYPE": "combine",
            "RCLONE_CONFIG_PHASE0_SHARED_UPSTREAMS": "Data=phase0_data:",
            "RCLONE_CONFIG_PHASE0_ROOT_TYPE": "combine",
            "RCLONE_CONFIG_PHASE0_ROOT_UPSTREAMS": (
                "Shareddrives=phase0_shared:"
            ),
        }
    )
    return environment


def _mount_command(binary: Path, mountpoint: Path) -> list[str]:
    return [
        str(binary),
        "mount",
        "phase0_root:",
        str(mountpoint),
        "--config",
        "/dev/null",
        "--read-only",
        "--vfs-cache-mode",
        "off",
        "--buffer-size",
        "0",
        "--vfs-read-ahead",
        "0",
        "--file-perms",
        "0400",
        "--dir-perms",
        "0500",
        "--umask",
        "077",
        "--devname",
        RCLONE_DEVNAME,
    ]


def _runtime_directory(state_file: Path) -> Path:
    return state_file.parent / f".{state_file.name}.runtime"


def _write_state(state_file: Path, state: dict[str, Any]) -> None:
    _prepare_state_directory(state_file)
    if state_file.exists() or state_file.is_symlink():
        raise FallbackError("state_already_exists")
    if set(state) != STATE_KEYS:
        raise FallbackError("state_invalid")
    temporary = state_file.parent / f".{state_file.name}.tmp-{os.getpid()}"
    payload = (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, state_file)
        state_file.chmod(0o600)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise FallbackError("state_write_failed") from exc


def _load_state(state_file: Path) -> dict[str, Any]:
    state = _read_json(state_file)
    if set(state) != STATE_KEYS:
        raise FallbackError("state_invalid")
    if (
        type(state.get("pid")) is not int
        or state["pid"] <= 0
        or type(state.get("process_start_time_ticks")) is not int
        or state["process_start_time_ticks"] <= 0
    ):
        raise FallbackError("state_invalid")
    for key in ("executable_sha256", "adc_sha256"):
        value = state.get(key)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise FallbackError("state_invalid")
    if state["executable_sha256"] != RCLONE_BINARY_SHA256:
        raise FallbackError("state_invalid")
    if state.get("devname") != RCLONE_DEVNAME:
        raise FallbackError("state_invalid")
    resource_id = state.get("resolved_resource_id")
    if not isinstance(resource_id, str) or not resource_id:
        raise FallbackError("state_invalid")
    return state


def _require_state_binding(
    state: dict[str, Any], adc_file: Path, drive_id: str
) -> None:
    if state.get("adc_sha256") != _sha256_file(adc_file):
        raise FallbackError("adc_binding_mismatch")
    if state.get("resolved_resource_id") != drive_id:
        raise FallbackError("resource_binding_mismatch")


def _decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _mount_entries(mountinfo: str, mountpoint: Path) -> list[MountEntry]:
    entries: list[MountEntry] = []
    for line in mountinfo.splitlines():
        fields = line.split()
        if "-" not in fields or len(fields) < 10:
            continue
        separator = fields.index("-")
        if separator + 2 >= len(fields):
            continue
        if _decode_mount_field(fields[4]) != str(mountpoint):
            continue
        entries.append(
            MountEntry(
                file_system=fields[separator + 1],
                source=_decode_mount_field(fields[separator + 2]),
                mount_options=frozenset(fields[5].split(",")),
            )
        )
    return entries


def _read_mountinfo() -> str:
    try:
        return Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError as exc:
        raise FallbackError("mountinfo_unavailable") from exc


def _require_exact_mount(mountinfo: str, mountpoint: Path) -> MountEntry:
    entries = _mount_entries(mountinfo, mountpoint)
    if not entries:
        raise FallbackError("mount_missing")
    if len(entries) != 1:
        raise FallbackError("foreign_mount")
    entry = entries[0]
    if (
        entry.file_system != "fuse.rclone"
        or entry.source != RCLONE_DEVNAME
        or "ro" not in entry.mount_options
    ):
        raise FallbackError("foreign_mount")
    return entry


def _require_mountpoint_available(mountpoint: Path) -> None:
    if not mountpoint.is_absolute():
        raise FallbackError("mountpoint_invalid")
    _reject_symlink_components(mountpoint)
    if _mount_entries(_read_mountinfo(), mountpoint):
        raise FallbackError("mountpoint_busy")
    if not mountpoint.exists():
        try:
            mountpoint.mkdir(mode=0o700, parents=False)
        except OSError as exc:
            raise FallbackError("mountpoint_create_failed") from exc
    try:
        metadata = mountpoint.lstat()
    except OSError as exc:
        raise FallbackError("mountpoint_unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise FallbackError("mountpoint_invalid")
    try:
        if any(mountpoint.iterdir()):
            raise FallbackError("mountpoint_not_empty")
    except OSError as exc:
        raise FallbackError("mountpoint_unavailable") from exc


def _process_start_time(pid: int) -> int:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        end = value.rindex(")")
        fields = value[end + 2 :].split()
        return int(fields[19])
    except (OSError, ValueError, IndexError) as exc:
        raise FallbackError("process_unavailable") from exc


def _process_command(pid: int) -> list[str]:
    try:
        value = Path(f"/proc/{pid}/cmdline").read_bytes()
        return [
            part.decode("utf-8", errors="strict")
            for part in value.rstrip(b"\x00").split(b"\x00")
            if part
        ]
    except (OSError, UnicodeDecodeError) as exc:
        raise FallbackError("process_unavailable") from exc


def _process_environment(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
        result: dict[str, str] = {}
        for item in raw.rstrip(b"\x00").split(b"\x00"):
            if not item or b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            result[key.decode("utf-8", errors="strict")] = value.decode(
                "utf-8", errors="strict"
            )
        return result
    except (OSError, UnicodeDecodeError) as exc:
        raise FallbackError("process_unavailable") from exc


def _process_executable_hash(pid: int) -> str:
    return _sha256_file(Path(f"/proc/{pid}/exe"))


def _require_process_identity(
    state: dict[str, Any],
    binary: Path,
    adc_file: Path,
    drive_id: str,
    *,
    mountpoint: Path,
    start_time_reader: Callable[[int], int] = _process_start_time,
    executable_hash_reader: Callable[[int], str] = _process_executable_hash,
    command_reader: Callable[[int], list[str]] = _process_command,
    environment_reader: Callable[[int], dict[str, str]] = _process_environment,
) -> None:
    pid = state["pid"]
    if start_time_reader(pid) != state["process_start_time_ticks"]:
        raise FallbackError("process_identity_mismatch")
    actual_hash = executable_hash_reader(pid)
    if (
        actual_hash != state["executable_sha256"]
        or actual_hash != _sha256_file(binary)
    ):
        raise FallbackError("process_identity_mismatch")
    if command_reader(pid) != _mount_command(binary, mountpoint):
        raise FallbackError("process_arguments_mismatch")
    actual_environment = environment_reader(pid)
    expected_environment = _rclone_environment(
        adc_file, drive_id, base_environment={}
    )
    for key, expected in expected_environment.items():
        if actual_environment.get(key) != expected:
            raise FallbackError("process_environment_mismatch")
    allowed_rclone_keys = {
        key for key in expected_environment if key.startswith("RCLONE_")
    }
    actual_rclone_keys = {
        key for key in actual_environment if key.startswith("RCLONE_")
    }
    if actual_rclone_keys != allowed_rclone_keys:
        raise FallbackError("process_environment_mismatch")


def _runtime_binary(state_file: Path) -> Path:
    return _runtime_directory(state_file) / "rclone"


def validate_active_mount(
    adc_file: Path,
    state_file: Path,
    *,
    drive_id_resolver: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    adc_file = Path(adc_file)
    state_file = Path(state_file)
    _require_private_file(adc_file, label="ADC")
    if not state_file.is_absolute() or state_file.name in {"", ".", ".."}:
        raise FallbackError("state_path_invalid")
    _require_private_directory(state_file.parent)
    state = _load_state(state_file)
    runtime_dir = _runtime_directory(state_file)
    _require_private_directory(runtime_dir)
    binary = runtime_dir / "rclone"
    licence = runtime_dir / "COPYING"
    _require_private_file(binary, label="rclone")
    _require_private_file(licence, label="licence")
    if _sha256_file(binary) != RCLONE_BINARY_SHA256:
        raise FallbackError("binary_checksum_mismatch")
    _require_process_identity(
        state,
        binary,
        adc_file,
        state["resolved_resource_id"],
        mountpoint=MOUNT_ROOT,
    )
    _require_exact_mount(_read_mountinfo(), MOUNT_ROOT)
    if drive_id_resolver is None:
        _, drive_id = _load_drive_context(adc_file)
    else:
        drive_id = drive_id_resolver(adc_file)
    _require_state_binding(state, adc_file, drive_id)
    return state


def _spawn_mount(
    command: list[str], environment: dict[str, str]
) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise FallbackError("mount_spawn_failed") from exc


def _wait_for_active_mount(
    process: subprocess.Popen[bytes],
    state: dict[str, Any],
    binary: Path,
    adc_file: Path,
    drive_id: str,
    *,
    timeout: float = MOUNT_START_TIMEOUT_SEC,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise FallbackError("mount_start_failed")
        try:
            _require_exact_mount(_read_mountinfo(), MOUNT_ROOT)
        except FallbackError as exc:
            if exc.code == "mount_missing":
                time.sleep(0.1)
                continue
            raise
        _require_process_identity(
            state,
            binary,
            adc_file,
            drive_id,
            mountpoint=MOUNT_ROOT,
        )
        return
    raise FallbackError("mount_start_timeout")


def _unmount(mountpoint: Path) -> None:
    utility = shutil.which("fusermount3") or shutil.which("fusermount")
    if utility is None:
        raise FallbackError("unmount_utility_missing")
    try:
        subprocess.run(
            [utility, "-u", "--", str(mountpoint)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FallbackError("unmount_failed") from exc


def _terminate_owned_process(pid: int, start_time: int) -> None:
    try:
        current_start = _process_start_time(pid)
    except FallbackError as exc:
        if not Path(f"/proc/{pid}").exists():
            return
        raise exc
    if current_start != start_time:
        raise FallbackError("process_identity_mismatch")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise FallbackError("process_termination_failed") from exc
    deadline = time.monotonic() + 5
    while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not Path(f"/proc/{pid}").exists():
        return
    if _process_start_time(pid) != start_time:
        raise FallbackError("process_identity_mismatch")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise FallbackError("process_termination_failed") from exc


def _remove_runtime_directory(runtime_dir: Path) -> None:
    if not runtime_dir.exists():
        return
    _require_private_directory(runtime_dir)
    try:
        children = list(runtime_dir.iterdir())
    except OSError as exc:
        raise FallbackError("runtime_cleanup_failed") from exc
    if any(child.name not in RUNTIME_FILENAMES or child.is_symlink() for child in children):
        raise FallbackError("runtime_cleanup_refused")
    try:
        for child in children:
            if child.is_dir():
                raise FallbackError("runtime_cleanup_refused")
            child.unlink()
        runtime_dir.rmdir()
    except FallbackError:
        raise
    except OSError as exc:
        raise FallbackError("runtime_cleanup_failed") from exc


def _remove_state_file(state_file: Path) -> None:
    if not state_file.exists() and not state_file.is_symlink():
        return
    _require_private_file(state_file, label="state")
    try:
        state_file.unlink()
    except OSError as exc:
        raise FallbackError("state_cleanup_failed") from exc


def _cleanup_failed_start(
    process: subprocess.Popen[bytes] | Any,
    state: dict[str, Any] | None,
) -> None:
    if state is None:
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FallbackError("failed_start_cleanup_failed") from exc
        return

    cleanup_error: FallbackError | None = None
    entries = _mount_entries(_read_mountinfo(), MOUNT_ROOT)
    if entries:
        try:
            _require_exact_mount(_read_mountinfo(), MOUNT_ROOT)
            _unmount(MOUNT_ROOT)
        except FallbackError as exc:
            cleanup_error = exc
    try:
        _terminate_owned_process(
            process.pid, state["process_start_time_ticks"]
        )
    except FallbackError as exc:
        if cleanup_error is None:
            cleanup_error = exc
    if _mount_entries(_read_mountinfo(), MOUNT_ROOT) and cleanup_error is None:
        cleanup_error = FallbackError("failed_start_cleanup_incomplete")
    if cleanup_error is not None:
        raise cleanup_error


def start(
    adc_file: Path,
    state_file: Path,
    client_id_file: Path,
) -> dict[str, Any]:
    adc_file = Path(adc_file)
    state_file = Path(state_file)
    client_id_file = Path(client_id_file)
    _require_supported_platform(system=platform.system(), machine=platform.machine())
    if os.environ.get("HF_DRIVE_SAME_ACCOUNT_ATTESTED") != "1":
        raise FallbackError("same_account_attestation_missing")
    _prepare_state_directory(state_file)
    if state_file.exists() or state_file.is_symlink():
        raise FallbackError("state_already_exists")
    _require_private_file(adc_file, label="ADC")
    _require_private_file(client_id_file, label="desktop OAuth client")
    _validate_oauth_binding(adc_file, client_id_file)
    _require_mountpoint_available(MOUNT_ROOT)
    _, drive_id = _load_drive_context(adc_file)

    runtime_dir = _runtime_directory(state_file)
    if runtime_dir.exists() or runtime_dir.is_symlink():
        raise FallbackError("runtime_already_exists")
    try:
        runtime_dir.mkdir(mode=0o700)
        runtime_dir.chmod(0o700)
    except OSError as exc:
        raise FallbackError("runtime_create_failed") from exc

    process: subprocess.Popen[bytes] | Any | None = None
    state: dict[str, Any] | None = None
    try:
        binary = _install_rclone(runtime_dir)
        environment = _rclone_environment(adc_file, drive_id)
        process = _spawn_mount(_mount_command(binary, MOUNT_ROOT), environment)
        state = {
            "pid": process.pid,
            "process_start_time_ticks": _process_start_time(process.pid),
            "executable_sha256": _sha256_file(binary),
            "adc_sha256": _sha256_file(adc_file),
            "devname": RCLONE_DEVNAME,
            "resolved_resource_id": drive_id,
        }
        if state["executable_sha256"] != RCLONE_BINARY_SHA256:
            raise FallbackError("binary_checksum_mismatch")
        _write_state(state_file, state)
        _wait_for_active_mount(
            process, state, binary, adc_file, drive_id
        )
        return state
    except BaseException as original_error:
        if process is not None:
            try:
                _cleanup_failed_start(process, state)
            except FallbackError as cleanup_error:
                raise cleanup_error from original_error
        try:
            _remove_state_file(state_file)
            _remove_runtime_directory(runtime_dir)
        except FallbackError as cleanup_error:
            raise cleanup_error from original_error
        raise


def status(adc_file: Path, state_file: Path) -> dict[str, Any]:
    state = validate_active_mount(Path(adc_file), Path(state_file))
    return {
        "active": True,
        "devname": state["devname"],
        "resolved_resource_id": state["resolved_resource_id"],
    }


def stop(adc_file: Path, state_file: Path) -> dict[str, Any]:
    adc_file = Path(adc_file)
    state_file = Path(state_file)
    state = validate_active_mount(adc_file, state_file)
    _unmount(MOUNT_ROOT)
    _terminate_owned_process(state["pid"], state["process_start_time_ticks"])
    if _mount_entries(_read_mountinfo(), MOUNT_ROOT):
        raise FallbackError("unmount_incomplete")
    _remove_runtime_directory(_runtime_directory(state_file))
    _remove_state_file(state_file)
    return {"active": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    for name in ("start", "status", "stop"):
        operation = operations.add_parser(name)
        operation.add_argument("--adc-file", type=Path, required=True)
        operation.add_argument("--state-file", type=Path, required=True)
        if name == "start":
            operation.add_argument("--client-id-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "start":
            result = start(args.adc_file, args.state_file, args.client_id_file)
            output = {
                "active": True,
                "devname": result["devname"],
                "resolved_resource_id": result["resolved_resource_id"],
            }
        elif args.operation == "status":
            output = status(args.adc_file, args.state_file)
        else:
            output = stop(args.adc_file, args.state_file)
    except FallbackError as exc:
        print(
            json.dumps(
                {"active": False, "error": exc.code},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"active": False, "error": "unexpected_error"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
