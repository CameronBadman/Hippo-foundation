"""Equal-capacity PyTorch model used by both preregistered arms.

PyTorch is imported lazily so generation, integrity gates, and package smoke
tests remain usable without an ML runtime. Both arms instantiate this exact
class; only the candidate-exposure schedule differs.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from .errors import TrainingBlocked
from .generator import structural_bfs_pool


def require_torch() -> tuple[Any, Any, Any]:
    try:
        import torch
        from torch import nn
        from torch.nn import functional
    except ImportError as exc:
        raise TrainingBlocked(
            "READ training requires PyTorch; install the read-run runtime first"
        ) from exc
    return torch, nn, functional


def _assertion_vector(values: list[int]) -> list[float]:
    result = [0.0, 0.0, 0.0, 0.0]
    for value in values:
        if value not in range(4):
            raise TrainingBlocked("model input assertion index is outside 0..3")
        result[value] = 1.0
    return result


def _structural_order(router_seed: str, edge: dict[str, int]) -> bytes:
    return hashlib.sha256(
        (
            f"{router_seed}:{edge['source']}:{edge['target']}:"
            f"{edge['relation']}:{edge['edge_id']}"
        ).encode()
    ).digest()


def build_read_model(config: dict[str, Any]) -> Any:
    torch, nn, _functional = require_torch()
    model_config = config["model"]
    hidden = int(model_config["hidden_dimension"])
    edge_hidden = int(model_config["edge_hidden_dimension"])
    score_hidden = int(model_config["score_hidden_dimension"])
    heads = int(model_config["self_attention_heads"])
    maximum_relations = int(model_config["maximum_relation_types"])
    output_classes = int(model_config["output_classes"])

    class EqualCapacityReadModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.hidden_dimension = hidden
            self.relation_embedding = nn.Embedding(maximum_relations, hidden)
            self.assertion_encoder = nn.Linear(4, hidden)
            self.query_encoder = nn.GRU(hidden, hidden, batch_first=True)
            self.edge_encoder = nn.Sequential(
                nn.Linear(hidden * 4 + 1, edge_hidden),
                nn.GELU(),
                nn.Linear(edge_hidden, hidden),
                nn.LayerNorm(hidden),
            )
            self.joint_attention = nn.MultiheadAttention(
                hidden,
                heads,
                dropout=float(model_config["dropout"]),
                batch_first=True,
            )
            self.state_cell = nn.GRUCell(hidden, hidden)
            self.edge_scorer = nn.Sequential(
                nn.Linear(hidden * 3, score_hidden),
                nn.GELU(),
                nn.Linear(score_hidden, 1),
            )
            self.answer_head = nn.Sequential(
                nn.Linear(hidden * 2, hidden),
                nn.GELU(),
                nn.Linear(hidden, output_classes),
            )

        def _query(self, visible_batch: list[dict[str, Any]]) -> Any:
            sequences = [
                torch.tensor(
                    visible["query_relations"], dtype=torch.long, device=self.device
                )
                for visible in visible_batch
            ]
            lengths = torch.tensor(
                [len(value) for value in sequences],
                dtype=torch.long,
                device="cpu",
            )
            padded = nn.utils.rnn.pad_sequence(sequences, batch_first=True)
            embedded = self.relation_embedding(padded)
            packed = nn.utils.rnn.pack_padded_sequence(
                embedded, lengths, batch_first=True, enforce_sorted=False
            )
            _output, state = self.query_encoder(packed)
            return state[-1]

        @property
        def device(self) -> Any:
            return next(self.parameters()).device

        def _edge_batch(
            self,
            visible_batch: list[dict[str, Any]],
            edge_ids_batch: list[list[int]],
            query: Any,
        ) -> Any:
            if not edge_ids_batch or len(visible_batch) != len(edge_ids_batch):
                raise TrainingBlocked("edge tensorization batch is empty or misaligned")
            width = len(edge_ids_batch[0])
            if width == 0 or any(len(values) != width for values in edge_ids_batch):
                raise TrainingBlocked(
                    "edge tensorization requires a fixed nonzero width"
                )
            source_assertions: list[list[list[float]]] = []
            target_assertions: list[list[list[float]]] = []
            relations: list[list[int]] = []
            similarities: list[list[list[float]]] = []
            for visible, edge_ids in zip(visible_batch, edge_ids_batch, strict=True):
                nodes = {
                    node["node"]: _assertion_vector(node["assertions"])
                    for node in visible["nodes"]
                }
                edges = {edge["edge_id"]: edge for edge in visible["edges"]}
                selected = [edges[edge_id] for edge_id in edge_ids]
                source_assertions.append([nodes[edge["source"]] for edge in selected])
                target_assertions.append([nodes[edge["target"]] for edge in selected])
                relations.append([edge["relation"] for edge in selected])
                similarities.append(
                    [[edge["query_similarity_ppm"] / 1_000_000] for edge in selected]
                )
            source = self.assertion_encoder(
                torch.tensor(source_assertions, dtype=torch.float32, device=self.device)
            )
            target = self.assertion_encoder(
                torch.tensor(target_assertions, dtype=torch.float32, device=self.device)
            )
            relation = self.relation_embedding(
                torch.tensor(relations, dtype=torch.long, device=self.device)
            )
            similarity = torch.tensor(
                similarities, dtype=torch.float32, device=self.device
            )
            expanded_query = query.unsqueeze(1).expand(-1, width, -1)
            return self.edge_encoder(
                torch.cat(
                    [source, target, relation, expanded_query, similarity], dim=-1
                )
            )

        def _scores(self, edge_state: Any, controller: Any, query: Any) -> Any:
            width = edge_state.shape[1]
            expanded_controller = controller.unsqueeze(1).expand(-1, width, -1)
            expanded_query = query.unsqueeze(1).expand(-1, width, -1)
            return self.edge_scorer(
                torch.cat([edge_state, expanded_controller, expanded_query], dim=-1)
            ).squeeze(-1)

        def forward_direct(
            self, visible_batch: list[dict[str, Any]], budget: int
        ) -> dict[str, Any]:
            pools = [structural_bfs_pool(visible, budget) for visible in visible_batch]
            query = self._query(visible_batch)
            encoded = self._edge_batch(visible_batch, pools, query)
            contextual, _weights = self.joint_attention(encoded, encoded, encoded)
            state = self.state_cell(contextual.mean(dim=1), query)
            scores = self._scores(contextual, state, query)
            pooling = torch.softmax(scores, dim=1).unsqueeze(-1)
            summary = (contextual * pooling).sum(dim=1)
            logits = self.answer_head(torch.cat([state, summary], dim=-1))
            return {"logits": logits, "scores": scores, "edge_ids": pools}

        def _forward_trav_one(
            self, visible: dict[str, Any], budget: int
        ) -> dict[str, Any]:
            query = self._query([visible])
            state = query
            by_source: dict[int, list[dict[str, int]]] = defaultdict(list)
            for edge in visible["edges"]:
                by_source[edge["source"]].append(edge)
            for values in by_source.values():
                values.sort(
                    key=lambda edge: _structural_order(visible["router_seed"], edge)
                )
            expanded_nodes: set[int] = set()
            scored_ids: set[int] = set()
            pending: dict[int, tuple[Any, Any]] = {}
            all_ids: list[int] = []
            all_representations: list[Any] = []
            all_scores: list[Any] = []
            current = visible["start_node"]
            while len(all_ids) < budget:
                if current not in expanded_nodes:
                    new_ids = [
                        edge["edge_id"]
                        for edge in by_source[current]
                        if edge["edge_id"] not in scored_ids
                    ][: budget - len(all_ids)]
                    expanded_nodes.add(current)
                    if new_ids:
                        encoded = self._edge_batch([visible], [new_ids], query)
                        contextual, _weights = self.joint_attention(
                            encoded, encoded, encoded
                        )
                        scores = self._scores(contextual, state, query)[0]
                        for offset, edge_id in enumerate(new_ids):
                            representation = contextual[0, offset]
                            score = scores[offset]
                            pending[edge_id] = (representation, score)
                            all_ids.append(edge_id)
                            all_representations.append(representation)
                            all_scores.append(score)
                            scored_ids.add(edge_id)
                if len(all_ids) == budget:
                    break
                if not pending:
                    raise TrainingBlocked(
                        "TRAV exhausted its frontier before consuming the edge budget"
                    )
                chosen_id = max(
                    pending,
                    key=lambda edge_id: (float(pending[edge_id][1].detach()), -edge_id),
                )
                representation, _score = pending.pop(chosen_id)
                state = self.state_cell(representation.unsqueeze(0), state)
                current = visible["edges"][chosen_id]["target"]
            representations = torch.stack(all_representations).unsqueeze(0)
            scores = torch.stack(all_scores).unsqueeze(0)
            pooling = torch.softmax(scores, dim=1).unsqueeze(-1)
            summary = (representations * pooling).sum(dim=1)
            logits = self.answer_head(torch.cat([state, summary], dim=-1))
            return {"logits": logits, "scores": scores, "edge_ids": [all_ids]}

        def forward_trav(
            self, visible_batch: list[dict[str, Any]], budget: int
        ) -> dict[str, Any]:
            outputs = [
                self._forward_trav_one(visible, budget) for visible in visible_batch
            ]
            return {
                "logits": torch.cat([item["logits"] for item in outputs], dim=0),
                "scores": torch.cat([item["scores"] for item in outputs], dim=0),
                "edge_ids": [item["edge_ids"][0] for item in outputs],
            }

        def forward(
            self, visible_batch: list[dict[str, Any]], *, arm: str, budget: int
        ) -> dict[str, Any]:
            if arm == "DIRECT":
                return self.forward_direct(visible_batch, budget)
            if arm == "TRAV":
                return self.forward_trav(visible_batch, budget)
            raise TrainingBlocked(f"unknown READ arm: {arm}")

    return EqualCapacityReadModel()


def trainable_parameter_count(model: Any) -> int:
    return sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )


def expected_trainable_parameter_count(config: dict[str, Any]) -> int:
    """Compute the exact parameter count without importing PyTorch."""

    value = config["model"]
    hidden = int(value["hidden_dimension"])
    edge_hidden = int(value["edge_hidden_dimension"])
    score_hidden = int(value["score_hidden_dimension"])
    relations = int(value["maximum_relation_types"])
    outputs = int(value["output_classes"])
    relation_embedding = relations * hidden
    assertion_encoder = 4 * hidden + hidden
    query_gru = 6 * hidden * hidden + 6 * hidden
    edge_encoder = (
        (4 * hidden + 1) * edge_hidden
        + edge_hidden
        + edge_hidden * hidden
        + hidden
        + 2 * hidden
    )
    attention = 4 * hidden * hidden + 4 * hidden
    state_cell = 6 * hidden * hidden + 6 * hidden
    scorer = 3 * hidden * score_hidden + score_hidden + score_hidden + 1
    answer = 2 * hidden * hidden + hidden + hidden * outputs + outputs
    return sum(
        (
            relation_embedding,
            assertion_encoder,
            query_gru,
            edge_encoder,
            attention,
            state_cell,
            scorer,
            answer,
        )
    )
