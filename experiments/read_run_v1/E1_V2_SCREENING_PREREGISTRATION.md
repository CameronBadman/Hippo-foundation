# E1-v2 screening preregistration

## Status: recorded, NOT IN FORCE

Written 2026-09-02 during the unattended overnight run. **Gate G1 failed** —
track B2 measured the greedy baseline at 82.65% against its stated 99.5%
threshold — so Track E never opened, no v2 data was generated, and no run is
governed by this document. It is committed as the record of what was fixed and
when, so that if a v2 run is later authorised the ordering is auditable rather
than reconstructed.

Sections 1–7 are the task's text, transcribed unaltered. Nothing in them was
authored, tuned, or reworded in response to a measurement. Everything this
session measured is confined to the **Disclosures** section below, which is
additive and changes no threshold.

The task named this file `private/read-run-v2/preregistration.md`. `private/` is
gitignored (it holds seeds and hidden labels), so a file there cannot be
committed and cannot be immutable. The authoritative copy is this one;
`private/read-run-v2/preregistration.md` is a pointer to it, not a second copy.

---

## 1. Gamma sweep

{0.00, 0.10, 0.20, 0.30, 0.40}. If the generator cannot produce a value exactly,
document the substitution before generating.

## 2. Primary comparison

excess(γ) = TRAV − greedy_baseline, on screening. DIRECT is retained as a
secondary reference only. TRAV − DIRECT is no longer the hypothesis test.

## 3. Predicted shapes, stated now

- Greedy baseline: success decays with γ, consistent with compounding per-hop
  failure over 2–4 hop paths (approx. (1−γ)^hops as the reference curve).
- Hypothesis TRUE: TRAV degrades materially slower than greedy; excess(γ)
  increases in γ and its Wilson LB clears 0 at γ ≥ 0.20.
- Hypothesis FALSE: excess(γ) statistically indistinguishable from 0 at every γ
  — TRAV learned greedy execution and nothing more.

## 4. Decision threshold

The hypothesis is supported iff excess(γ) Wilson LB > 0 at both γ = 0.20 and
γ = 0.30, and point estimate ≥ 5pp at γ ≥ 0.30. Anything less is reported as
unsupported at this scale.

## 5. Controls, run per-γ, thresholds fixed now

- Shuffled-serialization at every γ: |Δaccuracy| < 1pp → clean; ≥ 1pp at any γ
  → Concerning for that γ.
- Stopping-criterion leakage (γ>0 analogue of §6): re-run TRAV with the features
  feeding its stop decision ablated per the same zeroing procedure as §6.
  Accuracy retained above the abstain base rate + 5pp → Concerning.
- Pool/route-coverage parity: report route-completeness for DIRECT and
  reachable-set route-completeness for TRAV/greedy at every γ. If the two
  ceilings diverge by > 5pp at any γ, excess(γ) at that γ is flagged as
  ceiling-confounded and excluded from the decision rule.

## 6. Budgets

DIRECT and TRAV training budgets equal to their v1 Amendment-05 settings; TRAV
extension ceiling rule carried over unchanged (max 2× DIRECT's plateau point).
Greedy needs no training.

## 7. Holdout

Sealed. This run reads screening only. Holdout spend requires explicit human
authorization after the morning report.

---

# Disclosures

Additive. No threshold above is edited, and none was chosen from a measurement.

## D-i. B2 ran before this document was written, deliberately

The overnight task ordered D at T+0 alongside B. That order was changed on
review, for a reason that is itself worth recording: §5's parity control and
§4's threshold both read a greedy baseline curve, and writing them without
knowing whether that curve even has a well-defined γ=0 anchor risked freezing a
rule that could not be evaluated.

The distinction that makes this safe: §1–§7 were authored **before any of
tonight's numbers existed** and are transcribed here unchanged. Seeing data
before transcribing a fixed threshold is not adaptation; choosing a threshold
from data is, and that did not happen. Every measurement is below, separated.

## D-ii. §5's stopping-criterion control is vacuous as written

It directs a re-run of TRAV "with the features feeding its stop decision
ablated". **TRAV has no stop decision.** `model._forward_trav_one` loops on
`while len(all_ids) < budget` and `forward_trav_batched` on
`any(len(all_ids[i]) < budget ...)`; both arms always consume the full budget
exactly. There are no features feeding a stop, so there is nothing to ablate.

This is recorded rather than repaired. Substituting some other ablation would
be authoring a new control, which is the thing this document exists to prevent.
The other two controls in §5 are well-defined and unaffected.

## D-iii. The greedy arm's classifier is exact where TRAV's is learned

`greedy.greedy_predicted_class` reads the visible assertion masks of the
endpoints its own routes reached and applies the task's public labelling rule:
agreeing endpoints give that mask, disagreement gives abstain. It uses no hidden
field — but it reproduces the generator's own rule exactly, so greedy's answer
is correct whenever its routes are complete, while TRAV's head can still be
wrong.

excess(γ) on exact-set accuracy is therefore biased **against** TRAV. That is
the conservative direction for the §2 hypothesis, so it is disclosed rather than
corrected. The proof-valid decomposition is free of the asymmetry, because
`proof_valid` does not read the predicted class at all, and is reported beside
every exact-set number.

## D-iv. §5's "the two ceilings" is ambiguous, and the readings disagree

The parity control says to report route-completeness for DIRECT and for
TRAV/greedy, then excludes a γ where "the two ceilings diverge by > 5pp". Which
two is not stated, and the readings give opposite results:

**Reading A — DIRECT vs greedy.** Measured tonight on v1 screening, B=128,
gated `hops_2_4` non-abstain (n=1124):

| γ | DIRECT | greedy | divergence | > 5pp? |
|---|---|---|---|---|
| 0.0 | 87.90% | 82.65% | 5.25pp | yes |
| 0.1 | 87.90% | 75.36% | 12.54pp | yes |
| 0.2 | 87.90% | 68.33% | 19.57pp | yes |
| 0.3 | 87.90% | 60.85% | 27.05pp | yes |
| 0.4 | 87.90% | 58.54% | 29.36pp | yes |

Every γ is excluded, and §4 becomes inert — there is no γ left to decide on.

**Reading B — the two arms in excess(γ), TRAV vs greedy.** Only γ=0 is
computable: TRAV 100.00% against greedy 82.65% is 17.35pp, excluded. γ=0.2 and
γ=0.3 need a TRAV checkpoint trained at those γ, which does not exist. Their
status is **undetermined, not excluded** — this document does not claim
otherwise.

This is flagged for a human decision in the same way Amendment 09's
"last-qualifying" ambiguity was, and for the same reason: the reading changes
the answer, so it is not the unattended run's to pick.

## D-v. §3's reference curve is not the observed shape

§3 predicts greedy decaying "approx. (1−γ)^hops". Measured, relative to γ=0:

| γ | greedy | ratio to γ=0 | (1−γ)³ |
|---|---|---|---|
| 0.1 | 75.36% | 0.912 | 0.729 |
| 0.2 | 68.33% | 0.827 | 0.512 |
| 0.3 | 60.85% | 0.736 | 0.343 |
| 0.4 | 58.54% | 0.708 | 0.216 |

The direction is right — greedy decays monotonically in γ — but the decay is far
slower than compounding per-hop failure predicts. The reason is that greedy is
not a single-path follower: it holds a 128-edge frontier, so a misleading edge
costs budget rather than ending the walk. The prediction is scored as
directionally correct and quantitatively wrong; it is not rewritten.

## D-vi. §4 is not shown satisfiable from available screening data

Under Reading A no γ survives §5. Under Reading B the deciding cells are
unmeasured. Per the task's own governing sentence — no hypothesis verdict unless
the §4 rule is actually satisfiable from screening data available at wall clock
— **no verdict is recorded**, tonight or by this document. What is measured and
what is pending are stated; nothing is inferred past that line.
