"""
sparql_expander.py
------------------
Bounded BFS expansion of a seed-Q-ID list into a domain subgraph via the
public Wikidata SPARQL endpoint.

Walks only "domain-defining" properties (P31, P279, P361, P527, P2283,
P1535, P366, P1542). Batches all seeds per layer into a single SPARQL UNION
to avoid N×M round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import httpx

from .sparql_session import SparqlSession

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

# Properties that define "what this concept is about" — used for BFS edges.
DOMAIN_PROPERTIES: dict[str, str] = {
    "P31": "instance of",
    "P279": "subclass of",
    "P361": "part of",
    "P527": "has part",
    "P2283": "uses",
    "P1535": "used by",
    "P366": "has use",
    "P1542": "has effect",
}


@dataclass
class DomainEdge:
    subject: str   # Q-id
    predicate: str # P-id
    object: str    # Q-id

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.subject, self.predicate, self.object)


@dataclass
class DomainNode:
    qid: str
    label: str = ""
    description: str = ""


@dataclass
class ExpansionResult:
    seeds: list[str]
    nodes: dict[str, DomainNode] = field(default_factory=dict)
    edges: list[DomainEdge] = field(default_factory=list)


def _values_clause(qids: Iterable[str]) -> str:
    inside = " ".join(f"wd:{q}" for q in qids)
    return f"VALUES ?subj {{ {inside} }}"


def _run_sparql(session_or_client, query: str) -> list[dict]:
    """
    Execute a SPARQL query.

    Accepts a SparqlSession (preferred — respects budget, cache, Retry-After)
    or an httpx.Client for legacy callers (creates an ephemeral one-shot
    session that honours the same rules).
    """
    if isinstance(session_or_client, SparqlSession):
        return session_or_client.run(query)
    # Legacy path: wrap the bare client in a single-use session.
    with SparqlSession(client=session_or_client) as session:
        # Mark client as not-owned so the legacy caller can keep using it.
        session._owns_client = False
        return session.run(query)


def _layer_query(seed_qids: list[str], properties: list[str], language: str = "en") -> str:
    """Batched query: for the given seeds, return all neighbours through given properties."""
    props = " ".join(f"wdt:{p}" for p in properties)
    return f"""
SELECT DISTINCT ?subj ?prop ?obj ?objLabel ?objDescription WHERE {{
  {_values_clause(seed_qids)}
  VALUES ?prop {{ {props} }}
  ?subj ?prop ?obj .
  FILTER(STRSTARTS(STR(?obj), "http://www.wikidata.org/entity/Q"))
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{language}". }}
}}
LIMIT 400
"""


def _qid_from_uri(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _pid_from_uri(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def expand(
    seeds: list[str],
    depth: int = 2,
    node_budget: int = 150,
    language: str = "en",
    properties: list[str] | None = None,
    session: SparqlSession | None = None,
    client: httpx.Client | None = None,
) -> ExpansionResult:
    """BFS expand `seeds` over `properties` up to `depth`, capped at `node_budget` total nodes.

    Prefer passing a SparqlSession so cache + budget are shared across the
    whole turn. The legacy `client=` kwarg is kept for back-compat.
    """
    if not seeds:
        return ExpansionResult(seeds=[])

    props = properties or list(DOMAIN_PROPERTIES.keys())

    owned_session = session is None
    if owned_session:
        session = SparqlSession(client=client)

    result = ExpansionResult(seeds=list(seeds))
    for q in seeds:
        result.nodes.setdefault(q, DomainNode(qid=q))

    frontier = list(seeds)
    visited: set[str] = set(seeds)

    try:
        for _ in range(max(1, depth)):
            if not frontier or len(result.nodes) >= node_budget or session.exhausted:
                break
            query = _layer_query(frontier, props, language=language)
            bindings = session.run(query)

            next_frontier: list[str] = []
            for b in bindings:
                if len(result.nodes) >= node_budget:
                    break
                try:
                    subj = _qid_from_uri(b["subj"]["value"])
                    prop = _pid_from_uri(b["prop"]["value"])
                    obj = _qid_from_uri(b["obj"]["value"])
                except KeyError:
                    continue
                if not obj.startswith("Q"):
                    continue
                label = b.get("objLabel", {}).get("value", "")
                desc = b.get("objDescription", {}).get("value", "")
                if obj not in result.nodes:
                    result.nodes[obj] = DomainNode(qid=obj, label=label, description=desc)
                else:
                    if not result.nodes[obj].label and label:
                        result.nodes[obj].label = label
                    if not result.nodes[obj].description and desc:
                        result.nodes[obj].description = desc
                result.edges.append(DomainEdge(subject=subj, predicate=prop, object=obj))
                if obj not in visited:
                    visited.add(obj)
                    next_frontier.append(obj)

            frontier = next_frontier[: max(0, node_budget - len(result.nodes))]

        if not session.exhausted:
            _fetch_seed_labels(session, list(result.nodes.values()), language)
    finally:
        if owned_session:
            session.close()

    return result


def _fetch_seed_labels(session: SparqlSession, nodes: list[DomainNode], language: str) -> None:
    """Backfill labels for nodes that came in unlabeled (typically the seeds)."""
    missing = [n.qid for n in nodes if not n.label]
    if not missing:
        return
    # batch-fetch labels in chunks of 50
    for i in range(0, len(missing), 50):
        if session.exhausted:
            break
        chunk = missing[i : i + 50]
        query = f"""
SELECT ?item ?itemLabel ?itemDescription WHERE {{
  VALUES ?item {{ {' '.join(f'wd:{q}' for q in chunk)} }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{language}". }}
}}
"""
        for b in session.run(query):
            try:
                qid = _qid_from_uri(b["item"]["value"])
            except KeyError:
                continue
            label = b.get("itemLabel", {}).get("value", "")
            desc = b.get("itemDescription", {}).get("value", "")
            for n in nodes:
                if n.qid == qid:
                    if label:
                        n.label = label
                    if desc:
                        n.description = desc
                    break


def edge_exists(
    subject_qid: str,
    object_qid: str,
    properties: list[str] | None = None,
    session: SparqlSession | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """Return the property linking subject→object on Wikidata, or None if no edge."""
    props = properties or list(DOMAIN_PROPERTIES.keys())
    owned_session = session is None
    if owned_session:
        session = SparqlSession(client=client)
    try:
        props_clause = " ".join(f"wdt:{p}" for p in props)
        query = f"""
SELECT ?prop WHERE {{
  VALUES ?prop {{ {props_clause} }}
  wd:{subject_qid} ?prop wd:{object_qid} .
}} LIMIT 1
"""
        bindings = session.run(query)
        if not bindings:
            return None
        return _pid_from_uri(bindings[0]["prop"]["value"])
    finally:
        if owned_session:
            session.close()


def class_cone_path(
    subject_qid: str,
    object_qid: str,
    properties: list[str] | None = None,
    max_up_hops: int = 3,
    session: SparqlSession | None = None,
    client: httpx.Client | None = None,
) -> tuple[str, str, str] | None:
    """
    Walk UP the P31/P279 class hierarchy from both subject and object,
    and check whether any pair of ancestors (in either direction) is
    connected by a domain-defining property.

    Returns the first such (s_ancestor_qid, property_pid, o_ancestor_qid)
    tuple found, or None if no class-level path exists in `max_up_hops` hops.

    Cone shape: the cone for X is {X} ∪ {ancestors reachable via
    P31|P279 followed by up to max_up_hops-1 P279 hops}. Depth-bounded
    on purpose — unbounded P279* quickly drags in Q35120 "entity" which
    is reachable from nearly everything and ruins the reachability signal.

    One SPARQL query per pair (same cost as edge_exists). Most useful as
    the "is this really a gap?" gate inside gap_detector.
    """
    # Default properties: everything EXCEPT the hierarchy edges (P31, P279),
    # because those are already used to build the cones themselves — matching
    # on them would trivially say "they share an ancestor" (all things do).
    if properties is None:
        properties = [p for p in DOMAIN_PROPERTIES.keys() if p not in ("P31", "P279")]
    props = properties
    owned_session = session is None
    if owned_session:
        session = SparqlSession(client=client)
    try:
        props_clause = " ".join(f"wdt:{p}" for p in props)

        # Build cone clauses: hop 0 (entity itself), hop 1 (P31|P279), then
        # 1..(max_up_hops-1) more P279 steps. Explicit UNION of fixed depths
        # is faster and more predictable than unbounded property paths.
        def cone_clause(var: str, qid: str) -> str:
            alts: list[str] = [f"BIND(wd:{qid} AS ?{var})"]
            # hop 1: P31 or P279
            alts.append(f"wd:{qid} wdt:P31|wdt:P279 ?{var}")
            # hops 2..max_up_hops: chain P279
            for d in range(2, max_up_hops + 1):
                mids = " . ".join(
                    f"?{var}_m{i} wdt:P279 ?{'%s_m%d' % (var, i+1) if i+1 < d else var}"
                    for i in range(1, d)
                )
                alts.append(
                    f"wd:{qid} wdt:P31|wdt:P279 ?{var}_m1 . {mids}"
                )
            return "{ " + " } UNION { ".join(alts) + " }"

        query = f"""
SELECT ?s_anc ?prop ?o_anc WHERE {{
  VALUES ?prop {{ {props_clause} }}
  {cone_clause("s_anc", subject_qid)}
  {cone_clause("o_anc", object_qid)}
  {{ ?s_anc ?prop ?o_anc }} UNION {{ ?o_anc ?prop ?s_anc }}
}} LIMIT 1
"""
        bindings = session.run(query)
        if not bindings:
            return None
        b = bindings[0]
        s_anc = b["s_anc"]["value"].rsplit("/", 1)[-1]
        prop  = _pid_from_uri(b["prop"]["value"])
        o_anc = b["o_anc"]["value"].rsplit("/", 1)[-1]
        return (s_anc, prop, o_anc)
    finally:
        if owned_session:
            session.close()
