from __future__ import annotations

import hashlib
from pathlib import Path

from hippocampus_foundation.phase0.canonical import load_json
from hippocampus_foundation.phase0.v4_1 import evaluate_gate_v4_1

ROOT = Path(__file__).resolve().parents[1]


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def test_publisher_research_check_matches_registry_and_retained_copies() -> None:
    registry = load_json(ROOT / "registries" / "sources.v4.publisher-pinned.json")
    research = load_json(ROOT / "audit" / "publisher-manifest-research.v4.1.json")
    assert research["research_only"] is True
    assert research["authorization_evidence"] is False
    assert research["publisher_detached_signature_verified"] is False
    artifacts = {
        artifact["artifact_id"]: artifact
        for source in registry["sources"]
        for artifact in source["artifacts"]
    }
    requirements = {
        item["artifact_id"]: item
        for item in registry["publisher_evidence_requirements"]
    }
    checked_ids = set()
    for manifest in research["manifests"]:
        for row in manifest["rows"]:
            artifact_id = row["artifact_id"]
            artifact = artifacts[artifact_id]
            checked_ids.add(artifact_id)
            assert requirements[artifact_id]["statement_url"] == manifest["url"]
            assert Path(artifact["filename"]).name == row["filename"]
            assert row["registered_sha1"] == next(
                checksum["value"]
                for checksum in artifact["checksums"]
                if checksum["origin"] == "publisher" and checksum["algorithm"] == "sha1"
            )
        research_copy = (
            ROOT / "private" / "publisher-research" / Path(manifest["url"]).name
        )
        if research_copy.exists():
            body = research_copy.read_bytes()
            assert len(body) == manifest["byte_count"]
            assert _sha256_bytes(body) == manifest["manifest_sha256"]
            statement_rows = {
                parts[1].strip(): parts[0]
                for line in body.decode("utf-8").splitlines()
                if len(parts := line.split(maxsplit=1)) == 2
            }
            assert all(
                statement_rows[row["filename"]] == row["registered_sha1"]
                for row in manifest["rows"]
            )
    assert checked_ids == set(artifacts)
    assert research["registered_artifact_count"] == len(checked_ids)


def test_checked_blocked_report_is_mechanically_reproducible() -> None:
    expected = load_json(ROOT / "audit" / "phase0-gate.v4.1.blocked.json")
    observed = evaluate_gate_v4_1(
        evaluated_at=expected["evaluated_at"],
        source_registries=[
            load_json(ROOT / "registries" / "sources.v4.pending.json"),
            load_json(ROOT / "registries" / "sources.v4.publisher-pinned.json"),
        ],
        evaluation_registries=[load_json(ROOT / "registries" / "evaluations.v4.json")],
    )
    assert observed == expected
    assert observed["registry_lineage_ready"] is True
    assert observed["evaluation_materialization_ready"] is False
    assert observed["foundation_acquisition_authorized"] is False
    assert observed["foundation_transform_ready"] is False
    assert observed["training_authorized"] is False
