# Next milestone: activate and execute Phase 0 v4.2

## Outcome

Produce a fresh, blocker-free Phase 0 v4.2 report that authorizes only the
registered foundation transformation. `training_authorized` must remain
`false`. The checked real-state report is intentionally blocked; only synthetic
fixtures exercise the ready path.

## What is implemented

Phase 0 v4.2 is additive. It preserves the frozen v2/v3/v4 contracts, the two
frozen v4.1 contracts, and every legacy command. It adds four separately locked
contracts and these controls:

- a checked but deliberately unapproved Entor Workspace OAuth policy;
- a code-pinned policy root, currently `None`, so an unreviewed policy cannot
  authorize anything;
- exact-byte hashing of a protected installed-client JSON file without emitting
  its client ID or secret;
- detached signatures over the approved Internal Workspace project, exact
  client hashes, exact `drive.readonly` scope, stable shared-Drive/root IDs, and
  a canonical marker file;
- a live proof that checks the access token's exact scope and authorized OAuth
  client, verifies an Entor-domain Drive principal in memory, reads the same
  marker through both Drive API and DriveFS, pins the root directory descriptor,
  and repeats API identity checks to detect drift;
- a separate legacy storage observation and human same-account statement. The
  v4.2 observer does not manufacture that human claim;
- detached, per-artifact acquisition authority binding the registry entry,
  storage attestation, expected bytes, byte ceiling, and a validity window of at
  most 24 hours;
- rooted acquisition with no caller URL/path/size/checksum override, pre/post
  live proofs, a mechanically reproduced precondition gate, immutable
  promotion, and a resume sidecar bound to the exact signed authorization; and
- a direct v4.2 gate that retains the complete v4.1 evidence graph, adds the new
  evidence families, and never authorizes training.

The installed Better Colab build was read locally as
`0.1.dev103+ga8c1b68b5`. Its exact-scope provider writes the protected ADC shape
consumed by the v4.2 observer. Its `provider_mode=development` label is not used
as project authority: the separately reviewed and code-pinned v4.2 policy must
approve the exact client bytes and project before either development or
production mode can pass.

## What the successful broad mount proved

The user-run `colab drivemount` flow completed credential propagation and
reported `Mounted at /content/drive`. This is useful evidence that Better
Colab's interactive native-mount protocol works when the terminal remains open
until the user completes consent and presses Enter.

It is not v4.2 authorization. Classic DriveFS consent requests broader Drive
permissions, and that run did not bind an approved installed client, token
scope, authorized-party client, shared-Drive ID, root-folder ID, marker file,
or signed authority. The broad mount must not be converted into exact-scope
evidence after the fact.

## Why an Internal Workspace client is viable

Google classifies `drive.readonly` as a restricted scope and describes it as
permission to view and download all Drive files. Google also documents an
internal-use verification exception when the app is used only within one
Google Workspace or Cloud Identity organization, the project is owned by that
organization, and the OAuth audience is Internal. Administrator approval may
still be required, and all API/user-data policies still apply:

- [Google Drive scope classification](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Google OAuth verification exceptions](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- [Google Cloud internal-use summary](https://support.google.com/cloud/answer/13464323)

This repository has not verified that the intended Google Cloud project is
organization-owned or configured Internal. Those are external administrator
facts and remain blockers.

## External execution order

### 1. Approve and activate the non-secret policy

An Entor Workspace administrator must provide and review:

- the Workspace customer-ID hash;
- the organization-owned Cloud project number;
- confirmation that the OAuth audience is Internal;
- the OAuth-authority signing-key fingerprint;
- the acquisition-authority signing-key fingerprint; and
- the exact installed-client file SHA-256 and client-ID SHA-256.

Create an approved successor to
`policies/oauth-authority.v4.2.pending.json`, validate it, record the canonical
instance digest emitted by `registry validate-v4.2`, and set
`APPROVED_OAUTH_AUTHORITY_POLICY_SHA256` to that digest in a separate reviewed
activation commit. The policy contains no client secret, token, email address,
raw customer ID, or held-out data.

### 2. Create and place the root marker

Resolve the stable shared-Drive and direct lake-root folder IDs without
guessing from names. Generate the canonical marker locally:

```bash
uv run hf-phase0 storage marker-payload-v4.2 \
  --marker-id MARKER-UUID \
  --provider-resource-id SHARED-DRIVE-ID \
  --root-resource-id LAKE-ROOT-FOLDER-ID \
  --output private/drive/.entor-drive-identity-v1.json
```

The user or storage custodian uploads those exact bytes once as
`.entor-drive-identity-v1.json` directly beneath the lake root and records its
file ID and SHA-256. This is an authorized external Drive write; the v4.2
observer itself is read-only.

### 3. Sign the OAuth authority

Keep the approved installed-client file absolute, owner-owned, mode `0600`, and
outside Git. Build canonical authority bytes, sign them offline with the
policy-listed key, and verify the detached signature. The authority can last at
most 365 days and binds the exact policy, client bytes, project, resource IDs,
marker, scope, and approver.

### 4. Create exact-scope ADC and mount in one durable session

Allocate one disposable CPU session. Use Better Colab's exact-scope provider
with the protected approved client. Complete the browser consent as the intended
Entor account. Then run `colab drivemount --read-only` in the user's visible
terminal and leave it attached until the browser says to close the window;
return to that terminal and press Enter promptly so credential propagation can
finish.

The exact-scope ADC must remain at
`/dev/shm/better-colab/credentials/google-drive-readonly.json`, mode `0600`, in
the same durable kernel. Do not use the host control-plane token or classic
gcloud ADC as a substitute.

### 5. Produce both storage evidence families

Using the same ADC, session, mount, and account:

1. run the frozen storage/v1 observation with the explicit human
   same-account statement and bind its stable IDs into the source registry and
   storage attestation; and
2. run `storage observe-drive-v4.2` to independently prove the exact token
   client/scope and API-to-DriveFS marker equality.

Both observations are short-lived. Neither output contains an email address,
permission ID, client ID, token, refresh token, client secret, marker contents,
or evaluation content.

### 6. Complete the v4.1 evidence DAG

Fetch both official Wikimedia checksum statements again after Drive binding
and create all seven receipts inside the 72-hour window. Then, without opening
confirmatory item content in the development environment:

1. pin every evaluation archive, adapter/generator, independent oracle,
   dependency unit, custodian key, and seal ID;
2. rebind retained rights captures to the exact pinned entries;
3. obtain accountable human rights decisions;
4. materialize every evaluation under custody;
5. seal confirmatory envelopes and externally sign their canonical access-log
   anchors;
6. create the one evidence-backed final evaluation successor;
7. compile the complete quarantine union; and
8. audit all registered pre-existing source bytes.

### 7. Authorize and run each acquisition separately

Only after the v4.2 report says `foundation_acquisition_ready: true`, build one
canonical authorization payload per acquisition target. A policy-listed
authorizer reviews the exact artifact, byte count, and byte ceiling and signs
the payload offline. Verify the signature, then run only `source acquire-v4.2`.

The command uses runtime time rather than a caller-supplied evaluation time. It
rechecks the live Drive identity and recomputes the full authorization gate
before network transfer, retains an authorization-bound partial on interruption,
rechecks identity before atomic promotion, and emits the receipt, pre-source
audit, pre/post proofs, and exact authorization gate. An unbound or differently
authorized partial is rejected before contacting the publisher.

The roughly 102 GB Wikidata transfer is still a material external action. Do
not run it merely because the tooling exists; obtain the explicit artifact
signature and user approval at that point.

### 8. Re-audit, inventory, admit, and evaluate

Re-audit the acquired bytes, build structural inventories, and issue source
admission receipts. Evaluate `gate-v4.2` with the complete source/evaluation
lineages and every evidence family. Exit status 2 is blocked; exit status 0 can
authorize only the registered transformation. It never authorizes training.

## Current reproducible boundary

`audit/phase0-gate.v4.2.blocked.json` is mechanically regenerated from the
checked roots, publisher successor, pending policy, and a fixed evaluation
time. It has 54 structured blockers. Registry lineage and schema locks are
ready; OAuth policy/authority, live same-resource proof, fresh publisher
receipts, pinned evaluation assets, rights, materialization, custody,
quarantine, source audit/bytes, acquisition evidence, inventories, and
admissions are not.

No OAuth consent, Drive API or filesystem access, marker upload, human
approval, held-out-data read, sealing, acquisition, transformation, training,
or push was performed while implementing v4.2.

## Pause points

Stop for explicit external authority at policy activation, OAuth consent,
marker upload, human same-account observation, rights approval, held-out
materialization, offline signing, and each real source acquisition. Missing
authority is a blocker, not permission to simulate evidence. Training requires
a later, separately versioned authorization boundary.
