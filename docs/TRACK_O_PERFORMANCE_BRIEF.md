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
