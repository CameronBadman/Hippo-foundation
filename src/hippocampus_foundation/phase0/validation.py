"""Schema and registry validation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json
from .errors import ValidationError


def schema_root() -> Path:
    package_candidate = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = Path(__file__).resolve().parents[3] / "schemas" / "v1"
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate packaged or repository schema directory")


def load_schema(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(f"invalid JSON Schema {path}: {exc.message}") from exc
    return value


def validate_instance(
    instance: Any, schema_name: str, root: Path | None = None
) -> None:
    schema = load_schema(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    rendered: list[str] = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        rendered.append(f"{location}: {error.message}")
    raise ValidationError("; ".join(rendered))


def validate_json_file(path: Path, schema_name: str, root: Path | None = None) -> Any:
    instance = load_json(path)
    validate_instance(instance, schema_name, root)
    return instance


def validate_schema_set(root: Path | None = None) -> list[str]:
    target = root or schema_root()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no schemas found under {target}")
    for name in names:
        load_schema(name, target)
    return names


def schema_digests(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root()
    names = validate_schema_set(target)
    return {name: canonical_sha256(load_schema(name, target)) for name in names}


def reject_duplicate_ids(records: Iterable[dict[str, Any]], field: str = "id") -> None:
    seen: set[str] = set()
    for record in records:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise ValidationError(f"record has no non-empty {field!r}")
        if value in seen:
            raise ValidationError(f"duplicate {field}: {value}")
        seen.add(value)


def validate_source_registry(registry: Any) -> None:
    """Validate schema plus cross-record invariants JSON Schema cannot express."""

    validate_instance(registry, "source-manifest.schema.json")
    reject_duplicate_ids(registry["sources"], "source_id")
    storage_requirements = registry["storage_requirements"]
    reject_duplicate_ids(storage_requirements, "locator_id")
    declared_locators = {item["locator_id"] for item in storage_requirements}
    artifact_ids: set[str] = set()
    checksum_lengths = {"md5": 32, "sha1": 40, "sha256": 64}
    for source in registry["sources"]:
        licence = source["licence"]
        if licence["review_status"] == "approved":
            if licence["reviewer"] is None or licence["reviewed_at"] is None:
                raise ValidationError(
                    f"approved licence has no reviewer evidence: {source['source_id']}"
                )
        for artifact in source["artifacts"]:
            artifact_id = artifact["artifact_id"]
            if artifact_id in artifact_ids:
                raise ValidationError(f"duplicate artifact_id: {artifact_id}")
            artifact_ids.add(artifact_id)
            if artifact["locator_id"] not in declared_locators:
                raise ValidationError(
                    f"artifact uses undeclared locator_id: {artifact_id}"
                )
            algorithms: set[str] = set()
            for checksum in artifact["checksums"]:
                algorithm = checksum["algorithm"]
                if algorithm in algorithms:
                    raise ValidationError(
                        f"duplicate {algorithm} checksum for {artifact_id}"
                    )
                algorithms.add(algorithm)
                if len(checksum["value"]) != checksum_lengths[algorithm]:
                    raise ValidationError(
                        f"invalid {algorithm} checksum length for {artifact_id}"
                    )
            if artifact["integrity_status"] == "verified":
                if artifact["expected_bytes"] is None:
                    raise ValidationError(
                        f"verified artifact has no byte count: {artifact_id}"
                    )
                if not any(item["verified"] for item in artifact["checksums"]):
                    raise ValidationError(
                        f"verified artifact has no verified checksum: {artifact_id}"
                    )


def validate_source_audit(audit: Any) -> None:
    validate_instance(audit, "source-audit.schema.json")
    try:
        started_at = datetime.fromisoformat(audit["started_at"].replace("Z", "+00:00"))
        completed_at = datetime.fromisoformat(
            audit["completed_at"].replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid source audit timestamp: {exc}") from exc
    if started_at.tzinfo is None or completed_at.tzinfo is None:
        raise ValidationError("source audit timestamps must include a timezone")
    if completed_at < started_at:
        raise ValidationError("source audit completed before it started")
    artifacts = audit["artifacts"]
    if audit["artifact_count"] != len(artifacts):
        raise ValidationError("source audit artifact_count does not match its records")
    measured_total = sum(
        item["measured"]["bytes"] for item in artifacts if item["measured"] is not None
    )
    if audit["total_bytes"] != measured_total:
        raise ValidationError("source audit total_bytes does not match its records")
    all_verified = all(item["status"] == "verified" for item in artifacts)
    if audit["all_verified"] != all_verified:
        raise ValidationError("source audit all_verified is inconsistent")
    pairs: set[tuple[str, str]] = set()
    for item in artifacts:
        pair = (item["source_id"], item["artifact_id"])
        if pair in pairs:
            raise ValidationError(f"duplicate audited artifact: {pair[0]}:{pair[1]}")
        pairs.add(pair)
        if item["status"] == "verified" and (
            item["measured"] is None or item["mismatches"]
        ):
            raise ValidationError(
                f"verified audited artifact has inconsistent evidence: {pair[0]}:{pair[1]}"
            )
        if item["status"] == "error" and item["measured"] is not None:
            raise ValidationError(
                f"errored audited artifact unexpectedly has measurements: {pair[0]}:{pair[1]}"
            )


def validate_evaluation_registry(registry: Any) -> None:
    """Validate evaluation declarations and fail closed on ambiguous state."""

    validate_instance(registry, "evaluation.schema.json")
    reject_duplicate_ids(registry["datasets"], "dataset_id")
    from .quarantine import ALLOWED_RELATIONSHIPS  # avoid a module cycle at import

    declared_relationships = set(registry["closure_policy"]["relationship_types"])
    if declared_relationships != ALLOWED_RELATIONSHIPS:
        missing = sorted(ALLOWED_RELATIONSHIPS - declared_relationships)
        extra = sorted(declared_relationships - ALLOWED_RELATIONSHIPS)
        raise ValidationError(
            f"closure policy differs from implementation; missing={missing}, extra={extra}"
        )
    seal_ids: set[str] = set()
    for dataset in registry["datasets"]:
        dataset_id = dataset["dataset_id"]
        seal_id = dataset["seal_id"]
        if seal_id is not None:
            if seal_id in seal_ids:
                raise ValidationError(f"duplicate evaluation seal_id: {seal_id}")
            seal_ids.add(seal_id)
        if dataset["status"] in {"pinned", "sealed", "consumed"}:
            if dataset["resolved_version"] is None or dataset["archive_sha256"] is None:
                raise ValidationError(
                    f"{dataset_id} is {dataset['status']} without a version and archive hash"
                )
        if dataset["status"] in {"sealed", "consumed"}:
            if not dataset["seal_id"]:
                raise ValidationError(f"{dataset_id} is sealed without a seal_id")
            if dataset["licence_status"] != "approved":
                raise ValidationError(
                    f"{dataset_id} is sealed without licence approval"
                )
            if dataset["blockers"]:
                raise ValidationError(
                    f"{dataset_id} is sealed with unresolved blockers"
                )
