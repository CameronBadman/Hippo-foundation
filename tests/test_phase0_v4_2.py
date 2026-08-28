from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from test_phase0_v4_1 import _complete_v4_1_graph

from hippocampus_foundation.phase0.authority_v4_2 import (
    OAuthConfigIdentity,
    VerifiedOAuthAuthority,
    load_oauth_config_identity,
    make_acquisition_authorization_payload,
    make_oauth_authority_payload,
    validate_acquisition_authorization_time,
    verify_acquisition_authorization,
    verify_oauth_authority,
)
from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json
from hippocampus_foundation.phase0.errors import IntegrityError, ValidationError
from hippocampus_foundation.phase0.v4_1 import evaluate_gate_v4_1
from hippocampus_foundation.phase0.v4_1_contracts import validate_schema_lock_v4_1
from hippocampus_foundation.phase0.v4_2 import (
    AcquisitionEvidenceBundle,
    evaluate_gate_v4_2,
)
from hippocampus_foundation.phase0.v4_2_contracts import validate_schema_lock_v4_2
from hippocampus_foundation.phase0.v4_contracts import (
    FROZEN_SCHEMA_DIGESTS_V4,
    validate_schema_lock_v4,
)

ROOT = Path(__file__).resolve().parents[1]
ADMIN_KEY = "A" * 40
ACQUISITION_KEY = "B" * 40
T_AUTHORITY = "2026-08-25T00:35:00Z"
T_AUTHORIZATION = "2026-08-25T00:45:00Z"
T_PRE = "2026-08-25T00:55:00Z"
T_POST = "2026-08-25T00:56:00Z"
T_FINAL = "2026-08-25T01:00:00Z"


def _signature_verifier(
    _payload: bytes, _signature: bytes, _public_key: bytes, fingerprint: str
) -> str:
    return fingerprint


def _policy() -> dict:
    return {
        "schema_version": "4.2.0",
        "record_kind": "oauth_authority_policy",
        "policy_id": "entor-workspace-oauth-v4.2-test",
        "status": "approved",
        "workspace_domain": "entor.net",
        "workspace_customer_id_sha256": "sha256:" + "1" * 64,
        "cloud_project_numbers": ["123456789012"],
        "oauth_authority_signing_key_fingerprints": [ADMIN_KEY],
        "acquisition_authority_signing_key_fingerprints": [ACQUISITION_KEY],
        "maximum_oauth_authority_days": 365,
        "maximum_acquisition_authority_hours": 24,
        "training_authorized": False,
    }


def _authority(policy: dict, source_tip: dict) -> VerifiedOAuthAuthority:
    requirement = source_tip["storage_requirements"][0]
    payload = make_oauth_authority_payload(
        policy=policy,
        approved_policy_sha256=canonical_sha256(policy),
        oauth_config=OAuthConfigIdentity(
            sha256="sha256:" + "2" * 64,
            client_id_sha256="sha256:" + "5" * 64,
            cloud_project_number="123456789012",
        ),
        authority_id="entor-internal-drive-v1",
        provider_resource_id=requirement["provider_resource_id"],
        root_resource_id=requirement["root_resource_id"],
        marker_file_id="synthetic-marker-file-id",
        marker_sha256="sha256:" + "3" * 64,
        approved_at="2026-08-25T00:34:00Z",
        valid_until="2027-08-24T00:34:00Z",
        approver_id="workspace-admin",
        signing_key_fingerprint=ADMIN_KEY,
    )
    return verify_oauth_authority(
        payload,
        signature=b"oauth-signature",
        public_key=b"oauth-public-key",
        policy=policy,
        approved_policy_sha256=canonical_sha256(policy),
        signature_verifier=_signature_verifier,
    )


def _access_observation(base: dict, at: str) -> dict:
    observation = copy.deepcopy(base)
    observation["observed_at"] = at
    return observation


def _access_proof(
    observation: dict, authority: VerifiedOAuthAuthority, at: str
) -> dict:
    return {
        "schema_version": "4.2.0",
        "record_kind": "drive_access_proof",
        "observed_at": at,
        "oauth_authority_receipt_sha256": authority.sha256,
        "oauth_config_sha256": authority.receipt["oauth_config_sha256"],
        "oauth_client_id_sha256": authority.receipt["oauth_client_id_sha256"],
        "requested_scope": "https://www.googleapis.com/auth/drive.readonly",
        "scope_exact": True,
        "workspace_domain_verified": True,
        "same_resource_mechanically_proven": True,
        "principal_permission_id_sha256": observation["principal_permission_id_sha256"],
        "provider": observation["provider"],
        "provider_resource_id": observation["provider_resource_id"],
        "root_resource_id": observation["root_resource_id"],
        "observed_root": observation["observed_root"],
        "marker_file_id": authority.receipt["marker_file_id"],
        "marker_sha256": authority.receipt["marker_sha256"],
        "mount_identity_sha256": "sha256:" + "4" * 64,
        "checks": {
            "exact_scope": True,
            "internal_domain": True,
            "oauth_config_fingerprint": True,
            "oauth_client_id": True,
            "token_authorized_party": True,
            "registered_shared_drive": True,
            "registered_direct_folder": True,
            "folder_not_shortcut": True,
            "api_marker_identity": True,
            "api_mount_marker_equal": True,
            "root_descriptor_bound": True,
            "live_drivefs_mount": True,
            "identity_stable": True,
        },
        "contains_evaluation_content": False,
        "api_drive_write_authorized": False,
        "drive_write_performed": False,
        "training_authorized": False,
    }


def _v4_2_graph(tmp_path: Path) -> tuple[dict, dict]:
    base = _complete_v4_1_graph(tmp_path)
    policy = _policy()
    source_tip = base["source_registries"][-1]
    authority = _authority(policy, source_tip)
    current_observation = _access_observation(base["drive_observation"], T_FINAL)
    current_proof = _access_proof(current_observation, authority, T_FINAL)
    artifact = next(
        artifact
        for source in source_tip["sources"]
        for artifact in source["artifacts"]
        if artifact["availability"] == "acquisition_target"
    )
    authorization_payload = make_acquisition_authorization_payload(
        policy=policy,
        approved_policy_sha256=canonical_sha256(policy),
        source_registry=source_tip,
        artifact_id=artifact["artifact_id"],
        oauth_authority=authority,
        storage_attestation=base["storage_attestation"],
        authorization_id="synthetic-wikidata-acquisition",
        byte_ceiling=artifact["expected_bytes"],
        authorized_at=T_AUTHORIZATION,
        valid_until="2026-08-25T01:00:30Z",
        authorizer_id="acquisition-authorizer",
        signing_key_fingerprint=ACQUISITION_KEY,
    )
    authorization = verify_acquisition_authorization(
        authorization_payload,
        signature=b"acquisition-signature",
        public_key=b"acquisition-public-key",
        policy=policy,
        source_registry=source_tip,
        oauth_authority=authority,
        storage_attestation=base["storage_attestation"],
        approved_policy_sha256=canonical_sha256(policy),
        signature_verifier=_signature_verifier,
    )
    graph = {
        **base,
        "authority_policy": policy,
        "approved_policy_sha256": canonical_sha256(policy),
        "oauth_authority": authority,
        "drive_access_proof": current_proof,
        "acquisition_authorizations": [authorization],
        "acquisition_evidence": [],
    }
    return graph, {"artifact": artifact, "authorization": authorization}


def test_v4_and_v4_1_schema_locks_remain_unchanged() -> None:
    assert validate_schema_lock_v4() == FROZEN_SCHEMA_DIGESTS_V4
    validate_schema_lock_v4_1()
    validate_schema_lock_v4_2()


def test_v4_1_authorizes_without_client_authority_but_v4_2_fails_closed(
    tmp_path: Path,
) -> None:
    base = _complete_v4_1_graph(tmp_path)
    assert evaluate_gate_v4_1(**base)["foundation_acquisition_authorized"] is True
    report = evaluate_gate_v4_2(**base)
    assert report["oauth_authority_ready"] is False
    assert report["foundation_acquisition_authorized"] is False
    assert any(
        blocker["code"] == "oauth_authority_policy_missing"
        for blocker in report["blockers"]
    )


def test_checked_v4_2_blocked_report_is_mechanically_reproducible() -> None:
    expected = load_json(ROOT / "audit" / "phase0-gate.v4.2.blocked.json")
    observed = evaluate_gate_v4_2(
        evaluated_at=expected["evaluated_at"],
        source_registries=[
            load_json(ROOT / "registries" / "sources.v4.pending.json"),
            load_json(ROOT / "registries" / "sources.v4.publisher-pinned.json"),
        ],
        evaluation_registries=[load_json(ROOT / "registries" / "evaluations.v4.json")],
        authority_policy=load_json(
            ROOT / "policies" / "oauth-authority.v4.2.pending.json"
        ),
    )
    assert observed == expected
    assert len(observed["blockers"]) == 54
    assert observed["registry_lineage_ready"] is True
    assert observed["oauth_authority_ready"] is False
    assert observed["same_resource_ready"] is False
    assert observed["foundation_transform_ready"] is False
    assert observed["training_authorized"] is False


def test_complete_v4_2_graph_requires_signed_authorization_and_acquisition_evidence(
    tmp_path: Path,
) -> None:
    graph, context = _v4_2_graph(tmp_path)
    pre_observation = _access_observation(graph["drive_observation"], T_PRE)
    pre_proof = _access_proof(pre_observation, graph["oauth_authority"], T_PRE)
    pre_graph = {
        **graph,
        "evaluated_at": T_PRE,
        "drive_access_proof": pre_proof,
        "structural_inventories": [],
        "admission_receipts": [],
    }
    authorization_gate = evaluate_gate_v4_2(**pre_graph)
    assert authorization_gate["foundation_acquisition_ready"] is True
    assert authorization_gate["foundation_acquisition_authorized"] is True
    assert authorization_gate["foundation_transform_ready"] is False

    post_observation = _access_observation(graph["drive_observation"], T_POST)
    post_proof = _access_proof(post_observation, graph["oauth_authority"], T_POST)
    artifact = context["artifact"]
    audit_row = next(
        row
        for row in graph["source_audit"]["artifacts"]
        if row["artifact_id"] == artifact["artifact_id"]
    )
    receipt = {
        "schema_version": "4.2.0",
        "record_kind": "source_acquisition_receipt",
        "artifact_id": artifact["artifact_id"],
        "source_registry_sha256": canonical_sha256(graph["source_registries"][-1]),
        "artifact_entry_sha256": canonical_sha256(artifact),
        "authorization_gate_sha256": canonical_sha256(authorization_gate),
        "acquisition_authorization_receipt_sha256": context["authorization"].sha256,
        "oauth_authority_receipt_sha256": graph["oauth_authority"].sha256,
        "storage_attestation_sha256": canonical_sha256(graph["storage_attestation"]),
        "pre_source_audit_sha256": canonical_sha256(graph["source_audit"]),
        "pre_access_proof_sha256": canonical_sha256(pre_proof),
        "post_access_proof_sha256": canonical_sha256(post_proof),
        "provider_resource_id": graph["storage_attestation"]["provider_resource_id"],
        "root_resource_id": graph["storage_attestation"]["root_resource_id"],
        "destination_filename": artifact["filename"],
        "bytes": artifact["expected_bytes"],
        "checksums": {"sha256": audit_row["measured"]["sha256"]},
        "started_at": T_PRE,
        "completed_at": T_POST,
        "complete": True,
        "training_authorized": False,
    }
    final_graph = {
        **graph,
        "acquisition_evidence": [
            AcquisitionEvidenceBundle(
                receipt=receipt,
                pre_source_audit=graph["source_audit"],
                pre_access_proof=pre_proof,
                post_access_proof=post_proof,
                authorization_gate=authorization_gate,
            )
        ],
    }
    report = evaluate_gate_v4_2(**final_graph)
    assert report["blockers"] == []
    assert report["oauth_authority_ready"] is True
    assert report["same_resource_ready"] is True
    assert report["acquisition_evidence_ready"] is True
    assert report["foundation_transform_ready"] is True
    assert report["training_authorized"] is False

    for missing in (
        "authority_policy",
        "oauth_authority",
        "drive_access_proof",
        "acquisition_authorizations",
        "acquisition_evidence",
    ):
        incomplete = dict(final_graph)
        incomplete[missing] = [] if missing.endswith("s") else None
        assert evaluate_gate_v4_2(**incomplete)["foundation_transform_ready"] is False

    forged_gate = copy.deepcopy(authorization_gate)
    forged_gate["evaluated_at"] = T_POST
    forged_receipt = copy.deepcopy(receipt)
    forged_receipt["authorization_gate_sha256"] = canonical_sha256(forged_gate)
    forged_graph = {
        **graph,
        "acquisition_evidence": [
            AcquisitionEvidenceBundle(
                receipt=forged_receipt,
                pre_source_audit=graph["source_audit"],
                pre_access_proof=pre_proof,
                post_access_proof=post_proof,
                authorization_gate=forged_gate,
            )
        ],
    }
    forged_report = evaluate_gate_v4_2(**forged_graph)
    assert forged_report["acquisition_evidence_ready"] is False
    assert any(
        item["code"] == "acquisition_evidence_invalid"
        for item in forged_report["blockers"]
    )

    after_expiry = "2026-08-25T01:01:00Z"
    expired_observation = _access_observation(graph["drive_observation"], after_expiry)
    expired_graph = {
        **final_graph,
        "evaluated_at": after_expiry,
        "drive_access_proof": _access_proof(
            expired_observation, graph["oauth_authority"], after_expiry
        ),
    }
    expired_report = evaluate_gate_v4_2(**expired_graph)
    assert expired_report["acquisition_authorization_ready"] is False
    assert expired_report["foundation_acquisition_authorized"] is False
    assert expired_report["foundation_transform_ready"] is True
    assert expired_report["blockers"] == []


def test_authority_rejects_forged_policy_root_or_signature(tmp_path: Path) -> None:
    base = _complete_v4_1_graph(tmp_path)
    policy = _policy()
    authority = _authority(policy, base["source_registries"][-1])
    forged = copy.deepcopy(policy)
    forged["workspace_domain"] = "attacker.invalid"
    with pytest.raises(IntegrityError, match="approved root"):
        verify_oauth_authority(
            authority.payload,
            signature=b"signature",
            public_key=b"key",
            policy=forged,
            approved_policy_sha256=canonical_sha256(policy),
            signature_verifier=_signature_verifier,
        )

    with pytest.raises(IntegrityError, match="another key"):
        verify_oauth_authority(
            authority.payload,
            signature=b"signature",
            public_key=b"key",
            policy=policy,
            approved_policy_sha256=canonical_sha256(policy),
            signature_verifier=lambda *_args: ACQUISITION_KEY,
        )


def test_authority_validity_and_acquisition_byte_ceiling_fail_closed(
    tmp_path: Path,
) -> None:
    graph, context = _v4_2_graph(tmp_path)
    policy = graph["authority_policy"]
    with pytest.raises(ValidationError, match="byte ceiling"):
        make_acquisition_authorization_payload(
            policy=policy,
            approved_policy_sha256=canonical_sha256(policy),
            source_registry=graph["source_registries"][-1],
            artifact_id=context["artifact"]["artifact_id"],
            oauth_authority=graph["oauth_authority"],
            storage_attestation=graph["storage_attestation"],
            authorization_id="too-small",
            byte_ceiling=context["artifact"]["expected_bytes"] - 1,
            authorized_at=T_AUTHORIZATION,
            valid_until="2026-08-25T23:45:00Z",
            authorizer_id="acquisition-authorizer",
            signing_key_fingerprint=ACQUISITION_KEY,
        )


def test_signed_receipt_digests_are_stable_across_reverification(
    tmp_path: Path,
) -> None:
    graph, context = _v4_2_graph(tmp_path)
    policy = graph["authority_policy"]
    authority = graph["oauth_authority"]
    repeated_authority = verify_oauth_authority(
        authority.payload,
        signature=b"oauth-signature",
        public_key=b"oauth-public-key",
        policy=policy,
        approved_policy_sha256=canonical_sha256(policy),
        signature_verifier=_signature_verifier,
    )
    assert repeated_authority.receipt == authority.receipt
    assert repeated_authority.sha256 == authority.sha256

    authorization = context["authorization"]
    repeated_authorization = verify_acquisition_authorization(
        authorization.payload,
        signature=b"acquisition-signature",
        public_key=b"acquisition-public-key",
        policy=policy,
        source_registry=graph["source_registries"][-1],
        oauth_authority=authority,
        storage_attestation=graph["storage_attestation"],
        approved_policy_sha256=canonical_sha256(policy),
        signature_verifier=_signature_verifier,
    )
    assert repeated_authorization.receipt == authorization.receipt
    assert repeated_authorization.sha256 == authorization.sha256
    with pytest.raises(ValidationError, match="stale"):
        validate_acquisition_authorization_time(
            authorization, evaluated_at="2026-08-25T01:01:00Z"
        )

    stale = copy.deepcopy(context["authorization"].payload)
    stale["valid_until"] = "2026-08-26T00:46:00Z"
    with pytest.raises(ValidationError, match="24 hours"):
        verify_acquisition_authorization(
            stale,
            signature=b"signature",
            public_key=b"key",
            policy=policy,
            source_registry=graph["source_registries"][-1],
            oauth_authority=graph["oauth_authority"],
            storage_attestation=graph["storage_attestation"],
            approved_policy_sha256=canonical_sha256(policy),
            signature_verifier=_signature_verifier,
        )


def test_oauth_config_identity_hashes_exact_private_bytes_without_returning_secret(
    tmp_path: Path,
) -> None:
    config = tmp_path / "oauth.json"
    raw = (
        b'{"installed":{"client_id":"123456789012-example.apps.googleusercontent.com",'
        b'"client_secret":"do-not-emit",'
        b'"auth_uri":"https://accounts.google.com/o/oauth2/v2/auth",'
        b'"token_uri":"https://oauth2.googleapis.com/token",'
        b'"redirect_uris":["http://127.0.0.1/callback"]}}\r\n'
    )
    config.write_bytes(raw)
    config.chmod(0o600)
    identity = load_oauth_config_identity(config.resolve())
    assert identity.sha256 == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert (
        identity.client_id_sha256
        == "sha256:"
        + hashlib.sha256(b"123456789012-example.apps.googleusercontent.com").hexdigest()
    )
    assert identity.cloud_project_number == "123456789012"
    assert "do-not-emit" not in repr(identity)

    config.chmod(0o644)
    with pytest.raises(ValidationError, match="private regular"):
        load_oauth_config_identity(config.resolve())
