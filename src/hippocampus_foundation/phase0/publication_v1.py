"""Evidence-bound publication of public source bytes to Hugging Face.

Ambient Hugging Face credentials may prove the current principal, but never grant
publication authority.  The destination, local bytes, rights, obligations, and
parent commit are all pinned before an upload can run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from hippocampus_foundation.licensing import VerifiedBundle

from .canonical import canonical_bytes, canonical_sha256, sha256_bytes
from .errors import IntegrityError, ValidationError
from .inventory import hash_file
from .publication_v1_contracts import (
    validate_publication_schema_lock_v1,
    validate_publication_v1,
)
from .v4_3_contracts import validate_v4_3

SCHEMA_VERSION = "1.0.0"
MAXIMUM_PART_BYTES = 10 * 1024 * 1024 * 1024
REQUIRED_PUBLICATION_USES = frozenset(
    {"acquire", "inventory", "quarantine", "redistribute_source"}
)
REQUIRED_EXCLUDED_USES = frozenset(
    {
        "transform",
        "embed",
        "inference",
        "evaluate",
        "commercial_service",
        "train",
        "redistribute_derived",
        "redistribute_model",
    }
)
DESTINATION_OBSERVATION_MAX_AGE = timedelta(hours=72)

# The configured destination root is filled after the checked policy is generated.
APPROVED_DESTINATION_POLICY_SHA256: str | None = (
    "sha256:5732db9cdf9e9fec46a21e9c1b72a01e415917be1ccd13148900f9282a144e31"
)
# Deliberately unset until accountable reviewers approve a signing policy.
APPROVED_PUBLICATION_AUTHORITY_POLICY_SHA256: str | None = None


class HubClient(Protocol):
    def authenticated_identity(self, policy: Mapping[str, Any]) -> str: ...

    def repo_state(
        self, policy: Mapping[str, Any], *, anonymous: bool
    ) -> dict[str, Any]: ...

    def upload(
        self,
        policy: Mapping[str, Any],
        *,
        local_path: Path | bytes,
        remote_path: str,
        parent_commit: str,
        message: str,
    ) -> str: ...

    def download_small(
        self,
        policy: Mapping[str, Any],
        *,
        remote_path: str,
        revision: str,
        anonymous: bool,
        maximum_bytes: int,
    ) -> bytes: ...

    def hash_remote(
        self,
        policy: Mapping[str, Any],
        *,
        remote_path: str,
        revision: str,
        expected_bytes: int,
    ) -> str: ...


@dataclass(frozen=True)
class VerifiedPublicationRights:
    payload: dict[str, Any]
    receipt: dict[str, Any]
    sha256: str
    signature_sha256: str
    public_key_sha256: str
    signing_key_fingerprint: str


@dataclass(frozen=True)
class VerifiedPublicationAuthorization:
    payload: dict[str, Any]
    receipt: dict[str, Any]
    sha256: str
    signature_sha256: str
    public_key_sha256: str
    signing_key_fingerprint: str


class HuggingFaceHubClient:
    """Small adapter around ``huggingface_hub`` with no token parameters."""

    def __init__(self) -> None:
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:  # pragma: no cover - packaging test covers import
            raise ValidationError("huggingface-hub is not installed") from exc
        self._api_type = HfApi

    @staticmethod
    def _api(policy: Mapping[str, Any], *, token: bool) -> Any:
        from huggingface_hub import HfApi

        return HfApi(endpoint=policy["endpoint"], token=token)

    def authenticated_identity(self, policy: Mapping[str, Any]) -> str:
        api = self._api(policy, token=True)
        api.auth_check(policy["repo_id"], repo_type=policy["repo_type"], write=True)
        identity = api.whoami(token=True)
        name = identity.get("name") if isinstance(identity, dict) else None
        if not isinstance(name, str) or not name:
            raise ValidationError("Hugging Face principal is unavailable")
        return name

    def repo_state(
        self, policy: Mapping[str, Any], *, anonymous: bool
    ) -> dict[str, Any]:
        api = self._api(policy, token=not anonymous)
        info = api.repo_info(
            policy["repo_id"],
            revision=policy["revision"],
            repo_type=policy["repo_type"],
            files_metadata=True,
            token=not anonymous,
        )
        rows = []
        for sibling in api.list_repo_tree(
            policy["repo_id"],
            recursive=True,
            expand=True,
            revision=policy["revision"],
            repo_type=policy["repo_type"],
            token=not anonymous,
        ):
            path = getattr(sibling, "path", None)
            size = getattr(sibling, "size", None)
            if size is None:
                continue
            if not isinstance(path, str) or not isinstance(size, int):
                raise ValidationError("Hugging Face returned incomplete file metadata")
            lfs = getattr(sibling, "lfs", None)
            xet_hash = getattr(sibling, "xet_hash", None)
            digest: str | None = None
            storage_kind = "git"
            if lfs is not None:
                raw = getattr(lfs, "sha256", None) or getattr(lfs, "oid", None)
                if isinstance(raw, str):
                    raw = raw.removeprefix("sha256:")
                    if re.fullmatch(r"[0-9a-f]{64}", raw):
                        digest = f"sha256:{raw}"
                storage_kind = "lfs"
            elif xet_hash is not None:
                # Xet's 64-hex content hash is not treated as a SHA-256 claim.
                storage_kind = "xet"
            rows.append(
                {
                    "path": path,
                    "bytes": size,
                    "sha256": digest,
                    "storage_kind": storage_kind,
                }
            )
        return {
            "repo_id": getattr(info, "id", policy["repo_id"]),
            "private": bool(getattr(info, "private", True)),
            "sha": getattr(info, "sha", None),
            "files": sorted(rows, key=lambda row: row["path"]),
        }

    def upload(
        self,
        policy: Mapping[str, Any],
        *,
        local_path: Path | bytes,
        remote_path: str,
        parent_commit: str,
        message: str,
    ) -> str:
        api = self._api(policy, token=True)
        result = api.upload_file(
            path_or_fileobj=local_path,
            path_in_repo=remote_path,
            repo_id=policy["repo_id"],
            repo_type=policy["repo_type"],
            revision=policy["revision"],
            commit_message=message,
            parent_commit=parent_commit,
            token=True,
        )
        commit = getattr(result, "oid", None)
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValidationError("Hugging Face did not return a commit identifier")
        return commit

    def download_small(
        self,
        policy: Mapping[str, Any],
        *,
        remote_path: str,
        revision: str,
        anonymous: bool,
        maximum_bytes: int,
    ) -> bytes:
        api = self._api(policy, token=not anonymous)
        path = Path(
            api.hf_hub_download(
                repo_id=policy["repo_id"],
                filename=remote_path,
                repo_type=policy["repo_type"],
                revision=revision,
                token=not anonymous,
            )
        )
        size = path.stat().st_size
        if size > maximum_bytes:
            raise ValidationError("remote metadata file exceeds its policy limit")
        return path.read_bytes()

    def hash_remote(
        self,
        policy: Mapping[str, Any],
        *,
        remote_path: str,
        revision: str,
        expected_bytes: int,
    ) -> str:
        from urllib.parse import quote

        import httpx

        url = (
            f"{policy['endpoint']}/datasets/{policy['repo_id']}/resolve/"
            f"{revision}/{quote(remote_path, safe='/')}?download=true"
        )
        digest = hashlib.sha256()
        observed_bytes = 0
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            if response.status_code != 200:
                raise ValidationError(
                    f"anonymous remote hash request failed: {response.status_code}"
                )
            for chunk in response.iter_bytes(chunk_size=8 * 1024 * 1024):
                observed_bytes += len(chunk)
                if observed_bytes > expected_bytes:
                    raise IntegrityError("remote file exceeds its expected size")
                digest.update(chunk)
        if observed_bytes != expected_bytes:
            raise IntegrityError("remote file size differs during anonymous hashing")
        return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _safe_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationError("publication path is not a safe relative path")
    return path


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError) as exc:
        raise ValidationError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    return value


def _artifact_path(policy: Mapping[str, Any], artifact_id: str) -> str:
    matches = [
        item["path"]
        for item in policy["artifact_paths"]
        if item["artifact_id"] == artifact_id
    ]
    if len(matches) != 1:
        raise ValidationError("artifact must have exactly one destination mapping")
    _safe_path(matches[0])
    return matches[0]


def validate_destination_policy(
    policy: dict[str, Any], *, approved_policy_sha256: str | None = None
) -> str:
    validate_publication_v1(policy, "destination-policy.schema.json")
    observed = canonical_sha256(policy)
    expected = (
        APPROVED_DESTINATION_POLICY_SHA256
        if approved_policy_sha256 is None
        else approved_policy_sha256
    )
    if expected is None:
        raise ValidationError("approved publication destination policy is unavailable")
    if observed != expected:
        raise IntegrityError("publication destination policy does not match its root")
    metadata_paths = [item["path"] for item in policy["metadata_paths"]]
    artifact_paths = [item["path"] for item in policy["artifact_paths"]]
    artifact_ids = [item["artifact_id"] for item in policy["artifact_paths"]]
    if (
        len(metadata_paths) != len(set(metadata_paths))
        or len(artifact_paths) != len(set(artifact_paths))
        or len(artifact_ids) != len(set(artifact_ids))
    ):
        raise ValidationError("publication destination mappings are not unique")
    generated = {
        path
        for base in artifact_paths
        for path in (f"{base}.manifest.json", f"{base}.parts/")
    }
    for value in metadata_paths + artifact_paths:
        _safe_path(value)
        if any(value.startswith(prefix) for prefix in policy["excluded_path_prefixes"]):
            raise ValidationError("publication mapping uses an excluded path prefix")
    if any(path in metadata_paths for path in generated):
        raise ValidationError("metadata path collides with a generated artifact path")
    return observed


def validate_publication_authority_policy(
    policy: dict[str, Any], *, approved_policy_sha256: str | None = None
) -> str:
    validate_publication_v1(policy, "authority-policy.schema.json")
    observed = canonical_sha256(policy)
    expected = (
        APPROVED_PUBLICATION_AUTHORITY_POLICY_SHA256
        if approved_policy_sha256 is None
        else approved_policy_sha256
    )
    if expected is None:
        raise ValidationError("approved publication authority policy is unavailable")
    if observed != expected:
        raise IntegrityError("publication authority policy does not match its root")
    if policy["status"] != "approved":
        raise ValidationError("publication authority policy is not approved")
    if not policy["rights_signing_key_fingerprints"]:
        raise ValidationError("publication authority policy has no rights reviewer")
    if not policy["publication_signing_key_fingerprints"]:
        raise ValidationError("publication authority policy has no publisher")
    return observed


def _validate_destination_observation_binding(
    policy: Mapping[str, Any],
    policy_sha256: str,
    observation: dict[str, Any],
    *,
    evaluated_at: str | None = None,
) -> None:
    validate_publication_v1(observation, "evidence.schema.json")
    expected = {
        "record_kind": "hf_destination_observation",
        "destination_policy_sha256": policy_sha256,
        "endpoint": policy["endpoint"],
        "repo_id": policy["repo_id"],
        "repo_type": policy["repo_type"],
        "revision": policy["revision"],
        "visibility": policy["visibility"],
        "write_authorized": True,
        "anonymous_readable": True,
        "contains_credentials": False,
    }
    for field, value in expected.items():
        if observation[field] != value:
            raise ValidationError(f"destination observation binding mismatch: {field}")
    owner = policy["repo_id"].split("/", 1)[0]
    if observation["principal"].casefold() != owner.casefold():
        raise ValidationError("destination observation principal is not the owner")
    paths = [item["path"] for item in observation["files"]]
    if len(paths) != len(set(paths)) or paths != sorted(paths):
        raise ValidationError("destination observation paths are not unique and sorted")
    if evaluated_at is not None:
        now = _parse_time(evaluated_at, "evaluated_at")
        observed = _parse_time(observation["observed_at"], "destination observed_at")
        if observed > now or now - observed > DESTINATION_OBSERVATION_MAX_AGE:
            raise ValidationError("destination observation is stale or from the future")


def _validate_rights_wrapper(rights: VerifiedPublicationRights) -> None:
    validate_publication_v1(rights.payload, "evidence.schema.json")
    validate_publication_v1(rights.receipt, "evidence.schema.json")
    if (
        rights.payload["record_kind"] != "publication_rights_assessment_payload"
        or rights.receipt["record_kind"] != "publication_rights_assessment_receipt"
    ):
        raise ValidationError("invalid publication rights wrapper kinds")
    if rights.sha256 != canonical_sha256(rights.receipt):
        raise ValidationError("publication rights wrapper digest mismatch")
    if rights.receipt["payload_sha256"] != canonical_sha256(rights.payload):
        raise ValidationError("publication rights payload digest mismatch")
    shared = (
        "assessment_id",
        "authority_policy_sha256",
        "destination_policy_sha256",
        "source_id",
        "source_entry_sha256",
        "evidence_bundle_sha256",
        "signing_key_fingerprint",
        "reviewed_at",
        "valid_until",
    )
    if any(rights.receipt[field] != rights.payload[field] for field in shared):
        raise ValidationError("publication rights wrapper field mismatch")
    if (
        rights.signature_sha256 != rights.receipt["signature_sha256"]
        or rights.public_key_sha256 != rights.receipt["public_key_sha256"]
        or rights.signing_key_fingerprint != rights.receipt["signing_key_fingerprint"]
    ):
        raise ValidationError("publication rights wrapper evidence mismatch")


def _validate_publication_authorization_wrapper(
    authorization: VerifiedPublicationAuthorization,
) -> None:
    validate_publication_v1(authorization.payload, "evidence.schema.json")
    validate_publication_v1(authorization.receipt, "evidence.schema.json")
    if (
        authorization.payload["record_kind"] != "publication_authorization_payload"
        or authorization.receipt["record_kind"] != "publication_authorization_receipt"
    ):
        raise ValidationError("invalid publication authorization wrapper kinds")
    if authorization.sha256 != canonical_sha256(authorization.receipt):
        raise ValidationError("publication authorization wrapper digest mismatch")
    if authorization.receipt["payload_sha256"] != canonical_sha256(
        authorization.payload
    ):
        raise ValidationError("publication authorization payload digest mismatch")
    shared = (
        "authorization_id",
        "authority_policy_sha256",
        "destination_policy_sha256",
        "destination_observation_sha256",
        "artifact_id",
        "artifact_clearance_sha256",
        "rights_receipt_sha256",
        "obligations_sha256",
        "artifact_manifest_sha256",
        "local_bytes",
        "local_sha1",
        "local_sha256",
        "initial_head_commit",
        "authorized_at",
        "valid_until",
        "signing_key_fingerprint",
    )
    if any(
        authorization.receipt[field] != authorization.payload[field] for field in shared
    ):
        raise ValidationError("publication authorization wrapper field mismatch")
    if (
        authorization.signature_sha256 != authorization.receipt["signature_sha256"]
        or authorization.public_key_sha256 != authorization.receipt["public_key_sha256"]
        or authorization.signing_key_fingerprint
        != authorization.receipt["signing_key_fingerprint"]
    ):
        raise ValidationError("publication authorization wrapper evidence mismatch")


def _authorization_receipt_from_payload(
    payload: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    observed_fingerprint: str,
) -> dict[str, Any]:
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "publication_authorization_receipt",
        "authorization_id": payload["authorization_id"],
        "authority_policy_sha256": payload["authority_policy_sha256"],
        "destination_policy_sha256": payload["destination_policy_sha256"],
        "destination_observation_sha256": payload["destination_observation_sha256"],
        "payload_sha256": canonical_sha256(payload),
        "signature_sha256": sha256_bytes(signature),
        "public_key_sha256": sha256_bytes(public_key),
        "signing_key_fingerprint": observed_fingerprint,
        "artifact_id": payload["artifact_id"],
        "artifact_clearance_sha256": payload["artifact_clearance_sha256"],
        "rights_receipt_sha256": payload["rights_receipt_sha256"],
        "obligations_sha256": payload["obligations_sha256"],
        "artifact_manifest_sha256": payload["artifact_manifest_sha256"],
        "local_bytes": payload["local_bytes"],
        "local_sha1": payload["local_sha1"],
        "local_sha256": payload["local_sha256"],
        "initial_head_commit": payload["initial_head_commit"],
        "authorized_at": payload["authorized_at"],
        "valid_until": payload["valid_until"],
        "training_authorized": False,
    }
    validate_publication_v1(receipt, "evidence.schema.json")
    return receipt


def verify_historical_publication_authorization(
    payload: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    authority_policy: dict[str, Any],
    destination_policy: dict[str, Any],
    approved_authority_policy_sha256: str | None = None,
    approved_destination_policy_sha256: str | None = None,
    signature_verifier: Any,
) -> VerifiedPublicationAuthorization:
    """Verify the signed core needed to authenticate an earlier Hub receipt chain."""

    validate_publication_v1(payload, "evidence.schema.json")
    if payload["record_kind"] != "publication_authorization_payload":
        raise ValidationError("expected a publication authorization payload")
    authority_sha256 = validate_publication_authority_policy(
        authority_policy,
        approved_policy_sha256=approved_authority_policy_sha256,
    )
    destination_sha256 = validate_destination_policy(
        destination_policy,
        approved_policy_sha256=approved_destination_policy_sha256,
    )
    if (
        payload["authority_policy_sha256"] != authority_sha256
        or payload["destination_policy_sha256"] != destination_sha256
    ):
        raise ValidationError("historical publication authorization policy mismatch")
    fingerprint = payload["signing_key_fingerprint"]
    if fingerprint not in authority_policy["publication_signing_key_fingerprints"]:
        raise ValidationError("historical publication authorizer is not trusted")
    authorized = _parse_time(payload["authorized_at"], "authorized_at")
    expires = _parse_time(payload["valid_until"], "valid_until")
    if expires <= authorized or expires - authorized > timedelta(
        hours=authority_policy["maximum_publication_hours"]
    ):
        raise ValidationError("historical publication validity exceeds policy")
    observed = signature_verifier(
        canonical_bytes(payload), signature, public_key, fingerprint
    ).upper()
    if observed != fingerprint:
        raise IntegrityError("historical publication uses another signing key")
    receipt = _authorization_receipt_from_payload(
        payload,
        signature=signature,
        public_key=public_key,
        observed_fingerprint=observed,
    )
    return VerifiedPublicationAuthorization(
        payload=payload,
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        signature_sha256=receipt["signature_sha256"],
        public_key_sha256=receipt["public_key_sha256"],
        signing_key_fingerprint=observed,
    )


def observe_destination(
    *,
    policy: dict[str, Any],
    client: HubClient,
    observed_at: str | None = None,
    prior_publication_receipts: Iterable[dict[str, Any]] = (),
    prior_publication_authorizations: Iterable[VerifiedPublicationAuthorization] = (),
    prior_publication_manifests: Iterable[dict[str, Any]] = (),
    approved_policy_sha256: str | None = None,
) -> dict[str, Any]:
    policy_sha256 = validate_destination_policy(
        policy, approved_policy_sha256=approved_policy_sha256
    )
    principal = client.authenticated_identity(policy)
    authenticated = client.repo_state(policy, anonymous=False)
    anonymous = client.repo_state(policy, anonymous=True)
    expected_owner = policy["repo_id"].split("/", 1)[0]
    if principal.casefold() != expected_owner.casefold():
        raise ValidationError("authenticated principal does not own the destination")
    for label, state in (("authenticated", authenticated), ("anonymous", anonymous)):
        if state["repo_id"].casefold() != policy["repo_id"].casefold():
            raise ValidationError(f"{label} repository identity mismatch")
        if state["private"]:
            raise ValidationError(f"{label} repository is not public")
        if not isinstance(state["sha"], str) or not re.fullmatch(
            r"[0-9a-f]{40}", state["sha"]
        ):
            raise ValidationError(f"{label} repository head is invalid")
    if authenticated["sha"] != anonymous["sha"]:
        raise IntegrityError("authenticated and anonymous repository heads differ")
    file_map = {row["path"]: dict(row) for row in anonymous["files"]}
    if len(file_map) != len(anonymous["files"]):
        raise ValidationError("destination contains duplicate file paths")
    prior_receipts = list(prior_publication_receipts)
    prior_authorizations = list(prior_publication_authorizations)
    prior_manifests = list(prior_publication_manifests)
    authorization_map: dict[str, VerifiedPublicationAuthorization] = {}
    for authorization in prior_authorizations:
        _validate_publication_authorization_wrapper(authorization)
        if authorization.receipt["destination_policy_sha256"] != policy_sha256:
            raise ValidationError("prior authorization uses another destination")
        if authorization.sha256 in authorization_map:
            raise ValidationError("duplicate prior publication authorization")
        authorization_map[authorization.sha256] = authorization
    manifest_map: dict[str, dict[str, Any]] = {}
    for manifest in prior_manifests:
        validate_artifact_manifest(manifest)
        digest = canonical_sha256(manifest)
        if digest in manifest_map:
            raise ValidationError("duplicate prior publication manifest")
        manifest_map[digest] = manifest
    expected_head = policy["baseline_commit"]
    expected_paths = {item["path"] for item in policy["metadata_paths"]}
    expected_published: dict[str, tuple[int, str]] = {}
    seen_artifacts: set[str] = set()
    for receipt in prior_receipts:
        validate_publication_v1(receipt, "evidence.schema.json")
        if (
            receipt["record_kind"] != "hf_publication_receipt"
            or not receipt["complete"]
            or receipt["destination_policy_sha256"] != policy_sha256
            or receipt["initial_head_commit"] != expected_head
            or receipt["artifact_id"] in seen_artifacts
        ):
            raise ValidationError("prior publication receipt chain is invalid")
        authorization = authorization_map.get(receipt["authorization_receipt_sha256"])
        if authorization is None:
            raise ValidationError("prior publication receipt lacks signed authority")
        manifest = manifest_map.get(receipt["manifest_sha256"])
        if manifest is None:
            raise ValidationError("prior publication receipt lacks its signed manifest")
        if (
            authorization.payload["source_registry_sha256"]
            != receipt["source_registry_sha256"]
            or authorization.payload["artifact_entry_sha256"]
            != receipt["artifact_entry_sha256"]
            or authorization.receipt["artifact_id"] != receipt["artifact_id"]
            or authorization.receipt["artifact_clearance_sha256"]
            != receipt["artifact_clearance_sha256"]
            or authorization.receipt["artifact_manifest_sha256"]
            != receipt["manifest_sha256"]
            or authorization.receipt["local_bytes"] != receipt["local_bytes"]
            or authorization.receipt["local_sha1"] != receipt["local_sha1"]
            or authorization.receipt["local_sha256"] != receipt["local_sha256"]
            or authorization.receipt["initial_head_commit"]
            != receipt["initial_head_commit"]
            or manifest["artifact_id"] != receipt["artifact_id"]
            or manifest["source_registry_sha256"] != receipt["source_registry_sha256"]
            or manifest["artifact_entry_sha256"] != receipt["artifact_entry_sha256"]
            or manifest["original_bytes"] != receipt["local_bytes"]
            or manifest["original_sha1"] != receipt["local_sha1"]
            or manifest["original_sha256"] != receipt["local_sha256"]
        ):
            raise ValidationError("prior publication receipt authority mismatch")
        if not (
            _parse_time(authorization.receipt["authorized_at"], "authorized_at")
            <= _parse_time(receipt["started_at"], "publication started_at")
            <= _parse_time(authorization.receipt["valid_until"], "valid_until")
        ):
            raise ValidationError("prior publication began outside signed authority")
        manifest_bytes = canonical_bytes(manifest)
        expected_commits = [
            {
                "path": part["path"],
                "sha256": part["sha256"],
                "bytes": part["bytes"],
            }
            for part in manifest["parts"]
        ] + [
            {
                "path": f"{manifest['original_path']}.manifest.json",
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "bytes": len(manifest_bytes),
            }
        ]
        observed_commits = [
            {key: item[key] for key in ("path", "sha256", "bytes")}
            for item in receipt["commits"]
        ]
        if (
            observed_commits != expected_commits
            or receipt["manifest_path"] != expected_commits[-1]["path"]
            or receipt["commits"][-1]["commit"] != receipt["final_head_commit"]
            or _parse_time(receipt["completed_at"], "publication completed_at")
            < _parse_time(receipt["started_at"], "publication started_at")
        ):
            raise ValidationError("prior publication receipt content is invalid")
        seen_artifacts.add(receipt["artifact_id"])
        expected_head = receipt["final_head_commit"]
        for commit in receipt["commits"]:
            if commit["path"] in expected_published:
                raise ValidationError("prior publication receipts reuse a path")
            expected_published[commit["path"]] = (
                commit["bytes"],
                f"sha256:{commit['sha256']}",
            )
            expected_paths.add(commit["path"])
    if set(authorization_map) != {
        receipt["authorization_receipt_sha256"] for receipt in prior_receipts
    }:
        raise ValidationError("unused or missing prior publication authorization")
    if set(manifest_map) != {receipt["manifest_sha256"] for receipt in prior_receipts}:
        raise ValidationError("unused or missing prior publication manifest")
    if anonymous["sha"] != expected_head:
        raise IntegrityError("repository head is not the authorized receipt-chain tip")
    if set(file_map) != expected_paths:
        raise IntegrityError("destination file set contains missing or extra paths")
    for expected in policy["metadata_paths"]:
        path = expected["path"]
        if path not in file_map:
            raise ValidationError(f"required destination metadata is missing: {path}")
        row = file_map[path]
        if row["bytes"] > expected["maximum_bytes"]:
            raise ValidationError(f"destination metadata exceeds its limit: {path}")
        if not expected["platform_managed"]:
            raw = client.download_small(
                policy,
                remote_path=path,
                revision=anonymous["sha"],
                anonymous=True,
                maximum_bytes=expected["maximum_bytes"],
            )
            digest = sha256_bytes(raw)
            if digest != expected["sha256"]:
                raise IntegrityError(f"destination metadata digest mismatch: {path}")
            row["sha256"] = digest
    for path, (expected_bytes, expected_digest) in expected_published.items():
        row = file_map[path]
        if row["bytes"] != expected_bytes:
            raise IntegrityError(f"published destination size mismatch: {path}")
        digest = row["sha256"]
        if digest is None:
            digest = f"sha256:{client.hash_remote(policy, remote_path=path, revision=anonymous['sha'], expected_bytes=expected_bytes)}"
            row["sha256"] = digest
        if digest != expected_digest:
            raise IntegrityError(f"published destination digest mismatch: {path}")
    for manifest in prior_manifests:
        manifest_path = f"{manifest['original_path']}.manifest.json"
        remote = client.download_small(
            policy,
            remote_path=manifest_path,
            revision=anonymous["sha"],
            anonymous=True,
            maximum_bytes=16 * 1024 * 1024,
        )
        if remote != canonical_bytes(manifest):
            raise IntegrityError("prior remote manifest differs from signed evidence")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "hf_destination_observation",
        "destination_policy_sha256": policy_sha256,
        "endpoint": policy["endpoint"],
        "repo_id": policy["repo_id"],
        "repo_type": policy["repo_type"],
        "revision": policy["revision"],
        "visibility": policy["visibility"],
        "principal": principal,
        "write_authorized": True,
        "anonymous_readable": True,
        "head_commit": anonymous["sha"],
        "observed_at": observed_at or _utc_now(),
        "files": sorted(file_map.values(), key=lambda row: row["path"]),
        "contains_credentials": False,
        "training_authorized": False,
    }
    validate_publication_v1(result, "evidence.schema.json")
    _validate_destination_observation_binding(
        policy, policy_sha256, result, evaluated_at=result["observed_at"]
    )
    return result


def scaffold_publication_rights_payload(
    *,
    authority_policy: dict[str, Any],
    destination_policy: dict[str, Any],
    source_id: str,
    source_entry: dict[str, Any],
    evidence_bundle: VerifiedBundle,
    assessment_id: str,
) -> dict[str, Any]:
    """Create a non-approving packet; it cannot manufacture human judgment."""

    validate_publication_v1(authority_policy, "authority-policy.schema.json")
    validate_publication_v1(destination_policy, "destination-policy.schema.json")
    bundle = evidence_bundle.bundle
    if evidence_bundle.sha256 != canonical_sha256(bundle):
        raise ValidationError("verified licence bundle wrapper digest mismatch")
    if bundle["subject_id"] != source_id:
        raise ValidationError("licence bundle subject does not match the source")
    if bundle["subject_binding_sha256"] != canonical_sha256(source_entry):
        raise ValidationError("licence bundle source-entry binding mismatch")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "publication_rights_assessment_payload",
        "assessment_id": assessment_id,
        "authority_policy_sha256": canonical_sha256(authority_policy),
        "destination_policy_sha256": canonical_sha256(destination_policy),
        "source_id": source_id,
        "source_entry_sha256": canonical_sha256(source_entry),
        "evidence_bundle_sha256": evidence_bundle.sha256,
        "decision": "pending",
        "commercial_context": "unclear",
        "licence_identifiers": ["pending-human-review"],
        "allowed_uses": [],
        "excluded_uses": sorted(REQUIRED_EXCLUDED_USES),
        "obligations": [],
        "finding_dispositions": [
            {
                "finding_id": finding["finding_id"],
                "disposition": "acknowledged_nonblocking",
                "rationale_document_id": None,
            }
            for finding in bundle["findings"]
            if not finding["blocking"]
        ],
        "reviewer_id": None,
        "reviewed_at": None,
        "valid_until": None,
        "signing_key_fingerprint": None,
        "training_authorized": False,
    }
    validate_publication_v1(result, "evidence.schema.json")
    return result


def verify_publication_rights(
    payload: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    authority_policy: dict[str, Any],
    destination_policy: dict[str, Any],
    source_id: str,
    source_entry: dict[str, Any],
    evidence_bundle: VerifiedBundle,
    evaluated_at: str,
    approved_authority_policy_sha256: str | None = None,
    approved_destination_policy_sha256: str | None = None,
    signature_verifier: Any,
) -> VerifiedPublicationRights:
    validate_publication_v1(payload, "evidence.schema.json")
    if payload["record_kind"] != "publication_rights_assessment_payload":
        raise ValidationError("expected a publication rights assessment payload")
    authority_sha256 = validate_publication_authority_policy(
        authority_policy,
        approved_policy_sha256=approved_authority_policy_sha256,
    )
    destination_sha256 = validate_destination_policy(
        destination_policy,
        approved_policy_sha256=approved_destination_policy_sha256,
    )
    bundle = evidence_bundle.bundle
    if evidence_bundle.sha256 != canonical_sha256(bundle):
        raise ValidationError("verified licence bundle wrapper digest mismatch")
    expected = {
        "authority_policy_sha256": authority_sha256,
        "destination_policy_sha256": destination_sha256,
        "source_id": source_id,
        "source_entry_sha256": canonical_sha256(source_entry),
        "evidence_bundle_sha256": evidence_bundle.sha256,
    }
    for field, value in expected.items():
        if payload[field] != value:
            raise ValidationError(f"publication rights binding mismatch: {field}")
    if bundle["subject_id"] != source_id or bundle[
        "subject_binding_sha256"
    ] != canonical_sha256(source_entry):
        raise ValidationError("licence bundle does not bind the source entry")
    if payload["decision"] != "approved" or payload["commercial_context"] != "allowed":
        raise ValidationError("source redistribution rights are not approved")
    if set(payload["allowed_uses"]) != REQUIRED_PUBLICATION_USES:
        raise ValidationError("publication rights do not allow the exact required uses")
    if set(payload["excluded_uses"]) != REQUIRED_EXCLUDED_USES:
        raise ValidationError("publication rights exclusions are incomplete")
    if not payload["licence_identifiers"] or not payload["obligations"]:
        raise ValidationError("approved publication rights lack licence obligations")
    obligation_ids = [item["obligation_id"] for item in payload["obligations"]]
    if len(obligation_ids) != len(set(obligation_ids)):
        raise ValidationError("publication obligations contain duplicate IDs")
    dispositions = {
        item["finding_id"]: item for item in payload["finding_dispositions"]
    }
    finding_ids = {item["finding_id"] for item in bundle["findings"]}
    if set(dispositions) != finding_ids:
        raise ValidationError("publication rights do not cover every evidence finding")
    unresolved = [
        item["finding_id"]
        for item in bundle["findings"]
        if item["blocking"]
        and dispositions[item["finding_id"]]["disposition"] != "resolved"
    ]
    if unresolved:
        raise ValidationError(
            f"blocking publication findings remain: {sorted(unresolved)}"
        )
    reviewer = payload["reviewer_id"]
    reviewed_at = payload["reviewed_at"]
    valid_until = payload["valid_until"]
    fingerprint = payload["signing_key_fingerprint"]
    if not all(
        isinstance(value, str) and value
        for value in (reviewer, reviewed_at, valid_until, fingerprint)
    ):
        raise ValidationError("approved publication rights lack human review fields")
    fingerprint = fingerprint.upper()
    if fingerprint not in authority_policy["rights_signing_key_fingerprints"]:
        raise ValidationError("publication rights reviewer is not trusted")
    reviewed = _parse_time(reviewed_at, "reviewed_at")
    expires = _parse_time(valid_until, "valid_until")
    now = _parse_time(evaluated_at, "evaluated_at")
    if reviewed > now or expires <= now:
        raise ValidationError("publication rights are stale or from the future")
    if expires > reviewed + timedelta(days=authority_policy["maximum_rights_days"]):
        raise ValidationError("publication rights validity exceeds policy")
    observed = signature_verifier(
        canonical_bytes(payload), signature, public_key, fingerprint
    ).upper()
    if observed != fingerprint:
        raise IntegrityError("publication rights use another signing key")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "publication_rights_assessment_receipt",
        "assessment_id": payload["assessment_id"],
        "authority_policy_sha256": authority_sha256,
        "destination_policy_sha256": destination_sha256,
        "source_id": source_id,
        "source_entry_sha256": payload["source_entry_sha256"],
        "evidence_bundle_sha256": evidence_bundle.sha256,
        "payload_sha256": canonical_sha256(payload),
        "signature_sha256": sha256_bytes(signature),
        "public_key_sha256": sha256_bytes(public_key),
        "signing_key_fingerprint": observed,
        "reviewed_at": reviewed_at,
        "valid_until": valid_until,
        "redistribute_source_authorized": True,
        "training_authorized": False,
    }
    validate_publication_v1(receipt, "evidence.schema.json")
    return VerifiedPublicationRights(
        payload=payload,
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        signature_sha256=receipt["signature_sha256"],
        public_key_sha256=receipt["public_key_sha256"],
        signing_key_fingerprint=observed,
    )


def build_obligation_manifest(
    *,
    rights: VerifiedPublicationRights,
    destination_policy: dict[str, Any],
    destination_observation: dict[str, Any],
    manifest_id: str,
    implementation_refs: Sequence[dict[str, Any]],
    operational_evidence_sha256s: Iterable[str] = (),
    assembled_at: str | None = None,
    approved_destination_policy_sha256: str | None = None,
) -> dict[str, Any]:
    destination_sha256 = validate_destination_policy(
        destination_policy,
        approved_policy_sha256=approved_destination_policy_sha256,
    )
    _validate_rights_wrapper(rights)
    assembled = assembled_at or _utc_now()
    _validate_destination_observation_binding(
        destination_policy,
        destination_sha256,
        destination_observation,
        evaluated_at=assembled,
    )
    assembled_time = _parse_time(assembled, "assembled_at")
    if assembled_time < _parse_time(rights.receipt["reviewed_at"], "reviewed_at"):
        raise ValidationError("publication obligations predate the rights review")
    required = {item["obligation_id"] for item in rights.payload["obligations"]}
    supplied = [item["obligation_id"] for item in implementation_refs]
    if set(supplied) != required:
        raise ValidationError(
            "obligation implementations do not cover exact obligations"
        )
    pairs = [
        (item["obligation_id"], item["evidence_kind"]) for item in implementation_refs
    ]
    if len(pairs) != len(set(pairs)):
        raise ValidationError("duplicate obligation implementation")
    public_files = {item["path"]: item for item in destination_observation["files"]}
    operational = set(operational_evidence_sha256s)
    for item in implementation_refs:
        if item["evidence_kind"] == "public_file":
            row = public_files.get(item["path"])
            if row is None or row["sha256"] != item["sha256"]:
                raise ValidationError(
                    "public obligation evidence is absent or unverified"
                )
        elif item["path"] is not None or item["sha256"] not in operational:
            raise ValidationError("operational obligation evidence is not supplied")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "publication_obligation_manifest",
        "manifest_id": manifest_id,
        "rights_receipt_sha256": rights.sha256,
        "destination_policy_sha256": destination_sha256,
        "destination_observation_sha256": canonical_sha256(destination_observation),
        "implementation_refs": list(implementation_refs),
        "assembled_at": assembled,
        "complete": True,
        "training_authorized": False,
    }
    validate_publication_v1(result, "evidence.schema.json")
    return result


def make_publication_authorization_payload(
    *,
    authority_policy: dict[str, Any],
    destination_policy: dict[str, Any],
    destination_observation: dict[str, Any],
    source_registry_sha256: str,
    artifact_id: str,
    artifact_entry_sha256: str,
    artifact_clearance: dict[str, Any],
    rights: VerifiedPublicationRights,
    obligations: dict[str, Any],
    artifact_audit: dict[str, Any],
    artifact_manifest: dict[str, Any],
    authorization_id: str,
    authorized_at: str,
    valid_until: str,
    authorizer_id: str,
    signing_key_fingerprint: str,
    approved_authority_policy_sha256: str,
    approved_destination_policy_sha256: str,
) -> dict[str, Any]:
    authority_sha256 = validate_publication_authority_policy(
        authority_policy,
        approved_policy_sha256=approved_authority_policy_sha256,
    )
    destination_sha256 = validate_destination_policy(
        destination_policy,
        approved_policy_sha256=approved_destination_policy_sha256,
    )
    _validate_rights_wrapper(rights)
    _validate_destination_observation_binding(
        destination_policy,
        destination_sha256,
        destination_observation,
        evaluated_at=authorized_at,
    )
    validate_v4_3(artifact_clearance, "execution-evidence.schema.json")
    validate_v4_3(artifact_audit, "execution-evidence.schema.json")
    validate_publication_v1(obligations, "evidence.schema.json")
    validate_artifact_manifest(artifact_manifest)
    if artifact_clearance["record_kind"] != "artifact_publication_clearance":
        raise ValidationError("expected an artifact publication clearance")
    if not artifact_clearance["ready"]:
        raise ValidationError("artifact publication clearance is not ready")
    expected = {
        "artifact_id": artifact_id,
        "source_registry_sha256": source_registry_sha256,
        "artifact_entry_sha256": artifact_entry_sha256,
    }
    for field, value in expected.items():
        if artifact_clearance[field] != value:
            raise ValidationError(f"artifact clearance binding mismatch: {field}")
    if artifact_clearance["rights_receipt_sha256"] != rights.sha256:
        raise ValidationError("artifact clearance rights binding mismatch")
    if obligations["rights_receipt_sha256"] != rights.sha256:
        raise ValidationError("obligation manifest rights binding mismatch")
    if obligations["destination_observation_sha256"] != canonical_sha256(
        destination_observation
    ):
        raise ValidationError("obligation manifest observation binding mismatch")
    audit_expected = {
        "artifact_id": artifact_id,
        "source_registry_sha256": source_registry_sha256,
        "artifact_entry_sha256": artifact_entry_sha256,
    }
    for field, value in audit_expected.items():
        if artifact_audit[field] != value:
            raise ValidationError(f"artifact audit binding mismatch: {field}")
    manifest_expected = {
        "artifact_id": artifact_id,
        "source_registry_sha256": source_registry_sha256,
        "artifact_entry_sha256": artifact_entry_sha256,
        "original_path": _artifact_path(destination_policy, artifact_id),
        "original_bytes": artifact_audit["bytes"],
        "original_sha1": artifact_audit["sha1"],
        "original_sha256": artifact_audit["sha256"],
    }
    for field, value in manifest_expected.items():
        if artifact_manifest[field] != value:
            raise ValidationError(f"artifact manifest binding mismatch: {field}")
    fingerprint = signing_key_fingerprint.upper()
    if fingerprint not in authority_policy["publication_signing_key_fingerprints"]:
        raise ValidationError("publication authorizer is not trusted")
    authorized = _parse_time(authorized_at, "authorized_at")
    expires = _parse_time(valid_until, "valid_until")
    evidence_times = (
        _parse_time(artifact_clearance["cleared_at"], "clearance cleared_at"),
        _parse_time(artifact_audit["audited_at"], "artifact audited_at"),
        _parse_time(obligations["assembled_at"], "obligations assembled_at"),
        _parse_time(rights.receipt["reviewed_at"], "rights reviewed_at"),
        _parse_time(destination_observation["observed_at"], "destination observed_at"),
    )
    if any(value > authorized for value in evidence_times):
        raise ValidationError("publication authorization predates its evidence")
    rights_expiry = _parse_time(rights.receipt["valid_until"], "rights valid_until")
    maximum = timedelta(hours=authority_policy["maximum_publication_hours"])
    if expires <= authorized or expires - authorized > maximum:
        raise ValidationError("publication authorization validity exceeds policy")
    if expires > rights_expiry:
        raise ValidationError("publication authorization outlives its rights")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "publication_authorization_payload",
        "authorization_id": authorization_id,
        "authority_policy_sha256": authority_sha256,
        "destination_policy_sha256": destination_sha256,
        "destination_observation_sha256": canonical_sha256(destination_observation),
        "source_registry_sha256": source_registry_sha256,
        "artifact_id": artifact_id,
        "artifact_entry_sha256": artifact_entry_sha256,
        "artifact_clearance_sha256": canonical_sha256(artifact_clearance),
        "rights_receipt_sha256": rights.sha256,
        "obligations_sha256": canonical_sha256(obligations),
        "artifact_manifest_sha256": canonical_sha256(artifact_manifest),
        "local_bytes": artifact_audit["bytes"],
        "local_sha1": artifact_audit["sha1"],
        "local_sha256": artifact_audit["sha256"],
        "initial_head_commit": destination_observation["head_commit"],
        "authorized_at": authorized_at,
        "valid_until": valid_until,
        "authorizer_id": authorizer_id,
        "signing_key_fingerprint": fingerprint,
        "training_authorized": False,
    }
    validate_publication_v1(payload, "evidence.schema.json")
    return payload


def verify_publication_authorization(
    payload: dict[str, Any],
    *,
    signature: bytes,
    public_key: bytes,
    authority_policy: dict[str, Any],
    destination_policy: dict[str, Any],
    destination_observation: dict[str, Any],
    artifact_clearance: dict[str, Any],
    rights: VerifiedPublicationRights,
    obligations: dict[str, Any],
    artifact_audit: dict[str, Any],
    artifact_manifest: dict[str, Any],
    approved_authority_policy_sha256: str | None,
    approved_destination_policy_sha256: str | None,
    signature_verifier: Any,
) -> VerifiedPublicationAuthorization:
    validate_publication_v1(payload, "evidence.schema.json")
    if payload["record_kind"] != "publication_authorization_payload":
        raise ValidationError("expected a publication authorization payload")
    authority_sha256 = validate_publication_authority_policy(
        authority_policy,
        approved_policy_sha256=approved_authority_policy_sha256,
    )
    if payload["authority_policy_sha256"] != authority_sha256:
        raise ValidationError("publication authorization policy binding mismatch")
    expected_payload = make_publication_authorization_payload(
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        destination_observation=destination_observation,
        source_registry_sha256=payload["source_registry_sha256"],
        artifact_id=payload["artifact_id"],
        artifact_entry_sha256=payload["artifact_entry_sha256"],
        artifact_clearance=artifact_clearance,
        rights=rights,
        obligations=obligations,
        artifact_audit=artifact_audit,
        artifact_manifest=artifact_manifest,
        authorization_id=payload["authorization_id"],
        authorized_at=payload["authorized_at"],
        valid_until=payload["valid_until"],
        authorizer_id=payload["authorizer_id"],
        signing_key_fingerprint=payload["signing_key_fingerprint"],
        approved_authority_policy_sha256=(
            approved_authority_policy_sha256 or authority_sha256
        ),
        approved_destination_policy_sha256=(
            approved_destination_policy_sha256
            or validate_destination_policy(destination_policy)
        ),
    )
    if expected_payload != payload:
        raise ValidationError("publication authorization evidence graph mismatch")
    fingerprint = payload["signing_key_fingerprint"]
    if fingerprint not in authority_policy["publication_signing_key_fingerprints"]:
        raise ValidationError("publication authorizer is not trusted")
    authorized = _parse_time(payload["authorized_at"], "authorized_at")
    expires = _parse_time(payload["valid_until"], "valid_until")
    maximum = timedelta(hours=authority_policy["maximum_publication_hours"])
    if expires <= authorized or expires - authorized > maximum:
        raise ValidationError("publication authorization validity exceeds policy")
    observed = signature_verifier(
        canonical_bytes(payload), signature, public_key, fingerprint
    ).upper()
    if observed != fingerprint:
        raise IntegrityError("publication authorization uses another signing key")
    receipt = _authorization_receipt_from_payload(
        payload,
        signature=signature,
        public_key=public_key,
        observed_fingerprint=observed,
    )
    return VerifiedPublicationAuthorization(
        payload=payload,
        receipt=receipt,
        sha256=canonical_sha256(receipt),
        signature_sha256=receipt["signature_sha256"],
        public_key_sha256=receipt["public_key_sha256"],
        signing_key_fingerprint=observed,
    )


def validate_publication_authorization_time(
    authorization: VerifiedPublicationAuthorization, *, evaluated_at: str
) -> None:
    _validate_publication_authorization_wrapper(authorization)
    now = _parse_time(evaluated_at, "evaluated_at")
    starts = _parse_time(authorization.receipt["authorized_at"], "authorized_at")
    expires = _parse_time(authorization.receipt["valid_until"], "valid_until")
    if now < starts or now > expires:
        raise ValidationError("publication authorization is stale or from the future")


def plan_parts(
    *, total_bytes: int, base_path: str, maximum_part_bytes: int = MAXIMUM_PART_BYTES
) -> list[dict[str, Any]]:
    """Return a deterministic numeric plan; production policy fixes 10 GiB."""

    _safe_path(base_path)
    if total_bytes <= 0 or maximum_part_bytes <= 0:
        raise ValidationError("part planning sizes must be positive")
    count = (total_bytes + maximum_part_bytes - 1) // maximum_part_bytes
    width = max(5, len(str(count - 1)))
    rows = []
    offset = 0
    for index in range(count):
        size = min(maximum_part_bytes, total_bytes - offset)
        rows.append(
            {
                "index": index,
                "path": f"{base_path}.parts/part-{index:0{width}d}-of-{count:0{width}d}",
                "offset": offset,
                "bytes": size,
            }
        )
        offset += size
    return rows


def build_artifact_manifest(
    *,
    artifact_id: str,
    source_registry_sha256: str,
    artifact_entry_sha256: str,
    base_path: str,
    local_audit: Mapping[str, Any],
    part_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected_plan = plan_parts(
        total_bytes=local_audit["bytes"],
        base_path=base_path,
        maximum_part_bytes=MAXIMUM_PART_BYTES,
    )
    if len(part_rows) != len(expected_plan):
        raise ValidationError("artifact manifest part count is incomplete")
    parts = []
    for expected, supplied in zip(expected_plan, part_rows, strict=True):
        for field in ("index", "path", "offset", "bytes"):
            if supplied[field] != expected[field]:
                raise ValidationError(f"artifact part plan mismatch: {field}")
        digest = supplied.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValidationError("artifact part lacks a SHA-256 digest")
        parts.append({**expected, "sha256": digest})
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "publication_artifact_manifest",
        "artifact_id": artifact_id,
        "source_registry_sha256": source_registry_sha256,
        "artifact_entry_sha256": artifact_entry_sha256,
        "original_path": base_path,
        "original_bytes": local_audit["bytes"],
        "original_sha1": local_audit["sha1"],
        "original_sha256": local_audit["sha256"],
        "maximum_part_bytes": MAXIMUM_PART_BYTES,
        "parts": parts,
        "reassembly": "concatenate_parts_in_index_order",
        "training_authorized": False,
    }
    validate_artifact_manifest(result)
    return result


def inventory_publication_artifact(
    *,
    policy: dict[str, Any],
    artifact_id: str,
    source_registry_sha256: str,
    artifact_entry_sha256: str,
    local_path: Path,
    local_audit: Mapping[str, Any],
    approved_destination_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Hash every deterministic part before authorization or remote mutation."""

    validate_destination_policy(
        policy, approved_policy_sha256=approved_destination_policy_sha256
    )
    measured = hash_file(local_path)
    for field in ("bytes", "sha1", "sha256"):
        if measured[field] != local_audit[field]:
            raise IntegrityError(f"publication inventory local mismatch: {field}")
    base_path = _artifact_path(policy, artifact_id)
    planned = plan_parts(total_bytes=measured["bytes"], base_path=base_path)
    rows = []
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(local_path, flags)
    try:
        with os.fdopen(descriptor, "rb", buffering=0) as source:
            for part in planned:
                digest = hashlib.sha256()
                remaining = part["bytes"]
                while remaining:
                    chunk = source.read(min(8 * 1024 * 1024, remaining))
                    if not chunk:
                        raise IntegrityError(
                            "local artifact ended during part inventory"
                        )
                    digest.update(chunk)
                    remaining -= len(chunk)
                rows.append({**part, "sha256": digest.hexdigest()})
            if source.read(1):
                raise IntegrityError("local artifact exceeds its part inventory")
    except Exception:
        # fdopen owns the descriptor after it is entered.
        raise
    after = hash_file(local_path)
    if after != measured:
        raise IntegrityError("local artifact changed during part inventory")
    return build_artifact_manifest(
        artifact_id=artifact_id,
        source_registry_sha256=source_registry_sha256,
        artifact_entry_sha256=artifact_entry_sha256,
        base_path=base_path,
        local_audit=measured,
        part_rows=rows,
    )


def validate_artifact_manifest(manifest: dict[str, Any]) -> None:
    validate_publication_v1(manifest, "evidence.schema.json")
    if manifest["record_kind"] != "publication_artifact_manifest":
        raise ValidationError("expected a publication artifact manifest")
    expected = plan_parts(
        total_bytes=manifest["original_bytes"],
        base_path=manifest["original_path"],
        maximum_part_bytes=manifest["maximum_part_bytes"],
    )
    if len(expected) != len(manifest["parts"]):
        raise ValidationError("artifact manifest does not cover the original bytes")
    for planned, supplied in zip(expected, manifest["parts"], strict=True):
        for field in ("index", "path", "offset", "bytes"):
            if supplied[field] != planned[field]:
                raise ValidationError(
                    f"artifact manifest is not deterministic: {field}"
                )


def _write_part(source: Any, destination: Path, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            while remaining:
                chunk = source.read(min(8 * 1024 * 1024, remaining))
                if not chunk:
                    raise IntegrityError(
                        "local artifact ended before its planned boundary"
                    )
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _preflight_live_destination(
    *,
    policy: dict[str, Any],
    destination_observation: dict[str, Any],
    client: HubClient,
) -> None:
    """Recheck identity, visibility, head, and layout immediately before mutation."""

    owner = policy["repo_id"].split("/", 1)[0]
    if client.authenticated_identity(policy).casefold() != owner.casefold():
        raise ValidationError("live publication principal is not the destination owner")
    expected_files = {
        item["path"]: item["bytes"] for item in destination_observation["files"]
    }
    for label, state in (
        ("authenticated", client.repo_state(policy, anonymous=False)),
        ("anonymous", client.repo_state(policy, anonymous=True)),
    ):
        if state["repo_id"].casefold() != policy["repo_id"].casefold():
            raise ValidationError(f"live {label} destination identity mismatch")
        if state["private"]:
            raise ValidationError(f"live {label} destination is not public")
        if state["sha"] != destination_observation["head_commit"]:
            raise IntegrityError(f"live {label} destination head changed")
        observed_files = {item["path"]: item["bytes"] for item in state["files"]}
        if (
            len(observed_files) != len(state["files"])
            or observed_files != expected_files
        ):
            raise IntegrityError(f"live {label} destination layout changed")


def publish_artifact(
    *,
    policy: dict[str, Any],
    destination_observation: dict[str, Any],
    authorization: VerifiedPublicationAuthorization,
    artifact_clearance: dict[str, Any],
    artifact_manifest: dict[str, Any],
    local_path: Path,
    client: HubClient,
    approved_destination_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Publish deterministic parts with optimistic parent-commit locking."""

    destination_sha256 = validate_destination_policy(
        policy, approved_policy_sha256=approved_destination_policy_sha256
    )
    now = _utc_now()
    validate_publication_authorization_time(authorization, evaluated_at=now)
    _validate_destination_observation_binding(
        policy,
        destination_sha256,
        destination_observation,
        evaluated_at=now,
    )
    validate_v4_3(artifact_clearance, "execution-evidence.schema.json")
    receipt = authorization.receipt
    expected = {
        "destination_policy_sha256": destination_sha256,
        "destination_observation_sha256": canonical_sha256(destination_observation),
        "artifact_clearance_sha256": canonical_sha256(artifact_clearance),
        "initial_head_commit": destination_observation["head_commit"],
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise ValidationError(f"publication authorization mismatch: {field}")
    local = hash_file(local_path)
    for field in ("bytes", "sha1", "sha256"):
        if local[field] != receipt[f"local_{field}"]:
            raise IntegrityError(f"publication local artifact mismatch: {field}")
    if receipt["artifact_manifest_sha256"] != canonical_sha256(artifact_manifest):
        raise ValidationError("publication authorization manifest binding mismatch")
    base_path = _artifact_path(policy, receipt["artifact_id"])
    validate_artifact_manifest(artifact_manifest)
    manifest_expected = {
        "artifact_id": receipt["artifact_id"],
        "source_registry_sha256": authorization.payload["source_registry_sha256"],
        "artifact_entry_sha256": authorization.payload["artifact_entry_sha256"],
        "original_path": base_path,
        "original_bytes": local["bytes"],
        "original_sha1": local["sha1"],
        "original_sha256": local["sha256"],
    }
    for field, value in manifest_expected.items():
        if artifact_manifest[field] != value:
            raise ValidationError(f"artifact manifest binding mismatch: {field}")
    part_plan = artifact_manifest["parts"]
    initial_files = {item["path"] for item in destination_observation["files"]}
    generated_paths = {item["path"] for item in part_plan} | {
        f"{base_path}.manifest.json"
    }
    if initial_files & generated_paths:
        raise IntegrityError("refusing to overwrite an existing publication path")
    _preflight_live_destination(
        policy=policy,
        destination_observation=destination_observation,
        client=client,
    )
    parent = receipt["initial_head_commit"]
    commits: list[dict[str, Any]] = []
    part_rows: list[dict[str, Any]] = []
    started_at = _utc_now()
    try:
        source_descriptor = os.open(
            local_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
    except OSError as exc:
        raise ValidationError("cannot open local publication artifact") from exc
    try:
        with os.fdopen(source_descriptor, "rb", buffering=0) as source:
            for planned in part_plan:
                validate_publication_authorization_time(
                    authorization, evaluated_at=_utc_now()
                )
                with tempfile.TemporaryDirectory(
                    prefix="hf-publication-part-"
                ) as raw_dir:
                    part_path = Path(raw_dir) / "part"
                    digest = _write_part(source, part_path, planned["bytes"])
                    if digest != planned["sha256"]:
                        raise IntegrityError("local part differs from its inventory")
                    commit = client.upload(
                        policy,
                        local_path=part_path,
                        remote_path=planned["path"],
                        parent_commit=parent,
                        message=f"Publish {receipt['artifact_id']} part {planned['index']}",
                    )
                parent = commit
                part_rows.append(dict(planned))
                commits.append(
                    {
                        "path": planned["path"],
                        "sha256": digest,
                        "bytes": planned["bytes"],
                        "commit": commit,
                    }
                )
            if source.read(1):
                raise IntegrityError("local artifact exceeds its planned byte count")
    finally:
        # The fd is owned and closed by fdopen on normal and exceptional paths.
        pass
    manifest = build_artifact_manifest(
        artifact_id=receipt["artifact_id"],
        source_registry_sha256=authorization.payload["source_registry_sha256"],
        artifact_entry_sha256=authorization.payload["artifact_entry_sha256"],
        base_path=base_path,
        local_audit=local,
        part_rows=part_rows,
    )
    if manifest != artifact_manifest:
        raise IntegrityError("publication manifest changed during upload")
    validate_publication_authorization_time(authorization, evaluated_at=_utc_now())
    manifest_bytes = canonical_bytes(manifest)
    manifest_path = f"{base_path}.manifest.json"
    manifest_commit = client.upload(
        policy,
        local_path=manifest_bytes,
        remote_path=manifest_path,
        parent_commit=parent,
        message=f"Publish {receipt['artifact_id']} reassembly manifest",
    )
    commits.append(
        {
            "path": manifest_path,
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "bytes": len(manifest_bytes),
            "commit": manifest_commit,
        }
    )
    after = hash_file(local_path)
    if after != local:
        raise IntegrityError("local artifact changed during publication")
    result = _verify_remote_publication(
        policy=policy,
        client=client,
        authorization=authorization,
        artifact_clearance=artifact_clearance,
        manifest=manifest,
        commits=commits,
        initial_head=receipt["initial_head_commit"],
        final_head=manifest_commit,
        started_at=started_at,
        recovered=False,
        expected_initial_paths={
            item["path"] for item in destination_observation["files"]
        },
    )
    return result


def recover_publication(
    *,
    policy: dict[str, Any],
    authorization: VerifiedPublicationAuthorization,
    artifact_clearance: dict[str, Any],
    destination_observation: dict[str, Any],
    manifest: dict[str, Any],
    client: HubClient,
    started_at: str,
    approved_destination_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Conclude an unknown outcome only from anonymously observable exact bytes."""

    validate_destination_policy(
        policy, approved_policy_sha256=approved_destination_policy_sha256
    )
    _validate_publication_authorization_wrapper(authorization)
    validate_artifact_manifest(manifest)
    if authorization.receipt["artifact_manifest_sha256"] != canonical_sha256(manifest):
        raise ValidationError("recovery manifest is not authorized")
    destination_sha256 = canonical_sha256(policy)
    _validate_destination_observation_binding(
        policy, destination_sha256, destination_observation
    )
    if authorization.receipt["destination_observation_sha256"] != canonical_sha256(
        destination_observation
    ):
        raise ValidationError("recovery observation binding mismatch")
    validate_v4_3(artifact_clearance, "execution-evidence.schema.json")
    if (
        artifact_clearance["record_kind"] != "artifact_publication_clearance"
        or not artifact_clearance["ready"]
        or authorization.receipt["artifact_clearance_sha256"]
        != canonical_sha256(artifact_clearance)
    ):
        raise ValidationError("recovery clearance binding mismatch")
    expected_authorization = {
        "destination_policy_sha256": destination_sha256,
        "artifact_id": manifest["artifact_id"],
        "local_bytes": manifest["original_bytes"],
        "local_sha1": manifest["original_sha1"],
        "local_sha256": manifest["original_sha256"],
    }
    for field, value in expected_authorization.items():
        if authorization.receipt[field] != value:
            raise ValidationError(f"recovery authorization mismatch: {field}")
    if (
        authorization.payload["source_registry_sha256"]
        != manifest["source_registry_sha256"]
        or authorization.payload["artifact_entry_sha256"]
        != manifest["artifact_entry_sha256"]
    ):
        raise ValidationError("recovery manifest lineage binding mismatch")
    started = _parse_time(started_at, "started_at")
    authorized = _parse_time(authorization.receipt["authorized_at"], "authorized_at")
    expires = _parse_time(authorization.receipt["valid_until"], "valid_until")
    now = datetime.now(UTC)
    if started < authorized or started > expires or started > now:
        raise ValidationError("recovery start is outside the authorization window")
    state = client.repo_state(policy, anonymous=True)
    file_map = {item["path"]: item for item in state["files"]}
    commits = []
    for part in manifest["parts"]:
        row = file_map.get(part["path"])
        if row is None or row["bytes"] != part["bytes"]:
            raise IntegrityError("remote part is absent or does not match the manifest")
        digest = row["sha256"]
        if digest is None:
            digest = f"sha256:{client.hash_remote(policy, remote_path=part['path'], revision=state['sha'], expected_bytes=part['bytes'])}"
        if digest != f"sha256:{part['sha256']}":
            raise IntegrityError("remote part digest does not match the manifest")
        commits.append(
            {
                "path": part["path"],
                "sha256": part["sha256"],
                "bytes": part["bytes"],
                "commit": state["sha"],
            }
        )
    manifest_path = f"{manifest['original_path']}.manifest.json"
    manifest_bytes = canonical_bytes(manifest)
    remote_manifest = client.download_small(
        policy,
        remote_path=manifest_path,
        revision=state["sha"],
        anonymous=True,
        maximum_bytes=16 * 1024 * 1024,
    )
    if remote_manifest != manifest_bytes:
        raise IntegrityError("remote reassembly manifest differs from local evidence")
    commits.append(
        {
            "path": manifest_path,
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "bytes": len(manifest_bytes),
            "commit": state["sha"],
        }
    )
    return _verify_remote_publication(
        policy=policy,
        client=client,
        authorization=authorization,
        artifact_clearance=artifact_clearance,
        manifest=manifest,
        commits=commits,
        initial_head=authorization.receipt["initial_head_commit"],
        final_head=state["sha"],
        started_at=started_at,
        recovered=True,
        expected_initial_paths={
            item["path"] for item in destination_observation["files"]
        },
    )


def _verify_remote_publication(
    *,
    policy: dict[str, Any],
    client: HubClient,
    authorization: VerifiedPublicationAuthorization,
    artifact_clearance: dict[str, Any],
    manifest: dict[str, Any],
    commits: Sequence[dict[str, Any]],
    initial_head: str,
    final_head: str,
    started_at: str,
    recovered: bool,
    expected_initial_paths: set[str],
) -> dict[str, Any]:
    _validate_publication_authorization_wrapper(authorization)
    validate_v4_3(artifact_clearance, "execution-evidence.schema.json")
    if authorization.receipt["artifact_clearance_sha256"] != canonical_sha256(
        artifact_clearance
    ):
        raise ValidationError("publication receipt clearance binding mismatch")
    state = client.repo_state(policy, anonymous=True)
    if (
        state["repo_id"].casefold() != policy["repo_id"].casefold()
        or state["private"]
        or state["sha"] != final_head
    ):
        raise IntegrityError("final publication is not anonymously visible at its head")
    file_map = {item["path"]: item for item in state["files"]}
    expected_final_paths = (
        expected_initial_paths
        | {part["path"] for part in manifest["parts"]}
        | {f"{manifest['original_path']}.manifest.json"}
    )
    if set(file_map) != expected_final_paths:
        raise IntegrityError("final publication contains missing or extra paths")
    for part in manifest["parts"]:
        row = file_map.get(part["path"])
        if row is None or row["bytes"] != part["bytes"]:
            raise IntegrityError("anonymous remote part verification failed")
        digest = row["sha256"]
        if digest is None:
            digest = f"sha256:{client.hash_remote(policy, remote_path=part['path'], revision=final_head, expected_bytes=part['bytes'])}"
        if digest != f"sha256:{part['sha256']}":
            raise IntegrityError("anonymous remote part digest verification failed")
    manifest_path = f"{manifest['original_path']}.manifest.json"
    remote_manifest = client.download_small(
        policy,
        remote_path=manifest_path,
        revision=final_head,
        anonymous=True,
        maximum_bytes=16 * 1024 * 1024,
    )
    if _strict_json(remote_manifest, label="remote artifact manifest") != manifest:
        raise IntegrityError("anonymous remote manifest verification failed")
    completed_at = _utc_now()
    if _parse_time(started_at, "started_at") > _parse_time(
        completed_at, "completed_at"
    ):
        raise ValidationError("publication completion predates its start")
    result = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "hf_publication_receipt",
        "artifact_id": manifest["artifact_id"],
        "authorization_receipt_sha256": authorization.sha256,
        "destination_policy_sha256": authorization.receipt["destination_policy_sha256"],
        "source_registry_sha256": manifest["source_registry_sha256"],
        "artifact_entry_sha256": manifest["artifact_entry_sha256"],
        "artifact_clearance_sha256": canonical_sha256(artifact_clearance),
        "local_bytes": manifest["original_bytes"],
        "local_sha1": manifest["original_sha1"],
        "local_sha256": manifest["original_sha256"],
        "initial_head_commit": initial_head,
        "final_head_commit": final_head,
        "manifest_path": manifest_path,
        "manifest_sha256": canonical_sha256(manifest),
        "commits": list(commits),
        "started_at": started_at,
        "completed_at": completed_at,
        "anonymous_readable": True,
        "complete": True,
        "recovered_after_unknown_outcome": recovered,
        "training_authorized": False,
    }
    validate_publication_v1(result, "evidence.schema.json")
    return result


def evaluate_publication_gate(
    *,
    evaluated_at: str,
    destination_policy: dict[str, Any],
    destination_observation: dict[str, Any] | None = None,
    rights: VerifiedPublicationRights | None = None,
    obligations: dict[str, Any] | None = None,
    clearance: dict[str, Any] | None = None,
    authorization: VerifiedPublicationAuthorization | None = None,
    publication_receipt: dict[str, Any] | None = None,
    approved_destination_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Evaluate one artifact's publication DAG while keeping training disabled."""

    _parse_time(evaluated_at, "evaluated_at")
    validate_publication_schema_lock_v1()
    destination_sha256 = validate_destination_policy(
        destination_policy,
        approved_policy_sha256=approved_destination_policy_sha256,
    )
    bindings: list[dict[str, str]] = [
        {
            "kind": "destination_policy",
            "subject_id": destination_policy["policy_id"],
            "sha256": destination_sha256,
        }
    ]

    destination_ready = False
    if destination_observation is not None:
        try:
            _validate_destination_observation_binding(
                destination_policy,
                destination_sha256,
                destination_observation,
                evaluated_at=evaluated_at,
            )
            destination_ready = True
            if destination_ready:
                bindings.append(
                    {
                        "kind": "destination_observation",
                        "subject_id": destination_observation["repo_id"],
                        "sha256": canonical_sha256(destination_observation),
                    }
                )
        except (IntegrityError, ValidationError):
            destination_ready = False

    rights_ready = False
    if rights is not None:
        try:
            _validate_rights_wrapper(rights)
            now = _parse_time(evaluated_at, "evaluated_at")
            rights_ready = (
                rights.sha256 == canonical_sha256(rights.receipt)
                and rights.receipt["record_kind"]
                == "publication_rights_assessment_receipt"
                and rights.receipt["destination_policy_sha256"] == destination_sha256
                and rights.receipt["redistribute_source_authorized"]
                and _parse_time(rights.receipt["reviewed_at"], "rights reviewed_at")
                <= now
                <= _parse_time(rights.receipt["valid_until"], "rights valid_until")
            )
            if rights_ready:
                bindings.append(
                    {
                        "kind": "publication_rights",
                        "subject_id": rights.receipt["source_id"],
                        "sha256": rights.sha256,
                    }
                )
        except (IntegrityError, ValidationError):
            rights_ready = False

    obligations_ready = False
    if obligations is not None and rights_ready and destination_ready:
        try:
            validate_publication_v1(obligations, "evidence.schema.json")
            obligations_ready = (
                obligations["record_kind"] == "publication_obligation_manifest"
                and obligations["complete"]
                and obligations["rights_receipt_sha256"] == rights.sha256
                and obligations["destination_observation_sha256"]
                == canonical_sha256(destination_observation)
            )
            if obligations_ready:
                bindings.append(
                    {
                        "kind": "publication_obligations",
                        "subject_id": obligations["manifest_id"],
                        "sha256": canonical_sha256(obligations),
                    }
                )
        except (IntegrityError, ValidationError):
            obligations_ready = False

    clearance_ready = False
    if clearance is not None and rights_ready and obligations_ready:
        try:
            validate_v4_3(clearance, "execution-evidence.schema.json")
            clearance_ready = (
                clearance["record_kind"] == "artifact_publication_clearance"
                and clearance["ready"]
                and clearance["rights_receipt_sha256"] == rights.sha256
                and clearance["obligations_sha256"] == canonical_sha256(obligations)
            )
            if clearance_ready:
                bindings.append(
                    {
                        "kind": "artifact_clearance",
                        "subject_id": clearance["artifact_id"],
                        "sha256": canonical_sha256(clearance),
                    }
                )
        except (IntegrityError, ValidationError):
            clearance_ready = False

    authorization_ready = False
    if authorization is not None and clearance_ready and destination_ready:
        try:
            _validate_publication_authorization_wrapper(authorization)
            validate_publication_authorization_time(
                authorization,
                evaluated_at=(
                    publication_receipt["started_at"]
                    if publication_receipt is not None
                    else evaluated_at
                ),
            )
            authorization_ready = (
                authorization.sha256 == canonical_sha256(authorization.receipt)
                and authorization.receipt["artifact_clearance_sha256"]
                == canonical_sha256(clearance)
                and authorization.receipt["destination_observation_sha256"]
                == canonical_sha256(destination_observation)
                and authorization.receipt["rights_receipt_sha256"] == rights.sha256
                and authorization.receipt["obligations_sha256"]
                == canonical_sha256(obligations)
                and authorization.payload["source_registry_sha256"]
                == clearance["source_registry_sha256"]
                and authorization.payload["artifact_entry_sha256"]
                == clearance["artifact_entry_sha256"]
            )
            if authorization_ready:
                bindings.append(
                    {
                        "kind": "publication_authorization",
                        "subject_id": authorization.receipt["artifact_id"],
                        "sha256": authorization.sha256,
                    }
                )
        except (IntegrityError, ValidationError):
            authorization_ready = False

    publication_complete = False
    if publication_receipt is not None and authorization_ready:
        try:
            validate_publication_v1(publication_receipt, "evidence.schema.json")
            publication_complete = (
                publication_receipt["record_kind"] == "hf_publication_receipt"
                and publication_receipt["complete"]
                and publication_receipt["authorization_receipt_sha256"]
                == authorization.sha256
                and publication_receipt["artifact_clearance_sha256"]
                == canonical_sha256(clearance)
                and publication_receipt["manifest_sha256"]
                == authorization.receipt["artifact_manifest_sha256"]
                and publication_receipt["artifact_id"]
                == authorization.receipt["artifact_id"]
                and publication_receipt["destination_policy_sha256"]
                == authorization.receipt["destination_policy_sha256"]
                and publication_receipt["source_registry_sha256"]
                == authorization.payload["source_registry_sha256"]
                and publication_receipt["artifact_entry_sha256"]
                == authorization.payload["artifact_entry_sha256"]
                and publication_receipt["local_bytes"]
                == authorization.receipt["local_bytes"]
                and publication_receipt["local_sha1"]
                == authorization.receipt["local_sha1"]
                and publication_receipt["local_sha256"]
                == authorization.receipt["local_sha256"]
                and publication_receipt["initial_head_commit"]
                == authorization.receipt["initial_head_commit"]
                and _parse_time(authorization.receipt["authorized_at"], "authorized_at")
                <= _parse_time(
                    publication_receipt["started_at"], "publication started_at"
                )
                <= _parse_time(authorization.receipt["valid_until"], "valid_until")
                and _parse_time(
                    publication_receipt["started_at"], "publication started_at"
                )
                <= _parse_time(
                    publication_receipt["completed_at"], "publication completed_at"
                )
                <= _parse_time(evaluated_at, "evaluated_at")
            )
            paths = [item["path"] for item in publication_receipt["commits"]]
            publication_complete = (
                publication_complete
                and len(paths) == len(set(paths))
                and publication_receipt["manifest_path"] in paths
                and publication_receipt["commits"][-1]["path"]
                == publication_receipt["manifest_path"]
                and publication_receipt["commits"][-1]["commit"]
                == publication_receipt["final_head_commit"]
            )
            if publication_complete:
                bindings.append(
                    {
                        "kind": "publication_receipt",
                        "subject_id": publication_receipt["artifact_id"],
                        "sha256": canonical_sha256(publication_receipt),
                    }
                )
        except (IntegrityError, ValidationError):
            publication_complete = False

    readiness = {
        "destination_ready": destination_ready,
        "rights_ready": rights_ready,
        "obligations_ready": obligations_ready,
        "clearance_ready": clearance_ready,
        "authorization_ready": authorization_ready,
        "publication_complete": publication_complete,
    }
    blockers = [
        {
            "code": field.removesuffix("_ready") + "_missing",
            "subject_kind": "publication_v1",
            "subject_id": (
                clearance["artifact_id"]
                if clearance is not None and "artifact_id" in clearance
                else destination_policy["repo_id"]
            ),
        }
        for field, ready in readiness.items()
        if not ready
    ]
    result = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": "hf-public-source-publication-v1",
        "evaluated_at": evaluated_at,
        "contracts_frozen": True,
        **readiness,
        "blockers": sorted(blockers, key=lambda item: item["code"]),
        "evidence_bindings": sorted(
            bindings, key=lambda item: (item["kind"], item["subject_id"])
        ),
        "training_authorized": False,
    }
    validate_publication_v1(result, "gate.schema.json")
    return result
