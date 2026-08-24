# Next milestone: complete the external evidence firewall

## Outcome

Make foundation-data transformation mechanically possible only after storage
identity, publisher bytes, rights decisions, evaluation quarantine, structural
inventory, and admission evidence all bind to the same exact artifacts.

The target is a fresh Phase 0 v3 transformation report whose evidence checks
are ready while `training_authorized` remains `false`. This milestone does not
train a model, create embeddings, tune thresholds, inspect held-out items in the
development environment, or admit data through a documentation-only claim.

## Why this is next

The two local Phase 2 semantic slices are now reproducible and isolated. The
actual programme bottleneck is external evidence: current Phase 0 and Phase 1
gates remain blocked, rights assessments are pending, confirmatory envelopes
are unsealed, stable Drive resource IDs are absent, and registered source bytes
have not been audited and admitted.

## Decision definition

- Decision: may a registered source artifact enter foundation transformation?
- Unit: one exact source artifact at one registered publisher version and one
  stable storage resource identity.
- Information allowed: publisher metadata and checksums, byte observations,
  accountable rights assessments, public quarantine selectors derived under
  custody, structural inventories, and exact registry/gate bindings.
- Split unit: the highest available document, work, entity, page/revision,
  story, contract, paper, generator, world, seed-family, or time dependency.
- Principal error: transforming bytes that overlap confirmation data, lack
  sufficient rights, come from the wrong storage identity, or changed after
  review.

## Ordered work plan

### 1. Bind exact read-only storage identity

Use a disposable CPU runtime and the already verified native read-only Drive
mount path. Create exact `drive.readonly` user ADC in that runtime with an
approved protected desktop OAuth client, explicitly attest that the ADC and
mount refer to the same account, and run the identity probe within its 15-minute
binding window.

Create a new source-registry version and storage attestation containing the
stable shared-Drive and root-folder resource IDs. Do not infer IDs from names,
paths, a different connector account, or historical mount evidence. Use the
pinned rclone fallback only if native mounting fails and all fallback identity
preconditions remain satisfied.

### 2. Finish accountable rights review

Give the 10 digest-bound evidence packets to an accountable human reviewer.
Each assessment must explicitly approve, reject, or retain pending status for
the declared use, commercial compatibility, transformation, source/derived
redistribution, and model-output implications.

Code may validate and bind a decision but may not manufacture one. Rejected or
incompatible sources must retire; pending assessments continue to block
admission.

### 3. Capture remaining publisher byte evidence

Bind publisher checksum artifacts and verification receipts for every
registered source byte target. Preserve the distinction between an observed
publisher statement and a locally rehashed archive. Any mismatch, missing pin,
mutable URL, or stale evidence blocks acquisition or admission.

### 4. Correct evaluation roles before sealing

Version the evaluation registry so development, diagnostic, retired, and
confirmatory roles are explicit. Keep SocialIQA validation in development.
Keep the exposed EvidenceBench partition diagnostic or retired. Do not recover
confirmation status by renaming or encrypting a partition already used for
development decisions.

Freeze dependency closure before any source transformation. The registry must
name the document/work/entity/story/contract/paper/time and procedural-family
selectors that a custodian must cover.

### 5. Build the custodied confirmation boundary

Pin every public adapter and implement the two private first-party generators
outside the development environment. Derive each public quarantine
contribution from the same exact envelope that is encrypted to the custodian's
offline key. Create one schema-valid hash-chained access log per seal and bind
its head to an independently supplied anchor.

Do not disclose labels, answers, hidden spans, private worlds, seeds, result
reports, or evaluator internals. A consumed, tuned-on, or decision-influencing
holdout must retire rather than being represented as clean.

### 6. Compile and exercise the complete quarantine union

Compile all valid contributions into one public union. Add the missing
record-matching path so raw and normalized hashes, exact identifiers, and
approved near-match fingerprints are checked before graph features,
embeddings, neighbourhoods, negatives, or sampling are produced.

Test exact, normalized, related-entity, family, near-match, malformed,
ambiguous, and mutation cases. A record with incomplete dependency lineage is
not equivalent to a clear record.

### 7. Audit, inventory, and admit source bytes

Reopen bytes through the bound read-only identity, verify publisher pins,
detect read-time mutation, and produce structural inventories that bind the
same artifact hashes. Issue an admission receipt only when storage, rights,
source audit, inventory, and complete quarantine evidence agree exactly.

Generate a fresh Phase 0 v3 gate report from those records. Only then may the
raw-source-to-graph fixture path be implemented or executed on admitted bytes.
Training remains behind a later, separate authorization boundary.

## Verification matrix

- Every schema lock and pre-existing regression remains green.
- Registry versions preserve historical records and reject role laundering.
- Every evidence digest rehashes to a checked artifact; detached placeholder
  hashes are rejected.
- Storage attestation fails on wrong account, broad scope, unstable IDs,
  expired observation, writable mount evidence, or registry mismatch.
- Seals fail on missing dependency closure, ciphertext mismatch, missing log,
  missing independent anchor, or consuming/tuning events.
- Quarantine matching happens before any derived feature and rejects exact,
  normalized, identifier, and threshold-qualified near matches.
- Admission fails on any stale, missing, contradictory, or mismatched evidence.
- Current gate artifacts and every newly produced artifact retain
  `training_authorized: false`.

## Required external inputs and pause points

The exact-scope Drive observation requires a user-supplied approved desktop
OAuth client and interactive authorization. Rights approval requires an
accountable human reviewer. Offline encryption and independent log anchoring
require the designated custodian. Stop at each of those boundaries rather than
substituting guessed identity, automated legal approval, development-held
private material, or a self-asserted anchor.

## Exit criteria

Exit only when a clean rerun from exact bytes produces:

1. a bound storage identity and fresh source audit;
2. non-pending accountable rights decisions for every admitted subject;
3. verified publisher pins and structural inventories;
4. correctly role-classified evaluation records;
5. dependency-complete seals, access logs, and independent anchors;
6. the complete public quarantine union and pre-feature match evidence;
7. admission receipts binding all of the above; and
8. a Phase 0 v3 transformation report that is ready while training remains
   unauthorized.

If any dependency is missing, contradictory, exposed, or not independently
rehashable, the honest outcome is a blocked gate, not a weakened acceptance
criterion.
