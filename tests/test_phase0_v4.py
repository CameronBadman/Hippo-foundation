from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hippocampus_foundation.licensing import (
    FORBIDDEN_USES,
    build_evidence_bundle,
    verify_evidence_bundle,
)
from hippocampus_foundation.phase0.canonical import (
    canonical_bytes,
    canonical_sha256,
    load_json,
)
from hippocampus_foundation.phase0.cli import _read_bounded_regular_file
from hippocampus_foundation.phase0.errors import (
    GateBlocked,
    IntegrityError,
    Phase0Error,
    QuarantineError,
    ValidationError,
)
from hippocampus_foundation.phase0.evaluation_firewall import (
    build_quarantine_contribution_v4,
    compile_quarantine_index_v4,
    make_seal_receipt_v4,
    validate_evaluation_registry_v4,
    validate_source_registry_v4,
    verify_seal_ciphertext_v4,
)
from hippocampus_foundation.phase0.external_evidence import (
    bind_drive_observation_v4,
    build_publisher_checksum_receipt_v4,
    make_access_anchor_payload_v4,
    validate_storage_attestation_v4,
    verify_access_anchor_v4,
    verify_publisher_checksum_receipt_v4,
)
from hippocampus_foundation.phase0.quarantine import fingerprint_text
from hippocampus_foundation.phase0.quarantine_v4 import (
    build_source_record_descriptor_v4,
    match_quarantine_record_v4,
    require_clear_quarantine_receipt_v4,
)
from hippocampus_foundation.phase0.source_evidence_v4 import assess_admission_v4
from hippocampus_foundation.phase0.v3 import (
    EVALUATION_REQUIRED_USES,
    SOURCE_REQUIRED_USES,
)
from hippocampus_foundation.phase0.v4 import (
    evaluate_gate_v4,
    require_phase0_transform_gate_v4,
)
from hippocampus_foundation.phase0.v4_contracts import (
    validate_schema_lock_v4,
    validate_v4,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-08-25T10:00:00Z"
T1 = "2026-08-25T10:05:00Z"
T2 = "2026-08-25T10:10:00Z"
T3 = "2026-08-25T10:20:00Z"
T4 = "2026-08-25T10:30:00Z"
EVALUATED = "2026-08-25T12:00:00Z"
ROOT_PATH = "/content/drive/Shareddrives/Data/graph-memory-data-lake"
KEY_FINGERPRINT = "A" * 40


def _sha1(value: bytes) -> str:
    return hashlib.sha1(value, usedforsecurity=False).hexdigest()


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _pending_source_registry(payload: bytes) -> dict:
    return {
        "schema_version": "4.0.0",
        "registry_kind": "sources",
        "registry_id": "synthetic-sources-v4-pending",
        "previous_registry_sha256": "sha256:" + "1" * 64,
        "generated_at": T0,
        "storage_requirements": [
            {
                "locator_id": "drive_lake",
                "provider": "google_drive_shared_drive",
                "provider_resource_id": None,
                "root_resource_id": None,
                "required_root": ROOT_PATH,
            }
        ],
        "publisher_evidence_requirements": [
            {
                "evidence_id": "synthetic-source-checksum-v4",
                "source_id": "synthetic-source-v1",
                "artifact_id": "synthetic-source-artifact-v1",
                "statement_url": "https://publisher.example/checksums.txt",
                "statement_format": "gnu_checksum_manifest_v1",
                "max_age_hours": 72,
            }
        ],
        "sources": [
            {
                "source_id": "synthetic-source-v1",
                "publisher": "Synthetic test publisher",
                "version": "v1",
                "snapshot_at": T0,
                "role": "foundation_candidate",
                "admission_status": "pending",
                "licence_review_id": "synthetic-source-rights-v4",
                "quarantine_required": True,
                "artifacts": [
                    {
                        "artifact_id": "synthetic-source-artifact-v1",
                        "locator_id": "drive_lake",
                        "filename": "raw/synthetic/source.sql.gz",
                        "source_url": "https://publisher.example/source.sql.gz",
                        "media_type": "application/sql",
                        "compression": "gzip",
                        "expected_bytes": len(payload),
                        "checksums": [
                            {
                                "algorithm": "sha1",
                                "value": _sha1(payload),
                                "origin": "publisher",
                                "verified": False,
                            }
                        ],
                        "raw_policy": "immutable",
                        "integrity_status": "unverified",
                        "availability": "preexisting",
                        "inventory_kind": "mediawiki_sql",
                        "required_nonzero_counters": [
                            "rows",
                            "insert_statements",
                        ],
                        "required_zero_counters": [
                            "parse_errors",
                            "rejected_records",
                        ],
                    }
                ],
            }
        ],
    }


def _drive_observation() -> dict:
    return {
        "schema_version": "1.0.0",
        "record_kind": "drive_identity_observation",
        "observed_at": T0,
        "requested_scope": "https://www.googleapis.com/auth/drive.readonly",
        "scope_exact": True,
        "same_account_human_attested": True,
        "principal_permission_id_sha256": "sha256:" + "2" * 64,
        "provider": "google_drive_shared_drive",
        "provider_resource_id": "synthetic-shared-drive-id",
        "root_resource_id": "synthetic-root-folder-id",
        "observed_root": ROOT_PATH,
        "method": "google_drive_api_v3_authenticated",
        "checks": {
            "unique_shared_drive": True,
            "unique_direct_folder": True,
            "folder_not_shortcut": True,
            "list_get_consistent": True,
            "live_drivefs_mount": True,
            "identity_stable": True,
        },
        "contains_evaluation_content": False,
        "api_drive_write_authorized": False,
        "drive_write_performed": False,
        "mount_write_capability_assessed": False,
        "training_authorized": False,
    }


def _pending_evaluation_registry() -> dict:
    entry = {
        "dataset_id": "synthetic-confirmatory-v1",
        "task_role": "synthetic governance verification",
        "usage_role": "confirmatory",
        "official_source": "private:first-party-generator",
        "resolved_version": "v1",
        "partition": "private-confirmatory-10",
        "archive_sha256": None,
        "seal_id": "synthetic-confirmatory-seal-v4",
        "licence_review_id": "synthetic-evaluation-rights-v4",
        "adapter_id": None,
        "adapter_sha256": None,
        "custody_state": "declared",
        "project_exposure": "metadata_only",
        "confirmation_eligible": True,
        "exposure_history": [
            {
                "event_id": "synthetic-metadata-declaration-v4",
                "event_kind": "metadata_only",
                "recorded_at": T0,
                "evidence_refs": ["synthetic:test-fixture"],
            }
        ],
        "blockers": ["archive_hash_missing", "adapter_missing", "seal_missing"],
        "dependency_units": ["synthetic.family"],
        "previous_entry_sha256": "sha256:" + "3" * 64,
        "custodian_signing_key_fingerprint": None,
        "quarantine_required": True,
        "training_authorized": False,
    }
    return {
        "schema_version": "4.0.0",
        "registry_kind": "evaluations",
        "registry_id": "synthetic-evaluations-v4-pending",
        "previous_registry_sha256": "sha256:" + "4" * 64,
        "generated_at": T0,
        "closure_policy_id": "quarantine-closure-v4",
        "evaluation_protocol": {"decision": "synthetic contract test only"},
        "datasets": [entry],
    }


def _ready_evaluation_registry(predecessor: dict) -> dict:
    result = copy.deepcopy(predecessor)
    result["registry_id"] = "synthetic-evaluations-v4-ready"
    result["previous_registry_sha256"] = canonical_sha256(predecessor)
    result["generated_at"] = T2
    entry = result["datasets"][0]
    entry["archive_sha256"] = "sha256:" + "5" * 64
    entry["adapter_id"] = "synthetic-adapter-v1"
    entry["adapter_sha256"] = "sha256:" + "6" * 64
    entry["custody_state"] = "sealed"
    entry["blockers"] = []
    entry["previous_entry_sha256"] = canonical_sha256(predecessor["datasets"][0])
    entry["custodian_signing_key_fingerprint"] = KEY_FINGERPRINT
    return result


def _approved_rights(
    tmp_path: Path,
    *,
    kind: str,
    subject_id: str,
    review_id: str,
    entry: dict,
    required_uses: frozenset[str],
) -> tuple[dict, object]:
    snapshot = tmp_path / f"{review_id}.snapshot"
    content = f"Synthetic rights evidence for {subject_id}.".encode()
    snapshot.write_bytes(content)
    document = {
        "document_id": f"{review_id}-attestation",
        "role": "first_party_attestation",
        "source_kind": "local_attestation",
        "original_url": f"urn:synthetic:{review_id}",
        "resolved_url": f"urn:synthetic:{review_id}",
        "revision": "v1",
        "snapshot_path": snapshot.name,
        "media_type": "text/plain",
        "content_encoding": None,
        "byte_count": len(content),
        "sha256": _sha256(content),
        "retrieved_at": T0,
        "etag": None,
        "last_modified": None,
        "mutable": False,
    }
    bundle = build_evidence_bundle(
        bundle_id=f"{review_id}-evidence",
        review_id=review_id,
        subject_kind=kind,
        subject_id=subject_id,
        subject_binding_sha256=canonical_sha256(entry),
        documents=[document],
        findings=[],
        assembled_at=T1,
    )
    verified = verify_evidence_bundle(bundle, tmp_path)
    assessment = {
        "schema_version": "1.0.0",
        "record_kind": "licence_assessment",
        "review_id": review_id,
        "subject_kind": kind,
        "subject_id": subject_id,
        "subject_binding_sha256": canonical_sha256(entry),
        "bundle_sha256": verified.sha256,
        "decision": "approved",
        "commercial_context": "allowed",
        "licence_identifiers": ["LicenseRef-SYNTHETIC-TEST"],
        "allowed_uses": sorted(required_uses),
        "excluded_uses": sorted(FORBIDDEN_USES),
        "obligations": [],
        "finding_dispositions": [],
        "reviewer": "synthetic-test-reviewer",
        "reviewed_at": T2,
        "valid_until": "2026-09-25T10:10:00Z",
        "training_authorized": False,
        "notes": "Synthetic fixture approval; not evidence for a real dataset.",
    }
    return assessment, verified


def _source_audit(
    registry: dict,
    attestation: dict,
    publisher_receipt: object,
    payload: bytes,
) -> dict:
    return {
        "schema_version": "4.0.0",
        "record_kind": "source_audit",
        "registry_id": registry["registry_id"],
        "registry_sha256": canonical_sha256(registry),
        "storage_attestation_sha256": canonical_sha256(attestation),
        "publisher_receipt_sha256s": [publisher_receipt.sha256],
        "started_at": T1,
        "completed_at": T2,
        "artifact_count": 1,
        "total_bytes": len(payload),
        "all_verified": True,
        "artifacts": [
            {
                "source_id": "synthetic-source-v1",
                "artifact_id": "synthetic-source-artifact-v1",
                "locator_id": "drive_lake",
                "filename": "raw/synthetic/source.sql.gz",
                "measured": {
                    "bytes": len(payload),
                    "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
                    "sha1": _sha1(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "device": "1",
                    "inode": "2",
                    "mtime_ns": "3",
                },
                "status": "verified",
                "mismatches": [],
            }
        ],
        "training_authorized": False,
    }


def _inventory(
    registry: dict,
    attestation: dict,
    audit: dict,
    publisher_receipt: object,
    payload: bytes,
) -> dict:
    return {
        "schema_version": "4.0.0",
        "record_kind": "structural_inventory",
        "source_id": "synthetic-source-v1",
        "artifact_id": "synthetic-source-artifact-v1",
        "registry_sha256": canonical_sha256(registry),
        "source_audit_sha256": canonical_sha256(audit),
        "storage_attestation_sha256": canonical_sha256(attestation),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "artifact_sha256": _sha256(payload),
        "artifact_bytes": len(payload),
        "counter_kind": "mediawiki_sql",
        "counter_version": "hf-stream-counter-v4",
        "started_at": "2026-08-25T10:11:00Z",
        "completed_at": "2026-08-25T10:12:00Z",
        "complete": True,
        "parse_errors": 0,
        "rejected_records": 0,
        "counters": {"rows": 1, "insert_statements": 1},
        "training_authorized": False,
    }


def _access_event(seal_id: str) -> dict:
    payload = {
        "schema_version": "1.0.0",
        "seal_id": seal_id,
        "action": "seal_created",
        "actor": "synthetic-custodian",
        "at": T3,
        "previous_hash": None,
        "details": {"receipt_id": "synthetic-receipt-v4"},
    }
    return {**payload, "event_hash": canonical_sha256(payload)}


def _complete_evidence(tmp_path: Path) -> dict:
    payload = b"synthetic source bytes\n"
    source_predecessor = _pending_source_registry(payload)
    sources, attestation = bind_drive_observation_v4(
        source_predecessor,
        _drive_observation(),
        registry_id="synthetic-sources-v4-bound",
        verifier="synthetic-storage-verifier",
        bound_at=T0,
    )
    artifact = sources["sources"][0]["artifacts"][0]
    statement = f"{_sha1(payload)}  {Path(artifact['filename']).name}\n".encode()
    publisher_receipt = build_publisher_checksum_receipt_v4(
        source_registry=sources,
        evidence_id="synthetic-source-checksum-v4",
        statement=statement,
        resolved_url="https://publisher.example/checksums.txt",
        retrieved_at=T1,
        verified_at=T1,
        verifier="synthetic-publisher-verifier",
    )
    publisher = verify_publisher_checksum_receipt_v4(
        publisher_receipt, statement, sources, evaluated_at=EVALUATED
    )

    evaluation_predecessor = _pending_evaluation_registry()
    evaluations = _ready_evaluation_registry(evaluation_predecessor)
    dataset = evaluations["datasets"][0]
    envelope = {
        "schema_version": "4.0.0",
        "record_kind": "evaluation_envelope",
        "dataset_id": dataset["dataset_id"],
        "usage_role": "confirmatory",
        "resolved_version": dataset["resolved_version"],
        "archive_sha256": dataset["archive_sha256"],
        "adapter_id": dataset["adapter_id"],
        "adapter_sha256": dataset["adapter_sha256"],
        "commitment_nonce": "9" * 64,
        "records": [
            {
                "record_id": "synthetic-heldout-record-1",
                "selectors": {
                    "identifiers": [
                        {
                            "namespace": "synthetic.family",
                            "value": "family-1",
                            "source_version": "v1",
                        }
                    ],
                    "raw_hashes": ["sha256:" + "7" * 64],
                    "normalized_hashes": ["sha256:" + "8" * 64],
                    "fingerprints": [
                        fingerprint_text(
                            "synthetic held out sentence", "synthetic-fingerprint-1"
                        )
                    ],
                },
                "expected_dependency_units": [
                    {
                        "namespace": "synthetic.family",
                        "value": "family-1",
                        "source_version": "v1",
                    }
                ],
                "resolved_dependency_units": [
                    {
                        "namespace": "synthetic.family",
                        "value": "family-1",
                        "source_version": "v1",
                    }
                ],
                "unresolved_dependency_units": [],
                "private_payload": {"answer": "never publish this field"},
            }
        ],
        "training_authorized": False,
    }
    contribution = build_quarantine_contribution_v4(envelope)
    quarantine = compile_quarantine_index_v4(
        [contribution], expected_dataset_ids=[dataset["dataset_id"]]
    )
    ciphertext = tmp_path / "synthetic-evaluation.gpg"
    ciphertext.write_bytes(b"synthetic ciphertext")
    seal_receipt = make_seal_receipt_v4(
        evaluation_registry=evaluations,
        envelope=envelope,
        contribution=contribution,
        ciphertext_sha256=_sha256(ciphertext.read_bytes()),
        public_key_fingerprint=KEY_FINGERPRINT,
        custodian="synthetic-custodian",
        created_at=T2,
    )
    seal = verify_seal_ciphertext_v4(
        ciphertext,
        seal_receipt,
        evaluation_registry=evaluations,
        contribution=contribution,
    )
    access_events = [_access_event(dataset["seal_id"])]
    anchor_payload = make_access_anchor_payload_v4(
        seal_receipt=seal_receipt,
        access_events=access_events,
        sequence=1,
        previous_anchor=None,
        anchored_at=T4,
        valid_until="2026-08-27T10:30:00Z",
        authority_id="synthetic-independent-anchor",
        signing_key_fingerprint=KEY_FINGERPRINT,
    )
    anchor = verify_access_anchor_v4(
        anchor_payload,
        signature=b"synthetic detached signature",
        public_key=b"synthetic public key",
        expected_signing_key_fingerprint=KEY_FINGERPRINT,
        access_events=access_events,
        seal_receipt=seal_receipt,
        evaluated_at=EVALUATED,
        signature_verifier=lambda payload, signature, key, expected: expected,
    )

    source_assessment, source_bundle = _approved_rights(
        tmp_path,
        kind="source",
        subject_id="synthetic-source-v1",
        review_id="synthetic-source-rights-v4",
        entry=sources["sources"][0],
        required_uses=SOURCE_REQUIRED_USES,
    )
    evaluation_assessment, evaluation_bundle = _approved_rights(
        tmp_path,
        kind="evaluation",
        subject_id=dataset["dataset_id"],
        review_id=dataset["licence_review_id"],
        entry=dataset,
        required_uses=EVALUATION_REQUIRED_USES,
    )
    audit = _source_audit(sources, attestation, publisher, payload)
    inventory = _inventory(sources, attestation, audit, publisher, payload)
    admission = assess_admission_v4(
        source_id="synthetic-source-v1",
        source_registry=sources,
        evaluation_registry=evaluations,
        storage_attestation=attestation,
        source_audit=audit,
        publisher_receipts=[publisher],
        assessment=source_assessment,
        verified_bundle=source_bundle,
        inventories=[inventory],
        quarantine_index=quarantine,
        assessor="synthetic-admission-assessor",
        assessed_at=EVALUATED,
    )
    return {
        "evaluated_at": EVALUATED,
        "source_registry": sources,
        "source_registry_predecessor": source_predecessor,
        "evaluation_registry": evaluations,
        "evaluation_registry_predecessor": evaluation_predecessor,
        "drive_observation": _drive_observation(),
        "storage_attestation": attestation,
        "publisher_receipts": [publisher],
        "source_audit": audit,
        "licence_assessments": [source_assessment, evaluation_assessment],
        "verified_bundles": {
            source_assessment["review_id"]: source_bundle,
            evaluation_assessment["review_id"]: evaluation_bundle,
        },
        "quarantine_contributions": [contribution],
        "quarantine_index": quarantine,
        "verified_seals": [seal],
        "evaluation_access_events": {dataset["seal_id"]: access_events},
        "verified_access_anchors": {dataset["seal_id"]: anchor},
        "structural_inventories": [inventory],
        "admission_receipts": [admission],
    }


def test_checked_v4_contracts_and_registries_are_frozen() -> None:
    assert len(validate_schema_lock_v4()) == 8
    sources_v2 = load_json(ROOT / "registries" / "sources.v2.json")
    sources_v4 = load_json(ROOT / "registries" / "sources.v4.pending.json")
    evaluations_v2 = load_json(ROOT / "registries" / "evaluations.v2.json")
    evaluations_v4 = load_json(ROOT / "registries" / "evaluations.v4.json")
    validate_source_registry_v4(sources_v4, sources_v2)
    validate_evaluation_registry_v4(evaluations_v4, evaluations_v2)
    roles = {
        item["dataset_id"]: item["usage_role"] for item in evaluations_v4["datasets"]
    }
    assert roles["socialiqa-v1.4-validation"] == "development"
    assert roles["evidencebench-original-test"] == "diagnostic"
    assert sum(role == "confirmatory" for role in roles.values()) == 5


def test_role_laundering_and_registry_rewrites_are_rejected() -> None:
    old = load_json(ROOT / "registries" / "evaluations.v2.json")
    new = load_json(ROOT / "registries" / "evaluations.v4.json")
    social = next(
        item for item in new["datasets"] if item["dataset_id"].startswith("socialiqa")
    )
    social["usage_role"] = "confirmatory"
    social["confirmation_eligible"] = True
    social["seal_id"] = "laundered-confirmatory-v4"
    with pytest.raises(ValidationError, match="development or validation"):
        validate_evaluation_registry_v4(new, old)

    old_sources = load_json(ROOT / "registries" / "sources.v2.json")
    new_sources = load_json(ROOT / "registries" / "sources.v4.pending.json")
    new_sources["sources"][0]["version"] = "rewritten"
    with pytest.raises(ValidationError, match="byte-identical"):
        validate_source_registry_v4(new_sources, old_sources)

    escaped_sources = load_json(ROOT / "registries" / "sources.v4.pending.json")
    escaped_sources["sources"][0]["artifacts"][0]["filename"] = "../../escape"
    with pytest.raises(ValidationError, match="escapes its storage root"):
        validate_source_registry_v4(escaped_sources)

    insecure_sources = load_json(ROOT / "registries" / "sources.v4.pending.json")
    insecure_sources["sources"][0]["artifacts"][0]["source_url"] = (
        "http://publisher.example/source"
    )
    with pytest.raises(ValidationError, match="source_url"):
        validate_source_registry_v4(insecure_sources)


def test_publisher_receipt_binds_exact_statement_and_expires(tmp_path: Path) -> None:
    payload = b"publisher-bound bytes"
    pending = _pending_source_registry(payload)
    bound, _ = bind_drive_observation_v4(
        pending,
        _drive_observation(),
        registry_id="synthetic-sources-v4-bound",
        verifier="verifier",
        bound_at=T0,
    )
    statement = f"{_sha1(payload)}  source.sql.gz\n".encode()
    receipt = build_publisher_checksum_receipt_v4(
        source_registry=bound,
        evidence_id="synthetic-source-checksum-v4",
        statement=statement,
        resolved_url="https://publisher.example/checksums.txt",
        retrieved_at=T1,
        verified_at=T1,
        verifier="publisher-verifier",
    )
    verified = verify_publisher_checksum_receipt_v4(
        receipt, statement, bound, evaluated_at=EVALUATED
    )
    assert verified.statement_sha256 == _sha256(statement)
    with pytest.raises((IntegrityError, ValidationError)):
        verify_publisher_checksum_receipt_v4(
            receipt,
            statement.replace(_sha1(payload).encode(), b"0" * 40),
            bound,
            evaluated_at=EVALUATED,
        )
    with pytest.raises(ValidationError, match="stale"):
        verify_publisher_checksum_receipt_v4(
            receipt, statement, bound, evaluated_at="2026-08-29T10:05:01Z"
        )

    bounded = tmp_path / "bounded-statement"
    bounded.write_bytes(b"12345678")
    assert _read_bounded_regular_file(bounded, 8, "test statement") == b"12345678"
    with pytest.raises(Phase0Error, match="size limit"):
        _read_bounded_regular_file(bounded, 7, "test statement")
    linked = tmp_path / "linked-statement"
    linked.symlink_to(bounded)
    with pytest.raises(Phase0Error, match="cannot open"):
        _read_bounded_regular_file(linked, 8, "test statement")


def test_storage_attestation_requires_the_bound_observation() -> None:
    pending = _pending_source_registry(b"bytes")
    observation = _drive_observation()
    bound, attestation = bind_drive_observation_v4(
        pending,
        observation,
        registry_id="synthetic-sources-v4-bound",
        verifier="verifier",
        bound_at=T0,
    )
    validate_storage_attestation_v4(
        attestation, bound, observation=observation, evaluated_at=EVALUATED
    )
    changed = copy.deepcopy(observation)
    changed["principal_permission_id_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="observation digest"):
        validate_storage_attestation_v4(
            attestation, bound, observation=changed, evaluated_at=EVALUATED
        )


def test_quarantine_contribution_removes_private_payload_and_requires_closure(
    tmp_path: Path,
) -> None:
    evidence = _complete_evidence(tmp_path)
    contribution = evidence["quarantine_contributions"][0]
    assert "private_payload" not in repr(contribution)
    assert "answer" not in repr(contribution)
    assert "commitment_nonce" not in repr(contribution)
    assert contribution["coverage"]["uncovered_record_count"] == 0

    envelope = {
        "schema_version": "4.0.0",
        "record_kind": "evaluation_envelope",
        "dataset_id": "synthetic-confirmatory-v1",
        "usage_role": "confirmatory",
        "resolved_version": "v1",
        "archive_sha256": "sha256:" + "1" * 64,
        "adapter_id": "adapter-v1",
        "adapter_sha256": "sha256:" + "2" * 64,
        "commitment_nonce": "4" * 64,
        "records": [
            {
                "record_id": "record-1",
                "selectors": {
                    "identifiers": [],
                    "raw_hashes": ["sha256:" + "3" * 64],
                    "normalized_hashes": [],
                    "fingerprints": [],
                },
                "expected_dependency_units": [],
                "resolved_dependency_units": [],
                "unresolved_dependency_units": [],
                "private_payload": {"answer": "private"},
            }
        ],
        "training_authorized": False,
    }
    first_commitment = build_quarantine_contribution_v4(envelope)["records"][0][
        "record_commitment"
    ]
    envelope["commitment_nonce"] = "5" * 64
    second_commitment = build_quarantine_contribution_v4(envelope)["records"][0][
        "record_commitment"
    ]
    assert first_commitment != second_commitment

    missing_nonce = copy.deepcopy(envelope)
    missing_nonce.pop("commitment_nonce")
    missing_nonce["records"][0]["private_payload"] = {
        "answer": "uniquely-sensitive-answer"
    }
    with pytest.raises(ValidationError) as captured:
        build_quarantine_contribution_v4(missing_nonce)
    assert "uniquely-sensitive-answer" not in str(captured.value)

    envelope["records"][0]["unresolved_dependency_units"] = ["unknown-family"]
    with pytest.raises(QuarantineError, match="incomplete dependency closure"):
        build_quarantine_contribution_v4(envelope)

    tampered = copy.deepcopy(contribution)
    tampered["coverage"]["selector_count"] += 1
    with pytest.raises(QuarantineError, match="coverage is inconsistent"):
        compile_quarantine_index_v4([tampered])


def test_quarantine_matcher_is_tri_state_and_pre_feature(tmp_path: Path) -> None:
    evidence = _complete_evidence(tmp_path)
    index = evidence["quarantine_index"]
    excluded = build_source_record_descriptor_v4(
        descriptor_id="source-record-excluded-v4",
        source_id="synthetic-source-v1",
        artifact_id="synthetic-source-artifact-v1",
        record_id="source-record-1",
        raw_content=None,
        text=None,
        identifiers=[],
        dependency_units=[
            {
                "namespace": "synthetic.family",
                "value": "family-1",
                "source_version": "v1",
            }
        ],
        lineage_complete=True,
        derived_at=T4,
    )
    decision = match_quarantine_record_v4(excluded, index, checked_at=EVALUATED)
    assert decision["decision"] == "excluded"
    assert decision["features_permitted"] is False

    uncertain = build_source_record_descriptor_v4(
        descriptor_id="source-record-uncertain-v4",
        source_id="synthetic-source-v1",
        artifact_id="synthetic-source-artifact-v1",
        record_id="source-record-2",
        raw_content=b"different",
        text="different",
        identifiers=[],
        dependency_units=[],
        lineage_complete=False,
        derived_at=T4,
    )
    assert (
        match_quarantine_record_v4(uncertain, index, checked_at=EVALUATED)["decision"]
        == "undetermined"
    )

    clear = copy.deepcopy(uncertain)
    clear["descriptor_id"] = "source-record-clear-v4"
    clear["record_id"] = "source-record-3"
    clear["lineage_complete"] = True
    clear_decision = match_quarantine_record_v4(clear, index, checked_at=EVALUATED)
    assert clear_decision["decision"] == "clear"
    assert require_clear_quarantine_receipt_v4(
        clear_decision, descriptor=clear, quarantine_index=index
    )
    with pytest.raises(GateBlocked):
        require_clear_quarantine_receipt_v4(
            decision, descriptor=excluded, quarantine_index=index
        )

    forged_clear = copy.deepcopy(decision)
    forged_clear["decision"] = "clear"
    forged_clear["reasons"] = []
    forged_clear["matches"] = []
    forged_clear["features_permitted"] = True
    with pytest.raises(GateBlocked, match="not reproducible"):
        require_clear_quarantine_receipt_v4(
            forged_clear, descriptor=excluded, quarantine_index=index
        )
    with pytest.raises(ValidationError, match="predates its descriptor"):
        match_quarantine_record_v4(clear, index, checked_at=T3)


@settings(max_examples=40, deadline=None)
@given(
    st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=8,
        max_size=80,
    )
)
def test_descriptor_property_never_retains_source_text(suffix: str) -> None:
    source_text = f"private-content-{suffix}"
    descriptor = build_source_record_descriptor_v4(
        descriptor_id="property-record-v4",
        source_id="synthetic-source-v1",
        artifact_id="synthetic-source-artifact-v1",
        record_id="property-record-1",
        raw_content=source_text.encode(),
        text=source_text,
        identifiers=[],
        dependency_units=[],
        lineage_complete=True,
        derived_at=T4,
    )
    assert source_text not in repr(descriptor)
    assert descriptor["contains_features"] is False
    assert descriptor["contains_embeddings"] is False
    assert descriptor["training_authorized"] is False


def test_v4_contract_rejects_non_interoperable_fingerprint_integer() -> None:
    descriptor = build_source_record_descriptor_v4(
        descriptor_id="safe-integer-record-v4",
        source_id="synthetic-source-v1",
        artifact_id="synthetic-source-artifact-v1",
        record_id="safe-integer-record-1",
        raw_content=b"safe integers",
        text="safe integers",
        identifiers=[],
        dependency_units=[],
        lineage_complete=True,
        derived_at=T4,
    )
    descriptor["fingerprints"][0]["minhash"][0] = 2**53
    with pytest.raises(ValidationError, match="maximum"):
        validate_v4(descriptor, "quarantine-decision.schema.json")


def test_synthetic_complete_gate_is_ready_but_never_authorizes_training(
    tmp_path: Path,
) -> None:
    evidence = _complete_evidence(tmp_path)
    report = evaluate_gate_v4(**evidence)
    assert report["blockers"] == []
    assert report["foundation_acquisition_authorized"] is True
    assert report["foundation_transform_ready"] is True
    assert report["training_authorized"] is False
    assert require_phase0_transform_gate_v4(report) == canonical_sha256(report)


@pytest.mark.skipif(shutil.which("gpg") is None, reason="GnuPG is not installed")
def test_access_anchor_verifies_a_real_isolated_detached_signature(
    tmp_path: Path,
) -> None:
    evidence = _complete_evidence(tmp_path)
    seal = evidence["verified_seals"][0]
    events = next(iter(evidence["evaluation_access_events"].values()))
    gnupg_home = tmp_path / "signing-home"
    gnupg_home.mkdir(mode=0o700)
    generated = subprocess.run(
        [
            "gpg",
            "--batch",
            "--homedir",
            str(gnupg_home),
            "--passphrase",
            "",
            "--quick-generate-key",
            "Synthetic Anchor Test <anchor@example.invalid>",
            "ed25519",
            "sign",
            "1d",
        ],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if generated.returncode != 0:
        pytest.skip("GnuPG test key generation is unavailable in this environment")
    listing = subprocess.run(
        [
            "gpg",
            "--batch",
            "--homedir",
            str(gnupg_home),
            "--with-colons",
            "--list-secret-keys",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    fingerprint = next(
        line.split(":")[9].upper()
        for line in listing.stdout.splitlines()
        if line.startswith("fpr:")
    )
    public_key = subprocess.run(
        [
            "gpg",
            "--batch",
            "--homedir",
            str(gnupg_home),
            "--export",
            fingerprint,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    anchor = make_access_anchor_payload_v4(
        seal_receipt=seal.receipt,
        access_events=events,
        sequence=1,
        previous_anchor=None,
        anchored_at=T4,
        valid_until="2026-08-27T10:30:00Z",
        authority_id="synthetic-gpg-anchor",
        signing_key_fingerprint=fingerprint,
    )
    payload_path = tmp_path / "anchor.json"
    signature_path = tmp_path / "anchor.sig"
    payload_path.write_bytes(canonical_bytes(anchor))
    subprocess.run(
        [
            "gpg",
            "--batch",
            "--homedir",
            str(gnupg_home),
            "--local-user",
            fingerprint,
            "--output",
            str(signature_path),
            "--detach-sign",
            str(payload_path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    signature = signature_path.read_bytes()
    verified = verify_access_anchor_v4(
        anchor,
        signature=signature,
        public_key=public_key,
        expected_signing_key_fingerprint=fingerprint,
        access_events=events,
        seal_receipt=seal.receipt,
        evaluated_at=EVALUATED,
    )
    assert verified.signing_key_fingerprint == fingerprint
    with pytest.raises(IntegrityError):
        verify_access_anchor_v4(
            anchor,
            signature=signature[:-1] + bytes([signature[-1] ^ 1]),
            public_key=public_key,
            expected_signing_key_fingerprint=fingerprint,
            access_events=events,
            seal_receipt=seal.receipt,
            evaluated_at=EVALUATED,
        )


def test_gate_fails_closed_on_each_external_evidence_family(tmp_path: Path) -> None:
    evidence = _complete_evidence(tmp_path)
    cases = {
        "storage": ("drive_observation", None, "storage_identity_ready"),
        "publisher": ("publisher_receipts", [], "publisher_evidence_ready"),
        "rights": ("licence_assessments", [], "licensing_ready"),
        "custody": ("verified_access_anchors", {}, "confirmatory_custody_ready"),
        "quarantine": ("quarantine_index", None, "quarantine_ready"),
        "inventory": ("structural_inventories", [], "structural_inventory_ready"),
        "admission": ("admission_receipts", [], "admission_ready"),
    }
    for name, (field, replacement, readiness) in cases.items():
        candidate = dict(evidence)
        candidate[field] = replacement
        report = evaluate_gate_v4(**candidate)
        assert report[readiness] is False, name
        assert report["foundation_transform_ready"] is False, name
        assert report["training_authorized"] is False, name


def test_real_v4_gate_is_honestly_blocked() -> None:
    report = evaluate_gate_v4(
        evaluated_at="2026-08-25T00:00:00Z",
        source_registry=load_json(ROOT / "registries" / "sources.v4.pending.json"),
        source_registry_predecessor=load_json(ROOT / "registries" / "sources.v2.json"),
        evaluation_registry=load_json(ROOT / "registries" / "evaluations.v4.json"),
        evaluation_registry_predecessor=load_json(
            ROOT / "registries" / "evaluations.v2.json"
        ),
    )
    assert report["contracts_frozen"] is True
    assert report["evaluation_roles_ready"] is True
    assert report["foundation_acquisition_authorized"] is False
    assert report["foundation_transform_ready"] is False
    assert report["training_authorized"] is False
    assert report == load_json(ROOT / "audit" / "phase0-gate.v4.initial.json")
    assert {item["code"] for item in report["blockers"]} >= {
        "drive_observation_missing",
        "publisher_evidence_incomplete",
        "licensing_not_ready",
        "confirmatory_custody_not_ready",
        "quarantine_not_ready",
    }
