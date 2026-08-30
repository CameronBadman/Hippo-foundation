"""Mechanical P0 gates for the preregistered READ experiment."""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_bytes, canonical_sha256

from .errors import IntegrityGateError
from .generator import (
    BUDGET_CANDIDATES,
    GAMMA_BUCKETS,
    GeneratedEpisode,
    structural_bfs_pool,
)
from .io import model_input_bytes
from .oracle import independently_solve

GAMMA_TOLERANCE = 0.03
# Amendment 02: the 90% coverage threshold is a control against DIRECT losing
# on pool construction rather than on scoring. Beyond this depth, coverage loss
# is the mechanism under measurement rather than a confound, so the threshold is
# reported there but not gated on.
DECONFOUNDED_MAX_HOPS = 4
DECONFOUNDED_STRATUM = "hops_2_4"
ONE_SIDED_95_Z = 1.6448536269514722
MAX_PROBE_EXCESS = 0.01


def _truth_projection(hidden: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "target_nodes",
        "valid_routes",
        "teacher_actions",
        "abstain",
        "gold_assertion_mask",
        "greedy_wrong_count",
        "path_step_count",
        "measured_gamma",
    }
    return {key: hidden[key] for key in sorted(keys)}


def dual_oracle_gate(episodes: Iterable[GeneratedEpisode]) -> dict[str, Any]:
    checked = 0
    for episode in episodes:
        observed = independently_solve(episode.visible)
        expected = _truth_projection(episode.hidden)
        if observed != expected:
            raise IntegrityGateError(
                f"dual oracle disagreement for {episode.episode_id}: "
                f"expected={canonical_sha256(expected)}, "
                f"observed={canonical_sha256(observed)}"
            )
        checked += 1
    if checked == 0:
        raise IntegrityGateError("dual oracle gate received no episodes")
    return {
        "gate": "dual_oracle_agreement",
        "passed": True,
        "episode_count": checked,
    }


def gamma_measurement_gate(
    episodes: Iterable[GeneratedEpisode], *, requested_gamma: float
) -> dict[str, Any]:
    if requested_gamma not in GAMMA_BUCKETS:
        raise IntegrityGateError("gamma gate received an unregistered bucket")
    wrong = 0
    steps = 0
    count = 0
    for episode in episodes:
        if episode.hidden["requested_gamma"] != requested_gamma:
            raise IntegrityGateError("episode is assigned to the wrong gamma bucket")
        observed = independently_solve(episode.visible)
        wrong += observed["greedy_wrong_count"]
        steps += observed["path_step_count"]
        count += 1
    if count == 0 or steps == 0:
        raise IntegrityGateError("gamma gate received no measurable path steps")
    measured = wrong / steps
    passed = abs(measured - requested_gamma) <= GAMMA_TOLERANCE
    if not passed:
        raise IntegrityGateError(
            f"measured gamma {measured:.8f} differs from {requested_gamma:.1f} "
            f"by more than {GAMMA_TOLERANCE:.2f}"
        )
    return {
        "gate": "gamma_measured_not_declared",
        "passed": True,
        "requested_gamma": requested_gamma,
        "measured_gamma": measured,
        "greedy_wrong_count": wrong,
        "path_step_count": steps,
        "episode_count": count,
    }


def gold_swap_noninterference_gate(
    episodes: Iterable[GeneratedEpisode], *, maximum_episodes: int | None = None
) -> dict[str, Any]:
    checked = 0
    for episode in episodes:
        before = model_input_bytes(episode)
        swapped_hidden = copy.deepcopy(episode.hidden)
        swapped_hidden["target_nodes"] = [
            (node + 1) % episode.visible["node_count"]
            for node in swapped_hidden["target_nodes"]
        ]
        swapped_hidden["gold_assertion_mask"] = (
            1 if swapped_hidden["gold_assertion_mask"] is None else None
        )
        swapped_hidden["abstain"] = not swapped_hidden["abstain"]
        swapped = GeneratedEpisode(
            episode_id=episode.episode_id,
            paired_world_id=episode.paired_world_id,
            visible=copy.deepcopy(episode.visible),
            hidden=swapped_hidden,
        )
        after = model_input_bytes(swapped)
        if before != after:
            raise IntegrityGateError(
                f"gold swap changed model-visible bytes: {episode.episode_id}"
            )
        checked += 1
        if maximum_episodes is not None and checked >= maximum_episodes:
            break
    if checked == 0:
        raise IntegrityGateError("gold-swap gate received no episodes")
    return {
        "gate": "gold_swap_noninterference",
        "passed": True,
        "episode_count": checked,
    }


def _structural_projection(visible: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(visible)
    for edge in result["edges"]:
        edge.pop("query_similarity_ppm")
    return result


def target_hop_distance(episode: GeneratedEpisode) -> int:
    """BFS hops from the traversal root to the farthest target node.

    This is the depth the structural pool must actually reach. It is not the
    planted path length: background edges create shortcuts, so a length-6 route
    can put its targets far closer than six hops.
    """

    adjacency: dict[int, list[int]] = defaultdict(list)
    for edge in episode.visible["edges"]:
        adjacency[edge["source"]].append(edge["target"])
    start = episode.visible["start_node"]
    distance = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for target in adjacency[node]:
            if target not in distance:
                distance[target] = distance[node] + 1
                queue.append(target)
    unreachable = len(episode.visible["nodes"]) + 1
    return max(
        distance.get(node, unreachable) for node in episode.hidden["target_nodes"]
    )


def coverage_stratum(hops: int) -> str:
    """Name the reporting stratum for a farthest-target hop distance."""

    if hops <= DECONFOUNDED_MAX_HOPS:
        return DECONFOUNDED_STRATUM
    if hops == 5:
        return "hops_5"
    return "hops_6_plus"


def direct_pool_invariance_gate(
    episodes_by_gamma: dict[float, Sequence[GeneratedEpisode]],
) -> dict[str, Any]:
    if set(episodes_by_gamma) != set(GAMMA_BUCKETS):
        raise IntegrityGateError("pool invariance requires every gamma bucket")
    counts = {gamma: len(values) for gamma, values in episodes_by_gamma.items()}
    if len(set(counts.values())) != 1 or not next(iter(counts.values())):
        raise IntegrityGateError(
            "pool invariance gamma bucket counts differ or are empty"
        )
    coverage_counts = {
        budget: {gamma: 0 for gamma in GAMMA_BUCKETS} for budget in BUDGET_CANDIDATES
    }
    strata = (DECONFOUNDED_STRATUM, "hops_5", "hops_6_plus")
    stratum_counts = {
        stratum: {
            budget: {gamma: 0 for gamma in GAMMA_BUCKETS}
            for budget in BUDGET_CANDIDATES
        }
        for stratum in strata
    }
    stratum_totals = dict.fromkeys(strata, 0)
    baseline = episodes_by_gamma[GAMMA_BUCKETS[0]]
    for index, base in enumerate(baseline):
        stratum = coverage_stratum(target_hop_distance(base))
        stratum_totals[stratum] += 1
        structural_sha256 = canonical_sha256(_structural_projection(base.visible))
        base_targets = set(base.hidden["target_nodes"])
        for gamma in GAMMA_BUCKETS[1:]:
            candidate = episodes_by_gamma[gamma][index]
            if candidate.paired_world_id != base.paired_world_id:
                raise IntegrityGateError("gamma buckets are not paired by world")
            if (
                canonical_sha256(_structural_projection(candidate.visible))
                != structural_sha256
            ):
                raise IntegrityGateError("paired structure changed across gamma")
            if set(candidate.hidden["target_nodes"]) != base_targets:
                raise IntegrityGateError("paired targets changed across gamma")
        for budget in BUDGET_CANDIDATES:
            indicators: list[bool] = []
            baseline_pool: list[int] | None = None
            for gamma in GAMMA_BUCKETS:
                episode = episodes_by_gamma[gamma][index]
                pool = structural_bfs_pool(episode.visible, budget)
                if baseline_pool is None:
                    baseline_pool = pool
                elif pool != baseline_pool:
                    raise IntegrityGateError(
                        "DIRECT pool membership changed across gamma"
                    )
                by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}
                reached = {by_id[edge_id]["target"] for edge_id in pool}
                indicator = set(episode.hidden["target_nodes"]) <= reached
                indicators.append(indicator)
                coverage_counts[budget][gamma] += indicator
                stratum_counts[stratum][budget][gamma] += indicator
            if len(set(indicators)) != 1:
                raise IntegrityGateError(
                    "DIRECT target-in-pool indicator changed across gamma"
                )
    denominator = len(baseline)
    coverage = {
        str(budget): {
            f"{gamma:.1f}": coverage_counts[budget][gamma] / denominator
            for gamma in GAMMA_BUCKETS
        }
        for budget in BUDGET_CANDIDATES
    }
    coverage_by_stratum = {
        stratum: {
            str(budget): {
                f"{gamma:.1f}": (
                    stratum_counts[stratum][budget][gamma] / stratum_totals[stratum]
                    if stratum_totals[stratum]
                    else None
                )
                for gamma in GAMMA_BUCKETS
            }
            for budget in BUDGET_CANDIDATES
        }
        for stratum in strata
    }
    return {
        "gate": "direct_pool_invariance",
        "passed": True,
        "episode_count_per_gamma": denominator,
        "coverage": coverage,
        "coverage_by_stratum": coverage_by_stratum,
        "episode_count_by_stratum": stratum_totals,
        "gated_stratum": DECONFOUNDED_STRATUM,
    }


def wilson_upper_bound(successes: int, total: int) -> float:
    if total <= 0 or not 0 <= successes <= total:
        raise IntegrityGateError("invalid binomial counts for Wilson bound")
    p = successes / total
    z = ONE_SIDED_95_Z
    denominator = 1 + z * z / total
    center = p + z * z / (2 * total)
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return (center + radius) / denominator


def _edge_target_ranks(episode: GeneratedEpisode) -> tuple[int, ...]:
    pool = structural_bfs_pool(episode.visible, 128)
    by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}
    first_rank: dict[int, int] = {}
    for rank, edge_id in enumerate(pool):
        first_rank.setdefault(by_id[edge_id]["target"], rank)
    return tuple(
        first_rank.get(node, len(pool)) // 8 for node in episode.hidden["target_nodes"]
    )


def _features(episode: GeneratedEpisode) -> dict[str, str]:
    edges = episode.visible["edges"]
    start = episode.visible["start_node"]
    start_degree = sum(edge["source"] == start for edge in edges)
    target_ranks = _edge_target_ranks(episode)
    direct_pool = structural_bfs_pool(episode.visible, 128)
    edge_by_id = {edge["edge_id"]: edge for edge in edges}
    candidate_count = len({edge_by_id[edge_id]["target"] for edge_id in direct_pool})
    route_edges = sorted(
        {edge_id for route in episode.hidden["valid_routes"] for edge_id in route}
    )
    return {
        "degree": str(start_degree),
        "candidate_count": str(candidate_count // 8),
        "candidate_position": ",".join(map(str, target_ranks)),
        "serialization_order": ",".join(str(value // 32) for value in route_edges),
        "episode_length": str(len(episode.visible["query_relations"])),
    }


def _majority_label(counts: Counter[int | bool]) -> int | bool:
    if not counts:
        raise IntegrityGateError("cannot fit a lookup probe without labels")
    return min(counts, key=lambda value: (-counts[value], int(value)))


def _fit_lookup_probes(
    episodes: Iterable[GeneratedEpisode], *, conditional: bool
) -> tuple[dict[str, dict[str, int | bool]], dict[str, int | bool], int]:
    per_feature: dict[str, dict[str, Counter[int | bool]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    global_counts: dict[str, Counter[int | bool]] = defaultdict(Counter)
    observed = 0
    for episode in episodes:
        if conditional and episode.hidden["abstain"]:
            continue
        label: int | bool = (
            episode.hidden["gold_assertion_mask"]
            if conditional
            else bool(episode.hidden["abstain"])
        )
        if label is None:
            raise IntegrityGateError("non-abstain probe record has no assertion label")
        for name, value in _features(episode).items():
            per_feature[name][value][label] += 1
            global_counts[name][label] += 1
        observed += 1
    models = {
        name: {
            value: _majority_label(label_counts)
            for value, label_counts in categories.items()
        }
        for name, categories in per_feature.items()
    }
    defaults = {
        name: _majority_label(label_counts)
        for name, label_counts in global_counts.items()
    }
    return models, defaults, observed


def _score_lookup_probes(
    episodes: Iterable[GeneratedEpisode],
    *,
    models: dict[str, dict[str, int | bool]],
    defaults: dict[str, int | bool],
    conditional: bool,
) -> tuple[dict[str, int], int]:
    correct = {name: 0 for name in models}
    observed = 0
    for episode in episodes:
        if conditional and episode.hidden["abstain"]:
            continue
        label: int | bool = (
            episode.hidden["gold_assertion_mask"]
            if conditional
            else bool(episode.hidden["abstain"])
        )
        for name, value in _features(episode).items():
            predicted = models[name].get(value, defaults[name])
            correct[name] += predicted == label
        observed += 1
    return correct, observed


def shortcut_probe_gate(
    fit_episodes: Sequence[GeneratedEpisode],
    evaluation_episodes: Sequence[GeneratedEpisode],
    *,
    require_preregistered_counts: bool = True,
) -> dict[str, Any]:
    if require_preregistered_counts and (
        len(fit_episodes) != 120_000 or len(evaluation_episodes) != 30_000
    ):
        raise IntegrityGateError(
            "shortcut probes require the preregistered 120k/30k partition"
        )
    return shortcut_probe_gate_streaming(
        fit_factory=lambda: iter(fit_episodes),
        evaluation_factory=lambda: iter(evaluation_episodes),
        expected_fit_count=(120_000 if require_preregistered_counts else None),
        expected_evaluation_count=(30_000 if require_preregistered_counts else None),
    )


def shortcut_probe_gate_streaming(
    *,
    fit_factory: Callable[[], Iterator[GeneratedEpisode]],
    evaluation_factory: Callable[[], Iterator[GeneratedEpisode]],
    expected_fit_count: int | None = 120_000,
    expected_evaluation_count: int | None = 30_000,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for stratum, conditional, chance in (
        ("non_abstain_exact_set", True, 1 / 15),
        ("abstain_binary", False, 0.75),
    ):
        models, defaults, fit_count = _fit_lookup_probes(
            fit_factory(), conditional=conditional
        )
        correct, evaluation_count = _score_lookup_probes(
            evaluation_factory(),
            models=models,
            defaults=defaults,
            conditional=conditional,
        )
        expected_fit = (
            None
            if expected_fit_count is None
            else (expected_fit_count * 3 // 4 if conditional else expected_fit_count)
        )
        expected_evaluation = (
            None
            if expected_evaluation_count is None
            else (
                expected_evaluation_count * 3 // 4
                if conditional
                else expected_evaluation_count
            )
        )
        if expected_fit is not None and fit_count != expected_fit:
            raise IntegrityGateError(
                f"shortcut probe fit count differs: {fit_count} != {expected_fit}"
            )
        if expected_evaluation is not None and evaluation_count != expected_evaluation:
            raise IntegrityGateError(
                "shortcut probe evaluation count differs: "
                f"{evaluation_count} != {expected_evaluation}"
            )
        feature_results: dict[str, Any] = {}
        for feature, successes in sorted(correct.items()):
            point = successes / evaluation_count
            upper = wilson_upper_bound(successes, evaluation_count)
            passed = upper <= chance + MAX_PROBE_EXCESS
            feature_results[feature] = {
                "correct": successes,
                "n": evaluation_count,
                "accuracy": point,
                "upper_95_one_sided": upper,
                "chance": chance,
                "maximum_allowed_upper": chance + MAX_PROBE_EXCESS,
                "passed": passed,
            }
            if not passed:
                raise IntegrityGateError(
                    f"shortcut feature {feature} predicts {stratum} above its bound"
                )
        results[stratum] = {
            "fit_count": fit_count,
            "evaluation_count": evaluation_count,
            "features": feature_results,
        }
    return {"gate": "shortcut_probes", "passed": True, "strata": results}


def make_dire_variant(episode: GeneratedEpisode) -> GeneratedEpisode:
    """Sever the shared route prefix while retaining local endpoint features."""

    routes = [tuple(route) for route in episode.hidden["valid_routes"]]
    if len(routes) < 2:
        raise IntegrityGateError("DiRe requires at least two valid routes")
    common = set(routes[0]).intersection(*map(set, routes[1:]))
    ordered_common = [edge_id for edge_id in routes[0] if edge_id in common]
    if not ordered_common:
        raise IntegrityGateError("DiRe episode has no indispensable shared edge")
    severed_id = ordered_common[0]
    route_edge_ids = {edge_id for route in routes for edge_id in route}
    for candidate in episode.visible["edges"]:
        if candidate["edge_id"] == severed_id or candidate["edge_id"] in route_edge_ids:
            continue
        visible = copy.deepcopy(episode.visible)
        left = visible["edges"][severed_id]
        right = visible["edges"][candidate["edge_id"]]
        left["target"], right["target"] = right["target"], left["target"]
        try:
            solved = independently_solve(visible, allow_disconnected=True)
        except IntegrityGateError:
            continue
        if solved["valid_routes"]:
            continue
        hidden = copy.deepcopy(episode.hidden)
        hidden.update(solved)
        hidden["record_kind"] = "read_episode_hidden_dire"
        hidden["dire_source_episode_sha256"] = canonical_sha256(
            {"visible": episode.visible, "hidden": episode.hidden}
        )
        return GeneratedEpisode(
            episode_id=f"{episode.episode_id}-dire",
            paired_world_id=episode.paired_world_id,
            visible=visible,
            hidden=hidden,
        )
    raise IntegrityGateError("could not construct a disconnected DiRe variant")


def dire_gate(
    episodes: Iterable[GeneratedEpisode], *, maximum_episodes: int | None = None
) -> dict[str, Any]:
    checked = 0
    for episode in episodes:
        variant = make_dire_variant(episode)
        if variant.hidden["valid_routes"] or not variant.hidden["abstain"]:
            raise IntegrityGateError("DiRe variant remains answerable")
        if episode.visible["nodes"] != variant.visible["nodes"]:
            raise IntegrityGateError("DiRe changed endpoint-local node features")
        if len(episode.visible["edges"]) != len(variant.visible["edges"]):
            raise IntegrityGateError("DiRe changed candidate count")
        before_similarity = sorted(
            edge["query_similarity_ppm"] for edge in episode.visible["edges"]
        )
        after_similarity = sorted(
            edge["query_similarity_ppm"] for edge in variant.visible["edges"]
        )
        if before_similarity != after_similarity:
            raise IntegrityGateError("DiRe changed query-similarity marginals")
        if len(canonical_bytes(episode.visible)) != len(
            canonical_bytes(variant.visible)
        ):
            raise IntegrityGateError("DiRe changed serialized episode length")
        checked += 1
        if maximum_episodes is not None and checked >= maximum_episodes:
            break
    if checked == 0:
        raise IntegrityGateError("DiRe gate received no episodes")
    return {"gate": "dire_control", "passed": True, "episode_count": checked}


def dire_shortcut_probe_gate_streaming(
    *,
    fit_factory: Callable[[], Iterator[GeneratedEpisode]],
    evaluation_factory: Callable[[], Iterator[GeneratedEpisode]],
    expected_fit_count: int | None = 120_000,
    expected_evaluation_count: int | None = 30_000,
) -> dict[str, Any]:
    """Check that nuisance-only lookup cannot recover disconnected answers."""

    models, defaults, fit_count = _fit_lookup_probes(fit_factory(), conditional=True)
    correct = {name: 0 for name in models}
    evaluated = 0
    structural_checks = 0
    for episode in evaluation_factory():
        variant = make_dire_variant(episode)
        structural_checks += 1
        if episode.hidden["abstain"]:
            continue
        # The operational DiRe label is ABSTAIN. For the shortcut diagnostic,
        # preserve the original hidden answer only long enough to ask whether
        # nuisance features can recover it after the indispensable edge is gone.
        diagnostic = GeneratedEpisode(
            episode_id=variant.episode_id,
            paired_world_id=variant.paired_world_id,
            visible=variant.visible,
            hidden=episode.hidden,
        )
        label = episode.hidden["gold_assertion_mask"]
        for name, value in _features(diagnostic).items():
            predicted = models[name].get(value, defaults[name])
            correct[name] += predicted == label
        evaluated += 1
    expected_fit = None if expected_fit_count is None else expected_fit_count * 3 // 4
    expected_evaluation = (
        None
        if expected_evaluation_count is None
        else expected_evaluation_count * 3 // 4
    )
    if expected_fit is not None and fit_count != expected_fit:
        raise IntegrityGateError("DiRe fit count differs from the preregistration")
    if (
        expected_evaluation_count is not None
        and structural_checks != expected_evaluation_count
    ):
        raise IntegrityGateError(
            "DiRe structural count differs from the preregistration"
        )
    if expected_evaluation is not None and evaluated != expected_evaluation:
        raise IntegrityGateError(
            "DiRe diagnostic count differs from the preregistration"
        )
    features: dict[str, Any] = {}
    for name, successes in sorted(correct.items()):
        upper = wilson_upper_bound(successes, evaluated)
        passed = upper <= 1 / 15 + MAX_PROBE_EXCESS
        features[name] = {
            "correct": successes,
            "n": evaluated,
            "accuracy": successes / evaluated,
            "upper_95_one_sided": upper,
            "chance": 1 / 15,
            "maximum_allowed_upper": 1 / 15 + MAX_PROBE_EXCESS,
            "passed": passed,
        }
        if not passed:
            raise IntegrityGateError(
                f"DiRe shortcut feature {name} recovers disconnected answers"
            )
    return {
        "gate": "dire_control",
        "passed": True,
        "fit_count": fit_count,
        "structural_episode_count": structural_checks,
        "diagnostic_episode_count": evaluated,
        "features": features,
    }


def assert_world_family_disjoint(
    episodes_by_split: dict[str, Iterable[GeneratedEpisode]],
) -> dict[str, Any]:
    owners: dict[str, str] = {}
    counts: dict[str, int] = {}
    for split, episodes in episodes_by_split.items():
        count = 0
        seen_within: set[str] = set()
        for episode in episodes:
            world = episode.paired_world_id
            if world in seen_within:
                # The same world is expected across gamma, but a single split
                # iterator supplied here must represent only one gamma bucket.
                raise IntegrityGateError(f"duplicate world within {split}: {world}")
            seen_within.add(world)
            prior = owners.setdefault(world, split)
            if prior != split:
                raise IntegrityGateError(
                    f"world family overlaps {prior} and {split}: {world}"
                )
            count += 1
        counts[split] = count
    return {"passed": True, "world_counts": counts}


def select_main_budget(pool_gate: dict[str, Any]) -> int:
    if pool_gate.get("gate") != "direct_pool_invariance" or not pool_gate.get("passed"):
        raise IntegrityGateError("budget selection requires a passed pool gate")
    # Amendment 02: gate on the de-confounded stratum only. Applying the
    # threshold to the aggregate deletes the depth regime the experiment exists
    # to measure, because there coverage loss is the mechanism, not a confound.
    try:
        stratum = pool_gate["coverage_by_stratum"][DECONFOUNDED_STRATUM]
    except KeyError as exc:
        raise IntegrityGateError(
            "budget selection requires per-stratum coverage under Amendment 02"
        ) from exc
    if not pool_gate.get("episode_count_by_stratum", {}).get(DECONFOUNDED_STRATUM):
        raise IntegrityGateError("de-confounded stratum is empty")
    for budget in BUDGET_CANDIDATES:
        coverage = stratum[str(budget)]["0.0"]
        if coverage is not None and coverage > 0.9:
            return budget
    raise IntegrityGateError(
        "no preregistered budget exceeds 90% DIRECT target-in-pool coverage"
    )
