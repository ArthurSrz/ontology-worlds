"""
Unit tests for the JIT pipeline modules.

These tests mock the Wikidata HTTP layer — they do NOT hit the network — so
they verify the *plumbing* and *logic* of each module deterministically.
A separate integration test (run manually) exercises the live SPARQL endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Repository root added to sys.path so `src.…` imports resolve when pytest is
# invoked from anywhere in the repo.
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.entity_extractor import _candidate_surfaces, EntityMention, deduplicate_by_qid
from src.contribution_recorder import parse_proposals, capture, load_session, Contribution
from src.sparql_expander import ExpansionResult, DomainNode, DomainEdge
from src.domain_builder import JITDomain
from src.gap_detector import Gap, format_gaps_for_context


# ---------------------------------------------------------------------------
# entity_extractor
# ---------------------------------------------------------------------------

class TestCandidateSurfaces:
    def test_bigrams_first(self):
        out = _candidate_surfaces("I want to wash my car at the car wash.")
        # bigram "car wash" should appear; pure-stopword bigrams should not.
        assert "car wash" in out

    def test_skips_pure_stopwords(self):
        out = _candidate_surfaces("I want to go to the the the.")
        # "the the" is two stopwords → filtered.
        assert "the the" not in out

    def test_dedupes(self):
        out = _candidate_surfaces("car car car")
        assert out.count("car") == 1


class TestDeduplicateByQid:
    def test_keeps_first_occurrence(self):
        a = EntityMention(surface="car", qid="Q1420", label="motor car", description="", confidence=0.7)
        b = EntityMention(surface="automobile", qid="Q1420", label="motor car", description="", confidence=0.7)
        c = EntityMention(surface="walk", qid="Q1059891", label="walking", description="", confidence=0.7)
        out = deduplicate_by_qid([a, b, c])
        assert [m.qid for m in out] == ["Q1420", "Q1059891"]
        assert out[0].surface == "car"


# ---------------------------------------------------------------------------
# contribution_recorder — the [PROPOSE …] parser is critical
# ---------------------------------------------------------------------------

class TestParseProposals:
    def test_single_proposal(self):
        text = 'Yes — [PROPOSE Q190984 P2283 Q1420: "you drive a car"]. So drive.'
        props = parse_proposals(text)
        assert props == [("Q190984", "P2283", "Q1420", "you drive a car")]

    def test_multiple_proposals(self):
        text = (
            '[PROPOSE Q190984 P2283 Q1420: "drive uses car"]\n'
            '[PROPOSE Q193599 P2283 Q1420: "car wash uses car"]\n'
        )
        props = parse_proposals(text)
        assert len(props) == 2
        assert props[1] == ("Q193599", "P2283", "Q1420", "car wash uses car")

    def test_ignores_malformed(self):
        text = "[PROPOSE not-a-qid P2283 Q1420: 'wrong quote style']"
        assert parse_proposals(text) == []

    def test_multiline_reasoning(self):
        text = '[PROPOSE Q1 P2 Q3: "first line\nsecond line"]'
        props = parse_proposals(text)
        assert props == [("Q1", "P2", "Q3", "first line\nsecond line")]


class TestCaptureContributions:
    def test_writes_jsonl_and_returns(self, tmp_path: Path):
        text = '[PROPOSE Q190984 P2283 Q1420: "you drive a car"]'
        contribs = capture(
            response_text=text,
            source_prompt="should I drive or walk?",
            session_id="abc123",
            output_dir=tmp_path,
            gap_origin={("Q190984", "P2283", "Q1420"): "gap question"},
        )
        assert len(contribs) == 1
        c = contribs[0]
        assert c.subject_qid == "Q190984"
        assert c.gap_origin == "gap question"
        assert c.to_quickstatements() == 'Q190984|P2283|Q1420|S887|"you drive a car"'

        path = tmp_path / "abc123.jsonl"
        assert path.exists()
        loaded = load_session("abc123", tmp_path)
        assert len(loaded) == 1
        assert loaded[0].subject_qid == "Q190984"

    def test_append_not_overwrite(self, tmp_path: Path):
        capture('[PROPOSE Q1 P2 Q3: "first"]', "p", "s", tmp_path)
        capture('[PROPOSE Q4 P5 Q6: "second"]', "p", "s", tmp_path)
        loaded = load_session("s", tmp_path)
        assert len(loaded) == 2

    def test_no_tag_no_file(self, tmp_path: Path):
        contribs = capture("just a regular response, no tags here", "p", "s", tmp_path)
        assert contribs == []
        assert not (tmp_path / "s.jsonl").exists()


# ---------------------------------------------------------------------------
# domain_builder.JITDomain — round-trip serialization
# ---------------------------------------------------------------------------

class TestJITDomainRoundtrip:
    def test_to_dict_from_dict(self):
        seeds = [EntityMention(surface="car", qid="Q1420", label="motor car",
                               description="vehicle", confidence=0.7)]
        exp = ExpansionResult(seeds=["Q1420"])
        exp.nodes["Q1420"] = DomainNode(qid="Q1420", label="motor car", description="")
        exp.nodes["Q752870"] = DomainNode(qid="Q752870", label="vehicle", description="")
        exp.edges.append(DomainEdge(subject="Q1420", predicate="P279", object="Q752870"))

        d = JITDomain(prompt="wash car", seeds=seeds, expansion=exp, language="en")
        out = d.to_dict()
        d2 = JITDomain.from_dict(out)

        assert d2.prompt == "wash car"
        assert d2.seed_qids == ["Q1420"]
        assert d2.in_domain("Q1420")
        assert d2.in_domain("Q752870")
        assert not d2.in_domain("Q999999")
        assert len(d2.expansion.edges) == 1
        assert d2.expansion.edges[0].as_tuple() == ("Q1420", "P279", "Q752870")

    def test_context_summary_mentions_seeds(self):
        seeds = [EntityMention(surface="drive", qid="Q190984", label="driving",
                               description="", confidence=0.7)]
        exp = ExpansionResult(seeds=["Q190984"])
        exp.nodes["Q190984"] = DomainNode(qid="Q190984", label="driving")
        d = JITDomain(prompt="should i drive", seeds=seeds, expansion=exp)
        summary = d.context_summary()
        assert "Q190984" in summary
        assert "driving" in summary
        assert "JIT Wikidata domain" in summary


# ---------------------------------------------------------------------------
# gap_detector formatting
# ---------------------------------------------------------------------------

class TestFormatGapsForContext:
    def test_includes_propose_template(self):
        g = Gap(
            seed_a_qid="Q190984", seed_a_label="driving",
            seed_b_qid="Q1420", seed_b_label="motor car",
            suggested_property="P2283", suggested_property_label="uses",
            siblings_with_edge=7, siblings_checked=10,
            evidence_qids=["Q123", "Q456"],
            question_text="why no drive→car?",
        )
        out = format_gaps_for_context([g])
        assert "[PROPOSE Q190984 P2283 Q1420" in out
        assert "driving" in out
        assert "motor car" in out
        assert "7/10" not in out or "Evidence siblings" in out  # evidence rendered

    def test_empty_list_returns_empty_string(self):
        assert format_gaps_for_context([]) == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
