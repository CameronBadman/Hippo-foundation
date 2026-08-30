"""Completeness-first screening and main-run reports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .errors import IntegrityGateError
from .evaluation import apply_preregistered_decision
from .gates import select_main_budget
from .generator import BUDGET_CANDIDATES, GAMMA_BUCKETS, MODEL_SEEDS

RunKey = tuple[float, str, int, int]


def _key(value: dict[str, Any]) -> RunKey:
    return (
        float(value["gamma"]),
        str(value["arm"]),
        int(value["model_seed"]),
        int(value["budget"]),
    )


def _unique(
    values: Sequence[dict[str, Any]], label: str
) -> dict[RunKey, dict[str, Any]]:
    result: dict[RunKey, dict[str, Any]] = {}
    for value in values:
        key = _key(value)
        if key in result:
            raise IntegrityGateError(f"duplicate {label} run record: {key}")
        result[key] = value
    return result


def _fairness(receipts: dict[RunKey, dict[str, Any]], expected: set[RunKey]) -> None:
    pair_groups: dict[tuple[float, int, int], list[dict[str, Any]]] = {}
    for gamma, seed, budget in {
        (gamma, seed, budget) for gamma, _arm, seed, budget in expected
    }:
        key = (gamma, seed, budget)
        pair_groups.setdefault(key, [])
        for arm in ("TRAV", "DIRECT"):
            receipt = receipts.get((gamma, arm, seed, budget))
            if receipt is not None:
                pair_groups[key].append(receipt)
    for key, pair in pair_groups.items():
        if len(pair) != 2:
            continue
        counts = [int(item["parameter_count"]) for item in pair]
        relative = abs(counts[0] - counts[1]) / max(counts)
        if relative >= 0.01:
            raise IntegrityGateError(
                f"paired parameter counts differ by at least 1%: {key}"
            )
        if pair[0]["initialization_sha256"] != pair[1]["initialization_sha256"]:
            raise IntegrityGateError(f"paired arm initialization differs: {key}")


def screening_report(
    *,
    p0_report: dict[str, Any],
    receipts: Sequence[dict[str, Any]],
    failures: Sequence[dict[str, Any]],
    summaries: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if p0_report.get("record_kind") != "read_run_p0_report":
        raise IntegrityGateError("screening report requires a READ-run P0 report")
    pool = [
        item
        for item in p0_report.get("gates", [])
        if item.get("gate") == "direct_pool_invariance"
    ]
    if len(pool) != 1 or not pool[0].get("passed"):
        raise IntegrityGateError("screening report lacks a passed DIRECT-pool gate")
    try:
        reproduced_budget = select_main_budget(pool[0])
    except IntegrityGateError:
        reproduced_budget = None
    if reproduced_budget != p0_report.get("selected_main_budget"):
        raise IntegrityGateError("P0 budget does not reproduce from coverage")
    expected = {
        (gamma, arm, MODEL_SEEDS[0], budget)
        for gamma in (0.0, 0.4)
        for arm in ("TRAV", "DIRECT")
        for budget in BUDGET_CANDIDATES
    }
    receipt_map = _unique(receipts, "training receipt")
    failure_map = _unique(failures, "training failure")
    summary_map = _unique(summaries, "evaluation summary")
    overlap = set(receipt_map) & set(failure_map)
    if overlap:
        raise IntegrityGateError(
            f"runs are both successful and failed: {sorted(overlap)}"
        )
    unexpected = (set(receipt_map) | set(failure_map) | set(summary_map)) - expected
    if unexpected:
        raise IntegrityGateError(
            f"screening report has unregistered runs: {sorted(unexpected)}"
        )
    if set(summary_map) != set(receipt_map):
        raise IntegrityGateError("successful screening runs and summaries differ")
    for value in receipt_map.values():
        if value.get("stage") != "screening":
            raise IntegrityGateError("screening report contains a main receipt")
    for value in summary_map.values():
        if value.get("stage") != "screening" or value.get("split") != "screen":
            raise IntegrityGateError("screening summary has the wrong stage or split")
    _fairness(receipt_map, expected)
    missing = sorted(expected - set(receipt_map) - set(failure_map))
    accuracy = [
        {
            "gamma": key[0],
            "arm": key[1],
            "model_seed": key[2],
            "budget": key[3],
            "non_abstain_exact_set_accuracy": value["non_abstain_exact_set_accuracy"],
            "abstain_accuracy": value["abstain_accuracy"],
            "proof_valid_fraction": value["proof_valid_fraction"],
        }
        for key, value in sorted(summary_map.items())
    ]
    complete = not missing and len(receipt_map) + len(failure_map) == len(expected)
    selected = p0_report.get("selected_main_budget")
    if not complete:
        status = "incomplete"
    elif failure_map:
        status = "complete_with_failed_runs"
    elif selected is None:
        status = "complete_main_stopped_no_coverage_budget"
    else:
        status = "complete_main_budget_fixed"
    return {
        "schema_version": "1.0.0",
        "record_kind": "read_budget_sweep_report",
        "status": status,
        "expected_run_count": 16,
        "successful_run_count": len(receipt_map),
        "failed_run_count": len(failure_map),
        "missing_runs": [list(value) for value in missing],
        "selected_main_budget_from_coverage_only": selected,
        "accuracy_at_budget_secondary": accuracy,
        "main_sweep_authorized": bool(
            complete and not failure_map and selected in BUDGET_CANDIDATES
        ),
    }


def main_report(
    *,
    selected_budget: int,
    receipts: Sequence[dict[str, Any]],
    failures: Sequence[dict[str, Any]],
    summaries: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if selected_budget not in BUDGET_CANDIDATES:
        raise IntegrityGateError("main report budget is not preregistered")
    expected = {
        (gamma, arm, seed, selected_budget)
        for gamma in GAMMA_BUCKETS
        for arm in ("TRAV", "DIRECT")
        for seed in MODEL_SEEDS
    }
    receipt_map = _unique(receipts, "training receipt")
    failure_map = _unique(failures, "training failure")
    summary_map = _unique(summaries, "evaluation summary")
    if set(receipt_map) & set(failure_map):
        raise IntegrityGateError("a main run is both successful and failed")
    if (set(receipt_map) | set(failure_map) | set(summary_map)) - expected:
        raise IntegrityGateError("main report contains an unregistered run")
    if set(summary_map) != set(receipt_map):
        raise IntegrityGateError("successful main runs and summaries differ")
    for value in receipt_map.values():
        if value.get("stage") != "main":
            raise IntegrityGateError("main report contains a screening receipt")
    for value in summary_map.values():
        if value.get("stage") != "main" or value.get("split") != "holdout":
            raise IntegrityGateError("main summary has the wrong stage or split")
    _fairness(receipt_map, expected)
    missing = sorted(expected - set(receipt_map) - set(failure_map))
    if missing or failure_map:
        decision = {
            "decision": "incomplete",
            "reason": "missing or failed preregistered run",
        }
    else:
        decision = apply_preregistered_decision(list(summary_map.values()))
    return {
        "schema_version": "1.0.0",
        "record_kind": "read_main_report",
        "expected_run_count": 30,
        "successful_run_count": len(receipt_map),
        "failed_run_count": len(failure_map),
        "missing_runs": [list(value) for value in missing],
        "selected_budget": selected_budget,
        **decision,
    }
