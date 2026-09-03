"""Proof-validity on generator-v3 data, without the evaluator's top-two cap.

`evaluation.decode_best_routes` keeps at most one route per endpoint and then
**the best two** — a constant 2 that is harmless on v2 data, where the graph
holds exactly two complete routes, and wrong on v3, where a returned set that
contains a distractor route would be silently truncated to two before
`proof_valid` ever saw the third. Track P's principle is that no 2 is hard-coded
anywhere a model or its evaluation could lean on it, so this module decodes
*every* complete route in the supplied set (one per endpoint, best by score)
and lets `score_prediction`'s own rule — the supplied routes must be exactly
the target routes — do the selecting. `evaluation.py` is untouched.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .evaluation import score_prediction
from .generator import GeneratedEpisode

__all__ = ["decode_all_routes", "score_prediction_v3"]


def decode_all_routes(
    visible: dict[str, Any], edge_ids: Sequence[int], scores: Sequence[float]
) -> list[list[int]]:
    """Every complete query route inside `edge_ids`, one per endpoint, uncapped.

    Same traversal as `evaluation.decode_best_routes`; the only difference is
    that nothing is dropped after ranking.
    """

    score_by_id = dict(zip(edge_ids, scores, strict=True))
    allowed = set(edge_ids)
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        if edge["edge_id"] in allowed:
            by_source[edge["source"]].append(edge)
    relations = visible["query_relations"]
    completed: list[tuple[float, int, tuple[int, ...]]] = []

    def visit(node: int, depth: int, route: tuple[int, ...], total: float) -> None:
        if depth == len(relations):
            completed.append((total, node, route))
            return
        for edge in by_source[node]:
            if edge["relation"] == relations[depth]:
                visit(
                    edge["target"],
                    depth + 1,
                    route + (edge["edge_id"],),
                    total + score_by_id[edge["edge_id"]],
                )

    visit(visible["start_node"], 0, (), 0.0)
    best_by_endpoint: dict[int, tuple[float, tuple[int, ...]]] = {}
    for total, endpoint, route in completed:
        current = best_by_endpoint.get(endpoint)
        candidate = (total, route)
        if current is None or candidate > current:
            best_by_endpoint[endpoint] = candidate
    ranked = sorted(
        (
            (total, endpoint, route)
            for endpoint, (total, route) in best_by_endpoint.items()
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    return [list(route) for _total, _endpoint, route in ranked]


def score_prediction_v3(
    episode: GeneratedEpisode,
    *,
    predicted_class: int,
    recorded_routes: Sequence[Sequence[int]],
) -> dict[str, Any]:
    """`score_prediction` plus how many supplied routes were planted distractors."""

    row = score_prediction(
        episode, predicted_class=predicted_class, recorded_routes=recorded_routes
    )
    distractors = {
        tuple(route) for route in episode.hidden.get("distractor_routes", ())
    }
    supplied = [tuple(route) for route in recorded_routes]
    row["distractor_routes_returned"] = sum(route in distractors for route in supplied)
    row["routes_returned"] = len(supplied)
    return row
