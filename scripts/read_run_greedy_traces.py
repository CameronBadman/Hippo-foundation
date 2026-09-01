"""Traces for the episodes where the greedy baseline fails B2's threshold.

B2 asserted that a similarity-greedy walk must reach ~100% at gamma=0 because
greedy is optimal there by construction. It reaches 82.65%. These traces show
which of the two premises in that sentence holds and which does not.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hippocampus_foundation.read_run.coverage import (
    route_coverage,
)
from hippocampus_foundation.read_run.gates import coverage_stratum, target_hop_distance
from hippocampus_foundation.read_run.greedy import greedy_examined_set
from hippocampus_foundation.read_run.io import read_generated_split


def trace(episode: Any, budget: int) -> dict[str, Any]:
    visible = episode.visible
    examined = greedy_examined_set(visible, budget)
    cov = route_coverage(episode, examined)
    reached = set(cov["endpoints_reached"])
    targets = set(cov["targets"])
    missed = sorted(targets - reached)

    routes = [list(route) for route in episode.hidden["valid_routes"]]
    by_id = {edge["edge_id"]: edge for edge in visible["edges"]}
    examined_set = set(examined)

    # For each valid route, which of its edges the greedy walk never examined,
    # and what similarity those edges carried relative to their sibling set.
    route_detail = []
    for route in routes:
        endpoint = by_id[route[-1]]["target"]
        missing = [e for e in route if e not in examined_set]
        detail = {
            "endpoint": endpoint,
            "endpoint_missed": endpoint in missed,
            "edges": len(route),
            "missing_edges": missing,
            "first_missing_depth": (route.index(missing[0]) if missing else None),
        }
        if missing:
            first = by_id[missing[0]]
            siblings = [
                edge for edge in visible["edges"] if edge["source"] == first["source"]
            ]
            best = max(siblings, key=lambda e: e["query_similarity_ppm"])
            detail["first_missing_edge"] = {
                "edge_id": first["edge_id"],
                "source": first["source"],
                "similarity_ppm": first["query_similarity_ppm"],
                "best_sibling_edge_id": best["edge_id"],
                "best_sibling_similarity_ppm": best["query_similarity_ppm"],
                "source_node_was_expanded": any(
                    by_id[e]["source"] == first["source"] for e in examined
                ),
                "lost_to_a_900k_sibling": best["query_similarity_ppm"] == 900_000
                and best["edge_id"] != first["edge_id"],
            }
        route_detail.append(detail)

    return {
        "episode_id": visible.get("episode_id"),
        "stratum": coverage_stratum(target_hop_distance(episode)),
        "abstain": episode.hidden["abstain"],
        "budget": budget,
        "examined_count": len(examined),
        "total_edges": len(visible["edges"]),
        "query_path_length": len(visible["query_relations"]),
        "target_count": len(targets),
        "targets": sorted(targets),
        "endpoints_reached": sorted(reached),
        "missed_targets": missed,
        "reaches_some_target": cov["reaches_some_target"],
        "route_complete": cov["route_complete"],
        "target_node_present": cov["target_node_present"],
        "routes": route_detail,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen-root", required=True)
    parser.add_argument("--budget", type=int, default=128)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    failures: list[dict[str, Any]] = []
    scanned = 0
    summary = {
        "reached_none": 0,
        "reached_one_of_two": 0,
        "lost_to_900k_sibling": 0,
        "source_never_expanded": 0,
    }
    for episode in read_generated_split(Path(args.screen_root)):
        stratum = coverage_stratum(target_hop_distance(episode))
        if stratum != "hops_2_4" or episode.hidden["abstain"]:
            continue
        scanned += 1
        row = trace(episode, args.budget)
        if row["route_complete"]:
            continue
        if not row["reaches_some_target"]:
            summary["reached_none"] += 1
        else:
            summary["reached_one_of_two"] += 1
        for detail in row["routes"]:
            edge = detail.get("first_missing_edge")
            if not edge:
                continue
            if edge["lost_to_a_900k_sibling"]:
                summary["lost_to_900k_sibling"] += 1
            if not edge["source_node_was_expanded"]:
                summary["source_never_expanded"] += 1
        if len(failures) < args.limit:
            failures.append(row)

    result = {
        "budget": args.budget,
        "gated_non_abstain_scanned": scanned,
        "failure_summary": summary,
        "traces": failures,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result["failure_summary"], indent=2))
    print("traces written:", len(failures), "->", args.output)
    for row in failures[:3]:
        print(json.dumps(row, indent=1)[:900])


if __name__ == "__main__":
    main()
