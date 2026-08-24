"""Versioned evaluation roles and public quarantine evidence for Phase 0 v4."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from .canonical import canonical_sha256
from .errors import QuarantineError, ValidationError
from .inventory import hash_file
from .quarantine import normalize_identifier
from .v4_contracts import SCHEMA_VERSION_V4, validate_v4


_DEVELOPMENT_PARTITION = re.compile(
    r"(?:^|[^a-z0-9])(?:dev|development|validation)(?:$|[^a-z0-9])"
)
_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "label",
        "labels",
        "answer",
        "answers",
        "target",
        "targets",
        "split",
        "membership",
        "private_payload",
        "commitment_nonce",
    }
)
_ROLE_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "confirmatory": frozenset({"confirmatory", "development", "diagnostic", "retired"}),
    "development": frozenset({"development", "retired"}),
    "diagnostic": frozenset({"diagnostic", "retired"}),
    "retired": frozenset({"retired"}),
}
_CUSTODY_ORDER = {
    "declared": 0,
    "pinned": 1,
    "sealed": 2,
    "consumed": 3,
    "retired": 4,
}


@dataclass(frozen=True)
class VerifiedSealReceipt:
    receipt: dict[str, Any]
    sha256: str
    ciphertext_sha256: str


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return duplicate


def _source_artifacts(
    registry: Mapping[str, Any],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for source in registry["sources"]:
        for artifact in source["artifacts"]:
            artifact_id = artifact["artifact_id"]
            if artifact_id in result:
                raise ValidationError(f"duplicate artifact_id: {artifact_id}")
            result[artifact_id] = (source, artifact)
    return result


def validate_source_registry_v4(
    registry: dict[str, Any], predecessor: dict[str, Any] | None = None
) -> None:
    validate_v4(registry, "registry.schema.json")
    if registry.get("registry_kind") != "sources":
        raise ValidationError("expected a Phase 0 v4 source registry")
    source_ids = [item["source_id"] for item in registry["sources"]]
    if duplicate := _duplicates(source_ids):
        raise ValidationError(f"duplicate source_id: {sorted(duplicate)}")
    review_ids = [item["licence_review_id"] for item in registry["sources"]]
    if duplicate := _duplicates(review_ids):
        raise ValidationError(f"duplicate source licence review: {sorted(duplicate)}")
    locator_ids = [item["locator_id"] for item in registry["storage_requirements"]]
    if duplicate := _duplicates(locator_ids):
        raise ValidationError(f"duplicate locator_id: {sorted(duplicate)}")
    locator_set = set(locator_ids)
    artifacts = _source_artifacts(registry)
    checksum_lengths = {"md5": 32, "sha1": 40, "sha256": 64}
    for source, artifact in artifacts.values():
        if _parse_time(source["snapshot_at"], "source snapshot_at") > _parse_time(
            registry["generated_at"], "source registry generated_at"
        ):
            raise ValidationError("source snapshot is newer than its registry")
        if artifact["locator_id"] not in locator_set:
            raise ValidationError(
                f"artifact uses unknown locator: {artifact['artifact_id']}"
            )
        relative = Path(artifact["filename"])
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise ValidationError(
                f"artifact filename escapes its storage root: {artifact['artifact_id']}"
            )
        source_url = urlparse(str(artifact["source_url"]))
        if source_url.scheme != "https" or source_url.hostname is None:
            raise ValidationError(
                f"artifact source URL must use HTTPS: {artifact['artifact_id']}"
            )
        algorithms = [item["algorithm"] for item in artifact["checksums"]]
        if duplicate := _duplicates(algorithms):
            raise ValidationError(
                f"duplicate checksum for {artifact['artifact_id']}: {sorted(duplicate)}"
            )
        for checksum in artifact["checksums"]:
            value = checksum["value"]
            if len(value) != checksum_lengths[checksum["algorithm"]] or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise ValidationError(
                    f"invalid checksum for {artifact['artifact_id']}: {checksum['algorithm']}"
                )
        if not any(
            item["origin"] == "publisher" and item["algorithm"] in {"sha1", "sha256"}
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
                f"inventory counter policy overlaps for {artifact['artifact_id']}"
            )
        if source["role"] == "foundation_candidate" and not source["quarantine_required"]:
            raise ValidationError("foundation sources must require quarantine")

    requirements = registry["publisher_evidence_requirements"]
    evidence_ids = [item["evidence_id"] for item in requirements]
    if duplicate := _duplicates(evidence_ids):
        raise ValidationError(f"duplicate publisher evidence_id: {sorted(duplicate)}")
    requirement_artifacts = [item["artifact_id"] for item in requirements]
    if duplicate := _duplicates(requirement_artifacts):
        raise ValidationError(
            f"duplicate publisher artifact requirement: {sorted(duplicate)}"
        )
    if set(requirement_artifacts) != set(artifacts):
        raise ValidationError("publisher evidence requirement set does not match artifacts")
    for requirement in requirements:
        source, _ = artifacts[requirement["artifact_id"]]
        if requirement["source_id"] != source["source_id"]:
            raise ValidationError("publisher requirement source binding mismatch")
        statement_url = requirement["statement_url"]
        if statement_url is not None:
            parsed_statement = urlparse(statement_url)
            if parsed_statement.scheme != "https" or parsed_statement.hostname is None:
                raise ValidationError("publisher statement URL must use HTTPS")

    if predecessor is None:
        return
    if registry["previous_registry_sha256"] != canonical_sha256(predecessor):
        raise ValidationError("source predecessor digest mismatch")
    if predecessor.get("registry_kind") != "sources":
        raise ValidationError("source predecessor has the wrong registry kind")
    if registry["sources"] != predecessor.get("sources"):
        raise ValidationError("source entries must remain byte-identical across v4 migration")
    previous_storage = {
        item["locator_id"]: item for item in predecessor.get("storage_requirements", [])
    }
    current_storage = {
        item["locator_id"]: item for item in registry["storage_requirements"]
    }
    if set(previous_storage) != set(current_storage):
        raise ValidationError("storage requirement set changed across registry versions")
    for locator_id, old in previous_storage.items():
        new = current_storage[locator_id]
        for field in ("provider", "required_root"):
            if new[field] != old[field]:
                raise ValidationError(f"storage requirement changed: {locator_id}:{field}")
        for field in ("provider_resource_id", "root_resource_id"):
            if old[field] is not None and new[field] != old[field]:
                raise ValidationError(f"stable storage identity changed: {locator_id}:{field}")


def _validate_exposure_history(dataset: Mapping[str, Any]) -> None:
    history = dataset["exposure_history"]
    event_ids = [item["event_id"] for item in history]
    if duplicate := _duplicates(event_ids):
        raise ValidationError(f"duplicate exposure event: {sorted(duplicate)}")
    times = [_parse_time(item["recorded_at"], "exposure recorded_at") for item in history]
    if times != sorted(times):
        raise ValidationError("exposure history must be chronological")
    kinds = {item["event_kind"] for item in history}
    exposure = dataset["project_exposure"]
    required_kind = {
        "metadata_only": "metadata_only",
        "development": "publisher_designated_development",
        "content_exposed": "content_exposed",
        "consumed": "result_consumed",
        "retired": "retired",
    }[exposure]
    if required_kind not in kinds:
        raise ValidationError(
            f"exposure history does not support project_exposure: {dataset['dataset_id']}"
        )


def _validate_evaluation_semantics(dataset: Mapping[str, Any]) -> None:
    _validate_exposure_history(dataset)
    role = dataset["usage_role"]
    exposure = dataset["project_exposure"]
    custody = dataset["custody_state"]
    partition = (dataset.get("partition") or "").casefold()
    if _DEVELOPMENT_PARTITION.search(partition) and role != "development":
        raise ValidationError("development or validation partition must remain development")
    if role == "confirmatory":
        if not dataset["confirmation_eligible"]:
            raise ValidationError("confirmatory evaluation is marked ineligible")
        if exposure != "metadata_only":
            raise ValidationError("exposed evaluation cannot be confirmatory")
        if not dataset["seal_id"]:
            raise ValidationError("confirmatory evaluation lacks a seal_id")
    else:
        if dataset["confirmation_eligible"]:
            raise ValidationError("non-confirmatory evaluation cannot be eligible")
        if dataset["seal_id"] is not None:
            raise ValidationError("non-confirmatory evaluation must not carry a seal_id")
        if dataset["custodian_signing_key_fingerprint"] is not None:
            raise ValidationError("non-confirmatory evaluation must not pin a custodian key")
    if role == "development" and exposure != "development":
        raise ValidationError("development role must retain development exposure")
    if role == "diagnostic" and exposure not in {"development", "content_exposed"}:
        raise ValidationError("diagnostic role must retain its exposure state")
    if role == "retired" and custody != "retired":
        raise ValidationError("retired role must have retired custody state")
    if custody == "sealed" and role != "confirmatory":
        raise ValidationError("only confirmatory evaluations may be sealed")
    if custody in {"pinned", "sealed", "consumed"} and not all(
        (
            dataset["resolved_version"],
            dataset["partition"],
            dataset["archive_sha256"],
            dataset["adapter_id"],
            dataset["adapter_sha256"],
        )
    ):
        raise ValidationError("pinned evaluation lacks immutable asset bindings")
    if custody == "sealed" and dataset["blockers"]:
        raise ValidationError("sealed evaluation retains blockers")


def validate_evaluation_registry_v4(
    registry: dict[str, Any], predecessor: dict[str, Any] | None = None
) -> None:
    validate_v4(registry, "registry.schema.json")
    if registry.get("registry_kind") != "evaluations":
        raise ValidationError("expected a Phase 0 v4 evaluation registry")
    dataset_ids = [item["dataset_id"] for item in registry["datasets"]]
    if duplicate := _duplicates(dataset_ids):
        raise ValidationError(f"duplicate dataset_id: {sorted(duplicate)}")
    review_ids = [item["licence_review_id"] for item in registry["datasets"]]
    if duplicate := _duplicates(review_ids):
        raise ValidationError(f"duplicate evaluation licence review: {sorted(duplicate)}")
    seal_ids = [item["seal_id"] for item in registry["datasets"] if item["seal_id"]]
    if duplicate := _duplicates(seal_ids):
        raise ValidationError(f"duplicate seal_id: {sorted(duplicate)}")
    for dataset in registry["datasets"]:
        _validate_evaluation_semantics(dataset)
        if _parse_time(
            dataset["exposure_history"][-1]["recorded_at"],
            "exposure recorded_at",
        ) > _parse_time(registry["generated_at"], "evaluation registry generated_at"):
            raise ValidationError("evaluation exposure history is newer than its registry")
    if not any(
        item["usage_role"] == "confirmatory" for item in registry["datasets"]
    ):
        raise ValidationError("evaluation registry has no confirmatory dataset")

    if predecessor is None:
        return
    if registry["previous_registry_sha256"] != canonical_sha256(predecessor):
        raise ValidationError("evaluation predecessor digest mismatch")
    if predecessor.get("registry_kind") != "evaluations":
        raise ValidationError("evaluation predecessor has the wrong registry kind")
    old_by_id = {item["dataset_id"]: item for item in predecessor.get("datasets", [])}
    new_by_id = {item["dataset_id"]: item for item in registry["datasets"]}
    if not set(old_by_id) <= set(new_by_id):
        raise ValidationError("evaluation registry dropped historical entries")
    predecessor_is_v4 = predecessor.get("schema_version") == SCHEMA_VERSION_V4
    for dataset_id, old in old_by_id.items():
        new = new_by_id[dataset_id]
        if new["previous_entry_sha256"] != canonical_sha256(old):
            raise ValidationError(f"evaluation entry predecessor mismatch: {dataset_id}")
        old_task_role = old.get("task_role", old.get("role"))
        immutable = {
            "task_role": old_task_role,
            "official_source": old.get("official_source"),
            "partition": old.get("partition"),
            "licence_review_id": old.get("licence_review_id"),
        }
        for field, expected in immutable.items():
            if new[field] != expected:
                raise ValidationError(f"evaluation identity changed: {dataset_id}:{field}")
        for field in ("resolved_version", "archive_sha256", "adapter_id", "adapter_sha256"):
            old_value = old.get(field)
            if old_value is not None and new[field] != old_value:
                raise ValidationError(f"pinned evaluation asset changed: {dataset_id}:{field}")
        old_partition = (old.get("partition") or "").casefold()
        if _DEVELOPMENT_PARTITION.search(old_partition) and new["usage_role"] != "development":
            raise ValidationError("role laundering from a development partition")
        if any("exposure" in item for item in old.get("blockers", [])) and new[
            "usage_role"
        ] not in {"diagnostic", "retired"}:
            raise ValidationError("exposed evaluation must be diagnostic or retired")
        if not predecessor_is_v4:
            continue
        if new["usage_role"] not in _ROLE_TRANSITIONS[old["usage_role"]]:
            raise ValidationError(f"prohibited evaluation role transition: {dataset_id}")
        old_history = old["exposure_history"]
        if new["exposure_history"][: len(old_history)] != old_history:
            raise ValidationError(f"exposure history was rewritten: {dataset_id}")
        if _CUSTODY_ORDER[new["custody_state"]] < _CUSTODY_ORDER[old["custody_state"]]:
            raise ValidationError(f"custody state moved backwards: {dataset_id}")


def _normalized_identifier(value: Mapping[str, Any]) -> dict[str, Any]:
    identifier = normalize_identifier(
        str(value["namespace"]), str(value["value"]), value.get("source_version")
    )
    return {
        "namespace": identifier.namespace,
        "value": identifier.value,
        "source_version": identifier.source_version,
    }


def _reject_forbidden_public_fields(value: Any, path: str = "$.") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in _FORBIDDEN_PUBLIC_KEYS:
                raise QuarantineError(f"forbidden public quarantine field at {path}{key}")
            _reject_forbidden_public_fields(child, f"{path}{key}.")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _reject_forbidden_public_fields(child, f"{path}{index}.")


def _selector_count(selectors: Mapping[str, Sequence[Any]]) -> int:
    return sum(len(selectors[name]) for name in selectors)


def build_quarantine_contribution_v4(envelope: dict[str, Any]) -> dict[str, Any]:
    validate_v4(envelope, "evaluation-evidence.schema.json")
    if envelope.get("record_kind") != "evaluation_envelope":
        raise ValidationError("expected an evaluation_envelope")
    public_records: list[dict[str, Any]] = []
    expected_total = 0
    resolved_total = 0
    selector_total = 0
    for record in envelope["records"]:
        expected = sorted(
            (_normalized_identifier(item) for item in record["expected_dependency_units"]),
            key=canonical_sha256,
        )
        resolved = sorted(
            (_normalized_identifier(item) for item in record["resolved_dependency_units"]),
            key=canonical_sha256,
        )
        if record["unresolved_dependency_units"] or expected != resolved:
            raise QuarantineError(
                f"incomplete dependency closure: {record['record_id']}"
            )
        selectors = {
            "identifiers": sorted(
                (_normalized_identifier(item) for item in record["selectors"]["identifiers"]),
                key=canonical_sha256,
            ),
            "raw_hashes": sorted(set(record["selectors"]["raw_hashes"])),
            "normalized_hashes": sorted(
                set(record["selectors"]["normalized_hashes"])
            ),
            "fingerprints": sorted(
                record["selectors"]["fingerprints"], key=canonical_sha256
            ),
        }
        if _selector_count(selectors) == 0:
            raise QuarantineError(
                f"sealed record has no quarantine selector: {record['record_id']}"
            )
        public_records.append(
            {
                "record_commitment": canonical_sha256(
                    {
                        "commitment_nonce": envelope["commitment_nonce"],
                        "record": record,
                    }
                ),
                "selectors": selectors,
                "expected_dependency_count": len(expected),
                "resolved_dependency_count": len(resolved),
            }
        )
        expected_total += len(expected)
        resolved_total += len(resolved)
        selector_total += _selector_count(selectors)
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "quarantine_contribution",
        "dataset_id": envelope["dataset_id"],
        "usage_role": envelope["usage_role"],
        "origin": (
            "sealed_confirmatory"
            if envelope["usage_role"] == "confirmatory"
            else "pinned_nonconfirmatory"
        ),
        "resolved_version": envelope["resolved_version"],
        "archive_sha256": envelope["archive_sha256"],
        "adapter_id": envelope["adapter_id"],
        "adapter_sha256": envelope["adapter_sha256"],
        "envelope_sha256": canonical_sha256(envelope),
        "records": sorted(public_records, key=lambda item: item["record_commitment"]),
        "coverage": {
            "record_count": len(public_records),
            "covered_record_count": len(public_records),
            "uncovered_record_count": 0,
            "expected_dependency_count": expected_total,
            "resolved_dependency_count": resolved_total,
            "unresolved_dependency_count": 0,
            "selector_count": selector_total,
        },
        "training_authorized": False,
    }
    validate_quarantine_contribution_v4(result)
    return result


def validate_quarantine_contribution_v4(contribution: dict[str, Any]) -> None:
    """Validate public contribution semantics, not only its JSON shape."""

    validate_v4(contribution, "evaluation-evidence.schema.json")
    if contribution.get("record_kind") != "quarantine_contribution":
        raise ValidationError("expected a quarantine_contribution")
    _reject_forbidden_public_fields(contribution)
    expected_origin = (
        "sealed_confirmatory"
        if contribution["usage_role"] == "confirmatory"
        else "pinned_nonconfirmatory"
    )
    if contribution["origin"] != expected_origin:
        raise QuarantineError("quarantine contribution custody origin is inconsistent")

    records = contribution["records"]
    commitments = [item["record_commitment"] for item in records]
    if len(commitments) != len(set(commitments)):
        raise QuarantineError("duplicate quarantine record commitment")
    if records != sorted(records, key=lambda item: item["record_commitment"]):
        raise QuarantineError("quarantine records are not canonically ordered")

    expected_dependency_total = 0
    resolved_dependency_total = 0
    selector_total = 0
    for record in records:
        if record["expected_dependency_count"] != record["resolved_dependency_count"]:
            raise QuarantineError("quarantine record dependency closure is incomplete")
        selectors = record["selectors"]
        normalized_identifiers = [
            _normalized_identifier(item) for item in selectors["identifiers"]
        ]
        if normalized_identifiers != selectors["identifiers"]:
            raise QuarantineError("quarantine identifiers are not normalized")
        if selectors["identifiers"] != sorted(
            selectors["identifiers"], key=canonical_sha256
        ):
            raise QuarantineError("quarantine identifiers are not canonically ordered")
        identifier_hashes = [
            canonical_sha256(item) for item in selectors["identifiers"]
        ]
        if len(identifier_hashes) != len(set(identifier_hashes)):
            raise QuarantineError("duplicate quarantine identifier")
        if selectors["raw_hashes"] != sorted(selectors["raw_hashes"]):
            raise QuarantineError("quarantine raw hashes are not canonically ordered")
        if selectors["normalized_hashes"] != sorted(
            selectors["normalized_hashes"]
        ):
            raise QuarantineError(
                "quarantine normalized hashes are not canonically ordered"
            )
        if selectors["fingerprints"] != sorted(
            selectors["fingerprints"], key=canonical_sha256
        ):
            raise QuarantineError("quarantine fingerprints are not canonically ordered")
        fingerprint_ids = [
            item["fingerprint_id"] for item in selectors["fingerprints"]
        ]
        if len(fingerprint_ids) != len(set(fingerprint_ids)):
            raise QuarantineError("duplicate quarantine fingerprint identifier")
        count = _selector_count(selectors)
        if count == 0:
            raise QuarantineError("quarantine record lacks selectors")
        expected_dependency_total += record["expected_dependency_count"]
        resolved_dependency_total += record["resolved_dependency_count"]
        selector_total += count

    expected_coverage = {
        "record_count": len(records),
        "covered_record_count": len(records),
        "uncovered_record_count": 0,
        "expected_dependency_count": expected_dependency_total,
        "resolved_dependency_count": resolved_dependency_total,
        "unresolved_dependency_count": 0,
        "selector_count": selector_total,
    }
    if contribution["coverage"] != expected_coverage:
        raise QuarantineError("quarantine contribution coverage is inconsistent")


def compile_quarantine_index_v4(
    contributions: Iterable[dict[str, Any]],
    *,
    expected_dataset_ids: Iterable[str] | None = None,
    index_id: str = "public-evaluation-union-v4",
) -> dict[str, Any]:
    values = list(contributions)
    if not values:
        raise QuarantineError("no quarantine contributions supplied")
    by_dataset: dict[str, dict[str, Any]] = {}
    identifiers: dict[str, dict[str, Any]] = {}
    raw_hashes: set[str] = set()
    normalized_hashes: set[str] = set()
    fingerprints: dict[str, dict[str, Any]] = {}
    for contribution in values:
        validate_quarantine_contribution_v4(contribution)
        dataset_id = contribution["dataset_id"]
        if dataset_id in by_dataset:
            raise QuarantineError(f"duplicate contribution: {dataset_id}")
        coverage = contribution["coverage"]
        if (
            coverage["record_count"] != coverage["covered_record_count"]
            or coverage["uncovered_record_count"]
            or coverage["expected_dependency_count"]
            != coverage["resolved_dependency_count"]
            or coverage["unresolved_dependency_count"]
        ):
            raise QuarantineError(f"incomplete contribution: {dataset_id}")
        by_dataset[dataset_id] = contribution
        for record in contribution["records"]:
            for identifier in record["selectors"]["identifiers"]:
                normalized = _normalized_identifier(identifier)
                identifiers[canonical_sha256(normalized)] = normalized
            raw_hashes.update(record["selectors"]["raw_hashes"])
            normalized_hashes.update(record["selectors"]["normalized_hashes"])
            for fingerprint in record["selectors"]["fingerprints"]:
                fingerprint_id = fingerprint["fingerprint_id"]
                current = fingerprints.get(fingerprint_id)
                if current is not None and current != fingerprint:
                    raise QuarantineError(
                        f"conflicting fingerprint_id: {fingerprint_id}"
                    )
                fingerprints[fingerprint_id] = fingerprint
    if expected_dataset_ids is not None and set(by_dataset) != set(expected_dataset_ids):
        raise QuarantineError("quarantine contribution dataset set mismatch")
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "quarantine_index",
        "index_id": index_id,
        "closure_policy_id": "quarantine-closure-v4",
        "source_dataset_ids": sorted(by_dataset),
        "contribution_sha256s": sorted(
            canonical_sha256(value) for value in by_dataset.values()
        ),
        "identifiers": sorted(identifiers.values(), key=canonical_sha256),
        "raw_hashes": sorted(raw_hashes),
        "normalized_hashes": sorted(normalized_hashes),
        "fingerprints": sorted(fingerprints.values(), key=canonical_sha256),
        "training_authorized": False,
    }
    _reject_forbidden_public_fields(result)
    validate_v4(result, "evaluation-evidence.schema.json")
    return result


def make_seal_receipt_v4(
    *,
    evaluation_registry: dict[str, Any],
    envelope: dict[str, Any],
    contribution: dict[str, Any],
    ciphertext_sha256: str,
    public_key_fingerprint: str,
    custodian: str,
    created_at: str,
) -> dict[str, Any]:
    validate_evaluation_registry_v4(evaluation_registry)
    validate_v4(envelope, "evaluation-evidence.schema.json")
    expected_contribution = build_quarantine_contribution_v4(envelope)
    if contribution != expected_contribution:
        raise ValidationError("quarantine contribution does not derive from envelope")
    dataset = next(
        (
            item
            for item in evaluation_registry["datasets"]
            if item["dataset_id"] == envelope["dataset_id"]
        ),
        None,
    )
    if dataset is None:
        raise ValidationError("evaluation envelope uses an unknown dataset")
    if dataset["usage_role"] != "confirmatory":
        raise ValidationError("only confirmatory evaluations may be sealed")
    if _parse_time(created_at, "seal created_at") < _parse_time(
        evaluation_registry["generated_at"], "evaluation registry generated_at"
    ):
        raise ValidationError("seal receipt predates its evaluation registry")
    for field in ("resolved_version", "archive_sha256", "adapter_id", "adapter_sha256"):
        if envelope[field] != dataset[field]:
            raise ValidationError(f"evaluation envelope registry mismatch: {field}")
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "seal_receipt",
        "seal_id": dataset["seal_id"],
        "dataset_id": dataset["dataset_id"],
        "usage_role": "confirmatory",
        "evaluation_registry_sha256": canonical_sha256(evaluation_registry),
        "dataset_entry_sha256": canonical_sha256(dataset),
        "resolved_version": envelope["resolved_version"],
        "archive_sha256": envelope["archive_sha256"],
        "adapter_id": envelope["adapter_id"],
        "adapter_sha256": envelope["adapter_sha256"],
        "envelope_sha256": canonical_sha256(envelope),
        "contribution_sha256": canonical_sha256(contribution),
        "ciphertext_sha256": ciphertext_sha256,
        "public_key_fingerprint": public_key_fingerprint,
        "created_at": created_at,
        "custodian": custodian,
        "record_count": len(envelope["records"]),
        "state": "sealed",
        "training_authorized": False,
    }
    validate_v4(result, "evaluation-evidence.schema.json")
    return result


def verify_seal_receipt_v4(
    receipt: dict[str, Any],
    *,
    evaluation_registry: dict[str, Any],
    contribution: dict[str, Any],
    ciphertext_sha256: str,
) -> None:
    validate_v4(receipt, "evaluation-evidence.schema.json")
    if receipt.get("record_kind") != "seal_receipt":
        raise ValidationError("expected a seal_receipt")
    validate_evaluation_registry_v4(evaluation_registry)
    dataset = next(
        (
            item
            for item in evaluation_registry["datasets"]
            if item["dataset_id"] == receipt["dataset_id"]
        ),
        None,
    )
    if dataset is None:
        raise ValidationError("seal receipt uses an unknown dataset")
    if _parse_time(receipt["created_at"], "seal created_at") < _parse_time(
        evaluation_registry["generated_at"], "evaluation registry generated_at"
    ):
        raise ValidationError("seal receipt predates its evaluation registry")
    bindings = {
        "seal_id": dataset["seal_id"],
        "usage_role": "confirmatory",
        "evaluation_registry_sha256": canonical_sha256(evaluation_registry),
        "dataset_entry_sha256": canonical_sha256(dataset),
        "resolved_version": contribution["resolved_version"],
        "archive_sha256": contribution["archive_sha256"],
        "adapter_id": contribution["adapter_id"],
        "adapter_sha256": contribution["adapter_sha256"],
        "envelope_sha256": contribution["envelope_sha256"],
        "contribution_sha256": canonical_sha256(contribution),
        "ciphertext_sha256": ciphertext_sha256,
        "record_count": contribution["coverage"]["record_count"],
    }
    for field, expected in bindings.items():
        if receipt[field] != expected:
            raise ValidationError(f"seal receipt binding mismatch: {field}")


def verify_seal_ciphertext_v4(
    ciphertext_path: Path,
    receipt: dict[str, Any],
    *,
    evaluation_registry: dict[str, Any],
    contribution: dict[str, Any],
) -> VerifiedSealReceipt:
    measurement = hash_file(ciphertext_path)
    ciphertext_sha256 = f"sha256:{measurement['sha256']}"
    verify_seal_receipt_v4(
        receipt,
        evaluation_registry=evaluation_registry,
        contribution=contribution,
        ciphertext_sha256=ciphertext_sha256,
    )
    return VerifiedSealReceipt(
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        ciphertext_sha256=ciphertext_sha256,
    )
