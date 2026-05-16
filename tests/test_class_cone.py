"""
Tests for class_cone_path and the class-aware gap detector.

The query shape is validated by inspecting the generated SPARQL; the
reachability logic is exercised end-to-end via respx-mocked HTTP.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import respx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sparql_expander import class_cone_path, DOMAIN_PROPERTIES
from src.sparql_session import SPARQL_ENDPOINT, SparqlSession


def _ok(bindings: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"head": {"vars": ["s_anc", "prop", "o_anc"]},
              "results": {"bindings": bindings}},
    )


def _binding(s_anc: str, prop: str, o_anc: str) -> dict:
    return {
        "s_anc": {"type": "uri", "value": f"http://www.wikidata.org/entity/{s_anc}"},
        "prop":  {"type": "uri", "value": f"http://www.wikidata.org/prop/direct/{prop}"},
        "o_anc": {"type": "uri", "value": f"http://www.wikidata.org/entity/{o_anc}"},
    }


@respx.mock
def test_returns_tuple_when_reachable():
    """Reachable pair returns (s_ancestor, property, o_ancestor)."""
    respx.get(SPARQL_ENDPOINT).mock(
        return_value=_ok([_binding("Q42889", "P2283", "Q28692567")])
    )
    with SparqlSession() as s:
        result = class_cone_path("Q999646", "Q1420", session=s)
    assert result == ("Q42889", "P2283", "Q28692567")


@respx.mock
def test_returns_none_when_no_path():
    respx.get(SPARQL_ENDPOINT).mock(return_value=_ok([]))
    with SparqlSession() as s:
        result = class_cone_path("Q1", "Q2", session=s)
    assert result is None


@respx.mock
def test_excludes_hierarchy_properties_by_default():
    """The query must NOT match on P31/P279 — they build the cones."""
    captured: dict = {}
    def capture(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params.get("query", "")
        return _ok([])
    respx.get(SPARQL_ENDPOINT).mock(side_effect=capture)
    with SparqlSession() as s:
        class_cone_path("Q999646", "Q1420", session=s)
    q = captured["query"]
    # VALUES ?prop clause must list only "domain-defining" non-hierarchy props
    values_section = q.split("VALUES ?prop {", 1)[1].split("}", 1)[0]
    assert "wdt:P31" not in values_section, (
        "P31 must not be in the match-property set — it builds the cone"
    )
    assert "wdt:P279" not in values_section, (
        "P279 must not be in the match-property set — it builds the cone"
    )
    assert "wdt:P2283" in values_section
    assert "wdt:P527" in values_section


@respx.mock
def test_cone_query_walks_up_subclass_tree():
    """Generated SPARQL must include depth-1, 2, and 3 ancestor branches."""
    captured: dict = {}
    def capture(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params.get("query", "")
        return _ok([])
    respx.get(SPARQL_ENDPOINT).mock(side_effect=capture)
    with SparqlSession() as s:
        class_cone_path("Q999646", "Q1420", session=s, max_up_hops=3)
    q = captured["query"]
    # Depth 0: BIND of the entity itself
    assert "BIND(wd:Q999646 AS ?s_anc)" in q
    assert "BIND(wd:Q1420 AS ?o_anc)" in q
    # Depth 1: P31|P279
    assert "wd:Q999646 wdt:P31|wdt:P279 ?s_anc" in q
    # Depth 2: chained P279
    assert "?s_anc_m1 wdt:P279 ?s_anc" in q
    # Depth 3: deeper chain
    assert "?s_anc_m1 wdt:P279 ?s_anc_m2" in q


@respx.mock
def test_query_checks_both_directions():
    """Cross-cone match must allow subject→object AND object→subject."""
    captured: dict = {}
    def capture(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params.get("query", "")
        return _ok([])
    respx.get(SPARQL_ENDPOINT).mock(side_effect=capture)
    with SparqlSession() as s:
        class_cone_path("Q999646", "Q1420", session=s)
    q = captured["query"]
    assert "?s_anc ?prop ?o_anc" in q
    assert "?o_anc ?prop ?s_anc" in q


@respx.mock
def test_respects_session_budget():
    """When session is exhausted, returns None without hitting the wire."""
    route = respx.get(SPARQL_ENDPOINT).mock(return_value=_ok([]))
    with SparqlSession(query_budget=0) as s:
        result = class_cone_path("Q1", "Q2", session=s)
    assert result is None
    assert route.call_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
