---
description: List Wikidata gaps detected in this session and their debate questions
---

# /gaps — surface candidate Wikidata edits

Read the cached JIT domain at `${ONTOLOGY_WORLDS_CACHE:-/tmp/ontology-worlds}/<session_id>.json` and print every detected gap.

A pair is flagged as a gap only when BOTH conditions hold:
1. **No class-cone path** — walking up the P31/P279 hierarchy from both
   subject and object (depth ≤ 3), no pair of ancestors is connected by
   a domain-defining property (P2283, P527, P361, P1535, P366, P1542) in
   either direction. This filters out relationships Wikidata already
   models at the class level — e.g. `driving uses land_vehicle ← car`.
2. **Neighborhood-majority sibling evidence** — most P31/P279 siblings
   of the subject have an analogous edge to something in the object's
   class. This is what suggests *which* property to propose.

For each gap, render:

- **`<seed_a_label>` — *<suggested_property_label>* (<P-id>) → `<seed_b_label>`**
- *Confidence:* `siblings_with_edge / siblings_checked` (e.g. 7/10 = 0.70).
- *Question:* the framed debate text.
- *Evidence siblings:* the Q-IDs whose presence motivates the gap.
- *To propose:* the exact `[PROPOSE Q… P… Q…: "…"]` tag to emit in the chat to stage this as a Wikidata contribution.

If no gaps were detected, that's often the **correct** outcome: Wikidata
already models the relationships at the class level. Say so explicitly.
If no cache exists, prompt the user to send a question first.

Do not run new SPARQL queries — gaps are only ever computed by the UserPromptSubmit hook.
