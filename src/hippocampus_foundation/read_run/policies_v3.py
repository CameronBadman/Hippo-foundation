"""Model-free walks under Track P's rules: no budget, cost in expansions.

`policies_v2` measured its policies under an edge budget and an edge cost. Two
things the Track P design changed, and every policy here shares them so no
policy gets a free node:

- **The cost unit is expansions** (node reads), because the featurisers read a
  node's whole out-edge group and whole-group examination is what must be paid
  for. Edges examined are reported beside expansions, deduplicated per edge.
- **There is no budget.** A walk runs until its stop rule fires or its frontier
  is empty. States deduplicate on `(node, depth)` and the frontier holds only
  relation-matching entries keyed by `(edge_id, depth)`, so exhaustion is
  bounded by construction.

Three further rules, all identical across policies and matching what the
successor model does:

- **Endpoints register at examination.** When the depth-(L−1) matching edge is
  examined — that is, when its source is expanded — its target is an endpoint
  from that moment, and its assertion mask is read without expanding it. This
  is the structural form of the §2.19 fix; here it also means every policy pays
  the same constant for reaching an endpoint.
- **Route-completeness** is examined-set coverage of both *target* routes
  (`coverage.route_coverage_v3`); reaching a distractor endpoint is descriptive.
- **Expansions at RC** is the expansion count at the moment the second target
  was registered; a stop rule that fires before it has failed the episode.

`oracle_trace` reads hidden truth: it expands exactly the route source states,
which is the floor no expansion policy can beat. A reference for reports, never
a policy input.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .coverage import route_coverage_v3
from .generator import GeneratedEpisode
from .model import _structural_order

__all__ = [
    "POLICIES_V3",
    "WalkTrace",
    "bfs_two_stop_trace",
    "blind_exhaust_trace",
    "oracle_trace",
    "policy_row_v3",
    "policy_traces",
    "similarity_exhaust_trace",
    "stop_aware_trace",
]

STOP_TWO_ENDPOINTS = "two_endpoints"
STOP_EXHAUSTED = "exhausted"
STOP_TARGETS = "targets_registered"


@dataclass
class WalkTrace:
    """What one walk did, in the order it did it."""

    examined: list[int] = field(default_factory=list)
    expansions: int = 0
    endpoints: list[int] = field(default_factory=list)
    expansions_at_endpoint: list[int] = field(default_factory=list)
    stop_reason: str = STOP_EXHAUSTED


OrderKey = Callable[[dict[str, int], int, int], tuple[Any, ...]]


def _walk(
    visible: dict[str, Any],
    *,
    order: OrderKey,
    stop_at_two: bool,
    expandable: Callable[[int, int], bool] | None = None,
    stop_when_targets: set[int] | None = None,
) -> WalkTrace:
    """The shared mechanics. `order` ranks frontier entries (lowest first).

    `expandable(node, depth)` restricts which states may be expanded (the
    oracle); `stop_when_targets` stops the walk once every listed endpoint is
    registered (the oracle's stop, which reads hidden truth).
    """

    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)
    for values in by_source.values():
        values.sort(key=lambda edge: _structural_order(visible["router_seed"], edge))
    relations = visible["query_relations"]
    length = len(relations)

    trace = WalkTrace()
    scored: set[int] = set()
    expanded: set[tuple[int, int]] = set()
    seen_endpoints: set[int] = set()
    frontier: dict[tuple[int, int], tuple[Any, ...]] = {}
    by_key_edge: dict[tuple[int, int], dict[str, int]] = {}

    def expand(node: int, depth: int) -> None:
        expanded.add((node, depth))
        trace.expansions += 1
        for rank, edge in enumerate(by_source[node]):
            if edge["edge_id"] not in scored:
                scored.add(edge["edge_id"])
                trace.examined.append(edge["edge_id"])
            if edge["relation"] != relations[depth]:
                continue
            if depth + 1 == length:
                if edge["target"] not in seen_endpoints:
                    seen_endpoints.add(edge["target"])
                    trace.endpoints.append(edge["target"])
                    trace.expansions_at_endpoint.append(trace.expansions)
                continue
            key = (edge["edge_id"], depth + 1)
            if key not in frontier and (edge["target"], depth + 1) not in expanded:
                frontier[key] = order(edge, depth + 1, rank)
                by_key_edge[key] = edge

    expand(visible["start_node"], 0)
    while True:
        if stop_at_two and len(trace.endpoints) >= 2:
            trace.stop_reason = STOP_TWO_ENDPOINTS
            break
        if stop_when_targets is not None and stop_when_targets <= seen_endpoints:
            trace.stop_reason = STOP_TARGETS
            break
        if not frontier:
            trace.stop_reason = STOP_EXHAUSTED
            break
        key = min(frontier, key=lambda k: (frontier[k], k))
        frontier.pop(key)
        edge = by_key_edge.pop(key)
        node, depth = edge["target"], key[1]
        if (node, depth) in expanded:
            continue
        if expandable is not None and not expandable(node, depth):
            continue
        expand(node, depth)
    return trace


def _bfs_order(edge: dict[str, int], depth: int, rank: int) -> tuple[Any, ...]:
    """Breadth-first: shallower first, then the source group's structural order."""

    return (depth, edge["source"], rank)


def _similarity_order(edge: dict[str, int], depth: int, rank: int) -> tuple[Any, ...]:
    """Best-first on published similarity; lowest edge id on a tie."""

    return (-edge["query_similarity_ppm"], edge["edge_id"])


def blind_exhaust_trace(visible: dict[str, Any]) -> WalkTrace:
    """Relation-following BFS to exhaustion; ignores similarity."""

    return _walk(visible, order=_bfs_order, stop_at_two=False)


def bfs_two_stop_trace(visible: dict[str, Any]) -> WalkTrace:
    """Relation-following BFS that stops at two distinct endpoints."""

    return _walk(visible, order=_bfs_order, stop_at_two=True)


def similarity_exhaust_trace(visible: dict[str, Any]) -> WalkTrace:
    """Relation-gated similarity best-first to exhaustion."""

    return _walk(visible, order=_similarity_order, stop_at_two=False)


def stop_aware_trace(visible: dict[str, Any]) -> WalkTrace:
    """Relation-gated similarity best-first that stops at two distinct endpoints.

    v2's strongest model-free policy under the new rules. On v3 data its
    constant-2 stop is a real decision: the first two endpoints it registers
    need not be the targets.
    """

    return _walk(visible, order=_similarity_order, stop_at_two=True)


def oracle_trace(episode: GeneratedEpisode) -> WalkTrace:
    """Expand exactly the target routes' source states; stop when both register.

    Reads `valid_routes` and `target_nodes` from hidden truth. Its expansion
    count is the floor: every one of those states must be expanded to examine
    the route edge it sources, and nothing else is.
    """

    visible = episode.visible
    by_id = {edge["edge_id"]: edge for edge in visible["edges"]}
    route_states = {
        (by_id[edge_id]["source"], depth)
        for route in episode.hidden["valid_routes"]
        for depth, edge_id in enumerate(route)
    }
    return _walk(
        visible,
        order=_bfs_order,
        stop_at_two=False,
        expandable=lambda node, depth: (node, depth) in route_states,
        stop_when_targets=set(episode.hidden["target_nodes"]),
    )


POLICIES_V3: dict[str, Callable[[dict[str, Any]], WalkTrace]] = {
    "blind_exhaust": blind_exhaust_trace,
    "bfs_two_stop": bfs_two_stop_trace,
    "similarity_exhaust": similarity_exhaust_trace,
    "stop_aware": stop_aware_trace,
}


def policy_traces(visible: dict[str, Any]) -> dict[str, WalkTrace]:
    return {name: policy(visible) for name, policy in POLICIES_V3.items()}


def policy_row_v3(episode: GeneratedEpisode, trace: WalkTrace) -> dict[str, Any]:
    """The reportable quantities for one walk on one episode."""

    targets = set(episode.hidden["target_nodes"])
    coverage = route_coverage_v3(episode, trace.examined)
    on_route = {
        edge_id for route in episode.hidden["valid_routes"] for edge_id in route
    }
    registered = [
        count
        for endpoint, count in zip(
            trace.endpoints, trace.expansions_at_endpoint, strict=True
        )
        if endpoint in targets
    ]
    expansions_at_rc = registered[1] if len(registered) >= 2 else None
    # Set-based coverage and the walk's own knowledge can disagree: a target's
    # final edge can enter the examined set because its source was expanded at
    # a *different* depth, and a stop can fire before the correct-depth prefix
    # is ever popped. Coverage then says complete while the walk registered
    # only one target. Both are reported; `expansions_at_rc` and the overhead
    # are defined on registration, which is what a stop decision can see.
    targets_registered = targets <= set(trace.endpoints)
    complete_but_unregistered = bool(coverage["route_complete"]) and not (
        targets_registered
    )
    # One expansion can register several endpoints at once — a depth-(L−1)
    # node whose group holds a target's final edge and a sibling distractor's —
    # so a two-endpoint stop may hold more than two and "the first two" is not
    # well defined. The selectivity question is whether *everything* registered
    # at the stop is a target.
    registered_only_targets = bool(trace.endpoints) and set(trace.endpoints) <= targets
    return {
        "route_complete": bool(coverage["route_complete"]),
        "targets_registered": targets_registered,
        "complete_but_unregistered": complete_but_unregistered,
        "stop_reason": trace.stop_reason,
        "expansions": trace.expansions,
        "expansions_at_rc": expansions_at_rc,
        "overhead_expansions": (
            trace.expansions - expansions_at_rc
            if expansions_at_rc is not None
            else None
        ),
        "edges_examined": len(trace.examined),
        "on_route_examined": len(on_route & set(trace.examined)),
        "precision": (
            len(on_route & set(trace.examined)) / len(trace.examined)
            if trace.examined
            else 0.0
        ),
        "endpoints_registered": len(trace.endpoints),
        "distractor_endpoints_reached": len(coverage["distractor_endpoints_reached"]),
        "registered_only_targets": registered_only_targets,
    }
