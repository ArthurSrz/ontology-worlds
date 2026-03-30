"""
grammar_builder.py
------------------
Compile des "grammaires" depuis l'ontologie sous forme de JSON Schemas.

C'est le cœur de la stratégie 2 (Structured Decoding) :
- Pour chaque type de requête, on génère dynamiquement un JSON Schema
  qui contraint la réponse du LLM aux valeurs valides du graphe.
- Sans accès aux logits (API fermée), on force Claude à respecter
  ce schéma via tool_use / structured output.
- Avec un modèle local + Outlines, ce schéma serait utilisé pour
  masquer directement les logits invalides.

Architecture :
    QueryIntent → relevant_nodes → JSON Schema → structured prompt
"""

from __future__ import annotations
import json
from typing import Any
from .ontology_graph import OntologyGraph, OntologyNode


# ---------------------------------------------------------------------------
# Multilingual prompt templates
# ---------------------------------------------------------------------------
PROMPT_TEMPLATES = {
    "fr": {
        "header": "## CONTRAINTES ONTOLOGIQUES — {name}",
        "intro": [
            "Tu opères en mode STRUCTURED DECODING. Toute réponse doit être",
            "entièrement ancrée dans l'ontologie ci-dessous. Tu NE PEUX PAS :",
            "- Inventer des entités absentes de l'ontologie",
            "- Utiliser des prédicats non listés ci-dessous",
            "- Faire des assertions non vérifiables dans le graphe",
        ],
        "entities_header": "### Entités valides ({count} nœuds)",
        "predicates_header": "### Prédicats valides ({count})",
        "grounding_header": "### Règle de grounding",
        "grounding_body": [
            "Chaque fait que tu énonces doit correspondre à un triple",
            "(subject, predicate, object) existant dans l'ontologie.",
            "Si tu ne peux pas ancrer un fait, indique out_of_scope=true.",
        ],
        "class_instance_title": "Instance de {class_id}",
        "class_instance_desc": "Valeur contrainte aux instances de la classe {class_id} dans l'ontologie {name}",
        "no_value": "Aucune valeur connue pour {subject}.{predicate}",
        "predicate_desc": "Valeurs valides de la propriété '{predicate}' pour '{subject}'",
        "assertion_title": "Assertion Ontologique",
        "assertion_desc": "Triple RDF contraint aux valeurs de l'ontologie {name}",
        "response_title": "Réponse Contrainte par l'Ontologie",
        "response_desc": "Réponse du LLM entièrement ancrée dans le graphe {name}",
        "subgraph_title": "Réponse contrainte au voisinage de {node_id}",
    },
    "en": {
        "header": "## ONTOLOGICAL CONSTRAINTS — {name}",
        "intro": [
            "You are operating in STRUCTURED DECODING mode. Every response must be",
            "fully grounded in the ontology below. You CANNOT:",
            "- Invent entities absent from the ontology",
            "- Use predicates not listed below",
            "- Make assertions not verifiable in the graph",
        ],
        "entities_header": "### Valid entities ({count} nodes)",
        "predicates_header": "### Valid predicates ({count})",
        "grounding_header": "### Grounding rule",
        "grounding_body": [
            "Every fact you state must correspond to a triple",
            "(subject, predicate, object) existing in the ontology.",
            "If you cannot ground a fact, set out_of_scope=true.",
        ],
        "class_instance_title": "Instance of {class_id}",
        "class_instance_desc": "Value constrained to instances of class {class_id} in the {name} ontology",
        "no_value": "No known value for {subject}.{predicate}",
        "predicate_desc": "Valid values of property '{predicate}' for '{subject}'",
        "assertion_title": "Ontological Assertion",
        "assertion_desc": "RDF triple constrained to values in the {name} ontology",
        "response_title": "Ontology-Constrained Response",
        "response_desc": "LLM response fully grounded in the {name} graph",
        "subgraph_title": "Response constrained to neighborhood of {node_id}",
    },
}


class GrammarBuilder:
    """
    Construit des JSON Schemas à partir du graphe ontologique.
    Ces schémas servent de "grammaire" pour contraindre la génération.
    """

    def __init__(self, graph: OntologyGraph):
        self.graph = graph
        self._ontology_name = graph.metadata.get("name", "Ontology")
        self._language = graph.metadata.get("language", "en")
        self._t = PROMPT_TEMPLATES.get(self._language, PROMPT_TEMPLATES["en"])

    @property
    def ontology_name(self) -> str:
        return self._ontology_name

    def _fmt(self, key: str, **kwargs) -> str:
        """Format a template string with name always available."""
        return self._t[key].format(name=self._ontology_name, **kwargs)

    # ------------------------------------------------------------------
    # Schémas génériques par type de nœud
    # ------------------------------------------------------------------

    def schema_for_class(self, class_id: str) -> dict:
        """
        Schéma JSON énumérant toutes les instances valides d'une classe.
        Ex: schema_for_class("Institution") → enum [Etalab, DINUM, CADA, ...]
        """
        instances = self.graph.get_instances_of(class_id)
        ids = [n.id for n in instances]
        labels = [n.label for n in instances]
        labels_short = [n.label_short for n in instances if n.label_short != n.label]

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": self._fmt("class_instance_title", class_id=class_id),
            "description": self._fmt("class_instance_desc", class_id=class_id),
            "type": "string",
            "enum": ids,
            "x-labels": labels,
            "x-labels-short": labels_short,
        }

    def schema_for_predicate(self, subject_id: str, predicate: str) -> dict:
        """
        Schéma JSON pour les valeurs valides d'un prédicat depuis un sujet.
        Ex: schema_for_predicate("Etalab", "partOf") → enum ["DINUM"]
        """
        valid_objects = self.graph.find_objects(subject_id, predicate)
        if not valid_objects:
            return {
                "type": "string",
                "description": self._fmt("no_value", subject=subject_id, predicate=predicate),
            }

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{subject_id} → {predicate}",
            "description": self._fmt("predicate_desc", subject=subject_id, predicate=predicate),
            "type": "string",
            "enum": valid_objects,
        }

    # ------------------------------------------------------------------
    # Schéma de réponse structurée complète
    # ------------------------------------------------------------------

    def schema_assertion(self) -> dict:
        """
        Schéma pour une assertion atomique sur le graphe.
        Tout énoncé produit doit être exprimable comme triple (s, p, o)
        avec des valeurs connues dans le graphe.
        """
        all_ids = self.graph.get_all_ids()
        all_predicates = sorted(self.graph.valid_predicates)

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": self._fmt("assertion_title"),
            "description": self._fmt("assertion_desc"),
            "type": "object",
            "required": ["subject", "predicate", "object", "confidence"],
            "additionalProperties": False,
            "properties": {
                "subject": {
                    "type": "string",
                    "enum": all_ids,
                    "description": "Subject identifier in the ontology",
                },
                "predicate": {
                    "type": "string",
                    "enum": all_predicates,
                    "description": "Relation predicate",
                },
                "object": {
                    "type": "string",
                    "enum": all_ids,
                    "description": "Object identifier in the ontology",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Assertion confidence score (0.0 to 1.0)",
                },
                "grounded_in_wikidata": {
                    "type": "boolean",
                    "description": "Is the assertion verifiable on Wikidata?",
                },
            },
        }

    def schema_query_response(self) -> dict:
        """
        Schéma de réponse complète à une requête utilisateur.
        Contraint : le résumé textuel + les assertions soutenant la réponse.
        """
        all_ids = self.graph.get_all_ids()
        all_predicates = sorted(self.graph.valid_predicates)

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": self._fmt("response_title"),
            "description": self._fmt("response_desc"),
            "type": "object",
            "required": ["answer", "entities_mentioned", "supporting_triples", "out_of_scope"],
            "additionalProperties": False,
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "Natural language answer grounded in the ontology",
                    "maxLength": 2000,
                },
                "entities_mentioned": {
                    "type": "array",
                    "description": "List of ontology entity identifiers mentioned in the answer",
                    "items": {
                        "type": "string",
                        "enum": all_ids,
                    },
                    "uniqueItems": True,
                },
                "supporting_triples": {
                    "type": "array",
                    "description": "Graph triples supporting the answer",
                    "items": {
                        "type": "object",
                        "required": ["subject", "predicate", "object"],
                        "properties": {
                            "subject": {"type": "string", "enum": all_ids},
                            "predicate": {"type": "string", "enum": all_predicates},
                            "object": {"type": "string", "enum": all_ids},
                        },
                    },
                },
                "out_of_scope": {
                    "type": "boolean",
                    "description": "True if the question exceeds the ontology scope",
                },
                "wikidata_ids": {
                    "type": "array",
                    "description": "Wikidata Q-numbers of cited entities (for external validation)",
                    "items": {"type": "string", "pattern": "^Q[0-9]+$"},
                },
            },
        }

    def schema_node_lookup(self) -> dict:
        """Schéma pour identifier précisément un nœud de l'ontologie."""
        all_ids = self.graph.get_all_ids()
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Node Identification",
            "type": "object",
            "required": ["node_id", "confidence"],
            "properties": {
                "node_id": {"type": "string", "enum": all_ids},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "reasoning": {"type": "string"},
            },
        }

    # ------------------------------------------------------------------
    # Schéma contextuel (sous-graphe autour d'un nœud)
    # ------------------------------------------------------------------

    def schema_for_subgraph(self, node_id: str, depth: int = 1) -> dict:
        """
        Génère un schéma restreint au sous-graphe autour d'un nœud.
        Plus sélectif que les schémas globaux — utile pour les requêtes focalisées.
        """
        subgraph = self.graph.subgraph_around(node_id, depth)
        local_ids = [n["id"] for n in subgraph["nodes"]]
        local_predicates = sorted({e["predicate"] for e in subgraph["edges"]})

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": self._fmt("subgraph_title", node_id=node_id),
            "type": "object",
            "required": ["answer", "supporting_triples"],
            "properties": {
                "answer": {"type": "string", "maxLength": 1000},
                "supporting_triples": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["subject", "predicate", "object"],
                        "properties": {
                            "subject": {"type": "string", "enum": local_ids},
                            "predicate": {"type": "string", "enum": local_predicates or list(self.graph.valid_predicates)},
                            "object": {"type": "string", "enum": local_ids},
                        },
                    },
                },
            },
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_all_schemas(self, output_dir) -> list[str]:
        """Exporte tous les schémas dans un répertoire donné."""
        from pathlib import Path
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        exported = []

        schemas = {
            "assertion.json": self.schema_assertion(),
            "query_response.json": self.schema_query_response(),
            "node_lookup.json": self.schema_node_lookup(),
        }

        # Un schéma par classe
        for cls_id in self.graph.classes:
            schemas[f"class_{cls_id.lower()}.json"] = self.schema_for_class(cls_id)

        for filename, schema in schemas.items():
            path = output_dir / filename
            with open(path, "w", encoding="utf-8") as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            exported.append(str(path))

        return exported

    def build_system_prompt_fragment(self) -> str:
        """
        Génère le fragment de prompt système injectant les contraintes ontologiques.
        Ce fragment est inséré AVANT toute génération pour borner le contexte du LLM.

        Uses the ontology's language for the prompt template.
        """
        summary = self.graph.summary()
        all_ids = self.graph.get_all_ids()
        predicates = sorted(self.graph.valid_predicates)
        t = self._t

        lines = [
            self._fmt("header"),
            "",
            *t["intro"],
            "",
            self._fmt("entities_header", count=summary["total_nodes"]),
            "```",
            ", ".join(all_ids),
            "```",
            "",
            self._fmt("predicates_header", count=len(predicates)),
            "```",
            ", ".join(predicates),
            "```",
            "",
            t["grounding_header"],
            *t["grounding_body"],
        ]
        return "\n".join(lines)
