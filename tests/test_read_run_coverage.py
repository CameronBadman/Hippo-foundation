"""Route-completeness, and the greedy baseline arm that is scored against it.

The central assertion here is that `coverage.route_coverage(...)`'s
`route_complete` predicate equals the evaluator's own `proof_valid` flag, for
every episode and both parameter-free arms. The two are independent
implementations — a breadth-first frontier expansion over query-relation depth
against `decode_best_routes`' depth-first enumerate-rank-truncate — so their
agreement is a real cross-check rather than a restatement.

That equality is what makes route-completeness usable as a structural coverage
metric: it can be computed for any examined set, at any budget, without a
model, and it will predict proof-validity exactly.
"""

from __future__ import annotations

import pytest

from hippocampus_foundation.read_run.coverage import (
    node_assertion_masks,
    reachable_endpoints,
    route_coverage,
    summarize_route_coverage,
)
from hippocampus_foundation.read_run.errors import ReadRunError
from hippocampus_foundation.read_run.evaluation import (
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.generator import (
    GAMMA_BUCKETS,
    generate_episode,
    structural_bfs_pool,
)
from hippocampus_foundation.read_run.greedy import (
    ABSTAIN_CLASS,
    greedy_examined_set,
    greedy_predict,
    greedy_predicted_class,
)

TEST_SEED = bytes(range(32))
COUNT = 60


def _episode(index: int = 0, gamma: float = 0.0, mask: int | None = 1):
    return generate_episode(
        TEST_SEED,
        split="test-fixture",
        index=index,
        count=COUNT,
        gamma=gamma,
        gold_mask=mask,
    )


def _proof_valid(episode, examined, scores=None) -> bool:
    if scores is None:
        scores = [0.0] * len(examined)
    return score_prediction(
        episode,
        predicted_class=0,
        recorded_routes=decode_best_routes(episode.visible, examined, scores),
    )["proof_valid"]


@pytest.mark.parametrize("gamma", GAMMA_BUCKETS)
@pytest.mark.parametrize("budget", (16, 32, 64, 128))
def test_route_complete_equals_proof_valid_for_both_pool_arms(gamma, budget):
    """The structural predicate and the evaluator agree, episode by episode."""

    for index in range(COUNT):
        episode = _episode(index=index, gamma=gamma, mask=None if index % 4 else 1)
        for examined in (
            structural_bfs_pool(episode.visible, budget),
            greedy_examined_set(episode.visible, budget),
        ):
            coverage = route_coverage(episode, examined)
            assert coverage["route_complete"] == _proof_valid(episode, examined)


@pytest.mark.parametrize("gamma", GAMMA_BUCKETS)
def test_reachable_endpoints_never_leave_the_target_set(gamma):
    """Generation admits exactly two relation-matching paths, so every endpoint
    a subset can reach must be one of the episode's targets. Route-completeness
    would be measuring something else entirely if this failed."""

    for index in range(COUNT):
        episode = _episode(index=index, gamma=gamma, mask=None if index % 4 else 1)
        for budget in (16, 128):
            coverage = route_coverage(
                episode, greedy_examined_set(episode.visible, budget)
            )
            assert coverage["reached_outside_targets"] == []


def test_route_completeness_never_exceeds_target_in_pool_coverage():
    """Gate 7's quantity is an upper bound on the one scoring actually needs."""

    rows = []
    for index in range(COUNT):
        episode = _episode(index=index, mask=None if index % 4 else 1)
        pool = structural_bfs_pool(episode.visible, 64)
        coverage = route_coverage(episode, pool)
        assert coverage["target_node_present"] or not coverage["route_complete"]
        rows.append(coverage)
    summary = summarize_route_coverage(rows)
    assert summary["route_complete"] <= summary["target_node_present"]
    assert summary["gate7_overstatement_pp"] >= 0.0
    assert summary["reached_outside_targets_violations"] == 0


def test_full_edge_set_is_always_route_complete():
    """With every edge examined the decoder can always assemble both routes."""

    for index in range(COUNT):
        episode = _episode(index=index, mask=None if index % 4 else 1)
        every = [edge["edge_id"] for edge in episode.visible["edges"]]
        assert route_coverage(episode, every)["route_complete"]


def test_greedy_is_deterministic_and_consumes_its_budget():
    for index in range(COUNT):
        episode = _episode(index=index)
        first = greedy_examined_set(episode.visible, 64)
        assert first == greedy_examined_set(episode.visible, 64)
        assert len(first) == 64
        assert len(set(first)) == 64


def test_greedy_rejects_an_unpreregistered_budget():
    episode = _episode()
    with pytest.raises(ReadRunError):
        greedy_examined_set(episode.visible, 100)


def test_greedy_class_matches_the_generator_rule_when_routes_are_complete():
    """Greedy's answer is exact whenever it decoded every route — the
    asymmetry against TRAV's learned head that the preregistration records."""

    checked = 0
    for index in range(COUNT):
        episode = _episode(index=index, mask=None if index % 4 else 1)
        prediction = greedy_predict(episode, 128)
        if not route_coverage(episode, prediction["examined_edge_ids"])[
            "route_complete"
        ]:
            continue
        checked += 1
        expected = (
            ABSTAIN_CLASS
            if episode.hidden["abstain"]
            else episode.hidden["gold_assertion_mask"]
        )
        assert prediction["predicted_class"] == expected
    assert checked


def test_greedy_class_abstains_when_it_reached_nothing():
    episode = _episode()
    assert greedy_predicted_class(episode.visible, []) == ABSTAIN_CLASS


def test_node_assertion_masks_round_trip_the_visible_payload():
    episode = _episode(mask=1)
    masks = node_assertion_masks(episode.visible)
    for node in episode.visible["nodes"]:
        assert masks[node["node"]] == sum(1 << i for i in node["assertions"])


def test_greedy_follows_similarity_where_the_frontier_allows_it():
    """At gamma=0 the highest-similarity edge out of the start node is on a
    valid route, and greedy examines the start node's edges first."""

    episode = _episode(gamma=0.0)
    examined = greedy_examined_set(episode.visible, 128)
    start = episode.visible["start_node"]
    out_edges = {
        edge["edge_id"] for edge in episode.visible["edges"] if edge["source"] == start
    }
    assert out_edges <= set(examined)
    assert reachable_endpoints(episode.visible, examined)
