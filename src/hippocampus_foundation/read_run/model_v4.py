"""Track Q's model: v3's walk and stop, plus a head that scores route *sets*.

Version-additive. `model_v3` is not edited; this subclasses the module
`build_read_model_v3` returns, as v3 subclasses v2, so the walk, the stop head and
every shared parameter are the same objects. Two things change, both forced by
Track P's measurements (`experiments/track_p_v1/track_p_screening_report.md`).

**1. The returned set is decided per route, in the context of the other
candidates.** Track P returned an edge when its own logit was positive, and that
rule could not express what identifies a target: on distractor-route edges the
per-edge scorer sat at chance (50.9 % positive) with its loss flat from update
1,500, because "is this route one of the targets" is a comparison *across*
routes that `f(query, prefix, edge)` cannot see. Here every complete candidate
route in the examined set is decoded (`evaluation_v3.decode_all_routes`, uncapped),
encoded from the walk tokens of its own edges plus route-level features, passed
through self-attention over the candidate set, and given one logit. The returned
set is every route above zero. **There is no 2 anywhere in this head**: it may
return one route, three, or none.

**The feature it is deliberately not given.** A zero-parameter rule — "return the
largest group of candidates whose endpoints share an assertion mask" — scores
0.909–0.949 proof-valid on non-abstain episodes and 0.000 on abstain ones, because
the generator gives the targets a shared mask exactly when the episode is
non-abstain. Handing the head a mask-agreement count would buy that number and no
capability. Each route's own endpoint mask *bits* are a feature, as visible
evidence the head may weigh; the precomputed answer to "which pair agrees" is not.

**2. The answer head no longer hard-codes the constant Track P existed to remove.**
`model_v2.answer` reads `for slot in range(2)`, flags agreement only when
`len(endpoints) == 2`, and caps the route count at `min(len(routes), 2)`. On v3
data a walk registers three or more endpoints, so it saw an arbitrary two and its
agreement flag was wrong whenever a distractor was registered; class accuracy was
0.46–0.50. Here the registered endpoints are pooled as a set — mean and max over an
encoding of each endpoint's mask bits — and the route count is a raw count scaled
by `MAX_QUERY_LENGTH`. Capacity therefore differs from v3 and is reported; the
untrained reference is re-measured rather than assumed.
"""

from __future__ import annotations

from typing import Any

from .errors import TrainingBlocked
from .evaluation_v3 import decode_all_routes
from .model import require_torch
from .model_v2 import MAX_QUERY_LENGTH, EpisodeIndex
from .model_v3 import build_read_model_v3

__all__ = [
    "ROUTE_FEATURE_DIM",
    "build_read_model_v4",
    "route_features",
    "trainable_parameter_count_v4",
]

# Endpoint mask bits (4), length, mean / min / max edge logit, longest shared
# prefix with any other candidate. No count of anything across candidates.
ROUTE_FEATURE_DIM = 9
ENDPOINT_FEATURE_DIM = 4


def route_features(
    index: EpisodeIndex,
    route: tuple[int, ...],
    others: list[tuple[int, ...]],
    edge_logits: dict[int, float],
) -> list[float]:
    """Per-route features that are comparisons of *this* route against the set.

    `others` is every other candidate; the only cross-candidate quantity is the
    longest prefix this route shares with any of them, a structural fact about
    where it branched. Nothing here counts endpoint-mask agreement.
    """

    endpoint = index.by_id[route[-1]]["target"]
    mask = index.mask(endpoint)
    logits = [edge_logits[e] for e in route]
    shared = 0
    for other in others:
        k = 0
        while k < min(len(route), len(other)) and route[k] == other[k]:
            k += 1
        shared = max(shared, k)
    features = [float((mask >> bit) & 1) for bit in range(4)]
    features.append(len(route) / MAX_QUERY_LENGTH)
    features.append(sum(logits) / len(logits))
    features.append(min(logits))
    features.append(max(logits))
    features.append(shared / MAX_QUERY_LENGTH)
    if len(features) != ROUTE_FEATURE_DIM:
        raise TrainingBlocked("route feature width drifted from its constant")
    return features


def trainable_parameter_count_v4(model: Any) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def build_read_model_v4(config: dict[str, Any]) -> Any:
    """v3 plus a route-set head and a set-pooled answer head."""

    torch, nn, _functional = require_torch()
    base = build_read_model_v3(config)
    model_config = config["model"]
    hidden = int(model_config["hidden_dimension"])
    heads = int(model_config["self_attention_heads"])
    classes = int(model_config["output_classes"])
    dropout = float(model_config["dropout"])
    endpoint_hidden = int(model_config.get("endpoint_hidden_dimension", 64))

    class TrackQTraversalModel(type(base)):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.route_encoder = nn.Linear(hidden + ROUTE_FEATURE_DIM, hidden)
            self.route_norm = nn.LayerNorm(hidden)
            self.route_attention = nn.MultiheadAttention(
                hidden, heads, dropout=dropout, batch_first=True
            )
            self.route_attention_norm = nn.LayerNorm(hidden)
            self.route_feedforward = nn.Sequential(
                nn.Linear(hidden, hidden), nn.GELU(), nn.Linear(hidden, hidden)
            )
            self.route_feedforward_norm = nn.LayerNorm(hidden)
            self.route_head = nn.Linear(hidden, 1)
            # The set-pooled answer path that replaces v2's two fixed slots.
            self.endpoint_encoder = nn.Sequential(
                nn.Linear(ENDPOINT_FEATURE_DIM, endpoint_hidden), nn.GELU()
            )
            self.answer_head_v4 = nn.Sequential(
                nn.Linear(hidden + 2 * endpoint_hidden + 1, hidden),
                nn.GELU(),
                nn.Linear(hidden, classes),
            )

        # --- answer: set-pooled endpoints, no constant ------------------------

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
            if endpoints:
                bits = torch.tensor(
                    [
                        [float((index.mask(node) >> bit) & 1) for bit in range(4)]
                        for node in endpoints
                    ],
                    dtype=torch.float32,
                    device=self.device,
                )
                encoded = self.endpoint_encoder(bits)
                pooled = torch.cat([encoded.mean(dim=0), encoded.max(dim=0).values])
            else:
                pooled = torch.zeros(2 * endpoint_hidden, device=self.device)
            count = torch.tensor(
                [len(routes) / MAX_QUERY_LENGTH],
                dtype=torch.float32,
                device=self.device,
            )
            feature = torch.cat([self.answer_norm(summary), pooled, count])
            return self.answer_head_v4(feature)

        # --- route set ----------------------------------------------------------

        def score_routes(
            self, out: dict[str, Any], cuts: list[int] | None = None
        ) -> dict[str, Any]:
            """Score every complete candidate route in each episode's examined set.

            Returns per-episode candidate lists and their logits. `cuts` limits
            the examined prefix each episode may decode from (training reads at
            T*, evaluation at the stop); by default the whole examined set.
            """

            candidates: list[list[tuple[int, ...]]] = []
            logits: list[Any] = []
            for slot, (tokens, scores, index, _endpoints, _routes) in enumerate(
                out["answer_inputs"]
            ):
                cut = cuts[slot] if cuts is not None else len(out["edge_ids"][slot])
                edge_ids = out["edge_ids"][slot][:cut]
                position = {edge_id: k for k, edge_id in enumerate(edge_ids)}
                routes = [
                    tuple(r)
                    for r in decode_all_routes(
                        index.visible, edge_ids, [0.0] * len(edge_ids)
                    )
                ]
                candidates.append(routes)
                if not routes:
                    logits.append(torch.zeros(0, device=self.device))
                    continue
                edge_logits = {
                    edge_id: float(scores[position[edge_id]].detach())
                    for route in routes
                    for edge_id in route
                }
                rows = []
                feats = []
                for route in routes:
                    rows.append(
                        torch.stack([tokens[position[e]] for e in route]).mean(dim=0)
                    )
                    feats.append(
                        route_features(
                            index, route, [o for o in routes if o != route], edge_logits
                        )
                    )
                encoded = self.route_norm(
                    self.route_encoder(
                        torch.cat(
                            [
                                torch.stack(rows),
                                torch.tensor(
                                    feats, dtype=torch.float32, device=self.device
                                ),
                            ],
                            dim=-1,
                        )
                    )
                ).unsqueeze(0)
                attended, _w = self.route_attention(
                    self.route_attention_norm(encoded),
                    self.route_attention_norm(encoded),
                    self.route_attention_norm(encoded),
                    need_weights=False,
                )
                encoded = encoded + torch.nan_to_num(attended)
                encoded = encoded + self.route_feedforward(
                    self.route_feedforward_norm(encoded)
                )
                logits.append(self.route_head(encoded).squeeze(0).squeeze(-1))
            return {"route_candidates": candidates, "route_logits": logits}

        def returned_routes(self, scored: dict[str, Any]) -> list[list[list[int]]]:
            """Every candidate above zero. One, three or none — no constant."""

            out = []
            for routes, logits in zip(
                scored["route_candidates"], scored["route_logits"], strict=True
            ):
                out.append(
                    [
                        list(r)
                        for r, logit in zip(routes, logits.tolist(), strict=True)
                        if logit > 0.0
                    ]
                )
            return out

    model = TrackQTraversalModel()
    missing, unexpected = model.load_state_dict(base.state_dict(), strict=False)
    new = {
        "route_encoder",
        "route_norm",
        "route_attention",
        "route_attention_norm",
        "route_feedforward",
        "route_feedforward_norm",
        "route_head",
        "endpoint_encoder",
        "answer_head_v4",
    }
    stray = [k for k in missing if k.split(".")[0] not in new]
    if stray or unexpected:
        raise TrainingBlocked(
            f"v4 state does not extend v3 cleanly: {stray} {unexpected}"
        )
    return model
