# READ run v1 development log

This log records generator and harness observations made before any model was
instantiated and before any accuracy was observed. It is not an experiment
result.

## 2026-08-31 — preregistration freeze

- Committed preregistration v1 and the SHA-256 commitment to a private 32-byte
  seed in commit `e0f5c3d` before creating `read_run` generator code.
- The private preimage remained ignored and mode `0600`.
- Phase 0 v4.4 work stopped without source changes; it remains parked.

## 2026-08-31 — structural generator prototypes

Prototype A used four outgoing edges per node. On 2,000 screening-domain base
worlds, before any model code ran, measured gamma was 0.00000, 0.10051,
0.20158, 0.30133, and 0.39735 for requested gamma 0 through 0.4. DIRECT
all-target coverage at budgets 16, 32, 64, and 128 was respectively 14.15%,
28.80%, 48.50%, and 71.55%. Every per-world pool indicator was identical
across gamma.

This was a failed structural design check: no preregistered budget cleared the
90% selection threshold. No accuracy, loss, prediction, checkpoint, or holdout
value existed.

Prototype B reduced background out-degree to three while retaining two valid
branch actions plus a distractor at every route state. At gamma 0 on the same
2,000 screening-domain indices, coverage was 23.10%, 39.80%, 59.95%, and
82.25%. A separate 200-world all-gamma implementation check again found exact
per-world invariance; its B=128 estimate was 81.0%. Prototype B remains the
implemented candidate because it keeps the required distractor and lowers
storage/compute without reading labels or query similarity during pool
construction. It still does not clear the main-run threshold.

These observations are retained because silently tuning graph density until a
budget passed would undermine the purpose of the coverage control. The
official 2,000-episode P0/Day-3 evidence must be regenerated from committed
code. If it also fails to exceed 90%, the main sweep stops as preregistered.

## 2026-08-31 — implementation checks

- Construction truth and the independent backwards oracle agreed exactly on
  100 early gamma variants and on the focused automated suite.
- Two fresh-process 60-episode generations remained byte-identical after
  perturbing locale, timezone, working directory, and Python hash seed.
- A Python formatter was accidentally pointed at the JSON training config and
  inserted invalid trailing commas. JSON parsing failed immediately. The file
  was restored by explicit patch before any generator, gate, or model run used
  it; its canonical digest matches the code lock.
- No official split, holdout opening, training update, or accuracy measurement
  occurred during these checks.

## 2026-08-31 — runtime smoke check

- A temporary CPU-only runtime instantiated the same model class once per arm
  from the same model seed. Both untrained instances had 10,257,937 trainable
  parameters and the same initial-state digest.
- One synthetic batch completed forward and backward passes for each arm at
  B=16. Every parameter received a gradient. No optimizer step, checkpoint,
  prediction file, screening accuracy, or holdout accuracy was produced.

## 2026-08-31 — reproducibility-evidence binding fix

- An adversarial review found that the first P0 implementation checked a
  double-execution record's split, gamma, and count but did not compare its
  digests with the exact screening root consumed by P0. It also trusted split
  manifest digests without rehashing the compressed streams at consumption.
- The corrected path rehashes both streams and both manifests, requires public
  and private manifest agreement, checks the frozen seed commitment for every
  official root, and requires gate-6 replay digests to equal the consumed
  screening artifacts exactly. A forged replay digest is now rejected by a
  regression test.
- This was caught before an official split, P0 report, model run, or accuracy
  existed. No result was invalidated.
