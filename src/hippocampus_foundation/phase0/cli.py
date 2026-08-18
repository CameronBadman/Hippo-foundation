"""Command-line interface containing Phase 0 operations only."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from hippocampus_foundation.licensing import (
    FORBIDDEN_USES,
    build_evidence_bundle,
    capture_https_document,
    load_verified_bundle,
    make_pending_assessment,
    validate_schema_lock_v1 as validate_licensing_schema_lock_v1,
    validate_v1 as validate_licensing_v1,
    verify_assessment,
    verify_evidence_bundle,
)
from hippocampus_foundation.licence_catalog import (
    capture_catalogue,
    load_catalogue,
    prepare_catalogue_packets,
    validate_catalogue,
)
from hippocampus_foundation.storage_identity import (
    bind_drive_observation,
    validate_observation_v1,
    validate_schema_lock_v1 as validate_storage_schema_lock_v1,
)

from .acquisition import download_resumable, remote_metadata
from .canonical import canonical_sha256, dump_pretty, load_json, sha256_bytes
from .errors import GateBlocked, Phase0Error
from .gate import evaluate_gate
from .inventory import audit_source_registry, stream_count
from .quarantine import (
    Identifier,
    compile_public_index,
    fingerprint_text,
    match_record,
    normalize_identifier,
)
from .seal import (
    append_access_event,
    encrypt_canonical_bundle,
    make_seal_receipt,
    read_access_events,
    verify_ciphertext,
)
from .validation import (
    validate_evaluation_registry,
    validate_instance,
    validate_json_file,
    validate_schema_set,
    validate_source_audit,
    validate_source_registry,
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


def _emit(value: Any) -> None:
    sys.stdout.write(dump_pretty(value))


def _write_json_atomic(path: Path, value: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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
    if source["role"] != "foundation_candidate" or source["admission_status"] != "accepted":
        raise GateBlocked(f"artifact is not an accepted foundation candidate: {args.artifact_id}")
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
    return normalize_identifier(value["namespace"], value["value"], value.get("source_version"))


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
    bound_at = args.bound_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
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
    _emit({"ok": True, "bundle_id": bundle["bundle_id"], "sha256": canonical_sha256(bundle)})
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
            item for item in verified.bundle["findings"] if item["finding_id"] == finding_id
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
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
    _write_json_exclusive(output, assessment, mode=0o600)
    _emit(assessment)
    return 0


def _catalogue_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
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
    assembled_at = args.assembled_at or datetime.now(timezone.utc).isoformat().replace(
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
    remote = source_commands.add_parser("remote")
    remote.add_argument("--url", required=True)
    remote.set_defaults(handler=_source_remote)
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

    quarantine = commands.add_parser("quarantine")
    quarantine_commands = quarantine.add_subparsers(dest="quarantine_command", required=True)
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

    gate = commands.add_parser("gate")
    _add_v2_gate_arguments(gate)
    gate.add_argument("--output")
    gate.set_defaults(handler=_gate_v2)

    gate_v3 = commands.add_parser("gate-v3")
    _add_v3_gate_arguments(gate_v3)
    gate_v3.add_argument("--output")
    gate_v3.set_defaults(handler=_gate_v3)

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
