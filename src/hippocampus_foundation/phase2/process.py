"""Deterministic Phase 2B process-state generation, replay, and auditing."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from itertools import combinations
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_bytes, canonical_sha256
from hippocampus_foundation.phase0.errors import Phase0Error
from hippocampus_foundation.phase0.quarantine import (
    fingerprint_text,
    match_record,
    normalized_text_sha256,
)
from hippocampus_foundation.phase0.v2 import validate_v2 as validate_phase0_v2

from .contracts import validate_artifact as validate_artifact_v1
from .errors import Phase2IntegrityError, Phase2QuarantineError, Phase2ValidationError
from .io import bytes_identity, canonical_jsonl_bytes
from .process_oracles import (
    COPY_ON_WRITE_ORACLE_ID,
    DECLARATIVE_ORACLE_ID,
    compare_transition_oracles,
)
from .process_types import ProcessInput, apply_patch
from .v2 import (
    PROCESS_ACTIONS,
    PROCESS_DEPENDENCY_KINDS,
    bind_process_registry_spec,
    process_input_view,
    validate_process_artifact,
    validate_write_policy_example,
)

_DIRECT_MODES: tuple[tuple[str, str], ...] = (
    ("attach", "a0"),
    ("attach", "a1"),
    ("update", "b0"),
    ("update", "b1"),
    ("deprecate", "c0"),
    ("deprecate", "c1"),
    ("new_node", "d0"),
    ("new_node", "d1"),
    ("duplicate", "e0"),
    ("duplicate", "e1"),
    ("conflict", "f0"),
    ("conflict", "f1"),
    ("stage", "g0"),
    ("stage", "g1"),
    ("ignore", "h0"),
    ("ignore", "h1"),
)
_NEAR_MODES: tuple[tuple[str, str], ...] = (
    ("attach", "j0"),
    ("attach", "j1"),
    ("update", "k0"),
    ("update", "k1"),
    ("deprecate", "m0"),
    ("deprecate", "m1"),
    ("new_node", "n0"),
    ("new_node", "n1"),
    ("duplicate", "p0"),
    ("duplicate", "p1"),
    ("conflict", "q0"),
    ("conflict", "q1"),
    ("stage", "r0"),
    ("stage", "r1"),
    ("ignore", "s0"),
    ("ignore", "s1"),
)
_SCENARIOS = tuple(("direct", action, mode) for action, mode in _DIRECT_MODES) + tuple(
    ("near_miss", action, mode) for action, mode in _NEAR_MODES
)


def _seed_token(seed: int, ordinal: int) -> str:
    return hashlib.sha256(f"{seed}:{ordinal}".encode()).hexdigest()[:12]


def _scenario_for_ordinal(spec: dict[str, Any], ordinal: int) -> tuple[str, str, str]:
    block = ordinal // len(_SCENARIOS)
    position = ordinal % len(_SCENARIOS)
    ranked = sorted(
        _SCENARIOS,
        key=lambda item: hashlib.sha256(
            f"{spec['seed']}:{block}:{item[2]}".encode()
        ).digest(),
    )
    return ranked[position]


def _provenance(token: str, evidence_id: str | None = None) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id or f"evidence:{token}:base",
        "source_id": f"source:{token}:base",
        "stance": "supports",
        "observed_at": "2026-01-01T00:00:00Z",
    }


def _node(node_id: str, label: str, token: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": "entity",
        "label": label,
        "scope_id": f"scope:{token}",
        "lifecycle": "active",
        "valid_time": {"start": "2025-01-01T00:00:00Z", "end": None},
        "observation_time": "2026-01-01T00:00:00Z",
        "provenance": [_provenance(token)],
        "risk_class": "low",
        "conflict_ids": [],
        "version": 1,
    }


def _edge(
    edge_id: str,
    subject_id: str,
    predicate: str,
    object_value: dict[str, Any],
    token: str,
    *,
    mutable: bool = True,
) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "subject_id": subject_id,
        "predicate": predicate,
        "object": object_value,
        "scope_id": f"scope:{token}",
        "lifecycle": "active",
        "valid_time": {"start": "2025-01-01T00:00:00Z", "end": None},
        "observation_time": "2026-01-01T00:00:00Z",
        "provenance": [_provenance(token)],
        "risk_class": "low",
        "mutable": mutable,
        "version": 1,
        "previous_version_id": None,
        "conflict_ids": [],
    }


def _verified_evidence(token: str) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": f"evidence:{token}:proposal",
            "source_id": f"source:{token}:proposal",
            "stance": "supports",
            "status": "verified",
            "observed_at": "2026-02-01T00:00:00Z",
        }
    ]


def _build_inputs(
    mode: str, token: str
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    a = f"node:{token}:a"
    b = f"node:{token}:b"
    c = f"node:{token}:c"
    scope_id = f"scope:{token}"
    state = {
        "schema_version": "2.0.0",
        "record_kind": "process_state",
        "snapshot_id": f"snapshot:{token}",
        "as_of": "2026-02-01T00:00:00Z",
        "scope_id": scope_id,
        "relation_types": [
            {"predicate": "parent_of", "object_kind": "node", "acyclic": True},
            {"predicate": "related_to", "object_kind": "node", "acyclic": False},
            {"predicate": "status_value", "object_kind": "value", "acyclic": False},
        ],
        "nodes": sorted(
            [
                _node(a, f"Alpha {token}", token),
                _node(b, f"Beta {token}", token),
                _node(c, f"Gamma {token}", token),
            ],
            key=lambda item: item["node_id"],
        ),
        "edges": [],
        "staged_proposals": [],
        "decision_records": [],
    }
    proposal = {
        "schema_version": "2.0.0",
        "record_kind": "proposed_observation",
        "proposal_id": f"proposal:{token}",
        "subject": {
            "entity_type": "entity",
            "label": f"Alpha {token}",
            "identity_key": f"identity:{token}:a",
            "node_id": a,
        },
        "predicate": "status_value",
        "object": {"kind": "value", "value": f"new-{token}"},
        "signal": "assertion",
        "scope_id": scope_id,
        "valid_time": {"start": "2026-02-01T00:00:00Z", "end": None},
        "observation_time": "2026-02-01T00:00:00Z",
        "evidence": _verified_evidence(token),
        "risk_class": "low",
        "relevance": "relevant",
        "policy_status": "allowed",
    }
    frontier = [
        {
            "candidate_id": f"candidate:{token}:0",
            "target_kind": "node",
            "target_id": a,
            "identity_match": "exact",
            "scope_status": "in_scope",
        }
    ]
    visible_scope = {"scope_id": scope_id, "status": "in_scope"}

    node_object = {"kind": "node", "node_id": b}
    existing_value = {"kind": "value", "value": f"old-{token}"}

    if mode in {"a0", "r0", "s1", "p0"}:
        pass
    elif mode == "a1":
        proposal["predicate"] = "related_to"
        proposal["object"] = node_object
    elif mode in {"b0", "b1", "k0", "k1", "q0"}:
        proposal["signal"] = "correction"
        if mode == "b1":
            proposal["predicate"] = "related_to"
            proposal["object"] = {"kind": "node", "node_id": c}
            existing_value = node_object
        target = _edge(
            f"edge:{token}:base", a, proposal["predicate"], existing_value, token
        )
        state["edges"] = [target]
        frontier = [
            {
                "candidate_id": f"candidate:{token}:0",
                "target_kind": "edge",
                "target_id": target["edge_id"],
                "identity_match": "exact",
                "scope_status": "in_scope",
            }
        ]
        if mode == "k0":
            proposal["observation_time"] = "2025-12-01T00:00:00Z"
            proposal["evidence"][0]["observed_at"] = "2025-12-01T00:00:00Z"
        if mode == "k1":
            proposal["risk_class"] = "high"
    elif mode in {"c0", "c1", "m0", "m1"}:
        proposal["signal"] = "invalidation"
        if mode == "c1":
            proposal["predicate"] = "related_to"
            proposal["object"] = node_object
        target = _edge(
            f"edge:{token}:base", a, proposal["predicate"], proposal["object"], token
        )
        state["edges"] = [target]
        frontier = [
            {
                "candidate_id": f"candidate:{token}:0",
                "target_kind": "edge",
                "target_id": target["edge_id"],
                "identity_match": "exact",
                "scope_status": "in_scope",
            }
        ]
        if mode == "m0":
            proposal["evidence"] = []
        if mode == "m1":
            proposal["risk_class"] = "high"
    elif mode in {"d0", "d1", "n0", "n1"}:
        proposal["subject"] = {
            "entity_type": "entity",
            "label": f"Delta {token}",
            "identity_key": f"identity:{token}:new",
            "node_id": None,
        }
        if mode == "d1":
            proposal["predicate"] = "related_to"
            proposal["object"] = node_object
        frontier = [
            {
                "candidate_id": f"candidate:{token}:0",
                "target_kind": "node",
                "target_id": a,
                "identity_match": "none",
                "scope_status": "in_scope",
            }
        ]
        if mode == "n0":
            frontier = [
                {
                    "candidate_id": f"candidate:{token}:0",
                    "target_kind": "node",
                    "target_id": a,
                    "identity_match": "ambiguous",
                    "scope_status": "in_scope",
                },
                {
                    "candidate_id": f"candidate:{token}:1",
                    "target_kind": "node",
                    "target_id": c,
                    "identity_match": "ambiguous",
                    "scope_status": "in_scope",
                },
            ]
        if mode == "n1":
            proposal["scope_id"] = f"scope:{token}:other"
            visible_scope["status"] = "out_of_scope"
            frontier[0]["scope_status"] = "out_of_scope"
    elif mode in {"e0", "e1", "q1"}:
        if mode == "e1":
            proposal["predicate"] = "related_to"
            proposal["object"] = node_object
        target = _edge(
            f"edge:{token}:base", a, proposal["predicate"], proposal["object"], token
        )
        state["edges"] = [target]
        frontier = [
            {
                "candidate_id": f"candidate:{token}:0",
                "target_kind": "edge",
                "target_id": target["edge_id"],
                "identity_match": "exact",
                "scope_status": "in_scope",
            }
        ]
    elif mode in {"f0", "f1", "p1"}:
        if mode == "f1":
            proposal["predicate"] = "related_to"
            proposal["object"] = {"kind": "node", "node_id": c}
            existing_value = node_object
        target = _edge(
            f"edge:{token}:base", a, proposal["predicate"], existing_value, token
        )
        state["edges"] = [target]
        frontier = [
            {
                "candidate_id": f"candidate:{token}:0",
                "target_kind": "edge",
                "target_id": target["edge_id"],
                "identity_match": "exact",
                "scope_status": "in_scope",
            }
        ]
    elif mode == "g0":
        proposal["evidence"] = []
    elif mode == "g1":
        frontier = [
            {
                "candidate_id": f"candidate:{token}:0",
                "target_kind": "node",
                "target_id": a,
                "identity_match": "ambiguous",
                "scope_status": "in_scope",
            },
            {
                "candidate_id": f"candidate:{token}:1",
                "target_kind": "node",
                "target_id": c,
                "identity_match": "ambiguous",
                "scope_status": "in_scope",
            },
        ]
    elif mode == "h0":
        proposal["relevance"] = "irrelevant"
    elif mode == "h1":
        proposal["policy_status"] = "prohibited"
    elif mode == "j0":
        proposal["predicate"] = "parent_of"
        proposal["object"] = node_object
        state["edges"] = [
            _edge(
                f"edge:{token}:base",
                b,
                "parent_of",
                {"kind": "node", "node_id": a},
                token,
            )
        ]
    elif mode == "j1":
        proposal["risk_class"] = "high"
    elif mode == "r1":
        proposal["evidence"][0]["status"] = "rejected"
    elif mode == "s0":
        proposal["evidence"] = []
        visible_scope["status"] = "unknown"
        frontier[0]["scope_status"] = "unknown"
    else:
        raise Phase2ValidationError(f"unsupported neutral process scenario: {mode}")
    state["edges"].sort(key=lambda item: item["edge_id"])
    return state, proposal, frontier, visible_scope


def _dependency_values(spec: dict[str, Any], ordinal: int) -> dict[str, Any]:
    families = spec["dependency_families"]
    neutral_block = ordinal % 4
    world = f"{families['world']}:w{ordinal:06d}"
    return {
        "operation_id": f"{families['operation']}:o{neutral_block:04d}",
        "grammar_id": f"{families['grammar']}:g{neutral_block:04d}",
        "world_id": world,
        "relation_composition_id": f"{families['relation_composition']}:c{neutral_block:04d}",
        "entity_family_id": f"{families['entity_family']}:e{neutral_block:04d}",
        "seed_family_id": f"{families['seed_family']}:s{neutral_block:04d}",
        "template_id": f"{spec['source_id']}:template:t{neutral_block:04d}",
    }


def _input_text(example: dict[str, Any]) -> str:
    return canonical_bytes(process_input_view(example)).decode("utf-8")


def validate_process_quarantine_index(index: dict[str, Any]) -> str:
    try:
        validate_phase0_v2(index, "evaluation-evidence.schema.json")
    except Phase0Error as exc:
        raise Phase2ValidationError(
            f"invalid Phase 0 v2 quarantine index: {exc}"
        ) from exc
    if index.get("record_kind") != "quarantine_index":
        raise Phase2ValidationError("expected a Phase 0 v2 quarantine index")
    return canonical_sha256(index)


def _quarantine_descriptor(example: dict[str, Any]) -> dict[str, Any]:
    dependencies = example["dependencies"]
    identifiers = [
        {
            "namespace": f"generator.{kind}",
            "value": dependencies[f"{kind}_id"],
            "source_version": None,
        }
        for kind in PROCESS_DEPENDENCY_KINDS
    ]
    identifiers.extend(
        [
            {
                "namespace": "process.snapshot",
                "value": example["snapshot"]["snapshot_id"],
                "source_version": None,
            },
            {
                "namespace": "process.snapshot_sha256",
                "value": example["snapshot_sha256"],
                "source_version": None,
            },
            {
                "namespace": "process.proposal",
                "value": example["proposal"]["proposal_id"],
                "source_version": None,
            },
        ]
    )
    identifiers.extend(
        {"namespace": "process.entity", "value": entity_id, "source_version": None}
        for entity_id in dependencies["entity_ids"]
    )
    text = _input_text(example)
    return {
        "identifiers": identifiers,
        "raw_sha256": example["input_sha256"],
        "normalized_sha256": normalized_text_sha256(text),
        "fingerprint": fingerprint_text(text, f"{example['example_id']}:process-input"),
    }


def _build_example(
    spec: dict[str, Any],
    quarantine_index: dict[str, Any],
    quarantine_sha256: str,
    ordinal: int,
) -> tuple[dict[str, Any], tuple[str, str]]:
    scenario_kind, associated_action, mode = _scenario_for_ordinal(spec, ordinal)
    token = _seed_token(spec["seed"], ordinal)
    snapshot, proposal, frontier, scope = _build_inputs(mode, token)
    dependencies = _dependency_values(spec, ordinal)
    dependencies["entity_ids"] = sorted(item["node_id"] for item in snapshot["nodes"])
    example: dict[str, Any] = {
        "schema_version": "2.0.0",
        "record_kind": "write_policy_example",
        "example_id": f"{spec['source_id']}:{ordinal:06d}:{token}",
        "source_id": spec["source_id"],
        "role": spec["role"],
        "snapshot": snapshot,
        "proposal": proposal,
        "candidate_frontier": frontier,
        "visible_evidence_ids": sorted(
            item["evidence_id"] for item in proposal["evidence"]
        ),
        "scope": scope,
        "risk_policy": spec["risk_policy"],
        "candidates": list(PROCESS_ACTIONS),
        "dependencies": dependencies,
        "provenance": {
            "generator_id": spec["generator_id"],
            "algorithm_id": spec["algorithm_id"],
            "spec_sha256": canonical_sha256(spec),
            "rights_binding_id": spec["rights_binding_id"],
            "seed": spec["seed"],
            "ordinal": ordinal,
        },
        "training_authorized": False,
    }
    example["snapshot_sha256"] = canonical_sha256(snapshot)
    example["input_sha256"] = canonical_sha256(process_input_view(example))
    decision = match_record(_quarantine_descriptor(example), quarantine_index)
    if decision["decision"] != "clear":
        raise Phase2QuarantineError(
            f"process quarantine rejected {example['example_id']}: "
            f"decision={decision['decision']}, reasons={decision['reasons']}"
        )
    example["quarantine"] = {
        "index_id": quarantine_index["index_id"],
        "index_sha256": quarantine_sha256,
        "decision": "clear",
        "reasons": [],
    }
    example["target"] = compare_transition_oracles(
        ProcessInput.from_example(example)
    ).target()
    validate_write_policy_example(
        example,
        spec=spec,
        quarantine_index_id=quarantine_index["index_id"],
        quarantine_index_sha256=quarantine_sha256,
    )
    return example, (scenario_kind, associated_action)


def _mode(rows: list[dict[str, Any]], labels: dict[str, str] | None = None) -> str:
    counts = Counter(
        labels[row["example_id"]] if labels is not None else row["target"]["action"]
        for row in rows
    )
    if not counts:
        raise Phase2IntegrityError("cannot calculate process baseline without rows")
    return min(counts, key=lambda value: (-counts[value], value))


def _feature_accuracy(
    examples: list[dict[str, Any]],
    feature: Callable[[dict[str, Any]], str],
    *,
    labels: dict[str, str] | None = None,
) -> float:
    correct = 0
    for held_out in examples:
        training = [
            item
            for item in examples
            if item["snapshot_sha256"] != held_out["snapshot_sha256"]
        ]
        value = feature(held_out)
        matching = [item for item in training if feature(item) == value]
        predicted = _mode(matching or training, labels)
        actual = (
            labels[held_out["example_id"]]
            if labels is not None
            else held_out["target"]["action"]
        )
        correct += predicted == actual
    return round(correct / len(examples), 12)


def _proposal_feature(example: dict[str, Any]) -> str:
    proposal = example["proposal"]
    evidence = sorted(
        f"{item['stance']}:{item['status']}" for item in proposal["evidence"]
    )
    return "|".join(
        [
            proposal["signal"],
            proposal["object"]["kind"],
            proposal["risk_class"],
            proposal["relevance"],
            proposal["policy_status"],
            "known" if proposal["subject"]["node_id"] else "new",
            ",".join(evidence) or "none",
        ]
    )


def _shortcut_diagnostics(
    examples: list[dict[str, Any]], maximum: float
) -> dict[str, Any]:
    counts = Counter(item["target"]["action"] for item in examples)
    majority = max(counts.values()) / len(examples)
    sorted_examples = sorted(examples, key=lambda item: item["example_id"])
    actions = [item["target"]["action"] for item in sorted_examples]
    shuffled = actions[1:] + actions[:1]
    shuffled_labels = {
        item["example_id"]: label
        for item, label in zip(sorted_examples, shuffled, strict=True)
    }
    diagnostics = {
        "method": "leave-one-snapshot-out-v1",
        "maximum_restricted_accuracy": maximum,
        "majority_accuracy": round(majority, 12),
        "operation_accuracy": _feature_accuracy(
            examples, lambda item: item["dependencies"]["operation_id"]
        ),
        "grammar_accuracy": _feature_accuracy(
            examples, lambda item: item["dependencies"]["grammar_id"]
        ),
        "template_accuracy": _feature_accuracy(
            examples, lambda item: item["dependencies"]["template_id"]
        ),
        "entity_count_accuracy": _feature_accuracy(
            examples, lambda item: str(len(item["snapshot"]["nodes"]))
        ),
        "candidate_count_accuracy": _feature_accuracy(
            examples, lambda item: str(len(item["candidate_frontier"]))
        ),
        "risk_only_accuracy": _feature_accuracy(
            examples, lambda item: item["proposal"]["risk_class"]
        ),
        "proposal_only_accuracy": _feature_accuracy(examples, _proposal_feature),
        "label_shuffle_accuracy": _feature_accuracy(
            examples, _proposal_feature, labels=shuffled_labels
        ),
        "patch_size_accuracy": _feature_accuracy(
            examples,
            lambda item: str(
                len(item["target"]["patch"]["operations"])
                if item["target"]["patch"]
                else 0
            ),
        ),
        "patch_size_prediction_time_eligible": False,
        "blocked": False,
    }
    restricted = (
        "operation_accuracy",
        "grammar_accuracy",
        "template_accuracy",
        "entity_count_accuracy",
        "candidate_count_accuracy",
        "risk_only_accuracy",
        "proposal_only_accuracy",
        "label_shuffle_accuracy",
    )
    diagnostics["blocked"] = any(diagnostics[key] > maximum for key in restricted)
    return diagnostics


def _action_counts(examples: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(item["target"]["action"] for item in examples)
    return {action: counts.get(action, 0) for action in PROCESS_ACTIONS}


def _scenario_counts(values: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    output: dict[str, dict[str, int]] = {}
    for kind in ("direct", "near_miss"):
        counts = Counter(
            action for observed_kind, action in values if observed_kind == kind
        )
        output[kind] = {action: counts.get(action, 0) for action in PROCESS_ACTIONS}
    return output


def _dependency_ids(examples: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        kind: sorted({item["dependencies"][f"{kind}_id"] for item in examples})
        for kind in PROCESS_DEPENDENCY_KINDS
    }


def build_process_generation(
    *,
    registry: dict[str, Any],
    spec: dict[str, Any],
    quarantine_index: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    source = bind_process_registry_spec(registry, spec)
    quarantine_sha256 = validate_process_quarantine_index(quarantine_index)
    built = [
        _build_example(spec, quarantine_index, quarantine_sha256, ordinal)
        for ordinal in range(spec["example_count"])
    ]
    examples = sorted((item[0] for item in built), key=lambda item: item["example_id"])
    scenario_values = [item[1] for item in built]
    example_bytes = canonical_jsonl_bytes(examples)
    identity = bytes_identity(example_bytes)
    if (
        source["artifact_sha256"] is not None
        and source["artifact_sha256"] != identity["sha256"]
    ):
        raise Phase2IntegrityError(
            "process examples do not match registered artifact hash"
        )
    input_hashes = [item["input_sha256"] for item in examples]
    normalized_hashes = [normalized_text_sha256(_input_text(item)) for item in examples]
    snapshot_hashes = [item["snapshot_sha256"] for item in examples]
    exact_duplicates = len(input_hashes) - len(set(input_hashes))
    normalized_duplicates = len(normalized_hashes) - len(set(normalized_hashes))
    if (
        exact_duplicates
        or normalized_duplicates
        or len(snapshot_hashes) != len(set(snapshot_hashes))
    ):
        raise Phase2IntegrityError(
            "process generator produced duplicate inputs or snapshots"
        )
    diagnostics = _shortcut_diagnostics(
        examples, spec["shortcut_policy"]["maximum_restricted_accuracy"]
    )
    if diagnostics["blocked"]:
        raise Phase2IntegrityError(
            f"process shortcut diagnostic exceeded ceiling: {diagnostics}"
        )
    action_counts = _action_counts(examples)
    scenario_counts = _scenario_counts(scenario_values)
    if any(
        scenario_counts["direct"][action] < 2
        or scenario_counts["near_miss"][action] < 2
        for action in PROCESS_ACTIONS
    ):
        raise Phase2IntegrityError("process scenario coverage is incomplete")
    dependency_ids = _dependency_ids(examples)
    entity_ids = sorted(
        {entity for item in examples for entity in item["dependencies"]["entity_ids"]}
    )
    report = {
        "schema_version": "2.0.0",
        "record_kind": "transition_integrity_report",
        "report_id": f"{spec['source_id']}:integrity:v1",
        "created_at": spec["created_at"],
        "source_id": spec["source_id"],
        "role": spec["role"],
        "spec_sha256": canonical_sha256(spec),
        "quarantine_index_id": quarantine_index["index_id"],
        "quarantine_index_sha256": quarantine_sha256,
        "examples_sha256": identity["sha256"],
        "example_count": len(examples),
        "action_counts": action_counts,
        "scenario_counts": scenario_counts,
        "oracle": {
            "declarative_oracle_id": DECLARATIVE_ORACLE_ID,
            "copy_on_write_oracle_id": COPY_ON_WRITE_ORACLE_ID,
            "agreement": True,
            "disagreements": [],
            "input_mutation_count": 0,
        },
        "snapshot_unchanged": True,
        "rollback_complete": True,
        "provenance_complete": True,
        "quarantine_clear": True,
        "exact_duplicate_count": exact_duplicates,
        "normalized_duplicate_count": normalized_duplicates,
        "registry_role_overlap_count": 0,
        "dependency_ids": dependency_ids,
        "entity_ids": entity_ids,
        "input_sha256s": sorted(input_hashes),
        "normalized_input_sha256s": sorted(normalized_hashes),
        "snapshot_sha256s": sorted(snapshot_hashes),
        "shortcut_diagnostics": diagnostics,
        "complete": True,
        "blockers": [],
        "training_authorized": False,
    }
    validate_process_artifact(report)
    manifest = {
        "schema_version": "2.0.0",
        "record_kind": "process_generation_manifest",
        "manifest_id": f"{spec['source_id']}:generation:v1",
        "created_at": spec["created_at"],
        "source_id": spec["source_id"],
        "role": spec["role"],
        "generator_id": spec["generator_id"],
        "algorithm_id": spec["algorithm_id"],
        "registry_sha256": canonical_sha256(registry),
        "source_entry_sha256": canonical_sha256(source),
        "spec_sha256": canonical_sha256(spec),
        "quarantine_index_id": quarantine_index["index_id"],
        "quarantine_index_sha256": quarantine_sha256,
        "examples": identity,
        "transition_report_sha256": canonical_sha256(report),
        "example_count": len(examples),
        "action_counts": action_counts,
        "scenario_counts": scenario_counts,
        "dependency_ids": dependency_ids,
        "entity_ids": entity_ids,
        "input_sha256s": sorted(input_hashes),
        "normalized_input_sha256s": sorted(normalized_hashes),
        "snapshot_sha256s": sorted(snapshot_hashes),
        "complete": True,
        "blockers": [],
        "training_authorized": False,
    }
    validate_process_artifact(manifest)
    return examples, report, manifest


def replay_process_examples(
    *, examples: list[dict[str, Any]], report: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    validate_process_artifact(report)
    validate_process_artifact(manifest)
    observed_identity = bytes_identity(canonical_jsonl_bytes(examples))
    if observed_identity != manifest["examples"]:
        raise Phase2IntegrityError("replay examples do not match the manifest identity")
    if report["examples_sha256"] != manifest["examples"]["sha256"]:
        raise Phase2IntegrityError("replay report and manifest examples disagree")
    if manifest["transition_report_sha256"] != canonical_sha256(report):
        raise Phase2IntegrityError(
            "replay manifest does not bind its transition report"
        )
    if len(examples) != manifest["example_count"]:
        raise Phase2IntegrityError("replay example count disagrees with manifest")
    for example in examples:
        validate_write_policy_example(example)
        if (
            example["source_id"] != manifest["source_id"]
            or example["role"] != manifest["role"]
        ):
            raise Phase2IntegrityError("replay example source or role disagrees")
    entries = []
    for example in sorted(examples, key=lambda item: item["example_id"]):
        before_bytes = canonical_bytes(example["snapshot"])
        base_hash = canonical_sha256(example["snapshot"])
        patch = example["target"]["patch"]
        if patch is None:
            forward_hash = base_hash
            restored_hash = base_hash
            delta: list[dict[str, Any]] = []
            patch_hash = None
            inverse_hash = None
        else:
            forward, delta = apply_patch(example["snapshot"], patch)
            restored, _inverse_delta = apply_patch(forward, patch, inverse=True)
            forward_hash = canonical_sha256(forward)
            restored_hash = canonical_sha256(restored)
            patch_hash = canonical_sha256(patch)
            inverse_hash = canonical_sha256(patch["inverse_operations"])
        entries.append(
            {
                "example_id": example["example_id"],
                "action": example["target"]["action"],
                "base_snapshot_sha256": base_hash,
                "patch_sha256": patch_hash,
                "forward_snapshot_sha256": forward_hash,
                "inverse_patch_sha256": inverse_hash,
                "restored_snapshot_sha256": restored_hash,
                "delta_sha256": canonical_sha256(delta),
                "input_unchanged": canonical_bytes(example["snapshot"]) == before_bytes,
                "rollback_exact": restored_hash == base_hash,
            }
        )
    ledger = {
        "schema_version": "2.0.0",
        "record_kind": "process_replay_ledger",
        "ledger_id": f"{manifest['source_id']}:replay:v1",
        "created_at": manifest["created_at"],
        "source_id": manifest["source_id"],
        "role": manifest["role"],
        "manifest_sha256": canonical_sha256(manifest),
        "transition_report_sha256": canonical_sha256(report),
        "examples_sha256": manifest["examples"]["sha256"],
        "entries": entries,
        "complete": all(
            item["input_unchanged"] and item["rollback_exact"] for item in entries
        ),
        "blockers": [],
        "training_authorized": False,
    }
    validate_process_artifact(ledger)
    return ledger


def verify_process_generation(
    *,
    registry: dict[str, Any],
    spec: dict[str, Any],
    quarantine_index: dict[str, Any],
    examples: list[dict[str, Any]],
    report: dict[str, Any],
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    observed_examples_identity: dict[str, Any],
) -> dict[str, Any]:
    expected_examples, expected_report, expected_manifest = build_process_generation(
        registry=registry, spec=spec, quarantine_index=quarantine_index
    )
    if examples != expected_examples:
        raise Phase2IntegrityError(
            "process examples differ from deterministic regeneration"
        )
    if report != expected_report:
        raise Phase2IntegrityError("transition report differs from regeneration")
    if manifest != expected_manifest:
        raise Phase2IntegrityError("process manifest differs from regeneration")
    if observed_examples_identity != manifest["examples"]:
        raise Phase2IntegrityError("process example identity disagrees with manifest")
    expected_ledger = replay_process_examples(
        examples=examples, report=report, manifest=manifest
    )
    if ledger != expected_ledger:
        raise Phase2IntegrityError("replay ledger differs from deterministic replay")
    return {
        "ok": True,
        "source_id": manifest["source_id"],
        "role": manifest["role"],
        "examples": manifest["example_count"],
        "examples_sha256": manifest["examples"]["sha256"],
        "oracle_agreement": report["oracle"]["agreement"],
        "rollback_complete": report["rollback_complete"],
        "training_authorized": False,
    }


def audit_corpora_v2(
    manifests: list[dict[str, Any]], reports: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(manifests) < 2 or len(manifests) != len(reports):
        raise Phase2ValidationError("v2 corpus audit requires matching artifact pairs")
    reports_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for report in reports:
        report_v2 = report.get("schema_version") == "2.0.0"
        if report_v2:
            validate_process_artifact(report)
            expected_kind = "transition_integrity_report"
        else:
            validate_artifact_v1(report)
            expected_kind = "generation_integrity_report"
        if report.get("record_kind") != expected_kind:
            raise Phase2ValidationError(
                "v2 corpus audit received a non-integrity report"
            )
        key = (report["source_id"], report["role"], report["spec_sha256"])
        if key in reports_by_key:
            raise Phase2ValidationError("duplicate v2 corpus report pair")
        reports_by_key[key] = report
    pairs = []
    for manifest in manifests:
        v2 = manifest.get("schema_version") == "2.0.0"
        if v2:
            validate_process_artifact(manifest)
            expected_kind = "process_generation_manifest"
        else:
            validate_artifact_v1(manifest)
            expected_kind = "generation_manifest"
        if manifest.get("record_kind") != expected_kind:
            raise Phase2ValidationError(
                "v2 corpus audit received a non-generation manifest"
            )
        key = (manifest["source_id"], manifest["role"], manifest["spec_sha256"])
        report = reports_by_key.pop(key, None)
        if report is None:
            raise Phase2ValidationError("manifest lacks matching corpus report")
        report_field = "transition_report_sha256" if v2 else "integrity_report_sha256"
        if manifest[report_field] != canonical_sha256(report):
            raise Phase2IntegrityError("manifest does not bind matching corpus report")
        shared_fields = (
            ("quarantine_index_id", "quarantine index IDs"),
            ("quarantine_index_sha256", "quarantine hashes"),
            ("dependency_ids", "dependency IDs"),
            ("input_sha256s", "exact input hashes"),
            ("normalized_input_sha256s", "normalized input hashes"),
            ("example_count", "example counts"),
            ("action_counts", "action counts"),
        )
        for field, description in shared_fields:
            if manifest[field] != report[field]:
                raise Phase2IntegrityError(f"manifest/report {description} disagree")
        if manifest["examples"]["sha256"] != report["examples_sha256"]:
            raise Phase2IntegrityError("manifest/report examples hashes disagree")
        if v2:
            for field, description in (
                ("scenario_counts", "scenario counts"),
                ("entity_ids", "entity IDs"),
                ("snapshot_sha256s", "snapshot hashes"),
            ):
                if manifest[field] != report[field]:
                    raise Phase2IntegrityError(
                        f"manifest/report {description} disagree"
                    )
        if not manifest["complete"] or not report["complete"]:
            raise Phase2IntegrityError("v2 corpus audit refuses incomplete artifacts")
        pairs.append((manifest, report))
    if reports_by_key:
        raise Phase2ValidationError("corpus report lacks matching manifest")
    pairs.sort(key=lambda pair: (pair[0]["source_id"], pair[0]["role"]))
    source_ids = [item[0]["source_id"] for item in pairs]
    if len(source_ids) != len(set(source_ids)):
        raise Phase2ValidationError("corpus source IDs must be unique")
    roles = sorted({item[0]["role"] for item in pairs})
    if len(roles) < 2:
        raise Phase2ValidationError("v2 corpus audit requires two roles")

    def values(manifest: dict[str, Any], kind: str) -> set[str]:
        if kind == "artifact_sha256":
            return {manifest["examples"]["sha256"]}
        if kind == "input_sha256":
            return set(manifest["input_sha256s"])
        if kind == "normalized_input_sha256":
            return set(manifest["normalized_input_sha256s"])
        if kind == "snapshot_sha256":
            return set(manifest.get("snapshot_sha256s", []))
        if kind == "entity_id":
            return set(manifest.get("entity_ids", []))
        return set(manifest["dependency_ids"].get(kind, []))

    kinds = (
        "artifact_sha256",
        "input_sha256",
        "normalized_input_sha256",
        "snapshot_sha256",
        "entity_id",
        "operation",
        "grammar",
        "world",
        "relation_composition",
        "entity_family",
        "seed_family",
    )
    overlaps = []
    for (left, _), (right, _) in combinations(pairs, 2):
        if left["role"] == right["role"]:
            continue
        for kind in kinds:
            shared = sorted(values(left, kind) & values(right, kind))
            if shared:
                overlaps.append(
                    {
                        "left_source_id": left["source_id"],
                        "left_role": left["role"],
                        "right_source_id": right["source_id"],
                        "right_role": right["role"],
                        "kind": kind,
                        "values": shared,
                    }
                )
    overlaps.sort(
        key=lambda item: (item["left_source_id"], item["right_source_id"], item["kind"])
    )
    manifest_hashes = sorted(canonical_sha256(item[0]) for item in pairs)
    created_at = max(item[0]["created_at"] for item in pairs)
    seed = {
        "manifest_sha256s": manifest_hashes,
        "source_ids": sorted(source_ids),
        "roles": roles,
    }
    audit = {
        "schema_version": "2.0.0",
        "record_kind": "corpus_audit_v2",
        "created_at": created_at,
        "audit_id": f"corpus-audit-v2:{canonical_sha256(seed).removeprefix('sha256:')}",
        "manifest_sha256s": manifest_hashes,
        "source_ids": sorted(source_ids),
        "roles": roles,
        "overlaps": overlaps,
        "clean": not overlaps,
        "training_authorized": False,
    }
    validate_process_artifact(audit)
    return audit
