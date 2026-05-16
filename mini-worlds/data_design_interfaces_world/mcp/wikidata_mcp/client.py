"""HTTP client for the Wikidata Action API and SPARQL endpoint."""

from __future__ import annotations

from typing import Any

import httpx

ACTION_API = "https://www.wikidata.org/w/api.php"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
TIMEOUT = 30.0
USER_AGENT = "ontology-worlds-mcp/1.0 (https://github.com/coreandgraphs/ontology-worlds)"

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ── Action API helpers ─────────────────────────────────────────────

async def action_api(params: dict[str, Any]) -> dict[str, Any]:
    """Call the Wikidata Action API (always JSON format)."""
    params = {**params, "format": "json", "origin": "*"}
    client = get_http_client()
    resp = await client.get(ACTION_API, params=params)
    resp.raise_for_status()
    return resp.json()


async def search_entities(
    query: str,
    language: str = "en",
    limit: int = 10,
    entity_type: str = "item",
) -> list[dict[str, Any]]:
    """wbsearchentities — free-text search over labels and aliases."""
    data = await action_api({
        "action": "wbsearchentities",
        "search": query,
        "language": language,
        "limit": limit,
        "type": entity_type,
    })
    return data.get("search", [])


async def get_entities(
    ids: list[str],
    language: str = "en",
    props: str = "labels|descriptions|aliases|claims|sitelinks",
) -> dict[str, Any]:
    """wbgetentities — fetch full entity data by ID."""
    data = await action_api({
        "action": "wbgetentities",
        "ids": "|".join(ids),
        "languages": language,
        "props": props,
    })
    return data.get("entities", {})


# ── SPARQL helper ──────────────────────────────────────────────────

async def sparql_query(query: str) -> list[dict[str, Any]]:
    """Run a SPARQL SELECT query against query.wikidata.org."""
    client = get_http_client()
    resp = await client.get(
        SPARQL_ENDPOINT,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", {}).get("bindings", [])


# ── Formatting helpers ─────────────────────────────────────────────

def _label(entity: dict[str, Any], lang: str) -> str:
    labels = entity.get("labels", {})
    if lang in labels:
        return labels[lang]["value"]
    if labels:
        return next(iter(labels.values()))["value"]
    return entity.get("id", "?")


def _desc(entity: dict[str, Any], lang: str) -> str:
    descs = entity.get("descriptions", {})
    if lang in descs:
        return descs[lang]["value"]
    return ""


def _snak_value(snak: dict[str, Any]) -> str | None:
    """Extract a human-readable value from a claim snak."""
    if snak.get("snaktype") != "value":
        return None
    dv = snak.get("datavalue", {})
    vtype = dv.get("type")
    val = dv.get("value")
    if vtype == "wikibase-entityid":
        return val.get("id")
    if vtype == "string":
        return val
    if vtype == "monolingualtext":
        return val.get("text")
    if vtype == "time":
        return val.get("time", "")
    if vtype == "quantity":
        return val.get("amount", "")
    if vtype == "globecoordinate":
        return f"{val.get('latitude')}, {val.get('longitude')}"
    return str(val)


def format_entity(entity: dict[str, Any], lang: str) -> str:
    """Format a single entity into readable Markdown."""
    eid = entity.get("id", "?")
    label = _label(entity, lang)
    desc = _desc(entity, lang)
    lines = [f"### {label} ({eid})", ""]
    if desc:
        lines.append(f"*{desc}*\n")

    # Aliases
    aliases = entity.get("aliases", {}).get(lang, [])
    if aliases:
        alias_list = ", ".join(a["value"] for a in aliases)
        lines.append(f"**Aliases:** {alias_list}\n")

    # Claims summary (top-level property → values)
    claims = entity.get("claims", {})
    if claims:
        lines.append("**Statements:**\n")
        for pid, stmts in list(claims.items())[:30]:
            vals = []
            for stmt in stmts[:5]:
                v = _snak_value(stmt.get("mainsnak", {}))
                if v:
                    vals.append(v)
            if vals:
                lines.append(f"- **{pid}**: {', '.join(vals)}")
        lines.append("")

    return "\n".join(lines)


def format_relations(entity: dict[str, Any], lang: str, limit: int) -> str:
    """Format entity claims as a relation list."""
    eid = entity.get("id", "?")
    label = _label(entity, lang)
    lines = [f"### Relations of {label} ({eid})\n"]
    claims = entity.get("claims", {})
    count = 0
    for pid, stmts in claims.items():
        for stmt in stmts:
            v = _snak_value(stmt.get("mainsnak", {}))
            if v:
                lines.append(f"- {eid} —[{pid}]→ {v}")
                count += 1
                if count >= limit:
                    break
        if count >= limit:
            break
    if count == 0:
        lines.append("*No relations found.*")
    return "\n".join(lines)


def handle_api_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 429:
            return "Error: Wikidata rate limit exceeded. Please wait and retry."
        return f"Error: Wikidata API returned status {status}."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out after 30s."
    return f"Error: {type(e).__name__}: {e}"
