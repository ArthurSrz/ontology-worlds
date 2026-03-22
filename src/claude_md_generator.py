"""
claude_md_generator.py
----------------------
Auto-generates a domain-appropriate CLAUDE.md from any loaded ontology.

The generated CLAUDE.md contains:
- Project title and context from ontology metadata
- Entity table with Wikidata links
- Predicate table
- Enforcement rules (tool name, correction loop, etc.)
- Quick-start commands
"""

from __future__ import annotations
from .ontology_graph import OntologyGraph
from .config import OntoKitConfig


def generate(graph: OntologyGraph, config: OntoKitConfig) -> str:
    """Generate a complete CLAUDE.md from the ontology graph and config."""
    meta = graph.metadata
    name = meta.get("name", "Ontology")
    description = meta.get("description", "")
    language = meta.get("language", "en")
    tool_name = config.tool_name
    max_retries = config.max_retries

    sections = [
        _header(name, description),
        _structure(),
        _quickstart(),
        _rules(name, tool_name, max_retries),
        _entity_table(graph),
        _predicate_table(graph),
        _extension_note(),
    ]
    return "\n".join(sections)


def _header(name: str, description: str) -> str:
    lines = [
        f"# Structured Decoding — {name}",
        "## Ontology-Enforced Claude Code Environment",
        "",
        "---",
        "",
        "## Context",
        "",
        f"This project implements **Structured Decoding** to constrain",
        f"an LLM to only generate responses grounded in a **closed ontology** —",
        f"here: **{name}**.",
    ]
    if description:
        lines.append(f"")
        lines.append(f"> {description}")
    lines.extend([
        "",
        "### Core principle",
        "",
        "> At each generated token, values incompatible with the ontological schema",
        "> are masked. The LLM traverses the graph rather than free language space.",
        "",
        "Since the Claude API does not expose logits, this is **simulated** via:",
        "1. **Dynamic JSON Schema** compiled from the graph (grammar_builder)",
        "2. **Mandatory tool_use** with this schema → structured output",
        "3. **PreToolUse / PostToolUse Hooks** → validation before and after generation",
        "4. **Self-correction loop** if the response exceeds constraints",
        "",
        "---",
    ])
    return "\n".join(lines)


def _structure() -> str:
    return """
## Project structure

```
├── .claude/
│   └── settings.json          # Claude Code hooks (Pre/PostToolUse)
├── hooks/
│   ├── pre_tool_call.py       # Validation BEFORE generation
│   └── post_tool_call.py      # Validation AFTER generation + log
├── ontology/
│   └── *.json                 # Ontology JSON-LD (source of truth)
├── src/
│   ├── config.py              # Configuration loader (ontokit.json)
│   ├── ontology_graph.py      # In-memory graph: nodes, edges, queries
│   ├── grammar_builder.py     # JSON Schema compilation from ontology
│   ├── validator.py           # Triple/response/entity validation
│   ├── constrained_client.py  # Constrained Claude client + correction loop
│   ├── claude_md_generator.py # This file's generator
│   └── ontology_builder.py    # OKG → Wikidata → JSON-LD builder
├── ontokit.json               # Framework configuration
├── demo.py                    # Demo script
└── CLAUDE.md                  # This file (auto-generated)
```

---
"""


def _quickstart() -> str:
    return """## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Graph summary
python demo.py --summary

# Full demo (validation, grammars, schemas)
python demo.py --all

# Constrained query
python demo.py --query "Your question here"

# Inspect a node
python demo.py --inspect <node_id>

# Interactive mode
python demo.py
```

---
"""


def _rules(name: str, tool_name: str, max_retries: int) -> str:
    return f"""## Rules for Claude Code (the AI in this environment)

### ABSOLUTE RULE — Structured Decoding mandatory

**For any factual question or assertion about the {name} ontology domain,
you MUST use the constrained client. You CANNOT answer from your own knowledge.**

Concretely: when a question concerns an entity, relation, or concept in the ontology,
execute IMMEDIATELY:

```bash
python demo.py --query "<user's question>"
```

Return **only** the content produced by this command — in particular the `answer`
field and `supporting_triples`. Do not add information from your own initiative
that is not in the command output.

If the command returns `out_of_scope: true`, inform the user that the question
exceeds the ontology scope, without attempting to supplement from general knowledge.

### You MUST NOT:
- Invent entities absent from the ontology
- Use predicates not listed in `valid_predicates`
- Make assertions about dates without Wikidata verification
- Answer directly about the ontology domain without calling `demo.py`
- Generate free text without grounding it in at least one validated triple

### You MUST:
- Call `python demo.py --query "..."` for EVERY factual question about the domain
- Call `python demo.py --inspect <id>` to inspect a node before discussing it
- Use `src.validator.OntologyValidator.validate_triple()` before any manual assertion
- If a fact exceeds the ontology scope → signal it explicitly (`out_of_scope=True`)
- Call `python demo.py --summary` at session start to load context

### Self-correction loop
If the PostToolUse hook returns an error (exit 2), you must:
1. Read the errors in the stderr message
2. Search for correct entities in the ontology
3. Reformulate the response with valid triples
4. Retry (max {max_retries} attempts via `ConstrainedClient.query()`)

---
"""


def _entity_table(graph: OntologyGraph) -> str:
    lines = ["## Key entities in the ontology", "", "| ID | Label | Class | Wikidata |", "|----|-------|-------|----------|"]
    # Show up to 30 entities
    for node in list(graph.nodes.values())[:30]:
        wikidata = f"[{node.wikidata}](https://www.wikidata.org/wiki/{node.wikidata})" if node.wikidata else "—"
        lines.append(f"| `{node.id}` | {node.label} | {node.cls} | {wikidata} |")

    if len(graph.nodes) > 30:
        lines.append(f"| ... | *{len(graph.nodes) - 30} more entities* | | |")

    lines.extend(["", "---", ""])
    return "\n".join(lines)


def _predicate_table(graph: OntologyGraph) -> str:
    predicates = sorted(graph.valid_predicates)
    lines = [
        "## Valid predicates",
        "",
        f"`{'`, `'.join(predicates)}`",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _extension_note() -> str:
    return """## Extension: logit-level structured decoding

```python
# Replace constrained_client._call_claude() with:
import outlines
import outlines.models as models

model = models.transformers("mistralai/Mistral-7B-v0.1")
schema = grammar_builder.schema_query_response()

generator = outlines.generate.json(model, schema)
response = generator(prompt)  # Real logit masking!
```

This gives **hermetic** structured decoding — no token incompatible
with the schema can be generated. Requires a local model via HuggingFace.
"""
