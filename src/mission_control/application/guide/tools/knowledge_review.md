---
id: knowledge_review
title: knowledge_review: review a Knowledge Services use decision
summary: Record an operator's approve, hold or reject of one exact use decision that an assessment of a run cites.
---
Record an operator's review of one Knowledge Services use decision that an assessment of a run cites: approve, hold or reject.

Use it for knowledge that needs a reviewer's decision; Human Tasks are answered with mission_human_task_resolve instead. You need the knowledge.review permission and must not be the one who launched or revised the run, its producer or an evaluator.

`request` (the operator's review of one exact use decision, the same body on HTTP, MCP and the CLI):

- `decision` is the exact reference of the use decision (`kind` "use_decision", with its id, version, digest, tenant and binding).
- `outcome` is approve, hold or reject.
- `bound_effect_digest` and the optional `qualifiers_digest` are the digests that decision carries.
- `rationale` is your reason.

Returns `run_id`, `decision`, `reviewer`, `outcome` and the recorded `review`. Sending the same review twice records it once. See the result with mission_run_outputs.
