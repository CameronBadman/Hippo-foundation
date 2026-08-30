"""Rooted non-Drive staging, acquisition, audit, inventory, and admission.

The functions in this module never infer authority from ambient credentials.  Every
network mutation is downstream of a short-lived, signed, artifact-specific receipt.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .acquisition import download_resumable_at
from .canonical import canonical_bytes, canonical_sha256, sha256_bytes
from .errors import IntegrityError, ValidationError
from .evaluation_firewall import validate_source_registry_v4
from .execution_v4_1 import VerifiedRegistryLineage, validate_registry_lineage_v4_1
from .external_evidence import VerifiedPublisherReceipt
from .inventory import hash_file, stream_count
from .publication_v1 import VerifiedPublicationRights
from .publication_v1_contracts import validate_publication_v1
from .v4_1 import evaluate_gate_v4_1
from .v4_1_contracts import validate_v4_1
from .v4_3_contracts import validate_schema_lock_v4_3, validate_v4_3
from .v4_contracts import validate_v4

MARKER_FILENAME = ".entor-public-staging-v4.3.json"
MAXIMUM_MARKER_BYTES = 16 * 1024
SCHEMA_VERSION = "4.3.0"

# Deliberately unset until an accountable authority approves and signs a policy.
APPROVED_STAGING_AUTHORITY_POLICY_SHA256: str | None = None

SignatureVerifier = Callable[[bytes, bytes, bytes, str], str]
STAGING_OBSERVATION_MAX_AGE = timedelta(hours=72)


@dataclass(frozen=True)
class VerifiedStagingAuthorization:
    payload: dict[str, Any]
    receipt: dict[str, Any]
    sha256: str
    signature_sha256: str
    public_key_sha256: str
    signing_key_fingerprint: str


@dataclass(frozen=True)
class VerifiedEvaluationGate:
    gate: dict[str, Any]
    sha256: str


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _artifact_lookup(
    registry: Mapping[str, Any], artifact_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [
        (source, artifact)
        for source in registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == artifact_id
    ]
    if len(matches) != 1:
        raise ValidationError(f"artifact_id must resolve exactly once: {artifact_id}")
    return matches[0]


def _publisher_sha1(artifact: Mapping[str, Any]) -> str:
    values = [
        item["value"].casefold()
        for item in artifact["checksums"]
        if item["origin"] == "publisher" and item["algorithm"] == "sha1"
    ]
    if len(values) != 1:
        raise ValidationError("artifact must have exactly one publisher SHA-1")
    return values[0]


def _require_safe_relative(path: str) -> PurePosixPath:
    relative = PurePosixPath(path)
    if (
        not path
        or relative.is_absolute()
        or relative.as_posix() != path
        or "\\" in path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValidationError("artifact path must be a safe relative POSIX path")
    return relative


def _assert_no_symlink_path(path: Path) -> os.stat_result:
    if not path.is_absolute():
        raise ValidationError("staging path must be absolute")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ValidationError("staging path is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError("staging path symlinks are forbidden")
    return path.stat()


def _assert_private_root(root: Path) -> os.stat_result:
    if not root.is_absolute():
        raise ValidationError("staging root must be absolute")
    metadata = _assert_no_symlink_path(root)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValidationError("staging root is not a directory")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise ValidationError("staging root must be private and owned by this user")
    return metadata


def init_staging_root(
    root: Path, *, observation_id: str, created_at: str | None = None
) -> dict[str, Any]:
    """Create an empty, private staging root and its immutable identity marker."""

    root = Path(os.path.abspath(root))
    _parse_time(created_at or _utc_now(), "created_at")
    if root.exists():
        _assert_private_root(root)
        try:
            if next(root.iterdir(), None) is not None:
                raise ValidationError("refusing to initialize a non-empty staging root")
        except OSError as exc:
            raise ValidationError("cannot inspect staging root") from exc
    else:
        parent = root.parent
        parent_metadata = _assert_no_symlink_path(parent)
        if not stat.S_ISDIR(parent_metadata.st_mode):
            raise ValidationError("staging-root parent is not a directory")
        try:
            root.mkdir(mode=0o700)
        except OSError as exc:
            raise ValidationError("cannot create staging root") from exc
    marker = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "public_source_staging_marker",
        "observation_id": observation_id,
        "created_at": created_at or _utc_now(),
        "root_path_sha256": sha256_bytes(str(root).encode("utf-8")),
        "contains_evaluation_content": False,
        "training_authorized": False,
    }
    encoded = canonical_bytes(marker)
    if len(encoded) > MAXIMUM_MARKER_BYTES:
        raise ValidationError("staging marker exceeds its size limit")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root / MARKER_FILENAME, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValidationError("cannot create staging identity marker") from exc
    return observe_staging_root(
        root, observation_id=observation_id, observed_at=created_at or _utc_now()
    )


def _is_sensitive_path(relative: PurePosixPath) -> bool:
    forbidden = {
        "evaluation",
        "evaluations",
        "eval",
        "heldout",
        "held-out",
        "holdout",
        "private",
        "seals",
        "licensing",
    }
    return any(part.casefold() in forbidden for part in relative.parts)


def _inventory_kind(relative: PurePosixPath) -> str:
    name = relative.name
    if relative.as_posix() == MARKER_FILENAME:
        return "marker"
    if name.endswith(".partial.authorization.json"):
        return "resume_binding"
    if name.endswith(".partial"):
        return "partial"
    return "artifact"


def observe_staging_root(
    root: Path, *, observation_id: str, observed_at: str | None = None
) -> dict[str, Any]:
    """Re-hash an exact rooted inventory without following links."""

    observed_at = observed_at or _utc_now()
    _parse_time(observed_at, "observed_at")
    root = Path(os.path.abspath(root))
    before = _assert_private_root(root)
    marker_path = root / MARKER_FILENAME
    try:
        marker_metadata = marker_path.lstat()
    except OSError as exc:
        raise ValidationError("staging identity marker is unavailable") from exc
    if (
        not stat.S_ISREG(marker_metadata.st_mode)
        or marker_metadata.st_uid != os.geteuid()
        or marker_metadata.st_mode & 0o077
        or marker_metadata.st_size <= 0
        or marker_metadata.st_size > MAXIMUM_MARKER_BYTES
    ):
        raise ValidationError("staging identity marker is not a private regular file")

    rows: list[dict[str, Any]] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in names:
            if (directory_path / name).is_symlink():
                raise IntegrityError("symlinks are forbidden in the staging root")
        for name in filenames:
            path = directory_path / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if _is_sensitive_path(relative):
                raise IntegrityError("evaluation or private content is forbidden")
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise IntegrityError("only regular files are allowed in staging")
            measured = hash_file(path)
            rows.append(
                {
                    "path": relative.as_posix(),
                    "kind": _inventory_kind(relative),
                    "bytes": measured["bytes"],
                    "sha256": f"sha256:{measured['sha256']}",
                }
            )
    rows.sort(key=lambda row: row["path"])
    marker_rows = [row for row in rows if row["kind"] == "marker"]
    if len(marker_rows) != 1:
        raise IntegrityError("staging root must contain exactly one identity marker")
    after = _assert_private_root(root)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise IntegrityError("staging root changed during observation")
    file_system = os.statvfs(root)
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "staging_observation",
        "observation_id": observation_id,
        "observed_at": observed_at,
        "root_path": str(root),
        "root_path_sha256": sha256_bytes(str(root).encode("utf-8")),
        "marker_sha256": marker_rows[0]["sha256"],
        "device": str(before.st_dev),
        "inode": str(before.st_ino),
        "available_bytes": file_system.f_bavail * file_system.f_frsize,
        "inventory": rows,
        "contains_evaluation_content": False,
        "training_authorized": False,
    }
    validate_v4_3(result, "execution-evidence.schema.json")
    return result


def validate_staging_observation(observation: Mapping[str, Any]) -> None:
    validate_v4_3(observation, "execution-evidence.schema.json")
    if observation["record_kind"] != "staging_observation":
        raise ValidationError("expected a staging observation")
    paths = [row["path"] for row in observation["inventory"]]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValidationError("staging inventory paths are not unique and sorted")
    markers = [row for row in observation["inventory"] if row["kind"] == "marker"]
    if len(markers) != 1 or markers[0]["path"] != MARKER_FILENAME:
        raise ValidationError("staging observation marker inventory is invalid")
    if markers[0]["sha256"] != observation["marker_sha256"]:
        raise ValidationError("staging marker digest binding mismatch")
    expected_root = sha256_bytes(observation["root_path"].encode("utf-8"))
    if observation["root_path_sha256"] != expected_root:
        raise ValidationError("staging root path digest mismatch")


def validate_staging_authority_policy(
    policy: dict[str, Any], *, approved_policy_sha256: str | None = None
) -> str:
    validate_v4_3(policy, "authority-policy.schema.json")
    observed = canonical_sha256(policy)
    expected = (
        APPROVED_STAGING_AUTHORITY_POLICY_SHA256
        if approved_policy_sha256 is None
        else approved_policy_sha256
    )
    if expected is None:
        raise ValidationError("approved staging authority policy is unavailable")
    if observed != expected:
        raise IntegrityError("staging authority policy does not match its root")
    if policy["status"] != "approved":
        raise ValidationError("staging authority policy is not approved")
    if not policy["acquisition_signing_key_fingerprints"]:
        raise ValidationError("staging authority policy has no trusted authorizer")
    return observed


def reproduce_evaluation_gate_v4_1(**graph: Any) -> VerifiedEvaluationGate:
    """Mechanically evaluate the full v4.1 graph and bind the result."""

    gate = evaluate_gate_v4_1(**graph)
    validate_v4_1(gate, "gate.schema.json")
    return VerifiedEvaluationGate(gate=gate, sha256=canonical_sha256(gate))


def validate_evaluation_side_ready(
    verified_gate: VerifiedEvaluationGate, *, evaluated_at: str | None = None
) -> None:
    """Require the independent evaluation DAG, without creating a source loop."""

    gate = verified_gate.gate
    validate_v4_1(gate, "gate.schema.json")
    if verified_gate.sha256 != canonical_sha256(gate):
        raise ValidationError("evaluation gate wrapper digest mismatch")
    required = (
        "contracts_frozen",
        "registry_lineage_ready",
        "evaluation_registry_ready",
        "evaluation_roles_ready",
        "evaluation_materialization_ready",
        "licensing_evidence_verified",
        "licensing_ready",
        "confirmatory_custody_ready",
        "quarantine_ready",
        "quarantine_matcher_ready",
    )
    missing = [field for field in required if not gate[field]]
    if missing:
        raise ValidationError(
            "evaluation-side prerequisites are not ready: " + ", ".join(missing)
        )
    if evaluated_at is not None:
        now = _parse_time(evaluated_at, "evaluated_at")
        observed = _parse_time(gate["evaluated_at"], "evaluation gate evaluated_at")
        if observed > now or now - observed > timedelta(hours=72):
            raise ValidationError("evaluation gate is stale or from the future")


def make_staging_authorization_payload(
    *,
    policy: dict[str, Any],
    approved_policy_sha256: str,
    source_registry: dict[str, Any],
    artifact_id: str,
    publisher_receipt: VerifiedPublisherReceipt,
    staging_observation: dict[str, Any],
    evaluation_gate: VerifiedEvaluationGate,
    authorization_id: str,
    byte_ceiling: int,
    authorized_at: str,
    valid_until: str,
    authorizer_id: str,
    signing_key_fingerprint: str,
) -> dict[str, Any]:
    policy_sha256 = validate_staging_authority_policy(
        policy, approved_policy_sha256=approved_policy_sha256
    )
    validate_source_registry_v4(source_registry)
    validate_staging_observation(staging_observation)
    validate_evaluation_side_ready(evaluation_gate, evaluated_at=authorized_at)
    _, artifact = _artifact_lookup(source_registry, artifact_id)
    if not artifact["source_url"].startswith("https://"):
        raise ValidationError("artifact source URL must be HTTPS")
    expected_sha1 = _publisher_sha1(artifact)
    receipt = publisher_receipt.receipt
    if publisher_receipt.sha256 != canonical_sha256(receipt):
        raise ValidationError("publisher wrapper digest mismatch")
    expected_publisher = {
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "artifact_id": artifact_id,
        "algorithm": "sha1",
        "value": expected_sha1,
    }
    for field, expected in expected_publisher.items():
        if receipt[field] != expected:
            raise ValidationError(f"publisher receipt binding mismatch: {field}")
    publisher_time = _parse_time(receipt["verified_at"], "publisher verified_at")
    authorization_time = _parse_time(authorized_at, "authorized_at")
    if (
        publisher_time > authorization_time
        or authorization_time - publisher_time
        > timedelta(hours=receipt["max_age_hours"])
    ):
        raise ValidationError("publisher receipt is stale or from the future")
    if byte_ceiling < artifact["expected_bytes"]:
        raise ValidationError("acquisition byte ceiling is below the registered size")
    fingerprint = signing_key_fingerprint.upper()
    if fingerprint not in policy["acquisition_signing_key_fingerprints"]:
        raise ValidationError("staging acquisition signer is not trusted")
    authorized = _parse_time(authorized_at, "authorized_at")
    expires = _parse_time(valid_until, "valid_until")
    staged = _parse_time(staging_observation["observed_at"], "staging observed_at")
    if staged > authorized or authorized - staged > timedelta(minutes=15):
        raise ValidationError("staging observation is stale or from the future")
    maximum = timedelta(hours=policy["maximum_authority_hours"])
    if expires <= authorized or expires - authorized > maximum:
        raise ValidationError("staging authorization validity exceeds policy")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "staging_acquisition_authorization_payload",
        "authorization_id": authorization_id,
        "authority_policy_sha256": policy_sha256,
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_id": artifact_id,
        "artifact_entry_sha256": canonical_sha256(artifact),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "staging_observation_sha256": canonical_sha256(staging_observation),
        "evaluation_gate_sha256": evaluation_gate.sha256,
        "source_url_sha256": sha256_bytes(artifact["source_url"].encode("utf-8")),
        "expected_bytes": artifact["expected_bytes"],
        "publisher_sha1": expected_sha1,
        "byte_ceiling": byte_ceiling,
        "authorized_at": authorized_at,
        "valid_until": valid_until,
        "authorizer_id": authorizer_id,
        "signing_key_fingerprint": fingerprint,
        "training_authorized": False,
    }
    validate_v4_3(payload, "execution-evidence.schema.json")
    return payload


def verify_staging_authorization(
    payload: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    policy: dict[str, Any],
    source_registry: dict[str, Any],
    publisher_receipt: VerifiedPublisherReceipt,
    staging_observation: dict[str, Any],
    evaluation_gate: VerifiedEvaluationGate,
    approved_policy_sha256: str | None = None,
    signature_verifier: SignatureVerifier,
) -> VerifiedStagingAuthorization:
    validate_v4_3(payload, "execution-evidence.schema.json")
    if payload["record_kind"] != "staging_acquisition_authorization_payload":
        raise ValidationError("expected a staging acquisition authorization payload")
    policy_sha256 = validate_staging_authority_policy(
        policy, approved_policy_sha256=approved_policy_sha256
    )
    validate_source_registry_v4(source_registry)
    validate_staging_observation(staging_observation)
    validate_evaluation_side_ready(
        evaluation_gate, evaluated_at=payload["authorized_at"]
    )
    _, artifact = _artifact_lookup(source_registry, payload["artifact_id"])
    expected = {
        "authority_policy_sha256": policy_sha256,
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "staging_observation_sha256": canonical_sha256(staging_observation),
        "evaluation_gate_sha256": evaluation_gate.sha256,
        "source_url_sha256": sha256_bytes(artifact["source_url"].encode("utf-8")),
        "expected_bytes": artifact["expected_bytes"],
        "publisher_sha1": _publisher_sha1(artifact),
    }
    for field, value in expected.items():
        if payload[field] != value:
            raise ValidationError(f"staging authorization mismatch: {field}")
    publisher_time = _parse_time(
        publisher_receipt.receipt["verified_at"], "publisher verified_at"
    )
    payload_time = _parse_time(payload["authorized_at"], "authorized_at")
    if publisher_time > payload_time or payload_time - publisher_time > timedelta(
        hours=publisher_receipt.receipt["max_age_hours"]
    ):
        raise ValidationError("publisher receipt is stale or from the future")
    if payload["byte_ceiling"] < payload["expected_bytes"]:
        raise ValidationError("staging authorization byte ceiling is too small")
    fingerprint = payload["signing_key_fingerprint"]
    if fingerprint not in policy["acquisition_signing_key_fingerprints"]:
        raise ValidationError("staging acquisition signer is not trusted")
    authorized = _parse_time(payload["authorized_at"], "authorized_at")
    expires = _parse_time(payload["valid_until"], "valid_until")
    staged = _parse_time(staging_observation["observed_at"], "staging observed_at")
    if staged > authorized or authorized - staged > timedelta(minutes=15):
        raise ValidationError("staging observation is stale or from the future")
    maximum = timedelta(hours=policy["maximum_authority_hours"])
    if expires <= authorized or expires - authorized > maximum:
        raise ValidationError("staging authorization validity exceeds policy")
    observed = signature_verifier(
        canonical_bytes(payload), signature, public_key, fingerprint
    ).upper()
    if observed != fingerprint:
        raise IntegrityError("staging authorization uses another key")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "staging_acquisition_authorization_receipt",
        "authorization_id": payload["authorization_id"],
        "authority_policy_sha256": policy_sha256,
        "payload_sha256": canonical_sha256(payload),
        "signature_sha256": sha256_bytes(signature),
        "public_key_sha256": sha256_bytes(public_key),
        "signing_key_fingerprint": observed,
        "source_registry_sha256": payload["source_registry_sha256"],
        "artifact_id": payload["artifact_id"],
        "artifact_entry_sha256": payload["artifact_entry_sha256"],
        "publisher_receipt_sha256": payload["publisher_receipt_sha256"],
        "staging_observation_sha256": payload["staging_observation_sha256"],
        "evaluation_gate_sha256": payload["evaluation_gate_sha256"],
        "expected_bytes": payload["expected_bytes"],
        "publisher_sha1": payload["publisher_sha1"],
        "byte_ceiling": payload["byte_ceiling"],
        "authorized_at": payload["authorized_at"],
        "valid_until": payload["valid_until"],
        "training_authorized": False,
    }
    validate_v4_3(receipt, "execution-evidence.schema.json")
    return VerifiedStagingAuthorization(
        payload=payload,
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        signature_sha256=receipt["signature_sha256"],
        public_key_sha256=receipt["public_key_sha256"],
        signing_key_fingerprint=observed,
    )


def validate_staging_authorization_time(
    authorization: VerifiedStagingAuthorization, *, evaluated_at: str
) -> None:
    validate_v4_3(authorization.payload, "execution-evidence.schema.json")
    validate_v4_3(authorization.receipt, "execution-evidence.schema.json")
    if (
        authorization.payload["record_kind"]
        != "staging_acquisition_authorization_payload"
        or authorization.receipt["record_kind"]
        != "staging_acquisition_authorization_receipt"
    ):
        raise ValidationError("invalid staging authorization wrapper kinds")
    if authorization.sha256 != canonical_sha256(authorization.receipt):
        raise ValidationError("staging authorization wrapper digest mismatch")
    if authorization.receipt["payload_sha256"] != canonical_sha256(
        authorization.payload
    ):
        raise ValidationError("staging authorization payload digest mismatch")
    shared = (
        "authorization_id",
        "authority_policy_sha256",
        "source_registry_sha256",
        "artifact_id",
        "artifact_entry_sha256",
        "publisher_receipt_sha256",
        "staging_observation_sha256",
        "evaluation_gate_sha256",
        "expected_bytes",
        "publisher_sha1",
        "byte_ceiling",
        "authorized_at",
        "valid_until",
        "signing_key_fingerprint",
    )
    if any(
        authorization.receipt[field] != authorization.payload[field] for field in shared
    ):
        raise ValidationError("staging authorization wrapper field mismatch")
    if (
        authorization.signature_sha256 != authorization.receipt["signature_sha256"]
        or authorization.public_key_sha256 != authorization.receipt["public_key_sha256"]
        or authorization.signing_key_fingerprint
        != authorization.receipt["signing_key_fingerprint"]
    ):
        raise ValidationError("staging authorization wrapper evidence mismatch")
    evaluated = _parse_time(evaluated_at, "evaluated_at")
    authorized = _parse_time(authorization.receipt["authorized_at"], "authorized_at")
    expires = _parse_time(authorization.receipt["valid_until"], "valid_until")
    if evaluated < authorized or evaluated > expires:
        raise ValidationError("staging authorization is stale or from the future")


def acquire_to_staging(
    *,
    source_registry: dict[str, Any],
    publisher_receipt: VerifiedPublisherReceipt,
    authorization: VerifiedStagingAuthorization,
    staging_observation: dict[str, Any],
    minimum_free_bytes: int,
) -> dict[str, Any]:
    """Download one immutable artifact to the exact authorized staging root."""

    evaluated_at = _utc_now()
    validate_staging_authorization_time(authorization, evaluated_at=evaluated_at)
    validate_source_registry_v4(source_registry)
    validate_staging_observation(staging_observation)
    artifact_id = authorization.receipt["artifact_id"]
    _, artifact = _artifact_lookup(source_registry, artifact_id)
    expected = {
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "staging_observation_sha256": canonical_sha256(staging_observation),
        "expected_bytes": artifact["expected_bytes"],
        "publisher_sha1": _publisher_sha1(artifact),
    }
    for field, value in expected.items():
        if authorization.receipt[field] != value:
            raise ValidationError(f"acquisition receipt binding mismatch: {field}")
    root = Path(staging_observation["root_path"])
    stable_identity = {
        field: staging_observation[field]
        for field in ("root_path_sha256", "marker_sha256", "device", "inode")
    }

    def identity_check(stage: str, _root_fd: int) -> dict[str, Any]:
        root_metadata = _assert_private_root(root)
        marker = hash_file(root / MARKER_FILENAME)
        current = {
            "root_path_sha256": sha256_bytes(str(root).encode("utf-8")),
            "marker_sha256": f"sha256:{marker['sha256']}",
            "device": str(root_metadata.st_dev),
            "inode": str(root_metadata.st_ino),
        }
        for field, value in stable_identity.items():
            if current[field] != value:
                raise IntegrityError(f"staging identity changed: {field}")
        return {
            "stage": stage,
            **current,
        }

    started_at = _utc_now()
    download = download_resumable_at(
        url=artifact["source_url"],
        root=root,
        filename=artifact["filename"],
        expected_bytes=artifact["expected_bytes"],
        expected_checksums={"sha1": _publisher_sha1(artifact)},
        minimum_free_bytes=minimum_free_bytes,
        resume_authorization_sha256=authorization.sha256,
        identity_check=identity_check,
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "staging_acquisition_receipt",
        "artifact_id": artifact_id,
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "authorization_receipt_sha256": authorization.sha256,
        "staging_observation_sha256": canonical_sha256(staging_observation),
        "destination_relative_path": artifact["filename"],
        "bytes": download["bytes"],
        "sha1": download["checksums"]["sha1"],
        "sha256": download["checksums"]["sha256"],
        "started_at": started_at,
        "completed_at": _utc_now(),
        "complete": True,
        "training_authorized": False,
    }
    validate_v4_3(result, "execution-evidence.schema.json")
    return result


def make_artifact_publication_clearance(
    *,
    source_registry: dict[str, Any],
    artifact_id: str,
    artifact_audit: dict[str, Any],
    structural_inventory: dict[str, Any],
    publisher_receipt: VerifiedPublisherReceipt,
    rights: VerifiedPublicationRights,
    obligations: dict[str, Any],
    evaluation_gate: VerifiedEvaluationGate,
    quarantine_index: dict[str, Any],
    cleared_at: str,
) -> dict[str, Any]:
    """Bind the exact prerequisite graph; this does not authorize transformation."""

    validate_source_registry_v4(source_registry)
    validate_v4_3(artifact_audit, "execution-evidence.schema.json")
    validate_v4_3(structural_inventory, "execution-evidence.schema.json")
    rights_receipt = rights.receipt
    validate_publication_v1(rights_receipt, "evidence.schema.json")
    if rights.sha256 != canonical_sha256(rights_receipt):
        raise ValidationError("publication rights wrapper digest mismatch")
    validate_publication_v1(obligations, "evidence.schema.json")
    validate_evaluation_side_ready(evaluation_gate, evaluated_at=cleared_at)
    validate_v4(quarantine_index, "evaluation-evidence.schema.json")
    if quarantine_index["record_kind"] != "quarantine_index":
        raise ValidationError("expected a quarantine index")
    source, artifact = _artifact_lookup(source_registry, artifact_id)
    registry_sha256 = canonical_sha256(source_registry)
    if publisher_receipt.sha256 != canonical_sha256(publisher_receipt.receipt):
        raise ValidationError("publisher wrapper digest mismatch")
    expected_audit = {
        "record_kind": "staging_artifact_audit",
        "artifact_id": artifact_id,
        "source_registry_sha256": registry_sha256,
        "artifact_entry_sha256": canonical_sha256(artifact),
    }
    for field, value in expected_audit.items():
        if artifact_audit[field] != value:
            raise ValidationError(f"artifact audit binding mismatch: {field}")
    if structural_inventory["record_kind"] != "staging_structural_inventory":
        raise ValidationError("expected a staging structural inventory")
    if structural_inventory["artifact_id"] != artifact_id or structural_inventory[
        "artifact_audit_sha256"
    ] != canonical_sha256(artifact_audit):
        raise ValidationError("structural inventory does not bind the artifact audit")
    if rights_receipt["record_kind"] != "publication_rights_assessment_receipt":
        raise ValidationError("expected a publication rights receipt")
    if not rights_receipt["redistribute_source_authorized"]:
        raise ValidationError("source redistribution is not authorized")
    if rights_receipt["source_id"] != source["source_id"] or rights_receipt[
        "source_entry_sha256"
    ] != canonical_sha256(source):
        raise ValidationError("publication rights do not bind the source entry")
    now = _parse_time(cleared_at, "cleared_at")
    if now < _parse_time(
        rights_receipt["reviewed_at"], "rights reviewed_at"
    ) or now > _parse_time(rights_receipt["valid_until"], "rights valid_until"):
        raise ValidationError("publication rights are stale or from the future")
    if (
        obligations["record_kind"] != "publication_obligation_manifest"
        or not obligations["complete"]
    ):
        raise ValidationError("publication obligations are incomplete")
    if obligations["rights_receipt_sha256"] != rights.sha256:
        raise ValidationError("obligations do not bind the rights receipt")
    audit_time = _parse_time(artifact_audit["audited_at"], "artifact audited_at")
    inventory_started = _parse_time(
        structural_inventory["started_at"], "inventory started_at"
    )
    inventory_completed = _parse_time(
        structural_inventory["completed_at"], "inventory completed_at"
    )
    obligations_time = _parse_time(
        obligations["assembled_at"], "obligations assembled_at"
    )
    if not (
        audit_time <= inventory_started <= inventory_completed <= now
        and obligations_time <= now
    ):
        raise ValidationError("publication clearance evidence is out of causal order")
    publisher_time = _parse_time(
        publisher_receipt.receipt["verified_at"], "publisher verified_at"
    )
    if publisher_time > now or now - publisher_time > timedelta(
        hours=publisher_receipt.receipt["max_age_hours"]
    ):
        raise ValidationError("publisher receipt is stale or from the future")
    publisher_expected = {
        "source_registry_sha256": registry_sha256,
        "artifact_entry_sha256": canonical_sha256(artifact),
        "artifact_id": artifact_id,
    }
    for field, value in publisher_expected.items():
        if publisher_receipt.receipt[field] != value:
            raise ValidationError(f"publisher receipt binding mismatch: {field}")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "artifact_publication_clearance",
        "artifact_id": artifact_id,
        "source_registry_sha256": registry_sha256,
        "artifact_entry_sha256": canonical_sha256(artifact),
        "artifact_audit_sha256": canonical_sha256(artifact_audit),
        "inventory_sha256": canonical_sha256(structural_inventory),
        "publisher_receipt_sha256": publisher_receipt.sha256,
        "rights_receipt_sha256": rights.sha256,
        "obligations_sha256": canonical_sha256(obligations),
        "evaluation_gate_sha256": evaluation_gate.sha256,
        "quarantine_index_sha256": canonical_sha256(quarantine_index),
        "cleared_at": cleared_at,
        "ready": True,
        "foundation_transform_authorized": False,
        "training_authorized": False,
    }
    validate_v4_3(result, "execution-evidence.schema.json")
    return result


def evaluate_gate_v4_3(
    *,
    evaluated_at: str,
    source_lineage: VerifiedRegistryLineage | None,
    evaluation_lineage: VerifiedRegistryLineage | None,
    evaluation_gate: VerifiedEvaluationGate | None,
    staging_observation: dict[str, Any] | None,
    authorizations: Iterable[VerifiedStagingAuthorization] = (),
    acquisitions: Iterable[dict[str, Any]] = (),
    audits: Iterable[dict[str, Any]] = (),
    inventories: Iterable[dict[str, Any]] = (),
    clearances: Iterable[dict[str, Any]] = (),
    publication_receipts: Iterable[dict[str, Any]] = (),
    admissions: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Summarize a mechanically supplied evidence set without granting training."""

    _parse_time(evaluated_at, "evaluated_at")
    validate_schema_lock_v4_3()
    blockers: list[dict[str, str]] = []
    bindings: list[dict[str, str]] = []

    source_registry: dict[str, Any] | None = None
    registry_lineage_ready = False
    if source_lineage is not None and evaluation_lineage is not None:
        try:
            source_verified = validate_registry_lineage_v4_1(source_lineage.registries)
            evaluation_verified = validate_registry_lineage_v4_1(
                evaluation_lineage.registries
            )
            if (
                source_verified.sha256 != source_lineage.sha256
                or evaluation_verified.sha256 != evaluation_lineage.sha256
                or source_verified.receipt["registry_kind"] != "sources"
                or evaluation_verified.receipt["registry_kind"] != "evaluations"
            ):
                raise ValidationError("registry lineage wrapper mismatch")
            source_registry = source_verified.tip
            registry_lineage_ready = True
            for lineage in (source_verified, evaluation_verified):
                bindings.append(
                    {
                        "kind": f"{lineage.receipt['registry_kind']}_lineage",
                        "subject_id": lineage.tip["registry_id"],
                        "sha256": lineage.sha256,
                    }
                )
        except (IntegrityError, ValidationError):
            registry_lineage_ready = False
    expected_artifacts = (
        {
            artifact["artifact_id"]
            for source in source_registry["sources"]
            for artifact in source["artifacts"]
        }
        if source_registry is not None
        else set()
    )
    expected_sources = (
        {source["source_id"] for source in source_registry["sources"]}
        if source_registry is not None
        else set()
    )
    registry_sha256 = (
        canonical_sha256(source_registry) if source_registry is not None else None
    )
    artifact_entries = (
        {
            artifact["artifact_id"]: canonical_sha256(artifact)
            for source in source_registry["sources"]
            for artifact in source["artifacts"]
        }
        if source_registry is not None
        else {}
    )

    evaluation_ready = False
    if evaluation_gate is not None:
        try:
            validate_evaluation_side_ready(evaluation_gate, evaluated_at=evaluated_at)
            evaluation_ready = True
            bindings.append(
                {
                    "kind": "evaluation_gate",
                    "subject_id": evaluation_gate.gate["gate_id"],
                    "sha256": evaluation_gate.sha256,
                }
            )
        except (IntegrityError, ValidationError):
            evaluation_ready = False
    staging_ready = False
    if staging_observation is not None:
        try:
            validate_staging_observation(staging_observation)
            now = _parse_time(evaluated_at, "evaluated_at")
            observed = _parse_time(
                staging_observation["observed_at"], "staging observed_at"
            )
            if observed > now or now - observed > STAGING_OBSERVATION_MAX_AGE:
                raise ValidationError("staging observation is stale or from the future")
            staging_ready = True
            bindings.append(
                {
                    "kind": "staging_observation",
                    "subject_id": staging_observation["observation_id"],
                    "sha256": canonical_sha256(staging_observation),
                }
            )
        except (IntegrityError, ValidationError):
            staging_ready = False

    def evidence_map(
        values: Iterable[Any],
        kind: str,
        expected_record_kind: str,
        *,
        binds_entry: bool,
    ) -> dict[str, tuple[dict[str, Any], str]]:
        result: dict[str, tuple[dict[str, Any], str]] = {}
        for value in values:
            record = value.receipt if hasattr(value, "receipt") else value
            try:
                validate_v4_3(record, "execution-evidence.schema.json")
                if expected_record_kind == "staging_acquisition_authorization_receipt":
                    validate_staging_authorization_time(
                        value, evaluated_at=record["authorized_at"]
                    )
            except (IntegrityError, ValidationError):
                continue
            artifact_id = record.get("artifact_id")
            if (
                record.get("record_kind") != expected_record_kind
                or artifact_id not in artifact_entries
                or record.get("source_registry_sha256") != registry_sha256
                or artifact_id in result
            ):
                continue
            if (
                binds_entry
                and record.get("artifact_entry_sha256") != artifact_entries[artifact_id]
            ):
                continue
            if hasattr(value, "sha256") and value.sha256 != canonical_sha256(record):
                continue
            digest = (
                value.sha256 if hasattr(value, "sha256") else canonical_sha256(record)
            )
            result[artifact_id] = (record, digest)
            bindings.append({"kind": kind, "subject_id": artifact_id, "sha256": digest})
        return result

    authority_map = evidence_map(
        authorizations,
        "staging_authorization",
        "staging_acquisition_authorization_receipt",
        binds_entry=True,
    )
    authority_map = {
        artifact_id: value
        for artifact_id, value in authority_map.items()
        if value[0]["staging_observation_sha256"]
        == (
            canonical_sha256(staging_observation)
            if staging_observation is not None
            else None
        )
        and value[0]["evaluation_gate_sha256"]
        == (evaluation_gate.sha256 if evaluation_gate is not None else None)
    }
    acquisition_map = evidence_map(
        acquisitions,
        "staging_acquisition",
        "staging_acquisition_receipt",
        binds_entry=True,
    )
    audit_map = evidence_map(
        audits,
        "staging_artifact_audit",
        "staging_artifact_audit",
        binds_entry=True,
    )
    inventory_map = evidence_map(
        inventories,
        "staging_structural_inventory",
        "staging_structural_inventory",
        binds_entry=False,
    )
    clearance_map = evidence_map(
        clearances,
        "artifact_publication_clearance",
        "artifact_publication_clearance",
        binds_entry=True,
    )
    publication_map: dict[str, dict[str, Any]] = {}
    duplicate_publications: set[str] = set()
    for item in publication_receipts:
        try:
            validate_publication_v1(item, "evidence.schema.json")
        except ValidationError:
            continue
        artifact_id = item.get("artifact_id")
        if (
            item.get("record_kind") == "hf_publication_receipt"
            and item.get("complete")
            and artifact_id in artifact_entries
            and item.get("source_registry_sha256") == registry_sha256
            and item.get("artifact_entry_sha256") == artifact_entries[artifact_id]
        ):
            if artifact_id in publication_map:
                duplicate_publications.add(artifact_id)
            else:
                publication_map[artifact_id] = item
    for artifact_id in duplicate_publications:
        publication_map.pop(artifact_id, None)
    admission_map: dict[str, dict[str, Any]] = {}
    duplicate_admissions: set[str] = set()
    for item in admissions:
        try:
            validate_v4_3(item, "execution-evidence.schema.json")
        except ValidationError:
            continue
        if (
            item.get("record_kind") == "hf_source_admission_receipt"
            and item.get("decision") == "admitted"
            and item.get("source_id") in expected_sources
            and item.get("source_registry_sha256") == registry_sha256
        ):
            source = next(
                source
                for source in source_registry["sources"]
                if source["source_id"] == item["source_id"]
            )
            source_artifacts = {
                artifact["artifact_id"] for artifact in source["artifacts"]
            }
            if (
                item["source_entry_sha256"] != canonical_sha256(source)
                or not source_artifacts <= clearance_map.keys()
                or not source_artifacts <= publication_map.keys()
                or set(item["clearance_sha256s"])
                != {
                    clearance_map[artifact_id][1]
                    for artifact_id in source_artifacts
                    if artifact_id in clearance_map
                }
                or set(item["publication_receipt_sha256s"])
                != {
                    canonical_sha256(publication_map[artifact_id])
                    for artifact_id in source_artifacts
                    if artifact_id in publication_map
                }
            ):
                continue
            source_id = item["source_id"]
            if source_id in admission_map:
                duplicate_admissions.add(source_id)
            else:
                admission_map[source_id] = item
    for source_id in duplicate_admissions:
        admission_map.pop(source_id, None)
    authority_ids = set(authority_map)
    acquisition_ids = {
        artifact_id
        for artifact_id, (record, _) in acquisition_map.items()
        if artifact_id in authority_map
        and record["authorization_receipt_sha256"] == authority_map[artifact_id][1]
        and _parse_time(authority_map[artifact_id][0]["authorized_at"], "authorized_at")
        <= _parse_time(record["started_at"], "acquisition started_at")
        <= _parse_time(record["completed_at"], "acquisition completed_at")
        <= _parse_time(authority_map[artifact_id][0]["valid_until"], "valid_until")
        and record["publisher_receipt_sha256"]
        == authority_map[artifact_id][0]["publisher_receipt_sha256"]
        and record["staging_observation_sha256"]
        == authority_map[artifact_id][0]["staging_observation_sha256"]
        and record["bytes"] == authority_map[artifact_id][0]["expected_bytes"]
        and record["sha1"] == authority_map[artifact_id][0]["publisher_sha1"]
    }
    audit_ids = {
        artifact_id
        for artifact_id, (record, _) in audit_map.items()
        if artifact_id in acquisition_map
        and record["acquisition_receipt_sha256"] == acquisition_map[artifact_id][1]
        and record["staging_observation_sha256"]
        == acquisition_map[artifact_id][0]["staging_observation_sha256"]
        and record["bytes"] == acquisition_map[artifact_id][0]["bytes"]
        and record["sha1"] == acquisition_map[artifact_id][0]["sha1"]
        and record["sha256"] == acquisition_map[artifact_id][0]["sha256"]
        and _parse_time(
            acquisition_map[artifact_id][0]["completed_at"],
            "acquisition completed_at",
        )
        <= _parse_time(record["audited_at"], "artifact audited_at")
    }
    inventory_ids = {
        artifact_id
        for artifact_id, (record, _) in inventory_map.items()
        if artifact_id in audit_map
        and record["artifact_audit_sha256"] == audit_map[artifact_id][1]
        and record["artifact_sha256"] == f"sha256:{audit_map[artifact_id][0]['sha256']}"
        and record["artifact_bytes"] == audit_map[artifact_id][0]["bytes"]
        and _parse_time(audit_map[artifact_id][0]["audited_at"], "artifact audited_at")
        <= _parse_time(record["started_at"], "inventory started_at")
        <= _parse_time(record["completed_at"], "inventory completed_at")
    }
    clearance_ids = {
        artifact_id
        for artifact_id, (record, _) in clearance_map.items()
        if artifact_id in audit_map
        and artifact_id in inventory_map
        and record["artifact_audit_sha256"] == audit_map[artifact_id][1]
        and record["inventory_sha256"] == inventory_map[artifact_id][1]
        and record["evaluation_gate_sha256"]
        == (evaluation_gate.sha256 if evaluation_gate is not None else None)
        and _parse_time(
            inventory_map[artifact_id][0]["completed_at"], "inventory completed_at"
        )
        <= _parse_time(record["cleared_at"], "clearance cleared_at")
    }
    publication_ids = {
        artifact_id
        for artifact_id, record in publication_map.items()
        if artifact_id in clearance_map
        and artifact_id in audit_map
        and record["artifact_clearance_sha256"] == clearance_map[artifact_id][1]
        and record["local_bytes"] == audit_map[artifact_id][0]["bytes"]
        and record["local_sha1"] == audit_map[artifact_id][0]["sha1"]
        and record["local_sha256"] == audit_map[artifact_id][0]["sha256"]
        and _parse_time(clearance_map[artifact_id][0]["cleared_at"], "cleared_at")
        <= _parse_time(record["started_at"], "publication started_at")
        <= _parse_time(record["completed_at"], "publication completed_at")
    }
    admission_ids = {
        source_id
        for source_id, record in admission_map.items()
        if all(
            _parse_time(
                publication_map[artifact_id]["completed_at"], "publication completed_at"
            )
            <= _parse_time(record["assessed_at"], "admission assessed_at")
            for artifact_id in {
                artifact["artifact_id"]
                for source in source_registry["sources"]
                if source["source_id"] == source_id
                for artifact in source["artifacts"]
            }
        )
    }
    readiness = {
        "registry_lineage_ready": registry_lineage_ready,
        "evaluation_gate_ready": evaluation_ready,
        "staging_ready": staging_ready,
        "acquisition_authority_ready": (
            registry_lineage_ready
            and evaluation_ready
            and staging_ready
            and bool(expected_artifacts)
            and authority_ids == expected_artifacts
        ),
        "acquisition_evidence_ready": (
            bool(expected_artifacts) and acquisition_ids == expected_artifacts
        ),
        "artifact_audit_ready": (
            bool(expected_artifacts) and audit_ids == expected_artifacts
        ),
        "structural_inventory_ready": (
            bool(expected_artifacts) and inventory_ids == expected_artifacts
        ),
        "publication_clearance_ready": (
            bool(expected_artifacts) and clearance_ids == expected_artifacts
        ),
        "foundation_publication_ready": (
            bool(expected_artifacts)
            and clearance_ids == expected_artifacts
            and publication_ids == expected_artifacts
        ),
        "foundation_transform_ready": (
            registry_lineage_ready
            and evaluation_ready
            and staging_ready
            and bool(expected_sources)
            and authority_ids == expected_artifacts
            and acquisition_ids == expected_artifacts
            and audit_ids == expected_artifacts
            and inventory_ids == expected_artifacts
            and clearance_ids == expected_artifacts
            and publication_ids == expected_artifacts
            and admission_ids == expected_sources
        ),
    }
    for field, ready in readiness.items():
        if not ready:
            blockers.append(
                {
                    "code": field.removesuffix("_ready") + "_missing",
                    "subject_kind": "phase0_v4_3",
                    "subject_id": "foundation",
                }
            )
    if evaluation_gate is not None and not evaluation_ready:
        for blocker in evaluation_gate.gate["blockers"]:
            if not blocker["code"].startswith(
                (
                    "access_anchor_",
                    "access_log_",
                    "confirmatory_",
                    "evaluation_",
                    "licence_",
                    "licensing_",
                    "materialization_",
                    "quarantine_",
                    "seal_",
                )
            ):
                continue
            blockers.append(
                {
                    "code": f"prerequisite_{blocker['code']}",
                    "subject_kind": blocker["subject_kind"],
                    "subject_id": blocker["subject_id"],
                }
            )
    result = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": "phase0-hf-public-source-v4.3",
        "evaluated_at": evaluated_at,
        "contracts_frozen": True,
        **readiness,
        "blockers": sorted(blockers, key=lambda item: item["code"]),
        "evidence_bindings": sorted(
            bindings, key=lambda item: (item["kind"], item["subject_id"])
        ),
        "training_authorized": False,
    }
    validate_v4_3(result, "gate.schema.json")
    return result


def audit_staged_artifact(
    *,
    source_registry: dict[str, Any],
    acquisition_receipt: dict[str, Any],
    staging_observation: dict[str, Any],
    audited_at: str | None = None,
) -> dict[str, Any]:
    validate_source_registry_v4(source_registry)
    validate_v4_3(acquisition_receipt, "execution-evidence.schema.json")
    validate_staging_observation(staging_observation)
    if acquisition_receipt["record_kind"] != "staging_acquisition_receipt":
        raise ValidationError("expected a staging acquisition receipt")
    _, artifact = _artifact_lookup(source_registry, acquisition_receipt["artifact_id"])
    root = Path(staging_observation["root_path"])
    relative = _require_safe_relative(artifact["filename"])
    path = root.joinpath(*relative.parts)
    measured = hash_file(path)
    expected = {
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "destination_relative_path": artifact["filename"],
        "bytes": artifact["expected_bytes"],
        "sha1": _publisher_sha1(artifact),
        "sha256": acquisition_receipt["sha256"],
    }
    for field, value in expected.items():
        if acquisition_receipt[field] != value:
            raise ValidationError(f"staged acquisition binding mismatch: {field}")
    for field in ("bytes", "sha1", "sha256"):
        if measured[field] != acquisition_receipt[field]:
            raise IntegrityError(f"staged artifact mismatch: {field}")
    row = next(
        (
            item
            for item in staging_observation["inventory"]
            if item["path"] == artifact["filename"]
        ),
        None,
    )
    if row is None or row["kind"] != "artifact":
        raise ValidationError("staging observation omits the acquired artifact")
    if row["sha256"] != f"sha256:{measured['sha256']}":
        raise IntegrityError("staging observation artifact digest mismatch")
    audited = audited_at or _utc_now()
    if _parse_time(audited, "audited_at") < _parse_time(
        acquisition_receipt["completed_at"], "acquisition completed_at"
    ):
        raise ValidationError("artifact audit predates acquisition completion")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "staging_artifact_audit",
        "artifact_id": artifact["artifact_id"],
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "acquisition_receipt_sha256": canonical_sha256(acquisition_receipt),
        "staging_observation_sha256": canonical_sha256(staging_observation),
        "bytes": measured["bytes"],
        "sha1": measured["sha1"],
        "sha256": measured["sha256"],
        "device": str(measured["device"]),
        "inode": str(measured["inode"]),
        "mtime_ns": str(measured["mtime_ns"]),
        "audited_at": audited,
        "verified": True,
        "training_authorized": False,
    }
    validate_v4_3(result, "execution-evidence.schema.json")
    return result


def inventory_staged_artifact(
    *,
    source_registry: dict[str, Any],
    artifact_audit: dict[str, Any],
    staging_observation: dict[str, Any],
    started_at: str | None = None,
) -> dict[str, Any]:
    validate_source_registry_v4(source_registry)
    validate_v4_3(artifact_audit, "execution-evidence.schema.json")
    validate_staging_observation(staging_observation)
    if artifact_audit["record_kind"] != "staging_artifact_audit":
        raise ValidationError("expected a staging artifact audit")
    _, artifact = _artifact_lookup(source_registry, artifact_audit["artifact_id"])
    if artifact_audit["source_registry_sha256"] != canonical_sha256(source_registry):
        raise ValidationError("artifact audit registry binding mismatch")
    path = Path(staging_observation["root_path"]) / artifact["filename"]
    before = hash_file(path)
    if before["sha256"] != artifact_audit["sha256"]:
        raise IntegrityError("artifact changed after its audit")
    began = started_at or _utc_now()
    if _parse_time(began, "inventory started_at") < _parse_time(
        artifact_audit["audited_at"], "artifact audited_at"
    ):
        raise ValidationError("structural inventory predates the artifact audit")
    counts = stream_count(path, artifact["inventory_kind"])
    after = hash_file(path)
    if before != after:
        raise IntegrityError("artifact changed during structural inventory")
    counters = {key: value for key, value in counts.items() if key != "kind"}
    counters.setdefault("parse_errors", 0)
    counters.setdefault("rejected_records", 0)
    for required in artifact["required_nonzero_counters"]:
        if counters.get(required, 0) <= 0:
            raise IntegrityError(f"required structural counter is zero: {required}")
    for required in artifact["required_zero_counters"]:
        if counters.get(required, 0) != 0:
            raise IntegrityError(f"required structural counter is nonzero: {required}")
    completed = _utc_now()
    if _parse_time(completed, "inventory completed_at") < _parse_time(
        began, "inventory started_at"
    ):
        raise ValidationError("structural inventory completion predates its start")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "staging_structural_inventory",
        "artifact_id": artifact["artifact_id"],
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_audit_sha256": canonical_sha256(artifact_audit),
        "artifact_sha256": f"sha256:{artifact_audit['sha256']}",
        "artifact_bytes": artifact_audit["bytes"],
        "counter_kind": counts["kind"],
        "counter_version": "hf-stream-counter-v4",
        "started_at": began,
        "completed_at": completed,
        "complete": True,
        "parse_errors": counters["parse_errors"],
        "rejected_records": counters["rejected_records"],
        "counters": dict(sorted(counters.items())),
        "training_authorized": False,
    }
    validate_v4_3(result, "execution-evidence.schema.json")
    return result


def make_source_admission(
    *,
    source_registry: dict[str, Any],
    source_id: str,
    clearances: Iterable[dict[str, Any]],
    publication_receipts: Iterable[dict[str, Any]],
    assessed_at: str,
    assessor: str,
) -> dict[str, Any]:
    validate_source_registry_v4(source_registry)
    matches = [
        source
        for source in source_registry["sources"]
        if source["source_id"] == source_id
    ]
    if len(matches) != 1:
        raise ValidationError("source_id must resolve exactly once")
    source = matches[0]
    expected_ids = {item["artifact_id"] for item in source["artifacts"]}
    clearance_map: dict[str, dict[str, Any]] = {}
    for item in clearances:
        validate_v4_3(item, "execution-evidence.schema.json")
        if item["record_kind"] != "artifact_publication_clearance" or not item["ready"]:
            raise ValidationError("source admission requires ready clearances")
        if item["artifact_id"] in clearance_map:
            raise ValidationError("duplicate artifact publication clearance")
        clearance_map[item["artifact_id"]] = item
    publication_map: dict[str, dict[str, Any]] = {}
    for item in publication_receipts:
        validate_publication_v1(item, "evidence.schema.json")
        if item.get("record_kind") != "hf_publication_receipt" or not item.get(
            "complete"
        ):
            raise ValidationError(
                "source admission requires complete publication receipts"
            )
        if item["artifact_id"] in publication_map:
            raise ValidationError("duplicate artifact publication receipt")
        publication_map[item["artifact_id"]] = item
    if set(clearance_map) != expected_ids or set(publication_map) != expected_ids:
        raise ValidationError("source admission evidence does not cover the source")
    registry_sha256 = canonical_sha256(source_registry)
    for artifact_id in expected_ids:
        if clearance_map[artifact_id]["source_registry_sha256"] != registry_sha256:
            raise ValidationError("clearance registry binding mismatch")
        if publication_map[artifact_id][
            "artifact_clearance_sha256"
        ] != canonical_sha256(clearance_map[artifact_id]):
            raise ValidationError("publication receipt clearance binding mismatch")
    assessed = _parse_time(assessed_at, "assessed_at")
    if any(
        assessed < _parse_time(item["completed_at"], "publication completed_at")
        for item in publication_map.values()
    ) or any(
        assessed < _parse_time(item["cleared_at"], "clearance cleared_at")
        for item in clearance_map.values()
    ):
        raise ValidationError("source admission predates its evidence")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "hf_source_admission_receipt",
        "source_id": source_id,
        "source_registry_sha256": registry_sha256,
        "source_entry_sha256": canonical_sha256(source),
        "clearance_sha256s": sorted(
            canonical_sha256(item) for item in clearance_map.values()
        ),
        "publication_receipt_sha256s": sorted(
            canonical_sha256(item) for item in publication_map.values()
        ),
        "decision": "admitted",
        "assessed_at": assessed_at,
        "assessor": assessor,
        "training_authorized": False,
    }
    validate_v4_3(result, "execution-evidence.schema.json")
    return result
