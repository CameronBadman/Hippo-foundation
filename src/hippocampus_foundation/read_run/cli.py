"""Command line interface for the preregistered READ run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import (
    canonical_sha256,
    dump_pretty,
    load_json,
)
from hippocampus_foundation.phase0.errors import Phase0Error

from .contracts import validate_preregistration
from .errors import ReadRunError
from .evaluation import apply_preregistered_decision
from .freeze import create_code_freeze, load_and_validate_code_freeze
from .generator import GAMMA_BUCKETS, MODEL_SEEDS
from .io import write_generated_split
from .p0 import evaluate_p0
from .reports import main_report, screening_report
from .reproducibility import double_execution_gate
from .seed import read_master_seed, seed_commitment
from .training import evaluate_checkpoint, train_arm


def _emit(value: Any) -> None:
    sys.stdout.write(dump_pretty(value))


def _json_object(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ReadRunError(f"expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise ReadRunError(f"refusing to overwrite output: {path}") from exc
    try:
        encoded = dump_pretty(value).encode()
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise ReadRunError("short write while creating JSON evidence")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_gamma_paths(values: list[str], option: str) -> dict[float, Path]:
    result: dict[float, Path] = {}
    for value in values:
        parts = value.split("=", 1)
        if len(parts) != 2:
            raise ReadRunError(f"{option} requires GAMMA=PATH")
        try:
            gamma = float(parts[0])
        except ValueError as exc:
            raise ReadRunError(f"invalid gamma in {option}") from exc
        if gamma not in GAMMA_BUCKETS or gamma in result:
            raise ReadRunError(f"{option} gamma is invalid or duplicated")
        result[gamma] = Path(parts[1])
    return result


def _official_count(split: str) -> int:
    return {"train": 150_000, "screen": 2_000, "holdout": 15_000}[split]


def _require_timestamp(value: str | None, label: str) -> str:
    if not value:
        raise ReadRunError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReadRunError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReadRunError(f"{label} must include a timezone")
    return value


def _generate(args: argparse.Namespace) -> int:
    contracts = validate_preregistration()
    seed = read_master_seed(Path(args.seed_file))
    commitment = seed_commitment(seed)
    expected_commitment = contracts["preregistration"]["heldout_seed_sha256"]
    if not args.test_mode and commitment != expected_commitment:
        raise ReadRunError("seed differs from the frozen preregistration commitment")
    if args.count % 20:
        raise ReadRunError("episode count must be divisible by 20 for exact strata")
    if not args.test_mode:
        if args.split not in {"train", "screen", "holdout"}:
            raise ReadRunError("official generation requires train, screen, or holdout")
        if args.count != _official_count(args.split):
            raise ReadRunError("episode count differs from the frozen split size")
    if args.split == "holdout" and not args.test_mode:
        if not args.code_freeze or not args.p0_report:
            raise ReadRunError(
                "holdout generation requires code-freeze and P0 evidence"
            )
        p0 = _json_object(Path(args.p0_report))
        freeze = load_and_validate_code_freeze(
            Path(args.code_freeze), p0_report_path=Path(args.p0_report)
        )
        if not p0.get("training_authorized") or freeze["selected_main_budget"] is None:
            raise ReadRunError("main-run authorization is blocked")
        _require_timestamp(args.opened_at, "--opened-at")
    public, private = write_generated_split(
        master_seed=seed,
        split=args.split,
        count=args.count,
        gamma=args.gamma,
        destination=Path(args.output),
    )
    if args.split == "holdout" and not args.test_mode:
        opening = {
            "schema_version": "1.0.0",
            "record_kind": "read_holdout_opening_receipt",
            "opened_at": args.opened_at,
            "gamma": args.gamma,
            "code_freeze_sha256": canonical_sha256(freeze),
            "p0_report_sha256": canonical_sha256(p0),
            "private_manifest_sha256": canonical_sha256(private),
            "opened_once": True,
        }
        _write_json(Path(args.output) / "holdout-opening.json", opening)
    _emit(public)
    return 0


def _double_execute(args: argparse.Namespace) -> int:
    count = args.count
    if not args.test_mode and count != 2_000:
        raise ReadRunError(
            "official double execution requires 2,000 screening episodes"
        )
    if not args.test_mode:
        contracts = validate_preregistration()
        seed = read_master_seed(Path(args.seed_file))
        if seed_commitment(seed) != contracts["preregistration"]["heldout_seed_sha256"]:
            raise ReadRunError(
                "seed differs from the frozen preregistration commitment"
            )
    result = double_execution_gate(
        seed_path=Path(args.seed_file),
        split="screen",
        count=count,
        gamma=args.gamma,
        test_mode=args.test_mode,
    )
    if args.output:
        _write_json(Path(args.output), result)
    _emit(result)
    return 0


def _p0(args: argparse.Namespace) -> int:
    train = _parse_gamma_paths(args.train, "--train")
    screen = _parse_gamma_paths(args.screen, "--screen")
    doubles = [_json_object(Path(path)) for path in args.double_execution]
    report = evaluate_p0(
        train_roots=train,
        screen_roots=screen,
        double_execution_records=doubles,
        evaluated_at=_require_timestamp(args.evaluated_at, "--evaluated-at"),
        workers=args.workers,
        strict_counts=not args.test_mode,
    )
    _write_json(Path(args.output), report, mode=0o644)
    _emit(report)
    return 0 if report["screening_training_authorized"] else 2


def _freeze(args: argparse.Namespace) -> int:
    p0 = _json_object(Path(args.p0_report))
    result = create_code_freeze(
        p0_report=p0,
        frozen_at=_require_timestamp(args.frozen_at, "--frozen-at"),
        config_version=args.config_version,
    )
    _write_json(Path(args.output), result, mode=0o644)
    _emit(result)
    return 0


def _train(args: argparse.Namespace) -> int:
    receipt = train_arm(
        arm=args.arm,
        stage=args.stage,
        model_seed=args.model_seed,
        budget=args.budget,
        train_root=Path(args.train_root),
        p0_report_path=Path(args.p0_report),
        code_freeze_path=Path(args.code_freeze),
        output_root=Path(args.output),
        config_version=args.config_version,
    )
    _emit(receipt)
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        raise ReadRunError("refusing to overwrite an evaluation output")
    output.mkdir(parents=True)
    os.chmod(output, 0o700)
    summary, predictions = evaluate_checkpoint(
        checkpoint_path=Path(args.checkpoint),
        receipt_path=Path(args.training_receipt),
        dataset_root=Path(args.dataset_root),
        expected_split=args.split,
        code_freeze_path=(Path(args.code_freeze) if args.code_freeze else None),
        p0_report_path=(Path(args.p0_report) if args.p0_report else None),
        config_version=args.config_version,
    )
    _write_json(output / "summary.json", summary, mode=0o600)
    prediction_path = output / "predictions.jsonl"
    descriptor = os.open(prediction_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        for prediction in predictions:
            line = (
                json.dumps(prediction, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
            offset = 0
            while offset < len(line):
                offset += os.write(descriptor, line[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _emit(summary)
    return 0


def _decision(args: argparse.Namespace) -> int:
    results = [_json_object(Path(path)) for path in args.summary]
    decision = apply_preregistered_decision(results)
    result = {
        "schema_version": "1.0.0",
        "record_kind": "read_main_decision",
        **decision,
    }
    _write_json(Path(args.output), result, mode=0o644)
    _emit(result)
    return 0


def _screening_report(args: argparse.Namespace) -> int:
    result = screening_report(
        p0_report=_json_object(Path(args.p0_report)),
        receipts=[_json_object(Path(path)) for path in args.receipt],
        failures=[_json_object(Path(path)) for path in args.failure],
        summaries=[_json_object(Path(path)) for path in args.summary],
    )
    _write_json(Path(args.output), result, mode=0o644)
    _emit(result)
    return 0 if result["status"].startswith("complete") else 2


def _main_report(args: argparse.Namespace) -> int:
    p0 = _json_object(Path(args.p0_report))
    freeze = load_and_validate_code_freeze(
        Path(args.code_freeze), p0_report_path=Path(args.p0_report)
    )
    selected_budget = p0.get("selected_main_budget")
    if selected_budget is None or freeze["selected_main_budget"] != selected_budget:
        raise ReadRunError("main report lacks one frozen coverage-selected budget")
    result = main_report(
        selected_budget=selected_budget,
        receipts=[_json_object(Path(path)) for path in args.receipt],
        failures=[_json_object(Path(path)) for path in args.failure],
        summaries=[_json_object(Path(path)) for path in args.summary],
    )
    _write_json(Path(args.output), result, mode=0o644)
    _emit(result)
    return 0 if result["decision"] != "incomplete" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hf-read-run")
    commands = parser.add_subparsers(dest="command", required=True)

    contracts = commands.add_parser("contracts")
    contracts.set_defaults(handler=lambda _args: _emit(validate_preregistration()) or 0)

    generate = commands.add_parser("generate")
    generate.add_argument(
        "--split", required=True, choices=["train", "screen", "holdout", "test-fixture"]
    )
    generate.add_argument("--count", required=True, type=int)
    generate.add_argument("--gamma", required=True, type=float, choices=GAMMA_BUCKETS)
    generate.add_argument("--seed-file", required=True)
    generate.add_argument("--output", required=True)
    generate.add_argument("--code-freeze")
    generate.add_argument("--p0-report")
    generate.add_argument("--opened-at")
    generate.add_argument("--test-mode", action="store_true")
    generate.set_defaults(handler=_generate)

    double = commands.add_parser("double-execute")
    double.add_argument("--seed-file", required=True)
    double.add_argument("--gamma", required=True, type=float, choices=GAMMA_BUCKETS)
    double.add_argument("--count", default=2_000, type=int)
    double.add_argument("--output")
    double.add_argument("--test-mode", action="store_true")
    double.set_defaults(handler=_double_execute)

    p0 = commands.add_parser("p0")
    p0.add_argument("--train", action="append", required=True, metavar="GAMMA=PATH")
    p0.add_argument("--screen", action="append", required=True, metavar="GAMMA=PATH")
    p0.add_argument("--double-execution", action="append", required=True)
    p0.add_argument("--evaluated-at", required=True)
    p0.add_argument("--workers", type=int, default=1)
    p0.add_argument("--output", required=True)
    p0.add_argument("--test-mode", action="store_true")
    p0.set_defaults(handler=_p0)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--p0-report", required=True)
    freeze.add_argument("--frozen-at", required=True)
    freeze.add_argument("--output", required=True)
    freeze.add_argument("--config-version", default="v1", choices=["v1", "v2"])
    freeze.set_defaults(handler=_freeze)

    train = commands.add_parser("train")
    train.add_argument("--arm", required=True, choices=["TRAV", "DIRECT"])
    train.add_argument("--stage", required=True, choices=["screening", "main"])
    train.add_argument("--model-seed", required=True, type=int, choices=MODEL_SEEDS)
    train.add_argument("--budget", required=True, type=int, choices=[16, 32, 64, 128])
    train.add_argument("--train-root", required=True)
    train.add_argument("--p0-report", required=True)
    train.add_argument("--code-freeze", required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--config-version", default="v1", choices=["v1", "v2"])
    train.set_defaults(handler=_train)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--checkpoint", required=True)
    evaluate.add_argument("--training-receipt", required=True)
    evaluate.add_argument("--dataset-root", required=True)
    evaluate.add_argument("--split", required=True, choices=["screen", "holdout"])
    evaluate.add_argument("--code-freeze", required=True)
    evaluate.add_argument("--p0-report", required=True)
    evaluate.add_argument("--output", required=True)
    evaluate.add_argument("--config-version", default="v1", choices=["v1", "v2"])
    evaluate.set_defaults(handler=_evaluate)

    decision = commands.add_parser("decision")
    decision.add_argument("--summary", action="append", required=True)
    decision.add_argument("--output", required=True)
    decision.set_defaults(handler=_decision)

    screening = commands.add_parser("screening-report")
    screening.add_argument("--p0-report", required=True)
    screening.add_argument("--receipt", action="append", default=[])
    screening.add_argument("--failure", action="append", default=[])
    screening.add_argument("--summary", action="append", default=[])
    screening.add_argument("--output", required=True)
    screening.set_defaults(handler=_screening_report)

    main_report_command = commands.add_parser("main-report")
    main_report_command.add_argument("--p0-report", required=True)
    main_report_command.add_argument("--code-freeze", required=True)
    main_report_command.add_argument("--receipt", action="append", default=[])
    main_report_command.add_argument("--failure", action="append", default=[])
    main_report_command.add_argument("--summary", action="append", default=[])
    main_report_command.add_argument("--output", required=True)
    main_report_command.set_defaults(handler=_main_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ReadRunError, Phase0Error) as exc:
        sys.stderr.write(f"hf-read-run: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
