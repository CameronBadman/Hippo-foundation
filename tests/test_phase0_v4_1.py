from __future__ import annotations

import copy
import hashlib
import json
import warnings
import zipfile
from pathlib import Path

import pytest

from hippocampus_foundation.licensing import (
    FORBIDDEN_USES,
    build_evidence_bundle,
    verify_evidence_bundle,
)
from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.errors import (
    GateBlocked,
    IntegrityError,
    ValidationError,
)
from hippocampus_foundation.phase0.evaluation_firewall import (
    build_quarantine_contribution_v4,
    compile_quarantine_index_v4,
    make_seal_receipt_v4,
)
from hippocampus_foundation.phase0.execution_v4_1 import (
    EVALUATION_REGISTRY_ROOT_SHA256,
    SOURCE_REGISTRY_ROOT_SHA256,
    VerifiedMaterialization,
    finalize_evaluations_v4_1,
    materialize_evaluation_v4_1,
    publisher_pin_registry_v4_1,
    validate_registry_lineage_v4_1,
    verify_materialization_v4_1,
)
from hippocampus_foundation.phase0.external_evidence import (
    VerifiedAccessAnchor,
    bind_drive_observation_v4,
    build_publisher_checksum_receipt_v4,
    make_access_anchor_payload_v4,
    verify_publisher_checksum_receipt_v4,
)
from hippocampus_foundation.phase0.seal import make_access_event
from hippocampus_foundation.phase0.source_evidence_v4 import assess_admission_v4
from hippocampus_foundation.phase0.v3 import (
    EVALUATION_REQUIRED_USES,
    SOURCE_REQUIRED_USES,
)
from hippocampus_foundation.phase0.v4_1 import evaluate_gate_v4_1
from hippocampus_foundation.phase0.v4_1_contracts import validate_schema_lock_v4_1
from hippocampus_foundation.phase0.v4_contracts import (
    FROZEN_SCHEMA_DIGESTS_V4,
    validate_schema_lock_v4,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = "A" * 40
T0 = "2026-08-25T00:02:00Z"
T_PIN = "2026-08-25T00:05:00Z"
T_ASSEMBLED = "2026-08-25T00:06:00Z"
T_MATERIALIZED = "2026-08-25T00:10:00Z"
T_REVIEWED = "2026-08-25T00:09:00Z"
T_SEALED = "2026-08-25T00:13:00Z"
T_ANCHORED = "2026-08-25T00:14:00Z"
T_FINAL = "2026-08-25T00:15:00Z"
T_AUDITED = "2026-08-25T00:20:00Z"
T_INVENTORIED = "2026-08-25T00:21:00Z"
T_ADMITTED = "2026-08-25T00:30:00Z"
EVALUATED = "2026-08-25T01:00:00Z"


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _pinned_real_evaluations(
    *,
    archive_sha256: str = "sha256:" + "1" * 64,
    adapter_sha256: str = "sha256:" + "2" * 64,
) -> dict:
    root = load_json(ROOT / "registries" / "evaluations.v4.json")
    result = copy.deepcopy(root)
    result["registry_id"] = "synthetic-evaluations-v4-pinned"
    result["previous_registry_sha256"] = canonical_sha256(root)
    result["generated_at"] = T_PIN
    for entry in result["datasets"]:
        old = next(
            item
            for item in root["datasets"]
            if item["dataset_id"] == entry["dataset_id"]
        )
        entry["archive_sha256"] = archive_sha256
        entry["adapter_id"] = "synthetic-adapter-v1"
        entry["adapter_sha256"] = adapter_sha256
        entry["custody_state"] = "pinned"
        entry["previous_entry_sha256"] = canonical_sha256(old)
        if entry["usage_role"] == "confirmatory":
            entry["custodian_signing_key_fingerprint"] = KEY
        entry["blockers"] = [
            item
            for item in entry["blockers"]
            if item not in {"archive_hash_missing", "adapter_missing"}
        ]
    return result


def _single_pinned_evaluation(archive_sha256: str, adapter_sha256: str) -> dict:
    entry = {
        "dataset_id": "synthetic-confirmatory-v1",
        "task_role": "synthetic governance test",
        "usage_role": "confirmatory",
        "official_source": "private:first-party-generator",
        "resolved_version": "v1",
        "partition": "private-confirmatory",
        "archive_sha256": archive_sha256,
        "seal_id": "synthetic-confirmatory-seal-v4",
        "licence_review_id": "synthetic-evaluation-rights-v4",
        "adapter_id": "synthetic-adapter-v1",
        "adapter_sha256": adapter_sha256,
        "custody_state": "pinned",
        "project_exposure": "metadata_only",
        "confirmation_eligible": True,
        "exposure_history": [
            {
                "event_id": "synthetic-metadata-only-v4",
                "event_kind": "metadata_only",
                "recorded_at": "2026-08-25T00:00:00Z",
                "evidence_refs": ["synthetic:test"],
            }
        ],
        "blockers": [
            "human_rights_review_missing",
            "seal_missing",
            "custodian_anchor_missing",
        ],
        "dependency_units": ["synthetic.family"],
        "previous_entry_sha256": "sha256:" + "3" * 64,
        "custodian_signing_key_fingerprint": KEY,
        "quarantine_required": True,
        "training_authorized": False,
    }
    return {
        "schema_version": "4.0.0",
        "registry_kind": "evaluations",
        "registry_id": "synthetic-evaluations-v4-pinned",
        "previous_registry_sha256": "sha256:" + "4" * 64,
        "generated_at": T_PIN,
        "closure_policy_id": "quarantine-closure-v4",
        "evaluation_protocol": {"decision": "synthetic test only"},
        "datasets": [entry],
    }


def _envelope(dataset: dict, *, dependency: str = "family-1") -> dict:
    return {
        "schema_version": "4.0.0",
        "record_kind": "evaluation_envelope",
        "dataset_id": dataset["dataset_id"],
        "usage_role": dataset["usage_role"],
        "resolved_version": dataset["resolved_version"],
        "archive_sha256": dataset["archive_sha256"],
        "adapter_id": dataset["adapter_id"],
        "adapter_sha256": dataset["adapter_sha256"],
        "commitment_nonce": "9" * 64,
        "records": [
            {
                "record_id": f"{dataset['dataset_id']}.record-1",
                "selectors": {
                    "identifiers": [
                        {
                            "namespace": "synthetic.family",
                            "value": dependency,
                            "source_version": "v1",
                        }
                    ],
                    "raw_hashes": ["sha256:" + "5" * 64],
                    "normalized_hashes": [],
                    "fingerprints": [],
                },
                "expected_dependency_units": [
                    {
                        "namespace": "synthetic.family",
                        "value": dependency,
                        "source_version": "v1",
                    }
                ],
                "resolved_dependency_units": [
                    {
                        "namespace": "synthetic.family",
                        "value": dependency,
                        "source_version": "v1",
                    }
                ],
                "unresolved_dependency_units": [],
                "private_payload": {"answer": "must stay private"},
            }
        ],
        "training_authorized": False,
    }


def _inventory(archive: Path, dataset: dict) -> dict:
    return {
        "schema_version": "4.1.0",
        "record_kind": "evaluation_materialization_inventory",
        "archive_format": "raw",
        "members": [
            {
                "member_path": archive.name,
                "role": "primary",
                "primary_unit_id": f"{dataset['dataset_id']}.unit-1",
            }
        ],
        "record_primary_units": [
            {
                "record_id": f"{dataset['dataset_id']}.record-1",
                "primary_unit_ids": [f"{dataset['dataset_id']}.unit-1"],
            }
        ],
        "oracle_id": "synthetic-oracle-v1",
    }


def _materialization_fixture(
    tmp_path: Path,
) -> tuple[dict, VerifiedMaterialization, Path, Path, Path]:
    archive = tmp_path / "evaluation.raw"
    adapter = tmp_path / "adapter.py"
    oracle = tmp_path / "oracle.py"
    archive.write_bytes(b"primary evaluation unit")
    adapter.write_bytes(b"adapter-v1")
    oracle.write_bytes(b"oracle-v1")
    registry = _single_pinned_evaluation(
        _sha256_bytes(archive.read_bytes()), _sha256_bytes(adapter.read_bytes())
    )
    dataset = registry["datasets"][0]
    materialization = materialize_evaluation_v4_1(
        evaluation_registry=registry,
        dataset_id=dataset["dataset_id"],
        archive_path=archive,
        adapter_path=adapter,
        oracle_path=oracle,
        envelope=_envelope(dataset),
        inventory=_inventory(archive, dataset),
        manifest_id="synthetic-confirmatory-v1.materialization",
        materialized_at=T_MATERIALIZED,
    )
    return registry, materialization, archive, adapter, oracle


def _approved_rights(
    root: Path,
    *,
    kind: str,
    subject_id: str,
    review_id: str,
    entry: dict,
    required_uses: frozenset[str],
) -> tuple[dict, object]:
    subject_root = root / review_id
    subject_root.mkdir()
    content = f"Synthetic rights evidence for {subject_id}.".encode()
    snapshot = subject_root / "rights.snapshot"
    snapshot.write_bytes(content)
    document = {
        "document_id": "synthetic-rights-attestation",
        "role": "first_party_attestation",
        "source_kind": "local_attestation",
        "original_url": f"urn:synthetic:{review_id}",
        "resolved_url": f"urn:synthetic:{review_id}",
        "revision": "v1",
        "snapshot_path": snapshot.name,
        "media_type": "text/plain",
        "content_encoding": None,
        "byte_count": len(content),
        "sha256": _sha256_bytes(content),
        "retrieved_at": T_PIN,
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
        assembled_at=T_ASSEMBLED,
    )
    verified = verify_evidence_bundle(bundle, subject_root)
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
        "reviewer": "synthetic-reviewer",
        "reviewed_at": T_REVIEWED,
        "valid_until": "2026-08-26T00:12:00Z",
        "training_authorized": False,
        "notes": "Synthetic fixture; not a real approval.",
    }
    return assessment, verified


def _seal_graph(
    registry: dict,
    materialization: VerifiedMaterialization,
) -> tuple[object, list[dict], object]:
    dataset = next(
        item
        for item in registry["datasets"]
        if item["dataset_id"] == materialization.receipt["dataset_id"]
    )
    contribution = build_quarantine_contribution_v4(materialization.envelope)
    receipt = make_seal_receipt_v4(
        evaluation_registry=registry,
        envelope=materialization.envelope,
        contribution=contribution,
        ciphertext_sha256="sha256:" + "6" * 64,
        public_key_fingerprint=KEY,
        custodian="synthetic-custodian",
        created_at=T_SEALED,
    )
    from hippocampus_foundation.phase0.evaluation_firewall import VerifiedSealReceipt

    seal = VerifiedSealReceipt(
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        ciphertext_sha256=receipt["ciphertext_sha256"],
    )
    event = make_access_event(
        seal_id=dataset["seal_id"],
        action="seal_created",
        actor="synthetic-custodian",
        previous_hash=None,
        details={"receipt_id": canonical_sha256(materialization.receipt)},
        at=T_SEALED,
    )
    payload = make_access_anchor_payload_v4(
        seal_receipt=receipt,
        access_events=[event],
        sequence=1,
        previous_anchor=None,
        anchored_at=T_ANCHORED,
        valid_until="2026-08-25T02:00:00Z",
        authority_id="synthetic-independent-anchor",
        signing_key_fingerprint=KEY,
    )
    anchor = VerifiedAccessAnchor(
        anchor=payload,
        sha256=canonical_sha256(payload),
        signature_sha256="sha256:" + "7" * 64,
        public_key_sha256="sha256:" + "8" * 64,
        signing_key_fingerprint=KEY,
    )
    return seal, [event], anchor


def test_v4_contract_lock_is_unchanged_and_v4_1_is_separate() -> None:
    assert validate_schema_lock_v4() == FROZEN_SCHEMA_DIGESTS_V4
    assert set(validate_schema_lock_v4_1()) == {
        "execution-evidence.schema.json",
        "gate.schema.json",
    }
    v4_gate = load_json(ROOT / "schemas" / "phase0" / "v4" / "gate.schema.json")
    v4_1_gate = load_json(ROOT / "schemas" / "phase0" / "v4.1" / "gate.schema.json")
    additions = {"registry_lineage_ready", "evaluation_materialization_ready"}
    assert set(v4_1_gate["required"]) - additions == set(v4_gate["required"])
    assert set(v4_1_gate["properties"]) - additions == set(v4_gate["properties"])


def test_checked_registry_roots_and_publisher_successor_are_exact() -> None:
    source_root = load_json(ROOT / "registries" / "sources.v4.pending.json")
    evaluation_root = load_json(ROOT / "registries" / "evaluations.v4.json")
    successor = load_json(ROOT / "registries" / "sources.v4.publisher-pinned.json")
    assert canonical_sha256(source_root) == SOURCE_REGISTRY_ROOT_SHA256
    assert canonical_sha256(evaluation_root) == EVALUATION_REGISTRY_ROOT_SHA256
    assert successor["sources"] == source_root["sources"]
    assert [
        checksum["verified"]
        for source in successor["sources"]
        for artifact in source["artifacts"]
        for checksum in artifact["checksums"]
    ] == [
        checksum["verified"]
        for source in source_root["sources"]
        for artifact in source["artifacts"]
        for checksum in artifact["checksums"]
    ]
    assert all(
        item["statement_url"] is not None
        for item in successor["publisher_evidence_requirements"]
    )
    validate_registry_lineage_v4_1([source_root, successor])
    assert (
        publisher_pin_registry_v4_1(
            source_root,
            registry_id=successor["registry_id"],
            generated_at=successor["generated_at"],
        )
        == successor
    )

    reordered_requirements = copy.deepcopy(successor)
    reordered_requirements["publisher_evidence_requirements"].reverse()
    with pytest.raises(ValidationError, match="requirement order"):
        validate_registry_lineage_v4_1([source_root, reordered_requirements])


def test_lineage_rejects_forged_skipped_reordered_and_mutated_transitions() -> None:
    root = load_json(ROOT / "registries" / "evaluations.v4.json")
    pinned = _pinned_real_evaluations()
    validate_registry_lineage_v4_1([root, pinned])

    forged = copy.deepcopy(root)
    forged["registry_id"] = "forged-root"
    with pytest.raises(ValidationError, match="root mismatch"):
        validate_registry_lineage_v4_1([forged])

    skipped = copy.deepcopy(pinned)
    skipped["registry_id"] = "synthetic-evaluations-v4-skipped"
    skipped["generated_at"] = "2026-08-25T00:06:00Z"
    for entry, old in zip(skipped["datasets"], pinned["datasets"], strict=True):
        entry["previous_entry_sha256"] = canonical_sha256(old)
    skipped["previous_registry_sha256"] = canonical_sha256(root)
    with pytest.raises(ValidationError, match="missing, skipped, or reordered"):
        validate_registry_lineage_v4_1([root, pinned, skipped])
    with pytest.raises(ValidationError):
        validate_registry_lineage_v4_1([root, skipped, pinned])

    rollback = copy.deepcopy(pinned)
    rollback["generated_at"] = root["generated_at"]
    with pytest.raises(ValidationError, match="strictly increase"):
        validate_registry_lineage_v4_1([root, rollback])

    for field, replacement in (
        ("archive_sha256", "sha256:" + "a" * 64),
        ("custodian_signing_key_fingerprint", "B" * 40),
        ("seal_id", "changed-seal-v4"),
        ("dependency_units", ["changed.family"]),
    ):
        changed = copy.deepcopy(pinned)
        changed["registry_id"] = f"changed-{field}"
        changed["previous_registry_sha256"] = canonical_sha256(pinned)
        changed["generated_at"] = "2026-08-25T00:06:00Z"
        for entry, old in zip(changed["datasets"], pinned["datasets"], strict=True):
            entry["previous_entry_sha256"] = canonical_sha256(old)
        target = next(
            item for item in changed["datasets"] if item["usage_role"] == "confirmatory"
        )
        target[field] = replacement
        with pytest.raises(ValidationError):
            validate_registry_lineage_v4_1([root, pinned, changed])

    arbitrary = copy.deepcopy(pinned)
    arbitrary["registry_id"] = "synthetic-evaluations-v4-arbitrary-blocker"
    arbitrary["previous_registry_sha256"] = canonical_sha256(pinned)
    arbitrary["generated_at"] = "2026-08-25T00:06:00Z"
    for entry, old in zip(arbitrary["datasets"], pinned["datasets"], strict=True):
        entry["previous_entry_sha256"] = canonical_sha256(old)
    arbitrary["datasets"][0]["blockers"].append("unrecognized_blocker")
    with pytest.raises(ValidationError, match="recognized evidence family"):
        validate_registry_lineage_v4_1([root, pinned, arbitrary])


def test_materialization_rehashes_every_asset_and_receipt_does_not_leak(
    tmp_path: Path,
) -> None:
    registry, materialization, archive, adapter, oracle = _materialization_fixture(
        tmp_path
    )
    receipt_text = json.dumps(materialization.receipt).casefold()
    for marker in (
        "member_path",
        "record_id",
        "primary_unit_id",
        "private_payload",
        "commitment_nonce",
        "must stay private",
        "family-1",
    ):
        assert marker not in receipt_text
    assert materialization.receipt["complete_primary_unit_coverage"] is True
    verify_materialization_v4_1(
        manifest=materialization.manifest,
        receipt=materialization.receipt,
        evaluation_registry=registry,
        archive_path=archive,
        adapter_path=adapter,
        oracle_path=oracle,
        envelope=materialization.envelope,
    )
    for path in (archive, adapter, oracle):
        original = path.read_bytes()
        path.write_bytes(original + b"mutation")
        with pytest.raises((IntegrityError, ValidationError)):
            verify_materialization_v4_1(
                manifest=materialization.manifest,
                receipt=materialization.receipt,
                evaluation_registry=registry,
                archive_path=archive,
                adapter_path=adapter,
                oracle_path=oracle,
                envelope=materialization.envelope,
            )
        path.write_bytes(original)

    oracle.write_bytes(adapter.read_bytes())
    with pytest.raises(IntegrityError, match="byte-distinct"):
        materialize_evaluation_v4_1(
            evaluation_registry=registry,
            dataset_id=registry["datasets"][0]["dataset_id"],
            archive_path=archive,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=materialization.envelope,
            inventory=_inventory(archive, registry["datasets"][0]),
            manifest_id="aliased-oracle.materialization",
            materialized_at=T_MATERIALIZED,
        )

    oracle.write_bytes(b"oracle-v1")
    aliased_identity = _inventory(archive, registry["datasets"][0])
    aliased_identity["oracle_id"] = registry["datasets"][0]["adapter_id"]
    with pytest.raises(ValidationError, match="identity distinct"):
        materialize_evaluation_v4_1(
            evaluation_registry=registry,
            dataset_id=registry["datasets"][0]["dataset_id"],
            archive_path=archive,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=materialization.envelope,
            inventory=aliased_identity,
            manifest_id="aliased-oracle-id.materialization",
            materialized_at=T_MATERIALIZED,
        )


def test_materialization_rejects_unsafe_unaccounted_and_incomplete_archives(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.json", b"secret")
    adapter = tmp_path / "adapter.py"
    oracle = tmp_path / "oracle.py"
    adapter.write_bytes(b"adapter")
    oracle.write_bytes(b"oracle")
    registry = _single_pinned_evaluation(
        _sha256_bytes(archive.read_bytes()), _sha256_bytes(adapter.read_bytes())
    )
    dataset = registry["datasets"][0]
    inventory = _inventory(archive, dataset)
    inventory["archive_format"] = "zip"
    inventory["members"][0]["member_path"] = "escape.json"
    with pytest.raises(IntegrityError, match="unsafe archive member"):
        materialize_evaluation_v4_1(
            evaluation_registry=registry,
            dataset_id=dataset["dataset_id"],
            archive_path=archive,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=_envelope(dataset),
            inventory=inventory,
            manifest_id="unsafe.materialization",
            materialized_at=T_MATERIALIZED,
        )

    safe = tmp_path / "accounting.zip"
    with zipfile.ZipFile(safe, "w") as handle:
        handle.writestr("primary.json", b"primary")
        handle.writestr("unaccounted.json", b"extra")
    registry = _single_pinned_evaluation(
        _sha256_bytes(safe.read_bytes()), _sha256_bytes(adapter.read_bytes())
    )
    dataset = registry["datasets"][0]
    inventory = _inventory(safe, dataset)
    inventory["archive_format"] = "zip"
    inventory["members"][0]["member_path"] = "primary.json"
    with pytest.raises(IntegrityError, match="unaccounted"):
        materialize_evaluation_v4_1(
            evaluation_registry=registry,
            dataset_id=dataset["dataset_id"],
            archive_path=safe,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=_envelope(dataset),
            inventory=inventory,
            manifest_id="unaccounted.materialization",
            materialized_at=T_MATERIALIZED,
        )

    accounted = copy.deepcopy(inventory)
    accounted["members"].append(
        {
            "member_path": "unaccounted.json",
            "role": "support",
            "primary_unit_id": None,
        }
    )
    accounted["members"].reverse()
    normalized_materialization = materialize_evaluation_v4_1(
        evaluation_registry=registry,
        dataset_id=dataset["dataset_id"],
        archive_path=safe,
        adapter_path=adapter,
        oracle_path=oracle,
        envelope=_envelope(dataset),
        inventory=accounted,
        manifest_id="normalized-inventory.materialization",
        materialized_at=T_MATERIALIZED,
    )
    verify_materialization_v4_1(
        manifest=normalized_materialization.manifest,
        receipt=normalized_materialization.receipt,
        evaluation_registry=registry,
        archive_path=safe,
        adapter_path=adapter,
        oracle_path=oracle,
        envelope=normalized_materialization.envelope,
    )

    complete = copy.deepcopy(inventory)
    complete["members"].append(
        {
            "member_path": "unaccounted.json",
            "role": "primary",
            "primary_unit_id": "uncovered.unit",
        }
    )
    with pytest.raises(ValidationError, match="coverage is incomplete"):
        materialize_evaluation_v4_1(
            evaluation_registry=registry,
            dataset_id=dataset["dataset_id"],
            archive_path=safe,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=_envelope(dataset),
            inventory=complete,
            manifest_id="incomplete.materialization",
            materialized_at=T_MATERIALIZED,
        )

    orphaned = copy.deepcopy(complete)
    orphaned["record_primary_units"] = [
        {
            "record_id": "orphan-output",
            "primary_unit_ids": [
                f"{dataset['dataset_id']}.unit-1",
                "uncovered.unit",
            ],
        }
    ]
    with pytest.raises(ValidationError, match="orphaned"):
        materialize_evaluation_v4_1(
            evaluation_registry=registry,
            dataset_id=dataset["dataset_id"],
            archive_path=safe,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=_envelope(dataset),
            inventory=orphaned,
            manifest_id="orphaned.materialization",
            materialized_at=T_MATERIALIZED,
        )

    duplicate = tmp_path / "duplicate.zip"
    with warnings.catch_warnings(), zipfile.ZipFile(duplicate, "w") as handle:
        warnings.simplefilter("ignore", UserWarning)
        handle.writestr("primary.json", b"first")
        handle.writestr("primary.json", b"second")
    duplicate_registry = _single_pinned_evaluation(
        _sha256_bytes(duplicate.read_bytes()), _sha256_bytes(adapter.read_bytes())
    )
    duplicate_dataset = duplicate_registry["datasets"][0]
    duplicate_inventory = _inventory(duplicate, duplicate_dataset)
    duplicate_inventory["archive_format"] = "zip"
    duplicate_inventory["members"][0]["member_path"] = "primary.json"
    with pytest.raises(IntegrityError, match="duplicate archive member"):
        materialize_evaluation_v4_1(
            evaluation_registry=duplicate_registry,
            dataset_id=duplicate_dataset["dataset_id"],
            archive_path=duplicate,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=_envelope(duplicate_dataset),
            inventory=duplicate_inventory,
            manifest_id="duplicate.materialization",
            materialized_at=T_MATERIALIZED,
        )


def test_finalization_requires_evidence_bound_blocker_clearing(tmp_path: Path) -> None:
    registry, materialization, *_ = _materialization_fixture(tmp_path)
    dataset = registry["datasets"][0]
    assessment, bundle = _approved_rights(
        tmp_path,
        kind="evaluation",
        subject_id=dataset["dataset_id"],
        review_id=dataset["licence_review_id"],
        entry=dataset,
        required_uses=EVALUATION_REQUIRED_USES,
    )
    seal, events, anchor = _seal_graph(registry, materialization)
    final = finalize_evaluations_v4_1(
        pinned_registry=registry,
        materializations=[materialization],
        licence_assessments=[assessment],
        verified_bundles={assessment["review_id"]: bundle},
        verified_seals=[seal],
        access_events={dataset["seal_id"]: events},
        verified_access_anchors={dataset["seal_id"]: anchor},
        registry_id="synthetic-evaluations-v4-final",
        generated_at=T_FINAL,
    )
    assert final["datasets"][0]["custody_state"] == "sealed"
    assert final["datasets"][0]["blockers"] == []

    consumed_event = make_access_event(
        seal_id=dataset["seal_id"],
        action="consume",
        actor="synthetic-custodian",
        previous_hash=events[0]["event_hash"],
        details={"request_id": "synthetic-consumption"},
        at="2026-08-25T00:13:30Z",
    )
    consumed_payload = make_access_anchor_payload_v4(
        seal_receipt=seal.receipt,
        access_events=[*events, consumed_event],
        sequence=1,
        previous_anchor=None,
        anchored_at=T_ANCHORED,
        valid_until="2026-08-25T02:00:00Z",
        authority_id="synthetic-independent-anchor",
        signing_key_fingerprint=KEY,
    )
    consumed_anchor = VerifiedAccessAnchor(
        anchor=consumed_payload,
        sha256=canonical_sha256(consumed_payload),
        signature_sha256="sha256:" + "7" * 64,
        public_key_sha256="sha256:" + "8" * 64,
        signing_key_fingerprint=KEY,
    )
    with pytest.raises(GateBlocked, match="consumed"):
        finalize_evaluations_v4_1(
            pinned_registry=registry,
            materializations=[materialization],
            licence_assessments=[assessment],
            verified_bundles={assessment["review_id"]: bundle},
            verified_seals=[seal],
            access_events={dataset["seal_id"]: [*events, consumed_event]},
            verified_access_anchors={dataset["seal_id"]: consumed_anchor},
            registry_id="synthetic-evaluations-v4-consumed",
            generated_at=T_FINAL,
        )

    stale_payload = make_access_anchor_payload_v4(
        seal_receipt=seal.receipt,
        access_events=events,
        sequence=1,
        previous_anchor=None,
        anchored_at=T_ANCHORED,
        valid_until="2026-08-25T00:14:30Z",
        authority_id="synthetic-independent-anchor",
        signing_key_fingerprint=KEY,
    )
    stale_anchor = VerifiedAccessAnchor(
        anchor=stale_payload,
        sha256=canonical_sha256(stale_payload),
        signature_sha256="sha256:" + "7" * 64,
        public_key_sha256="sha256:" + "8" * 64,
        signing_key_fingerprint=KEY,
    )
    with pytest.raises(ValidationError, match="stale or invalid"):
        finalize_evaluations_v4_1(
            pinned_registry=registry,
            materializations=[materialization],
            licence_assessments=[assessment],
            verified_bundles={assessment["review_id"]: bundle},
            verified_seals=[seal],
            access_events={dataset["seal_id"]: events},
            verified_access_anchors={dataset["seal_id"]: stale_anchor},
            registry_id="synthetic-evaluations-v4-stale-anchor",
            generated_at=T_FINAL,
        )

    unsupported = copy.deepcopy(registry)
    unsupported["datasets"][0]["blockers"].append("unproven_blocker")
    # Changing the pinned blocker set invalidates every pinned-entry evidence
    # binding before finalization can even consider clearing it.
    with pytest.raises((GateBlocked, ValidationError)):
        finalize_evaluations_v4_1(
            pinned_registry=unsupported,
            materializations=[materialization],
            licence_assessments=[assessment],
            verified_bundles={assessment["review_id"]: bundle},
            verified_seals=[seal],
            access_events={dataset["seal_id"]: events},
            verified_access_anchors={dataset["seal_id"]: anchor},
            registry_id="synthetic-evaluations-v4-invalid",
            generated_at=T_FINAL,
        )
    with pytest.raises(ValidationError, match="follow every supplied evidence"):
        finalize_evaluations_v4_1(
            pinned_registry=registry,
            materializations=[materialization],
            licence_assessments=[assessment],
            verified_bundles={assessment["review_id"]: bundle},
            verified_seals=[seal],
            access_events={dataset["seal_id"]: events},
            verified_access_anchors={dataset["seal_id"]: anchor},
            registry_id="synthetic-evaluations-v4-premature",
            generated_at=T_ANCHORED,
        )


def _drive_observation() -> dict:
    return {
        "schema_version": "1.0.0",
        "record_kind": "drive_identity_observation",
        "observed_at": T0,
        "requested_scope": "https://www.googleapis.com/auth/drive.readonly",
        "scope_exact": True,
        "same_account_human_attested": True,
        "principal_permission_id_sha256": "sha256:" + "a" * 64,
        "provider": "google_drive_shared_drive",
        "provider_resource_id": "synthetic-shared-drive-id",
        "root_resource_id": "synthetic-root-folder-id",
        "observed_root": "/content/drive/Shareddrives/Data/graph-memory-data-lake",
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


def _synthetic_source_evidence(
    tmp_path: Path,
) -> tuple[list[dict], dict, list[object], dict, list[dict], list[dict], dict, dict]:
    source_root = load_json(ROOT / "registries" / "sources.v4.pending.json")
    publisher_pinned = load_json(
        ROOT / "registries" / "sources.v4.publisher-pinned.json"
    )
    observation = _drive_observation()
    sources, attestation = bind_drive_observation_v4(
        publisher_pinned,
        observation,
        registry_id="synthetic-sources-v4-drive-bound",
        verifier="synthetic-storage-verifier",
        bound_at=T0,
    )
    publisher_receipts = []
    for requirement in sources["publisher_evidence_requirements"]:
        source = next(
            item
            for item in sources["sources"]
            if item["source_id"] == requirement["source_id"]
        )
        artifact = next(
            item
            for item in source["artifacts"]
            if item["artifact_id"] == requirement["artifact_id"]
        )
        checksum = next(
            item
            for item in artifact["checksums"]
            if item["origin"] == "publisher" and item["algorithm"] == "sha1"
        )
        statement = f"{checksum['value']}  {Path(artifact['filename']).name}\n".encode()
        receipt = build_publisher_checksum_receipt_v4(
            source_registry=sources,
            evidence_id=requirement["evidence_id"],
            statement=statement,
            resolved_url=requirement["statement_url"],
            retrieved_at="2026-08-25T00:03:00Z",
            verified_at="2026-08-25T00:03:00Z",
            verifier="synthetic-publisher-verifier",
        )
        publisher_receipts.append(
            verify_publisher_checksum_receipt_v4(
                receipt, statement, sources, evaluated_at=EVALUATED
            )
        )

    rows = []
    for source_index, source in enumerate(sources["sources"], start=1):
        for artifact_index, artifact in enumerate(source["artifacts"], start=1):
            seed = artifact["artifact_id"].encode()
            sha1 = next(
                item["value"]
                for item in artifact["checksums"]
                if item["algorithm"] == "sha1"
            )
            rows.append(
                {
                    "source_id": source["source_id"],
                    "artifact_id": artifact["artifact_id"],
                    "locator_id": artifact["locator_id"],
                    "filename": artifact["filename"],
                    "measured": {
                        "bytes": artifact["expected_bytes"],
                        "md5": hashlib.md5(seed, usedforsecurity=False).hexdigest(),
                        "sha1": sha1,
                        "sha256": hashlib.sha256(seed).hexdigest(),
                        "device": str(source_index),
                        "inode": str(artifact_index),
                        "mtime_ns": "1",
                    },
                    "status": "verified",
                    "mismatches": [],
                }
            )
    source_audit = {
        "schema_version": "4.0.0",
        "record_kind": "source_audit",
        "registry_id": sources["registry_id"],
        "registry_sha256": canonical_sha256(sources),
        "storage_attestation_sha256": canonical_sha256(attestation),
        "publisher_receipt_sha256s": sorted(item.sha256 for item in publisher_receipts),
        "started_at": "2026-08-25T00:19:00Z",
        "completed_at": T_AUDITED,
        "artifact_count": len(rows),
        "total_bytes": sum(row["measured"]["bytes"] for row in rows),
        "all_verified": True,
        "artifacts": rows,
        "training_authorized": False,
    }
    publisher_by_artifact = {
        item.receipt["artifact_id"]: item for item in publisher_receipts
    }
    row_by_artifact = {item["artifact_id"]: item for item in rows}
    inventories = []
    for source in sources["sources"]:
        for artifact in source["artifacts"]:
            row = row_by_artifact[artifact["artifact_id"]]
            inventories.append(
                {
                    "schema_version": "4.0.0",
                    "record_kind": "structural_inventory",
                    "source_id": source["source_id"],
                    "artifact_id": artifact["artifact_id"],
                    "registry_sha256": canonical_sha256(sources),
                    "source_audit_sha256": canonical_sha256(source_audit),
                    "storage_attestation_sha256": canonical_sha256(attestation),
                    "publisher_receipt_sha256": publisher_by_artifact[
                        artifact["artifact_id"]
                    ].sha256,
                    "artifact_sha256": f"sha256:{row['measured']['sha256']}",
                    "artifact_bytes": artifact["expected_bytes"],
                    "counter_kind": artifact["inventory_kind"],
                    "counter_version": "hf-stream-counter-v4",
                    "started_at": T_AUDITED,
                    "completed_at": T_INVENTORIED,
                    "complete": True,
                    "parse_errors": 0,
                    "rejected_records": 0,
                    "counters": {
                        name: 1 for name in artifact["required_nonzero_counters"]
                    },
                    "training_authorized": False,
                }
            )
    return (
        [source_root, publisher_pinned, sources],
        observation,
        publisher_receipts,
        source_audit,
        inventories,
        [],
        sources,
        attestation,
    )


def _complete_v4_1_graph(tmp_path: Path) -> dict:
    (
        source_registries,
        observation,
        publisher_receipts,
        source_audit,
        inventories,
        _,
        sources,
        attestation,
    ) = _synthetic_source_evidence(tmp_path)

    archive = tmp_path / "all-evaluations.raw"
    adapter = tmp_path / "all-evaluations.adapter"
    oracle = tmp_path / "all-evaluations.oracle"
    archive.write_bytes(b"synthetic primary unit for every evaluation")
    adapter.write_bytes(b"synthetic adapter")
    oracle.write_bytes(b"synthetic independent oracle")
    evaluation_root = load_json(ROOT / "registries" / "evaluations.v4.json")
    pinned = _pinned_real_evaluations(
        archive_sha256=_sha256_bytes(archive.read_bytes()),
        adapter_sha256=_sha256_bytes(adapter.read_bytes()),
    )

    materializations = []
    contributions = []
    for dataset in pinned["datasets"]:
        envelope = _envelope(dataset, dependency=f"{dataset['dataset_id']}.family")
        materialization = materialize_evaluation_v4_1(
            evaluation_registry=pinned,
            dataset_id=dataset["dataset_id"],
            archive_path=archive,
            adapter_path=adapter,
            oracle_path=oracle,
            envelope=envelope,
            inventory=_inventory(archive, dataset),
            manifest_id=f"{dataset['dataset_id']}.materialization",
            materialized_at=T_MATERIALIZED,
        )
        materializations.append(materialization)
        contributions.append(build_quarantine_contribution_v4(envelope))
    quarantine = compile_quarantine_index_v4(
        contributions,
        expected_dataset_ids=[item["dataset_id"] for item in pinned["datasets"]],
    )

    assessments = []
    bundles = {}
    for source in sources["sources"]:
        assessment, bundle = _approved_rights(
            tmp_path,
            kind="source",
            subject_id=source["source_id"],
            review_id=source["licence_review_id"],
            entry=source,
            required_uses=SOURCE_REQUIRED_USES,
        )
        assessments.append(assessment)
        bundles[assessment["review_id"]] = bundle
    evaluation_assessments = []
    evaluation_bundles = {}
    for dataset in pinned["datasets"]:
        assessment, bundle = _approved_rights(
            tmp_path,
            kind="evaluation",
            subject_id=dataset["dataset_id"],
            review_id=dataset["licence_review_id"],
            entry=dataset,
            required_uses=EVALUATION_REQUIRED_USES,
        )
        assessments.append(assessment)
        evaluation_assessments.append(assessment)
        bundles[assessment["review_id"]] = bundle
        evaluation_bundles[assessment["review_id"]] = bundle

    seals = []
    access_events = {}
    anchors = {}
    materialization_by_id = {
        item.receipt["dataset_id"]: item for item in materializations
    }
    for dataset in pinned["datasets"]:
        if dataset["usage_role"] != "confirmatory":
            continue
        seal, events, anchor = _seal_graph(
            pinned, materialization_by_id[dataset["dataset_id"]]
        )
        seals.append(seal)
        access_events[dataset["seal_id"]] = events
        anchors[dataset["seal_id"]] = anchor
    final = finalize_evaluations_v4_1(
        pinned_registry=pinned,
        materializations=materializations,
        licence_assessments=evaluation_assessments,
        verified_bundles=evaluation_bundles,
        verified_seals=seals,
        access_events=access_events,
        verified_access_anchors=anchors,
        registry_id="synthetic-evaluations-v4-final",
        generated_at=T_FINAL,
    )

    publisher_by_artifact = {
        item.receipt["artifact_id"]: item for item in publisher_receipts
    }
    inventory_by_artifact = {item["artifact_id"]: item for item in inventories}
    assessment_by_review = {item["review_id"]: item for item in assessments}
    admissions = []
    for source in sources["sources"]:
        artifact_ids = {item["artifact_id"] for item in source["artifacts"]}
        review_id = source["licence_review_id"]
        admissions.append(
            assess_admission_v4(
                source_id=source["source_id"],
                source_registry=sources,
                evaluation_registry=final,
                storage_attestation=attestation,
                source_audit=source_audit,
                publisher_receipts=[
                    publisher_by_artifact[item] for item in artifact_ids
                ],
                assessment=assessment_by_review[review_id],
                verified_bundle=bundles[review_id],
                inventories=[inventory_by_artifact[item] for item in artifact_ids],
                quarantine_index=quarantine,
                assessor="synthetic-admission-assessor",
                assessed_at=T_ADMITTED,
            )
        )
    return {
        "evaluated_at": EVALUATED,
        "source_registries": source_registries,
        "evaluation_registries": [evaluation_root, pinned, final],
        "drive_observation": observation,
        "storage_attestation": attestation,
        "publisher_receipts": publisher_receipts,
        "source_audit": source_audit,
        "licence_assessments": assessments,
        "verified_bundles": bundles,
        "materializations": materializations,
        "quarantine_contributions": contributions,
        "quarantine_index": quarantine,
        "verified_seals": seals,
        "evaluation_access_events": access_events,
        "verified_access_anchors": anchors,
        "structural_inventories": inventories,
        "admission_receipts": admissions,
    }


def test_complete_synthetic_v4_1_graph_reaches_transform_only(tmp_path: Path) -> None:
    evidence = _complete_v4_1_graph(tmp_path)
    report = evaluate_gate_v4_1(**evidence)
    assert report["blockers"] == []
    assert report["registry_lineage_ready"] is True
    assert report["evaluation_materialization_ready"] is True
    assert report["foundation_acquisition_authorized"] is True
    assert report["foundation_transform_ready"] is True
    assert report["training_authorized"] is False

    without_materialization = dict(evidence)
    without_materialization["materializations"] = []
    assert (
        evaluate_gate_v4_1(**without_materialization)[
            "foundation_acquisition_authorized"
        ]
        is False
    )
    without_source_root = dict(evidence)
    without_source_root["source_registries"] = evidence["source_registries"][1:]
    assert evaluate_gate_v4_1(**without_source_root)["registry_lineage_ready"] is False
    without_evaluation_root = dict(evidence)
    without_evaluation_root["evaluation_registries"] = evidence[
        "evaluation_registries"
    ][1:]
    assert (
        evaluate_gate_v4_1(**without_evaluation_root)["registry_lineage_ready"] is False
    )
