"""Path-scoped traversal model for Track O. Version-additive; v1 is untouched.

This implements `docs/TRACK_O_DESIGN.md` M1-M7, which exist to fix four measured
defects of the v1 traversal model (design notes sections 2.9-2.16):

- **Adjacency was inexpressible.** v1 encoded an edge as two 4-bit assertion
  masks, a relation embedding, a broadcast query vector and a similarity scalar,
  with no node identity, so the true continuation of a route step was uniquely
  identifiable on 28.33 % of steps. Here adjacency is carried by the prefix tree
  itself — a candidate is scored in the context of *its own* ancestry — and by
  explicit `target(x) == source(c)` bits in the pair features. Neither costs a
  parameter, and neither needs an episode-local node embedding.
- **The query had no per-hop resolution.** v1 broadcast `state[-1]`. Here the
  query is a token sequence indexed by position and candidates cross-attend to
  it, so matching hop k against relation k is a lookup.
- **State was destructive and visit-ordered.** v1 mutated a GRU cell in *jump*
  order under best-first selection, which made frontier scores incommensurable.
  Here the stable term `f` is a pure function of `(query, prefix, edge)`, cached
  on the prefix, and never depends on exploration history.
- **The budget was always spent.** v1 examined exactly `budget` edges in every
  episode, capping examined-set precision at about 0.04. Here the walk stops
  when the frontier empties or both endpoints are reached.

**Zero-shot by construction.** Relation ids, content values and node ids carry no
meaning across episodes on the Track O generator, so nothing here is indexed by
one. Relations enter only through equality tests against the query, content only
through attribute-agreement bits, nodes only through identity tests. The one
learned symbol table is over assertion masks, which *are* globally meaningful —
they are the 16 answer classes.

**No free lookahead.** `EpisodeIndex` holds the whole visible payload, so a
featuriser could trivially read an unexpanded target's out-edges and get one-hop
lookahead for nothing, which would silently invalidate examined-set precision —
structurally the same failure as v1's similarity leak. `EpisodeIndex.out_edges`
therefore refuses any node that has not been expanded, and featurisers receive
only that guarded accessor.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, NamedTuple

from .errors import TrainingBlocked
from .model import _structural_order, require_torch

MAX_QUERY_LENGTH = 8
MAX_ATTRIBUTES = 5
CANDIDATE_FEATURE_DIM = 72
CONTEXT_FEATURE_DIM = 48
PAIR_FEATURE_DIM = 32
QUERY_CROSS_FEATURE_DIM = 16
QUERY_PAIR_FEATURE_DIM = 18
COVERAGE_FEATURE_DIM = 16
# Where block E (content) sits inside the candidate vector: blocks A(19),
# B(18), C(4) and D(7) precede it. Exported so the ablation test asserts on
# the real offset rather than a copy of it.
CONTENT_FEATURE_SLICE = (48, 64)
SIMILARITY_SCALE = 1_000_000.0
EXPECTED_TARGET_COUNT = 2

STOP_TREE_EXHAUSTED = "tree_exhausted"
STOP_TARGETS_REACHED = "targets_reached"
STOP_BUDGET_CAP = "budget_cap"


class Prefix(NamedTuple):
    """A path from the start node, identified by its edges and labelled by state.

    `edges` is the score-cache key: `f` is a pure function of it. `(node, depth)`
    is the expansion-dedup label, identical to the one
    `coverage.relation_walker_examined_set` queues on, so a node reached at two
    different depths is two states.
    """

    edges: tuple[int, ...]
    node: int
    depth: int


@dataclass
class WalkState:
    """Coverage facts the event-triggered term `g` reads (design notes 2.15)."""

    examined: int = 0
    expansions: int = 0
    endpoints: frozenset[int] = frozenset()
    complete_routes: int = 0
    exhausted: int = 0
    epoch: int = 0


class EpisodeIndex:
    """Adjacency and content for one visible payload, with expansion guarded."""

    def __init__(self, visible: dict[str, Any]) -> None:
        self.visible = visible
        self.relations: list[int] = list(visible["query_relations"])
        self.length = len(self.relations)
        self.start = visible["start_node"]
        self.attribute_count = visible["content_attribute_count"]
        self.by_id = {edge["edge_id"]: edge for edge in visible["edges"]}
        groups: dict[int, list[dict[str, int]]] = defaultdict(list)
        for edge in visible["edges"]:
            groups[edge["source"]].append(edge)
        for values in groups.values():
            values.sort(
                key=lambda edge: _structural_order(visible["router_seed"], edge)
            )
        self._groups = groups
        self._content = {
            node["node"]: tuple(node["content"]) for node in visible["nodes"]
        }
        self._masks = {
            node["node"]: sum(1 << index for index in node["assertions"])
            for node in visible["nodes"]
        }
        self._similarity_stats: dict[int, tuple[float, float, dict[int, int]]] = {}

    def group(self, node: int) -> list[dict[str, int]]:
        """The full out-edge group. Reachable only from the walk's expansion."""

        return self._groups[node]

    def out_edges(self, node: int, *, expanded: frozenset[int]) -> list[dict[str, int]]:
        """Guarded accessor: refuses a node the walk has not expanded.

        Without this an unexpanded target's out-edges are one attribute access
        away and every featuriser gets free one-hop lookahead.
        """

        if node not in expanded:
            raise TrainingBlocked(
                "model_v2 may not read the out-edges of an unexpanded node"
            )
        return self._groups[node]

    def content(self, node: int) -> tuple[int, ...]:
        return self._content[node]

    def mask(self, node: int) -> int:
        return self._masks[node]

    def similarity_stats(self, node: int) -> tuple[float, float, dict[int, int]]:
        """Mean, max and per-edge rank of similarity within a node's group."""

        cached = self._similarity_stats.get(node)
        if cached is None:
            group = self._groups[node]
            values = [edge["query_similarity_ppm"] for edge in group]
            order = sorted(
                group, key=lambda e: (-e["query_similarity_ppm"], e["edge_id"])
            )
            ranks = {edge["edge_id"]: rank for rank, edge in enumerate(order)}
            cached = (sum(values) / len(values), float(max(values)), ranks)
            self._similarity_stats[node] = cached
        return cached


def _one_hot(value: int, size: int) -> list[float]:
    vector = [0.0] * size
    if 0 <= value < size:
        vector[value] = 1.0
    return vector


def candidate_features(
    index: EpisodeIndex,
    prefix: Prefix,
    edge_id: int,
    *,
    content_features: bool = True,
) -> list[float]:
    """The zero-shot feature vector for one candidate edge under one prefix.

    Every block is a function of the query, the prefix, and the *source's* own
    out-edge group. Nothing reads the target's out-edges.
    """

    edge = index.by_id[edge_id]
    depth, relations, length = prefix.depth, index.relations, index.length
    source, target = edge["source"], edge["target"]

    # A — relation matching, symbolic only (19)
    features = [
        1.0 if k < length and edge["relation"] == relations[k] else 0.0
        for k in range(MAX_QUERY_LENGTH)
    ]
    features += [1.0 if k < length else 0.0 for k in range(MAX_QUERY_LENGTH)]
    features.append(
        1.0 if depth < length and edge["relation"] == relations[depth] else 0.0
    )
    parent = index.by_id[prefix.edges[-1]] if prefix.edges else None
    features.append(
        1.0 if parent is not None and parent["relation"] == edge["relation"] else 0.0
    )
    features.append(1.0 if depth == 0 else 0.0)

    # B — depth (18)
    features += _one_hot(depth, MAX_QUERY_LENGTH)
    features += _one_hot(length - 1 - depth, MAX_QUERY_LENGTH)
    features.append(1.0 if depth == length - 1 else 0.0)
    features.append(depth / max(length, 1))

    # C — sibling ambiguity at the source (4)
    group = index.group(source)
    matching = sum(
        1 for other in group if depth < length and other["relation"] == relations[depth]
    )
    features.append(len(group) / 8.0)
    features.append(matching / max(len(group), 1))
    features.append(1.0 if matching == 1 else 0.0)
    features.append(len({other["relation"] for other in group}) / max(len(group), 1))

    # D — similarity (7)
    mean, top, ranks = index.similarity_stats(source)
    similarity = float(edge["query_similarity_ppm"])
    features.append(similarity / SIMILARITY_SCALE)
    features.append(1.0 if similarity >= top else 0.0)
    features.append(ranks[edge_id] / max(len(group) - 1, 1))
    features.append((similarity - mean) / SIMILARITY_SCALE)
    features.append((similarity - top) / SIMILARITY_SCALE)
    if prefix.edges:
        along = [
            float(index.by_id[value]["query_similarity_ppm"]) for value in prefix.edges
        ]
        features.append(sum(along) / len(along) / SIMILARITY_SCALE)
        features.append(
            1.0
            if all(
                index.by_id[value]["query_similarity_ppm"]
                >= index.similarity_stats(index.by_id[value]["source"])[1]
                for value in prefix.edges
            )
            else 0.0
        )
    else:
        features += [0.0, 1.0]

    # E — content, relational and ablatable (16)
    if len(features) != CONTENT_FEATURE_SLICE[0]:
        raise TrainingBlocked("candidate feature blocks A-D drifted in width")
    if content_features:
        source_content = index.content(source)
        target_content = index.content(target)
        start_content = index.content(index.start)
        agree = [
            1.0
            if i < index.attribute_count and source_content[i] == target_content[i]
            else 0.0
            for i in range(MAX_ATTRIBUTES)
        ]
        features += agree
        features += [
            1.0
            if i < index.attribute_count and target_content[i] == start_content[i]
            else 0.0
            for i in range(MAX_ATTRIBUTES)
        ]
        features.append(sum(agree) / max(index.attribute_count, 1))
        features += [
            1.0 if i < index.attribute_count else 0.0 for i in range(MAX_ATTRIBUTES)
        ]
    else:
        features += [0.0] * (CONTENT_FEATURE_SLICE[1] - CONTENT_FEATURE_SLICE[0])

    # F — prefix structure (2)
    nodes_on_prefix = {index.by_id[value]["source"] for value in prefix.edges} | {
        index.by_id[value]["target"] for value in prefix.edges
    }
    features.append(1.0 if target in nodes_on_prefix else 0.0)
    features.append(len(nodes_on_prefix) / max(length, 1))

    features += [0.0] * (CANDIDATE_FEATURE_DIM - len(features))
    if len(features) != CANDIDATE_FEATURE_DIM:
        raise TrainingBlocked("candidate feature width drifted from its constant")
    return features


def context_features(
    index: EpisodeIndex, prefix: Prefix, edge_id: int, context_depth: int
) -> list[float]:
    """Features of one already-examined edge that forms a candidate's context."""

    edge = index.by_id[edge_id]
    relations, length = index.relations, index.length
    features = [
        1.0 if k < length and edge["relation"] == relations[k] else 0.0
        for k in range(MAX_QUERY_LENGTH)
    ]
    features += _one_hot(context_depth, MAX_QUERY_LENGTH)
    features.append(float(edge["query_similarity_ppm"]) / SIMILARITY_SCALE)
    features.append(1.0 if edge_id in prefix.edges else 0.0)
    features.append(1.0 if edge["source"] == prefix.node else 0.0)
    features.append(1.0 if edge["target"] == prefix.node else 0.0)
    mean, top, ranks = index.similarity_stats(edge["source"])
    features.append(1.0 if edge["query_similarity_ppm"] >= top else 0.0)
    features.append(context_depth / max(length, 1))
    features += [0.0] * (CONTEXT_FEATURE_DIM - len(features))
    if len(features) != CONTEXT_FEATURE_DIM:
        raise TrainingBlocked("context feature width drifted from its constant")
    return features


def pair_features(
    index: EpisodeIndex, candidate_edge_id: int, context_edge_id: int
) -> list[float]:
    """Candidate-by-context bias features. Carries the adjacency identities."""

    candidate = index.by_id[candidate_edge_id]
    context = index.by_id[context_edge_id]
    features = [
        1.0 if candidate["relation"] == context["relation"] else 0.0,
        1.0 if context["target"] == candidate["source"] else 0.0,
        1.0 if context["source"] == candidate["source"] else 0.0,
        1.0 if context["target"] == candidate["target"] else 0.0,
        1.0 if context["source"] == candidate["target"] else 0.0,
        1.0 if context["source"] == context["target"] else 0.0,
    ]
    source_a, target_a = (
        index.content(candidate["source"]),
        index.content(candidate["target"]),
    )
    source_b, target_b = (
        index.content(context["source"]),
        index.content(context["target"]),
    )
    for left, right in (
        (source_a, source_b),
        (target_a, target_b),
        (source_a, target_b),
    ):
        features += [
            1.0 if i < index.attribute_count and left[i] == right[i] else 0.0
            for i in range(MAX_ATTRIBUTES)
        ]
    features.append(
        (
            float(context["query_similarity_ppm"])
            - float(candidate["query_similarity_ppm"])
        )
        / SIMILARITY_SCALE
    )
    features += [0.0] * (PAIR_FEATURE_DIM - len(features))
    if len(features) != PAIR_FEATURE_DIM:
        raise TrainingBlocked("pair feature width drifted from its constant")
    return features


def query_cross_features(
    index: EpisodeIndex, prefix: Prefix, edge_id: int, position: int
) -> list[float]:
    """Candidate-by-query-position bias. This is M1: matching is a lookup."""

    edge = index.by_id[edge_id]
    depth, length = prefix.depth, index.length
    features = [
        1.0
        if position < length and edge["relation"] == index.relations[position]
        else 0.0,
        1.0 if position == depth else 0.0,
        1.0 if position == depth + 1 else 0.0,
        1.0 if position < depth else 0.0,
        1.0 if position >= length else 0.0,
    ]
    offset = position - depth
    features += _one_hot(offset + 4, 9) if -4 <= offset <= 4 else [0.0] * 9
    features += [0.0] * (QUERY_CROSS_FEATURE_DIM - len(features))
    if len(features) != QUERY_CROSS_FEATURE_DIM:
        raise TrainingBlocked("query cross feature width drifted from its constant")
    return features


def query_pair_features(index: EpisodeIndex, position: int, other: int) -> list[float]:
    """Query-position by query-position bias: the relation-repeat pattern."""

    length = index.length
    same = (
        position < length
        and other < length
        and index.relations[position] == index.relations[other]
    )
    features = [1.0 if same else 0.0]
    offset = other - position
    features += _one_hot(offset + 7, 15) if -7 <= offset <= 7 else [0.0] * 15
    features.append(1.0 if position == other else 0.0)
    features.append(1.0 if other >= length else 0.0)
    if len(features) != QUERY_PAIR_FEATURE_DIM:
        raise TrainingBlocked("query pair feature width drifted from its constant")
    return features


def coverage_features(state: WalkState, prefix: Prefix, budget: int) -> list[float]:
    """What the event-triggered term `g` reads. Never identity, only counts."""

    features = _one_hot(min(state.complete_routes, 3), 4)
    features += _one_hot(min(len(state.endpoints), 2), 3)
    features.append(state.examined / max(budget, 1))
    features.append(min(state.expansions, 16) / 16.0)
    features.append(min(state.exhausted, 8) / 8.0)
    features.append(prefix.depth / max(1, MAX_QUERY_LENGTH))
    features.append(1.0 if len(state.endpoints) >= EXPECTED_TARGET_COUNT else 0.0)
    features.append(1.0 if state.complete_routes > 0 else 0.0)
    features.append(
        1.0 if budget - state.examined < (MAX_QUERY_LENGTH - prefix.depth) else 0.0
    )
    features += [0.0] * (COVERAGE_FEATURE_DIM - len(features))
    if len(features) != COVERAGE_FEATURE_DIM:
        raise TrainingBlocked("coverage feature width drifted from its constant")
    return features


def walker_expansions(
    visible: dict[str, Any], budget: int
) -> list[tuple[Prefix, list[int]]]:
    """The (prefix, out-edge group) sequence the relation walker would produce.

    Reproduces `coverage.relation_walker_examined_set` exactly, but keeps the
    prefix that reached each expanded state so the sequence can be replayed as
    supplied-prefix supervision.
    """

    index = EpisodeIndex(visible)
    relations = index.relations
    # `coverage.relation_walker_examined_set` orders a node's out-edges by
    # `edge_id`; the model orders its own groups by `_structural_order`. This
    # function replays the *walker*, so it uses the walker's order — otherwise
    # the two disagree wherever a budget truncates a group.
    by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
    for edge in visible["edges"]:
        by_source[edge["source"]].append(edge)
    for values in by_source.values():
        values.sort(key=lambda edge: edge["edge_id"])
    examined: list[int] = []
    scored: set[int] = set()
    expanded: set[int] = set()
    out: list[tuple[Prefix, list[int]]] = []
    queue: list[Prefix] = [Prefix((), index.start, 0)]
    queued: set[tuple[int, int]] = {(index.start, 0)}
    while queue and len(examined) < budget:
        prefix = queue.pop(0)
        if prefix.node not in expanded:
            expanded.add(prefix.node)
            fresh = [
                edge["edge_id"]
                for edge in by_source[prefix.node]
                if edge["edge_id"] not in scored
            ][: budget - len(examined)]
            if fresh:
                out.append((prefix, fresh))
                examined.extend(fresh)
                scored.update(fresh)
        if prefix.depth + 1 >= len(relations):
            continue
        for edge in by_source[prefix.node]:
            if edge["relation"] != relations[prefix.depth]:
                continue
            state = (edge["target"], prefix.depth + 1)
            if state not in queued:
                queued.add(state)
                queue.append(
                    Prefix(
                        prefix.edges + (edge["edge_id"],),
                        edge["target"],
                        prefix.depth + 1,
                    )
                )
    return out


def route_prefixes(
    visible: dict[str, Any], valid_routes: list[list[int]]
) -> list[tuple[Prefix, list[int]]]:
    """Every true-prefix expansion of the planted routes (the M6 gold source).

    Because scoring is path-scoped, each route edge can be supervised under the
    prefix that actually reaches it, regardless of where the model's own walk
    went. This is what dissolves v1's exposure-bias loop.
    """

    index = EpisodeIndex(visible)
    seen: set[tuple[int, ...]] = set()
    out: list[tuple[Prefix, list[int]]] = []
    for route in valid_routes:
        node, edges = index.start, ()
        for depth, edge_id in enumerate(route):
            prefix = Prefix(edges, node, depth)
            if prefix.edges not in seen:
                seen.add(prefix.edges)
                out.append((prefix, [edge["edge_id"] for edge in index.group(node)]))
            edges = edges + (edge_id,)
            node = index.by_id[edge_id]["target"]
    return out


def expected_trainable_parameter_count_v2(config: dict[str, Any]) -> int:
    """Closed-form parameter count, computed without importing PyTorch."""

    model = config["model"]
    d = int(model["hidden_dimension"])
    heads = int(model["self_attention_heads"])
    multiplier = int(model["feedforward_multiplier"])
    score_hidden = int(model["score_hidden_dimension"])
    coverage_hidden = int(model["coverage_hidden_dimension"])
    query_blocks = int(model["query_blocks"])
    traversal_blocks = int(model["traversal_blocks"])
    classes = int(model["output_classes"])

    attention = 4 * d * d + 4 * d
    norm = 2 * d
    feedforward = 2 * multiplier * d * d + (multiplier + 1) * d
    query_block = attention + norm + feedforward + norm + QUERY_PAIR_FEATURE_DIM * heads
    traversal_block = (
        attention
        + norm
        + PAIR_FEATURE_DIM * heads
        + PAIR_FEATURE_DIM * d
        + attention
        + norm
        + QUERY_CROSS_FEATURE_DIM * heads
        + feedforward
        + norm
    )
    return (
        MAX_QUERY_LENGTH * d
        + query_blocks * query_block
        + traversal_blocks * traversal_block
        + CANDIDATE_FEATURE_DIM * d
        + d
        + norm
        + CONTEXT_FEATURE_DIM * d
        + d
        + norm
        + (d + 2) * score_hidden
        + 1
        + COVERAGE_FEATURE_DIM * coverage_hidden
        + coverage_hidden
        + coverage_hidden
        + 1
        + norm
        + (d + 12) * d
        + d
        + d * classes
        + classes
    )


def parameter_count_breakdown_v2(config: dict[str, Any]) -> dict[str, int]:
    """Per-term counts, so a capacity mismatch names the term that drifted."""

    model = config["model"]
    d = int(model["hidden_dimension"])
    heads = int(model["self_attention_heads"])
    multiplier = int(model["feedforward_multiplier"])
    attention = 4 * d * d + 4 * d
    norm = 2 * d
    feedforward = 2 * multiplier * d * d + (multiplier + 1) * d
    return {
        "query_position": MAX_QUERY_LENGTH * d,
        "query_blocks": int(model["query_blocks"])
        * (attention + norm + feedforward + norm + QUERY_PAIR_FEATURE_DIM * heads),
        "traversal_blocks": int(model["traversal_blocks"])
        * (
            attention
            + norm
            + PAIR_FEATURE_DIM * heads
            + PAIR_FEATURE_DIM * d
            + attention
            + norm
            + QUERY_CROSS_FEATURE_DIM * heads
            + feedforward
            + norm
        ),
        "candidate_encoder": CANDIDATE_FEATURE_DIM * d + d + norm,
        "context_encoder": CONTEXT_FEATURE_DIM * d + d + norm,
        "score_head": (d + 2) * int(model["score_hidden_dimension"]) + 1,
        "coverage_head": COVERAGE_FEATURE_DIM * int(model["coverage_hidden_dimension"])
        + 2 * int(model["coverage_hidden_dimension"])
        + 1,
        "answer_head": norm
        + (d + 12) * d
        + d
        + d * int(model["output_classes"])
        + int(model["output_classes"]),
    }


def build_read_model_v2(config: dict[str, Any]) -> Any:
    """Factory-closure like v1's `build_read_model`, with torch imported lazily."""

    torch, nn, functional = require_torch()
    model_config = config["model"]
    hidden = int(model_config["hidden_dimension"])
    heads = int(model_config["self_attention_heads"])
    multiplier = int(model_config["feedforward_multiplier"])
    score_hidden = int(model_config["score_hidden_dimension"])
    coverage_hidden = int(model_config["coverage_hidden_dimension"])
    query_blocks = int(model_config["query_blocks"])
    traversal_blocks = int(model_config["traversal_blocks"])
    classes = int(model_config["output_classes"])
    dropout = float(model_config["dropout"])
    use_content = bool(model_config.get("content_features", True))

    class QueryBlock(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.attention = nn.MultiheadAttention(
                hidden, heads, dropout=dropout, batch_first=True
            )
            self.norm_attention = nn.LayerNorm(hidden)
            self.feedforward = nn.Sequential(
                nn.Linear(hidden, multiplier * hidden),
                nn.GELU(),
                nn.Linear(multiplier * hidden, hidden),
            )
            self.norm_feedforward = nn.LayerNorm(hidden)
            self.bias = nn.Linear(QUERY_PAIR_FEATURE_DIM, heads, bias=False)

        def forward(self, tokens, pair, key_padding_mask):
            normed = self.norm_attention(tokens)
            bias = self.bias(pair).permute(0, 3, 1, 2)
            key_padding_mask = key_padding_mask.to(bias.dtype)
            batch, _positions, _positions2 = pair.shape[0], pair.shape[1], pair.shape[2]
            bias = bias.reshape(batch * heads, pair.shape[1], pair.shape[2])
            attended, _weights = self.attention(
                normed,
                normed,
                normed,
                attn_mask=bias,
                key_padding_mask=key_padding_mask,
                need_weights=False,
            )
            attended = torch.nan_to_num(attended)
            tokens = tokens + attended
            tokens = tokens + self.feedforward(self.norm_feedforward(tokens))
            return tokens

    class TraversalBlock(nn.Module):
        """One hop of message passing: context, then the indexed query, then FFN."""

        def __init__(self) -> None:
            super().__init__()
            self.context_attention = nn.MultiheadAttention(
                hidden, heads, dropout=dropout, batch_first=True
            )
            self.norm_context = nn.LayerNorm(hidden)
            self.context_bias = nn.Linear(PAIR_FEATURE_DIM, heads, bias=False)
            self.context_projection = nn.Linear(PAIR_FEATURE_DIM, hidden, bias=False)
            self.query_attention = nn.MultiheadAttention(
                hidden, heads, dropout=dropout, batch_first=True
            )
            self.norm_query = nn.LayerNorm(hidden)
            self.query_bias = nn.Linear(QUERY_CROSS_FEATURE_DIM, heads, bias=False)
            self.feedforward = nn.Sequential(
                nn.Linear(hidden, multiplier * hidden),
                nn.GELU(),
                nn.Linear(multiplier * hidden, hidden),
            )
            self.norm_feedforward = nn.LayerNorm(hidden)

        def forward(
            self,
            candidates,
            context,
            query,
            pair,
            query_cross,
            context_mask,
            query_mask,
        ):
            normed = self.norm_context(candidates)
            bias = self.context_bias(pair).permute(0, 3, 1, 2)
            context_mask = context_mask.to(bias.dtype)
            bias = bias.reshape(-1, pair.shape[1], pair.shape[2])
            attended, _weights = self.context_attention(
                normed,
                context,
                context,
                attn_mask=bias,
                key_padding_mask=context_mask,
                need_weights=False,
            )
            attended = torch.nan_to_num(attended)
            summary = self.context_projection(pair.mean(dim=2))
            candidates = candidates + attended + summary

            normed = self.norm_query(candidates)
            bias = self.query_bias(query_cross).permute(0, 3, 1, 2)
            query_mask = query_mask.to(bias.dtype)
            bias = bias.reshape(-1, query_cross.shape[1], query_cross.shape[2])
            attended, _weights = self.query_attention(
                normed,
                query,
                query,
                attn_mask=bias,
                key_padding_mask=query_mask,
                need_weights=False,
            )
            candidates = candidates + torch.nan_to_num(attended)
            candidates = candidates + self.feedforward(
                self.norm_feedforward(candidates)
            )
            return candidates

    class PathScopedTraversalModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.query_position = nn.Embedding(MAX_QUERY_LENGTH, hidden)
            self.query_blocks = nn.ModuleList(QueryBlock() for _ in range(query_blocks))
            self.candidate_encoder = nn.Linear(CANDIDATE_FEATURE_DIM, hidden)
            self.candidate_norm = nn.LayerNorm(hidden)
            self.context_encoder = nn.Linear(CONTEXT_FEATURE_DIM, hidden)
            self.context_norm = nn.LayerNorm(hidden)
            self.traversal_blocks = nn.ModuleList(
                TraversalBlock() for _ in range(traversal_blocks)
            )
            self.score_head = nn.Sequential(
                nn.Linear(hidden, score_hidden),
                nn.GELU(),
                nn.Linear(score_hidden, 1),
            )
            self.coverage_head = nn.Sequential(
                nn.Linear(COVERAGE_FEATURE_DIM, coverage_hidden),
                nn.GELU(),
                nn.Linear(coverage_hidden, 1),
            )
            self.answer_norm = nn.LayerNorm(hidden)
            self.answer_head = nn.Sequential(
                nn.Linear(hidden + 12, hidden),
                nn.GELU(),
                nn.Linear(hidden, classes),
            )

        @property
        def device(self) -> Any:
            return next(self.parameters()).device

        def _tensor(self, rows: list[list[list[float]]]) -> Any:
            return torch.tensor(rows, dtype=torch.float32, device=self.device)

        def _arrays(self, index: EpisodeIndex, cache: dict[int, Any]) -> Any:
            """Per-episode numpy columns, built once per call and reused.

            The cache is **per-call**, passed in, never stored on the module.
            An id-keyed cache that outlives a `forward` is silently wrong:
            `forward` holds its `EpisodeIndex` objects alive only for the call,
            so a later call allocates new ones that can reuse a freed address
            and receive the previous episode's edge columns. That bug produced
            an out-of-bounds edge id on the second update; `query_cache` avoids
            it by being local, and this now does too.
            """

            from .features_v2 import EpisodeArrays

            key = id(index)
            cached = cache.get(key)
            if cached is None:
                cached = EpisodeArrays(index)
                cache[key] = cached
            return cached

        def _float_mask(self, mask: Any) -> Any:
            """Bool padding mask as an additive float mask.

            `MultiheadAttention` deprecates mixing a bool `key_padding_mask`
            with a float `attn_mask`, and every attention here carries a float
            relational bias, so padding is expressed the same way.
            """

            return torch.zeros_like(mask, dtype=torch.float32).masked_fill(
                mask, float("-inf")
            )

        def encode_query(self, index: EpisodeIndex) -> Any:
            """Query tokens: positional identity plus the repeat pattern."""

            length = index.length
            positions = torch.arange(MAX_QUERY_LENGTH, device=self.device)
            tokens = self.query_position(positions).unsqueeze(0)
            pair = self._tensor(
                [
                    [
                        [
                            query_pair_features(index, position, other)
                            for other in range(MAX_QUERY_LENGTH)
                        ]
                        for position in range(MAX_QUERY_LENGTH)
                    ]
                ]
            )
            mask = torch.tensor(
                [[position >= length for position in range(MAX_QUERY_LENGTH)]],
                device=self.device,
            )
            float_mask = self._float_mask(mask)
            for block in self.query_blocks:
                tokens = block(tokens, pair, float_mask)
            return tokens, mask

        def score_expansions(
            self,
            items: list[tuple[EpisodeIndex, Prefix, list[int], frozenset[int]]],
            query_cache: dict[int, tuple[Any, Any]],
            array_cache: dict[int, Any] | None = None,
        ) -> Any:
            """Stable score `f` for a bag of (episode, prefix, candidate group).

            `f` depends on the query, the prefix and the candidate alone, so an
            arbitrary bag drawn from anywhere in any episode's walk can be scored
            in one padded batch. This is what removes v1's lockstep coupling and
            what makes the visit-order invariance test pass.
            """

            width = max(len(group) for _index, _prefix, group, _e in items)
            context_lists: list[list[tuple[int, int]]] = []
            for index, prefix, _group, expanded in items:
                seen: list[tuple[int, int]] = []
                nodes = [index.start]
                for edge_id in prefix.edges:
                    nodes.append(index.by_id[edge_id]["target"])
                for depth, node in enumerate(nodes):
                    for edge in index.out_edges(node, expanded=expanded):
                        seen.append((edge["edge_id"], depth))
                context_lists.append(seen)
            context_width = max(1, max(len(values) for values in context_lists))

            # Feature arrays are built with numpy and handed to torch, rather
            # than as four-deep Python lists to `torch.tensor`. The scalar
            # featurisers remain the reference implementation; `features_v2`
            # reproduces them elementwise (asserted by
            # `tests/test_read_run_features_v2.py`) and is about nine times
            # faster on the pair grid, which dominates at roughly 322,560 calls
            # per training update. numpy arrives through `require_numpy`, lazily,
            # because it lives in the `read-run` extra like torch.
            from .features_v2 import (
                candidate_feature_rows,
                context_feature_rows,
                pair_feature_grid,
                query_cross_grid,
                require_numpy,
            )

            numpy = require_numpy()
            if array_cache is None:
                array_cache = {}
            candidate_batch = numpy.zeros(
                (len(items), width, CANDIDATE_FEATURE_DIM), dtype=numpy.float32
            )
            context_batch = numpy.zeros(
                (len(items), context_width, CONTEXT_FEATURE_DIM), dtype=numpy.float32
            )
            pair_batch = numpy.zeros(
                (len(items), width, context_width, PAIR_FEATURE_DIM),
                dtype=numpy.float32,
            )
            cross_batch = numpy.zeros(
                (len(items), width, MAX_QUERY_LENGTH, QUERY_CROSS_FEATURE_DIM),
                dtype=numpy.float32,
            )
            candidate_mask, context_mask = [], []
            for row, ((index, prefix, group, _expanded), contexts) in enumerate(
                zip(items, context_lists, strict=True)
            ):
                arrays = self._arrays(index, array_cache)
                padded_group = list(group) + [group[0]] * (width - len(group))
                padded_context = contexts + [contexts[0]] * (
                    context_width - len(contexts)
                )
                candidate_batch[row] = candidate_feature_rows(
                    index, arrays, prefix, padded_group, content_features=use_content
                )
                context_batch[row] = context_feature_rows(
                    index, arrays, prefix, padded_context
                )
                pair_batch[row] = pair_feature_grid(
                    index, arrays, padded_group, [edge for edge, _d in padded_context]
                )
                cross_batch[row] = query_cross_grid(index, arrays, prefix, padded_group)
                candidate_mask.append(
                    [False] * len(group) + [True] * (width - len(group))
                )
                context_mask.append(
                    [False] * len(contexts) + [True] * (context_width - len(contexts))
                )

            def _to_device(array: Any) -> Any:
                return torch.from_numpy(array).to(self.device)

            candidates = self.candidate_norm(
                self.candidate_encoder(_to_device(candidate_batch))
            )
            context = self.context_norm(self.context_encoder(_to_device(context_batch)))
            pair = _to_device(pair_batch)
            cross = _to_device(cross_batch)
            context_key_padding = self._float_mask(
                torch.tensor(context_mask, device=self.device)
            )
            candidate_key_padding = torch.tensor(candidate_mask, device=self.device)

            query_rows, query_masks = [], []
            for index, _prefix, _group, _expanded in items:
                key = id(index)
                if key not in query_cache:
                    query_cache[key] = self.encode_query(index)
                tokens, mask = query_cache[key]
                query_rows.append(tokens)
                query_masks.append(mask)
            query = torch.cat(query_rows, dim=0)
            query_key_padding = self._float_mask(torch.cat(query_masks, dim=0))

            for block in self.traversal_blocks:
                candidates = block(
                    candidates,
                    context,
                    query,
                    pair,
                    cross,
                    context_key_padding,
                    query_key_padding,
                )
            scores = self.score_head(candidates).squeeze(-1)
            return scores, candidates, candidate_key_padding

        def coverage_bonus(self, state: WalkState, prefix: Prefix, budget: int) -> Any:
            features = torch.tensor(
                [coverage_features(state, prefix, budget)],
                dtype=torch.float32,
                device=self.device,
            )
            return self.coverage_head(features).squeeze()

        def answer(
            self,
            tokens: list[Any],
            scores: list[Any],
            index: EpisodeIndex,
            endpoints: list[int],
            routes: list[tuple[int, ...]],
        ) -> Any:
            if tokens:
                stacked = torch.stack(tokens)
                weights = torch.softmax(torch.stack(scores), dim=0).unsqueeze(-1)
                summary = (stacked * weights).sum(dim=0)
            else:
                summary = torch.zeros(hidden, device=self.device)
            extras = []
            for slot in range(2):
                if slot < len(endpoints):
                    mask = index.mask(endpoints[slot])
                    extras += [float((mask >> bit) & 1) for bit in range(4)]
                else:
                    extras += [0.0] * 4
            agree = (
                1.0
                if len(endpoints) == 2
                and index.mask(endpoints[0]) == index.mask(endpoints[1])
                else 0.0
            )
            extras.append(agree)
            extras += _one_hot(min(len(routes), 2), 3)
            feature = torch.cat(
                [
                    self.answer_norm(summary),
                    torch.tensor(extras, dtype=torch.float32, device=self.device),
                ]
            )
            return self.answer_head(feature)

        def forward(
            self,
            visible_batch: list[dict[str, Any]],
            *,
            budget: int,
            supplied: list[list[tuple[Prefix, list[int]]]] | None = None,
            stop_rule: str = "targets_reached_or_exhausted",
        ) -> dict[str, Any]:
            if stop_rule not in {
                "targets_reached_or_exhausted",
                "exhaust",
                "budget_cap",
            }:
                raise TrainingBlocked(f"unknown stop rule: {stop_rule}")
            indexes = [EpisodeIndex(visible) for visible in visible_batch]
            query_cache: dict[int, tuple[Any, Any]] = {}
            array_cache: dict[int, Any] = {}
            count = len(indexes)

            examined: list[list[int]] = [[] for _ in range(count)]
            owner: list[list[tuple[int, ...]]] = [[] for _ in range(count)]
            kept_tokens: list[list[Any]] = [[] for _ in range(count)]
            kept_scores: list[list[Any]] = [[] for _ in range(count)]
            stable: list[list[Any]] = [[] for _ in range(count)]
            scored: list[set[int]] = [set() for _ in range(count)]
            expanded: list[set[int]] = [set() for _ in range(count)]
            states: list[set[tuple[int, int]]] = [set() for _ in range(count)]
            frontier: list[dict[int, tuple[Any, Prefix]]] = [{} for _ in range(count)]
            walk_state = [WalkState() for _ in range(count)]
            endpoints: list[list[int]] = [[] for _ in range(count)]
            routes: list[list[tuple[int, ...]]] = [[] for _ in range(count)]
            stop_reason: list[str] = [STOP_TREE_EXHAUSTED] * count
            bonus_by_depth: list[dict[int, Any]] = [{} for _ in range(count)]
            active = list(range(count))

            if supplied is not None:
                pending: list[list[tuple[Prefix, list[int]]]] = [
                    list(values) for values in supplied
                ]
            else:
                pending = [[(Prefix((), index.start, 0), None)] for index in indexes]

            def refresh_bonus(slot: int) -> None:
                walk_state[slot].epoch += 1
                bonus_by_depth[slot] = {}

            def bonus(slot: int, prefix: Prefix) -> Any:
                cached = bonus_by_depth[slot].get(prefix.depth)
                if cached is None:
                    cached = self.coverage_bonus(walk_state[slot], prefix, budget)
                    bonus_by_depth[slot][prefix.depth] = cached
                return cached

            while active:
                batch: list[tuple[int, EpisodeIndex, Prefix, list[int]]] = []
                for slot in list(active):
                    if not pending[slot]:
                        continue
                    prefix, group = pending[slot].pop(0)
                    if (prefix.node, prefix.depth) in states[slot]:
                        continue
                    states[slot].add((prefix.node, prefix.depth))
                    expanded[slot].add(prefix.node)
                    if group is None:
                        group = [
                            edge["edge_id"] for edge in indexes[slot].group(prefix.node)
                        ]
                    batch.append((slot, indexes[slot], prefix, list(group)))
                if not batch:
                    break

                scores, tokens, _mask = self.score_expansions(
                    [
                        (index, prefix, group, frozenset(expanded[slot]))
                        for slot, index, prefix, group in batch
                    ],
                    query_cache,
                    array_cache,
                )
                for row, (slot, index, prefix, group) in enumerate(batch):
                    walk_state[slot].expansions += 1
                    remaining = budget - len(examined[slot])
                    fresh = [
                        edge_id for edge_id in group if edge_id not in scored[slot]
                    ][:remaining]
                    for column, edge_id in enumerate(group):
                        if edge_id in fresh:
                            examined[slot].append(edge_id)
                            owner[slot].append(prefix.edges)
                            scored[slot].add(edge_id)
                            kept_tokens[slot].append(tokens[row, column])
                            kept_scores[slot].append(scores[row, column])
                            stable[slot].append(scores[row, column])
                    walk_state[slot].examined = len(examined[slot])
                    if prefix.depth < index.length:
                        wanted = index.relations[prefix.depth]
                        for column, edge_id in enumerate(group):
                            edge = index.by_id[edge_id]
                            if edge["relation"] != wanted:
                                continue
                            child = Prefix(
                                prefix.edges + (edge_id,),
                                edge["target"],
                                prefix.depth + 1,
                            )
                            if (child.node, child.depth) in states[slot]:
                                continue
                            frontier[slot].setdefault(
                                edge_id, (scores[row, column], child)
                            )

                if supplied is not None:
                    active = [slot for slot in active if pending[slot]]
                    continue

                for slot in list(active):
                    while True:
                        if len(examined[slot]) >= budget:
                            stop_reason[slot] = STOP_BUDGET_CAP
                            active.remove(slot)
                            break
                        if (
                            stop_rule == "targets_reached_or_exhausted"
                            and len(set(endpoints[slot])) >= EXPECTED_TARGET_COUNT
                        ):
                            stop_reason[slot] = STOP_TARGETS_REACHED
                            active.remove(slot)
                            break
                        if not frontier[slot]:
                            stop_reason[slot] = STOP_TREE_EXHAUSTED
                            walk_state[slot].exhausted += 1
                            active.remove(slot)
                            break
                        chosen = max(
                            frontier[slot],
                            key=lambda edge_id: (
                                float(frontier[slot][edge_id][0].detach())
                                + float(
                                    bonus(slot, frontier[slot][edge_id][1]).detach()
                                ),
                                -edge_id,
                            ),
                        )
                        _score, child = frontier[slot].pop(chosen)
                        if child.depth >= indexes[slot].length:
                            if child.node not in endpoints[slot]:
                                endpoints[slot].append(child.node)
                                routes[slot].append(child.edges)
                                walk_state[slot].complete_routes += 1
                                walk_state[slot].endpoints = frozenset(endpoints[slot])
                                refresh_bonus(slot)
                            continue
                        if (child.node, child.depth) in states[slot]:
                            continue
                        pending[slot].append((child, None))
                        break

            width = max((len(values) for values in examined), default=1) or 1
            logits = torch.stack(
                [
                    self.answer(
                        kept_tokens[slot],
                        kept_scores[slot],
                        indexes[slot],
                        endpoints[slot],
                        routes[slot],
                    )
                    for slot in range(count)
                ]
            )
            score_rows, stable_rows, masks = [], [], []
            zero = torch.zeros((), device=self.device)
            for slot in range(count):
                pad = width - len(kept_scores[slot])
                score_rows.append(
                    torch.stack(kept_scores[slot] + [zero] * pad)
                    if kept_scores[slot] or pad
                    else zero.reshape(1)
                )
                stable_rows.append(
                    torch.stack(stable[slot] + [zero] * pad)
                    if stable[slot] or pad
                    else zero.reshape(1)
                )
                masks.append([True] * len(kept_scores[slot]) + [False] * pad)
            return {
                "logits": logits,
                "scores": torch.stack(score_rows),
                "stable_scores": torch.stack(stable_rows),
                "score_mask": torch.tensor(masks, device=self.device),
                "edge_ids": examined,
                "prefixes": owner,
                "routes": [[list(route) for route in values] for values in routes],
                "stop_reason": stop_reason,
                "examined_count": [len(values) for values in examined],
                "expansion_count": [state.expansions for state in walk_state],
            }

    return PathScopedTraversalModel()
