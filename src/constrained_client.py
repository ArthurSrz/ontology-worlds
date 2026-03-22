"""
constrained_client.py
---------------------
Client Claude contraint par l'ontologie — implémentation de la Stratégie 2.

Mécanisme :
- Injecte le fragment de prompt système ontologique (grammar_builder)
- Force la réponse via tool_use avec un JSON Schema compilé (schema_query_response)
- Valide la réponse (validator)
- Si invalide → boucle de self-correction (max MAX_RETRIES fois)

Note sur les logits :
  Avec l'API Claude (boîte noire), on ne peut pas masquer les logits directement.
  On simule le structured decoding via tool_use + JSON Schema strict.
  Avec un modèle local + Outlines, remplacer _call_claude() par le pipeline
  Outlines pour obtenir le masquage logit réel.
"""

from __future__ import annotations
import json
import os
from typing import Any

import anthropic

from .config import load_config, OntoKitConfig
from .ontology_graph import OntologyGraph
from .grammar_builder import GrammarBuilder
from .validator import OntologyValidator, ValidationResult


DEFAULT_MODEL = "claude-opus-4-6"


class ConstrainedClient:
    """
    Client LLM dont toutes les générations sont contraintes par l'ontologie.
    """

    def __init__(
        self,
        graph: OntologyGraph,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        verbose: bool = False,
        config: OntoKitConfig | None = None,
    ):
        self.graph = graph
        self.builder = GrammarBuilder(graph)
        self.validator = OntologyValidator(graph)
        self.model = model
        self.verbose = verbose
        self.config = config or load_config(graph.path.parent.parent if graph.path else None)
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def query(self, user_question: str, focus_node: str | None = None) -> dict:
        """
        Pose une question au LLM en mode structured decoding.

        Args:
            user_question: Question en langage naturel
            focus_node: Optionnel — restreint le schéma au voisinage de ce nœud

        Returns:
            dict avec les champs du schema_query_response + métadonnées de validation
        """
        # 1. Choisir le schéma approprié
        if focus_node and focus_node in self.graph.nodes:
            schema = self.builder.schema_for_subgraph(focus_node, depth=2)
        else:
            schema = self.builder.schema_query_response()

        # 2. Construire le contexte ontologique (injection dans le system prompt)
        system_prompt = self._build_system_prompt(focus_node)

        # 3. Boucle de génération + validation
        response = None
        validation: ValidationResult | None = None

        max_retries = self.config.max_retries
        for attempt in range(1, max_retries + 1):
            if self.verbose:
                print(f"[ConstrainedClient] Attempt {attempt}/{max_retries}...")

            messages = self._build_messages(user_question, response, validation, attempt)
            raw = self._call_claude(system_prompt, messages, schema)

            # Parser la réponse JSON
            try:
                response = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as e:
                response = {"answer": raw, "entities_mentioned": [], "supporting_triples": [], "out_of_scope": True}

            # Valider
            validation = self.validator.validate_response(response)

            if self.verbose:
                print(f"[ConstrainedClient] Validation : {validation.summary()}")

            if validation.valid:
                break

            # Si dernier essai → auto-correction
            if attempt == max_retries:
                response = self.validator.suggest_corrections(response)
                response["_max_retries_reached"] = True

        # Ajouter les métadonnées de validation
        response["_validation"] = {
            "valid": validation.valid if validation else False,
            "score": validation.score if validation else 0.0,
            "errors": validation.errors if validation else [],
            "warnings": validation.warnings if validation else [],
            "attempts": attempt,
        }

        return response

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
    # Méthodes internes
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

    def _build_messages(
        self,
        question: str,
        previous_response: dict | None,
        previous_validation: ValidationResult | None,
        attempt: int,
    ) -> list[dict]:
        messages = [{"role": "user", "content": question}]

        if attempt > 1 and previous_response and previous_validation:
            # Injecter le feedback de validation pour la correction
            feedback = (
                f"\n\n[SYSTÈME - Tentative {attempt}] Ta réponse précédente était invalide :\n"
                f"Erreurs : {previous_validation.errors}\n"
                f"Corrections suggérées : {previous_validation.corrections}\n"
                f"Reformule ta réponse en corrigeant ces erreurs."
            )
            messages[0]["content"] = question + feedback

        return messages

    def _call_claude(
        self, system_prompt: str, messages: list[dict], schema: dict
    ) -> Any:
        """
        Appel à l'API Claude avec tool_use pour forcer le JSON Schema.
        Simule le structured decoding via structured output.
        """
        ontology_name = self.builder.ontology_name
        tool_definition = {
            "name": self.config.tool_name,
            "description": (
                f"Produce a response fully grounded in the {ontology_name} ontology. "
                "Every entity mentioned must exist in the graph. "
                "Every fact must be expressible as a valid triple."
            ),
            "input_schema": schema,
        }

        response = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=[tool_definition],
            tool_choice={"type": "any"},
        )

        # Extraire le contenu du tool_use
        for block in response.content:
            if block.type == "tool_use":
                return block.input

        # Fallback : texte libre si pas de tool_use
        for block in response.content:
            if hasattr(block, "text"):
                return block.text

        return {}
