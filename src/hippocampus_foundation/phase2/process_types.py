"""Immutable byte-backed inputs and reversible process-state patch operations."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_bytes, canonical_sha256

from .errors import Phase2IntegrityError, Phase2ValidationError

COLLECTION_IDS = {
    "nodes": "node_id",
    "edges": "edge_id",
    "staged_proposals": "record_id",
    "decision_records": "record_id",
}


def _decode(value: bytes) -> Any:
    return json.loads(value)


@dataclass(frozen=True)
class ProcessInput:
    """An immutable, canonical representation shared by both transition oracles."""

    snapshot_bytes: bytes
    proposal_bytes: bytes
    frontier_bytes: bytes
    visible_evidence_bytes: bytes
    scope_bytes: bytes
    risk_policy_bytes: bytes

    @classmethod
    def from_example(cls, example: dict[str, Any]) -> ProcessInput:
        return cls(
            snapshot_bytes=canonical_bytes(example["snapshot"]),
            proposal_bytes=canonical_bytes(example["proposal"]),
            frontier_bytes=canonical_bytes(example["candidate_frontier"]),
            visible_evidence_bytes=canonical_bytes(example["visible_evidence_ids"]),
            scope_bytes=canonical_bytes(example["scope"]),
            risk_policy_bytes=canonical_bytes(example["risk_policy"]),
        )

    @property
    def snapshot_sha256(self) -> str:
        return canonical_sha256(_decode(self.snapshot_bytes))

    def snapshot(self) -> dict[str, Any]:
        return _decode(self.snapshot_bytes)

    def proposal(self) -> dict[str, Any]:
        return _decode(self.proposal_bytes)

    def frontier(self) -> list[dict[str, Any]]:
        return _decode(self.frontier_bytes)

    def visible_evidence_ids(self) -> list[str]:
        return _decode(self.visible_evidence_bytes)

    def scope(self) -> dict[str, Any]:
        return _decode(self.scope_bytes)

    def risk_policy(self) -> dict[str, Any]:
        return _decode(self.risk_policy_bytes)


@dataclass(frozen=True)
class TransitionResult:
    """Canonical immutable transition target and observable delta."""

    target_bytes: bytes
    delta_bytes: bytes

    @classmethod
    def from_objects(
        cls, target: dict[str, Any], delta: list[dict[str, Any]]
    ) -> TransitionResult:
        return cls(canonical_bytes(target), canonical_bytes(delta))

    @property
    def action(self) -> str:
        return self.target()["action"]

    def target(self) -> dict[str, Any]:
        return _decode(self.target_bytes)

    def delta(self) -> list[dict[str, Any]]:
        return _decode(self.delta_bytes)


def normalized_inverse(
    operations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "collection": operation["collection"],
            "record_id": operation["record_id"],
            "before": deepcopy(operation["after"]),
            "after": deepcopy(operation["before"]),
        }
        for operation in reversed(operations)
    ]


def _find_record(
    records: list[dict[str, Any]], id_field: str, record_id: str
) -> tuple[int | None, dict[str, Any] | None]:
    for index, record in enumerate(records):
        if record[id_field] == record_id:
            return index, record
    return None, None


def apply_operations(
    snapshot: dict[str, Any], operations: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply typed operations to a fresh copy and return a normalized delta."""

    candidate = deepcopy(snapshot)
    delta: list[dict[str, Any]] = []
    for operation in operations:
        collection = operation.get("collection")
        if collection not in COLLECTION_IDS:
            raise Phase2ValidationError(f"unsupported patch collection: {collection}")
        record_id = operation.get("record_id")
        if not isinstance(record_id, str):
            raise Phase2ValidationError("patch record_id must be a string")
        before = operation.get("before")
        after = operation.get("after")
        if before == after:
            raise Phase2ValidationError("patch operation must change a record")
        if before is None and after is None:
            raise Phase2ValidationError("patch operation cannot be null to null")
        records = candidate[collection]
        id_field = COLLECTION_IDS[collection]
        index, observed = _find_record(records, id_field, record_id)
        if before is None:
            if observed is not None:
                raise Phase2IntegrityError(
                    f"patch insert precondition failed: {collection}/{record_id} exists"
                )
            if not isinstance(after, dict) or after.get(id_field) != record_id:
                raise Phase2ValidationError("patch insert record identity mismatch")
            records.append(deepcopy(after))
        elif after is None:
            if observed != before or index is None:
                raise Phase2IntegrityError(
                    f"patch delete precondition failed: {collection}/{record_id}"
                )
            del records[index]
        else:
            if observed != before or index is None:
                raise Phase2IntegrityError(
                    f"patch replace precondition failed: {collection}/{record_id}"
                )
            if not isinstance(after, dict) or after.get(id_field) != record_id:
                raise Phase2ValidationError("patch replace record identity mismatch")
            records[index] = deepcopy(after)
        records.sort(key=lambda item: item[id_field])
        delta.append(
            {
                "collection": collection,
                "record_id": record_id,
                "before_sha256": canonical_sha256(before),
                "after_sha256": canonical_sha256(after),
            }
        )

    from .v2 import validate_process_state

    validate_process_state(candidate)
    return candidate, delta


def apply_patch(
    snapshot: dict[str, Any], patch: dict[str, Any], *, inverse: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    observed = canonical_sha256(snapshot)
    expected = (
        patch["result_snapshot_sha256"] if inverse else patch["base_snapshot_sha256"]
    )
    if observed != expected:
        raise Phase2IntegrityError(
            f"patch base hash mismatch: expected {expected}, observed {observed}"
        )
    operations = patch["inverse_operations"] if inverse else patch["operations"]
    candidate, delta = apply_operations(snapshot, operations)
    wanted = (
        patch["base_snapshot_sha256"] if inverse else patch["result_snapshot_sha256"]
    )
    if canonical_sha256(candidate) != wanted:
        raise Phase2IntegrityError("patch result hash disagrees with declared state")
    return candidate, delta
