"""
Shared data layer — DuckDB-backed store for both apps.

Maps to ontology concepts:
- StockDonnees: the DuckDB database itself
- FluxDonnees: the sample feed data generator
- EtatDonnee: tracked via the `etat` column in every table
"""

import duckdb
import json
import random
import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data_design.duckdb"
ONTOLOGY_PATH = Path(__file__).parent.parent / "ontology" / "data_design_interfaces_ontology.json"


def get_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH))


def load_ontology() -> dict:
    with open(ONTOLOGY_PATH) as f:
        return json.load(f)


def get_instances_by_class(ontology: dict, class_id: str) -> list[dict]:
    return [i for i in ontology["instances"] if i.get("class") == class_id]


def get_relations_for(ontology: dict, node_id: str) -> list[dict]:
    return [
        r for r in ontology["relations"]
        if r["subject"] == node_id or r["object"] == node_id
    ]


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist."""
    con = get_connection()

    # Feed content table (consumption app)
    con.execute("""
        CREATE TABLE IF NOT EXISTS feed_items (
            id INTEGER PRIMARY KEY,
            titre VARCHAR,
            contenu TEXT,
            source VARCHAR,
            categorie VARCHAR,
            score_algo FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            etat VARCHAR DEFAULT 'brute',
            likes INTEGER DEFAULT 0,
            partages INTEGER DEFAULT 0,
            vues INTEGER DEFAULT 0,
            sauvegarde BOOLEAN DEFAULT FALSE
        )
    """)

    # User-constructed datasets (construction app)
    con.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY,
            nom VARCHAR,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            etat VARCHAR DEFAULT 'brute',
            schema_json TEXT,
            nb_lignes INTEGER DEFAULT 0
        )
    """)

    # Rows within a dataset
    con.execute("""
        CREATE TABLE IF NOT EXISTS dataset_rows (
            id INTEGER PRIMARY KEY,
            dataset_id INTEGER,
            data_json TEXT,
            etat VARCHAR DEFAULT 'brute',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Interaction log (both apps)
    con.execute("""
        CREATE TABLE IF NOT EXISTS interaction_log (
            id INTEGER PRIMARY KEY,
            app VARCHAR,
            action VARCHAR,
            entity_id VARCHAR,
            etat_before VARCHAR,
            etat_after VARCHAR,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.close()


# ---------------------------------------------------------------------------
# Feed data generator (FluxDonnees)
# ---------------------------------------------------------------------------

SOURCES = ["LinkedIn", "Le Monde", "Twitter/X", "Reddit", "Medium", "TechCrunch"]
CATEGORIES = ["data", "design", "IA", "politique", "tech", "science", "culture"]

SAMPLE_TITLES = [
    "Les interfaces de demain seront construites, pas consommées",
    "Comment DuckDB révolutionne l'analyse de données locale",
    "Scroll infini : le piège attentionnel que personne ne voit",
    "Streamlit 2.0 : construire des apps de données en minutes",
    "L'économie de l'attention a-t-elle atteint ses limites ?",
    "Pourquoi les tableurs restent l'outil le plus puissant",
    "Architecture de l'information : retour aux fondamentaux",
    "Le pipeline Input-Traitement-Output comme acte de liberté",
    "Réseaux sociaux : sommes-nous des consommateurs ou des produits ?",
    "Visualisation de données : rendre visible l'invisible",
    "GitHub Codespaces change la donne pour le développement",
    "La donnée brute n'existe pas — tout est déjà interprété",
    "DataButton : quand le no-code rencontre la data science",
    "Presse en ligne : le flux qui ne s'arrête jamais",
    "De la donnée consommée à la donnée publiée : deux chemins",
    "Les algorithmes de flux décident ce que vous pensez",
    "Excel a 40 ans et n'a jamais été aussi pertinent",
    "ChatGPT est-il une interface de consommation déguisée ?",
    "Le design d'interface est un acte politique",
    "Temporalité discrète vs continue : choisissez votre camp",
]


def generate_feed_items(n: int = 50) -> list[dict]:
    """Generate sample feed items — simulates FluxDonnees."""
    items = []
    for i in range(n):
        items.append({
            "titre": random.choice(SAMPLE_TITLES),
            "contenu": f"Contenu de l'article #{i+1}. " * random.randint(3, 8),
            "source": random.choice(SOURCES),
            "categorie": random.choice(CATEGORIES),
            "score_algo": round(random.random(), 3),
            "likes": random.randint(0, 500),
            "partages": random.randint(0, 100),
            "vues": random.randint(10, 10000),
        })
    return items


def seed_feed(n: int = 50):
    """Populate feed_items table with sample data."""
    con = get_connection()
    count = con.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0]
    if count >= n:
        con.close()
        return

    items = generate_feed_items(n)
    for i, item in enumerate(items):
        con.execute(
            """INSERT OR IGNORE INTO feed_items (id, titre, contenu, source, categorie, score_algo, likes, partages, vues)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [i + 1, item["titre"], item["contenu"], item["source"],
             item["categorie"], item["score_algo"], item["likes"],
             item["partages"], item["vues"]]
        )
    con.close()


def log_interaction(app: str, action: str, entity_id: str,
                    etat_before: str = "", etat_after: str = ""):
    """Log a user interaction — maps to ActionUtilisateur."""
    con = get_connection()
    con.execute(
        """INSERT INTO interaction_log (app, action, entity_id, etat_before, etat_after)
           VALUES (?, ?, ?, ?, ?)""",
        [app, action, entity_id, etat_before, etat_after]
    )
    con.close()
