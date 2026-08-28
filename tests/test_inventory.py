from __future__ import annotations

import bz2
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from hippocampus_foundation.phase0 import inventory
from hippocampus_foundation.phase0.errors import IntegrityError
from hippocampus_foundation.phase0.inventory import (
    audit_source_registry,
    hash_file,
    resolve_artifact,
    stream_count,
)
from hippocampus_foundation.phase0.validation import validate_source_audit


def test_byte_audit_records_verified_mismatch_and_missing_without_aborting(
    tmp_path: Path,
) -> None:
    payload = b"immutable bytes\n"
    (tmp_path / "good.bin").write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    registry = {
        "registry_id": "fixture",
        "sources": [
            {
                "source_id": "fixture@v1",
                "artifacts": [
                    {
                        "artifact_id": "good",
                        "locator_id": "fixture",
                        "filename": "good.bin",
                        "expected_bytes": len(payload),
                        "checksums": [{"algorithm": "sha256", "value": expected}],
                    },
                    {
                        "artifact_id": "mismatch",
                        "locator_id": "fixture",
                        "filename": "good.bin",
                        "expected_bytes": len(payload) + 1,
                        "checksums": [{"algorithm": "sha256", "value": expected}],
                    },
                    {
                        "artifact_id": "missing",
                        "locator_id": "fixture",
                        "filename": "missing.bin",
                        "expected_bytes": 1,
                        "checksums": [],
                    },
                ],
            }
        ],
    }
    result = audit_source_registry(registry, {"fixture": str(tmp_path)})
    validate_source_audit(result)
    assert [item["status"] for item in result["artifacts"]] == [
        "verified",
        "mismatch",
        "error",
    ]
    assert result["all_verified"] is False


def test_full_audit_post_scan_recheck_detects_late_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact.bin"
    payload = b"initial"
    path.write_bytes(payload)
    registry = {
        "registry_id": "fixture",
        "sources": [
            {
                "source_id": "fixture@v1",
                "artifacts": [
                    {
                        "artifact_id": "artifact",
                        "locator_id": "fixture",
                        "filename": path.name,
                        "expected_bytes": len(payload),
                        "checksums": [
                            {
                                "algorithm": "sha256",
                                "value": hashlib.sha256(payload).hexdigest(),
                            }
                        ],
                    }
                ],
            }
        ],
    }
    original = inventory.audit_artifact

    def mutate_after_hash(artifact: dict, storage_map: dict[str, str]) -> dict:
        result = original(artifact, storage_map)
        path.write_bytes(b"changed after hash")
        return result

    monkeypatch.setattr(inventory, "audit_artifact", mutate_after_hash)
    result = inventory.audit_source_registry(registry, {"fixture": str(tmp_path)})
    assert result["all_verified"] is False
    assert result["artifacts"][0]["status"] == "mismatch"
    assert any(
        "changed after its hash pass" in message
        for message in result["artifacts"][0]["mismatches"]
    )


def test_hashing_rejects_symlink_artifacts(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"data")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(IntegrityError, match="symlink"):
        hash_file(link)


def test_artifact_resolution_rejects_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-fixture"
    outside.write_bytes(b"not in root")
    try:
        with pytest.raises(IntegrityError, match="parent traversal"):
            resolve_artifact(
                {"fixture": str(tmp_path)}, "fixture", "../outside-fixture"
            )
    finally:
        outside.unlink()


def test_streaming_structural_counters(tmp_path: Path) -> None:
    wikipedia = tmp_path / "wiki.xml.bz2"
    with bz2.open(wikipedia, "wt", encoding="utf-8") as handle:
        handle.write(
            "<mediawiki><page><title>A</title><revision><id>1</id>"
            "<text>hello</text></revision></page></mediawiki>"
        )
    wiki_result = stream_count(wikipedia, "wikipedia_xml")
    assert wiki_result["documents"] == 1
    assert wiki_result["document_versions"] == 1

    sql = tmp_path / "rows.sql.gz"
    with gzip.open(sql, "wb") as handle:
        handle.write(b"INSERT INTO t VALUES (1,'a,b'),(2,'semi;colon');\n")
    sql_result = stream_count(sql, "mediawiki_sql")
    assert sql_result["rows"] == 2
    assert sql_result["insert_statements"] == 1

    wikidata = tmp_path / "wikidata.json.bz2"
    entity = {
        "id": "Q1",
        "type": "item",
        "sitelinks": {"enwiki": {}},
        "claims": {
            "P1": [
                {
                    "rank": "normal",
                    "mainsnak": {"datatype": "string"},
                    "qualifiers": {"P2": [{}, {}]},
                    "references": [{}, {}],
                }
            ]
        },
    }
    with bz2.open(wikidata, "wt", encoding="utf-8") as handle:
        handle.write("[\n" + json.dumps(entity) + "\n]\n")
    wd_result = stream_count(wikidata, "wikidata_json")
    assert wd_result["entities"] == 1
    assert wd_result["statements"] == 1
    assert wd_result["qualifiers"] == 2
    assert wd_result["references"] == 2

    conceptnet = tmp_path / "conceptnet.csv.gz"
    with gzip.open(conceptnet, "wt", encoding="utf-8") as handle:
        handle.write("/a/1\t/r/RelatedTo\t/c/en/cat\t/c/en/animal\t{}\n")
    cn_result = stream_count(conceptnet, "conceptnet_assertions")
    assert cn_result["rows"] == 1
    assert cn_result["relation.RelatedTo"] == 1
    assert cn_result["language.en"] == 2
