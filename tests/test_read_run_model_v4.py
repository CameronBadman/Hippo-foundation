"""Track Q's route-set head and set-pooled answer, property by property.

The load-bearing ones: the walk is unchanged from v3 (the head is additive);
candidate routes are exactly the planted ones on v3 data; the head returns a
variable number of routes; its logits do not depend on candidate order; the
source contains no target constant; and the ranking loss actually separates a
target from a distractor when optimised.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from hippocampus_foundation.read_run.errors import GenerationError, TrainingBlocked
from hippocampus_foundation.read_run.generator_v3 import CELLS_V3, generate_episode_v3
from hippocampus_foundation.read_run.training_v4 import route_labels, route_loss

TEST_SEED = hashlib.sha256(b"model-v4-tests").digest()
CONFIG = json.loads(Path("experiments/track_p_v1/training-config.p1.json").read_text())


def _torch():
    return pytest.importorskip("torch")


def _episodes(cell: str, n: int = 8):
    out = []
    for index in range(n * 3):
        try:
            out.append(
                generate_episode_v3(
                    TEST_SEED,
                    config=CELLS_V3[cell],
                    split="test-fixture",
                    index=index,
                    count=n * 3,
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


def _models(seed: int = 1729):
    torch = _torch()
    from hippocampus_foundation.read_run.model_v3 import build_read_model_v3
    from hippocampus_foundation.read_run.model_v4 import build_read_model_v4

    torch.manual_seed(seed)
    v3 = build_read_model_v3(CONFIG)
    torch.manual_seed(seed)
    v4 = build_read_model_v4(CONFIG)
    return v3, v4


def test_capacity_is_v3_plus_exactly_the_new_heads():
    """The change in capacity is stated, and it is only the new modules."""

    from hippocampus_foundation.read_run.model_v4 import trainable_parameter_count_v4

    v3, v4 = _models()
    new = {
        "route_encoder",
        "route_norm",
        "route_attention",
        "route_attention_norm",
        "route_feedforward",
        "route_feedforward_norm",
        "route_head",
        "endpoint_encoder",
        "answer_head_v4",
    }
    added = sum(p.numel() for n, p in v4.named_parameters() if n.split(".")[0] in new)
    shared = sum(
        p.numel() for n, p in v4.named_parameters() if n.split(".")[0] not in new
    )
    assert shared == sum(p.numel() for p in v3.parameters()) == 10_257_896
    assert trainable_parameter_count_v4(v4) == shared + added
    assert added > 0


def test_the_walk_is_unchanged_from_v3():
    episodes = _episodes("deg6_len8_v4_rep-k1")
    v3, v4 = _models()
    visible = [e.visible for e in episodes]
    a = v3(visible, stop_rule="exhaust")
    b = v4(visible, stop_rule="exhaust")
    assert a["edge_ids"] == b["edge_ids"]
    assert a["endpoints"] == b["endpoints"]
    assert a["stop_reason"] == b["stop_reason"]
    assert a["expansion_count"] == b["expansion_count"]


def test_candidates_are_exactly_the_planted_routes_at_exhaustion():
    episodes = _episodes("deg6_len8_v4_rep-k1")
    _v3, v4 = _models()
    out = v4([e.visible for e in episodes], stop_rule="exhaust")
    scored = v4.score_routes(out)
    labels = route_labels(episodes, scored["route_candidates"])
    for episode, routes, row in zip(
        episodes, scored["route_candidates"], labels, strict=True
    ):
        planted = {tuple(r) for r in episode.hidden["valid_routes"]} | {
            tuple(r) for r in episode.hidden["distractor_routes"]
        }
        assert set(routes) == planted
        assert sum(row) == len(episode.hidden["valid_routes"])


def test_returned_set_has_no_fixed_size():
    """One, three or none — whatever clears zero."""

    torch = _torch()
    _v3, v4 = _models()
    routes = [(1, 2), (3, 4), (5, 6)]
    for logits, expect in (
        ([1.0, 1.0, 1.0], 3),
        ([1.0, -1.0, -1.0], 1),
        ([-1.0, -1.0, -1.0], 0),
        ([0.5, 0.5, -0.5], 2),
    ):
        scored = {
            "route_candidates": [routes],
            "route_logits": [torch.tensor(logits)],
        }
        assert len(v4.returned_routes(scored)[0]) == expect


def test_route_logits_are_invariant_to_candidate_order():
    """Self-attention with no positional signal must be permutation-equivariant,
    and the only cross-candidate feature (longest shared prefix) is order-free."""

    torch = _torch()
    from hippocampus_foundation.read_run import model_v4 as module

    episodes = _episodes("deg6_len8_v4_rep-k1", 4)
    _v3, v4 = _models()
    v4.eval()
    out = v4([e.visible for e in episodes], stop_rule="exhaust")
    with torch.no_grad():
        first = v4.score_routes(out)
        original = module.decode_all_routes

        def reversed_decode(*args, **kwargs):
            return list(reversed(original(*args, **kwargs)))

        module.decode_all_routes = reversed_decode
        try:
            second = v4.score_routes(out)
        finally:
            module.decode_all_routes = original
    for routes_a, logits_a, routes_b, logits_b in zip(
        first["route_candidates"],
        first["route_logits"],
        second["route_candidates"],
        second["route_logits"],
        strict=True,
    ):
        assert routes_b == list(reversed(routes_a))
        by_route_a = dict(zip(routes_a, logits_a.tolist(), strict=True))
        by_route_b = dict(zip(routes_b, logits_b.tolist(), strict=True))
        for route in routes_a:
            assert abs(by_route_a[route] - by_route_b[route]) < 1e-5


def test_no_target_constant_in_the_source():
    """Grep-level: the patterns Track P's answer head carried must be absent."""

    source = Path("src/hippocampus_foundation/read_run/model_v4.py").read_text()
    body = source.split('"""', 2)[2]  # skip the module docstring, which cites them
    for pattern in (r"range\(2\)", r"==\s*2\b", r"min\(len\([a-z_]+\),\s*2\)"):
        assert not re.search(pattern, body), pattern


def test_answer_is_identical_across_supervision_modes():
    """The 2.19 invariant, on the set-pooled answer: a supplied replay of the
    same expansions must give the same answer logits as the on-policy walk."""

    torch = _torch()
    from hippocampus_foundation.read_run.model_v2 import EpisodeIndex, Prefix

    episodes = _episodes("deg6_len8_v4_rep-k1", 6)
    _v3, v4 = _models()
    v4.eval()
    with torch.no_grad():
        on_policy = v4([e.visible for e in episodes], stop_rule="exhaust")
        supplied = []
        for index, episode in enumerate(episodes):
            walk_index = EpisodeIndex(episode.visible)
            seen, items = set(), []
            for prefix_edges in on_policy["prefixes"][index]:
                if prefix_edges in seen:
                    continue
                seen.add(prefix_edges)
                node = walk_index.start
                for edge_id in prefix_edges:
                    node = walk_index.by_id[edge_id]["target"]
                prefix = Prefix(prefix_edges, node, len(prefix_edges))
                items.append(
                    (prefix, [edge["edge_id"] for edge in walk_index.group(node)])
                )
            supplied.append(items)
        replay = v4(
            [e.visible for e in episodes], supplied=supplied, stop_rule="exhaust"
        )
    assert torch.allclose(on_policy["logits"], replay["logits"], atol=1e-4)


def test_ranking_loss_separates_a_target_from_a_distractor():
    """Optimising the loss must push the target above the distractor, and the
    loss must reject shape mismatches."""

    torch = _torch()
    from torch.nn import functional

    logits = torch.zeros(3, requires_grad=True)
    labels = [[1.0, 1.0, 0.0]]
    optimiser = torch.optim.SGD([logits], lr=0.5)
    for _ in range(50):
        optimiser.zero_grad()
        route_loss(torch, functional, [logits], labels).backward()
        optimiser.step()
    assert logits[0] > 0 and logits[1] > 0 and logits[2] < 0
    assert min(logits[0], logits[1]) - logits[2] > 1.0
    with pytest.raises(TrainingBlocked):
        route_loss(torch, functional, [logits], [[1.0, 0.0]])
