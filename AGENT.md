# AGENT.md — Installation guide for Claude Code agents

This file tells a Claude Code agent how to install and use **ontology-worlds**.
The repo ships **three independent artifacts**. Pick the one that matches the user's intent.

| Artifact | Path | Use when |
|---|---|---|
| `plugin/` | Claude Code plugin (JIT Wikidata-grounded conversations) | User wants every prompt grounded in a fresh ontology, with `/world`, `/gaps`, `/contribute` slash commands |
| `mini-worlds/` | Self-contained pre-built worlds (closed ontologies) | User wants to explore a specific domain (legal reasoning, attentional theory, data-design isomorphism) with hooks that block out-of-ontology claims |
| `ontology-worlds-plugin.zip` | Cowork bundle (on `main` branch) | User wants the lightweight, hook-free skills/commands version for Claude Cowork |

---

## 1 — Install the plugin (`plugin/`)

**Prereqs:** Python 3.11+, `httpx`, `jsonschema`, `python-dotenv`.

```bash
git clone https://github.com/ArthurSrz/ontology-worlds.git
cd ontology-worlds
pip install -r plugin/requirements.txt
```

From any Claude Code session, point the plugin installer at the `plugin/` folder:

```
/plugin install /absolute/path/to/ontology-worlds/plugin
```

`plugin/.claude-plugin/plugin.json` is the manifest. `${CLAUDE_PLUGIN_ROOT}` resolves to `plugin/`, so `hooks/`, `commands/`, and `src/` are all picked up automatically — no path edits needed.

After install, the following are wired:
- **UserPromptSubmit** hook → builds JIT domain, injects context
- **Stop** hook → scores response in-domain, stages Wikidata contribution candidates
- Slash commands: `/world`, `/gaps`, `/contribute`

---

## 2 — Use a mini-world (`mini-worlds/<name>/`)

Each subfolder is a fully self-contained Claude Code environment. Pick one and `cd` in.

```bash
git clone https://github.com/ArthurSrz/ontology-worlds.git
cd ontology-worlds/mini-worlds/<world-name>
pip install -r requirements.txt
claude
```

Available worlds:
- `court_case_reasoning_world/` — RFK assassination evidence reasoning (13 classes · 59 instances · 146 relations)
- `machines_attentionnelles_world/` — Second-order attention machines (FR, Citton/Stephens-Davidowitz)
- `data_design_interfaces_world/` — Ontology-isomorphic Streamlit apps (74 nodes · 229 edges · 40 bijective couplings)
- `le_couple/` — (additional working dir, has its own `.claude/` config)

Inside the world, Claude is constrained: every entity must exist in the ontology, hooks validate before and after each generation, and a live ASCII map renders coverage after every turn.

---

## 3 — Cowork bundle (`ontology-worlds-plugin.zip`)

Only present on the `main` branch. Download the zip directly from GitHub or:

```bash
git fetch origin main
git show origin/main:ontology-worlds-plugin.zip > /tmp/ontology-worlds-plugin.zip
unzip /tmp/ontology-worlds-plugin.zip -d ~/
```

Contains a skills-based variant of the plugin (`.claude-plugin/`, `commands/`, `skills/wikidata-ground/SKILL.md`) — no Python hooks, designed for Claude Cowork environments where hooks aren't available.

---

## Architecture quick-reference

```
ontology-worlds/
├── plugin/                          # Artifact 1: the JIT plugin
│   ├── .claude-plugin/plugin.json
│   ├── hooks/{user_prompt_submit,stop}.py
│   ├── commands/{world,gaps,contribute}.md
│   ├── src/                         # JIT pipeline + legacy factory engine
│   ├── tests/
│   ├── scripts/
│   ├── mcp/                         # OKG + Wikidata MCP servers
│   ├── requirements.txt
│   └── {create_world,init,demo,map,log_entities}.py
│
├── mini-worlds/                     # Artifact 2: pre-built closed-ontology envs
│   ├── court_case_reasoning_world/
│   ├── machines_attentionnelles_world/
│   ├── data_design_interfaces_world/
│   └── le_couple/
│
├── ontology-worlds-plugin.zip       # Artifact 3 (main branch): cowork bundle
├── AGENT.md                         # This file
├── README.md
├── CLAUDE.md                        # Architecture notes for contributors
└── LICENSE
```

## Pipeline (plugin mode)

```
prompt
  → src/entity_extractor.py    (regex + wbsearchentities)
  → src/disambiguator.py       (mutual-context joint optimisation)
  → src/sparql_expander.py     (batched BFS over P31/P279/P361/…)
  → src/domain_builder.py      (JITDomain — ephemeral, in-memory)
  → src/gap_detector.py        (class-cone reachability check)
  → plugin/hooks/user_prompt_submit.py  (inject additionalContext)
  → Claude responds (may emit [PROPOSE …] tags)
  → plugin/hooks/stop.py
      ├─ src/domain_validator.py     (in-domain score; block + reword if low)
      └─ src/contribution_recorder.py (stage QuickStatements)
```

`src/sparql_session.py` is the single SPARQL gateway: Wikimedia-policy User-Agent, 60 queries / 55 s budget per turn, per-turn cache, `Retry-After` honoured.
