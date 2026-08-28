"""Command-line interface containing Phase 0 operations only."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hippocampus_foundation.licence_catalog import (
    capture_catalogue,
    load_catalogue,
    prepare_catalogue_packets,
    rebind_catalogue_packets,
    validate_catalogue,
)
from hippocampus_foundation.licensing import (
    FORBIDDEN_USES,
    build_evidence_bundle,
    capture_https_document,
    load_verified_bundle,
    make_pending_assessment,
    verify_assessment,
    verify_evidence_bundle,
)
from hippocampus_foundation.licensing import (
    validate_schema_lock_v1 as validate_licensing_schema_lock_v1,
)
from hippocampus_foundation.licensing import (
    validate_v1 as validate_licensing_v1,
)
from hippocampus_foundation.storage_identity import (
    bind_drive_observation,
    validate_observation_v1,
)
from hippocampus_foundation.storage_identity import (
    validate_schema_lock_v1 as validate_storage_schema_lock_v1,
)

from .acquisition import download_resumable, download_resumable_at, remote_metadata
from .authority_v4_2 import (
    APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
    VerifiedAcquisitionAuthorization,
    VerifiedOAuthAuthority,
    load_oauth_config_identity,
    make_acquisition_authorization_payload,
    make_oauth_authority_payload,
    validate_acquisition_authorization_time,
    validate_oauth_authority_time,
    verify_acquisition_authorization,
    verify_oauth_authority,
)
from .canonical import (
    canonical_bytes,
    canonical_sha256,
    dump_pretty,
    load_json,
    sha256_bytes,
)
from .drive_access_v4_2 import (
    make_drive_identity_marker,
    observe_drive_access_from_adc,
)
from .errors import GateBlocked, Phase0Error
from .evaluation_firewall import (
    VerifiedSealReceipt,
    build_quarantine_contribution_v4,
    compile_quarantine_index_v4,
    make_seal_receipt_v4,
    validate_evaluation_registry_v4,
    validate_source_registry_v4,
    verify_seal_ciphertext_v4,
)
from .execution_v4_1 import (
    VerifiedMaterialization,
    finalize_evaluations_v4_1,
    materialize_evaluation_v4_1,
    publisher_pin_registry_v4_1,
    validate_registry_lineage_v4_1,
    validate_seal_authorization_v4_1,
    verify_materialization_v4_1,
)
from .external_evidence import (
    MAX_OPENPGP_EVIDENCE_BYTES,
    MAX_PUBLISHER_STATEMENT_BYTES,
    VerifiedAccessAnchor,
    VerifiedPublisherReceipt,
    _verify_detached_signature_gpg,
    bind_drive_observation_v4,
    build_publisher_checksum_receipt_v4,
    make_access_anchor_payload_v4,
    verify_access_anchor_v4,
    verify_publisher_checksum_receipt_v4,
)
from .gate import evaluate_gate
from .inventory import audit_source_registry, stream_count
from .quarantine import (
    Identifier,
    compile_public_index,
    fingerprint_text,
    match_record,
    normalize_identifier,
)
from .quarantine_v4 import (
    build_source_record_descriptor_v4,
    match_quarantine_record_v4,
)
from .seal import (
    append_access_event,
    encrypt_canonical_bundle,
    make_seal_receipt,
    read_access_events,
    resolve_public_key_fingerprint,
    verify_ciphertext,
)
from .source_evidence_v4 import (
    assess_admission_v4,
    audit_source_registry_v4,
    build_structural_inventory_v4,
)
from .v2 import (
    assess_admission_v2,
    audit_source_registry_v2,
    build_quarantine_contribution_v2,
    build_structural_inventory_v2,
    compile_quarantine_index_v2,
    evaluate_gate_v2,
    make_seal_receipt_v2,
    validate_evaluation_registry_v2,
    validate_schema_lock_v2,
    validate_source_registry_v2,
    validate_v2,
    verify_licence_review_v2,
)
from .v3 import (
    assess_admission_v3,
    evaluate_gate_v3,
)
from .v4 import evaluate_gate_v4
from .v4_1 import evaluate_gate_v4_1
from .v4_1_contracts import validate_schema_lock_v4_1, validate_v4_1
from .v4_2 import AcquisitionEvidenceBundle, evaluate_gate_v4_2
from .v4_2_contracts import validate_schema_lock_v4_2, validate_v4_2
from .v4_contracts import validate_schema_lock_v4, validate_v4
from .validation import (
    validate_evaluation_registry,
    validate_instance,
    validate_json_file,
    validate_schema_set,
    validate_source_audit,
    validate_source_registry,
)


def _emit(value: Any) -> None:
    sys.stdout.write(dump_pretty(value))


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, value: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(dump_pretty(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_stdin_json() -> Any:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise Phase0Error(f"invalid JSON on stdin: {exc}") from exc


def _read_bounded_regular_file(path: Path, maximum_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise Phase0Error(f"cannot open {label} safely: {path}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise Phase0Error(f"{label} is not a regular file: {path}")
        if before.st_size > maximum_bytes:
            raise Phase0Error(f"{label} exceeds its size limit: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            value = handle.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise Phase0Error(f"cannot read {label} safely: {path}") from exc
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
    if len(value) > maximum_bytes or identity_before != identity_after:
        raise Phase0Error(f"{label} changed or exceeded its size limit: {path}")
    return value


def _assignment(value: str, option: str) -> tuple[str, str]:
    left, separator, right = value.partition("=")
    if not separator or not left or not right:
        raise Phase0Error(f"{option} must be LEFT=RIGHT")
    return left, right


def _registry_validate_v1(args: argparse.Namespace) -> int:
    schemas = validate_schema_set(Path(args.schema_root) if args.schema_root else None)
    checked: list[str] = []
    for value in args.instance:
        path_text, schema_name = _assignment(value, "--instance")
        instance = validate_json_file(Path(path_text), schema_name)
        if schema_name == "source-manifest.schema.json":
            validate_source_registry(instance)
        elif schema_name == "source-audit.schema.json":
            validate_source_audit(instance)
        elif schema_name == "evaluation.schema.json":
            validate_evaluation_registry(instance)
        checked.append(path_text)
    _emit({"ok": True, "schemas": schemas, "instances": sorted(checked)})
    return 0


def _source_audit_v1(args: argparse.Namespace) -> int:
    registry = load_json(Path(args.registry))
    storage_map = load_json(Path(args.storage_map))
    validate_source_registry(registry)
    validate_instance(storage_map, "storage-map.schema.json")
    result = audit_source_registry(registry, storage_map)
    validate_source_audit(result)
    if args.output:
        _write_json_atomic(Path(args.output), result)
    _emit(result)
    return 0 if result["all_verified"] else 2


def _source_count_v1(args: argparse.Namespace) -> int:
    result = stream_count(Path(args.path), args.kind)
    if args.output:
        _write_json_atomic(Path(args.output), result)
    _emit(result)
    return 0


def _source_remote(args: argparse.Namespace) -> int:
    _emit(remote_metadata(args.url))
    return 0


def _source_acquire_v1(args: argparse.Namespace) -> int:
    registry = load_json(Path(args.registry))
    storage_map = load_json(Path(args.storage_map))
    evaluations = load_json(Path(args.evaluations))
    quarantine = load_json(Path(args.quarantine))
    source_audit = load_json(Path(args.source_audit))
    validate_source_registry(registry)
    validate_instance(storage_map, "storage-map.schema.json")
    receipts, verified_seal_ids = _load_verified_seals(args.seal)
    authorization = evaluate_gate(
        evaluated_at=args.evaluated_at,
        source_registry=registry,
        evaluation_registry=evaluations,
        quarantine_index=quarantine,
        seal_receipts=receipts,
        source_audit=source_audit,
        verified_seal_ids=verified_seal_ids,
    )
    if not authorization["foundation_acquisition_authorized"]:
        raise GateBlocked(
            "foundation acquisition gate is blocked: "
            + ", ".join(authorization["blockers"])
        )
    matches = [
        (source, artifact)
        for source in registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == args.artifact_id
    ]
    if len(matches) != 1:
        raise Phase0Error(
            f"--artifact-id must resolve exactly once, observed {len(matches)} matches"
        )
    source, artifact = matches[0]
    if (
        source["role"] != "foundation_candidate"
        or source["admission_status"] != "accepted"
    ):
        raise GateBlocked(
            f"artifact is not an accepted foundation candidate: {args.artifact_id}"
        )
    checksums = {
        item["algorithm"]: item["value"]
        for item in artifact["checksums"]
        if item["origin"] == "publisher" and item["verified"]
    }
    if artifact["expected_bytes"] is None:
        raise GateBlocked(f"artifact has no registered byte count: {args.artifact_id}")
    destination = Path(storage_map[artifact["locator_id"]]) / artifact["filename"]
    result = download_resumable(
        url=artifact["source_url"],
        destination=destination,
        expected_bytes=artifact["expected_bytes"],
        expected_checksums=checksums,
        minimum_free_bytes=args.minimum_free_bytes,
    )
    result["artifact_id"] = artifact["artifact_id"]
    result["authorization_gate_sha256"] = canonical_sha256(authorization)
    _emit(result)
    return 0


def _quarantine_fingerprint(args: argparse.Namespace) -> int:
    try:
        text = (
            Path(args.path).read_text(encoding="utf-8")
            if args.path != "-"
            else sys.stdin.read()
        )
    except OSError as exc:
        raise Phase0Error(f"cannot read fingerprint input {args.path}: {exc}") from exc
    _emit(fingerprint_text(text, args.fingerprint_id))
    return 0


def _parse_identifier(value: dict[str, Any]) -> Identifier:
    return normalize_identifier(
        value["namespace"], value["value"], value.get("source_version")
    )


def _quarantine_compile_v1(args: argparse.Namespace) -> int:
    specification = load_json(Path(args.specification))
    validate_instance(specification, "quarantine-specification.schema.json")
    bundles = []
    for bundle in specification["bundles"]:
        bundles.append(
            {
                **bundle,
                "seeds": [_parse_identifier(item) for item in bundle["seeds"]],
                "relationships": [
                    (
                        _parse_identifier(item["source"]),
                        item["relation"],
                        _parse_identifier(item["destination"]),
                    )
                    for item in bundle["relationships"]
                ],
            }
        )
    index = compile_public_index(
        index_id=specification["index_id"],
        bundles=bundles,
    )
    validate_instance(index, "quarantine-index.schema.json")
    if args.output:
        _write_json_atomic(Path(args.output), index)
    _emit(index)
    return 0


def _quarantine_check(args: argparse.Namespace) -> int:
    descriptor = load_json(Path(args.descriptor))
    index = load_json(Path(args.index))
    validate_instance(descriptor, "quarantine-descriptor.schema.json")
    validate_instance(index, "quarantine-index.schema.json")
    result = match_record(descriptor, index)
    _emit(result)
    return 0 if result["decision"] == "clear" else 2


def _seal_create_v1(args: argparse.Namespace) -> int:
    bundle = _load_stdin_json() if args.input == "-" else load_json(Path(args.input))
    fingerprint, ciphertext_sha256 = encrypt_canonical_bundle(
        bundle, Path(args.output), args.recipient
    )
    receipt = make_seal_receipt(
        seal_id=args.seal_id,
        evaluation_class=args.evaluation_class,
        ciphertext_sha256=ciphertext_sha256,
        artifact_hashes=args.artifact_hash,
        public_key_fingerprint=fingerprint,
        custodian=args.custodian,
        record_count=args.record_count,
    )
    validate_instance(receipt, "seal.schema.json")
    _write_json_atomic(Path(args.receipt), receipt)
    _emit(receipt)
    return 0


def _seal_verify_v1(args: argparse.Namespace) -> int:
    receipt = load_json(Path(args.receipt))
    validate_instance(receipt, "seal.schema.json")
    verify_ciphertext(Path(args.ciphertext), receipt)
    _emit({"ok": True, "seal_id": receipt["seal_id"]})
    return 0


def _seal_log_event(args: argparse.Namespace) -> int:
    try:
        details = json.loads(args.details)
    except json.JSONDecodeError as exc:
        raise Phase0Error(f"--details is invalid JSON: {exc}") from exc
    if not isinstance(details, dict):
        raise Phase0Error("--details must decode to a JSON object")
    event = append_access_event(
        log_path=Path(args.log),
        seal_id=args.seal_id,
        action=args.action,
        actor=args.actor,
        details=details,
    )
    validate_instance(event, "access-event.schema.json")
    _emit(event)
    return 0


def _seal_verify_log(args: argparse.Namespace) -> int:
    events = read_access_events(
        Path(args.log),
        expected_head=args.expected_head,
        expected_count=args.expected_count,
    )
    _emit(
        {
            "ok": True,
            "events": len(events),
            "head": events[-1]["event_hash"] if events else None,
            "externally_anchored": (
                args.expected_head is not None or args.expected_count is not None
            ),
        }
    )
    return 0


def _load_verified_seals(
    values: Sequence[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    receipts: list[dict[str, Any]] = []
    verified_seal_ids: set[str] = set()
    for value in values:
        ciphertext_text, receipt_text = _assignment(value, "--seal")
        receipt = load_json(Path(receipt_text))
        validate_instance(receipt, "seal.schema.json")
        verify_ciphertext(Path(ciphertext_text), receipt)
        receipts.append(receipt)
        verified_seal_ids.add(receipt["seal_id"])
    return receipts, verified_seal_ids


def _gate_v1(args: argparse.Namespace) -> int:
    sources = load_json(Path(args.sources))
    evaluations = load_json(Path(args.evaluations))
    quarantine = load_json(Path(args.quarantine)) if args.quarantine else None
    source_audit = load_json(Path(args.source_audit)) if args.source_audit else None
    receipts, verified_seal_ids = _load_verified_seals(args.seal)
    report = evaluate_gate(
        evaluated_at=args.evaluated_at,
        source_registry=sources,
        evaluation_registry=evaluations,
        quarantine_index=quarantine,
        seal_receipts=receipts,
        source_audit=source_audit,
        verified_seal_ids=verified_seal_ids,
    )
    if args.output:
        _write_json_atomic(Path(args.output), report)
    _emit(report)
    return 0 if report["public_foundation_ready"] else 2


def _registry_validate_v2(args: argparse.Namespace) -> int:
    digests = validate_schema_lock_v2(
        Path(args.schema_root) if args.schema_root else None
    )
    checked: list[str] = []
    for path_text in args.instance:
        path = Path(path_text)
        instance = load_json(path)
        if instance.get("registry_kind") == "sources":
            validate_source_registry_v2(instance)
        elif instance.get("registry_kind") == "evaluations":
            validate_evaluation_registry_v2(instance)
        elif instance.get("record_kind") in {
            "storage_attestation",
            "licence_review",
            "source_audit",
            "structural_inventory",
            "admission_receipt",
        }:
            validate_v2(instance, "control-evidence.schema.json")
        elif instance.get("record_kind") in {
            "evaluation_envelope",
            "quarantine_contribution",
            "quarantine_index",
            "seal_receipt",
        }:
            validate_v2(instance, "evaluation-evidence.schema.json")
        elif instance.get("gate_id") == "phase0-public-foundation-v2":
            validate_v2(instance, "gate.schema.json")
        else:
            raise Phase0Error(f"cannot identify Phase 0 v2 instance kind: {path}")
        checked.append(str(path))
    _emit({"ok": True, "schema_digests": digests, "instances": sorted(checked)})
    return 0


def _source_audit_v2(args: argparse.Namespace) -> int:
    registry = load_json(Path(args.registry))
    attestation = load_json(Path(args.storage_attestation))
    result = audit_source_registry_v2(registry, attestation)
    if args.output:
        _write_json_atomic(Path(args.output), result)
    _emit(result)
    return 0 if result["all_verified"] else 2


def _storage_contracts_validate_v1(args: argparse.Namespace) -> int:
    digests = validate_storage_schema_lock_v1(
        Path(args.schema_root) if args.schema_root else None
    )
    checked: list[str] = []
    for path_text in args.observation:
        observation = _json_object(Path(path_text))
        validate_observation_v1(observation, evaluated_at=args.evaluated_at)
        checked.append(path_text)
    _emit({"ok": True, "schema_digests": digests, "observations": sorted(checked)})
    return 0


def _storage_bind_drive_v1(args: argparse.Namespace) -> int:
    source_registry = _json_object(Path(args.registry))
    observation = _json_object(Path(args.observation))
    bound_at = args.bound_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    bound_registry, attestation = bind_drive_observation(
        source_registry,
        observation,
        verifier=args.verifier,
        bound_at=bound_at,
    )
    registry_output = Path(args.registry_output)
    attestation_output = Path(args.attestation_output)
    _refuse_output(registry_output)
    _refuse_output(attestation_output)
    _write_json_exclusive(registry_output, bound_registry)
    _write_json_exclusive(attestation_output, attestation)
    _emit(
        {
            "ok": True,
            "bound_at": bound_at,
            "observation_sha256": canonical_sha256(observation),
            "source_registry_sha256": canonical_sha256(bound_registry),
            "storage_attestation_sha256": canonical_sha256(attestation),
            "training_authorized": False,
        }
    )
    return 0


def _source_count_v2(args: argparse.Namespace) -> int:
    registry = load_json(Path(args.registry))
    attestation = load_json(Path(args.storage_attestation))
    source_audit = load_json(Path(args.source_audit))
    result = build_structural_inventory_v2(
        registry=registry,
        attestation=attestation,
        source_audit=source_audit,
        artifact_id=args.artifact_id,
    )
    if args.output:
        _write_json_atomic(Path(args.output), result)
    _emit(result)
    return 0


def _load_licence_reviews_v2(
    values: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    reviews: list[dict[str, Any]] = []
    verified_terms: dict[str, str] = {}
    for value in values:
        review_text, terms_text = _assignment(value, "--licence-review")
        review = load_json(Path(review_text))
        terms = Path(terms_text).read_bytes()
        validate_v2(review, "control-evidence.schema.json")
        verify_licence_review_v2(review, terms)
        review_id = review["review_id"]
        if review_id in verified_terms:
            raise Phase0Error(f"duplicate --licence-review: {review_id}")
        reviews.append(review)
        verified_terms[review_id] = sha256_bytes(terms)
    return reviews, verified_terms


def _licence_verify_v2(args: argparse.Namespace) -> int:
    review = load_json(Path(args.review))
    terms = Path(args.terms).read_bytes()
    verify_licence_review_v2(review, terms)
    _emit(
        {
            "ok": True,
            "review_id": review["review_id"],
            "terms_snapshot_sha256": sha256_bytes(terms),
        }
    )
    return 0


def _refuse_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise Phase0Error(f"refusing to overwrite output: {path}")


def _write_json_exclusive(path: Path, value: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise Phase0Error(f"refusing to overwrite output: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(dump_pretty(value))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _write_bytes_exclusive(path: Path, value: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise Phase0Error(f"refusing to overwrite output: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _json_object(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise Phase0Error(f"expected a JSON object: {path}")
    return value


def _licence_contracts_validate_v1(args: argparse.Namespace) -> int:
    digests = validate_licensing_schema_lock_v1(
        Path(args.schema_root) if args.schema_root else None
    )
    checked: list[str] = []
    for value in args.instance:
        path_text, schema_name = _assignment(value, "--instance")
        instance = _json_object(Path(path_text))
        validate_licensing_v1(instance, schema_name)
        checked.append(path_text)
    _emit({"ok": True, "schema_digests": digests, "instances": sorted(checked)})
    return 0


def _licence_capture_v1(args: argparse.Namespace) -> int:
    result = capture_https_document(
        url=args.url,
        document_id=args.document_id,
        role=args.role,
        source_kind=args.source_kind,
        output=Path(args.output),
        receipt=Path(args.receipt),
        allowed_hosts=args.allow_host,
        expected_media_type=args.expected_media_type,
        revision=args.revision,
        mutable=args.mutable,
        retrieved_at=args.retrieved_at,
    )
    _emit(result)
    return 0


def _licence_bundle_create_v1(args: argparse.Namespace) -> int:
    output = Path(args.output)
    _refuse_output(output)
    documents = [_json_object(Path(path)) for path in args.document]
    findings = [_json_object(Path(path)) for path in args.finding]
    bundle = build_evidence_bundle(
        bundle_id=args.bundle_id,
        review_id=args.review_id,
        subject_kind=args.subject_kind,
        subject_id=args.subject_id,
        subject_binding_sha256=args.subject_binding_sha256,
        documents=documents,
        findings=findings,
        assembled_at=args.assembled_at,
    )
    verify_evidence_bundle(bundle, output.parent)
    _write_json_exclusive(output, bundle, mode=0o600)
    _emit(
        {
            "ok": True,
            "bundle_id": bundle["bundle_id"],
            "sha256": canonical_sha256(bundle),
        }
    )
    return 0


def _licence_bundle_verify_v1(args: argparse.Namespace) -> int:
    verified = load_verified_bundle(Path(args.bundle))
    _emit(
        {
            "ok": True,
            "bundle_id": verified.bundle["bundle_id"],
            "review_id": verified.bundle["review_id"],
            "documents": len(verified.bundle["documents"]),
            "sha256": verified.sha256,
        }
    )
    return 0


def _licence_assessment_scaffold_v1(args: argparse.Namespace) -> int:
    output = Path(args.output)
    _refuse_output(output)
    verified = load_verified_bundle(Path(args.bundle))
    assessment = make_pending_assessment(verified.bundle)
    validate_licensing_v1(assessment, "licence-assessment.schema.json")
    _write_json_exclusive(output, assessment, mode=0o600)
    _emit(assessment)
    return 0


def _licence_assessment_finalize_v1(args: argparse.Namespace) -> int:
    output = Path(args.output)
    _refuse_output(output)
    verified = load_verified_bundle(Path(args.bundle))
    source = _json_object(Path(args.input))
    validate_licensing_v1(source, "licence-assessment.schema.json")
    if source["review_id"] != verified.bundle["review_id"]:
        raise Phase0Error("assessment and evidence bundle review IDs differ")

    dispositions = {
        item["finding_id"]: dict(item) for item in source["finding_dispositions"]
    }
    document_ids = {item["document_id"] for item in verified.bundle["documents"]}
    for value in args.resolve_finding:
        finding_id, document_id = _assignment(value, "--resolve-finding")
        if finding_id not in dispositions:
            raise Phase0Error(f"unknown licence finding: {finding_id}")
        if document_id not in document_ids:
            raise Phase0Error(f"unknown rationale evidence document: {document_id}")
        dispositions[finding_id] = {
            "finding_id": finding_id,
            "disposition": "resolved",
            "rationale_document_id": document_id,
        }
    for finding_id in args.acknowledge_finding:
        if finding_id not in dispositions:
            raise Phase0Error(f"unknown licence finding: {finding_id}")
        finding = next(
            item
            for item in verified.bundle["findings"]
            if item["finding_id"] == finding_id
        )
        if finding["blocking"]:
            raise Phase0Error("blocking findings require evidence-backed resolution")
        dispositions[finding_id] = {
            "finding_id": finding_id,
            "disposition": "acknowledged_nonblocking",
            "rationale_document_id": None,
        }

    obligations = [_json_object(Path(path)) for path in args.obligation]
    assessment = dict(source)
    assessment.update(
        {
            "decision": args.decision,
            "commercial_context": args.commercial_context,
            "licence_identifiers": args.licence_id or source["licence_identifiers"],
            "allowed_uses": sorted(set(args.allow_use)),
            "excluded_uses": sorted(set(args.exclude_use) | set(FORBIDDEN_USES)),
            "obligations": obligations,
            "finding_dispositions": sorted(
                dispositions.values(), key=lambda item: item["finding_id"]
            ),
            "reviewer": args.reviewer,
            "reviewed_at": args.reviewed_at,
            "valid_until": args.valid_until,
            "training_authorized": False,
            "notes": args.notes,
        }
    )
    validate_licensing_v1(assessment, "licence-assessment.schema.json")
    if args.decision in {"approved", "rejected"} and (
        not args.reviewer or not args.reviewed_at
    ):
        raise Phase0Error("a final human decision requires reviewer and reviewed-at")
    if args.decision == "approved":
        if not args.valid_until:
            raise Phase0Error("an approved assessment requires valid-until")
        verify_assessment(
            assessment,
            verified,
            subject_kind=verified.bundle["subject_kind"],
            subject_id=verified.bundle["subject_id"],
            subject_binding_sha256=verified.bundle["subject_binding_sha256"],
            required_uses=args.required_use,
            evaluated_at=args.evaluated_at
            or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
    _write_json_exclusive(output, assessment, mode=0o600)
    _emit(assessment)
    return 0


def _catalogue_inputs(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalogue = load_catalogue(Path(args.catalogue))
    sources = _json_object(Path(args.sources))
    evaluations = _json_object(Path(args.evaluations))
    encoder = _json_object(Path(args.encoder_spec))
    validate_catalogue(
        catalogue,
        source_registry=sources,
        evaluation_registry=evaluations,
        encoder_spec=encoder,
    )
    return catalogue, sources, evaluations, encoder


def _licence_catalogue_validate_v1(args: argparse.Namespace) -> int:
    catalogue, _, _, _ = _catalogue_inputs(args)
    _emit({"ok": True, "subjects": len(catalogue["subjects"])})
    return 0


def _licence_catalogue_capture_v1(args: argparse.Namespace) -> int:
    catalogue, _, _, _ = _catalogue_inputs(args)
    result = capture_catalogue(catalogue, output_root=Path(args.output_root))
    _emit(result)
    return 0


def _licence_catalogue_prepare_v1(args: argparse.Namespace) -> int:
    catalogue, sources, evaluations, encoder = _catalogue_inputs(args)
    assembled_at = args.assembled_at or datetime.now(UTC).isoformat().replace(
        "+00:00", "Z"
    )
    result = prepare_catalogue_packets(
        catalogue,
        source_registry=sources,
        evaluation_registry=evaluations,
        encoder_spec=encoder,
        evidence_root=Path(args.evidence_root),
        audit_index_path=Path(args.audit_index),
        assembled_at=assembled_at,
    )
    _emit(result)
    return 0


def _licence_catalogue_rebind(args: argparse.Namespace) -> int:
    catalogue, sources, evaluations, encoder = _catalogue_inputs(args)
    result = rebind_catalogue_packets(
        catalogue,
        source_registry=sources,
        evaluation_registry=evaluations,
        encoder_spec=encoder,
        verified_capture_root=Path(args.verified_capture_root),
        output_root=Path(args.output_root),
        audit_index_path=Path(args.audit_index),
        assembled_at=args.assembled_at,
    )
    _emit(result)
    return 0


def _quarantine_compile_v2(args: argparse.Namespace) -> int:
    contributions = [load_json(Path(path)) for path in args.contribution]
    index = compile_quarantine_index_v2(contributions, index_id=args.index_id)
    if args.output:
        _write_json_atomic(Path(args.output), index)
    _emit(index)
    return 0


def _seal_create_v2(args: argparse.Namespace) -> int:
    envelope = _load_stdin_json() if args.input == "-" else load_json(Path(args.input))
    validate_v2(envelope, "evaluation-evidence.schema.json")
    if envelope.get("record_kind") != "evaluation_envelope":
        raise Phase0Error("v2 seal input must be an evaluation_envelope")
    evaluations = load_json(Path(args.evaluations))
    validate_evaluation_registry_v2(evaluations)
    matches = [
        item
        for item in evaluations["datasets"]
        if item["dataset_id"] == envelope["dataset_id"]
    ]
    if len(matches) != 1:
        raise Phase0Error("envelope dataset_id does not resolve exactly once")
    dataset = matches[0]
    for field in (
        "seal_id",
        "resolved_version",
        "archive_sha256",
        "adapter_id",
        "adapter_sha256",
    ):
        if dataset[field] != envelope[field]:
            raise Phase0Error(f"envelope/registry binding mismatch: {field}")
    output_paths = [Path(args.output), Path(args.receipt), Path(args.contribution)]
    if any(path.exists() or path.is_symlink() for path in output_paths):
        raise Phase0Error("refusing to overwrite seal, receipt, or contribution output")
    contribution = build_quarantine_contribution_v2(envelope)
    fingerprint, ciphertext_sha256 = encrypt_canonical_bundle(
        envelope, Path(args.output), args.recipient
    )
    receipt = make_seal_receipt_v2(
        envelope=envelope,
        contribution=contribution,
        ciphertext_sha256=ciphertext_sha256,
        public_key_fingerprint=fingerprint,
        custodian=args.custodian,
    )
    _write_json_atomic(Path(args.contribution), contribution)
    _write_json_atomic(Path(args.receipt), receipt)
    _emit(receipt)
    return 0


def _load_verified_seals_v2(
    values: Sequence[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    receipts: list[dict[str, Any]] = []
    verified_seal_ids: set[str] = set()
    for value in values:
        ciphertext_text, receipt_text = _assignment(value, "--seal")
        receipt = load_json(Path(receipt_text))
        validate_v2(receipt, "evaluation-evidence.schema.json")
        verify_ciphertext(Path(ciphertext_text), receipt)
        receipts.append(receipt)
        verified_seal_ids.add(receipt["seal_id"])
    return receipts, verified_seal_ids


def _seal_verify_v2(args: argparse.Namespace) -> int:
    receipt = load_json(Path(args.receipt))
    validate_v2(receipt, "evaluation-evidence.schema.json")
    if receipt.get("record_kind") != "seal_receipt":
        raise Phase0Error("v2 seal verification requires a seal_receipt")
    verify_ciphertext(Path(args.ciphertext), receipt)
    _emit({"ok": True, "seal_id": receipt["seal_id"]})
    return 0


def _load_many(paths: Sequence[str]) -> list[dict[str, Any]]:
    return [load_json(Path(path)) for path in paths]


def _load_anchored_access_logs(
    values: Sequence[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    events_by_seal: dict[str, list[dict[str, Any]]] = {}
    heads_by_seal: dict[str, str] = {}
    for value in values:
        log_text, expected_head = _assignment(value, "--access-log")
        events = read_access_events(Path(log_text), expected_head=expected_head)
        if not events:
            raise Phase0Error(f"--access-log is empty: {log_text}")
        seal_ids = {event["seal_id"] for event in events}
        if len(seal_ids) != 1:
            raise Phase0Error(f"--access-log contains multiple seal IDs: {log_text}")
        seal_id = seal_ids.pop()
        if seal_id in events_by_seal:
            raise Phase0Error(f"duplicate --access-log for seal: {seal_id}")
        events_by_seal[seal_id] = events
        heads_by_seal[seal_id] = expected_head
    return events_by_seal, heads_by_seal


def _evaluate_from_v2_args(args: argparse.Namespace) -> dict[str, Any]:
    sources = load_json(Path(args.sources))
    evaluations = load_json(Path(args.evaluations))
    attestation = (
        load_json(Path(args.storage_attestation)) if args.storage_attestation else None
    )
    source_audit = load_json(Path(args.source_audit)) if args.source_audit else None
    quarantine = load_json(Path(args.quarantine)) if args.quarantine else None
    reviews, verified_terms = _load_licence_reviews_v2(args.licence_review)
    receipts, verified_seal_ids = _load_verified_seals_v2(args.seal)
    access_events, access_heads = _load_anchored_access_logs(args.access_log)
    return evaluate_gate_v2(
        evaluated_at=args.evaluated_at,
        source_registry=sources,
        evaluation_registry=evaluations,
        storage_attestation=attestation,
        source_audit=source_audit,
        licence_reviews=reviews,
        verified_terms_sha256=verified_terms,
        seal_receipts=receipts,
        quarantine_contributions=_load_many(args.contribution),
        quarantine_index=quarantine,
        structural_inventories=_load_many(args.inventory),
        admission_receipts=_load_many(args.admission),
        verified_seal_ids=verified_seal_ids,
        evaluation_access_events=access_events,
        evaluation_access_heads=access_heads,
    )


def _load_licence_assessments_v1(
    values: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assessments: list[dict[str, Any]] = []
    bundles: dict[str, Any] = {}
    for value in values:
        assessment_text, bundle_text = _assignment(value, "--licence-assessment")
        assessment = _json_object(Path(assessment_text))
        validate_licensing_v1(assessment, "licence-assessment.schema.json")
        verified = load_verified_bundle(Path(bundle_text))
        review_id = assessment["review_id"]
        if review_id != verified.bundle["review_id"]:
            raise Phase0Error("assessment and evidence bundle review IDs differ")
        if review_id in bundles:
            raise Phase0Error(f"duplicate --licence-assessment: {review_id}")
        assessments.append(assessment)
        bundles[review_id] = verified
    return assessments, bundles


def _evaluate_from_v3_args(args: argparse.Namespace) -> dict[str, Any]:
    sources = load_json(Path(args.sources))
    evaluations = load_json(Path(args.evaluations))
    attestation = (
        load_json(Path(args.storage_attestation)) if args.storage_attestation else None
    )
    source_audit = load_json(Path(args.source_audit)) if args.source_audit else None
    quarantine = load_json(Path(args.quarantine)) if args.quarantine else None
    assessments, bundles = _load_licence_assessments_v1(args.licence_assessment)
    receipts, verified_seal_ids = _load_verified_seals_v2(args.seal)
    access_events, access_heads = _load_anchored_access_logs(args.access_log)
    return evaluate_gate_v3(
        evaluated_at=args.evaluated_at,
        source_registry=sources,
        evaluation_registry=evaluations,
        storage_attestation=attestation,
        source_audit=source_audit,
        licence_assessments=assessments,
        verified_bundles=bundles,
        seal_receipts=receipts,
        quarantine_contributions=_load_many(args.contribution),
        quarantine_index=quarantine,
        structural_inventories=_load_many(args.inventory),
        admission_receipts=_load_many(args.admission),
        verified_seal_ids=verified_seal_ids,
        evaluation_access_events=access_events,
        evaluation_access_heads=access_heads,
    )


def _gate_v2(args: argparse.Namespace) -> int:
    report = _evaluate_from_v2_args(args)
    if args.output:
        _write_json_atomic(Path(args.output), report)
    _emit(report)
    return 0 if report["foundation_transform_ready"] else 2


def _gate_v3(args: argparse.Namespace) -> int:
    report = _evaluate_from_v3_args(args)
    if args.output:
        _write_json_atomic(Path(args.output), report)
    _emit(report)
    return 0 if report["foundation_transform_ready"] else 2


def _source_assess_admission_v2(args: argparse.Namespace) -> int:
    registry = load_json(Path(args.registry))
    attestation = load_json(Path(args.storage_attestation))
    source_audit = load_json(Path(args.source_audit))
    quarantine = load_json(Path(args.quarantine))
    review = load_json(Path(args.licence_review))
    terms = Path(args.terms).read_bytes()
    result = assess_admission_v2(
        source_id=args.source_id,
        registry=registry,
        storage_attestation=attestation,
        source_audit=source_audit,
        licence_review=review,
        verified_terms_sha256=sha256_bytes(terms),
        inventories=_load_many(args.inventory),
        quarantine_index=quarantine,
        assessor=args.assessor,
        assessed_at=args.assessed_at,
    )
    if args.output:
        _write_json_atomic(Path(args.output), result)
    _emit(result)
    return 0


def _source_assess_admission_v3(args: argparse.Namespace) -> int:
    assessment = _json_object(Path(args.licence_assessment))
    verified = load_verified_bundle(Path(args.licence_bundle))
    result = assess_admission_v3(
        source_id=args.source_id,
        registry=_json_object(Path(args.registry)),
        storage_attestation=_json_object(Path(args.storage_attestation)),
        source_audit=_json_object(Path(args.source_audit)),
        assessment=assessment,
        verified_bundle=verified,
        inventories=_load_many(args.inventory),
        quarantine_index=_json_object(Path(args.quarantine)),
        assessor=args.assessor,
        assessed_at=args.assessed_at,
    )
    if args.output:
        _write_json_atomic(Path(args.output), result)
    _emit(result)
    return 0


def _parts(value: str, option: str, count: int) -> list[str]:
    parts = value.split("=")
    if len(parts) != count or any(not part for part in parts):
        shape = "=".join(f"PART{index + 1}" for index in range(count))
        raise Phase0Error(f"{option} must be {shape}")
    return parts


def _registry_validate_v4(args: argparse.Namespace) -> int:
    digests = validate_schema_lock_v4(
        Path(args.schema_root) if args.schema_root else None
    )
    source_predecessor = (
        _json_object(Path(args.source_predecessor)) if args.source_predecessor else None
    )
    evaluation_predecessor = (
        _json_object(Path(args.evaluation_predecessor))
        if args.evaluation_predecessor
        else None
    )
    checked: list[str] = []
    schema_by_kind = {
        "storage_attestation": "storage-evidence.schema.json",
        "publisher_checksum_receipt": "publisher-evidence.schema.json",
        "evaluation_envelope": "evaluation-evidence.schema.json",
        "quarantine_contribution": "evaluation-evidence.schema.json",
        "quarantine_index": "evaluation-evidence.schema.json",
        "seal_receipt": "evaluation-evidence.schema.json",
        "access_log_anchor": "access-anchor.schema.json",
        "source_record_descriptor": "quarantine-decision.schema.json",
        "quarantine_decision": "quarantine-decision.schema.json",
        "source_audit": "source-evidence.schema.json",
        "structural_inventory": "source-evidence.schema.json",
        "admission_receipt": "source-evidence.schema.json",
    }
    for path_text in args.instance:
        instance = _json_object(Path(path_text))
        if instance.get("registry_kind") == "sources":
            validate_source_registry_v4(instance, source_predecessor)
        elif instance.get("registry_kind") == "evaluations":
            validate_evaluation_registry_v4(instance, evaluation_predecessor)
        elif instance.get("gate_id") == "phase0-external-evidence-firewall-v4":
            validate_v4(instance, "gate.schema.json")
        else:
            record_kind = instance.get("record_kind")
            schema_name = schema_by_kind.get(record_kind)
            if schema_name is None:
                raise Phase0Error(
                    f"cannot identify Phase 0 v4 instance kind: {path_text}"
                )
            validate_v4(instance, schema_name)
        checked.append(path_text)
    _emit(
        {
            "ok": True,
            "schema_digests": digests,
            "instances": sorted(checked),
            "training_authorized": False,
        }
    )
    return 0


def _registry_validate_v4_1(args: argparse.Namespace) -> int:
    digests = validate_schema_lock_v4_1(
        Path(args.schema_root) if args.schema_root else None
    )
    checked: list[str] = []
    for path_text in args.instance:
        instance = _json_object(Path(path_text))
        if instance.get("gate_id") == "phase0-external-evidence-firewall-v4.1":
            validate_v4_1(instance, "gate.schema.json")
        else:
            validate_v4_1(instance, "execution-evidence.schema.json")
        checked.append(path_text)
    _emit(
        {
            "ok": True,
            "schema_digests": digests,
            "instances": sorted(checked),
            "training_authorized": False,
        }
    )
    return 0


def _registry_validate_v4_2(args: argparse.Namespace) -> int:
    digests = validate_schema_lock_v4_2(
        Path(args.schema_root) if args.schema_root else None
    )
    checked: dict[str, str] = {}
    for path_text in args.instance:
        instance = _json_object(Path(path_text))
        if instance.get("gate_id") == "phase0-external-evidence-firewall-v4.2":
            validate_v4_2(instance, "gate.schema.json")
        elif instance.get("record_kind") == "oauth_authority_policy":
            validate_v4_2(instance, "authority-policy.schema.json")
        elif instance.get("record_kind") == "entor_drive_identity_marker":
            validate_v4_2(instance, "drive-identity-marker.schema.json")
        else:
            validate_v4_2(instance, "execution-evidence.schema.json")
        checked[path_text] = canonical_sha256(instance)
    _emit(
        {
            "ok": True,
            "schema_digests": digests,
            "instances": sorted(checked),
            "instance_digests": {path: checked[path] for path in sorted(checked)},
            "training_authorized": False,
        }
    )
    return 0


def _registry_lineage_v4_1(args: argparse.Namespace) -> int:
    verified = validate_registry_lineage_v4_1(
        [_json_object(Path(path)) for path in args.registry]
    )
    if args.output:
        _write_json_exclusive(Path(args.output), verified.receipt)
    _emit(verified.receipt)
    return 0


def _registry_publisher_pin_v4_1(args: argparse.Namespace) -> int:
    result = publisher_pin_registry_v4_1(
        _json_object(Path(args.registry)),
        registry_id=args.registry_id,
        generated_at=args.generated_at,
    )
    _write_json_exclusive(Path(args.output), result)
    _emit(
        {
            "ok": True,
            "registry_id": result["registry_id"],
            "registry_sha256": canonical_sha256(result),
            "training_authorized": False,
        }
    )
    return 0


def _storage_bind_drive_v4(args: argparse.Namespace) -> int:
    registry = _json_object(Path(args.registry))
    observation = _json_object(Path(args.observation))
    bound_at = args.bound_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    bound_registry, attestation = bind_drive_observation_v4(
        registry,
        observation,
        registry_id=args.registry_id,
        verifier=args.verifier,
        bound_at=bound_at,
    )
    registry_output = Path(args.registry_output)
    attestation_output = Path(args.attestation_output)
    _refuse_output(registry_output)
    _refuse_output(attestation_output)
    _write_json_exclusive(registry_output, bound_registry)
    _write_json_exclusive(attestation_output, attestation)
    _emit(
        {
            "ok": True,
            "bound_at": bound_at,
            "observation_sha256": canonical_sha256(observation),
            "source_registry_sha256": canonical_sha256(bound_registry),
            "storage_attestation_sha256": canonical_sha256(attestation),
            "training_authorized": False,
        }
    )
    return 0


def _source_publisher_receipt_v4(args: argparse.Namespace) -> int:
    registry = _json_object(Path(args.registry))
    statement = _read_bounded_regular_file(
        Path(args.statement),
        MAX_PUBLISHER_STATEMENT_BYTES,
        "publisher checksum statement",
    )
    receipt = build_publisher_checksum_receipt_v4(
        source_registry=registry,
        evidence_id=args.evidence_id,
        statement=statement,
        resolved_url=args.resolved_url,
        retrieved_at=args.retrieved_at,
        verified_at=args.verified_at,
        verifier=args.verifier,
    )
    output = Path(args.output)
    _refuse_output(output)
    _write_json_exclusive(output, receipt)
    _emit(receipt)
    return 0


def _load_publisher_receipts_v4(
    values: Sequence[str],
    *,
    source_registry: dict[str, Any],
    evaluated_at: str,
) -> list[VerifiedPublisherReceipt]:
    result: list[VerifiedPublisherReceipt] = []
    evidence_ids: set[str] = set()
    for value in values:
        statement_text, receipt_text = _parts(value, "--publisher", 2)
        receipt = _json_object(Path(receipt_text))
        verified = verify_publisher_checksum_receipt_v4(
            receipt,
            _read_bounded_regular_file(
                Path(statement_text),
                MAX_PUBLISHER_STATEMENT_BYTES,
                "publisher checksum statement",
            ),
            source_registry,
            evaluated_at=evaluated_at,
        )
        evidence_id = receipt["evidence_id"]
        if evidence_id in evidence_ids:
            raise Phase0Error(f"duplicate --publisher evidence: {evidence_id}")
        evidence_ids.add(evidence_id)
        result.append(verified)
    return result


def _source_audit_v4(args: argparse.Namespace) -> int:
    registry = _json_object(Path(args.registry))
    receipts = _load_publisher_receipts_v4(
        args.publisher,
        source_registry=registry,
        evaluated_at=args.evaluated_at,
    )
    result = audit_source_registry_v4(
        registry,
        _json_object(Path(args.storage_attestation)),
        receipts,
        evaluated_at=args.evaluated_at,
    )
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0 if result["all_verified"] else 2


def _source_count_v4(args: argparse.Namespace) -> int:
    registry = _json_object(Path(args.registry))
    receipts = _load_publisher_receipts_v4(
        args.publisher,
        source_registry=registry,
        evaluated_at=args.evaluated_at,
    )
    matches = [
        item for item in receipts if item.receipt["artifact_id"] == args.artifact_id
    ]
    if len(matches) != 1:
        raise Phase0Error("--artifact-id must have exactly one publisher receipt")
    result = build_structural_inventory_v4(
        registry=registry,
        storage_attestation=_json_object(Path(args.storage_attestation)),
        source_audit=_json_object(Path(args.source_audit)),
        publisher_receipt=matches[0],
        artifact_id=args.artifact_id,
        evaluated_at=args.evaluated_at,
    )
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0


def _quarantine_contribution_v4(args: argparse.Namespace) -> int:
    result = build_quarantine_contribution_v4(_json_object(Path(args.envelope)))
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0


def _quarantine_compile_v4(args: argparse.Namespace) -> int:
    evaluations = _json_object(Path(args.evaluations))
    validate_evaluation_registry_v4(evaluations)
    result = compile_quarantine_index_v4(
        _load_many(args.contribution),
        expected_dataset_ids=(item["dataset_id"] for item in evaluations["datasets"]),
        index_id=args.index_id,
    )
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0


def _quarantine_descriptor_v4(args: argparse.Namespace) -> int:
    record = _load_stdin_json() if args.input == "-" else load_json(Path(args.input))
    if not isinstance(record, dict):
        raise Phase0Error("v4 descriptor input must be a JSON object")
    expected = {
        "descriptor_id",
        "source_id",
        "artifact_id",
        "record_id",
        "raw_text",
        "normalized_text",
        "identifiers",
        "dependency_units",
        "lineage_complete",
        "derived_at",
    }
    if set(record) != expected:
        raise Phase0Error(
            "v4 descriptor input fields differ: "
            f"missing={sorted(expected - set(record))}, "
            f"extra={sorted(set(record) - expected)}"
        )
    raw_text = record["raw_text"]
    normalized_text = record["normalized_text"]
    if raw_text is not None and not isinstance(raw_text, str):
        raise Phase0Error("raw_text must be a string or null")
    if normalized_text is not None and not isinstance(normalized_text, str):
        raise Phase0Error("normalized_text must be a string or null")
    result = build_source_record_descriptor_v4(
        descriptor_id=record["descriptor_id"],
        source_id=record["source_id"],
        artifact_id=record["artifact_id"],
        record_id=record["record_id"],
        raw_content=raw_text.encode("utf-8") if raw_text is not None else None,
        text=normalized_text,
        identifiers=record["identifiers"],
        dependency_units=record["dependency_units"],
        lineage_complete=record["lineage_complete"],
        derived_at=record["derived_at"],
    )
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0


def _quarantine_check_v4(args: argparse.Namespace) -> int:
    result = match_quarantine_record_v4(
        _json_object(Path(args.descriptor)),
        _json_object(Path(args.index)),
        checked_at=args.checked_at,
    )
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0 if result["decision"] == "clear" else 2


def _load_materializations_v4_1(
    values: Sequence[str],
    *,
    evaluation_registry: dict[str, Any],
) -> list[VerifiedMaterialization]:
    result: list[VerifiedMaterialization] = []
    datasets: set[str] = set()
    for value in values:
        (
            manifest_text,
            receipt_text,
            archive_text,
            adapter_text,
            oracle_text,
            envelope_text,
        ) = _parts(value, "--materialization", 6)
        manifest = _json_object(Path(manifest_text))
        receipt = _json_object(Path(receipt_text))
        envelope = _json_object(Path(envelope_text))
        verified = verify_materialization_v4_1(
            manifest=manifest,
            receipt=receipt,
            evaluation_registry=evaluation_registry,
            archive_path=Path(archive_text),
            adapter_path=Path(adapter_text),
            oracle_path=Path(oracle_text),
            envelope=envelope,
        )
        dataset_id = verified.receipt["dataset_id"]
        if dataset_id in datasets:
            raise Phase0Error(f"duplicate --materialization dataset: {dataset_id}")
        datasets.add(dataset_id)
        result.append(verified)
    return result


def _evaluation_materialize_v4_1(args: argparse.Namespace) -> int:
    output_paths = [Path(args.manifest_output), Path(args.receipt_output)]
    if any(path.exists() or path.is_symlink() for path in output_paths):
        raise Phase0Error("refusing to overwrite materialization outputs")
    verified = materialize_evaluation_v4_1(
        evaluation_registry=_json_object(Path(args.evaluations)),
        dataset_id=args.dataset_id,
        archive_path=Path(args.archive),
        adapter_path=Path(args.adapter),
        oracle_path=Path(args.oracle),
        envelope=_json_object(Path(args.envelope)),
        inventory=_json_object(Path(args.inventory)),
        manifest_id=args.manifest_id,
        materialized_at=args.materialized_at,
    )
    _write_json_exclusive(Path(args.manifest_output), verified.manifest, mode=0o600)
    _write_json_exclusive(Path(args.receipt_output), verified.receipt)
    _emit(verified.receipt)
    return 0


def _seal_create_v4(args: argparse.Namespace) -> int:
    envelope = _load_stdin_json() if args.input == "-" else load_json(Path(args.input))
    if not isinstance(envelope, dict):
        raise Phase0Error("v4 seal input must be a JSON object")
    evaluations = _json_object(Path(args.evaluations))
    contribution = build_quarantine_contribution_v4(envelope)
    output_paths = [Path(args.output), Path(args.receipt), Path(args.contribution)]
    if any(path.exists() or path.is_symlink() for path in output_paths):
        raise Phase0Error("refusing to overwrite seal, receipt, or contribution output")
    fingerprint, ciphertext_sha256 = encrypt_canonical_bundle(
        envelope, Path(args.output), args.recipient
    )
    created_at = args.created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    receipt = make_seal_receipt_v4(
        evaluation_registry=evaluations,
        envelope=envelope,
        contribution=contribution,
        ciphertext_sha256=ciphertext_sha256,
        public_key_fingerprint=fingerprint,
        custodian=args.custodian,
        created_at=created_at,
    )
    _write_json_exclusive(Path(args.contribution), contribution)
    _write_json_exclusive(Path(args.receipt), receipt)
    _emit(receipt)
    return 0


def _seal_create_v4_1(args: argparse.Namespace) -> int:
    evaluations = _json_object(Path(args.evaluations))
    materializations = _load_materializations_v4_1(
        [args.materialization], evaluation_registry=evaluations
    )
    if len(materializations) != 1:
        raise Phase0Error("seal create-v4.1 requires exactly one materialization")
    materialization = materializations[0]
    assessment = _json_object(Path(args.licence_assessment))
    bundle = load_verified_bundle(Path(args.licence_bundle))
    dataset, contribution = validate_seal_authorization_v4_1(
        evaluation_registry=evaluations,
        materialization=materialization,
        assessment=assessment,
        verified_bundle=bundle,
        created_at=args.created_at,
    )
    pinned_fingerprint = dataset["custodian_signing_key_fingerprint"]
    observed_fingerprint = resolve_public_key_fingerprint(args.recipient)
    if observed_fingerprint != pinned_fingerprint:
        raise GateBlocked("seal recipient differs from the pinned custodian key")
    output_paths = [
        Path(args.output),
        Path(args.receipt),
        Path(args.contribution),
        Path(args.access_log),
    ]
    if any(path.exists() or path.is_symlink() for path in output_paths):
        raise Phase0Error(
            "refusing to overwrite seal, receipt, contribution, or access-log output"
        )
    fingerprint, ciphertext_sha256 = encrypt_canonical_bundle(
        materialization.envelope, Path(args.output), args.recipient
    )
    if fingerprint != pinned_fingerprint:
        raise GateBlocked(
            "encryption resolved a key other than the pinned custodian key"
        )
    receipt = make_seal_receipt_v4(
        evaluation_registry=evaluations,
        envelope=materialization.envelope,
        contribution=contribution,
        ciphertext_sha256=ciphertext_sha256,
        public_key_fingerprint=fingerprint,
        custodian=args.custodian,
        created_at=args.created_at,
    )
    _write_json_exclusive(Path(args.contribution), contribution, mode=0o600)
    _write_json_exclusive(Path(args.receipt), receipt, mode=0o600)
    append_access_event(
        log_path=Path(args.access_log),
        seal_id=receipt["seal_id"],
        action="seal_created",
        actor=args.custodian,
        details={"receipt_id": canonical_sha256(materialization.receipt)},
        at=args.created_at,
    )
    _emit(receipt)
    return 0


def _seal_anchor_payload_v4(args: argparse.Namespace) -> int:
    receipt = _json_object(Path(args.seal_receipt))
    validate_v4(receipt, "evaluation-evidence.schema.json")
    if receipt.get("record_kind") != "seal_receipt":
        raise Phase0Error("anchor payload requires a v4 seal receipt")
    events = read_access_events(Path(args.access_log))
    if any(event["seal_id"] != receipt["seal_id"] for event in events):
        raise Phase0Error("access log contains another seal_id")
    previous = None
    if args.previous_anchor:
        anchor = _json_object(Path(args.previous_anchor))
        validate_v4(anchor, "access-anchor.schema.json")
        previous = VerifiedAccessAnchor(
            anchor=anchor,
            sha256=canonical_sha256(anchor),
            signature_sha256="sha256:" + "0" * 64,
            public_key_sha256="sha256:" + "0" * 64,
            signing_key_fingerprint=anchor["signing_key_fingerprint"],
        )
    payload = make_access_anchor_payload_v4(
        seal_receipt=receipt,
        access_events=events,
        sequence=args.sequence,
        previous_anchor=previous,
        anchored_at=args.anchored_at,
        valid_until=args.valid_until,
        authority_id=args.authority_id,
        signing_key_fingerprint=args.signing_key_fingerprint,
    )
    _write_bytes_exclusive(Path(args.output), canonical_bytes(payload))
    _emit(payload)
    return 0


def _load_verified_seals_v4(
    values: Sequence[str],
    *,
    evaluation_registry: dict[str, Any],
    contributions: Sequence[dict[str, Any]],
) -> list[VerifiedSealReceipt]:
    contribution_by_dataset = {item["dataset_id"]: item for item in contributions}
    if len(contribution_by_dataset) != len(contributions):
        raise Phase0Error("duplicate contribution dataset")
    result: list[VerifiedSealReceipt] = []
    datasets: set[str] = set()
    for value in values:
        ciphertext_text, receipt_text = _parts(value, "--seal-v4", 2)
        receipt = _json_object(Path(receipt_text))
        dataset_id = receipt.get("dataset_id")
        if dataset_id in datasets:
            raise Phase0Error(f"duplicate --seal-v4 dataset: {dataset_id}")
        contribution = contribution_by_dataset.get(dataset_id)
        if contribution is None:
            raise Phase0Error(f"seal lacks contribution: {dataset_id}")
        result.append(
            verify_seal_ciphertext_v4(
                Path(ciphertext_text),
                receipt,
                evaluation_registry=evaluation_registry,
                contribution=contribution,
            )
        )
        datasets.add(dataset_id)
    return result


def _load_verified_anchor_chains_v4(
    values: Sequence[str],
    *,
    evaluation_registry: dict[str, Any],
    verified_seals: Sequence[VerifiedSealReceipt],
    evaluated_at: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, VerifiedAccessAnchor]]:
    seal_by_id = {item.receipt["seal_id"]: item for item in verified_seals}
    dataset_by_seal = {
        item["seal_id"]: item
        for item in evaluation_registry["datasets"]
        if item["seal_id"] is not None
    }
    previous: dict[str, VerifiedAccessAnchor] = {}
    full_events: dict[str, list[dict[str, Any]]] = {}
    for value in values:
        anchor_text, signature_text, key_text, log_text = _parts(
            value, "--anchor-v4", 4
        )
        anchor = _json_object(Path(anchor_text))
        seal_id = anchor["seal_id"]
        verified_seal = seal_by_id.get(seal_id)
        dataset = dataset_by_seal.get(seal_id)
        if verified_seal is None or dataset is None:
            raise Phase0Error(f"anchor uses an unverified seal: {seal_id}")
        expected_fingerprint = dataset["custodian_signing_key_fingerprint"]
        if expected_fingerprint is None:
            raise Phase0Error(f"anchor seal lacks a pinned custodian key: {seal_id}")
        events = read_access_events(Path(log_text))
        if len(events) < anchor["event_count"]:
            raise Phase0Error(f"anchor event_count exceeds its log: {seal_id}")
        prefix = events[: anchor["event_count"]]
        verified = verify_access_anchor_v4(
            anchor,
            signature=_read_bounded_regular_file(
                Path(signature_text),
                MAX_OPENPGP_EVIDENCE_BYTES,
                "detached access-anchor signature",
            ),
            public_key=_read_bounded_regular_file(
                Path(key_text),
                MAX_OPENPGP_EVIDENCE_BYTES,
                "custodian public key",
            ),
            expected_signing_key_fingerprint=expected_fingerprint,
            access_events=prefix,
            seal_receipt=verified_seal.receipt,
            evaluated_at=evaluated_at,
            previous_anchor=previous.get(seal_id),
        )
        previous[seal_id] = verified
        existing = full_events.get(seal_id)
        if existing is not None and existing != events:
            raise Phase0Error(f"anchor chain changed access log: {seal_id}")
        full_events[seal_id] = events
    for seal_id, anchor in previous.items():
        if anchor.anchor["event_count"] != len(full_events[seal_id]):
            raise Phase0Error(f"latest anchor does not cover the full log: {seal_id}")
    return full_events, previous


def _load_verified_oauth_authority_v4_2(
    value: str,
    *,
    policy: dict[str, Any],
) -> VerifiedOAuthAuthority:
    payload_text, signature_text, key_text = _parts(value, "--oauth-authority", 3)
    return verify_oauth_authority(
        _json_object(Path(payload_text)),
        signature=_read_bounded_regular_file(
            Path(signature_text),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "OAuth authority signature",
        ),
        public_key=_read_bounded_regular_file(
            Path(key_text),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "OAuth authority public key",
        ),
        policy=policy,
        approved_policy_sha256=APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
        signature_verifier=_verify_detached_signature_gpg,
    )


def _load_verified_acquisition_authorizations_v4_2(
    values: Sequence[str],
    *,
    policy: dict[str, Any],
    source_registry: dict[str, Any],
    oauth_authority: VerifiedOAuthAuthority,
    storage_attestation: dict[str, Any],
) -> list[VerifiedAcquisitionAuthorization]:
    result: list[VerifiedAcquisitionAuthorization] = []
    artifacts: set[str] = set()
    for value in values:
        payload_text, signature_text, key_text = _parts(
            value, "--acquisition-authorization", 3
        )
        verified = verify_acquisition_authorization(
            _json_object(Path(payload_text)),
            signature=_read_bounded_regular_file(
                Path(signature_text),
                MAX_OPENPGP_EVIDENCE_BYTES,
                "acquisition authorization signature",
            ),
            public_key=_read_bounded_regular_file(
                Path(key_text),
                MAX_OPENPGP_EVIDENCE_BYTES,
                "acquisition authorization public key",
            ),
            policy=policy,
            source_registry=source_registry,
            oauth_authority=oauth_authority,
            storage_attestation=storage_attestation,
            approved_policy_sha256=APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
            signature_verifier=_verify_detached_signature_gpg,
        )
        artifact_id = verified.receipt["artifact_id"]
        if artifact_id in artifacts:
            raise Phase0Error(
                f"duplicate --acquisition-authorization artifact: {artifact_id}"
            )
        result.append(verified)
        artifacts.add(artifact_id)
    return result


def _load_acquisition_evidence_v4_2(
    values: Sequence[str],
) -> list[AcquisitionEvidenceBundle]:
    result: list[AcquisitionEvidenceBundle] = []
    for value in values:
        (
            receipt_text,
            pre_source_audit_text,
            pre_proof_text,
            post_proof_text,
            gate_text,
        ) = _parts(value, "--acquisition-evidence", 5)
        result.append(
            AcquisitionEvidenceBundle(
                receipt=_json_object(Path(receipt_text)),
                pre_source_audit=_json_object(Path(pre_source_audit_text)),
                pre_access_proof=_json_object(Path(pre_proof_text)),
                post_access_proof=_json_object(Path(post_proof_text)),
                authorization_gate=_json_object(Path(gate_text)),
            )
        )
    return result


def _oauth_authority_payload_v4_2(args: argparse.Namespace) -> int:
    policy = _json_object(Path(args.policy))
    oauth_config = load_oauth_config_identity(Path(args.oauth_config))
    payload = make_oauth_authority_payload(
        policy=policy,
        approved_policy_sha256=APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
        oauth_config=oauth_config,
        authority_id=args.authority_id,
        provider_resource_id=args.provider_resource_id,
        root_resource_id=args.root_resource_id,
        marker_file_id=args.marker_file_id,
        marker_sha256=args.marker_sha256,
        approved_at=args.approved_at,
        valid_until=args.valid_until,
        approver_id=args.approver_id,
        signing_key_fingerprint=args.signing_key_fingerprint,
    )
    _write_bytes_exclusive(Path(args.output), canonical_bytes(payload))
    _emit(
        {
            "ok": True,
            "authority_id": payload["authority_id"],
            "payload_sha256": canonical_sha256(payload),
            "contains_credentials": False,
            "training_authorized": False,
        }
    )
    return 0


def _oauth_authority_verify_v4_2(args: argparse.Namespace) -> int:
    verified = verify_oauth_authority(
        _json_object(Path(args.payload)),
        signature=_read_bounded_regular_file(
            Path(args.signature),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "OAuth authority signature",
        ),
        public_key=_read_bounded_regular_file(
            Path(args.public_key),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "OAuth authority public key",
        ),
        policy=_json_object(Path(args.policy)),
        approved_policy_sha256=APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
        signature_verifier=_verify_detached_signature_gpg,
    )
    validate_oauth_authority_time(verified, evaluated_at=args.verified_at)
    _write_json_exclusive(Path(args.output), verified.receipt)
    _emit(verified.receipt)
    return 0


def _storage_marker_payload_v4_2(args: argparse.Namespace) -> int:
    marker = make_drive_identity_marker(
        marker_id=args.marker_id,
        provider_resource_id=args.provider_resource_id,
        root_resource_id=args.root_resource_id,
    )
    encoded = canonical_bytes(marker)
    _write_bytes_exclusive(Path(args.output), encoded)
    _emit(
        {
            "ok": True,
            "marker_id": marker["marker_id"],
            "marker_sha256": sha256_bytes(encoded),
            "contains_evaluation_content": False,
            "training_authorized": False,
        }
    )
    return 0


def _storage_observe_drive_v4_2(args: argparse.Namespace) -> int:
    proof_output = Path(args.proof_output)
    _refuse_output(proof_output)
    observed_at = _utc_now_text()
    policy = _json_object(Path(args.policy))
    authority = _load_verified_oauth_authority_v4_2(
        args.oauth_authority,
        policy=policy,
    )
    proof = observe_drive_access_from_adc(
        adc_path=Path(args.adc_file),
        authority=authority,
        observed_at=observed_at,
    )
    _write_json_exclusive(proof_output, proof)
    _emit(
        {
            "ok": True,
            "observed_at": observed_at,
            "proof_sha256": canonical_sha256(proof),
            "same_resource_mechanically_proven": True,
            "training_authorized": False,
        }
    )
    return 0


def _registry_evaluations_finalize_v4_1(args: argparse.Namespace) -> int:
    pinned = _json_object(Path(args.evaluations))
    materializations = _load_materializations_v4_1(
        args.materialization, evaluation_registry=pinned
    )
    assessments, bundles = _load_licence_assessments_v1(args.licence_assessment)
    contributions = [
        build_quarantine_contribution_v4(item.envelope) for item in materializations
    ]
    seals = _load_verified_seals_v4(
        args.seal_v4,
        evaluation_registry=pinned,
        contributions=contributions,
    )
    access_events, anchors = _load_verified_anchor_chains_v4(
        args.anchor_v4,
        evaluation_registry=pinned,
        verified_seals=seals,
        evaluated_at=args.generated_at,
    )
    result = finalize_evaluations_v4_1(
        pinned_registry=pinned,
        materializations=materializations,
        licence_assessments=assessments,
        verified_bundles=bundles,
        verified_seals=seals,
        access_events=access_events,
        verified_access_anchors=anchors,
        registry_id=args.registry_id,
        generated_at=args.generated_at,
    )
    _write_json_exclusive(Path(args.output), result)
    _emit(
        {
            "ok": True,
            "registry_id": result["registry_id"],
            "registry_sha256": canonical_sha256(result),
            "training_authorized": False,
        }
    )
    return 0


def _evaluate_from_v4_args(args: argparse.Namespace) -> dict[str, Any]:
    sources = _json_object(Path(args.sources))
    evaluations = _json_object(Path(args.evaluations))
    contributions = _load_many(args.contribution)
    publisher_receipts = _load_publisher_receipts_v4(
        args.publisher,
        source_registry=sources,
        evaluated_at=args.evaluated_at,
    )
    assessments, bundles = _load_licence_assessments_v1(args.licence_assessment)
    verified_seals = _load_verified_seals_v4(
        args.seal_v4,
        evaluation_registry=evaluations,
        contributions=contributions,
    )
    access_events, anchors = _load_verified_anchor_chains_v4(
        args.anchor_v4,
        evaluation_registry=evaluations,
        verified_seals=verified_seals,
        evaluated_at=args.evaluated_at,
    )
    return evaluate_gate_v4(
        evaluated_at=args.evaluated_at,
        source_registry=sources,
        source_registry_predecessor=_json_object(Path(args.source_predecessor)),
        evaluation_registry=evaluations,
        evaluation_registry_predecessor=_json_object(Path(args.evaluation_predecessor)),
        drive_observation=(
            _json_object(Path(args.drive_observation))
            if args.drive_observation
            else None
        ),
        storage_attestation=(
            _json_object(Path(args.storage_attestation))
            if args.storage_attestation
            else None
        ),
        publisher_receipts=publisher_receipts,
        source_audit=(
            _json_object(Path(args.source_audit)) if args.source_audit else None
        ),
        licence_assessments=assessments,
        verified_bundles=bundles,
        quarantine_contributions=contributions,
        quarantine_index=(
            _json_object(Path(args.quarantine)) if args.quarantine else None
        ),
        verified_seals=verified_seals,
        evaluation_access_events=access_events,
        verified_access_anchors=anchors,
        structural_inventories=_load_many(args.inventory),
        admission_receipts=_load_many(args.admission),
    )


def _gate_v4(args: argparse.Namespace) -> int:
    result = _evaluate_from_v4_args(args)
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0 if result["foundation_transform_ready"] else 2


def _load_v4_1_graph_args(
    args: argparse.Namespace, *, evaluated_at: str | None = None
) -> dict[str, Any]:
    effective_time = evaluated_at or args.evaluated_at
    source_registries = [_json_object(Path(path)) for path in args.source_registry]
    evaluation_registries = [
        _json_object(Path(path)) for path in args.evaluation_registry
    ]
    source_tip = source_registries[-1]
    pinned = evaluation_registries[-2] if len(evaluation_registries) >= 3 else None
    contributions = _load_many(args.contribution)
    publishers = _load_publisher_receipts_v4(
        args.publisher,
        source_registry=source_tip,
        evaluated_at=effective_time,
    )
    assessments, bundles = _load_licence_assessments_v1(args.licence_assessment)
    if args.materialization and pinned is None:
        raise Phase0Error(
            "--materialization requires a root-to-pinned-to-final evaluation lineage"
        )
    materializations = (
        _load_materializations_v4_1(args.materialization, evaluation_registry=pinned)
        if pinned is not None
        else []
    )
    if args.seal_v4 and pinned is None:
        raise Phase0Error("--seal-v4 requires a penultimate pinned registry")
    seals = (
        _load_verified_seals_v4(
            args.seal_v4,
            evaluation_registry=pinned,
            contributions=contributions,
        )
        if pinned is not None
        else []
    )
    access_events, anchors = (
        _load_verified_anchor_chains_v4(
            args.anchor_v4,
            evaluation_registry=pinned,
            verified_seals=seals,
            evaluated_at=effective_time,
        )
        if pinned is not None
        else ({}, {})
    )
    return {
        "evaluated_at": effective_time,
        "source_registries": source_registries,
        "evaluation_registries": evaluation_registries,
        "drive_observation": (
            _json_object(Path(args.drive_observation))
            if args.drive_observation
            else None
        ),
        "storage_attestation": (
            _json_object(Path(args.storage_attestation))
            if args.storage_attestation
            else None
        ),
        "publisher_receipts": publishers,
        "source_audit": (
            _json_object(Path(args.source_audit)) if args.source_audit else None
        ),
        "licence_assessments": assessments,
        "verified_bundles": bundles,
        "materializations": materializations,
        "quarantine_contributions": contributions,
        "quarantine_index": (
            _json_object(Path(args.quarantine)) if args.quarantine else None
        ),
        "verified_seals": seals,
        "evaluation_access_events": access_events,
        "verified_access_anchors": anchors,
        "structural_inventories": _load_many(args.inventory),
        "admission_receipts": _load_many(args.admission),
    }


def _evaluate_from_v4_1_args(args: argparse.Namespace) -> dict[str, Any]:
    return evaluate_gate_v4_1(**_load_v4_1_graph_args(args))


def _gate_v4_1(args: argparse.Namespace) -> int:
    result = _evaluate_from_v4_1_args(args)
    if args.output:
        _write_json_exclusive(Path(args.output), result)
    _emit(result)
    return 0 if result["foundation_transform_ready"] else 2


def _load_v4_2_graph_args(
    args: argparse.Namespace,
    *,
    evaluated_at: str | None = None,
    drive_access_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_time = evaluated_at or args.evaluated_at
    graph = _load_v4_1_graph_args(args, evaluated_at=effective_time)
    policy = (
        _json_object(Path(args.authority_policy)) if args.authority_policy else None
    )
    authority = None
    if args.oauth_authority:
        if policy is None:
            raise Phase0Error("--oauth-authority requires --authority-policy")
        authority = _load_verified_oauth_authority_v4_2(
            args.oauth_authority,
            policy=policy,
        )
    authorizations: list[VerifiedAcquisitionAuthorization] = []
    if args.acquisition_authorization:
        if policy is None or authority is None or graph["storage_attestation"] is None:
            raise Phase0Error(
                "--acquisition-authorization requires policy, OAuth authority, "
                "and storage attestation"
            )
        authorizations = _load_verified_acquisition_authorizations_v4_2(
            args.acquisition_authorization,
            policy=policy,
            source_registry=graph["source_registries"][-1],
            oauth_authority=authority,
            storage_attestation=graph["storage_attestation"],
        )
    graph.update(
        {
            "authority_policy": policy,
            "approved_policy_sha256": APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
            "oauth_authority": authority,
            "drive_access_proof": (
                drive_access_proof
                if drive_access_proof is not None
                else (
                    _json_object(Path(args.drive_access_proof))
                    if args.drive_access_proof
                    else None
                )
            ),
            "acquisition_authorizations": authorizations,
            "acquisition_evidence": _load_acquisition_evidence_v4_2(
                args.acquisition_evidence
            ),
        }
    )
    return graph


def _evaluate_from_v4_2_args(
    args: argparse.Namespace,
    *,
    evaluated_at: str | None = None,
    drive_access_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return evaluate_gate_v4_2(
        **_load_v4_2_graph_args(
            args,
            evaluated_at=evaluated_at,
            drive_access_proof=drive_access_proof,
        )
    )


def _gate_v4_2(args: argparse.Namespace) -> int:
    result = _evaluate_from_v4_2_args(args)
    if args.output:
        _write_json_exclusive(Path(args.output), result)
    _emit(result)
    return 0 if result["foundation_transform_ready"] else 2


def _source_assess_admission_v4(args: argparse.Namespace) -> int:
    sources = _json_object(Path(args.registry))
    source = next(
        (item for item in sources["sources"] if item["source_id"] == args.source_id),
        None,
    )
    if source is None:
        raise Phase0Error(f"unknown source_id: {args.source_id}")
    publisher_receipts = _load_publisher_receipts_v4(
        args.publisher,
        source_registry=sources,
        evaluated_at=args.assessed_at,
    )
    artifact_ids = {item["artifact_id"] for item in source["artifacts"]}
    publisher_receipts = [
        item
        for item in publisher_receipts
        if item.receipt["artifact_id"] in artifact_ids
    ]
    assessment = _json_object(Path(args.licence_assessment))
    bundle = load_verified_bundle(Path(args.licence_bundle))
    result = assess_admission_v4(
        source_id=args.source_id,
        source_registry=sources,
        evaluation_registry=_json_object(Path(args.evaluations)),
        storage_attestation=_json_object(Path(args.storage_attestation)),
        source_audit=_json_object(Path(args.source_audit)),
        publisher_receipts=publisher_receipts,
        assessment=assessment,
        verified_bundle=bundle,
        inventories=_load_many(args.inventory),
        quarantine_index=_json_object(Path(args.quarantine)),
        assessor=args.assessor,
        assessed_at=args.assessed_at,
    )
    if args.output:
        output = Path(args.output)
        _refuse_output(output)
        _write_json_exclusive(output, result)
    _emit(result)
    return 0


def _source_authorization_payload_v4_2(args: argparse.Namespace) -> int:
    gate = _evaluate_from_v4_2_args(args)
    if not gate["foundation_acquisition_ready"]:
        codes = [item["code"] for item in gate["blockers"]]
        raise GateBlocked(
            "Phase 0 v4.2 acquisition prerequisites are blocked: " + ", ".join(codes)
        )
    graph = _load_v4_2_graph_args(args)
    policy = graph["authority_policy"]
    authority = graph["oauth_authority"]
    attestation = graph["storage_attestation"]
    if policy is None or authority is None or attestation is None:
        raise GateBlocked("v4.2 acquisition authority prerequisites are unavailable")
    payload = make_acquisition_authorization_payload(
        policy=policy,
        approved_policy_sha256=APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
        source_registry=graph["source_registries"][-1],
        artifact_id=args.artifact_id,
        oauth_authority=authority,
        storage_attestation=attestation,
        authorization_id=args.authorization_id,
        byte_ceiling=args.byte_ceiling,
        authorized_at=args.authorized_at,
        valid_until=args.valid_until,
        authorizer_id=args.authorizer_id,
        signing_key_fingerprint=args.signing_key_fingerprint,
    )
    _write_bytes_exclusive(Path(args.authorization_output), canonical_bytes(payload))
    _emit(
        {
            "ok": True,
            "authorization_id": payload["authorization_id"],
            "artifact_id": payload["artifact_id"],
            "payload_sha256": canonical_sha256(payload),
            "training_authorized": False,
        }
    )
    return 0


def _source_authorization_verify_v4_2(args: argparse.Namespace) -> int:
    policy = _json_object(Path(args.policy))
    source_lineage = validate_registry_lineage_v4_1(
        [_json_object(Path(path)) for path in args.source_registry]
    )
    attestation = _json_object(Path(args.storage_attestation))
    authority = _load_verified_oauth_authority_v4_2(
        args.oauth_authority,
        policy=policy,
    )
    validate_oauth_authority_time(authority, evaluated_at=args.verified_at)
    verified = verify_acquisition_authorization(
        _json_object(Path(args.payload)),
        signature=_read_bounded_regular_file(
            Path(args.signature),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "acquisition authorization signature",
        ),
        public_key=_read_bounded_regular_file(
            Path(args.public_key),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "acquisition authorization public key",
        ),
        policy=policy,
        source_registry=source_lineage.tip,
        oauth_authority=authority,
        storage_attestation=attestation,
        approved_policy_sha256=APPROVED_OAUTH_AUTHORITY_POLICY_SHA256,
        signature_verifier=_verify_detached_signature_gpg,
    )
    validate_acquisition_authorization_time(verified, evaluated_at=args.verified_at)
    _write_json_exclusive(Path(args.output), verified.receipt)
    _emit(verified.receipt)
    return 0


def _source_acquire_v4_2(args: argparse.Namespace) -> int:
    outputs = [
        Path(args.receipt_output),
        Path(args.pre_source_audit_output),
        Path(args.pre_proof_output),
        Path(args.post_proof_output),
        Path(args.authorization_gate_output),
    ]
    for output in outputs:
        _refuse_output(output)

    initial_time = _utc_now_text()
    graph = _load_v4_2_graph_args(args, evaluated_at=initial_time)
    source_lineage = validate_registry_lineage_v4_1(graph["source_registries"])
    registry = source_lineage.tip
    attestation = graph["storage_attestation"]
    authority = graph["oauth_authority"]
    pre_source_audit = graph["source_audit"]
    if attestation is None or authority is None or pre_source_audit is None:
        raise GateBlocked(
            "v4.2 storage, OAuth authority, and pre-acquisition audit are required"
        )
    matches = [
        artifact
        for source in registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == args.artifact_id
    ]
    if len(matches) != 1:
        raise Phase0Error("--artifact-id must resolve exactly once")
    artifact = matches[0]
    if artifact["availability"] != "acquisition_target":
        raise GateBlocked("source acquire-v4.2 accepts only an acquisition target")
    publisher_matches = [
        item
        for item in graph["publisher_receipts"]
        if item.receipt["artifact_id"] == args.artifact_id
    ]
    if len(publisher_matches) != 1:
        raise GateBlocked("acquisition target lacks exact publisher evidence")
    publisher = publisher_matches[0].receipt
    authorization_matches = [
        item
        for item in graph["acquisition_authorizations"]
        if item.receipt["artifact_id"] == args.artifact_id
    ]
    if len(authorization_matches) != 1:
        raise GateBlocked("acquisition target lacks one signed authorization")
    acquisition_authorization = authorization_matches[0]
    if acquisition_authorization.receipt["byte_ceiling"] < artifact["expected_bytes"]:
        raise GateBlocked("signed acquisition byte ceiling is insufficient")
    if Path(attestation["observed_root"]) != Path(
        "/content/drive/Shareddrives/Data/graph-memory-data-lake"
    ):
        raise GateBlocked("storage attestation root differs from the frozen lake root")

    identity_results: dict[str, dict[str, Any]] = {}

    def identity_check(stage: str, _root_fd: int) -> dict[str, Any]:
        checked_at = _utc_now_text()
        proof = observe_drive_access_from_adc(
            adc_path=Path(args.adc_file),
            authority=authority,
            observed_at=checked_at,
            root_fd=_root_fd,
        )
        authorization_graph = _load_v4_2_graph_args(
            args, evaluated_at=checked_at, drive_access_proof=proof
        )
        authorization_graph["source_audit"] = pre_source_audit
        authorization_graph["structural_inventories"] = []
        authorization_graph["admission_receipts"] = []
        authorization_graph["acquisition_evidence"] = []
        gate = evaluate_gate_v4_2(**authorization_graph)
        if not gate["foundation_acquisition_authorized"]:
            codes = [item["code"] for item in gate["blockers"]]
            raise GateBlocked(
                f"v4.2 acquisition {stage} gate is blocked: " + ", ".join(codes)
            )
        if stage == "before_promote":
            before = identity_results.get("before_download")
            if before is None:
                raise GateBlocked("pre-download identity evidence is unavailable")
            for field in (
                "mount_identity_sha256",
                "principal_permission_id_sha256",
                "provider_resource_id",
                "root_resource_id",
                "marker_file_id",
                "marker_sha256",
            ):
                if before["proof"][field] != proof[field]:
                    raise GateBlocked(
                        f"Drive identity changed during acquisition: {field}"
                    )
        result = {"proof": proof, "gate": gate}
        identity_results[stage] = result
        return result

    download = download_resumable_at(
        url=artifact["source_url"],
        root=Path(attestation["observed_root"]),
        filename=artifact["filename"],
        expected_bytes=artifact["expected_bytes"],
        expected_checksums={publisher["algorithm"]: publisher["value"]},
        minimum_free_bytes=args.minimum_free_bytes,
        resume_authorization_sha256=acquisition_authorization.sha256,
        identity_check=identity_check,
    )
    pre = identity_results["before_download"]
    post = identity_results["before_promote"]
    receipt = {
        "schema_version": "4.2.0",
        "record_kind": "source_acquisition_receipt",
        "artifact_id": artifact["artifact_id"],
        "source_registry_sha256": canonical_sha256(registry),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "authorization_gate_sha256": canonical_sha256(pre["gate"]),
        "acquisition_authorization_receipt_sha256": acquisition_authorization.sha256,
        "oauth_authority_receipt_sha256": authority.sha256,
        "storage_attestation_sha256": canonical_sha256(attestation),
        "pre_source_audit_sha256": canonical_sha256(pre_source_audit),
        "pre_access_proof_sha256": canonical_sha256(pre["proof"]),
        "post_access_proof_sha256": canonical_sha256(post["proof"]),
        "provider_resource_id": attestation["provider_resource_id"],
        "root_resource_id": attestation["root_resource_id"],
        "destination_filename": artifact["filename"],
        "bytes": download["bytes"],
        "checksums": download["checksums"],
        "started_at": pre["proof"]["observed_at"],
        "completed_at": post["proof"]["observed_at"],
        "complete": True,
        "training_authorized": False,
    }
    validate_v4_2(receipt, "execution-evidence.schema.json")
    _write_json_exclusive(Path(args.pre_source_audit_output), pre_source_audit)
    _write_json_exclusive(Path(args.pre_proof_output), pre["proof"])
    _write_json_exclusive(Path(args.post_proof_output), post["proof"])
    _write_json_exclusive(Path(args.authorization_gate_output), pre["gate"])
    _write_json_exclusive(Path(args.receipt_output), receipt)
    _emit(receipt)
    return 0


def _source_acquire_v4(args: argparse.Namespace) -> int:
    authorization = _evaluate_from_v4_args(args)
    if not authorization["foundation_acquisition_authorized"]:
        codes = [item["code"] for item in authorization["blockers"]]
        raise GateBlocked(
            "Phase 0 v4 foundation acquisition gate is blocked: " + ", ".join(codes)
        )
    registry = _json_object(Path(args.sources))
    attestation = _json_object(Path(args.storage_attestation))
    matches = [
        (source, artifact)
        for source in registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == args.artifact_id
    ]
    if len(matches) != 1:
        raise Phase0Error("--artifact-id must resolve exactly once")
    _, artifact = matches[0]
    if artifact["availability"] != "acquisition_target":
        raise GateBlocked("source acquire-v4 accepts only an acquisition target")
    publisher_receipts = _load_publisher_receipts_v4(
        args.publisher,
        source_registry=registry,
        evaluated_at=args.evaluated_at,
    )
    publisher_matches = [
        item
        for item in publisher_receipts
        if item.receipt["artifact_id"] == args.artifact_id
    ]
    if len(publisher_matches) != 1:
        raise GateBlocked("acquisition target lacks exact publisher evidence")
    publisher = publisher_matches[0].receipt
    destination = Path(attestation["observed_root"]) / artifact["filename"]
    result = download_resumable(
        url=artifact["source_url"],
        destination=destination,
        expected_bytes=artifact["expected_bytes"],
        expected_checksums={publisher["algorithm"]: publisher["value"]},
        minimum_free_bytes=args.minimum_free_bytes,
    )
    result["artifact_id"] = artifact["artifact_id"]
    result["authorization_gate_sha256"] = canonical_sha256(authorization)
    _emit(result)
    return 0


def _source_acquire_v4_1(args: argparse.Namespace) -> int:
    authorization = _evaluate_from_v4_1_args(args)
    if not authorization["foundation_acquisition_authorized"]:
        codes = [item["code"] for item in authorization["blockers"]]
        raise GateBlocked(
            "Phase 0 v4.1 foundation acquisition gate is blocked: " + ", ".join(codes)
        )
    source_lineage = validate_registry_lineage_v4_1(
        [_json_object(Path(path)) for path in args.source_registry]
    )
    source_lineage_bindings = [
        item["sha256"]
        for item in authorization["evidence_bindings"]
        if item["kind"] == "registry_lineage" and item["subject_id"] == "sources"
    ]
    if source_lineage_bindings != [source_lineage.sha256]:
        raise GateBlocked("source registry lineage changed after gate evaluation")
    registry = source_lineage.tip
    attestation = _json_object(Path(args.storage_attestation))
    attestation_bindings = [
        item["sha256"]
        for item in authorization["evidence_bindings"]
        if item["kind"] == "storage_attestation"
        and item["subject_id"] == attestation["locator_id"]
    ]
    if attestation_bindings != [canonical_sha256(attestation)]:
        raise GateBlocked("storage attestation changed after gate evaluation")
    matches = [
        artifact
        for source in registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == args.artifact_id
    ]
    if len(matches) != 1:
        raise Phase0Error("--artifact-id must resolve exactly once")
    artifact = matches[0]
    if artifact["availability"] != "acquisition_target":
        raise GateBlocked("source acquire-v4.1 accepts only an acquisition target")
    publishers = _load_publisher_receipts_v4(
        args.publisher,
        source_registry=registry,
        evaluated_at=args.evaluated_at,
    )
    publisher_bindings = {
        item["subject_id"]: item["sha256"]
        for item in authorization["evidence_bindings"]
        if item["kind"] == "publisher_receipt"
    }
    if publisher_bindings != {
        item.receipt["artifact_id"]: item.sha256 for item in publishers
    }:
        raise GateBlocked("publisher evidence changed after gate evaluation")
    publisher_matches = [
        item for item in publishers if item.receipt["artifact_id"] == args.artifact_id
    ]
    if len(publisher_matches) != 1:
        raise GateBlocked("acquisition target lacks exact publisher evidence")
    publisher = publisher_matches[0].receipt
    destination = Path(attestation["observed_root"]) / artifact["filename"]
    result = download_resumable(
        url=artifact["source_url"],
        destination=destination,
        expected_bytes=artifact["expected_bytes"],
        expected_checksums={publisher["algorithm"]: publisher["value"]},
        minimum_free_bytes=args.minimum_free_bytes,
    )
    result["artifact_id"] = artifact["artifact_id"]
    result["authorization_gate_sha256"] = canonical_sha256(authorization)
    _emit(result)
    return 0


def _source_acquire_authorized(
    args: argparse.Namespace, authorization: dict[str, Any]
) -> int:
    if not authorization["foundation_acquisition_authorized"]:
        raise GateBlocked(
            "foundation acquisition gate is blocked: "
            + ", ".join(authorization["blockers"])
        )
    registry = load_json(Path(args.sources))
    attestation = load_json(Path(args.storage_attestation))
    source, artifact = next(
        (
            (source, artifact)
            for source in registry["sources"]
            for artifact in source["artifacts"]
            if artifact["artifact_id"] == args.artifact_id
        ),
        (None, None),
    )
    if source is None or artifact is None:
        raise Phase0Error(f"unknown artifact_id: {args.artifact_id}")
    if artifact["availability"] != "acquisition_target":
        raise GateBlocked("source acquire only accepts a registered acquisition target")
    checksums = {
        item["algorithm"]: item["value"]
        for item in artifact["checksums"]
        if item["origin"] == "publisher" and item["verified"]
    }
    if not ({"sha1", "sha256"} & checksums.keys()):
        raise GateBlocked("acquisition target lacks a verified publisher SHA checksum")
    destination = Path(attestation["observed_root"]) / artifact["filename"]
    result = download_resumable(
        url=artifact["source_url"],
        destination=destination,
        expected_bytes=artifact["expected_bytes"],
        expected_checksums=checksums,
        minimum_free_bytes=args.minimum_free_bytes,
    )
    result["artifact_id"] = artifact["artifact_id"]
    result["authorization_gate_sha256"] = canonical_sha256(authorization)
    _emit(result)
    return 0


def _source_acquire_v2(args: argparse.Namespace) -> int:
    return _source_acquire_authorized(args, _evaluate_from_v2_args(args))


def _source_acquire_v3(args: argparse.Namespace) -> int:
    return _source_acquire_authorized(args, _evaluate_from_v3_args(args))


def _add_v2_gate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sources", required=True)
    parser.add_argument("--evaluations", required=True)
    parser.add_argument("--storage-attestation")
    parser.add_argument("--source-audit")
    parser.add_argument(
        "--licence-review",
        action="append",
        default=[],
        metavar="REVIEW=TERMS",
    )
    parser.add_argument(
        "--seal",
        action="append",
        default=[],
        metavar="CIPHERTEXT=RECEIPT",
    )
    parser.add_argument(
        "--access-log",
        action="append",
        default=[],
        metavar="LOG=EXPECTED_ANCHORED_HEAD",
    )
    parser.add_argument("--contribution", action="append", default=[])
    parser.add_argument("--quarantine")
    parser.add_argument("--inventory", action="append", default=[])
    parser.add_argument("--admission", action="append", default=[])
    parser.add_argument("--evaluated-at", required=True)


def _add_v3_gate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sources", required=True)
    parser.add_argument("--evaluations", required=True)
    parser.add_argument("--storage-attestation")
    parser.add_argument("--source-audit")
    parser.add_argument(
        "--licence-assessment",
        action="append",
        default=[],
        metavar="ASSESSMENT=BUNDLE",
    )
    parser.add_argument(
        "--seal",
        action="append",
        default=[],
        metavar="CIPHERTEXT=RECEIPT",
    )
    parser.add_argument(
        "--access-log",
        action="append",
        default=[],
        metavar="LOG=EXPECTED_ANCHORED_HEAD",
    )
    parser.add_argument("--contribution", action="append", default=[])
    parser.add_argument("--quarantine")
    parser.add_argument("--inventory", action="append", default=[])
    parser.add_argument("--admission", action="append", default=[])
    parser.add_argument("--evaluated-at", required=True)


def _add_v4_gate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sources", required=True)
    parser.add_argument("--source-predecessor", required=True)
    parser.add_argument("--evaluations", required=True)
    parser.add_argument("--evaluation-predecessor", required=True)
    parser.add_argument("--drive-observation")
    parser.add_argument("--storage-attestation")
    parser.add_argument(
        "--publisher",
        action="append",
        default=[],
        metavar="STATEMENT=RECEIPT",
    )
    parser.add_argument("--source-audit")
    parser.add_argument(
        "--licence-assessment",
        action="append",
        default=[],
        metavar="ASSESSMENT=BUNDLE",
    )
    parser.add_argument(
        "--seal-v4",
        action="append",
        default=[],
        metavar="CIPHERTEXT=RECEIPT",
    )
    parser.add_argument(
        "--anchor-v4",
        action="append",
        default=[],
        metavar="ANCHOR=SIGNATURE=PUBLIC_KEY=ACCESS_LOG",
    )
    parser.add_argument("--contribution", action="append", default=[])
    parser.add_argument("--quarantine")
    parser.add_argument("--inventory", action="append", default=[])
    parser.add_argument("--admission", action="append", default=[])
    parser.add_argument("--evaluated-at", required=True)


def _add_v4_1_gate_arguments(
    parser: argparse.ArgumentParser, *, include_evaluated_at: bool = True
) -> None:
    parser.add_argument(
        "--source-registry", action="append", required=True, metavar="PATH"
    )
    parser.add_argument(
        "--evaluation-registry", action="append", required=True, metavar="PATH"
    )
    parser.add_argument("--drive-observation")
    parser.add_argument("--storage-attestation")
    parser.add_argument(
        "--publisher",
        action="append",
        default=[],
        metavar="STATEMENT=RECEIPT",
    )
    parser.add_argument("--source-audit")
    parser.add_argument(
        "--licence-assessment",
        action="append",
        default=[],
        metavar="ASSESSMENT=BUNDLE",
    )
    parser.add_argument(
        "--materialization",
        action="append",
        default=[],
        metavar="MANIFEST=RECEIPT=ARCHIVE=ADAPTER=ORACLE=ENVELOPE",
    )
    parser.add_argument(
        "--seal-v4",
        action="append",
        default=[],
        metavar="CIPHERTEXT=RECEIPT",
    )
    parser.add_argument(
        "--anchor-v4",
        action="append",
        default=[],
        metavar="ANCHOR=SIGNATURE=PUBLIC_KEY=ACCESS_LOG",
    )
    parser.add_argument("--contribution", action="append", default=[])
    parser.add_argument("--quarantine")
    parser.add_argument("--inventory", action="append", default=[])
    parser.add_argument("--admission", action="append", default=[])
    if include_evaluated_at:
        parser.add_argument("--evaluated-at", required=True)


def _add_v4_2_gate_arguments(
    parser: argparse.ArgumentParser, *, include_evaluated_at: bool = True
) -> None:
    _add_v4_1_gate_arguments(parser, include_evaluated_at=include_evaluated_at)
    parser.add_argument("--authority-policy")
    parser.add_argument(
        "--oauth-authority",
        metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY",
    )
    parser.add_argument("--drive-access-proof")
    parser.add_argument(
        "--acquisition-authorization",
        action="append",
        default=[],
        metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY",
    )
    parser.add_argument(
        "--acquisition-evidence",
        action="append",
        default=[],
        metavar=("RECEIPT=PRE_SOURCE_AUDIT=PRE_PROOF=POST_PROOF=AUTHORIZATION_GATE"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hf-phase0")
    commands = parser.add_subparsers(dest="command", required=True)

    registry = commands.add_parser("registry")
    registry_commands = registry.add_subparsers(dest="registry_command", required=True)
    validate = registry_commands.add_parser("validate")
    validate.add_argument("--schema-root")
    validate.add_argument("--instance", action="append", default=[], metavar="PATH")
    validate.set_defaults(handler=_registry_validate_v2)
    validate_v1 = registry_commands.add_parser("validate-v1")
    validate_v1.add_argument("--schema-root")
    validate_v1.add_argument(
        "--instance", action="append", default=[], metavar="PATH=SCHEMA"
    )
    validate_v1.set_defaults(handler=_registry_validate_v1)
    validate_v4_command = registry_commands.add_parser("validate-v4")
    validate_v4_command.add_argument("--schema-root")
    validate_v4_command.add_argument("--source-predecessor")
    validate_v4_command.add_argument("--evaluation-predecessor")
    validate_v4_command.add_argument(
        "--instance", action="append", default=[], metavar="PATH"
    )
    validate_v4_command.set_defaults(handler=_registry_validate_v4)
    validate_v4_1_command = registry_commands.add_parser("validate-v4.1")
    validate_v4_1_command.add_argument("--schema-root")
    validate_v4_1_command.add_argument(
        "--instance", action="append", default=[], metavar="PATH"
    )
    validate_v4_1_command.set_defaults(handler=_registry_validate_v4_1)
    validate_v4_2_command = registry_commands.add_parser("validate-v4.2")
    validate_v4_2_command.add_argument("--schema-root")
    validate_v4_2_command.add_argument(
        "--instance", action="append", default=[], metavar="PATH"
    )
    validate_v4_2_command.set_defaults(handler=_registry_validate_v4_2)
    lineage_v4_1 = registry_commands.add_parser("lineage-v4.1")
    lineage_v4_1.add_argument(
        "--registry", action="append", required=True, metavar="PATH"
    )
    lineage_v4_1.add_argument("--output")
    lineage_v4_1.set_defaults(handler=_registry_lineage_v4_1)
    publisher_pin_v4_1 = registry_commands.add_parser("publisher-pin-v4.1")
    publisher_pin_v4_1.add_argument("--registry", required=True)
    publisher_pin_v4_1.add_argument("--registry-id", required=True)
    publisher_pin_v4_1.add_argument("--generated-at", required=True)
    publisher_pin_v4_1.add_argument("--output", required=True)
    publisher_pin_v4_1.set_defaults(handler=_registry_publisher_pin_v4_1)
    finalize_v4_1 = registry_commands.add_parser("evaluations-finalize-v4.1")
    finalize_v4_1.add_argument("--evaluations", required=True)
    finalize_v4_1.add_argument(
        "--materialization",
        action="append",
        default=[],
        metavar="MANIFEST=RECEIPT=ARCHIVE=ADAPTER=ORACLE=ENVELOPE",
    )
    finalize_v4_1.add_argument(
        "--licence-assessment",
        action="append",
        default=[],
        metavar="ASSESSMENT=BUNDLE",
    )
    finalize_v4_1.add_argument(
        "--seal-v4", action="append", default=[], metavar="CIPHERTEXT=RECEIPT"
    )
    finalize_v4_1.add_argument(
        "--anchor-v4",
        action="append",
        default=[],
        metavar="ANCHOR=SIGNATURE=PUBLIC_KEY=ACCESS_LOG",
    )
    finalize_v4_1.add_argument("--registry-id", required=True)
    finalize_v4_1.add_argument("--generated-at", required=True)
    finalize_v4_1.add_argument("--output", required=True)
    finalize_v4_1.set_defaults(handler=_registry_evaluations_finalize_v4_1)

    oauth = commands.add_parser("oauth")
    oauth_commands = oauth.add_subparsers(dest="oauth_command", required=True)
    authority_payload_v4_2 = oauth_commands.add_parser("authority-payload-v4.2")
    authority_payload_v4_2.add_argument("--policy", required=True)
    authority_payload_v4_2.add_argument("--oauth-config", required=True)
    authority_payload_v4_2.add_argument("--authority-id", required=True)
    authority_payload_v4_2.add_argument("--provider-resource-id", required=True)
    authority_payload_v4_2.add_argument("--root-resource-id", required=True)
    authority_payload_v4_2.add_argument("--marker-file-id", required=True)
    authority_payload_v4_2.add_argument("--marker-sha256", required=True)
    authority_payload_v4_2.add_argument("--approved-at", required=True)
    authority_payload_v4_2.add_argument("--valid-until", required=True)
    authority_payload_v4_2.add_argument("--approver-id", required=True)
    authority_payload_v4_2.add_argument("--signing-key-fingerprint", required=True)
    authority_payload_v4_2.add_argument("--output", required=True)
    authority_payload_v4_2.set_defaults(handler=_oauth_authority_payload_v4_2)
    authority_verify_v4_2 = oauth_commands.add_parser("authority-verify-v4.2")
    authority_verify_v4_2.add_argument("--policy", required=True)
    authority_verify_v4_2.add_argument("--payload", required=True)
    authority_verify_v4_2.add_argument("--signature", required=True)
    authority_verify_v4_2.add_argument("--public-key", required=True)
    authority_verify_v4_2.add_argument("--verified-at", required=True)
    authority_verify_v4_2.add_argument("--output", required=True)
    authority_verify_v4_2.set_defaults(handler=_oauth_authority_verify_v4_2)

    storage = commands.add_parser("storage")
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    storage_contracts = storage_commands.add_parser("contracts-validate")
    storage_contracts.add_argument("--schema-root")
    storage_contracts.add_argument("--observation", action="append", default=[])
    storage_contracts.add_argument("--evaluated-at")
    storage_contracts.set_defaults(handler=_storage_contracts_validate_v1)
    bind_drive = storage_commands.add_parser("bind-drive")
    bind_drive.add_argument("--registry", required=True)
    bind_drive.add_argument("--observation", required=True)
    bind_drive.add_argument("--registry-output", required=True)
    bind_drive.add_argument("--attestation-output", required=True)
    bind_drive.add_argument("--verifier", required=True)
    bind_drive.add_argument("--bound-at")
    bind_drive.set_defaults(handler=_storage_bind_drive_v1)
    bind_drive_v4 = storage_commands.add_parser("bind-drive-v4")
    bind_drive_v4.add_argument("--registry", required=True)
    bind_drive_v4.add_argument("--observation", required=True)
    bind_drive_v4.add_argument("--registry-id", required=True)
    bind_drive_v4.add_argument("--registry-output", required=True)
    bind_drive_v4.add_argument("--attestation-output", required=True)
    bind_drive_v4.add_argument("--verifier", required=True)
    bind_drive_v4.add_argument("--bound-at")
    bind_drive_v4.set_defaults(handler=_storage_bind_drive_v4)
    marker_payload_v4_2 = storage_commands.add_parser("marker-payload-v4.2")
    marker_payload_v4_2.add_argument("--marker-id", required=True)
    marker_payload_v4_2.add_argument("--provider-resource-id", required=True)
    marker_payload_v4_2.add_argument("--root-resource-id", required=True)
    marker_payload_v4_2.add_argument("--output", required=True)
    marker_payload_v4_2.set_defaults(handler=_storage_marker_payload_v4_2)
    observe_drive_v4_2 = storage_commands.add_parser("observe-drive-v4.2")
    observe_drive_v4_2.add_argument("--policy", required=True)
    observe_drive_v4_2.add_argument(
        "--oauth-authority",
        required=True,
        metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY",
    )
    observe_drive_v4_2.add_argument("--adc-file", required=True)
    observe_drive_v4_2.add_argument("--proof-output", required=True)
    observe_drive_v4_2.set_defaults(handler=_storage_observe_drive_v4_2)

    source = commands.add_parser("source")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    audit = source_commands.add_parser("audit")
    audit.add_argument("--registry", required=True)
    audit.add_argument("--storage-attestation", required=True)
    audit.add_argument("--output")
    audit.set_defaults(handler=_source_audit_v2)
    audit_v1 = source_commands.add_parser("audit-v1")
    audit_v1.add_argument("--registry", required=True)
    audit_v1.add_argument("--storage-map", required=True)
    audit_v1.add_argument("--output")
    audit_v1.set_defaults(handler=_source_audit_v1)
    audit_v4 = source_commands.add_parser("audit-v4")
    audit_v4.add_argument("--registry", required=True)
    audit_v4.add_argument("--storage-attestation", required=True)
    audit_v4.add_argument(
        "--publisher", action="append", default=[], metavar="STATEMENT=RECEIPT"
    )
    audit_v4.add_argument("--evaluated-at", required=True)
    audit_v4.add_argument("--output")
    audit_v4.set_defaults(handler=_source_audit_v4)
    count = source_commands.add_parser("count")
    count.add_argument("--registry", required=True)
    count.add_argument("--storage-attestation", required=True)
    count.add_argument("--source-audit", required=True)
    count.add_argument("--artifact-id", required=True)
    count.add_argument("--output")
    count.set_defaults(handler=_source_count_v2)
    count_v1 = source_commands.add_parser("count-v1")
    count_v1.add_argument("--path", required=True)
    count_v1.add_argument(
        "--kind",
        required=True,
        choices=[
            "wikipedia_xml",
            "mediawiki_sql",
            "wikidata_json",
            "conceptnet_assertions",
        ],
    )
    count_v1.add_argument("--output")
    count_v1.set_defaults(handler=_source_count_v1)
    count_v4 = source_commands.add_parser("count-v4")
    count_v4.add_argument("--registry", required=True)
    count_v4.add_argument("--storage-attestation", required=True)
    count_v4.add_argument("--source-audit", required=True)
    count_v4.add_argument("--artifact-id", required=True)
    count_v4.add_argument(
        "--publisher", action="append", default=[], metavar="STATEMENT=RECEIPT"
    )
    count_v4.add_argument("--evaluated-at", required=True)
    count_v4.add_argument("--output")
    count_v4.set_defaults(handler=_source_count_v4)
    remote = source_commands.add_parser("remote")
    remote.add_argument("--url", required=True)
    remote.set_defaults(handler=_source_remote)
    publisher_receipt_v4 = source_commands.add_parser("publisher-receipt-v4")
    publisher_receipt_v4.add_argument("--registry", required=True)
    publisher_receipt_v4.add_argument("--evidence-id", required=True)
    publisher_receipt_v4.add_argument("--statement", required=True)
    publisher_receipt_v4.add_argument("--resolved-url", required=True)
    publisher_receipt_v4.add_argument("--retrieved-at", required=True)
    publisher_receipt_v4.add_argument("--verified-at", required=True)
    publisher_receipt_v4.add_argument("--verifier", required=True)
    publisher_receipt_v4.add_argument("--output", required=True)
    publisher_receipt_v4.set_defaults(handler=_source_publisher_receipt_v4)
    assess = source_commands.add_parser("assess-admission")
    assess.add_argument("--source-id", required=True)
    assess.add_argument("--registry", required=True)
    assess.add_argument("--storage-attestation", required=True)
    assess.add_argument("--source-audit", required=True)
    assess.add_argument("--licence-review", required=True)
    assess.add_argument("--terms", required=True)
    assess.add_argument("--quarantine", required=True)
    assess.add_argument("--inventory", action="append", default=[])
    assess.add_argument("--assessor", required=True)
    assess.add_argument("--assessed-at")
    assess.add_argument("--output")
    assess.set_defaults(handler=_source_assess_admission_v2)
    assess_v3 = source_commands.add_parser("assess-admission-v3")
    assess_v3.add_argument("--source-id", required=True)
    assess_v3.add_argument("--registry", required=True)
    assess_v3.add_argument("--storage-attestation", required=True)
    assess_v3.add_argument("--source-audit", required=True)
    assess_v3.add_argument("--licence-assessment", required=True)
    assess_v3.add_argument("--licence-bundle", required=True)
    assess_v3.add_argument("--quarantine", required=True)
    assess_v3.add_argument("--inventory", action="append", default=[])
    assess_v3.add_argument("--assessor", required=True)
    assess_v3.add_argument("--assessed-at", required=True)
    assess_v3.add_argument("--output")
    assess_v3.set_defaults(handler=_source_assess_admission_v3)
    assess_v4 = source_commands.add_parser("assess-admission-v4")
    assess_v4.add_argument("--source-id", required=True)
    assess_v4.add_argument("--registry", required=True)
    assess_v4.add_argument("--evaluations", required=True)
    assess_v4.add_argument("--storage-attestation", required=True)
    assess_v4.add_argument("--source-audit", required=True)
    assess_v4.add_argument("--licence-assessment", required=True)
    assess_v4.add_argument("--licence-bundle", required=True)
    assess_v4.add_argument("--quarantine", required=True)
    assess_v4.add_argument("--inventory", action="append", default=[])
    assess_v4.add_argument(
        "--publisher", action="append", default=[], metavar="STATEMENT=RECEIPT"
    )
    assess_v4.add_argument("--assessor", required=True)
    assess_v4.add_argument("--assessed-at", required=True)
    assess_v4.add_argument("--output")
    assess_v4.set_defaults(handler=_source_assess_admission_v4)
    acquire = source_commands.add_parser("acquire")
    _add_v2_gate_arguments(acquire)
    acquire.add_argument("--artifact-id", required=True)
    acquire.add_argument("--minimum-free-bytes", required=True, type=int)
    acquire.set_defaults(handler=_source_acquire_v2)
    acquire_v3 = source_commands.add_parser("acquire-v3")
    _add_v3_gate_arguments(acquire_v3)
    acquire_v3.add_argument("--artifact-id", required=True)
    acquire_v3.add_argument("--minimum-free-bytes", required=True, type=int)
    acquire_v3.set_defaults(handler=_source_acquire_v3)
    acquire_v4 = source_commands.add_parser("acquire-v4")
    _add_v4_gate_arguments(acquire_v4)
    acquire_v4.add_argument("--artifact-id", required=True)
    acquire_v4.add_argument("--minimum-free-bytes", required=True, type=int)
    acquire_v4.set_defaults(handler=_source_acquire_v4)
    acquire_v4_1 = source_commands.add_parser("acquire-v4.1")
    _add_v4_1_gate_arguments(acquire_v4_1)
    acquire_v4_1.add_argument("--artifact-id", required=True)
    acquire_v4_1.add_argument("--minimum-free-bytes", required=True, type=int)
    acquire_v4_1.set_defaults(handler=_source_acquire_v4_1)
    authorization_payload_v4_2 = source_commands.add_parser(
        "authorization-payload-v4.2"
    )
    _add_v4_2_gate_arguments(authorization_payload_v4_2)
    authorization_payload_v4_2.add_argument("--artifact-id", required=True)
    authorization_payload_v4_2.add_argument("--authorization-id", required=True)
    authorization_payload_v4_2.add_argument("--byte-ceiling", required=True, type=int)
    authorization_payload_v4_2.add_argument("--authorized-at", required=True)
    authorization_payload_v4_2.add_argument("--valid-until", required=True)
    authorization_payload_v4_2.add_argument("--authorizer-id", required=True)
    authorization_payload_v4_2.add_argument("--signing-key-fingerprint", required=True)
    authorization_payload_v4_2.add_argument("--authorization-output", required=True)
    authorization_payload_v4_2.set_defaults(handler=_source_authorization_payload_v4_2)
    authorization_verify_v4_2 = source_commands.add_parser("authorization-verify-v4.2")
    authorization_verify_v4_2.add_argument("--policy", required=True)
    authorization_verify_v4_2.add_argument(
        "--source-registry", action="append", required=True
    )
    authorization_verify_v4_2.add_argument("--storage-attestation", required=True)
    authorization_verify_v4_2.add_argument(
        "--oauth-authority",
        required=True,
        metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY",
    )
    authorization_verify_v4_2.add_argument("--payload", required=True)
    authorization_verify_v4_2.add_argument("--signature", required=True)
    authorization_verify_v4_2.add_argument("--public-key", required=True)
    authorization_verify_v4_2.add_argument("--verified-at", required=True)
    authorization_verify_v4_2.add_argument("--output", required=True)
    authorization_verify_v4_2.set_defaults(handler=_source_authorization_verify_v4_2)
    acquire_v4_2 = source_commands.add_parser("acquire-v4.2")
    _add_v4_2_gate_arguments(acquire_v4_2, include_evaluated_at=False)
    acquire_v4_2.add_argument("--artifact-id", required=True)
    acquire_v4_2.add_argument("--minimum-free-bytes", required=True, type=int)
    acquire_v4_2.add_argument("--adc-file", required=True)
    acquire_v4_2.add_argument("--receipt-output", required=True)
    acquire_v4_2.add_argument("--pre-source-audit-output", required=True)
    acquire_v4_2.add_argument("--pre-proof-output", required=True)
    acquire_v4_2.add_argument("--post-proof-output", required=True)
    acquire_v4_2.add_argument("--authorization-gate-output", required=True)
    acquire_v4_2.set_defaults(handler=_source_acquire_v4_2)
    acquire_v1 = source_commands.add_parser("acquire-v1")
    acquire_v1.add_argument("--registry", required=True)
    acquire_v1.add_argument("--storage-map", required=True)
    acquire_v1.add_argument("--evaluations", required=True)
    acquire_v1.add_argument("--quarantine", required=True)
    acquire_v1.add_argument("--source-audit", required=True)
    acquire_v1.add_argument(
        "--seal", action="append", default=[], metavar="CIPHERTEXT=RECEIPT"
    )
    acquire_v1.add_argument("--artifact-id", required=True)
    acquire_v1.add_argument("--evaluated-at", required=True)
    acquire_v1.add_argument("--minimum-free-bytes", required=True, type=int)
    acquire_v1.set_defaults(handler=_source_acquire_v1)

    evaluation = commands.add_parser("evaluation")
    evaluation_commands = evaluation.add_subparsers(
        dest="evaluation_command", required=True
    )
    materialize_v4_1 = evaluation_commands.add_parser("materialize-v4.1")
    materialize_v4_1.add_argument("--evaluations", required=True)
    materialize_v4_1.add_argument("--dataset-id", required=True)
    materialize_v4_1.add_argument("--archive", required=True)
    materialize_v4_1.add_argument("--adapter", required=True)
    materialize_v4_1.add_argument("--oracle", required=True)
    materialize_v4_1.add_argument("--envelope", required=True)
    materialize_v4_1.add_argument("--inventory", required=True)
    materialize_v4_1.add_argument("--manifest-id", required=True)
    materialize_v4_1.add_argument("--materialized-at", required=True)
    materialize_v4_1.add_argument("--manifest-output", required=True)
    materialize_v4_1.add_argument("--receipt-output", required=True)
    materialize_v4_1.set_defaults(handler=_evaluation_materialize_v4_1)

    quarantine = commands.add_parser("quarantine")
    quarantine_commands = quarantine.add_subparsers(
        dest="quarantine_command", required=True
    )
    fingerprint = quarantine_commands.add_parser("fingerprint")
    fingerprint.add_argument("--path", default="-")
    fingerprint.add_argument("--fingerprint-id", required=True)
    fingerprint.set_defaults(handler=_quarantine_fingerprint)
    compile_command = quarantine_commands.add_parser("compile")
    compile_command.add_argument("--contribution", action="append", default=[])
    compile_command.add_argument("--index-id", default="public-evaluation-union-v2")
    compile_command.add_argument("--output")
    compile_command.set_defaults(handler=_quarantine_compile_v2)
    compile_v1 = quarantine_commands.add_parser("compile-v1")
    compile_v1.add_argument("--specification", required=True)
    compile_v1.add_argument("--output")
    compile_v1.set_defaults(handler=_quarantine_compile_v1)
    check = quarantine_commands.add_parser("check")
    check.add_argument("--descriptor", required=True)
    check.add_argument("--index", required=True)
    check.set_defaults(handler=_quarantine_check)
    contribution_v4 = quarantine_commands.add_parser("contribution-v4")
    contribution_v4.add_argument("--envelope", required=True)
    contribution_v4.add_argument("--output")
    contribution_v4.set_defaults(handler=_quarantine_contribution_v4)
    compile_v4 = quarantine_commands.add_parser("compile-v4")
    compile_v4.add_argument("--evaluations", required=True)
    compile_v4.add_argument("--contribution", action="append", default=[])
    compile_v4.add_argument("--index-id", default="public-evaluation-union-v4")
    compile_v4.add_argument("--output")
    compile_v4.set_defaults(handler=_quarantine_compile_v4)
    descriptor_v4 = quarantine_commands.add_parser("descriptor-v4")
    descriptor_v4.add_argument("--input", default="-")
    descriptor_v4.add_argument("--output")
    descriptor_v4.set_defaults(handler=_quarantine_descriptor_v4)
    check_v4 = quarantine_commands.add_parser("check-v4")
    check_v4.add_argument("--descriptor", required=True)
    check_v4.add_argument("--index", required=True)
    check_v4.add_argument("--checked-at", required=True)
    check_v4.add_argument("--output")
    check_v4.set_defaults(handler=_quarantine_check_v4)

    seal = commands.add_parser("seal")
    seal_commands = seal.add_subparsers(dest="seal_command", required=True)
    create = seal_commands.add_parser("create")
    create.add_argument("--input", default="-")
    create.add_argument("--output", required=True)
    create.add_argument("--recipient", required=True)
    create.add_argument("--receipt", required=True)
    create.add_argument("--contribution", required=True)
    create.add_argument("--evaluations", required=True)
    create.add_argument("--custodian", required=True)
    create.set_defaults(handler=_seal_create_v2)
    create_v4 = seal_commands.add_parser("create-v4")
    create_v4.add_argument("--input", default="-")
    create_v4.add_argument("--output", required=True)
    create_v4.add_argument("--recipient", required=True)
    create_v4.add_argument("--receipt", required=True)
    create_v4.add_argument("--contribution", required=True)
    create_v4.add_argument("--evaluations", required=True)
    create_v4.add_argument("--custodian", required=True)
    create_v4.add_argument("--created-at")
    create_v4.set_defaults(handler=_seal_create_v4)
    create_v4_1 = seal_commands.add_parser("create-v4.1")
    create_v4_1.add_argument("--output", required=True)
    create_v4_1.add_argument("--recipient", required=True)
    create_v4_1.add_argument("--receipt", required=True)
    create_v4_1.add_argument("--contribution", required=True)
    create_v4_1.add_argument("--access-log", required=True)
    create_v4_1.add_argument("--evaluations", required=True)
    create_v4_1.add_argument(
        "--materialization",
        required=True,
        metavar="MANIFEST=RECEIPT=ARCHIVE=ADAPTER=ORACLE=ENVELOPE",
    )
    create_v4_1.add_argument("--licence-assessment", required=True)
    create_v4_1.add_argument("--licence-bundle", required=True)
    create_v4_1.add_argument("--custodian", required=True)
    create_v4_1.add_argument("--created-at", required=True)
    create_v4_1.set_defaults(handler=_seal_create_v4_1)
    anchor_payload_v4 = seal_commands.add_parser("anchor-payload-v4")
    anchor_payload_v4.add_argument("--seal-receipt", required=True)
    anchor_payload_v4.add_argument("--access-log", required=True)
    anchor_payload_v4.add_argument("--sequence", required=True, type=int)
    anchor_payload_v4.add_argument("--previous-anchor")
    anchor_payload_v4.add_argument("--anchored-at", required=True)
    anchor_payload_v4.add_argument("--valid-until", required=True)
    anchor_payload_v4.add_argument("--authority-id", required=True)
    anchor_payload_v4.add_argument("--signing-key-fingerprint", required=True)
    anchor_payload_v4.add_argument("--output", required=True)
    anchor_payload_v4.set_defaults(handler=_seal_anchor_payload_v4)
    create_v1 = seal_commands.add_parser("create-v1")
    create_v1.add_argument("--input", default="-")
    create_v1.add_argument("--output", required=True)
    create_v1.add_argument("--recipient", required=True)
    create_v1.add_argument("--receipt", required=True)
    create_v1.add_argument("--seal-id", required=True)
    create_v1.add_argument(
        "--evaluation-class",
        required=True,
        choices=["confirmatory", "private_transfer"],
    )
    create_v1.add_argument("--artifact-hash", action="append", default=[])
    create_v1.add_argument("--custodian", required=True)
    create_v1.add_argument("--record-count", required=True, type=int)
    create_v1.set_defaults(handler=_seal_create_v1)
    verify = seal_commands.add_parser("verify")
    verify.add_argument("--ciphertext", required=True)
    verify.add_argument("--receipt", required=True)
    verify.set_defaults(handler=_seal_verify_v2)
    verify_v1 = seal_commands.add_parser("verify-v1")
    verify_v1.add_argument("--ciphertext", required=True)
    verify_v1.add_argument("--receipt", required=True)
    verify_v1.set_defaults(handler=_seal_verify_v1)
    log_event = seal_commands.add_parser("log-event")
    log_event.add_argument("--log", required=True)
    log_event.add_argument("--seal-id", required=True)
    log_event.add_argument(
        "--action",
        required=True,
        choices=[
            "seal_created",
            "verify",
            "decrypt",
            "inspect_labels",
            "report_confirmatory_result",
            "tune_from_result",
            "consume",
            "retire",
        ],
    )
    log_event.add_argument("--actor", required=True)
    log_event.add_argument("--details", default="{}")
    log_event.set_defaults(handler=_seal_log_event)
    verify_log = seal_commands.add_parser("verify-log")
    verify_log.add_argument("--log", required=True)
    verify_log.add_argument("--expected-head")
    verify_log.add_argument("--expected-count", type=int)
    verify_log.set_defaults(handler=_seal_verify_log)

    licence = commands.add_parser("licence")
    licence_commands = licence.add_subparsers(dest="licence_command", required=True)
    licence_verify = licence_commands.add_parser("verify")
    licence_verify.add_argument("--review", required=True)
    licence_verify.add_argument("--terms", required=True)
    licence_verify.set_defaults(handler=_licence_verify_v2)
    licence_contracts = licence_commands.add_parser("contracts-validate")
    licence_contracts.add_argument("--schema-root")
    licence_contracts.add_argument(
        "--instance", action="append", default=[], metavar="PATH=SCHEMA"
    )
    licence_contracts.set_defaults(handler=_licence_contracts_validate_v1)
    licence_capture = licence_commands.add_parser("capture")
    licence_capture.add_argument("--url", required=True)
    licence_capture.add_argument("--document-id", required=True)
    licence_capture.add_argument(
        "--role",
        required=True,
        choices=[
            "applicability_statement",
            "legal_code",
            "publisher_terms",
            "platform_terms",
            "download_terms",
            "repository_licence",
            "model_or_dataset_card",
            "repository_tree",
            "embedded_licence",
            "provenance",
            "official_legal_metadata",
            "first_party_attestation",
        ],
    )
    licence_capture.add_argument(
        "--source-kind",
        default="https_response",
        choices=["https_response", "repository_file", "official_metadata"],
    )
    licence_capture.add_argument("--output", required=True)
    licence_capture.add_argument("--receipt", required=True)
    licence_capture.add_argument("--allow-host", action="append", required=True)
    licence_capture.add_argument("--expected-media-type")
    licence_capture.add_argument("--revision")
    licence_capture.add_argument("--mutable", action="store_true")
    licence_capture.add_argument("--retrieved-at")
    licence_capture.set_defaults(handler=_licence_capture_v1)
    bundle_create = licence_commands.add_parser("bundle-create")
    bundle_create.add_argument("--bundle-id", required=True)
    bundle_create.add_argument("--review-id", required=True)
    bundle_create.add_argument(
        "--subject-kind", required=True, choices=["source", "evaluation", "encoder"]
    )
    bundle_create.add_argument("--subject-id", required=True)
    bundle_create.add_argument("--subject-binding-sha256", required=True)
    bundle_create.add_argument("--document", action="append", default=[])
    bundle_create.add_argument("--finding", action="append", default=[])
    bundle_create.add_argument("--assembled-at")
    bundle_create.add_argument("--output", required=True)
    bundle_create.set_defaults(handler=_licence_bundle_create_v1)
    bundle_verify = licence_commands.add_parser("bundle-verify")
    bundle_verify.add_argument("--bundle", required=True)
    bundle_verify.set_defaults(handler=_licence_bundle_verify_v1)
    assessment_scaffold = licence_commands.add_parser("assessment-scaffold")
    assessment_scaffold.add_argument("--bundle", required=True)
    assessment_scaffold.add_argument("--output", required=True)
    assessment_scaffold.set_defaults(handler=_licence_assessment_scaffold_v1)
    assessment_finalize = licence_commands.add_parser("assessment-finalize")
    assessment_finalize.add_argument("--input", required=True)
    assessment_finalize.add_argument("--bundle", required=True)
    assessment_finalize.add_argument("--output", required=True)
    assessment_finalize.add_argument(
        "--decision", required=True, choices=["approved", "rejected", "pending"]
    )
    assessment_finalize.add_argument(
        "--commercial-context",
        required=True,
        choices=["allowed", "prohibited", "unclear"],
    )
    assessment_finalize.add_argument("--licence-id", action="append", default=[])
    use_choices = [
        "acquire",
        "inventory",
        "quarantine",
        "transform",
        "embed",
        "inference",
        "evaluate",
        "commercial_service",
        "train",
        "redistribute_source",
        "redistribute_derived",
        "redistribute_model",
    ]
    assessment_finalize.add_argument(
        "--allow-use", action="append", default=[], choices=use_choices
    )
    assessment_finalize.add_argument(
        "--exclude-use", action="append", default=[], choices=use_choices
    )
    assessment_finalize.add_argument("--required-use", action="append", default=[])
    assessment_finalize.add_argument("--obligation", action="append", default=[])
    assessment_finalize.add_argument("--resolve-finding", action="append", default=[])
    assessment_finalize.add_argument(
        "--acknowledge-finding", action="append", default=[]
    )
    assessment_finalize.add_argument("--reviewer")
    assessment_finalize.add_argument("--reviewed-at")
    assessment_finalize.add_argument("--valid-until")
    assessment_finalize.add_argument("--evaluated-at")
    assessment_finalize.add_argument("--notes", default="")
    assessment_finalize.set_defaults(handler=_licence_assessment_finalize_v1)
    catalogue_validate = licence_commands.add_parser("catalogue-validate")
    catalogue_validate.add_argument("--catalogue", required=True)
    catalogue_validate.add_argument("--sources", required=True)
    catalogue_validate.add_argument("--evaluations", required=True)
    catalogue_validate.add_argument("--encoder-spec", required=True)
    catalogue_validate.set_defaults(handler=_licence_catalogue_validate_v1)
    catalogue_capture = licence_commands.add_parser("catalogue-capture")
    catalogue_capture.add_argument("--catalogue", required=True)
    catalogue_capture.add_argument("--sources", required=True)
    catalogue_capture.add_argument("--evaluations", required=True)
    catalogue_capture.add_argument("--encoder-spec", required=True)
    catalogue_capture.add_argument("--output-root", required=True)
    catalogue_capture.set_defaults(handler=_licence_catalogue_capture_v1)
    catalogue_prepare = licence_commands.add_parser("catalogue-prepare")
    catalogue_prepare.add_argument("--catalogue", required=True)
    catalogue_prepare.add_argument("--sources", required=True)
    catalogue_prepare.add_argument("--evaluations", required=True)
    catalogue_prepare.add_argument("--encoder-spec", required=True)
    catalogue_prepare.add_argument("--evidence-root", required=True)
    catalogue_prepare.add_argument("--audit-index", required=True)
    catalogue_prepare.add_argument("--assembled-at")
    catalogue_prepare.set_defaults(handler=_licence_catalogue_prepare_v1)
    catalogue_rebind = licence_commands.add_parser("catalogue-rebind")
    catalogue_rebind.add_argument("--catalogue", required=True)
    catalogue_rebind.add_argument("--sources", required=True)
    catalogue_rebind.add_argument("--evaluations", required=True)
    catalogue_rebind.add_argument("--encoder-spec", required=True)
    catalogue_rebind.add_argument("--verified-capture-root", required=True)
    catalogue_rebind.add_argument("--output-root", required=True)
    catalogue_rebind.add_argument("--audit-index", required=True)
    catalogue_rebind.add_argument("--assembled-at", required=True)
    catalogue_rebind.set_defaults(handler=_licence_catalogue_rebind)

    gate = commands.add_parser("gate")
    _add_v2_gate_arguments(gate)
    gate.add_argument("--output")
    gate.set_defaults(handler=_gate_v2)

    gate_v3 = commands.add_parser("gate-v3")
    _add_v3_gate_arguments(gate_v3)
    gate_v3.add_argument("--output")
    gate_v3.set_defaults(handler=_gate_v3)

    gate_v4 = commands.add_parser("gate-v4")
    _add_v4_gate_arguments(gate_v4)
    gate_v4.add_argument("--output")
    gate_v4.set_defaults(handler=_gate_v4)

    gate_v4_1 = commands.add_parser("gate-v4.1")
    _add_v4_1_gate_arguments(gate_v4_1)
    gate_v4_1.add_argument("--output")
    gate_v4_1.set_defaults(handler=_gate_v4_1)

    gate_v4_2 = commands.add_parser("gate-v4.2")
    _add_v4_2_gate_arguments(gate_v4_2)
    gate_v4_2.add_argument("--output")
    gate_v4_2.set_defaults(handler=_gate_v4_2)

    gate_v1 = commands.add_parser("gate-v1")
    gate_v1.add_argument("--sources", required=True)
    gate_v1.add_argument("--evaluations", required=True)
    gate_v1.add_argument("--quarantine")
    gate_v1.add_argument(
        "--seal",
        action="append",
        default=[],
        metavar="CIPHERTEXT=RECEIPT",
    )
    gate_v1.add_argument("--source-audit")
    gate_v1.add_argument("--evaluated-at", required=True)
    gate_v1.add_argument("--output")
    gate_v1.set_defaults(handler=_gate_v1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Phase0Error as exc:
        sys.stderr.write(f"hf-phase0: {exc}\n")
        return 2
