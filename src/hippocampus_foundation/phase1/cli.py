"""Command line for Phase 1 validation and deterministic data preparation only."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hippocampus_foundation.licensing import load_verified_bundle
from hippocampus_foundation.phase0.canonical import (
    canonical_sha256,
    dump_pretty,
    load_json,
)
from hippocampus_foundation.phase0.errors import Phase0Error
from hippocampus_foundation.phase0.v2 import validate_v2 as validate_phase0_v2
from hippocampus_foundation.phase0.v3 import require_phase0_transform_gate_v3

from .contracts import (
    validate_artifact_manifest,
    validate_encoder_spec,
    validate_encoder_verification,
    validate_gate_report,
    validate_graph_record,
    validate_objective_example,
    validate_schema_lock_v1,
    validate_v1,
)
from .encoder import verify_encoder_assets
from .errors import Phase1Error, Phase1IntegrityError, Phase1ValidationError
from .gate import evaluate_phase1_gate, require_phase0_transform_gate
from .io import file_identity, iter_records, write_json_atomic, write_jsonl_atomic
from .neighbours import cap_neighbours, make_cap_manifest
from .objectives import make_objective_manifest, replay_objectives
from .sampling import DEFAULT_SAMPLE_SIZE, make_sample_manifest, select_nodes
from .v2 import (
    evaluate_phase1_gate_v2,
    validate_encoder_verification_v2,
    validate_schema_lock_v2,
)
from .v2 import (
    validate_v2 as validate_phase1_v2,
)


def _emit(value: Any) -> None:
    sys.stdout.write(dump_pretty(value))


def _assignment(value: str, option: str) -> tuple[str, str]:
    left, separator, right = value.partition("=")
    if not separator or not left or not right:
        raise Phase1ValidationError(f"{option} must be LEFT=RIGHT")
    return left, right


def _refuse_outputs(*paths: Path) -> None:
    collisions = [str(path) for path in paths if path.exists() or path.is_symlink()]
    if collisions:
        raise Phase1IntegrityError(f"refusing to overwrite outputs: {collisions}")


def _load_object(path: str | Path) -> dict[str, Any]:
    value = load_json(Path(path))
    if not isinstance(value, dict):
        raise Phase1ValidationError(f"expected a JSON object: {path}")
    return value


def _require_phase0_and_quarantine(
    phase0_path: str, quarantine_path: str
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    phase0_gate = _load_object(phase0_path)
    if phase0_gate.get("gate_id") == "phase0-public-foundation-v3":
        phase0_sha256 = require_phase0_transform_gate_v3(phase0_gate)
    else:
        phase0_sha256 = require_phase0_transform_gate(phase0_gate)
    quarantine = _load_object(quarantine_path)
    validate_phase0_v2(quarantine, "evaluation-evidence.schema.json")
    if quarantine.get("record_kind") != "quarantine_index":
        raise Phase1ValidationError("expected a Phase 0 v2 quarantine index")
    quarantine_sha256 = canonical_sha256(quarantine)
    if f"quarantine_index:{quarantine_sha256}" not in phase0_gate["evidence"]:
        raise Phase1ValidationError(
            "quarantine index is not the one admitted by the Phase 0 gate"
        )
    return phase0_gate, phase0_sha256, quarantine, quarantine_sha256


def _contracts_validate(args: argparse.Namespace) -> int:
    digests = validate_schema_lock_v1(
        Path(args.schema_root) if args.schema_root else None
    )
    checked: list[str] = []
    for value in args.instance:
        path_text, schema_name = _assignment(value, "--instance")
        instance = _load_object(path_text)
        validate_v1(instance, schema_name)
        if schema_name == "graph.schema.json":
            validate_graph_record(instance)
        elif schema_name == "objective-example.schema.json":
            validate_objective_example(instance)
        elif schema_name == "encoder.schema.json":
            if instance.get("record_kind") == "encoder_spec":
                validate_encoder_spec(instance)
            else:
                validate_encoder_verification(instance)
        elif schema_name == "artifact.schema.json":
            validate_artifact_manifest(instance)
        elif schema_name == "gate.schema.json":
            validate_gate_report(instance)
        checked.append(path_text)
    _emit({"ok": True, "schema_digests": digests, "instances": sorted(checked)})
    return 0


def _contracts_validate_v2(args: argparse.Namespace) -> int:
    digests = validate_schema_lock_v2(
        Path(args.schema_root) if args.schema_root else None
    )
    checked: list[str] = []
    for path_text in args.instance:
        instance = _load_object(path_text)
        if instance.get("record_kind") == "encoder_verification":
            validate_encoder_verification_v2(instance)
        else:
            validate_phase1_v2(instance, "gate.schema.json")
        checked.append(path_text)
    _emit({"ok": True, "schema_digests": digests, "instances": sorted(checked)})
    return 0


def _graph_validate(args: argparse.Namespace) -> int:
    count = 0
    kinds: dict[str, int] = {}
    for record in iter_records(Path(args.input)):
        validate_graph_record(record)
        count += 1
        kind = record["record_kind"]
        kinds[kind] = kinds.get(kind, 0) + 1
    _emit({"ok": True, "records": count, "record_kinds": dict(sorted(kinds.items()))})
    return 0


def _sample_build(args: argparse.Namespace) -> int:
    _, phase0_sha256, _, quarantine_sha256 = _require_phase0_and_quarantine(
        args.phase0_gate, args.quarantine
    )
    output = Path(args.output)
    manifest_path = Path(args.manifest)
    _refuse_outputs(output, manifest_path)
    candidates_path = Path(args.candidates)
    input_before = file_identity(candidates_path)
    selected, stats = select_nodes(iter_records(candidates_path), size=args.size)
    input_after = file_identity(candidates_path)
    if input_before != input_after:
        raise Phase1IntegrityError("sample candidates changed during selection")
    written = write_jsonl_atomic(output, selected)
    if written != stats["selected_size"]:
        raise Phase1IntegrityError("sample output count mismatch")
    selected_identity = file_identity(output)
    manifest = make_sample_manifest(
        phase0_gate_sha256=phase0_sha256,
        candidate_sha256=input_before["sha256"],
        selected_sha256=selected_identity["sha256"],
        quarantine_index_sha256=quarantine_sha256,
        requested_size=args.size,
        stats=stats,
    )
    write_json_atomic(manifest_path, manifest)
    _emit(manifest)
    return 0


def _graph_cap(args: argparse.Namespace) -> int:
    _, phase0_sha256, _, quarantine_sha256 = _require_phase0_and_quarantine(
        args.phase0_gate, args.quarantine
    )
    output = Path(args.output)
    overflow_path = Path(args.overflow)
    manifest_path = Path(args.manifest)
    _refuse_outputs(output, overflow_path, manifest_path)
    input_path = Path(args.input)
    input_before = file_identity(input_path)
    selected, overflow, stats = cap_neighbours(iter_records(input_path))
    input_after = file_identity(input_path)
    if input_before != input_after:
        raise Phase1IntegrityError("neighbour candidates changed during selection")
    write_jsonl_atomic(output, selected)
    write_jsonl_atomic(overflow_path, overflow)
    selected_identity = file_identity(output)
    overflow_identity = file_identity(overflow_path)
    manifest = make_cap_manifest(
        phase0_gate_sha256=phase0_sha256,
        input_sha256=input_before["sha256"],
        selected_sha256=selected_identity["sha256"],
        overflow_sha256=overflow_identity["sha256"],
        quarantine_index_sha256=quarantine_sha256,
        stats=stats,
    )
    write_json_atomic(manifest_path, manifest)
    _emit(manifest)
    return 0


def _encoder_verify(args: argparse.Namespace) -> int:
    spec = _load_object(args.spec)
    output = Path(args.output)
    _refuse_outputs(output)
    verification = verify_encoder_assets(
        spec=spec,
        snapshot=Path(args.snapshot),
        bakeoff_report=Path(args.bakeoff_report),
        snapshot_id=args.snapshot_id,
    )
    write_json_atomic(output, verification)
    _emit(verification)
    return 0 if verification["verified"] else 2


def _objectives_validate(args: argparse.Namespace) -> int:
    count = 0
    for record in iter_records(Path(args.input)):
        validate_objective_example(record)
        count += 1
    _emit({"ok": True, "examples": count})
    return 0


def _objectives_replay(args: argparse.Namespace) -> int:
    _, phase0_sha256, _, quarantine_sha256 = _require_phase0_and_quarantine(
        args.phase0_gate, args.quarantine
    )
    output = Path(args.output)
    manifest_path = Path(args.manifest)
    _refuse_outputs(output, manifest_path)
    input_path = Path(args.input)
    input_before = file_identity(input_path)
    examples, stats = replay_objectives(iter_records(input_path))
    input_after = file_identity(input_path)
    if input_before != input_after:
        raise Phase1IntegrityError("objective input changed during replay assembly")
    if stats["quarantine_index_sha256"] != quarantine_sha256:
        raise Phase1ValidationError(
            "objective examples bind a different quarantine index"
        )
    write_jsonl_atomic(output, examples)
    output_identity = file_identity(output)
    manifest = make_objective_manifest(
        phase0_gate_sha256=phase0_sha256,
        input_sha256=input_before["sha256"],
        output_sha256=output_identity["sha256"],
        stats=stats,
    )
    write_json_atomic(manifest_path, manifest)
    _emit(manifest)
    return 0


def _gate(args: argparse.Namespace) -> int:
    spec = _load_object(args.encoder_spec)
    report = evaluate_phase1_gate(
        evaluated_at=args.evaluated_at,
        phase0_gate=_load_object(args.phase0_gate) if args.phase0_gate else None,
        encoder_spec=spec,
        encoder_verification=(
            _load_object(args.encoder_verification)
            if args.encoder_verification
            else None
        ),
        sample_manifest=(
            _load_object(args.sample_manifest) if args.sample_manifest else None
        ),
        graph_manifest=(
            _load_object(args.graph_manifest) if args.graph_manifest else None
        ),
        objective_manifest=(
            _load_object(args.objective_manifest) if args.objective_manifest else None
        ),
    )
    if args.output:
        write_json_atomic(Path(args.output), report)
    _emit(report)
    return 0 if report["phase1_data_ready"] else 2


def _gate_v2(args: argparse.Namespace) -> int:
    assessment = None
    verified_bundle = None
    if args.encoder_licence_assessment:
        assessment_text, bundle_text = _assignment(
            args.encoder_licence_assessment, "--encoder-licence-assessment"
        )
        assessment = _load_object(assessment_text)
        verified_bundle = load_verified_bundle(Path(bundle_text))
    report = evaluate_phase1_gate_v2(
        evaluated_at=args.evaluated_at,
        phase0_gate=_load_object(args.phase0_gate) if args.phase0_gate else None,
        encoder_spec=_load_object(args.encoder_spec),
        encoder_verification=(
            _load_object(args.encoder_verification)
            if args.encoder_verification
            else None
        ),
        encoder_licence_assessment=assessment,
        encoder_verified_bundle=verified_bundle,
        sample_manifest=(
            _load_object(args.sample_manifest) if args.sample_manifest else None
        ),
        graph_manifest=(
            _load_object(args.graph_manifest) if args.graph_manifest else None
        ),
        objective_manifest=(
            _load_object(args.objective_manifest) if args.objective_manifest else None
        ),
    )
    if args.output:
        write_json_atomic(Path(args.output), report)
    _emit(report)
    return 0 if report["phase1_data_ready"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hf-phase1")
    commands = parser.add_subparsers(dest="command", required=True)

    contracts = commands.add_parser("contracts")
    contract_commands = contracts.add_subparsers(
        dest="contracts_command", required=True
    )
    validate = contract_commands.add_parser("validate")
    validate.add_argument("--schema-root")
    validate.add_argument(
        "--instance", action="append", default=[], metavar="PATH=SCHEMA"
    )
    validate.set_defaults(handler=_contracts_validate)
    validate_v2 = contract_commands.add_parser("validate-v2")
    validate_v2.add_argument("--schema-root")
    validate_v2.add_argument("--instance", action="append", default=[], metavar="PATH")
    validate_v2.set_defaults(handler=_contracts_validate_v2)

    graph = commands.add_parser("graph")
    graph_commands = graph.add_subparsers(dest="graph_command", required=True)
    graph_validate = graph_commands.add_parser("validate")
    graph_validate.add_argument("--input", required=True)
    graph_validate.set_defaults(handler=_graph_validate)
    cap = graph_commands.add_parser("cap-neighbours")
    cap.add_argument("--phase0-gate", required=True)
    cap.add_argument("--quarantine", required=True)
    cap.add_argument("--input", required=True)
    cap.add_argument("--output", required=True)
    cap.add_argument("--overflow", required=True)
    cap.add_argument("--manifest", required=True)
    cap.set_defaults(handler=_graph_cap)

    sample = commands.add_parser("sample")
    sample_commands = sample.add_subparsers(dest="sample_command", required=True)
    sample_build = sample_commands.add_parser("build")
    sample_build.add_argument("--phase0-gate", required=True)
    sample_build.add_argument("--quarantine", required=True)
    sample_build.add_argument("--candidates", required=True)
    sample_build.add_argument("--output", required=True)
    sample_build.add_argument("--manifest", required=True)
    sample_build.add_argument("--size", type=int, default=DEFAULT_SAMPLE_SIZE)
    sample_build.set_defaults(handler=_sample_build)

    encoder = commands.add_parser("encoder")
    encoder_commands = encoder.add_subparsers(dest="encoder_command", required=True)
    encoder_verify = encoder_commands.add_parser("verify")
    encoder_verify.add_argument("--spec", required=True)
    encoder_verify.add_argument("--snapshot", required=True)
    encoder_verify.add_argument("--bakeoff-report", required=True)
    encoder_verify.add_argument("--snapshot-id")
    encoder_verify.add_argument("--output", required=True)
    encoder_verify.set_defaults(handler=_encoder_verify)

    objectives = commands.add_parser("objectives")
    objective_commands = objectives.add_subparsers(
        dest="objectives_command", required=True
    )
    objective_validate = objective_commands.add_parser("validate")
    objective_validate.add_argument("--input", required=True)
    objective_validate.set_defaults(handler=_objectives_validate)
    replay = objective_commands.add_parser("replay")
    replay.add_argument("--phase0-gate", required=True)
    replay.add_argument("--quarantine", required=True)
    replay.add_argument("--input", required=True)
    replay.add_argument("--output", required=True)
    replay.add_argument("--manifest", required=True)
    replay.set_defaults(handler=_objectives_replay)

    gate = commands.add_parser("gate")
    gate.add_argument("--phase0-gate")
    gate.add_argument("--encoder-spec", required=True)
    gate.add_argument("--encoder-verification")
    gate.add_argument("--sample-manifest")
    gate.add_argument("--graph-manifest")
    gate.add_argument("--objective-manifest")
    gate.add_argument("--evaluated-at", required=True)
    gate.add_argument("--output")
    gate.set_defaults(handler=_gate)
    gate_v2 = commands.add_parser("gate-v2")
    gate_v2.add_argument("--phase0-gate")
    gate_v2.add_argument("--encoder-spec", required=True)
    gate_v2.add_argument("--encoder-verification")
    gate_v2.add_argument("--encoder-licence-assessment", metavar="ASSESSMENT=BUNDLE")
    gate_v2.add_argument("--sample-manifest")
    gate_v2.add_argument("--graph-manifest")
    gate_v2.add_argument("--objective-manifest")
    gate_v2.add_argument("--evaluated-at", required=True)
    gate_v2.add_argument("--output")
    gate_v2.set_defaults(handler=_gate_v2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (Phase1Error, Phase0Error) as exc:
        sys.stderr.write(f"hf-phase1: {exc}\n")
        return 2
