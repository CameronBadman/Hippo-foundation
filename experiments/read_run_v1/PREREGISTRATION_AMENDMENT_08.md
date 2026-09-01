# READ run v1 — Preregistration Amendment 08

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-09-01. Records a new held-out master seed for E1-v2 and
the training configuration that goes with it. Amendments 02–07 and 09 stand.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`. This amendment adds two records
beside them; it edits neither.

## 1. Why a new seed

E1's holdout was generated and opened once under code freeze
`sha256:07d18b39…`, and all 30 main runs were evaluated against it. It is spent.
Holdout episodes are deterministic from seed, split, and index, so the existing
episodes cannot be reused at any budget — a retry needs a seed the frozen
preregistration cannot name.

`preregistration.v1.json` carries `heldout_seed_sha256` and is hash-pinned, so
the commitment cannot be changed in place. The new commitment therefore lives in
a separate record.

## 2. The new commitment

`experiments/read_run_v1/heldout-seed.v2.json`:

| field | value |
|---|---|
| `seed_version` | 2 |
| `heldout_seed_sha256` | `sha256:bfbbdf5c7d7bfde431483c3ccc1890cc7465bcefaf52f9f2be5f346cd065d726` |
| `supersedes` | `sha256:6183dc36b8a9fededaee99db385013d33785bc75de531937e65115d6d770c663` (v1) |
| `bound_preregistration_json_sha256` | `sha256:b28bfb07b90671cdf863b43557212973d6eadcba6530af90fec5f2fe5a76f717` |

Record digest: `sha256:cf962fe56f67f05f32f7326fc5788b0247337b5da290bb8e2a2e8441bc5da803`,
pinned as `FROZEN_HELDOUT_SEED_V2_SHA256` in `read_run/contracts.py`.

The raw 32 bytes live at `private/read-run-v2/heldout.seed`, mode `0600`, under
a gitignored directory. They are never printed, committed, or passed on a
command line; every CLI takes the file's path and verifies the commitment.

### Why a narrow record rather than a second preregistration

The record contains the seed, what it supersedes, and the preregistration digest
it is bound to — nothing else. "Provably identical to v1 except the seed" is then
true by construction, because there is nothing else in the file to differ. A full
`preregistration.v2.json` would duplicate fourteen documentation-only fields,
create a second source of truth that can drift, and then need a structural
comparison to re-establish a property the narrow shape never puts in question.

**The preregistration itself did not change.** Hypotheses, thresholds, arms,
decision rules, strata and the gamma=0 control are all v1's, unmodified and still
governing. A seed is the credential proving the holdout was fixed before
evaluation; rotating a credential does not re-found the experiment, and a v2
preregistration identity would falsely signal that the science moved.

**Amendment digests are deliberately not pinned in the record.** Amendment 05 was
corrected three times in a single session as the probe progressively refuted its
evidence. Had the seed record bound amendment digests, each honest correction
would have broken a cryptographic binding and forced a reissue. A rule that
penalises correction is the wrong rule for this repository; amendments govern in
prose and are cited, not hashed.

## 3. The training configuration that accompanies it

`experiments/read_run_v1/training-config.v2.json`, digest
`sha256:a9154e278d28dd186e4a47379923c8a6751a6a78f1509a653d423719c9aa50f2`,
pinned as `FROZEN_TRAINING_CONFIG_V2_SHA256`.

It differs from v1 in exactly two fields:

| field | v1 | v2 |
|---|---|---|
| `training.update_count` | 1172 | **8000** |
| `config_id` | `hippocampus-read-run-training-v1` | `hippocampus-read-run-training-v2` |

`config_id` is an identity field carrying no experimental content; it is changed
so the file does not misidentify itself, and it is called out here because
Amendment 04 §3 authorised `update_count` as the single changed knob and this is
technically a second difference. The committed test asserts the **complete
flattened difference set** is exactly these two, so a third cannot appear
unnoticed — an earlier version of that test compared only the `training`
sub-dict and would not have caught a top-level change.

Every other value is byte-identical: optimizer, learning rate, weight decay,
gradient clipping, microbatch size, accumulation, effective batch, loss weights,
`early_stopping: false`, mixed precision, determinism flags, and the whole
`model`, `fairness` and `selection` blocks.
`fairness.arm_specific_hyperparameters_allowed` remains `false`.

### Where 8,000 came from

Amendment 09's settled-streak plateau rule, applied identically to both arms
over their complete 9,376-update probe curves:

| arm | qualifying checkpoints | final unbroken run | plateau |
|---|---|---|---|
| DIRECT | 7500, 8000, 8500, 9000, 9376 | `[7500, 8000, 8500, 9000, 9376]` | **7,500** |
| TRAV | 4500, 8000, 8500, 9000, 9376 | `[8000, 8500, 9000, 9376]` | **8,000** |

`update_count = max(7500, 8000) = 8000`, per Amendment 05 §3 as read under
Amendment 09 §2.

TRAV's isolated qualifying point at 4,500 is exactly the false positive
Amendment 09 was written to discard: it satisfies the pairwise test but is not
part of the run reaching the end, and the two checkpoints after it gained
+5.07pp and +3.11pp. Under Amendment 05's first-qualifying rule the answer would
have been 4,500 and the shared budget 7,500, training TRAV to less than half the
point at which it actually converged. The 3-checkpoint minimum also binds here:
TRAV's run is exactly four, so a shorter run would have been admissible without
it.

## 4. Run version

`run_version = 2` resolves this configuration and this seed **together**, as one
pair (`contracts.validate_preregistration`). Two independent version parameters
would admit a v2 configuration with the spent v1 seed, or a v1 configuration
with the fresh seed; neither may occur on an official path, and resolving both
from one number makes them unconstructible rather than merely forbidden. Both
digests activate in a single commit — a partial activation is refused.

## 5. What this does not authorise

No holdout is generated or opened by this amendment. E1-v2 still requires a full
regeneration under the new seed, a fresh seven-gate P0 report, the dev learner
gate of Amendment 04 §5, and a new code freeze before its holdout is opened once.

**Phase 3a remains blocked** on the TRAV edge-selection diagnostic at gamma=0,
which is unrelated to this amendment and reports separately.

`training_authorized` in Phase 0, Phase 1, and Phase 2 artifacts remains
mechanically `false`, pinned by `tests/test_no_training_surface.py`.
