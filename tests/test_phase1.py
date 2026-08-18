from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hippocampus_foundation.phase0.canonical import canonical_sha256
from hippocampus_foundation.phase1.contracts import (
    FROZEN_ENCODER_SPEC_SHA256,
    OBJECTIVE_FAMILIES,
    validate_encoder_spec,
    validate_graph_record,
    validate_objective_example,
    validate_schema_lock_v1,
)
from hippocampus_foundation.phase1.encoder import (
    render_text,
    select_context,
    verify_encoder_assets,
)
from hippocampus_foundation.phase1.errors import (
    Phase1IntegrityError,
    Phase1ValidationError,
)
from hippocampus_foundation.phase1.gate import evaluate_phase1_gate
from hippocampus_foundation.phase1.neighbours import LIMITS, cap_neighbours
from hippocampus_foundation.phase1.objectives import (
    make_objective_manifest,
    replay_objectives,
)
from hippocampus_foundation.phase1.sampling import select_nodes


ROOT = Path(__file__).resolve().parents[1]
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def now(offset_seconds: int = 0) -> str:
    value = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return value.isoformat().replace("+00:00", "Z")


def source_ref(value: str = "fixture") -> dict:
    return {
        "namespace": "fixture.source",
        "value": value,
        "source_version": "fixture-v1",
        "artifact_sha256": DIGEST_A,
    }


def node(index: int, community: int) -> dict:
    return {
        "schema_version": "1.0.0",
        "record_kind": "node",
        "node_id": f"node-{index:03d}",
        "source_kind": "wikipedia" if index % 2 else "wikidata",
        "title": f"Node {index}",
        "body": f"Body {index}",
        "community_id": f"community-{community}",
        "pagerank": (index + 1) / 1000,
        "in_degree": index % 11,
        "out_degree": index % 7,
        "text_characters": 100 + index * 13,
        "quarantine_decision": "clear",
        "provenance_refs": [source_ref(str(index))],
    }


def neighbour(
    index: int,
    *,
    center: str,
    source_kind: str,
    direction: str,
    value_kind: str = "entity_ref",
    property_id: str = "P1",
) -> dict:
    return {
        "schema_version": "1.0.0",
        "record_kind": "neighbour_candidate",
        "candidate_id": f"{center}-candidate-{index:03d}",
        "center_node_id": center,
        "neighbour_node_id": None if value_kind == "literal" else f"target-{index}",
        "source_kind": source_kind,
        "direction": direction,
        "value_kind": value_kind,
        "property_id": property_id,
        "statement_id": f"statement-{center}-{index}",
        "diversity_key": f"diversity-{index % 7}",
        "rank": "normal",
        "quarantine_decision": "clear",
        "provenance_refs": [source_ref(str(index))],
    }


def objective(family: str, index: int) -> dict:
    return {
        "schema_version": "1.0.0",
        "record_kind": "objective_example",
        "example_id": f"{family}-{index}",
        "objective_family": family,
        "selection_stage": "development",
        "graph_snapshot_sha256": DIGEST_B,
        "quarantine_index_sha256": DIGEST_C,
        "prompt": {"query": f"fixture {index}"},
        "candidates": [
            {
                "candidate_id": "target",
                "value": {"answer": "observed"},
                "is_target": True,
                "negative_basis": None,
                "evidence_refs": [source_ref("target")],
            },
            {
                "candidate_id": "alternative",
                "value": {"answer": "other observed value"},
                "is_target": False,
                "negative_basis": "observed_alternative",
                "evidence_refs": [source_ref("alternative")],
            },
        ],
        "target_candidate_id": "target",
        "generator_id": "fixture-generator-v1",
        "generator_seed": 20260817,
        "provenance_refs": [source_ref()],
    }


def test_phase1_contracts_and_frozen_encoder_spec_validate() -> None:
    assert set(validate_schema_lock_v1()) == {
        "artifact.schema.json",
        "encoder.schema.json",
        "gate.schema.json",
        "graph.schema.json",
        "objective-example.schema.json",
    }
    spec = json.loads(
        (ROOT / "registries/encoder.gte-modernbert.v1.json").read_text(
            encoding="utf-8"
        )
    )
    validate_encoder_spec(spec)
    assert canonical_sha256(spec) == FROZEN_ENCODER_SPEC_SHA256
    assert render_text("Title", "Body") == "Title\n\nBody"
    assert select_context(3000, spec) == {
        "selected_context_tokens": 2048,
        "maximum_supported_tokens": 8192,
        "requires_truncation": True,
        "exceeds_model_capacity": False,
        "chunking": False,
    }


def test_encoder_verification_rejects_any_unregistered_snapshot_entry(
    tmp_path: Path,
) -> None:
    spec = json.loads(
        (ROOT / "registries/encoder.gte-modernbert.v1.json").read_text(
            encoding="utf-8"
        )
    )
    snapshot = tmp_path / "snapshot"
    for asset in spec["assets"]:
        path = snapshot / asset["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    (snapshot / "unexpected.bin").write_bytes(b"undeclared")

    with pytest.raises(
        Phase1IntegrityError,
        match=r"unexpected_files=\['unexpected\.bin'\]",
    ):
        verify_encoder_assets(
            spec=spec,
            snapshot=snapshot,
            bakeoff_report=tmp_path / "not-reached.json",
        )


def test_graph_value_union_reuses_snak_contracts() -> None:
    statement = {
        "schema_version": "1.0.0",
        "record_kind": "statement",
        "statement_id": "S1",
        "subject": {"kind": "entity_ref", "entity_id": "Q1"},
        "property_id": "P31",
        "value": {"kind": "entity_ref", "entity_id": "Q5"},
        "rank": "normal",
        "qualifiers": [
            {
                "property_id": "P580",
                "value": {
                    "kind": "literal",
                    "datatype": "time",
                    "lexical_value": "+2026-08-17T00:00:00Z",
                    "language": None,
                    "unit": None,
                    "calendar_model": "Q1985727",
                    "precision": 11,
                },
            }
        ],
        "references": [
            {
                "reference_id": "R1",
                "snaks": [
                    {
                        "property_id": "P248",
                        "value": {"kind": "sentinel", "sentinel": "somevalue"},
                    }
                ],
            }
        ],
        "quarantine_decision": "clear",
        "provenance_refs": [source_ref()],
    }
    validate_graph_record(statement)
    malformed = copy.deepcopy(statement)
    malformed["value"]["lexical_value"] = "extra field from another union arm"
    with pytest.raises(Phase1ValidationError):
        validate_graph_record(malformed)


def test_sample_is_deterministic_and_covers_communities() -> None:
    candidates = [node(index, index % 6) for index in range(60)]
    left, left_stats = select_nodes(candidates, size=24)
    right, right_stats = select_nodes(reversed(candidates), size=24)
    assert [item["node_id"] for item in left] == [item["node_id"] for item in right]
    assert left_stats == right_stats
    assert left_stats["covered_communities"] == left_stats["community_count"] == 6
    assert len(left) == 24


def test_neighbour_caps_preserve_every_exclusion_in_overflow() -> None:
    records = [
        neighbour(i, center="wiki", source_kind="wikipedia", direction="outgoing")
        for i in range(20)
    ]
    records.extend(
        neighbour(
            100 + i,
            center="wd-property",
            source_kind="wikidata",
            direction="outgoing",
            property_id="P31",
        )
        for i in range(10)
    )
    records.extend(
        neighbour(
            200 + i,
            center="wd-category",
            source_kind="wikidata",
            direction="outgoing",
            property_id=f"P{i + 100}",
        )
        for i in range(30)
    )
    selected, overflow, stats = cap_neighbours(records)
    assert stats["input_count"] == stats["selected_count"] + stats["overflow_count"]
    assert sum(item["center_node_id"] == "wiki" for item in selected) == 16
    assert sum(item["center_node_id"] == "wd-property" for item in selected) == 4
    assert sum(item["center_node_id"] == "wd-category" for item in selected) == 24
    assert {item["reason"] for item in overflow} == {"property_cap", "category_cap"}
    assert len({item["candidate"]["candidate_id"] for item in overflow}) == len(overflow)
    assert LIMITS["wikidata_property"] == 4


def test_all_objective_families_replay_without_absent_edge_negatives() -> None:
    examples = [
        objective(family, index)
        for index, family in enumerate(sorted(OBJECTIVE_FAMILIES))
    ]
    replayed, stats = replay_objectives(examples)
    assert len(replayed) == len(OBJECTIVE_FAMILIES)
    assert set(stats["family_counts"]) == OBJECTIVE_FAMILIES
    assert all(item["selection_stage"] == "development" for item in replayed)
    manifest = make_objective_manifest(
        phase0_gate_sha256=DIGEST_A,
        input_sha256=DIGEST_A,
        output_sha256=DIGEST_B,
        stats=stats,
        created_at="2026-08-17T00:00:00Z",
    )
    assert manifest["absent_edge_negatives"] == 0
    assert manifest["training_authorized"] is False

    invalid = copy.deepcopy(examples[0])
    invalid["candidates"][1]["negative_basis"] = None
    with pytest.raises(Phase1ValidationError, match="negative candidate"):
        validate_objective_example(invalid)


def test_phase1_gate_can_only_authorize_data_preparation() -> None:
    spec = json.loads(
        (ROOT / "registries/encoder.gte-modernbert.v1.json").read_text(
            encoding="utf-8"
        )
    )
    blocked = evaluate_phase1_gate(
        evaluated_at=now(2),
        phase0_gate=None,
        encoder_spec=spec,
        encoder_verification=None,
        sample_manifest=None,
        graph_manifest=None,
        objective_manifest=None,
    )
    assert blocked["phase1_data_ready"] is False
    assert blocked["training_authorized"] is False

    phase0 = {
        "schema_version": "2.0.0",
        "gate_id": "phase0-public-foundation-v2",
        "evaluated_at": now(),
        "schemas_frozen": True,
        "storage_identity_ready": True,
        "source_audit_ready": True,
        "licensing_ready": True,
        "public_confirmatory_ready": True,
        "quarantine_ready": True,
        "structural_inventory_ready": True,
        "admission_ready": True,
        "foundation_acquisition_authorized": True,
        "foundation_transform_ready": True,
        "training_authorized": False,
        "blockers": [],
        "evidence": [f"quarantine_index:{DIGEST_C}"],
    }
    phase0_sha = canonical_sha256(phase0)
    verification = {
        "schema_version": "1.0.0",
        "record_kind": "encoder_verification",
        "encoder_id": spec["encoder_id"],
        "spec_sha256": FROZEN_ENCODER_SPEC_SHA256,
        "snapshot_id": "fixture-snapshot",
        "revision": spec["revision"],
        "bakeoff_report_sha256": spec["bakeoff_report_sha256"],
        "assets": sorted(spec["assets"], key=lambda item: item["path"]),
        "asset_set_exact": True,
        "executable_model_code_files": [],
        "verified_at": now(),
        "verified": True,
    }
    common = {
        "schema_version": "1.0.0",
        "phase0_gate_sha256": phase0_sha,
        "created_at": now(),
        "complete": True,
        "errors": [],
        "training_authorized": False,
        "quarantine_index_sha256": DIGEST_C,
    }
    sample = {
        **common,
        "record_kind": "sample_manifest",
        "algorithm_id": "community-joint-strata-waterfill-v1",
        "candidate_sha256": DIGEST_A,
        "selected_sha256": DIGEST_B,
        "seed": 20260817,
        "requested_size": 40000,
        "candidate_count": 50000,
        "selected_size": 40000,
        "community_count": 1200,
        "covered_communities": 1200,
        "stratum_count": 900,
        "covered_strata": 900,
    }
    graph = {
        **common,
        "record_kind": "neighbour_cap_manifest",
        "algorithm_id": "one-hop-diverse-cap-v1",
        "input_sha256": DIGEST_A,
        "selected_sha256": DIGEST_B,
        "overflow_sha256": DIGEST_A,
        "input_count": 100,
        "selected_count": 80,
        "overflow_count": 20,
        "no_silent_drop": True,
        "limits": LIMITS,
    }
    objectives = {
        **common,
        "record_kind": "objective_manifest",
        "algorithm_id": "objective-validation-replay-v1",
        "input_sha256": DIGEST_A,
        "output_sha256": DIGEST_B,
        "graph_snapshot_sha256": DIGEST_B,
        "example_count": len(OBJECTIVE_FAMILIES),
        "family_counts": {family: 1 for family in sorted(OBJECTIVE_FAMILIES)},
        "development_only": True,
        "maximum_candidates": 8,
        "absent_edge_negatives": 0,
    }
    ready = evaluate_phase1_gate(
        evaluated_at=now(2),
        phase0_gate=phase0,
        encoder_spec=spec,
        encoder_verification=verification,
        sample_manifest=sample,
        graph_manifest=graph,
        objective_manifest=objectives,
    )
    assert ready["phase1_data_ready"] is True
    assert ready["training_authorized"] is False
    assert ready["blockers"] == []
