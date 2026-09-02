# γ-sweep screening report (Amendment 10 §8)

## Status: screening descriptives, single seed, inadmissible as a result

Generated 2026-09-02T08:39:26Z by `scripts/read_run_gamma_sweep_report.py` at commit `0c50d7d`. Reading rule: Amendment 10, committed as `0c50d7d` (2026-09-02T09:38:09+10:00); first γ > 0 learned run started 2026-09-02T00:16:01Z. Screening split only (`private/read-run-v1/p0-rerun/screen-g0X`), B = 128, v1 training configuration with `update_count` varied. Nothing here is a hypothesis verdict: every arm comparison below is a design-phase, one-seed screening number that cannot move Amendment 10 §5–§7. The holdout was not generated, read, or opened.

## 0. Material disclosures found after this reader was written

Two findings from 2026-09-02 are not captured by any threshold or criterion below, and both bear directly on how the curves in §2 and the recommendation in §7 should be read. They are stated here, ahead of the numbers, because a reader who reaches §7 without them will draw a conclusion this evidence does not support. Full analysis is in `docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md` §1.5 and §1.7.

**D-1. The similarity field marks on-path nodes, at every γ.** `generator._assign_similarity` promotes exactly one out-edge to 900,000 at each valid-path state. γ decides only whether the promoted edge is the correct one or a distractor; it never changes whether the node carries a promotion. Verified on all 2,000 episodes of the γ = 0 screening split: the set of nodes with a 900,000 out-edge equals the set of nodes sourcing a path edge in 2,000 of 2,000, mean 4.83 marked nodes out of 161.3 (3.00% of the graph). The similarity channel therefore carries a γ-degraded edge-choice hint **and** a γ-invariant node-localisation marker. TRAV's flatness across γ in §2 is consistent with a policy that navigates by marker presence and discriminates edges by relation, so §2 demonstrates relation-based edge discrimination but does not establish shortcut-free traversal.

**D-2. The flattened-similarity accuracy column in §5 is not a stable measurement.** Flattening removes similarity from the answer head as well as the walk, and the head responds by abstaining. Across the two seeds at γ = 0.4 the flattened exact accuracy reads 14.50% and 30.69%, and at γ = 0 it reads 0.36% and 6.14%, with predicted-abstain rates from 33.63% to 99.47% on checkpoints whose baselines are within half a point of each other. No inference about γ may be drawn from that column. Flattened **route-completeness** is stable — 62.10% and 61.30% at γ = 0.4 across seeds — and is the quantity that isolates the walk. It spans 53.56% to 69.13% across all seven checkpoints with no relation to training γ, and every value is below the 87.90% that DIRECT's query-blind structural pool reaches at the same budget: with similarity removed, every TRAV checkpoint walks worse than not walking adaptively at all.

Neither disclosure changes a threshold, a criterion, or the computed recommendation in §7. Amendment 10 §9's three criteria are mechanically met and are reported as met. The disclosures are the material a human needs in order to decide whether meeting them is sufficient, which is the only kind of authorisation §7 asks for.

## 1. Runs

| run | γ | seed | updates | device | bf16 | complete |
|---|---|---|---|---|---|---|
| TRAV | 0.0 | 1729 | 9376/9376 | cuda | True | yes |
| DIRECT | 0.0 | 1729 | 9376/9376 | cuda | True | yes |
| DIRECT | 0.1 | 1729 | 9376/9376 | cuda | True | yes |
| DIRECT | 0.2 | 1729 | 9376/9376 | cuda | True | yes |
| DIRECT | 0.3 | 1729 | 9376/9376 | cuda | True | yes |
| DIRECT | 0.4 | 1729 | 9376/9376 | cuda | True | yes |
| TRAV | 0.0 | 2718 | 9376/9376 | cuda | True | yes |
| TRAV | 0.1 | 1729 | 9376/9376 | cuda | True | yes |
| TRAV | 0.2 | 1729 | 9376/9376 | cuda | True | yes |
| TRAV | 0.3 | 1729 | 9376/9376 | cuda | True | yes |
| TRAV | 0.4 | 1729 | 9376/9376 | cuda | True | yes |
| TRAV | 0.4 | 2718 | 9376/9376 | cuda | True | yes |

γ = 0 rows are the existing probes (`diagnostics/learnability_probe.md`); `probe-TRAV-checkpoint` and `probe-TRAV-ext` are bitwise-identical logs of the same seed, data and code, which is the determinism check for this harness.

## 2. The curves at the two declared read points (gated `hops_2_4`, non-abstain)

### Update 8,000 (= v2 update_count)

| γ | arm/seed | exact-set acc | Wilson LB | classes | H (nats) | L(U) | (L) | §5 floors | ≥ 99% |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | DIRECT_s1729 | 86.74% | 84.99% | 16 | 2.769 | 0.6101 | pass | pass | no |
| 0.0 | TRAV_s1729 | 100.00% | 99.76% | 15 | 2.707 | 0.0010 | pass | pass | censored |
| 0.0 | TRAV_s2718 | 99.64% | 99.21% | 16 | 2.715 | 0.0308 | pass | pass | censored |
| 0.0 | greedy (no training) | 82.65% | 80.72% | — | — | — | — | — | — |
| 0.1 | DIRECT_s1729 | 82.47% | 80.53% | 16 | 2.767 | 0.8918 | pass | pass | no |
| 0.1 | TRAV_s1729 | 99.56% | 99.09% | 16 | 2.724 | 0.0198 | pass | pass | censored |
| 0.1 | greedy (no training) | 75.36% | 73.18% | — | — | — | — | — | — |
| 0.2 | DIRECT_s1729 | 75.71% | 73.55% | 16 | 2.716 | 1.0224 | pass | pass | no |
| 0.2 | TRAV_s1729 | 99.56% | 99.09% | 16 | 2.721 | 0.0312 | pass | pass | censored |
| 0.2 | greedy (no training) | 68.33% | 66.00% | — | — | — | — | — | — |
| 0.3 | DIRECT_s1729 | 70.20% | 67.91% | 16 | 2.702 | 1.1183 | pass | pass | no |
| 0.3 | TRAV_s1729 | 99.47% | 98.97% | 16 | 2.726 | 0.0332 | pass | pass | censored |
| 0.3 | greedy (no training) | 60.85% | 58.44% | — | — | — | — | — | — |
| 0.4 | DIRECT_s1729 | 62.01% | 59.60% | 16 | 2.602 | 1.2284 | pass | pass | no |
| 0.4 | TRAV_s1729 | 99.64% | 99.21% | 16 | 2.721 | 0.0359 | pass | pass | censored |
| 0.4 | TRAV_s2718 | 99.73% | 99.33% | 16 | 2.718 | 0.0280 | pass | pass | censored |
| 0.4 | greedy (no training) | 58.54% | 56.11% | — | — | — | — | — | — |

### Update 9,376

| γ | arm/seed | exact-set acc | Wilson LB | classes | H (nats) | L(U) | (L) | §5 floors | ≥ 99% |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | DIRECT_s1729 | 87.81% | 86.11% | 16 | 2.769 | 0.6068 | pass | pass | no |
| 0.0 | TRAV_s1729 | 100.00% | 99.76% | 15 | 2.707 | 0.0000 | pass | pass | censored |
| 0.0 | TRAV_s2718 | 100.00% | 99.76% | 15 | 2.707 | 0.0034 | pass | pass | censored |
| 0.0 | greedy (no training) | 82.65% | 80.72% | — | — | — | — | — | — |
| 0.1 | DIRECT_s1729 | 82.56% | 80.62% | 16 | 2.764 | 0.8232 | pass | pass | no |
| 0.1 | TRAV_s1729 | 99.38% | 98.86% | 16 | 2.721 | 0.0166 | pass | pass | censored |
| 0.1 | greedy (no training) | 75.36% | 73.18% | — | — | — | — | — | — |
| 0.2 | DIRECT_s1729 | 75.80% | 73.64% | 16 | 2.731 | 0.9786 | pass | pass | no |
| 0.2 | TRAV_s1729 | 99.47% | 98.97% | 16 | 2.726 | 0.0289 | pass | pass | censored |
| 0.2 | greedy (no training) | 68.33% | 66.00% | — | — | — | — | — | — |
| 0.3 | DIRECT_s1729 | 69.75% | 67.45% | 16 | 2.694 | 1.0842 | pass | pass | no |
| 0.3 | TRAV_s1729 | 99.91% | 99.60% | 15 | 2.707 | 0.0259 | pass | pass | censored |
| 0.3 | greedy (no training) | 60.85% | 58.44% | — | — | — | — | — | — |
| 0.4 | DIRECT_s1729 | 64.06% | 61.67% | 16 | 2.672 | 1.1806 | pass | pass | no |
| 0.4 | TRAV_s1729 | 99.73% | 99.33% | 16 | 2.718 | 0.0253 | pass | pass | censored |
| 0.4 | TRAV_s2718 | 99.56% | 99.09% | 16 | 2.724 | 0.0329 | pass | pass | censored |
| 0.4 | greedy (no training) | 58.54% | 56.11% | — | — | — | — | — | — |

`L(U)` is the mean training `answer_loss` over updates (U−99, U] (Amendment 04 §4); (L) passes at ≤ 2.34 nats. The §5 floors are Wilson LB > 1/15 with acc ≥ 7.67%, ≥ 8 distinct classes, and entropy ≥ 1.00 nats. `≥ 99%` marks Amendment 10 §6 ceiling censoring.

## 3. Coverage per γ (B = 128, gated stratum)

| γ | n | DIRECT pool route-complete | DIRECT pool target-node exposure | greedy route-complete | relation tree ≤ 16 | relation tree ≤ 128 | tree size median / p95 / max |
|---|---|---|---|---|---|---|---|
| 0.0 | 1124 | 87.90% | 100.00% | 82.65% | 100.00% | 100.00% | 5 / 10 / 16 |
| 0.1 | 1124 | 87.90% | 100.00% | 75.36% | 100.00% | 100.00% | 5 / 10 / 16 |
| 0.2 | 1124 | 87.90% | 100.00% | 68.33% | 100.00% | 100.00% | 5 / 10 / 16 |
| 0.3 | 1124 | 87.90% | 100.00% | 60.85% | 100.00% | 100.00% | 5 / 10 / 16 |
| 0.4 | 1124 | 87.90% | 100.00% | 58.54% | 100.00% | 100.00% | 5 / 10 / 16 |

TRAV's own route-completeness per checkpoint is in §5 (it needs the checkpoint).

## 4. Amendment 10 §4 statistics on screening — inadmissible

`lead(γ) = acc_TRAV(γ) − acc_greedy(γ)`; `excess(γ) = lead(γ) − lead(0)`; `excess_DIRECT(γ)` is Amendment 07's DIRECT-comparator quantity, secondary. One seed each, screening split, design phase: **these cannot support or refute the hypothesis** (Amendment 10 §3, §8). A cell marked censored has TRAV ≥ 99% and its `excess` is a lower bound only.

### s1729@8000 — allocation offset lead(0) = +17.35 pp

| γ | TRAV | DIRECT | greedy | lead | excess | TRAV − DIRECT | excess_DIRECT | censored | (L) |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 100.00% | 86.74% | 82.65% | +17.35 pp | +0.00 pp | +13.26 pp | +0.00 pp | yes | pass |
| 0.1 | 99.56% | 82.47% | 75.36% | +24.20 pp | +6.85 pp | +17.08 pp | +3.83 pp | yes | pass |
| 0.2 | 99.56% | 75.71% | 68.33% | +31.23 pp | +13.88 pp | +23.84 pp | +10.59 pp | yes | pass |
| 0.3 | 99.47% | 70.20% | 60.85% | +38.61 pp | +21.26 pp | +29.27 pp | +16.01 pp | yes | pass |
| 0.4 | 99.64% | 62.01% | 58.54% | +41.10 pp | +23.75 pp | +37.63 pp | +24.38 pp | yes | pass |

Outcome-table reading for this seed (an *expectation*, not a verdict): **positive expectation, right-censored** — TRAV ≥ 99% at every γ; the slope cannot be measured on this generator

### s1729@9376 — allocation offset lead(0) = +17.35 pp

| γ | TRAV | DIRECT | greedy | lead | excess | TRAV − DIRECT | excess_DIRECT | censored | (L) |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 100.00% | 87.81% | 82.65% | +17.35 pp | +0.00 pp | +12.19 pp | +0.00 pp | yes | pass |
| 0.1 | 99.38% | 82.56% | 75.36% | +24.02 pp | +6.67 pp | +16.81 pp | +4.63 pp | yes | pass |
| 0.2 | 99.47% | 75.80% | 68.33% | +31.14 pp | +13.79 pp | +23.67 pp | +11.48 pp | yes | pass |
| 0.3 | 99.91% | 69.75% | 60.85% | +39.06 pp | +21.71 pp | +30.16 pp | +17.97 pp | yes | pass |
| 0.4 | 99.73% | 64.06% | 58.54% | +41.19 pp | +23.84 pp | +35.68 pp | +23.49 pp | yes | pass |

Outcome-table reading for this seed (an *expectation*, not a verdict): **positive expectation, right-censored** — TRAV ≥ 99% at every γ; the slope cannot be measured on this generator

### s2718@8000 — allocation offset lead(0) = +16.99 pp

| γ | TRAV | DIRECT | greedy | lead | excess | TRAV − DIRECT | excess_DIRECT | censored | (L) |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 99.64% | — | 82.65% | +16.99 pp | +0.00 pp | — | — | yes | pass |
| 0.4 | 99.73% | — | 58.54% | +41.19 pp | +24.20 pp | — | — | yes | pass |

Outcome-table reading for this seed (an *expectation*, not a verdict): **incomplete** — a γ > 0 TRAV cell is missing

### s2718@9376 — allocation offset lead(0) = +17.35 pp

| γ | TRAV | DIRECT | greedy | lead | excess | TRAV − DIRECT | excess_DIRECT | censored | (L) |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 100.00% | — | 82.65% | +17.35 pp | +0.00 pp | — | — | yes | pass |
| 0.4 | 99.56% | — | 58.54% | +41.01 pp | +23.67 pp | — | — | yes | pass |

Outcome-table reading for this seed (an *expectation*, not a verdict): **incomplete** — a γ > 0 TRAV cell is missing

## 5. Controls and descriptives on the TRAV checkpoints

| γ | seed | baseline acc | matches probe row | route-complete (gated) | shuffled acc | Δ shuffled | verdict | flattened-similarity acc | drop | flattened route-complete | cross-check |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 1729 | 100.00% | yes | 100.00% | 100.00% | +0.00 pp | clean | 0.36% | +99.64 pp | 54.00% | 0 |
| 0.0 | 2718 | 100.00% | yes | 100.00% | 100.00% | +0.00 pp | clean | 6.14% | +93.86 pp | 60.50% | 0 |
| 0.1 | 1729 | 99.38% | yes | 99.56% | 99.38% | +0.00 pp | clean | 34.25% | +65.12 pp | 69.13% | 0 |
| 0.2 | 1729 | 99.47% | yes | 100.00% | 99.47% | +0.00 pp | clean | 19.04% | +80.43 pp | 53.56% | 0 |
| 0.3 | 1729 | 99.91% | yes | 100.00% | 99.91% | +0.00 pp | clean | 11.92% | +87.99 pp | 66.55% | 0 |
| 0.4 | 1729 | 99.73% | yes | 99.91% | 99.73% | +0.00 pp | clean | 14.50% | +85.23 pp | 62.10% | 0 |
| 0.4 | 2718 | 99.56% | yes | 100.00% | 99.56% | +0.00 pp | clean | 30.69% | +68.86 pp | 61.30% | 0 |

Shuffled serialization is Amendment 10 §7.1 on screening (|Δ| < 1 pp clean). The flattened-similarity column repeats Stage C's ablation (`query_similarity_ppm` held at 500,000) and is descriptive. The cross-check column counts route-complete ≠ proof_valid over all three variants of that checkpoint.

### TRAV route-completeness by stratum at 9,376 (baseline variant)

| γ | seed | stratum | n | route-complete | target-node exposure | exact-set acc | predicted-abstain |
|---|---|---|---|---|---|---|---|
| 0.0 | 1729 | hops_2_4 | 1124 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.0 | 1729 | hops_2_4_abstain | 394 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.0 | 1729 | hops_5 | 322 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.0 | 1729 | hops_5_abstain | 90 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.0 | 1729 | hops_6_plus | 54 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.0 | 1729 | hops_6_plus_abstain | 16 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.0 | 2718 | hops_2_4 | 1124 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.0 | 2718 | hops_2_4_abstain | 394 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.0 | 2718 | hops_5 | 322 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.0 | 2718 | hops_5_abstain | 90 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.0 | 2718 | hops_6_plus | 54 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.0 | 2718 | hops_6_plus_abstain | 16 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.1 | 1729 | hops_2_4 | 1124 | 99.56% | 99.73% | 99.38% | 0.36% |
| 0.1 | 1729 | hops_2_4_abstain | 394 | 100.00% | 100.00% | 98.73% | 98.73% |
| 0.1 | 1729 | hops_5 | 322 | 99.38% | 99.69% | 99.38% | 0.31% |
| 0.1 | 1729 | hops_5_abstain | 90 | 98.89% | 100.00% | 97.78% | 98.89% |
| 0.1 | 1729 | hops_6_plus | 54 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.1 | 1729 | hops_6_plus_abstain | 16 | 100.00% | 100.00% | 93.75% | 93.75% |
| 0.2 | 1729 | hops_2_4 | 1124 | 100.00% | 100.00% | 99.47% | 0.53% |
| 0.2 | 1729 | hops_2_4_abstain | 394 | 99.75% | 99.75% | 99.49% | 99.75% |
| 0.2 | 1729 | hops_5 | 322 | 99.07% | 99.69% | 98.45% | 0.93% |
| 0.2 | 1729 | hops_5_abstain | 90 | 100.00% | 100.00% | 97.78% | 97.78% |
| 0.2 | 1729 | hops_6_plus | 54 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.2 | 1729 | hops_6_plus_abstain | 16 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.3 | 1729 | hops_2_4 | 1124 | 100.00% | 100.00% | 99.91% | 0.00% |
| 0.3 | 1729 | hops_2_4_abstain | 394 | 100.00% | 100.00% | 98.73% | 98.73% |
| 0.3 | 1729 | hops_5 | 322 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.3 | 1729 | hops_5_abstain | 90 | 100.00% | 100.00% | 95.56% | 95.56% |
| 0.3 | 1729 | hops_6_plus | 54 | 100.00% | 100.00% | 98.15% | 1.85% |
| 0.3 | 1729 | hops_6_plus_abstain | 16 | 100.00% | 100.00% | 100.00% | 100.00% |
| 0.4 | 1729 | hops_2_4 | 1124 | 99.91% | 100.00% | 99.73% | 0.27% |
| 0.4 | 1729 | hops_2_4_abstain | 394 | 100.00% | 100.00% | 99.24% | 99.24% |
| 0.4 | 1729 | hops_5 | 322 | 99.69% | 100.00% | 98.76% | 0.93% |
| 0.4 | 1729 | hops_5_abstain | 90 | 100.00% | 100.00% | 93.33% | 93.33% |
| 0.4 | 1729 | hops_6_plus | 54 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.4 | 1729 | hops_6_plus_abstain | 16 | 100.00% | 100.00% | 81.25% | 81.25% |
| 0.4 | 2718 | hops_2_4 | 1124 | 100.00% | 100.00% | 99.56% | 0.44% |
| 0.4 | 2718 | hops_2_4_abstain | 394 | 100.00% | 100.00% | 98.73% | 98.73% |
| 0.4 | 2718 | hops_5 | 322 | 100.00% | 100.00% | 98.45% | 1.55% |
| 0.4 | 2718 | hops_5_abstain | 90 | 100.00% | 100.00% | 96.67% | 96.67% |
| 0.4 | 2718 | hops_6_plus | 54 | 100.00% | 100.00% | 100.00% | 0.00% |
| 0.4 | 2718 | hops_6_plus_abstain | 16 | 100.00% | 100.00% | 93.75% | 93.75% |

## 6. Amendment 09 plateau reading per run

| run | γ | seed | qualifying checkpoints | final unbroken run | plateau point |
|---|---|---|---|---|---|
| TRAV | 0.0 | 1729 | 4500, 8000, 8500, 9000, 9376 | 4 | 8000 |
| DIRECT | 0.0 | 1729 | 7500, 8000, 8500, 9000, 9376 | 5 | 7500 |
| DIRECT | 0.1 | 1729 | 7000, 7500, 9000 | 0 | not plateaued |
| DIRECT | 0.2 | 1729 | 5500, 6000 | 0 | not plateaued |
| DIRECT | 0.3 | 1729 | 5500, 9376 | 1 | not plateaued |
| DIRECT | 0.4 | 1729 | 5500, 7000, 7500, 8000, 9376 | 1 | not plateaued |
| TRAV | 0.0 | 2718 | 2500, 4000, 8500, 9000, 9376 | 3 | 8500 |
| TRAV | 0.1 | 1729 | 4000, 7500, 8000, 8500 | 0 | not plateaued |
| TRAV | 0.2 | 1729 | 7000, 7500, 8000, 8500, 9000, 9376 | 6 | 7000 |
| TRAV | 0.3 | 1729 | 6000, 6500, 7000, 7500, 8000, 8500, 9000, 9376 | 8 | 6000 |
| TRAV | 0.4 | 1729 | 7500, 8000, 8500, 9000, 9376 | 5 | 7500 |
| TRAV | 0.4 | 2718 | 3500, 5500, 6000, 6500, 7000, 7500, 8000, 8500, 9000, 9376 | 9 | 5500 |

## 7. Go/no-go for opening Track E (Amendment 10 §9) — recommendation only

- Criterion 1 (both arms clear the §5 floors at 8,000 at every γ): met
- Criterion 2 (cross-check disagreements): 0
- Criterion 3 (Concerning controls): none; greedy strictly decreasing in γ: True

**Recommendation: go.** recommendation only; opening the holdout requires explicit human authorisation.

## 8. Generator-knob grid (E2 preparation; informs nothing above)

Public diagnostic seed `sha256("hf-read-run generator-grid diagnostic seed")`, 2000 attempted episodes per cell, split `test-fixture`, budgets [64, 128, 256] (diagnostic-only: [256]). Frozen values: {'MAX_NODES': 256, 'MAX_PATH_LENGTH': 6, 'OUT_DEGREE': 3} (`deg3_len6_nodes256`).

| config | γ | generation failures | gated n | edges (median) | tree size p95 (gated) | tree ≤ 128 | DIRECT pool rc @64 / @128 / @256 | greedy rc @64 / @128 / @256 |
|---|---|---|---|---|---|---|---|---|
| deg2_len6_nodes256 | 0.0 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg2_len6_nodes256 | 0.4 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg2_len6_nodes512 | 0.0 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg2_len6_nodes512 | 0.4 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg2_len8_nodes256 | 0.0 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg2_len8_nodes256 | 0.4 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg2_len8_nodes512 | 0.0 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg2_len8_nodes512 | 0.4 | 100.00% (valid route state has no greedy distractor ×2000) | 0 | — | — | — | — | — |
| deg3_len6_nodes256 | 0.0 | 0.00% | 1160 | 477 | 10 | 100.00% | 65.60% / 86.98% / 96.81% | 74.14% / 82.33% / 91.21% |
| deg3_len6_nodes256 | 0.4 | 0.00% | 1160 | 477 | 10 | 100.00% | 65.60% / 86.98% / 96.81% | 42.07% / 53.28% / 73.79% |
| deg3_len6_nodes512 | 0.0 | 0.00% | 1061 | 867 | 10 | 100.00% | 69.65% / 91.14% / 97.27% | 75.59% / 80.30% / 86.90% |
| deg3_len6_nodes512 | 0.4 | 0.00% | 1061 | 867 | 10 | 100.00% | 69.65% / 91.14% / 97.27% | 44.30% / 51.27% / 63.62% |
| deg3_len8_nodes256 | 0.0 | 0.00% | 998 | 477 | 14 | 100.00% | 53.81% / 74.05% / 90.48% | 70.24% / 79.76% / 90.08% |
| deg3_len8_nodes256 | 0.4 | 0.00% | 998 | 477 | 14 | 100.00% | 53.81% / 74.05% / 90.48% | 35.57% / 48.20% / 72.44% |
| deg3_len8_nodes512 | 0.0 | 0.00% | 849 | 867 | 13 | 100.00% | 60.90% / 81.86% / 91.17% | 71.73% / 78.09% / 85.51% |
| deg3_len8_nodes512 | 0.4 | 0.00% | 849 | 867 | 13 | 100.00% | 60.90% / 81.86% / 91.17% | 37.57% / 44.99% / 59.48% |
| deg4_len6_nodes256 | 0.0 | 0.00% | 1376 | 636 | 12 | 100.00% | 39.53% / 53.85% / 78.42% | 65.26% / 71.88% / 83.36% |
| deg4_len6_nodes256 | 0.4 | 0.00% | 1376 | 636 | 12 | 100.00% | 39.53% / 53.85% / 78.42% | 31.76% / 38.66% / 54.80% |
| deg4_len6_nodes512 | 0.0 | 0.00% | 1250 | 1156 | 12 | 100.00% | 42.40% / 56.72% / 78.16% | 66.96% / 72.08% / 78.16% |
| deg4_len6_nodes512 | 0.4 | 0.00% | 1250 | 1156 | 12 | 100.00% | 42.40% / 56.72% / 78.16% | 34.56% / 39.12% / 48.16% |
| deg4_len8_nodes256 | 0.0 | 0.00% | 1322 | 636 | 16 | 100.00% | 27.91% / 38.96% / 62.03% | 57.11% / 66.57% / 80.03% |
| deg4_len8_nodes256 | 0.4 | 0.00% | 1322 | 636 | 16 | 100.00% | 27.91% / 38.96% / 62.03% | 23.75% / 30.56% / 46.75% |
| deg4_len8_nodes512 | 0.0 | 0.00% | 1137 | 1156 | 16 | 100.00% | 33.16% / 43.89% / 64.29% | 59.98% / 67.99% / 75.37% |
| deg4_len8_nodes512 | 0.4 | 0.00% | 1137 | 1156 | 16 | 100.00% | 33.16% / 43.89% / 64.29% | 27.09% / 30.96% / 40.90% |
| deg6_len6_nodes256 | 0.0 | 0.00% | 1496 | 954 | 14 | 100.00% | 24.33% / 33.09% / 48.66% | 63.17% / 67.51% / 74.20% |
| deg6_len6_nodes256 | 0.4 | 0.00% | 1496 | 954 | 14 | 100.00% | 24.33% / 33.09% / 48.66% | 26.67% / 31.28% / 39.17% |
| deg6_len6_nodes512 | 0.0 | 0.00% | 1485 | 1734 | 14 | 100.00% | 23.64% / 31.58% / 45.12% | 61.62% / 65.59% / 71.25% |
| deg6_len6_nodes512 | 0.4 | 0.00% | 1485 | 1734 | 14 | 100.00% | 23.64% / 31.58% / 45.12% | 26.13% / 28.69% / 33.87% |
| deg6_len8_nodes256 | 0.0 | 0.00% | 1493 | 954 | 20 | 100.00% | 16.61% / 22.91% / 34.29% | 55.19% / 61.69% / 70.33% |
| deg6_len8_nodes256 | 0.4 | 0.00% | 1493 | 954 | 20 | 100.00% | 16.61% / 22.91% / 34.29% | 19.09% / 22.91% / 31.41% |
| deg6_len8_nodes512 | 0.0 | 0.00% | 1474 | 1734 | 19 | 100.00% | 16.55% / 22.05% / 32.23% | 53.05% / 58.68% / 65.74% |
| deg6_len8_nodes512 | 0.4 | 0.00% | 1474 | 1734 | 19 | 100.00% | 16.55% / 22.05% / 32.23% | 18.25% / 20.35% / 25.03% |

## 9. What this report does not do

It records no hypothesis verdict. It changes no threshold, arm, metric, seed or frozen digest. It reads no holdout. Amendment 10 remains pending review; the go/no-go above is a recommendation to a human, not an authorisation.
