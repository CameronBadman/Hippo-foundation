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
FROZEN_TRAINING_CONFIG_V2_SHA256: str | None = (
    "sha256:a9154e278d28dd186e4a47379923c8a6751a6a78f1509a653d423719c9aa50f2"
)
# Set when `heldout-seed.v2.json` is created, in the same ceremony that writes the
# new 32-byte master seed. E1's holdout was opened once under freeze 07d18b39 and
# is spent, so E1-v2 needs a seed the frozen preregistration cannot name.
FROZEN_HELDOUT_SEED_V2_SHA256: str | None = (
    "sha256:cf962fe56f67f05f32f7326fc5788b0247337b5da290bb8e2a2e8441bc5da803"
)
RUN_VERSIONS = (1, 2)
HELDOUT_SEED_V2_FIELDS = frozenset(
    {
        "schema_version",
        "record_kind",
        "seed_version",
        "heldout_seed_sha256",
        "supersedes",
        "bound_preregistration_json_sha256",
        "frozen_at",
    }
)


def contract_directory() -> Path:
    package_candidate = Path(__file__).resolve().parent / "contracts_data"
    if package_candidate.is_dir():
        return package_candidate
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "experiments" / "read_run_v1").is_dir():
        return candidate / "experiments" / "read_run_v1"
    raise IntegrityGateError("cannot locate the frozen READ-run preregistration")


def validate_preregistration(
    root: Path | None = None, *, run_version: int = 1
) -> dict[str, Any]:
    """Verify the frozen preregistration and resolve one run version.

    A run version selects a *pair* — a training configuration and a held-out seed
    commitment — rather than each independently. Two separate version parameters
    would admit four states, two of which must never occur on an official path: a
    v2 configuration with the spent v1 seed, or a v1 configuration with the fresh
    seed. Resolving both from one number makes those combinations unconstructible
    rather than merely forbidden.

    v1's three digests are re-checked on every call whatever version is asked
    for. A v2 run is a new seed and a new update count against an *unmodified*
    preregistration; the scientific commitment did not change, only the
    credential proving the holdout was fixed before evaluation.
    """

    if run_version not in RUN_VERSIONS:
        raise IntegrityGateError("run version is not preregistered")
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
    heldout_seed_sha256 = value["heldout_seed_sha256"]
    heldout_seed_record_sha256 = None
    if run_version == 2:
        # Both halves activate together or neither does. A partial activation
        # would pair one version's configuration with the other's seed, which is
        # the state this function exists to make unconstructible.
        if FROZEN_TRAINING_CONFIG_V2_SHA256 is None or (
            FROZEN_HELDOUT_SEED_V2_SHA256 is None
        ):
            raise IntegrityGateError("run version 2 is not frozen yet")
        training_config = load_json(directory / "training-config.v2.json")
        if not isinstance(training_config, dict):
            raise IntegrityGateError("training configuration must be an object")
        observed_training_config = canonical_sha256(training_config)
        if observed_training_config != FROZEN_TRAINING_CONFIG_V2_SHA256:
            raise IntegrityGateError(
                "training configuration changed after it was locked"
            )
        seed_record = load_json(directory / "heldout-seed.v2.json")
        if not isinstance(seed_record, dict):
            raise IntegrityGateError("held-out seed record must be an object")
        heldout_seed_record_sha256 = canonical_sha256(seed_record)
        if heldout_seed_record_sha256 != FROZEN_HELDOUT_SEED_V2_SHA256:
            raise IntegrityGateError("held-out seed record changed after it was locked")
        if set(seed_record) != HELDOUT_SEED_V2_FIELDS:
            raise IntegrityGateError("held-out seed record fields differ")
        if seed_record["bound_preregistration_json_sha256"] != observed_json:
            raise IntegrityGateError(
                "held-out seed record is bound to another preregistration"
            )
        if seed_record["supersedes"] != value["heldout_seed_sha256"]:
            raise IntegrityGateError(
                "held-out seed record supersedes another commitment"
            )
        heldout_seed_sha256 = seed_record["heldout_seed_sha256"]
    return {
        "preregistration": value,
        "training_config": training_config,
        "run_version": run_version,
        "heldout_seed_sha256": heldout_seed_sha256,
        "heldout_seed_record_sha256": heldout_seed_record_sha256,
        "preregistration_json_sha256": observed_json,
        "preregistration_markdown_sha256": observed_document,
        "training_config_sha256": observed_training_config,
    }
