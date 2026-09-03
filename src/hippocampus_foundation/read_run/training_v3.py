"""Track P's losses: a supervised stop, an answer read at T*, and the edge BCE.

Three heads, three exact labels, no weight that sets an operating point. Design
note 2.16 rules out a tuned budget-versus-coverage trade-off; that is not what
the loss weights here do. Each head is separately supervised against labels that
are exactly derivable from hidden truth, so each converges to its own Bayes
solution and the mixture changes only how fast, never where.

**The stop label is `route_complete_now`, defined on registration.** At every
decision point, before the expansion it would avoid: have both target endpoints
already been *registered* by this walk? Markov, exactly derivable, and it
survives a change of policy, which is what lets the stop head train off-policy
on an exhaustive walk and then be used to halt one.

Registration rather than set coverage, for the reason measured in design note
2.23: a target's final edge can enter the examined set through an expansion at
a different depth while the walk never pops the correct-depth prefix. A
set-coverage label would then read 1 at a point where the model's own endpoint
list holds one target, and no structural feature could explain the difference.
That is a label the head cannot learn, and it would look like a capability
ceiling rather than a labelling bug.

Alternatives rejected, with the reason recorded so they are not retried:

- *"Stop exactly once", a single positive at T\*.* A walk that misses T\* has no
  positive at all, so the label turns "stopped late" into "never stop".
- *Cost-to-go regression.* The target is non-stationary under a changing policy,
  and turning a predicted cost into a decision needs a comparison constant,
  which is precisely the hard-coded threshold this track exists to remove.
- *"Will some future expansion find a route".* The negation of the chosen label,
  with the same information and a harder credit assignment.

**The answer trains at T\***, the first decision point whose label is 1 — the
stop is teacher-forced from hidden truth during training, so the answer head
sees the same examined prefix under `gold`, `walker` and `on_policy`. At
evaluation the answer is read at the learned stop, and the early-stop rate is
reported so any residual train/eval gap is visible rather than hidden.

**Every training walk exhausts**, with the stop head's own output ignored. That
decouples what the stop head *learns* from what it *does*, and yields decision
points on both sides of completion — which a walk that halted at its own
prediction would not.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .errors import TrainingBlocked
from .generator import GeneratedEpisode

__all__ = [
    "SUPERVISION_SOURCES_V3",
    "answer_cut_indices",
    "stop_labels",
    "stop_loss",
    "supervision_source_v3",
]

# `walker` is dropped from Track O's three. Under exhaustion a walker-ordered
# and an on-policy walk examine the same prefix tree in a different order, and
# `f` is order-invariant, so they are the same edge-loss data; on-policy still
# differs for the stop head's state distribution, which is why it is kept.
SUPERVISION_SOURCES_V3 = ("gold", "on_policy")


def supervision_source_v3(
    update: int, total_updates: int, schedule: dict[str, Any]
) -> str:
    """Which prefix source this update draws from, per the preregistered schedule."""

    if total_updates <= 0:
        raise TrainingBlocked("update count must be positive")
    position = update / total_updates
    for name in SUPERVISION_SOURCES_V3:
        window = schedule.get(name)
        if window is None:
            continue
        start, end = float(window[0]), float(window[1])
        if start <= position < end:
            return name
    return "on_policy"


def stop_labels(
    episodes: Sequence[GeneratedEpisode], decisions: Sequence[Sequence[Any]]
) -> list[list[float]]:
    """`route_complete_now` at every decision point of every episode.

    1 where both target endpoints are already registered, 0 otherwise. Reads
    `target_nodes` from hidden truth; the model never sees it.
    """

    out: list[list[float]] = []
    for episode, points in zip(episodes, decisions, strict=True):
        targets = set(episode.hidden["target_nodes"])
        out.append(
            [1.0 if targets <= set(point.endpoints) else 0.0 for point in points]
        )
    return out


def answer_cut_indices(
    episodes: Sequence[GeneratedEpisode],
    decisions: Sequence[Sequence[Any]],
    examined_counts: Sequence[int],
) -> list[int]:
    """How many examined edges the answer head may read, per episode: T*.

    T* is the first decision point whose stop label is 1. The examined prefix at
    that point is what the walk had seen *before* the expansion it declined, and
    a decision point records exactly that as its expansion count — but the
    answer head reads edges, so the cut is the number of edges examined by then.
    An episode that never becomes route-complete has no T* and is given its full
    examined set; `stop_labels` is all zeros there, so it contributes no stop
    positive either, and the runner reports how often that happens.
    """

    cuts: list[int] = []
    for episode, points, total in zip(
        episodes, decisions, examined_counts, strict=True
    ):
        targets = set(episode.hidden["target_nodes"])
        cut = total
        for point in points:
            if targets <= set(point.endpoints):
                cut = point.examined
                break
        cuts.append(min(cut, total))
    return cuts


def stop_loss(
    torch: Any,
    functional: Any,
    logits: Sequence[Any],
    labels: Sequence[Sequence[float]],
) -> Any:
    """Per-episode mean BCE over decision points, then the batch mean.

    The same reduction as `training_v2.masked_edge_loss` and for the same
    reason: an episode that exhausts in three expansions must weigh as much as
    one that takes twenty, or the loss is dominated by the largest trees.
    """

    if len(logits) != len(labels):
        raise TrainingBlocked("stop logits and labels disagree on the batch size")
    per_episode = []
    for row, target in zip(logits, labels, strict=True):
        if len(target) != row.shape[0]:
            raise TrainingBlocked(
                "stop labels and decision points disagree within an episode"
            )
        if not target:
            continue
        goal = torch.tensor(target, dtype=row.dtype, device=row.device)
        per_episode.append(
            functional.binary_cross_entropy_with_logits(row, goal, reduction="mean")
        )
    if not per_episode:
        raise TrainingBlocked("no decision points in the batch")
    return torch.stack(per_episode).mean()
