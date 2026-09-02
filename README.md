# Hippocampus Foundation

Hippocampus Foundation is the clean-room design space for a general-purpose,
evidence-grounded graph memory system. The system should learn to traverse a
memory graph, return only sufficiently supported information, and propose or
commit memory changes according to the risk of the affected node.

This folder is documentation-first. It does not inherit an architecture,
checkpoint, dataset split, reward, benchmark result, or product claim from an
older Hippocampus implementation.

## Status

The active milestone is the frozen, one-week synthetic READ experiment in
[`experiments/read_run_v1/PREREGISTRATION.md`](experiments/read_run_v1/PREREGISTRATION.md).
It asks whether learned adaptive traversal beats an equal-capacity,
equal-examined-edge DIRECT scorer, and whether the gap grows with empirically
measured greedy-wrongness. All worlds are generated locally; no external
corpus, Drive mount, Hub payload, rights decision, or custody ceremony is
needed. Phase 0 v4.4 and public-source execution are parked, not deleted.

The READ implementation includes separated visible/hidden deterministic
streams, a causally separate oracle, seven pre-training integrity gates, a
query-similarity-independent structural DIRECT pool, identical 10,257,937
parameter model classes for both arms, fixed-step training, proof-valid
exact-set scoring, route-completeness measurement, and the frozen four-way
decision rule. What has actually executed, in order, with every outcome
retained:

- **E1 ran and is void.** All 30 preregistered main runs completed under the
  committed code freeze; the γ=0 negative control failed (the arms differed by
  28.49pp in the gated `hops_2_4` stratum against a 1.00pp threshold), so no
  comparison between the arms is a result. The v1 holdout was opened once and
  is spent. [`experiments/read_run_v1/results/E1.md`](experiments/read_run_v1/results/E1.md).
- **The cause was demonstrated.** A diagnostic probe reproduced E1's DIRECT run
  bit for bit and continued past its 1,172-update cutoff: DIRECT reached 83.36%
  proof-valid exact-set accuracy by update 3,500. E1 stopped about 2,300 updates
  short of that transition.
- **The E1-v2 overnight sequence stopped at gate G1.** No v2 data, holdout, or
  model exists. Route-completeness — a complete relation-matching route to
  every target inside the examined set, which is what proof-valid scoring
  needs — is now measured beside gate 7's target-node exposure (87.90% against
  100.00% on the gated stratum at B=128). Amendment 10, which makes it a
  mandatory report field and redesigns the primary statistic, is pending review.
- **The Amendment 10 γ sweep ran on screening splits only** — twelve runs of
  9,376 updates, one seed per cell plus a second seed at γ ∈ {0, 0.4}, read
  under a rule committed before the runs started. With the similarity field
  present, TRAV holds 99.47–100.00% exact-set accuracy at every γ at update
  8,000 while DIRECT falls from 86.74% to 62.01% and similarity-greedy from
  82.65% to 58.54%. Two disclosures qualify that curve: the generator's
  similarity field marks the on-path nodes at every γ (2,000 of 2,000 screening
  episodes), and with the field flattened every TRAV checkpoint is only
  53.56–69.13% route-complete — below the 87.90% that DIRECT's query-blind
  structural pool reaches at the same budget. Edge discrimination by relation
  was learned; navigation without the marker was not demonstrated.
  [`experiments/read_run_v1/diagnostics/gamma_sweep_screening_report.md`](experiments/read_run_v1/diagnostics/gamma_sweep_screening_report.md)
  is single-seed screening and inadmissible as a hypothesis result.

The next run is a structural-only screening ablation: the same frozen model and
v1 data, trained with `query_similarity_ppm` held at a constant, read by an
outcome table committed before the run. It is not a preregistered arm and opens
no holdout. Every observation above is recorded, with failures, in
[`experiments/read_run_v1/DEVELOPMENT_LOG.md`](experiments/read_run_v1/DEVELOPMENT_LOG.md).

### Parked foundation programme

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

- [Frozen READ-run preregistration](experiments/read_run_v1/PREREGISTRATION.md)
- [READ-run execution guide](experiments/read_run_v1/README.md)
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

1. Run the structural-only screening ablation on the frozen v1 γ=0 buckets:
   three seeds per arm with `query_similarity_ppm` masked at train and eval,
   read per seed against the model-free references (DIRECT's structural pool
   and a relation-following walker) under an outcome table committed first.
2. Decide from that reading whether the generator needs a shortcut-free
   similarity field before any E1-v2, and record the decision in
   `docs/DECISIONS.md`.
3. Review Amendment 10. Only an approved amendment, a new master seed, a full
   regeneration, a fresh seven-gate P0 report and a new code freeze can open a
   holdout again, once.
4. Apply whichever preregistered decision rule is then in force without
   changing thresholds, arms, seeds, metrics, or reporting. Only after that
   result should the parked external-data programme be reconsidered.
