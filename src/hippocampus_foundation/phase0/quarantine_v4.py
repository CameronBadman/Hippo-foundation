"""Tri-state pre-feature quarantine matching for Phase 0 v4."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from .canonical import canonical_sha256, sha256_bytes
from .errors import GateBlocked, QuarantineError, ValidationError
from .quarantine import (
    fingerprint_text,
    jaccard_similarity,
    normalize_identifier,
    normalized_text_sha256,
)
from .v4_contracts import SCHEMA_VERSION_V4, validate_v4


MATCHER_POLICY_ID_V4 = "pre-feature-quarantine-v4"
NEAR_MATCH_THRESHOLDS_V4: Mapping[str, float] = {
    "character5": 0.90,
    "word5": 0.85,
}


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _normalized_identifier(value: Mapping[str, Any]) -> dict[str, Any]:
    item = normalize_identifier(
        str(value["namespace"]), str(value["value"]), value.get("source_version")
    )
    return {
        "namespace": item.namespace,
        "value": item.value,
        "source_version": item.source_version,
    }


def build_source_record_descriptor_v4(
    *,
    descriptor_id: str,
    source_id: str,
    artifact_id: str,
    record_id: str,
    raw_content: bytes | None,
    text: str | None,
    identifiers: Iterable[Mapping[str, Any]],
    dependency_units: Iterable[Mapping[str, Any]],
    lineage_complete: bool,
    derived_at: str,
) -> dict[str, Any]:
    """Derive one-way selectors without retaining raw text or feature output."""

    normalized_identifiers = sorted(
        (_normalized_identifier(item) for item in identifiers), key=canonical_sha256
    )
    normalized_dependencies = sorted(
        (_normalized_identifier(item) for item in dependency_units),
        key=canonical_sha256,
    )
    fingerprints = []
    if text is not None:
        fingerprints.append(fingerprint_text(text, f"{descriptor_id}-text"))
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "source_record_descriptor",
        "descriptor_id": descriptor_id,
        "source_id": source_id,
        "artifact_id": artifact_id,
        "record_id": record_id,
        "raw_sha256": sha256_bytes(raw_content) if raw_content is not None else None,
        "normalized_sha256": (
            normalized_text_sha256(text) if text is not None else None
        ),
        "identifiers": normalized_identifiers,
        "dependency_units": normalized_dependencies,
        "lineage_complete": lineage_complete,
        "fingerprints": fingerprints,
        "derived_at": derived_at,
        "contains_features": False,
        "contains_embeddings": False,
        "training_authorized": False,
    }
    validate_v4(result, "quarantine-decision.schema.json")
    return result


def match_quarantine_record_v4(
    descriptor: dict[str, Any],
    quarantine_index: dict[str, Any],
    *,
    checked_at: str,
) -> dict[str, Any]:
    validate_v4(descriptor, "quarantine-decision.schema.json")
    if descriptor.get("record_kind") != "source_record_descriptor":
        raise ValidationError("expected a source_record_descriptor")
    validate_v4(quarantine_index, "evaluation-evidence.schema.json")
    if quarantine_index.get("record_kind") != "quarantine_index":
        raise ValidationError("expected a quarantine_index")
    if quarantine_index["closure_policy_id"] != "quarantine-closure-v4":
        raise QuarantineError("quarantine index uses another closure policy")
    if _parse_time(checked_at, "checked_at") < _parse_time(
        descriptor["derived_at"], "descriptor derived_at"
    ):
        raise ValidationError("quarantine decision predates its descriptor")

    index_identifiers = {
        canonical_sha256(_normalized_identifier(item)): item
        for item in quarantine_index["identifiers"]
    }
    matches: list[dict[str, str]] = []
    reasons: set[str] = set()
    for item in descriptor["identifiers"]:
        key = canonical_sha256(_normalized_identifier(item))
        if key in index_identifiers:
            reasons.add("identifier_match")
            matches.append({"kind": "identifier", "reference": key})
    for item in descriptor["dependency_units"]:
        key = canonical_sha256(_normalized_identifier(item))
        if key in index_identifiers:
            reasons.add("dependency_family_match")
            matches.append({"kind": "dependency_family", "reference": key})
    raw_sha256 = descriptor["raw_sha256"]
    if raw_sha256 is not None and raw_sha256 in set(quarantine_index["raw_hashes"]):
        reasons.add("raw_hash_match")
        matches.append({"kind": "raw_hash", "reference": raw_sha256})
    normalized_sha256 = descriptor["normalized_sha256"]
    if normalized_sha256 is not None and normalized_sha256 in set(
        quarantine_index["normalized_hashes"]
    ):
        reasons.add("normalized_hash_match")
        matches.append(
            {"kind": "normalized_hash", "reference": normalized_sha256}
        )
    for candidate in descriptor["fingerprints"]:
        for held_out in quarantine_index["fingerprints"]:
            if candidate["kind"] != held_out["kind"]:
                continue
            similarity = jaccard_similarity(
                candidate["shingle_hashes"], held_out["shingle_hashes"]
            )
            threshold = NEAR_MATCH_THRESHOLDS_V4[candidate["kind"]]
            if similarity >= threshold:
                kind = candidate["kind"]
                reasons.add(f"{kind}_near_match")
                matches.append(
                    {"kind": kind, "reference": held_out["fingerprint_id"]}
                )

    has_exclusion = any(reason.endswith("_match") for reason in reasons)
    selector_count = sum(
        (
            raw_sha256 is not None,
            normalized_sha256 is not None,
            bool(descriptor["identifiers"]),
            bool(descriptor["dependency_units"]),
            bool(descriptor["fingerprints"]),
        )
    )
    if has_exclusion:
        decision = "excluded"
    elif not descriptor["lineage_complete"]:
        reasons.add("lineage_incomplete")
        decision = "undetermined"
    elif selector_count == 0:
        reasons.add("selector_evidence_missing")
        decision = "undetermined"
    else:
        decision = "clear"
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "quarantine_decision",
        "descriptor_sha256": canonical_sha256(descriptor),
        "quarantine_index_sha256": canonical_sha256(quarantine_index),
        "matcher_policy_id": MATCHER_POLICY_ID_V4,
        "decision": decision,
        "reasons": sorted(reasons),
        "matches": sorted(
            {canonical_sha256(item): item for item in matches}.values(),
            key=canonical_sha256,
        ),
        "features_permitted": decision == "clear",
        "checked_at": checked_at,
        "training_authorized": False,
    }
    validate_quarantine_decision_v4(result)
    return result


def validate_quarantine_decision_v4(receipt: dict[str, Any]) -> None:
    validate_v4(receipt, "quarantine-decision.schema.json")
    if receipt.get("record_kind") != "quarantine_decision":
        raise ValidationError("expected a quarantine_decision")
    decision = receipt["decision"]
    if receipt["features_permitted"] != (decision == "clear"):
        raise ValidationError("quarantine features_permitted is inconsistent")
    if decision == "clear" and (receipt["reasons"] or receipt["matches"]):
        raise ValidationError("clear quarantine decision carries match evidence")
    if decision == "excluded" and not receipt["matches"]:
        raise ValidationError("excluded quarantine decision lacks match evidence")
    if decision == "undetermined" and not set(receipt["reasons"]) & {
        "lineage_incomplete",
        "selector_evidence_missing",
    }:
        raise ValidationError("undetermined decision lacks an uncertainty reason")


def require_clear_quarantine_receipt_v4(
    receipt: dict[str, Any],
    *,
    descriptor: dict[str, Any],
    quarantine_index: dict[str, Any],
) -> str:
    validate_quarantine_decision_v4(receipt)
    if receipt["descriptor_sha256"] != canonical_sha256(descriptor):
        raise GateBlocked("quarantine receipt descriptor binding mismatch")
    if receipt["quarantine_index_sha256"] != canonical_sha256(quarantine_index):
        raise GateBlocked("quarantine receipt index binding mismatch")
    expected = match_quarantine_record_v4(
        descriptor,
        quarantine_index,
        checked_at=receipt["checked_at"],
    )
    if receipt != expected:
        raise GateBlocked("quarantine receipt is not reproducible")
    if receipt["decision"] != "clear" or not receipt["features_permitted"]:
        raise GateBlocked("source record has not cleared pre-feature quarantine")
    return canonical_sha256(receipt)
