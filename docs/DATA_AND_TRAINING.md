# Data and Training Strategy

## Purpose

No single dataset contains the required behaviour. Large natural corpora supply
breadth, deterministic transformations supply scalable objectives, and smaller
gold datasets shape particular reasoning and evidence decisions.

This document is a future curriculum design, not authorization to train. The
current implementation stops at Phase 1 data preparation, and both mechanical
gates hard-code `training_authorized: false`.

The evidence-backed role and lineage review is recorded in
[`audit/DATASET_REVIEW.md`](../audit/DATASET_REVIEW.md). It corrects two
important declarations: SocialIQA validation is development data, not clean
confirmation, and the exposed EvidenceBench original test is diagnostic until
replaced. The active gate now rejects partitions explicitly named `dev`,
`development`, or `validation` as confirmatory evidence.

Datasets are not poured into one undifferentiated mixture. Every source receives
a declared role, trust level, licence state, contamination policy, sampling
policy, and allowed evaluation use.

## Common training-example contract

Every transformed example should be representable with:

- immutable example and transformation identifiers;
- source dataset, version, record IDs, and hashes;
- graph snapshot and schema version;
- input query or incoming observation;
- permitted starting state;
- candidate nodes, edges, and traversal actions;
- target read or write action;
- supporting, contradicting, and unresolved evidence;
- qualifiers and valid/observation times;
- scope and risk class;
- negative-generation method;
- generator/tool version and deterministic seed;
- split and quarantine membership.

Materialised examples should reference source documents rather than duplicate
their full text for every edge.

## Dataset roles

### Foundation breadth

Wikipedia supplies natural language, entities, document structure, hyperlinks,
and broad domain coverage. Wikidata supplies structured statements, ranks,
qualifiers, references, values, units, and sitelinks.

Candidate temporally aligned snapshot pair:

- English Wikipedia: `20260801`;
- Wikidata full JSON: `20260720`, the nearest currently identified completed
  full-JSON snapshot before the Wikipedia snapshot.

This pair is a candidate registration, not an implicit floating `latest`
dependency. The full Wikidata JSON is required; truthy RDF is insufficient
because it omits qualifiers, references, and non-best-ranked statements.

Primary sources:

- <https://dumps.wikimedia.org/enwiki/20260801/>
- <https://dumps.wikimedia.org/wikidatawiki/entities/20260720/>
- <https://www.wikidata.org/wiki/Wikidata:Database_download>

### Relationship and event shaping

- EventStoryLine v1.5 is the currently declared confirmatory event, temporal,
  and causal family; its embedded-news rights review remains unresolved.
- MAVEN-ERE remains a possible later shaping source and is not currently
  admitted or registered as confirmatory data.
- ASER: large automatically extracted eventuality/discourse graph; licence and
  source-provenance audit required before commercial use.
- CauseNet: claimed causal graph with source evidence; automatically extracted
  and therefore noisy.
- CausalBank: very large pattern-mined cause/effect pairs; suitable only after
  lexical-shortcut controls and explicit-negative supplementation.
- GLUCOSE and WIQA: smaller, denser causal explanation signals.

### Evidence and qualification shaping

- VitaminC: revision-grounded support and contradiction.
- EvidenceBench: biomedical evidence retrieval; embedded paper-text rights and
  adapter lineage remain unresolved.
- ContractNLI: entailment, contradiction, and not-mentioned decisions over long
  contracts.
- The first-party open-world Phase 2A training/development fixture is locally
  implemented and independently cross-checked, but is not admitted or
  authorized for training. The process-state generator and private
  confirmatory generator remain unimplemented.
- SocialIQA train is a possible later shaping source after ATOMIC lineage
  closure and rights review. Its public validation partition is development
  data and cannot be confirmatory.

These are possible supervision and evaluation assets, not foundation-scale
corpora. The seven records in `registries/evaluations.v2.json` are historical
confirmatory declarations, not a training roster. That registry must be revised
before sealing because one record names a validation partition and another has
a recorded exposure incident. Every other named dataset remains an unadmitted
candidate.

### Write and change shaping

- Wikipedia and Wikidata revision deltas;
- WikiAtomicEdits for atomic insertion/deletion prototypes;
- retractions and corrections linked through scholarly metadata;
- later, licensed domain-specific document histories.

Edits are proposals, not truth labels. Reverts, vandalism, formatting changes,
source disputes, and later corrections must remain distinguishable.

### Scholarly evidence graph

OpenAlex metadata can supply works, citations, authors, institutions, dates,
topics, retractions, and corrections. Commercial-use-compatible PMC Open Access
full text can supply evidence spans. Join through DOI, PMID, PMCID, and other
stable identifiers.

OpenAlex metadata being CC0 does not make every linked full-text work CC0. PMC
licences must be filtered and retained per article.

### Deferred noisy temporal sources

GDELT and broad web corpora may later provide temporal events and source
disagreement. They are not early-stage truth sources. Their automatically
extracted records, source-text rights, duplication, and adversarial content
require a separate ingestion policy.

## Progressive curriculum

### Phase 0: quarantine before transformation

1. Select candidate benchmark and transfer datasets.
2. Register all known source documents, Wikipedia page/revision IDs, Wikidata
   entities, stories, contracts, papers, and near-duplicate fingerprints.
3. Exclude quarantined sources and related revisions from foundation training.
4. Seal private evaluation manifests before objective development.

Quarantine must happen before data-derived features, embeddings, hard negatives,
or graph neighbourhoods are constructed.

### Phase 1: graph-mechanics data preparation

Construct and audit deterministic development examples for:

- masked node attribute recovery;
- masked edge and direction recovery;
- masked qualifier and value recovery;
- evidence-span alignment;
- local entity disambiguation;
- bounded path continuation and stopping;
- neighbourhood ranking;
- source and time-conditioned retrieval.

Begin with the frozen 40,000-node auditable subset. The current implementation
validates and replays these examples but does not train on them. Any later
training phase requires a separate authorization and may scale only objectives
that pass shortcut and leakage tests.

### Phase 2: exact policy preparation, then separately authorized learning

Use procedural graphs with known ground truth to train:

- return versus abstain;
- continue versus stop;
- attach versus new node;
- update versus duplicate;
- conflict versus overwrite;
- stage versus canonical commit;
- behaviour under different action-cost matrices.

Procedural generation must split by world, generator grammar, relation
composition, and seed family. A random example split is insufficient.

The current Phase 2A implementation prepares and verifies only the first two
read-path decisions. It contains no trainer and does not authorize use of its
candidate artifacts. Phase 2B next covers reversible staged-write decisions;
any actual learning remains behind a separate authorization boundary.

### Phase 3: specialist multitask shaping

Introduce the smaller relationship, causal, evidence, NLI, and proof datasets
through a common schema. Use a controlled sampler and retain foundation replay.
Do not fine-tune through each dataset sequentially without measuring forgetting.

Dataset identity must not be exposed through templates or formatting that lets
the model infer the answer policy from the source name.

### Phase 4: noisy real-world change

Train proposal generation using revision histories and automatically extracted
graphs. Keep the acceptance gate anchored by higher-trust data and explicit
policy constraints. Noisy sources may improve candidate recall without being
allowed to define canonical-write thresholds.

### Phase 5: calibration and transfer

Freeze ordinary model choices before opening confirmatory data. Calibrate read
and write gates independently on source-disjoint examples, then evaluate on
entirely held-out domains and private cases.

High-stakes domain adaptation occurs only after the general system demonstrates
stable abstention, provenance, and isolation behaviour.

## Negative supervision

Negative labels require an explicit basis:

- direct contradiction in evidence;
- mutually incompatible values under the same qualifiers and valid time;
- source-corrected or retracted statements;
- type-compatible near misses;
- wrong-entity and same-name confusions;
- temporal incompatibility;
- path candidates that are plausible but unsupported;
- explicit `unknown` and `insufficient_evidence` cases.

Do not treat a missing graph edge, missing citation, or absent sentence as false.
Do not rely only on random corruption; it mostly creates easy type and degree
shortcuts.

Deprecated Wikidata ranks and removed revisions are candidate signals, not
automatic false labels. Their reasons and later history must be considered.

## Sampling

Sampling must control for:

- dataset size and annotation density;
- repeated source documents;
- high-degree nodes and popular entities;
- relation and qualifier frequency;
- document length;
- easy versus hard negatives;
- risk class;
- noisy versus gold supervision;
- foundation replay during specialist shaping.

Sampling ratios are ablations. They must not be selected using sealed test
performance.

## Storage approach

1. Preserve immutable compressed originals and official checksums.
2. Stream-transform large archives; do not retain unnecessary decompressed
   copies.
3. Store documents, evidence, nodes, edges, qualifiers, and splits separately.
4. Use compact columnar shards with deterministic ordering and checksums.
5. Keep transformation manifests, rejection reports, and row counts.
6. Never overwrite a registered dataset version.

## Required inventory before training

For every source, record:

- exact version/date and download URL;
- official and local hashes;
- compressed and materialised bytes;
- licence and commercial-use status;
- unique documents and versions;
- tokens, nodes, edges, qualifiers, and evidence spans;
- entity and document overlap with every other source;
- transformation losses and rejected records;
- split construction and quarantine coverage.
