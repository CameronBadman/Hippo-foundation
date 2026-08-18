from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hippocampus_foundation.phase0.canonical import canonical_sha256, sha256_bytes
from hippocampus_foundation.phase0.v2 import (
    build_quarantine_contribution_v2,
    compile_quarantine_index_v2,
)
from hippocampus_foundation.phase2 import oracles
from hippocampus_foundation.phase2.cli import main as phase2_main
from hippocampus_foundation.phase2.contracts import (
    ACTIONS,
    validate_artifact,
    validate_policy_example,
    validate_schema_lock_v1,
    validate_training_registry,
)
from hippocampus_foundation.phase2.errors import (
    Phase2IntegrityError,
    Phase2OracleDisagreement,
    Phase2QuarantineError,
    Phase2ValidationError,
)
from hippocampus_foundation.phase2.io import (
    bytes_identity,
    canonical_jsonl_bytes,
    write_artifact_set_exclusive,
)
from hippocampus_foundation.phase2.procedural import (
    audit_corpora,
    build_generation,
    verify_generation,
)

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def load_jsonl(relative: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line
    ]


def phase2_inputs(role: str = "training") -> tuple[dict, dict, dict]:
    return (
        load("registries/training-sources.v1.json"),
        load(f"registries/phase2.generator.{role}.v1.json"),
        load("quarantine/phase2-public-reservations.v1.json"),
    )


def checked_artifacts(role: str) -> tuple[list[dict], dict, dict]:
    return (
        load_jsonl(f"fixtures/phase2/{role}.examples.v1.jsonl"),
        load(f"fixtures/phase2/{role}.integrity.v1.json"),
        load(f"fixtures/phase2/{role}.manifest.v1.json"),
    )


def test_phase2_schema_lock_registry_and_checked_in_slice_reproduce() -> None:
    assert set(validate_schema_lock_v1()) == {
        "artifact.schema.json",
        "generator-spec.schema.json",
        "policy-example.schema.json",
        "registry.schema.json",
    }
    registry = load("registries/training-sources.v1.json")
    validate_training_registry(registry)
    assert all(source["training_authorized"] is False for source in registry["sources"])
    assert all(
        source["admission_state"] == "declared" for source in registry["sources"]
    )
    assert all(
        source["rights"]["review_status"] == "pending" for source in registry["sources"]
    )

    generated: list[tuple[dict, dict]] = []
    for role in ("training", "development"):
        registry, spec, quarantine = phase2_inputs(role)
        examples, report, manifest = build_generation(
            registry=registry, spec=spec, quarantine_index=quarantine
        )
        checked_examples, checked_report, checked_manifest = checked_artifacts(role)
        assert examples == checked_examples
        assert report == checked_report
        assert manifest == checked_manifest
        example_bytes = canonical_jsonl_bytes(examples)
        assert (
            example_bytes
            == (ROOT / f"fixtures/phase2/{role}.examples.v1.jsonl").read_bytes()
        )
        assert manifest["examples"] == bytes_identity(example_bytes)
        assert manifest["examples"]["sha256"] == next(
            source["artifact_sha256"]
            for source in registry["sources"]
            if source["source_id"] == spec["source_id"]
        )
        assert verify_generation(
            registry=registry,
            spec=spec,
            quarantine_index=quarantine,
            examples=checked_examples,
            report=checked_report,
            manifest=checked_manifest,
            observed_examples_identity=bytes_identity(example_bytes),
        )["ok"]
        generated.append((manifest, report))

    audit = audit_corpora(
        [item[0] for item in generated], [item[1] for item in generated]
    )
    reversed_audit = audit_corpora(
        [item[0] for item in reversed(generated)],
        [item[1] for item in reversed(generated)],
    )
    assert audit == load("fixtures/phase2/corpus-audit.v1.json")
    assert reversed_audit == audit
    assert audit["clean"] is True
    assert audit["overlaps"] == []
    assert audit["training_authorized"] is False


def test_reservation_quarantine_index_derives_from_real_fixture_bytes() -> None:
    envelope = load("fixtures/phase2/quarantine-reservation.envelope.v1.json")
    contribution = load("fixtures/phase2/quarantine-reservation.contribution.v1.json")
    index = load("quarantine/phase2-public-reservations.v1.json")
    assert envelope["archive_sha256"] == sha256_bytes(
        (ROOT / "fixtures/phase2/quarantine-reservation-source.v1.json").read_bytes()
    )
    assert envelope["adapter_sha256"] == sha256_bytes(
        (ROOT / "fixtures/phase2/quarantine-reservation-adapter.v1.json").read_bytes()
    )
    assert build_quarantine_contribution_v2(envelope) == contribution
    assert index["contribution_sha256s"] == [canonical_sha256(contribution)]
    assert (
        compile_quarantine_index_v2([contribution], index_id=index["index_id"]) == index
    )


def test_generation_is_independent_of_json_object_key_order() -> None:
    registry, spec, quarantine = phase2_inputs()
    left = build_generation(registry=registry, spec=spec, quarantine_index=quarantine)
    reordered_registry = dict(reversed(list(registry.items())))
    reordered_spec = dict(reversed(list(spec.items())))
    reordered_quarantine = dict(reversed(list(quarantine.items())))
    right = build_generation(
        registry=reordered_registry,
        spec=reordered_spec,
        quarantine_index=reordered_quarantine,
    )
    assert left == right
    assert canonical_sha256(registry) == canonical_sha256(reordered_registry)


def test_open_world_actions_proofs_cycles_and_no_label_metadata() -> None:
    examples, report, _manifest = checked_artifacts("training")
    assert report["action_counts"] == {
        "return": 6,
        "abstain_unknown": 4,
        "abstain_conflict": 2,
        "continue": 2,
        "stop_irrelevant": 2,
    }
    assert report["case_counts"] == {kind: 2 for kind in report["case_counts"]}
    assert report["oracle"]["agreement"] is True
    assert report["shortcut_diagnostics"] == {
        "method": "leave-one-world-out-v1",
        "majority_accuracy": 0.375,
        "grammar_accuracy": 0.0,
        "template_accuracy": 0.375,
        "path_length_accuracy": 0.5,
    }

    return_truths = {
        example["target"]["payload"]["truth"]
        for example in examples
        if example["target"]["action"] == "return"
    }
    assert return_truths == {True, False}
    conflicts = [
        example
        for example in examples
        if example["target"]["action"] == "abstain_conflict"
    ]
    assert all(item["evidence"]["positive_proofs"] for item in conflicts)
    assert all(item["evidence"]["negative_proofs"] for item in conflicts)
    unknowns = [
        item for item in examples if item["target"]["action"] == "abstain_unknown"
    ]
    assert all(not item["evidence"]["positive_proofs"] for item in unknowns)
    assert all(not item["evidence"]["negative_proofs"] for item in unknowns)
    continuations = [
        item for item in examples if item["target"]["action"] == "continue"
    ]
    assert all(
        item["evidence"]["useful_frontier_candidate_ids"] for item in continuations
    )
    irrelevant = [
        item for item in examples if item["target"]["action"] == "stop_irrelevant"
    ]
    assert all(item["prediction_time"]["frontier"] for item in irrelevant)
    assert all(
        not item["evidence"]["useful_frontier_candidate_ids"] for item in irrelevant
    )

    cyclic = [
        item
        for item in examples
        if item["dependencies"]["path_length_bucket"] == "cyclic"
        or len(item["prediction_time"]["rules"]) == 3
    ]
    assert len(cyclic) == 4
    for example in cyclic:
        forward, proof_tree = oracles.compare_oracles(
            example["prediction_time"],
            example["query"],
            max_rule_firings=256,
            max_depth=16,
        )
        assert (forward.action, forward.positive, forward.negative) == (
            proof_tree.action,
            proof_tree.positive,
            proof_tree.negative,
        )

    for example in examples:
        assert set(example["provenance"]) == {
            "generator_id",
            "algorithm_id",
            "spec_sha256",
            "seed",
            "ordinal",
        }
        assert example["dependencies"]["template_id"].endswith(":template:base")
        assert tuple(example["candidates"]) == ACTIONS
        assert example["training_authorized"] is False


def test_quarantine_exact_dependency_match_blocks_generation() -> None:
    registry, spec, quarantine = phase2_inputs()
    contaminated = copy.deepcopy(quarantine)
    contaminated["identifiers"].append(
        {
            "namespace": "generator.world",
            "value": "hf-logic-owa-training:world:w000000",
            "source_version": None,
        }
    )
    with pytest.raises(Phase2QuarantineError, match="exact_identifier"):
        build_generation(registry=registry, spec=spec, quarantine_index=contaminated)


def test_confirmatory_generation_and_missing_prediction_fields_fail() -> None:
    registry, spec, quarantine = phase2_inputs()
    confirmatory = copy.deepcopy(spec)
    confirmatory["role"] = "confirmatory"
    with pytest.raises(Phase2ValidationError):
        build_generation(
            registry=registry, spec=confirmatory, quarantine_index=quarantine
        )

    malformed = checked_artifacts("training")[0][0]
    malformed = copy.deepcopy(malformed)
    del malformed["prediction_time"]["predicates"]
    with pytest.raises(Phase2ValidationError):
        validate_policy_example(malformed, spec=spec)


def test_registry_and_corpus_reject_cross_role_reuse() -> None:
    registry = load("registries/training-sources.v1.json")
    reused_registry = copy.deepcopy(registry)
    reused_registry["sources"][0]["artifact_sha256"] = reused_registry["sources"][1][
        "artifact_sha256"
    ]
    with pytest.raises(Phase2ValidationError, match="artifact hash is reused"):
        validate_training_registry(reused_registry)

    train_manifest = checked_artifacts("training")[2]
    train_report = checked_artifacts("training")[1]
    dev_manifest = copy.deepcopy(checked_artifacts("development")[2])
    dev_report = copy.deepcopy(checked_artifacts("development")[1])
    shared_world = train_manifest["dependency_ids"]["world"][0]
    for artifact in (dev_manifest, dev_report):
        worlds = artifact["dependency_ids"]["world"]
        artifact["dependency_ids"]["world"] = sorted({shared_world, *worlds[1:]})
    dev_manifest["integrity_report_sha256"] = canonical_sha256(dev_report)
    audit = audit_corpora([train_manifest, dev_manifest], [train_report, dev_report])
    assert audit["clean"] is False
    assert any(item["kind"] == "world" for item in audit["overlaps"])


def test_oracle_fault_and_tampered_target_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    examples, report, manifest = checked_artifacts("training")
    positive = next(
        item
        for item in examples
        if item["target"] == {"action": "return", "payload": {"truth": True}}
    )
    original = oracles.evaluate_proof_tree

    def faulty(*args: object, **kwargs: object) -> oracles.OracleResult:
        result = original(*args, **kwargs)
        return replace(result, action="abstain_unknown", payload=None)

    monkeypatch.setattr(oracles, "evaluate_proof_tree", faulty)
    with pytest.raises(Phase2OracleDisagreement):
        oracles.compare_oracles(
            positive["prediction_time"],
            positive["query"],
            max_rule_firings=256,
            max_depth=16,
        )
    monkeypatch.setattr(oracles, "evaluate_proof_tree", original)

    registry, spec, quarantine = phase2_inputs()
    tampered = copy.deepcopy(examples)
    tampered_index = next(
        index
        for index, item in enumerate(tampered)
        if item["example_id"] == positive["example_id"]
    )
    tampered[tampered_index]["target"] = {
        "action": "abstain_unknown",
        "payload": None,
    }
    with pytest.raises(Phase2IntegrityError, match="examples differ"):
        verify_generation(
            registry=registry,
            spec=spec,
            quarantine_index=quarantine,
            examples=tampered,
            report=report,
            manifest=manifest,
            observed_examples_identity=manifest["examples"],
        )


def test_phase2_cli_round_trip_and_refuses_output_collision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "examples.jsonl"
    report = tmp_path / "integrity.json"
    manifest = tmp_path / "manifest.json"
    common = [
        "--registry",
        str(ROOT / "registries/training-sources.v1.json"),
        "--spec",
        str(ROOT / "registries/phase2.generator.training.v1.json"),
        "--quarantine",
        str(ROOT / "quarantine/phase2-public-reservations.v1.json"),
    ]
    generate = [
        "procedural",
        "generate",
        *common,
        "--output",
        str(output),
        "--report",
        str(report),
        "--manifest",
        str(manifest),
    ]
    assert phase2_main(generate) == 0
    capsys.readouterr()
    assert (
        phase2_main(
            [
                "procedural",
                "verify",
                *common,
                "--examples",
                str(output),
                "--report",
                str(report),
                "--manifest",
                str(manifest),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert phase2_main(generate) == 2
    captured = capsys.readouterr()
    assert "refusing to overwrite output" in captured.err


def test_phase2_output_rejects_symlinked_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(Phase2IntegrityError, match="traverses a symbolic link"):
        write_artifact_set_exclusive({alias / "artifact.json": b"{}\n"})


def test_phase2_artifacts_are_semantically_complete_and_not_training_authority() -> (
    None
):
    for role in ("training", "development"):
        examples, report, manifest = checked_artifacts(role)
        validate_artifact(report)
        validate_artifact(manifest)
        assert report["complete"] and manifest["complete"]
        assert report["blockers"] == manifest["blockers"] == []
        assert report["training_authorized"] is False
        assert manifest["training_authorized"] is False
        assert all(example["training_authorized"] is False for example in examples)
    audit = load("fixtures/phase2/corpus-audit.v1.json")
    validate_artifact(audit)
    assert audit["training_authorized"] is False
