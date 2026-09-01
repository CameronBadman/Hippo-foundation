# READ run v1 — Preregistration Amendment 06

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-09-01. Bounds the probe-extension clause that Amendment 04
§4 opened and Amendment 05 §3 carried forward. Nothing else changes.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`.

## 0. Disclosure

Written while the probe is still running and **before TRAV reached its horizon**,
which is the point of committing it now. State of the evidence at the time of
writing:

- DIRECT: past update 5,500, transitioned, **not plateaued** under Amendment 05
  §2. Its plateau point is unknown.
- TRAV: roughly 1,250 of 4,688 updates. It has left one class behind but sits
  **below two of the three learner floors** — Wilson lower bound 6.201% against a
  required 6.67%, prediction entropy 0.552 against a required 1.00 nats. Whether
  it clears them at all is unknown.

The rule below therefore constrains an outcome that does not yet exist, for the
arm whose data does not yet exist. It is applied identically to both arms.

## 1. The gap this closes

Amendment 04 §4 rule 2 says that if one arm's plateau lands past the other arm's
probe horizon, the shorter probe is **extended** and the selection re-applied,
rather than the curve extrapolated. That was written to stop a budget being
placed where an arm had never been measured. It has no stopping point.

An extension clause with no ceiling is "extend until it works", which is the
same defect as tuning a threshold after seeing the data, reached by a slower
route. This amendment supplies the ceiling.

## 2. The extension ceiling

> **A probe may be extended to at most 2× the anchor arm's Amendment 05 plateau
> point.** If the extended arm has not cleared **all three** Amendment 04 §5
> learner floors by that ceiling — one-sided 95% Wilson lower bound above
> 1/15 = 6.67% with the point estimate at least 1.00pp above chance, at least 8
> distinct predicted classes, and prediction entropy at least 1.00 nats, all in
> the `hops_2_4` stratum at gamma=0 on the `screen` split — the recovery **stops
> for redesign**. The probe is not extended further and the curve is reported as
> it stands.

**The anchor is the first arm to plateau.** On the probe as configured that is
expected to be DIRECT, whose horizon is 9,376 against TRAV's 4,688 and which
transitioned first, but the rule is stated by role rather than by name so that it
does not depend on which arm happens to get there.

**If no arm plateaus, there is no anchor and no ceiling can be computed.** In
that case Amendment 05 §4's stop-for-redesign applies rather than an unbounded
extension of either arm.

### Why 2×, recorded before the number it will be applied to is known

DIRECT's measured behaviour supplies the scale. It sat on the label marginal for
about 2,500 updates and then completed its transition within about 500 — a
transition beginning at roughly 53% of its first plateau-eligible checkpoint. A
2× allowance therefore covers an arm whose transition arrives **twice as late as
the one arm that has been observed**, which is a wide margin for a
same-architecture, same-capacity, same-data arm differing only in how it selects
the edges it examines.

It is not so wide that it licenses indefinite extension. That is the property
being bought: the ceiling must be generous enough that a genuine slow learner is
not cut off, and tight enough that "keep training until the gate passes" is not
available. A failure at the ceiling is reported as a failure, not converted into
another extension.

## 3. What a stop under this clause means, and does not mean

A stop here says that one arm did not become a learner within twice the budget
the other arm needed. It does **not** say the arm cannot learn, and it must not
be reported as a finding about traversal or about the experiment's hypothesis. It
is a statement about the recovery's budget, and the correct response is a design
change reasoned about deliberately — not a further extension, and not a
relaxation of the floors.

The curve is reported as it stands in either case. A probe that runs to its
ceiling and fails is evidence, and it is committed with the same discipline as
one that succeeds.

## 4. Unchanged

Amendment 05's dev-defined plateau, its shared-budget maximum, and its translated
stop clause stand. Amendment 04's single-knob restriction to `update_count`, its
§5 learner-gate thresholds, its per-gamma final-loss reporting requirement, and
its §6 rejection of per-run early stopping stand. Amendment 02's stratification
and Amendment 03's E2 deferral stand.

No per-arm, per-gamma, or per-seed value is introduced here.
`fairness.arm_specific_hyperparameters_allowed` remains `false`, and
`training_authorized` in Phase 0, Phase 1, and Phase 2 artifacts remains
mechanically `false` under `tests/test_no_training_surface.py`.

E1's holdout was opened once under freeze `07d18b39…` and is spent.
