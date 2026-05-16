# mini-worlds

Each subfolder here is a **self-contained Claude Code environment** bound to a
closed ontology. Hooks validate every entity and triple against the graph
before and after generation. Out-of-ontology claims are blocked or rewritten.

## Use one

```bash
cd <world-name>
pip install -r requirements.txt
claude
```

A live ASCII map renders coverage after every turn. Run `python map.py` for
the full view or `python map.py --browser` for an interactive force-directed
graph.

## Worlds

| Folder | Domain | Companion text |
|---|---|---|
| `court_case_reasoning_world/` | RFK assassination evidence reasoning | Arthur Sarazin, *Ontology Worlds* (2025) |
| `machines_attentionnelles_world/` | Second-order attention machines (FR) | Substack article on digital traces |
| `data_design_interfaces_world/` | Ontology-isomorphic Streamlit apps | *Le Bateau Ivre des Données* (2023) |
| `le_couple/` | (separate repo — see below) | — |

### `le_couple/`

`le_couple` is its own GitHub repository (`github.com/ArthurSrz/le_couple`) and is
not embedded directly. To use it locally:

```bash
git submodule add git@github.com:ArthurSrz/le_couple.git mini-worlds/le_couple
git submodule update --init --recursive
```

## Anatomy of a world

```
<world>/
├── .claude/settings.json     # Hooks wired to this world's ontology
├── .mcp.json                 # OKG + Wikidata MCP server config
├── hooks/                    # Pre/Post tool validation + statusline
├── ontology/
│   ├── <slug>_ontology.json  # JSON-LD source of truth
│   └── schemas/              # Compiled JSON Schemas (enum-constrained)
├── src/                      # Enforcement engine (copy of plugin/src)
├── mcp/                      # OKG + Wikidata MCP servers
├── ontokit.json              # Validation threshold, max retries, etc.
├── CLAUDE.md                 # Auto-generated rules for this domain
├── map.py / demo.py          # Inspection tools
└── requirements.txt
```

## Make a new one

Use the factory in `../plugin/`:

```bash
cd ../plugin
python create_world.py "<domain>" --language en --limit 25
```
