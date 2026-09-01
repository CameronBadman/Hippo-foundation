# Decision Log and Open Questions

This file records architectural commitments separately from hypotheses. Dates
use Australia/Brisbane local time.

## Accepted decisions

### 2026-08-16: clean-room foundation

Older Hippocampus implementations, datasets, checkpoints, metrics, evaluators,
and reward designs are untrusted until audited. This folder is the new
documentation source of truth.

### 2026-08-16: shared traversal, separate terminal decisions

Read and write paths share a traversal core but have separate candidate and
acceptance decisions. A traversal score is not permission to return or commit.

### 2026-08-16: layered memory

Working, candidate, and canonical memory have different acceptance policies.
Uncertain facts may be staged rather than forced into accept/reject.

### 2026-08-16: progressive data curriculum

Wikipedia and Wikidata provide broad foundation training. Deterministic and
procedural objectives teach exact mechanics and policy. Smaller relationship,
evidence, contradiction, and reasoning datasets subsequently shape specific
capabilities. Domain data is introduced only after general calibration.

### 2026-08-16: asymmetric risk policy

The system may explore greedily while returning or committing conservatively.
Risk is conditioned on explicit node, source, scope, time, evidence, and action
metadata.

### 2026-08-16: provenance and unknown semantics

Every durable claim retains provenance and evidence. Missing edges and absent
evidence are unknown rather than false unless an explicit negative basis exists.

### 2026-08-16: frozen write training

Initial write-head training reconstructs or compares against frozen graph
snapshots. Model proposals do not mutate canonical training truth.

### 2026-08-16: multi-metric evaluation

Read correctness, write safety, abstention, calibration, traversal cost, and
contamination are evaluated separately. There is no single reward whose average
can conceal a high-cost regression.

### 2026-08-16: Phase 0 execution boundary

Phase 0 freezes contracts, inventories immutable bytes, quarantines evaluation
families, seals confirmatory material, and evaluates readiness. It has no model
or optimization dependency, exposes no training command, and can never
authorize training. Foundation acquisition and foundation transformation are
separate mechanical gates.

### 2026-08-17: Phase 0 v2 is the active evidence contract

The default CLI now requires stable provider/root resource IDs, fresh storage
attestation, exact terms-byte licence bindings, per-evaluation envelopes and
derived quarantine contributions, structural inventories, and source admission
receipts. Historical v1 commands remain explicitly suffixed and cannot satisfy
the v2 gate. Registry assertions are not represented as independent external
evidence when no captured source artifact exists.

### 2026-08-25: Phase 0 v4 is the active external-evidence firewall

Phase 0 v4 supersedes v2/v3 operationally while preserving their frozen
contracts. Its gate evaluates exact evidence directly and emits structured
subject-specific blockers. It binds the full Drive observation, retained
publisher statements, current rights bundles, explicit evaluation roles,
GPG-authenticated access anchors, the complete quarantine union, exact byte
audits, inventories, and admissions. Acquisition and transformation remain
separate, and training is always unauthorized. Phase 1 v2 does not consume v4;
that integration must be additive rather than a conversion of the frozen v2
gate schema.

### 2026-08-25: Phase 0 v4.1 supersedes v4 for execution authorization

The eight v4 schemas and legacy commands remain frozen, but `gate-v4` is no
longer an operational authorization boundary. V4.1 anchors every registry
lineage to the checked-in root, replaces self-asserted evaluation completeness
with independently recomputed materialization evidence, and breaks the
rights/seal custody cycle by binding rights, materialization, seals, logs, and
anchors to the penultimate pinned registry before producing one final
successor. Only `gate-v4.1` and `source acquire-v4.1` may support real Phase 0
execution. Training remains unconditionally unauthorized.

### 2026-09-02: READ run coverage is reported as route-completeness, selected by exposure

Gate 7 of the READ run's P0 report measures whether the target node lies inside
DIRECT's examined pool; proof-valid scoring needs a complete relation-matching
route to every target, a strictly stronger condition that
`read_run/coverage.py` now measures and that equals the evaluator's own
`proof_valid` flag. From Amendment 10 on, every READ report carries
route-completeness per arm, γ, budget and stratum beside gate 7's quantity,
which is called target-node exposure in prose. Gate 7's code, its 90% threshold
and its role in selecting the budget are deliberately unchanged, so the selected
budget is not silently re-derived; making route-completeness *select* a budget
would be a new gate version.

The primary statistic of any READ retry compares TRAV with the model-free
similarity-greedy arm, offset-subtracted at γ=0, under a sign-symmetric per-seed
rule; DIRECT is retained as the γ-invariant reference. The γ=0 gap is a reported
allocation offset, not a void condition. Amendment 10 is pending review; the
holdout stays sealed and nothing frozen changes.

### 2026-08-28: Phase 0 v4.2 roots OAuth and acquisition authority externally

Phase 0 v4.2 supersedes v4.1 for operational authorization while preserving all
frozen predecessor contracts and commands. A broad native DriveFS mount proves
only that Colab credential propagation and the mount worked; it does not prove
the exact API scope, OAuth client, Workspace organization, stable resource IDs,
or API-to-filesystem identity required by the data firewall.

V4.2 therefore requires a separately reviewed, code-pinned Internal Workspace
policy; detached administrator authority over the exact installed-client bytes,
Cloud project, resource IDs, and canonical marker; and a live proof that reads
the same marker through exact-scope Drive API and a pinned DriveFS root. The
mechanical proof is separate from the legacy human same-account observation and
must never synthesize that human statement.

Every real acquisition additionally requires a short-lived detached signature
over the exact artifact, registry, storage identity, expected bytes, and byte
ceiling. The acquisition command recomputes its precondition gate, binds
resumable partials to that signature, repeats live identity before immutable
promotion, and retains enough evidence for later reproduction. Completed
acquisition evidence remains historically valid after the short authorization
expires; new transfer does not. Training remains unconditionally unauthorized.

### 2026-08-25: evaluation roles cannot be laundered

SocialIQA v1.4 validation is development-only and the exposed EvidenceBench
partition is diagnostic-only. Five other datasets remain unsealed
confirmatory candidates. A development or exposed partition cannot regain
confirmation status through renaming, encryption, or registry versioning.
Exposure history is append-only and custody cannot move backwards.

### 2026-08-25: private commitments require nonce hardening

Each v4 private evaluation envelope contains an unpredictable 256-bit nonce.
Public record and envelope commitments bind the private material without
publishing that nonce or payload. Validation errors report only paths and
failed schema keywords. Public overlap selectors remain membership-revealing
for guessed text and are not represented as zero-knowledge evidence.

### 2026-08-18: native-first, identity-bound Drive access

Phase 0 attempts Colab's native read-only Drive mount before any fallback. A
fallback may use only the pinned read-only rclone path, the same explicit ADC
file for API resolution, mount authentication, and observation, plus human
same-account attestation. It remains disabled without an approved protected
desktop OAuth client file. Neither path relaxes stable resource identity,
frozen observation fields, the 15-minute binding window, or the prohibition on
Drive writes and training.

### 2026-08-17: Phase 1 is data preparation only

Phase 1 freezes graph, objective, encoder, artifact-manifest, and gate schemas;
it validates and deterministically assembles development artifacts. It exposes
no train, fit, optimize, or model command, and its gate always emits
`training_authorized: false`. A separately reviewed authorization boundary is
required before any future training work.

### 2026-08-24: Phase 2B process data remains preparation only

Phase 2B freezes additive process-state and write-policy contracts and creates
role-disjoint training/development candidates for eight staged-write actions.
Declarative and copy-on-write oracles must agree; every detached patch must
replay and roll back on a disposable copy. Patch application is not a canonical
write surface. Rights remain pending, the reservation index is not the complete
Phase 0 union, every artifact declares `training_authorized: false`, and the
CLI still exposes no train, fit, optimize, model, commit, or apply command.

### 2026-08-18: Phase 2A procedural data remains preparation only

Phase 2A freezes signed open-world policy examples and generates role-disjoint
training/development candidates with agenda and proof-tree verification. Its
local reservation quarantine index is a fixture, not the complete Phase 0
union. Source rights remain pending, every artifact declares
`training_authorized: false`, and the CLI exposes no training or model surface.
Human-readable case names are prohibited from prediction metadata because they
create a direct label shortcut.

### 2026-08-17: frozen Phase 1 text encoder

The prior encoder bake-off selects `Alibaba-NLP/gte-modernbert-base` at revision
`e7f32e3c00f91d699e8c43b53106206bcc72bb22`, with 768-dimensional CLS output,
no normalization, and a 2,048-token default context. The input recipe is title,
two newlines, then body. Runtime assets and the bake-off report are byte-pinned.
This freezes a non-trainable data-preparation encoder identity, not the later
trainable traversal/model backbone. Static verification is not a numerical
inference test or a licence decision.

### 2026-08-17: deterministic auditable Phase 1 subset

The required subset has 40,000 nodes with seed `20260817`, complete community
coverage, and water-filled joint source/length/degree/PageRank strata. One-hop
neighbour caps retain every exclusion in a typed overflow ledger. Development
objective replay covers eight frozen families, permits at most seven negatives
beside one target, and requires an explicit evidence-backed negative basis;
absence of an edge is not a negative.

### 2026-08-16, revised 2026-08-25: public evaluation quarantine

The v4 registry assigns VitaminC, ContractNLI, EventStoryLine v1.5, and two
private first-party families to confirmatory candidate use. EvidenceBench is
diagnostic and SocialIQA validation is development-only. All seven roles'
document/work/entity/story/contract/time/generator dependencies, exact hashes,
and near duplicates must be excluded before foundation transformation. Each
dataset has separate coverage; confirmatory coverage is also bound to its
encrypted receipt and authenticated anchor. A union index cannot conceal a
missing dataset. The five confirmation candidates remain unsealed and blocked.

### 2026-08-16: offline-key confirmatory vault

Label-bearing manifests, answers, and split membership remain encrypted to a
custodian-held offline GPG private key. Development and Colab environments may
hold only the public key. The public union contains identifiers and
fingerprints, never label-bearing fields.

### 2026-08-16: pinned full Wikidata source

The official Wikidata `20260720` full JSON bzip2 dump is the registered
foundation candidate because it preserves ranks, qualifiers, references, and
sitelinks. Acquisition is allowed only from its registered publisher URL into
the registered Google shared-Drive identity after the existing lake audit and
public quarantine gates pass. The later choice to pair or transform English
Wikipedia remains undecided because the current copy is pre-clean-room.

## Candidate decisions requiring admission or later registration

- Admit the registered English Wikipedia `20260801` and Wikidata `20260720`
  pair only after both pass the Phase 0 v4 evidence and admission controls.
- Add Wikidata before other large external graphs.
- Evaluate ASER Core and CauseNet before their larger/noisier alternatives.
- Pair a filtered OpenAlex graph with commercial-use-compatible PMC full text
  for later scholarly and medical evidence shaping.

These candidates require manifests, licence review, storage plans, and leakage
quarantines before they become accepted dataset decisions.

## Open questions

1. Which evidence-backed revisions, if any, does the frozen Phase 1 graph schema
   need after real admitted records are transformed?
2. Should read and write heads share all traversal parameters or only the input
   and neighbour encoders?
3. Which decisions remain deterministic policy constraints rather than learned
   behaviour?
4. How should independent evidence sources be identified when many publishers
   repeat one origin?
5. What procedural worlds best predict real graph transfer?
6. How should calibration transfer across node and domain risk tiers?
7. What evidence is sufficient to promote a staged claim?
8. How are conflicting but temporally compatible claims represented?
9. Which private evaluation domains can remain genuinely unseen?
10. What model scale is justified by unique semantic contexts rather than raw
    edge count?

## Deliberately not decided

- production product shape;
- medical or medicolegal workflow;
- customer-specific implementation;
- trainable traversal/model backbone or parameter count;
- graph database;
- online autonomous writing;
- final training mixture or thresholds;
- claims of determinism, accuracy, or safety.
