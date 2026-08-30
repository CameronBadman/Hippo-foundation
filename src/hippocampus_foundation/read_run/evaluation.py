"""Proof-valid exact-set evaluation and preregistered decision reporting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .generator import GeneratedEpisode


def decode_best_routes(
    visible: dict[str, Any], edge_ids: Sequence[int], scores: Sequence[float]
) -> list[list[int]]:
    """Decode at most one best complete query route per endpoint.

    DIRECT calls this only after its B scores have been produced jointly. The
    decoder never affects pool construction or a score, so it does not turn
    the direct arm into an adaptive scorer.
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
    return [list(route) for _total, _endpoint, route in ranked[:2]]


def score_prediction(
    episode: GeneratedEpisode,
    *,
    predicted_class: int,
    recorded_routes: Sequence[Sequence[int]],
) -> dict[str, Any]:
    valid_routes = {tuple(route) for route in episode.hidden["valid_routes"]}
    supplied = [tuple(route) for route in recorded_routes]
    by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}
    supplied_endpoints = {by_id[route[-1]]["target"] for route in supplied if route}
    proof_valid = (
        bool(supplied)
        and all(route in valid_routes for route in supplied)
        and supplied_endpoints == set(episode.hidden["target_nodes"])
    )
    expected_class = (
        0 if episode.hidden["abstain"] else episode.hidden["gold_assertion_mask"]
    )
    class_correct = predicted_class == expected_class
    exact_correct = bool(class_correct and proof_valid)
    return {
        "expected_class": expected_class,
        "predicted_class": predicted_class,
        "abstain": episode.hidden["abstain"],
        "class_correct": class_correct,
        "proof_valid": proof_valid,
        "exact_correct": exact_correct,
    }


def summarize_predictions(predictions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not predictions:
        raise ValueError("cannot summarize an empty prediction set")
    non_abstain = [item for item in predictions if not item["abstain"]]
    abstain = [item for item in predictions if item["abstain"]]
    return {
        "episode_count": len(predictions),
        "non_abstain_count": len(non_abstain),
        "abstain_count": len(abstain),
        "non_abstain_exact_set_accuracy": (
            sum(item["exact_correct"] for item in non_abstain) / len(non_abstain)
        ),
        "abstain_accuracy": (
            sum(item["exact_correct"] for item in abstain) / len(abstain)
        ),
        "proof_valid_fraction": (
            sum(item["proof_valid"] for item in predictions) / len(predictions)
        ),
        "class_only_accuracy_not_primary": (
            sum(item["class_correct"] for item in predictions) / len(predictions)
        ),
    }


def apply_preregistered_decision(
    results: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Apply the frozen four-way rule without threshold flexibility."""

    expected_specs = {
        (gamma, arm, seed)
        for gamma in (0.0, 0.1, 0.2, 0.3, 0.4)
        for arm in ("TRAV", "DIRECT")
        for seed in (1729, 2718, 3141)
    }
    observed_specs = [
        (float(result["gamma"]), result["arm"], int(result["model_seed"]))
        for result in results
    ]
    if (
        len(observed_specs) != len(set(observed_specs))
        or set(observed_specs) != expected_specs
    ):
        raise ValueError(
            "main decision requires every preregistered model seed exactly once"
        )
    budgets = {int(result["budget"]) for result in results}
    if len(budgets) != 1 or not budgets <= {16, 32, 64, 128}:
        raise ValueError("main decision requires one preregistered budget")
    grouped: dict[tuple[float, str], list[float]] = defaultdict(list)
    for result in results:
        grouped[(float(result["gamma"]), result["arm"])].append(
            float(result["non_abstain_exact_set_accuracy"])
        )
    expected = {
        (gamma, arm)
        for gamma in (0.0, 0.1, 0.2, 0.3, 0.4)
        for arm in ("TRAV", "DIRECT")
    }
    if set(grouped) != expected or any(len(values) != 3 for values in grouped.values()):
        raise ValueError(
            "main decision requires exactly three seeds for every arm/gamma"
        )
    curve = []
    gaps: dict[float, float] = {}
    for gamma in (0.0, 0.1, 0.2, 0.3, 0.4):
        trav = grouped[(gamma, "TRAV")]
        direct = grouped[(gamma, "DIRECT")]
        gap = sum(trav) / 3 - sum(direct) / 3
        gaps[gamma] = gap
        curve.append(
            {
                "gamma": gamma,
                "trav": trav,
                "direct": direct,
                "gap": gap,
            }
        )
    negative_control_passed = abs(gaps[0.0]) <= 0.01
    separated = min(grouped[(0.4, "TRAV")]) > max(grouped[(0.4, "DIRECT")])
    if not negative_control_passed:
        decision = "void_negative_control"
    elif gaps[0.4] >= 0.05 and separated:
        decision = "positive"
    elif all(abs(gap) <= 0.02 for gap in gaps.values()):
        decision = "null"
    else:
        decision = "inconclusive"
    return {
        "decision": decision,
        "negative_control_passed": negative_control_passed,
        "gamma_04_complete_seed_range_separation": separated,
        "gamma_04_exact_permutation_p_one_sided": 0.05 if separated else None,
        "curve": curve,
    }
