"""CLI registration for additive Phase 0 v4.3 and publication v1."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hippocampus_foundation.licensing import load_verified_bundle

from .canonical import canonical_sha256, dump_pretty, load_json, sha256_bytes
from .errors import Phase0Error
from .execution_v4_1 import VerifiedRegistryLineage, validate_registry_lineage_v4_1
from .external_evidence import (
    MAX_OPENPGP_EVIDENCE_BYTES,
    VerifiedPublisherReceipt,
    _verify_detached_signature_gpg,
)
from .publication_v1 import (
    APPROVED_DESTINATION_POLICY_SHA256,
    APPROVED_PUBLICATION_AUTHORITY_POLICY_SHA256,
    HuggingFaceHubClient,
    VerifiedPublicationAuthorization,
    VerifiedPublicationRights,
    build_obligation_manifest,
    evaluate_publication_gate,
    inventory_publication_artifact,
    make_publication_authorization_payload,
    observe_destination,
    publish_artifact,
    recover_publication,
    scaffold_publication_rights_payload,
    verify_historical_publication_authorization,
    verify_publication_authorization,
    verify_publication_rights,
)
from .publication_v1_contracts import (
    validate_publication_schema_lock_v1,
    validate_publication_v1,
)
from .staging_v4_3 import (
    APPROVED_STAGING_AUTHORITY_POLICY_SHA256,
    VerifiedEvaluationGate,
    VerifiedStagingAuthorization,
    acquire_to_staging,
    audit_staged_artifact,
    evaluate_gate_v4_3,
    init_staging_root,
    inventory_staged_artifact,
    make_artifact_publication_clearance,
    make_source_admission,
    make_staging_authorization_payload,
    observe_staging_root,
    reproduce_evaluation_gate_v4_1,
    validate_evaluation_side_ready,
    validate_staging_authorization_time,
    validate_staging_observation,
    verify_staging_authorization,
)
from .v4_3_contracts import validate_schema_lock_v4_3, validate_v4_3


def _emit(value: Any) -> None:
    sys.stdout.write(dump_pretty(value))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_object(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise Phase0Error(f"expected a JSON object: {path}")
    return value


def _read_file(path: Path, maximum_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise Phase0Error(f"cannot open {label} safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum_bytes:
            raise Phase0Error(f"{label} is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            value = handle.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(value) > maximum_bytes or (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise Phase0Error(f"{label} changed while being read")
    return value


def _write_json(path: Path, value: Any, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
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


def _parts(value: str, option: str, count: int) -> list[str]:
    parts = value.split("=")
    if len(parts) != count or any(not part for part in parts):
        raise Phase0Error(f"{option} requires exactly {count} non-empty parts")
    return parts


def _lineage(paths: Sequence[str], kind: str) -> VerifiedRegistryLineage:
    lineage = validate_registry_lineage_v4_1(
        [_json_object(Path(path)) for path in paths]
    )
    if lineage.receipt["registry_kind"] != kind:
        raise Phase0Error(f"expected a rooted {kind} registry lineage")
    return lineage


def _lookup(
    registry: dict[str, Any], artifact_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [
        (source, artifact)
        for source in registry["sources"]
        for artifact in source["artifacts"]
        if artifact["artifact_id"] == artifact_id
    ]
    if len(matches) != 1:
        raise Phase0Error(f"artifact must resolve exactly once: {artifact_id}")
    return matches[0]


def _reproduced_graph(
    args: argparse.Namespace,
    *,
    evaluated_at: str,
    require_complete_publishers: bool = True,
) -> tuple[
    VerifiedRegistryLineage,
    Any,
    dict[str, VerifiedPublisherReceipt],
]:
    # Runtime import avoids a module cycle while reusing the frozen CLI's exact
    # evidence loaders and independent verifiers.
    from .cli import _load_v4_1_graph_args

    graph = _load_v4_1_graph_args(args, evaluated_at=evaluated_at)
    verified_gate = reproduce_evaluation_gate_v4_1(**graph)
    source_lineage = validate_registry_lineage_v4_1(graph["source_registries"])
    publisher_map: dict[str, VerifiedPublisherReceipt] = {}
    for item in graph["publisher_receipts"]:
        artifact_id = item.receipt["artifact_id"]
        if artifact_id in publisher_map:
            raise Phase0Error(f"duplicate publisher evidence: {artifact_id}")
        publisher_map[artifact_id] = item
    expected = {
        artifact["artifact_id"]
        for source in source_lineage.tip["sources"]
        for artifact in source["artifacts"]
    }
    if require_complete_publishers and set(publisher_map) != expected:
        raise Phase0Error("publisher evidence does not cover the exact source registry")
    return source_lineage, verified_gate, publisher_map


def _rights(
    value: str,
    *,
    authority_policy: dict[str, Any],
    destination_policy: dict[str, Any],
    source: dict[str, Any],
    evaluated_at: str,
) -> VerifiedPublicationRights:
    payload_text, signature_text, key_text, bundle_text = _parts(value, "--rights", 4)
    return verify_publication_rights(
        _json_object(Path(payload_text)),
        signature=_read_file(
            Path(signature_text), MAX_OPENPGP_EVIDENCE_BYTES, "rights signature"
        ),
        public_key=_read_file(
            Path(key_text), MAX_OPENPGP_EVIDENCE_BYTES, "rights public key"
        ),
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        source_id=source["source_id"],
        source_entry=source,
        evidence_bundle=load_verified_bundle(Path(bundle_text)),
        evaluated_at=evaluated_at,
        approved_authority_policy_sha256=(APPROVED_PUBLICATION_AUTHORITY_POLICY_SHA256),
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
        signature_verifier=_verify_detached_signature_gpg,
    )


def _staging_authorization(
    value: str,
    *,
    policy: dict[str, Any],
    source_registry: dict[str, Any],
    publisher_receipt: VerifiedPublisherReceipt,
    staging_observation: dict[str, Any],
    evaluation_gate: VerifiedEvaluationGate,
) -> VerifiedStagingAuthorization:
    payload_text, signature_text, key_text = _parts(value, "--authorization", 3)
    return verify_staging_authorization(
        _json_object(Path(payload_text)),
        signature=_read_file(
            Path(signature_text),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "staging authorization signature",
        ),
        public_key=_read_file(
            Path(key_text),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "staging authorization public key",
        ),
        policy=policy,
        source_registry=source_registry,
        publisher_receipt=publisher_receipt,
        staging_observation=staging_observation,
        evaluation_gate=evaluation_gate,
        approved_policy_sha256=APPROVED_STAGING_AUTHORITY_POLICY_SHA256,
        signature_verifier=_verify_detached_signature_gpg,
    )


def _publication_authorization(
    value: str,
    *,
    authority_policy: dict[str, Any],
    destination_policy: dict[str, Any],
    destination_observation: dict[str, Any],
    artifact_clearance: dict[str, Any],
    rights: VerifiedPublicationRights,
    obligations: dict[str, Any],
    artifact_audit: dict[str, Any],
    artifact_manifest: dict[str, Any],
) -> VerifiedPublicationAuthorization:
    payload_text, signature_text, key_text = _parts(value, "--authorization", 3)
    return verify_publication_authorization(
        _json_object(Path(payload_text)),
        signature=_read_file(
            Path(signature_text),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "publication authorization signature",
        ),
        public_key=_read_file(
            Path(key_text),
            MAX_OPENPGP_EVIDENCE_BYTES,
            "publication authorization public key",
        ),
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        destination_observation=destination_observation,
        artifact_clearance=artifact_clearance,
        rights=rights,
        obligations=obligations,
        artifact_audit=artifact_audit,
        artifact_manifest=artifact_manifest,
        approved_authority_policy_sha256=(APPROVED_PUBLICATION_AUTHORITY_POLICY_SHA256),
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
        signature_verifier=_verify_detached_signature_gpg,
    )


def _registry_validate(args: argparse.Namespace) -> int:
    phase = validate_schema_lock_v4_3(
        Path(args.phase_schema_root) if args.phase_schema_root else None
    )
    publication = validate_publication_schema_lock_v1(
        Path(args.publication_schema_root) if args.publication_schema_root else None
    )
    checked: dict[str, str] = {}
    for value in args.instance:
        path_text, schema_family, schema_name = _parts(value, "--instance", 3)
        instance = _json_object(Path(path_text))
        if schema_family == "phase0-v4.3":
            validate_v4_3(instance, schema_name)
        elif schema_family == "publication-v1":
            validate_publication_v1(instance, schema_name)
        else:
            raise Phase0Error("schema family must be phase0-v4.3 or publication-v1")
        checked[path_text] = canonical_sha256(instance)
    result = {
        "ok": True,
        "phase0_v4_3_schema_digests": phase,
        "publication_v1_schema_digests": publication,
        "instance_digests": {key: checked[key] for key in sorted(checked)},
        "training_authorized": False,
    }
    _emit(result)
    return 0


def _staging_init(args: argparse.Namespace) -> int:
    result = init_staging_root(
        Path(args.root),
        observation_id=args.observation_id,
        created_at=args.created_at,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _staging_observe(args: argparse.Namespace) -> int:
    result = observe_staging_root(
        Path(args.root),
        observation_id=args.observation_id,
        observed_at=args.observed_at,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _staging_authorization_payload(args: argparse.Namespace) -> int:
    lineage, evaluation_gate, publishers = _reproduced_graph(
        args, evaluated_at=args.authorized_at
    )
    registry = lineage.tip
    result = make_staging_authorization_payload(
        policy=_json_object(Path(args.policy)),
        approved_policy_sha256=APPROVED_STAGING_AUTHORITY_POLICY_SHA256 or "",
        source_registry=registry,
        artifact_id=args.artifact_id,
        publisher_receipt=publishers[args.artifact_id],
        staging_observation=_json_object(Path(args.staging_observation)),
        evaluation_gate=evaluation_gate,
        authorization_id=args.authorization_id,
        byte_ceiling=args.byte_ceiling,
        authorized_at=args.authorized_at,
        valid_until=args.valid_until,
        authorizer_id=args.authorizer_id,
        signing_key_fingerprint=args.signing_key_fingerprint,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _staging_authorization_verify(args: argparse.Namespace) -> int:
    payload_path = _parts(args.authorization, "--authorization", 3)[0]
    payload = _json_object(Path(payload_path))
    lineage, evaluation_gate, publishers = _reproduced_graph(
        args, evaluated_at=payload["authorized_at"]
    )
    _reproduced_graph(args, evaluated_at=args.verified_at)
    registry = lineage.tip
    artifact_id = payload["artifact_id"]
    verified = _staging_authorization(
        args.authorization,
        policy=_json_object(Path(args.policy)),
        source_registry=registry,
        publisher_receipt=publishers[artifact_id],
        staging_observation=_json_object(Path(args.staging_observation)),
        evaluation_gate=evaluation_gate,
    )
    validate_staging_authorization_time(verified, evaluated_at=args.verified_at)
    _write_json(Path(args.output), verified.receipt)
    _emit(verified.receipt)
    return 0


def _staging_acquire(args: argparse.Namespace) -> int:
    now = _utc_now()
    payload_path = _parts(args.authorization, "--authorization", 3)[0]
    payload = _json_object(Path(payload_path))
    lineage, signed_gate, signed_publishers = _reproduced_graph(
        args, evaluated_at=payload["authorized_at"]
    )
    fresh_lineage, fresh_gate, fresh_publishers = _reproduced_graph(
        args, evaluated_at=now
    )
    if fresh_lineage.sha256 != lineage.sha256:
        raise Phase0Error("source registry lineage changed after authorization")
    registry = lineage.tip
    validate_evaluation_side_ready(fresh_gate, evaluated_at=now)
    artifact_id = payload["artifact_id"]
    publisher = signed_publishers[artifact_id]
    if fresh_publishers[artifact_id].sha256 != publisher.sha256:
        raise Phase0Error("publisher evidence changed after authorization")
    observation = _json_object(Path(args.staging_observation))
    authorization = _staging_authorization(
        args.authorization,
        policy=_json_object(Path(args.policy)),
        source_registry=registry,
        publisher_receipt=publisher,
        staging_observation=observation,
        evaluation_gate=signed_gate,
    )
    result = acquire_to_staging(
        source_registry=registry,
        publisher_receipt=publisher,
        authorization=authorization,
        staging_observation=observation,
        minimum_free_bytes=args.minimum_free_bytes,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _staging_audit(args: argparse.Namespace) -> int:
    registry = _lineage(args.source_registry, "sources").tip
    result = audit_staged_artifact(
        source_registry=registry,
        acquisition_receipt=_json_object(Path(args.acquisition_receipt)),
        staging_observation=_json_object(Path(args.staging_observation)),
        audited_at=args.audited_at,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _staging_inventory(args: argparse.Namespace) -> int:
    registry = _lineage(args.source_registry, "sources").tip
    result = inventory_staged_artifact(
        source_registry=registry,
        artifact_audit=_json_object(Path(args.artifact_audit)),
        staging_observation=_json_object(Path(args.staging_observation)),
        started_at=args.started_at,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _rights_scaffold(args: argparse.Namespace) -> int:
    registry = _lineage(args.source_registry, "sources").tip
    source_matches = [
        item for item in registry["sources"] if item["source_id"] == args.source_id
    ]
    if len(source_matches) != 1:
        raise Phase0Error("source must resolve exactly once")
    result = scaffold_publication_rights_payload(
        authority_policy=_json_object(Path(args.authority_policy)),
        destination_policy=_json_object(Path(args.destination_policy)),
        source_id=args.source_id,
        source_entry=source_matches[0],
        evidence_bundle=load_verified_bundle(Path(args.bundle)),
        assessment_id=args.assessment_id,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _rights_verify(args: argparse.Namespace) -> int:
    registry = _lineage(args.source_registry, "sources").tip
    sources = [
        item for item in registry["sources"] if item["source_id"] == args.source_id
    ]
    if len(sources) != 1:
        raise Phase0Error("source must resolve exactly once")
    verified = _rights(
        args.rights,
        authority_policy=_json_object(Path(args.authority_policy)),
        destination_policy=_json_object(Path(args.destination_policy)),
        source=sources[0],
        evaluated_at=args.evaluated_at,
    )
    _write_json(Path(args.output), verified.receipt)
    _emit(verified.receipt)
    return 0


def _destination_observe(args: argparse.Namespace) -> int:
    prior_receipts = [
        _json_object(Path(path)) for path in args.prior_publication_receipt
    ]
    prior_manifests = [
        _json_object(Path(path)) for path in args.prior_publication_manifest
    ]
    prior_authorizations: list[VerifiedPublicationAuthorization] = []
    if args.prior_publication_authorization:
        if not args.authority_policy:
            raise Phase0Error(
                "prior publication authorization requires --authority-policy"
            )
        authority_policy = _json_object(Path(args.authority_policy))
        destination_policy = _json_object(Path(args.destination_policy))
        for value in args.prior_publication_authorization:
            payload_path, signature_path, key_path = _parts(
                value, "--prior-publication-authorization", 3
            )
            prior_authorizations.append(
                verify_historical_publication_authorization(
                    _json_object(Path(payload_path)),
                    signature=_read_file(
                        Path(signature_path),
                        MAX_OPENPGP_EVIDENCE_BYTES,
                        "historical publication signature",
                    ),
                    public_key=_read_file(
                        Path(key_path),
                        MAX_OPENPGP_EVIDENCE_BYTES,
                        "historical publication public key",
                    ),
                    authority_policy=authority_policy,
                    destination_policy=destination_policy,
                    approved_authority_policy_sha256=(
                        APPROVED_PUBLICATION_AUTHORITY_POLICY_SHA256
                    ),
                    approved_destination_policy_sha256=(
                        APPROVED_DESTINATION_POLICY_SHA256
                    ),
                    signature_verifier=_verify_detached_signature_gpg,
                )
            )
    if not (len(prior_receipts) == len(prior_authorizations) == len(prior_manifests)):
        raise Phase0Error(
            "prior receipts require exactly one signed authorization and manifest each"
        )
    result = observe_destination(
        policy=_json_object(Path(args.destination_policy)),
        client=HuggingFaceHubClient(),
        observed_at=_utc_now(),
        prior_publication_receipts=prior_receipts,
        prior_publication_authorizations=prior_authorizations,
        prior_publication_manifests=prior_manifests,
        approved_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _obligations(args: argparse.Namespace) -> int:
    registry = _lineage(args.source_registry, "sources").tip
    source, _ = _lookup(registry, args.artifact_id)
    authority_policy = _json_object(Path(args.authority_policy))
    destination_policy = _json_object(Path(args.destination_policy))
    rights = _rights(
        args.rights,
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        source=source,
        evaluated_at=args.evaluated_at,
    )
    implementations = [_json_object(Path(path)) for path in args.implementation]
    controls = [
        sha256_bytes(_read_file(Path(path), 16 * 1024 * 1024, "operational evidence"))
        for path in args.operational_evidence
    ]
    result = build_obligation_manifest(
        rights=rights,
        destination_policy=destination_policy,
        destination_observation=_json_object(Path(args.destination_observation)),
        manifest_id=args.manifest_id,
        implementation_refs=implementations,
        operational_evidence_sha256s=controls,
        assembled_at=args.assembled_at,
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _clearance(args: argparse.Namespace) -> int:
    lineage, evaluation_gate, publishers = _reproduced_graph(
        args, evaluated_at=args.cleared_at
    )
    registry = lineage.tip
    source, _ = _lookup(registry, args.artifact_id)
    authority_policy = _json_object(Path(args.authority_policy))
    destination_policy = _json_object(Path(args.destination_policy))
    rights = _rights(
        args.rights,
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        source=source,
        evaluated_at=args.cleared_at,
    )
    result = make_artifact_publication_clearance(
        source_registry=registry,
        artifact_id=args.artifact_id,
        artifact_audit=_json_object(Path(args.artifact_audit)),
        structural_inventory=_json_object(Path(args.structural_inventory)),
        publisher_receipt=publishers[args.artifact_id],
        rights=rights,
        obligations=_json_object(Path(args.obligations)),
        evaluation_gate=evaluation_gate,
        quarantine_index=_json_object(Path(args.quarantine)),
        cleared_at=args.cleared_at,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _publication_context(
    args: argparse.Namespace, *, evaluated_at: str | None = None
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    VerifiedPublicationRights,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    clearance = _json_object(Path(args.clearance))
    lineage, evaluation_gate, publishers = _reproduced_graph(
        args, evaluated_at=clearance["cleared_at"]
    )
    registry = lineage.tip
    source, artifact = _lookup(registry, args.artifact_id)
    authority_policy = _json_object(Path(args.authority_policy))
    destination_policy = _json_object(Path(args.destination_policy))
    observation = _json_object(Path(args.destination_observation))
    rights = _rights(
        args.rights,
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        source=source,
        evaluated_at=evaluated_at or args.evaluated_at,
    )
    obligations = _json_object(Path(args.obligations))
    audit = _json_object(Path(args.artifact_audit))
    artifact_manifest = _json_object(Path(args.manifest))
    expected_clearance = make_artifact_publication_clearance(
        source_registry=registry,
        artifact_id=args.artifact_id,
        artifact_audit=audit,
        structural_inventory=_json_object(Path(args.structural_inventory)),
        publisher_receipt=publishers[args.artifact_id],
        rights=rights,
        obligations=obligations,
        evaluation_gate=evaluation_gate,
        quarantine_index=_json_object(Path(args.quarantine)),
        cleared_at=clearance["cleared_at"],
    )
    if expected_clearance != clearance:
        raise Phase0Error(
            "artifact clearance does not reproduce from its evidence graph"
        )
    return (
        registry,
        artifact,
        authority_policy,
        destination_policy,
        rights,
        observation,
        clearance,
        obligations,
        audit,
        artifact_manifest,
    )


def _publication_authorization_payload_handler(args: argparse.Namespace) -> int:
    (
        registry,
        artifact,
        authority_policy,
        destination_policy,
        rights,
        observation,
        clearance,
        obligations,
        audit,
        artifact_manifest,
    ) = _publication_context(args)
    result = make_publication_authorization_payload(
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        destination_observation=observation,
        source_registry_sha256=canonical_sha256(registry),
        artifact_id=args.artifact_id,
        artifact_entry_sha256=canonical_sha256(artifact),
        artifact_clearance=clearance,
        rights=rights,
        obligations=obligations,
        artifact_audit=audit,
        artifact_manifest=artifact_manifest,
        authorization_id=args.authorization_id,
        authorized_at=args.authorized_at,
        valid_until=args.valid_until,
        authorizer_id=args.authorizer_id,
        signing_key_fingerprint=args.signing_key_fingerprint,
        approved_authority_policy_sha256=(
            APPROVED_PUBLICATION_AUTHORITY_POLICY_SHA256 or ""
        ),
        approved_destination_policy_sha256=(APPROVED_DESTINATION_POLICY_SHA256 or ""),
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _verified_publication_context(
    args: argparse.Namespace, *, evaluated_at: str | None = None
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], VerifiedPublicationAuthorization
]:
    (
        registry,
        artifact,
        authority_policy,
        destination_policy,
        rights,
        observation,
        clearance,
        obligations,
        audit,
        artifact_manifest,
    ) = _publication_context(args, evaluated_at=evaluated_at)
    verified = _publication_authorization(
        args.authorization,
        authority_policy=authority_policy,
        destination_policy=destination_policy,
        destination_observation=observation,
        artifact_clearance=clearance,
        rights=rights,
        obligations=obligations,
        artifact_audit=audit,
        artifact_manifest=artifact_manifest,
    )
    return registry, artifact, destination_policy, verified


def _publication_authorization_verify_handler(args: argparse.Namespace) -> int:
    _, _, _, verified = _verified_publication_context(args)
    _write_json(Path(args.output), verified.receipt)
    _emit(verified.receipt)
    return 0


def _local_path(
    registry: dict[str, Any], artifact_id: str, staging_observation: dict[str, Any]
) -> Path:
    validate_staging_observation(staging_observation)
    _, artifact = _lookup(registry, artifact_id)
    root = Path(staging_observation["root_path"])
    return root / artifact["filename"]


def _publication_inventory(args: argparse.Namespace) -> int:
    registry = _lineage(args.source_registry, "sources").tip
    _, artifact = _lookup(registry, args.artifact_id)
    observation = _json_object(Path(args.staging_observation))
    result = inventory_publication_artifact(
        policy=_json_object(Path(args.destination_policy)),
        artifact_id=args.artifact_id,
        source_registry_sha256=canonical_sha256(registry),
        artifact_entry_sha256=canonical_sha256(artifact),
        local_path=_local_path(registry, args.artifact_id, observation),
        local_audit=_json_object(Path(args.artifact_audit)),
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _publication_upload(args: argparse.Namespace) -> int:
    registry, _, policy, authorization = _verified_publication_context(
        args, evaluated_at=_utc_now()
    )
    result = publish_artifact(
        policy=policy,
        destination_observation=_json_object(Path(args.destination_observation)),
        authorization=authorization,
        artifact_clearance=_json_object(Path(args.clearance)),
        artifact_manifest=_json_object(Path(args.manifest)),
        local_path=_local_path(
            registry,
            args.artifact_id,
            _json_object(Path(args.staging_observation)),
        ),
        client=HuggingFaceHubClient(),
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _publication_recover(args: argparse.Namespace) -> int:
    _, _, policy, authorization = _verified_publication_context(args)
    result = recover_publication(
        policy=policy,
        authorization=authorization,
        artifact_clearance=_json_object(Path(args.clearance)),
        destination_observation=_json_object(Path(args.destination_observation)),
        manifest=_json_object(Path(args.manifest)),
        client=HuggingFaceHubClient(),
        started_at=args.started_at,
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _source_admission(args: argparse.Namespace) -> int:
    registry = _lineage(args.source_registry, "sources").tip
    result = make_source_admission(
        source_registry=registry,
        source_id=args.source_id,
        clearances=[_json_object(Path(path)) for path in args.clearance],
        publication_receipts=[
            _json_object(Path(path)) for path in args.publication_receipt
        ],
        assessed_at=args.assessed_at,
        assessor=args.assessor,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _gate_v4_3(args: argparse.Namespace) -> int:
    source_lineage, evaluation_gate, _publishers = _reproduced_graph(
        args,
        evaluated_at=args.evaluated_at,
        require_complete_publishers=False,
    )
    evaluation_lineage = _lineage(args.evaluation_registry, "evaluations")
    policy = _json_object(Path(args.policy)) if args.policy else None
    observation = (
        _json_object(Path(args.staging_observation))
        if args.staging_observation
        else None
    )
    authorizations: list[VerifiedStagingAuthorization] = []
    if args.staging_authorization:
        if policy is None or observation is None:
            raise Phase0Error("staging authorization verification lacks its graph")
        for value in args.staging_authorization:
            payload, signature, key = _parts(value, "--staging-authorization", 3)
            payload_object = _json_object(Path(payload))
            artifact_id = payload_object["artifact_id"]
            signed_lineage, signed_gate, signed_publishers = _reproduced_graph(
                args, evaluated_at=payload_object["authorized_at"]
            )
            if signed_lineage.sha256 != source_lineage.sha256:
                raise Phase0Error("authorization uses another source lineage")
            authorizations.append(
                _staging_authorization(
                    f"{payload}={signature}={key}",
                    policy=policy,
                    source_registry=source_lineage.tip,
                    publisher_receipt=signed_publishers[artifact_id],
                    staging_observation=observation,
                    evaluation_gate=signed_gate,
                )
            )
    result = evaluate_gate_v4_3(
        evaluated_at=args.evaluated_at,
        source_lineage=source_lineage,
        evaluation_lineage=evaluation_lineage,
        evaluation_gate=evaluation_gate,
        staging_observation=observation,
        authorizations=authorizations,
        acquisitions=[_json_object(Path(path)) for path in args.acquisition],
        audits=[_json_object(Path(path)) for path in args.artifact_audit],
        inventories=[_json_object(Path(path)) for path in args.staging_inventory],
        clearances=[_json_object(Path(path)) for path in args.artifact_clearance],
        publication_receipts=[
            _json_object(Path(path)) for path in args.hf_publication_receipt
        ],
        admissions=[_json_object(Path(path)) for path in args.hf_admission],
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0 if result["foundation_transform_ready"] else 2


def _publication_gate(args: argparse.Namespace) -> int:
    policy = _json_object(Path(args.destination_policy))
    observation = (
        _json_object(Path(args.destination_observation))
        if args.destination_observation
        else None
    )
    clearance = _json_object(Path(args.clearance)) if args.clearance else None
    rights = None
    authorization = None
    if args.rights:
        if not all((args.authority_policy, args.source_registry, args.artifact_id)):
            raise Phase0Error("rights verification lacks policy/source inputs")
        registry = _lineage(args.source_registry, "sources").tip
        source, _ = _lookup(registry, args.artifact_id)
        rights = _rights(
            args.rights,
            authority_policy=_json_object(Path(args.authority_policy)),
            destination_policy=policy,
            source=source,
            evaluated_at=args.evaluated_at,
        )
    obligations = _json_object(Path(args.obligations)) if args.obligations else None
    if args.authorization:
        required = (
            rights,
            observation,
            clearance,
            obligations,
            args.artifact_audit,
            args.manifest,
            args.authority_policy,
        )
        if not all(required):
            raise Phase0Error("publication authorization verification lacks its graph")
        authorization = _publication_authorization(
            args.authorization,
            authority_policy=_json_object(Path(args.authority_policy)),
            destination_policy=policy,
            destination_observation=observation,
            artifact_clearance=clearance,
            rights=rights,
            obligations=obligations,
            artifact_audit=_json_object(Path(args.artifact_audit)),
            artifact_manifest=_json_object(Path(args.manifest)),
        )
    result = evaluate_publication_gate(
        evaluated_at=args.evaluated_at,
        destination_policy=policy,
        destination_observation=observation,
        rights=rights,
        obligations=obligations,
        clearance=clearance,
        authorization=authorization,
        publication_receipt=(
            _json_object(Path(args.publication_receipt))
            if args.publication_receipt
            else None
        ),
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
    )
    _write_json(Path(args.output), result)
    _emit(result)
    return 0 if result["publication_complete"] else 2


def _add_lineage(parser: argparse.ArgumentParser, *, evaluations: bool = False) -> None:
    parser.add_argument("--source-registry", action="append", required=True)
    if evaluations:
        parser.add_argument("--evaluation-registry", action="append", required=True)


def _add_v4_1_graph(parser: argparse.ArgumentParser) -> None:
    _add_lineage(parser, evaluations=True)
    parser.add_argument("--drive-observation")
    parser.add_argument("--storage-attestation")
    parser.add_argument(
        "--publisher", action="append", default=[], metavar="STATEMENT=RECEIPT"
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


def _add_rights_context(
    parser: argparse.ArgumentParser,
    *,
    full_evaluation_graph: bool = False,
    include_evaluated_at: bool = True,
) -> None:
    parser.add_argument("--authority-policy", required=True)
    parser.add_argument("--destination-policy", required=True)
    if full_evaluation_graph:
        _add_v4_1_graph(parser)
    else:
        _add_lineage(parser)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument(
        "--rights", required=True, metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY=BUNDLE"
    )
    if include_evaluated_at:
        parser.add_argument("--evaluated-at", required=True)


def _add_publication_context(
    parser: argparse.ArgumentParser, *, include_evaluated_at: bool = True
) -> None:
    _add_rights_context(
        parser,
        full_evaluation_graph=True,
        include_evaluated_at=include_evaluated_at,
    )
    parser.add_argument("--destination-observation", required=True)
    parser.add_argument("--clearance", required=True)
    parser.add_argument("--obligations", required=True)
    parser.add_argument("--artifact-audit", required=True)
    parser.add_argument("--structural-inventory", required=True)
    parser.add_argument("--manifest", required=True)


def add_v4_3_commands(
    *,
    commands: Any,
    registry_commands: Any,
    source_commands: Any,
    licence_commands: Any,
) -> None:
    validate = registry_commands.add_parser("validate-v4.3")
    validate.add_argument("--phase-schema-root")
    validate.add_argument("--publication-schema-root")
    validate.add_argument(
        "--instance",
        action="append",
        default=[],
        metavar="PATH=FAMILY=SCHEMA",
    )
    validate.set_defaults(handler=_registry_validate)

    staging_init = source_commands.add_parser("staging-init-v4.3")
    staging_init.add_argument("--root", required=True)
    staging_init.add_argument("--observation-id", required=True)
    staging_init.add_argument("--created-at", required=True)
    staging_init.add_argument("--output", required=True)
    staging_init.set_defaults(handler=_staging_init)
    staging_observe = source_commands.add_parser("staging-observe-v4.3")
    staging_observe.add_argument("--root", required=True)
    staging_observe.add_argument("--observation-id", required=True)
    staging_observe.add_argument("--observed-at", required=True)
    staging_observe.add_argument("--output", required=True)
    staging_observe.set_defaults(handler=_staging_observe)

    staging_payload = source_commands.add_parser("authorization-payload-v4.3")
    staging_payload.add_argument("--policy", required=True)
    _add_v4_1_graph(staging_payload)
    staging_payload.add_argument("--artifact-id", required=True)
    staging_payload.add_argument("--staging-observation", required=True)
    staging_payload.add_argument("--authorization-id", required=True)
    staging_payload.add_argument("--byte-ceiling", required=True, type=int)
    staging_payload.add_argument("--authorized-at", required=True)
    staging_payload.add_argument("--valid-until", required=True)
    staging_payload.add_argument("--authorizer-id", required=True)
    staging_payload.add_argument("--signing-key-fingerprint", required=True)
    staging_payload.add_argument("--output", required=True)
    staging_payload.set_defaults(handler=_staging_authorization_payload)

    staging_verify = source_commands.add_parser("authorization-verify-v4.3")
    staging_verify.add_argument("--policy", required=True)
    _add_v4_1_graph(staging_verify)
    staging_verify.add_argument("--staging-observation", required=True)
    staging_verify.add_argument(
        "--authorization", required=True, metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY"
    )
    staging_verify.add_argument("--verified-at", required=True)
    staging_verify.add_argument("--output", required=True)
    staging_verify.set_defaults(handler=_staging_authorization_verify)

    acquire = source_commands.add_parser("acquire-v4.3")
    acquire.add_argument("--policy", required=True)
    _add_v4_1_graph(acquire)
    acquire.add_argument("--staging-observation", required=True)
    acquire.add_argument(
        "--authorization", required=True, metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY"
    )
    acquire.add_argument("--minimum-free-bytes", required=True, type=int)
    acquire.add_argument("--output", required=True)
    acquire.set_defaults(handler=_staging_acquire)

    audit = source_commands.add_parser("audit-v4.3")
    _add_lineage(audit)
    audit.add_argument("--acquisition-receipt", required=True)
    audit.add_argument("--staging-observation", required=True)
    audit.add_argument("--audited-at", required=True)
    audit.add_argument("--output", required=True)
    audit.set_defaults(handler=_staging_audit)
    inventory = source_commands.add_parser("count-v4.3")
    _add_lineage(inventory)
    inventory.add_argument("--artifact-audit", required=True)
    inventory.add_argument("--staging-observation", required=True)
    inventory.add_argument("--started-at", required=True)
    inventory.add_argument("--output", required=True)
    inventory.set_defaults(handler=_staging_inventory)

    rights_scaffold = licence_commands.add_parser("publication-scaffold-v1")
    rights_scaffold.add_argument("--authority-policy", required=True)
    rights_scaffold.add_argument("--destination-policy", required=True)
    _add_lineage(rights_scaffold)
    rights_scaffold.add_argument("--source-id", required=True)
    rights_scaffold.add_argument("--bundle", required=True)
    rights_scaffold.add_argument("--assessment-id", required=True)
    rights_scaffold.add_argument("--output", required=True)
    rights_scaffold.set_defaults(handler=_rights_scaffold)
    rights_verify = licence_commands.add_parser("publication-verify-v1")
    rights_verify.add_argument("--authority-policy", required=True)
    rights_verify.add_argument("--destination-policy", required=True)
    _add_lineage(rights_verify)
    rights_verify.add_argument("--source-id", required=True)
    rights_verify.add_argument(
        "--rights", required=True, metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY=BUNDLE"
    )
    rights_verify.add_argument("--evaluated-at", required=True)
    rights_verify.add_argument("--output", required=True)
    rights_verify.set_defaults(handler=_rights_verify)

    publication = commands.add_parser("publication")
    publication_commands = publication.add_subparsers(
        dest="publication_command", required=True
    )
    contracts = publication_commands.add_parser("contracts-v1")
    contracts.set_defaults(
        handler=lambda _args: _emit(validate_publication_schema_lock_v1()) or 0
    )
    observe = publication_commands.add_parser("observe-v1")
    observe.add_argument("--destination-policy", required=True)
    observe.add_argument("--authority-policy")
    observe.add_argument("--prior-publication-receipt", action="append", default=[])
    observe.add_argument("--prior-publication-manifest", action="append", default=[])
    observe.add_argument(
        "--prior-publication-authorization",
        action="append",
        default=[],
        metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY",
    )
    observe.add_argument("--output", required=True)
    observe.set_defaults(handler=_destination_observe)
    obligation = publication_commands.add_parser("obligations-v1")
    _add_rights_context(obligation)
    obligation.add_argument("--destination-observation", required=True)
    obligation.add_argument("--manifest-id", required=True)
    obligation.add_argument("--implementation", action="append", default=[])
    obligation.add_argument("--operational-evidence", action="append", default=[])
    obligation.add_argument("--assembled-at", required=True)
    obligation.add_argument("--output", required=True)
    obligation.set_defaults(handler=_obligations)

    clearance = source_commands.add_parser("clearance-v4.3")
    _add_rights_context(clearance, full_evaluation_graph=True)
    clearance.add_argument("--artifact-audit", required=True)
    clearance.add_argument("--structural-inventory", required=True)
    clearance.add_argument("--obligations", required=True)
    clearance.add_argument("--cleared-at", required=True)
    clearance.add_argument("--output", required=True)
    clearance.set_defaults(handler=_clearance)

    auth_payload = publication_commands.add_parser("authorization-payload-v1")
    _add_publication_context(auth_payload)
    auth_payload.add_argument("--authorization-id", required=True)
    auth_payload.add_argument("--authorized-at", required=True)
    auth_payload.add_argument("--valid-until", required=True)
    auth_payload.add_argument("--authorizer-id", required=True)
    auth_payload.add_argument("--signing-key-fingerprint", required=True)
    auth_payload.add_argument("--output", required=True)
    auth_payload.set_defaults(handler=_publication_authorization_payload_handler)
    auth_verify = publication_commands.add_parser("authorization-verify-v1")
    _add_publication_context(auth_verify)
    auth_verify.add_argument(
        "--authorization", required=True, metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY"
    )
    auth_verify.add_argument("--output", required=True)
    auth_verify.set_defaults(handler=_publication_authorization_verify_handler)
    pub_inventory = publication_commands.add_parser("inventory-v1")
    pub_inventory.add_argument("--destination-policy", required=True)
    _add_lineage(pub_inventory)
    pub_inventory.add_argument("--artifact-id", required=True)
    pub_inventory.add_argument("--staging-observation", required=True)
    pub_inventory.add_argument("--artifact-audit", required=True)
    pub_inventory.add_argument("--output", required=True)
    pub_inventory.set_defaults(handler=_publication_inventory)
    upload = publication_commands.add_parser("upload-v1")
    _add_publication_context(upload, include_evaluated_at=False)
    upload.add_argument(
        "--authorization", required=True, metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY"
    )
    upload.add_argument("--staging-observation", required=True)
    upload.add_argument("--output", required=True)
    upload.set_defaults(handler=_publication_upload)
    recover = publication_commands.add_parser("recover-v1")
    _add_publication_context(recover)
    recover.add_argument(
        "--authorization", required=True, metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY"
    )
    recover.add_argument("--started-at", required=True)
    recover.add_argument("--output", required=True)
    recover.set_defaults(handler=_publication_recover)

    admission = source_commands.add_parser("admission-v4.3")
    _add_lineage(admission)
    admission.add_argument("--source-id", required=True)
    admission.add_argument("--clearance", action="append", required=True)
    admission.add_argument("--publication-receipt", action="append", required=True)
    admission.add_argument("--assessed-at", required=True)
    admission.add_argument("--assessor", required=True)
    admission.add_argument("--output", required=True)
    admission.set_defaults(handler=_source_admission)

    phase_gate = commands.add_parser("gate-v4.3")
    _add_v4_1_graph(phase_gate)
    phase_gate.add_argument("--policy")
    phase_gate.add_argument("--staging-observation")
    phase_gate.add_argument(
        "--staging-authorization",
        action="append",
        default=[],
        metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY",
    )
    phase_gate.add_argument("--acquisition", action="append", default=[])
    phase_gate.add_argument("--artifact-audit", action="append", default=[])
    phase_gate.add_argument("--staging-inventory", action="append", default=[])
    phase_gate.add_argument("--artifact-clearance", action="append", default=[])
    phase_gate.add_argument("--hf-publication-receipt", action="append", default=[])
    phase_gate.add_argument("--hf-admission", action="append", default=[])
    phase_gate.add_argument("--evaluated-at", required=True)
    phase_gate.add_argument("--output", required=True)
    phase_gate.set_defaults(handler=_gate_v4_3)

    pub_gate = commands.add_parser("publication-gate-v1")
    pub_gate.add_argument("--destination-policy", required=True)
    pub_gate.add_argument("--destination-observation")
    pub_gate.add_argument("--authority-policy")
    pub_gate.add_argument("--source-registry", action="append")
    pub_gate.add_argument("--artifact-id")
    pub_gate.add_argument("--rights", metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY=BUNDLE")
    pub_gate.add_argument("--obligations")
    pub_gate.add_argument("--clearance")
    pub_gate.add_argument("--artifact-audit")
    pub_gate.add_argument("--manifest")
    pub_gate.add_argument("--authorization", metavar="PAYLOAD=SIGNATURE=PUBLIC_KEY")
    pub_gate.add_argument("--publication-receipt")
    pub_gate.add_argument("--evaluated-at", required=True)
    pub_gate.add_argument("--output", required=True)
    pub_gate.set_defaults(handler=_publication_gate)
