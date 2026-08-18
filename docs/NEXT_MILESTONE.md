# Next milestone: Phase 2B staged-write process-state slice

## Outcome

Build a second deterministic first-party family that proves reversible staged
write decisions over immutable process-state snapshots. It must exercise the
write path without mutating canonical memory, training a model, or consuming
private confirmation data.

The milestone produces separate training-role and development-role candidate
artifacts for `attach`, `update`, `deprecate`, `new_node`, `duplicate`,
`conflict`, `stage`, and `ignore`. Every proposed change remains a detached
patch against a frozen input snapshot.

## Decision definition

Before generation, freeze:

- the unit of analysis: one proposed observation against one immutable graph
  snapshot and candidate attachment neighbourhood;
- prediction time: only the snapshot, proposed observation, visible evidence,
  risk class, scope, and bounded candidate frontier;
- outcome: one write-policy action plus a reversible staged patch or null;
- split unit: operation family, grammar, world, relation composition, entity
  family, and seed family; and
- error costs: unsupported overwrite, cross-scope attachment, and false
  deprecation cost more than staging or ignoring an ambiguous proposal.

No later state, accepted patch, evaluator output, or target from another example
may influence prediction-time features.

## Contract changes

Add independently locked Phase 2B contracts for:

- typed immutable state snapshots with node/edge lifecycle, scope, valid time,
  observation time, provenance, conflict, and risk state;
- proposed observations and bounded candidate attachment points;
- write-policy examples with the exact prediction-time snapshot, action,
  reversible patch, preconditions, postconditions, evidence, costs, role,
  quarantine binding, and generator lineage;
- generator specs allocating operation, grammar, world, composition, entity,
  and seed families before generation; and
- transition-integrity reports binding both oracle results, unchanged input
  hashes, staged-output hashes, action counts, overlap findings, duplicates,
  and shortcut diagnostics.

Extend the training-source registry rather than using the confirmatory
evaluation registry as training configuration. Rights remain pending and every
record must keep `training_authorized: false`.

## State and action semantics

Use conservative rules:

- `attach`: the observation is supported, in scope, and has one unambiguous
  existing attachment point;
- `update`: it revises a mutable candidate-state value with explicit temporal
  and provenance support;
- `deprecate`: evidence explicitly invalidates an existing candidate claim
  without erasing its history;
- `new_node`: the observation is supported but no compatible existing entity
  exists;
- `duplicate`: an equivalent supported claim already exists;
- `conflict`: supported evidence contradicts live state and cannot be safely
  resolved at prediction time;
- `stage`: a potentially useful change lacks evidence, identity, scope, or risk
  certainty required for a more specific action; and
- `ignore`: the proposal is irrelevant, unsupported, prohibited, or outside
  the visible scope.

Absence is never evidence for deprecation. Conflict never authorizes overwrite.
High-risk or irreversible canonical changes are outside this milestone.

## Independent verification

Implement two transition oracles that share only parsed immutable input types:

1. a declarative precondition/effect evaluator that derives admissible actions
   and a normalized patch; and
2. a copy-on-write state interpreter that tries each bounded action, validates
   invariants on the resulting candidate state, and compares the observable
   delta.

They must agree on the action, patch, preconditions, and postconditions. The
interpreter works on a fresh deep copy per example and must prove that the input
snapshot hash is unchanged before and after evaluation. Generated or predicted
patches may not become truth for later examples.

## Leakage and shortcut controls

- Allocate every dependency family to a role before generating rows; prohibit
  random row splitting.
- Keep action names and case types out of template IDs, example IDs,
  provenance, formatting, and prediction-time metadata.
- Quarantine exact and normalized state/proposal inputs plus every procedural
  dependency identifier against the explicitly bound public index.
- Reject cross-role artifact, snapshot, entity, operation, grammar, world,
  composition, or seed overlap.
- Record majority, operation-family, grammar, template, entity-count,
  candidate-count, patch-size, and risk-only baselines. Treat suspiciously high
  diagnostics as blockers until the shortcut is removed or justified.
- Add label-shuffle and proposal-only negative controls before any trainer is
  considered.

## Public CLI

Extend `hf-phase2` with preparation-only commands:

- `process generate` writes canonical examples, manifest, and transition
  report without overwriting outputs;
- `process verify` deterministically regenerates both oracle results and every
  bound hash;
- `process replay` applies staged patches only to disposable copies and emits a
  complete delta ledger; and
- `corpus audit` expands its overlap checks to operation/entity families and
  immutable snapshot hashes.

No command may train, fit, optimize, commit canonical state, or expose a model
surface.

## Acceptance criteria

- Each of the eight write actions has at least two distinct positive cases and
  explicit near-miss cases that should choose a safer action.
- Unknown, explicit negative, contradiction, temporal ordering, scope mismatch,
  duplicate identity, ambiguous attachment, cyclic reference, and high-risk
  cases agree across both oracles.
- Input snapshot bytes and hashes remain unchanged through generation, replay,
  and verification.
- Every non-null patch is reversible, provenance-complete, scoped, and produces
  the declared postcondition on a disposable copy.
- Training and development share no artifact, snapshot, entity, operation,
  grammar, world, composition, or seed family.
- Missing provenance, time, scope, risk, rights, split, quarantine, precondition,
  or rollback evidence fails validation.
- Output collisions, confirmatory generation, target-bearing metadata,
  oracle disagreement, cross-role overlap, and state mutation are rejected.
- Existing Phase 0, Phase 1, and Phase 2A tests and package smoke checks remain
  green.

## Explicit exclusions

This milestone does not add canonical writes, online learning, a trainer, ML
dependencies, model weights, private confirmation worlds, external source
acquisition, real Wikipedia/Wikidata transformation, or a production graph
store. Those remain behind later roadmap and authorization gates.
