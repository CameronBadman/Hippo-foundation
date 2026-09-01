# E1-v2 overnight run — morning report

Run window 2026-09-02 02:29 → 03:05 (T+0 → T+36min). Unattended.
HEAD at start `1f70055`. Screening data only; **the holdout was not opened,
generated, or referenced.**

---

## Outcome in one line

**Gate G1 failed on B2. Track E never opened, so no v2 data was generated and no
model was trained.** Tracks A, C and D completed in full. The night's finding is
that the negative control's premise — that a non-adaptive baseline should match
an adaptive one at γ=0 — is false at every preregistered budget, and the reason
is measurable and structural.

## G1 status

| condition | required | observed | verdict |
|---|---|---|---|
| A1 computed | exists (either verdict) | 987/988 = 99.899% | **met** |
| B2 | greedy ≥ 99.5% at γ=0 | **82.65%** | **FAILED** |
| C2 | reproduce 987–989/1124 and TRAV 100% | 988/1124 and 100% | **met** |
| D committed | yes | committed, marked not-in-force | **met** |

Per the task's stop rule — *"An unattended run must never improvise past a
failed gate"* — Track E was not opened and nothing downstream was attempted.

---

## A1 — DIRECT conditional accuracy on route-complete episodes

**Verdict: pool-capped.** 987 of 988 = **99.899%**, against the pre-stated
≥ 985/988 = 99.696%.

DIRECT's scorer is exonerated. The entire 12.10pp shortfall at γ=0 is pool
construction, not scoring.

This joins two artifacts rather than reading one per-episode table, and they are
commensurable for a specific reason:

- **987** — `probe-DIRECT/screen.jsonl`, update 9376, `hops_2_4` cell:
  `correct: 987, n: 1124`.
- **988** — computed tonight by `coverage.route_coverage` over
  `structural_bfs_pool` on the same 1,124 episodes.

`structural_bfs_pool` is deterministic and query-blind, and P0 gate 7 asserts it
is bit-identical across γ, so the examined set the probe scored is the same set
measured tonight. `exact_correct ⟹ proof_valid ⟹ route_complete`, so all 987
correct episodes necessarily lie inside the 988.

## A2 — de-confounded premise audit

Every citation of gate 7's node-in-pool number, and whether it survives when the
premise is replaced with route-completeness **87.90%** on the gated stratum.
**Nothing was changed.**

| # | location | claim | survives? |
|---|---|---|---|
| 1 | `PREREGISTRATION.md:92` | B is "the smallest candidate B for which DIRECT's **target-in-pool** coverage is > 90% at γ=0" | **Yes, internally.** Says target-in-pool explicitly. B=128 is correctly selected under its own terms |
| 2 | `PREREGISTRATION.md:178` | Gate 7 tests the "structural BFS **target-in-pool** indicator" | **Yes, internally.** Correctly named; it simply measures the weaker quantity |
| 3 | `PREREGISTRATION.md:237` | stop if "no candidate B exceeds 90% **target-in-pool** coverage" | **Yes, internally.** Consistently scoped |
| 4 | `AMENDMENT_02.md:22` | "Gate 7's 90% threshold was written to **stop DIRECT losing on pool construction rather than on scoring**" | **No.** This is the gate's stated *intent*, and at B=128 DIRECT loses 12.10pp on pool construction inside the stratum the gate certified. The intent is unmet by the metric chosen to serve it |
| 5 | `AMENDMENT_02.md:62` | table: `hops_2_4` role = "**de-confounded** scoring comparison / gate 7 applies / §5 rules apply" | **No.** At 87.90% route-completeness the stratum is not de-confounded for scoring. The decision rules are attached to it on this premise |
| 6 | `AMENDMENT_02.md:106` | "**2–4 hops. Full coverage for both arms.** This is the de-confounded scoring comparison" | **No.** Full *target-in-pool* coverage (100.00%); route-completeness is 87.90%. The sentence is true of the weaker metric and false of the one scoring uses |
| 7 | `AMENDMENT_02.md:114` | "The arms must agree within 1 percentage point there or the run is void" | **No — unsatisfiable by construction.** TRAV's ceiling is 100%, DIRECT's is 87.90%. The two cannot agree within 1pp regardless of training |
| 8 | `DEVELOPMENT_LOG.md:188` | "The de-confounded stratum is exactly **100.00%** at B=128" | **Yes, as target-in-pool** (reproduced exactly tonight). Does not support the "de-confounded" label it is offered under |
| 9 | `DEVELOPMENT_LOG.md:131` | "**Proof-valid coverage** … is also **100.00%** at B=128" | **No — stale.** Describes the Amendment-01 `MAX_PATH_LENGTH=4` generator, which Amendment 02 reverted. Current value is 69.55% all-strata |
| 10 | `DEVELOPMENT_LOG.md:149` | "before the fix, proof-valid coverage (**69.55%**) sat well below target-in-pool (**81.30%**) … **although after the fix both are 100%**" | **Warning correct, trailing clause stale.** Tonight reproduces 69.55% and 81.30% *exactly*, because the fix was reverted. The clause that neutralised the warning describes a configuration that no longer exists |
| 11 | `gates.py:655-665` | selection reads the gated stratum's coverage | **Yes.** Code faithfully implements the rule; the rule measures the weaker quantity |
| 12 | `README.md:29,170` | "90% **structural target** coverage" | **Yes.** Accurately scoped, no overclaim |
| 13 | `AMENDMENT_03.md:146` | "the de-confounded stratum stand unchanged" | **Inherits #5.** Fails with it |
| 14 | `VERIFICATION.md:57` | prototypes "failed to clear 90% DIRECT all-target coverage" | **Yes.** Historical, pre-accuracy, unaffected |

**Item 10 is the significant one.** The repository had already measured this
exact discrepancy and stated the correct conclusion — *"Clearing the
preregistered target-in-pool gate does not by itself guarantee a proof-valid
answer at the same rate"* — and then discharged it with a clause that a later
amendment invalidated. Nothing was hidden; the finding was simply retired one
entry before the change that made it current again.

## B2 — greedy validation: **FAILED**

**82.65% at γ=0 against the stated ≥ 99.5%.** Reported as failed. The threshold
is not restated on a friendlier metric to obtain a pass.

The pre-stated diagnosis was "either the implementation or the understanding of
γ's definition is wrong". The traces say **neither**, and the discriminating
pair is unambiguous:

| measurement at γ=0, B=128 | value |
|---|---|
| (a) reaches **some** target | **100.00%** (1124/1124) |
| (b) covers **every** target (= `proof_valid`) | **82.65%** (929/1124) |

Failure breakdown over all 195 failing episodes:

| | count |
|---|---|
| reached neither target | **0** |
| reached exactly one of two | **195** |
| missing edge lost to a competing 900k sibling | **0** |
| missing edge's source node never expanded within budget | **193** |

**Not one failure was caused by greedy following a misleading edge.** A
representative trace: missing edge 342 carries `similarity_ppm = 900000` — it is
itself the greedy winner at its state — but its source node 89 was never
reached inside 128 edges, because the walk spent its budget on the other branch.

So "greedy is optimal at γ=0 by construction" is **exactly true** as a statement
about edge choice, and 82.65% is entirely two-endpoint budget coverage.
`_assign_similarity` promotes one winner per `(node, depth)`; at the branch
depth both routes leave the same node and only one is promoted, so the second
endpoint is reached by budget exploration, which γ does not govern.

This is structurally the same conflation as gate 7's: a threshold written
against single-route semantics, measured on a two-route metric.

Traces: `private/read-run-v2/tracks/b2_failure_traces_g00.json`.

## C2 — route-completeness regression: **PASSED**

| assertion | required | observed |
|---|---|---|
| DIRECT route-complete at γ=0 | 987–989 / 1124 | **988** (87.90%) |
| TRAV route-complete at γ=0 | 100% | **100.00%** (2000/2000, every stratum) |

Stronger than the task required: because at most one relation-matching route
reaches each endpoint, `proof_valid` is a **pure function of the examined set**
and is score-independent. So C1 and `proof_valid` are the same predicate and can
be compared episode-by-episode rather than in aggregate:

**0 disagreements across 40,000 episode-arm pairs** (5 γ × 2,000 episodes ×
2 parameter-free arms × 4 budgets), plus 0 for TRAV at B=128. Also **0
`reached_outside_targets` violations**, confirming generation's two-path premise.

`tests/test_read_run_coverage.py` pins this as 33 tests.

---

## The greedy baseline curve — the night's reference number

B=128, gated `hops_2_4` non-abstain, n=1124, one-sided 95% Wilson LB.

| γ | greedy route-complete | Wilson LB | greedy reaches-some | DIRECT route-complete | DIRECT target-in-pool |
|---|---|---|---|---|---|
| 0.0 | **82.65%** (929) | 80.72% | 100.00% | 87.90% (988) | 100.00% |
| 0.1 | **75.36%** (847) | 73.18% | 92.62% | 87.90% (988) | 100.00% |
| 0.2 | **68.33%** (768) | 66.00% | 84.61% | 87.90% (988) | 100.00% |
| 0.3 | **60.85%** (684) | 58.44% | 75.27% | 87.90% (988) | 100.00% |
| 0.4 | **58.54%** (658) | 56.11% | 72.95% | 87.90% (988) | 100.00% |

DIRECT is flat in γ by construction — its pool is query-blind, which is exactly
what gate 7's invariance property asserts. Greedy decays because γ is defined as
the rate at which similarity misleads, and greedy is the arm that follows
similarity.

Note the crossover: at γ ≥ 0.1 the **query-blind fixed pool beats
similarity-greedy traversal**, by 29.36pp at γ=0.4.

### Budget sweep (descriptive, not gating — parameter-free, so it was free)

Route-completeness, gated stratum:

| B | DIRECT (all γ) | DIRECT target-in-pool | greedy γ=0 | greedy reaches-some γ=0 | greedy γ=0.4 |
|---|---|---|---|---|---|
| 16 | 30.07% | 31.58% | 58.19% | 94.66% | 32.74% |
| 32 | 49.20% | 55.07% | 68.33% | **100.00%** | 40.04% |
| 64 | 69.75% | 80.52% | 75.80% | **100.00%** | 46.62% |
| 128 | 87.90% | 100.00% | 82.65% | **100.00%** | 58.54% |

**No preregistered budget saturates route-completeness at γ=0** for either
non-adaptive arm, while greedy's single-route metric saturates at B=32. TRAV
reaches 100% at B=128.

---

## Per-γ controls against D5's pre-stated thresholds

- **Shuffled serialization** — not runnable. Requires per-γ trained TRAV
  checkpoints, which do not exist; Track E would have produced them. *Pending,
  not clean, not concerning.* (The γ=0 instance was run on 2026-09-01 and was
  clean: 1.0000 → 1.0000.)
- **Stopping-criterion leakage** — **vacuous as specified.** TRAV has no stop
  decision; both arms loop to a fixed budget. Disclosure D-ii. No substitute
  control was invented.
- **Pool/route-coverage parity** — computed, and **ambiguous**; see below.

### D5 parity control, and the ambiguity that blocks it

"the two ceilings" is not defined, and the two readings disagree.

**Reading A — DIRECT vs greedy:** divergence 5.25 / 12.54 / 19.57 / 27.05 /
29.36 pp at γ = 0 / 0.1 / 0.2 / 0.3 / 0.4. **Every γ exceeds 5pp, so every γ is
excluded and D4 is inert.**

**Reading B — the two arms in excess(γ), TRAV vs greedy:** only γ=0 is
computable (100.00% vs 82.65% = 17.35pp → excluded). γ=0.2 and γ=0.3 need TRAV
checkpoints that do not exist; their status is **undetermined, not excluded.**

This is flagged rather than resolved, exactly as Amendment 09's
"last-qualifying" ambiguity was, and for the same reason: the reading changes
the answer.

## excess(γ)

Only γ=0 has a TRAV number: **excess(0) = 100.00% − 82.65% = +17.35pp**
(TRAV Wilson LB 99.76%, greedy 80.72%; paired, 195 discordant episodes, all
favouring TRAV).

**This is not admissible as a result and no conclusion is drawn from it.** It is
probe-derived — a diagnostic checkpoint at one seed, one γ, unfrozen, on
screening — which the execution plan's non-goal 1 excludes from any committed
result. It appears here only because the report format asked for excess(γ)
wherever both arms have numbers, and it is labelled so it cannot be quoted as
one.

## Training state

**None.** Track E did not open. No v2 generation, no P0, no code freeze, no
checkpoint, no optimizer update. No arm has a plateau status to report because
no arm was trained tonight.

---

## Decisions reserved for the human

**1. Holdout authorization — recommend NO for now.**
The v2 holdout is unsealed and ungenerated, and nothing tonight brings it
closer. The γ=0 control is unsatisfiable against *both* non-adaptive baselines
at *every* preregistered budget (DIRECT capped at 87.90% and flat; greedy at
82.65% and falling), while TRAV reaches 100%. Opening a holdout under the
current control would spend it to observe a void that is already predictable
from screening.

**2. Items flagged Concerning — three, none of them data-integrity.**

| # | item | why it needs a person |
|---|---|---|
| C-1 | D5's "the two ceilings" ambiguity | The two readings give opposite answers; picking one after seeing the curves is exactly the adaptive move the repo forbids |
| C-2 | Gate 7 certifies node-in-pool while scoring requires route-completeness | Changing a P0 gate's metric is a governance act, not a fix. Route-completeness is now implemented and tested but is **wired into nothing** |
| C-3 | A2 items 4–7: Amendment 02's "de-confounded" premise | The decision rules are attached to `hops_2_4` on a premise that does not survive. Whether that voids the attachment is the user's call |

**Not done, deliberately:** no amendment drafted, no arm/rule/config modified,
no gate rewired, no redesign proposed. The budget sweep points at one direction
and naming it is not the unattended run's decision.

---

## Verification

- Full suite **274 passed, 0 failed** (241 pre-existing + 33 new), measured by
  the canonical `uv run pytest -q` in **454.58 s**.

  A 26-way per-file shard was used while iterating and returned the same 274 in
  295 s, but it is *not* the number cited: it invokes `pytest <file> -q -p
  no:cacheprovider`, which departs from the `addopts` pinned in
  `pyproject.toml` and gives session-scoped fixtures a different session than
  they normally get. It is a faster check, not an equivalent one, so the
  verification claim rests on the canonical run. The two agreeing is
  reassuring but was not assumed. The shard's ceiling is `test_phase2_process`
  at 294.59 s, which is why it only bought 1.54x.
- `ruff check` and `ruff format --check` clean on all new source, tests, scripts.
- Route-completeness ≡ `proof_valid`: 0 disagreements, 40,000+ pairs.
- Two-path premise: 0 `reached_outside_targets` violations.
- A1's 987 and 988 come from independent artifacts, joined on a deterministic
  γ-invariant pool.
- Holdout: not opened, not generated, not read. Seed files untouched.

### Artifacts

Paths under `private/` are **session-local and gitignored** — they hold the raw
outputs this report was computed from and are regenerable from the committed
scripts. A reader of this committed copy should expect them to be absent; every
number quoted above is reproduced in the committed `rc_*.json` files beside this
file, except the B2 traces, which are withheld for the reason given in the table.

| path | contents |
|---|---|
| `private/read-run-v2/tracks/abc_b{16,32,64,128}.json` | per-γ coverage, both parameter-free arms (committed as `experiments/read_run_v1/diagnostics/rc_abc_b*.json`) |
| `private/read-run-v2/tracks/b2_failure_traces_g00.json` | B2 failure traces — **private only**: they carry per-episode `targets` and route edge ids derived from hidden `target_nodes` / `valid_routes`. Screening hidden labels are 0600 by repository convention, so only the aggregate breakdown above is committed |
| `private/read-run-v2/tracks/trav_coverage_g00.json` | TRAV route-completeness, all strata |
| `private/read-run-v2/tracks/shards/` | 26 per-file test logs |
| `private/read-run-v2/overnight-preflight.md` | T+0 machine state and the two `tail -F` monitors |
| `experiments/read_run_v1/E1_V2_SCREENING_PREREGISTRATION.md` | D, verbatim, with disclosures |
| `src/hippocampus_foundation/read_run/coverage.py` | C1 |
| `src/hippocampus_foundation/read_run/greedy.py` | B1 |
| `tests/test_read_run_coverage.py` | 33 tests |
