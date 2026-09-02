"""Model-input ablations for screening runs.

The γ sweep showed that `query_similarity_ppm` carries a γ-invariant on-path
marker as well as the γ-degraded edge hint it was designed to carry (design
notes §1.5), and that with the field flattened every trained TRAV checkpoint is
less route-complete than DIRECT's query-blind pool (§1.7). Whether the frozen
model can learn to navigate from structure alone has therefore never been
tested: every TRAV trained so far had the marker from update 0.

This module is the fair test's instrument. `no_similarity` holds the field at
a constant at train **and** eval. The constant is 0, so the similarity column
of `edge_encoder[0].weight` receives exactly zero gradient and the feature is
removed at unchanged parameter count — nothing in `model.py` needs to change
and `expected_trainable_parameter_count` still holds. The masked payload is
`gates._structural_projection` (P0 gate 7's γ-invariance check) with the field
present, so under the mask the five γ buckets are the same data.

Screening only. An ablated run is not a preregistered arm; it emits no receipt
and reads no holdout. Adding this file changes `freeze._source_inventory()`,
which is already true of `coverage.py` and `greedy.py` relative to the spent v1
freeze; any future official run re-freezes.
"""

from __future__ import annotations

import copy
from typing import Any

from .errors import ReadRunError
from .generator import GeneratedEpisode

NONE = "none"
NO_SIMILARITY = "no_similarity"
INPUT_ABLATIONS = (NONE, NO_SIMILARITY)
MASKED_SIMILARITY_PPM = 0


def mask_query_similarity(
    visible: dict[str, Any], constant: int = MASKED_SIMILARITY_PPM
) -> None:
    """Hold every edge's `query_similarity_ppm` at `constant`, in place.

    The field stays present so `io.validate_model_input_fields` still passes;
    only its value is removed as information.
    """

    for edge in visible["edges"]:
        edge["query_similarity_ppm"] = constant


def masked_similarity_ppm(name: str) -> int | None:
    """The constant an ablation holds the similarity field at, or None."""

    if name == NONE:
        return None
    if name == NO_SIMILARITY:
        return MASKED_SIMILARITY_PPM
    raise ReadRunError(f"unknown input ablation: {name}")


def apply_input_ablation(episode: GeneratedEpisode, name: str) -> GeneratedEpisode:
    """Return the episode as the ablated model sees it.

    `none` returns the same object untouched. `no_similarity` returns a deep
    copy whose visible payload is masked; the hidden payload is copied but not
    changed, so scoring against it is unaffected.
    """

    constant = masked_similarity_ppm(name)
    if constant is None:
        return episode
    masked = copy.deepcopy(episode)
    mask_query_similarity(masked.visible, constant)
    return masked
