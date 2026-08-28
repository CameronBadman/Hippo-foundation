"""Mechanical Phase 0 readiness gate."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from .canonical import canonical_sha256
from .validation import (
    schema_digests,
    validate_evaluation_registry,
    validate_instance,
    validate_schema_set,
    validate_source_audit,
    validate_source_registry,
)

PUBLIC_EVALUATION_DATASETS = frozenset(
    {
        "vitaminc",
        "maven-ere",
        "evidence-inference",
        "contractnli",
        "proofwriter",
        "glucose",
        "wiqa",
    }
)
FROZEN_SCHEMA_NAMES = frozenset(
    {
        "access-event.schema.json",
        "evaluation.schema.json",
        "gate.schema.json",
        "graph.schema.json",
        "quarantine-descriptor.schema.json",
        "quarantine-index.schema.json",
        "quarantine-specification.schema.json",
        "seal.schema.json",
        "source-audit.schema.json",
        "source-manifest.schema.json",
        "storage-map.schema.json",
        "training-example.schema.json",
    }
)
SOURCE_AUDIT_MAX_AGE = timedelta(hours=72)


def _foundation_artifact_pairs(
    source_registry: dict[str, Any],
) -> set[tuple[str, str]]:
    return {
        (source["source_id"], artifact["artifact_id"])
        for source in source_registry.get("sources", [])
        if source.get("role") == "foundation_candidate"
        for artifact in source.get("artifacts", [])
    }


def _existing_lake_artifact_pairs(
    source_registry: dict[str, Any],
) -> set[tuple[str, str]]:
    return {
        (source["source_id"], artifact["artifact_id"])
        for source in source_registry.get("sources", [])
        if source.get("role") == "forensic_only"
        for artifact in source.get("artifacts", [])
    }


def evaluate_gate(
    *,
    evaluated_at: str,
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    quarantine_index: dict[str, Any] | None,
    seal_receipts: Iterable[dict[str, Any]],
    source_audit: dict[str, Any] | None,
    verified_seal_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Evaluate only declared Phase 0 controls; training is never authorized."""

    blockers: set[str] = set()
    evidence: set[str] = set()

    try:
        schemas = validate_schema_set()
        schemas_frozen = FROZEN_SCHEMA_NAMES == set(schemas)
        if not schemas_frozen:
            blockers.add("frozen_schema_set_mismatch")
        evidence.add(f"schemas:{canonical_sha256(schema_digests())}")
    except Exception as exc:  # gate reports validation failures as blockers
        schemas_frozen = False
        blockers.add(f"schemas_invalid:{type(exc).__name__}")

    source_registry_valid = False
    try:
        validate_source_registry(source_registry)
        source_registry_valid = True
        evidence.add(f"source_registry:{canonical_sha256(source_registry)}")
    except Exception as exc:
        blockers.add(f"source_registry_invalid:{type(exc).__name__}")

    evaluation_registry_valid = False
    try:
        validate_evaluation_registry(evaluation_registry)
        evaluation_registry_valid = True
        evidence.add(f"evaluation_registry:{canonical_sha256(evaluation_registry)}")
    except Exception as exc:
        blockers.add(f"evaluation_registry_invalid:{type(exc).__name__}")

    foundation_sources = [
        source
        for source in source_registry.get("sources", [])
        if source.get("role") == "foundation_candidate"
    ]
    if not foundation_sources:
        blockers.add("no_foundation_sources")
    for source in foundation_sources:
        if source.get("admission_status") != "accepted":
            blockers.add(f"source_not_accepted:{source.get('source_id', 'unknown')}")

    source_integrity_ready = False
    existing_lake_audit_ready = False
    if source_audit is None:
        blockers.add("source_audit_missing")
    else:
        try:
            validate_source_audit(source_audit)
            evaluated_time = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
            audit_completed_time = datetime.fromisoformat(
                source_audit["completed_at"].replace("Z", "+00:00")
            )
            audit_fresh = True
            if audit_completed_time > evaluated_time:
                blockers.add("source_audit_after_gate_time")
                audit_fresh = False
            elif evaluated_time - audit_completed_time > SOURCE_AUDIT_MAX_AGE:
                blockers.add("source_audit_stale")
                audit_fresh = False
            if source_audit["registry_sha256"] != canonical_sha256(source_registry):
                blockers.add("source_audit_registry_mismatch")
            elif source_audit["storage_map_sha256"] != canonical_sha256(
                {
                    item["locator_id"]: item["required_root"]
                    for item in source_registry.get("storage_requirements", [])
                }
            ):
                blockers.add("source_audit_storage_identity_mismatch")
            else:
                foundation_pairs = _foundation_artifact_pairs(source_registry)
                existing_pairs = _existing_lake_artifact_pairs(source_registry)
                expected_pairs = foundation_pairs | existing_pairs
                audited = {
                    (item["source_id"], item["artifact_id"]): item["status"]
                    for item in source_audit["artifacts"]
                }
                duplicate_count = len(source_audit["artifacts"]) - len(audited)
                if duplicate_count:
                    blockers.add("source_audit_duplicate_artifacts")
                unexpected_pairs = audited.keys() - expected_pairs
                for source_id, artifact_id in sorted(unexpected_pairs):
                    blockers.add(
                        f"source_audit_unregistered_artifact:{source_id}:{artifact_id}"
                    )
                missing_foundation = foundation_pairs - audited.keys()
                for source_id, artifact_id in sorted(missing_foundation):
                    blockers.add(
                        f"foundation_artifact_not_audited:{source_id}:{artifact_id}"
                    )
                failed_foundation = {
                    pair
                    for pair in foundation_pairs & audited.keys()
                    if audited[pair] != "verified"
                }
                for source_id, artifact_id in sorted(failed_foundation):
                    blockers.add(
                        f"foundation_artifact_not_verified:{source_id}:{artifact_id}"
                    )
                source_integrity_ready = bool(foundation_pairs) and not (
                    duplicate_count
                    or unexpected_pairs
                    or missing_foundation
                    or failed_foundation
                )
                missing_existing = existing_pairs - audited.keys()
                failed_existing = {
                    pair
                    for pair in existing_pairs & audited.keys()
                    if audited[pair] != "verified"
                }
                for source_id, artifact_id in sorted(missing_existing):
                    blockers.add(
                        f"existing_lake_artifact_not_audited:{source_id}:{artifact_id}"
                    )
                for source_id, artifact_id in sorted(failed_existing):
                    blockers.add(
                        f"existing_lake_artifact_not_verified:{source_id}:{artifact_id}"
                    )
                existing_lake_audit_ready = bool(existing_pairs) and not (
                    duplicate_count
                    or unexpected_pairs
                    or missing_existing
                    or failed_existing
                )
                source_integrity_ready = source_integrity_ready and audit_fresh
                existing_lake_audit_ready = existing_lake_audit_ready and audit_fresh
            evidence.add(f"source_audit:{canonical_sha256(source_audit)}")
        except Exception as exc:
            blockers.add(f"source_audit_invalid:{type(exc).__name__}")
    if not source_integrity_ready:
        blockers.add("source_integrity_not_ready")
    if not existing_lake_audit_ready:
        blockers.add("existing_lake_audit_not_ready")

    licensing_ready = source_registry_valid and bool(foundation_sources)
    for source in foundation_sources:
        licence = source.get("licence", {})
        if (
            licence.get("review_status") != "approved"
            or licence.get("commercial_use") != "allowed"
            or "train" not in licence.get("allowed_uses", [])
        ):
            licensing_ready = False
            blockers.add(
                f"foundation_licence_not_approved:{source.get('source_id', 'unknown')}"
            )

    datasets = evaluation_registry.get("datasets", [])
    datasets_by_id: dict[str, dict[str, Any]] = {}
    duplicate_dataset_ids: set[str] = set()
    for dataset in datasets:
        dataset_id = dataset.get("dataset_id", "unknown")
        if dataset_id in datasets_by_id:
            duplicate_dataset_ids.add(dataset_id)
        datasets_by_id[dataset_id] = dataset
    for dataset_id in sorted(duplicate_dataset_ids):
        blockers.add(f"evaluation_dataset_duplicate:{dataset_id}")
    for missing in sorted(PUBLIC_EVALUATION_DATASETS - datasets_by_id.keys()):
        blockers.add(f"evaluation_dataset_missing:{missing}")
    for dataset in datasets:
        dataset_id = dataset.get("dataset_id", "unknown")
        if dataset.get("status") != "sealed":
            blockers.add(f"evaluation_not_sealed:{dataset_id}")
        if dataset.get("licence_status") != "approved":
            blockers.add(f"evaluation_licence_not_approved:{dataset_id}")
        for item in dataset.get("blockers", []):
            blockers.add(f"evaluation_blocker:{dataset_id}:{item}")

    verified_seals = set(verified_seal_ids)
    receipt_by_id: dict[str, dict[str, Any]] = {}
    private_transfer_ready = False
    for receipt in seal_receipts:
        try:
            validate_instance(receipt, "seal.schema.json")
            seal_id = receipt["seal_id"]
            if seal_id in receipt_by_id:
                blockers.add(f"seal_duplicate:{seal_id}")
            receipt_by_id[seal_id] = receipt
            evidence.add(f"seal:{seal_id}:{canonical_sha256(receipt)}")
            if seal_id not in verified_seals:
                blockers.add(f"seal_ciphertext_not_verified:{seal_id}")
            if (
                seal_id in verified_seals
                and receipt["state"] == "sealed"
                and receipt["evaluation_class"] == "private_transfer"
            ):
                private_transfer_ready = True
        except Exception as exc:
            blockers.add(f"seal_invalid:{type(exc).__name__}")

    quarantine_seal_ids: set[str] = set()
    coverage_by_seal: dict[str, dict[str, Any]] = {}
    quarantine_ready = False
    if quarantine_index is None:
        blockers.add("quarantine_index_missing")
    else:
        try:
            validate_instance(quarantine_index, "quarantine-index.schema.json")
            quarantine_seal_ids = set(quarantine_index["source_seal_ids"])
            coverage_valid = True
            for item in quarantine_index["coverage"]:
                seal_id = item["seal_id"]
                if seal_id in coverage_by_seal:
                    blockers.add(f"quarantine_coverage_duplicate:{seal_id}")
                    coverage_valid = False
                coverage_by_seal[seal_id] = item
                selector_count = sum(
                    item[field]
                    for field in (
                        "seed_identifier_count",
                        "raw_hash_count",
                        "normalized_hash_count",
                        "fingerprint_count",
                    )
                )
                if selector_count < 1:
                    blockers.add(f"quarantine_coverage_empty:{seal_id}")
                    coverage_valid = False
                if item["closure_identifier_count"] < item["seed_identifier_count"]:
                    blockers.add(f"quarantine_coverage_closure_underflow:{seal_id}")
                    coverage_valid = False
            if quarantine_seal_ids != coverage_by_seal.keys():
                blockers.add("quarantine_coverage_seal_mismatch")
                coverage_valid = False
            fingerprint_ids = [
                item["fingerprint_id"] for item in quarantine_index["fingerprints"]
            ]
            if len(fingerprint_ids) != len(set(fingerprint_ids)):
                blockers.add("quarantine_fingerprint_id_duplicate")
                coverage_valid = False
            if (
                len(quarantine_index["identifiers"])
                > sum(
                    item["closure_identifier_count"]
                    for item in coverage_by_seal.values()
                )
                or len(quarantine_index["raw_hashes"])
                > sum(item["raw_hash_count"] for item in coverage_by_seal.values())
                or len(quarantine_index["normalized_hashes"])
                > sum(
                    item["normalized_hash_count"] for item in coverage_by_seal.values()
                )
                or len(quarantine_index["fingerprints"])
                != sum(item["fingerprint_count"] for item in coverage_by_seal.values())
            ):
                blockers.add("quarantine_coverage_count_mismatch")
                coverage_valid = False
            quarantine_ready = (
                bool(
                    quarantine_index["identifiers"]
                    or quarantine_index["raw_hashes"]
                    or quarantine_index["normalized_hashes"]
                    or quarantine_index["fingerprints"]
                )
                and bool(quarantine_seal_ids)
                and coverage_valid
            )
            evidence.add(f"quarantine_index:{canonical_sha256(quarantine_index)}")
        except Exception as exc:
            blockers.add(f"quarantine_index_invalid:{type(exc).__name__}")
    if not quarantine_ready:
        blockers.add("quarantine_not_ready")

    public_confirmatory_ready = evaluation_registry_valid and not duplicate_dataset_ids
    for dataset_id in sorted(PUBLIC_EVALUATION_DATASETS):
        dataset = datasets_by_id.get(dataset_id)
        if dataset is None:
            public_confirmatory_ready = False
            continue
        seal_id = dataset.get("seal_id")
        receipt = receipt_by_id.get(seal_id) if seal_id else None
        coverage = coverage_by_seal.get(seal_id) if seal_id else None
        dataset_ready = bool(
            dataset.get("status") == "sealed"
            and dataset.get("licence_status") == "approved"
            and not dataset.get("blockers")
            and seal_id in verified_seals
            and seal_id in quarantine_seal_ids
            and receipt
            and receipt.get("state") == "sealed"
            and receipt.get("evaluation_class") == "confirmatory"
            and dataset.get("archive_sha256") in receipt.get("artifact_hashes", [])
            and coverage
            and coverage.get("sealed_record_count") == receipt.get("record_count")
            and coverage.get("closure_complete") is True
        )
        if not dataset_ready:
            public_confirmatory_ready = False
            blockers.add(f"public_evaluation_not_ready:{dataset_id}")
    if not public_confirmatory_ready:
        blockers.add("public_confirmatory_not_ready")

    foundation_acquisition_authorized = all(
        [
            schemas_frozen,
            existing_lake_audit_ready,
            licensing_ready,
            quarantine_ready,
            public_confirmatory_ready,
        ]
    )
    foundation_transform_ready = all(
        [
            schemas_frozen,
            existing_lake_audit_ready,
            source_integrity_ready,
            licensing_ready,
            quarantine_ready,
            public_confirmatory_ready,
        ]
    )
    report = {
        "schema_version": "1.0.0",
        "gate_id": "phase0-public-foundation-v1",
        "evaluated_at": evaluated_at,
        "schemas_frozen": schemas_frozen,
        "existing_lake_audit_ready": existing_lake_audit_ready,
        "source_integrity_ready": source_integrity_ready,
        "licensing_ready": licensing_ready,
        "quarantine_ready": quarantine_ready,
        "public_confirmatory_ready": public_confirmatory_ready,
        "private_transfer_ready": private_transfer_ready,
        "foundation_acquisition_authorized": foundation_acquisition_authorized,
        "foundation_transform_ready": foundation_transform_ready,
        "public_foundation_ready": foundation_transform_ready,
        "training_authorized": False,
        "blockers": sorted(blockers),
        "evidence": sorted(evidence),
    }
    validate_instance(report, "gate.schema.json")
    return report
