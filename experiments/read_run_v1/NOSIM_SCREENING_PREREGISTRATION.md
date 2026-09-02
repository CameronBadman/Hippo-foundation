# Track N — structural-only (similarity-masked) screening preregistration

## Status: recorded, screening only, NOT a preregistered arm

Written 2026-09-02 and committed **before** any similarity-masked run exists.
Every threshold, band and reference number below is fixed by this commit; the
runs it governs start after it, and each run's `probe.json` records
`started_at` and `git_head` so the order is checkable rather than asserted.
The frozen preregistration, `preregistration.v1.json`,
`training-config.v1.json` and the v2 records keep the digests pinned in
`read_run/contracts.py`; this document edits none of them and no amendment.
Amendment 10 stays **pending review**. Nothing here generates, reads or opens a
holdout, and no screening arm comparison in the resulting report is a result.

The word "ablation" in `docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md` §2.1 means
*route* ablation (a generator design). This document is an *input* mask on
the frozen data; it is called structural-only or similarity-masked throughout,
and the CLI flag is `--input-ablation no_similarity`.

---

## 1. Why this run

The γ sweep (`diagnostics/gamma_sweep_screening_report.md`, read at commit
`0c50d7d`) showed that `query_similarity_ppm` is both the γ-degraded edge hint
it was designed to be and a γ-invariant on-path marker (D-1: at every valid-path
state exactly one out-edge is promoted to 900,000, so the set of marked nodes is
the set of path-edge sources on all 2,000 γ = 0 screening episodes). Every
trained TRAV checkpoint holds 99.47–100.00 % exact-set accuracy with the field
present and, with the field held at Stage C's constant 500,000, is
route-complete on only 53.56–69.13 % of the gated stratum — every value below
the 87.90 % that DIRECT's query-blind BFS pool reaches at the same budget.

So the capability measured so far splits in two. Edge discrimination was
learned. **Navigation** — reaching the route from structure when nothing marks
the on-path nodes — was never tested, because every TRAV ever trained had the
marker from update 0. Navigation is the load-bearing half for a memory system
(no real graph carries the marker) and is what the successor design's insert
path would depend on. This run asks the narrowest question that settles whether
the collapse was a shortcut *preference* or an *inability*: the same frozen
model class, the same frozen v1 data, trained from scratch with the similarity
input held at a constant.

## 2. The mask, and what it leaves the model

**Definition.** `read_run/ablation.py`: `no_similarity` sets every edge's
`query_similarity_ppm` to **0** at train and at eval, in place on the training
stream (`_cycle_episodes` re-reads the gzip each epoch, so nothing accumulates)
and on a deep copy for scoring. The field stays present, so
`io.validate_model_input_fields` still passes and the field set the model
consumes is unchanged.

**Equivalence to removal.** `model.py` reads the field on one line
(`edge["query_similarity_ppm"] / 1_000_000`, the last input column of
`edge_encoder[0]`); no node id, edge id, position, depth or hop count enters
any tensor. With the column held at 0 its weight receives exactly zero
gradient (`tests/test_read_run_ablation.py` asserts this after a backward
pass), so the feature is removed at unchanged `expected_trainable_parameter_count`
and no frozen model code changes. The masked payload equals
`gates._structural_projection` (P0 gate 7's γ-invariance projection) with the
field re-inserted at 0, so under the mask the five γ buckets are the same data:
the audit compared `screen-g01`–`g04` against `screen-g00` position by position
and found **0** masked-visible mismatches, **0** label mismatches and **0**
paired-world mismatches in 4 × 2,000 pairs. γ is therefore inert, and the six
runs use `train-g00` and `screen-g00` only. Stage C's constant 500,000 is a
different ablation of a *trained-with-similarity* model and is never compared
to this one.

**What is left** — from `diagnostics/model_input_audit.json` (commit
`4fdd9cc`; `screen-g00`, 2,000 episodes, and the first
10,000 of `train-g00`; every number below is copied from that file):

| channel | screen-g00 | train-g00 (first 10,000) |
|---|---|---|
| rank AUC, on-route node by mask value / popcount | 0.4997 / 0.4991 | 0.4994 / 0.4981 |
| rank AUC, target node by mask value / popcount | 0.5011 / 0.4997 | 0.5009 / 0.4995 |
| P(two targets share a mask) — equals 1 − abstain rate by construction | 0.7500 | 0.7498 |
| P(random node pair shares a mask) | 0.0669 | 0.0668 |
| answer is the graph's modal mask (non-abstain) | 16.73 % of 1,500 | 16.15 % of 7,498 |
| route states with a same-relation distractor edge | 9.10 % of 9,661 | 9.49 % of 48,915 |
| episodes with any such state | 35.60 % | 36.59 % |
| distractor fraction by depth 0 / 1 / 2 / 3 / 4 / 5 | 15.00 % / 10.60 % / 8.17 % / 7.85 % / 5.23 % / 0.00 % | 15.98 % / 10.42 % / 9.16 % / 8.08 % / 5.56 % / 0.00 % |
| fraction of edges whose relation is in the query set — all edges / pool-128 | 35.43 % / 37.04 % | 35.83 % / 37.39 % |

The assertion masks carry no information about routes or targets (all eight
AUCs within 0.002 of 0.5), and the answer class is not recoverable from the
graph's mask distribution. What remains is relations: the query's relation
sequence against each node's three out-edge relations. The generator's
ambiguity profile is easy — at fewer than one route state in ten does a
same-relation distractor exist, and at depth 0 it is 15.00 % — which
bounds what a positive result can say (§8). The 0.00 % at depth 5 (the last
step of L = 6 routes, 656 and 3,508 states) is consistent with the generator's
rule that no complete matching path other than the two routes exists.

**The walker's true ceiling — a correction.** Amendment 10 §1.5 and the
development log of 2026-09-02 state that a relation-following policy is
route-complete on 100 % of gated episodes at B = 16 because the relation-prefix
tree holds 3–16 edges. That counts only the *matching* edges. The frozen model
expands a node by scoring all of its out-edges, so a relation-follower under
the model's own mechanics examines 3 edges per expanded node — dead ends
included, since a node is only known to be a dead end once its out-edges have
been examined. `coverage.relation_walker_examined_set` implements exactly that
walker (breadth-first over `(node, depth)`, following the query relation at
each depth, never reading similarity); its examined list is
3 · |expanded nodes| on every audited episode
(`walker_size_is_three_per_expanded_node`), min 6, median 12, mean 13.46,
p95 27, max 45 on the gated stratum. The
tree-size statement stands as a lower bound for an edge-level selector; the
reference for *this* model is the walker's route-completeness in §4.

## 3. Runs declared in advance

`scripts/read_run_learning_probe.py` with the new `--input-ablation
no_similarity` flag (`record_kind: read_run_learning_probe_not_preregistered`,
no training receipt, no holdout), v1 screening data under
`private/read-run-v1/p0-rerun/`, B = 128, device `cuda` with bf16 autocast,
the v1 training configuration with only `update_count` varied, exactly as the
γ sweep ran. Outputs `private/read-run-v1/diagnostics/nosim/probe-<arm>-nosim-s<seed>/`.

| arm | γ | model seed | updates | read at | checkpoint saved |
|---|---|---|---|---|---|
| TRAV | 0.0 (inert under the mask, §2) | 1729, 2718, 3141 | 9,376, scored every 500 (+100, +250) | 8,000 (= v2 `update_count`, primary) and 9,376 | yes, at 9,376 |
| DIRECT | 0.0 (inert under the mask, §2) | 1729, 2718, 3141 | 9,376, scored every 500 (+100, +250) | 8,000 (primary) and 9,376 | yes, at 9,376 |

All six train on `train-g00` and are scored on `screen-g00`. There is no
learning-rate schedule, so the 8,000-update point of a 9,376 run is what an
8,000-update run would produce; 9,376 aligns every checkpoint with the existing
curves. Six runs are launched together under MPS (one launcher, 60 s stagger,
the sweep's resource gates, never a kill); nothing about the schedule is
conditional on a result.

**Verification of order.** `git log -1` of the commit that adds this file is
recorded in `private/read-run-v1/diagnostics/nosim/preflight.md` before the
launcher runs; every `probe.json` must carry `git_head` equal to that commit
and a `started_at` later than its timestamp. The report prints both.

## 4. Primary quantity and reference numbers

**Primary quantity: route-completeness (RC)** of the examined set — the
fraction of episodes whose examined edges contain a complete relation-matching
path to every target (`coverage.route_coverage`, equal to the evaluator's
`proof_valid` on 0 disagreements over every audited examined set). Read on
the gated `hops_2_4` non-abstain stratum, **n = 1124**, at update **8,000**
(primary; 9,376 reported beside it), at B = 128 and at the prefix budgets
8/16/32/64 of the same walk — valid because the walk's examined list is
prefix-consistent in the budget (`tests/test_read_run_ablation.py` asserts
`edge_ids(16) == edge_ids(128)[:16]` for TRAV and for the pool).

Reference values, gated non-abstain, n = 1124, from `model_input_audit.json`
(the pool rows equal `ceiling_sweep.json` count for count):

| reference | RC@8 | RC@16 | RC@32 | RC@64 | RC@128 |
|---|---|---|---|---|---|
| relation walker (`relation_walker_examined_set`) | 335 (29.80 %) | 836 (74.38 %) | **1112 (98.93 %)** | 1124 (100.00 %) | 1124 (100.00 %) |
| DIRECT pool (`structural_bfs_pool`) | 136 (12.10 %) | 338 (30.07 %) | 553 (49.20 %) | 784 (69.75 %) | **988 (87.90 %)** |

Per path length L (n): L2 (300), L3 (337), L4 (266), L5 (118), L6 (103).

| L | walker RC@32 | walker RC@128 | pool RC@32 | pool RC@128 |
|---|---|---|---|---|
| 2 | 300/300 | 300/300 | 300/300 | 300/300 |
| 3 | 337/337 | 337/337 | 250/337 | 337/337 |
| 4 | 266/266 | 266/266 | 3/266 | 266/266 |
| 5 | 115/118 | 118/118 | 0/118 | 67/118 |
| 6 | 94/103 | 103/103 | 0/103 | 18/103 |

L = 5 and L = 6 (n = 118 and 103) are where the pool fails
(67/118 and 18/103 at B = 128) and a walker does not; they are where learned
navigation would separate from BFS, and the report carries them as rows.

**Fixed constants of the table.** Pool reference **87.90 %** (988/1124); null band
±2 pp → **[85.90, 89.90] %** (counts 966–1010 of 1124); oracle line
**99.0 %** (1113 of 1124); walker RC@32 **98.93 %** − 5 pp → **93.93 %**
(1056 of 1124). None of the thresholds falls on an attainable count, so no
boundary tie can arise. Wilson lower bounds are reported beside every RC value
and are not part of any band condition.

**DIRECT-nosim** has no walk: its examined set is the model-free pool, so its
RC is 87.90 % by construction and the bands do not apply to it. It is
reported for what it isolates — what the answer head can learn from structure
alone given the pool — as exact-set accuracy, `exact_given_route_complete`
against its 87.90 % ceiling, and the §6 floors.

## 5. Outcome table — read per seed on TRAV-nosim, gated non-abstain, update 8,000

Let each seed's RC@128 fall in one of four levels: ≥ 99.0 %; (89.90, 99.0) %;
[85.90, 89.90] %; < 85.90 %. The band is read from the three seeds together:

| band | condition | reading | consequence for the graph model |
|---|---|---|---|
| **A** oracle-grade | every seed RC@128 ≥ 99.0 % **and** every seed RC@32 ≥ 93.93 % | structural navigation learned, with relation-follower precision | the earlier collapse was a shortcut preference, not an inability; insert can assume a learnable relation-conditioned walker (caveat: this generator's ambiguity profile is easy — §2) |
| **B** learned, imprecise | every seed RC@128 ≥ 99.0 % but the RC@32 condition fails in ≥ 1 seed | routes found, at a budget cost well above a relation-follower | navigation learnable; budget efficiency is a separate design problem before insert |
| **C** partial | every seed RC@128 > 89.90 % and at least one seed < 99.0 % | above the pool, not saturating | report magnitude with Wilson bounds; the per-L rows say where it fails |
| **D** pool-indistinguishable | every seed within [85.90, 89.90] % | null — the learned walk does no better than query-blind BFS | as frozen, this architecture does not learn navigation from structure at this budget; the walker design changes before insert |
| **E** below pool | at least one seed < 85.90 % and no seed > 89.90 % | directional negative — the learned scorer misdirects | as D, and the scorer is actively harmful |
| **F** seeds split | any other combination (some seed > 89.90 % and some seed ≤ 89.90 %) | inconclusive; every seed reported | the user decides on more seeds or a harder generator |
| **G** floor failure | any arm × seed fails an Amendment 04 §5 floor at 8,000 (§6) | not runnable at the v2 budget on that cell | block; whether to extend is the user's call, never automatic |
| **H** harness defect | identity variant ≠ baseline, any `route_complete` / `proof_valid` disagreement, or the prefix test fails (§9) | no reading | stop, report, fix, rerun |

Bands A–F are exhaustive and mutually exclusive in the three seeds' RC@128
levels (min ≥ 99.0 → A/B; 89.90 < min < 99.0 → C; min in the null band → D
if max is too, else F; min < 85.90 → E if max ≤ 89.90, else F). **Precedence:**
H over everything — a harness defect voids the reading until fixed. G is
evaluated on exact-set accuracy and is reported *beside* the A–F band; neither
suppresses the other, because a walk can be route-complete while the head is
degenerate and vice versa, and both facts are needed. The band is read at
8,000 only; the 9,376 reading is reported beside it and does not change the
letter.

Descriptives carry no thresholds and enter no band: exact-set accuracy,
`exact_given_route_complete` (TRAV: walk × head; DIRECT-nosim: head against
the pool ceiling), per-L RC, RC@8/16/64, the learning curves, the controls,
and — descriptive, same generator, different input — the same seeds'
with-similarity TRAV rows from the γ sweep beside the masked rows.

## 6. Floors and plateau reading, applied unchanged

**Amendment 04 §5 floors**, per arm × seed on the gated stratum at 8,000 (and
reported at 9,376): one-sided 95 % Wilson lower bound of exact-set accuracy
strictly above 1/15 **and** accuracy ≥ 7.67 %; ≥ 8 distinct predicted classes;
prediction entropy ≥ 1.00 nats. Failure is band G for that cell and is
reported, never used to exclude a run.

**Amendment 09 §2 plateau reading**, applied literally to each run's
exact-set-accuracy curve (checkpoints at 100, 250, 500, 1,000, …, 9,000,
9,376; qualifying = left uniform under Amendment 04 §4 criterion (L), the
floors, and two consecutive steps ≤ 1.00 pp; plateau = start of the final
unbroken qualifying run of ≥ 3 checkpoints reaching the last checkpoint), and
— same mechanics, RC in place of accuracy — to the **RC@128** and **RC@32**
curves. A curve that has not plateaued by 9,376 is reported as not plateaued.
**No automatic extension**: Amendment 04 §4's extension rule is the user's
call and is not invoked by the report.

## 7. What this does not authorise

No holdout is generated, read or opened, and no path containing `holdout` or
`heldout` is opened by any Track N script. No v2 data is generated. The
generator (`_assign_similarity` included) is unchanged. No arm, metric, seed,
budget candidate, threshold or frozen digest changes, and
`training-config.v1.json` is untouched. The masked run is a screening
ablation, not a new arm: it emits no receipt, and no comparison between a
masked run and any with-similarity run, or between TRAV-nosim and DIRECT-nosim,
is a result. Amendment 10 stays pending review. MPS is started and stopped by
the user only; runs are stopped only via `stop_run.sh <pidfile>`.

## 8. Interpretation for the graph model, per band

- **A.** The frozen architecture can learn relation-conditioned navigation from
  structure alone on this generator, at walker precision. The design question
  moves to whether that survives a harder ambiguity profile (`generator_grid.json`
  and design notes §1.6 say where the tree grows), and the insert design may
  assume a learnable walker as its substrate. It does *not* say the
  with-similarity checkpoints navigated — they did not — only that the
  shortcut was preferred, not required.
- **B.** Navigation is learnable but the learned scorer spends budget on
  non-route edges; RC@8/16/32 against the walker say how much. Precision, not
  reachability, becomes the design problem, and the successor's budget/stop
  rule (design notes §2.5) is the place to solve it.
- **C.** Partial navigation. The per-L rows locate the failure (expect the
  L = 5/6 rows, where the pool fails, to carry it); the Wilson bounds bound the
  magnitude. Whether to add seeds, updates or a generator change is the user's
  call.
- **D.** The learned walk is no better than a query-blind BFS at this budget:
  as frozen, the architecture does not learn navigation from structure within
  9,376 updates. Since the inputs suffice in principle (§2: relations are
  present per edge, the query GRU state carries position), this reads as an
  optimisation/architecture limit of the frozen model, and the walker design
  changes before insert is attempted.
- **E.** The scorer actively steers away from routes — worse than not walking
  adaptively. Same consequence as D with the added fact that the learned
  preference is harmful, which the per-L and RC@b rows should make legible.
- **F.** Seeds disagree; every seed is reported and nothing is concluded.
- **G / H.** As stated in §5.

## 9. Controls, thresholds fixed now

1. **Identity variant** (H if it fails). Each TRAV checkpoint is re-scored by
   `scripts/read_run_gamma_checkpoint_diag.py --constant-similarity 0`: with the
   checkpoint's recorded `masked_similarity_ppm` equal to the constant, the
   "flattened" variant must equal the baseline on every episode
   (`identity_differing_episodes` = 0) and `baseline_matches_probe_final_row`
   must hold.
2. **Shuffled serialization** on each TRAV checkpoint: |Δ| < 1.00 pp on
   exact-set accuracy **and** on RC@128 → clean; otherwise Concerning. A
   Concerning control is reported beside that seed's band and flags the
   reading; it does not change the letter.
3. **Cross-check** (H if it fails): `route_complete` equals `proof_valid` on
   every scored examined set of every variant, and the probe's own tally at
   the final row equals the diag's baseline.
4. **Prefix property** (H if it fails): the unit tests asserting
   `edge_ids(16) == edge_ids(128)[:16]` for TRAV and the pool pass at the
   commit the runs record.
5. **Order**: every `probe.json` `git_head` equals the commit recorded in
   `preflight.md` and every `started_at` post-dates it.

Every number the report quotes is copied from `screen.jsonl`, `probe.json`,
`checkpoint_diag.json`, `model_input_audit.json`, `ceiling_sweep.json` or
`gamma_sweep_curves.json` by `scripts/read_run_nosim_report.py`; none is typed.
