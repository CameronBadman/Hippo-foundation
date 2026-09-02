"""Materialise the Track O training and screening splits (phase O-3b).

Generation is the bottleneck, not writing: `deg6_len8_v4_rep` rejects about
17 % of attempts to its uniqueness constraint and costs roughly 0.2 s per
surviving episode single-threaded, so a training loop that generated per batch
would spend two orders of magnitude more time on data than on the model. This
script generates in parallel across the machine's cores and streams the results
into `io_v2.write_generated_split_v2` in index order, so the bytes are a
function of the seed, the cell and the split alone — identical to what
single-threaded generation would have produced.

Writes visible streams 0644 and hidden streams 0600 under `private/`, which is
gitignored. Touches no holdout: `split` is `train` or `screen` only, and the
script refuses any other value.
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
from hippocampus_foundation.read_run.generator_v2 import (  # noqa: E402
    CELLS,
    generate_episode_v2,
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
        return generate_episode_v2(
            _CONTEXT["seed"],
            config=CELLS[_CONTEXT["cell"]],
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
    parser.add_argument("--cell", required=True, choices=sorted(CELLS))
    parser.add_argument("--split", required=True, choices=ALLOWED_SPLITS)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--gamma", type=float, default=0.4)
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--seed-label", default="track-o-v1-data")
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

    public, _private = write_generated_split_v2(
        master_seed=seed,
        config=CELLS[args.cell],
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
        f"visible {public['visible_sha256'][:19]}"
    )


if __name__ == "__main__":
    main()
