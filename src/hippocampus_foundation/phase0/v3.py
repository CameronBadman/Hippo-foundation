"""Phase 0 v3 gate with compound licence evidence and human assessments.

Phase 0 v2 remains unchanged for historical reproducibility.  This module
composes its structural checks with the stricter licensing/v1 authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from hippocampus_foundation.licensing import (
    VerifiedBundle,
    verify_assessment,
)
from hippocampus_foundation.licensing import (
    validate_schema_lock_v1 as validate_licensing_schema_lock_v1,
)
from hippocampus_foundation.licensing import (
    validate_v1 as validate_licensing_v1,
)

from .canonical import canonical_sha256, load_json
from .errors import GateBlocked, ValidationError
from .v2 import (
    evaluate_gate_v2,
    validate_evaluation_registry_v2,
    validate_schema_lock_v2,
    validate_source_audit_v2,
    validate_source_registry_v2,
    validate_storage_attestation_v2,
    validate_structural_inventory_v2,
    validate_v2,
)

SCHEMA_VERSION = "3.0.0"
SOURCE_REQUIRED_USES = frozenset(
    {"acquire", "inventory", "quarantine", "transform", "embed", "commercial_service"}
)
EVALUATION_REQUIRED_USES = frozenset({"acquire", "quarantine", "evaluate"})

FROZEN_SCHEMA_DIGESTS_V3: dict[str, str] = {
    "control-evidence.schema.json": "sha256:79dc2f3485152bf5fde2f286bee0e4d3bf200b1c8794915246cb03552389311a",
    "gate.schema.json": "sha256:1397829b8d3ca0d12ae90068477613eae3d3f67e445f75430ec71ddb2059ec31",
}

_V2_LICENSING_BLOCKER_PREFIXES = (
    "source_licence_not_ready:",
    "evaluation_licence_not_ready:",
    "licence_reviews_invalid:",
)
_V2_ADMISSION_BLOCKER_PREFIXES = ("admission_invalid:",)
_V2_REPLACED_BLOCKERS = frozenset(
    {
        "licensing_not_ready",
        "admission_not_ready",
        "admission_set_mismatch",
    }
)


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def schema_root_v3() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase0" / "v3"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase0" / "v3"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate Phase 0 v3 schema directory")


def load_schema_v3(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v3()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(
            f"invalid Phase 0 v3 schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v3(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v3(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    rendered = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        rendered.append(f"{location}: {error.message}")
    raise ValidationError("; ".join(rendered))


def schema_digests_v3(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v3()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no Phase 0 v3 schemas under {target}")
    return {name: canonical_sha256(load_schema_v3(name, target)) for name in names}


def validate_schema_lock_v3(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v3(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V3:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V3.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V3.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V3.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V3[name] != observed[name]
        )
        raise ValidationError(
            f"Phase 0 v3 schema lock mismatch: missing={missing}, extra={extra}, changed={changed}"
        )
    return observed


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


def _assessment_binding_check(
    *,
    assessment: dict[str, Any],
    verified_bundle: VerifiedBundle,
    review_id: str,
    subject_kind: str,
    subject_id: str,
    subject_binding_sha256: str,
) -> None:
    bundle = verified_bundle.bundle
    expected = {
        "review_id": review_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "subject_binding_sha256": subject_binding_sha256,
    }
    for field, value in expected.items():
        if assessment[field] != value or bundle[field] != value:
            raise ValidationError(f"licence evidence binding mismatch: {field}")
    if assessment["bundle_sha256"] != verified_bundle.sha256:
        raise ValidationError("licence assessment bundle digest mismatch")


def _audit_rows_for_source(
    audit: dict[str, Any], source_id: str
) -> list[dict[str, Any]]:
    return sorted(
        [item for item in audit["artifacts"] if item["source_id"] == source_id],
        key=lambda item: item["artifact_id"],
    )


def _remove_replaced_v2_blockers(blockers: Iterable[str]) -> set[str]:
    return {
        blocker
        for blocker in blockers
        if blocker not in _V2_REPLACED_BLOCKERS
        and not blocker.startswith(_V2_LICENSING_BLOCKER_PREFIXES)
        and not blocker.startswith(_V2_ADMISSION_BLOCKER_PREFIXES)
    }


def evaluate_gate_v3(
    *,
    evaluated_at: str,
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    storage_attestation: dict[str, Any] | None,
    source_audit: dict[str, Any] | None,
    licence_assessments: Iterable[dict[str, Any]] = (),
    verified_bundles: Mapping[str, VerifiedBundle] | None = None,
    seal_receipts: Iterable[dict[str, Any]] = (),
    quarantine_contributions: Iterable[dict[str, Any]] = (),
    quarantine_index: dict[str, Any] | None = None,
    structural_inventories: Iterable[dict[str, Any]] = (),
    admission_receipts: Iterable[dict[str, Any]] = (),
    verified_seal_ids: Iterable[str] = (),
    evaluation_access_events: Mapping[str, Iterable[dict[str, Any]]] | None = None,
    evaluation_access_heads: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate v3 evidence. This function can never authorize training."""

    assessments = list(licence_assessments)
    bundles = dict(verified_bundles or {})
    inventories = list(structural_inventories)
    receipts = list(admission_receipts)
    base = evaluate_gate_v2(
        evaluated_at=evaluated_at,
        source_registry=source_registry,
        evaluation_registry=evaluation_registry,
        storage_attestation=storage_attestation,
        source_audit=source_audit,
        licence_reviews=(),
        verified_terms_sha256={},
        seal_receipts=seal_receipts,
        quarantine_contributions=quarantine_contributions,
        quarantine_index=quarantine_index,
        structural_inventories=inventories,
        admission_receipts=(),
        verified_seal_ids=verified_seal_ids,
        evaluation_access_events=evaluation_access_events,
        evaluation_access_heads=evaluation_access_heads,
    )
    blockers = _remove_replaced_v2_blockers(base["blockers"])
    evidence = set(base["evidence"])

    try:
        v2_schemas = validate_schema_lock_v2()
        v3_schemas = validate_schema_lock_v3()
        licensing_schemas = validate_licensing_schema_lock_v1()
        contracts_frozen = True
        evidence.add(f"phase0_v3_schemas:{canonical_sha256(v3_schemas)}")
        evidence.add(f"licensing_v1_schemas:{canonical_sha256(licensing_schemas)}")
        evidence.add(f"phase0_v2_dependency_schemas:{canonical_sha256(v2_schemas)}")
    except Exception as exc:
        contracts_frozen = False
        blockers.add(f"contracts_invalid:{type(exc).__name__}:{exc}")

    try:
        validate_source_registry_v2(source_registry)
        validate_evaluation_registry_v2(evaluation_registry)
        registries_valid = True
    except Exception:
        registries_valid = False

    try:
        assessments_by_id = _assessment_by_id(assessments)
    except Exception as exc:
        assessments_by_id = {}
        blockers.add(f"licence_assessments_invalid:{type(exc).__name__}:{exc}")

    expected_reviews: dict[str, tuple[str, str, str, frozenset[str]]] = {}
    if registries_valid:
        for source in source_registry["sources"]:
            if source["role"] != "foundation_candidate":
                continue
            expected_reviews[source["licence_review_id"]] = (
                "source",
                source["source_id"],
                canonical_sha256(source),
                SOURCE_REQUIRED_USES,
            )
        for dataset in evaluation_registry["datasets"]:
            expected_reviews[dataset["licence_review_id"]] = (
                "evaluation",
                dataset["dataset_id"],
                canonical_sha256(dataset),
                EVALUATION_REQUIRED_USES,
            )

    licensing_evidence_verified = registries_valid and bool(expected_reviews)
    licensing_ready = licensing_evidence_verified
    if set(assessments_by_id) != set(expected_reviews):
        licensing_evidence_verified = False
        licensing_ready = False
        blockers.add("licence_assessment_set_mismatch")
    if set(bundles) != set(expected_reviews):
        licensing_evidence_verified = False
        licensing_ready = False
        blockers.add("licence_evidence_bundle_set_mismatch")

    for review_id, (
        kind,
        subject_id,
        binding_sha256,
        required_uses,
    ) in expected_reviews.items():
        assessment = assessments_by_id.get(review_id)
        verified_bundle = bundles.get(review_id)
        try:
            if assessment is None or verified_bundle is None:
                raise ValidationError(
                    "assessment or verified evidence bundle is missing"
                )
            _assessment_binding_check(
                assessment=assessment,
                verified_bundle=verified_bundle,
                review_id=review_id,
                subject_kind=kind,
                subject_id=subject_id,
                subject_binding_sha256=binding_sha256,
            )
            evidence.add(f"licence_bundle:{review_id}:{verified_bundle.sha256}")
            evidence.add(
                f"licence_assessment:{review_id}:{canonical_sha256(assessment)}"
            )
        except Exception as exc:
            licensing_evidence_verified = False
            licensing_ready = False
            blockers.add(
                f"{kind}_licence_evidence_invalid:{subject_id}:{type(exc).__name__}:{exc}"
            )
            continue
        try:
            verify_assessment(
                assessment,
                verified_bundle,
                subject_kind=kind,
                subject_id=subject_id,
                subject_binding_sha256=binding_sha256,
                required_uses=required_uses,
                evaluated_at=evaluated_at,
            )
        except Exception as exc:
            licensing_ready = False
            blockers.add(
                f"{kind}_licence_not_ready:{subject_id}:{type(exc).__name__}:{exc}"
            )
    if not licensing_evidence_verified:
        blockers.add("licensing_evidence_not_verified")
    if not licensing_ready:
        blockers.add("licensing_not_ready")

    admission_ready = (
        base["structural_inventory_ready"]
        and licensing_ready
        and base["quarantine_ready"]
    )
    receipt_by_source: dict[str, dict[str, Any]] = {}
    expected_sources = {
        source["source_id"]
        for source in source_registry.get("sources", [])
        if source.get("role") == "foundation_candidate"
    }
    if (
        admission_ready
        and source_audit is not None
        and storage_attestation is not None
        and quarantine_index is not None
    ):
        for receipt in receipts:
            try:
                validate_v3(receipt, "control-evidence.schema.json")
                source_id = receipt["source_id"]
                if source_id in receipt_by_source:
                    raise ValidationError(
                        f"duplicate v3 admission receipt: {source_id}"
                    )
                source = next(
                    item
                    for item in source_registry["sources"]
                    if item["source_id"] == source_id
                )
                review_id = source["licence_review_id"]
                assessment = assessments_by_id[review_id]
                verified_bundle = bundles[review_id]
                rows = _audit_rows_for_source(source_audit, source_id)
                inventory_hashes = sorted(
                    canonical_sha256(item)
                    for item in inventories
                    if item.get("source_id") == source_id
                )
                bindings = {
                    "source_registry_sha256": canonical_sha256(source_registry),
                    "source_entry_sha256": canonical_sha256(source),
                    "audited_artifacts_sha256": canonical_sha256(rows),
                    "storage_attestation_sha256": canonical_sha256(storage_attestation),
                    "licence_assessment_sha256": canonical_sha256(assessment),
                    "evidence_bundle_sha256": verified_bundle.sha256,
                    "inventory_sha256s": inventory_hashes,
                    "quarantine_index_sha256": canonical_sha256(quarantine_index),
                }
                for field, expected in bindings.items():
                    if receipt[field] != expected:
                        raise ValidationError(f"v3 admission binding mismatch: {field}")
                if receipt["decision"] != "admitted":
                    raise ValidationError("source admission is blocked")
                receipt_by_source[source_id] = receipt
                evidence.add(f"admission_v3:{source_id}:{canonical_sha256(receipt)}")
            except Exception as exc:
                admission_ready = False
                blockers.add(f"admission_v3_invalid:{type(exc).__name__}:{exc}")
        if set(receipt_by_source) != expected_sources:
            admission_ready = False
            blockers.add("admission_v3_set_mismatch")
    else:
        admission_ready = False
    if not admission_ready:
        blockers.add("admission_not_ready")

    foundation_acquisition_authorized = all(
        [
            contracts_frozen,
            base["storage_identity_ready"],
            base["source_audit_ready"],
            licensing_ready,
            base["public_confirmatory_ready"],
            base["quarantine_ready"],
        ]
    )
    foundation_transform_ready = all(
        [
            foundation_acquisition_authorized,
            base["structural_inventory_ready"],
            admission_ready,
        ]
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": "phase0-public-foundation-v3",
        "evaluated_at": evaluated_at,
        "contracts_frozen": contracts_frozen,
        "storage_identity_ready": base["storage_identity_ready"],
        "source_audit_ready": base["source_audit_ready"],
        "licensing_evidence_verified": licensing_evidence_verified,
        "licensing_ready": licensing_ready,
        "public_confirmatory_ready": base["public_confirmatory_ready"],
        "quarantine_ready": base["quarantine_ready"],
        "structural_inventory_ready": base["structural_inventory_ready"],
        "admission_ready": admission_ready,
        "foundation_acquisition_authorized": foundation_acquisition_authorized,
        "foundation_transform_ready": foundation_transform_ready,
        "training_authorized": False,
        "blockers": sorted(blockers),
        "evidence": sorted(evidence),
    }
    validate_v3(report, "gate.schema.json")
    return report


def assess_admission_v3(
    *,
    source_id: str,
    registry: dict[str, Any],
    storage_attestation: dict[str, Any],
    source_audit: dict[str, Any],
    assessment: dict[str, Any],
    verified_bundle: VerifiedBundle,
    inventories: Iterable[dict[str, Any]],
    quarantine_index: dict[str, Any],
    assessor: str,
    assessed_at: str,
) -> dict[str, Any]:
    """Build a v3 admission receipt after all bound evidence is valid."""

    validate_source_registry_v2(registry)
    validate_storage_attestation_v2(
        storage_attestation, registry, evaluated_at=assessed_at
    )
    validate_source_audit_v2(source_audit)
    validate_v2(quarantine_index, "evaluation-evidence.schema.json")
    source = next(
        (
            item
            for item in registry["sources"]
            if item["source_id"] == source_id and item["role"] == "foundation_candidate"
        ),
        None,
    )
    if source is None:
        raise ValidationError(f"unknown foundation source: {source_id}")
    verify_assessment(
        assessment,
        verified_bundle,
        subject_kind="source",
        subject_id=source_id,
        subject_binding_sha256=canonical_sha256(source),
        required_uses=SOURCE_REQUIRED_USES,
        evaluated_at=assessed_at,
    )
    inventory_values = list(inventories)
    for inventory in inventory_values:
        if inventory.get("source_id") == source_id:
            validate_structural_inventory_v2(inventory, registry, source_audit)
    rows = _audit_rows_for_source(source_audit, source_id)
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "admission_receipt",
        "source_id": source_id,
        "source_registry_sha256": canonical_sha256(registry),
        "source_entry_sha256": canonical_sha256(source),
        "audited_artifacts_sha256": canonical_sha256(rows),
        "storage_attestation_sha256": canonical_sha256(storage_attestation),
        "licence_assessment_sha256": canonical_sha256(assessment),
        "evidence_bundle_sha256": verified_bundle.sha256,
        "inventory_sha256s": sorted(
            canonical_sha256(item)
            for item in inventory_values
            if item.get("source_id") == source_id
        ),
        "quarantine_index_sha256": canonical_sha256(quarantine_index),
        "decision": "admitted",
        "condition": "admitted_with_mandatory_quarantine",
        "assessed_at": assessed_at,
        "assessor": assessor,
    }
    validate_v3(result, "control-evidence.schema.json")
    return result


def require_phase0_transform_gate_v3(gate: dict[str, Any]) -> str:
    validate_v3(gate, "gate.schema.json")
    required_controls = (
        "contracts_frozen",
        "storage_identity_ready",
        "source_audit_ready",
        "licensing_evidence_verified",
        "licensing_ready",
        "public_confirmatory_ready",
        "quarantine_ready",
        "structural_inventory_ready",
        "admission_ready",
        "foundation_acquisition_authorized",
        "foundation_transform_ready",
    )
    if not all(gate[field] is True for field in required_controls) or gate["blockers"]:
        raise GateBlocked("Phase 0 v3 has not authorized foundation transformation")
    if gate["training_authorized"] is not False:
        raise GateBlocked("Phase 0 v3 training invariant is violated")
    return canonical_sha256(gate)
