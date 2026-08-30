# READ run v1 — Preregistration Amendment 01

**Status: superseded by Amendment 02. Never approved; never in force.**

Amendment 02 reverts this amendment's `MAX_PATH_LENGTH` change and re-scopes
gate 7 per stratum instead. The generator constant this file amends is back at
its frozen value of 6. This file is retained because its §3 world-size
rejection still stands and because the reasoning that led to the wrong remedy
is part of the record. **Do not apply §4 or §5.**

This file did not exist in the workspace when the amendment was to be filled.
The work item that produced it stated that Amendment 01 was already committed at
this path with a deliberately blank §3; it was not. `git log --all` finds no
such file in any commit on any branch, and the repository has a single branch.
It was therefore authored in this session, and is recorded as pending in keeping
with this repository's pending/approved authority pattern. It carries no
authority until reviewed and approved.

Amendment date: 2026-08-31.

The frozen preregistration is not modified by this file. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact
SHA-256 digests pinned in `read_run/contracts.py`, and `hf-read-run contracts`
passes unchanged.

## 1. Occasion

P0 gate 7 blocked the main sweep. DIRECT target-in-pool coverage did not exceed
the preregistered 90% threshold at any candidate budget at gamma=0, measured
before any training.

The recorded prototype figure was 82.25% at B=128. The committed generator does
not reproduce that figure; the measured governing value is **81.30%**. See
[`diagnostics/coverage_stratified.md`](diagnostics/coverage_stratified.md) for
the three independent reasons this difference was expected rather than
anomalous.

## 2. Evidence

The complete stratified diagnostic is
[`diagnostics/coverage_stratified.md`](diagnostics/coverage_stratified.md),
committed before any generator constant was changed. It reports coverage by
world size, path length, hop distance, coverage level, and gamma, with counts
alongside every rate, over the 2,000-world screening domain.

Two preregistered gates were evaluated on that diagnostic before any fix was
considered, and both passed:

- The blocked figure was already **set-level** — every target node of both valid
  routes pooled — so the governing number did not move down. Node-level coverage
  is 95.80%.
- Coverage is **bit-identical across all five gamma buckets** per episode, not
  merely equal within sampling noise. DIRECT pool construction does not read
  query similarity, so the deficit was a generator-shape problem and not a
  correctness bug in pool construction.

## 3. World-size range — not applicable

**This section cannot be filled as specified, and the reason is itself the
result.** It was to carry a narrowed node-count range on the expectation that
world size drove the coverage deficit. The stratification does not support that
expectation.

World size is a real but shallow gradient: 95.09% down to 72.09% at B=128 across
the full 64–256 range, a spread of 23 points. Path length spans 100% down to
47.16% over the same episodes, a spread of 53 points.

Narrowing world size was additionally rejected as statistically unsafe. The best
qualifying cap is `MAX_NODES = 127`, giving 596/662 = 90.03% at B=128 — clearing
`coverage > 0.9` by four hundredths of a point, with a one-sided 95% Wilson lower
bound of 87.95%. It would satisfy the gate while being statistically
indistinguishable from a failure. This repository already reasons in Wilson
bounds for exactly this class of judgement.

| MAX_NODES cap | Episodes | Coverage at B=128 |
|---|---|---|
| 95 | 326 | 95.09% |
| 111 | 511 | 92.95% |
| 127 | 662 | 90.03% |
| 143 | 808 | 89.23% |
| 159 | 982 | 88.29% |
| 191 | 1296 | 85.65% |
| 223 | 1631 | 83.38% |
| 256 (unchanged) | 2000 | 81.30% |

**The world-size range is unchanged at 64–256 nodes.** `PREREGISTRATION.md` §6
stands as written on this point.

## 4. Amended parameter

The single amended parameter is the valid target-path length.

| Parameter | Frozen value | Amended value |
|---|---|---|
| `MAX_PATH_LENGTH` | 6 | **4** |

`PREREGISTRATION.md` §6 reads "valid target-path length 2–6". Under this
amendment the generator draws **2–4**. `MIN_PATH_LENGTH` (2), `MIN_NODES` and
`MAX_NODES` (64 and 256), `OUT_DEGREE` (3), the relation range, the gamma
buckets, the budget candidates, the split sizes, the model seeds, the arms, the
decision rule, and the 90% threshold are all unchanged.

`MAX_PATH_LENGTH = 5` was measured at 89.52% and rejected as a genuine miss
rather than a rounding question. The amended value is the smallest change that
clears the threshold.

Hop distance from the traversal root is the sharper stratifier — 100% coverage
within 4 hops, 26.21% at 5, 0% at 6 — but the generator exposes no knob that sets
it directly. Of the three candidate knobs, `MAX_PATH_LENGTH` is the only one that
moves it. The third candidate, constraining router-seed placement, has no
referent: `router_seed` is a hex string that orders each node's outgoing edges
and is not a placed node.

## 5. Effect

Measured on the 2,000-world screening domain at gamma=0 after regeneration:

| Budget | Set-level coverage, before | after |
|---|---|---|
| 16 | 23.50% | 39.20% |
| 32 | 40.85% | 62.25% |
| 64 | 60.45% | 83.30% |
| 128 | 81.30% | **100.00%** |

`select_main_budget` returns **128**, the smallest candidate exceeding 90%. The
examined-edge budget is not increased; 128 was already the largest preregistered
candidate. Proof-valid coverage, requiring both valid routes to be fully
decodable from the pool, is also 100.00% at B=128.

## 6. Recorded cost

Capping at 4 removes path lengths 5 and 6. Those are the hardest traversal cases
and precisely where an adaptive-traversal advantage over an equal-budget DIRECT
scorer would most be expected to appear. This amendment buys the preregistered
coverage threshold at some cost to the experiment's power to discriminate
between the arms.

This is recorded, not resolved. A null or weak TRAV-versus-DIRECT result under
this amendment must be interpreted against a generator whose hardest cases were
removed, and must not be reported as evidence that adaptive traversal does not
help.

## 7. Integrity

No model was instantiated, no training step was taken, no holdout episode was
generated, and no accuracy was measured in the work that produced this
amendment. `training_authorized` remains `false`. The frozen preregistration
digests are unchanged. The diagnostic was committed before the generator
constant was changed, and the generator change was committed before this file.
