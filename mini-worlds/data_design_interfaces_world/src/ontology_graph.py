"""
ontology_graph.py
-----------------
Charge l'ontologie JSON-LD en mémoire sous forme de graphe orienté.
Fournit des méthodes de requête (voisins, chemins, classes, instances)
qui servent de base au grammar_builder et au validator.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from collections import defaultdict

from .config import load_config, get_ontology_metadata


class OntologyNode:
    def __init__(self, data: dict):
        self.id: str = data["id"]
        self.cls: str = data.get("class", data.get("id"))  # classes use their id as class
        self.label: str = data.get("label", self.id)
        self.label_short: str = data.get("label_short", self.label)
        self.wikidata: str | None = data.get("wikidata")
        self.description: str = data.get("description", "")
        self.properties: dict = data.get("properties", {})
        self.raw: dict = data

    def __repr__(self):
        return f"OntologyNode(id={self.id!r}, class={self.cls!r}, label={self.label!r})"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "class": self.cls,
            "label": self.label,
            "label_short": self.label_short,
            "wikidata": self.wikidata,
            "description": self.description,
            "properties": self.properties,
        }


class OntologyGraph:
    """
    Graphe en mémoire construit depuis le fichier JSON-LD de l'ontologie.

    Structure interne :
    - self.nodes : dict[id -> OntologyNode]
    - self.classes : dict[id -> OntologyNode]   (nœuds de type classe)
    - self.edges : list[(subject_id, predicate, object_id)]
    - self.adj_out : dict[id -> list[(predicate, target_id)]]
    - self.adj_in  : dict[id -> list[(predicate, source_id)]]
    """

    def __init__(self, path: Path | str | None = None):
        if path is None:
            config = load_config(Path(__file__).parent.parent)
            path = config.ontology_path
        self.path = Path(path)
        self.nodes: dict[str, OntologyNode] = {}
        self.classes: dict[str, OntologyNode] = {}
        self.edges: list[tuple[str, str, str]] = []
        self.adj_out: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.adj_in: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.valid_predicates: set[str] = set()
        self.metadata: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    def _load(self):
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extraire les métadonnées de l'ontologie
        self.metadata = get_ontology_metadata(data)

        # Enregistrer les classes
        for cls in data.get("classes", []):
            node = OntologyNode({**cls, "class": "_Class"})
            self.nodes[cls["id"]] = node
            self.classes[cls["id"]] = node

        # Enregistrer les instances
        for inst in data.get("instances", []):
            node = OntologyNode(inst)
            self.nodes[inst["id"]] = node
            # Ajouter une arête instanceOf vers la classe
            cls_id = inst.get("class")
            if cls_id and cls_id in self.classes:
                self._add_edge(inst["id"], "instanceOf", cls_id)
            # Ajouter les arêtes depuis les properties inline
            for pred, obj in inst.get("properties", {}).items():
                if isinstance(obj, list):
                    for o in obj:
                        if isinstance(o, str):
                            self._add_edge(inst["id"], pred, o)
                elif isinstance(obj, str):
                    self._add_edge(inst["id"], pred, obj)

        # Enregistrer les relations explicites
        for rel in data.get("relations", []):
            self._add_edge(rel["subject"], rel["predicate"], rel["object"])

        # Prédicats valides
        self.valid_predicates = set(data.get("valid_predicates", []))

    def _add_edge(self, subject: str, predicate: str, obj: str):
        triple = (subject, predicate, obj)
        if triple not in self.edges:
            self.edges.append(triple)
            self.adj_out[subject].append((predicate, obj))
            self.adj_in[obj].append((predicate, subject))

    # ------------------------------------------------------------------
    # Requêtes
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> OntologyNode | None:
        return self.nodes.get(node_id)

    def get_instances_of(self, class_id: str) -> list[OntologyNode]:
        """Retourne toutes les instances d'une classe donnée."""
        return [
            self.nodes[nid]
            for nid, node in self.nodes.items()
            if node.cls == class_id
        ]

    def get_neighbors_out(self, node_id: str) -> list[tuple[str, str]]:
        """Voisins sortants : liste de (predicate, target_id)."""
        return self.adj_out.get(node_id, [])

    def get_neighbors_in(self, node_id: str) -> list[tuple[str, str]]:
        """Voisins entrants : liste de (predicate, source_id)."""
        return self.adj_in.get(node_id, [])

    def find_by_predicate(self, predicate: str) -> list[tuple[str, str, str]]:
        """Toutes les arêtes avec un prédicat donné."""
        return [(s, p, o) for (s, p, o) in self.edges if p == predicate]

    def find_objects(self, subject: str, predicate: str) -> list[str]:
        """Valeurs d'un prédicat donné depuis un sujet."""
        return [o for (p, o) in self.adj_out.get(subject, []) if p == predicate]

    def find_subjects(self, predicate: str, obj: str) -> list[str]:
        """Sujets pointant vers obj avec le prédicat donné."""
        return [s for (p, s) in self.adj_in.get(obj, []) if p == predicate]

    def get_all_ids(self) -> list[str]:
        return list(self.nodes.keys())

    def get_all_labels(self) -> list[str]:
        return [n.label for n in self.nodes.values()]

    def get_all_labels_short(self) -> list[str]:
        return [n.label_short for n in self.nodes.values()]

    def get_class_of(self, node_id: str) -> str | None:
        node = self.nodes.get(node_id)
        return node.cls if node else None

    def search(self, query: str) -> list[OntologyNode]:
        """Recherche partielle sur id, label, description (case-insensitive)."""
        q = query.lower()
        results = []
        for node in self.nodes.values():
            if (
                q in node.id.lower()
                or q in node.label.lower()
                or q in node.description.lower()
                or (node.wikidata and q in node.wikidata.lower())
            ):
                results.append(node)
        return results

    def subgraph_around(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        """
        Retourne un sous-graphe centré sur node_id jusqu'à une profondeur donnée.
        Utile pour construire dynamiquement le contexte d'une requête.
        """
        visited = set()
        nodes_data = []
        edges_data = []

        def dfs(nid: str, remaining: int):
            if nid in visited or remaining < 0:
                return
            visited.add(nid)
            node = self.nodes.get(nid)
            if node:
                nodes_data.append(node.to_dict())
            for pred, target in self.adj_out.get(nid, []):
                edges_data.append({"subject": nid, "predicate": pred, "object": target})
                dfs(target, remaining - 1)
            for pred, source in self.adj_in.get(nid, []):
                edges_data.append({"subject": source, "predicate": pred, "object": nid})
                dfs(source, remaining - 1)

        dfs(node_id, depth)
        return {"nodes": nodes_data, "edges": edges_data}

    def summary(self) -> dict:
        class_counts = defaultdict(int)
        for node in self.nodes.values():
            class_counts[node.cls] += 1
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "total_classes": len(self.classes),
            "nodes_by_class": dict(class_counts),
            "valid_predicates": list(self.valid_predicates),
        }
