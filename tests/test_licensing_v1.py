from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hippocampus_foundation.licensing import (
    FORBIDDEN_USES,
    build_evidence_bundle,
    make_pending_assessment,
    validate_schema_lock_v1,
    verify_assessment,
    verify_evidence_bundle,
)
from hippocampus_foundation.phase0.canonical import canonical_sha256, sha256_bytes
from hippocampus_foundation.phase0.errors import IntegrityError, ValidationError


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def evidence_bundle(tmp_path: Path, *, findings: list[dict] | None = None):
    body = b"pinned licence evidence\n"
    snapshot = tmp_path / "terms.txt"
    snapshot.write_bytes(body)
    subject = {"source_id": "source-v1", "version": "1"}
    bundle = build_evidence_bundle(
        bundle_id="source-v1-evidence",
        review_id="source-v1-rights",
        subject_kind="source",
        subject_id="source-v1",
        subject_binding_sha256=canonical_sha256(subject),
        documents=[
            {
                "document_id": "terms-v1",
                "role": "legal_code",
                "source_kind": "https_response",
                "original_url": "https://example.invalid/licence.txt",
                "resolved_url": "https://example.invalid/licence.txt",
                "revision": "v1",
                "snapshot_path": snapshot.name,
                "media_type": "text/plain",
                "content_encoding": None,
                "byte_count": len(body),
                "sha256": sha256_bytes(body),
                "retrieved_at": "2026-08-17T00:00:00Z",
                "etag": None,
                "last_modified": None,
                "mutable": False,
            }
        ],
        findings=findings or [],
        assembled_at="2026-08-17T00:01:00Z",
    )
    return subject, bundle, verify_evidence_bundle(bundle, tmp_path)


def approved_assessment(bundle: dict, now: datetime) -> dict:
    assessment = make_pending_assessment(bundle)
    assessment.update(
        {
            "decision": "approved",
            "commercial_context": "allowed",
            "licence_identifiers": ["LicenseRef-reviewed"],
            "allowed_uses": [
                "acquire",
                "inventory",
                "quarantine",
                "transform",
                "embed",
                "commercial_service",
            ],
            "excluded_uses": sorted(FORBIDDEN_USES),
            "reviewer": "accountable-human",
            "reviewed_at": timestamp(now),
            "valid_until": timestamp(now + timedelta(days=20)),
            "notes": "Human-reviewed fixture.",
        }
    )
    return assessment


def test_licensing_schema_lock_and_exact_document_bytes(tmp_path: Path) -> None:
    assert set(validate_schema_lock_v1()) == {
        "evidence-bundle.schema.json",
        "licence-assessment.schema.json",
    }
    _, bundle, verified = evidence_bundle(tmp_path)
    assert verified.sha256 == canonical_sha256(bundle)

    (tmp_path / "terms.txt").write_bytes(b"changed\n")
    with pytest.raises(IntegrityError, match="byte count mismatch|digest mismatch"):
        verify_evidence_bundle(bundle, tmp_path)


def test_evidence_bundle_rejects_symlink(tmp_path: Path) -> None:
    _, bundle, _ = evidence_bundle(tmp_path)
    original = tmp_path / "terms.txt"
    target = tmp_path / "target.txt"
    target.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(target.name)
    with pytest.raises(IntegrityError, match="symlink"):
        verify_evidence_bundle(bundle, tmp_path)


def test_pending_assessment_never_authorizes_use(tmp_path: Path) -> None:
    subject, bundle, verified = evidence_bundle(tmp_path)
    assessment = make_pending_assessment(bundle)
    assert assessment["training_authorized"] is False
    assert set(FORBIDDEN_USES) <= set(assessment["excluded_uses"])
    with pytest.raises(ValidationError, match="not approved"):
        verify_assessment(
            assessment,
            verified,
            subject_kind="source",
            subject_id="source-v1",
            subject_binding_sha256=canonical_sha256(subject),
            required_uses={"acquire"},
            evaluated_at="2026-08-17T01:00:00Z",
        )


def test_approved_assessment_requires_scope_freshness_and_resolved_findings(
    tmp_path: Path,
) -> None:
    finding = {
        "finding_id": "third-party-rights",
        "category": "third_party_rights",
        "blocking": True,
        "summary": "Third-party rights require evidence-backed resolution.",
    }
    subject, bundle, verified = evidence_bundle(tmp_path, findings=[finding])
    now = datetime(2026, 8, 17, 1, tzinfo=UTC)
    assessment = approved_assessment(bundle, now)
    with pytest.raises(ValidationError, match="remain unresolved"):
        verify_assessment(
            assessment,
            verified,
            subject_kind="source",
            subject_id="source-v1",
            subject_binding_sha256=canonical_sha256(subject),
            required_uses={"acquire", "commercial_service"},
            evaluated_at=timestamp(now + timedelta(days=1)),
        )

    assessment["finding_dispositions"] = [
        {
            "finding_id": "third-party-rights",
            "disposition": "resolved",
            "rationale_document_id": "terms-v1",
        }
    ]
    verify_assessment(
        assessment,
        verified,
        subject_kind="source",
        subject_id="source-v1",
        subject_binding_sha256=canonical_sha256(subject),
        required_uses={"acquire", "commercial_service"},
        evaluated_at=timestamp(now + timedelta(days=1)),
    )

    assessment["allowed_uses"].remove("commercial_service")
    with pytest.raises(ValidationError, match="omits required uses"):
        verify_assessment(
            assessment,
            verified,
            subject_kind="source",
            subject_id="source-v1",
            subject_binding_sha256=canonical_sha256(subject),
            required_uses={"acquire", "commercial_service"},
            evaluated_at=timestamp(now + timedelta(days=1)),
        )


def test_training_cannot_be_smuggled_into_approval(tmp_path: Path) -> None:
    subject, bundle, verified = evidence_bundle(tmp_path)
    now = datetime(2026, 8, 17, 1, tzinfo=UTC)
    assessment = approved_assessment(bundle, now)
    assessment["allowed_uses"].append("train")
    with pytest.raises(
        ValidationError, match="allows and excludes|explicitly excluded"
    ):
        verify_assessment(
            assessment,
            verified,
            subject_kind="source",
            subject_id="source-v1",
            subject_binding_sha256=canonical_sha256(subject),
            required_uses={"acquire"},
            evaluated_at=timestamp(now + timedelta(days=1)),
        )


def test_bundle_and_review_timestamps_follow_evidence_lineage(tmp_path: Path) -> None:
    subject, bundle, verified = evidence_bundle(tmp_path)
    bundle["documents"][0]["retrieved_at"] = "2026-08-17T00:02:00Z"
    with pytest.raises(ValidationError, match="retrieved after bundle assembly"):
        verify_evidence_bundle(bundle, tmp_path)

    _, clean_bundle, clean_verified = evidence_bundle(tmp_path)
    reviewed_at = datetime(2026, 8, 17, tzinfo=UTC)
    assessment = approved_assessment(clean_bundle, reviewed_at)
    with pytest.raises(ValidationError, match="predates its evidence bundle"):
        verify_assessment(
            assessment,
            clean_verified,
            subject_kind="source",
            subject_id="source-v1",
            subject_binding_sha256=canonical_sha256(subject),
            required_uses={"acquire"},
            evaluated_at="2026-08-17T02:00:00Z",
        )
