"""Immutable raw-artifact auditing and streaming structural inventories."""

from __future__ import annotations

import bz2
import csv
import gzip
import hashlib
import json
import os
import stat
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from .canonical import canonical_sha256
from .errors import IntegrityError, ValidationError

HASH_CHUNK_BYTES = 8 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _assert_regular_no_symlinks(root: Path, target: Path) -> Path:
    root = Path(os.path.abspath(root))
    current = Path(root.anchor)
    for component in root.parts[1:]:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise IntegrityError(
                f"cannot inspect storage root {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError(f"storage-root symlink is forbidden: {current}")
    candidate = Path(os.path.abspath(target if target.is_absolute() else root / target))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise IntegrityError(f"path escapes registered root: {candidate}") from exc

    current = root
    for component in relative.parts:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise IntegrityError(f"cannot inspect {current}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError(f"symlink is forbidden: {current}")
    metadata = candidate.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise IntegrityError(f"artifact is not a regular file: {candidate}")
    return candidate


def resolve_artifact(
    storage_map: dict[str, str], locator_id: str, filename: str
) -> Path:
    if locator_id not in storage_map:
        raise IntegrityError(f"unknown storage locator: {locator_id}")
    relative = Path(filename)
    if relative.is_absolute():
        raise IntegrityError("artifact filename must be relative")
    if ".." in relative.parts:
        raise IntegrityError("artifact filename cannot contain parent traversal")
    root = Path(storage_map[locator_id])
    return _assert_regular_no_symlinks(root, root / relative)


def hash_file(path: Path) -> dict[str, Any]:
    """Hash immutable bytes and fail if the file changes while being read."""

    path = _assert_regular_no_symlinks(path.parent, path)
    digests = {
        "md5": hashlib.md5(usedforsecurity=False),
        "sha1": hashlib.sha1(usedforsecurity=False),
        "sha256": hashlib.sha256(),
    }
    bytes_read = 0
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise IntegrityError(f"cannot open artifact safely {path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise IntegrityError(f"artifact is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", buffering=0, closefd=False) as handle:
            while chunk := handle.read(HASH_CHUNK_BYTES):
                bytes_read += len(chunk)
                for digest in digests.values():
                    digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_after = path.lstat()
    except OSError as exc:
        raise IntegrityError(f"artifact disappeared after scan: {path}: {exc}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    path_identity_after = (
        path_after.st_dev,
        path_after.st_ino,
        path_after.st_size,
        path_after.st_mtime_ns,
    )
    if (
        stat.S_ISLNK(path_after.st_mode)
        or identity_before != identity_after
        or identity_before != path_identity_after
        or bytes_read != before.st_size
    ):
        raise IntegrityError(f"artifact changed during scan: {path}")
    return {
        "bytes": bytes_read,
        "md5": digests["md5"].hexdigest(),
        "sha1": digests["sha1"].hexdigest(),
        "sha256": digests["sha256"].hexdigest(),
        "device": before.st_dev,
        "inode": before.st_ino,
        "mtime_ns": before.st_mtime_ns,
    }


def audit_artifact(
    artifact: dict[str, Any], storage_map: dict[str, str]
) -> dict[str, Any]:
    path = resolve_artifact(storage_map, artifact["locator_id"], artifact["filename"])
    measured = hash_file(path)
    mismatches: list[str] = []
    expected_bytes = artifact.get("expected_bytes")
    if expected_bytes is not None and measured["bytes"] != expected_bytes:
        mismatches.append(
            f"bytes expected {expected_bytes}, measured {measured['bytes']}"
        )
    for checksum in artifact.get("checksums", []):
        expected = checksum["value"].lower()
        actual = measured[checksum["algorithm"]]
        if expected != actual:
            mismatches.append(
                f"{checksum['algorithm']} expected {expected}, measured {actual}"
            )
    return {
        "artifact_id": artifact["artifact_id"],
        "locator_id": artifact["locator_id"],
        "filename": artifact["filename"],
        "measured": measured,
        "status": "verified" if not mismatches else "mismatch",
        "mismatches": mismatches,
    }


def audit_source_registry(
    registry: dict[str, Any], storage_map: dict[str, str]
) -> dict[str, Any]:
    started_at = _utc_now()
    if registry.get("storage_requirements"):
        expected_storage_map = {
            item["locator_id"]: item["required_root"]
            for item in registry["storage_requirements"]
        }
        if storage_map != expected_storage_map:
            raise IntegrityError(
                "storage map does not exactly match the registry's required provider roots"
            )
    results: list[dict[str, Any]] = []
    artifacts_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for source in registry["sources"]:
        for artifact in source["artifacts"]:
            artifacts_by_pair[(source["source_id"], artifact["artifact_id"])] = artifact
            try:
                result = audit_artifact(artifact, storage_map)
            except IntegrityError as exc:
                result = {
                    "artifact_id": artifact["artifact_id"],
                    "locator_id": artifact["locator_id"],
                    "filename": artifact["filename"],
                    "measured": None,
                    "status": "error",
                    "mismatches": [str(exc)],
                }
            result["source_id"] = source["source_id"]
            results.append(result)
    # Recheck identity after the full scan so an early artifact cannot change
    # silently while later (potentially very large) artifacts are being read.
    for result in results:
        if result["status"] != "verified":
            continue
        artifact = artifacts_by_pair[(result["source_id"], result["artifact_id"])]
        try:
            path = resolve_artifact(
                storage_map, artifact["locator_id"], artifact["filename"]
            )
            metadata = path.stat()
            measured = result["measured"]
            observed_identity = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
            measured_identity = (
                measured["device"],
                measured["inode"],
                measured["bytes"],
                measured["mtime_ns"],
            )
            if observed_identity != measured_identity:
                result["status"] = "mismatch"
                result["mismatches"].append("artifact changed after its hash pass")
        except IntegrityError as exc:
            result["status"] = "mismatch"
            result["mismatches"].append(f"post-scan identity check failed: {exc}")
    return {
        "schema_version": "1.0.0",
        "registry_id": registry["registry_id"],
        "registry_sha256": canonical_sha256(registry),
        "storage_map_sha256": canonical_sha256(storage_map),
        "started_at": started_at,
        "completed_at": _utc_now(),
        "artifact_count": len(results),
        "total_bytes": sum(
            item["measured"]["bytes"]
            for item in results
            if item["measured"] is not None
        ),
        "all_verified": all(item["status"] == "verified" for item in results),
        "artifacts": results,
    }


@contextmanager
def open_decompressed_binary(path: Path) -> Iterator[BinaryIO]:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
    elif suffix == ".bz2":
        with bz2.open(path, "rb") as handle:
            yield handle
    else:
        with path.open("rb") as handle:
            yield handle


@contextmanager
def open_decompressed_text(path: Path) -> Iterator[TextIO]:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        with gzip.open(
            path, "rt", encoding="utf-8", errors="strict", newline=""
        ) as handle:
            yield handle
    elif suffix == ".bz2":
        with bz2.open(
            path, "rt", encoding="utf-8", errors="strict", newline=""
        ) as handle:
            yield handle
    else:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
            yield handle


def count_wikipedia_xml(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    namespace_marker: str | None = None
    with open_decompressed_binary(path) as handle:
        for event, element in ET.iterparse(handle, events=("start", "end")):
            if (
                namespace_marker is None
                and event == "start"
                and element.tag.startswith("{")
            ):
                namespace_marker = element.tag.split("}", 1)[0] + "}"
            if event != "end":
                continue
            local = element.tag.split("}", 1)[-1]
            if local == "page":
                counts["documents"] += 1
                element.clear()
            elif local == "revision":
                counts["document_versions"] += 1
            elif local == "text":
                text = element.text or ""
                counts["text_characters"] += len(text)
                counts["text_utf8_bytes"] += len(text.encode("utf-8"))
    return {"kind": "wikipedia_xml", **dict(sorted(counts.items()))}


def count_sql_rows(path: Path) -> dict[str, Any]:
    """Count top-level tuples following SQL VALUES without executing SQL."""

    marker = b"VALUES "
    matched = 0
    in_values = False
    quote = False
    escape = False
    depth = 0
    rows = 0
    statements = 0
    uncompressed_bytes = 0
    with open_decompressed_binary(path) as handle:
        while chunk := handle.read(1024 * 1024):
            uncompressed_bytes += len(chunk)
            for byte in chunk:
                if not in_values:
                    expected = marker[matched]
                    if byte == expected:
                        matched += 1
                        if matched == len(marker):
                            in_values = True
                            matched = 0
                    else:
                        matched = 1 if byte == marker[0] else 0
                    continue
                if quote:
                    if escape:
                        escape = False
                    elif byte == 0x5C:
                        escape = True
                    elif byte == 0x27:
                        quote = False
                    continue
                if byte == 0x27:
                    quote = True
                elif byte == 0x28:
                    if depth == 0:
                        rows += 1
                    depth += 1
                elif byte == 0x29 and depth:
                    depth -= 1
                elif byte == 0x3B and depth == 0:
                    statements += 1
                    in_values = False
                    matched = 0
    if quote or depth != 0:
        raise IntegrityError(f"unterminated SQL value structure in {path}")
    return {
        "kind": "mediawiki_sql",
        "rows": rows,
        "insert_statements": statements,
        "uncompressed_bytes": uncompressed_bytes,
    }


def count_wikidata_json(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    with open_decompressed_text(path) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if line in {"", "[", "]"}:
                continue
            if line.endswith(","):
                line = line[:-1]
            try:
                entity = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IntegrityError(
                    f"invalid Wikidata JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(entity, dict):
                raise IntegrityError(
                    f"Wikidata entity is not an object at line {line_number}"
                )
            counts["entities"] += 1
            entity_type = str(entity.get("type", "unknown"))
            counts[f"entity_type.{entity_type}"] += 1
            counts["sitelinks"] += len(entity.get("sitelinks") or {})
            claims = entity.get("claims") or {}
            for statements in claims.values():
                for statement in statements:
                    counts["statements"] += 1
                    counts[f"rank.{statement.get('rank', 'unknown')}"] += 1
                    mainsnak = statement.get("mainsnak") or {}
                    counts[f"datatype.{mainsnak.get('datatype', 'unknown')}"] += 1
                    qualifiers = statement.get("qualifiers") or {}
                    counts["qualifiers"] += sum(
                        len(values) for values in qualifiers.values()
                    )
                    counts["references"] += len(statement.get("references") or [])
    return {"kind": "wikidata_json", **dict(sorted(counts.items()))}


def count_conceptnet(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    with open_decompressed_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        for _row_number, row in enumerate(reader, start=1):
            if len(row) < 4:
                counts["rejected_records"] += 1
                continue
            counts["rows"] += 1
            relation = row[1].removeprefix("/r/")
            counts[f"relation.{relation}"] += 1
            for endpoint in row[2:4]:
                parts = endpoint.split("/")
                if len(parts) > 2 and parts[1] == "c":
                    counts[f"language.{parts[2]}"] += 1
    return {"kind": "conceptnet_assertions", **dict(sorted(counts.items()))}


def stream_count(path: Path, kind: str) -> dict[str, Any]:
    path = _assert_regular_no_symlinks(path.parent, path)
    if kind == "wikipedia_xml":
        return count_wikipedia_xml(path)
    if kind == "mediawiki_sql":
        return count_sql_rows(path)
    if kind == "wikidata_json":
        return count_wikidata_json(path)
    if kind == "conceptnet_assertions":
        return count_conceptnet(path)
    raise ValidationError(f"unsupported inventory counter kind: {kind}")
