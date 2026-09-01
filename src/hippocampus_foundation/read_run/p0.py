"""Aggregate the seven preregistered gates without opening the holdout."""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json

from .contracts import validate_preregistration
from .errors import IntegrityGateError
from .gates import (
    dire_shortcut_probe_gate_streaming,
    direct_pool_invariance_gate,
    dual_oracle_gate,
    gamma_measurement_gate,
    gold_swap_noninterference_gate,
    select_main_budget,
    shortcut_probe_gate_streaming,
)
from .generator import GAMMA_BUCKETS
from .io import read_generated_split, validate_generated_split_artifacts
from .reproducibility import validate_double_execution_record


def _load_manifest(root: Path) -> dict[str, Any]:
    value = load_json(root / "manifest.private.json")
    if not isinstance(value, dict):
        raise IntegrityGateError("private split manifest must be an object")
    return value


def _capture_gate(name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = operation()
    except IntegrityGateError as exc:
        return {
            "gate": name,
            "passed": False,
            "failure_type": type(exc).__name__,
            "failure": str(exc),
        }
    if result.get("gate") != name or result.get("passed") is not True:
        return {
            "gate": name,
            "passed": False,
            "failure_type": "InvalidGateResult",
            "failure": "gate returned a malformed success record",
        }
    return result


def _aggregate_gate(
    name: str, operations: list[Callable[[], dict[str, Any]]]
) -> dict[str, Any]:
    results = []
    for operation in operations:
        result = _capture_gate(name, operation)
        results.append(result)
        if not result["passed"]:
            return {
                "gate": name,
                "passed": False,
                "checks": results,
                "failure": result["failure"],
            }
    return {"gate": name, "passed": True, "checks": results}


def _slice_factory(root: Path, start: int, stop: int) -> Callable[[], Any]:
    return lambda: islice(read_generated_split(root), start, stop)


def _validate_roots(
    roots: dict[float, Path],
    *,
    split: str,
    expected_count: int,
    expected_seed_commitment: str | None,
) -> dict[str, str]:
    if set(roots) != set(GAMMA_BUCKETS):
        raise IntegrityGateError(f"{split} roots do not cover every gamma bucket")
    bindings = {}
    for gamma, root in roots.items():
        _public, manifest, _artifacts = validate_generated_split_artifacts(
            root, expected_seed_commitment=expected_seed_commitment
        )
        if manifest.get("split") != split:
            raise IntegrityGateError(f"{split} root contains another split")
        if manifest.get("requested_gamma") != gamma:
            raise IntegrityGateError(f"{split} root is assigned to another gamma")
        if manifest.get("episode_count") != expected_count:
            raise IntegrityGateError(f"{split} episode count differs")
        if manifest.get("abstain_count") != expected_count // 4:
            raise IntegrityGateError(f"{split} ABSTAIN count differs")
        bindings[f"{gamma:.1f}"] = canonical_sha256(manifest)
    return bindings


def _world_disjoint(train_root: Path, screen_root: Path) -> dict[str, Any]:
    train_worlds = {
        episode.paired_world_id for episode in read_generated_split(train_root)
    }
    screen_worlds = {
        episode.paired_world_id for episode in read_generated_split(screen_root)
    }
    overlap = train_worlds & screen_worlds
    if overlap:
        raise IntegrityGateError("train and screening world families overlap")
    return {
        "train_world_count": len(train_worlds),
        "screen_world_count": len(screen_worlds),
        "overlap_count": 0,
    }


def _double_execution_record(
    records: list[dict[str, Any]],
    gamma: float,
    expected_count: int,
    dataset_root: Path,
) -> dict[str, Any]:
    matches = [item for item in records if item.get("gamma") == gamma]
    if len(matches) != 1:
        raise IntegrityGateError("double execution evidence is missing or duplicated")
    return validate_double_execution_record(
        matches[0],
        dataset_root=dataset_root,
        gamma=gamma,
        expected_count=expected_count,
    )


DEFAULT_P0_WORKERS = 1


def _unit_gamma(
    train_root: Path, screen_root: Path, gamma: float
) -> tuple[list[dict[str, Any]], str | None]:
    checks: list[dict[str, Any]] = []
    for split, root in (("train", train_root), ("screen", screen_root)):
        try:
            result = gamma_measurement_gate(
                read_generated_split(root), requested_gamma=gamma
            )
        except IntegrityGateError as exc:
            return checks, str(exc)
        result["split"] = split
        checks.append(result)
    return checks, None


def _unit_probe(
    train_root: Path,
    gamma: float,
    fit_stop: int,
    train_count: int,
    expected_fit: int,
    expected_evaluation: int,
    dire: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    runner = (
        dire_shortcut_probe_gate_streaming if dire else shortcut_probe_gate_streaming
    )
    try:
        result = runner(
            fit_factory=_slice_factory(train_root, 0, fit_stop),
            evaluation_factory=_slice_factory(train_root, fit_stop, train_count),
            expected_fit_count=expected_fit,
            expected_evaluation_count=expected_evaluation,
        )
    except IntegrityGateError as exc:
        return None, str(exc)
    result["gamma"] = gamma
    return result, None


def _unit_oracle(root: Path) -> dict[str, Any]:
    return _capture_gate(
        "dual_oracle_agreement", lambda: dual_oracle_gate(read_generated_split(root))
    )


def _unit_gold(screen_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return gold_swap_noninterference_gate(
            list(read_generated_split(screen_root))
        ), None
    except IntegrityGateError as exc:
        return None, str(exc)


def _unit_disjoint(
    train_root: Path, screen_root: Path
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return _world_disjoint(train_root, screen_root), None
    except IntegrityGateError as exc:
        return None, str(exc)


_UNIT_DISPATCH: dict[str, Callable[..., Any]] = {
    "gamma": _unit_gamma,
    "probe": _unit_probe,
    "oracle": _unit_oracle,
    "gold": _unit_gold,
    "disjoint": _unit_disjoint,
}


def _run_unit(spec: tuple[str, tuple[Any, ...]]) -> Any:
    kind, arguments = spec
    return _UNIT_DISPATCH[kind](*arguments)


def _run_units(specs: Sequence[tuple[str, tuple[Any, ...]]], workers: int) -> list[Any]:
    """Evaluate independent gate units, always returning them in submission order.

    Determinism comes from the ordering here, not from completion order: each
    unit reads its own split from disk and returns a plain result record, so the
    assembled report cannot depend on how the pool schedules them.
    """

    if workers <= 1:
        return [_run_unit(spec) for spec in specs]
    # "spawn", not the default fork: a forked child of a multi-threaded parent
    # can deadlock, and a P0 unit runs for minutes, so a fresh interpreter's
    # start-up cost is not worth the hazard.
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        return list(pool.map(_run_unit, specs))


def evaluate_p0(
    *,
    train_roots: dict[float, Path],
    screen_roots: dict[float, Path],
    double_execution_records: list[dict[str, Any]],
    evaluated_at: str,
    strict_counts: bool = True,
    workers: int = DEFAULT_P0_WORKERS,
) -> dict[str, Any]:
    """Evaluate all seven gates and return a report even when one blocks.

    `workers` only changes how the independent per-gamma units are scheduled.
    Every unit reads its own split and the results are assembled in submission
    order, so the report is byte-identical at any width; if any unit reports a
    blocker the affected gate is recomputed serially, so the early-termination
    semantics of a failing gate are the original code's, not a reimplementation.
    The cost of that guarantee is that a blocked gate is evaluated twice, and
    that every gamma runs even where the serial code would have stopped at the
    first failure. A blocked P0 is therefore slower than a passing one, which is
    the right way round.
    """

    contracts = validate_preregistration()
    expected_seed_commitment = (
        contracts["preregistration"]["heldout_seed_sha256"] if strict_counts else None
    )
    train_count = (
        150_000
        if strict_counts
        else _load_manifest(next(iter(train_roots.values())))["episode_count"]
    )
    screen_count = (
        2_000
        if strict_counts
        else _load_manifest(next(iter(screen_roots.values())))["episode_count"]
    )
    bindings = {
        "train": _validate_roots(
            train_roots,
            split="train" if strict_counts else "test-fixture",
            expected_count=train_count,
            expected_seed_commitment=expected_seed_commitment,
        ),
        "screen": _validate_roots(
            screen_roots,
            split="screen" if strict_counts else "test-fixture",
            expected_count=screen_count,
            expected_seed_commitment=expected_seed_commitment,
        ),
    }
    screen = {
        gamma: list(read_generated_split(screen_roots[gamma]))
        for gamma in GAMMA_BUCKETS
    }

    fit_stop = train_count - train_count // 5
    expected_fit = 120_000 if strict_counts else fit_stop
    expected_evaluation = 30_000 if strict_counts else train_count - fit_stop
    specs: list[tuple[str, tuple[Any, ...]]] = []
    for gamma in GAMMA_BUCKETS:
        specs.append(("gamma", (train_roots[gamma], screen_roots[gamma], gamma)))
    for dire in (False, True):
        for gamma in GAMMA_BUCKETS:
            specs.append(
                (
                    "probe",
                    (
                        train_roots[gamma],
                        gamma,
                        fit_stop,
                        train_count,
                        expected_fit,
                        expected_evaluation,
                        dire,
                    ),
                )
            )
    for gamma in GAMMA_BUCKETS:
        specs.append(("oracle", (train_roots[gamma],)))
    for gamma in GAMMA_BUCKETS:
        specs.append(("gold", (screen_roots[gamma],)))
    specs.append(("disjoint", (train_roots[0.0], screen_roots[0.0])))
    scheduled = _run_units(specs, workers)
    unit_gamma = scheduled[0:5]
    unit_probe = scheduled[5:10]
    unit_dire = scheduled[10:15]
    unit_oracle = scheduled[15:20]
    unit_gold = scheduled[20:25]
    unit_disjoint = scheduled[25]

    gamma_checks = []
    gamma_failed: str | None = None
    if all(failure is None for _checks, failure in unit_gamma):
        gamma_checks = [check for checks, _failure in unit_gamma for check in checks]
    else:
        for gamma in GAMMA_BUCKETS:
            for split, root in (
                ("train", train_roots[gamma]),
                ("screen", screen_roots[gamma]),
            ):
                try:
                    result = gamma_measurement_gate(
                        read_generated_split(root), requested_gamma=gamma
                    )
                    result["split"] = split
                    gamma_checks.append(result)
                except IntegrityGateError as exc:
                    gamma_failed = str(exc)
                    break
            if gamma_failed:
                break
    gate_1 = {
        "gate": "gamma_measured_not_declared",
        "passed": gamma_failed is None,
        "checks": gamma_checks,
    }
    if gamma_failed:
        gate_1["failure"] = gamma_failed

    def gold_checks() -> dict[str, Any]:
        if all(failure is None for _check, failure in unit_gold) and (
            unit_disjoint[1] is None
        ):
            return {
                "gate": "gold_swap_noninterference",
                "passed": True,
                "checks": [check for check, _failure in unit_gold],
                "split_disjointness": unit_disjoint[0],
            }
        checks = [
            gold_swap_noninterference_gate(screen[gamma]) for gamma in GAMMA_BUCKETS
        ]
        disjoint = _world_disjoint(train_roots[0.0], screen_roots[0.0])
        return {
            "gate": "gold_swap_noninterference",
            "passed": True,
            "checks": checks,
            "split_disjointness": disjoint,
        }

    gate_2 = _capture_gate("gold_swap_noninterference", gold_checks)

    probe_checks = []
    probe_failure: str | None = None
    if all(failure is None for _check, failure in unit_probe):
        probe_checks = [check for check, _failure in unit_probe]
    else:
        for gamma in GAMMA_BUCKETS:
            try:
                result = shortcut_probe_gate_streaming(
                    fit_factory=_slice_factory(train_roots[gamma], 0, fit_stop),
                    evaluation_factory=_slice_factory(
                        train_roots[gamma], fit_stop, train_count
                    ),
                    expected_fit_count=(120_000 if strict_counts else fit_stop),
                    expected_evaluation_count=(
                        30_000 if strict_counts else train_count - fit_stop
                    ),
                )
                result["gamma"] = gamma
                probe_checks.append(result)
            except IntegrityGateError as exc:
                probe_failure = str(exc)
                break
    gate_3 = {
        "gate": "shortcut_probes",
        "passed": probe_failure is None,
        "checks": probe_checks,
    }
    if probe_failure:
        gate_3["failure"] = probe_failure

    dire_checks = []
    dire_failure: str | None = None
    if all(failure is None for _check, failure in unit_dire):
        dire_checks = [check for check, _failure in unit_dire]
    else:
        for gamma in GAMMA_BUCKETS:
            try:
                result = dire_shortcut_probe_gate_streaming(
                    fit_factory=_slice_factory(train_roots[gamma], 0, fit_stop),
                    evaluation_factory=_slice_factory(
                        train_roots[gamma], fit_stop, train_count
                    ),
                    expected_fit_count=(120_000 if strict_counts else fit_stop),
                    expected_evaluation_count=(
                        30_000 if strict_counts else train_count - fit_stop
                    ),
                )
                result["gamma"] = gamma
                dire_checks.append(result)
            except IntegrityGateError as exc:
                dire_failure = str(exc)
                break
    gate_4 = {
        "gate": "dire_control",
        "passed": dire_failure is None,
        "checks": dire_checks,
    }
    if dire_failure:
        gate_4["failure"] = dire_failure

    oracle_operations: list[Callable[[], dict[str, Any]]] = []
    for index, gamma in enumerate(GAMMA_BUCKETS):
        if all(result["passed"] for result in unit_oracle):
            oracle_operations.append(lambda index=index: unit_oracle[index])
        else:
            oracle_operations.append(
                lambda gamma=gamma: dual_oracle_gate(
                    read_generated_split(train_roots[gamma])
                )
            )
        oracle_operations.append(
            lambda gamma=gamma: dual_oracle_gate(iter(screen[gamma]))
        )
    gate_5 = _aggregate_gate("dual_oracle_agreement", oracle_operations)

    double_checks = []
    double_failure: str | None = None
    for gamma in GAMMA_BUCKETS:
        try:
            double_checks.append(
                _double_execution_record(
                    double_execution_records,
                    gamma,
                    screen_count,
                    screen_roots[gamma],
                )
            )
        except IntegrityGateError as exc:
            double_failure = str(exc)
            break
    gate_6 = {
        "gate": "double_execution",
        "passed": double_failure is None,
        "checks": double_checks,
    }
    if double_failure:
        gate_6["failure"] = double_failure

    gate_7 = _capture_gate(
        "direct_pool_invariance", lambda: direct_pool_invariance_gate(screen)
    )
    selected_budget = None
    budget_failure = None
    if gate_7["passed"]:
        try:
            selected_budget = select_main_budget(gate_7)
        except IntegrityGateError as exc:
            budget_failure = str(exc)

    gates = [gate_1, gate_2, gate_3, gate_4, gate_5, gate_6, gate_7]
    blockers = [item["gate"] for item in gates if not item["passed"]]
    if budget_failure:
        blockers.append("no_budget_over_90_percent_coverage")
    return {
        "schema_version": "1.0.0",
        "record_kind": "read_run_p0_report",
        "evaluated_at": evaluated_at,
        "preregistration_json_sha256": contracts["preregistration_json_sha256"],
        "training_config_sha256": contracts["training_config_sha256"],
        "dataset_bindings": bindings,
        "gates": gates,
        "selected_main_budget": selected_budget,
        "budget_selection_failure": budget_failure,
        "blockers": blockers,
        "holdout_opened": False,
        "screening_training_authorized": all(item["passed"] for item in gates),
        "training_authorized": not blockers,
    }
