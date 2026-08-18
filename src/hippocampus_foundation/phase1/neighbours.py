"""Deterministic one-hop context caps with a complete overflow ledger."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .contracts import validate_artifact_manifest, validate_graph_record
from .errors import Phase1ValidationError


ALGORITHM_ID = "one-hop-diverse-cap-v1"
SELECTION_SEED = 20_260_817
LIMITS = {
    "wikipedia_outgoing_entity": 16,
    "wikipedia_incoming_entity": 8,
    "wikidata_outgoing_entity": 24,
    "wikidata_incoming_entity": 8,
    "wikidata_outgoing_literal": 32,
    "wikidata_property": 4,
}

_RANK_ORDER = {"preferred": 0, "normal": 1, "deprecated": 2}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(*parts: str) -> str:
    return hashlib.sha256(
        "\0".join((str(SELECTION_SEED), *parts)).encode("utf-8")
    ).hexdigest()


def _category(record: dict[str, Any]) -> str:
    suffix = "literal" if record["value_kind"] == "literal" else "entity"
    key = f"{record['source_kind']}_{record['direction']}_{suffix}"
    if key not in LIMITS:
        raise Phase1ValidationError(f"unsupported neighbour category: {key}")
    return key


def _record_order(record: dict[str, Any]) -> tuple[int, str, str]:
    return (
        _RANK_ORDER[record["rank"]],
        _hash(
            record["center_node_id"],
            record["property_id"],
            record["diversity_key"],
            record["candidate_id"],
        ),
        record["candidate_id"],
    )


def _property_diverse_prefix(
    records: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_diversity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_diversity[record["diversity_key"]].append(record)
    for values in by_diversity.values():
        values.sort(key=_record_order)
    keys = sorted(
        by_diversity,
        key=lambda key: (
            _record_order(by_diversity[key][0]),
            key,
        ),
    )
    positions = {key: 0 for key in keys}
    selected: list[dict[str, Any]] = []
    while len(selected) < limit:
        progressed = False
        for key in keys:
            position = positions[key]
            values = by_diversity[key]
            if position >= len(values):
                continue
            selected.append(values[position])
            positions[key] += 1
            progressed = True
            if len(selected) == limit:
                break
        if not progressed:
            break
    selected_ids = {item["candidate_id"] for item in selected}
    overflow = [item for item in records if item["candidate_id"] not in selected_ids]
    return selected, overflow


def _category_waterfill(
    records: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_property: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_property[record["property_id"]].append(record)
    for values in by_property.values():
        values.sort(key=_record_order)
    properties = sorted(
        by_property,
        key=lambda value: (
            _hash(records[0]["center_node_id"], "property", value),
            value,
        ),
    )
    positions = {value: 0 for value in properties}
    selected: list[dict[str, Any]] = []
    while len(selected) < limit:
        progressed = False
        for property_id in properties:
            position = positions[property_id]
            values = by_property[property_id]
            if position >= len(values):
                continue
            selected.append(values[position])
            positions[property_id] += 1
            progressed = True
            if len(selected) == limit:
                break
        if not progressed:
            break
    selected_ids = {item["candidate_id"] for item in selected}
    overflow = [item for item in records if item["candidate_id"] not in selected_ids]
    return selected, overflow


def cap_neighbours(
    records: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    values = list(records)
    candidate_ids: set[str] = set()
    for record in values:
        validate_graph_record(record)
        if record["record_kind"] != "neighbour_candidate":
            raise Phase1ValidationError("neighbour cap input contains another record kind")
        candidate_id = record["candidate_id"]
        if candidate_id in candidate_ids:
            raise Phase1ValidationError(f"duplicate neighbour candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        _category(record)

    selected: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    retained_ids = {
        item["candidate_id"] for item in values if item["source_kind"] == "wikipedia"
    }
    wikidata_by_property: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in values:
        if record["source_kind"] == "wikidata":
            wikidata_by_property[
                (record["center_node_id"], record["property_id"])
            ].append(record)
    for key in sorted(wikidata_by_property):
        within, excluded = _property_diverse_prefix(
            wikidata_by_property[key], LIMITS["wikidata_property"]
        )
        retained_ids.update(item["candidate_id"] for item in within)
        overflow.extend(
            {
                "schema_version": "1.0.0",
                "record_kind": "neighbour_overflow",
                "reason": "property_cap",
                "candidate": item,
            }
            for item in excluded
        )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in values:
        if record["candidate_id"] in retained_ids:
            grouped[(record["center_node_id"], _category(record))].append(record)
    for (_, category), group in sorted(grouped.items()):
        within_category, excluded_category = _category_waterfill(
            group, LIMITS[category]
        )
        selected.extend(within_category)
        overflow.extend(
            {
                "schema_version": "1.0.0",
                "record_kind": "neighbour_overflow",
                "reason": "category_cap",
                "candidate": item,
            }
            for item in excluded_category
        )

    selected.sort(key=lambda item: (item["center_node_id"], _category(item), item["candidate_id"]))
    overflow.sort(
        key=lambda item: (
            item["candidate"]["center_node_id"],
            _category(item["candidate"]),
            item["reason"],
            item["candidate"]["candidate_id"],
        )
    )
    for record in overflow:
        validate_graph_record(record)
    if len(values) != len(selected) + len(overflow):
        raise Phase1ValidationError("neighbour accounting lost or duplicated records")
    stats = {
        "input_count": len(values),
        "selected_count": len(selected),
        "overflow_count": len(overflow),
    }
    return selected, overflow, stats


def make_cap_manifest(
    *,
    phase0_gate_sha256: str,
    input_sha256: str,
    selected_sha256: str,
    overflow_sha256: str,
    quarantine_index_sha256: str,
    stats: dict[str, int],
    created_at: str | None = None,
) -> dict[str, Any]:
    manifest = {
        "schema_version": "1.0.0",
        "record_kind": "neighbour_cap_manifest",
        "phase0_gate_sha256": phase0_gate_sha256,
        "created_at": created_at or _utc_now(),
        "algorithm_id": ALGORITHM_ID,
        "complete": True,
        "errors": [],
        "training_authorized": False,
        "input_sha256": input_sha256,
        "selected_sha256": selected_sha256,
        "overflow_sha256": overflow_sha256,
        "quarantine_index_sha256": quarantine_index_sha256,
        **stats,
        "no_silent_drop": stats["input_count"]
        == stats["selected_count"] + stats["overflow_count"],
        "limits": LIMITS,
    }
    validate_artifact_manifest(manifest)
    return manifest
