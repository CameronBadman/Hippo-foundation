# TRAV edge-selection diagnostic at gamma=0

**Status: complete. Overall verdict CLEAN.** All six sections computed against
the diagnostic checkpoint, which reproduces the 100.00% model exactly
(9,376/9,376 update records and 21/21 screening evaluations identical to its
reference).

Diagnostic, not preregistered. Screening split only. No holdout is read; the v1
holdout is spent and the v2 holdout does not exist. This emits no training
receipt, no gate evidence, and nothing that resembles a result. It examines
TRAV's behaviour; DIRECT appears only as an explicitly-labelled reference
distribution, and no arm comparison is quoted as a finding.

## Why this exists

TRAV's screening accuracy at gamma=0 accelerated rather than converged:

| U | 1,500 | 2,000 | 2,500 | 3,000 | 3,500 | 4,000 | 4,500 | 5,000 | 5,500 | 6,000 | 6,500 | 7,000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| acc | 76.87 | 75.27 | 79.72 | 79.72 | 82.65 | 82.21 | 83.19 | 88.26 | 91.37 | 96.00 | 98.22 | **99.91** |

An arm approaching an asymptote decelerates. This one accelerated to 1,123 of
1,124 correct with answer loss at 0.0002 — roughly 3,000x below DIRECT's final
0.6068. gamma=0 is the negative control: the condition where the
highest-query-similarity neighbour is on-path at every step, the task is
greedy-solvable, and adaptive traversal is supposed to confer nothing.

**The gap the P0 gates cannot rule out.** All seven gates test what the *data*
exposes, and were written when both arms consumed the same fixed pool. TRAV
selects its own edges through a recurrent state and therefore searches a
strictly larger space over episode structure than DIRECT can reach. Gate 7's
gamma-invariance and gates 2 and 3 concern DIRECT's pool construction and label
leakage into episode bytes; none of them covers "an adaptive policy discovers a
structural regularity a fixed pool cannot exploit."

This is not a prediction that something is wrong. 99.91% is exactly what a
*legitimate* policy should score here, because "follow the highest-similarity
edge" is a complete algorithm at gamma=0. The point is that an accelerating
curve on the control condition is the moment to check, and checking costs a
screening diagnostic rather than a second holdout.

## Predictions, recorded before the data exists

Written while the diagnostic checkpoint run is at roughly 500 of 9,376 updates,
pre-transition, with none of sections 1/2/4-TRAV/5/6 computed. The diagnostic is
to be read against these, not used to explain whatever appears.

**Section 5, shuffled serialization — predicted: accuracy materially unchanged.**
Query similarity is a per-edge property and is order-independent. If TRAV is
chaining similarity, re-randomizing each node's outgoing-edge serialization
order changes which edges are *offered first* but not which edge is *best*, so a
similarity-following policy should be nearly unaffected. A substantial drop
means TRAV is exploiting presentation order, which is not a property of the
graph and would not survive regeneration under a new seed.

**Section 6, ablated query — predicted: accuracy collapses toward the abstain
base rate.** The feature TRAV chains is query-derived
(`query_similarity_ppm`, `model.py:141`), and the query also enters through the
GRU-encoded relation sequence. Zeroing it should destroy the policy. **Retaining
material accuracy without the query is disqualifying**: it would mean TRAV
locates targets from structure alone, which is not the task as specified. At
99.91% and loss 0.0002 there is no ambiguous middle ground left — the model
either depends on the query or it does not.

**Section 1, on-path fraction — predicted: high, and higher on correct
episodes.** A similarity-chaining walker should spend most of its 128 examined
edges on or adjacent to a valid route. Low on-path fraction combined with high
accuracy is the finding that matters: it would mean the accuracy is not coming
from traversal.

**Section 2, first-target-examination step — predicted: concentrated at
moderate steps, not at very early ones.** A 2-4 hop task should not surface the
target within the first handful of examinations if the walk is genuine. Heavy
concentration in the first 16 would mean TRAV reaches targets faster than
traversal should allow.

**Section 3/4, structural concentration and probe — predicted: concentration on
hop distance and possibly relation, and no excess over the class prior on
serialization order, local rank, or global position.** Hop-distance
concentration is traversal working as intended. Concentration on presentation
order carries no semantic information about the target and would be a shortcut.

## Provenance of the checkpoint

Neither existing probe run saved model weights and `screen.jsonl` carries only
aggregate statistics, so no per-episode edge selections existed anywhere. A
second TRAV run was launched at the identical configuration (model seed 1729,
gamma=0, B=128, target 9,376 updates) with checkpoint saving enabled, added to
`scripts/read_run_learning_probe.py` as an opt-in `--save-checkpoint` flag that
does not alter the running probe.

That run is verified bit-identical to the original for its shared prefix — 508
of 508 update records and 3 of 3 screening evaluations at the time of writing —
so the weights it produces will be the weights that produced the curve above,
not a divergent run that merely started the same way. This verification is
repeated against the full prefix before section 1 is computed.

## Interpretive substitutions, disclosed

**"Hop distance from nearest router seed" reads as hop distance from
`start_node`.** `router_seed` is not a placed node: it is the hex string that
orders each node's outgoing edges (`generator._edge_order_key`). This
misreading was made and corrected once earlier in this experiment; the
substitute is BFS from the traversal root over the same visible edges
`gates.target_hop_distance` uses.

**"Target assertion" reads as "the edge's target node is in
`hidden['target_nodes']`."** This is deliberately distinct from section 1's
on-path fraction, which requires full route validity, so that sections 2 and 4
are not restatements of section 1. **This reading is not confirmed** and a
narrower one — only the specific relation-typed assertion edge — is defensible.
Re-running under the narrower reading costs another full checkpoint pass.

## Method note: accuracy alone is uninformative at this base rate

Target assertions are 1.6% of all available edges and 2.5% of DIRECT's pool. A
probe that always predicts "not a target" therefore scores 97.5-98.4% while
having learned nothing, and the checkpoint-independent results below confirm
this exactly: raw accuracy equals `1 - base_rate` to ten decimal places for
every feature. Two statistics are reported alongside it:

- `excess_over_constant_baseline` — accuracy minus the constant-baseline
  accuracy; the quantity that signals information beyond the class prior.
- `max_bucket_lift_over_base_rate` — the largest per-bucket positive rate on the
  fit set divided by the base rate, restricted to buckets with at least 30 fit
  examples so a lift cannot be manufactured by a near-empty bucket.

Majority-vote-per-bucket is close to insensitive at a 2% base rate: a real 5-10x
local enrichment still loses to "always predict the majority" unless it clears
50%. The lift statistic is what actually detects a shortcut here.

## Section 3/4 reference populations — COMPUTED (no checkpoint required)

Official gamma=0 screening domain, 2,000 episodes, 1,000 fit / 1,000 score.

### All available edges (base rate 0.0162)

| feature | accuracy | excess over baseline | max bucket lift | buckets >=30 |
|---|---|---|---|---|
| degree | 0.9838 | +0.00000 | 0.995 | 1 |
| global_position | 0.9838 | +0.00000 | 1.271 | 48 |
| hop_distance | 0.9838 | +0.00000 | 3.536 | 11 |
| local_rank | 0.9838 | +0.00000 | 1.026 | 3 |
| relation | 0.9838 | +0.00000 | 1.094 | 16 |

### DIRECT structural pool (base rate 0.0250)

| feature | accuracy | excess over baseline | max bucket lift | buckets >=30 |
|---|---|---|---|---|
| degree | 0.9750 | +0.00000 | 1.012 | 1 |
| global_position | 0.9750 | +0.00000 | 1.232 | 48 |
| hop_distance | 0.9750 | +0.00000 | 2.293 | 5 |
| local_rank | 0.9750 | +0.00000 | 1.054 | 3 |
| relation | 0.9750 | +0.00000 | 1.166 | 16 |

### DIRECT pool vs all available edges — distribution divergence

| feature | total variation | KL |
|---|---|---|
| degree | 0.0000 | 0.0000 |
| global_position | 0.0749 | 0.0149 |
| hop_distance | 0.5863 | 1.0131 |
| local_rank | 0.0052 | 0.0001 |
| relation | 0.0022 | 0.0000 |

**Reading.** No feature beats the class prior on either population. The only
material concentration is hop distance (TV 0.586), which is BFS doing exactly
what BFS does — concentrating near the traversal root — and is the benign case
named in advance. Serialization-order features are flat: local rank TV 0.005,
relation TV 0.002. `global_position` shows a mild 1.23-1.27x lift on both
populations, present in the *available-edge* population too, so it is a property
of the generator's serialization rather than of pool construction.

**This is the reference against which TRAV's chosen edges are measured.** It
establishes that a fixed structural pool exposes no exploitable regularity at
the class-prior-corrected level.

## Results

TRAV scored **1,500 / 1,500 non-abstain screening episodes correct** in the
baseline pass — the 100.00% under investigation, reproduced at inference.

### Section 1 — on-path fraction: **CLEAN**

**The metric as specified is uninformative, and this was found only after
running it.** Episodes contain a mean of 5.86 on-path edges while TRAV examines
128, so the on-path *fraction* is capped at roughly 0.0466 by construction. The
observed 0.0458 is 98% of the arithmetic maximum, not a low number. Predicting
"high" against a scale that cannot exceed 4.66% was a specification error.

Recomputed as **recall** — of the on-path edges that exist, how many did TRAV
examine:

| | mean | min | median | max |
|---|---|---|---|---|
| on-path edges available | 5.862 | 3 | 6 | 11 |
| on-path edges examined | 5.862 | 3 | 6 | 11 |
| **recall** | **1.000** | **1.000** | **1.000** | **1.000** |

**TRAV examined every on-path edge in every one of 1,500 episodes.** Perfect
recall, no exceptions. This is traversal doing exactly what the mechanism
claims. The correct/incorrect split the section asked for is vacuous here
because there were no incorrect episodes.

### Section 2 — first-target-examination step: **CLEAN**

| n | mean | min | p25 | median | p75 | max | within first 16 |
|---|---|---|---|---|---|---|---|
| 1,500 | 9.12 | 0 | 6 | 9 | 13 | 17 | 89.7% |

89.7% within the first 16 examinations is heavy concentration, which the
prediction named as the concerning shape — **but the prediction did not compute
what traversal actually allows, and that was the error.** Mean out-degree in this
domain is exactly 3.0, and a walk expanding one node per hop examines roughly
`3 x hops` edges: 6 at two hops, 9 at three, 12 at four. The gated stratum is
2–4 hops. **The observed median of 9 is precisely the centre of that range.**

TRAV is not reaching targets faster than traversal allows. It is reaching them
at exactly the rate an efficient walk predicts.

### Section 3 — structural concentration: **CLEAN**

Total variation of TRAV's chosen edges against all available edges, with
DIRECT's structural pool as the reference:

| feature | TRAV | DIRECT pool | reading |
|---|---|---|---|
| hop_distance | 0.3543 | 0.5863 | concentration, benign — and *less* than BFS's |
| global_position | 0.0755 | 0.0749 | indistinguishable from the fixed pool |
| local_rank | 0.0052 | 0.0052 | **identical**; no serialization preference |
| relation | 0.0028 | 0.0022 | flat |
| degree | 0.0000 | 0.0000 | flat |

The features that would indicate a shortcut — local rank in the router-seed
serialization, global position, degree — are flat and match the fixed pool to
four decimal places. The only concentration is hop distance, named as benign in
advance, and TRAV's is *lower* than DIRECT's BFS.

### Section 4 — predictive probe on chosen edges: **CLEAN**

Base rate 0.0288 over 128,000 scored edges.

| feature | excess over constant baseline | max bucket lift | DIRECT pool lift |
|---|---|---|---|
| degree | +0.00000 | 1.013 | 1.012 |
| global_position | +0.00000 | 1.245 | 1.232 |
| hop_distance | +0.00000 | 1.974 | 2.293 |
| local_rank | +0.00000 | 1.072 | 1.054 |
| relation | +0.00000 | 1.175 | 1.166 |

**No structural feature predicts target membership above the class prior on
TRAV's chosen edges**, and every lift is at or below the fixed pool's. If TRAV
had learned to select on a structural regularity, this is where it would appear.
It does not.

### Section 5 — shuffled serialization: **CLEAN**

| | exact-set accuracy |
|---|---|
| baseline | 1.0000 |
| node-level edge order re-randomized under a different seed | **1.0000** |

**Exactly zero change.** Graph, query, targets and budget held fixed; only the
order in which edges are presented was re-randomized. The prediction was that a
similarity-following policy would be unaffected because similarity is
order-independent. Confirmed to the last episode.

### Section 6 — ablated query: **CLEAN, after correcting the ablation**

**The ablation as first implemented did not remove query information.** Zeroing
the query embedding leaves `query_similarity_ppm` in the per-edge features
(`model.py:141`), and that scalar is itself query-derived — it is the signal a
similarity-following policy actually chains. The first result (16.93%) therefore
measured "query embedding removed, similarity retained", not "structure alone".
This was a specification error in the diagnostic, found on reading the result.

Three variants, separating the channels. Chance on non-abstain episodes is
1/15 = 6.67%:

| condition | exact-set accuracy |
|---|---|
| baseline | 100.00% |
| query embedding zeroed, similarity retained | 16.93% |
| **similarity flattened to a constant, query embedding retained** | **0.27%** |
| both ablated | 2.60% |

**Flattening similarity alone collapses TRAV from 100% to 0.27% — far below the
6.67% chance level.** Below chance, not merely at it: without the query signal
the model does not degrade to guessing, it produces predictions that fail
proof-valid scoring outright.

This is the innocent explanation confirmed as directly as the design allows.
TRAV is entirely dependent on query-derived information and retains nothing
without it. It does not locate targets from structure alone.

## Verdicts

| section | verdict |
|---|---|
| 1. on-path fraction (as recall) | **Clean** — 1.000 recall on 1,500/1,500 episodes |
| 2. first-target step | **Clean** — median 9 against an expected 6–12 |
| 3. structural concentration | **Clean** — serialization features flat, at the fixed pool's level |
| 4. predictive probe | **Clean** — zero excess over the class prior on every feature |
| 5. shuffled serialization | **Clean** — exactly zero change |
| 6. ablated query | **Clean** — collapses to 0.27%, below chance |

### Overall verdict: **CLEAN**

**The 100.00% at gamma=0 is what adaptive selection buys.** At gamma=0 the
highest-similarity neighbour is on-path at every step, so "follow maximum
similarity" is a complete and correct algorithm; TRAV learned it, executes it
with perfect on-path recall, and is entirely dependent on the query signal that
makes it work. No structural regularity, no serialization artifact, no
structure-only shortcut.

**This does not vindicate the arm comparison.** It establishes that TRAV's
gamma=0 result is legitimate, not that the gamma=0 control is informative. The
open question in the next section is untouched by these findings and is arguably
sharpened by them.

## Errors in this diagnostic's own specification

Recorded because the checks were mine and two of them were wrong:

1. **Section 1's metric was capped at 4.66% by construction.** "Predicted high"
   was stated against a scale that could not reach it. Corrected to recall.
2. **Section 6's ablation was incomplete**, leaving the query-derived similarity
   feature in place. The first number it produced was not evidence about
   structure-only performance. Corrected with three variants.
3. **Section 2's prediction named a concerning shape without computing the
   benign one.** 89.7% within the first 16 looked alarming until mean
   out-degree (3.0) and the 2–4 hop range were multiplied together.

All three were found by reading results against stated predictions, which is the
argument for stating them in advance. Had the predictions not been recorded, the
first would have read as a finding and the second as a disqualification.

## Open question — recorded, not acted on

**Is the 1.00pp gamma=0 control structurally satisfiable for this arm pair?**

If "follow the highest-similarity edge" is a complete algorithm at gamma=0, and
DIRECT's pool is query-blind by construction (`structural_bfs_pool` never reads
`query_similarity_ppm`), then DIRECT may be definitionally unable to compete at
gamma=0 — in which case the control fails not because the harness is wrong but
because the arms were specified that way, and the void was determined the moment
the arm definitions were frozen.

That is a question about the control's design, not about either arm's behaviour,
and it is recorded here **deliberately without action**. No amendment is drafted,
nothing is redesigned, and no conclusion is drawn. It is the kind of structural
conclusion that should not be reached in the same sitting as the number that
prompted it, and it waits until after this diagnostic reports.

Noted alongside it, for the record: an earlier reading of the gamma=0 gap as
evidence about adaptive-versus-fixed candidate selection *in general* was too
strong. DIRECT's inability to compete at gamma=0 is a property of its query-blind
pool construction. Any general claim lives at gamma>0, where no data exists.

## Effect on Phase 3a

This diagnostic gated Phase 3a and **reports Clean, so that gate lifts.** No
generator fix is required, and the v1 procedural data is not invalidated for
this comparison by anything found here.

The remaining prerequisite for Phase 3a is unchanged and unrelated: a code
freeze on a clean tree, since `freeze.py` inventories every `read_run` source
file and those changed.
