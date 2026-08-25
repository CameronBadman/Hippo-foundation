from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from hippocampus_foundation.licence_catalog import (
    load_catalogue,
    prepare_catalogue_packets,
    rebind_catalogue_packets,
    validate_catalogue,
)
from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.errors import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def inputs():
    return (
        load_catalogue(ROOT / "licensing" / "catalog.v1.json"),
        load_json(ROOT / "registries" / "sources.v2.json"),
        load_json(ROOT / "registries" / "evaluations.v2.json"),
        load_json(ROOT / "registries" / "encoder.gte-modernbert.v1.json"),
    )


def test_catalogue_covers_exact_registered_subjects_without_evaluation_content() -> (
    None
):
    catalogue, sources, evaluations, encoder = inputs()
    registered = validate_catalogue(
        catalogue,
        source_registry=sources,
        evaluation_registry=evaluations,
        encoder_spec=encoder,
    )
    assert len(registered) == 10
    assert sum(len(subject["documents"]) for subject in catalogue["subjects"]) == 43
    assert catalogue["contains_evaluation_content"] is False
    urls = [
        document["url"].casefold()
        for subject in catalogue["subjects"]
        for document in subject["documents"]
    ]
    for marker in ("evidencebench_test_set.json", "dev-labels.lst"):
        assert all(marker not in url for url in urls)
    evidencebench = next(
        subject
        for subject in catalogue["subjects"]
        if subject["subject_id"] == "evidencebench-original-test"
    )
    exposure = next(
        finding
        for finding in evidencebench["findings"]
        if finding["finding_id"] == "holdout-exposure-incident"
    )
    assert exposure["blocking"] is True
    registry_entry = next(
        dataset
        for dataset in evaluations["datasets"]
        if dataset["dataset_id"] == "evidencebench-original-test"
    )
    assert (
        "holdout_exposure_requires_replacement_or_independent_custody"
        in registry_entry["blockers"]
    )


def test_packet_preparation_records_missing_documents_without_leaking_urls(
    tmp_path: Path,
) -> None:
    catalogue, sources, evaluations, encoder = inputs()
    audit_path = tmp_path / "audit-index.json"
    audit = prepare_catalogue_packets(
        catalogue,
        source_registry=sources,
        evaluation_registry=evaluations,
        encoder_spec=encoder,
        evidence_root=tmp_path / "private",
        audit_index_path=audit_path,
        assembled_at="2026-08-17T12:00:00Z",
    )
    assert len(audit["subjects"]) == 10
    assert audit["contains_evaluation_content"] is False
    assert all(subject["decision"] == "pending" for subject in audit["subjects"])
    assert all(subject["training_authorized"] is False for subject in audit["subjects"])
    serialized = audit_path.read_text(encoding="utf-8").casefold()
    assert "https://" not in serialized
    assert "reviewer" not in serialized
    assert "question" not in serialized
    assert "answer" not in serialized


def _pinned_evaluations() -> dict:
    root = load_json(ROOT / "registries" / "evaluations.v4.json")
    result = copy.deepcopy(root)
    result["registry_id"] = "synthetic-catalogue-rebind-pinned"
    result["previous_registry_sha256"] = canonical_sha256(root)
    result["generated_at"] = "2026-08-25T00:05:00Z"
    for current, previous in zip(result["datasets"], root["datasets"], strict=True):
        current["archive_sha256"] = "sha256:" + "1" * 64
        current["adapter_id"] = "synthetic-adapter-v1"
        current["adapter_sha256"] = "sha256:" + "2" * 64
        current["custody_state"] = "pinned"
        current["previous_entry_sha256"] = canonical_sha256(previous)
        if current["usage_role"] == "confirmatory":
            current["custodian_signing_key_fingerprint"] = "A" * 40
        current["blockers"] = [
            blocker
            for blocker in current["blockers"]
            if blocker not in {"archive_hash_missing", "adapter_missing"}
        ]
    return result


def _synthetic_catalogue_captures(catalogue: dict, root: Path) -> None:
    for subject in catalogue["subjects"]:
        subject_root = root / subject["review_id"]
        subject_root.mkdir(parents=True)
        for document in subject["documents"]:
            body = (
                f"Synthetic retained evidence: {subject['review_id']}:"
                f"{document['document_id']}"
            ).encode()
            snapshot_name = f"{document['document_id']}.snapshot"
            (subject_root / snapshot_name).write_bytes(body)
            receipt = {
                "document_id": document["document_id"],
                "role": document["role"],
                "source_kind": document["source_kind"],
                "original_url": document["url"],
                "resolved_url": document["url"],
                "revision": document["revision"],
                "snapshot_path": snapshot_name,
                "media_type": "text/plain",
                "content_encoding": None,
                "byte_count": len(body),
                "sha256": f"sha256:{hashlib.sha256(body).hexdigest()}",
                "retrieved_at": "2026-08-25T00:03:00Z",
                "etag": None,
                "last_modified": None,
                "mutable": document["mutable"],
            }
            (subject_root / f"{document['document_id']}.document.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )


def test_catalogue_rebind_rehashes_separate_captures_and_stays_pending(
    tmp_path: Path,
) -> None:
    catalogue = load_catalogue(ROOT / "licensing" / "catalog.v1.json")
    sources = load_json(ROOT / "registries" / "sources.v4.publisher-pinned.json")
    evaluations = _pinned_evaluations()
    encoder = load_json(ROOT / "registries" / "encoder.gte-modernbert.v1.json")
    captures = tmp_path / "verified-captures"
    captures.mkdir()
    _synthetic_catalogue_captures(catalogue, captures)

    with pytest.raises(ValidationError, match="fully pinned"):
        rebind_catalogue_packets(
            catalogue,
            source_registry=sources,
            evaluation_registry=load_json(ROOT / "registries" / "evaluations.v4.json"),
            encoder_spec=encoder,
            verified_capture_root=captures,
            output_root=tmp_path / "unpinned-output",
            audit_index_path=tmp_path / "unpinned-index.json",
            assembled_at="2026-08-25T00:06:00Z",
        )

    output = tmp_path / "rebound"
    audit_path = tmp_path / "rebind-index.json"
    audit = rebind_catalogue_packets(
        catalogue,
        source_registry=sources,
        evaluation_registry=evaluations,
        encoder_spec=encoder,
        verified_capture_root=captures,
        output_root=output,
        audit_index_path=audit_path,
        assembled_at="2026-08-25T00:06:00Z",
    )
    assert len(audit["subjects"]) == len(catalogue["subjects"])
    assert audit["contains_evaluation_content"] is False
    assert audit["verified_capture_set_sha256"].startswith("sha256:")
    assert all(item["decision"] == "pending" for item in audit["subjects"])
    assert all(item["training_authorized"] is False for item in audit["subjects"])
    assert captures.resolve() not in output.resolve().parents
    serialized = audit_path.read_text(encoding="utf-8").casefold()
    assert "https://" not in serialized
    assert "reviewer" not in serialized

    evaluation = evaluations["datasets"][0]
    rebound_bundle = load_json(output / evaluation["licence_review_id"] / "bundle.json")
    rebound_assessment = load_json(
        output / evaluation["licence_review_id"] / "assessment.pending.json"
    )
    assert rebound_bundle["subject_binding_sha256"] == canonical_sha256(evaluation)
    assert rebound_assessment["decision"] == "pending"

    first_subject = catalogue["subjects"][0]
    first_document = first_subject["documents"][0]
    receipt_path = (
        captures
        / first_subject["review_id"]
        / f"{first_document['document_id']}.document.json"
    )
    forged = load_json(receipt_path)
    forged["snapshot_path"] = "another.snapshot"
    receipt_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(ValidationError, match="snapshot_path"):
        rebind_catalogue_packets(
            catalogue,
            source_registry=sources,
            evaluation_registry=evaluations,
            encoder_spec=encoder,
            verified_capture_root=captures,
            output_root=tmp_path / "forged-output",
            audit_index_path=tmp_path / "forged-index.json",
            assembled_at="2026-08-25T00:06:00Z",
        )
