"""Exact source-byte audit, inventory, and admission for Phase 0 v4."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from hippocampus_foundation.licensing import VerifiedBundle, verify_assessment

from .canonical import canonical_sha256
from .errors import GateBlocked, IntegrityError, ValidationError
from .evaluation_firewall import (
    validate_evaluation_registry_v4,
    validate_source_registry_v4,
)
from .external_evidence import (
    VerifiedPublisherReceipt,
    validate_storage_attestation_v4,
)
from .inventory import audit_source_registry, hash_file, resolve_artifact, stream_count
from .v3 import SOURCE_REQUIRED_USES
from .v4_contracts import SCHEMA_VERSION_V4, validate_v4


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _artifact_lookup(
    registry: dict[str, Any], artifact_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [
        (source, artifact)
        for source in registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == artifact_id
    ]
    if len(matches) != 1:
        raise ValidationError(f"artifact_id must resolve exactly once: {artifact_id}")
    return matches[0]


def _publisher_by_artifact(
    values: Iterable[VerifiedPublisherReceipt],
) -> dict[str, VerifiedPublisherReceipt]:
    result: dict[str, VerifiedPublisherReceipt] = {}
    for value in values:
        artifact_id = value.receipt["artifact_id"]
        if artifact_id in result:
            raise ValidationError(f"duplicate publisher receipt: {artifact_id}")
        result[artifact_id] = value
    return result


def audit_source_registry_v4(
    registry: dict[str, Any],
    storage_attestation: dict[str, Any],
    publisher_receipts: Iterable[VerifiedPublisherReceipt],
    *,
    evaluated_at: str,
) -> dict[str, Any]:
    validate_source_registry_v4(registry)
    validate_storage_attestation_v4(
        storage_attestation, registry, evaluated_at=evaluated_at
    )
    publisher_by_artifact = _publisher_by_artifact(publisher_receipts)
    expected_artifacts = {
        artifact["artifact_id"]
        for source in registry["sources"]
        for artifact in source["artifacts"]
    }
    if set(publisher_by_artifact) != expected_artifacts:
        raise ValidationError("publisher receipt set does not match source artifacts")
    for artifact_id, verified in publisher_by_artifact.items():
        _, artifact = _artifact_lookup(registry, artifact_id)
        receipt = verified.receipt
        validate_v4(receipt, "publisher-evidence.schema.json")
        if verified.sha256 != canonical_sha256(receipt):
            raise ValidationError("publisher wrapper receipt digest mismatch")
        if verified.statement_sha256 != receipt["statement_sha256"]:
            raise ValidationError("publisher wrapper statement digest mismatch")
        verified_at = _parse_time(receipt["verified_at"], "publisher verified_at")
        evaluated = _parse_time(evaluated_at, "evaluated_at")
        if verified_at > evaluated or evaluated - verified_at > timedelta(
            hours=receipt["max_age_hours"]
        ):
            raise ValidationError("publisher receipt is stale or from the future")
        if receipt["source_registry_sha256"] != canonical_sha256(registry):
            raise ValidationError("publisher receipt registry binding mismatch")
        if receipt["artifact_entry_sha256"] != canonical_sha256(artifact):
            raise ValidationError("publisher receipt artifact binding mismatch")

    historical_shape = {
        "registry_id": registry["registry_id"],
        "storage_requirements": [
            {
                "locator_id": item["locator_id"],
                "required_root": item["required_root"],
            }
            for item in registry["storage_requirements"]
        ],
        "sources": registry["sources"],
    }
    storage_map = {
        storage_attestation["locator_id"]: storage_attestation["observed_root"]
    }
    result = audit_source_registry(historical_shape, storage_map)
    result["schema_version"] = SCHEMA_VERSION_V4
    result["record_kind"] = "source_audit"
    result["registry_sha256"] = canonical_sha256(registry)
    result["storage_attestation_sha256"] = canonical_sha256(storage_attestation)
    result["publisher_receipt_sha256s"] = sorted(
        value.sha256 for value in publisher_by_artifact.values()
    )
    result["training_authorized"] = False
    result.pop("storage_map_sha256", None)
    for row in result["artifacts"]:
        measured = row["measured"]
        if measured is not None:
            for field in ("device", "inode", "mtime_ns"):
                measured[field] = str(measured[field])
    validate_source_audit_v4(result)
    return result


def validate_source_audit_v4(audit: dict[str, Any]) -> None:
    validate_v4(audit, "source-evidence.schema.json")
    if audit.get("record_kind") != "source_audit":
        raise ValidationError("expected a source_audit")
    started = _parse_time(audit["started_at"], "source audit started_at")
    completed = _parse_time(audit["completed_at"], "source audit completed_at")
    if completed < started:
        raise ValidationError("source audit completed before it started")
    if audit["artifact_count"] != len(audit["artifacts"]):
        raise ValidationError("source audit artifact_count mismatch")
    measured_total = sum(
        row["measured"]["bytes"]
        for row in audit["artifacts"]
        if row["measured"] is not None
    )
    if audit["total_bytes"] != measured_total:
        raise ValidationError("source audit total_bytes mismatch")
    if audit["all_verified"] != all(
        row["status"] == "verified" for row in audit["artifacts"]
    ):
        raise ValidationError("source audit all_verified is inconsistent")
    pairs = [(row["source_id"], row["artifact_id"]) for row in audit["artifacts"]]
    if len(pairs) != len(set(pairs)):
        raise ValidationError("source audit contains duplicate artifact rows")
    for row in audit["artifacts"]:
        if row["status"] == "verified" and (
            row["measured"] is None or row["mismatches"]
        ):
            raise ValidationError("verified source audit row is inconsistent")


def build_structural_inventory_v4(
    *,
    registry: dict[str, Any],
    storage_attestation: dict[str, Any],
    source_audit: dict[str, Any],
    publisher_receipt: VerifiedPublisherReceipt,
    artifact_id: str,
    evaluated_at: str,
) -> dict[str, Any]:
    validate_source_registry_v4(registry)
    validate_storage_attestation_v4(
        storage_attestation, registry, evaluated_at=evaluated_at
    )
    validate_source_audit_v4(source_audit)
    if source_audit["registry_sha256"] != canonical_sha256(registry):
        raise ValidationError("source audit registry binding mismatch")
    if source_audit["storage_attestation_sha256"] != canonical_sha256(
        storage_attestation
    ):
        raise ValidationError("source audit storage binding mismatch")
    evaluated = _parse_time(evaluated_at, "evaluated_at")
    audit_completed = _parse_time(source_audit["completed_at"], "completed_at")
    if audit_completed > evaluated:
        raise ValidationError("source audit is from the future")
    source, artifact = _artifact_lookup(registry, artifact_id)
    if publisher_receipt.receipt["artifact_id"] != artifact_id:
        raise ValidationError("publisher receipt belongs to another artifact")
    if publisher_receipt.sha256 not in source_audit["publisher_receipt_sha256s"]:
        raise ValidationError("source audit does not bind the publisher receipt")
    rows = [
        row for row in source_audit["artifacts"] if row["artifact_id"] == artifact_id
    ]
    if len(rows) != 1 or rows[0]["status"] != "verified":
        raise GateBlocked("structural inventory requires a verified audit row")
    row = rows[0]
    measured = row["measured"]
    if measured is None:
        raise GateBlocked("structural inventory lacks measured bytes")
    storage_map = {
        storage_attestation["locator_id"]: storage_attestation["observed_root"]
    }
    path = resolve_artifact(storage_map, artifact["locator_id"], artifact["filename"])
    started_at = _utc_now()
    before = hash_file(path)
    counters = stream_count(path, artifact["inventory_kind"])
    after = hash_file(path)
    completed_at = _utc_now()
    if before != after:
        raise IntegrityError("artifact changed during structural inventory")
    if before["sha256"] != measured["sha256"] or before["bytes"] != measured["bytes"]:
        raise IntegrityError("structural inventory bytes differ from source audit")
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "structural_inventory",
        "source_id": source["source_id"],
        "artifact_id": artifact_id,
        "registry_sha256": canonical_sha256(registry),
        "source_audit_sha256": canonical_sha256(source_audit),
        "storage_attestation_sha256": canonical_sha256(storage_attestation),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "artifact_sha256": f"sha256:{before['sha256']}",
        "artifact_bytes": before["bytes"],
        "counter_kind": artifact["inventory_kind"],
        "counter_version": "hf-stream-counter-v4",
        "started_at": started_at,
        "completed_at": completed_at,
        "complete": True,
        "parse_errors": counters.get("parse_errors", 0),
        "rejected_records": counters.get("rejected_records", 0),
        "counters": counters,
        "training_authorized": False,
    }
    validate_structural_inventory_v4(
        result,
        registry=registry,
        storage_attestation=storage_attestation,
        source_audit=source_audit,
        publisher_receipt=publisher_receipt,
    )
    return result


def validate_structural_inventory_v4(
    inventory: dict[str, Any],
    *,
    registry: dict[str, Any],
    storage_attestation: dict[str, Any],
    source_audit: dict[str, Any],
    publisher_receipt: VerifiedPublisherReceipt,
) -> None:
    validate_v4(inventory, "source-evidence.schema.json")
    if inventory.get("record_kind") != "structural_inventory":
        raise ValidationError("expected a structural_inventory")
    started = _parse_time(inventory["started_at"], "inventory started_at")
    completed = _parse_time(inventory["completed_at"], "inventory completed_at")
    audit_completed = _parse_time(source_audit["completed_at"], "audit completed_at")
    if completed < started:
        raise ValidationError("structural inventory completed before it started")
    if started < audit_completed:
        raise ValidationError("structural inventory predates its source audit")
    source, artifact = _artifact_lookup(registry, inventory["artifact_id"])
    bindings = {
        "source_id": source["source_id"],
        "registry_sha256": canonical_sha256(registry),
        "source_audit_sha256": canonical_sha256(source_audit),
        "storage_attestation_sha256": canonical_sha256(storage_attestation),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "counter_kind": artifact["inventory_kind"],
    }
    for field, expected in bindings.items():
        if inventory[field] != expected:
            raise ValidationError(f"structural inventory binding mismatch: {field}")
    rows = [
        row
        for row in source_audit["artifacts"]
        if row["artifact_id"] == inventory["artifact_id"]
    ]
    if len(rows) != 1 or rows[0]["status"] != "verified":
        raise ValidationError("structural inventory lacks a verified audit row")
    measured = rows[0]["measured"]
    if measured is None:
        raise ValidationError("verified audit row lacks measurement")
    if inventory["artifact_sha256"] != f"sha256:{measured['sha256']}":
        raise ValidationError("structural inventory artifact digest mismatch")
    if inventory["artifact_bytes"] != measured["bytes"]:
        raise ValidationError("structural inventory byte count mismatch")
    if not inventory["complete"] or inventory["parse_errors"] or inventory[
        "rejected_records"
    ]:
        raise ValidationError("structural inventory is incomplete or invalid")
    for name in artifact["required_nonzero_counters"]:
        if inventory["counters"].get(name, 0) <= 0:
            raise ValidationError(f"required inventory counter is not positive: {name}")
    for name in artifact["required_zero_counters"]:
        value = (
            inventory[name]
            if name in {"parse_errors", "rejected_records"}
            else inventory["counters"].get(name, 0)
        )
        if value != 0:
            raise ValidationError(f"required inventory counter is not zero: {name}")


def _audit_rows_for_source(audit: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    return sorted(
        [row for row in audit["artifacts"] if row["source_id"] == source_id],
        key=lambda row: row["artifact_id"],
    )


def assess_admission_v4(
    *,
    source_id: str,
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    storage_attestation: dict[str, Any],
    source_audit: dict[str, Any],
    publisher_receipts: Iterable[VerifiedPublisherReceipt],
    assessment: dict[str, Any],
    verified_bundle: VerifiedBundle,
    inventories: Iterable[dict[str, Any]],
    quarantine_index: dict[str, Any],
    assessor: str,
    assessed_at: str,
) -> dict[str, Any]:
    validate_source_registry_v4(source_registry)
    validate_evaluation_registry_v4(evaluation_registry)
    validate_storage_attestation_v4(
        storage_attestation, source_registry, evaluated_at=assessed_at
    )
    validate_source_audit_v4(source_audit)
    validate_v4(quarantine_index, "evaluation-evidence.schema.json")
    if quarantine_index.get("record_kind") != "quarantine_index":
        raise ValidationError("expected a v4 quarantine_index")
    sources = [
        item
        for item in source_registry["sources"]
        if item["source_id"] == source_id and item["role"] == "foundation_candidate"
    ]
    if len(sources) != 1:
        raise ValidationError(f"source_id must resolve exactly once: {source_id}")
    source = sources[0]
    if not assessor.strip():
        raise ValidationError("admission assessor must not be empty")
    verify_assessment(
        assessment,
        verified_bundle,
        subject_kind="source",
        subject_id=source_id,
        subject_binding_sha256=canonical_sha256(source),
        required_uses=SOURCE_REQUIRED_USES,
        evaluated_at=assessed_at,
    )
    if assessment["review_id"] != source["licence_review_id"]:
        raise ValidationError("source references another licence assessment")
    if source_audit["registry_sha256"] != canonical_sha256(source_registry):
        raise ValidationError("source audit registry binding mismatch")
    if source_audit["storage_attestation_sha256"] != canonical_sha256(
        storage_attestation
    ):
        raise ValidationError("source audit storage binding mismatch")
    expected_artifacts = {item["artifact_id"] for item in source["artifacts"]}
    rows = _audit_rows_for_source(source_audit, source_id)
    if {row["artifact_id"] for row in rows} != expected_artifacts or not all(
        row["status"] == "verified" for row in rows
    ):
        raise GateBlocked("admission requires every source artifact to be verified")
    publisher_by_artifact = _publisher_by_artifact(publisher_receipts)
    if set(publisher_by_artifact) != expected_artifacts:
        raise GateBlocked("admission requires one publisher receipt per artifact")
    expected_publisher_hashes = sorted(
        value.sha256 for value in publisher_by_artifact.values()
    )
    if not set(expected_publisher_hashes) <= set(
        source_audit["publisher_receipt_sha256s"]
    ):
        raise ValidationError("source audit omits a source publisher receipt")
    inventory_values = list(inventories)
    by_artifact = {item.get("artifact_id"): item for item in inventory_values}
    if len(by_artifact) != len(inventory_values) or set(by_artifact) != expected_artifacts:
        raise GateBlocked("admission requires exactly one inventory per artifact")
    for artifact_id, inventory in by_artifact.items():
        validate_structural_inventory_v4(
            inventory,
            registry=source_registry,
            storage_attestation=storage_attestation,
            source_audit=source_audit,
            publisher_receipt=publisher_by_artifact[artifact_id],
        )
    assessed = _parse_time(assessed_at, "assessed_at")
    latest_inventory = max(
        _parse_time(item["completed_at"], "inventory completed_at")
        for item in inventory_values
    )
    if assessed < latest_inventory:
        raise ValidationError("admission predates its structural inventory")
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "admission_receipt",
        "source_id": source_id,
        "source_registry_sha256": canonical_sha256(source_registry),
        "source_entry_sha256": canonical_sha256(source),
        "evaluation_registry_sha256": canonical_sha256(evaluation_registry),
        "storage_attestation_sha256": canonical_sha256(storage_attestation),
        "drive_observation_sha256": storage_attestation[
            "drive_observation_sha256"
        ],
        "publisher_receipt_sha256s": expected_publisher_hashes,
        "source_audit_sha256": canonical_sha256(source_audit),
        "audited_artifacts_sha256": canonical_sha256(rows),
        "licence_assessment_sha256": canonical_sha256(assessment),
        "evidence_bundle_sha256": verified_bundle.sha256,
        "inventory_sha256s": sorted(
            canonical_sha256(item) for item in inventory_values
        ),
        "quarantine_index_sha256": canonical_sha256(quarantine_index),
        "quarantine_policy_id": "pre-feature-quarantine-v4",
        "decision": "admitted",
        "condition": "admitted_with_mandatory_pre_feature_quarantine",
        "assessed_at": assessed_at,
        "assessor": assessor,
        "training_authorized": False,
    }
    validate_v4(result, "source-evidence.schema.json")
    return result
