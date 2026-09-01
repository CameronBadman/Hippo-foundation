# READ run v1 — Preregistration Amendment 07

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-09-01. Adds a void taxonomy, a preregistered secondary
statistic, and the stop clause Amendment 06 left undefined. Amendments 02–06
stand.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`.

## 0. Disclosure

Written while TRAV's extended probe is at **183 of 9,376 updates**, having
produced one screening checkpoint — update 100, one predicted class, 0.00%
accuracy, a pre-transition row carrying no information about where TRAV lands.
DIRECT is at 8,366 with its plateau already fixed at 7,500 under Amendment 05.

Nothing below is derived from TRAV's extended curve, because that curve does not
yet exist. Every rule is applied identically to both arms. This is deliberately
the last arm-blind moment available: TRAV's extension began at 03:49:52Z and
accumulates continuously.

## 1. Void taxonomy for the gamma=0 negative control

The frozen rule is unchanged: at gamma=0 the arms must agree within 1.00
percentage point in the `hops_2_4` stratum, and the run is void otherwise. What
changes is that "void" stops being a single undifferentiated outcome.

Classification uses the Amendment 04 §5 three-condition learner gate — one-sided
95% Wilson lower bound above 1/15 with the point estimate at least 1.00pp above
chance, at least 8 distinct predicted classes, and prediction entropy at least
1.00 nats — evaluated for **both arms** on **both** the dev split before the
holdout opens and the holdout's own gamma=0 gated stratum. The same three
conditions, the same thresholds, both arms, both splits.

### Control-void, learner gates failed

At least one arm fails at least one condition. This is E1's case: DIRECT emitted
five distinct classes across 15,000 holdout episodes with 99.94% of mass on class
0, and scored roughly 300× *below* the 1/15 chance level.

**The comparison is uninterpretable and is discarded.** A gap between a learner
and a degenerate constant predictor measures which arm is a learner, not which
arm is better. No gap is reported as a result.

### Control-void, learner gates passed

Both arms clear all three conditions on both splits, and the arms nonetheless
differ by more than 1.00pp at gamma=0.

**This is reported as a substantive finding about the arms, not discarded.** Two
healthy learners separated by a gamma-independent offset is a real observation
about the architectures. It is not the preregistered hypothesis — the hypothesis
is about gamma-dependence — and it must not be reported as confirming it. It is
reported as what it is: an offset present where the task is greedy-solvable and
adaptive traversal should confer no advantage.

#### Candidate mechanism, corrected against the code

The mechanism proposed for this case in review was that TRAV receives roughly 128
supervised decisions per episode against 1 for DIRECT. **That proposal was made
without reading the training loop and it is wrong.** It came from the review, not
from this implementation, and is recorded here with its source because a rejected
claim is only useful if a later reader can see where it came from.

Both arms return `scores` of shape `(batch, B)` and `edge_ids` of length B —
`model.py:182` for `forward_direct`, `model.py:399` for `forward_trav_batched` —
and `training.py:254` applies `binary_cross_entropy_with_logits` across all B for
both. **Each arm receives B = 128 edge-level supervised targets per episode.**
The supervision counts are equal.

The asymmetry is where the gradient can act:

- DIRECT's examined set is `structural_bfs_pool`, which is query-independent and
  fixed. Edge supervision trains **scoring only**; no gradient can change which
  edges are examined.
- TRAV selects its edges sequentially through a recurrent state, so the same 128
  supervisions also shape **which edges are examined**.

A gamma-independent offset between two healthy arms is therefore consistent with
supervision that reaches an adaptive selection policy in one arm and terminates
at a scorer in the other. **This is a candidate mechanism, not a finding.**
Distinguishing it from alternatives requires an experiment designed for the
purpose, and the taxonomy above does not depend on which mechanism is correct.

## 2. Preregistered secondary statistic

Let `gap(γ)` be the seed-mean TRAV-minus-DIRECT proof-valid exact-set accuracy
over non-abstain episodes in `hops_2_4`. Define

```
excess(γ) = gap(γ) − gap(0)
```

`excess(0) = 0` by construction. Reported for γ ∈ {0.1, 0.2, 0.3, 0.4}, with
per-seed values in every cell and never seed means alone.

`excess(γ)` is immune to a uniform offset and is the quantity the path-dependence
hypothesis actually predicts: greedy-wrongness should make traversal matter
*more*, whatever the arms' baseline difference.

**It is strictly secondary and cannot convert a failed control into a positive
claim.** The frozen §5 decision rule continues to operate on `gap(γ)` and is
untouched. A void run stays void; `excess(γ)` is reported as description within
it, never as a substitute finding.

**Its resolution is poor and that is stated in advance.** With three seeds per
arm per cell, `excess(γ)` is a difference of differences over six numbers. It
will not support a significance claim and none will be made for it.

## 3. The stop clause Amendment 06 left undefined

Amendment 06 §2 stops the recovery when an extended arm has not cleared the
learner floors by its ceiling. TRAV cleared all three floors at update 1,500, so
that clause cannot fire for it — and Amendment 06 says nothing about an arm that
has transitioned but never plateaus. The case is reachable and the rule was
undefined in it.

> **An arm that has transitioned but has not plateaued under Amendment 05 §2 by
> its Amendment 06 ceiling stops the recovery for redesign.**

The alternative — taking the ceiling itself as the budget — would select a
training length that no evidence supports, which is precisely how E1 reached a
void holdout. Extending past the ceiling is "extend until it works" and is
already excluded.

**What such a stop means:** the arm converges more slowly than twice the budget
the other arm required. **What it does not mean:** anything about traversal,
about the preregistered hypothesis, or about the arms relative to one another. It
is a statement about the recovery's budget and is reported as one, with both
curves published as they stand.

## 4. Unchanged

The 1.00pp negative-control threshold, the void rule itself, all frozen §5
decision rules, Amendment 02's three-stratum reporting, Amendment 03's E2
deferral, Amendment 04's single-knob restriction and §5 learner-gate thresholds,
Amendment 05's dev-defined plateau and shared-budget maximum, and Amendment 06's
2× extension ceiling all stand exactly as committed.

No per-arm, per-gamma, or per-seed value is introduced.
`fairness.arm_specific_hyperparameters_allowed` remains `false`, and
`training_authorized` in Phase 0, Phase 1, and Phase 2 artifacts remains
mechanically `false` under `tests/test_no_training_surface.py`.

E1's holdout was opened once under freeze `07d18b39…` and is spent.
