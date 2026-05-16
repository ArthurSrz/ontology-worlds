"""
domain_validator.py
-------------------
Validate Claude's response against the ephemeral JIT domain graph.

Unlike `src/validator.py` (which validates structured tool_use payloads
against a pre-built ontology), this validator works on free-text responses
and scores how much of the response's named entities fall inside the
just-built Wikidata subgraph.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .domain_builder import JITDomain
from .entity_extractor import extract_entities


@dataclass
class ResponseValidation:
    score: float
    in_domain: list[str]      # qids
    out_of_domain: list[str]  # qids
    out_of_domain_labels: list[str]

    @property
    def passes(self) -> bool:
        return self.score >= 0.5  # default threshold; configurable upstream


def validate_response(
    response_text: str,
    domain: JITDomain,
    threshold: float = 0.5,
    client: httpx.Client | None = None,
) -> ResponseValidation:
    """
    Re-extract entities from `response_text` and score the fraction that
    land inside the domain's expanded node set.
    """
    mentions = extract_entities(response_text, language=domain.language, max_entities=12, client=client)

    in_dom: list[str] = []
    ood: list[str] = []
    ood_labels: list[str] = []

    for m in mentions:
        if domain.in_domain(m.qid):
            in_dom.append(m.qid)
        else:
            ood.append(m.qid)
            ood_labels.append(m.label or m.surface)

    total = len(in_dom) + len(ood)
    score = (len(in_dom) / total) if total else 1.0  # no entities → vacuously passing

    rv = ResponseValidation(
        score=score,
        in_domain=in_dom,
        out_of_domain=ood,
        out_of_domain_labels=ood_labels,
    )
    # threshold is held by the caller, but expose via passes too:
    rv.passes  # noqa: B018  — keeps property warm; trivial.
    return rv
