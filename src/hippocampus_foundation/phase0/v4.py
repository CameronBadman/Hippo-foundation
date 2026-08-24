"""Phase 0 v4 external-evidence firewall and transformation boundary."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from hippocampus_foundation.licensing import (
    VerifiedBundle,
    validate_schema_lock_v1 as validate_licensing_schema_lock_v1,
    validate_v1 as validate_licensing_v1,
    verify_assessment,
)
from hippocampus_foundation.storage_identity import (
    validate_schema_lock_v1 as validate_storage_schema_lock_v1,
)

from .canonical import canonical_sha256
from .errors import GateBlocked, ValidationError
from .evaluation_firewall import (
    VerifiedSealReceipt,
    compile_quarantine_index_v4,
    validate_quarantine_contribution_v4,
    validate_evaluation_registry_v4,
    validate_source_registry_v4,
    verify_seal_receipt_v4,
)
from .external_evidence import (
    VerifiedAccessAnchor,
    VerifiedPublisherReceipt,
    validate_storage_attestation_v4,
)
from .quarantine_v4 import MATCHER_POLICY_ID_V4
from .seal import consumes_evaluation, verify_access_chain
from .source_evidence_v4 import (
    assess_admission_v4,
    validate_source_audit_v4,
    validate_structural_inventory_v4,
)
from .v2 import validate_schema_lock_v2
from .v3 import (
    EVALUATION_REQUIRED_USES,
    SOURCE_REQUIRED_USES,
    validate_schema_lock_v3,
)
from .v4_contracts import (
    SCHEMA_VERSION_V4,
    validate_schema_lock_v4,
    validate_v4,
)


SOURCE_AUDIT_MAX_AGE_V4 = timedelta(hours=72)
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

BlockerKey = tuple[str, str, str]
EvidenceKey = tuple[str, str, str]


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _block(
    blockers: set[BlockerKey], code: str, subject_kind: str, subject_id: str
) -> None:
    blockers.add((code, subject_kind, subject_id))


def _evidence(
    evidence: set[EvidenceKey], kind: str, subject_id: str, sha256: str
) -> None:
    evidence.add((kind, subject_id, sha256))


def _render_blockers(values: set[BlockerKey]) -> list[dict[str, str]]:
    return [
        {"code": code, "subject_kind": subject_kind, "subject_id": subject_id}
        for code, subject_kind, subject_id in sorted(values)
    ]


def _render_evidence(values: set[EvidenceKey]) -> list[dict[str, str]]:
    return [
        {"kind": kind, "subject_id": subject_id, "sha256": sha256}
        for kind, subject_id, sha256 in sorted(values)
    ]


def _assessment_by_id(
    assessments: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        validate_licensing_v1(assessment, "licence-assessment.schema.json")
        review_id = assessment["review_id"]
        if review_id in result:
            raise ValidationError(f"duplicate licence assessment: {review_id}")
        result[review_id] = assessment
    return result


def _publisher_by_artifact(
    values: Iterable[VerifiedPublisherReceipt],
) -> dict[str, VerifiedPublisherReceipt]:
    result: dict[str, VerifiedPublisherReceipt] = {}
    for value in values:
        artifact_id = value.receipt["artifact_id"]
        if artifact_id in result:
            raise ValidationError(f"duplicate publisher evidence: {artifact_id}")
        result[artifact_id] = value
    return result


def _source_and_artifact_by_id(
    registry: Mapping[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for source in registry.get("sources", []):
        for artifact in source["artifacts"]:
            result[artifact["artifact_id"]] = (source, artifact)
    return result


def evaluate_gate_v4(
    *,
    evaluated_at: str,
    source_registry: dict[str, Any],
    source_registry_predecessor: dict[str, Any] | None,
    evaluation_registry: dict[str, Any],
    evaluation_registry_predecessor: dict[str, Any] | None,
    drive_observation: dict[str, Any] | None = None,
    storage_attestation: dict[str, Any] | None = None,
    publisher_receipts: Iterable[VerifiedPublisherReceipt] = (),
    source_audit: dict[str, Any] | None = None,
    licence_assessments: Iterable[dict[str, Any]] = (),
    verified_bundles: Mapping[str, VerifiedBundle] | None = None,
    quarantine_contributions: Iterable[dict[str, Any]] = (),
    quarantine_index: dict[str, Any] | None = None,
    verified_seals: Iterable[VerifiedSealReceipt] = (),
    evaluation_access_events: Mapping[str, Iterable[dict[str, Any]]] | None = None,
    verified_access_anchors: Mapping[str, VerifiedAccessAnchor] | None = None,
    structural_inventories: Iterable[dict[str, Any]] = (),
    admission_receipts: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Evaluate exact evidence. Phase 0 v4 can never authorize training."""

    now = _parse_time(evaluated_at, "evaluated_at")
    blockers: set[BlockerKey] = set()
    evidence: set[EvidenceKey] = set()

    try:
        locks = {
            "phase0_v2": validate_schema_lock_v2(),
            "phase0_v3": validate_schema_lock_v3(),
            "phase0_v4": validate_schema_lock_v4(),
            "licensing_v1": validate_licensing_schema_lock_v1(),
            "storage_v1": validate_storage_schema_lock_v1(),
        }
        contracts_frozen = True
        for kind, value in locks.items():
            _evidence(evidence, "schema_lock", kind, canonical_sha256(value))
    except Exception:
        contracts_frozen = False
        _block(blockers, "contracts_invalid", "gate", "phase0-v4")

    source_registry_ready = False
    try:
        validate_source_registry_v4(source_registry, source_registry_predecessor)
        if _parse_time(source_registry["generated_at"], "source generated_at") > now:
            raise ValidationError("source registry is from the future")
        source_registry_ready = True
        _evidence(
            evidence,
            "source_registry",
            source_registry["registry_id"],
            canonical_sha256(source_registry),
        )
    except Exception:
        _block(
            blockers,
            "source_registry_invalid",
            "registry",
            str(source_registry.get("registry_id", "sources")),
        )

    evaluation_registry_ready = False
    evaluation_roles_ready = False
    try:
        validate_v4(evaluation_registry, "registry.schema.json")
        if evaluation_registry.get("registry_kind") != "evaluations":
            raise ValidationError("wrong evaluation registry kind")
        evaluation_registry_ready = True
        validate_evaluation_registry_v4(
            evaluation_registry, evaluation_registry_predecessor
        )
        if _parse_time(
            evaluation_registry["generated_at"], "evaluation generated_at"
        ) > now:
            raise ValidationError("evaluation registry is from the future")
        evaluation_roles_ready = True
        _evidence(
            evidence,
            "evaluation_registry",
            evaluation_registry["registry_id"],
            canonical_sha256(evaluation_registry),
        )
    except Exception:
        _block(
            blockers,
            "evaluation_registry_invalid",
            "registry",
            str(evaluation_registry.get("registry_id", "evaluations")),
        )
    if evaluation_registry_ready and not evaluation_roles_ready:
        _block(blockers, "evaluation_roles_invalid", "registry", "evaluations")
    source_entries = source_registry["sources"] if source_registry_ready else []
    evaluation_entries = (
        evaluation_registry["datasets"] if evaluation_roles_ready else []
    )

    storage_identity_ready = False
    if drive_observation is None:
        _block(blockers, "drive_observation_missing", "storage", "drive_lake")
    if storage_attestation is None:
        _block(blockers, "storage_attestation_missing", "storage", "drive_lake")
    if (
        source_registry_ready
        and drive_observation is not None
        and storage_attestation is not None
    ):
        try:
            validate_storage_attestation_v4(
                storage_attestation,
                source_registry,
                observation=drive_observation,
                evaluated_at=evaluated_at,
            )
            storage_identity_ready = True
            _evidence(
                evidence,
                "drive_observation",
                storage_attestation["locator_id"],
                canonical_sha256(drive_observation),
            )
            _evidence(
                evidence,
                "storage_attestation",
                storage_attestation["locator_id"],
                canonical_sha256(storage_attestation),
            )
        except Exception:
            _block(
                blockers,
                "storage_identity_invalid",
                "storage",
                "drive_lake",
            )

    publisher_evidence_ready = False
    publisher_by_artifact: dict[str, VerifiedPublisherReceipt] = {}
    artifacts = (
        _source_and_artifact_by_id(source_registry) if source_registry_ready else {}
    )
    try:
        publisher_by_artifact = _publisher_by_artifact(publisher_receipts)
        if set(publisher_by_artifact) != set(artifacts):
            raise ValidationError("publisher evidence set mismatch")
        requirements = {
            item["artifact_id"]: item
            for item in source_registry["publisher_evidence_requirements"]
        }
        for artifact_id, verified in publisher_by_artifact.items():
            source, artifact = artifacts[artifact_id]
            requirement = requirements[artifact_id]
            receipt = verified.receipt
            validate_v4(receipt, "publisher-evidence.schema.json")
            if verified.sha256 != canonical_sha256(receipt):
                raise ValidationError("publisher wrapper receipt digest mismatch")
            if verified.statement_sha256 != receipt["statement_sha256"]:
                raise ValidationError("publisher wrapper statement digest mismatch")
            bindings = {
                "evidence_id": requirement["evidence_id"],
                "source_id": source["source_id"],
                "artifact_entry_sha256": canonical_sha256(artifact),
                "source_registry_sha256": canonical_sha256(source_registry),
                "statement_url": requirement["statement_url"],
                "statement_format": requirement["statement_format"],
                "max_age_hours": requirement["max_age_hours"],
            }
            for field, expected in bindings.items():
                if receipt[field] != expected:
                    raise ValidationError(f"publisher evidence mismatch: {field}")
            if requirement["statement_url"] is None:
                raise ValidationError("publisher statement URL is not pinned")
            registered = {
                (item["algorithm"], item["value"])
                for item in artifact["checksums"]
                if item["origin"] == "publisher"
            }
            if (receipt["algorithm"], receipt["value"]) not in registered:
                raise ValidationError("publisher evidence checksum is not registered")
            verified_at = _parse_time(receipt["verified_at"], "verified_at")
            if verified_at > now or now - verified_at > timedelta(
                hours=receipt["max_age_hours"]
            ):
                raise ValidationError("publisher evidence is stale or future")
            _evidence(evidence, "publisher_receipt", artifact_id, verified.sha256)
        publisher_evidence_ready = bool(artifacts)
    except Exception:
        publisher_evidence_ready = False
        _block(blockers, "publisher_evidence_incomplete", "artifact", "all")

    source_audit_ready = False
    foundation_bytes_ready = False
    audit_status: dict[tuple[str, str], str] = {}
    if source_audit is None:
        _block(blockers, "source_audit_missing", "source", "all")
    elif source_registry_ready and storage_identity_ready and publisher_evidence_ready:
        try:
            validate_source_audit_v4(source_audit)
            if source_audit["registry_sha256"] != canonical_sha256(source_registry):
                raise ValidationError("source audit registry mismatch")
            if source_audit["storage_attestation_sha256"] != canonical_sha256(
                storage_attestation
            ):
                raise ValidationError("source audit storage mismatch")
            if source_audit["publisher_receipt_sha256s"] != sorted(
                item.sha256 for item in publisher_by_artifact.values()
            ):
                raise ValidationError("source audit publisher set mismatch")
            completed = _parse_time(source_audit["completed_at"], "completed_at")
            if completed > now or now - completed > SOURCE_AUDIT_MAX_AGE_V4:
                raise ValidationError("source audit is stale or future")
            audit_status = {
                (row["source_id"], row["artifact_id"]): row["status"]
                for row in source_audit["artifacts"]
            }
            audit_rows = {
                (row["source_id"], row["artifact_id"]): row
                for row in source_audit["artifacts"]
            }
            expected_pairs = {
                (source["source_id"], artifact["artifact_id"])
                for source in source_registry["sources"]
                for artifact in source["artifacts"]
            }
            if set(audit_status) != expected_pairs:
                raise ValidationError("source audit artifact set mismatch")
            for source in source_registry["sources"]:
                for artifact in source["artifacts"]:
                    row = audit_rows[(source["source_id"], artifact["artifact_id"])]
                    if (
                        row["locator_id"] != artifact["locator_id"]
                        or row["filename"] != artifact["filename"]
                    ):
                        raise ValidationError("source audit locator binding mismatch")
                    measured = row["measured"]
                    if row["status"] == "verified":
                        if measured is None or measured["bytes"] != artifact["expected_bytes"]:
                            raise ValidationError("source audit byte count mismatch")
                        for checksum in artifact["checksums"]:
                            if measured[checksum["algorithm"]] != checksum["value"]:
                                raise ValidationError("source audit checksum mismatch")
            preexisting_pairs = {
                (source["source_id"], artifact["artifact_id"])
                for source in source_registry["sources"]
                for artifact in source["artifacts"]
                if artifact["availability"] == "preexisting"
            }
            if any(audit_status[pair] != "verified" for pair in preexisting_pairs):
                raise ValidationError("preexisting source bytes are not verified")
            source_audit_ready = True
            foundation_pairs = {
                (source["source_id"], artifact["artifact_id"])
                for source in source_registry["sources"]
                if source["role"] == "foundation_candidate"
                for artifact in source["artifacts"]
            }
            foundation_bytes_ready = bool(foundation_pairs) and all(
                audit_status[pair] == "verified" for pair in foundation_pairs
            )
            _evidence(
                evidence,
                "source_audit",
                source_audit["registry_id"],
                canonical_sha256(source_audit),
            )
        except Exception:
            _block(blockers, "source_audit_invalid", "source", "all")
    if not source_audit_ready:
        _block(blockers, "source_audit_not_ready", "source", "all")
    if not foundation_bytes_ready:
        _block(blockers, "foundation_bytes_not_ready", "source", "all")

    assessments = list(licence_assessments)
    bundles = dict(verified_bundles or {})
    try:
        assessments_by_id = _assessment_by_id(assessments)
    except Exception:
        assessments_by_id = {}
        _block(blockers, "licence_assessments_invalid", "rights", "all")
    expected_reviews: dict[str, tuple[str, str, str, frozenset[str]]] = {}
    review_id_collision = False
    if source_registry_ready:
        for source in source_entries:
            if source["role"] == "foundation_candidate":
                expected_reviews[source["licence_review_id"]] = (
                    "source",
                    source["source_id"],
                    canonical_sha256(source),
                    SOURCE_REQUIRED_USES,
                )
    if evaluation_roles_ready:
        for dataset in evaluation_entries:
            if dataset["licence_review_id"] in expected_reviews:
                review_id_collision = True
                _block(
                    blockers,
                    "licence_review_id_reused",
                    "rights",
                    dataset["licence_review_id"],
                )
                continue
            expected_reviews[dataset["licence_review_id"]] = (
                "evaluation",
                dataset["dataset_id"],
                canonical_sha256(dataset),
                EVALUATION_REQUIRED_USES,
            )
    licensing_evidence_verified = bool(expected_reviews) and not review_id_collision
    licensing_ready = licensing_evidence_verified
    if set(assessments_by_id) != set(expected_reviews) or set(bundles) != set(
        expected_reviews
    ):
        licensing_evidence_verified = False
        licensing_ready = False
        _block(blockers, "licence_evidence_set_mismatch", "rights", "all")
    for review_id, (kind, subject_id, binding, required_uses) in expected_reviews.items():
        assessment = assessments_by_id.get(review_id)
        bundle = bundles.get(review_id)
        if assessment is None or bundle is None:
            _block(blockers, "licence_evidence_missing", "rights", subject_id)
            continue
        try:
            bundle_value = bundle.bundle
            expected_binding = {
                "review_id": review_id,
                "subject_kind": kind,
                "subject_id": subject_id,
                "subject_binding_sha256": binding,
            }
            for field, expected in expected_binding.items():
                if assessment[field] != expected or bundle_value[field] != expected:
                    raise ValidationError("licence evidence binding mismatch")
            if assessment["bundle_sha256"] != bundle.sha256:
                raise ValidationError("licence bundle digest mismatch")
            _evidence(evidence, "licence_bundle", subject_id, bundle.sha256)
            _evidence(
                evidence,
                "licence_assessment",
                subject_id,
                canonical_sha256(assessment),
            )
        except Exception:
            licensing_evidence_verified = False
            licensing_ready = False
            _block(blockers, "licence_evidence_invalid", "rights", subject_id)
            continue
        try:
            verify_assessment(
                assessment,
                bundle,
                subject_kind=kind,
                subject_id=subject_id,
                subject_binding_sha256=binding,
                required_uses=required_uses,
                evaluated_at=evaluated_at,
            )
        except Exception:
            licensing_ready = False
            _block(blockers, "licence_not_approved", "rights", subject_id)
    if not licensing_evidence_verified:
        _block(blockers, "licensing_evidence_not_verified", "rights", "all")
    if not licensing_ready:
        _block(blockers, "licensing_not_ready", "rights", "all")

    contribution_values = list(quarantine_contributions)
    contribution_by_dataset: dict[str, dict[str, Any]] = {}
    for contribution in contribution_values:
        try:
            validate_quarantine_contribution_v4(contribution)
            dataset_id = contribution["dataset_id"]
            if dataset_id in contribution_by_dataset:
                raise ValidationError("duplicate contribution")
            contribution_by_dataset[dataset_id] = contribution
        except Exception:
            _block(blockers, "quarantine_contribution_invalid", "quarantine", "unknown")

    seal_by_dataset: dict[str, VerifiedSealReceipt] = {}
    for verified in verified_seals:
        dataset_id = verified.receipt.get("dataset_id", "unknown")
        if dataset_id in seal_by_dataset:
            _block(blockers, "seal_duplicate", "seal", dataset_id)
            continue
        seal_by_dataset[dataset_id] = verified
    access_events = {
        seal_id: list(events)
        for seal_id, events in (evaluation_access_events or {}).items()
    }
    anchors = dict(verified_access_anchors or {})
    confirmatory_custody_ready = evaluation_roles_ready
    confirmatory_datasets = {
        item["dataset_id"]: item
        for item in evaluation_entries
        if item.get("usage_role") == "confirmatory"
    }
    if set(seal_by_dataset) != set(confirmatory_datasets):
        confirmatory_custody_ready = False
        _block(blockers, "seal_set_mismatch", "seal", "confirmatory")
    expected_seal_ids = {
        item["seal_id"] for item in confirmatory_datasets.values()
    }
    if set(access_events) != expected_seal_ids:
        confirmatory_custody_ready = False
        _block(blockers, "access_log_set_mismatch", "seal", "confirmatory")
    if set(anchors) != expected_seal_ids:
        confirmatory_custody_ready = False
        _block(blockers, "access_anchor_set_mismatch", "seal", "confirmatory")
    for dataset_id, dataset in confirmatory_datasets.items():
        try:
            if dataset["custody_state"] != "sealed" or dataset["blockers"]:
                raise ValidationError("confirmatory dataset is not sealed")
            contribution = contribution_by_dataset[dataset_id]
            if contribution["usage_role"] != "confirmatory":
                raise ValidationError("confirmatory contribution role mismatch")
            verified_seal = seal_by_dataset[dataset_id]
            if verified_seal.sha256 != canonical_sha256(verified_seal.receipt):
                raise ValidationError("verified seal wrapper digest mismatch")
            verify_seal_receipt_v4(
                verified_seal.receipt,
                evaluation_registry=evaluation_registry,
                contribution=contribution,
                ciphertext_sha256=verified_seal.ciphertext_sha256,
            )
            seal_id = dataset["seal_id"]
            anchor = anchors[seal_id]
            if anchor.sha256 != canonical_sha256(anchor.anchor):
                raise ValidationError("verified anchor wrapper digest mismatch")
            if not SHA256_DIGEST.fullmatch(
                anchor.signature_sha256
            ) or not SHA256_DIGEST.fullmatch(anchor.public_key_sha256):
                raise ValidationError("verified anchor wrapper artifact digest is invalid")
            validate_v4(anchor.anchor, "access-anchor.schema.json")
            if anchor.anchor["seal_receipt_sha256"] != verified_seal.sha256:
                raise ValidationError("anchor seal receipt binding mismatch")
            if (
                anchor.signing_key_fingerprint
                != dataset["custodian_signing_key_fingerprint"]
            ):
                raise ValidationError("anchor custodian key binding mismatch")
            events = access_events[seal_id]
            verify_access_chain(
                events,
                expected_head=anchor.anchor["head_event_sha256"],
                expected_count=anchor.anchor["event_count"],
            )
            if any(consumes_evaluation(event["action"]) for event in events):
                raise ValidationError("confirmatory evaluation was consumed")
            anchored = _parse_time(anchor.anchor["anchored_at"], "anchor anchored_at")
            valid_until = _parse_time(
                anchor.anchor["valid_until"], "anchor valid_until"
            )
            if anchored > now or valid_until < now:
                raise ValidationError("confirmatory access anchor is stale or future")
            if valid_until <= anchored or valid_until - anchored > timedelta(hours=72):
                raise ValidationError("confirmatory access anchor window is invalid")
            if _parse_time(
                verified_seal.receipt["created_at"], "seal created_at"
            ) > now:
                raise ValidationError("confirmatory seal is from the future")
            _evidence(evidence, "seal_receipt", dataset_id, verified_seal.sha256)
            _evidence(evidence, "access_anchor", dataset_id, anchor.sha256)
            _evidence(
                evidence,
                "access_anchor_signature",
                dataset_id,
                anchor.signature_sha256,
            )
            _evidence(
                evidence,
                "custodian_public_key",
                dataset_id,
                anchor.public_key_sha256,
            )
        except Exception:
            confirmatory_custody_ready = False
            _block(blockers, "confirmatory_custody_invalid", "evaluation", dataset_id)
    if not confirmatory_custody_ready:
        _block(blockers, "confirmatory_custody_not_ready", "seal", "all")

    quarantine_ready = False
    expected_dataset_ids = {
        item["dataset_id"] for item in evaluation_entries
    }
    if quarantine_index is None:
        _block(blockers, "quarantine_index_missing", "quarantine", "union")
    elif evaluation_roles_ready:
        try:
            if set(contribution_by_dataset) != expected_dataset_ids:
                raise ValidationError("quarantine contribution set mismatch")
            for dataset in evaluation_entries:
                contribution = contribution_by_dataset[dataset["dataset_id"]]
                bindings = {
                    "usage_role": dataset["usage_role"],
                    "resolved_version": dataset["resolved_version"],
                    "archive_sha256": dataset["archive_sha256"],
                    "adapter_id": dataset["adapter_id"],
                    "adapter_sha256": dataset["adapter_sha256"],
                }
                for field, expected in bindings.items():
                    if contribution[field] != expected:
                        raise ValidationError(f"contribution binding mismatch: {field}")
                expected_origin = (
                    "sealed_confirmatory"
                    if dataset["usage_role"] == "confirmatory"
                    else "pinned_nonconfirmatory"
                )
                if contribution["origin"] != expected_origin:
                    raise ValidationError("contribution custody origin mismatch")
            validate_v4(quarantine_index, "evaluation-evidence.schema.json")
            recomputed = compile_quarantine_index_v4(
                contribution_by_dataset.values(),
                expected_dataset_ids=expected_dataset_ids,
                index_id=quarantine_index["index_id"],
            )
            if recomputed != quarantine_index:
                raise ValidationError("quarantine union is not reproducible")
            quarantine_ready = True
            _evidence(
                evidence,
                "quarantine_index",
                quarantine_index["index_id"],
                canonical_sha256(quarantine_index),
            )
        except Exception:
            _block(blockers, "quarantine_invalid", "quarantine", "union")
    if not quarantine_ready:
        _block(blockers, "quarantine_not_ready", "quarantine", "union")
    quarantine_matcher_ready = contracts_frozen and quarantine_ready
    if not quarantine_matcher_ready:
        _block(blockers, "quarantine_matcher_not_ready", "quarantine", MATCHER_POLICY_ID_V4)

    inventory_values = list(structural_inventories)
    inventory_by_artifact: dict[str, dict[str, Any]] = {}
    structural_inventory_ready = (
        foundation_bytes_ready
        and source_audit is not None
        and storage_attestation is not None
    )
    for inventory in inventory_values:
        artifact_id = str(inventory.get("artifact_id", "unknown"))
        try:
            if artifact_id in inventory_by_artifact:
                raise ValidationError("duplicate inventory")
            validate_structural_inventory_v4(
                inventory,
                registry=source_registry,
                storage_attestation=storage_attestation,
                source_audit=source_audit,
                publisher_receipt=publisher_by_artifact[artifact_id],
            )
            if _parse_time(inventory["completed_at"], "inventory completed_at") > now:
                raise ValidationError("structural inventory is from the future")
            inventory_by_artifact[artifact_id] = inventory
            _evidence(
                evidence,
                "structural_inventory",
                artifact_id,
                canonical_sha256(inventory),
            )
        except Exception:
            structural_inventory_ready = False
            _block(blockers, "inventory_invalid", "inventory", artifact_id)
    expected_inventory_ids = {
        artifact["artifact_id"]
        for source in source_entries
        if source.get("role") == "foundation_candidate"
        for artifact in source["artifacts"]
    }
    if set(inventory_by_artifact) != expected_inventory_ids:
        structural_inventory_ready = False
        _block(blockers, "inventory_set_mismatch", "inventory", "all")
    if not structural_inventory_ready:
        _block(blockers, "structural_inventory_not_ready", "inventory", "all")

    admission_values = list(admission_receipts)
    admission_by_source: dict[str, dict[str, Any]] = {}
    admission_ready = (
        structural_inventory_ready
        and licensing_ready
        and quarantine_ready
        and storage_attestation is not None
        and source_audit is not None
        and quarantine_index is not None
    )
    expected_sources = {
        item["source_id"]
        for item in source_entries
        if item.get("role") == "foundation_candidate"
    }
    for receipt in admission_values:
        source_id = str(receipt.get("source_id", "unknown"))
        try:
            if source_id in admission_by_source:
                raise ValidationError("duplicate admission")
            source = next(
                item for item in source_entries if item["source_id"] == source_id
            )
            review_id = source["licence_review_id"]
            source_artifact_ids = {item["artifact_id"] for item in source["artifacts"]}
            expected_receipt = assess_admission_v4(
                source_id=source_id,
                source_registry=source_registry,
                evaluation_registry=evaluation_registry,
                storage_attestation=storage_attestation,
                source_audit=source_audit,
                publisher_receipts=[
                    publisher_by_artifact[item] for item in source_artifact_ids
                ],
                assessment=assessments_by_id[review_id],
                verified_bundle=bundles[review_id],
                inventories=[
                    inventory_by_artifact[item] for item in source_artifact_ids
                ],
                quarantine_index=quarantine_index,
                assessor=receipt["assessor"],
                assessed_at=receipt["assessed_at"],
            )
            if receipt != expected_receipt:
                raise ValidationError("admission receipt is not reproducible")
            if _parse_time(receipt["assessed_at"], "admission assessed_at") > now:
                raise ValidationError("admission receipt is from the future")
            admission_by_source[source_id] = receipt
            _evidence(
                evidence,
                "admission_receipt",
                source_id,
                canonical_sha256(receipt),
            )
        except Exception:
            admission_ready = False
            _block(blockers, "admission_invalid", "admission", source_id)
    if set(admission_by_source) != expected_sources:
        admission_ready = False
        _block(blockers, "admission_set_mismatch", "admission", "all")
    if not admission_ready:
        _block(blockers, "admission_not_ready", "admission", "all")

    foundation_acquisition_authorized = all(
        (
            contracts_frozen,
            source_registry_ready,
            evaluation_registry_ready,
            evaluation_roles_ready,
            storage_identity_ready,
            publisher_evidence_ready,
            source_audit_ready,
            licensing_evidence_verified,
            licensing_ready,
            confirmatory_custody_ready,
            quarantine_ready,
            quarantine_matcher_ready,
        )
    )
    foundation_transform_ready = all(
        (
            foundation_acquisition_authorized,
            foundation_bytes_ready,
            structural_inventory_ready,
            admission_ready,
        )
    )
    report = {
        "schema_version": SCHEMA_VERSION_V4,
        "gate_id": "phase0-external-evidence-firewall-v4",
        "evaluated_at": evaluated_at,
        "contracts_frozen": contracts_frozen,
        "source_registry_ready": source_registry_ready,
        "evaluation_registry_ready": evaluation_registry_ready,
        "evaluation_roles_ready": evaluation_roles_ready,
        "storage_identity_ready": storage_identity_ready,
        "publisher_evidence_ready": publisher_evidence_ready,
        "source_audit_ready": source_audit_ready,
        "foundation_bytes_ready": foundation_bytes_ready,
        "licensing_evidence_verified": licensing_evidence_verified,
        "licensing_ready": licensing_ready,
        "confirmatory_custody_ready": confirmatory_custody_ready,
        "quarantine_ready": quarantine_ready,
        "quarantine_matcher_ready": quarantine_matcher_ready,
        "structural_inventory_ready": structural_inventory_ready,
        "admission_ready": admission_ready,
        "foundation_acquisition_authorized": foundation_acquisition_authorized,
        "foundation_transform_ready": foundation_transform_ready,
        "training_authorized": False,
        "blockers": _render_blockers(blockers),
        "evidence_bindings": _render_evidence(evidence),
    }
    validate_v4(report, "gate.schema.json")
    return report


def require_phase0_transform_gate_v4(gate: dict[str, Any]) -> str:
    validate_v4(gate, "gate.schema.json")
    required = (
        "contracts_frozen",
        "source_registry_ready",
        "evaluation_registry_ready",
        "evaluation_roles_ready",
        "storage_identity_ready",
        "publisher_evidence_ready",
        "source_audit_ready",
        "foundation_bytes_ready",
        "licensing_evidence_verified",
        "licensing_ready",
        "confirmatory_custody_ready",
        "quarantine_ready",
        "quarantine_matcher_ready",
        "structural_inventory_ready",
        "admission_ready",
        "foundation_acquisition_authorized",
        "foundation_transform_ready",
    )
    if not all(gate[field] is True for field in required) or gate["blockers"]:
        raise GateBlocked("Phase 0 v4 has not authorized foundation transformation")
    if gate["training_authorized"] is not False:
        raise GateBlocked("Phase 0 v4 training invariant is violated")
    return canonical_sha256(gate)
