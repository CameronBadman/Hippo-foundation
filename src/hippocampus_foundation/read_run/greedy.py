"""The non-learned greedy baseline arm.

TRAV and DIRECT differ in two ways at once: TRAV *chooses* which edges to
examine while DIRECT is handed a fixed query-blind pool, and TRAV's choice is
made by a *learned* scorer. A TRAV-minus-DIRECT gap cannot separate those.
This arm holds the first difference and removes the second: it performs the
same adaptive best-first walk as TRAV, scoring each edge by its published
`query_similarity_ppm` instead of by a network.

It has no parameters and no training. Its examined set is a deterministic
function of the episode and the budget, so its whole gamma curve is computable
without a GPU.

The walk mirrors `model._forward_trav_one` step for step, including the
`(score, -edge_id)` tie-break — highest score first, lowest edge id on a tie —
and the `_structural_order` expansion order, so the two arms differ in the
scoring function alone.

`greedy_predicted_class` supplies the answer that TRAV takes from a learned
head. It reads the assertion masks of the endpoints its own routes reached and
applies the task's public labelling rule: agreeing endpoints give that mask, a
disagreement gives abstain. This uses only the visible payload, never a hidden
field, but it is *exact* where TRAV's head is learned, so it biases exact-set
comparisons in greedy's favour. Any exact-set comparison against a learned arm
must therefore be reported beside the proof-valid decomposition, which is free
of the asymmetry because `proof_valid` does not depend on the answer at all.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .coverage import node_assertion_masks, reachable_endpoints
from .errors import ReadRunError
from .generator import BUDGET_CANDIDATES, GeneratedEpisode
from .model import _structural_order

ABSTAIN_CLASS = 0


def greedy_examined_set(visible: dict[str, Any], budget: int) -> list[int]:
    """The edges a similarity-greedy best-first walk would examine."""

    if budget not in BUDGET_CANDIDATES:
        raise ReadRunError(f"unsupported examined-edge budget: {budget}")
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)
    for values in by_source.values():
        values.sort(key=lambda edge: _structural_order(visible["router_seed"], edge))
    by_id = {edge["edge_id"]: edge for edge in visible["edges"]}

    expanded_nodes: set[int] = set()
    scored_ids: set[int] = set()
    pending: dict[int, int] = {}
    examined: list[int] = []
    current = visible["start_node"]
    while len(examined) < budget:
        if current not in expanded_nodes:
            new_ids = [
                edge["edge_id"]
                for edge in by_source[current]
                if edge["edge_id"] not in scored_ids
            ][: budget - len(examined)]
            expanded_nodes.add(current)
            for edge_id in new_ids:
                pending[edge_id] = by_id[edge_id]["query_similarity_ppm"]
                examined.append(edge_id)
                scored_ids.add(edge_id)
        if len(examined) == budget:
            break
        if not pending:
            raise ReadRunError(
                "greedy exhausted its frontier before consuming the edge budget"
            )
        chosen_id = max(pending, key=lambda edge_id: (pending[edge_id], -edge_id))
        pending.pop(chosen_id)
        current = by_id[chosen_id]["target"]
    return examined


def greedy_predicted_class(
    visible: dict[str, Any], examined_edge_ids: Sequence[int]
) -> int:
    """Apply the task's public labelling rule to the endpoints actually reached."""

    reached = reachable_endpoints(visible, examined_edge_ids)
    if not reached:
        return ABSTAIN_CLASS
    masks = node_assertion_masks(visible)
    distinct = {masks[node] for node in reached}
    if len(distinct) != 1:
        return ABSTAIN_CLASS
    return distinct.pop()


def greedy_predict(episode: GeneratedEpisode, budget: int) -> dict[str, Any]:
    """One greedy episode: examined set, predicted class, decoded routes."""

    examined = greedy_examined_set(episode.visible, budget)
    # A uniform score is the honest input to the shared decoder: greedy ranks
    # edges by similarity while walking, but `decode_best_routes` only uses
    # scores to break ties between routes sharing an endpoint, and at most one
    # relation-matching route reaches each endpoint, so the choice cannot
    # change any decoded route. Passing similarity here would imply a
    # preference the arm does not exercise.
    scores = [0.0] * len(examined)
    return {
        "examined_edge_ids": examined,
        "scores": scores,
        "predicted_class": greedy_predicted_class(episode.visible, examined),
    }
