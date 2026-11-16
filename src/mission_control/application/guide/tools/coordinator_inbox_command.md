---
id: coordinator_inbox_command
title: coordinator_inbox_command: a Command caused by a notification
summary: Send one Command to a run because of an inbox notification, recorded as caused by it and bounded.
---
Send one Command to a run because of an inbox notification.

Use it instead of mission_command_send when a delivered notification is the reason: the Command is recorded as caused by it and is bounded. It is refused when the chain of reactions passes the inbox's recursion depth, or above the inbox's rate of such Commands per run (retryable later).

`subscription_id` and `notification_id` name your inbox and that notification.

`command` is the object mission_command_send takes as `request`:

- `request_id`: a new UUID.
- `expected_version` and `expected_generation`: from mission_run_inspect.
- `target`: `{"kind": "run", "id": the run to command}`.
- `kind`: pause, resume, cancel, satisfy_wait, queue_instruction, add_context, interrupt_and_inject or request_continuation.
- `payload`: per kind, as listed under `tool:mission_command_send`.
- `reason`.

Returns the same receipt as mission_command_send (`admission`, `delivery`).
