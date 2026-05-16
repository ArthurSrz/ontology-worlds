# Structured Decoding — Data Design Interfaces
## Ontology-Enforced Claude Code Environment

---

## Context

This project implements **Structured Decoding** to constrain
an LLM to only generate responses grounded in a **closed ontology** —
here: **Data Design Interfaces**.

> Ontologie des interfaces comme architectures de nos interactions avec les données — d'après Arthur Sarazin (Le Bateau Ivre des Données, 2023)

### Core principle

> At each generated token, values incompatible with the ontological schema
> are masked. The LLM traverses the graph rather than free language space.

Since the Claude API does not expose logits, this is **simulated** via:
1. **Dynamic JSON Schema** compiled from the graph (grammar_builder)
2. **Mandatory tool_use** with this schema → structured output
3. **PreToolUse / PostToolUse Hooks** → validation before and after generation
4. **Self-correction loop** if the response exceeds constraints

---

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

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Graph summary
python demo.py --summary

# Full demo (validation, grammars, schemas)
python demo.py --all

# Constrained query (outputs ontology context for Claude Code)
python demo.py --query "Your question here"

# Inspect a node
python demo.py --inspect <node_id>

# Interactive mode
python demo.py
```

> **No API key needed** — this world runs inside Claude Code, which is the LLM.
> Ontology enforcement happens through hooks and JSON Schema constraints.

---

## Rules for Claude Code (the AI in this environment)

### ABSOLUTE RULE — Structured Decoding mandatory

**For any factual question or assertion about the Data Design Interfaces ontology domain,
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
- **After EVERY constrained query response**, show the world map to the user:
  ```bash
  cat .live_map
  ```
  The `.live_map` file is updated automatically by the PostToolUse hook after each interaction.
  This shows the user where you are in the ontology. ALWAYS do this — never skip.

### Self-correction loop
If the PostToolUse hook returns an error (exit 2), you must:
1. Read the errors in the stderr message
2. Search for correct entities in the ontology
3. Reformulate the response with valid triples
4. Retry (max 3 attempts via `ConstrainedClient.query()`)

---

## Key entities in the ontology

| ID | Label | Class | Wikidata |
|----|-------|-------|----------|
| `ConceptFondamental` | Concept fondamental | _Class | — |
| `ArchitectureInterface` | Architecture d'interface | _Class | — |
| `MecanismeInteraction` | Mécanisme d'interaction | _Class | — |
| `DimensionTemporelle` | Dimension temporelle | _Class | — |
| `ExempleInterface` | Exemple d'interface | _Class | — |
| `RoleUtilisateur` | Rôle de l'utilisateur | _Class | — |
| `OutilNavigation` | Outil de navigation | _Class | — |
| `Interface` | Interface | ConceptFondamental | [Q47146](https://www.wikidata.org/wiki/Q47146) |
| `ArchitectureInformation` | Architecture de l'information | ConceptFondamental | [Q845921](https://www.wikidata.org/wiki/Q845921) |
| `EconomieAttention` | Économie de l'attention | ConceptFondamental | [Q295287](https://www.wikidata.org/wiki/Q295287) |
| `Donnee` | Donnée | ConceptFondamental | [Q42848](https://www.wikidata.org/wiki/Q42848) |
| `Attention` | Attention | ConceptFondamental | — |
| `FluxDonnees` | Flux de données | ConceptFondamental | — |
| `StockDonnees` | Stock de données | ConceptFondamental | — |
| `DesignInterface` | Design d'interface | ConceptFondamental | [Q135707](https://www.wikidata.org/wiki/Q135707) |
| `VisualisationDonnees` | Visualisation de données | ConceptFondamental | [Q6504956](https://www.wikidata.org/wiki/Q6504956) |
| `ArchitectureConsommation` | Architecture de consommation de données | ArchitectureInterface | — |
| `ArchitectureConstruction` | Architecture de construction de données | ArchitectureInterface | — |
| `TemporaliteContinue` | Temporalité continue | DimensionTemporelle | [Q3517747](https://www.wikidata.org/wiki/Q3517747) |
| `TemporaliteDiscrete` | Temporalité discrète | DimensionTemporelle | [Q3517747](https://www.wikidata.org/wiki/Q3517747) |
| `ScrollInfini` | Scroll infini | MecanismeInteraction | [Q109316840](https://www.wikidata.org/wiki/Q109316840) |
| `PipelineITO` | Pipeline Input-Traitement-Output | MecanismeInteraction | — |
| `AlgorithmeFlux` | Algorithme de flux | MecanismeInteraction | [Q136936092](https://www.wikidata.org/wiki/Q136936092) |
| `Categories` | Catégories | MecanismeInteraction | — |
| `ConsommateurDonnees` | Consommateur de données | RoleUtilisateur | — |
| `ConstructeurDonnees` | Constructeur de données | RoleUtilisateur | — |
| `ReseauxSociaux` | Réseaux sociaux | ExempleInterface | — |
| `PresseEnLigne` | Presse en ligne | ExempleInterface | — |
| `ChatGPT` | ChatGPT | ExempleInterface | — |
| `ParisSportifs` | Sites de paris sportifs | ExempleInterface | — |
| ... | *7 more entities* | | |

---

## Valid predicates

`consomme`, `determine`, `enabledBy`, `estTransformeEn`, `estUnType`, `fondement`, `illustre`, `induit`, `installeComme`, `opereSur`, `opposeDe`, `preserve`, `sousJacente`, `utilise`

---

## Extension: logit-level structured decoding

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
