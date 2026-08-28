"""Immutable licence evidence and human-assessment controls.

This module captures and verifies legal/provenance documents.  It does not make
legal decisions and cannot authorize training.
"""

from __future__ import annotations

import hashlib
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from hippocampus_foundation.phase0.canonical import (
    canonical_sha256,
    dump_pretty,
    load_json,
)
from hippocampus_foundation.phase0.errors import IntegrityError, ValidationError

SCHEMA_VERSION = "1.0.0"
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_MUTABLE_REVIEW_AGE = timedelta(days=30)
MAX_IMMUTABLE_REVIEW_AGE = timedelta(days=365)
FORBIDDEN_USES = frozenset(
    {"train", "redistribute_source", "redistribute_derived", "redistribute_model"}
)
ALLOWED_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/ld+json",
        "application/pdf",
        "application/rdf+xml",
        "application/xml",
        "text/html",
        "text/markdown",
        "text/plain",
        "text/xml",
        "text/x-wiki",
    }
)
FORBIDDEN_PATH_SUFFIXES = (
    ".bz2",
    ".csv",
    ".gz",
    ".jsonl",
    ".ndjson",
    ".parquet",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tsv",
    ".xz",
    ".zip",
)

# Filled after schema validation; the lock lives outside the artifacts it pins.
FROZEN_SCHEMA_DIGESTS_V1: dict[str, str] = {
    "evidence-bundle.schema.json": "sha256:8fd7fecf7890dc427fa9f9fe1f720b5bf7bd49de34f45382b2972fc3f3b5f424",
    "licence-assessment.schema.json": "sha256:8ed50f832936a66dd17d707d077fe45010fd3f76829db180db8c2618e3c798f7",
}


@dataclass(frozen=True)
class VerifiedBundle:
    """A schema-valid bundle whose retained document bytes were rehashed."""

    bundle: dict[str, Any]
    sha256: str
    snapshot_root: Path


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


def schema_root_v1() -> Path:
    package_candidate = Path(__file__).resolve().parent / "schemas" / "licensing" / "v1"
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[2] / "schemas" / "licensing" / "v1"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate licensing v1 schema directory")


def load_schema_v1(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v1()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(
            f"invalid licensing schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v1(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v1(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    rendered = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        rendered.append(f"{location}: {error.message}")
    raise ValidationError("; ".join(rendered))


def schema_digests_v1(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v1()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no licensing schemas under {target}")
    return {name: canonical_sha256(load_schema_v1(name, target)) for name in names}


def validate_schema_lock_v1(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v1(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V1:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V1.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V1.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V1.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V1[name] != observed[name]
        )
        raise ValidationError(
            f"licensing schema lock mismatch: missing={missing}, extra={extra}, changed={changed}"
        )
    return observed


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationError(f"unsafe evidence snapshot path: {value!r}")
    return path


def _hash_regular_file_without_links(root: Path, relative: str) -> tuple[int, str]:
    root_resolved = root.resolve(strict=True)
    pure = _safe_relative_path(relative)
    candidate = root_resolved
    for part in pure.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise IntegrityError(
                f"evidence snapshot path contains a symlink: {relative}"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"evidence snapshot escapes its root: {relative}") from exc

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise IntegrityError(
            f"cannot open evidence snapshot safely: {relative}: {exc}"
        ) from exc
    digest = hashlib.sha256()
    byte_count = 0
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise IntegrityError(f"evidence snapshot is not a regular file: {relative}")
        with os.fdopen(descriptor, "rb", buffering=0, closefd=False) as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                byte_count += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or byte_count != before.st_size:
        raise IntegrityError(f"evidence snapshot changed while hashing: {relative}")
    return byte_count, f"sha256:{digest.hexdigest()}"


def verify_evidence_bundle(
    bundle: dict[str, Any], snapshot_root: Path
) -> VerifiedBundle:
    """Validate a bundle and independently rehash each retained document."""

    validate_v1(bundle, "evidence-bundle.schema.json")
    assembled_at = _parse_time(bundle["assembled_at"], "assembled_at")
    document_ids: set[str] = set()
    snapshot_paths: set[str] = set()
    finding_ids: set[str] = set()
    for document in bundle["documents"]:
        document_id = document["document_id"]
        snapshot_path = document["snapshot_path"]
        if document_id in document_ids:
            raise ValidationError(f"duplicate evidence document ID: {document_id}")
        if snapshot_path in snapshot_paths:
            raise ValidationError(f"duplicate evidence snapshot path: {snapshot_path}")
        document_ids.add(document_id)
        snapshot_paths.add(snapshot_path)
        if _parse_time(document["retrieved_at"], "retrieved_at") > assembled_at:
            raise ValidationError(
                f"evidence document was retrieved after bundle assembly: {document_id}"
            )
        for field in ("original_url", "resolved_url"):
            parsed = urllib.parse.urlparse(document[field])
            if (
                document["source_kind"] != "local_attestation"
                and parsed.scheme != "https"
            ):
                raise ValidationError(
                    f"remote evidence URL must use HTTPS: {document[field]}"
                )
        observed_bytes, observed_sha256 = _hash_regular_file_without_links(
            snapshot_root, snapshot_path
        )
        if observed_bytes != document["byte_count"]:
            raise IntegrityError(
                f"evidence snapshot byte count mismatch: {document_id}"
            )
        if observed_sha256 != document["sha256"]:
            raise IntegrityError(f"evidence snapshot digest mismatch: {document_id}")
    for finding in bundle["findings"]:
        finding_id = finding["finding_id"]
        if finding_id in finding_ids:
            raise ValidationError(f"duplicate licence finding ID: {finding_id}")
        finding_ids.add(finding_id)
    return VerifiedBundle(
        bundle=bundle,
        sha256=canonical_sha256(bundle),
        snapshot_root=snapshot_root.resolve(strict=True),
    )


def load_verified_bundle(path: Path) -> VerifiedBundle:
    bundle = load_json(path)
    if not isinstance(bundle, dict):
        raise ValidationError(f"licence evidence bundle must be an object: {path}")
    return verify_evidence_bundle(bundle, path.parent)


def make_pending_assessment(bundle: dict[str, Any]) -> dict[str, Any]:
    """Create a non-authorizing scaffold for an accountable human reviewer."""

    validate_v1(bundle, "evidence-bundle.schema.json")
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "licence_assessment",
        "review_id": bundle["review_id"],
        "subject_kind": bundle["subject_kind"],
        "subject_id": bundle["subject_id"],
        "subject_binding_sha256": bundle["subject_binding_sha256"],
        "bundle_sha256": canonical_sha256(bundle),
        "decision": "pending",
        "commercial_context": "unclear",
        "licence_identifiers": ["LicenseRef-UNRESOLVED"],
        "allowed_uses": [],
        "excluded_uses": sorted(FORBIDDEN_USES),
        "obligations": [],
        "finding_dispositions": [
            {
                "finding_id": finding["finding_id"],
                "disposition": "unresolved",
                "rationale_document_id": None,
            }
            for finding in bundle["findings"]
        ],
        "reviewer": None,
        "reviewed_at": None,
        "valid_until": None,
        "training_authorized": False,
        "notes": "Pending accountable human review; no use is authorized.",
    }


def verify_assessment(
    assessment: dict[str, Any],
    verified_bundle: VerifiedBundle,
    *,
    subject_kind: str,
    subject_id: str,
    subject_binding_sha256: str,
    required_uses: Iterable[str],
    evaluated_at: str,
) -> None:
    """Require an unexpired human approval for the exact subject and bundle."""

    validate_v1(assessment, "licence-assessment.schema.json")
    bundle = verified_bundle.bundle
    bindings = {
        "review_id": bundle["review_id"],
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "subject_binding_sha256": subject_binding_sha256,
        "bundle_sha256": verified_bundle.sha256,
    }
    for field, expected in bindings.items():
        if assessment[field] != expected:
            raise ValidationError(f"licence assessment binding mismatch: {field}")
    if bundle["subject_kind"] != subject_kind or bundle["subject_id"] != subject_id:
        raise ValidationError("licence evidence bundle subject mismatch")
    if bundle["subject_binding_sha256"] != subject_binding_sha256:
        raise ValidationError("licence evidence bundle registry/spec binding mismatch")
    if assessment["decision"] != "approved":
        raise ValidationError("licence assessment is not approved")
    if not bundle["documents"]:
        raise ValidationError(
            "approved licence assessment has no retained evidence documents"
        )
    if assessment["commercial_context"] != "allowed":
        raise ValidationError("licence assessment does not allow commercial context")
    if (
        not assessment["reviewer"]
        or not assessment["reviewed_at"]
        or not assessment["valid_until"]
    ):
        raise ValidationError("approved licence assessment lacks human review timing")
    if assessment["training_authorized"] is not False:
        raise ValidationError("licence assessment violates the no-training invariant")
    allowed = set(assessment["allowed_uses"])
    excluded = set(assessment["excluded_uses"])
    if allowed & excluded:
        raise ValidationError("licence assessment both allows and excludes a use")
    missing_uses = set(required_uses) - allowed
    if missing_uses:
        raise ValidationError(
            f"licence assessment omits required uses: {sorted(missing_uses)}"
        )
    if FORBIDDEN_USES - excluded or FORBIDDEN_USES & allowed:
        raise ValidationError(
            "training and redistribution must remain explicitly excluded"
        )

    document_ids = {document["document_id"] for document in bundle["documents"]}
    disposition_by_id: dict[str, dict[str, Any]] = {}
    for disposition in assessment["finding_dispositions"]:
        finding_id = disposition["finding_id"]
        if finding_id in disposition_by_id:
            raise ValidationError(
                f"duplicate licence finding disposition: {finding_id}"
            )
        disposition_by_id[finding_id] = disposition
        rationale = disposition["rationale_document_id"]
        if rationale is not None and rationale not in document_ids:
            raise ValidationError(f"unknown rationale evidence document: {rationale}")
    expected_findings = {finding["finding_id"] for finding in bundle["findings"]}
    if set(disposition_by_id) != expected_findings:
        raise ValidationError("licence assessment finding coverage mismatch")
    unresolved = [
        finding["finding_id"]
        for finding in bundle["findings"]
        if finding["blocking"]
        and disposition_by_id[finding["finding_id"]]["disposition"] != "resolved"
    ]
    if unresolved:
        raise ValidationError(
            f"blocking licence findings remain unresolved: {sorted(unresolved)}"
        )

    now = _parse_time(evaluated_at, "evaluated_at")
    reviewed_at = _parse_time(assessment["reviewed_at"], "reviewed_at")
    valid_until = _parse_time(assessment["valid_until"], "valid_until")
    if reviewed_at > now:
        raise ValidationError("licence assessment is from the future")
    assembled_at = _parse_time(bundle["assembled_at"], "bundle assembled_at")
    if reviewed_at < assembled_at:
        raise ValidationError("licence assessment predates its evidence bundle")
    if valid_until <= now:
        raise ValidationError("licence assessment has expired")
    maximum_age = (
        MAX_MUTABLE_REVIEW_AGE
        if any(document["mutable"] for document in bundle["documents"])
        else MAX_IMMUTABLE_REVIEW_AGE
    )
    if valid_until > reviewed_at + maximum_age:
        raise ValidationError(
            "licence assessment validity exceeds evidence freshness policy"
        )


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str], maximum: int = 5) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.maximum = maximum
        self.count = 0

    def redirect_request(  # type: ignore[override]
        self,
        request: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> urllib.request.Request | None:
        self.count += 1
        parsed = urllib.parse.urlparse(newurl)
        if self.count > self.maximum:
            raise ValidationError("licence evidence redirect limit exceeded")
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise ValidationError(
                f"licence evidence redirect is not allowlisted: {newurl}"
            )
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _write_exclusive(path: Path, data: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def capture_https_document(
    *,
    url: str,
    document_id: str,
    role: str,
    source_kind: str,
    output: Path,
    receipt: Path,
    allowed_hosts: Sequence[str],
    expected_media_type: str | None = None,
    revision: str | None = None,
    mutable: bool,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Capture one allowlisted legal/provenance response without crawling."""

    if (
        output.exists()
        or output.is_symlink()
        or receipt.exists()
        or receipt.is_symlink()
    ):
        raise IntegrityError("refusing to overwrite licence evidence output")
    parsed = urllib.parse.urlparse(url)
    hosts = frozenset(host.casefold() for host in allowed_hosts)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in hosts
    ):
        raise ValidationError("licence evidence URL must be HTTPS and host-allowlisted")
    path_lower = parsed.path.casefold()
    if any(path_lower.endswith(suffix) for suffix in FORBIDDEN_PATH_SUFFIXES):
        raise ValidationError(
            "licence evidence capture rejects dataset/archive file types"
        )

    redirect_handler = _BoundedRedirectHandler(hosts)
    opener = urllib.request.build_opener(redirect_handler)
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "hippocampus-foundation-licence-evidence/1.0",
        },
        method="GET",
    )
    try:
        with opener.open(request, timeout=30) as response:
            status = getattr(response, "status", None)
            if status != 200:
                raise ValidationError(
                    f"licence evidence HTTP status is not 200: {status}"
                )
            resolved_url = response.geturl()
            final = urllib.parse.urlparse(resolved_url)
            if (
                final.scheme != "https"
                or final.hostname is None
                or final.hostname.casefold() not in hosts
            ):
                raise ValidationError(
                    "resolved licence evidence URL is not allowlisted"
                )
            content_encoding = response.headers.get("Content-Encoding")
            if content_encoding and content_encoding.casefold() != "identity":
                raise ValidationError(
                    "licence evidence response did not honor identity encoding"
                )
            media_type = response.headers.get_content_type().casefold()
            if expected_media_type and media_type != expected_media_type.casefold():
                raise ValidationError(
                    f"licence evidence media type mismatch: expected {expected_media_type}, got {media_type}"
                )
            if media_type not in ALLOWED_MEDIA_TYPES:
                raise ValidationError(
                    f"licence evidence media type is not allowlisted: {media_type}"
                )
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > MAX_DOCUMENT_BYTES:
                raise ValidationError(
                    "licence evidence response exceeds the size limit"
                )
            body = response.read(MAX_DOCUMENT_BYTES + 1)
            if len(body) > MAX_DOCUMENT_BYTES:
                raise ValidationError(
                    "licence evidence response exceeds the size limit"
                )
            metadata = {
                "document_id": document_id,
                "role": role,
                "source_kind": source_kind,
                "original_url": url,
                "resolved_url": resolved_url,
                "revision": revision,
                "snapshot_path": output.name,
                "media_type": media_type,
                "content_encoding": content_encoding,
                "byte_count": len(body),
                "sha256": f"sha256:{hashlib.sha256(body).hexdigest()}",
                "retrieved_at": retrieved_at or _utc_now(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "mutable": mutable,
            }
    except urllib.error.HTTPError as exc:
        raise ValidationError(
            f"licence evidence HTTP request failed: {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationError(
            f"licence evidence network request failed: {exc.reason}"
        ) from exc

    _write_exclusive(output, body, mode=0o600)
    try:
        _write_exclusive(receipt, dump_pretty(metadata).encode("utf-8"), mode=0o600)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return metadata


def build_evidence_bundle(
    *,
    bundle_id: str,
    review_id: str,
    subject_kind: str,
    subject_id: str,
    subject_binding_sha256: str,
    documents: Sequence[dict[str, Any]],
    findings: Sequence[dict[str, Any]],
    assembled_at: str | None = None,
) -> dict[str, Any]:
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "licence_evidence_bundle",
        "bundle_id": bundle_id,
        "review_id": review_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "subject_binding_sha256": subject_binding_sha256,
        "assembled_at": assembled_at or _utc_now(),
        "contains_evaluation_content": False,
        "documents": list(documents),
        "findings": list(findings),
    }
    validate_v1(bundle, "evidence-bundle.schema.json")
    return bundle
