---
type: Concept
category: surfaces
title: Wake channels and the operator MCP
description: "How an orchestrating agent (Claude Code, Codex, Cursor or a Mission Control run) is woken by its coordinator inbox - the inbox wait behind missionctl wait, the HTTP long-poll and the MCP coordinator_inbox_wait, the launcher auto-subscribe, the default-on relay, summary webhooks and the authenticated operator MCP mounted by the configured API (MO-43, ADR-0049)."
tags: [mission-control, subscriptions, coordinator-inbox, cli, mcp, implementation]
aliases: [missionctl wait, inbox long-poll, operator MCP, wake channel]
questions:
  - How is an orchestrating agent woken when its run needs it?
  - How do I wait on a run from Claude Code or Codex?
  - Which tools does the operator MCP serve?
updated: 2026-11-01
---

# Wake channels and the operator MCP

Mission Control cannot interrupt an idle agent, so it offers channels that use the
orchestrator's own primitives ([SPEC-04 §6](../specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md),
[ADR-0049](../adr/0049-deprecate-mission-subscribe-push-in-favour-of-inbox-wait-channels.md)).
Every channel is a cursor over the one durable coordinator inbox of
[events and commands](events-and-commands.md) (ADR-0040): notifications are classified, batched
and bounded there, and acknowledgement is always explicit.

## The inbox wait

`CoordinatorInboxService.wait` (`application/subscriptions/coordinator_service.py`) is a
server-side long-poll: each round materializes committed journal events into notifications, so no
relay is needed, and it returns the first non-empty pending page, optionally narrowed to
notification kinds (`terminal_result`, `blocked`, `review_required`, `failed`, ...), or an empty
page at the deadline (at most 300 s). It never acknowledges. `inboxes` lists the caller's open
inboxes over a mission or run; `ensure` reuses one or subscribes.

| Channel | Surface |
| --- | --- |
| W1 HTTP | `GET /v1/applications/{app}/coordinator-inboxes/{id}/notifications?wait=<s>&kinds=a,b`; `GET .../coordinator-inboxes?target=run&target_id=` lists the caller's inboxes |
| W1 CLI | `missionctl wait --run RUN \| --mission M \| --inbox ID [--kinds a,b] [--follow] [--ack] [--wait S]` (`interfaces/cli/wait.py`): one JSON line per notification on stdout, the inbox used on stderr; exit 0, or 6 at the deadline (default 3600 s). `missionctl inbox list` and `inbox ack ID --id N \| --through SEQ` |
| W2 MCP | `coordinator_inbox_wait` (and `coordinator_inbox_list`) on the operator MCP; the result is model-visible |
| W4 webhook | inbox webhook delivery with `webhook_payload: summary` adds `render_summary` text (ids, counts, whitelisted facts) to the signed body; a 2xx is a transport observation, never acknowledgment (WI-19) |
| W5 prompt | unchanged: `prompt_mode` queues an instruction into a coordinator that is itself a run |

`missionctl wait --run` reuses the caller's open inbox over the run, or registers one from journal
sequence 0, so a wait that starts after the run ended still wakes. A one-shot wait prints an
unacknowledged notification again; `--follow` keeps a local cursor; `--ack` acknowledges what it
printed. From Claude Code, run it as a background task (the exit notification wakes the session)
or `--follow` under Monitor. The recorded wake is
[docs/qualification/wake-channels](../qualification/wake-channels/README.md).

Since WI-19 every page also carries a per-delivery `delivery_nonce`, an HTTP or MCP answer
records a transport observation, and the host attests its idle wake and the model-visible payload
separately (echoing the nonce) (`missionctl inbox observe`, `coordinator_inbox_observe`): the six delivery stages,
bounded content and the C14 host procedure are in [coordinator attention](coordinator-attention.md).

## Launcher auto-subscribe and the relay

`application/subscriptions/launcher.py` ensures, **before** the launch, an inbox over the run for
the launching actor with the default coordinator profile, on `POST /runs/{id}/launch`,
`POST /missions:start`, `POST /missions/{id}/runs` and MCP `mission_run_start`. `notify=none`
(query parameter, `--notify none`, MCP `notify`) opts out. The receipt's `coordinator_inbox`
reports `subscribed`, `existing`, `off` or `unavailable` (no inbox service, a non-uuid run id, or
a launcher without `workflow_run.read`); the hook never decides the launch. The subscription relay
now runs in the API by default (`MISSION_CONTROL_SUBSCRIPTION_RELAY=0` turns it off); loopback
webhook targets still need `WEBHOOK_ALLOW_LOOPBACK=true` (there is no `local_dev` installation
kind yet).

## The operator MCP

`bootstrap/api.py` mounts `interfaces/mcp/operator_server.py` at
`/v1/applications/{application_id}/mcp/` (Streamable HTTP, stateless, JSON responses).
`BearerPrincipalGate` verifies each HTTP request with the same bearer verifier and application
authorization as the HTTP routes before FastMCP reads it; tools resolve that principal, whose
canonical request scope selects the API's own tenant services. It registers the scoped tools the
coordinator server shares (`register_scoped_tools`): the inbox tools including the wait,
`mission_run_transcript|search|list`, `mission_manifest_compile|submit`, `mission_run_start`,
`mission_command_send` (intervene), `mission_run_inspect`, `mission_run_fork`,
`mission_chain_inspect`, `mission_human_task_*`, the governed tools, the cognition-point tools
(`mission_run_points`, `mission_run_state_as_of`, `mission_run_replay`...), the selection tools
(`mission_search`, `selection_check`), the output reads (`mission_run_outputs`, `mission_transfer_plan`)
and `knowledge_review` (`operator_server.py:40-55,145-185`). It has no catalog facade
and no `mission_subscribe`: that session push is deprecated, kept only on the development server
(`python -m mission_control.interfaces.mcp`, compile-only manifests). `signal_emit` is not on
this surface: it is served on the Signal Ingress (`/v1/ingress/{app}/mcp`, MO-41) with the run
credential, because the operator's bearer never enters an environment
([Signal Ingress](signal-ingress.md)).

Built / specified / goal: the wait channels, launcher auto-subscribe, relay and operator MCP are implemented and
integrated locally (acceptance test below); the C14 real coordinator-host wake is unrun
([coordinator attention](coordinator-attention.md)).

## Citations

- History: [SPEC-04 §6](../specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md), [MO-43](../specs/archive/materialization-observation-2026-10/issues/MO-43-wake-channels-missionctl-wait-inbox-long-poll-mcp-inbox-wait-auto-subscribe.md); ADRs [0032](../adr/0032-interventions-real-queue-inject-cancel-fork-and-subscriptions.md), [0040](../adr/0040-native-frames-normalized-lifecycle-lineage-graph-bounded-coordinator-subscriptions.md), [0049](../adr/0049-deprecate-mission-subscribe-push-in-favour-of-inbox-wait-channels.md).
- Code: [inbox service](../../src/mission_control/application/subscriptions/coordinator_service.py), [launcher hook](../../src/mission_control/application/subscriptions/launcher.py), [inbox routes](../../src/mission_control/interfaces/http/coordinator_inbox.py), [missionctl wait](../../src/mission_control/interfaces/cli/wait.py), [MCP inbox tools](../../src/mission_control/interfaces/mcp/subscriptions.py), [operator MCP](../../src/mission_control/interfaces/mcp/operator_server.py), [API mount](../../src/mission_control/bootstrap/api.py), [relay switch](../../src/mission_control/bootstrap/subscriptions.py).
- Tests: [unit](../../tests/unit/subscriptions/test_mo43_wake_channels.py), [PostgreSQL](../../tests/integration/postgres/test_mo43_wake_channels_postgres.py), [local PostgreSQL and Temporal acceptance](../../tests/acceptance/mission_control/test_wake_channels.py).
