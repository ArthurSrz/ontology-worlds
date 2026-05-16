"""
contribution_recorder.py
------------------------
Parse `[PROPOSE <S> <P> <O>: "<reasoning>"]` tags out of Claude's response
and stage them as Wikidata contribution candidates.

Rendered as QuickStatements (https://quickstatements.toolforge.org/) for the
user to paste — direct `wbeditentity` POST is a follow-up that needs OAuth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# [PROPOSE Q190984 P2283 Q1420: "you drive a car"]
_PROPOSE_RE = re.compile(
    r"\[PROPOSE\s+(Q\d+)\s+(P\d+)\s+(Q\d+)\s*:\s*\"(.*?)\"\s*\]",
    re.DOTALL,
)


@dataclass
class Contribution:
    subject_qid: str
    property_pid: str
    object_qid: str
    reasoning: str
    source_prompt: str = ""
    gap_origin: str = ""
    session_id: str = ""
    status: str = "staged"
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_quickstatements(self) -> str:
        """Render as a single QuickStatements line (v1 syntax)."""
        # Reasoning becomes an S887 (based on heuristic) string qualifier.
        safe = self.reasoning.replace('"', "'")
        return f"{self.subject_qid}|{self.property_pid}|{self.object_qid}|S887|\"{safe}\""

    def to_dict(self) -> dict:
        return asdict(self)


def parse_proposals(response_text: str) -> list[tuple[str, str, str, str]]:
    """Return list of (subject_qid, property_pid, object_qid, reasoning)."""
    return [m.groups() for m in _PROPOSE_RE.finditer(response_text or "")]


def capture(
    response_text: str,
    source_prompt: str,
    session_id: str,
    output_dir: Path,
    gap_origin: dict[tuple[str, str, str], str] | None = None,
) -> list[Contribution]:
    """
    Parse [PROPOSE …] tags, build Contribution records, append to
    contributions/<session_id>.jsonl, and return them.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    contribs: list[Contribution] = []
    for subj, prop, obj, reasoning in parse_proposals(response_text):
        origin = ""
        if gap_origin is not None:
            origin = gap_origin.get((subj, prop, obj), "")
        c = Contribution(
            subject_qid=subj,
            property_pid=prop,
            object_qid=obj,
            reasoning=reasoning.strip(),
            source_prompt=source_prompt,
            gap_origin=origin,
            session_id=session_id,
        )
        contribs.append(c)

    if contribs:
        path = output_dir / f"{session_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for c in contribs:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    return contribs


def load_session(session_id: str, output_dir: Path) -> list[Contribution]:
    path = output_dir / f"{session_id}.jsonl"
    if not path.exists():
        return []
    out: list[Contribution] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(Contribution(**d))
    return out


def render_quickstatements(contribs: Iterable[Contribution]) -> str:
    return "\n".join(c.to_quickstatements() for c in contribs)
