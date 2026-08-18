# Phase 0 v2 controls

The following rules are normative for the default Phase 0 implementation.
Historical v1 commands do not satisfy a v2 gate.

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
- Phase 1 data preparation may begin only from a ready, blocker-free Phase 0 v2
  transformation gate and its admitted quarantine index. A ready Phase 1 data
  gate still does not authorize training.
