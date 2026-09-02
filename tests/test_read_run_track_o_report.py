"""The Track O band reader is §5 of its preregistration, executed.

These pin the reader to the table as written — over every combination of the
three seeds' improve/degrade classification — on synthetic read points, with no
run output and no torch. The comparison rules come from §4 and use no constant
beyond the Wilson bound, so the tests assert the rules rather than a threshold.
"""

from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_reader() -> ModuleType:
    path = ROOT / "scripts" / "read_run_track_o_report.py"
    specification = importlib.util.spec_from_file_location(
        "read_run_track_o_report", path
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reader() -> ModuleType:
    return load_reader()


# The untrained line these are compared against, taken from the committed
# reference: RC 0.85 with a Wilson lower bound of 0.83, precision 0.170.
UNTRAINED = {
    "route_complete_fraction": 0.850,
    "route_complete_wilson_lower_bound": 0.830,
    "precision_mean": 0.170,
    "examined_mean": 37.5,
}
STOP_AWARE = {"route_complete": 0.862, "precision": 0.173, "examined": 37.4}


def _trained(rc: float, rc_lb: float, precision: float) -> dict:
    return {
        "route_complete_fraction": rc,
        "route_complete_wilson_lower_bound": rc_lb,
        "precision_mean": precision,
        "examined_mean": 33.0,
    }


# One representative trained cell per (rc class, precision class).
IMPROVED = _trained(0.930, 0.915, 0.190)
NEUTRAL = _trained(0.850, 0.835, 0.170)
DEGRADED = _trained(0.800, 0.780, 0.150)
PRECISION_ONLY = _trained(0.850, 0.835, 0.190)


def test_comparison_rules_use_only_the_wilson_bound(reader: ModuleType) -> None:
    improved = reader.compare_to_untrained(IMPROVED, UNTRAINED)
    assert (
        improved["route_complete_improved"] and not improved["route_complete_degraded"]
    )
    assert improved["precision_improved"] and not improved["precision_degraded"]

    neutral = reader.compare_to_untrained(NEUTRAL, UNTRAINED)
    assert not neutral["route_complete_improved"]
    assert not neutral["route_complete_degraded"]
    assert not neutral["precision_improved"] and not neutral["precision_degraded"]

    degraded = reader.compare_to_untrained(DEGRADED, UNTRAINED)
    assert (
        degraded["route_complete_degraded"] and not degraded["route_complete_improved"]
    )
    assert degraded["precision_degraded"]

    # A trained point above the untrained estimate but whose Wilson bound does
    # not clear it counts as neither improved nor degraded — the guard's job.
    marginal = reader.compare_to_untrained(_trained(0.860, 0.845, 0.170), UNTRAINED)
    assert not marginal["route_complete_improved"]
    assert not marginal["route_complete_degraded"]


def test_frontier_condition_needs_both_axes(reader: ModuleType) -> None:
    assert reader.clears_frontier(IMPROVED, STOP_AWARE)
    # Coverage clears but precision does not.
    assert not reader.clears_frontier(_trained(0.930, 0.915, 0.150), STOP_AWARE)
    # Precision clears but the coverage Wilson bound does not.
    assert not reader.clears_frontier(_trained(0.870, 0.855, 0.190), STOP_AWARE)


def _band(reader: ModuleType, cells: tuple[dict, ...], defects=()) -> str:
    per_seed = {}
    for seed, trained in zip(reader.SEEDS, cells, strict=True):
        row = reader.compare_to_untrained(trained, UNTRAINED)
        row["clears_frontier"] = reader.clears_frontier(trained, STOP_AWARE)
        row["trained"] = trained
        row["untrained"] = UNTRAINED
        per_seed[str(seed)] = row
    return reader.read_band(per_seed, list(defects))["band"]


def test_band_a_needs_every_seed_to_clear_the_frontier(reader: ModuleType) -> None:
    assert _band(reader, (IMPROVED, IMPROVED, IMPROVED)) == "A"


def test_band_b_is_learned_but_short_of_the_frontier(reader: ModuleType) -> None:
    # RC improves in every seed, precision never degrades, but one seed's
    # precision sits below stop_aware's.
    short = _trained(0.930, 0.915, 0.171)
    assert not reader.clears_frontier(short, STOP_AWARE)
    assert _band(reader, (IMPROVED, IMPROVED, short)) == "B"


def test_band_c_is_one_axis(reader: ModuleType) -> None:
    assert _band(reader, (PRECISION_ONLY, PRECISION_ONLY, PRECISION_ONLY)) == "C"


def test_band_d_is_the_architecture_prior(reader: ModuleType) -> None:
    assert _band(reader, (NEUTRAL, NEUTRAL, NEUTRAL)) == "D"


def test_band_e_is_training_harm(reader: ModuleType) -> None:
    assert _band(reader, (DEGRADED, DEGRADED, DEGRADED)) == "E"
    assert _band(reader, (DEGRADED, NEUTRAL, NEUTRAL)) == "E"


def test_band_f_is_any_split(reader: ModuleType) -> None:
    assert _band(reader, (IMPROVED, DEGRADED, NEUTRAL)) == "F"


@pytest.mark.parametrize(
    "cells",
    list(itertools.product((IMPROVED, NEUTRAL, DEGRADED, PRECISION_ONLY), repeat=3)),
)
def test_every_combination_yields_exactly_one_band(
    reader: ModuleType, cells: tuple[dict, ...]
) -> None:
    band = _band(reader, cells)
    assert band in set("ABCDEF")


def test_harness_defect_takes_precedence_and_keeps_the_letter(
    reader: ModuleType,
) -> None:
    per_seed = {}
    for seed in reader.SEEDS:
        row = reader.compare_to_untrained(IMPROVED, UNTRAINED)
        row["clears_frontier"] = True
        row["trained"], row["untrained"] = IMPROVED, UNTRAINED
        per_seed[str(seed)] = row
    result = reader.read_band(per_seed, ["easy cell fell below 100%"])
    assert result["band"] == "H"
    assert result["letter_before_precedence"] == "A"
    assert result["voided_by_harness_defect"]


def test_a_missing_seed_yields_no_band(reader: ModuleType) -> None:
    row = reader.compare_to_untrained(IMPROVED, UNTRAINED)
    row["clears_frontier"] = True
    assert reader.read_band({"1729": row}, [])["band"] is None


def test_floors_match_amendment_04(reader: ModuleType) -> None:
    passing = {
        "wilson_lower_bound": 0.10,
        "exact_set_accuracy": 0.12,
        "distinct_classes": 12,
        "prediction_entropy_nats": 1.8,
    }
    assert reader._floors(passing)["all"]
    for broken in (
        {**passing, "wilson_lower_bound": 1 / 15},
        {**passing, "exact_set_accuracy": 0.05},
        {**passing, "distinct_classes": 7},
        {**passing, "prediction_entropy_nats": 0.9},
    ):
        assert not reader._floors(broken)["all"]


def test_plateau_reads_the_named_quantity(reader: ModuleType) -> None:
    flat = [
        {"update": u, "route_complete_fraction": 0.9, "precision_mean": 0.05 * i}
        for i, u in enumerate(range(1000, 9001, 1000))
    ]
    rc = reader._plateau(flat, "route_complete_fraction")
    precision = reader._plateau(flat, "precision_mean")
    assert rc["plateaued"] and rc["plateau_point"] == 3000
    assert not precision["plateaued"]
