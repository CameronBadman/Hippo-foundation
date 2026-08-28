"""Frozen Phase 1 schemas and semantic validation."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json

from .errors import Phase1ValidationError

OBJECTIVE_FAMILIES = frozenset(
    {
        "masked_node_attribute",
        "masked_edge_direction",
        "masked_qualifier_value",
        "evidence_span_alignment",
        "local_entity_disambiguation",
        "bounded_path_continuation",
        "neighbourhood_ranking",
        "source_time_conditioned_retrieval",
    }
)

ENCODER_ASSET_PATHS = frozenset(
    {
        "1_Pooling/config.json",
        "config.json",
        "config_sentence_transformers.json",
        "model.safetensors",
        "modules.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    }
)
ENCODER_VERIFICATION_METHOD_V2 = "exact-snapshot-layout-v2"

# These anchors live outside the artifacts they identify.  Values are filled
# only after the checked-in schemas/spec have passed structural validation.
FROZEN_SCHEMA_DIGESTS_V1: dict[str, str] = {
    "artifact.schema.json": "sha256:2147f450a6af5de7f93a4d4ca6976bc4013ce0c06dda4773da811acca4b43478",
    "encoder.schema.json": "sha256:353028524d58f1060403b02dcfa050af22b5a7bfcdb2d245ba71c36792f7b430",
    "gate.schema.json": "sha256:da9728c39be04df9497f6afe85bc3f3b638c1655edb52f423c771b9dc976ad81",
    "graph.schema.json": "sha256:67bae7ea40e5d9ab35abe88055149996dcb5a6d37511cf9588d055ce0d673a0e",
    "objective-example.schema.json": "sha256:bfbc589e253bb709fc50b0b483ff2a8c173fd92af9908216f1cee31a2c30226f",
}
FROZEN_ENCODER_SPEC_SHA256 = (
    "sha256:c89d05f5eaa510cbda58d8fb07517ae3084868cc3c8c85b4de2eab119511bbbb"
)


def schema_root_v1() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase1" / "v1"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase1" / "v1"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise Phase1ValidationError("cannot locate Phase 1 v1 schemas")


def load_schema_v1(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v1()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise Phase1ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise Phase1ValidationError(
            f"invalid JSON Schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v1(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v1(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    messages: list[str] = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{location}: {error.message}")
    raise Phase1ValidationError("; ".join(messages))


def schema_digests_v1(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v1()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise Phase1ValidationError(f"no Phase 1 schemas under {target}")
    return {name: canonical_sha256(load_schema_v1(name, target)) for name in names}


def validate_schema_lock_v1(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v1(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V1:
        expected_names = set(FROZEN_SCHEMA_DIGESTS_V1)
        observed_names = set(observed)
        changed = sorted(
            name
            for name in expected_names & observed_names
            if FROZEN_SCHEMA_DIGESTS_V1[name] != observed[name]
        )
        raise Phase1ValidationError(
            "Phase 1 schema lock mismatch; "
            f"missing={sorted(expected_names - observed_names)}, "
            f"extra={sorted(observed_names - expected_names)}, changed={changed}"
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


def validate_graph_record(record: dict[str, Any]) -> None:
    validate_v1(record, "graph.schema.json")
    kind = record["record_kind"]
    if kind == "node":
        if not math.isfinite(record["pagerank"]):
            raise Phase1ValidationError("node pagerank must be finite")
    elif kind == "statement":
        qualifier_keys = [canonical_sha256(item) for item in record["qualifiers"]]
        if duplicate := _duplicates(qualifier_keys):
            raise Phase1ValidationError(
                f"duplicate qualifier snaks: {sorted(duplicate)}"
            )
        reference_ids = [item["reference_id"] for item in record["references"]]
        if duplicate := _duplicates(reference_ids):
            raise Phase1ValidationError(
                f"duplicate statement reference IDs: {sorted(duplicate)}"
            )
    elif kind == "neighbour_candidate":
        if record["value_kind"] == "literal":
            if (
                record["direction"] != "outgoing"
                or record["neighbour_node_id"] is not None
            ):
                raise Phase1ValidationError(
                    "literal neighbours must be outgoing and have no neighbour_node_id"
                )
        elif record["neighbour_node_id"] is None:
            raise Phase1ValidationError("entity neighbours require neighbour_node_id")
        if (
            record["source_kind"] == "wikipedia"
            and record["value_kind"] != "entity_ref"
        ):
            raise Phase1ValidationError(
                "Wikipedia neighbours must be entity references"
            )
    elif kind == "neighbour_overflow":
        validate_graph_record(record["candidate"])


def validate_objective_example(example: dict[str, Any]) -> None:
    validate_v1(example, "objective-example.schema.json")
    candidates = example["candidates"]
    candidate_ids = [item["candidate_id"] for item in candidates]
    if duplicate := _duplicates(candidate_ids):
        raise Phase1ValidationError(
            f"duplicate objective candidate IDs: {sorted(duplicate)}"
        )
    targets = [item for item in candidates if item["is_target"]]
    if len(targets) != 1:
        raise Phase1ValidationError("objective must have exactly one target candidate")
    if targets[0]["candidate_id"] != example["target_candidate_id"]:
        raise Phase1ValidationError("target_candidate_id does not identify the target")
    if targets[0]["negative_basis"] is not None:
        raise Phase1ValidationError("target candidate cannot have a negative basis")
    for candidate in candidates:
        if candidate["is_target"]:
            continue
        if candidate["negative_basis"] is None:
            raise Phase1ValidationError("negative candidate lacks an explicit basis")
        if not candidate["evidence_refs"]:
            raise Phase1ValidationError("negative candidate lacks evidence")


def validate_encoder_spec(spec: dict[str, Any], *, require_frozen: bool = True) -> None:
    validate_v1(spec, "encoder.schema.json")
    if spec.get("record_kind") != "encoder_spec":
        raise Phase1ValidationError("expected encoder_spec")
    paths = [item["path"] for item in spec["assets"]]
    if duplicate := _duplicates(paths):
        raise Phase1ValidationError(
            f"duplicate encoder asset paths: {sorted(duplicate)}"
        )
    if set(paths) != ENCODER_ASSET_PATHS:
        raise Phase1ValidationError(
            "encoder runtime asset set mismatch; "
            f"missing={sorted(ENCODER_ASSET_PATHS - set(paths))}, "
            f"extra={sorted(set(paths) - ENCODER_ASSET_PATHS)}"
        )
    if require_frozen and canonical_sha256(spec) != FROZEN_ENCODER_SPEC_SHA256:
        raise Phase1ValidationError("encoder spec does not match the frozen digest")


def validate_encoder_verification(value: dict[str, Any]) -> None:
    validate_v1(value, "encoder.schema.json")
    if value.get("record_kind") != "encoder_verification":
        raise Phase1ValidationError("expected encoder_verification")
    paths = [item["path"] for item in value["assets"]]
    if len(paths) != len(set(paths)):
        raise Phase1ValidationError("encoder verification repeats an asset")


def validate_artifact_manifest(value: dict[str, Any]) -> None:
    validate_v1(value, "artifact.schema.json")
    if value["complete"] != (not value["errors"]):
        raise Phase1ValidationError("manifest complete flag disagrees with errors")
    kind = value["record_kind"]
    if kind == "sample_manifest":
        if value["selected_size"] > value["candidate_count"]:
            raise Phase1ValidationError("sample selects more records than candidates")
        if value["covered_communities"] > value["community_count"]:
            raise Phase1ValidationError("sample community coverage is impossible")
        if value["covered_strata"] > value["stratum_count"]:
            raise Phase1ValidationError("sample stratum coverage is impossible")
    elif kind == "neighbour_cap_manifest":
        if value["input_count"] != value["selected_count"] + value["overflow_count"]:
            raise Phase1ValidationError("neighbour cap accounting mismatch")
        if value["no_silent_drop"] is not True:
            raise Phase1ValidationError("neighbour cap manifest permits silent drops")
    elif kind == "objective_manifest":
        if set(value["family_counts"]) != OBJECTIVE_FAMILIES:
            raise Phase1ValidationError("objective manifest family set mismatch")
        if sum(value["family_counts"].values()) != value["example_count"]:
            raise Phase1ValidationError(
                "objective family counts do not sum to examples"
            )


def validate_gate_report(value: dict[str, Any]) -> None:
    validate_v1(value, "gate.schema.json")
