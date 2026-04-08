"""
structured_decoding_opendata
----------------------------
Environnement Claude Code implémentant la Stratégie 2 (Structured Decoding)
sur l'ontologie Open Data France.

Modules :
- ontology_graph   : Graphe en mémoire de l'ontologie
- grammar_builder  : Compilation de JSON Schemas depuis le graphe
- validator        : Validation des réponses contre l'ontologie
- constrained_client : Client Claude contraint par l'ontologie
"""

from .ontology_graph import OntologyGraph, OntologyNode
from .grammar_builder import GrammarBuilder
from .validator import OntologyValidator, ValidationResult
from .constrained_client import ConstrainedClient

__all__ = [
    "OntologyGraph",
    "OntologyNode",
    "GrammarBuilder",
    "OntologyValidator",
    "ValidationResult",
    "ConstrainedClient",
]
