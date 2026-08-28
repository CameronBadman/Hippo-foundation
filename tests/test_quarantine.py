from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hippocampus_foundation.phase0 import quarantine
from hippocampus_foundation.phase0.errors import QuarantineError, ValidationError
from hippocampus_foundation.phase0.quarantine import (
    MAX_SAFE_JSON_INTEGER,
    Identifier,
    compile_public_index,
    dependency_closure,
    fingerprint_text,
    match_record,
    normalize_identifier,
    normalize_text,
    normalized_text_sha256,
)


def bundle(*, fingerprints: list[dict]) -> dict:
    return {
        "seal_id": "test-seal",
        "sealed_record_count": 1,
        "seeds": [],
        "relationships": [],
        "raw_hashes": [],
        "normalized_hashes": [],
        "fingerprints": fingerprints,
    }


def test_identifier_normalization_is_namespace_specific() -> None:
    assert normalize_identifier("WIKIDATA.ENTITY", " q42 ").value == "Q42"
    assert (
        normalize_identifier("doi", "https://doi.org/10.1000/ABC").value
        == "10.1000/abc"
    )
    assert normalize_identifier("pmid", "00042").value == "42"
    with pytest.raises(ValidationError):
        normalize_identifier("wikidata.entity", "not-an-entity")


@given(st.text())
def test_text_normalization_is_idempotent(value: str) -> None:
    assert normalize_text(normalize_text(value)) == normalize_text(value)


def test_incident_statement_closure_is_directed_and_cannot_explode_to_siblings() -> (
    None
):
    entity = Identifier("wikidata.entity", "Q1", "20260720")
    first = Identifier("wikidata.statement", "Q1$A", "20260720")
    sibling = Identifier("wikidata.statement", "Q1$B", "20260720")
    relations = [
        (entity, "incident_statement", first),
        (entity, "incident_statement", sibling),
    ]
    assert dependency_closure([first], relations) == {first}
    assert dependency_closure([entity], relations) == {entity, first, sibling}


def test_family_closure_is_symmetric_and_transitive() -> None:
    page = Identifier("wikipedia.page", "1")
    revision = Identifier("wikipedia.revision", "2")
    redirect = Identifier("wikipedia.page", "3")
    relations = [
        (page, "revision_of", revision),
        (redirect, "redirect_to", page),
    ]
    assert dependency_closure([revision], relations) == {page, revision, redirect}


def test_fingerprint_is_deterministic_and_near_duplicate_matching_is_exactly_checked() -> (
    None
):
    text = " ".join(f"word{index}" for index in range(80))
    reference = fingerprint_text(text, "reference")
    candidate = fingerprint_text(text + " ", "candidate")
    index = compile_public_index(
        index_id="test",
        bundles=[bundle(fingerprints=[reference])],
    )
    descriptor = {
        "identifiers": [],
        "raw_sha256": "sha256:" + "0" * 64,
        "normalized_sha256": normalized_text_sha256("different"),
        "fingerprint": candidate,
    }
    decision = match_record(descriptor, index)
    assert decision["decision"] == "excluded"
    assert decision["reasons"] == ["near_duplicate:reference"]
    assert len(reference["minhash"]) == 128
    assert max(reference["minhash"]) <= MAX_SAFE_JSON_INTEGER
    assert index["coverage"] == [
        {
            "seal_id": "test-seal",
            "sealed_record_count": 1,
            "seed_identifier_count": 0,
            "closure_identifier_count": 0,
            "relationship_count": 0,
            "raw_hash_count": 0,
            "normalized_hash_count": 0,
            "fingerprint_count": 1,
            "closure_complete": True,
        }
    ]


def test_minhash_estimate_cannot_veto_exact_contamination_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = " ".join(f"word{index}" for index in range(60))
    reference = fingerprint_text(text, "reference")
    candidate = fingerprint_text(text, "candidate")
    monkeypatch.setattr(quarantine, "minhash_similarity", lambda *_args: 0.0)
    result = match_record(
        {
            "identifiers": [],
            "raw_sha256": "sha256:" + "0" * 64,
            "normalized_sha256": "sha256:" + "1" * 64,
            "fingerprint": candidate,
        },
        {
            "identifiers": [],
            "raw_hashes": [],
            "normalized_hashes": [],
            "fingerprints": [reference],
        },
    )
    assert result["decision"] == "excluded"


def test_duplicate_fingerprint_ids_are_rejected() -> None:
    fingerprint = fingerprint_text("short text", "duplicate")
    with pytest.raises(QuarantineError, match="duplicate fingerprint_id"):
        compile_public_index(
            index_id="test",
            bundles=[bundle(fingerprints=[fingerprint, dict(fingerprint)])],
        )


def test_unresolved_sealed_record_count_fails_closed() -> None:
    unresolved = bundle(fingerprints=[fingerprint_text("short text", "fixture")])
    unresolved["sealed_record_count"] = None
    with pytest.raises(QuarantineError, match="unresolved"):
        compile_public_index(index_id="test", bundles=[unresolved])


def test_missing_descriptor_evidence_fails_closed() -> None:
    decision = match_record(
        {"identifiers": []},
        {
            "identifiers": [],
            "raw_hashes": [],
            "normalized_hashes": [],
            "fingerprints": [],
        },
    )
    assert decision["decision"] == "undetermined"
    assert "missing:fingerprint" in decision["reasons"]


def test_public_index_rejects_label_bearing_fields() -> None:
    fingerprint = fingerprint_text("short text", "fixture")
    fingerprint["labels"] = ["hidden"]
    with pytest.raises(QuarantineError, match="label-bearing field"):
        compile_public_index(
            index_id="test",
            bundles=[bundle(fingerprints=[fingerprint])],
        )
