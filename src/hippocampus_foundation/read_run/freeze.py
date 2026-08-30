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


def create_code_freeze(*, p0_report: dict[str, Any], frozen_at: str) -> dict[str, Any]:
    contracts = validate_preregistration()
    if p0_report.get("record_kind") != "read_run_p0_report":
        raise IntegrityGateError("code freeze requires a READ-run P0 report")
    if not p0_report.get("screening_training_authorized"):
        raise IntegrityGateError("code freeze requires seven passed P0 gates")
    if p0_report.get("selected_main_budget") not in {None, 16, 32, 64, 128}:
        raise IntegrityGateError("code freeze has an invalid coverage-selected budget")
    inventory = _source_inventory()
    return {
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
    }


def validate_code_freeze(
    freeze: dict[str, Any], *, p0_report: dict[str, Any] | None = None
) -> None:
    contracts = validate_preregistration()
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
    }
    if set(freeze) != required or freeze["record_kind"] != "read_run_code_freeze":
        raise IntegrityGateError("code-freeze fields differ from the fixed contract")
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
    path: Path, *, p0_report_path: Path | None = None
) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise IntegrityGateError("code freeze must be an object")
    p0 = None
    if p0_report_path is not None:
        p0 = load_json(p0_report_path)
        if not isinstance(p0, dict):
            raise IntegrityGateError("P0 report must be an object")
    validate_code_freeze(value, p0_report=p0)
    return value
