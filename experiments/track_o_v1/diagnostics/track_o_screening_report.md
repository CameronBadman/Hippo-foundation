# Track O screening report — path-scoped traversal v2

## Status: screening, three seeds per arm, not a preregistered arm

Generated 2026-09-03T08:01:33Z by `scripts/read_run_track_o_report.py` at `5eb9399`. Reading rule: `experiments/track_o_v1/SCREENING_PREREGISTRATION.md`, committed as `e5511596a704` (2026-09-03T07:47:05+10:00). Band read at update 8,000 on `deg6_len8_v4_rep`, gated `hops_2_4` non-abstain, B = 64, γ = 0.4. No holdout was generated, read, or opened.

## 1. Band

**Band A — learned and dominant.** training adds capability beyond the architecture and beats every model-free policy on both axes.

Each seed is compared against **its own untrained line**, because the architecture carries the strongest model-free policy's frontier restriction and stop rule structurally. The model-free frontier is beside it, not instead of it.

| seed | RC untrained → trained | Wilson LB | precision untrained → trained | examined | RC improved | precision degraded | clears frontier |
|---|---|---|---|---|---|---|---|
| 1729 | 82.67 % → **93.41 %** (+10.74 pp) | 92.15 % | 0.166 → **0.192** (+0.026) | 37.8 → 32.7 | True | False | True |
| 2718 | 84.95 % → **93.33 %** (+8.38 pp) | 92.06 % | 0.165 → **0.192** (+0.027) | 38.3 → 32.7 | True | False | True |
| 3141 | 89.42 % → **93.73 %** (+4.31 pp) | 92.50 % | 0.172 → **0.193** (+0.021) | 37.1 → 32.7 | True | False | True |

## 2. Model-free references (measured before any training run)

| policy | route-complete | precision | examined |
|---|---|---|---|
| hybrid | 86.27 % | 0.093 | 60.0 |
| stop aware | 86.19 % | 0.173 | 37.4 |
| blind walker | 78.27 % | 0.158 | 39.7 |
| greedy similarity | 22.05 % | 0.044 | 64.0 |

Oracle floor feasible on 98.14 % of these episodes.

## 3. Every run at the read point

| arm | cell | seed | complete | RC | precision | examined | exact acc | distinct | entropy | floors | stop reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRAVV1 | deg3_len6_v8 | 1729 | True | 80.14 % | 0.073 | 64.0 | 58.54 % | 16 | 2.64 | pass | {'budget_cap': 1148} |
| TRAVV1 | deg3_len6_v8 | 2718 | True | 78.22 % | 0.071 | 64.0 | 61.41 % | 16 | 2.71 | pass | {'budget_cap': 1148} |
| TRAVV1 | deg3_len6_v8 | 3141 | True | 82.14 % | 0.073 | 64.0 | 61.85 % | 16 | 2.68 | pass | {'budget_cap': 1148} |
| TRAVV1 | deg6_len8_v4_rep | 1729 | True | 16.19 % | 0.038 | 64.0 | 6.18 % | 16 | 2.60 | FAIL (above_chance) | {'budget_cap': 1229} |
| TRAVV1 | deg6_len8_v4_rep | 2718 | True | 14.73 % | 0.039 | 64.0 | 5.61 % | 16 | 2.64 | FAIL (above_chance) | {'budget_cap': 1229} |
| TRAVV1 | deg6_len8_v4_rep | 3141 | True | 15.38 % | 0.038 | 64.0 | 5.13 % | 16 | 2.35 | FAIL (above_chance) | {'budget_cap': 1229} |
| TRAVV2 | deg3_len6_v8 | 1729 | True | 100.00 % | 0.420 | 13.2 | 99.56 % | 16 | 2.71 | pass | {'targets_reached': 1148} |
| TRAVV2 | deg3_len6_v8 | 2718 | True | 100.00 % | 0.421 | 13.2 | 100.00 % | 15 | 2.71 | pass | {'targets_reached': 1148} |
| TRAVV2 | deg3_len6_v8 | 3141 | True | 100.00 % | 0.421 | 13.1 | 99.13 % | 15 | 2.71 | pass | {'targets_reached': 1148} |
| TRAVV2 | deg6_len8_v4_rep | 1729 | True | 93.41 % | 0.192 | 32.7 | 90.48 % | 16 | 2.76 | pass | {'budget_cap': 99, 'targets_reached': 1130} |
| TRAVV2 | deg6_len8_v4_rep | 2718 | True | 93.33 % | 0.192 | 32.7 | 91.13 % | 16 | 2.76 | pass | {'budget_cap': 98, 'targets_reached': 1131} |
| TRAVV2 | deg6_len8_v4_rep | 3141 | True | 93.73 % | 0.193 | 32.7 | 90.64 % | 16 | 2.75 | pass | {'budget_cap': 96, 'targets_reached': 1133} |

**Band G (Amendment 04 §5 floors on exact accuracy):** **G — TRAVV1-deg6_len8_v4_rep-s1729, TRAVV1-deg6_len8_v4_rep-s2718, TRAVV1-deg6_len8_v4_rep-s3141**. Reported beside the letter; neither suppresses the other.

## 4. Order of evidence

- All runs descend from the preregistration commit and post-date it: **True**
  - probe-TRAVV1-deg3_len6_v8-s1729: `5eb93999df69` descends True, started 2026-09-03T04:07:07+00:00 after True
  - probe-TRAVV1-deg3_len6_v8-s2718: `5eb93999df69` descends True, started 2026-09-03T04:08:07+00:00 after True
  - probe-TRAVV1-deg3_len6_v8-s3141: `5eb93999df69` descends True, started 2026-09-03T04:09:07+00:00 after True
  - probe-TRAVV1-deg6_len8_v4_rep-s1729: `5eb93999df69` descends True, started 2026-09-03T04:04:07+00:00 after True
  - probe-TRAVV1-deg6_len8_v4_rep-s2718: `5eb93999df69` descends True, started 2026-09-03T04:05:07+00:00 after True
  - probe-TRAVV1-deg6_len8_v4_rep-s3141: `5eb93999df69` descends True, started 2026-09-03T04:06:07+00:00 after True
  - probe-TRAVV2-deg3_len6_v8-s1729: `3d6cf59adc75` descends True, started 2026-09-02T22:02:02+00:00 after True
  - probe-TRAVV2-deg3_len6_v8-s2718: `3d6cf59adc75` descends True, started 2026-09-02T22:03:02+00:00 after True
  - probe-TRAVV2-deg3_len6_v8-s3141: `3e9e82191ccf` descends True, started 2026-09-02T22:04:02+00:00 after True
  - probe-TRAVV2-deg6_len8_v4_rep-s1729: `3d6cf59adc75` descends True, started 2026-09-02T21:59:02+00:00 after True
  - probe-TRAVV2-deg6_len8_v4_rep-s2718: `3d6cf59adc75` descends True, started 2026-09-02T22:00:02+00:00 after True
  - probe-TRAVV2-deg6_len8_v4_rep-s3141: `3d6cf59adc75` descends True, started 2026-09-02T22:01:02+00:00 after True
- Generator audit cross-checks: {'deg6_len8_v4_rep': {'reached_outside_targets': 0, 'route_complete_vs_proof_valid_disagreements': 0}, 'deg3_len6_v8': {'reached_outside_targets': 0, 'route_complete_vs_proof_valid_disagreements': 0}}

## 5. Plateau reading (Amendment 09 §2; no automatic extension)

| arm | cell | seed | quantity | final unbroken run | plateau point |
|---|---|---|---|---|---|
| TRAVV1 | deg3_len6_v8 | 1729 | exact_set_accuracy | 1 | not plateaued |
| TRAVV1 | deg3_len6_v8 | 1729 | route_complete_fraction | 0 | not plateaued |
| TRAVV1 | deg3_len6_v8 | 1729 | precision_mean | 13 | 2000 |
| TRAVV1 | deg3_len6_v8 | 2718 | exact_set_accuracy | 0 | not plateaued |
| TRAVV1 | deg3_len6_v8 | 2718 | route_complete_fraction | 0 | not plateaued |
| TRAVV1 | deg3_len6_v8 | 2718 | precision_mean | 13 | 2000 |
| TRAVV1 | deg3_len6_v8 | 3141 | exact_set_accuracy | 0 | not plateaued |
| TRAVV1 | deg3_len6_v8 | 3141 | route_complete_fraction | 0 | not plateaued |
| TRAVV1 | deg3_len6_v8 | 3141 | precision_mean | 13 | 2000 |
| TRAVV1 | deg6_len8_v4_rep | 1729 | exact_set_accuracy | 3 | 7000 |
| TRAVV1 | deg6_len8_v4_rep | 1729 | route_complete_fraction | 3 | 7000 |
| TRAVV1 | deg6_len8_v4_rep | 1729 | precision_mean | 16 | 500 |
| TRAVV1 | deg6_len8_v4_rep | 2718 | exact_set_accuracy | 0 | not plateaued |
| TRAVV1 | deg6_len8_v4_rep | 2718 | route_complete_fraction | 0 | not plateaued |
| TRAVV1 | deg6_len8_v4_rep | 2718 | precision_mean | 16 | 500 |
| TRAVV1 | deg6_len8_v4_rep | 3141 | exact_set_accuracy | 5 | 6000 |
| TRAVV1 | deg6_len8_v4_rep | 3141 | route_complete_fraction | 1 | not plateaued |
| TRAVV1 | deg6_len8_v4_rep | 3141 | precision_mean | 16 | 500 |
| TRAVV2 | deg3_len6_v8 | 1729 | exact_set_accuracy | 6 | 5500 |
| TRAVV2 | deg3_len6_v8 | 1729 | route_complete_fraction | 16 | 500 |
| TRAVV2 | deg3_len6_v8 | 1729 | precision_mean | 16 | 500 |
| TRAVV2 | deg3_len6_v8 | 2718 | exact_set_accuracy | 0 | not plateaued |
| TRAVV2 | deg3_len6_v8 | 2718 | route_complete_fraction | 16 | 500 |
| TRAVV2 | deg3_len6_v8 | 2718 | precision_mean | 16 | 500 |
| TRAVV2 | deg3_len6_v8 | 3141 | exact_set_accuracy | 3 | 7000 |
| TRAVV2 | deg3_len6_v8 | 3141 | route_complete_fraction | 16 | 500 |
| TRAVV2 | deg3_len6_v8 | 3141 | precision_mean | 16 | 500 |
| TRAVV2 | deg6_len8_v4_rep | 1729 | exact_set_accuracy | 0 | not plateaued |
| TRAVV2 | deg6_len8_v4_rep | 1729 | route_complete_fraction | 16 | 500 |
| TRAVV2 | deg6_len8_v4_rep | 1729 | precision_mean | 16 | 500 |
| TRAVV2 | deg6_len8_v4_rep | 2718 | exact_set_accuracy | 0 | not plateaued |
| TRAVV2 | deg6_len8_v4_rep | 2718 | route_complete_fraction | 16 | 500 |
| TRAVV2 | deg6_len8_v4_rep | 2718 | precision_mean | 16 | 500 |
| TRAVV2 | deg6_len8_v4_rep | 3141 | exact_set_accuracy | 2 | not plateaued |
| TRAVV2 | deg6_len8_v4_rep | 3141 | route_complete_fraction | 9 | 4000 |
| TRAVV2 | deg6_len8_v4_rep | 3141 | precision_mean | 16 | 500 |

## 6. The returned set — what the walk asserts is relevant

Examined-set precision is a **cost**: reaching a node examines all of its out-edges, so even a perfect selector pays ~30 edges for ~6 on-route ones on the hard cell, capping examined precision near 0.20. What a write operation adjudicates is the **returned** set. The edge head is already a relevance classifier — its loss is BCE against route membership — so the returned set is read at a **positive logit**, the loss's own boundary, with no threshold fitted to any result. Declared as a descriptive in design notes §2.17 before any run reached its read point.

| cell | seed | examined | returned | examined precision | returned precision | returned recall | average precision |
|---|---|---|---|---|---|---|---|
| `deg3_len6_v8` | 1729 | 13.2 | **5.2** | 0.379 | **0.963** | 0.960 | 0.994 |
| `deg3_len6_v8` | 2718 | 13.2 | **5.3** | 0.384 | **0.960** | 0.970 | 0.995 |
| `deg3_len6_v8` | 3141 | 13.1 | **5.3** | 0.388 | **0.956** | 0.979 | 0.994 |
| `deg6_len8_v4_rep` | 1729 | 32.7 | **5.9** | 0.160 | **0.893** | 0.881 | 0.931 |
| `deg6_len8_v4_rep` | 2718 | 32.7 | **5.9** | 0.160 | **0.892** | 0.885 | 0.933 |
| `deg6_len8_v4_rep` | 3141 | 32.7 | **5.6** | 0.156 | **0.909** | 0.860 | 0.935 |

The traversal reports about six edges from the thirty-three it examined, at roughly nine-tenths precision and recall. Average precision is computed over the whole precision-recall curve, so it commits to no operating point at all.

## 7. Stated limitations of this reading

- **Exact accuracy is largely a restatement of route-completeness** (design notes §2.20). `exact_correct` requires `proof_valid`, which requires the emitted routes to be valid routes whose endpoints are exactly the targets — so on a proof-valid episode the endpoint assertion masks the head reads are the gold answer by construction. Read the `acc / RC` column, not raw accuracy.
- **The answer head trained on the wrong input for half the run** (§2.19). Under supplied-prefix supervision the walk skips the frontier block, so `endpoints` and `routes` are empty and the head's twelve label-carrying dimensions are identically zero. Its effective budget was 4,000 updates, not 8,000.
- **One generator, screening only, no holdout.** The band is evidence about this task at this budget, not about graph memory generally.
- **The architecture carries much of the base performance.** An untrained TRAVV2 is already near the strongest model-free policy, because the frontier restriction and stop rule are structural. Training adds roughly eight points of route-completeness on top of that, which is what the paired comparison measures.

## 8. What this report does not do

It records no hypothesis verdict. It changes no threshold, arm, metric, seed or frozen digest; the band is read from §5 of the preregistration as written, at update 8,000 only. It reads no holdout. Amendment 10 remains pending review. Whether this advances the programme to the insert objective is the user's decision against the standing branch rule in `docs/DECISIONS.md`.
