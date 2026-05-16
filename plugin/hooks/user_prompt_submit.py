#!/usr/bin/env python3
"""
hooks/user_prompt_submit.py
---------------------------
Claude Code UserPromptSubmit hook.

Pipeline:
  prompt → extract entities → SPARQL-expand domain → detect gaps
        → inject `additionalContext` so Claude reasons in-domain
          and surfaces Wikidata gaps as user-facing debates.

Cache the built JIT domain to /tmp/ontology-worlds/<session_id>.json so the
Stop hook can score the response against the same graph.

Hook protocol:
  stdin  : JSON with {session_id, prompt, hook_event_name, …}
  stdout : JSON {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                         "additionalContext": "..."}}
  exit 0 : allow, additionalContext fed to model
  exit 2 : block (we never block here — degrade gracefully instead)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

CACHE_DIR = Path(os.environ.get("ONTOLOGY_WORLDS_CACHE", Path(tempfile.gettempdir()) / "ontology-worlds"))


def log(msg: str) -> None:
    print(f"[ontology-worlds:UserPromptSubmit] {msg}", file=sys.stderr)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        log(f"bad stdin: {e}")
        return 0

    prompt = (data.get("prompt") or "").strip()
    session_id = data.get("session_id") or "unknown"

    if not prompt:
        return 0

    try:
        from src.domain_builder import build_domain
        from src.gap_detector import detect_gaps, format_gaps_for_context
        from src.sparql_session import SparqlSession
    except Exception as e:
        log(f"import failure: {e}")
        return 0

    # One session for the whole turn → shared budget + cache + Retry-After.
    with SparqlSession() as session:
        try:
            domain = build_domain(prompt, language="en", depth=2,
                                  node_budget=120, max_seeds=6, session=session)
        except Exception:
            log("domain build failed:\n" + traceback.format_exc())
            return 0

        if not domain.seeds:
            log("no entities extracted; skipping")
            return 0

        gaps = []
        if not session.exhausted:
            try:
                gaps = detect_gaps(domain, min_majority=0.4, sibling_limit=10,
                                   session=session)
            except Exception:
                log("gap detection failed (non-fatal):\n" + traceback.format_exc())
        else:
            log(f"session exhausted before gap detection; {session.status_line()}")

    # Cache for the Stop hook
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CACHE_DIR / f"{session_id}.json"
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "domain": domain.to_dict(),
                    "gaps": [g.to_dict() for g in gaps],
                    "prompt": prompt,
                },
                f,
                ensure_ascii=False,
            )
    except Exception:
        log("cache write failed:\n" + traceback.format_exc())

    parts: list[str] = [domain.context_summary()]
    if gaps:
        parts.append("")
        parts.append(format_gaps_for_context(gaps))
    parts.append("")
    parts.append(
        "## Contribution protocol\n"
        "When you and the user agree that a missing Wikidata edge is real, "
        "emit a tag of the form `[PROPOSE <subject_qid> <property_pid> <object_qid>: \"<reasoning>\"]` "
        "inline in your answer. The plugin's Stop hook will stage it as a "
        "Wikidata contribution candidate. Examples of valid properties: "
        "P2283 (uses), P527 (has part), P361 (part of), P1535 (used by), "
        "P366 (has use), P1542 (has effect)."
    )

    additional_context = "\n".join(parts)

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": additional_context,
                }
            }
        )
    )
    log(
        f"session={session_id} seeds={len(domain.seeds)} "
        f"nodes={len(domain.expansion.nodes)} edges={len(domain.expansion.edges)} "
        f"gaps={len(gaps)} sparql={session.status_line()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
