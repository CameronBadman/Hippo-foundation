"""Track P's model-free walks and the uncapped v3 evaluator."""

from __future__ import annotations

import hashlib

import pytest

from hippocampus_foundation.read_run.coverage import (
    relation_walker_examined_set,
    route_coverage_v3,
)
from hippocampus_foundation.read_run.errors import GenerationError
from hippocampus_foundation.read_run.evaluation import decode_best_routes
from hippocampus_foundation.read_run.evaluation_v3 import (
    decode_all_routes,
    score_prediction_v3,
)
from hippocampus_foundation.read_run.generator_v3 import CELLS_V3, generate_episode_v3
from hippocampus_foundation.read_run.policies_v3 import (
    POLICIES_V3,
    STOP_EXHAUSTED,
    STOP_TARGETS,
    STOP_TWO_ENDPOINTS,
    blind_exhaust_trace,
    oracle_trace,
    policy_row_v3,
    policy_traces,
    stop_aware_trace,
)

TEST_SEED = hashlib.sha256(b"policies-v3-tests").digest()


def _episodes(cell: str, n: int, gamma: float = 0.4):
    config = CELLS_V3[cell]
    out = []
    for index in range(n):
        try:
            out.append(
                generate_episode_v3(
                    TEST_SEED,
                    config=config,
                    split="test-fixture",
                    index=index,
                    count=n,
                    gamma=gamma,
                    gold_mask=1 + index % 15,
                )
            )
        except GenerationError:
            continue
    assert out
    return out


@pytest.mark.parametrize(
    "cell", ["deg3_len6_v8", "deg3_len6_v8-k2", "deg6_len8_v4_rep-k2"]
)
def test_exhaustion_examines_exactly_the_relation_walkers_tree(cell):
    """Independent implementation check: the exhausted BFS equals the v1-era
    relation walker given an unlimited budget, on v2 and v3 data alike."""

    for episode in _episodes(cell, 12):
        visible = episode.visible
        walker = relation_walker_examined_set(visible, len(visible["edges"]))
        trace = blind_exhaust_trace(visible)
        assert set(trace.examined) == set(walker)
        assert trace.stop_reason == STOP_EXHAUSTED
        # Every complete matching path's endpoint is registered at exhaustion.
        expected = set(episode.hidden["target_nodes"]) | set(
            episode.hidden.get("distractor_endpoints", ())
        )
        assert set(trace.endpoints) == expected


def test_all_policies_share_the_mechanics():
    """Same examined edges for the same expansions: only order and stop differ."""

    for episode in _episodes("deg6_len8_v4_rep-k2", 10):
        traces = policy_traces(episode.visible)
        exhausted = {
            name: set(trace.examined)
            for name, trace in traces.items()
            if trace.stop_reason == STOP_EXHAUSTED
        }
        assert len({frozenset(s) for s in exhausted.values()}) == 1
        for name, trace in traces.items():
            assert len(trace.endpoints) == len(set(trace.endpoints))
            assert len(trace.expansions_at_endpoint) == len(trace.endpoints)
            assert all(
                a <= b
                for a, b in zip(
                    trace.expansions_at_endpoint,
                    trace.expansions_at_endpoint[1:],
                    strict=False,
                )
            )
            row = policy_row_v3(episode, trace)
            # Registration implies set coverage, never the reverse.
            if row["targets_registered"]:
                assert row["route_complete"]
                assert row["expansions_at_rc"] is not None
                assert row["expansions_at_rc"] <= row["expansions"]
                assert row["overhead_expansions"] >= 0
            else:
                assert row["expansions_at_rc"] is None
                assert row["complete_but_unregistered"] == row["route_complete"]
            if trace.stop_reason == STOP_EXHAUSTED:
                # At exhaustion every correct-depth prefix has been popped.
                assert row["targets_registered"]
            if trace.stop_reason == STOP_TWO_ENDPOINTS:
                # One expansion can register several endpoints at once, so the
                # stop fires at "at least two", never at exactly two.
                assert len(trace.endpoints) >= 2


def test_oracle_expands_exactly_the_route_source_states():
    for cell in ("deg3_len6_v8-k2", "deg6_len8_v4_rep-k2"):
        for episode in _episodes(cell, 8):
            trace = oracle_trace(episode)
            by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}
            states = {
                (by_id[edge_id]["source"], depth)
                for route in episode.hidden["valid_routes"]
                for depth, edge_id in enumerate(route)
            }
            assert trace.expansions == len(states)
            assert trace.stop_reason == STOP_TARGETS
            row = policy_row_v3(episode, trace)
            assert row["route_complete"]
            assert row["expansions_at_rc"] == trace.expansions
            # The oracle can still *register* a distractor endpoint whose final
            # edge shares a source with a route edge; it never expands one.
            walker = policy_row_v3(episode, blind_exhaust_trace(episode.visible))
            assert row["expansions"] <= walker["expansions"]


def test_two_endpoint_stop_is_exact_on_v2_and_a_decision_on_v3():
    """On v2 the only two complete paths are the targets, so stopping at two
    loses nothing. On v3 the first two endpoints can be a distractor's."""

    for episode in _episodes("deg3_len6_v8", 20):
        row = policy_row_v3(episode, stop_aware_trace(episode.visible))
        assert row["route_complete"] and row["registered_only_targets"]
        assert row["overhead_expansions"] == 0
    rows = [
        policy_row_v3(episode, stop_aware_trace(episode.visible))
        for episode in _episodes("deg6_len8_v4_rep-k2", 24)
    ]
    assert any(not row["registered_only_targets"] for row in rows)
    assert any(not row["route_complete"] for row in rows)
    # A stop that registered only targets and at least two of them is complete.
    for row in rows:
        if row["registered_only_targets"] and row["endpoints_registered"] >= 2:
            assert row["route_complete"]


def test_decode_all_routes_is_uncapped_and_ranks_like_the_v1_decoder():
    for episode in _episodes("deg6_len8_v4_rep-k2", 8):
        visible = episode.visible
        ids = [edge["edge_id"] for edge in visible["edges"]]
        scores = [float(edge["query_similarity_ppm"]) for edge in visible["edges"]]
        everything = decode_all_routes(visible, ids, scores)
        capped = decode_best_routes(visible, ids, scores)
        assert len(everything) == CELLS_V3["deg6_len8_v4_rep-k2"].distractor_paths + 2
        assert everything[:2] == capped
        full = score_prediction_v3(
            episode, predicted_class=0, recorded_routes=everything
        )
        assert not full["proof_valid"]
        assert full["distractor_routes_returned"] == 2
        assert full["routes_returned"] == 4
        targets_only = [
            route for route in everything if route in episode.hidden["valid_routes"]
        ]
        exact = score_prediction_v3(
            episode, predicted_class=0, recorded_routes=targets_only
        )
        assert exact["proof_valid"] and exact["distractor_routes_returned"] == 0


def test_gate_four_route_complete_agrees_with_the_decoder():
    """Coverage's `route_complete` must equal 'both target routes decodable
    from the examined set', for every policy, episode by episode."""

    disagreements = 0
    checked = 0
    for cell in ("deg3_len6_v8-k2", "deg6_len8_v4_rep-k2"):
        for episode in _episodes(cell, 10):
            targets = {tuple(route) for route in episode.hidden["valid_routes"]}
            for name in POLICIES_V3:
                trace = POLICIES_V3[name](episode.visible)
                decoded = {
                    tuple(route)
                    for route in decode_all_routes(
                        episode.visible, trace.examined, [0.0] * len(trace.examined)
                    )
                }
                complete = route_coverage_v3(episode, trace.examined)["route_complete"]
                disagreements += complete != (targets <= decoded)
                checked += 1
    assert checked >= 40
    assert disagreements == 0
