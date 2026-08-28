from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_fallback() -> ModuleType:
    path = ROOT / "scripts" / "drive_mount_fallback.py"
    specification = importlib.util.spec_from_file_location("drive_mount_fallback", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self, *, num_retries: int):
        assert num_retries == 3
        return self.value


class Drives:
    def __init__(self, listed, confirmed=None):
        self.listed = listed
        self.confirmed = confirmed
        self.list_calls = []
        self.get_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return Request({"drives": self.listed})

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return Request(self.confirmed or self.listed[0])


class Service:
    def __init__(self, drives):
        self._drives = drives

    def drives(self):
        return self._drives


def _drive(identifier="drive-id"):
    return {
        "id": identifier,
        "name": "Data",
        "hidden": False,
        "createdTime": "2026-01-01T00:00:00Z",
        "capabilities": {"canListChildren": True},
    }


def test_pins_exact_rclone_release_hashes_and_platform() -> None:
    fallback = load_fallback()

    assert fallback.RCLONE_VERSION == "1.75.0"
    assert fallback.RCLONE_ARCHIVE_SHA256 == (
        "aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa"
    )
    assert fallback.RCLONE_BINARY_SHA256 == (
        "f3f9aff817f9766029e50adf9a7963c169e475b8f10c7927823568a0d9443db7"
    )
    assert fallback.RCLONE_LICENCE_URL == (
        "https://raw.githubusercontent.com/rclone/rclone/v1.75.0/COPYING"
    )
    assert fallback.RCLONE_LICENCE_SHA256 == (
        "8cd2e9e750b90a04b7d82dbbca3930c696ae0309d7c10464f90a44f45754cd04"
    )
    fallback._require_supported_platform(system="Linux", machine="x86_64")
    with pytest.raises(fallback.FallbackError, match="unsupported_platform"):
        fallback._require_supported_platform(system="Darwin", machine="arm64")


def test_archive_and_binary_checksums_are_enforced_and_copying_is_preserved(
    monkeypatch, tmp_path
) -> None:
    fallback = load_fallback()
    source = tmp_path / "source.zip"
    binary_bytes = b"synthetic-rclone"
    with zipfile.ZipFile(source, "w") as archive:
        prefix = "rclone-v1.75.0-linux-amd64/"
        archive.writestr(prefix + "rclone", binary_bytes)
    licence_bytes = b"MIT licence text\n"
    monkeypatch.setattr(
        fallback,
        "RCLONE_ARCHIVE_SHA256",
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        fallback,
        "RCLONE_BINARY_SHA256",
        hashlib.sha256(binary_bytes).hexdigest(),
    )
    monkeypatch.setattr(
        fallback,
        "RCLONE_LICENCE_SHA256",
        hashlib.sha256(licence_bytes).hexdigest(),
    )

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o700)

    def copy_archive(_url, destination):
        shutil.copyfile(source, destination)

    def copy_licence(_url, destination):
        destination.write_bytes(licence_bytes)

    binary = fallback._install_rclone(
        runtime_dir,
        archive_downloader=copy_archive,
        licence_downloader=copy_licence,
    )

    assert binary.read_bytes() == binary_bytes
    assert (runtime_dir / "COPYING").read_text(encoding="utf-8") == (
        "MIT licence text\n"
    )
    assert binary.stat().st_mode & 0o777 == 0o500
    assert (runtime_dir / "COPYING").stat().st_mode & 0o777 == 0o400

    bad_runtime = tmp_path / "bad-runtime"
    bad_runtime.mkdir(mode=0o700)

    def corrupt_archive(_url, destination):
        destination.write_bytes(b"corrupt")

    with pytest.raises(fallback.FallbackError, match="archive_checksum_mismatch"):
        fallback._install_rclone(
            bad_runtime,
            archive_downloader=corrupt_archive,
            licence_downloader=copy_licence,
        )

    wrong_licence_runtime = tmp_path / "wrong-licence-runtime"
    wrong_licence_runtime.mkdir(mode=0o700)

    def corrupt_licence(_url, destination):
        destination.write_bytes(b"not the pinned licence")

    with pytest.raises(fallback.FallbackError, match="licence_checksum_mismatch"):
        fallback._install_rclone(
            wrong_licence_runtime,
            archive_downloader=copy_archive,
            licence_downloader=corrupt_licence,
        )


def test_scope_gate_accepts_only_exact_drive_readonly() -> None:
    fallback = load_fallback()
    fallback._require_readonly_scope({fallback.DRIVE_READONLY_SCOPE, "openid"})
    with pytest.raises(fallback.FallbackError, match="readonly_scope_missing"):
        fallback._require_readonly_scope({"openid"})
    with pytest.raises(fallback.FallbackError, match="broader_drive_scope"):
        fallback._require_readonly_scope(
            {fallback.DRIVE_READONLY_SCOPE, fallback.DRIVE_FULL_SCOPE}
        )


def test_desktop_oauth_gate_requires_matching_authorized_user_adc(tmp_path) -> None:
    fallback = load_fallback()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    adc = private / "adc.json"
    client = private / "client.json"
    adc.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "desktop-id",
                "client_secret": "desktop-secret",
                "refresh_token": "refresh-token",
            }
        ),
        encoding="utf-8",
    )
    client.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "desktop-id",
                    "client_secret": "desktop-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    adc.chmod(0o600)
    client.chmod(0o600)

    fallback._validate_oauth_binding(adc, client)

    client.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "other-id",
                    "client_secret": "desktop-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(fallback.FallbackError, match="oauth_binding_mismatch"):
        fallback._validate_oauth_binding(adc, client)

    client.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "desktop-id",
                    "client_secret": "desktop-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        fallback.FallbackError, match="desktop_oauth_prerequisite_missing"
    ):
        fallback._validate_oauth_binding(adc, client)


@pytest.mark.parametrize("listed", [[], [_drive("one"), _drive("two")]])
def test_drive_api_resolution_requires_exactly_one_matching_drive(listed) -> None:
    fallback = load_fallback()

    with pytest.raises(fallback.FallbackError, match="drive_match_count"):
        fallback._resolve_shared_drive_id(Service(Drives(listed)))


def test_drive_api_resolution_list_get_confirms_resource_id() -> None:
    fallback = load_fallback()
    drives = Drives([_drive()])

    assert fallback._resolve_shared_drive_id(Service(drives)) == "drive-id"
    assert drives.list_calls == [
        {
            "q": "name = 'Data'",
            "pageSize": 100,
            "pageToken": None,
            "useDomainAdminAccess": False,
            "fields": (
                "nextPageToken,drives(id,name,hidden,createdTime,"
                "capabilities(canListChildren))"
            ),
        }
    ]
    assert drives.get_calls[0]["driveId"] == "drive-id"


def test_rclone_environment_is_memory_only_and_bound_to_one_adc(tmp_path) -> None:
    fallback = load_fallback()
    adc = tmp_path / "adc.json"
    inherited = {
        "PATH": "/usr/bin",
        "LD_PRELOAD": "/unsafe/inject.so",
        "UNRELATED_SECRET": "must-not-be-forwarded",
        "RCLONE_CONFIG_EVIL_TYPE": "local",
        "RCLONE_CONFIG": "/unsafe/config",
        "GOOGLE_APPLICATION_CREDENTIALS": "/wrong/adc.json",
        "GOOGLE_CLOUD_PROJECT": "wrong-project",
    }

    environment = fallback._rclone_environment(
        adc, "drive-id", base_environment=inherited
    )

    assert environment["PATH"] == "/usr/bin"
    assert environment["GOOGLE_APPLICATION_CREDENTIALS"] == str(adc)
    assert environment["RCLONE_CONFIG"] == "/dev/null"
    assert environment["RCLONE_CONFIG_PHASE0_DATA_TYPE"] == "drive"
    assert environment["RCLONE_CONFIG_PHASE0_DATA_ENV_AUTH"] == "true"
    assert environment["RCLONE_CONFIG_PHASE0_DATA_SCOPE"] == "drive.readonly"
    assert environment["RCLONE_CONFIG_PHASE0_DATA_TEAM_DRIVE"] == "drive-id"
    assert environment["RCLONE_CONFIG_PHASE0_SHARED_TYPE"] == "combine"
    assert environment["RCLONE_CONFIG_PHASE0_SHARED_UPSTREAMS"] == ("Data=phase0_data:")
    assert environment["RCLONE_CONFIG_PHASE0_ROOT_TYPE"] == "combine"
    assert environment["RCLONE_CONFIG_PHASE0_ROOT_UPSTREAMS"] == (
        "Shareddrives=phase0_shared:"
    )
    assert "RCLONE_CONFIG_EVIL_TYPE" not in environment
    assert "LD_PRELOAD" not in environment
    assert "UNRELATED_SECRET" not in environment
    assert "GOOGLE_CLOUD_PROJECT" not in environment


def test_mount_arguments_are_exactly_read_only_owner_only_and_cacheless(
    tmp_path,
) -> None:
    fallback = load_fallback()
    binary = tmp_path / "rclone"
    mountpoint = tmp_path / "drive"

    command = fallback._mount_command(binary, mountpoint)

    assert command == [
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
        fallback.RCLONE_DEVNAME,
    ]
    assert "--allow-other" not in command


def test_private_path_checks_reject_group_readable_and_symlink_files(tmp_path) -> None:
    fallback = load_fallback()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    adc = private / "adc.json"
    adc.write_text("{}", encoding="utf-8")
    adc.chmod(0o640)
    with pytest.raises(fallback.FallbackError, match="unsafe_permissions"):
        fallback._require_private_file(adc, label="adc")

    adc.chmod(0o600)
    link = private / "adc-link.json"
    link.symlink_to(adc)
    with pytest.raises(fallback.FallbackError, match="unsafe_symlink"):
        fallback._require_private_file(link, label="adc")


def test_state_is_exact_mode_and_binds_adc_and_drive_id(tmp_path) -> None:
    fallback = load_fallback()
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    state_file = state_dir / "fallback.json"
    adc = state_dir / "adc.json"
    adc.write_text('{"type":"authorized_user"}', encoding="utf-8")
    adc.chmod(0o600)
    state = {
        "pid": 123,
        "process_start_time_ticks": 456,
        "executable_sha256": fallback.RCLONE_BINARY_SHA256,
        "adc_sha256": fallback._sha256_file(adc),
        "devname": fallback.RCLONE_DEVNAME,
        "resolved_resource_id": "drive-id",
    }

    fallback._write_state(state_file, state)

    assert state_dir.stat().st_mode & 0o777 == 0o700
    assert state_file.stat().st_mode & 0o777 == 0o600
    loaded = fallback._load_state(state_file)
    assert loaded == state
    fallback._require_state_binding(loaded, adc, "drive-id")
    with pytest.raises(fallback.FallbackError, match="resource_binding_mismatch"):
        fallback._require_state_binding(loaded, adc, "different-drive")


def test_status_validation_does_not_create_a_missing_state_directory(tmp_path) -> None:
    fallback = load_fallback()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    adc = private / "adc.json"
    adc.write_text("{}", encoding="utf-8")
    adc.chmod(0o600)
    missing_parent = tmp_path / "missing-state"

    with pytest.raises(fallback.FallbackError):
        fallback.validate_active_mount(
            adc,
            missing_parent / "state.json",
            drive_id_resolver=lambda _adc: "drive-id",
        )

    assert not missing_parent.exists()


def test_mount_validation_rejects_foreign_and_accepts_exact_readonly_mount(
    tmp_path,
) -> None:
    fallback = load_fallback()
    mountpoint = tmp_path / "drive"
    escaped = str(mountpoint).replace(" ", r"\040")
    exact = (
        f"42 31 0:99 / {escaped} ro,nosuid,nodev - "
        f"fuse.rclone {fallback.RCLONE_DEVNAME} rw,user_id=1000\n"
    )
    entry = fallback._require_exact_mount(exact, mountpoint)
    assert entry.file_system == "fuse.rclone"
    assert entry.source == fallback.RCLONE_DEVNAME

    foreign = exact.replace(fallback.RCLONE_DEVNAME, "foreign-device")
    with pytest.raises(fallback.FallbackError, match="foreign_mount"):
        fallback._require_exact_mount(foreign, mountpoint)


def test_process_validation_rejects_reused_pid(tmp_path) -> None:
    fallback = load_fallback()
    binary = tmp_path / "rclone"
    binary.write_bytes(b"binary")
    binary.chmod(0o500)
    adc = tmp_path / "adc.json"
    adc.write_text("{}", encoding="utf-8")
    adc.chmod(0o600)
    state = {
        "pid": 55,
        "process_start_time_ticks": 100,
        "executable_sha256": hashlib.sha256(b"binary").hexdigest(),
        "adc_sha256": fallback._sha256_file(adc),
        "devname": fallback.RCLONE_DEVNAME,
        "resolved_resource_id": "drive-id",
    }

    with pytest.raises(fallback.FallbackError, match="process_identity_mismatch"):
        fallback._require_process_identity(
            state,
            binary,
            adc,
            "drive-id",
            mountpoint=tmp_path / "mount",
            start_time_reader=lambda _pid: 101,
            executable_hash_reader=lambda _pid: state["executable_sha256"],
            command_reader=lambda _pid: fallback._mount_command(
                binary, tmp_path / "mount"
            ),
            environment_reader=lambda _pid: fallback._rclone_environment(
                adc, "drive-id", base_environment={}
            ),
        )


def test_process_validation_requires_exact_arguments_and_adc_environment(
    tmp_path,
) -> None:
    fallback = load_fallback()
    binary = tmp_path / "rclone"
    binary.write_bytes(b"binary")
    binary.chmod(0o500)
    adc = tmp_path / "adc.json"
    adc.write_text("{}", encoding="utf-8")
    adc.chmod(0o600)
    mountpoint = tmp_path / "mount"
    executable_hash = hashlib.sha256(b"binary").hexdigest()
    state = {
        "pid": 55,
        "process_start_time_ticks": 100,
        "executable_sha256": executable_hash,
        "adc_sha256": fallback._sha256_file(adc),
        "devname": fallback.RCLONE_DEVNAME,
        "resolved_resource_id": "drive-id",
    }
    hooks = {
        "mountpoint": mountpoint,
        "start_time_reader": lambda _pid: 100,
        "executable_hash_reader": lambda _pid: executable_hash,
        "environment_reader": lambda _pid: fallback._rclone_environment(
            adc, "drive-id", base_environment={}
        ),
    }

    fallback._require_process_identity(
        state,
        binary,
        adc,
        "drive-id",
        command_reader=lambda _pid: fallback._mount_command(binary, mountpoint),
        **hooks,
    )
    with pytest.raises(fallback.FallbackError, match="process_arguments_mismatch"):
        fallback._require_process_identity(
            state,
            binary,
            adc,
            "drive-id",
            command_reader=lambda _pid: [str(binary), "wrong"],
            **hooks,
        )
    with pytest.raises(fallback.FallbackError, match="process_environment_mismatch"):
        fallback._require_process_identity(
            state,
            binary,
            adc,
            "drive-id",
            command_reader=lambda _pid: fallback._mount_command(binary, mountpoint),
            environment_reader=lambda _pid: {
                **fallback._rclone_environment(adc, "drive-id", base_environment={}),
                "GOOGLE_APPLICATION_CREDENTIALS": "/wrong/adc.json",
            },
            **{
                key: value
                for key, value in hooks.items()
                if key != "environment_reader"
            },
        )


def test_stop_refuses_foreign_mount_without_cleanup(monkeypatch, tmp_path) -> None:
    fallback = load_fallback()
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    state_file = state_dir / "fallback.json"
    state_file.write_text("{}", encoding="utf-8")
    state_file.chmod(0o600)
    adc = state_dir / "adc.json"
    adc.write_text("{}", encoding="utf-8")
    adc.chmod(0o600)
    unmount = pytest.fail

    def reject(*_args, **_kwargs):
        raise fallback.FallbackError("foreign_mount")

    monkeypatch.setattr(fallback, "validate_active_mount", reject)
    monkeypatch.setattr(fallback, "_unmount", unmount)

    with pytest.raises(fallback.FallbackError, match="foreign_mount"):
        fallback.stop(adc, state_file)

    assert state_file.exists()


def test_failed_start_removes_only_its_state_and_runtime(monkeypatch, tmp_path) -> None:
    fallback = load_fallback()
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    state_file = state_dir / "fallback.json"
    adc = state_dir / "adc.json"
    adc.write_text("{}", encoding="utf-8")
    adc.chmod(0o600)
    client = state_dir / "client.json"
    client.write_text("{}", encoding="utf-8")
    client.chmod(0o600)
    mountpoint = tmp_path / "mount"
    mountpoint.mkdir()
    unrelated = state_dir / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(fallback, "MOUNT_ROOT", mountpoint)
    monkeypatch.setenv("HF_DRIVE_SAME_ACCOUNT_ATTESTED", "1")
    monkeypatch.setattr(
        fallback,
        "RCLONE_BINARY_SHA256",
        hashlib.sha256(b"synthetic").hexdigest(),
    )
    monkeypatch.setattr(fallback, "_validate_oauth_binding", lambda *_args: None)
    monkeypatch.setattr(
        fallback,
        "_load_drive_context",
        lambda _adc: (object(), "drive-id"),
    )
    monkeypatch.setattr(fallback, "_require_mountpoint_available", lambda *_: None)

    def install(runtime_dir, **_kwargs):
        binary = runtime_dir / "rclone"
        binary.write_bytes(b"synthetic")
        binary.chmod(0o500)
        (runtime_dir / "COPYING").write_text("MIT", encoding="utf-8")
        return binary

    class Process:
        pid = 123

    monkeypatch.setattr(fallback, "_install_rclone", install)
    monkeypatch.setattr(fallback, "_spawn_mount", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(fallback, "_process_start_time", lambda _pid: 456)
    monkeypatch.setattr(
        fallback,
        "_wait_for_active_mount",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            fallback.FallbackError("mount_start_failed")
        ),
    )
    monkeypatch.setattr(fallback, "_cleanup_failed_start", lambda *_args: None)

    with pytest.raises(fallback.FallbackError, match="mount_start_failed"):
        fallback.start(adc, state_file, client)

    assert not state_file.exists()
    assert not fallback._runtime_directory(state_file).exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_failed_start_terminates_spawned_child_before_state_exists() -> None:
    fallback = load_fallback()
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        fallback._cleanup_failed_start(process, None)
        process.wait(timeout=2)
        assert process.returncode is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_start_fails_closed_without_human_same_account_attestation(
    monkeypatch, tmp_path
) -> None:
    fallback = load_fallback()
    monkeypatch.delenv("HF_DRIVE_SAME_ACCOUNT_ATTESTED", raising=False)

    with pytest.raises(
        fallback.FallbackError, match="same_account_attestation_missing"
    ):
        fallback.start(
            tmp_path / "missing-adc.json",
            tmp_path / "state" / "fallback.json",
            tmp_path / "missing-client.json",
        )


def test_cli_failure_output_does_not_expose_unexpected_secret(
    monkeypatch, capsys, tmp_path
) -> None:
    fallback = load_fallback()
    canary = "CANARY-unexpected-secret"
    monkeypatch.setattr(
        fallback,
        "status",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(canary)),
    )

    result = fallback.main(
        [
            "status",
            "--adc-file",
            str(tmp_path / "adc.json"),
            "--state-file",
            str(tmp_path / "state.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert canary not in captured.out
    assert canary not in captured.err
    assert json.loads(captured.err) == {
        "active": False,
        "error": "unexpected_error",
    }


@pytest.mark.skipif(shutil.which("rclone") is None, reason="rclone is unavailable")
def test_local_nested_combine_exposes_required_topology(tmp_path) -> None:
    fallback = load_fallback()
    data_root = tmp_path / "data"
    lake = data_root / "graph-memory-data-lake"
    lake.mkdir(parents=True)
    environment = fallback._rclone_environment(
        tmp_path / "unused-adc.json", "unused-drive", base_environment=os.environ
    )
    environment["RCLONE_CONFIG_PHASE0_DATA_TYPE"] = "local"
    environment.pop("RCLONE_CONFIG_PHASE0_DATA_ENV_AUTH")
    environment.pop("RCLONE_CONFIG_PHASE0_DATA_SCOPE")
    environment.pop("RCLONE_CONFIG_PHASE0_DATA_TEAM_DRIVE")
    environment["RCLONE_CONFIG_PHASE0_SHARED_UPSTREAMS"] = (
        f"Data=phase0_data:{data_root}"
    )

    completed = subprocess.run(
        [
            shutil.which("rclone"),
            "lsf",
            "phase0_root:Shareddrives/Data",
            "--config",
            "/dev/null",
        ],
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )

    assert completed.stdout.splitlines() == ["graph-memory-data-lake/"]
