# Phase 2B staged-write process-state runbook

## Boundary

Phase 2B is a deterministic, preparation-only fixture for write-policy
semantics. It evaluates one proposed observation against one immutable process
snapshot and emits one of `attach`, `update`, `deprecate`, `new_node`,
`duplicate`, `conflict`, `stage`, or `ignore`.

The implementation cannot train a model or commit a patch to canonical state.
Every patch is detached, is applied only to a disposable copy during replay,
and carries exact forward and inverse preconditions. Every schema, example,
manifest, report, ledger, and audit fixes `training_authorized` to `false`.

## Frozen inputs and outputs

The additive Phase 2 v2 contracts are under `schemas/phase2/v2/`. They do not
change the frozen Phase 2A v1 contracts or fixtures.

Generation reads:

- `registries/training-sources.v2.json`;
- one of `registries/phase2.process.training.v1.json` or
  `registries/phase2.process.development.v1.json`; and
- `quarantine/phase2-public-reservations.v2.json`.

The checked outputs under `fixtures/phase2/process/` contain 32 examples per
role, a transition report, a generation manifest, and a replay ledger. The
directory also contains process-only and mixed Phase 2 corpus audits plus the
raw, adapter, envelope, and contribution records from which the local
reservation index is re-derived.

These are declared candidates, not admitted training data. Both process source
entries retain pending rights review. The local reservation index proves only
that these examples do not collide with its checked public selectors; it is not
the missing complete Phase 0 confirmatory quarantine union.

## Prediction-time contract

The target is derived only from:

- the immutable snapshot at its declared `as_of` time;
- the proposal and evidence whose evidence timestamps do not exceed the
  proposal observation time;
- the bounded candidate frontier;
- visible scope status; and
- the frozen asymmetric risk policy.

Targets, later snapshots, accepted changes, other examples, replay results, and
private confirmatory material are excluded. Operation, grammar, world,
relation-composition, entity, and seed families are allocated to a role before
generation.

## Generate into an empty directory

The commands refuse to overwrite any output. Replace `$OUT` with a new local
directory.

```bash
hf-phase2 process generate \
  --registry registries/training-sources.v2.json \
  --spec registries/phase2.process.training.v1.json \
  --quarantine quarantine/phase2-public-reservations.v2.json \
  --output "$OUT/training.examples.jsonl" \
  --report "$OUT/training.integrity.json" \
  --manifest "$OUT/training.manifest.json"
```

Use the development spec and distinct output names for the other role.
Generation fails closed on contract or schema-lock errors, rights/spec binding
errors, quarantine matches, duplicate inputs or snapshots, oracle disagreement,
incomplete action/near-miss coverage, or a restricted shortcut diagnostic above
0.5.

## Replay and verify

Replay first regenerates the expected examples, report, and manifest. It then
applies each patch to a fresh snapshot copy, applies the declared inverse, and
writes a ledger only if the supplied inputs remain canonical and unchanged.

```bash
hf-phase2 process replay \
  --registry registries/training-sources.v2.json \
  --spec registries/phase2.process.training.v1.json \
  --quarantine quarantine/phase2-public-reservations.v2.json \
  --examples "$OUT/training.examples.jsonl" \
  --report "$OUT/training.integrity.json" \
  --manifest "$OUT/training.manifest.json" \
  --ledger "$OUT/training.replay.json"

hf-phase2 process verify \
  --registry registries/training-sources.v2.json \
  --spec registries/phase2.process.training.v1.json \
  --quarantine quarantine/phase2-public-reservations.v2.json \
  --examples "$OUT/training.examples.jsonl" \
  --report "$OUT/training.integrity.json" \
  --manifest "$OUT/training.manifest.json" \
  --ledger "$OUT/training.replay.json"
```

Verification requires exact deterministic equality, canonical bytes, every
bound hash, dual-oracle agreement, unchanged inputs, and exact rollback.

## Audit split isolation

```bash
hf-phase2 corpus audit \
  --manifest fixtures/phase2/process/training.manifest.v1.json \
  --manifest fixtures/phase2/process/development.manifest.v1.json \
  --report fixtures/phase2/process/training.integrity.v1.json \
  --report fixtures/phase2/process/development.integrity.v1.json
```

The v2 audit compares artifact, exact-input, normalized-input, snapshot,
entity, operation, grammar, world, relation-composition, entity-family, and
seed-family identities. It also accepts the frozen Phase 2A v1 manifest/report
pairs so isolation can be checked across both procedural families.

## Checked fixture observations

- Training JSONL: 32 examples,
  `sha256:9124fa3cb284c48af9d20887e615c06fa6986998928920567180b4b847e0326e`.
- Development JSONL: 32 examples,
  `sha256:9314281a37f68f10a2b1652e0ff4db2c5732682cc46458381fdff66042164ebc`.
- Both roles contain two direct and two near-miss scenarios associated with
  each action; the realized action counts are `5/3/2/2/3/3/7/7` in the action
  order above.
- Both transition oracles agree on all 64 targets and deltas. Every replayed
  patch rolls back to the exact starting snapshot hash.
- The process-only and mixed four-corpus audits report no cross-role overlap.
- Every eligible shortcut diagnostic is at or below 0.3125, below the frozen
  0.5 blocking threshold. Patch size reaches 0.4375 but is explicitly excluded
  because it is target-derived and unavailable at prediction time.

These observations are deterministic fixture checks, not predictive metrics or
evidence of model quality.

## Forbidden interpretations

Do not describe this milestone as training, learning, calibration, model
evaluation, canonical-memory mutation, rights approval, full quarantine
clearance, or readiness for production. A successful replay demonstrates only
the semantics and reversibility of these checked procedural transitions.
