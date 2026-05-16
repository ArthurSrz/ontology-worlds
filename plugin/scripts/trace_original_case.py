"""
Trace the JIT pipeline against the user's motivating prompt.

Shows every intermediate step:
  1) candidate surface forms
  2) resolved seed entities (Wikidata Q-IDs)
  3) SPARQL expansion (nodes + edges)
  4) detected gaps
  5) final additionalContext string injected into Claude
  6) session status (queries used, time, cooled?)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.entity_extractor import _candidate_surfaces, extract_entities, deduplicate_by_qid
from src.domain_builder import build_domain
from src.gap_detector import detect_gaps, format_gaps_for_context
from src.sparql_session import SparqlSession

PROMPT = "I want to wash my car. The car wash is 100m away. Should I drive or walk?"

H = "=" * 78


def hr(title: str) -> None:
    print(f"\n{H}\n  {title}\n{H}")


def main() -> int:
    hr(f"PROMPT")
    print(f"  {PROMPT}")

    # 1. Candidate surfaces (before any HTTP)
    hr("1. Candidate surface forms (regex tokeniser)")
    surfaces = _candidate_surfaces(PROMPT)
    for s in surfaces:
        print(f"  • {s}")

    with SparqlSession() as session:
        # Same capping that extract_entities applies — pass ALL surfaces,
        # including unigrams shadowed by bigrams; final mentions are
        # deduplicated by Q-ID downstream.
        capped: list[str] = surfaces[:6]

        # 2a. Run explain (caches wbsearch + ancestor SPARQL on the session)
        hr("2a. Candidate matrix (top-K wbsearch per surface)")
        from src.disambiguator import explain_resolution
        from src.disambiguator import DEFAULT_TOP_K
        explanation = explain_resolution(capped, session=session, top_k=DEFAULT_TOP_K)
        chosen_qids = {ch["qid"] for ch in explanation["chosen"]}
        for surface, cands in explanation["candidates"].items():
            print(f"\n  surface = {surface!r}")
            for c in cands:
                qid = c["qid"]
                anc = explanation["ancestor_counts"].get(qid, 0)
                marker = "  ←CHOSEN" if qid in chosen_qids else ""
                print(f"    rank={c['rank']}  {qid:<10} {c['label']!r:<32} "
                      f"anc={anc:<3} desc={c['description']!r:.55}{marker}")

        hr("2b. Pairwise shared-ancestor overlap (for chosen assignment)")
        for a, b, n in explanation["pair_overlaps"]:
            print(f"  |{a}  ∩  {b}|  =  {n}")
        lm, ov, neg_rank = explanation["chosen_score"]
        print(f"\n  score = (label_exact_matches={lm}, overlap={ov:.0f}, "
              f"-rank_sum={neg_rank})")

        # 2c. Resolved seeds — wbsearch + ancestor queries hit the cache
        hr("2c. Resolved seeds (deterministic via session cache)")
        mentions = extract_entities(PROMPT, max_entities=6,
                                    client=session.client, session=session)
        mentions = deduplicate_by_qid(mentions)
        for m in mentions:
            print(f"  {m.surface!r:18} → {m.qid:<10} {m.label!r:<28} "
                  f"conf={m.confidence:.2f}  desc={m.description!r}")

        # 3. Domain expansion (uses the same session → shared budget + cache)
        hr("3. SPARQL domain expansion (P31/P279/P361/P527/P2283/P1535/P366/P1542)")
        # Re-run build_domain reusing the same session; but we already extracted,
        # so call expand directly.
        from src.sparql_expander import expand
        expansion = expand(
            seeds=[m.qid for m in mentions],
            depth=2,
            node_budget=80,
            session=session,
        )
        print(f"  nodes = {len(expansion.nodes)}    edges = {len(expansion.edges)}")
        print(f"  session after expand: {session.status_line()}")
        print()
        print("  --- in-domain entities (first 20) ---")
        for q, n in list(expansion.nodes.items())[:20]:
            print(f"    {q:<12} {n.label!r:<40} {n.description!r:.60}")
        print()
        print("  --- domain edges (first 20) ---")
        for e in expansion.edges[:20]:
            obj_label = expansion.nodes[e.object].label if e.object in expansion.nodes else ''
            print(f"    {e.subject:<10} --{e.predicate:<6}--> {e.object:<10} {obj_label!r}")

        from src.domain_builder import JITDomain
        domain = JITDomain(prompt=PROMPT, seeds=mentions, expansion=expansion)

        # 4. Gap detection (shares session)
        hr("4. Gap detection (neighbourhood-majority over seed pairs)")
        trace_steps: list[dict] = []
        gaps = detect_gaps(domain, min_majority=0.3, sibling_limit=8,
                           session=session, trace=trace_steps)
        print(f"  detected {len(gaps)} gap(s)")
        print(f"  session after gaps: {session.status_line()}")
        print(f"\n  --- per-pair trace ({len(trace_steps)} pairs checked) ---")
        for s in trace_steps:
            extra = ""
            if "ratio" in s:
                extra = f"  ratio={s['ratio']}  best_prop={s.get('best_property','-')}  evidence={s.get('evidence_count','-')}/{s.get('sibling_limit','-')}"
            print(f"    {s['subj']:<35} → {s['obj']:<35} [{s['status']}]{extra}")
        for g in gaps:
            print()
            print(f"  ► {g.seed_a_label} ({g.seed_a_qid}) — ?{g.suggested_property_label}? "
                  f"({g.suggested_property}) → {g.seed_b_label} ({g.seed_b_qid})")
            print(f"    confidence = {g.confidence:.2f}  "
                  f"({g.siblings_with_edge}/{g.siblings_checked} siblings)")
            print(f"    evidence Q-IDs: {', '.join(g.evidence_qids[:5])}"
                  f"{' …' if len(g.evidence_qids) > 5 else ''}")
            print(f"    question: {g.question_text}")

        # 5. Final additionalContext
        hr("5. additionalContext (what would be injected into Claude)")
        parts = [domain.context_summary()]
        if gaps:
            parts.append("")
            parts.append(format_gaps_for_context(gaps))
        parts.append("")
        parts.append(
            "## Contribution protocol\n"
            "When you and the user agree that a missing Wikidata edge is real, "
            "emit a tag of the form `[PROPOSE <subject_qid> <property_pid> <object_qid>: \"<reasoning>\"]` "
            "inline in your answer."
        )
        print("\n".join(parts))

        # 6. Final session status
        hr("6. Session final state")
        print(f"  {session.status_line()}")
        print(f"  cache entries: {len(session.cache)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
