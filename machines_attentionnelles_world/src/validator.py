"""
validator.py
------------
Valide les réponses LLM contre l'ontologie Open Data France.

Trois types de validation :
1. validate_triple()   — un triple (s, p, o) est-il dans le graphe ?
2. validate_response() — une réponse structurée est-elle cohérente ?
3. validate_entities() — les entités mentionnées existent-elles ?

En cas d'échec, le validator produit des corrections suggérées
(pour implémenter la boucle de self-correction du pattern 1+3).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from .ontology_graph import OntologyGraph


@dataclass
class ValidationResult:
    valid: bool
    score: float  # 0.0 → 1.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)

    def __bool__(self):
        return self.valid

    def summary(self) -> str:
        status = "✅ VALIDE" if self.valid else "❌ INVALIDE"
        lines = [f"{status} (score={self.score:.2f})"]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        for c in self.corrections:
            lines.append(f"  CORRECTION: {c}")
        return "\n".join(lines)


class OntologyValidator:

    def __init__(self, graph: OntologyGraph):
        self.graph = graph
        # Index rapide des arêtes pour O(1) lookup
        self._edge_set: set[tuple[str, str, str]] = set(
            (s, p, o) for (s, p, o) in graph.edges
        )

    # ------------------------------------------------------------------
    # Validation d'un triple atomique
    # ------------------------------------------------------------------

    def validate_triple(
        self, subject: str, predicate: str, obj: str
    ) -> ValidationResult:
        errors = []
        warnings = []
        corrections = []

        # 1. Le sujet existe-t-il ?
        if subject not in self.graph.nodes:
            similar = self.graph.search(subject)
            errors.append(f"Sujet inconnu : '{subject}'")
            if similar:
                corrections.append({
                    "field": "subject",
                    "invalid": subject,
                    "suggestions": [n.id for n in similar[:3]],
                })

        # 2. Le prédicat est-il valide ?
        if predicate not in self.graph.valid_predicates:
            errors.append(f"Prédicat invalide : '{predicate}'")
            closest = [p for p in self.graph.valid_predicates if predicate.lower() in p.lower()]
            if closest:
                corrections.append({
                    "field": "predicate",
                    "invalid": predicate,
                    "suggestions": closest[:3],
                })

        # 3. L'objet existe-t-il ?
        if obj not in self.graph.nodes:
            similar = self.graph.search(obj)
            errors.append(f"Objet inconnu : '{obj}'")
            if similar:
                corrections.append({
                    "field": "object",
                    "invalid": obj,
                    "suggestions": [n.id for n in similar[:3]],
                })

        # 4. Le triple existe-t-il dans le graphe ?
        if not errors and (subject, predicate, obj) not in self._edge_set:
            # Triple syntaxiquement valide mais absent du graphe
            valid_objects = self.graph.find_objects(subject, predicate)
            if valid_objects:
                warnings.append(
                    f"Triple ({subject}, {predicate}, {obj}) absent du graphe. "
                    f"Valeurs connues pour ce prédicat : {valid_objects}"
                )
                corrections.append({
                    "field": "object",
                    "invalid": obj,
                    "suggestions": valid_objects,
                })
            else:
                warnings.append(
                    f"Triple ({subject}, {predicate}, {obj}) absent du graphe. "
                    f"Prédicat '{predicate}' jamais utilisé depuis '{subject}'."
                )

        score = 1.0 - (len(errors) * 0.4 + len(warnings) * 0.1)
        score = max(0.0, min(1.0, score))
        valid = len(errors) == 0

        return ValidationResult(
            valid=valid, score=score,
            errors=errors, warnings=warnings, corrections=corrections
        )

    # ------------------------------------------------------------------
    # Validation d'une liste d'entités
    # ------------------------------------------------------------------

    def validate_entities(self, entity_ids: list[str]) -> ValidationResult:
        errors = []
        warnings = []
        corrections = []

        for eid in entity_ids:
            if eid not in self.graph.nodes:
                errors.append(f"Entité inconnue : '{eid}'")
                similar = self.graph.search(eid)
                if similar:
                    corrections.append({
                        "field": "entity",
                        "invalid": eid,
                        "suggestions": [n.id for n in similar[:3]],
                    })

        score = 1.0 - len(errors) / max(len(entity_ids), 1) * 0.5
        return ValidationResult(
            valid=len(errors) == 0, score=score,
            errors=errors, warnings=warnings, corrections=corrections
        )

    # ------------------------------------------------------------------
    # Validation d'une réponse structurée complète
    # ------------------------------------------------------------------

    def validate_response(self, response: dict) -> ValidationResult:
        """
        Valide une réponse au format schema_query_response().
        Vérifie :
        - Les entités mentionnées existent dans le graphe
        - Les triples de support sont cohérents avec le graphe
        - La réponse n'est pas marquée out_of_scope abusivement
        """
        all_errors = []
        all_warnings = []
        all_corrections = []
        scores = []

        # 1. Entités
        entities = response.get("entities_mentioned", [])
        if entities:
            r = self.validate_entities(entities)
            all_errors.extend(r.errors)
            all_warnings.extend(r.warnings)
            all_corrections.extend(r.corrections)
            scores.append(r.score)
        else:
            all_warnings.append("Aucune entité mentionnée dans la réponse.")

        # 2. Triples de support
        triples = response.get("supporting_triples", [])
        if triples:
            for t in triples:
                s = t.get("subject", "")
                p = t.get("predicate", "")
                o = t.get("object", "")
                r = self.validate_triple(s, p, o)
                all_errors.extend(r.errors)
                all_warnings.extend(r.warnings)
                all_corrections.extend(r.corrections)
                scores.append(r.score)
        else:
            all_warnings.append("Aucun triple de support fourni.")

        # 3. out_of_scope
        if response.get("out_of_scope") and not all_errors:
            all_warnings.append(
                "La réponse est marquée out_of_scope alors que des entités connues sont présentes."
            )

        # 4. Cohérence Wikidata
        wikidata_ids = response.get("wikidata_ids", [])
        for qid in wikidata_ids:
            if not qid.startswith("Q"):
                all_errors.append(f"Q-number Wikidata invalide : '{qid}'")

        avg_score = sum(scores) / len(scores) if scores else 0.5
        valid = len(all_errors) == 0

        return ValidationResult(
            valid=valid,
            score=avg_score,
            errors=all_errors,
            warnings=all_warnings,
            corrections=all_corrections,
        )

    # ------------------------------------------------------------------
    # Validation d'un texte libre (extraction naïve d'entités)
    # ------------------------------------------------------------------

    def validate_free_text(self, text: str) -> ValidationResult:
        """
        Valide un texte libre en cherchant les entités mentionnées.
        Détecte les entités connues et les entités inconnues/inventées.
        """
        text_lower = text.lower()
        found_known = []
        potential_unknown = []

        for node in self.graph.nodes.values():
            if (
                node.label.lower() in text_lower
                or node.id.lower() in text_lower
                or (node.label_short and node.label_short.lower() in text_lower)
            ):
                found_known.append(node.id)

        warnings = []
        if not found_known:
            warnings.append("Aucune entité ontologique détectée dans le texte libre.")

        return ValidationResult(
            valid=True,
            score=1.0 if found_known else 0.5,
            warnings=warnings,
            corrections=[],
        )

    # ------------------------------------------------------------------
    # Auto-correction
    # ------------------------------------------------------------------

    def suggest_corrections(self, response: dict) -> dict:
        """
        Tente de corriger automatiquement une réponse invalide.
        Remplace les entités inconnues par les suggestions les plus proches.
        """
        result = self.validate_response(response)
        if result.valid:
            return response  # Rien à corriger

        corrected = dict(response)

        # Corriger les entités mentionnées
        corrected_entities = []
        for eid in response.get("entities_mentioned", []):
            if eid in self.graph.nodes:
                corrected_entities.append(eid)
            else:
                similar = self.graph.search(eid)
                if similar:
                    corrected_entities.append(similar[0].id)
        corrected["entities_mentioned"] = corrected_entities

        # Corriger les triples
        corrected_triples = []
        for t in response.get("supporting_triples", []):
            s, p, o = t.get("subject", ""), t.get("predicate", ""), t.get("object", "")
            fixed_t = dict(t)
            if s not in self.graph.nodes:
                similar = self.graph.search(s)
                if similar:
                    fixed_t["subject"] = similar[0].id
            if p not in self.graph.valid_predicates:
                closest = [pr for pr in self.graph.valid_predicates if p.lower() in pr.lower()]
                if closest:
                    fixed_t["predicate"] = closest[0]
            if o not in self.graph.nodes:
                similar = self.graph.search(o)
                if similar:
                    fixed_t["object"] = similar[0].id
            corrected_triples.append(fixed_t)
        corrected["supporting_triples"] = corrected_triples
        corrected["_auto_corrected"] = True

        return corrected
