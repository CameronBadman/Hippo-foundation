"""Track P's traversal: a two-pass walk, no budget, and a supervised stop head.

Version-additive. `model_v2` is **not edited**: Track O's reported walk came out
of it, `tests/fixtures/track_o_golden.json` pins that walk exactly, and the
repository's rule is that an earlier revision stays reproducible. Everything
shared and unchanged — `EpisodeIndex`, `Prefix`, the featurisers, the query and
traversal blocks' shapes — is imported from `model_v2` rather than copied, so
there is one implementation of each. (The approved plan proposed editing
`model_v2` under a fixture-regeneration protocol; a new module reaches the same
place while keeping Track O reproducible and needing no regeneration at all.)

Four changes, all of them consequences of what Track P measures.

**1. The walk runs in two passes.**

- *Pass 1* runs the walk under `torch.no_grad()`, batched across episodes one
  round at a time. It fixes the expansion order, the examined set, the endpoint
  registrations and the decision points.
- *Pass 2* scores every `(prefix, candidate)` pair the walk touched in **one**
  batched call, with gradients.

This is exact, not an approximation: `f` is a pure function of
`(query, prefix, candidate)` — `test_stable_score_is_invariant_to_visit_order`
asserts it — so a pair's pass-2 score is the value pass 1 ordered on, up to
padding-width float noise that cannot change a decision already made. Under
exhaustion the examined set is the whole relation-matching prefix tree, a
function of the episode alone, so the edge loss is identical in content.

*It was expected to be faster and it is not, and the prediction is worth
recording because the reasoning was wrong in an instructive way.* The autograd
graph does collapse from about ninety-six small block applications to one wide
one, which was measured at 47 % of a v2 step. But pass 1 is a **second forward**
that v2 never paid, and the two roughly cancel: measured at microbatch 128 on
the hard cell, v2 takes 1.262 s/update at 6.55 expansions per episode and v3
takes 1.289 s at 7.98 — even per update, about 1.19x cheaper per expansion, and
v3 is doing the strictly larger job of exhausting the tree. So the two-pass
split is kept for what it does to *supervision*, not for speed: the examined
set, the registrations and the decision points are all fixed before any gradient
is taken, which is what lets the stop head be trained off-policy on the same
walk and what makes the head extras identical across supervision modes.

**2. No budget.** `budget` leaves the walk. Exhaustion is bounded by
construction: states deduplicate on `(node, depth)` and the frontier admits only
relation-matching edges. `stop_reason` is `learned_stop` or `tree_exhausted`;
anything else is a harness failure, not a result.

**3. Endpoints register at examination, inside the scoring loop.** This is the
structural fix for the supervision starvation of design note 2.19, not a patch:
in `model_v2` the registration lived in the selection branch that a supplied
prefix path skips, so under `gold` and `walker` supervision the answer head's
twelve extras were zero for the first 4,000 updates. Here a candidate whose
child depth equals the query length registers its endpoint the moment it is
scored, and that code runs in every supervision mode.

**4. A supervised stop head replaces the untrained coverage head.** Same shape
and parameter count, so the equal-capacity comparison is unchanged, but it now
has its own BCE loss (`training_v3`) and its features contain **no 2, no 3 and
no budget**: `EXPECTED_TARGET_COUNT` is gone. `model_v2.coverage_features`
encoded the constant 2 three times and the budget twice, which is why a stop
learned from it would have been learning `stop_aware`'s hard-coded rule rather
than a capability.

Two facts from design note 2.23 are load-bearing here. One expansion can
register several endpoints at once, so nothing may be written as
`endpoints == 2`; the head reads raw counts. And a *registration*-based view of
completeness is what a stop decision can see — set-based coverage can credit a
walk with a target whose final edge arrived through an expansion at another
depth — so `forward` reports the endpoints registered at each decision point and
`training_v3` labels them.
"""

from __future__ import annotations

from typing import Any

from .errors import TrainingBlocked
from .model import require_torch
from .model_v2 import (
    MAX_QUERY_LENGTH,
    EpisodeIndex,
    Prefix,
    build_read_model_v2,
    parameter_count_breakdown_v2,
)

__all__ = [
    "STOP_FEATURE_DIM",
    "STOP_LEARNED",
    "STOP_TREE_EXHAUSTED",
    "DecisionPoint",
    "build_read_model_v3",
    "parameter_count_breakdown_v3",
    "stop_features",
]

# Sixteen, matching `COVERAGE_FEATURE_DIM`, so the head this replaces keeps its
# exact parameter count and the equal-capacity comparison is unchanged.
STOP_FEATURE_DIM = 16

STOP_LEARNED = "learned_stop"
STOP_TREE_EXHAUSTED = "tree_exhausted"


class DecisionPoint:
    """The walk's state before one expansion — what the stop head reads.

    `endpoints` and `complete_routes` are the *registrations* made so far, which
    is what a stop decision can see; `training_v3` turns them into a label by
    asking whether the episode's targets are among them.
    """

    __slots__ = (
        "complete_routes",
        "endpoints",
        "examined",
        "expansions",
        "features",
        "prefix_depth",
    )

    def __init__(
        self,
        *,
        features: list[float],
        endpoints: list[int],
        complete_routes: int,
        expansions: int,
        examined: int,
        prefix_depth: int,
    ) -> None:
        self.features = features
        self.endpoints = endpoints
        self.complete_routes = complete_routes
        self.expansions = expansions
        # Edges examined before this expansion — the answer head's cut at T*.
        self.examined = examined
        self.prefix_depth = prefix_depth


def stop_features(
    *,
    endpoints: list[int],
    complete_routes: int,
    frontier_depths: list[int],
    expansions: int,
    expansions_since_endpoint: int,
    last_expansion_matched: bool,
    prefix_depth: int,
    endpoints_agree: bool,
) -> list[float]:
    """What the stop head reads. Raw counts and structure; no target constant.

    Deliberately absent: the number 2 in any form, the number 3, and any
    budget. `model_v2.coverage_features` carried
    `_one_hot(min(endpoints, 2), 3)`, `endpoints >= EXPECTED_TARGET_COUNT` and
    two budget ratios, so a head reading it could only rediscover the
    hard-coded stop. The single scale used here is `MAX_QUERY_LENGTH`, a
    property of the query's shape rather than of the answer.
    """

    scale = float(MAX_QUERY_LENGTH)
    histogram = [0.0] * MAX_QUERY_LENGTH
    for depth in frontier_depths:
        if 0 <= depth < MAX_QUERY_LENGTH:
            histogram[depth] += 1.0
    total = float(len(frontier_depths)) or 1.0
    features = [value / total for value in histogram]
    features.append(min(len(endpoints), MAX_QUERY_LENGTH) / scale)
    features.append(min(complete_routes, MAX_QUERY_LENGTH) / scale)
    features.append(min(len(frontier_depths), 32) / 32.0)
    features.append(min(expansions, 32) / 32.0)
    features.append(min(expansions_since_endpoint, 32) / 32.0)
    features.append(1.0 if last_expansion_matched else 0.0)
    features.append(prefix_depth / scale)
    features.append(1.0 if endpoints_agree else 0.0)
    if len(features) != STOP_FEATURE_DIM:
        raise TrainingBlocked("stop feature width drifted from its constant")
    return features


def parameter_count_breakdown_v3(config: dict[str, Any]) -> dict[str, int]:
    """v2's breakdown with the coverage head renamed; the count is unchanged."""

    breakdown = parameter_count_breakdown_v2(config)
    breakdown["stop_head"] = breakdown.pop("coverage_head")
    return breakdown


def build_read_model_v3(config: dict[str, Any]) -> Any:
    """Track P's model: v2's encoder stack, a two-pass walk, a supervised stop."""

    torch, nn, _functional = require_torch()
    base = build_read_model_v2(config)

    class TrackPTraversalModel(type(base)):  # type: ignore[misc]
        """`build_read_model_v2`'s module with the walk and the stop replaced.

        Subclassing the closure class keeps every parameter tensor, encoder and
        block definition shared with v2 — the two models are capacity-identical
        by construction rather than by a matching arithmetic comment.
        """

        def stop_logits(self, rows: list[list[float]]) -> Any:
            """One batched call over every decision point in the batch."""

            if not rows:
                return torch.zeros(0, device=self.device)
            features = torch.tensor(rows, dtype=torch.float32, device=self.device)
            return self.coverage_head(features).squeeze(-1)

        def _answer_batch(
            self, answer_inputs: list[tuple[Any, ...]], cuts: list[int]
        ) -> Any:
            return torch.stack(
                [
                    self.answer(
                        tokens[: cuts[slot]],
                        scores[: cuts[slot]],
                        index,
                        endpoints,
                        routes,
                    )
                    for slot, (tokens, scores, index, endpoints, routes) in enumerate(
                        answer_inputs
                    )
                ]
            )

        def answer_at_cuts(self, out: dict[str, Any], cuts: list[int]) -> Any:
            """Re-read the answer head at a different cut, with no second walk.

            Training reads the answer at T*, the first route-complete decision
            point, which is derived from hidden truth and so cannot be computed
            inside `forward`. The walk and its scored tokens are unchanged; only
            how many of them the answer summarises differs.
            """

            return self._answer_batch(out["answer_inputs"], cuts)

        def _walk_batch(
            self,
            indexes: list[EpisodeIndex],
            *,
            supplied: list[list[tuple[Prefix, list[int]]]] | None,
            stop_rule: str,
            stop_decision: str,
            query_cache: dict[int, tuple[Any, Any]],
            array_cache: dict[int, Any],
        ) -> list[dict[str, Any]]:
            """Pass 1: every episode's walk, round by round, under `no_grad`.

            **Batched across episodes, one round at a time** — v2's structure,
            and the reason it matters is measured: a first version of this
            module walked each episode alone, calling the scorer once per
            expansion with a batch of one. That is about a thousand batch-size-1
            calls per update instead of a dozen wide ones, and it ran the whole
            step six times slower than v2 rather than faster. The two-pass split
            only pays if pass 1 keeps the round batching and pass 2 adds one
            wide call on top.

            Scores here are used for ordering only and are discarded; pass 2
            recomputes them with gradients.
            """

            count = len(indexes)
            walks: list[dict[str, Any]] = [
                {
                    "items": [],
                    "examined": [],
                    "owner": [],
                    "endpoints": [],
                    "routes": [],
                    "decisions": [],
                    "expansions": 0,
                    "stop_reason": STOP_TREE_EXHAUSTED,
                }
                for _ in range(count)
            ]
            scored: list[set[int]] = [set() for _ in range(count)]
            states: list[set[tuple[int, int]]] = [set() for _ in range(count)]
            expanded: list[set[int]] = [set() for _ in range(count)]
            frontier: list[dict[tuple[int, int], tuple[float, Prefix]]] = [
                {} for _ in range(count)
            ]
            last_endpoint_at = [0] * count
            last_matched = [False] * count
            pending: list[list[tuple[Prefix, list[int] | None]]] = (
                [
                    [(prefix, list(group)) for prefix, group in values]
                    for values in supplied
                ]
                if supplied is not None
                else [[(Prefix((), index.start, 0), None)] for index in indexes]
            )
            active = list(range(count))

            while active:
                # Each active slot offers its next expansion, and every slot's
                # stop decision for this round is taken in one batched call.
                offers: list[tuple[int, Prefix, list[int] | None]] = []
                for slot in list(active):
                    while pending[slot]:
                        prefix, group = pending[slot].pop(0)
                        if (prefix.node, prefix.depth) in states[slot]:
                            continue
                        offers.append((slot, prefix, group))
                        break
                    else:
                        active.remove(slot)
                if not offers:
                    break

                decisions = []
                for slot, prefix, _group in offers:
                    index = indexes[slot]
                    endpoints = walks[slot]["endpoints"]
                    agree = (
                        len(endpoints) >= 2
                        and len({index.mask(node) for node in endpoints}) == 1
                    )
                    decisions.append(
                        DecisionPoint(
                            features=stop_features(
                                endpoints=list(endpoints),
                                complete_routes=len(walks[slot]["routes"]),
                                frontier_depths=[d for _e, d in frontier[slot]],
                                expansions=walks[slot]["expansions"],
                                expansions_since_endpoint=(
                                    walks[slot]["expansions"] - last_endpoint_at[slot]
                                ),
                                last_expansion_matched=last_matched[slot],
                                prefix_depth=prefix.depth,
                                endpoints_agree=agree,
                            ),
                            endpoints=list(endpoints),
                            complete_routes=len(walks[slot]["routes"]),
                            expansions=walks[slot]["expansions"],
                            examined=len(walks[slot]["examined"]),
                            prefix_depth=prefix.depth,
                        )
                    )
                for (slot, _p, _g), decision in zip(offers, decisions, strict=True):
                    walks[slot]["decisions"].append(decision)

                if stop_rule == "learned" and supplied is None:
                    logits = self.stop_logits([d.features for d in decisions])
                    keep = []
                    for row, (slot, prefix, group) in enumerate(offers):
                        stop_logit = float(logits[row])
                        if stop_decision == "probability":
                            # The BCE's own boundary: P(stop) > 0.5.
                            halt = stop_logit > 0.0
                        else:
                            # Constant-free: "done" is more probable than "the
                            # best edge left is on-route". Compares two learned
                            # logits and carries no threshold of its own.
                            #
                            # The default is +inf, not -inf. An empty frontier
                            # means there is no "best remaining edge" to be more
                            # confident than, which is the state before the very
                            # first expansion — with -inf the rule fired
                            # immediately on every episode and the walk returned
                            # zero expansions, which reads as a perfectly cheap
                            # policy that never finds anything. No frontier is an
                            # absence of evidence for stopping, so the rule
                            # abstains and the walk exhausts naturally instead.
                            best_edge = max(
                                (score for score, _child in frontier[slot].values()),
                                default=float("inf"),
                            )
                            halt = stop_logit > best_edge
                        if halt:
                            walks[slot]["stop_reason"] = STOP_LEARNED
                            active.remove(slot)
                        else:
                            keep.append((slot, prefix, group))
                    offers = keep
                    if not offers:
                        continue

                batch = []
                for slot, prefix, group in offers:
                    states[slot].add((prefix.node, prefix.depth))
                    expanded[slot].add(prefix.node)
                    if group is None:
                        group = [
                            edge["edge_id"] for edge in indexes[slot].group(prefix.node)
                        ]
                    walks[slot]["items"].append((prefix, list(group)))
                    walks[slot]["expansions"] += 1
                    batch.append((slot, prefix, list(group)))

                scores, _tokens, _mask = self.score_expansions(
                    [
                        (indexes[slot], prefix, group, frozenset(expanded[slot]))
                        for slot, prefix, group in batch
                    ],
                    query_cache,
                    array_cache,
                )

                for row, (slot, prefix, group) in enumerate(batch):
                    index = indexes[slot]
                    walk = walks[slot]
                    last_matched[slot] = False
                    wanted = (
                        index.relations[prefix.depth]
                        if prefix.depth < index.length
                        else None
                    )
                    for column, edge_id in enumerate(group):
                        if edge_id not in scored[slot]:
                            scored[slot].add(edge_id)
                            walk["examined"].append(edge_id)
                            walk["owner"].append(prefix.edges)
                        edge = index.by_id[edge_id]
                        if wanted is None or edge["relation"] != wanted:
                            continue
                        last_matched[slot] = True
                        child = Prefix(
                            prefix.edges + (edge_id,), edge["target"], prefix.depth + 1
                        )
                        # Registration at examination: the endpoint is known the
                        # moment its final edge is scored, in every supervision
                        # mode. The structural fix for design note 2.19.
                        if child.depth == index.length:
                            if child.node not in walk["endpoints"]:
                                walk["endpoints"].append(child.node)
                                walk["routes"].append(child.edges)
                                last_endpoint_at[slot] = walk["expansions"]
                            continue
                        if (child.node, child.depth) in states[slot]:
                            continue
                        key = (edge_id, child.depth)
                        if key not in frontier[slot]:
                            frontier[slot][key] = (float(scores[row, column]), child)

                if supplied is not None:
                    active = [slot for slot in active if pending[slot]]
                    continue
                for slot, _prefix, _group in batch:
                    while frontier[slot]:
                        key = max(
                            frontier[slot],
                            key=lambda k: (frontier[slot][k][0], -k[0]),
                        )
                        _score, child = frontier[slot].pop(key)
                        if (child.node, child.depth) in states[slot]:
                            continue
                        pending[slot].append((child, None))
                        break

            return walks

        def forward(
            self,
            visible_batch: list[dict[str, Any]],
            *,
            supplied: list[list[tuple[Prefix, list[int]]]] | None = None,
            stop_rule: str = "exhaust",
            stop_decision: str = "probability",
            answer_at: list[int] | None = None,
        ) -> dict[str, Any]:
            """Two passes: walk without gradients, then score everything with them.

            `stop_rule` is `exhaust` (training, and the reference walk) or
            `learned` (evaluation). `stop_decision` selects which of the two
            reported rules a learned walk halts on. `answer_at` gives, per
            episode, how many examined edges the answer head may read; when the
            cut is not known until the walk has run — training reads at T*,
            which is derived from hidden truth the model must not see — leave it
            unset and call `answer_at_cuts` on the result instead.
            """

            if stop_rule not in {"exhaust", "learned"}:
                raise TrainingBlocked(f"unknown stop rule: {stop_rule}")
            if stop_decision not in {"probability", "logit_margin"}:
                raise TrainingBlocked(f"unknown stop decision: {stop_decision}")
            indexes = [EpisodeIndex(visible) for visible in visible_batch]
            query_cache: dict[int, tuple[Any, Any]] = {}
            array_cache: dict[int, Any] = {}

            with torch.no_grad():
                walks = self._walk_batch(
                    indexes,
                    supplied=supplied,
                    stop_rule=stop_rule,
                    stop_decision=stop_decision,
                    query_cache=query_cache,
                    array_cache=array_cache,
                )

            # Pass 2: every (prefix, group) the walk touched, in one call.
            flat: list[tuple[EpisodeIndex, Prefix, list[int], frozenset[int]]] = []
            position: list[list[int]] = []
            for index, walk in zip(indexes, walks, strict=True):
                seen = {prefix.node for prefix, _group in walk["items"]}
                rows = []
                for prefix, group in walk["items"]:
                    rows.append(len(flat))
                    flat.append((index, prefix, group, frozenset(seen)))
                position.append(rows)
            if flat:
                scores, tokens, _mask = self.score_expansions(
                    flat, query_cache, array_cache
                )
            else:
                scores = tokens = None

            count = len(indexes)
            kept_scores: list[list[Any]] = [[] for _ in range(count)]
            kept_tokens: list[list[Any]] = [[] for _ in range(count)]
            for slot, walk in enumerate(walks):
                taken: set[int] = set()
                for row, (_prefix, group) in zip(
                    position[slot], walk["items"], strict=True
                ):
                    for column, edge_id in enumerate(group):
                        if edge_id in taken:
                            continue
                        taken.add(edge_id)
                        kept_scores[slot].append(scores[row, column])
                        kept_tokens[slot].append(tokens[row, column])
                if len(kept_scores[slot]) != len(walk["examined"]):
                    raise TrainingBlocked(
                        "pass 2 recovered a different examined set from pass 1"
                    )

            stop_rows = [
                decision.features for walk in walks for decision in walk["decisions"]
            ]
            stop_all = self.stop_logits(stop_rows)
            stop_logits: list[Any] = []
            cursor = 0
            for walk in walks:
                size = len(walk["decisions"])
                stop_logits.append(stop_all[cursor : cursor + size])
                cursor += size

            # Everything the answer head needs, kept so a caller who only learns
            # the cut *after* the walk (training reads at T*, derived from hidden
            # truth) can re-read the answer without a second forward.
            answer_inputs = [
                (
                    kept_tokens[slot],
                    kept_scores[slot],
                    indexes[slot],
                    walks[slot]["endpoints"],
                    walks[slot]["routes"],
                )
                for slot in range(count)
            ]
            cuts = answer_at or [len(walk["examined"]) for walk in walks]
            logits = self._answer_batch(answer_inputs, cuts)

            width = max((len(values) for values in kept_scores), default=1) or 1
            zero = torch.zeros((), device=self.device)
            score_rows, masks = [], []
            for slot in range(count):
                pad = width - len(kept_scores[slot])
                score_rows.append(
                    torch.stack(kept_scores[slot] + [zero] * pad)
                    if kept_scores[slot] or pad
                    else zero.reshape(1)
                )
                masks.append([True] * len(kept_scores[slot]) + [False] * pad)
            return {
                "logits": logits,
                "answer_inputs": answer_inputs,
                "scores": torch.stack(score_rows),
                "score_mask": torch.tensor(masks, device=self.device),
                "stop_logits": stop_logits,
                "decisions": [walk["decisions"] for walk in walks],
                "edge_ids": [walk["examined"] for walk in walks],
                "prefixes": [walk["owner"] for walk in walks],
                "routes": [[list(route) for route in walk["routes"]] for walk in walks],
                "endpoints": [walk["endpoints"] for walk in walks],
                "stop_reason": [walk["stop_reason"] for walk in walks],
                "examined_count": [len(walk["examined"]) for walk in walks],
                "expansion_count": [walk["expansions"] for walk in walks],
            }

    model = TrackPTraversalModel()
    model.load_state_dict(base.state_dict())
    return model
