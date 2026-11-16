---
id: mission_human_task_resolve
title: mission_human_task_resolve: answer a Human Task
summary: Answer a Human Task with approve, deny or request_changes, as one of its reviewers.
---
Answer a Human Task with approve, deny or request_changes, as one of its reviewers.

Use it for Human Gate tasks and for a plain approve or deny of any other task; mission_approval_resolve covers edited arguments, offered options, forms and cancel. Read the task first (mission_human_task_get).

`request` (the one mutation body, `POST /human-tasks/{id}/resolutions`):

- `expected_task_version` is the task's `version`.
- `reviewed_packet_digest` is its `packet_digest`.
- `decision` is one of its `permitted_decisions`.
- `request_id` is an id you choose (repeating the same request returns the same result).
- request_changes needs a `comment` or `feedback_artifact_refs`; on a question task the `comment` is the answer.

Who may answer: only one of the task's `reviewers`, that is the principal whose actor id is listed, or a principal holding the permission `reviewer:<name>` for a listed name. mission_whoami returns `reviews_as`: every reviewer name your principal satisfies. Anyone else is refused `not_reviewer`; the refusal's `required_reviewers` and `principal_reviews_as` say who was required and what you hold. Resolve only on the reviewer's decision.

Returns `status` (accepted or duplicate) and the updated `task`.
