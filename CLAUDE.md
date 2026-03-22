# Ontology Worlds — Constrained Claude Code Environments

## What this is

This repo is a **world factory**. It creates self-contained Claude Code environments
where every LLM response is grounded in a closed ontology — no hallucination possible.

Each "world" is a subfolder (`<domain>_world/`) with its own ontology, hooks,
validation, and CLAUDE.md. Open Claude Code inside a world to have a fully
constrained conversation about that domain.

---

## How to create a world

When the user asks for a domain (e.g., "economics", "cosmetics regulation",
"French open data"), run:

```bash
python create_world.py "<domain>" --language <lang> --limit <n>
```

This will:
1. Search the Open Knowledge Graphs for ontologies related to the domain
2. Enrich entities from Wikidata (labels, descriptions, relations)
3. Build a JSON-LD ontology file
4. Create a `<domain>_world/` folder with the full enforcement pipeline
5. Generate CLAUDE.md, hooks, schemas — everything auto-configured

**Example:**
```bash
python create_world.py "economics" --language en --limit 25
```

Then the user enters the world:
```bash
cd economics_world
claude    # Claude Code starts — constrained to the economics ontology
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

## Project structure

```
├── .claude/settings.json     # MCP server config (OKG)
├── mcp/                      # Bundled Open Knowledge Graphs MCP server
│   └── okg_mcp/              # Python MCP server source
├── src/                      # Enforcement engine (template — copied into worlds)
│   ├── config.py             # Configuration loader
│   ├── ontology_graph.py     # In-memory graph engine
│   ├── grammar_builder.py    # JSON Schema compiler
│   ├── validator.py          # Triple/entity/response validation
│   ├── constrained_client.py # Claude client + self-correction loop
│   ├── claude_md_generator.py# CLAUDE.md auto-generator
│   └── ontology_builder.py   # OKG → Wikidata → JSON-LD pipeline
├── hooks/                    # Hook templates (copied into worlds)
│   ├── pre_tool_call.py      # PreToolUse validation
│   └── post_tool_call.py     # PostToolUse validation + logging
├── create_world.py           # Main entry point — creates worlds
├── demo.py                   # Demo script (also copied into worlds)
├── requirements.txt          # Python dependencies
├── CLAUDE.md                 # This file (factory instructions)
│
├── economics_world/          # ← Created on demand
├── cosmetics_world/          # ← Created on demand
└── ...
```

---

## Inside a world

Each `<domain>_world/` folder is fully self-contained:

```
economics_world/
├── .claude/settings.json     # Hooks wired to this world's ontology
├── hooks/                    # Pre/Post tool validation
├── ontology/
│   ├── economics_ontology.json   # JSON-LD ontology (source of truth)
│   └── schemas/              # Compiled JSON Schemas (enum constraints)
├── src/                      # Enforcement engine
├── ontokit.json              # Configuration
├── CLAUDE.md                 # Auto-generated rules for this domain
├── demo.py                   # Query tool
└── requirements.txt
```

Every tool call inside a world passes through:
1. **PreToolUse hook** → validates entities/triples BEFORE generation
2. **JSON Schema** → constrains output to graph values (enum)
3. **PostToolUse hook** → validates response, scores it (0.0–1.0)
4. **Self-correction loop** → up to 3 retries with feedback if invalid
