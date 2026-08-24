# Phase 2A procedural open-world slice

## Status and boundary

Phase 2A is implemented locally as a deterministic, first-party candidate-data
slice. It contains 16 training-role and 16 development-role examples spanning
positive, explicitly negative, unknown, conflict, useful-frontier,
irrelevant-frontier, reachable-cycle, and unreachable-cycle cases.

This is not an admitted training corpus. The source registry records pending
rights review and a missing project licence, every example and detached
artifact contains `training_authorized: false`, and no training command or ML
runtime dependency exists. The checked-in quarantine index is a public local
reservation fixture. A `clear` decision means clear against that exact bound
fixture only; it does not substitute for the complete Phase 0 confirmatory
quarantine union, which remains unavailable.

## Frozen surface

Phase 2 v1 independently locks four JSON Schema contracts:

- `registry.schema.json` for immutable source roles, rights state, artifact
  identity, and preallocated dependency families;
- `generator-spec.schema.json` for algorithm, seed, bounds, risk policy, and
  role-specific grammar/world/composition/seed allocations;
- `policy-example.schema.json` for typed signed facts, ground Horn rules,
  prediction-time frontiers, policy targets, proof evidence, quarantine, and
  provenance; and
- `artifact.schema.json` for generation manifests, integrity reports, and
  cross-role corpus audits.

The independent lock anchors live in
`src/hippocampus_foundation/phase2/contracts.py`. The runtime dependency list is
unchanged: only `jsonschema` and `rfc8785` are required.

## Label semantics

Explicit negation is represented as data. Missing support is unknown, and a
positive/negative contradiction does not entail unrelated propositions.

For a positive query, the two oracles assign:

- `return` with `{"truth": true}` for positive support only;
- `return` with `{"truth": false}` for negative support only;
- `abstain_unknown` when neither side is supported and no frontier exists;
- `abstain_conflict` when both sides are supported;
- `continue` when at least one bounded frontier observation would establish
  positive or negative support; and
- `stop_irrelevant` when a non-empty frontier cannot affect the query.

The agenda oracle performs signed forward closure. The second oracle recursively
enumerates bounded proof trees with separate path-cycle handling. They share
parsed atom identities, not derivation or decision code. Any disagreement is a
hard generation failure.

## Checked-in inputs and outputs

Inputs:

- `registries/training-sources.v1.json`;
- `registries/phase2.generator.training.v1.json`;
- `registries/phase2.generator.development.v1.json`; and
- `quarantine/phase2-public-reservations.v1.json`.

The reservation index is mechanically re-derived from the checked-in fixture
envelope and public contribution. That envelope binds the exact bytes of the
fixture selector source and its identifier-copy adapter specification; no
placeholder digest is accepted as provenance.

Reproducible outputs are under `fixtures/phase2/`. The registered example-file
identities are:

- training: `sha256:fba8244ede343e9dd52ac1f769f6f107607a4aae67c51a9867d9615767241d0c`;
- development: `sha256:91729b18f7717fc15f6bd700f4b0585fb83049e0f5a924c588976affa7e506a4`.

The checked-in corpus audit contains no cross-role artifact, exact-input,
normalized-input, grammar, world, relation-composition, or seed-family overlap.
That observation is limited to these 32 generated examples.

## Verification commands

Validate the frozen contracts and declared inputs:

```bash
uv run hf-phase2 contracts validate \
  --registry registries/training-sources.v1.json \
  --spec registries/phase2.generator.training.v1.json \
  --spec registries/phase2.generator.development.v1.json
```

Verify each checked-in slice by deterministic regeneration:

```bash
uv run hf-phase2 procedural verify \
  --registry registries/training-sources.v1.json \
  --spec registries/phase2.generator.training.v1.json \
  --quarantine quarantine/phase2-public-reservations.v1.json \
  --examples fixtures/phase2/training.examples.v1.jsonl \
  --manifest fixtures/phase2/training.manifest.v1.json \
  --report fixtures/phase2/training.integrity.v1.json

uv run hf-phase2 procedural verify \
  --registry registries/training-sources.v1.json \
  --spec registries/phase2.generator.development.v1.json \
  --quarantine quarantine/phase2-public-reservations.v1.json \
  --examples fixtures/phase2/development.examples.v1.jsonl \
  --manifest fixtures/phase2/development.manifest.v1.json \
  --report fixtures/phase2/development.integrity.v1.json
```

Recheck role isolation:

```bash
uv run hf-phase2 corpus audit \
  --manifest fixtures/phase2/training.manifest.v1.json \
  --report fixtures/phase2/training.integrity.v1.json \
  --manifest fixtures/phase2/development.manifest.v1.json \
  --report fixtures/phase2/development.integrity.v1.json
```

Generation refuses existing outputs. Reproduction therefore uses three new
paths per role rather than overwriting the checked-in evidence.

## Integrity findings

Both roles contain all eight case families twice. The detached diagnostics are
not model results: majority accuracy is 0.375, grammar-only accuracy is 0.0,
template-only accuracy is 0.375, and path-length-only accuracy is 0.5 under the
small leave-one-world-out diagnostic. An early implementation draft exposed
case names in metadata and produced a perfect template shortcut; those fields
were removed before the checked-in artifacts were created. Prediction records
now use a neutral template identifier and seed-dependent case ordering.

These diagnostics are too small to support a modelling claim. They are useful
only as leakage and shortcut guards for this fixture.

## Remaining blockers

- The project still lacks a selected repository licence and final accountable
  rights approval for even first-party output distribution.
- The Phase 0 confirmatory quarantine union, seals, access-log anchors, and
  private independently custodied worlds do not exist.
- The procedural family has not been scaled, diversified, or tested for model
  generalisation.
- No trainer, model, threshold, predictive metric, or training authorization
  exists.

The staged-write process-state slice is now implemented and documented in
`PHASE_2B_RUNBOOK.md`. The next milestone is the external evidence firewall in
`NEXT_MILESTONE.md`.
