"""Generator v3.2: distractors that carry their own evidence. Version-additive.

`generator_v3` is untouched; Track P's data stays byte-identical. This module
exists because of a measurement, not a hunch: on v3 data the planted similarity
signal cannot separate a target route from its distractor **at any γ** —
identifiability by promoted-edge ranking is 0.38 at γ = 0 and 0.23 at γ = 0.4, with
ties above 0.61 throughout (`experiments/track_q_v1/diagnostics/gamma_sweep_v3.json`).
Two properties of v3's construction cause it, both mine:

1. **A v3 distractor branches off a target route at a uniform depth**, so it
   shares — and inherits the promoted edges of — the target's prefix. 85 % of them
   branch at depth ≥ L−2.
2. **At the branch node the two targets have two valid continuations and the
   generator promotes exactly one**, so on every episode one target route carries
   an unpromoted edge. A late-branching distractor ties it.

v3.2 removes both, under two config switches that default to v3 behaviour so the
byte-identity test holds:

- `distractor_branch_at_start`: every distractor leaves from the start node
  (branch depth 0). It shares no prefix with either target beyond the start, so
  it inherits nothing. Feasibility bound: the start node holds one target edge
  (the targets share their first edge, since `branch_depth ≥ 1`) plus K
  distractor edges, so `K + 1 ≤ out_degree`; the easy cell at out-degree 3
  admits K ≤ 2.
- `distractor_gamma`: the distractor route's interior nodes are treated as
  *distractor route states* with their own greedy-wrong probability. At such a
  node the distractor's continuation is promoted with probability
  1 − `distractor_gamma`, otherwise a non-distractor edge is. In v3 those nodes
  were hash-uniform (continuation promoted at 1/out-degree), which at
  out-degree 6 is roughly `distractor_gamma` = 0.83 — but tangled with the
  prefix inheritance above. Here the rate is explicit and swept, and the
  choice is made by a rule written before the sweep runs
  (`scripts/read_run_v3_2_evidence_sweep.py`).

Everything else — content rules, planting draws, the uniqueness check that the
complete matching paths are exactly targets ∪ distractors, the mask schedule,
the visible allowlist — is v3's by import. The endpoint masks are unchanged and
still the answer label; v3.2's point is that a path-level signal now exists
beside them, so a model that returns the targets can be shown to have used
evidence rather than the label.
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
    SCHEMA_VERSION_V2,
    SIMILARITY_BASE_FLOOR,
    SIMILARITY_BASE_RANGE,
    SIMILARITY_WINNER_PPM,
    _assign_similarity_v2,
    _fill_out_degree,
    _plant_routes,
    _relation_rules,
    _uniform_choice,
    rule_valid_targets,
)
from .generator_v3 import CELLS_V3, GeneratorV3Config, _plant_distractors, _route_edges
from .seed import derive_bytes, derive_int

DISTRACTOR_GAMMA_GRID = (0.4, 0.6, 0.8, 1.0)


@dataclass(frozen=True)
class GeneratorV32Config(GeneratorV3Config):
    """v3 plus two switches. Both off reproduces v3 byte for byte."""

    distractor_branch_at_start: bool = False
    distractor_gamma: float | None = None

    def validate(self) -> None:
        super().validate()
        if (
            self.distractor_gamma is not None
            and not 0.0 <= self.distractor_gamma <= 1.0
        ):
            raise GenerationError("distractor gamma must lie in [0, 1]")
        if (
            self.distractor_branch_at_start
            and self.distractor_paths + 1 > self.out_degree
        ):
            raise GenerationError(
                "start-node distractors need out_degree >= distractor_paths + 1"
            )

    def label(self) -> str:
        base = super().label()
        if self.distractor_branch_at_start:
            base = f"{base}|b0"
        if self.distractor_gamma is not None:
            base = f"{base}|dg{self.distractor_gamma}"
        return base

    def visible_cell(self) -> str:
        base = super().visible_cell()
        if self.distractor_branch_at_start:
            base = f"{base}-b0"
        if self.distractor_gamma is not None:
            base = f"{base}-dg{int(round(self.distractor_gamma * 10)):02d}"
        return base


def _with(base: GeneratorV3Config, **overrides: Any) -> GeneratorV32Config:
    fields = {
        name: getattr(base, name) for name in GeneratorV3Config.__dataclass_fields__
    }
    fields.update(overrides)
    return GeneratorV32Config(**fields)


CELLS_V32: dict[str, GeneratorV32Config] = {
    **{name: _with(config) for name, config in CELLS_V3.items()},
    **{
        f"{name}-b0-dg{int(round(dg * 10)):02d}": _with(
            CELLS_V3[name], distractor_branch_at_start=True, distractor_gamma=dg
        )
        for name in ("deg3_len6_v8-k1", "deg6_len8_v4_rep-k1")
        for dg in DISTRACTOR_GAMMA_GRID
    },
}


def _plant_distractors_at_start(
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
    """`_plant_distractors` with the branch depth fixed at 0: no shared prefix."""

    used = set(route_a) | set(route_b)
    routes: list[list[int]] = []
    for _ in range(count):
        parent_index = rng.randrange(2)
        route = [(route_a, route_b)[parent_index][0]]
        for depth in range(path_length):
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
    return routes, [0] * count, [0] * count


def _assign_similarity_v3_2(
    *,
    master_seed: bytes,
    config_label: str,
    split: str,
    index: int,
    gamma: float,
    distractor_gamma: float,
    edges: list[dict[str, int]],
    route_edge_ids: list[list[int]],
    distractor_edge_ids: list[list[int]],
) -> None:
    """v2's assignment, plus distractor route states with their own wrong-rate.

    Target route states are exactly v2's. A node that lies on a distractor
    route and on no target route becomes a *distractor route state*: its
    promoted edge is the distractor continuation with probability
    1 − `distractor_gamma`, otherwise a hash-minimum non-distractor edge. Nodes on
    neither stay hash-uniform.
    """

    if gamma not in GAMMA_BUCKETS:
        raise GenerationError(f"gamma is not preregistered: {gamma}")
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    by_id = {edge["edge_id"]: edge for edge in edges}
    for edge in edges:
        base = derive_int(
            master_seed,
            "v2-similarity-base",
            config_label,
            split,
            str(index),
            str(gamma),
            str(edge["edge_id"]),
        )
        edge["query_similarity_ppm"] = (
            SIMILARITY_BASE_FLOOR + base % SIMILARITY_BASE_RANGE
        )
        by_source[edge["source"]].append(edge)

    valid_by_node: dict[int, tuple[int, set[int]]] = {}
    for route in route_edge_ids:
        for depth, edge_id in enumerate(route):
            source = by_id[edge_id]["source"]
            recorded = valid_by_node.setdefault(source, (depth, set()))
            if recorded[0] != depth:
                raise GenerationError("a route node appears at two depths")
            recorded[1].add(edge_id)
    distractor_by_node: dict[int, tuple[int, set[int]]] = {}
    for route in distractor_edge_ids:
        for depth, edge_id in enumerate(route):
            source = by_id[edge_id]["source"]
            if source in valid_by_node:
                continue  # a target route state keeps target semantics
            recorded = distractor_by_node.setdefault(source, (depth, set()))
            recorded[1].add(edge_id)

    threshold = int(gamma * (1 << 64))
    distractor_threshold = int(distractor_gamma * (1 << 64))
    for node in sorted(by_source):
        candidates = by_source[node]
        if node in valid_by_node:
            depth, valid_ids = valid_by_node[node]
            others = [e for e in candidates if e["edge_id"] not in valid_ids]
            if not others:
                raise GenerationError("valid route state has no greedy distractor")
            draw = derive_int(
                master_seed,
                "v2-greedy-wrong",
                config_label,
                split,
                str(index),
                str(gamma),
                str(node),
                str(depth),
            ) & ((1 << 64) - 1)
            eligible = (
                others if draw < threshold else [by_id[v] for v in sorted(valid_ids)]
            )
        elif node in distractor_by_node:
            depth, distractor_ids = distractor_by_node[node]
            others = [e for e in candidates if e["edge_id"] not in distractor_ids]
            if not others:
                raise GenerationError("distractor route state has no alternative")
            draw = derive_int(
                master_seed,
                "v32-distractor-wrong",
                config_label,
                split,
                str(index),
                str(distractor_gamma),
                str(node),
                str(depth),
            ) & ((1 << 64) - 1)
            eligible = (
                others
                if draw < distractor_threshold
                else [by_id[v] for v in sorted(distractor_ids)]
            )
        else:
            eligible = candidates
        winner = min(
            eligible,
            key=lambda edge: derive_int(
                master_seed,
                "v2-similarity-winner",
                config_label,
                split,
                str(index),
                str(gamma),
                str(node),
                str(edge["edge_id"]),
            ),
        )
        winner["query_similarity_ppm"] = SIMILARITY_WINNER_PPM


def generate_episode_v3_2(
    master_seed: bytes,
    *,
    config: GeneratorV32Config,
    split: str,
    index: int,
    count: int,
    gamma: float,
    gold_mask: int | None,
) -> GeneratedEpisode:
    """v3's flow; with both switches off, v3's bytes."""

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

    plant = (
        _plant_distractors_at_start
        if config.distractor_branch_at_start
        else _plant_distractors
    )
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

        distractors = plant(
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
            _route_edges(r, query_relations) for r in (route_a, route_b)
        }
        expected_distractors = {
            _route_edges(r, query_relations) for r in distractor_routes
        }
        if set(candidate_paths) != expected_targets | expected_distractors:
            continue
        raw_edges = sorted(edge_set)
        constructed_routes = [list(path) for path in sorted(expected_targets)]
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
        (e["source"], e["target"], e["relation"]): e["edge_id"] for e in edges
    }
    route_edge_ids = [
        [id_by_tuple[edge] for edge in route] for route in constructed_routes
    ]
    distractor_edge_ids = [
        [id_by_tuple[edge] for edge in _route_edges(route, query_relations)]
        for route in distractor_routes
    ]
    if config.distractor_gamma is None:
        _assign_similarity_v2(
            master_seed=master_seed,
            config_label=label,
            split=split,
            index=index,
            gamma=gamma,
            edges=edges,
            route_edge_ids=route_edge_ids,
        )
    else:
        _assign_similarity_v3_2(
            master_seed=master_seed,
            config_label=label,
            split=split,
            index=index,
            gamma=gamma,
            distractor_gamma=config.distractor_gamma,
            edges=edges,
            route_edge_ids=route_edge_ids,
            distractor_edge_ids=distractor_edge_ids,
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
        edges=edges, route_edge_ids=route_edge_ids, endpoint_masks=endpoint_masks
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
        if config.distractor_gamma is not None:
            hidden["distractor_gamma"] = config.distractor_gamma
    return GeneratedEpisode(
        episode_id=episode_id,
        paired_world_id=paired_world_id,
        visible=visible,
        hidden=hidden,
    )


def generate_split_v3_2(
    master_seed: bytes,
    *,
    config: GeneratorV32Config,
    split: str,
    count: int,
    gamma: float,
) -> Iterator[GeneratedEpisode]:
    labels = _label_schedule(master_seed, split, count)
    for index, gold_mask in enumerate(labels):
        yield generate_episode_v3_2(
            master_seed,
            config=config,
            split=split,
            index=index,
            count=count,
            gamma=gamma,
            gold_mask=gold_mask,
        )
