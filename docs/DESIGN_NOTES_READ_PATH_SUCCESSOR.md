# Design notes — a successor read-path experiment

## Status: exploratory. Not preregistered, not a decision, not in force.

Written 2026-09-02 during the E1 gamma-sweep GPU phase, from a working
conversation about where the read path goes after E1. Nothing here is an
amendment, a threshold, or a commitment. No measurement recorded below licenses
any change to a frozen contract, and none of it may be cited as authority for a
decision rule. Amendment 10 remains the governing reading rule for the sweep now
running.

Everything in **Measured** was observed this session with the command that
produced it named. Everything in **Proposed** is design discussion, and is
labelled as such. The distinction is the point of the document.

---

# 1. Measured

All figures are the frozen v1 generator, screening split, gated `hops_2_4`
stratum, non-abstain, n = 1124 unless stated. Source files are named per row.
Single seed (1729) except where noted. These are design-phase screening numbers
and are inadmissible as results under the preregistration.

## 1.1 The budget/precision trade

From `experiments/read_run_v1/diagnostics/ceiling_sweep.json`, gamma = 0.
"Selection precision" is the mean relation-prefix-tree size divided by the
budget — the fraction of examined edges that a perfect relation-following
selector would have needed.

| B | DIRECT pool route-complete | greedy route-complete | frontier exhausted | selection precision |
|---|---|---|---|---|
| 16 | 30.07 % | 58.19 % | 0 | 34.3 % |
| 32 | 49.20 % | 68.33 % | 0 | 17.2 % |
| 64 | 69.75 % | 75.80 % | 0 | 8.6 % |
| 128 | 87.90 % | 82.65 % | 0 | 4.3 % |
| 256 | 98.22 % | 90.66 % | 184 | 2.1 % |
| 384 | 99.73 % | 95.46 % | 449 | 1.4 % |
| 512 | 100.00 % | 98.84 % | 696 | 1.1 % |
| 768 | 100.00 % | 100.00 % | 1124 | 0.7 % |

Two readings follow from the table and both matter for a successor design.

**The top of the curve is the absence of an architecture.** The mean reachable
edge set is 455 edges (median 456, max 747). At B = 768 all 1124 episodes
exhaust the frontier — the 100 % row is "examine the entire reachable graph".
Raising the budget converges on having no memory system at all, so budget is not
a substitute for selection.

**The bottom of the curve is where a correct selector would already be —
corrected 2026-09-02.** The relation-prefix tree — the matching edges alone — is
min 3, median 5, mean 5.49, p95 10, max 16, and this section originally
concluded "a correct selector is route-complete at B = 16". That figure is a
lower bound for an edge-level selector only. Under the model's own expansion
mechanics, reaching a node examines all three of its out-edges, so a
relation-following walker examines 3·|expanded nodes| edges (gated: min 6,
median 12, mean 13.46, p95 27, max 45) and is route-complete on 29.80 % of gated
episodes at B = 8, 74.38 % at B = 16, 98.93 % at B = 32, and 100.00 % at B = 64
(`model_input_audit.json`, `relation_walker_examined_set`). The corrected
statement: a correct selector under the model's mechanics is route-complete at
B = 64, and near it (98.93 %) at B = 32. At B = 16 the real arms reach 30.07 %
and 58.19 % against the walker's 74.38 %. The 128-edge budget in use exists to
compensate for selection failure, and at that budget roughly 96 % of what is
examined is irrelevant.

## 1.2 World structure

Measured directly from the frozen gamma = 0 screening split (2,000 episodes for
the visible payload, 2,000 for the hidden records).

- **Out-degree is uniformly exactly 3.** 47,546 nodes sampled across 300
  episodes; the histogram has a single bin. This is a generator constant
  (`OUT_DEGREE = 3`), not an emergent property.
- Edges per episode: min 192, median 462, max 768.
- **Exactly two paths and two target nodes per episode**, on all 2,000.
- Route length: 2 to 6 edges, roughly uniform across that range.
- **The two paths share a prefix and diverge.** Shared edge counts across 801
  episodes: 1 edge in 316, 2 in 225, 3 in 137, 4 in 73, 5 in 50. The generator's
  invariant is two disjoint *suffixes*, not two disjoint paths.
- **Every episode has both paths carrying at least one unique edge.** Across
  2,000 episodes, 2,000 have a nonempty divergent tail on both paths; tail
  lengths are 1 to 5 edges, most commonly 1.
- **Each generated world is used for exactly one query.** 2,000 episodes map to
  2,000 distinct world identifiers and 2,000 distinct pair identifiers.

## 1.3 What the gamma = 0 arms actually did

- Similarity-greedy, parameterless, B = 128: **82.65 %** exact-set accuracy.
- TRAV, trained, same budget: **100.00 %** at update 8,000 and 9,376.
- Therefore TRAV solves all 195 gated episodes on which pure similarity ranking
  fails.
- Flattening the published similarity field at evaluation drops that same TRAV
  checkpoint to **0.27 %** (recorded earlier as the Stage C diagnostic).

**Corrected reading.** Earlier in this session I described the gamma = 0 TRAV as
having "learned to follow similarity rather than to traverse". That overstates
the evidence and is withdrawn. Greedy *is* similarity-following on the same
budget and reaches 82.65 %; TRAV reaches 100 %. TRAV is therefore
**similarity-dependent** — it collapses without the field — but not
**similarity-only**, since it beats pure similarity ranking by 17.35pp. What the
extra 17.35pp consists of (relation conditioning, backtracking, tie-breaking) is
unmeasured. The distinction changes the prior on the sweep and should not be
blurred again.

## 1.4 The DIRECT gamma curve

Completed 2026-09-02 00:55–00:58Z, four runs of 9,376 updates, seed 1729,
`private/read-run-v1/diagnostics/gamma-sweep/probe-DIRECT-g0X/`. Screening,
single seed, design-phase, inadmissible as a result.

| gamma | @8,000 | @9,376 | Wilson LB @9,376 | greedy | distinct classes | entropy (nats) |
|---|---|---|---|---|---|---|
| 0.0 | 86.74 % | 87.81 % | 0.8611 | 82.65 % | 16 | 2.769 |
| 0.1 | 82.47 % | 82.56 % | 0.8062 | 75.36 % | 16 | 2.764 |
| 0.2 | 75.71 % | 75.80 % | 0.7364 | 68.33 % | 16 | 2.731 |
| 0.3 | 70.20 % | 69.75 % | 0.6745 | 60.85 % | 16 | 2.694 |
| 0.4 | 62.01 % | 64.06 % | 0.6167 | 58.54 % | 16 | 2.672 |

**The load-bearing observation: gamma is not a pure allocation stress test.**
DIRECT's pool is query-blind and gamma-invariant; its route-completeness ceiling
is 87.90 % at every gamma. Yet DIRECT falls to 64.06 %, roughly 24pp below its
own unchanged ceiling. The noise is degrading scoring and route decoding in an
arm that has no walk to corrupt. Any successor that uses a similarity-corruption
knob inherits this confound: the knob moves two things at once.

## 1.5 A leak: the similarity field marks on-path nodes, at every gamma

Found 2026-09-02 by reading `generator._assign_similarity` and then verified
against the frozen data. **This is the most consequential measurement of the
session and it changes how the gamma sweep must be read.**

**The mechanism.** Every edge is given a base similarity in [100000, 600000)
from a hash. Then, for each *valid-path state* — a (node, depth) pair where that
node sources an edge on a planted path — exactly one of that node's out-edges is
promoted to **900000**. Gamma decides only whether the promoted edge is the
correct one (probability 1 - gamma) or an off-path distractor (probability
gamma). The in-code rationale is that a unique maximum makes ties impossible and
gives the baseline an exact decision, which it does.

**The side effect.** A node has an out-edge at 900000 **if and only if** it
sources an edge on a planted path. Checked over all 2,000 episodes of the
gamma = 0 screening split: the set of nodes carrying a 900000 out-edge equals
the set of nodes sourcing a path edge in **2,000 of 2,000** episodes, with no
exceptions in either direction. On average 4.83 nodes are marked out of 161.3,
so the marker narrows the graph to **3.00 %** of its nodes.

**Why it matters.** The promotion happens at every gamma. Gamma randomises
*which* edge at a marked node carries the marker; it never changes *whether* the
node is marked. So the similarity channel carries two distinguishable signals:

- an **edge-choice** signal, which gamma degrades exactly as intended, and
- a **node-localisation** signal — "you are standing on the path" — which is
  perfect at gamma = 0.4 exactly as it is at gamma = 0.

The sweep therefore does not remove the shortcut. It removes half of it. A model
at gamma = 0.4 can navigate by the marker and use relations only for the final
step choice at each marked node, and that would look like robustness to noise
while being nothing of the kind. A strong positive result from the sweep does not
by itself establish relation-following in the intended sense.

**What still distinguishes the two readings.** Flattening the similarity field
destroys the marker along with everything else, so the flattening probe separates
them: a checkpoint that survives flattening is not using the marker, and one that
collapses is. That probe is already implemented as the `flattened_similarity`
variant of the checkpoint diagnostic. Its status changes from a supporting
control to **the** measurement that determines what the sweep means.

**For a successor generator.** Promote an edge at non-path nodes too, or draw
the promoted value from the same distribution as the rest so that the promotion
is not identifiable, or drop the unique-maximum device entirely and break ties by
edge id. Any of the three removes the localisation leak while keeping the
baseline deterministic. This is also a concrete instance of the enumerability
argument in 2.7: the shortcut set here is small enough that this one was findable
by reading a single function, which is not true of the vision and language
settings the pessimistic literature is drawn from.

## 1.6 Generator-knob grid

Run 2026-09-02 on the idle CPU, 2,000 episodes per cell, public diagnostic seed,
`split="test-fixture"`, no holdout involvement. Full output in
`experiments/read_run_v1/diagnostics/generator_grid.json`. The frozen v1
configuration is `deg3_len6_nodes256`.

| config | generation failure | gated non-abstain | edges (median) | tree p95 | tree max | greedy route-complete at B=128, gamma 0 → 0.4 | DIRECT pool route-complete, gamma 0 |
|---|---|---|---|---|---|---|---|
| `deg2_len6_nodes256` | generation fails 100 % | — | — | — | — | — | — |
| `deg2_len6_nodes512` | generation fails 100 % | — | — | — | — | — | — |
| `deg2_len8_nodes256` | generation fails 100 % | — | — | — | — | — | — |
| `deg2_len8_nodes512` | generation fails 100 % | — | — | — | — | — | — |
| `deg3_len6_nodes256` | 0 % | 1160 | 477 | 10 | 17 | 82.33 % → 53.28 % | 86.98 % |
| `deg3_len6_nodes512` | 0 % | 1061 | 867 | 10 | 14 | 80.30 % → 51.27 % | 91.14 % |
| `deg3_len8_nodes256` | 0 % | 998 | 477 | 14 | 22 | 79.76 % → 48.20 % | 74.05 % |
| `deg3_len8_nodes512` | 0 % | 849 | 867 | 13 | 23 | 78.09 % → 44.99 % | 81.86 % |
| `deg4_len6_nodes256` | 0 % | 1376 | 636 | 12 | 19 | 71.88 % → 38.66 % | 53.85 % |
| `deg4_len6_nodes512` | 0 % | 1250 | 1156 | 12 | 19 | 72.08 % → 39.12 % | 56.72 % |
| `deg4_len8_nodes256` | 0 % | 1322 | 636 | 16 | 28 | 66.57 % → 30.56 % | 38.96 % |
| `deg4_len8_nodes512` | 0 % | 1137 | 1156 | 16 | 24 | 67.99 % → 30.96 % | 43.89 % |
| `deg6_len6_nodes256` | 0 % | 1496 | 954 | 14 | 23 | 67.51 % → 31.28 % | 33.09 % |
| `deg6_len6_nodes512` | 0 % | 1485 | 1734 | 14 | 27 | 65.59 % → 28.69 % | 31.58 % |
| `deg6_len8_nodes256` | 0 % | 1493 | 954 | 20 | 39 | 61.69 % → 22.91 % | 22.91 % |
| `deg6_len8_nodes512` | 0 % | 1474 | 1734 | 19 | 31 | 58.68 % → 20.35 % | 22.05 % |

**Out-degree 2 is impossible, confirmed at full count.** All four cells fail on
100 % of attempts. Generation requires every valid-path state to have an
off-path out-edge, and with two edges leaving each node and up to two of them on
a path, that cannot be satisfied. Out-degree 3 is the floor, not a preference.

**Raising out-degree widens the gamma range, which is what 1.5 said was needed.**
Greedy route-completeness at B=128 spans 82.33 % → 53.28 % across gamma at the
frozen configuration, a 29pp range; at `deg6_len8_nodes512` it spans 58.68 % →
20.35 %, a 38pp range. Since the maximum similarity rank on a path is bounded by
out-degree, the "k-th most attractive path" difficulty knob gains positions in
direct proportion: three at the frozen setting, six at out-degree 6.

**The task stays saturable by a correct policy everywhere in the grid.** The
relation-prefix tree reaches p95 = 20 and max = 39 at the densest setting, still
far inside a 128-edge budget, so a relation-following selector remains
route-complete at every configuration tested. Node count barely moves anything;
out-degree and path length move everything.

**But the DIRECT arm degrades badly as the graph densifies.** Its query-blind
pool is route-complete on 87.90 % of gated episodes at the frozen configuration
and only 22.05 % at `deg6_len8_nodes512`, because a fixed 128-edge breadth-first
pool covers a shrinking fraction of a denser graph. A successor that raises
out-degree either needs a larger budget for the reference arm or must accept that
DIRECT stops being an informative comparator.

**What this grid does not fix.** The localisation leak in 1.5 is independent of
every knob swept here, because the promotion to 900000 happens in
`_assign_similarity` regardless of out-degree, path length, or node count.
Widening the edge-choice knob does not narrow the node-marking one; that needs
the separate change named at the end of 1.5.

## 1.7 The flattening probe decomposed: the walk degrades, the head abstains

Measured 2026-09-02 on four finished checkpoints, gated `hops_2_4`, n = 1124,
screening only. The flattening variant sets every edge's similarity to a
constant, which removes both the edge-choice signal and the node marker of 1.5.

| training gamma | baseline exact | flattened exact | flattened route-complete | flattened abstain rate | flattened modal class share |
|---|---|---|---|---|---|
| 0.0 | 100.00 % | 0.36 % | 54.00 % | 99.47 % | 99.47 % |
| 0.1 | 99.38 % | 34.25 % | 69.13 % | 51.78 % | 51.78 % |
| 0.2 | 99.47 % | 19.04 % | 53.56 % | 58.72 % | 58.72 % |
| 0.3 | 99.91 % | 11.92 % | 66.55 % | 81.58 % | 81.58 % |

Baseline abstain rates are 0.00–0.53 % and baseline prediction entropy is 2.71
nats over 15–16 classes, so the answer head is healthy until similarity is
removed.

**The headline claim this project has been reasoning from is substantially
wrong.** "The gamma = 0 checkpoint drops from 100 % to 0.27 % when similarity is
flattened, therefore it is a learned similarity-follower" has been quoted
repeatedly in this session and in the earlier diagnostics. The number is real;
the inference about *navigation* is not. Decomposed:

- The **walk** falls from 100 % to 54.00 % route-complete. That is a large
  degradation, not an annihilation.
- The **answer head** collapses to abstain on 99.47 % of episodes, with
  prediction entropy 0.040 nats over 5 classes. Class 0 is the abstain class, so
  the model is refusing to answer, not answering wrongly.

Exact-set accuracy multiplies the two, so a head that abstains drives the metric
to near zero regardless of what the walk did. The 0.27 % / 0.36 % figure is
mostly a head-collapse measurement.

**The correct damning statement is sharper than the wrong one.** DIRECT's
query-blind structural pool is route-complete on 87.90 % of these episodes at the
same budget. A flattened TRAV walk reaches 54.00 %. **Removing similarity makes
the adaptive walker worse than not walking adaptively at all** — it falls below
the non-adaptive baseline it was built to beat. That is a stronger and better
evidenced claim than the one it replaces, and it does not depend on the head.

**Consequence for the gamma sweep in 1.4 and for the reading in this session.**
Earlier tonight I argued that TRAV's flatness across gamma could not be
marker-following, because the marker sits on a distractor 40 % of the time at
gamma = 0.4 while TRAV scores 99.64 %. That argument is correct about **edge
choice** and wrong as a general acquittal. The leak has two parts and they
behave differently:

- **Marker presence** identifies on-path nodes and is perfectly gamma-invariant.
- **Marker location** hints at the correct edge and is degraded exactly by gamma.

A model that navigates by marker presence and discriminates edges by relation is
consistent with every number measured: flat accuracy across gamma (presence is
gamma-invariant), 99.64 % at gamma = 0.4 (relations handle the choice), and a
walk that falls below the query-blind baseline when similarity is removed
(presence is gone). The sweep therefore demonstrates **relation-based edge
discrimination**, which is real and worth having, but not **shortcut-free
traversal**, which it does not establish.

**The second seed settles which of the two flattened numbers is a measurement.**
All seven checkpoints, gated `hops_2_4`, n = 1124:

| gamma | seed | baseline | shuffled delta | flattened exact | flattened route-complete | flattened abstain |
|---|---|---|---|---|---|---|
| 0.0 | 1729 | 100.00 % | +0.00pp | 0.36 % | 54.00 % | 99.47 % |
| 0.0 | 2718 | 100.00 % | +0.00pp | 6.14 % | 60.50 % | 85.85 % |
| 0.1 | 1729 | 99.38 % | +0.00pp | 34.25 % | 69.13 % | 51.78 % |
| 0.2 | 1729 | 99.47 % | +0.00pp | 19.04 % | 53.56 % | 58.72 % |
| 0.3 | 1729 | 99.91 % | +0.00pp | 11.92 % | 66.55 % | 81.58 % |
| 0.4 | 1729 | 99.73 % | +0.00pp | 14.50 % | 62.10 % | 79.09 % |
| 0.4 | 2718 | 99.56 % | +0.00pp | 30.69 % | 61.30 % | 33.63 % |

**Flattened exact accuracy is noise.** The two gamma = 0.4 seeds read 14.50 % and
30.69 %, a factor of two apart, and between them they span almost the entire
range of the single-seed figures that looked like a gamma trend
(34.25 / 19.04 / 11.92). At gamma = 0 the two seeds differ by a factor of
seventeen (0.36 % and 6.14 %). The driver is the abstain rate, which varies from
33.63 % to 99.47 % across checkpoints that are all within half a point of each
other on the baseline. Nothing in the flattened exact-accuracy column supports an
inference about training gamma, and the apparent trend in the first four cells
was an artifact of one run per cell.

**Flattened route-completeness is a measurement.** The two gamma = 0.4 seeds read
62.10 % and 61.30 % — 0.8pp apart. Across all seven checkpoints it spans
53.56 % to 69.13 % with no relationship to training gamma, and every value is far
below the **87.90 %** that DIRECT's query-blind structural pool reaches at the
same budget.

**The seed-replicated conclusion.** With similarity removed, every TRAV
checkpoint walks at roughly 53–69 % route-completeness regardless of the gamma it
was trained at, and every one of them is worse than not walking adaptively at
all. Training under noise did **not** produce shortcut-free traversal. This is a
negative result on the deeper question, and it is replicated at two gammas across
two seeds rather than inferred from a single curve.

What remains positive, and is not diminished by it: with similarity present, TRAV
holds 99.4–99.9 % at every gamma while greedy falls to 58.54 % and DIRECT to
62.01 %, and at gamma = 0.4 the marker sits on a distractor 40 % of the time. The
edge-level discrimination is real relation use. The navigation underneath it is
not.

**Controls, all seven checkpoints.** Shuffled-serialization delta is +0.00pp
everywhere, so every cell is `clean` under the 1pp rule. Route-completeness
equals proof-validity with **0 disagreements** on every checkpoint and every
variant. Amendment 10 section 9 criteria 2 and 3 are satisfied.

**Instrument note for a successor.** Flattening confounds walk and head because
it changes the head's input distribution as well as the walk's. Route-
completeness under flattening isolates the walk and should be the primary
reported quantity; exact-set accuracy under flattening should not be quoted
without it. A cleaner probe would ablate similarity from the scorer's input only,
leaving the head's features intact.

---

## 1.8 The head without the marker: DIRECT-nosim at 8,000

Measured 2026-09-02, gated `hops_2_4`, n = 1124, screening only. DIRECT-nosim is
the structural-only run whose examined set is the model-free BFS pool: no walk
is learned, `query_similarity_ppm` is held at 0 at train and eval, and route-
completeness is fixed at the pool's 988/1124 (87.90 %) at B = 128 —
reproduced exactly at every checkpoint of every seed, at every prefix budget.
It therefore isolates one thing: **what the answer head can learn to read from
structure alone, given a query-blind neighbourhood.** The preregistration (§4)
declares bands do not apply to it and fixes this reading in advance, so it is
read here ahead of the TRAV runs without adaptation: nothing about the TRAV
band, its thresholds or its schedule depends on these numbers.

| seed | exact-set acc | Wilson LB | exact given route-complete | distinct classes | entropy (nats) | modal share |
|---|---|---|---|---|---|---|
| 1729 | 41.28 % | 38.89 % | **46.96 %** | 16 | 2.41 | 32.83 % |
| 2718 | 42.53 % | 40.12 % | **48.38 %** | 16 | 2.50 | 27.85 % |
| 3141 | 41.64 % | 39.24 % | **47.37 %** | 16 | 2.46 | 30.43 % |

Chance is 1/15 = 6.67 %. The head is not degenerate — 16 distinct classes,
entropy 2.4–2.5 nats against a uniform 15-class label distribution, modal share
0.28–0.33 — so all three Amendment 04 §5 floors pass with room. This is a
learned capability, not a collapse, and it replicates across three seeds within
1.3 pp.

**The comparison that matters.** The with-similarity DIRECT run at the same
update, same pool, same seed 1729, answered 975/988 = 98.68 % of its
route-complete episodes. Masked, the same architecture on the same examined sets
answers 46.96 %. Selection was query-blind in both. **So roughly half of what
looked like reading was the head reading §1.5's on-path marker, not the graph.**
§1.7 established that the *walk* was leaning on similarity; this establishes
that the *head* was too, and it does so without the confound §1.7 carried — that
model was trained with similarity and shocked by its removal (99.47 % abstain),
whereas these heads were trained masked from update 0.

Per path length L, `exact given route-complete` by seed:

| L | n | pool route-complete | s1729 | s2718 | s3141 |
|---|---|---|---|---|---|
| 2 | 300 | 300/300 | 47.33 % | 48.67 % | 46.33 % |
| 3 | 337 | 337/337 | 50.74 % | 50.15 % | 52.23 % |
| 4 | 266 | 266/266 | 50.38 % | 53.38 % | 50.75 % |
| 5 | 118 | 67/118 | 20.90 % | 25.37 % | 20.90 % |
| 6 | 103 | 18/103 | 16.67 % | 22.22 % | 22.22 % |

L = 2–4 sit near 50 % and are flat in depth, so the failure is not path length
per se: given a route-complete pool the head identifies the endpoint about half
the time whether the route is two hops or four. L = 5 and L = 6 fall to roughly
a fifth, but each conditional is computed on that length's route-complete subset
only — 67 of 118 and 18 of 103 episodes — so those two rows are small-n and are
also the rows where the pool itself is the binding constraint.

**What this does and does not settle.** It is the "can a model read this graph
from structure alone?" measurement of §2.8, and the answer is *partially, well
above chance, far below the marker-assisted number* — not a dead idea, and not a
solved one. It says nothing about whether an adaptive walk helps; that is the
TRAV band, unread at the time of writing. The authoritative record of these
numbers is `diagnostics/nosim_screening_report.md`, generated from the JSON.

## 1.9 Track N executed: band D at 8,000, and nothing plateaued

Measured 2026-09-02/03; full record in `diagnostics/nosim_screening_report.md`
and `nosim_curves.json`, read by `scripts/read_run_nosim_report.py` under the
preregistered table, every §9 control clean (identity 0 differing episodes,
0 route-complete/proof-valid disagreements, shuffled |Δ| ≤ 0.09 pp, prefix
tests passed at the recorded commit, every probe post-dates the preregistration
commit it names).

**The band is D — pool-indistinguishable**: every seed's RC@128 at update 8,000
sits inside the null band [85.90, 89.90] % around the query-blind pool.

| seed | RC@128 @8,000 | RC@32 | exact | exact given RC | RC@128 @9,376 | exact @9,376 |
|---|---|---|---|---|---|---|
| 1729 | 972/1124 (86.48 %) | 63.79 % | 82.56 % | 95.47 % | 984/1124 (87.54 %) | 84.34 % |
| 2718 | 1009/1124 (89.77 %) | 62.19 % | 85.14 % | 94.85 % | 1013/1124 (90.12 %) | 87.90 % |
| 3141 | 1001/1124 (89.06 %) | 63.70 % | 83.99 % | 94.31 % | 993/1124 (88.35 %) | 84.79 % |

Three facts sit beside the letter and belong to any reading of it:

- **Structure-only navigation learns.** From ~2–5 % answers at update 1,000 to
  82.6–85.1 % at 8,000, with the walk's examined set read at ~95 % given
  route-completeness — against 47 % for the same head on the blind pool (§1.8).
  The with-similarity collapse was shortcut preference, not inability.
- **Not one of the nine curves plateaued** (exact, RC@128, RC@32 × three
  seeds, Amendment 09 read literally): all were still climbing at 9,376, and
  s2718 crossed the null band's upper edge *after* the read point
  (RC 90.12 % at 9,376). The letter is read at 8,000 by rule; extension is a
  human decision and is not made here.
- **Precision is where the distance is.** RC@32 is 62–64 % against the
  walker's 98.93 %, and the walk still spends its full budget (§2.16). The gap
  to a correct selector is selection efficiency, not reachability.

Per the preregistration's §8, band D reads: as frozen, the architecture does
not learn navigation from structure *at this budget* — an optimisation or
architecture limit, and the walker design changes before insert. The programme
decision that follows (Track O: generator v2 plus the path-scoped traversal of
§2.12–§2.16, decided before this band was read) is recorded in
`docs/DECISIONS.md`.

# 2. Proposed

None of this is designed, costed, or agreed. It is the shape of the idea as it
stood at the end of the conversation.

## 2.1 Ablation instead of noise

Replace the similarity-corruption knob with **route ablation**: remove the route
the policy would prefer, leaving a valid but less-preferred route in place, and
train on the result.

Why it is a better instrument than a noise fraction:

- It is an automatic hard-negative generator. Whatever heuristic the policy is
  leaning on is what gets removed, rather than whatever a global noise parameter
  happens to disturb.
- It needs no hyperparameter. The current sweep exists because nobody knows the
  right noise level; ablation depth is an integer that is set, not searched.
- It does not suffer the confound in 1.4. Removing a route changes the graph,
  not the meaning of the similarity field, so the scoring channel is left alone.

**Depth 1 is the load-bearing case, and it does NOT run on the frozen v1 data.**
An earlier draft of this section claimed it did, on the grounds that all 2,000
sampled episodes have both paths carrying unique edges (1.2), so one path's
divergent tail can be deleted with the other left intact. The structural fact is
correct; the inference drawn from it was wrong, and the error is worth recording
because it constrains the whole approach.

The v1 task requires **both** paths, not either one. `coverage.route_coverage`
defines completeness as the reached endpoint set being a superset of the goal
set, and every episode has two goal nodes. The two planted paths are not alternatives competing to be
found; they are jointly required, and the answer rule then asks whether their
endpoints agree. Deleting one therefore makes the episode **unsatisfiable rather
than harder**, and an ablation evaluation on v1 data would measure zero for a
trivial reason.

Ablation needs a task in which paths are alternatives — plant k, require any one
(or any m of k) — which is a change to the task definition, not only to the data.
That is legitimate for a successor experiment, but it means the approach cannot
be trialled on the frozen corpus and its cost is a v2 task plus a v2 generator,
not a weekend of CPU.

**The difficulty knob already present in v1 is bounded, and the measurement says
by what.** For every gated non-abstain episode at gamma = 0, each true-path edge
was ranked among its source node's out-edges by the published similarity field
(rank 1 = a similarity-follower takes that step for free). Measured over all
1,124 episodes:

- The maximum rank on a true path is **never 1, and never above 3**. It is 2 in
  562 episodes and 3 in the other 562. Out-degree 3 caps it: with three edges
  leaving every node there is no fourth position for an answer to hide in.
- That rank predicts greedy success only weakly: **89.15 %** at max rank 2 versus
  **76.16 %** at max rank 3, a spread of 13pp.
- **Path length is the far stronger predictor**: 100.00 % at length 2, 82.20 % at
  3, 71.43 % at 4, 74.58 % at 5, 71.84 % at 6.
- Episodes greedy fails are structurally bigger: mean path length 4.14 against
  3.31, tree size 7.18 against 5.14, 524 edges against 459.

The consequence for 2.2 is direct. "The answer is the k-th most similarity-
attractive path" is the difficulty knob the constructive generator wants, and
**out-degree is what sets its ceiling** — at out-degree 3 the knob has three
positions and only about 13pp of discriminating power. Raising out-degree is
therefore not a nice-to-have for depth; it is the precondition for the difficulty
axis to exist at all.

**Depth beyond 1 needs constructed worlds, not deeper search.** Out-degree 3
bounds edge-disjoint paths from the start node at 3 (Menger), so a random world
cannot carry a long ladder. This bounds difficulty per world; it does not bound
training signal, because worlds are cheap and currently wasted (1.2: one query
per world, and a 256-node graph supports many).

## 2.2 Constructive generation

Plant the paths first, then grow the world around them, instead of sampling a
world and rejecting it until the invariants hold. The current generator retries
up to 128 times per episode and fails outright at out-degree 2, which is a
symptom of the rejection approach rather than of the task.

- A **broom** buys depth cheaply: a shared stem, one branch node of out-degree k,
  k tails reconverging on the target. Depth k costs a single high-degree node
  rather than a uniformly dense graph.
- **The planted paths should be similarity-ranked deliberately** — route 1 most
  attractive, route k least. Without that, ablation removes options and makes the
  task easier rather than harder. With it, ablation depth d means "the best
  surviving route is the (d+1)-th most similarity-attractive", which is a
  per-episode integer difficulty label available at generation time.
- **Depth 0 must stay in the training mix.** If the preferred route is always
  wrong, the policy can learn to invert the heuristic — the same failure with the
  sign flipped. Similarity has to be right often enough that relations are the
  only way to tell the cases apart.

## 2.3 Traps worth naming now

- **Constructive generation requires a verification pass.** Random filler edges
  will occasionally create an accidental relation-matching route that was not
  planted, silently falsifying "exactly k ranked paths" and putting noise in the
  labels that no unit test would catch. Enumeration is cheap — the tree is a
  median of 5 edges — but it has to exist.
- **The off-route distractor invariant is load-bearing and easy to lose.** The
  current generator requires every valid-route state to have an off-route
  out-edge; planting paths rather than rejecting worlds is exactly the change
  that would drop it by accident.
- **Keep the relation-sequence query.** Degrading the task to "find any path from
  A to B" teaches reachability and discards the proof semantics that make a route
  evidence rather than a guess. Ablate the preferred route, keep the relation
  constraint.
- **A model-dependent curriculum breaks reproducibility.** Removing "the route
  the model took" makes the training data a function of the model, which is
  incompatible with frozen splits, hash-pinned preregistration, and deterministic
  execution. Precomputing the ladder offline by removing the *similarity-preferred*
  route each round preserves the mechanism, stays seed-reproducible, and attacks
  the same failure mode.

## 2.4 The paired design this makes available

One ablation yields two episodes from one world: same graph, same query, with
and without the preferred route. That is a **within-world control** — the
shortcut effect measured with everything else held constant. The sweep now
running compares independently generated worlds across five noise levels and
needs three seeds to say anything; a paired contrast needs far fewer episodes for
the same confidence. This is the strongest methodological argument for the
approach and does not depend on any of the generator work.

## 2.5 Precision, the stop rule, and why traversal is a substrate

The project's intent is that traversal is the first capability in a sequence and
is later used to train the write operations. Those consume traversal's
intermediate state — which edges were examined and how they were scored — not its
final answer. Accuracy can therefore be high while the state that gets passed
downstream is mostly noise, which is what 1.1 shows at B = 128.

Three observations about the current harness follow:

- **There is no stop decision.** Both arms loop until the budget is consumed, so
  every arm examines exactly B edges and nothing can reward a policy that needed
  five. This is also why the earlier stopping-criterion control was vacuous.
- **Every scored metric is recall-flavoured.** Route-completeness, proof validity,
  and target-node exposure all ask whether the examined set *contained* the
  paths; none asks whether it contained *only* them. A policy that became precise
  would score identically to one that did not.
- **A precision-shaped objective already exists.** Training applies binary
  cross-entropy on the edge scores against membership of the true paths, at
  weight 0.25 against an answer-loss weight of 1.0. The model is already trained
  to rank route edges above the rest; what is missing is an inference-time stop
  rule and a precision metric, not a new loss.

A gate of the form "traversal is good enough, start on the write operations"
should therefore be a precision-and-mechanism gate, not an accuracy gate.

## 2.6 The insert objective: manufacture the label by deleting a node

The stated original design for the insert capability is to **remove a node and
train the model to traverse and select every node that connected to it**. Three
properties make this stronger than it first appears, and two make it harder.

**It is the task that finally makes precision a scored quantity.** Section 2.5
records that the read path cannot measure precision: both arms consume exactly
the budget, and every scored metric asks whether the examined set *contained* the
answer rather than whether it contained *only* the answer. The insert objective
has no such escape. Its answer **is** a set, so a false attachment point costs
directly, and precision is scored without needing an inference-time stop rule
bolted on. The capability the roadmap wants next happens to be the one that fixes
the measurement gap in the capability before it.

**It is the same trick as the ablation curriculum, applied to a different
capability.** Both manufacture exact supervision by removal: delete the preferred
path and the label is the surviving path; delete a node and the label is its
former neighbourhood. One generator mechanism, no annotation, exact ground truth
in both cases. That is an argument for building the removal machinery once and
using it twice.

**It is architecturally almost free.** Training already applies binary
cross-entropy per examined edge against membership of the true path set. The
insert objective is binary classification over candidate attachment points across
the same examined set. It changes what the training target means, not the head.

**Prediction versus retrieval, and why the first framing was the wrong target.**
An earlier draft of this section objected that the objective is unsolvable
without learnable graph regularity: delete a node, its edges go with it, and
nothing remains to recover the neighbourhood from. That objection is aimed at a
*prediction* framing — "given the graph minus this node, predict what it was
attached to" — which does depend on statistical regularities in the wiring.

Cameron's framing is *retrieval*, and it dissolves most of the objection. The
model is handed the node's payload and finds where that content belongs, by
matching content against the surviving graph. The signal is then not graph
statistics but the **edge-formation rule relating the two endpoints' content**,
which is observable thousands of times over in the edges that were not deleted.
The requirement is therefore much weaker than "community structure" or exotic
latent structure: it is only that **edges be a function of what the endpoints
contain, rather than arbitrary**. Every real memory graph satisfies that by
construction, because its edges mean something.

What survives of the objection is narrow but real: the current generator wires
randomly at uniform out-degree 3, so endpoint content predicts nothing there and
this objective cannot be trained on it as it stands. That is a generator
requirement, not an obstacle in principle.

**The label is the historical neighbourhood, and the correct label is the valid
one.** This is the sharper version of the same problem and it survives the
reframing. Deleting a node yields the attachment points it *happened* to have.
Under a content-matching rule there may be other equally valid attachment points
it simply did not have, and scoring against the historical set penalises the
model for correct answers while training it to reproduce arbitrary wiring. The
read path already handles the analogous case, since both planted paths count. For
insert the label must be the set of *rule-valid* attachment points, which is
computable exactly when edges are planted by a rule and not computable at all
when they are arbitrary. Label correctness and learnability therefore require the
same generator change, and are solved by it together.

The fix is a generator setting rather than a scale decision, and which one it is
matters. If the planted edges are drawn **uniformly at random from the rule-valid
set**, the historical label is an unbiased sample of the valid set: the omissions
differ from world to world, they average out across examples, and more data does
genuinely converge on the rule. If instead the planted edge is chosen by some
preference — the nearest or most similar valid endpoint, say — the omission is
systematic, every example carries the same bias, and more data entrenches it into
a confident wrong answer. Unbiased planting is what makes scale work here; it is
not something scale can supply on its own.

**The unification is the real payoff.** Under the retrieval framing the read and
insert capabilities become one primitive with two query types: given a relation
sequence, traverse and select the evidence path; given a payload, traverse and
select the attachment points. Same traversal, same selection head, same
per-candidate binary objective. That is a considerably stronger architectural
position than two separately trained capabilities, and it is the reason to pursue
the retrieval framing rather than the prediction one.

**Insert inherits the read path's shortcut unless it is designed out from the
start.** If insert is content-matching retrieval, its failure mode is "attach to
the most similar node", which is the same failure the read path already exhibits
one level down. Should the generator's edge rule correlate with the published
similarity field, insert will learn similarity-matching and the shortcut is
rebuilt one layer up. The removal discipline from 2.1 — make the obvious answer
wrong often enough that the rule must be learned — has to be applied to insert
from the beginning rather than retrofitted after the fact.

**The query has to be reframed, because you cannot refer to what you deleted.**
"Reconstruct the neighbourhood of node X" is not a well-posed prompt once X is
gone. The well-posed version hands the model the node's payload and asks where it
attaches — which is exactly the runtime insert decision. Deletion is not the task;
it is the label-manufacturing trick behind the task.

**Traversal's recall bounds the insert ceiling, and should be measured first.**
Candidate generation for insert is traversal. If traversal can only reach
similarity-adjacent nodes, insert can only propose similarity-adjacent attachment
points, and a true neighbour outside that reach is unreachable no matter how good
the selection head becomes. The cheap precondition is the insert analogue of
route-completeness: for a deleted node, does the traversal's examined set contain
its former neighbourhood? Measure that before training a selection head on top,
or the head is being optimised against a retriever that cannot deliver.

Two smaller notes. Difficulty should be stratified by the deleted node's degree,
since reconstructing a degree-3 neighbourhood and a degree-30 one are different
problems and the current generator only exhibits the former. And the relation
type of each reconstructed edge is a free additional label that insert genuinely
needs at runtime — knowing where a fact attaches is not enough without knowing
how.

---

---

# 2.7 Prior work, and what it changes

A literature review was commissioned on 2026-09-02. Its report is transcribed
unaltered in `docs/LITERATURE_REVIEW_2026-09.md`; this section is the analysis of
it and is not part of that source document. **None of its citations were independently verified in this
repository.** The report itself flags two anchors (GROVER, Graph-BERT) as
recalled without a retrieved source. Treat every quotation below as second-hand
until checked; the two that carry the most decision weight are named at the end
of this section as the ones to spot-check first.

## What it establishes

**Our failure mode was named in 2018 and is still open.** Multi-hop KG reasoning
with reward shaping (Lin, Socher, Xiong, EMNLP 2018) describes an agent "misled
by spurious search trajectories that incidentally lead to the correct answer",
and notes that because spurious trajectories outnumber correct ones they are
found first and exploration becomes biased toward them. Work through 2023 (a
path-spuriousness metric and reward, EACL 2023) is still attacking it. The
failure we measured is the canonical one, not a novelty.

**The ablation curriculum is known-disappointing as a training lever.** The
structurally identical line — adversarial filtering of examples a weak heuristic
already solves — reports that mitigating one shortcut amplifies reliance on
others (CVPR 2023), that filtered evaluation sets do not preserve model rank
order (ACL DADC workshop 2022), and that adversarially trained multi-hop QA
models remain limited on adversarial test data (ACL 2019). This is a direct hit
on 2.1 and demotes it from primary training mechanism to diagnostic.

**Model-dependent curricula have a quantified failure mode.** Self-mined hard
negatives in dense retrieval are contaminated by false negatives — roughly 70 %
of top-retrieved passages inspected in one study were actually positive — and
contamination worsens as the model improves. This is a second, empirical reason
for the conclusion 2.3 already reached from reproducibility grounds: the
ablation ladder must be **precomputed from the parameterless baseline's fixed
scores**, never from the trained model's evolving ones. Two independent
arguments now converge on the same design.

**The insert objective needs edge reconstruction, not feature masking.** Graph
masked-autoencoding that reconstructs node *features* is reported not to help
link prediction, because it never minimises edge reconstruction error, whereas
denoising *link* reconstruction transfers well precisely to link-classification
tasks. Section 2.6's objective is neighbourhood recovery, so the pretext must be
structural. Negative transfer in graph pretraining is well documented, so any
pretraining gain must be ablated against from-scratch and discarded if it does
not exceed roughly one standard deviation.

**The methodology stands up.** Parameterless shortcut baselines are orthodox —
hypothesis-only inference, question-only visual QA, claim-only verification, and
frequency-rule knowledge-graph completion are all standard instruments, and our
budget-matched variant is a refinement beyond the norm. Proof-scoring is
established as a reported metric (joint answer-and-supporting-fact scoring, and
all-or-nothing proof-tree scoring in entailment work); making it a *gate* on
correctness is stricter than the norm and was found to have no direct precedent
in budget-limited traversal.

**One warning we already satisfy, and must keep satisfying.** Strict proof gates
under-credit correct reasoning when multiple valid proofs exist. Our v1
generator enforces that the only complete relation-matching paths in the graph
are the constructed ones, so there is nothing to under-credit. If a successor
plants k paths and requires any one, **the gate must accept any valid decoding
path**, and that property has to be enforced in the generator rather than
assumed.

## Where the report is wrong about us, and it matters

The report reads our failure through the reinforcement-learning spurious-path
literature and recommends process supervision as the durable fix. **We already
have process supervision, and it did not prevent the failure.**

The systems that literature describes learn from a sparse terminal reward, so
any trajectory reaching the answer is reinforced and credit assignment is the
problem. Our training is not that. It applies binary cross-entropy per examined
edge against membership of the true path, at weight 0.25 against an answer-loss
weight of 1.0 — the model is told directly, edge by edge, which edges lie on the
correct path. It became a similarity-follower anyway.

That is a stronger result than the one the report imports, and it points
somewhere different. Dense per-edge supervision does not defeat the shortcut when
the shortcut *predicts the supervision*: the scorer can minimise the edge loss by
reading the similarity scalar, because similarity and true-path membership are
correlated by construction. The remedy therefore cannot be "add process
supervision"; it has to be to break the correlation itself, or to change what the
scorer is allowed to see.

Two cheap diagnostics follow, neither of which the report could have suggested:
raise the edge-loss weight (or pretrain on the edge loss alone) and see whether
the flattening collapse softens; and train a scorer with the similarity input
removed entirely, to establish whether the architecture can rank relation-
matching edges at all without it. Both are diagnostic runs against a modified
config and neither touches the frozen v1 contract.

## Where our setting is friendlier than the pessimistic literature

The strongest "next shortcut down" evidence comes from vision and natural
language, where the space of exploitable surface features is large and largely
unenumerable. Our episodes expose a per-edge feature set that is small and known:
a relation embedding, the endpoint assertion encodings, and one similarity
scalar. There is no long tail of alternative shortcuts to migrate to, and the
enumerability means all known shortcuts can in principle be ablated at once
rather than one at a time — which is what the vision work prescribes and cannot
usually do. This does not overturn the pessimistic reading, but it is a real
disanalogy and it is the reason 2.1 is demoted rather than abandoned.

Our ground truth is also exact and synthetic, so the annotator-disagreement
pathology that drives much of the adversarial-filtering skepticism does not apply
here at all.

## Verify these two first

The two claims carrying the most decision weight are the 2018 spurious-path
characterisation (it is the basis for treating our failure as canonical) and the
false-negative rate in self-mined hard negatives (it is one of the two arguments
for precomputing the ablation ladder). If either is misattributed, the conclusion
it supports needs re-deriving rather than inheriting.

# 2.8 What Track N can and cannot decide

Written 2026-09-02 while the six masked runs are between update ~350 and ~4,700
of 9,376, before any of them reaches the 8,000 read point. It exists because the
question "is a graph-based model a dead idea?" is not the question the band
answers, and the two get fused easily. Per-band consequences are owned by
`NOSIM_SCREENING_PREREGISTRATION.md` §8 and are deliberately not restated here.

**What is actually under test.** TRAV is a GRU-conditioned per-edge scorer
driving a hard greedy expansion: `model.py` scores each out-edge of an expanded
node from the source/target assertion masks, a relation embedding, the query GRU
state and (unmasked) one similarity scalar, then expands the argmax. Its edge
supervision is `binary_cross_entropy_with_logits` against `_edge_targets`
(`training.py:146`), which labels an edge 1 iff it lies on a valid route — but
only over `output_batch["edge_ids"]`, the edges the walk **actually examined**.
Selection is not differentiable and is not policy-gradient trained; it is a
directly supervised scorer whose training distribution is generated by its own
past choices.

**So the band is near-silent about a graph transformer.** A transformer over a
retrieved subgraph has no walk to learn and no such loop: its examined set is
chosen by a retrieval policy outside the model, and every candidate edge is in
its input whether or not it was on the argmax path. That architecture's analogue
in this experiment is DIRECT, whose examined set is the model-free BFS pool. A
band D or E on TRAV-nosim would say that *this* scorer, under *this* self-
generated supervision, does not learn to navigate; it would not transfer to an
architecture that never navigates.

**Two questions, two different measurements.**

- *Is a learned walk worth having?* — the §5 band on TRAV-nosim, read at 8,000.
- *Can a model read this graph from structure alone at all?* — DIRECT-nosim's
  `exact_given_route_complete` against its fixed 87.90 % pool ceiling. §4 says
  bands do not apply to DIRECT-nosim; it is a head-only reference. This, not the
  band, is the "dead idea" measurement, and it is the cheaper of the two.

Do not read the with-similarity DIRECT number (86.74 % exact at 8,000, ≈ 98.7 %
of its 87.90 % pool ceiling) as evidence that the head is healthy on structure.
Selection was query-blind there, but the head's input was not: §1.5's marker
identifies on-path nodes and was inside the pool the head read. The masked run
is the uncontaminated version of that measurement.

**What a kill would require, and why half of it is already dead.** For "learned
graph reading is not viable on this generator" one needs *both* that the head
cannot read a route-complete examined set *and* that no non-learned policy
reaches high route-completeness at a feasible budget. The second half is already
falsified by measurement: `relation_walker_examined_set`, a model-free
relation-follower under the model's own expansion mechanics, is route-complete
on 1124/1124 gated episodes at B = 64 and 1112/1124 at B = 32
(`model_input_audit.json`). Navigation here is *computable*; it never has to be
learned. A negative band therefore reallocates the learned capacity — to the
head, and to the INCLUDE/INSERT decisions of §2.6 where structure genuinely
underdetermines the answer — rather than closing the programme.

**The per-L table already discriminates the two failure modes.** Because edge
targets cover only examined edges, a wrong branch at depth 2 means the on-route
edges at depth ≥ 3 are never supervised: bad walk → no signal → bad walk. That
exposure-bias loop and a plain inability to learn "score high iff this edge's
relation matches the query at this depth" have different signatures in §4 of the
report, which is computed either way:

- failures concentrated at L = 5 and L = 6 with L = 2–4 matching the walker →
  exposure bias; the fix is supervision (walker-forced examined sets, scheduled
  sampling), not architecture.
- failures spread uniformly across L → the local rule itself was not learned
  from direct supervision, which is a much starker statement about this scorer.

**Limits in both directions.** This generator is easy in exactly the way that
makes navigation computable: query relations are distinct within a query,
out-degree is 3, and the gated relation-prefix tree has median 5 and max 16
edges (walker examined set: median 12, p95 27, max 45; 35.4 % of all edges carry
an in-query relation; a route state has a same-relation distractor 9.1 % of the
time, 0 % at the final step by construction). Band A would therefore not
establish that a learned walker survives a real graph's ambiguity, and band D
would not establish that one cannot exist — only that this scorer did not learn
the easy case within 9,376 updates. Both readings are about the frozen
architecture on a synthetic corpus, and §1.6's knob grid is where the ambiguity
profile would have to be raised before either reading generalises.

# 2.9 What "slow, high-accuracy memory" implies, given 1.8

The design goal this experiment serves is a *compute-intensive, slower,
high-accuracy* memory: it is allowed to spend time and FLOPs per query in
exchange for being right. §1.8's 47 % is a poor number, but read against that
goal it locates the problem rather than condemning the programme, in three
steps.

**1. The deficit is in the reader, and the reader is one attention layer.**
`forward_direct` encodes each retrieved edge independently, applies
`joint_attention` **once**, takes a softmax-weighted mean of the 128 edge
vectors, and sends `[state, summary]` through a two-layer MLP
(`model.py:175`). Of the model's 10,257,937 trainable parameters, the entire
read path is 1,050,624 (one `MultiheadAttention`) plus 533,008 (the answer
head); the rest is spent encoding edges and scoring them. One attention layer
is roughly one hop of message passing. Identifying the answer requires knowing
which retrieved edge terminates a path whose relation sequence matches the
query — an L-hop composition for L = 2…6. The architecture cannot express it.

**2. The flatness in depth is the signature that it is not composing.**
`exact | route-complete` at L = 2 / 3 / 4 is 47.3 / 50.7 / 50.4 % (seed 1729;
the other two seeds agree). A reader composing hop by hop would degrade with
depth. A flat line is a depth-independent heuristic — such as "attend to edges
carrying the query's last relation and report the target's mask", which needs
no path at all, and for which there are a median of 12 candidate edges in the
pool. The similarity marker short-circuits the gap: it labels on-path nodes
directly, so one pooling step suffices, which is why the same architecture on
the same examined sets reaches 98.68 % with the field present. That the model
is not composing is well supported; *why* it is not is answered in 3, and is
not the shallow-reader story this section first proposed.

**3. Superseded by measurement: the reader cannot see the graph at all.**
The paragraph that stood here argued depth was the leading explanation and that
more attention layers were the fix. Measurement contradicts it, and the real
constraint is upstream of depth. `model.py::_edge_batch` encodes each edge as
(source assertion mask, target assertion mask, relation embedding, query state,
similarity scalar) — **no node identifier of any kind**. Two edges in the pool
therefore cannot tell whether one's target is the other's source except through
a 4-bit mask. `scripts/read_run_adjacency_ambiguity.py`, run on screen-g00,
gated non-abstain, n = 1124, B = 128:

| quantity | min | median | mean | max |
|---|---|---|---|---|
| distinct nodes touched by the 128-edge pool | 53 | 88 | 84.88 | 108 |
| distinct assertion masks among those nodes | 13 | 15 | 14.94 | 15 |
| nodes sharing the target node's mask | 2 | 7 | 7.70 | 17 |
| candidate continuations of a route step under `(source mask, relation)` | 0 | 2 | 2.14 | 8 |

Over 5,518 route steps the true continuation is uniquely identifiable **28.33 %
of the time**; the rest of the time two or more pool edges are, to this model,
the same edge. A path cannot be composed over a relation the input does not
express, at any depth. **Depth is not the binding constraint; the edge encoding
is.** (The pool touches ~88 nodes carrying ~15 masks — roughly six nodes per
mask — so the collision is structural, not incidental.)

This also explains why the deficit is specific to the set reader. TRAV never
infers adjacency: its walk expands the chosen edge's target mechanically and its
GRU state carries the traversal, so connectivity is supplied by the control flow
rather than recovered from the encoding. §1.8 should therefore be read as a
result about *a set transformer over edges with no structural encoding*, which
is exactly the configuration a graph transformer is defined in contrast to — not
as a result about attention-based readers in general.

**Consequence for sizing, in the right order.** Reallocating the parameter
budget from width to depth is the correct instinct — a transformer block costs
about 12d², quadratic in width and linear in depth, so at d = 256 a block is
≈ 786 K parameters and eight of them ≈ 6.3 M, comfortably inside the current
10,257,937 — and 512/1536 is over-provisioned for 16 relation types and 4-bit
masks. But spent before the encoding is fixed it buys nothing. The order is:

1. **Make adjacency representable.** Either an attention bias/mask that connects
   edge A to edge B when `target(A) == source(B)` (costs ~no parameters and is
   exact), or episode-local node identity embeddings. This is the step that
   makes a reader a *graph* transformer rather than a set transformer.
2. **Then depth**, sized to the task: paths here are at most six hops, so about
   six to eight layers, with residual connections and pre-LayerNorm around each
   block — the current single block has **neither** (`joint_attention` is
   applied raw), so stacking it as-is would degrade rather than compose.
   Over-smoothing across a 128-token set is a real risk past roughly that depth
   and is the reason to stop there rather than go deeper.
3. **Then trim width**, which is where the parameters for (2) come from.

**And the strategic conclusion: do not learn what can be computed.** On this
generator the whole read task is exactly solvable without a model. The relation
walker is route-complete on 1124/1124 gated episodes at B = 64, and generation
enforces that the only complete relation-matching paths are the two planted
routes — `ceiling_sweep.json` records `reached_outside_targets_violations: 0`
and `relation_tree_not_route_complete: 0` — so enumerating those paths yields
the target nodes exactly, and comparing their assertion masks yields the answer
or the abstain. A deterministic algorithm scores 100 % here. That reframes what
these runs are: a **substrate test** of whether the frozen architecture can
learn a capability we can already compute, not a product benchmark. A learned
reader at 47 % is a weak showing for the architecture and says little about
whether a graph memory can be accurate.

**What the goal actually licenses.** A slow, high-accuracy memory is exactly the
setting in which the deterministic half should be kept and the learned half
narrowed:

- *Retrieval* is deterministic and exact here (the walker), so spend the budget
  on recall, not on learning to navigate.
- *Verification* is structural: whether a proposed route's relations match the
  query and its edges exist is checkable without labels, at inference, with no
  model. A weak reader inside a propose-and-verify loop is a different system
  from a weak one-shot reader, and the compute budget is what pays for the
  loop.
- *Learning* then earns its place where structure genuinely underdetermines the
  answer — ambiguous relation graphs where the walker's tree explodes (§1.6),
  and the INCLUDE/INSERT decisions of §2.6, which have no deterministic
  solution at all.

None of this is established by §1.8; it is the design reading §1.8 supports and
the reason a 47 % one-shot reader is not by itself a verdict on the programme.

# 2.10 A concrete specification for a successor reader

The actionable content of 1.8, 2.8 and 2.9, gathered in one place. This is a
design proposal, not a result: nothing in it has been built or measured, and the
only *measured* claim it rests on is 2.9's — that the current edge encoding
fails to identify a route's continuation on 71.67 % of route steps. The frozen
v1 contracts pin the existing model, so this is a successor experiment, never an
edit to `training-config.v1.json`.

**Two representation defects to fix before any capacity change.**

1. *Adjacency is not expressed.* Give the reader a token per edge and a hard
   attention bias: edge A may attend to edge B when `target(A) == source(B)`.
   This is exact, costs approximately no parameters, and is computed from the
   visible payload the model already receives. The alternative — episode-local
   random node-identity embeddings, so `target(A) == source(B)` is recoverable
   by dot product — is softer, must be re-randomised per episode to avoid
   memorising node numbers, and asks the model to learn something the bias
   simply states. Prefer the bias; it is the same "do not learn what can be
   computed" rule as 2.9's.
2. *The query has no per-hop resolution.* `_query` returns `state[-1]`, the GRU's
   final hidden state, and `_edge_batch` broadcasts that single vector to every
   edge. To align hop k of a path with relation k of the query, the reader needs
   the ordered relation sequence, not a summary of it: cross-attention from edge
   tokens to per-relation query tokens. Without this the model cannot tell which
   relation it is currently supposed to be matching, which is a second, separate
   reason path composition is not expressible today.

**Then the shape, which is where the width/depth trade lands.** Depth sized to
the reasoning diameter rather than to model scale: paths here are at most six
hops, so six to eight blocks, one hop each, with residual connections and
pre-LayerNorm — the current model applies `joint_attention` raw, with neither.
Width can fall a long way to pay for it: an edge's information content is a
relation from 16 types, two 4-bit assertion masks, and a query-position signal,
so d = 128–256 is ample where the frozen model uses 512 hidden and 1536 edge-
hidden. At d = 256 a block is ≈ 786 K parameters and eight of them ≈ 6.3 M,
against the frozen model's 10,257,937 total — deeper *and* smaller.

**Feed it the walker's set, not the BFS pool.** Retrieval is already exact and
model-free: `relation_walker_examined_set` is route-complete on 1124/1124 gated
episodes at B = 64, with a median examined set of 12 edges (p95 27, max 45)
against the pool's 128. That is an order of magnitude fewer tokens, far fewer
mask collisions, no distractor swamping, and much less over-smoothing pressure
across the stack — and it keeps the learned capacity on composition rather than
on search. It also makes the "compute-intensive" budget cheap to spend: twelve
tokens through eight blocks is nothing, which leaves the budget for the loop
below.

**Wrap it in propose-and-verify.** A proposed route's validity — its relations
match the query in order and its edges exist — is checkable at inference with no
model and no labels. A reader that is right 60 % of the time inside a
propose-verify-retry loop is a different system from a 60 % one-shot reader, and
this is the mechanism by which "slower" converts into "higher accuracy". The
verifier already exists in `evaluation.py`; what is missing is a reader that
proposes routes rather than emitting a class directly.

**And evaluate it somewhere the answer is not already computable.** On this
generator the task is exactly solvable without a model (2.9), so a successor
reader scoring well here demonstrates only that it learned what an algorithm
does. The measurement that would mean something is the ambiguous regime — the
knob settings of §1.6 where the relation-prefix tree grows and the walker stops
being a sufficient policy — plus the INCLUDE/INSERT decisions of §2.6, which
have no deterministic solution at all. Building the reader without also raising
the generator would produce a good number and no information.

**What the running TRAV arm still decides.** TRAV supplies adjacency through its
control flow rather than its encoding, so it is the one architecture in this
experiment not affected by 2.9's defect. If TRAV-nosim navigates without
similarity, a recurrent walker remains a live alternative to a structure-aware
reader and the two should be compared. If it does not, the structure-aware
reader above is the remaining candidate and the walk is not worth learning.

# 2.11 Does a transformer traversal design have merit?

Asked directly, 2026-09-02, with TRAV-nosim about 40 % of the way through its
9,376 updates and therefore unread. The answer below is an architectural
argument from code and from the measurements in 1.8, 2.9 and the audit; the
empirical half is still running and is named at the end.

**Yes — and on the present evidence it has more merit than the set-reader
design.** Five reasons, in descending order of how well each is evidenced.

1. *It gets adjacency for free.* This is the decisive one. 2.9 measured the set
   reader's fatal defect: the true continuation of a route step is uniquely
   identifiable from the model's inputs on only 28.33 % of steps, because edges
   carry no node identity. A walker never infers adjacency — it moves to the
   chosen edge's actual target and expands that node's actual out-edges.
   Connectivity is supplied exactly by the environment. The one thing measured
   to be structurally impossible for the reader is free for the walker.
2. *The decision is local and tiny.* Out-degree is 3, so each expansion scores
   three candidates against "does this relation match what the query wants
   here". The set reader must instead locate one edge among 128 by global
   composition.
3. *It is roughly ten times cheaper in examined edges, at higher coverage.* The
   model-free relation walker is route-complete on 1124/1124 gated episodes at
   B = 64 with a median examined set of 12 edges (p95 27, max 45); the BFS pool
   reaches 87.90 % at 128. Traversal is the more budget-efficient shape of the
   two by an order of magnitude.
4. *It is the only one of the two with a story for graphs that cannot be
   pooled.* A set reader needs a retrieval policy that returns a bounded,
   route-complete neighbourhood. On an ambiguous real graph the relation-prefix
   tree grows past any fixed budget (§1.6 is where that is knobbed), and pooling
   a million-node store is not an option at all. Pruning *during* the walk is
   the mechanism that keeps the examined set small, and only a traversal design
   has it.
5. *It emits the verifiable object.* A walk produces a route, whose validity is
   checkable at inference without labels; a set reader emitting a class produces
   nothing to check. §2.10's propose-and-verify loop is native to traversal and
   bolted on to the alternative.

**But the current traversal implementation has three specific defects, and a
transformer version should be understood as fixing them rather than as adding
capacity.**

- *No per-hop query indexing.* `_query` returns the GRU's final hidden state and
  broadcasts it; the controller must decode "the query's k-th relation" from a
  fixed summary plus an implicit step counter carried in `state`. Learnable in
  principle, indirect in practice, and the same defect 2.10 names for the
  reader. A transformer controller should cross-attend to the query's relation
  tokens with an explicit depth, so matching hop k against relation k is a
  lookup rather than a decoding problem.
- *The recurrent state assumes a path that selection does not follow.*
  `_forward_trav_one` accumulates every scored-but-unchosen edge in a global
  `pending` frontier and each step takes the global argmax, so the walk is
  best-first search, not a greedy path — it can and does jump back to an edge
  discovered several expansions ago. That is a genuine strength (a wrong early
  step is recoverable within the budget), but `state` is updated as
  `state_cell(chosen_edge_representation, state)` in *jump order*, so after a
  jump the controller's state describes a history that is not a path in the
  graph. A frontier-scoring transformer should condition each candidate on
  **its own** prefix — its depth and the relations along the path that reached
  it — rather than on the order in which the search happened to visit things.
- *Supervision covers only what was examined.* `_edge_targets`
  (`training.py:146`) labels an edge 1 iff it lies on a valid route, over the
  examined set only, so a wrong branch means the deeper route edges are never
  supervised: bad walk → no signal → bad walk. This is traversal-specific — the
  set reader's pool is fixed and its edge supervision is stable — and it is the
  most likely training pathology if TRAV-nosim reads poorly. The fix is
  supervision, not architecture: mix teacher-forced examined sets (score the
  model-free walker's set) with on-policy ones, i.e. scheduled sampling.

**What the running arm decides, and what it does not.** TRAV-nosim measures
whether *this* implementation learns to navigate without the similarity marker.
A poor result is evidence about the three defects above, not about traversal as
a design, and §4 of the screening report separates the two cases: failures
concentrated at L = 5–6 with L = 2–4 matching the walker indicate the
supervision loop, while failures flat across L indicate that the local
relation-matching rule itself was never learned. Only the second would be an
argument against the design, and even then it would be an argument against
learning a policy that §2.9 shows can simply be computed.

# 2.12 The common root: destructive state, and what replaces it

All three defects of §2.11 are the same defect. The traversal controller carries
a mutated hidden vector — `state = state_cell(chosen_edge_representation, state)`
— and every problem follows from compressing an exactly-known, discrete history
into an order-dependent latent.

- The query's k-th relation is hard to reach because the query was compressed to
  `state[-1]` and the depth lives implicitly in how many times the state has
  been updated.
- The path/jump incoherence exists because the state mutates in *visit* order
  while selection is best-first over a global frontier.
- Scheduled sampling is awkward because a teacher-forced trajectory and an
  on-policy one produce different states, so the state itself is off-policy;
  the supervision problem is partly a state problem.

**A fourth symptom, from the same cause, not previously recorded.** Frontier
scores are computed once, at expansion time, under whatever `state` held then
(`model.py:216`), stored in `pending`, and never revised. The selection step
`max(pending, ...)` then compares an edge scored at step 2 against an edge
scored at step 9 — two numbers produced by different functions, because the
controller state differed. **The frontier's scores are not commensurable.** This
is not a subtle inefficiency; it means best-first selection is ordering
candidates by a quantity whose units drift as the walk proceeds, and it is
caused entirely by conditioning the score on a mutated state.

**What replaces it: append-only context, not a smaller state.** The traversal
history here is not hidden and not large — at most six hops, at most 128 scored
edges, each with a known depth, relation, and prefix. Compressing that into 512
mutated dimensions discards structure that is available exactly, which is the
same error §2.9 identifies in the edge encoding. The successor's step function
should be a *pure function of facts*:

- tokens for the query's relation sequence, indexed by position;
- tokens for the examined edges so far, each carrying its own depth and the
  relations along the path that reached it;
- tokens for the current frontier candidates, scored under a context that makes
  their scores comparable — §2.14 shows this is achieved by scoping the context
  to each candidate's own path rather than by re-scoring the frontier, which is
  what an earlier revision of this section proposed.

The distinction that matters is **append-only versus destructive**. A KV cache
or a token sequence is still state, and still O(1) to extend, but it preserves
the history exactly and is invariant to the order the search happened to visit
things; a GRU cell overwrites. "Stateless" here means no *mutated* state, not no
context — the model must still see what it has examined and where the frontier
is, or it cannot know the search's progress.

Every §2.11 defect dissolves rather than being patched: depth becomes a lookup
against an indexed query; jump order stops mattering because each candidate is
scored from its own prefix rather than from the walk's history; teacher-forced
and on-policy examined sets become interchangeable inputs to the same function,
which makes scheduled sampling a data decision instead of an architectural one;
and the frontier becomes commensurable because each candidate is scored under
its own path rather than under the walk's history (§2.14).

**Cost, and why this setting can afford it.** Re-attending over the prefix and
frontier at every step is O(frontier + prefix) per step instead of an O(1) state
update, and quadratic in path length over a whole walk. At ≤ 6 hops and a
frontier of ≤ 45 edges (the walker's max examined set; median 12) this is
negligible, and it is precisely the recomputation a compute-intensive,
higher-accuracy memory is meant to buy. The trade only reverses for walks
hundreds of hops long, which is not this regime — and even there the answer is
caching the append-only context, not reinstating a destructive one.

Unmeasured: nothing in this section has been built or run. The measured inputs
to it are §2.9's adjacency figures and the code cited above.

# 2.13 Is a graph-wide KV cache viable at 50,000 nodes?

Two different things get called a KV cache here and they have opposite viability
profiles. All figures below are arithmetic under stated assumptions — bf16, K and
V of width d per node per layer, out-degree 3 so 150,000 edges at 50,000 nodes —
not measurements. Nothing in this section has been built or benchmarked.

**The traversal context cache is a non-question.** The tokens a walk appends for
one query — the query's relations, the examined edges, the frontier — number in
the low hundreds at ≤ 6 hops and ≤ 128 examined edges. It scales with the walk,
not with the store. Viable at any graph size, and it is what §2.12 actually asks
for.

**The graph-wide cache is the real question, and for reads the answer is yes.**

| d | layer-0 embeddings only | full 8-layer node KV | dense attention/query | adjacency-sparse/query |
|---|---|---|---|---|
| 128 | 12.2 MiB | 195.3 MiB | 20.48 GFLOP | 0.614 GFLOP |
| 256 | 24.4 MiB | 390.6 MiB | 40.96 GFLOP | 1.229 GFLOP |
| 512 | 48.8 MiB | 781.2 MiB | 81.92 GFLOP | 2.458 GFLOP |

Dense figures assume ~100 traversal tokens attending over all 50,000 nodes at
every one of 8 layers; sparse figures assume one message per edge per layer.
A few hundred MiB of cache and one to forty GFLOPs per query is small — on the
order of a millisecond of consumer-GPU compute, with the cache read likely
dominating and amortising across batched queries.

**Which forces an uncomfortable observation: at 50,000 nodes, traversal is not
required by compute.** You can attend to the entire store. The scale at which
walking becomes necessary for *reads* is 10⁶–10⁹ nodes, not 10⁴·⁷. Traversal
still earns its place at this size for three reasons that are not about read
cost, and they should be the stated justification rather than efficiency:

1. **Headroom.** The design should not have to be rebuilt when the store grows
   two orders of magnitude.
2. **The verifiable object.** A walk emits a route, checkable without labels
   (§2.10); dense attention emits a distribution over the store, checkable
   against nothing.
3. **A small, precise candidate set for the write path.** This is the strongest
   one. INCLUDE/INSERT (§2.6) needs a handful of candidates a verifier or a
   human can adjudicate, not a soft attention map over 50,000 nodes. The
   walker's median examined set is 12 edges. Read accuracy is not what
   traversal is being kept for.

**The binding constraint is writes, not reads.** A memory system mutates. A
cached layer-ℓ representation of a node depends on layer ℓ−1 of its neighbours,
so one node's change dirties its ℓ-hop neighbourhood at layer ℓ: with 8 layers
and out-degree 3 that is up to 3⁸ ≈ 6,561 nodes per write in the uniform case,
and effectively the whole store once hubs exist. **A multi-layer graph KV cache
is a read-optimised structure that is hostile to the thing this system is for.**

The resolution is to cache only what writes invalidate locally:

- **Cache layer-0 node embeddings** — 12–49 MiB at these widths — where a write
  dirties exactly one entry.
- **Recompute the stack per query over the retrieved subgraph**, which
  traversal keeps tiny (median 12 edges, p95 27, max 45). Eight layers over
  forty-five tokens is nothing, and it composes with §2.12's append-only
  traversal context.
- Reserve a full multi-layer cache for a read-mostly snapshot with periodic
  rebuilds, the way an index is rebuilt, if profiling ever justifies it.

**A separate caveat, about the data rather than the model.** The current
generator produces independent episodic worlds; a persistent 50,000-node store
with many queries against one graph is a different setup, and the Phase 1
sampler, the split discipline, and the leakage argument would all have to be
redesigned around it. That is a larger change than the model work in §2.10–2.12
and should not be smuggled in as an implementation detail.

# 2.14 Path-scoped context: the cache is keyed to the branch, not the walk

The proposal is a KV cache holding the path a traversal has taken so far. It is
the right structure, and it is worth being exact about *which* path, because the
walk is not one.

**There is no single path — there is a search tree.** `_forward_trav_one` keeps
a global `pending` frontier and takes the global argmax, so it routinely jumps
to an edge discovered several expansions ago on a different branch (§2.11).
"The path so far" therefore has three readings: the visit order (what the GRU
state currently encodes, and incoherent for exactly this reason), the actual
prefix from the start node to the candidate being scored, or the whole explored
tree. **The second is the one to cache.** The structure that results is the same
one beam search over an LLM uses: a prefix tree of cache entries, one branch per
frontier candidate, shared ancestors computed once.

**Key the cache by `(node, depth)`, not by node.** `coverage.py` already records
why: a node can sit at several depths on different matching paths, and a cycle
can return the walk to an earlier node at a later depth, which is why
`relation_walker_examined_set` queues `(node, depth)` states. A cache keyed by
node alone would collide two genuinely different traversal contexts.

**Four consequences, and the third is the important one.**

1. *Backtracking becomes free and correct.* Jumping to a frontier edge from
   another branch requires no recomputation and no state surgery: that
   candidate's context is its own cached ancestry, which was written when its
   ancestors were expanded.
2. *Prefix sharing makes it cheap.* All out-edges of an expanded node share
   their entire ancestry. The walker expands a median of 4 nodes to a median
   examined set of 12 edges at depth ≤ 6, so a whole query's cache is on the
   order of tens of entries. Sizing is a non-issue at any store size (§2.13).
3. *Scores become stable, not merely comparable.* If a candidate's score is a
   function of (indexed query, its own prefix, the candidate edge) and nothing
   else, then it never goes stale: it does not depend on what the walk did
   elsewhere or when the candidate was discovered. Best-first selection over
   the frontier is then coherent — it compares numbers produced by one function
   — **without re-scoring the frontier at every step**, which is what §2.12
   originally proposed and is now withdrawn as unnecessary. The
   incommensurability §2.12 identified is a symptom of walk-scoped context, and
   path-scoping removes the cause rather than paying to work around it.
4. *Supervision stops depending on the model's own choices.* This dissolves
   §2.11's third defect by construction. Because scoring is a function of a
   supplied prefix, every route edge can be supervised under its **true**
   prefix regardless of where the model's walk actually went — the "wrong branch
   at depth 2 means the depth-3 route edges are never labelled" loop simply does
   not arise. Teacher-forced and on-policy prefixes become two input
   distributions to the same function, so scheduled sampling is a data mix, not
   an architectural change.

**What is given up.** Path-scoped context means a candidate cannot condition on
what the search found on other branches. An earlier revision of this section
argued that measurement settled the trade — that the optimal policy is local,
since `relation_walker_examined_set` consults nothing but the query's relation
at the current depth and is route-complete on 1124/1124 gated episodes at
B = 64. **That argument was wrong, and §2.15 replaces it.** Local context is
sufficient to be route-complete *at a budget of 64*; it is not sufficient to be
budget-*efficient*, and budget efficiency is the whole justification for
traversal (§2.11). Read §2.14 as the right cache *structure* and §2.15 as the
correction to its conditioning claim.

Unmeasured: this is a design argument from the cited code and audit figures. No
such model has been built or run.

# 2.15 Cross-branch context: what staleness actually costs

§2.14 concluded that a candidate's score should depend only on its own prefix,
because the known-optimal policy is local. That conclusion does not survive
contact with the task, and the objection is worth recording because it changes
the design rather than decorating it.

**Every episode has two targets, and coverage is inherently cross-branch.**
`route_coverage` defines `route_complete` as `reached >= targets` — reaching
*every* target, not one — and generation plants exactly two routes per episode
(2,248 target nodes over the 1,124 gated episodes). A traversal is therefore not
searching for *a* path; it is trying to cover a set. Whether a given expansion
is worth its budget depends on which targets are already reached, which is
precisely the information path-scoped context withholds.

**And the measurement I cited does not support the claim I made with it.** The
relation walker is route-complete on 1124/1124 at B = 64, but 1112/1124
(98.93 %) at B = 32, 836/1124 (74.38 %) at B = 16 and 335/1124 (29.80 %) at
B = 8. A purely local policy is route-complete only once the budget is generous
enough to expand every node reachable by a matching prefix, dead ends included.
It is *not* budget-optimal, and budget efficiency — a median 12-edge examined
set instead of a 128-edge pool — is exactly what §2.11 keeps traversal for. A
policy that knew "target A's branch is already covered, spend what is left on
the other" would beat the walker at small budgets, and no path-scoped scorer
can express it.

**So the real question is not local versus global, but how often the global
context changes.** Staleness costs one re-score of the frontier per change. The
facts a scorer would want from other branches are discrete and rare, not
continuous: a complete matching path was found, a subtree was exhausted, a
second endpoint was reached. That is a handful of events per query — bounded
below by the two targets — not one per expansion step. The current design pays
staleness on *every* step because it conditions on a state that mutates on every
step; a design that appends cross-branch facts only when they occur pays it a
handful of times.

**Concretely, split the score.** A stable term `f(indexed query, own prefix,
candidate edge)`, cached in the prefix tree of §2.14 and never recomputed, plus
a cheap term `g(coverage so far)` evaluated against the current global context.
Only `g` is re-evaluated, and only on the events above; `f` — the expensive
part, carrying the path — stays cached and shared across siblings. This is the
familiar shape of a search heuristic: a stable path cost and a dynamic estimate
of what remains. Selection stays commensurable within a round, and rounds are
few.

**One thing that does *not* argue for a global scorer.** The abstain decision —
whether the two endpoints share an assertion mask — is cross-branch, but it is
made by the answer head, which already pools over the entire examined set at the
end of the walk. Global context is needed by the *scorer* for budget allocation,
not for the answer. Keeping those two arguments apart matters, because only the
first justifies paying for re-scoring.

Unmeasured: no scorer of either shape has been built. The figures above are from
`model_input_audit.json` and `coverage.py`, and the design conclusion is an
argument, not a result.

# 2.16 A router or a threshold: where it belongs, and what it must not be

Both are worth having, but they answer different questions, they are only
meaningful *after* §2.14 fixes score commensurability, and one of them collides
with this project's governance in a way worth naming before it is written into a
config.

**Sequencing first: a threshold on an incommensurable score is meaningless.**
§2.11 and §2.12 established that the current frontier scores are produced under
different controller states and are not comparable to one another. A stop rule
or a routing rule reading such a score is reading a quantity whose units drift
as the walk proceeds. Path-scoped, stable scores (§2.14) are a precondition, not
an alternative.

**The highest-value threshold is a stop rule, and its payoff is precision, not
compute.** `_forward_trav_one` loops `while len(all_ids) < budget` and raises if
the frontier empties first, so **TRAV always examines exactly the full budget**.
Measured on screen-g00, gated non-abstain, n = 1124:

| examined set | median precision | mean precision |
|---|---|---|
| relation walker (median 12 edges, stops when the tree is exhausted) | 0.417 | 0.405 |
| TRAV at a fixed B = 128 | 0.039 | 0.040 |

There are a median of 5 distinct on-route edges per episode (mean 5.07). A walk
that stops when it is done is an order of magnitude more precise than one that
spends its budget regardless, at equal or better route-completeness. Since
selection precision is what the write path will consume — a verifier or a human
adjudicates a handful of candidates, not 128 — this is the single largest
available improvement in the traversal design, and it is a stop rule, not a
bigger model.

**Prefer a computed stop rule to a learned one, on the same principle as
everywhere else.** "Stop when every discoverable complete matching path has been
found" is computable from structure on this generator: it is what
`relation_walker_examined_set` already does when it exhausts the prefix tree,
and it needs no threshold at all. A learned router earns its place exactly where
that computation blows up — an ambiguous graph whose prefix tree outgrows the
budget (§1.6) — which is the same boundary that justifies learned traversal in
the first place.

**A router is safer than a threshold here, for a governance reason.**
`training-config.v1.json` sets `selection.threshold_tuning: false` and
`model_selection: false`, and records `budget_source:
coverage_only_before_screening_accuracy` — the existing budget was derived from
coverage *before* anyone looked at screening accuracy, precisely so it could not
be tuned. A scalar threshold chosen by looking at screening or holdout results
is the selection this experiment is built to forbid. A router whose parameters
are trained by the loss is not selection against a metric and does not have that
problem. If a scalar is used anyway it must be derived structurally, in the same
way and with the same disclosure as the budget was, and fixed before the data it
will be read against exists.

**And be honest that a learned stop rule moves the knob rather than removing
it.** Stopping early is only rewarded if the loss rewards small examined sets
subject to route-completeness, which is a two-objective problem whose weight is
a hyperparameter — a threshold wearing a different hat. The defensible version
of that weight is again a structural derivation or a preregistered value, not a
sweep. The routing trigger of §2.15 is the cheaper case: re-score when the top
two frontier scores are within a margin, which is uncertainty-triggered
computation and needs no accuracy-derived constant.

Unmeasured: no router, threshold or stop rule has been built. The precision
figures above are measured; everything else in this section is design argument.

# 2.17 Examined is a cost, returned is a product — and I conflated them

Raised by Cameron on 2026-09-03 while the Track O runs were launching: is
precision low because the walk *returns* everything it traverses, and should the
model be able to traverse a node without returning it? The observation is
correct and the distinction is one this project has been measuring past.

**Two different quantities wore one name.** "Examined-set precision" is
`on-route edges ÷ edges examined`. Expanding a node examines all of its
out-edges, because that is what reaching a node costs under the model's
mechanics — and under the walker's, and under v1's. So the denominator is a
**cost**: what the policy paid to look. It is the right metric for budget
efficiency and it is why v1's always-spend-the-budget walk is capped near 0.04.
It is *not* a measure of what the traversal asserts is relevant.

The quantity a write operation actually adjudicates is the **returned set**:
what the traversal hands downstream as its answer. Nothing forces those to be
the same set, and on the Track O generator they are far apart — the walk
examines a median 37 edges on the hard cell while the two planted routes total
about five.

**The model already has a returned set, and it is trivially precise.** M5 makes
the walk emit its routes directly. On a proof-valid episode those routes are
exactly the on-route edges, so their precision is 1.0 by construction and the
quantity degenerates into `proof_valid`, which is already the primary coverage
metric. Reporting it as "returned precision" would be measuring nothing new.

**The version with content is a graded relevance decision, and the edge head is
already trained to make it.** The edge loss is binary cross-entropy against
"this edge lies on a valid route", so the scorer is a relevance classifier
whose natural decision boundary is a positive logit — τ = 0 is the loss's own
boundary, not a tuned constant, which matters because
`selection.threshold_tuning: false` forbids fitting one to a screening result.
That gives a threshold-free returned set:

    returned = { examined edges whose edge logit is positive }

with **returned precision** = on-route ÷ returned and **returned recall** =
on-route returned ÷ on-route total. A traversal that examines 37 edges and
returns 6 of which 5 are on route has done something the examined-set number
cannot express: it looked broadly and reported narrowly.

**What this changes, and what it deliberately does not.** The Track O
preregistration was committed before the runs started and its primary
quantities stand; the band is read on route-completeness and examined-set
precision as written, and no result will be read against a metric invented
after the fact. Returned precision and recall are **descriptives, declared here
before any run reaches its read point**, and they are computable from the saved
checkpoints after the fact — the edge logits are already produced for the loss,
so no running run needs restarting and no reading rule moves.

**For the next iteration this is a design change, not a metric change.** Making
the model *selectively aware* — free to traverse without returning — means
giving the returned set its own objective rather than reading it off the edge
head as a side effect: a stop-and-report decision per examined edge, trained
against route membership, with the walk's cost and the report's precision as
two separate terms. That is the shape the insert objective wants, because
INCLUDE/INSERT consumes a small adjudicable candidate set, and it is the first
place where "traverse widely, report narrowly" becomes an objective the model
is optimised for instead of a property it happens to have.

# 2.18 The answer path is diluted, and the walk is not — observed mid-run

Observed 2026-09-03 at update 1,500-2,000 of the Track O runs, recorded before
the read point at 8,000 and before any band is read.

**The two halves separated cleanly, and only one of them works.** Edge loss falls
from 0.79 to 0.05 within a hundred updates: the walk learns almost immediately,
and route-completeness and examined-set precision move with it. Answer loss sits
at ln(16) = 2.77 for well over a thousand updates with the head emitting a single
class (modal fraction 1.000, one distinct class, entropy 0), and only begins to
differentiate around update 1,500-2,000.

**It is not a bug.** The head's input is `[LayerNorm(summary) (256), endpoint
mask bits (8), agreement (1), route-count one-hot (3)]`, and the endpoint bits
were checked directly against the label: `recovered_from_extras == gold` on every
episode tested. The answer is present in the input, in eight bits, exactly where
it should be.

**It is a dilution.** Those eight bits sit beside 256 dimensions of
softmax-weighted edge-token summary which carry route *structure* and say nothing
about the answer class — assertion masks are deliberately not in the candidate
features, because they are the label. So the head must learn to suppress a
256-dimensional distractor to read an 8-bit signal, and at standard
initialisation the distractor dominates. It gets there, slowly, once the edge
loss saturates and the answer term starts to dominate the gradient.

**Why the runs continue anyway.** Track O's primary quantities are
route-completeness and examined-set precision, both of which come from the walk
and are unaffected; exact-set accuracy is a descriptive whose failure is band G,
reported *beside* the letter and explicitly not suppressing it. That split was
written into the preregistration before any run started, precisely so a weak head
could not make the navigation measurement unreadable. Changing the architecture
now, after seeing partial curves, is the adaptive move the discipline forbids —
and it would invalidate the untrained reference line, which was measured for this
exact architecture.

**The fix, for the next iteration.** Give the answer its own path rather than
making it compete with the walk's summary: read the endpoint masks through a
dedicated small head and combine at the logit level, so the answer does not
depend on the summary suppressing itself. This is the same shape as section 2.17's
selective-return change — both are cases of one representation being asked to
serve two purposes, and both are fixed by giving the second purpose its own
parameters rather than a larger share of the first's.

# 2.19 The supervision schedule starved the answer head — a third dilution

Found 2026-09-03 at update ~4,150 of the Track O runs, while checking whether the
hard cell's answer head was failing. It was not; it had barely been trained on
the input it is evaluated on.

**The mechanism.** `model_v2.forward` has two paths. On-policy, the walk runs its
frontier, reaches endpoints, and fills `endpoints` and `routes`. Under supplied
prefixes — the M6 `gold` and `walker` phases — it replays the supplied expansions
and `continue`s past the frontier block entirely, so `routes` comes back empty
and `stop_reason` is `tree_exhausted` on every episode. Verified directly:
on-policy returns 2 routes per episode, `gold` and `walker` return 0.

The answer head's input is `[LayerNorm(summary), endpoint mask bits (8),
agreement, route-count one-hot]`. With no endpoints those twelve dimensions are
**identically zero**. So for the first half of training — the preregistered
schedule puts `gold` on [0, 0.25] and `walker` on [0.25, 0.5] — the head learned
to answer from the 256-dimensional summary alone, with the eight bits that
actually carry the label held at zero, and only met its real input at update
4,000.

**The evidence is unusually clean.** Easy-cell exact accuracy per checkpoint:
0.019 at 3,500, 0.040 at 4,000, **0.989 at 4,500**. The schedule switches to
on-policy at 4,000 and the jump lands in the next checkpoint interval, on all
three seeds. Nothing else changes at that update.

**Consequence for the run in flight.** The primary quantities are untouched:
route-completeness and examined-set precision are computed from the walk's own
examined set under on-policy screening, and the edge loss — which drives the walk
— gets correct targets under every supervision source. What is compromised is the
head's *effective* training budget: it is 4,000 updates, not 8,000. That belongs
in the report as a stated limitation of the accuracy reading, not as a reason to
discard it, and band G was already the preregistered home for a floor failure.

**The fix, and the pattern.** The supplied path should still run the frontier so
that supplied and on-policy produce the same answer-head input; teacher forcing
should change *which prefixes are scored*, never *what the head sees*. That is a
one-branch change and it is not made mid-run.

More usefully, this is the third instance of one pattern in as many days:
section 2.17 (returned set read off the edge head as a side effect),
section 2.18 (answer competing with the walk summary for the same 256
dimensions), and now the answer head's input silently changing shape with the
training phase. Each is a representation asked to serve two purposes, and each is
fixed by giving the second purpose its own parameters and its own guaranteed
input rather than a share of the first's. The successor design should treat
"every training mode presents the head an identically-shaped input" as an
invariant with a test, in the register of the visit-order invariance test that
already guards `f`.

# 2.20 Exact accuracy is nearly a restatement of route-completeness

Audited 2026-09-03 at update ~5,000 of the Track O runs, prompted by Cameron
asking whether the results were "a bit too well". Two checks; the first came
back clean and the second found something that changes how the report reads.

**No contamination.** Train and screen share zero episode ids, zero
paired-world ids and zero identical visible payloads, on both cells
(16,432/1,652 and 20,000/2,000). The splits are disjoint worlds, as the
derivation labels intend.

**But the headline number is not independent evidence.** Conditioning accuracy
on the walk succeeding — `acc / RC`, the head's hit rate given a correct
traversal — gives 0.994, 0.981 and 0.997 on the easy cell and 0.904, 0.717,
0.906 on the hard one. On the easy cell the head is right essentially whenever
the walk is, and the reason is structural rather than empirical:
`exact_correct = class_correct AND proof_valid`, and `proof_valid` requires the
emitted routes to *be* valid routes whose endpoints are exactly the targets. So
on any proof-valid episode the endpoint assertion masks the head reads are the
gold answer by construction. Given a correct walk, naming the answer is close to
mechanical.

This is not a leak. Assertion masks are public `visible` data, and the model
still had to identify which nodes to read them from — that identification is the
whole task. But it does mean **exact-set accuracy carries little information
beyond route-completeness here**, and a report that leads with 99 % is reporting
the walk twice.

**Consequence for the reading.** The preregistration already made
route-completeness and examined-set precision primary and accuracy a
descriptive, which this vindicates — though for a sharper reason than was
written down. The reason recorded there was that a weak head must not make the
navigation measurement unreadable. The reason found here is the converse and
stronger: a *strong* head must not make the navigation measurement look better
than it is. Both point the same way, and the report should state the acc/RC
decomposition rather than the raw accuracy so the redundancy is visible.

**Consequence for the successor.** If the answer head is to measure anything the
walk does not, it needs a task the walk does not already determine — which is
another way of saying what section 2.6 says about insert: the objective whose
answer is a *set* the traversal has to select, not a value it can read off a node
it already found. Until then, accuracy on this generator should be read as a
consistency check on the walk, not as a second capability.

# 2.21 Selective return belongs in the read contract — Cameron was right

Recorded 2026-09-03. I argued that selective return was an insert-time concern
because on the read path the returned set is the route and `proof_valid` already
scores it. Cameron disagreed: it is fundamentally what makes precision high
enough for relevance, on read. He is right and the argument I gave was reasoning
from this generator's shape rather than from what a read *is*.

**Where my argument failed.** A read in the system being built does not return a
path; it returns the evidence relevant to the query, and which facts are relevant
is a selection the model makes. This generator hides that by planting exactly two
routes and making them the answer, so relevance and route coincide *by
construction*. Designing the read path against that coincidence yields an output
contract of "a path" where it should be "a relevant set", and insert then
inherits the wrong substrate. The coincidence is a property of the task, not of
the capability.

**What follows for the output contract.** The read path should emit a relevance
set as its product, with the examined set remaining its cost. Three quantities,
not one: examined count (what it paid), returned precision and recall (what it
asserts), and route-completeness (whether the evidence actually supports the
answer). The examined-precision ceiling of ~0.20 measured in section 2.16 is a
property of whole-node expansion and cannot be beaten by any reordering of the
walk; only a narrower *report* escapes it.

**What this generator can and cannot measure.** It can measure the classifier
half: thresholding the edge head at a positive logit — the BCE loss's own
boundary, not a tuned constant — gives a returned set that is not trivially the
routes, because the classifier errs. Returned precision and recall are therefore
real numbers here, and are computed post hoc from the Track O checkpoints as the
section 2.17 descriptive.

It cannot measure the judgment half. Scoring "return only what is relevant"
requires evidence that is structurally valid but not relevant — paths a correct
walk may legitimately reach and should decline to return. Generation currently
enforces that the only complete matching paths are the two planted routes
(`cell_audit` records zero reached-outside-targets violations), so no such
evidence exists and the capability has no wrong answer available to it beyond
classifier noise. **A successor generator needs planted distractor evidence:
complete, rule-valid, query-matching paths that are deliberately not targets.**
That is a generator change of the same kind as section 2.6's content rule, and it is
the precondition for relevance being a scored capability rather than an exercised
one.

**Degeneracy, and how to score it without a threshold.** Returning nothing gives
perfect precision at zero recall; returning everything gives perfect recall at
the examined-set precision. Any fixed weighting between them is a threshold
wearing a different hat (section 2.16). Report the precision-recall curve or average
precision, which has no operating point, and leave the training objective as the
per-edge BCE it already is.

# 2.22 The Track O coverage term was never trained — a disclosure

Found 2026-09-03 while designing Track P, and verified three ways before being
written down. It does not overturn band A, but it retires a claim this document
has been making since section 2.15.

**The finding.** After 8,000 updates, every parameter of `coverage_head` is
**byte-identical to its initialisation**, on all three hard-cell seeds (1,153
parameters; checked with `torch.equal` against a model rebuilt from the same
seed). The `score_head` parameters moved, as expected. So the coverage term
received exactly zero gradient for the whole of Track O.

**The mechanism, and it is two lines.** `model_v2.py:1025-1026` appends
`scores[row, column]` — the score head's output, `f` alone — to *both*
`kept_scores` and `stable`, and the edge loss reads `kept_scores`. The coverage
bonus enters only inside the selection `max` at `:1068-1076`, wrapped in
`.detach()`. Detached values have no gradient path, so `g` influenced *which
edge was walked* but never appeared in any loss. Zero input gradient means the
head's weights could not move.

**What this does and does not change.**

- **Band A stands.** It was read on route-completeness and examined-set
  precision, both properties of the walk, and the walk was ordered by `f` plus a
  fixed random `g`. The result is "a learned ordering beats every model-free
  policy", which is exactly what was measured; it simply had one fewer trained
  component than the design claimed.
- **Section 2.15's event-triggered coverage term is unevidenced.** The argument
  for it — that cross-branch coverage information should modulate frontier
  scores — may well be right, but Track O did not test it. The section stands as
  a design argument, not as something demonstrated.
- **`training_v2.py`'s module docstring was false** where it said the loss reads
  "`scores` (the stable term plus the coverage term, as used for selection)". It
  reads the stable term only. Corrected in place.
- It also explains a small puzzle: a randomly initialised `g` added a fixed
  per-depth offset to every frontier score, which is why the walk still behaved
  sensibly. Since `bonus_by_depth` is memoised per epoch, the offset was
  constant within a round and mostly cancelled in the comparison.

**Why it went unnoticed, which is the more useful lesson.** Every test asserted
properties of the *walk* — invariance, stop behaviour, route validity, capacity —
and none asserted that a declared component receives gradient. A parameter that
never moves is invisible to any output-based test. Track P adds the obvious
guard: after a short training run, assert that every module with parameters has
a non-zero gradient at least once, which is cheap and would have caught this on
the first smoke test.

**Consequence for Track P.** The stop head takes `coverage_head`'s place and its
loss is a real supervised term, so the same failure cannot recur silently — but
the gradient-coverage test goes in regardless, because the next component to be
wired in half-way will not announce itself either.

# 2.23 Registering endpoints at examination: three facts the v3 walk forced

Building the model-free walks for Track P (`policies_v3.py`, 2026-09-03) under
the rule "an endpoint registers the moment its final edge is examined" turned
up three facts that the model's stop head and the reading rules have to respect.
Each was found by a failing test or a crashing script, not by reasoning, and
each is now held by a test.

**One expansion can register several endpoints at once.** A node at depth L−1
whose out-edge group holds a target's final edge *and* a sibling distractor's
final edge registers both in the same expansion; a trace on the hard cell
registered four endpoints in one step. Two consequences. A two-endpoint stop
fires at "at least two", never "exactly two", so any feature or label written as
`endpoints == 2` is wrong on v3 data — the stop head reads the raw count. And
"were the first two endpoints the targets" is not a well-defined quantity when
several arrive together; the selectivity question is whether *everything*
registered at the stop is a target (`registered_only_targets`).

**Set-based route-completeness over-credits a stop policy.** `route_coverage`
asks whether both target routes lie inside the examined *set*. A target's final
edge can enter that set because its source node was expanded at a *different*
depth — reached by a shorter matching prefix — while the correct-depth prefix
still sits unpopped in the frontier when the stop fires. Coverage then says
complete; the walk registered one target. The two coincide at exhaustion (every
correct-depth prefix has been popped) and differ only for policies that stop,
which is exactly the case Track P is about. So the ladder records both, and
defines expansions-at-RC, overhead, and gate 1 on **registration** — what a
stop decision can see. The training label for the stop head must be defined
the same way (P-4): a set-based label can be 1 while the model's own endpoint
count is 1, which no structural feature can explain.

**The v1 evaluator caps decoded routes at two.** `decode_best_routes` returns
the best two routes by score — a constant 2 that is harmless on v2 data and
wrong on v3, where a returned set holding three endpoints would be silently
truncated before `proof_valid` saw the third. `evaluation_v3.decode_all_routes`
decodes every complete route in the supplied set and lets `score_prediction`'s
own rule — the supplied routes must be exactly the targets — do the selecting.
Proof-validity on v3 is therefore a statement about the *returned* set (it
contains the targets and nothing else), while route-completeness is a statement
about the *examined* set (it covers the targets, distractors allowed). That is
the cost-versus-product split of 2.17 and 2.21, and neither v1 function changed
to produce it.

A fourth, smaller fact: the lost start-only prototype's rejection rates were far
too pessimistic. Distractors that branch off a target route at a random depth
(2.21's sibling case included) relax node-disjointness to "beyond the branch
point", and the hard cell at K = 2 generates with 0.60 success at 1.36 s per
episode — a 20,000-episode split in about fifteen minutes on thirty cores, with
no mitigation lever needed.

# 2.24 Why v3's distractors are unidentifiable at any γ — two construction facts

Track P's selective return failed (proof-validity 0.117), and the first reading
was that the edge head could not express a route-set comparison. That is true and
Track Q builds the head. But a γ sweep run before Track Q
(`experiments/track_q_v1/diagnostics/gamma_sweep_v3.json`, 1,500 episodes per
cell per bucket, abstain included) says something prior to the model: **on v3
data the planted similarity signal cannot separate a target route from its
distractor at any γ.** Ranking routes by promoted-edge fraction puts the worst
target above the best distractor on 0.382 of hard-cell episodes at γ = 0 and
0.229 at γ = 0.4, with ties between 0.61 and 0.66 throughout. A model given only
that evidence has nothing to learn, and the fact that Track P's trained edge
logits separate on 0.552 means the model was already extracting more than was
planted.

The cause is two properties of the construction, verified directly at γ = 0,
where every target route state promotes a route edge:

1. **The two targets' branch node promotes exactly one continuation.**
   `_assign_similarity_v2` picks one winner per node; at the node where the two
   target routes diverge there are two valid edges and one is promoted. So on
   **100 % of episodes one target route carries an unpromoted edge**, and the
   worst target's promoted fraction is at most (L−1)/L.
2. **A v3 distractor branches off a target at a uniform depth and inherits its
   promoted prefix.** 85 % branch at depth ≥ L−2. A distractor that shares L−1
   promoted edges with a target and adds one unpromoted edge of its own sits at
   exactly (L−1)/L — a tie with the worst target, on 58 % of episodes at γ = 0.

Neither is a function of γ, which is why lowering it does nothing. The
random-branch-depth rule was my refinement of the approved design (2.21 wanted
the sibling case for selective return; it got it, and the sibling case is
precisely what erases the evidence). A simulation I ran before this sweep
predicted separability near 1.0 at γ = 0 because it modelled every target edge
as promoted independently; it missed fact 1 and led me to withdraw a generator
fix on a wrong argument. The sweep, whose rule was written first, corrected it.

**What was left as a discriminator on v3, and why it is not one.** The only
visible evidence that separates targets from a prefix-sharing distractor is the
endpoint assertion mask — the two targets share one when the episode is
non-abstain. That is the answer label. A zero-parameter rule that returns the
largest mask-agreeing group scores 0.929 proof-valid on non-abstain episodes and
0.000 on abstain ones. Selective return on v3 therefore reduces to reading the
label on three quarters of episodes and is unidentifiable on the rest; the
route-mean rule's 0.12 on abstain episodes is roughly that floor.

**Generator v3.2** removes both facts under two switches that default to v3
(byte-identity test): distractors leave from the start node, sharing no prefix;
and distractor interior nodes are promoted at their own rate 1 − `distractor_gamma`,
chosen by a rule written before its sweep. The rule requires identifiability ≥
0.80 with ties ≤ 0.10 while the ladder's gate 1 still holds — the hard-coded stop
must still fail on ≥ 10 % of episodes, or the stop experiment collapses along
with the selection one. Fact 1 is not removed: the worst target still loses the
branch-node tie-break, so at γ = 0.4 it sits near 0.6·(L−1)/L. What changes is
that the distractor no longer inherits anything, so its fraction is set by its own
rate alone, and the gap between the two is now a design parameter rather than an
accident of where it branched.

# 2.25 The stop and the selection want opposite evidence — a structural tension

Generator v3.2 was swept twice, both times under a rule written before the run.
The second sweep (`experiments/track_q_v1/diagnostics/evidence_sweep_v3_2_second.json`,
γ × distractor rate, 1,500 episodes per point) produced a result worth stating on
its own, because it constrains every future experiment on this generator.

**Identifiability is fixable, and was fixed.** Removing the distractor's inherited
prefix (start-node branching) and giving it its own promotion rate takes the
hard cell from v3's 0.229 separability with 0.662 ties to **0.916 with 0.073
ties** at γ = 0.2 with the distractor never promoted. The mechanism runs through a
third quantity the sweep records: the fraction of episodes whose *worst target
route has no promoted edge at all* falls from 0.177 at γ = 0.4 to 0.070 at
γ = 0.2. A target edge is promoted 1 − γ of the time and the branch-node loser has
only L−1 chances, so γ, not the distractor, sets that floor.

**But making the evidence clearer makes the hard-coded stop better.** With the
distractor never promoted, similarity-following reaches the target endpoints
first, so `stop_aware`'s two-endpoint rule registers both targets more often:
0.899 at γ = 0.4, rising to 0.906 at γ = 0.2 and 0.933 at
`distractor_gamma` = 0.8. The ladder's gate 1 asks that it fail on at least 10 %
of episodes, so a *stop* experiment needs the evidence to be ambiguous, while a
*selection* experiment needs it not to be.

**No point on the grid satisfies both**, on the hard cell, at either sweep. That
is not a tuning failure to be swept again with a wider grid; it is a property of
a generator in which one similarity field carries both the ordering signal and the
identifying signal. Separating them would need a second, independent evidence
channel — for instance content that is diagnostic of route membership rather than
merely rule-valid, which §2.24's closing paragraph notes is exactly what the
read-path generators do not currently have and what the insert objective will
need anyway.

The practical consequence for Track Q: it runs at γ = 0.2 with the distractor
never promoted, taking the easy cell as the gate-clean primary and the hard cell
as a disclosed secondary that misses gate 1 by 0.0064. Gate 1 governs the question
Track P already answered; carrying it into Track Q's sweep was the error, and the
relaxation is recorded rather than quietly dropped.

# 3. Open, and deliberately not answered here

- Whether the current architecture can learn relation-following at all under
  stress. The sweep running now is the measurement; it reads at update 8,000
  around 07:00Z on 2026-09-02 and nothing above anticipates its result.
- Whether ablation depth beyond 1 buys anything. Untested.
- What the right precision target is for a write operation. The read query's
  relation-prefix tree is the correct denominator for a read; the relevant
  neighbourhood for an insert is probably not the same set, and this document
  does not assume it is.
- Whether any of the gamma-sweep conclusions survive a second seed. Tier 3
  (seed 2718 at gamma 0.0 and 0.4) is running for exactly this reason.

# 4. Cheap diagnostics identified but not run

- **Partition the existing results by greedy difficulty.** "Did similarity-greedy
  solve this episode" splits the frozen screening set into 929 easy and 195 hard
  with no new data. Re-reading the completed DIRECT gamma curve through that
  partition distinguishes "the noise breaks the shortcut" (collapse concentrated
  in the hard episodes) from "the noise degrades something more general" (spread
  evenly). This is CPU-minutes on data already on disk and would sharpen the
  interpretation of 1.4.
- **Measure the minimum cut between query endpoints** in the generator-knob grid.
  That number is the number of ablation rounds a world can support, and the grid
  already sweeps out-degree, path length, and node count. It would turn the grid
  into a direct feasibility answer for 2.2.
