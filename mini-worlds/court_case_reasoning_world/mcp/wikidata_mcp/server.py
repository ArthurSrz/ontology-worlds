"""MCP server for querying the Wikidata knowledge graph.

Provides five tools: search_entities, get_entity, get_relations,
find_by_property, and sparql_query.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from wikidata_mcp.client import (
    close_http_client,
    format_entity,
    format_relations,
    get_entities,
    handle_api_error,
    search_entities as _search,
    sparql_query as _sparql,
)
from wikidata_mcp.models import (
    FindByPropertyInput,
    GetEntityInput,
    GetRelationsInput,
    SearchEntitiesInput,
    SparqlQueryInput,
)


@asynccontextmanager
async def lifespan(_mcp: FastMCP):
    yield
    await close_http_client()


mcp = FastMCP("wikidata_mcp", lifespan=lifespan)


# ── Tools ──────────────────────────────────────────────────────────


@mcp.tool(
    name="search_entities",
    annotations={
        "title": "Search Wikidata Entities",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_entities(params: SearchEntitiesInput) -> str:
    """Free-text search over Wikidata entity labels and aliases.

    Returns matching entities with their IDs, labels, descriptions,
    and Wikidata URLs. Use this as the starting point to discover
    entity IDs for further exploration.

    Args:
        params: query, language, limit, type (item or property)

    Returns:
        Markdown-formatted list of matching entities.
    """
    try:
        results = await _search(
            params.query,
            language=params.language,
            limit=params.limit,
            entity_type=params.type,
        )
        if not results:
            return f"No entities found for '{params.query}'."
        lines = [f"## Wikidata search: '{params.query}'\n"]
        for r in results:
            eid = r.get("id", "?")
            label = r.get("label", eid)
            desc = r.get("description", "")
            url = r.get("concepturi", f"https://www.wikidata.org/wiki/{eid}")
            lines.append(f"- **{label}** ([{eid}]({url}))")
            if desc:
                lines.append(f"  {desc}")
        return "\n".join(lines)
    except Exception as e:
        return handle_api_error(e)


@mcp.tool(
    name="get_entity",
    annotations={
        "title": "Get Wikidata Entity",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_entity(params: GetEntityInput) -> str:
    """Fetch full details for a Wikidata entity by its ID.

    Returns the entity's label, description, aliases, and all
    statements (property–value pairs).

    Args:
        params: entity_id (Q42, P31, etc.), language

    Returns:
        Markdown-formatted entity profile with all statements.
    """
    try:
        entities = await get_entities([params.entity_id], language=params.language)
        entity = entities.get(params.entity_id)
        if not entity or "missing" in entity:
            return f"Entity {params.entity_id} not found."
        return format_entity(entity, params.language)
    except Exception as e:
        return handle_api_error(e)


@mcp.tool(
    name="get_relations",
    annotations={
        "title": "Get Entity Relations",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_relations(params: GetRelationsInput) -> str:
    """Get all outgoing relations (statements) for an entity.

    Each relation is formatted as: subject —[property]→ value.
    Use this to explore the knowledge graph around an entity.

    Args:
        params: entity_id, language, limit

    Returns:
        Markdown-formatted relation list.
    """
    try:
        entities = await get_entities(
            [params.entity_id],
            language=params.language,
            props="labels|descriptions|claims",
        )
        entity = entities.get(params.entity_id)
        if not entity or "missing" in entity:
            return f"Entity {params.entity_id} not found."
        return format_relations(entity, params.language, params.limit)
    except Exception as e:
        return handle_api_error(e)


@mcp.tool(
    name="find_by_property",
    annotations={
        "title": "Find Entities by Property",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def find_by_property(params: FindByPropertyInput) -> str:
    """Find entities that have a specific property value.

    For example: find all entities where P31 (instance of) = Q5 (human).
    Uses SPARQL under the hood.

    Args:
        params: property_id, value (Q-ID or string), language, limit

    Returns:
        Markdown-formatted list of matching entities.
    """
    try:
        value = params.value.strip()
        # Determine if value is an entity reference or a literal
        if value.startswith("Q") and value[1:].isdigit():
            value_clause = f"wd:{value}"
        elif value.startswith("P") and value[1:].isdigit():
            value_clause = f"wd:{value}"
        else:
            value_clause = f'"{value}"'

        query = f"""
SELECT ?item ?itemLabel ?itemDescription WHERE {{
  ?item wdt:{params.property_id} {value_clause} .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{params.language},en". }}
}}
LIMIT {params.limit}
"""
        bindings = await _sparql(query)
        if not bindings:
            return f"No entities found with {params.property_id} = {params.value}."
        lines = [f"## Entities where {params.property_id} = {params.value}\n"]
        for b in bindings:
            uri = b.get("item", {}).get("value", "")
            eid = uri.rsplit("/", 1)[-1] if uri else "?"
            label = b.get("itemLabel", {}).get("value", eid)
            desc = b.get("itemDescription", {}).get("value", "")
            lines.append(f"- **{label}** ({eid})")
            if desc:
                lines.append(f"  {desc}")
        return "\n".join(lines)
    except Exception as e:
        return handle_api_error(e)


@mcp.tool(
    name="sparql_query",
    annotations={
        "title": "Run SPARQL Query",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sparql_query(params: SparqlQueryInput) -> str:
    """Execute an arbitrary SPARQL query against the Wikidata Query Service.

    Returns results formatted as a Markdown table. Use standard Wikidata
    prefixes (wd:, wdt:, p:, ps:, wikibase:, etc.).

    Args:
        params: query (SPARQL SELECT or CONSTRUCT string)

    Returns:
        Markdown table of results or error message.
    """
    try:
        bindings = await _sparql(params.query)
        if not bindings:
            return "Query returned no results."
        # Build a markdown table from the bindings
        keys = list(bindings[0].keys())
        header = "| " + " | ".join(keys) + " |"
        sep = "| " + " | ".join("---" for _ in keys) + " |"
        rows = []
        for b in bindings[:100]:
            cells = []
            for k in keys:
                cell = b.get(k, {})
                cells.append(cell.get("value", "") if isinstance(cell, dict) else str(cell))
            rows.append("| " + " | ".join(cells) + " |")
        return "\n".join([header, sep, *rows])
    except Exception as e:
        return handle_api_error(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
