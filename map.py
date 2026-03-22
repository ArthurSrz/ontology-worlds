#!/usr/bin/env python3
"""
map.py — Show where Claude is in the ontology world (terminal view).

Usage:
    python map.py                    # Full map
    python map.py --focus Etalab     # Zoom on a node
    python map.py --browser          # Open interactive HTML view
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ontology_graph import OntologyGraph
from src.world_map import render_map, parse_log


def main():
    parser = argparse.ArgumentParser(description="Show Claude's position in the ontology world")
    parser.add_argument("--focus", "-f", help="Focus on a specific node")
    parser.add_argument("--browser", "-b", action="store_true", help="Open interactive HTML view in browser")
    args = parser.parse_args()

    config = load_config(ROOT)
    graph = OntologyGraph(config.ontology_path)
    log_data = parse_log(config.log_path)

    if args.browser:
        from src.visualize import generate_html
        import webbrowser
        html = generate_html(graph, {
            "visited_entities": log_data["visited"],
            "visited_triples": [],
            "current_entities": log_data["current"],
            "total_interactions": log_data["interactions"],
        })
        out = ROOT / "world_map.html"
        out.write_text(html)
        webbrowser.open(f"file://{out.resolve()}")
        print(f"  Opened {out}")
    else:
        render_map(graph, log_data, focus=args.focus)


if __name__ == "__main__":
    main()
