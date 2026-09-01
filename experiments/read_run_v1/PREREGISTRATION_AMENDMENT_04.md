# READ run v1 — Preregistration Amendment 04

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-09-01. Written **before** the learnability probe runs, so
that every rule it states is fixed ahead of the curve it will be applied to.
Amendments 02 and 03 stand unchanged; Amendment 01 remains superseded.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`.

## 1. What this amendment is for

E1 is void. Its negative control failed by 28.49pp against a 1.00pp threshold and
no comparison between the arms is reportable. The recorded cause is that
`update_count = 1172` — a single epoch over one 150,000-episode bucket — cut both
arms off before either had learned anything beyond the label marginal.

The evidence is in the retained per-update logs, which cost nothing to read.
Means over the first 100 and the last 100 updates, averaged across all fifteen
runs of each arm:

| Arm | `answer_loss` first → last | `gradient_norm` first → last |
|---|---|---|
| DIRECT | 2.6093 → 2.5639 | 0.5991 → 0.5830 |
| TRAV | 2.6097 → 2.3135 | 0.6291 → **1.6683** |

Two reference points make the table legible. Uniform prediction over 16 classes
is `ln(16) = 2.7726` nats, and the very first logged update is 2.7728 for DIRECT
and 2.7733 for TRAV — the arms start exactly at uniform, as they should. **The
label marginal is 2.5934 nats**: exactly 25% ABSTAIN and 5% for each of the
fifteen assertion masks, verified empirically over 15,000 holdout episodes rather
than assumed from the preregistration.

DIRECT's 2.5639 is the label marginal and nothing past it — across all fifteen
runs it lands between 2.5556 and 2.5799. It had learned the label frequencies and
no function of its input. TRAV had begun to move, but its gradient norm nearly
tripled over training and was still rising at the final update, which is not a
converged model.

This amendment changes one knob, `update_count`, and states in advance every rule
by which its value will be chosen and every condition an arm must satisfy before
a new holdout is opened.

## 2. The process lesson

The root cause of the void is not the update budget. **It is that the Day-3
screening sweep the frozen design always required was skipped.**

`PREREGISTRATION.md` §5 and §8 specify sixteen screening runs — both arms ×
gamma {0, 0.4} × B {16, 32, 64, 128} — on Day 3, before the main sweep. Those runs
evaluate on the `screen` split and touch no holdout. Every symptom that voided E1
would have been visible in them: a DIRECT arm emitting one class, an accuracy two
orders of magnitude below chance, an answer loss sitting on the label marginal.

The sweep exists precisely to catch this before a holdout is spent, and it was
not run. Recorded plainly here because it is the reusable finding: the frozen
schedule's cheap step was the one that mattered, and skipping it converted a
recoverable configuration error into a spent holdout and a void experiment.

## 3. The single changed knob

| Parameter | v1 | v2 |
|---|---|---|
| `training.update_count` | 1172 | determined by §4, identical for all 30 runs |

Everything else is unchanged and is restated so that the claim is checkable:
optimizer `adamw`, learning rate `0.0003`, weight decay `0.01`, gradient clip
norm `1.0`, microbatch size `16`, gradient accumulation `8`, effective batch
`128`, `answer_loss_weight` `1.0`, `edge_loss_weight` `0.25`, `early_stopping`
`false`, `mixed_precision` `bf16_if_supported_else_fp32`,
`deterministic_algorithms` `true`, every `model` field, every `fairness` field,
and every `selection` field. Arms, model seeds {1729, 2718, 3141}, gamma buckets,
budget candidates, metrics, strata, and all §5 decision thresholds are unchanged.

`fairness.arm_specific_hyperparameters_allowed` remains `false` and this
amendment does not weaken it. No value anywhere below is chosen per arm, per
gamma, or per seed.

### Version-additive implementation

Per the repository's frozen-contract convention, v1 is not edited.
`experiments/read_run_v1/training-config.v2.json` is a new file and
`read_run/contracts.py` gains a v2 path alongside the v1 digests, which stay
pinned and reproducible.

**The v2 config is deliberately not created yet.** Its only new value is
`update_count`, and that number is an output of the Phase 2 probe read through
§4's rule. Creating the file now would mean inventing the number this amendment
exists to constrain. The ordering — rule committed, then probe run, then number
recorded — is the point, and it is auditable in the git history.

## 4. Reading rule for the probe curve

Applied to the diagnostic learnability probe. The probe replicates the v1
training loop exactly and varies only `update_count`; it writes to
`private/read-run-v1/diagnostics/`, emits no training receipt and no gate
evidence, and touches no holdout.

Let `L(U)` be the mean training `answer_loss` over updates in the window
`(U-99, U]`.

**An arm leaves uniform at U** when both hold:

- **(L)** `L(U) <= 2.34` nats. The anchors are fixed, not fitted: uniform is
  2.7726 and the label marginal is 2.5934. The line sits 0.25 nats below the
  label marginal, far enough that a model which has learned only the label
  frequencies cannot cross it on logging noise. For calibration against E1, whose
  runs all ended at `U = 1172`: **no DIRECT run of the fifteen reaches 2.34**,
  and their `L(1172)` values span only 2.5556 to 2.5799 — glued to the label
  marginal across every seed and gamma. Eight of the fifteen TRAV runs are at or
  below 2.34, spanning 1.8705 to 2.5372. The line separates an arm that had
  started moving from one that had not, and neither arm's noise can cross it.
- **(A)** The arm passes the §5 learner gate on the `screen` split.

**An arm has plateaued at U** when it has left uniform at U *and*
`L(U-500) - L(U) < 0.02` nats — improvement over the preceding 500 updates has
fallen below 0.02 nats.

**The E1-v2 budget** is the smallest multiple of 100 at which **both** arms have
plateaued, read from the probe curves and applied identically to all 30 runs.

If either arm has not plateaued by the end of its probe run, no budget is
selected, and the recovery stops for redesign rather than extrapolating the curve.

## 5. Learner gate

Three conditions, all evaluated on the **`screen` split**, in the `hops_2_4`
stratum, at **gamma = 0**, over non-abstain episodes, separately for each arm.
Sixteen output classes exist; class 0 is ABSTAIN; chance on non-abstain episodes
is 1/15 = 6.67%.

1. **Above chance.** Exact-set accuracy `p̂` whose one-sided 95% Wilson lower
   bound is strictly greater than 1/15, **and** `p̂ >= 7.67%` — chance plus a
   1.00pp absolute margin. The margin is the resolution scale the frozen
   preregistration already uses for its negative control, carried over rather than
   invented; it stops the Wilson rule from being satisfiable by a hair at large n.
   The screening cell is exactly **1,124 episodes** — 2,000 per gamma bucket, 75%
   non-abstain by construction, of which 1,124 fall in `hops_2_4` (322 at
   `hops_5`, 54 at `hops_6_plus`). At that n the Wilson condition requires 89
   correct, `p̂ = 7.92%`, so it binds first here and the absolute margin binds
   only at larger n.
2. **Distinct classes.** At least **8** distinct predicted classes.
3. **Entropy floor.** Shannon entropy of the empirical predicted-label
   distribution at least **1.00 nats** — an effective support of `e^1.00 ≈ 2.72`
   of 16 classes.

Conditions 2 and 3 are a floor on non-degeneracy, not on quality. A model that
spreads its predictions over three classes clears the entropy floor; a constant
predictor cannot. Condition 1 alone is insufficient, which is the whole reason
the other two exist: E1's DIRECT emitted five distinct classes across 15,000
holdout episodes with 99.94% of mass on class 0, and a near-degenerate model can
scrape past a bare above-chance test without having learned a function of its
input.

### Where the gate applies

- **Phase 3 screening sweep.** Both arms must pass at gamma=0 and the selected
  budget. Failure blocks E1-v2 entirely.
- **Phase 5, before the holdout opens.** Re-evaluated on dev. Failure blocks the
  opening.
- **Never after the fact.** It is a precondition for spending a holdout, not a
  filter applied to holdout results. No run is excluded from reporting because it
  failed the gate; a failure stops the experiment and is reported as the result.

### Provenance of the thresholds, stated against interest

The distinct-class and entropy numbers were **calibrated against E1's holdout
predictions**, which is disclosed here rather than left to be discovered. The
observed signature was: DIRECT never above 5 distinct classes and never above
0.0676 nats across all fifteen runs, emitting exactly one class in three of them;
TRAV emitting all 16 classes in every run, with gamma=0 entropies of 1.618,
1.756 and 1.902.

Four things bound what that calibration can have bought:

- The thresholds are **identical for both arms** and for every gamma and seed.
  Nothing here is a per-arm choice, which is what this recovery forbids.
- They are **degeneracy floors, not performance thresholds**. Raising them would
  make the gate stricter for both arms symmetrically; it cannot advantage either.
- The run they were read from is **void**, and its holdout is spent. E1-v2 draws a
  new master seed, so none of those episodes recurs.
- The gate is applied **on dev, before** the new holdout opens, so no holdout
  result can be reached by it.

The residual risk is stated rather than dismissed: E1-v2 resamples from the same
generator, so a threshold calibrated on E1's distribution is not fully
independent of prior observation. The mitigation is that both floors are set
where they exclude a constant predictor rather than where any observed arm
happened to land — 1.00 nats is roughly 15× E1's worst DIRECT value and well
below its best TRAV value, and TRAV itself would have **failed** the entropy
floor at gamma=0.2, where it collapsed to 0.2735 nats. A threshold that fails the
arm it was calibrated against is not one tuned to let that arm through.

## 6. Stopping criterion for E1-v2

The recovery plan expressed a preference for early stopping on dev. **It is not
adopted, and the reason is recorded here as that plan requires.**

Per-run early stopping produces a different step count for each of the 30 runs.
That contradicts two commitments this experiment already holds: that both arms
receive identical data, schedule, optimizer, steps and budget, and
`training-config`'s `fairness.arm_specific_hyperparameters_allowed: false`. It
also introduces thirty independent stopping decisions taken on dev — thirty model
selections — which is a new adaptation surface, and adopting it would mean
amending `early_stopping` and the fairness block as well, which is more than the
single-knob change §3 authorizes.

**E1-v2 uses a fixed `update_count`, identical across all 30 runs, selected once
from the probe by §4.** The preference's substance is preserved in how the number
is chosen: it is the smallest count at which the **slower** arm has plateaued, so
neither arm is cut off mid-learning, which is exactly the failure that voided E1.

The cost is stated: the faster arm trains past its own plateau. That cost is
symmetric — it is the same schedule applied to both arms — whereas undertraining
is asymmetric, because the arms differ in supervision density and would be cut
off at different points on their curves. Both arms' full dev curves are reported
so a reader can see whether the faster arm degraded after its plateau, and if it
did, that observation is reported rather than used to re-select the budget.

## 7. Unchanged

Amendment 02's per-stratum gate 7 scope and three-stratum reporting rule,
Amendment 03's withdrawal of the aggregator check and of E2-as-size-generalization
and its depth-6 structural ceiling, the frozen §5 decision rules on `hops_2_4`,
the gamma=0 negative control at a 1.00pp threshold, and the four-way decision rule
all stand unchanged.

`training_authorized` in Phase 0, Phase 1, and Phase 2 artifacts remains
mechanically `false`, pinned by `tests/test_no_training_surface.py`, and is
unaffected by this amendment.

E1's holdout was opened once under freeze `07d18b39…` and is spent. It is not
reused at any budget. E1-v2 requires a new master seed, a full regeneration, a
fresh seven-gate P0 report, and a new code freeze before its holdout is opened
once.
