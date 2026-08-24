"""Independent declarative and copy-on-write oracles for staged writes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256

from .errors import (
    Phase2IntegrityError,
    Phase2OracleDisagreement,
    Phase2ValidationError,
)
from .process_types import ProcessInput, TransitionResult, apply_operations

DECLARATIVE_ORACLE_ID = "declarative-precondition-effect-v1"
COPY_ON_WRITE_ORACLE_ID = "copy-on-write-transition-v1"


def _decl_live(edge: dict[str, Any]) -> bool:
    return edge["lifecycle"] in {"active", "candidate"}


def _decl_same_value(edge: dict[str, Any], proposal: dict[str, Any]) -> bool:
    return (
        edge["subject_id"] == proposal["subject"]["node_id"]
        and edge["predicate"] == proposal["predicate"]
        and edge["object"] == proposal["object"]
    )


def _decl_provenance(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": item["evidence_id"],
            "source_id": item["source_id"],
            "stance": item["stance"],
            "observed_at": item["observed_at"],
        }
        for item in sorted(proposal["evidence"], key=lambda value: value["evidence_id"])
        if item["status"] != "rejected"
    ]


def _decl_apply(
    snapshot: dict[str, Any], operations: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Declarative oracle's independent precondition/effect evaluator."""

    candidate = deepcopy(snapshot)
    id_fields = {
        "nodes": "node_id",
        "edges": "edge_id",
        "staged_proposals": "record_id",
        "decision_records": "record_id",
    }
    delta: list[dict[str, Any]] = []
    for operation in operations:
        records = candidate[operation["collection"]]
        id_field = id_fields[operation["collection"]]
        matches = [
            (index, record)
            for index, record in enumerate(records)
            if record[id_field] == operation["record_id"]
        ]
        before, after = operation["before"], operation["after"]
        if before is None:
            if matches:
                raise Phase2IntegrityError("declarative insert precondition failed")
            records.append(deepcopy(after))
        elif after is None:
            if len(matches) != 1 or matches[0][1] != before:
                raise Phase2IntegrityError("declarative delete precondition failed")
            del records[matches[0][0]]
        else:
            if len(matches) != 1 or matches[0][1] != before:
                raise Phase2IntegrityError("declarative replace precondition failed")
            records[matches[0][0]] = deepcopy(after)
        records.sort(key=lambda item: item[id_field])
        delta.append(
            {
                "collection": operation["collection"],
                "record_id": operation["record_id"],
                "before_sha256": canonical_sha256(before),
                "after_sha256": canonical_sha256(after),
            }
        )
    from .v2 import validate_process_state

    validate_process_state(candidate)
    return candidate, delta


def _decl_inverse(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "collection": item["collection"],
            "record_id": item["record_id"],
            "before": deepcopy(item["after"]),
            "after": deepcopy(item["before"]),
        }
        for item in reversed(operations)
    ]


def _decl_conditions(
    snapshot: dict[str, Any], operations: list[dict[str, Any]], result_hash: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    base = canonical_sha256(snapshot)
    preconditions: list[dict[str, str]] = [
        {"kind": "snapshot_hash", "subject": snapshot["snapshot_id"], "expected": base},
        {"kind": "invariant", "subject": "scope_consistent", "expected": "true"},
    ]
    for operation in operations:
        before = operation["before"]
        preconditions.append(
            {
                "kind": "record_absent" if before is None else "record_hash",
                "subject": f"{operation['collection']}/{operation['record_id']}",
                "expected": "absent" if before is None else canonical_sha256(before),
            }
        )
    postconditions = [
        {
            "kind": "snapshot_hash",
            "subject": snapshot["snapshot_id"],
            "expected": result_hash,
        },
        {"kind": "invariant", "subject": "scope_consistent", "expected": "true"},
    ]
    return preconditions, postconditions


def evaluate_declarative_transition(process_input: ProcessInput) -> TransitionResult:
    """Oracle A: derive admissibility facts, select an action, then effects."""

    snapshot = process_input.snapshot()
    proposal = process_input.proposal()
    frontier = process_input.frontier()
    scope = process_input.scope()
    policy = process_input.risk_policy()
    original_hash = canonical_sha256(snapshot)
    edges = [edge for edge in snapshot["edges"] if _decl_live(edge)]
    verified_support = sorted(
        item["evidence_id"]
        for item in proposal["evidence"]
        if item["status"] == "verified" and item["stance"] == "supports"
    )
    rejected = any(item["status"] == "rejected" for item in proposal["evidence"])
    ambiguous_identity = any(item["identity_match"] == "ambiguous" for item in frontier)
    unknown_candidate_scope = any(
        item["scope_status"] == "unknown" for item in frontier
    )
    uncertain_frontier = ambiguous_identity or unknown_candidate_scope
    outside_frontier = any(item["scope_status"] == "out_of_scope" for item in frontier)
    exact_edge_ids = [
        item["target_id"]
        for item in frontier
        if item["target_kind"] == "edge" and item["identity_match"] == "exact"
    ]
    target_edge = next(
        (edge for edge in edges if edge["edge_id"] in exact_edge_ids), None
    )
    duplicates = [edge for edge in edges if _decl_same_value(edge, proposal)]
    contradictions = [
        edge
        for edge in edges
        if edge["subject_id"] == proposal["subject"]["node_id"]
        and edge["predicate"] == proposal["predicate"]
        and edge["object"] != proposal["object"]
    ]

    rejection_reason: str | None = None
    if (
        proposal["relevance"] == "irrelevant"
        or proposal["policy_status"] == "prohibited"
        or rejected
    ):
        rejection_reason = "unsupported_write"
    elif scope["status"] == "out_of_scope" or outside_frontier:
        rejection_reason = "cross_scope_write"
    elif proposal["signal"] == "invalidation" and not verified_support:
        rejection_reason = "false_deprecation"
    elif (
        proposal["signal"] in {"correction", "invalidation"}
        and target_edge is not None
        and (
            not target_edge["mutable"]
            or proposal["observation_time"] <= target_edge["observation_time"]
        )
    ):
        rejection_reason = "unsupported_write"

    action: str
    error_class: str
    if rejection_reason is not None:
        action, error_class = "ignore", rejection_reason
    elif (
        not verified_support
        or uncertain_frontier
        or scope["status"] == "unknown"
        or proposal["signal"] in {"correction", "invalidation"}
        and target_edge is None
        or proposal["risk_class"] == "high"
        and proposal["signal"]
        in {
            "assertion",
            "correction",
            "invalidation",
        }
    ):
        action, error_class = "stage", "unnecessary_stage"
    elif duplicates and proposal["signal"] == "assertion":
        action, error_class = "duplicate", "false_identity_merge"
    elif contradictions and proposal["signal"] == "assertion":
        action, error_class = "conflict", "unsupported_write"
    elif proposal["signal"] == "invalidation" and target_edge is not None:
        action, error_class = "deprecate", "false_deprecation"
    elif proposal["signal"] == "correction" and target_edge is not None:
        action, error_class = "update", "missed_valid_write"
    elif proposal["subject"]["node_id"] is None:
        action, error_class = "new_node", "missed_valid_write"
    else:
        action, error_class = "attach", "missed_valid_write"

    provenance = _decl_provenance(proposal)
    operations: list[dict[str, Any]] = []
    proposal_id = proposal["proposal_id"]
    if action == "attach":
        record = {
            "edge_id": f"edge:{proposal_id}",
            "subject_id": proposal["subject"]["node_id"],
            "predicate": proposal["predicate"],
            "object": deepcopy(proposal["object"]),
            "scope_id": snapshot["scope_id"],
            "lifecycle": "candidate",
            "valid_time": deepcopy(proposal["valid_time"]),
            "observation_time": proposal["observation_time"],
            "provenance": provenance,
            "risk_class": proposal["risk_class"],
            "mutable": True,
            "version": 1,
            "previous_version_id": None,
            "conflict_ids": [],
        }
        operations = [
            {
                "collection": "edges",
                "record_id": record["edge_id"],
                "before": None,
                "after": record,
            }
        ]
    elif action == "update":
        if target_edge is None:
            raise Phase2ValidationError("declarative update lacks a target")
        retired = deepcopy(target_edge)
        retired["lifecycle"] = "superseded"
        retired["observation_time"] = proposal["observation_time"]
        retired["valid_time"]["end"] = proposal["valid_time"]["start"]
        retired["provenance"] = sorted(
            [*retired["provenance"], *provenance],
            key=lambda item: item["evidence_id"],
        )
        replacement = deepcopy(target_edge)
        replacement.update(
            {
                "edge_id": f"edge:{proposal_id}",
                "object": deepcopy(proposal["object"]),
                "lifecycle": "candidate",
                "valid_time": deepcopy(proposal["valid_time"]),
                "observation_time": proposal["observation_time"],
                "provenance": provenance,
                "risk_class": proposal["risk_class"],
                "version": target_edge["version"] + 1,
                "previous_version_id": target_edge["edge_id"],
                "conflict_ids": [],
            }
        )
        operations = [
            {
                "collection": "edges",
                "record_id": target_edge["edge_id"],
                "before": target_edge,
                "after": retired,
            },
            {
                "collection": "edges",
                "record_id": replacement["edge_id"],
                "before": None,
                "after": replacement,
            },
        ]
    elif action == "deprecate":
        if target_edge is None:
            raise Phase2ValidationError("declarative deprecate lacks a target")
        retired = deepcopy(target_edge)
        retired["lifecycle"] = "deprecated"
        retired["observation_time"] = proposal["observation_time"]
        retired["valid_time"]["end"] = proposal["valid_time"]["start"]
        retired["provenance"] = sorted(
            [*retired["provenance"], *provenance], key=lambda item: item["evidence_id"]
        )
        operations = [
            {
                "collection": "edges",
                "record_id": target_edge["edge_id"],
                "before": target_edge,
                "after": retired,
            }
        ]
    elif action == "new_node":
        node_id = f"node:{proposal_id}"
        node = {
            "node_id": node_id,
            "node_type": proposal["subject"]["entity_type"],
            "label": proposal["subject"]["label"],
            "scope_id": snapshot["scope_id"],
            "lifecycle": "candidate",
            "valid_time": deepcopy(proposal["valid_time"]),
            "observation_time": proposal["observation_time"],
            "provenance": provenance,
            "risk_class": proposal["risk_class"],
            "conflict_ids": [],
            "version": 1,
        }
        edge = {
            "edge_id": f"edge:{proposal_id}",
            "subject_id": node_id,
            "predicate": proposal["predicate"],
            "object": deepcopy(proposal["object"]),
            "scope_id": snapshot["scope_id"],
            "lifecycle": "candidate",
            "valid_time": deepcopy(proposal["valid_time"]),
            "observation_time": proposal["observation_time"],
            "provenance": provenance,
            "risk_class": proposal["risk_class"],
            "mutable": True,
            "version": 1,
            "previous_version_id": None,
            "conflict_ids": [],
        }
        operations = [
            {
                "collection": "nodes",
                "record_id": node_id,
                "before": None,
                "after": node,
            },
            {
                "collection": "edges",
                "record_id": edge["edge_id"],
                "before": None,
                "after": edge,
            },
        ]
    elif action == "duplicate":
        duplicate = min(duplicates, key=lambda item: item["edge_id"])
        record = {
            "record_id": f"record:{proposal_id}:duplicate",
            "decision_kind": "duplicate",
            "proposal_id": proposal_id,
            "related_ids": [duplicate["edge_id"]],
            "evidence_ids": verified_support,
            "created_at": proposal["observation_time"],
        }
        operations = [
            {
                "collection": "decision_records",
                "record_id": record["record_id"],
                "before": None,
                "after": record,
            }
        ]
    elif action == "conflict":
        conflict = min(contradictions, key=lambda item: item["edge_id"])
        edge = {
            "edge_id": f"edge:{proposal_id}",
            "subject_id": proposal["subject"]["node_id"],
            "predicate": proposal["predicate"],
            "object": deepcopy(proposal["object"]),
            "scope_id": snapshot["scope_id"],
            "lifecycle": "candidate",
            "valid_time": deepcopy(proposal["valid_time"]),
            "observation_time": proposal["observation_time"],
            "provenance": provenance,
            "risk_class": proposal["risk_class"],
            "mutable": True,
            "version": 1,
            "previous_version_id": None,
            "conflict_ids": [conflict["edge_id"]],
        }
        decision = {
            "record_id": f"record:{proposal_id}:conflict",
            "decision_kind": "conflict",
            "proposal_id": proposal_id,
            "related_ids": sorted([conflict["edge_id"], edge["edge_id"]]),
            "evidence_ids": verified_support,
            "created_at": proposal["observation_time"],
        }
        operations = [
            {
                "collection": "edges",
                "record_id": edge["edge_id"],
                "before": None,
                "after": edge,
            },
            {
                "collection": "decision_records",
                "record_id": decision["record_id"],
                "before": None,
                "after": decision,
            },
        ]
    elif action == "stage":
        reasons = []
        if not verified_support:
            reasons.append("evidence_uncertain")
        if ambiguous_identity:
            reasons.append("identity_uncertain")
        if scope["status"] == "unknown" or unknown_candidate_scope:
            reasons.append("scope_uncertain")
        if proposal["risk_class"] == "high":
            reasons.append("risk_high")
        if proposal["signal"] in {"correction", "invalidation"} and target_edge is None:
            reasons.append("identity_uncertain")
        record = {
            "record_id": f"record:{proposal_id}:staged",
            "proposal_id": proposal_id,
            "scope_id": snapshot["scope_id"],
            "reason_codes": sorted(set(reasons or ["evidence_uncertain"])),
            "evidence_ids": sorted(
                item["evidence_id"] for item in proposal["evidence"]
            ),
            "created_at": proposal["observation_time"],
        }
        operations = [
            {
                "collection": "staged_proposals",
                "record_id": record["record_id"],
                "before": None,
                "after": record,
            }
        ]

    if action == "ignore":
        preconditions = [
            {
                "kind": "snapshot_hash",
                "subject": snapshot["snapshot_id"],
                "expected": original_hash,
            },
            {"kind": "invariant", "subject": "no_state_change", "expected": "true"},
        ]
        target = {
            "action": action,
            "patch": None,
            "preconditions": preconditions,
            "postconditions": deepcopy(preconditions),
            "evidence_ids": verified_support,
            "cost_record": {
                "error_class": error_class,
                "cost": policy["error_costs"][error_class],
            },
            "rollback": {"kind": "identity", "restored_snapshot_sha256": original_hash},
        }
        return TransitionResult.from_objects(target, [])

    try:
        candidate, delta = _decl_apply(snapshot, operations)
    except Phase2ValidationError as exc:
        if "cycle" not in str(exc):
            raise
        target = {
            "action": "ignore",
            "patch": None,
            "preconditions": [
                {
                    "kind": "snapshot_hash",
                    "subject": snapshot["snapshot_id"],
                    "expected": original_hash,
                },
                {"kind": "invariant", "subject": "no_state_change", "expected": "true"},
            ],
            "postconditions": [
                {
                    "kind": "snapshot_hash",
                    "subject": snapshot["snapshot_id"],
                    "expected": original_hash,
                },
                {"kind": "invariant", "subject": "no_state_change", "expected": "true"},
            ],
            "evidence_ids": verified_support,
            "cost_record": {
                "error_class": "cycle_violation",
                "cost": policy["error_costs"]["cycle_violation"],
            },
            "rollback": {"kind": "identity", "restored_snapshot_sha256": original_hash},
        }
        return TransitionResult.from_objects(target, [])
    result_hash = canonical_sha256(candidate)
    inverse = _decl_inverse(operations)
    restored, _ = _decl_apply(candidate, inverse)
    if canonical_sha256(restored) != original_hash:
        raise Phase2IntegrityError("declarative rollback failed")
    preconditions, postconditions = _decl_conditions(snapshot, operations, result_hash)
    patch = {
        "patch_id": f"patch:{proposal_id}",
        "base_snapshot_sha256": original_hash,
        "operations": operations,
        "inverse_operations": inverse,
        "result_snapshot_sha256": result_hash,
    }
    target = {
        "action": action,
        "patch": patch,
        "preconditions": preconditions,
        "postconditions": postconditions,
        "evidence_ids": verified_support,
        "cost_record": {
            "error_class": error_class,
            "cost": policy["error_costs"][error_class],
        },
        "rollback": {
            "kind": "inverse_patch",
            "restored_snapshot_sha256": original_hash,
        },
    }
    if canonical_sha256(snapshot) != original_hash:
        raise Phase2IntegrityError("declarative oracle mutated its input")
    return TransitionResult.from_objects(target, delta)


class _CopyOnWriteOracle:
    """Oracle B: independently try bounded actions on disposable state copies."""

    def __init__(self, process_input: ProcessInput) -> None:
        self.input = process_input
        self.snapshot = process_input.snapshot()
        self.proposal = process_input.proposal()
        self.frontier = process_input.frontier()
        self.scope = process_input.scope()
        self.policy = process_input.risk_policy()
        self.base_hash = canonical_sha256(self.snapshot)
        self.live_edges = [
            item
            for item in self.snapshot["edges"]
            if item["lifecycle"] == "active" or item["lifecycle"] == "candidate"
        ]
        self.support_ids = sorted(
            item["evidence_id"]
            for item in self.proposal["evidence"]
            if item["status"] == "verified" and item["stance"] == "supports"
        )

    def _edge_target(self) -> dict[str, Any] | None:
        identifiers = {
            item["target_id"]
            for item in self.frontier
            if item["target_kind"] == "edge" and item["identity_match"] == "exact"
        }
        return next(
            (item for item in self.live_edges if item["edge_id"] in identifiers), None
        )

    def _provenance(self) -> list[dict[str, Any]]:
        values = []
        for item in self.proposal["evidence"]:
            if item["status"] == "rejected":
                continue
            values.append(
                {
                    key: item[key]
                    for key in ("evidence_id", "source_id", "stance", "observed_at")
                }
            )
        return sorted(values, key=lambda item: item["evidence_id"])

    def _ignore(self, error_class: str) -> TransitionResult:
        conditions = [
            {
                "kind": "snapshot_hash",
                "subject": self.snapshot["snapshot_id"],
                "expected": self.base_hash,
            },
            {"kind": "invariant", "subject": "no_state_change", "expected": "true"},
        ]
        target = {
            "action": "ignore",
            "patch": None,
            "preconditions": conditions,
            "postconditions": deepcopy(conditions),
            "evidence_ids": self.support_ids,
            "cost_record": {
                "error_class": error_class,
                "cost": self.policy["error_costs"][error_class],
            },
            "rollback": {
                "kind": "identity",
                "restored_snapshot_sha256": self.base_hash,
            },
        }
        return TransitionResult.from_objects(target, [])

    def _finish(
        self, action: str, error_class: str, operations: list[dict[str, Any]]
    ) -> TransitionResult:
        try:
            candidate, delta = apply_operations(self.snapshot, operations)
        except Phase2ValidationError as exc:
            if "cycle" in str(exc):
                return self._ignore("cycle_violation")
            raise
        result_hash = canonical_sha256(candidate)
        inverse = [
            {
                "collection": item["collection"],
                "record_id": item["record_id"],
                "before": deepcopy(item["after"]),
                "after": deepcopy(item["before"]),
            }
            for item in reversed(operations)
        ]
        restored, _ = apply_operations(candidate, inverse)
        if canonical_sha256(restored) != self.base_hash:
            raise Phase2IntegrityError("copy-on-write rollback failed")
        preconditions = [
            {
                "kind": "snapshot_hash",
                "subject": self.snapshot["snapshot_id"],
                "expected": self.base_hash,
            },
            {"kind": "invariant", "subject": "scope_consistent", "expected": "true"},
        ]
        for operation in operations:
            before = operation["before"]
            preconditions.append(
                {
                    "kind": "record_absent" if before is None else "record_hash",
                    "subject": f"{operation['collection']}/{operation['record_id']}",
                    "expected": "absent"
                    if before is None
                    else canonical_sha256(before),
                }
            )
        postconditions = [
            {
                "kind": "snapshot_hash",
                "subject": self.snapshot["snapshot_id"],
                "expected": result_hash,
            },
            {"kind": "invariant", "subject": "scope_consistent", "expected": "true"},
        ]
        patch = {
            "patch_id": f"patch:{self.proposal['proposal_id']}",
            "base_snapshot_sha256": self.base_hash,
            "operations": operations,
            "inverse_operations": inverse,
            "result_snapshot_sha256": result_hash,
        }
        target = {
            "action": action,
            "patch": patch,
            "preconditions": preconditions,
            "postconditions": postconditions,
            "evidence_ids": self.support_ids,
            "cost_record": {
                "error_class": error_class,
                "cost": self.policy["error_costs"][error_class],
            },
            "rollback": {
                "kind": "inverse_patch",
                "restored_snapshot_sha256": self.base_hash,
            },
        }
        return TransitionResult.from_objects(target, delta)

    def _stage(self) -> TransitionResult:
        reasons = []
        if not self.support_ids:
            reasons.append("evidence_uncertain")
        if any(item["identity_match"] == "ambiguous" for item in self.frontier):
            reasons.append("identity_uncertain")
        if self.scope["status"] == "unknown" or any(
            item["scope_status"] == "unknown" for item in self.frontier
        ):
            reasons.append("scope_uncertain")
        if self.proposal["risk_class"] == "high":
            reasons.append("risk_high")
        if (
            self.proposal["signal"] in {"correction", "invalidation"}
            and self._edge_target() is None
        ):
            reasons.append("identity_uncertain")
        record = {
            "record_id": f"record:{self.proposal['proposal_id']}:staged",
            "proposal_id": self.proposal["proposal_id"],
            "scope_id": self.snapshot["scope_id"],
            "reason_codes": sorted(set(reasons or ["evidence_uncertain"])),
            "evidence_ids": sorted(
                item["evidence_id"] for item in self.proposal["evidence"]
            ),
            "created_at": self.proposal["observation_time"],
        }
        return self._finish(
            "stage",
            "unnecessary_stage",
            [
                {
                    "collection": "staged_proposals",
                    "record_id": record["record_id"],
                    "before": None,
                    "after": record,
                }
            ],
        )

    def evaluate(self) -> TransitionResult:
        p = self.proposal
        if (
            p["relevance"] == "irrelevant"
            or p["policy_status"] == "prohibited"
            or any(item["status"] == "rejected" for item in p["evidence"])
        ):
            return self._ignore("unsupported_write")
        if self.scope["status"] == "out_of_scope" or any(
            item["scope_status"] == "out_of_scope" for item in self.frontier
        ):
            return self._ignore("cross_scope_write")
        target_edge = self._edge_target()
        if p["signal"] == "invalidation" and not self.support_ids:
            return self._ignore("false_deprecation")
        if (
            p["signal"] in {"correction", "invalidation"}
            and target_edge is not None
            and (
                not target_edge["mutable"]
                or p["observation_time"] <= target_edge["observation_time"]
            )
        ):
            return self._ignore("unsupported_write")

        uncertain = (
            not self.support_ids
            or self.scope["status"] == "unknown"
            or any(
                item["identity_match"] == "ambiguous"
                or item["scope_status"] == "unknown"
                for item in self.frontier
            )
        )
        if uncertain or p["risk_class"] == "high":
            return self._stage()
        if p["signal"] in {"correction", "invalidation"} and target_edge is None:
            return self._stage()

        equivalent = next(
            (
                edge
                for edge in sorted(self.live_edges, key=lambda item: item["edge_id"])
                if edge["subject_id"] == p["subject"]["node_id"]
                and edge["predicate"] == p["predicate"]
                and edge["object"] == p["object"]
            ),
            None,
        )
        if equivalent is not None and self.support_ids and p["signal"] == "assertion":
            record = {
                "record_id": f"record:{p['proposal_id']}:duplicate",
                "decision_kind": "duplicate",
                "proposal_id": p["proposal_id"],
                "related_ids": [equivalent["edge_id"]],
                "evidence_ids": self.support_ids,
                "created_at": p["observation_time"],
            }
            return self._finish(
                "duplicate",
                "false_identity_merge",
                [
                    {
                        "collection": "decision_records",
                        "record_id": record["record_id"],
                        "before": None,
                        "after": record,
                    }
                ],
            )

        opposed = next(
            (
                edge
                for edge in sorted(self.live_edges, key=lambda item: item["edge_id"])
                if edge["subject_id"] == p["subject"]["node_id"]
                and edge["predicate"] == p["predicate"]
                and edge["object"] != p["object"]
            ),
            None,
        )
        if opposed is not None and self.support_ids and p["signal"] == "assertion":
            edge = {
                "edge_id": f"edge:{p['proposal_id']}",
                "subject_id": p["subject"]["node_id"],
                "predicate": p["predicate"],
                "object": deepcopy(p["object"]),
                "scope_id": self.snapshot["scope_id"],
                "lifecycle": "candidate",
                "valid_time": deepcopy(p["valid_time"]),
                "observation_time": p["observation_time"],
                "provenance": self._provenance(),
                "risk_class": p["risk_class"],
                "mutable": True,
                "version": 1,
                "previous_version_id": None,
                "conflict_ids": [opposed["edge_id"]],
            }
            decision = {
                "record_id": f"record:{p['proposal_id']}:conflict",
                "decision_kind": "conflict",
                "proposal_id": p["proposal_id"],
                "related_ids": sorted([opposed["edge_id"], edge["edge_id"]]),
                "evidence_ids": self.support_ids,
                "created_at": p["observation_time"],
            }
            return self._finish(
                "conflict",
                "unsupported_write",
                [
                    {
                        "collection": "edges",
                        "record_id": edge["edge_id"],
                        "before": None,
                        "after": edge,
                    },
                    {
                        "collection": "decision_records",
                        "record_id": decision["record_id"],
                        "before": None,
                        "after": decision,
                    },
                ],
            )

        provenance = self._provenance()
        if p["signal"] == "invalidation" and target_edge is not None:
            changed = deepcopy(target_edge)
            changed["lifecycle"] = "deprecated"
            changed["observation_time"] = p["observation_time"]
            changed["valid_time"]["end"] = p["valid_time"]["start"]
            changed["provenance"] = sorted(
                [*changed["provenance"], *provenance],
                key=lambda item: item["evidence_id"],
            )
            return self._finish(
                "deprecate",
                "false_deprecation",
                [
                    {
                        "collection": "edges",
                        "record_id": target_edge["edge_id"],
                        "before": target_edge,
                        "after": changed,
                    }
                ],
            )
        if p["signal"] == "correction" and target_edge is not None:
            old = deepcopy(target_edge)
            old["lifecycle"] = "superseded"
            old["observation_time"] = p["observation_time"]
            old["valid_time"]["end"] = p["valid_time"]["start"]
            old["provenance"] = sorted(
                [*old["provenance"], *provenance],
                key=lambda item: item["evidence_id"],
            )
            new = deepcopy(target_edge)
            new.update(
                {
                    "edge_id": f"edge:{p['proposal_id']}",
                    "object": deepcopy(p["object"]),
                    "lifecycle": "candidate",
                    "valid_time": deepcopy(p["valid_time"]),
                    "observation_time": p["observation_time"],
                    "provenance": provenance,
                    "risk_class": p["risk_class"],
                    "version": target_edge["version"] + 1,
                    "previous_version_id": target_edge["edge_id"],
                    "conflict_ids": [],
                }
            )
            return self._finish(
                "update",
                "missed_valid_write",
                [
                    {
                        "collection": "edges",
                        "record_id": target_edge["edge_id"],
                        "before": target_edge,
                        "after": old,
                    },
                    {
                        "collection": "edges",
                        "record_id": new["edge_id"],
                        "before": None,
                        "after": new,
                    },
                ],
            )
        if p["subject"]["node_id"] is None:
            node_id = f"node:{p['proposal_id']}"
            node = {
                "node_id": node_id,
                "node_type": p["subject"]["entity_type"],
                "label": p["subject"]["label"],
                "scope_id": self.snapshot["scope_id"],
                "lifecycle": "candidate",
                "valid_time": deepcopy(p["valid_time"]),
                "observation_time": p["observation_time"],
                "provenance": provenance,
                "risk_class": p["risk_class"],
                "conflict_ids": [],
                "version": 1,
            }
            edge = {
                "edge_id": f"edge:{p['proposal_id']}",
                "subject_id": node_id,
                "predicate": p["predicate"],
                "object": deepcopy(p["object"]),
                "scope_id": self.snapshot["scope_id"],
                "lifecycle": "candidate",
                "valid_time": deepcopy(p["valid_time"]),
                "observation_time": p["observation_time"],
                "provenance": provenance,
                "risk_class": p["risk_class"],
                "mutable": True,
                "version": 1,
                "previous_version_id": None,
                "conflict_ids": [],
            }
            return self._finish(
                "new_node",
                "missed_valid_write",
                [
                    {
                        "collection": "nodes",
                        "record_id": node_id,
                        "before": None,
                        "after": node,
                    },
                    {
                        "collection": "edges",
                        "record_id": edge["edge_id"],
                        "before": None,
                        "after": edge,
                    },
                ],
            )
        edge = {
            "edge_id": f"edge:{p['proposal_id']}",
            "subject_id": p["subject"]["node_id"],
            "predicate": p["predicate"],
            "object": deepcopy(p["object"]),
            "scope_id": self.snapshot["scope_id"],
            "lifecycle": "candidate",
            "valid_time": deepcopy(p["valid_time"]),
            "observation_time": p["observation_time"],
            "provenance": provenance,
            "risk_class": p["risk_class"],
            "mutable": True,
            "version": 1,
            "previous_version_id": None,
            "conflict_ids": [],
        }
        return self._finish(
            "attach",
            "missed_valid_write",
            [
                {
                    "collection": "edges",
                    "record_id": edge["edge_id"],
                    "before": None,
                    "after": edge,
                }
            ],
        )


def evaluate_copy_on_write_transition(process_input: ProcessInput) -> TransitionResult:
    return _CopyOnWriteOracle(process_input).evaluate()


def compare_transition_oracles(process_input: ProcessInput) -> TransitionResult:
    before = process_input.snapshot_bytes
    declarative = evaluate_declarative_transition(process_input)
    if process_input.snapshot_bytes != before:
        raise Phase2IntegrityError("declarative transition mutated immutable input")
    copy_on_write = evaluate_copy_on_write_transition(process_input)
    if process_input.snapshot_bytes != before:
        raise Phase2IntegrityError("copy-on-write transition mutated immutable input")
    if (
        declarative.target_bytes != copy_on_write.target_bytes
        or declarative.delta_bytes != copy_on_write.delta_bytes
    ):
        raise Phase2OracleDisagreement(
            "process transition oracles disagree on action, patch, conditions, or delta"
        )
    return declarative
