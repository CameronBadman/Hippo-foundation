# Phase 0 controls

## Additive v4.3 public-source controls

Phase 0 v4.3 replaces the Drive-specific source execution route for the public
Hugging Face path; it does not alter or reinterpret any frozen v4, v4.1, or
v4.2 artifact. The following controls are normative for v4.3:

- Source and evaluation registries must reproduce as complete ordered v4.1
  chains from the checked roots. A supplied gate report is not evidence: the
  complete v4.1 graph is reopened and evaluated at each authority boundary.
- A staging root is absolute, owner-owned, mode-private, symlink-free, and
  identified by an immutable canonical marker. Evaluation, held-out, private,
  licensing, and seal path families are forbidden there.
- Staging acquisition authority is a detached, short-lived, per-artifact
  signature over the exact source entry, URL digest, publisher receipt,
  staging observation, evaluation-gate digest, expected bytes, checksum, and
  byte ceiling. The mutation command derives every transfer parameter from
  those bindings and uses runtime time.
- Acquisition, byte audit, structural inventory, publication clearance,
  publication, and admission form a digest-bound and causally ordered chain.
  Duplicate evidence, timestamp rollback, orphan outputs, missing artifacts,
  and changed local bytes fail closed.
- Public-source redistribution is a separate human decision. Acquisition,
  transformation rights, public upstream availability, or source admission
  cannot substitute for an assessment explicitly permitting
  `redistribute_source` and recording every applicable obligation.
- The Hugging Face endpoint, owner, dataset repository, public visibility,
  revision, baseline commit, controlled metadata, and seven artifact paths are
  code-pinned. Ambient credentials prove only the current principal and live
  write capability.
- Publication authorization is a second detached, short-lived signature over
  the exact clearance, rights, obligations, local bytes, deterministic 10-GiB
  reassembly manifest, and initial repository head. No CLI option may override
  endpoint, repository, remote path, local path, size, checksum, token, or
  decision time during upload.
- Immediately before its first write, publication rechecks the authenticated
  owner, anonymous visibility, exact head, and complete remote layout. Every
  upload uses the previous commit as its optimistic parent, the canonical
  manifest is last, and completion requires anonymous size and SHA-256 checks
  with no missing or extra remote paths.
- A prior publication receipt advances destination lineage only when paired
  with its exact signed manifest and verified detached authorization.
  Unknown-outcome recovery is
  read-only, is bound to the signed manifest and clearance, and accepts only a
  start time inside the original authorization window.
- Evaluation/private material is never a publication artifact. Phase 0 v4.3
  may authorize the registered foundation transformation only after exact
  publication and source admission; `training_authorized` is always false.

## Active v4 additions

The v2 controls below remain frozen historical requirements. Phase 0 v4 adds
the following normative controls and does not infer readiness from a v2 or v3
gate report:

- Source and evaluation registries carry exact predecessor hashes. Historical
  source entries cannot be rewritten, development partitions cannot be
  relabelled confirmatory, exposed sets remain diagnostic or retired, exposure
  history is append-only, and custody cannot move backwards.
- A storage attestation must bind the complete fresh storage/v1 observation,
  including exact `drive.readonly` scope, same-account attestation, permission
  identity digest, stable resource IDs, and all six positive checks.
- Every artifact requires a retained publisher checksum statement, exact target
  row, same-host HTTPS resolution, statement digest and byte count, and a fresh
  verification receipt. A null statement URL is an explicit blocker.
- Every private evaluation envelope contains an unpredictable 256-bit
  commitment nonce. Public commitments bind that private envelope without
  publishing the nonce or private payload; validator errors may not echo a
  rejected private instance.
- Confirmatory custody requires the exact ciphertext receipt, a non-consuming
  hash-chained access log, and a fresh detached GPG signature from the signing
  key fingerprint pinned in the evaluation registry. A self-asserted local log
  head is not an independent anchor.
- The v4 matcher makes exact identifier, dependency-family, raw-hash,
  normalized-hash, and exact-Jaccard near-match decisions before any feature or
  embedding. Incomplete lineage or absent selectors is `undetermined`, never
  `clear`.
- Contribution counts are derived from their constituent records. A serialized
  quarantine decision is accepted only when the matcher reproduces the complete
  receipt from its bound descriptor and union index.
- Gate blockers and evidence bindings are structured records. Acquisition and
  transformation are separate flags; both remain distinct from training, which
  is always false.
- Frozen Phase 1 v2 cannot consume a v4 report. A Phase 1 v3 consumer must be
  additive and bind v4 evidence without relabelling it as an older gate.

## Frozen v2 controls

The following rules remain normative for the historical Phase 0 v2
implementation. Historical v1 commands do not satisfy a v2 gate.

- Raw artifacts are immutable. Downloads use a `.partial` sibling and are
  promoted atomically only after registered size and checksum verification.
- A local path or familiar folder name is not storage identity evidence. The
  shared-Drive ID, root-folder ID, mounted root, observation method, and time
  must match a fresh authenticated storage attestation. Attestations and source
  audits expire for gate purposes after 72 hours.
- Stable provider IDs must be observed, never inferred or fabricated. Null IDs
  in the source registry keep the gate blocked.
- A registry checksum marked `verified` is only a frozen pin assertion. The
  underlying publisher checksum artifact and the method/date of verification
  must be preserved and rechecked before acquisition.
- Licence decisions are human decisions bound to the SHA-256 of exact terms
  bytes. A changed or missing terms snapshot, missing intended use, ambiguous
  decision, or non-matching subject blocks the gate.
- Evaluation archives, adapters or generators, and every source dependency they
  expose are frozen and quarantined before any source transformation, feature,
  embedding, hard-negative, or neighbourhood construction.
- Confirmatory labels, answers, split membership, and private-transfer material
  remain GPG-encrypted under a custodian-held offline private key. Development
  and Colab environments may hold only the public key.
- Each public quarantine contribution is derived from the exact private
  evaluation envelope that is sealed. The gate requires one independently
  verified ciphertext/receipt/contribution tuple for every declared evaluation
  and recomputes the public union.
- The public quarantine union is one-way: identifiers, exact hashes, normalized
  hashes, and text fingerprints only. It contains no labels, answers, split
  membership, or private payload.
- MinHash sketches are bounded to the RFC 8785 safe-integer domain. Approximate
  matches may rank candidates only; exact comparison over the declared shingle
  hashes must decide exclusion at the registered threshold.
- The current v2 CLI compiles and binds quarantine fingerprints but does not yet
  expose a v2 record matcher. No transformer may emit
  `quarantine_decision: clear` until that matching step is implemented and
  independently tested.
- Missing descriptor or dependency evidence yields `undetermined` or a blocker,
  never `clear`.
- Source auditing hashes registered raw bytes, detects mutation during the read,
  and requires complete registry coverage. A missing acquisition target may be
  reported missing, but every `preexisting` artifact must verify before
  acquisition authorization.
- Foundation acquisition is a separate mechanical sub-gate. Its command accepts
  a registered artifact ID, never caller-supplied URL, destination, size, or
  checksum.
- Every admitted source is bound to the exact registry, audited rows, storage
  attestation, human licence review, structural inventories, and public
  quarantine index.
- Public and private-transfer readiness are separate. Lack of authorized private
  data cannot be represented as success.
- The final test set is not used for feature design, preprocessing, model or
  prompt selection, early stopping, threshold selection, qualitative iteration,
  or negative mining.
- Phase 0 has no training command, model dependency, optimization loop, or
  permission to train. Its gate always emits `training_authorized: false`.
- Historical Phase 1 v1 data preparation may begin only from its ready,
  blocker-free Phase 0 v2 transformation gate and admitted quarantine index.
  Frozen Phase 1 v2 instead requires its exact Phase 0 v3 predecessor. Neither
  consumes v4, and no Phase 1 data gate authorizes training.
