"""
constrained_client.py
---------------------
Client contraint par l'ontologie.

This module runs INSIDE Claude Code — Claude Code itself is the LLM.
No separate API key or SDK is needed.

Mécanisme :
- Construit le contexte ontologique (grammar_builder)
- Compile le JSON Schema strict (schema_query_response)
- Valide la réponse (validator)
- Si invalide → boucle de self-correction (max MAX_RETRIES fois)

The actual LLM generation is handled by Claude Code via CLAUDE.md rules
and PreToolUse/PostToolUse hooks. This module provides the validation
and schema infrastructure that constrains Claude Code's responses.
"""

from __future__ import annotations
import json
from typing import Any

from .config import load_config, OntoKitConfig
from .ontology_graph import OntologyGraph
from .grammar_builder import GrammarBuilder
from .validator import OntologyValidator, ValidationResult


class ConstrainedClient:
    """
    Validation and schema client for ontology-constrained responses.

    Runs inside Claude Code — no external API key needed.
    Claude Code is the LLM; this module enforces the ontology constraints.
    """

    def __init__(
        self,
        graph: OntologyGraph,
        verbose: bool = False,
        config: OntoKitConfig | None = None,
    ):
        self.graph = graph
        self.builder = GrammarBuilder(graph)
        self.validator = OntologyValidator(graph)
        self.verbose = verbose
        self.config = config or load_config(graph.path.parent.parent if graph.path else None)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def query(self, user_question: str, focus_node: str | None = None) -> dict:
        """
        Build ontology context and schema for a question, then output
        the constraints for Claude Code to use when generating its response.

        Args:
            user_question: Question en langage naturel
            focus_node: Optionnel — restreint le schéma au voisinage de ce nœud

        Returns:
            dict with ontology context, schema, and validation info
        """
        # 1. Choose the appropriate schema
        if focus_node and focus_node in self.graph.nodes:
            schema = self.builder.schema_for_subgraph(focus_node, depth=2)
        else:
            schema = self.builder.schema_query_response()

        # 2. Build ontology context
        system_prompt = self._build_system_prompt(focus_node)

        # 3. Return the context and schema for Claude Code to use
        return {
            "question": user_question,
            "system_prompt": system_prompt,
            "schema": schema,
            "valid_entities": list(self.graph.nodes.keys()),
            "valid_predicates": sorted(self.graph.valid_predicates),
            "focus_node": focus_node,
        }

    def validate_response(self, response: dict) -> dict:
        """Validate a response dict against the ontology."""
        validation = self.validator.validate_response(response)
        return {
            "valid": validation.valid,
            "score": validation.score,
            "errors": validation.errors,
            "warnings": validation.warnings,
            "corrections": validation.corrections,
        }

    def check_fact(self, subject: str, predicate: str, obj: str) -> ValidationResult:
        """Vérifie directement si un triple est dans l'ontologie."""
        return self.validator.validate_triple(subject, predicate, obj)

    def explain_entity(self, entity_id: str) -> dict:
        """Génère une explication structurée d'un nœud du graphe."""
        node = self.graph.get_node(entity_id)
        if not node:
            return {"error": f"Entité '{entity_id}' introuvable dans l'ontologie"}

        subgraph = self.graph.subgraph_around(entity_id, depth=1)
        return {
            "entity": node.to_dict(),
            "neighbors": subgraph["edges"],
            "wikidata_url": f"https://www.wikidata.org/wiki/{node.wikidata}" if node.wikidata else None,
        }

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _build_system_prompt(self, focus_node: str | None = None) -> str:
        base = self.builder.build_system_prompt_fragment()

        if focus_node:
            node = self.graph.get_node(focus_node)
            if node:
                subgraph = self.graph.subgraph_around(focus_node, depth=2)
                base += f"\n\n### Contexte focalisé sur : {node.label} ({focus_node})\n"
                base += f"Nœuds dans le voisinage : {[n['id'] for n in subgraph['nodes']]}\n"
                base += f"Relations : {subgraph['edges']}\n"

        return base
