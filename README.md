# Hippocampus Foundation

Hippocampus Foundation is the clean-room design space for a general-purpose,
evidence-grounded graph memory system. The system should learn to traverse a
memory graph, return only sufficiently supported information, and propose or
commit memory changes according to the risk of the affected node.

This folder is documentation-first. It does not inherit an architecture,
checkpoint, dataset split, reward, benchmark result, or product claim from an
older Hippocampus implementation.

## Status

Phase 0 v4.2 clean-room controls and Phase 1 v2 deterministic data-preparation
controls are implemented locally. Phase 0 v4.2 retains the complete v4.1
trusted-root evidence graph and adds an externally rooted Entor Workspace OAuth
policy, signed authority over the exact installed-client bytes, a live
same-resource proof joining the Drive API to the mounted DriveFS root through a
canonical marker, and signed per-artifact authority for acquisition. Rooted
downloads bind resumable partials to that signature and repeat the live proof
before immutable promotion. Phase 0 also binds independently materialized
evaluation receipts, publisher statements, accountable rights packets,
explicit evaluation roles, authenticated custody anchors, the complete
quarantine union, source-byte audits, inventories, and admission receipts.
Phase 1 freezes
graph/objective contracts, a deterministic 40,000-node sampler, complete
neighbour-overflow accounting, development
objective replay, and separate encoder identity/licensing readiness. The
frozen Phase 0 v2/v3/v4/v4.1 and Phase 1 v1 contracts remain available for
historical reproducibility; v4.2 does not delegate readiness to an older gate.

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

The checked real-state Phase 0 v4.2 and Phase 1 v2 gates are blocked. Phase 0 v4
corrects evaluation roles: SocialIQA validation is development-only, the
previously exposed EvidenceBench partition is diagnostic-only, and five other
datasets remain confirmatory candidates. Forty-three allowlisted legal/provenance
documents have been captured into 10 digest-bound review packets; none is a
human approval. Every assessment remains pending, and two private confirmatory
first-party evaluations have no external evidence documents. The installed
Better Colab build is `0.1.dev103+ga8c1b68b5`. A user-run `colab drivemount`
completed interactive credential propagation and mounted `/content/drive`;
that establishes that the broad native mount works, but it does not establish
the exact API scope, approved OAuth client, stable Drive IDs, marker identity,
or v4.2 authority. The exact-scope provider and v4.2 observer are implemented,
but no approved Internal Workspace policy/client pair or live v4.2 proof was
supplied to this work. The checked pending policy deliberately has no trusted
project or signing keys, and its hash is not activated in code. Phase 0 also
lacks
fresh publisher receipts and verified source bytes, a pinned evaluation
successor, pinned-entry rights approvals, materialization receipts, sealed
evaluation envelopes with GPG-signed independently anchored access logs, the
complete Phase 0 v4 quarantine union, structural inventories,
and admission receipts. Phase 1 consequently
lacks a ready Phase 0 gate and its sample, graph, and objective manifests.

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
- [Next milestone: external evidence firewall](docs/NEXT_MILESTONE.md)
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

1. Have an Entor Workspace administrator create or identify an
   organization-owned Google Cloud project whose OAuth audience is Internal,
   approve the exact installed-client SHA-256 and signing keys in a non-secret
   v4.2 policy, and activate only that reviewed policy hash in a separate
   commit. Do not commit the client secret or ADC.
2. Create the canonical marker, upload those exact bytes once to the registered
   lake root, and bind its file ID and digest into the signed OAuth authority.
   In one durable Better Colab CPU session, use `drive-auth authorize` with the
   protected approved client and manually complete `colab drivemount
   --read-only`. Then generate both the legacy human-observed storage record and
   the independent v4.2 API/DriveFS marker proof. A broad default mount is not a
   substitute.
3. Fetch fresh publisher statements after Drive binding and create one receipt
   per registered artifact.
4. Pin all evaluation assets, adapters or generators, independent-oracle
   artifacts, dependency units, and custodian keys in one successor registry.
5. Rebind the retained rights captures to the pinned entries, then have an
   accountable human resolve or reject every blocking finding; do not convert a
   pending scaffold into an approval mechanically.
6. Materialize every evaluation, seal confirmatory envelopes to the custodian's
   offline public key, externally anchor each materialization-bound access log,
   create the evidence-backed final registry successor, and compile the public
   quarantine union.
7. Audit the existing lake from raw bytes. For each registered acquisition
   target, obtain a fresh detached signature over its exact registry entry,
   storage identity, expected bytes, and byte ceiling. Use only `source
   acquire-v4.2`, then re-audit and build structural inventories and admission
   receipts.
8. After a ready v4.2 transformation report exists, add the separately versioned
   raw-source consumer and Phase 1 v3 input gate. Then run data preparation on
   admitted, quarantine-cleared records. Frozen Phase 1 v2 cannot consume v4.2,
   and no Phase 1 readiness report authorizes training.
