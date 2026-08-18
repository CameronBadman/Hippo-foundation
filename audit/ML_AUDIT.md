# Machine-learning integrity audit — Phases 0, 1, and 2A

Updated: 2026-08-18

## Decision boundary

The current operational decisions are only:

1. whether registered source acquisition or transformation may begin under the
   Phase 0 v3 evidence controls; and
2. whether deterministic Phase 1 v2 development-data artifacts satisfy their
   frozen contracts; and
3. whether the local Phase 2A procedural candidates reproduce exactly, agree
   across two oracles, and remain isolated across training/development roles.

None of these decisions permits model training. There is no measured predictive
performance and no basis for a claim about model quality, safety, calibration,
or usefulness.

This restoration review reran the local contracts, tests, gates, and package
build. The Better Colab and live Drive observations below are preserved
historical evidence from the restored audit record; they were not repeated in
this review and are not treated as new verification.

The future evaluation decision is declared in
`registries/evaluations.v2.json`: assess frozen evidence-grounded graph-memory
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

- `registries/sources.v2.json` still has null shared-Drive and root-folder IDs.
  No authenticated observation, bound registry, storage attestation, or fresh
  source audit exists. Native authorization and the read-only mount now pass,
  but the remaining external step is to create provable exact
  `drive.readonly` user ADC inside the same runtime with an approved protected
  desktop OAuth client, explicitly attest that it is the mounted account, and
  run and bind the identity observation within 15 minutes. The fallback is
  unavailable until that client file is supplied locally. The connected Drive
  integration cannot substitute because it has no accessible `Data` drive.
- The Wikidata checksum entry marked `verified` reflects a prior primary-source
  observation, but the v2 workspace does not yet contain the publisher checksum
  artifact or a verification receipt. All English Wikipedia checksum flags are
  false. The overall publisher-pin gate is therefore blocked.
- Forty-three allowlisted legal/provenance responses are captured and rehashed
  into 10 subject-bound bundles with no missing catalogued document. All 10
  assessments remain pending; these captures are evidence for review, not legal
  approvals. The two private first-party confirmatory evaluations have empty
  bundles and cannot be approved.
- Every confirmatory evaluation remains declared rather than sealed. Archive
  hashes and adapters are missing; private confirmatory generators and custody
  are not implemented; dependency closure is incomplete; no access logs or
  independent head anchors exist; and no complete Phase 0 quarantine union
  exists. The public Phase 2A fixture does not satisfy those requirements.
- The registered source bytes have not passed the v2 audit. Wikidata has not
  been acquired under the v2 gate. No structural inventory or admission receipt
  exists.
- The Phase 1 CLI does not transform raw Wikipedia/Wikidata dumps into its graph
  records and does not generate objective labels. Phase 0 v2 compiles
  fingerprint selectors but has no v2 record-matching command, so real
  `quarantine_decision: clear` records cannot yet be mechanically established.
  Phase 1 manifests bind hashes and semantics, but are detached unsigned JSON;
  the gate does not independently reopen the output files named by those hashes.
- No model-based label-only, metadata-only, degree-only, lexical-marker,
  permutation, counterfactual, source-held-out, or generator-held-out baseline
  has been run because no model or complete development corpus exists. Phase 2A
  records only small detached majority, grammar, template, and path-length
  diagnostics; they are not predictive-performance measurements.

## Current gate interpretation

`audit/phase0-gate.v3.licensing.json` is correctly blocked.
`contracts_frozen` and `licensing_evidence_verified` are true, meaning the exact
packet set and bindings verify; `licensing_ready` is false because all human
decisions are pending. Storage, source bytes, confirmatory seals, quarantine,
inventories, and admissions are also not ready. Acquisition, transformation,
and training are unauthorized.

`audit/phase1-gate.v2.licensing.json` is also correctly blocked. Contract checks
pass, but fresh encoder identity evidence, encoder licensing, the Phase 0
transformation prerequisite, and all three data manifests are not ready.
`phase1_data_ready` and `training_authorized` are both false.

## Leakage and reward-hacking assessment

The leading leakage risks are page/revision/redirect/sitelink overlap;
entity-neighbourhood and incident-statement overlap; DOI/PMID/PMCID work
overlap; contract/story/document/time overlap; generator grammar/world/seed
overlap; exact and near duplicates; pretrained-encoder contamination; and human
adaptation after seeing confirmatory results. The v2 envelope and contribution
design can represent those dependency families, but no cleanliness claim is
warranted until all seven envelopes are derived from pinned bytes, sealed, and
recomputed into the public union.

Within the local Phase 2A fixture, exact and normalized input hashes and all
four allocated dependency families are disjoint across roles. The bound
quarantine index is explicitly named `phase2-public-reservations-v1`; it is a
local reservation fixture derived from a checked-in envelope, public
contribution, and byte-bound selector/adapter fixtures. It is not evidence that
the examples are clear of every future confirmatory dependency. An early draft
placed case names in template and provenance metadata, and its template-only
diagnostic reached 1.0. Those
label-bearing fields were removed, case placement was seed-permuted, and the
checked-in template-only diagnostic is 0.375. This correction happened before
commit or model use.

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
test. No training or evaluation was performed.
