"""Code/configuration freeze evidence for one-time holdout generation."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import canonical_sha256, load_json

from .contracts import validate_preregistration
from .errors import IntegrityGateError


def _file_sha256(path: Path) -> str:
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise IntegrityGateError("cannot read a code-freeze input") from exc
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _source_inventory() -> list[dict[str, str]]:
    package = Path(__file__).resolve().parent
    files = sorted(package.glob("*.py"))
    if not files:
        raise IntegrityGateError("READ-run source inventory is empty")
    return [
        {"path": f"read_run/{path.name}", "sha256": _file_sha256(path)}
        for path in files
    ]


def _repository_commit() -> str:
    package = Path(__file__).resolve()
    repository = package.parents[3]
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40:
        raise IntegrityGateError("code freeze requires a committed repository state")
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "src/hippocampus_foundation/read_run",
            "experiments/read_run_v1",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=repository,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if status.returncode != 0 or status.stdout.strip():
        raise IntegrityGateError("READ-run code/config must be committed before freeze")
    return value


# The order in which the batched TRAV path was adopted is what makes it the
# reference implementation rather than an arbitrary swap, so the sequence is
# recorded in the freeze itself rather than only in prose.
IMPLEMENTATION_PROVENANCE = {
    "trav_batched_forward": {
        "specification": "EqualCapacityReadModel._forward_trav_one",
        "selected_on": "wall_clock_only",
        "gated_on": "identical_traversal_decisions_against_the_specification",
        "selected_before_any_accuracy_existed": True,
        "numeric_difference": "float32_reassociation_only",
        "arms_frozen_before_holdout_opened": True,
    }
}

# A failure here means the batched implementation has drifted from the serial
# specification it was gated against. That invalidates E1 results themselves,
# not merely continuous integration: every accuracy number under this freeze was
# produced by the batched path on the strength of that equivalence.
INVALIDATING_TESTS = [
    "tests/test_read_run.py::test_batched_trav_matches_the_serial_traversal",
]


def create_code_freeze(
    *, p0_report: dict[str, Any], frozen_at: str, run_version: int = 1
) -> dict[str, Any]:
    contracts = validate_preregistration(run_version=run_version)
    if p0_report.get("record_kind") != "read_run_p0_report":
        raise IntegrityGateError("code freeze requires a READ-run P0 report")
    if not p0_report.get("screening_training_authorized"):
        raise IntegrityGateError("code freeze requires seven passed P0 gates")
    if p0_report.get("selected_main_budget") not in {None, 16, 32, 64, 128}:
        raise IntegrityGateError("code freeze has an invalid coverage-selected budget")
    inventory = _source_inventory()
    versioned: dict[str, Any] = {}
    if run_version != 1:
        # Presence-dispatched: a v1 freeze keeps the exact field set it always
        # had, and a later run version adds its own bindings rather than
        # widening one universal set. See `validate_code_freeze`.
        versioned = {
            "run_version": run_version,
            "heldout_seed_record_sha256": contracts["heldout_seed_record_sha256"],
        }
    return {
        **versioned,
        "schema_version": "1.0.0",
        "record_kind": "read_run_code_freeze",
        "frozen_at": frozen_at,
        "git_commit": _repository_commit(),
        "source_inventory": inventory,
        "source_inventory_sha256": canonical_sha256(inventory),
        "preregistration_json_sha256": contracts["preregistration_json_sha256"],
        "preregistration_markdown_sha256": contracts["preregistration_markdown_sha256"],
        "training_config_sha256": contracts["training_config_sha256"],
        "p0_report_sha256": canonical_sha256(p0_report),
        "selected_main_budget": p0_report["selected_main_budget"],
        "holdout_opened": False,
        "implementation_provenance": IMPLEMENTATION_PROVENANCE,
        "invalidating_tests": INVALIDATING_TESTS,
    }


def validate_code_freeze(
    freeze: dict[str, Any],
    *,
    p0_report: dict[str, Any] | None = None,
    run_version: int = 1,
) -> None:
    contracts = validate_preregistration(run_version=run_version)
    # Two exact sets, dispatched on whether the record carries `run_version`, so
    # that freezes written before this change stay readable. Both branches are
    # exact matches and the v2 set is a strict superset of the v1 set, so a
    # v1-shaped freeze smuggling v2 fields fails the v1 match and a v2 freeze
    # missing its seed binding fails the v2 match. There is no fallback path.
    required = {
        "schema_version",
        "record_kind",
        "frozen_at",
        "git_commit",
        "source_inventory",
        "source_inventory_sha256",
        "preregistration_json_sha256",
        "preregistration_markdown_sha256",
        "training_config_sha256",
        "p0_report_sha256",
        "selected_main_budget",
        "holdout_opened",
        "implementation_provenance",
        "invalidating_tests",
    }
    if "run_version" in freeze:
        required = required | {"run_version", "heldout_seed_record_sha256"}
    if set(freeze) != required or freeze["record_kind"] != "read_run_code_freeze":
        raise IntegrityGateError("code-freeze fields differ from the fixed contract")
    if freeze.get("run_version", 1) != run_version:
        raise IntegrityGateError("code freeze was written for another run version")
    if run_version != 1 and (
        freeze["heldout_seed_record_sha256"] != contracts["heldout_seed_record_sha256"]
    ):
        raise IntegrityGateError("code-freeze binding changed: heldout seed record")
    inventory = _source_inventory()
    if freeze["source_inventory"] != inventory or freeze[
        "source_inventory_sha256"
    ] != canonical_sha256(inventory):
        raise IntegrityGateError("READ-run source changed after code freeze")
    for field in (
        "preregistration_json_sha256",
        "preregistration_markdown_sha256",
        "training_config_sha256",
    ):
        if freeze[field] != contracts[field]:
            raise IntegrityGateError(f"code-freeze binding changed: {field}")
    if freeze["holdout_opened"] is not False:
        raise IntegrityGateError("code-freeze input already records a holdout opening")
    if p0_report is not None:
        if canonical_sha256(p0_report) != freeze["p0_report_sha256"]:
            raise IntegrityGateError("code freeze is bound to another P0 report")


def load_and_validate_code_freeze(
    path: Path, *, p0_report_path: Path | None = None, run_version: int = 1
) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise IntegrityGateError("code freeze must be an object")
    p0 = None
    if p0_report_path is not None:
        p0 = load_json(p0_report_path)
        if not isinstance(p0, dict):
            raise IntegrityGateError("P0 report must be an object")
    validate_code_freeze(value, p0_report=p0, run_version=run_version)
    return value
