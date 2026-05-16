"""Pydantic input models for the Wikidata MCP tools."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchEntitiesInput(BaseModel):
    query: str = Field(..., description="Search text (label, alias, or description)")
    language: str = Field("en", description="Language code (default: en)")
    limit: int = Field(10, ge=1, le=50, description="Max results (1–50, default: 10)")
    type: str = Field(
        "item",
        description="Entity type: 'item' (Q-entities) or 'property' (P-properties)",
    )


class GetEntityInput(BaseModel):
    entity_id: str = Field(..., description="Wikidata entity ID, e.g. Q42 or P31")
    language: str = Field("en", description="Language for labels/descriptions")


class GetRelationsInput(BaseModel):
    entity_id: str = Field(..., description="Wikidata entity ID, e.g. Q42")
    language: str = Field("en", description="Language for labels/descriptions")
    limit: int = Field(50, ge=1, le=200, description="Max relations to return")


class FindByPropertyInput(BaseModel):
    property_id: str = Field(..., description="Property ID, e.g. P31 (instance of)")
    value: str = Field(..., description="Value to match — a Q-ID (e.g. Q5) or string literal")
    language: str = Field("en", description="Language for labels")
    limit: int = Field(20, ge=1, le=100, description="Max results")


class SparqlQueryInput(BaseModel):
    query: str = Field(..., description="SPARQL query string (SELECT or CONSTRUCT)")
