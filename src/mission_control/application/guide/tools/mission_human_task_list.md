---
id: mission_human_task_list
title: mission_human_task_list: list Human Tasks
summary: The decisions runs are waiting on a reviewer to make.
---
List Human Tasks: the decisions runs are waiting on a reviewer to make.

Use it to find what blocks a run, for example after a review_required notification. `run_id` limits the list to one run; `lifecycle` is open, resolved, expired or cancelled (omit it for all).

Returns `human_tasks`, each with `human_task_id`, `origin`, `kind`, `lifecycle`, `version`, `prompt`, `permitted_decisions` and `packet_digest`. Read one with mission_human_task_get, then answer it with mission_human_task_resolve.
