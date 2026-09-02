"""Deterministic content-rule generator for Track O (v2). Version-additive.

The frozen v1 generator is untouched; this module implements the Track O
requirements G1-G4 (`docs/TRACK_O_DESIGN.md` section 3) and changes exactly
three things about how a world is built:

1. **Leak-free similarity (G1).** v1 promoted one out-edge to the unique
   maximum only at on-route states, so "this node has a 900k out-edge" marked
   the route (`docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md` section 1.5). Here
   *every* node with out-edges gets exactly one promoted out-edge: at a route
   state the winner is a valid route edge with probability 1 - gamma and a
   distractor otherwise (v1's semantics, so `measured_gamma` keeps its
   meaning), and at every other node the winner is a hash-uniform out-edge.
   Any statistic computed from similarity values alone is therefore
   identically distributed on and off the route; the remaining
   similarity-relation correlation at route states is the *intended*
   edge-choice signal that gamma degrades, not a side channel. The rank
   depth of a wrong state widens automatically with out-degree, because the
   valid edge's rank among the unpromoted rest is a base-similarity draw.

2. **Content-rule edges (G2), zero-shot by construction.** Every node carries
   visible content — a tuple of attributes whose count and value range are
   themselves drawn per episode from config bounds — and every relation r
   carries a hidden rule sampled *per episode*: an attribute pair
   `(source_attribute, target_attribute)` plus a compatibility matrix giving,
   for each source value, the non-empty set of compatible target values. An
   edge (u, r, v) may exist iff
   `content(v)[target_attribute] ∈ compatible[content(u)[source_attribute]]`.
   Nothing semantic is fixed across episodes — not the rule instances, not the
   rule family beyond pairwise-attribute compatibility, not the schema shape,
   and not what any relation id means — so the model must infer each
   episode's rules from that episode's observed edges (Cameron's zero-shot
   requirement, `docs/DECISIONS.md`). The bound that keeps this inferable:
   a rule is a V×V table over one attribute pair, observable from a few
   hundred in-episode edges, never a function of the full content tuple.
   Every edge
   in the world satisfies its relation's rule, so the rule is observable from
   the visible edges alone; the rule table itself is hidden truth. Route
   continuations are drawn **uniformly from the rule-valid target set**
   (minus already-used route nodes), which is the unbiased planting the
   insert objective requires; filler edges draw a relation uniformly and then
   a rule-valid target uniformly. The hidden payload records the rule table
   and the per-step valid-set sizes, from which rule-valid attachment sets
   are exactly recomputable — the insert objective never forces a
   regeneration.

3. **Difficulty cells (G3).** Out-degree, path length, relation vocabulary,
   and query-relation repetition are per-cell configuration
   (`GeneratorV2Config`, named registry `CELLS`). Small vocabularies, longer
   paths, higher out-degree and repeats grow the relation-prefix tree; which
   cells actually defeat the computed walker is measured by the O-2 audit,
   never assumed here.

Everything else is v1 verbatim, deliberately: the paired-world two-route
construction with a shared prefix, the uniqueness guarantee that the only
complete query-matching paths are the two planted routes, the 25%-abstain /
15-mask label schedule, the assertion-mask answer machinery,
`_truth_from_constructed_routes`, the gamma-bucket derivation-label
separation (structure labels exclude gamma, so buckets of one world differ
only in similarity and episode id), and the visible/hidden split. Visible
payloads gain `content` per node and a `generator_cell` string, under
`schema_version` 2.0.0.
"""

from __future__ import annotations

import random
from collections import defaultdict
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
from .seed import derive_bytes, derive_int

SCHEMA_VERSION_V2 = "2.0.0"
SIMILARITY_WINNER_PPM = 900_000
SIMILARITY_BASE_FLOOR = 100_000
SIMILARITY_BASE_RANGE = 500_000


@dataclass(frozen=True)
class GeneratorV2Config:
    """One difficulty cell. Frozen; every field enters the derivation labels."""

    cell: str
    out_degree: int = 3
    min_nodes: int = 64
    max_nodes: int = 256
    min_relations: int = 8
    max_relations: int = 16
    min_path_length: int = 2
    max_path_length: int = 6
    allow_query_relation_repeats: bool = False
    min_content_attributes: int = 3
    max_content_attributes: int = 5
    min_content_values: int = 6
    max_content_values: int = 10
    min_rule_fanout: int = 1
    max_rule_fanout: int = 2
    max_generation_attempts: int = 128

    def validate(self) -> None:
        if not self.cell or any(ch.isspace() for ch in self.cell):
            raise GenerationError("cell name must be non-empty without whitespace")
        if self.out_degree < 3:
            raise GenerationError(
                "out-degree below 3 cannot give every route state a distractor"
            )
        if not 2 <= self.min_path_length <= self.max_path_length <= 8:
            raise GenerationError(
                "path length bounds must satisfy 2 <= min <= max <= 8"
            )
        if self.min_nodes < 16 or self.min_nodes > self.max_nodes:
            raise GenerationError("node bounds must satisfy 16 <= min <= max")
        if self.min_relations < 2 or self.min_relations > self.max_relations:
            raise GenerationError("relation bounds must satisfy 2 <= min <= max")
        if (
            not self.allow_query_relation_repeats
            and self.min_relations < self.max_path_length
        ):
            raise GenerationError(
                "without query repeats the relation vocabulary must cover the path"
            )
        if not 1 <= self.min_content_attributes <= self.max_content_attributes:
            raise GenerationError(
                "content attribute bounds must satisfy 1 <= min <= max"
            )
        if not 2 <= self.min_content_values <= self.max_content_values:
            raise GenerationError("content value bounds must satisfy 2 <= min <= max")
        if not 1 <= self.min_rule_fanout <= self.max_rule_fanout:
            raise GenerationError("rule fanout bounds must satisfy 1 <= min <= max")
        if self.max_generation_attempts < 1:
            raise GenerationError("at least one generation attempt is required")

    def label(self) -> str:
        """The exact configuration string entering every derivation label."""

        return (
            f"{self.cell}|d{self.out_degree}|n{self.min_nodes}-{self.max_nodes}"
            f"|r{self.min_relations}-{self.max_relations}"
            f"|l{self.min_path_length}-{self.max_path_length}"
            f"|rep{int(self.allow_query_relation_repeats)}"
            f"|a{self.min_content_attributes}-{self.max_content_attributes}"
            f"|v{self.min_content_values}-{self.max_content_values}"
            f"|f{self.min_rule_fanout}-{self.max_rule_fanout}"
        )


CELLS: dict[str, GeneratorV2Config] = {
    # v1's shape with content rules and the leak fix: the walker-exact sanity
    # rung of the O-2 ladder.
    "deg3_len6_v8": GeneratorV2Config(cell="deg3_len6_v8"),
    # Denser graph, longer paths, small repeated vocabulary: the candidate
    # walker-insufficient rung. Whether it actually is one is measured at O-2.
    "deg6_len8_v4_rep": GeneratorV2Config(
        cell="deg6_len8_v4_rep",
        out_degree=6,
        min_relations=4,
        max_relations=6,
        max_path_length=8,
        allow_query_relation_repeats=True,
        max_generation_attempts=512,
    ),
    # The middle rung.
    "deg4_len8_v6_rep": GeneratorV2Config(
        cell="deg4_len8_v6_rep",
        out_degree=4,
        min_relations=6,
        max_relations=8,
        max_path_length=8,
        allow_query_relation_repeats=True,
        max_generation_attempts=256,
    ),
}


def _uniform_choice(rng: random.Random, values: set[int]) -> int:
    """Uniform draw from a set, deterministic under the seeded rng."""

    if not values:
        raise GenerationError("uniform draw from an empty candidate set")
    return rng.choice(sorted(values))


def _relation_rules(
    rng: random.Random,
    relation_count: int,
    config: GeneratorV2Config,
    *,
    attribute_count: int,
    value_count: int,
) -> list[dict[str, Any]]:
    """Sample one episode's rule table: a compatibility matrix per relation.

    For each relation, an attribute pair and, for every source value, a
    non-empty compatible target-value set of size `rule_fanout` (clamped to
    the episode's value range). Nothing here survives the episode.
    """

    rules: list[dict[str, Any]] = []
    for relation in range(relation_count):
        fanout = min(
            rng.randint(config.min_rule_fanout, config.max_rule_fanout), value_count
        )
        rules.append(
            {
                "relation": relation,
                "source_attribute": rng.randrange(attribute_count),
                "target_attribute": rng.randrange(attribute_count),
                "compatible_target_values": [
                    sorted(rng.sample(range(value_count), fanout))
                    for _source_value in range(value_count)
                ],
            }
        )
    return rules


def rule_valid_targets(
    *,
    source: int,
    relation: int,
    content: list[tuple[int, ...]],
    rules: list[dict[str, Any]],
    nodes_by_attribute_value: list[list[set[int]]],
) -> set[int]:
    """Every node a rule-valid edge (source, relation, ·) may point at."""

    rule = rules[relation]
    source_value = content[source][rule["source_attribute"]]
    targets: set[int] = set()
    for value in rule["compatible_target_values"][source_value]:
        targets |= nodes_by_attribute_value[rule["target_attribute"]][value]
    targets.discard(source)
    return targets


def edge_satisfies_rule(
    edge: tuple[int, int, int],
    *,
    content: list[tuple[int, ...]],
    rules: list[dict[str, Any]],
) -> bool:
    source, target, relation = edge
    rule = rules[relation]
    source_value = content[source][rule["source_attribute"]]
    return (
        content[target][rule["target_attribute"]]
        in rule["compatible_target_values"][source_value]
    )


def _plant_routes(
    rng: random.Random,
    *,
    config: GeneratorV2Config,
    path_length: int,
    query_relations: list[int],
    content: list[tuple[int, ...]],
    rules: list[dict[str, Any]],
    nodes_by_attribute_value: list[list[set[int]]],
) -> tuple[list[int], list[int], int, list[int]] | None:
    """Walk two rule-valid routes with a shared prefix; None when stuck.

    Each continuation is drawn uniformly from the rule-valid target set minus
    the nodes already on either route — the unbiased planting G2 requires.
    Returns (route_a, route_b, branch_depth, valid_set_sizes) where the sizes
    are the candidate-set cardinalities each uniform draw was made from,
    recorded for the planting audit.
    """

    branch_depth = rng.randrange(1, path_length)
    start = rng.randrange(len(content))
    used = {start}
    sizes: list[int] = []

    def extend(route: list[int], from_depth: int, to_depth: int) -> bool:
        for depth in range(from_depth, to_depth):
            candidates = rule_valid_targets(
                source=route[-1],
                relation=query_relations[depth],
                content=content,
                rules=rules,
                nodes_by_attribute_value=nodes_by_attribute_value,
            )
            candidates -= used
            if not candidates:
                return False
            sizes.append(len(candidates))
            chosen = _uniform_choice(rng, candidates)
            route.append(chosen)
            used.add(chosen)
        return True

    common = [start]
    if not extend(common, 0, branch_depth):
        return None
    route_a = list(common)
    if not extend(route_a, branch_depth, path_length):
        return None
    route_b = list(common)
    if not extend(route_b, branch_depth, path_length):
        return None
    return route_a, route_b, branch_depth, sizes


def _fill_out_degree(
    rng: random.Random,
    *,
    config: GeneratorV2Config,
    relation_count: int,
    content: list[tuple[int, ...]],
    rules: list[dict[str, Any]],
    nodes_by_attribute_value: list[list[set[int]]],
    edge_set: set[tuple[int, int, int]],
    by_source: dict[int, list[tuple[int, int]]],
) -> bool:
    """Give every node `out_degree` rule-valid out-edges; False when stuck."""

    node_count = len(content)
    for source in range(node_count):
        tries = 0
        while len(by_source[source]) < config.out_degree:
            tries += 1
            if tries > node_count * relation_count * 4:
                return False
            relation = rng.randrange(relation_count)
            candidates = rule_valid_targets(
                source=source,
                relation=relation,
                content=content,
                rules=rules,
                nodes_by_attribute_value=nodes_by_attribute_value,
            )
            if not candidates:
                continue
            target = _uniform_choice(rng, candidates)
            edge = (source, target, relation)
            if edge in edge_set:
                continue
            edge_set.add(edge)
            by_source[source].append((target, relation))
    return True


def _assign_similarity_v2(
    *,
    master_seed: bytes,
    config_label: str,
    split: str,
    index: int,
    gamma: float,
    edges: list[dict[str, int]],
    route_edge_ids: list[list[int]],
) -> None:
    """G1: base draws everywhere, exactly one promoted winner at every node."""

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

    threshold = int(gamma * (1 << 64))
    for node in sorted(by_source):
        candidates = by_source[node]
        if node in valid_by_node:
            depth, valid_ids = valid_by_node[node]
            distractors = [
                edge for edge in candidates if edge["edge_id"] not in valid_ids
            ]
            if not distractors:
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
                distractors
                if draw < threshold
                else [by_id[value] for value in sorted(valid_ids)]
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


def generate_episode_v2(
    master_seed: bytes,
    *,
    config: GeneratorV2Config,
    split: str,
    index: int,
    count: int,
    gamma: float,
    gold_mask: int | None,
) -> GeneratedEpisode:
    """Generate one content-rule paired-world episode."""

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
        "generator_cell": config.cell,
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
    hidden = {
        "schema_version": SCHEMA_VERSION_V2,
        "record_kind": "read_episode_hidden",
        "episode_id": episode_id,
        "paired_world_id": paired_world_id,
        "split": split,
        "generator_cell": config.cell,
        "requested_gamma": gamma,
        "branch_depth": branch_depth,
        "relation_rules": rules,
        "planting_valid_set_sizes": valid_set_sizes,
        **truth,
    }
    return GeneratedEpisode(
        episode_id=episode_id,
        paired_world_id=paired_world_id,
        visible=visible,
        hidden=hidden,
    )


def generate_split_v2(
    master_seed: bytes,
    *,
    config: GeneratorV2Config,
    split: str,
    count: int,
    gamma: float,
) -> Iterator[GeneratedEpisode]:
    labels = _label_schedule(master_seed, split, count)
    for index, gold_mask in enumerate(labels):
        yield generate_episode_v2(
            master_seed,
            config=config,
            split=split,
            index=index,
            count=count,
            gamma=gamma,
            gold_mask=gold_mask,
        )
