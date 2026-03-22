# ontology-worlds

Create small worlds of meaning and have constrained conversations with Claude Code inside them.

Each world is a self-contained Claude Code environment where **every LLM response is grounded in a closed ontology**. No hallucination — only facts that exist in the knowledge graph.

## How it works

```
Clone → Ask for a domain → Enter the world → Constrained conversation
```

### 1. Clone and open

```bash
git clone https://github.com/ArthurSrz/ontology-worlds.git
cd ontology-worlds
pip install -r requirements.txt
claude
```

### 2. Ask for a world

Tell Claude a domain — economics, cosmetics regulation, French open data, anything discoverable through the [Open Knowledge Graphs](https://openknowledgegraphs.com):

```bash
python create_world.py "economics" --language en --limit 25
```

This searches OKG for ontologies, enriches entities from Wikidata, and builds a self-contained `economics_world/` folder.

### 3. Enter the world

```bash
cd economics_world
claude
```

Inside the world, Claude is constrained:
- Every entity must exist in the ontology
- Every fact must be a valid triple in the graph
- Hooks validate before AND after each generation
- A self-correction loop retries up to 3 times on invalid output

## What's inside a world

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
└── demo.py                   # Query tool
```

## The enforcement pipeline

```
User question
     ↓
System prompt injection (valid entities + predicates)
     ↓
PreToolUse hook → validates entities/triples → blocks if invalid
     ↓
Claude generates → forced tool_use with JSON Schema (enum-constrained)
     ↓
PostToolUse hook → scores response (0.0–1.0) → blocks if < threshold
     ↓
Self-correction loop (up to 3 retries with feedback)
     ↓
Grounded response (or marked out_of_scope)
```

## The ontology format

Standard JSON-LD with metadata:

```json
{
  "@context": { "wd": "http://www.wikidata.org/entity/", ... },
  "metadata": {
    "name": "Economics",
    "language": "en",
    "version": "1.0.0"
  },
  "classes": [...],
  "instances": [...],
  "relations": [...],
  "valid_predicates": [...]
}
```

You can also bring your own ontology:

```bash
python init.py --ontology path/to/my_ontology.json --language en
```

## Requirements

- Python 3.11+
- `anthropic` (for constrained LLM queries)
- `httpx` (for OKG + Wikidata API calls)
- [Claude Code](https://claude.ai/claude-code) (for the constrained environment)

## License

MIT
