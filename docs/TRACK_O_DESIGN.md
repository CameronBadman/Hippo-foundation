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
- **G2 — content-rule edges, zero-shot by construction.** Nodes carry visible
  content; edge (u, r, v) is valid iff rule_r(content(u), content(v)); planted
  route continuations are drawn **uniformly from the rule-valid set**. Per
  Cameron's requirement (2026-09-03), nothing semantic is hard-coded across
  episodes: the rule instances, the rule family beyond pairwise-attribute
  compatibility (each relation gets a sampled attribute pair and a sampled
  compatibility matrix, not a fixed functional form), the schema shape
  (attribute and value counts drawn per episode from config bounds), and
  relation-id meaning are all episode-local, so the system is exercised
  zero-shot — the model must infer each episode's rules from that episode's
  observed edges. The inferability bound: a rule is a table over one attribute
  pair, observable from a few hundred in-episode edges, never a function of
  the full content tuple. Hidden fields record the rule tables and planting
  valid-set sizes, from which rule-valid attachment sets are exactly
  recomputable — the insert objective never forces regeneration. *Checks:*
  planting-uniformity frequency test; every edge satisfies its episode's
  rule; rule tables and schema shapes vary across episodes; similarity
  statistics identify no route node (rank-AUC in band).
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

- **M1 — indexed query, episode-local symbols.** Per-relation query tokens;
  candidate scoring cross-attends to them. No `state[-1]` summary anywhere.
  Zero-shot corollary: relation ids carry no stable cross-episode meaning
  under G2, so the architecture must match query and edge relations
  symbolically within the episode; a design that leans on globally learned
  per-id semantics is fighting the generator.
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

## 7. O-2 result: the gates, and the budget the measurement chose

Recorded 2026-09-03 from
`experiments/track_o_v1/diagnostics/cell_audit.json`
(`scripts/read_run_v2_cell_audit.py`, 2,000 episodes per cell per gamma at
gamma 0.0 and 0.4, 30 workers, no split written, no holdout touched).

**All four gates pass**, but only after the budget was fixed by measurement.
At the initially assumed B = 128 gate 2 failed on every cell: the computed
relation walker was route-complete on 98–100 % of gated episodes everywhere,
so no cell left anything for a learned policy to win. Rather than densify the
generator, the budget was chosen from the model-free quantity that decides the
question — the band between the **oracle floor** (a perfect selector still
expands whole nodes, so it needs out-degree x distinct route-source nodes) and
the walker's blind requirement:

| cell | gated n | gen. failure | walker RC@64 | pool RC@64 | oracle feasible @64 | room | walker precision |
|---|---|---|---|---|---|---|---|
| `deg3_len6_v8` | 1162 | 0.0 % | 100.0 % | 65.9 % | 100.0 % | +0.0 pp | 0.407 |
| `deg4_len8_v6_rep` | 1311 | 0.0 % | 95.5 % | 29.2 % | 100.0 % | +5.0 pp | 0.253 |
| `deg6_len8_v4_rep` | 1233 | 17.3 % | 79.0 % | 18.7 % | 98.2 % | +23.0 pp | 0.159 |

**The planned budget for Track O is B = 64.** At B = 128 the hard cell's room
is +1.0 pp — nothing to learn; at B = 64 it is +23.0 pp, with the oracle still
feasible on 98.2 % of episodes so the task stays solvable, and the easy cell
stays walker-exact as the sanity rung. The choice was made with no model in
existence, on coverage alone, exactly as v1 selected its budget
(`training-config.v1.json`: `budget_source:
coverage_only_before_screening_accuracy`), and is disclosed here and in the
O-4 preregistration rather than being presented as a free parameter. Cameron
took the decision on 2026-09-03 when gate 2 first failed, choosing the budget
change over densifying the generator.

**Gate detail.** (1) Leak AUCs: node-level max-similarity AUC 0.5000 on all
three cells and mean-similarity 0.5001–0.5052, all inside [0.45, 0.55], at
both gammas — the section 1.5 marker is gone. (2) Walker insufficient:
`deg6_len8_v4_rep` at 78.99 % route-complete at B = 64. (3) Walker exact:
`deg3_len6_v8` at 100.00 %. (4) Zero cross-check disagreements and zero
reached-outside-targets over all six cell-gamma audits; zero rule violations
across every generated edge.

**Zero-shot evidence.** Rule tables are distinct in every single generated
episode (2000/2000, 2000/2000, 1654/1654) and 15 distinct content-schema
shapes appear per cell, so nothing semantic is shared across episodes for a
model to memorise. Measured gamma at the 0.4 setting is 0.398–0.402 on all
three cells, so the edge-choice knob still means what it meant in v1.

**Costs recorded.** `deg6_len8_v4_rep` rejects 17.3 % of generation attempts to
the uniqueness constraint (the price of a dense graph in which only two
complete matching paths exist); the other two cells reject none.

## 8. O-3a result: the model-free frontier, and γ fixed at 0.4

Recorded 2026-09-03 from `experiments/track_o_v1/diagnostics/policy_ladder.json`
(`scripts/read_run_v2_policy_ladder.py`, 2,000 episodes per cell per γ, gated
non-abstain, budgets 16/32/64/128 — the four preregistered candidates, which are
all `greedy.greedy_examined_set` accepts).

**Track N's near-miss, avoided.** Had Track O been preregistered against the
blind relation walker, a learned walk reaching 80 % route-completeness would
have looked like a win. It is not: a three-line relation-gated similarity walk
(`policies_v2.hybrid_examined_set`) reaches **86.3 %** on the same episodes. The
reference is the *frontier* of what needs no learning, not the weakest member of
it.

**On the hard cell at γ = 0.4, B = 64 (n = 1,238), no model-free policy dominates:**

| policy | route-complete | Wilson LB | precision | examined | stopped early |
|---|---|---|---|---|---|
| blind walker | 78.3 % | 76.3 % | 0.158 | 39.7 / 64 | 75 % |
| hybrid | 86.3 % | 84.6 % | 0.093 | 60.0 / 64 | 18 % |
| greedy similarity | 22.1 % | 20.2 % | 0.044 | 64.0 / 64 | 0 % |

The blind walker wins **precision** (0.158) by stopping early on 75.3 % of
episodes; the hybrid wins **coverage** (86.3 %) by spending 60 of 64 edges.
Neither dominates, so the Pareto frontier is `['blind_walker', 'hybrid']` and the
meaningful Track O result is a learned policy that beats **both** members on
**both** axes at once. The oracle floor is feasible on 98.1 % of
these episodes, so the room above the best model-free coverage is
+11.9 pp.

**γ is fixed at 0.4** by the same coverage-only rule that chose the budget — the
value leaving the widest band between the best model-free policy and the oracle,
measured with no model in existence:

| cell | γ | band above best model-free | frontier |
|---|---|---|---|
| `deg3_len6_v8` | 0.0 | +0.0 pp | blind_walker |
| `deg3_len6_v8` | 0.2 | +0.0 pp | blind_walker |
| `deg3_len6_v8` | 0.4 | +0.0 pp | blind_walker |
| `deg4_len8_v6_rep` | 0.0 | +0.9 pp | blind_walker, hybrid |
| `deg4_len8_v6_rep` | 0.2 | +2.8 pp | blind_walker, hybrid |
| `deg4_len8_v6_rep` | 0.4 | +4.1 pp | blind_walker, hybrid |
| `deg6_len8_v4_rep` | 0.0 | +3.8 pp | blind_walker, hybrid |
| `deg6_len8_v4_rep` | 0.2 | +8.8 pp | blind_walker, hybrid |
| `deg6_len8_v4_rep` | 0.4 | +11.9 pp | blind_walker, hybrid |

**The easy cell is a sanity rung, not a comparison.** At γ = 0.4 the blind
walker is already 100 % route-complete on 1185 episodes at
precision 0.403, examining
only 13.9 of 64 edges, so its band is +0.0 pp. Its
question is "does this architecture reach 100 % where a correct policy can, and
does it stop when it is done?" — an architecture check, never evidence of
learning.

**Note on greedy.** Similarity-greedy collapses to 22.1 % on the hard cell at
γ = 0.4 and never stops early, which is the intended effect of γ: it corrupts
the promoted edge at 40 % of route states, so a policy that reads similarity
without gating on relations compounds failure over up to eight hops.

## 6. Not authorised by this document

No insert training. No holdout generation, read, or open (v1 or v2; the v2
seed stays sealed). No edit to any frozen v1 artifact. No change to Amendment
10's status. No Track O run before the O-4 preregistration is committed.
