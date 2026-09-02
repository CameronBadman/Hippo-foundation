# Track O screening preregistration — path-scoped traversal v2

## Status: recorded, screening only, NOT a preregistered arm

Written 2026-09-03, committed before the first Track O training run starts.
This governs the reading of that run. It is a screening ablation on new v2 data,
not an arm of the frozen READ v1 experiment: it opens no holdout, changes no
frozen digest, arm, metric, seed or threshold, and no comparison in it can move
Amendment 10, which remains pending review.

Every number below is copied from committed JSON — `policy_ladder.json`,
`untrained_reference.json`, `cell_audit.json` — all of which were measured
before any Track O model was trained.

## 1. What is being asked

Track N read band D: the frozen v1 traversal learns navigation from structure
but no better than a query-blind pool, and its examined-set precision is capped
near 0.04 because it always spends its budget. Track O rebuilds the traversal
around path-scoped scoring, an indexed query, and a computed stop rule
(`docs/TRACK_O_DESIGN.md` M1-M7), on a zero-shot content-rule generator whose
similarity leak is fixed.

The question is **not** "does the new architecture beat the old one" — that is
answered by construction and is reported as a descriptive contrast. It is
**does training this architecture add capability beyond what its structure
already provides**, measured on two axes at once.

## 2. Why the untrained model is the primary reference

The architecture carries two of the strongest model-free policy's mechanics
structurally: the frontier admits only relation-matching edges, and the walk
stops once both endpoints are reached. An untrained TRAVV2 therefore behaves
like a shuffled `stop_aware`, and it does — measured, gated `hops_2_4`
non-abstain, B = 64, γ = 0.4, hard cell `deg6_len8_v4_rep`:

| seed | untrained RC | Wilson LB | precision | examined | exact acc |
|---|---|---|---|---|---|
| 1729 | 82.7 % | 80.8 % | 0.166 | 37.8 | 4.31 % |
| 2718 | 84.9 % | 83.2 % | 0.165 | 38.3 | 0.24 % |
| 3141 | 89.4 % | 87.9 % | 0.172 | 37.1 | 4.96 % |

against the model-free frontier on the same episodes:

| policy | RC | precision | examined |
|---|---|---|---|
| stop aware | 86.2 % | 0.173 | 37.4 |
| hybrid | 86.3 % | 0.093 | 60.0 |
| blind walker | 78.3 % | 0.158 | 39.7 |
| greedy similarity | 22.1 % | 0.044 | 64.0 |

with the oracle floor feasible on 98.1 % of these episodes.

**So a trained model that reaches 86 % route-completeness has demonstrated
nothing**: its own untrained initialisation is already there. The outcome table
below is therefore written against the model's *own untrained line at the same
seed*, paired, with the model-free frontier beside it.

Easy cell `deg3_len6_v8`, the sanity rung — untrained:

| seed | untrained RC | Wilson LB | precision | examined | exact acc |
|---|---|---|---|---|---|
| 1729 | 100.0 % | 99.8 % | 0.408 | 13.7 | 6.45 % |
| 2718 | 100.0 % | 99.8 % | 0.406 | 13.8 | 0.44 % |
| 3141 | 100.0 % | 99.8 % | 0.416 | 13.4 | 6.79 % |

The blind walker and `stop_aware` are both 100 % route-complete there at
precision 0.411, so this cell asks only whether
training *breaks* what the architecture already does.

## 3. Runs declared in advance

`scripts/read_run_track_o_probe.py`, `record_kind:
read_run_track_o_probe_not_preregistered`, no training receipt, no code-freeze
binding, no holdout. Data: the committed v2 splits under
`private/track-o-v1/data/<cell>-g04/`, written by
`scripts/read_run_v2_write_splits.py` and pinned by their manifests.

| arm | model | cells | seeds | updates | budget | γ |
|---|---|---|---|---|---|---|
| TRAVV2 | `model_v2.build_read_model_v2`, 10,257,896 params | both | 1729, 2718, 3141 | 8,000 | 64 | 0.4 |
| TRAVV1 | frozen v1 `build_read_model`, 10,257,937 params | both | 1729, 2718, 3141 | 8,000 | 64 | 0.4 |

Twelve runs, equal capacity to 4 × 10⁻⁶ relative difference, launched in two
waves under MPS (TRAVV2 first — measured 2.56 s/update against TRAVV1's 0.69 —
under the Track N resource gates, 60 s stagger, never killed). Read point:
update **8,000**. Nothing about the schedule is conditional on a result.

**Verification of order.** The commit adding this file is recorded in
`private/track-o-v1/preflight.md` before the launcher runs; every `probe.json`
must carry a `git_head` equal to it and a `started_at` after it.

## 4. Primary quantities

Both read on gated `hops_2_4` non-abstain at update 8,000, per seed, per cell:

1. **Route-completeness at B = 64** — does the examined set contain complete
   relation-matching routes to every target (`coverage.route_coverage`, equal to
   the evaluator's `proof_valid`).
2. **Examined-set precision** — on-route edges ÷ edges examined. This is what
   the insert objective consumes, and it is a quantity only a stopping walk can
   compete on.

Reported beside them, carrying no thresholds: exact-set accuracy, stop-reason
mix, examined count, per-path-length rows, the learning curves, and the TRAVV1
contrast.

**Fixed comparisons, per seed, paired against the same seed's untrained line
(U) and against `stop_aware` (S = 86.2 % RC, 0.173 precision):**

- *RC improved* iff the trained Wilson lower bound exceeds U's point estimate.
- *RC degraded* iff the trained point estimate is below U's Wilson lower bound.
- *precision improved / degraded* iff strictly above / below U's precision.
- *clears the frontier* iff trained RC Wilson LB > S RC **and** trained
  precision ≥ S precision.

The Wilson bound is the statistical guard so that no accuracy-derived constant
is introduced; `selection.threshold_tuning: false` carries over from v1.

## 5. Outcome table — read per seed on TRAVV2, hard cell, update 8,000

| band | condition (every seed unless stated) | reading |
|---|---|---|
| **A** learned and dominant | RC improved, precision not degraded, and clears the frontier | training adds capability beyond the architecture and beats every model-free policy on both axes |
| **B** learned, frontier not cleared | RC improved and precision not degraded, but the frontier condition fails in ≥ 1 seed | training helps; the result does not yet beat a parameterless policy |
| **C** one axis | at least one axis improved and neither degraded, in every seed | partial; the per-axis rows say which |
| **D** architecture prior only | no seed improved on either axis and none degraded | the structure did the work; training added nothing measurable at this budget |
| **E** training harmful | ≥ 1 seed degraded on an axis and no seed improved | the learned scorer is worse than random under the same walk |
| **F** seeds split | any other combination | inconclusive; every seed reported |
| **G** floor failure | any arm × seed fails an Amendment 04 §5 floor on exact accuracy at 8,000 | not readable at this budget on that cell; reported beside the letter, neither suppressing the other |
| **H** harness defect | the easy cell's RC falls below 100 %, any `route_complete` ≠ `proof_valid` disagreement, or the visit-order invariance test fails at the run commit | no reading; stop, fix, rerun |

Bands A–F are exhaustive and mutually exclusive over the per-seed improve /
degrade / neither classification. **Precedence:** H over everything; G reported
beside the letter. The band is read at 8,000 only.

**TRAVV1 is not banded.** It is the equal-capacity contrast: same data, same
budget, same harness, different architecture. Its examined-set precision is
capped near 0.04 by construction because it always spends its budget, which is
the Track N finding restated on new data, not a new result.

## 6. Floors and plateau

**Amendment 04 §5 floors**, per arm × seed on exact-set accuracy at 8,000:
one-sided 95 % Wilson lower bound strictly above 1/15 **and** accuracy ≥ 7.67 %;
≥ 8 distinct predicted classes; prediction entropy ≥ 1.00 nats. Failure is band
G for that cell and is reported, never used to exclude a run.

**Amendment 09 §2 plateau reading** applied literally to the exact-accuracy
curve and, with the same mechanics, to the route-completeness and precision
curves. A curve not plateaued by 8,000 is reported as not plateaued. **No
automatic extension.**

## 7. Controls

1. **Untrained line** (§2), measured per seed before any run — the primary
   reference. Already committed in `untrained_reference.json`.
2. **Easy-cell sanity** (H if it fails): TRAVV2 must remain 100 % route-complete
   on `deg3_len6_v8` with the stop rule still firing.
3. **Cross-check** (H if it fails): `route_complete` equals `proof_valid` on
   every scored examined set.
4. **Visit-order invariance** (H if it fails):
   `tests/test_read_run_model_v2.py::test_stable_score_is_invariant_to_visit_order`
   passes at the commit the runs record — the property the architecture exists
   for.
5. **Order**: every `probe.json` `git_head` equals this file's commit and every
   `started_at` post-dates it.

## 8. What this does not authorise

No insert training. No holdout generation, read, or open — the v2 holdout seed
stays sealed and unspent. No change to any frozen v1 artifact, to Amendment 10's
status, or to the E1-v2 preregistration, which remains recorded and not in
force. No threshold tuned on any screening result. No automatic extension of the
update budget. Whether Track O's reading advances the programme to the insert
objective is decided by the user against this table, per the standing branch
rule in `docs/DECISIONS.md`: good results advance to insert, insufficient ones
iterate on traversal.
