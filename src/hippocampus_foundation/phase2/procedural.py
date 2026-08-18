"""Deterministic first-party open-world policy-example generation."""

from __future__ import annotations

import hashlib
from collections import Counter
from copy import deepcopy
from itertools import combinations
from typing import Any

from hippocampus_foundation.phase0.canonical import (
    canonical_bytes,
    canonical_sha256,
)
from hippocampus_foundation.phase0.errors import Phase0Error
from hippocampus_foundation.phase0.quarantine import (
    fingerprint_text,
    match_record,
    normalized_text_sha256,
)
from hippocampus_foundation.phase0.v2 import validate_v2 as validate_phase0_v2

from .contracts import (
    ACTIONS,
    CASE_KINDS,
    DEPENDENCY_KINDS,
    bind_registry_spec,
    policy_input_view,
    validate_artifact,
    validate_policy_example,
)
from .errors import (
    Phase2IntegrityError,
    Phase2QuarantineError,
    Phase2ValidationError,
)
from .io import bytes_identity, canonical_jsonl_bytes
from .oracles import compare_oracles, render_evidence

FORWARD_ORACLE_ID = "agenda-signed-closure-v1"
PROOF_TREE_ORACLE_ID = "bounded-proof-tree-v1"


def _atom(predicate: str, entity_id: str, polarity: str = "positive") -> dict[str, Any]:
    return {
        "predicate": predicate,
        "arguments": [entity_id],
        "polarity": polarity,
    }


def _fact(fact_id: str, atom: dict[str, Any]) -> dict[str, Any]:
    return {"fact_id": fact_id, "atom": atom}


def _rule(
    rule_id: str,
    antecedents: list[dict[str, Any]],
    consequent: dict[str, Any],
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "antecedents": antecedents,
        "consequent": consequent,
    }


def _seed_token(seed: int, ordinal: int) -> str:
    material = canonical_bytes({"seed": seed, "ordinal": ordinal})
    return hashlib.sha256(material).hexdigest()[:16]


def _case_for_ordinal(spec: dict[str, Any], ordinal: int) -> str:
    block = ordinal // len(CASE_KINDS)
    position = ordinal % len(CASE_KINDS)
    ordered = sorted(
        CASE_KINDS,
        key=lambda case_kind: hashlib.sha256(
            canonical_bytes(
                {
                    "seed": spec["seed"],
                    "block": block,
                    "case_kind": case_kind,
                }
            )
        ).digest(),
    )
    return ordered[position]


def _world_for_case(
    case_kind: str, *, entity_id: str, proof_prefix: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    ready = _atom("ready", entity_id)
    not_ready = _atom("ready", entity_id, "negative")
    marker = _atom("marker", entity_id)
    trigger = _atom("trigger", entity_id)
    mid = _atom("mid", entity_id)
    loop_a = _atom("loop_a", entity_id)
    loop_b = _atom("loop_b", entity_id)
    facts: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    frontier: list[dict[str, Any]] = []
    query = ready
    path_length = "zero"

    if case_kind == "positive":
        facts = [_fact(f"{proof_prefix}:f0", ready)]
    elif case_kind == "negative":
        facts = [_fact(f"{proof_prefix}:f0", not_ready)]
    elif case_kind == "unknown":
        facts = [_fact(f"{proof_prefix}:f0", marker)]
    elif case_kind == "conflict":
        facts = [
            _fact(f"{proof_prefix}:f0", ready),
            _fact(f"{proof_prefix}:f1", not_ready),
        ]
    elif case_kind == "continue":
        facts = [_fact(f"{proof_prefix}:f0", marker)]
        rules = [_rule(f"{proof_prefix}:r0", [trigger], ready)]
        frontier = [
            {
                "candidate_id": f"{proof_prefix}:frontier0",
                "observation": trigger,
                "cost": 1,
            }
        ]
        path_length = "one"
    elif case_kind == "stop_irrelevant":
        facts = [_fact(f"{proof_prefix}:f0", marker)]
        frontier = [
            {
                "candidate_id": f"{proof_prefix}:frontier0",
                "observation": trigger,
                "cost": 1,
            }
        ]
        path_length = "one"
    elif case_kind == "cycle_reachable":
        facts = [_fact(f"{proof_prefix}:f0", marker)]
        rules = [
            _rule(f"{proof_prefix}:r0", [marker], mid),
            _rule(f"{proof_prefix}:r1", [mid], ready),
            _rule(f"{proof_prefix}:r2", [ready], mid),
        ]
        path_length = "two"
    elif case_kind == "cycle_unreachable":
        query = loop_a
        rules = [
            _rule(f"{proof_prefix}:r0", [loop_a], loop_b),
            _rule(f"{proof_prefix}:r1", [loop_b], loop_a),
        ]
        path_length = "cyclic"
    else:
        raise Phase2ValidationError(f"unsupported procedural case: {case_kind}")

    world = {
        "entities": [{"entity_id": entity_id, "type_id": "item"}],
        "predicates": [
            {"predicate_id": predicate, "argument_types": ["item"]}
            for predicate in ("loop_a", "loop_b", "marker", "mid", "ready", "trigger")
        ],
        "facts": facts,
        "rules": rules,
        "frontier": frontier,
    }
    return world, query, path_length


def _dependency_values(spec: dict[str, Any], ordinal: int) -> dict[str, str]:
    block = ordinal // len(CASE_KINDS)
    families = spec["dependency_families"]
    return {
        "grammar_id": f"{families['grammar']}:g{block:04d}",
        "world_id": f"{families['world']}:w{ordinal:06d}",
        "relation_composition_id": (f"{families['relation_composition']}:c{block:04d}"),
        "seed_family_id": f"{families['seed_family']}:s{block:04d}",
    }


def _input_text(example: dict[str, Any]) -> str:
    return canonical_bytes(policy_input_view(example)).decode("utf-8")


def _quarantine_descriptor(example: dict[str, Any]) -> dict[str, Any]:
    dependencies = example["dependencies"]
    identifiers = [
        {
            "namespace": f"generator.{kind}",
            "value": dependencies[f"{kind}_id"],
            "source_version": None,
        }
        for kind in DEPENDENCY_KINDS
    ]
    text = _input_text(example)
    return {
        "identifiers": identifiers,
        "raw_sha256": example["input_sha256"],
        "normalized_sha256": normalized_text_sha256(text),
        "fingerprint": fingerprint_text(
            text, f"{example['example_id']}:prediction-input"
        ),
    }


def validate_quarantine_index(index: dict[str, Any]) -> str:
    try:
        validate_phase0_v2(index, "evaluation-evidence.schema.json")
    except Phase0Error as exc:
        raise Phase2ValidationError(
            f"invalid Phase 0 v2 quarantine index: {exc}"
        ) from exc
    if index.get("record_kind") != "quarantine_index":
        raise Phase2ValidationError("expected a Phase 0 v2 quarantine index")
    return canonical_sha256(index)


def _build_example(
    spec: dict[str, Any],
    quarantine_index: dict[str, Any],
    quarantine_sha256: str,
    ordinal: int,
) -> dict[str, Any]:
    case_kind = _case_for_ordinal(spec, ordinal)
    token = _seed_token(spec["seed"], ordinal)
    example_id = f"{spec['source_id']}:{ordinal:06d}:{token}"
    entity_id = f"item_{token}"
    proof_prefix = f"step:{ordinal:06d}:{token}"
    world, query, path_length = _world_for_case(
        case_kind, entity_id=entity_id, proof_prefix=proof_prefix
    )
    dependencies = _dependency_values(spec, ordinal)
    dependencies.update(
        {
            "template_id": f"{spec['source_id']}:template:base",
            "path_length_bucket": path_length,
        }
    )
    example: dict[str, Any] = {
        "schema_version": "1.0.0",
        "record_kind": "policy_example",
        "example_id": example_id,
        "source_id": spec["source_id"],
        "role": spec["role"],
        "prediction_time": world,
        "query": query,
        "candidates": list(ACTIONS),
        "risk": deepcopy(spec["risk_policy"]),
        "dependencies": dependencies,
        "provenance": {
            "generator_id": spec["generator_id"],
            "algorithm_id": spec["algorithm_id"],
            "spec_sha256": canonical_sha256(spec),
            "seed": spec["seed"],
            "ordinal": ordinal,
        },
        "training_authorized": False,
    }
    example["input_sha256"] = canonical_sha256(policy_input_view(example))
    descriptor = _quarantine_descriptor(example)
    decision = match_record(descriptor, quarantine_index)
    if decision["decision"] != "clear":
        raise Phase2QuarantineError(
            f"quarantine rejected {example_id}: "
            f"decision={decision['decision']}, reasons={decision['reasons']}"
        )
    example["quarantine"] = {
        "index_id": quarantine_index["index_id"],
        "index_sha256": quarantine_sha256,
        "decision": "clear",
        "reasons": [],
    }
    forward, _proof_tree = compare_oracles(
        world,
        query,
        max_rule_firings=spec["bounds"]["max_rule_firings"],
        max_depth=spec["bounds"]["max_proof_depth"],
    )
    example["target"] = {"action": forward.action, "payload": forward.payload}
    example["evidence"] = render_evidence(forward)
    validate_policy_example(
        example,
        spec=spec,
        quarantine_index_id=quarantine_index["index_id"],
        quarantine_index_sha256=quarantine_sha256,
    )
    return example


def _action_counts(examples: list[dict[str, Any]]) -> dict[str, int]:
    observed = Counter(example["target"]["action"] for example in examples)
    return {value: observed.get(value, 0) for value in ACTIONS}


def _case_counts(spec: dict[str, Any]) -> dict[str, int]:
    observed = Counter(
        _case_for_ordinal(spec, ordinal) for ordinal in range(spec["example_count"])
    )
    return {value: observed.get(value, 0) for value in CASE_KINDS}


def _mode(rows: list[dict[str, Any]]) -> str:
    counts = Counter(row["target"]["action"] for row in rows)
    if not counts:
        raise Phase2IntegrityError("cannot calculate a baseline from no rows")
    return min(counts, key=lambda action: (-counts[action], action))


def _feature_accuracy(examples: list[dict[str, Any]], feature: str) -> float:
    correct = 0
    for held_out in examples:
        training_rows = [
            row
            for row in examples
            if row["dependencies"]["world_id"] != held_out["dependencies"]["world_id"]
        ]
        matching = [
            row
            for row in training_rows
            if row["dependencies"][feature] == held_out["dependencies"][feature]
        ]
        prediction = _mode(matching or training_rows)
        if prediction == held_out["target"]["action"]:
            correct += 1
    return round(correct / len(examples), 12)


def _shortcut_diagnostics(examples: list[dict[str, Any]]) -> dict[str, Any]:
    action_counts = Counter(example["target"]["action"] for example in examples)
    majority = max(action_counts.values()) / len(examples)
    return {
        "method": "leave-one-world-out-v1",
        "majority_accuracy": round(majority, 12),
        "grammar_accuracy": _feature_accuracy(examples, "grammar_id"),
        "template_accuracy": _feature_accuracy(examples, "template_id"),
        "path_length_accuracy": _feature_accuracy(examples, "path_length_bucket"),
    }


def _dependency_ids(examples: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        kind: sorted({example["dependencies"][f"{kind}_id"] for example in examples})
        for kind in DEPENDENCY_KINDS
    }


def build_generation(
    *,
    registry: dict[str, Any],
    spec: dict[str, Any],
    quarantine_index: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Build examples, integrity report, and manifest entirely in memory."""

    source = bind_registry_spec(registry, spec)
    if spec["role"] not in {"training", "development"}:
        raise Phase2ValidationError(
            "procedural generation permits training/development only"
        )
    quarantine_sha256 = validate_quarantine_index(quarantine_index)
    examples = [
        _build_example(spec, quarantine_index, quarantine_sha256, ordinal)
        for ordinal in range(spec["example_count"])
    ]
    examples.sort(key=lambda item: item["example_id"])
    example_bytes = canonical_jsonl_bytes(examples)
    example_identity = bytes_identity(example_bytes)
    if (
        source["artifact_sha256"] is not None
        and source["artifact_sha256"] != example_identity["sha256"]
    ):
        raise Phase2IntegrityError(
            "generated examples do not match registered artifact hash"
        )

    input_hashes = [example["input_sha256"] for example in examples]
    normalized_hashes = [
        normalized_text_sha256(_input_text(example)) for example in examples
    ]
    exact_duplicates = len(input_hashes) - len(set(input_hashes))
    normalized_duplicates = len(normalized_hashes) - len(set(normalized_hashes))
    if exact_duplicates or normalized_duplicates:
        raise Phase2IntegrityError(
            "procedural generation produced duplicate prediction inputs: "
            f"exact={exact_duplicates}, normalized={normalized_duplicates}"
        )

    action_counts = _action_counts(examples)
    case_counts = _case_counts(spec)
    dependency_ids = _dependency_ids(examples)
    report = {
        "schema_version": "1.0.0",
        "record_kind": "generation_integrity_report",
        "report_id": f"{spec['source_id']}-integrity-v1",
        "created_at": spec["created_at"],
        "source_id": spec["source_id"],
        "role": spec["role"],
        "spec_sha256": canonical_sha256(spec),
        "quarantine_index_id": quarantine_index["index_id"],
        "quarantine_index_sha256": quarantine_sha256,
        "examples_sha256": example_identity["sha256"],
        "example_count": len(examples),
        "action_counts": action_counts,
        "case_counts": case_counts,
        "oracle": {
            "forward_oracle_id": FORWARD_ORACLE_ID,
            "proof_tree_oracle_id": PROOF_TREE_ORACLE_ID,
            "agreement": True,
            "disagreements": [],
        },
        "provenance_complete": True,
        "quarantine_clear": True,
        "exact_duplicate_count": 0,
        "normalized_duplicate_count": 0,
        "registry_role_overlap_count": 0,
        "dependency_ids": dependency_ids,
        "input_sha256s": sorted(input_hashes),
        "normalized_input_sha256s": sorted(normalized_hashes),
        "shortcut_diagnostics": _shortcut_diagnostics(examples),
        "complete": True,
        "blockers": [],
        "training_authorized": False,
    }
    validate_artifact(report)
    manifest = {
        "schema_version": "1.0.0",
        "record_kind": "generation_manifest",
        "manifest_id": f"{spec['source_id']}-generation-v1",
        "created_at": spec["created_at"],
        "source_id": spec["source_id"],
        "role": spec["role"],
        "generator_id": spec["generator_id"],
        "algorithm_id": spec["algorithm_id"],
        "registry_sha256": canonical_sha256(registry),
        "spec_sha256": canonical_sha256(spec),
        "quarantine_index_id": quarantine_index["index_id"],
        "quarantine_index_sha256": quarantine_sha256,
        "examples": example_identity,
        "integrity_report_sha256": canonical_sha256(report),
        "example_count": len(examples),
        "action_counts": action_counts,
        "case_counts": case_counts,
        "dependency_ids": dependency_ids,
        "input_sha256s": sorted(input_hashes),
        "normalized_input_sha256s": sorted(normalized_hashes),
        "complete": True,
        "blockers": [],
        "training_authorized": False,
    }
    validate_artifact(manifest)
    return examples, report, manifest


def verify_generation(
    *,
    registry: dict[str, Any],
    spec: dict[str, Any],
    quarantine_index: dict[str, Any],
    examples: list[dict[str, Any]],
    report: dict[str, Any],
    manifest: dict[str, Any],
    observed_examples_identity: dict[str, Any],
) -> dict[str, Any]:
    expected_examples, expected_report, expected_manifest = build_generation(
        registry=registry, spec=spec, quarantine_index=quarantine_index
    )
    if examples != expected_examples:
        raise Phase2IntegrityError("examples differ from deterministic regeneration")
    if report != expected_report:
        raise Phase2IntegrityError(
            "integrity report differs from deterministic regeneration"
        )
    if manifest != expected_manifest:
        raise Phase2IntegrityError("manifest differs from deterministic regeneration")
    if observed_examples_identity != manifest["examples"]:
        raise Phase2IntegrityError("examples file identity disagrees with manifest")
    return {
        "ok": True,
        "source_id": manifest["source_id"],
        "role": manifest["role"],
        "examples": manifest["example_count"],
        "examples_sha256": manifest["examples"]["sha256"],
        "oracle_agreement": report["oracle"]["agreement"],
        "training_authorized": False,
    }


def audit_corpora(
    manifests: list[dict[str, Any]], reports: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(manifests) < 2 or len(manifests) != len(reports):
        raise Phase2ValidationError(
            "corpus audit requires at least two manifest/report pairs"
        )
    report_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for report in reports:
        validate_artifact(report)
        if report["record_kind"] != "generation_integrity_report":
            raise Phase2ValidationError("corpus audit received a non-integrity report")
        key = (report["source_id"], report["role"], report["spec_sha256"])
        if key in report_by_key:
            raise Phase2ValidationError(f"duplicate integrity report pair: {key}")
        report_by_key[key] = report

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for manifest in manifests:
        validate_artifact(manifest)
        if manifest["record_kind"] != "generation_manifest":
            raise Phase2ValidationError(
                "corpus audit received a non-generation manifest"
            )
        key = (manifest["source_id"], manifest["role"], manifest["spec_sha256"])
        report = report_by_key.pop(key, None)
        if report is None:
            raise Phase2ValidationError(
                f"manifest has no matching integrity report: {key}"
            )
        if manifest["integrity_report_sha256"] != canonical_sha256(report):
            raise Phase2IntegrityError("manifest does not bind its integrity report")
        if manifest["quarantine_index_id"] != report["quarantine_index_id"]:
            raise Phase2IntegrityError("manifest/report quarantine index IDs disagree")
        if manifest["quarantine_index_sha256"] != report["quarantine_index_sha256"]:
            raise Phase2IntegrityError("manifest/report quarantine hashes disagree")
        if manifest["examples"]["sha256"] != report["examples_sha256"]:
            raise Phase2IntegrityError("manifest/report examples hashes disagree")
        if manifest["dependency_ids"] != report["dependency_ids"]:
            raise Phase2IntegrityError("manifest/report dependency IDs disagree")
        if manifest["input_sha256s"] != report["input_sha256s"]:
            raise Phase2IntegrityError("manifest/report exact input hashes disagree")
        if manifest["normalized_input_sha256s"] != report["normalized_input_sha256s"]:
            raise Phase2IntegrityError(
                "manifest/report normalized input hashes disagree"
            )
        if not manifest["complete"] or not report["complete"]:
            raise Phase2IntegrityError("corpus audit refuses incomplete artifacts")
        pairs.append((manifest, report))
    if report_by_key:
        raise Phase2ValidationError("integrity report has no matching manifest")
    pairs.sort(key=lambda pair: (pair[0]["source_id"], pair[0]["role"]))

    source_ids = [manifest["source_id"] for manifest, _report in pairs]
    if len(source_ids) != len(set(source_ids)):
        raise Phase2ValidationError("corpus audit source IDs must be unique")
    roles = sorted({manifest["role"] for manifest, _report in pairs})
    if len(roles) < 2:
        raise Phase2ValidationError("corpus audit requires at least two distinct roles")

    overlaps: list[dict[str, Any]] = []
    for (left, _left_report), (right, _right_report) in combinations(pairs, 2):
        if left["role"] == right["role"]:
            continue
        comparisons: list[tuple[str, set[str], set[str]]] = [
            (
                "artifact_sha256",
                {left["examples"]["sha256"]},
                {right["examples"]["sha256"]},
            ),
            ("input_sha256", set(left["input_sha256s"]), set(right["input_sha256s"])),
            (
                "normalized_input_sha256",
                set(left["normalized_input_sha256s"]),
                set(right["normalized_input_sha256s"]),
            ),
        ]
        comparisons.extend(
            (
                kind,
                set(left["dependency_ids"][kind]),
                set(right["dependency_ids"][kind]),
            )
            for kind in DEPENDENCY_KINDS
        )
        for kind, left_values, right_values in comparisons:
            shared = sorted(left_values & right_values)
            if not shared:
                continue
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
        key=lambda item: (
            item["left_source_id"],
            item["right_source_id"],
            item["kind"],
        )
    )
    manifest_sha256s = sorted(canonical_sha256(item) for item, _report in pairs)
    created_at = max(item["created_at"] for item, _report in pairs)
    audit_seed = {
        "manifest_sha256s": manifest_sha256s,
        "source_ids": sorted(source_ids),
        "roles": roles,
    }
    audit = {
        "schema_version": "1.0.0",
        "record_kind": "corpus_audit",
        "created_at": created_at,
        "audit_id": f"corpus-audit:{canonical_sha256(audit_seed).removeprefix('sha256:')}",
        "manifest_sha256s": manifest_sha256s,
        "source_ids": sorted(source_ids),
        "roles": roles,
        "overlaps": overlaps,
        "clean": not overlaps,
        "training_authorized": False,
    }
    validate_artifact(audit)
    return audit
