# READ run v1 — per-seed spread and autocast scope of the void E1 sweep

Diagnostic date: 2026-09-01. Phase 0 of the E1 recovery plan.

This file reads existing artifacts only. No model was instantiated, no training
step was taken, no episode was generated, and no new evaluation was run. Every
number below comes from the 30 `predictions.jsonl` files the E1 evaluation
already wrote, joined against hop distances recomputed from the holdout streams
with the committed `gates.target_hop_distance`.

The holdout was opened once, under freeze `07d18b39…`, and is spent. Re-reading
predictions that were already scored spends nothing further; it also buys no
new licence, and no result on this page may be reported as an E1 finding. E1 is
void.

## Reproduction gate

Before any new figure was read, the recomputation was required to reproduce the
negative-control counts committed in [`results/E1.md`](../results/E1.md)
exactly. Had it not, the finding would have been that the committed table is
wrong, not that the seeds are tight or scattered.

| Cell | Recomputed | Committed in `results/E1.md` |
|---|---|---|
| DIRECT, gamma=0, `hops_2_4`, 3 seeds | 7 / 25,707 | 7 / 25,707 |
| TRAV, gamma=0, `hops_2_4`, 3 seeds | 7,330 / 25,707 | 7,330 / 25,707 |

Both reproduce. The stratification harness used here is the same one that
produced the committed table.

`abstain` in `predictions.jsonl` is `episode.hidden["abstain"]` — the gold flag,
not a model output (`evaluation.py:79`). Every `(gamma, stratum)` cell therefore
has a denominator that is identical across arms and seeds: 8,569 non-abstain
episodes in `hops_2_4` at every gamma. The table below is pure numerator
variation.

## Per-seed exact-set accuracy, `hops_2_4`, non-abstain

### DIRECT

| gamma | n per seed | s1729 | s2718 | s3141 | pooled |
|---|---|---|---|---|---|
| 0.0 | 8,569 | 4 = 0.05% | 1 = 0.01% | 2 = 0.02% | 0.03% |
| 0.1 | 8,569 | 0 = 0.00% | 1 = 0.01% | 1 = 0.01% | 0.01% |
| 0.2 | 8,569 | 0 = 0.00% | 0 = 0.00% | 4 = 0.05% | 0.02% |
| 0.3 | 8,569 | 3 = 0.04% | 22 = 0.26% | 1 = 0.01% | 0.10% |
| 0.4 | 8,569 | 1 = 0.01% | 0 = 0.00% | 8 = 0.09% | 0.04% |

DIRECT's entire signal is 48 correct answers out of 128,535 scored episodes.
Chance is 1/15 = 6.67%, which at n = 8,569 would be roughly 571 per cell. Every
DIRECT cell sits two orders of magnitude *below* chance. Seed variation here is
counting noise on a degenerate predictor and carries no information.

### TRAV

| gamma | n per seed | s1729 | s2718 | s3141 | pooled | seed range |
|---|---|---|---|---|---|---|
| 0.0 | 8,569 | 34.64% | 24.96% | 25.94% | 28.51% | 9.68pp |
| 0.1 | 8,569 | 39.20% | 29.10% | 45.71% | 38.01% | 16.61pp |
| 0.2 | 8,569 | 8.41% | 2.70% | 9.45% | 6.85% | 6.75pp |
| 0.3 | 8,569 | 40.45% | 3.69% | 30.59% | 24.91% | **36.76pp** |
| 0.4 | 8,569 | 31.36% | 20.76% | 17.21% | 23.11% | 14.15pp |

## Reading

The interpretation rule was written down before these numbers were read: seeds
tight within cells would mean the gamma series is systematic and gamma=0.2's
6.85% needs a mechanism; seeds scattered would mean it is training noise.

**The seeds are scattered, and the scatter is large enough to dominate.** The
widest cell, gamma=0.3, spans 3.69% to 40.45% — a 36.76pp range within a single
gamma, from three runs that differ only in model seed. The full pooled gamma
series spans 6.85% to 38.01%, a 31.16pp range. **The within-cell seed range at
gamma=0.3 alone exceeds the entire between-gamma range of the pooled means.**
The seed ordering is also unstable: s1729 leads at gamma 0, 0.3 and 0.4, while
s3141 leads at gamma 0.1 and 0.2. At gamma=0.1 s3141 is 6.51pp ahead of s1729;
at gamma=0.3 s1729 is 9.86pp ahead of s3141 and 36.76pp ahead of s2718. No seed
is uniformly stronger, which is the pattern a shared optimisation instability
produces rather than a systematic per-seed quality difference.

A gamma series whose between-gamma variation is smaller than its within-cell
seed variation carries no reportable trend. The apparent lurch in the E1 curve
is what three-seed noise looks like on an undertrained model, and no mechanism
for gamma=0.2 needs to be sought.

**One qualification, stated because it cuts the other way.** The gamma=0.2 dip
is present in all three seeds: 8.41%, 2.70% and 9.45% are each below their
gamma=0 counterparts of 34.64%, 24.96% and 25.94%. Three-for-three agreement is
not what pure noise looks like, so the scatter accounts for the *magnitude* of
the series' irregularity but not for the *sign* consistency at gamma=0.2.

**The per-update logs supply the mechanism, and it is convergence rate.** Mean
`answer_loss` over each run's last 100 updates, grouped by gamma:

| gamma | TRAV `L(1172)`, three seeds |
|---|---|
| 0.0 | 2.2432, 2.3102, 2.3830 |
| 0.1 | 1.8705, 2.1871, 2.2244 |
| **0.2** | **2.4720, 2.5138, 2.5372** |
| 0.3 | 1.9676, 2.3297, 2.5369 |
| 0.4 | 2.3367, 2.3810, 2.4091 |

All three gamma=0.2 runs sit above all three gamma=0 runs. Final loss and
exact-set accuracy are computed from different quantities — one from training
batches, one from held-out scoring — and they agree that gamma=0.2 is TRAV's
slowest bucket. That is a second, independent measurement of the same effect
rather than a restatement of the first.

DIRECT, by contrast, shows **no gamma structure at all**: its fifteen `L(1172)`
values sort perfectly by model seed, with all five s3141 runs below all five
s1729 runs below all five s2718 runs, and gamma nowhere in the ordering. That is
what an arm which has not learned a function of its input looks like, and it
makes the gamma=0.2 effect specific to TRAV.

The effect is therefore about how fast TRAV converges at gamma=0.2, not about
the data or the metric. It is **not** evidence of a gamma mechanism in the sense
the experiment was designed to test, because no cell on this page is a converged
measurement: both arms finish near uniform and TRAV's gradient norm is still
rising. Its practical consequence is recorded in Amendment 04 §4 — a budget
chosen from a gamma=0 probe may undertrain the gamma=0.2 cell, so E1-v2 must
report per-gamma final loss and flag any cell that never left uniform.

## Degeneracy signature, `hops_2_4`, gamma=0, non-abstain

Distinct predicted classes and the Shannon entropy of the empirical
predicted-label distribution, over 8,569 episodes per cell. Sixteen classes
exist; class 0 is ABSTAIN.

| Arm | seed | distinct classes | entropy (nats) | modal class | modal fraction |
|---|---|---|---|---|---|
| DIRECT | 1729 | 5 | 0.0095 | 0 | 99.89% |
| DIRECT | 2718 | 2 | 0.0031 | 0 | 99.96% |
| DIRECT | 3141 | 4 | 0.0101 | 0 | 99.88% |
| TRAV | 1729 | 16 | 1.9017 | 0 | 54.29% |
| TRAV | 2718 | 16 | 1.6180 | 0 | 62.54% |
| TRAV | 3141 | 16 | 1.7567 | 0 | 56.65% |

Across all fifteen DIRECT runs the distinct-class count never exceeds 5 and
falls to **1** in three of them — gamma 0.1/s1729, gamma 0.2/s2718 and gamma
0.4/s2718 emitted a single class on every scored episode. Entropy never exceeds
0.0676 nats. TRAV emits all 16 classes in all fifteen runs, but is not uniformly
healthy either: at gamma=0.2 its entropy falls to 0.2735 nats with 95.78% of
mass on class 0 for s2718, which is the same collapse in milder form and is the
cell with the lowest TRAV accuracy.

These are the anchors for the learner gate in Amendment 04.

Both arms' modal prediction is class 0 — ABSTAIN — on episodes whose gold label
is by construction *not* ABSTAIN. The label marginal is exactly 25% class 0 and
5% for each of the fifteen others, so class 0 is the single most frequent label
in training, and both arms are pulled onto it. That is what a model which has
learned the label marginal and little else does.

## Autocast scope

The equivalence test that gated the batched TRAV traversal ran in fp32 on CPU,
while training ran under `torch.autocast(bfloat16)` on CUDA. The gate therefore
verified a regime training never used, which is how the `index_copy_` dtype
mismatch reached the sweep. The question for E1 is whether any of the 30 runs
predates the fix at `112fcb0`; if some did, the TRAV column would mix two
regimes and would be uninterpretable independently of the void.

**All 30 runs are post-fix.** Two independent lines of evidence.

**Records.** All 30 training receipts bind
`code_freeze_sha256 = sha256:07d18b39486e5d2a67a78284f1bd0547c03eb842b44b06637b5ac5743f14dea9`.
Recomputing `canonical_sha256` over `private/read-run-v1/p0-rerun/code-freeze.json`
returns that exact digest, and that freeze records
`git_commit = 112fcb0446021f2208aa72761dbbe3301e7165bc` — the dtype fix itself.
The freeze also refuses to be created from a dirty working tree, so the commit
it names is the tree that ran.

**Structure.** The records claim is corroborated by an argument that does not
depend on any record.

- The dtype mismatch raised `RuntimeError` and killed every TRAV run outright.
  It was fatal, not silent, so a pre-fix TRAV run cannot have produced a
  `checkpoint.pt` at all. The 15 TRAV checkpoints that exist are post-fix by
  construction.
- DIRECT never reaches the affected code. `forward` dispatches on the arm
  (`model.py:412`); DIRECT enters `forward_direct`, which calls `state_cell`
  exactly once and rebinds `state` (`model.py:177`). `index_copy` appears only
  in `forward_trav_batched` (`model.py:390`), which DIRECT never enters. The
  bug is unreachable on the DIRECT path in any dtype regime.

The two arguments have different failure modes — one would break if a receipt
were wrong, the other if the dispatch were wrong — so they are genuinely
independent confirmations rather than one restated.

## What this does not establish

Nothing here rehabilitates E1. The negative control failed by 28.49pp against a
1.00pp threshold and the run stays void. This page establishes only that the
void has one cause rather than two: the arms were undertrained, and no part of
the TRAV column is an artifact of mixed dtype regimes.
