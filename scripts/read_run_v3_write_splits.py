"""Materialise the Track P training and screening splits at K distractor paths.

The v2 writer (`read_run_v2_write_splits.py`) stays as it is; this is its v3
counterpart and keeps the property that matters: episodes are generated in
parallel but streamed to `io_v2.write_generated_split_v2` in **index order**, so
the bytes on disk are a function of the seed, the cell and the split alone and
are identical to what single-threaded generation would have produced.

Generation is the bottleneck. The hard cell at K = 1 succeeds on about 72 % of
attempts and costs roughly 1.4 s per surviving episode single-threaded
(`experiments/track_p_v1/diagnostics/policy_ladder_v3.json`), so a 20,000-episode
split is hours serially and minutes across the machine.

Writes visible streams 0644 and hidden streams 0600 under `private/`, which is
gitignored, and refuses any split but `train`/`screen` and any destination whose
path mentions a holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import multiprocessing
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hippocampus_foundation.read_run.errors import GenerationError  # noqa: E402
from hippocampus_foundation.read_run.generator_v3 import (  # noqa: E402
    CELLS_V3,
    generate_episode_v3,
)
from hippocampus_foundation.read_run.io_v2 import (  # noqa: E402
    write_generated_split_v2,
)

ALLOWED_SPLITS = ("train", "screen")
_CONTEXT: dict[str, Any] = {}


def _initialise(cell: str, seed_hex: str, split: str, count: int, gamma: float) -> None:
    _CONTEXT.update(
        cell=cell, seed=bytes.fromhex(seed_hex), split=split, count=count, gamma=gamma
    )


def _generate(index: int):
    try:
        return generate_episode_v3(
            _CONTEXT["seed"],
            config=CELLS_V3[_CONTEXT["cell"]],
            split=_CONTEXT["split"],
            index=index,
            count=_CONTEXT["count"],
            gamma=_CONTEXT["gamma"],
            gold_mask=None if index % 4 == 0 else 1 + (index % 15),
        )
    except GenerationError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", required=True, choices=sorted(CELLS_V3))
    parser.add_argument("--split", required=True, choices=ALLOWED_SPLITS)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--gamma", type=float, default=0.4)
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--seed-label", default="track-p-v1-data")
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()

    destination = Path(args.destination)
    if "holdout" in str(destination) or "heldout" in str(destination):
        raise SystemExit("refusing to write a holdout path")
    seed = hashlib.sha256(args.seed_label.encode()).digest()

    with multiprocessing.Pool(
        args.workers,
        initializer=_initialise,
        initargs=(args.cell, seed.hex(), args.split, args.count, args.gamma),
    ) as pool:
        episodes = [
            episode
            for episode in pool.imap(_generate, range(args.count), chunksize=8)
            if episode is not None
        ]

    distractors = sum(
        len(episode.hidden.get("distractor_routes", ())) for episode in episodes
    )
    public, _private = write_generated_split_v2(
        master_seed=seed,
        config=CELLS_V3[args.cell],
        split=args.split,
        count=args.count,
        gamma=args.gamma,
        destination=destination,
        episodes=iter(episodes),
    )
    print(
        f"{args.cell}/{args.split}: {public['episode_count']}/{public['attempted']} "
        f"episodes (failure {public['generation_failure_fraction']:.3f}), "
        f"measured gamma {public['measured_gamma']:.4f}, "
        f"distractors/episode {distractors / max(len(episodes), 1):.2f}, "
        f"visible {public['visible_sha256'][:19]}",
        flush=True,
    )


if __name__ == "__main__":
    main()
