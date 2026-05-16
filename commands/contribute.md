---
description: Review staged Wikidata contributions and render them as QuickStatements
---

# /contribute — turn staged proposals into a Wikidata edit batch

Read `contributions/<session_id>.jsonl` from the plugin root. Each line is a JSON Contribution record with `subject_qid`, `property_pid`, `object_qid`, `reasoning`, `source_prompt`, `gap_origin`, `status`.

Output:

1. **Summary table** — one row per staged contribution: subject (label + Q-ID) | property | object | reasoning excerpt | status.

2. **QuickStatements block** — fenced code block, one line per contribution, using v1 syntax:
   ```
   Q190984|P2283|Q1420|S887|"you drive a car"
   ```
   Tell the user they can paste this at <https://quickstatements.toolforge.org/> to publish.

3. **Provenance** — for each contribution with a non-empty `gap_origin`, quote the gap question that triggered it. This makes the contribution auditable.

4. **Next step prompt** — ask whether the user wants to:
   - Mark contributions as `submitted` (update the JSONL in place).
   - Edit reasoning / drop a contribution before publishing.
   - Skip — leave them staged.

If `contributions/<session_id>.jsonl` does not exist or is empty, say so: "No Wikidata contributions staged yet in this session."

Do not POST to Wikidata directly — direct API write (`wbeditentity` + OAuth) is deliberately out of scope for this iteration.
