"""Deterministic split writer and reader for Track O (v2 payloads).

`io.validate_model_input_fields` exact-set-matches the v1 visible allowlist, so
it rejects every v2 payload: generator v2 adds `generator_cell`,
`content_attribute_count`, `content_value_count` and a `content` key inside each
node. That check is the leakage control and must not be widened in place, so
this module carries the v2 allowlist and leaves v1's frozen.

Everything else is v1's discipline verbatim, reusing its helpers by import: one
deterministic gzip stream for visible bytes at 0644 and one for hidden labels at
0600, written into a private temporary directory and moved into place with
`os.replace` only after both are fsynced, public and private manifests carrying
the stream digests and the seed commitment, and `training_authorized: False`
stamped on every manifest — a dataset is never a licence to train.

Materialising splits is not a convenience here. The `deg6_len8_v4_rep` cell
rejects about 17 % of generation attempts to its uniqueness constraint and costs
roughly 0.2 s per surviving episode single-threaded, so generating per training
batch would cost more than the forward pass by two orders of magnitude. Writing
the split once, in parallel, also makes the training data a hashable artifact
the Track O preregistration can pin.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from hippocampus_foundation.phase0.canonical import canonical_bytes

from .errors import GenerationError, IntegrityGateError
from .generator import GeneratedEpisode
from .generator_v2 import CELLS, GeneratorV2Config, generate_episode_v2
from .io import (
    MAX_JSON_LINE_BYTES,
    _open_deterministic_gzip,
    _sha256_file,
    _write_all,
    _write_json_exclusive,
)
from .seed import seed_commitment

SCHEMA_VERSION_V2 = "2.0.0"

VISIBLE_ALLOWLIST_V2 = frozenset(
    {
        "schema_version",
        "record_kind",
        "generator_cell",
        "router_seed",
        "budget_candidates",
        "node_count",
        "relation_count",
        "content_attribute_count",
        "content_value_count",
        "start_node",
        "query_relations",
        "nodes",
        "edges",
    }
)

FORBIDDEN_IN_VISIBLE_V2 = frozenset(
    {
        "episode_id",
        "paired_world_id",
        "split",
        "requested_gamma",
        "branch_depth",
        "relation_rules",
        "planting_valid_set_sizes",
        "target_nodes",
        "valid_routes",
        "teacher_actions",
        "abstain",
        "gold_assertion_mask",
        "greedy_wrong_count",
        "path_step_count",
        "measured_gamma",
    }
)

NODE_ALLOWLIST_V2 = frozenset({"node", "assertions", "content"})


def validate_model_input_fields_v2(episode: GeneratedEpisode) -> None:
    """Raise unless the v2 model-visible payload matches its allowlist.

    Checks the node records too, which v1 did not need to: `content` is the one
    v2 field a careless generator change could fill from hidden truth, and the
    episode-local rule table (`relation_rules`) is exactly the kind of thing
    that must never cross into the visible stream.
    """

    overlap = FORBIDDEN_IN_VISIBLE_V2 & set(episode.visible)
    if overlap:
        raise IntegrityGateError(
            f"hidden fields entered model-visible payload: {sorted(overlap)}"
        )
    if set(episode.visible) != set(VISIBLE_ALLOWLIST_V2):
        raise IntegrityGateError(
            "v2 model-visible payload fields differ from the allowlist"
        )
    attributes = episode.visible["content_attribute_count"]
    values = episode.visible["content_value_count"]
    for node in episode.visible["nodes"]:
        if set(node) != set(NODE_ALLOWLIST_V2):
            raise IntegrityGateError("v2 node record fields differ from the allowlist")
        content = node["content"]
        if len(content) != attributes or any(
            not isinstance(value, int) or not 0 <= value < values for value in content
        ):
            raise IntegrityGateError("v2 node content violates the declared schema")


def model_input_bytes_v2(episode: GeneratedEpisode) -> bytes:
    """The only bytes a Track O model is permitted to receive."""

    validate_model_input_fields_v2(episode)
    return canonical_bytes(episode.visible)


def write_generated_split_v2(
    *,
    master_seed: bytes,
    config: GeneratorV2Config,
    split: str,
    count: int,
    gamma: float,
    destination: Path,
    episodes: Iterator[GeneratedEpisode] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically write separate visible and hidden deterministic streams.

    `episodes` exists so a caller that generated in parallel can stream its
    results in; when omitted the episodes are generated here in order. Either
    way the bytes written are a function of the seed, the cell and the split
    alone, and `attempted` records how many indices were tried so a cell's
    generation-failure rate stays visible in the manifest.
    """

    config.validate()
    if destination.exists() or destination.is_symlink():
        raise GenerationError("refusing to overwrite a dataset destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    os.chmod(temporary, 0o700)
    visible_path = temporary / "visible.jsonl.gz"
    hidden_path = temporary / "hidden.jsonl.gz"
    visible_raw: BinaryIO | None = None
    hidden_raw: BinaryIO | None = None
    visible_gzip: gzip.GzipFile | None = None
    hidden_gzip: gzip.GzipFile | None = None

    def _default_episodes() -> Iterator[GeneratedEpisode]:
        for index in range(count):
            try:
                yield generate_episode_v2(
                    master_seed,
                    config=config,
                    split=split,
                    index=index,
                    count=count,
                    gamma=gamma,
                    gold_mask=None if index % 4 == 0 else 1 + (index % 15),
                )
            except GenerationError:
                continue

    try:
        visible_raw, visible_gzip = _open_deterministic_gzip(visible_path, mode=0o644)
        hidden_raw, hidden_gzip = _open_deterministic_gzip(hidden_path, mode=0o600)
        generated = 0
        abstain_count = 0
        gamma_wrong = 0
        gamma_steps = 0
        for episode in episodes if episodes is not None else _default_episodes():
            validate_model_input_fields_v2(episode)
            _write_all(
                visible_gzip,
                canonical_bytes(
                    {"episode_id": episode.episode_id, "visible": episode.visible}
                ),
            )
            _write_all(
                hidden_gzip,
                canonical_bytes(
                    {"episode_id": episode.episode_id, "hidden": episode.hidden}
                ),
            )
            generated += 1
            abstain_count += bool(episode.hidden["abstain"])
            gamma_wrong += episode.hidden["greedy_wrong_count"]
            gamma_steps += episode.hidden["path_step_count"]
        if generated == 0:
            raise GenerationError("split produced no episodes")
        for handle in (visible_gzip, hidden_gzip):
            handle.close()
        visible_gzip = hidden_gzip = None
        for handle in (visible_raw, hidden_raw):
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
        visible_raw = hidden_raw = None

        visible_bytes, visible_sha256 = _sha256_file(visible_path)
        hidden_bytes, hidden_sha256 = _sha256_file(hidden_path)
        common = {
            "schema_version": SCHEMA_VERSION_V2,
            "record_kind": "read_split_manifest_v2",
            "generator_cell": config.cell,
            "generator_config": config.label(),
            "split": split,
            "requested_gamma": gamma,
            "attempted": count,
            "episode_count": generated,
            "generation_failure_fraction": 1.0 - generated / count,
            "abstain_count": abstain_count,
            "measured_gamma": gamma_wrong / gamma_steps if gamma_steps else None,
            "visible_bytes": visible_bytes,
            "visible_sha256": visible_sha256,
            "seed_commitment": seed_commitment(master_seed),
            "training_authorized": False,
        }
        public_manifest = {**common, "disclosure": "model_visible_only"}
        private_manifest = {
            **common,
            "disclosure": "private_labels_and_oracle",
            "hidden_bytes": hidden_bytes,
            "hidden_sha256": hidden_sha256,
        }
        _write_json_exclusive(
            temporary / "manifest.public.json", public_manifest, mode=0o644
        )
        _write_json_exclusive(
            temporary / "manifest.private.json", private_manifest, mode=0o600
        )
        directory = os.open(temporary, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        os.replace(temporary, destination)
        parent = os.open(
            destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return public_manifest, private_manifest
    except Exception:
        for handle in (visible_gzip, hidden_gzip, visible_raw, hidden_raw):
            if handle is not None:
                handle.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _read_gzip_records_v2(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with gzip.open(path, "rb") as handle:
            for raw in handle:
                if len(raw) > MAX_JSON_LINE_BYTES:
                    raise IntegrityGateError(
                        "dataset JSON line exceeds the fixed bound"
                    )
                try:
                    value = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise IntegrityGateError(
                        "dataset stream contains invalid JSON"
                    ) from exc
                if not isinstance(value, dict):
                    raise IntegrityGateError("dataset record must be an object")
                yield value
    except OSError as exc:
        raise IntegrityGateError("cannot read deterministic dataset stream") from exc


def read_generated_split_v2(root: Path) -> Iterator[GeneratedEpisode]:
    """Stream a v2 split, checking the visible allowlist on every episode."""

    visible = _read_gzip_records_v2(root / "visible.jsonl.gz")
    hidden = _read_gzip_records_v2(root / "hidden.jsonl.gz")
    count = 0
    while True:
        public_record = next(visible, None)
        private_record = next(hidden, None)
        if public_record is None or private_record is None:
            if public_record is not None or private_record is not None:
                raise IntegrityGateError("visible and hidden stream lengths differ")
            break
        if set(public_record) != {"episode_id", "visible"} or set(private_record) != {
            "episode_id",
            "hidden",
        }:
            raise IntegrityGateError("dataset stream record fields differ")
        if public_record["episode_id"] != private_record["episode_id"]:
            raise IntegrityGateError("visible and hidden stream identities differ")
        episode = GeneratedEpisode(
            episode_id=public_record["episode_id"],
            paired_world_id=private_record["hidden"]["paired_world_id"],
            visible=public_record["visible"],
            hidden=private_record["hidden"],
        )
        validate_model_input_fields_v2(episode)
        count += 1
        yield episode
    if count == 0:
        raise IntegrityGateError("dataset stream is empty")


def validate_generated_split_artifacts_v2(root: Path) -> dict[str, Any]:
    """Rehash the streams against the manifests before any episode is read."""

    public_manifest = json.loads((root / "manifest.public.json").read_text())
    private_manifest = json.loads((root / "manifest.private.json").read_text())
    if public_manifest["record_kind"] != "read_split_manifest_v2":
        raise IntegrityGateError("split manifest is not a v2 manifest")
    if public_manifest["training_authorized"] is not False:
        raise IntegrityGateError("a dataset manifest may never authorize training")
    if public_manifest["generator_cell"] not in CELLS:
        raise IntegrityGateError("split manifest names an unknown generator cell")
    visible_bytes, visible_sha256 = _sha256_file(root / "visible.jsonl.gz")
    hidden_bytes, hidden_sha256 = _sha256_file(root / "hidden.jsonl.gz")
    if (
        visible_bytes != public_manifest["visible_bytes"]
        or visible_sha256 != public_manifest["visible_sha256"]
    ):
        raise IntegrityGateError("visible stream does not match its manifest")
    if (
        hidden_bytes != private_manifest["hidden_bytes"]
        or hidden_sha256 != private_manifest["hidden_sha256"]
    ):
        raise IntegrityGateError("hidden stream does not match its manifest")
    return {"public": public_manifest, "private": private_manifest}
