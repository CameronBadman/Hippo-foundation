"""Read Track P against its preregistration: references, paired tests, bands.

Everything the preregistration's outcome table needs, computed here and nowhere
else, so the band assignment is a function of committed code rather than of a
judgement made while looking at numbers.

The comparison the bands rest on is **paired per-episode**, not a difference of
means: for each reference, the fraction of episodes on which the model used no
more expansions than the reference did on that same episode, with a Wilson lower
bound against 0.5. Mean differences are printed as descriptives only.

Cost is read **only on episodes where the model registered both targets**, because
stopping early is free and worthless: a walk that halts immediately is infinitely
cheap and completely wrong, and comparing its cost to anything would be
meaningless.

Two references carry the load:

- `stop_aware` — the best hand-coded policy, relation-gated similarity halting at
  two endpoints, measured in `policy_ladder_v3.json` and recomputed here on the
  screening split so the pairing is episode-by-episode.
- **untrained ordering with an oracle stop** — the same architecture at its
  initialisation, walking on its own scores but halted the moment both targets
  register. This isolates what training bought: an untrained model given a
  perfect stop is the honest floor for the ordering. The degenerate line —
  untrained ordering *and* untrained stop — is reported beside it and never used
  as the reference, because an untrained stop head is close to a coin flip per
  step and flatters anything compared against it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from read_run_learning_probe import wilson_lower_bound  # noqa: E402
from read_run_track_o_probe import load_split  # noqa: E402

from hippocampus_foundation.read_run.model import require_torch  # noqa: E402
from hippocampus_foundation.read_run.model_v3 import build_read_model_v3  # noqa: E402
from hippocampus_foundation.read_run.policies_v3 import (  # noqa: E402
    blind_exhaust_trace,
    oracle_trace,
    policy_row_v3,
    stop_aware_trace,
)

GATED = "hops_2_4"


def _paired(model: list[int], reference: list[int]) -> dict[str, Any]:
    """Fraction of episodes where the model used no more expansions, with a bound."""

    wins = sum(1 for a, b in zip(model, reference, strict=True) if a <= b)
    n = len(model)
    return {
        "n": n,
        "model_no_worse_fraction": wins / n if n else 0.0,
        "wilson_lower_bound": wilson_lower_bound(wins, n),
        "beats_reference": wilson_lower_bound(wins, n) > 0.5,
        "mean_model": sum(model) / n if n else 0.0,
        "mean_reference": sum(reference) / n if n else 0.0,
    }


def walk_stats(
    torch, model, episodes, *, stop_rule: str, stop_decision: str, microbatch: int
) -> list[dict[str, Any]]:
    """Per-episode registration and expansion count for one model configuration."""

    out_rows: list[dict[str, Any]] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(episodes), microbatch):
            chunk = episodes[start : start + microbatch]
            out = model(
                [e.visible for e in chunk],
                stop_rule=stop_rule,
                stop_decision=stop_decision,
            )
            for slot, episode in enumerate(chunk):
                targets = set(episode.hidden["target_nodes"])
                out_rows.append(
                    {
                        "registered": targets <= set(out["endpoints"][slot]),
                        "expansions": out["expansion_count"][slot],
                    }
                )
    return out_rows


def oracle_stopped_stats(
    torch, model, episodes, *, microbatch: int
) -> list[dict[str, Any]]:
    """Untrained (or any) ordering, halted the instant both targets register.

    Runs the walk to exhaustion and then reads the expansion count at the first
    decision point that saw both targets — a stop that cannot be beaten, applied
    to this model's ordering. Episodes where no decision point observed
    completion fall back to the full expansion count, which is the honest cost
    of a walk that only discovered it was done by running out of frontier.
    """

    rows: list[dict[str, Any]] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(episodes), microbatch):
            chunk = episodes[start : start + microbatch]
            out = model([e.visible for e in chunk], stop_rule="exhaust")
            for slot, episode in enumerate(chunk):
                targets = set(episode.hidden["target_nodes"])
                registered = targets <= set(out["endpoints"][slot])
                first = [
                    point.expansions
                    for point in out["decisions"][slot]
                    if targets <= set(point.endpoints)
                ]
                rows.append(
                    {
                        "registered": registered,
                        "expansions": first[0]
                        if first
                        else out["expansion_count"][slot],
                    }
                )
    return rows


def model_free_rows(episodes) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {
        "stop_aware": [],
        "blind_exhaust": [],
        "oracle": [],
    }
    for episode in episodes:
        for name, trace in (
            ("stop_aware", stop_aware_trace(episode.visible)),
            ("blind_exhaust", blind_exhaust_trace(episode.visible)),
            ("oracle", oracle_trace(episode)),
        ):
            row = policy_row_v3(episode, trace)
            out[name].append(
                {
                    "registered": bool(row["targets_registered"]),
                    "expansions": row["expansions"],
                }
            )
    return out


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    registered = sum(r["registered"] for r in rows)
    complete = [r["expansions"] for r in rows if r["registered"]]
    return {
        "n": n,
        "registered_fraction": registered / n if n else 0.0,
        "registered_wilson_lower_bound": wilson_lower_bound(registered, n),
        "expansions_mean_all": sum(r["expansions"] for r in rows) / n if n else 0.0,
        "expansions_mean_when_registered": (
            sum(complete) / len(complete) if complete else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--model-seed", type=int, required=True)
    parser.add_argument("--microbatch", type=int, default=16)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if "holdout" in args.screen_root or "heldout" in args.screen_root:
        raise SystemExit("refusing a holdout path")

    config = json.loads(Path(args.config).read_text())
    torch, _nn, _f = require_torch()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    screening = [
        episode
        for episode, stratum in load_split(Path(args.screen_root))
        if stratum == GATED and not episode.hidden["abstain"]
    ]

    # Trained model, both stop rules.
    torch.manual_seed(args.model_seed)
    trained = build_read_model_v3(config).to(device)
    trained.load_state_dict(
        torch.load(args.checkpoint, map_location=device)["state_dict"]
    )

    # Untrained, same seed and therefore the same initialisation the run began at.
    torch.manual_seed(args.model_seed)
    untrained = build_read_model_v3(config).to(device)

    arms: dict[str, list[dict[str, Any]]] = {}
    for rule in ("probability", "logit_margin"):
        arms[f"trained_{rule}"] = walk_stats(
            torch,
            trained,
            screening,
            stop_rule="learned",
            stop_decision=rule,
            microbatch=args.microbatch,
        )
    arms["trained_oracle_stop"] = oracle_stopped_stats(
        torch, trained, screening, microbatch=args.microbatch
    )
    arms["untrained_oracle_stop"] = oracle_stopped_stats(
        torch, untrained, screening, microbatch=args.microbatch
    )
    arms["untrained_own_stop"] = walk_stats(
        torch,
        untrained,
        screening,
        stop_rule="learned",
        stop_decision="probability",
        microbatch=args.microbatch,
    )
    arms.update(model_free_rows(screening))

    summaries = {name: summarise(rows) for name, rows in arms.items()}

    # Paired comparisons, on episodes the model completed — cost is only
    # meaningful where the walk actually found both targets.
    primary = arms["trained_probability"]
    keep = [i for i, r in enumerate(primary) if r["registered"]]
    paired = {}
    for reference in (
        "stop_aware",
        "untrained_oracle_stop",
        "blind_exhaust",
        "oracle",
    ):
        paired[reference] = _paired(
            [primary[i]["expansions"] for i in keep],
            [arms[reference][i]["expansions"] for i in keep],
        )

    record = {
        "record_kind": "read_run_track_p_report",
        "cell": args.cell,
        "model_seed": args.model_seed,
        "checkpoint": args.checkpoint,
        "gated_stratum": GATED,
        "screening_episodes": len(screening),
        "cost_compared_on_completed_episodes": len(keep),
        "summaries": summaries,
        "paired_vs_references": paired,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))

    print(f"\n{args.cell} seed {args.model_seed}  (n={len(screening)} gated)")
    print(f"  {'arm':26s} {'reg':>6s} {'regLB':>6s} {'exp(all)':>9s} {'exp(reg)':>9s}")
    for name in (
        "trained_probability",
        "trained_logit_margin",
        "trained_oracle_stop",
        "untrained_oracle_stop",
        "untrained_own_stop",
        "stop_aware",
        "blind_exhaust",
        "oracle",
    ):
        s = summaries[name]
        w = s["expansions_mean_when_registered"]
        print(
            f"  {name:26s} {s['registered_fraction']:6.3f} "
            f"{s['registered_wilson_lower_bound']:6.3f} "
            f"{s['expansions_mean_all']:9.3f} "
            f"{(f'{w:9.3f}' if w is not None else '        -')}"
        )
    print(f"\n  paired, on the {len(keep)} episodes the model completed:")
    for name, p in paired.items():
        print(
            f"    vs {name:24s} model_no_worse={p['model_no_worse_fraction']:.3f} "
            f"LB={p['wilson_lower_bound']:.3f} beats={p['beats_reference']} "
            f"({p['mean_model']:.2f} vs {p['mean_reference']:.2f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
