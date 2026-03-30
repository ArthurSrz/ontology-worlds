"""
ontology_builder.py
-------------------
Builds a JSON-LD ontology file from a domain query using:
1. OKG API (discovery) — find ontologies/entities via Open Knowledge Graphs
2. Wikidata API (enrichment) — pull entity data, labels, relations

Pipeline:
    domain query → OKG search → wikidataIds → Wikidata enrichment → JSON-LD

Usage:
    python -m src.ontology_builder --domain "cosmetics regulation" --language fr --limit 30
"""

from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


# ---------------------------------------------------------------------------
# API endpoints (same as OKG MCP server uses internally)
# ---------------------------------------------------------------------------
OKG_API_URL = "https://api.openknowledgegraphs.com"
OKG_STATIC_URL = "https://openknowledgegraphs.com/data"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

# Wikidata properties to extract as relations
# Maps Wikidata property IDs to human-readable predicate names
WIKIDATA_RELATION_PROPERTIES = {
    "P31": "instanceOf",
    "P279": "subClassOf",
    "P361": "partOf",
    "P527": "hasPart",
    "P1269": "facetOf",
    "P155": "follows",
    "P156": "followedBy",
    "P1366": "replacedBy",
    "P1365": "replaces",
    "P137": "operator",
    "P127": "ownedBy",
    "P749": "parentOrganization",
    "P355": "subsidiaryOf",
    "P17": "country",
    "P131": "locatedIn",
    "P1001": "appliesToJurisdiction",
    "P2578": "studyOf",
    "P2579": "studiedIn",
}


def _require_httpx():
    if httpx is None:
        print("httpx is required for the ontology builder. Install with: pip install httpx", file=sys.stderr)
        sys.exit(1)


def _normalize_qid(value: str) -> str:
    """Extract Q-number from either 'Q123' or 'https://www.wikidata.org/wiki/Q123'."""
    if not value:
        return ""
    m = re.search(r"(Q\d+)", value)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# OKG Discovery
# ---------------------------------------------------------------------------

def okg_search(query: str, limit: int = 30) -> list[dict]:
    """Search OKG API for ontologies/entities related to the query."""
    _require_httpx()
    results = []

    # Semantic search
    try:
        resp = httpx.get(
            f"{OKG_API_URL}/search",
            params={"q": query, "limit": limit},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("results", []):
                results.append(item)
    except Exception as e:
        print(f"[OKG] Semantic search failed: {e}", file=sys.stderr)

    # Text search (static dataset)
    try:
        resp = httpx.get(f"{OKG_STATIC_URL}/ontologies.json", timeout=30)
        if resp.status_code == 200:
            ontologies = resp.json()
            terms = query.lower().split()
            for item in ontologies:
                if not isinstance(item, dict):
                    continue
                searchable = f"{item.get('title', '')} {item.get('description', '')} {item.get('category', '')}".lower()
                if all(t in searchable for t in terms):
                    # Deduplicate by wikidataId
                    wid = _normalize_qid(item.get("wikidataId", ""))
                    if wid and not any(_normalize_qid(r.get("wikidataId", "")) == wid for r in results):
                        item["match"] = "text"
                        results.append(item)
    except Exception as e:
        print(f"[OKG] Text search failed: {e}", file=sys.stderr)

    return results[:limit]


# ---------------------------------------------------------------------------
# Wikidata Enrichment
# ---------------------------------------------------------------------------

def wikidata_get_entities(qids: list[str], language: str = "en") -> dict[str, dict]:
    """Fetch entity data from Wikidata API for a batch of Q-numbers."""
    _require_httpx()
    entities = {}
    headers = {"User-Agent": "OntoKit/1.0 (ontology-builder; https://github.com/coreandgraphs)"}

    # Wikidata API accepts max 50 IDs per request
    for i in range(0, len(qids), 50):
        batch = qids[i:i + 50]
        try:
            resp = httpx.get(
                WIKIDATA_API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "languages": f"{language}|en",
                    "props": "labels|descriptions|claims",
                    "format": "json",
                },
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                for qid, entity in data.get("entities", {}).items():
                    if "missing" not in entity:
                        entities[qid] = entity
        except Exception as e:
            print(f"[Wikidata] Batch fetch failed for {batch[:3]}...: {e}", file=sys.stderr)

        # Rate limiting
        if i + 50 < len(qids):
            time.sleep(0.5)

    return entities


def _extract_label(entity: dict, language: str) -> str:
    """Extract best label from Wikidata entity."""
    labels = entity.get("labels", {})
    if language in labels:
        return labels[language]["value"]
    if "en" in labels:
        return labels["en"]["value"]
    # Fallback to any available label
    if labels:
        return next(iter(labels.values()))["value"]
    return entity.get("id", "Unknown")


def _extract_description(entity: dict, language: str) -> str:
    """Extract best description from Wikidata entity."""
    descs = entity.get("descriptions", {})
    if language in descs:
        return descs[language]["value"]
    if "en" in descs:
        return descs["en"]["value"]
    if descs:
        return next(iter(descs.values()))["value"]
    return ""


def _extract_relations(entity: dict, known_qids: set[str]) -> list[dict]:
    """
    Extract relations from Wikidata claims.
    Only includes relations where the target is also in the known set (closed world).
    """
    relations = []
    claims = entity.get("claims", {})
    qid = entity.get("id", "")

    for prop_id, prop_claims in claims.items():
        predicate = WIKIDATA_RELATION_PROPERTIES.get(prop_id)
        if not predicate:
            continue

        for claim in prop_claims:
            mainsnak = claim.get("mainsnak", {})
            if mainsnak.get("snaktype") != "value":
                continue
            datavalue = mainsnak.get("datavalue", {})
            if datavalue.get("type") != "wikibase-entityid":
                continue
            target_qid = "Q" + str(datavalue["value"].get("numeric-id", ""))
            if target_qid in known_qids:
                relations.append({
                    "subject": qid,
                    "predicate": predicate,
                    "object": target_qid,
                })

    return relations


# ---------------------------------------------------------------------------
# Graph Assembly
# ---------------------------------------------------------------------------

def build_ontology(
    domain: str,
    language: str = "en",
    limit: int = 30,
) -> dict:
    """
    Build a JSON-LD ontology from a domain query.

    Pipeline:
    1. OKG search → discover entities with wikidataIds
    2. Wikidata API → enrich with labels, descriptions, relations
    3. Assemble → JSON-LD format with metadata, classes, instances, relations
    """
    print(f"[Builder] Searching OKG for '{domain}'...", file=sys.stderr)
    okg_results = okg_search(domain, limit=limit)
    print(f"[Builder] Found {len(okg_results)} OKG results", file=sys.stderr)

    if not okg_results:
        print("[Builder] No results found. Cannot build ontology.", file=sys.stderr)
        return {}

    # Collect wikidataIds (handles both "Q123" and full URLs)
    qid_to_okg: dict[str, dict] = {}
    for item in okg_results:
        wid = _normalize_qid(item.get("wikidataId", ""))
        if wid:
            qid_to_okg[wid] = item

    if not qid_to_okg:
        print("[Builder] No Wikidata IDs found in OKG results.", file=sys.stderr)
        # Fall back to OKG-only ontology
        return _build_okg_only(domain, language, okg_results)

    qids = list(qid_to_okg.keys())
    print(f"[Builder] Enriching {len(qids)} entities from Wikidata...", file=sys.stderr)
    wd_entities = wikidata_get_entities(qids, language=language)
    print(f"[Builder] Got {len(wd_entities)} Wikidata entities", file=sys.stderr)

    known_qids = set(qids)

    # Build classes from OKG categories
    categories = sorted({item.get("category", "General") for item in okg_results if item.get("category")})
    classes = [{"id": _sanitize_id(cat), "label": cat, "description": f"Category: {cat}"} for cat in categories]

    # Build instances from OKG + Wikidata
    instances = []
    for qid in qids:
        okg_item = qid_to_okg[qid]
        wd_entity = wd_entities.get(qid, {})

        label = _extract_label(wd_entity, language) if wd_entity else okg_item.get("title", qid)
        description = _extract_description(wd_entity, language) if wd_entity else okg_item.get("description", "")
        category = okg_item.get("category", "General")

        instance = {
            "id": _sanitize_id(label),
            "class": _sanitize_id(category),
            "label": label,
            "wikidata": qid,
            "description": description,
            "properties": {},
        }

        # Add partOf from OKG if present
        part_of = okg_item.get("partOf")
        if part_of:
            instance["properties"]["partOf"] = _sanitize_id(part_of)

        instances.append(instance)

    # Build relations from Wikidata claims (closed world)
    all_relations = []
    instance_ids = {inst["wikidata"]: inst["id"] for inst in instances}

    for qid in qids:
        wd_entity = wd_entities.get(qid)
        if not wd_entity:
            continue
        wd_relations = _extract_relations(wd_entity, known_qids)
        for rel in wd_relations:
            subject_id = instance_ids.get(rel["subject"])
            object_id = instance_ids.get(rel["object"])
            if subject_id and object_id:
                all_relations.append({
                    "subject": subject_id,
                    "predicate": rel["predicate"],
                    "object": object_id,
                })

    # Add instanceOf relations
    for inst in instances:
        all_relations.append({
            "subject": inst["id"],
            "predicate": "instanceOf",
            "object": inst["class"],
        })

    # Infer valid_predicates from actual relations
    valid_predicates = sorted({rel["predicate"] for rel in all_relations})

    # Assemble JSON-LD
    domain_slug = re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")
    ontology = {
        "@context": {
            "wd": "http://www.wikidata.org/entity/",
            "wdt": "http://www.wikidata.org/prop/direct/",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "owl": "http://www.w3.org/2002/07/owl#",
            "schema": "http://schema.org/",
        },
        "metadata": {
            "name": domain.title(),
            "name_short": domain_slug,
            "description": f"Auto-generated ontology for: {domain}",
            "language": language,
            "version": "1.0.0",
            "domain": domain_slug,
            "source": "OKG + Wikidata",
        },
        "classes": classes,
        "instances": instances,
        "relations": all_relations,
        "valid_predicates": valid_predicates,
    }

    print(f"[Builder] Assembled: {len(classes)} classes, {len(instances)} instances, "
          f"{len(all_relations)} relations, {len(valid_predicates)} predicates", file=sys.stderr)

    return ontology


def _build_okg_only(domain: str, language: str, okg_results: list[dict]) -> dict:
    """Fallback: build ontology from OKG results only (no Wikidata enrichment)."""
    categories = sorted({item.get("category", "General") for item in okg_results if item.get("category")})
    classes = [{"id": _sanitize_id(cat), "label": cat} for cat in categories]

    instances = []
    relations = []
    for item in okg_results:
        title = item.get("title", "Unknown")
        inst_id = _sanitize_id(title)
        category = item.get("category", "General")
        instances.append({
            "id": inst_id,
            "class": _sanitize_id(category),
            "label": title,
            "wikidata": item.get("wikidataId"),
            "description": item.get("description", ""),
        })
        relations.append({"subject": inst_id, "predicate": "instanceOf", "object": _sanitize_id(category)})
        if item.get("partOf"):
            relations.append({"subject": inst_id, "predicate": "partOf", "object": _sanitize_id(item["partOf"])})

    domain_slug = re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")
    return {
        "@context": {"wd": "http://www.wikidata.org/entity/"},
        "metadata": {
            "name": domain.title(),
            "description": f"Auto-generated ontology for: {domain} (OKG only, no Wikidata enrichment)",
            "language": language,
            "version": "1.0.0",
            "domain": domain_slug,
            "source": "OKG",
        },
        "classes": classes,
        "instances": instances,
        "relations": relations,
        "valid_predicates": sorted({r["predicate"] for r in relations}),
    }


def _sanitize_id(text: str) -> str:
    """Convert a label to a valid ontology ID (PascalCase, no spaces)."""
    # Remove special characters, split into words
    words = re.sub(r"[^a-zA-Z0-9\s]", "", text).split()
    if not words:
        return "Unknown"
    return "".join(w.capitalize() for w in words)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build ontology from OKG + Wikidata")
    parser.add_argument("--domain", "-d", required=True, help="Domain query (e.g., 'cosmetics regulation')")
    parser.add_argument("--language", "-l", default="en", help="Language code (default: en)")
    parser.add_argument("--limit", type=int, default=30, help="Max entities to discover (default: 30)")
    parser.add_argument("--output", "-o", help="Output file path (default: ontology/<domain>_ontology.json)")
    args = parser.parse_args()

    ontology = build_ontology(args.domain, language=args.language, limit=args.limit)

    if not ontology:
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        domain_slug = re.sub(r"[^a-z0-9]+", "_", args.domain.lower()).strip("_")
        output_path = Path(__file__).parent.parent / "ontology" / f"{domain_slug}_ontology.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ontology, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Ontology written to {output_path}", file=sys.stderr)
    print(f"   {len(ontology['classes'])} classes, {len(ontology['instances'])} instances, "
          f"{len(ontology['relations'])} relations", file=sys.stderr)


if __name__ == "__main__":
    main()
