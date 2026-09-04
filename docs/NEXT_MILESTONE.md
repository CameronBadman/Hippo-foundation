# Next milestone: run the preregistered local READ comparison

## Active status (2026-09-02)

The public-source and Phase 0 v4.4 path below is parked, not deleted. The active
milestone is the one-week, local-only READ experiment frozen in
[`experiments/read_run_v1/PREREGISTRATION.md`](../experiments/read_run_v1/PREREGISTRATION.md).
It tests the load-bearing traversal claim before spending time or authority on
external corpora.

Where it stands: E1 executed and is void (its γ=0 negative control failed; the
v1 holdout is spent); the E1-v2 overnight sequence stopped at gate G1 with no
v2 data generated; Amendment 10 is pending review; and the Amendment 10 γ sweep
ran on screening splits. The sweep's reading is in
[`experiments/read_run_v1/diagnostics/gamma_sweep_screening_report.md`](../experiments/read_run_v1/diagnostics/gamma_sweep_screening_report.md):
with the similarity field present TRAV is 99.47–100.00% exact at every γ, but
the generator's similarity field marks the on-path nodes at every γ, and with
it flattened every TRAV checkpoint is 53.56–69.13% route-complete against
87.90% for DIRECT's query-blind structural pool. What was learned is relation
discrimination on marked nodes; whether the frozen model can learn to navigate
from structure alone has never been tested, because every TRAV trained so far
had the marker from update 0.

Track N read band D, and Track O — the path-scoped rebuild it motivated — has now
run and read **band A, learned and dominant**
([`track_o_screening_report.md`](../experiments/track_o_v1/diagnostics/track_o_screening_report.md)).
Twelve runs, zero stderr, no harness defect, order of evidence verified. Every
TRAVV2 seed improved on both primary axes over its own untrained line and cleared
every model-free policy; the equal-capacity frozen v1 comparator reached 14.7–16.2%
route-completeness and failed the accuracy floors on every hard-cell seed. The
returned set — six of thirty-three examined edges at 89.3% precision, 88.1% recall
— is the strongest evidence that the read path's product should be a relevance set
rather than a route.

The optimisation pass ran (2.58x on identical work; the two-pass walk a further
1.35x) and Track P — the necessity experiment band A left open — has run and is
reported in
[`track_p_screening_report.md`](../experiments/track_p_v1/track_p_screening_report.md).
On generator v3 data with a planted distractor route, no budget and cost counted
in expansions, the learned walk registers both targets on 95.0–97.3% of hard-cell
episodes against the best hand-coded policy's 85.4%, and its supervised stop —
whose features carry no target constant — ties an oracle stop on every episode it
completes. Training bought ordering (beating similarity-following by ~0.45
expansions) and the stop bought ~2 more. Two seeds read band A, one C. Selective
return did not work (proof-validity 0.095–0.128), and the report's limitations
section carries what changes the reading: a tie-inflated cost rule, the answer
head's hard-coded 2, a weak discriminative signal in the generator, and a
screening subset on which a zero-parameter mask-agreement rule scores 0.929 while
scoring 0.000 off it.

**The active milestone is Track Q: selective return.** The edge head is at chance
on distractor-route edges and its loss has been flat since update 1,500, so
neither more training nor more data can move it; the identifying signal is a
route-set property the per-edge scorer cannot express. Track Q scores route sets
with a head that is explicitly not given the mask-agreement count, evaluates on
all gated episodes with the abstain split shown, and fixes γ for identifiability
by a rule written before any run. Its reference is the constant-free route-mean
decode at 0.243. By the standing branch rule, insert waits until the returned set
is a substrate worth bootstrapping from. E1-v2 stays recorded and not in force;
both holdout seeds remain sealed; Amendment 10 remains pending review.

## Parked public-source milestone

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
