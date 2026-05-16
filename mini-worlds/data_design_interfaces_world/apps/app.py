"""
Launcher — Choose between consumption and construction architectures.

Maps to the core ontological opposition:
  ArchitectureConsommation ←opposeDe→ ArchitectureConstruction
  ConsommateurDonnees ←opposeDe→ ConstructeurDonnees
"""

import streamlit as st
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from data_store import load_ontology, get_connection, init_db


def render_ontology_sidebar():
    """Show the ontology structure in the sidebar."""
    onto = load_ontology()
    classes = onto["classes"]
    instances = onto["instances"]

    st.sidebar.markdown("## 🌍 Ontologie")
    st.sidebar.caption(f"{len(instances)} entités · {len(onto['relations'])} relations · {len(onto['valid_predicates'])} prédicats")

    for cls in classes:
        members = [i for i in instances if i.get("class") == cls["id"]]
        if members:
            with st.sidebar.expander(f"**{cls['label']}** ({len(members)})", expanded=False):
                for m in members:
                    st.caption(f"· {m['label']}")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Prédicats valides")
    st.sidebar.caption(", ".join(onto["valid_predicates"]))


def render_interaction_stats():
    """Show interaction stats from the log."""
    try:
        con = get_connection()
        stats = con.execute("""
            SELECT app, action, COUNT(*) as n
            FROM interaction_log
            GROUP BY app, action
            ORDER BY n DESC
        """).fetchdf()
        con.close()

        if not stats.empty:
            st.markdown("### 📊 Interactions enregistrées")
            col_c, col_b = st.columns(2)
            with col_c:
                conso = stats[stats["app"] == "consommation"]
                if not conso.empty:
                    st.markdown("**Consommation**")
                    for _, row in conso.iterrows():
                        st.caption(f"{row['action']}: {row['n']}x")
            with col_b:
                build = stats[stats["app"] == "construction"]
                if not build.empty:
                    st.markdown("**Construction**")
                    for _, row in build.iterrows():
                        st.caption(f"{row['action']}: {row['n']}x")
    except Exception:
        pass


def main():
    st.set_page_config(
        page_title="Data Design Interfaces",
        layout="wide",
        page_icon="🌍",
    )

    init_db()
    render_ontology_sidebar()

    st.markdown("""
    # 🌍 Data Design Interfaces

    > _Ontologie des interfaces comme architectures de nos interactions avec les données_
    > — Arthur Sarazin, Le Bateau Ivre des Données (2023)

    ---

    Choisissez votre architecture :
    """)

    col_conso, col_divider, col_build = st.columns([5, 1, 5])

    with col_conso:
        st.markdown("""
        ## 📱 Consommation

        L'interface **décide pour vous**. Vous êtes installé dans un flux
        continu, guidé par l'algorithme. Votre attention est la ressource.

        | Propriété | Valeur |
        |-----------|--------|
        | Temporalité | **Continue** (infinie) |
        | Rôle | **Consommateur** passif |
        | Mécanisme | Scroll infini + algorithme |
        | Données | **Flux** (en mouvement) |
        | Attention | **Consommée** |

        **Composants** : Feed, Carte, Notification, Recommandation

        **Actions** : Scroller, Liker, Partager, Sauvegarder

        **Pipeline** : Brute → Algorithmisée → Affichée → Consommée
        """)

        if st.button("📱 Entrer en mode Consommation", type="primary", use_container_width=True):
            st.switch_page("pages/consommation.py")

    with col_divider:
        st.markdown("""
        <div style="display:flex; justify-content:center; align-items:center; height:400px;">
            <span style="font-size:2em; color:#888;">⚡</span>
        </div>
        """, unsafe_allow_html=True)

    with col_build:
        st.markdown("""
        ## 🔨 Construction

        **Vous** décidez ce qui se passe. Chaque action est intentionnelle :
        input, traitement conscient, output. Vous construisez du stock.

        | Propriété | Valeur |
        |-----------|--------|
        | Temporalité | **Discrète** (séquencée) |
        | Rôle | **Constructeur** actif |
        | Mécanisme | Pipeline I-T-O |
        | Données | **Stock** (persistant) |
        | Attention | **Préservée** |

        **Composants** : Formulaire, Tableau, Requête, Canvas, Terminal

        **Actions** : Créer, Transformer, Requêter, Valider, Exporter

        **Pipeline** : Brute → Nettoyée → Transformée → Structurée → Publiée
        """)

        if st.button("🔨 Entrer en mode Construction", type="primary", use_container_width=True):
            st.switch_page("pages/construction.py")

    st.markdown("---")
    render_interaction_stats()

    st.markdown("---")
    st.caption("""
    _Chaque composant, action et transition de ces applications correspond à un nœud
    ou une relation dans l'ontologie. Les apps ne sont pas "inspirées" de l'ontologie —
    elles en sont l'instanciation directe._
    """)


if __name__ == "__main__":
    main()
