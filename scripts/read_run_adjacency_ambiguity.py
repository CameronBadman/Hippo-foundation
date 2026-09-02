"""Can the reader's inputs even tell which edges are adjacent?

`model.py::_edge_batch` encodes each edge as (source assertion mask, target
assertion mask, relation embedding, query state, similarity scalar). No node
identifier of any kind enters the tensor. So for a set reader such as DIRECT,
chaining edge A to edge B requires inferring `target(A) == source(B)` from a
4-bit assertion mask, and a relation-matching path can only be composed as far
as that inference is unique.

This script measures how ambiguous the inference is on the real screening
split, gated `hops_2_4` non-abstain: for each step of each planted route it
counts the pool edges that are indistinguishable from the true continuation
under the model's own view, `(source mask, relation)`. Read-only, structural,
no model, no checkpoint, no holdout. Cited by
`docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md` §2.9.
"""

from collections import Counter
from pathlib import Path
from statistics import median

from hippocampus_foundation.read_run.coverage import node_assertion_masks
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.generator import structural_bfs_pool
from hippocampus_foundation.read_run.io import read_generated_split

BUDGET = 128
fanout, nodes_in_pool, masks_in_pool, true_share, last_rel = [], [], [], [], []
episodes = 0
for episode in read_generated_split(Path("private/read-run-v1/p0-rerun/screen-g00")):
    hidden, visible = episode.hidden, episode.visible
    if hidden["abstain"]:
        continue
    if coverage_stratum(target_hop_distance(episode)) != "hops_2_4":
        continue
    episodes += 1
    pool = set(structural_bfs_pool(visible, BUDGET))
    masks = node_assertion_masks(visible)
    edges = {e["edge_id"]: e for e in visible["edges"]}
    pooled = [edges[i] for i in pool]
    touched = {e["source"] for e in pooled} | {e["target"] for e in pooled}
    nodes_in_pool.append(len(touched))
    masks_in_pool.append(len({masks[n] for n in touched}))
    q = visible["query_relations"]
    # How many pool edges could be the true continuation, judged only on
    # (source mask, relation) — the model's own view of adjacency?
    for route in hidden["valid_routes"]:
        for step, edge_id in enumerate(route[:-1]):
            edge = edges[edge_id]
            want_mask, want_rel = masks[edge["target"]], q[step + 1]
            candidates = [
                e
                for e in pooled
                if e["relation"] == want_rel and masks[e["source"]] == want_mask
            ]
            fanout.append(len(candidates))
    # Nodes sharing the target's mask, and edges matching the final relation.
    for t in hidden["target_nodes"]:
        true_share.append(sum(1 for n in touched if masks[n] == masks[t]))
    last_rel.append(sum(1 for e in pooled if e["relation"] == q[-1]))


def stats(name, xs):
    c = Counter(xs)
    print(
        f"{name}: n={len(xs)} min={min(xs)} median={median(xs)} mean={sum(xs) / len(xs):.2f} "
        f"max={max(xs)} p_exactly_one={c[1] / len(xs):.4f}"
    )


print(f"gated non-abstain episodes: {episodes}")
stats("adjacency fan-out (candidate continuations by mask+relation)", fanout)
stats("distinct nodes touched by the 128-edge pool", nodes_in_pool)
stats("distinct assertion masks among them", masks_in_pool)
stats("nodes sharing the target node's mask", true_share)
stats("pool edges carrying the query's last relation", last_rel)
