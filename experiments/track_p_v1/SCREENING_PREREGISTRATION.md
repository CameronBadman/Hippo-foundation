# Track P screening preregistration — a learned stop under honest expansion cost

## Status: recorded, screening only, NOT a preregistered arm

Written 2026-09-04, committed before the first Track P training run starts. This
governs the reading of that run. It is a screening ablation on new v3 data, not
an arm of the frozen READ v1 experiment: it opens no holdout, changes no frozen
digest, arm, metric, seed or threshold, and no comparison in it can move
Amendment 10, which remains pending review.

Every reference number below is copied from committed JSON —
`diagnostics/policy_ladder_v3.json`, read against `LADDER_PREFLIGHT.md` — all of
which was measured before any Track P model was trained.

## 1. What is being asked

Track O read band A, but under a cost model that turned out to flatter it. Two
things measured afterwards set up this experiment:

- **On v2 data there was nothing to learn.** Under relation-indexed expansion the
  blind walker's cost equals the oracle's on 65 % of episodes, and the
  two-endpoint stop `stop_aware` uses is exact on 100 %. A stop head trained
  there would be learning the constant 2.
- **Track O's own coverage head was never trained** (design note 2.22): its
  parameters are byte-identical to initialisation after 8,000 updates. Band A was
  earned by the edge score alone.

Generator v3 plants K distractor paths — complete, rule-valid, query-matching
paths to non-target endpoints — so that stopping becomes a decision and ordering
has room. **K = 1** was fixed by the rule "smallest K passing ladder gates 1–3",
written into the ladder script before it ran.

The question: **does a learned stop, trained on exactly derivable labels with no
target constant anywhere in its features, halt a walk correctly and more cheaply
than the best hand-coded stop?**

## 2. The references, all measured before any model exists

Hard cell `deg6_len8_v4_rep-k1`, gated `hops_2_4`, non-abstain, n = 1,080,
γ = 0.4. Cost in **expansions**; completeness is **registration** of both target
endpoints by the walk, not set coverage (design note 2.23).

| policy | registers both | Wilson LB | expansions mean / median | at RC | overhead | examined precision |
|---|---|---|---|---|---|---|
| oracle (reads hidden) | 1.000 | — | — / 4 | 4 | 0 | — |
| stop_aware | 0.873 | 0.856 | 6.03 / 5 | 4 | 0 | 0.184 |
| bfs_two_stop | 0.844 | 0.825 | 7.33 / 6 | 5 | 0 | 0.163 |
| blind_exhaust | 1.000 | 0.998 | 7.93 / 6 | 6 | 0.43 | 0.153 |
| similarity_exhaust | 1.000 | 0.998 | 7.93 / 6 | 5 | 1.63 | 0.153 |

Easy cell `deg3_len6_v8-k1`, n = 1,122: `stop_aware` registers 0.771 at 4.83
expansions; `blind_exhaust` 1.000 at 5.96; oracle median 4.

**The shape of the problem.** No model-free policy is both complete and cheap.
The two exhaustive policies are always right and cost 7.9 expansions; the two
stopping policies cost 5–6 and are wrong on 13–16 % of episodes. The oracle needs
4. A learned stop that is right *and* cheaper than `stop_aware` would be doing
something no policy here can do.

**A sixth reference, the honest untrained line:** the same architecture,
untrained, walking with its own ordering and stopping on an **oracle** stop. An
untrained model with its own untrained stop head is a coin flip per step and is
reported beside it as the degenerate case, never used as the reference. The 2×2
of {trained, untrained} ordering × {learned, oracle} stop is what lets the report
say whether the stop or the ordering carried any result.

## 3. Runs declared in advance

One arm `TRAVP` (`model_v3`, 10,257,896 parameters — identical to Track O's, by
shared module definition) × 2 cells × 3 model seeds (1729, 2718, 3141) × 8,000
updates, under `training-config.p1.json`. Data: `private/track-p-v1/data/`,
20,000 train / 4,000 screen requested per cell; the hard cell yields 14,380 and
2,916 after its 28 % uniqueness rejection, the easy cell all 20,000 and 4,000.
Measured γ 0.395–0.401 against 0.4 requested.

Training always **exhausts** and ignores the stop head's own output, so what the
head learns is decoupled from what it does. No budget exists anywhere in the run;
`stop_reason` is restricted to `learned_stop` and `tree_exhausted` and any other
value is band H.

## 4. Primary quantities

Read per seed, on the hard cell, gated `hops_2_4`, non-abstain, at update 8,000.

1. **Completeness** — the fraction of episodes where the walk registered both
   target endpoints before it stopped, with a Wilson lower bound.
2. **Cost** — expansions at the stop, compared **only on episodes where
   completeness holds**. Cost is trivially gameable by stopping early, so
   completeness gates the cost reading; a policy that stops at zero expansions is
   infinitely cheap and worthless.
3. **The returned set** — a route is returned when every one of its edges scores
   above zero, the edge head's own boundary and not a tuned threshold.
   `proof_valid` requires the returned routes to be exactly the two target
   routes, so returning the planted distractor fails it. Precision, recall and
   the mean number of returned routes are reported beside it.

**Cost comparison without a tuned effect size:** the paired per-episode
proportion "model expansions ≤ reference expansions" with a Wilson lower bound
above 0.5, the same shape as the existing decision rules. Bootstrap CIs on mean
differences are descriptives, not gates.

Both stop rules are reported side by side, from the same trained head:
`probability` (`P(stop) > 0.5`, the BCE's own boundary) and `logit_margin` (stop
when the stop logit exceeds the best remaining frontier edge logit — no constant
at all). Neither is selected after the fact; both appear in every table.

## 5. Outcome table — per seed, hard cell, paired

Sign-symmetric: every favourable row has an unfavourable mirror.

| band | condition |
|---|---|
| **A** | completeness LB ≥ 0.95 **and** cost beats `stop_aware` **and** beats the untrained line (both paired LB > 0.5) |
| **B** | completeness LB ≥ 0.95 and cost beats the untrained line but not `stop_aware` |
| **C** | cost beats both but completeness LB < 0.95 — cheap and wrong, the failure the gate exists to catch |
| **D** | indistinguishable from the untrained line on both axes |
| **E** | worse than the untrained line on either axis (paired LB > 0.5 in the reference's favour) |
| **F** | seeds split across bands A/B and D/E — reported as split, never averaged |
| **G** | a floor: completeness at 1.000 with cost equal to exhaustion (the stop never fires), or completeness at 0 |
| **H** | harness: a `stop_reason` outside the two allowed, any `route_coverage_v3`/registration disagreement above 1 %, a capacity drift from 10,257,896, or the visit-order invariance test failing |

**Bands B, D and E are real outcomes, not failures to be explained away.** Band D
in particular — a stop head that learns nothing beyond its initialisation — is
the direct analogue of what Track O's coverage head silently did, and would be
reported as such.

## 6. Expected results, written down before the runs

So that an over- or under-shoot is visible rather than rationalised afterwards:

- **Easy cell:** completeness ~1.0, overhead ~0, early stops ~0. If this cell
  fails, the harness is wrong, not the hypothesis.
- **Hard cell:** completeness near 1.0 against `stop_aware`'s measured 0.873, and
  expansions below `stop_aware`'s 6.03 mean / 5 median, against the oracle's 4.
- **Stop-label agreement** on the training batch should approach 1.0 quickly on
  the easy cell and more slowly on the hard one. That gap *is* the capability
  being measured; if both saturate immediately, the label is too easy and the
  result is uninformative.
- **The interesting number is the early-stop rate.** A nonzero rate with high
  completeness means the head has learned something the constant-2 rule cannot
  express.
- **Returned-set precision** is expected to be well below 1.0 at first: the
  edge head must learn to exclude a complete, rule-valid, query-matching
  distractor route, which is strictly harder than anything Track O asked of it.

## 7. Controls and what is not authorised

- No holdout is opened. Both holdout seeds stay sealed and no path containing
  `holdout` or `heldout` is read.
- No threshold is tuned: `selection.threshold_tuning` is false, and both stop
  rules are parameter-free consequences of trained logits.
- No model selection: the reported checkpoint is update 8,000, fixed here, not
  the best checkpoint.
- The loss weights (answer 1.0, edge 0.25, stop 0.25) are **not** an operating
  point in the sense design note 2.16 rules out. Each head is separately
  supervised against exactly derivable labels, so the mixture changes how fast
  each converges, never where it converges.
- K = 2 and K = 4 also passed every ladder gate and are deliberately **not** run.
  They are the next cell if K = 1 reads band A, and running them now would be a
  sweep.
- Nothing here authorises training on real data, opens the write path, or
  promotes any Track P result into the frozen v1 experiment.
