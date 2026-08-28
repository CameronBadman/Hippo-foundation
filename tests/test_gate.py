from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from hippocampus_foundation.phase0.canonical import canonical_sha256
from hippocampus_foundation.phase0.gate import evaluate_gate

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-08-16T12:00:00Z"


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def ready_evidence() -> tuple[dict, dict, dict, list[dict], dict, set[str]]:
    sources = load("registries/sources.v1.json")
    evaluations = load("registries/evaluations.v1.json")
    for dataset in evaluations["datasets"]:
        dataset["resolved_version"] = "fixture-v1"
        dataset["archive_sha256"] = (
            "sha256:" + hashlib.sha256(dataset["dataset_id"].encode()).hexdigest()
        )
        dataset["licence_status"] = "approved"
        dataset["status"] = "sealed"
        dataset["blockers"] = []

    audited_artifacts = []
    total_bytes = 0
    for source in sources["sources"]:
        for artifact in source["artifacts"]:
            checksums = {
                item["algorithm"]: item["value"] for item in artifact["checksums"]
            }
            measurement = {
                "bytes": artifact["expected_bytes"],
                "md5": checksums.get("md5", "0" * 32),
                "sha1": checksums.get("sha1", "0" * 40),
                "sha256": checksums.get("sha256", "1" * 64),
                "device": 1,
                "inode": len(audited_artifacts) + 1,
                "mtime_ns": 1,
            }
            total_bytes += artifact["expected_bytes"]
            audited_artifacts.append(
                {
                    "source_id": source["source_id"],
                    "artifact_id": artifact["artifact_id"],
                    "locator_id": artifact["locator_id"],
                    "filename": artifact["filename"],
                    "measured": measurement,
                    "status": "verified",
                    "mismatches": [],
                }
            )
    source_audit = {
        "schema_version": "1.0.0",
        "registry_id": sources["registry_id"],
        "registry_sha256": canonical_sha256(sources),
        "storage_map_sha256": canonical_sha256(
            {
                item["locator_id"]: item["required_root"]
                for item in sources["storage_requirements"]
            }
        ),
        "started_at": "2026-08-16T10:00:00Z",
        "completed_at": "2026-08-16T11:00:00Z",
        "artifact_count": len(audited_artifacts),
        "total_bytes": total_bytes,
        "all_verified": True,
        "artifacts": audited_artifacts,
    }

    receipts = []
    seal_ids = set()
    for dataset in evaluations["datasets"]:
        seal_id = dataset["seal_id"]
        seal_ids.add(seal_id)
        receipts.append(
            {
                "schema_version": "1.0.0",
                "seal_id": seal_id,
                "evaluation_class": "confirmatory",
                "ciphertext_sha256": "sha256:"
                + hashlib.sha256((seal_id + ":ciphertext").encode()).hexdigest(),
                "artifact_hashes": [dataset["archive_sha256"]],
                "public_key_fingerprint": "A" * 40,
                "created_at": NOW,
                "custodian": "offline-key-custodian",
                "record_count": 1,
                "state": "sealed",
            }
        )
    quarantine = {
        "schema_version": "1.0.0",
        "index_id": "public-evaluation-union-v1",
        "closure_policy_id": "quarantine-closure-v1",
        "source_seal_ids": sorted(seal_ids),
        "coverage": [
            {
                "seal_id": seal_id,
                "sealed_record_count": 1,
                "seed_identifier_count": 1,
                "closure_identifier_count": 1,
                "relationship_count": 0,
                "raw_hash_count": 0,
                "normalized_hash_count": 0,
                "fingerprint_count": 0,
                "closure_complete": True,
            }
            for seal_id in sorted(seal_ids)
        ],
        "identifiers": [
            {"namespace": "wikipedia.page", "value": "1", "source_version": "20260801"}
        ],
        "raw_hashes": [],
        "normalized_hashes": [],
        "fingerprints": [],
    }
    return sources, evaluations, quarantine, receipts, source_audit, seal_ids


def test_checked_in_state_is_mechanically_blocked_and_never_authorizes_training() -> (
    None
):
    report = evaluate_gate(
        evaluated_at=NOW,
        source_registry=load("registries/sources.v1.json"),
        evaluation_registry=load("registries/evaluations.v1.json"),
        quarantine_index=None,
        seal_receipts=[],
        source_audit=None,
    )
    assert report["schemas_frozen"] is True
    assert report["existing_lake_audit_ready"] is False
    assert report["foundation_acquisition_authorized"] is False
    assert report["public_foundation_ready"] is False
    assert report["training_authorized"] is False
    assert "source_audit_missing" in report["blockers"]
    assert "quarantine_index_missing" in report["blockers"]


def test_checked_in_initial_gate_report_is_reproducible() -> None:
    expected = load("audit/phase0-gate.initial.json")
    observed = evaluate_gate(
        evaluated_at=expected["evaluated_at"],
        source_registry=load("registries/sources.v1.json"),
        evaluation_registry=load("registries/evaluations.v1.json"),
        quarantine_index=None,
        seal_receipts=[],
        source_audit=None,
    )
    assert observed == expected


def test_complete_independent_evidence_can_open_foundation_transform_gate_only() -> (
    None
):
    sources, evaluations, quarantine, receipts, source_audit, seal_ids = (
        ready_evidence()
    )
    report = evaluate_gate(
        evaluated_at=NOW,
        source_registry=sources,
        evaluation_registry=evaluations,
        quarantine_index=quarantine,
        seal_receipts=receipts,
        source_audit=source_audit,
        verified_seal_ids=seal_ids,
    )
    assert report["public_foundation_ready"] is True
    assert report["existing_lake_audit_ready"] is True
    assert report["foundation_acquisition_authorized"] is True
    assert report["foundation_transform_ready"] is True
    assert report["training_authorized"] is False
    assert report["blockers"] == []


def test_stale_source_audit_and_unverified_ciphertext_fail_closed() -> None:
    sources, evaluations, quarantine, receipts, source_audit, seal_ids = (
        ready_evidence()
    )
    source_audit = copy.deepcopy(source_audit)
    source_audit["registry_sha256"] = "sha256:" + "0" * 64
    missing_verified = set(seal_ids)
    missing_verified.remove(next(iter(missing_verified)))
    report = evaluate_gate(
        evaluated_at=NOW,
        source_registry=sources,
        evaluation_registry=evaluations,
        quarantine_index=quarantine,
        seal_receipts=receipts,
        source_audit=source_audit,
        verified_seal_ids=missing_verified,
    )
    assert report["source_integrity_ready"] is False
    assert report["public_confirmatory_ready"] is False
    assert report["public_foundation_ready"] is False
    assert report["training_authorized"] is False
    assert "source_audit_registry_mismatch" in report["blockers"]


def test_quarantine_coverage_and_archive_receipt_binding_fail_closed() -> None:
    sources, evaluations, quarantine, receipts, source_audit, seal_ids = (
        ready_evidence()
    )
    missing_coverage = copy.deepcopy(quarantine)
    missing_coverage["coverage"].pop()
    receipts[0]["artifact_hashes"] = ["sha256:" + "f" * 64]
    report = evaluate_gate(
        evaluated_at=NOW,
        source_registry=sources,
        evaluation_registry=evaluations,
        quarantine_index=missing_coverage,
        seal_receipts=receipts,
        source_audit=source_audit,
        verified_seal_ids=seal_ids,
    )
    assert report["quarantine_ready"] is False
    assert report["public_confirmatory_ready"] is False
    assert report["public_foundation_ready"] is False
    assert "quarantine_coverage_seal_mismatch" in report["blockers"]


def test_stale_source_audit_cannot_authorize_acquisition() -> None:
    sources, evaluations, quarantine, receipts, source_audit, seal_ids = (
        ready_evidence()
    )
    source_audit["started_at"] = "2026-08-01T00:00:00Z"
    source_audit["completed_at"] = "2026-08-01T01:00:00Z"
    report = evaluate_gate(
        evaluated_at=NOW,
        source_registry=sources,
        evaluation_registry=evaluations,
        quarantine_index=quarantine,
        seal_receipts=receipts,
        source_audit=source_audit,
        verified_seal_ids=seal_ids,
    )
    assert report["existing_lake_audit_ready"] is False
    assert report["foundation_acquisition_authorized"] is False
    assert report["public_foundation_ready"] is False
    assert "source_audit_stale" in report["blockers"]
