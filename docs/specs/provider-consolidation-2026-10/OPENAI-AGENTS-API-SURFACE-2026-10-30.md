---
type: Research
title: "OpenAI Agents API surface and lifecycle evidence, 2026-10-30"
description: "Official-source findings for hosted sessions, files, delegation, vaults, recovery and the limits of checkpoint parity."
tags: [mission-control, research, openai, providers]
as_of: 2026-10-30
pins: "Source adapter: openai 3.29.0 wire shapes, agents=v1; documentation fetched 2026-10-30, live account unprobed"
status: draft
---

# OpenAI Agents API surface and lifecycle evidence

This is dated research, not a contract or a qualification receipt. It feeds the
[architecture projection](OPENAI-AGENTS-API-DESIGN.md). The owner requested deep official-doc
research with a GPT-6.1 Sol subagent; that research and primary-agent source inspection produced
this register. No provider resources were created and no live model calls were made.

## Runtime and configuration

The Agents API runs a managed Codex harness at OpenAI. The Agents SDK instead runs an agent
loop inside the application. API environment choice is independent of harness location:
`none` has no filesystem/executor, `openai_hosted` supplies managed compute, and `self_hosted`
connects application-managed compute. The latter can be cloud infrastructure rather than a
laptop. Custom function handlers still need an available application service.
[Architecture](https://developers.openai.com/api/docs/guides/agents-api/architecture),
[runtime comparison](https://developers.openai.com/api/docs/guides/agents#compare-agent-runtimes).

Saved-agent settings are copied into sessions. Saved-agent updates affect new sessions.
Creation overrides replace supplied arrays/objects; existing-session updates merge only the
supported model/reasoning-effort/service-tier fields and can replace metadata. Instructions,
tools, output format and multi-agent settings require a new session. Active turns keep their
settings, including when steered. Instructions/tool configuration and input/output-schema
requests have documented 4 MiB limits; leave metadata headroom.
[Configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration).

## Sessions, input and events

Idle input starts a turn; active input steers it. Turns run asynchronously. `idle` is not
success, and root turn completion does not establish that all tools or output obligations
succeeded. Subscribe before sending work. Persist one idempotency key per logical input and
reuse the same key/session/payload after uncertain delivery; identical text in a different
logical submission needs a new key. `environment: none` requires initial input.
[Sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions).

Input returns HTTP 202, not completed work. Cancellation targets the current turn, preserves
saved history, and is not effect rollback. Endpoint-specific idempotency does not establish
universal exactly-once operations. Native schemas and beta surface are in the
[input reference](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/subresources/events/methods/create).

Streams do not replay missed events. Recovery opens a new stream and buffers, fetches session
and saved paginated items, rebuilds by item ID and applies buffered updates, ignoring changes
to already-final items. Retrieve outstanding `required_actions` from current state, not merely
historical calls. Some intermediate deltas can be permanently missing. Root and child events
must remain separately attributed.
[Events and Items](https://developers.openai.com/api/docs/guides/agents-api/sessions/events).

## Checkpoints, inspection and fork limits

The reviewed [public reference](https://developers.openai.com/api/reference/resources/beta/subresources/agents)
contains session, turn, item, child, artifact and trace retrieval, but no public session-fork,
checkpoint selection/restore, history-edit or rollback endpoint was found. This is a limitation
of the reviewed public contract, not a claim about hidden implementation.

The same reference describes suspended environments with a **private checkpoint**, plus
expired/reset events. That does not provide an application-selected restoration point.
The hosted guide describes a one-hour inactivity/keep-alive limit and replacement after expiry;
the error guide requires a new session after session failure or hosted idle timeout. These
surfaces expose different detail, so actual version behavior needs qualification.
[Hosted environments](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted),
[errors and recovery](https://developers.openai.com/api/docs/guides/agents-api/errors).

**Architectural inference:** reproduce mission dependency closure and accepted-output lineage
independently of provider state. A fresh session supplied with a captured transcript and files
is reconstructed continuation, not a native checkpoint fork. Read fidelity must disclose gaps.

## Environments, inputs and artifacts

Hosted environments accept initial files in `environment.files`, using either inline base64 or
Files API IDs with destinations under `/workspace`. The environment Files API can add files
after connection. Existing destinations, symlink traversal and invalid paths are rejected.
Templates hold configuration, not a copy of a live workspace. Setup failures prevent startup.

Outputs under `/workspace/outputs` are published as immutable artifacts on completed turns;
identify versions by turn and path. They survive environment expiry, but needed bytes should
be retained before session deletion. The Artifacts API does not upload/edit artifacts or batch
download; self-hosted files use the application's infrastructure instead.

Documented bounds at research time: creation has 50 files; inline 5 MiB/file and 10 MiB total;
Files API copies 50 MiB/file; artifacts 200 MiB/file and 500 MiB published together. These are
provider constraints to pin and verify, not permanent MC constants.
[Files and artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files).

## Tools, skills and native children

Function tools require application handlers and current action identity. Hosted shell and file
tools execute in the provider environment; function-tool approval does not intercept them.
Remote MCP and sandbox-mounted skills have their own configuration paths. Skills and plugins
must be materialized under the selected API's rules; Responses skill attachment is not evidence
of Agents API compatibility.
[Functions](https://developers.openai.com/api/docs/guides/agents-api/tools/functions),
[MCP](https://developers.openai.com/api/docs/guides/agents-api/tools/mcp),
[plugins and skills](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins).

Native delegation enables harness coordination tools. `max_concurrent_subagents` defaults to
six excluding the coordinator in the current guide. Children have separate context but share
the environment filesystem and inherit supported tools/MCP/credentials; **function tools are
not supported for subagents**. Coordination items can omit message contents. Retrieve saved
child turns/items for deeper inspection. REST inspection resources do not establish an
application-level equivalent of every harness create/message/wait/interrupt action.
[Multi-agent delegation](https://developers.openai.com/api/docs/guides/agents-api/multi-agent).

## Vaults and access

Vaults separate credentials from agent configuration. Environment-variable credentials expose
placeholders; the egress proxy substitutes secrets for allowed HTTPS destinations on ports
443/8443. This does not support arbitrary sandbox-local signing with the real secret. Network
policy must also allow the destination. Rotation of environment-variable credentials requires
a new session for the replacement. Credential deletion is not upstream token revocation or
termination of active sessions.
[Vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults).

The hosted guide describes an enabled network default; the reference says omission can be
API-version-dependent. Explicit network policy avoids reliance on this discrepancy. Data
residency and retention are separate admission concerns: the overview documents US-only
residency and no ZDR for Agents API, including when compute is self-hosted.
[Overview](https://developers.openai.com/api/docs/guides/agents-api/overview).

## Webhooks and automations

Webhooks cover session transitions, not every individual failed turn. The webhook action type
is `agent.session.action_required`; the stream type is `agent.session.requires_action`.
Verify the signature and retrieve current session/action details. Self-hosted environment
connection waits are bounded and are not a durable input queue. Session deletion is not an
external-compute shutdown instruction or a deletion webhook.
[Webhooks](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks).

Automations support once/cron schedules and new/existing-session targets. Busy-session tasks
wait rather than steering or answering pending actions. Invocation completion means input
delivery, not agent work completion. Queued invocations retain their target/input snapshot;
pausing/deleting schedules does not undo accepted work. Agent-created schedules can outlive
the turn that created them. The automations tool is absent by default.
[Scheduled automations](https://developers.openai.com/api/docs/guides/agents-api/sessions/automations).

**Architectural inference:** keep provider automation disabled for MC-governed sessions so
Temporal remains the sole mission dispatcher. Scheduled documentation research should use the
same governed mission/admission path rather than a second provider clock.

## Usage, traces and error recovery

Usage is best effort, nullable and may arrive/change after completion. Cached tokens are part
of input; reasoning tokens are part of output. Totals are not final billing. Preserve root,
child and aggregate accounting scope and avoid overlapping sums.
[Observability and usage](https://developers.openai.com/api/docs/guides/agents-api/observability).

Traces are enabled by default, built after turns and can lag. Paginated OTLP JSON export needs
organization/project enablement and permissions; a snapshot export is not a subscription.
Trace unavailability must not be reported as absence of work. Customer API does not report
command-output truncation, so complete shell output cannot be assumed.
[Tracing](https://developers.openai.com/api/docs/guides/agents-api/tracing).

For transient failures, inspect session, exact turn, saved items and effects before retry;
honor Retry-After and use bounded backoff. A reusable idle session after a failed turn differs
from a failed session requiring replacement. `active_turn_not_steerable` requires waiting;
session-budget exhaustion needs a new session. Files checks have a specific 429 error family.
Beta session error text is not the same structured object as stream errors.
[Error guide](https://developers.openai.com/api/docs/guides/agents-api/errors).

## Open proof register

| ID | Unknown / risk | Required evidence |
| --- | --- | --- |
| OA-P1 | Current wire/API/account compatibility versus code's 3.29.0 pin | Exact schema pin, feature permissions and small live fixture |
| OA-P2 | Lost create/send outcomes and input dedupe lifetime | Fault-injected acknowledgement loss, restart and exact root attribution |
| OA-P3 | Targeted steer/cancel completion race | Native boundary behavior and typed stale-target/continuation receipt |
| OA-P4 | Private suspension/expiry/recovery behavior | Environment lifecycle fixture; no R3 claim from successful internal resume |
| OA-P5 | Complete workspace capture for R2 | Quiescent bounded export, file manifest and independent digest/custody verification |
| OA-P6 | Native-child usage aggregation and trace export | Root/child/session observations, permissions and late-accounting reconciliation |
| OA-P7 | Hosted package/skill/file/input readiness | Setup/upload proof and failed/colliding upload recovery |
| OA-P8 | Independent verifier and exact transfer in GoalDirected | Two-iteration fixture with fresh verifier, saved settlement and replacement session |

All proofs are unrun in this research task. Provider evidence informs the design; it does not
change lane describe claims or release the live qualification gates.
