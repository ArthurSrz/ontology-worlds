#!/usr/bin/env python3
"""
hooks/pre_tool_call.py
----------------------
Hook PreToolUse Claude Code — Stratégie 2 (Structured Decoding)

Rôle : Intercepte chaque appel d'outil AVANT son exécution.
- Si l'outil est une génération de réponse, injecte les contraintes ontologiques.
- Vérifie que les arguments de l'outil ne font pas référence à des entités
  inconnues dans l'ontologie.
- Bloque les appels susceptibles de produire des hallucinations.

Configuration lue depuis ontokit.json (ontology path, tool name).

Format d'entrée (stdin JSON) :
{
    "session_id": "...",
    "tool_name": "...",
    "tool_input": {...}
}

Sortie :
- Exit 0 + JSON sur stdout → tool autorisé (éventuellement avec modifications)
- Exit 2 + message stderr → tool bloqué (Claude voit le message et peut corriger)
"""

import json
import sys
from pathlib import Path

# Ajouter le répertoire src au path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ontology_graph import OntologyGraph
from src.validator import OntologyValidator

# Champs qui doivent contenir des entités ontologiques valides
ENTITY_FIELDS = {"entities_mentioned", "subject", "object", "node_id", "entity_id"}

# Outils système toujours validés (en plus du tool_name configuré)
SYSTEM_TOOLS_TO_VALIDATE = {"Bash", "Write"}


def log(msg: str):
    print(f"[PreToolUse] {msg}", file=sys.stderr)


def check_entity_fields(tool_input: dict, validator: OntologyValidator) -> list[str]:
    """Vérifie récursivement les champs qui devraient contenir des entités valides."""
    errors = []

    def check_value(key: str, value):
        if key not in ENTITY_FIELDS:
            return
        if isinstance(value, str):
            if value and value not in validator.graph.nodes:
                similar = validator.graph.search(value)
                suggestions = [n.id for n in similar[:2]]
                errors.append(
                    f"Field '{key}' contains unknown entity: '{value}'. "
                    f"Suggestions: {suggestions}"
                )
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item and item not in validator.graph.nodes:
                    errors.append(f"Field '{key}' contains unknown entity: '{item}'")

    def recurse(obj, depth=0):
        if depth > 3:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                check_value(k, v)
                recurse(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item, depth + 1)

    recurse(tool_input)
    return errors


def main():
    # Lire l'entrée JSON depuis stdin
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        log(f"Cannot parse JSON input: {e}")
        sys.exit(0)  # Ne pas bloquer si l'entrée est mal formée

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "unknown")

    log(f"session={session_id} tool={tool_name}")

    # Refresh .live_map if the ontology file has been modified
    try:
        from hooks.post_tool_call import refresh_live_map_if_stale
        refresh_live_map_if_stale(ROOT)
    except Exception:
        pass

    # Charger la configuration
    config = load_config(ROOT)
    ontology_tool_name = config.tool_name

    # Construire l'ensemble des outils à valider
    tools_to_validate = {ontology_tool_name} | SYSTEM_TOOLS_TO_VALIDATE

    # Ne valider que les outils listés
    if tool_name not in tools_to_validate:
        sys.exit(0)

    # Charger le graphe
    try:
        graph = OntologyGraph(config.ontology_path)
        validator = OntologyValidator(graph)
    except Exception as e:
        log(f"Error loading ontology: {e}")
        sys.exit(0)  # Ne pas bloquer si l'ontologie est inaccessible

    ontology_name = graph.metadata.get("name", "Ontology")

    # Valider les champs d'entités
    errors = check_entity_fields(tool_input, validator)

    if errors:
        error_msg = (
            f"[STRUCTURED DECODING - PreToolUse] Invalid entities detected before generation.\n"
            + "\n".join(f"  • {e}" for e in errors)
            + f"\n\nValid entities in {ontology_name}: {', '.join(list(graph.nodes.keys())[:20])}..."
            + "\nCorrect the entities and retry."
        )
        print(error_msg, file=sys.stderr)
        sys.exit(2)  # Bloque le tool call

    # Validation des triples si présents
    triples = tool_input.get("supporting_triples", [])
    triple_errors = []
    for t in triples:
        s = t.get("subject", "")
        p = t.get("predicate", "")
        o = t.get("object", "")
        if s and p and o:
            result = validator.validate_triple(s, p, o)
            if not result.valid:
                triple_errors.extend(result.errors)

    if triple_errors:
        error_msg = (
            f"[STRUCTURED DECODING - PreToolUse] Invalid triples in request:\n"
            + "\n".join(f"  • {e}" for e in triple_errors[:5])
            + f"\nCorrect the triples to match the {ontology_name} ontology."
        )
        print(error_msg, file=sys.stderr)
        sys.exit(2)

    log(f"✅ tool={tool_name} — ontological constraints satisfied")
    sys.exit(0)


if __name__ == "__main__":
    main()
