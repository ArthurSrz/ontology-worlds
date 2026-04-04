"""
App Construction — Architecture de construction de données

Ontology mapping:
  Architecture:  ArchitectureConstruction
  Composants:    Formulaire, TableauEditable, PanneauRequete, Canvas, Terminal, BarreRecherche
  Actions:       Creer, Transformer, Requeter, Valider, Exporter
  Pipeline:      DonneeBrute → DonneeNettoyee → DonneeTransformee → DonneeStructuree → DonneePubliee
  Temporalité:   Discrète (chaque action a input, traitement, output)
  Rôle:          ConstructeurDonnees (agency forte)
"""

import streamlit as st
import pandas as pd
import duckdb
import json
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from data_store import get_connection, init_db, log_interaction, load_ontology


# ---------------------------------------------------------------------------
# State init
# ---------------------------------------------------------------------------

def init_state():
    if "current_dataset_id" not in st.session_state:
        st.session_state.current_dataset_id = None
    if "pipeline_stage" not in st.session_state:
        st.session_state.pipeline_stage = "brute"


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

PIPELINE_STAGES = ["brute", "nettoyee", "transformee", "structuree", "publiee"]
PIPELINE_LABELS = {
    "brute": "⬜ Donnée brute",
    "nettoyee": "🟦 Donnée nettoyée",
    "transformee": "🟪 Donnée transformée",
    "structuree": "🟩 Donnée structurée",
    "publiee": "✅ Donnée publiée",
}


def advance_pipeline(dataset_id: int, new_stage: str):
    """Advance a dataset through the construction pipeline."""
    con = get_connection()
    old = con.execute("SELECT etat FROM datasets WHERE id = ?", [dataset_id]).fetchone()
    old_etat = old[0] if old else "brute"
    con.execute("UPDATE datasets SET etat = ? WHERE id = ?", [new_stage, dataset_id])
    con.execute("UPDATE dataset_rows SET etat = ? WHERE dataset_id = ?", [new_stage, dataset_id])
    con.close()
    log_interaction("construction", f"Pipeline:{new_stage}", str(dataset_id), old_etat, new_stage)
    st.session_state.pipeline_stage = new_stage


# ---------------------------------------------------------------------------
# Component: Formulaire de saisie (Creer)
# ---------------------------------------------------------------------------

def render_formulaire():
    """
    Maps to: Formulaire ─[requiert]→ PipelineITO
    Action: Creer ─[declenche]→ DonneeBrute
    """
    st.subheader("📝 Créer un dataset")
    st.caption("_Formulaire de saisie — Input → Traitement conscient → Output_")

    with st.form("create_dataset", clear_on_submit=True):
        nom = st.text_input("Nom du dataset")
        description = st.text_area("Description")

        st.markdown("**Définir le schéma** (colonnes)")
        col_defs = st.text_area(
            "Colonnes (une par ligne, format: nom:type)",
            placeholder="nom:text\nage:integer\nville:text\nsalaire:float",
            height=120,
        )

        submitted = st.form_submit_button("✨ Créer", type="primary")

        if submitted and nom and col_defs:
            # Parse schema
            schema = {}
            for line in col_defs.strip().split("\n"):
                if ":" in line:
                    cname, ctype = line.split(":", 1)
                    schema[cname.strip()] = ctype.strip()

            con = get_connection()
            next_id = (con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM datasets").fetchone()[0])
            con.execute(
                "INSERT INTO datasets (id, nom, description, etat, schema_json) VALUES (?, ?, ?, 'brute', ?)",
                [next_id, nom, description, json.dumps(schema)]
            )
            con.close()
            log_interaction("construction", "Creer", str(next_id), "", "brute")
            st.session_state.current_dataset_id = next_id
            st.session_state.pipeline_stage = "brute"
            st.success(f"Dataset **{nom}** créé (id={next_id})")
            st.rerun()


# ---------------------------------------------------------------------------
# Component: TableauEditable (Creer + Transformer)
# ---------------------------------------------------------------------------

def render_tableau_editable(dataset_id: int):
    """
    Maps to: TableauEditable ─[representePar]→ Tableau
    Actions: Creer (add rows), Transformer (edit cells)
    """
    st.subheader("📊 Tableau éditable")
    st.caption("_Vue et édition simultanées — grille CRUD_")

    con = get_connection()
    ds = con.execute("SELECT * FROM datasets WHERE id = ?", [dataset_id]).fetchone()
    if not ds:
        st.warning("Dataset non trouvé.")
        con.close()
        return

    schema = json.loads(ds[5]) if ds[5] else {}
    rows = con.execute(
        "SELECT id, data_json, etat FROM dataset_rows WHERE dataset_id = ? ORDER BY id",
        [dataset_id]
    ).fetchall()
    con.close()

    # Build dataframe from stored JSON rows
    data = []
    row_ids = []
    for row in rows:
        row_ids.append(row[0])
        data.append(json.loads(row[1]))

    if data:
        df = pd.DataFrame(data)
    else:
        df = pd.DataFrame(columns=list(schema.keys()))

    # Editable table
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"editor_{dataset_id}",
    )

    col_save, col_add = st.columns(2)

    with col_save:
        if st.button("💾 Sauvegarder les modifications", type="primary"):
            con = get_connection()
            # Delete old rows and rewrite
            con.execute("DELETE FROM dataset_rows WHERE dataset_id = ?", [dataset_id])
            for i, (_, row) in enumerate(edited_df.iterrows()):
                row_data = row.to_dict()
                # Convert NaN to None for clean JSON
                row_data = {k: (None if pd.isna(v) else v) for k, v in row_data.items()}
                next_row_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM dataset_rows").fetchone()[0]
                con.execute(
                    "INSERT INTO dataset_rows (id, dataset_id, data_json, etat) VALUES (?, ?, ?, ?)",
                    [next_row_id, dataset_id, json.dumps(row_data, default=str),
                     st.session_state.pipeline_stage]
                )
            con.execute("UPDATE datasets SET nb_lignes = ? WHERE id = ?",
                        [len(edited_df), dataset_id])
            con.close()
            log_interaction("construction", "Transformer", str(dataset_id))
            st.success(f"✅ {len(edited_df)} lignes sauvegardées")
            st.rerun()

    return edited_df


# ---------------------------------------------------------------------------
# Component: PanneauRequete (Requeter)
# ---------------------------------------------------------------------------

def render_panneau_requete(dataset_id: int):
    """
    Maps to: PanneauRequete ─[requiert]→ StockDonnees
    Action: Requeter — interroger le stock via SQL
    """
    st.subheader("🔍 Panneau de requête")
    st.caption("_Requêter le stock de données via SQL (DuckDB)_")

    con = get_connection()
    rows = con.execute(
        "SELECT data_json FROM dataset_rows WHERE dataset_id = ? ORDER BY id",
        [dataset_id]
    ).fetchall()
    con.close()

    if not rows:
        st.info("Ajoutez des données dans le tableau pour pouvoir les requêter.")
        return

    data = [json.loads(r[0]) for r in rows]
    df = pd.DataFrame(data)

    st.markdown(f"**Colonnes disponibles** : `{', '.join(df.columns)}`")

    query = st.text_area(
        "Requête SQL",
        value=f"SELECT * FROM df LIMIT 10",
        height=100,
        help="Utilisez 'df' comme nom de table"
    )

    if st.button("▶️ Exécuter", type="primary"):
        try:
            result = duckdb.sql(query).df()
            st.dataframe(result, use_container_width=True)
            log_interaction("construction", "Requeter", str(dataset_id))
            st.success(f"✅ {len(result)} résultats")
        except Exception as e:
            st.error(f"Erreur SQL : {e}")


# ---------------------------------------------------------------------------
# Component: Pipeline controls (Nettoyer, Transformer, Structurer, Publier)
# ---------------------------------------------------------------------------

def render_pipeline_controls(dataset_id: int, df: pd.DataFrame):
    """
    Maps to the full construction pipeline:
      Brute → Nettoyée → Transformée → Structurée → Publiée
    Each step is a discrete, intentional action (TemporaliteDiscrete).
    """
    st.subheader("⚙️ Pipeline de construction")

    con = get_connection()
    ds = con.execute("SELECT etat FROM datasets WHERE id = ?", [dataset_id]).fetchone()
    con.close()
    current = ds[0] if ds else "brute"
    current_idx = PIPELINE_STAGES.index(current) if current in PIPELINE_STAGES else 0

    # Visual pipeline
    cols = st.columns(len(PIPELINE_STAGES))
    for i, stage in enumerate(PIPELINE_STAGES):
        with cols[i]:
            if i < current_idx:
                st.markdown(f"~~{PIPELINE_LABELS[stage]}~~")
            elif i == current_idx:
                st.markdown(f"**→ {PIPELINE_LABELS[stage]}**")
            else:
                st.markdown(f"{PIPELINE_LABELS[stage]}")

    st.markdown("---")

    if df is None or df.empty:
        st.info("Ajoutez des données pour avancer dans le pipeline.")
        return

    # Stage-specific actions
    if current == "brute":
        st.markdown("### 🧹 Nettoyer les données")
        st.caption("_Supprimer doublons, corriger erreurs, combler les vides_")
        col1, col2, col3 = st.columns(3)
        with col1:
            remove_dupes = st.checkbox("Supprimer les doublons")
        with col2:
            fill_na = st.checkbox("Remplir les valeurs vides")
        with col3:
            strip_spaces = st.checkbox("Nettoyer les espaces")

        if st.button("🧹 Nettoyer → Avancer", type="primary"):
            cleaned = df.copy()
            if remove_dupes:
                cleaned = cleaned.drop_duplicates()
            if fill_na:
                cleaned = cleaned.fillna("")
            if strip_spaces:
                for col in cleaned.select_dtypes(include="object").columns:
                    cleaned[col] = cleaned[col].str.strip()
            _save_df(dataset_id, cleaned)
            advance_pipeline(dataset_id, "nettoyee")
            st.success("✅ Données nettoyées")
            st.rerun()

    elif current == "nettoyee":
        st.markdown("### 🔄 Transformer les données")
        st.caption("_Restructurer selon votre modèle cible_")

        transforms = st.multiselect("Transformations à appliquer", [
            "Renommer des colonnes",
            "Filtrer les lignes",
            "Ajouter une colonne calculée",
            "Trier par colonne",
        ])

        transformed = df.copy()

        if "Renommer des colonnes" in transforms:
            rename_input = st.text_input("Renommages (ancien:nouveau, séparés par virgule)",
                                         placeholder="nom:name, ville:city")
            if rename_input:
                for pair in rename_input.split(","):
                    if ":" in pair:
                        old, new = pair.split(":", 1)
                        transformed = transformed.rename(columns={old.strip(): new.strip()})

        if "Filtrer les lignes" in transforms:
            filter_col = st.selectbox("Colonne à filtrer", transformed.columns)
            filter_val = st.text_input("Valeur à garder")
            if filter_val:
                transformed = transformed[transformed[filter_col].astype(str).str.contains(filter_val, na=False)]

        if "Trier par colonne" in transforms:
            sort_col = st.selectbox("Trier par", transformed.columns, key="sort_col")
            transformed = transformed.sort_values(sort_col)

        if st.button("🔄 Transformer → Avancer", type="primary"):
            _save_df(dataset_id, transformed)
            advance_pipeline(dataset_id, "transformee")
            st.success("✅ Données transformées")
            st.rerun()

    elif current == "transformee":
        st.markdown("### 🏗️ Structurer les données")
        st.caption("_Organiser dans un schéma formel — prêt à être interrogé_")

        st.markdown("**Schéma détecté :**")
        schema_info = {col: str(dtype) for col, dtype in df.dtypes.items()}
        st.json(schema_info)

        st.markdown("**Typage des colonnes :**")
        type_map = {}
        for col in df.columns:
            type_map[col] = st.selectbox(f"Type de `{col}`",
                                         ["text", "integer", "float", "date", "boolean"],
                                         key=f"type_{col}")

        if st.button("🏗️ Structurer → Avancer", type="primary"):
            con = get_connection()
            con.execute("UPDATE datasets SET schema_json = ? WHERE id = ?",
                        [json.dumps(type_map), dataset_id])
            con.close()
            advance_pipeline(dataset_id, "structuree")
            st.success("✅ Données structurées — schéma formel appliqué")
            st.rerun()

    elif current == "structuree":
        st.markdown("### ✅ Publier les données")
        st.caption("_Valider et rendre accessible — stock finalisé_")

        st.dataframe(df, use_container_width=True)
        st.metric("Lignes", len(df))
        st.metric("Colonnes", len(df.columns))

        if st.button("✅ Publier", type="primary"):
            advance_pipeline(dataset_id, "publiee")
            log_interaction("construction", "Valider", str(dataset_id), "structuree", "publiee")
            st.balloons()
            st.success("🎉 Dataset publié — donnée désormais dans le stock finalisé")
            st.rerun()

    elif current == "publiee":
        st.success("🎉 Ce dataset est publié.")
        st.dataframe(df, use_container_width=True)

        # Export (Exporter action)
        st.markdown("### 📤 Exporter")
        fmt = st.radio("Format", ["CSV", "JSON", "Parquet"], horizontal=True)
        if st.button("📤 Exporter"):
            if fmt == "CSV":
                data = df.to_csv(index=False)
                st.download_button("Télécharger CSV", data, "dataset.csv", "text/csv")
            elif fmt == "JSON":
                data = df.to_json(orient="records", force_ascii=False, indent=2)
                st.download_button("Télécharger JSON", data, "dataset.json", "application/json")
            elif fmt == "Parquet":
                buf = io.BytesIO()
                df.to_parquet(buf, index=False)
                st.download_button("Télécharger Parquet", buf.getvalue(), "dataset.parquet",
                                   "application/octet-stream")
            log_interaction("construction", "Exporter", str(dataset_id))


def _save_df(dataset_id: int, df: pd.DataFrame):
    """Persist a dataframe back to dataset_rows."""
    con = get_connection()
    con.execute("DELETE FROM dataset_rows WHERE dataset_id = ?", [dataset_id])
    for _, row in df.iterrows():
        row_data = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        next_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM dataset_rows").fetchone()[0]
        con.execute(
            "INSERT INTO dataset_rows (id, dataset_id, data_json, etat) VALUES (?, ?, ?, ?)",
            [next_id, dataset_id, json.dumps(row_data, default=str),
             st.session_state.pipeline_stage]
        )
    con.execute("UPDATE datasets SET nb_lignes = ? WHERE id = ?", [len(df), dataset_id])
    con.close()


# ---------------------------------------------------------------------------
# Sidebar: pipeline tracker + ontology
# ---------------------------------------------------------------------------

def render_sidebar():
    st.sidebar.markdown("### Pipeline de construction")
    st.sidebar.caption("Brute → Nettoyée → Transformée → Structurée → Publiée")

    con = get_connection()
    datasets = con.execute("SELECT id, nom, etat, nb_lignes FROM datasets ORDER BY id DESC").fetchall()
    con.close()

    if datasets:
        for ds in datasets:
            stage_label = PIPELINE_LABELS.get(ds[2], ds[2])
            st.sidebar.markdown(f"**{ds[1]}** ({ds[3]} lignes) — {stage_label}")
    else:
        st.sidebar.info("Aucun dataset créé.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Ontologie active")
    st.sidebar.caption("Composants: Formulaire, TableauEditable, PanneauRequete, Canvas, Terminal")
    st.sidebar.caption("Actions: Créer, Transformer, Requêter, Valider, Exporter")
    st.sidebar.caption("Prédicats: preserve(Attention), opereSur(StockDonnees)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Construction de données", layout="wide", page_icon="🔨")

    st.markdown("""
    # 🔨 Interface de Construction de Données
    > _Architecture où l'utilisateur construit activement des données via un cycle input-traitement-output_

    **Temporalité** : discrète · **Rôle** : constructeur actif · **Mécanisme** : Pipeline I-T-O
    """)

    init_state()
    init_db()
    render_sidebar()

    # --- Dataset selector ---
    con = get_connection()
    datasets = con.execute("SELECT id, nom, etat FROM datasets ORDER BY id DESC").fetchall()
    con.close()

    tab_create, tab_work = st.tabs(["📝 Créer un dataset", "⚙️ Travailler sur un dataset"])

    with tab_create:
        render_formulaire()

    with tab_work:
        if not datasets:
            st.info("Créez d'abord un dataset dans l'onglet **Créer**.")
            return

        ds_options = {f"{ds[1]} (id={ds[0]}, {PIPELINE_LABELS.get(ds[2], ds[2])})": ds[0] for ds in datasets}
        selected = st.selectbox("Dataset", list(ds_options.keys()))
        dataset_id = ds_options[selected]
        st.session_state.current_dataset_id = dataset_id

        # Load current stage
        con = get_connection()
        ds = con.execute("SELECT etat FROM datasets WHERE id = ?", [dataset_id]).fetchone()
        con.close()
        st.session_state.pipeline_stage = ds[0] if ds else "brute"

        # Render components
        col_table, col_query = st.columns([3, 2])

        with col_table:
            df = render_tableau_editable(dataset_id)

        with col_query:
            render_panneau_requete(dataset_id)

        st.markdown("---")
        render_pipeline_controls(dataset_id, df)


if __name__ == "__main__":
    main()
