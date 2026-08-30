"""Domain-separated seed handling for the READ run."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from .errors import GenerationError

MASTER_SEED_BYTES = 32


def read_master_seed(path: Path) -> bytes:
    """Read an exact private seed without following links or accepting changes."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GenerationError("cannot open the private seed safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size != MASTER_SEED_BYTES:
            raise GenerationError("private seed must be an exact 32-byte regular file")
        value = os.read(descriptor, MASTER_SEED_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(value) != MASTER_SEED_BYTES:
        raise GenerationError("private seed length changed while being read")
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after:
        raise GenerationError("private seed changed while being read")
    return value


def seed_commitment(seed: bytes) -> str:
    if len(seed) != MASTER_SEED_BYTES:
        raise GenerationError("seed commitment requires exactly 32 bytes")
    return f"sha256:{hashlib.sha256(seed).hexdigest()}"


def derive_bytes(master_seed: bytes, *parts: str, length: int = 32) -> bytes:
    """Derive bytes with explicit length framing and SHA-256 counter mode."""

    if len(master_seed) != MASTER_SEED_BYTES:
        raise GenerationError("seed derivation requires exactly 32 master bytes")
    if length < 1 or length > 1024:
        raise GenerationError("derived seed length is outside the fixed bound")
    framed = bytearray(b"hippocampus-read-run-v1\x00")
    for part in parts:
        encoded = part.encode("utf-8")
        framed.extend(len(encoded).to_bytes(4, "big"))
        framed.extend(encoded)
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(
            hashlib.sha256(
                master_seed + bytes(framed) + counter.to_bytes(4, "big")
            ).digest()
        )
        counter += 1
    return bytes(output[:length])


def derive_int(master_seed: bytes, *parts: str) -> int:
    return int.from_bytes(derive_bytes(master_seed, *parts, length=16), "big")
