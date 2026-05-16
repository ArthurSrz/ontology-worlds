#!/usr/bin/env python3
"""
hooks/statusline.py
-------------------
Claude Code statusline for an ontology world.

Invoked by Claude Code on every turn (see .claude/settings.json → "statusLine").
Receives JSON on stdin (session info) and outputs the live map to stdout.
The content appears in the blue-boxed statusline below the Claude Code prompt.

Reads the plain-text `.live_map` file written by hooks/post_tool_call.py
after every valid ontology-grounded tool call. If no map exists yet
(fresh session, no interactions), falls back to a one-line summary.

Design constraints:
- Fast (<100ms) — called on every turn
- No dependencies beyond stdlib
- Strips box borders so only the informative inner lines render
- Safe: never raises; always prints something
"""

from __future__ import annotations
import json
import sys
from pathlib import Path


def read_live_map(world_root: Path) -> str | None:
    p = world_root / ".live_map"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def fallback_summary(world_root: Path) -> str:
    """One-line summary when .live_map hasn't been written yet."""
    ontokit = world_root / "ontokit.json"
    name = "Ontology World"
    try:
        cfg = json.loads(ontokit.read_text(encoding="utf-8"))
        onto_path = world_root / cfg.get("ontology", "")
        if onto_path.exists():
            data = json.loads(onto_path.read_text(encoding="utf-8"))
            name = data.get("metadata", {}).get("name", name)
    except Exception:
        pass
    return f"\033[90m🌍 {name} — no interactions yet\033[0m"


def format_statusline(map_text: str) -> str:
    """Strip box borders; keep the informative inner lines."""
    lines = [ln for ln in map_text.splitlines() if ln.strip()]
    # Drop pure-border lines (top ┌…┐, bottom └…┘)
    lines = [ln for ln in lines if not (ln.startswith("┌") or ln.startswith("└"))]
    # Strip leading "│ " from each line (statusline has its own frame)
    cleaned = []
    for ln in lines:
        if ln.startswith("│"):
            ln = ln[1:].lstrip()
        cleaned.append(ln)
    # Colorize: dim the tail lines; keep header bold
    if cleaned:
        cleaned[0] = f"\033[1m{cleaned[0]}\033[0m"
    return "\n".join(cleaned)


def main():
    # Consume stdin (Claude Code sends JSON session info; we don't need it,
    # but must not leave it dangling).
    try:
        sys.stdin.read()
    except Exception:
        pass

    # Claude Code invokes the statusline command from the world root (cwd).
    world_root = Path.cwd()

    map_text = read_live_map(world_root)
    if map_text is None or not map_text.strip():
        print(fallback_summary(world_root))
        return

    print(format_statusline(map_text))


if __name__ == "__main__":
    main()
