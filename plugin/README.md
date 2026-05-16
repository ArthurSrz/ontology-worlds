# ontology-worlds plugin

JIT Wikidata-grounded plugin for Claude Code. Every prompt builds a fresh
domain subgraph via mutual-context disambiguation and class-cone reachability;
every chat turn surfaces candidate Wikidata edits.

## Install

```bash
pip install -r requirements.txt
```

Then, from any Claude Code session:

```
/plugin install /absolute/path/to/this/folder
```

The manifest is `.claude-plugin/plugin.json`. `${CLAUDE_PLUGIN_ROOT}` resolves
to this folder, so `hooks/`, `commands/`, and `src/` are picked up
automatically.

## What you get

- **UserPromptSubmit hook** — extracts entities, expands the domain via
  Wikidata SPARQL, detects gaps, injects context into the model.
- **Stop hook** — re-scores the response in-domain, stages
  `[PROPOSE <S> <P> <O>: "<reasoning>"]` tags as Wikidata contribution
  candidates.
- **Slash commands** — `/world`, `/gaps`, `/contribute`.

## Legacy: world factory

This folder also contains the original pre-built-world factory
(`create_world.py`, `init.py`, `demo.py`, `map.py`, `log_entities.py`) —
still works for offline domain construction. Outputs go to
`../mini-worlds/<domain>_world/` by convention.

## Architecture

See `../AGENT.md` for the full pipeline diagram and `../CLAUDE.md` for
contributor notes.
