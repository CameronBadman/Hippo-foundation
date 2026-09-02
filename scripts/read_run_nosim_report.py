"""Assemble the Track N structural-only screening report.

Reading rule: `experiments/read_run_v1/NOSIM_SCREENING_PREREGISTRATION.md`
§4–§9, committed before any masked run existed. This script reads only
artifacts that already exist — the six learning-probe output directories
(`probe.json`, `screen.jsonl`, `updates.jsonl`), the per-checkpoint
diagnostics written by `read_run_gamma_checkpoint_diag.py --constant-similarity
0`, the model-input audit (`model_input_audit.json`), the relation-prefix
ceiling (`ceiling_sweep.json`) and the γ-sweep record
(`gamma_sweep_curves.json`) — and writes a JSON curve record plus a Markdown
report. Every number in the Markdown is copied from the JSON by this script,
never typed.

What it computes per run: the gated `hops_2_4` curve of exact-set accuracy and
route-completeness (RC) at B = 128 and at the prefix budgets 8/16/32/64,
Amendment 04 §5's floors at the two declared read points (8,000 primary,
9,376 beside it), Amendment 09 §2's plateau reading of the exact curve and —
same mechanics, RC in place of accuracy — of the RC@128 and RC@32 curves. It
evaluates the preregistration's §9 controls (identity variant, shuffled
serialization, cross-check, prefix tests, commit order), then reads the §5
band from the three TRAV-nosim seeds together. The band is read from the
table as written; nothing is re-derived, and no threshold is adjusted per seed.

Screening only. No holdout is read or referenced. The masked runs are a
screening ablation, not a preregistered arm: nothing here is a hypothesis
verdict and no screening arm comparison is a result.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_run_learning_probe import PREFIX_BUDGETS, wilson_lower_bound  # noqa: E402

READ_POINTS = (8000, 9376)
PRIMARY_READ_POINT = 8000
GATED = "hops_2_4"
PRIMARY_BUDGET = 128
PRECISION_BUDGET = 32
PATH_LENGTHS = ("2", "3", "4", "5", "6")

# Amendment 04 §4/§5 and Amendment 09 §2, applied unchanged (preregistration §6).
CHANCE = 1.0 / 15.0
ABOVE_CHANCE_MARGIN = 0.0767
DISTINCT_FLOOR = 8
ENTROPY_FLOOR = 1.0
L_LINE = 2.34
L_WINDOW = 100
PLATEAU_STEP_PP = 1.0
PLATEAU_MIN_RUN = 3

# Preregistration §4 fixed constants. The pool reference and the walker's RC@32
# are copied from `model_input_audit.json` at run time, never typed here.
ORACLE_FRACTION = 0.99
NULL_PP = 2.0
WALKER_PRECISION_MARGIN_PP = 5.0
CONCERNING_PP = 1.0

RUN_NAME = re.compile(r"^probe-(TRAV|DIRECT)-nosim-s(\d+)$")
SEEDS = (1729, 2718, 3141)
PREFIX_TESTS = (
    "tests/test_read_run_ablation.py::test_examined_lists_are_prefix_consistent_in_the_budget",
    "tests/test_read_run_ablation.py::test_prefix_route_coverage_is_route_coverage_of_each_prefix",
    "tests/test_read_run_coverage.py::test_prefix_route_coverage_of_the_walker_matches_its_own_size",
)
# The code the runs and the controls depend on. `git diff` against the
# preregistration commit over these paths must be empty for the recorded
# `git_head` to vouch for the scoring code this report runs.
CODE_PATHS = (
    "src/hippocampus_foundation/read_run",
    "scripts/read_run_learning_probe.py",
    "scripts/read_run_gamma_checkpoint_diag.py",
    "scripts/read_run_model_input_audit.py",
    "tests/test_read_run_ablation.py",
    "tests/test_read_run_coverage.py",
)

BAND_TEXT = {
    "A": (
        "oracle-grade",
        "structural navigation learned, with relation-follower precision",
        "the earlier collapse was a shortcut preference, not an inability; insert can "
        "assume a learnable relation-conditioned walker (caveat: this generator's "
        "ambiguity profile is easy — preregistration §2)",
    ),
    "B": (
        "learned, imprecise",
        "routes found, at a budget cost well above a relation-follower",
        "navigation learnable; budget efficiency is a separate design problem before insert",
    ),
    "C": (
        "partial",
        "above the pool, not saturating",
        "report magnitude with Wilson bounds; the per-L rows say where it fails",
    ),
    "D": (
        "pool-indistinguishable",
        "null — the learned walk does no better than query-blind BFS",
        "as frozen, this architecture does not learn navigation from structure at this "
        "budget; the walker design changes before insert",
    ),
    "E": (
        "below pool",
        "directional negative — the learned scorer misdirects",
        "as D, and the scorer is actively harmful",
    ),
    "F": (
        "seeds split",
        "inconclusive; every seed reported",
        "the user decides on more seeds or a harder generator",
    ),
    "H": (
        "harness defect",
        "no reading",
        "stop, report, fix, rerun",
    ),
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _loss_window(updates: list[dict[str, Any]], at: int) -> float | None:
    """Amendment 04 §4: mean training `answer_loss` over updates (U-99, U]."""

    window = [
        row["answer_loss"] for row in updates if at - L_WINDOW < row["update"] <= at
    ]
    if len(window) != L_WINDOW:
        return None
    return sum(window) / len(window)


def _floors(cell: dict[str, Any]) -> dict[str, Any]:
    """Amendment 04 §5's three learner-gate floors on one gated screening cell."""

    above_chance = (
        cell["wilson_lower_bound"] > CHANCE
        and cell["exact_set_accuracy"] >= ABOVE_CHANCE_MARGIN
    )
    distinct = cell["distinct_classes"] >= DISTINCT_FLOOR
    entropy = cell["prediction_entropy_nats"] >= ENTROPY_FLOOR
    return {
        "above_chance": above_chance,
        "distinct_classes": distinct,
        "entropy": entropy,
        "all": above_chance and distinct and entropy,
    }


def _plateau(curve: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Amendment 09 §2 applied literally to one quantity's evaluated checkpoints.

    `key` is the curve column the two-consecutive-steps rule is read on:
    exact-set accuracy as written, or RC@128 / RC@32 with RC in place of
    accuracy (preregistration §6). Left-uniform is the same in all three cases.
    """

    n = len(curve)
    qualifying = []
    for i in range(n):
        if i < 2:
            qualifying.append(False)
            continue
        here, prev, prev2 = curve[i], curve[i - 1], curve[i - 2]
        left_uniform = (
            here["loss_window"] is not None
            and here["loss_window"] <= L_LINE
            and here["floors"]["all"]
        )
        step = 100.0 * (here[key] - prev[key])
        step_prev = 100.0 * (prev[key] - prev2[key])
        qualifying.append(
            left_uniform and step <= PLATEAU_STEP_PP and step_prev <= PLATEAU_STEP_PP
        )
    streak = 0
    for flag in reversed(qualifying):
        if not flag:
            break
        streak += 1
    plateau_point = curve[n - streak]["update"] if streak >= PLATEAU_MIN_RUN else None
    return {
        "quantity": key,
        "qualifying_updates": [
            row["update"] for row, flag in zip(curve, qualifying, strict=True) if flag
        ],
        "final_unbroken_run_length": streak,
        "plateau_point": plateau_point,
        "plateaued": plateau_point is not None,
    }


def _rc_block(cell: dict[str, Any]) -> dict[str, Any]:
    """Route-completeness at every prefix budget, with Wilson lower bounds."""

    n = cell["n"]
    at = {str(b): int(cell["route_complete_at"][str(b)]) for b in PREFIX_BUDGETS}
    if at[str(PRIMARY_BUDGET)] != cell["route_complete"]:
        raise ValueError("route_complete_at[128] disagrees with route_complete")
    return {
        "n": n,
        "route_complete_at": at,
        "route_complete_fraction_at": {b: c / n for b, c in at.items()},
        "route_complete_wilson_lower_bound_at": {
            b: wilson_lower_bound(c, n) for b, c in at.items()
        },
    }


def _curve_entry(
    row: dict[str, Any], updates: list[dict[str, Any]]
) -> dict[str, Any] | None:
    gated = row["strata"].get(GATED)
    if gated is None:
        return None
    rc = _rc_block(gated)
    entry = {
        "update": row["update"],
        "n": gated["n"],
        "correct": gated["correct"],
        "exact_set_accuracy": gated["exact_set_accuracy"],
        "wilson_lower_bound": gated["wilson_lower_bound"],
        "distinct_classes": gated["distinct_classes"],
        "prediction_entropy_nats": gated["prediction_entropy_nats"],
        "modal_fraction": gated["modal_fraction"],
        "exact_given_route_complete": gated["exact_given_route_complete"],
        "loss_window": _loss_window(updates, row["update"]),
        **rc,
        "rc128": rc["route_complete_fraction_at"][str(PRIMARY_BUDGET)],
        "rc32": rc["route_complete_fraction_at"][str(PRECISION_BUDGET)],
        "by_path_length": {
            length: {
                "n": cell["n"],
                "correct": cell["correct"],
                "exact_set_accuracy": cell["exact_set_accuracy"],
                "exact_given_route_complete": cell["exact_given_route_complete"],
                **_rc_block(cell),
            }
            for length, cell in gated["by_path_length"].items()
        },
    }
    entry["floors"] = _floors(gated)
    return entry


def load_run(directory: Path, *, arm: str, seed: int) -> dict[str, Any]:
    probe = json.loads((directory / "probe.json").read_text())
    if probe["arm"] != arm or probe["model_seed"] != seed:
        raise ValueError(f"{directory}: probe.json disagrees with the run name")
    if (
        probe["input_ablation"] != "no_similarity"
        or probe["masked_similarity_ppm"] != 0
    ):
        raise ValueError(
            f"{directory}: probe.json does not record the no_similarity mask"
        )
    if probe["touches_holdout"] is not False:
        raise ValueError(
            f"{directory}: probe.json does not assert touches_holdout false"
        )
    screen = _load_jsonl(directory / "screen.jsonl")
    updates = _load_jsonl(directory / "updates.jsonl")
    completed = len(updates)
    curve = [e for e in (_curve_entry(row, updates) for row in screen) if e]
    by_update = {row["update"]: row for row in curve}
    strata_by_update = {row["update"]: row["strata"] for row in screen}
    read_points: dict[str, Any] = {}
    for at in READ_POINTS:
        cell = by_update.get(at)
        if cell is None:
            read_points[str(at)] = None
            continue
        read_points[str(at)] = {
            **cell,
            "other_strata": {
                name: {
                    "n": s["n"],
                    "exact_set_accuracy": s["exact_set_accuracy"],
                    "route_complete_fraction": s["route_complete_fraction"],
                    "route_complete": s["route_complete"],
                }
                for name, s in strata_by_update[at].items()
                if name != GATED
            },
            "criterion_L": (
                cell["loss_window"] <= L_LINE
                if cell["loss_window"] is not None
                else None
            ),
            "left_uniform": (
                cell["loss_window"] is not None
                and cell["loss_window"] <= L_LINE
                and cell["floors"]["all"]
            ),
        }
    diag_path = directory / "checkpoint_diag.json"
    diag = json.loads(diag_path.read_text()) if diag_path.exists() else None
    return {
        "directory": str(directory),
        "name": directory.name,
        "arm": arm,
        "model_seed": seed,
        "git_head": probe["git_head"],
        "started_at": probe["started_at"],
        "requested_update_count": probe["requested_update_count"],
        "completed_updates": completed,
        "complete": completed == probe["requested_update_count"],
        "device": probe["device"],
        "bf16_autocast": probe["bf16_autocast"],
        "screen_root": probe["screen_root"],
        "train_root": probe["train_root"],
        "input_ablation": probe["input_ablation"],
        "masked_similarity_ppm": probe["masked_similarity_ppm"],
        "training_config_sha256": probe["training_config_sha256"],
        "curve": curve,
        "read_points": read_points,
        "plateau": {
            "exact_set_accuracy": _plateau(curve, "exact_set_accuracy"),
            "rc128": _plateau(curve, "rc128"),
            "rc32": _plateau(curve, "rc32"),
        },
        "checkpoint_diag": diag,
    }


def discover_runs(nosim_dir: Path) -> list[dict[str, Any]]:
    runs = []
    for child in sorted(nosim_dir.iterdir()):
        match = RUN_NAME.match(child.name)
        if not match or not child.is_dir():
            continue
        if not (child / "screen.jsonl").exists():
            continue
        runs.append(load_run(child, arm=match.group(1), seed=int(match.group(2))))
    return runs


def references(audit: dict[str, Any], ceiling: dict[str, Any]) -> dict[str, Any]:
    """§4's reference rows, copied from the audit and checked against the ceiling."""

    screen = audit["screen"]
    ref = screen["reference_route_completeness_gated_non_abstain"]
    n = screen["gated_non_abstain_count"]
    pool_ref = audit["pool_reference"]
    if (
        pool_ref["measured_route_complete_counts"]
        != pool_ref["expected_route_complete_counts"]
    ):
        raise ValueError("audit pool counts do not reproduce ceiling_sweep.json")
    ceiling_gated = ceiling["by_gamma"]["0.0"]["gated"]
    for budget, count in pool_ref["expected_route_complete_counts"].items():
        c = ceiling_gated[budget]["direct"]["route_complete"]["count"]
        if c != count:
            raise ValueError(
                f"ceiling_sweep pool count at B={budget} is {c}, audit says {count}"
            )
    out = {
        "source": "experiments/read_run_v1/diagnostics/model_input_audit.json",
        "ceiling_source": "experiments/read_run_v1/diagnostics/ceiling_sweep.json",
        "audit_git_head": audit["git_head"],
        "n": n,
        "path_length_n": {
            length: ref["direct_pool"]["by_path_length"][length][str(PRIMARY_BUDGET)][
                "n"
            ]
            for length in PATH_LENGTHS
        },
        "launch_gates": audit["launch_gates"],
        "cross_checks": screen["cross_checks"],
    }
    for name in ("relation_walker", "direct_pool"):
        out[name] = {
            "overall": {
                str(b): {
                    "count": ref[name]["overall"][str(b)]["count"],
                    "fraction": ref[name]["overall"][str(b)]["fraction"],
                    "wilson_lower_bound": ref[name]["overall"][str(b)][
                        "wilson_lower_bound"
                    ],
                }
                for b in PREFIX_BUDGETS
            },
            "by_path_length": {
                length: {
                    str(b): {
                        "count": ref[name]["by_path_length"][length][str(b)]["count"],
                        "n": ref[name]["by_path_length"][length][str(b)]["n"],
                        "fraction": ref[name]["by_path_length"][length][str(b)][
                            "fraction"
                        ],
                    }
                    for b in PREFIX_BUDGETS
                }
                for length in PATH_LENGTHS
            },
        }
        if any(out[name]["overall"][str(b)]["count"] > n for b in PREFIX_BUDGETS):
            raise ValueError("reference count exceeds n")
    return out


def thresholds(ref: dict[str, Any]) -> dict[str, Any]:
    """§4's fixed constants, derived from the copied references, in fractions and counts."""

    n = ref["n"]
    pool = ref["direct_pool"]["overall"][str(PRIMARY_BUDGET)]["fraction"]
    walker32 = ref["relation_walker"]["overall"][str(PRECISION_BUDGET)]["fraction"]
    null_low = pool - NULL_PP / 100.0
    null_high = pool + NULL_PP / 100.0
    precision = walker32 - WALKER_PRECISION_MARGIN_PP / 100.0
    return {
        "n": n,
        "pool_rc128_fraction": pool,
        "walker_rc32_fraction": walker32,
        "oracle_fraction": ORACLE_FRACTION,
        "null_band_fraction": [null_low, null_high],
        "walker_precision_fraction": precision,
        "null_pp": NULL_PP,
        "walker_precision_margin_pp": WALKER_PRECISION_MARGIN_PP,
        "concerning_pp": CONCERNING_PP,
        "counts": {
            "oracle_at_least": math.ceil(ORACLE_FRACTION * n),
            "null_band": [math.ceil(null_low * n), math.floor(null_high * n)],
            "walker_precision_at_least": math.ceil(precision * n),
        },
        "floors": {
            "chance": CHANCE,
            "above_chance_margin": ABOVE_CHANCE_MARGIN,
            "distinct_floor": DISTINCT_FLOOR,
            "entropy_floor_nats": ENTROPY_FLOOR,
            "criterion_L_nats": L_LINE,
            "plateau_step_pp": PLATEAU_STEP_PP,
            "plateau_min_run": PLATEAU_MIN_RUN,
        },
    }


def _level(fraction: float, th: dict[str, Any]) -> str:
    low, high = th["null_band_fraction"]
    if fraction >= th["oracle_fraction"]:
        return "oracle"
    if fraction > high:
        return "above_null"
    if fraction >= low:
        return "null"
    return "below_null"


def _level_by_count(count: int, th: dict[str, Any]) -> str:
    c = th["counts"]
    if count >= c["oracle_at_least"]:
        return "oracle"
    if count > c["null_band"][1]:
        return "above_null"
    if count >= c["null_band"][0]:
        return "null"
    return "below_null"


def read_band(
    trav_runs: list[dict[str, Any]], th: dict[str, Any], defects: list[str]
) -> dict[str, Any]:
    """§5 read per seed at 8,000 and combined across the three seeds, as written."""

    per_seed: dict[str, Any] = {}
    missing = []
    for run in trav_runs:
        rp = run["read_points"][str(PRIMARY_READ_POINT)]
        if rp is None:
            missing.append(run["name"])
            continue
        count128 = rp["route_complete_at"][str(PRIMARY_BUDGET)]
        count32 = rp["route_complete_at"][str(PRECISION_BUDGET)]
        level = _level(rp["rc128"], th)
        if level != _level_by_count(count128, th):
            raise ValueError("fraction and count thresholds disagree; boundary tie")
        precise = rp["rc32"] >= th["walker_precision_fraction"]
        if precise != (count32 >= th["counts"]["walker_precision_at_least"]):
            raise ValueError("fraction and count precision thresholds disagree")
        per_seed[str(run["model_seed"])] = {
            "rc128": rp["rc128"],
            "rc128_count": count128,
            "rc128_wilson_lower_bound": rp["route_complete_wilson_lower_bound_at"][
                str(PRIMARY_BUDGET)
            ],
            "rc32": rp["rc32"],
            "rc32_count": count32,
            "level": level,
            "rc32_meets_walker_precision": precise,
        }
    expected = {str(s) for s in SEEDS}
    if missing or set(per_seed) != expected:
        return {
            "band": None,
            "reason": "not every TRAV-nosim seed has an 8,000 read point",
            "missing": missing,
            "per_seed": per_seed,
            "voided_by_harness_defect": bool(defects),
        }
    levels = [row["level"] for row in per_seed.values()]
    fractions = [row["rc128"] for row in per_seed.values()]
    low, high = th["null_band_fraction"]
    lo, hi = min(fractions), max(fractions)
    if lo >= th["oracle_fraction"]:
        letter = (
            "A"
            if all(r["rc32_meets_walker_precision"] for r in per_seed.values())
            else "B"
        )
    elif lo > high:
        letter = "C"
    elif lo >= low:
        letter = "D" if hi <= high else "F"
    else:
        letter = "E" if hi <= high else "F"
    reading = {
        "band": letter if not defects else "H",
        "letter_before_precedence": letter,
        "voided_by_harness_defect": bool(defects),
        "harness_defects": defects,
        "per_seed": per_seed,
        "levels": levels,
        "min_rc128": lo,
        "max_rc128": hi,
        "read_at": PRIMARY_READ_POINT,
        "stratum": GATED,
    }
    name, meaning, consequence = BAND_TEXT[reading["band"]]
    reading["name"] = name
    reading["reading"] = meaning
    reading["consequence"] = consequence
    return reading


def floors_G(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """§5 band G: Amendment 04 §5 floors per arm × seed at 8,000 (and at 9,376, beside)."""

    cells: dict[str, Any] = {}
    failures: list[str] = []
    unreadable: list[str] = []
    for run in runs:
        for at in READ_POINTS:
            rp = run["read_points"][str(at)]
            key = f"{run['arm']}_s{run['model_seed']}@{at}"
            if rp is None:
                cells[key] = None
                if at == PRIMARY_READ_POINT:
                    unreadable.append(f"{run['name']} has no {at} read point")
                continue
            cells[key] = {
                "floors": rp["floors"],
                "exact_set_accuracy": rp["exact_set_accuracy"],
                "wilson_lower_bound": rp["wilson_lower_bound"],
                "distinct_classes": rp["distinct_classes"],
                "prediction_entropy_nats": rp["prediction_entropy_nats"],
                "loss_window": rp["loss_window"],
                "criterion_L": rp["criterion_L"],
            }
            if at == PRIMARY_READ_POINT and not rp["floors"]["all"]:
                failures.append(f"{run['name']} fails an Amendment 04 §5 floor at {at}")
    return {
        "cells": cells,
        "failures_at_8000": failures,
        "unreadable_at_8000": unreadable,
        "G": bool(failures),
    }


def controls(
    runs: list[dict[str, Any]],
    ref: dict[str, Any],
    prefix_tests: dict[str, Any],
    order: dict[str, Any],
    code_identity: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """§9's five controls. Returns the record and the list of harness defects (H)."""

    defects: list[str] = []
    per_trav: dict[str, Any] = {}
    concerning: list[str] = []
    for run in runs:
        if run["arm"] != "TRAV":
            continue
        diag = run["checkpoint_diag"]
        key = f"TRAV_s{run['model_seed']}"
        if diag is None:
            per_trav[key] = None
            defects.append(
                f"{run['name']}: checkpoint_diag.json missing — controls not evaluated"
            )
            continue
        gs = diag["gated_summary"]
        if diag["constant_similarity_ppm"] != run["masked_similarity_ppm"]:
            defects.append(
                f"{run['name']}: diag constant ≠ the run's masked_similarity_ppm"
            )
        if not gs.get("flattened_is_identity_check"):
            defects.append(f"{run['name']}: diag did not run the identity variant")
        identity_ok = gs.get("identity_differing_episodes") == 0
        if not identity_ok:
            defects.append(
                f"{run['name']}: identity variant differs from baseline on "
                f"{gs.get('identity_differing_episodes')} episodes"
            )
        if not gs["baseline_matches_probe_final_row"]:
            defects.append(f"{run['name']}: diag baseline ≠ probe's final screen row")
        disagreements = {
            name: variant["route_complete_vs_proof_valid_disagreements"]
            for name, variant in diag["variants"].items()
        }
        if any(disagreements.values()):
            defects.append(
                f"{run['name']}: route_complete ≠ proof_valid: {disagreements}"
            )
        shuffled_exact_ok = abs(gs["shuffled_delta_pp"]) < CONCERNING_PP
        shuffled_rc_ok = abs(gs["shuffled_route_complete_delta_pp"]) < CONCERNING_PP
        clean = shuffled_exact_ok and shuffled_rc_ok
        if gs["shuffled_control"] != ("clean" if shuffled_exact_ok else "concerning"):
            defects.append(
                f"{run['name']}: diag's shuffled_control label disagrees with its Δ"
            )
        if not clean:
            concerning.append(
                f"{run['name']}: shuffled Δ exact {gs['shuffled_delta_pp']:+.2f} pp, "
                f"RC@128 {gs['shuffled_route_complete_delta_pp']:+.2f} pp"
            )
        base = diag["variants"]["baseline"]["by_stratum"][GATED]
        per_trav[key] = {
            "identity_differing_episodes": gs.get("identity_differing_episodes"),
            "identity_ok": identity_ok,
            "baseline_matches_probe_final_row": gs["baseline_matches_probe_final_row"],
            "route_complete_vs_proof_valid_disagreements": disagreements,
            "shuffled_delta_exact_pp": gs["shuffled_delta_pp"],
            "shuffled_delta_rc128_pp": gs["shuffled_route_complete_delta_pp"],
            "shuffled_control": "clean" if clean else "concerning",
            "baseline_at_9376": {
                "exact_set_accuracy": base["exact_set_accuracy"],
                "route_complete_fraction": base["route_complete_fraction"],
                "route_complete_at": base["route_complete_at"],
                "predicted_abstain_fraction": base["predicted_abstain_fraction"],
                "target_node_present_fraction": base["target_node_present_fraction"],
            },
            "by_stratum_baseline": {
                s: {
                    "n": row["n"],
                    "route_complete_fraction": row["route_complete_fraction"],
                    "exact_set_accuracy": row["exact_set_accuracy"],
                    "predicted_abstain_fraction": row["predicted_abstain_fraction"],
                }
                for s, row in diag["variants"]["baseline"]["by_stratum"].items()
            },
        }
    if ref["cross_checks"]["route_complete_vs_proof_valid_disagreements"]:
        defects.append("model_input_audit cross-check has disagreements")
    if not prefix_tests["passed"]:
        defects.append("prefix-property tests did not pass")
    if not order["all_ok"]:
        defects.append("commit order: a run's git_head or started_at fails §3's rule")
    if not code_identity["clean"]:
        defects.append("scoring code differs from the preregistration commit")
    # DIRECT-nosim's examined set is the model-free pool; its RC must equal the
    # reference at every checkpoint. Not one of §9's five controls, so it is
    # reported as a consistency check rather than folded into H.
    pool_count = ref["direct_pool"]["overall"][str(PRIMARY_BUDGET)]["count"]
    direct_pool_mismatches = []
    for run in runs:
        if run["arm"] != "DIRECT":
            continue
        for row in run["curve"]:
            if row["route_complete_at"] != {
                str(b): ref["direct_pool"]["overall"][str(b)]["count"]
                for b in PREFIX_BUDGETS
            }:
                direct_pool_mismatches.append((run["name"], row["update"]))
    record = {
        "per_trav_seed": per_trav,
        "concerning": concerning,
        "audit_cross_checks": ref["cross_checks"],
        "prefix_tests": prefix_tests,
        "order": order,
        "code_identity": code_identity,
        "direct_pool_rc_matches_reference": {
            "expected_rc128_count": pool_count,
            "mismatching_checkpoints": direct_pool_mismatches,
            "ok": not direct_pool_mismatches,
        },
        "harness_defects": defects,
    }
    return record, defects


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def order_check(runs: list[dict[str, Any]], prereg_commit: str) -> dict[str, Any]:
    """§3/§9(5): every probe.json git_head equals the preregistration commit and starts after it."""

    full = _git(["rev-parse", prereg_commit])
    committed_at = _git(["log", "-1", "--format=%cI", full])
    # ISO-8601 with offsets; compare as UTC epoch seconds.
    from datetime import datetime

    commit_epoch = datetime.fromisoformat(committed_at).timestamp()
    rows = []
    for run in runs:
        started = datetime.fromisoformat(run["started_at"]).timestamp()
        rows.append(
            {
                "run": run["name"],
                "git_head": run["git_head"],
                "git_head_matches": run["git_head"] == full,
                "started_at": run["started_at"],
                "started_after_commit": started > commit_epoch,
                "seconds_after_commit": started - commit_epoch,
            }
        )
    return {
        "preregistration_commit": full,
        "preregistration_committed_at": committed_at,
        "runs": rows,
        "all_ok": bool(rows)
        and all(r["git_head_matches"] and r["started_after_commit"] for r in rows),
    }


def code_identity_check(prereg_commit: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "diff", "--stat", prereg_commit, "--", *CODE_PATHS],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "paths": list(CODE_PATHS),
        "against": prereg_commit,
        "diff_stat": result.stdout.strip(),
        "clean": result.stdout.strip() == "",
    }


def run_prefix_tests() -> dict[str, Any]:
    """§9(4): the prefix-property tests, run now, at the checked-out code."""

    command = ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", *PREFIX_TESTS]
    result = subprocess.run(command, capture_output=True, text=True)
    tail = "\n".join(result.stdout.strip().splitlines()[-3:])
    return {
        "tests": list(PREFIX_TESTS),
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "summary": tail,
        "head_at_run": _git(["rev-parse", "HEAD"]),
    }


def contrast_rows(sweep: dict[str, Any]) -> dict[str, Any]:
    """Descriptive only: the same seeds' with-similarity rows from the γ sweep."""

    rows: dict[str, Any] = {}
    for run in sweep["runs"]:
        if run["gamma"] != "0.0":
            continue
        key = f"{run['arm']}_s{run['model_seed']}"
        diag = run.get("checkpoint_diag")
        gs = diag["gated_summary"] if diag else None
        rows[key] = {
            "directory": run["directory"],
            "exact_set_accuracy": {
                at: (None if rp is None else rp["exact_set_accuracy"])
                for at, rp in run["read_points"].items()
            },
            "wilson_lower_bound": {
                at: (None if rp is None else rp["wilson_lower_bound"])
                for at, rp in run["read_points"].items()
            },
            "checkpoint_9376": None
            if gs is None
            else {
                "baseline_route_complete_fraction": gs[
                    "baseline_route_complete_fraction"
                ],
                "baseline_exact_set_accuracy": gs["baseline_exact_set_accuracy"],
                "flattened_500000_route_complete_fraction": gs[
                    "flattened_route_complete_fraction"
                ],
                "flattened_500000_exact_set_accuracy": gs[
                    "flattened_exact_set_accuracy"
                ],
                "shuffled_control": gs["shuffled_control"],
            },
        }
    return {
        "source": "experiments/read_run_v1/diagnostics/gamma_sweep_curves.json",
        "report_commit": sweep["report_commit"],
        "note": "with-similarity runs, same generator and seeds, different input; descriptive",
        "rows": rows,
    }


def _first_launch(nosim_dir: Path) -> str | None:
    log = nosim_dir / "launch.log"
    if not log.exists():
        return None
    for line in log.read_text().splitlines():
        if " start " in line:
            return line.split()[0]
    return None


def _fmt(value: float | None, digits: int = 2, pct: bool = True) -> str:
    if value is None:
        return "—"
    if pct:
        return f"{100.0 * value:.{digits}f}%"
    return f"{value:.{digits}f}"


def _fmt_pp(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f} pp"


def _count(count: int | None, n: int | None) -> str:
    if count is None or n is None:
        return "—"
    return f"{count}/{n} ({100.0 * count / n:.2f}%)"


def render_markdown(record: dict[str, Any]) -> str:
    out: list[str] = []
    w = out.append
    th = record["thresholds"]
    ref = record["references"]
    band = record["band"]
    ctl = record["controls"]
    runs = record["runs"]
    trav = [r for r in runs if r["arm"] == "TRAV"]
    direct = [r for r in runs if r["arm"] == "DIRECT"]
    n = th["n"]

    w("# Track N structural-only screening report")
    w("")
    w("## Status: screening descriptives, three seeds per arm, not a preregistered arm")
    w("")
    w(
        f"Generated {record['generated_at']} by `scripts/read_run_nosim_report.py` at commit "
        f"`{record['report_commit']}`. Reading rule: `NOSIM_SCREENING_PREREGISTRATION.md`, "
        f"committed as `{record['order']['preregistration_commit'][:12]}` "
        f"({record['order']['preregistration_committed_at']}); first masked run started "
        f"{record['first_launch_utc']}. Screening split only "
        "(`private/read-run-v1/p0-rerun/screen-g00`, gated `hops_2_4` non-abstain, "
        f"n = {n}), B = 128, v1 training configuration with `update_count` varied, "
        "`query_similarity_ppm` held at 0 at train and eval. Nothing here is a hypothesis "
        "verdict; no screening arm comparison is a result. The holdout was not generated, "
        "read, or opened."
    )
    w("")
    w("## 1. Band (preregistration §5), read at 8,000 on TRAV-nosim")
    w("")
    if band.get("band") is None:
        w(f"**No band: {band['reason']}.** Missing: {band.get('missing')}")
    else:
        w(
            f"**Band {band['band']} — {band['name']}.** Reading: {band['reading']}. "
            f"Consequence for the graph model: {band['consequence']}."
        )
        if band["voided_by_harness_defect"]:
            w("")
            w(
                f"The A–F letter the seeds would have produced is **{band['letter_before_precedence']}**, "
                "voided by the harness defects listed in §6 (H takes precedence over everything)."
            )
    w("")
    w(
        f"Levels per seed (RC@128 at 8,000; oracle ≥ {_fmt(th['oracle_fraction'], 1)} = "
        f"≥ {th['counts']['oracle_at_least']}/{n}; null band [{_fmt(th['null_band_fraction'][0])}, "
        f"{_fmt(th['null_band_fraction'][1])}] = counts {th['counts']['null_band'][0]}–"
        f"{th['counts']['null_band'][1]}; walker precision RC@32 ≥ {_fmt(th['walker_precision_fraction'])} "
        f"= ≥ {th['counts']['walker_precision_at_least']}/{n}):"
    )
    w("")
    w("| seed | RC@128 | Wilson LB | level | RC@32 | ≥ walker − 5 pp |")
    w("|---|---|---|---|---|---|")
    for seed, row in band.get("per_seed", {}).items():
        w(
            f"| {seed} | {_count(row['rc128_count'], n)} | {_fmt(row['rc128_wilson_lower_bound'])} | "
            f"{row['level']} | {_count(row['rc32_count'], n)} | {row['rc32_meets_walker_precision']} |"
        )
    w("")
    g = record["floors_G"]
    w(
        f"Band G (floors at 8,000, reported beside the letter, never suppressing it): "
        f"{'**G — ' + '; '.join(g['failures_at_8000']) + '**' if g['G'] else 'no arm × seed fails a floor'}."
        + (
            f" Not readable at 8,000: {'; '.join(g['unreadable_at_8000'])}."
            if g["unreadable_at_8000"]
            else ""
        )
    )
    w("")
    w("## 2. Reference rows (preregistration §4; copied from `model_input_audit.json`)")
    w("")
    w(
        f"Audit at `{ref['audit_git_head'][:12]}`; launch gates: "
        + ", ".join(f"{k} = {v}" for k, v in ref["launch_gates"].items())
        + f"; cross-checks: {ref['cross_checks']}."
    )
    w("")
    w("| reference | " + " | ".join(f"RC@{b}" for b in PREFIX_BUDGETS) + " |")
    w("|---|" + "---|" * len(PREFIX_BUDGETS))
    for name, label in (
        ("relation_walker", "relation walker"),
        ("direct_pool", "DIRECT pool"),
    ):
        w(
            f"| {label} | "
            + " | ".join(
                _count(ref[name]["overall"][str(b)]["count"], n) for b in PREFIX_BUDGETS
            )
            + " |"
        )
    w("")
    w("## 3. Primary table — TRAV-nosim route-completeness per seed")
    w("")
    for at in READ_POINTS:
        w(
            f"### At update {at:,}{' (primary)' if at == PRIMARY_READ_POINT else ' (beside; does not change the letter)'}"
        )
        w("")
        w(
            "| seed | complete | "
            + " | ".join(f"RC@{b}" for b in PREFIX_BUDGETS)
            + " | RC@128 Wilson LB | exact-set acc | exact given RC | loss (L) |"
        )
        w("|---|---|" + "---|" * len(PREFIX_BUDGETS) + "---|---|---|---|")
        for run in trav:
            rp = run["read_points"][str(at)]
            if rp is None:
                w(
                    f"| {run['model_seed']} | {run['complete']} | "
                    + "— | " * len(PREFIX_BUDGETS)
                    + "— | — | — | — |"
                )
                continue
            w(
                f"| {run['model_seed']} | {run['complete']} | "
                + " | ".join(
                    _count(rp["route_complete_at"][str(b)], rp["n"])
                    for b in PREFIX_BUDGETS
                )
                + f" | {_fmt(rp['route_complete_wilson_lower_bound_at'][str(PRIMARY_BUDGET)])} | "
                f"{_fmt(rp['exact_set_accuracy'])} | {_fmt(rp['exact_given_route_complete'])} | "
                f"{_fmt(rp['loss_window'], 3, pct=False)} |"
            )
        w("")
    w(
        "## 4. Route-completeness by path length L at 8,000 (TRAV-nosim per seed, beside the references)"
    )
    w("")
    w(
        "| L | n | walker RC@32 | walker RC@128 | pool RC@32 | pool RC@128 | "
        + " | ".join(f"s{r['model_seed']} RC@32" for r in trav)
        + " | "
        + " | ".join(f"s{r['model_seed']} RC@128" for r in trav)
        + " |"
    )
    w("|---|---|---|---|---|---|" + "---|" * (2 * len(trav)))
    for length in PATH_LENGTHS:
        ln = ref["path_length_n"][length]
        cells = [
            f"{ref['relation_walker']['by_path_length'][length][str(PRECISION_BUDGET)]['count']}/{ln}",
            f"{ref['relation_walker']['by_path_length'][length][str(PRIMARY_BUDGET)]['count']}/{ln}",
            f"{ref['direct_pool']['by_path_length'][length][str(PRECISION_BUDGET)]['count']}/{ln}",
            f"{ref['direct_pool']['by_path_length'][length][str(PRIMARY_BUDGET)]['count']}/{ln}",
        ]
        for budget in (PRECISION_BUDGET, PRIMARY_BUDGET):
            for run in trav:
                rp = run["read_points"][str(PRIMARY_READ_POINT)]
                if rp is None:
                    cells.append("—")
                    continue
                bl = rp["by_path_length"][length]
                cells.append(_count(bl["route_complete_at"][str(budget)], bl["n"]))
        w(f"| {length} | {ln} | " + " | ".join(cells) + " |")
    w("")
    w("## 5. Head accuracy and floors (Amendment 04 §5), every arm × seed")
    w("")
    w(
        "DIRECT-nosim has no walk: its examined set is the model-free pool and its RC is the "
        f"reference {_count(ref['direct_pool']['overall'][str(PRIMARY_BUDGET)]['count'], n)} by "
        f"construction (checked at every checkpoint: "
        f"{'all match' if ctl['direct_pool_rc_matches_reference']['ok'] else 'MISMATCH ' + str(ctl['direct_pool_rc_matches_reference']['mismatching_checkpoints'])}). "
        "Its `exact given RC` is the head's localisation against that ceiling."
    )
    w("")
    w(
        "| arm | seed | update | exact-set acc | Wilson LB | exact given RC | RC@128 | distinct | entropy (nats) | loss (L) | criterion L | floors |"
    )
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for run in runs:
        for at in READ_POINTS:
            rp = run["read_points"][str(at)]
            if rp is None:
                w(
                    f"| {run['arm']} | {run['model_seed']} | {at:,} | — | — | — | — | — | — | — | — | not reached |"
                )
                continue
            f = rp["floors"]
            verdict = (
                "pass"
                if f["all"]
                else "FAIL ("
                + ", ".join(
                    k
                    for k in ("above_chance", "distinct_classes", "entropy")
                    if not f[k]
                )
                + ")"
            )
            w(
                f"| {run['arm']} | {run['model_seed']} | {at:,} | {_fmt(rp['exact_set_accuracy'])} | "
                f"{_fmt(rp['wilson_lower_bound'])} | {_fmt(rp['exact_given_route_complete'])} | "
                f"{_fmt(rp['rc128'])} | {rp['distinct_classes']} | {rp['prediction_entropy_nats']:.3f} | "
                f"{_fmt(rp['loss_window'], 3, pct=False)} | {rp['criterion_L']} | {verdict} |"
            )
    w("")
    w("Other strata at 8,000 (not gated; descriptive):")
    w("")
    w("| arm | seed | stratum | n | exact-set acc | RC@128 |")
    w("|---|---|---|---|---|---|")
    for run in runs:
        rp = run["read_points"][str(PRIMARY_READ_POINT)]
        if rp is None:
            continue
        for stratum, s in rp["other_strata"].items():
            w(
                f"| {run['arm']} | {run['model_seed']} | {stratum} | {s['n']} | "
                f"{_fmt(s['exact_set_accuracy'])} | {_count(s['route_complete'], s['n'])} |"
            )
    w("")
    w("## 6. Controls (preregistration §9)")
    w("")
    w(
        f"- Order (§3): preregistration commit `{ctl['order']['preregistration_commit'][:12]}` at "
        f"{ctl['order']['preregistration_committed_at']}; all runs match and start after it: "
        f"**{ctl['order']['all_ok']}**."
    )
    for r in ctl["order"]["runs"]:
        w(
            f"  - {r['run']}: git_head `{r['git_head'][:12]}` (match {r['git_head_matches']}), "
            f"started {r['started_at']} ({r['seconds_after_commit']:.0f} s after the commit)"
        )
    w(
        f"- Scoring code identical to the preregistration commit over {len(ctl['code_identity']['paths'])} paths: "
        f"**{ctl['code_identity']['clean']}**"
        + (
            f" (diff: {ctl['code_identity']['diff_stat']})"
            if not ctl["code_identity"]["clean"]
            else ""
        )
    )
    w(
        f"- Prefix-property tests at `{ctl['prefix_tests']['head_at_run'][:12]}`: "
        f"**{'passed' if ctl['prefix_tests']['passed'] else 'FAILED'}** — `{ctl['prefix_tests']['summary'].splitlines()[-1] if ctl['prefix_tests']['summary'] else ''}`"
    )
    w(f"- Audit cross-checks: {ctl['audit_cross_checks']}")
    w("")
    w(
        "| TRAV seed | identity differing episodes | baseline = probe final row | RC ≠ proof_valid (per variant) | shuffled Δ exact | shuffled Δ RC@128 | shuffled control |"
    )
    w("|---|---|---|---|---|---|---|")
    for key, c in ctl["per_trav_seed"].items():
        if c is None:
            w(f"| {key} | — | — | — | — | — | diag missing |")
            continue
        w(
            f"| {key} | {c['identity_differing_episodes']} | {c['baseline_matches_probe_final_row']} | "
            f"{c['route_complete_vs_proof_valid_disagreements']} | {_fmt_pp(c['shuffled_delta_exact_pp'])} | "
            f"{_fmt_pp(c['shuffled_delta_rc128_pp'])} | {c['shuffled_control']} |"
        )
    w("")
    if ctl["harness_defects"]:
        w("**Harness defects (H):**")
        w("")
        for d in ctl["harness_defects"]:
            w(f"- {d}")
        w("")
    else:
        w("No harness defect: the §9 controls all hold.")
        w("")
    if ctl["concerning"]:
        w("Concerning controls (flag the reading, do not change the letter):")
        w("")
        for c in ctl["concerning"]:
            w(f"- {c}")
        w("")
    w("### TRAV-nosim checkpoint (9,376) by stratum, baseline variant")
    w("")
    w("| seed | stratum | n | RC@128 | exact-set acc | predicted-abstain |")
    w("|---|---|---|---|---|---|")
    for key, c in ctl["per_trav_seed"].items():
        if c is None:
            continue
        for stratum, row in c["by_stratum_baseline"].items():
            w(
                f"| {key} | {stratum} | {row['n']} | {_fmt(row['route_complete_fraction'])} | "
                f"{_fmt(row['exact_set_accuracy'])} | {_fmt(row['predicted_abstain_fraction'])} |"
            )
    w("")
    w("## 7. Amendment 09 plateau reading per run (no automatic extension)")
    w("")
    w(
        "| run | seed | quantity | qualifying checkpoints | final unbroken run | plateau point |"
    )
    w("|---|---|---|---|---|---|")
    for run in runs:
        for key, p in run["plateau"].items():
            if run["arm"] == "DIRECT" and key != "exact_set_accuracy":
                continue
            w(
                f"| {run['arm']} | {run['model_seed']} | {key} | "
                f"{', '.join(str(u) for u in p['qualifying_updates']) or '—'} | "
                f"{p['final_unbroken_run_length']} | {p['plateau_point'] if p['plateaued'] else 'not plateaued'} |"
            )
    w("")
    w(
        "## 8. Learning curves, TRAV-nosim (gated; RC@128 / RC@32 / exact-set accuracy per checkpoint)"
    )
    w("")
    w("| update | " + " | ".join(f"s{r['model_seed']}" for r in trav) + " |")
    w("|---|" + "---|" * len(trav))
    checkpoints = sorted({row["update"] for r in trav for row in r["curve"]})
    for u in checkpoints:
        cells = []
        for r in trav:
            row = next((c for c in r["curve"] if c["update"] == u), None)
            cells.append(
                "—"
                if row is None
                else f"{_fmt(row['rc128'])} / {_fmt(row['rc32'])} / {_fmt(row['exact_set_accuracy'])}"
            )
        w(f"| {u:,} | " + " | ".join(cells) + " |")
    w("")
    w("DIRECT-nosim exact-set accuracy per checkpoint (RC fixed at the pool):")
    w("")
    w("| update | " + " | ".join(f"s{r['model_seed']}" for r in direct) + " |")
    w("|---|" + "---|" * len(direct))
    checkpoints = sorted({row["update"] for r in direct for row in r["curve"]})
    for u in checkpoints:
        cells = []
        for r in direct:
            row = next((c for c in r["curve"] if c["update"] == u), None)
            cells.append("—" if row is None else _fmt(row["exact_set_accuracy"]))
        w(f"| {u:,} | " + " | ".join(cells) + " |")
    w("")
    w("## 9. Contrast: the same seeds with similarity (γ sweep; descriptive only)")
    w("")
    con = record["contrast"]
    w(
        f"From `{con['source']}` (report commit `{con['report_commit']}`): γ = 0.0 runs with "
        "`query_similarity_ppm` present. Same generator, same seeds where they exist, "
        "different input; a screening-vs-screening contrast, not an arm comparison."
    )
    w("")
    w(
        "| run | exact @8,000 | exact @9,376 | ckpt RC@128 (baseline) | ckpt RC@128 (flattened 500,000) | ckpt exact (flattened) |"
    )
    w("|---|---|---|---|---|---|")
    for key, row in con["rows"].items():
        c = row["checkpoint_9376"]
        w(
            f"| {key} | {_fmt(row['exact_set_accuracy'].get('8000'))} | {_fmt(row['exact_set_accuracy'].get('9376'))} | "
            f"{_fmt(None if c is None else c['baseline_route_complete_fraction'])} | "
            f"{_fmt(None if c is None else c['flattened_500000_route_complete_fraction'])} | "
            f"{_fmt(None if c is None else c['flattened_500000_exact_set_accuracy'])} |"
        )
    w("")
    w("## 10. What this report does not do")
    w("")
    w(
        "It records no hypothesis verdict. It changes no threshold, arm, metric, seed or "
        "frozen digest; the band is read from §5 of the preregistration as written, at "
        "8,000 only. It reads no holdout. Amendment 10 remains pending review. Whether to "
        "extend, add seeds, or change the generator is the user's call and is not "
        "recommended by any number above."
    )
    w("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nosim-dir", default="private/read-run-v1/diagnostics/nosim")
    parser.add_argument(
        "--audit", default="experiments/read_run_v1/diagnostics/model_input_audit.json"
    )
    parser.add_argument(
        "--ceiling", default="experiments/read_run_v1/diagnostics/ceiling_sweep.json"
    )
    parser.add_argument(
        "--sweep", default="experiments/read_run_v1/diagnostics/gamma_sweep_curves.json"
    )
    parser.add_argument("--preregistration-commit", required=True)
    parser.add_argument(
        "--skip-prefix-tests",
        action="store_true",
        help="smoke only: records the prefix tests as not run (a harness defect)",
    )
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--md-output", required=True)
    args = parser.parse_args()

    nosim_dir = Path(args.nosim_dir)
    runs = discover_runs(nosim_dir)
    audit = json.loads(Path(args.audit).read_text())
    ceiling = json.loads(Path(args.ceiling).read_text())
    sweep = json.loads(Path(args.sweep).read_text())
    ref = references(audit, ceiling)
    th = thresholds(ref)
    order = order_check(runs, args.preregistration_commit)
    code_identity = code_identity_check(args.preregistration_commit)
    if args.skip_prefix_tests:
        prefix_tests = {
            "tests": list(PREFIX_TESTS),
            "returncode": None,
            "passed": False,
            "summary": "not run (--skip-prefix-tests)",
            "head_at_run": _git(["rev-parse", "HEAD"]),
        }
    else:
        prefix_tests = run_prefix_tests()
    ctl, defects = controls(runs, ref, prefix_tests, order, code_identity)
    trav = [r for r in runs if r["arm"] == "TRAV"]
    band = read_band(trav, th, defects)
    record: dict[str, Any] = {
        "record_kind": "read_run_nosim_screening_report",
        "generated_at": subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "report_commit": _git(["rev-parse", "--short", "HEAD"]),
        "preregistration": "experiments/read_run_v1/NOSIM_SCREENING_PREREGISTRATION.md",
        "first_launch_utc": _first_launch(nosim_dir),
        "gated_stratum": GATED,
        "read_points": list(READ_POINTS),
        "primary_read_point": PRIMARY_READ_POINT,
        "prefix_budgets": list(PREFIX_BUDGETS),
        "thresholds": th,
        "references": ref,
        "order": order,
        "runs": [
            {k: v for k, v in run.items() if k != "checkpoint_diag"}
            | {
                "checkpoint_diag": (
                    None
                    if run["checkpoint_diag"] is None
                    else {
                        "gated_summary": run["checkpoint_diag"]["gated_summary"],
                        "variants": run["checkpoint_diag"]["variants"],
                        "constant_similarity_ppm": run["checkpoint_diag"][
                            "constant_similarity_ppm"
                        ],
                    }
                )
            }
            for run in runs
        ],
        "controls": ctl,
        "floors_G": floors_G(runs),
        "band": band,
        "contrast": contrast_rows(sweep),
        "touches_holdout": False,
    }
    Path(args.json_output).write_text(json.dumps(record, indent=2, sort_keys=True))
    Path(args.md_output).write_text(render_markdown(record))
    print(
        json.dumps(
            {
                "band": band.get("band"),
                "reason": band.get("reason"),
                "harness_defects": defects,
                "floors_G": record["floors_G"]["failures_at_8000"],
                "unreadable_at_8000": record["floors_G"]["unreadable_at_8000"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
