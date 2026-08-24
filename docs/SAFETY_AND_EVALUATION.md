# Safety, Leakage, and Evaluation

## Objective

The system must not merely appear conservative. It must demonstrate calibrated
behaviour under asymmetric read and write costs, including conditions designed
to expose memorisation, graph shortcuts, source leakage, and reward hacking.

## Evaluation separation

Maintain four physically and procedurally distinct classes:

1. training data;
2. development data available for ordinary decisions;
3. frozen confirmatory data opened after decisions are registered;
4. sealed private transfer data unavailable to training and evaluator tuning.

Access to sealed data must be logged. Once a sealed result influences a model or
policy decision, that set is no longer sealed for future confirmation.

The checked Phase 0 v4 registry applies these roles mechanically. SocialIQA
v1.4 validation remains development data. The EvidenceBench partition whose
content was previously opened remains diagnostic-only. Neither can regain
confirmatory status through renaming, encryption, or a new registry entry.
Role history is append-only and custody state cannot move backwards.

## Split requirements

Splits must occur at the highest relevant dependency unit:

- Wikipedia page family and revision history;
- Wikidata entity neighbourhood and sitelink family;
- source document and near-duplicate cluster;
- story, contract, paper, case, claimant, and organisation;
- time window;
- generator grammar and procedural world;
- extraction template or causal connective;
- domain and publisher where appropriate.

Random row splitting is prohibited when rows share a source, graph
neighbourhood, template, or revision lineage.

## Leakage register

Every dataset version must carry a leakage register covering:

- exact duplicate hashes;
- normalised and near-duplicate text matches;
- shared page, revision, document, story, paper, and entity IDs;
- graph-neighbourhood overlap;
- labels embedded in filenames, fields, templates, or metadata;
- target evidence present in model-only features;
- future information relative to a temporal test cutoff;
- upstream pretrained-model contamination that cannot be ruled out.

Public quarantine records may disclose only the minimum selectors needed to
detect source overlap. They must not disclose labels, answers, private worlds,
seeds, result reports, evaluator internals, or the private commitment nonce.
Every private envelope uses an unpredictable 256-bit nonce before its envelope
and record commitments are published; an unsalted hash of a predictable answer
is not confidentiality. Validation errors must identify paths and failed schema
keywords without echoing rejected private instances. Public exact and near-
match selectors still reveal membership for guessed source text, so their
release requires a separate disclosure review and must not be described as
zero-knowledge.

Unavoidable upstream contamination must be disclosed. A newly created private
evaluation is required for the strongest zero-shot claim.

## Reward-hacking controls

### Separate objectives and metrics

Do not collapse correctness, coverage, abstention, traversal cost, and write
safety into a single headline reward. Optimise and report them separately, then
choose a registered operating point subject to hard safety constraints.

### Shortcut tests

Every objective should be challenged with:

- label-only and metadata-only baselines;
- node-degree and path-length baselines;
- source-name and dataset-format removal;
- lexical-marker masking;
- evidence-order permutation;
- entity-name replacement;
- counterfactual qualifier and time swaps;
- disconnected or irrelevant evidence injection;
- plausible type-compatible negatives;
- label-shuffle tests;
- source and generator held-out evaluation.

If a weak shortcut baseline performs strongly, the objective is not accepted at
scale until the shortcut is removed or explicitly modelled.

### Synthetic-data controls

Synthetic examples require:

- deterministic seeds and full generator provenance;
- independent train/test world generation;
- held-out grammars and relation compositions;
- adversarial paraphrases;
- exact satisfiability checks;
- rejection of ambiguous worlds;
- no teacher answer accepted without a mechanical verifier where one exists.

LLM-generated labels must not become their own correctness oracle.

## Metrics

### Read path

- candidate recall;
- returned-claim precision and recall;
- evidence precision, recall, and sufficiency;
- path correctness;
- abstention precision and recall by reason;
- selective risk versus coverage;
- Brier score and calibration error;
- traversal expansions, latency, and budget exhaustion;
- cross-scope retrieval violations.

### Write path

- proposal recall;
- action classification by `attach`, `update`, `deprecate`, `new_node`,
  `duplicate`, `conflict`, `stage`, and `ignore`;
- false canonical-write rate;
- missed valid-write rate;
- incorrect merge rate;
- qualifier, evidence, and provenance correctness;
- temporal versioning correctness;
- rollback and audit completeness;
- downstream contamination caused by an incorrect write;
- cross-scope write violations.

### System behaviour

- performance by risk tier, source type, relation type, and domain;
- degradation under conflicting or stale evidence;
- calibration drift;
- catastrophic forgetting after specialist training;
- robustness to graph degree, entity popularity, and text length;
- private transfer performance.

Averages must not hide rare but high-cost failure classes.

## Risk-versus-coverage policy

Each action class receives its own risk-versus-coverage curve. Thresholds may
vary by explicit risk tier, but the tier definition and threshold-selection rule
must be registered before confirmatory evaluation.

Candidate memory can run at a broader operating point than canonical memory.
Internally explored nodes can run at a broader operating point than externally
returned facts.

## Memory-poisoning tests

Test at least:

- unsupported high-confidence assertions;
- many correlated sources repeating the same false origin;
- forged or circular provenance;
- source-collusion simulations;
- slow multi-step poisoning;
- stale facts with plausible dates;
- same-name entity collisions;
- malicious instructions embedded in evidence;
- attempts to cross tenant, user, claimant, or case boundaries;
- candidate claims cited as if they were canonical evidence.

The evaluator must measure not only whether one bad write is accepted, but how
far it propagates through later reads and writes.

## High-stakes gate

Before any medical, legal, financial, or safety-critical pilot:

1. freeze the intended task and allowed claims;
2. use anonymised or properly authorised data;
3. isolate cases and tenants mechanically;
4. require evidence display and provenance logging;
5. disable autonomous canonical writes unless separately approved;
6. define human-review responsibilities;
7. run domain-specific false-return and cross-case contamination tests;
8. document limitations without converting benchmark performance into a
   reliability claim.

## Stop conditions

Pause scaling when:

- train/test provenance cannot be reconstructed;
- a benchmark source cannot be quarantined;
- a model beats the task using metadata or surface cues alone;
- a licence does not clearly permit the intended use;
- unknown cases are being converted into false labels;
- generated examples cannot be mechanically checked;
- write errors contaminate later training targets;
- sealed test access has influenced model selection.
