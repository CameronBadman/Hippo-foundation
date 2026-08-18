# Architecture

## Objective

Build a model that can navigate a heterogeneous graph and make calibrated read
and write decisions. It must distinguish internal exploration from externally
visible returns and distinguish proposed changes from durable memory commits.

The trainable architecture remains model-family-neutral. No traversal/model
backbone, graph database, or parameter count is frozen. Phase 1 separately
freezes `Alibaba-NLP/gte-modernbert-base` as a non-trainable text encoder for
deterministic data preparation; that choice does not select the later trainable
model family.

## Graph contract

### Node

A node represents an entity, event, claim, document, episode, concept, or
scope-specific object. A node must support:

- stable node identifier;
- node type and schema version;
- canonical and alternate labels;
- source scope, tenant, user, case, or episode boundary;
- valid time and observation time where applicable;
- lifecycle state: working, candidate, canonical, disputed, deprecated, or
  tombstoned;
- provenance references;
- sensitivity and risk class;
- confidence and calibration namespace;
- immutable creation metadata and version history.

### Edge

An edge is not merely `(subject, predicate, object)`. It must support:

- stable edge or statement identifier;
- source and destination nodes;
- relation type and direction;
- qualifiers, including temporal, spatial, conditional, quantitative, modal,
  and role information;
- supporting and contradicting evidence spans;
- provenance and source independence group;
- valid time and observation time;
- assertion status and rank;
- extraction method and model/tool version;
- confidence, uncertainty, and conflict state;
- lifecycle state and complete revision history.

Absence of an edge is not a negative edge.

### Evidence

Evidence is stored separately from claims so that text is not copied once per
edge. An evidence record contains:

- immutable document and version identifier;
- exact span offsets or structured-cell coordinates;
- content hash;
- source URL or dataset record identifier;
- retrieval timestamp and licence metadata;
- stance: supports, contradicts, contextualises, or unresolved;
- extraction and alignment method;
- source independence group.

## Model components

```text
input/query/new observation
            |
            v
      input representation
            |
            v
   shared traversal policy/core
       /                  \
      v                    v
read candidate head   write candidate head
      |                    |
      v                    v
return/abstain gate   commit/stage/reject gate
      |                    |
      v                    v
evidence-grounded      versioned memory
response               transition proposal
```

### Shared traversal core

The core scores neighbouring nodes and edges, maintains traversal state, and
decides how to allocate a bounded search budget. It should learn local and
multi-hop navigation without receiving privileged destination-page text or
other target-only information.

Candidate expansion may favour recall. The core is not authorised to return an
answer or mutate memory by itself.

### Read path

The read path supports the following terminal actions:

- `continue`: spend more traversal budget;
- `return`: return selected nodes, claims, paths, and evidence;
- `abstain_unknown`: relevant information is not established;
- `abstain_ambiguous`: entity, scope, or question is unresolved;
- `abstain_conflict`: material sources disagree;
- `stop_irrelevant`: no candidate justifies further traversal.

The returned object must identify which evidence supports each claim. Internal
candidates that fail the terminal gate are not exposed as facts.

### Write path

The write path proposes one of:

- `attach`: add a new supported relationship;
- `update`: create a new version of an existing claim;
- `deprecate`: retain history while marking an older claim superseded or
  unsupported;
- `new_node`: create an entity/event/claim because no existing node matches;
- `duplicate`: link or merge a likely duplicate through a reversible proposal;
- `conflict`: preserve incompatible claims and their separate evidence;
- `stage`: retain an uncertain proposal in candidate memory;
- `ignore`: take no memory action.

Training initially scores proposals against a frozen target graph. Predicted
writes must not alter later examples in the same training corpus.

### Verifier and calibrator

Acceptance is separately calibrated from candidate scoring. It may combine a
learned verifier with deterministic policy constraints. Inputs include:

- action type;
- node and edge risk classes;
- source reliability and independence;
- evidence sufficiency;
- temporal compatibility;
- conflict and ambiguity state;
- scope boundary;
- reversibility and downstream propagation cost.

A high candidate score does not imply permission to return or commit.

## Risk-sensitive behaviour

Conservative versus greedy behaviour is conditional, not global.

The system can traverse greedily when the action is internal, reversible, and
low-cost. It must become conservative when information crosses a case boundary,
is returned as established fact, changes canonical memory, or can influence
many downstream nodes.

Risk tiers and their consequences must be explicit configuration and evaluation
inputs. They must not be inferred solely from a latent node embedding.

## Invariants

1. Canonical history is append-only and versioned.
2. A committed write always points to its proposal, evidence, and policy
   decision.
3. Cross-scope traversal requires an explicit allowed relationship.
4. Conflicting claims may coexist; the graph does not silently overwrite them.
5. Confidence is namespaced by model, task, and calibration set.
6. Evidence and provenance cannot be supplied only after a decision.
7. A model cannot promote its own generated statement solely by citing itself.
8. Candidate-memory contamination cannot automatically propagate into
   canonical retrieval.

## Deferred decisions

- trainable traversal/model backbone and its tokenizer;
- textual versus graph-native node representation;
- sparse, dense, or hybrid neighbour retrieval;
- traversal state representation;
- graph database and serving system;
- parameter sharing between heads;
- online learning mechanism;
- exact risk tiers and acceptance thresholds.

These are experimental decisions and must be resolved through registered
ablations rather than assumed here.
