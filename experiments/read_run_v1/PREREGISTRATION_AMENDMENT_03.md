# READ run v1 — Preregistration Amendment 03

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-08-31. Withdraws the aggregator check and replaces the E2
design. Amendment 02 stands unchanged.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`.

## 1. Withdrawn: the aggregator check

The planned max-versus-current aggregation ablation is withdrawn and will not be
run.

Its rationale came from the neural algorithmic reasoning literature, where max
aggregation beats sum because sum's output magnitude grows with neighbourhood
size as graphs scale. That argument requires aggregation width to track node
count. Neither precondition holds here:

- There is no sum aggregation in the model. `forward_direct` aggregates with
  `contextual.mean(dim=1)`, and both arms summarise with
  `(contextual * softmax(scores)).sum(dim=1)`, which is a normalised weighted
  mean whose magnitude does not grow with width.
- Aggregation width is the examined-edge budget B, fixed at 128, not the node
  count. It is identical at every world size, so the scaling failure the
  ablation was designed to detect cannot occur.

Running it would have consumed compute to compare two variants of a quantity
that is invariant in this design.

## 2. Withdrawn: E2 as size generalization

Amendment 01 §4 assumed that one-shot pool coverage degrades as node count grows
at a fixed budget. The official stratification contradicts this. Coverage is
determined by hop distance and B, not by node count: 100.00% at 2–4 hops, 26.21%
at 5 hops, and 0.00% at 6 hops, and those figures are flat across all four
budgets and all five gamma buckets.

Evaluating at 2×, 4×, 8×, and 16× node count with B fixed would therefore have
measured a quantity that does not vary with the axis being swept. E2 as written
would likely have reported nothing.

## 3. Replacement: E2 as depth generalization

The claim under test is whether adaptive expansion crosses a reachability
boundary that one-shot expansion structurally cannot.

- Train both arms on the `hops_2_4` stratum only.
- Evaluate inference-only at 5, 6, 7, and 8 hops with B fixed at 128.
- Report exact-set accuracy, DIRECT target-in-pool coverage, and TRAV terminal
  action validity per depth.
- Do not run E2 until E1 has reported. If TRAV does not beat DIRECT in the clean
  `hops_2_4` stratum, there is nothing to generalize and E2 is not run.

### The current generator cannot produce depths 7 and 8

Measured on the official 2,000-episode screening domain:

| Farthest-target hop distance | Episodes |
|---|---|
| 2 | 412 |
| 3 | 536 |
| 4 | 570 |
| 5 | 412 |
| 6 | 70 |
| 7 | **0** |
| 8 | **0** |

The maximum depth present is 6. `MAX_PATH_LENGTH` is 6, which bounds the planted
route, and background edges create shortcuts that only ever *reduce* hop
distance. No episode at 7 or 8 hops can exist under the current generator.

E2 as specified in §3 therefore cannot run on any data the frozen generator
produces. Reaching depths 7 and 8 requires raising `MAX_PATH_LENGTH` past its
frozen value of 6, which amends `PREREGISTRATION.md` §6 and requires a fresh
generation and a fresh seven-gate P0 run. That is deliberately deferred: it is
not undertaken before E1 reports, because E1's outcome decides whether E2 happens
at all.

## 4. Deep-strata statistical power

Half-widths of the 95% interval at the worst case p = 0.5:

| n | Single proportion | Unpaired difference |
|---|---|---|
| 70 (current, 6 hops) | ±11.7pp | ±16.6pp |
| 412 (current, 5 hops) | ±4.8pp | ±6.8pp |
| 385 | ±5.0pp | ±7.1pp |
| 768 | ±3.5pp | ±5.0pp |
| 1068 | ±3.0pp | ±4.2pp |

To resolve a difference between arms rather than a single rate, the unpaired
column governs. Reaching a ±5pp interval on the difference needs about 770
episodes per depth; ±3pp needs about 2,135. A paired analysis on identical
episodes would do somewhat better, but the unpaired figure is the conservative
one and is what this amendment plans against.

### Decision: no oversampling before E1

Oversampling the deep strata is **not** performed for E1. Two reasons:

1. It would invalidate the evidence just produced. The official train and
   screening domains passed all seven P0 gates and are committed at
   `audit/read-run-p0.v1.passed.json`. Changing the depth distribution changes
   every bucket, voiding that report and requiring a fresh four-hour P0 run.
2. It would buy nothing for E1. E1 attaches decision rules only to the
   `hops_2_4` stratum, where n = 1,518 and coverage is already 100%. The deep
   strata carry no decision rules in E1 under Amendment 02, so their interval
   width does not affect any E1 conclusion.

**Accordingly, and as required when oversampling is not done: the 5-hop and 6-hop
strata are descriptive only for E1. No decision rule is attached to them.** The
6-hop cell in particular, at n = 70 and ±11.7pp, is reported as a reachability
observation and nothing more.

### Target for the E2 generation, if E2 runs

E2 requires a new generation regardless, because depths 7 and 8 do not otherwise
exist. Oversampling should be designed into that generation rather than retrofitted:

**Target n = 800 per depth at 5, 6, 7, and 8 hops**, giving a ±5pp interval on
the between-arm difference and ±3.5pp on each arm's rate. That is the width at
which a reachability boundary of the expected size — DIRECT at or near zero,
TRAV materially above it — is resolvable rather than suggestive. If a smaller
effect must be resolved, 2,135 per depth gives ±3pp, at roughly 2.7× the
generation cost.

## 5. Unchanged

Amendment 02's per-stratum gate 7 scope, the `hops_2_4` gated stratum, B=128 as
evidence-selected from the coverage curve, and all frozen §5 decision rules for
the de-confounded stratum stand unchanged. The holdout remains unopened and
opens once, after the E1 code and configuration freeze.
