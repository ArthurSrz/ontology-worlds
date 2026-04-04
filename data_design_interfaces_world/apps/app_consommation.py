"""
App Consommation — Architecture de consommation de données

Ontology mapping:
  Architecture:  ArchitectureConsommation
  Composants:    Feed, CarteContenu, Notification, Recommandation, BarreRecherche
  Actions:       Scroller, Liker, Partager, Sauvegarder
  Pipeline:      DonneeBrute → DonneeAlgorithmisee → DonneeAffichee → DonneeConsommee
  Temporalité:   Continue (scroll infini)
  Rôle:          ConsommateurDonnees (agency faible)
"""

import streamlit as st
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from data_store import get_connection, seed_feed, init_db, log_interaction, load_ontology


# ---------------------------------------------------------------------------
# State init
# ---------------------------------------------------------------------------

def init_state():
    if "feed_offset" not in st.session_state:
        st.session_state.feed_offset = 0
    if "consumed_ids" not in st.session_state:
        st.session_state.consumed_ids = set()
    if "saved_ids" not in st.session_state:
        st.session_state.saved_ids = set()
    if "liked_ids" not in st.session_state:
        st.session_state.liked_ids = set()
    if "notifs" not in st.session_state:
        st.session_state.notifs = []


# ---------------------------------------------------------------------------
# AlgorithmeFlux — sorts and prioritizes content
# ---------------------------------------------------------------------------

def algorithme_flux(items: list[dict], mode: str) -> list[dict]:
    """
    Maps to: AlgorithmeFlux → declenche → DonneeAlgorithmisee
    The algorithm decides what the user sees.
    """
    if mode == "Tendances":
        return sorted(items, key=lambda x: x["likes"] + x["partages"], reverse=True)
    elif mode == "Récent":
        return sorted(items, key=lambda x: x["id"], reverse=True)
    elif mode == "Pour vous":
        # Simulated personalization: boost categories the user has liked
        liked_cats = set()
        con = get_connection()
        for lid in st.session_state.liked_ids:
            row = con.execute("SELECT categorie FROM feed_items WHERE id = ?", [lid]).fetchone()
            if row:
                liked_cats.add(row[0])
        con.close()
        def score(item):
            base = item["score_algo"]
            if item["categorie"] in liked_cats:
                base += 0.5
            return base
        return sorted(items, key=score, reverse=True)
    return items


# ---------------------------------------------------------------------------
# UI Components — each maps to a ComposantInterface node
# ---------------------------------------------------------------------------

def render_notification_bar():
    """Maps to: Notification — signal push qui ramène dans le flux."""
    if not st.session_state.notifs:
        # Generate a fake notification occasionally
        if random.random() < 0.3:
            msgs = [
                "Nouveau contenu tendance dans **data**",
                "Un article que vous avez sauvegardé a été mis à jour",
                "3 nouveaux articles dans votre catégorie préférée",
                "Contenu recommandé basé sur vos likes récents",
            ]
            st.session_state.notifs.append(random.choice(msgs))

    if st.session_state.notifs:
        for notif in st.session_state.notifs:
            st.toast(notif, icon="🔔")
        st.session_state.notifs.clear()


def render_search_bar() -> str:
    """Maps to: BarreRecherche — filtrage dans les données exposées."""
    return st.text_input("🔍 Rechercher dans le flux", key="search_feed",
                         placeholder="Filtrer par mot-clé...")


def render_carte_contenu(item: dict, index: int):
    """
    Maps to: CarteContenu — unité visuelle résumant un élément.
    Each render = DonneeAffichee → DonneeConsommee transition.
    """
    item_id = item["id"]

    # Mark as consumed (DonneeAffichee → DonneeConsommee)
    if item_id not in st.session_state.consumed_ids:
        st.session_state.consumed_ids.add(item_id)
        con = get_connection()
        con.execute("UPDATE feed_items SET etat = 'consommee', vues = vues + 1 WHERE id = ?", [item_id])
        con.close()
        log_interaction("consommation", "Scroller", str(item_id), "affichee", "consommee")

    is_liked = item_id in st.session_state.liked_ids
    is_saved = item_id in st.session_state.saved_ids

    with st.container(border=True):
        cols = st.columns([6, 1])
        with cols[0]:
            st.markdown(f"**{item['titre']}**")
            st.caption(f"{item['source']}  ·  {item['categorie']}  ·  {item['vues']} vues")
        with cols[1]:
            st.caption(f"📊 {item['score_algo']:.2f}")

        st.markdown(item["contenu"][:200] + "..." if len(item["contenu"]) > 200 else item["contenu"])

        # Action buttons — low-effort interactions (ConsommateurDonnees)
        action_cols = st.columns(4)
        with action_cols[0]:
            label = f"{'❤️' if is_liked else '🤍'} {item['likes']}"
            if st.button(label, key=f"like_{item_id}_{index}"):
                handle_like(item_id)
        with action_cols[1]:
            if st.button(f"🔄 {item['partages']}", key=f"share_{item_id}_{index}"):
                handle_share(item_id)
        with action_cols[2]:
            label = "🔖 Sauvé" if is_saved else "📌 Sauver"
            if st.button(label, key=f"save_{item_id}_{index}"):
                handle_save(item_id)
        with action_cols[3]:
            st.caption(f"{'👁️ Vu' if item_id in st.session_state.consumed_ids else ''}")


def render_recommandations(current_items: list[dict]):
    """Maps to: Recommandation — prolonge la session de consommation."""
    if not current_items:
        return
    cats = list({i["categorie"] for i in current_items[:5]})
    con = get_connection()
    recs = con.execute(
        "SELECT * FROM feed_items WHERE categorie IN (SELECT unnest(?)) ORDER BY score_algo DESC LIMIT 3",
        [cats]
    ).fetchdf()
    con.close()

    if not recs.empty:
        st.markdown("---")
        st.subheader("💡 Recommandations")
        st.caption("_Suggestion algorithmique — prolonge le temps de consommation_")
        rec_cols = st.columns(3)
        for i, (_, row) in enumerate(recs.iterrows()):
            with rec_cols[i]:
                st.markdown(f"**{row['titre'][:50]}...**")
                st.caption(f"{row['source']} · ❤️ {row['likes']}")


# ---------------------------------------------------------------------------
# Action handlers — map to ActionUtilisateur
# ---------------------------------------------------------------------------

def handle_like(item_id: int):
    """Maps to: Liker — feedback minimal, effort cognitif faible."""
    con = get_connection()
    if item_id in st.session_state.liked_ids:
        st.session_state.liked_ids.discard(item_id)
        con.execute("UPDATE feed_items SET likes = likes - 1 WHERE id = ?", [item_id])
    else:
        st.session_state.liked_ids.add(item_id)
        con.execute("UPDATE feed_items SET likes = likes + 1 WHERE id = ?", [item_id])
        log_interaction("consommation", "Liker", str(item_id))
    con.close()


def handle_share(item_id: int):
    """Maps to: Partager — redistribuer dans le flux."""
    con = get_connection()
    con.execute("UPDATE feed_items SET partages = partages + 1 WHERE id = ?", [item_id])
    con.close()
    log_interaction("consommation", "Partager", str(item_id))
    st.toast("Partagé dans le flux", icon="🔄")


def handle_save(item_id: int):
    """
    Maps to: Sauvegarder — transition flux→stock.
    This is the ONLY action that crosses architecture boundaries.
    Sauvegarder ─[estTransformeEn]→ StockDonnees
    """
    if item_id in st.session_state.saved_ids:
        st.session_state.saved_ids.discard(item_id)
    else:
        st.session_state.saved_ids.add(item_id)
        con = get_connection()
        con.execute("UPDATE feed_items SET sauvegarde = TRUE WHERE id = ?", [item_id])
        con.close()
        log_interaction("consommation", "Sauvegarder", str(item_id), "consommee", "stock")
        st.toast("Sauvegardé dans votre stock personnel", icon="🔖")


# ---------------------------------------------------------------------------
# Pipeline visualization
# ---------------------------------------------------------------------------

def render_pipeline_status():
    """Show the consumption pipeline state."""
    con = get_connection()
    stats = con.execute("""
        SELECT etat, COUNT(*) as n FROM feed_items GROUP BY etat ORDER BY etat
    """).fetchdf()
    con.close()

    st.sidebar.markdown("### Pipeline de consommation")
    st.sidebar.caption("DonneeBrute → Algorithmisée → Affichée → Consommée")

    states = {"brute": 0, "algorithmisee": 0, "affichee": 0, "consommee": 0}
    for _, row in stats.iterrows():
        if row["etat"] in states:
            states[row["etat"]] = row["n"]

    total = max(sum(states.values()), 1)
    for state, count in states.items():
        pct = count / total
        emoji = {"brute": "⬜", "algorithmisee": "🟨", "affichee": "🟧", "consommee": "🟥"}
        st.sidebar.markdown(f"{emoji.get(state, '⬜')} **{state}**: {count} ({pct:.0%})")

    st.sidebar.markdown("---")
    st.sidebar.metric("Articles consommés", len(st.session_state.consumed_ids))
    st.sidebar.metric("Likes donnés", len(st.session_state.liked_ids))
    st.sidebar.metric("Sauvegardés (→ stock)", len(st.session_state.saved_ids))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Consommation de données", layout="wide", page_icon="📱")

    st.markdown("""
    # 📱 Interface de Consommation de Données
    > _Architecture où l'utilisateur consomme des données dans un flux continu et supposé infini_

    **Temporalité** : continue · **Rôle** : consommateur passif · **Mécanisme** : scroll infini + algorithme de flux
    """)

    init_state()
    init_db()
    seed_feed(50)

    # --- Sidebar: pipeline + ontology ---
    render_pipeline_status()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Ontologie active")
    st.sidebar.caption("Composants: Feed, CarteContenu, Notification, Recommandation, BarreRecherche")
    st.sidebar.caption("Actions: Scroller, Liker, Partager, Sauvegarder")
    st.sidebar.caption("Prédicats: consomme(Attention), opereSur(FluxDonnees)")

    # --- Notifications (push) ---
    render_notification_bar()

    # --- Algorithm selector (Categories) ---
    col_algo, col_cat = st.columns([2, 2])
    with col_algo:
        algo_mode = st.selectbox("🤖 Algorithme de flux", ["Pour vous", "Tendances", "Récent"],
                                 help="L'algorithme décide ce que vous voyez — agency faible")
    with col_cat:
        con = get_connection()
        all_cats = [r[0] for r in con.execute("SELECT DISTINCT categorie FROM feed_items").fetchall()]
        con.close()
        cat_filter = st.multiselect("📂 Catégories", all_cats, default=all_cats,
                                    help="Naviguer entre les sections de données exposées")

    # --- Search bar ---
    search_q = render_search_bar()

    # --- Load & algorithmize feed ---
    con = get_connection()
    items = con.execute("SELECT * FROM feed_items").fetchdf().to_dict("records")
    con.close()

    # Filter by category
    items = [i for i in items if i["categorie"] in cat_filter]

    # Filter by search
    if search_q:
        items = [i for i in items if search_q.lower() in i["titre"].lower()
                 or search_q.lower() in i["contenu"].lower()]

    # Mark as algorithmized (DonneeBrute → DonneeAlgorithmisee)
    con = get_connection()
    for item in items:
        if item["etat"] == "brute":
            con.execute("UPDATE feed_items SET etat = 'algorithmisee' WHERE id = ?", [item["id"]])
            item["etat"] = "algorithmisee"
    con.close()

    # Apply algorithm (DonneeAlgorithmisee → DonneeAffichee)
    items = algorithme_flux(items, algo_mode)

    con = get_connection()
    for item in items:
        if item["etat"] == "algorithmisee":
            con.execute("UPDATE feed_items SET etat = 'affichee' WHERE id = ?", [item["id"]])
            item["etat"] = "affichee"
    con.close()

    # --- THE FEED (scroll infini simulé) ---
    st.markdown("---")

    batch_size = 10
    end = st.session_state.feed_offset + batch_size
    visible_items = items[:end]

    for i, item in enumerate(visible_items):
        render_carte_contenu(item, i)

    # "Infinite scroll" — load more button
    if end < len(items):
        st.markdown("---")
        if st.button("⬇️ Charger plus de contenu", use_container_width=True, type="primary"):
            st.session_state.feed_offset += batch_size
            log_interaction("consommation", "Scroller", f"offset_{end}")
            st.rerun()
        st.caption(f"_Le flux continue... {len(items) - end} articles en attente_")
    else:
        st.info("Vous avez tout consommé. Le flux se renouvellera bientôt.")

    # --- Recommendations ---
    render_recommandations(visible_items)

    # --- Saved items (stock personnel) ---
    if st.session_state.saved_ids:
        st.markdown("---")
        st.subheader("🔖 Votre stock personnel")
        st.caption("_Sauvegarder ─[estTransformeEn]→ StockDonnees — transition flux→stock_")
        con = get_connection()
        saved = con.execute(
            f"SELECT titre, source, categorie FROM feed_items WHERE id IN ({','.join(map(str, st.session_state.saved_ids))})"
        ).fetchdf()
        con.close()
        st.dataframe(saved, use_container_width=True)


if __name__ == "__main__":
    main()
