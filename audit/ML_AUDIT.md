# Machine-learning integrity audit — Phases 0, 1, 2A, and 2B

Updated: 2026-08-25

## Decision boundary

The current operational decisions are only:

1. whether registered source acquisition or transformation may begin under the
   direct Phase 0 v4 external-evidence firewall; and
2. whether deterministic Phase 1 v2 development-data artifacts satisfy their
   frozen contracts; and
3. whether the local Phase 2A procedural candidates reproduce exactly, agree
   across two oracles, and remain isolated across training/development roles;
   and
4. whether the local Phase 2B process candidates reproduce exactly, agree
   across two transition oracles, roll back exactly, and remain isolated from
   the other training/development procedural artifacts.

None of these decisions permits model training. There is no measured predictive
performance and no basis for a claim about model quality, safety, calibration,
or usefulness.

This restoration review reran the local contracts, tests, gates, and package
build. The Better Colab and live Drive observations below are preserved
historical evidence from the restored audit record; they were not repeated in
this review and are not treated as new verification.

The future evaluation decision is declared in
`registries/evaluations.v4.json`: assess frozen evidence-grounded graph-memory
behaviour before confirmatory labels, answers, hidden spans, or results are
disclosed. The population is the exact sealed partitions and private generated
sets. The split unit is the highest available document, work, entity, story,
contract, paper, generator, world, seed-family, or temporal dependency. Metrics
must be reported per family and safety dimension; no scalar average may hide
contamination or false acceptance. The principal error cost is asymmetric:
unsupported returned claims and unsafe durable writes cost more than abstention
or staging. Exact operating metrics and thresholds remain deliberately unset
because no training or model-selection phase is authorized.

## Verified in the checked-in implementation

- Phase 0 v2 has four frozen JSON Schema 2020-12 contracts with independent RFC
  8785/SHA-256 locks. Its source and evaluation registries pass schema and
  semantic validation.
- Phase 0 v3 adds two independently locked schemas and replaces the v2
  single-document rights review with licensing/v1 evidence bundles and
  accountable assessments. The licensing layer has two locked schemas;
  Phase 1 v2 has separately locked gate and encoder-verification schemas.
- Phase 0 v4 adds eight independently locked schemas without modifying the
  frozen v2/v3 artifacts. Its direct gate binds exact predecessor registries,
  the complete Drive observation, retained publisher checksum statements,
  current rights packets, explicit evaluation roles, authenticated custody
  anchors, the complete quarantine union, source audits, inventories, and
  admissions. It does not import or filter a historical gate's blockers.
- `registries/evaluations.v4.json` preserves SocialIQA validation as
  development-only and the previously exposed EvidenceBench partition as
  diagnostic-only. Five other entries remain confirmatory candidates. Role
  history is append-only; development/validation partitions cannot be promoted,
  exposed entries cannot be confirmatory, and custody cannot move backwards.
- Private v4 envelopes require a 256-bit commitment nonce. Public commitments
  omit the nonce and private payload, and v4 schema errors report paths and
  failed keywords without rendering rejected instances. Public overlap
  selectors remain membership-revealing for guessed text and are not claimed
  to be zero-knowledge.
- The v4 matcher implements exact identifier, dependency-family, raw-hash,
  normalized-hash, and exact-Jaccard near-match checks before features. Missing
  lineage or selectors is `undetermined`; only `clear` permits features.
- Public contribution coverage is re-derived from its records, and a serialized
  clear receipt is accepted only when the matcher reproduces the complete
  decision from the bound descriptor and union index.
- V4 custody anchors bind the exact seal receipt, access-log count and head,
  monotonic sequence, validity window, and registry-pinned signing fingerprint.
  Detached GPG verification uses an isolated temporary keyring rather than the
  user's keyring.
- Storage attestations bind stable provider/root resource IDs, mounted root,
  method, verifier, and observation time. Source audits bind the exact registry
  and attestation, reject unsafe paths, hash raw bytes, detect mutation during
  reading, cover every registered artifact, and expire after 72 hours.
- The storage/v1 observation contract requires a proven read-only Drive API
  scope, unique Drive/folder identity, list/get stability, a live FUSE mount,
  and explicit same-account human attestation. It expires after 15 minutes for
  binding and makes no claim that the mounted filesystem lacks write
  capability. The probe contains no Drive mutation or file-content read path.
- When a credential does not expose `granted_scopes`, the probe uses a bounded
  Google token-info POST and retains only the returned scope set. Missing
  `drive.readonly` or any additional Drive scope fails closed; token-info email,
  subject, token, and client fields are not emitted.
- A native-first, read-only rclone fallback is locally implemented but remains
  gated on an approved protected desktop OAuth client file. It binds one ADC
  digest across API resolution, rclone, and the probe; pins and checksums the
  Linux-amd64 release archive and executable; separately pins the tag-matched
  MIT licence because the release ZIP omits it; and accepts only exact read-only
  FUSE, process, argument, environment, ADC, and Drive-ID identity.
- Licensing/v1 rehashes every captured document, binds the exact subject entry,
  distinguishes verified packet structure from human approval, requires fresh
  review of mutable terms, and mechanically excludes training and source,
  derived, and model redistribution. Empty bundles cannot be approved.
- Phase 0 v2 derives each public quarantine contribution from the same private
  evaluation envelope that is sealed. The gate requires exact registry,
  receipt, ciphertext-verification, contribution, and quarantine-union
  bindings for every declared evaluation.
- The current gate also requires one schema-valid, hash-chained access log and
  independently supplied head anchor for every declared seal. Any decrypt,
  label inspection, result report, tuning, consume, or retire event blocks
  confirmatory readiness.
- Structural inventories bind the audited artifact bytes. Admission receipts
  bind the source registry, audited rows, storage attestation, licence review,
  source inventories, and quarantine index.
- Phase 1 v1 has five frozen schemas for graph records, objective examples,
  encoder evidence, artifact manifests, and its historical data-readiness gate.
  Phase 1 v2 separately locks its current gate and exact-layout encoder
  verification schemas.
- The Phase 1 sampler is deterministic with seed `20260817`; the ready gate
  requires exactly 40,000 nodes, complete declared-community coverage, and
  complete joint-stratum coverage.
- Neighbour selection enforces the frozen source/direction/value and per-property
  caps. Every exclusion becomes a typed overflow record, and semantic validation
  enforces `input = selected + overflow`.
- Objective replay requires exactly the eight development families, one target
  among at most eight candidates, and evidence for every explicitly based
  negative. Absence of an edge is not an allowed negative basis.
- Data-producing Phase 1 commands require a ready Phase 0 v3 transformation
  report and the exact quarantine index named in that report. They refuse output
  collisions, re-hash inputs before and after processing, and write atomically.
- Phase 2A has four separately locked contracts, a role-aware source registry,
  signed typed ground-Horn worlds, bounded frontiers, agenda and proof-tree
  oracles, exact/normalized duplicate checks, quarantine matching, atomic
  no-overwrite output, deterministic regeneration, and cross-role artifact and
  dependency audits.
- The 16 training-role and 16 development-role checked-in candidates reproduce
  at their registered hashes. All eight declared case families appear twice in
  each role, the two oracles agree, and the corpus audit finds no artifact,
  exact-input, normalized-input, grammar, world, relation-composition, or
  seed-family overlap. These are fixture observations, not model results.
- Phase 2B has six separately locked additive contracts for immutable process
  state, proposals, generator specs, registry entries, write-policy examples,
  and generated artifacts. The original Phase 2A schema locks and checked
  fixtures are unchanged.
- The checked process candidates reproduce at their registered hashes: 32
  training-role and 32 development-role examples. Each role has two direct and
  two near-miss scenarios associated with every write action. Declarative and
  copy-on-write oracles agree on the action, patch, conditions, and observable
  delta for every example.
- Every process patch is applied only to a fresh state copy during replay. All
  64 inputs remain byte-identical and every non-null patch inverse restores the
  exact starting snapshot hash. The mixed corpus audit finds no cross-role
  artifact, exact-input, normalized-input, snapshot, entity, operation,
  grammar, world, relation-composition, entity-family, or seed-family overlap
  across the Phase 2A and Phase 2B manifests.
- Restricted leave-one-snapshot-out shortcut diagnostics are at or below
  0.3125 in both process roles, below the frozen 0.5 blocker. Patch-size
  accuracy is 0.4375 but is marked prediction-time-ineligible because it is
  derived from the target. These detached diagnostics are not model metrics.
- Runtime dependencies contain no ML framework. None of the three CLIs exposes
  `train`, `fit`, `optimize`, or `model`; both gates and every Phase 1/Phase 2
  artifact hard-code `training_authorized: false`.

These are implementation observations supported by code inspection and the
tests recorded in `audit/VERIFICATION.md`. They do not prove the truth of input
metadata or the cleanliness of data that has not been acquired and audited.

## Encoder evidence

The restored workspace contains the frozen encoder specification and a legacy
v1 verification record, but not the cached snapshot or bake-off report. Code
inspection of the verifier that produced the legacy record found that
`asset_set_exact` compared only the eight declared asset observations with the
specification. It separately searched for `*.py`, but did not enumerate and
reject arbitrary extra files, directories, directory symlinks, or special
entries. The record therefore supports the listed per-file hashes but does not
support its stronger exact-set conclusion.

The current verifier exact-enumerates the snapshot topology before checking the
bake-off and asset hashes. Phase 1 v2 has a separately frozen evidence schema
requiring `verification_method: exact-snapshot-layout-v2`; legacy v1 records
cannot satisfy it. No clean v2 record was created because the required snapshot
and bake-off artifact are absent. The current gate correctly reports
`encoder_identity_ready: false`, `encoder_licensing_ready: false`, and
`encoder_ready: false`. The model was not loaded, no embedding was generated,
numerical parity was not measured, upstream training-data contamination was not
assessed, and the encoder licence assessment remains pending.

## Better Colab recovery evidence

The stale execution `1344f0d2-bfd8-48bd-8617-02494ba40001` was dispatched in
the `graph-memory-data-lake` session and later became disconnected. Its source
path no longer existed, its deadline had expired, and output was incomplete.
The database indexed five contiguous chunks ending at byte 876, while the spool
contained 14,410 bytes. The complete spool, database/WAL/SHM, consistent SQLite
backup, logs, and session history were copied into a project-local ignored
recovery bundle and verified against `SHA256SUMS` before repair.

The full 14,410-byte spool remains preserved with SHA-256
`77b4eebbe4db5798eeecfca75d3522a4afc983e77225c045e8214e849a189352`.
The live spool was replaced with only the indexed 876-byte prefix, SHA-256
`92642e44c54d60f7239fda64c5e7a01792169c6ccc5a9a8842f4e7f1f47d9a90`,
so Better Colab could finalize the durable prefix and transition the execution
from `disconnected` to `unknown` with reason `forced_controller_stop`. A fresh
controller then reported zero active executions. SQLite `PRAGMA quick_check`
returned `ok`.

No execution was replayed, no remote notebook code was run, and no acquisition
or training was performed. The Colab backend subsequently reported offline, so
no Drive resource IDs or byte attestation were obtained. Any partial-download
messages in the incomplete spool are not accepted as evidence that a remote
artifact completed or is usable.

The subsequent retry separated Better Colab's two credential providers. The
default `oauth2` profile still used an expired token in its own Colab CLI cache;
refreshing Google application-default credentials did not modify that cache.
Explicit `--auth adc` commands authenticated successfully. An attempted
unassignment returned `Not Found`, establishing that the recorded endpoint was
stale remotely, so the local database was not edited by hand. A fresh CPU-only
session named `graph-memory-drive-audit-20260818` was allocated instead.

Its first nonce probes also failed with `CONNECT_FAILED:AttributeError`. An
independent direct transport attempt reproduced the exact cause: the installed
PyPI `jupyter-kernel-client` 1.0.1 lacked the `KernelClient` attribute consumed
by `colab-cli`. The Better Colab lock instead selected Git revision
`f18e982c3265df5e923aa9def101ab3fd737e139`, version 0.8.0. Reinstalling the tool
offline with that cached locked revision restored the expected API; a fresh
nonce probe then reported backend, kernel connection, and execution readiness
all true. The current CLI branch subsequently adapted its transport boundary to
and pinned released 1.0.1, with clean-wheel tests. This was an environment
dependency repair, not a model or project-code change.

Three guarded, read-only diagnostic executions finished with complete reply and
idle evidence. They called no Drive API, listed no mounted content, and performed
no training. The runtime exposes `drive.mount(..., readonly=False)` with an
available `readonly` argument and has `gcloud` support for `--scopes` and
`--no-launch-browser`. The fresh runtime currently has no `/content/drive`
mount, no expected lake root, no same-account attestation, and no provable
granted Drive scope. The real identity probe has therefore not been dispatched.
A separate read-only Google Drive connector check had returned no shared drive
named `Data`; it remains rejected as an identity source rather than being
treated as the intended account by assumption.

The earlier Drive authorization attempt emitted a validated consent URL but the
then-current CLI polled its dry run until the command deadline. Comparison with
the official client established that the browser close-window page sends no
completion notification to the CLI: the intended protocol is one dry run,
explicit human Continue, then a fresh-token final propagation. The timeout is
therefore evidence of a CLI protocol deadlock, not an upstream Drive failure.
Whether the earlier HTTP 400 was caused by XSRF-token reuse, the obsolete
multipart body, or another factor remains unresolved.

A corrected-flow retry allocated one disposable CPU runtime and completed a
guarded nonce execution. Its dry run emitted one validated consent URL, but
human approval arrived after the 600-second command deadline; the coordinator
had already cancelled before Continue, so no final propagation request was
made. The retry then stopped locally because host ADC had expired and required
separate reauthentication. The exact runtime endpoint subsequently returned
HTTP 404. Its stale local keep-alive and session record were removed, but an
account-wide session listing could not be repeated with expired ADC. This is
not evidence of a successful mount or of an upstream Colab failure.

After ADC reauthentication, a second disposable CPU runtime passed its guarded
readiness probe and live-accepted the repaired sequence. Persisted allowlisted
metadata shows dry-run GET/POST followed, after one explicit human Continue, by
a fresh-token final GET and bodyless POST. Both POSTs returned HTTP 200; the dry
run returned `success: false` with a consent redirect and final propagation
returned `success: true`. History contains exactly one `drive_auth_success` and
no consent URL, Authorization header, or XSRF-header material. The generated
`drive.mount('/content/drive', readonly=True)` command completed. An exact-hash
metadata-only execution found one `fuse.drive` mount with `ro` and the fixed
expected lake-root directory; it read no Drive file contents, performed no
Drive write, and returned `training_authorized: false`. The runtime was released
and the account-wide session list was empty. This verifies native mounting, not
the separate exact-scope identity observation, and no resource ID was bound.

## Evidence still missing or weak

- `registries/sources.v4.pending.json` still has null shared-Drive and
  root-folder IDs and deliberately null publisher-statement URLs.
  No authenticated observation, bound registry, storage attestation, or fresh
  source audit exists. Native authorization and the read-only mount now pass,
  but the remaining external step is to create provable exact
  `drive.readonly` user ADC inside the same runtime with an approved protected
  desktop OAuth client, explicitly attest that it is the mounted account, and
  run and bind the identity observation within 15 minutes. The fallback is
  unavailable until that client file is supplied locally. The connected Drive
  integration cannot substitute because it has no accessible `Data` drive.
- The Wikidata checksum entry marked `verified` reflects a prior primary-source
  observation, but the workspace does not retain its publisher statement or a
  v4 receipt. No official statement URL was guessed during implementation. The
  overall publisher-evidence gate is therefore blocked.
- Forty-three allowlisted legal/provenance responses are captured and rehashed
  into 10 subject-bound bundles with no missing catalogued document. All 10
  assessments remain pending; these captures are evidence for review, not legal
  approvals. Evaluation entry hashes changed in v4, so new exact bundles and
  assessments must be assembled before the v4 gate can verify them. The two
  private first-party confirmatory evaluations have empty historical bundles
  and cannot be approved.
- Every confirmatory evaluation remains declared rather than sealed. Archive
  hashes and adapters are missing; private confirmatory generators and custody
  are not implemented; dependency closure is incomplete; no access logs or
  independent head anchors exist; and no complete Phase 0 quarantine union
  exists. The public Phase 2A and Phase 2B fixtures do not satisfy those
  requirements.
- The registered source bytes have not passed a v4 audit. Wikidata has not
  been acquired under the v4 gate. No structural inventory or admission receipt
  exists.
- The Phase 1 CLI does not transform raw Wikipedia/Wikidata dumps into its graph
  records and does not generate objective labels. Phase 0 v4 compiles and
  matches its fingerprint selectors, but no raw-source-to-graph consumer yet
  requires and preserves a v4 `quarantine_decision: clear` receipt.
  Phase 1 manifests bind hashes and semantics, but are detached unsigned JSON;
  the gate does not independently reopen the output files named by those hashes.
- No model-based label-only, metadata-only, degree-only, lexical-marker,
  permutation, counterfactual, source-held-out, or generator-held-out baseline
  has been run because no model or complete development corpus exists. Phase 2A
  and Phase 2B record only small detached shortcut diagnostics; they are not
  predictive-performance measurements.

## Current gate interpretation

`audit/phase0-gate.v4.initial.json` is the current direct report and is
correctly blocked. Contract and registry-role checks pass. Storage identity,
publisher evidence, current rights evidence, confirmatory custody, quarantine,
source bytes, inventories, and admissions are not ready. Acquisition,
transformation, and training are unauthorized. The older v3 licensing report
remains historical evidence that the prior packet structure rehashed and every
then-current decision was pending; it is not a v4 prerequisite or approval.

`audit/phase1-gate.v2.licensing.json` is also correctly blocked. Contract checks
pass, but fresh encoder identity evidence, encoder licensing, the Phase 0
transformation prerequisite, and all three data manifests are not ready.
`phase1_data_ready` and `training_authorized` are both false.

## Leakage and reward-hacking assessment

The leading leakage risks are page/revision/redirect/sitelink overlap;
entity-neighbourhood and incident-statement overlap; DOI/PMID/PMCID work
overlap; contract/story/document/time overlap; generator grammar/world/seed
overlap; exact and near duplicates; pretrained-encoder contamination; and human
adaptation after seeing confirmatory results. The v4 envelope and contribution
design can represent those dependency families, but no cleanliness claim is
warranted until all seven role-specific envelopes are derived from pinned
bytes, the five confirmatory candidates are sealed and authenticated, and the
complete union is recomputed.

Within the local Phase 2 fixtures, exact and normalized input hashes and every
allocated dependency family are disjoint across roles. Phase 2B also checks
snapshot and entity identities, and the mixed audit covers both procedural
families. The bound v2 quarantine index is a local reservation fixture compiled
from checked-in envelopes, public contributions, and byte-bound
selector/adapter fixtures. It is not evidence that the examples are clear of
every future confirmatory dependency. An early Phase 2A draft
placed case names in template and provenance metadata, and its template-only
diagnostic reached 1.0. Those
label-bearing fields were removed, case placement was seed-permuted, and the
checked-in template-only diagnostic is 0.375. This correction happened before
commit or model use.

The Phase 2B oracles use separate transition implementations, but they share
the frozen policy contract and process-state validator. Their agreement is
therefore evidence against some implementation faults, not independent proof
that the policy is correct. Adversarial cross-product checks found that an
early rule order let duplicate/conflict structure precede evidence, identity,
and risk gates; separate temporal checks also found lifecycle changes whose
new evidence time was not reflected in the changed record. Both oracle paths
were corrected, update/deprecation now close valid intervals and bind the new
evidence time, and regressions cover the combined conditions. Correlated errors
from a shared specification or author remain possible.

There is no optimization result to audit and no metric improvement to report.
The Phase 1 algorithms do not consult confirmatory scores. An unusually strong
future result must still be challenged with duplicate/lineage checks, clean
reruns, shortcut baselines, ablations, repeated seeds or splits, and an
independent sealed evaluation.

## Held-out exposure incident

During an earlier diagnostic, a delegated process opened the public
EvidenceBench test JSON while investigating licensing. That was outside the
clean legal/provenance-only boundary. No observation from the file is used in
the catalogue, implementation, gates, or this report, but non-use does not
restore evaluation independence. The evaluation registry and licence packet now
carry blocking exposure records. This partition must be replaced or handled by
genuinely independent custody before it can support a clean confirmatory claim.
The catalogue validator mechanically rejects the known held-out path and other
label-bearing evaluation URLs.

## Prior-lesson review

A prior integrity lesson about canonical JSON's safe numeric domain was applied
mechanically: filesystem device, inode, and nanosecond timestamp evidence is
stored as decimal strings rather than unsafe JSON integers. The same pattern
recurred during the final audit in 64-bit MinHash sketches. Those sketches now
retain deterministic high 53-bit values, all relevant schemas cap them at
`9007199254740991`, and a real-fingerprint canonicalization test prevents the
fixture-only blind spot. The lesson is generalized in the global ML lessons
file. The held-out exposure established a second reusable lesson: item-level
rights inspection must remain behind the holdout boundary, with legal review
based on repository, publisher, and aggregate provenance evidence. That lesson
is also recorded in the global file. Phase 2A established another reusable
near miss: human-readable generator case metadata can become a direct label
channel even when the intended world semantics are sound. The global lesson now
requires metadata/template-only diagnostics and removal or explicit exclusion
of target-bearing generator fields. A final fixture-provenance near miss also
established that every accepted evidence digest, including synthetic fixtures,
must resolve to mechanically rehashable content rather than a schema-valid
placeholder. That rule is recorded globally and enforced by a new derivation
test. Phase 2B added two reusable checks: test admissibility gates in
cross-product with apparently decisive structural signals, and distinguish
snapshot, proposal, evidence, and lifecycle timestamps before asserting future
leakage or temporal validity. Both are recorded globally and enforced by
regressions here. No training or evaluation was performed.

## Phase 0 v4.1 execution-hardening audit (2026-08-25)

This section supersedes the earlier operational statements in this file that
name `gate-v4` or `audit/phase0-gate.v4.initial.json` as the current
authorization boundary. Those artifacts remain historical. The active boundary
is `gate-v4.1`, and the current checked report is
`audit/phase0-gate.v4.1.blocked.json`.

Three material v4 flaws were reproduced from code and adversarial fixtures:

1. V4 validated only the caller-supplied predecessor-to-successor transition.
   It did not compare the first registry in that pair with a checked-in trusted
   root, so a self-consistent alternate lineage could be supplied. V4.1 fixes
   the source root at
   `sha256:c724de9fea9e13d365503f8cdaeaa25016fc906cebf6bb05b6884a2dae69e3ec`
   and the evaluation root at
   `sha256:6c52a922377d7ae017ae24ecca0f2dc7d239b562a954ac310b6325fe21cd97cb`,
   then recomputes every ordered transition with unique IDs/hashes and strictly
   increasing timestamps.
2. V4 could validate an evaluation envelope and its derived public
   contribution without independently reopening the registered archive,
   adapter, or oracle and without proving that every archive member, primary
   unit, output record, and dependency was accounted for. V4.1 materialization
   rehashes those artifacts and rejects unsafe paths, links, devices,
   encryption, duplicate or unaccounted members, missing primary-unit coverage,
   orphan outputs, unresolved dependencies, adapter/oracle aliasing, and public
   receipt fields that could disclose private evaluation structure or payload.
3. V4 operationally bound rights and seal evidence to the registry entry that
   was also expected to assert sealed custody and cleared blockers. That left no
   mechanically enforced acyclic order for pinning, review, materialization,
   sealing, anchoring, and final registry publication. V4.1 binds evaluation
   rights, materialization, seals, initial access events, and anchors to the
   penultimate fully pinned registry. It then reproduces exactly one successor,
   moving only confirmatory entries to `sealed`, leaving non-confirmatory
   entries pinned, and clearing only blocker families backed by supplied
   evidence.

The leading explanations were challenged with mutations rather than only happy
paths. Tests reject alternate roots, missing/skipped/reordered transitions,
timestamp rollback, changes to pinned assets, keys, seal IDs, or dependency
units, unsafe/duplicate/unaccounted archives, incomplete or orphaned output
coverage, mutated archives/adapters/oracles, public-field leakage, late rights
review, stale anchors, consumed confirmatory logs, premature finalization, and
unsupported blocker removal. A synthetic complete graph rooted in the real
checked registries reaches foundation transformation readiness while retaining
`training_authorized: false`; removing either trusted root or materialization
evidence blocks it. This is a control-path fixture, not evidence that any real
dataset, licence, custody process, or source byte is ready.

The source publisher successor preserves every source entry and existing
`verified` flag while pinning the exact Wikidata 20260720 manifest URL and the
enwiki 20260801 manifest URL for all six enwiki artifacts. Fresh research
copies fetched over HTTPS had SHA-256
`1d46f0ada283801de16a7a865207926f30ee940adf6328ff60da645636cc2c43`
(449-byte Wikidata statement) and
`96f53060f2cbb20329222be57bada28679855038900b0ac382a12edc6bdcd838`
(243,860-byte enwiki statement). All seven registered SHA-1 rows matched. No
detached publisher signature was verified, so
`audit/publisher-manifest-research.v4.1.json` marks these observations as
research-only and non-authorizing. Final statements and receipts must be
fetched after Drive binding and remain inside the 72-hour evidence window.

The mechanically reproduced real-state v4.1 report has trusted source and
evaluation roots plus the publisher successor, but remains blocked on exact
OAuth/Drive identity, fresh publisher receipts, a fully pinned evaluation
successor, accountable rights approvals, materialization, confirmatory seals
and signed anchors, the complete quarantine union, source audit and bytes,
structural inventories, and admissions. Acquisition, transformation, and
training are false. No held-out evaluation record, answer, label, evaluator
internal, large source byte, or private custodian key was accessed during this
work. No Drive mutation, human approval, sealing, source acquisition,
transformation, embedding, model run, threshold selection, or training was
performed.

The materialization oracle check establishes a distinct ID and digest from the
adapter; it does not establish independent authorship or methodological
correctness. Human custody review and separate implementation provenance remain
necessary. Likewise, a passing synthetic graph and full unit suite can disprove
specific implementation failures but cannot establish the truth of external
rights, storage, publisher, or custody claims.

## Better Colab exact-scope OAuth prerequisite (2026-08-25)

The installed Better Colab build and its upstream checkout were compared before
attributing the failed identity probe to an obsolete local CLI. Both identified
the same current development revision (`0.1.dev97+g0491cc985`, commit
`0491cc985ccc53251d1f290e2347c4ad673356cc`). This rules out the proposed
"old installed version" explanation for the reproduced behavior, but does not
establish that later upstream revisions will retain it.

Code-path inspection and a live disposable-runtime experiment independently
identified a kernel-affinity defect. Normal execution supplies stored kernel
and Jupyter session IDs and callbacks that persist newly discovered IDs.
Compatibility automation constructed its runtime without either IDs or those
callbacks. In the experiment, classic `colab auth` created refreshable user ADC
in shared runtime storage, while the later guarded command ran in another
kernel and selected compute metadata instead. Explicitly selecting the ADC path
inside the tracked kernel made credential refresh succeed. This establishes a
Better Colab automation/reconnect bug; it does not establish an upstream Colab
OAuth defect.

The successful credential was then rejected for Phase 0 on an independent
ground: its granted Drive permissions were broader than the gate's sole allowed
Drive scope, `https://www.googleapis.com/auth/drive.readonly`. Classic Colab
auth has no exact Drive-scope selector, and Better Colab's host control-plane
credential is a different authority that must not be copied into workload
storage. Therefore repairing kernel reuse is necessary but insufficient.

Implementation is split at that boundary. Release A will only make automation
reuse and persist the durable kernel/session identity, with failure-path and
live integration coverage. Release B will add an explicit exact-read-only Drive
provider to the core and compatibility CLIs. Development configuration can
exercise the protocol, but no production credential, Phase 0 binding, or
authorization may be claimed until the public OAuth application has completed
Google verification and any applicable security assessment. No token, consent
code, verifier, client secret, Drive object ID, or held-out content was recorded
in this audit.

Once both releases and the external provider approval exist, the next bounded
execution is a fresh disposable CPU assignment: authorize the dedicated Google
Reader identity, prove same-account ADC and read-only mount state in one durable
kernel, run the fixed-hash metadata-only probe, bind within 15 minutes, then
capture fresh publisher statements and seven receipts within 72 hours. Rights
review, evaluation materialization, sealing/anchoring, registry finalization,
quarantine, source audit, acquisition, inventory, admission, and the final gate
remain ordered after that checkpoint. Large acquisition still requires
separate explicit authority, and `training_authorized` remains false.

## Better Colab releases staged to external authority (2026-08-28)

The preceding future-tense implementation paragraph is now superseded. Release
A was committed as `3ebcf0b` (kernel/session affinity) and `1be475a`
(design record). Release B was committed as `6bb93e0` (exact Drive read-only
provider) and `0a6aadc` (boundary documentation and integration harness). The
exact core and compatibility wheels both identify as
`0.1.dev101+g0a6aadc17`; they were installed together in a fresh Python 3.12
environment, their package metadata matched, and the same wheels replaced the
previously installed global `better-colab` and `colab` tools. Both global entry
points now report that version. The user-owned unrelated untracked directories
in the Better Colab checkout were not staged or modified.

Release B separates four authorities that must not be conflated: Colab
control-plane authentication, classic VM authentication, DriveFS propagation,
and exact-scope workload ADC. Its authorization URL uses state-bound PKCE and
requests only `https://www.googleapis.com/auth/drive.readonly`. The
authorization-code and refresh-token exchanges occur inside the exclusively
leased assigned kernel. Both token responses must explicitly report `Bearer`
and exactly that one granted
scope; missing or combined grants fail before a credential is written. The
runtime stores only authorized-user refresh material in owner-only volatile
storage, binds the environment in that kernel, clears transient token-bearing
namespace references, and emits only typed non-secret status. Revocation
deletes locally only after HTTP 200; explicit clear never claims revocation.

Adversarial tests reproduced and then closed several independent fail-open
paths: expected metadata previously masked a different observed fingerprint
and provider mode; a remote result without an explicit success marker was
accepted; absent token-response scope evidence was treated as exact; runtime
constructor details could escape sanitization; replacement kernel IDs could be
paired transiently with stale Jupyter session IDs; a session removed during
probe escaped as an assertion; and token dictionaries remained reachable in
the notebook namespace after otherwise redacted operations. Tests now reject
fingerprint/mode mismatches, absent or broader grants, unsafe client files,
duplicate stdin handoffs, remote canaries, unready or raced sessions, mixed
identity pairs, unproven revocation, and secret namespace retention.

The final Better Colab verification comprised 541 passing tests plus 5 passing
subtests, repository-wide Ruff, source/test compilation with redirected
bytecode, core and compatibility sdist/wheel builds, matching clean-wheel
installation, CLI/version/capability smoke tests, and the no-allocation
integration harness. The harness and the globally installed provider both
returned exit 3 with `PRODUCTION_OAUTH_UNAVAILABLE` before session lookup or
controller start. No verified production client resource or fingerprint is
present. A caller-provided client is mechanically labelled development and
cannot set `production_authorized`.

Google's current [Drive scope table](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
classifies `drive.readonly` as restricted, and its
[verification requirements](https://support.google.com/cloud/answer/13464321?hl=en)
require an annual security assessment for restricted scopes. Therefore
ordinary user authentication is not the next step. An accountable external
owner must establish the dedicated public OAuth application, complete
restricted-scope verification and assessment, and deliver the exact approved
desktop-client bytes. A later reviewed activation commit must package those
bytes and pin their SHA-256; the provider already fails closed on missing or
mismatched bundle bytes. Only then may a human approve a fresh production
consent in one disposable CPU runtime.

No production or development Drive consent, token exchange, Drive access,
Drive mutation, runtime allocation, publisher fetch, held-out evaluation
access, rights decision, materialization, sealing, acquisition,
transformation, training, or evaluation was performed during these releases.
The existing checked Phase 0 v4.1 report remains blocked. The next in-project
execution after external activation remains the same-account ADC/read-only
mount identity proof and 15-minute binding, followed by fresh publisher
receipts inside 72 hours. `training_authorized` remains false.
