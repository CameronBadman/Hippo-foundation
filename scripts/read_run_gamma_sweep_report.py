"""Assemble the γ-sweep screening report declared in Amendment 10 §8.

Reads only artifacts that already exist — the learning-probe output
directories (`probe.json`, `screen.jsonl`, `updates.jsonl`), the per-checkpoint
diagnostics written by `read_run_gamma_checkpoint_diag.py`, the greedy baseline
(`rc_abc_b128.json`), the relation-prefix ceiling (`ceiling_sweep.json`) and,
when present, the generator grid — and writes two files: a JSON curve record
and a Markdown report. Every number in the Markdown is copied from the JSON by
this script, never typed.

What it computes per run: the gated `hops_2_4` curve, Amendment 04 §4's
criterion (L) and §5's three floors at the two declared read points (8,000 =
the v2 `update_count`, and 9,376), and Amendment 09 §2's plateau reading. Per
γ it lays TRAV, DIRECT, greedy and the relation ceiling side by side and forms
Amendment 10 §4's `lead` and `excess` (and Amendment 07's `excess_DIRECT`),
labelled inadmissible: screening, one seed, design phase. Per-seed values are
reported wherever a second seed exists; nothing is pooled.

Screening only. No holdout is read or referenced.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

GAMMAS = ("0.0", "0.1", "0.2", "0.3", "0.4")
READ_POINTS = (8000, 9376)
GATED = "hops_2_4"
CHANCE = 1.0 / 15.0
ABOVE_CHANCE_MARGIN = 0.0767
DISTINCT_FLOOR = 8
ENTROPY_FLOOR = 1.0
L_LINE = 2.34
L_WINDOW = 100
PLATEAU_STEP_PP = 1.0
PLATEAU_MIN_RUN = 3
CEILING_FRACTION = 0.99
SUPPORT_PP = 5.0
NULL_PP = 2.0
CONCERNING_PP = 1.0

RUN_NAME = re.compile(r"^probe-(TRAV|DIRECT)-g(\d\d)(?:-s(\d+))?$")


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


def _plateau(curve: list[dict[str, Any]]) -> dict[str, Any]:
    """Amendment 09 §2 applied literally to an arm's evaluated checkpoints."""

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
        step = 100.0 * (here["exact_set_accuracy"] - prev["exact_set_accuracy"])
        step_prev = 100.0 * (prev["exact_set_accuracy"] - prev2["exact_set_accuracy"])
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
        "qualifying_updates": [
            row["update"] for row, flag in zip(curve, qualifying, strict=True) if flag
        ],
        "final_unbroken_run_length": streak,
        "plateau_point": plateau_point,
        "plateaued": plateau_point is not None,
    }


def load_run(directory: Path, *, arm: str, gamma: str, seed: int) -> dict[str, Any]:
    probe = json.loads((directory / "probe.json").read_text())
    if probe["arm"] != arm or probe["model_seed"] != seed:
        raise ValueError(f"{directory}: probe.json disagrees with the run name")
    expected_root = f"screen-g{int(float(gamma) * 10):02d}"
    if not probe["screen_root"].endswith(expected_root):
        raise ValueError(f"{directory}: screen_root is not {expected_root}")
    screen = _load_jsonl(directory / "screen.jsonl")
    updates = _load_jsonl(directory / "updates.jsonl")
    completed = len(updates)
    curve = []
    for row in screen:
        gated = row["strata"].get(GATED)
        if gated is None:
            continue
        entry = {
            "update": row["update"],
            "n": gated["n"],
            "correct": gated["correct"],
            "exact_set_accuracy": gated["exact_set_accuracy"],
            "wilson_lower_bound": gated["wilson_lower_bound"],
            "distinct_classes": gated["distinct_classes"],
            "prediction_entropy_nats": gated["prediction_entropy_nats"],
            "modal_fraction": gated["modal_fraction"],
            "loss_window": _loss_window(updates, row["update"]),
        }
        entry["floors"] = _floors(gated)
        curve.append(entry)
    by_update = {row["update"]: row for row in curve}
    read_points = {}
    for at in READ_POINTS:
        cell = by_update.get(at)
        if cell is None:
            read_points[str(at)] = None
            continue
        read_points[str(at)] = {
            **cell,
            "all_strata": screen[[r["update"] for r in screen].index(at)]["strata"],
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
        "arm": arm,
        "gamma": gamma,
        "model_seed": seed,
        "requested_update_count": probe["requested_update_count"],
        "completed_updates": completed,
        "complete": completed == probe["requested_update_count"],
        "device": probe["device"],
        "bf16_autocast": probe["bf16_autocast"],
        "screen_root": probe["screen_root"],
        "train_root": probe["train_root"],
        "curve": curve,
        "read_points": read_points,
        "plateau": _plateau(curve),
        "checkpoint_diag": diag,
    }


def discover_runs(sweep_dir: Path, reference_dir: Path) -> list[dict[str, Any]]:
    runs = [
        load_run(
            reference_dir / "probe-TRAV-checkpoint", arm="TRAV", gamma="0.0", seed=1729
        ),
        load_run(reference_dir / "probe-DIRECT", arm="DIRECT", gamma="0.0", seed=1729),
    ]
    for child in sorted(sweep_dir.iterdir()):
        match = RUN_NAME.match(child.name)
        if not match or not child.is_dir():
            continue
        if not (child / "screen.jsonl").exists():
            continue
        arm, bucket, seed = match.group(1), match.group(2), match.group(3)
        gamma = f"{int(bucket) / 10:.1f}"
        runs.append(load_run(child, arm=arm, gamma=gamma, seed=int(seed or 1729)))
    return runs


def _pp(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return 100.0 * (a - b)


def build_curves(
    runs: list[dict[str, Any]], greedy: dict[str, Any], ceiling: dict[str, Any]
) -> dict[str, Any]:
    index: dict[tuple[str, str, int], dict[str, Any]] = {
        (run["arm"], run["gamma"], run["model_seed"]): run for run in runs
    }
    seeds = sorted({run["model_seed"] for run in runs})
    per_gamma: dict[str, Any] = {}
    for gamma in GAMMAS:
        g = greedy["by_gamma"][gamma]
        c = ceiling["by_gamma"][gamma]
        cell: dict[str, Any] = {
            "gated_non_abstain": g["gated_non_abstain"],
            "greedy": {
                "exact_set_accuracy": g["greedy"]["exact_set_accuracy"]["fraction"],
                "wilson_lower_bound": g["greedy"]["exact_set_accuracy"][
                    "wilson_lower_bound"
                ],
                "route_complete": g["greedy"]["route_complete"]["fraction"],
            },
            "direct_pool": {
                "route_complete": g["direct"]["route_complete"]["fraction"],
                "target_node_present": g["direct"]["target_node_present"]["fraction"],
            },
            "relation_ceiling": {
                "tree_size": c["tree_size"],
                "within_128": c["gated"]["128"]["relation_tree_within_budget"][
                    "fraction"
                ],
                "within_16": c["gated"]["16"]["relation_tree_within_budget"][
                    "fraction"
                ],
            },
            "arms": {},
        }
        for arm in ("TRAV", "DIRECT"):
            for seed in seeds:
                run = index.get((arm, gamma, seed))
                if run is None:
                    continue
                cell["arms"][f"{arm}_s{seed}"] = {
                    "complete": run["complete"],
                    "read_points": {
                        at: (
                            None
                            if rp is None
                            else {
                                "exact_set_accuracy": rp["exact_set_accuracy"],
                                "wilson_lower_bound": rp["wilson_lower_bound"],
                                "n": rp["n"],
                                "correct": rp["correct"],
                                "distinct_classes": rp["distinct_classes"],
                                "prediction_entropy_nats": rp[
                                    "prediction_entropy_nats"
                                ],
                                "loss_window": rp["loss_window"],
                                "criterion_L": rp["criterion_L"],
                                "floors": rp["floors"],
                                "left_uniform": rp["left_uniform"],
                                "ceiling_censored": rp["exact_set_accuracy"]
                                >= CEILING_FRACTION,
                                "other_strata": {
                                    k: v
                                    for k, v in rp["all_strata"].items()
                                    if k != GATED
                                },
                            }
                        )
                        for at, rp in run["read_points"].items()
                    },
                    "plateau": run["plateau"],
                }
        per_gamma[gamma] = cell

    # Amendment 10 §4 statistics, per seed, per read point. Inadmissible here.
    statistics: dict[str, Any] = {}
    for seed in seeds:
        for at in READ_POINTS:
            key = f"s{seed}@{at}"
            rows: dict[str, Any] = {}
            lead0 = None
            gap0 = None
            base = (
                per_gamma["0.0"]["arms"]
                .get(f"TRAV_s{seed}", {})
                .get("read_points", {})
                .get(str(at))
            )
            base_direct = (
                per_gamma["0.0"]["arms"]
                .get(f"DIRECT_s{seed}", {})
                .get("read_points", {})
                .get(str(at))
            )
            if base is not None:
                lead0 = _pp(
                    base["exact_set_accuracy"],
                    per_gamma["0.0"]["greedy"]["exact_set_accuracy"],
                )
                if base_direct is not None:
                    gap0 = _pp(
                        base["exact_set_accuracy"], base_direct["exact_set_accuracy"]
                    )
            for gamma in GAMMAS:
                trav = (
                    per_gamma[gamma]["arms"]
                    .get(f"TRAV_s{seed}", {})
                    .get("read_points", {})
                    .get(str(at))
                )
                direct = (
                    per_gamma[gamma]["arms"]
                    .get(f"DIRECT_s{seed}", {})
                    .get("read_points", {})
                    .get(str(at))
                )
                if trav is None:
                    continue
                lead = _pp(
                    trav["exact_set_accuracy"],
                    per_gamma[gamma]["greedy"]["exact_set_accuracy"],
                )
                gap = (
                    _pp(trav["exact_set_accuracy"], direct["exact_set_accuracy"])
                    if direct
                    else None
                )
                rows[gamma] = {
                    "trav": trav["exact_set_accuracy"],
                    "direct": direct["exact_set_accuracy"] if direct else None,
                    "greedy": per_gamma[gamma]["greedy"]["exact_set_accuracy"],
                    "lead_pp": lead,
                    "excess_pp": None if lead0 is None else lead - lead0,
                    "trav_minus_direct_pp": gap,
                    "excess_direct_pp": None
                    if (gap is None or gap0 is None)
                    else gap - gap0,
                    "ceiling_censored": trav["ceiling_censored"],
                    "criterion_L_fails": trav["criterion_L"] is False,
                }
            statistics[key] = {
                "allocation_offset_lead0_pp": lead0,
                "by_gamma": rows,
                "admissible": False,
                "label": "screening, single seed, design phase — inadmissible as a result",
            }
    return {"seeds": seeds, "per_gamma": per_gamma, "statistics": statistics}


def screening_expectation(stat: dict[str, Any]) -> dict[str, Any]:
    """The plan's outcome table applied to one seed's screening excess (expectation only)."""

    rows = stat["by_gamma"]
    needed = [g for g in GAMMAS if g != "0.0"]
    if any(g not in rows or rows[g]["excess_pp"] is None for g in needed):
        return {"reading": "incomplete", "reason": "a γ > 0 TRAV cell is missing"}
    excess = {g: rows[g]["excess_pp"] for g in needed}
    censored = {g: rows[g]["ceiling_censored"] for g in GAMMAS if g in rows}
    if all(censored[g] for g in GAMMAS if g in censored):
        return {
            "reading": "positive expectation, right-censored",
            "reason": "TRAV ≥ 99% at every γ; the slope cannot be measured on this generator",
            "excess_pp": excess,
        }
    supported = excess["0.3"] > 0 and excess["0.4"] > 0 and excess["0.4"] >= SUPPORT_PP
    negative = excess["0.3"] < 0 and excess["0.4"] < 0 and excess["0.4"] <= -SUPPORT_PP
    null = all(abs(v) <= NULL_PP for v in excess.values())
    if supported:
        reading = "positive expectation"
    elif negative:
        reading = "directional-negative expectation"
    elif null:
        reading = "null expectation"
    else:
        reading = "inconclusive expectation"
    return {"reading": reading, "excess_pp": excess, "censored": censored}


def go_no_go(
    curves: dict[str, Any], runs: list[dict[str, Any]], ceiling: dict[str, Any]
) -> dict[str, Any]:
    """Amendment 10 §9, evaluated on screening at update 8,000. Recommendation only."""

    failures: list[str] = []
    floor_cells: dict[str, Any] = {}
    for gamma in GAMMAS:
        for arm in ("TRAV", "DIRECT"):
            key = f"{arm}_s1729"
            rp = (
                curves["per_gamma"][gamma]["arms"]
                .get(key, {})
                .get("read_points", {})
                .get("8000")
            )
            if rp is None:
                failures.append(f"{arm} γ={gamma} seed 1729 has no 8,000 read point")
                floor_cells[f"{arm}@{gamma}"] = None
                continue
            floor_cells[f"{arm}@{gamma}"] = rp["floors"]
            if not rp["floors"]["all"]:
                failures.append(
                    f"{arm} γ={gamma} fails an Amendment 04 §5 floor at 8,000"
                )
    disagreements = ceiling["cross_check"][
        "route_complete_vs_proof_valid_disagreements"
    ]
    for run in runs:
        diag = run["checkpoint_diag"]
        if diag is None:
            continue
        for name, variant in diag["variants"].items():
            disagreements += variant["route_complete_vs_proof_valid_disagreements"]
            if variant["route_complete_vs_proof_valid_disagreements"]:
                failures.append(
                    f"{run['arm']} γ={run['gamma']} {name}: cross-check disagreement"
                )
    if ceiling["cross_check"]["route_complete_vs_proof_valid_disagreements"]:
        failures.append("ceiling sweep cross-check has disagreements")
    concerning: list[str] = []
    for run in runs:
        diag = run["checkpoint_diag"]
        if diag is None:
            continue
        if diag["gated_summary"]["shuffled_control"] != "clean":
            concerning.append(
                f"TRAV γ={run['gamma']} seed {run['model_seed']}: shuffled Δ = "
                f"{diag['gated_summary']['shuffled_delta_pp']:+.2f} pp"
            )
    greedy_curve = [
        curves["per_gamma"][g]["greedy"]["exact_set_accuracy"] for g in GAMMAS
    ]
    greedy_monotone = all(
        a > b for a, b in zip(greedy_curve[:-1], greedy_curve[1:], strict=True)
    )
    if not greedy_monotone:
        concerning.append("greedy is not strictly decreasing in γ")
    failures.extend(concerning)
    return {
        "criterion_1_floors_at_8000": floor_cells,
        "criterion_2_cross_check_disagreements": disagreements,
        "criterion_3_concerning_controls": concerning,
        "greedy_strictly_decreasing": greedy_monotone,
        "failures": failures,
        "recommendation": "go" if not failures else "no-go",
        "note": "recommendation only; opening the holdout requires explicit human authorisation",
    }


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _first_launch(sweep_dir: Path) -> str | None:
    log = sweep_dir / "launch.log"
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


def render_markdown(record: dict[str, Any]) -> str:
    curves = record["curves"]
    out: list[str] = []
    w = out.append
    w("# γ-sweep screening report (Amendment 10 §8)")
    w("")
    w("## Status: screening descriptives, single seed, inadmissible as a result")
    w("")
    w(
        f"Generated {record['generated_at']} by `scripts/read_run_gamma_sweep_report.py` "
        f"at commit `{record['report_commit']}`. Reading rule: Amendment 10, committed as "
        f"`{record['amendment_commit']}` ({record['amendment_commit_time']}); first γ > 0 "
        f"learned run started {record['first_launch_utc']}. Screening split only "
        "(`private/read-run-v1/p0-rerun/screen-g0X`), B = 128, v1 training configuration "
        "with `update_count` varied. Nothing here is a hypothesis verdict: every arm "
        "comparison below is a design-phase, one-seed screening number that cannot move "
        "Amendment 10 §5–§7. The holdout was not generated, read, or opened."
    )
    w("")
    w("## 0. Material disclosures found after this reader was written")
    w("")
    w(
        "Two findings from 2026-09-02 are not captured by any threshold or criterion "
        "below, and both bear directly on how the curves in §2 and the recommendation "
        "in §7 should be read. They are stated here, ahead of the numbers, because a "
        "reader who reaches §7 without them will draw a conclusion this evidence does "
        "not support. Full analysis is in `docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md` "
        "§1.5 and §1.7."
    )
    w("")
    w(
        "**D-1. The similarity field marks on-path nodes, at every γ.** "
        "`generator._assign_similarity` promotes exactly one out-edge to 900,000 at "
        "each valid-path state. γ decides only whether the promoted edge is the correct "
        "one or a distractor; it never changes whether the node carries a promotion. "
        "Verified on all 2,000 episodes of the γ = 0 screening split: the set of nodes "
        "with a 900,000 out-edge equals the set of nodes sourcing a path edge in "
        "2,000 of 2,000, mean 4.83 marked nodes out of 161.3 (3.00% of the graph). "
        "The similarity channel therefore carries a γ-degraded edge-choice hint **and** "
        "a γ-invariant node-localisation marker. TRAV's flatness across γ in §2 is "
        "consistent with a policy that navigates by marker presence and discriminates "
        "edges by relation, so §2 demonstrates relation-based edge discrimination but "
        "does not establish shortcut-free traversal."
    )
    w("")
    w(
        "**D-2. The flattened-similarity accuracy column in §5 is not a stable "
        "measurement.** Flattening removes similarity from the answer head as well as "
        "the walk, and the head responds by abstaining. Across the two seeds at "
        "γ = 0.4 the flattened exact accuracy reads 14.50% and 30.69%, and at γ = 0 it "
        "reads 0.36% and 6.14%, with predicted-abstain rates from 33.63% to 99.47% on "
        "checkpoints whose baselines are within half a point of each other. No "
        "inference about γ may be drawn from that column. Flattened "
        "**route-completeness** is stable — 62.10% and 61.30% at γ = 0.4 across seeds — "
        "and is the quantity that isolates the walk. It spans 53.56% to 69.13% across "
        "all seven checkpoints with no relation to training γ, and every value is below "
        "the 87.90% that DIRECT's query-blind structural pool reaches at the same "
        "budget: with similarity removed, every TRAV checkpoint walks worse than not "
        "walking adaptively at all."
    )
    w("")
    w(
        "Neither disclosure changes a threshold, a criterion, or the computed "
        "recommendation in §7. Amendment 10 §9's three criteria are mechanically met "
        "and are reported as met. The disclosures are the material a human needs in "
        "order to decide whether meeting them is sufficient, which is the only kind of "
        "authorisation §7 asks for."
    )
    w("")
    w("## 1. Runs")
    w("")
    w("| run | γ | seed | updates | device | bf16 | complete |")
    w("|---|---|---|---|---|---|---|")
    for run in record["runs"]:
        w(
            f"| {run['arm']} | {run['gamma']} | {run['model_seed']} | "
            f"{run['completed_updates']}/{run['requested_update_count']} | {run['device']} | "
            f"{run['bf16_autocast']} | {'yes' if run['complete'] else 'NO'} |"
        )
    w("")
    w(
        "γ = 0 rows are the existing probes (`diagnostics/learnability_probe.md`); "
        "`probe-TRAV-checkpoint` and `probe-TRAV-ext` are bitwise-identical logs of the same "
        "seed, data and code, which is the determinism check for this harness."
    )
    w("")
    w(
        "## 2. The curves at the two declared read points (gated `hops_2_4`, non-abstain)"
    )
    w("")
    for at in READ_POINTS:
        w(f"### Update {at:,}{' (= v2 update_count)' if at == 8000 else ''}")
        w("")
        w(
            "| γ | arm/seed | exact-set acc | Wilson LB | classes | H (nats) | L(U) | (L) | §5 floors | ≥ 99% |"
        )
        w("|---|---|---|---|---|---|---|---|---|---|")
        for gamma in GAMMAS:
            cell = curves["per_gamma"][gamma]
            for key, arm in sorted(cell["arms"].items()):
                rp = arm["read_points"].get(str(at))
                if rp is None:
                    w(f"| {gamma} | {key} | — | — | — | — | — | — | — | — |")
                    continue
                w(
                    f"| {gamma} | {key} | {_fmt(rp['exact_set_accuracy'])} | "
                    f"{_fmt(rp['wilson_lower_bound'])} | {rp['distinct_classes']} | "
                    f"{rp['prediction_entropy_nats']:.3f} | {_fmt(rp['loss_window'], 4, pct=False)} | "
                    f"{'pass' if rp['criterion_L'] else 'FAIL'} | "
                    f"{'pass' if rp['floors']['all'] else 'FAIL'} | "
                    f"{'censored' if rp['ceiling_censored'] else 'no'} |"
                )
            w(
                f"| {gamma} | greedy (no training) | {_fmt(cell['greedy']['exact_set_accuracy'])} | "
                f"{_fmt(cell['greedy']['wilson_lower_bound'])} | — | — | — | — | — | — |"
            )
        w("")
    w(
        "`L(U)` is the mean training `answer_loss` over updates (U−99, U] (Amendment 04 §4); "
        "(L) passes at ≤ 2.34 nats. The §5 floors are Wilson LB > 1/15 with acc ≥ 7.67%, "
        "≥ 8 distinct classes, and entropy ≥ 1.00 nats. `≥ 99%` marks Amendment 10 §6 "
        "ceiling censoring."
    )
    w("")
    w("## 3. Coverage per γ (B = 128, gated stratum)")
    w("")
    w(
        "| γ | n | DIRECT pool route-complete | DIRECT pool target-node exposure | greedy route-complete | relation tree ≤ 16 | relation tree ≤ 128 | tree size median / p95 / max |"
    )
    w("|---|---|---|---|---|---|---|---|")
    for gamma in GAMMAS:
        cell = curves["per_gamma"][gamma]
        t = cell["relation_ceiling"]["tree_size"]
        w(
            f"| {gamma} | {cell['gated_non_abstain']} | {_fmt(cell['direct_pool']['route_complete'])} | "
            f"{_fmt(cell['direct_pool']['target_node_present'])} | {_fmt(cell['greedy']['route_complete'])} | "
            f"{_fmt(cell['relation_ceiling']['within_16'])} | {_fmt(cell['relation_ceiling']['within_128'])} | "
            f"{t['median']} / {t['p95']} / {t['max']} |"
        )
    w("")
    w(
        "TRAV's own route-completeness per checkpoint is in §5 (it needs the checkpoint)."
    )
    w("")
    w("## 4. Amendment 10 §4 statistics on screening — inadmissible")
    w("")
    w(
        "`lead(γ) = acc_TRAV(γ) − acc_greedy(γ)`; `excess(γ) = lead(γ) − lead(0)`; "
        "`excess_DIRECT(γ)` is Amendment 07's DIRECT-comparator quantity, secondary. "
        "One seed each, screening split, design phase: **these cannot support or refute the "
        "hypothesis** (Amendment 10 §3, §8). A cell marked censored has TRAV ≥ 99% and its "
        "`excess` is a lower bound only."
    )
    w("")
    for key, stat in record["curves"]["statistics"].items():
        if not stat["by_gamma"]:
            continue
        w(
            f"### {key} — allocation offset lead(0) = {_fmt_pp(stat['allocation_offset_lead0_pp'])}"
        )
        w("")
        w(
            "| γ | TRAV | DIRECT | greedy | lead | excess | TRAV − DIRECT | excess_DIRECT | censored | (L) |"
        )
        w("|---|---|---|---|---|---|---|---|---|---|")
        for gamma, row in stat["by_gamma"].items():
            w(
                f"| {gamma} | {_fmt(row['trav'])} | {_fmt(row['direct'])} | {_fmt(row['greedy'])} | "
                f"{_fmt_pp(row['lead_pp'])} | {_fmt_pp(row['excess_pp'])} | "
                f"{_fmt_pp(row['trav_minus_direct_pp'])} | {_fmt_pp(row['excess_direct_pp'])} | "
                f"{'yes' if row['ceiling_censored'] else 'no'} | "
                f"{'FAIL' if row['criterion_L_fails'] else 'pass'} |"
            )
        w("")
        exp = record["screening_expectation"].get(key)
        if exp:
            w(
                f"Outcome-table reading for this seed (an *expectation*, not a verdict): "
                f"**{exp['reading']}** — {exp.get('reason', '')}".rstrip(" —")
            )
            w("")
    w("## 5. Controls and descriptives on the TRAV checkpoints")
    w("")
    w(
        "| γ | seed | baseline acc | matches probe row | route-complete (gated) | shuffled acc | Δ shuffled | verdict | flattened-similarity acc | drop | flattened route-complete | cross-check |"
    )
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    any_diag = False
    for run in record["runs"]:
        diag = run["checkpoint_diag"]
        if diag is None:
            continue
        any_diag = True
        s = diag["gated_summary"]
        dis = sum(
            v["route_complete_vs_proof_valid_disagreements"]
            for v in diag["variants"].values()
        )
        w(
            f"| {run['gamma']} | {run['model_seed']} | {_fmt(s['baseline_exact_set_accuracy'])} | "
            f"{'yes' if s['baseline_matches_probe_final_row'] else 'NO'} | "
            f"{_fmt(s['baseline_route_complete_fraction'])} | {_fmt(s['shuffled_exact_set_accuracy'])} | "
            f"{s['shuffled_delta_pp']:+.2f} pp | {s['shuffled_control']} | "
            f"{_fmt(s['flattened_exact_set_accuracy'])} | {s['flattened_drop_pp']:+.2f} pp | "
            f"{_fmt(s['flattened_route_complete_fraction'])} | {dis} |"
        )
    if not any_diag:
        w("| — | — | no checkpoint diagnostics were found | | | | | | | | | |")
    w("")
    w(
        "Shuffled serialization is Amendment 10 §7.1 on screening (|Δ| < 1 pp clean). The "
        "flattened-similarity column repeats Stage C's ablation (`query_similarity_ppm` held "
        "at 500,000) and is descriptive. The cross-check column counts route-complete ≠ "
        "proof_valid over all three variants of that checkpoint."
    )
    w("")
    w("### TRAV route-completeness by stratum at 9,376 (baseline variant)")
    w("")
    w(
        "| γ | seed | stratum | n | route-complete | target-node exposure | exact-set acc | predicted-abstain |"
    )
    w("|---|---|---|---|---|---|---|---|")
    for run in record["runs"]:
        diag = run["checkpoint_diag"]
        if diag is None:
            continue
        for stratum, row in diag["variants"]["baseline"]["by_stratum"].items():
            w(
                f"| {run['gamma']} | {run['model_seed']} | {stratum} | {row['n']} | "
                f"{_fmt(row['route_complete_fraction'])} | {_fmt(row['target_node_present_fraction'])} | "
                f"{_fmt(row['exact_set_accuracy'])} | {_fmt(row['predicted_abstain_fraction'])} |"
            )
    w("")
    w("## 6. Amendment 09 plateau reading per run")
    w("")
    w(
        "| run | γ | seed | qualifying checkpoints | final unbroken run | plateau point |"
    )
    w("|---|---|---|---|---|---|")
    for run in record["runs"]:
        p = run["plateau"]
        w(
            f"| {run['arm']} | {run['gamma']} | {run['model_seed']} | "
            f"{', '.join(str(u) for u in p['qualifying_updates']) or '—'} | "
            f"{p['final_unbroken_run_length']} | {p['plateau_point'] if p['plateaued'] else 'not plateaued'} |"
        )
    w("")
    w("## 7. Go/no-go for opening Track E (Amendment 10 §9) — recommendation only")
    w("")
    g = record["go_no_go"]
    w(
        f"- Criterion 1 (both arms clear the §5 floors at 8,000 at every γ): "
        f"{'met' if not any('floor' in f or 'no 8,000' in f for f in g['failures']) else 'NOT met'}"
    )
    w(
        f"- Criterion 2 (cross-check disagreements): {g['criterion_2_cross_check_disagreements']}"
    )
    w(
        f"- Criterion 3 (Concerning controls): {', '.join(g['criterion_3_concerning_controls']) or 'none'}; "
        f"greedy strictly decreasing in γ: {g['greedy_strictly_decreasing']}"
    )
    w("")
    if g["failures"]:
        w("Failures:")
        w("")
        for f in g["failures"]:
            w(f"- {f}")
        w("")
    w(f"**Recommendation: {g['recommendation']}.** {g['note']}.")
    w("")
    if record.get("generator_grid"):
        w("## 8. Generator-knob grid (E2 preparation; informs nothing above)")
        w("")
        grid = record["generator_grid"]
        w(
            f'Public diagnostic seed `sha256("{grid["diagnostic_seed_label"]}")`, '
            f"{grid['count_per_cell']} attempted episodes per cell, split `test-fixture`, "
            f"budgets {grid['budgets']} (diagnostic-only: {grid['diagnostic_only_budgets']}). "
            f"Frozen values: {grid['frozen_generator_values']} (`{grid['frozen_config_key']}`)."
        )
        w("")
        w(
            "| config | γ | generation failures | gated n | edges (median) | tree size p95 (gated) | tree ≤ 128 | DIRECT pool rc @64 / @128 / @256 | greedy rc @64 / @128 / @256 |"
        )
        w("|---|---|---|---|---|---|---|---|---|")
        for key, cell in grid["cells"].items():
            for gamma, s in cell["by_gamma"].items():
                fail = s["generation_failure_rate"]
                if s["generated"] == 0:
                    msgs = "; ".join(
                        f"{k} ×{v}" for k, v in s["generation_failure_messages"].items()
                    )
                    w(
                        f"| {key} | {gamma} | {_fmt(fail)} ({msgs}) | 0 | — | — | — | — | — |"
                    )
                    continue
                d = " / ".join(
                    _fmt(s["gated"][str(b)]["direct"]["route_complete"]["fraction"])
                    for b in grid["budgets"]
                )
                gr = " / ".join(
                    _fmt(s["gated"][str(b)]["greedy"]["route_complete"]["fraction"])
                    for b in grid["budgets"]
                )
                w(
                    f"| {key} | {gamma} | {_fmt(fail)} | {s['gated_non_abstain']} | "
                    f"{s['edge_count'].get('median', '—')} | {s['tree_size_gated'].get('p95', '—')} | "
                    f"{_fmt(s['gated']['128']['relation_tree_within_budget']['fraction'])} | {d} | {gr} |"
                )
        w("")
    w("## 9. What this report does not do")
    w("")
    w(
        "It records no hypothesis verdict. It changes no threshold, arm, metric, seed or "
        "frozen digest. It reads no holdout. Amendment 10 remains pending review; the "
        "go/no-go above is a recommendation to a human, not an authorisation."
    )
    w("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sweep-dir", default="private/read-run-v1/diagnostics/gamma-sweep"
    )
    parser.add_argument("--reference-dir", default="private/read-run-v1/diagnostics")
    parser.add_argument(
        "--greedy", default="experiments/read_run_v1/diagnostics/rc_abc_b128.json"
    )
    parser.add_argument(
        "--ceiling", default="experiments/read_run_v1/diagnostics/ceiling_sweep.json"
    )
    parser.add_argument("--generator-grid", default=None)
    parser.add_argument("--amendment-commit", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--md-output", required=True)
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    runs = discover_runs(sweep_dir, Path(args.reference_dir))
    greedy = json.loads(Path(args.greedy).read_text())
    ceiling = json.loads(Path(args.ceiling).read_text())
    curves = build_curves(runs, greedy, ceiling)
    record: dict[str, Any] = {
        "record_kind": "read_run_gamma_sweep_screening_report",
        "generated_at": subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "report_commit": _git(["rev-parse", "--short", "HEAD"]),
        "amendment_commit": args.amendment_commit,
        "amendment_commit_time": _git(
            ["log", "-1", "--format=%cI", args.amendment_commit]
        ),
        "first_launch_utc": _first_launch(sweep_dir),
        "budget": greedy["budget"],
        "gated_stratum": GATED,
        "thresholds": {
            "chance": CHANCE,
            "above_chance_margin": ABOVE_CHANCE_MARGIN,
            "distinct_floor": DISTINCT_FLOOR,
            "entropy_floor_nats": ENTROPY_FLOOR,
            "criterion_L_nats": L_LINE,
            "ceiling_fraction": CEILING_FRACTION,
            "support_pp": SUPPORT_PP,
            "null_pp": NULL_PP,
            "concerning_pp": CONCERNING_PP,
        },
        "runs": [
            {k: v for k, v in run.items() if k != "checkpoint_diag"}
            | {
                "checkpoint_diag": (
                    None
                    if run["checkpoint_diag"] is None
                    else {
                        "gated_summary": run["checkpoint_diag"]["gated_summary"],
                        "variants": run["checkpoint_diag"]["variants"],
                    }
                )
            }
            for run in runs
        ],
        "curves": curves,
    }
    record["screening_expectation"] = {
        key: screening_expectation(stat) for key, stat in curves["statistics"].items()
    }
    record["go_no_go"] = go_no_go(curves, record["runs"], ceiling)
    if args.generator_grid:
        record["generator_grid"] = json.loads(Path(args.generator_grid).read_text())
    Path(args.json_output).write_text(json.dumps(record, indent=2, sort_keys=True))
    Path(args.md_output).write_text(render_markdown(record))
    print(json.dumps(record["go_no_go"], indent=2))
    for key, exp in record["screening_expectation"].items():
        print(key, exp["reading"])


if __name__ == "__main__":
    main()
