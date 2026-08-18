"""Evidence-bound Phase 0 v2 controls.

The v1 modules remain available for historical reproducibility.  This module is
the authorization boundary for new acquisition and transformation work.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json, sha256_bytes
from .errors import GateBlocked, IntegrityError, QuarantineError, ValidationError
from .inventory import audit_source_registry, hash_file, resolve_artifact, stream_count
from .quarantine import normalize_identifier
from .seal import consumes_evaluation, verify_access_chain


SCHEMA_VERSION = "2.0.0"
SOURCE_AUDIT_MAX_AGE = timedelta(hours=72)
STORAGE_ATTESTATION_MAX_AGE = timedelta(hours=72)

PUBLIC_EVALUATION_DATASETS_V2 = frozenset(
    {
        "vitaminc",
        "contractnli",
        "eventstoryline-v1.5",
        "evidencebench-original-test",
        "hf-logic-owa-v1",
        "socialiqa-v1.4-validation",
        "hf-process-state-v1",
    }
)

# Filled with canonical JSON digests after the schema files are frozen.  The
# anchor deliberately lives outside the schemas so it cannot form a digest
# cycle.
FROZEN_SCHEMA_DIGESTS_V2: dict[str, str] = {
    "control-evidence.schema.json": "sha256:4d0f99a8e32499560faaad4166ec4591397408318902e1b0b66c4d1e83a87ad1",
    "evaluation-evidence.schema.json": "sha256:7bb23c98d4213fb24102c1bce5d02378c24e791d88b9d7d0c0216dd6906e7794",
    "gate.schema.json": "sha256:76a2d8c735c5ce79064650c2936135ff66dba4b04d14878371c1b57f49282c92",
    "registry.schema.json": "sha256:6852bbcf65cb5852cfd056319872931fe04a95d682783ed608831994ec0e1e7a",
}

_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {"label", "labels", "answer", "answers", "target", "targets", "split", "membership"}
)
_DEVELOPMENT_PARTITION = re.compile(
    r"(?:^|[^a-z0-9])(?:dev|development|validation)(?:$|[^a-z0-9])"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _digest_bytes(data: bytes) -> str:
    return sha256_bytes(data)


def schema_root_v2() -> Path:
    package_candidate = Path(__file__).resolve().parents[1] / "schemas" / "phase0" / "v2"
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = Path(__file__).resolve().parents[3] / "schemas" / "phase0" / "v2"
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate Phase 0 v2 schema directory")


def load_schema_v2(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v2()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(f"invalid JSON Schema {path}: {exc.message}") from exc
    return value


def validate_v2(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v2(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    rendered: list[str] = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        rendered.append(f"{location}: {error.message}")
    raise ValidationError("; ".join(rendered))


def schema_digests_v2(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v2()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no Phase 0 v2 schemas under {target}")
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
        raise ValidationError(
            f"Phase 0 v2 schema lock mismatch; missing={missing}, extra={extra}, changed={changed}"
        )
    return observed


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return duplicate


def validate_source_registry_v2(registry: dict[str, Any]) -> None:
    validate_v2(registry, "registry.schema.json")
    if registry.get("registry_kind") != "sources":
        raise ValidationError("expected a Phase 0 v2 source registry")
    source_ids = [source["source_id"] for source in registry["sources"]]
    if duplicate := _duplicates(source_ids):
        raise ValidationError(f"duplicate source_id: {sorted(duplicate)}")
    locator_ids = [item["locator_id"] for item in registry["storage_requirements"]]
    if duplicate := _duplicates(locator_ids):
        raise ValidationError(f"duplicate locator_id: {sorted(duplicate)}")
    locators = {item["locator_id"] for item in registry["storage_requirements"]}
    artifact_ids: list[str] = []
    lengths = {"md5": 32, "sha1": 40, "sha256": 64}
    for source in registry["sources"]:
        for artifact in source["artifacts"]:
            artifact_ids.append(artifact["artifact_id"])
            if artifact["locator_id"] not in locators:
                raise ValidationError(
                    f"artifact uses unknown locator: {artifact['artifact_id']}"
                )
            algorithms = [item["algorithm"] for item in artifact["checksums"]]
            if duplicate := _duplicates(algorithms):
                raise ValidationError(
                    f"duplicate checksum for {artifact['artifact_id']}: {sorted(duplicate)}"
                )
            for checksum in artifact["checksums"]:
                value = checksum["value"]
                if len(value) != lengths[checksum["algorithm"]] or any(
                    character not in "0123456789abcdef" for character in value
                ):
                    raise ValidationError(
                        f"invalid {checksum['algorithm']} checksum for {artifact['artifact_id']}"
                    )
            if not any(
                item["origin"] == "publisher"
                and item["algorithm"] in {"sha1", "sha256"}
                for item in artifact["checksums"]
            ):
                raise ValidationError(
                    f"artifact lacks a publisher SHA checksum: {artifact['artifact_id']}"
                )
            overlap = set(artifact["required_nonzero_counters"]) & set(
                artifact["required_zero_counters"]
            )
            if overlap:
                raise ValidationError(
                    f"inventory counters cannot be both zero and nonzero for {artifact['artifact_id']}: {sorted(overlap)}"
                )
    if duplicate := _duplicates(artifact_ids):
        raise ValidationError(f"duplicate artifact_id: {sorted(duplicate)}")


def validate_evaluation_registry_v2(registry: dict[str, Any]) -> None:
    validate_v2(registry, "registry.schema.json")
    if registry.get("registry_kind") != "evaluations":
        raise ValidationError("expected a Phase 0 v2 evaluation registry")
    dataset_ids = [item["dataset_id"] for item in registry["datasets"]]
    if duplicate := _duplicates(dataset_ids):
        raise ValidationError(f"duplicate dataset_id: {sorted(duplicate)}")
    observed = set(dataset_ids)
    if observed != PUBLIC_EVALUATION_DATASETS_V2:
        raise ValidationError(
            "evaluation suite mismatch; "
            f"missing={sorted(PUBLIC_EVALUATION_DATASETS_V2 - observed)}, "
            f"extra={sorted(observed - PUBLIC_EVALUATION_DATASETS_V2)}"
        )
    seal_ids = [item["seal_id"] for item in registry["datasets"]]
    if duplicate := _duplicates(seal_ids):
        raise ValidationError(f"duplicate seal_id: {sorted(duplicate)}")
    for dataset in registry["datasets"]:
        if dataset["status"] in {"pinned", "sealed", "consumed"} and not all(
            [
                dataset["resolved_version"],
                dataset["partition"],
                dataset["archive_sha256"],
                dataset["adapter_id"],
                dataset["adapter_sha256"],
            ]
        ):
            raise ValidationError(
                f"pinned evaluation lacks immutable bindings: {dataset['dataset_id']}"
            )
        if dataset["status"] in {"sealed", "consumed"} and dataset["blockers"]:
            raise ValidationError(
                f"sealed evaluation retains blockers: {dataset['dataset_id']}"
            )


def _storage_requirement(
    source_registry: dict[str, Any], locator_id: str
) -> dict[str, Any]:
    matches = [
        item
        for item in source_registry["storage_requirements"]
        if item["locator_id"] == locator_id
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"locator_id must resolve exactly once, observed {len(matches)}: {locator_id}"
        )
    return matches[0]


def validate_storage_attestation_v2(
    attestation: dict[str, Any],
    source_registry: dict[str, Any],
    *,
    evaluated_at: str | None = None,
) -> None:
    validate_v2(attestation, "control-evidence.schema.json")
    if attestation.get("record_kind") != "storage_attestation":
        raise ValidationError("expected storage_attestation evidence")
    requirement = _storage_requirement(source_registry, attestation["locator_id"])
    comparisons = {
        "provider": requirement["provider"],
        "provider_resource_id": requirement["provider_resource_id"],
        "root_resource_id": requirement["root_resource_id"],
        "observed_root": requirement["required_root"],
    }
    for field, expected in comparisons.items():
        if attestation[field] != expected:
            raise ValidationError(
                f"storage attestation {field} mismatch: expected {expected!r}, observed {attestation[field]!r}"
            )
    if evaluated_at is not None:
        now = _parse_time(evaluated_at, "evaluated_at")
        observed = _parse_time(attestation["observed_at"], "observed_at")
        if observed > now:
            raise ValidationError("storage attestation is from the future")
        if now - observed > STORAGE_ATTESTATION_MAX_AGE:
            raise ValidationError("storage attestation is stale")


def verify_licence_review_v2(
    review: dict[str, Any],
    terms_snapshot: bytes | str,
    *,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    required_uses: Iterable[str] = (),
) -> None:
    validate_v2(review, "control-evidence.schema.json")
    if review.get("record_kind") != "licence_review":
        raise ValidationError("expected licence_review evidence")
    observed_digest = (
        terms_snapshot
        if isinstance(terms_snapshot, str) and terms_snapshot.startswith("sha256:")
        else _digest_bytes(
            terms_snapshot.encode("utf-8")
            if isinstance(terms_snapshot, str)
            else terms_snapshot
        )
    )
    if review["terms_snapshot_sha256"] != observed_digest:
        raise ValidationError("licence terms snapshot digest mismatch")
    if subject_kind is not None and review["subject_kind"] != subject_kind:
        raise ValidationError("licence review subject kind mismatch")
    if subject_id is not None and review["subject_id"] != subject_id:
        raise ValidationError("licence review subject ID mismatch")
    if review["decision"] != "approved" or review["commercial_use"] != "allowed":
        raise ValidationError("licence review does not approve commercial use")
    if not review["reviewer"] or not review["reviewed_at"]:
        raise ValidationError("approved licence review lacks human reviewer evidence")
    missing_uses = set(required_uses) - set(review["intended_uses"])
    if missing_uses:
        raise ValidationError(f"licence review omits intended uses: {sorted(missing_uses)}")


def audit_source_registry_v2(
    registry: dict[str, Any], attestation: dict[str, Any]
) -> dict[str, Any]:
    validate_source_registry_v2(registry)
    validate_storage_attestation_v2(attestation, registry)
    storage_map = {attestation["locator_id"]: attestation["observed_root"]}
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
    result = audit_source_registry(historical_shape, storage_map)
    result["schema_version"] = SCHEMA_VERSION
    result["record_kind"] = "source_audit"
    result["registry_sha256"] = canonical_sha256(registry)
    result["storage_attestation_sha256"] = canonical_sha256(attestation)
    result.pop("storage_map_sha256", None)
    # Filesystem identity values routinely exceed the interoperable integer
    # domain required by RFC 8785.  Preserve them exactly as decimal strings so
    # the evidence record itself remains canonically hashable.
    for row in result["artifacts"]:
        measured = row["measured"]
        if measured is not None:
            for field in ("device", "inode", "mtime_ns"):
                measured[field] = str(measured[field])
    validate_source_audit_v2(result)
    return result


def validate_source_audit_v2(audit: dict[str, Any]) -> None:
    validate_v2(audit, "control-evidence.schema.json")
    if audit.get("record_kind") != "source_audit":
        raise ValidationError("expected source_audit evidence")
    started = _parse_time(audit["started_at"], "source audit started_at")
    completed = _parse_time(audit["completed_at"], "source audit completed_at")
    if completed < started:
        raise ValidationError("source audit completed before it started")
    if audit["artifact_count"] != len(audit["artifacts"]):
        raise ValidationError("source audit artifact_count mismatch")
    measured_total = sum(
        item["measured"]["bytes"]
        for item in audit["artifacts"]
        if item["measured"] is not None
    )
    if audit["total_bytes"] != measured_total:
        raise ValidationError("source audit total_bytes mismatch")
    if audit["all_verified"] != all(
        item["status"] == "verified" for item in audit["artifacts"]
    ):
        raise ValidationError("source audit all_verified is inconsistent")
    pairs = [(item["source_id"], item["artifact_id"]) for item in audit["artifacts"]]
    if duplicate := _duplicates(f"{left}\0{right}" for left, right in pairs):
        raise ValidationError(f"duplicate source audit artifact: {sorted(duplicate)}")
    for item in audit["artifacts"]:
        if item["status"] == "verified" and (
            item["measured"] is None or item["mismatches"]
        ):
            raise ValidationError("verified audit row has inconsistent evidence")


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
        raise ValidationError(
            f"artifact_id must resolve exactly once, observed {len(matches)}: {artifact_id}"
        )
    return matches[0]


def build_structural_inventory_v2(
    *,
    registry: dict[str, Any],
    attestation: dict[str, Any],
    source_audit: dict[str, Any],
    artifact_id: str,
) -> dict[str, Any]:
    validate_source_registry_v2(registry)
    validate_storage_attestation_v2(attestation, registry)
    validate_source_audit_v2(source_audit)
    if source_audit["registry_sha256"] != canonical_sha256(registry):
        raise IntegrityError("source audit is bound to another registry")
    if source_audit["storage_attestation_sha256"] != canonical_sha256(attestation):
        raise IntegrityError("source audit is bound to another storage attestation")
    source, artifact = _artifact_lookup(registry, artifact_id)
    audited = [
        item
        for item in source_audit["artifacts"]
        if item["source_id"] == source["source_id"] and item["artifact_id"] == artifact_id
    ]
    if len(audited) != 1 or audited[0]["status"] != "verified":
        raise GateBlocked(f"artifact is not verified by the bound audit: {artifact_id}")
    storage_map = {attestation["locator_id"]: attestation["observed_root"]}
    path = resolve_artifact(storage_map, artifact["locator_id"], artifact["filename"])
    started_at = _utc_now()
    before = hash_file(path)
    counters = stream_count(path, artifact["inventory_kind"])
    after = hash_file(path)
    identity_fields = ("bytes", "md5", "sha1", "sha256", "device", "inode", "mtime_ns")
    if any(before[field] != after[field] for field in identity_fields):
        raise IntegrityError("artifact changed during structural inventory")
    measured = audited[0]["measured"]
    if measured is None or any(
        (
            str(before[field])
            if field in {"device", "inode", "mtime_ns"}
            else before[field]
        )
        != measured[field]
        for field in identity_fields
    ):
        raise IntegrityError("structural inventory bytes differ from source audit")
    counter_values = {
        key: int(value)
        for key, value in counters.items()
        if key != "kind" and isinstance(value, int) and not isinstance(value, bool)
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "structural_inventory",
        "source_id": source["source_id"],
        "artifact_id": artifact_id,
        "registry_sha256": canonical_sha256(registry),
        "source_audit_sha256": canonical_sha256(source_audit),
        "artifact_sha256": f"sha256:{before['sha256']}",
        "artifact_bytes": before["bytes"],
        "counter_kind": artifact["inventory_kind"],
        "counter_version": "hf-stream-counter-v2",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "complete": True,
        "parse_errors": int(counter_values.pop("parse_errors", 0)),
        "rejected_records": int(counter_values.pop("rejected_records", 0)),
        "counters": dict(sorted(counter_values.items())),
    }
    validate_structural_inventory_v2(result, registry, source_audit)
    return result


def validate_structural_inventory_v2(
    inventory: dict[str, Any],
    registry: dict[str, Any],
    source_audit: dict[str, Any],
) -> None:
    validate_v2(inventory, "control-evidence.schema.json")
    if inventory.get("record_kind") != "structural_inventory":
        raise ValidationError("expected structural_inventory evidence")
    source, artifact = _artifact_lookup(registry, inventory["artifact_id"])
    if inventory["source_id"] != source["source_id"]:
        raise ValidationError("structural inventory source binding mismatch")
    if inventory["registry_sha256"] != canonical_sha256(registry):
        raise ValidationError("structural inventory registry binding mismatch")
    if inventory["source_audit_sha256"] != canonical_sha256(source_audit):
        raise ValidationError("structural inventory audit binding mismatch")
    if inventory["counter_kind"] != artifact["inventory_kind"]:
        raise ValidationError("structural inventory counter kind mismatch")
    audited = [
        item
        for item in source_audit["artifacts"]
        if item["source_id"] == source["source_id"]
        and item["artifact_id"] == artifact["artifact_id"]
    ]
    if len(audited) != 1 or audited[0]["status"] != "verified":
        raise ValidationError("structural inventory lacks a verified audit row")
    measured = audited[0]["measured"]
    if measured is None or inventory["artifact_sha256"] != f"sha256:{measured['sha256']}":
        raise ValidationError("structural inventory artifact digest mismatch")
    if inventory["artifact_bytes"] != measured["bytes"]:
        raise ValidationError("structural inventory byte count mismatch")
    if not inventory["complete"]:
        raise ValidationError("structural inventory is incomplete")
    if inventory["parse_errors"] or inventory["rejected_records"]:
        raise ValidationError("structural inventory reports rejected or invalid records")
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


def _identifier_tuple(value: Mapping[str, Any]) -> tuple[str, str, str | None]:
    identifier = normalize_identifier(
        str(value["namespace"]), str(value["value"]), value.get("source_version")
    )
    return identifier.namespace, identifier.value, identifier.source_version


def _normalized_identifier(value: Mapping[str, Any]) -> dict[str, Any]:
    namespace, identifier_value, version = _identifier_tuple(value)
    return {
        "namespace": namespace,
        "value": identifier_value,
        "source_version": version,
    }


def _reject_forbidden_public_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in _FORBIDDEN_PUBLIC_KEYS:
                raise QuarantineError(f"label-bearing public field forbidden: {path}/{key}")
            _reject_forbidden_public_fields(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_public_fields(child, f"{path}/{index}")


def _selector_count(selectors: Mapping[str, Sequence[Any]]) -> int:
    return sum(
        len(selectors[field])
        for field in ("identifiers", "raw_hashes", "normalized_hashes", "fingerprints")
    )


def build_quarantine_contribution_v2(envelope: dict[str, Any]) -> dict[str, Any]:
    validate_v2(envelope, "evaluation-evidence.schema.json")
    if envelope.get("record_kind") != "evaluation_envelope":
        raise ValidationError("expected evaluation_envelope")
    record_ids = [record["record_id"] for record in envelope["records"]]
    if duplicate := _duplicates(record_ids):
        raise QuarantineError(f"duplicate private record IDs: {sorted(duplicate)}")
    bundle_sha256 = canonical_sha256(envelope)
    public_records: list[dict[str, Any]] = []
    total_expected = 0
    total_resolved = 0
    selector_total = 0
    fingerprint_ids: list[str] = []
    for record in envelope["records"]:
        selectors = record["selectors"]
        if _selector_count(selectors) < 1:
            raise QuarantineError(
                f"sealed record has no quarantine selector: {record['record_id']}"
            )
        expected = {_identifier_tuple(item) for item in record["expected_dependency_units"]}
        resolved = {_identifier_tuple(item) for item in record["resolved_dependency_units"]}
        unresolved = record["unresolved_dependency_units"]
        if unresolved:
            raise QuarantineError(
                f"sealed record has unresolved dependencies: {record['record_id']}"
            )
        if expected != resolved:
            raise QuarantineError(
                f"dependency closure mismatch for sealed record: {record['record_id']}"
            )
        normalized_selectors = {
            "identifiers": sorted(
                (_normalized_identifier(item) for item in selectors["identifiers"]),
                key=lambda item: (
                    item["namespace"], item["value"], item["source_version"] or ""
                ),
            ),
            "raw_hashes": sorted(set(selectors["raw_hashes"])),
            "normalized_hashes": sorted(set(selectors["normalized_hashes"])),
            "fingerprints": sorted(
                selectors["fingerprints"], key=lambda item: item["fingerprint_id"]
            ),
        }
        fingerprint_ids.extend(
            item["fingerprint_id"] for item in normalized_selectors["fingerprints"]
        )
        public_records.append(
            {
                "record_commitment": canonical_sha256(
                    {"bundle_sha256": bundle_sha256, "record_id": record["record_id"]}
                ),
                "selectors": normalized_selectors,
                "expected_dependency_count": len(expected),
                "resolved_dependency_count": len(resolved),
            }
        )
        total_expected += len(expected)
        total_resolved += len(resolved)
        selector_total += _selector_count(normalized_selectors)
    if duplicate := _duplicates(fingerprint_ids):
        raise QuarantineError(f"duplicate fingerprint IDs in contribution: {sorted(duplicate)}")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "quarantine_contribution",
        "seal_id": envelope["seal_id"],
        "dataset_id": envelope["dataset_id"],
        "resolved_version": envelope["resolved_version"],
        "archive_sha256": envelope["archive_sha256"],
        "adapter_id": envelope["adapter_id"],
        "adapter_sha256": envelope["adapter_sha256"],
        "bundle_sha256": bundle_sha256,
        "records": sorted(
            public_records, key=lambda item: item["record_commitment"]
        ),
        "coverage": {
            "record_count": len(public_records),
            "covered_record_count": len(public_records),
            "uncovered_record_count": 0,
            "expected_dependency_count": total_expected,
            "resolved_dependency_count": total_resolved,
            "unresolved_dependency_count": 0,
            "selector_count": selector_total,
        },
    }
    _reject_forbidden_public_fields(result)
    validate_v2(result, "evaluation-evidence.schema.json")
    return result


def compile_quarantine_index_v2(
    contributions: Iterable[dict[str, Any]],
    *,
    index_id: str = "public-evaluation-union-v2",
) -> dict[str, Any]:
    values = list(contributions)
    if not values:
        raise QuarantineError("no quarantine contributions supplied")
    seal_ids: list[str] = []
    identifiers: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    raw_hashes: set[str] = set()
    normalized_hashes: set[str] = set()
    fingerprints: dict[str, dict[str, Any]] = {}
    contribution_hashes: list[str] = []
    for contribution in values:
        validate_v2(contribution, "evaluation-evidence.schema.json")
        if contribution.get("record_kind") != "quarantine_contribution":
            raise ValidationError("expected quarantine_contribution")
        coverage = contribution["coverage"]
        if (
            coverage["record_count"] != len(contribution["records"])
            or coverage["covered_record_count"] != coverage["record_count"]
            or coverage["uncovered_record_count"] != 0
            or coverage["unresolved_dependency_count"] != 0
            or coverage["expected_dependency_count"]
            != coverage["resolved_dependency_count"]
        ):
            raise QuarantineError(
                f"incomplete quarantine contribution: {contribution['seal_id']}"
            )
        seal_ids.append(contribution["seal_id"])
        contribution_hashes.append(canonical_sha256(contribution))
        for record in contribution["records"]:
            if _selector_count(record["selectors"]) < 1:
                raise QuarantineError("public contribution record has no selector")
            for item in record["selectors"]["identifiers"]:
                key = _identifier_tuple(item)
                identifiers[key] = _normalized_identifier(item)
            raw_hashes.update(record["selectors"]["raw_hashes"])
            normalized_hashes.update(record["selectors"]["normalized_hashes"])
            for fingerprint in record["selectors"]["fingerprints"]:
                fingerprint_id = fingerprint["fingerprint_id"]
                if fingerprint_id in fingerprints:
                    raise QuarantineError(
                        f"duplicate fingerprint ID across contributions: {fingerprint_id}"
                    )
                fingerprints[fingerprint_id] = fingerprint
    if duplicate := _duplicates(seal_ids):
        raise QuarantineError(f"duplicate contribution seal IDs: {sorted(duplicate)}")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "quarantine_index",
        "index_id": index_id,
        "closure_policy_id": "quarantine-closure-v2",
        "source_seal_ids": sorted(seal_ids),
        "contribution_sha256s": sorted(contribution_hashes),
        "identifiers": [identifiers[key] for key in sorted(identifiers)],
        "raw_hashes": sorted(raw_hashes),
        "normalized_hashes": sorted(normalized_hashes),
        "fingerprints": [fingerprints[key] for key in sorted(fingerprints)],
    }
    _reject_forbidden_public_fields(result)
    validate_v2(result, "evaluation-evidence.schema.json")
    return result


def make_seal_receipt_v2(
    *,
    envelope: dict[str, Any],
    contribution: dict[str, Any],
    ciphertext_sha256: str,
    public_key_fingerprint: str,
    custodian: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    expected = build_quarantine_contribution_v2(envelope)
    if expected != contribution:
        raise ValidationError("quarantine contribution does not derive from envelope")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "seal_receipt",
        "seal_id": envelope["seal_id"],
        "dataset_id": envelope["dataset_id"],
        "resolved_version": envelope["resolved_version"],
        "archive_sha256": envelope["archive_sha256"],
        "adapter_id": envelope["adapter_id"],
        "adapter_sha256": envelope["adapter_sha256"],
        "bundle_sha256": canonical_sha256(envelope),
        "contribution_sha256": canonical_sha256(contribution),
        "ciphertext_sha256": ciphertext_sha256,
        "public_key_fingerprint": public_key_fingerprint.upper(),
        "created_at": created_at or _utc_now(),
        "custodian": custodian,
        "record_count": len(envelope["records"]),
        "state": "sealed",
    }
    validate_v2(result, "evaluation-evidence.schema.json")
    return result


def verify_seal_receipt_v2(
    receipt: dict[str, Any],
    contribution: dict[str, Any],
    *,
    verified_ciphertext_sha256: str | None = None,
) -> None:
    validate_v2(receipt, "evaluation-evidence.schema.json")
    validate_v2(contribution, "evaluation-evidence.schema.json")
    if receipt.get("record_kind") != "seal_receipt":
        raise ValidationError("expected seal_receipt")
    fields = (
        "seal_id",
        "dataset_id",
        "resolved_version",
        "archive_sha256",
        "adapter_id",
        "adapter_sha256",
        "bundle_sha256",
    )
    for field in fields:
        if receipt[field] != contribution[field]:
            raise ValidationError(f"receipt/contribution binding mismatch: {field}")
    if receipt["contribution_sha256"] != canonical_sha256(contribution):
        raise ValidationError("receipt contribution digest mismatch")
    if receipt["record_count"] != contribution["coverage"]["record_count"]:
        raise ValidationError("receipt record count mismatch")
    if (
        verified_ciphertext_sha256 is not None
        and receipt["ciphertext_sha256"] != verified_ciphertext_sha256
    ):
        raise ValidationError("receipt ciphertext digest mismatch")


def _review_by_id(reviews: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for review in reviews:
        validate_v2(review, "control-evidence.schema.json")
        if review.get("record_kind") != "licence_review":
            raise ValidationError("non-licence record supplied as licence review")
        review_id = review["review_id"]
        if review_id in result:
            raise ValidationError(f"duplicate licence review: {review_id}")
        result[review_id] = review
    return result


def _audit_rows_for_source(
    audit: dict[str, Any], source_id: str
) -> list[dict[str, Any]]:
    return sorted(
        [item for item in audit["artifacts"] if item["source_id"] == source_id],
        key=lambda item: item["artifact_id"],
    )


def _publisher_pins_verified(source: Mapping[str, Any]) -> bool:
    return all(
        any(
            checksum["origin"] == "publisher"
            and checksum["verified"]
            and checksum["algorithm"] in {"sha1", "sha256"}
            for checksum in artifact["checksums"]
        )
        for artifact in source["artifacts"]
    )


def assess_admission_v2(
    *,
    source_id: str,
    registry: dict[str, Any],
    storage_attestation: dict[str, Any],
    source_audit: dict[str, Any],
    licence_review: dict[str, Any],
    verified_terms_sha256: str,
    inventories: Iterable[dict[str, Any]],
    quarantine_index: dict[str, Any],
    assessor: str,
    assessed_at: str | None = None,
) -> dict[str, Any]:
    validate_source_registry_v2(registry)
    validate_storage_attestation_v2(storage_attestation, registry)
    validate_source_audit_v2(source_audit)
    sources = [item for item in registry["sources"] if item["source_id"] == source_id]
    if len(sources) != 1:
        raise ValidationError(f"source_id must resolve exactly once: {source_id}")
    source = sources[0]
    if not _publisher_pins_verified(source):
        raise GateBlocked("source admission requires freshly verified publisher checksums")
    verify_licence_review_v2(
        licence_review,
        verified_terms_sha256,
        subject_kind="source",
        subject_id=source_id,
        required_uses={"acquire", "inventory", "quarantine", "transform", "embed"},
    )
    if licence_review["review_id"] != source["licence_review_id"]:
        raise ValidationError("source references a different licence review")
    if source_audit["registry_sha256"] != canonical_sha256(registry):
        raise ValidationError("source audit registry mismatch")
    if source_audit["storage_attestation_sha256"] != canonical_sha256(
        storage_attestation
    ):
        raise ValidationError("source audit storage attestation mismatch")
    expected_artifacts = {item["artifact_id"] for item in source["artifacts"]}
    rows = _audit_rows_for_source(source_audit, source_id)
    if {item["artifact_id"] for item in rows} != expected_artifacts or not all(
        item["status"] == "verified" for item in rows
    ):
        raise GateBlocked("source admission requires every artifact to be verified")
    inventory_values = list(inventories)
    by_artifact = {item.get("artifact_id"): item for item in inventory_values}
    if len(by_artifact) != len(inventory_values) or set(by_artifact) != expected_artifacts:
        raise GateBlocked("source admission requires one inventory per artifact")
    for inventory in inventory_values:
        validate_structural_inventory_v2(inventory, registry, source_audit)
        if inventory["source_id"] != source_id:
            raise ValidationError("inventory belongs to another source")
    validate_v2(quarantine_index, "evaluation-evidence.schema.json")
    if quarantine_index.get("record_kind") != "quarantine_index":
        raise ValidationError("expected quarantine_index")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "admission_receipt",
        "source_id": source_id,
        "registry_sha256": canonical_sha256(registry),
        "audited_artifacts_sha256": canonical_sha256(rows),
        "storage_attestation_sha256": canonical_sha256(storage_attestation),
        "licence_review_sha256": canonical_sha256(licence_review),
        "inventory_sha256s": sorted(canonical_sha256(item) for item in inventory_values),
        "quarantine_index_sha256": canonical_sha256(quarantine_index),
        "decision": "admitted",
        "condition": "admitted_with_mandatory_quarantine",
        "assessed_at": assessed_at or _utc_now(),
        "assessor": assessor,
    }
    validate_v2(result, "control-evidence.schema.json")
    return result


def _audit_status_map(audit: dict[str, Any]) -> dict[tuple[str, str], str]:
    return {
        (item["source_id"], item["artifact_id"]): item["status"]
        for item in audit["artifacts"]
    }


def evaluate_gate_v2(
    *,
    evaluated_at: str,
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    storage_attestation: dict[str, Any] | None,
    source_audit: dict[str, Any] | None,
    licence_reviews: Iterable[dict[str, Any]] = (),
    verified_terms_sha256: Mapping[str, str] | None = None,
    seal_receipts: Iterable[dict[str, Any]] = (),
    quarantine_contributions: Iterable[dict[str, Any]] = (),
    quarantine_index: dict[str, Any] | None = None,
    structural_inventories: Iterable[dict[str, Any]] = (),
    admission_receipts: Iterable[dict[str, Any]] = (),
    verified_seal_ids: Iterable[str] = (),
    evaluation_access_events: Mapping[str, Iterable[dict[str, Any]]] | None = None,
    evaluation_access_heads: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate v2 evidence.  This function can never authorize training."""

    blockers: set[str] = set()
    evidence: set[str] = set()
    verified_terms = dict(verified_terms_sha256 or {})

    try:
        observed_schemas = validate_schema_lock_v2()
        schemas_frozen = True
        evidence.add(f"phase0_v2_schemas:{canonical_sha256(observed_schemas)}")
    except Exception as exc:  # fail-closed reporting boundary
        schemas_frozen = False
        blockers.add(f"schemas_invalid:{type(exc).__name__}:{exc}")

    try:
        validate_source_registry_v2(source_registry)
        source_registry_valid = True
        evidence.add(f"source_registry:{canonical_sha256(source_registry)}")
    except Exception as exc:
        source_registry_valid = False
        blockers.add(f"source_registry_invalid:{type(exc).__name__}:{exc}")
    publisher_pins_ready = source_registry_valid and all(
        _publisher_pins_verified(source)
        for source in source_registry.get("sources", [])
        if source.get("role") == "foundation_candidate"
    )
    if not publisher_pins_ready:
        blockers.add("publisher_checksum_pins_not_verified")
    try:
        validate_evaluation_registry_v2(evaluation_registry)
        evaluation_registry_valid = True
        evidence.add(f"evaluation_registry:{canonical_sha256(evaluation_registry)}")
    except Exception as exc:
        evaluation_registry_valid = False
        blockers.add(f"evaluation_registry_invalid:{type(exc).__name__}:{exc}")

    storage_identity_ready = False
    if storage_attestation is None:
        blockers.add("storage_attestation_missing")
    elif source_registry_valid:
        try:
            validate_storage_attestation_v2(
                storage_attestation, source_registry, evaluated_at=evaluated_at
            )
            storage_identity_ready = True
            evidence.add(
                f"storage_attestation:{canonical_sha256(storage_attestation)}"
            )
        except Exception as exc:
            blockers.add(f"storage_attestation_invalid:{type(exc).__name__}:{exc}")

    source_audit_ready = False
    all_foundation_bytes_ready = False
    audit_status: dict[tuple[str, str], str] = {}
    if source_audit is None:
        blockers.add("source_audit_missing")
    elif source_registry_valid and storage_identity_ready:
        try:
            validate_source_audit_v2(source_audit)
            now = _parse_time(evaluated_at, "evaluated_at")
            completed = _parse_time(source_audit["completed_at"], "completed_at")
            if completed > now:
                raise ValidationError("source audit is from the future")
            if now - completed > SOURCE_AUDIT_MAX_AGE:
                raise ValidationError("source audit is stale")
            if source_audit["registry_sha256"] != canonical_sha256(source_registry):
                raise ValidationError("source audit registry mismatch")
            if source_audit["storage_attestation_sha256"] != canonical_sha256(
                storage_attestation
            ):
                raise ValidationError("source audit storage attestation mismatch")
            audit_status = _audit_status_map(source_audit)
            expected_pairs = {
                (source["source_id"], artifact["artifact_id"])
                for source in source_registry["sources"]
                for artifact in source["artifacts"]
            }
            if set(audit_status) != expected_pairs:
                raise ValidationError("source audit artifact coverage mismatch")
            preexisting_pairs = {
                (source["source_id"], artifact["artifact_id"])
                for source in source_registry["sources"]
                for artifact in source["artifacts"]
                if artifact["availability"] == "preexisting"
            }
            failed_preexisting = sorted(
                pair for pair in preexisting_pairs if audit_status[pair] != "verified"
            )
            if failed_preexisting:
                raise ValidationError(
                    f"preexisting lake artifacts are not verified: {failed_preexisting}"
                )
            source_audit_ready = True
            foundation_pairs = {
                (source["source_id"], artifact["artifact_id"])
                for source in source_registry["sources"]
                if source["role"] == "foundation_candidate"
                for artifact in source["artifacts"]
            }
            all_foundation_bytes_ready = (
                publisher_pins_ready
                and bool(foundation_pairs)
                and all(audit_status[pair] == "verified" for pair in foundation_pairs)
            )
            evidence.add(f"source_audit:{canonical_sha256(source_audit)}")
        except Exception as exc:
            blockers.add(f"source_audit_invalid:{type(exc).__name__}:{exc}")
    if not source_audit_ready:
        blockers.add("source_audit_not_ready")
    if not all_foundation_bytes_ready:
        blockers.add("foundation_bytes_not_ready")

    try:
        reviews_by_id = _review_by_id(licence_reviews)
    except Exception as exc:
        reviews_by_id = {}
        blockers.add(f"licence_reviews_invalid:{type(exc).__name__}:{exc}")
    licensing_ready = source_registry_valid and evaluation_registry_valid
    if source_registry_valid:
        for source in source_registry["sources"]:
            if source["role"] != "foundation_candidate":
                continue
            review_id = source["licence_review_id"]
            review = reviews_by_id.get(review_id)
            try:
                if review is None or review_id not in verified_terms:
                    raise ValidationError("review or verified terms snapshot is missing")
                verify_licence_review_v2(
                    review,
                    verified_terms[review_id],
                    subject_kind="source",
                    subject_id=source["source_id"],
                    required_uses={
                        "acquire",
                        "inventory",
                        "quarantine",
                        "transform",
                        "embed",
                    },
                )
                if review["review_id"] != review_id:
                    raise ValidationError("registry licence review binding mismatch")
            except Exception as exc:
                licensing_ready = False
                blockers.add(
                    f"source_licence_not_ready:{source['source_id']}:{type(exc).__name__}:{exc}"
                )
    if evaluation_registry_valid:
        for dataset in evaluation_registry["datasets"]:
            review_id = dataset["licence_review_id"]
            review = reviews_by_id.get(review_id)
            try:
                if review is None or review_id not in verified_terms:
                    raise ValidationError("review or verified terms snapshot is missing")
                verify_licence_review_v2(
                    review,
                    verified_terms[review_id],
                    subject_kind="evaluation",
                    subject_id=dataset["dataset_id"],
                    required_uses={"acquire", "quarantine", "evaluate"},
                )
            except Exception as exc:
                licensing_ready = False
                blockers.add(
                    f"evaluation_licence_not_ready:{dataset['dataset_id']}:{type(exc).__name__}:{exc}"
                )
    if not licensing_ready:
        blockers.add("licensing_not_ready")

    contributions = list(quarantine_contributions)
    receipts = list(seal_receipts)
    access_events_by_seal = {
        seal_id: list(events)
        for seal_id, events in (evaluation_access_events or {}).items()
    }
    access_heads = dict(evaluation_access_heads or {})
    contribution_by_seal: dict[str, dict[str, Any]] = {}
    receipt_by_seal: dict[str, dict[str, Any]] = {}
    public_confirmatory_ready = evaluation_registry_valid
    for contribution in contributions:
        try:
            validate_v2(contribution, "evaluation-evidence.schema.json")
            seal_id = contribution["seal_id"]
            if seal_id in contribution_by_seal:
                raise ValidationError(f"duplicate contribution: {seal_id}")
            contribution_by_seal[seal_id] = contribution
        except Exception as exc:
            public_confirmatory_ready = False
            blockers.add(f"contribution_invalid:{type(exc).__name__}:{exc}")
    verified_seals = set(verified_seal_ids)
    for receipt in receipts:
        try:
            validate_v2(receipt, "evaluation-evidence.schema.json")
            seal_id = receipt["seal_id"]
            if seal_id in receipt_by_seal:
                raise ValidationError(f"duplicate seal receipt: {seal_id}")
            receipt_by_seal[seal_id] = receipt
            if seal_id not in verified_seals:
                raise ValidationError("ciphertext has not been independently verified")
            contribution = contribution_by_seal.get(seal_id)
            if contribution is None:
                raise ValidationError("matching contribution is missing")
            verify_seal_receipt_v2(receipt, contribution)
            evidence.add(f"seal:{seal_id}:{canonical_sha256(receipt)}")
        except Exception as exc:
            public_confirmatory_ready = False
            blockers.add(f"seal_invalid:{type(exc).__name__}:{exc}")

    if evaluation_registry_valid:
        for dataset in evaluation_registry["datasets"]:
            seal_id = dataset["seal_id"]
            receipt = receipt_by_seal.get(seal_id)
            contribution = contribution_by_seal.get(seal_id)
            try:
                if _DEVELOPMENT_PARTITION.search(dataset["partition"].casefold()):
                    raise ValidationError(
                        "development or validation partition cannot be confirmatory"
                    )
                if dataset["status"] != "sealed" or dataset["blockers"]:
                    raise ValidationError("evaluation is not sealed and blocker-free")
                if receipt is None or contribution is None or seal_id not in verified_seals:
                    raise ValidationError("evaluation seal evidence is incomplete")
                for field in (
                    "dataset_id",
                    "resolved_version",
                    "archive_sha256",
                    "adapter_id",
                    "adapter_sha256",
                ):
                    if dataset[field] != receipt[field] or dataset[field] != contribution[field]:
                        raise ValidationError(f"evaluation binding mismatch: {field}")
            except Exception as exc:
                public_confirmatory_ready = False
                blockers.add(
                    f"public_evaluation_not_ready:{dataset['dataset_id']}:{type(exc).__name__}:{exc}"
                )
    expected_seal_ids = {
        item["seal_id"] for item in evaluation_registry.get("datasets", [])
    }
    if set(receipt_by_seal) != expected_seal_ids:
        public_confirmatory_ready = False
        blockers.add("seal_set_mismatch")
    if set(access_events_by_seal) != expected_seal_ids:
        public_confirmatory_ready = False
        blockers.add("access_log_set_mismatch")
    if set(access_heads) != expected_seal_ids:
        public_confirmatory_ready = False
        blockers.add("access_log_anchor_set_mismatch")
    for seal_id in sorted(expected_seal_ids):
        try:
            events = access_events_by_seal.get(seal_id)
            if events is None:
                raise ValidationError("access log is missing")
            if not events:
                raise ValidationError("access log is empty")
            expected_head = access_heads.get(seal_id)
            if expected_head is None:
                raise ValidationError("access-log anchor is missing")
            verify_access_chain(events, expected_head=expected_head)
            if any(event["seal_id"] != seal_id for event in events):
                raise ValidationError("access log contains a different seal_id")
            if events[0]["action"] != "seal_created":
                raise ValidationError("access log does not begin with seal_created")
            consuming_actions = sorted(
                {
                    event["action"]
                    for event in events
                    if consumes_evaluation(event["action"])
                }
            )
            if consuming_actions:
                raise ValidationError(
                    f"evaluation is consumed or retired: {consuming_actions}"
                )
            evidence.add(f"access_log:{seal_id}:{expected_head}")
        except Exception as exc:
            public_confirmatory_ready = False
            blockers.add(
                f"evaluation_access_not_ready:{seal_id}:{type(exc).__name__}:{exc}"
            )
    if not public_confirmatory_ready:
        blockers.add("public_confirmatory_not_ready")

    quarantine_ready = False
    if quarantine_index is None:
        blockers.add("quarantine_index_missing")
    else:
        try:
            validate_v2(quarantine_index, "evaluation-evidence.schema.json")
            recomputed = compile_quarantine_index_v2(
                contributions, index_id=quarantine_index["index_id"]
            )
            if recomputed != quarantine_index:
                raise QuarantineError("public quarantine index differs from contributions")
            quarantine_ready = True
            evidence.add(f"quarantine_index:{canonical_sha256(quarantine_index)}")
        except Exception as exc:
            blockers.add(f"quarantine_invalid:{type(exc).__name__}:{exc}")
    if not quarantine_ready:
        blockers.add("quarantine_not_ready")

    inventory_values = list(structural_inventories)
    inventory_by_artifact: dict[str, dict[str, Any]] = {}
    structural_inventory_ready = all_foundation_bytes_ready
    if source_registry_valid and source_audit is not None:
        for inventory in inventory_values:
            try:
                artifact_id = inventory["artifact_id"]
                if artifact_id in inventory_by_artifact:
                    raise ValidationError(f"duplicate inventory: {artifact_id}")
                validate_structural_inventory_v2(inventory, source_registry, source_audit)
                inventory_by_artifact[artifact_id] = inventory
                evidence.add(f"inventory:{artifact_id}:{canonical_sha256(inventory)}")
            except Exception as exc:
                structural_inventory_ready = False
                blockers.add(f"inventory_invalid:{type(exc).__name__}:{exc}")
        expected_inventory_ids = {
            artifact["artifact_id"]
            for source in source_registry["sources"]
            if source["role"] == "foundation_candidate"
            for artifact in source["artifacts"]
        }
        if set(inventory_by_artifact) != expected_inventory_ids:
            structural_inventory_ready = False
            blockers.add("inventory_set_mismatch")
    else:
        structural_inventory_ready = False
    if not structural_inventory_ready:
        blockers.add("structural_inventory_not_ready")

    admission_values = list(admission_receipts)
    admission_by_source: dict[str, dict[str, Any]] = {}
    admission_ready = structural_inventory_ready and licensing_ready and quarantine_ready
    if source_registry_valid and source_audit is not None and storage_attestation is not None:
        expected_sources = {
            source["source_id"]
            for source in source_registry["sources"]
            if source["role"] == "foundation_candidate"
        }
        for receipt in admission_values:
            try:
                validate_v2(receipt, "control-evidence.schema.json")
                source_id = receipt["source_id"]
                if source_id in admission_by_source:
                    raise ValidationError(f"duplicate admission receipt: {source_id}")
                source = next(
                    item for item in source_registry["sources"] if item["source_id"] == source_id
                )
                review = reviews_by_id[source["licence_review_id"]]
                rows = _audit_rows_for_source(source_audit, source_id)
                source_inventory_hashes = sorted(
                    canonical_sha256(item)
                    for item in inventory_values
                    if item.get("source_id") == source_id
                )
                bindings = {
                    "registry_sha256": canonical_sha256(source_registry),
                    "audited_artifacts_sha256": canonical_sha256(rows),
                    "storage_attestation_sha256": canonical_sha256(storage_attestation),
                    "licence_review_sha256": canonical_sha256(review),
                    "inventory_sha256s": source_inventory_hashes,
                    "quarantine_index_sha256": canonical_sha256(quarantine_index),
                }
                for field, expected in bindings.items():
                    if receipt[field] != expected:
                        raise ValidationError(f"admission binding mismatch: {field}")
                if receipt["decision"] != "admitted":
                    raise ValidationError("source admission is blocked")
                admission_by_source[source_id] = receipt
                evidence.add(f"admission:{source_id}:{canonical_sha256(receipt)}")
            except Exception as exc:
                admission_ready = False
                blockers.add(f"admission_invalid:{type(exc).__name__}:{exc}")
        if set(admission_by_source) != expected_sources:
            admission_ready = False
            blockers.add("admission_set_mismatch")
    else:
        admission_ready = False
    if not admission_ready:
        blockers.add("admission_not_ready")

    foundation_acquisition_authorized = all(
        [
            schemas_frozen,
            storage_identity_ready,
            source_audit_ready,
            licensing_ready,
            public_confirmatory_ready,
            quarantine_ready,
        ]
    )
    foundation_transform_ready = all(
        [
            foundation_acquisition_authorized,
            all_foundation_bytes_ready,
            structural_inventory_ready,
            admission_ready,
        ]
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": "phase0-public-foundation-v2",
        "evaluated_at": evaluated_at,
        "schemas_frozen": schemas_frozen,
        "storage_identity_ready": storage_identity_ready,
        "source_audit_ready": source_audit_ready,
        "licensing_ready": licensing_ready,
        "public_confirmatory_ready": public_confirmatory_ready,
        "quarantine_ready": quarantine_ready,
        "structural_inventory_ready": structural_inventory_ready,
        "admission_ready": admission_ready,
        "foundation_acquisition_authorized": foundation_acquisition_authorized,
        "foundation_transform_ready": foundation_transform_ready,
        "training_authorized": False,
        "blockers": sorted(blockers),
        "evidence": sorted(evidence),
    }
    validate_v2(report, "gate.schema.json")
    return report
