# Dataset role, lineage, and rights review

Review date: 2026-08-18

## Outcome

The current evaluation registry is not a training-data roster. Its entries were
declared for confirmatory evaluation, and their labels or results must not be
used to select model architecture, dataset mixtures, thresholds, prompts, or
training duration.

The defensible near-term training roster is narrower:

1. dated English Wikipedia and full Wikidata JSON snapshots for foundation
   breadth, after rights approval, byte verification, and evaluation-family
   quarantine;
2. first-party procedural graph data for exact traversal, open-world, process,
   and write-policy supervision, after the generators and independent oracles
   exist;
3. only the official training partitions of VitaminC, ContractNLI, and
   SocialIQA as optional specialist supervision, after lineage and rights
   review;
4. public development partitions for development only; and
5. source-disjoint tests plus independently held first-party sets for
   confirmation.

More datasets are not automatically better. A source belongs in training only
when it adds a named behaviour, has an admissible licence and provenance path,
and survives leakage and shortcut controls.

## Scope and evidence standard

This review used publisher repositories, official project pages, papers, and
Wikimedia/IARC policy pages. It did not open item-level held-out examples. A
repository licence is recorded as a publisher assertion, not as proof that the
publisher controls every embedded article, contract, paper, or news story. No
pending human rights assessment is changed by this review.

The registered snapshot dates and commit IDs remain project declarations until
their remote artifacts, publisher hashes, and local bytes are independently
verified.

## Role matrix

| Asset | Verified publisher facts | Honest project role | Mandatory isolation |
|---|---|---|---|
| Wikidata full JSON | Wikidata describes dumps as complete entity exports and states that its structured data is CC0. Its own data-access documentation says the `simple` entity representation omits qualifiers and references. | Foundation training candidate. Use the full JSON form because graph semantics require ranks, qualifiers, references, and non-best statements. | Freeze a dated dump; split and quarantine by entity, sitelink, neighbourhood, revision, and linked evaluation family before transformation. |
| English Wikipedia | Wikimedia's dump guidance applies CC BY-SA 4.0/GFDL to original text but also warns about fair-use material and possible undetected infringement. | Foundation training candidate after accountable rights and attribution decisions. | Quarantine page and revision families, imported-source lineage, exact and near duplicates, and all pages underlying VitaminC or other evaluations. |
| VitaminC | The project reports more than 400,000 contrastive claim/evidence pairs from more than 100,000 factual Wikipedia revisions. Its paper says splits were assigned by article and kept consistent with FEVER for overlap. Its data notice applies Wikipedia-page terms and identifies FEVER-derived synthetic annotations. | Official train only: specialist supervision for evidence sensitivity and contradiction. Official dev is development; official test is within-project confirmation, not training. | Preserve article, page, revision, claim, and FEVER source families. Quarantine every dev/test family from Wikipedia foundation data before features or embeddings. |
| ContractNLI | The paper reports 607 contracts split by document into 423 train, 61 development, and 123 test records, stratified by source format. The publisher states CC BY 4.0 and places click-through terms on download. | Train/dev/test can retain their official roles after authorized terms acceptance and embedded-text review. Useful for long-document evidence, entailment, contradiction, and `not mentioned`. | Recheck overlap by contract, filing, organisation, template, and near-duplicate cluster; do not assume document-level splitting removed entity or template leakage. |
| EventStoryLine v1.5 | The repository says v1.5 combines expert v1.0 and crowd v1.2 plot-link annotations and distributes evaluation data; its top-level licence is CC BY 3.0. The paper describes cross-document news stories clustered around a seminal event or topic. | Confirmatory or diagnostic event/causal evaluation after embedded-news rights review. It is not a large independent training source. | Treat v1.0, v1.2, and v1.5 as overlapping views of one corpus, not separate splits. Isolate by topic, story, document, event cluster, publisher, and time window. |
| EvidenceBench original | The repository reports 426 items split 96/37/293 and says the public test is CC BY while train/dev are non-commercial ShareAlike; each candidate pool contains paper sentences. IARC's terms restrict substantial or commercial reuse absent permission and warn about third-party components. | The current original test is retired from clean confirmation because the project records prior exposure. At most it is a labelled diagnostic. Train/dev are not commercial-training candidates without a separate legal basis. | Replace with a genuinely fresh, independently custodied set and bind per-paper rights and source bytes. Split by paper, DOI/PMID/PMCID, publication family, systematic review, and near-duplicate text. |
| SocialIQA v1.4 | The paper reports 37,588 questions, says contexts are derived from ATOMIC events, and assigns contexts to the same train/dev/test partition as their source ATOMIC event. The current publisher dataset card exposes 33,410 train and 1,954 validation examples and identifies CC BY 4.0. The paper used dev performance for hyperparameter selection. | Official train is a possible specialist source after ATOMIC lineage closure. Public validation is development only and cannot be confirmatory. A fresh test needs independent custody or a replacement design. | Preserve ATOMIC event/source, scenario, template, reasoning dimension, and near-duplicate families across all downstream SocialIQA records. |
| First-party open-world and process generators | The registry declares these sets, but no generator, independent oracle, or sealed output exists. | Highest-priority route to clean procedural training and private confirmation once implemented. | Split before generation by grammar, world, rule composition, operation family, and seed family. Keep test grammars/seeds with an independent custodian and oracle implementation. |

Primary evidence:

- [Wikidata data access and dump guidance](https://www.wikidata.org/wiki/Wikidata:Data_access)
- [Wikimedia dump licensing and exceptions](https://dumps.wikimedia.org/legal.html)
- [Wikimedia content reuse terms](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/en#7._Licensing_of_Content)
- [VitaminC repository and data notice](https://github.com/TalSchuster/VitaminC), [VitaminC paper](https://aclanthology.org/2021.naacl-main.52/)
- [ContractNLI publisher page and download terms](https://stanfordnlp.github.io/contract-nli/), [ContractNLI paper](https://aclanthology.org/2021.findings-emnlp.164/)
- [EventStoryLine repository](https://github.com/tommasoc80/EventStoryLine), [v1.5 publisher record](https://research.rug.nl/en/datasets/the-event-storyline-corpus-v15/), [corpus paper](https://aclanthology.org/W17-2711/)
- [EvidenceBench repository and split licences](https://github.com/EvidenceBench/EvidenceBench), [IARC publication terms](https://publications.iarc.who.int/Terms-Of-Use)
- [SocialIQA publisher page](https://maartensap.com/social-iqa/), [publisher dataset card](https://huggingface.co/datasets/allenai/social_i_qa), [SocialIQA paper](https://aclanthology.org/D19-1454/)

## Corrected curriculum

### Foundation stage

Transform admitted Wikipedia and Wikidata bytes into a provenance-preserving
graph. Use deterministic graph-mechanics objectives first. The frozen encoder
is a data-preparation component, not the trainable memory policy.

Before any transformation, compile the union of all confirmatory document,
page, revision, entity, story, contract, paper, ATOMIC, template, and
near-duplicate families. Matching after features or embeddings are built is too
late because held-out information may already influence representation and
sampling.

### Procedural stage

Implement separate first-party training and confirmatory generators for:

- open-world entailment where absence remains unknown;
- path continuation and stopping;
- evidence-supported return versus abstention;
- process-state transitions;
- attach/update/duplicate/conflict/stage decisions; and
- asymmetric read and write costs.

The oracle must be independently implemented or cross-checked against a second
derivation. A random row split from one grammar is not independent evaluation.

### Specialist stage

Adapt official training partitions through one common provenance-rich example
contract. Start with small, separately ablated mixtures of VitaminC,
ContractNLI, and SocialIQA. Dataset ratios are selected on development data and
then frozen. Do not sequentially fine-tune through datasets without measuring
catastrophic forgetting on foundation and procedural objectives.

EventStoryLine is too overlapping across versions to manufacture independent
train/dev/test sets from v1.0, v1.2, and v1.5. EvidenceBench's current original
test cannot recover clean status merely by being sealed after exposure.

### Confirmation stage

Public test sets can measure within-project generalisation when they were kept
out of this project's decisions, but their public availability means they do
not establish that a pretrained backbone has never seen them. Report that
limitation. Strong confirmation should lean on fresh first-party sets under
independent custody, source-disjoint time windows, and later domain transfer.

## Mechanical requirements before a training implementation

1. Create a training-source registry separate from the confirmatory evaluation
   registry. Require explicit `training`, `development`, `diagnostic`, or
   `confirmatory` stage and reject cross-stage asset hashes.
2. Define the prediction unit, information available at prediction time,
   outcome, cost matrix, and split unit for every objective family.
3. Acquire and hash raw archives without reading held-out item content into the
   development environment; the custodian should derive public quarantine
   selectors.
4. Split by the highest dependency unit before preprocessing. Fit learned
   preprocessing only on training folds.
5. Run exact-hash, normalized-hash, near-duplicate, entity/document/story, and
   temporal-overlap checks across every source pair.
6. Use simple baselines, negative controls, source-only/template-only
   classifiers, ablations, repeated seeds, calibration, and per-family metrics.
7. Freeze architecture, mixtures, hyperparameters, thresholds, and reporting
   code before opening confirmatory results.
8. Never convert a public validation split into a confirmatory split by naming
   or sealing it. The active gate now rejects partitions explicitly named
   `dev`, `development`, or `validation`.

## Unresolved decisions

- Whether the intended deployment is commercial materially changes which
  non-commercial datasets are admissible; the current controls correctly leave
  this to accountable review.
- Wikipedia attribution and ShareAlike treatment for graph artifacts,
  embeddings, checkpoints, and service outputs remains a legal and product
  decision, not a code inference.
- The current evaluation registry needs a versioned redesign that separates
  development, diagnostic, and confirmatory records. Until then, its blockers
  must remain and it must not be repurposed as training configuration.
