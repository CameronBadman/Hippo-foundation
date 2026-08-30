"""Deterministic closed-world generator for the preregistered READ run.

This module records construction truth. It deliberately does not import the
independent oracle, whose job is to derive the same answers from visible bytes
through a separate implementation.
"""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import GenerationError
from .seed import derive_bytes, derive_int

SCHEMA_VERSION = "1.0.0"
GAMMA_BUCKETS = (0.0, 0.1, 0.2, 0.3, 0.4)
BUDGET_CANDIDATES = (16, 32, 64, 128)
MODEL_SEEDS = (1729, 2718, 3141)
MIN_NODES = 64
MAX_NODES = 256
MIN_RELATIONS = 8
MAX_RELATIONS = 16
MIN_PATH_LENGTH = 2
MAX_PATH_LENGTH = 6
OUT_DEGREE = 3
ASSERTION_COUNT = 4
MAX_GENERATION_ATTEMPTS = 128
_UNSET = object()


@dataclass(frozen=True)
class GeneratedEpisode:
    episode_id: str
    paired_world_id: str
    visible: dict[str, Any]
    hidden: dict[str, Any]


def _rng(seed: bytes, *parts: str) -> random.Random:
    return random.Random(derive_int(seed, *parts))


def _hex_id(seed: bytes, *parts: str, prefix: str) -> str:
    value = derive_bytes(seed, *parts, length=16).hex()
    return f"{prefix}-{value}"


def _label_schedule(master_seed: bytes, split: str, count: int) -> list[int | None]:
    if count <= 0 or count % 4:
        raise GenerationError("split count must be positive and divisible by four")
    non_abstain = count - count // 4
    if non_abstain % 15:
        raise GenerationError(
            "non-abstain split count must divide evenly across 15 assertion sets"
        )
    segment_lengths = (
        [120_000, 30_000] if split == "train" and count == 150_000 else [count]
    )
    labels: list[int | None] = []
    for segment_index, segment_length in enumerate(segment_lengths):
        segment_non_abstain = segment_length - segment_length // 4
        if segment_length % 4 or segment_non_abstain % 15:
            raise GenerationError("label-schedule segment cannot be exactly stratified")
        segment: list[int | None] = [None] * (segment_length // 4)
        repeats = segment_non_abstain // 15
        segment.extend(mask for mask in range(1, 16) for _ in range(repeats))
        _rng(
            master_seed,
            "label-schedule",
            split,
            str(count),
            str(segment_index),
        ).shuffle(segment)
        labels.extend(segment)
    return labels


def _assertions(mask: int) -> list[int]:
    return [index for index in range(ASSERTION_COUNT) if mask & (1 << index)]


def _enumerate_matching_paths(
    adjacency: dict[int, list[tuple[int, int]]],
    *,
    start: int,
    relations: Sequence[int],
) -> list[tuple[tuple[int, int, int], ...]]:
    """Generator-side path enumerator using recursive edge expansion."""

    results: list[tuple[tuple[int, int, int], ...]] = []

    def visit(node: int, depth: int, path: tuple[tuple[int, int, int], ...]) -> None:
        if depth == len(relations):
            results.append(path)
            return
        relation = relations[depth]
        for target, observed_relation in adjacency[node]:
            if observed_relation == relation:
                visit(target, depth + 1, path + ((node, target, relation),))

    visit(start, 0, ())
    return results


def _choose_route_nodes(
    rng: random.Random, node_count: int, path_length: int
) -> tuple[list[int], list[int], int]:
    # A common prefix plus two divergent suffixes creates two equally valid
    # endpoints without making candidate count an ABSTAIN shortcut.
    # Keep one shared indispensable edge so the preregistered disconnected
    # reasoning (DiRe) control can sever every valid route without changing
    # endpoint-local features.
    branch_depth = rng.randrange(1, path_length)
    required = 1 + branch_depth + 2 * (path_length - branch_depth)
    if required > node_count:
        raise GenerationError("world is too small for two disjoint route suffixes")
    chosen = rng.sample(range(node_count), required)
    common = chosen[: branch_depth + 1]
    cursor = branch_depth + 1
    suffix_length = path_length - branch_depth
    suffix_a = chosen[cursor : cursor + suffix_length]
    cursor += suffix_length
    suffix_b = chosen[cursor : cursor + suffix_length]
    return common + suffix_a, common + suffix_b, branch_depth


def _edge_order_key(router_seed: str, edge: dict[str, int]) -> bytes:
    material = (
        f"{router_seed}:{edge['source']}:{edge['target']}:{edge['relation']}:"
        f"{edge['edge_id']}"
    ).encode()
    return hashlib.sha256(material).digest()


def structural_bfs_pool(visible: dict[str, Any], budget: int) -> list[int]:
    """Expose B edges by a query-similarity-independent structural BFS."""

    if budget not in BUDGET_CANDIDATES:
        raise GenerationError(f"unsupported examined-edge budget: {budget}")
    edges = visible["edges"]
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in edges:
        by_source[edge["source"]].append(edge)
    router_seed = visible["router_seed"]
    for values in by_source.values():
        values.sort(key=lambda edge: _edge_order_key(router_seed, edge))

    queue = [visible["start_node"]]
    queued = {visible["start_node"]}
    expanded: set[int] = set()
    selected: list[int] = []
    seen_edges: set[int] = set()
    while queue and len(selected) < budget:
        node = queue.pop(0)
        if node in expanded:
            continue
        expanded.add(node)
        for edge in by_source[node]:
            edge_id = edge["edge_id"]
            if edge_id not in seen_edges:
                selected.append(edge_id)
                seen_edges.add(edge_id)
                if len(selected) == budget:
                    break
            target = edge["target"]
            if target not in queued:
                queue.append(target)
                queued.add(target)
    if len(selected) != budget:
        raise GenerationError("structural BFS could not expose the exact edge budget")
    return selected


def _assign_similarity(
    *,
    master_seed: bytes,
    split: str,
    index: int,
    gamma: float,
    edges: list[dict[str, int]],
    route_edge_ids: list[list[int]],
) -> None:
    if gamma not in GAMMA_BUCKETS:
        raise GenerationError(f"gamma is not preregistered: {gamma}")
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    by_id = {edge["edge_id"]: edge for edge in edges}
    for edge in edges:
        base = derive_int(
            master_seed,
            "similarity-base",
            split,
            str(index),
            str(gamma),
            str(edge["edge_id"]),
        )
        edge["query_similarity_ppm"] = 100_000 + base % 500_000
        by_source[edge["source"]].append(edge)

    valid_by_state: dict[tuple[int, int], set[int]] = defaultdict(set)
    for route in route_edge_ids:
        for depth, edge_id in enumerate(route):
            valid_by_state[(by_id[edge_id]["source"], depth)].add(edge_id)

    threshold = int(gamma * (1 << 64))
    for (node, depth), valid_ids in sorted(valid_by_state.items()):
        candidates = by_source[node]
        distractors = [edge for edge in candidates if edge["edge_id"] not in valid_ids]
        if not distractors:
            raise GenerationError("valid route state has no greedy distractor")
        draw = derive_int(
            master_seed,
            "greedy-wrong",
            split,
            str(index),
            str(gamma),
            str(node),
            str(depth),
        ) & ((1 << 64) - 1)
        wrong = draw < threshold
        eligible = distractors if wrong else [by_id[value] for value in valid_ids]
        winner = min(
            eligible,
            key=lambda edge: derive_int(
                master_seed,
                "similarity-winner",
                split,
                str(index),
                str(gamma),
                str(node),
                str(depth),
                str(edge["edge_id"]),
            ),
        )
        # All non-winners are below 600k. A single 900k winner makes maximum
        # ties impossible and gives the oracle an exact greedy decision.
        winner["query_similarity_ppm"] = 900_000


def _truth_from_constructed_routes(
    *,
    edges: list[dict[str, int]],
    route_edge_ids: list[list[int]],
    endpoint_masks: list[int],
) -> dict[str, Any]:
    by_id = {edge["edge_id"]: edge for edge in edges}
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in edges:
        by_source[edge["source"]].append(edge)
    teacher: dict[tuple[int, int], set[int]] = defaultdict(set)
    wrong_count = 0
    step_count = 0
    for route in route_edge_ids:
        for depth, edge_id in enumerate(route):
            edge = by_id[edge_id]
            state = (edge["source"], depth)
            teacher[state].add(edge_id)
            top = max(
                by_source[edge["source"]],
                key=lambda item: item["query_similarity_ppm"],
            )
            if top["edge_id"] not in {
                candidate_route[depth]
                for candidate_route in route_edge_ids
                if candidate_route[:depth] == route[:depth]
            }:
                wrong_count += 1
            step_count += 1
    abstain = len(set(endpoint_masks)) != 1
    return {
        "target_nodes": sorted(
            {by_id[route[-1]]["target"] for route in route_edge_ids}
        ),
        "valid_routes": [list(route) for route in sorted(map(tuple, route_edge_ids))],
        "teacher_actions": [
            {"depth": depth, "node": node, "edge_ids": sorted(edge_ids)}
            for (node, depth), edge_ids in sorted(teacher.items())
        ],
        "abstain": abstain,
        "gold_assertion_mask": None if abstain else endpoint_masks[0],
        "greedy_wrong_count": wrong_count,
        "path_step_count": step_count,
        "measured_gamma": wrong_count / step_count,
    }


def generate_episode(
    master_seed: bytes,
    *,
    split: str,
    index: int,
    count: int,
    gamma: float,
    gold_mask: int | None | object = _UNSET,
) -> GeneratedEpisode:
    """Generate one paired-world episode and its separated construction truth."""

    if split not in {"train", "screen", "holdout", "test-fixture"}:
        raise GenerationError(f"unsupported split: {split}")
    if index < 0 or index >= count:
        raise GenerationError("episode index is outside the split")
    if gamma not in GAMMA_BUCKETS:
        raise GenerationError(f"gamma is not preregistered: {gamma}")
    if gold_mask is _UNSET:
        gold_mask = _label_schedule(master_seed, split, count)[index]
    if gold_mask is not None and not isinstance(gold_mask, int):
        raise GenerationError("gold mask has an invalid type")
    if gold_mask is not None and gold_mask not in range(1, 16):
        raise GenerationError("gold mask must be one of the 15 non-empty sets")

    paired_world_id = _hex_id(
        master_seed, "paired-world", split, str(index), prefix="world"
    )
    episode_id = f"{paired_world_id}-g{int(gamma * 10):02d}"
    structural_rng = _rng(master_seed, "structure", split, str(index))
    node_count = structural_rng.randint(MIN_NODES, MAX_NODES)
    relation_count = structural_rng.randint(MIN_RELATIONS, MAX_RELATIONS)
    path_length = structural_rng.randint(MIN_PATH_LENGTH, MAX_PATH_LENGTH)
    query_relations = structural_rng.sample(range(relation_count), path_length)

    route_a: list[int]
    route_b: list[int]
    branch_depth: int
    raw_edges: list[tuple[int, int, int]]
    constructed_routes: list[list[tuple[int, int, int]]]
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        attempt_rng = _rng(
            master_seed, "structure-attempt", split, str(index), str(attempt)
        )
        route_a, route_b, branch_depth = _choose_route_nodes(
            attempt_rng, node_count, path_length
        )
        planted: list[tuple[int, int, int]] = []
        for route in (route_a, route_b):
            planted.extend(
                (route[depth], route[depth + 1], query_relations[depth])
                for depth in range(path_length)
            )
        planted = list(dict.fromkeys(planted))
        by_source: dict[int, list[tuple[int, int]]] = defaultdict(list)
        edge_set = set(planted)
        for source, target, relation in planted:
            by_source[source].append((target, relation))
        failed = False
        for source in range(node_count):
            tries = 0
            while len(by_source[source]) < OUT_DEGREE:
                tries += 1
                if tries > node_count * relation_count * 4:
                    failed = True
                    break
                target = attempt_rng.randrange(node_count)
                relation = attempt_rng.randrange(relation_count)
                edge = (source, target, relation)
                if target == source or edge in edge_set:
                    continue
                edge_set.add(edge)
                by_source[source].append((target, relation))
            if failed:
                break
        if failed:
            continue
        candidate_paths = _enumerate_matching_paths(
            by_source, start=route_a[0], relations=query_relations
        )
        expected_paths = {
            tuple(
                (route[depth], route[depth + 1], query_relations[depth])
                for depth in range(path_length)
            )
            for route in (route_a, route_b)
        }
        if set(candidate_paths) != expected_paths:
            continue
        raw_edges = sorted(edge_set)
        constructed_routes = [list(path) for path in sorted(expected_paths)]
        break
    else:
        raise GenerationError("could not construct an unambiguous paired world")

    serialization_rng = _rng(master_seed, "edge-serialization", split, str(index))
    serialization_rng.shuffle(raw_edges)
    edges = [
        {
            "edge_id": edge_id,
            "source": source,
            "target": target,
            "relation": relation,
            "query_similarity_ppm": 0,
        }
        for edge_id, (source, target, relation) in enumerate(raw_edges)
    ]
    id_by_tuple = {
        (edge["source"], edge["target"], edge["relation"]): edge["edge_id"]
        for edge in edges
    }
    route_edge_ids = [
        [id_by_tuple[edge] for edge in route] for route in constructed_routes
    ]
    _assign_similarity(
        master_seed=master_seed,
        split=split,
        index=index,
        gamma=gamma,
        edges=edges,
        route_edge_ids=route_edge_ids,
    )

    node_rng = _rng(master_seed, "node-assertions", split, str(index))
    node_masks = [node_rng.randint(1, 15) for _ in range(node_count)]
    endpoint_nodes = [route_a[-1], route_b[-1]]
    if gold_mask is None:
        first = node_rng.randint(1, 15)
        second = node_rng.randint(1, 14)
        if second >= first:
            second += 1
        endpoint_masks = [first, second]
    else:
        endpoint_masks = [gold_mask, gold_mask]
    for node, mask in zip(endpoint_nodes, endpoint_masks, strict=True):
        node_masks[node] = mask

    router_seed = derive_bytes(
        master_seed, "router", split, str(index), length=16
    ).hex()
    visible = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "read_episode_visible",
        "router_seed": router_seed,
        "budget_candidates": list(BUDGET_CANDIDATES),
        "node_count": node_count,
        "relation_count": relation_count,
        "start_node": route_a[0],
        "query_relations": query_relations,
        "nodes": [
            {"node": node, "assertions": _assertions(mask)}
            for node, mask in enumerate(node_masks)
        ],
        "edges": edges,
    }
    truth = _truth_from_constructed_routes(
        edges=edges,
        route_edge_ids=route_edge_ids,
        endpoint_masks=endpoint_masks,
    )
    hidden = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "read_episode_hidden",
        "episode_id": episode_id,
        "paired_world_id": paired_world_id,
        "split": split,
        "requested_gamma": gamma,
        "branch_depth": branch_depth,
        **truth,
    }
    return GeneratedEpisode(
        episode_id=episode_id,
        paired_world_id=paired_world_id,
        visible=visible,
        hidden=hidden,
    )


def generate_split(
    master_seed: bytes,
    *,
    split: str,
    count: int,
    gamma: float,
) -> Iterator[GeneratedEpisode]:
    labels = _label_schedule(master_seed, split, count)
    for index, gold_mask in enumerate(labels):
        yield generate_episode(
            master_seed,
            split=split,
            index=index,
            count=count,
            gamma=gamma,
            gold_mask=gold_mask,
        )
