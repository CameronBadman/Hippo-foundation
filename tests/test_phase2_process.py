from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hippocampus_foundation.phase0.canonical import (
    canonical_bytes,
    canonical_sha256,
    sha256_bytes,
)
from hippocampus_foundation.phase0.v2 import (
    build_quarantine_contribution_v2,
    compile_quarantine_index_v2,
)
from hippocampus_foundation.phase2 import process_oracles
from hippocampus_foundation.phase2.cli import main as phase2_main
from hippocampus_foundation.phase2.errors import (
    Phase2IntegrityError,
    Phase2OracleDisagreement,
    Phase2QuarantineError,
    Phase2ValidationError,
)
from hippocampus_foundation.phase2.io import (
    bytes_identity,
    canonical_json_bytes,
    canonical_jsonl_bytes,
)
from hippocampus_foundation.phase2.process import (
    _quarantine_descriptor,
    _scenario_for_ordinal,
    audit_corpora_v2,
    build_process_generation,
    replay_process_examples,
    verify_process_generation,
)
from hippocampus_foundation.phase2.process_types import ProcessInput, apply_patch
from hippocampus_foundation.phase2.v2 import (
    PROCESS_ACTIONS,
    PROCESS_DEPENDENCY_KINDS,
    bind_process_registry_spec,
    process_input_view,
    validate_process_artifact,
    validate_process_generator_spec,
    validate_schema_lock_v2,
    validate_training_registry_v2,
    validate_write_policy_example,
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


def inputs(role: str = "training") -> tuple[dict, dict, dict]:
    return (
        load("registries/training-sources.v2.json"),
        load(f"registries/phase2.process.{role}.v1.json"),
        load("quarantine/phase2-public-reservations.v2.json"),
    )


@pytest.fixture(scope="module")
def generated() -> dict[str, tuple[list[dict], dict, dict, dict]]:
    values = {}
    for role in ("training", "development"):
        registry, spec, quarantine = inputs(role)
        examples, report, manifest = build_process_generation(
            registry=registry, spec=spec, quarantine_index=quarantine
        )
        ledger = replay_process_examples(
            examples=examples, report=report, manifest=manifest
        )
        values[role] = examples, report, manifest, ledger
    return values


def test_v2_schema_registry_specs_and_roles_generate(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    assert set(validate_schema_lock_v2()) == {
        "artifact.schema.json",
        "generator-spec.schema.json",
        "process-state.schema.json",
        "proposal.schema.json",
        "registry.schema.json",
        "write-policy-example.schema.json",
    }
    registry = load("registries/training-sources.v2.json")
    validate_training_registry_v2(registry)
    legacy = load("registries/training-sources.v1.json")["sources"]
    assert registry["sources"][:2] == legacy
    for role in ("training", "development"):
        spec = inputs(role)[1]
        validate_process_generator_spec(spec)
        source = bind_process_registry_spec(registry, spec)
        assert source["admission_state"] == "declared"
        assert source["rights"]["review_status"] == "pending"
        examples, report, manifest, ledger = generated[role]
        assert len(examples) == 32
        assert all(value >= 2 for value in report["action_counts"].values())
        assert report["scenario_counts"] == {
            kind: {action: 2 for action in PROCESS_ACTIONS}
            for kind in ("direct", "near_miss")
        }
        assert report["oracle"]["agreement"] is True
        assert report["shortcut_diagnostics"]["blocked"] is False
        assert ledger["complete"] is True
        for artifact in (report, manifest, ledger):
            validate_process_artifact(artifact)
            assert artifact["training_authorized"] is False
        assert all(item["training_authorized"] is False for item in examples)

    pairs = [generated[role][1:3] for role in ("training", "development")]
    audit = audit_corpora_v2([pair[1] for pair in pairs], [pair[0] for pair in pairs])
    assert audit["clean"] is True
    assert audit["overlaps"] == []
    assert load("fixtures/phase2/process/corpus-audit.v2.json") == audit
    assert (
        ROOT / "fixtures/phase2/process/corpus-audit.v2.json"
    ).read_bytes() == canonical_json_bytes(audit)


def test_checked_process_artifacts_are_exact_deterministic_outputs(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    registry = load("registries/training-sources.v2.json")
    for role in ("training", "development"):
        examples, report, manifest, ledger = generated[role]
        prefix = f"fixtures/phase2/process/{role}"
        assert load_jsonl(f"{prefix}.examples.v1.jsonl") == examples
        assert load(f"{prefix}.integrity.v1.json") == report
        assert load(f"{prefix}.manifest.v1.json") == manifest
        assert load(f"{prefix}.replay.v1.json") == ledger
        assert (ROOT / f"{prefix}.examples.v1.jsonl").read_bytes() == (
            canonical_jsonl_bytes(examples)
        )
        for suffix, value in (
            ("integrity", report),
            ("manifest", manifest),
            ("replay", ledger),
        ):
            assert (ROOT / f"{prefix}.{suffix}.v1.json").read_bytes() == (
                canonical_json_bytes(value)
            )
        source = next(
            item
            for item in registry["sources"]
            if item["source_id"] == manifest["source_id"]
        )
        assert source["artifact_sha256"] == manifest["examples"]["sha256"]


def test_direct_cases_and_near_misses_use_conservative_actions(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    examples = generated["training"][0]
    by_ordinal = {item["provenance"]["ordinal"]: item for item in examples}
    spec = inputs("training")[1]
    for ordinal, example in by_ordinal.items():
        kind, associated_action, _neutral_mode = _scenario_for_ordinal(spec, ordinal)
        if kind == "direct":
            assert example["target"]["action"] == associated_action
        else:
            assert example["target"]["action"] != associated_action
        assert tuple(example["candidates"]) == PROCESS_ACTIONS
        metadata = json.dumps(
            {
                "id": example["example_id"],
                "dependencies": example["dependencies"],
                "provenance": example["provenance"],
            }
        )
        assert not any(f'"{action}"' in metadata for action in PROCESS_ACTIONS)


@pytest.mark.parametrize(
    ("structural_match", "blocking_condition", "reason"),
    [
        ("duplicate", "missing_evidence", "evidence_uncertain"),
        ("conflict", "missing_evidence", "evidence_uncertain"),
        ("duplicate", "high_risk", "risk_high"),
        ("conflict", "ambiguous_identity", "identity_uncertain"),
    ],
)
def test_structural_matches_cannot_bypass_conservative_gates(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
    structural_match: str,
    blocking_condition: str,
    reason: str,
) -> None:
    example = copy.deepcopy(
        next(
            item
            for item in generated["training"][0]
            if item["target"]["action"] == structural_match
        )
    )
    if blocking_condition == "missing_evidence":
        example["proposal"]["evidence"] = []
        example["visible_evidence_ids"] = []
    elif blocking_condition == "high_risk":
        example["proposal"]["risk_class"] = "high"
    else:
        example["candidate_frontier"][0]["identity_match"] = "ambiguous"
    result = process_oracles.compare_transition_oracles(
        ProcessInput.from_example(example)
    )
    assert result.action == "stage"
    target = result.target()
    assert reason in target["patch"]["operations"][0]["after"]["reason_codes"]


@pytest.mark.parametrize("direct_action", ["update", "deprecate"])
def test_revision_without_an_exact_target_is_staged(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
    direct_action: str,
) -> None:
    example = copy.deepcopy(
        next(
            item
            for item in generated["training"][0]
            if item["target"]["action"] == direct_action
        )
    )
    example["snapshot"]["edges"] = []
    subject_id = example["proposal"]["subject"]["node_id"]
    example["candidate_frontier"] = [
        {
            "candidate_id": f"candidate:{example['provenance']['ordinal']:06d}:fallback",
            "target_kind": "node",
            "target_id": subject_id,
            "identity_match": "exact",
            "scope_status": "in_scope",
        }
    ]
    example["snapshot_sha256"] = canonical_sha256(example["snapshot"])
    result = process_oracles.compare_transition_oracles(
        ProcessInput.from_example(example)
    )
    example["target"] = result.target()
    example["input_sha256"] = canonical_sha256(process_input_view(example))
    assert result.action == "stage"
    assert (
        "identity_uncertain"
        in example["target"]["patch"]["operations"][0]["after"]["reason_codes"]
    )
    validate_write_policy_example(example, spec=inputs("training")[1])


def test_every_patch_replays_and_rolls_back_exactly(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    for example in generated["training"][0]:
        original = canonical_bytes(example["snapshot"])
        patch = example["target"]["patch"]
        if patch is None:
            assert example["target"]["action"] == "ignore"
            assert example["target"]["rollback"]["kind"] == "identity"
            continue
        forward, _delta = apply_patch(example["snapshot"], patch)
        restored, _inverse = apply_patch(forward, patch, inverse=True)
        assert canonical_bytes(restored) == original
        assert canonical_sha256(forward) == patch["result_snapshot_sha256"]
        assert canonical_sha256(restored) == example["snapshot_sha256"]
        assert example["target"]["action"] != "ignore"
        if example["target"]["action"] in {"update", "deprecate"}:
            retired = patch["operations"][0]["after"]
            proposal = example["proposal"]
            assert retired["observation_time"] == proposal["observation_time"]
            assert retired["valid_time"]["end"] == proposal["valid_time"]["start"]
            assert set(example["visible_evidence_ids"]) <= {
                item["evidence_id"] for item in retired["provenance"]
            }


def test_generation_order_never_changes_another_example(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    examples = generated["training"][0]
    reversed_results = {
        item["example_id"]: process_oracles.compare_transition_oracles(
            ProcessInput.from_example(item)
        ).target()
        for item in reversed(examples)
    }
    assert reversed_results == {item["example_id"]: item["target"] for item in examples}


def test_oracle_fault_target_tamper_and_patch_precondition_fail(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example = next(item for item in generated["training"][0] if item["target"]["patch"])
    original = process_oracles.evaluate_copy_on_write_transition

    def faulty(value: ProcessInput) -> process_oracles.TransitionResult:
        result = original(value)
        target = result.target()
        target["postconditions"][0]["expected"] = "sha256:" + "0" * 64
        return replace(
            result,
            target_bytes=canonical_bytes(target),
        )

    monkeypatch.setattr(process_oracles, "evaluate_copy_on_write_transition", faulty)
    with pytest.raises(Phase2OracleDisagreement):
        process_oracles.compare_transition_oracles(ProcessInput.from_example(example))
    monkeypatch.setattr(process_oracles, "evaluate_copy_on_write_transition", original)

    tampered = copy.deepcopy(example)
    tampered["target"]["action"] = "ignore"
    with pytest.raises(Phase2ValidationError):
        validate_write_policy_example(tampered, spec=inputs("training")[1])

    changed_snapshot = copy.deepcopy(example["snapshot"])
    changed_snapshot["nodes"][0]["label"] += " changed"
    with pytest.raises(Phase2IntegrityError, match="base hash mismatch"):
        apply_patch(changed_snapshot, example["target"]["patch"])


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "risk_policy",
        "quarantine",
        "provenance",
        "snapshot_sha256",
        "input_sha256",
    ],
)
def test_process_contracts_fail_closed_on_missing_prediction_evidence(
    generated: dict[str, tuple[list[dict], dict, dict, dict]], field: str
) -> None:
    malformed = copy.deepcopy(generated["training"][0][0])
    del malformed[field]
    with pytest.raises(Phase2ValidationError):
        validate_write_policy_example(malformed, spec=inputs("training")[1])


@pytest.mark.parametrize(
    "path",
    [
        ("proposal", "observation_time"),
        ("proposal", "valid_time"),
        ("proposal", "evidence"),
        ("risk_policy", "error_costs"),
        ("target", "preconditions"),
        ("target", "postconditions"),
        ("target", "cost_record"),
        ("target", "rollback"),
    ],
)
def test_process_contracts_reject_missing_nested_governance_fields(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
    path: tuple[str, str],
) -> None:
    malformed = copy.deepcopy(generated["training"][0][0])
    del malformed[path[0]][path[1]]
    with pytest.raises(Phase2ValidationError):
        validate_write_policy_example(malformed, spec=inputs("training")[1])


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("future_node", "after the snapshot"),
        ("future_provenance", "future provenance"),
        ("future_proposal", "future information"),
        ("dangling_candidate", "dangling target"),
        ("wrong_exact_node", "wrong subject"),
        ("unbound_entities", "do not bind snapshot nodes"),
        ("unsorted_candidates", "must be sorted"),
    ],
)
def test_temporal_frontier_and_entity_lineage_fail_closed(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
    mutation: str,
    message: str,
) -> None:
    if mutation == "unsorted_candidates":
        example = copy.deepcopy(
            next(
                item
                for item in generated["training"][0]
                if len(item["candidate_frontier"]) == 2
            )
        )
        example["candidate_frontier"].reverse()
    else:
        example = copy.deepcopy(generated["training"][0][0])
        if mutation == "future_node":
            example["snapshot"]["nodes"][0]["observation_time"] = "2027-01-01T00:00:00Z"
        elif mutation == "future_provenance":
            example["snapshot"]["nodes"][0]["provenance"][0]["observed_at"] = (
                "2026-01-15T00:00:00Z"
            )
        elif mutation == "future_proposal":
            example["proposal"]["observation_time"] = "2027-01-01T00:00:00Z"
        elif mutation == "dangling_candidate":
            example["candidate_frontier"][0]["target_id"] = "node:missing"
        elif mutation == "wrong_exact_node":
            subject = example["proposal"]["subject"]["node_id"]
            example["candidate_frontier"][0]["target_id"] = next(
                item["node_id"]
                for item in example["snapshot"]["nodes"]
                if item["node_id"] != subject
            )
        else:
            example["dependencies"]["entity_ids"] = example["dependencies"][
                "entity_ids"
            ][1:]
    example["snapshot_sha256"] = canonical_sha256(example["snapshot"])
    example["input_sha256"] = canonical_sha256(process_input_view(example))
    with pytest.raises(Phase2ValidationError, match=message):
        validate_write_policy_example(example, spec=inputs("training")[1])


@pytest.mark.parametrize(
    ("bound", "message"),
    [("max_patch_operations", "patch-operation"), ("max_nodes", "node bound")],
)
def test_generator_spec_bounds_are_enforced_on_examples(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
    bound: str,
    message: str,
) -> None:
    example = copy.deepcopy(
        next(
            item
            for item in generated["training"][0]
            if item["target"]["action"] == "update"
        )
    )
    spec = copy.deepcopy(inputs("training")[1])
    spec["bounds"][bound] = 1 if bound == "max_patch_operations" else 2
    example["provenance"]["spec_sha256"] = canonical_sha256(spec)
    with pytest.raises(Phase2ValidationError, match=message):
        validate_write_policy_example(example, spec=spec)


def test_label_metadata_and_cross_role_family_reuse_are_rejected(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    example = copy.deepcopy(generated["training"][0][0])
    example["dependencies"]["template_id"] = "template:attach"
    with pytest.raises(Phase2ValidationError, match="target-bearing"):
        validate_write_policy_example(example, spec=inputs("training")[1])

    registry = load("registries/training-sources.v2.json")
    process_sources = [
        item
        for item in registry["sources"]
        if item["generator_id"] == "hf-process-state-v1"
    ]
    process_sources[0]["dependency_families"]["operation"] = process_sources[1][
        "dependency_families"
    ]["operation"]
    with pytest.raises(Phase2ValidationError, match="reused across roles"):
        validate_training_registry_v2(registry)


def test_quarantine_dependency_collision_blocks_generation() -> None:
    registry, spec, quarantine = inputs("training")
    contaminated = copy.deepcopy(quarantine)
    contaminated["identifiers"].append(
        {
            "namespace": "generator.operation",
            "value": f"{spec['dependency_families']['operation']}:o0000",
            "source_version": None,
        }
    )
    with pytest.raises(Phase2QuarantineError, match="exact_identifier"):
        build_process_generation(
            registry=registry, spec=spec, quarantine_index=contaminated
        )


def test_quarantine_descriptor_covers_every_process_overlap_surface(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    example = generated["training"][0][0]
    descriptor = _quarantine_descriptor(example)
    namespaces = {item["namespace"] for item in descriptor["identifiers"]}
    assert namespaces == {f"generator.{kind}" for kind in PROCESS_DEPENDENCY_KINDS} | {
        "process.snapshot",
        "process.snapshot_sha256",
        "process.proposal",
        "process.entity",
    }
    assert descriptor["raw_sha256"] == example["input_sha256"]
    assert descriptor["normalized_sha256"].startswith("sha256:")
    assert descriptor["fingerprint"]["fingerprint_id"].endswith(":process-input")
    assert len(descriptor["fingerprint"]["minhash"]) == 128


def test_process_reservation_index_derives_from_real_fixture_bytes() -> None:
    source = load("fixtures/phase2/process/quarantine-reservation-source.v1.json")
    adapter = load("fixtures/phase2/process/quarantine-reservation-adapter.v1.json")
    envelope = load("fixtures/phase2/process/quarantine-reservation.envelope.v1.json")
    contribution = load(
        "fixtures/phase2/process/quarantine-reservation.contribution.v1.json"
    )
    index = load("quarantine/phase2-public-reservations.v2.json")
    assert envelope["archive_sha256"] == sha256_bytes(
        (
            ROOT / "fixtures/phase2/process/quarantine-reservation-source.v1.json"
        ).read_bytes()
    )
    assert envelope["adapter_sha256"] == sha256_bytes(
        (
            ROOT / "fixtures/phase2/process/quarantine-reservation-adapter.v1.json"
        ).read_bytes()
    )
    assert envelope["adapter_id"] == adapter["adapter_id"]
    assert adapter["behavior"] == "copy_exact_public_process_identifiers"
    [record] = envelope["records"]
    assert record["selectors"]["identifiers"] == source["identifiers"]
    assert record["expected_dependency_units"] == source["identifiers"]
    assert record["resolved_dependency_units"] == source["identifiers"]
    assert record["unresolved_dependency_units"] == []
    assert build_quarantine_contribution_v2(envelope) == contribution
    legacy = load("fixtures/phase2/quarantine-reservation.contribution.v1.json")
    assert (
        compile_quarantine_index_v2([legacy, contribution], index_id=index["index_id"])
        == index
    )


def test_process_verify_rejects_tampered_ledger(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    examples, report, manifest, ledger = generated["training"]
    registry, spec, quarantine = inputs("training")
    assert verify_process_generation(
        registry=registry,
        spec=spec,
        quarantine_index=quarantine,
        examples=examples,
        report=report,
        manifest=manifest,
        ledger=ledger,
        observed_examples_identity=bytes_identity(canonical_jsonl_bytes(examples)),
    )["ok"]
    altered = copy.deepcopy(ledger)
    altered["entries"][0]["rollback_exact"] = False
    with pytest.raises(Phase2IntegrityError, match="ledger differs"):
        verify_process_generation(
            registry=registry,
            spec=spec,
            quarantine_index=quarantine,
            examples=examples,
            report=report,
            manifest=manifest,
            ledger=altered,
            observed_examples_identity=manifest["examples"],
        )

    with pytest.raises(Phase2IntegrityError, match="manifest identity"):
        replay_process_examples(
            examples=examples[:-1], report=report, manifest=manifest
        )


def test_process_cli_surface_and_collision_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    examples = tmp_path / "examples.jsonl"
    report = tmp_path / "report.json"
    manifest = tmp_path / "manifest.json"
    ledger = tmp_path / "ledger.json"
    common = [
        "--registry",
        str(ROOT / "registries/training-sources.v2.json"),
        "--spec",
        str(ROOT / "registries/phase2.process.training.v1.json"),
        "--quarantine",
        str(ROOT / "quarantine/phase2-public-reservations.v2.json"),
    ]
    generate = [
        "process",
        "generate",
        *common,
        "--output",
        str(examples),
        "--report",
        str(report),
        "--manifest",
        str(manifest),
    ]
    assert phase2_main(generate) == 0
    capsys.readouterr()
    replay = [
        "process",
        "replay",
        *common,
        "--examples",
        str(examples),
        "--report",
        str(report),
        "--manifest",
        str(manifest),
        "--ledger",
        str(ledger),
    ]
    assert phase2_main(replay) == 0
    capsys.readouterr()
    verify = [
        "process",
        "verify",
        *common,
        "--examples",
        str(examples),
        "--report",
        str(report),
        "--manifest",
        str(manifest),
        "--ledger",
        str(ledger),
    ]
    assert phase2_main(verify) == 0
    capsys.readouterr()
    assert phase2_main(generate) == 2
    assert "refusing to overwrite output" in capsys.readouterr().err


def test_process_dependencies_are_exact_and_role_disjoint(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    left = generated["training"][2]
    right = generated["development"][2]
    assert set(left["dependency_ids"]) == set(PROCESS_DEPENDENCY_KINDS)
    for kind in PROCESS_DEPENDENCY_KINDS:
        assert set(left["dependency_ids"][kind]).isdisjoint(
            right["dependency_ids"][kind]
        )
    assert set(left["entity_ids"]).isdisjoint(right["entity_ids"])
    assert set(left["snapshot_sha256s"]).isdisjoint(right["snapshot_sha256s"])


def test_v2_corpus_audit_detects_every_cross_role_overlap_surface(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    base_manifests = {
        role: copy.deepcopy(generated[role][2]) for role in ("training", "development")
    }
    base_reports = {
        role: copy.deepcopy(generated[role][1]) for role in ("training", "development")
    }

    def replace_first(values: list[str], replacement: str) -> list[str]:
        return sorted({replacement, *values[1:]})

    for kind in (
        "artifact_sha256",
        "input_sha256",
        "normalized_input_sha256",
        "snapshot_sha256",
        "entity_id",
        *PROCESS_DEPENDENCY_KINDS,
    ):
        manifests = copy.deepcopy(base_manifests)
        reports = copy.deepcopy(base_reports)
        left_manifest = manifests["training"]
        right_manifest = manifests["development"]
        right_report = reports["development"]
        if kind == "artifact_sha256":
            shared = left_manifest["examples"]["sha256"]
            right_manifest["examples"]["sha256"] = shared
            right_report["examples_sha256"] = shared
        elif kind == "entity_id":
            shared = left_manifest["entity_ids"][0]
            replacement = replace_first(right_manifest["entity_ids"], shared)
            right_manifest["entity_ids"] = replacement
            right_report["entity_ids"] = replacement
        elif kind in PROCESS_DEPENDENCY_KINDS:
            shared = left_manifest["dependency_ids"][kind][0]
            replacement = replace_first(right_manifest["dependency_ids"][kind], shared)
            right_manifest["dependency_ids"][kind] = replacement
            right_report["dependency_ids"][kind] = replacement
        else:
            field = f"{kind}s"
            shared = left_manifest[field][0]
            replacement = replace_first(right_manifest[field], shared)
            right_manifest[field] = replacement
            right_report[field] = replacement
        right_manifest["transition_report_sha256"] = canonical_sha256(right_report)
        audit = audit_corpora_v2(list(manifests.values()), list(reports.values()))
        assert audit["clean"] is False
        assert kind in {item["kind"] for item in audit["overlaps"]}


def test_v2_corpus_audit_cross_checks_manifest_report_fields_and_mixed_v1_v2(
    generated: dict[str, tuple[list[dict], dict, dict, dict]],
) -> None:
    manifests = [
        copy.deepcopy(generated[role][2]) for role in ("training", "development")
    ]
    reports = [
        copy.deepcopy(generated[role][1]) for role in ("training", "development")
    ]
    reports[1]["action_counts"]["attach"] -= 1
    reports[1]["action_counts"]["conflict"] += 1
    manifests[1]["transition_report_sha256"] = canonical_sha256(reports[1])
    with pytest.raises(Phase2IntegrityError, match="action counts disagree"):
        audit_corpora_v2(manifests, reports)

    mixed_manifests = [
        load("fixtures/phase2/training.manifest.v1.json"),
        load("fixtures/phase2/development.manifest.v1.json"),
        generated["training"][2],
        generated["development"][2],
    ]
    mixed_reports = [
        load("fixtures/phase2/training.integrity.v1.json"),
        load("fixtures/phase2/development.integrity.v1.json"),
        generated["training"][1],
        generated["development"][1],
    ]
    audit = audit_corpora_v2(mixed_manifests, mixed_reports)
    assert audit["clean"] is True
    assert len(audit["source_ids"]) == 4
    assert load("fixtures/phase2/process/all-phase2-corpus-audit.v2.json") == audit
    assert (
        ROOT / "fixtures/phase2/process/all-phase2-corpus-audit.v2.json"
    ).read_bytes() == canonical_json_bytes(audit)
