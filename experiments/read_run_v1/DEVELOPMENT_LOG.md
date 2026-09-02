# READ run v1 development log

This log records generator and harness observations made before any model was
instantiated and before any accuracy was observed. It is not an experiment
result.

## 2026-09-02 — the γ sweep read; the capability splits in two; a structural-only run is next

The twelve Amendment 10 §8 screening runs completed (9,376 updates each, cuda,
bf16; one seed per cell plus a second seed at γ ∈ {0, 0.4}) and were read by
`scripts/read_run_gamma_sweep_report.py` at commit `0c50d7d`, the commit that
carries the reading rule; the first γ > 0 run started after it. Report:
[`diagnostics/gamma_sweep_screening_report.md`](diagnostics/gamma_sweep_screening_report.md),
curves in [`diagnostics/gamma_sweep_curves.json`](diagnostics/gamma_sweep_curves.json).
Screening splits only, single seed in most cells: inadmissible as a hypothesis
result, and no arm comparison in it is a result.

### What the curves say

At update 8,000 on the gated `hops_2_4` non-abstain stratum (n = 1,124), TRAV
holds 99.47–100.00% exact-set accuracy at every γ — right-censored above the
99% line — while DIRECT falls from 86.74% (γ = 0) to 62.01% (γ = 0.4) and the
model-free similarity-greedy walker from 82.65% to 58.54%. Both arms clear the
Amendment 04 §5 floors at every γ; shuffled-serialization Δ is +0.00pp on all
seven TRAV checkpoints; route-completeness equals `proof_valid` with 0
disagreements over every checkpoint and variant. Amendment 10 §9's three
criteria are mechanically met and the script's recommendation reads "go", which
is a recommendation to a human and authorises nothing.

### Two disclosures, and the reading they force

**D-1.** `generator._assign_similarity` promotes exactly one out-edge to
900,000 at every valid-path state; γ decides whether that edge is the correct
one or a distractor, never whether the node carries a promotion. On all 2,000
γ = 0 screening episodes the set of nodes with a 900,000 out-edge equals the set
of nodes sourcing a path edge (mean 4.83 marked nodes of 161.3). The similarity
field is therefore a γ-invariant on-path marker as well as a γ-degraded edge
hint, and TRAV's flatness across γ is consistent with navigating by the marker
and discriminating edges by relation.

**D-2.** Re-scoring each TRAV checkpoint with `query_similarity_ppm` held at
500,000 (Stage C's ablation) gives exact-set accuracies of 0.36–34.25% that are
unstable across seeds because the answer head abstains (33.63–99.47%
predicted-abstain); that column supports no inference. Route-completeness under
the same flattening is stable across seeds (62.10% and 61.30% at γ = 0.4) and
reads **53.56–69.13%** across all seven checkpoints, with no relation to
training γ — every value below the **87.90%** that DIRECT's query-blind
structural pool reaches at the same budget.

So the capability the sweep measured splits in two. **Edge discrimination** was
learned: with similarity present, TRAV picks relation-matching edges on marked
nodes at every γ while greedy and DIRECT degrade. **Navigation** — finding the
route from structure when nothing marks the on-path nodes — was not
demonstrated: with the marker removed, every checkpoint walks worse than not
walking adaptively at all. Navigation is the load-bearing half for a memory
system, because no real graph carries the marker, and it has never been tested
on this generator: every TRAV trained so far had the shortcut available from
update 0. Full analysis in
[`../../docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md`](../../docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md)
§1.5 and §1.7.

### The next run: structural-only screening on the frozen data

The fair test needs no generator change, no new contract and no holdout: the
same frozen model class, training configuration and v1 γ = 0 buckets, trained
from scratch with `query_similarity_ppm` held at a constant at train and eval.
The constant is 0, which zeroes the gradient of that input column and is
equivalent to removing the feature while keeping the trainable parameter count;
`model.py` reads the field on one line and no node id, edge id, position, depth
or hop count enters any tensor. Under the mask the five γ buckets are
byte-identical for the same `(split, index)` — the projection is
`gates._structural_projection`, P0 gate 7's own γ-invariance check — so γ is
inert and only `train-g00`/`screen-g00` are used. Three seeds per arm,
route-completeness at B = 128 and at prefix budgets as the primary quantity,
read against DIRECT's pool (87.90% at B = 128) and a relation-following walker
under an outcome table written before any masked run exists. It is a screening
ablation, not a preregistered arm; Amendment 10 stays pending review.

### Housekeeping

The canonical suite at `0c50d7d` ran 280 passed, 1 failed in 460 s. The failure
was `test_deterministic_publication_and_unknown_outcome_recovery` in the Phase 0
v4.3 publication tests: its fixture carried a literal authorization window
(`authorized_at` 2026-08-30, `valid_until` 2026-09-02) and a literal destination
observation that `publish_artifact` checks against the wall clock, so the test
expired on its own. The fixture's time chain is now anchored on the clock with
the same relative offsets, in a separate `test(phase0)` commit that touches
only the test file. Unrelated to READ code. The two regenerable per-episode row
files under `private/` from the generator grid and the ceiling sweep (81 MB)
were deleted after confirming no script reads them; the aggregates they fed are
committed.

## 2026-09-02 — Amendment 10 drafted; the relation-prefix ceiling measured

Recorded before any learned run at γ>0 exists. The reading rule for the γ
sweep is committed first; the runs it will be read from start after this commit.

### The γ-immune ceiling is 16 edges

`coverage.relation_prefix_tree` returns every edge on a path from the start
whose relations match a prefix of the query — the set a walker that follows
relations alone, with no lookahead and no similarity, must examine to be
route-complete with certainty. On the gated `hops_2_4` stratum it holds **3 to
16 edges** (median 5, p95 10), identically at every γ, so a relation-following
policy is route-complete on 100% of gated episodes at B = 16 and every larger
preregistered budget. Seven new tests pin containment of both routes,
γ-invariance, and the necessary-route / dead-end split.

### The two non-adaptive arms saturate late

`scripts/read_run_ceiling_sweep.py` extends the B = 128 measurement to
B ∈ {16 … 768} on all 10,000 screening episodes, 30 worker processes, about
25 s wall. Budgets above 128 are admitted only by patching the two module
tuples inside the workers; `generator.py` and `greedy.py` are unedited and the
preregistered candidates are unchanged. DIRECT's pool first exceeds 99%
route-completeness at B = 384 (99.73%); similarity-greedy is still 98.84% at
B = 512 (γ = 0) and reaches 100% only at B = 768, where every gated episode's
reachable graph is exhausted. The B = 128 rows reproduce `rc_abc_b128.json`
count for count, and route-completeness equals `proof_valid` on all 160,000
episode-arm-budget triples, exhausted walks included. Aggregates:
[`diagnostics/ceiling_sweep.json`](diagnostics/ceiling_sweep.json); per-episode
rows stay under `private/`.

By planted path length the two arms fail in different places: at B = 128
DIRECT is 100% route-complete for lengths 2–4 and 56.8% / 17.5% at 5 / 6, while
greedy is 100% at length 2 and 82.2%, 71.4%, 74.6%, 71.8% at 3–6.

### Amendment 10, pending review

[`PREREGISTRATION_AMENDMENT_10.md`](PREREGISTRATION_AMENDMENT_10.md) withdraws
Amendment 02's four coverage premises with their measured values, the
E1-v2 screening preregistration's "two ceilings" and stopping-criterion
controls and its Wilson clause; makes route-completeness a mandatory report
field beside gate 7's quantity, now called target-node exposure in prose with
its code and threshold unchanged; reclassifies the γ=0 TRAV−greedy gap as the
allocation offset; defines `lead(γ)` and `excess(γ)` against greedy with
per-seed reporting; fixes a sign-symmetric holdout decision rule; provides for
ceiling censoring; and declares the screening runs that follow. Nothing frozen
changes.

### A correction

The route-completeness report's headline cross-check count read "40,000
episode-arm pairs" against its own multiplication (5 γ × 2,000 × 2 arms × 4
budgets = 80,000); the four `rc_abc_b*.json` files confirm 10,000 episodes and
two arms each. Corrected in place, with the earlier figure noted.

## 2026-09-02 — route-completeness measured; E1-v2 overnight run stopped at gate G1

The overnight E1-v2 sequence ran tracks A–D and **stopped at gate G1**, which
failed on track B2. Track E — v2 generation, P0, code freeze and training —
never opened. No v2 data exists and no model was trained. Full report:
[`diagnostics/route_completeness_and_greedy_baseline.md`](diagnostics/route_completeness_and_greedy_baseline.md).

### Route-completeness is now a measurable quantity

`read_run/coverage.py` measures whether an examined edge set contains a complete
relation-matching route to *every* target, which is what `score_prediction`
requires. Gate 7 measures target-node-in-pool, an upper bound on it. On the
gated `hops_2_4` stratum at B=128 the two differ by **12.10pp** (100.00% against
87.90%); over all strata they are 81.30% against 69.55%.

Because generation admits exactly two relation-matching paths per episode,
`proof_valid` is a pure function of the examined set and is score-independent.
`coverage.route_coverage` and the evaluator therefore compute the same predicate
by independent means — a breadth-first frontier expansion against
`decode_best_routes`' depth-first enumeration — and agree on **0 disagreements
across more than 40,000 episode-arm pairs**. `tests/test_read_run_coverage.py`
pins this in 33 tests.

### DIRECT is at its structural ceiling, not underperforming

At γ=0 DIRECT scored 987 of the 988 episodes whose routes its pool can complete
— **99.899%** conditional accuracy. Its scorer is not the limiting factor; pool
construction is.

### A non-learned greedy arm was added, and it fails its own γ=0 validation

`read_run/greedy.py` performs TRAV's best-first walk scored by published
`query_similarity_ppm` instead of by a network. It reaches **82.65%** at γ=0
against a pre-stated ≥99.5%, so B2 failed and G1 closed.

The traces show why, and it is not an implementation fault: greedy reaches *some*
target in **100.00%** of episodes, **zero** failures came from following a
competing 900k sibling, and 193 of 195 failures are a route edge whose source
node was never expanded inside the budget. "Greedy is optimal at γ=0" is exactly
true for edge choice and false for two-endpoint coverage within a fixed budget —
structurally the same conflation as gate 7's.

### What is recorded but deliberately not acted on

An audit of every citation of gate 7's node-in-pool number is in the report.
Four conclusions do not survive when the premise is replaced with
route-completeness, including Amendment 02's "de-confounded" label for
`hops_2_4` and its 1pp γ=0 negative control, which is unsatisfiable against both
non-adaptive baselines at every preregistered budget.

**Nothing was changed in response.** No amendment was drafted, no gate rewired,
no arm or config modified; route-completeness is implemented and tested but
wired into no gate. Those are governance decisions reserved for a human.

Full suite: **274 passed, 0 failed** (241 pre-existing plus 33 new) under the
canonical `uv run pytest -q`, 454.58 s.

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

## 2026-08-31 — official-scale P0 passed under Amendment 02

All seven P0 gates passed on the official screening and train domains. The
machine-readable report is committed at `audit/read-run-p0.v1.passed.json`.

`blockers: []`, `selected_main_budget: 128`, `holdout_opened: false`.
`screening_training_authorized` and `training_authorized` are both `true`, which
authorizes E1 for this experiment only. Phase 0, Phase 1, and Phase 2 artifacts
remain mechanically `false` and pinned by `tests/test_no_training_surface.py`.

| Gate | Result |
|---|---|
| 1 gamma_measured_not_declared | pass |
| 2 gold_swap_noninterference | pass |
| 3 shortcut_probes | pass |
| 4 dire_control | pass |
| 5 dual_oracle_agreement | pass |
| 6 double_execution | pass |
| 7 direct_pool_invariance | pass |

### Amendment 02 stratification at official scale

| Stratum | n | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| `hops_2_4` (gated) | 1518 | 30.96% | 53.82% | 79.64% | 100.00% |
| `hops_5` | 412 | 0.00% | 0.00% | 0.00% | 26.21% |
| `hops_6_plus` | 70 | 0.00% | 0.00% | 0.00% | 0.00% |
| aggregate (reported, not gated) | 2000 | 23.50% | 40.85% | 60.45% | 81.30% |

Every value reproduces the 2,000-world prediction exactly, including the 81.30%
aggregate that would have blocked the sweep under the unscoped rule. B=128 is
selected from the gated stratum, and is evidence-selected from the coverage
curve rather than from any accuracy measurement.

### Gamma invariance

Coverage is bit-identical across all five gamma buckets in all three strata at
all four budgets — sixty of sixty rows. The preregistered stop condition on
gamma-correlated pool construction is cleared on official data rather than on a
sample.

### Runtime calibration

P0 took 4 hours 7 minutes (13:05:12 to 17:12:06) single-threaded. Successive
estimates during the run were 30–90 minutes, then ~15:25, then 16:25–17:00, then
18:00–18:30. The first three were too optimistic and the last too pessimistic.

This is recorded as calibration data rather than as a correction. The error came
from extrapolating byte throughput measured during cheap gates into gates that
compute `_features` on every episode, where throughput falls from about
414 MB/min to about 152 MB/min. Future estimates should be derived per gate from
its per-episode cost, not from an aggregate rate.

The measured decomposition is on record for that purpose: the dual oracle costs
0.36 ms per episode and `_features` 0.58 ms, while reading and decompressing an
episode costs 2.27 ms, so P0 is I/O-bound rather than oracle-bound, and
`shortcut_probe_gate_streaming` traverses each split four times where one pass
would do.

## 2026-08-31 — two withdrawals recorded before training

Both items below were withdrawn on evidence before any training run. The full
reasoning is in
[`PREREGISTRATION_AMENDMENT_03.md`](PREREGISTRATION_AMENDMENT_03.md).

### The aggregator check is withdrawn and will not be run

The planned max-versus-current aggregation ablation rested on an argument from
the neural algorithmic reasoning literature: max beats sum because sum's output
magnitude grows with neighbourhood size as graphs scale. That requires
aggregation width to track node count.

Neither precondition holds in this model. There is no sum aggregation —
`forward_direct` uses `contextual.mean(dim=1)` and both arms summarise with a
softmax-normalised weighted sum, whose magnitude does not grow with width — and
the aggregation width is the fixed budget B, not the node count. The failure
mode the ablation was designed to detect cannot occur here.

### E2 as size generalization is withdrawn

Amendment 01 §4 assumed one-shot pool coverage degrades as node count grows at
fixed budget. The official stratification contradicts it: coverage tracks hop
distance and B, not node count, and is flat across all four budgets and all five
gamma buckets. Sweeping node count at fixed B would have swept an axis the
measured quantity does not vary along.

It is replaced by depth generalization: train on `hops_2_4`, evaluate
inference-only at 5, 6, 7 and 8 hops at B=128, and test whether adaptive
expansion crosses a reachability boundary that one-shot expansion structurally
cannot.

### The replacement cannot run on current data

Measured on the official screening domain, farthest-target hop distance reaches a
maximum of 6: 412 episodes at 2 hops, 536 at 3, 570 at 4, 412 at 5, 70 at 6, and
**zero at 7 or 8**. `MAX_PATH_LENGTH` is 6 and background shortcuts only reduce
hop distance, so no deeper episode can exist.

Depths 7 and 8 therefore require raising `MAX_PATH_LENGTH` past its frozen value,
a fresh generation, and a fresh seven-gate P0 run. This is deferred until E1
reports, because E1's outcome decides whether E2 happens at all.

### Deep strata are descriptive only for E1

Oversampling the deep strata was considered and declined for E1. It would void
the committed P0 report and require regenerating every bucket, and it would buy
nothing, because E1 attaches decision rules only to `hops_2_4`, where n = 1,518
and coverage is already 100%.

The 5-hop and 6-hop strata are accordingly **descriptive only** in E1 and carry
no decision rule. At n = 70 the 6-hop interval is ±11.7pp on a single rate and
±16.6pp on a between-arm difference, which is an observation, not a measurement.

If E2 runs it needs a new generation anyway, so oversampling is designed into
that generation instead: a target of 800 episodes per depth at 5, 6, 7 and 8
hops gives ±5pp on the between-arm difference, the width at which the expected
reachability boundary is resolvable rather than suggestive.

## 2026-09-01 — E1 executed and voided by its own negative control

All 30 preregistered main runs completed with zero failures under code freeze
`07d18b39…` at commit `112fcb0`. The result is in
[`results/E1.md`](results/E1.md) and `audit/read-run-e1.v1.void.json`.

**The run is void.** At gamma=0 in the gated `hops_2_4` stratum the arms differ
by 28.49 percentage points against a 1.00-point threshold. gamma=0 is the regime
with no greedy-wrongness, where adaptive traversal should confer no advantage;
disagreement there means the arms are not comparable and the sweep measured an
implementation asymmetry rather than the effect it was built to test.

DIRECT collapsed to a constant predictor, emitting class 0 on 14,991 of 15,000
holdout episodes and only five distinct classes in total. Its exact-set accuracy
of 0.0002 is roughly 300× below the 1/15 chance level, which is the signature of
a degenerate constant predictor rather than a weak learner; a model that merely
failed to learn would sit at chance. TRAV was not stable either: across gamma its
accuracy runs 28.51%, 38.01%, 6.85%, 24.91%, 23.11%, with no monotone structure,
where the preregistered hypothesis expected the gap to grow with gamma.

Nothing was tuned in response. The holdout was opened once under this freeze and
is spent; a retry needs a new generation, a fresh P0, and a new holdout, and is a
new experiment rather than a continuation.

### Two failures on the way to this result, both recorded

An earlier sweep lost all 15 TRAV runs to a dtype fault: under
`torch.autocast(bfloat16)` the state cell returns a different dtype than the
query encoder, and the batched traversal's `index_copy` requires them to match.
The equivalence test that gated the batching ran fp32 on CPU and never exercised
the regime training uses. The test now runs under autocast on the training
device. The 15 DIRECT runs from that sweep were discarded **unread** so that
nothing downstream was informed by them, and the holdout was regenerated under a
corrected freeze — all ten streams verified byte-identical to their pre-fix
digests, since `generator.py` was untouched, so no re-roll was possible.

Runtime estimates were repeatedly wrong in both directions across P0 and E1.
Measured figures for future planning: DIRECT 15.3 min per run, TRAV 73.3 min per
run, both at concurrency 3 on one RTX 5070 Ti, with the whole 30-run sweep taking
7 hours 50 minutes.

## Recovery, Phase 0 — free diagnostics on the void run

2026-09-01. Two questions were settled entirely from artifacts already on disk:
the 30 `predictions.jsonl` files and the per-update logs. No model was
instantiated, no episode generated, no evaluation re-run.
[`diagnostics/per_seed_spread.md`](diagnostics/per_seed_spread.md) carries the
full record; the stratification harness first had to reproduce the committed
negative-control counts of 7/25,707 and 7,330/25,707 exactly, which it did.

**The seeds are scattered, and the scatter dominates the gamma series.** TRAV's
gamma=0.3 cell spans 3.69% to 40.45% across three seeds — a 36.76pp range within
one gamma, wider than the 31.16pp span of the entire pooled gamma curve. No seed
is uniformly stronger. The apparent lurch in the E1 curve is three-seed noise on
an undertrained model. The one qualification, recorded because it cuts the other
way: the gamma=0.2 dip is present in all three seeds, and the scatter explains
the magnitude of the irregularity without explaining that sign consistency.

**All 30 runs are post-`112fcb0`,** on two independent arguments. Every receipt
binds freeze `07d18b39…`, which recomputes to that digest and records
`git_commit 112fcb0…`; and separately, the dtype fault was fatal rather than
silent, so no pre-fix TRAV checkpoint can exist, while DIRECT never enters the
affected code path at all. The TRAV column does not mix dtype regimes.

**The label marginal is 2.5934 nats** — 25% ABSTAIN and 5% for each of fifteen
masks, measured rather than assumed. DIRECT's final loss lands between 2.5556 and
2.5799 in all fifteen runs: it learned the label frequencies and no function of
its input. This anchors the reading rule in Amendment 04.
