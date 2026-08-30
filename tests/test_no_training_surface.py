from __future__ import annotations

import tomllib
from pathlib import Path

from hippocampus_foundation.phase0.cli import build_parser as build_phase0_parser
from hippocampus_foundation.phase1.cli import build_parser as build_phase1_parser
from hippocampus_foundation.phase2.cli import build_parser as build_phase2_parser

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_and_cli_expose_governance_only() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    assert project["dependencies"] == [
        "google-api-python-client>=2.179,<3",
        "google-auth>=2.40,<3",
        "huggingface-hub>=1.29,<2",
        "jsonschema>=4.23,<5",
        "rfc8785>=0.1.4,<1",
    ]
    assert project["scripts"] == {
        "hf-phase0": "hippocampus_foundation.phase0.cli:main",
        "hf-phase1": "hippocampus_foundation.phase1.cli:main",
        "hf-phase2": "hippocampus_foundation.phase2.cli:main",
    }

    parser = build_phase0_parser()
    top_level_choices = next(
        action.choices for action in parser._actions if getattr(action, "choices", None)
    )
    assert set(top_level_choices) == {
        "registry",
        "oauth",
        "storage",
        "source",
        "evaluation",
        "quarantine",
        "seal",
        "licence",
        "gate",
        "gate-v3",
        "gate-v4",
        "gate-v4.1",
        "gate-v4.2",
        "gate-v4.3",
        "gate-v1",
        "publication",
        "publication-gate-v1",
    }
    assert not ({"train", "fit", "optimize", "model"} & set(top_level_choices))

    source_parser = top_level_choices["source"]
    source_choices = next(
        action.choices
        for action in source_parser._actions
        if getattr(action, "choices", None)
    )
    acquire_parser = source_choices["acquire"]
    acquire_options = {
        option for action in acquire_parser._actions for option in action.option_strings
    }
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        acquire_options
    )
    assert {
        "--sources",
        "--storage-attestation",
        "--evaluations",
        "--quarantine",
        "--source-audit",
        "--licence-review",
        "--seal",
        "--contribution",
        "--inventory",
        "--admission",
        "--artifact-id",
        "--evaluated-at",
    }.issubset(acquire_options)

    acquire_v3_parser = source_choices["acquire-v3"]
    assert acquire_v3_parser.get_default("handler").__name__ == "_source_acquire_v3"
    acquire_v3_options = {
        option
        for action in acquire_v3_parser._actions
        for option in action.option_strings
    }
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        acquire_v3_options
    )
    assert {
        "--sources",
        "--storage-attestation",
        "--evaluations",
        "--quarantine",
        "--source-audit",
        "--licence-assessment",
        "--seal",
        "--contribution",
        "--inventory",
        "--admission",
        "--artifact-id",
        "--evaluated-at",
    }.issubset(acquire_v3_options)

    acquire_v4_parser = source_choices["acquire-v4"]
    acquire_v4_options = {
        option
        for action in acquire_v4_parser._actions
        for option in action.option_strings
    }
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        acquire_v4_options
    )
    assert {
        "--sources",
        "--source-predecessor",
        "--evaluations",
        "--evaluation-predecessor",
        "--publisher",
        "--artifact-id",
        "--evaluated-at",
    }.issubset(acquire_v4_options)
    gate_v4_parser = top_level_choices["gate-v4"]
    gate_v4_options = {
        option for action in gate_v4_parser._actions for option in action.option_strings
    }
    assert {
        "--sources",
        "--source-predecessor",
        "--evaluations",
        "--evaluation-predecessor",
        "--drive-observation",
        "--storage-attestation",
        "--publisher",
        "--source-audit",
        "--licence-assessment",
        "--seal-v4",
        "--anchor-v4",
        "--contribution",
        "--quarantine",
        "--inventory",
        "--admission",
        "--evaluated-at",
    }.issubset(gate_v4_options)
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        gate_v4_options
    )

    acquire_v4_1_parser = source_choices["acquire-v4.1"]
    acquire_v4_1_options = {
        option
        for action in acquire_v4_1_parser._actions
        for option in action.option_strings
    }
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        acquire_v4_1_options
    )
    assert {
        "--source-registry",
        "--evaluation-registry",
        "--drive-observation",
        "--storage-attestation",
        "--publisher",
        "--source-audit",
        "--licence-assessment",
        "--materialization",
        "--seal-v4",
        "--anchor-v4",
        "--contribution",
        "--quarantine",
        "--inventory",
        "--admission",
        "--artifact-id",
        "--evaluated-at",
    }.issubset(acquire_v4_1_options)

    gate_v4_1_parser = top_level_choices["gate-v4.1"]
    gate_v4_1_options = {
        option
        for action in gate_v4_1_parser._actions
        for option in action.option_strings
    }
    assert acquire_v4_1_options - {"--artifact-id", "--minimum-free-bytes"} <= (
        gate_v4_1_options | {"-h", "--help"}
    )
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        gate_v4_1_options
    )

    acquire_v4_2_parser = source_choices["acquire-v4.2"]
    acquire_v4_2_options = {
        option
        for action in acquire_v4_2_parser._actions
        for option in action.option_strings
    }
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        acquire_v4_2_options
    )
    assert {
        "--source-registry",
        "--evaluation-registry",
        "--authority-policy",
        "--oauth-authority",
        "--drive-access-proof",
        "--acquisition-authorization",
        "--adc-file",
        "--artifact-id",
        "--receipt-output",
        "--pre-source-audit-output",
    }.issubset(acquire_v4_2_options)
    assert "--evaluated-at" not in acquire_v4_2_options

    gate_v4_2_parser = top_level_choices["gate-v4.2"]
    gate_v4_2_options = {
        option
        for action in gate_v4_2_parser._actions
        for option in action.option_strings
    }
    assert {
        "--authority-policy",
        "--oauth-authority",
        "--drive-access-proof",
        "--acquisition-authorization",
        "--acquisition-evidence",
        "--evaluated-at",
    }.issubset(gate_v4_2_options)
    assert {"--url", "--destination", "--expected-bytes", "--checksum"}.isdisjoint(
        gate_v4_2_options
    )

    acquire_v4_3_parser = source_choices["acquire-v4.3"]
    acquire_v4_3_options = {
        option
        for action in acquire_v4_3_parser._actions
        for option in action.option_strings
    }
    assert {
        "--url",
        "--destination",
        "--expected-bytes",
        "--checksum",
        "--evaluated-at",
    }.isdisjoint(acquire_v4_3_options)
    assert {
        "--source-registry",
        "--evaluation-registry",
        "--publisher",
        "--materialization",
        "--seal-v4",
        "--anchor-v4",
        "--staging-observation",
        "--authorization",
    }.issubset(acquire_v4_3_options)

    publication_parser = top_level_choices["publication"]
    publication_choices = next(
        action.choices
        for action in publication_parser._actions
        if getattr(action, "choices", None)
    )
    upload_options = {
        option
        for action in publication_choices["upload-v1"]._actions
        for option in action.option_strings
    }
    assert {
        "--token",
        "--endpoint",
        "--repo-id",
        "--remote-path",
        "--local-path",
        "--expected-bytes",
        "--checksum",
        "--evaluated-at",
    }.isdisjoint(upload_options)
    assert {
        "--destination-policy",
        "--source-registry",
        "--evaluation-registry",
        "--rights",
        "--clearance",
        "--manifest",
        "--authorization",
        "--staging-observation",
    }.issubset(upload_options)

    evaluation_parser = top_level_choices["evaluation"]
    evaluation_choices = next(
        action.choices
        for action in evaluation_parser._actions
        if getattr(action, "choices", None)
    )
    assert set(evaluation_choices) == {"materialize-v4.1"}
    assert not ({"train", "fit", "optimize", "model"} & set(evaluation_choices))

    phase1_parser = build_phase1_parser()
    phase1_choices = next(
        action.choices
        for action in phase1_parser._actions
        if getattr(action, "choices", None)
    )
    assert set(phase1_choices) == {
        "contracts",
        "graph",
        "sample",
        "encoder",
        "objectives",
        "gate",
        "gate-v2",
    }
    assert not ({"train", "fit", "optimize", "model"} & set(phase1_choices))

    phase2_parser = build_phase2_parser()
    phase2_choices = next(
        action.choices
        for action in phase2_parser._actions
        if getattr(action, "choices", None)
    )
    assert set(phase2_choices) == {"contracts", "procedural", "process", "corpus"}
    assert not (
        {"train", "fit", "optimize", "model", "commit", "apply"} & set(phase2_choices)
    )
    process_parser = phase2_choices["process"]
    process_choices = next(
        action.choices
        for action in process_parser._actions
        if getattr(action, "choices", None)
    )
    assert set(process_choices) == {"generate", "replay", "verify"}
    assert not (
        {"train", "fit", "optimize", "model", "commit", "apply"} & set(process_choices)
    )
