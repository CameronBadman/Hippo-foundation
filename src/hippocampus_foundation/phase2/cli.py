"""CLI for Phase 2 contracts and procedural candidate-data integrity."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hippocampus_foundation.phase0.canonical import dump_pretty
from hippocampus_foundation.phase0.errors import Phase0Error

from .contracts import (
    bind_registry_spec,
    validate_artifact,
    validate_generator_spec,
    validate_policy_example,
    validate_schema_lock_v1,
    validate_training_registry,
)
from .errors import Phase2Error, Phase2IntegrityError, Phase2ValidationError
from .io import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    file_identity,
    load_json_object,
    load_jsonl_objects,
    require_canonical_json,
    require_canonical_jsonl,
    write_artifact_set_exclusive,
)
from .procedural import audit_corpora, build_generation, verify_generation
from .process import (
    audit_corpora_v2,
    build_process_generation,
    replay_process_examples,
    verify_process_generation,
)
from .v2 import (
    bind_process_registry_spec,
    validate_process_artifact,
    validate_process_generator_spec,
    validate_process_state,
    validate_proposal,
    validate_schema_lock_v2,
    validate_training_registry_v2,
    validate_write_policy_example,
)


def _emit(value: Any) -> None:
    sys.stdout.write(dump_pretty(value))


def _load(path_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return load_json_object(Path(path_text))


def _require_unchanged(paths: list[tuple[Path, dict[str, Any]]]) -> None:
    for path, identity in paths:
        if file_identity(path) != identity:
            raise Phase2IntegrityError(f"input changed during operation: {path}")


def _contracts_validate(args: argparse.Namespace) -> int:
    schema_digests = validate_schema_lock_v1(
        Path(args.schema_root) if args.schema_root else None
    )
    registry: dict[str, Any] | None = None
    checked: list[str] = []
    if args.registry:
        registry, _identity = _load(args.registry)
        validate_training_registry(registry)
        checked.append(args.registry)

    specs: dict[str, dict[str, Any]] = {}
    for path_text in args.spec:
        spec, _identity = _load(path_text)
        validate_generator_spec(spec)
        if spec["source_id"] in specs:
            raise Phase2ValidationError(
                f"multiple specs supplied for source: {spec['source_id']}"
            )
        specs[spec["source_id"]] = spec
        if registry is not None:
            bind_registry_spec(registry, spec)
        checked.append(path_text)

    seen_example_ids: set[str] = set()
    seen_ordinals: set[tuple[str, int]] = set()
    seen_world_ids: set[str] = set()
    for path_text in args.examples:
        examples, _identity = load_jsonl_objects(Path(path_text))
        if not examples:
            raise Phase2ValidationError(f"example file is empty: {path_text}")
        for example in examples:
            source_id = example.get("source_id")
            if not isinstance(source_id, str):
                raise Phase2ValidationError("example source_id must be a string")
            spec = specs.get(source_id)
            if specs and spec is None:
                raise Phase2ValidationError(
                    f"example has no supplied generator spec: {source_id}"
                )
            validate_policy_example(example, spec=spec)
            example_id = example["example_id"]
            if example_id in seen_example_ids:
                raise Phase2ValidationError(f"duplicate example_id: {example_id}")
            seen_example_ids.add(example_id)
            ordinal_key = (example["source_id"], example["provenance"]["ordinal"])
            if ordinal_key in seen_ordinals:
                raise Phase2ValidationError(
                    f"duplicate source/ordinal pair: {ordinal_key}"
                )
            seen_ordinals.add(ordinal_key)
            world_id = example["dependencies"]["world_id"]
            if world_id in seen_world_ids:
                raise Phase2ValidationError(f"duplicate world_id: {world_id}")
            seen_world_ids.add(world_id)
        checked.append(path_text)

    for path_text in args.artifact:
        artifact, _identity = _load(path_text)
        validate_artifact(artifact)
        checked.append(path_text)

    _emit(
        {
            "ok": True,
            "schema_digests": schema_digests,
            "instances": sorted(checked),
            "training_authorized": False,
        }
    )
    return 0


def _contracts_validate_v2(args: argparse.Namespace) -> int:
    schema_digests = validate_schema_lock_v2(
        Path(args.schema_root) if args.schema_root else None
    )
    registry: dict[str, Any] | None = None
    checked: list[str] = []
    if args.registry:
        registry, _identity = _load(args.registry)
        validate_training_registry_v2(registry)
        checked.append(args.registry)
    specs: dict[str, dict[str, Any]] = {}
    for path_text in args.spec:
        spec, _identity = _load(path_text)
        validate_process_generator_spec(spec)
        if spec["source_id"] in specs:
            raise Phase2ValidationError(
                f"multiple v2 specs supplied for source: {spec['source_id']}"
            )
        specs[spec["source_id"]] = spec
        if registry is not None:
            bind_process_registry_spec(registry, spec)
        checked.append(path_text)
    for path_text in args.state:
        state, _identity = _load(path_text)
        validate_process_state(state)
        checked.append(path_text)
    for path_text in args.proposal:
        proposal, _identity = _load(path_text)
        validate_proposal(proposal)
        checked.append(path_text)
    seen_example_ids: set[str] = set()
    seen_snapshot_ids: set[str] = set()
    for path_text in args.examples:
        examples, _identity = load_jsonl_objects(Path(path_text))
        if not examples:
            raise Phase2ValidationError(f"v2 example file is empty: {path_text}")
        for example in examples:
            spec = specs.get(example.get("source_id"))
            if specs and spec is None:
                raise Phase2ValidationError("v2 example lacks a supplied process spec")
            validate_write_policy_example(example, spec=spec)
            if example["example_id"] in seen_example_ids:
                raise Phase2ValidationError("duplicate v2 example_id")
            seen_example_ids.add(example["example_id"])
            snapshot_id = example["snapshot"]["snapshot_id"]
            if snapshot_id in seen_snapshot_ids:
                raise Phase2ValidationError("duplicate v2 snapshot_id")
            seen_snapshot_ids.add(snapshot_id)
        checked.append(path_text)
    for path_text in args.artifact:
        artifact, _identity = _load(path_text)
        validate_process_artifact(artifact)
        checked.append(path_text)
    _emit(
        {
            "ok": True,
            "schema_digests": schema_digests,
            "instances": sorted(checked),
            "training_authorized": False,
        }
    )
    return 0


def _procedural_generate(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry)
    spec_path = Path(args.spec)
    quarantine_path = Path(args.quarantine)
    registry, registry_identity = load_json_object(registry_path)
    spec, spec_identity = load_json_object(spec_path)
    quarantine, quarantine_identity = load_json_object(quarantine_path)
    examples, report, manifest = build_generation(
        registry=registry, spec=spec, quarantine_index=quarantine
    )
    _require_unchanged(
        [
            (registry_path, registry_identity),
            (spec_path, spec_identity),
            (quarantine_path, quarantine_identity),
        ]
    )
    write_artifact_set_exclusive(
        {
            Path(args.output): canonical_jsonl_bytes(examples),
            Path(args.report): canonical_json_bytes(report),
            Path(args.manifest): canonical_json_bytes(manifest),
        }
    )
    _emit(manifest)
    return 0


def _procedural_verify(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry)
    spec_path = Path(args.spec)
    quarantine_path = Path(args.quarantine)
    examples_path = Path(args.examples)
    report_path = Path(args.report)
    manifest_path = Path(args.manifest)
    registry, registry_identity = load_json_object(registry_path)
    spec, spec_identity = load_json_object(spec_path)
    quarantine, quarantine_identity = load_json_object(quarantine_path)
    examples, examples_identity = load_jsonl_objects(examples_path)
    report, report_identity = load_json_object(report_path)
    manifest, manifest_identity = load_json_object(manifest_path)
    require_canonical_jsonl(examples_path, examples)
    require_canonical_json(report_path, report)
    require_canonical_json(manifest_path, manifest)
    result = verify_generation(
        registry=registry,
        spec=spec,
        quarantine_index=quarantine,
        examples=examples,
        report=report,
        manifest=manifest,
        observed_examples_identity=examples_identity,
    )
    _require_unchanged(
        [
            (registry_path, registry_identity),
            (spec_path, spec_identity),
            (quarantine_path, quarantine_identity),
            (examples_path, examples_identity),
            (report_path, report_identity),
            (manifest_path, manifest_identity),
        ]
    )
    _emit(result)
    return 0


def _process_generate(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry)
    spec_path = Path(args.spec)
    quarantine_path = Path(args.quarantine)
    registry, registry_identity = load_json_object(registry_path)
    spec, spec_identity = load_json_object(spec_path)
    quarantine, quarantine_identity = load_json_object(quarantine_path)
    examples, report, manifest = build_process_generation(
        registry=registry, spec=spec, quarantine_index=quarantine
    )
    _require_unchanged(
        [
            (registry_path, registry_identity),
            (spec_path, spec_identity),
            (quarantine_path, quarantine_identity),
        ]
    )
    write_artifact_set_exclusive(
        {
            Path(args.output): canonical_jsonl_bytes(examples),
            Path(args.report): canonical_json_bytes(report),
            Path(args.manifest): canonical_json_bytes(manifest),
        }
    )
    _emit(manifest)
    return 0


def _load_process_set(
    args: argparse.Namespace,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[tuple[Path, dict[str, Any]]],
]:
    registry_path = Path(args.registry)
    spec_path = Path(args.spec)
    quarantine_path = Path(args.quarantine)
    examples_path = Path(args.examples)
    report_path = Path(args.report)
    manifest_path = Path(args.manifest)
    registry, registry_identity = load_json_object(registry_path)
    spec, spec_identity = load_json_object(spec_path)
    quarantine, quarantine_identity = load_json_object(quarantine_path)
    examples, examples_identity = load_jsonl_objects(examples_path)
    report, report_identity = load_json_object(report_path)
    manifest, manifest_identity = load_json_object(manifest_path)
    require_canonical_jsonl(examples_path, examples)
    require_canonical_json(report_path, report)
    require_canonical_json(manifest_path, manifest)
    inputs = [
        (registry_path, registry_identity),
        (spec_path, spec_identity),
        (quarantine_path, quarantine_identity),
        (examples_path, examples_identity),
        (report_path, report_identity),
        (manifest_path, manifest_identity),
    ]
    return (
        registry,
        spec,
        quarantine,
        examples,
        report,
        manifest,
        examples_identity,
        inputs,
    )


def _process_replay(args: argparse.Namespace) -> int:
    (
        registry,
        spec,
        quarantine,
        examples,
        report,
        manifest,
        examples_identity,
        inputs,
    ) = _load_process_set(args)
    expected_examples, expected_report, expected_manifest = build_process_generation(
        registry=registry, spec=spec, quarantine_index=quarantine
    )
    if (
        examples != expected_examples
        or report != expected_report
        or manifest != expected_manifest
        or examples_identity != manifest["examples"]
    ):
        raise Phase2IntegrityError(
            "process replay inputs fail deterministic verification"
        )
    ledger = replay_process_examples(
        examples=examples, report=report, manifest=manifest
    )
    _require_unchanged(inputs)
    write_artifact_set_exclusive({Path(args.ledger): canonical_json_bytes(ledger)})
    _emit(ledger)
    return 0


def _process_verify(args: argparse.Namespace) -> int:
    (
        registry,
        spec,
        quarantine,
        examples,
        report,
        manifest,
        examples_identity,
        inputs,
    ) = _load_process_set(args)
    ledger_path = Path(args.ledger)
    ledger, ledger_identity = load_json_object(ledger_path)
    require_canonical_json(ledger_path, ledger)
    result = verify_process_generation(
        registry=registry,
        spec=spec,
        quarantine_index=quarantine,
        examples=examples,
        report=report,
        manifest=manifest,
        ledger=ledger,
        observed_examples_identity=examples_identity,
    )
    _require_unchanged([*inputs, (ledger_path, ledger_identity)])
    _emit(result)
    return 0


def _corpus_audit(args: argparse.Namespace) -> int:
    if len(args.manifest) != len(args.report):
        raise Phase2ValidationError(
            "--manifest and --report must be supplied in matching counts"
        )
    manifests: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    inputs: list[tuple[Path, dict[str, Any]]] = []
    for path_text in args.manifest:
        path = Path(path_text)
        value, identity = load_json_object(path)
        require_canonical_json(path, value)
        manifests.append(value)
        inputs.append((path, identity))
    for path_text in args.report:
        path = Path(path_text)
        value, identity = load_json_object(path)
        require_canonical_json(path, value)
        reports.append(value)
        inputs.append((path, identity))
    if any(item.get("schema_version") == "2.0.0" for item in manifests):
        audit = audit_corpora_v2(manifests, reports)
    else:
        audit = audit_corpora(manifests, reports)
    _require_unchanged(inputs)
    if args.output:
        write_artifact_set_exclusive({Path(args.output): canonical_json_bytes(audit)})
    _emit(audit)
    return 0 if audit["clean"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hf-phase2")
    commands = parser.add_subparsers(dest="command", required=True)

    contracts = commands.add_parser("contracts")
    contract_commands = contracts.add_subparsers(
        dest="contracts_command", required=True
    )
    validate = contract_commands.add_parser("validate")
    validate.add_argument("--schema-root")
    validate.add_argument("--registry")
    validate.add_argument("--spec", action="append", default=[])
    validate.add_argument("--examples", action="append", default=[])
    validate.add_argument("--artifact", action="append", default=[])
    validate.set_defaults(handler=_contracts_validate)
    validate_v2 = contract_commands.add_parser("validate-v2")
    validate_v2.add_argument("--schema-root")
    validate_v2.add_argument("--registry")
    validate_v2.add_argument("--spec", action="append", default=[])
    validate_v2.add_argument("--state", action="append", default=[])
    validate_v2.add_argument("--proposal", action="append", default=[])
    validate_v2.add_argument("--examples", action="append", default=[])
    validate_v2.add_argument("--artifact", action="append", default=[])
    validate_v2.set_defaults(handler=_contracts_validate_v2)

    procedural = commands.add_parser("procedural")
    procedural_commands = procedural.add_subparsers(
        dest="procedural_command", required=True
    )
    generate = procedural_commands.add_parser("generate")
    generate.add_argument("--registry", required=True)
    generate.add_argument("--spec", required=True)
    generate.add_argument("--quarantine", required=True)
    generate.add_argument("--output", required=True)
    generate.add_argument("--manifest", required=True)
    generate.add_argument("--report", required=True)
    generate.set_defaults(handler=_procedural_generate)
    verify = procedural_commands.add_parser("verify")
    verify.add_argument("--registry", required=True)
    verify.add_argument("--spec", required=True)
    verify.add_argument("--quarantine", required=True)
    verify.add_argument("--examples", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--report", required=True)
    verify.set_defaults(handler=_procedural_verify)

    process = commands.add_parser("process")
    process_commands = process.add_subparsers(dest="process_command", required=True)
    process_generate = process_commands.add_parser("generate")
    process_generate.add_argument("--registry", required=True)
    process_generate.add_argument("--spec", required=True)
    process_generate.add_argument("--quarantine", required=True)
    process_generate.add_argument("--output", required=True)
    process_generate.add_argument("--manifest", required=True)
    process_generate.add_argument("--report", required=True)
    process_generate.set_defaults(handler=_process_generate)
    for command_name, handler in (
        ("replay", _process_replay),
        ("verify", _process_verify),
    ):
        command = process_commands.add_parser(command_name)
        command.add_argument("--registry", required=True)
        command.add_argument("--spec", required=True)
        command.add_argument("--quarantine", required=True)
        command.add_argument("--examples", required=True)
        command.add_argument("--manifest", required=True)
        command.add_argument("--report", required=True)
        command.add_argument("--ledger", required=True)
        command.set_defaults(handler=handler)

    corpus = commands.add_parser("corpus")
    corpus_commands = corpus.add_subparsers(dest="corpus_command", required=True)
    audit = corpus_commands.add_parser("audit")
    audit.add_argument("--manifest", action="append", required=True)
    audit.add_argument("--report", action="append", required=True)
    audit.add_argument("--output")
    audit.set_defaults(handler=_corpus_audit)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (Phase2Error, Phase0Error) as exc:
        sys.stderr.write(f"hf-phase2: {exc}\n")
        return 2
