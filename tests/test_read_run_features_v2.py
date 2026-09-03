"""The vectorised featurisers must reproduce the scalar reference exactly.

Two independent implementations of one predicate, checked against each other —
the pattern `coverage.py` uses against the evaluator. The scalar versions in
`model_v2` stay authoritative; these tests are what allow the fast path to be
trusted, since a transposed axis in the pair grid would still produce plausible
scores and a plausible walk.
"""

from __future__ import annotations

import hashlib

import pytest

from hippocampus_foundation.read_run.errors import GenerationError
from hippocampus_foundation.read_run.generator_v2 import CELLS, generate_episode_v2
from hippocampus_foundation.read_run.model_v2 import (
    EpisodeIndex,
    Prefix,
    candidate_features,
    context_features,
    pair_features,
    query_cross_features,
)

TEST_SEED = hashlib.sha256(b"features-v2-tests").digest()


def _numpy():
    return pytest.importorskip("numpy")


def _episodes(cell: str, count: int = 6):
    config = CELLS[cell]
    out = []
    for index in range(count * 8):
        try:
            out.append(
                generate_episode_v2(
                    TEST_SEED,
                    config=config,
                    split="test-fixture",
                    index=index,
                    count=count * 8,
                    gamma=0.4,
                    gold_mask=1 + index % 15,
                )
            )
        except GenerationError:
            continue
        if len(out) == count:
            break
    assert out
    return out


def _prefixes(index: EpisodeIndex):
    """Depth 0 and, where one exists, a depth-1 prefix."""

    out = [Prefix((), index.start, 0)]
    for edge in index.group(index.start):
        if edge["relation"] == index.relations[0]:
            out.append(Prefix((edge["edge_id"],), edge["target"], 1))
            break
    return out


@pytest.mark.parametrize("cell", ("deg3_len6_v8", "deg6_len8_v4_rep"))
def test_vectorised_features_match_the_reference(cell: str) -> None:
    numpy = _numpy()
    from hippocampus_foundation.read_run.features_v2 import (
        EpisodeArrays,
        candidate_feature_rows,
        context_feature_rows,
        pair_feature_grid,
        query_cross_grid,
    )

    checked = 0
    for episode in _episodes(cell):
        index = EpisodeIndex(episode.visible)
        arrays = EpisodeArrays(index)
        contexts = [(edge["edge_id"], 0) for edge in index.group(index.start)]
        for prefix in _prefixes(index):
            group = [edge["edge_id"] for edge in index.group(prefix.node)]

            reference = numpy.array(
                [[pair_features(index, c, x) for x, _d in contexts] for c in group],
                dtype=numpy.float32,
            )
            assert numpy.array_equal(
                reference,
                pair_feature_grid(index, arrays, group, [x for x, _d in contexts]),
            )

            reference = numpy.array(
                [
                    [query_cross_features(index, prefix, c, p) for p in range(8)]
                    for c in group
                ],
                dtype=numpy.float32,
            )
            assert numpy.array_equal(
                reference, query_cross_grid(index, arrays, prefix, group)
            )

            for content in (True, False):
                reference = numpy.array(
                    [
                        candidate_features(index, prefix, c, content_features=content)
                        for c in group
                    ],
                    dtype=numpy.float32,
                )
                assert numpy.array_equal(
                    reference,
                    candidate_feature_rows(
                        index, arrays, prefix, group, content_features=content
                    ),
                )

            reference = numpy.array(
                [context_features(index, prefix, e, d) for e, d in contexts],
                dtype=numpy.float32,
            )
            assert numpy.array_equal(
                reference, context_feature_rows(index, arrays, prefix, contexts)
            )
            checked += 1
    assert checked >= 6


def test_padding_attributes_never_compare_equal() -> None:
    """Content slots beyond an episode's schema must not create false agreement."""

    numpy = _numpy()
    from hippocampus_foundation.read_run.features_v2 import EpisodeArrays

    for episode in _episodes("deg6_len8_v4_rep", 4):
        index = EpisodeIndex(episode.visible)
        arrays = EpisodeArrays(index)
        padding = arrays.content[:, index.attribute_count :]
        if padding.size:
            # Every padded column is a distinct negative sentinel, so no two
            # nodes agree on it.
            assert (padding < 0).all()
            assert numpy.unique(padding).size == padding.shape[1]


def test_requires_numpy_reports_the_extra() -> None:
    from hippocampus_foundation.read_run.features_v2 import require_numpy

    assert require_numpy() is not None
