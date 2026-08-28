"""Mechanical Phase 1 preparation gate. It never authorizes training."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256
from hippocampus_foundation.phase0.v2 import validate_v2 as validate_phase0_v2

from .contracts import (
    FROZEN_ENCODER_SPEC_SHA256,
    OBJECTIVE_FAMILIES,
    validate_artifact_manifest,
    validate_encoder_spec,
    validate_encoder_verification,
    validate_gate_report,
    validate_schema_lock_v1,
)
from .errors import Phase1GateBlocked, Phase1ValidationError

EVIDENCE_MAX_AGE = timedelta(hours=72)


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Phase1ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise Phase1ValidationError(f"{field} must include a timezone")
    return parsed


def require_phase0_transform_gate(gate: dict[str, Any]) -> str:
    validate_phase0_v2(gate, "gate.schema.json")
    if gate.get("gate_id") != "phase0-public-foundation-v2":
        raise Phase1GateBlocked("Phase 1 requires the Phase 0 v2 gate")
    required_controls = (
        "schemas_frozen",
        "storage_identity_ready",
        "source_audit_ready",
        "licensing_ready",
        "public_confirmatory_ready",
        "quarantine_ready",
        "structural_inventory_ready",
        "admission_ready",
        "foundation_acquisition_authorized",
        "foundation_transform_ready",
    )
    if not all(gate[field] is True for field in required_controls) or gate["blockers"]:
        raise Phase1GateBlocked("Phase 0 has not authorized foundation transformation")
    if gate["training_authorized"] is not False:
        raise Phase1GateBlocked("Phase 0 training invariant is violated")
    return canonical_sha256(gate)


def evaluate_phase1_gate(
    *,
    evaluated_at: str,
    phase0_gate: dict[str, Any] | None,
    encoder_spec: dict[str, Any],
    encoder_verification: dict[str, Any] | None,
    sample_manifest: dict[str, Any] | None,
    graph_manifest: dict[str, Any] | None,
    objective_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers: set[str] = set()
    evidence: set[str] = set()
    now = _parse_time(evaluated_at, "evaluated_at")

    try:
        schema_digests = validate_schema_lock_v1()
        contracts_frozen = True
        evidence.add(f"phase1_schemas:{canonical_sha256(schema_digests)}")
    except Exception as exc:
        contracts_frozen = False
        blockers.add(f"contracts_invalid:{type(exc).__name__}:{exc}")

    phase0_transform_ready = False
    phase0_sha256: str | None = None
    if phase0_gate is None:
        blockers.add("phase0_gate_missing")
    else:
        try:
            phase0_sha256 = require_phase0_transform_gate(phase0_gate)
            phase0_time = _parse_time(
                phase0_gate["evaluated_at"], "phase0 evaluated_at"
            )
            if phase0_time > now:
                raise Phase1ValidationError("Phase 0 gate is from the future")
            if now - phase0_time > EVIDENCE_MAX_AGE:
                raise Phase1ValidationError("Phase 0 gate is stale")
            phase0_transform_ready = True
            evidence.add(f"phase0_gate:{phase0_sha256}")
        except Exception as exc:
            blockers.add(f"phase0_gate_invalid:{type(exc).__name__}:{exc}")

    try:
        validate_encoder_spec(encoder_spec)
        encoder_spec_valid = True
        evidence.add(f"encoder_spec:{canonical_sha256(encoder_spec)}")
    except Exception as exc:
        encoder_spec_valid = False
        blockers.add(f"encoder_spec_invalid:{type(exc).__name__}:{exc}")

    encoder_ready = False
    if encoder_verification is None:
        blockers.add("encoder_verification_missing")
    elif encoder_spec_valid:
        try:
            validate_encoder_verification(encoder_verification)
            if encoder_verification["spec_sha256"] != FROZEN_ENCODER_SPEC_SHA256:
                raise Phase1ValidationError(
                    "encoder verification spec binding mismatch"
                )
            if (
                encoder_verification["bakeoff_report_sha256"]
                != encoder_spec["bakeoff_report_sha256"]
            ):
                raise Phase1ValidationError("encoder bake-off binding mismatch")
            if encoder_verification["assets"] != sorted(
                encoder_spec["assets"], key=lambda item: item["path"]
            ):
                raise Phase1ValidationError("encoder asset evidence mismatch")
            verified_at = _parse_time(
                encoder_verification["verified_at"], "encoder verified_at"
            )
            if verified_at > now:
                raise Phase1ValidationError("encoder verification is from the future")
            if now - verified_at > EVIDENCE_MAX_AGE:
                raise Phase1ValidationError("encoder verification is stale")
            if (
                not encoder_verification["verified"]
                or not encoder_verification["asset_set_exact"]
                or encoder_verification["executable_model_code_files"]
            ):
                raise Phase1ValidationError("encoder verification is not clean")
            encoder_ready = True
            evidence.add(
                f"encoder_verification:{canonical_sha256(encoder_verification)}"
            )
        except Exception as exc:
            blockers.add(f"encoder_verification_invalid:{type(exc).__name__}:{exc}")

    manifests = {
        "sample": sample_manifest,
        "graph": graph_manifest,
        "objectives": objective_manifest,
    }
    readiness = {name: False for name in manifests}
    for name, manifest in manifests.items():
        if manifest is None:
            blockers.add(f"{name}_manifest_missing")
            continue
        try:
            validate_artifact_manifest(manifest)
            if phase0_sha256 is None or manifest["phase0_gate_sha256"] != phase0_sha256:
                raise Phase1ValidationError("manifest Phase 0 binding mismatch")
            created_at = _parse_time(manifest["created_at"], f"{name} created_at")
            if created_at > now:
                raise Phase1ValidationError("manifest is from the future")
            if not manifest["complete"] or manifest["errors"]:
                raise Phase1ValidationError("manifest is incomplete")
            readiness[name] = True
            evidence.add(f"{name}_manifest:{canonical_sha256(manifest)}")
        except Exception as exc:
            blockers.add(f"{name}_manifest_invalid:{type(exc).__name__}:{exc}")

    if readiness["sample"] and sample_manifest is not None:
        if (
            sample_manifest["requested_size"] != 40_000
            or sample_manifest["selected_size"] != 40_000
            or sample_manifest["covered_communities"]
            != sample_manifest["community_count"]
            or sample_manifest["covered_strata"] != sample_manifest["stratum_count"]
        ):
            readiness["sample"] = False
            blockers.add("sample_contract_not_satisfied")
    if readiness["objectives"] and objective_manifest is not None:
        if set(objective_manifest["family_counts"]) != OBJECTIVE_FAMILIES or any(
            value < 1 for value in objective_manifest["family_counts"].values()
        ):
            readiness["objectives"] = False
            blockers.add("objective_family_coverage_incomplete")

    if all(readiness.values()):
        assert sample_manifest is not None
        assert graph_manifest is not None
        assert objective_manifest is not None
        quarantine_hashes = {
            sample_manifest["quarantine_index_sha256"],
            graph_manifest["quarantine_index_sha256"],
            objective_manifest["quarantine_index_sha256"],
        }
        if len(quarantine_hashes) != 1:
            readiness["sample"] = False
            readiness["graph"] = False
            readiness["objectives"] = False
            blockers.add("quarantine_binding_mismatch")
        elif phase0_gate is None or (
            f"quarantine_index:{next(iter(quarantine_hashes))}"
            not in phase0_gate["evidence"]
        ):
            readiness["sample"] = False
            readiness["graph"] = False
            readiness["objectives"] = False
            blockers.add("quarantine_not_admitted_by_phase0")
        if (
            objective_manifest["graph_snapshot_sha256"]
            != graph_manifest["selected_sha256"]
        ):
            readiness["objectives"] = False
            blockers.add("objective_graph_binding_mismatch")

    sample_ready = readiness["sample"]
    graph_ready = readiness["graph"]
    objectives_ready = readiness["objectives"]
    phase1_data_ready = all(
        [
            contracts_frozen,
            phase0_transform_ready,
            encoder_ready,
            sample_ready,
            graph_ready,
            objectives_ready,
        ]
    )
    report = {
        "schema_version": "1.0.0",
        "gate_id": "phase1-data-preparation-v1",
        "evaluated_at": evaluated_at,
        "contracts_frozen": contracts_frozen,
        "phase0_transform_ready": phase0_transform_ready,
        "encoder_ready": encoder_ready,
        "sample_ready": sample_ready,
        "graph_ready": graph_ready,
        "objectives_ready": objectives_ready,
        "phase1_data_ready": phase1_data_ready,
        "training_authorized": False,
        "blockers": sorted(blockers),
        "evidence": sorted(evidence),
    }
    validate_gate_report(report)
    return report
