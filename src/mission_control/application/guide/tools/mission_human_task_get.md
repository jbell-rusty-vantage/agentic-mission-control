---
id: mission_human_task_get
title: mission_human_task_get: read one Human Task
summary: What is asked, by which run, who may answer and what an answer must cite.
---
Read one Human Task: what is asked, by which run, and what an answer must cite.

Use it before answering. `human_task_id` comes from mission_human_task_list.

Returns the task: `origin` (workflow_gate for a Human Gate; otherwise provider_permission, provider_question, mcp_elicitation or governed_effect), `prompt`, `permitted_decisions`, `reviewers`, `deadline_at`, `version`, `packet_digest` and what is under review (the review packet, the pending tool call, the question or the form).

Next: mission_human_task_resolve, or mission_approval_resolve to approve with edited arguments, choose among offered options, fill a form or cancel.
