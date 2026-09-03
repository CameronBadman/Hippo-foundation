"""Track P's two-pass walk and its supervised stop, property by property.

The load-bearing ones: the walk is the same tree an independent model-free
implementation produces; the answer head's inputs are identical across
supervision modes (the design note 2.19 fix, which Track O shipped broken and
whose absence no output test caught); every head receives gradient (which Track
O's coverage head did not); and no feature encodes the target count.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hippocampus_foundation.read_run.errors import GenerationError, TrainingBlocked
from hippocampus_foundation.read_run.generator_v3 import CELLS_V3, generate_episode_v3
from hippocampus_foundation.read_run.policies_v3 import blind_exhaust_trace
from hippocampus_foundation.read_run.training_v3 import (
    SUPERVISION_SOURCES_V3,
    answer_cut_indices,
    stop_labels,
    stop_loss,
    supervision_source_v3,
)

TEST_SEED = hashlib.sha256(b"model-v3-tests").digest()
CONFIG = json.loads(Path("experiments/track_o_v1/training-config.o1.json").read_text())


def _torch():
    return pytest.importorskip("torch")


def _episodes(cell: str, n: int = 10):
    config = CELLS_V3[cell]
    out = []
    for index in range(n * 2):
        try:
            out.append(
                generate_episode_v3(
                    TEST_SEED,
                    config=config,
                    split="test-fixture",
                    index=index,
                    count=n * 2,
                    gamma=0.4,
                    gold_mask=1 + index % 15,
                )
            )
        except GenerationError:
            continue
        if len(out) == n:
            break
    assert out
    return out


def _model(seed: int = 1729):
    torch = _torch()
    from hippocampus_foundation.read_run.model_v3 import build_read_model_v3

    torch.manual_seed(seed)
    return build_read_model_v3(CONFIG)


# --- capacity and constants ---------------------------------------------------


def test_capacity_is_identical_to_v2():
    """The equal-capacity comparison must survive replacing the head."""

    torch = _torch()
    from hippocampus_foundation.read_run.model_v2 import build_read_model_v2
    from hippocampus_foundation.read_run.model_v3 import (
        build_read_model_v3,
        parameter_count_breakdown_v3,
    )

    torch.manual_seed(1729)
    v3 = build_read_model_v3(CONFIG)
    torch.manual_seed(1729)
    v2 = build_read_model_v2(CONFIG)
    assert sum(p.numel() for p in v3.parameters()) == sum(
        p.numel() for p in v2.parameters()
    )
    breakdown = parameter_count_breakdown_v3(CONFIG)
    assert "stop_head" in breakdown and "coverage_head" not in breakdown


def test_no_stop_feature_encodes_the_target_count():
    """A stop head that reads a 2 is learning `stop_aware`, not a capability.

    Varying only the endpoint count from 0 to 4 must move the features
    monotonically and without a step at 2, which is what a `>= 2` flag or a
    3-wide one-hot capped at 2 would produce.
    """

    from hippocampus_foundation.read_run.model_v3 import STOP_FEATURE_DIM, stop_features

    def row(endpoints: int) -> list[float]:
        return stop_features(
            endpoints=list(range(endpoints)),
            complete_routes=endpoints,
            frontier_depths=[1, 2],
            expansions=4,
            expansions_since_endpoint=1,
            last_expansion_matched=True,
            prefix_depth=2,
            endpoints_agree=False,
        )

    rows = [row(n) for n in range(5)]
    assert all(len(r) == STOP_FEATURE_DIM for r in rows)
    changed = [
        index for index in range(STOP_FEATURE_DIM) if rows[0][index] != rows[4][index]
    ]
    # Exactly two columns respond to the endpoint count: its own and the
    # complete-route count. Neither saturates before 4.
    assert len(changed) == 2
    for index in changed:
        values = [r[index] for r in rows]
        assert values == sorted(values)
        assert len(set(values)) == 5, "a column saturates — a cap is hiding in it"


def test_stop_features_reject_a_width_drift():
    from hippocampus_foundation.read_run import model_v3

    original = model_v3.STOP_FEATURE_DIM
    model_v3.STOP_FEATURE_DIM = original + 1
    try:
        with pytest.raises(TrainingBlocked):
            model_v3.stop_features(
                endpoints=[],
                complete_routes=0,
                frontier_depths=[],
                expansions=0,
                expansions_since_endpoint=0,
                last_expansion_matched=False,
                prefix_depth=0,
                endpoints_agree=False,
            )
    finally:
        model_v3.STOP_FEATURE_DIM = original


# --- the walk -----------------------------------------------------------------


@pytest.mark.parametrize(
    "cell", ["deg3_len6_v8-k1", "deg6_len8_v4_rep-k1"], ids=["easy", "hard"]
)
def test_exhaustion_reproduces_the_model_free_walker(cell):
    """Independent implementation check, and the no-budget guarantee."""

    from hippocampus_foundation.read_run.model_v3 import STOP_TREE_EXHAUSTED

    episodes = _episodes(cell, 8)
    model = _model()
    out = model([e.visible for e in episodes], stop_rule="exhaust")
    for index, episode in enumerate(episodes):
        assert set(out["edge_ids"][index]) == set(
            blind_exhaust_trace(episode.visible).examined
        )
        assert out["stop_reason"][index] == STOP_TREE_EXHAUSTED
        # Registration at examination: exhaustion registers every endpoint.
        assert set(out["endpoints"][index]) == set(
            episode.hidden["target_nodes"]
        ) | set(episode.hidden["distractor_endpoints"])
        assert len(out["edge_ids"][index]) == len(set(out["edge_ids"][index]))


def test_stop_reason_is_one_of_exactly_two_values():
    from hippocampus_foundation.read_run.model_v3 import (
        STOP_LEARNED,
        STOP_TREE_EXHAUSTED,
    )

    episodes = _episodes("deg6_len8_v4_rep-k1", 8)
    model = _model()
    for rule in ("exhaust", "learned"):
        out = model([e.visible for e in episodes], stop_rule=rule)
        assert set(out["stop_reason"]) <= {STOP_LEARNED, STOP_TREE_EXHAUSTED}
    with pytest.raises(TrainingBlocked):
        model([e.visible for e in episodes], stop_rule="budget_cap")


def test_pass_two_recovers_pass_one_exactly():
    """The examined set, its width and the score tensor must line up."""

    episodes = _episodes("deg6_len8_v4_rep-k1", 8)
    model = _model()
    out = model([e.visible for e in episodes], stop_rule="exhaust")
    width = out["scores"].shape[1]
    for index in range(len(episodes)):
        count = out["examined_count"][index]
        assert count == len(out["edge_ids"][index])
        assert count == len(out["prefixes"][index])
        assert int(out["score_mask"][index].sum()) == count
        assert count <= width


def test_every_head_receives_gradient():
    """Track O's coverage head received none and no output test noticed."""

    torch = _torch()
    episodes = _episodes("deg6_len8_v4_rep-k1", 6)
    model = _model()
    out = model([e.visible for e in episodes], stop_rule="exhaust")
    loss = (
        out["scores"].sum() + torch.cat(out["stop_logits"]).sum() + out["logits"].sum()
    )
    loss.backward()
    for name in ("score_head", "coverage_head", "answer_head", "traversal_blocks"):
        module = getattr(model, name)
        moved = [
            parameter
            for parameter in module.parameters()
            if parameter.grad is not None and float(parameter.grad.abs().sum()) > 0.0
        ]
        assert moved, f"{name} received no gradient"


def test_head_extras_are_identical_across_supervision_modes():
    """The design note 2.19 invariant, at the level that failed in Track O.

    A supplied (gold/walker) prefix path and an on-policy walk must give the
    answer head the same endpoint-derived inputs, because registration now
    happens in the scoring loop rather than in the selection branch that a
    supplied path skips.
    """

    episodes = _episodes("deg6_len8_v4_rep-k1", 8)
    model = _model()
    on_policy = model([e.visible for e in episodes], stop_rule="exhaust")
    # Replay each walk as a supplied path: the same expansions, no selection.
    from hippocampus_foundation.read_run.model_v2 import EpisodeIndex, Prefix

    supplied = []
    for index, episode in enumerate(episodes):
        walk_index = EpisodeIndex(episode.visible)
        items = []
        seen = set()
        for prefix_edges in on_policy["prefixes"][index]:
            if prefix_edges in seen:
                continue
            seen.add(prefix_edges)
            node = walk_index.start
            for edge_id in prefix_edges:
                node = walk_index.by_id[edge_id]["target"]
            items.append((Prefix(prefix_edges, node, len(prefix_edges)), None))
        supplied.append(
            [
                (
                    prefix,
                    [edge["edge_id"] for edge in walk_index.group(prefix.node)],
                )
                for prefix, _ in items
            ]
        )
    gold = model([e.visible for e in episodes], supplied=supplied, stop_rule="exhaust")
    for index in range(len(episodes)):
        assert set(gold["endpoints"][index]) == set(on_policy["endpoints"][index])
        assert {tuple(r) for r in gold["routes"][index]} == {
            tuple(r) for r in on_policy["routes"][index]
        }


# --- labels -------------------------------------------------------------------


def test_stop_labels_are_monotone_and_registration_based():
    """Once both targets are registered the label stays 1 for the rest of the walk."""

    episodes = _episodes("deg6_len8_v4_rep-k1", 8)
    model = _model()
    out = model([e.visible for e in episodes], stop_rule="exhaust")
    labels = stop_labels(episodes, out["decisions"])
    positives = 0
    for row in labels:
        assert row == sorted(row), "the stop label is not monotone in the walk"
        positives += int(any(row))
    assert positives >= 1
    # Exhaustion registers both targets, so every episode ends route-complete;
    # the final decision point is the one before the last expansion, so a
    # single-expansion tail can still be labelled 0.
    for episode, row, decisions in zip(episodes, labels, out["decisions"], strict=True):
        targets = set(episode.hidden["target_nodes"])
        for value, point in zip(row, decisions, strict=True):
            assert value == (1.0 if targets <= set(point.endpoints) else 0.0)


def test_answer_cut_is_t_star_and_within_the_examined_set():
    episodes = _episodes("deg6_len8_v4_rep-k1", 8)
    model = _model()
    out = model([e.visible for e in episodes], stop_rule="exhaust")
    cuts = answer_cut_indices(episodes, out["decisions"], out["examined_count"])
    labels = stop_labels(episodes, out["decisions"])
    for index, cut in enumerate(cuts):
        assert 0 <= cut <= out["examined_count"][index]
        row = labels[index]
        if any(row):
            first = row.index(1.0)
            assert cut == out["decisions"][index][first].examined


def test_stop_loss_reduces_per_episode_then_batch():
    torch = _torch()
    from torch.nn import functional

    logits = [torch.zeros(2, requires_grad=True), torch.zeros(8, requires_grad=True)]
    labels = [[1.0, 1.0], [0.0] * 8]
    loss = stop_loss(torch, functional, logits, labels)
    # Both episodes weigh the same despite the 4x difference in length.
    assert abs(float(loss) - 0.6931471805599453) < 1e-6
    with pytest.raises(TrainingBlocked):
        stop_loss(torch, functional, logits, [[1.0], [0.0] * 8])


def test_the_walker_phase_is_gone_from_the_schedule():
    assert SUPERVISION_SOURCES_V3 == ("gold", "on_policy")
    schedule = {"gold": [0.0, 0.25], "on_policy": [0.25, 1.0]}
    assert supervision_source_v3(0, 100, schedule) == "gold"
    assert supervision_source_v3(50, 100, schedule) == "on_policy"
    with pytest.raises(TrainingBlocked):
        supervision_source_v3(0, 0, schedule)
