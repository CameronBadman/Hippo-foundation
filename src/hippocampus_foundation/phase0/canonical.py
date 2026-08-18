"""Canonical serialization and content identifiers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import rfc8785

from .errors import ValidationError


def canonical_bytes(value: Any) -> bytes:
    """Serialize *value* using RFC 8785 JSON Canonicalization Scheme."""

    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"value is not canonical-JSON compatible: {exc}") from exc


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON from {path}: {exc}") from exc


def dump_pretty(value: Any) -> str:
    """Human-readable JSON; never use this representation for hashing."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
