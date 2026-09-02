"""The `no_similarity` input ablation and the walk's prefix property.

The ablation is the instrument of the structural-only screening run: it must
be exactly P0 gate 7's structural projection with the field left in place, it
must remove the feature from the model's gradient at unchanged parameter
count, and the model must be blind to the original values once it is applied.

The prefix property is what lets one B = 128 pass report route-completeness at
every smaller budget: TRAV's examined list at budget b must be the first b
edges of its list at budget 128, and the same must hold for DIRECT's pool. It
is asserted on the model here rather than assumed from a reading of the walk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hippocampus_foundation.read_run.ablation import (
    INPUT_ABLATIONS,
    MASKED_SIMILARITY_PPM,
    NO_SIMILARITY,
    NONE,
    apply_input_ablation,
    mask_query_similarity,
    masked_similarity_ppm,
)
from hippocampus_foundation.read_run.coverage import (
    prefix_route_coverage,
    route_coverage,
)
from hippocampus_foundation.read_run.errors import ReadRunError
from hippocampus_foundation.read_run.gates import _structural_projection
from hippocampus_foundation.read_run.generator import (
    GAMMA_BUCKETS,
    GeneratedEpisode,
    generate_episode,
    structural_bfs_pool,
)
from hippocampus_foundation.read_run.io import validate_model_input_fields

TEST_SEED = bytes(range(32))
COUNT = 60
PREFIX_BUDGETS = (8, 16, 32, 64, 128)


def _episode(
    index: int = 0, gamma: float = 0.0, mask: int | None = 1
) -> GeneratedEpisode:
    return generate_episode(
        TEST_SEED,
        split="test-fixture",
        index=index,
        count=COUNT,
        gamma=gamma,
        gold_mask=mask,
    )


def _without_similarity(visible: dict) -> dict:
    projected = json.loads(json.dumps(visible))
    for edge in projected["edges"]:
        edge.pop("query_similarity_ppm")
    return projected


def _model():
    torch = pytest.importorskip("torch")
    from hippocampus_foundation.read_run.model import build_read_model

    config = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "experiments/read_run_v1/training-config.v1.json"
        ).read_text(encoding="utf-8")
    )
    torch.manual_seed(1729)
    return torch, build_read_model(config)


@pytest.mark.parametrize("gamma", GAMMA_BUCKETS)
def test_masked_payload_is_the_structural_projection_with_the_field_kept(gamma):
    for index in range(0, COUNT, 7):
        episode = _episode(index=index, gamma=gamma, mask=None if index % 4 else 1)
        original = json.loads(json.dumps(episode.visible))
        masked = apply_input_ablation(episode, NO_SIMILARITY)

        assert masked is not episode
        assert episode.visible == original, "the source episode was mutated"
        assert masked.hidden == episode.hidden
        assert masked.episode_id == episode.episode_id
        assert all(
            edge["query_similarity_ppm"] == MASKED_SIMILARITY_PPM
            for edge in masked.visible["edges"]
        )
        assert _without_similarity(masked.visible) == _structural_projection(
            episode.visible
        )
        validate_model_input_fields(masked)


def test_masked_buckets_are_identical_across_gamma():
    """Under the mask, γ is inert: the buckets are the same data."""

    for index in range(0, COUNT, 5):
        reference = apply_input_ablation(
            _episode(index, GAMMA_BUCKETS[0]), NO_SIMILARITY
        )
        for gamma in GAMMA_BUCKETS[1:]:
            other = apply_input_ablation(_episode(index, gamma), NO_SIMILARITY)
            assert other.visible == reference.visible
            assert other.hidden["target_nodes"] == reference.hidden["target_nodes"]


def test_none_is_the_identity_and_unknown_names_are_rejected():
    episode = _episode()
    assert apply_input_ablation(episode, NONE) is episode
    assert masked_similarity_ppm(NONE) is None
    assert masked_similarity_ppm(NO_SIMILARITY) == MASKED_SIMILARITY_PPM
    assert set(INPUT_ABLATIONS) == {NONE, NO_SIMILARITY}
    with pytest.raises(ReadRunError, match="unknown input ablation"):
        apply_input_ablation(episode, "similarity_noise")
    with pytest.raises(ReadRunError, match="unknown input ablation"):
        masked_similarity_ppm("")


def test_mask_in_place_keeps_every_other_field_byte_identical():
    episode = _episode(index=3, gamma=0.3)
    before = _without_similarity(episode.visible)
    mask_query_similarity(episode.visible, 0)
    assert _without_similarity(episode.visible) == before
    assert {edge["query_similarity_ppm"] for edge in episode.visible["edges"]} == {0}


def test_similarity_column_receives_zero_gradient_under_the_mask():
    """Constant 0 removes the feature at unchanged parameter count."""

    torch, model = _model()
    episodes = [_episode(index, 0.2, (index % 15) + 1) for index in range(4)]

    def similarity_column_gradient(visible_batch):
        model.zero_grad(set_to_none=True)
        output = model(visible_batch, arm="DIRECT", budget=16)
        (output["logits"].sum() + output["scores"].sum()).backward()
        gradient = model.edge_encoder[0].weight.grad
        return gradient[:, -1].detach().clone(), gradient[:, :-1].detach().clone()

    masked = [apply_input_ablation(e, NO_SIMILARITY).visible for e in episodes]
    column, rest = similarity_column_gradient(masked)
    assert torch.count_nonzero(column) == 0
    assert torch.count_nonzero(rest) > 0, "the control: other inputs still learn"

    column, _rest = similarity_column_gradient([e.visible for e in episodes])
    assert torch.count_nonzero(column) > 0, "unmasked, the column does learn"


def test_model_is_blind_to_the_original_similarity_once_masked():
    torch, model = _model()
    model.eval()
    indices = range(6)
    low = [
        apply_input_ablation(_episode(i, 0.0), NO_SIMILARITY).visible for i in indices
    ]
    high = [
        apply_input_ablation(_episode(i, 0.4), NO_SIMILARITY).visible for i in indices
    ]
    with torch.no_grad():
        for arm in ("TRAV", "DIRECT"):
            a = model(low, arm=arm, budget=16)
            b = model(high, arm=arm, budget=16)
            assert a["edge_ids"] == b["edge_ids"]
            assert torch.equal(a["logits"], b["logits"])
            assert torch.equal(a["scores"], b["scores"])


def test_examined_lists_are_prefix_consistent_in_the_budget():
    """One B = 128 pass yields the examined set at every smaller budget."""

    torch, model = _model()
    model.eval()
    episodes = [_episode(index, 0.2, (index % 15) + 1) for index in range(8)]
    masked = [apply_input_ablation(e, NO_SIMILARITY).visible for e in episodes]
    with torch.no_grad():
        full = model(masked, arm="TRAV", budget=128)["edge_ids"]
        assert all(len(ids) == 128 for ids in full)
        for budget in (16, 32, 64):
            partial = model(masked, arm="TRAV", budget=budget)["edge_ids"]
            assert partial == [ids[:budget] for ids in full]
    for visible in masked:
        pool = structural_bfs_pool(visible, 128)
        for budget in (16, 32, 64):
            assert structural_bfs_pool(visible, budget) == pool[:budget]


def test_prefix_route_coverage_is_route_coverage_of_each_prefix():
    for index in range(0, COUNT, 6):
        episode = _episode(index=index, gamma=0.1, mask=None if index % 4 else 1)
        pool = structural_bfs_pool(episode.visible, 128)
        by_budget = prefix_route_coverage(episode, pool, PREFIX_BUDGETS)
        assert sorted(by_budget) == list(PREFIX_BUDGETS)
        for budget, coverage in by_budget.items():
            assert coverage == route_coverage(episode, pool[:budget])
            if budget in (16, 32, 64, 128):
                assert coverage == route_coverage(
                    episode, structural_bfs_pool(episode.visible, budget)
                )
        flags = [by_budget[b]["route_complete"] for b in PREFIX_BUDGETS]
        assert flags == sorted(flags), "completeness is monotone in the budget"
