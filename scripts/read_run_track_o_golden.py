"""Record the Track O walk's behaviour as a fixture, before any optimisation.

The optimisation pass changes how features are built, how tensors are
constructed, and how work is batched. None of that may change *which edges the
walk examines* — and the walk is the result Track O reported. A speedup that
quietly reorders the frontier is indistinguishable from one that does not unless
the prior behaviour is written down first, so this script writes it down.

Two hazards make the exact-equality half load-bearing rather than pedantic. The
frontier tie-break at `model_v2.py:1068-1076` sums two independently detached
float32 values in Python float64, once per frontier entry per round; summing
them on the GPU or fusing the bonus into the score tensor can flip a near-tie
and change the walk. And `pair_features` supplies the adjacency bits that the
whole path-scoped design rests on, so a vectorised rewrite that transposes an
axis would still produce plausible-looking scores.

CPU and float32, so the fixture is portable and the test needs no GPU. Device
and dtype equivalence is a separate test, because v1 once shipped a dtype fault
to a whole sweep behind an fp32-only equivalence check
(`tests/test_read_run.py:616-626`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hippocampus_foundation.read_run.errors import GenerationError  # noqa: E402
from hippocampus_foundation.read_run.generator_v2 import (  # noqa: E402
    CELLS,
    generate_episode_v2,
)
from hippocampus_foundation.read_run.model import require_torch  # noqa: E402
from hippocampus_foundation.read_run.model_v2 import (  # noqa: E402
    EpisodeIndex,
    Prefix,
    build_read_model_v2,
    candidate_features,
    context_features,
    pair_features,
    query_cross_features,
    route_prefixes,
    walker_expansions,
)

FIXTURE_SEED = hashlib.sha256(b"track-o-golden-fixture").digest()
CELL_NAMES = ("deg3_len6_v8", "deg6_len8_v4_rep")
EPISODES_PER_CELL = 4
MODEL_SEED = 1729
BUDGET = 64


def episodes_for(cell: str, count: int = EPISODES_PER_CELL) -> list[Any]:
    config = CELLS[cell]
    out = []
    for index in range(count * 8):
        try:
            out.append(
                generate_episode_v2(
                    FIXTURE_SEED,
                    config=config,
                    split="test-fixture",
                    index=index,
                    count=count * 8,
                    gamma=0.4,
                    gold_mask=1 + index % 15,
                )
            )
        except GenerationError:
            continue
        if len(out) == count:
            break
    if len(out) != count:
        raise RuntimeError(f"{cell}: could not generate {count} fixture episodes")
    return out


def feature_rows(episodes) -> dict[str, Any]:
    """Feature vectors, recorded independently of any model weights.

    The walk-decision fixture turned out to be an insensitive detector on its
    own: with a randomly initialised scorer, flipping the sign of the similarity
    feature left every examined set identical, because a random head does not
    respond strongly to any single input column. Since the optimisation pass
    rewrites exactly these functions, the featurisers are pinned directly —
    elementwise, weight-free, and immune to that insensitivity.
    """

    out: dict[str, Any] = {}
    for episode in episodes[:2]:
        index = EpisodeIndex(episode.visible)
        start = index.start
        group = [edge["edge_id"] for edge in index.group(start)]
        prefix = Prefix((), start, 0)
        # A depth-1 prefix as well, so prefix-dependent blocks are exercised.
        deeper = None
        for edge in index.group(start):
            if edge["relation"] == index.relations[0]:
                deeper = Prefix((edge["edge_id"],), edge["target"], 1)
                break
        rows: dict[str, Any] = {
            "candidate_depth0": [
                candidate_features(index, prefix, edge_id) for edge_id in group
            ],
            "candidate_no_content": [
                candidate_features(index, prefix, edge_id, content_features=False)
                for edge_id in group
            ],
            "context": [
                context_features(index, prefix, edge_id, 0) for edge_id in group
            ],
            "pair": [[pair_features(index, c, x) for x in group] for c in group],
            "query_cross": [
                [
                    query_cross_features(index, prefix, group[0], position)
                    for position in range(8)
                ]
            ],
        }
        if deeper is not None:
            deep_group = [edge["edge_id"] for edge in index.group(deeper.node)]
            rows["candidate_depth1"] = [
                candidate_features(index, deeper, edge_id) for edge_id in deep_group
            ]
            rows["context_depth1"] = [
                context_features(index, deeper, edge_id, 1) for edge_id in deep_group
            ]
        out[episode.episode_id] = rows
    return out


def record(torch, model, episodes, *, mode: str) -> dict[str, Any]:
    visible = [episode.visible for episode in episodes]
    supplied = None
    if mode == "gold":
        supplied = [
            route_prefixes(e.visible, e.hidden["valid_routes"]) for e in episodes
        ]
    elif mode == "walker":
        supplied = [walker_expansions(e.visible, BUDGET) for e in episodes]
    with torch.no_grad():
        out = model(visible, budget=BUDGET, supplied=supplied)

    # The walk's per-episode structures are recorded as digests, not values.
    # `routes` on a correct walk *is* the episode's planted route set, and
    # `edge_ids`/`prefixes` are examined-set data; a digest pins them exactly
    # while keeping hidden-derived per-episode values out of a tracked file,
    # which is the same rule the committed diagnostics follow.
    def digest(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    return {
        "edge_ids_sha256": [digest(row) for row in out["edge_ids"]],
        "prefixes_sha256": [digest([list(p) for p in row]) for row in out["prefixes"]],
        "routes_sha256": [digest(row) for row in out["routes"]],
        "stop_reason": out["stop_reason"],
        "examined_count": out["examined_count"],
        "expansion_count": out["expansion_count"],
        "logits": [[round(v, 6) for v in row] for row in out["logits"].tolist()],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="experiments/track_o_v1/training-config.o1.json"
    )
    parser.add_argument("--output", default="tests/fixtures/track_o_golden.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    torch, _nn, _functional = require_torch()
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(MODEL_SEED)
    model = build_read_model_v2(config)  # CPU, float32
    model.eval()

    cells: dict[str, Any] = {}
    for cell in CELL_NAMES:
        episodes = episodes_for(cell)
        cells[cell] = {
            "episode_ids": [e.episode_id for e in episodes],
            "features": feature_rows(episodes),
            "modes": {
                mode: record(torch, model, episodes, mode=mode)
                for mode in ("on_policy", "gold", "walker")
            },
        }
        walk = cells[cell]["modes"]["on_policy"]
        print(
            f"{cell}: examined {walk['examined_count']} expansions "
            f"{walk['expansion_count']} stops {walk['stop_reason']}"
        )

    Path(args.output).write_text(
        json.dumps(
            {
                "record_kind": "read_run_track_o_golden_fixture",
                "purpose": (
                    "pins the walk's behaviour before the optimisation pass; "
                    "walk decisions are asserted exactly, logits to a tolerance"
                ),
                "fixture_seed_label": "track-o-golden-fixture",
                "model_seed": MODEL_SEED,
                "budget": BUDGET,
                "device": "cpu",
                "dtype": "float32",
                "config": args.config,
                "config_sha256": "sha256:"
                + hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
                "cells": cells,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
