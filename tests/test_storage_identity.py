from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hippocampus_foundation.phase0.canonical import canonical_sha256
from hippocampus_foundation.phase0.cli import main as phase0_main
from hippocampus_foundation.phase0.errors import ValidationError
from hippocampus_foundation.phase0.v2 import validate_storage_attestation_v2
from hippocampus_foundation.storage_identity import (
    bind_drive_observation,
    validate_observation_v1,
    validate_schema_lock_v1,
)

ROOT = Path(__file__).resolve().parents[1]


def timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def observation(observed_at: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "record_kind": "drive_identity_observation",
        "observed_at": observed_at,
        "requested_scope": "https://www.googleapis.com/auth/drive.readonly",
        "scope_exact": True,
        "same_account_human_attested": True,
        "principal_permission_id_sha256": "sha256:" + "a" * 64,
        "provider": "google_drive_shared_drive",
        "provider_resource_id": "shared-drive-id",
        "root_resource_id": "lake-folder-id",
        "observed_root": "/content/drive/Shareddrives/Data/graph-memory-data-lake",
        "method": "google_drive_api_v3_authenticated",
        "checks": {
            "unique_shared_drive": True,
            "unique_direct_folder": True,
            "folder_not_shortcut": True,
            "list_get_consistent": True,
            "live_drivefs_mount": True,
            "identity_stable": True,
        },
        "contains_evaluation_content": False,
        "api_drive_write_authorized": False,
        "drive_write_performed": False,
        "mount_write_capability_assessed": False,
        "training_authorized": False,
    }


def source_registry() -> dict:
    return json.loads(
        (ROOT / "registries" / "sources.v2.json").read_text(encoding="utf-8")
    )


def test_schema_is_frozen_and_observation_must_be_fresh() -> None:
    assert validate_schema_lock_v1() == {
        "drive-observation.schema.json": "sha256:79215c85b26df37c9124760dcb4368137101c1f33ef40813ac8bb1a04cde030c"
    }
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    validate_observation_v1(
        observation(timestamp(now - timedelta(minutes=15))),
        evaluated_at=timestamp(now),
    )
    with pytest.raises(ValidationError, match="stale"):
        validate_observation_v1(
            observation(timestamp(now - timedelta(minutes=15, seconds=1))),
            evaluated_at=timestamp(now),
        )


def test_binding_populates_only_storage_ids_and_derives_attestation() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    registry = source_registry()
    original_digest = canonical_sha256(registry)
    observed = observation(timestamp(now))
    bound, attestation = bind_drive_observation(
        registry,
        observed,
        verifier="drive-lake-custodian",
        bound_at=timestamp(now),
    )
    assert canonical_sha256(registry) == original_digest
    requirement = bound["storage_requirements"][0]
    assert requirement["provider_resource_id"] == "shared-drive-id"
    assert requirement["root_resource_id"] == "lake-folder-id"
    assert attestation == {
        "schema_version": "2.0.0",
        "record_kind": "storage_attestation",
        "locator_id": "drive_lake",
        "provider": "google_drive_shared_drive",
        "provider_resource_id": "shared-drive-id",
        "root_resource_id": "lake-folder-id",
        "observed_root": "/content/drive/Shareddrives/Data/graph-memory-data-lake",
        "observed_at": timestamp(now),
        "method": "google_drive_api_v3_authenticated",
        "verifier": "drive-lake-custodian",
    }
    validate_storage_attestation_v2(attestation, bound, evaluated_at=timestamp(now))


def test_binding_rejects_conflicting_registered_identity_or_false_check() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    registry = source_registry()
    registry["storage_requirements"][0]["provider_resource_id"] = "different-drive"
    with pytest.raises(ValidationError, match="conflicts"):
        bind_drive_observation(
            registry,
            observation(timestamp(now)),
            verifier="custodian",
            bound_at=timestamp(now),
        )

    invalid = copy.deepcopy(observation(timestamp(now)))
    invalid["checks"]["identity_stable"] = False
    with pytest.raises(ValidationError, match="True was expected"):
        validate_observation_v1(invalid, evaluated_at=timestamp(now))


def test_bind_drive_cli_refuses_to_overwrite_outputs(tmp_path: Path) -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    registry_path = tmp_path / "sources.json"
    observation_path = tmp_path / "observation.json"
    registry_output = tmp_path / "bound-sources.json"
    attestation_output = tmp_path / "attestation.json"
    registry_path.write_text(json.dumps(source_registry()), encoding="utf-8")
    observation_path.write_text(
        json.dumps(observation(timestamp(now))), encoding="utf-8"
    )
    arguments = [
        "storage",
        "bind-drive",
        "--registry",
        str(registry_path),
        "--observation",
        str(observation_path),
        "--registry-output",
        str(registry_output),
        "--attestation-output",
        str(attestation_output),
        "--verifier",
        "drive-lake-custodian",
        "--bound-at",
        timestamp(now),
    ]
    assert phase0_main(arguments) == 0
    before = (registry_output.read_bytes(), attestation_output.read_bytes())
    assert phase0_main(arguments) == 2
    assert (registry_output.read_bytes(), attestation_output.read_bytes()) == before
