"""
Regression test for mutual-context disambiguation.

Uses respx to mock both wbsearchentities (Action API) and the SPARQL
endpoint so the behaviour is deterministic without any network. The
scenario reproduces the "drive vs walk" problem: context-free
disambiguation picks the film/photographer; mutual-context must pick
the activity senses because they share ancestors.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import respx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.disambiguator import mutual_context_resolve
from src.sparql_session import SparqlSession

WBSEARCH_URL = "https://www.wikidata.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"


# Mock candidate pools per (search term, language)
# Realistic shape: each "drive" search returns the film first; each
# "driving" search returns the activity. The optimiser must combine.
WBSEARCH_HITS = {
    ("drive", "en"): [
        {"id": "Q105086487", "label": "Drive", "description": "film"},
    ],
    ("driving", "en"): [
        {"id": "Q999646", "label": "driving", "description": "operation of a land vehicle"},
    ],
    ("walk", "en"): [
        {"id": "Q323774", "label": "Valka", "description": "town in Latvia"},
    ],
    ("walking", "en"): [
        {"id": "Q6537379", "label": "walking", "description": "gait of locomotion"},
    ],
    ("car", "en"): [
        {"id": "Q1420", "label": "car", "description": "motorized road vehicle"},
    ],
    # The bigram "carring" or "caring" — our gerund variant — would also
    # be queried for unigram "car"; return nothing.
    ("caring", "en"): [],
}


# Ancestor map: which ancestors each candidate Q-ID has.
# Q999646 (driving) and Q1420 (car) share "vehicle"-related ancestors.
# Q6537379 (walking) shares "activity" ancestors with Q999646 (driving).
# Q105086487 (Drive film) and Q323774 (Valka) have media/place ancestors
# that DON'T overlap with the others.
ANCESTORS = {
    "Q999646":   {"Q1914636", "Q451967", "Q1190554", "Q205961"},     # activity, intentional, occurrence, skill
    "Q6537379":  {"Q1914636", "Q451967", "Q1190554", "Q349"},         # activity, intentional, occurrence, sport
    "Q1420":     {"Q42889", "Q752870", "Q11442"},                     # vehicle, motor vehicle, bicycle-like
    "Q105086487": {"Q11424", "Q4502142"},                             # film, visual artwork
    "Q323774":   {"Q515", "Q1549591"},                                # city, town
}


def _wbsearch_response(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    key = (params.get("search", ""), params.get("language", "en"))
    return httpx.Response(
        200,
        json={"search": WBSEARCH_HITS.get(key, [])},
    )


def _sparql_response(request: httpx.Request) -> httpx.Response:
    q = request.url.params.get("query", "")
    # Identify ancestor batch query: contains "VALUES ?item"
    if "VALUES ?item" in q and "?anc" in q:
        bindings = []
        for qid, ancs in ANCESTORS.items():
            if f"wd:{qid}" in q:
                for anc in ancs:
                    bindings.append({
                        "item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"},
                        "anc":  {"type": "uri", "value": f"http://www.wikidata.org/entity/{anc}"},
                    })
        return httpx.Response(200, json={
            "head": {"vars": ["item", "anc"]},
            "results": {"bindings": bindings},
        })
    return httpx.Response(200, json={"head": {"vars": []}, "results": {"bindings": []}})


@respx.mock
def test_mutual_context_picks_activity_senses_over_film_and_place():
    """
    Surfaces ['drive', 'walk', 'car'] with film/town/vehicle candidates.

    Context-free disambiguation would pick:
        drive → Drive (film) Q105086487
        walk  → Valka       Q323774
        car   → car         Q1420  (only option)

    Mutual-context should pick:
        drive → driving Q999646   (activity, shares ancestors with walking)
        walk  → walking Q6537379
        car   → car     Q1420
    """
    respx.get(WBSEARCH_URL).mock(side_effect=_wbsearch_response)
    respx.get(SPARQL_URL).mock(side_effect=_sparql_response)

    with SparqlSession() as session:
        mentions = mutual_context_resolve(
            surfaces=["drive", "walk", "car"],
            session=session,
            top_k=2,
        )

    qids = {m.surface: m.qid for m in mentions}
    assert qids["drive"] == "Q999646", (
        f"drive should resolve to driving (Q999646) via gerund + mutual "
        f"context, got {qids['drive']}"
    )
    assert qids["walk"] == "Q6537379", (
        f"walk should resolve to walking (Q6537379), got {qids['walk']}"
    )
    assert qids["car"] == "Q1420"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
