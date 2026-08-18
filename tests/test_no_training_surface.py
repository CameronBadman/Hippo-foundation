from __future__ import annotations

import tomllib
from pathlib import Path

from hippocampus_foundation.phase0.cli import build_parser as build_phase0_parser
from hippocampus_foundation.phase1.cli import build_parser as build_phase1_parser

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_and_cli_expose_governance_only() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == ["jsonschema>=4.23,<5", "rfc8785>=0.1.4,<1"]
    assert project["scripts"] == {
        "hf-phase0": "hippocampus_foundation.phase0.cli:main",
        "hf-phase1": "hippocampus_foundation.phase1.cli:main",
    }

    parser = build_phase0_parser()
    top_level_choices = next(
        action.choices
        for action in parser._actions
        if getattr(action, "choices", None)
    )
    assert set(top_level_choices) == {
        "registry",
        "storage",
        "source",
        "quarantine",
        "seal",
        "licence",
        "gate",
        "gate-v3",
        "gate-v1",
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
        option
        for action in acquire_parser._actions
        for option in action.option_strings
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
