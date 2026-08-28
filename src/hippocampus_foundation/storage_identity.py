"""Bind a fresh, read-only Drive observation to Phase 0 storage contracts."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.errors import ValidationError
from hippocampus_foundation.phase0.v2 import (
    validate_source_registry_v2,
    validate_storage_attestation_v2,
)

SCHEMA_VERSION = "1.0.0"
DRIVE_OBSERVATION_MAX_AGE = timedelta(minutes=15)
DRIVE_LOCATOR_ID = "drive_lake"
FROZEN_SCHEMA_DIGESTS_V1: dict[str, str] = {
    "drive-observation.schema.json": "sha256:79215c85b26df37c9124760dcb4368137101c1f33ef40813ac8bb1a04cde030c",
}


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def schema_root_v1() -> Path:
    package_candidate = Path(__file__).resolve().parent / "schemas" / "storage" / "v1"
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[2] / "schemas" / "storage" / "v1"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate storage identity v1 schema directory")


def load_schema_v1(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v1()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(
            f"invalid storage identity schema {path}: {exc.message}"
        ) from exc
    return value


def validate_observation_v1(
    observation: dict[str, Any],
    *,
    evaluated_at: str | None = None,
    root: Path | None = None,
) -> None:
    schema = load_schema_v1("drive-observation.schema.json", root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(observation), key=lambda item: list(item.path)
    )
    if errors:
        rendered = []
        for error in errors:
            location = "/".join(str(part) for part in error.absolute_path) or "$"
            rendered.append(f"{location}: {error.message}")
        raise ValidationError("; ".join(rendered))
    if evaluated_at is not None:
        evaluated = _parse_time(evaluated_at, "evaluated_at")
        observed = _parse_time(observation["observed_at"], "observed_at")
        if observed > evaluated:
            raise ValidationError("Drive observation is from the future")
        if evaluated - observed > DRIVE_OBSERVATION_MAX_AGE:
            raise ValidationError("Drive observation is stale")


def validate_schema_lock_v1(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v1()
    observed = {
        path.name: canonical_sha256(load_schema_v1(path.name, target))
        for path in sorted(target.glob("*.schema.json"))
    }
    if observed != FROZEN_SCHEMA_DIGESTS_V1:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V1.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V1.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V1.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V1[name] != observed[name]
        )
        raise ValidationError(
            "storage identity schema lock mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return observed


def bind_drive_observation(
    source_registry: dict[str, Any],
    observation: dict[str, Any],
    *,
    verifier: str,
    bound_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a new registry and v2 attestation bound to one fresh observation."""

    if not verifier.strip():
        raise ValidationError("storage verifier must not be empty")
    validate_schema_lock_v1()
    validate_source_registry_v2(source_registry)
    validate_observation_v1(observation, evaluated_at=bound_at)

    matches = [
        item
        for item in source_registry["storage_requirements"]
        if item["locator_id"] == DRIVE_LOCATOR_ID
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"expected exactly one {DRIVE_LOCATOR_ID} requirement; observed {len(matches)}"
        )
    requirement = matches[0]
    comparisons = {
        "provider": observation["provider"],
        "required_root": observation["observed_root"],
    }
    for field, observed_value in comparisons.items():
        if requirement[field] != observed_value:
            raise ValidationError(f"Drive observation/registry mismatch: {field}")
    for field in ("provider_resource_id", "root_resource_id"):
        registered = requirement[field]
        observed_value = observation[field]
        if registered is not None and registered != observed_value:
            raise ValidationError(
                f"Drive observation conflicts with registered {field}"
            )

    bound_registry = copy.deepcopy(source_registry)
    bound_requirement = next(
        item
        for item in bound_registry["storage_requirements"]
        if item["locator_id"] == DRIVE_LOCATOR_ID
    )
    bound_requirement["provider_resource_id"] = observation["provider_resource_id"]
    bound_requirement["root_resource_id"] = observation["root_resource_id"]
    validate_source_registry_v2(bound_registry)

    attestation = {
        "schema_version": "2.0.0",
        "record_kind": "storage_attestation",
        "locator_id": DRIVE_LOCATOR_ID,
        "provider": observation["provider"],
        "provider_resource_id": observation["provider_resource_id"],
        "root_resource_id": observation["root_resource_id"],
        "observed_root": observation["observed_root"],
        "observed_at": observation["observed_at"],
        "method": observation["method"],
        "verifier": verifier,
    }
    validate_storage_attestation_v2(attestation, bound_registry, evaluated_at=bound_at)
    return bound_registry, attestation
