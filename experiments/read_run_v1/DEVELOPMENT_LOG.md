# READ run v1 development log

This log records generator and harness observations made before any model was
instantiated and before any accuracy was observed. It is not an experiment
result.

## 2026-08-31 — preregistration freeze

- Committed preregistration v1 and the SHA-256 commitment to a private 32-byte
  seed in commit `e0f5c3d` before creating `read_run` generator code.
- The private preimage remained ignored and mode `0600`.
- Phase 0 v4.4 work stopped without source changes; it remains parked.

## 2026-08-31 — structural generator prototypes

Prototype A used four outgoing edges per node. On 2,000 screening-domain base
worlds, before any model code ran, measured gamma was 0.00000, 0.10051,
0.20158, 0.30133, and 0.39735 for requested gamma 0 through 0.4. DIRECT
all-target coverage at budgets 16, 32, 64, and 128 was respectively 14.15%,
28.80%, 48.50%, and 71.55%. Every per-world pool indicator was identical
across gamma.

This was a failed structural design check: no preregistered budget cleared the
90% selection threshold. No accuracy, loss, prediction, checkpoint, or holdout
value existed.

Prototype B reduced background out-degree to three while retaining two valid
branch actions plus a distractor at every route state. At gamma 0 on the same
2,000 screening-domain indices, coverage was 23.10%, 39.80%, 59.95%, and
82.25%. A separate 200-world all-gamma implementation check again found exact
per-world invariance; its B=128 estimate was 81.0%. Prototype B remains the
implemented candidate because it keeps the required distractor and lowers
storage/compute without reading labels or query similarity during pool
construction. It still does not clear the main-run threshold.

These observations are retained because silently tuning graph density until a
budget passed would undermine the purpose of the coverage control. The
official 2,000-episode P0/Day-3 evidence must be regenerated from committed
code. If it also fails to exceed 90%, the main sweep stops as preregistered.

## 2026-08-31 — implementation checks

- Construction truth and the independent backwards oracle agreed exactly on
  100 early gamma variants and on the focused automated suite.
- Two fresh-process 60-episode generations remained byte-identical after
  perturbing locale, timezone, working directory, and Python hash seed.
- A Python formatter was accidentally pointed at the JSON training config and
  inserted invalid trailing commas. JSON parsing failed immediately. The file
  was restored by explicit patch before any generator, gate, or model run used
  it; its canonical digest matches the code lock.
- No official split, holdout opening, training update, or accuracy measurement
  occurred during these checks.

## 2026-08-31 — runtime smoke check

- A temporary CPU-only runtime instantiated the same model class once per arm
  from the same model seed. Both untrained instances had 10,257,937 trainable
  parameters and the same initial-state digest.
- One synthetic batch completed forward and backward passes for each arm at
  B=16. Every parameter received a gradient. No optimizer step, checkpoint,
  prediction file, screening accuracy, or holdout accuracy was produced.

## 2026-08-31 — reproducibility-evidence binding fix

- An adversarial review found that the first P0 implementation checked a
  double-execution record's split, gamma, and count but did not compare its
  digests with the exact screening root consumed by P0. It also trusted split
  manifest digests without rehashing the compressed streams at consumption.
- The corrected path rehashes both streams and both manifests, requires public
  and private manifest agreement, checks the frozen seed commitment for every
  official root, and requires gate-6 replay digests to equal the consumed
  screening artifacts exactly. A forged replay digest is now rejected by a
  regression test.
- This was caught before an official split, P0 report, model run, or accuracy
  existed. No result was invalidated.

## 2026-08-31 — stratified coverage diagnostic and single-knob generator fix

The full stratified evidence is in
[`diagnostics/coverage_stratified.md`](diagnostics/coverage_stratified.md). This
entry records the change it selected and the consequences of that change. No
model, training step, holdout episode, or accuracy was involved.

### Measured baseline replaces the prototype figure

No prototype episodes were retained, so the screening domain was reconstructed
deterministically from the committed seed and code rather than re-drawn. The
committed generator reproduces this log's earlier 200-world check exactly
(81.00% at B=128) but not its 2,000-world row: measured set-level coverage at
gamma=0 was 23.50%, 40.85%, 60.45%, and 81.30% against the recorded 23.10%,
39.80%, 59.95%, and 82.25%. The 2,000-world row predates a later code change,
which this log already anticipated when it recorded that the official
2,000-episode evidence must be regenerated from committed code. **81.30% is the
governing pre-fix number.**

### Both preregistered gates on the diagnostic passed

The blocked figure was already set-level: the shipped indicator is a subset test
requiring every target node of both valid routes to be pooled. Node-level
coverage is 95.80%. The governing number therefore did not move down.

Coverage is bit-identical across all five gamma buckets per episode, not merely
equal within sampling noise, because pool construction orders edges without
reading `query_similarity_ppm`. Pool construction is not correlated with query
similarity, so the deficit was a generator-shape problem rather than a
correctness bug.

### Path length dominates; world size was rejected

Coverage at B=128 spans 100% to 47.16% across path lengths 2 to 6, against 95.09%
to 72.09% across the 64–256 node range. Hop distance from the traversal root is
sharper still and very nearly deterministic — 100% within 4 hops, 26.21% at 5
hops, 0% at 6 — but the generator exposes no knob that sets it directly, and the
task's third option presupposes router seeds are placed nodes, which they are
not: `router_seed` only orders each node's outgoing edges.

Narrowing world size was rejected on evidence rather than preference. Capping
`MAX_NODES` at 127 yields 596/662 = 90.03% at B=128, clearing `coverage > 0.9` by
four hundredths of a point with a one-sided 95% Wilson lower bound of 87.95%.
That would satisfy the gate while being statistically indistinguishable from a
failure.

### Applied change

`MAX_PATH_LENGTH` 6 → 4, in `read_run/generator.py`. One constant; `MIN_NODES`,
`MAX_NODES`, `MIN_PATH_LENGTH`, `OUT_DEGREE`, and the budget set are unchanged,
and B was not increased. `MAX_PATH_LENGTH = 5` was predicted at 89.52% and is a
genuine miss rather than a rounding question.

Measured after regeneration at gamma=0 on 2,000 screening worlds: 39.20%,
62.25%, 83.30%, and 100.00% set-level. Proof-valid coverage, where both valid
routes are fully decodable from the pool, is also 100.00% at B=128. B=64 reaches
83.30%, so `select_main_budget` still returns 128.

### Known consequence, recorded rather than resolved

Capping at 4 removes path lengths 5 and 6. Those are the hardest traversal cases
and precisely where an adaptive-traversal advantage over an equal-budget DIRECT
scorer would be most expected to appear. The change therefore buys the
preregistered coverage threshold at some cost to the experiment's power to
discriminate between the arms.

This is not treated as grounds for deviating: the 90% coverage rule is
preregistered and the single-knob rule was specified. It is recorded so that a
null or weak TRAV-versus-DIRECT result is interpreted against a generator whose
hardest cases were removed, rather than being read as evidence that adaptive
traversal does not help.

A supplementary observation points the same way: before the fix, proof-valid
coverage (69.55% at B=128) sat well below target-in-pool coverage (81.30%).
Clearing the preregistered target-in-pool gate does not by itself guarantee a
proof-valid answer at the same rate, although after the fix both are 100%.

### Test surface

`test_direct_pool_is_similarity_independent_and_gamma_invariant` asserted that no
preregistered budget cleared 90%, encoding the blocked state as expected
behaviour. It now asserts that selection returns the smallest candidate above the
threshold. The blocked branch retains coverage through a separate test built on a
synthetic below-threshold report, so the raise path is still exercised.

## 2026-08-31 — Amendment 02: gate 7 re-scoped, path-length cap reverted

Amendment 01's cap was reverted. `MAX_PATH_LENGTH` is back at its frozen value
of 6 and no generator constant is amended. The full reasoning is in
[`PREREGISTRATION_AMENDMENT_02.md`](PREREGISTRATION_AMENDMENT_02.md).

### The previous entry's fix was the wrong remedy

The diagnosis in the previous entry was correct — path length dominates coverage
loss — but the remedy was not. Coverage loss at depth is not a confound. At 5–6
hops DIRECT structurally cannot see the target while TRAV can still reach it,
which is the asymmetry the experiment exists to measure. Gate 7's threshold
exists to stop DIRECT losing on pool construction rather than on scoring;
applied to this cause it deletes the comparison instead of de-confounding it.

The previous entry recorded this cost accurately but treated the preregistered
rule as binding on the generator. The rule's scope was the thing to fix.

### Measured strata, at the restored path length range

| Stratum | n | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| 2–4 hops | 1518 | 30.96% | 53.82% | 79.64% | 100.00% |
| 5 hops | 412 | 0.00% | 0.00% | 0.00% | 26.21% |
| 6 hops | 70 | 0.00% | 0.00% | 0.00% | 0.00% |

The de-confounded stratum is exactly 100.00% at B=128 and 79.64% at B=64, so
B=128 is selected — the same value the aggregate rule would have picked had it
cleared. The aggregate over all strata is 81.30%, which is why the unscoped rule
blocked.

The 5-hop and 6-hop strata are reported separately rather than pooled. At 6 hops
DIRECT has zero coverage at every preregistered budget, so that cell is an empty
comparison rather than a coverage-limited curve; pooling it with the 26.21% at
5 hops would conceal that.

### Implementation

`direct_pool_invariance_gate` now emits `coverage_by_stratum`,
`episode_count_by_stratum`, and `gated_stratum` beside the aggregate.
`select_main_budget` reads the gated stratum and raises when it is missing or
empty, so a pre-amendment report cannot satisfy the new rule by accident. Strata
are assigned by BFS hop distance to the farthest target, not by planted path
length, because background edges create shortcuts that put length-6 routes as
close as 2 hops.

Three tests encoded the aggregate contract and were updated: the invariance test
now asserts gamma-invariance within every stratum, and a new test confirms that a
zero-coverage deep stratum neither blocks selection nor folds into the gated
number.

### A generation run was invalidated by operator sequencing

The official-scale P0 run for the capped configuration was still generating when
`MAX_PATH_LENGTH` was reverted. Later buckets in that run would have been drawn
from different code than earlier ones, which would have produced a mixed-config
dataset and tripped the gamma-pairing check. The run was killed and its 1.3 GiB
of partial output deleted rather than repaired.

The cost is one information item: the seven-gate outcome for the capped
configuration was never recorded. That configuration is abandoned, so the loss is
small, but it is recorded here because the sequencing error is the reusable
lesson — generator constants must not be edited while a generation run is in
flight.

### Authorization boundary clarified

The READ-run P0 report sets `training_authorized` to `true` when all seven gates
pass, which authorizes this experiment's sweep only. This is a different schema
from the Phase 0, Phase 1, and Phase 2 artifacts, whose `training_authorized` is
mechanically `false` and remains pinned by `tests/test_no_training_surface.py`.
The two must not be conflated. No holdout has been opened and no accuracy has
been measured.
