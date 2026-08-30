# Next milestone: execute the public-source path through Hugging Face

## Outcome

Produce a blocker-free Phase 0 v4.3 report for the registered public-source
transformation boundary. The workflow stages and independently audits the exact
publisher bytes, satisfies the evaluation quarantine boundary first, publishes
only approved public source artifacts to the pinned public Hugging Face dataset,
and then admits those exact artifacts. `training_authorized` remains `false`.

This milestone does not require Google Drive. It also does not authorize model
training, transformation before admission, access to confirmatory plaintext in
the development environment, or publication of evaluation/licensing/private
artifacts.

## Current verified boundary

The configured destination is `Kyriah/hippocampus-foundation`, repository type
`dataset`, revision `main`, at baseline commit
`efeed3dd9fc85dc1ec6e2991e2aaae51e6f3d347`. A live authenticated and anonymous
observation on 2026-08-30 found exactly `.gitattributes`, `README.md`, and
`planned-publication.v1.json`. The two controlled metadata files matched their
pinned SHA-256 values. No corpus payload was present or uploaded.

The checked evidence is:

- `audit/hf-destination-observation.v1.json` — the bounded live observation;
- `audit/publication-gate.v1.blocked.json` — destination ready, five publication
  evidence families absent; and
- `audit/phase0-gate.v4.3.blocked.json` — both trusted registry lineages ready,
  with evaluation, staging, audit, publication, and admission still blocked.

The source registry contains seven artifacts totaling 141,447,172,673 bytes
(131.73 GiB). The deterministic publication plan produces 18 payload parts no
larger than exactly 10 GiB plus seven canonical reassembly manifests. These are
planning facts derived from registered sizes, not evidence that any source byte
has been acquired.

Both new authority policies remain deliberately pending, with empty signer
allowlists. Their code roots remain unset. A local edit that merely changes
`pending` to `approved` cannot pass either verifier.

## What v4.3 adds

Phase 0 v4.3 and publication v1 are additive. All frozen v4/v4.1/v4.2 schemas
and legacy commands remain unchanged.

The staging layer creates a private owner-only root with a canonical identity
marker, rejects links and evaluation/private path families, inventories exact
files, and never accepts a caller-supplied URL, destination, size, checksum, or
decision time for acquisition. A detached per-artifact signature binds the
rooted source registry, fresh publisher evidence, an independently reproduced
v4.1 evaluation graph, staging identity, expected bytes, checksum, and ceiling.
Downloads remain resumable only through the existing authorization-bound
sidecar and are promoted after exact publisher checksum verification.

The publication layer pins the Hub endpoint, owner, repository, revision,
visibility, baseline commit, metadata, and all seven destination paths. It
requires a separate signed human redistribution assessment and complete
obligation evidence. Every artifact is deterministically inventoried into
10-GiB parts before a second detached signature binds its exact manifest,
clearance, local digests, and initial Hub head. Immediately before mutation the
tool rechecks the authenticated owner, anonymous visibility, head, and complete
file layout. Each upload uses optimistic parent-commit locking; the manifest is
uploaded last; anonymous size and SHA-256 verification is required before a
receipt is emitted. Unknown-outcome recovery is read-only and accepts only the
signed manifest and a start time inside the original authorization window.

Prior publication receipts cannot advance the trusted Hub head by themselves.
Every retained receipt must be paired with the exact deterministic manifest and
the detached signed authorization whose canonical receipt digest it names.

## External execution order

### 1. Pin every evaluation asset and key

Create one v4.1 pinned evaluation successor containing exact archives,
adapters/generators, independent oracles, dependency units, custodian public
keys, and seal IDs. Validate the complete chain from the checked evaluation
root. Do not open confirmatory item content in the development environment.

### 2. Complete accountable rights review

Rebind the retained source and evaluation licence captures to the exact pinned
entries. Accountable reviewers must resolve or reject every blocking finding.
The existing pending assessments are scaffolds, not approvals.

Separately create and review publication rights packets for the two source
entries. They must explicitly allow the exact set `acquire`, `inventory`,
`quarantine`, and `redistribute_source`; record every applicable notice,
attribution, share-alike, privacy, access-term, and takedown obligation; and
explicitly exclude transformation/training uses from this publication-only
authority. Legacy transformation rights remain an independent prerequisite.

### 3. Materialize, seal, anchor, finalize, and quarantine

Under custodian control:

1. independently rehash each archive, adapter, oracle, and dependency;
2. materialize complete primary-unit coverage without public item leakage;
3. seal each confirmatory envelope to the pinned custodian key;
4. build canonical access-log anchor payloads and sign them externally;
5. create the single evidence-backed final evaluation successor; and
6. compile and verify the complete public quarantine union and matcher.

The final evaluation timestamp must follow every review, materialization, seal,
log event, and anchor. No source acquisition begins until the mechanically
reproduced evaluation-side prerequisites pass.

### 4. Refresh publisher evidence

Fetch the official Wikidata and English Wikipedia checksum statements again.
Create all seven publisher receipts against the checked publisher-pinned source
registry. Treat the current research copies as stale; acquisition and
clearance require receipts inside their registered freshness windows.

### 5. Approve the two non-secret authority policies

An accountable authority selects separate OpenPGP fingerprints for staging
acquisition, redistribution review, and Hub publication as required by policy.
Create reviewed approved successors to:

- `policies/staging-acquisition.v4.3.pending.json`; and
- `policies/hf-publication-authority.v1.pending.json`.

Validate their canonical digests, then pin those exact digests in a separate
reviewed activation commit. The policies contain no tokens, private keys,
emails, held-out content, or raw credentials. Activation does not itself sign
an artifact or authorize acquisition/publication.

### 6. Initialize and observe public-only staging

Run `source staging-init-v4.3` on storage with at least the registered bytes,
working-part overhead, and safety margin. Keep the root owner-only. Re-observe
it immediately before each signed acquisition. Never place evaluation archives,
rights bundles, keys, signatures, seal material, or debugging output beneath
that root.

### 7. Authorize and acquire each artifact

For each registered artifact, reproduce the complete source/evaluation graph,
build the canonical `source authorization-payload-v4.3`, review its exact byte
count and ceiling, sign it with the policy-listed key, and verify the detached
signature. Run only `source acquire-v4.3` while the authorization and publisher
receipt are fresh.

The roughly 102.35-GB Wikidata artifact is a material external transfer and
requires explicit user approval at that point even after its mechanical gate
passes. An interrupted, correctly bound partial may resume; an unbound or
differently authorized partial fails before publisher access.

### 8. Re-observe, audit, and count

After every transfer, create a fresh exact staging observation, run
`source audit-v4.3`, and then `source count-v4.3`. The audit independently
rehashes bytes; the structural counter must cover the registered format with
zero parse errors and zero rejected records. Evidence timestamps must follow
acquisition in causal order.

### 9. Implement obligations and issue artifact clearance

Place required public notices in the pinned metadata files or provide bounded
operational-control evidence. Build `publication obligations-v1`, then
`source clearance-v4.3` for each artifact. Clearance reproduces the evaluation
gate and binds the exact audit, inventory, publisher receipt, redistribution
rights, obligations, and quarantine index. It authorizes neither transformation
nor training.

### 10. Inventory, sign, and publish one artifact at a time

Run `publication inventory-v1` to hash the deterministic part plan. Build and
externally sign `publication authorization-payload-v1`; then verify it. Only
`publication upload-v1` may mutate the Hub repository.

Publish one artifact at a time. Retain its manifest, receipt, and signed
authorization, then run a new `publication observe-v1` with the complete ordered
prior receipt/manifest/signed-authorization chain before authorizing the next
artifact. Do not parallelize uploads: each artifact's initial head must equal
the previous receipt's final head.

If the client loses the response after dispatch, do not replay blindly. Run
`publication recover-v1`; it performs no upload and succeeds only if every
authorized part and the canonical manifest are anonymously visible with exact
digests and no extra file.

### 11. Admit sources and evaluate the final gate

After all artifacts for one source have complete publication receipts, run
`source admission-v4.3`. Then reproduce `publication-gate-v1` per artifact and
the complete `gate-v4.3` graph. A ready v4.3 report authorizes only the
registered foundation transformation. It does not authorize training, and the
frozen Phase 1 v2 consumer still cannot consume a v4.3 gate; that requires a
separately versioned Phase 1 input contract.

## Pause points

Stop for explicit external authority at human rights decisions, custodian
materialization, seal/anchor signing, policy activation, every acquisition
signature, the large Wikidata transfer, every publication signature, and any
cleanup of an unknown or partial remote outcome. Hugging Face ambient login is
only identity/write-capability evidence; it is never publication authority.
