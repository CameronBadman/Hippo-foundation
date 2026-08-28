from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest

from hippocampus_foundation.phase0.authority_v4_2 import VerifiedOAuthAuthority
from hippocampus_foundation.phase0.canonical import canonical_sha256, sha256_bytes
from hippocampus_foundation.phase0.drive_access_v4_2 import (
    DRIVE_READONLY_SCOPE,
    _token_info,
    observe_drive_access_v4_2,
)
from hippocampus_foundation.phase0.errors import IntegrityError, ValidationError


class Request:
    def __init__(self, value: Any):
        self.value = value

    def execute(self, *, num_retries: int) -> Any:
        assert num_retries == 3
        return copy.deepcopy(self.value)


class HttpResponse(io.BytesIO):
    def __enter__(self) -> HttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class About:
    def __init__(self, email: str):
        self.email = email

    def get(self, *, fields: str) -> Request:
        assert fields == "user(permissionId,emailAddress)"
        return Request(
            {
                "user": {
                    "permissionId": "principal-permission-id",
                    "emailAddress": self.email,
                }
            }
        )


class Drives:
    def get(self, **kwargs: Any) -> Request:
        assert kwargs["driveId"] == "shared-drive-id"
        return Request(
            {
                "id": "shared-drive-id",
                "name": "Data",
                "hidden": False,
                "capabilities": {"canListChildren": True},
            }
        )


class Files:
    def __init__(self, marker: bytes):
        self.marker = marker

    def get(self, **kwargs: Any) -> Request:
        file_id = kwargs["fileId"]
        if file_id == "root-folder-id":
            return Request(
                {
                    "id": "root-folder-id",
                    "name": "graph-memory-data-lake",
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": ["shared-drive-id"],
                    "driveId": "shared-drive-id",
                    "trashed": False,
                    "version": "1",
                    "capabilities": {"canListChildren": True},
                    "shortcutDetails": None,
                }
            )
        assert file_id == "marker-file-id"
        return Request(
            {
                "id": "marker-file-id",
                "name": ".entor-drive-identity-v1.json",
                "mimeType": "application/json",
                "parents": ["root-folder-id"],
                "driveId": "shared-drive-id",
                "trashed": False,
                "version": "2",
                "size": str(len(self.marker)),
                "md5Checksum": hashlib.md5(
                    self.marker, usedforsecurity=False
                ).hexdigest(),
            }
        )

    def get_media(self, **kwargs: Any) -> Request:
        assert kwargs == {"fileId": "marker-file-id", "supportsAllDrives": True}
        return Request(self.marker)


class Service:
    def __init__(self, marker: bytes, email: str = "reader@entor.net"):
        self._about = About(email)
        self._drives = Drives()
        self._files = Files(marker)

    def about(self) -> About:
        return self._about

    def drives(self) -> Drives:
        return self._drives

    def files(self) -> Files:
        return self._files


def _marker() -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "record_kind": "entor_drive_identity_marker",
            "marker_id": "12532a96-1f83-4e58-934c-735e335e96f6",
            "provider_resource_id": "shared-drive-id",
            "root_resource_id": "root-folder-id",
            "contains_evaluation_content": False,
            "training_authorized": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _authority(marker: bytes) -> VerifiedOAuthAuthority:
    receipt = {
        "oauth_config_sha256": "sha256:" + "a" * 64,
        "oauth_client_id_sha256": sha256_bytes(
            b"123456789012-test.apps.googleusercontent.com"
        ),
        "cloud_project_number": "123456789012",
        "workspace_domain": "entor.net",
        "provider_resource_id": "shared-drive-id",
        "root_resource_id": "root-folder-id",
        "marker_file_id": "marker-file-id",
        "marker_sha256": sha256_bytes(marker),
    }
    return VerifiedOAuthAuthority(
        payload={},
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        signature_sha256="sha256:" + "b" * 64,
        public_key_sha256="sha256:" + "c" * 64,
        signing_key_fingerprint="A" * 40,
    )


def _prepare_root(
    tmp_path: Path, marker: bytes, monkeypatch: pytest.MonkeyPatch
) -> Path:
    mount_root = tmp_path / "drive"
    root = mount_root / "Shareddrives" / "Data" / "graph-memory-data-lake"
    root.mkdir(parents=True)
    (root / ".entor-drive-identity-v1.json").write_bytes(marker)
    from hippocampus_foundation.phase0 import drive_access_v4_2

    monkeypatch.setattr(drive_access_v4_2, "DRIVE_MOUNT_ROOT", mount_root)
    monkeypatch.setattr(drive_access_v4_2, "EXPECTED_ROOT", root)
    return root


def _mountinfo(root: Path) -> str:
    mount_root = root.parents[2]
    return f"36 25 0:35 / {mount_root} rw,nosuid - fuse.drivefs drive rw\n"


def _credential(authority: VerifiedOAuthAuthority) -> dict:
    return {
        "better_colab_scope": DRIVE_READONLY_SCOPE,
        "client_id": "123456789012-test.apps.googleusercontent.com",
        "better_colab_oauth_config_sha256": authority.receipt["oauth_config_sha256"],
        "better_colab_provider_mode": "development",
    }


def test_drive_access_proves_api_mount_marker_without_leaking_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    authority = _authority(marker)
    root = _prepare_root(tmp_path, marker, monkeypatch)
    proof = observe_drive_access_v4_2(
        service=Service(marker),
        credential_metadata=_credential(authority),
        principal_scopes={DRIVE_READONLY_SCOPE},
        token_authorized_party="123456789012-test.apps.googleusercontent.com",
        authority=authority,
        observed_at="2026-08-28T00:00:00Z",
        root=root,
        mountinfo_text=_mountinfo(root),
    )
    assert proof["same_resource_mechanically_proven"] is True
    assert proof["checks"]["root_descriptor_bound"] is True
    rendered = json.dumps(proof)
    assert "reader@entor.net" not in rendered
    assert "principal-permission-id" not in rendered


def test_drive_access_rejects_external_account_or_broad_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    authority = _authority(marker)
    root = _prepare_root(tmp_path, marker, monkeypatch)
    with pytest.raises(ValidationError, match="outside"):
        observe_drive_access_v4_2(
            service=Service(marker, email="reader@example.com"),
            credential_metadata=_credential(authority),
            principal_scopes={DRIVE_READONLY_SCOPE},
            token_authorized_party="123456789012-test.apps.googleusercontent.com",
            authority=authority,
            observed_at="2026-08-28T00:00:00Z",
            root=root,
            mountinfo_text=_mountinfo(root),
        )

    with pytest.raises(ValidationError, match="authorized party"):
        observe_drive_access_v4_2(
            service=Service(marker),
            credential_metadata=_credential(authority),
            principal_scopes={DRIVE_READONLY_SCOPE},
            token_authorized_party="another-client.apps.googleusercontent.com",
            authority=authority,
            observed_at="2026-08-28T00:00:00Z",
            root=root,
            mountinfo_text=_mountinfo(root),
        )
    with pytest.raises(ValidationError, match="exactly"):
        observe_drive_access_v4_2(
            service=Service(marker),
            credential_metadata=_credential(authority),
            principal_scopes={
                DRIVE_READONLY_SCOPE,
                "https://www.googleapis.com/auth/drive",
            },
            token_authorized_party="123456789012-test.apps.googleusercontent.com",
            authority=authority,
            observed_at="2026-08-28T00:00:00Z",
            root=root,
            mountinfo_text=_mountinfo(root),
        )


def test_drive_access_rejects_mount_marker_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    authority = _authority(marker)
    root = _prepare_root(tmp_path, marker, monkeypatch)
    (root / ".entor-drive-identity-v1.json").write_bytes(marker + b"\n")
    with pytest.raises((IntegrityError, ValidationError), match="marker"):
        observe_drive_access_v4_2(
            service=Service(marker),
            credential_metadata=_credential(authority),
            principal_scopes={DRIVE_READONLY_SCOPE},
            token_authorized_party="123456789012-test.apps.googleusercontent.com",
            authority=authority,
            observed_at="2026-08-28T00:00:00Z",
            root=root,
            mountinfo_text=_mountinfo(root),
        )


def test_drive_access_rejects_unbound_root_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker()
    authority = _authority(marker)
    root = _prepare_root(tmp_path, marker, monkeypatch)
    other = tmp_path / "other"
    other.mkdir()
    descriptor = os.open(other, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(IntegrityError, match="descriptor"):
            observe_drive_access_v4_2(
                service=Service(marker),
                credential_metadata=_credential(authority),
                principal_scopes={DRIVE_READONLY_SCOPE},
                token_authorized_party="123456789012-test.apps.googleusercontent.com",
                authority=authority,
                observed_at="2026-08-28T00:00:00Z",
                root=root,
                root_fd=descriptor,
                mountinfo_text=_mountinfo(root),
            )
    finally:
        os.close(descriptor)


def test_drive_access_rejects_ambiguous_marker_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = _marker().replace(
        b'"training_authorized":false',
        b'"training_authorized":false,"training_authorized":false',
    )
    authority = _authority(marker)
    root = _prepare_root(tmp_path, marker, monkeypatch)
    with pytest.raises(ValidationError, match="strict JSON"):
        observe_drive_access_v4_2(
            service=Service(marker),
            credential_metadata=_credential(authority),
            principal_scopes={DRIVE_READONLY_SCOPE},
            token_authorized_party="123456789012-test.apps.googleusercontent.com",
            authority=authority,
            observed_at="2026-08-28T00:00:00Z",
            root=root,
            mountinfo_text=_mountinfo(root),
        )


def test_token_info_uses_authorized_party_not_resource_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {
            "azp": "approved-client.apps.googleusercontent.com",
            "aud": "different-resource-client.apps.googleusercontent.com",
            "scope": DRIVE_READONLY_SCOPE,
        }
    ).encode()
    monkeypatch.setattr(
        "hippocampus_foundation.phase0.drive_access_v4_2.urllib.request.urlopen",
        lambda *_args, **_kwargs: HttpResponse(payload),
    )
    info = _token_info("do-not-log-this-token")
    assert info.authorized_party == "approved-client.apps.googleusercontent.com"
    assert info.scopes == frozenset({DRIVE_READONLY_SCOPE})
