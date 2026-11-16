---
id: mission_command_send
title: mission_command_send: send one Command to a run
summary: Pause, resume, cancel, satisfy a wait, or give a run's agents an instruction or more context.
---
Send one Command to a run: pause, resume, cancel, satisfy a wait, or give its agents an instruction or more context.

Call mission_run_inspect first: `expected_version` is its `version` and `expected_generation` its `execution_generation`; a stale value is refused with the current ones. To act because of an inbox notification, use coordinator_inbox_command.

`request` fields, all required:

- `request_id`: a new UUID; repeating it returns the first receipt.
- `expected_version`, `expected_generation`: from the inspection.
- `target`: `{"kind": "run", "id": the same run_id}`.
- `kind` and `payload`: below.
- `reason`: 1 to 4096 characters.

`payload` for each `kind`:

- `cancel`: `{"urgency": "normal"}` (default, stops at the next safe boundary) or `{"urgency": "immediate"}` (first fences the run against any further effect).
- `queue_instruction`: `{"content", "boundary": "next_turn" (default) or "next_iteration", optional "deadline" and "node_key"}`; read once at that boundary.
- `add_context`: the same fields plus `"expand"`: `"auto"` (default), `"inline"`, `"reference"` or `"materialize"`; added to the next Context Packet.
- `interrupt_and_inject`: `{"content", optional "node_key"}`; delivered now.
- `request_continuation`: `{optional "activation_id"}`; seals the agent session at the next turn boundary and transfers its work (default: the most recently active one).
- `pause`: `{"decision": {"decision_id", "scope" (a list of "run", "workflow" or "stage:<stage id>"), "reason", "authority_ref"}, "runnable_work_remains": true or false}`.
- `resume`: `{"decision": {"decision_id", "pause_decision_id", "reason", "authority_ref"}}`.
- `satisfy_wait`: `{"condition_id", "verification_evidence_ref"}`.

`"content"` is `{"text": "..."}` (inline, at most 8 KiB) or `{"artifact_ref", "content_digest": "sha256:<64 hex>"}`.

Returns the receipt: `admission` (status accepted, rejected or stale) and `delivery` (the Command's receipts so far). Follow its delivery with mission_run_inspect.
