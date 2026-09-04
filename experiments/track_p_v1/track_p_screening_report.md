# Track P screening report — a learned stop under honest expansion cost

## Status: screening, six runs, not a preregistered arm

Read against `SCREENING_PREREGISTRATION.md` as amended (amendment 1, commit
`b4bd881`), at update 8,000, per seed, never pooled. Six runs: `TRAVP` ×
{`deg6_len8_v4_rep-k1`, `deg3_len6_v8-k1`} × seeds {1729, 2718, 3141}. All six
completed 8,000 updates; the easy-cell seed 3141 run was launched later than the
other five because the launcher's GPU-memory gate refused it, and is included
here rather than silently excluded.

Every number is from committed JSON under `diagnostics/` — `report-*.json`
(references and paired comparisons), `limitations.json` (the abstain split and
the win/tie/loss breakdown), and the runs' own `screen.jsonl` — or from
`LADDER_PREFLIGHT.md`. Nothing here opens a holdout, changes a frozen digest, or
moves Amendment 10.

## 1. Band, hard cell, per seed

By the preregistered rule — completeness Wilson lower bound ≥ 0.95, cost beats
`stop_aware` and beats the untrained-ordering-with-oracle-stop line, both by the
paired proportion "model expansions ≤ reference" with Wilson LB > 0.5:

| seed | registers both | Wilson LB | vs stop_aware LB | vs untrained LB | band |
|---|---|---|---|---|---|
| 1729 | 0.973 | 0.967 | 0.811 | 0.902 | **A** |
| 2718 | 0.959 | 0.952 | 0.800 | 0.909 | **A** |
| 3141 | 0.951 | 0.943 | 0.810 | 0.868 | **C** |

**Two seeds read A and one reads C**, the third missing the completeness bound
by 0.007. The preregistration's band F covers a split across A/B versus D/E and
did not anticipate A/A/C; this is recorded as a gap in the outcome table, not
resolved by choosing a reading. The cost half of band A rests on a metric that
section 7 shows to be tie-inflated: the robust part of the result is
completeness, not cost.

Easy cell, the sanity rung: registers both on 0.977 / 0.972 / 0.971 (LB 0.972 /
0.966 / 0.964) at 4.89 / 4.88 / 4.91 expansions. Expected result was ~1.0; the
2–3 % early-stop rate is the residual.

## 2. Model-free references, measured before any training run

Hard cell, gated `hops_2_4`, non-abstain, n = 2,179 on the screening split.
Cost in expansions; completeness is registration of both target endpoints.

| policy | registers both | expansions (all) | expansions (when registered) |
|---|---|---|---|
| oracle (reads hidden) | 1.000 | 4.739 | 4.739 |
| stop_aware | 0.854 | 5.951 | 5.655 |
| blind_exhaust | 1.000 | 7.799 | 7.799 |

Plus the untrained line — the same architecture at its initialisation, walking on
its own scores with an oracle stop — which is seed-specific: 7.147 / 6.737 /
6.076. The degenerate line (untrained ordering *and* untrained stop) is wildly
seed-dependent — seed 2718 halts at zero expansions on every episode, seeds 1729
and 3141 never halt — which is why it is reported and not used as a reference.

## 3. Every run at the read point (update 8,000, `probability` stop rule)

| run | n | registers | LB | expansions | early stop | returned edges | precision | recall | proof-valid | exact |
|---|---|---|---|---|---|---|---|---|---|---|
| hard s1729 | 2179 | 0.972 | 0.966 | 5.709 | 0.028 | 5.3 | 0.810 | 0.769 | 0.117 | 0.088 |
| hard s2718 | 2179 | 0.959 | 0.951 | 5.723 | 0.041 | 5.3 | 0.805 | 0.767 | 0.128 | 0.085 |
| hard s3141 | 2179 | 0.950 | 0.942 | 5.623 | 0.050 | 4.7 | 0.834 | 0.713 | 0.095 | 0.074 |
| easy s1729 | 2308 | 0.977 | 0.972 | 4.893 | 0.023 | 5.8 | 0.804 | 0.889 | 0.279 | 0.251 |
| easy s2718 | 2308 | 0.972 | 0.966 | 4.883 | 0.028 | 5.7 | 0.809 | 0.880 | 0.283 | 0.260 |
| easy s3141 | 2308 | 0.971 | 0.964 | 4.908 | 0.029 | 4.7 | 0.838 | 0.761 | 0.168 | 0.146 |

The `logit_margin` rule is reported in every run's `screen.jsonl` beside it and
is uniformly slightly worse: registers 0.933–0.948 on the hard cell at 5.94–6.02
expansions with 0.61–0.64 overhead, against `probability`'s zero overhead.
Neither rule was selected after the fact; `probability` is the preregistered
primary. Coverage disagreements between the two independent implementations:
0, 0, 1, 0, 0, 0 of ~2,200 each — within band H's 1 % bound by two orders of
magnitude.

**Overhead is 0.00 on every run.** On the episodes the learned stop completes, it
halts at exactly the decision point where the second target registered; paired
against the same model with an oracle stop on the same episodes, the two tie on
100 % of them. The stop's only failure mode is halting *before* completion, on
2.3–5.0 % of episodes.

## 4. Order of evidence

1. Ladder JSON committed in `f0a104f`; gates and the K rule in its docstring
   before it ran; K = 1 follows.
2. Preregistration committed in `23e78c3`; amended in `b4bd881` at ~250 of 8,000
   updates, before any checkpoint was read (section 7).
3. `preflight.md` quotes the HEAD the runs descend from; the launcher refused to
   start unless HEAD descended from the preregistration commit.
4. The runs.

## 5. What training bought, decomposed

The 2×2 the preregistration asked for, hard cell, all 2,899 gated episodes
including abstain, oracle stop applied to everyone so only the ordering differs:

| ordering | expansions until both targets register |
|---|---|
| similarity-following | 6.254 |
| trained, seeds 1729 / 2718 / 3141 | 5.814 / 5.819 / 5.743 |
| oracle | 4.736 |

And with exhaustion as the no-stop reference (7.799 for everyone):

| seed | stop saves, untrained ordering | stop saves, trained ordering | ordering saves, oracle stop held |
|---|---|---|---|
| 1729 | 0.65 | 1.97 | 1.32 |
| 2718 | 1.06 | 1.95 | 0.88 |
| 3141 | 1.72 | 2.03 | 0.30 |

**Training bought ordering** — the model beats similarity-following by ~0.45
expansions and sits ~1.05 above the oracle — **and the stop bought about two
expansions on top, roughly a quarter of the walk.** The two multiply: the stop is
worth two to three times more with trained ordering than without, because good
ordering registers the targets earlier and that is what creates room to stop.
Amendment 1's "the stop's headroom is only 0.43 expansions" was measured on the
blind walker and understated what a trained ordering makes available.

**The stop head is clean on the abstain split.** Registration on abstain versus
non-abstain episodes: 0.972 / 0.973, 0.964 / 0.959, 0.961 / 0.951. Its
`endpoints_agree` feature is exactly the one that could have carried the
shortcut of section 7; it did not.

## 6. The returned set — what the walk asserts is relevant

A route is returned when every one of its edges scores above zero, the edge
head's own boundary. Proof-validity requires the returned set to be exactly the
two target routes.

Selective return did not work, and the reason is measured. At update 8,000 on
hard-cell seed 1729, over 22,772 examined edges: off-route edges score −9.45 mean
logit and are 98.6 % correctly negative; target-route edges are 74.9 % positive;
**distractor-route edges are 50.9 % positive — chance.** Distractors are 3.5 %
of examined edges and 27 % of the edge loss. The edge loss flatlined at ~0.14 from
update 1,500 and did not move through 6,500 further updates; train-set edge loss
(0.133) equals screening-set edge BCE (0.125), so this is not a generalisation
gap. The model returns the planted distractor route on 25–31 % of hard-cell
episodes and 41–48 % of easy-cell ones.

Precision and recall oscillate across checkpoints rather than converge — recall
between 0.57 and 0.94, proof-validity between 0.023 and 0.173 on seed 1729 — so
update 8,000 is a point on a flat loss, not a plateau. It was fixed in advance
precisely so the flattering checkpoint at 4,000 could not be chosen.

Answer class accuracy alone, without the proof-validity gate: 0.477 / 0.461 /
0.498 on non-abstain episodes and 0.435 / 0.443 / 0.426 on abstain. Section 7(c)
gives a probable cause.

## 7. Stated limitations of this reading

**(a) The preregistered cost metric is tie-inflated.** "Model expansions ≤
reference" counts a tie as a win, and ties are the majority. From
`limitations.json`, on episodes the model completed:

| run | vs stop_aware: better / tie / worse | vs untrained + oracle stop: better / tie / worse |
|---|---|---|
| hard s1729 | 0.196 / 0.602 / 0.202 | 0.504 / 0.404 / 0.092 |
| hard s2718 | 0.206 / 0.587 / 0.207 | 0.374 / 0.525 / 0.101 |
| hard s3141 | 0.221 / 0.581 / 0.198 | 0.220 / 0.638 / 0.142 |
| easy s1729 | 0.111 / 0.594 / 0.295 | 0.375 / 0.480 / 0.145 |
| easy s2718 | 0.115 / 0.601 / 0.284 | 0.257 / 0.634 / 0.109 |
| easy s3141 | 0.104 / 0.606 / 0.290 | 0.087 / 0.779 / 0.134 |

On the hard cell the model is strictly better than `stop_aware` about as often as
it is strictly worse; on the easy cell it is strictly worse nearly three times as
often as better. The preregistered rule reports 0.73–0.81 in both cases. Against
the oracle it reports 0.62 while the model is strictly better on **0.000** of
episodes. **The model's advantage over `stop_aware` is completeness (0.95–0.97
against 0.85), not cost.**

Against its own untrained initialisation the picture is genuinely mixed by seed:
the hard-cell gain is real and largest for seed 1729 (strictly better on half the
episodes), while easy-cell seed 3141 is strictly *worse* than untrained more often
than better — that seed's initialisation already ordered the easy cell at 4.975
expansions against the trained 4.963, so training had almost nothing to buy there.
Per-seed reporting is what makes that visible. A future preregistration should use
a cost rule that excludes ties or reads a signed mean with its interval.

**(b) The band table did not anticipate A/A/C.** Section 1.

**(c) The answer head hard-codes the constant this track existed to remove.**
`model_v2.answer`, inherited unchanged by `model_v3`, reads `for slot in
range(2)`, flags agreement only `if len(endpoints) == 2`, and caps the route count
at `min(len(routes), 2)`. On v3 data a walk registers three or more endpoints, so
the head sees an arbitrary two by registration order and its agreement flag is
false whenever a distractor was registered. The constant was removed from the
stop features and left here. Class accuracy of 0.46–0.50 is consistent with it.
Fixed in Track Q, not rerun here.

**(d) The generator's intended discriminative signal is weak.** `generator_v3`
claims similarity promotion at 0.6 on target routes against ~0.17 on distractor
interiors. Per edge that is true and tested. Per route it barely separates:
ranking by promoted-edge fraction puts the worst target route above the best
distractor on 24.8 % of episodes with 63.3 % ties, and simulation shows a ceiling
of 0.47 even with distractor promotion at zero, because a target edge is itself
promoted only 60 % of the time at γ = 0.4. A handful of binary draws per route is
weak evidence at the route level. Owned as a design error in the generator's
docstring, which states the per-edge fact and not its route-level consequence.

**(e) The selective-return evaluation ran on a subset that admits a shortcut.**
Screening filtered to non-abstain episodes, inherited from Track O. The generator
gives the two targets a shared assertion mask exactly when the episode is
non-abstain. A zero-parameter, constant-free rule — return the largest group of
candidate routes whose endpoints share a mask — scores, from `limitations.json`:

| run | per-edge rule (this model), non-abstain / abstain | route-mean rule, non-abstain / abstain | mask-group rule, non-abstain / abstain |
|---|---|---|---|
| hard s1729 | 0.116 / 0.110 | 0.243 / 0.122 | **0.928 / 0.000** |
| hard s2718 | 0.127 / 0.104 | 0.235 / 0.121 | 0.916 / 0.000 |
| hard s3141 | 0.095 / 0.103 | 0.236 / 0.144 | 0.909 / 0.000 |
| easy s1729 | 0.279 / 0.238 | 0.399 / 0.242 | 0.949 / 0.000 |
| easy s2718 | 0.284 / 0.254 | 0.414 / 0.257 | 0.945 / 0.000 |
| easy s3141 | 0.169 / 0.173 | 0.398 / 0.258 | 0.943 / 0.000 |

Three readings. The model's own rule is flat across the split (0.116 / 0.110),
so **the model did not exploit the shortcut**; it was measured on a subset where
one existed. The constant-free route-mean rule — the same edge logits, aggregated
per route and thresholded at zero — doubles proof-validity with no new parameters,
which says the per-edge decode discards information the scores contain; but it
also drops from 0.24 to 0.12 on abstain, so it is not free of the split either.
And selective return must in future be reported on all gated episodes with the
abstain split shown, because proof-validity is well defined on an abstain episode
and excluding those is what created the gameable subset. Traversal completeness
and cost never depended on masks and are unaffected.

**(f) Amendment 1 was made mid-run.** At ~250 of 8,000 updates, before any
checkpoint, the gold supervision phase was dropped after the diagnostics showed
the stop label was 0 at every decision point of every episode under it — a gold
walk expands exactly the route prefixes, so both targets register during its final
expansion and no decision point observes completion. Measured 0/212 and 0/228
positive decision points under gold against 21/299 and 33/361 on-policy. The
change removed states in which the stop label cannot exist; it added no edge-loss
data on-policy did not already cover. Recorded in the preregistration with its
measurement.

**(h) Stderr was not empty.** Three runs (easy s1729, easy s2718, hard s2718)
each logged one `CUDACachingAllocator` OOM *warning* two to five minutes after
launch, while five runs were allocating concurrently on a 16 GB device — the same
pressure that made the launcher refuse the sixth. On that path the allocator frees
its cache and retries; a failed retry raises a hard error and ends the run. All
three completed 8,000 updates with continuous loss curves and nineteen screening
checkpoints, so the retries succeeded. A memory-pressure event, not a numerical
one; recorded because "zero stderr" would be false.

**(g) Content features carry no ordering information on this generator.** Every
edge in a v2/v3 graph satisfies its relation's rule by construction, so content
cannot separate a route edge from a filler edge; the zero-shot content machinery
is a question for insert, not read. Not measured by ablation here; noted so the
read-path result is not credited to it.

## 8. What this report does not do

It does not open a holdout, promote any Track P result into the frozen v1
experiment, move Amendment 10, or authorise insert training. By the standing
branch rule — good traversal results advance to insert, insufficient ones mean
continuing to iterate on traversal — the substrate is not yet ready: the walk and
the stop are, selective return is not, and downstream write operations consume
the returned set. Track Q addresses selective return specifically, with the
corrected reference (0.243, not 0.117), evaluation on the whole distribution, and
a route-set scoring head that is explicitly not given the mask-agreement count.
