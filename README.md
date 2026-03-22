# ontology-worlds

Create small worlds of meaning and have constrained conversations with Claude Code inside them.

Each world is a self-contained Claude Code environment where **every LLM response is grounded in a closed ontology**. No hallucination — only facts that exist in the knowledge graph.

## Watch an LLM navigate a formal world

As Claude explores the ontology, a **live map renders automatically** in your terminal after each interaction:

```diff
┌──────────────────────────────────────────────────┐
│ 🌍 Economics  ████████░░░░░░░░░░░░ 44%  (12/27) │
+ #5 → Bank Ontology, Petrochemical Ontology
+  └ Bank Ontology ─[instanceOf]→ Finance & Biz
+  └ Petrochemical ─[instanceOf]→ Finance & Biz
└──────────────────────────────────────────────────┘
```

No command needed — it just appears. Run `python map.py` for the full view:

```diff
────────────────────────────────────────────────────────────
  🌍 Economics  —  World Map
────────────────────────────────────────────────────────────

  Coverage: █████████████████░░░░░░░░░░░░░░░░░ 44%
  Visited: 12/27 nodes  |  Interactions: 5

  🟢 Current focus    🔵 Visited    ⚫ Unvisited
────────────────────────────────────────────────────────────

  ◆ Finance & Business (12)

+   🟢 STW Thesaurus for Economics (2x)          ← HERE
+       └ ─[instanceOf]→ Finance & Business
!   🔵 Economics Ontology (1x)
!       └ ─[instanceOf]→ Finance & Business
!   🔵 glossary of economics (1x)
!       └ ─[instanceOf]→ Finance & Business
!   🔵 NACE Rev. 2 (2008) (1x)
!       └ ─[instanceOf]→ Finance & Business
!       └ ─[followedBy]→ NACE Rev. 2.1 (2025)
!   🔵 NACE Rev. 2.1 (2025) (1x)
!       └ ─[follows]→ NACE Rev. 2 (2008)
+   🟢 Bank Ontology                             ← HERE
+       └ ─[instanceOf]→ Finance & Business
+   🟢 Petrochemical Ontology                    ← HERE
+   🟢 Ethereum ontology                         ← HERE
    ⚫ Economics Departments...
    ⚫ RePEc Author Service
    ⚫ GoodRelations
    ⚫ Federal Reserve Subject Taxonomy

  ◆ Life Sciences & Healthcare (13)

!   🔵 Core Ontology for Biology and Biomedicine (1x)
!       └ ─[partOf]→ BLOD Biomedical Datasets
!   🔵 Evolution Ontology (1x)
!   🔵 Uberon (1x)
!       └ ─[replaces]→ Amphibian gross anatomy
    ⚫ Mathematical modeling ontology
    ⚫ Coleoptera Anatomy Ontology
    ⚫ ...

────────────────────────────────────────────────────────────
```

> `python map.py --browser` opens an interactive force-directed graph with zoom, hover, and highlighted traversal paths.

**Legend:**

| Symbol | Meaning |
|--------|---------|
| 🟢 `← HERE` | Claude's current focus |
| 🔵 `(3x)` | Previously visited (with count) |
| ⚫ | Unexplored territory |
| ◆ | Class node |
| `└ ─[pred]→` | Edge to neighbor (bold = both visited) |
| `████░░░░` | Coverage bar (% of ontology explored) |

The map reads from `validation_log.jsonl`, written by the PostToolUse hook after every constrained generation. Coverage grows as Claude traverses the ontology.

---

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
- A **live map** shows where Claude is in the ontology after each interaction

## What's inside a world

```
economics_world/
├── .claude/settings.json     # Hooks wired to this world's ontology
├── hooks/                    # Pre/Post tool validation + live map
├── ontology/
│   ├── economics_ontology.json   # JSON-LD ontology (source of truth)
│   └── schemas/              # Compiled JSON Schemas (enum constraints)
├── src/                      # Enforcement engine
├── ontokit.json              # Configuration
├── CLAUDE.md                 # Auto-generated rules for this domain
├── map.py                    # Terminal world map viewer
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
     ↓                                        ↓
Self-correction loop (up to 3 retries)    Live map renders in terminal
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
