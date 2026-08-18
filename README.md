# Hippocampus Foundation

Hippocampus Foundation is the clean-room design space for a general-purpose,
evidence-grounded graph memory system. The system should learn to traverse a
memory graph, return only sufficiently supported information, and propose or
commit memory changes according to the risk of the affected node.

This folder is documentation-first. It does not inherit an architecture,
checkpoint, dataset split, reward, benchmark result, or product claim from an
older Hippocampus implementation.

## Status

Phase 0 v3 clean-room controls and Phase 1 v2 deterministic data-preparation
controls are implemented locally. Phase 0 covers evidence-bound storage,
licensing, source, inventory, admission, evaluation-seal, quarantine, and
readiness records. Phase 1 freezes graph/objective contracts, a deterministic
40,000-node sampler, complete neighbour-overflow accounting, development
objective replay, and separate encoder identity/licensing readiness. The
frozen Phase 0 v2 and Phase 1 v1 contracts remain available for historical
reproducibility.

Both current gates are blocked. Forty-three allowlisted legal/provenance
documents have been captured into 10 digest-bound review packets; none is a
human approval. Every assessment remains pending, and two unimplemented
first-party evaluations have no external evidence documents. The native
read-only Drive command, identity probe, binding command, and a fail-closed
rclone fallback are implemented. The repaired native authorization sequence
and read-only mount were live-verified on one disposable CPU runtime, including
the fixed expected lake-root directory, but no exact-scope identity observation
has yet established stable resource IDs. The fallback and identity observation
cannot proceed without protected exact-scope user ADC created with an approved
desktop OAuth client file, and none was supplied to this work. The separately
connected Drive integration has no accessible shared drive named `Data`, so it
was not used as a substitute. Phase 0 also lacks
verified source bytes, sealed evaluation envelopes, the public quarantine
index, structural inventories, and admission receipts. Phase 1 consequently
lacks a ready Phase 0 gate and its sample, graph, and objective manifests.

There is no training command or ML runtime dependency. Every Phase 0 and Phase
1 report mechanically sets `training_authorized` to `false`. The encoder check
performed so far was static identity verification only; no embedding inference,
model fitting, threshold tuning, or optimization was run.

## Core idea

The model has a shared traversal core and two decision paths:

- The read path traverses candidate nodes and decides whether to continue,
  return evidence-grounded information, or abstain.
- The write path traverses possible attachment points and proposes `attach`,
  `update`, `deprecate`, `new_node`, `duplicate`, `conflict`, `stage`, or
  `ignore`.

Both paths may search broadly. Their terminal gates must be conservative when
an incorrect return or permanent write is costly.

> Search broadly; return narrowly. Propose broadly; commit narrowly.

## Non-negotiable principles

1. Every durable claim must retain provenance and evidence.
2. Missing information means unknown, not false.
3. Retrieval confidence and write confidence are separate quantities.
4. Candidate generation and acceptance are separate decisions.
5. Risk, scope, time, source reliability, and reversibility are explicit model
   inputs rather than hidden assumptions.
6. Early write training reconstructs frozen graph snapshots; the learner never
   mutates its own training truth.
7. Gold evaluation data is quarantined before foundation-corpus construction.
8. Random row splits are not acceptable for graph, revision, or
   Wikipedia-derived evaluations.
9. No single scalar reward is allowed to hide safety regressions behind average
   performance.
10. Online canonical writes are a late capability, not a starting condition.

## Memory layers

```text
working memory   temporary, exploratory, cheap to discard
       |
       v
candidate memory uncertain claims with provenance and conflict state
       |
       v
canonical memory accepted claims with stricter evidence requirements
```

Promotion is a first-class decision. Uncertain information does not need to be
forced into a binary accept/reject outcome.

## Source-of-truth documents

- [Architecture](docs/ARCHITECTURE.md)
- [Data and training strategy](docs/DATA_AND_TRAINING.md)
- [Safety, leakage, and evaluation](docs/SAFETY_AND_EVALUATION.md)
- [Decision log and open questions](docs/DECISIONS.md)
- [Phase 0 runbook](docs/PHASE_0_RUNBOOK.md)
- [Phase 1 data-preparation runbook](docs/PHASE_1_RUNBOOK.md)
- [Machine-learning integrity audit](audit/ML_AUDIT.md)
- [Verification record](audit/VERIFICATION.md)

## Clean-room boundary

Older Hippocampus artifacts are treated as untrusted inputs. They may be
examined later only through a documented quarantine process. Reuse requires an
audit covering provenance, split integrity, label generation, reward design,
test access, and contamination. Until such an audit exists, do not copy old
weights, generated examples, metrics, evaluator code, thresholds, or training
configurations into this project.

## Immediate programme

1. Attempt the repaired native `colab drivemount --read-only` flow first. With
   an approved protected desktop OAuth client, create exact-scope ADC in the
   same CPU runtime, run the read-only Drive identity probe, and bind its stable
   shared-Drive/root-folder IDs into a new registry plus fresh storage
   attestation. Use the gated rclone fallback only if native mounting fails.
   Do not grant a Drive scope broader than `drive.readonly`.
2. Have an accountable human review the prepared evidence packets. Resolve or
   reject every blocking finding; do not convert a pending scaffold into an
   approval mechanically.
3. Capture and bind the remaining publisher checksum evidence.
4. Pin adapters or generators, derive dependency-closed evaluation envelopes,
   seal them to the custodian's offline public key, and compile their public
   quarantine union.
5. Audit the existing lake from raw bytes. Acquire the registered Wikidata dump
   only if the Phase 0 acquisition gate becomes ready, then re-audit and build
   structural inventories and admission receipts.
6. Run the Phase 1 data-preparation pipeline on admitted, quarantine-cleared
   records and evaluate its gate. This still does not authorize training.
# Hippo-foundation
