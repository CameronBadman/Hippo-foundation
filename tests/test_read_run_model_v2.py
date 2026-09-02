"""Track O traversal model: the properties the architecture exists to have.

Test one is the reason this model was built. v1's frontier scores were produced
under a controller state mutated in visit order, so two candidates compared by
best-first selection had been scored by different functions. Here the stable
term is a pure function of (query, prefix, candidate) and nothing else, and that
is asserted directly rather than argued.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from hippocampus_foundation.read_run.coverage import (
    relation_walker_examined_set,
    route_coverage,
)
from hippocampus_foundation.read_run.errors import GenerationError, TrainingBlocked
from hippocampus_foundation.read_run.evaluation import score_prediction
from hippocampus_foundation.read_run.generator_v2 import CELLS, generate_episode_v2
from hippocampus_foundation.read_run.model_v2 import (
    CONTENT_FEATURE_SLICE,
    STOP_BUDGET_CAP,
    EpisodeIndex,
    Prefix,
    build_read_model_v2,
    candidate_features,
    expected_trainable_parameter_count_v2,
    parameter_count_breakdown_v2,
    route_prefixes,
    walker_expansions,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads(
    (ROOT / "experiments/track_o_v1/training-config.o1.json").read_text()
)
TEST_SEED = hashlib.sha256(b"model-v2-tests").digest()
V1_PARAMETERS = 10_257_937
BUDGET = 64
EASY, HARD = CELLS["deg3_len6_v8"], CELLS["deg6_len8_v4_rep"]


def _torch():
    return pytest.importorskip("torch")


def _episodes(config, count=4, gamma=0.4):
    """`count` episodes, skipping the hard cell's ~17% generation rejections."""

    pool = max(count * 4, 16)
    episodes = []
    for index in range(pool):
        try:
            episodes.append(
                generate_episode_v2(
                    TEST_SEED,
                    config=config,
                    split="test-fixture",
                    index=index,
                    count=pool,
                    gamma=gamma,
                    gold_mask=1 + index % 15,
                )
            )
        except GenerationError:
            continue
        if len(episodes) == count:
            break
    assert len(episodes) == count
    return episodes


def _model(overrides=None):
    torch = _torch()
    torch.manual_seed(1729)
    config = copy.deepcopy(CONFIG)
    if overrides:
        config["model"].update(overrides)
    model = build_read_model_v2(config)
    model.eval()
    return model, config


def test_stable_score_is_invariant_to_visit_order():
    """The defect v1 had: a score that depends on how the walk got there.

    The same (query, prefix, candidate) is scored alone, beside other episodes
    (which changes every padding width), and beside a different companion set.
    All three must agree, because the stable term is a function of the triple.
    """

    torch = _torch()
    model, _config = _model()
    episodes = _episodes(HARD, 4)
    indexes = [EpisodeIndex(episode.visible) for episode in episodes]
    subject = indexes[0]
    prefix = Prefix((), subject.start, 0)
    group = [edge["edge_id"] for edge in subject.group(subject.start)]
    expanded = frozenset({subject.start})

    def score(items):
        with torch.no_grad():
            scores, _tokens, _mask = model.score_expansions(items, {})
        return scores[0, : len(group)]

    alone = score([(subject, prefix, group, expanded)])
    companions = [
        (
            other,
            Prefix((), other.start, 0),
            [edge["edge_id"] for edge in other.group(other.start)],
            frozenset({other.start}),
        )
        for other in indexes[1:]
    ]
    with_two = score([(subject, prefix, group, expanded), *companions[:1]])
    with_three = score([(subject, prefix, group, expanded), *companions])
    assert torch.allclose(alone, with_two, atol=1e-5)
    assert torch.allclose(alone, with_three, atol=1e-5)

    # Order within the batch must not matter either.
    with torch.no_grad():
        reordered, _tokens, _mask = model.score_expansions(
            [*companions, (subject, prefix, group, expanded)], {}
        )
    assert torch.allclose(alone, reordered[len(companions), : len(group)], atol=1e-5)


def test_stable_score_does_not_depend_on_what_else_was_examined():
    """History-independence: a longer prior walk must not move `f`."""

    torch = _torch()
    model, _config = _model()
    episode = _episodes(HARD, 1)[0]
    index = EpisodeIndex(episode.visible)
    expansions = walker_expansions(episode.visible, BUDGET)
    prefix, group = expansions[-1]
    nodes = {index.start} | {index.by_id[edge_id]["target"] for edge_id in prefix.edges}
    narrow = frozenset(nodes)
    wide = frozenset(nodes | {p.node for p, _g in expansions})
    with torch.no_grad():
        first, _t, _m = model.score_expansions([(index, prefix, group, narrow)], {})
        second, _t, _m = model.score_expansions([(index, prefix, group, wide)], {})
    assert torch.allclose(first, second, atol=1e-6)


def test_score_cannot_see_an_unexpanded_targets_out_edges():
    """No free lookahead: mutating an unexpanded target must not move `f`."""

    torch = _torch()
    model, _config = _model()
    episode = _episodes(HARD, 1)[0]
    index = EpisodeIndex(episode.visible)
    prefix = Prefix((), index.start, 0)
    group = [edge["edge_id"] for edge in index.group(index.start)]
    expanded = frozenset({index.start})
    with torch.no_grad():
        before, _t, _m = model.score_expansions([(index, prefix, group, expanded)], {})

    target = index.by_id[group[0]]["target"]
    mutated = copy.deepcopy(episode.visible)
    for edge in mutated["edges"]:
        if edge["source"] == target:
            edge["relation"] = (edge["relation"] + 1) % mutated["relation_count"]
    other = EpisodeIndex(mutated)
    with torch.no_grad():
        after, _t, _m = model.score_expansions([(other, prefix, group, expanded)], {})
    assert torch.allclose(before, after, atol=1e-6)

    with pytest.raises(TrainingBlocked):
        index.out_edges(target, expanded=frozenset())


def test_walker_expansions_reproduce_the_relation_walker():
    for episode in _episodes(HARD, 3) + _episodes(EASY, 3):
        for budget in (8, 16, 32, 64):
            flat = [
                edge_id
                for _prefix, group in walker_expansions(episode.visible, budget)
                for edge_id in group
            ]
            assert flat == relation_walker_examined_set(episode.visible, budget)


def test_the_walk_stops_when_done_rather_than_spending_the_budget():
    """The precision mechanism: the denominator has to be earned."""

    torch = _torch()
    model, _config = _model()
    episodes = _episodes(EASY, 6)
    with torch.no_grad():
        out = model([episode.visible for episode in episodes], budget=BUDGET)
    assert all(reason != STOP_BUDGET_CAP for reason in out["stop_reason"])
    assert all(count < BUDGET for count in out["examined_count"])
    for slot, episode in enumerate(episodes):
        assert route_coverage(episode, out["edge_ids"][slot])["route_complete"]
        assert set(out["edge_ids"][slot]) <= set(
            relation_walker_examined_set(episode.visible, BUDGET)
        )


def test_routes_are_emitted_and_are_proof_valid():
    torch = _torch()
    model, _config = _model()
    episodes = _episodes(EASY, 4)
    with torch.no_grad():
        out = model([episode.visible for episode in episodes], budget=BUDGET)
    for slot, episode in enumerate(episodes):
        routes = out["routes"][slot]
        assert routes, "the walk emitted no routes"
        assert all(set(route) <= set(out["edge_ids"][slot]) for route in routes)
        scored = score_prediction(
            episode,
            predicted_class=episode.hidden["gold_assertion_mask"],
            recorded_routes=routes,
        )
        assert scored["proof_valid"]


def test_supplied_prefixes_supervise_every_route_edge():
    """M6: a route edge is supervisable under its true prefix, walk or no walk."""

    torch = _torch()
    model, _config = _model()
    episodes = _episodes(HARD, 3)
    supplied = [
        route_prefixes(episode.visible, episode.hidden["valid_routes"])
        for episode in episodes
    ]
    with torch.no_grad():
        out = model(
            [episode.visible for episode in episodes],
            budget=BUDGET,
            supplied=supplied,
        )
    for slot, episode in enumerate(episodes):
        on_route = {
            edge_id for route in episode.hidden["valid_routes"] for edge_id in route
        }
        assert on_route <= set(out["edge_ids"][slot])


def test_expected_parameter_count_matches_torch_and_v1_capacity():
    _torch()
    model, config = _model()
    actual = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    closed = expected_trainable_parameter_count_v2(config)
    assert actual == closed, parameter_count_breakdown_v2(config)
    assert abs(actual - V1_PARAMETERS) / V1_PARAMETERS <= 0.01
    assert sum(parameter_count_breakdown_v2(config).values()) == closed


def test_closed_form_counter_runs_without_torch():
    assert expected_trainable_parameter_count_v2(CONFIG) > 0


def test_no_parameter_is_indexed_by_an_episode_local_symbol():
    """Zero-shot guard: relation ids, content values and node ids mean nothing."""

    torch = _torch()
    model, _config = _model()
    episode = _episodes(HARD, 1)[0]
    forbidden = {
        episode.visible["relation_count"],
        episode.visible["node_count"],
        episode.visible["content_value_count"],
        CONFIG["model"].get("maximum_relation_types", 16),
    }
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Embedding):
            assert module.num_embeddings not in forbidden, name
            assert module.num_embeddings == 8, name


def test_determinism_from_the_seed():
    torch = _torch()
    episodes = _episodes(HARD, 3)
    outputs = []
    for _attempt in range(2):
        model, _config = _model()
        with torch.no_grad():
            outputs.append(model([e.visible for e in episodes], budget=BUDGET))
    first, second = outputs
    assert first["edge_ids"] == second["edge_ids"]
    assert first["routes"] == second["routes"]
    assert first["stop_reason"] == second["stop_reason"]
    assert torch.allclose(first["logits"], second["logits"])


def test_content_ablation_keeps_capacity_and_zeroes_the_block():
    _torch()
    model, config = _model({"content_features": False})
    assert expected_trainable_parameter_count_v2(config) == sum(
        p.numel() for p in model.parameters() if p.requires_grad
    )
    episode = _episodes(HARD, 1)[0]
    index = EpisodeIndex(episode.visible)
    prefix = Prefix((), index.start, 0)
    edge_id = index.group(index.start)[0]["edge_id"]
    ablated = candidate_features(index, prefix, edge_id, content_features=False)
    present = candidate_features(index, prefix, edge_id, content_features=True)
    assert ablated != present
    assert len(ablated) == len(present)
    start, end = CONTENT_FEATURE_SLICE
    assert sum(abs(value) for value in ablated[start:end]) == 0.0
    assert sum(abs(value) for value in present[start:end]) > 0.0
    assert ablated[:start] == present[:start] and ablated[end:] == present[end:]
