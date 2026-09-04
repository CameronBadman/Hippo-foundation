"""Track Q's route-set loss: per-route BCE plus a within-episode ranking term.

Labels are exact: a candidate route is positive iff it is one of the episode's
two planted target routes (`valid_routes`). The BCE trains each route's logit
towards its own label; the ranking term asks, for every (target, distractor) pair
*within one episode*, that the target's logit exceed the distractor's, which is
the comparison the per-edge head could never make. Neither term carries a
threshold, and the returned set is read at zero — the BCE's own boundary.

Per-episode mean, then batch mean, as every other loss in this package: an
episode with two candidates weighs the same as one with five.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .errors import TrainingBlocked
from .generator import GeneratedEpisode

__all__ = ["route_labels", "route_loss"]


def route_labels(
    episodes: Sequence[GeneratedEpisode],
    candidates: Sequence[Sequence[tuple[int, ...]]],
) -> list[list[float]]:
    out = []
    for episode, routes in zip(episodes, candidates, strict=True):
        targets = {tuple(r) for r in episode.hidden["valid_routes"]}
        out.append([1.0 if route in targets else 0.0 for route in routes])
    return out


def route_loss(
    torch: Any,
    functional: Any,
    logits: Sequence[Any],
    labels: Sequence[Sequence[float]],
    *,
    ranking_weight: float = 1.0,
) -> Any:
    """BCE per candidate plus softplus(distractor − target) over pairs, per episode."""

    if len(logits) != len(labels):
        raise TrainingBlocked("route logits and labels disagree on the batch size")
    per_episode = []
    for row, target in zip(logits, labels, strict=True):
        if row.shape[0] != len(target):
            raise TrainingBlocked(
                "route labels and candidates disagree within an episode"
            )
        if not target:
            continue
        goal = torch.tensor(target, dtype=row.dtype, device=row.device)
        term = functional.binary_cross_entropy_with_logits(row, goal, reduction="mean")
        positive = row[goal > 0.5]
        negative = row[goal <= 0.5]
        if positive.numel() and negative.numel():
            gap = negative.unsqueeze(0) - positive.unsqueeze(1)
            term = term + ranking_weight * functional.softplus(gap).mean()
        per_episode.append(term)
    if not per_episode:
        raise TrainingBlocked("no candidate routes in the batch")
    return torch.stack(per_episode).mean()
