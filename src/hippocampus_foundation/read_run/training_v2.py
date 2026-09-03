"""Losses and the supervision schedule for Track O. Version-additive.

`training._edge_targets` builds a fixed-width tensor, which is correct for v1
where both arms always examined exactly `budget` edges. The Track O walk stops
when it is done, so examined sets are ragged by construction and the edge loss
needs a padded, masked form. Two consequences are deliberate:

- the per-episode mean is taken **before** the batch mean, so an episode that
  stops at twelve edges is weighted equally with one that spends sixty-four
  rather than contributing a fifth as much signal;
- the loss reads `scores`, which is the stable term alone. This was intended to
  give the coverage head a gradient path without a second loss weight, and it
  does not: `model_v2.forward` appends the score head's output to `kept_scores`
  and admits the coverage bonus only under `.detach()` in the selection step, so
  the coverage head received zero gradient for the whole of Track O and its
  parameters are byte-identical to initialisation. Recorded in design notes
  2.22. Track P replaces that head with a supervised stop head, which has a real
  loss term; a budget-versus-coverage weight remains ruled out by 2.16.

The supervision schedule is the M6 mix. Because scoring is path-scoped, a route
edge can be supervised under its *true* prefix no matter where the model's own
walk went, so the exposure-bias loop v1 had — wrong branch, no signal, wrong
branch — cannot arise. The mix is a data decision, preregistered as fractions of
`update_count`, never swept.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from .errors import TrainingBlocked
from .generator import GeneratedEpisode

SUPERVISION_SOURCES = ("gold", "walker", "on_policy")


def supervision_source(
    update: int, total_updates: int, schedule: dict[str, Any]
) -> str:
    """Which prefix source this update draws from, per the preregistered schedule."""

    if total_updates <= 0:
        raise TrainingBlocked("update count must be positive")
    position = update / total_updates
    for name in SUPERVISION_SOURCES:
        window = schedule.get(name)
        if window is None:
            continue
        start, end = float(window[0]), float(window[1])
        if start <= position < end:
            return name
    return "on_policy"


def episode_source(
    episode: GeneratedEpisode, update: int, schedule_source: str, blend: float = 0.0
) -> str:
    """Per-episode source, so a window can blend deterministically rather than switch.

    The blend fraction is hashed from `(episode_id, update)`, so the assignment
    is reproducible from the run's own record and does not depend on batch order.
    """

    if blend <= 0.0 or schedule_source == "on_policy":
        return schedule_source
    digest = hashlib.sha256(f"{episode.episode_id}:{update}".encode()).digest()
    draw = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return "on_policy" if draw < blend else schedule_source


def labels_v2(torch: Any, episodes: Sequence[GeneratedEpisode], device: Any) -> Any:
    """Answer targets: abstain is class 0, otherwise the shared assertion mask."""

    values = [
        0 if episode.hidden["abstain"] else int(episode.hidden["gold_assertion_mask"])
        for episode in episodes
    ]
    return torch.tensor(values, dtype=torch.long, device=device)


def edge_targets_ragged(
    torch: Any,
    episodes: Sequence[GeneratedEpisode],
    edge_ids: Sequence[Sequence[int]],
    width: int,
    device: Any,
) -> tuple[Any, Any]:
    """Padded route-membership targets and their validity mask."""

    targets, masks = [], []
    for episode, examined in zip(episodes, edge_ids, strict=True):
        positives = {
            edge_id for route in episode.hidden["valid_routes"] for edge_id in route
        }
        row = [1.0 if edge_id in positives else 0.0 for edge_id in examined]
        pad = width - len(row)
        if pad < 0:
            raise TrainingBlocked("examined set is wider than the padded width")
        targets.append(row + [0.0] * pad)
        masks.append([True] * len(row) + [False] * pad)
    return (
        torch.tensor(targets, dtype=torch.float32, device=device),
        torch.tensor(masks, dtype=torch.bool, device=device),
    )


def masked_edge_loss(
    torch: Any, functional: Any, scores: Any, targets: Any, mask: Any
) -> Any:
    """Per-episode mean BCE over the examined edges, then the batch mean."""

    raw = functional.binary_cross_entropy_with_logits(scores, targets, reduction="none")
    weights = mask.to(raw.dtype)
    per_episode = (raw * weights).sum(dim=1) / weights.sum(dim=1).clamp(min=1.0)
    return per_episode.mean()


def examined_set_precision(
    episodes: Sequence[GeneratedEpisode], edge_ids: Sequence[Sequence[int]]
) -> list[float]:
    """Fraction of each examined set that lies on a route — the write-path metric."""

    out = []
    for episode, examined in zip(episodes, edge_ids, strict=True):
        positives = {
            edge_id for route in episode.hidden["valid_routes"] for edge_id in route
        }
        out.append(len(positives & set(examined)) / len(examined) if examined else 0.0)
    return out
