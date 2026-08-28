# Phase 0 v4.2 clean-room runbook

Phase 0 establishes frozen contracts, storage identity, provenance, licensing,
evaluation quarantine, immutable raw-byte inventory, source admission, and a
mechanical readiness gate. It does not transform a graph, generate model
examples, run an encoder, fit a model, tune a threshold, or authorize training.

The active authorization boundary is `gate-v4.2`. It consumes the complete
v4.1 evidence graph and adds a code-pinned Internal Workspace OAuth policy,
detached authority over exact installed-client bytes, a live Drive API/DriveFS
same-resource proof, signed per-artifact acquisition authority, and retained
pre/post-acquisition evidence. It validates every frozen predecessor contract
but does not import an older gate's readiness decision. `gate-v4.1`, `gate-v4`,
and all unsuffixed or older-suffix commands remain available for reproducibility
or as explicitly required evidence producers; they cannot by themselves
authorize real acquisition or transformation.

## Active v4.2 authority layer

### External activation boundary

The checked policy `policies/oauth-authority.v4.2.pending.json` remains the
intentionally non-authorizing baseline used by the reproducible blocked report.
On 2026-08-29, the Workspace administrator confirmed the organization-owned
project and Internal audience, supplied the non-secret policy facts, accepted
online passphrase-protected key staging as an interim custody exception, and
directed activation of `policies/oauth-authority.v4.2.approved.json`. The exact
approved policy digest is pinned in code. That pin recognizes only the policy;
it supplies no OAuth consent, signed authority, live Drive proof, acquisition
authority, or training authority.

Validate the approved policy and record its canonical instance digest:

```bash
uv run hf-phase0 registry validate-v4.2 \
  --instance policies/oauth-authority.v4.2.approved.json
```

`APPROVED_OAUTH_AUTHORITY_POLICY_SHA256` in `phase0/authority_v4_2.py` is set to
the emitted digest. Any successor requires another separately reviewed change.
Never add the installed-client file, client secret, ADC, token, raw Workspace
customer ID, or private signing key to the repository.

Google documents `drive.readonly` as a restricted scope, but also documents an
internal-use verification exception when the project is organization-owned,
the audience is Internal, and users belong to that organization. On 2026-08-29,
the Workspace administrator confirmed the organization ownership and Internal
audience, and the installed-client project binding was checked mechanically.
Those organization and audience claims remain human-confirmed rather than
independently observed through the Cloud API:

- [Drive scope classification](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Internal-use verification exception](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

### Canonical Drive root marker

Once the stable shared-Drive and direct lake-root folder IDs are independently
resolved, generate a non-sensitive marker:

```bash
uv run hf-phase0 storage marker-payload-v4.2 \
  --marker-id MARKER-UUID \
  --provider-resource-id SHARED-DRIVE-ID \
  --root-resource-id LAKE-ROOT-FOLDER-ID \
  --output private/drive/.entor-drive-identity-v1.json
```

The storage custodian uploads those exact canonical bytes once as
`.entor-drive-identity-v1.json` directly beneath
`/content/drive/Shareddrives/Data/graph-memory-data-lake`, then records its Drive
file ID and emitted SHA-256. This is the one deliberate external write in this
identity setup. The observer below performs no write.

### Signed OAuth authority

Keep the installed-client JSON at an absolute, owner-owned, mode-`0600` path.
Construct the canonical payload, sign the exact output with a policy-listed
offline key, and verify it:

```bash
uv run hf-phase0 oauth authority-payload-v4.2 \
  --policy policies/oauth-authority.v4.2.approved.json \
  --oauth-config /PROTECTED/entor-internal-oauth.json \
  --authority-id ENTOR-AUTHORITY-ID \
  --provider-resource-id SHARED-DRIVE-ID \
  --root-resource-id LAKE-ROOT-FOLDER-ID \
  --marker-file-id MARKER-FILE-ID \
  --marker-sha256 MARKER-SHA256 \
  --approved-at APPROVED-AT \
  --valid-until VALID-UNTIL \
  --approver-id WORKSPACE-ADMIN-ID \
  --signing-key-fingerprint ADMIN-SIGNING-FINGERPRINT \
  --output private/authority/oauth-authority.v4.2.canonical.json

uv run hf-phase0 oauth authority-verify-v4.2 \
  --policy policies/oauth-authority.v4.2.approved.json \
  --payload private/authority/oauth-authority.v4.2.canonical.json \
  --signature private/authority/oauth-authority.v4.2.sig \
  --public-key private/authority/oauth-authority.v4.2.pub \
  --verified-at VERIFIED-AT \
  --output artifacts/oauth-authority.v4.2.receipt.json
```

The receipt digest is stable across re-verification. Freshness is evaluated
separately, so checking the same signature later does not silently change every
downstream binding.

### Exact-scope ADC and live same-resource proof

The installed Better Colab build is `0.1.dev103+ga8c1b68b5`. Use one fresh,
durable CPU session. Authorize the exact-scope provider with the protected
approved client and keep its ADC in the runtime's protected `/dev/shm` path.
Then run `colab drivemount --read-only` in the user's visible terminal. Leave
the command attached while the user finishes browser consent; after the browser
says to close the window, return to the terminal and press Enter so credential
propagation completes.

Better Colab labels a caller-supplied client `provider_mode=development`. That
label is not treated as authority. V4.2 accepts it only when the separately
signed and code-pinned project policy approves the exact client bytes and Cloud
project. A broad default `colab drivemount` success cannot be reused because it
does not prove the exact API scope or client.

Using the same ADC and mounted runtime, first create the frozen storage/v1
observation with the accountable human same-account statement and bind it with
`storage bind-drive-v4`. Then independently create the v4.2 proof:

```bash
uv run hf-phase0 storage observe-drive-v4.2 \
  --policy policies/oauth-authority.v4.2.approved.json \
  --oauth-authority \
private/authority/oauth-authority.v4.2.canonical.json=private/authority/oauth-authority.v4.2.sig=private/authority/oauth-authority.v4.2.pub \
  --adc-file /dev/shm/better-colab/credentials/google-drive-readonly.json \
  --proof-output artifacts/drive-access-proof.v4.2.json
```

The observer verifies the exact token scope and authorized OAuth client, checks
the Entor-domain principal without emitting its email or raw permission ID,
gets the registered Drive/root/marker by ID, compares exact marker bytes through
the API and pinned DriveFS root, checks the live mount, and repeats remote
identity. It does not claim that a human performed a check. The separate
storage/v1 observation remains required by the v4.1 base graph.

## Required v4.1 evidence graph

The order below is part of the evidence contract. Do not move rights review or
sealing after the final evaluation-registry transition, and do not treat a
research manifest copy as a fresh publisher receipt.

### 1. Validate the roots and publisher-URL successor

The trusted roots are:

- sources:
  `sha256:c724de9fea9e13d365503f8cdaeaa25016fc906cebf6bb05b6884a2dae69e3ec`;
- evaluations:
  `sha256:6c52a922377d7ae017ae24ecca0f2dc7d239b562a954ac310b6325fe21cd97cb`.

The checked successor
`registries/sources.v4.publisher-pinned.json` pins the Wikidata 20260720
manifest URL once and the enwiki 20260801 manifest URL for all six enwiki
artifacts. It preserves every source entry and existing `verified` flag.

```bash
uv run hf-phase0 registry lineage-v4.1 \
  --registry registries/sources.v4.pending.json \
  --registry registries/sources.v4.publisher-pinned.json
```

To reproduce it into a new path, use `registry publisher-pin-v4.1`; never edit
the checked registry in place. The ignored research copies recorded in
`audit/publisher-manifest-research.v4.1.json` matched all seven registered SHA-1
rows over HTTPS. They are not authorization evidence, and no detached publisher
signature was verified.

### 2. Bind exact Drive identity

Obtain the exact-scope, same-account Drive observation using the protected
workflow later in this document, then bind it within 15 minutes:

```bash
uv run hf-phase0 storage bind-drive-v4 \
  --registry registries/sources.v4.publisher-pinned.json \
  --observation artifacts/drive-observation.v1.json \
  --registry-id hippocampus-foundation-sources-v4-drive-bound \
  --registry-output artifacts/sources.v4.drive-bound.json \
  --attestation-output artifacts/storage-attestation.v4.json \
  --verifier DRIVE-CUSTODIAN-ID \
  --bound-at OBSERVATION-BIND-TIME
```

A protected Desktop OAuth client is available and mechanically bound to the
administrator-confirmed project. The policy root, signed authority, stable
resource IDs, and exact-scope observation are not yet available. That remains
an external-authority boundary, not permission to infer IDs from a mount path.

### 3. Fetch fresh publisher statements after Drive binding

Fetch both manifests again after binding, retain their exact bytes privately,
and create one receipt for every registered artifact. Receipts expire after 72
hours and must bind the Drive-bound source-registry tip:

```bash
uv run hf-phase0 source publisher-receipt-v4 \
  --registry artifacts/sources.v4.drive-bound.json \
  --evidence-id REGISTERED-EVIDENCE-ID \
  --statement private/publisher/STATEMENT.txt \
  --resolved-url EXACT-REGISTERED-MANIFEST-URL \
  --retrieved-at RETRIEVED-AT \
  --verified-at VERIFIED-AT \
  --verifier PUBLISHER-EVIDENCE-REVIEWER \
  --output private/publisher/ARTIFACT.receipt.v4.json
```

The Wikimedia statements supply SHA-1 values over HTTPS. Locally computed
hashes and the earlier research copies cannot substitute for these receipts.

### 4. Pin evaluation assets, keys, and dependency units

Create one v4 successor of `registries/evaluations.v4.json` in which every
entry is `pinned`, every archive/adapter binding is concrete, every confirmatory
key fingerprint is exact, and the highest dependency units are frozen. Validate
the complete ordered chain:

```bash
uv run hf-phase0 registry lineage-v4.1 \
  --registry registries/evaluations.v4.json \
  --registry artifacts/evaluations.v4.pinned.json
```

This stage requires real private assets, adapters or generators, independent
oracles, and custodian keys. None was manufactured while implementing v4.1.

### 5. Rebind retained rights captures and obtain human decisions

Rehash the existing verified captures from one private root into a distinct new
root. `catalogue-rebind` requires a fully pinned evaluation registry, creates
new entry-bound bundles, and writes pending assessments only:

```bash
uv run hf-phase0 licence catalogue-rebind \
  --catalogue licensing/catalog.v1.json \
  --sources artifacts/sources.v4.drive-bound.json \
  --evaluations artifacts/evaluations.v4.pinned.json \
  --encoder-spec registries/encoder.gte-modernbert.v1.json \
  --verified-capture-root private/licensing \
  --output-root private/licensing-v4.1 \
  --audit-index artifacts/licensing-v4.1.rebind-index.json \
  --assembled-at ASSEMBLED-AT
```

An accountable reviewer must separately resolve or reject every blocking
finding. Code must not change `decision: pending` into an approval. Evaluation
reviews must follow registry pinning and precede materialization.

### 6. Materialize every evaluation independently

The custodian runs `evaluation materialize-v4.1` once per pinned entry. The
command rehashes the archive, adapter, and byte-distinct oracle; rejects unsafe,
duplicate, absent, or unaccounted archive members; proves complete primary-unit
coverage; and binds every output and dependency. The private manifest remains
under custodian control; the public receipt contains counts and digests only.

```bash
uv run hf-phase0 evaluation materialize-v4.1 \
  --evaluations artifacts/evaluations.v4.pinned.json \
  --dataset-id DATASET-ID \
  --archive private/evaluations/DATASET.archive \
  --adapter private/evaluations/DATASET.adapter \
  --oracle private/evaluations/DATASET.oracle \
  --envelope private/envelopes/DATASET.v4.json \
  --inventory private/evaluations/DATASET.inventory.v4.1.json \
  --manifest-id DATASET.materialization.v4.1 \
  --materialized-at MATERIALIZED-AT \
  --manifest-output private/materialization/DATASET.manifest.v4.1.json \
  --receipt-output artifacts/materialization/DATASET.receipt.v4.1.json
```

The archive and evaluation envelope are held-out material. They must not enter
the development workspace or be inspected to tune features, thresholds, or
prompts.

### 7. Seal confirmatory envelopes and anchor custody

For each confirmatory entry, `seal create-v4.1` requires the pinned registry,
approved pinned-entry rights evidence, and the reproducible materialization. It
encrypts the same envelope and starts the private log with a `seal_created`
event bound to the materialization-receipt digest.

```bash
uv run hf-phase0 seal create-v4.1 \
  --evaluations artifacts/evaluations.v4.pinned.json \
  --materialization MANIFEST=RECEIPT=ARCHIVE=ADAPTER=ORACLE=ENVELOPE \
  --licence-assessment private/licensing-v4.1/REVIEW/assessment.final.json \
  --licence-bundle private/licensing-v4.1/REVIEW/bundle.json \
  --recipient OFFLINE-CUSTODIAN-KEY-FINGERPRINT \
  --custodian OFFLINE-CUSTODIAN-ID \
  --created-at CREATED-AT \
  --output vault/DATASET.v4.gpg \
  --receipt private/receipts/DATASET.v4.json \
  --contribution private/contributions/DATASET.v4.json \
  --access-log private/access/DATASET.jsonl
```

Construct exact RFC 8785 bytes before offline signing:

```bash
uv run hf-phase0 seal anchor-payload-v4 \
  --seal-receipt private/receipts/DATASET.v4.json \
  --access-log private/access/DATASET.jsonl \
  --sequence 1 \
  --anchored-at ANCHORED-AT \
  --valid-until VALID-UNTIL \
  --authority-id INDEPENDENT-AUTHORITY-ID \
  --signing-key-fingerprint OFFLINE-CUSTODIAN-KEY-FINGERPRINT \
  --output private/anchors/DATASET.v4.canonical.json
```

Sign that file outside the development environment. The finalizer verifies the
detached signature, pinned key, full log, freshness window, and absence of any
confirmatory-consumption event.

### 8. Create the sealed evaluation successor

Only after reviews, materializations, seals, logs, and anchors exist may the
final transition be created:

```bash
uv run hf-phase0 registry evaluations-finalize-v4.1 \
  --evaluations artifacts/evaluations.v4.pinned.json \
  --materialization MANIFEST=RECEIPT=ARCHIVE=ADAPTER=ORACLE=ENVELOPE \
  --licence-assessment ASSESSMENT=BUNDLE \
  --seal-v4 CIPHERTEXT=RECEIPT \
  --anchor-v4 ANCHOR=SIGNATURE=PUBLIC_KEY=ACCESS_LOG \
  --registry-id hippocampus-foundation-evaluations-v4-final \
  --generated-at FINALIZED-AT \
  --output artifacts/evaluations.v4.final.json
```

Repeat each evidence option for its complete expected set. Confirmatory entries
move from `pinned` to `sealed`; non-confirmatory entries stay pinned. The tool
removes only evidence-backed blockers, preserves every other field, and requires
the final timestamp to follow all supplied evidence.

### 9. Quarantine and audit the pre-acquisition source state

Compile all seven contributions against the final registry, then perform the
registered source audit. Evaluate `gate-v4.2` with the approved policy, verified
OAuth authority, and current Drive access proof. Before a per-artifact signature
is supplied, it must report `foundation_acquisition_ready: true` and
`foundation_acquisition_authorized: false`.

### 10. Sign and execute each acquisition

Build a canonical `source authorization-payload-v4.2` using the same complete
v4.1 evidence arguments plus the v4.2 policy, OAuth authority, and live proof.
The policy-listed authorizer reviews the exact artifact, expected bytes, byte
ceiling, and validity window, then signs it offline. Verify the signature with
`source authorization-verify-v4.2`.

Only `source acquire-v4.2` may perform the real download. It accepts the complete
evidence graph, the verified signed authorization, artifact ID, minimum free
space, protected ADC, and five output paths. It accepts no caller URL,
destination, expected-size, checksum, or evaluation-time override. Runtime time
must fall inside the 24-hour authorization window.

The command pins the lake-root directory descriptor, reproduces the full
authorization gate immediately before transfer, binds any resumable partial to
the exact signed authorization, repeats the API/DriveFS proof before immutable
promotion, and preserves the partial if identity drifts. An old unbound partial
is rejected before publisher network access. It emits:

- the acquisition receipt;
- the retained pre-acquisition source audit;
- the pre- and post-acquisition Drive proofs; and
- the exact precondition gate.

After acquisition, re-audit all bytes, build each structural inventory, and
create one admission receipt per foundation source.

### 11. Evaluate the final v4.2 gate

The final gate repeats every registry in order:

```bash
uv run hf-phase0 gate-v4.2 \
  --source-registry registries/sources.v4.pending.json \
  --source-registry registries/sources.v4.publisher-pinned.json \
  --source-registry artifacts/sources.v4.drive-bound.json \
  --evaluation-registry registries/evaluations.v4.json \
  --evaluation-registry artifacts/evaluations.v4.pinned.json \
  --evaluation-registry artifacts/evaluations.v4.final.json \
  --drive-observation artifacts/drive-observation.v1.json \
  --storage-attestation artifacts/storage-attestation.v4.json \
  --publisher STATEMENT=RECEIPT \
  --source-audit artifacts/source-audit.v4.json \
  --licence-assessment ASSESSMENT=BUNDLE \
  --materialization MANIFEST=RECEIPT=ARCHIVE=ADAPTER=ORACLE=ENVELOPE \
  --seal-v4 CIPHERTEXT=RECEIPT \
  --anchor-v4 ANCHOR=SIGNATURE=PUBLIC_KEY=ACCESS_LOG \
  --contribution private/contributions/DATASET.v4.json \
  --quarantine artifacts/public-quarantine-index.v4.json \
  --inventory artifacts/inventory.ARTIFACT.v4.json \
  --admission artifacts/admission.SOURCE.v4.json \
  --authority-policy policies/oauth-authority.v4.2.approved.json \
  --oauth-authority PAYLOAD=SIGNATURE=PUBLIC_KEY \
  --drive-access-proof artifacts/drive-access-proof.v4.2.json \
  --acquisition-authorization PAYLOAD=SIGNATURE=PUBLIC_KEY \
  --acquisition-evidence RECEIPT=PRE_SOURCE_AUDIT=PRE_PROOF=POST_PROOF=AUTHORIZATION_GATE \
  --evaluated-at EVALUATED-AT \
  --output artifacts/phase0-gate.v4.2.json
```

Exit status 2 is blocked. Exit status 0 authorizes only the named acquisition or
transformation action. Every v4.2 report has `training_authorized: false`.

### Current reproducible boundary

`audit/phase0-gate.v4.2.blocked.json` is generated from the trusted roots,
publisher successor, pending policy, and fixed evaluation time. Its 54
structured blockers include the unapproved OAuth policy, missing signed
authority and same-resource proof, fresh publisher receipts, pinned evaluation
assets, rights approvals, materializations, custody anchors, quarantine, source
audit/bytes, acquisition evidence, inventories, and admissions. No OAuth
consent, Drive access or mutation, held-out-data access, human approval, sealing,
source acquisition, transformation, training, or push was performed while
implementing v4.2.

## Frozen v4 reference workflow

The following section documents the legacy v4 command path. It is retained for
reproducibility and must not be used for real authorization.

Validate the frozen contracts and exact migrations:

```bash
uv run hf-phase0 registry validate-v4 \
  --source-predecessor registries/sources.v2.json \
  --evaluation-predecessor registries/evaluations.v2.json \
  --instance registries/sources.v4.pending.json \
  --instance registries/evaluations.v4.json
```

The pending source registry deliberately has null stable Drive IDs and null
publisher statement URLs. It cannot pass the real gate. After independently
verifying every official statement URL, create a successor registry, then bind
one fresh exact-scope observation within 15 minutes:

```bash
uv run hf-phase0 storage bind-drive-v4 \
  --registry artifacts/sources.v4.publisher-pinned.json \
  --observation artifacts/drive-observation.v1.json \
  --registry-id hippocampus-foundation-sources-v4-drive-bound \
  --registry-output artifacts/sources.v4.drive-bound.json \
  --attestation-output artifacts/storage-attestation.v4.json \
  --verifier DRIVE-CUSTODIAN-ID \
  --bound-at OBSERVATION-BIND-TIME
```

Retain each official checksum statement as immutable evidence; this command
does not fetch it:

```bash
uv run hf-phase0 source publisher-receipt-v4 \
  --registry artifacts/sources.v4.drive-bound.json \
  --evidence-id REGISTERED-EVIDENCE-ID \
  --statement private/publisher/STATEMENT.txt \
  --resolved-url EXACT-SAME-HOST-HTTPS-URL \
  --retrieved-at RETRIEVED-AT \
  --verified-at VERIFIED-AT \
  --verifier PUBLISHER-EVIDENCE-REVIEWER \
  --output private/publisher/ARTIFACT.receipt.v4.json
```

Reassemble rights packets against the v4 entries before human review. The v4
evaluation role fields changed their subject hashes, so historical evaluation
assessments cannot be reused as approvals. The catalogue contains evidence
locations, not decisions.

Every private v4 envelope must include an unpredictable 64-hex-character
`commitment_nonce`. The nonce and private payload remain inside the encrypted
envelope. Seal outside the development environment:

```bash
uv run hf-phase0 seal create-v4 \
  --input private/envelopes/DATASET.v4.json \
  --output vault/DATASET.v4.gpg \
  --recipient OFFLINE-ENCRYPTION-KEY-FINGERPRINT \
  --receipt private/receipts/DATASET.v4.json \
  --contribution private/contributions/DATASET.v4.json \
  --evaluations artifacts/evaluations.v4.sealed.json \
  --custodian OFFLINE-CUSTODIAN-ID \
  --created-at CREATED-AT
```

The custodian creates the anchor object under
`schemas/phase0/v4/access-anchor.schema.json`, signs its RFC 8785 bytes with a
detached GPG signature, and supplies the public key. The signing-key fingerprint
must already be pinned in the evaluation registry. `gate-v4` accepts anchor
chains in sequence order as
`ANCHOR=SIGNATURE=PUBLIC_KEY=ACCESS_LOG`; the newest anchor must cover the full
log.

Compile every role's contribution, including development and diagnostics:

```bash
uv run hf-phase0 quarantine compile-v4 \
  --evaluations artifacts/evaluations.v4.sealed.json \
  --contribution private/contributions/DATASET.v4.json \
  --index-id public-evaluation-union-v4 \
  --output artifacts/public-quarantine-index.v4.json
```

Before creating any feature, derive a source descriptor and obtain a tri-state
decision:

```bash
uv run hf-phase0 quarantine descriptor-v4 \
  --input private/source-record.json \
  --output artifacts/source-record.descriptor.v4.json
uv run hf-phase0 quarantine check-v4 \
  --descriptor artifacts/source-record.descriptor.v4.json \
  --index artifacts/public-quarantine-index.v4.json \
  --checked-at CHECKED-AT \
  --output artifacts/source-record.quarantine.v4.json
```

Only `clear` permits later feature construction. `excluded` and `undetermined`
both exit with status 2. Descriptor input may contain source text, but the
output contains only hashes, identifiers, lineage state, and fingerprints.

Audit and inventory using one `--publisher STATEMENT=RECEIPT` option per
artifact:

```bash
uv run hf-phase0 source audit-v4 \
  --registry artifacts/sources.v4.drive-bound.json \
  --storage-attestation artifacts/storage-attestation.v4.json \
  --publisher private/publisher/STATEMENT.txt=private/publisher/ARTIFACT.receipt.v4.json \
  --evaluated-at EVALUATED-AT \
  --output artifacts/source-audit.v4.json

uv run hf-phase0 source count-v4 \
  --registry artifacts/sources.v4.drive-bound.json \
  --storage-attestation artifacts/storage-attestation.v4.json \
  --source-audit artifacts/source-audit.v4.json \
  --artifact-id ARTIFACT-ID \
  --publisher private/publisher/STATEMENT.txt=private/publisher/ARTIFACT.receipt.v4.json \
  --evaluated-at EVALUATED-AT \
  --output artifacts/inventory.ARTIFACT-ID.v4.json
```

Then issue one exact admission receipt per foundation source:

```bash
uv run hf-phase0 source assess-admission-v4 \
  --source-id SOURCE-ID \
  --registry artifacts/sources.v4.drive-bound.json \
  --evaluations artifacts/evaluations.v4.sealed.json \
  --storage-attestation artifacts/storage-attestation.v4.json \
  --source-audit artifacts/source-audit.v4.json \
  --licence-assessment private/licensing-v4/SOURCE-REVIEW/assessment.final.json \
  --licence-bundle private/licensing-v4/SOURCE-REVIEW/bundle.json \
  --publisher private/publisher/STATEMENT.txt=private/publisher/ARTIFACT.receipt.v4.json \
  --quarantine artifacts/public-quarantine-index.v4.json \
  --inventory artifacts/inventory.ARTIFACT-ID.v4.json \
  --assessor ACCOUNTABLE-ASSESSOR-ID \
  --assessed-at ASSESSED-AT \
  --output artifacts/admission.SOURCE-ID.v4.json
```

The complete gate uses both predecessor registries and repeats every evidence
option as required:

```bash
uv run hf-phase0 gate-v4 \
  --sources artifacts/sources.v4.drive-bound.json \
  --source-predecessor artifacts/sources.v4.publisher-pinned.json \
  --evaluations artifacts/evaluations.v4.sealed.json \
  --evaluation-predecessor registries/evaluations.v4.json \
  --drive-observation artifacts/drive-observation.v1.json \
  --storage-attestation artifacts/storage-attestation.v4.json \
  --publisher private/publisher/STATEMENT.txt=private/publisher/ARTIFACT.receipt.v4.json \
  --source-audit artifacts/source-audit.v4.json \
  --licence-assessment private/licensing-v4/REVIEW/assessment.final.json=private/licensing-v4/REVIEW/bundle.json \
  --seal-v4 vault/DATASET.v4.gpg=private/receipts/DATASET.v4.json \
  --anchor-v4 private/anchors/DATASET.json=private/anchors/DATASET.sig=private/anchors/CUSTODIAN.pub=private/DATASET.access.jsonl \
  --contribution private/contributions/DATASET.v4.json \
  --quarantine artifacts/public-quarantine-index.v4.json \
  --inventory artifacts/inventory.ARTIFACT-ID.v4.json \
  --admission artifacts/admission.SOURCE-ID.v4.json \
  --evaluated-at EVALUATED-AT \
  --output artifacts/phase0-gate.v4.json
```

Exit status 2 is blocked; 0 permits only the action named by the ready flag.
`source acquire-v4` consumes the acquisition flag and accepts no caller URL,
destination, size, or checksum. Re-audit after any download. No Phase 0 command
authorizes training.

## Frozen v3 reference workflow

All remaining sections reproduce v3 or earlier operational history. They are
retained to explain existing artifacts and are not part of the active v4.2
authorization path above.

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

Create exact-scope ADC first, then attempt native mounting in the same durable
session. Keep `colab drivemount` attached, approve the validated Google URL in
the browser, and press Enter once only after the browser shows its close-window
page. The keypress permits final propagation; require both the credential
status check and `Mounted at /content/drive` before continuing:

```bash
better-colab drive-auth authorize DRIVE-AUDIT-CPU \
  --oauth-config /PROTECTED/entor-internal-oauth.json
better-colab drive-auth status DRIVE-AUDIT-CPU --format json
colab drivemount --session DRIVE-AUDIT-CPU --read-only /content/drive
```

The corrected client performs one fresh-token/bodyless dry run and one
fresh-token/bodyless final propagation. It does not poll, reuse an XSRF token,
or send the obsolete multipart `file_id`. If native mounting fails, compare it
with the official browser flow on the same account before classifying the
failure as upstream.

The provider keeps exact-scope ADC at
`/dev/shm/better-colab/credentials/google-drive-readonly.json` in the tracked
kernel. Keep the installed-client file protected locally; do not commit it,
paste it into chat, or include it in logs. Set the legacy attestation only after
personally checking that the native mount and exact-scope ADC used the same
account:

```python
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
identity observation and supplied no resource IDs. A protected Desktop OAuth
client was supplied and validated on 2026-08-29, but it has not yet been used
for exact-scope user ADC or fallback execution. A
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
