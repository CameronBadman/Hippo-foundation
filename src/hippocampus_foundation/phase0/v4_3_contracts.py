"""Locked additive Phase 0 v4.3 staging and publication contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json
from .errors import ValidationError

SCHEMA_VERSION_V4_3 = "4.3.0"

# These are canonical RFC 8785 digests. A schema change requires a new version.
FROZEN_SCHEMA_DIGESTS_V4_3: dict[str, str] = {
    "authority-policy.schema.json": (
        "sha256:650b2a662964275d9bc14cdac707702255f162601cb162ca23b79e6ce6161eca"
    ),
    "execution-evidence.schema.json": (
        "sha256:28e49b86b0ea8445219f50841b5483d10f6a2760c41d2267f7e484aa9fd83104"
    ),
    "gate.schema.json": (
        "sha256:56193fe202da27f7e20f82340cecfb6d70f7e38d1a822f1ba63359586bfbebd4"
    ),
}


def schema_root_v4_3() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase0" / "v4.3"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase0" / "v4.3"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate Phase 0 v4.3 schema directory")


def load_schema_v4_3(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v4_3()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(
            f"invalid Phase 0 v4.3 schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v4_3(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v4_3(schema_name, root)
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


def schema_digests_v4_3(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v4_3()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no Phase 0 v4.3 schemas under {target}")
    return {name: canonical_sha256(load_schema_v4_3(name, target)) for name in names}


def validate_schema_lock_v4_3(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v4_3(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V4_3:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V4_3.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V4_3.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V4_3.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V4_3[name] != observed[name]
        )
        raise ValidationError(
            "Phase 0 v4.3 schema lock mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return observed
