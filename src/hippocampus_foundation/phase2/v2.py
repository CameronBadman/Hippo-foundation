"""Additive Phase 2 v2 process-state contracts and semantic validation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.errors import (
    ValidationError as Phase0ValidationError,
)

from .errors import Phase2ValidationError

PROCESS_ACTIONS = (
    "attach",
    "update",
    "deprecate",
    "new_node",
    "duplicate",
    "conflict",
    "stage",
    "ignore",
)
PROCESS_DEPENDENCY_KINDS = (
    "operation",
    "grammar",
    "world",
    "relation_composition",
    "entity_family",
    "seed_family",
)
LABEL_TOKENS = frozenset(
    (*PROCESS_ACTIONS, "direct", "near", "miss", "positive", "negative", "case")
)

FROZEN_SCHEMA_DIGESTS_V2: dict[str, str] = {
    "artifact.schema.json": "sha256:a572ae9ea41a8c303553f9c5ade132aa69fdc27c5f51d3e790515b832789bf03",
    "generator-spec.schema.json": "sha256:50848c7f6b32118cb1dff92fa7d3b962a91877e08386a51d112be8108437b00c",
    "process-state.schema.json": "sha256:bf100aba4ba84d54263613dcd62ad604178c965f6badd9798e1f4fb2d9467510",
    "proposal.schema.json": "sha256:5dc7db8cc35935196356cab48f8af1bcb8fe39f0016149accb2e7ff63d5e7d23",
    "registry.schema.json": "sha256:9201a6b1fbe0c46af8f1e833eb0db16039699ba93578d353453c59c0c14dac2e",
    "write-policy-example.schema.json": "sha256:6ba1c8b5e07f8946ecb4781a088084b7a7f3573304634a7c5ab7d4db5ef06216",
}


def schema_root_v2() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase2" / "v2"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase2" / "v2"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise Phase2ValidationError("cannot locate Phase 2 v2 schemas")


def load_schema_v2(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v2()) / name
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


def _schema_registry(root: Path | None = None) -> Registry:
    target = root or schema_root_v2()
    resources = []
    for path in sorted(target.glob("*.schema.json")):
        schema = load_schema_v2(path.name, target)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate_v2(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v2(schema_name, root)
    validator = Draft202012Validator(
        schema, registry=_schema_registry(root), format_checker=FormatChecker()
    )
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        messages = []
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


def schema_digests_v2(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v2()
    return {
        path.name: canonical_sha256(load_schema_v2(path.name, target))
        for path in sorted(target.glob("*.schema.json"))
    }


def validate_schema_lock_v2(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v2(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V2:
        expected_names = set(FROZEN_SCHEMA_DIGESTS_V2)
        observed_names = set(observed)
        changed = sorted(
            name
            for name in expected_names & observed_names
            if FROZEN_SCHEMA_DIGESTS_V2[name] != observed[name]
        )
        raise Phase2ValidationError(
            "Phase 2 v2 schema lock mismatch; "
            f"missing={sorted(expected_names - observed_names)}, "
            f"extra={sorted(observed_names - expected_names)}, changed={changed}"
        )
    return observed


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _require_sorted_unique(values: list[str], field: str) -> None:
    if values != sorted(set(values)):
        raise Phase2ValidationError(f"{field} must be sorted and unique")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _validate_interval(value: dict[str, Any], location: str) -> None:
    start = value["start"]
    end = value["end"]
    if start is not None and end is not None and _parse_time(start) > _parse_time(end):
        raise Phase2ValidationError(f"{location} valid_time start exceeds end")


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[._:-]+", value.lower()) if token}


def _reject_label_identifier(value: str, location: str) -> None:
    shared = _tokens(value) & LABEL_TOKENS
    if shared:
        raise Phase2ValidationError(
            f"{location} contains target-bearing metadata token(s): {sorted(shared)}"
        )


def validate_process_state(state: dict[str, Any]) -> None:
    validate_v2(state, "process-state.schema.json")
    as_of = _parse_time(state["as_of"])
    relation_types = {item["predicate"]: item for item in state["relation_types"]}
    if len(relation_types) != len(state["relation_types"]):
        raise Phase2ValidationError("duplicate process-state relation type")
    if list(relation_types) != sorted(relation_types):
        raise Phase2ValidationError("process-state relation types must be sorted")
    scope_id = state["scope_id"]
    collections = (
        ("nodes", "node_id"),
        ("edges", "edge_id"),
        ("staged_proposals", "record_id"),
        ("decision_records", "record_id"),
    )
    all_ids: list[str] = []
    for collection, id_field in collections:
        identifiers = [item[id_field] for item in state[collection]]
        if identifiers != sorted(identifiers):
            raise Phase2ValidationError(f"process-state {collection} must be sorted")
        if duplicate := _duplicates(identifiers):
            raise Phase2ValidationError(
                f"duplicate process-state {collection} IDs: {sorted(duplicate)}"
            )
        all_ids.extend(identifiers)
    if duplicate := _duplicates(all_ids):
        raise Phase2ValidationError(
            f"process-state IDs must be globally unique: {sorted(duplicate)}"
        )

    nodes = {item["node_id"]: item for item in state["nodes"]}
    edges = {item["edge_id"]: item for item in state["edges"]}

    def validate_observation(record: dict[str, Any], location: str) -> None:
        observed = _parse_time(record["observation_time"])
        if observed > as_of:
            raise Phase2ValidationError(
                f"{location} uses an observation after the snapshot as_of"
            )
        provenance_ids = [item["evidence_id"] for item in record["provenance"]]
        _require_sorted_unique(provenance_ids, f"{location} provenance")
        if any(
            _parse_time(item["observed_at"]) > observed for item in record["provenance"]
        ):
            raise Phase2ValidationError(f"{location} uses future provenance")

    for node in nodes.values():
        if node["scope_id"] != scope_id:
            raise Phase2ValidationError("node crosses immutable snapshot scope")
        if node["version"] < 1:
            raise Phase2ValidationError("node version must be positive")
        _validate_interval(node["valid_time"], f"node {node['node_id']}")
        validate_observation(node, f"node {node['node_id']}")
        _require_sorted_unique(node["conflict_ids"], "node conflict IDs")
        if any(conflict not in nodes for conflict in node["conflict_ids"]):
            raise Phase2ValidationError("node conflict reference is dangling")
    previous_graph: dict[str, str] = {}
    for edge in edges.values():
        if edge["scope_id"] != scope_id:
            raise Phase2ValidationError("edge crosses immutable snapshot scope")
        if edge["subject_id"] not in nodes:
            raise Phase2ValidationError("edge subject is dangling")
        relation = relation_types.get(edge["predicate"])
        if relation is None:
            raise Phase2ValidationError("edge uses undeclared relation type")
        if edge["object"]["kind"] != relation["object_kind"]:
            raise Phase2ValidationError("edge object kind disagrees with relation type")
        if edge["object"]["kind"] == "node" and edge["object"]["node_id"] not in nodes:
            raise Phase2ValidationError("edge object is dangling")
        if edge["version"] < 1:
            raise Phase2ValidationError("edge version must be positive")
        _validate_interval(edge["valid_time"], f"edge {edge['edge_id']}")
        validate_observation(edge, f"edge {edge['edge_id']}")
        _require_sorted_unique(edge["conflict_ids"], "edge conflict IDs")
        previous = edge["previous_version_id"]
        if previous is not None:
            if previous not in edges or previous == edge["edge_id"]:
                raise Phase2ValidationError(
                    "edge previous-version reference is invalid"
                )
            if edges[previous]["version"] >= edge["version"]:
                raise Phase2ValidationError("edge version lineage is not increasing")
            previous_graph[edge["edge_id"]] = previous
        if any(conflict not in edges for conflict in edge["conflict_ids"]):
            raise Phase2ValidationError("edge conflict reference is dangling")

    for start in previous_graph:
        active: set[str] = set()
        current: str | None = start
        while current is not None:
            if current in active:
                raise Phase2ValidationError("edge version lineage contains a cycle")
            active.add(current)
            current = previous_graph.get(current)

    adjacency: dict[str, set[str]] = {}
    for edge in edges.values():
        relation = relation_types[edge["predicate"]]
        if (
            relation["acyclic"]
            and edge["object"]["kind"] == "node"
            and edge["lifecycle"] in {"candidate", "active"}
        ):
            adjacency.setdefault(edge["subject_id"], set()).add(
                edge["object"]["node_id"]
            )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise Phase2ValidationError("acyclic relation contains a cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in sorted(adjacency.get(node_id, set())):
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(nodes):
        visit(node_id)

    for staged in state["staged_proposals"]:
        if staged["scope_id"] != scope_id:
            raise Phase2ValidationError("staged proposal crosses snapshot scope")
        _require_sorted_unique(staged["reason_codes"], "staged reason codes")
        _require_sorted_unique(staged["evidence_ids"], "staged evidence IDs")
        if _parse_time(staged["created_at"]) > as_of:
            raise Phase2ValidationError("staged proposal is future information")
    known_related = set(nodes) | set(edges)
    for decision in state["decision_records"]:
        _require_sorted_unique(decision["related_ids"], "decision related IDs")
        _require_sorted_unique(decision["evidence_ids"], "decision evidence IDs")
        if not set(decision["related_ids"]) <= known_related:
            raise Phase2ValidationError("decision record has dangling related IDs")
        if _parse_time(decision["created_at"]) > as_of:
            raise Phase2ValidationError("decision record is future information")


def validate_proposal(proposal: dict[str, Any]) -> None:
    validate_v2(proposal, "proposal.schema.json")
    _validate_interval(proposal["valid_time"], "proposal")
    evidence_ids = [item["evidence_id"] for item in proposal["evidence"]]
    if duplicate := _duplicates(evidence_ids):
        raise Phase2ValidationError(
            f"duplicate proposal evidence IDs: {sorted(duplicate)}"
        )
    observed = _parse_time(proposal["observation_time"])
    if any(
        _parse_time(item["observed_at"]) > observed for item in proposal["evidence"]
    ):
        raise Phase2ValidationError("proposal uses future evidence")


def validate_training_registry_v2(registry: dict[str, Any]) -> None:
    validate_v2(registry, "registry.schema.json")
    source_ids = [item["source_id"] for item in registry["sources"]]
    if duplicate := _duplicates(source_ids):
        raise Phase2ValidationError(f"duplicate v2 source_id: {sorted(duplicate)}")
    process_roles: set[str] = set()
    for source in registry["sources"]:
        process = source["generator_id"] == "hf-process-state-v1"
        dependencies = source["dependency_families"]
        if process:
            if set(dependencies) != set(PROCESS_DEPENDENCY_KINDS):
                raise Phase2ValidationError(
                    "process source lacks exact v2 dependencies"
                )
            if source["dataset_family"] != "hf-process-state-v1":
                raise Phase2ValidationError("process source uses wrong dataset family")
            if source["role"] not in {"training", "development"}:
                raise Phase2ValidationError(
                    "process registry permits training/development only"
                )
            if source["role"] in process_roles:
                raise Phase2ValidationError("process registry repeats a role")
            process_roles.add(source["role"])
        if source["admission_state"] == "admitted":
            rights = source["rights"]
            if (
                source["artifact_sha256"] is None
                or source["blockers"]
                or rights["review_status"] != "approved"
                or rights["commercial_compatibility"] != "verified"
            ):
                raise Phase2ValidationError(
                    "admitted v2 source lacks complete rights evidence"
                )
        rights = source["rights"]
        if (
            rights["review_status"] == "rejected"
            or rights["commercial_compatibility"] == "incompatible"
        ) and source["admission_state"] != "retired":
            raise Phase2ValidationError("rejected v2 source must be retired")
    if process_roles != {"training", "development"}:
        raise Phase2ValidationError("v2 registry requires both process roles")

    process_sources = [
        item
        for item in registry["sources"]
        if item["generator_id"] == "hf-process-state-v1"
    ]
    left, right = sorted(process_sources, key=lambda item: item["role"])
    if (
        left["artifact_sha256"] is not None
        and left["artifact_sha256"] == right["artifact_sha256"]
    ):
        raise Phase2ValidationError("process artifact hash is reused across roles")
    for kind in PROCESS_DEPENDENCY_KINDS:
        if left["dependency_families"][kind] == right["dependency_families"][kind]:
            raise Phase2ValidationError(f"process {kind} family is reused across roles")


def validate_process_generator_spec(spec: dict[str, Any]) -> None:
    validate_v2(spec, "generator-spec.schema.json")
    families = list(spec["dependency_families"].values())
    if len(families) != len(set(families)):
        raise Phase2ValidationError("process dependency-family bases must be distinct")
    for kind, family in spec["dependency_families"].items():
        _reject_label_identifier(family, f"spec dependency family {kind}")


def bind_process_registry_spec(
    registry: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    validate_training_registry_v2(registry)
    validate_process_generator_spec(spec)
    matches = [
        item for item in registry["sources"] if item["source_id"] == spec["source_id"]
    ]
    if len(matches) != 1:
        raise Phase2ValidationError(
            "process generator source is not uniquely registered"
        )
    source = matches[0]
    if source["generator_id"] != "hf-process-state-v1":
        raise Phase2ValidationError("process spec selected a non-process source")
    if source["role"] != spec["role"]:
        raise Phase2ValidationError("process registry/spec roles disagree")
    if source["generator_spec_sha256"] != canonical_sha256(spec):
        raise Phase2ValidationError("process registry does not bind generator spec")
    if source["dependency_families"] != spec["dependency_families"]:
        raise Phase2ValidationError(
            "process registry/spec dependency families disagree"
        )
    if source["rights"]["licence_review_id"] != spec["rights_binding_id"]:
        raise Phase2ValidationError(
            "process spec rights binding disagrees with registry"
        )
    if source["admission_state"] == "retired":
        raise Phase2ValidationError("retired process source cannot generate candidates")
    return source


def process_input_view(example: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot": example["snapshot"],
        "proposal": example["proposal"],
        "candidate_frontier": example["candidate_frontier"],
        "visible_evidence_ids": example["visible_evidence_ids"],
        "scope": example["scope"],
        "risk_policy": example["risk_policy"],
    }


def validate_write_policy_example(
    example: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
    quarantine_index_id: str | None = None,
    quarantine_index_sha256: str | None = None,
) -> None:
    validate_v2(example, "write-policy-example.schema.json")
    validate_process_state(example["snapshot"])
    validate_proposal(example["proposal"])
    if _parse_time(example["proposal"]["observation_time"]) > _parse_time(
        example["snapshot"]["as_of"]
    ):
        raise Phase2ValidationError("proposal is future information for the snapshot")
    if tuple(example["candidates"]) != PROCESS_ACTIONS:
        raise Phase2ValidationError("write-policy candidates use the wrong order")
    if example["snapshot_sha256"] != canonical_sha256(example["snapshot"]):
        raise Phase2ValidationError("snapshot_sha256 does not bind immutable input")
    if example["input_sha256"] != canonical_sha256(process_input_view(example)):
        raise Phase2ValidationError("input_sha256 does not bind prediction-time view")
    if example["scope"]["scope_id"] != example["snapshot"]["scope_id"]:
        raise Phase2ValidationError("visible scope disagrees with snapshot scope")
    if (
        example["scope"]["scope_id"] != example["proposal"]["scope_id"]
        and example["scope"]["status"] != "out_of_scope"
    ):
        raise Phase2ValidationError("cross-scope proposal must be marked out_of_scope")
    expected_evidence = sorted(
        item["evidence_id"] for item in example["proposal"]["evidence"]
    )
    if example["visible_evidence_ids"] != expected_evidence:
        raise Phase2ValidationError(
            "visible evidence IDs must bind every proposal item"
        )
    candidate_ids = [item["candidate_id"] for item in example["candidate_frontier"]]
    _require_sorted_unique(candidate_ids, "candidate frontier IDs")
    nodes = {item["node_id"]: item for item in example["snapshot"]["nodes"]}
    edges = {item["edge_id"]: item for item in example["snapshot"]["edges"]}
    proposal_subject = example["proposal"]["subject"]["node_id"]
    proposal_predicate = example["proposal"]["predicate"]
    for candidate in example["candidate_frontier"]:
        collection = nodes if candidate["target_kind"] == "node" else edges
        target = collection.get(candidate["target_id"])
        if target is None:
            raise Phase2ValidationError("candidate frontier contains a dangling target")
        if candidate["identity_match"] != "exact":
            continue
        if proposal_subject is None:
            raise Phase2ValidationError("new subject cannot have an exact candidate")
        if candidate["target_kind"] == "node":
            if candidate["target_id"] != proposal_subject:
                raise Phase2ValidationError(
                    "exact node candidate has the wrong subject"
                )
        elif (
            target["subject_id"] != proposal_subject
            or target["predicate"] != proposal_predicate
        ):
            raise Phase2ValidationError("exact edge candidate has the wrong relation")
    expected_entities = sorted(nodes)
    if example["dependencies"]["entity_ids"] != expected_entities:
        raise Phase2ValidationError("dependency entity IDs do not bind snapshot nodes")
    if example["target"]["action"] == "ignore":
        if (
            example["target"]["patch"] is not None
            or example["target"]["rollback"]["kind"] != "identity"
        ):
            raise Phase2ValidationError("ignore must use a null identity patch")
    elif (
        example["target"]["patch"] is None
        or example["target"]["rollback"]["kind"] != "inverse_patch"
    ):
        raise Phase2ValidationError("non-ignore action requires a reversible patch")

    metadata_values = [example["example_id"], example["dependencies"]["template_id"]]
    metadata_values.extend(
        value
        for key, value in example["dependencies"].items()
        if key != "entity_ids" and isinstance(value, str)
    )
    for index, value in enumerate(metadata_values):
        _reject_label_identifier(value, f"example metadata {index}")

    if spec is not None:
        validate_process_generator_spec(spec)
        if example["source_id"] != spec["source_id"] or example["role"] != spec["role"]:
            raise Phase2ValidationError(
                "example source/role disagrees with process spec"
            )
        provenance = example["provenance"]
        expected = {
            "generator_id": spec["generator_id"],
            "algorithm_id": spec["algorithm_id"],
            "spec_sha256": canonical_sha256(spec),
            "rights_binding_id": spec["rights_binding_id"],
            "seed": spec["seed"],
        }
        for field, value in expected.items():
            if provenance[field] != value:
                raise Phase2ValidationError(f"example provenance {field} disagrees")
        if provenance["ordinal"] >= spec["example_count"]:
            raise Phase2ValidationError("example ordinal exceeds generator range")
        if len(example["candidate_frontier"]) > spec["bounds"]["max_candidates"]:
            raise Phase2ValidationError("example exceeds candidate bound")
        if len(example["snapshot"]["nodes"]) > spec["bounds"]["max_nodes"]:
            raise Phase2ValidationError("example exceeds process node bound")
        if len(example["snapshot"]["edges"]) > spec["bounds"]["max_edges"]:
            raise Phase2ValidationError("example exceeds process edge bound")
        patch = example["target"]["patch"]
        if (
            patch is not None
            and len(patch["operations"]) > spec["bounds"]["max_patch_operations"]
        ):
            raise Phase2ValidationError("example exceeds patch-operation bound")
        if example["risk_policy"] != spec["risk_policy"]:
            raise Phase2ValidationError("example risk policy disagrees with spec")
        for kind, family in spec["dependency_families"].items():
            if not example["dependencies"][f"{kind}_id"].startswith(f"{family}:"):
                raise Phase2ValidationError(f"example is outside {kind} allocation")
    if (
        quarantine_index_id is not None
        and example["quarantine"]["index_id"] != quarantine_index_id
    ):
        raise Phase2ValidationError("example binds another quarantine index")
    if (
        quarantine_index_sha256 is not None
        and example["quarantine"]["index_sha256"] != quarantine_index_sha256
    ):
        raise Phase2ValidationError("example binds another quarantine digest")

    from .process_oracles import compare_transition_oracles
    from .process_types import ProcessInput

    result = compare_transition_oracles(ProcessInput.from_example(example))
    if example["target"] != result.target():
        raise Phase2ValidationError(
            "write-policy target disagrees with transition oracles"
        )


def validate_process_artifact(value: dict[str, Any]) -> None:
    validate_v2(value, "artifact.schema.json")
    kind = value["record_kind"]
    if kind == "corpus_audit_v2":
        if value["clean"] != (not value["overlaps"]):
            raise Phase2ValidationError("v2 corpus clean flag disagrees with overlaps")
        _require_sorted_unique(value["manifest_sha256s"], "manifest_sha256s")
        _require_sorted_unique(value["source_ids"], "source_ids")
        _require_sorted_unique(value["roles"], "roles")
        return
    if value["complete"] != (not value["blockers"]):
        raise Phase2ValidationError(
            "process artifact complete flag disagrees with blockers"
        )
    if kind == "process_replay_ledger":
        ids = [item["example_id"] for item in value["entries"]]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise Phase2ValidationError("replay entries must be sorted and unique")
        expected = (
            all(
                item["input_unchanged"] and item["rollback_exact"]
                for item in value["entries"]
            )
            and not value["blockers"]
        )
        if value["complete"] != expected:
            raise Phase2ValidationError("replay completeness disagrees with entries")
        return
    if sum(value["action_counts"].values()) != value["example_count"]:
        raise Phase2ValidationError("process action counts do not sum")
    if sum(value["scenario_counts"]["direct"].values()) != value["example_count"] // 2:
        raise Phase2ValidationError("direct scenario counts do not sum")
    if (
        sum(value["scenario_counts"]["near_miss"].values())
        != value["example_count"] // 2
    ):
        raise Phase2ValidationError("near-miss scenario counts do not sum")
    for field in (
        "input_sha256s",
        "normalized_input_sha256s",
        "snapshot_sha256s",
        "entity_ids",
    ):
        _require_sorted_unique(value[field], field)
    for dependency, identifiers in value["dependency_ids"].items():
        _require_sorted_unique(identifiers, f"dependency_ids/{dependency}")
    if kind == "process_generation_manifest":
        if len(value["input_sha256s"]) != value["example_count"]:
            raise Phase2ValidationError("manifest contains duplicate process inputs")
        if len(value["snapshot_sha256s"]) != value["example_count"]:
            raise Phase2ValidationError("manifest requires one snapshot per example")
    elif kind == "transition_integrity_report":
        expected = (
            value["oracle"]["agreement"]
            and not value["oracle"]["disagreements"]
            and value["oracle"]["input_mutation_count"] == 0
            and value["snapshot_unchanged"]
            and value["rollback_complete"]
            and value["provenance_complete"]
            and value["quarantine_clear"]
            and value["exact_duplicate_count"] == 0
            and value["normalized_duplicate_count"] == 0
            and value["registry_role_overlap_count"] == 0
            and not value["shortcut_diagnostics"]["blocked"]
            and not value["blockers"]
        )
        if value["complete"] != expected:
            raise Phase2ValidationError("transition report completeness disagrees")
    else:
        raise Phase2ValidationError(f"unsupported process artifact: {kind}")
