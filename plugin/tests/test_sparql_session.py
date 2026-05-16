"""
Tests for src/sparql_session.py — budget, cache, and Retry-After handling.

Uses respx to mock the Wikidata SPARQL endpoint without any network access.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx
import pytest
import respx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sparql_session import (
    MAX_RETRY_WAIT_S,
    SPARQL_ENDPOINT,
    SparqlSession,
)


def _ok(payload: list[dict] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"head": {"vars": ["x"]}, "results": {"bindings": payload or []}},
    )


def _429(retry_after: str | None) -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return httpx.Response(429, headers=headers, text="Too Many Requests")


@respx.mock
def test_caches_repeated_query():
    route = respx.get(SPARQL_ENDPOINT).mock(return_value=_ok([{"x": {"value": "Q1"}}]))
    with SparqlSession() as s:
        a = s.run("SELECT 1")
        b = s.run("SELECT 1")
    assert a == b
    # Cache hit means only one HTTP call.
    assert route.call_count == 1
    assert s.queries_made == 1


@respx.mock
def test_query_budget_exhausts():
    respx.get(SPARQL_ENDPOINT).mock(return_value=_ok())
    with SparqlSession(query_budget=2) as s:
        s.run("Q1")
        s.run("Q2")
        # Third call should refuse (budget exhausted) and return [].
        result = s.run("Q3")
    assert result == []
    assert s.queries_made == 2
    assert s.exhausted


@respx.mock
def test_short_retry_after_is_honoured_and_retries(monkeypatch):
    """Retry-After ≤ MAX_RETRY_WAIT_S → wait, then retry once."""
    slept: list[float] = []
    monkeypatch.setattr("src.sparql_session.time.sleep", lambda s: slept.append(s))

    # First call → 429, second call → 200
    route = respx.get(SPARQL_ENDPOINT).mock(
        side_effect=[_429("3"), _ok([{"x": {"value": "Q42"}}])]
    )
    with SparqlSession() as s:
        result = s.run("SELECT 1")

    assert result == [{"x": {"value": "Q42"}}]
    assert route.call_count == 2
    assert slept == [3.0]
    assert not s.cooled


@respx.mock
def test_long_retry_after_cools_turn(monkeypatch):
    """Retry-After > MAX_RETRY_WAIT_S → honour by giving up the turn, NOT retry."""
    slept: list[float] = []
    monkeypatch.setattr("src.sparql_session.time.sleep", lambda s: slept.append(s))

    huge = str(MAX_RETRY_WAIT_S + 100)
    route = respx.get(SPARQL_ENDPOINT).mock(return_value=_429(huge))
    with SparqlSession() as s:
        result = s.run("SELECT 1")

    assert result == []
    assert route.call_count == 1, "must not retry when server demands >MAX_RETRY_WAIT_S"
    assert slept == [], "must not sleep when honouring long Retry-After"
    assert s.cooled
    assert s.exhausted


@respx.mock
def test_cooled_session_short_circuits_subsequent_queries(monkeypatch):
    monkeypatch.setattr("src.sparql_session.time.sleep", lambda s: None)
    huge = str(MAX_RETRY_WAIT_S + 100)
    route = respx.get(SPARQL_ENDPOINT).mock(return_value=_429(huge))
    with SparqlSession() as s:
        s.run("SELECT 1")  # cools
        assert s.cooled
        result = s.run("SELECT 2")  # cached miss + exhausted → no wire call
    assert result == []
    assert route.call_count == 1


@respx.mock
def test_429_without_retry_after_uses_short_default(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("src.sparql_session.time.sleep", lambda s: slept.append(s))
    respx.get(SPARQL_ENDPOINT).mock(side_effect=[_429(None), _ok()])
    with SparqlSession() as s:
        s.run("SELECT 1")
    # Default short conservative wait (4s) when header absent.
    assert slept == [4.0]


def test_user_agent_is_policy_compliant():
    """UA must include contact info + library token per Wikimedia policy."""
    from src.sparql_session import USER_AGENT
    assert "(" in USER_AGENT and ")" in USER_AGENT, "contact-info parens required"
    assert "github.com" in USER_AGENT or "@" in USER_AGENT, "contact info required"
    assert "/" in USER_AGENT, "Client/version format required"
    assert "bot" in USER_AGENT.lower(), "should self-identify as bot"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
