"""Validation and deterministic replay assembly for eight development objectives."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .contracts import (
    OBJECTIVE_FAMILIES,
    validate_artifact_manifest,
    validate_objective_example,
)
from .errors import Phase1ValidationError

ALGORITHM_ID = "objective-validation-replay-v1"
REPLAY_SEED = 20_260_817


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def replay_objectives(
    records: Iterable[dict[str, Any]], *, seed: int = REPLAY_SEED
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate and order predeclared development examples without relabelling."""

    values = list(records)
    seen: set[str] = set()
    graph_hashes: set[str] = set()
    quarantine_hashes: set[str] = set()
    family_counts: Counter[str] = Counter()
    for example in values:
        validate_objective_example(example)
        example_id = example["example_id"]
        if example_id in seen:
            raise Phase1ValidationError(f"duplicate objective example_id: {example_id}")
        seen.add(example_id)
        graph_hashes.add(example["graph_snapshot_sha256"])
        quarantine_hashes.add(example["quarantine_index_sha256"])
        family_counts[example["objective_family"]] += 1
    if len(graph_hashes) != 1:
        raise Phase1ValidationError("objective replay must bind one graph snapshot")
    if len(quarantine_hashes) != 1:
        raise Phase1ValidationError("objective replay must bind one quarantine index")
    missing = OBJECTIVE_FAMILIES - set(family_counts)
    if missing:
        raise Phase1ValidationError(
            f"objective replay is missing required families: {sorted(missing)}"
        )
    ordered = sorted(
        values,
        key=lambda item: (
            hashlib.sha256(f"{seed}\0{item['example_id']}".encode()).hexdigest(),
            item["example_id"],
        ),
    )
    stats = {
        "example_count": len(ordered),
        "family_counts": {
            family: family_counts[family] for family in sorted(OBJECTIVE_FAMILIES)
        },
        "graph_snapshot_sha256": next(iter(graph_hashes)),
        "quarantine_index_sha256": next(iter(quarantine_hashes)),
    }
    return ordered, stats


def make_objective_manifest(
    *,
    phase0_gate_sha256: str,
    input_sha256: str,
    output_sha256: str,
    stats: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    manifest = {
        "schema_version": "1.0.0",
        "record_kind": "objective_manifest",
        "phase0_gate_sha256": phase0_gate_sha256,
        "created_at": created_at or _utc_now(),
        "algorithm_id": ALGORITHM_ID,
        "complete": True,
        "errors": [],
        "training_authorized": False,
        "input_sha256": input_sha256,
        "output_sha256": output_sha256,
        **stats,
        "development_only": True,
        "maximum_candidates": 8,
        "absent_edge_negatives": 0,
    }
    validate_artifact_manifest(manifest)
    return manifest
