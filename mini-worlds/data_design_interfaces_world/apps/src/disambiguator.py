"""
disambiguator.py
----------------
Mutual-context entity disambiguation.

Context-free disambiguation (one-best per surface form) breaks on prompts
like:

    "Should I drive or walk to the car wash?"

where wbsearchentities returns the most "famous" Q-ID for each token:

    drive  → Q644302  motivation
    walk   → Q363308  Walker Evans
    car    → Q1420    motor car
    car wash → Q1139861

Insight: the user's phrasing implicitly poses an *optimisation problem*
(a structured this-or-that choice). The right resolution of "drive" and
"walk" is the assignment that maximises **mutual semantic coherence**
with the rest of the seeds.

We implement that as exhaustive search over the small Cartesian product
of top-K candidates per surface, scored by pairwise **shared-ancestor
overlap** under (P31|P279)/P279*. A single batched SPARQL fetches all
ancestor sets in one round-trip.

Complexity: K^N evaluations (e.g. 5⁴ = 625) — trivial.
Rate-limit cost: +1 SPARQL query per prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from itertools import product
from typing import Iterable

import httpx

from .entity_extractor import EntityMention, _wbsearch_topk
from .sparql_session import SparqlSession


# Cap K to keep the assignment search small. With N up to ~6 seeds this is
# 8^6 = 262 144 — still in-memory tractable. Larger K is needed because
# wbsearchentities relevance is heavily prefix-biased: e.g. the literal
# entity "car" (Q1420) is rank 4 behind "Carina"/"CAR"/"Cardiff"/"Linnaeus".
DEFAULT_TOP_K = 7  # 7^6 ≈ 117K assignments — fast (<0.5 s) at N=6 surfaces


@dataclass
class Candidate:
    surface: str
    qid: str
    label: str
    description: str
    rank: int  # 0-indexed position in wbsearch results (smaller = more popular)

    def to_mention(self, confidence: float) -> EntityMention:
        return EntityMention(
            surface=self.surface,
            qid=self.qid,
            label=self.label,
            description=self.description,
            confidence=confidence,
        )


def _ancestors_query(qids: Iterable[str]) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    # P31|P279 then up to two P279 hops — captures enough class structure
    # to score overlap without unbounded recursion.
    return f"""
SELECT ?item ?anc WHERE {{
  VALUES ?item {{ {values} }}
  {{
    ?item wdt:P31|wdt:P279 ?anc .
  }} UNION {{
    ?item wdt:P31|wdt:P279 ?mid .
    ?mid wdt:P279 ?anc .
  }} UNION {{
    ?item wdt:P31|wdt:P279 ?mid1 .
    ?mid1 wdt:P279 ?mid2 .
    ?mid2 wdt:P279 ?anc .
  }}
}}
"""


def _fetch_ancestors(
    session: SparqlSession,
    qids: list[str],
) -> dict[str, set[str]]:
    """Return {qid: set(ancestor_qids)} for the given Q-IDs in one query."""
    if not qids:
        return {}
    bindings = session.run(_ancestors_query(qids))
    out: dict[str, set[str]] = {q: set() for q in qids}
    for b in bindings:
        try:
            item_uri = b["item"]["value"]
            anc_uri = b["anc"]["value"]
        except KeyError:
            continue
        item_q = item_uri.rsplit("/", 1)[-1]
        anc_q = anc_uri.rsplit("/", 1)[-1]
        if not item_q.startswith("Q") or not anc_q.startswith("Q"):
            continue
        if item_q in out:
            out[item_q].add(anc_q)
    return out


def _label_exact_match(c: Candidate) -> bool:
    """True if the candidate's label matches the surface form or its
    English gerund (case-insensitive).

    Accepting the gerund lets the activity sense (label "driving",
    "walking") score equally with the bare-verb surface ("drive",
    "walk") — without this, only the noun/film senses match exactly.
    """
    surface = c.surface.strip().lower()
    label = c.label.strip().lower()
    if label == surface:
        return True
    # Cheap gerund check (mirrors _gerund_variant in entity_extractor.py)
    if " " not in surface and len(surface) >= 3 and not surface.endswith("ing"):
        gerund = surface[:-1] + "ing" if surface.endswith("e") else surface + "ing"
        if label == gerund:
            return True
    return False


def _score_assignment(
    assignment: tuple[Candidate, ...],
    ancestors: dict[str, set[str]],
) -> tuple[int, float, int]:
    """
    Return a sort key: (label_exact_matches, mutual_overlap, -total_rank).

    Lexicographic ordering:
      1. PRIMARY — count of candidates whose label *exactly* matches the
         surface form. wbsearch relevance is prefix-biased, so the literal
         sense (e.g. "car" → Q1420 "car") often ranks below noisy prefix
         matches ("Carina", "Cardiff"). Exact-label-match is a strong
         "this is actually about this concept" signal that we promote
         above semantic-overlap.
      2. SECONDARY — pairwise shared-ancestor overlap. Within the set of
         max-label-match assignments, this picks the most mutually
         coherent reading.
      3. TERTIARY — wbsearch popularity (smaller total rank = more famous).

    Mutual overlap: Σ_{i<j} |ancestors(qid_i) ∩ ancestors(qid_j)|, with
    duplicate-Q-ID pairs excluded (they would trivially overlap by 100%).
    """
    qids = [c.qid for c in assignment]
    n = len(qids)
    overlap = 0
    for i in range(n):
        for j in range(i + 1, n):
            if qids[i] == qids[j]:
                continue
            overlap += len(ancestors.get(qids[i], set()) & ancestors.get(qids[j], set()))
    label_matches = sum(1 for c in assignment if _label_exact_match(c))
    total_rank = sum(c.rank for c in assignment)
    return (label_matches, float(overlap), -total_rank)


def mutual_context_resolve(
    surfaces: list[str],
    session: SparqlSession,
    language: str = "en",
    top_k: int = DEFAULT_TOP_K,
    max_surfaces: int = 8,
) -> list[EntityMention]:
    """
    Joint disambiguation across all surfaces.

    Pipeline:
      1. wbsearch top-K candidates per surface (trivial-description hits
         already filtered by _wbsearch_topk).
      2. One batched SPARQL fetches the ancestor set of every candidate.
      3. Exhaustive search across the Cartesian product picks the
         assignment maximising pairwise shared-ancestor overlap.
      4. Returns EntityMention list (one per surface, in input order).

    Falls back to a context-free per-surface best if SPARQL fails or the
    candidate pool is too small to be ambiguous.
    """
    if not surfaces:
        return []

    surfaces = surfaces[:max_surfaces]
    http_client: httpx.Client = session.client  # reuse session's UA-policy client

    # 1. Top-K candidates per surface
    per_surface: list[list[Candidate]] = []
    for surface in surfaces:
        hits = _wbsearch_topk(http_client, surface, language=language, limit=top_k, session=session)
        cands: list[Candidate] = []
        for rank, h in enumerate(hits[:top_k]):
            qid = h.get("id", "")
            if not qid.startswith("Q"):
                continue
            cands.append(
                Candidate(
                    surface=surface,
                    qid=qid,
                    label=h.get("label", surface),
                    description=h.get("description", ""),
                    rank=rank,
                )
            )
        if cands:
            per_surface.append(cands)

    if not per_surface:
        return []
    if len(per_surface) == 1:
        # Nothing to disambiguate against — use the top candidate.
        top = per_surface[0][0]
        return [top.to_mention(confidence=0.7)]

    # 2. Batched ancestor fetch
    all_qids = list({c.qid for cands in per_surface for c in cands})
    ancestors = _fetch_ancestors(session, all_qids)

    # If SPARQL failed/empty, fall back to context-free (top-1 per surface).
    if not any(ancestors.values()):
        return [cands[0].to_mention(confidence=0.6) for cands in per_surface]

    # 3. Exhaustive joint optimisation
    best_assignment: tuple[Candidate, ...] | None = None
    best_score: tuple[float, int, int] | None = None
    for assignment in product(*per_surface):
        score = _score_assignment(assignment, ancestors)
        if best_score is None or score > best_score:
            best_score = score
            best_assignment = assignment

    assert best_assignment is not None
    assert best_score is not None

    label_matches, overlap, _ = best_score
    n = len(best_assignment)
    # Confidence blends label-exact-match fraction and overlap density.
    base = 0.4 + 0.3 * (label_matches / max(1, n)) + min(0.3, overlap / 30.0)
    return [c.to_mention(confidence=round(base, 2)) for c in best_assignment]


def explain_resolution(
    surfaces: list[str],
    session: SparqlSession,
    language: str = "en",
    top_k: int = DEFAULT_TOP_K,
) -> dict:
    """
    Debug helper: returns the full per-surface candidate list, the chosen
    assignment, and per-pair overlap matrix. Used by the trace script.
    """
    http_client = session.client
    per_surface: list[list[Candidate]] = []
    for surface in surfaces:
        hits = _wbsearch_topk(http_client, surface, language=language, limit=top_k, session=session)
        cands: list[Candidate] = []
        for rank, h in enumerate(hits[:top_k]):
            qid = h.get("id", "")
            if not qid.startswith("Q"):
                continue
            cands.append(Candidate(
                surface=surface, qid=qid,
                label=h.get("label", surface),
                description=h.get("description", ""),
                rank=rank,
            ))
        if cands:
            per_surface.append(cands)

    all_qids = list({c.qid for cands in per_surface for c in cands})
    ancestors = _fetch_ancestors(session, all_qids)

    # Find best
    best: tuple[Candidate, ...] | None = None
    best_score = None
    for assignment in product(*per_surface):
        score = _score_assignment(assignment, ancestors)
        if best_score is None or score > best_score:
            best_score = score
            best = assignment

    # Per-pair overlap for chosen
    pair_overlaps: list[tuple[str, str, int]] = []
    if best is not None:
        for i in range(len(best)):
            for j in range(i + 1, len(best)):
                a, b = best[i].qid, best[j].qid
                if a == b:
                    continue
                pair_overlaps.append(
                    (f"{best[i].label} ({a})", f"{best[j].label} ({b})",
                     len(ancestors.get(a, set()) & ancestors.get(b, set())))
                )

    return {
        "candidates": {
            cands[0].surface: [asdict(c) for c in cands]
            for cands in per_surface
        },
        "chosen": [asdict(c) for c in best] if best else [],
        "chosen_score": best_score,
        "pair_overlaps": pair_overlaps,
        "ancestor_counts": {q: len(a) for q, a in ancestors.items()},
    }
