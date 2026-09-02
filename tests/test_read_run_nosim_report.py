"""The Track N band reader is the preregistration's §5 table, executed.

`scripts/read_run_nosim_report.py` reads the band from the three TRAV-nosim
seeds' route-completeness at 8,000. These tests pin that reader to the table
as written — exhaustiveness and mutual exclusion of A–F over the three seeds'
levels, H's precedence, the count/fraction threshold agreement §4 relies on —
on synthetic read points, with no run output and no torch. The reference
numbers come from the committed `model_input_audit.json`, so the thresholds
under test are the ones the report will use.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (1729, 2718, 3141)


def load_report() -> ModuleType:
    path = ROOT / "scripts" / "read_run_nosim_report.py"
    specification = importlib.util.spec_from_file_location(
        "read_run_nosim_report", path
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report() -> ModuleType:
    return load_report()


@pytest.fixture(scope="module")
def thresholds(report: ModuleType) -> dict:
    audit = json.loads(
        (
            ROOT / "experiments/read_run_v1/diagnostics/model_input_audit.json"
        ).read_text()
    )
    ceiling = json.loads(
        (ROOT / "experiments/read_run_v1/diagnostics/ceiling_sweep.json").read_text()
    )
    return report.thresholds(report.references(audit, ceiling))


def _run(report: ModuleType, seed: int, rc128: int, rc32: int, n: int) -> dict:
    at = {
        str(b): (
            rc128
            if b == report.PRIMARY_BUDGET
            else rc32
            if b == report.PRECISION_BUDGET
            else 0
        )
        for b in report.PREFIX_BUDGETS
    }
    return {
        "name": f"probe-TRAV-nosim-s{seed}",
        "arm": "TRAV",
        "model_seed": seed,
        "read_points": {
            str(report.PRIMARY_READ_POINT): {
                "n": n,
                "rc128": rc128 / n,
                "rc32": rc32 / n,
                "route_complete_at": at,
                "route_complete_wilson_lower_bound_at": {
                    b: report.wilson_lower_bound(c, n) for b, c in at.items()
                },
            }
        },
    }


def test_thresholds_are_the_preregistered_counts(thresholds: dict) -> None:
    # Preregistration §4: n = 1124, pool 988, null band 966–1010, oracle ≥ 1113,
    # walker RC@32 1112 − 5 pp → ≥ 1056. None of them falls on an attainable tie.
    assert thresholds["n"] == 1124
    assert thresholds["counts"] == {
        "oracle_at_least": 1113,
        "null_band": [966, 1010],
        "walker_precision_at_least": 1056,
    }
    assert thresholds["pool_rc128_fraction"] == pytest.approx(988 / 1124)
    assert thresholds["walker_rc32_fraction"] == pytest.approx(1112 / 1124)


def test_count_and_fraction_levels_agree_at_every_count(
    report: ModuleType, thresholds: dict
) -> None:
    n = thresholds["n"]
    for count in range(n + 1):
        assert report._level(count / n, thresholds) == report._level_by_count(
            count, thresholds
        ), count
    assert report._level(1113 / n, thresholds) == "oracle"
    assert report._level(1112 / n, thresholds) == "above_null"
    assert report._level(1011 / n, thresholds) == "above_null"
    assert report._level(1010 / n, thresholds) == "null"
    assert report._level(966 / n, thresholds) == "null"
    assert report._level(965 / n, thresholds) == "below_null"


# One representative RC@128 count per level, and RC@32 counts either side of
# the walker-precision line.
LEVEL_COUNTS = {"oracle": 1120, "above_null": 1050, "null": 990, "below_null": 900}
PRECISE, IMPRECISE = 1100, 1000


def _expected_letter(levels: tuple[str, ...], precise: tuple[bool, ...]) -> str:
    """§5 as written, independently of the reader's code path."""

    if all(lv == "oracle" for lv in levels):
        return "A" if all(precise) else "B"
    if all(lv in ("oracle", "above_null") for lv in levels):
        return "C"
    if all(lv == "null" for lv in levels):
        return "D"
    if any(lv == "below_null" for lv in levels) and not any(
        lv in ("oracle", "above_null") for lv in levels
    ):
        return "E"
    return "F"


@pytest.mark.parametrize(
    "levels", list(itertools.product(LEVEL_COUNTS, repeat=len(SEEDS)))
)
@pytest.mark.parametrize("precise", [(True, True, True), (True, False, True)])
def test_band_is_exhaustive_and_matches_the_table(
    report: ModuleType,
    thresholds: dict,
    levels: tuple[str, ...],
    precise: tuple[bool, ...],
) -> None:
    n = thresholds["n"]
    runs = [
        _run(report, seed, LEVEL_COUNTS[lv], PRECISE if p else IMPRECISE, n)
        for seed, lv, p in zip(SEEDS, levels, precise, strict=True)
    ]
    band = report.read_band(runs, thresholds, [])
    assert band["band"] == _expected_letter(levels, precise)
    assert band["band"] in "ABCDEF"
    assert band["levels"] == list(levels)
    assert not band["voided_by_harness_defect"]
    assert set(band["per_seed"]) == {str(s) for s in SEEDS}


def test_harness_defect_takes_precedence_but_keeps_the_letter(
    report: ModuleType, thresholds: dict
) -> None:
    n = thresholds["n"]
    runs = [_run(report, seed, 1120, PRECISE, n) for seed in SEEDS]
    band = report.read_band(runs, thresholds, ["identity variant differs"])
    assert band["band"] == "H"
    assert band["letter_before_precedence"] == "A"
    assert band["voided_by_harness_defect"]


def test_a_missing_seed_or_read_point_yields_no_band(
    report: ModuleType, thresholds: dict
) -> None:
    n = thresholds["n"]
    runs = [_run(report, seed, 1120, PRECISE, n) for seed in SEEDS[:2]]
    assert report.read_band(runs, thresholds, [])["band"] is None
    runs.append(_run(report, SEEDS[2], 1120, PRECISE, n))
    runs[2]["read_points"][str(report.PRIMARY_READ_POINT)] = None
    band = report.read_band(runs, thresholds, [])
    assert band["band"] is None
    assert band["missing"] == ["probe-TRAV-nosim-s3141"]


def test_plateau_reads_the_named_quantity(report: ModuleType) -> None:
    def point(update: int, exact: float, rc: float) -> dict:
        return {
            "update": update,
            "exact_set_accuracy": exact,
            "rc128": rc,
            "rc32": rc,
            "loss_window": 1.0,
            "floors": {"all": True},
        }

    # Exact accuracy flat from the start; RC climbs 5 pp per checkpoint until
    # 5000 and is flat after, so its first qualifying checkpoint (two flat
    # steps behind it) is 7000. Amendment 09's rule read on each quantity.
    curve = [
        point(u, 0.50, min(0.5 + 0.05 * i, 0.70))
        for i, u in enumerate(range(1000, 10000, 1000))
    ]
    exact = report._plateau(curve, "exact_set_accuracy")
    rc = report._plateau(curve, "rc128")
    assert exact["plateaued"] and exact["plateau_point"] == 3000
    assert rc["plateaued"] and rc["plateau_point"] == 7000
    assert rc["final_unbroken_run_length"] == 3
    # A curve that keeps moving never plateaus.
    rising = [
        point(u, 0.05 * i, 0.05 * i) for i, u in enumerate(range(1000, 10000, 1000))
    ]
    assert not report._plateau(rising, "rc32")["plateaued"]
