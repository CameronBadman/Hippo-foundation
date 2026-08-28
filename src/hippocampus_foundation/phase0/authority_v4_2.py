"""Workspace-internal OAuth and artifact-specific acquisition authority."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .canonical import canonical_bytes, canonical_sha256, sha256_bytes
from .errors import IntegrityError, ValidationError
from .v4_2_contracts import validate_v4_2

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_ROOT = "/content/drive/Shareddrives/Data/graph-memory-data-lake"
MARKER_FILENAME = ".entor-drive-identity-v1.json"
MAX_OAUTH_CONFIG_BYTES = 64 * 1024
OAUTH_AUTHORITY_MAX_AGE = timedelta(days=365)
ACQUISITION_AUTHORITY_MAX_AGE = timedelta(hours=24)
DRIVE_ACCESS_PROOF_MAX_AGE = timedelta(minutes=15)

# Activation is a separate reviewed commit after an Entor Workspace
# administrator supplies the non-secret policy and public signing keys.
APPROVED_OAUTH_AUTHORITY_POLICY_SHA256: str | None = None

SignatureVerifier = Callable[[bytes, bytes, bytes, str], str]


@dataclass(frozen=True)
class OAuthConfigIdentity:
    sha256: str
    client_id_sha256: str
    cloud_project_number: str


@dataclass(frozen=True)
class VerifiedOAuthAuthority:
    payload: dict[str, Any]
    receipt: dict[str, Any]
    sha256: str
    signature_sha256: str
    public_key_sha256: str
    signing_key_fingerprint: str


@dataclass(frozen=True)
class VerifiedAcquisitionAuthorization:
    payload: dict[str, Any]
    receipt: dict[str, Any]
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


def _unique_object(raw: str, *, label: str = "JSON document") -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
    except (UnicodeError, ValueError) as exc:
        raise ValidationError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    return value


def _read_private_bytes(path: Path, *, maximum_bytes: int, label: str) -> bytes:
    if not path.is_absolute():
        raise ValidationError(f"{label} path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValidationError(f"{label} is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o077
            or before.st_size <= 0
            or before.st_size > maximum_bytes
        ):
            raise ValidationError(f"{label} is not a private regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ValidationError(f"{label} cannot be read") from exc
    finally:
        os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if len(raw) > maximum_bytes or len(raw) != before.st_size:
        raise ValidationError(f"{label} size changed or exceeded its limit")
    if identity_before != identity_after:
        raise ValidationError(f"{label} changed while it was read")
    return raw


def _is_local_redirect(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        and parsed.username is None
        and parsed.password is None
        and (port is None or 1 <= port <= 65535)
    )


def load_oauth_config_identity(path: Path) -> OAuthConfigIdentity:
    """Return only a protected OAuth file's digest and project number."""

    try:
        encoded = _read_private_bytes(
            path,
            maximum_bytes=MAX_OAUTH_CONFIG_BYTES,
            label="OAuth client configuration",
        )
        root = _unique_object(
            encoded.decode("utf-8", errors="strict"),
            label="OAuth client configuration",
        )
    except UnicodeError as exc:
        raise ValidationError("OAuth client configuration is not UTF-8") from exc
    installed = root.get("installed")
    if set(root) != {"installed"} or not isinstance(installed, dict):
        raise ValidationError("OAuth client configuration is not an installed app")
    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")
    auth_uri = installed.get("auth_uri")
    token_uri = installed.get("token_uri")
    redirect_uris = installed.get("redirect_uris")
    if not (
        isinstance(client_id, str)
        and client_id.endswith(".apps.googleusercontent.com")
        and isinstance(client_secret, str)
        and bool(client_secret)
        and auth_uri
        in {
            "https://accounts.google.com/o/oauth2/auth",
            "https://accounts.google.com/o/oauth2/v2/auth",
        }
        and token_uri == "https://oauth2.googleapis.com/token"
        and isinstance(redirect_uris, list)
        and any(_is_local_redirect(uri) for uri in redirect_uris)
    ):
        raise ValidationError("OAuth client configuration shape is invalid")
    project_number = client_id.split("-", 1)[0]
    if not project_number.isdigit() or not 6 <= len(project_number) <= 30:
        raise ValidationError("OAuth client ID does not expose a project number")
    return OAuthConfigIdentity(
        sha256=sha256_bytes(encoded),
        client_id_sha256=sha256_bytes(client_id.encode("utf-8")),
        cloud_project_number=project_number,
    )


def validate_authority_policy(
    policy: dict[str, Any],
    *,
    approved_policy_sha256: str | None = None,
) -> str:
    validate_v4_2(policy, "authority-policy.schema.json")
    observed = canonical_sha256(policy)
    expected = (
        APPROVED_OAUTH_AUTHORITY_POLICY_SHA256
        if approved_policy_sha256 is None
        else approved_policy_sha256
    )
    if expected is None:
        raise ValidationError("approved Entor OAuth authority policy is unavailable")
    if observed != expected:
        raise IntegrityError("OAuth authority policy does not match its approved root")
    if policy["status"] != "approved":
        raise ValidationError("OAuth authority policy is not approved")
    if not policy["oauth_authority_signing_key_fingerprints"]:
        raise ValidationError("OAuth authority policy has no trusted administrator")
    if not policy["acquisition_authority_signing_key_fingerprints"]:
        raise ValidationError("OAuth authority policy has no acquisition authorizer")
    if not policy["cloud_project_numbers"]:
        raise ValidationError("OAuth authority policy has no approved Cloud project")
    return observed


def make_oauth_authority_payload(
    *,
    policy: dict[str, Any],
    approved_policy_sha256: str,
    oauth_config: OAuthConfigIdentity,
    authority_id: str,
    provider_resource_id: str,
    root_resource_id: str,
    marker_file_id: str,
    marker_sha256: str,
    approved_at: str,
    valid_until: str,
    approver_id: str,
    signing_key_fingerprint: str,
) -> dict[str, Any]:
    policy_sha256 = validate_authority_policy(
        policy, approved_policy_sha256=approved_policy_sha256
    )
    if oauth_config.cloud_project_number not in policy["cloud_project_numbers"]:
        raise ValidationError("OAuth client Cloud project is not approved")
    payload = {
        "schema_version": "4.2.0",
        "record_kind": "oauth_authority_payload",
        "authority_id": authority_id,
        "authority_policy_sha256": policy_sha256,
        "oauth_config_sha256": oauth_config.sha256,
        "oauth_client_id_sha256": oauth_config.client_id_sha256,
        "workspace_domain": policy["workspace_domain"],
        "workspace_customer_id_sha256": policy["workspace_customer_id_sha256"],
        "cloud_project_number": oauth_config.cloud_project_number,
        "oauth_user_type": "internal",
        "approved_scopes": [DRIVE_READONLY_SCOPE],
        "provider_resource_id": provider_resource_id,
        "root_resource_id": root_resource_id,
        "marker_file_id": marker_file_id,
        "marker_filename": MARKER_FILENAME,
        "marker_sha256": marker_sha256,
        "approved_at": approved_at,
        "valid_until": valid_until,
        "approver_id": approver_id,
        "signing_key_fingerprint": signing_key_fingerprint.upper(),
        "contains_credentials": False,
        "training_authorized": False,
    }
    validate_v4_2(payload, "execution-evidence.schema.json")
    approved = _parse_time(approved_at, "approved_at")
    expires = _parse_time(valid_until, "valid_until")
    if expires <= approved or expires - approved > OAUTH_AUTHORITY_MAX_AGE:
        raise ValidationError("OAuth authority validity exceeds 365 days")
    if (
        payload["signing_key_fingerprint"]
        not in policy["oauth_authority_signing_key_fingerprints"]
    ):
        raise ValidationError("OAuth authority signer is not trusted")
    return payload


def verify_oauth_authority(
    payload: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    policy: dict[str, Any],
    approved_policy_sha256: str | None = None,
    signature_verifier: SignatureVerifier,
) -> VerifiedOAuthAuthority:
    validate_v4_2(payload, "execution-evidence.schema.json")
    policy_sha256 = validate_authority_policy(
        policy, approved_policy_sha256=approved_policy_sha256
    )
    if payload["record_kind"] != "oauth_authority_payload":
        raise ValidationError("expected an OAuth authority payload")
    if payload["authority_policy_sha256"] != policy_sha256:
        raise ValidationError("OAuth authority policy binding mismatch")
    expected = payload["signing_key_fingerprint"]
    if expected not in policy["oauth_authority_signing_key_fingerprints"]:
        raise ValidationError("OAuth authority signer is not trusted")
    if payload["workspace_domain"] != policy["workspace_domain"]:
        raise ValidationError("OAuth authority Workspace domain mismatch")
    if (
        payload["workspace_customer_id_sha256"]
        != policy["workspace_customer_id_sha256"]
    ):
        raise ValidationError("OAuth authority Workspace customer mismatch")
    if payload["cloud_project_number"] not in policy["cloud_project_numbers"]:
        raise ValidationError("OAuth authority Cloud project mismatch")
    approved = _parse_time(payload["approved_at"], "approved_at")
    expires = _parse_time(payload["valid_until"], "valid_until")
    if expires <= approved or expires - approved > OAUTH_AUTHORITY_MAX_AGE:
        raise ValidationError("OAuth authority validity exceeds 365 days")
    observed = signature_verifier(
        canonical_bytes(payload), signature, public_key, expected
    ).upper()
    if observed != expected:
        raise IntegrityError("OAuth authority signature uses another key")
    receipt = {
        "schema_version": "4.2.0",
        "record_kind": "oauth_authority_receipt",
        "authority_id": payload["authority_id"],
        "authority_policy_sha256": policy_sha256,
        "payload_sha256": canonical_sha256(payload),
        "signature_sha256": sha256_bytes(signature),
        "public_key_sha256": sha256_bytes(public_key),
        "signing_key_fingerprint": observed,
        "oauth_config_sha256": payload["oauth_config_sha256"],
        "oauth_client_id_sha256": payload["oauth_client_id_sha256"],
        "workspace_domain": payload["workspace_domain"],
        "cloud_project_number": payload["cloud_project_number"],
        "provider_resource_id": payload["provider_resource_id"],
        "root_resource_id": payload["root_resource_id"],
        "marker_file_id": payload["marker_file_id"],
        "marker_sha256": payload["marker_sha256"],
        "approved_at": payload["approved_at"],
        "valid_until": payload["valid_until"],
        "contains_credentials": False,
        "training_authorized": False,
    }
    validate_v4_2(receipt, "execution-evidence.schema.json")
    return VerifiedOAuthAuthority(
        payload=payload,
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        signature_sha256=receipt["signature_sha256"],
        public_key_sha256=receipt["public_key_sha256"],
        signing_key_fingerprint=observed,
    )


def validate_oauth_authority_time(
    authority: VerifiedOAuthAuthority, *, evaluated_at: str
) -> None:
    evaluated = _parse_time(evaluated_at, "evaluated_at")
    approved = _parse_time(authority.receipt["approved_at"], "approved_at")
    expires = _parse_time(authority.receipt["valid_until"], "valid_until")
    if evaluated < approved or evaluated > expires:
        raise ValidationError("OAuth authority is stale or from the future")


def validate_drive_access_proof(
    proof: dict[str, Any],
    *,
    authority: VerifiedOAuthAuthority,
    storage_attestation: Mapping[str, Any],
    evaluated_at: str,
) -> None:
    validate_v4_2(proof, "execution-evidence.schema.json")
    if proof["record_kind"] != "drive_access_proof":
        raise ValidationError("expected a Drive access proof")
    now = _parse_time(evaluated_at, "evaluated_at")
    observed = _parse_time(proof["observed_at"], "observed_at")
    if observed > now or now - observed > DRIVE_ACCESS_PROOF_MAX_AGE:
        raise ValidationError("Drive access proof is stale or from the future")
    bindings = {
        "oauth_authority_receipt_sha256": authority.sha256,
        "oauth_config_sha256": authority.receipt["oauth_config_sha256"],
        "oauth_client_id_sha256": authority.receipt["oauth_client_id_sha256"],
        "provider": storage_attestation["provider"],
        "provider_resource_id": storage_attestation["provider_resource_id"],
        "root_resource_id": storage_attestation["root_resource_id"],
        "observed_root": storage_attestation["observed_root"],
        "marker_file_id": authority.receipt["marker_file_id"],
        "marker_sha256": authority.receipt["marker_sha256"],
    }
    for field, expected in bindings.items():
        if proof[field] != expected:
            raise ValidationError(f"Drive access proof binding mismatch: {field}")


def make_acquisition_authorization_payload(
    *,
    policy: dict[str, Any],
    approved_policy_sha256: str,
    source_registry: Mapping[str, Any],
    artifact_id: str,
    oauth_authority: VerifiedOAuthAuthority,
    storage_attestation: Mapping[str, Any],
    authorization_id: str,
    byte_ceiling: int,
    authorized_at: str,
    valid_until: str,
    authorizer_id: str,
    signing_key_fingerprint: str,
) -> dict[str, Any]:
    policy_sha256 = validate_authority_policy(
        policy, approved_policy_sha256=approved_policy_sha256
    )
    validate_oauth_authority_time(oauth_authority, evaluated_at=authorized_at)
    matches = [
        artifact
        for source in source_registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == artifact_id
    ]
    if len(matches) != 1:
        raise ValidationError("acquisition artifact must resolve exactly once")
    artifact = matches[0]
    expected_bytes = artifact["expected_bytes"]
    if artifact["availability"] != "acquisition_target":
        raise ValidationError(
            "acquisition authorization requires an acquisition target"
        )
    if byte_ceiling < expected_bytes:
        raise ValidationError("acquisition byte ceiling is below the registered size")
    fingerprint = signing_key_fingerprint.upper()
    if fingerprint not in policy["acquisition_authority_signing_key_fingerprints"]:
        raise ValidationError("acquisition authorizer is not trusted")
    payload = {
        "schema_version": "4.2.0",
        "record_kind": "acquisition_authorization_payload",
        "authorization_id": authorization_id,
        "authority_policy_sha256": policy_sha256,
        "artifact_id": artifact_id,
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "oauth_authority_receipt_sha256": oauth_authority.sha256,
        "storage_attestation_sha256": canonical_sha256(storage_attestation),
        "provider_resource_id": storage_attestation["provider_resource_id"],
        "root_resource_id": storage_attestation["root_resource_id"],
        "expected_bytes": expected_bytes,
        "byte_ceiling": byte_ceiling,
        "authorized_at": authorized_at,
        "valid_until": valid_until,
        "authorizer_id": authorizer_id,
        "signing_key_fingerprint": fingerprint,
        "training_authorized": False,
    }
    validate_v4_2(payload, "execution-evidence.schema.json")
    authorized = _parse_time(authorized_at, "authorized_at")
    expires = _parse_time(valid_until, "valid_until")
    if expires <= authorized or expires - authorized > ACQUISITION_AUTHORITY_MAX_AGE:
        raise ValidationError("acquisition authorization validity exceeds 24 hours")
    return payload


def verify_acquisition_authorization(
    payload: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    policy: dict[str, Any],
    source_registry: Mapping[str, Any],
    oauth_authority: VerifiedOAuthAuthority,
    storage_attestation: Mapping[str, Any],
    approved_policy_sha256: str | None = None,
    signature_verifier: SignatureVerifier,
) -> VerifiedAcquisitionAuthorization:
    validate_v4_2(payload, "execution-evidence.schema.json")
    if payload["record_kind"] != "acquisition_authorization_payload":
        raise ValidationError("expected an acquisition authorization payload")
    policy_sha256 = validate_authority_policy(
        policy, approved_policy_sha256=approved_policy_sha256
    )
    expected = payload["signing_key_fingerprint"]
    if expected not in policy["acquisition_authority_signing_key_fingerprints"]:
        raise ValidationError("acquisition authorizer is not trusted")
    matches = [
        artifact
        for source in source_registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == payload["artifact_id"]
    ]
    if len(matches) != 1:
        raise ValidationError("acquisition artifact must resolve exactly once")
    artifact = matches[0]
    bindings = {
        "authority_policy_sha256": policy_sha256,
        "source_registry_sha256": canonical_sha256(source_registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "oauth_authority_receipt_sha256": oauth_authority.sha256,
        "storage_attestation_sha256": canonical_sha256(storage_attestation),
        "provider_resource_id": storage_attestation["provider_resource_id"],
        "root_resource_id": storage_attestation["root_resource_id"],
        "expected_bytes": artifact["expected_bytes"],
    }
    for field, expected_value in bindings.items():
        if payload[field] != expected_value:
            raise ValidationError(f"acquisition authorization mismatch: {field}")
    if payload["byte_ceiling"] < payload["expected_bytes"]:
        raise ValidationError("acquisition byte ceiling is too small")
    authorized = _parse_time(payload["authorized_at"], "authorized_at")
    expires = _parse_time(payload["valid_until"], "valid_until")
    validate_oauth_authority_time(
        oauth_authority, evaluated_at=payload["authorized_at"]
    )
    if expires <= authorized or expires - authorized > ACQUISITION_AUTHORITY_MAX_AGE:
        raise ValidationError("acquisition authorization validity exceeds 24 hours")
    observed = signature_verifier(
        canonical_bytes(payload), signature, public_key, expected
    ).upper()
    if observed != expected:
        raise IntegrityError("acquisition authorization uses another key")
    receipt = {
        "schema_version": "4.2.0",
        "record_kind": "acquisition_authorization_receipt",
        "authorization_id": payload["authorization_id"],
        "authority_policy_sha256": policy_sha256,
        "artifact_id": payload["artifact_id"],
        "payload_sha256": canonical_sha256(payload),
        "signature_sha256": sha256_bytes(signature),
        "public_key_sha256": sha256_bytes(public_key),
        "signing_key_fingerprint": observed,
        "source_registry_sha256": payload["source_registry_sha256"],
        "artifact_entry_sha256": payload["artifact_entry_sha256"],
        "oauth_authority_receipt_sha256": payload["oauth_authority_receipt_sha256"],
        "storage_attestation_sha256": payload["storage_attestation_sha256"],
        "expected_bytes": payload["expected_bytes"],
        "byte_ceiling": payload["byte_ceiling"],
        "authorized_at": payload["authorized_at"],
        "valid_until": payload["valid_until"],
        "training_authorized": False,
    }
    validate_v4_2(receipt, "execution-evidence.schema.json")
    return VerifiedAcquisitionAuthorization(
        payload=payload,
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        signature_sha256=receipt["signature_sha256"],
        public_key_sha256=receipt["public_key_sha256"],
        signing_key_fingerprint=observed,
    )


def validate_acquisition_authorization_time(
    authorization: VerifiedAcquisitionAuthorization, *, evaluated_at: str
) -> None:
    evaluated = _parse_time(evaluated_at, "evaluated_at")
    authorized = _parse_time(authorization.receipt["authorized_at"], "authorized_at")
    expires = _parse_time(authorization.receipt["valid_until"], "valid_until")
    if evaluated < authorized or evaluated > expires:
        raise ValidationError("acquisition authorization is stale or from the future")
