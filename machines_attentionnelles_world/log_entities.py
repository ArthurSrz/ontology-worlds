#!/usr/bin/env python3
"""log_entities.py — Record visited ontology entities and refresh the live map.

Usage:
    python3 log_entities.py EntityId1 EntityId2 ...

Called by Claude after every ontology-grounded answer to log which entities
were discussed and update .live_map to reflect exploration progress.
"""
import sys
import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ontology_graph import OntologyGraph
from hooks.post_tool_call import write_map_file, append_log

entities = [e for e in sys.argv[1:] if e]
if not entities:
    print("Usage: python3 log_entities.py EntityId1 EntityId2 ...")
    sys.exit(0)

config = load_config(ROOT)
graph = OntologyGraph(config.ontology_path)

# Validate that entity IDs exist in the graph
valid = [e for e in entities if e in graph.nodes]
unknown = [e for e in entities if e not in graph.nodes]
if unknown:
    print(f"Warning: unknown entities ignored: {unknown}", file=sys.stderr)

if not valid:
    print("No valid entities to log.")
    sys.exit(0)

entry = {
    "timestamp": datetime.datetime.now().isoformat(),
    "session_id": "log_entities",
    "tool_name": "log_entities",
    "ontology": graph.metadata.get("name", "Ontology"),
    "validation_score": 1.0,
    "valid": True,
    "errors": [],
    "warnings": [],
    "entities_mentioned": valid,
    "triple_count": 0,
}
append_log(config.log_path, entry)
write_map_file(graph, config.log_path, valid, ROOT)
print(f"Logged {len(valid)} entities → map updated.")
