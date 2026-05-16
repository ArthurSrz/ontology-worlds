"""
entity_extractor.py
-------------------
Extract entity mentions from a free-text user prompt and resolve them to
Wikidata Q-IDs.

No spaCy / no heavy NLP — cheap regex tokenisation + Wikidata
`wbsearchentities` API. Returns a list of EntityMention dicts that seed the
JIT domain graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Iterable

import httpx

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

_STOPWORDS = {
    "the", "a", "an", "i", "you", "we", "they", "he", "she", "it", "is", "am",
    "are", "was", "were", "be", "been", "being", "to", "of", "in", "on", "at",
    "by", "for", "with", "about", "as", "into", "from", "and", "or", "but",
    "if", "then", "than", "so", "that", "this", "these", "those", "should",
    "would", "could", "do", "does", "did", "have", "has", "had", "my", "your",
    "our", "their", "his", "her", "its", "me", "us", "them", "want", "wants",
    "need", "needs", "go", "going", "very", "only", "just", "also", "too",
    "what", "when", "where", "why", "how", "who", "which",
}


@dataclass
class EntityMention:
    surface: str
    qid: str
    label: str
    description: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


_WORD = re.compile(r"\b[a-zA-Z][a-zA-Z\-]+\b")


def _candidate_surfaces(prompt: str) -> list[str]:
    """Return ordered, deduped candidate surface forms — overlapping bigrams first, then unigrams."""
    words = [m.group(0).lower() for m in _WORD.finditer(prompt)]

    seen: set[str] = set()
    out: list[str] = []

    # Overlapping bigrams, in left-to-right order. Both tokens must be
    # content words — stopword bigrams produce noisy Wikidata hits
    # (song titles, papers, films).
    for i in range(len(words) - 1):
        a, b = words[i], words[i + 1]
        if a in _STOPWORDS or b in _STOPWORDS:
            continue
        if len(a) < 2 or len(b) < 2:
            continue
        bigram = f"{a} {b}"
        if bigram in seen:
            continue
        seen.add(bigram)
        out.append(bigram)

    # Unigrams (≥ 3 chars), skipping stopwords and already-seen forms.
    for w in words:
        if len(w) < 3 or w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)

    return out


_TRIVIAL_DESCRIPTION_MARKERS = (
    # Music / media titles
    "song by", "album by", "film by", "novel by", "video game",
    "studio recording", "vocal track", "studio album", "single by",
    "comic book", "tv series", "manga series", "anime", "music studio",
    # Episodes & specific releases (catches "episode of The Mr Men Show",
    # "2025 film", "film directed by", "Christmas carol", "webcomic" etc.)
    "episode of", "film directed", "film starring", "film featuring",
    " film", " movie", " song", " album", " novel", " carol", " webcomic",
    " strip", " manga", " series episode",
    # Generic creative-work fallback: a candidate whose ONLY defining
    # property is "creative work by …" is virtually always the wrong
    # sense for a common-noun prompt.
    "creative work by", "work by",
    # Names of people / professions (a person's name is rarely the
    # intended sense when a common-noun candidate also exists)
    "family name", "given name", "surname",
    "photographer", "photojournalist", "painter", "musician",
    "writer", "author", "actor", "actress", "athlete", "filmmaker",
    "director", "producer", "singer", "composer", "journalist",
    "politician", "scientist", "biographical", "drummer", "entomologist",
    "botanist", "zoologist",
    # Geographic-name noise: villages, parishes, towns named after common
    # English words ("Walkington", "Walkhampton", "Valka")
    " village", " parish", " hamlet",
    # Disambiguation / meta
    "disambiguation page", "wikimedia",
)


def _looks_trivial(desc: str) -> bool:
    if not desc:
        return False
    low = desc.lower()
    return any(m in low for m in _TRIVIAL_DESCRIPTION_MARKERS)


def _wbsearch_raw(
    client: httpx.Client,
    query: str,
    language: str,
    limit: int,
    *,
    session: "object | None" = None,
) -> list[dict]:
    """Call wbsearchentities. Caches by (query, language, limit) on the
    session if one is provided — same call within one turn never re-hits
    the Action API."""
    cache_key = (query, language, limit)
    if session is not None:
        cached = getattr(session, "wbsearch_cache", {}).get(cache_key)
        if cached is not None:
            return cached
    try:
        r = client.get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": language,
                "uselang": language,
                "type": "item",
                "limit": limit,
                "format": "json",
            },
            timeout=5.0,
        )
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    hits = r.json().get("search", [])
    if session is not None and hasattr(session, "wbsearch_cache"):
        session.wbsearch_cache[cache_key] = hits
    return hits


def _gerund_variant(surface: str) -> str | None:
    """Cheap English gerund augmentation for short verb-like single-word surfaces.

    "drive" → "driving", "walk" → "walking", "bake" → "baking".
    Returns None if the surface is unsuitable (multi-word, already ends in
    -ing, too short, etc.). False positives are OK — they just add a few
    candidates that won't score well.
    """
    if " " in surface or len(surface) < 3 or surface.endswith("ing"):
        return None
    if surface.endswith("e") and len(surface) >= 4:
        return surface[:-1] + "ing"   # drive → driving
    return surface + "ing"            # walk → walking


def _wbsearch_topk(
    client: httpx.Client,
    surface: str,
    language: str = "en",
    limit: int = 7,
    *,
    session: "object | None" = None,
) -> list[dict]:
    """Return top-K candidates for `surface`, with verb→gerund augmentation.

    For a short single-word surface that looks like a verb, also queries
    the gerund form (e.g. "drive" → "driving") and merges results. This
    is the cheapest way to surface the activity senses (Q190984 driving,
    Q149557 walking) that wbsearch never returns for the bare verb.

    Trivial-description hits (songs, films, names of people) are filtered
    out unless that leaves no candidates.
    """
    hits = _wbsearch_raw(client, surface, language, limit, session=session)
    gerund = _gerund_variant(surface)
    if gerund:
        extra = _wbsearch_raw(client, gerund, language, limit, session=session)
        seen = {h.get("id") for h in hits}
        for h in extra:
            qid = h.get("id")
            if qid and qid not in seen:
                hits.append(h)
                seen.add(qid)

    if not hits:
        return []
    filtered = [h for h in hits if not _looks_trivial(h.get("description", ""))]
    return filtered or hits


def _wbsearch(client: httpx.Client, surface: str, language: str = "en") -> dict | None:
    """Single best hit — used by the context-free fallback path."""
    hits = _wbsearch_topk(client, surface, language=language, limit=7)
    return hits[0] if hits else None


def extract_entities(
    prompt: str,
    language: str = "en",
    max_entities: int = 8,
    client: httpx.Client | None = None,
    session: "object | None" = None,  # SparqlSession; forward-declared to avoid cycle
) -> list[EntityMention]:
    """
    Extract entity mentions from a prompt.

    Returns at most `max_entities` resolved Wikidata items, in order of first
    appearance. Bigrams take precedence over their constituent unigrams.

    If a SparqlSession is passed, **mutual-context disambiguation** runs:
    candidates are scored jointly via shared-ancestor overlap so e.g.
    "drive" + "walk" resolve to the activity senses rather than to
    "motivation" / "Walker Evans".
    """
    surfaces = _candidate_surfaces(prompt)
    if not surfaces:
        return []

    owned_client = client is None
    if owned_client:
        client = httpx.Client(
            headers={
                "User-Agent": (
                    "ontology-worlds-bot/0.3 "
                    "(https://github.com/ArthurSrz/ontology-worlds; "
                    "arthur.sarazin@etu-iepg.fr) httpx/0.27"
                )
            }
        )

    # Keep both bigrams and their constituent unigrams during
    # disambiguation — the unigrams provide essential contextual anchors
    # for mutual-overlap scoring (e.g. "car" pulls "drive" toward the
    # vehicle-driving sense rather than horse-driving). Final EntityMentions
    # are deduplicated by Q-ID so two surfaces resolving to the same entity
    # produce only one seed.
    capped: list[str] = surfaces[:max_entities]

    try:
        # Mutual-context path: one combined SPARQL determines the joint
        # best assignment across all surfaces.
        if session is not None and len(capped) >= 2:
            from .disambiguator import mutual_context_resolve
            mentions = mutual_context_resolve(
                surfaces=capped,
                session=session,
                language=language,
            )
            if mentions:
                return mentions
            # Fall through to context-free on failure.

        # Context-free fallback.
        matched: list[EntityMention] = []
        for surface in capped:
            hit = _wbsearch(client, surface, language=language)
            if not hit:
                continue
            qid = hit.get("id", "")
            if not qid.startswith("Q"):
                continue
            toks = surface.split()
            matched.append(
                EntityMention(
                    surface=surface,
                    qid=qid,
                    label=hit.get("label", surface),
                    description=hit.get("description", ""),
                    confidence=1.0 if len(toks) >= 2 else 0.7,
                )
            )
        return matched
    finally:
        if owned_client:
            client.close()


def deduplicate_by_qid(mentions: Iterable[EntityMention]) -> list[EntityMention]:
    seen: set[str] = set()
    out: list[EntityMention] = []
    for m in mentions:
        if m.qid in seen:
            continue
        seen.add(m.qid)
        out.append(m)
    return out
