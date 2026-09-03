"""Generator v3: distractor evidence, each property held by a test that can fail.

The first test is the one that makes the module safe: v3 copies v2's top-level
flow, and K = 0 must reproduce v2 on the canonical bytes of both payloads.
"""

from __future__ import annotations

import hashlib
from collections import Counter

import pytest

from hippocampus_foundation.phase0.canonical import canonical_sha256
from hippocampus_foundation.read_run.coverage import (
    reachable_endpoints,
    route_coverage_v3,
)
from hippocampus_foundation.read_run.errors import GenerationError
from hippocampus_foundation.read_run.generator import _enumerate_matching_paths
from hippocampus_foundation.read_run.generator_v2 import (
    CELLS,
    SIMILARITY_WINNER_PPM,
    edge_satisfies_rule,
    generate_episode_v2,
)
from hippocampus_foundation.read_run.generator_v3 import (
    CELLS_V3,
    GeneratorV3Config,
    generate_episode_v3,
    generate_split_v3,
)

TEST_SEED = hashlib.sha256(b"generator-v3-tests").digest()
EASY_K2 = CELLS_V3["deg3_len6_v8-k2"]
HARD_K2 = CELLS_V3["deg6_len8_v4_rep-k2"]


def _episode(config, index=0, gamma=0.4, gold_mask=5, count=64):
    return generate_episode_v3(
        TEST_SEED,
        config=config,
        split="test-fixture",
        index=index,
        count=count,
        gamma=gamma,
        gold_mask=gold_mask,
    )


def _episodes(config, n, gamma=0.4, gold_mask_of=lambda i: 1 + i % 15):
    out = []
    for index in range(n):
        try:
            out.append(
                _episode(
                    config, index=index, gamma=gamma, gold_mask=gold_mask_of(index)
                )
            )
        except GenerationError:
            continue
    assert out, "every generation attempt failed"
    return out


def _node_route(episode, edge_ids):
    by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}
    nodes = [by_id[edge_ids[0]]["source"]]
    nodes.extend(by_id[edge_id]["target"] for edge_id in edge_ids)
    return nodes


# --- K = 0 is v2 ---------------------------------------------------------------


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_k0_reproduces_v2_byte_for_byte(cell):
    """Every RNG stream, branch and payload at K = 0 is v2's, including failures."""

    v2 = CELLS[cell]
    v3 = CELLS_V3[cell]
    assert v3.distractor_paths == 0
    assert v3.label() == v2.label()
    compared = 0
    for index in range(12):
        gold_mask = None if index % 4 == 3 else 1 + index % 15
        gamma = (0.0, 0.4, 0.8)[index % 3]
        try:
            expected = generate_episode_v2(
                TEST_SEED,
                config=v2,
                split="test-fixture",
                index=index,
                count=12,
                gamma=gamma,
                gold_mask=gold_mask,
            )
        except GenerationError:
            with pytest.raises(GenerationError):
                generate_episode_v3(
                    TEST_SEED,
                    config=v3,
                    split="test-fixture",
                    index=index,
                    count=12,
                    gamma=gamma,
                    gold_mask=gold_mask,
                )
            continue
        actual = generate_episode_v3(
            TEST_SEED,
            config=v3,
            split="test-fixture",
            index=index,
            count=12,
            gamma=gamma,
            gold_mask=gold_mask,
        )
        assert canonical_sha256(actual.visible) == canonical_sha256(expected.visible)
        assert canonical_sha256(actual.hidden) == canonical_sha256(expected.hidden)
        assert actual.episode_id == expected.episode_id
        compared += 1
    assert compared >= 4


def test_k_changes_the_world_and_the_label():
    base = CELLS_V3["deg3_len6_v8"]
    assert EASY_K2.label() == base.label() + "|k2"
    assert EASY_K2.visible_cell() == "deg3_len6_v8-k2"
    assert base.visible_cell() == "deg3_len6_v8"
    a = _episode(base)
    b = _episode(EASY_K2)
    assert a.paired_world_id != b.paired_world_id
    assert b.visible["generator_cell"] == "deg3_len6_v8-k2"
    with pytest.raises(GenerationError):
        GeneratorV3Config(cell="x", distractor_paths=-1).validate()


# --- distractor structure ----------------------------------------------------


@pytest.mark.parametrize("config", [EASY_K2, HARD_K2], ids=["easy", "hard"])
def test_distractors_are_complete_valid_matching_and_disjoint(config):
    for episode in _episodes(config, 10):
        visible, hidden = episode.visible, episode.hidden
        length = len(visible["query_relations"])
        content = [tuple(node["content"]) for node in visible["nodes"]]
        rules = hidden["relation_rules"]
        by_id = {edge["edge_id"]: edge for edge in visible["edges"]}
        targets = set(hidden["target_nodes"])
        target_nodes = [
            set(_node_route(episode, route)) for route in hidden["valid_routes"]
        ]
        assert len(hidden["distractor_routes"]) == config.distractor_paths
        assert len(hidden["distractor_endpoints"]) == config.distractor_paths
        route_by_endpoint = {
            _node_route(episode, route)[-1]: _node_route(episode, route)
            for route in hidden["valid_routes"]
        }
        earlier: list[tuple[list[int], int]] = []
        for route, depth, parent_endpoint, endpoint in zip(
            hidden["distractor_routes"],
            hidden["distractor_branch_depths"],
            hidden["distractor_parent_endpoints"],
            hidden["distractor_endpoints"],
            strict=True,
        ):
            assert len(route) == length
            nodes = _node_route(episode, route)
            assert nodes[0] == visible["start_node"]
            assert nodes[-1] == endpoint
            assert endpoint not in targets
            for position, edge_id in enumerate(route):
                edge = by_id[edge_id]
                assert edge["relation"] == visible["query_relations"][position]
                assert edge_satisfies_rule(
                    (edge["source"], edge["target"], edge["relation"]),
                    content=content,
                    rules=rules,
                )
            # Shares the parent's prefix to the branch depth, then diverges
            # from both targets and from every earlier distractor.
            assert parent_endpoint in targets
            parent_nodes = route_by_endpoint[parent_endpoint]
            assert nodes[: depth + 1] == parent_nodes[: depth + 1]
            beyond = set(nodes[depth + 1 :])
            assert not beyond & (target_nodes[0] | target_nodes[1])
            for other_nodes, _other_depth in earlier:
                assert not beyond & set(other_nodes)
            earlier.append((nodes, depth))


@pytest.mark.parametrize("config", [EASY_K2, HARD_K2], ids=["easy", "hard"])
def test_exactly_k_plus_two_complete_matching_paths(config):
    for episode in _episodes(config, 8):
        visible, hidden = episode.visible, episode.hidden
        by_source: dict[int, list[tuple[int, int]]] = {}
        for edge in visible["edges"]:
            by_source.setdefault(edge["source"], []).append(
                (edge["target"], edge["relation"])
            )
        paths = _enumerate_matching_paths(
            by_source, start=visible["start_node"], relations=visible["query_relations"]
        )
        assert len(set(paths)) == config.distractor_paths + 2
        endpoints = reachable_endpoints(
            visible, [edge["edge_id"] for edge in visible["edges"]]
        )
        assert endpoints == set(hidden["target_nodes"]) | set(
            hidden["distractor_endpoints"]
        )


def test_branch_depths_span_start_and_sibling_and_degree_is_respected():
    depths: Counter[int] = Counter()
    lengths = set()
    for episode in _episodes(EASY_K2, 40):
        length = len(episode.visible["query_relations"])
        lengths.add(length)
        for depth in episode.hidden["distractor_branch_depths"]:
            depths[depth] += 1
            assert 0 <= depth < length
        degree = Counter(edge["source"] for edge in episode.visible["edges"])
        assert max(degree.values()) == EASY_K2.out_degree
        assert min(degree.values()) == EASY_K2.out_degree
    assert depths[0] > 0, "the start-only case never occurred"
    assert any(depths[length - 1] > 0 for length in lengths), (
        "the sibling-endpoint case never occurred"
    )


# --- evidence ----------------------------------------------------------------


def test_promotion_is_universal_and_weaker_on_distractors():
    """Exactly one promoted edge per node; on a distractor's interior the
    promoted edge is the continuation at ~1/out-degree, not 1 − γ."""

    on_target = Counter()
    on_distractor = Counter()
    expected_distractor = 0.0
    episodes = [(EASY_K2, episode) for episode in _episodes(EASY_K2, 60, gamma=0.4)] + [
        (HARD_K2, episode) for episode in _episodes(HARD_K2, 24, gamma=0.4)
    ]
    for config, episode in episodes:
        visible, hidden = episode.visible, episode.hidden
        by_source: dict[int, list[dict]] = {}
        for edge in visible["edges"]:
            by_source.setdefault(edge["source"], []).append(edge)
        for group in by_source.values():
            assert (
                sum(
                    edge["query_similarity_ppm"] == SIMILARITY_WINNER_PPM
                    for edge in group
                )
                == 1
            )
        by_id = {edge["edge_id"]: edge for edge in visible["edges"]}
        for route in hidden["valid_routes"]:
            for edge_id in route:
                on_target["steps"] += 1
                on_target["promoted"] += (
                    by_id[edge_id]["query_similarity_ppm"] == SIMILARITY_WINNER_PPM
                )
        route_nodes = set()
        for route in hidden["valid_routes"]:
            route_nodes |= set(_node_route(episode, route))
        for route in hidden["distractor_routes"]:
            for edge_id in route:
                if by_id[edge_id]["source"] in route_nodes:
                    continue  # a route state: v2's gamma semantics apply there
                on_distractor["steps"] += 1
                expected_distractor += 1.0 / config.out_degree
                on_distractor["promoted"] += (
                    by_id[edge_id]["query_similarity_ppm"] == SIMILARITY_WINNER_PPM
                )
    target_rate = on_target["promoted"] / on_target["steps"]
    distractor_rate = on_distractor["promoted"] / on_distractor["steps"]
    expected_distractor /= on_distractor["steps"]
    assert on_distractor["steps"] >= 100
    # 1 − γ = 0.6 on the target routes; 1/out-degree on distractor interiors
    # (a third on the easy cell, a sixth on the hard one), pooled here.
    assert 0.45 < target_rate < 0.75, target_rate
    assert abs(distractor_rate - expected_distractor) < 0.12, (
        distractor_rate,
        expected_distractor,
    )
    assert target_rate - distractor_rate > 0.15


def test_distractor_masks_are_not_steered_away_from_gold():
    """The 1/15 collision is a reported noise floor, not a leak in either direction."""

    collisions = 0
    total = 0
    for episode in _episodes(EASY_K2, 40, gold_mask_of=lambda i: 1 + i % 15):
        masks = {
            node["node"]: sum(1 << i for i in node["assertions"])
            for node in episode.visible["nodes"]
        }
        gold = episode.hidden["gold_assertion_mask"]
        for endpoint in episode.hidden["distractor_endpoints"]:
            total += 1
            collisions += masks[endpoint] == gold
    assert total >= 60
    # Binomial(total, 1/15): zero collisions would itself be suspicious.
    assert 0 < collisions < 0.25 * total


# --- coverage ----------------------------------------------------------------


def test_route_coverage_v3_counts_distractors_and_rejects_strangers():
    episode = _episodes(EASY_K2, 6)[0]
    all_ids = [edge["edge_id"] for edge in episode.visible["edges"]]
    row = route_coverage_v3(episode, all_ids)
    assert row["route_complete"]
    assert row["distractor_endpoints_reached"] == sorted(
        episode.hidden["distractor_endpoints"]
    )
    assert row["distractor_endpoint_count"] == EASY_K2.distractor_paths
    # Only the target routes: complete, no distractor reached.
    target_only = [
        edge_id for route in episode.hidden["valid_routes"] for edge_id in route
    ]
    row = route_coverage_v3(episode, target_only)
    assert row["route_complete"] and row["distractor_endpoints_reached"] == []
    # A stranger endpoint is still a falsified premise.
    forged = GeneratedEpisodeStub(episode)
    forged.hidden["distractor_endpoints"] = []
    with pytest.raises(ValueError, match="neither a target nor a planted"):
        route_coverage_v3(forged, all_ids)


class GeneratedEpisodeStub:
    """A shallow copy whose hidden record can be altered for a negative test."""

    def __init__(self, episode):
        self.episode_id = episode.episode_id
        self.paired_world_id = episode.paired_world_id
        self.visible = episode.visible
        self.hidden = dict(episode.hidden)


def test_split_generation_follows_the_label_schedule():
    episodes = list(
        generate_split_v3(
            TEST_SEED, config=EASY_K2, split="test-fixture", count=20, gamma=0.4
        )
    )
    # 20 is the smallest count the label schedule accepts: divisible by four,
    # with the three-quarters non-abstain share dividing across 15 masks.
    assert len(episodes) == 20
    assert {episode.hidden["split"] for episode in episodes} == {"test-fixture"}
    assert len({episode.episode_id for episode in episodes}) == 20
    assert sum(episode.hidden["abstain"] for episode in episodes) == 5
