from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from hippocampus_foundation.phase0 import acquisition
from hippocampus_foundation.phase0.errors import IntegrityError


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        status: int,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(payload)
        self.status = status
        self.url = url
        self.headers = headers or {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def metadata(url: str, size: int) -> dict[str, object]:
    return {
        "status": 200,
        "content_length": size,
        "etag": None,
        "last_modified": None,
        "accept_ranges": "bytes",
        "final_url": url,
    }


def test_zero_byte_partial_is_resumed_without_exclusive_open_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"verified payload"
    url = "https://example.test/artifact"
    destination = tmp_path / "artifact"
    destination.with_name("artifact.partial").write_bytes(b"")
    monkeypatch.setattr(
        acquisition, "remote_metadata", lambda _url: metadata(url, len(payload))
    )
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload, status=200, url=url),
    )
    result = acquisition.download_resumable(
        url=url,
        destination=destination,
        expected_bytes=len(payload),
        expected_checksums={
            "sha1": hashlib.sha1(payload, usedforsecurity=False).hexdigest()
        },
        minimum_free_bytes=0,
    )
    assert destination.read_bytes() == payload
    assert result["bytes"] == len(payload)


def test_complete_partial_is_verified_and_promoted_without_another_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"already complete"
    url = "https://example.test/artifact"
    destination = tmp_path / "artifact"
    destination.with_name("artifact.partial").write_bytes(payload)
    monkeypatch.setattr(
        acquisition, "remote_metadata", lambda _url: metadata(url, len(payload))
    )

    def unexpected_get(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a complete partial must not be fetched again")

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", unexpected_get)
    acquisition.download_resumable(
        url=url,
        destination=destination,
        expected_bytes=len(payload),
        expected_checksums={"sha256": hashlib.sha256(payload).hexdigest()},
        minimum_free_bytes=0,
    )
    assert destination.read_bytes() == payload


def test_resume_requires_exact_content_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"abcdef"
    url = "https://example.test/artifact"
    destination = tmp_path / "artifact"
    destination.with_name("artifact.partial").write_bytes(payload[:2])
    monkeypatch.setattr(
        acquisition, "remote_metadata", lambda _url: metadata(url, len(payload))
    )
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            payload[2:], status=206, url=url, headers={"Content-Range": "bytes 3-5/6"}
        ),
    )
    with pytest.raises(IntegrityError, match="Content-Range mismatch"):
        acquisition.download_resumable(
            url=url,
            destination=destination,
            expected_bytes=len(payload),
            expected_checksums={"sha256": hashlib.sha256(payload).hexdigest()},
            minimum_free_bytes=0,
        )
    assert destination.with_name("artifact.partial").read_bytes() == payload[:2]


def test_acquisition_requires_secure_publisher_checksum(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="SHA-1 or SHA-256"):
        acquisition.download_resumable(
            url="https://example.test/artifact",
            destination=tmp_path / "artifact",
            expected_bytes=1,
            expected_checksums={"md5": "0" * 32},
            minimum_free_bytes=0,
        )


def test_rooted_acquisition_rechecks_identity_before_atomic_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"root-pinned payload"
    url = "https://example.test/rooted-artifact"
    monkeypatch.setattr(
        acquisition, "remote_metadata", lambda _url: metadata(url, len(payload))
    )
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload, status=200, url=url),
    )
    stages: list[str] = []

    def identity(stage: str, root_fd: int) -> dict[str, str]:
        assert root_fd >= 0
        stages.append(stage)
        return {"stage": stage}

    result = acquisition.download_resumable_at(
        url=url,
        root=tmp_path,
        filename="artifact.bin",
        expected_bytes=len(payload),
        expected_checksums={"sha256": hashlib.sha256(payload).hexdigest()},
        minimum_free_bytes=0,
        resume_authorization_sha256="sha256:" + ("a" * 64),
        identity_check=identity,
    )
    assert stages == ["before_download", "before_promote"]
    assert (tmp_path / "artifact.bin").read_bytes() == payload
    assert not (tmp_path / "artifact.bin.partial").exists()
    assert not (tmp_path / "artifact.bin.partial.authorization.json").exists()
    assert result["pre_identity"] == {"stage": "before_download"}


def test_rooted_acquisition_supports_registry_relative_subdirectories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"nested rooted payload"
    url = "https://example.test/nested-artifact"
    monkeypatch.setattr(
        acquisition, "remote_metadata", lambda _url: metadata(url, len(payload))
    )
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload, status=200, url=url),
    )
    result = acquisition.download_resumable_at(
        url=url,
        root=tmp_path,
        filename="wikidata/20260720/artifact.bin",
        expected_bytes=len(payload),
        expected_checksums={"sha256": hashlib.sha256(payload).hexdigest()},
        minimum_free_bytes=0,
        resume_authorization_sha256="sha256:" + ("a" * 64),
        identity_check=lambda stage, _root_fd: {"stage": stage},
    )
    assert result["destination_filename"] == "wikidata/20260720/artifact.bin"
    assert (tmp_path / "wikidata/20260720/artifact.bin").read_bytes() == payload


def test_rooted_acquisition_rejects_symlinked_parent_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "unsafe").symlink_to(outside, target_is_directory=True)

    def unexpected_network(_url: str) -> dict[str, object]:
        raise AssertionError("unsafe parent must be rejected before network access")

    monkeypatch.setattr(acquisition, "remote_metadata", unexpected_network)
    with pytest.raises(IntegrityError, match="unsafe"):
        acquisition.download_resumable_at(
            url="https://example.test/artifact",
            root=tmp_path,
            filename="unsafe/artifact.bin",
            expected_bytes=1,
            expected_checksums={"sha256": "0" * 64},
            minimum_free_bytes=0,
            resume_authorization_sha256="sha256:" + ("a" * 64),
            identity_check=lambda stage, _root_fd: {"stage": stage},
        )
    assert not (outside / "artifact.bin").exists()


def test_rooted_acquisition_keeps_partial_when_final_identity_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"must remain partial"
    url = "https://example.test/drift"
    monkeypatch.setattr(
        acquisition, "remote_metadata", lambda _url: metadata(url, len(payload))
    )
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload, status=200, url=url),
    )

    def identity(stage: str, _root_fd: int) -> dict[str, str]:
        if stage == "before_promote":
            raise IntegrityError("mount identity drift")
        return {"stage": stage}

    with pytest.raises(IntegrityError, match="drift"):
        acquisition.download_resumable_at(
            url=url,
            root=tmp_path,
            filename="artifact.bin",
            expected_bytes=len(payload),
            expected_checksums={"sha1": hashlib.sha1(payload).hexdigest()},
            minimum_free_bytes=0,
            resume_authorization_sha256="sha256:" + ("a" * 64),
            identity_check=identity,
        )
    assert not (tmp_path / "artifact.bin").exists()
    assert (tmp_path / "artifact.bin.partial").read_bytes() == payload
    assert (tmp_path / "artifact.bin.partial.authorization.json").is_file()


def test_rooted_acquisition_rejects_unbound_partial_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifact.bin.partial").write_bytes(b"old unauthorized bytes")

    def unexpected_network(_url: str) -> dict[str, object]:
        raise AssertionError("unbound partial must be rejected before network access")

    monkeypatch.setattr(acquisition, "remote_metadata", unexpected_network)
    with pytest.raises(IntegrityError, match="no signed-authorization binding"):
        acquisition.download_resumable_at(
            url="https://example.test/artifact",
            root=tmp_path,
            filename="artifact.bin",
            expected_bytes=24,
            expected_checksums={"sha256": "0" * 64},
            minimum_free_bytes=0,
            resume_authorization_sha256="sha256:" + ("a" * 64),
            identity_check=lambda stage, _root_fd: {"stage": stage},
        )


def test_rooted_acquisition_rejects_partial_from_another_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"previously authorized bytes"
    url = "https://example.test/artifact"
    checksum = hashlib.sha256(payload).hexdigest()
    (tmp_path / "artifact.bin.partial").write_bytes(payload)
    (tmp_path / "artifact.bin.partial.authorization.json").write_bytes(
        acquisition._resume_binding_bytes(
            authorization_sha256="sha256:" + ("a" * 64),
            url=url,
            filename="artifact.bin",
            expected_bytes=len(payload),
            expected_checksums={"sha256": checksum},
        )
    )

    def unexpected_network(_url: str) -> dict[str, object]:
        raise AssertionError("mismatched partial must fail before network access")

    monkeypatch.setattr(acquisition, "remote_metadata", unexpected_network)
    with pytest.raises(IntegrityError, match="another authorization"):
        acquisition.download_resumable_at(
            url=url,
            root=tmp_path,
            filename="artifact.bin",
            expected_bytes=len(payload),
            expected_checksums={"sha256": checksum},
            minimum_free_bytes=0,
            resume_authorization_sha256="sha256:" + ("b" * 64),
            identity_check=lambda stage, _root_fd: {"stage": stage},
        )


@pytest.mark.parametrize(
    "filename", ["../artifact", "/absolute", "a\\b", ".", "..", "a/../b"]
)
def test_rooted_acquisition_rejects_unsafe_relative_path(
    tmp_path: Path, filename: str
) -> None:
    with pytest.raises(IntegrityError, match="safe relative"):
        acquisition.download_resumable_at(
            url="https://example.test/artifact",
            root=tmp_path,
            filename=filename,
            expected_bytes=1,
            expected_checksums={"sha256": "0" * 64},
            minimum_free_bytes=0,
            resume_authorization_sha256="sha256:" + ("a" * 64),
            identity_check=lambda *_args: {},
        )
