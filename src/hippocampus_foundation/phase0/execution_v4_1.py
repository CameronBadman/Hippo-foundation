"""Execution-hardened Phase 0 v4.1 evidence and registry transitions."""

from __future__ import annotations

import copy
import hashlib
import os
import stat
import tarfile
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from hippocampus_foundation.licensing import (
    VerifiedBundle,
    verify_assessment,
)

from .canonical import canonical_sha256
from .errors import GateBlocked, IntegrityError, QuarantineError, ValidationError
from .evaluation_firewall import (
    VerifiedSealReceipt,
    build_quarantine_contribution_v4,
    validate_evaluation_registry_v4,
    validate_source_registry_v4,
    verify_seal_receipt_v4,
)
from .external_evidence import VerifiedAccessAnchor
from .quarantine import normalize_identifier
from .seal import consumes_evaluation, verify_access_chain
from .v3 import EVALUATION_REQUIRED_USES
from .v4_1_contracts import SCHEMA_VERSION_V4_1, validate_v4_1
from .v4_contracts import validate_v4

SOURCE_REGISTRY_ROOT_SHA256 = (
    "sha256:c724de9fea9e13d365503f8cdaeaa25016fc906cebf6bb05b6884a2dae69e3ec"
)
EVALUATION_REGISTRY_ROOT_SHA256 = (
    "sha256:6c52a922377d7ae017ae24ecca0f2dc7d239b562a954ac310b6325fe21cd97cb"
)
WIKIDATA_MANIFEST_URL = (
    "https://dumps.wikimedia.org/wikidatawiki/entities/20260720/"
    "wikidata-20260720-sha1sums.txt"
)
ENWIKI_MANIFEST_URL = (
    "https://dumps.wikimedia.org/enwiki/20260801/enwiki-20260801-sha1sums.txt"
)

_PUBLISHER_URL_BY_ARTIFACT = {
    "wikidata-20260720-all-json-bz2": WIKIDATA_MANIFEST_URL,
    "enwiki-20260801-redirect-sql-gz": ENWIKI_MANIFEST_URL,
    "enwiki-20260801-linktarget-sql-gz": ENWIKI_MANIFEST_URL,
    "enwiki-20260801-page-sql-gz": ENWIKI_MANIFEST_URL,
    "enwiki-20260801-categorylinks-sql-gz": ENWIKI_MANIFEST_URL,
    "enwiki-20260801-pagelinks-sql-gz": ENWIKI_MANIFEST_URL,
    "enwiki-20260801-pages-articles-xml-bz2": ENWIKI_MANIFEST_URL,
}

_CUSTODY_RANK = {
    "declared": 0,
    "pinned": 1,
    "sealed": 2,
    "consumed": 3,
    "retired": 4,
}
_PIN_BACKED_BLOCKERS = frozenset({"archive_hash_missing", "adapter_missing"})
_MATERIALIZATION_BACKED_BLOCKERS = frozenset(
    {
        "generator_not_implemented",
        "independent_oracle_missing",
        "atomic_lineage_closure_missing",
    }
)
_RIGHTS_BACKED_BLOCKERS = frozenset(
    {
        "human_rights_review_missing",
        "authorized_terms_acceptance_missing",
        "embedded_news_rights_review_missing",
        "embedded_paper_text_rights_review_missing",
        "ownership_review_missing",
    }
)
_CUSTODY_BACKED_BLOCKERS = frozenset({"seal_missing", "custodian_anchor_missing"})
_PUBLIC_RECEIPT_FORBIDDEN_KEYS = frozenset(
    {
        "member_path",
        "archive_members",
        "record_id",
        "record_bindings",
        "primary_unit_id",
        "primary_unit_ids",
        "dependency",
        "dependencies",
        "selector",
        "selectors",
        "private_payload",
        "commitment_nonce",
        "label",
        "labels",
        "answer",
        "answers",
        "target",
        "targets",
    }
)


@dataclass(frozen=True)
class VerifiedRegistryLineage:
    registries: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]
    sha256: str

    @property
    def root(self) -> dict[str, Any]:
        return self.registries[0]

    @property
    def tip(self) -> dict[str, Any]:
        return self.registries[-1]


@dataclass(frozen=True)
class VerifiedMaterialization:
    manifest: dict[str, Any]
    receipt: dict[str, Any]
    envelope: dict[str, Any]
    manifest_sha256: str
    receipt_sha256: str


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    return parsed


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _expected_root(kind: str) -> str:
    if kind == "sources":
        return SOURCE_REGISTRY_ROOT_SHA256
    if kind == "evaluations":
        return EVALUATION_REGISTRY_ROOT_SHA256
    raise ValidationError(f"unsupported registry kind: {kind!r}")


def _validate_source_transition(
    predecessor: dict[str, Any], successor: dict[str, Any]
) -> None:
    validate_source_registry_v4(successor, predecessor)
    old_requirements = {
        item["artifact_id"]: item
        for item in predecessor["publisher_evidence_requirements"]
    }
    new_requirements = {
        item["artifact_id"]: item
        for item in successor["publisher_evidence_requirements"]
    }
    if set(old_requirements) != set(new_requirements):
        raise ValidationError("publisher requirement set changed across v4.1 lineage")
    if [
        item["artifact_id"] for item in successor["publisher_evidence_requirements"]
    ] != [
        item["artifact_id"] for item in predecessor["publisher_evidence_requirements"]
    ]:
        raise ValidationError("publisher requirement order changed across v4.1 lineage")
    if set(new_requirements) != set(_PUBLISHER_URL_BY_ARTIFACT):
        raise ValidationError("source root artifact set is not the checked-in v4 set")
    for artifact_id, old in old_requirements.items():
        new = new_requirements[artifact_id]
        for field in (
            "evidence_id",
            "source_id",
            "artifact_id",
            "statement_format",
            "max_age_hours",
        ):
            if new[field] != old[field]:
                raise ValidationError(
                    f"publisher requirement identity changed: {artifact_id}:{field}"
                )
        expected_url = _PUBLISHER_URL_BY_ARTIFACT[artifact_id]
        if new["statement_url"] not in {None, expected_url}:
            raise ValidationError(
                f"publisher manifest URL is not the pinned value: {artifact_id}"
            )
        if (
            old["statement_url"] is not None
            and new["statement_url"] != old["statement_url"]
        ):
            raise ValidationError(f"pinned publisher URL changed: {artifact_id}")


def _validate_evaluation_transition(
    predecessor: dict[str, Any], successor: dict[str, Any]
) -> None:
    validate_evaluation_registry_v4(successor, predecessor)
    old_ids = [item["dataset_id"] for item in predecessor["datasets"]]
    new_ids = [item["dataset_id"] for item in successor["datasets"]]
    if new_ids != old_ids:
        raise ValidationError(
            "evaluation entry set or order changed across v4.1 lineage"
        )
    old_by_id = {item["dataset_id"]: item for item in predecessor["datasets"]}
    for new in successor["datasets"]:
        old = old_by_id[new["dataset_id"]]
        dataset_id = new["dataset_id"]
        if new["seal_id"] != old["seal_id"]:
            raise ValidationError(f"evaluation seal ID changed: {dataset_id}")
        if new["dependency_units"] != old["dependency_units"]:
            raise ValidationError(f"evaluation dependency units changed: {dataset_id}")
        old_rank = _CUSTODY_RANK[old["custody_state"]]
        new_rank = _CUSTODY_RANK[new["custody_state"]]
        if new_rank - old_rank > 1:
            raise ValidationError(
                f"evaluation custody transition skipped a state: {dataset_id}"
            )
        old_key = old["custodian_signing_key_fingerprint"]
        new_key = new["custodian_signing_key_fingerprint"]
        if old_key is not None and new_key != old_key:
            raise ValidationError(f"pinned custodian key changed: {dataset_id}")
        if (
            old_key is None
            and new_key is not None
            and not (
                old["custody_state"] == "declared" and new["custody_state"] == "pinned"
            )
        ):
            raise ValidationError(
                f"custodian key was not introduced at pinning: {dataset_id}"
            )
        if old_rank >= _CUSTODY_RANK["pinned"]:
            for field in (
                "resolved_version",
                "partition",
                "archive_sha256",
                "adapter_id",
                "adapter_sha256",
                "seal_id",
                "custodian_signing_key_fingerprint",
                "dependency_units",
            ):
                if new[field] != old[field]:
                    raise ValidationError(
                        f"pinned evaluation field changed: {dataset_id}:{field}"
                    )
        removed = set(old["blockers"]) - set(new["blockers"])
        added = set(new["blockers"]) - set(old["blockers"])
        if (
            old["custody_state"] == "declared"
            and new["custody_state"] == "pinned"
            and removed - _PIN_BACKED_BLOCKERS
        ):
            raise ValidationError(f"pinning cleared a non-asset blocker: {dataset_id}")
        if old_rank >= _CUSTODY_RANK["pinned"]:
            allowed_removals = (
                _PIN_BACKED_BLOCKERS
                | _MATERIALIZATION_BACKED_BLOCKERS
                | _RIGHTS_BACKED_BLOCKERS
            )
            if new["custody_state"] == "sealed":
                allowed_removals |= _CUSTODY_BACKED_BLOCKERS
            if added or removed - allowed_removals:
                raise ValidationError(
                    f"pinned evaluation blockers changed without a recognized evidence family: {dataset_id}"
                )


def validate_registry_lineage_v4_1(
    registries: Sequence[dict[str, Any]],
) -> VerifiedRegistryLineage:
    """Verify an ordered, root-anchored, gap-free v4 registry chain."""

    values = tuple(registries)
    if not values:
        raise ValidationError("registry lineage is empty")
    kind = str(values[0].get("registry_kind", ""))
    if any(item.get("registry_kind") != kind for item in values):
        raise ValidationError("registry lineage mixes registry kinds")
    root_digest = canonical_sha256(values[0])
    if root_digest != _expected_root(kind):
        raise ValidationError(
            f"registry lineage root mismatch: expected {_expected_root(kind)}, got {root_digest}"
        )
    if kind == "sources":
        validate_source_registry_v4(values[0])
    else:
        validate_evaluation_registry_v4(values[0])

    ids = [str(item.get("registry_id", "")) for item in values]
    hashes = [canonical_sha256(item) for item in values]
    if duplicate := _duplicates(ids):
        raise ValidationError(f"duplicate registry IDs in lineage: {sorted(duplicate)}")
    if duplicate := _duplicates(hashes):
        raise ValidationError(
            f"duplicate registry hashes in lineage: {sorted(duplicate)}"
        )
    times = [
        _parse_time(item["generated_at"], "registry generated_at") for item in values
    ]
    if any(current <= previous for previous, current in pairwise(times)):
        raise ValidationError("registry lineage timestamps must strictly increase")

    for predecessor, successor in pairwise(values):
        expected = canonical_sha256(predecessor)
        if successor.get("previous_registry_sha256") != expected:
            raise ValidationError(
                "registry lineage transition is missing, skipped, or reordered"
            )
        if kind == "sources":
            _validate_source_transition(predecessor, successor)
        else:
            _validate_evaluation_transition(predecessor, successor)

    receipt = {
        "schema_version": SCHEMA_VERSION_V4_1,
        "record_kind": "registry_lineage_receipt",
        "registry_kind": kind,
        "root_sha256": root_digest,
        "tip_sha256": hashes[-1],
        "registry_count": len(values),
        "transition_count": len(values) - 1,
        "registry_ids": ids,
        "registry_sha256s": hashes,
        "generated_at_first": values[0]["generated_at"],
        "generated_at_last": values[-1]["generated_at"],
        "training_authorized": False,
    }
    validate_v4_1(receipt, "execution-evidence.schema.json")
    return VerifiedRegistryLineage(
        registries=values,
        receipt=receipt,
        sha256=canonical_sha256(receipt),
    )


def publisher_pin_registry_v4_1(
    registry: dict[str, Any], *, registry_id: str, generated_at: str
) -> dict[str, Any]:
    """Create the one canonical publisher-URL successor of the source root."""

    lineage = validate_registry_lineage_v4_1([registry])
    if lineage.receipt["registry_kind"] != "sources":
        raise ValidationError("publisher pinning requires the source registry root")
    if not registry_id.strip() or registry_id == registry["registry_id"]:
        raise ValidationError("publisher-pinned registry needs a fresh registry_id")
    if _parse_time(generated_at, "generated_at") <= _parse_time(
        registry["generated_at"], "predecessor generated_at"
    ):
        raise ValidationError("publisher-pinned registry timestamp must increase")
    result = copy.deepcopy(registry)
    result["registry_id"] = registry_id
    result["previous_registry_sha256"] = canonical_sha256(registry)
    result["generated_at"] = generated_at
    for requirement in result["publisher_evidence_requirements"]:
        artifact_id = requirement["artifact_id"]
        if artifact_id not in _PUBLISHER_URL_BY_ARTIFACT:
            raise ValidationError(f"unexpected source artifact: {artifact_id}")
        requirement["statement_url"] = _PUBLISHER_URL_BY_ARTIFACT[artifact_id]
    if result["sources"] != registry["sources"]:
        raise AssertionError("publisher pinning changed source entries")
    validate_registry_lineage_v4_1([registry, result])
    return result


@contextmanager
def _open_regular(path: Path, description: str) -> Iterator[BinaryIO]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise IntegrityError(
            f"cannot open {description} safely: {path}: {exc}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise IntegrityError(f"{description} is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            yield handle
        after = os.fstat(descriptor)
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
        if identity_before != identity_after:
            raise IntegrityError(f"{description} changed while it was read: {path}")
    finally:
        os.close(descriptor)


def _hash_handle(handle: BinaryIO) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_count = 0
    while chunk := handle.read(8 * 1024 * 1024):
        digest.update(chunk)
        byte_count += len(chunk)
    return byte_count, f"sha256:{digest.hexdigest()}"


def _hash_regular_file(path: Path, description: str) -> tuple[int, str]:
    with _open_regular(path, description) as handle:
        return _hash_handle(handle)


def _safe_member_path(name: str, *, directory: bool = False) -> str:
    candidate = name[:-1] if directory and name.endswith("/") else name
    if (
        not candidate
        or "\\" in candidate
        or "\x00" in candidate
        or candidate.startswith("/")
    ):
        raise IntegrityError(f"unsafe archive member path: {name!r}")
    path = PurePosixPath(candidate)
    if any(part in {"", ".", ".."} for part in path.parts) or str(path) != candidate:
        raise IntegrityError(f"unsafe archive member path: {name!r}")
    return candidate


def _hash_stream(stream: BinaryIO, expected_bytes: int, member: str) -> tuple[int, str]:
    measured = _hash_handle(stream)
    if measured[0] != expected_bytes:
        raise IntegrityError(f"archive member size changed while reading: {member}")
    return measured


def _measure_zip(handle: BinaryIO) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        archive = zipfile.ZipFile(handle)
    except (OSError, zipfile.BadZipFile) as exc:
        raise IntegrityError("evaluation archive is not a valid ZIP file") from exc
    with archive:
        for info in archive.infolist():
            name = _safe_member_path(info.filename, directory=info.is_dir())
            if name in seen:
                raise IntegrityError(f"duplicate archive member: {name}")
            seen.add(name)
            unix_mode = info.external_attr >> 16
            file_type = stat.S_IFMT(unix_mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise IntegrityError(f"unsafe non-regular ZIP member: {name}")
            if info.flag_bits & 0x1:
                raise IntegrityError(f"encrypted ZIP member is not allowed: {name}")
            if info.is_dir():
                continue
            try:
                with archive.open(info, "r") as member_handle:
                    byte_count, sha256 = _hash_stream(
                        member_handle, info.file_size, name
                    )
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise IntegrityError(f"cannot read ZIP member safely: {name}") from exc
            result.append(
                {"member_path": name, "byte_count": byte_count, "sha256": sha256}
            )
    return result


def _measure_tar(handle: BinaryIO) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        archive = tarfile.open(fileobj=handle, mode="r:*")  # noqa: SIM115
    except (OSError, tarfile.TarError) as exc:
        raise IntegrityError("evaluation archive is not a valid TAR file") from exc
    with archive:
        for info in archive:
            name = _safe_member_path(info.name, directory=info.isdir())
            if name in seen:
                raise IntegrityError(f"duplicate archive member: {name}")
            seen.add(name)
            if info.isdir():
                continue
            if not info.isreg():
                raise IntegrityError(f"unsafe non-regular TAR member: {name}")
            member_handle = archive.extractfile(info)
            if member_handle is None:
                raise IntegrityError(f"cannot read TAR member: {name}")
            with member_handle:
                byte_count, sha256 = _hash_stream(member_handle, info.size, name)
            result.append(
                {"member_path": name, "byte_count": byte_count, "sha256": sha256}
            )
    return result


def _measure_archive(
    path: Path, archive_format: str
) -> tuple[str, list[dict[str, Any]]]:
    with _open_regular(path, "evaluation archive") as handle:
        _, archive_sha256 = _hash_handle(handle)
        handle.seek(0)
        if archive_format == "zip":
            members = _measure_zip(handle)
        elif archive_format == "tar":
            members = _measure_tar(handle)
        elif archive_format == "raw":
            name = _safe_member_path(path.name)
            handle.seek(0)
            byte_count, member_sha256 = _hash_handle(handle)
            members = [
                {
                    "member_path": name,
                    "byte_count": byte_count,
                    "sha256": member_sha256,
                }
            ]
        else:
            raise ValidationError(f"unsupported archive_format: {archive_format!r}")
    if not members:
        raise IntegrityError("evaluation archive has no regular members")
    return archive_sha256, sorted(members, key=lambda item: item["member_path"])


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], field: str
) -> None:
    observed = set(value)
    if observed != expected:
        raise ValidationError(
            f"{field} fields differ: missing={sorted(expected - observed)}, "
            f"extra={sorted(observed - expected)}"
        )


def _validate_materialization_inventory(inventory: dict[str, Any]) -> None:
    _require_exact_keys(
        inventory,
        {
            "schema_version",
            "record_kind",
            "archive_format",
            "members",
            "record_primary_units",
            "oracle_id",
        },
        "materialization inventory",
    )
    if inventory["schema_version"] != SCHEMA_VERSION_V4_1:
        raise ValidationError("materialization inventory version mismatch")
    if inventory["record_kind"] != "evaluation_materialization_inventory":
        raise ValidationError("materialization inventory kind mismatch")
    if inventory["archive_format"] not in {"zip", "tar", "raw"}:
        raise ValidationError("materialization archive format is invalid")
    if (
        not isinstance(inventory["oracle_id"], str)
        or not inventory["oracle_id"].strip()
    ):
        raise ValidationError("materialization oracle_id is empty")
    members = inventory["members"]
    mappings = inventory["record_primary_units"]
    if not isinstance(members, list) or not members:
        raise ValidationError("materialization member inventory is empty")
    if not isinstance(mappings, list) or not mappings:
        raise ValidationError("materialization record mapping is empty")
    paths: list[str] = []
    for item in members:
        if not isinstance(item, dict):
            raise ValidationError("materialization member must be an object")
        _require_exact_keys(
            item, {"member_path", "role", "primary_unit_id"}, "member inventory"
        )
        path = _safe_member_path(str(item["member_path"]))
        paths.append(path)
        if item["role"] not in {"primary", "support"}:
            raise ValidationError(f"invalid archive member role: {path}")
        primary_id = item["primary_unit_id"]
        if item["role"] == "primary":
            if not isinstance(primary_id, str) or not primary_id.strip():
                raise ValidationError(f"primary archive member lacks unit ID: {path}")
        elif primary_id is not None:
            raise ValidationError(
                f"support archive member carries a primary unit: {path}"
            )
    if duplicate := _duplicates(paths):
        raise ValidationError(f"duplicate materialization member: {sorted(duplicate)}")
    record_ids: list[str] = []
    for item in mappings:
        if not isinstance(item, dict):
            raise ValidationError("materialization record mapping must be an object")
        _require_exact_keys(
            item, {"record_id", "primary_unit_ids"}, "record-primary mapping"
        )
        record_id = item["record_id"]
        units = item["primary_unit_ids"]
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValidationError("materialization mapping has an empty record_id")
        if (
            not isinstance(units, list)
            or not units
            or not all(isinstance(unit, str) and unit.strip() for unit in units)
            or len(units) != len(set(units))
        ):
            raise ValidationError(f"invalid primary-unit mapping: {record_id}")
        record_ids.append(record_id)
    if duplicate := _duplicates(record_ids):
        raise ValidationError(
            f"duplicate materialized record mapping: {sorted(duplicate)}"
        )


def _normalize_materialization_inventory(
    inventory: dict[str, Any],
) -> dict[str, Any]:
    normalized = copy.deepcopy(inventory)
    normalized["members"] = sorted(
        normalized["members"], key=lambda item: item["member_path"]
    )
    normalized["record_primary_units"] = sorted(
        (
            {
                "record_id": item["record_id"],
                "primary_unit_ids": sorted(item["primary_unit_ids"]),
            }
            for item in normalized["record_primary_units"]
        ),
        key=lambda item: item["record_id"],
    )
    return normalized


def _normal_identifier(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_identifier(
        str(value["namespace"]), str(value["value"]), value.get("source_version")
    )
    return {
        "namespace": normalized.namespace,
        "value": normalized.value,
        "source_version": normalized.source_version,
    }


def _selector_count(record: Mapping[str, Any]) -> int:
    selectors = record["selectors"]
    return sum(
        len(selectors[field])
        for field in ("identifiers", "raw_hashes", "normalized_hashes", "fingerprints")
    )


def _manifest_inventory(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION_V4_1,
        "record_kind": "evaluation_materialization_inventory",
        "archive_format": manifest["archive_format"],
        "members": [
            {
                "member_path": item["member_path"],
                "role": item["role"],
                "primary_unit_id": item["primary_unit_id"],
            }
            for item in manifest["archive_members"]
        ],
        "record_primary_units": [
            {
                "record_id": item["record_id"],
                "primary_unit_ids": item["primary_unit_ids"],
            }
            for item in manifest["record_bindings"]
        ],
        "oracle_id": manifest["oracle_id"],
    }


def _reject_public_leakage(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in _PUBLIC_RECEIPT_FORBIDDEN_KEYS:
                raise QuarantineError(
                    f"private materialization field leaked at {path}/{key}"
                )
            _reject_public_leakage(child, f"{path}/{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _reject_public_leakage(child, f"{path}/{index}")


def _materialization_receipt(manifest: dict[str, Any]) -> dict[str, Any]:
    validate_v4_1(manifest, "execution-evidence.schema.json")
    if manifest.get("record_kind") != "evaluation_materialization_manifest":
        raise ValidationError("expected an evaluation materialization manifest")
    primary_units = {
        item["primary_unit_id"]
        for item in manifest["archive_members"]
        if item["role"] == "primary"
    }
    support_count = sum(
        item["role"] == "support" for item in manifest["archive_members"]
    )
    dependency_bindings = [
        {
            "record_sha256": item["record_sha256"],
            "expected_dependency_sha256s": item["expected_dependency_sha256s"],
            "resolved_dependency_sha256s": item["resolved_dependency_sha256s"],
        }
        for item in manifest["record_bindings"]
    ]
    result = {
        "schema_version": SCHEMA_VERSION_V4_1,
        "record_kind": "evaluation_materialization_receipt",
        "receipt_id": f"{manifest['manifest_id']}.receipt",
        "dataset_id": manifest["dataset_id"],
        "usage_role": manifest["usage_role"],
        "evaluation_registry_sha256": manifest["evaluation_registry_sha256"],
        "dataset_entry_sha256": manifest["dataset_entry_sha256"],
        "archive_sha256": manifest["archive_sha256"],
        "adapter_id": manifest["adapter_id"],
        "adapter_sha256": manifest["adapter_sha256"],
        "oracle_id": manifest["oracle_id"],
        "oracle_sha256": manifest["oracle_sha256"],
        "envelope_sha256": manifest["envelope_sha256"],
        "inventory_sha256": manifest["inventory_sha256"],
        "manifest_sha256": canonical_sha256(manifest),
        "records_root_sha256": canonical_sha256(
            [item["record_sha256"] for item in manifest["record_bindings"]]
        ),
        "dependencies_root_sha256": canonical_sha256(dependency_bindings),
        "archive_member_count": len(manifest["archive_members"]),
        "primary_unit_count": len(primary_units),
        "support_member_count": support_count,
        "output_record_count": len(manifest["record_bindings"]),
        "dependency_binding_count": sum(
            len(item["expected_dependency_sha256s"])
            for item in manifest["record_bindings"]
        ),
        "complete_primary_unit_coverage": True,
        "all_archive_members_accounted": True,
        "all_outputs_bound": True,
        "materialized_at": manifest["materialized_at"],
        "contains_evaluation_content": False,
        "training_authorized": False,
    }
    _reject_public_leakage(result)
    validate_v4_1(result, "execution-evidence.schema.json")
    return result


def materialize_evaluation_v4_1(
    *,
    evaluation_registry: dict[str, Any],
    dataset_id: str,
    archive_path: Path,
    adapter_path: Path,
    oracle_path: Path,
    envelope: dict[str, Any],
    inventory: dict[str, Any],
    manifest_id: str,
    materialized_at: str,
) -> VerifiedMaterialization:
    """Rehash and account for a pinned evaluation without exposing its content."""

    validate_evaluation_registry_v4(evaluation_registry)
    _validate_materialization_inventory(inventory)
    inventory = _normalize_materialization_inventory(inventory)
    datasets = [
        item
        for item in evaluation_registry["datasets"]
        if item["dataset_id"] == dataset_id
    ]
    if len(datasets) != 1:
        raise ValidationError(f"dataset_id must resolve exactly once: {dataset_id}")
    dataset = datasets[0]
    if dataset["custody_state"] != "pinned":
        raise GateBlocked("evaluation materialization requires a pinned registry entry")
    if _parse_time(materialized_at, "materialized_at") <= _parse_time(
        evaluation_registry["generated_at"], "evaluation registry generated_at"
    ):
        raise ValidationError("materialization must follow the pinned registry")
    if not manifest_id.strip():
        raise ValidationError("materialization manifest_id is empty")

    validate_v4(envelope, "evaluation-evidence.schema.json")
    if envelope.get("record_kind") != "evaluation_envelope":
        raise ValidationError("materialization input must be an evaluation envelope")
    build_quarantine_contribution_v4(envelope)
    for field in (
        "dataset_id",
        "usage_role",
        "resolved_version",
        "archive_sha256",
        "adapter_id",
        "adapter_sha256",
    ):
        if envelope[field] != dataset[field]:
            raise ValidationError(f"materialization envelope mismatch: {field}")

    archive_sha256, measured_members = _measure_archive(
        archive_path, inventory["archive_format"]
    )
    if archive_sha256 != dataset["archive_sha256"]:
        raise IntegrityError("evaluation archive digest differs from the pinned entry")
    _, adapter_sha256 = _hash_regular_file(adapter_path, "evaluation adapter")
    if adapter_sha256 != dataset["adapter_sha256"]:
        raise IntegrityError("evaluation adapter digest differs from the pinned entry")
    _, oracle_sha256 = _hash_regular_file(oracle_path, "evaluation oracle")
    if inventory["oracle_id"] == dataset["adapter_id"]:
        raise ValidationError(
            "evaluation oracle must have an identity distinct from the adapter"
        )
    if oracle_sha256 == adapter_sha256:
        raise IntegrityError("evaluation oracle must be byte-distinct from the adapter")

    declared_members = {item["member_path"]: item for item in inventory["members"]}
    measured_by_path = {item["member_path"]: item for item in measured_members}
    if set(declared_members) != set(measured_by_path):
        missing = sorted(set(measured_by_path) - set(declared_members))
        absent = sorted(set(declared_members) - set(measured_by_path))
        raise IntegrityError(
            "archive member accounting mismatch: "
            f"unaccounted={missing}, absent={absent}"
        )
    archive_members = [
        {
            "member_path": path,
            "role": declared_members[path]["role"],
            "primary_unit_id": declared_members[path]["primary_unit_id"],
            "byte_count": measured_by_path[path]["byte_count"],
            "sha256": measured_by_path[path]["sha256"],
        }
        for path in sorted(measured_by_path)
    ]
    primary_units = {
        item["primary_unit_id"] for item in archive_members if item["role"] == "primary"
    }
    if not primary_units:
        raise ValidationError("materialization declares no primary units")

    mappings = {
        item["record_id"]: sorted(item["primary_unit_ids"])
        for item in inventory["record_primary_units"]
    }
    records = {item["record_id"]: item for item in envelope["records"]}
    if len(records) != len(envelope["records"]):
        raise ValidationError("evaluation envelope contains duplicate record IDs")
    if set(mappings) != set(records):
        missing = sorted(set(records) - set(mappings))
        orphaned = sorted(set(mappings) - set(records))
        raise ValidationError(
            f"output record binding mismatch: missing={missing}, orphaned={orphaned}"
        )
    referenced_units = {unit for units in mappings.values() for unit in units}
    if not referenced_units <= primary_units:
        raise ValidationError(
            f"output records reference unknown primary units: {sorted(referenced_units - primary_units)}"
        )
    if referenced_units != primary_units:
        raise ValidationError(
            f"primary-unit coverage is incomplete: {sorted(primary_units - referenced_units)}"
        )

    nonce = envelope["commitment_nonce"]
    record_bindings: list[dict[str, Any]] = []
    for record_id in sorted(records):
        record = records[record_id]
        expected = sorted(
            (_normal_identifier(item) for item in record["expected_dependency_units"]),
            key=canonical_sha256,
        )
        resolved = sorted(
            (_normal_identifier(item) for item in record["resolved_dependency_units"]),
            key=canonical_sha256,
        )
        if record["unresolved_dependency_units"] or expected != resolved:
            raise QuarantineError(f"unresolved materialization dependency: {record_id}")
        expected_commitments = sorted(
            canonical_sha256({"commitment_nonce": nonce, "dependency": item})
            for item in expected
        )
        resolved_commitments = sorted(
            canonical_sha256({"commitment_nonce": nonce, "dependency": item})
            for item in resolved
        )
        record_bindings.append(
            {
                "record_id": record_id,
                "record_sha256": canonical_sha256(
                    {"commitment_nonce": nonce, "record": record}
                ),
                "primary_unit_ids": mappings[record_id],
                "expected_dependency_sha256s": expected_commitments,
                "resolved_dependency_sha256s": resolved_commitments,
                "unresolved_dependency_count": 0,
                "selector_count": _selector_count(record),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION_V4_1,
        "record_kind": "evaluation_materialization_manifest",
        "manifest_id": manifest_id,
        "dataset_id": dataset_id,
        "usage_role": dataset["usage_role"],
        "evaluation_registry_sha256": canonical_sha256(evaluation_registry),
        "dataset_entry_sha256": canonical_sha256(dataset),
        "archive_sha256": archive_sha256,
        "archive_format": inventory["archive_format"],
        "archive_members": archive_members,
        "adapter_id": dataset["adapter_id"],
        "adapter_sha256": adapter_sha256,
        "oracle_id": inventory["oracle_id"],
        "oracle_sha256": oracle_sha256,
        "envelope_sha256": canonical_sha256(envelope),
        "inventory_sha256": canonical_sha256(inventory),
        "commitment_nonce": nonce,
        "record_bindings": record_bindings,
        "materialized_at": materialized_at,
        "training_authorized": False,
    }
    validate_v4_1(manifest, "execution-evidence.schema.json")
    receipt = _materialization_receipt(manifest)
    return VerifiedMaterialization(
        manifest=manifest,
        receipt=receipt,
        envelope=copy.deepcopy(envelope),
        manifest_sha256=canonical_sha256(manifest),
        receipt_sha256=canonical_sha256(receipt),
    )


def verify_materialization_v4_1(
    *,
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    evaluation_registry: dict[str, Any],
    archive_path: Path,
    adapter_path: Path,
    oracle_path: Path,
    envelope: dict[str, Any],
) -> VerifiedMaterialization:
    validate_v4_1(manifest, "execution-evidence.schema.json")
    validate_v4_1(receipt, "execution-evidence.schema.json")
    if manifest.get("record_kind") != "evaluation_materialization_manifest":
        raise ValidationError("expected a materialization manifest")
    if receipt.get("record_kind") != "evaluation_materialization_receipt":
        raise ValidationError("expected a materialization receipt")
    expected = materialize_evaluation_v4_1(
        evaluation_registry=evaluation_registry,
        dataset_id=manifest["dataset_id"],
        archive_path=archive_path,
        adapter_path=adapter_path,
        oracle_path=oracle_path,
        envelope=envelope,
        inventory=_manifest_inventory(manifest),
        manifest_id=manifest["manifest_id"],
        materialized_at=manifest["materialized_at"],
    )
    if expected.manifest != manifest:
        raise ValidationError("materialization manifest is not reproducible")
    if expected.receipt != receipt:
        raise ValidationError("materialization receipt is not reproducible")
    return expected


def _materializations_by_dataset(
    values: Iterable[VerifiedMaterialization],
) -> dict[str, VerifiedMaterialization]:
    result: dict[str, VerifiedMaterialization] = {}
    manifest_ids: set[str] = set()
    receipt_ids: set[str] = set()
    for value in values:
        dataset_id = value.receipt["dataset_id"]
        if dataset_id in result:
            raise ValidationError(f"duplicate materialization: {dataset_id}")
        if value.manifest_sha256 != canonical_sha256(value.manifest):
            raise ValidationError(
                f"materialization manifest wrapper mismatch: {dataset_id}"
            )
        if value.receipt_sha256 != canonical_sha256(value.receipt):
            raise ValidationError(
                f"materialization receipt wrapper mismatch: {dataset_id}"
            )
        if value.receipt["envelope_sha256"] != canonical_sha256(value.envelope):
            raise ValidationError(
                f"materialization envelope wrapper mismatch: {dataset_id}"
            )
        if value.receipt != _materialization_receipt(value.manifest):
            raise ValidationError(
                f"materialization receipt derivation mismatch: {dataset_id}"
            )
        manifest_id = value.manifest["manifest_id"]
        receipt_id = value.receipt["receipt_id"]
        if manifest_id in manifest_ids or receipt_id in receipt_ids:
            raise ValidationError(
                f"duplicate materialization evidence ID: {dataset_id}"
            )
        manifest_ids.add(manifest_id)
        receipt_ids.add(receipt_id)
        result[dataset_id] = value
    return result


def validate_seal_authorization_v4_1(
    *,
    evaluation_registry: dict[str, Any],
    materialization: VerifiedMaterialization,
    assessment: dict[str, Any],
    verified_bundle: VerifiedBundle,
    created_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require pinned assets, materialization, and exact approved rights before sealing."""

    validate_evaluation_registry_v4(evaluation_registry)
    dataset_id = materialization.receipt["dataset_id"]
    matches = [
        item
        for item in evaluation_registry["datasets"]
        if item["dataset_id"] == dataset_id
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"materialized dataset resolves incorrectly: {dataset_id}"
        )
    dataset = matches[0]
    if dataset["usage_role"] != "confirmatory" or dataset["custody_state"] != "pinned":
        raise GateBlocked("seal create-v4.1 requires a pinned confirmatory entry")
    receipt_bindings = {
        "evaluation_registry_sha256": canonical_sha256(evaluation_registry),
        "dataset_entry_sha256": canonical_sha256(dataset),
        "archive_sha256": dataset["archive_sha256"],
        "adapter_id": dataset["adapter_id"],
        "adapter_sha256": dataset["adapter_sha256"],
        "envelope_sha256": canonical_sha256(materialization.envelope),
    }
    for field, expected in receipt_bindings.items():
        if materialization.receipt[field] != expected:
            raise ValidationError(f"materialization registry binding mismatch: {field}")
    if _parse_time(created_at, "seal created_at") <= _parse_time(
        materialization.receipt["materialized_at"], "materialized_at"
    ):
        raise ValidationError("seal creation must follow evaluation materialization")
    verify_assessment(
        assessment,
        verified_bundle,
        subject_kind="evaluation",
        subject_id=dataset_id,
        subject_binding_sha256=canonical_sha256(dataset),
        required_uses=EVALUATION_REQUIRED_USES,
        evaluated_at=created_at,
    )
    reviewed_at = _parse_time(assessment["reviewed_at"], "reviewed_at")
    pinned_at = _parse_time(
        evaluation_registry["generated_at"], "pinned registry generated_at"
    )
    materialized_at = _parse_time(
        materialization.receipt["materialized_at"], "materialized_at"
    )
    if reviewed_at <= pinned_at:
        raise ValidationError("pinned-entry rights review must follow registry pinning")
    if materialized_at <= reviewed_at:
        raise ValidationError("evaluation materialization must follow rights review")
    if assessment["review_id"] != dataset["licence_review_id"]:
        raise ValidationError("evaluation references another licence assessment")
    contribution = build_quarantine_contribution_v4(materialization.envelope)
    return dataset, contribution


def _assessment_maps(
    assessments: Iterable[dict[str, Any]],
    bundles: Mapping[str, VerifiedBundle],
) -> tuple[dict[str, dict[str, Any]], dict[str, VerifiedBundle]]:
    assessment_by_id: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        review_id = str(assessment.get("review_id", ""))
        if review_id in assessment_by_id:
            raise ValidationError(f"duplicate licence assessment: {review_id}")
        assessment_by_id[review_id] = assessment
    return assessment_by_id, dict(bundles)


def finalize_evaluations_v4_1(
    *,
    pinned_registry: dict[str, Any],
    materializations: Iterable[VerifiedMaterialization],
    licence_assessments: Iterable[dict[str, Any]],
    verified_bundles: Mapping[str, VerifiedBundle],
    verified_seals: Iterable[VerifiedSealReceipt],
    access_events: Mapping[str, Iterable[dict[str, Any]]],
    verified_access_anchors: Mapping[str, VerifiedAccessAnchor],
    registry_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Create the evidence-backed pinned-to-sealed evaluation successor."""

    validate_evaluation_registry_v4(pinned_registry)
    if any(item["custody_state"] != "pinned" for item in pinned_registry["datasets"]):
        raise GateBlocked("evaluation finalization requires every entry to be pinned")
    if registry_id == pinned_registry["registry_id"] or not registry_id.strip():
        raise ValidationError("final evaluation registry needs a fresh registry_id")
    final_time = _parse_time(generated_at, "final registry generated_at")
    if final_time <= _parse_time(
        pinned_registry["generated_at"], "pinned registry generated_at"
    ):
        raise ValidationError("final registry must follow the pinned registry")

    datasets = {item["dataset_id"]: item for item in pinned_registry["datasets"]}
    materialization_by_id = _materializations_by_dataset(materializations)
    if set(materialization_by_id) != set(datasets):
        raise GateBlocked("finalization requires one materialization per evaluation")
    assessment_by_id, bundle_by_id = _assessment_maps(
        licence_assessments, verified_bundles
    )
    expected_reviews = {item["licence_review_id"] for item in datasets.values()}
    if (
        set(assessment_by_id) != expected_reviews
        or set(bundle_by_id) != expected_reviews
    ):
        raise GateBlocked("finalization requires exact pinned-entry rights evidence")

    latest_times = [
        _parse_time(pinned_registry["generated_at"], "pinned registry generated_at")
    ]
    for dataset_id, dataset in datasets.items():
        materialization = materialization_by_id[dataset_id]
        receipt = materialization.receipt
        expected_receipt = {
            "evaluation_registry_sha256": canonical_sha256(pinned_registry),
            "dataset_entry_sha256": canonical_sha256(dataset),
            "archive_sha256": dataset["archive_sha256"],
            "adapter_id": dataset["adapter_id"],
            "adapter_sha256": dataset["adapter_sha256"],
        }
        for field, expected in expected_receipt.items():
            if receipt[field] != expected:
                raise ValidationError(
                    f"materialization binding mismatch: {dataset_id}:{field}"
                )
        latest_times.append(_parse_time(receipt["materialized_at"], "materialized_at"))
        review_id = dataset["licence_review_id"]
        assessment = assessment_by_id[review_id]
        verify_assessment(
            assessment,
            bundle_by_id[review_id],
            subject_kind="evaluation",
            subject_id=dataset_id,
            subject_binding_sha256=canonical_sha256(dataset),
            required_uses=EVALUATION_REQUIRED_USES,
            evaluated_at=generated_at,
        )
        reviewed_at = _parse_time(assessment["reviewed_at"], "reviewed_at")
        materialized_at = _parse_time(receipt["materialized_at"], "materialized_at")
        if reviewed_at <= _parse_time(
            pinned_registry["generated_at"], "pinned registry generated_at"
        ):
            raise ValidationError(
                f"pinned-entry rights review predates pinning: {dataset_id}"
            )
        if materialized_at <= reviewed_at:
            raise ValidationError(
                f"materialization does not follow rights review: {dataset_id}"
            )
        latest_times.append(reviewed_at)

    seal_by_dataset: dict[str, VerifiedSealReceipt] = {}
    for seal in verified_seals:
        dataset_id = seal.receipt["dataset_id"]
        if dataset_id in seal_by_dataset:
            raise ValidationError(f"duplicate seal: {dataset_id}")
        seal_by_dataset[dataset_id] = seal
    confirmatory = {
        dataset_id: dataset
        for dataset_id, dataset in datasets.items()
        if dataset["usage_role"] == "confirmatory"
    }
    if set(seal_by_dataset) != set(confirmatory):
        raise GateBlocked("finalization requires exact confirmatory seal coverage")
    expected_seal_ids = {item["seal_id"] for item in confirmatory.values()}
    event_by_seal = {key: list(value) for key, value in access_events.items()}
    anchors = dict(verified_access_anchors)
    if set(event_by_seal) != expected_seal_ids or set(anchors) != expected_seal_ids:
        raise GateBlocked("finalization requires exact access-log and anchor coverage")

    for dataset_id, dataset in confirmatory.items():
        materialization = materialization_by_id[dataset_id]
        contribution = build_quarantine_contribution_v4(materialization.envelope)
        seal = seal_by_dataset[dataset_id]
        if seal.sha256 != canonical_sha256(seal.receipt):
            raise ValidationError(f"seal wrapper digest mismatch: {dataset_id}")
        verify_seal_receipt_v4(
            seal.receipt,
            evaluation_registry=pinned_registry,
            contribution=contribution,
            ciphertext_sha256=seal.ciphertext_sha256,
        )
        if (
            seal.receipt["public_key_fingerprint"]
            != dataset["custodian_signing_key_fingerprint"]
        ):
            raise ValidationError(
                f"seal key differs from pinned custodian key: {dataset_id}"
            )
        seal_id = dataset["seal_id"]
        events = event_by_seal[seal_id]
        anchor = anchors[seal_id]
        if not events or events[0]["action"] != "seal_created":
            raise ValidationError(
                f"access log does not begin at seal creation: {dataset_id}"
            )
        expected_materialization_digest = canonical_sha256(materialization.receipt)
        if events[0]["details"] != {"receipt_id": expected_materialization_digest}:
            raise ValidationError(
                f"seal-created event does not bind materialization: {dataset_id}"
            )
        verify_access_chain(
            events,
            expected_head=anchor.anchor["head_event_sha256"],
            expected_count=anchor.anchor["event_count"],
        )
        if any(event["seal_id"] != seal_id for event in events):
            raise ValidationError(f"access log crosses seals: {dataset_id}")
        if any(consumes_evaluation(event["action"]) for event in events):
            raise GateBlocked(f"confirmatory evaluation was consumed: {dataset_id}")
        if anchor.sha256 != canonical_sha256(anchor.anchor):
            raise ValidationError(f"anchor wrapper digest mismatch: {dataset_id}")
        validate_v4(anchor.anchor, "access-anchor.schema.json")
        if anchor.anchor["seal_receipt_sha256"] != seal.sha256:
            raise ValidationError(f"anchor seal binding mismatch: {dataset_id}")
        if (
            anchor.anchor["signing_key_fingerprint"]
            != dataset["custodian_signing_key_fingerprint"]
        ):
            raise ValidationError(
                f"anchor payload key differs from pinned key: {dataset_id}"
            )
        if (
            anchor.signing_key_fingerprint
            != dataset["custodian_signing_key_fingerprint"]
        ):
            raise ValidationError(f"anchor key differs from pinned key: {dataset_id}")
        materialized_at = _parse_time(
            materialization.receipt["materialized_at"], "materialized_at"
        )
        seal_created_at = _parse_time(seal.receipt["created_at"], "seal created_at")
        event_times = [_parse_time(event["at"], "access event at") for event in events]
        anchored_at = _parse_time(anchor.anchor["anchored_at"], "anchored_at")
        valid_until = _parse_time(anchor.anchor["valid_until"], "valid_until")
        if seal_created_at <= materialized_at:
            raise ValidationError(f"seal does not follow materialization: {dataset_id}")
        if event_times != sorted(event_times) or event_times[0] < seal_created_at:
            raise ValidationError(f"access-log chronology is invalid: {dataset_id}")
        if event_times[-1] > anchored_at:
            raise ValidationError(f"anchor predates its access log: {dataset_id}")
        if (
            valid_until <= anchored_at
            or valid_until - anchored_at > timedelta(hours=72)
            or final_time > valid_until
        ):
            raise ValidationError(f"access anchor is stale or invalid: {dataset_id}")
        latest_times.extend(event_times)
        latest_times.append(seal_created_at)
        latest_times.append(anchored_at)

    if final_time <= max(latest_times):
        raise ValidationError(
            "final registry timestamp must follow every supplied evidence event"
        )

    result = copy.deepcopy(pinned_registry)
    result["registry_id"] = registry_id
    result["previous_registry_sha256"] = canonical_sha256(pinned_registry)
    result["generated_at"] = generated_at
    for entry in result["datasets"]:
        old = datasets[entry["dataset_id"]]
        cleared = set()
        if entry["archive_sha256"] is not None:
            cleared.add("archive_hash_missing")
        if entry["adapter_id"] is not None and entry["adapter_sha256"] is not None:
            cleared.add("adapter_missing")
        cleared.update(_MATERIALIZATION_BACKED_BLOCKERS)
        cleared.update(_RIGHTS_BACKED_BLOCKERS)
        if entry["usage_role"] == "confirmatory":
            cleared.update(_CUSTODY_BACKED_BLOCKERS)
            entry["custody_state"] = "sealed"
        entry["blockers"] = [
            blocker for blocker in old["blockers"] if blocker not in cleared
        ]
        entry["previous_entry_sha256"] = canonical_sha256(old)
        if entry["usage_role"] == "confirmatory" and entry["blockers"]:
            raise GateBlocked(
                f"confirmatory entry retains unsupported blockers: {entry['dataset_id']}"
            )
    validate_evaluation_registry_v4(result, pinned_registry)
    if _parse_time(
        result["generated_at"], "final registry generated_at"
    ) <= _parse_time(pinned_registry["generated_at"], "pinned registry generated_at"):
        raise ValidationError("final evaluation registry timestamp did not increase")
    _validate_evaluation_transition(pinned_registry, result)
    return result


def verify_finalized_evaluations_v4_1(
    final_registry: dict[str, Any],
    *,
    pinned_registry: dict[str, Any],
    materializations: Iterable[VerifiedMaterialization],
    licence_assessments: Iterable[dict[str, Any]],
    verified_bundles: Mapping[str, VerifiedBundle],
    verified_seals: Iterable[VerifiedSealReceipt],
    access_events: Mapping[str, Iterable[dict[str, Any]]],
    verified_access_anchors: Mapping[str, VerifiedAccessAnchor],
) -> None:
    expected = finalize_evaluations_v4_1(
        pinned_registry=pinned_registry,
        materializations=materializations,
        licence_assessments=licence_assessments,
        verified_bundles=verified_bundles,
        verified_seals=verified_seals,
        access_events=access_events,
        verified_access_anchors=verified_access_anchors,
        registry_id=final_registry.get("registry_id", ""),
        generated_at=final_registry.get("generated_at", ""),
    )
    if final_registry != expected:
        raise ValidationError("final evaluation registry is not reproducible")
