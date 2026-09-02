"""The model-free ladder is the bar Track O is read against, so it is pinned.

These tests fix the properties the O-4 outcome table depends on: that each
policy is deterministic and budget-respecting, that the hybrid is the coverage
leader while the blind walker is the precision leader (so the frontier really
has two members and no single baseline), that gamma degrades exactly the
policies it should and leaves the blind walker alone, and that the oracle floor
bounds them all.
"""

from __future__ import annotations

import hashlib

import pytest

from hippocampus_foundation.read_run.coverage import route_coverage
from hippocampus_foundation.read_run.errors import GenerationError
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.generator_v2 import CELLS, generate_episode_v2
from hippocampus_foundation.read_run.policies_v2 import (
    POLICIES,
    hybrid_examined_set,
    oracle_floor,
    pareto_frontier,
    policy_examined_sets,
    policy_row,
)

TEST_SEED = hashlib.sha256(b"policies-v2-tests").digest()
BUDGET = 64
EASY, HARD = CELLS["deg3_len6_v8"], CELLS["deg6_len8_v4_rep"]


def _gated(config, count, gamma):
    episodes = []
    for index in range(count):
        try:
            episode = generate_episode_v2(
                TEST_SEED,
                config=config,
                split="test-fixture",
                index=index,
                count=count,
                gamma=gamma,
                gold_mask=None if index % 4 == 0 else 1 + index % 15,
            )
        except GenerationError:
            continue
        if episode.hidden["abstain"]:
            continue
        if coverage_stratum(target_hop_distance(episode)) != "hops_2_4":
            continue
        episodes.append(episode)
    assert episodes
    return episodes


def _summary(episodes, budget=BUDGET):
    rows = {}
    for name, policy in POLICIES.items():
        per = [
            policy_row(episode, policy(episode.visible, budget), budget=budget)
            for episode in episodes
        ]
        rows[name] = {
            "route_complete_fraction": sum(r["route_complete"] for r in per) / len(per),
            "precision_mean": sum(r["precision"] for r in per) / len(per),
            "examined_mean": sum(r["examined"] for r in per) / len(per),
        }
    return rows


def test_every_policy_is_deterministic_and_within_budget():
    for episode in _gated(HARD, 25, 0.4):
        first = policy_examined_sets(episode.visible, BUDGET)
        second = policy_examined_sets(episode.visible, BUDGET)
        assert first == second
        for name, examined in first.items():
            assert len(examined) <= BUDGET, name
            assert len(set(examined)) == len(examined), name


def test_policy_row_refuses_an_oversized_examined_set():
    episode = _gated(EASY, 8, 0.0)[0]
    everything = [edge["edge_id"] for edge in episode.visible["edges"]]
    with pytest.raises(ValueError):
        policy_row(episode, everything, budget=BUDGET)


def test_hybrid_leads_on_coverage_and_the_blind_walker_on_precision():
    """The measured frontier: neither policy dominates, so both are the bar."""

    rows = _summary(_gated(HARD, 150, 0.4))
    assert (
        rows["hybrid"]["route_complete_fraction"]
        > rows["blind_walker"]["route_complete_fraction"]
    )
    assert rows["blind_walker"]["precision_mean"] > rows["hybrid"]["precision_mean"]
    assert rows["blind_walker"]["examined_mean"] < rows["hybrid"]["examined_mean"]
    frontier = pareto_frontier(rows)
    assert set(frontier) == {"hybrid", "blind_walker"}
    assert "greedy_similarity" not in frontier


def test_gamma_degrades_similarity_policies_and_spares_the_blind_walker():
    """Gamma corrupts the promoted edge, so only similarity-reading policies move."""

    low = _summary(_gated(HARD, 120, 0.0))
    high = _summary(_gated(HARD, 120, 0.4))
    assert (
        low["blind_walker"]["route_complete_fraction"]
        == high["blind_walker"]["route_complete_fraction"]
    )
    assert low["blind_walker"]["precision_mean"] == pytest.approx(
        high["blind_walker"]["precision_mean"]
    )
    for name in ("greedy_similarity", "hybrid"):
        assert (
            high[name]["route_complete_fraction"] < low[name]["route_complete_fraction"]
        ), name


def test_the_easy_cell_is_the_sanity_rung():
    rows = _summary(_gated(EASY, 80, 0.4))
    assert rows["blind_walker"]["route_complete_fraction"] == 1.0
    assert rows["hybrid"]["route_complete_fraction"] == 1.0


def test_oracle_floor_bounds_what_any_policy_needs():
    """No policy can be route-complete on fewer edges than the floor."""

    for episode in _gated(HARD, 25, 0.4):
        floor = oracle_floor(episode, out_degree=HARD.out_degree)
        assert floor % HARD.out_degree == 0
        for name, policy in POLICIES.items():
            examined = policy(episode.visible, 128)
            if route_coverage(episode, examined)["route_complete"]:
                assert len(examined) >= floor, name


def test_hybrid_examined_set_is_prefix_consistent_in_the_budget():
    for episode in _gated(HARD, 20, 0.4):
        full = hybrid_examined_set(episode.visible, 64)
        for smaller in (8, 16, 32):
            assert hybrid_examined_set(episode.visible, smaller) == full[:smaller]
