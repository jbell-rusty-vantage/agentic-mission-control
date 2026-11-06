---
type: Decision Record
title: "Deprecate mission_subscribe push in favour of inbox wait channels"
description: "Accepted for the materialization-observation packet (SPEC-04 §6, MO-43, gap G5): every way of waking an orchestrating agent is a cursor over the one durable coordinator inbox (missionctl wait, the HTTP long-poll, the authenticated MCP coordinator_inbox_wait); a launch subscribes its launcher; the relay runs by default; the MCP session push mission_subscribe is deprecated."
tags: [mission-control, adr, accepted, subscriptions, coordinator-inbox, mcp, cli]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md (§6 wake channels); GAP-REPORT G5; research/codebase-observation.md §3 and §7; ADR-0032; ADR-0040; application/subscriptions/; interfaces/cli/wait.py; interfaces/mcp/operator_server.py
---

# Deprecate mission_subscribe push in favour of inbox wait channels

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. 

Nothing woke an idle orchestrating agent. The MCP push `mission_subscribe` registers an
`mcp_session` Subscription whose events arrive as `notifications/mission/event`, but both MCP servers
are stateless Streamable HTTP, the API relay ran without a notifier, and a custom notification is never
model input in Claude Code even when it is delivered. The coordinator inbox (ADR-0040, MP-15) was durable
and bounded but had no wait, no CLI verb, was reachable over MCP only on the unauthenticated development
server, and no launch subscribed anyone to it although ADR-0032 promised that.

We make the coordinator inbox the single durable source of every wake channel and give each
orchestrator a primitive it already has. `CoordinatorInboxService.wait` is a server-side long-poll over
the same pending page (each round materializes committed journal events, so no relay is needed for it),
optionally narrowed to notification kinds; it returns as soon as a matching notification is pending, or
an empty page at the deadline (at most 300 s), and never acknowledges. It is exposed three ways:
`GET /coordinator-inboxes/{id}/notifications?wait=<s>&kinds=` (W1 HTTP); `missionctl wait
--run|--mission|--inbox [--kinds] [--follow] [--ack]`, which prints one JSON line per notification and
exits 0, or 6 on timeout (the general CLI's wait-timeout code), and which a Claude Code session runs as a
background task whose exit is the wake-up (W1 CLI); and `coordinator_inbox_wait` on the authenticated
operator MCP server, whose result is model-visible (W2). Every run launched through the operator API
(HTTP `runs/{id}/launch`, `missions:start`, `missions/{id}/runs`, MCP `mission_run_start`) first ensures
an inbox over the run for the launching actor with the default coordinator profile, unless the launch
says `notify=none`; because it exists before the launch, even a run that finishes at once is
materialized after its cursor. The subscription relay now runs by default in API processes
(`MISSION_CONTROL_SUBSCRIPTION_RELAY=0` turns it off), and inbox webhooks may carry an inline
reference-only summary (`payload: summary`, W4). The authenticated operator MCP is mounted by the
configured API at `/v1/applications/{application_id}/mcp/`, verifies the same bearer token as the HTTP
routes before FastMCP reads a request, and registers the inbox, transcript, manifest submit and start,
run control (intervene), chain, Human Task and governed tools over the same tenant services; the
development server keeps compile-only manifests and the deprecated push.

We deprecate `mission_subscribe` rather than compose a notifier with stateful sessions: stateful MCP
sessions would add sticky routing and session lifetime to an otherwise stateless API, and the result
would still not be model input. We rejected a client-side poll loop as the primary channel (it burns
the orchestrator's context and was the source of the owner's prior stop and claim races), and rejected
pushing into an arbitrary idle session (Mission Control cannot interrupt one; the Claude Code channel W3
stays optional until qualified, Q-O1).

## Consequences

- Acknowledgement stays explicit everywhere: a one-shot wait prints an unacknowledged notification
  again; `missionctl inbox ack` or `--ack` moves the cursor. `--follow` keeps a local cursor instead.
- A launch receipt carries `coordinator_inbox` (`subscribed | existing | off | unavailable`); an absent
  inbox service (database release < 1.2.0) or a launcher without `workflow_run.read` is reported, never
  fails the launch.
- `missionctl wait --run` reuses the caller's open inbox over the run, or registers one from journal
  sequence 0, so a wait that starts after the run ended still wakes.
- Each waiting request materializes about once per second under the inbox row lock; a LISTEN-driven
  wake-up can replace the interval later without changing any channel.
- Notification text (kinds, ids, counts, whitelisted scalar facts) is untrusted data with provenance,
  never instructions; payload bodies never leave the journal.
- The operator MCP is stateless: `notifications/coordinator/inbox` hints and `mission_subscribe` are not
  offered there. `signal_emit` is served on the Signal Ingress instead (`/v1/ingress/{app}/mcp`,
  MO-41), authenticated by the run credential, since the operator's bearer never enters an
  environment.
- There is no `local_dev` installation kind yet; loopback webhook targets still need
  `WEBHOOK_ALLOW_LOOPBACK=true`.
