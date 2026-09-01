# TRAV edge-selection diagnostic at gamma=0

**Status: predictions and checkpoint-independent results recorded. Sections 1, 2,
4 (TRAV column), 5 and 6 await the diagnostic checkpoint and are marked
PENDING. No verdict is issued yet.**

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

## Sections 1, 2, 4 (TRAV column), 5, 6 — PENDING

Await the diagnostic checkpoint. The analysis code is written and validated
end-to-end against an untrained model on CPU; all six sections execute and the
edge cases (zero correct episodes, empty buckets) are handled.

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

## Verdict

**PENDING.** Per-section verdicts (Clean / Concerning / Disqualifying) and an
overall verdict are issued once sections 1, 2, 4-TRAV, 5 and 6 are computed.
This diagnostic blocks Phase 3a: no new code freeze and no gate jobs until it
reports. It does not block plateau determination, budget selection, or the
seed and configuration work, all of which proceed in parallel.
