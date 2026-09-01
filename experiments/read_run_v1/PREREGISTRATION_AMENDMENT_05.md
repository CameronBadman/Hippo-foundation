# READ run v1 — Preregistration Amendment 05

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-09-01. Replaces Amendment 04 §4's plateau definition and
translates its stop clause into dev terms. Everything else in Amendment 04
stands, and Amendments 02 and 03 are untouched.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`.

## 0. Disclosure, first and plainly

**This amendment was written after seeing DIRECT's probe curve and before TRAV
produced any curve at all.** That ordering is the whole of its defence and it is
stated at the top rather than buried.

- DIRECT's screening accuracy, gradient norms, and loss through update 5,000 were
  known when this was written. They are recorded in §1 as the evidence.
- TRAV had reached roughly 1,100 of its 4,688 updates and had produced exactly
  four screening checkpoints, three of which are all-zero pre-transition rows. No
  TRAV accuracy plateau, transition point, or final value existed.
- Every rule below is applied **identically to both arms**. Nothing is per-arm,
  per-gamma, or per-seed, and `fairness.arm_specific_hyperparameters_allowed`
  remains `false`.

Writing this now is the least adaptive moment available. Waiting for TRAV's curve
would add data the rule could have been tuned to and would make the same change
strictly more post-hoc, not less. The confirmatory machinery is untouched: the
gamma=0 negative control at 1.00pp, the frozen §5 decision rules, the
three-stratum reporting under Amendment 02, and the Amendment 04 §5 learner-gate
thresholds all stand exactly as committed.

## 1. Why the original proxy was wrong

Amendment 04 §4 defined plateau on **training** `answer_loss`:
`L(U-500) - L(U) < 0.02`. The probe shows that quantity measuring the wrong
thing.

DIRECT, screening `hops_2_4` at gamma=0, n = 1,124:

| U | `L(U)` (train) | ΔL/500 | accuracy (dev) |
|---|---|---|---|
| 3000 | 2.4201 | 0.1157 | 8.54% |
| 3500 | 0.9931 | 1.4270 | 83.36% |
| 4000 | 0.8933 | 0.0998 | 80.16% |
| 4500 | 0.8678 | 0.0254 | 83.90% |
| 5000 | 0.8389 | 0.0289 | 82.65% |

**Held-out accuracy has been flat since update 3,500 while training loss keeps
falling.** That is the signature of a model fitting the training bucket rather
than the task; at 5,000 updates it has seen about 4.3 epochs of 150,000
episodes.

The consequence is not hypothetical. `ΔL/500` is hovering at 0.025–0.029 and
would plausibly cross 0.02 somewhere near 5,500 — placing the shared budget
roughly two thousand updates past the point where dev accuracy stopped
improving. **A clean fire of the original rule would have hidden the problem
rather than surfaced it**, which is why this is not left to see whether the
threshold happens to trip.

### Correction: the overfitting claim is refuted, not merely weakened

**The "flat since 3,500" claim above is wrong.** It was written from DIRECT's
curve through update 5,000 and was corrected once as "weaker than stated"; the
curve through update 7,000 refutes it outright. The correction is recorded here,
where the claim lives.

| U | accuracy | ΔA | `L(U)` | ΔL/500 |
|---|---|---|---|---|
| 3500 | 83.36% | — | 0.9931 | 1.4270 |
| 4000 | 80.16% | −3.20 | 0.8933 | 0.0998 |
| 4500 | 83.90% | +3.74 | 0.8678 | 0.0254 |
| 5000 | 82.65% | −1.25 | 0.8389 | 0.0289 |
| 5500 | 86.48% | +3.83 | 0.8115 | 0.0275 |
| 6000 | 84.96% | −1.51 | 0.7678 | 0.0437 |
| 6500 | 87.54% | +2.58 | 0.6958 | 0.0720 |
| 7000 | 87.63% | +0.09 | 0.6476 | 0.0481 |

Least squares over the post-transition region gives **+1.758pp per 1,000
updates**, and the 3,500-to-6,500 change of +4.27pp is about 2.7 standard errors
at SE = 1.12pp. DIRECT was not overfitting and its dev accuracy was not flat. It
was improving slowly underneath a ±3pp oscillation, and the shape was misread
from too few checkpoints.

**No rule changes, and the instrument change is better supported than before.**
The original argument for moving off training loss was an overfitting story that
did not hold. The argument the data actually supports is sharper, and it is the
one that now stands:

- The training-loss rule was moving **away** from firing. `ΔL/500` runs
  0.0275, 0.0437, 0.0720, 0.0481 across updates 5,500 to 7,000 — the loss is
  falling *faster*, not settling, so a threshold of 0.02 recedes rather than
  approaches.
- The dev rule is one checkpoint from firing. `ΔA` reached +0.09pp at 7,000, so
  a plateau is declared at 7,500 if that interval is also within 1.00pp.

Two instruments pointed at the same arm therefore disagree about whether it is
converging, and they disagree in the direction that decides the budget. That is
the case for defining plateau on the quantity the experiment reports rather than
on a training-side proxy, and it does not depend on any claim about overfitting.

**Recorded against interest:** this section's original evidence was wrong, the
amendment was written on a misreading of eight checkpoints, and the rule it
installed survives on a different argument than the one that motivated it. The
rule was not adjusted to fit the new data.

## 2. Plateau, redefined on dev

Let `A(U)` be proof-valid exact-set accuracy over non-abstain episodes in the
`hops_2_4` stratum at gamma=0, on the **`screen` split**, at evaluated
checkpoint `U`. Checkpoints are every 500 updates.

**An arm has plateaued at `U`** when it has left uniform at `U` and

```
A(U)      - A(U-500)   <= 1.00 pp
A(U-500)  - A(U-1000)  <= 1.00 pp
```

Two consecutive intervals, because a single interval is noise. A negative change
satisfies the condition: the test is on *improvement*, not on absolute movement.

"Leaves uniform" is unchanged from Amendment 04 §4 — criterion (L)
`L(U) <= 2.34` together with the §5 learner gate. Criterion (L) is retained
deliberately: it is a **floor** test asking whether an arm moved off the label
marginal at all, not a convergence test, and training loss is a sound instrument
for that question. Only the convergence test moves to dev.

### The threshold's precision, disclosed

At n = 1,124 and p ≈ 0.83 the binomial standard error is **1.12pp**, and the
standard error of a difference between two checkpoints is about **1.59pp** if
they were independent. A 1.00pp threshold therefore sits at roughly one standard
error, which is why the two-consecutive requirement carries the rule rather than
the threshold value: the probability of noise alone producing a spurious
above-threshold "improvement" twice in a row is small, while a single interval
would trip constantly.

**The direction of the residual error is stated because it is the unfavourable
one.** When noise delays the rule, it selects a *larger* budget — further into
the overfitting regime this amendment exists to avoid. The reported curve must
therefore show both the selected checkpoint and the first checkpoint at which
dev accuracy came within 1.00pp of its running maximum, so a reader can see how
far past dev saturation the selection landed.

## 3. Shared budget

**The E1-v2 budget is the maximum, over the two arms, of each arm's plateau
checkpoint.** One number, applied identically to all 30 runs.

This preserves Amendment 04 §6 exactly: a single fixed `update_count`, no per-run
early stopping, no per-arm schedule, `early_stopping` still `false` in the
configuration. The slower arm sizes the budget, so neither arm is cut off
mid-learning. Amendment 04 §4's horizon rule is unchanged — if the maximum lands
past an arm's probe horizon, that arm's probe is extended and the rule
re-applied, never extrapolated.

The synthesis is worth naming because neither original position was complete. The
recovery plan's preference for stopping on dev was right about the *quantity*;
Amendment 04 §6's fixed shared count was right about *fairness*. A dev-defined
plateau taken as a maximum across arms, applied as one shared number, is both.

## 4. Amendment 04 §4 rule 3, translated

The original clause read: if DIRECT has not plateaued by 9,376, the problem is
not the budget and the recovery stops for redesign. Its **intent** was to catch
an arm that cannot learn the task at any budget. Its letter, under a training-loss
proxy, could instead have stopped a recovery whose success is already
demonstrated — DIRECT reaches 83% exact-set accuracy on the gated stratum.

The intent survives; the instrument changes:

> **Stop for redesign if an arm has not transitioned by its probe horizon** —
> that is, if it remains at or below the Amendment 04 §5 floors of 8 distinct
> predicted classes and 1.00 nats of prediction entropy in the gated stratum at
> gamma=0.

An arm that has transitioned but not yet plateaued triggers Amendment 04 §4's
extension clause, not this stop clause. Those are different failures and are no
longer conflated.

As of this writing the clause is live for TRAV and its outcome is unknown: TRAV
is at roughly 1,100 of 4,688 updates with 16 distinct classes and 0.552 nats of
entropy, below the floor.

## 5. Note carried to E1-v2

The overfit onset visible at updates 3,500–4,000 argues for a budget at dev
saturation rather than past it. **By the §2 accuracy criterion DIRECT's plateau
sits at or near 3,500**, far below the 9,376 its probe horizon allows and far
below where the training-loss rule would have put it.

The shared count will therefore be set by whichever arm is slower, and on present
evidence that is TRAV, which had not transitioned when this was written. E1-v2
must report both arms' full dev curves so that a reader can see where each arm
saturated and how the maximum was reached, and any post-saturation degradation
in the faster arm is reported rather than used to re-select the budget.

## 6. Unchanged

Amendment 04's single-knob restriction to `update_count`, its §5 learner-gate
thresholds and their provenance disclosure, its per-gamma final-loss reporting
requirement, its horizon and extension rules, and its §6 rejection of per-run
early stopping all stand. Amendment 02's stratification and Amendment 03's E2
deferral stand. `training_authorized` in Phase 0, Phase 1, and Phase 2 artifacts
remains mechanically `false`, pinned by `tests/test_no_training_surface.py`.

E1's holdout was opened once under freeze `07d18b39…` and is spent. E1-v2 requires
a new master seed, a full regeneration, a fresh seven-gate P0 report, and a new
code freeze before its holdout is opened once.
