"""Locked additive Phase 0 v4.2 authority and acquisition contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json
from .errors import ValidationError

SCHEMA_VERSION_V4_2 = "4.2.0"

# Filled only with canonical schema digests. Changing a v4.2 schema requires a
# new contract version rather than updating these values in place.
FROZEN_SCHEMA_DIGESTS_V4_2: dict[str, str] = {
    "authority-policy.schema.json": "sha256:0d052d604a731602acafe4779bf98affab394e3808fa664ee7f8f78954af0192",
    "drive-identity-marker.schema.json": "sha256:0cbf054689b16c622b696b73458d06dac7e2d204c39faa3e51975ec512528696",
    "execution-evidence.schema.json": "sha256:dd9c19f7d365008c8d2e26359762a765e162d1eadc955788379ddadc7d23c12f",
    "gate.schema.json": "sha256:698706551145cc1ca9a1a91cd5a5a655010d5924a21d0d0d1e6d203544d5cf4b",
}


def schema_root_v4_2() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase0" / "v4.2"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase0" / "v4.2"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate Phase 0 v4.2 schema directory")


def load_schema_v4_2(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v4_2()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(
            f"invalid Phase 0 v4.2 schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v4_2(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v4_2(schema_name, root)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    leaves = []
    pending = list(errors)
    while pending:
        error = pending.pop()
        if error.context:
            pending.extend(error.context)
        else:
            leaves.append(error)
    rendered = sorted(
        {
            ("/".join(str(part) for part in error.absolute_path) or "$")
            + f": failed JSON Schema keyword {error.validator!r}"
            for error in leaves
        }
    )
    raise ValidationError("; ".join(rendered))


def schema_digests_v4_2(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v4_2()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no Phase 0 v4.2 schemas under {target}")
    return {name: canonical_sha256(load_schema_v4_2(name, target)) for name in names}


def validate_schema_lock_v4_2(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v4_2(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V4_2:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V4_2.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V4_2.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V4_2.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V4_2[name] != observed[name]
        )
        raise ValidationError(
            "Phase 0 v4.2 schema lock mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return observed
