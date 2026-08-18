from __future__ import annotations

from pathlib import Path
from typing import Any

from hippocampus_foundation.licensing import (
    VerifiedBundle,
    build_evidence_bundle,
    make_pending_assessment,
    verify_evidence_bundle,
)
from hippocampus_foundation.phase0.canonical import load_json
from hippocampus_foundation.phase1.contracts import (
    ENCODER_VERIFICATION_METHOD_V2,
    FROZEN_ENCODER_SPEC_SHA256,
)
from hippocampus_foundation.phase1.v2 import (
    evaluate_phase1_gate_v2,
    validate_schema_lock_v2,
)


ROOT = Path(__file__).resolve().parents[1]


def _pending_encoder_evidence(
    tmp_path: Path, spec: dict[str, Any]
) -> tuple[dict[str, Any], VerifiedBundle]:
    bundle = build_evidence_bundle(
        bundle_id="gte-modernbert-base-rights-v1-evidence",
        review_id=spec["licence_review_id"],
        subject_kind="encoder",
        subject_id=spec["encoder_id"],
        subject_binding_sha256=FROZEN_ENCODER_SPEC_SHA256,
        documents=[],
        findings=[
            {
                "finding_id": "upstream-provenance",
                "category": "missing_provenance",
                "blocking": True,
                "summary": "Upstream provenance remains unresolved.",
            }
        ],
        assembled_at="2026-08-17T09:38:00Z",
    )
    verified = verify_evidence_bundle(bundle, tmp_path)
    return make_pending_assessment(bundle), verified


def _evaluate(
    tmp_path: Path, spec: dict[str, Any], verification: dict[str, Any]
) -> dict[str, Any]:
    pending, verified = _pending_encoder_evidence(tmp_path, spec)
    return evaluate_phase1_gate_v2(
        evaluated_at="2026-08-17T10:00:00Z",
        phase0_gate=None,
        encoder_spec=spec,
        encoder_verification=verification,
        encoder_licence_assessment=pending,
        encoder_verified_bundle=verified,
        sample_manifest=None,
        graph_manifest=None,
        objective_manifest=None,
    )


def test_phase1_v2_distinguishes_encoder_identity_from_licensing(tmp_path: Path) -> None:
    spec = load_json(ROOT / "registries" / "encoder.gte-modernbert.v1.json")
    verification = load_json(ROOT / "audit" / "encoder-verification.v1.json")
    verification = {
        **verification,
        "schema_version": "2.0.0",
        "verification_method": ENCODER_VERIFICATION_METHOD_V2,
    }
    report = _evaluate(tmp_path, spec, verification)
    assert set(validate_schema_lock_v2()) == {
        "encoder-verification.schema.json",
        "gate.schema.json",
    }
    assert report["contracts_frozen"] is True
    assert report["encoder_identity_ready"] is True
    assert report["encoder_licensing_ready"] is False
    assert report["encoder_ready"] is False
    assert report["phase1_data_ready"] is False
    assert report["training_authorized"] is False


def test_phase1_v2_rejects_legacy_encoder_attestation(tmp_path: Path) -> None:
    spec = load_json(ROOT / "registries" / "encoder.gte-modernbert.v1.json")
    legacy = load_json(ROOT / "audit" / "encoder-verification.v1.json")
    report = _evaluate(tmp_path, spec, legacy)
    identity_blockers = [
        item
        for item in report["blockers"]
        if item.startswith("encoder_verification_invalid:")
    ]
    assert len(identity_blockers) == 1
    assert "verification_method" in identity_blockers[0]
    assert report["encoder_identity_ready"] is False
    assert report["encoder_ready"] is False
    assert not any(
        item.startswith("encoder_verification_v2:") for item in report["evidence"]
    )
