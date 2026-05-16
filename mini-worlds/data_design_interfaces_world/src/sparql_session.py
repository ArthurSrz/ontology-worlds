"""
sparql_session.py
-----------------
Single per-turn session object that wraps the Wikidata SPARQL endpoint
according to the Wikidata Query Service rate-limit policy:

  - 60s of processing time per (UA + IP) per 60s window
  - Max 5 parallel queries per IP
  - Honour Retry-After on 429 (ignoring → temporary ban)
  - User-Agent: Client/version (contact) library/version, "bot" for automation
    https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy

The SparqlSession is created once per UserPromptSubmit invocation. It:
  - sends a compliant User-Agent
  - caches every query result by query string (turn-scoped LRU)
  - tracks total elapsed processing time + query count and refuses
    further calls once a per-turn budget is exhausted
  - on 429, honours Retry-After but caps the wait at MAX_RETRY_WAIT;
    if the server demands more, the session goes into a "cooled" state
    and degrades gracefully (subsequent calls return [] without hitting
    the wire) until the next turn.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import httpx

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = (
    "ontology-worlds-bot/0.3 "
    "(https://github.com/ArthurSrz/ontology-worlds; arthur.sarazin@etu-iepg.fr) "
    "httpx/0.27"
)

# Per-turn safety budget. Hooks should fail-fast rather than monopolise the
# Wikidata endpoint or stall Claude Code waiting on a slow query path.
# Wikidata's published limit is 60s of processing time per (UA+IP) per 60s
# window; we stay safely below that.
DEFAULT_QUERY_BUDGET = 60         # max SPARQL calls per turn
DEFAULT_PROCESSING_BUDGET_S = 55  # cumulative wall-time spent in _run_sparql
MAX_RETRY_WAIT_S = 12             # if Retry-After > this, give up the turn
DEFAULT_TIMEOUT_S = 15            # per-query timeout (Wikidata hard cap is 60s)


def _log(msg: str) -> None:
    print(f"[sparql] {msg}", file=sys.stderr)


@dataclass
class SparqlSession:
    client: httpx.Client | None = None
    query_budget: int = DEFAULT_QUERY_BUDGET
    processing_budget_s: float = DEFAULT_PROCESSING_BUDGET_S
    timeout_s: float = DEFAULT_TIMEOUT_S

    # State
    queries_made: int = 0
    elapsed_s: float = 0.0
    cooled: bool = False
    cache: dict[str, list[dict]] = field(default_factory=dict)
    # wbsearch cache: shared across all callers in one turn so the
    # entity_extractor's resolution and the disambiguator's debug
    # explainer don't issue duplicate Action-API calls.
    wbsearch_cache: dict[tuple[str, str, int], list[dict]] = field(default_factory=dict)
    _owns_client: bool = False

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = httpx.Client(headers={"User-Agent": USER_AGENT})
            self._owns_client = True

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    def __enter__(self) -> "SparqlSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    # ------------------------------------------------------------------
    # Status / budget helpers
    # ------------------------------------------------------------------
    @property
    def exhausted(self) -> bool:
        return (
            self.cooled
            or self.queries_made >= self.query_budget
            or self.elapsed_s >= self.processing_budget_s
        )

    def status_line(self) -> str:
        return (
            f"queries={self.queries_made}/{self.query_budget} "
            f"elapsed={self.elapsed_s:.1f}s/{self.processing_budget_s:.0f}s "
            f"cooled={self.cooled}"
        )

    # ------------------------------------------------------------------
    # The single SPARQL entrypoint everyone else routes through
    # ------------------------------------------------------------------
    def run(self, query: str) -> list[dict]:
        if query in self.cache:
            return self.cache[query]

        if self.exhausted:
            _log(f"budget exhausted; refusing query ({self.status_line()})")
            return []

        started = time.monotonic()
        bindings = self._do_request(query, _retried=False)
        elapsed = time.monotonic() - started

        self.queries_made += 1
        self.elapsed_s += elapsed
        self.cache[query] = bindings
        return bindings

    # ------------------------------------------------------------------
    # Wire-level request + 429-aware retry
    # ------------------------------------------------------------------
    def _do_request(self, query: str, _retried: bool) -> list[dict]:
        assert self.client is not None
        try:
            r = self.client.get(
                SPARQL_ENDPOINT,
                params={"query": query, "format": "json"},
                headers={"Accept": "application/sparql-results+json"},
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as e:
            _log(f"network error: {e}")
            return []

        if r.status_code == 429:
            retry_after_h = r.headers.get("retry-after", "")
            wait_s: float | None = None
            if retry_after_h.isdigit():
                wait_s = float(retry_after_h)

            if wait_s is None:
                wait_s = 4.0  # unknown — short conservative wait
            if wait_s > MAX_RETRY_WAIT_S:
                _log(
                    f"429: server asked for {wait_s:.0f}s cooldown — "
                    f"exceeds MAX_RETRY_WAIT_S={MAX_RETRY_WAIT_S}s. "
                    f"Honouring the Retry-After by NOT retrying this turn "
                    f"(per Wikidata policy)."
                )
                self.cooled = True
                return []
            if _retried:
                _log(f"429 again after {wait_s:.1f}s wait — cooling turn")
                self.cooled = True
                return []
            _log(f"429: sleeping {wait_s:.1f}s before single retry")
            time.sleep(wait_s)
            return self._do_request(query, _retried=True)

        if r.status_code != 200:
            _log(f"HTTP {r.status_code}: {r.text[:200]}")
            return []

        try:
            return r.json().get("results", {}).get("bindings", [])
        except ValueError as e:
            _log(f"non-JSON response: {e}")
            return []
