# Phase 0 v3 clean-room runbook

Phase 0 establishes frozen contracts, storage identity, provenance, licensing,
evaluation quarantine, immutable raw-byte inventory, source admission, and a
mechanical readiness gate. It does not transform a graph, generate model
examples, run an encoder, fit a model, tune a threshold, or authorize training.

The operational authorization boundary is `gate-v3`, licensing/v1 assessment
bundles, and v3 admission receipts. Phase 0 v2 remains a frozen dependency for
storage, source-audit, inventory, seal, and quarantine evidence. The historical
`gate`, `source acquire`, and `source assess-admission` routes use v2 licence
reviews; do not use them as substitutes for the v3 paths. Commands ending in
`-v1` reproduce still older artifacts only.

## Control order

1. Validate the frozen v2/v3, licensing/v1, and storage/v1 contracts plus the
   checked-in registries.
2. Resolve the stable Google shared-Drive and root-folder resource IDs through
   an authenticated API and create a fresh storage attestation. A mounted path
   or familiar folder name is not identity evidence.
3. Capture the allowlisted legal/provenance documents, verify each immutable
   evidence bundle, then obtain accountable human decisions. A pending scaffold
   is not an approval, and a registry `verified` flag is not source evidence.
4. Pin each confirmatory archive and adapter or first-party generator. Build a
   dependency-closed private evaluation envelope, then seal it to the
   custodian's offline GPG public key. The sealing command derives the public
   quarantine contribution from that same envelope.
5. Compile the public union from every per-evaluation contribution.
6. Audit the registered pre-existing Drive artifacts from raw bytes. If the
   acquisition sub-gate becomes ready, acquire the pinned Wikidata target.
7. Re-audit all bytes, stream structural inventories, and issue source admission
   receipts bound to the registry, audit, attestation, licence assessment,
   inventories, and quarantine index.
8. Evaluate the final transformation gate. Even a ready report must contain
   `training_authorized: false`.

## Local contract verification

```bash
uv sync --group dev
uv run pytest -q
uv run hf-phase0 registry validate \
  --instance registries/sources.v2.json \
  --instance registries/evaluations.v2.json
uv run hf-phase0 licence contracts-validate
uv run hf-phase0 storage contracts-validate
```

The validators recompute RFC 8785 digests and compare them with independent
locks in the implementation. `gate-v3` also checks its own frozen schemas and
all frozen dependencies.

## Storage identity

The source registry deliberately leaves `provider_resource_id` and
`root_resource_id` null until the IDs are observed through an authenticated
Google Drive API. Do not infer either ID from a mounted path or folder name.

Choose the Better Colab authentication provider explicitly and use it for every
command in one workflow. The default `oauth2` provider reads the separate
`~/.config/colab-cli/token.json` cache; `gcloud auth application-default login`
refreshes the `adc` provider instead. Do not infer that refreshing one repaired
the other. Never replay an execution in the `unknown` state. Use a CPU session,
and require a nonce probe to report `backend_alive`, `kernel_connected`, and
`kernel_execution_ready` before sending source.

If the nonce probe reports `CONNECT_FAILED:AttributeError`, verify the installed
Better Colab build and its `jupyter-kernel-client` API before blaming
authentication or the remote runtime. The current CLI source is adapted to and
pins the released 1.0.1 API, and its wheel smoke test exercises that exact
boundary. Reinstall the current built artifact and repeat the nonce probe; do
not silently substitute a different source-only dependency.

Attempt native mounting first. Keep `colab drivemount` attached, approve the
validated Google URL in the browser, and press Enter once only after the browser
shows its close-window page. The keypress merely permits final propagation;
require the CLI's final `drive_auth_success` before accepting the mount:

```bash
uv run colab --auth=adc drivemount --read-only \
  --session DRIVE-AUDIT-CPU /content/drive
```

The corrected client performs one fresh-token/bodyless dry run and one
fresh-token/bodyless final propagation. It does not poll, reuse an XSRF token,
or send the obsolete multipart `file_id`. If native mounting fails, compare it
with the official browser flow on the same account before classifying the
failure as upstream.

In the browser connected to the exact audited Colab runtime, obtain ADC with
the exact Drive read-only scope. User ADC containing Drive scopes requires an
approved desktop OAuth client file. Keep that file protected locally; do not
commit it, paste it into chat, or include it in logs. Set the attestation only
after personally checking that the native mount and ADC used the same account:

```python
!gcloud auth application-default login --no-launch-browser --client-id-file=/PROTECTED/approved-desktop-oauth.json --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly

import os
os.environ["HF_DRIVE_SAME_ACCOUNT_ATTESTED"] = "1"
```

Then execute `scripts/drive_identity_probe.py` once through Better Colab with an
exact source SHA-256 guard and a new idempotency key. The probe must fail closed
if the credential cannot prove its granted scopes, if any other Drive API scope
was granted, or if the human attestation is absent. When credentials do not
expose `granted_scopes`, the probe sends the current access token to Google's
token-info endpoint with a bounded POST and retains only the returned scope set.
It never emits token-info email, subject, token, or client fields.

The probe fully paginates Drive API results and requires exactly one visible
shared drive named `Data` and one direct, non-shortcut folder named
`graph-memory-data-lake`. It compares list/get responses before and after
checking a live DriveFS/FUSE mount. It emits neither account email nor child
names and performs no Drive API mutation or file write. It proves that its API
credential lacks a write-capable Drive scope; it explicitly does not claim the
mounted filesystem lacks write capability.

### Gated read-only fallback

Use the fallback only after the native path fails and only when the approved
desktop OAuth client prerequisite above is available. The fallback requires
the same explicit protected ADC file for Drive API resolution, rclone, and the
identity probe; it also requires the same-account human attestation. It pins
rclone 1.75.0 for Linux amd64, verifies archive SHA-256
`aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa`
and binary SHA-256
`f3f9aff817f9766029e50adf9a7963c169e475b8f10c7927823568a0d9443db7`,
then downloads the tag-matched MIT `COPYING` file from the official rclone
repository and verifies SHA-256
`8cd2e9e750b90a04b7d82dbbca3930c696ae0309d7c10464f90a44f45754cd04`
before preserving it beside the executable. The release ZIP itself does not
contain `COPYING`.

Prepare an owner-only state directory and run all commands in the exact CPU
runtime. These paths are examples; use explicit absolute protected paths:

```bash
chmod 600 /PROTECTED/application_default_credentials.json
chmod 600 /PROTECTED/approved-desktop-oauth.json
mkdir -m 700 /PROTECTED/phase0-fallback-state
export HF_DRIVE_SAME_ACCOUNT_ATTESTED=1

python scripts/drive_mount_fallback.py start \
  --adc-file /PROTECTED/application_default_credentials.json \
  --state-file /PROTECTED/phase0-fallback-state/state.json \
  --client-id-file /PROTECTED/approved-desktop-oauth.json

python scripts/drive_mount_fallback.py status \
  --adc-file /PROTECTED/application_default_credentials.json \
  --state-file /PROTECTED/phase0-fallback-state/state.json
```

The in-memory remotes expose exactly
`/content/drive/Shareddrives/Data/...`: a Drive remote restricted to the
API-resolved shared-drive ID, then nested `Data` and `Shareddrives` combine
remotes. The mount uses `--read-only`, VFS cache off, zero buffer/read-ahead,
owner-only permissions, no `--allow-other`, and a fixed device name. No rclone
configuration is persisted. Mode-`0600` state under a mode-`0700` directory
contains only PID, process start ticks, executable hash, ADC digest, device
name, and resolved shared-drive ID.

`status` accepts the mount only when `fuse.rclone`, device name, read-only mount
metadata, process start time, executable, exact launch arguments, environment
ADC binding, current ADC digest, and freshly API-resolved Drive ID all agree.
Foreign mounts, reused PIDs, unsafe paths, broader scopes, checksum failures,
and zero or multiple matching drives fail closed.

Run the frozen observation with the same ADC and state, then bind it within 15
minutes exactly as for the native path:

```bash
python scripts/drive_identity_probe.py \
  --adc-file /PROTECTED/application_default_credentials.json \
  --fallback-state-file /PROTECTED/phase0-fallback-state/state.json \
  > artifacts/drive-observation.v1.json
```

After binding—or after any aborted attempt—stop only the validated owned mount:

```bash
python scripts/drive_mount_fallback.py stop \
  --adc-file /PROTECTED/application_default_credentials.json \
  --state-file /PROTECTED/phase0-fallback-state/state.json
```

`stop` refuses foreign mount metadata or a reused PID. It removes only its
validated mount, process, private state, executable, and preserved temporary
licence file. It never reads Drive file content or performs a Drive write.

Save only the single successful JSON object as an ignored observation artifact,
then bind it within 15 minutes:

```bash
uv run hf-phase0 storage contracts-validate \
  --observation artifacts/drive-observation.v1.json \
  --evaluated-at OBSERVATION-BIND-TIME

uv run hf-phase0 storage bind-drive \
  --registry registries/sources.v2.json \
  --observation artifacts/drive-observation.v1.json \
  --registry-output artifacts/sources.v2.drive-bound.json \
  --attestation-output artifacts/storage-attestation.v2.json \
  --verifier DRIVE-CUSTODIAN-ID \
  --bound-at OBSERVATION-BIND-TIME
```

The command refuses existing outputs, leaves the checked-in unbound registry
unchanged, and derives the v2 `storage_attestation` from the exact observation.
Use the bound registry for every later audit, gate, and admission command.

Keep the machine-specific attestation under `artifacts/` or another ignored
location. It must bind:

- the registered locator and provider;
- the shared-Drive resource ID;
- the root-folder resource ID;
- the exact mounted root;
- observation time, method, and verifier.

The gate rejects a missing, mismatched, future-dated, or older-than-72-hours
attestation. No observation or attestation has yet been produced. Native final
propagation was live-verified on 2026-08-18: after one explicit human Continue,
the fresh-token bodyless final POST returned HTTP 200 with `success: true`, the
read-only mount completed, and an exact-hash metadata-only probe found one
`fuse.drive` mount with `ro` plus the fixed expected lake-root directory. It
read no Drive file content, performed no Drive write, and reported
`training_authorized: false`; the disposable CPU runtime was released and the
account-wide session list was empty. This mount check is not the exact-scope
identity observation and supplied no resource IDs. No approved desktop OAuth
client file was supplied for exact-scope user ADC or fallback execution. A
read-only check through the separately connected Drive integration found no
accessible shared drive named `Data`; its account therefore cannot be assumed
to match the intended Colab mount and no ID from it may be bound.

## Licence evidence

`licensing/catalog.v1.json` enumerates the exact subject set and 43 allowlisted
legal/provenance documents. It contains no evaluation archives, records,
answers, or labels. Validate and capture it without crawling:

```bash
uv run hf-phase0 licence catalogue-validate \
  --catalogue licensing/catalog.v1.json \
  --sources registries/sources.v2.json \
  --evaluations registries/evaluations.v2.json \
  --encoder-spec registries/encoder.gte-modernbert.v1.json

uv run hf-phase0 licence catalogue-capture \
  --catalogue licensing/catalog.v1.json \
  --sources registries/sources.v2.json \
  --evaluations registries/evaluations.v2.json \
  --encoder-spec registries/encoder.gte-modernbert.v1.json \
  --output-root private/licensing
```

The capture is resumable but immutable: a partial output pair requires manual
inspection, and a complete pair is never overwritten. Packet preparation
rehashes every snapshot, binds the exact subject entry, writes a pending
assessment, and emits only a redacted public audit index. Those steps have been
completed in the current workspace: 43 documents, 10 packets, no missing
catalogued capture. Two unimplemented first-party evaluations intentionally
have zero documents and blocking missing-implementation/provenance findings;
the approval verifier rejects an empty evidence bundle.

An accountable human must inspect the private packets and use
`licence assessment-finalize` to create a separate final file. Source approvals
must explicitly allow acquisition, inventory, quarantine, transformation,
embedding, and commercial-service use. Evaluation approvals must allow
acquisition, quarantine, evaluation, and commercial context. Training and all
redistribution uses remain explicitly excluded. Every blocking finding needs a
document-backed resolution; otherwise reject the subject or leave it pending.
The tool does not make a legal judgment.

## Confirmatory vault and quarantine contributions

The custodian retains the private GPG key offline. This workspace and Colab may
receive only the full public-key fingerprint. Do not generate or import the
private key here.

Before sealing, update the evaluation registry with the exact archive and
adapter hashes and remove only blockers that are actually resolved. The private
`evaluation_envelope` must match those registry bindings exactly. Seal and
verify one envelope at a time, then mark its registry entry `sealed` only after
the matching ciphertext, receipt, and contribution exist:

```bash
uv run hf-phase0 seal create \
  --input private/envelopes/DATASET.json \
  --output vault/DATASET.gpg \
  --recipient FULL_PUBLIC_KEY_FINGERPRINT \
  --receipt private/receipts/DATASET.json \
  --contribution private/contributions/DATASET.json \
  --evaluations registries/evaluations.v2.json \
  --custodian offline-key-custodian
```

The command refuses to overwrite any output. It canonicalizes and encrypts the
private envelope over standard input to GPG, derives the public contribution
from the same records, and binds both into the receipt. Verify the ciphertext:

```bash
uv run hf-phase0 seal verify \
  --ciphertext vault/DATASET.gpg \
  --receipt private/receipts/DATASET.json
```

Create one private access log per seal. The optional detail object accepts only
bounded `receipt_id`, `report_id`, `request_id`, and `ticket_id` identifiers;
it must never contain labels, answers, secrets, credentials, or free text:

```bash
uv run hf-phase0 seal log-event \
  --log private/DATASET.access.jsonl \
  --seal-id DATASET-SEAL-ID \
  --action seal_created \
  --actor offline-key-custodian
```

Copy the emitted `event_hash` to an independently protected append-only custody
record. Keeping the expected head beside the mutable JSONL file does not make
it an external anchor and cannot prove that a suffix was not deleted. Verify
the local chain against that independently obtained value before using it:

```bash
uv run hf-phase0 seal verify-log \
  --log private/DATASET.access.jsonl \
  --expected-head sha256:EXPECTED_ANCHORED_HEAD \
  --expected-count EXPECTED_EVENT_COUNT
```

The active gate requires one non-empty, externally head-anchored log for every
declared evaluation seal. A `decrypt`, `inspect_labels`,
`report_confirmatory_result`, `tune_from_result`, `consume`, or `retire` event
automatically makes that evaluation unavailable for confirmatory readiness.

Compile the public union from every contribution:

```bash
uv run hf-phase0 quarantine compile \
  --contribution private/contributions/DATASET-1.json \
  --contribution private/contributions/DATASET-2.json \
  --index-id public-evaluation-union-v2 \
  --output artifacts/public-quarantine-index.v2.json
```

Repeat `--contribution` for all seven declared evaluations. The gate recomputes
the union and rejects an index that differs from its contributions. Public
contributions contain one-way identifiers, hashes, and fingerprints—not labels,
answers, split membership, or private payloads.

MinHash values are constrained to RFC 8785's safe-integer domain. The current
v2 implementation compiles and verifies the fingerprint union but does not yet
offer a v2 record-matching command. Before any source transformer can declare a
record `clear`, implement a v2 matcher in which MinHash is only a candidate
index and exact Jaccard over the stored shingle hashes makes the exclusion
decision (0.90 for `character5`, 0.85 for `word5`). The unsuffixed historical
`quarantine check` command still validates v1 descriptor/index schemas and must
not be presented as v2 evidence.

## Byte audit and acquisition

Audit all registered paths without following an unregistered symlink:

```bash
uv run hf-phase0 source audit \
  --registry artifacts/sources.v2.drive-bound.json \
  --storage-attestation artifacts/storage-attestation.v2.json \
  --output artifacts/source-audit.v2.json
```

The audit covers every registered artifact, including a missing acquisition
target, but every artifact marked `preexisting` must verify before the
acquisition sub-gate can open. Audits bind the exact registry and attestation,
detect a changing file during hashing, and expire after 72 hours.

Only when the gate report sets `foundation_acquisition_authorized: true` may the
registered acquisition target be downloaded. The command accepts no caller
override for URL, destination, expected size, or publisher checksum:

```bash
uv run hf-phase0 source acquire-v3 \
  --sources artifacts/sources.v2.drive-bound.json \
  --evaluations registries/evaluations.v2.json \
  --storage-attestation artifacts/storage-attestation.v2.json \
  --source-audit artifacts/source-audit.v2.json \
  --licence-assessment private/licensing/REVIEW/assessment.final.json=private/licensing/REVIEW/bundle.json \
  --seal vault/DATASET.gpg=private/receipts/DATASET.json \
  --access-log private/DATASET.access.jsonl=sha256:EXPECTED_ANCHORED_HEAD \
  --contribution private/contributions/DATASET.json \
  --quarantine artifacts/public-quarantine-index.v2.json \
  --artifact-id wikidata-20260720-all-json-bz2 \
  --evaluated-at 2026-08-17T00:00:00Z \
  --minimum-free-bytes 26843545600
```

Repeat the licence-assessment, seal, and contribution options for every
required record.
Recheck and preserve the official checksum evidence immediately before a real
acquisition. The downloader requires HTTPS, exact range semantics when
resuming, registered size and SHA-1/SHA-256 verification, fsync, and atomic
promotion. It never overwrites a completed artifact.

## Structural inventories and source admission

After acquisition, regenerate the audit so it covers the newly present bytes.
Build one inventory for every registered artifact:

```bash
uv run hf-phase0 source count \
  --registry artifacts/sources.v2.drive-bound.json \
  --storage-attestation artifacts/storage-attestation.v2.json \
  --source-audit artifacts/source-audit.v2.json \
  --artifact-id ARTIFACT-ID \
  --output artifacts/inventory.ARTIFACT-ID.v2.json
```

Then assess each foundation source with all of its inventory records:

```bash
uv run hf-phase0 source assess-admission-v3 \
  --source-id SOURCE-ID \
  --registry artifacts/sources.v2.drive-bound.json \
  --storage-attestation artifacts/storage-attestation.v2.json \
  --source-audit artifacts/source-audit.v2.json \
  --licence-assessment private/licensing/SOURCE-REVIEW/assessment.final.json \
  --licence-bundle private/licensing/SOURCE-REVIEW/bundle.json \
  --quarantine artifacts/public-quarantine-index.v2.json \
  --inventory artifacts/inventory.ARTIFACT-ID.v2.json \
  --assessor HUMAN-ASSESSOR-ID \
  --output artifacts/admission.SOURCE-ID.v2.json
```

Admission remains a human-accountable decision bound to mechanical evidence;
the tool does not infer rights or suitability from a filename or passing hash.

## Final gate

Supply the complete evidence set:

```bash
uv run hf-phase0 gate-v3 \
  --sources artifacts/sources.v2.drive-bound.json \
  --evaluations registries/evaluations.v2.json \
  --storage-attestation artifacts/storage-attestation.v2.json \
  --source-audit artifacts/source-audit.v2.json \
  --licence-assessment private/licensing/REVIEW/assessment.final.json=private/licensing/REVIEW/bundle.json \
  --seal vault/DATASET.gpg=private/receipts/DATASET.json \
  --contribution private/contributions/DATASET.json \
  --quarantine artifacts/public-quarantine-index.v2.json \
  --inventory artifacts/inventory.ARTIFACT-ID.v2.json \
  --admission artifacts/admission.SOURCE-ID.v2.json \
  --evaluated-at 2026-08-17T00:00:00Z \
  --output artifacts/phase0-gate.v3.json
```

Repeat all evidence options as needed, including one `--access-log` per seal.
The supplied head must come from the independent custody record, not be derived
ad hoc from the log being checked. Exit status `2` means blocked; `0` means
foundation transformation is permitted. Neither status authorizes training.

The checked-in `audit/phase0-gate.v3.licensing.json` is the current fail-closed
checkpoint. `contracts_frozen` and `licensing_evidence_verified` are true: the
complete set of bound packets is structurally verified. `licensing_ready` is
false because all human decisions remain pending. The evidence flag does not
mean the evidence is legally sufficient or that a subject is approved.
