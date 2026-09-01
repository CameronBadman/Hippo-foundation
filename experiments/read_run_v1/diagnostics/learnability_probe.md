# READ run v1 — learnability probe

**Complete. Both arms ran their full 9,376-update horizon.**

Started 2026-09-01T02:18:35Z. DIRECT finished in 6,673 s at concurrency 2;
TRAV's extended run finished in 26,024 s. Phase 2 of the E1 recovery, run under the rules
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

## TRAV: complete curve and plateau

TRAV's run was restarted once, to extend its horizon from 4,688 to 9,376. The
restart replays the killed run exactly — **1595/1595 update records identical**
on every field, and every shared screening evaluation identical — so the curve
below is one continuous trajectory, not two spliced ones. Its first 1,172
updates are also **bit-identical to E1's own TRAV run** at the same seed and
gamma, as DIRECT's were.

| U | acc% | ΔA | classes | H |
|---|---|---|---|---|
| 1,000 | 7.38 | +7.38 | 16 | 0.552 |
| 1,500 | 76.87 | +69.48 | 16 | 2.767 |
| 2,000 | 75.27 | −1.60 | 16 | 2.746 |
| 2,500 | 79.72 | +4.45 | 16 | 2.764 |
| 3,000 | 79.72 | +0.00 | 16 | 2.761 |
| 3,500 | 82.65 | +2.94 | 16 | 2.769 |
| 4,000 | 82.21 | −0.44 | 16 | 2.767 |
| 4,500 | 83.19 | +0.98 | 16 | 2.768 |
| 5,000 | 88.26 | +5.07 | 16 | 2.769 |
| 5,500 | 91.37 | +3.11 | 16 | 2.763 |
| 6,000 | 96.00 | +4.63 | 16 | 2.743 |
| 6,500 | 98.22 | +2.22 | 16 | 2.741 |
| 7,000 | 99.91 | +1.69 | 16 | 2.712 |
| 7,500 | 99.56 | −0.36 | 16 | 2.724 |
| **8,000** | **100.00** | +0.44 | 15 | 2.707 |
| 8,500 | 99.82 | −0.18 | 15 | 2.707 |
| 9,000 | 100.00 | +0.18 | 15 | 2.707 |
| 9,376 | 100.00 | 0.00 | 15 | 2.707 |

TRAV finishes at **1,124 of 1,124 correct** with answer loss 0.0000.

**The drop from 16 to 15 distinct classes at 8,000 is the perfect value, not a
regression.** Non-abstain episodes in the gated stratum carry gold labels 1–15;
class 0 is ABSTAIN. Emitting 16 meant the model was still wrongly predicting
abstain on some episodes. Emitting exactly 15 means it never does. Both learner
floors (≥8 classes, entropy ≥1.00 nats) pass comfortably.

## Plateau under Amendment 09, both arms

| arm | qualifying checkpoints | final unbroken run | plateau |
|---|---|---|---|
| DIRECT | 7500, 8000, 8500, 9000, 9376 | `[7500, 8000, 8500, 9000, 9376]` | **7,500** |
| TRAV | **4500**, 8000, 8500, 9000, 9376 | `[8000, 8500, 9000, 9376]` | **8,000** |

```
shared update_count = max(7500, 8000) = 8000
```

**The isolated 4,500 is the false positive Amendment 09 exists to discard.** It
satisfies the pairwise test — ΔA +0.9786pp against a 1.00pp threshold, a margin
of 0.0214pp, or 11 correct episodes out of 1,124 where a twelfth would have
prevented it — and the two checkpoints after it gained +5.07pp and +3.11pp. It
is not part of the run reaching the end, so the settled-streak reading drops it.

Under Amendment 05's original first-qualifying rule the answer would have been
**4,500**, and the shared budget would have stayed at 7,500 with TRAV trained to
less than half the point where it actually converged. Same curve, same
underlying test, different reading.

Amendment 09's 3-checkpoint minimum also binds: TRAV's run is exactly four, so a
two-checkpoint run would have been admissible without it — which is the 4,500
fragility in another form.

### Post-saturation behaviour

Neither arm degrades after its plateau. DIRECT runs 86.03 → 86.74 → 87.19 →
87.28 → 87.81; TRAV runs 100.00 → 99.82 → 100.00 → 100.00. The first checkpoint
within 1.00pp of each arm's whole-run maximum is 6,500 for DIRECT and 7,000 for
TRAV, so each selection lands one to two checkpoints past saturation, in the
direction Amendment 05 §2 flagged as the unfavourable one.

## What this does not establish

**No comparison between the arms is a finding here.** Both curves are one model
seed, on screening data, at gamma=0, from a non-preregistered diagnostic. The
probe answers one question — where does each arm stop improving — and that
answer is a single shared number.

TRAV's gamma=0 accuracy accelerated to 100% rather than converging, on the
negative-control condition where adaptive traversal is supposed to confer
nothing. That is the subject of a separate blocking diagnostic
([`trav_edge_selection_g00.md`](trav_edge_selection_g00.md)) and is explicitly
not interpreted here.

## Status of the Amendment 04 rules

- **Left uniform.** DIRECT satisfies criterion (L) and all three §5
  learner-gate conditions from U = 3,500 onward. TRAV satisfies them from
  U = 1,500 onward, so Amendment 06 §2's stop clause cannot fire for either arm.
- **Plateau.** DIRECT **7,500**, TRAV **8,000**, both under Amendment 09 §2
  against complete 9,376-update curves.
- **Budget.** `update_count = max(7500, 8000) = 8000`, recorded in
  `training-config.v2.json` and Amendment 08.

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
