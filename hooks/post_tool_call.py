#!/usr/bin/env python3
"""
hooks/post_tool_call.py
-----------------------
Hook PostToolUse Claude Code — Stratégie 2 (Structured Decoding)

Rôle : Intercepte chaque réponse d'outil APRÈS son exécution.
- Valide la réponse produite contre l'ontologie.
- Si la réponse contient des assertions invalides, retourne un message
  d'erreur structuré pour déclencher la boucle de self-correction.
- Journalise toutes les validations dans un fichier de log.

Configuration lue depuis ontokit.json (ontology path, threshold, tool name).

Format d'entrée (stdin JSON) :
{
    "session_id": "...",
    "tool_name": "...",
    "tool_input": {...},
    "tool_response": {...}
}

Sortie :
- Exit 0 → réponse acceptée
- Exit 2 + message stderr → réponse bloquée, self-correction déclenchée
"""

import json
import sys
import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ontology_graph import OntologyGraph
from src.validator import OntologyValidator, ValidationResult


def log(msg: str):
    print(f"[PostToolUse] {msg}", file=sys.stderr)


def append_log(log_path: Path, entry: dict):
    """Journalise la validation dans un fichier JSONL."""
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Ne pas faire échouer le hook si le log est inaccessible


def main():
    # Lire l'entrée JSON
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        log(f"Cannot parse JSON input: {e}")
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})
    session_id = data.get("session_id", "unknown")

    log(f"session={session_id} tool={tool_name}")

    # Charger la configuration
    config = load_config(ROOT)
    ontology_tool_name = config.tool_name
    threshold = config.validation_threshold
    log_path = config.log_path

    # Ne valider que le tool ontologique configuré
    if tool_name != ontology_tool_name:
        sys.exit(0)

    # Charger le graphe
    try:
        graph = OntologyGraph(config.ontology_path)
        validator = OntologyValidator(graph)
    except Exception as e:
        log(f"Error loading ontology: {e}")
        sys.exit(0)

    ontology_name = graph.metadata.get("name", "Ontology")

    # La réponse est l'input du tool (structured output via tool_use)
    response_to_validate = tool_input if tool_name == ontology_tool_name else tool_response

    # Si la réponse est une chaîne JSON, la parser
    if isinstance(response_to_validate, str):
        try:
            response_to_validate = json.loads(response_to_validate)
        except json.JSONDecodeError:
            response_to_validate = {"answer": response_to_validate, "entities_mentioned": [], "supporting_triples": []}

    # Valider
    result: ValidationResult = validator.validate_response(response_to_validate)

    # Journaliser
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

    log(f"Validation: score={result.score:.2f} valid={result.valid} errors={len(result.errors)}")

    # Décider si on bloque ou accepte
    if not result.valid and result.score < threshold:
        correction_hints = []
        for c in result.corrections[:5]:
            correction_hints.append(
                f"  • '{c['invalid']}' → suggestions: {c['suggestions']}"
            )

        error_msg = (
            f"[STRUCTURED DECODING - PostToolUse] Invalid response (score={result.score:.2f}).\n\n"
            f"Errors detected:\n"
            + "\n".join(f"  ❌ {e}" for e in result.errors[:5])
            + (f"\n\nSuggested corrections:\n" + "\n".join(correction_hints) if correction_hints else "")
            + f"\n\nWarnings:\n"
            + "\n".join(f"  ⚠️ {w}" for w in result.warnings[:3])
            + f"\n\nReformulate your response using only valid entities "
            f"and triples from the {ontology_name} ontology."
        )
        print(error_msg, file=sys.stderr)
        sys.exit(2)

    # Réponse acceptée — afficher un résumé de validation
    if result.warnings:
        log(f"⚠️ Warnings: {result.warnings}")

    entities = response_to_validate.get("entities_mentioned", [])
    if entities:
        log(f"✅ Validated entities: {entities}")

    triples = response_to_validate.get("supporting_triples", [])
    if triples:
        log(f"✅ {len(triples)} triple(s) validated")

    sys.exit(0)


if __name__ == "__main__":
    main()
