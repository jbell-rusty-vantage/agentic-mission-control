---
id: mission_approval_resolve
title: mission_approval_resolve: answer an approval-origin Human Task
summary: Answer a Human Task an agent's own request raised, when the answer is more than approve or deny.
---
Answer a Human Task raised by an agent's own request: a tool permission, a question, a form or a Governed Effect.

Use it when the answer is more than approve or deny (mission_human_task_resolve does those); it does not serve Human Gate tasks (`origin` workflow_gate). Read the task first (mission_human_task_get).

`request` (the resolution body for approval-origin tasks, the same on HTTP, MCP and the socket):

- `expected_task_version` is the task's `version`, `reviewed_digest` its `packet_digest`, and `request_id` an id you choose.
- `decision` is one of the task's `permitted_decisions`: approve, deny, approve_edited (with `edited_arguments`, which must differ from the pending ones) or cancel. `cancel` is distinct from `deny`.
- A question takes approve with `answer` or `selected` (offered options); a form takes approve with `elicitation_content`, or deny to decline.

Only one of the task's `reviewers` can answer: that actor id, or a principal holding `reviewer:<name>`. A refusal `not_reviewer` names the required reviewers and what the principal reviews as.

Returns `status` (accepted or duplicate) and the updated `task`.
