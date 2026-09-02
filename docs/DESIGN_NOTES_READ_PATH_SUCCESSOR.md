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

**The bottom of the curve is where a correct selector would already be.** The
relation-prefix tree — the edges a relation-following walker actually needs — is
min 3, median 5, mean 5.49, p95 10, max 16. A correct selector is route-complete
at B = 16. At B = 16 the real arms reach 30.07 % and 58.19 %. The 128-edge budget
in use exists to compensate for selection failure, and at that budget roughly
96 % of what is examined is irrelevant.

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
