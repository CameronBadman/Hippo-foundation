# Phase 0 v4, Phase 1 v2, Phase 2A, and Phase 2B verification record

Verification date: 2026-08-25

## Current checks and restoration context

- Current 2026-08-25 run: `.venv/bin/pytest -q` passed all 171 tests in
  329.00 seconds. This includes the complete pre-existing regression suite,
  v4 role and lineage invariants, external-evidence binding, adversarial
  contribution/receipt tampering, private-error redaction, tri-state
  pre-feature quarantine, a synthetic blocker-free path, and a real isolated
  GPG detached-signature verification.
- Current static and interface checks: `git diff --check`, Python bytecode
  compilation, `uv lock --check`, and all three installed CLI help surfaces
  passed. The v4 CLI validated both predecessor-bound registries and
  `audit/phase0-gate.v4.initial.json` against all eight locked schemas.
- Current packaging check: `uv build --out-dir /tmp/hf-phase0-v4-dist` produced
  an sdist and wheel. Direct wheel inspection found the v4 implementation and
  all eight v4 schemas; loading the extracted wheel from outside the repository
  located its packaged schema directory and reproduced all eight locks.
- Preserved 2026-08-18 restoration record: missing `src/`, `tests/`, and
  `scripts/` content was restored without
  overwriting existing paths from the local source distribution with SHA-256
  `6aa097cfb7d03fc9a87901eb69afb63fc0a876984dc0d78944eac119766a24b6`.
  That restoration operation was not repeated in the Phase 2B verification.
- Preserved 2026-08-24 Phase 2B result: 159 tests passed in 317.56 seconds. Its
  checks covered the older Phase 0/1 gates and both Phase 2 slices, including
  deterministic regeneration, temporal/provenance ordering, oracle agreement,
  rollback, overlap surfaces, CLI round trips, output collision rejection, and
  the absence of a training surface.
- The v3 and earlier checked fail-closed reports were not regenerated during
  this v4 work. Their historical status is retained separately from the newly
  reproduced direct v4 report.
- Phase 1 v2 reproduced the locked digests for its gate and new exact-layout
  encoder-verification schema. The latter is
  `sha256:e7fbdb108a9cd2750422668c4f35a0fee4a310afaf9d289065028ee3fd3e402d`.
- Preserved 2026-08-24 packaging result: a source distribution and wheel were
  built into a temporary directory.
  Wheel inspection found all three console scripts and all schemas, including
  Phase 1 v2 and both Phase 2 contract versions. A clean temporary environment
  installed the wheel plus its declared dependencies, loaded the package from
  site-packages, reproduced the Phase 2 v1 and v2 schema locks, and validated
  both checked-in process roles, their ledgers, and both clean corpus audits.
- Preserved 2026-08-24 lint result: Ruff check and format checks passed for the
  Phase 2 package and its changed contract/surface tests. No whole-repository
  Ruff claim is made. The declared
  runtime dependencies remain only `jsonschema` and `rfc8785`; neither is an ML
  framework.

## Phase 0 v4 external-evidence firewall

- Eight additive JSON Schema 2020-12 contracts reproduce their independent RFC
  8785/SHA-256 locks. Frozen v2/v3 schemas and registries were not edited.
- The pending source registry validates against the exact v2 predecessor and
  preserves every source entry byte-for-byte. Its stable Drive IDs and seven
  publisher-statement URLs remain null, so it cannot produce ready external
  evidence.
- The v4 evaluation registry validates against the exact v2 predecessor.
  SocialIQA validation is development-only, the exposed EvidenceBench partition
  is diagnostic-only, and exactly five entries remain confirmatory candidates.
  All five candidates remain declared and blocked rather than being represented
  as sealed.
- The focused v4/no-training suite passed 13 tests. It covers role laundering,
  predecessor rewriting, full observation binding, exact and stale publisher
  statements, dependency closure, nonce-hardened commitments, private error
  redaction, safe integers, tri-state matching, a complete synthetic ready path,
  removal of each evidence family, an isolated real GPG detached-signature
  round trip when the local GPG agent is available, and the absence of caller
  acquisition overrides.
- The synthetic path reaches both acquisition and transformation readiness with
  no blockers while retaining `training_authorized: false`. Its source bytes,
  rights attestation, custodian, key, and approvals are explicitly synthetic
  test fixtures and support no claim about a real source or evaluation.
- `audit/phase0-gate.v4.initial.json` was regenerated through the direct v4 CLI
  and validates against the v4 gate schema. Contract, source-registry, and
  evaluation-role checks pass. Storage, publisher evidence, current rights
  evidence, confirmatory custody, quarantine, byte audit, inventories, and
  admissions remain blocked. Acquisition, transformation, and training are
  false.
- No live Drive call, publisher capture, human approval, confirmatory-item read,
  source download, graph transformation, embedding, model run, threshold
  selection, or training occurred in this implementation pass.

## Phase 2A procedural slice

- Four Phase 2 v1 schemas validate and reproduce their independent RFC
  8785/SHA-256 lock anchors.
- The checked-in training-role JSONL is 38,254 bytes with SHA-256
  `fba8244ede343e9dd52ac1f769f6f107607a4aae67c51a9867d9615767241d0c`.
  The development-role JSONL is 38,638 bytes with SHA-256
  `91729b18f7717fc15f6bd700f4b0585fb83049e0f5a924c588976affa7e506a4`.
- Each role contains 16 examples and all eight declared case families twice.
  Agenda closure and bounded proof-tree enumeration agree on reachability,
  frontier utility, payload, and action for every example.
- Corpus audit `corpus-audit:1ff9047ac43a43190624675371f19647b40b2a286a4972fddc77378bdb152eba`
  reports no cross-role artifact, exact-input, normalized-input, grammar,
  world, relation-composition, or seed-family overlap.
- The fixture is clear only against the exactly bound local index
  `phase2-public-reservations-v1`; it is not evidence of cleanliness against the
  missing complete Phase 0 quarantine union. Both source rights reviews remain
  pending, the repository has no selected project licence, and every record
  keeps `training_authorized: false`.
- Detached leave-one-world-out diagnostics are majority 0.375, grammar 0.0,
  template 0.375, and path length 0.5. They are shortcut checks on 16 examples
  per role, not model-performance results.

## Phase 2B staged-write process slice

- Six additive Phase 2 v2 schemas validate and reproduce their independent RFC
  8785/SHA-256 lock anchors. The Phase 2A v1 schema digests and fixtures remain
  unchanged.
- The checked training-role JSONL is 229,439 bytes with SHA-256
  `9124fa3cb284c48af9d20887e615c06fa6986998928920567180b4b847e0326e`.
  The development-role JSONL is 230,495 bytes with SHA-256
  `9314281a37f68f10a2b1652e0ff4db2c5732682cc46458381fdff66042164ebc`.
- Each role has 32 examples: two direct and two near-miss scenarios associated
  with every one of the eight write actions. Realized counts are 5 attach, 3
  update, 2 deprecate, 2 new-node, 3 duplicate, 3 conflict, 7 stage, and 7
  ignore examples per role.
- Declarative precondition/effect and copy-on-write transition oracles agree on
  action, target, patch conditions, and observable delta for all 64 examples.
  Replays preserve every input and restore the exact starting snapshot after
  every non-null patch inverse.
- Process corpus audit
  `corpus-audit-v2:bdd646f1f3570f5c98e472fb79bdfaaa2eefc5a387d4d08828683dff4fe7fd77`
  finds no cross-role overlap. Mixed four-corpus audit
  `corpus-audit-v2:e41f6a59e560464b1d639b67597d4b1140e4c050c6a921ec7482f5b29727e6b5`
  also finds none across artifact, exact/normalized input, snapshot, entity,
  operation, grammar, world, relation-composition, entity-family, and
  seed-family surfaces.
- Every eligible shortcut diagnostic is at or below 0.3125, below the frozen
  0.5 blocker. Patch-size accuracy is 0.4375 but explicitly prediction-time
  ineligible. These are fixture diagnostics, not predictive metrics.
- The reservation index is re-derived from both checked public contributions;
  its process source and adapter bytes are independently rehashed and their
  exact copied selectors are checked. This remains a local fixture, not the
  complete Phase 0 union.
- Both source entries remain declared with pending rights review. No trainer,
  canonical-write command, model, performance result, private confirmation
  data, or training authorization was created.

## Restored Drive authorization and fallback record

The following external observations were restored from the prior audit record
and were not independently rerun during this repository review.

- The Better Colab source-tree suite passed 498 tests after the authorization
  change. Its tests assert GET/POST/GET/POST ordering, fresh dry-run and final
  XSRF tokens, bodyless POSTs, one explicit Continue, already-authorized
  behavior, final-response authority, cancellation, no-TTY/EOF/deadline paths,
  exact integer-or-string correlation IDs, one reply per accepted request,
  concise traceback-free CLI failures, and absence of seeded secrets from
  errors and history.
- The CLI's Ruff, lock, plugin-package, source/wheel builds, and isolated
  core-plus-compatibility wheel smoke checks passed. The smoke environment
  exercised the released `jupyter-kernel-client==1.0.1` boundary and exposed
  the new `drivemount --read-only` option.
- A clean official rclone 1.75.0 Linux-amd64 ZIP was independently downloaded.
  It was 31,456,234 bytes, passed ZIP validation, matched archive SHA-256
  `aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa`,
  and its executable matched SHA-256
  `f3f9aff817f9766029e50adf9a7963c169e475b8f10c7927823568a0d9443db7`.
  The release ZIP does not contain `COPYING`; the tag-matched upstream licence
  was therefore separately downloaded and pinned at SHA-256
  `8cd2e9e750b90a04b7d82dbbca3930c696ae0309d7c10464f90a44f45754cd04`.
  The real artifacts passed the fallback install path with modes `0500` and
  `0400` and removal of the downloaded ZIP.
- Mocked Drive/API/FUSE tests cover exact scope rejection, zero or multiple
  shared-drive matches, unsafe paths, foreign mounts, reused PIDs, failed-start
  cleanup, exact mount arguments, minimal environment, and ADC/state/Drive-ID
  binding. A local synthetic FUSE mount with the installed rclone 1.73.2
  independently confirmed the nested-combine topology and read-only mount
  metadata; this is not a live Google Drive or pinned-1.75.0 network test.
- The first corrected-flow live attempt allocated one disposable CPU runtime
  and passed a guarded nonce execution, but human approval arrived after its
  600-second command deadline. It made no final propagation request; expired
  host ADC then blocked a retry. The exact endpoint later returned HTTP 404 and
  its stale local state was removed. After ADC reauthentication, the orphaned
  account assignment was explicitly released and the account-wide list was
  empty before the next test.
- A fresh disposable CPU runtime then live-accepted the corrected flow. The
  allowlisted history sequence was dry-run GET/POST, one human Continue,
  fresh-token final GET, and bodyless final POST. Both POSTs returned HTTP 200;
  final propagation returned `success: true`, and history contains exactly one
  `drive_auth_success`. A scan found no persisted consent URL, Authorization
  header, or XSRF-header material. The read-only mount command completed. An
  exact-hash metadata-only probe observed one `fuse.drive` mount with `ro`, the
  fixed expected lake-root directory, no Drive-content read, no Drive write,
  and `training_authorized: false`. The CPU runtime was released and a final
  account-wide session query returned an empty list.
- This verifies native authorization and mounting, not the separate exact-scope
  Drive identity observation. No stable resource ID was captured or bound. The
  fallback was not executed against Google because no approved desktop OAuth
  client file was supplied.

## Reproduced fail-closed reports

- `audit/phase0-gate.v4.initial.json` validates as the direct Phase 0 v4 gate
  and is blocked. Its contract and role-classification flags are true; every
  external evidence family is absent or incomplete, and both action flags are
  false.
- `audit/phase0-gate.v3.licensing.json` validates as a Phase 0 v3 gate and is
  blocked. `contracts_frozen` and `licensing_evidence_verified` are true;
  `licensing_ready` is false because all decisions remain pending. Storage,
  source bytes, confirmatory seals, quarantine, structural inventory,
  admission, acquisition, and transformation are not ready.
- `audit/phase1-gate.v2.licensing.json` validates as a Phase 1 v2 gate and is
  blocked. `encoder_identity_ready`, `encoder_licensing_ready`,
  `encoder_ready`, the Phase 0 prerequisite, and all three data manifests are
  false or absent.
- Both reports contain `training_authorized: false`.
- `audit/phase0-gate.initial.json`, `audit/phase0-gate.v2.initial.json`, and
  `audit/phase1-gate.initial.json` remain historical artifacts. They are not
  evidence for the current gates.

## Licence evidence

- The catalogue covers exactly two foundation sources, seven evaluations, and
  one encoder. It contains 43 HTTPS legal/provenance references and no
  evaluation archive or known held-out item path.
- All 43 snapshots and receipts were captured. Packet preparation independently
  rehashed them and produced 10 bound bundles plus pending assessment scaffolds;
  `audit/licensing-evidence.v1.json` discloses only coarse counts, hashes, and
  finding categories.
- A GitHub Contents response for `LICENSEDATA.TXT` transformed five invalid
  UTF-8 punctuation bytes. The exact 1,786-byte Git blob was separately
  captured and its Git object SHA-1 was independently reproduced. The
  discrepancy is retained as a finding rather than hidden.
- No human licence decision was made. The two unimplemented first-party
  evaluations have zero-document bundles and cannot pass approval.

## Encoder verification

- `audit/encoder-verification.v1.json` records matching observations for eight
  declared files and the declared bake-off hash. The current workspace does not
  contain the snapshot or bake-off report, so those observations were not
  reproduced in this review.
- Inspection of the legacy verifier established that its `asset_set_exact`
  value did not enumerate arbitrary non-Python files or the full directory
  topology. The stronger exact-set claim is therefore invalidated; the legacy
  record is retained only for provenance.
- The corrected verifier exact-enumerates files and directories and rejects
  undeclared entries, unsafe symlinks, and special filesystem entries. A
  regression test demonstrates rejection of an undeclared `unexpected.bin`.
- Phase 1 v2 requires a new method-bound record. No such record was fabricated
  in the absence of the real artifacts, and the reproduced gate reports encoder
  identity false.
- The model was not loaded and no numerical inference was run. No check here
  establishes numerical parity, performance, contamination status, or licence
  permission.

## Better Colab recovery

- Initial SQLite `PRAGMA quick_check` returned `ok`. A focused recovery bundle
  was created at ignored path
  `artifacts/better-colab-recovery-20260817T100002Z/`, and every file passed its
  recorded `SHA256SUMS` check.
- The stale execution's database index covered five contiguous output chunks
  totaling 876 bytes, while its incomplete spool was 14,410 bytes. The full
  spool was retained twice: in the recovery bundle and beside the live spool as
  a pre-recovery copy.
- After replacing only the live spool with the indexed prefix, Better Colab's
  own forced-stop path finalized SHA-256
  `92642e44c54d60f7239fda64c5e7a01792169c6ccc5a9a8842f4e7f1f47d9a90`
  and transitioned the execution from `disconnected` to `unknown` with reason
  `forced_controller_stop`.
- A fresh controller reported zero active executions. The named Colab session
  reported `backend_alive: false`, `kernel_connected: false`, and
  `kernel_execution_ready: false`.
- No stale execution was replayed, no remote code or probe was run, and no
  source acquisition or training occurred.
- A later explicit-ADC retry isolated the packaged kernel-client API mismatch,
  repaired that compatibility boundary, and obtained a fresh nonce-ready CPU
  runtime. This supersedes the earlier `CONNECT_FAILED:AttributeError` as a
  current dependency diagnosis; it does not establish Drive authorization.
- The earlier Drive attempt displayed a validated Google consent URL but the
  then-current CLI repeatedly polled a dry run until its deadline. Source
  comparison with the official client established that this was a CLI protocol
  deadlock: the browser close-window page does not signal the process, which
  instead requires explicit Continue followed by fresh-token final
  propagation. A later disposable-CPU test live-verified that corrected path,
  the read-only `fuse.drive` mount, and complete account-wide cleanup.
- A separate read-only Drive connector listed no shared drive named `Data`.
  It was not treated as the intended account and supplied no registry ID.

## Expected external blockers

- Stable shared-Drive and root-folder resource IDs have not been obtained, so no
  Drive observation, bound registry, storage attestation, or byte audit exists.
- Publisher statement locations and receipts are absent. Legal/provenance
  captures exist, but every historical human assessment remains pending and v4
  evaluation entries need newly bound packets. Five confirmatory envelopes,
  adapters/generators, seals, signed anchors, all seven role-specific
  contributions, and the public union remain absent.
- A prior diagnostic exposed the public EvidenceBench test JSON. The registry
  and evidence packet now block its confirmatory use until replacement or
  independent custody; its item-level observations were not used here.
- Registered source bytes have not passed Phase 0 v4 audit/inventory/admission.
  The Wikidata acquisition target was not downloaded under this implementation.
- No raw-source-to-Phase-1 transformer exists. No 40,000-node sample, capped
  graph artifact, or eight-family objective replay manifest has been created.
  Phase 0 v4 has the record matcher, but no transformer consumes and preserves
  its `quarantine_decision: clear` output.
- The earlier restored-workspace claim that `.git` was an empty read-only
  directory no longer applies; this directory is now a writable Git worktree.

## Integrity interpretation

Passing tests shows that the checked-in implementation behaves as those tests
exercise it. It does not prove unacquired data clean, metadata truthful,
licences approved, generated labels correct, detached manifests authentic, or
any model effective. No training, optimization, threshold selection, embedding
generation, or confirmatory evaluation was run.
