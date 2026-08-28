from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_probe() -> ModuleType:
    path = ROOT / "scripts" / "drive_identity_probe.py"
    specification = importlib.util.spec_from_file_location("drive_identity_probe", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self, *, num_retries: int):
        assert num_retries == 3
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def test_pagination_restarts_once_after_invalid_noninitial_token() -> None:
    probe = load_probe()
    calls: list[str | None] = []

    class BadToken(Exception):
        resp = SimpleNamespace(status=400)

    def request_for_page(token: str | None) -> Request:
        calls.append(token)
        if calls == [None]:
            return Request({"files": [{"id": "stale"}], "nextPageToken": "expired"})
        if calls == [None, "expired"]:
            return Request(BadToken())
        return Request({"files": [{"id": "fresh"}]})

    values = probe._fully_paginate(
        request_for_page,
        result_key="files",
        reject_incomplete_search=True,
    )
    assert calls == [None, "expired", None]
    assert values == [{"id": "fresh"}]


def test_pagination_rejects_incomplete_search_and_malformed_pages() -> None:
    probe = load_probe()
    with pytest.raises(probe.ProbeError, match="incompleteSearch"):
        probe._fully_paginate(
            lambda _: Request({"files": [], "incompleteSearch": True}),
            result_key="files",
            reject_incomplete_search=True,
        )
    with pytest.raises(probe.ProbeError, match="malformed"):
        probe._fully_paginate(
            lambda _: Request({"files": ["not-an-object"]}),
            result_key="files",
            reject_incomplete_search=False,
        )


def test_drive_and_folder_identity_are_exact_and_not_shortcuts() -> None:
    probe = load_probe()
    drive = {
        "id": "shared-drive-id",
        "name": "Data",
        "hidden": False,
        "capabilities": {"canListChildren": True},
    }
    assert probe._require_unique_drive([drive]) is drive
    with pytest.raises(probe.ProbeError, match="exactly one"):
        probe._require_unique_drive([drive, dict(drive)])

    folder = {
        "id": "lake-folder-id",
        "name": "graph-memory-data-lake",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": ["shared-drive-id"],
        "driveId": "shared-drive-id",
        "trashed": False,
        "version": "7",
        "capabilities": {"canListChildren": True},
    }
    assert probe._require_unique_folder([folder], "shared-drive-id") is folder
    shortcut = dict(folder, shortcutDetails={"targetId": "other"})
    with pytest.raises(probe.ProbeError, match="shortcut"):
        probe._require_unique_folder([shortcut], "shared-drive-id")
    wrong_parent = dict(folder, parents=["nested-parent"])
    with pytest.raises(probe.ProbeError, match="parents"):
        probe._require_unique_folder([wrong_parent], "shared-drive-id")


def test_only_proven_granted_readonly_drive_scope_is_accepted() -> None:
    probe = load_probe()
    credentials = SimpleNamespace(granted_scopes=[probe.DRIVE_READONLY_SCOPE])
    assert probe._credential_scopes(credentials) == {probe.DRIVE_READONLY_SCOPE}
    token_canary = "CANARY-current-access-token"
    assert probe._credential_scopes(
        SimpleNamespace(granted_scopes=None, token=token_canary),
        tokeninfo_fetcher=lambda token: (
            {probe.DRIVE_READONLY_SCOPE} if token == token_canary else set()
        ),
    ) == {probe.DRIVE_READONLY_SCOPE}
    with pytest.raises(probe.ProbeError, match="current access token") as raised:
        probe._credential_scopes(SimpleNamespace(granted_scopes=None, token=None))
    assert token_canary not in str(raised.value)
    with pytest.raises(probe.ProbeError, match="other than drive.readonly"):
        probe.probe(
            object(),
            principal_scopes={probe.DRIVE_READONLY_SCOPE, probe.DRIVE_FULL_SCOPE},
        )


def test_token_info_uses_bounded_post_and_retains_only_scope_set() -> None:
    probe = load_probe()
    token_canary = "CANARY-current-access-token"
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            captured["read_size"] = size
            return json.dumps(
                {
                    "scope": f"openid {probe.DRIVE_READONLY_SCOPE}",
                    "email": "must-not-be-retained@example.invalid",
                    "sub": "must-not-be-retained",
                    "client_id": "must-not-be-retained",
                }
            ).encode("utf-8")

    def opener(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    scopes = probe._token_info_scopes(token_canary, opener=opener)

    request = captured["request"]
    assert request.full_url == probe.TOKEN_INFO_URL
    assert request.get_method() == "POST"
    assert request.data == b"access_token=CANARY-current-access-token"
    assert captured["timeout"] == probe.TOKEN_INFO_TIMEOUT_SEC
    assert captured["read_size"] == probe.MAX_TOKEN_INFO_BYTES + 1
    assert scopes == {"openid", probe.DRIVE_READONLY_SCOPE}


def test_token_info_failures_are_sanitized_and_bounded() -> None:
    probe = load_probe()
    token_canary = "CANARY-current-access-token"

    def failed_opener(*_args, **_kwargs):
        raise OSError("CANARY-transport-detail")

    with pytest.raises(probe.ProbeError, match="token-info request failed") as raised:
        probe._token_info_scopes(token_canary, opener=failed_opener)
    assert token_canary not in str(raised.value)
    assert "CANARY-transport-detail" not in str(raised.value)

    class Oversized:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b"x" * (probe.MAX_TOKEN_INFO_BYTES + 1)

    with pytest.raises(probe.ProbeError, match="too large"):
        probe._token_info_scopes(
            token_canary, opener=lambda *_args, **_kwargs: Oversized()
        )


def test_fallback_binding_requires_same_adc_digest_and_drive_id(tmp_path) -> None:
    probe = load_probe()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    adc = private / "adc.json"
    adc.write_text('{"type":"authorized_user"}', encoding="utf-8")
    adc.chmod(0o600)
    state = private / "fallback.json"
    binding = {
        "pid": 1,
        "process_start_time_ticks": 2,
        "executable_sha256": probe.FALLBACK_RCLONE_SHA256,
        "adc_sha256": hashlib.sha256(adc.read_bytes()).hexdigest(),
        "devname": probe.FALLBACK_DEVNAME,
        "resolved_resource_id": "drive-id",
    }
    state.write_text(json.dumps(binding), encoding="utf-8")
    state.chmod(0o600)

    loaded = probe._load_fallback_binding(adc, state)
    probe._require_fallback_result_binding({"provider_resource_id": "drive-id"}, loaded)
    with pytest.raises(probe.ProbeError, match="resource ID mismatch"):
        probe._require_fallback_result_binding(
            {"provider_resource_id": "other-drive"}, loaded
        )

    adc.write_text('{"type":"authorized_user","changed":true}', encoding="utf-8")
    with pytest.raises(probe.ProbeError, match="ADC digest mismatch"):
        probe._load_fallback_binding(adc, state)


def test_fallback_runtime_validation_is_required_and_sanitized(tmp_path) -> None:
    probe = load_probe()
    adc = tmp_path / "adc.json"
    state = tmp_path / "state.json"
    binding = {"resolved_resource_id": "drive-id"}
    calls = []

    probe._validate_fallback_runtime(
        adc,
        state,
        binding,
        validator=lambda adc_path, state_path: (
            calls.append((adc_path, state_path)) or dict(binding)
        ),
    )
    assert calls == [(adc, state)]

    canary = "CANARY-validator-detail"
    with pytest.raises(probe.ProbeError, match="validation failed") as raised:
        probe._validate_fallback_runtime(
            adc,
            state,
            binding,
            validator=lambda *_args: (_ for _ in ()).throw(RuntimeError(canary)),
        )
    assert canary not in str(raised.value)

    with pytest.raises(probe.ProbeError, match="state changed"):
        probe._validate_fallback_runtime(
            adc,
            state,
            binding,
            validator=lambda *_args: {"resolved_resource_id": "other"},
        )


def test_probe_source_has_no_drive_write_or_content_read_surface() -> None:
    source = (ROOT / "scripts" / "drive_identity_probe.py").read_text(encoding="utf-8")
    for forbidden in (
        "files().create",
        "files().update",
        "files().delete",
        "permissions().create",
        "drives().create",
        "drives().update",
        "drives().delete",
        "MediaFileUpload",
        'alt="media"',
        "user(emailAddress)",
    ):
        assert forbidden not in source


def test_probe_help_does_not_require_optional_google_dependencies(capsys) -> None:
    probe = load_probe()

    with pytest.raises(SystemExit) as raised:
        probe.main(["--help"])

    assert raised.value.code == 0
    assert "--fallback-state-file" in capsys.readouterr().out
