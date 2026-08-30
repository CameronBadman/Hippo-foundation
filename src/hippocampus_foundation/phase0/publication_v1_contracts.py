"""Locked public-source publication v1 contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json
from .errors import ValidationError

PUBLICATION_SCHEMA_VERSION = "1.0.0"

FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1: dict[str, str] = {
    "authority-policy.schema.json": (
        "sha256:958a7adda6b861c65d9bc2c9fa1df29d94a87d4eb80bc3c420264cd96c11332a"
    ),
    "destination-policy.schema.json": (
        "sha256:8d52d3fe80c069d638854567d8c476abec04009cef26ca642cb5483a41636aa7"
    ),
    "evidence.schema.json": (
        "sha256:580c8d75ef4a09cd9f89fd5de61cce4e4a3216e7363bf9838532abda8bc684f1"
    ),
    "gate.schema.json": (
        "sha256:e1303afd5d1ca80219d3556d9e556b5c7229bb1fe58e108b1afc9c3019718511"
    ),
}


def publication_schema_root_v1() -> Path:
    package_candidate = (
        Path(__file__).resolve().parents[1] / "schemas" / "publication" / "v1"
    )
    if package_candidate.is_dir():
        return package_candidate
    repository_candidate = (
        Path(__file__).resolve().parents[3] / "schemas" / "publication" / "v1"
    )
    if repository_candidate.is_dir():
        return repository_candidate
    raise ValidationError("cannot locate publication v1 schema directory")


def load_publication_schema_v1(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or publication_schema_root_v1()) / name
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValidationError(f"schema must be an object: {path}")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(
            f"invalid publication v1 schema {path}: {exc.message}"
        ) from exc
    return value


def validate_publication_v1(
    instance: Any, schema_name: str, root: Path | None = None
) -> None:
    schema = load_publication_schema_v1(schema_name, root)
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


def publication_schema_digests_v1(root: Path | None = None) -> dict[str, str]:
    target = root or publication_schema_root_v1()
    names = sorted(path.name for path in target.glob("*.schema.json"))
    if not names:
        raise ValidationError(f"no publication v1 schemas under {target}")
    return {
        name: canonical_sha256(load_publication_schema_v1(name, target))
        for name in names
    }


def validate_publication_schema_lock_v1(
    root: Path | None = None,
) -> dict[str, str]:
    observed = publication_schema_digests_v1(root)
    if observed != FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1:
        missing = sorted(FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1.keys() - observed)
        extra = sorted(observed.keys() - FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1)
        changed = sorted(
            name
            for name in FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1.keys() & observed.keys()
            if FROZEN_PUBLICATION_SCHEMA_DIGESTS_V1[name] != observed[name]
        )
        raise ValidationError(
            "publication v1 schema lock mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    return observed
