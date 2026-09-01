# READ run v1 — Preregistration Amendment 10

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-09-02. Route-completeness becomes a mandatory report
field, the γ=0 arm gap is reclassified from a control to a reported offset, and
the primary statistic of any retry becomes an offset-subtracted TRAV-minus-greedy
slope with a sign-symmetric decision rule. Amendments 03–09 stand except where
this amendment names a clause. Amendment 02 stands in its mechanics and loses
four of its stated premises, listed in §1 with the values that refute them.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, `training-config.v1.json`, and the v2 records of
Amendment 08 retain the exact SHA-256 digests pinned in `read_run/contracts.py`.
This amendment edits none of them and no earlier amendment; it is additive.

**Ordering.** Every threshold below was fixed in the plan approved before any
learned run at γ>0 existed, and this document is committed before the first
such run starts (§8 records how that is verified). The one measurement that
precedes it — the model-free budget sweep of §1.5 — is structural: it reads no
model, no checkpoint, and no holdout, and none of §5's numbers is derived
from it.

## 1. Withdrawals, with the values that force them

Each item names the clause, what it assumed, and the measured value under which
the assumption fails. Measurements are on the v1 screening split, gated
`hops_2_4` non-abstain stratum, n = 1,124 per γ, B = 128, from
[`diagnostics/rc_abc_b128.json`](diagnostics/rc_abc_b128.json) and
[`diagnostics/ceiling_sweep.json`](diagnostics/ceiling_sweep.json).

### 1.1 Amendment 02's four coverage premises

Gate 7 measures whether the **target node** is inside DIRECT's examined pool.
Proof-valid scoring requires the pool to contain a complete relation-matching
**route** to every target. The second is strictly stronger; `coverage.py`
measures it and `tests/test_read_run_coverage.py` pins it equal to the
evaluator's `proof_valid` flag (0 disagreements on 80,000 episode-arm pairs at
B ∈ {16, 32, 64, 128} — 5 γ × 2,000 episodes × 2 arms × 4 budgets; the earlier
report's headline says 40,000 against its own multiplication and is corrected
with this amendment — and now 0 on 160,000 over eight budgets, §1.5).

| Amendment 02 | assumed | measured at B = 128, `hops_2_4` | status |
|---|---|---|---|
| line 22: "Gate 7's 90% threshold was written to stop DIRECT losing on pool construction rather than on scoring" | gate 7 detects pool-construction loss | DIRECT target-node exposure **100.00%**; route-completeness **87.90%**; DIRECT loses 12.10% of the stratum on pool construction and gate 7 reports none of it | premise withdrawn; the threshold and the gate are unchanged (§2) |
| line 62: `hops_2_4` — "de-confounded scoring comparison" | both arms see every route | DIRECT 87.90%, greedy 82.65%, TRAV 100.00% route-complete at γ=0 — coverage differs by arm inside the stratum | label withdrawn; the stratum stays the gated stratum |
| line 106: "2–4 hops. Full coverage for both arms." | full route coverage | full **exposure** for both arms (100.00%); route coverage as above | corrected to exposure |
| line 114: the 1 pp γ=0 negative control, "load-bearing for a specific risk" | at γ=0 the arms should agree within 1 pp | TRAV's ceiling is 100.00% and DIRECT's is 87.90%: a **12.10 pp floor** on the γ=0 gap that no learning can remove | unsatisfiable by construction; withdrawn for every future run |

**E1's void verdict is not reopened.** E1 failed its γ=0 control by DIRECT
collapsing to a constant predictor (exact-set 0.0002, five distinct classes),
not by the 12.10 pp ceiling floor. A control that was unsatisfiable would have
voided a healthy run too; that it was unsatisfiable is the reason it is
withdrawn, and it changes nothing about the run it already voided.

### 1.2 The E1-v2 screening preregistration ("Track D")

[`E1_V2_SCREENING_PREREGISTRATION.md`](E1_V2_SCREENING_PREREGISTRATION.md),
recorded and not in force. Its §1 (γ set), §2 (greedy as comparator, DIRECT as
reference), §6 (budgets) and §7 (holdout sealed) **stand** and are adopted
here. Its §3 stands as a prediction already scored in its D-v. Three clauses are
withdrawn:

- **§5 "the two ceilings" parity control.** Ambiguous (D-iv). Reading A
  (DIRECT vs greedy route-completeness, > 5 pp) excludes every γ: divergences
  are 5.25, 12.54, 19.57, 27.05, 29.36 pp. Reading B (TRAV vs greedy) is
  computable only at γ=0, where it is 17.35 pp and also excludes. A control
  that excludes every cell it can see is not a control. Replaced by §3 and §4:
  the γ=0 divergence is the *offset*, subtracted rather than excluded.
- **§5 stopping-criterion control.** Vacuous (D-ii): TRAV has no stop
  decision, `model._forward_trav_one` loops `while len(all_ids) < budget`.
  Withdrawn, not substituted.
- **§4 decision threshold.** It asks for a Wilson lower bound on `excess(γ)`.
  A Wilson interval bounds one binomial proportion; `excess(γ)` is a
  difference of two differences of proportions, over three seeds. Replaced by
  §5, which is the E1-style per-seed rule.

### 1.3 Amendment 07 §2's `excess(γ)`

Amendment 07 defined `excess(γ) = gap(γ) − gap(0)` with `gap` the
TRAV-minus-**DIRECT** accuracy. It stands as a secondary descriptive, and to
avoid two quantities sharing one name it is referred to from here on as
`excess_DIRECT(γ)`. Unqualified `excess(γ)` means §4's greedy-comparator
quantity.

### 1.4 What is not withdrawn

Amendment 02's stratification, gate 7's code, its 90% threshold and the
"coverage alone selects B" rule; Amendment 04 §4's reading rule and §5's three
learner floors; Amendment 05/09's plateau rule; Amendment 06 §2's 2× extension
ceiling; Amendment 08's seed and configuration; Amendment 03's per-γ
reporting. B = 128 remains the admissible budget selected by gate 7.

### 1.5 The structural measurement that precedes this amendment

`scripts/read_run_ceiling_sweep.py`, v1 screening, all five γ, B ∈ {16, 32,
64, 128, 256, 384, 512, 768}. Budgets above 128 are diagnostic only — admitted
by patching the two module tuples inside worker processes, with
`generator.py` and `greedy.py` unedited — and none becomes a preregistered
candidate. Gated stratum, n = 1,124 per γ:

| B | DIRECT route-complete | greedy route-complete, γ = 0.0 / 0.4 | episodes with relation-prefix tree ≤ B |
|---|---|---|---|
| 16 | 30.07% | 58.19% / 32.74% | **100.00%** |
| 32 | 49.20% | 68.33% / 40.04% | 100.00% |
| 64 | 69.75% | 75.80% / 46.62% | 100.00% |
| 128 | 87.90% | 82.65% / 58.54% | 100.00% |
| 256 | 98.22% | 90.66% / 78.91% | 100.00% |
| 384 | 99.73% | 95.46% / 90.30% | 100.00% |
| 512 | 100.00% | 98.84% / 96.98% | 100.00% |
| 768 | 100.00% | 100.00% / 100.00% | 100.00% |

The **relation-prefix tree** (`coverage.relation_prefix_tree`) is every edge
on a path from the start whose relations match a prefix of the query. It is what
a walker that follows relations alone, with no lookahead and no similarity,
must examine to be route-complete with certainty. In the gated stratum its size
is **3 to 16 edges** (median 5, p95 10), identical at every γ because it never
reads similarity. **A relation-following policy is therefore route-complete on
100% of gated episodes at every preregistered budget, B = 16 included, at
every γ.** DIRECT needs B ≥ 384 for 99%; similarity-greedy is still below 99%
at B = 512 (98.84% at γ = 0) and reaches 100% only when the budget exhausts the
reachable graph (B = 768, all 1,124 episodes exhausted). The benchmark is
saturable by any arm that reads relations, which is the case §6 provides for.

The B = 128 rows reproduce `rc_abc_b128.json` count for count, and
route-completeness equals `proof_valid` on all 160,000 episode-arm-budget
triples, exhausted walks included.

## 2. Route-completeness is a mandatory report field

Every screening report and every main-run report from this amendment on
carries, for **each arm × γ × budget × stratum**, both:

- **route-completeness** — fraction of episodes whose examined set contains a
  complete relation-matching route to every target (`coverage.route_coverage`,
  `route_complete`); and
- **target-node exposure** — gate 7's quantity (`target_node_present`), reported
  beside it and never in its place.

For DIRECT the examined set is the structural pool, model-free; for greedy it
is the similarity walk, model-free; for TRAV it is the trained model's examined
set at the reported checkpoint (`scripts/read_run_trav_coverage.py`), which
depends on the model and is reported per seed.

**Gate 7 is renamed in prose only.** Its quantity is called *target-node
exposure* wherever it is discussed from now on. Its code, its 90% threshold,
and the rule that coverage alone selects the budget are unchanged, by explicit
decision: selection stays on the quantity the gate has always computed so that
the selected B = 128 is not silently re-derived, and the stronger quantity is
disclosed next to it rather than substituted for it. If a future design wants
route-completeness to *select* the budget, that is a new gate version, not an
edit to this one.

## 3. The γ=0 gap is the allocation offset, not a control

At γ=0 there is no greedy-wrongness, and the frozen design read any TRAV–arm
gap there as an implementation asymmetry to be voided. That reading assumed both
arms could cover every route in the gated stratum, which §1 shows they cannot:
at B = 128 greedy fails to complete 17.35% of routes and DIRECT 12.10%, for
structural reasons that are the same at every γ. The γ=0 gap measures how much
of that fixed-budget coverage deficit an arm's edge *allocation* recovers.

Define the **allocation offset** as `lead(0)` (§4). It is a real property of
the arms at the selected budget, reported in every result, and it is the
quantity that is *subtracted* to isolate γ-dependence. It is not a control and
its size is not a void condition.

The screening value at seed 1729, B = 128, is **+17.35 pp** (TRAV 100.00%
against greedy 82.65%). It is recorded here as a design-phase, single-seed
number, **inadmissible as a result**; the holdout value will be reported per
seed.

## 4. Primary statistic

All accuracies are proof-valid exact-set accuracy over non-abstain episodes in
the `hops_2_4` stratum at the selected budget. Greedy is model-free and has no
seed; TRAV has model seeds `s`.

```
lead_s(γ)   = acc_TRAV,s(γ) − acc_greedy(γ)
excess_s(γ) = lead_s(γ) − lead_s(0)
```

`excess_s(0) = 0` by construction. `excess_s(γ)` is reported for
γ ∈ {0.1, 0.2, 0.3, 0.4} with **per-seed values in every cell**; seed means are
shown beside them and never alone. Positive `excess` means TRAV's advantage
over similarity-greedy **grows** with greedy-wrongness — the path-dependence
hypothesis. Zero means TRAV learned greedy execution and nothing more. Negative
means TRAV degrades faster than the similarity heuristic it could have copied.

`excess_DIRECT,s(γ)` (Amendment 07 §2, DIRECT comparator) and the raw
TRAV−DIRECT gap are reported as secondary descriptives; DIRECT's curve is
retained as the γ-invariant reference (its pool, and so its ceiling, do not
depend on γ: 87.90% at every γ at B = 128).

The exact-set comparison is biased *against* TRAV, whose classifier is learned
where greedy's is exact (Track D, D-iii); the proof-valid decomposition, which
does not read the predicted class, is reported beside every cell.

## 5. Decision rule on the holdout

Three model seeds per arm per γ, the holdout opened once under a fresh freeze.
Let `min_s`, `max_s` and `mean_s` range over seeds. The verdict is one of four,
evaluated in this order, and the table is sign-symmetric by construction:

| verdict | condition |
|---|---|
| **supported** | `min_s excess_s(0.3) > 0` **and** `min_s excess_s(0.4) > 0` **and** `mean_s excess_s(0.4) ≥ +5 pp` |
| **directional negative** | `max_s excess_s(0.3) < 0` **and** `max_s excess_s(0.4) < 0` **and** `mean_s excess_s(0.4) ≤ −5 pp` |
| **null** | `|mean_s excess_s(γ)| ≤ 2 pp` for every γ ∈ {0.1, 0.2, 0.3, 0.4} |
| **inconclusive** | otherwise |

The three positive conditions cannot hold together with the null condition, so
the order is a formality. No significance test is attached: three seeds are
three seeds, and a per-seed sign requirement is the honest form of "the effect
is not one seed's noise". A verdict is issued only when §7's preconditions
hold; otherwise the run is reported as void or as inconclusive with its cause.

**Why 0.3 and 0.4, and why 5 pp.** The screening greedy curve decays most
between γ = 0 and 0.3 (82.65 → 60.85%) and flattens into 0.4 (58.54%), so the
two highest γ carry the most greedy-wrongness and the least chance of a
spurious sign. 5 pp is the frozen preregistration's own positive threshold
("the mean gamma=0.4 gap is at least five percentage points") and 2 pp is its
own null band ("at most two percentage points at every gamma"); both are reused
rather than invented, and the per-seed sign requirement mirrors its
`min(TRAV) > max(DIRECT)` clause. All were fixed in the approved plan before
any γ>0 learned data existed.

## 6. Ceiling censoring, not void

§1.5 shows the benchmark is saturable at every preregistered budget by any arm
that reads relations. If TRAV learns to, it will sit at or near 100% at every
γ, and `excess_s(γ)` then equals `acc_greedy(0) − acc_greedy(γ)` — a real,
positive number that measures greedy's decay rather than TRAV's margin.

The rule: **if `acc_TRAV,s(γ) ≥ 99.0%` at some γ, `excess_s(γ)` is
right-censored** and is reported as `≥ value`, a lower bound on the robustness
advantage. A censored cell still enters §5 — a positive lower bound is a
positive value, so "supported" can be reached with censored cells and is then
labelled **supported (right-censored)**. A censored cell cannot support
"null": if any cell is censored the null condition is not evaluable and the
verdict cannot be null.

A supported-censored verdict is a **qualitative** result: TRAV's advantage
over similarity-greedy grows with γ, and no magnitude beyond the bound is
claimed. Magnitude claims defer to a generator on which no arm saturates; that
is E2's territory and this amendment authorises nothing there. Greedy cannot
saturate at B = 128 (§1.5: 82.65% at γ = 0, decreasing), so the slope always
discriminates.

## 7. Controls on the holdout, thresholds fixed now

1. **Shuffled serialization**, per γ, per TRAV seed: re-score the checkpoint on
   the same episodes with `router_seed` salted (every node's outgoing-edge order
   re-randomised; graph, query, targets, budget unchanged). `|Δ accuracy| < 1 pp`
   → clean; `≥ 1 pp` at any γ → **Concerning** for that γ, and the cell is
   reported with the flag and excluded from §5.
2. **Greedy monotonicity.** `acc_greedy(γ)` must be strictly decreasing over
   the five γ. It is model-free and holdout-computable. A violation means the
   γ manipulation did not deliver increasing greedy-wrongness, the premise of
   `excess`; the run is then reported as **inconclusive** with the curve.
3. **Abstain rates** per arm × γ × seed (predicted-abstain on non-abstain
   episodes, and the true abstain rate), reported; no threshold.
4. **DIRECT's curve** at every γ, reported as the invariant reference; no
   threshold.
5. **Amendment 04 §4's per-cell flag** stands: a cell whose final training
   loss fails criterion (L) is reported as not having left uniform and is not
   quoted as an accuracy.

Amendment 04 §5's learner gate remains the precondition for opening the
holdout, evaluated on dev at γ=0 as written and additionally at every γ (§9).

## 8. Screening runs declared in advance

The following diagnostic runs are declared before they start. They use
`scripts/read_run_learning_probe.py` unchanged (`record_kind:
read_run_learning_probe_not_preregistered`, no training receipt, no holdout),
v1 screening data under `private/read-run-v1/p0-rerun/`, B = 128, device
`cuda` with bf16 autocast, and the v1 training configuration with only
`update_count` varied, exactly as the γ = 0 probe ran.

| arm | γ | model seed | updates | read at | checkpoint saved |
|---|---|---|---|---|---|
| TRAV | 0.1, 0.2, 0.3, 0.4 | 1729 | 9,376, scored every 500 (+100, +250) | 8,000 (= v2 `update_count`) and 9,376 | yes, at 9,376 |
| DIRECT | 0.1, 0.2, 0.3, 0.4 | 1729 | 9,376 | 8,000 and 9,376 | no |
| TRAV | 0.0, 0.4 | 2718 | 9,376 | 8,000 and 9,376 | yes — conditional on throughput, may not run |

Each trains on `train-g0X` and is scored on `screen-g0X` of the same γ. There
is no learning-rate schedule, so the 8,000-update point of a 9,376 run is what
an 8,000-update run would produce; 9,376 is used so every checkpoint aligns
with the existing γ = 0 curve (`diagnostics/learnability_probe.md`), which
supplies the γ = 0 row and is not re-run.

**Purpose:** (a) Amendment 04 §5's three floors at γ > 0, which the γ = 0
probe cannot see; (b) whether TRAV at γ > 0 sits at the §6 ceiling; (c) the
descriptive screening `lead` and `excess` at one seed. **None of these numbers
can move §5, §6 or §7**, all of which are fixed above. Every screening arm
comparison is design-phase, single-seed, and inadmissible as a result; the
screening report labels it so in every table.

Descriptives the screening report may add without becoming decision inputs:
per-checkpoint route-completeness of TRAV's examined set; the
similarity-flattening ablation of `diagnostics/trav_edge_selection_stage_c.json`
re-run on each γ > 0 checkpoint (does a γ > 0 TRAV still collapse when
`query_similarity_ppm` is held constant?); the shuffled-serialization control
of §7.1 on screening.

**Verification of order.** The commit that adds this file is recorded in
`private/read-run-v1/diagnostics/gamma-sweep/preflight.md` before the launch
script runs, and the launch log's first UTC start timestamp must post-date that
commit's timestamp. The probe writes no `started_at`; the launcher's timing log
and the output directories' creation times are the evidence.

## 9. Go/no-go for opening Track E (recommendation only)

Track E — v2 generation, P0, freeze, training, holdout — is recommended for
opening when **all** of the following hold at update 8,000 on screening:

1. both arms clear Amendment 04 §5's three floors in `hops_2_4` at **every** γ
   in {0.0, 0.1, 0.2, 0.3, 0.4};
2. the §1.5 cross-check stands at 0 disagreements;
3. no §7 control is Concerning on screening.

A failure on (1) is reported as the cell that failed; whether Amendment 04 §4
/ Amendment 06 §2's extension rule is invoked is the user's call and is not
applied automatically. A failure on (2) is a harness defect and stops
everything. The recommendation is a recommendation: opening the holdout
requires explicit human authorisation, as Track D §7 says, and this amendment
does not grant it.

## 10. What this does not authorise

No holdout is generated, read, or opened. No v2 P0 report, code freeze, or
double-execute is run. No arm, metric, seed, budget candidate, threshold or
frozen digest changes. `training_authorized` in Phase 0, 1 and 2 artifacts
remains mechanically `false`. This amendment is **pending review** until the
user says otherwise; the screening runs of §8 are diagnostics under the
existing probe and would run under the same rules whether or not it is
approved.
