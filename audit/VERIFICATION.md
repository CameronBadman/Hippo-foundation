# Phase 0 v3 and Phase 1 v2 verification record

Verification date: 2026-08-18

## Current restoration checks

- Missing `src/`, `tests/`, and `scripts/` content was restored without
  overwriting existing paths from the local source distribution with SHA-256
  `6aa097cfb7d03fc9a87901eb69afb63fc0a876984dc0d78944eac119766a24b6`.
- `.venv/bin/pytest -q` passed all 104 tests. New regressions cover arbitrary
  undeclared encoder entries, legacy encoder-attestation rejection, access-log
  schema and symlink safety, externally anchored suffix-truncation detection,
  consuming evaluation actions, and rejection of development partitions as
  confirmatory data.
- `uv lock --check`, Python bytecode compilation, both CLI help surfaces, and
  Phase 0 v2 source/evaluation registry validation passed.
- Both current fail-closed gate reports were regenerated with the restored
  evidence. Phase 0 now exposes missing per-seal access logs/anchors and rejects
  SocialIQA validation as confirmatory. Phase 1 rejects the legacy encoder
  record. Both reports validate against their frozen schemas and keep
  `training_authorized: false`.
- Phase 1 v2 reproduced the locked digests for its gate and new exact-layout
  encoder-verification schema. The latter is
  `sha256:e7fbdb108a9cd2750422668c4f35a0fee4a310afaf9d289065028ee3fd3e402d`.
- A fresh source distribution and wheel were built into a temporary directory.
  Wheel inspection found both console scripts and all schemas, including the
  new Phase 1 v2 encoder schema. A temporary target install loaded the package
  from that wheel and reproduced the Phase 0 v3 and Phase 1 v2 schema locks.
- Ruff was not rerun in this restoration review, so no current lint claim is
  made. The declared runtime dependencies remain only `jsonschema` and
  `rfc8785`; neither is an ML framework.

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
- Publisher checksum evidence is incomplete. Legal/provenance captures exist,
  but every human assessment remains pending. All seven confirmatory evaluation
  envelopes, adapters/generators, seals, contributions, and the public union
  remain absent.
- A prior diagnostic exposed the public EvidenceBench test JSON. The registry
  and evidence packet now block its confirmatory use until replacement or
  independent custody; its item-level observations were not used here.
- Registered source bytes have not passed Phase 0 v2 audit/inventory/admission.
  The Wikidata acquisition target was not downloaded under this implementation.
- No raw-source-to-Phase-1 transformer exists. No 40,000-node sample, capped
  graph artifact, or eight-family objective replay manifest has been created.
  Phase 0 v2 also lacks the record matcher needed to establish a transformer's
  `quarantine_decision: clear` output.
- `.git` is an empty read-only directory rather than a Git repository, so no
  commit, remote, push, or pull request is represented as completed.

## Integrity interpretation

Passing tests shows that the checked-in implementation behaves as those tests
exercise it. It does not prove unacquired data clean, metadata truthful,
licences approved, generated labels correct, detached manifests authentic, or
any model effective. No training, optimization, threshold selection, embedding
generation, or confirmatory evaluation was run.
