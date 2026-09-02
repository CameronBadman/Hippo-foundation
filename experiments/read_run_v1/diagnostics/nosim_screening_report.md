# Track N structural-only screening report

## Status: screening descriptives, three seeds per arm, not a preregistered arm

Generated 2026-09-02T17:21:47Z by `scripts/read_run_nosim_report.py` at commit `841cdf5`. Reading rule: `NOSIM_SCREENING_PREREGISTRATION.md`, committed as `841cdf5bf477` (2026-09-02T20:02:56+10:00); first masked run started 2026-09-02T10:03:21Z. Screening split only (`private/read-run-v1/p0-rerun/screen-g00`, gated `hops_2_4` non-abstain, n = 1124), B = 128, v1 training configuration with `update_count` varied, `query_similarity_ppm` held at 0 at train and eval. Nothing here is a hypothesis verdict; no screening arm comparison is a result. The holdout was not generated, read, or opened.

## 1. Band (preregistration §5), read at 8,000 on TRAV-nosim

**Band D — pool-indistinguishable.** Reading: null — the learned walk does no better than query-blind BFS. Consequence for the graph model: as frozen, this architecture does not learn navigation from structure at this budget; the walker design changes before insert.

Levels per seed (RC@128 at 8,000; oracle ≥ 99.0% = ≥ 1113/1124; null band [85.90%, 89.90%] = counts 966–1010; walker precision RC@32 ≥ 93.93% = ≥ 1056/1124):

| seed | RC@128 | Wilson LB | level | RC@32 | ≥ walker − 5 pp |
|---|---|---|---|---|---|
| 1729 | 972/1124 (86.48%) | 84.71% | null | 717/1124 (63.79%) | False |
| 2718 | 1009/1124 (89.77%) | 88.19% | null | 699/1124 (62.19%) | False |
| 3141 | 1001/1124 (89.06%) | 87.43% | null | 716/1124 (63.70%) | False |

Band G (floors at 8,000, reported beside the letter, never suppressing it): no arm × seed fails a floor.

## 2. Reference rows (preregistration §4; copied from `model_input_audit.json`)

Audit at `4fdd9cc32007`; launch gates: cross_bucket_identity_exact = True, disagreements_zero = True, mask_aucs_in_band = True, pool_prefix_consistent = True, pool_reproduced = True, walker_route_complete_128_gated_fraction = 1.0, walker_route_complete_128_is_100_percent = True; cross-checks: {'pool_prefix_mismatches': 0, 'route_complete_vs_proof_valid_disagreements': 0, 'walker_128_not_prefix_of_full': 0}.

| reference | RC@8 | RC@16 | RC@32 | RC@64 | RC@128 |
|---|---|---|---|---|---|
| relation walker | 335/1124 (29.80%) | 836/1124 (74.38%) | 1112/1124 (98.93%) | 1124/1124 (100.00%) | 1124/1124 (100.00%) |
| DIRECT pool | 136/1124 (12.10%) | 338/1124 (30.07%) | 553/1124 (49.20%) | 784/1124 (69.75%) | 988/1124 (87.90%) |

## 3. Primary table — TRAV-nosim route-completeness per seed

### At update 8,000 (primary)

| seed | complete | RC@8 | RC@16 | RC@32 | RC@64 | RC@128 | RC@128 Wilson LB | exact-set acc | exact given RC | loss (L) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1729 | True | 307/1124 (27.31%) | 544/1124 (48.40%) | 717/1124 (63.79%) | 845/1124 (75.18%) | 972/1124 (86.48%) | 84.71% | 82.56% | 95.47% | 0.798 |
| 2718 | True | 304/1124 (27.05%) | 506/1124 (45.02%) | 699/1124 (62.19%) | 869/1124 (77.31%) | 1009/1124 (89.77%) | 88.19% | 85.14% | 94.85% | 0.788 |
| 3141 | True | 312/1124 (27.76%) | 514/1124 (45.73%) | 716/1124 (63.70%) | 869/1124 (77.31%) | 1001/1124 (89.06%) | 87.43% | 83.99% | 94.31% | 0.753 |

### At update 9,376 (beside; does not change the letter)

| seed | complete | RC@8 | RC@16 | RC@32 | RC@64 | RC@128 | RC@128 Wilson LB | exact-set acc | exact given RC | loss (L) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1729 | True | 324/1124 (28.83%) | 586/1124 (52.14%) | 736/1124 (65.48%) | 857/1124 (76.25%) | 984/1124 (87.54%) | 85.83% | 84.34% | 96.34% | 0.693 |
| 2718 | True | 314/1124 (27.94%) | 550/1124 (48.93%) | 735/1124 (65.39%) | 863/1124 (76.78%) | 1013/1124 (90.12%) | 88.56% | 87.90% | 97.53% | 0.698 |
| 3141 | True | 306/1124 (27.22%) | 514/1124 (45.73%) | 725/1124 (64.50%) | 868/1124 (77.22%) | 993/1124 (88.35%) | 86.68% | 84.79% | 95.97% | 0.675 |

## 4. Route-completeness by path length L at 8,000 (TRAV-nosim per seed, beside the references)

| L | n | walker RC@32 | walker RC@128 | pool RC@32 | pool RC@128 | s1729 RC@32 | s2718 RC@32 | s3141 RC@32 | s1729 RC@128 | s2718 RC@128 | s3141 RC@128 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 300 | 300/300 | 300/300 | 300/300 | 300/300 | 300/300 (100.00%) | 300/300 (100.00%) | 300/300 (100.00%) | 300/300 (100.00%) | 300/300 (100.00%) | 300/300 (100.00%) |
| 3 | 337 | 337/337 | 337/337 | 250/337 | 337/337 | 332/337 (98.52%) | 327/337 (97.03%) | 325/337 (96.44%) | 337/337 (100.00%) | 337/337 (100.00%) | 337/337 (100.00%) |
| 4 | 266 | 266/266 | 266/266 | 3/266 | 266/266 | 80/266 (30.08%) | 71/266 (26.69%) | 87/266 (32.71%) | 229/266 (86.09%) | 259/266 (97.37%) | 253/266 (95.11%) |
| 5 | 118 | 115/118 | 118/118 | 0/118 | 67/118 | 5/118 (4.24%) | 1/118 (0.85%) | 3/118 (2.54%) | 77/118 (65.25%) | 82/118 (69.49%) | 82/118 (69.49%) |
| 6 | 103 | 94/103 | 103/103 | 0/103 | 18/103 | 0/103 (0.00%) | 0/103 (0.00%) | 1/103 (0.97%) | 29/103 (28.16%) | 31/103 (30.10%) | 29/103 (28.16%) |

## 5. Head accuracy and floors (Amendment 04 §5), every arm × seed

DIRECT-nosim has no walk: its examined set is the model-free pool and its RC is the reference 988/1124 (87.90%) by construction (checked at every checkpoint: all match). Its `exact given RC` is the head's localisation against that ceiling.

| arm | seed | update | exact-set acc | Wilson LB | exact given RC | RC@128 | distinct | entropy (nats) | loss (L) | criterion L | floors |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DIRECT | 1729 | 8,000 | 41.28% | 38.89% | 46.96% | 87.90% | 16 | 2.415 | 1.644 | True | pass |
| DIRECT | 1729 | 9,376 | 41.19% | 38.80% | 46.86% | 87.90% | 16 | 2.543 | 1.563 | True | pass |
| DIRECT | 2718 | 8,000 | 42.53% | 40.12% | 48.38% | 87.90% | 16 | 2.497 | 1.647 | True | pass |
| DIRECT | 2718 | 9,376 | 43.06% | 40.65% | 48.99% | 87.90% | 16 | 2.580 | 1.574 | True | pass |
| DIRECT | 3141 | 8,000 | 41.64% | 39.24% | 47.37% | 87.90% | 16 | 2.459 | 1.620 | True | pass |
| DIRECT | 3141 | 9,376 | 41.01% | 38.63% | 46.66% | 87.90% | 16 | 2.618 | 1.538 | True | pass |
| TRAV | 1729 | 8,000 | 82.56% | 80.62% | 95.47% | 86.48% | 16 | 2.748 | 0.798 | True | pass |
| TRAV | 1729 | 9,376 | 84.34% | 82.48% | 96.34% | 87.54% | 16 | 2.766 | 0.693 | True | pass |
| TRAV | 2718 | 8,000 | 85.14% | 83.31% | 94.85% | 89.77% | 16 | 2.756 | 0.788 | True | pass |
| TRAV | 2718 | 9,376 | 87.90% | 86.21% | 97.53% | 90.12% | 16 | 2.771 | 0.698 | True | pass |
| TRAV | 3141 | 8,000 | 83.99% | 82.11% | 94.31% | 89.06% | 16 | 2.750 | 0.753 | True | pass |
| TRAV | 3141 | 9,376 | 84.79% | 82.94% | 95.97% | 88.35% | 16 | 2.769 | 0.675 | True | pass |

Other strata at 8,000 (not gated; descriptive):

| arm | seed | stratum | n | exact-set acc | RC@128 |
|---|---|---|---|---|---|
| DIRECT | 1729 | hops_5 | 322 | 3.42% | 45/322 (13.98%) |
| DIRECT | 1729 | hops_6_plus | 54 | 0.00% | 0/54 (0.00%) |
| DIRECT | 2718 | hops_5 | 322 | 3.11% | 45/322 (13.98%) |
| DIRECT | 2718 | hops_6_plus | 54 | 0.00% | 0/54 (0.00%) |
| DIRECT | 3141 | hops_5 | 322 | 2.80% | 45/322 (13.98%) |
| DIRECT | 3141 | hops_6_plus | 54 | 0.00% | 0/54 (0.00%) |
| TRAV | 1729 | hops_5 | 322 | 28.57% | 116/322 (36.02%) |
| TRAV | 1729 | hops_6_plus | 54 | 7.41% | 5/54 (9.26%) |
| TRAV | 2718 | hops_5 | 322 | 28.26% | 117/322 (36.34%) |
| TRAV | 2718 | hops_6_plus | 54 | 9.26% | 5/54 (9.26%) |
| TRAV | 3141 | hops_5 | 322 | 27.64% | 115/322 (35.71%) |
| TRAV | 3141 | hops_6_plus | 54 | 1.85% | 1/54 (1.85%) |

## 6. Controls (preregistration §9)

- Order (§3): preregistration commit `841cdf5bf477` at 2026-09-02T20:02:56+10:00; all runs match and start after it: **True**.
  - probe-DIRECT-nosim-s1729: git_head `841cdf5bf477` (match True), started 2026-09-02T10:06:26+00:00 (210 s after the commit)
  - probe-DIRECT-nosim-s2718: git_head `841cdf5bf477` (match True), started 2026-09-02T10:07:26+00:00 (270 s after the commit)
  - probe-DIRECT-nosim-s3141: git_head `841cdf5bf477` (match True), started 2026-09-02T10:08:26+00:00 (330 s after the commit)
  - probe-TRAV-nosim-s1729: git_head `841cdf5bf477` (match True), started 2026-09-02T10:03:26+00:00 (30 s after the commit)
  - probe-TRAV-nosim-s2718: git_head `841cdf5bf477` (match True), started 2026-09-02T10:04:25+00:00 (89 s after the commit)
  - probe-TRAV-nosim-s3141: git_head `841cdf5bf477` (match True), started 2026-09-02T10:05:26+00:00 (150 s after the commit)
- Scoring code identical to the preregistration commit over 6 paths: **True**
- Prefix-property tests at `841cdf5bf477`: **passed** — `3 passed in 1.14s`
- Audit cross-checks: {'pool_prefix_mismatches': 0, 'route_complete_vs_proof_valid_disagreements': 0, 'walker_128_not_prefix_of_full': 0}

| TRAV seed | identity differing episodes | baseline = probe final row | RC ≠ proof_valid (per variant) | shuffled Δ exact | shuffled Δ RC@128 | shuffled control |
|---|---|---|---|---|---|---|
| TRAV_s1729 | 0 | True | {'baseline': 0, 'flattened_similarity': 0, 'shuffled_serialization': 0} | -0.09 pp | -0.09 pp | clean |
| TRAV_s2718 | 0 | True | {'baseline': 0, 'flattened_similarity': 0, 'shuffled_serialization': 0} | -0.09 pp | -0.09 pp | clean |
| TRAV_s3141 | 0 | True | {'baseline': 0, 'flattened_similarity': 0, 'shuffled_serialization': 0} | -0.09 pp | +0.00 pp | clean |

No harness defect: the §9 controls all hold.

### TRAV-nosim checkpoint (9,376) by stratum, baseline variant

| seed | stratum | n | RC@128 | exact-set acc | predicted-abstain |
|---|---|---|---|---|---|
| TRAV_s1729 | hops_2_4 | 1124 | 87.54% | 84.34% | 8.90% |
| TRAV_s1729 | hops_2_4_abstain | 394 | 86.80% | 80.96% | 91.62% |
| TRAV_s1729 | hops_5 | 322 | 40.37% | 35.71% | 39.75% |
| TRAV_s1729 | hops_5_abstain | 90 | 32.22% | 26.67% | 75.56% |
| TRAV_s1729 | hops_6_plus | 54 | 9.26% | 9.26% | 62.96% |
| TRAV_s1729 | hops_6_plus_abstain | 16 | 12.50% | 12.50% | 75.00% |
| TRAV_s2718 | hops_2_4 | 1124 | 90.12% | 87.90% | 6.76% |
| TRAV_s2718 | hops_2_4_abstain | 394 | 87.56% | 81.73% | 90.86% |
| TRAV_s2718 | hops_5 | 322 | 37.89% | 29.81% | 41.61% |
| TRAV_s2718 | hops_5_abstain | 90 | 33.33% | 21.11% | 67.78% |
| TRAV_s2718 | hops_6_plus | 54 | 7.41% | 7.41% | 61.11% |
| TRAV_s2718 | hops_6_plus_abstain | 16 | 0.00% | 0.00% | 81.25% |
| TRAV_s3141 | hops_2_4 | 1124 | 88.35% | 84.79% | 7.92% |
| TRAV_s3141 | hops_2_4_abstain | 394 | 88.32% | 80.71% | 89.09% |
| TRAV_s3141 | hops_5 | 322 | 40.68% | 34.47% | 35.09% |
| TRAV_s3141 | hops_5_abstain | 90 | 38.89% | 30.00% | 64.44% |
| TRAV_s3141 | hops_6_plus | 54 | 12.96% | 11.11% | 55.56% |
| TRAV_s3141 | hops_6_plus_abstain | 16 | 25.00% | 18.75% | 56.25% |

## 7. Amendment 09 plateau reading per run (no automatic extension)

| run | seed | quantity | qualifying checkpoints | final unbroken run | plateau point |
|---|---|---|---|---|---|
| DIRECT | 1729 | exact_set_accuracy | 8000, 9376 | 1 | not plateaued |
| DIRECT | 2718 | exact_set_accuracy | 5500, 6000, 6500 | 0 | not plateaued |
| DIRECT | 3141 | exact_set_accuracy | 6000, 6500, 9376 | 1 | not plateaued |
| TRAV | 1729 | exact_set_accuracy | 8000 | 0 | not plateaued |
| TRAV | 1729 | rc128 | 1500, 2000, 2500, 6000, 8500 | 0 | not plateaued |
| TRAV | 1729 | rc32 | 7500, 9000 | 0 | not plateaued |
| TRAV | 2718 | exact_set_accuracy | — | 0 | not plateaued |
| TRAV | 2718 | rc128 | 2500 | 0 | not plateaued |
| TRAV | 2718 | rc32 | 6500, 9376 | 1 | not plateaued |
| TRAV | 3141 | exact_set_accuracy | — | 0 | not plateaued |
| TRAV | 3141 | rc128 | 1500, 3000, 7000 | 0 | not plateaued |
| TRAV | 3141 | rc32 | 1500, 7500, 9000, 9376 | 2 | not plateaued |

## 8. Learning curves, TRAV-nosim (gated; RC@128 / RC@32 / exact-set accuracy per checkpoint)

| update | s1729 | s2718 | s3141 |
|---|---|---|---|
| 100 | 88.35% / 49.47% / 0.00% | 88.70% / 49.29% / 0.00% | 88.35% / 49.47% / 0.00% |
| 250 | 88.61% / 49.56% / 0.00% | 89.06% / 48.93% / 0.00% | 88.88% / 49.38% / 0.00% |
| 500 | 87.01% / 45.28% / 0.00% | 89.15% / 47.86% / 0.00% | 88.52% / 48.67% / 0.00% |
| 1,000 | 66.99% / 25.18% / 4.98% | 60.77% / 22.42% / 2.14% | 71.62% / 30.52% / 4.18% |
| 1,500 | 66.81% / 33.72% / 53.11% | 66.19% / 30.78% / 48.22% | 64.50% / 23.40% / 46.09% |
| 2,000 | 67.53% / 35.94% / 56.67% | 67.17% / 34.34% / 50.98% | 67.44% / 33.99% / 53.91% |
| 2,500 | 65.66% / 37.81% / 56.49% | 66.64% / 33.01% / 57.03% | 66.64% / 40.48% / 55.78% |
| 3,000 | 73.84% / 46.17% / 67.62% | 73.75% / 42.26% / 66.46% | 66.81% / 41.19% / 59.34% |
| 3,500 | 76.16% / 49.20% / 71.35% | 73.58% / 44.75% / 68.06% | 74.47% / 46.80% / 68.86% |
| 4,000 | 79.27% / 50.09% / 73.75% | 77.76% / 54.63% / 73.31% | 77.94% / 48.58% / 72.51% |
| 4,500 | 81.41% / 53.38% / 77.49% | 78.65% / 50.36% / 74.29% | 78.65% / 51.33% / 74.64% |
| 5,000 | 82.56% / 56.67% / 77.49% | 81.32% / 52.05% / 77.14% | 81.94% / 53.65% / 77.94% |
| 5,500 | 82.56% / 59.70% / 79.00% | 82.65% / 57.12% / 79.18% | 84.07% / 56.85% / 79.80% |
| 6,000 | 82.83% / 55.96% / 78.47% | 84.79% / 57.38% / 80.52% | 85.41% / 57.74% / 80.96% |
| 6,500 | 83.99% / 62.54% / 81.32% | 84.70% / 57.12% / 79.54% | 85.94% / 62.19% / 82.12% |
| 7,000 | 85.68% / 62.72% / 82.56% | 86.30% / 60.68% / 81.94% | 85.94% / 61.30% / 81.76% |
| 7,500 | 86.74% / 62.54% / 83.27% | 87.10% / 63.17% / 82.74% | 87.37% / 61.57% / 82.83% |
| 8,000 | 86.48% / 63.79% / 82.56% | 89.77% / 62.19% / 85.14% | 89.06% / 63.70% / 83.99% |
| 8,500 | 87.37% / 64.59% / 84.52% | 89.68% / 64.23% / 85.77% | 88.08% / 63.35% / 83.99% |
| 9,000 | 89.59% / 63.43% / 86.21% | 91.28% / 64.95% / 87.28% | 89.15% / 64.06% / 85.14% |
| 9,376 | 87.54% / 65.48% / 84.34% | 90.12% / 65.39% / 87.90% | 88.35% / 64.50% / 84.79% |

DIRECT-nosim exact-set accuracy per checkpoint (RC fixed at the pool):

| update | s1729 | s2718 | s3141 |
|---|---|---|---|
| 100 | 0.00% | 0.00% | 0.00% |
| 250 | 0.00% | 0.00% | 0.00% |
| 500 | 0.00% | 0.00% | 0.00% |
| 1,000 | 0.00% | 0.00% | 0.44% |
| 1,500 | 0.00% | 0.00% | 0.00% |
| 2,000 | 0.00% | 0.00% | 0.00% |
| 2,500 | 0.09% | 0.00% | 0.09% |
| 3,000 | 27.94% | 29.00% | 30.69% |
| 3,500 | 40.84% | 38.97% | 39.32% |
| 4,000 | 41.90% | 41.01% | 40.93% |
| 4,500 | 40.84% | 42.17% | 39.86% |
| 5,000 | 42.44% | 42.17% | 41.99% |
| 5,500 | 40.04% | 41.99% | 41.99% |
| 6,000 | 44.04% | 40.93% | 42.17% |
| 6,500 | 40.66% | 39.32% | 39.15% |
| 7,000 | 43.42% | 41.90% | 41.55% |
| 7,500 | 40.48% | 38.97% | 40.12% |
| 8,000 | 41.28% | 42.53% | 41.64% |
| 8,500 | 44.31% | 44.93% | 44.75% |
| 9,000 | 43.42% | 40.57% | 41.73% |
| 9,376 | 41.19% | 43.06% | 41.01% |

## 9. Contrast: the same seeds with similarity (γ sweep; descriptive only)

From `experiments/read_run_v1/diagnostics/gamma_sweep_curves.json` (report commit `0c50d7d`): γ = 0.0 runs with `query_similarity_ppm` present. Same generator, same seeds where they exist, different input; a screening-vs-screening contrast, not an arm comparison.

| run | exact @8,000 | exact @9,376 | ckpt RC@128 (baseline) | ckpt RC@128 (flattened 500,000) | ckpt exact (flattened) |
|---|---|---|---|---|---|
| TRAV_s1729 | 100.00% | 100.00% | 100.00% | 54.00% | 0.36% |
| DIRECT_s1729 | 86.74% | 87.81% | — | — | — |
| TRAV_s2718 | 99.64% | 100.00% | 100.00% | 60.50% | 6.14% |

## 10. What this report does not do

It records no hypothesis verdict. It changes no threshold, arm, metric, seed or frozen digest; the band is read from §5 of the preregistration as written, at 8,000 only. It reads no holdout. Amendment 10 remains pending review. Whether to extend, add seeds, or change the generator is the user's call and is not recommended by any number above.
