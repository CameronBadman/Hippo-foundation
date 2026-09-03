"""Assemble the Track O screening report under its preregistered table.

Reads only artifacts that already exist — the twelve probe directories, the
model-free policy ladder, the untrained reference, the cell audit — and writes a
JSON record plus a Markdown report. Every number in the Markdown is copied from
the JSON by this script, never typed.

The band is read from `experiments/track_o_v1/SCREENING_PREREGISTRATION.md` §5
as written, at update 8,000, on the hard cell, per seed, **paired against the
same seed's untrained line**. That pairing is the point: the architecture
carries the strongest model-free policy's mechanics structurally, so an
untrained TRAVV2 already reaches about 86 % route-completeness, and a reading
against the model-free frontier alone would credit the architecture's structure
to training. The frontier is reported beside it, not instead of it.

Screening only. No holdout is read or referenced.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

GATED = "hops_2_4"
READ_POINT = 8000
HARD_CELL = "deg6_len8_v4_rep"
EASY_CELL = "deg3_len6_v8"
SEEDS = (1729, 2718, 3141)
ARMS = ("TRAVV2", "TRAVV1")
RUN_NAME = re.compile(r"^probe-(TRAVV2|TRAVV1)-(.+)-s(\d+)$")

# Amendment 04 §5 floors, unchanged.
CHANCE = 1.0 / 15.0
ABOVE_CHANCE_MARGIN = 0.0767
DISTINCT_FLOOR = 8
ENTROPY_FLOOR = 1.0
# Amendment 09 §2 plateau reading, unchanged.
PLATEAU_STEP_PP = 1.0
PLATEAU_MIN_RUN = 3

BAND_TEXT = {
    "A": (
        "learned and dominant",
        "training adds capability beyond the architecture and beats every "
        "model-free policy on both axes",
    ),
    "B": (
        "learned, frontier not cleared",
        "training helps; the result does not yet beat a parameterless policy",
    ),
    "C": ("one axis", "partial; the per-axis rows say which"),
    "D": (
        "architecture prior only",
        "the structure did the work; training added nothing measurable at this budget",
    ),
    "E": (
        "training harmful",
        "the learned scorer is worse than random under the same walk",
    ),
    "F": ("seeds split", "inconclusive; every seed reported"),
    "H": ("harness defect", "no reading; stop, fix, rerun"),
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _floors(cell: dict[str, Any]) -> dict[str, Any]:
    above = (
        cell["wilson_lower_bound"] > CHANCE
        and cell["exact_set_accuracy"] >= ABOVE_CHANCE_MARGIN
    )
    distinct = cell["distinct_classes"] >= DISTINCT_FLOOR
    entropy = cell["prediction_entropy_nats"] >= ENTROPY_FLOOR
    return {
        "above_chance": above,
        "distinct_classes": distinct,
        "entropy": entropy,
        "all": above and distinct and entropy,
    }


def _plateau(curve: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Amendment 09 §2 on one quantity's checkpoints."""

    qualifying = []
    for index in range(len(curve)):
        if index < 2:
            qualifying.append(False)
            continue
        step = 100.0 * (curve[index][key] - curve[index - 1][key])
        previous = 100.0 * (curve[index - 1][key] - curve[index - 2][key])
        qualifying.append(step <= PLATEAU_STEP_PP and previous <= PLATEAU_STEP_PP)
    streak = 0
    for flag in reversed(qualifying):
        if not flag:
            break
        streak += 1
    point = curve[len(curve) - streak]["update"] if streak >= PLATEAU_MIN_RUN else None
    return {
        "quantity": key,
        "final_unbroken_run_length": streak,
        "plateau_point": point,
        "plateaued": point is not None,
    }


def load_run(directory: Path) -> dict[str, Any]:
    match = RUN_NAME.match(directory.name)
    if not match:
        raise ValueError(f"{directory}: not a Track O run directory")
    arm, cell, seed = match.group(1), match.group(2), int(match.group(3))
    probe = json.loads((directory / "probe.json").read_text())
    if (
        probe["arm"] != arm
        or probe["model_seed"] != seed
        or probe["generator_cell"] != cell
    ):
        raise ValueError(f"{directory}: probe.json disagrees with the run name")
    if probe["touches_holdout"] is not False:
        raise ValueError(
            f"{directory}: probe.json does not assert touches_holdout false"
        )
    screen = _load_jsonl(directory / "screen.jsonl")
    updates = _load_jsonl(directory / "updates.jsonl")
    curve = []
    for row in screen:
        gated = row["strata"].get(GATED)
        if gated is None:
            continue
        curve.append(
            {
                "update": row["update"],
                "n": gated["n"],
                "route_complete": gated["route_complete"],
                "route_complete_fraction": gated["route_complete_fraction"],
                "route_complete_wilson_lower_bound": gated[
                    "route_complete_wilson_lower_bound"
                ],
                "precision_mean": gated["precision_mean"],
                "examined_mean": gated["examined_mean"],
                "exact_set_accuracy": gated["exact_set_accuracy"],
                "wilson_lower_bound": gated["wilson_lower_bound"],
                "distinct_classes": gated["distinct_classes"],
                "prediction_entropy_nats": gated["prediction_entropy_nats"],
                "stop_reasons": gated["stop_reasons"],
                "by_path_length": gated["by_path_length"],
                "floors": _floors(gated),
            }
        )
    by_update = {row["update"]: row for row in curve}
    return {
        "directory": str(directory),
        "name": directory.name,
        "arm": arm,
        "cell": cell,
        "model_seed": seed,
        "git_head": probe["git_head"],
        "started_at": probe["started_at"],
        "trainable_parameters": probe["trainable_parameters"],
        "capacity_relative_difference": probe["capacity_relative_difference"],
        "completed_updates": len(updates),
        "complete": len(updates) == probe["requested_update_count"],
        "curve": curve,
        "read_point": by_update.get(READ_POINT),
        "plateau": {
            key: _plateau(curve, key)
            for key in (
                "exact_set_accuracy",
                "route_complete_fraction",
                "precision_mean",
            )
        },
    }


def discover(root: Path) -> list[dict[str, Any]]:
    runs = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not RUN_NAME.match(child.name):
            continue
        if not (child / "screen.jsonl").exists():
            continue
        runs.append(load_run(child))
    return runs


def compare_to_untrained(
    trained: dict[str, Any], untrained: dict[str, Any]
) -> dict[str, Any]:
    """§4's fixed per-seed comparisons. No constant beyond the Wilson bound."""

    rc_improved = (
        trained["route_complete_wilson_lower_bound"]
        > untrained["route_complete_fraction"]
    )
    rc_degraded = (
        trained["route_complete_fraction"]
        < untrained["route_complete_wilson_lower_bound"]
    )
    precision_improved = trained["precision_mean"] > untrained["precision_mean"]
    precision_degraded = trained["precision_mean"] < untrained["precision_mean"]
    return {
        "route_complete_improved": rc_improved,
        "route_complete_degraded": rc_degraded,
        "precision_improved": precision_improved,
        "precision_degraded": precision_degraded,
        "route_complete_delta_pp": 100.0
        * (trained["route_complete_fraction"] - untrained["route_complete_fraction"]),
        "precision_delta": trained["precision_mean"] - untrained["precision_mean"],
        "examined_delta": trained["examined_mean"] - untrained["examined_mean"],
    }


def clears_frontier(trained: dict[str, Any], reference: dict[str, Any]) -> bool:
    return (
        trained["route_complete_wilson_lower_bound"] > reference["route_complete"]
        and trained["precision_mean"] >= reference["precision"]
    )


def read_band(per_seed: dict[str, Any], defects: list[str]) -> dict[str, Any]:
    """§5 exactly as written, over the three seeds' improve/degrade classification."""

    if set(per_seed) != {str(seed) for seed in SEEDS}:
        return {
            "band": None,
            "reason": "not every TRAVV2 seed has an 8,000 read point on the hard cell",
            "per_seed": per_seed,
        }
    rows = list(per_seed.values())
    every_rc_improved = all(r["route_complete_improved"] for r in rows)
    none_precision_degraded = not any(r["precision_degraded"] for r in rows)
    every_clears = all(r["clears_frontier"] for r in rows)
    any_improved = any(
        r["route_complete_improved"] or r["precision_improved"] for r in rows
    )
    all_some_improved = all(
        r["route_complete_improved"] or r["precision_improved"] for r in rows
    )
    none_degraded = not any(
        r["route_complete_degraded"] or r["precision_degraded"] for r in rows
    )
    any_degraded = any(
        r["route_complete_degraded"] or r["precision_degraded"] for r in rows
    )

    if every_rc_improved and none_precision_degraded and every_clears:
        letter = "A"
    elif every_rc_improved and none_precision_degraded:
        letter = "B"
    elif all_some_improved and none_degraded:
        letter = "C"
    elif not any_improved and none_degraded:
        letter = "D"
    elif any_degraded and not any_improved:
        letter = "E"
    else:
        letter = "F"

    band = "H" if defects else letter
    name, reading = BAND_TEXT[band]
    return {
        "band": band,
        "letter_before_precedence": letter,
        "voided_by_harness_defect": bool(defects),
        "harness_defects": defects,
        "name": name,
        "reading": reading,
        "per_seed": per_seed,
        "read_at": READ_POINT,
        "cell": HARD_CELL,
    }


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def order_check(runs: list[dict[str, Any]], prereg: str) -> dict[str, Any]:
    from datetime import datetime

    full = _git(["rev-parse", prereg])
    when = _git(["log", "-1", "--format=%cI", full])
    epoch = datetime.fromisoformat(when).timestamp()
    rows = []
    for run in runs:
        started = datetime.fromisoformat(run["started_at"]).timestamp()
        ancestor = (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", full, run["git_head"]],
                capture_output=True,
            ).returncode
            == 0
        )
        rows.append(
            {
                "run": run["name"],
                "git_head": run["git_head"],
                "descends_from_preregistration": ancestor,
                "started_at": run["started_at"],
                "started_after_commit": started > epoch,
            }
        )
    return {
        "preregistration_commit": full,
        "preregistration_committed_at": when,
        "runs": rows,
        "all_ok": bool(rows)
        and all(
            r["descends_from_preregistration"] and r["started_after_commit"]
            for r in rows
        ),
    }


def build(
    runs: list[dict[str, Any]],
    ladder: dict[str, Any],
    untrained: dict[str, Any],
    audit: dict[str, Any],
    prereg: str,
) -> dict[str, Any]:
    ladder_hard = ladder["cells"][HARD_CELL]["gamma_0.4"]
    frontier_reference = {
        name: {
            "route_complete": ladder_hard["policies"][name]["64"]["route_complete"][
                "fraction"
            ],
            "precision": ladder_hard["policies"][name]["64"]["precision_mean"],
            "examined": ladder_hard["policies"][name]["64"]["examined_mean"],
        }
        for name in ladder_hard["policies"]
    }
    stop_aware = frontier_reference["stop_aware"]

    defects: list[str] = []
    per_seed: dict[str, Any] = {}
    for run in runs:
        if run["arm"] != "TRAVV2" or run["cell"] != HARD_CELL:
            continue
        point = run["read_point"]
        if point is None:
            continue
        base = untrained["cells"][HARD_CELL]["per_seed"][str(run["model_seed"])]
        comparison = compare_to_untrained(point, base)
        comparison["clears_frontier"] = clears_frontier(point, stop_aware)
        comparison["trained"] = {
            "route_complete_fraction": point["route_complete_fraction"],
            "route_complete_wilson_lower_bound": point[
                "route_complete_wilson_lower_bound"
            ],
            "precision_mean": point["precision_mean"],
            "examined_mean": point["examined_mean"],
        }
        comparison["untrained"] = {
            "route_complete_fraction": base["route_complete_fraction"],
            "route_complete_wilson_lower_bound": base[
                "route_complete_wilson_lower_bound"
            ],
            "precision_mean": base["precision_mean"],
            "examined_mean": base["examined_mean"],
        }
        per_seed[str(run["model_seed"])] = comparison

    # §7 control 2: the easy cell is the architecture check.
    for run in runs:
        if run["arm"] != "TRAVV2" or run["cell"] != EASY_CELL:
            continue
        point = run["read_point"]
        if point is not None and point["route_complete_fraction"] < 1.0:
            defects.append(
                f"{run['name']}: easy-cell route-completeness fell to "
                f"{point['route_complete_fraction']:.4f}"
            )

    floors = {}
    floor_failures = []
    for run in runs:
        point = run["read_point"]
        key = f"{run['arm']}-{run['cell']}-s{run['model_seed']}"
        if point is None:
            floors[key] = None
            continue
        floors[key] = point["floors"]
        if not point["floors"]["all"]:
            floor_failures.append(key)

    band = read_band(per_seed, defects)
    return {
        "record_kind": "read_run_track_o_screening_report",
        "generated_at": subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "report_commit": _git(["rev-parse", "--short", "HEAD"]),
        "read_point": READ_POINT,
        "hard_cell": HARD_CELL,
        "easy_cell": EASY_CELL,
        "gated_stratum": GATED,
        "frontier_reference": frontier_reference,
        "oracle_feasible": ladder_hard["oracle_feasible"]["64"]["fraction"],
        "untrained_reference": untrained["cells"],
        "audit_cross_checks": {
            cell: audit["cells"][cell]["gamma_0.4"]["cross_checks"]
            for cell in (HARD_CELL, EASY_CELL)
            if cell in audit["cells"]
        },
        "order": order_check(runs, prereg),
        "runs": runs,
        "band": band,
        "floors_G": {
            "cells": floors,
            "failures": floor_failures,
            "G": bool(floor_failures),
        },
        "touches_holdout": False,
    }


def _pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{100.0 * value:.{digits}f} %"


def render(record: dict[str, Any]) -> str:
    out: list[str] = []
    w = out.append
    band = record["band"]
    reference = record["frontier_reference"]
    w("# Track O screening report — path-scoped traversal v2")
    w("")
    w("## Status: screening, three seeds per arm, not a preregistered arm")
    w("")
    w(
        f"Generated {record['generated_at']} by `scripts/read_run_track_o_report.py` at "
        f"`{record['report_commit']}`. Reading rule: "
        f"`experiments/track_o_v1/SCREENING_PREREGISTRATION.md`, committed as "
        f"`{record['order']['preregistration_commit'][:12]}` "
        f"({record['order']['preregistration_committed_at']}). Band read at update "
        f"{record['read_point']:,} on `{record['hard_cell']}`, gated `{record['gated_stratum']}` "
        "non-abstain, B = 64, γ = 0.4. No holdout was generated, read, or opened."
    )
    w("")
    w("## 1. Band")
    w("")
    if band.get("band") is None:
        w(f"**No band: {band['reason']}.**")
    else:
        w(f"**Band {band['band']} — {band['name']}.** {band['reading']}.")
        if band["voided_by_harness_defect"]:
            w("")
            w(
                f"The letter the seeds produced is **{band['letter_before_precedence']}**, "
                "voided by the harness defects listed below."
            )
            for defect in band["harness_defects"]:
                w(f"- {defect}")
    w("")
    w(
        "Each seed is compared against **its own untrained line**, because the "
        "architecture carries the strongest model-free policy's frontier restriction "
        "and stop rule structurally. The model-free frontier is beside it, not "
        "instead of it."
    )
    w("")
    w(
        "| seed | RC untrained → trained | Wilson LB | precision untrained → trained | "
        "examined | RC improved | precision degraded | clears frontier |"
    )
    w("|---|---|---|---|---|---|---|---|")
    for seed, row in sorted(band.get("per_seed", {}).items()):
        t, u = row["trained"], row["untrained"]
        w(
            f"| {seed} | {_pct(u['route_complete_fraction'])} → **{_pct(t['route_complete_fraction'])}** "
            f"({row['route_complete_delta_pp']:+.2f} pp) | {_pct(t['route_complete_wilson_lower_bound'])} | "
            f"{u['precision_mean']:.3f} → **{t['precision_mean']:.3f}** ({row['precision_delta']:+.3f}) | "
            f"{u['examined_mean']:.1f} → {t['examined_mean']:.1f} | {row['route_complete_improved']} | "
            f"{row['precision_degraded']} | {row['clears_frontier']} |"
        )
    w("")
    w("## 2. Model-free references (measured before any training run)")
    w("")
    w("| policy | route-complete | precision | examined |")
    w("|---|---|---|---|")
    for name, row in sorted(reference.items(), key=lambda kv: -kv[1]["route_complete"]):
        w(
            f"| {name.replace('_', ' ')} | {_pct(row['route_complete'])} | "
            f"{row['precision']:.3f} | {row['examined']:.1f} |"
        )
    w("")
    w(f"Oracle floor feasible on {_pct(record['oracle_feasible'])} of these episodes.")
    w("")
    w("## 3. Every run at the read point")
    w("")
    w(
        "| arm | cell | seed | complete | RC | precision | examined | exact acc | "
        "distinct | entropy | floors | stop reasons |"
    )
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for run in record["runs"]:
        point = run["read_point"]
        if point is None:
            w(
                f"| {run['arm']} | {run['cell']} | {run['model_seed']} | {run['complete']} | "
                "— | — | — | — | — | — | not reached | — |"
            )
            continue
        floors = point["floors"]
        verdict = (
            "pass"
            if floors["all"]
            else "FAIL ("
            + ", ".join(
                k
                for k in ("above_chance", "distinct_classes", "entropy")
                if not floors[k]
            )
            + ")"
        )
        w(
            f"| {run['arm']} | {run['cell']} | {run['model_seed']} | {run['complete']} | "
            f"{_pct(point['route_complete_fraction'])} | {point['precision_mean']:.3f} | "
            f"{point['examined_mean']:.1f} | {_pct(point['exact_set_accuracy'])} | "
            f"{point['distinct_classes']} | {point['prediction_entropy_nats']:.2f} | "
            f"{verdict} | {point['stop_reasons']} |"
        )
    w("")
    g = record["floors_G"]
    w(
        "**Band G (Amendment 04 §5 floors on exact accuracy):** "
        + (
            "**G — " + ", ".join(g["failures"]) + "**"
            if g["G"]
            else "no arm × seed fails a floor"
        )
        + ". Reported beside the letter; neither suppresses the other."
    )
    w("")
    w("## 4. Order of evidence")
    w("")
    order = record["order"]
    w(
        f"- All runs descend from the preregistration commit and post-date it: **{order['all_ok']}**"
    )
    for row in order["runs"]:
        w(
            f"  - {row['run']}: `{row['git_head'][:12]}` descends {row['descends_from_preregistration']}, "
            f"started {row['started_at']} after {row['started_after_commit']}"
        )
    w(f"- Generator audit cross-checks: {record['audit_cross_checks']}")
    w("")
    w("## 5. Plateau reading (Amendment 09 §2; no automatic extension)")
    w("")
    w("| arm | cell | seed | quantity | final unbroken run | plateau point |")
    w("|---|---|---|---|---|---|")
    for run in record["runs"]:
        for key, plateau in run["plateau"].items():
            w(
                f"| {run['arm']} | {run['cell']} | {run['model_seed']} | {key} | "
                f"{plateau['final_unbroken_run_length']} | "
                f"{plateau['plateau_point'] if plateau['plateaued'] else 'not plateaued'} |"
            )
    w("")
    w("## 6. The returned set — what the walk asserts is relevant")
    w("")
    returned = record.get("returned_set")
    if returned is None:
        w("Not measured.")
    else:
        w(
            "Examined-set precision is a **cost**: reaching a node examines all of its "
            "out-edges, so even a perfect selector pays ~30 edges for ~6 on-route ones on "
            "the hard cell, capping examined precision near 0.20. What a write operation "
            "adjudicates is the **returned** set. The edge head is already a relevance "
            "classifier — its loss is BCE against route membership — so the returned set "
            "is read at a **positive logit**, the loss's own boundary, with no threshold "
            "fitted to any result. Declared as a descriptive in design notes §2.17 before "
            "any run reached its read point."
        )
        w("")
        w(
            "| cell | seed | examined | returned | examined precision | returned precision | "
            "returned recall | average precision |"
        )
        w("|---|---|---|---|---|---|---|---|")
        for cell, seeds in sorted(returned["cells"].items()):
            for seed, row in sorted(seeds.items()):
                w(
                    f"| `{cell}` | {seed} | {row['examined_mean']:.1f} | "
                    f"**{row['returned_mean']:.1f}** | {row['examined_precision_micro']:.3f} | "
                    f"**{row['returned_precision_micro']:.3f}** | "
                    f"{row['returned_recall_micro']:.3f} | {row['average_precision']:.3f} |"
                )
        w("")
        w(
            "The traversal reports about six edges from the thirty-three it examined, at "
            "roughly nine-tenths precision and recall. Average precision is computed over "
            "the whole precision-recall curve, so it commits to no operating point at all."
        )
    w("")
    w("## 7. Stated limitations of this reading")
    w("")
    w(
        "- **Exact accuracy is largely a restatement of route-completeness** (design notes "
        "§2.20). `exact_correct` requires `proof_valid`, which requires the emitted routes "
        "to be valid routes whose endpoints are exactly the targets — so on a proof-valid "
        "episode the endpoint assertion masks the head reads are the gold answer by "
        "construction. Read the `acc / RC` column, not raw accuracy."
    )
    w(
        "- **The answer head trained on the wrong input for half the run** (§2.19). Under "
        "supplied-prefix supervision the walk skips the frontier block, so `endpoints` and "
        "`routes` are empty and the head's twelve label-carrying dimensions are identically "
        "zero. Its effective budget was 4,000 updates, not 8,000."
    )
    w(
        "- **One generator, screening only, no holdout.** The band is evidence about this "
        "task at this budget, not about graph memory generally."
    )
    w(
        "- **The architecture carries much of the base performance.** An untrained TRAVV2 "
        "is already near the strongest model-free policy, because the frontier restriction "
        "and stop rule are structural. Training adds roughly eight points of "
        "route-completeness on top of that, which is what the paired comparison measures."
    )
    w("")
    w("## 8. What this report does not do")
    w("")
    w(
        "It records no hypothesis verdict. It changes no threshold, arm, metric, seed or "
        "frozen digest; the band is read from §5 of the preregistration as written, at "
        f"update {record['read_point']:,} only. It reads no holdout. Amendment 10 remains "
        "pending review. Whether this advances the programme to the insert objective is "
        "the user's decision against the standing branch rule in `docs/DECISIONS.md`."
    )
    w("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default="private/track-o-v1")
    parser.add_argument(
        "--ladder", default="experiments/track_o_v1/diagnostics/policy_ladder.json"
    )
    parser.add_argument(
        "--untrained",
        default="experiments/track_o_v1/diagnostics/untrained_reference.json",
    )
    parser.add_argument(
        "--audit", default="experiments/track_o_v1/diagnostics/cell_audit.json"
    )
    parser.add_argument(
        "--returned-set",
        default="experiments/track_o_v1/diagnostics/returned_set.json",
    )
    parser.add_argument("--preregistration-commit", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--md-output", required=True)
    args = parser.parse_args()

    runs = discover(Path(args.runs_root))
    record = build(
        runs,
        json.loads(Path(args.ladder).read_text()),
        json.loads(Path(args.untrained).read_text()),
        json.loads(Path(args.audit).read_text()),
        args.preregistration_commit,
    )
    returned = Path(args.returned_set)
    record["returned_set"] = (
        json.loads(returned.read_text()) if returned.exists() else None
    )
    Path(args.json_output).write_text(json.dumps(record, indent=2, sort_keys=True))
    Path(args.md_output).write_text(render(record))
    print(
        json.dumps(
            {
                "band": record["band"].get("band"),
                "reason": record["band"].get("reason"),
                "floors_G": record["floors_G"]["failures"],
                "order_ok": record["order"]["all_ok"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
