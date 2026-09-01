# READ run v1 — learnability probe

**DIRECT is complete. TRAV's extended run is in progress; its sections are
updated on completion.**

Started 2026-09-01T02:18:35Z. DIRECT finished its 9,376-update horizon in
6,673 s at concurrency 2. Phase 2 of the E1 recovery, run under the rules
fixed in [`../PREREGISTRATION_AMENDMENT_04.md`](../PREREGISTRATION_AMENDMENT_04.md)
§4 and §5, which were committed before the probe launched.

Diagnostic, not preregistered. `scripts/read_run_learning_probe.py` emits no
training receipt, no code-freeze binding and no gate evidence, scores only
against the `screen` split, and touches no holdout. Both arms run on the
existing `p0-rerun` train buckets at gamma=0, model seed 1729, B=128.

## The probe replays E1's official run exactly

The probe reuses `training.py`'s loop components rather than reimplementing
them, and the retained E1 logs make that checkable rather than merely asserted.
For DIRECT at seed 1729, gamma=0:

| | probe | E1 |
|---|---|---|
| update 1 `answer_loss` | 2.772827 | 2.772827 |
| `L(1172)` | 2.5583 | 2.5583 |
| exactly equal updates in the first 1,172 | **1,172 / 1,172** | |

Every update matches bit for bit. The probe is not an approximation of the
official runner: it is that runner's trajectory, continued past the update count
E1 stopped at. Any curve below is therefore E1's own DIRECT arm, not a
differently configured script that happens to resemble it.

## DIRECT leaves uniform between updates 2,500 and 3,000

`L(U)` is the mean `answer_loss` over the window `(U-99, U]`. Accuracy is
proof-valid exact-set accuracy over non-abstain episodes in the `hops_2_4`
stratum, n = 1,124. Chance is 1/15 = 6.67%.

| U | `L(U)` | ΔL/500 | grad | acc% | Wilson LB% | classes | H |
|---|---|---|---|---|---|---|---|
| 500 | 2.5909 | — | 0.418 | 0.00 | 0.000 | 1 | 0.000 |
| 1000 | 2.5731 | 0.0179 | 0.573 | 0.44 | 0.217 | 4 | 0.163 |
| **1172** | **2.5583** | | | | | | | 
| 1500 | 2.5561 | 0.0170 | 0.604 | 0.09 | 0.020 | 4 | 0.057 |
| 2000 | 2.5409 | 0.0152 | 0.656 | 0.00 | 0.000 | 4 | 0.033 |
| 2500 | 2.5357 | 0.0051 | 0.685 | 0.09 | 0.020 | 5 | 0.029 |
| 3000 | 2.4201 | 0.1157 | 1.068 | 8.54 | 7.267 | 14 | 0.844 |
| 3500 | 0.9931 | 1.4270 | 2.802 | 83.36 | 81.456 | 16 | 2.764 |
| 4000 | 0.8933 | 0.0998 | 2.695 | 80.16 | 78.132 | 16 | 2.738 |
| 4500 | 0.8678 | 0.0254 | 2.664 | 83.90 | 82.012 | 16 | 2.765 |

The row at 1,172 is where E1 stopped. It is in the flat region, 1,300 updates
before anything happens and 2,300 before the transition completes.

For 2,500 updates DIRECT sits on the label marginal of 2.5934 emitting one to
five of sixteen classes. Then in 500 updates the loss falls 1.43 nats, the
gradient norm nearly triples, accuracy goes from 0.09% to 83.36%, and the
predicted-label distribution opens from five classes at 0.029 nats to all
sixteen at 2.764.

**This is the direct confirmation that E1 was undertrained, and it cost no
holdout to obtain.** DIRECT is not a weak arm and never was. E1's recorded
28.49pp gap measured which arm was further along a curve that neither had begun
to climb.

### The deep strata reproduce the structural prediction

DIRECT at U = 4,500, other strata, same checkpoint:

| Stratum | n | accuracy | DIRECT target-in-pool coverage (Amendment 02) |
|---|---|---|---|
| `hops_2_4` | 1,124 | 83.90% | 100.00% |
| `hops_5` | 322 | 13.98% | 26.21% |
| `hops_6_plus` | 54 | **0.00%** | **0.00%** |

Accuracy tracks coverage: roughly half of what it can see at 5 hops, and exactly
nothing where the structural pool cannot reach the target at any budget. The
coverage figures were measured before any accuracy existed and are bound into
`audit/read-run-p0.v1.passed.json`, so this is a prediction confirmed rather
than a fit.

## DIRECT: complete curve and plateau

| U | `L(U)` | acc% | Wilson LB% | classes | H | ΔA | plateau |
|---|---|---|---|---|---|---|---|
| 2500 | 2.5357 | 0.09 | 0.020 | 5 | 0.029 | +0.09 | |
| 3000 | 2.4201 | 8.54 | 7.267 | 14 | 0.844 | +8.45 | |
| 3500 | 0.9931 | 83.36 | 81.456 | 16 | 2.764 | +74.82 | |
| 4000 | 0.8933 | 80.16 | 78.132 | 16 | 2.738 | −3.20 | |
| 4500 | 0.8678 | 83.90 | 82.012 | 16 | 2.765 | +3.74 | |
| 5000 | 0.8389 | 82.65 | 80.716 | 16 | 2.751 | −1.25 | |
| 5500 | 0.8115 | 86.48 | 84.711 | 16 | 2.771 | +3.83 | |
| 6000 | 0.7678 | 84.96 | 83.127 | 16 | 2.765 | −1.51 | |
| 6500 | 0.6958 | 87.54 | 85.834 | 16 | 2.770 | +2.58 | |
| 7000 | 0.6476 | 87.63 | 85.927 | 16 | 2.771 | +0.09 | |
| **7500** | 0.6115 | 86.03 | 84.245 | 16 | 2.771 | −1.60 | **YES** |
| 8000 | 0.6101 | 86.74 | 84.992 | 16 | 2.769 | +0.71 | yes |
| 8500 | 0.6078 | 87.19 | 85.459 | 16 | 2.772 | +0.44 | yes |
| 9000 | 0.6126 | 87.28 | 85.553 | 16 | 2.771 | +0.09 | yes |
| 9376 | 0.6068 | 87.81 | 86.115 | 16 | 2.769 | | |

**Plateau checkpoint under Amendment 05 §2: 7,500.** The first checkpoint to
satisfy the rule, and every later checkpoint satisfies it too, so the selection
is not a single noisy crossing.

### Post-saturation behaviour, as Amendment 05 §2 requires reporting

The run's maximum accuracy is **87.81%**, its final value. The first checkpoint
within 1.00pp of that maximum is **6,500**, so the selected budget landed **one
checkpoint past saturation**.

Post-plateau accuracy runs 86.03, 86.74, 87.19, 87.28, 87.81. **There is no
degradation** — the arm was still improving slightly at its horizon. The
overfitting risk that motivated the dev-plateau rule did not materialise for this
arm, and Amendment 05 records that correction against itself.

### The two instruments differ by one checkpoint

Applied retrospectively to the same curve, Amendment 04's training-loss rule
(`L(U−500) − L(U) < 0.02`) first fires at **8,000**: `ΔL/500` runs 0.0720,
0.0481, 0.0362, then 0.0013 at 8,000. The dev rule fires at 7,500.

The instrument change therefore selected the earlier and cheaper budget, but by
500 updates rather than the two thousand Amendment 05 §1 anticipated. Recorded
because it is evidence against the strength of that section's original argument,
not for it.

## Status of the Amendment 04 rules

- **Left uniform.** DIRECT satisfies criterion (L) and all three §5
  learner-gate conditions from U = 3,500 onward. TRAV satisfies them from
  U = 1,500 onward, so Amendment 06 §2's stop clause cannot fire for either arm.
- **Plateau.** DIRECT: **7,500**, confirmed against its complete curve. TRAV:
  pending its extended run.
- **Budget.** None selected yet. Amendment 05 §3 takes the **maximum** over arms,
  so the shared count is `max(7500, plateau_TRAV)`.

### The §4 escalation clause is likely to be needed

DIRECT's probe runs to 9,376 updates and TRAV's to 4,688. If DIRECT plateaus
past 4,688 — which its current trajectory suggests — §4 forbids selecting a
budget there, because TRAV would have no measurement at that point. The rule
then requires extending TRAV's probe to at least DIRECT's plateau checkpoint and
re-applying the selection, rather than extrapolating TRAV's curve.

## What this does not establish

Nothing here compares the arms. TRAV has not left uniform, this is a single seed
at a single gamma on screening data, and no result on this page may be reported
as an E1 finding. E1 remains void and its holdout remains spent.
