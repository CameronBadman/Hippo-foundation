"""Locked Phase 0 v4.1 execution-evidence contracts.

The v4.1 schemas are additive.  They deliberately live outside the frozen v4
directory so validating this lock cannot alter or silently extend any v4
contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json
from .errors import ValidationError

SCHEMA_VERSION_V4_1 = "4.1.0"

FROZEN_SCHEMA_DIGESTS_V4_1: dict[str, str] = {
    "execution-evidence.schema.json": "sha256:0706dafb046972193c225d5651d3ddac6f4407c6d35362900c20abd8065170f1",
    "gate.schema.json": "sha256:678818fd646f00dc25df404e7db78ffbb279f4663c1eaec659ea8dc59ba740d0",
}


def schema_root_v4_1() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "phase0" / "v4.1"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "phase0" / "v4.1"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate Phase 0 v4.1 schema directory")


def load_schema_v4_1(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v4_1()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(
            f"invalid Phase 0 v4.1 schema {path}: {exc.message}"
        ) from exc
    return value


def validate_v4_1(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v4_1(schema_name, root)
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


def schema_digests_v4_1(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v4_1()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no Phase 0 v4.1 schemas under {target}")
    return {name: canonical_sha256(load_schema_v4_1(name, target)) for name in names}


def validate_schema_lock_v4_1(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v4_1(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V4_1:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V4_1.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V4_1.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V4_1.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V4_1[name] != observed[name]
        )
        raise ValidationError(
            "Phase 0 v4.1 schema lock mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return observed
