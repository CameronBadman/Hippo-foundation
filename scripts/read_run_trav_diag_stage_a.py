"""Stage A of the TRAV edge-selection diagnostic: everything computable
without a trained checkpoint -- the "all available edges" and "DIRECT pool"
populations for section 3 (structural concentration) and section 4 (the
predictive probe), on the official gamma=0 screening domain (2,000 episodes).

Read-only against generated data. No model, no training, no holdout.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from read_run_trav_diag_common import (  # noqa: E402
    FEATURES,
    episode_index,
    features,
    fit_edge_probe,
    kl_divergence,
    probe_report,
    score_edge_probe,
    total_variation,
)

from hippocampus_foundation.read_run.generator import structural_bfs_pool  # noqa: E402
from hippocampus_foundation.read_run.io import read_generated_split  # noqa: E402

SCREEN_ROOT = Path("private/read-run-v1/p0-rerun/screen-g00")
BUDGET = 128


def main() -> None:
    episodes = list(read_generated_split(SCREEN_ROOT))
    assert len(episodes) == 2000, len(episodes)
    fit_set = episodes[0::2]  # 1000 episodes
    score_set = episodes[1::2]  # 1000 episodes

    def population_rows(subset, which: str):
        rows = []
        for episode in subset:
            index = episode_index(episode)
            edge_ids = (
                list(index["by_id"])
                if which == "available"
                else structural_bfs_pool(episode.visible, BUDGET)
            )
            for edge_id in edge_ids:
                label = index["is_target_assertion"][edge_id]
                rows.append((index, edge_id, label))
        return rows

    result: dict[str, object] = {"populations": {}}

    for which in ("available", "direct_pool"):
        fit_rows = population_rows(fit_set, which)
        score_rows = population_rows(score_set, which)
        base_rate = sum(1 for *_r, label in score_rows if label) / len(score_rows)
        probes = {}
        for name in FEATURES:
            model, default, bucket_rates = fit_edge_probe(fit_rows, name)
            correct, total = score_edge_probe(score_rows, name, model, default)
            probes[name] = probe_report(correct, total, base_rate, bucket_rates)
        result["populations"][which] = {
            "fit_edges": len(fit_rows),
            "score_edges": len(score_rows),
            "target_assertion_base_rate": base_rate,
            "probes": probes,
        }

    # Section 3: distribution of DIRECT-pool edges vs all-available edges,
    # per feature, on the SAME episode set (use the full 2000 for the
    # distribution comparison -- no fit/score split needed, it's descriptive).
    all_index = [episode_index(e) for e in episodes]
    dist_available = {name: Counter() for name in FEATURES}
    dist_pool = {name: Counter() for name in FEATURES}
    from read_run_trav_diag_common import bucket

    for episode, index in zip(episodes, all_index, strict=True):
        pool = set(structural_bfs_pool(episode.visible, BUDGET))
        for edge_id in index["by_id"]:
            feats = features(index, edge_id)
            for name in FEATURES:
                dist_available[name][bucket(name, feats[name])] += 1
                if edge_id in pool:
                    dist_pool[name][bucket(name, feats[name])] += 1

    result["direct_pool_vs_available_divergence"] = {
        name: {
            "total_variation": total_variation(dist_pool[name], dist_available[name]),
            "kl_divergence": kl_divergence(dist_pool[name], dist_available[name]),
        }
        for name in FEATURES
    }

    out = Path("private/read-run-v1/diagnostics/trav_edge_selection_stage_a.json")
    out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print("wrote", out)
    print(json.dumps(result, indent=2, sort_keys=True)[:3000])


if __name__ == "__main__":
    main()
