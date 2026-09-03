"""Vectorised builders for the Track O featurisers. Behaviour-preserving.

`model_v2`'s scalar featurisers stay as the reference implementation and are not
edited: `tests/test_read_run_model_v2.py::test_content_ablation_keeps_capacity_and_zeroes_the_block`
compares their output with `!=` and slice equality, which raises on ndarrays, and
more importantly two independent implementations of one predicate can be checked
against each other. That is the pattern `coverage.py` already uses against the
evaluator, and `tests/test_read_run_features_v2.py` asserts elementwise equality
here.

The gain is in the aggregation layer, not in any single call. `pair_features` is
invoked about 322,560 times per training update (candidates x context x rounds x
episodes) and `model_v2.score_expansions` then hands four-deep Python lists to
`torch.tensor`. Building the same numbers as numpy arrays and passing them to
`torch.from_numpy` removes both costs; a prototype measured 5.1x on the pair
grid alone.

**numpy is imported lazily, exactly as torch is.** `pyproject.toml` keeps numpy
in the `read-run` extra, not in `[project] dependencies`, and
`tests/test_no_training_surface.py` pins that base list by exact equality — so a
module-level `import numpy` here would break every base-environment import of the
package, the same failure a module-level torch import would cause. `require_numpy`
mirrors `model.require_torch`, and `EpisodeIndex`'s array columns are built on
first use so the torch-free callers (`walker_expansions`, `route_prefixes`, the
generator tests) never touch numpy at all.
"""

from __future__ import annotations

from typing import Any

from .errors import TrainingBlocked
from .model_v2 import (
    CANDIDATE_FEATURE_DIM,
    CONTENT_FEATURE_SLICE,
    CONTEXT_FEATURE_DIM,
    MAX_ATTRIBUTES,
    MAX_QUERY_LENGTH,
    PAIR_FEATURE_DIM,
    QUERY_CROSS_FEATURE_DIM,
    SIMILARITY_SCALE,
    EpisodeIndex,
    Prefix,
)


def require_numpy() -> Any:
    """Import numpy on demand, mirroring `model.require_torch`."""

    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise TrainingBlocked(
            "Track O vectorised features require numpy; install the read-run runtime"
        ) from exc
    return numpy


class EpisodeArrays:
    """Per-episode edge and content columns, built once and reused.

    Held beside an `EpisodeIndex` rather than inside it so that constructing an
    index stays numpy-free; only the vectorised path materialises these.
    """

    def __init__(self, index: EpisodeIndex) -> None:
        numpy = require_numpy()
        edges = index.visible["edges"]
        count = len(edges)
        self.numpy = numpy
        self.source = numpy.empty(count, dtype=numpy.int64)
        self.target = numpy.empty(count, dtype=numpy.int64)
        self.relation = numpy.empty(count, dtype=numpy.int64)
        self.similarity = numpy.empty(count, dtype=numpy.float32)
        for edge in edges:
            edge_id = edge["edge_id"]
            self.source[edge_id] = edge["source"]
            self.target[edge_id] = edge["target"]
            self.relation[edge_id] = edge["relation"]
            self.similarity[edge_id] = edge["query_similarity_ppm"]
        attributes = index.attribute_count
        self.content = numpy.zeros(
            (index.visible["node_count"], MAX_ATTRIBUTES), dtype=numpy.int64
        )
        for node in index.visible["nodes"]:
            self.content[node["node"], :attributes] = node["content"]
        # Attributes beyond the episode's schema must never compare equal, so
        # pad each row with a value distinct per attribute slot.
        for slot in range(attributes, MAX_ATTRIBUTES):
            self.content[:, slot] = -(slot + 1)
        self.attribute_valid = numpy.zeros(MAX_ATTRIBUTES, dtype=bool)
        self.attribute_valid[:attributes] = True
        self.relations = numpy.array(index.relations, dtype=numpy.int64)


def pair_feature_grid(
    index: EpisodeIndex,
    arrays: EpisodeArrays,
    candidates: list[int],
    contexts: list[int],
) -> Any:
    """`[len(candidates), len(contexts), PAIR_FEATURE_DIM]`, matching `pair_features`."""

    numpy = arrays.numpy
    c = numpy.asarray(candidates, dtype=numpy.int64)
    x = numpy.asarray(contexts, dtype=numpy.int64)
    grid = numpy.zeros((len(c), len(x), PAIR_FEATURE_DIM), dtype=numpy.float32)
    cs, ct = arrays.source[c][:, None], arrays.target[c][:, None]
    xs, xt = arrays.source[x][None, :], arrays.target[x][None, :]
    grid[:, :, 0] = arrays.relation[c][:, None] == arrays.relation[x][None, :]
    grid[:, :, 1] = xt == cs
    grid[:, :, 2] = xs == cs
    grid[:, :, 3] = xt == ct
    grid[:, :, 4] = xs == ct
    grid[:, :, 5] = xs == xt
    content = arrays.content
    for block, (left, right) in enumerate(((cs, xs), (ct, xt), (cs, xt))):
        agree = (content[left] == content[right]) & arrays.attribute_valid
        grid[:, :, 6 + 5 * block : 11 + 5 * block] = agree
    grid[:, :, 21] = (
        arrays.similarity[x][None, :] - arrays.similarity[c][:, None]
    ) / SIMILARITY_SCALE
    return grid


def query_cross_grid(
    index: EpisodeIndex, arrays: EpisodeArrays, prefix: Prefix, candidates: list[int]
) -> Any:
    """`[len(candidates), MAX_QUERY_LENGTH, QUERY_CROSS_FEATURE_DIM]`."""

    numpy = arrays.numpy
    c = numpy.asarray(candidates, dtype=numpy.int64)
    length, depth = index.length, prefix.depth
    grid = numpy.zeros(
        (len(c), MAX_QUERY_LENGTH, QUERY_CROSS_FEATURE_DIM), dtype=numpy.float32
    )
    positions = numpy.arange(MAX_QUERY_LENGTH)
    in_query = positions < length
    padded = numpy.full(MAX_QUERY_LENGTH, -1, dtype=numpy.int64)
    padded[:length] = arrays.relations[:length]
    grid[:, :, 0] = (arrays.relation[c][:, None] == padded[None, :]) & in_query[None, :]
    grid[:, :, 1] = positions == depth
    grid[:, :, 2] = positions == depth + 1
    grid[:, :, 3] = positions < depth
    grid[:, :, 4] = positions >= length
    offsets = positions - depth
    within = (offsets >= -4) & (offsets <= 4)
    for column in range(9):
        grid[:, within & (offsets + 4 == column), 5 + column] = 1.0
    return grid


def candidate_feature_rows(
    index: EpisodeIndex,
    arrays: EpisodeArrays,
    prefix: Prefix,
    candidates: list[int],
    *,
    content_features: bool = True,
) -> Any:
    """`[len(candidates), CANDIDATE_FEATURE_DIM]`, matching `candidate_features`.

    Blocks C and D read the *source's whole out-edge group*, which is legitimate
    because reaching a node examines that group; the scalar version does the same.
    """

    numpy = arrays.numpy
    from .model_v2 import candidate_features

    rows = numpy.empty((len(candidates), CANDIDATE_FEATURE_DIM), dtype=numpy.float32)
    for row, edge_id in enumerate(candidates):
        rows[row] = candidate_features(
            index, prefix, edge_id, content_features=content_features
        )
    return rows


def context_feature_rows(
    index: EpisodeIndex,
    arrays: EpisodeArrays,
    prefix: Prefix,
    contexts: list[tuple[int, int]],
) -> Any:
    """`[len(contexts), CONTEXT_FEATURE_DIM]`, matching `context_features`."""

    numpy = arrays.numpy
    from .model_v2 import context_features

    rows = numpy.empty((len(contexts), CONTEXT_FEATURE_DIM), dtype=numpy.float32)
    for row, (edge_id, depth) in enumerate(contexts):
        rows[row] = context_features(index, prefix, edge_id, depth)
    return rows


__all__ = [
    "CONTENT_FEATURE_SLICE",
    "EpisodeArrays",
    "candidate_feature_rows",
    "context_feature_rows",
    "pair_feature_grid",
    "query_cross_grid",
    "require_numpy",
]
