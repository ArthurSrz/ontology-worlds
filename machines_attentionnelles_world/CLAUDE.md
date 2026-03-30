# Structured Decoding — Machines attentionnelles
## Ontology-Enforced Claude Code Environment

---

## Context

This project implements **Structured Decoding** to constrain
an LLM to only generate responses grounded in a **closed ontology** —
here: **Machines attentionnelles**.

> Ontologie des machines attentionnelles à la puissance 2 — d'après l'article d'Arthur Sarazin sur les traces numériques, les fenêtres d'attention et la critique de l'épistémologie des données des réseaux sociaux (réf. Yves Citton, Pour une écologie de l'attention).

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

**For any factual question or assertion about the Machines attentionnelles ontology domain,
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
- **After EVERY ontology-grounded answer**, log the entities you discussed:
  ```bash
  python3 log_entities.py EntityId1 EntityId2 ...
  ```
  Use the exact entity IDs from the ontology table above.
  This writes to `validation_log.jsonl` and refreshes `.live_map`.
- **Then show the updated map**:
  ```bash
  cat .live_map
  ```
  ALWAYS do both steps — never skip. This is how exploration progress is tracked.


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
| `ConceptAttentionnel` | Concept attentionnel | _Class | — |
| `MecanismeAttentionnel` | Mécanisme attentionnel | _Class | — |
| `SourceDeDonnees` | Source de données | _Class | — |
| `ActeurTheorique` | Acteur théorique | _Class | — |
| `ProblemeEpistemologique` | Problème épistémologique | _Class | — |
| `MachineAttentionnelle` | Machine attentionnelle à la puissance 2 | MecanismeAttentionnel | — |
| `FiltreIndividuel` | Filtre attentionnel individuel | MecanismeAttentionnel | — |
| `FiltreReseau` | Filtre attentionnel du réseau | MecanismeAttentionnel | — |
| `BoucleDeRetroaction` | Boucle de rétroaction | MecanismeAttentionnel | [Q213208](https://www.wikidata.org/wiki/Q213208) |
| `AlgorithmeRecommandation` | Algorithme de recommandation | MecanismeAttentionnel | — |
| `FenetreAttention` | Fenêtre d'attention | ConceptAttentionnel | — |
| `EconomieAttention` | Économie de l'attention | ConceptAttentionnel | [Q2579979](https://www.wikidata.org/wiki/Q2579979) |
| `CaptationAttention` | Captation de l'attention | ConceptAttentionnel | — |
| `SusceptibiliteAttentionnelle` | Susceptibilité attentionnelle | ConceptAttentionnel | — |
| `TracesNumeriques` | Traces numériques | SourceDeDonnees | [Q1474447](https://www.wikidata.org/wiki/Q1474447) |
| `MetadonneesYoutube` | Métadonnées YouTube | SourceDeDonnees | [Q180160](https://www.wikidata.org/wiki/Q180160) |
| `PostsLinkedin` | Posts LinkedIn | SourceDeDonnees | — |
| `ArticlesDePresse` | Articles de presse | SourceDeDonnees | — |
| `ReseauxSociaux` | Réseaux sociaux | SourceDeDonnees | [Q2003370](https://www.wikidata.org/wiki/Q2003370) |
| `BigData` | Big data | SourceDeDonnees | [Q858810](https://www.wikidata.org/wiki/Q858810) |
| `YvesCitton` | Yves Citton | ActeurTheorique | [Q3573306](https://www.wikidata.org/wiki/Q3573306) |
| `SethStephensDavidowitz` | Seth Stephens-Davidowitz | ActeurTheorique | [Q29643056](https://www.wikidata.org/wiki/Q29643056) |
| `StatutEpistemologique` | Statut épistémologique des données | ProblemeEpistemologique | — |
| `BesoinVsAttention` | Besoin vs susceptibilité attentionnelle | ProblemeEpistemologique | — |
| `ContexteDeProduction` | Contexte de production des données | ProblemeEpistemologique | — |

---

## Valid predicates

`claims`, `critiques`, `feedsInto`, `hasPart`, `influences`, `instanceOf`, `partOf`, `produces`, `proposes`, `revealNot`, `reveals`, `studiedBy`, `subClassOf`

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
