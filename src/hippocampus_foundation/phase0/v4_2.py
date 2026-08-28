"""Phase 0 v4.2 internal-authority and live-acquisition gate."""

# Evidence-family failures are deliberately converted to structured blockers.
# ruff: noqa: BLE001

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hippocampus_foundation.licensing import VerifiedBundle

from .authority_v4_2 import (
    VerifiedAcquisitionAuthorization,
    VerifiedOAuthAuthority,
    validate_acquisition_authorization_time,
    validate_authority_policy,
    validate_drive_access_proof,
    validate_oauth_authority_time,
)
from .canonical import canonical_sha256
from .errors import GateBlocked, IntegrityError, ValidationError
from .evaluation_firewall import VerifiedSealReceipt
from .execution_v4_1 import VerifiedMaterialization
from .external_evidence import (
    VerifiedAccessAnchor,
    VerifiedPublisherReceipt,
)
from .v4_1 import evaluate_gate_v4_1
from .v4_2_contracts import (
    SCHEMA_VERSION_V4_2,
    validate_schema_lock_v4_2,
    validate_v4_2,
)


@dataclass(frozen=True)
class AcquisitionEvidenceBundle:
    receipt: dict[str, Any]
    pre_source_audit: dict[str, Any]
    pre_access_proof: dict[str, Any]
    post_access_proof: dict[str, Any]
    authorization_gate: dict[str, Any]


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _block(
    blockers: set[tuple[str, str, str]],
    code: str,
    subject_kind: str,
    subject_id: str,
) -> None:
    blockers.add((code, subject_kind, subject_id))


def _evidence(
    evidence: set[tuple[str, str, str]], kind: str, subject_id: str, sha256: str
) -> None:
    evidence.add((kind, subject_id, sha256))


def _render_blockers(values: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [
        {"code": code, "subject_kind": kind, "subject_id": subject_id}
        for code, kind, subject_id in sorted(values)
    ]


def _render_evidence(values: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [
        {"kind": kind, "subject_id": subject_id, "sha256": sha256}
        for kind, subject_id, sha256 in sorted(values)
    ]


def _target_artifacts(source_registry: Mapping[str, Any] | None) -> dict[str, dict]:
    if source_registry is None:
        return {}
    result: dict[str, dict] = {}
    for source in source_registry.get("sources", []):
        for artifact in source["artifacts"]:
            if artifact["availability"] != "acquisition_target":
                continue
            artifact_id = artifact["artifact_id"]
            if artifact_id in result:
                raise ValidationError(f"duplicate acquisition target: {artifact_id}")
            result[artifact_id] = artifact
    return result


def _authorization_by_artifact(
    values: Iterable[VerifiedAcquisitionAuthorization],
) -> dict[str, VerifiedAcquisitionAuthorization]:
    result: dict[str, VerifiedAcquisitionAuthorization] = {}
    for value in values:
        artifact_id = value.receipt["artifact_id"]
        if artifact_id in result:
            raise ValidationError(f"duplicate acquisition authorization: {artifact_id}")
        result[artifact_id] = value
    return result


def evaluate_gate_v4_2(
    *,
    evaluated_at: str,
    source_registries: Sequence[dict[str, Any]],
    evaluation_registries: Sequence[dict[str, Any]],
    drive_observation: dict[str, Any] | None = None,
    storage_attestation: dict[str, Any] | None = None,
    publisher_receipts: Iterable[VerifiedPublisherReceipt] = (),
    source_audit: dict[str, Any] | None = None,
    licence_assessments: Iterable[dict[str, Any]] = (),
    verified_bundles: Mapping[str, VerifiedBundle] | None = None,
    materializations: Iterable[VerifiedMaterialization] = (),
    quarantine_contributions: Iterable[dict[str, Any]] = (),
    quarantine_index: dict[str, Any] | None = None,
    verified_seals: Iterable[VerifiedSealReceipt] = (),
    evaluation_access_events: Mapping[str, Iterable[dict[str, Any]]] | None = None,
    verified_access_anchors: Mapping[str, VerifiedAccessAnchor] | None = None,
    structural_inventories: Iterable[dict[str, Any]] = (),
    admission_receipts: Iterable[dict[str, Any]] = (),
    authority_policy: dict[str, Any] | None = None,
    approved_policy_sha256: str | None = None,
    oauth_authority: VerifiedOAuthAuthority | None = None,
    drive_access_proof: dict[str, Any] | None = None,
    acquisition_authorizations: Iterable[VerifiedAcquisitionAuthorization] = (),
    acquisition_evidence: Iterable[AcquisitionEvidenceBundle] = (),
) -> dict[str, Any]:
    """Add Internal OAuth and acquisition authority to the complete v4.1 graph."""

    publisher_receipts = list(publisher_receipts)
    licence_assessments = list(licence_assessments)
    verified_bundles = dict(verified_bundles or {})
    materializations = list(materializations)
    quarantine_contributions = list(quarantine_contributions)
    verified_seals = list(verified_seals)
    evaluation_access_events = {
        key: list(values) for key, values in (evaluation_access_events or {}).items()
    }
    verified_access_anchors = dict(verified_access_anchors or {})
    structural_inventories = list(structural_inventories)
    admission_receipts = list(admission_receipts)
    authorizations = list(acquisition_authorizations or ())
    evidence_bundles = list(acquisition_evidence or ())
    base = evaluate_gate_v4_1(
        evaluated_at=evaluated_at,
        source_registries=source_registries,
        evaluation_registries=evaluation_registries,
        drive_observation=drive_observation,
        storage_attestation=storage_attestation,
        publisher_receipts=publisher_receipts,
        source_audit=source_audit,
        licence_assessments=licence_assessments,
        verified_bundles=verified_bundles,
        materializations=materializations,
        quarantine_contributions=quarantine_contributions,
        quarantine_index=quarantine_index,
        verified_seals=verified_seals,
        evaluation_access_events=evaluation_access_events,
        verified_access_anchors=verified_access_anchors,
        structural_inventories=structural_inventories,
        admission_receipts=admission_receipts,
    )
    blockers = {
        (item["code"], item["subject_kind"], item["subject_id"])
        for item in base["blockers"]
    }
    evidence = {
        (item["kind"], item["subject_id"], item["sha256"])
        for item in base["evidence_bindings"]
    }

    contracts_frozen = base["contracts_frozen"]
    try:
        lock = validate_schema_lock_v4_2()
        _evidence(evidence, "schema_lock", "phase0_v4_2", canonical_sha256(lock))
    except Exception:
        contracts_frozen = False
        _block(blockers, "contracts_invalid", "gate", "phase0-v4.2")

    policy_sha256 = None
    if authority_policy is None:
        _block(
            blockers,
            "oauth_authority_policy_missing",
            "authority",
            "entor-workspace",
        )
    else:
        try:
            policy_sha256 = validate_authority_policy(
                authority_policy,
                approved_policy_sha256=approved_policy_sha256,
            )
            _evidence(
                evidence,
                "oauth_authority_policy",
                authority_policy["policy_id"],
                policy_sha256,
            )
        except Exception:
            _block(
                blockers,
                "oauth_authority_policy_invalid",
                "authority",
                "entor-workspace",
            )

    oauth_authority_ready = False
    if oauth_authority is None:
        _block(
            blockers,
            "oauth_authority_missing",
            "authority",
            "drive-readonly-client",
        )
    elif policy_sha256 is not None:
        try:
            receipt = oauth_authority.receipt
            validate_v4_2(receipt, "execution-evidence.schema.json")
            if receipt["record_kind"] != "oauth_authority_receipt":
                raise ValidationError("wrong OAuth authority receipt kind")
            if oauth_authority.sha256 != canonical_sha256(receipt):
                raise IntegrityError("OAuth authority wrapper digest mismatch")
            if receipt["authority_policy_sha256"] != policy_sha256:
                raise ValidationError("OAuth authority policy mismatch")
            if receipt["payload_sha256"] != canonical_sha256(oauth_authority.payload):
                raise IntegrityError("OAuth authority payload digest mismatch")
            if receipt["signature_sha256"] != oauth_authority.signature_sha256:
                raise IntegrityError("OAuth authority signature digest mismatch")
            if receipt["public_key_sha256"] != oauth_authority.public_key_sha256:
                raise IntegrityError("OAuth authority public-key digest mismatch")
            if (
                receipt["signing_key_fingerprint"]
                != oauth_authority.signing_key_fingerprint
            ):
                raise IntegrityError("OAuth authority signer mismatch")
            if (
                receipt["signing_key_fingerprint"]
                not in authority_policy["oauth_authority_signing_key_fingerprints"]
            ):
                raise ValidationError("OAuth authority signer is not trusted")
            authority_bindings = {
                "authority_id": "authority_id",
                "authority_policy_sha256": "authority_policy_sha256",
                "oauth_config_sha256": "oauth_config_sha256",
                "oauth_client_id_sha256": "oauth_client_id_sha256",
                "workspace_domain": "workspace_domain",
                "cloud_project_number": "cloud_project_number",
                "provider_resource_id": "provider_resource_id",
                "root_resource_id": "root_resource_id",
                "marker_file_id": "marker_file_id",
                "marker_sha256": "marker_sha256",
                "approved_at": "approved_at",
                "valid_until": "valid_until",
                "signing_key_fingerprint": "signing_key_fingerprint",
            }
            for receipt_field, payload_field in authority_bindings.items():
                if receipt[receipt_field] != oauth_authority.payload[payload_field]:
                    raise ValidationError(
                        f"OAuth authority payload mismatch: {receipt_field}"
                    )
            validate_oauth_authority_time(oauth_authority, evaluated_at=evaluated_at)
            oauth_authority_ready = True
            _evidence(
                evidence,
                "oauth_authority_receipt",
                receipt["authority_id"],
                oauth_authority.sha256,
            )
            _evidence(
                evidence,
                "oauth_authority_signature",
                receipt["authority_id"],
                oauth_authority.signature_sha256,
            )
            _evidence(
                evidence,
                "oauth_authority_public_key",
                receipt["authority_id"],
                oauth_authority.public_key_sha256,
            )
        except Exception:
            _block(
                blockers,
                "oauth_authority_invalid",
                "authority",
                "drive-readonly-client",
            )
    if not oauth_authority_ready:
        _block(
            blockers,
            "oauth_authority_not_ready",
            "authority",
            "drive-readonly-client",
        )

    same_resource_ready = False
    if drive_access_proof is None:
        _block(
            blockers,
            "drive_access_proof_missing",
            "storage",
            "drive_lake",
        )
    elif (
        oauth_authority_ready
        and oauth_authority is not None
        and storage_attestation is not None
    ):
        try:
            validate_drive_access_proof(
                drive_access_proof,
                authority=oauth_authority,
                storage_attestation=storage_attestation,
                evaluated_at=evaluated_at,
            )
            same_resource_ready = True
            _evidence(
                evidence,
                "drive_access_proof",
                storage_attestation["locator_id"],
                canonical_sha256(drive_access_proof),
            )
        except Exception:
            _block(
                blockers,
                "drive_access_proof_invalid",
                "storage",
                "drive_lake",
            )
    if not same_resource_ready:
        _block(
            blockers,
            "same_resource_not_ready",
            "storage",
            "drive_lake",
        )

    source_tip = source_registries[-1] if source_registries else None
    targets = _target_artifacts(source_tip)
    foundation_acquisition_ready = all(
        (
            contracts_frozen,
            base["foundation_acquisition_authorized"],
            oauth_authority_ready,
            same_resource_ready,
            bool(targets),
        )
    )
    if not foundation_acquisition_ready:
        _block(
            blockers,
            "foundation_acquisition_not_ready",
            "acquisition",
            "foundation",
        )

    acquisition_authorization_ready = False
    authorization_by_artifact: dict[str, VerifiedAcquisitionAuthorization] = {}
    authorization_set_valid = False
    try:
        authorization_by_artifact = _authorization_by_artifact(authorizations)
        if set(authorization_by_artifact) != set(targets):
            raise ValidationError("acquisition authorization set mismatch")
        for artifact_id, authorization in authorization_by_artifact.items():
            receipt = authorization.receipt
            validate_v4_2(receipt, "execution-evidence.schema.json")
            if receipt["record_kind"] != "acquisition_authorization_receipt":
                raise ValidationError("wrong acquisition authorization receipt kind")
            if authorization.sha256 != canonical_sha256(receipt):
                raise IntegrityError("acquisition authorization wrapper mismatch")
            if receipt["artifact_id"] != artifact_id:
                raise ValidationError("acquisition authorization artifact mismatch")
            if receipt["payload_sha256"] != canonical_sha256(authorization.payload):
                raise IntegrityError("acquisition authorization payload mismatch")
            if receipt["signature_sha256"] != authorization.signature_sha256:
                raise IntegrityError("acquisition authorization signature mismatch")
            if receipt["public_key_sha256"] != authorization.public_key_sha256:
                raise IntegrityError("acquisition authorization public-key mismatch")
            if (
                receipt["signing_key_fingerprint"]
                != authorization.signing_key_fingerprint
            ):
                raise IntegrityError("acquisition authorization signer mismatch")
            if (
                oauth_authority is None
                or receipt["oauth_authority_receipt_sha256"] != oauth_authority.sha256
            ):
                raise ValidationError("acquisition OAuth authority mismatch")
            if source_tip is None or receipt[
                "source_registry_sha256"
            ] != canonical_sha256(source_tip):
                raise ValidationError("acquisition source registry mismatch")
            if storage_attestation is None or receipt[
                "storage_attestation_sha256"
            ] != canonical_sha256(storage_attestation):
                raise ValidationError("acquisition storage attestation mismatch")
            artifact = targets[artifact_id]
            authorization_bindings = {
                "authority_policy_sha256": policy_sha256,
                "artifact_id": artifact_id,
                "source_registry_sha256": receipt["source_registry_sha256"],
                "artifact_entry_sha256": canonical_sha256(artifact),
                "oauth_authority_receipt_sha256": oauth_authority.sha256,
                "storage_attestation_sha256": canonical_sha256(storage_attestation),
                "provider_resource_id": storage_attestation["provider_resource_id"],
                "root_resource_id": storage_attestation["root_resource_id"],
                "expected_bytes": artifact["expected_bytes"],
                "byte_ceiling": receipt["byte_ceiling"],
                "authorized_at": receipt["authorized_at"],
                "valid_until": receipt["valid_until"],
                "signing_key_fingerprint": receipt["signing_key_fingerprint"],
            }
            for field, expected in authorization_bindings.items():
                if authorization.payload[field] != expected:
                    raise ValidationError(
                        f"acquisition authorization payload mismatch: {field}"
                    )
            _evidence(
                evidence,
                "acquisition_authorization_receipt",
                artifact_id,
                authorization.sha256,
            )
        authorization_set_valid = bool(targets)
    except Exception:
        if authorizations and not base["foundation_bytes_ready"]:
            _block(
                blockers,
                "acquisition_authorization_invalid",
                "acquisition",
                "foundation",
            )
    if authorization_set_valid and foundation_acquisition_ready:
        try:
            for authorization in authorization_by_artifact.values():
                validate_acquisition_authorization_time(
                    authorization, evaluated_at=evaluated_at
                )
            acquisition_authorization_ready = True
        except Exception:
            if not base["foundation_bytes_ready"]:
                _block(
                    blockers,
                    "acquisition_authorization_invalid",
                    "acquisition",
                    "foundation",
                )
    if not acquisition_authorization_ready and not base["foundation_bytes_ready"]:
        _block(
            blockers,
            "acquisition_authorization_missing",
            "acquisition",
            "foundation",
        )

    foundation_acquisition_authorized = (
        foundation_acquisition_ready and acquisition_authorization_ready
    )

    evidence_by_artifact: dict[str, AcquisitionEvidenceBundle] = {}
    acquisition_evidence_ready = False
    try:
        for bundle in evidence_bundles:
            receipt = bundle.receipt
            validate_v4_2(receipt, "execution-evidence.schema.json")
            if receipt["record_kind"] != "source_acquisition_receipt":
                raise ValidationError("wrong source acquisition receipt kind")
            artifact_id = receipt["artifact_id"]
            if artifact_id in evidence_by_artifact:
                raise ValidationError("duplicate source acquisition evidence")
            if artifact_id not in targets:
                raise ValidationError(
                    "source acquisition evidence uses another artifact"
                )
            artifact = targets[artifact_id]
            authorization = authorization_by_artifact.get(artifact_id)
            if authorization is None:
                raise ValidationError("source acquisition lacks signed authorization")
            validate_v4_2(bundle.authorization_gate, "gate.schema.json")
            if (
                bundle.authorization_gate["foundation_acquisition_authorized"]
                is not True
            ):
                raise ValidationError("source acquisition gate was not authorized")
            if receipt["authorization_gate_sha256"] != canonical_sha256(
                bundle.authorization_gate
            ):
                raise IntegrityError("source acquisition gate digest mismatch")
            if (
                receipt["acquisition_authorization_receipt_sha256"]
                != authorization.sha256
            ):
                raise ValidationError("source acquisition authorization mismatch")
            if (
                oauth_authority is None
                or receipt["oauth_authority_receipt_sha256"] != oauth_authority.sha256
            ):
                raise ValidationError("source acquisition OAuth authority mismatch")
            if source_tip is None or receipt[
                "source_registry_sha256"
            ] != canonical_sha256(source_tip):
                raise ValidationError("source acquisition registry mismatch")
            if receipt["artifact_entry_sha256"] != canonical_sha256(artifact):
                raise ValidationError("source acquisition artifact entry mismatch")
            if storage_attestation is None or receipt[
                "storage_attestation_sha256"
            ] != canonical_sha256(storage_attestation):
                raise ValidationError("source acquisition storage mismatch")
            if (
                receipt["provider_resource_id"]
                != storage_attestation["provider_resource_id"]
            ):
                raise ValidationError("source acquisition shared-Drive mismatch")
            if receipt["root_resource_id"] != storage_attestation["root_resource_id"]:
                raise ValidationError("source acquisition root-folder mismatch")
            if receipt["pre_source_audit_sha256"] != canonical_sha256(
                bundle.pre_source_audit
            ):
                raise IntegrityError("pre-acquisition source-audit digest mismatch")
            if receipt["destination_filename"] != artifact["filename"]:
                raise ValidationError("source acquisition filename mismatch")
            if receipt["bytes"] != artifact["expected_bytes"]:
                raise ValidationError("source acquisition byte count mismatch")
            if receipt["pre_access_proof_sha256"] != canonical_sha256(
                bundle.pre_access_proof
            ):
                raise IntegrityError("pre-acquisition proof digest mismatch")
            if receipt["post_access_proof_sha256"] != canonical_sha256(
                bundle.post_access_proof
            ):
                raise IntegrityError("post-acquisition proof digest mismatch")
            if storage_attestation is None or oauth_authority is None:
                raise ValidationError(
                    "source acquisition proof prerequisites unavailable"
                )
            validate_drive_access_proof(
                bundle.pre_access_proof,
                authority=oauth_authority,
                storage_attestation=storage_attestation,
                evaluated_at=receipt["started_at"],
            )
            validate_drive_access_proof(
                bundle.post_access_proof,
                authority=oauth_authority,
                storage_attestation=storage_attestation,
                evaluated_at=receipt["completed_at"],
            )
            if bundle.pre_access_proof["observed_at"] != receipt["started_at"]:
                raise ValidationError("pre-acquisition proof timestamp mismatch")
            if bundle.post_access_proof["observed_at"] != receipt["completed_at"]:
                raise ValidationError("post-acquisition proof timestamp mismatch")
            for field in (
                "principal_permission_id_sha256",
                "mount_identity_sha256",
                "provider_resource_id",
                "root_resource_id",
                "marker_file_id",
                "marker_sha256",
            ):
                if bundle.pre_access_proof[field] != bundle.post_access_proof[field]:
                    raise IntegrityError(
                        f"Drive acquisition identity changed between proofs: {field}"
                    )
            if source_audit is None:
                raise ValidationError("source acquisition lacks a source audit")
            rows = [
                row
                for row in source_audit["artifacts"]
                if row["artifact_id"] == artifact_id
            ]
            if len(rows) != 1:
                raise ValidationError("source audit acquisition row mismatch")
            row = rows[0]
            if (
                row["status"] != "verified"
                or row["measured"] is None
                or row["measured"]["bytes"] != receipt["bytes"]
                or row["measured"]["sha256"] != receipt["checksums"]["sha256"]
            ):
                raise IntegrityError("source audit does not corroborate acquisition")
            for algorithm, measured in receipt["checksums"].items():
                if row["measured"].get(algorithm) != measured:
                    raise IntegrityError(
                        f"source audit does not corroborate {algorithm} acquisition digest"
                    )
            started = _parse_time(receipt["started_at"], "acquisition started_at")
            completed = _parse_time(receipt["completed_at"], "acquisition completed_at")
            auth_started = _parse_time(
                authorization.receipt["authorized_at"], "authorization authorized_at"
            )
            auth_expires = _parse_time(
                authorization.receipt["valid_until"], "authorization valid_until"
            )
            if not (auth_started <= started <= completed <= auth_expires):
                raise ValidationError("source acquisition fell outside authorization")
            expected_authorization_gate = evaluate_gate_v4_2(
                evaluated_at=receipt["started_at"],
                source_registries=source_registries,
                evaluation_registries=evaluation_registries,
                drive_observation=drive_observation,
                storage_attestation=storage_attestation,
                publisher_receipts=publisher_receipts,
                source_audit=bundle.pre_source_audit,
                licence_assessments=licence_assessments,
                verified_bundles=verified_bundles,
                materializations=materializations,
                quarantine_contributions=quarantine_contributions,
                quarantine_index=quarantine_index,
                verified_seals=verified_seals,
                evaluation_access_events=evaluation_access_events,
                verified_access_anchors=verified_access_anchors,
                structural_inventories=(),
                admission_receipts=(),
                authority_policy=authority_policy,
                approved_policy_sha256=approved_policy_sha256,
                oauth_authority=oauth_authority,
                drive_access_proof=bundle.pre_access_proof,
                acquisition_authorizations=authorizations,
                acquisition_evidence=(),
            )
            if bundle.authorization_gate != expected_authorization_gate:
                raise IntegrityError("source acquisition gate is not reproducible")
            evidence_by_artifact[artifact_id] = bundle
            _evidence(
                evidence,
                "source_acquisition_receipt",
                artifact_id,
                canonical_sha256(receipt),
            )
        if set(evidence_by_artifact) != set(targets):
            raise ValidationError("source acquisition evidence set mismatch")
        acquisition_evidence_ready = bool(targets)
    except Exception:
        if evidence_bundles:
            _block(
                blockers,
                "acquisition_evidence_invalid",
                "acquisition",
                "foundation",
            )
    if not acquisition_evidence_ready:
        _block(
            blockers,
            "acquisition_evidence_missing",
            "acquisition",
            "foundation",
        )

    foundation_transform_ready = all(
        (
            base["foundation_transform_ready"],
            contracts_frozen,
            oauth_authority_ready,
            same_resource_ready,
            acquisition_evidence_ready,
        )
    )

    report = {
        **{
            key: base[key]
            for key in (
                "evaluated_at",
                "registry_lineage_ready",
                "source_registry_ready",
                "evaluation_registry_ready",
                "evaluation_roles_ready",
                "evaluation_materialization_ready",
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
            )
        },
        "schema_version": SCHEMA_VERSION_V4_2,
        "gate_id": "phase0-external-evidence-firewall-v4.2",
        "contracts_frozen": contracts_frozen,
        "oauth_authority_ready": oauth_authority_ready,
        "same_resource_ready": same_resource_ready,
        "foundation_acquisition_ready": foundation_acquisition_ready,
        "acquisition_authorization_ready": acquisition_authorization_ready,
        "acquisition_evidence_ready": acquisition_evidence_ready,
        "foundation_acquisition_authorized": foundation_acquisition_authorized,
        "foundation_transform_ready": foundation_transform_ready,
        "training_authorized": False,
        "blockers": _render_blockers(blockers),
        "evidence_bindings": _render_evidence(evidence),
    }
    validate_v4_2(report, "gate.schema.json")
    return report


def require_phase0_transform_gate_v4_2(gate: dict[str, Any]) -> str:
    validate_v4_2(gate, "gate.schema.json")
    required = (
        "contracts_frozen",
        "registry_lineage_ready",
        "source_registry_ready",
        "evaluation_registry_ready",
        "evaluation_roles_ready",
        "evaluation_materialization_ready",
        "storage_identity_ready",
        "oauth_authority_ready",
        "same_resource_ready",
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
        "acquisition_evidence_ready",
        "foundation_transform_ready",
    )
    if not all(gate[field] is True for field in required) or gate["blockers"]:
        raise GateBlocked("Phase 0 v4.2 has not authorized foundation transformation")
    if gate["training_authorized"] is not False:
        raise GateBlocked("Phase 0 v4.2 training invariant is violated")
    return canonical_sha256(gate)
