from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hippocampus_foundation.phase0.canonical import canonical_sha256, sha256_bytes
from hippocampus_foundation.phase0.cli import build_parser
from hippocampus_foundation.phase0.errors import QuarantineError, ValidationError
from hippocampus_foundation.phase0.inventory import hash_file
from hippocampus_foundation.phase0.quarantine import fingerprint_text
from hippocampus_foundation.phase0.seal import make_access_event
from hippocampus_foundation.phase0.v2 import (
    PUBLIC_EVALUATION_DATASETS_V2,
    assess_admission_v2,
    audit_source_registry_v2,
    build_quarantine_contribution_v2,
    build_structural_inventory_v2,
    compile_quarantine_index_v2,
    evaluate_gate_v2,
    make_seal_receipt_v2,
    validate_evaluation_registry_v2,
    validate_schema_lock_v2,
    validate_source_registry_v2,
    validate_storage_attestation_v2,
    verify_licence_review_v2,
)

ROOT = Path(__file__).resolve().parents[1]
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat().replace("+00:00", "Z")


def identifier(value: str = "Q42") -> dict:
    return {
        "namespace": "wikidata.entity",
        "value": value,
        "source_version": "fixture-v1",
    }


def envelope(dataset_id: str, seal_id: str) -> dict:
    dependency = identifier()
    return {
        "schema_version": "2.0.0",
        "record_kind": "evaluation_envelope",
        "seal_id": seal_id,
        "dataset_id": dataset_id,
        "resolved_version": "fixture-revision",
        "archive_sha256": SHA_A,
        "adapter_id": "fixture-adapter-v1",
        "adapter_sha256": SHA_B,
        "records": [
            {
                "record_id": f"{dataset_id}-record-1",
                "selectors": {
                    "identifiers": [dependency],
                    "raw_hashes": [],
                    "normalized_hashes": [],
                    "fingerprints": [],
                },
                "expected_dependency_units": [dependency],
                "resolved_dependency_units": [dependency],
                "unresolved_dependency_units": [],
                "private_payload": {"label": "held-out"},
            }
        ],
    }


def licence_review(
    *, review_id: str, subject_kind: str, subject_id: str, terms: bytes
) -> dict:
    uses = (
        ["acquire", "inventory", "quarantine", "transform", "embed"]
        if subject_kind == "source"
        else ["acquire", "quarantine", "evaluate"]
    )
    return {
        "schema_version": "2.0.0",
        "record_kind": "licence_review",
        "review_id": review_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "licence_id": "fixture-licence",
        "original_terms_url": "https://example.test/original",
        "resolved_terms_url": "https://example.test/resolved",
        "terms_snapshot_sha256": sha256_bytes(terms),
        "retrieved_at": "2026-08-16T00:00:00Z",
        "decision": "approved",
        "commercial_use": "allowed",
        "intended_uses": uses,
        "reviewer": "fixture-human-reviewer",
        "reviewed_at": "2026-08-16T01:00:00Z",
    }


def ready_evaluation_evidence() -> tuple[
    dict,
    list[dict],
    list[dict],
    dict,
    list[dict],
    dict[str, str],
    dict[str, list[dict]],
    dict[str, str],
]:
    datasets = []
    contributions = []
    receipts = []
    reviews = []
    verified_terms: dict[str, str] = {}
    access_events: dict[str, list[dict]] = {}
    access_heads: dict[str, str] = {}
    for dataset_id in sorted(PUBLIC_EVALUATION_DATASETS_V2):
        seal_id = f"{dataset_id}-fixture-seal"
        private = envelope(dataset_id, seal_id)
        contribution = build_quarantine_contribution_v2(private)
        receipt = make_seal_receipt_v2(
            envelope=private,
            contribution=contribution,
            ciphertext_sha256=SHA_C,
            public_key_fingerprint="A" * 40,
            custodian="fixture-custodian",
            created_at="2026-08-16T02:00:00Z",
        )
        review_id = f"{dataset_id}-rights"
        terms = f"terms for {dataset_id}".encode()
        review = licence_review(
            review_id=review_id,
            subject_kind="evaluation",
            subject_id=dataset_id,
            terms=terms,
        )
        datasets.append(
            {
                "dataset_id": dataset_id,
                "role": "confirmatory fixture",
                "official_source": "https://example.test/dataset",
                "resolved_version": private["resolved_version"],
                "partition": "held-out",
                "archive_sha256": private["archive_sha256"],
                "seal_id": seal_id,
                "licence_review_id": review_id,
                "adapter_id": private["adapter_id"],
                "adapter_sha256": private["adapter_sha256"],
                "status": "sealed",
                "blockers": [],
                "dependency_units": ["entity_family"],
            }
        )
        contributions.append(contribution)
        receipts.append(receipt)
        reviews.append(review)
        verified_terms[review_id] = sha256_bytes(terms)
        event = make_access_event(
            seal_id=seal_id,
            action="seal_created",
            actor="fixture-custodian",
            previous_hash=None,
        )
        access_events[seal_id] = [event]
        access_heads[seal_id] = event["event_hash"]
    registry = {
        "schema_version": "2.0.0",
        "registry_kind": "evaluations",
        "registry_id": "fixture-evaluations-v2",
        "generated_at": "2026-08-16T00:00:00Z",
        "evaluation_protocol": {"decision": "fixture only"},
        "datasets": datasets,
        "closure_policy_id": "quarantine-closure-v2",
    }
    quarantine = compile_quarantine_index_v2(contributions)
    return (
        registry,
        contributions,
        receipts,
        quarantine,
        reviews,
        verified_terms,
        access_events,
        access_heads,
    )


def ready_source_evidence(tmp_path: Path) -> tuple[dict, dict, dict, dict, bytes, dict]:
    artifact_path = tmp_path / "fixture-wikidata.json"
    artifact_path.write_text(
        '[\n{"id":"Q42","type":"item","sitelinks":{"enwiki":{}},'
        '"claims":{"P31":[{"rank":"normal","mainsnak":{"datatype":"wikibase-item"},'
        '"qualifiers":{"P580":[{}]},"references":[{}]}]}}\n]\n',
        encoding="utf-8",
    )
    measured = hash_file(artifact_path)
    registry = {
        "schema_version": "2.0.0",
        "registry_kind": "sources",
        "registry_id": "fixture-sources-v2",
        "generated_at": "2026-08-16T00:00:00Z",
        "storage_requirements": [
            {
                "locator_id": "fixture_drive",
                "provider": "google_drive_shared_drive",
                "provider_resource_id": "shared-drive-id",
                "root_resource_id": "root-folder-id",
                "required_root": str(tmp_path),
            }
        ],
        "sources": [
            {
                "source_id": "wikidata@fixture",
                "publisher": "fixture publisher",
                "version": "fixture-v1",
                "snapshot_at": "2026-08-16T00:00:00Z",
                "role": "foundation_candidate",
                "admission_status": "pending",
                "licence_review_id": "wikidata-fixture-rights",
                "quarantine_required": True,
                "artifacts": [
                    {
                        "artifact_id": "wikidata-fixture-json",
                        "locator_id": "fixture_drive",
                        "filename": artifact_path.name,
                        "source_url": "https://example.test/wikidata.json",
                        "media_type": "application/json",
                        "compression": "none",
                        "expected_bytes": measured["bytes"],
                        "checksums": [
                            {
                                "algorithm": "sha256",
                                "value": measured["sha256"],
                                "origin": "publisher",
                                "verified": True,
                            }
                        ],
                        "raw_policy": "immutable",
                        "integrity_status": "verified",
                        "availability": "preexisting",
                        "inventory_kind": "wikidata_json",
                        "required_nonzero_counters": [
                            "entities",
                            "statements",
                            "sitelinks",
                            "qualifiers",
                            "references",
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
    attestation = {
        "schema_version": "2.0.0",
        "record_kind": "storage_attestation",
        "locator_id": "fixture_drive",
        "provider": "google_drive_shared_drive",
        "provider_resource_id": "shared-drive-id",
        "root_resource_id": "root-folder-id",
        "observed_root": str(tmp_path),
        "observed_at": timestamp(),
        "method": "google_drive_api_v3_authenticated",
        "verifier": "fixture-verifier",
    }
    audit = audit_source_registry_v2(registry, attestation)
    terms = b"fixture source terms"
    review = licence_review(
        review_id="wikidata-fixture-rights",
        subject_kind="source",
        subject_id="wikidata@fixture",
        terms=terms,
    )
    inventory = build_structural_inventory_v2(
        registry=registry,
        attestation=attestation,
        source_audit=audit,
        artifact_id="wikidata-fixture-json",
    )
    return registry, attestation, audit, review, terms, inventory


def test_v2_schema_lock_and_checked_in_registries() -> None:
    assert set(validate_schema_lock_v2()) == {
        "control-evidence.schema.json",
        "evaluation-evidence.schema.json",
        "gate.schema.json",
        "registry.schema.json",
    }
    validate_source_registry_v2(load("registries/sources.v2.json"))
    validate_evaluation_registry_v2(load("registries/evaluations.v2.json"))


def test_schema_lock_detects_byte_independent_semantic_change(tmp_path: Path) -> None:
    copied = tmp_path / "schemas"
    shutil.copytree(ROOT / "schemas/phase0/v2", copied)
    path = copied / "gate.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["title"] = "tampered title"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ValidationError, match="changed=\\['gate.schema.json'\\]"):
        validate_schema_lock_v2(copied)


def test_storage_attestation_binds_ids_and_freshness(tmp_path: Path) -> None:
    registry, attestation, *_ = ready_source_evidence(tmp_path)
    evaluated = datetime.now(UTC)
    validate_storage_attestation_v2(
        attestation, registry, evaluated_at=timestamp(evaluated + timedelta(seconds=1))
    )

    wrong = copy.deepcopy(attestation)
    wrong["root_resource_id"] = "wrong-folder-id"
    with pytest.raises(ValidationError, match="root_resource_id mismatch"):
        validate_storage_attestation_v2(wrong, registry)

    stale = copy.deepcopy(attestation)
    stale["observed_at"] = timestamp(evaluated - timedelta(hours=73))
    with pytest.raises(ValidationError, match="stale"):
        validate_storage_attestation_v2(
            stale, registry, evaluated_at=timestamp(evaluated)
        )


def test_licence_decision_is_bound_to_exact_terms() -> None:
    terms = b"commercial use is allowed for this fixture"
    review = licence_review(
        review_id="fixture-rights",
        subject_kind="source",
        subject_id="fixture-source",
        terms=terms,
    )
    verify_licence_review_v2(review, terms)
    with pytest.raises(ValidationError, match="digest mismatch"):
        verify_licence_review_v2(review, terms + b" changed")


def test_quarantine_contribution_is_derived_per_record_and_public() -> None:
    private = envelope("vitaminc", "vitaminc-fixture-seal")
    contribution = build_quarantine_contribution_v2(private)
    assert contribution["coverage"]["record_count"] == len(private["records"]) == 1
    assert contribution["coverage"]["selector_count"] == 1
    rendered = json.dumps(contribution).casefold()
    assert "private_payload" not in rendered
    assert '"label"' not in rendered

    unresolved = copy.deepcopy(private)
    unresolved["records"][0]["unresolved_dependency_units"] = ["missing family"]
    with pytest.raises(QuarantineError, match="unresolved dependencies"):
        build_quarantine_contribution_v2(unresolved)

    uncovered = copy.deepcopy(private)
    uncovered["records"][0]["selectors"]["identifiers"] = []
    with pytest.raises(QuarantineError, match="no quarantine selector"):
        build_quarantine_contribution_v2(uncovered)


def test_real_minhash_fingerprint_is_canonicalizable_in_v2_envelope() -> None:
    private = envelope("vitaminc", "vitaminc-fixture-seal")
    private["records"][0]["selectors"]["fingerprints"] = [
        fingerprint_text(" ".join(f"token-{index}" for index in range(80)), "fixture")
    ]
    contribution = build_quarantine_contribution_v2(private)
    assert canonical_sha256(private).startswith("sha256:")
    assert canonical_sha256(contribution).startswith("sha256:")

    unsafe = copy.deepcopy(private)
    unsafe["records"][0]["selectors"]["fingerprints"][0]["minhash"][0] = (
        9_007_199_254_740_992
    )
    with pytest.raises(ValidationError, match="not valid under any"):
        build_quarantine_contribution_v2(unsafe)


def test_quarantine_union_recomputation_rejects_tampering() -> None:
    contribution = build_quarantine_contribution_v2(
        envelope("vitaminc", "vitaminc-fixture-seal")
    )
    index = compile_quarantine_index_v2([contribution])
    tampered = copy.deepcopy(contribution)
    tampered["coverage"]["covered_record_count"] = 0
    with pytest.raises(QuarantineError, match="incomplete quarantine contribution"):
        compile_quarantine_index_v2([tampered], index_id=index["index_id"])


def test_gate_separates_acquisition_transform_and_training(tmp_path: Path) -> None:
    source_registry, attestation, audit, source_review, terms, inventory = (
        ready_source_evidence(tmp_path)
    )
    (
        evaluation_registry,
        contributions,
        receipts,
        quarantine,
        evaluation_reviews,
        verified_terms,
        access_events,
        access_heads,
    ) = ready_evaluation_evidence()
    reviews = [source_review, *evaluation_reviews]
    verified_terms[source_review["review_id"]] = sha256_bytes(terms)
    evaluated_at = timestamp(datetime.now(UTC) + timedelta(seconds=2))
    base = dict(
        evaluated_at=evaluated_at,
        source_registry=source_registry,
        evaluation_registry=evaluation_registry,
        storage_attestation=attestation,
        source_audit=audit,
        licence_reviews=reviews,
        verified_terms_sha256=verified_terms,
        seal_receipts=receipts,
        quarantine_contributions=contributions,
        quarantine_index=quarantine,
        verified_seal_ids=[item["seal_id"] for item in receipts],
        evaluation_access_events=access_events,
        evaluation_access_heads=access_heads,
    )

    acquisition_only = evaluate_gate_v2(**base)
    assert acquisition_only["foundation_acquisition_authorized"] is True
    assert acquisition_only["foundation_transform_ready"] is False
    assert acquisition_only["training_authorized"] is False
    assert "inventory_set_mismatch" in acquisition_only["blockers"]

    admission = assess_admission_v2(
        source_id="wikidata@fixture",
        registry=source_registry,
        storage_attestation=attestation,
        source_audit=audit,
        licence_review=source_review,
        verified_terms_sha256=sha256_bytes(terms),
        inventories=[inventory],
        quarantine_index=quarantine,
        assessor="fixture-assessor",
        assessed_at="2026-08-16T03:00:00Z",
    )
    transformed = evaluate_gate_v2(
        **base,
        structural_inventories=[inventory],
        admission_receipts=[admission],
    )
    assert transformed["foundation_transform_ready"] is True
    assert transformed["training_authorized"] is False
    assert transformed["blockers"] == []
    assert canonical_sha256(transformed).startswith("sha256:")

    development_registry = copy.deepcopy(evaluation_registry)
    development_registry["datasets"][0]["partition"] = "dev.jsonl plus dev-labels.lst"
    development_arguments = {
        **base,
        "evaluation_registry": development_registry,
        "structural_inventories": [inventory],
        "admission_receipts": [admission],
    }
    development_partition = evaluate_gate_v2(**development_arguments)
    assert development_partition["public_confirmatory_ready"] is False
    assert any(
        "development or validation partition cannot be confirmatory" in blocker
        for blocker in development_partition["blockers"]
    )

    consumed_events = copy.deepcopy(access_events)
    consumed_heads = dict(access_heads)
    consumed_seal = sorted(consumed_events)[0]
    consumed_event = make_access_event(
        seal_id=consumed_seal,
        action="decrypt",
        actor="fixture-custodian",
        previous_hash=consumed_heads[consumed_seal],
    )
    consumed_events[consumed_seal].append(consumed_event)
    consumed_heads[consumed_seal] = consumed_event["event_hash"]
    consumed_arguments = {
        **base,
        "evaluation_access_events": consumed_events,
        "evaluation_access_heads": consumed_heads,
        "structural_inventories": [inventory],
        "admission_receipts": [admission],
    }
    consumed = evaluate_gate_v2(**consumed_arguments)
    assert consumed["public_confirmatory_ready"] is False
    assert consumed["foundation_acquisition_authorized"] is False
    assert any(
        blocker.startswith(f"evaluation_access_not_ready:{consumed_seal}:")
        for blocker in consumed["blockers"]
    )


def test_v2_seal_cli_derives_ids_counts_and_hashes() -> None:
    parser = build_parser()
    top = next(action.choices for action in parser._actions if action.choices)
    seal_parser = top["seal"]
    seal_choices = next(
        action.choices for action in seal_parser._actions if action.choices
    )
    create = seal_choices["create"]
    options = {option for action in create._actions for option in action.option_strings}
    assert {"--record-count", "--artifact-hash", "--seal-id"}.isdisjoint(options)
    assert {"--evaluations", "--contribution", "--receipt"}.issubset(options)
