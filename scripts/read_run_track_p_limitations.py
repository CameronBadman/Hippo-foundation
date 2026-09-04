"""The two measurements Track P's report needs that its preregistration did not ask for.

Both were found after the runs and both change how a number in the report should
be read, so they are computed here from the committed checkpoints rather than
quoted from an interactive session.

**1. Selective return on the whole distribution, split by abstain.** The
preregistration screened on non-abstain episodes, inherited from Track O. For
traversal that is harmless. For selective return it is not: the generator gives the
two targets a shared assertion mask exactly when the episode is non-abstain, so on
the screened subset a zero-parameter rule — return the largest group of candidate
routes whose endpoints share a mask — is the answer. This script reports the
trained model's per-edge rule, the constant-free route-mean rule, and that mask
rule on non-abstain and abstain episodes separately, so the shortcut is visible as
a split rather than hidden by a filter.

**2. Strict win / tie / loss against each reference.** The preregistered cost
comparison counts "model expansions ≤ reference" as a win. Ties are common (the
walks often take the same number of expansions), so that proportion can exceed
0.5 while the model is worse on the mean. The three-way breakdown is what the
proportion actually contains.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hippocampus_foundation.read_run.evaluation_v3 import (
    decode_all_routes,  # noqa: E402
)
from hippocampus_foundation.read_run.gates import (  # noqa: E402
    coverage_stratum,
    target_hop_distance,
)
from hippocampus_foundation.read_run.io_v2 import read_generated_split_v2  # noqa: E402
from hippocampus_foundation.read_run.model import require_torch  # noqa: E402
from hippocampus_foundation.read_run.model_v3 import build_read_model_v3  # noqa: E402
from hippocampus_foundation.read_run.policies_v3 import (  # noqa: E402
    policy_row_v3,
    stop_aware_trace,
)

GATED = "hops_2_4"


def _rules(episode, edge_ids, scores) -> dict[str, bool]:
    """Three constant-free decode rules; True when the returned set is exactly the targets."""

    by_id = {edge["edge_id"]: edge for edge in episode.visible["edges"]}
    masks = {
        node["node"]: sum(1 << bit for bit in node["assertions"])
        for node in episode.visible["nodes"]
    }
    gold = {tuple(route) for route in episode.hidden["valid_routes"]}
    score = dict(zip(edge_ids, scores, strict=True))

    kept = [edge_id for edge_id in edge_ids if score[edge_id] > 0.0]
    per_edge = {
        tuple(r) for r in decode_all_routes(episode.visible, kept, [0.0] * len(kept))
    }
    candidates = [
        tuple(r)
        for r in decode_all_routes(episode.visible, edge_ids, [0.0] * len(edge_ids))
    ]

    def mean(route):
        return sum(score[e] for e in route) / len(route)

    route_mean = {r for r in candidates if mean(r) > 0.0}
    groups: dict[int, list] = {}
    for route in candidates:
        groups.setdefault(masks[by_id[route[-1]]["target"]], []).append(route)
    multi = [g for g in groups.values() if len(g) >= 2]
    mask_group = (
        set(max(multi, key=lambda g: (len(g), sum(mean(r) for r in g))))
        if multi
        else set()
    )
    return {
        "per_edge_gt0": per_edge == gold,
        "route_mean_gt0": route_mean == gold,
        "largest_mask_group": mask_group == gold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--microbatch", type=int, default=16)
    args = parser.parse_args()
    for path in (args.runs_root, args.data_root):
        if "holdout" in path or "heldout" in path:
            raise SystemExit("refusing a holdout path")

    config = json.loads(Path(args.config).read_text())
    torch, _nn, _f = require_torch()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    record: dict[str, Any] = {"record_kind": "read_run_track_p_limitations", "runs": {}}

    for cell in ("deg6_len8_v4_rep-k1", "deg3_len6_v8-k1"):
        episodes = [
            e
            for e in read_generated_split_v2(Path(args.data_root) / cell / "screen")
            if coverage_stratum(target_hop_distance(e)) == GATED
        ]
        stop_aware = [
            policy_row_v3(e, stop_aware_trace(e.visible))["expansions"]
            for e in episodes
        ]
        for seed in (1729, 2718, 3141):
            name = f"probe-TRAVP-{cell}-s{seed}"
            checkpoint = Path(args.runs_root) / name / "checkpoint.pt"
            if not checkpoint.exists():
                record["runs"][name] = {"missing": True}
                continue
            torch.manual_seed(seed)
            model = build_read_model_v3(config).to(device)
            model.load_state_dict(
                torch.load(checkpoint, map_location=device)["state_dict"]
            )
            torch.manual_seed(seed)
            untrained = build_read_model_v3(config).to(device)

            split: dict[str, dict[str, int]] = {
                "non_abstain": {"n": 0},
                "abstain": {"n": 0},
            }
            registered: list[bool] = []
            model_exp: list[int] = []
            untrained_exp: list[int] = []
            model.eval()
            untrained.eval()
            with torch.no_grad():
                for start in range(0, len(episodes), args.microbatch):
                    chunk = episodes[start : start + args.microbatch]
                    visible = [e.visible for e in chunk]
                    out = model(
                        visible, stop_rule="learned", stop_decision="probability"
                    )
                    ex = untrained(visible, stop_rule="exhaust")
                    for slot, episode in enumerate(chunk):
                        targets = set(episode.hidden["target_nodes"])
                        bucket = split[
                            "abstain" if episode.hidden["abstain"] else "non_abstain"
                        ]
                        bucket["n"] += 1
                        ids = out["edge_ids"][slot]
                        scores = out["scores"][slot][: len(ids)].tolist()
                        for rule, hit in _rules(episode, ids, scores).items():
                            bucket[rule] = bucket.get(rule, 0) + int(hit)
                        registered.append(targets <= set(out["endpoints"][slot]))
                        model_exp.append(out["expansion_count"][slot])
                        first = [
                            p.expansions
                            for p in ex["decisions"][slot]
                            if targets <= set(p.endpoints)
                        ]
                        untrained_exp.append(
                            first[0] if first else ex["expansion_count"][slot]
                        )

            keep = [i for i, r in enumerate(registered) if r]

            def breakdown(
                reference: list[int],
                keep: list[int] = keep,
                model_exp: list[int] = model_exp,
            ) -> dict[str, Any]:
                better = sum(1 for i in keep if model_exp[i] < reference[i])
                tie = sum(1 for i in keep if model_exp[i] == reference[i])
                worse = sum(1 for i in keep if model_exp[i] > reference[i])
                n = len(keep) or 1
                return {
                    "n": len(keep),
                    "strictly_better": better / n,
                    "tie": tie / n,
                    "strictly_worse": worse / n,
                    "preregistered_no_worse": (better + tie) / n,
                    "mean_model": sum(model_exp[i] for i in keep) / n,
                    "mean_reference": sum(reference[i] for i in keep) / n,
                }

            record["runs"][name] = {
                "cell": cell,
                "seed": seed,
                "selection_by_abstain": {
                    k: {
                        "n": v["n"],
                        **{
                            rule: v.get(rule, 0) / v["n"]
                            for rule in (
                                "per_edge_gt0",
                                "route_mean_gt0",
                                "largest_mask_group",
                            )
                        },
                    }
                    for k, v in split.items()
                },
                "cost_breakdown": {
                    "vs_stop_aware": breakdown(stop_aware),
                    "vs_untrained_oracle_stop": breakdown(untrained_exp),
                },
            }
            s = record["runs"][name]
            na, ab = (
                s["selection_by_abstain"]["non_abstain"],
                s["selection_by_abstain"]["abstain"],
            )
            b = s["cost_breakdown"]["vs_stop_aware"]
            print(
                f"{name:34s} proof per-edge {na['per_edge_gt0']:.3f}/{ab['per_edge_gt0']:.3f}  "
                f"route-mean {na['route_mean_gt0']:.3f}/{ab['route_mean_gt0']:.3f}  "
                f"mask-group {na['largest_mask_group']:.3f}/{ab['largest_mask_group']:.3f}  "
                f"| vs stop_aware better/tie/worse {b['strictly_better']:.3f}/{b['tie']:.3f}/{b['strictly_worse']:.3f}",
                flush=True,
            )
    Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
