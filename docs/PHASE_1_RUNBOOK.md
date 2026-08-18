# Phase 1 v2 data-preparation runbook

Phase 1 prepares a small, auditable graph-mechanics development corpus. It
validates records, selects nodes deterministically, caps one-hop context without
silent loss, validates and reorders predeclared development objectives, and
checks the frozen encoder identity. It does not create labels from held-out
data, run encoder inference through the CLI, fit a model, select thresholds, or
authorize training.

## Entry conditions

Do not run a data-producing Phase 1 command until all of these are true:

- a Phase 0 v3 report is no more than 72 hours old;
- the report has every readiness control true, no blockers, and
  `foundation_transform_ready: true`;
- the report still has `training_authorized: false`;
- the supplied public quarantine index has the exact SHA-256 recorded in the
  Phase 0 evidence list;
- all Phase 1 input records were derived only from admitted source bytes.

The commands mechanically enforce the Phase 0 gate and quarantine bindings.
The checked-in initial Phase 0 report is blocked, so it cannot be used to
produce Phase 1 artifacts.

## Current implementation boundary

The CLI consumes already constructed `.jsonl`, `.ndjson`, or optional Parquet
records conforming to the Phase 1 schemas. A raw Wikipedia/Wikidata-to-Phase-1
transformer and its required Phase 0 quarantine matcher are not implemented
yet. Consequently, no real transformed record can currently establish the
required `quarantine_decision: clear` lineage. Parquet reads require `pyarrow`
supplied by the execution environment; it is intentionally not a project
runtime dependency.

Similarly, objective replay validates and deterministically orders supplied
development examples; it does not invent prompts, candidates, targets, or
negative labels. The repository contains a frozen inference adapter, but no CLI
command invokes it and the heavy inference packages are not project
dependencies.

## Verify contracts

```bash
uv sync --group dev
uv run hf-phase1 contracts validate-v2
uv run hf-phase1 contracts validate \
  --instance registries/encoder.gte-modernbert.v1.json=encoder.schema.json
uv run hf-phase0 licence contracts-validate
```

Together these validate the Phase 1 v2 gate schema, its five frozen v1
dependency schemas, the licensing/v1 dependency, and the encoder spec's
separately frozen digest. `gate-v2` repeats all dependency locks. The historical
`contracts validate` and `gate` commands remain the v1 path.

## Frozen encoder identity

The encoder selected by the prior bake-off is fixed as:

- model: `Alibaba-NLP/gte-modernbert-base`;
- revision: `e7f32e3c00f91d699e8c43b53106206bcc72bb22`;
- output: 768 dimensions, CLS pooling, no normalization;
- text recipe: `title`, two newlines, `body`;
- default context: 2,048 tokens; supported maximum: 8,192 tokens;
- execution policy: local files only, no remote code, inference mode, frozen
  weights.

Verify the exact cached snapshot and exact bake-off report:

```bash
uv run hf-phase1 encoder verify \
  --spec registries/encoder.gte-modernbert.v1.json \
  --snapshot /ABSOLUTE/PATH/TO/FROZEN-SNAPSHOT \
  --bakeoff-report /ABSOLUTE/PATH/TO/encoder-bakeoff-report.json \
  --snapshot-id huggingface:Alibaba-NLP/gte-modernbert-base@e7f32e3c00f91d699e8c43b53106206bcc72bb22 \
  --output artifacts/encoder-verification.v2.json
```

This is byte-level static verification of the declared report and eight runtime
assets. It exact-enumerates files and directories, rejects undeclared entries,
directory symlinks, special filesystem entries, and a symlinked snapshot root,
and records `verification_method: exact-snapshot-layout-v2`. It does not load
the model, test numerical embeddings, establish upstream training-data
cleanliness, or complete the encoder's human licence review. Five allowlisted
model-card, repository-tree, platform-terms, and legal-code documents are
captured in the encoder evidence bundle. Its assessment remains pending because
the repository has no licence/notice file, the upstream revision is not pinned,
and commercial scope remains a human legal question.

`audit/encoder-verification.v1.json` is retained as historical evidence only.
The old verifier did not enumerate arbitrary undeclared snapshot entries, and
the restored workspace does not contain the snapshot or bake-off report needed
to rerun it. Phase 1 v2 therefore rejects that record rather than inferring a
clean identity from it.

## Validate graph records

Phase 1 graph records are nodes, statements, neighbour candidates, or typed
overflow entries. Wikidata values use exactly one of `entity_ref`, `literal`,
or the `somevalue`/`novalue` sentinel, and qualifier/reference snaks reuse the
same value union. Every admitted node, statement, and candidate must carry
source-version and artifact-hash provenance and a `clear` quarantine decision.

```bash
uv run hf-phase1 graph validate --input artifacts/phase1/nodes.jsonl
uv run hf-phase1 graph validate --input artifacts/phase1/statements.jsonl
uv run hf-phase1 graph validate --input artifacts/phase1/neighbour-candidates.jsonl
```

Validation does not prove that a record was truthfully transformed from its
claimed source. That lineage must be established by the missing raw transformer
and independently checked against Phase 0 evidence.

## Deterministic 40,000-node sample

The default and gate-required sample size is 40,000 with seed `20260817`. The
algorithm selects at least one node from every community, then water-fills the
joint strata of source, text-length quintile, incoming-degree tercile,
outgoing-degree tercile, and PageRank decile. It never consults labels or
confirmatory results.

```bash
uv run hf-phase1 sample build \
  --phase0-gate artifacts/phase0-gate.v3.json \
  --quarantine artifacts/public-quarantine-index.v2.json \
  --candidates artifacts/phase1/node-candidates.jsonl \
  --output artifacts/phase1/nodes.sample-40000.jsonl \
  --manifest artifacts/phase1/sample-manifest.v1.json
```

The command refuses existing outputs, hashes the input before and after use,
writes canonical JSONL atomically, and records the selected-byte hash. It fails
if 40,000 candidates are unavailable or 40,000 nodes cannot cover all declared
communities. A custom `--size` may be useful for development checks, but the
Phase 1 gate will not accept it as the required corpus.

## One-hop neighbour caps and overflow ledger

Apply deterministic one-hop context limits:

- Wikipedia outgoing entity: 16;
- Wikipedia incoming entity: 8;
- Wikidata outgoing entity: 24;
- Wikidata incoming entity: 8;
- Wikidata outgoing literal: 32;
- Wikidata per center/property: 4 before category caps.

```bash
uv run hf-phase1 graph cap-neighbours \
  --phase0-gate artifacts/phase0-gate.v3.json \
  --quarantine artifacts/public-quarantine-index.v2.json \
  --input artifacts/phase1/neighbour-candidates.jsonl \
  --output artifacts/phase1/neighbours.selected.jsonl \
  --overflow artifacts/phase1/neighbours.overflow.jsonl \
  --manifest artifacts/phase1/neighbour-cap-manifest.v1.json
```

Property and category exclusions are retained as typed `neighbour_overflow`
records with a reason. The manifest is invalid unless input count equals
selected plus overflow count. The overflow file is evidence, not disposable
scratch data.

## Development objective replay

Each example must have two to eight candidates, exactly one target, and
evidence-backed negative candidates with an allowed explicit basis. A missing
edge is never accepted as a negative basis. Every replay must cover all eight
families:

- `masked_node_attribute`;
- `masked_edge_direction`;
- `masked_qualifier_value`;
- `evidence_span_alignment`;
- `local_entity_disambiguation`;
- `bounded_path_continuation`;
- `neighbourhood_ranking`;
- `source_time_conditioned_retrieval`.

Validate first, then produce the deterministic replay ordering:

```bash
uv run hf-phase1 objectives validate \
  --input artifacts/phase1/objectives.development.jsonl

uv run hf-phase1 objectives replay \
  --phase0-gate artifacts/phase0-gate.v3.json \
  --quarantine artifacts/public-quarantine-index.v2.json \
  --input artifacts/phase1/objectives.development.jsonl \
  --output artifacts/phase1/objectives.replay.jsonl \
  --manifest artifacts/phase1/objective-manifest.v1.json
```

Replay requires one graph-snapshot hash and one quarantine-index hash across all
examples. It preserves the supplied labels; correctness still requires an
independent generator/oracle or source-grounded audit outside this command.

## Phase 1 gate

```bash
uv run hf-phase1 gate-v2 \
  --phase0-gate artifacts/phase0-gate.v3.json \
  --encoder-spec registries/encoder.gte-modernbert.v1.json \
  --encoder-verification artifacts/encoder-verification.v2.json \
  --encoder-licence-assessment private/licensing/gte-modernbert-base-rights-v1/assessment.final.json=private/licensing/gte-modernbert-base-rights-v1/bundle.json \
  --sample-manifest artifacts/phase1/sample-manifest.v1.json \
  --graph-manifest artifacts/phase1/neighbour-cap-manifest.v1.json \
  --objective-manifest artifacts/phase1/objective-manifest.v1.json \
  --evaluated-at 2026-08-17T00:00:00Z \
  --output artifacts/phase1-gate.v2.json
```

The v2 gate reports `encoder_identity_ready` and `encoder_licensing_ready`
separately; `encoder_ready` requires both. A valid static snapshot can therefore
never conceal a pending or rejected human rights assessment. The checked-in
`audit/phase1-gate.v2.licensing.json` demonstrates the current restored state:
both identity and licensing are false, and no data preparation or training is
authorized. Identity can become true only after a fresh v2 verification against
the actual snapshot and bake-off report.

Exit status `2` means blocked; `0` means only that the declared Phase 1 data
artifacts satisfy the gate. The report always sets `training_authorized: false`.

The gate validates manifest semantics and cross-bindings, but manifests are
detached JSON rather than signed attestations and the gate does not reopen their
referenced output files. Retain the files immutably and independently re-hash
them before any later authorization decision.
