"""Deterministic content-rule generator with planted distractor evidence (v3).

Version-additive: `generator_v2` is untouched and Track O's data stays
byte-identical. This module changes exactly one thing about how a world is
built, and it is the thing the Track P experiment turns on.

**Why distractors.** On v2 data the uniqueness constraint — the only complete
query-matching paths are the two planted routes — keeps every dead end to about
one edge, so relation-following is already the optimal expansion policy: the
blind walker's cost equals the oracle's on 65 % of episodes and a learned stop
would be learning the constant 2. There is nothing for a model to be *selective
about*. v3 plants K further complete, rule-valid, query-matching paths to
non-target endpoints, so that (a) expansion order has room to matter and (b) the
stop and the returned set become decisions, not counts.

**Where a distractor branches.** Each distractor picks a parent target route
(a or b, uniform) and a branch depth `d ∈ [0, L−1]` (uniform), shares the
parent's prefix to depth `d`, then extends by the same uniform rule-valid draws
`_plant_routes` uses, node-disjoint from both targets and from earlier
distractors beyond its branch point. `d = 0` is the start-only case; `d = L−1`
makes the distractor endpoint a *sibling* of a target endpoint, distinguishable
by evidence alone, which is the selective-return test §2.21 asks for.

**What distinguishes a target from a distractor costs no new mechanism.**
`_assign_similarity_v2` is called with the target routes only, so its
`valid_by_node` is the target routes': a distractor edge leaving a route state
is a greedy distractor there (promoted with probability γ, v2's semantics, so
`measured_gamma` keeps its meaning), and a distractor's own interior nodes are
not route states, so their promoted edge is hash-uniform over the group — on the
distractor continuation with probability 1/out-degree, against 1 − γ along a
target route. That gap is the evidential signal, degraded exactly by γ. The
second signal is mask agreement between the two targets; distractor endpoints
draw their mask from `node_rng` like any node, and the resulting 1/15 collision
is a reported noise floor, not suppressed — forcing distractor masks away from
the gold mask would make mask-matching a perfect target identifier and leak
hidden structure into the visible payload.

**The answer changes meaning.** The public rule "all reached endpoints agree →
that mask, else abstain" (`greedy.greedy_predicted_class`) is wrong whenever a
distractor is reached; on v3 the answer requires *identifying* the targets.
`evaluation.score_prediction`'s `proof_valid` already demands that the returned
routes be exactly the target routes, while `coverage.route_complete` only asks
that the examined set cover them — so the cost may include distractors and the
product may not. Neither function changes.

**K = 0 is v2, byte for byte.** `label()` returns v2's label verbatim at K = 0,
the derivation tags stay `"v2-…"`, and `_plant_distractors` consumes no random
draw when K = 0, so every RNG stream and every branch is v2's.
`tests/test_read_run_generator_v3.py` asserts identity on the canonical bytes of
both payloads; that test is what makes copying v2's top-level flow safe.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .errors import GenerationError
from .generator import (
    BUDGET_CANDIDATES,
    GAMMA_BUCKETS,
    GeneratedEpisode,
    _assertions,
    _enumerate_matching_paths,
    _hex_id,
    _label_schedule,
    _rng,
    _truth_from_constructed_routes,
)
from .generator_v2 import (
    CELLS,
    SCHEMA_VERSION_V2,
    GeneratorV2Config,
    _assign_similarity_v2,
    _fill_out_degree,
    _plant_routes,
    _relation_rules,
    _uniform_choice,
    rule_valid_targets,
)
from .seed import derive_bytes


@dataclass(frozen=True)
class GeneratorV3Config(GeneratorV2Config):
    """A v2 cell plus K planted distractor paths. K = 0 is v2 exactly."""

    distractor_paths: int = 0

    def validate(self) -> None:
        super().validate()
        if self.distractor_paths < 0:
            raise GenerationError("distractor path count must be non-negative")

    def label(self) -> str:
        """v2's label verbatim at K = 0; otherwise v2's label with a K suffix."""

        base = super().label()
        if self.distractor_paths == 0:
            return base
        return f"{base}|k{self.distractor_paths}"

    def visible_cell(self) -> str:
        """The `generator_cell` string: the v2 name at K = 0."""

        if self.distractor_paths == 0:
            return self.cell
        return f"{self.cell}-k{self.distractor_paths}"


def _with_distractors(base: GeneratorV2Config, count: int) -> GeneratorV3Config:
    return GeneratorV3Config(
        **{name: getattr(base, name) for name in base.__dataclass_fields__},
        distractor_paths=count,
    )


CELLS_V3: dict[str, GeneratorV3Config] = {
    **{name: _with_distractors(config, 0) for name, config in CELLS.items()},
    **{
        f"{name}-k{count}": _with_distractors(CELLS[name], count)
        for name in ("deg3_len6_v8", "deg6_len8_v4_rep")
        for count in (1, 2, 4)
    },
}


def _plant_distractors(
    rng: random.Random,
    *,
    count: int,
    route_a: list[int],
    route_b: list[int],
    path_length: int,
    query_relations: list[int],
    content: list[tuple[int, ...]],
    rules: list[dict[str, Any]],
    nodes_by_attribute_value: list[list[set[int]]],
) -> tuple[list[list[int]], list[int], list[int]] | None:
    """Plant K distractor routes; None when stuck. Consumes no draw at K = 0.

    Returns (routes as node lists, branch depths, parent indices). Each route
    shares its parent's nodes to its branch depth and is node-disjoint from
    both targets and from earlier distractors beyond it.
    """

    used = set(route_a) | set(route_b)
    routes: list[list[int]] = []
    depths: list[int] = []
    parents: list[int] = []
    for _ in range(count):
        parent_index = rng.randrange(2)
        parent = (route_a, route_b)[parent_index]
        branch = rng.randrange(path_length)
        route = list(parent[: branch + 1])
        for depth in range(branch, path_length):
            candidates = rule_valid_targets(
                source=route[-1],
                relation=query_relations[depth],
                content=content,
                rules=rules,
                nodes_by_attribute_value=nodes_by_attribute_value,
            )
            candidates -= used
            if not candidates:
                return None
            chosen = _uniform_choice(rng, candidates)
            route.append(chosen)
            used.add(chosen)
        routes.append(route)
        depths.append(branch)
        parents.append(parent_index)
    return routes, depths, parents


def _route_edges(
    route: list[int], query_relations: list[int]
) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (route[depth], route[depth + 1], query_relations[depth])
        for depth in range(len(route) - 1)
    )


def generate_episode_v3(
    master_seed: bytes,
    *,
    config: GeneratorV3Config,
    split: str,
    index: int,
    count: int,
    gamma: float,
    gold_mask: int | None,
) -> GeneratedEpisode:
    """Generate one content-rule paired-world episode with K distractor paths.

    v2's flow with one inserted step (`_plant_distractors`, after the targets
    and before `_fill_out_degree`), one widened check (the complete matching
    paths must be exactly targets ∪ distractors) and one attempt-level guard
    (no node may carry more planted edges than the cell's out-degree, since
    `_fill_out_degree` only adds).
    """

    config.validate()
    if split not in {"train", "screen", "holdout", "test-fixture"}:
        raise GenerationError(f"unsupported split: {split}")
    if index < 0 or index >= count:
        raise GenerationError("episode index is outside the split")
    if gamma not in GAMMA_BUCKETS:
        raise GenerationError(f"gamma is not preregistered: {gamma}")
    if gold_mask is not None and gold_mask not in range(1, 16):
        raise GenerationError("gold mask must be one of the 15 non-empty sets")

    label = config.label()
    paired_world_id = _hex_id(
        master_seed, "v2-paired-world", label, split, str(index), prefix="world2"
    )
    episode_id = f"{paired_world_id}-g{int(gamma * 10):02d}"
    structural_rng = _rng(master_seed, "v2-structure", label, split, str(index))
    node_count = structural_rng.randint(config.min_nodes, config.max_nodes)
    relation_count = structural_rng.randint(config.min_relations, config.max_relations)
    path_length = structural_rng.randint(config.min_path_length, config.max_path_length)
    if config.allow_query_relation_repeats:
        query_relations = [
            structural_rng.randrange(relation_count) for _ in range(path_length)
        ]
    else:
        query_relations = structural_rng.sample(range(relation_count), path_length)

    for attempt in range(config.max_generation_attempts):
        attempt_rng = _rng(
            master_seed, "v2-structure-attempt", label, split, str(index), str(attempt)
        )
        attribute_count = attempt_rng.randint(
            config.min_content_attributes, config.max_content_attributes
        )
        value_count = attempt_rng.randint(
            config.min_content_values, config.max_content_values
        )
        content = [
            tuple(attempt_rng.randrange(value_count) for _ in range(attribute_count))
            for _ in range(node_count)
        ]
        rules = _relation_rules(
            attempt_rng,
            relation_count,
            config,
            attribute_count=attribute_count,
            value_count=value_count,
        )
        nodes_by_attribute_value: list[list[set[int]]] = [
            [set() for _ in range(value_count)] for _ in range(attribute_count)
        ]
        for node, values in enumerate(content):
            for attribute, value in enumerate(values):
                nodes_by_attribute_value[attribute][value].add(node)

        planted_routes = _plant_routes(
            attempt_rng,
            config=config,
            path_length=path_length,
            query_relations=query_relations,
            content=content,
            rules=rules,
            nodes_by_attribute_value=nodes_by_attribute_value,
        )
        if planted_routes is None:
            continue
        route_a, route_b, branch_depth, valid_set_sizes = planted_routes

        distractors = _plant_distractors(
            attempt_rng,
            count=config.distractor_paths,
            route_a=route_a,
            route_b=route_b,
            path_length=path_length,
            query_relations=query_relations,
            content=content,
            rules=rules,
            nodes_by_attribute_value=nodes_by_attribute_value,
        )
        if distractors is None:
            continue
        distractor_routes, distractor_depths, distractor_parents = distractors

        planted: list[tuple[int, int, int]] = []
        for route in (route_a, route_b, *distractor_routes):
            planted.extend(_route_edges(route, query_relations))
        planted = list(dict.fromkeys(planted))
        if config.distractor_paths:
            planted_degree = Counter(source for source, _t, _r in planted)
            if max(planted_degree.values()) > config.out_degree:
                continue
        by_source: dict[int, list[tuple[int, int]]] = defaultdict(list)
        edge_set = set(planted)
        for source, target, relation in planted:
            by_source[source].append((target, relation))
        if not _fill_out_degree(
            attempt_rng,
            config=config,
            relation_count=relation_count,
            content=content,
            rules=rules,
            nodes_by_attribute_value=nodes_by_attribute_value,
            edge_set=edge_set,
            by_source=by_source,
        ):
            continue
        candidate_paths = _enumerate_matching_paths(
            by_source, start=route_a[0], relations=query_relations
        )
        expected_targets = {
            _route_edges(route, query_relations) for route in (route_a, route_b)
        }
        expected_distractors = {
            _route_edges(route, query_relations) for route in distractor_routes
        }
        if set(candidate_paths) != expected_targets | expected_distractors:
            continue
        raw_edges = sorted(edge_set)
        constructed_routes = [list(path) for path in sorted(expected_targets)]
        # The parent is recorded by its endpoint node rather than by index:
        # `valid_routes` is sorted by edge id after serialisation, so no index
        # into the planting order survives, and the two endpoints are distinct.
        distractor_parent_endpoints = [
            (route_a, route_b)[parent][-1] for parent in distractor_parents
        ]
        break
    else:
        raise GenerationError("could not construct an unambiguous content-rule world")

    serialization_rng = _rng(
        master_seed, "v2-edge-serialization", label, split, str(index)
    )
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
    distractor_edge_ids = [
        [id_by_tuple[edge] for edge in _route_edges(route, query_relations)]
        for route in distractor_routes
    ]
    _assign_similarity_v2(
        master_seed=master_seed,
        config_label=label,
        split=split,
        index=index,
        gamma=gamma,
        edges=edges,
        route_edge_ids=route_edge_ids,
    )

    node_rng = _rng(master_seed, "v2-node-assertions", label, split, str(index))
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
        master_seed, "v2-router", label, split, str(index), length=16
    ).hex()
    visible = {
        "schema_version": SCHEMA_VERSION_V2,
        "record_kind": "read_episode_visible",
        "generator_cell": config.visible_cell(),
        "router_seed": router_seed,
        "budget_candidates": list(BUDGET_CANDIDATES),
        "node_count": node_count,
        "relation_count": relation_count,
        "content_attribute_count": attribute_count,
        "content_value_count": value_count,
        "start_node": route_a[0],
        "query_relations": query_relations,
        "nodes": [
            {
                "node": node,
                "assertions": _assertions(mask),
                "content": list(content[node]),
            }
            for node, mask in enumerate(node_masks)
        ],
        "edges": edges,
    }
    truth = _truth_from_constructed_routes(
        edges=edges,
        route_edge_ids=route_edge_ids,
        endpoint_masks=endpoint_masks,
    )
    hidden: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION_V2,
        "record_kind": "read_episode_hidden",
        "episode_id": episode_id,
        "paired_world_id": paired_world_id,
        "split": split,
        "generator_cell": config.visible_cell(),
        "requested_gamma": gamma,
        "branch_depth": branch_depth,
        "relation_rules": rules,
        "planting_valid_set_sizes": valid_set_sizes,
        **truth,
    }
    if config.distractor_paths:
        hidden["distractor_routes"] = distractor_edge_ids
        hidden["distractor_endpoints"] = [route[-1] for route in distractor_routes]
        hidden["distractor_branch_depths"] = distractor_depths
        hidden["distractor_parent_endpoints"] = distractor_parent_endpoints
    return GeneratedEpisode(
        episode_id=episode_id,
        paired_world_id=paired_world_id,
        visible=visible,
        hidden=hidden,
    )


def generate_split_v3(
    master_seed: bytes,
    *,
    config: GeneratorV3Config,
    split: str,
    count: int,
    gamma: float,
) -> Iterator[GeneratedEpisode]:
    labels = _label_schedule(master_seed, split, count)
    for index, gold_mask in enumerate(labels):
        yield generate_episode_v3(
            master_seed,
            config=config,
            split=split,
            index=index,
            count=count,
            gamma=gamma,
            gold_mask=gold_mask,
        )
