from __future__ import annotations

from pathlib import Path

from hippocampus_foundation.licensing import (
    build_evidence_bundle,
    make_pending_assessment,
    verify_evidence_bundle,
)
from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.v3 import (
    evaluate_gate_v3,
    validate_schema_lock_v3,
)

ROOT = Path(__file__).resolve().parents[1]


def test_phase0_v3_accounts_for_every_subject_without_inventing_approval(
    tmp_path: Path,
) -> None:
    sources = load_json(ROOT / "registries" / "sources.v2.json")
    evaluations = load_json(ROOT / "registries" / "evaluations.v2.json")
    assessments = []
    bundles = {}
    entries = [
        ("source", source["source_id"], source["licence_review_id"], source)
        for source in sources["sources"]
        if source["role"] == "foundation_candidate"
    ] + [
        ("evaluation", dataset["dataset_id"], dataset["licence_review_id"], dataset)
        for dataset in evaluations["datasets"]
    ]
    for kind, subject_id, review_id, entry in entries:
        bundle = build_evidence_bundle(
            bundle_id=f"{review_id}-evidence",
            review_id=review_id,
            subject_kind=kind,
            subject_id=subject_id,
            subject_binding_sha256=canonical_sha256(entry),
            documents=[],
            findings=[
                {
                    "finding_id": "human-review-missing",
                    "category": "commercial_scope",
                    "blocking": True,
                    "summary": "Accountable human review is still required.",
                }
            ],
            assembled_at="2026-08-17T00:00:00Z",
        )
        verified = verify_evidence_bundle(bundle, tmp_path)
        assessments.append(make_pending_assessment(bundle))
        bundles[review_id] = verified

    report = evaluate_gate_v3(
        evaluated_at="2026-08-17T01:00:00Z",
        source_registry=sources,
        evaluation_registry=evaluations,
        storage_attestation=None,
        source_audit=None,
        licence_assessments=assessments,
        verified_bundles=bundles,
    )
    assert validate_schema_lock_v3()
    assert report["contracts_frozen"] is True
    assert report["licensing_evidence_verified"] is True
    assert report["licensing_ready"] is False
    assert report["foundation_acquisition_authorized"] is False
    assert report["foundation_transform_ready"] is False
    assert report["training_authorized"] is False
    assert "licensing_not_ready" in report["blockers"]


def test_phase0_v3_fails_closed_when_one_declared_subject_is_omitted(
    tmp_path: Path,
) -> None:
    sources = load_json(ROOT / "registries" / "sources.v2.json")
    evaluations = load_json(ROOT / "registries" / "evaluations.v2.json")
    report = evaluate_gate_v3(
        evaluated_at="2026-08-17T01:00:00Z",
        source_registry=sources,
        evaluation_registry=evaluations,
        storage_attestation=None,
        source_audit=None,
        licence_assessments=[],
        verified_bundles={},
    )
    assert report["licensing_evidence_verified"] is False
    assert "licence_assessment_set_mismatch" in report["blockers"]
    assert "licence_evidence_bundle_set_mismatch" in report["blockers"]
    assert report["training_authorized"] is False
