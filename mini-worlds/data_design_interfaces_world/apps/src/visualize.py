"""
visualize.py
------------
Live visualization of Claude Code's position in the ontology world.

Generates an interactive graph (vis-network) that highlights:
- 🔵 Visited nodes (entities Claude has mentioned)
- 🟢 Current focus (most recent interaction)
- 🔴 Unvisited nodes (not yet explored)
- Bold edges = traversed triples

Usage:
    python -m src.visualize                  # Generate + open in browser
    python -m src.visualize --serve          # Live server with auto-refresh
    python -m src.visualize --output map.html  # Save to file
"""

from __future__ import annotations
import argparse
import json
import sys
import webbrowser
from collections import Counter
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from .config import load_config
from .ontology_graph import OntologyGraph


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def parse_validation_log(log_path: Path) -> dict[str, Any]:
    """Parse validation_log.jsonl and extract visited entities + triples."""
    visited_entities: Counter = Counter()
    visited_triples: list[tuple[str, str, str]] = []
    current_entities: set[str] = set()
    total_interactions = 0

    if not log_path.exists():
        return {
            "visited_entities": visited_entities,
            "visited_triples": visited_triples,
            "current_entities": current_entities,
            "total_interactions": 0,
        }

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            total_interactions += 1
            entities = entry.get("entities_mentioned", [])
            for eid in entities:
                visited_entities[eid] += 1

            # Track current (most recent) entities
            current_entities = set(entities)

    return {
        "visited_entities": visited_entities,
        "visited_triples": visited_triples,
        "current_entities": current_entities,
        "total_interactions": total_interactions,
    }


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(graph: OntologyGraph, log_data: dict, auto_refresh: bool = False) -> str:
    """Generate a self-contained HTML file with interactive graph visualization."""
    meta = graph.metadata
    name = meta.get("name", "Ontology")
    visited = log_data["visited_entities"]
    current = log_data["current_entities"]
    total_interactions = log_data["total_interactions"]

    # Build vis.js nodes
    vis_nodes = []
    for node_id, node in graph.nodes.items():
        visit_count = visited.get(node_id, 0)
        is_current = node_id in current
        is_class = node_id in graph.classes

        if is_current:
            color = "#22c55e"  # green — current focus
            border_color = "#16a34a"
            font_color = "#ffffff"
            size = 30
        elif visit_count > 0:
            # Intensity scales with visit count
            intensity = min(visit_count / max(max(visited.values(), default=1), 1), 1.0)
            r = int(59 + (96 - 59) * (1 - intensity))
            g = int(130 + (165 - 130) * (1 - intensity))
            b = int(246 + (246 - 246) * (1 - intensity))
            color = f"#{r:02x}{g:02x}{b:02x}"
            border_color = "#3b82f6"
            font_color = "#ffffff"
            size = 18 + visit_count * 4
        elif is_class:
            color = "#374151"  # dark gray — class node
            border_color = "#6b7280"
            font_color = "#d1d5db"
            size = 22
        else:
            color = "#1f2937"  # very dark — unvisited
            border_color = "#374151"
            font_color = "#6b7280"
            size = 14

        label = node.label if len(node.label) < 25 else node.label[:22] + "..."
        title_parts = [f"<b>{node.label}</b>", f"ID: {node_id}", f"Class: {node.cls}"]
        if node.wikidata:
            title_parts.append(f"Wikidata: {node.wikidata}")
        if visit_count > 0:
            title_parts.append(f"Visited: {visit_count}x")
        if node.description:
            title_parts.append(f"<i>{node.description[:80]}</i>")
        title = "<br>".join(title_parts)

        shape = "diamond" if is_class else "dot"

        vis_nodes.append({
            "id": node_id,
            "label": label,
            "title": title,
            "color": {"background": color, "border": border_color, "highlight": {"background": "#f59e0b", "border": "#d97706"}},
            "font": {"color": font_color, "size": 12},
            "size": size,
            "shape": shape,
            "borderWidth": 3 if is_current else (2 if visit_count > 0 else 1),
        })

    # Build vis.js edges
    vis_edges = []
    visited_entity_set = set(visited.keys())
    for subject, predicate, obj in graph.edges:
        is_traversed = subject in visited_entity_set and obj in visited_entity_set
        vis_edges.append({
            "from": subject,
            "to": obj,
            "label": predicate,
            "font": {"size": 9, "color": "#9ca3af", "strokeWidth": 0},
            "color": {"color": "#3b82f6" if is_traversed else "#374151", "opacity": 0.8 if is_traversed else 0.3},
            "width": 2.5 if is_traversed else 0.8,
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.5}},
            "smooth": {"type": "curvedCW", "roundness": 0.2},
        })

    # Stats
    total_nodes = len(graph.nodes)
    visited_count = len(visited)
    coverage = (visited_count / total_nodes * 100) if total_nodes > 0 else 0

    refresh_script = """
        <script>
        setTimeout(function() { location.reload(); }, 3000);
        </script>
    """ if auto_refresh else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{name} — Ontology World Map</title>
    <script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0f172a; color: #e2e8f0; font-family: 'SF Mono', 'Fira Code', monospace; }}
        #header {{
            padding: 16px 24px;
            background: #1e293b;
            border-bottom: 1px solid #334155;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        #header h1 {{ font-size: 18px; font-weight: 600; }}
        #header h1 span {{ color: #3b82f6; }}
        #stats {{
            display: flex;
            gap: 24px;
            font-size: 13px;
        }}
        .stat {{ display: flex; align-items: center; gap: 6px; }}
        .stat .dot {{ width: 10px; height: 10px; border-radius: 50%; }}
        .dot-current {{ background: #22c55e; }}
        .dot-visited {{ background: #3b82f6; }}
        .dot-unvisited {{ background: #374151; }}
        .dot-class {{ background: #374151; border: 2px solid #6b7280; width: 10px; height: 10px;
                      transform: rotate(45deg); border-radius: 0; }}
        #coverage {{
            background: #1e293b;
            padding: 4px 12px;
            border-radius: 12px;
            border: 1px solid #334155;
            font-size: 13px;
        }}
        #coverage strong {{ color: #f59e0b; }}
        #graph {{ width: 100%; height: calc(100vh - 56px); }}
    </style>
    {refresh_script}
</head>
<body>
    <div id="header">
        <h1><span>&#x1f30d;</span> {name}</h1>
        <div id="stats">
            <div class="stat"><div class="dot dot-current"></div> Current focus</div>
            <div class="stat"><div class="dot dot-visited"></div> Visited ({visited_count})</div>
            <div class="stat"><div class="dot dot-unvisited"></div> Unvisited ({total_nodes - visited_count})</div>
            <div class="stat"><div class="dot dot-class"></div> Class</div>
        </div>
        <div id="coverage">
            Coverage: <strong>{coverage:.0f}%</strong> &nbsp;|&nbsp;
            Interactions: <strong>{total_interactions}</strong>
        </div>
    </div>
    <div id="graph"></div>
    <script>
        var nodes = new vis.DataSet({json.dumps(vis_nodes)});
        var edges = new vis.DataSet({json.dumps(vis_edges)});
        var container = document.getElementById('graph');
        var data = {{ nodes: nodes, edges: edges }};
        var options = {{
            physics: {{
                solver: 'forceAtlas2Based',
                forceAtlas2Based: {{
                    gravitationalConstant: -80,
                    centralGravity: 0.01,
                    springLength: 120,
                    springConstant: 0.04,
                    damping: 0.5,
                    avoidOverlap: 0.5
                }},
                stabilization: {{ iterations: 200 }},
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 100,
                zoomView: true,
                dragView: true,
            }},
            layout: {{ improvedLayout: true }},
        }};
        var network = new vis.Network(container, data, options);

        // Zoom to visited nodes on load
        var visitedIds = {json.dumps(list(visited.keys()))};
        if (visitedIds.length > 0) {{
            network.once('stabilizationIterationsDone', function() {{
                network.fit({{ nodes: visitedIds, animation: true }});
            }});
        }}
    </script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Visualize Claude's position in the ontology world")
    parser.add_argument("--serve", action="store_true", help="Start live server with auto-refresh (every 3s)")
    parser.add_argument("--output", "-o", default="world_map.html", help="Output HTML file (default: world_map.html)")
    parser.add_argument("--port", type=int, default=8765, help="Server port (default: 8765)")
    args = parser.parse_args()

    root = Path.cwd()
    config = load_config(root)
    graph = OntologyGraph(config.ontology_path)
    log_data = parse_validation_log(config.log_path)

    meta = graph.metadata
    name = meta.get("name", "Ontology")

    html = generate_html(graph, log_data, auto_refresh=args.serve)

    output_path = root / args.output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    summary = graph.summary()
    visited_count = len(log_data["visited_entities"])
    coverage = (visited_count / summary["total_nodes"] * 100) if summary["total_nodes"] > 0 else 0

    print(f"\n🗺️  World Map: {name}")
    print(f"   Nodes: {summary['total_nodes']}  |  Visited: {visited_count}  |  Coverage: {coverage:.0f}%")
    print(f"   Interactions: {log_data['total_interactions']}")

    if args.serve:
        print(f"\n   Live server: http://localhost:{args.port}/{args.output}")
        print(f"   Auto-refreshes every 3 seconds. Ctrl+C to stop.\n")

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *a): pass

        server = HTTPServer(("", args.port), QuietHandler)
        webbrowser.open(f"http://localhost:{args.port}/{args.output}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n   Server stopped.")
    else:
        print(f"   File: {output_path}")
        webbrowser.open(f"file://{output_path.resolve()}")


if __name__ == "__main__":
    main()
