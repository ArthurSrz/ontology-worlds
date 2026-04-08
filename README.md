```
 ██████╗ ███╗   ██╗████████╗ ██████╗ ██╗      ██████╗  ██████╗██╗   ██╗
██╔═══██╗████╗  ██║╚══██╔══╝██╔═══██╗██║     ██╔═══██╗██╔════╝╚██╗ ██╔╝
██║   ██║██╔██╗ ██║   ██║   ██║   ██║██║     ██║   ██║██║  ███╗╚████╔╝
██║   ██║██║╚██╗██║   ██║   ██║   ██║██║     ██║   ██║██║   ██║ ╚██╔╝
╚██████╔╝██║ ╚████║   ██║   ╚██████╔╝███████╗╚██████╔╝╚██████╔╝  ██║
 ╚═════╝ ╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚══════╝ ╚═════╝  ╚═════╝   ╚═╝
                         W O R L D S
```

<div align="center">

[![GitHub stars](https://img.shields.io/github/stars/ArthurSrz/ontology-worlds?style=flat-square&color=yellow)](https://github.com/ArthurSrz/ontology-worlds/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ArthurSrz/ontology-worlds?style=flat-square&color=blue)](https://github.com/ArthurSrz/ontology-worlds/network)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python)](https://www.python.org)
[![Claude Code](https://img.shields.io/badge/Claude_Code-compatible-blueviolet?style=flat-square)](https://claude.ai/claude-code)

**Create mini worlds of meaning. Have constrained conversations inside them.**

</div>

---

Each world is a self-contained Claude Code environment where **every LLM response is grounded in a closed ontology**. No hallucination — only facts that exist in the knowledge graph.

## Watch an LLM navigate a formal world

As Claude explores the ontology, a **live map renders automatically** in your terminal after each interaction.

**On world creation** — a full class/concept overview appears immediately:

```
┌──────────────────────────────────────────────────┐
│ 🌍 Economics  ░░░░░░░░░░░░░░░░░░░░ 0%  (0/69)
│ #0
│  Macroeconomics    Inflation, Deflation, Gross Domes…, Economic Gr… +13
│  Microeconomics    Supply and…, Market Equi…, Elasticity +1
│  Monetary & Finance  Central Bank, Interest Ra…, Exchange Ra…
│  International Tra…  Comparative…, Balance of…, Trade Balan…
└──────────────────────────────────────────────────┘
```

**After each query** — an inline ASCII concept graph shows where Claude is and how concepts connect:

```
┌──────────────────────────────────────────────────┐
│ 🌍 Economics  ██████░░░░░░░░░░░░░░ 33%  (23/69)
│ #5 → Inflation, Central Bank
│  [Inflation]*  ──instanceOf──>  [Macroeconomics]* ──instanceOf──>  [Finance & Biz]
│       └──  ──measuredBy──>  [Consumer Pric…]*
│  [Central Bank]*  ──implements──>  [Monetary Poli…]* ──affects──>  [Inflation]*
│       └──  ──setBy──>  [Interest Rate]*
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
| `[Label]*` green | Claude's current focus (this turn) |
| `[Label]` blue | Previously visited concept |
| `[Label]` dim | Unexplored concept |
| `──pred──>` | Edge between concepts |
| `+N` | Additional concepts in class not shown |
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
uv pip install -r requirements.txt   # or: pip install -r requirements.txt
claude
```

> **Note:** The bundled MCP servers (`mcp/`) are auto-bootstrapped by `uv` on first Claude Code startup — no manual install needed.

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
- [`uv`](https://docs.astral.sh/uv/) (recommended — auto-bootstraps MCP server dependencies)
- `httpx` (for OKG + Wikidata API calls)
- `jsonschema` (for JSON Schema validation)
- [Claude Code](https://claude.ai/claude-code) — **Claude Code is the LLM**. No API key needed.

---

## Available mini-worlds

### `machines_attentionnelles_world` — Second-order attention machines

**Companion to:** [the Substack article on digital traces, attention windows, and the epistemology of social media data](https://arthursarazin.substack.com)

This mini-world encodes the theory developed in the article as a formal ontology that Claude must navigate. The core argument: social media data does not reveal what people *need* — it reveals what they are *likely to pay attention to* within a group. This distinction is formalized here as a knowledge graph.

**Key concepts in the ontology:**

| Concept | What it represents |
|---|---|
| Machine attentionnelle (2nd order) | The feedback loop between individual attention filters and network algorithms |
| Filtre individuel / Filtre reseau | The two attentional filters that amplify each other |
| Boucle de retroaction | The closed loop that distorts data away from actual needs |
| Fenetre d'attention | Attention windows — what the data actually maps |
| Besoin vs susceptibilite attentionnelle | The epistemological problem: needs vs. attention susceptibility |
| Traces numeriques | Digital traces — the raw material under scrutiny |

**Theoretical references:** Yves Citton (*Pour une ecologie de l'attention*), Seth Stephens-Davidowitz (*Everybody Lies*)

### How to use this mini-world

```bash
# 1. Clone the subscribers branch
git clone -b subscribers https://github.com/ArthurSrz/ontology-worlds.git
cd ontology-worlds

# 2. Install dependencies
cd machines_attentionnelles_world
pip install -r requirements.txt   # or: uv pip install -r requirements.txt

# 3. Launch Claude Code inside the world
claude
```

Once inside, Claude is constrained to the ontology. Try:

```bash
# Get an overview of the ontology
python demo.py --summary

# Ask a grounded question
python demo.py --query "What does social media data actually reveal?"

# View the world map
python map.py
```

Every response Claude gives is validated against the knowledge graph. If a claim falls outside the ontology, it is flagged as `out_of_scope` rather than hallucinated.

### `data_design_interfaces_world` — Ontology-isomorphic apps

**Companion to:** Arthur Sarazin, *Le Bateau Ivre des Données* (2023)

Two Streamlit applications that are **structurally identical to their ontology**. Every UI component, user action, and data state maps 1:1 to an ontology node or relation.

| | Consumption app | Construction app |
|---|---|---|
| **Architecture** | `ArchitectureConsommation` | `ArchitectureConstruction` |
| **Temporality** | Continuous (infinite scroll) | Discrete (5-stage pipeline) |
| **User role** | Passive consumer | Active builder |
| **Attention** | Consumed | Preserved |
| **Data** | Flux (feed_items) | Stock (datasets) |
| **Mechanism** | Algorithm + scroll | Pipeline I-T-O |
| **Components** | Feed, Cards, Notifications, Recommendations | Form, Editable table, Query panel, Terminal |
| **Actions** | Scroll, Like, Share, Save | Create, Transform, Query, Validate, Export |

**74 nodes · 229 edges · 19 predicates · 40 bijective couplings**

Run the apps:
```bash
cd data_design_interfaces_world
streamlit run apps/app.py
```

View the bijection: open `couplage_suisse.html` or visit [arthursrz.github.io/ontology-worlds](https://arthursrz.github.io/ontology-worlds/)

### `court_case_reasoning_world` — Structured evidence reasoning in the RFK assassination case

**Companion to:** Arthur Sarazin, *Ontology Worlds* (2025)

This mini-world encodes the assassination of Robert F. Kennedy (1968) as a formal evidence reasoning ontology. Every claim, contradiction, witness, and forensic finding is a node — Claude must navigate the graph rather than free-associate. The core demonstration: **stubborn facts and actual contradictions can ground legal analysis beyond LLM correlation**.

**Key concepts in the ontology:**

| Concept | What it represents |
|---|---|
| Sirhan Sirhan | The convicted shooter — and a central node of evidentiary contradiction |
| Thomas Noguchi | Chief Medical Examiner — his autopsy findings are a forensic anchor |
| Thane Eugene Cesar | Security guard — subject of unresolved proximity and weapon claims |
| Powder burns / bullet trajectory | Physical evidence nodes that constrain what can be asserted about the shooting |
| Contradiction | Explicit class for documented conflicts between evidence nodes |
| Evidence Assessment | Structured class for reliability and corroboration scoring |

**13 classes · 59 instances · 146 relations · 20 predicates**

```bash
cd court_case_reasoning_world
pip install -r requirements.txt
claude
```

Once inside, Claude is constrained to the ontology. Try:

```bash
python demo.py --summary
python demo.py --query "What does the physical evidence say about the shooter's position?"
python map.py
```

Every claim Claude makes is validated against the knowledge graph. Contradictions between evidence nodes are surfaced explicitly — not smoothed over.

---

## License

MIT
