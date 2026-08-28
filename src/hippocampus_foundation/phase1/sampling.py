"""Deterministic community-covering, joint-strata node sampling."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .contracts import validate_artifact_manifest, validate_graph_record
from .errors import Phase1ValidationError

DEFAULT_SAMPLE_SIZE = 40_000
DEFAULT_SAMPLE_SEED = 20_260_817
ALGORITHM_ID = "community-joint-strata-waterfill-v1"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _score(seed: int, *parts: str) -> str:
    payload = "\0".join((str(seed), *parts)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _empirical_bins(
    records: list[dict[str, Any]], field: str, bin_count: int
) -> dict[str, int]:
    ordered = sorted(records, key=lambda item: (item[field], item["node_id"]))
    total = len(ordered)
    return {
        item["node_id"]: min(bin_count - 1, index * bin_count // total)
        for index, item in enumerate(ordered)
    }


def select_nodes(
    records: Iterable[dict[str, Any]],
    *,
    size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SAMPLE_SEED,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Select a deterministic sample without consulting labels or held-out data."""

    values = list(records)
    if size < 1:
        raise Phase1ValidationError("sample size must be positive")
    if len(values) < size:
        raise Phase1ValidationError(
            f"sample requires {size} nodes but only {len(values)} candidates exist"
        )
    node_ids: set[str] = set()
    for record in values:
        validate_graph_record(record)
        if record["record_kind"] != "node":
            raise Phase1ValidationError("sampling input contains a non-node record")
        node_id = record["node_id"]
        if node_id in node_ids:
            raise Phase1ValidationError(
                f"duplicate sample candidate node_id: {node_id}"
            )
        node_ids.add(node_id)

    communities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in values:
        communities[record["community_id"]].append(record)
    if len(communities) > size:
        raise Phase1ValidationError(
            f"sample size {size} cannot cover {len(communities)} communities"
        )

    length_bins = _empirical_bins(values, "text_characters", 5)
    incoming_bins = _empirical_bins(values, "in_degree", 3)
    outgoing_bins = _empirical_bins(values, "out_degree", 3)
    pagerank_bins = _empirical_bins(values, "pagerank", 10)

    def stratum(record: dict[str, Any]) -> tuple[str, int, int, int, int]:
        node_id = record["node_id"]
        return (
            record["source_kind"],
            length_bins[node_id],
            incoming_bins[node_id],
            outgoing_bins[node_id],
            pagerank_bins[node_id],
        )

    selected_ids: set[str] = set()
    for community_id in sorted(communities):
        chosen = min(
            communities[community_id],
            key=lambda item: (
                _score(seed, "community", item["node_id"]),
                item["node_id"],
            ),
        )
        selected_ids.add(chosen["node_id"])

    buckets: dict[tuple[str, int, int, int, int], list[dict[str, Any]]] = defaultdict(
        list
    )
    for record in values:
        buckets[stratum(record)].append(record)
    for key in buckets:
        buckets[key].sort(
            key=lambda item: (_score(seed, "stratum", item["node_id"]), item["node_id"])
        )

    positions = {key: 0 for key in buckets}
    ordered_keys = sorted(buckets)
    while len(selected_ids) < size:
        progress = False
        for key in ordered_keys:
            bucket = buckets[key]
            position = positions[key]
            while (
                position < len(bucket) and bucket[position]["node_id"] in selected_ids
            ):
                position += 1
            positions[key] = position
            if position >= len(bucket):
                continue
            selected_ids.add(bucket[position]["node_id"])
            positions[key] += 1
            progress = True
            if len(selected_ids) == size:
                break
        if not progress:
            raise Phase1ValidationError(
                "water-fill exhausted before reaching sample size"
            )

    selected = sorted(
        (item for item in values if item["node_id"] in selected_ids),
        key=lambda item: item["node_id"],
    )
    selected_strata = {stratum(item) for item in selected}
    stats = {
        "candidate_count": len(values),
        "selected_size": len(selected),
        "community_count": len(communities),
        "covered_communities": len({item["community_id"] for item in selected}),
        "stratum_count": len(buckets),
        "covered_strata": len(selected_strata),
    }
    return selected, stats


def make_sample_manifest(
    *,
    phase0_gate_sha256: str,
    candidate_sha256: str,
    selected_sha256: str,
    quarantine_index_sha256: str,
    requested_size: int,
    stats: dict[str, int],
    created_at: str | None = None,
) -> dict[str, Any]:
    manifest = {
        "schema_version": "1.0.0",
        "record_kind": "sample_manifest",
        "phase0_gate_sha256": phase0_gate_sha256,
        "created_at": created_at or _utc_now(),
        "algorithm_id": ALGORITHM_ID,
        "complete": True,
        "errors": [],
        "training_authorized": False,
        "candidate_sha256": candidate_sha256,
        "selected_sha256": selected_sha256,
        "quarantine_index_sha256": quarantine_index_sha256,
        "seed": DEFAULT_SAMPLE_SEED,
        "requested_size": requested_size,
        **stats,
    }
    validate_artifact_manifest(manifest)
    return manifest
