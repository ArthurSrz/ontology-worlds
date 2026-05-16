"""
domain_builder.py
-----------------
Orchestrates entity extraction + SPARQL expansion into a single ephemeral
JIT domain object, then exposes a compact summary suitable for injection
into a Claude prompt via UserPromptSubmit hook `additionalContext`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from .entity_extractor import EntityMention, deduplicate_by_qid, extract_entities
from .sparql_expander import (
    DOMAIN_PROPERTIES,
    DomainEdge,
    DomainNode,
    ExpansionResult,
    expand,
)


@dataclass
class JITDomain:
    """Ephemeral, per-prompt domain graph."""

    prompt: str
    seeds: list[EntityMention]
    expansion: ExpansionResult
    language: str = "en"

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def seed_qids(self) -> list[str]:
        return [s.qid for s in self.seeds]

    def in_domain(self, qid: str) -> bool:
        return qid in self.expansion.nodes

    def label(self, qid: str) -> str:
        node = self.expansion.nodes.get(qid)
        return node.label if node and node.label else qid

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "language": self.language,
            "seeds": [s.to_dict() for s in self.seeds],
            "nodes": {q: {"qid": n.qid, "label": n.label, "description": n.description}
                      for q, n in self.expansion.nodes.items()},
            "edges": [e.as_tuple() for e in self.expansion.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JITDomain":
        seeds = [EntityMention(**s) for s in data.get("seeds", [])]
        exp = ExpansionResult(seeds=[s.qid for s in seeds])
        for q, n in data.get("nodes", {}).items():
            exp.nodes[q] = DomainNode(qid=n["qid"], label=n.get("label", ""),
                                       description=n.get("description", ""))
        for (s, p, o) in data.get("edges", []):
            exp.edges.append(DomainEdge(subject=s, predicate=p, object=o))
        return cls(
            prompt=data.get("prompt", ""),
            language=data.get("language", "en"),
            seeds=seeds,
            expansion=exp,
        )

    # ------------------------------------------------------------------
    # Human-readable context for Claude
    # ------------------------------------------------------------------

    def context_summary(self, max_nodes: int = 60, max_edges: int = 60) -> str:
        """Compact Markdown summary injected into Claude via additionalContext."""
        lines: list[str] = []
        lines.append("## JIT Wikidata domain (built for this prompt)")
        lines.append("")
        if self.seeds:
            lines.append("**Seed entities (from your prompt):**")
            for s in self.seeds:
                desc = f" — {s.description}" if s.description else ""
                lines.append(f"- `{s.qid}` **{s.label}** (\"{s.surface}\"){desc}")
            lines.append("")

        nodes = list(self.expansion.nodes.values())[:max_nodes]
        if nodes:
            lines.append(f"**In-domain entities ({len(self.expansion.nodes)} total, showing {len(nodes)}):**")
            for n in nodes:
                label = n.label or n.qid
                lines.append(f"- `{n.qid}` {label}")
            lines.append("")

        edges = self.expansion.edges[:max_edges]
        if edges:
            lines.append(f"**Domain edges (Wikidata; {len(self.expansion.edges)} total, showing {len(edges)}):**")
            for e in edges:
                prop_label = DOMAIN_PROPERTIES.get(e.predicate, e.predicate)
                lines.append(f"- {self.label(e.subject)} — *{prop_label}* ({e.predicate}) → {self.label(e.object)}")
            lines.append("")

        lines.append(
            "**Constraint.** Stay within in-domain entities when answering. "
            "If the natural answer requires an out-of-domain concept, name it explicitly "
            "and explain why it falls outside the domain cone."
        )
        return "\n".join(lines)


def build_domain(
    prompt: str,
    language: str = "en",
    depth: int = 2,
    node_budget: int = 150,
    max_seeds: int = 6,
    session: "SparqlSession | None" = None,
    client: httpx.Client | None = None,
) -> JITDomain:
    """Top-level entrypoint: prompt → JITDomain.

    Prefer passing a SparqlSession so its budget + cache are shared with
    downstream gap detection in the same hook turn.
    """
    from .sparql_session import SparqlSession  # local import; avoid cycle

    owned_session = session is None
    if owned_session:
        session = SparqlSession(client=client)
    # entity_extractor still uses the Action API (different host), so it gets
    # the raw httpx.Client; we share it through the session.
    http_client = session.client
    try:
        mentions = extract_entities(
            prompt,
            language=language,
            max_entities=max_seeds,
            client=http_client,
            session=session,  # enables mutual-context disambiguation
        )
        mentions = deduplicate_by_qid(mentions)
        expansion = expand(
            seeds=[m.qid for m in mentions],
            depth=depth,
            node_budget=node_budget,
            language=language,
            session=session,
        )
        return JITDomain(prompt=prompt, seeds=mentions, expansion=expansion, language=language)
    finally:
        if owned_session:
            session.close()
