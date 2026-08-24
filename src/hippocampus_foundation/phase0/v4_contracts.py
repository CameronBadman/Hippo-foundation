"""Frozen Phase 0 v4 external-evidence firewall contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json
from .errors import ValidationError


SCHEMA_VERSION_V4 = "4.0.0"

FROZEN_SCHEMA_DIGESTS_V4: dict[str, str] = {
    "access-anchor.schema.json": "sha256:dae63dbf21f0f45bdfb0369f5ac510123752489003359898c3bc3dce7c95cfcd",
    "evaluation-evidence.schema.json": "sha256:242a5fec9cae920c96123c9333d9b8ac7e14a1f7d95f9661ffe3ec733e8f2b38",
    "gate.schema.json": "sha256:0f1ac6c08b7762d6c7ba85269874a2f983fa42f7ad458be0ba03049972fd75d8",
    "publisher-evidence.schema.json": "sha256:ed0d7599bc19bb855500adad7c60979c6c02b5b671d9fa20bf9d3788a8da7fc2",
    "quarantine-decision.schema.json": "sha256:4bcbfa34f8387063d3df610450925e1fc646261c0e5e520ba4081e6b68732584",
    "registry.schema.json": "sha256:710afefe09f927344f1fa2b8e874b4fcf3d962d3e2f0ac0dee83030ef7893596",
    "source-evidence.schema.json": "sha256:4e425bf254c54eaf8ac767a4cffe66a73c0ee9c893b87eb541f7f8fe9d450645",
    "storage-evidence.schema.json": "sha256:85277084828aba780f6eead444357132492cdc991c3ab8f5e62fbf3dbf343933",
}


def schema_root_v4() -> Path:
    package_candidate = Path(__file__).resolve().parents[1] / "schemas" / "phase0" / "v4"
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = Path(__file__).resolve().parents[3] / "schemas" / "phase0" / "v4"
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate Phase 0 v4 schema directory")


def load_schema_v4(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or schema_root_v4()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(f"invalid Phase 0 v4 schema {path}: {exc.message}") from exc
    return value


def validate_v4(instance: Any, schema_name: str, root: Path | None = None) -> None:
    schema = load_schema_v4(schema_name, root)
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
            (
                "/".join(str(part) for part in error.absolute_path) or "$"
            )
            + f": failed JSON Schema keyword {error.validator!r}"
            for error in leaves
        }
    )
    raise ValidationError("; ".join(rendered))


def schema_digests_v4(root: Path | None = None) -> dict[str, str]:
    target = root or schema_root_v4()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no Phase 0 v4 schemas under {target}")
    return {name: canonical_sha256(load_schema_v4(name, target)) for name in names}


def validate_schema_lock_v4(root: Path | None = None) -> dict[str, str]:
    observed = schema_digests_v4(root)
    if observed != FROZEN_SCHEMA_DIGESTS_V4:
        missing = sorted(FROZEN_SCHEMA_DIGESTS_V4.keys() - observed.keys())
        extra = sorted(observed.keys() - FROZEN_SCHEMA_DIGESTS_V4.keys())
        changed = sorted(
            name
            for name in FROZEN_SCHEMA_DIGESTS_V4.keys() & observed.keys()
            if FROZEN_SCHEMA_DIGESTS_V4[name] != observed[name]
        )
        raise ValidationError(
            "Phase 0 v4 schema lock mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return observed
