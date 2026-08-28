from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hippocampus_foundation.phase0.canonical import sha256_bytes
from hippocampus_foundation.phase0.errors import SealError
from hippocampus_foundation.phase0.seal import (
    append_access_event,
    consumes_evaluation,
    make_seal_receipt,
    read_access_events,
    resolve_public_key_fingerprint,
    verify_access_chain,
    verify_ciphertext,
)
from hippocampus_foundation.phase0.validation import validate_instance


def test_ciphertext_receipt_verification_detects_tampering(tmp_path: Path) -> None:
    ciphertext = tmp_path / "bundle.gpg"
    ciphertext.write_bytes(b"ciphertext fixture")
    receipt = make_seal_receipt(
        seal_id="fixture-seal",
        evaluation_class="confirmatory",
        ciphertext_sha256=sha256_bytes(ciphertext.read_bytes()),
        artifact_hashes=["sha256:" + "1" * 64],
        public_key_fingerprint="A" * 40,
        custodian="offline-key-custodian",
        record_count=1,
    )
    validate_instance(receipt, "seal.schema.json")
    verify_ciphertext(ciphertext, receipt)
    ciphertext.write_bytes(b"tampered")
    with pytest.raises(SealError, match="digest mismatch"):
        verify_ciphertext(ciphertext, receipt)


def test_access_log_is_private_hash_chained_and_tamper_evident(tmp_path: Path) -> None:
    log = tmp_path / "access.jsonl"
    first = append_access_event(
        log_path=log,
        seal_id="fixture-seal",
        action="seal_created",
        actor="custodian",
        details={"receipt_id": "fixture"},
    )
    second = append_access_event(
        log_path=log,
        seal_id="fixture-seal",
        action="verify",
        actor="auditor",
    )
    assert second["previous_hash"] == first["event_hash"]
    assert log.stat().st_mode & 0o077 == 0
    events = read_access_events(log)
    verify_access_chain(events)
    for event in events:
        validate_instance(event, "access-event.schema.json")

    lines = log.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["actor"] = "intruder"
    lines[0] = json.dumps(tampered)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SealError, match="hash mismatch"):
        read_access_events(log)


def test_access_log_rejects_sensitive_detail_fields(tmp_path: Path) -> None:
    with pytest.raises(SealError, match="sensitive access-log field"):
        append_access_event(
            log_path=tmp_path / "access.jsonl",
            seal_id="fixture-seal",
            action="verify",
            actor="auditor",
            details={"labels": ["must not be logged"]},
        )

    with pytest.raises(SealError, match="sensitive access-log field"):
        append_access_event(
            log_path=tmp_path / "access.jsonl",
            seal_id="fixture-seal",
            action="verify",
            actor="auditor",
            details={"gold_answer": "denylist alias"},
        )


def test_access_log_rejects_symlink_output_without_touching_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text("unchanged\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "access.jsonl"
    link.symlink_to(target)

    with pytest.raises(SealError, match="contains a symlink"):
        append_access_event(
            log_path=link,
            seal_id="fixture-seal",
            action="verify",
            actor="auditor",
        )
    assert target.read_text(encoding="utf-8") == "unchanged\n"


def test_external_access_log_anchor_detects_suffix_truncation(tmp_path: Path) -> None:
    log = tmp_path / "access.jsonl"
    first = append_access_event(
        log_path=log,
        seal_id="fixture-seal",
        action="seal_created",
        actor="custodian",
    )
    second = append_access_event(
        log_path=log,
        seal_id="fixture-seal",
        action="verify",
        actor="auditor",
    )
    read_access_events(log, expected_head=second["event_hash"], expected_count=2)

    first_line = log.read_text(encoding="utf-8").splitlines()[0]
    log.write_text(first_line + "\n", encoding="utf-8")
    with pytest.raises(SealError, match="count mismatch"):
        read_access_events(log, expected_head=second["event_hash"], expected_count=2)
    with pytest.raises(SealError, match="head mismatch"):
        read_access_events(log, expected_head=second["event_hash"])
    read_access_events(log, expected_head=first["event_hash"], expected_count=1)


def test_invalid_access_event_is_rejected_before_log_creation(tmp_path: Path) -> None:
    log = tmp_path / "access.jsonl"
    with pytest.raises(SealError, match="invalid access event"):
        append_access_event(
            log_path=log,
            seal_id="fixture-seal",
            action="not-a-real-action",
            actor="auditor",
        )
    assert not log.exists()


def test_explicit_consume_and_retire_actions_make_evaluation_unavailable() -> None:
    assert consumes_evaluation("consume") is True
    assert consumes_evaluation("retire") is True
    assert consumes_evaluation("verify") is False


def test_gpg_recipient_resolution_requires_one_encryption_capable_primary_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = "A" * 40
    pub_fields = ["pub", "-", "2048", "1", "keyid", "0", "0", "", "", "", "", "e", ""]
    fpr_fields = ["fpr", "", "", "", "", "", "", "", "", fingerprint, ""]
    output = ":".join(pub_fields) + "\n" + ":".join(fpr_fields) + "\n"
    monkeypatch.setattr(
        "hippocampus_foundation.phase0.seal.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=output, stderr=""
        ),
    )
    assert resolve_public_key_fingerprint(fingerprint) == fingerprint


def test_gpg_recipient_resolution_rejects_ambiguous_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def key_block(value: str) -> str:
        pub = ["pub", "-", "2048", "1", "keyid", "0", "0", "", "", "", "", "e", ""]
        fpr = ["fpr", "", "", "", "", "", "", "", "", value, ""]
        return ":".join(pub) + "\n" + ":".join(fpr) + "\n"

    monkeypatch.setattr(
        "hippocampus_foundation.phase0.seal.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=key_block("A" * 40) + key_block("B" * 40),
            stderr="",
        ),
    )
    with pytest.raises(SealError, match="ambiguous"):
        resolve_public_key_fingerprint("recipient")
