from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hippocampus_foundation.phase0.canonical import canonical_bytes, canonical_sha256
from hippocampus_foundation.phase0.errors import ValidationError
from hippocampus_foundation.phase0.validation import (
    validate_evaluation_registry,
    validate_instance,
    validate_schema_set,
    validate_source_registry,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _assert_integer_domains_are_canonical_safe(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        declared_type = value.get("type")
        is_integer = declared_type == "integer" or (
            isinstance(declared_type, list) and "integer" in declared_type
        )
        if is_integer:
            assert "maximum" in value, path
            assert value["maximum"] <= MAX_SAFE_JSON_INTEGER, path
        for key, child in value.items():
            _assert_integer_domains_are_canonical_safe(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_integer_domains_are_canonical_safe(child, f"{path}/{index}")


def test_frozen_schema_set_and_checked_in_registries_validate() -> None:
    schemas = validate_schema_set()
    assert {
        "access-event.schema.json",
        "evaluation.schema.json",
        "gate.schema.json",
        "graph.schema.json",
        "quarantine-descriptor.schema.json",
        "quarantine-index.schema.json",
        "quarantine-specification.schema.json",
        "seal.schema.json",
        "source-audit.schema.json",
        "source-manifest.schema.json",
        "storage-map.schema.json",
        "training-example.schema.json",
    }.issubset(schemas)
    validate_source_registry(load("registries/sources.v1.json"))
    validate_evaluation_registry(load("registries/evaluations.v1.json"))
    validate_instance(
        load("registries/storage-map.colab.example.json"),
        "storage-map.schema.json",
    )
    validate_instance(
        load("quarantine/specification.template.json"),
        "quarantine-specification.schema.json",
    )


def test_rfc8785_canonicalization_is_order_independent() -> None:
    left = {"z": [3, 2, 1], "a": {"b": True}}
    right = {"a": {"b": True}, "z": [3, 2, 1]}
    assert canonical_bytes(left) == b'{"a":{"b":true},"z":[3,2,1]}'
    assert canonical_sha256(left) == canonical_sha256(right)


def test_active_schema_integer_domains_fit_rfc8785_safe_range() -> None:
    for relative in ("schemas/phase0/v2", "schemas/phase1/v1", "schemas/phase2/v1"):
        for schema_path in sorted((ROOT / relative).glob("*.schema.json")):
            _assert_integer_domains_are_canonical_safe(
                json.loads(schema_path.read_text(encoding="utf-8")),
                str(schema_path.relative_to(ROOT)),
            )


def test_graph_node_contract_accepts_provenanced_record_and_rejects_extra() -> None:
    record = {
        "record_kind": "node",
        "id": "urn:hf:node:Q42",
        "schema_version": "1.0.0",
        "node_type": "entity",
        "canonical_label": "Douglas Adams",
        "alternate_labels": [],
        "scope_id": "public",
        "valid_time": {"start": None, "end": None, "precision": "source_native"},
        "observation_time": "2026-08-16T00:00:00Z",
        "lifecycle_state": "candidate",
        "provenance_refs": [
            {"namespace": "wikidata.entity", "value": "Q42", "source_version": "20260720"}
        ],
        "risk_policy_id": "risk-v1",
        "risk_class": "ordinary",
        "sensitivity_class": "public",
        "created_at": "2026-08-16T00:00:00Z",
        "version_history": [
            {
                "version": 1,
                "at": "2026-08-16T00:00:00Z",
                "actor": {"namespace": "tool", "value": "fixture"},
                "reason": "contract test"
            }
        ]
    }
    validate_instance(record, "graph.schema.json")
    invalid = {**record, "unregistered_field": True}
    with pytest.raises(ValidationError):
        validate_instance(invalid, "graph.schema.json")


def test_duplicate_source_and_evaluation_ids_fail_semantic_validation() -> None:
    sources = load("registries/sources.v1.json")
    sources["sources"].append(copy.deepcopy(sources["sources"][0]))
    with pytest.raises(ValidationError, match="duplicate source_id"):
        validate_source_registry(sources)

    evaluations = load("registries/evaluations.v1.json")
    evaluations["datasets"].append(copy.deepcopy(evaluations["datasets"][0]))
    with pytest.raises(ValidationError, match="duplicate dataset_id"):
        validate_evaluation_registry(evaluations)


def test_closure_registry_must_match_the_implementation() -> None:
    evaluations = load("registries/evaluations.v1.json")
    evaluations["closure_policy"]["relationship_types"].remove("revision_of")
    with pytest.raises(ValidationError, match="closure policy differs"):
        validate_evaluation_registry(evaluations)
