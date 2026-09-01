"""Frozen preregistration contract checks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json

from .errors import IntegrityGateError

FROZEN_PREREGISTRATION_JSON_SHA256 = (
    "sha256:b28bfb07b90671cdf863b43557212973d6eadcba6530af90fec5f2fe5a76f717"
)
FROZEN_PREREGISTRATION_MARKDOWN_SHA256 = (
    "sha256:9acfc1cb5d498058f242e0df71e6eea22f3c854d71b745eae191f645be425229"
)
FROZEN_TRAINING_CONFIG_SHA256 = (
    "sha256:9b3e5b9123261d7be95fdf3831accbbb15573e29befaab8905971ec8bcd1d660"
)
# Set when `training-config.v2.json` is created, which happens only after the
# learnability probe supplies its single new value under Amendment 05 §2.
# Until then a v2 request is refused rather than silently falling back to v1.
FROZEN_TRAINING_CONFIG_V2_SHA256: str | None = None
TRAINING_CONFIG_VERSIONS = ("v1", "v2")


def contract_directory() -> Path:
    package_candidate = Path(__file__).resolve().parent / "contracts_data"
    if package_candidate.is_dir():
        return package_candidate
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "experiments" / "read_run_v1").is_dir():
        return candidate / "experiments" / "read_run_v1"
    raise IntegrityGateError("cannot locate the frozen READ-run preregistration")


def validate_preregistration(
    root: Path | None = None, *, version: str = "v1"
) -> dict[str, Any]:
    """Verify the frozen preregistration and return the requested training config.

    The v1 digests are checked on every call whatever `version` asks for: a v2
    run must still be running against an unmodified frozen preregistration. Only
    which training configuration is *returned* changes, and the returned
    `training_config_sha256` identifies it, so a receipt written under one
    version cannot be evaluated under the other.
    """

    if version not in TRAINING_CONFIG_VERSIONS:
        raise IntegrityGateError("training configuration version is not preregistered")
    directory = (
        root / "experiments" / "read_run_v1"
        if root is not None
        else contract_directory()
    )
    machine_path = directory / "preregistration.v1.json"
    document_path = directory / "PREREGISTRATION.md"
    value = load_json(machine_path)
    if not isinstance(value, dict):
        raise IntegrityGateError("machine preregistration must be an object")
    observed_json = canonical_sha256(value)
    try:
        document = document_path.read_bytes()
    except OSError as exc:
        raise IntegrityGateError("cannot read the frozen preregistration") from exc
    observed_document = f"sha256:{hashlib.sha256(document).hexdigest()}"
    training_config = load_json(directory / "training-config.v1.json")
    if not isinstance(training_config, dict):
        raise IntegrityGateError("training configuration must be an object")
    observed_training_config = canonical_sha256(training_config)
    if observed_json != FROZEN_PREREGISTRATION_JSON_SHA256:
        raise IntegrityGateError(
            "machine preregistration digest changed after the freeze"
        )
    if observed_document != FROZEN_PREREGISTRATION_MARKDOWN_SHA256:
        raise IntegrityGateError("preregistration document changed after the freeze")
    if observed_training_config != FROZEN_TRAINING_CONFIG_SHA256:
        raise IntegrityGateError("training configuration changed after it was locked")
    if version == "v2":
        if FROZEN_TRAINING_CONFIG_V2_SHA256 is None:
            raise IntegrityGateError("training configuration v2 is not frozen yet")
        training_config = load_json(directory / "training-config.v2.json")
        if not isinstance(training_config, dict):
            raise IntegrityGateError("training configuration must be an object")
        observed_training_config = canonical_sha256(training_config)
        if observed_training_config != FROZEN_TRAINING_CONFIG_V2_SHA256:
            raise IntegrityGateError(
                "training configuration changed after it was locked"
            )
    return {
        "preregistration": value,
        "training_config": training_config,
        "training_config_version": version,
        "preregistration_json_sha256": observed_json,
        "preregistration_markdown_sha256": observed_document,
        "training_config_sha256": observed_training_config,
    }
