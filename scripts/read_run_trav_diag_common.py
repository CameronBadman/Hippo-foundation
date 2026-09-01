"""Shared feature extraction for the TRAV edge-selection diagnostic at gamma=0.

Diagnostic only. Reuses production code wherever it exists rather than
reimplementing it: `structural_bfs_pool` and `_structural_order`-equivalent
ordering come from the generator/model modules directly, `wilson_upper_bound`
from gates.py, `score_prediction`/`decode_best_routes` from evaluation.py.

One interpretive substitution, disclosed here and in the report: the task asks
for "hop distance from nearest router seed". `router_seed` is not a placed
node -- it is the hex string that orders each node's outgoing edges (see
`generator._edge_order_key`). This was already established and corrected once
this session. Substituted: hop distance from `start_node` (the traversal
root), via BFS over the same visible edges `gates.target_hop_distance` uses.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict, deque
from typing import Any

from hippocampus_foundation.read_run.gates import wilson_upper_bound
from hippocampus_foundation.read_run.generator import (
    GeneratedEpisode,
)

FEATURES = (
    "degree",
    "local_rank",
    "hop_distance",
    "relation",
    "global_position",
)


def _order_key(router_seed: str, edge: dict[str, int]) -> bytes:
    material = (
        f"{router_seed}:{edge['source']}:{edge['target']}:{edge['relation']}:"
        f"{edge['edge_id']}"
    ).encode()
    return hashlib.sha256(material).digest()


def episode_index(episode: GeneratedEpisode) -> dict[str, Any]:
    """Precompute the per-episode structures every feature function needs."""

    edges = episode.visible["edges"]
    by_id = {edge["edge_id"]: edge for edge in edges}
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in edges:
        by_source[edge["source"]].append(edge)
    router_seed = episode.visible["router_seed"]
    local_rank: dict[int, int] = {}
    for values in by_source.values():
        ordered = sorted(values, key=lambda edge: _order_key(router_seed, edge))
        for rank, edge in enumerate(ordered):
            local_rank[edge["edge_id"]] = rank
    global_position = {edge["edge_id"]: index for index, edge in enumerate(edges)}
    degree = {edge["edge_id"]: len(by_source[edge["source"]]) for edge in edges}

    start = episode.visible["start_node"]
    distance = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for edge in by_source[node]:
            if edge["target"] not in distance:
                distance[edge["target"]] = distance[node] + 1
                queue.append(edge["target"])
    unreachable = len(episode.visible["nodes"]) + 1
    hop_distance = {
        edge["edge_id"]: distance.get(edge["source"], unreachable) for edge in edges
    }

    on_path = {edge_id for route in episode.hidden["valid_routes"] for edge_id in route}
    target_nodes = set(episode.hidden["target_nodes"])
    is_target_assertion = {
        edge["edge_id"]: edge["target"] in target_nodes for edge in edges
    }

    return {
        "by_id": by_id,
        "local_rank": local_rank,
        "global_position": global_position,
        "degree": degree,
        "hop_distance": hop_distance,
        "on_path": on_path,
        "is_target_assertion": is_target_assertion,
        "n_edges": len(edges),
    }


def features(index: dict[str, Any], edge_id: int) -> dict[str, int]:
    edge = index["by_id"][edge_id]
    return {
        "degree": index["degree"][edge_id],
        "local_rank": index["local_rank"][edge_id],
        "hop_distance": index["hop_distance"][edge_id],
        "relation": edge["relation"],
        "global_position": index["global_position"][edge_id],
    }


def bucket(feature_name: str, value: int) -> int:
    """Discretize a raw feature value for distribution/probe comparison.

    Matches the bucketing granularity already used in this codebase's own
    shortcut probes (`gates._features` divides by 8 or 32); the divisor here
    is chosen per feature so that a typical episode's edges spread over a
    double-digit number of buckets rather than collapsing to one or exploding
    to thousands.
    """

    if feature_name == "relation":
        return value  # already small and categorical (<=16 relation types)
    if feature_name == "local_rank":
        return min(value, 15)
    if feature_name == "hop_distance":
        return min(value, 10)
    if feature_name == "degree":
        return min(value // 4, 15)
    if feature_name == "global_position":
        return min(value // 16, 63)
    raise ValueError(feature_name)


# --------------------------------------------------------------------------
# Distribution comparison
# --------------------------------------------------------------------------


def total_variation(p: Counter[int], q: Counter[int]) -> float:
    keys = set(p) | set(q)
    total_p, total_q = sum(p.values()), sum(q.values())
    return 0.5 * sum(abs(p.get(k, 0) / total_p - q.get(k, 0) / total_q) for k in keys)


def kl_divergence(p: Counter[int], q: Counter[int], epsilon: float = 1e-6) -> float:
    """KL(p || q) with additive smoothing over the union of observed buckets.

    Smoothing is disclosed rather than silent: a bucket populated under `p`
    but never observed under `q` is exactly the "chosen edges land somewhere
    the available population never does" signal this diagnostic is looking
    for, so it is reported (as a large but finite KL) rather than suppressed.
    """

    keys = set(p) | set(q)
    total_p, total_q = sum(p.values()), sum(q.values())
    n = len(keys)
    out = 0.0
    for k in keys:
        pk = (p.get(k, 0) + epsilon) / (total_p + epsilon * n)
        qk = (q.get(k, 0) + epsilon) / (total_q + epsilon * n)
        out += pk * math.log(pk / qk)
    return out


# --------------------------------------------------------------------------
# The "as in P0 gate 3" trivial classifier: majority-vote per bucketed value,
# fit on one half of episodes and scored on the other, matching
# `gates._fit_lookup_probes` / `_score_lookup_probes` exactly in spirit.
# --------------------------------------------------------------------------


def fit_edge_probe(
    rows: list[tuple[dict[str, Any], int, bool]], feature_name: str
) -> tuple[dict[int, bool], bool, dict[int, tuple[int, int]]]:
    per_bucket: dict[int, Counter[bool]] = defaultdict(Counter)
    overall: Counter[bool] = Counter()
    for index, edge_id, label in rows:
        b = bucket(feature_name, features(index, edge_id)[feature_name])
        per_bucket[b][label] += 1
        overall[label] += 1
    default = overall[True] >= overall[False]
    model = {b: (counts[True] >= counts[False]) for b, counts in per_bucket.items()}
    # (positives, total) per bucket, on the FIT set -- kept so the report can
    # show the single most target-enriched bucket even when it never crosses
    # the 50% threshold needed to flip that bucket's majority vote. At the
    # base rates here (1-3% positive), majority-vote-per-bucket is close to
    # insensitive: a real 5-10x local enrichment still loses to "always
    # predict the global majority" unless it clears 50%. This statistic is
    # what actually catches a shortcut at this base rate; raw accuracy alone
    # would not.
    bucket_rates = {
        b: (counts[True], sum(counts.values())) for b, counts in per_bucket.items()
    }
    return model, default, bucket_rates


def score_edge_probe(
    rows: list[tuple[dict[str, Any], int, bool]],
    feature_name: str,
    model: dict[int, bool],
    default: bool,
) -> tuple[int, int]:
    correct = 0
    for index, edge_id, label in rows:
        b = bucket(feature_name, features(index, edge_id)[feature_name])
        predicted = model.get(b, default)
        correct += predicted == label
    return correct, len(rows)


def probe_report(
    correct: int,
    total: int,
    base_rate: float,
    bucket_rates: dict[int, tuple[int, int]],
) -> dict[str, Any]:
    """Accuracy alone is uninformative at a 1-3% positive base rate: a probe
    that always predicts the majority class scores ~(1 - base_rate) without
    having learned anything. `excess_over_constant_baseline` is accuracy minus
    that constant-baseline accuracy, the quantity that actually signals
    information beyond the class prior. `max_bucket_lift` is the largest
    per-bucket positive rate observed on the fit set, divided by the base
    rate, restricted to buckets with at least 30 fit-set examples so a lift
    is not manufactured by a near-empty bucket.
    """

    accuracy = correct / total if total else None
    constant_baseline = max(base_rate, 1 - base_rate)
    lifts = [
        (positives / support) / base_rate
        for positives, support in bucket_rates.values()
        if support >= 30 and base_rate > 0
    ]
    return {
        "n": total,
        "correct": correct,
        "accuracy": accuracy,
        "wilson_upper_bound": wilson_upper_bound(correct, total) if total else None,
        "constant_baseline_accuracy": constant_baseline,
        "excess_over_constant_baseline": (
            accuracy - constant_baseline if accuracy is not None else None
        ),
        "max_bucket_lift_over_base_rate": max(lifts) if lifts else None,
        "buckets_at_or_above_30_fit_examples": len(
            [s for _p, s in bucket_rates.values() if s >= 30]
        ),
    }
