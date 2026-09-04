"""Generator v3.2: distractors with their own evidence, each property a test that can fail."""

from __future__ import annotations

import hashlib

import pytest

from hippocampus_foundation.phase0.canonical import canonical_sha256
from hippocampus_foundation.read_run.errors import GenerationError
from hippocampus_foundation.read_run.generator import _enumerate_matching_paths
from hippocampus_foundation.read_run.generator_v2 import SIMILARITY_WINNER_PPM
from hippocampus_foundation.read_run.generator_v3 import CELLS_V3, generate_episode_v3
from hippocampus_foundation.read_run.generator_v3_2 import (
    CELLS_V32,
    GeneratorV32Config,
    generate_episode_v3_2,
)

TEST_SEED = hashlib.sha256(b"generator-v3-2-tests").digest()
HARD_B0 = CELLS_V32["deg6_len8_v4_rep-k1-b0-dg10"]
HARD_B0_SOFT = CELLS_V32["deg6_len8_v4_rep-k1-b0-dg06"]
EASY_B0 = CELLS_V32["deg3_len6_v8-k1-b0-dg10"]


def _episodes(config, n, gamma=0.4):
    out = []
    for index in range(n * 3):
        try:
            out.append(
                generate_episode_v3_2(
                    TEST_SEED,
                    config=config,
                    split="test-fixture",
                    index=index,
                    count=n * 3,
                    gamma=gamma,
                    gold_mask=1 + index % 15,
                )
            )
        except GenerationError:
            continue
        if len(out) == n:
            break
    assert out
    return out


def _nodes(episode, edge_ids):
    by_id = {e["edge_id"]: e for e in episode.visible["edges"]}
    return [by_id[edge_ids[0]]["source"]] + [by_id[e]["target"] for e in edge_ids]


@pytest.mark.parametrize("cell", ["deg3_len6_v8-k1", "deg6_len8_v4_rep-k1"])
def test_defaults_reproduce_v3_byte_for_byte(cell):
    """Both switches off: every RNG stream, branch and payload is v3's."""

    v3, v32 = CELLS_V3[cell], CELLS_V32[cell]
    assert v32.label() == v3.label() and v32.visible_cell() == v3.visible_cell()
    compared = 0
    for index in range(12):
        gold = None if index % 4 == 3 else 1 + index % 15
        gamma = (0.0, 0.4)[index % 2]
        try:
            expected = generate_episode_v3(
                TEST_SEED,
                config=v3,
                split="test-fixture",
                index=index,
                count=12,
                gamma=gamma,
                gold_mask=gold,
            )
        except GenerationError:
            with pytest.raises(GenerationError):
                generate_episode_v3_2(
                    TEST_SEED,
                    config=v32,
                    split="test-fixture",
                    index=index,
                    count=12,
                    gamma=gamma,
                    gold_mask=gold,
                )
            continue
        actual = generate_episode_v3_2(
            TEST_SEED,
            config=v32,
            split="test-fixture",
            index=index,
            count=12,
            gamma=gamma,
            gold_mask=gold,
        )
        assert canonical_sha256(actual.visible) == canonical_sha256(expected.visible)
        assert canonical_sha256(actual.hidden) == canonical_sha256(expected.hidden)
        compared += 1
    assert compared >= 4


def test_switches_change_the_label_and_are_validated():
    assert HARD_B0.label().endswith("|k1|b0|dg1.0")
    assert HARD_B0.visible_cell() == "deg6_len8_v4_rep-k1-b0-dg10"
    with pytest.raises(GenerationError):
        GeneratorV32Config(
            cell="x", distractor_paths=1, distractor_gamma=1.5
        ).validate()
    with pytest.raises(GenerationError):
        # out-degree 3 cannot hold one target edge plus three start distractors
        GeneratorV32Config(
            cell="x", distractor_paths=3, distractor_branch_at_start=True
        ).validate()


@pytest.mark.parametrize("config", [EASY_B0, HARD_B0], ids=["easy", "hard"])
def test_distractors_leave_from_the_start_and_share_no_prefix(config):
    for episode in _episodes(config, 8):
        start = episode.visible["start_node"]
        targets = [set(_nodes(episode, r)) for r in episode.hidden["valid_routes"]]
        assert (
            episode.hidden["distractor_branch_depths"] == [0] * config.distractor_paths
        )
        for route in episode.hidden["distractor_routes"]:
            nodes = _nodes(episode, route)
            assert nodes[0] == start
            # nothing beyond the start is shared with either target
            assert not (set(nodes[1:]) & (targets[0] | targets[1]))
        # uniqueness: exactly K + 2 complete matching paths
        by_source: dict[int, list] = {}
        for e in episode.visible["edges"]:
            by_source.setdefault(e["source"], []).append((e["target"], e["relation"]))
        paths = _enumerate_matching_paths(
            by_source, start=start, relations=episode.visible["query_relations"]
        )
        assert len(set(paths)) == config.distractor_paths + 2


def test_distractor_gamma_sets_the_interior_promotion_rate():
    """At dg = 1.0 a distractor's interior continuation is never promoted; at
    dg = 0.6 it is promoted about 40 % of the time. Target rate stays 1 − γ."""

    def rates(config):
        target = [0, 0]
        interior = [0, 0]
        for episode in _episodes(config, 40):
            by_id = {e["edge_id"]: e for e in episode.visible["edges"]}
            route_nodes = set()
            for r in episode.hidden["valid_routes"]:
                route_nodes |= set(_nodes(episode, r))
                for e in r:
                    target[1] += 1
                    target[0] += (
                        by_id[e]["query_similarity_ppm"] == SIMILARITY_WINNER_PPM
                    )
            for r in episode.hidden["distractor_routes"]:
                for e in r:
                    if by_id[e]["source"] in route_nodes:
                        continue  # the start node: a target route state
                    interior[1] += 1
                    interior[0] += (
                        by_id[e]["query_similarity_ppm"] == SIMILARITY_WINNER_PPM
                    )
        return target[0] / target[1], interior[0] / interior[1], interior[1]

    t_hard, d_hard, n_hard = rates(HARD_B0)
    t_soft, d_soft, n_soft = rates(HARD_B0_SOFT)
    assert n_hard >= 60 and n_soft >= 60
    assert 0.45 < t_hard < 0.75 and 0.45 < t_soft < 0.75
    assert d_hard == 0.0, d_hard
    assert 0.25 < d_soft < 0.55, d_soft


def test_promotion_is_still_universal():
    for episode in _episodes(HARD_B0, 6):
        groups: dict[int, int] = {}
        for e in episode.visible["edges"]:
            groups[e["source"]] = groups.get(e["source"], 0) + (
                e["query_similarity_ppm"] == SIMILARITY_WINNER_PPM
            )
        assert set(groups.values()) == {1}


def test_hidden_records_the_distractor_gamma_and_masks_are_unchanged():
    for episode in _episodes(HARD_B0, 4):
        assert episode.hidden["distractor_gamma"] == 1.0
        assert episode.hidden["gold_assertion_mask"] in range(1, 16)
