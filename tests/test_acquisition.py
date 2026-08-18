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

    def __enter__(self) -> "FakeResponse":
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
    monkeypatch.setattr(acquisition, "remote_metadata", lambda _url: metadata(url, len(payload)))
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload, status=200, url=url),
    )
    result = acquisition.download_resumable(
        url=url,
        destination=destination,
        expected_bytes=len(payload),
        expected_checksums={"sha1": hashlib.sha1(payload, usedforsecurity=False).hexdigest()},
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
    monkeypatch.setattr(acquisition, "remote_metadata", lambda _url: metadata(url, len(payload)))

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
    monkeypatch.setattr(acquisition, "remote_metadata", lambda _url: metadata(url, len(payload)))
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
