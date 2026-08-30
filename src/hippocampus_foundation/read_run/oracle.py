"""Independent visible-graph oracle for the preregistered READ experiment.

This implementation does not import generator helpers. It uses a backwards
dynamic program, unlike the generator's forward recursive construction check.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .errors import IntegrityGateError


def _assertion_mask(values: list[int]) -> int:
    if len(values) != len(set(values)) or any(
        value not in range(4) for value in values
    ):
        raise IntegrityGateError("node assertions are not a unique subset of 0..3")
    return sum(1 << value for value in values)


def independently_solve(
    visible: dict[str, Any], *, allow_disconnected: bool = False
) -> dict[str, Any]:
    """Derive targets, routes, teacher actions, labels, and gamma from visibility."""

    if visible.get("record_kind") != "read_episode_visible":
        raise IntegrityGateError("independent oracle received the wrong record kind")
    node_count = visible.get("node_count")
    relation_count = visible.get("relation_count")
    if not isinstance(node_count, int) or not 1 <= node_count <= 256:
        raise IntegrityGateError("visible node count is invalid")
    if not isinstance(relation_count, int) or not 1 <= relation_count <= 16:
        raise IntegrityGateError("visible relation count is invalid")
    nodes = visible.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != node_count:
        raise IntegrityGateError("visible node table is incomplete")
    masks: dict[int, int] = {}
    for expected_node, item in enumerate(nodes):
        if item.get("node") != expected_node or set(item) != {"node", "assertions"}:
            raise IntegrityGateError("visible node table is not canonical")
        masks[expected_node] = _assertion_mask(item["assertions"])

    edges = visible.get("edges")
    if not isinstance(edges, list) or not edges:
        raise IntegrityGateError("visible edge table is empty")
    expected_edge_fields = {
        "edge_id",
        "source",
        "target",
        "relation",
        "query_similarity_ppm",
    }
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    by_id: dict[int, dict[str, int]] = {}
    triples: set[tuple[int, int, int]] = set()
    for expected_id, edge in enumerate(edges):
        if set(edge) != expected_edge_fields or edge["edge_id"] != expected_id:
            raise IntegrityGateError("visible edge table is not canonical")
        if not 0 <= edge["source"] < node_count or not 0 <= edge["target"] < node_count:
            raise IntegrityGateError("edge endpoint is outside the world")
        if not 0 <= edge["relation"] < relation_count:
            raise IntegrityGateError("edge relation is outside the vocabulary")
        if not 0 <= edge["query_similarity_ppm"] <= 1_000_000:
            raise IntegrityGateError("edge query similarity is outside the fixed range")
        triple = (edge["source"], edge["target"], edge["relation"])
        if triple in triples:
            raise IntegrityGateError("duplicate structural edge")
        triples.add(triple)
        by_source[edge["source"]].append(edge)
        by_id[expected_id] = edge

    relations = visible.get("query_relations")
    if (
        not isinstance(relations, list)
        or not 2 <= len(relations) <= 6
        or any(
            not isinstance(value, int) or not 0 <= value < relation_count
            for value in relations
        )
    ):
        raise IntegrityGateError("query relation program is invalid")
    start = visible.get("start_node")
    if not isinstance(start, int) or not 0 <= start < node_count:
        raise IntegrityGateError("query start node is invalid")

    # reachable[depth] maps a node at this depth to every edge sequence that
    # finishes the remaining relation suffix. Building it backwards is
    # causally separate from the generator's forward enumerator.
    suffixes: dict[tuple[int, int], list[tuple[int, ...]]] = {
        (len(relations), node): [()] for node in range(node_count)
    }
    for depth in range(len(relations) - 1, -1, -1):
        required_relation = relations[depth]
        for node in range(node_count):
            completions: list[tuple[int, ...]] = []
            for edge in by_source[node]:
                if edge["relation"] != required_relation:
                    continue
                for suffix in suffixes.get((depth + 1, edge["target"]), []):
                    completions.append((edge["edge_id"],) + suffix)
            if completions:
                suffixes[(depth, node)] = sorted(completions)
    routes = suffixes.get((0, start), [])
    if not routes:
        if not allow_disconnected:
            raise IntegrityGateError("query has no complete route")
        return {
            "target_nodes": [],
            "valid_routes": [],
            "teacher_actions": [],
            "abstain": True,
            "gold_assertion_mask": None,
            "greedy_wrong_count": 0,
            "path_step_count": 0,
            "measured_gamma": None,
        }

    teacher: dict[tuple[int, int], set[int]] = defaultdict(set)
    target_nodes: set[int] = set()
    wrong_count = 0
    step_count = 0
    for route in routes:
        node = start
        for depth, edge_id in enumerate(route):
            edge = by_id[edge_id]
            if edge["source"] != node:
                raise IntegrityGateError("oracle route is structurally discontinuous")
            teacher[(node, depth)].add(edge_id)
            maxima = max(
                candidate["query_similarity_ppm"] for candidate in by_source[node]
            )
            winners = [
                candidate["edge_id"]
                for candidate in by_source[node]
                if candidate["query_similarity_ppm"] == maxima
            ]
            if len(winners) != 1:
                raise IntegrityGateError("greedy query similarity has a maximum tie")
            valid_next = {
                candidate_route[depth]
                for candidate_route in routes
                if candidate_route[:depth] == route[:depth]
            }
            if winners[0] not in valid_next:
                wrong_count += 1
            step_count += 1
            node = edge["target"]
        target_nodes.add(node)

    endpoint_masks = {masks[node] for node in target_nodes}
    abstain = len(endpoint_masks) != 1
    return {
        "target_nodes": sorted(target_nodes),
        "valid_routes": [list(route) for route in routes],
        "teacher_actions": [
            {"depth": depth, "node": node, "edge_ids": sorted(edge_ids)}
            for (node, depth), edge_ids in sorted(teacher.items())
        ],
        "abstain": abstain,
        "gold_assertion_mask": None if abstain else next(iter(endpoint_masks)),
        "greedy_wrong_count": wrong_count,
        "path_step_count": step_count,
        "measured_gamma": wrong_count / step_count,
    }
