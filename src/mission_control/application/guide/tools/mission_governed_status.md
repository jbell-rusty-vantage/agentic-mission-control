---
id: mission_governed_status
title: mission_governed_status: read a prepared Governed Effect
summary: Whether a prepared effect still waits for review, is ready, was executed or was refused.
---
Read the state of a prepared Governed Effect. Nothing is executed.

Use it to check whether an effect still waits for review, is ready, was executed or was refused. `intent_id` comes from mission_governed_prepare.

Returns `status` (pending_approval, ready, executing, executed, denied, cancelled, expired, fenced, stale or in_doubt), `tool_name`, `input_digest`, the `human_task` under review if there is one, and the `receipt` once executed.

Next: resolve the Human Task while pending_approval; call mission_governed_execute when ready.
