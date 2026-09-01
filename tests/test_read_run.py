from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

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
    DECONFOUNDED_STRATUM,
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
    validate_model_input_fields,
    write_generated_split,
)
from hippocampus_foundation.read_run.model import (
    expected_trainable_parameter_count,
    require_torch,
    trainable_parameter_count,
)
from hippocampus_foundation.read_run.oracle import independently_solve
from hippocampus_foundation.read_run.p0 import _run_units, evaluate_p0
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
    # Amendment 02: coverage is reported per stratum and never aggregated away,
    # and every stratum stays gamma-invariant.
    for stratum in report["coverage_by_stratum"].values():
        for values in stratum.values():
            assert len(set(values.values())) == 1
    assert report["gated_stratum"] == DECONFOUNDED_STRATUM
    assert sum(report["episode_count_by_stratum"].values()) == 60

    # Selection gates on the de-confounded stratum only. The aggregate stays
    # below the threshold here, which is exactly the case Amendment 02 exists
    # for: gating on it would delete the deep stratum rather than de-confound.
    gated = report["coverage_by_stratum"][DECONFOUNDED_STRATUM]
    selected = select_main_budget(report)
    assert selected in BUDGET_CANDIDATES
    assert gated[str(selected)]["0.0"] > 0.9
    assert all(
        gated[str(budget)]["0.0"] <= 0.9
        for budget in BUDGET_CANDIDATES
        if budget < selected
    )


def test_budget_selection_ignores_the_coverage_limited_strata() -> None:
    # A deep stratum with zero coverage must not block selection, and must not
    # be silently folded into the gated number either.
    report = {
        "gate": "direct_pool_invariance",
        "passed": True,
        "gated_stratum": DECONFOUNDED_STRATUM,
        "episode_count_by_stratum": {
            DECONFOUNDED_STRATUM: 1518,
            "hops_5": 412,
            "hops_6_plus": 70,
        },
        "coverage_by_stratum": {
            DECONFOUNDED_STRATUM: {
                "16": {f"{gamma:.1f}": 0.31 for gamma in GAMMA_BUCKETS},
                "32": {f"{gamma:.1f}": 0.54 for gamma in GAMMA_BUCKETS},
                "64": {f"{gamma:.1f}": 0.80 for gamma in GAMMA_BUCKETS},
                "128": {f"{gamma:.1f}": 1.0 for gamma in GAMMA_BUCKETS},
            },
            "hops_5": {
                str(budget): {f"{gamma:.1f}": 0.0 for gamma in GAMMA_BUCKETS}
                for budget in BUDGET_CANDIDATES
            },
            "hops_6_plus": {
                str(budget): {f"{gamma:.1f}": 0.0 for gamma in GAMMA_BUCKETS}
                for budget in BUDGET_CANDIDATES
            },
        },
    }
    assert select_main_budget(report) == 128


def test_budget_selection_still_blocks_when_no_candidate_clears_threshold() -> None:
    blocked = {
        "gate": "direct_pool_invariance",
        "passed": True,
        "gated_stratum": DECONFOUNDED_STRATUM,
        "episode_count_by_stratum": {DECONFOUNDED_STRATUM: 1518},
        "coverage_by_stratum": {
            DECONFOUNDED_STRATUM: {
                str(budget): {f"{gamma:.1f}": 0.5 for gamma in GAMMA_BUCKETS}
                for budget in BUDGET_CANDIDATES
            }
        },
    }
    with pytest.raises(IntegrityGateError, match="no preregistered budget"):
        select_main_budget(blocked)


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
                "gated_stratum": DECONFOUNDED_STRATUM,
                "episode_count_by_stratum": {DECONFOUNDED_STRATUM: 1518},
                "coverage_by_stratum": {
                    DECONFOUNDED_STRATUM: {
                        "16": {f"{gamma:.1f}": 0.5 for gamma in GAMMA_BUCKETS},
                        "32": {f"{gamma:.1f}": 0.8 for gamma in GAMMA_BUCKETS},
                        "64": {f"{gamma:.1f}": 0.95 for gamma in GAMMA_BUCKETS},
                        "128": {f"{gamma:.1f}": 0.99 for gamma in GAMMA_BUCKETS},
                    }
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


def test_batched_trav_matches_the_serial_traversal() -> None:
    """The batched traversal must make the same decisions as the serial one.

    `_forward_trav_one` is the executable specification for TRAV. Batching is
    a performance change only: it may reassociate floating-point reductions,
    but it must never expand a different node, choose a different edge, or
    change a predicted class.
    """

    torch = pytest.importorskip("torch")
    import json

    from hippocampus_foundation.read_run.model import build_read_model

    config = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "experiments/read_run_v1/training-config.v1.json"
        ).read_text(encoding="utf-8")
    )
    episodes = [_episode(index, 0.2, (index % 15) + 1) for index in range(8)]
    visible = [episode.visible for episode in episodes]

    torch.manual_seed(1729)
    model = build_read_model(config).eval()
    with torch.no_grad():
        serial = [model._forward_trav_one(item, 16) for item in visible]
        batched = model.forward_trav_batched(visible, 16)

    assert [item["edge_ids"][0] for item in serial] == batched["edge_ids"]
    reference_logits = torch.cat([item["logits"] for item in serial], dim=0)
    assert torch.allclose(reference_logits, batched["logits"], atol=1e-4)
    assert (reference_logits.argmax(-1) == batched["logits"].argmax(-1)).all()


def test_batched_trav_runs_under_the_autocast_training_configuration() -> None:
    """The batched traversal must work in the dtype regime training uses.

    `train_arm` wraps the forward pass in `torch.autocast(bfloat16)` on CUDA,
    where the query encoder and the state cell can return different dtypes.
    The batched path keeps one state tensor for the whole microbatch and must
    reconcile them; the serial path never had to, because it rebinds `state`
    per episode. An equivalence test that only runs in fp32 does not exercise
    this, which is exactly how a dtype fault reached a sweep.
    """

    torch = pytest.importorskip("torch")
    import json

    from hippocampus_foundation.read_run.model import build_read_model

    config = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "experiments/read_run_v1/training-config.v1.json"
        ).read_text(encoding="utf-8")
    )
    episodes = [_episode(index, 0.2, (index % 15) + 1) for index in range(4)]
    visible = [episode.visible for episode in episodes]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32

    torch.manual_seed(1729)
    model = build_read_model(config).to(device).eval()
    with torch.no_grad(), torch.autocast(device_type=device, dtype=dtype):
        batched = model.forward_trav_batched(visible, 16)
        serial = [model._forward_trav_one(item, 16) for item in visible]

    assert [item["edge_ids"][0] for item in serial] == batched["edge_ids"]
    assert batched["logits"].shape[0] == len(visible)


def test_field_validation_matches_the_serializing_check_exactly() -> None:
    """`validate_model_input_fields` must accept and reject exactly what
    `model_input_bytes` does.

    This is load-bearing, not a style test. The training and evaluation loops
    now call the cheap check instead of the serializing one, so if the two ever
    diverge, a payload that `model_input_bytes` would have refused could reach a
    model. That is the leakage control this experiment rests on, and a failure
    here invalidates any run made under the divergence, not just CI.
    """

    episode = _episode()
    assert validate_model_input_fields(episode) is None
    assert model_input_bytes(episode)

    missing = copy.deepcopy(episode)
    del missing.visible["edges"]
    extra = copy.deepcopy(episode)
    extra.visible["unexpected"] = 1
    cases = [missing, extra]
    for field in (
        "episode_id",
        "gold_assertion_mask",
        "target_nodes",
        "valid_routes",
        "measured_gamma",
    ):
        leaked = copy.deepcopy(episode)
        leaked.visible[field] = episode.hidden.get(field, 1)
        cases.append(leaked)

    for case in cases:
        with pytest.raises(IntegrityGateError) as cheap:
            validate_model_input_fields(case)
        with pytest.raises(IntegrityGateError) as serializing:
            model_input_bytes(case)
        assert str(cheap.value) == str(serializing.value)


def test_parallel_p0_scheduling_is_byte_identical_to_serial(tmp_path: Path) -> None:
    """Gate width must not change a single byte of the report.

    `workers` is a scheduling choice, not a contract change: every unit reads
    its own split and results are assembled in submission order. This is the
    check that keeps that true, and it is load-bearing in the same way the
    batched-traversal equivalence test is -- a divergence here would mean a P0
    report whose contents depend on how a process pool happened to schedule.
    """

    train_roots = {}
    screen_roots = {}
    screen_seed = bytes(range(32, 64))
    for gamma in GAMMA_BUCKETS:
        for label, roots, seed in (
            ("train", train_roots, TEST_SEED),
            ("screen", screen_roots, screen_seed),
        ):
            destination = tmp_path / f"{label}-{gamma:.1f}"
            write_generated_split(
                master_seed=seed,
                split="test-fixture",
                count=200,
                gamma=gamma,
                destination=destination,
            )
            roots[gamma] = destination

    # Gate 6 needs fresh-process evidence this test deliberately does not
    # supply, and the shortcut probes are noisy at fixture scale. The report is
    # still emitted with those blockers recorded, which is the contract, and
    # every gate that passes here took the scheduled path rather than the
    # serial fallback.
    def report(workers: int) -> dict[str, Any]:
        return evaluate_p0(
            train_roots=train_roots,
            screen_roots=screen_roots,
            double_execution_records=[],
            evaluated_at="2026-01-01T00:00:00Z",
            strict_counts=False,
            workers=workers,
        )

    serial = report(1)
    passed = [item["gate"] for item in serial["gates"] if item["passed"]]
    assert "double_execution" in serial["blockers"]
    assert {
        "gamma_measured_not_declared",
        "gold_swap_noninterference",
        "dual_oracle_agreement",
        "direct_pool_invariance",
    } <= set(passed)
    for workers in (2, 4):
        assert canonical_sha256(report(workers)) == canonical_sha256(serial)

    # The probe gates block at fixture scale, so the report above exercises
    # their serial fallback rather than their scheduled path. Compare those
    # units directly so both paths are covered.
    specs: list[tuple[str, tuple[Any, ...]]] = [
        ("probe", (train_roots[gamma], gamma, 160, 200, 160, 40, dire))
        for dire in (False, True)
        for gamma in GAMMA_BUCKETS
    ]
    assert _run_units(specs, 1) == _run_units(specs, 4)
