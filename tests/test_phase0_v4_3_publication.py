from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import pytest
from test_phase0_v4_1 import EVALUATED, _complete_v4_1_graph

from hippocampus_foundation.licensing import VerifiedBundle
from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.errors import IntegrityError, ValidationError
from hippocampus_foundation.phase0.execution_v4_1 import (
    validate_registry_lineage_v4_1,
)
from hippocampus_foundation.phase0.inventory import hash_file
from hippocampus_foundation.phase0.publication_v1 import (
    APPROVED_DESTINATION_POLICY_SHA256,
    VerifiedPublicationRights,
    build_obligation_manifest,
    evaluate_publication_gate,
    inventory_publication_artifact,
    make_publication_authorization_payload,
    observe_destination,
    plan_parts,
    publish_artifact,
    recover_publication,
    validate_destination_policy,
    verify_publication_authorization,
    verify_publication_rights,
)
from hippocampus_foundation.phase0.publication_v1_contracts import (
    FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1,
    validate_publication_schema_lock_v1,
)
from hippocampus_foundation.phase0.staging_v4_3 import (
    VerifiedStagingAuthorization,
    evaluate_gate_v4_3,
    init_staging_root,
    make_staging_authorization_payload,
    observe_staging_root,
    reproduce_evaluation_gate_v4_1,
    validate_staging_authority_policy,
    verify_staging_authorization,
)
from hippocampus_foundation.phase0.v4_3_contracts import (
    FROZEN_SCHEMA_DIGESTS_V4_3,
    validate_schema_lock_v4_3,
)
from hippocampus_foundation.phase0.v4_contracts import (
    FROZEN_SCHEMA_DIGESTS_V4,
    validate_schema_lock_v4,
)

ROOT = Path(__file__).resolve().parents[1]
KEY = "A" * 40
DIGEST = "sha256:" + "1" * 64
HEX = "2" * 64


def _signature(
    _payload: bytes, _signature: bytes, _public_key: bytes, fingerprint: str
) -> str:
    return fingerprint


@pytest.fixture
def complete_v4_1(tmp_path: Path) -> dict[str, Any]:
    return _complete_v4_1_graph(tmp_path)


def _staging_policy() -> dict[str, Any]:
    return {
        "schema_version": "4.3.0",
        "record_kind": "staging_acquisition_authority_policy",
        "policy_id": "synthetic-staging-v4.3",
        "status": "approved",
        "acquisition_signing_key_fingerprints": [KEY],
        "maximum_authority_hours": 24,
        "required_evaluation_gate_id": "phase0-external-evidence-firewall-v4.1",
        "training_authorized": False,
    }


def test_schema_locks_are_additive_and_destination_is_exact() -> None:
    assert validate_schema_lock_v4() == FROZEN_SCHEMA_DIGESTS_V4
    assert validate_schema_lock_v4_3() == FROZEN_SCHEMA_DIGESTS_V4_3
    assert validate_publication_schema_lock_v1() == FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1
    policy = load_json(ROOT / "policies" / "hf-destination.v1.configured.json")
    assert validate_destination_policy(policy) == (
        "sha256:5732db9cdf9e9fec46a21e9c1b72a01e415917be1ccd13148900f9282a144e31"
    )
    registry = load_json(ROOT / "registries" / "sources.v4.publisher-pinned.json")
    assert {item["artifact_id"] for item in policy["artifact_paths"]} == {
        artifact["artifact_id"]
        for source in registry["sources"]
        for artifact in source["artifacts"]
    }


def test_checked_blocked_reports_are_mechanically_reproducible() -> None:
    phase_expected = load_json(ROOT / "audit" / "phase0-gate.v4.3.blocked.json")
    source_registries = [
        load_json(ROOT / "registries" / "sources.v4.pending.json"),
        load_json(ROOT / "registries" / "sources.v4.publisher-pinned.json"),
    ]
    evaluation_registries = [load_json(ROOT / "registries" / "evaluations.v4.json")]
    evaluation_gate = reproduce_evaluation_gate_v4_1(
        evaluated_at=phase_expected["evaluated_at"],
        source_registries=source_registries,
        evaluation_registries=evaluation_registries,
    )
    phase_observed = evaluate_gate_v4_3(
        evaluated_at=phase_expected["evaluated_at"],
        source_lineage=validate_registry_lineage_v4_1(source_registries),
        evaluation_lineage=validate_registry_lineage_v4_1(evaluation_registries),
        evaluation_gate=evaluation_gate,
        staging_observation=None,
    )
    assert phase_observed == phase_expected
    assert len(phase_observed["blockers"]) == 44
    assert phase_observed["registry_lineage_ready"] is True
    assert phase_observed["foundation_transform_ready"] is False
    assert not any(
        "drive" in item["code"] or "oauth" in item["code"]
        for item in phase_observed["blockers"]
    )

    publication_expected = load_json(
        ROOT / "audit" / "publication-gate.v1.blocked.json"
    )
    destination_policy = load_json(
        ROOT / "policies" / "hf-destination.v1.configured.json"
    )
    destination_observation = load_json(
        ROOT / "audit" / "hf-destination-observation.v1.json"
    )
    publication_observed = evaluate_publication_gate(
        evaluated_at=publication_expected["evaluated_at"],
        destination_policy=destination_policy,
        destination_observation=destination_observation,
        approved_destination_policy_sha256=APPROVED_DESTINATION_POLICY_SHA256,
    )
    assert publication_observed == publication_expected
    assert publication_observed["destination_ready"] is True
    assert publication_observed["publication_complete"] is False
    assert publication_observed["training_authorized"] is False


def test_staging_root_rejects_links_and_evaluation_content(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    initial = init_staging_root(
        root,
        observation_id="staging-initial",
        created_at="2026-08-30T00:00:00Z",
    )
    assert initial["contains_evaluation_content"] is False
    assert root.stat().st_mode & 0o077 == 0
    raw = root / "raw"
    raw.mkdir()
    (raw / "source.bin").write_bytes(b"public source")
    observed = observe_staging_root(
        root,
        observation_id="staging-with-source",
        observed_at="2026-08-30T00:01:00Z",
    )
    assert [item["path"] for item in observed["inventory"]] == [
        ".entor-public-staging-v4.3.json",
        "raw/source.bin",
    ]

    (raw / "source-link").symlink_to(raw / "source.bin")
    with pytest.raises(IntegrityError, match="regular files"):
        observe_staging_root(root, observation_id="linked")
    (raw / "source-link").unlink()
    private = root / "evaluations"
    private.mkdir()
    (private / "heldout.json").write_text("{}", encoding="utf-8")
    with pytest.raises(IntegrityError, match="evaluation or private"):
        observe_staging_root(root, observation_id="leaking")


def test_staging_authority_binds_reproduced_evaluation_graph(
    tmp_path: Path, complete_v4_1: dict[str, Any]
) -> None:
    source_lineage = validate_registry_lineage_v4_1(complete_v4_1["source_registries"])
    evaluation_gate = reproduce_evaluation_gate_v4_1(**complete_v4_1)
    registry = source_lineage.tip
    artifact = registry["sources"][0]["artifacts"][0]
    publisher = next(
        item
        for item in complete_v4_1["publisher_receipts"]
        if item.receipt["artifact_id"] == artifact["artifact_id"]
    )
    staging = init_staging_root(
        tmp_path / "public-staging",
        observation_id="staging-auth",
        created_at="2026-08-25T00:59:00Z",
    )
    policy = _staging_policy()
    payload = make_staging_authorization_payload(
        policy=policy,
        approved_policy_sha256=canonical_sha256(policy),
        source_registry=registry,
        artifact_id=artifact["artifact_id"],
        publisher_receipt=publisher,
        staging_observation=staging,
        evaluation_gate=evaluation_gate,
        authorization_id="synthetic-staging-authorization",
        byte_ceiling=artifact["expected_bytes"],
        authorized_at=EVALUATED,
        valid_until="2026-08-25T02:00:00Z",
        authorizer_id="synthetic-authorizer",
        signing_key_fingerprint=KEY,
    )
    verified = verify_staging_authorization(
        payload,
        signature=b"signature",
        public_key=b"public-key",
        policy=policy,
        source_registry=registry,
        publisher_receipt=publisher,
        staging_observation=staging,
        evaluation_gate=evaluation_gate,
        approved_policy_sha256=canonical_sha256(policy),
        signature_verifier=_signature,
    )
    assert verified.receipt["evaluation_gate_sha256"] == evaluation_gate.sha256
    assert verified.receipt["training_authorized"] is False

    forged_registry = copy.deepcopy(registry)
    forged_registry["sources"][0]["artifacts"][0]["expected_bytes"] += 1
    with pytest.raises(ValidationError, match="authorization mismatch"):
        verify_staging_authorization(
            payload,
            signature=b"signature",
            public_key=b"public-key",
            policy=policy,
            source_registry=forged_registry,
            publisher_receipt=publisher,
            staging_observation=staging,
            evaluation_gate=evaluation_gate,
            approved_policy_sha256=canonical_sha256(policy),
            signature_verifier=_signature,
        )

    incomplete = dict(complete_v4_1)
    incomplete["materializations"] = []
    incomplete_gate = reproduce_evaluation_gate_v4_1(**incomplete)
    with pytest.raises(ValidationError, match="evaluation-side prerequisites"):
        make_staging_authorization_payload(
            policy=policy,
            approved_policy_sha256=canonical_sha256(policy),
            source_registry=registry,
            artifact_id=artifact["artifact_id"],
            publisher_receipt=publisher,
            staging_observation=staging,
            evaluation_gate=incomplete_gate,
            authorization_id="blocked-staging-authorization",
            byte_ceiling=artifact["expected_bytes"],
            authorized_at=EVALUATED,
            valid_until="2026-08-25T02:00:00Z",
            authorizer_id="synthetic-authorizer",
            signing_key_fingerprint=KEY,
        )

    pending = load_json(ROOT / "policies" / "staging-acquisition.v4.3.pending.json")
    with pytest.raises(ValidationError, match="not approved"):
        validate_staging_authority_policy(
            pending, approved_policy_sha256=canonical_sha256(pending)
        )


def _gate_evidence(graph: dict[str, Any], staging: dict[str, Any]) -> dict[str, Any]:
    source_lineage = validate_registry_lineage_v4_1(graph["source_registries"])
    evaluation_lineage = validate_registry_lineage_v4_1(graph["evaluation_registries"])
    evaluation_gate = reproduce_evaluation_gate_v4_1(**graph)
    registry = source_lineage.tip
    registry_sha = canonical_sha256(registry)
    authorizations = []
    acquisitions = []
    audits = []
    inventories = []
    clearances = []
    publications = []
    for index, artifact in enumerate(
        [item for source in registry["sources"] for item in source["artifacts"]]
    ):
        artifact_id = artifact["artifact_id"]
        entry_sha = canonical_sha256(artifact)
        sha1 = next(
            item["value"]
            for item in artifact["checksums"]
            if item["algorithm"] == "sha1"
        )
        local_sha = hashlib.sha256(artifact_id.encode()).hexdigest()
        auth_payload = {
            "schema_version": "4.3.0",
            "record_kind": "staging_acquisition_authorization_payload",
            "authorization_id": f"auth-{index}",
            "authority_policy_sha256": DIGEST,
            "source_registry_sha256": registry_sha,
            "artifact_id": artifact_id,
            "artifact_entry_sha256": entry_sha,
            "publisher_receipt_sha256": "sha256:" + "5" * 64,
            "staging_observation_sha256": canonical_sha256(staging),
            "evaluation_gate_sha256": evaluation_gate.sha256,
            "source_url_sha256": "sha256:"
            + hashlib.sha256(artifact["source_url"].encode()).hexdigest(),
            "expected_bytes": artifact["expected_bytes"],
            "publisher_sha1": sha1,
            "byte_ceiling": artifact["expected_bytes"],
            "authorized_at": "2026-08-25T00:30:00Z",
            "valid_until": "2026-08-25T02:00:00Z",
            "authorizer_id": "synthetic-authorizer",
            "signing_key_fingerprint": KEY,
            "training_authorized": False,
        }
        auth_receipt = {
            "schema_version": "4.3.0",
            "record_kind": "staging_acquisition_authorization_receipt",
            "authorization_id": f"auth-{index}",
            "authority_policy_sha256": DIGEST,
            "payload_sha256": canonical_sha256(auth_payload),
            "signature_sha256": "sha256:" + "3" * 64,
            "public_key_sha256": "sha256:" + "4" * 64,
            "signing_key_fingerprint": KEY,
            "source_registry_sha256": registry_sha,
            "artifact_id": artifact_id,
            "artifact_entry_sha256": entry_sha,
            "publisher_receipt_sha256": "sha256:" + "5" * 64,
            "staging_observation_sha256": canonical_sha256(staging),
            "evaluation_gate_sha256": evaluation_gate.sha256,
            "expected_bytes": artifact["expected_bytes"],
            "publisher_sha1": sha1,
            "byte_ceiling": artifact["expected_bytes"],
            "authorized_at": "2026-08-25T00:30:00Z",
            "valid_until": "2026-08-25T02:00:00Z",
            "training_authorized": False,
        }
        authorization = VerifiedStagingAuthorization(
            payload=auth_payload,
            receipt=auth_receipt,
            sha256=canonical_sha256(auth_receipt),
            signature_sha256=auth_receipt["signature_sha256"],
            public_key_sha256=auth_receipt["public_key_sha256"],
            signing_key_fingerprint=KEY,
        )
        authorizations.append(authorization)
        acquisition = {
            "schema_version": "4.3.0",
            "record_kind": "staging_acquisition_receipt",
            "artifact_id": artifact_id,
            "source_registry_sha256": registry_sha,
            "artifact_entry_sha256": entry_sha,
            "publisher_receipt_sha256": auth_receipt["publisher_receipt_sha256"],
            "authorization_receipt_sha256": authorization.sha256,
            "staging_observation_sha256": canonical_sha256(staging),
            "destination_relative_path": artifact["filename"],
            "bytes": artifact["expected_bytes"],
            "sha1": sha1,
            "sha256": local_sha,
            "started_at": "2026-08-25T00:40:00Z",
            "completed_at": "2026-08-25T00:41:00Z",
            "complete": True,
            "training_authorized": False,
        }
        acquisitions.append(acquisition)
        audit = {
            "schema_version": "4.3.0",
            "record_kind": "staging_artifact_audit",
            "artifact_id": artifact_id,
            "source_registry_sha256": registry_sha,
            "artifact_entry_sha256": entry_sha,
            "acquisition_receipt_sha256": canonical_sha256(acquisition),
            "staging_observation_sha256": canonical_sha256(staging),
            "bytes": artifact["expected_bytes"],
            "sha1": sha1,
            "sha256": local_sha,
            "device": "1",
            "inode": str(index + 1),
            "mtime_ns": "1",
            "audited_at": "2026-08-25T00:42:00Z",
            "verified": True,
            "training_authorized": False,
        }
        audits.append(audit)
        inventory = {
            "schema_version": "4.3.0",
            "record_kind": "staging_structural_inventory",
            "artifact_id": artifact_id,
            "source_registry_sha256": registry_sha,
            "artifact_audit_sha256": canonical_sha256(audit),
            "artifact_sha256": f"sha256:{local_sha}",
            "artifact_bytes": artifact["expected_bytes"],
            "counter_kind": artifact["inventory_kind"],
            "counter_version": "hf-stream-counter-v4",
            "started_at": "2026-08-25T00:43:00Z",
            "completed_at": "2026-08-25T00:44:00Z",
            "complete": True,
            "parse_errors": 0,
            "rejected_records": 0,
            "counters": {"rows": 1},
            "training_authorized": False,
        }
        inventories.append(inventory)
        clearance = {
            "schema_version": "4.3.0",
            "record_kind": "artifact_publication_clearance",
            "artifact_id": artifact_id,
            "source_registry_sha256": registry_sha,
            "artifact_entry_sha256": entry_sha,
            "artifact_audit_sha256": canonical_sha256(audit),
            "inventory_sha256": canonical_sha256(inventory),
            "publisher_receipt_sha256": auth_receipt["publisher_receipt_sha256"],
            "rights_receipt_sha256": "sha256:" + "6" * 64,
            "obligations_sha256": "sha256:" + "7" * 64,
            "evaluation_gate_sha256": evaluation_gate.sha256,
            "quarantine_index_sha256": canonical_sha256(graph["quarantine_index"]),
            "cleared_at": "2026-08-25T00:45:00Z",
            "ready": True,
            "foundation_transform_authorized": False,
            "training_authorized": False,
        }
        clearances.append(clearance)
        publication = {
            "schema_version": "1.0.0",
            "record_kind": "hf_publication_receipt",
            "artifact_id": artifact_id,
            "authorization_receipt_sha256": "sha256:" + "8" * 64,
            "destination_policy_sha256": "sha256:" + "9" * 64,
            "source_registry_sha256": registry_sha,
            "artifact_entry_sha256": entry_sha,
            "artifact_clearance_sha256": canonical_sha256(clearance),
            "local_bytes": artifact["expected_bytes"],
            "local_sha1": sha1,
            "local_sha256": local_sha,
            "initial_head_commit": "a" * 40,
            "final_head_commit": "b" * 40,
            "manifest_path": f"published/{index}.manifest.json",
            "manifest_sha256": "sha256:" + "a" * 64,
            "commits": [
                {
                    "path": f"published/{index}.part",
                    "sha256": "b" * 64,
                    "bytes": 1,
                    "commit": "b" * 40,
                },
                {
                    "path": f"published/{index}.manifest.json",
                    "sha256": "c" * 64,
                    "bytes": 1,
                    "commit": "b" * 40,
                },
            ],
            "started_at": "2026-08-25T00:46:00Z",
            "completed_at": "2026-08-25T00:47:00Z",
            "anonymous_readable": True,
            "complete": True,
            "recovered_after_unknown_outcome": False,
            "training_authorized": False,
        }
        publications.append(publication)
    admissions = []
    for source in registry["sources"]:
        artifact_ids = {artifact["artifact_id"] for artifact in source["artifacts"]}
        admissions.append(
            {
                "schema_version": "4.3.0",
                "record_kind": "hf_source_admission_receipt",
                "source_id": source["source_id"],
                "source_registry_sha256": registry_sha,
                "source_entry_sha256": canonical_sha256(source),
                "clearance_sha256s": sorted(
                    canonical_sha256(item)
                    for item in clearances
                    if item["artifact_id"] in artifact_ids
                ),
                "publication_receipt_sha256s": sorted(
                    canonical_sha256(item)
                    for item in publications
                    if item["artifact_id"] in artifact_ids
                ),
                "decision": "admitted",
                "assessed_at": "2026-08-25T00:50:00Z",
                "assessor": "synthetic-assessor",
                "training_authorized": False,
            }
        )
    return {
        "evaluated_at": EVALUATED,
        "source_lineage": source_lineage,
        "evaluation_lineage": evaluation_lineage,
        "evaluation_gate": evaluation_gate,
        "staging_observation": staging,
        "authorizations": authorizations,
        "acquisitions": acquisitions,
        "audits": audits,
        "inventories": inventories,
        "clearances": clearances,
        "publication_receipts": publications,
        "admissions": admissions,
    }


def test_complete_v4_3_graph_requires_every_evidence_family(
    tmp_path: Path, complete_v4_1: dict[str, Any]
) -> None:
    staging = init_staging_root(
        tmp_path / "gate-staging",
        observation_id="gate-staging",
        created_at="2026-08-25T00:25:00Z",
    )
    graph = _gate_evidence(complete_v4_1, staging)
    ready = evaluate_gate_v4_3(**graph)
    assert ready["blockers"] == []
    assert ready["foundation_transform_ready"] is True
    assert ready["training_authorized"] is False

    for family in (
        "authorizations",
        "acquisitions",
        "audits",
        "inventories",
        "clearances",
        "publication_receipts",
        "admissions",
    ):
        missing = dict(graph)
        missing[family] = []
        assert evaluate_gate_v4_3(**missing)["foundation_transform_ready"] is False

    forged = copy.deepcopy(graph["inventories"])
    forged[0]["artifact_audit_sha256"] = "sha256:" + "f" * 64
    broken = {**graph, "inventories": forged}
    assert evaluate_gate_v4_3(**broken)["structural_inventory_ready"] is False


def test_v4_3_gate_rejects_wrapper_mutation_and_timestamp_rollbacks(
    tmp_path: Path, complete_v4_1: dict[str, Any]
) -> None:
    staging = init_staging_root(
        tmp_path / "ordered-staging",
        observation_id="ordered-staging",
        created_at="2026-08-25T00:25:00Z",
    )
    graph = _gate_evidence(complete_v4_1, staging)

    mutated_authorizations = copy.deepcopy(graph["authorizations"])
    mutated_authorizations[0].payload["expected_bytes"] += 1
    assert (
        evaluate_gate_v4_3(**{**graph, "authorizations": mutated_authorizations})[
            "acquisition_authority_ready"
        ]
        is False
    )

    cases = (
        (
            "acquisitions",
            "completed_at",
            "2026-08-25T00:29:00Z",
            "acquisition_evidence_ready",
        ),
        ("audits", "audited_at", "2026-08-25T00:39:00Z", "artifact_audit_ready"),
        (
            "inventories",
            "started_at",
            "2026-08-25T00:41:00Z",
            "structural_inventory_ready",
        ),
        (
            "clearances",
            "cleared_at",
            "2026-08-25T00:43:00Z",
            "publication_clearance_ready",
        ),
        (
            "publication_receipts",
            "started_at",
            "2026-08-25T00:44:00Z",
            "foundation_publication_ready",
        ),
        (
            "admissions",
            "assessed_at",
            "2026-08-25T00:46:00Z",
            "foundation_transform_ready",
        ),
    )
    for family, field, value, readiness in cases:
        changed = copy.deepcopy(graph[family])
        changed[0][field] = value
        report = evaluate_gate_v4_3(**{**graph, family: changed})
        assert report[readiness] is False, (family, field)

    stale = copy.deepcopy(staging)
    stale["observed_at"] = "2026-08-20T00:00:00Z"
    assert (
        evaluate_gate_v4_3(**{**graph, "staging_observation": stale})["staging_ready"]
        is False
    )


def _destination_policy(readme: bytes) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "record_kind": "hf_destination_policy",
        "policy_id": "synthetic-publication-destination",
        "status": "configured",
        "endpoint": "https://huggingface.co",
        "repo_id": "Owner/synthetic-publication",
        "repo_type": "dataset",
        "revision": "main",
        "visibility": "public",
        "baseline_commit": "a" * 40,
        "maximum_part_bytes": 10737418240,
        "metadata_paths": [
            {
                "path": "README.md",
                "sha256": "sha256:" + hashlib.sha256(readme).hexdigest(),
                "maximum_bytes": 1024,
                "platform_managed": False,
            }
        ],
        "artifact_paths": [
            {"artifact_id": "source-artifact", "path": "sources/source.bin"}
        ],
        "excluded_path_prefixes": ["evaluations/", "private/"],
        "training_authorized": False,
    }


class _FakeHub:
    def __init__(self, readme: bytes) -> None:
        self.head = "a" * 40
        self.files = {"README.md": readme}
        self.counter = 0

    def authenticated_identity(self, _policy: dict[str, Any]) -> str:
        return "Owner"

    def repo_state(self, policy: dict[str, Any], *, anonymous: bool) -> dict[str, Any]:
        del anonymous
        return {
            "repo_id": policy["repo_id"],
            "private": False,
            "sha": self.head,
            "files": [
                {
                    "path": path,
                    "bytes": len(value),
                    "sha256": "sha256:" + hashlib.sha256(value).hexdigest(),
                    "storage_kind": "lfs",
                }
                for path, value in sorted(self.files.items())
            ],
        }

    def upload(
        self,
        _policy: dict[str, Any],
        *,
        local_path: Path | bytes,
        remote_path: str,
        parent_commit: str,
        message: str,
    ) -> str:
        del message
        if parent_commit != self.head:
            raise IntegrityError("parent commit mismatch")
        value = local_path if isinstance(local_path, bytes) else local_path.read_bytes()
        self.counter += 1
        self.head = f"{self.counter:040x}"
        self.files[remote_path] = value
        return self.head

    def download_small(
        self,
        _policy: dict[str, Any],
        *,
        remote_path: str,
        revision: str,
        anonymous: bool,
        maximum_bytes: int,
    ) -> bytes:
        del revision, anonymous
        value = self.files[remote_path]
        if len(value) > maximum_bytes:
            raise ValidationError("too large")
        return value

    def hash_remote(
        self,
        _policy: dict[str, Any],
        *,
        remote_path: str,
        revision: str,
        expected_bytes: int,
    ) -> str:
        del revision
        value = self.files[remote_path]
        assert len(value) == expected_bytes
        return hashlib.sha256(value).hexdigest()


def _publication_rights(
    *, policy: dict[str, Any], source: dict[str, Any], tmp_path: Path
) -> tuple[VerifiedPublicationRights, dict[str, Any]]:
    bundle = {
        "subject_id": "synthetic-source",
        "subject_binding_sha256": canonical_sha256(source),
        "findings": [
            {
                "finding_id": "notice-reviewed",
                "blocking": False,
            }
        ],
    }
    verified_bundle = VerifiedBundle(
        bundle=bundle,
        sha256=canonical_sha256(bundle),
        snapshot_root=tmp_path,
    )
    authority = {
        "schema_version": "1.0.0",
        "record_kind": "publication_authority_policy",
        "policy_id": "synthetic-publication-authority",
        "status": "approved",
        "rights_signing_key_fingerprints": [KEY],
        "publication_signing_key_fingerprints": [KEY],
        "maximum_rights_days": 365,
        "maximum_publication_hours": 72,
        "training_authorized": False,
    }
    payload = {
        "schema_version": "1.0.0",
        "record_kind": "publication_rights_assessment_payload",
        "assessment_id": "synthetic-publication-rights",
        "authority_policy_sha256": canonical_sha256(authority),
        "destination_policy_sha256": canonical_sha256(policy),
        "source_id": "synthetic-source",
        "source_entry_sha256": canonical_sha256(source),
        "evidence_bundle_sha256": verified_bundle.sha256,
        "decision": "approved",
        "commercial_context": "allowed",
        "licence_identifiers": ["CC-BY-SA-4.0"],
        "allowed_uses": [
            "acquire",
            "inventory",
            "quarantine",
            "redistribute_source",
        ],
        "excluded_uses": [
            "commercial_service",
            "embed",
            "evaluate",
            "inference",
            "redistribute_derived",
            "redistribute_model",
            "train",
            "transform",
        ],
        "obligations": [
            {
                "obligation_id": "public-notice",
                "category": "notice",
                "description": "Retain a public source and licence notice.",
            }
        ],
        "finding_dispositions": [
            {
                "finding_id": "notice-reviewed",
                "disposition": "acknowledged_nonblocking",
                "rationale_document_id": None,
            }
        ],
        "reviewer_id": "synthetic-human-reviewer",
        "reviewed_at": "2026-08-29T00:00:00Z",
        "valid_until": "2026-09-30T00:00:00Z",
        "signing_key_fingerprint": KEY,
        "training_authorized": False,
    }
    rights = verify_publication_rights(
        payload,
        signature=b"rights-signature",
        public_key=b"rights-public-key",
        authority_policy=authority,
        destination_policy=policy,
        source_id="synthetic-source",
        source_entry=source,
        evidence_bundle=verified_bundle,
        evaluated_at="2026-08-30T00:00:00Z",
        approved_authority_policy_sha256=canonical_sha256(authority),
        approved_destination_policy_sha256=canonical_sha256(policy),
        signature_verifier=_signature,
    )
    return rights, authority


def test_deterministic_publication_and_unknown_outcome_recovery(
    tmp_path: Path,
) -> None:
    readme = b"source and licence notice\n"
    policy = _destination_policy(readme)
    client = _FakeHub(readme)
    observation = observe_destination(
        policy=policy,
        client=client,
        observed_at="2026-08-30T00:00:00Z",
        approved_policy_sha256=canonical_sha256(policy),
    )
    assert observation["head_commit"] == policy["baseline_commit"]
    source = {"source_id": "synthetic-source", "version": "v1"}
    rights, authority = _publication_rights(
        policy=policy, source=source, tmp_path=tmp_path
    )
    obligations = build_obligation_manifest(
        rights=rights,
        destination_policy=policy,
        destination_observation=observation,
        manifest_id="synthetic-obligations",
        implementation_refs=[
            {
                "obligation_id": "public-notice",
                "evidence_kind": "public_file",
                "path": "README.md",
                "sha256": policy["metadata_paths"][0]["sha256"],
            }
        ],
        assembled_at="2026-08-30T00:01:00Z",
        approved_destination_policy_sha256=canonical_sha256(policy),
    )
    local_path = tmp_path / "source.bin"
    local_path.write_bytes(b"abcdefghij" * 1000)
    measured = hash_file(local_path)
    audit = {
        "schema_version": "4.3.0",
        "record_kind": "staging_artifact_audit",
        "artifact_id": "source-artifact",
        "source_registry_sha256": "sha256:" + "3" * 64,
        "artifact_entry_sha256": "sha256:" + "4" * 64,
        "acquisition_receipt_sha256": "sha256:" + "5" * 64,
        "staging_observation_sha256": "sha256:" + "6" * 64,
        "bytes": measured["bytes"],
        "sha1": measured["sha1"],
        "sha256": measured["sha256"],
        "device": str(measured["device"]),
        "inode": str(measured["inode"]),
        "mtime_ns": str(measured["mtime_ns"]),
        "audited_at": "2026-08-30T00:02:00Z",
        "verified": True,
        "training_authorized": False,
    }
    manifest = inventory_publication_artifact(
        policy=policy,
        artifact_id="source-artifact",
        source_registry_sha256=audit["source_registry_sha256"],
        artifact_entry_sha256=audit["artifact_entry_sha256"],
        local_path=local_path,
        local_audit=audit,
        approved_destination_policy_sha256=canonical_sha256(policy),
    )
    clearance = {
        "schema_version": "4.3.0",
        "record_kind": "artifact_publication_clearance",
        "artifact_id": "source-artifact",
        "source_registry_sha256": audit["source_registry_sha256"],
        "artifact_entry_sha256": audit["artifact_entry_sha256"],
        "artifact_audit_sha256": canonical_sha256(audit),
        "inventory_sha256": "sha256:" + "7" * 64,
        "publisher_receipt_sha256": "sha256:" + "8" * 64,
        "rights_receipt_sha256": rights.sha256,
        "obligations_sha256": canonical_sha256(obligations),
        "evaluation_gate_sha256": "sha256:" + "9" * 64,
        "quarantine_index_sha256": "sha256:" + "a" * 64,
        "cleared_at": "2026-08-30T00:03:00Z",
        "ready": True,
        "foundation_transform_authorized": False,
        "training_authorized": False,
    }
    payload = make_publication_authorization_payload(
        authority_policy=authority,
        destination_policy=policy,
        destination_observation=observation,
        source_registry_sha256=audit["source_registry_sha256"],
        artifact_id="source-artifact",
        artifact_entry_sha256=audit["artifact_entry_sha256"],
        artifact_clearance=clearance,
        rights=rights,
        obligations=obligations,
        artifact_audit=audit,
        artifact_manifest=manifest,
        authorization_id="synthetic-publication-authorization",
        authorized_at="2026-08-30T00:04:00Z",
        valid_until="2026-09-02T00:04:00Z",
        authorizer_id="synthetic-publisher",
        signing_key_fingerprint=KEY,
        approved_authority_policy_sha256=canonical_sha256(authority),
        approved_destination_policy_sha256=canonical_sha256(policy),
    )
    authorization = verify_publication_authorization(
        payload,
        signature=b"publication-signature",
        public_key=b"publication-public-key",
        authority_policy=authority,
        destination_policy=policy,
        destination_observation=observation,
        artifact_clearance=clearance,
        rights=rights,
        obligations=obligations,
        artifact_audit=audit,
        artifact_manifest=manifest,
        approved_authority_policy_sha256=canonical_sha256(authority),
        approved_destination_policy_sha256=canonical_sha256(policy),
        signature_verifier=_signature,
    )

    with pytest.raises(ValidationError, match="predates its evidence"):
        make_publication_authorization_payload(
            authority_policy=authority,
            destination_policy=policy,
            destination_observation=observation,
            source_registry_sha256=audit["source_registry_sha256"],
            artifact_id="source-artifact",
            artifact_entry_sha256=audit["artifact_entry_sha256"],
            artifact_clearance=clearance,
            rights=rights,
            obligations=obligations,
            artifact_audit=audit,
            artifact_manifest=manifest,
            authorization_id="premature-publication-authorization",
            authorized_at="2026-08-30T00:00:00Z",
            valid_until="2026-08-31T00:00:00Z",
            authorizer_id="synthetic-publisher",
            signing_key_fingerprint=KEY,
            approved_authority_policy_sha256=canonical_sha256(authority),
            approved_destination_policy_sha256=canonical_sha256(policy),
        )

    client.files["unexpected-before-upload.txt"] = b"drift"
    with pytest.raises(IntegrityError, match="layout changed"):
        publish_artifact(
            policy=policy,
            destination_observation=observation,
            authorization=authorization,
            artifact_clearance=clearance,
            artifact_manifest=manifest,
            local_path=local_path,
            client=client,
            approved_destination_policy_sha256=canonical_sha256(policy),
        )
    assert client.counter == 0
    del client.files["unexpected-before-upload.txt"]
    receipt = publish_artifact(
        policy=policy,
        destination_observation=observation,
        authorization=authorization,
        artifact_clearance=clearance,
        artifact_manifest=manifest,
        local_path=local_path,
        client=client,
        approved_destination_policy_sha256=canonical_sha256(policy),
    )
    assert receipt["anonymous_readable"] is True
    assert receipt["complete"] is True
    assert len(receipt["commits"]) == 2
    assert (
        receipt["manifest_sha256"] == authorization.receipt["artifact_manifest_sha256"]
    )
    with pytest.raises(ValidationError, match="lacks signed authority"):
        observe_destination(
            policy=policy,
            client=client,
            observed_at=receipt["completed_at"],
            prior_publication_receipts=[receipt],
            approved_policy_sha256=canonical_sha256(policy),
        )
    with pytest.raises(ValidationError, match="lacks its signed manifest"):
        observe_destination(
            policy=policy,
            client=client,
            observed_at=receipt["completed_at"],
            prior_publication_receipts=[receipt],
            prior_publication_authorizations=[authorization],
            approved_policy_sha256=canonical_sha256(policy),
        )
    chained_observation = observe_destination(
        policy=policy,
        client=client,
        observed_at=receipt["completed_at"],
        prior_publication_receipts=[receipt],
        prior_publication_authorizations=[authorization],
        prior_publication_manifests=[manifest],
        approved_policy_sha256=canonical_sha256(policy),
    )
    assert chained_observation["head_commit"] == receipt["final_head_commit"]

    completed_gate = evaluate_publication_gate(
        evaluated_at=receipt["completed_at"],
        destination_policy=policy,
        destination_observation=observation,
        rights=rights,
        obligations=obligations,
        clearance=clearance,
        authorization=authorization,
        publication_receipt=receipt,
        approved_destination_policy_sha256=canonical_sha256(policy),
    )
    assert completed_gate["publication_complete"] is True
    assert completed_gate["blockers"] == []
    assert completed_gate["training_authorized"] is False

    recovered = recover_publication(
        policy=policy,
        authorization=authorization,
        artifact_clearance=clearance,
        destination_observation=observation,
        manifest=manifest,
        client=client,
        started_at="2026-08-30T00:04:00Z",
        approved_destination_policy_sha256=canonical_sha256(policy),
    )
    assert recovered["recovered_after_unknown_outcome"] is True
    assert recovered["final_head_commit"] == receipt["final_head_commit"]

    tampered = copy.deepcopy(manifest)
    tampered["parts"][0]["sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="not authorized"):
        recover_publication(
            policy=policy,
            authorization=authorization,
            artifact_clearance=clearance,
            destination_observation=observation,
            manifest=tampered,
            client=client,
            started_at="2026-08-30T00:04:00Z",
            approved_destination_policy_sha256=canonical_sha256(policy),
        )

    wrong_clearance = copy.deepcopy(clearance)
    wrong_clearance["cleared_at"] = "2026-08-30T00:03:01Z"
    with pytest.raises(ValidationError, match="clearance binding"):
        recover_publication(
            policy=policy,
            authorization=authorization,
            artifact_clearance=wrong_clearance,
            destination_observation=observation,
            manifest=manifest,
            client=client,
            started_at="2026-08-30T00:04:00Z",
            approved_destination_policy_sha256=canonical_sha256(policy),
        )
    with pytest.raises(ValidationError, match="outside the authorization window"):
        recover_publication(
            policy=policy,
            authorization=authorization,
            artifact_clearance=clearance,
            destination_observation=observation,
            manifest=manifest,
            client=client,
            started_at="2026-08-30T00:03:59Z",
            approved_destination_policy_sha256=canonical_sha256(policy),
        )


def test_observation_rejects_extra_remote_file() -> None:
    readme = b"notice\n"
    policy = _destination_policy(readme)
    client = _FakeHub(readme)
    client.files["unexpected.txt"] = b"not authorized"
    with pytest.raises(IntegrityError, match="missing or extra"):
        observe_destination(
            policy=policy,
            client=client,
            observed_at="2026-08-30T00:00:00Z",
            approved_policy_sha256=canonical_sha256(policy),
        )


def test_part_boundaries_are_exact() -> None:
    ten_gib = 10 * 1024 * 1024 * 1024
    assert plan_parts(total_bytes=ten_gib, base_path="sources/a.bin") == [
        {
            "index": 0,
            "path": "sources/a.bin.parts/part-00000-of-00001",
            "offset": 0,
            "bytes": ten_gib,
        }
    ]
    split = plan_parts(total_bytes=ten_gib + 1, base_path="sources/a.bin")
    assert [item["bytes"] for item in split] == [ten_gib, 1]
    assert [item["offset"] for item in split] == [0, ten_gib]
