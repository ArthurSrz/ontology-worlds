#!/usr/bin/env python3
"""
hooks/stop.py
-------------
Claude Code Stop hook.

Loads the JIT domain cached by UserPromptSubmit, re-scores Claude's last
response against it, captures any [PROPOSE ...] contribution tags, and
logs everything to validation_log.jsonl.

Hook protocol:
  stdin  : {session_id, transcript_path, stop_hook_active, ...}
  stdout : JSON to control whether Claude continues (we generally don't block)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

CACHE_DIR = Path(os.environ.get("ONTOLOGY_WORLDS_CACHE", Path(tempfile.gettempdir()) / "ontology-worlds"))
CONTRIBUTIONS_DIR = ROOT / "contributions"
LOG_PATH = ROOT / "validation_log.jsonl"
THRESHOLD = float(os.environ.get("ONTOLOGY_WORLDS_THRESHOLD", "0.5"))


def log(msg: str) -> None:
    print(f"[ontology-worlds:Stop] {msg}", file=sys.stderr)


def _last_assistant_text(transcript_path: str | None) -> str:
    """Read the latest assistant message from the Claude Code transcript JSONL."""
    if not transcript_path:
        return ""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    last_text = ""
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Claude Code transcripts: messages have {"type":"assistant","message":{"content":[...]}}
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, str):
                    last_text = content
                elif isinstance(content, list):
                    pieces = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            pieces.append(c.get("text", ""))
                    if pieces:
                        last_text = "\n".join(pieces)
    except Exception:
        log("transcript read failed:\n" + traceback.format_exc())
    return last_text


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        log(f"bad stdin: {e}")
        return 0

    session_id = data.get("session_id") or "unknown"
    transcript_path = data.get("transcript_path")
    stop_already_active = bool(data.get("stop_hook_active"))

    cache_path = CACHE_DIR / f"{session_id}.json"
    if not cache_path.exists():
        log(f"no cached domain for session={session_id}; passthrough")
        return 0

    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        log("cache read failed:\n" + traceback.format_exc())
        return 0

    response_text = _last_assistant_text(transcript_path)
    if not response_text:
        log("no assistant text; passthrough")
        return 0

    try:
        from src.domain_builder import JITDomain
        from src.domain_validator import validate_response
        from src.contribution_recorder import capture
    except Exception as e:
        log(f"import failure: {e}")
        return 0

    domain = JITDomain.from_dict(cached.get("domain", {}))
    gaps = cached.get("gaps", [])

    # Build (S,P,O) → question_text map for provenance on contributions
    gap_origin = {
        (g["seed_a_qid"], g["suggested_property"], g["seed_b_qid"]): g["question_text"]
        for g in gaps
    }

    try:
        rv = validate_response(response_text, domain)
    except Exception:
        log("validation failed:\n" + traceback.format_exc())
        return 0

    contribs = []
    try:
        contribs = capture(
            response_text=response_text,
            source_prompt=cached.get("prompt", ""),
            session_id=session_id,
            output_dir=CONTRIBUTIONS_DIR,
            gap_origin=gap_origin,
        )
    except Exception:
        log("contribution capture failed:\n" + traceback.format_exc())

    # Append log entry
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "session_id": session_id,
                        "prompt": cached.get("prompt", ""),
                        "seeds": [s["qid"] for s in cached.get("domain", {}).get("seeds", [])],
                        "domain_size": len(cached.get("domain", {}).get("nodes", {})),
                        "gaps": len(gaps),
                        "score": rv.score,
                        "in_domain": rv.in_domain,
                        "out_of_domain": rv.out_of_domain,
                        "staged_contributions": [c.to_dict() for c in contribs],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        log("log write failed:\n" + traceback.format_exc())

    log(
        f"session={session_id} score={rv.score:.2f} "
        f"in={len(rv.in_domain)} ood={len(rv.out_of_domain)} "
        f"contribs={len(contribs)}"
    )

    # Block & reword if the response strayed too far out of the domain — but
    # only once per turn (Stop hook is re-fired after Claude continues).
    if not stop_already_active and rv.score < THRESHOLD and rv.out_of_domain:
        reason = (
            f"Response in-domain score is {rv.score:.2f} (threshold {THRESHOLD:.2f}). "
            f"Out-of-domain entities: {', '.join(rv.out_of_domain_labels[:5])}. "
            f"Please rewrite using only in-domain Wikidata entities, or explicitly "
            f"name and justify why an out-of-domain concept is necessary."
        )
        sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
