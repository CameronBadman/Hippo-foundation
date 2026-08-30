# READ run v1 execution guide

The active experiment is the locally generated READ comparison frozen in
[`PREREGISTRATION.md`](PREREGISTRATION.md). Phase 0 v4.4 and the external-corpus
programme are parked. This runner downloads no corpus, uses no Hub or Drive
credential, and does not touch the final holdout until a committed code freeze
exists.

## Current boundary

The implementation supplies deterministic split generation, separated visible
and hidden streams, independent route reconstruction, all seven P0 gates, the
structural DIRECT pool, equal-capacity TRAV/DIRECT model code, fixed-step
training, proof-valid evaluation, and the frozen four-way decision rule.

No official train, screening, or final-held-out split has been generated. No
P0 report has authorized training. PyTorch is an optional runtime. Two
temporary, untrained model instances were used for a CPU forward/backward
smoke check; no official model, optimizer step, checkpoint, prediction, or
accuracy exists.

## Runtime setup

The governance and generator commands need only the base project environment.
The model runner additionally needs the `read-run` extra:

```console
uv sync --extra read-run
hf-read-run contracts
```

The raw 32-byte seed stays at `private/read-run-v1/heldout.seed` with mode
`0600`. Never print, commit, upload, or pass its bytes on the command line. The
CLI accepts only its file path and verifies the frozen SHA-256 commitment.

## Execution order

1. Generate all five train and screening gamma buckets into ignored private
   storage. Official sizes are fixed at 150,000 and 2,000 episodes per bucket.
2. Run `double-execute` for every screening bucket. Each run regenerates in two
   fresh processes with different locale, timezone, working directory, and
   Python hash seed.
3. Run `p0` with exactly five train roots, five screening roots, and five
   double-execution records. It always emits a report, including blockers.
4. If all seven P0 gates pass, commit the exact implementation and create the
   code-freeze evidence. The freeze inventories every READ-run Python file and
   binds the P0 report, training config, preregistration, repository commit, and
   coverage-selected budget.
5. Run all 16 Day-3 screening jobs: both arms, gamma 0 and 0.4, budgets 16, 32,
   64, and 128, model seed 1729. Report every accuracy-at-budget result. The
   budget already recorded from coverage cannot be changed by these results.
6. If no budget exceeds 90% DIRECT target-in-pool coverage, stop after the
   screening report. Otherwise run the 30 main jobs at the selected budget.
7. Only after the code freeze, generate each 15,000-episode holdout gamma
   bucket once. Retain its opening receipt. Evaluate all 30 checkpoints without
   changing code, configuration, thresholds, or arm definitions.
8. Run `decision` with exactly the 30 main summaries and publish the complete
   curve, seed values, broken-run ledger, ABSTAIN accuracy, proof-validity rate,
   and the preregistered decision.

Training commands reject non-train manifests, unregistered seeds or budgets,
missing code-freeze evidence, malformed P0 reports, fewer than seven passed
gates, and main budgets other than the coverage-selected value. Evaluation
credits a class prediction only when the scored edges also decode both valid
target routes.

## Expected storage, not a completed measurement

A 60-episode deterministic fixture produced about 6.5 KiB of compressed
model-visible data per episode. Linear extrapolation suggests roughly 5–6 GiB
for all official generated streams, before checkpoints and run logs. This is an
estimate from a small fixture, not a measured final corpus size; check free
space before official generation.
