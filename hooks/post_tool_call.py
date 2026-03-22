#!/usr/bin/env python3
"""
hooks/post_tool_call.py
-----------------------
Hook PostToolUse Claude Code — Stratégie 2 (Structured Decoding)

Rôle : Intercepte chaque réponse d'outil APRÈS son exécution.
- Valide la réponse produite contre l'ontologie.
- Si invalide → retourne message d'erreur pour self-correction.
- Journalise toutes les validations.
- Renders a LIVE MINI-MAP after each valid interaction.

Configuration lue depuis ontokit.json.
"""

import json
import sys
import datetime
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ontology_graph import OntologyGraph
from src.validator import OntologyValidator, ValidationResult


def log(msg: str):
    print(f"[PostToolUse] {msg}", file=sys.stderr)


def append_log(log_path: Path, entry: dict):
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Live mini-map (compact, renders inline after each interaction)
# ---------------------------------------------------------------------------

def render_live_map(graph: OntologyGraph, log_path: Path, current_entities: list[str]):
    """Render a compact live map to stderr after each interaction."""
    # Parse full log for visited entities
    visited: Counter = Counter()
    interactions = 0
    if log_path.exists():
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

    total = len(graph.nodes)
    visited_count = len(visited)
    coverage = (visited_count / total * 100) if total > 0 else 0
    name = graph.metadata.get("name", "Ontology")

    # ANSI colors
    G = "\033[92m"   # green
    B = "\033[94m"   # blue
    Y = "\033[93m"   # yellow
    D = "\033[90m"   # dim gray
    W = "\033[97m"   # white
    BOLD = "\033[1m"
    R = "\033[0m"    # reset

    # Coverage bar
    bar_w = 20
    filled = int(coverage / 100 * bar_w)
    bar = f"{B}{'█' * filled}{D}{'░' * (bar_w - filled)}{R}"

    # Current position
    current_labels = []
    for eid in current_entities[:3]:
        node = graph.get_node(eid)
        current_labels.append(node.label if node else eid)
    pos = f" → {G}{', '.join(current_labels)}{R}" if current_labels else ""

    # Edges from current
    edge_strs = []
    for eid in current_entities[:2]:
        for pred, target in graph.get_neighbors_out(eid)[:2]:
            tgt = graph.get_node(target)
            tgt_label = tgt.label if tgt else target
            color = B if target in visited else D
            edge_strs.append(f"  {D}└{R} {G}{graph.get_node(eid).label if graph.get_node(eid) else eid}{R} ─[{Y}{pred}{R}]→ {color}{tgt_label}{R}")

    # Render to stderr (visible in verbose mode)
    print(f"\n{D}┌──────────────────────────────────────────────────┐{R}", file=sys.stderr)
    print(f"{D}│{R} {BOLD}🌍 {name}{R}  {bar} {Y}{coverage:.0f}%{R}  {D}({visited_count}/{total}){R}", file=sys.stderr)
    print(f"{D}│{R} {W}#{interactions}{R}{pos}", file=sys.stderr)
    for es in edge_strs[:3]:
        print(f"{D}│{R}{es}", file=sys.stderr)
    print(f"{D}└──────────────────────────────────────────────────┘{R}\n", file=sys.stderr)


def write_map_file(graph: OntologyGraph, log_path: Path, current_entities: list[str], world_root: Path):
    """Write a plain-text map (no ANSI) to .live_map for Claude to read."""
    visited: Counter = Counter()
    interactions = 0
    if log_path.exists():
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

    total = len(graph.nodes)
    visited_count = len(visited)
    coverage = (visited_count / total * 100) if total > 0 else 0
    name = graph.metadata.get("name", "Ontology")

    bar_w = 20
    filled = int(coverage / 100 * bar_w)
    bar = f"{'█' * filled}{'░' * (bar_w - filled)}"

    current_labels = []
    for eid in current_entities[:3]:
        node = graph.get_node(eid)
        current_labels.append(node.label if node else eid)

    lines = [
        f"┌──────────────────────────────────────────────────┐",
        f"│ 🌍 {name}  {bar} {coverage:.0f}%  ({visited_count}/{total})",
        f"│ #{interactions} → {', '.join(current_labels)}" if current_labels else f"│ #{interactions}",
    ]

    for eid in current_entities[:2]:
        node = graph.get_node(eid)
        label = node.label if node else eid
        for pred, target in graph.get_neighbors_out(eid)[:2]:
            tgt = graph.get_node(target)
            tgt_label = tgt.label if tgt else target
            marker = "🔵" if target in visited else "⚫"
            lines.append(f"│  └ 🟢 {label} ─[{pred}]→ {marker} {tgt_label}")

    lines.append(f"└──────────────────────────────────────────────────┘")

    try:
        with open(world_root / ".live_map", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main hook
# ---------------------------------------------------------------------------

def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        log(f"Cannot parse JSON input: {e}")
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})
    session_id = data.get("session_id", "unknown")

    config = load_config(ROOT)
    ontology_tool_name = config.tool_name
    threshold = config.validation_threshold
    log_path = config.log_path

    if tool_name != ontology_tool_name:
        sys.exit(0)

    try:
        graph = OntologyGraph(config.ontology_path)
        validator = OntologyValidator(graph)
    except Exception as e:
        log(f"Error loading ontology: {e}")
        sys.exit(0)

    ontology_name = graph.metadata.get("name", "Ontology")

    response_to_validate = tool_input if tool_name == ontology_tool_name else tool_response

    if isinstance(response_to_validate, str):
        try:
            response_to_validate = json.loads(response_to_validate)
        except json.JSONDecodeError:
            response_to_validate = {"answer": response_to_validate, "entities_mentioned": [], "supporting_triples": []}

    result: ValidationResult = validator.validate_response(response_to_validate)

    # Log
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "session_id": session_id,
        "tool_name": tool_name,
        "ontology": ontology_name,
        "validation_score": result.score,
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "entities_mentioned": response_to_validate.get("entities_mentioned", []),
        "triple_count": len(response_to_validate.get("supporting_triples", [])),
    }
    append_log(log_path, log_entry)

    # Block if invalid
    if not result.valid and result.score < threshold:
        correction_hints = []
        for c in result.corrections[:5]:
            correction_hints.append(f"  • '{c['invalid']}' → suggestions: {c['suggestions']}")

        error_msg = (
            f"[STRUCTURED DECODING - PostToolUse] Invalid response (score={result.score:.2f}).\n\n"
            f"Errors detected:\n"
            + "\n".join(f"  ❌ {e}" for e in result.errors[:5])
            + (f"\n\nSuggested corrections:\n" + "\n".join(correction_hints) if correction_hints else "")
            + f"\n\nReformulate your response using only valid entities "
            f"and triples from the {ontology_name} ontology."
        )
        print(error_msg, file=sys.stderr)
        sys.exit(2)

    # ─── LIVE MAP ─── renders after every valid interaction
    current_entities = response_to_validate.get("entities_mentioned", [])
    render_live_map(graph, log_path, current_entities)
    write_map_file(graph, log_path, current_entities, ROOT)

    sys.exit(0)


if __name__ == "__main__":
    main()
