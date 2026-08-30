from __future__ import annotations

import copy
from pathlib import Path

import pytest

from hippocampus_foundation.phase0.canonical import canonical_bytes, canonical_sha256
from hippocampus_foundation.read_run.cli import build_parser
from hippocampus_foundation.read_run.contracts import (
    FROZEN_PREREGISTRATION_JSON_SHA256,
    FROZEN_PREREGISTRATION_MARKDOWN_SHA256,
    FROZEN_TRAINING_CONFIG_SHA256,
    validate_preregistration,
)
from hippocampus_foundation.read_run.errors import (
    GenerationError,
    IntegrityGateError,
    TrainingBlocked,
)
from hippocampus_foundation.read_run.evaluation import (
    apply_preregistered_decision,
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.gates import (
    dire_gate,
    direct_pool_invariance_gate,
    dual_oracle_gate,
    gamma_measurement_gate,
    gold_swap_noninterference_gate,
    select_main_budget,
    wilson_upper_bound,
)
from hippocampus_foundation.read_run.generator import (
    BUDGET_CANDIDATES,
    GAMMA_BUCKETS,
    GeneratedEpisode,
    generate_episode,
    generate_split,
    structural_bfs_pool,
)
from hippocampus_foundation.read_run.io import (
    model_input_bytes,
    read_generated_split,
    validate_generated_split_artifacts,
    write_generated_split,
)
from hippocampus_foundation.read_run.model import (
    expected_trainable_parameter_count,
    require_torch,
    trainable_parameter_count,
)
from hippocampus_foundation.read_run.oracle import independently_solve
from hippocampus_foundation.read_run.reports import main_report, screening_report
from hippocampus_foundation.read_run.reproducibility import (
    double_execution_gate,
    validate_double_execution_record,
)
from hippocampus_foundation.read_run.seed import seed_commitment

TEST_SEED = bytes(range(32))


def _episode(
    index: int = 0, gamma: float = 0.0, mask: int | None = 1
) -> GeneratedEpisode:
    return generate_episode(
        TEST_SEED,
        split="test-fixture",
        index=index,
        count=60,
        gamma=gamma,
        gold_mask=mask,
    )


def test_preregistration_and_training_config_are_digest_locked() -> None:
    observed = validate_preregistration()
    assert observed["preregistration_json_sha256"] == FROZEN_PREREGISTRATION_JSON_SHA256
    assert (
        observed["preregistration_markdown_sha256"]
        == FROZEN_PREREGISTRATION_MARKDOWN_SHA256
    )
    assert observed["training_config_sha256"] == FROZEN_TRAINING_CONFIG_SHA256
    assert observed["preregistration"]["heldout_seed_sha256"] == (
        "sha256:6183dc36b8a9fededaee99db385013d33785bc75de531937e65115d6d770c663"
    )


def test_generation_is_balanced_and_split_domain_separated() -> None:
    train = list(generate_split(TEST_SEED, split="test-fixture", count=60, gamma=0.0))
    assert sum(item.hidden["abstain"] for item in train) == 15
    masks = [
        item.hidden["gold_assertion_mask"]
        for item in train
        if not item.hidden["abstain"]
    ]
    assert {mask: masks.count(mask) for mask in range(1, 16)} == {
        mask: 3 for mask in range(1, 16)
    }
    other = generate_episode(
        TEST_SEED,
        split="screen",
        index=0,
        count=20,
        gamma=0.0,
        gold_mask=1,
    )
    assert train[0].paired_world_id != other.paired_world_id
    assert seed_commitment(TEST_SEED) not in model_input_bytes(train[0]).decode()


def test_independent_oracle_agrees_and_teacher_contains_all_branch_actions() -> None:
    episodes = [
        _episode(index, gamma, (index % 15) + 1)
        for index, gamma in enumerate(GAMMA_BUCKETS)
    ]
    assert dual_oracle_gate(episodes)["passed"] is True
    for episode in episodes:
        oracle = independently_solve(episode.visible)
        assert oracle == {
            key: episode.hidden[key]
            for key in (
                "target_nodes",
                "valid_routes",
                "teacher_actions",
                "abstain",
                "gold_assertion_mask",
                "greedy_wrong_count",
                "path_step_count",
                "measured_gamma",
            )
        }
        assert any(len(item["edge_ids"]) == 2 for item in oracle["teacher_actions"])


def test_oracle_disagrees_with_mutated_construction_truth() -> None:
    episode = _episode()
    changed = copy.deepcopy(episode)
    changed.hidden["gold_assertion_mask"] = 15
    with pytest.raises(IntegrityGateError, match="dual oracle disagreement"):
        dual_oracle_gate([changed])


def test_gamma_is_empirical_and_close_for_each_bucket() -> None:
    for gamma in GAMMA_BUCKETS:
        episodes = generate_split(
            TEST_SEED, split="test-fixture", count=600, gamma=gamma
        )
        result = gamma_measurement_gate(episodes, requested_gamma=gamma)
        assert abs(result["measured_gamma"] - gamma) <= 0.03


def test_gold_swap_serializer_has_a_strict_visible_allowlist() -> None:
    episode = _episode()
    assert gold_swap_noninterference_gate([episode])["passed"] is True
    leaked = copy.deepcopy(episode)
    leaked.visible["gold_assertion_mask"] = 1
    with pytest.raises(IntegrityGateError, match="hidden fields entered"):
        model_input_bytes(leaked)


def test_direct_pool_is_similarity_independent_and_gamma_invariant() -> None:
    by_gamma = {
        gamma: [
            generate_episode(
                TEST_SEED,
                split="test-fixture",
                index=index,
                count=60,
                gamma=gamma,
                gold_mask=(index % 15) + 1,
            )
            for index in range(60)
        ]
        for gamma in GAMMA_BUCKETS
    }
    for budget in BUDGET_CANDIDATES:
        expected = structural_bfs_pool(by_gamma[0.0][0].visible, budget)
        mutated = copy.deepcopy(by_gamma[0.0][0].visible)
        for edge in mutated["edges"]:
            edge["query_similarity_ppm"] = 1_000_000 - edge["query_similarity_ppm"]
        assert structural_bfs_pool(mutated, budget) == expected
    report = direct_pool_invariance_gate(by_gamma)
    assert report["passed"] is True
    for values in report["coverage"].values():
        assert len(set(values.values())) == 1
    with pytest.raises(IntegrityGateError, match="no preregistered budget"):
        select_main_budget(report)


def test_dire_removes_reachability_without_changing_local_marginals() -> None:
    episodes = [_episode(index, 0.2, (index % 15) + 1) for index in range(20)]
    assert dire_gate(episodes)["episode_count"] == 20


def test_deterministic_atomic_split_io_and_private_boundary(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    public_a, private_a = write_generated_split(
        master_seed=TEST_SEED,
        split="test-fixture",
        count=60,
        gamma=0.2,
        destination=first,
    )
    public_b, private_b = write_generated_split(
        master_seed=TEST_SEED,
        split="test-fixture",
        count=60,
        gamma=0.2,
        destination=second,
    )
    assert public_a == public_b
    assert private_a == private_b
    assert "hidden_sha256" not in public_a
    assert "hidden_sha256" in private_a
    _public, _private, artifacts = validate_generated_split_artifacts(
        first, expected_seed_commitment=seed_commitment(TEST_SEED)
    )
    assert set(artifacts) == {
        "visible.jsonl.gz",
        "hidden.jsonl.gz",
        "manifest.public.json",
        "manifest.private.json",
    }
    with pytest.raises(IntegrityGateError, match="another seed"):
        validate_generated_split_artifacts(
            first, expected_seed_commitment="sha256:" + "0" * 64
        )
    for name in (
        "visible.jsonl.gz",
        "hidden.jsonl.gz",
        "manifest.public.json",
        "manifest.private.json",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    changed_stream = second / "visible.jsonl.gz"
    changed_stream.write_bytes(changed_stream.read_bytes() + b"\x00")
    with pytest.raises(IntegrityGateError, match="differ from their manifests"):
        validate_generated_split_artifacts(second)
    assert (first / "hidden.jsonl.gz").stat().st_mode & 0o777 == 0o600
    assert len(list(read_generated_split(first))) == 60
    with pytest.raises(GenerationError, match="refusing to overwrite"):
        write_generated_split(
            master_seed=TEST_SEED,
            split="test-fixture",
            count=60,
            gamma=0.2,
            destination=first,
        )


def test_fresh_process_double_execution(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.write_bytes(TEST_SEED)
    seed.chmod(0o600)
    result = double_execution_gate(
        seed_path=seed,
        split="screen",
        count=60,
        gamma=0.3,
        timeout_seconds=60,
        test_mode=True,
    )
    assert result["passed"] is True
    assert set(result["artifact_sha256s"]) == {
        "visible.jsonl.gz",
        "hidden.jsonl.gz",
        "manifest.public.json",
        "manifest.private.json",
    }
    expected = tmp_path / "expected"
    write_generated_split(
        master_seed=TEST_SEED,
        split="screen",
        count=60,
        gamma=0.3,
        destination=expected,
    )
    assert (
        validate_double_execution_record(
            result,
            dataset_root=expected,
            gamma=0.3,
            expected_count=60,
        )["passed"]
        is True
    )
    forged = copy.deepcopy(result)
    forged["artifact_sha256s"]["visible.jsonl.gz"] = "sha256:" + "0" * 64
    with pytest.raises(IntegrityGateError, match="not bound"):
        validate_double_execution_record(
            forged,
            dataset_root=expected,
            gamma=0.3,
            expected_count=60,
        )


def test_exact_set_credit_also_requires_complete_valid_proof() -> None:
    episode = _episode(mask=7)
    edge_ids = list(range(len(episode.visible["edges"])))
    route_edges = {edge for route in episode.hidden["valid_routes"] for edge in route}
    scores = [1.0 if edge in route_edges else -1.0 for edge in edge_ids]
    routes = decode_best_routes(episode.visible, edge_ids, scores)
    result = score_prediction(episode, predicted_class=7, recorded_routes=routes)
    assert result["exact_correct"] is True
    assert (
        score_prediction(episode, predicted_class=7, recorded_routes=routes[:1])[
            "exact_correct"
        ]
        is False
    )


def _summary(gamma: float, arm: str, value: float, seed: int) -> dict:
    return {
        "gamma": gamma,
        "arm": arm,
        "model_seed": seed,
        "budget": 64,
        "non_abstain_exact_set_accuracy": value,
    }


def test_frozen_decision_rule_and_exact_seed_separation() -> None:
    results = []
    for gamma in GAMMA_BUCKETS:
        for seed, direct in zip((1729, 2718, 3141), (0.50, 0.51, 0.52), strict=True):
            gap = 0.0 if gamma == 0.0 else (0.06 if gamma == 0.4 else 0.03)
            results.append(_summary(gamma, "DIRECT", direct, seed))
            results.append(_summary(gamma, "TRAV", direct + gap, seed))
    decision = apply_preregistered_decision(results)
    assert decision["decision"] == "positive"
    assert decision["gamma_04_complete_seed_range_separation"] is True
    assert decision["gamma_04_exact_permutation_p_one_sided"] == 0.05


def test_one_sided_wilson_bound_not_point_estimate() -> None:
    assert wilson_upper_bound(1_500, 22_500) > 1 / 15
    assert wilson_upper_bound(1_500, 22_500) < 1 / 15 + 0.01


def test_cli_keeps_torch_optional_and_training_explicit() -> None:
    parser = build_parser()
    choices = next(
        action.choices for action in parser._actions if getattr(action, "choices", None)
    )
    assert set(choices) == {
        "contracts",
        "generate",
        "double-execute",
        "p0",
        "freeze",
        "train",
        "evaluate",
        "decision",
        "screening-report",
        "main-report",
    }
    try:
        torch, _nn, _functional = require_torch()
    except TrainingBlocked as exc:
        assert "requires PyTorch" in str(exc)
    else:
        assert torch.__name__ == "torch"


def test_equal_model_is_approximately_ten_million_parameters() -> None:
    config = validate_preregistration()["training_config"]
    expected = expected_trainable_parameter_count(config)
    assert 9_000_000 <= expected <= 11_000_000
    try:
        require_torch()
    except TrainingBlocked:
        return
    from hippocampus_foundation.read_run.model import build_read_model

    direct = build_read_model(config)
    trav = build_read_model(config)
    assert trainable_parameter_count(direct) == expected
    assert trainable_parameter_count(trav) == expected


def test_seed_commitment_is_not_raw_seed_or_model_input() -> None:
    commitment = seed_commitment(TEST_SEED)
    assert commitment.startswith("sha256:") and len(commitment) == 71
    episode = _episode()
    visible = canonical_bytes(episode.visible)
    assert TEST_SEED not in visible
    assert TEST_SEED.hex().encode() not in visible
    assert canonical_sha256(episode.visible).startswith("sha256:")


def _receipt(gamma: float, arm: str, seed: int, budget: int, stage: str) -> dict:
    return {
        "gamma": gamma,
        "arm": arm,
        "model_seed": seed,
        "budget": budget,
        "stage": stage,
        "parameter_count": 10_257_937,
        "initialization_sha256": f"sha256:{seed:064x}",
    }


def _evaluation_summary(
    gamma: float,
    arm: str,
    seed: int,
    budget: int,
    stage: str,
    split: str,
    accuracy: float,
) -> dict:
    return {
        "gamma": gamma,
        "arm": arm,
        "model_seed": seed,
        "budget": budget,
        "stage": stage,
        "split": split,
        "non_abstain_exact_set_accuracy": accuracy,
        "abstain_accuracy": 0.8,
        "proof_valid_fraction": 0.9,
    }


def test_reports_require_all_preregistered_runs_and_paired_fairness() -> None:
    screening_receipts = []
    screening_summaries = []
    for gamma in (0.0, 0.4):
        for arm in ("TRAV", "DIRECT"):
            for budget in BUDGET_CANDIDATES:
                screening_receipts.append(
                    _receipt(gamma, arm, 1729, budget, "screening")
                )
                screening_summaries.append(
                    _evaluation_summary(
                        gamma,
                        arm,
                        1729,
                        budget,
                        "screening",
                        "screen",
                        0.5,
                    )
                )
    p0 = {
        "record_kind": "read_run_p0_report",
        "selected_main_budget": 64,
        "gates": [
            {
                "gate": "direct_pool_invariance",
                "passed": True,
                "coverage": {
                    "16": {f"{gamma:.1f}": 0.5 for gamma in GAMMA_BUCKETS},
                    "32": {f"{gamma:.1f}": 0.8 for gamma in GAMMA_BUCKETS},
                    "64": {f"{gamma:.1f}": 0.95 for gamma in GAMMA_BUCKETS},
                    "128": {f"{gamma:.1f}": 0.99 for gamma in GAMMA_BUCKETS},
                },
            }
        ],
    }
    report = screening_report(
        p0_report=p0,
        receipts=screening_receipts,
        failures=[],
        summaries=screening_summaries,
    )
    assert report["expected_run_count"] == 16
    assert report["main_sweep_authorized"] is True

    main_receipts = []
    main_summaries = []
    for gamma in GAMMA_BUCKETS:
        for seed in (1729, 2718, 3141):
            for arm in ("TRAV", "DIRECT"):
                main_receipts.append(_receipt(gamma, arm, seed, 64, "main"))
                direct = 0.5 + (seed - 1729) / 100_000
                value = direct + (0.06 if arm == "TRAV" and gamma == 0.4 else 0.0)
                main_summaries.append(
                    _evaluation_summary(gamma, arm, seed, 64, "main", "holdout", value)
                )
    final = main_report(
        selected_budget=64,
        receipts=main_receipts,
        failures=[],
        summaries=main_summaries,
    )
    assert final["expected_run_count"] == 30
    assert final["decision"] == "positive"

    with pytest.raises(IntegrityGateError, match="summaries differ"):
        main_report(
            selected_budget=64,
            receipts=main_receipts,
            failures=[],
            summaries=main_summaries[:-1],
        )
