---
description: Show the JIT Wikidata domain built for the most recent prompt
---

# /world — inspect the current JIT domain

Read the cached JIT domain for this session and render it as a structured report:

1. Locate the cache file at `${ONTOLOGY_WORLDS_CACHE:-/tmp/ontology-worlds}/<session_id>.json`. You can find the session_id by inspecting the env or recent transcript metadata.
2. Read the JSON. It contains `domain` (with `seeds`, `nodes`, `edges`) and `gaps`.
3. Output a Markdown report with:
   - **Prompt** — the original user prompt.
   - **Seed entities** — `Q-ID label ("surface form") — description`.
   - **Domain size** — counts of nodes and edges.
   - **Top in-domain entities** — first 20 nodes by appearance order.
   - **Sample domain edges** — first 15 edges as `subject — predicate → object`.
   - **Detected gaps** — count, with one-line summary of each.

If no cache file exists yet, tell the user: "No JIT domain has been built yet — send a prompt first."

Do not run SPARQL queries here; this is a read-only inspection command.
