"""Fresh-process reproducibility checks for generated READ data."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .errors import IntegrityGateError
from .io import DATASET_ARTIFACT_NAMES, dataset_artifact_sha256s


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def double_execution_gate(
    *,
    seed_path: Path,
    split: str,
    count: int,
    gamma: float,
    timeout_seconds: int = 7200,
    test_mode: bool = False,
) -> dict[str, Any]:
    """Regenerate under perturbed process state and compare every output byte."""

    seed_path = seed_path.resolve()
    with tempfile.TemporaryDirectory(prefix="read-run-double-execution-") as raw:
        root = Path(raw)
        working_a = root / "cwd-a"
        working_b = root / "cwd-b"
        working_a.mkdir()
        working_b.mkdir()
        output_a = root / "output-a"
        output_b = root / "output-b"
        base = [
            sys.executable,
            "-m",
            "hippocampus_foundation.read_run.cli",
            "generate",
            "--split",
            split,
            "--count",
            str(count),
            "--gamma",
            str(gamma),
            "--seed-file",
            str(seed_path),
        ]
        if test_mode:
            base.append("--test-mode")
        variants = (
            (
                working_a,
                output_a,
                {"LC_ALL": "C", "TZ": "UTC", "PYTHONHASHSEED": "1"},
            ),
            (
                working_b,
                output_b,
                {
                    "LC_ALL": "C.UTF-8",
                    "TZ": "Pacific/Kiritimati",
                    "PYTHONHASHSEED": "8675309",
                },
            ),
        )
        observations = []
        for working, output, changes in variants:
            environment = os.environ.copy()
            environment.update(changes)
            command = [*base, "--output", str(output)]
            try:
                completed = subprocess.run(
                    command,
                    cwd=working,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise IntegrityGateError(
                    "double execution exceeded its time bound"
                ) from exc
            if completed.returncode != 0:
                raise IntegrityGateError(
                    "double execution child failed without producing valid evidence"
                )
            observations.append(
                {
                    "stdout_sha256": _digest(completed.stdout),
                    "stderr_sha256": _digest(completed.stderr),
                }
            )
        digests: dict[str, str] = {}
        for name in DATASET_ARTIFACT_NAMES:
            first = (output_a / name).read_bytes()
            second = (output_b / name).read_bytes()
            if first != second:
                raise IntegrityGateError(
                    f"double execution output differs under perturbation: {name}"
                )
            digests[name] = _digest(first)
        if observations[0] != observations[1]:
            raise IntegrityGateError("double execution process output differs")
        return {
            "gate": "double_execution",
            "passed": True,
            "split": split,
            "gamma": gamma,
            "episode_count": count,
            "artifact_sha256s": digests,
            "process_observation": observations[0],
        }


def validate_double_execution_record(
    record: dict[str, Any],
    *,
    dataset_root: Path,
    gamma: float,
    expected_count: int,
) -> dict[str, Any]:
    """Bind a replay record to the exact split bytes consumed by P0."""

    required = {
        "gate",
        "passed",
        "split",
        "gamma",
        "episode_count",
        "artifact_sha256s",
        "process_observation",
    }
    if set(record) != required:
        raise IntegrityGateError("double execution record fields differ")
    if (
        record["gate"] != "double_execution"
        or record["passed"] is not True
        or record["split"] != "screen"
        or record["gamma"] != gamma
        or record["episode_count"] != expected_count
    ):
        raise IntegrityGateError("double execution record covers another split")
    observed = record["artifact_sha256s"]
    if observed != dataset_artifact_sha256s(dataset_root):
        raise IntegrityGateError(
            "double execution record is not bound to the consumed screening bytes"
        )
    process = record["process_observation"]
    if not isinstance(process, dict) or set(process) != {
        "stdout_sha256",
        "stderr_sha256",
    }:
        raise IntegrityGateError("double execution process observation is malformed")
    return record
