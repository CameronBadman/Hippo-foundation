# Hippocampus Foundation

Hippocampus Foundation is the clean-room design space for a general-purpose,
evidence-grounded graph memory system. The system should learn to traverse a
memory graph, return only sufficiently supported information, and propose or
commit memory changes according to the risk of the affected node.

This folder is documentation-first. It does not inherit an architecture,
checkpoint, dataset split, reward, benchmark result, or product claim from an
older Hippocampus implementation.

## Status

Phase 0 v4.3 public-source controls and Phase 1 v2 deterministic
data-preparation controls are implemented locally. V4.3 preserves the complete
v4.1 trusted-root evaluation graph while replacing the Drive-specific source
execution path with private local/remote staging and an exact public Hugging
Face destination. It adds signed per-artifact staging acquisition, independent
byte audit and structural inventory, separate human redistribution rights and
obligation evidence, deterministic 10-GiB publication manifests, optimistic
Hub commit locking, anonymous remote verification, and post-publication source
admission. Phase 0 also binds independently materialized evaluation receipts,
publisher statements, accountable rights packets, explicit evaluation roles,
authenticated custody anchors, and the complete quarantine union. Phase 1 freezes
graph/objective contracts, a deterministic 40,000-node sampler, complete
neighbour-overflow accounting, development
objective replay, and separate encoder identity/licensing readiness. The
frozen Phase 0 v2/v3/v4/v4.1/v4.2 and Phase 1 v1 contracts remain available for
historical reproducibility; v4.3 does not accept a supplied predecessor report
as proof and instead reopens the complete rooted evidence graph.

Phase 2A and Phase 2B are also implemented locally. The preparation-only Phase
2 CLI generates and verifies 16 open-world candidates and 32 staged-write
process candidates per role. The read-path slice compares agenda and proof-tree
oracles; the write-path slice compares declarative and copy-on-write transition
oracles and replays every detached patch and inverse against disposable state.
The mixed audit finds no cross-role artifact, input, snapshot, entity, or
allocated dependency-family overlap across the four corpora. These slices are
contract and leakage-control fixtures, not admitted corpora: they are bound
only to a local reservation quarantine index, their rights records remain
pending, and no predictive performance was measured.

The checked real-state Phase 0 v4.3, publication v1, and Phase 1 v2 gates are
blocked. The pinned public dataset currently contains exactly three metadata
files at the configured baseline; a fresh authenticated/anonymous observation
proved the intended account can write and anonymous users can read, but no
corpus byte was uploaded. The source registry describes seven Wikimedia
artifacts totaling 141,447,172,673 bytes; none is present in this workspace.
Both v4.3 authority policies remain pending and code-unpinned. The project still
lacks fresh publisher receipts, verified source bytes, a pinned evaluation
successor, accountable rights approvals, materialization receipts, sealed
evaluation envelopes with independently signed access-log anchors, the complete
quarantine union, staging/acquisition evidence, structural inventories,
publication clearances and receipts, and admissions. Phase 1 consequently lacks
a ready Phase 0 gate and its sample, graph, and objective manifests.

There is no training command or ML runtime dependency. Every Phase 0, Phase 1,
and Phase 2 artifact mechanically sets `training_authorized` to `false`. The
preserved v1
encoder record is historical and cannot satisfy the current Phase 1 v2 gate:
its verifier checked the declared assets and Python files, but did not prove
that no other snapshot entry existed. The snapshot and bake-off report are not
present in this restored workspace, so a fresh exact-layout v2 verification is
required. No embedding inference, model fitting, threshold tuning, or
optimization was run.

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
- [Programme roadmap](docs/ROADMAP.md)
- [Dataset role and lineage review](audit/DATASET_REVIEW.md)
- [Safety, leakage, and evaluation](docs/SAFETY_AND_EVALUATION.md)
- [Decision log and open questions](docs/DECISIONS.md)
- [Phase 0 runbook](docs/PHASE_0_RUNBOOK.md)
- [Phase 1 data-preparation runbook](docs/PHASE_1_RUNBOOK.md)
- [Phase 2A procedural runbook](docs/PHASE_2A_RUNBOOK.md)
- [Phase 2B staged-write runbook](docs/PHASE_2B_RUNBOOK.md)
- [Next milestone: public-source execution](docs/NEXT_MILESTONE.md)
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

1. Pin all evaluation assets, adapters or generators, independent-oracle
   artifacts, dependency units, and custodian keys in one successor registry.
2. Rebind the retained rights captures to the pinned entries, then have an
   accountable human resolve or reject every blocking finding; do not convert a
   pending scaffold into an approval mechanically. Perform a separate review
   explicitly covering public source redistribution and its obligations.
3. Materialize every evaluation, seal confirmatory envelopes to the custodian's
   offline public key, externally anchor each materialization-bound access log,
   create the evidence-backed final registry successor, and compile the public
   quarantine union.
4. Refresh all seven publisher receipts, approve and code-pin the separate
   staging and publication authority policies, and initialize a private
   public-only staging root.
5. Obtain a short-lived detached signature for each exact artifact, use only
   `source acquire-v4.3`, then independently audit and structurally inventory
   the staged bytes. The 102.35-GB Wikidata transfer requires explicit approval
   at execution time.
6. Complete publication obligations and clear each artifact. Inventory its
   deterministic parts, obtain a separate short-lived publication signature,
   and use only `publication upload-v1`. Publish serially and retain every
   signed authorization and anonymously verified receipt.
7. Admit each complete source and reproduce `publication-gate-v1` and
   `gate-v4.3`. After a ready v4.3 transformation report exists, add the separately versioned
   raw-source consumer and Phase 1 v3 input gate. Then run data preparation on
   admitted, quarantine-cleared records. Frozen Phase 1 v2 cannot consume v4.3,
   and no Phase 1 readiness report authorizes training.
