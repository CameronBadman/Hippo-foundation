# Next milestone: execute the Phase 0 v4.1 evidence firewall

## Outcome

Produce a fresh, blocker-free Phase 0 v4.1 report that authorizes only the
registered foundation transformation. `training_authorized` must remain
`false`. The checked real-state report is correctly blocked; only synthetic
fixtures exercise the ready path.

## Implemented boundary

The repository now contains:

- all eight frozen Phase 0 v4 schemas with unchanged locks and behavior;
- two separately locked v4.1 schemas for execution evidence and the gate;
- trusted-root, gap-free source and evaluation lineage verification;
- a byte-preserving publisher-URL successor of the checked source root;
- private materialization manifests and redacted receipts derived by rehashing
  archives, adapters, and separate oracles and accounting for every unit,
  output, and dependency;
- pinned-entry rights and materialization requirements before confirmatory
  sealing, plus canonical anchor-payload construction;
- an evidence-reproduced final evaluation successor that keeps
  non-confirmatory entries pinned and moves only confirmatory entries to
  sealed custody;
- capture-rehashing catalogue rebinds that create only pending assessments;
- `gate-v4.1` and `source acquire-v4.1`, both consuming complete registry
  chains; and
- adversarial tests for alternate roots, skipped or reordered transitions,
  timestamp rollback, asset/key/seal/dependency mutation, unsafe or incomplete
  archives, public leakage, rights/custody misbinding, consumed logs, stale
  anchors, arbitrary blocker clearing, and missing evidence families.

The two official Wikimedia manifests were fetched into ignored research
storage and all seven registered SHA-1 rows matched. The public record in
`audit/publisher-manifest-research.v4.1.json` is explicitly research-only: the
transport was HTTPS and no detached publisher signature was verified. Final
statement bytes and receipts must be fetched after Drive binding.

No Drive authorization, human approval, held-out evaluation access, sealing,
large source acquisition, transformation, embedding, training, or evaluation
was performed while implementing this boundary.

## Better Colab prerequisite and resume plan (2026-08-25)

Phase 0 is paused before Drive binding while Better Colab is repaired in two
independently releasable changes. A live compatibility `colab auth` flow did
create valid user ADC in the runtime filesystem, but the later guarded command
attached to a different kernel because the automation path did not reuse or
persist the session's kernel and Jupyter session IDs. The tracked kernel then
fell back to compute metadata until the credential path was selected there.
This is a reproduced Better Colab kernel-affinity defect, not evidence that
Colab OAuth itself failed.

The credential produced by classic Colab auth is nevertheless unsuitable for
this gate: its observed Drive grant was broader than the one allowed
`https://www.googleapis.com/auth/drive.readonly` scope. The project must not
reinterpret a successful broad-scope login as exact-scope evidence, and it must
not copy Better Colab's host control-plane token into the runtime.

The dependency plan is:

1. **Release A — automation kernel affinity.** Make every automation command
   reuse stored kernel/session IDs, persist IDs discovered by reconnect, and
   retain them on success and failure. Lock this with regression, integration,
   package, and clean-wheel tests. This release is useful independently and
   must not alter OAuth scopes or credential selection.
2. **Release B — exact Drive read-only provider.** Add an explicit
   `drive-auth` command family and the compatibility route
   `colab auth --drive-read-only`. Obtain consent through a separately verified
   public OAuth application requesting the exact Drive read-only scope, perform
   token exchange inside the assigned runtime, keep credentials only in the
   runtime's protected volatile storage, bind them to the tracked kernel, and
   expose only redacted status. Development OAuth configuration may test the
   mechanism but cannot authorize Phase 0. Production release remains blocked
   until Google completes the required app verification and any applicable
   security assessment.

After both releases are installed, resume with one fresh disposable CPU
assignment. Authorize through the production provider, prove that ADC and the
read-only mount belong to the same dedicated Google Reader identity, run the
fixed-hash metadata-only identity probe in that same durable kernel, and bind
the observation within 15 minutes. Then fetch the two registered publisher
statements anew and create all seven receipts within the 72-hour window. Only
after that checkpoint may the evaluation-rights/materialization/custody DAG
continue. The roughly 102 GB source acquisition still requires a ready v4.1
acquisition report and separate explicit authorization; training remains
unauthorized.

## External execution order

### 1. Reconfirm publisher locations

Validate the trusted source root and checked publisher successor as one ordered
lineage. Recheck both official URLs immediately before execution; do not replace
the registered publisher SHA-1 with a locally computed digest.

### 2. Bind exact storage identity

After both Better Colab releases above are installed, use one disposable CPU
runtime to create exact `drive.readonly` user ADC through the production,
verified provider. Confirm that ADC and the read-only mount use the same
dedicated Google Reader identity, run the metadata-only identity probe in the
same durable kernel, and bind the observation within 15 minutes. Stable Drive
and folder IDs must be observed, not inferred. A development/test OAuth client
is non-authorizing; production provider approval is not currently available.

### 3. Capture fresh publisher receipts

After Drive binding, fetch and retain the exact Wikidata and enwiki manifest
bytes again. Create one receipt per registered artifact against the Drive-bound
source registry. Complete source audit and final access evidence must remain
inside their 72-hour freshness windows.

### 4. Pin every evaluation entry

For development and diagnostic roles, pin only the assets needed for their
declared non-confirmatory use. For the five confirmatory candidates, the
custodian must pin archives/adapters or implement and pin the private
first-party generators. Pin byte-distinct oracle artifacts, custodian keys,
seal IDs, and highest dependency units before any materialization. Validate the
complete root-to-pinned lineage.

### 5. Rebind rights evidence and obtain accountable decisions

Run `licence catalogue-rebind` from the verified capture root into a distinct
private output root, against the Drive-bound sources and pinned evaluation
entries. The generated assessments remain pending. An accountable human must
resolve or reject each finding and approve the complete declared use before
materialization or sealing. Existing assessments bound to another entry hash
cannot authorize the pinned entry.

### 6. Materialize evaluations under custody

For all seven entries, rehash and account for the exact archive, adapter,
oracle, envelope, records, primary units, and dependencies. Keep manifests and
envelopes private. Public receipts may expose only counts and digests. A
distinct oracle file/digest is a mechanical anti-alias check, not proof of
independent methodology; the custodian must review methodological independence
separately.

### 7. Seal and authenticate confirmatory custody

Seal the five confirmatory envelopes to their pinned keys, create the initial
materialization-bound `seal_created` events, construct canonical anchor bytes,
and obtain detached offline signatures. Verify full log coverage, signature and
key bindings, freshness, and the absence of any consumption event.

### 8. Finalize the evaluation registry once

Run `registry evaluations-finalize-v4.1` only after all rights,
materializations, seals, logs, and anchors exist. It must reproduce a single
pinned-to-final successor, preserve unrelated fields, clear only
evidence-backed blockers, leave non-confirmatory custody pinned, and timestamp
the registry after every supplied evidence event.

### 9. Build quarantine and audit source bytes

Compile exactly one contribution for every evaluation entry and review the
public selector set for unnecessary disclosure. Audit every registered
pre-existing source artifact through the bound storage identity with fresh
publisher receipts.

### 10. Acquire, re-audit, inventory, and admit

Only a v4.1 acquisition report with
`foundation_acquisition_authorized: true` may start the registered roughly
102 GB Wikidata download. The acquisition CLI accepts no URL, destination,
expected-size, or checksum override. Re-audit after acquisition, produce exact
structural inventories, and issue one admission receipt per foundation source.

### 11. Evaluate the final v4.1 gate

Pass every source registry from root to Drive-bound tip and every evaluation
registry from root through pinned to final, plus every retained evidence
artifact. A missing, stale, contradictory, exposed, future-dated, misbound, or
incomplete family must produce a structured blocker. Preserve and independently
rehash the resulting report and every referenced artifact.

## Verification checkpoints

- Frozen v2/v3/v4 schema digests and legacy behavior remain unchanged.
- A clean full test run, format/lint check, compile check, package build, and
  clean wheel-install smoke test pass.
- The synthetic complete graph reaches transformation readiness while training
  stays false; removing either trusted root or materialization blocks it.
- The checked real-state report reproduces exactly from committed inputs.
- No final answer, label, score, evaluator internal, threshold, or held-out
  content is used for feature design, source selection, admission, or blocker
  removal.

## Pause points

Stop for user-supplied authority at exact-scope OAuth, accountable rights
decisions, custodian-held evaluation material, offline signing, and real source
acquisition. Missing authority is a blocker, not permission to weaken or
simulate evidence. A later and separate authorization boundary is required
before any training.
