"""
world_map.py
------------
Terminal-based visualization of Claude Code's position in the ontology world.

Renders directly in the terminal — no browser needed.
Shows visited nodes, current focus, coverage, and the graph neighborhood.

Usage:
    python -m src.world_map              # Full map
    python -m src.world_map --focus Etalab   # Zoom on a node
"""

from __future__ import annotations
import json
import sys
from collections import Counter
from pathlib import Path

from .config import load_config
from .ontology_graph import OntologyGraph


# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"
    WHITE = "\033[97m"
    BG_GREEN = "\033[42m"
    BG_BLUE = "\033[44m"
    BG_GRAY = "\033[100m"


def parse_log(log_path: Path) -> dict:
    visited: Counter = Counter()
    current: set = set()
    interactions = 0

    if not log_path.exists():
        return {"visited": visited, "current": current, "interactions": 0}

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            interactions += 1
            for eid in entry.get("entities_mentioned", []):
                visited[eid] += 1
            current = set(entry.get("entities_mentioned", []))

    return {"visited": visited, "current": current, "interactions": interactions}


def render_map(graph: OntologyGraph, log_data: dict, focus: str | None = None):
    meta = graph.metadata
    name = meta.get("name", "Ontology")
    visited = log_data["visited"]
    current = log_data["current"]
    interactions = log_data["interactions"]

    total = len(graph.nodes)
    visited_count = len(visited)
    coverage = (visited_count / total * 100) if total > 0 else 0

    # Header
    print(f"\n{C.BOLD}{'─' * 60}{C.RESET}")
    print(f"  {C.BOLD}🌍 {name}{C.RESET}  —  World Map")
    print(f"{'─' * 60}")

    # Coverage bar
    bar_width = 40
    filled = int(coverage / 100 * bar_width)
    bar = f"{C.BLUE}{'█' * filled}{C.GRAY}{'░' * (bar_width - filled)}{C.RESET}"
    print(f"\n  Coverage: {bar} {C.YELLOW}{coverage:.0f}%{C.RESET}")
    print(f"  {C.DIM}Visited: {visited_count}/{total} nodes  |  Interactions: {interactions}{C.RESET}")

    # Legend
    print(f"\n  {C.BG_GREEN} {C.RESET} {C.GREEN}Current focus{C.RESET}   "
          f"{C.BG_BLUE} {C.RESET} {C.BLUE}Visited{C.RESET}   "
          f"{C.BG_GRAY} {C.RESET} {C.GRAY}Unvisited{C.RESET}")

    # Class-by-class view
    print(f"\n{C.BOLD}{'─' * 60}{C.RESET}")

    classes_to_show = {}
    for node_id, node in graph.nodes.items():
        if node_id in graph.classes:
            continue
        cls = node.cls
        if cls not in classes_to_show:
            classes_to_show[cls] = []
        classes_to_show[cls].append(node)

    for cls_id, instances in sorted(classes_to_show.items()):
        cls_node = graph.get_node(cls_id)
        cls_label = cls_node.label if cls_node else cls_id
        print(f"\n  {C.BOLD}{C.CYAN}◆ {cls_label}{C.RESET} {C.DIM}({len(instances)}){C.RESET}")

        for node in sorted(instances, key=lambda n: -visited.get(n.id, 0)):
            nid = node.id
            count = visited.get(nid, 0)

            if nid in current:
                marker = f"{C.GREEN}●{C.RESET}"
                label = f"{C.GREEN}{C.BOLD}{node.label}{C.RESET}"
                suffix = f" {C.GREEN}← HERE{C.RESET}"
            elif count > 0:
                marker = f"{C.BLUE}●{C.RESET}"
                label = f"{C.BLUE}{node.label}{C.RESET}"
                suffix = f" {C.DIM}({count}x){C.RESET}"
            else:
                marker = f"{C.GRAY}○{C.RESET}"
                label = f"{C.GRAY}{node.label}{C.RESET}"
                suffix = ""

            # Show edges for visited or focused nodes
            edges_str = ""
            if count > 0 or nid in current:
                out_edges = graph.get_neighbors_out(nid)
                if out_edges:
                    edge_parts = []
                    for pred, target in out_edges[:3]:
                        tgt = graph.get_node(target)
                        tgt_label = tgt.label if tgt else target
                        if target in visited:
                            edge_parts.append(f"{C.BLUE}─[{pred}]→ {tgt_label}{C.RESET}")
                        else:
                            edge_parts.append(f"{C.GRAY}─[{pred}]→ {tgt_label}{C.RESET}")
                    edges_str = "\n" + "\n".join(f"      {C.DIM}└{C.RESET} {e}" for e in edge_parts)

            print(f"    {marker} {label}{suffix}{edges_str}")

    # Focus mode: show full neighborhood
    if focus:
        node = graph.get_node(focus)
        if node:
            print(f"\n{C.BOLD}{'─' * 60}{C.RESET}")
            print(f"  {C.BOLD}🔍 Focus: {node.label}{C.RESET}")
            if node.wikidata:
                print(f"  {C.DIM}Wikidata: {node.wikidata}{C.RESET}")
            if node.description:
                print(f"  {C.DIM}{node.description[:80]}{C.RESET}")

            subgraph = graph.subgraph_around(focus, depth=1)
            print(f"\n  {C.BOLD}Neighborhood:{C.RESET}")
            for edge in subgraph["edges"]:
                src_node = graph.get_node(edge["subject"])
                tgt_node = graph.get_node(edge["object"])
                src = src_node.label if src_node else edge["subject"]
                tgt = tgt_node.label if tgt_node else edge["object"]
                pred = edge["predicate"]

                src_color = C.GREEN if edge["subject"] in current else (C.BLUE if edge["subject"] in visited else C.GRAY)
                tgt_color = C.GREEN if edge["object"] in current else (C.BLUE if edge["object"] in visited else C.GRAY)

                print(f"    {src_color}{src}{C.RESET} ─[{C.YELLOW}{pred}{C.RESET}]→ {tgt_color}{tgt}{C.RESET}")

    print(f"\n{C.BOLD}{'─' * 60}{C.RESET}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Terminal world map")
    parser.add_argument("--focus", "-f", help="Focus on a specific node")
    args = parser.parse_args()

    root = Path.cwd()
    config = load_config(root)
    graph = OntologyGraph(config.ontology_path)
    log_data = parse_log(config.log_path)

    render_map(graph, log_data, focus=args.focus)


if __name__ == "__main__":
    main()
