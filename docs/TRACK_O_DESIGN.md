# Track O design — generator v2 and path-scoped traversal v2

## Status: decision-grade specification. Not preregistered; no run is governed by it.

Recorded 2026-09-03. The decision it implements — **traversal v2 first** — was
taken by Cameron on 2026-09-03 *before* Track N's band was read, with two
alternatives considered and declined (insert-first on a computed-walker
substrate; band-contingent branching), and is recorded with the band in
`DECISIONS.md`. The analysis this spec consolidates is
`DESIGN_NOTES_READ_PATH_SUCCESSOR.md` §1.8–§2.16; this file is the buildable
subset, one requirement per line, each with the check that proves it. The
screening preregistration that will govern the runs
(`experiments/track_o_v1/SCREENING_PREREGISTRATION.md`) is written at phase
O-4 and committed before any run starts.

## 1. What Track N settled, and what it left

Track N read **band D — pool-indistinguishable** (RC@128 at 8,000: 86.48 /
89.77 / 89.06 %, all inside [85.90, 89.90] %; every control clean;
`diagnostics/nosim_screening_report.md`). Beside the letter: structure-only
navigation *learns* (2–5 % → 82.6–85.1 % exact), the walk's examined sets are
readable (~95 % exact given route-complete vs 47 % for the blind pool), and no
curve had plateaued at 9,376 — s2718 crossed the band's upper edge after the
read point. So the possibility question is answered in the affirmative, and an
extension of the frozen architecture might eventually clear the pool line on
RC@128. Track O does not rest on the claim that it would not. It rests on the
quantity that **cannot** improve with more updates: the frozen walk examines
exactly its 128-edge budget by construction, so its examined-set precision is
capped near 5/128 ≈ 0.04 no matter what the scorer learns, while the write
path needs the walker's ≈ 0.42 or better on a small set. Precision is
architectural, not trainable, in v1. That, plus the two generator facts below,
is the case for building v2 rather than extending v1.

Two generator facts bound what any v1-data result can mean: the similarity
field marks on-path nodes at every γ (`generator._assign_similarity`), and the
task is exactly computable — the relation walker is route-complete on
1124/1124 gated episodes at B = 64, and blind breadth alone reaches 87.90 % at
B = 128 — so success on v1 data cannot demonstrate a capability an algorithm
does not already have.

## 2. The question Track O answers

**Can a traversal architecture without the v1 defects learn navigation that is
route-complete *and* precise, in a regime where neither blind breadth nor the
computed relation walker suffices?** Primary quantities, fixed now: gated
route-completeness at the run budget and at prefix budgets, and **examined-set
precision** (on-route edges ÷ edges examined; the walk stops, so the
denominator is earned, not spent). The outcome table over these is written at
O-4 against O-2's measured references, sign-symmetric, before any run exists.
Per Cameron's standing branch rule: table good → insert; table not good →
iterate on traversal, never around it.

## 3. Generator v2 requirements (phase O-1)

Version-additive (`read_run/generator_v2.py`, new schema version); the frozen
v1 generator, schemas and digests untouched.

- **G1 — leak-free similarity.** The promoted-edge device is replaced by one of
  §1.5's three options, chosen by measurement. *Check:* rank-AUC of any
  similarity-derived statistic for on-route/is-target nodes in [0.45, 0.55] on
  generated files (O-2 gate 1).
- **G2 — content-rule edges.** Nodes carry content; edge (u, r, v) is valid iff
  rule_r(content(u), content(v)); planted edges are drawn **uniformly from the
  rule-valid set**. Hidden fields record the rule-valid attachment sets so the
  insert objective never forces regeneration. *Checks:* planting-uniformity
  frequency test; recorded sets exactly recomputable from the rule.
- **G3 — a regime that defeats both references.** Difficulty axes: out-degree
  {3, 4, 6}, path length ≤ 8, γ on the widened rank knob, plus repeatable
  relations within a query and/or content-conditioned branching. *Check:* O-2
  gates 2–3 — at least one cell where the walker is insufficient at the planned
  budget, and one easy cell where it is exact.
- **G4 — v1 discipline.** Determinism from a seed path; hidden/visible
  separation; 0600/0644; structural γ-projection where applicable; typed
  errors; exit 2. *Check:* the v1 test patterns, ported.

## 4. Traversal v2 requirements (phase O-3)

Version-additive (`read_run/model_v2.py`, new training-config file), d in
128–256, equal-capacity comparator (±1 %): the adjacency-biased set reader of
design notes §2.10.

- **M1 — indexed query.** Per-relation query tokens; candidate scoring
  cross-attends to them. No `state[-1]` summary anywhere.
- **M2 — path-scoped context.** Prefix-tree cache keyed `(node, depth)`; the
  stable score term `f(query, own prefix, candidate edge)` is cached and shared
  across siblings. *Check (the property the design exists for):* identical
  (query, prefix, edge) → identical `f`, regardless of exploration history.
- **M3 — event-triggered coverage term.** `g(coverage)` re-evaluated only on:
  endpoint reached, subtree exhausted, complete path found (§2.15). Frontier
  comparisons stay commensurable within a round.
- **M4 — computed stop rule.** Best-first over the frontier; stop when the
  prefix tree is exhausted or every matching path is found; the budget is a
  cap, not a target. *Check:* on walker-exact cells the walk reproduces the
  walker's examined set and stopping point.
- **M5 — routes out.** The walk emits its routes for proof-valid scoring; no
  answer without contained evidence.
- **M6 — supervision by supplied prefix.** Teacher-forced (walker prefixes) and
  on-policy examined sets are inputs to the same scoring function; the mix is a
  data schedule. Every route edge is supervisable under its true prefix.
- **M7 — determinism, equal capacity, full-suite cleanliness**, as v1.

## 5. Order of evidence (unchanged discipline)

O-1 tests → O-2 audit and its four gates recorded in a preflight → O-3 tests →
O-4 preregistration committed, `git log -1` recorded, every probe post-dates it
→ runs → O-5 report generated by a reader whose tests pass before any run
reaches the read point. Every scalar in the outcome table derives from
structure or is preregistered; nothing is tuned on screening accuracy.

## 6. Not authorised by this document

No insert training. No holdout generation, read, or open (v1 or v2; the v2
seed stays sealed). No edit to any frozen v1 artifact. No change to Amendment
10's status. No Track O run before the O-4 preregistration is committed.
