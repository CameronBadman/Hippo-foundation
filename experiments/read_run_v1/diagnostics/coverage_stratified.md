# READ run v1 — stratified DIRECT coverage diagnostic

Diagnostic date: 2026-08-31. Task: Step 1 of the coverage diagnostic and
single-generator-fix work item.

This file reports structural measurements only. No model was instantiated, no
training step was taken, no holdout episode was generated, and no accuracy was
measured. All figures are properties of the generator and the
query-similarity-independent DIRECT pool.

## Provenance of the measured episodes

The task specified measuring "the existing prototype episodes" with no
regeneration. **No prototype episodes exist in this workspace.**
`private/read-run-v1/` contains only the 32-byte `heldout.seed`; the prototype
runs recorded in `DEVELOPMENT_LOG.md` did not retain their episodes.

Generation is deterministic from the committed seed and the committed code, so
the episodes were reconstructed rather than re-drawn: `split="screen"`,
`count=2000`, every gamma bucket, generator exactly as committed at `5451425`.
This produces the same worlds the prototype indices name, not new ones. This is
the screening domain `evaluate_p0(strict_counts=True)` pins, so these are the
official screening worlds, not a separate prototype population.

### The committed code does not reproduce the 82.25% figure

| Source | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|
| `DEVELOPMENT_LOG.md` prototype B, 2,000 worlds | 23.10% | 39.80% | 59.95% | 82.25% |
| Committed code, 2,000 screening worlds (this run) | 23.50% | 40.85% | 60.45% | **81.30%** |
| `DEVELOPMENT_LOG.md` prototype B, 200-world check | — | — | — | 81.0% |
| Committed code, first 200 screening worlds (this run) | 22.50% | 41.50% | 59.50% | **81.00%** |

The 200-world check reproduces exactly, which establishes that this harness is
faithful to the committed generator. The 2,000-world row does not reproduce and
predates a subsequent code change. This was anticipated, not discovered here:
`DEVELOPMENT_LOG.md` already states that "The official 2,000-episode P0/Day-3
evidence must be regenerated from committed code", and the task states that
prototype worlds may differ from official generation.

**The governing number is 81.30%** set-level at gamma=0, B=128 — not 82.25%.
Both are below the preregistered 90% threshold, so the blocked status of gate 7
is unchanged.

## Breakdown 4 (gate) — set-level versus node-level

These are reported first because Step 2 makes them a gate on every number below.

The shipped indicator in `gates.py:185` is
`set(episode.hidden["target_nodes"]) <= reached`: a subset test requiring **every**
target node of both valid routes to be the target of some pooled edge.

**The 82.25% figure was already set-level.** The governing number therefore does
not move down; node-level is the strictly weaker quantity, reported here for
completeness only.

| Level | Definition | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| Set-level (governing) | all target nodes pooled | 470/2000 (23.50%) | 817/2000 (40.85%) | 1209/2000 (60.45%) | 1626/2000 (81.30%) |
| Node-level | at least one target node pooled | 794/2000 (39.70%) | 1223/2000 (61.15%) | 1611/2000 (80.55%) | 1916/2000 (95.80%) |

A third quantity is reported as supplementary evidence because evaluation is
strictly stronger than target-in-pool: a prediction is credited only when the
scored edges also decode both valid routes.

| Level | Definition | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| All-route-edges | every edge of both valid routes pooled | 449/2000 (22.45%) | 735/2000 (36.75%) | 1041/2000 (52.05%) | 1391/2000 (69.55%) |

Proof-validity coverage (69.55% at B=128) sits well below target-in-pool
coverage (81.30%). Clearing the preregistered 90% target-in-pool gate does not
by itself guarantee that DIRECT can produce a proof-valid answer at the same
rate. This does not change the preregistered gate, which is defined on
target-in-pool, but it is recorded so the gap is not rediscovered later.

## Breakdown 5 (gate) — coverage by gamma

| B | gamma=0.0 | gamma=0.1 | gamma=0.2 | gamma=0.3 | gamma=0.4 |
|---|---|---|---|---|---|
| 16 | 470/2000 (23.50%) | 470/2000 (23.50%) | 470/2000 (23.50%) | 470/2000 (23.50%) | 470/2000 (23.50%) |
| 32 | 817/2000 (40.85%) | 817/2000 (40.85%) | 817/2000 (40.85%) | 817/2000 (40.85%) | 817/2000 (40.85%) |
| 64 | 1209/2000 (60.45%) | 1209/2000 (60.45%) | 1209/2000 (60.45%) | 1209/2000 (60.45%) | 1209/2000 (60.45%) |
| 128 | 1626/2000 (81.30%) | 1626/2000 (81.30%) | 1626/2000 (81.30%) | 1626/2000 (81.30%) | 1626/2000 (81.30%) |

**The gamma gate passes, and by a stronger criterion than the task requires.**
Coverage is not merely equal within sampling noise; the per-episode indicator is
bit-identical across all five gamma buckets for all 2,000 worlds at all four
budgets, and so are `node_count`, `path_length`, `branch_depth`, `edge_count`
and both target hop distances.

This is structural rather than empirical. `_assign_similarity` mutates only
`query_similarity_ppm`; `_edge_order_key` hashes `router_seed`, `source`,
`target`, `relation` and `edge_id`, and never reads similarity. DIRECT pool
construction is therefore independent of query similarity by construction.

The shipped `direct_pool_invariance_gate` was run on 400 paired worlds per gamma
as an independent confirmation and returned `passed: true` with identical
coverage columns (0.2275 / 0.3850 / 0.5750 / 0.8025). That gate raises on any
per-episode divergence in pool membership or indicator, so its passing is itself
the invariance evidence.

**No correctness bug in pool construction. Step 3 proceeds.**

## Breakdown 1 — coverage by world size

| Stratum | Episodes | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| 64–95 nodes | 326 | 71/326 (21.78%) | 156/326 (47.85%) | 231/326 (70.86%) | 310/326 (95.09%) |
| 96–127 nodes | 336 | 92/336 (27.38%) | 156/336 (46.43%) | 221/336 (65.77%) | 286/336 (85.12%) |
| 128–159 nodes | 320 | 86/320 (26.88%) | 138/320 (43.12%) | 208/320 (65.00%) | 271/320 (84.69%) |
| 160–191 nodes | 314 | 67/314 (21.34%) | 118/314 (37.58%) | 177/314 (56.37%) | 243/314 (77.39%) |
| 192–223 nodes | 335 | 84/335 (25.07%) | 121/335 (36.12%) | 181/335 (54.03%) | 250/335 (74.63%) |
| 224–256 nodes | 369 | 70/369 (18.97%) | 128/369 (34.69%) | 191/369 (51.76%) | 266/369 (72.09%) |

A real but shallow gradient: 95.09% down to 72.09% at B=128, a spread of 23
points across the full 64–256 range.

## Breakdown 2 — coverage by path length

| Stratum | Episodes | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| path length 2 | 397 | 397/397 (100.00%) | 397/397 (100.00%) | 397/397 (100.00%) | 397/397 (100.00%) |
| path length 3 | 441 | 58/441 (13.15%) | 336/441 (76.19%) | 441/441 (100.00%) | 441/441 (100.00%) |
| path length 4 | 395 | 5/395 (1.27%) | 29/395 (7.34%) | 215/395 (54.43%) | 395/395 (100.00%) |
| path length 5 | 379 | 6/379 (1.58%) | 27/379 (7.12%) | 78/379 (20.58%) | 210/379 (55.41%) |
| path length 6 | 388 | 4/388 (1.03%) | 28/388 (7.22%) | 78/388 (20.10%) | 183/388 (47.16%) |

A far sharper gradient: 100% down to 47.16% at B=128, a spread of 53 points.
Path lengths 2, 3 and 4 are fully covered at B=128; lengths 5 and 6 are the
entire deficit.

## Breakdown 3 — coverage by hop distance

The task specifies "hop distance from nearest router seed to target". **This has
no referent in the implementation.** `router_seed` is a 16-byte hex string
consumed only by `_edge_order_key` to order each node's outgoing edges; it is not
a node and has no placement. The measurable analogue is BFS hop distance from
`start_node`, which is where `structural_bfs_pool` actually roots its traversal.
Distance to the farthest target is reported, since the governing indicator is
set-level.

| Stratum | Episodes | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| 2 hops | 412 | 412/412 (100.00%) | 412/412 (100.00%) | 412/412 (100.00%) | 412/412 (100.00%) |
| 3 hops | 536 | 58/536 (10.82%) | 404/536 (75.37%) | 536/536 (100.00%) | 536/536 (100.00%) |
| 4 hops | 570 | 0/570 (0.00%) | 1/570 (0.18%) | 261/570 (45.79%) | 570/570 (100.00%) |
| 5 hops | 412 | 0/412 (0.00%) | 0/412 (0.00%) | 0/412 (0.00%) | 108/412 (26.21%) |
| 6 hops | 70 | 0/70 (0.00%) | 0/70 (0.00%) | 0/70 (0.00%) | 0/70 (0.00%) |

This is the sharpest stratifier of the three and is very nearly deterministic:
at B=128, targets within 4 hops are covered 100% of the time, targets at 5 hops
26.21%, and targets at 6 hops never.

### Hop distance is the mechanism, not an independent knob

| Path length | Distribution of farthest-target hop distance |
|---|---|
| 2 | 2 hops: 397 |
| 3 | 2 hops: 5, 3 hops: 436 |
| 4 | 2 hops: 5, 3 hops: 30, 4 hops: 360 |
| 5 | 2 hops: 3, 3 hops: 34, 4 hops: 106, 5 hops: 236 |
| 6 | 2 hops: 2, 3 hops: 36, 4 hops: 104, 5 hops: 176, 6 hops: 70 |

Hop distance is not determined by path length — background out-degree-3 edges
create shortcuts, so length-6 routes spread across 2–6 hops. But the generator
exposes no knob that sets hop distance directly. Of the three knobs the task
offers, `MAX_PATH_LENGTH` is the only one that moves it.

## Plateau curves

Coverage conditional on each candidate restriction, measured on this sample.
These are selection predictors only: changing a generator constant perturbs the
draw, so the selected fix must be confirmed by regeneration.

### Capping MAX_PATH_LENGTH at P

| P | Episodes | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| 2 | 397 | 397/397 (100.00%) | 397/397 (100.00%) | 397/397 (100.00%) | 397/397 (100.00%) |
| 3 | 838 | 455/838 (54.30%) | 733/838 (87.47%) | 838/838 (100.00%) | 838/838 (100.00%) |
| 4 | 1233 | 460/1233 (37.31%) | 762/1233 (61.80%) | 1053/1233 (85.40%) | 1233/1233 (100.00%) |
| 5 | 1612 | 466/1612 (28.91%) | 789/1612 (48.95%) | 1131/1612 (70.16%) | 1443/1612 (89.52%) |
| 6 | 2000 | 470/2000 (23.50%) | 817/2000 (40.85%) | 1209/2000 (60.45%) | 1626/2000 (81.30%) |

### Capping MAX_NODES at N

| N | Episodes | B=16 | B=32 | B=64 | B=128 |
|---|---|---|---|---|---|
| 95 | 326 | 71/326 (21.78%) | 156/326 (47.85%) | 231/326 (70.86%) | 310/326 (95.09%) |
| 111 | 511 | 129/511 (25.24%) | 250/511 (48.92%) | 363/511 (71.04%) | 475/511 (92.95%) |
| 127 | 662 | 163/662 (24.62%) | 312/662 (47.13%) | 452/662 (68.28%) | 596/662 (90.03%) |
| 143 | 808 | 206/808 (25.50%) | 378/808 (46.78%) | 546/808 (67.57%) | 721/808 (89.23%) |
| 159 | 982 | 249/982 (25.36%) | 450/982 (45.82%) | 660/982 (67.21%) | 867/982 (88.29%) |
| 191 | 1296 | 316/1296 (24.38%) | 568/1296 (43.83%) | 837/1296 (64.58%) | 1110/1296 (85.65%) |
| 223 | 1631 | 400/1631 (24.52%) | 689/1631 (42.24%) | 1018/1631 (62.42%) | 1360/1631 (83.38%) |
| 256 | 2000 | 470/2000 (23.50%) | 817/2000 (40.85%) | 1209/2000 (60.45%) | 1626/2000 (81.30%) |

## Selected knob

Path length dominates. Its 53-point spread against world size's 23 points, and
the near-deterministic hop-distance table it drives, identify it as the cause of
the deficit rather than a correlate.

The world-size route is not merely weaker, it is statistically unsafe. Capping
`MAX_NODES` at 127 yields 596/662 = 90.03% at B=128 — a point estimate that
clears `coverage > 0.9` by four hundredths of a point on 662 episodes. Its
one-sided 95% Wilson lower bound is 87.95%, so it would satisfy the gate
while being statistically indistinguishable from a failure.

Selected change: **`MAX_PATH_LENGTH` 6 → 4**, predicted to reach 100% set-level
coverage at B=128 and gamma=0. `MAX_PATH_LENGTH = 5` predicts 89.52% and is a
genuine miss, not a rounding question.

This is a single-knob change. `MIN_PATH_LENGTH` (2), `MIN_NODES`/`MAX_NODES`
(64/256), `OUT_DEGREE` (3), and the budget set are all unchanged, and B is not
increased.
