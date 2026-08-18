# Next milestone: Phase 2A procedural open-world data slice

## Outcome

Build one complete, deterministic first-party data family that proves
open-world read and traversal semantics before any trainer or external dataset
adapter is added. The milestone produces public training/development candidate
artifacts and integrity reports, but cannot authorize or run training.

## Contract surface

Add frozen Phase 2 v1 schemas and independent SHA-256 locks for:

- a training-source registry with immutable roles (`training`, `development`,
  `diagnostic`, `confirmatory`), admission state, rights binding, artifact
  hashes, and dependency units;
- generator specifications binding algorithm version, role, seed, grammar,
  world, relation-composition, and seed-family allocations;
- policy examples containing the complete prediction-time world, query,
  candidate actions, target action and payload, proof evidence, risk/cost
  class, split identities, quarantine binding, and provenance; and
- generation manifests and integrity reports binding all inputs and outputs,
  role counts, oracle agreement, overlap findings, duplicates, and shortcut
  diagnostics.

The role describes intended evaluation use and does not authorize training.
Every Phase 2A manifest must contain `training_authorized: false`. Reuse of an
artifact hash or grammar, world, relation-composition, or seed family across
roles is invalid.

## Public CLI

Add an `hf-phase2` console script with these commands:

- `contracts validate` validates schema locks, registries, specs, examples,
  manifests, and reports;
- `procedural generate` accepts a registry entry, generator spec, and public
  quarantine index, then atomically writes canonical JSONL examples, a manifest,
  and an integrity report;
- `procedural verify` reopens those artifacts, recomputes both oracles and all
  hashes, and rejects any mismatch; and
- `corpus audit` accepts multiple manifests/reports and rejects cross-role
  dependency or artifact overlap.

Generation permits only `training` and `development`. It refuses confirmation,
existing outputs, unsafe paths or values, mutable inputs, and any excluded or
undetermined quarantine decision. No command may be named `train`, `fit`,
`optimize`, or `model`.

## World and label semantics

Generate finite typed worlds containing signed ground facts and typed Horn
rules. Explicit negation is data; absence is unknown. Contradictions do not
explode into unrelated conclusions.

For a queried signed proposition:

- positive support only targets `return` with a true payload and proof;
- negative support only targets `return` with a false payload and proof;
- neither targets `abstain_unknown`;
- both target `abstain_conflict` with both proof sets;
- a useful bounded frontier targets `continue`; and
- an irrelevant frontier targets `stop_irrelevant`.

Assign grammar, world, relation-composition, and seed families to roles before
generating any examples. Random row splitting is prohibited.

## Independent verification

Implement two oracles that share only parsed immutable input types:

1. agenda-based signed forward closure with proof provenance; and
2. exhaustive bounded proof-tree enumeration with independent cycle handling.

They must agree on positive/negative reachability and terminal action. Any
disagreement blocks the artifact. The integrity report also records action
balance, provenance completeness, exact and normalized duplicates, dependency
overlap, and majority, grammar/template, and path-length baselines. Oracle,
provenance, duplicate, and overlap failures are blockers; shortcut scores are
diagnostic until representative data exists.

## Acceptance criteria

- Identical specs and seeds produce byte-identical examples, manifests, and
  reports regardless of input ordering.
- Training and development share no dependency identifiers or artifact hashes.
- Positive, explicitly negative, unknown, conflict, continuation,
  irrelevant-stop, cyclic, and unreachable cases agree across both oracles.
- Missing prediction-time fields, provenance, split identity, risk/cost class,
  rights binding, or quarantine binding fails validation.
- Quarantined dependencies, deliberate oracle faults, output collisions,
  confirmatory generation, and cross-role duplicates are rejected.
- Existing tests remain green; the new schemas, CLI, sdist, wheel, and isolated
  install all verify.

## Explicit exclusions

This milestone does not add a neural trainer, ML framework, model weights,
private seeds, confirmatory examples, real external acquisition, graph-schema
migration, Wikipedia/Wikidata adapters, or encoder recovery. Those remain later
roadmap gates.
