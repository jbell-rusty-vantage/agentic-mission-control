---
id: mission_governed_prepare
title: mission_governed_prepare: prepare a Governed Effect
summary: Record the intent to run one Mission Control-owned effect tool for a run; nothing is executed yet.
---
Prepare a Governed Effect: record the intent to run one Mission Control-owned effect tool for a run. Nothing is executed yet.

It is the first of three steps: prepare, review, then mission_governed_execute.

- `tool_name` names the governed tool; an unknown name is refused.
- `arguments` is that tool's own JSON object, so its fields depend on the tool: for example repo_pr, where it is offered, takes `{"repository": "...", "branch": "mc/<run>/<unit>", "base": "main", "title": "...", "body": "..."}`.
- `run_id`, `harness_execution_id`, `generation` and `lane_profile` name the Harness Execution that asks; they are in the `lane` section of mission_run_inspect.
- `lane_profile` is one of the lane profiles the schema below lists.

Returns `status`, `intent_id`, `tool_name` and `input_digest`. With status pending_approval it also returns the `human_task` (id, version, review_digest) a reviewer must resolve first (mission_approval_resolve); with status ready, execute at once. Preparing the same call again returns the same intent.
