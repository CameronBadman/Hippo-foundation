"""Track P's training config and the loss-equivalence its microbatch shape rests on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CONFIG_PATH = Path("experiments/track_p_v1/training-config.p1.json")
CONFIG = json.loads(CONFIG_PATH.read_text())


def _torch():
    return pytest.importorskip("torch")


def test_the_config_carries_no_target_count_and_no_budget():
    """The two constants Track P exists to remove must be absent, not zeroed."""

    selection = CONFIG["selection"]
    assert "expected_target_count" not in selection
    assert selection["budget"] is None
    assert selection["cost_unit"] == "expansions"
    assert selection["distractor_paths"] == 1
    assert selection["threshold_tuning"] is False
    assert selection["model_selection"] is False
    assert selection["holdout_forbidden"] is True
    assert CONFIG["training_authorized"] is False
    # No stray 2 anywhere in the selection block's values.
    assert 2 not in [value for value in selection.values() if isinstance(value, int)]


def test_evaluation_microbatch_is_separate_from_training():
    training = CONFIG["training"]
    assert training["microbatch_size"] == 128
    assert training["gradient_accumulation_steps"] == 1
    assert training["evaluation_microbatch_size"] == 16
    assert (
        training["microbatch_size"] * training["gradient_accumulation_steps"]
        == training["effective_batch_size"]
    )


def test_the_schedule_is_on_policy_throughout():
    """Gold supervision cannot produce a positive stop label — see below."""

    schedule = CONFIG["training"]["supervision_schedule"]
    assert set(schedule) == {"on_policy"}
    assert schedule["on_policy"] == [0.0, 1.0]
    assert CONFIG["training"]["training_walk_stop_rule"] == "exhaust"


def test_gold_supervision_cannot_produce_a_positive_stop_label():
    """The measurement that forced the schedule change, held as a test.

    A gold walk expands exactly the two planted route prefixes, so both target
    endpoints register during its final expansion and no decision point ever
    observes the walk as complete. Every stop label is 0, and a head trained on
    that scores perfect agreement by predicting the constant "never stop" — the
    same silent nothing Track O's coverage head did. An on-policy exhaustive
    walk continues past completion often enough to give real positives.
    """

    torch = _torch()
    import hashlib

    from hippocampus_foundation.read_run.errors import GenerationError
    from hippocampus_foundation.read_run.generator_v3 import (
        CELLS_V3,
        generate_episode_v3,
    )
    from hippocampus_foundation.read_run.model_v2 import route_prefixes
    from hippocampus_foundation.read_run.model_v3 import build_read_model_v3
    from hippocampus_foundation.read_run.training_v3 import stop_labels

    seed = hashlib.sha256(b"gold-stop-label-test").digest()
    episodes = []
    for index in range(60):
        try:
            episodes.append(
                generate_episode_v3(
                    seed,
                    config=CELLS_V3["deg3_len6_v8-k1"],
                    split="test-fixture",
                    index=index,
                    count=60,
                    gamma=0.4,
                    gold_mask=1 + index % 15,
                )
            )
        except GenerationError:
            continue
        if len(episodes) == 24:
            break

    torch.manual_seed(1729)
    model = build_read_model_v3(CONFIG)

    supplied = [route_prefixes(e.visible, e.hidden["valid_routes"]) for e in episodes]
    gold = model([e.visible for e in episodes], stop_rule="exhaust", supplied=supplied)
    gold_labels = stop_labels(episodes, gold["decisions"])
    assert sum(sum(row) for row in gold_labels) == 0.0, (
        "gold supervision produced a positive stop label; the schedule change "
        "that removed it may no longer be needed"
    )

    on_policy = model([e.visible for e in episodes], stop_rule="exhaust")
    on_policy_labels = stop_labels(episodes, on_policy["decisions"])
    assert sum(sum(row) for row in on_policy_labels) > 0.0
    assert sum(1 for row in on_policy_labels if any(row)) >= 3


def test_capacity_matches_track_o_exactly():
    """A capacity drift would void the equal-capacity comparison silently."""

    torch = _torch()
    from hippocampus_foundation.read_run.model_v2 import build_read_model_v2
    from hippocampus_foundation.read_run.model_v3 import build_read_model_v3

    o1 = json.loads(Path("experiments/track_o_v1/training-config.o1.json").read_text())
    torch.manual_seed(1729)
    track_o = sum(p.numel() for p in build_read_model_v2(o1).parameters())
    torch.manual_seed(1729)
    track_p = sum(p.numel() for p in build_read_model_v3(CONFIG).parameters())
    assert track_p == track_o == 10_257_896


def test_microbatch_shape_is_loss_equivalent():
    """128x1 and 16x8 must give the same loss and the same gradients.

    `masked_edge_loss` takes a per-episode mean then a batch mean, and each
    accumulated chunk is divided by the chunk count, so the identity holds by
    construction — this pins it, because a future reduction change would break
    the equivalence without breaking anything else.
    """

    torch = _torch()
    from torch.nn import functional

    torch.manual_seed(0)
    scores = torch.randn(128, 12)
    targets = (torch.rand(128, 12) > 0.5).float()
    mask = torch.rand(128, 12) > 0.2

    from hippocampus_foundation.read_run.training_v2 import masked_edge_loss

    whole = masked_edge_loss(torch, functional, scores, targets, mask)

    chunks = []
    for start in range(0, 128, 16):
        stop = start + 16
        chunks.append(
            masked_edge_loss(
                torch,
                functional,
                scores[start:stop],
                targets[start:stop],
                mask[start:stop],
            )
            / 8
        )
    accumulated = torch.stack(chunks).sum()
    assert torch.allclose(whole, accumulated, atol=1e-6)

    # And the same for gradients, which is what actually reaches the optimiser.
    parameter = torch.zeros(128, 12, requires_grad=True)
    masked_edge_loss(torch, functional, scores + parameter, targets, mask).backward()
    whole_grad = parameter.grad.clone()
    parameter.grad = None
    for start in range(0, 128, 16):
        stop = start + 16
        (
            masked_edge_loss(
                torch,
                functional,
                scores[start:stop] + parameter[start:stop],
                targets[start:stop],
                mask[start:stop],
            )
            / 8
        ).backward()
    assert torch.allclose(whole_grad, parameter.grad, atol=1e-6)


def test_stop_loss_weights_every_episode_equally():
    """An episode that exhausts in three expansions weighs as much as one in twenty."""

    torch = _torch()
    from torch.nn import functional

    from hippocampus_foundation.read_run.training_v3 import stop_loss

    # A short episode the head gets badly wrong, and a long one it gets right.
    # Per-episode weighting must let the short episode dominate; pooling the
    # decision points would bury it 20:3.
    short = torch.full((3,), -4.0)
    long = torch.full((20,), -4.0)
    labels = [[1.0] * 3, [0.0] * 20]
    balanced = float(stop_loss(torch, functional, [short, long], labels))
    pooled = float(
        functional.binary_cross_entropy_with_logits(
            torch.cat([short, long]),
            torch.cat([torch.ones(3), torch.zeros(20)]),
        )
    )
    # The short episode's loss is ~4.018, the long one's ~0.018; the per-episode
    # mean is ~2.018 while pooling gives ~0.540.
    assert abs(balanced - 2.0183) < 0.01, balanced
    assert abs(pooled - 0.5400) < 0.01, pooled
    assert balanced > 3 * pooled, "per-episode weighting collapsed into pooling"
