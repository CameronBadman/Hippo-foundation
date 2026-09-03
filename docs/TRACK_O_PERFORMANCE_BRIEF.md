# Optimisation brief: Track O traversal training

## Status: scoped work item, measured baseline, not yet started

Written 2026-09-03 while the first Track O runs were finishing, so that whoever
takes this on starts from measurement. The first guess — that the Python
featurisers were the bottleneck — was **wrong**, and the profile below is the
correction. Do not re-optimise from intuition.

## Baseline, measured

| quantity | value |
|---|---|
| TRAVV2 | **2.56 s/update** (90-update run, solo, RTX-class GPU) |
| TRAVV1 (frozen v1, same data, same budget) | 0.69 s/update |
| six concurrent under MPS | 2.84 s/update each — concurrency costs only ~11 % |
| worker CPU | 106 % (one core pegged per run) |
| GPU SM utilisation | 66–83 % |
| **GPU memory utilisation** | **5 %** |
| **GPU power** | **74 W of 300 W**, SM clock 2775 MHz (not throttled) |
| RSS | 2.0 GB/run after streaming the split |

## Where the time actually goes

Featuriser micro-benchmarks (per call, and per 2.56 s update at 128 episodes ×
~10 expansions, out-degree 6):

| featuriser | per call | calls/update | time | share |
|---|---|---|---|---|
| `pair_features` | 1.16 µs | 322,560 | 0.37 s | 14.6 % |
| `context_features` | 0.85 µs | 53,760 | 0.05 s | 1.8 % |
| `candidate_features` | 3.17 µs | 7,680 | 0.02 s | 1.0 % |
| `query_cross_features` | 0.34 µs | 61,440 | 0.02 s | 0.8 % |
| **total featurisation** | | | **0.46 s** | **18 %** |

So 82 % is elsewhere. The GPU counters name it: 5 % memory utilisation at a
quarter of the power budget, with the clock maxed, is the signature of **many
tiny kernel launches**, not of computation. Each update runs ~10 sequential walk
rounds × 8 accumulation steps ≈ 80 forward passes, each through 8 traversal
blocks × (2 `MultiheadAttention` + FFN), on tensors of roughly `[16, 6, 256]`.
The device spends its time being handed work.

## Targets, in expected-payoff order

1. **Widen the microbatch.** `training-config.o1.json` uses microbatch 16 ×
   accumulation 8 = 128 effective. Microbatch 64 × accumulation 2 is the same
   effective batch and the same arithmetic (modulo float reassociation) with
   **4× fewer rounds of small tensors**. Largest single lever; it is a config
   change, so it belongs to a new preregistration, not to a run in flight.
2. **`torch.compile` or CUDA graphs over the block stack.** Exactly the
   "many small identical kernels" case they exist for. Watch that
   `torch.use_deterministic_algorithms(True)` is preserved.
3. **numpy for the nested-list → tensor conversion.** `score_expansions` builds
   4-deep Python lists (`pair_rows` is `[R][G][X][32]`) and hands them to
   `torch.tensor`. Build them as numpy arrays instead; likely most of the
   remaining Python cost, and it subsumes target 5.
4. **Cache `pair_features` across rounds.** It depends only on the ordered edge
   pair, not on the prefix, so the same pair is recomputed every round it
   appears in. A per-episode memo is straightforward.
5. **Vectorise the featurisers** — last, since they are only 18 %.

Not useful, with reasons: **a better GPU** (the card is coasting at 74 W and 5 %
memory utilisation); **a Rust rewrite of the model** (cannot reduce CUDA launch
overhead, and leaving PyTorch for `tch`/`burn`/`candle` is an enormous rewrite
for the 18 % slice, against a dependency list pinned by
`tests/test_no_training_surface.py` precisely to keep the supply chain
auditable). Rust *would* pay on the **generator** — pure combinatorial path
enumeration, 0.2 s/episode with 17 % rejection on `deg6_len8_v4_rep`, no PyTorch
involved — if a later iteration wants much larger splits or a harder ambiguity
regime.

## Correctness constraints — this is a refactor under test, not a rewrite

Any change must preserve, and be shown to preserve:

- `tests/test_read_run_model_v2.py::test_stable_score_is_invariant_to_visit_order`
  — the property the architecture exists for.
- `test_score_cannot_see_an_unexpanded_targets_out_edges` — the no-lookahead
  guard; a vectorised featuriser that takes the raw `visible` dict instead of the
  guarded `EpisodeIndex` accessor silently reopens it.
- `test_walk_reproduces_the_relation_walker_on_the_walker_exact_cell` and the
  stop-rule behaviour.
- `expected_trainable_parameter_count_v2` exactly equal to the torch count, and
  within 1 % of v1's 10,257,937.
- Determinism under `torch.use_deterministic_algorithms(True)`.

**Add a golden-output test before optimising**: fix a seed and a small episode
set, record `edge_ids`, `routes`, `stop_reason` and `logits`, and assert the
optimised path reproduces the first three exactly and the logits to a stated
tolerance. Without it, a speedup that quietly changes the walk is
indistinguishable from one that does not.

## Known defects to fix in the same pass

Three from the design notes, all cheap and all found during the first runs:

- **§2.19** the supplied-prefix path skips the frontier block, so `endpoints`
  and `routes` are empty and the answer head's 12 label-carrying input
  dimensions are zero for the whole teacher-forced phase. Teacher forcing should
  change *which prefixes are scored*, never *what the head sees*. Add a test
  asserting every training mode presents the head an identically-shaped input.
- **§2.18** the answer competes with the walk summary for the same 256
  dimensions; give it its own path and combine at the logit level.
- **§2.17 / §2.21** the read path should emit a relevance set as its product,
  scored by precision and recall, with the examined count remaining its cost.


---

# Results of the optimisation pass (2026-09-03)

**Achieved 2.25x**, from 3.003 s/update to 1.337 s at microbatch 128 x 1.
Short of the 4-6x target, and the reason is structural rather than a missed
optimisation — recorded below so the next attempt does not re-tread it.

| step | s/update | cumulative |
|---|---|---|
| baseline (microbatch 16 x 8) | 3.003 | — |
| microbatch 128 x 1 alone | 1.773 | 1.44x |
| + vectorised featurisers | 1.398 | 2.15x |
| + lazy structural sort | 1.337 | **2.25x** |

**What worked.**

- *Vectorised featurisers* (`features_v2.py`). The pair grid alone is 9.0x
  faster; end to end this contributed 1.27x on top of the batch shape. The
  scalar versions stay as the reference and are checked elementwise.
- *Wider microbatch.* Same arithmetic — the loss is a per-episode mean before
  the batch mean — with a quarter of the rounds of small tensors.
- *Lazy structural sort.* `EpisodeIndex.__init__` was SHA-256-sorting every
  node's out-edge group at construction: 122,706 `_structural_order` calls per
  update, when a walk expands about ten nodes per episode. Sorting on first
  access to a node's group is identical in output and removes the rest.

**What was tried and rejected, with the measurement.**

- *`torch.compile` on the traversal blocks* (`dynamic=True`): **1.02x**, and it
  **changed the walk** — `edge_ids`, `routes` and `stop_reason` all differed
  from eager. Inductor is free to re-associate reductions, and the frontier
  tie-break sums two detached float32 values, so a near-tie flips and the walk
  diverges. Both a failure on speed and a failure against the golden fixture, so
  it is out. CUDA graphs were not attempted for the related reason that the
  candidate group and context length vary per round, so the shapes are not
  static without bucketing that would itself change the masked-attention
  numerics.

**Where the floor is, and why it is not an optimisation problem.**

At the current shape the backward pass is **47 % of the step** (0.62 s of
1.34 s) and nothing above reaches it. The remaining forward-side Python —
`candidate_features` and `context_features` still looping internally, the last
`torch.tensor` and `torch.stack` calls — totals about 10 % of the step, so
eliminating all of it would give roughly 2.5x, not 4x.

The cause is the walk's shape: a training update runs about twelve *sequential*
rounds, each applying eight traversal blocks, so the autograd graph is roughly
ninety-six small block applications and the backward is ninety-six small
backward passes. The work is not large; the launches are many, and they cannot
be batched because round k+1 depends on the edge chosen in round k.

**The one idea that reaches it, not attempted here.** Because `f` is a pure
function of `(query, prefix, edge)` and the walk's decisions are made on
`.detach()`ed scores, the walk does not need gradients. A two-pass forward —
run the walk under `no_grad` to determine the examined `(prefix, candidate)`
set, then score that whole set **once** with gradients — would collapse ninety-six
small backward passes into one large one. The walk is fully determined by pass
one, so pass two's float differences cannot change `edge_ids`, `routes` or
`stop_reason`, which is exactly what the golden fixture asserts. It costs a
second forward (cheaper without graph construction) and is a real restructuring
of `forward`, so it is a decision to take deliberately rather than a tidy-up.

---

# The two-pass forward: a prediction that was wrong (2026-09-04)

The brief above proposed one idea that reached the backward-pass floor — walk
under `no_grad`, then score the examined set once with gradients — and estimated
a further 1.5-2x. **Built as `model_v3`, it delivers about 1.0x per update.**
Recorded here in full, because the reasoning error is reusable.

**Corrected 2026-09-04 after a like-for-like measurement.** The first reading
of this compared v3 exhausting against v2 *stopping at two endpoints* — two
different jobs — and concluded the two-pass forward was level or slightly
slower. That was wrong, and the correction runs the other way: `model_v2`
supports `stop_rule="exhaust"`, so both builds can be measured on the identical
job, and on it the two-pass forward is **1.35x faster**.

| build | job | s/update | expansions/episode | edges/episode |
|---|---|---|---|---|
| v2, interleaved | budget 64, stop at 2 | 1.165 | 6.55 | 38.4 |
| v2, interleaved | **exhaust, no budget** | 1.608 | 7.96 | 46.5 |
| v3, two-pass | **exhaust, no budget** | **1.188** | 7.98 | 46.5 |

So the two-pass split does pay: 1.608 to 1.188 s/update on the same work. It is
also worth noting that v3 exhausting (1.188 s) costs about what v2 cost while
stopping early (1.165 s) — the restructure pays for the extra 22 % of expansions
that Track P's exhaustive training needs.

**Two errors, in opposite directions, both from comparing the wrong things.**
The original estimate of 1.5-2x counted backward's saving and not the cost of
pass 1's second forward. The correction to "level" then compared unequal jobs
and normalised by expansions to compensate — a ratio invented after seeing a
disappointing number, which happened to favour the new code and was still an
underestimate. The measurement that settles it took one run of a flag `model_v2`
already had. Measure the like-for-like before reaching for a normalisation.

**Why the estimate was wrong.** The autograd graph does collapse from ~96 small
block applications to one wide one, and backward was 47 % of a v2 step. But
pass 1 is a *second forward* that v2 never paid. Halving something that is 47 %
of the step while adding back most of the other 53 % nets out near zero. The
estimate counted the saving and not the new cost.

**A larger error found on the way, worth more than the result.** The first
version of `model_v3` walked each episode independently, calling
`score_expansions` once per expansion with a batch of one — roughly a thousand
batch-size-1 calls per update where v2 issues a dozen wide ones. It ran at
**7.308 s/update, six times slower than v2**, and the two-pass idea looked
refuted. It was not; the batching was. Pass 1 now keeps v2's round structure,
batched across episodes, and pass 2 adds one wide call on top. Any future
restructuring of this walk should check the *shape* of the calls it makes before
concluding anything about the idea it is testing.

**The two-pass split earns its place twice over.** Beyond the 1.35x, the
examined set, the endpoint registrations and the decision points are all fixed
before any gradient is taken, which is what lets the stop head train off-policy
on an exhaustive walk and what makes the answer head's inputs identical across
supervision modes (the design note 2.19 fix). Those were the reasons Track P
needed it; the speed turned out to be real as well.

**Cumulative, like-for-like.** Against the original 3.003 s/update baseline
(v2, microbatch 16 x 8, budget 64) the optimisation pass reached 1.165 s on that
same job — **2.58x**. Track P's job is larger: v2 would need 1.608 s to exhaust,
and v3 does it in 1.188 s. Quoting a single cumulative number across the two
jobs would flatter the result, so both are given.
