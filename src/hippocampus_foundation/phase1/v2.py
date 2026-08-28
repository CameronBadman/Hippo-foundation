"""Phase 1 v2 readiness gate with explicit encoder licensing."""

from __future__ import annotations

from datetime import datetime, timedelta
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
from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.v3 import (
    require_phase0_transform_gate_v3,
)
from hippocampus_foundation.phase0.v3 import (
    validate_schema_lock_v3 as validate_phase0_schema_lock_v3,
)

from .contracts import (
    ENCODER_ASSET_PATHS,
    FROZEN_ENCODER_SPEC_SHA256,
    OBJECTIVE_FAMILIES,
    validate_artifact_manifest,
    validate_encoder_spec,
    validate_schema_lock_v1,
)
from .errors import Phase1ValidationError

SCHEMA_VERSION = "2.0.0"
EVIDENCE_MAX_AGE = timedelta(hours=72)
ENCODER_REQUIRED_USES = frozenset({"acquire", "embed", "commercial_service"})
FROZEN_SCHEMA_DIGESTS_V2: dict[str, str] = {
    "encoder-verification.schema.json": "sha256:e7fbdb108a9cd2750422668c4f35a0fee4a310afaf9d289065028ee3fd3e402d",
    "gate.schema.json": "sha256:e553be848e30d15474e752cf3572500b17d5be56930d3df89afcde9aeb256aea",
}


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Phase1ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise Phase1ValidationError(f"{field} must include a timezone")
    return parsed


def schema_root_v2() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase1" / "v2"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase1" / "v2"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise Phase1ValidationError("cannot locate Phase 1 v2 schema directory")


def load_schema_v2(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v2()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise Phase1ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise Phase1ValidationError(
            f"invalid Phase 1 v2 schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v2(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v2(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    rendered = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        rendered.append(f"{location}: {error.message}")
    raise Phase1ValidationError("; ".join(rendered))


def schema_digests_v2(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v2()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise Phase1ValidationError(f"no Phase 1 v2 schemas under {target}")
    return {name: canonical_sha256(load_schema_v2(name, target)) for name in names}


def validate_schema_lock_v2(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v2(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V2:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V2.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V2.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V2.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V2[name] != observed[name]
        )
        raise Phase1ValidationError(
            f"Phase 1 v2 schema lock mismatch: missing={missing}, extra={extra}, changed={changed}"
        )
    return observed


def validate_encoder_verification_v2(value: dict[str, Any]) -> None:
    """Validate evidence emitted by the exact snapshot-layout verifier."""

    validate_v2(value, "encoder-verification.schema.json")
    paths = [item["path"] for item in value["assets"]]
    if len(paths) != len(set(paths)):
        raise Phase1ValidationError("encoder verification repeats an asset")
    if set(paths) != ENCODER_ASSET_PATHS:
        raise Phase1ValidationError(
            "encoder verification asset set mismatch; "
            f"missing={sorted(ENCODER_ASSET_PATHS - set(paths))}, "
            f"extra={sorted(set(paths) - ENCODER_ASSET_PATHS)}"
        )


def evaluate_phase1_gate_v2(
    *,
    evaluated_at: str,
    phase0_gate: dict[str, Any] | None,
    encoder_spec: dict[str, Any],
    encoder_verification: dict[str, Any] | None,
    encoder_licence_assessment: dict[str, Any] | None,
    encoder_verified_bundle: VerifiedBundle | None,
    sample_manifest: dict[str, Any] | None,
    graph_manifest: dict[str, Any] | None,
    objective_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers: set[str] = set()
    evidence: set[str] = set()
    now = _parse_time(evaluated_at, "evaluated_at")

    try:
        v1_schemas = validate_schema_lock_v1()
        v2_schemas = validate_schema_lock_v2()
        licensing_schemas = validate_licensing_schema_lock_v1()
        phase0_schemas = validate_phase0_schema_lock_v3()
        contracts_frozen = True
        evidence.add(f"phase1_v1_dependency_schemas:{canonical_sha256(v1_schemas)}")
        evidence.add(f"phase1_v2_schemas:{canonical_sha256(v2_schemas)}")
        evidence.add(f"licensing_v1_schemas:{canonical_sha256(licensing_schemas)}")
        evidence.add(f"phase0_v3_dependency_schemas:{canonical_sha256(phase0_schemas)}")
    except Exception as exc:
        contracts_frozen = False
        blockers.add(f"contracts_invalid:{type(exc).__name__}:{exc}")

    phase0_transform_ready = False
    phase0_sha256: str | None = None
    if phase0_gate is None:
        blockers.add("phase0_gate_missing")
    else:
        try:
            phase0_sha256 = require_phase0_transform_gate_v3(phase0_gate)
            phase0_time = _parse_time(
                phase0_gate["evaluated_at"], "phase0 evaluated_at"
            )
            if phase0_time > now:
                raise Phase1ValidationError("Phase 0 gate is from the future")
            if now - phase0_time > EVIDENCE_MAX_AGE:
                raise Phase1ValidationError("Phase 0 gate is stale")
            phase0_transform_ready = True
            evidence.add(f"phase0_gate_v3:{phase0_sha256}")
        except Exception as exc:
            blockers.add(f"phase0_gate_invalid:{type(exc).__name__}:{exc}")

    try:
        validate_encoder_spec(encoder_spec)
        encoder_spec_valid = True
        evidence.add(f"encoder_spec:{canonical_sha256(encoder_spec)}")
    except Exception as exc:
        encoder_spec_valid = False
        blockers.add(f"encoder_spec_invalid:{type(exc).__name__}:{exc}")

    encoder_identity_ready = False
    if encoder_verification is None:
        blockers.add("encoder_verification_missing")
    elif encoder_spec_valid:
        try:
            validate_encoder_verification_v2(encoder_verification)
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
            encoder_identity_ready = True
            evidence.add(
                f"encoder_verification_v2:{canonical_sha256(encoder_verification)}"
            )
        except Exception as exc:
            blockers.add(f"encoder_verification_invalid:{type(exc).__name__}:{exc}")

    encoder_licensing_ready = False
    if encoder_licence_assessment is None or encoder_verified_bundle is None:
        blockers.add("encoder_licence_evidence_missing")
    elif encoder_spec_valid:
        try:
            if (
                encoder_licence_assessment["review_id"]
                != encoder_spec["licence_review_id"]
            ):
                raise Phase1ValidationError("encoder licence review ID mismatch")
            verify_assessment(
                encoder_licence_assessment,
                encoder_verified_bundle,
                subject_kind="encoder",
                subject_id=encoder_spec["encoder_id"],
                subject_binding_sha256=FROZEN_ENCODER_SPEC_SHA256,
                required_uses=ENCODER_REQUIRED_USES,
                evaluated_at=evaluated_at,
            )
            encoder_licensing_ready = True
            evidence.add(f"encoder_licence_bundle:{encoder_verified_bundle.sha256}")
            evidence.add(
                f"encoder_licence_assessment:{canonical_sha256(encoder_licence_assessment)}"
            )
        except Exception as exc:
            blockers.add(f"encoder_licence_not_ready:{type(exc).__name__}:{exc}")

    encoder_ready = encoder_identity_ready and encoder_licensing_ready
    if not encoder_ready:
        blockers.add("encoder_not_ready")

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
            readiness = {name: False for name in readiness}
            blockers.add("quarantine_binding_mismatch")
        elif phase0_gate is None or (
            f"quarantine_index:{next(iter(quarantine_hashes))}"
            not in phase0_gate["evidence"]
        ):
            readiness = {name: False for name in readiness}
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
        "schema_version": SCHEMA_VERSION,
        "gate_id": "phase1-data-preparation-v2",
        "evaluated_at": evaluated_at,
        "contracts_frozen": contracts_frozen,
        "phase0_transform_ready": phase0_transform_ready,
        "encoder_identity_ready": encoder_identity_ready,
        "encoder_licensing_ready": encoder_licensing_ready,
        "encoder_ready": encoder_ready,
        "sample_ready": sample_ready,
        "graph_ready": graph_ready,
        "objectives_ready": objectives_ready,
        "phase1_data_ready": phase1_data_ready,
        "training_authorized": False,
        "blockers": sorted(blockers),
        "evidence": sorted(evidence),
    }
    validate_v2(report, "gate.schema.json")
    return report
