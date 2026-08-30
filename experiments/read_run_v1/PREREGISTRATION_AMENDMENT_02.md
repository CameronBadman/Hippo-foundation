# READ run v1 — Preregistration Amendment 02

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-08-31. Supersedes the schedule in Amendment 01 and reverts
Amendment 01's generator change.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`.

## 1. Why Amendment 01's fix was wrong

Amendment 01 capped `MAX_PATH_LENGTH` at 4 because the stratified diagnostic
identified path length as the dominant cause of DIRECT coverage loss. The
diagnosis was correct. The remedy was not.

Coverage loss at depth is not a confound. At 5–6 hops DIRECT structurally cannot
see the target while TRAV can still reach it. That asymmetry *is* the mechanism
the experiment exists to measure.

Gate 7's 90% threshold was written to stop DIRECT losing on pool construction
rather than on scoring. Applied to this cause it does not de-confound the
comparison — it deletes it. Capping at 4 retains only the range where both arms
have full visibility, which is precisely the range where a gap is least likely to
appear.

The gate's scope was wrong, not its intent.

## 2. Reversion

| Parameter | Amendment 01 | Amendment 02 |
|---|---|---|
| `MAX_PATH_LENGTH` | 4 | **6** (frozen value restored) |

`PREREGISTRATION.md` §6's "valid target-path length 2–6" stands unamended. No
generator constant is changed by this amendment. Amendment 01 §3 remains
not-applicable and its `MAX_NODES = 127` rejection stands: 90.03% with a
one-sided 95% Wilson lower bound of 87.95% is statistically indistinguishable
from a failure.

## 3. Amended gate 7 scope

Gate 7's 90% coverage threshold applies **only to strata where coverage loss
would be a confound on scoring**, and not to strata where coverage loss is the
measured mechanism.

DIRECT target-in-pool coverage is reported per stratum in all cases and is never
aggregated away. The aggregate remains in the report as supplementary context
and carries no gating authority.

### Strata

Episodes are assigned by BFS hop distance from the traversal root to the
**farthest** target node, which is the depth the structural pool must reach for
the set-level indicator to fire. This is deliberately not the planted path
length: background edges create shortcuts, so length-6 routes spread across 2–6
hops.

| Stratum | Role | Gate 7 threshold | §5 decision rules |
|---|---|---|---|
| `hops_2_4` | de-confounded scoring comparison | applies | apply |
| `hops_5` | coverage-limited | reported only | do not apply |
| `hops_6_plus` | coverage-limited | reported only | do not apply |

### The deep stratum is split, not pooled

The plan specified a single 5–6 hop stratum. Measurement shows the two depths are
not the same regime, so they are reported separately:

| Stratum | n | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| 2–4 hops | 1518 | 30.96% | 53.82% | 79.64% | **100.00%** |
| 5 hops | 412 | 0.00% | 0.00% | 0.00% | 26.21% |
| 6 hops | 70 | 0.00% | 0.00% | 0.00% | **0.00%** |

At 6 hops DIRECT has zero visibility at **every** preregistered budget. That cell
is not a coverage-limited curve, it is an empty comparison: DIRECT cannot answer
correctly there under proof-valid scoring at any budget, so any TRAV advantage at
6 hops is entirely a coverage artifact and carries no scoring information.
Pooling it with the 5-hop stratum, where DIRECT retains 26.21% at B=128, would
conceal that. The strata can be re-pooled by any later reader; they cannot be
un-pooled.

### Budget selection

Selection reads the `hops_2_4` stratum. Measured on the 2,000-world screening
domain at gamma=0: 79.64% at B=64 and 100.00% at B=128, so **B=128** is selected
— the same value the aggregate rule would have chosen had it cleared. B is not
increased; 128 was already the largest preregistered candidate.

## 4. Implementation

`direct_pool_invariance_gate` now emits `coverage_by_stratum`,
`episode_count_by_stratum`, and `gated_stratum` alongside the existing aggregate
`coverage`. `select_main_budget` reads the gated stratum and raises if it is
absent or empty, so a pre-amendment report cannot silently satisfy the new rule.

The per-episode gamma-invariance assertions are unchanged and now also hold
within each stratum.

## 5. Reporting rules for E1

Results are reported in two claims, never merged:

- **2–4 hops.** Full coverage for both arms. This is the de-confounded scoring
  comparison and the frozen §5 decision rules apply here.
- **5 hops and 6 hops.** Coverage-and-accuracy curves, explicitly not scoring
  comparisons.

The gamma=0, 2–4 hop cell is the negative control. The arms must agree within 1
percentage point there or the run is void.

That control is load-bearing for a specific risk: both arms train on all path
lengths, so roughly a quarter of DIRECT's training episodes are ones it cannot
answer at any budget. If that unlearnable fraction degrades DIRECT's performance
in the full-coverage stratum, the negative control is what detects it, and a
failure there voids the run rather than being reported as a TRAV advantage.

## 6. Stop conditions

Unchanged from the frozen preregistration, plus:

- If coverage varies with gamma after regeneration, stop. Pool construction is
  query-correlated and that is a correctness bug, not a tuning problem.
- If the 2–4 hop negative control fails at gamma=0, the run is void.
- A null result in the 2–4 hop stratum must not be reported as "adaptive
  traversal does not help". It is scoped to the full-coverage regime and must say
  so.
- A gap in the 5-hop or 6-hop stratum must not be reported as a scoring win. It
  is coverage-limited and must say so.

## 7. Integrity

`training_authorized` in Phase 0, Phase 1, and Phase 2 artifacts remains
mechanically `false` and is unaffected by this amendment; that invariant is
pinned by `tests/test_no_training_surface.py`.

The READ-run P0 report is a separate schema whose purpose is to authorize this
experiment's own sweep. When all seven gates pass it sets `training_authorized`
to `true`, which authorizes E1 only. This was confirmed as the intended
resolution before any training was run.

No holdout episode has been generated and no accuracy has been measured under
this amendment.
