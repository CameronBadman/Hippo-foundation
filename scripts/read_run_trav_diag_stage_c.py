"""Stage C: corrections to two Stage B measurements that were mis-specified.

1. Section 1's on-path FRACTION is capped at ~4.66% by construction -- episodes
   contain only ~5.97 on-path edges and TRAV examines 128, so the fraction can
   never be high no matter how well it traverses. The informative quantity is
   RECALL: of the on-path edges that exist, how many did TRAV examine?

2. Section 6's ablation zeroed the query *embedding* but left
   `query_similarity_ppm` in the per-edge features (`model.py:141`), which is
   itself query-derived. It therefore did not test "targets from structure
   alone". Three variants are run here to separate the channels.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from read_run_trav_diag_common import episode_index  # noqa: E402

from hippocampus_foundation.read_run.contracts import (
    validate_preregistration,  # noqa: E402
)
from hippocampus_foundation.read_run.evaluation import (  # noqa: E402
    decode_best_routes,
    score_prediction,
)
from hippocampus_foundation.read_run.io import read_generated_split  # noqa: E402
from hippocampus_foundation.read_run.model import (  # noqa: E402
    build_read_model,
    require_torch,
)

CHECKPOINT = "private/read-run-v1/diagnostics/probe-TRAV-checkpoint/checkpoint.pt"
SCREEN = "private/read-run-v1/p0-rerun/screen-g00"
BUDGET = 128
MICROBATCH = 16
CONSTANT_SIMILARITY = 500_000  # midpoint of the ppm range


def run(torch, model, episodes, device, *, zero_query=False):
    out = []
    original = model._query
    if zero_query:
        hidden = model.state_dict()["state_cell.weight_hh"].shape[1]

        def zero(visible_batch):
            return torch.zeros(len(visible_batch), hidden, device=device)

        model._query = zero
    try:
        for start in range(0, len(episodes), MICROBATCH):
            chunk = episodes[start : start + MICROBATCH]
            with torch.no_grad():
                o = model([e.visible for e in chunk], arm="TRAV", budget=BUDGET)
            classes = o["logits"].argmax(dim=1).detach().cpu().tolist()
            rows = o["scores"].detach().float().cpu().tolist()
            for ep, pred, ids, sc in zip(
                chunk, classes, o["edge_ids"], rows, strict=True
            ):
                routes = decode_best_routes(ep.visible, ids, sc)
                out.append(
                    (
                        ep,
                        list(ids),
                        score_prediction(
                            ep, predicted_class=pred, recorded_routes=routes
                        ),
                    )
                )
    finally:
        model._query = original
    return out


def flatten_similarity(episodes):
    out = []
    for ep in episodes:
        c = copy.deepcopy(ep)
        for edge in c.visible["edges"]:
            edge["query_similarity_ppm"] = CONSTANT_SIMILARITY
        out.append(c)
    return out


def accuracy(results):
    na = [r for _e, _i, r in results if not r["abstain"]]
    return sum(r["exact_correct"] for r in na) / len(na), len(na)


def main() -> None:
    torch, _nn, _f = require_torch()
    contracts = validate_preregistration()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_read_model(contracts["training_config"]).to(device)
    saved = torch.load(CHECKPOINT, map_location=device, weights_only=True)
    model.load_state_dict(saved["state_dict"])
    model.eval()

    episodes = list(read_generated_split(Path(SCREEN)))
    result = {}

    baseline = run(torch, model, episodes, device)
    base_acc, n = accuracy(baseline)

    # --- Section 1 corrected: on-path RECALL ---
    recalls, examined_on_path, available_on_path = [], [], []
    for ep, ids, r in baseline:
        if r["abstain"]:
            continue
        idx = episode_index(ep)
        on_path = idx["on_path"]
        hit = sum(1 for e in ids if e in on_path)
        recalls.append(hit / len(on_path))
        examined_on_path.append(hit)
        available_on_path.append(len(on_path))

    def summarize(v):
        s = sorted(v)
        m = len(s)
        return {
            "n": m,
            "mean": sum(s) / m,
            "min": s[0],
            "p25": s[m // 4],
            "median": s[m // 2],
            "p75": s[(3 * m) // 4],
            "max": s[-1],
        }

    result["section_1_corrected_on_path_recall"] = {
        "note": "fraction of the episode's on-path edges that TRAV examined; the "
        "Stage B 'on-path fraction of 128 examined' is capped at ~0.0466 "
        "by construction and is not informative",
        "recall": summarize(recalls),
        "on_path_edges_examined": summarize(examined_on_path),
        "on_path_edges_available": summarize(available_on_path),
    }

    # --- Section 6 corrected: three ablation variants ---
    flat = flatten_similarity(episodes)
    sim_only, _ = accuracy(run(torch, model, flat, device))
    query_only, _ = accuracy(run(torch, model, episodes, device, zero_query=True))
    both, _ = accuracy(run(torch, model, flat, device, zero_query=True))

    result["section_6_corrected_ablations"] = {
        "note": "query_similarity_ppm is a per-edge feature (model.py:141) and "
        "survives zeroing the query embedding, so the Stage B ablation "
        "did not remove query information. Variants separate the channels.",
        "chance_on_non_abstain": 1 / 15,
        "n_non_abstain": n,
        "baseline": base_acc,
        "query_embedding_zeroed_only": query_only,
        "similarity_flattened_only": sim_only,
        "both_ablated": both,
    }

    out = Path("private/read-run-v1/diagnostics/trav_edge_selection_stage_c.json")
    out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
