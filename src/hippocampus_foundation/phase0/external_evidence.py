"""Storage, publisher, and authenticated custody evidence for Phase 0 v4."""

from __future__ import annotations

import copy
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from hippocampus_foundation.storage_identity import (
    DRIVE_LOCATOR_ID,
    validate_observation_v1,
)

from .canonical import canonical_bytes, canonical_sha256, sha256_bytes
from .errors import GateBlocked, IntegrityError, ValidationError
from .evaluation_firewall import validate_source_registry_v4
from .seal import verify_access_chain
from .v4_contracts import SCHEMA_VERSION_V4, validate_v4


DRIVE_BIND_MAX_AGE = timedelta(minutes=15)
STORAGE_ATTESTATION_MAX_AGE = timedelta(hours=72)
ANCHOR_MAX_AGE = timedelta(hours=72)
MAX_PUBLISHER_STATEMENT_BYTES = 16 * 1024 * 1024
MAX_OPENPGP_EVIDENCE_BYTES = 1024 * 1024

SignatureVerifier = Callable[[bytes, bytes, bytes, str], str]


@dataclass(frozen=True)
class VerifiedPublisherReceipt:
    receipt: dict[str, Any]
    sha256: str
    statement_sha256: str


@dataclass(frozen=True)
class VerifiedAccessAnchor:
    anchor: dict[str, Any]
    sha256: str
    signature_sha256: str
    public_key_sha256: str
    signing_key_fingerprint: str


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def bind_drive_observation_v4(
    source_registry: dict[str, Any],
    observation: dict[str, Any],
    *,
    registry_id: str,
    verifier: str,
    bound_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Version a pending v4 registry and bind the complete Drive observation."""

    validate_source_registry_v4(source_registry)
    validate_observation_v1(observation, evaluated_at=bound_at)
    if not registry_id.strip() or not verifier.strip():
        raise ValidationError("registry_id and verifier must not be empty")
    requirements = [
        item
        for item in source_registry["storage_requirements"]
        if item["locator_id"] == DRIVE_LOCATOR_ID
    ]
    if len(requirements) != 1:
        raise ValidationError(f"expected exactly one {DRIVE_LOCATOR_ID} requirement")
    requirement = requirements[0]
    for field, expected in {
        "provider": observation["provider"],
        "required_root": observation["observed_root"],
    }.items():
        if requirement[field] != expected:
            raise ValidationError(f"Drive observation/registry mismatch: {field}")
    for field in ("provider_resource_id", "root_resource_id"):
        if requirement[field] is not None and requirement[field] != observation[field]:
            raise ValidationError(f"Drive observation conflicts with registered {field}")

    bound_registry = copy.deepcopy(source_registry)
    bound_registry["registry_id"] = registry_id
    bound_registry["previous_registry_sha256"] = canonical_sha256(source_registry)
    bound_registry["generated_at"] = bound_at
    bound_requirement = next(
        item
        for item in bound_registry["storage_requirements"]
        if item["locator_id"] == DRIVE_LOCATOR_ID
    )
    bound_requirement["provider_resource_id"] = observation["provider_resource_id"]
    bound_requirement["root_resource_id"] = observation["root_resource_id"]
    validate_source_registry_v4(bound_registry, predecessor=source_registry)

    bound_time = _parse_time(bound_at, "bound_at")
    attestation = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "storage_attestation",
        "locator_id": DRIVE_LOCATOR_ID,
        "provider": observation["provider"],
        "provider_resource_id": observation["provider_resource_id"],
        "root_resource_id": observation["root_resource_id"],
        "observed_root": observation["observed_root"],
        "drive_observation_sha256": canonical_sha256(observation),
        "source_registry_sha256": canonical_sha256(bound_registry),
        "principal_permission_id_sha256": observation[
            "principal_permission_id_sha256"
        ],
        "requested_scope": observation["requested_scope"],
        "scope_exact": observation["scope_exact"],
        "same_account_human_attested": observation[
            "same_account_human_attested"
        ],
        "method": observation["method"],
        "observed_at": observation["observed_at"],
        "bound_at": bound_at,
        "expires_at": _format_time(bound_time + STORAGE_ATTESTATION_MAX_AGE),
        "checks": copy.deepcopy(observation["checks"]),
        "contains_evaluation_content": observation["contains_evaluation_content"],
        "api_drive_write_authorized": observation["api_drive_write_authorized"],
        "drive_write_performed": observation["drive_write_performed"],
        "verifier": verifier,
        "training_authorized": False,
    }
    validate_storage_attestation_v4(
        attestation,
        bound_registry,
        observation=observation,
        evaluated_at=bound_at,
    )
    return bound_registry, attestation


def validate_storage_attestation_v4(
    attestation: dict[str, Any],
    source_registry: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    evaluated_at: str | None = None,
) -> None:
    validate_v4(attestation, "storage-evidence.schema.json")
    validate_source_registry_v4(source_registry)
    requirements = [
        item
        for item in source_registry["storage_requirements"]
        if item["locator_id"] == attestation["locator_id"]
    ]
    if len(requirements) != 1:
        raise ValidationError("storage attestation locator does not resolve exactly once")
    requirement = requirements[0]
    expected = {
        "provider": requirement["provider"],
        "provider_resource_id": requirement["provider_resource_id"],
        "root_resource_id": requirement["root_resource_id"],
        "observed_root": requirement["required_root"],
        "source_registry_sha256": canonical_sha256(source_registry),
    }
    for field, value in expected.items():
        if attestation[field] != value:
            raise ValidationError(f"storage attestation binding mismatch: {field}")
    observed = _parse_time(attestation["observed_at"], "observed_at")
    bound = _parse_time(attestation["bound_at"], "bound_at")
    expires = _parse_time(attestation["expires_at"], "expires_at")
    generated = _parse_time(source_registry["generated_at"], "registry generated_at")
    if generated > bound:
        raise ValidationError("storage attestation predates its source registry")
    if bound < observed or bound - observed > DRIVE_BIND_MAX_AGE:
        raise ValidationError("Drive observation was not bound within 15 minutes")
    if expires != bound + STORAGE_ATTESTATION_MAX_AGE:
        raise ValidationError("storage attestation expiry is not exactly 72 hours")
    if observation is not None:
        validate_observation_v1(observation, evaluated_at=attestation["bound_at"])
        if attestation["drive_observation_sha256"] != canonical_sha256(observation):
            raise ValidationError("storage attestation observation digest mismatch")
        observation_bindings = {
            "principal_permission_id_sha256": observation[
                "principal_permission_id_sha256"
            ],
            "requested_scope": observation["requested_scope"],
            "scope_exact": observation["scope_exact"],
            "same_account_human_attested": observation[
                "same_account_human_attested"
            ],
            "checks": observation["checks"],
        }
        for field, value in observation_bindings.items():
            if attestation[field] != value:
                raise ValidationError(f"storage observation binding mismatch: {field}")
    if evaluated_at is not None:
        evaluated = _parse_time(evaluated_at, "evaluated_at")
        if evaluated < bound:
            raise ValidationError("storage attestation is from the future")
        if evaluated > expires:
            raise ValidationError("storage attestation is stale")


def _artifact_lookup(
    registry: dict[str, Any], artifact_id: str
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


def _publisher_requirement(
    registry: dict[str, Any], evidence_id: str
) -> dict[str, Any]:
    matches = [
        item
        for item in registry["publisher_evidence_requirements"]
        if item["evidence_id"] == evidence_id
    ]
    if len(matches) != 1:
        raise ValidationError(f"publisher evidence_id must resolve once: {evidence_id}")
    return matches[0]


def _parse_gnu_checksum_manifest(
    statement: bytes, filename: str
) -> list[tuple[str, str]]:
    if not statement or len(statement) > MAX_PUBLISHER_STATEMENT_BYTES:
        raise ValidationError("publisher checksum statement size is invalid")
    try:
        text = statement.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("publisher checksum statement is not UTF-8") from exc
    result: list[tuple[str, str]] = []
    pattern = re.compile(r"^([0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})[ \t]+[*]?(.+?)\s*$")
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if match is None:
            continue
        candidate = match.group(2)
        if candidate == filename:
            digest = match.group(1).casefold()
            result.append(("sha256" if len(digest) == 64 else "sha1", digest))
    return result


def build_publisher_checksum_receipt_v4(
    *,
    source_registry: dict[str, Any],
    evidence_id: str,
    statement: bytes,
    resolved_url: str,
    retrieved_at: str,
    verified_at: str,
    verifier: str,
) -> dict[str, Any]:
    validate_source_registry_v4(source_registry)
    if not verifier.strip():
        raise ValidationError("publisher evidence verifier must not be empty")
    requirement = _publisher_requirement(source_registry, evidence_id)
    source, artifact = _artifact_lookup(source_registry, requirement["artifact_id"])
    if source["source_id"] != requirement["source_id"]:
        raise ValidationError("publisher evidence source binding mismatch")
    if requirement["statement_url"] is None:
        raise GateBlocked("publisher checksum statement URL is not pinned")
    original = urlparse(requirement["statement_url"])
    resolved = urlparse(resolved_url)
    if (
        original.scheme != "https"
        or original.hostname is None
        or resolved.scheme != "https"
        or resolved.hostname != original.hostname
    ):
        raise ValidationError("publisher statement redirect changed scheme or host")
    filename = Path(artifact["filename"]).name
    matches = _parse_gnu_checksum_manifest(statement, filename)
    if len(matches) != 1:
        raise ValidationError(
            f"publisher statement must contain exactly one target row: {filename}"
        )
    algorithm, value = matches[0]
    registered = {
        (item["algorithm"], item["value"])
        for item in artifact["checksums"]
        if item["origin"] == "publisher" and item["algorithm"] in {"sha1", "sha256"}
    }
    if (algorithm, value) not in registered:
        raise IntegrityError("publisher statement checksum differs from the registry")
    retrieved = _parse_time(retrieved_at, "retrieved_at")
    verified = _parse_time(verified_at, "verified_at")
    generated = _parse_time(source_registry["generated_at"], "registry generated_at")
    if retrieved < generated:
        raise ValidationError("publisher evidence predates its source registry")
    if verified < retrieved:
        raise ValidationError("publisher evidence was verified before retrieval")
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "publisher_checksum_receipt",
        "evidence_id": evidence_id,
        "source_id": source["source_id"],
        "artifact_id": artifact["artifact_id"],
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "statement_sha256": sha256_bytes(statement),
        "statement_bytes": len(statement),
        "statement_url": requirement["statement_url"],
        "resolved_url": resolved_url,
        "statement_format": requirement["statement_format"],
        "retrieved_at": retrieved_at,
        "max_age_hours": requirement["max_age_hours"],
        "algorithm": algorithm,
        "value": value,
        "filename": filename,
        "statement_match_count": 1,
        "verified_at": verified_at,
        "verifier": verifier,
        "contains_source_bytes": False,
        "training_authorized": False,
    }
    validate_v4(result, "publisher-evidence.schema.json")
    return result


def verify_publisher_checksum_receipt_v4(
    receipt: dict[str, Any],
    statement: bytes,
    source_registry: dict[str, Any],
    *,
    evaluated_at: str,
) -> VerifiedPublisherReceipt:
    validate_v4(receipt, "publisher-evidence.schema.json")
    expected = build_publisher_checksum_receipt_v4(
        source_registry=source_registry,
        evidence_id=receipt["evidence_id"],
        statement=statement,
        resolved_url=receipt["resolved_url"],
        retrieved_at=receipt["retrieved_at"],
        verified_at=receipt["verified_at"],
        verifier=receipt["verifier"],
    )
    if expected != receipt:
        raise ValidationError("publisher checksum receipt is not reproducible")
    evaluated = _parse_time(evaluated_at, "evaluated_at")
    verified = _parse_time(receipt["verified_at"], "verified_at")
    if verified > evaluated:
        raise ValidationError("publisher checksum receipt is from the future")
    if evaluated - verified > timedelta(hours=receipt["max_age_hours"]):
        raise ValidationError("publisher checksum receipt is stale")
    return VerifiedPublisherReceipt(
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        statement_sha256=sha256_bytes(statement),
    )


def make_access_anchor_payload_v4(
    *,
    seal_receipt: dict[str, Any],
    access_events: Iterable[dict[str, Any]],
    sequence: int,
    previous_anchor: VerifiedAccessAnchor | None,
    anchored_at: str,
    valid_until: str,
    authority_id: str,
    signing_key_fingerprint: str,
) -> dict[str, Any]:
    events = list(access_events)
    if not events:
        raise ValidationError("access log is empty")
    verify_access_chain(events)
    if sequence < 1:
        raise ValidationError("anchor sequence must be positive")
    if previous_anchor is None and sequence != 1:
        raise ValidationError("the first anchor must use sequence 1")
    if previous_anchor is not None:
        if sequence != previous_anchor.anchor["sequence"] + 1:
            raise ValidationError("anchor sequence is not monotonic")
        if previous_anchor.anchor["seal_id"] != seal_receipt["seal_id"]:
            raise ValidationError("previous anchor belongs to another seal")
    result = {
        "schema_version": SCHEMA_VERSION_V4,
        "record_kind": "access_log_anchor",
        "seal_id": seal_receipt["seal_id"],
        "seal_receipt_sha256": canonical_sha256(seal_receipt),
        "event_count": len(events),
        "head_event_sha256": events[-1]["event_hash"],
        "sequence": sequence,
        "previous_anchor_sha256": (
            previous_anchor.sha256 if previous_anchor is not None else None
        ),
        "anchored_at": anchored_at,
        "valid_until": valid_until,
        "authority_id": authority_id,
        "signing_key_fingerprint": signing_key_fingerprint,
        "training_authorized": False,
    }
    validate_v4(result, "access-anchor.schema.json")
    return result


def _verify_detached_signature_gpg(
    payload: bytes,
    signature: bytes,
    public_key: bytes,
    expected_fingerprint: str,
) -> str:
    if not signature or len(signature) > MAX_OPENPGP_EVIDENCE_BYTES:
        raise ValidationError("detached signature size is invalid")
    if not public_key or len(public_key) > MAX_OPENPGP_EVIDENCE_BYTES:
        raise ValidationError("custodian public key size is invalid")
    with tempfile.TemporaryDirectory(prefix="hf-phase0-anchor-") as directory:
        root = Path(directory)
        gnupg_home = root / "gnupg"
        gnupg_home.mkdir(mode=0o700)
        payload_path = root / "anchor.json"
        signature_path = root / "anchor.sig"
        key_path = root / "custodian.pub"
        payload_path.write_bytes(payload)
        signature_path.write_bytes(signature)
        key_path.write_bytes(public_key)
        try:
            inspect = subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--homedir",
                    str(gnupg_home),
                    "--with-colons",
                    "--import-options",
                    "show-only",
                    "--import",
                    str(key_path),
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise ValidationError("GnuPG verifier is unavailable") from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValidationError("GnuPG key inspection failed") from exc
        if inspect.returncode != 0:
            raise ValidationError("custodian public key cannot be inspected")
        fingerprints = {
            line.split(":")[9].upper()
            for line in inspect.stdout.decode("utf-8", "replace").splitlines()
            if line.startswith("fpr:") and len(line.split(":")) > 9
        }
        if expected_fingerprint.upper() not in fingerprints:
            raise ValidationError("custodian public key fingerprint mismatch")
        try:
            imported = subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--homedir",
                    str(gnupg_home),
                    "--import",
                    str(key_path),
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValidationError("GnuPG key import failed") from exc
        if imported.returncode != 0:
            raise ValidationError("custodian public key cannot be imported")
        try:
            verified = subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--homedir",
                    str(gnupg_home),
                    "--status-fd",
                    "1",
                    "--verify",
                    str(signature_path),
                    str(payload_path),
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValidationError("GnuPG signature verification failed") from exc
        if verified.returncode != 0:
            raise IntegrityError("access anchor detached signature is invalid")
        valid_signers = {
            line.split()[2].upper()
            for line in verified.stdout.decode("utf-8", "replace").splitlines()
            if line.startswith("[GNUPG:] VALIDSIG ") and len(line.split()) > 2
        }
        if valid_signers != {expected_fingerprint.upper()}:
            raise IntegrityError("access anchor was signed by an unexpected key")
    return next(iter(valid_signers))


def verify_access_anchor_v4(
    anchor: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    expected_signing_key_fingerprint: str,
    access_events: Iterable[dict[str, Any]],
    seal_receipt: dict[str, Any],
    evaluated_at: str,
    previous_anchor: VerifiedAccessAnchor | None = None,
    signature_verifier: SignatureVerifier | None = None,
) -> VerifiedAccessAnchor:
    validate_v4(anchor, "access-anchor.schema.json")
    events = list(access_events)
    if anchor["seal_id"] != seal_receipt["seal_id"]:
        raise ValidationError("access anchor seal binding mismatch")
    if anchor["seal_receipt_sha256"] != canonical_sha256(seal_receipt):
        raise ValidationError("access anchor receipt binding mismatch")
    verify_access_chain(
        events,
        expected_head=anchor["head_event_sha256"],
        expected_count=anchor["event_count"],
    )
    if any(event["seal_id"] != anchor["seal_id"] for event in events):
        raise ValidationError("access log contains another seal_id")
    if events[0]["action"] != "seal_created":
        raise ValidationError("access log must begin with seal_created")
    anchored = _parse_time(anchor["anchored_at"], "anchored_at")
    valid_until = _parse_time(anchor["valid_until"], "valid_until")
    evaluated = _parse_time(evaluated_at, "evaluated_at")
    receipt_created = _parse_time(seal_receipt["created_at"], "seal created_at")
    event_times = [_parse_time(event["at"], "access event at") for event in events]
    if event_times != sorted(event_times):
        raise ValidationError("access-log timestamps are not chronological")
    if event_times[0] < receipt_created:
        raise ValidationError("access log predates its seal receipt")
    if event_times[-1] > anchored or anchored < receipt_created:
        raise ValidationError("access anchor predates the evidence it anchors")
    if valid_until <= anchored or valid_until - anchored > ANCHOR_MAX_AGE:
        raise ValidationError("access anchor validity window exceeds 72 hours")
    if anchored > evaluated:
        raise ValidationError("access anchor is from the future")
    if evaluated > valid_until:
        raise ValidationError("access anchor is stale")
    if anchor["signing_key_fingerprint"] != expected_signing_key_fingerprint:
        raise ValidationError("access anchor signing fingerprint mismatch")
    if previous_anchor is None:
        if anchor["sequence"] != 1 or anchor["previous_anchor_sha256"] is not None:
            raise ValidationError("access anchor genesis is invalid")
    else:
        if anchor["sequence"] != previous_anchor.anchor["sequence"] + 1:
            raise ValidationError("access anchor sequence is not monotonic")
        if anchor["previous_anchor_sha256"] != previous_anchor.sha256:
            raise ValidationError("access anchor chain binding mismatch")
        if anchor["seal_id"] != previous_anchor.anchor["seal_id"]:
            raise ValidationError("access anchor chain crosses seals")
    verifier = signature_verifier or _verify_detached_signature_gpg
    observed_fingerprint = verifier(
        canonical_bytes(anchor),
        signature,
        public_key,
        expected_signing_key_fingerprint,
    ).upper()
    if observed_fingerprint != expected_signing_key_fingerprint.upper():
        raise ValidationError("signature verifier returned another key fingerprint")
    return VerifiedAccessAnchor(
        anchor=anchor,
        sha256=canonical_sha256(anchor),
        signature_sha256=sha256_bytes(signature),
        public_key_sha256=sha256_bytes(public_key),
        signing_key_fingerprint=observed_fingerprint,
    )
