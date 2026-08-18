"""Frozen Phase 2 v1 contracts and fail-closed semantic validation."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.errors import (
    ValidationError as Phase0ValidationError,
)

from .errors import Phase2ValidationError
from .oracles import atom_key, compare_oracles, render_evidence

ACTIONS = (
    "return",
    "abstain_unknown",
    "abstain_conflict",
    "continue",
    "stop_irrelevant",
)
CASE_KINDS = (
    "positive",
    "negative",
    "unknown",
    "conflict",
    "continue",
    "stop_irrelevant",
    "cycle_reachable",
    "cycle_unreachable",
)
DEPENDENCY_KINDS = (
    "grammar",
    "world",
    "relation_composition",
    "seed_family",
)


FROZEN_SCHEMA_DIGESTS_V1: dict[str, str] = {
    "artifact.schema.json": "sha256:bf975aafded324595f88f4d4b5187488ac758d4ea40d0bf8b04612e9ae91b640",
    "generator-spec.schema.json": "sha256:03152e022dcddc69683937d0bd593768a109b99c7492c19135f2489bc0bc1e2c",
    "policy-example.schema.json": "sha256:d4372b6de0351a762be29464fb12a14943f5e1326b10f6174709160f3481c3a3",
    "registry.schema.json": "sha256:61b69e2340d3ebc55828abb0fa3864709b4941dbf24d220d471fc855e9867e75",
}


def schema_root_v1() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase2" / "v1"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase2" / "v1"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise Phase2ValidationError("cannot locate Phase 2 v1 schemas")


def load_schema_v1(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v1()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise Phase2ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise Phase2ValidationError(
            f"invalid JSON Schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v1(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v1(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        messages: list[str] = []
        for error in errors:
            location = "/".join(str(part) for part in error.absolute_path) or "$"
            messages.append(f"{location}: {error.message}")
        raise Phase2ValidationError("; ".join(messages))
    try:
        canonical_sha256(instance)
    except Phase0ValidationError as exc:
        raise Phase2ValidationError(
            f"instance is not canonical-JSON compatible: {exc}"
        ) from exc


def schema_digests_v1(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v1()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise Phase2ValidationError(f"no Phase 2 v1 schemas under {target}")
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
        raise Phase2ValidationError(
            "Phase 2 schema lock mismatch; "
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


def _require_sorted_unique(values: list[str], field: str) -> None:
    if values != sorted(set(values)):
        raise Phase2ValidationError(f"{field} must be sorted and unique")


def validate_training_registry(registry: dict[str, Any]) -> None:
    validate_v1(registry, "registry.schema.json")
    sources = registry["sources"]
    source_ids = [item["source_id"] for item in sources]
    if duplicate := _duplicates(source_ids):
        raise Phase2ValidationError(f"duplicate source_id: {sorted(duplicate)}")

    role_by_dataset: set[tuple[str, str]] = set()
    for source in sources:
        key = (source["dataset_family"], source["role"])
        if key in role_by_dataset:
            raise Phase2ValidationError(
                f"dataset family repeats role: {source['dataset_family']} {source['role']}"
            )
        role_by_dataset.add(key)
        rights = source["rights"]
        if source["admission_state"] == "admitted":
            if source["artifact_sha256"] is None or source["blockers"]:
                raise Phase2ValidationError(
                    f"admitted source lacks a bound artifact or has blockers: {source['source_id']}"
                )
            if (
                rights["review_status"] != "approved"
                or rights["commercial_compatibility"] != "verified"
            ):
                raise Phase2ValidationError(
                    f"admitted source lacks verified rights: {source['source_id']}"
                )
        if (
            rights["review_status"] == "rejected"
            or rights["commercial_compatibility"] == "incompatible"
        ) and source["admission_state"] != "retired":
            raise Phase2ValidationError(
                f"rejected or incompatible source must be retired: {source['source_id']}"
            )

    for left_index, left in enumerate(sources):
        for right in sources[left_index + 1 :]:
            if left["role"] == right["role"]:
                continue
            if (
                left["artifact_sha256"] is not None
                and left["artifact_sha256"] == right["artifact_sha256"]
            ):
                raise Phase2ValidationError(
                    "artifact hash is reused across roles: "
                    f"{left['source_id']} and {right['source_id']}"
                )
            for kind in DEPENDENCY_KINDS:
                if (
                    left["dependency_families"][kind]
                    == right["dependency_families"][kind]
                ):
                    raise Phase2ValidationError(
                        f"{kind} family is reused across roles: "
                        f"{left['source_id']} and {right['source_id']}"
                    )


def validate_generator_spec(spec: dict[str, Any]) -> None:
    validate_v1(spec, "generator-spec.schema.json")
    families = list(spec["dependency_families"].values())
    if len(families) != len(set(families)):
        raise Phase2ValidationError(
            "generator dependency-family identifiers must be distinct by kind"
        )
    if spec["bounds"]["max_rule_firings"] < spec["bounds"]["max_proof_depth"]:
        raise Phase2ValidationError(
            "max_rule_firings must not be smaller than max_proof_depth"
        )


def bind_registry_spec(
    registry: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    validate_training_registry(registry)
    validate_generator_spec(spec)
    matches = [
        source
        for source in registry["sources"]
        if source["source_id"] == spec["source_id"]
    ]
    if len(matches) != 1:
        raise Phase2ValidationError(
            f"generator source is not uniquely registered: {spec['source_id']}"
        )
    source = matches[0]
    if source["role"] != spec["role"]:
        raise Phase2ValidationError("registry and generator spec roles disagree")
    if source["generator_id"] != spec["generator_id"]:
        raise Phase2ValidationError("registry and generator IDs disagree")
    if source["generator_spec_sha256"] != canonical_sha256(spec):
        raise Phase2ValidationError("registry does not bind the generator spec digest")
    if source["dependency_families"] != spec["dependency_families"]:
        raise Phase2ValidationError(
            "registry and generator dependency families disagree"
        )
    if source["rights"]["licence_review_id"] != spec["rights_binding_id"]:
        raise Phase2ValidationError(
            "generator spec does not bind the registered rights review"
        )
    if source["admission_state"] == "retired":
        raise Phase2ValidationError("retired source cannot generate candidates")
    if (
        source["rights"]["review_status"] == "rejected"
        or source["rights"]["commercial_compatibility"] == "incompatible"
    ):
        raise Phase2ValidationError("rights status forbids candidate generation")
    return source


def policy_input_view(example: dict[str, Any]) -> dict[str, Any]:
    return {
        "prediction_time": example["prediction_time"],
        "query": example["query"],
        "candidates": example["candidates"],
        "risk": example["risk"],
    }


def _validate_atom_types(
    atom: dict[str, Any],
    *,
    entity_types: dict[str, str],
    predicates: dict[str, tuple[str, ...]],
    location: str,
) -> None:
    predicate_id = atom["predicate"]
    if predicate_id not in predicates:
        raise Phase2ValidationError(
            f"{location} uses undeclared predicate: {predicate_id}"
        )
    arguments = atom["arguments"]
    expected_types = predicates[predicate_id]
    if len(arguments) != len(expected_types):
        raise Phase2ValidationError(f"{location} has wrong predicate arity")
    for argument, expected_type in zip(arguments, expected_types, strict=True):
        if entity_types.get(argument) != expected_type:
            raise Phase2ValidationError(
                f"{location} argument {argument!r} is missing or has the wrong type"
            )


def _validate_world(example: dict[str, Any]) -> None:
    world = example["prediction_time"]
    entity_ids = [item["entity_id"] for item in world["entities"]]
    if duplicate := _duplicates(entity_ids):
        raise Phase2ValidationError(f"duplicate entity IDs: {sorted(duplicate)}")
    predicate_ids = [item["predicate_id"] for item in world["predicates"]]
    if duplicate := _duplicates(predicate_ids):
        raise Phase2ValidationError(f"duplicate predicate IDs: {sorted(duplicate)}")
    entity_types = {item["entity_id"]: item["type_id"] for item in world["entities"]}
    predicates = {
        item["predicate_id"]: tuple(item["argument_types"])
        for item in world["predicates"]
    }

    proof_ids: list[str] = []
    fact_atoms: list[tuple[str, str, tuple[str, ...]]] = []
    for fact in world["facts"]:
        proof_ids.append(fact["fact_id"])
        fact_atoms.append(atom_key(fact["atom"]))
        _validate_atom_types(
            fact["atom"],
            entity_types=entity_types,
            predicates=predicates,
            location=f"fact {fact['fact_id']}",
        )
    if duplicate := _duplicates([repr(item) for item in fact_atoms]):
        raise Phase2ValidationError(f"duplicate signed facts: {sorted(duplicate)}")
    for rule in world["rules"]:
        proof_ids.append(rule["rule_id"])
        antecedent_keys = [atom_key(item) for item in rule["antecedents"]]
        if len(antecedent_keys) != len(set(antecedent_keys)):
            raise Phase2ValidationError(
                f"rule repeats an antecedent: {rule['rule_id']}"
            )
        for index, atom in enumerate(rule["antecedents"]):
            _validate_atom_types(
                atom,
                entity_types=entity_types,
                predicates=predicates,
                location=f"rule {rule['rule_id']} antecedent {index}",
            )
        _validate_atom_types(
            rule["consequent"],
            entity_types=entity_types,
            predicates=predicates,
            location=f"rule {rule['rule_id']} consequent",
        )
    frontier_ids: list[str] = []
    for candidate in world["frontier"]:
        frontier_ids.append(candidate["candidate_id"])
        proof_ids.append(candidate["candidate_id"])
        _validate_atom_types(
            candidate["observation"],
            entity_types=entity_types,
            predicates=predicates,
            location=f"frontier {candidate['candidate_id']}",
        )
    if duplicate := _duplicates(proof_ids):
        raise Phase2ValidationError(
            f"fact, rule, and frontier proof IDs must be globally unique: {sorted(duplicate)}"
        )
    if duplicate := _duplicates(frontier_ids):
        raise Phase2ValidationError(f"duplicate frontier IDs: {sorted(duplicate)}")
    _validate_atom_types(
        example["query"],
        entity_types=entity_types,
        predicates=predicates,
        location="query",
    )
    if example["query"]["polarity"] != "positive":
        raise Phase2ValidationError("Phase 2A queries must use positive polarity")


def validate_policy_example(
    example: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
    quarantine_index_id: str | None = None,
    quarantine_index_sha256: str | None = None,
) -> None:
    validate_v1(example, "policy-example.schema.json")
    _validate_world(example)
    if tuple(example["candidates"]) != ACTIONS:
        raise Phase2ValidationError(
            "policy candidates must use the frozen action order"
        )
    if example["input_sha256"] != canonical_sha256(policy_input_view(example)):
        raise Phase2ValidationError(
            "policy input_sha256 does not bind prediction-time input"
        )

    if spec is None:
        max_depth = 64
        max_rule_firings = 4096
    else:
        validate_generator_spec(spec)
        max_depth = spec["bounds"]["max_proof_depth"]
        max_rule_firings = spec["bounds"]["max_rule_firings"]
        expected = {
            "source_id": spec["source_id"],
            "role": spec["role"],
        }
        for field, value in expected.items():
            if example[field] != value:
                raise Phase2ValidationError(
                    f"example {field} disagrees with generator spec"
                )
        provenance = example["provenance"]
        if provenance["generator_id"] != spec["generator_id"]:
            raise Phase2ValidationError(
                "example generator provenance disagrees with spec"
            )
        if provenance["algorithm_id"] != spec["algorithm_id"]:
            raise Phase2ValidationError(
                "example algorithm provenance disagrees with spec"
            )
        if provenance["spec_sha256"] != canonical_sha256(spec):
            raise Phase2ValidationError(
                "example provenance does not bind generator spec"
            )
        if provenance["seed"] != spec["seed"]:
            raise Phase2ValidationError("example seed disagrees with generator spec")
        if example["risk"] != spec["risk_policy"]:
            raise Phase2ValidationError(
                "example risk policy disagrees with generator spec"
            )
        for kind, family in spec["dependency_families"].items():
            example_key = f"{kind}_id"
            if not example["dependencies"][example_key].startswith(f"{family}:"):
                raise Phase2ValidationError(
                    f"example {example_key} is outside its allocated family"
                )
    if (
        quarantine_index_id is not None
        and example["quarantine"]["index_id"] != quarantine_index_id
    ):
        raise Phase2ValidationError("example names a different quarantine index")
    if (
        quarantine_index_sha256 is not None
        and example["quarantine"]["index_sha256"] != quarantine_index_sha256
    ):
        raise Phase2ValidationError("example binds a different quarantine index")
    if spec is not None:
        if (
            len(example["prediction_time"]["frontier"])
            > spec["bounds"]["max_frontier_candidates"]
        ):
            raise Phase2ValidationError("example exceeds max_frontier_candidates")
        if example["provenance"]["ordinal"] >= spec["example_count"]:
            raise Phase2ValidationError(
                "example ordinal is outside the generator range"
            )

    forward, _proof_tree = compare_oracles(
        example["prediction_time"],
        example["query"],
        max_rule_firings=max_rule_firings,
        max_depth=max_depth,
    )
    expected_target = {"action": forward.action, "payload": forward.payload}
    if example["target"] != expected_target:
        raise Phase2ValidationError("policy target disagrees with independent oracles")
    if example["evidence"] != render_evidence(forward):
        raise Phase2ValidationError(
            "policy proof evidence disagrees with forward closure"
        )


def validate_artifact(value: dict[str, Any]) -> None:
    validate_v1(value, "artifact.schema.json")
    kind = value["record_kind"]
    if kind == "corpus_audit":
        if value["clean"] != (not value["overlaps"]):
            raise Phase2ValidationError(
                "corpus audit clean flag disagrees with overlaps"
            )
        _require_sorted_unique(value["manifest_sha256s"], "manifest_sha256s")
        _require_sorted_unique(value["source_ids"], "source_ids")
        _require_sorted_unique(value["roles"], "roles")
        return

    if value["complete"] != (not value["blockers"]):
        raise Phase2ValidationError("artifact complete flag disagrees with blockers")
    if sum(value["action_counts"].values()) != value["example_count"]:
        raise Phase2ValidationError("action counts do not sum to example_count")
    if sum(value["case_counts"].values()) != value["example_count"]:
        raise Phase2ValidationError("case counts do not sum to example_count")
    for dependency_kind, identifiers in value["dependency_ids"].items():
        _require_sorted_unique(identifiers, f"dependency_ids/{dependency_kind}")
    _require_sorted_unique(value["input_sha256s"], "input_sha256s")
    _require_sorted_unique(
        value["normalized_input_sha256s"], "normalized_input_sha256s"
    )

    if kind == "generation_manifest":
        if len(value["input_sha256s"]) != value["example_count"]:
            raise Phase2ValidationError("manifest contains exact duplicate inputs")
        if len(value["normalized_input_sha256s"]) != value["example_count"]:
            raise Phase2ValidationError("manifest contains normalized duplicate inputs")
        if value["complete"] and value["examples"]["bytes"] == 0:
            raise Phase2ValidationError(
                "complete manifest binds an empty examples file"
            )
        if len(value["dependency_ids"]["world"]) != value["example_count"]:
            raise Phase2ValidationError(
                "manifest must bind one unique world per example"
            )
    elif kind == "generation_integrity_report":
        if (
            len(value["input_sha256s"]) + value["exact_duplicate_count"]
            != value["example_count"]
        ):
            raise Phase2ValidationError("exact duplicate accounting mismatch")
        if (
            len(value["normalized_input_sha256s"]) + value["normalized_duplicate_count"]
            != value["example_count"]
        ):
            raise Phase2ValidationError("normalized duplicate accounting mismatch")
        if len(value["dependency_ids"]["world"]) != value["example_count"]:
            raise Phase2ValidationError("report must bind one unique world per example")
        expected_complete = (
            value["oracle"]["agreement"]
            and not value["oracle"]["disagreements"]
            and value["provenance_complete"]
            and value["quarantine_clear"]
            and value["exact_duplicate_count"] == 0
            and value["normalized_duplicate_count"] == 0
            and value["registry_role_overlap_count"] == 0
            and not value["blockers"]
        )
        if value["complete"] != expected_complete:
            raise Phase2ValidationError(
                "integrity report completeness disagrees with blocking checks"
            )
    else:
        raise Phase2ValidationError(f"unsupported Phase 2 artifact kind: {kind}")
