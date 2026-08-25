"""Leakage-safe capture and packet preparation for the licence catalogue."""

from __future__ import annotations

import os
import stat
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from hippocampus_foundation.licensing import (
    FORBIDDEN_PATH_SUFFIXES,
    build_evidence_bundle,
    capture_https_document,
    make_pending_assessment,
    verify_evidence_bundle,
)
from hippocampus_foundation.phase0.canonical import (
    canonical_sha256,
    dump_pretty,
    load_json,
)
from hippocampus_foundation.phase0.errors import IntegrityError, ValidationError
from hippocampus_foundation.phase0.evaluation_firewall import (
    validate_evaluation_registry_v4,
    validate_source_registry_v4,
)

CATALOGUE_VERSION = "1.0.0"
_FORBIDDEN_URL_MARKERS = (
    "evidencebench_test_set",
    "dev-labels",
    "test.json",
    "test.jsonl",
    "validation.jsonl",
)


def _write_json_exclusive(path: Path, value: Any, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise IntegrityError(f"refusing to overwrite catalogue output: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(dump_pretty(value))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def load_catalogue(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError("licence evidence catalogue must be an object")
    return value


def _registered_subjects(
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    encoder_spec: dict[str, Any],
) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    result: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for source in source_registry["sources"]:
        if source["role"] == "foundation_candidate":
            result[("source", source["source_id"])] = (
                source["licence_review_id"],
                source,
            )
    for dataset in evaluation_registry["datasets"]:
        result[("evaluation", dataset["dataset_id"])] = (
            dataset["licence_review_id"],
            dataset,
        )
    result[("encoder", encoder_spec["encoder_id"])] = (
        encoder_spec["licence_review_id"],
        encoder_spec,
    )
    return result


def validate_catalogue(
    catalogue: dict[str, Any],
    *,
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    encoder_spec: dict[str, Any],
) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    if catalogue.get("schema_version") != CATALOGUE_VERSION:
        raise ValidationError("licence evidence catalogue version mismatch")
    if catalogue.get("record_kind") != "licence_evidence_catalogue":
        raise ValidationError("unexpected licence evidence catalogue kind")
    if catalogue.get("contains_evaluation_content") is not False:
        raise ValidationError("licence catalogue may not contain evaluation content")
    subjects = catalogue.get("subjects")
    if not isinstance(subjects, list):
        raise ValidationError("licence catalogue subjects must be an array")
    registered = _registered_subjects(
        source_registry, evaluation_registry, encoder_spec
    )
    observed: set[tuple[str, str]] = set()
    review_ids: set[str] = set()
    for subject in subjects:
        if not isinstance(subject, dict):
            raise ValidationError("licence catalogue subject must be an object")
        key = (subject.get("subject_kind"), subject.get("subject_id"))
        if key in observed:
            raise ValidationError(f"duplicate licence catalogue subject: {key}")
        if key not in registered:
            raise ValidationError(f"unregistered licence catalogue subject: {key}")
        observed.add(key)
        expected_review, _ = registered[key]
        if subject.get("review_id") != expected_review:
            raise ValidationError(f"licence catalogue review binding mismatch: {key}")
        if expected_review in review_ids:
            raise ValidationError(
                f"duplicate licence catalogue review ID: {expected_review}"
            )
        review_ids.add(expected_review)
        required_uses = subject.get("required_uses")
        if (
            not isinstance(required_uses, list)
            or not required_uses
            or len(required_uses) != len(set(required_uses))
        ):
            raise ValidationError(f"invalid catalogue use scope: {key}")
        documents = subject.get("documents")
        findings = subject.get("findings")
        if not isinstance(documents, list) or not isinstance(findings, list):
            raise ValidationError(f"invalid catalogue evidence lists: {key}")
        document_ids: set[str] = set()
        for document in documents:
            document_id = document.get("document_id")
            if not isinstance(document_id, str) or document_id in document_ids:
                raise ValidationError(f"invalid or duplicate catalogue document: {key}")
            document_ids.add(document_id)
            url = document.get("url")
            parsed = urllib.parse.urlparse(url if isinstance(url, str) else "")
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValidationError(
                    f"catalogue evidence URL must use HTTPS: {key}/{document_id}"
                )
            allow_hosts = document.get("allow_hosts")
            if not isinstance(allow_hosts, list) or parsed.hostname not in allow_hosts:
                raise ValidationError(
                    f"catalogue evidence host is not explicitly allowed: {key}/{document_id}"
                )
            lowered = parsed.path.casefold()
            if any(lowered.endswith(suffix) for suffix in FORBIDDEN_PATH_SUFFIXES):
                raise ValidationError(
                    f"catalogue references an archive or label-bearing file: {key}/{document_id}"
                )
            if any(marker in lowered for marker in _FORBIDDEN_URL_MARKERS):
                raise ValidationError(
                    f"catalogue references held-out evaluation content: {key}/{document_id}"
                )
        finding_ids = [
            finding.get("finding_id")
            for finding in findings
            if isinstance(finding, dict)
        ]
        if len(finding_ids) != len(findings) or len(finding_ids) != len(
            set(finding_ids)
        ):
            raise ValidationError(f"invalid or duplicate catalogue findings: {key}")
    if observed != set(registered):
        missing = sorted(set(registered) - observed)
        extra = sorted(observed - set(registered))
        raise ValidationError(
            f"licence catalogue subject coverage mismatch: missing={missing}, extra={extra}"
        )
    return registered


def capture_catalogue(
    catalogue: dict[str, Any],
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Capture explicit catalogue URLs; existing complete pairs are verified later."""

    captured = 0
    retained = 0
    pending: list[tuple[dict[str, Any], Path, Path]] = []
    for subject in catalogue["subjects"]:
        subject_root = output_root / subject["review_id"]
        for document in subject["documents"]:
            output = subject_root / f"{document['document_id']}.snapshot"
            receipt = subject_root / f"{document['document_id']}.document.json"
            if (
                output.exists()
                and receipt.exists()
                and not output.is_symlink()
                and not receipt.is_symlink()
            ):
                retained += 1
                continue
            if (
                output.exists()
                or receipt.exists()
                or output.is_symlink()
                or receipt.is_symlink()
            ):
                raise IntegrityError(
                    f"partial licence evidence capture requires manual inspection: {document['document_id']}"
                )
            pending.append((document, output, receipt))

    failures: list[str] = []
    with ThreadPoolExecutor(
        max_workers=6, thread_name_prefix="licence-capture"
    ) as executor:
        futures = {
            executor.submit(
                capture_https_document,
                url=document["url"],
                document_id=document["document_id"],
                role=document["role"],
                source_kind=document["source_kind"],
                output=output,
                receipt=receipt,
                allowed_hosts=document["allow_hosts"],
                revision=document["revision"],
                mutable=document["mutable"],
            ): document["document_id"]
            for document, output, receipt in pending
        }
        for future in as_completed(futures):
            document_id = futures[future]
            try:
                future.result()
                captured += 1
            except Exception as exc:  # noqa: BLE001 - aggregate concurrent capture failures
                failures.append(f"{document_id}:{type(exc).__name__}:{exc}")
    if failures:
        raise ValidationError(
            "one or more allowlisted evidence captures failed: "
            + "; ".join(sorted(failures))
        )
    return {"ok": True, "captured": captured, "retained": retained}


def _receipt_matches_catalogue(
    receipt: dict[str, Any], document: dict[str, Any]
) -> None:
    expected = {
        "document_id": document["document_id"],
        "role": document["role"],
        "source_kind": document["source_kind"],
        "original_url": document["url"],
        "revision": document["revision"],
        "mutable": document["mutable"],
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ValidationError(
                f"captured document catalogue mismatch: {document['document_id']}:{field}"
            )


def prepare_catalogue_packets(
    catalogue: dict[str, Any],
    *,
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    encoder_spec: dict[str, Any],
    evidence_root: Path,
    audit_index_path: Path,
    assembled_at: str,
) -> dict[str, Any]:
    registered = validate_catalogue(
        catalogue,
        source_registry=source_registry,
        evaluation_registry=evaluation_registry,
        encoder_spec=encoder_spec,
    )
    public_subjects: list[dict[str, Any]] = []
    for subject in catalogue["subjects"]:
        key = (subject["subject_kind"], subject["subject_id"])
        _, entry = registered[key]
        subject_root = evidence_root / subject["review_id"]
        bundle_path = subject_root / "bundle.json"
        assessment_path = subject_root / "assessment.pending.json"
        if bundle_path.exists() or assessment_path.exists():
            raise IntegrityError(
                f"refusing to overwrite licence packet: {subject['review_id']}"
            )
        # An evidence bundle with zero captured documents is a valid fail-closed
        # packet, but its verification root must still exist and be a real
        # directory.  Refuse links so packet paths cannot be redirected.
        subject_root.mkdir(parents=True, exist_ok=True)
        if subject_root.is_symlink() or not subject_root.is_dir():
            raise IntegrityError(
                f"licence packet root is not a real directory: {subject_root}"
            )

        documents = []
        findings = [dict(finding) for finding in subject["findings"]]
        missing_documents = []
        for document in subject["documents"]:
            receipt_path = subject_root / f"{document['document_id']}.document.json"
            snapshot_path = subject_root / f"{document['document_id']}.snapshot"
            if not receipt_path.exists() or not snapshot_path.exists():
                missing_documents.append(document["document_id"])
                findings.append(
                    {
                        "finding_id": f"capture-missing-{document['document_id']}",
                        "category": "other",
                        "blocking": True,
                        "summary": "A mandatory allowlisted evidence document was not captured.",
                    }
                )
                continue
            receipt = load_json(receipt_path)
            if not isinstance(receipt, dict):
                raise ValidationError(
                    f"evidence receipt must be an object: {receipt_path}"
                )
            _receipt_matches_catalogue(receipt, document)
            documents.append(receipt)

        bundle = build_evidence_bundle(
            bundle_id=f"{subject['review_id']}-evidence",
            review_id=subject["review_id"],
            subject_kind=subject["subject_kind"],
            subject_id=subject["subject_id"],
            subject_binding_sha256=canonical_sha256(entry),
            documents=documents,
            findings=findings,
            assembled_at=assembled_at,
        )
        verified = verify_evidence_bundle(bundle, subject_root)
        assessment = make_pending_assessment(bundle)
        _write_json_exclusive(bundle_path, bundle, mode=0o600)
        _write_json_exclusive(assessment_path, assessment, mode=0o600)
        public_subjects.append(
            {
                "subject_kind": subject["subject_kind"],
                "subject_id": subject["subject_id"],
                "review_id": subject["review_id"],
                "bundle_sha256": verified.sha256,
                "captured_document_count": len(documents),
                "missing_document_count": len(missing_documents),
                "finding_categories": sorted(
                    {finding["category"] for finding in findings}
                ),
                "decision": "pending",
                "commercial_context": "unclear",
                "training_authorized": False,
            }
        )
    audit_index = {
        "schema_version": CATALOGUE_VERSION,
        "record_kind": "licence_evidence_audit_index",
        "generated_at": assembled_at,
        "contains_evaluation_content": False,
        "subjects": public_subjects,
    }
    _write_json_exclusive(audit_index_path, audit_index, mode=0o644)
    return audit_index


def _read_verified_capture(path: Path, expected_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise IntegrityError(
            f"cannot open verified capture safely: {path}: {exc}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise IntegrityError(f"verified capture is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            body = handle.read(expected_bytes + 1)
        after = os.fstat(descriptor)
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
        ):
            raise IntegrityError(f"verified capture changed while reading: {path}")
    finally:
        os.close(descriptor)
    if len(body) != expected_bytes:
        raise IntegrityError(f"verified capture byte count changed: {path}")
    return body


def _roots_are_separate(capture_root: Path, output_root: Path) -> None:
    capture = capture_root.resolve(strict=True)
    if capture_root.is_symlink() or not capture.is_dir():
        raise IntegrityError("verified capture root must be a real directory")
    output_parent = output_root.parent.resolve(strict=True)
    output = output_parent / output_root.name
    if output.exists() or output.is_symlink():
        raise IntegrityError(f"refusing to overwrite catalogue rebind root: {output}")
    common = Path(os.path.commonpath((capture, output)))
    if common in {capture, output}:
        raise ValidationError(
            "verified capture and rebind output roots must be separate"
        )


def rebind_catalogue_packets(
    catalogue: dict[str, Any],
    *,
    source_registry: dict[str, Any],
    evaluation_registry: dict[str, Any],
    encoder_spec: dict[str, Any],
    verified_capture_root: Path,
    output_root: Path,
    audit_index_path: Path,
    assembled_at: str,
) -> dict[str, Any]:
    """Rehash retained captures and create fresh pending, entry-bound packets."""

    validate_source_registry_v4(source_registry)
    validate_evaluation_registry_v4(evaluation_registry)
    if any(
        entry["custody_state"] != "pinned" for entry in evaluation_registry["datasets"]
    ):
        raise ValidationError(
            "catalogue rebind requires a fully pinned evaluation registry"
        )
    registered = validate_catalogue(
        catalogue,
        source_registry=source_registry,
        evaluation_registry=evaluation_registry,
        encoder_spec=encoder_spec,
    )
    _roots_are_separate(verified_capture_root, output_root)
    if audit_index_path.exists() or audit_index_path.is_symlink():
        raise IntegrityError(
            f"refusing to overwrite rebind audit index: {audit_index_path}"
        )

    prepared: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    capture_commitments: list[dict[str, Any]] = []
    for subject in catalogue["subjects"]:
        key = (subject["subject_kind"], subject["subject_id"])
        _, entry = registered[key]
        capture_subject_root = verified_capture_root / subject["review_id"]
        if capture_subject_root.is_symlink() or not capture_subject_root.is_dir():
            raise IntegrityError(
                f"verified capture subject root is missing or unsafe: {subject['review_id']}"
            )
        documents: list[dict[str, Any]] = []
        for document in subject["documents"]:
            receipt_path = (
                capture_subject_root / f"{document['document_id']}.document.json"
            )
            snapshot_path = capture_subject_root / f"{document['document_id']}.snapshot"
            if (
                receipt_path.is_symlink()
                or snapshot_path.is_symlink()
                or not receipt_path.is_file()
                or not snapshot_path.is_file()
            ):
                raise IntegrityError(
                    f"verified catalogue capture is incomplete: {document['document_id']}"
                )
            receipt = load_json(receipt_path)
            if not isinstance(receipt, dict):
                raise ValidationError(
                    f"captured document receipt must be an object: {document['document_id']}"
                )
            _receipt_matches_catalogue(receipt, document)
            if receipt.get("snapshot_path") != f"{document['document_id']}.snapshot":
                raise ValidationError(
                    f"captured document catalogue mismatch: {document['document_id']}:snapshot_path"
                )
            documents.append(receipt)
        bundle = build_evidence_bundle(
            bundle_id=f"{subject['review_id']}-evidence",
            review_id=subject["review_id"],
            subject_kind=subject["subject_kind"],
            subject_id=subject["subject_id"],
            subject_binding_sha256=canonical_sha256(entry),
            documents=documents,
            findings=[dict(finding) for finding in subject["findings"]],
            assembled_at=assembled_at,
        )
        verify_evidence_bundle(bundle, capture_subject_root)
        capture_commitments.extend(
            {
                "review_id": subject["review_id"],
                "document_id": document["document_id"],
                "byte_count": document["byte_count"],
                "sha256": document["sha256"],
                "retrieved_at": document["retrieved_at"],
            }
            for document in bundle["documents"]
        )
        prepared.append((subject, bundle, capture_subject_root))

    output_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    public_subjects: list[dict[str, Any]] = []
    for subject, bundle, capture_subject_root in prepared:
        subject_output = output_root / subject["review_id"]
        subject_output.mkdir(mode=0o700)
        for document in bundle["documents"]:
            body = _read_verified_capture(
                capture_subject_root / document["snapshot_path"],
                document["byte_count"],
            )
            snapshot_output = subject_output / document["snapshot_path"]
            _write_json_exclusive(
                subject_output / f"{document['document_id']}.document.json",
                document,
                mode=0o600,
            )
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(snapshot_output, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
        verified = verify_evidence_bundle(bundle, subject_output)
        assessment = make_pending_assessment(bundle)
        _write_json_exclusive(subject_output / "bundle.json", bundle, mode=0o600)
        _write_json_exclusive(
            subject_output / "assessment.pending.json", assessment, mode=0o600
        )
        public_subjects.append(
            {
                "subject_kind": subject["subject_kind"],
                "subject_id": subject["subject_id"],
                "review_id": subject["review_id"],
                "subject_binding_sha256": bundle["subject_binding_sha256"],
                "bundle_sha256": verified.sha256,
                "verified_document_count": len(bundle["documents"]),
                "decision": "pending",
                "commercial_context": "unclear",
                "training_authorized": False,
            }
        )
    audit_index = {
        "schema_version": CATALOGUE_VERSION,
        "record_kind": "licence_evidence_rebind_index",
        "generated_at": assembled_at,
        "contains_evaluation_content": False,
        "verified_capture_set_sha256": canonical_sha256(
            sorted(
                capture_commitments,
                key=lambda item: (item["review_id"], item["document_id"]),
            )
        ),
        "subjects": public_subjects,
    }
    _write_json_exclusive(audit_index_path, audit_index, mode=0o644)
    return audit_index
