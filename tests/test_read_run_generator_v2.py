"""Track O generator v2: the G1-G4 requirements, each held by a test.

Nothing here touches the frozen v1 generator. The cells exercised are the
registry's; the hard cell is used sparingly because its uniqueness rejections
make it slow by design.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter

import pytest

from hippocampus_foundation.read_run.coverage import (
    relation_prefix_tree,
    route_coverage,
)
from hippocampus_foundation.read_run.errors import GenerationError
from hippocampus_foundation.read_run.gates import _structural_projection
from hippocampus_foundation.read_run.generator import _enumerate_matching_paths
from hippocampus_foundation.read_run.generator_v2 import (
    CELLS,
    SIMILARITY_WINNER_PPM,
    GeneratorV2Config,
    _uniform_choice,
    edge_satisfies_rule,
    generate_episode_v2,
    generate_split_v2,
    rule_valid_targets,
)

TEST_SEED = hashlib.sha256(b"generator-v2-tests").digest()
FAST = CELLS["deg3_len6_v8"]
MID = CELLS["deg4_len8_v6_rep"]
HARD = CELLS["deg6_len8_v4_rep"]


def _episode(config=FAST, index=0, gamma=0.0, gold_mask=5, count=64):
    return generate_episode_v2(
        TEST_SEED,
        config=config,
        split="test-fixture",
        index=index,
        count=count,
        gamma=gamma,
        gold_mask=gold_mask,
    )


def _episodes(config, n, gamma=0.0):
    out = []
    for index in range(n):
        try:
            out.append(
                _episode(config, index=index, gamma=gamma, gold_mask=1 + index % 15)
            )
        except GenerationError:
            continue
    assert out, "every generation attempt failed"
    return out


def test_generation_is_deterministic_and_config_sensitive():
    first = _episode()
    second = _episode()
    assert first.visible == second.visible and first.hidden == second.hidden
    other = _episode(config=MID)
    assert other.visible != first.visible
    assert other.paired_world_id != first.paired_world_id


def test_every_edge_satisfies_its_relations_episode_local_rule():
    for episode in _episodes(FAST, 8) + _episodes(MID, 4):
        content = [tuple(node["content"]) for node in episode.visible["nodes"]]
        rules = episode.hidden["relation_rules"]
        attributes = episode.visible["content_attribute_count"]
        values = episode.visible["content_value_count"]
        assert all(
            len(node["content"]) == attributes
            and all(0 <= value < values for value in node["content"])
            for node in episode.visible["nodes"]
        )
        for edge in episode.visible["edges"]:
            assert edge_satisfies_rule(
                (edge["source"], edge["target"], edge["relation"]),
                content=content,
                rules=rules,
            )


def test_rules_and_schema_are_episode_local():
    episodes = _episodes(FAST, 12)
    rule_tables = {str(episode.hidden["relation_rules"]) for episode in episodes}
    shapes = {
        (
            episode.visible["content_attribute_count"],
            episode.visible["content_value_count"],
        )
        for episode in episodes
    }
    assert len(rule_tables) == len(episodes), "a rule table repeated across episodes"
    assert len(shapes) > 1, "the content schema never varied"


def test_only_the_two_planted_routes_match_the_query():
    for episode in _episodes(FAST, 8):
        adjacency: dict[int, list[tuple[int, int]]] = {}
        for edge in episode.visible["edges"]:
            adjacency.setdefault(edge["source"], []).append(
                (edge["target"], edge["relation"])
            )
        adjacency.setdefault(episode.visible["start_node"], [])
        paths = _enumerate_matching_paths(
            adjacency,
            start=episode.visible["start_node"],
            relations=episode.visible["query_relations"],
        )
        assert len(set(paths)) == len(episode.hidden["valid_routes"]) == 2
        coverage = route_coverage(
            episode, [edge["edge_id"] for edge in episode.visible["edges"]]
        )
        assert coverage["route_complete"]
        assert not coverage["reached_outside_targets"]


def test_every_node_has_exactly_one_promoted_out_edge():
    for gamma in (0.0, 0.4):
        for episode in _episodes(FAST, 6, gamma=gamma):
            winners = Counter(
                edge["source"]
                for edge in episode.visible["edges"]
                if edge["query_similarity_ppm"] == SIMILARITY_WINNER_PPM
            )
            assert set(winners.values()) == {1}
            assert len(winners) == episode.visible["node_count"]


def _rank_auc(positives, negatives):
    both = sorted([(v, 1) for v in positives] + [(v, 0) for v in negatives])
    rank_sum, rank, i = 0.0, 1, 0
    while i < len(both):
        j = i
        while j < len(both) and both[j][0] == both[i][0]:
            j += 1
        average = (2 * rank + (j - i) - 1) / 2
        rank_sum += average * sum(1 for k in range(i, j) if both[k][1] == 1)
        rank += j - i
        i = j
    n1, n0 = len(positives), len(negatives)
    return (rank_sum - n1 * (n1 + 1) / 2) / (n1 * n0)


@pytest.mark.parametrize("gamma", [0.0, 0.4])
def test_similarity_statistics_do_not_identify_route_nodes(gamma):
    """G1: any per-node statistic of similarity values alone is uninformative."""

    max_pos, max_neg, mean_pos, mean_neg = [], [], [], []
    for episode in _episodes(FAST, 120, gamma=gamma):
        on_route = {
            node
            for route in episode.hidden["valid_routes"]
            for edge_id in route
            for node in (episode.visible["edges"][edge_id]["source"],)
        }
        per_node: dict[int, list[int]] = {}
        for edge in episode.visible["edges"]:
            per_node.setdefault(edge["source"], []).append(edge["query_similarity_ppm"])
        for node, values in per_node.items():
            bucket_max = max_pos if node in on_route else max_neg
            bucket_mean = mean_pos if node in on_route else mean_neg
            bucket_max.append(max(values))
            bucket_mean.append(sum(values) / len(values))
    assert 0.45 <= _rank_auc(max_pos, max_neg) <= 0.55
    assert 0.45 <= _rank_auc(mean_pos, mean_neg) <= 0.55


def test_route_planting_is_uniform_over_the_valid_set():
    rng = random.Random(7)
    counts = Counter(
        _uniform_choice(rng, {3, 11, 4, 25, 9, 17, 6}) for _ in range(14_000)
    )
    assert set(counts) == {3, 4, 6, 9, 11, 17, 25}
    for value in counts.values():
        assert 1_700 <= value <= 2_300, counts


def test_route_continuations_are_rule_valid_and_node_disjoint():
    for episode in _episodes(MID, 6):
        content = [tuple(node["content"]) for node in episode.visible["nodes"]]
        rules = episode.hidden["relation_rules"]
        by_attribute: list[list[set[int]]] = [
            [set() for _ in range(episode.visible["content_value_count"])]
            for _ in range(episode.visible["content_attribute_count"])
        ]
        for node, values in enumerate(content):
            for attribute, value in enumerate(values):
                by_attribute[attribute][value].add(node)
        edges = episode.visible["edges"]
        seen: set[int] = set()
        for route in episode.hidden["valid_routes"]:
            for depth, edge_id in enumerate(route):
                edge = edges[edge_id]
                assert edge["relation"] == episode.visible["query_relations"][depth]
                assert edge["target"] in rule_valid_targets(
                    source=edge["source"],
                    relation=edge["relation"],
                    content=content,
                    rules=rules,
                    nodes_by_attribute_value=by_attribute,
                )
            nodes = [edges[route[0]]["source"]] + [
                edges[edge_id]["target"] for edge_id in route
            ]
            assert len(set(nodes)) == len(nodes)
            seen |= set(nodes[1:])
        sizes = episode.hidden["planting_valid_set_sizes"]
        assert len(sizes) >= len(episode.hidden["valid_routes"][0])
        assert all(size >= 1 for size in sizes)


def test_gamma_zero_has_no_greedy_wrong_states_and_gamma_is_measured():
    wrong = steps = 0
    for episode in _episodes(FAST, 10, gamma=0.0):
        assert episode.hidden["greedy_wrong_count"] == 0
    for episode in _episodes(FAST, 25, gamma=0.4):
        wrong += episode.hidden["greedy_wrong_count"]
        steps += episode.hidden["path_step_count"]
    assert 0.25 <= wrong / steps <= 0.55


def test_gamma_buckets_share_structure_and_differ_only_in_similarity():
    low = _episode(gamma=0.0)
    high = _episode(gamma=0.4)
    assert _structural_projection(low.visible) == _structural_projection(high.visible)
    assert low.visible != high.visible
    assert low.paired_world_id == high.paired_world_id
    assert low.episode_id != high.episode_id


def test_query_repeats_only_where_the_cell_allows_them():
    assert all(
        len(set(episode.visible["query_relations"]))
        == len(episode.visible["query_relations"])
        for episode in _episodes(FAST, 10)
    )
    repeated = any(
        len(set(episode.visible["query_relations"]))
        < len(episode.visible["query_relations"])
        for episode in _episodes(HARD, 8)
    )
    assert repeated, "the repeat cell never produced a repeated query relation"


def test_prefix_trees_grow_on_the_harder_cells():
    fast = sorted(len(relation_prefix_tree(e.visible)) for e in _episodes(FAST, 12))
    mid = sorted(len(relation_prefix_tree(e.visible)) for e in _episodes(MID, 12))
    assert mid[len(mid) // 2] > fast[len(fast) // 2]


def test_split_schedule_keeps_the_v1_abstain_and_mask_stratification():
    episodes = list(
        generate_split_v2(
            TEST_SEED, config=FAST, split="test-fixture", count=20, gamma=0.0
        )
    )
    assert len(episodes) == 20
    abstain = [episode for episode in episodes if episode.hidden["abstain"]]
    assert len(abstain) == 5
    for episode in abstain:
        assert episode.hidden["gold_assertion_mask"] is None
    for episode in episodes:
        if not episode.hidden["abstain"]:
            assert episode.hidden["gold_assertion_mask"] in range(1, 16)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"out_degree": 2},
        {"min_rule_fanout": 0},
        {"min_content_values": 1, "max_content_values": 1},
        {"max_path_length": 9},
        {
            "min_relations": 4,
            "max_relations": 4,
            "allow_query_relation_repeats": False,
            "max_path_length": 6,
        },
        {"cell": "has space"},
    ],
)
def test_invalid_configurations_are_refused(kwargs):
    base = {"cell": "bad"}
    base.update(kwargs)
    with pytest.raises(GenerationError):
        GeneratorV2Config(**base).validate()


def test_frozen_v1_generator_is_untouched_by_importing_v2():
    from hippocampus_foundation.read_run import generator

    assert generator.SCHEMA_VERSION == "1.0.0"
    assert generator.OUT_DEGREE == 3
