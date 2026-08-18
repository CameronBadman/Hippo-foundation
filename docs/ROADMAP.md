# Hippocampus Foundation roadmap

## Product boundary

The target is an offline, evidence-grounded graph-memory prototype. It may
return supported information, abstain, and propose reversible staged writes.
It may not autonomously commit canonical memory or make high-stakes decisions.

The default data lane must remain compatible with intended commercial use.
Research-only or unresolved assets are excluded unless a separately governed
lane is approved later. Dataset roles are immutable: training, development,
diagnostic, and confirmatory artifacts may not share bytes or dependency
families.

## Current checkpoint

Phase 0 v3 and Phase 1 v2 implement fail-closed governance and deterministic
data-preparation controls, but both gates remain blocked. There is no trainer,
ML runtime dependency, authorized training corpus, model checkpoint, or
performance result. The immediate local work can establish task semantics and
data integrity while storage, licensing, and custody dependencies are resolved
in parallel.

## Programme

### 1. Prove open-world semantics locally

Implement the Phase 2A procedural open-world slice specified in
`NEXT_MILESTONE.md`. It must produce deterministic training/development
candidates, compare two independent oracles, enforce dependency-family split
isolation, and remain incapable of training a model.

Exit when public fixtures reproduce byte-for-byte, oracle disagreement is
zero, cross-role overlap is zero, and all artifacts still declare
`training_authorized: false`.

### 2. Prove staged-write semantics locally

Add a separate process-state and write-policy generator covering `attach`,
`update`, `deprecate`, `new_node`, `duplicate`, `conflict`, `stage`, and
`ignore`. Split by operation family, grammar, world, composition, and seed
family before generation. Verify state transitions with an independently
implemented oracle and never let predicted writes mutate later targets.

Exit when every action has mechanically checked positive, negative, conflict,
and unknown cases with no split-family overlap.

### 3. Complete the external evidence firewall

In parallel with the local generators:

- replace the current evaluation declarations with explicit development,
  diagnostic, and valid confirmatory roles;
- keep SocialIQA validation in development and the exposed EvidenceBench set in
  diagnostic/retired status;
- resolve exact Drive identity, publisher checksums, and accountable human
  rights decisions;
- pin adapters and archives, create dependency-closed envelopes, seal valid
  confirmation sets, and independently anchor every access-log head; and
- compile the complete public quarantine union before any source
  transformation.

Exit only with a fresh Phase 0 v3 report where foundation transformation is
ready and training remains unauthorized.

### 4. Define and build the real graph-data path

Version a provenance-complete graph/evidence contract before implementing raw
adapters. It must represent immutable evidence documents and spans, content
hashes, source-independence groups, valid and observation time, scope, risk,
conflict, and lifecycle state.

Implement exact quarantine matching before graph metrics, embeddings, hard
negatives, or sampling. Stream-transform small synthetic Wikipedia/Wikidata
fixtures first, then only admitted real bytes. Reopen and rehash every artifact
referenced by a readiness manifest.

Exit when the fixture pipeline is deterministic and real-data execution is
mechanically impossible without a ready Phase 0 gate.

### 5. Complete Phase 1 data preparation

Generate and independently audit all eight graph-mechanics objective families,
the frozen 40,000-node sample, and the complete neighbour-overflow ledger.
Recover and freshly verify the historical encoder assets or register a new
version after a clean development-only bake-off; do not reconstruct missing
evidence.

Exit with a reproducible Phase 1 gate reporting data readiness while still
reporting `training_authorized: false`.

### 6. Create the training authorization boundary

Add a separate gate binding admitted training hashes, frozen role-exclusive
splits, mixture ratios, model configuration, seed plan, dependency versions,
checkpoint lineage, evaluator versions, and accountable approval. Heavy ML
dependencies and training commands remain outside Phase 0 and Phase 1.

Before authorization, require majority, random, degree/path, lexical,
source/template-only, dense-retrieval, and label-shuffle baselines. Define
prediction time, costs, thresholds, and per-action metrics before optimization.

### 7. Train a small credible prototype

Begin with frozen text representations, a small shared traversal core, separate
read and staged-write candidate heads, and separate acceptance calibrators.
Train first on procedural worlds, then graph mechanics, then separately ablated
approved specialist training partitions. Select mixtures and thresholds only
on development data and measure forgetting after every specialist stage.

Exit only after improvements reproduce across seeds and cannot be explained by
shortcut baselines, leakage, or evaluator defects.

### 8. Confirm and release conservatively

Freeze code, data hashes, configuration, thresholds, and reporting before one
custodian-run confirmation. Report correctness, evidence sufficiency,
abstention, calibration, traversal cost, false returns, false staged writes,
and cross-scope violations separately. Any consumed or decision-influencing
holdout is retired.

The first release remains offline and staged-write-only. Canonical writes,
online learning, multi-tenant operation, and medical, legal, financial, or
safety-critical use require separate evidence and approval.

## Programme-level stop conditions

Pause progression if provenance cannot be reconstructed, rights do not permit
the intended use, quarantine coverage is incomplete, a weak shortcut explains
performance, unknown facts become negative labels, oracle agreement fails, or
confirmatory evidence influences development decisions.

Choose and add a project licence before public package distribution; the
repository currently has no project-level licence.
