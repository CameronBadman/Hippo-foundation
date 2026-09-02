"""Route-completeness: the coverage that proof-valid exact-set scoring needs.

`direct_pool_invariance_gate` (P0 gate 7) reports the fraction of episodes
whose *target node* lies within an examined edge set. Proof-valid scoring asks
a strictly stronger question. `evaluation.score_prediction` requires the
supplied routes to be valid *and* their endpoints to cover every target node,
and `evaluation.decode_best_routes` can only assemble a route from edges that
are already inside the examined set. An examined set can therefore contain the
target node and still be unable to produce any proof, whenever some edge of
every relation-matching route to that node is absent.

Gate 7's quantity is an upper bound on this one and can exceed it by a wide
margin. This module measures the stronger quantity directly: structurally, for
any arm, without a model and without a trained checkpoint.

It is deliberately written as a breadth-first frontier expansion over query
relation depth, rather than as a call into `decode_best_routes`, which is a
depth-first enumeration that also ranks and truncates. The two are independent
implementations of the same predicate, so they can be cross-checked against
each other; `tests/test_read_run_coverage.py` asserts that
`route_coverage(...)["route_complete"]` equals the evaluator's `proof_valid`
flag episode by episode.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from typing import Any

from .generator import GeneratedEpisode

ASSERTION_COUNT = 4


def reachable_endpoints(
    visible: dict[str, Any], examined_edge_ids: Sequence[int]
) -> set[int]:
    """Nodes reachable from the start by a full query-relation path inside the set.

    Expands one query relation at a time, so the returned nodes are exactly the
    endpoints of complete relation-matching paths that use only examined edges.
    """

    allowed = set(examined_edge_ids)
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        if edge["edge_id"] in allowed:
            by_source[edge["source"]].append(edge)
    frontier = {visible["start_node"]}
    for relation in visible["query_relations"]:
        advanced: set[int] = set()
        for node in frontier:
            for edge in by_source[node]:
                if edge["relation"] == relation:
                    advanced.add(edge["target"])
        frontier = advanced
        if not frontier:
            break
    return frontier


def relation_prefix_tree(visible: dict[str, Any]) -> set[int]:
    """Every edge on a path from the start whose relations match a query prefix.

    A walker that follows relations alone, with no lookahead and no similarity,
    cannot tell a route edge from a dead end that happens to carry the right
    relation at the right depth. It must examine all of them. This set is what
    it examines, so its size is the budget at which such a walker is
    route-complete with certainty, independent of gamma: query similarity is
    never consulted.

    Both planted routes are relation-matching paths from the start, so their
    edges are always contained here; the endpoints reachable through this set
    are exactly the targets. States are `(node, depth)` pairs because a node
    can sit at several depths of different matching paths, and a cycle can
    return one to an earlier node at a later depth.
    """

    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)
    relations = visible["query_relations"]
    tree: set[int] = set()
    frontier = {visible["start_node"]}
    for relation in relations:
        advanced: set[int] = set()
        for node in frontier:
            for edge in by_source[node]:
                if edge["relation"] == relation:
                    tree.add(edge["edge_id"])
                    advanced.add(edge["target"])
        frontier = advanced
        if not frontier:
            break
    return tree


def node_assertion_masks(visible: dict[str, Any]) -> dict[int, int]:
    """Recover each node's integer assertion mask from the visible payload."""

    masks: dict[int, int] = {}
    for node in visible["nodes"]:
        mask = 0
        for index in node["assertions"]:
            if index not in range(ASSERTION_COUNT):
                raise ValueError("assertion index is outside 0..3")
            mask |= 1 << index
        masks[node["node"]] = mask
    return masks


def route_coverage(
    episode: GeneratedEpisode, examined_edge_ids: Sequence[int]
) -> dict[str, Any]:
    """Route-completeness of one examined set, with gate 7's weaker quantity beside it.

    `route_complete` is the predicate proof-valid scoring actually depends on.
    `target_node_present` is the gate 7 analogue, reported alongside so the two
    can never again be conflated by a reader of the report.
    """

    targets = set(episode.hidden["target_nodes"])
    reached = reachable_endpoints(episode.visible, examined_edge_ids)
    allowed = set(examined_edge_ids)
    touched = {
        edge["target"]
        for edge in episode.visible["edges"]
        if edge["edge_id"] in allowed
    }
    touched.add(episode.visible["start_node"])
    return {
        "targets": sorted(targets),
        "endpoints_reached": sorted(reached),
        "route_complete": reached >= targets,
        "reaches_some_target": bool(reached & targets),
        "target_node_present": targets <= touched,
        # Generation enforces `set(candidate_paths) == expected_paths`, so the
        # only complete relation-matching paths in the whole graph are the two
        # constructed routes and every reachable endpoint must be a target.
        # A violation would falsify that premise, so it is checked, not assumed.
        "reached_outside_targets": sorted(reached - targets),
    }


def prefix_route_coverage(
    episode: GeneratedEpisode,
    examined_edge_ids: Sequence[int],
    budgets: Sequence[int],
) -> dict[int, dict[str, Any]]:
    """Route-coverage of the first `b` examined edges, for each budget `b`.

    Meaningful only for an examined list that is prefix-consistent in the
    budget: TRAV's walk appends whole expansion groups in a budget-independent
    order and truncates the final group in that order, and the structural BFS
    pool is a truncated BFS order, so for both the examined set at a smaller
    budget is a prefix of the set at a larger one. `tests/test_read_run_ablation.py`
    asserts that property on the model rather than assuming it. A budget beyond
    the list covers the whole list.
    """

    examined = list(examined_edge_ids)
    return {
        int(budget): route_coverage(episode, examined[: int(budget)])
        for budget in budgets
    }


def relation_walker_examined_set(visible: dict[str, Any], budget: int) -> list[int]:
    """The examined list of a model-free relation-following walker.

    This is the navigation ceiling a structural-only TRAV is read against. It
    walks under the model's own expansion mechanics — reaching a node examines
    every one of its out-edges, once — and follows relations alone: from state
    `(node, depth)` it steps along the out-edges whose relation is the query's
    relation at `depth`, stopping one step short of the query's end because a
    node at full depth is an endpoint and needs no expansion. States are
    breadth-first from `(start_node, 0)`, so the walker expands exactly the
    nodes reached by a matching prefix shorter than the query — dead ends
    included, since a node is only known to be a dead end once its out-edges
    have been examined — and nothing else. Its list is therefore a superset of
    `relation_prefix_tree`, which counts only the matching edges; with
    out-degree 3 it is route-complete at any budget of at least three edges
    per distinct expanded node, and it never consults `query_similarity_ppm`.

    Out-edges of one node are examined in `edge_id` order, which matters only
    for the group the budget truncates. The list is shorter than the budget
    when the tree is exhausted first: the walker has nowhere left to go.
    """

    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)
    for values in by_source.values():
        values.sort(key=lambda edge: edge["edge_id"])
    relations = visible["query_relations"]
    start = visible["start_node"]
    examined: list[int] = []
    scored: set[int] = set()
    expanded: set[int] = set()
    queue: deque[tuple[int, int]] = deque([(start, 0)])
    queued: set[tuple[int, int]] = {(start, 0)}
    while queue and len(examined) < budget:
        node, depth = queue.popleft()
        if node not in expanded:
            expanded.add(node)
            fresh = [
                edge["edge_id"]
                for edge in by_source[node]
                if edge["edge_id"] not in scored
            ][: budget - len(examined)]
            examined.extend(fresh)
            scored.update(fresh)
        if depth + 1 >= len(relations):
            continue
        for edge in by_source[node]:
            if edge["relation"] != relations[depth]:
                continue
            state = (edge["target"], depth + 1)
            if state not in queued:
                queued.add(state)
                queue.append(state)
    return examined


def summarize_route_coverage(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-episode coverage rows into the reportable counts."""

    if not rows:
        raise ValueError("cannot summarize an empty coverage set")
    total = len(rows)
    complete = sum(row["route_complete"] for row in rows)
    present = sum(row["target_node_present"] for row in rows)
    violations = sum(bool(row["reached_outside_targets"]) for row in rows)
    return {
        "episode_count": total,
        "route_complete": complete,
        "route_complete_fraction": complete / total,
        "target_node_present": present,
        "target_node_present_fraction": present / total,
        "gate7_overstatement_pp": 100.0 * (present - complete) / total,
        "reached_outside_targets_violations": violations,
    }
