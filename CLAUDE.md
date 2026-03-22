# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

This repo is a **world factory**. It creates self-contained Claude Code environments
where every LLM response is grounded in a closed ontology — no hallucination possible.

Each "world" is a subfolder (`<domain>_world/`) with its own ontology, hooks,
validation, and CLAUDE.md. Open Claude Code inside a world to have a fully
constrained conversation about that domain.

---

## Commands

### Setup
```bash
uv pip install -r requirements.txt   # or: pip install -r requirements.txt
```

### Create a world (main workflow)
```bash
python create_world.py "<domain>" --language <lang> --limit <n>
# Example:
python create_world.py "economics" --language en --limit 25
```

### Initialize from an existing JSON-LD ontology file
```bash
python init.py --ontology path/to/my_ontology.json --language en
# Or build from a domain query directly (in current folder, not a world):
python init.py --build "cosmetics regulation" --language fr --limit 30
```

### Inspect a world after creation
```bash
cd <domain>_world
python demo.py --summary          # Print ontology summary
python demo.py --list-entities    # List all entities
python map.py                     # Print live ASCII map to terminal
python map.py --browser           # Open interactive force-directed graph
```

### Test the enforcement engine directly
```bash
python -m src.ontology_builder --domain "cosmetics" --language en --limit 20
```

---

## Rules for Claude Code in this root folder

### You MUST:
- When the user mentions a domain or topic → offer to create a world for it
- Use `python create_world.py "<domain>"` to create worlds
- After creating a world, tell the user to `cd <domain>_world` and run `claude`
- If the user wants to explore available domains first, use the OKG MCP tools
  (`okg_search`, `okg_search_ontologies`, `okg_get_catalog_info`)

### You MUST NOT:
- Answer domain-specific questions from this root folder
- All constrained conversations happen INSIDE worlds, not here
- Don't modify the `src/`, `hooks/`, or `mcp/` directories — they are templates

### Available OKG MCP tools (for domain discovery):
- `okg_get_catalog_info` — see available categories and counts
- `okg_search` — search all resources (ontologies + software)
- `okg_search_ontologies` — search only ontologies/vocabularies
- `okg_search_software` — search semantic software tools

---

## Architecture

### Enforcement pipeline (inside a world)
```
User question
     ↓
System prompt injection (valid entities + predicates from ontology)
     ↓
PreToolUse hook → validates entities/triples → blocks if invalid (exit 2)
     ↓
Claude generates → forced tool_use with JSON Schema (enum-constrained)
     ↓
PostToolUse hook → scores response (0.0–1.0) → blocks if < threshold
     ↓                                        ↓
Self-correction loop (up to 3 retries)    Live map renders in terminal
     ↓
Grounded response (or marked out_of_scope)
```

### Key source modules (in `src/` — template copied into each world)

- **`ontology_builder.py`** — OKG API + Wikidata enrichment pipeline. Takes a domain query, discovers ontologies via OKG, enriches entities from Wikidata (labels, descriptions, relations via P31/P279/P361 etc.), outputs JSON-LD.
- **`ontology_graph.py`** — In-memory directed graph (`OntologyGraph`). Loads JSON-LD, indexes nodes, classes, and edges for O(1) lookup. Used by all other modules.
- **`grammar_builder.py`** — Compiles JSON Schemas from the graph (enum-constrained to valid entity IDs and predicates). Powers structured decoding via Claude's `tool_use`.
- **`validator.py`** — Three validation types: `validate_triple(s, p, o)`, `validate_entities()`, `validate_response()`. Returns `ValidationResult(valid, score, errors, corrections)`.
- **`constrained_client.py`** — Claude API client with self-correction loop (up to `max_retries` from `ontokit.json`).
- **`claude_md_generator.py`** — Auto-generates domain-specific CLAUDE.md from graph contents.
- **`world_map.py`** / **`visualize.py`** — Map rendering logic (terminal ASCII + browser force-directed graph).

### Hooks (in `hooks/` — template copied into each world)

- **`pre_tool_call.py`** — Reads stdin JSON (`session_id`, `tool_name`, `tool_input`). Checks entity fields (`entities_mentioned`, `subject`, `object`, `node_id`) against `graph.nodes`. Exit 2 blocks the tool call with a correction message.
- **`post_tool_call.py`** — Validates the response, logs to `validation_log.jsonl`, renders live mini-map to stderr. Also calls `write_map_file()` to update `.live_map` for `map.py`.

### Ontology format (JSON-LD)
```json
{
  "@context": { "wd": "http://www.wikidata.org/entity/", ... },
  "metadata": { "name": "Economics", "language": "en", "version": "1.0.0" },
  "classes": [...],
  "instances": [...],
  "relations": [...],
  "valid_predicates": [...]
}
```

### Configuration (`ontokit.json` in each world)
```json
{
  "ontology": "ontology/<slug>_ontology.json",
  "tool_name": "ontology_grounded_response",
  "validation_threshold": 0.5,
  "max_retries": 3,
  "language": "en",
  "log_file": "validation_log.jsonl"
}
```

### MCP servers (in `mcp/` — symlinked into each world)
- **`okg_mcp`** — Open Knowledge Graphs search API
- **`wikidata_mcp`** — Wikidata entity/SPARQL queries
- Auto-bootstrapped by `uv` on first Claude Code startup — no manual install needed.

---

## Project structure

```
├── .claude/settings.json     # MCP server config (OKG + Wikidata)
├── mcp/                      # Bundled MCP servers (symlinked into worlds)
│   └── okg_mcp/              # Python MCP server source
├── src/                      # Enforcement engine (template — copied into worlds)
├── hooks/                    # Hook templates (copied into worlds)
├── create_world.py           # Main entry point — creates worlds
├── init.py                   # Initialize project from existing ontology
├── demo.py                   # Query tool (also copied into worlds)
├── map.py                    # World map viewer (also copied into worlds)
├── requirements.txt          # Python dependencies (httpx, jsonschema, python-dotenv)
│
├── economics_world/          # ← Created on demand
└── ...
```

---

## Inside a world

Each `<domain>_world/` folder is fully self-contained:

```
economics_world/
├── .claude/settings.json     # Hooks wired to this world's ontology
├── .claude/settings.local.json  # Allows Bash(python:*)
├── .mcp.json                 # MCP server config (okg + mcp-wikidata)
├── mcp -> ../mcp             # Symlink to shared MCP servers
├── hooks/                    # Pre/Post tool validation + live map
├── ontology/
│   ├── economics_ontology.json   # JSON-LD ontology (source of truth)
│   └── schemas/              # Compiled JSON Schemas (enum constraints)
├── src/                      # Enforcement engine (copy)
├── ontokit.json              # Configuration
├── CLAUDE.md                 # Auto-generated rules for this domain
├── validation_log.jsonl      # Append-only validation log
├── map.py / demo.py          # Tools
└── requirements.txt
```
