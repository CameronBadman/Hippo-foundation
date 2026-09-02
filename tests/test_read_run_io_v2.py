"""The v2 split boundary: what may reach a model, and what may never.

`io.validate_model_input_fields` rejects every v2 payload by exact-set match,
which is why this module exists rather than widening the frozen v1 check. These
tests hold the replacement to the same standard: the allowlist is exact, the
hidden stream stays private, the manifests bind the bytes, and no dataset ever
declares itself authorized to train.
"""

from __future__ import annotations

import copy
import hashlib
import os
import stat
from pathlib import Path

import pytest

from hippocampus_foundation.read_run.errors import GenerationError, IntegrityGateError
from hippocampus_foundation.read_run.generator_v2 import CELLS, generate_episode_v2
from hippocampus_foundation.read_run.io import validate_model_input_fields
from hippocampus_foundation.read_run.io_v2 import (
    read_generated_split_v2,
    validate_generated_split_artifacts_v2,
    validate_model_input_fields_v2,
    write_generated_split_v2,
)

TEST_SEED = hashlib.sha256(b"io-v2-tests").digest()
CELL = CELLS["deg3_len6_v8"]


def _episode(index: int = 0, gamma: float = 0.4):
    return generate_episode_v2(
        TEST_SEED,
        config=CELL,
        split="test-fixture",
        index=index,
        count=32,
        gamma=gamma,
        gold_mask=1 + index % 15,
    )


def _written(tmp_path: Path, count: int = 32, gamma: float = 0.4):
    destination = tmp_path / "split"
    public, private = write_generated_split_v2(
        master_seed=TEST_SEED,
        config=CELL,
        split="test-fixture",
        count=count,
        gamma=gamma,
        destination=destination,
    )
    return destination, public, private


def test_v1_validator_rejects_v2_payloads_which_is_why_this_module_exists():
    episode = _episode()
    with pytest.raises(IntegrityGateError):
        validate_model_input_fields(episode)
    validate_model_input_fields_v2(episode)


def test_allowlist_is_exact_in_both_directions():
    episode = _episode()
    extra = copy.deepcopy(episode.visible)
    extra["valid_routes"] = [[0]]
    with pytest.raises(IntegrityGateError):
        validate_model_input_fields_v2(
            type(episode)(
                episode.episode_id, episode.paired_world_id, extra, episode.hidden
            )
        )
    missing = copy.deepcopy(episode.visible)
    del missing["content_value_count"]
    with pytest.raises(IntegrityGateError):
        validate_model_input_fields_v2(
            type(episode)(
                episode.episode_id, episode.paired_world_id, missing, episode.hidden
            )
        )


def test_node_records_are_checked_against_the_declared_schema():
    episode = _episode()
    for mutate in (
        lambda visible: visible["nodes"][0].__setitem__("rule", [1, 2]),
        lambda visible: visible["nodes"][0].__setitem__("content", [0]),
        lambda visible: visible["nodes"][0]["content"].__setitem__(
            0, visible["content_value_count"]
        ),
    ):
        broken = copy.deepcopy(episode.visible)
        mutate(broken)
        with pytest.raises(IntegrityGateError):
            validate_model_input_fields_v2(
                type(episode)(
                    episode.episode_id, episode.paired_world_id, broken, episode.hidden
                )
            )


def test_round_trip_is_byte_exact_and_streams_carry_their_modes(tmp_path):
    destination, public, private = _written(tmp_path)
    assert public["training_authorized"] is False
    assert public["record_kind"] == "read_split_manifest_v2"
    assert public["generator_cell"] == CELL.cell
    assert "hidden_sha256" in private and "hidden_sha256" not in public

    generated = [
        generate_episode_v2(
            TEST_SEED,
            config=CELL,
            split="test-fixture",
            index=index,
            count=32,
            gamma=0.4,
            gold_mask=None if index % 4 == 0 else 1 + (index % 15),
        )
        for index in range(32)
    ]
    read_back = list(read_generated_split_v2(destination))
    assert len(read_back) == len(generated) == public["episode_count"]
    for original, restored in zip(generated, read_back, strict=True):
        assert restored.episode_id == original.episode_id
        assert restored.visible == original.visible
        assert restored.hidden == original.hidden

    for name, expected in (
        ("visible.jsonl.gz", 0o644),
        ("hidden.jsonl.gz", 0o600),
        ("manifest.public.json", 0o644),
        ("manifest.private.json", 0o600),
    ):
        assert stat.S_IMODE(os.stat(destination / name).st_mode) == expected, name


def test_manifests_bind_the_bytes(tmp_path):
    destination, _public, _private = _written(tmp_path)
    assert validate_generated_split_artifacts_v2(destination)
    with (destination / "visible.jsonl.gz").open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(IntegrityGateError):
        validate_generated_split_artifacts_v2(destination)


def test_writing_refuses_to_overwrite_a_destination(tmp_path):
    destination, _public, _private = _written(tmp_path)
    with pytest.raises(GenerationError):
        write_generated_split_v2(
            master_seed=TEST_SEED,
            config=CELL,
            split="test-fixture",
            count=32,
            gamma=0.4,
            destination=destination,
        )


def test_split_is_deterministic_from_the_seed(tmp_path):
    first, public_a, _ = _written(tmp_path / "a")
    second, public_b, _ = _written(tmp_path / "b")
    assert public_a["visible_sha256"] == public_b["visible_sha256"]
    assert public_a["seed_commitment"] == public_b["seed_commitment"]
    other = hashlib.sha256(b"a-different-seed").digest()
    third = tmp_path / "c" / "split"
    public_c, _ = write_generated_split_v2(
        master_seed=other,
        config=CELL,
        split="test-fixture",
        count=32,
        gamma=0.4,
        destination=third,
    )
    assert public_c["visible_sha256"] != public_a["visible_sha256"]
