from __future__ import annotations

from pathlib import Path

from hippocampus_foundation.licence_catalog import (
    load_catalogue,
    prepare_catalogue_packets,
    validate_catalogue,
)
from hippocampus_foundation.phase0.canonical import load_json


ROOT = Path(__file__).resolve().parents[1]


def inputs():
    return (
        load_catalogue(ROOT / "licensing" / "catalog.v1.json"),
        load_json(ROOT / "registries" / "sources.v2.json"),
        load_json(ROOT / "registries" / "evaluations.v2.json"),
        load_json(ROOT / "registries" / "encoder.gte-modernbert.v1.json"),
    )


def test_catalogue_covers_exact_registered_subjects_without_evaluation_content() -> None:
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
    assert "holdout_exposure_requires_replacement_or_independent_custody" in registry_entry[
        "blockers"
    ]


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
