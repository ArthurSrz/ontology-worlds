"""
gap_detector.py
---------------
Detect missing Wikidata edges between co-mentioned seed entities, with
neighborhood-majority evidence.

This is the engine behind the "Why isn't `car` an object of co-occurrence of
`drive`?" debate prompts. Each Gap is a candidate Wikidata contribution.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from itertools import combinations

import httpx

from .domain_builder import JITDomain
from .sparql_expander import DOMAIN_PROPERTIES, class_cone_path, edge_exists
from .sparql_session import SparqlSession

# Property humans most naturally call "co-occurrence" / "uses" relations.
CO_OCCURRENCE_PROPERTIES = ["P2283", "P527", "P361", "P1535", "P366", "P1542"]


@dataclass
class Gap:
    seed_a_qid: str
    seed_a_label: str
    seed_b_qid: str
    seed_b_label: str
    suggested_property: str          # e.g. "P2283"
    suggested_property_label: str    # e.g. "uses"
    siblings_with_edge: int
    siblings_checked: int
    evidence_qids: list[str]
    question_text: str

    @property
    def confidence(self) -> float:
        if self.siblings_checked == 0:
            return 0.0
        return self.siblings_with_edge / self.siblings_checked

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confidence"] = self.confidence
        return d


def _frame_question(a_label: str, a_qid: str, b_label: str, b_qid: str,
                     prop: str, prop_label: str,
                     evidence: list[str], total: int) -> str:
    return (
        f"Wikidata gap: `{a_label}` ({a_qid}) has no `{prop}` ({prop_label}) edge to "
        f"`{b_label}` ({b_qid}), yet {len(evidence)}/{total} sibling concepts of "
        f"`{a_label}` do have this kind of edge to things of `{b_label}`'s class. "
        f"If this gap is load-bearing for the answer, surface it to the user and "
        f"invite their reasoning."
    )


def _pair_evidence_query(
    subj_qid: str,
    obj_qid: str,
    props: list[str],
    sibling_limit: int,
) -> str:
    """
    Single combined query that:
      - finds up to `sibling_limit` siblings of subj_qid (P31/P279 peers),
      - for each, returns the property (among `props`) by which they
        point to something in obj_qid's class.

    Yields (sib_qid, prop_pid) pairs. Empty result → no evidence / no gap.

    Replaces N+1 round-trips per directed pair with one.
    """
    props_clause = " ".join(f"wdt:{p}" for p in props)
    return f"""
SELECT DISTINCT ?sib ?prop WHERE {{
  {{
    SELECT ?sib WHERE {{
      wd:{subj_qid} wdt:P31|wdt:P279 ?cls .
      ?sib wdt:P31|wdt:P279 ?cls .
      FILTER(?sib != wd:{subj_qid})
    }} LIMIT {sibling_limit}
  }}
  VALUES ?prop {{ {props_clause} }}
  wd:{obj_qid} wdt:P31|wdt:P279 ?objCls .
  ?sib ?prop ?o .
  ?o wdt:P31|wdt:P279 ?objCls .
}}
"""


def detect_gaps(
    domain: JITDomain,
    co_occurrence_properties: list[str] | None = None,
    sibling_limit: int = 10,
    min_majority: float = 0.5,
    session: SparqlSession | None = None,
    client: httpx.Client | None = None,
    trace: list[dict] | None = None,
) -> list[Gap]:
    """For each pair of seed Q-IDs, look for missing co-occurrence edges.

    One combined SPARQL query per directed pair (sibling discovery + evidence
    in a single round-trip). Respects the SparqlSession budget — stops early
    if the session is exhausted.
    """
    seeds = domain.seeds
    if len(seeds) < 2:
        return []

    props = co_occurrence_properties or CO_OCCURRENCE_PROPERTIES

    owned_session = session is None
    if owned_session:
        session = SparqlSession(client=client)

    gaps: list[Gap] = []
    try:
        for a, b in combinations(seeds, 2):
            for subj, obj in ((a, b), (b, a)):
                if session.exhausted:
                    return gaps

                step: dict = {
                    "subj": f"{subj.label} ({subj.qid})",
                    "obj":  f"{obj.label} ({obj.qid})",
                }
                # Class-cone reachability: walk UP the P31/P279 hierarchy
                # from both subject and object (depth ≤ 3) and look for any
                # connecting property between any pair of cone members.
                # If reachable, this is NOT a Wikidata gap — the ontology
                # already models the relationship via class-level edges.
                path = class_cone_path(
                    subj.qid, obj.qid,
                    properties=props,
                    max_up_hops=3,
                    session=session,
                )
                if path is not None:
                    s_anc, prop, o_anc = path
                    step["status"] = (
                        f"reachable_via_classes "
                        f"({s_anc} --{prop}--> {o_anc})"
                    )
                    if trace is not None: trace.append(step)
                    continue  # not a gap

                bindings = session.run(
                    _pair_evidence_query(subj.qid, obj.qid, props, sibling_limit)
                )
                if not bindings:
                    step["status"] = "no_sibling_evidence"
                    if trace is not None: trace.append(step)
                    continue

                # Aggregate evidence by property
                per_prop: dict[str, set[str]] = {}
                for row in bindings:
                    try:
                        sib_qid = row["sib"]["value"].rsplit("/", 1)[-1]
                        prop_pid = row["prop"]["value"].rsplit("/", 1)[-1]
                    except KeyError:
                        continue
                    per_prop.setdefault(prop_pid, set()).add(sib_qid)

                if not per_prop:
                    step["status"] = "no_sibling_evidence"
                    if trace is not None: trace.append(step)
                    continue
                prop, evidence_set = max(per_prop.items(), key=lambda kv: len(kv[1]))
                evidence = sorted(evidence_set)
                ratio = len(evidence) / sibling_limit
                step["best_property"] = prop
                step["evidence_count"] = len(evidence)
                step["sibling_limit"] = sibling_limit
                step["ratio"] = round(ratio, 2)

                if ratio < min_majority:
                    step["status"] = f"below_threshold ({ratio:.2f} < {min_majority})"
                    if trace is not None: trace.append(step)
                    continue

                step["status"] = "GAP"
                if trace is not None: trace.append(step)

                gaps.append(
                    Gap(
                        seed_a_qid=subj.qid,
                        seed_a_label=subj.label,
                        seed_b_qid=obj.qid,
                        seed_b_label=obj.label,
                        suggested_property=prop,
                        suggested_property_label=DOMAIN_PROPERTIES.get(prop, prop),
                        siblings_with_edge=len(evidence),
                        siblings_checked=sibling_limit,
                        evidence_qids=evidence,
                        question_text=_frame_question(
                            subj.label, subj.qid, obj.label, obj.qid,
                            prop, DOMAIN_PROPERTIES.get(prop, prop),
                            evidence, sibling_limit,
                        ),
                    )
                )
    finally:
        if owned_session:
            session.close()

    return gaps


def format_gaps_for_context(gaps: list[Gap]) -> str:
    if not gaps:
        return ""
    lines = ["## Detected Wikidata gaps", ""]
    for g in gaps:
        lines.append(f"- **{g.seed_a_label} → ?{g.suggested_property_label}? → {g.seed_b_label}**")
        lines.append(f"  - {g.question_text}")
        lines.append(f"  - Evidence siblings: {', '.join(g.evidence_qids[:5])}"
                     f"{' …' if len(g.evidence_qids) > 5 else ''}")
        lines.append(
            f"  - If the user agrees this edge is real, emit "
            f"`[PROPOSE {g.seed_a_qid} {g.suggested_property} {g.seed_b_qid}: \"<reasoning>\"]` "
            f"in your response."
        )
    return "\n".join(lines)
