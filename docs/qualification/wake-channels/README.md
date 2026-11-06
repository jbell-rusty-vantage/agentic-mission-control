---
type: Verification Reference
title: Wake channel qualification transcript (MO-43)
description: A Claude Code coordinator session launches a deterministic offline GoalDirected run through the operator API on local PostgreSQL and a local Temporal server, runs missionctl wait as a background task, and is woken by the run's real run.completed; the same inbox then answers the authenticated operator MCP. Recorded 2026-10-13, redacted.
tags: [mission-control, qualification, subscriptions, coordinator-inbox, wake-channels]
outcome: woken
evidence: local_drill
---

# Wake channel qualification transcript (MO-43, SPEC-04 §6 recipe 1)

**Claim.** A Claude Code coordinator using recipe 1 ("launch then wait") is woken by a real
`run.completed` without polling in its own context: it starts `missionctl wait` as a background
Bash task, continues other work, and the task's completion notification is the wake-up.

**Who ran it.** The MO-43 implementer, itself a Claude Code session (Opus 5.5), on the owner's
Windows 11 machine, 2026-10-13. No provider was called and nothing was paid.

## Stack

`scripts/offline_operator_stack.py` (the signed scoped stack of
`tests/fixtures/scoped_api_stack.py`): a fresh common-component database on the disposable
PostgreSQL 17 cluster (`127.0.0.1:55433`, restricted runtime and family-writer logins, forced RLS),
a local Temporal dev server (`127.0.0.1:17233`, SQLite), the production workers with
deterministic DeepAgents cognition, and the configured API (`bootstrap.api.create_application`,
operator MCP mounted) served by uvicorn on `127.0.0.1:63692`. It admitted one GoalDirected run
and wrote its launch body; the coordinator held a signed bearer token in a file (never printed;
deleted after the drill). Branch `mo/mo-43-wake-channels`.

## Transcript (redacted: the bearer token is omitted; ids are local and synthetic)

Environment of every command: `MISSION_CONTROL_URL=http://127.0.0.1:63692`,
`MISSION_CONTROL_APPLICATION_ID=biotech`, `MISSION_CONTROL_TOKEN=<from file>`.

**1. Inspect the admitted run, then launch it through the operator API.**

```text
## 2026-10-13T04:02:31Z missionctl run inspect 34dc8137-2f1f-5443-86c1-d459f69727b0 --json
{"run_id": "34dc8137-2f1f-5443-86c1-d459f69727b0", "lifecycle": "pending", "phase": "pending", "execution_outcome": null, "version": 1}
## 2026-10-13T04:02:41Z missionctl run start 34dc8137-2f1f-5443-86c1-d459f69727b0 --request-file drill/launch.json --json
{"run_id": "34dc8137-2f1f-5443-86c1-d459f69727b0", "family": "GoalDirected",
 "workflow_id": "mc/0192a4f0-0000-7000-8000-00000000b10e/biotech/run/34dc8137-2f1f-5443-86c1-d459f69727b0",
 "temporal_run_id": "01a1336d-587b-7b00-98a7-4c3d86a6d67e", "accepted_run_version": 1, "application_id": "biotech",
 "coordinator_inbox": {"status": "subscribed", "subscription_id": "01a1336d-50b0-7b9f-b13c-c30ee646beb9", "reason": null}}
exit=0
```

The launch subscribed the launcher's coordinator inbox before starting the run.

**2. Start the wait as a background Bash task and continue working.** The session issued the
command with `run_in_background: true` and went on with other work (it ran `ty` and the full
`mypy` gate meanwhile); it did not poll the task.

```text
## 2026-10-13T04:02:54Z started: missionctl wait --run 34dc8137-2f1f-5443-86c1-d459f69727b0 --kinds terminal_result,blocked,review_required --wait 900
```

**3. The wake.** At 04:04:41Z the harness delivered the task-completion notification
("Background command ... completed (exit code 0)") into the session, which then read the task
output:

```text
{"inbox": "01a1336d-50b0-7b9f-b13c-c30ee646beb9", "created": false}
{"schema_version": "mc.coordinator_notification.v1", "notification_id": "e79bfb07-eabc-5d59-a1c6-55e720762795",
 "subscription_id": "01a1336d-50b0-7b9f-b13c-c30ee646beb9", "inbox_seq": 4, "state": "pending",
 "kind": "terminal_result", "actionable": true, "mission_id": "01a1336c-ff28-74e8-9d54-bab67f90efc0",
 "run_id": "01a1336c-ff28-715d-aedd-e7f59ea777de", "seq_from": 61, "seq_to": 61, "event_count": 1,
 "events": [{"event_id": "01a1336f-1588-77f7-afd7-a0ce3cc847c7", "seq": 61, "event_type": "run.completed",
             "public_event_id": "a33f9ede-3ab4-551b-ade6-223d57bafb0c"}],
 "counts": {"run.completed": 1}, "causation_refs": ["goal:terminalization:sha256:ae0d94a4…"],
 "depth": 0, "facts": {"terminal_outcome": "completed"},
 "opened_at": "2026-10-13T04:04:40.017272Z", "sealed_at": "2026-10-13T04:04:41.141095Z", "acknowledged_at": null}
## 2026-10-13T04:04:41Z missionctl wait exited 0
```

The notification's `run_id` is the journal's row id of the run; the inbox list below maps it to
the public run id the coordinator launched.

**4. Inspect on wake, acknowledge, and confirm nothing terminal is pending.**

```text
## 2026-10-13T04:04:59Z (woken) missionctl run inspect 34dc8137-2f1f-5443-86c1-d459f69727b0 --json
{"run_id": "34dc8137-2f1f-5443-86c1-d459f69727b0", "lifecycle": "completed", "phase": "terminal", "execution_outcome": "completed", "version": 26}
## 2026-10-13T04:05:03Z missionctl inbox list --run 34dc8137-2f1f-5443-86c1-d459f69727b0
[{"subscription_id": "01a1336d-50b0-7b9f-b13c-c30ee646beb9", "target": {"kind": "run", "mission_id": "01a1336c-ff28-74e8-9d54-bab67f90efc0",
  "run_id": "01a1336c-ff28-715d-aedd-e7f59ea777de"}, "state": "active", "acked_inbox_seq": 0, "high_inbox_seq": 4, "delivery": "poll"}]
## 2026-10-13T04:05:05Z missionctl inbox ack 01a1336d-50b0-7b9f-b13c-c30ee646beb9 --id e79bfb07-eabc-5d59-a1c6-55e720762795
{"application_id": "biotech", "acknowledged": ["e79bfb07-eabc-5d59-a1c6-55e720762795"], "already": [], "unknown": [], "acked_inbox_seq": 0}
exit=0
## 2026-10-13T04:05:08Z missionctl wait --run 34dc8137-2f1f-5443-86c1-d459f69727b0 --kinds terminal_result --wait 3
{"inbox": "01a1336d-50b0-7b9f-b13c-c30ee646beb9", "created": false}
{"error": "wait_timeout", "inbox": "01a1336d-50b0-7b9f-b13c-c30ee646beb9"}
exit=6
```

The acknowledged cursor stays at 0 because notifications 1 to 3 (progress and accepted output)
are still pending; acknowledgement is by id and the cursor only moves over a contiguous prefix.

**5. The same inbox over the authenticated operator MCP (W2).**

```text
## 2026-10-13T04:05:35Z POST /v1/applications/biotech/mcp/ tools/list without a bearer -> 401 {"detail":{"code":"bearer_token_required"}}
## 2026-10-13T04:05:35Z tools/list (bearer) -> 23 tools
["coordinator_inbox_ack", "coordinator_inbox_command", "coordinator_inbox_list", "coordinator_inbox_poll",
 "coordinator_inbox_subscribe", "coordinator_inbox_wait", "mission_approval_resolve", "mission_chain_inspect",
 "mission_command_send", "mission_governed_execute", "mission_governed_prepare", "mission_governed_status",
 "mission_human_task_get", "mission_human_task_list", "mission_human_task_resolve", "mission_manifest_compile",
 "mission_manifest_submit", "mission_run_fork", "mission_run_inspect", "mission_run_list", "mission_run_search",
 "mission_run_start", "mission_run_transcript"]
## 2026-10-13T04:05:36Z tools/call coordinator_inbox_wait (all kinds, 5 s)
{"ok": true, "acked_inbox_seq": 0, "high_inbox_seq": 4, "notifications": [
 {"inbox_seq": 1, "kind": "progress", "actionable": false, "counts": {"session.ended": 1, "session.started": 1, "workflow_run.start": 1, "workflow_run.apply_authority_batch": 1, "workflow_run.family_admission_committed": 2}},
 {"inbox_seq": 2, "kind": "progress", "actionable": false, "counts": {"session.ended": 3, "session.started": 3, "workflow_run.apply_authority_batch": 3, "workflow_run.family_admission_committed": 2, "workflow_run.record_obligation_evidence": 1}},
 {"inbox_seq": 3, "kind": "accepted_output", "actionable": false, "counts": {"workflow_run.record_output_evidence": 1}}]}
```

`mission_subscribe` is not offered; `mission_run_start` and `mission_command_send` (intervene)
are.

## Limits

- Local disposable proof only: one GoalDirected run with deterministic cognition, a local Temporal
  dev server rather than the compose Temporal, and no lane provider. It qualifies the wake channel,
  not any lane; S0 repeats recipe 1 on `claude_agent_sdk`, `codex` and `cursor_local` (MO-72).
- The automated equivalent (separate `missionctl wait` process, same assertions) is
  `tests/acceptance/mission_control/test_wake_channels.py`.
