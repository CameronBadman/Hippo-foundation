"""Model-free examined-set policies: the bar a learned Track O traversal must clear.

Track N's mistake, avoided here: reading a learned walk against the weakest
available reference. On the Track O generator these policies do not order
themselves the same way on the two quantities that matter, so there is no single
"baseline" to beat. Measured on `deg6_len8_v4_rep` at gamma 0.4, B = 64, the
blind relation walker is the most *precise* policy while the hybrid is the most
*complete* one, and neither dominates. `pareto_frontier` computes that frontier
so an outcome table can be written against it rather than against whichever
policy happens to flatter the model.

Every policy here is deterministic, parameter-free, and computable without a
GPU. Each mirrors `model._forward_trav_one`'s expansion mechanics exactly —
reaching a node examines all of its out-edges once, in `_structural_order`, and
a budget truncates the final group — so a policy's examined set and a model's
are the same kind of object and their precisions are comparable.

`oracle_floor` is the one quantity here that reads hidden truth: it is the floor
no examined-set policy can beat under whole-node expansion, used to bound how
much room any policy has. It is a reference for reports, never an input to a
model or a policy.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .coverage import relation_walker_examined_set, route_coverage
from .generator import GeneratedEpisode
from .greedy import greedy_examined_set
from .model import _structural_order

__all__ = [
    "blind_walker_examined_set",
    "greedy_similarity_examined_set",
    "hybrid_examined_set",
    "oracle_floor",
    "policy_examined_sets",
    "policy_row",
    "pareto_frontier",
    "POLICIES",
]


def blind_walker_examined_set(visible: dict[str, Any], budget: int) -> list[int]:
    """Relation-following walker: expands every node reached by a matching prefix.

    Ignores `query_similarity_ppm` entirely, so its coverage is invariant to
    gamma. Thin alias of `coverage.relation_walker_examined_set`, present so the
    ladder reads as one family.
    """

    return relation_walker_examined_set(visible, budget)


def greedy_similarity_examined_set(visible: dict[str, Any], budget: int) -> list[int]:
    """Similarity-greedy best-first walk, ignoring relations.

    Thin alias of `greedy.greedy_examined_set`; gamma degrades it by
    construction, which is what makes it the ladder's lower rung.
    """

    return greedy_examined_set(visible, budget)


def hybrid_examined_set(visible: dict[str, Any], budget: int) -> list[int]:
    """Relation-gated similarity walk: the strongest model-free policy measured.

    Best-first over a global frontier, ordering candidates by

        (edge relation matches the query at the candidate's own depth,
         query_similarity_ppm,
         -edge_id)

    so a relation-matching edge always outranks a non-matching one and
    similarity breaks ties within each class. Depth is carried per candidate —
    the depth of the node the edge would reach — rather than as a property of
    the walk, so a jump to a frontier edge discovered on another branch resumes
    at that edge's own depth. This is the model-free analogue of the
    path-scoped scoring the successor model implements, and it is why the
    policy is coherent under best-first jumps where a walk-scoped one would not
    be.

    Candidates whose target sits at full query depth are endpoints and are never
    expanded, matching `relation_walker_examined_set`.
    """

    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)
    for values in by_source.values():
        values.sort(key=lambda edge: _structural_order(visible["router_seed"], edge))
    by_id = {edge["edge_id"]: edge for edge in visible["edges"]}
    relations = visible["query_relations"]

    examined: list[int] = []
    scored: set[int] = set()
    expanded: set[int] = set()
    pending: dict[int, tuple[int, int, int]] = {}
    current, depth = visible["start_node"], 0
    while len(examined) < budget:
        if current not in expanded:
            expanded.add(current)
            fresh = [
                edge["edge_id"]
                for edge in by_source[current]
                if edge["edge_id"] not in scored
            ][: budget - len(examined)]
            for edge_id in fresh:
                edge = by_id[edge_id]
                matches = (
                    depth < len(relations) and edge["relation"] == relations[depth]
                )
                pending[edge_id] = (
                    1 if matches else 0,
                    edge["query_similarity_ppm"],
                    depth + 1,
                )
                examined.append(edge_id)
                scored.add(edge_id)
        if len(examined) >= budget or not pending:
            break
        chosen = max(
            pending,
            key=lambda edge_id: (
                pending[edge_id][0],
                pending[edge_id][1],
                -edge_id,
            ),
        )
        _match, _similarity, next_depth = pending.pop(chosen)
        if next_depth >= len(relations):
            continue
        current, depth = by_id[chosen]["target"], next_depth
    return examined


def oracle_floor(episode: GeneratedEpisode, *, out_degree: int) -> int:
    """Edges a perfect selector must still examine under whole-node expansion.

    Reaching a node examines every one of its out-edges, so even a policy that
    expands *only* the nodes that source a route edge pays `out_degree` per such
    node. Reads hidden truth; a reference for reports, never a policy input.
    """

    sources = {
        episode.visible["edges"][edge_id]["source"]
        for route in episode.hidden["valid_routes"]
        for edge_id in route
    }
    return out_degree * len(sources)


POLICIES = {
    "blind_walker": blind_walker_examined_set,
    "greedy_similarity": greedy_similarity_examined_set,
    "hybrid": hybrid_examined_set,
}


def policy_examined_sets(visible: dict[str, Any], budget: int) -> dict[str, list[int]]:
    """Every ladder policy's examined set for one episode at one budget."""

    return {name: policy(visible, budget) for name, policy in POLICIES.items()}


def policy_row(
    episode: GeneratedEpisode, examined_edge_ids: Sequence[int], *, budget: int
) -> dict[str, Any]:
    """The reportable quantities for one policy on one episode.

    `route_complete` is the coverage half; `precision` is the fraction of the
    examined set that lies on a valid route — what a write operation downstream
    has to adjudicate, and the axis a budget-spending policy cannot win.
    `stopped_early` records whether the policy left budget unspent, which is the
    mechanism precision comes from: a walk that always fills its budget has its
    precision capped by the budget itself regardless of how well it selects.
    """

    examined = list(examined_edge_ids)
    if len(examined) > budget:
        raise ValueError("a policy examined more edges than the budget allows")
    on_route = {
        edge_id for route in episode.hidden["valid_routes"] for edge_id in route
    }
    coverage = route_coverage(episode, examined)
    return {
        "route_complete": bool(coverage["route_complete"]),
        "examined": len(examined),
        "on_route_examined": len(on_route & set(examined)),
        "precision": (len(on_route & set(examined)) / len(examined))
        if examined
        else 0.0,
        "stopped_early": len(examined) < budget,
    }


def pareto_frontier(rows: dict[str, dict[str, float]]) -> list[str]:
    """Names of the policies no other policy beats on both axes at once.

    A policy is dominated when another has route-completeness at least as high
    *and* precision at least as high, with at least one strictly higher. The
    surviving set is what an outcome table should be written against: a learned
    policy that beats every frontier member on both axes has done something no
    model-free policy here can do, and one that beats some member on one axis
    only has not.
    """

    names = sorted(rows)
    frontier = []
    for name in names:
        here = rows[name]
        dominated = any(
            other != name
            and rows[other]["route_complete_fraction"]
            >= here["route_complete_fraction"]
            and rows[other]["precision_mean"] >= here["precision_mean"]
            and (
                rows[other]["route_complete_fraction"] > here["route_complete_fraction"]
                or rows[other]["precision_mean"] > here["precision_mean"]
            )
            for other in names
        )
        if not dominated:
            frontier.append(name)
    return frontier
