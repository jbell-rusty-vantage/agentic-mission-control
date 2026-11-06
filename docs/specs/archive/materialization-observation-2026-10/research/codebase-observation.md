---
type: Research Note
title: "Codebase audit: observation, events, callbacks and prior watcher patterns (2026-10-12)"
description: "Read-only audit of events, subscriptions, coordinator inbox, hook callbacks and manifest declarations per lane, plus archaeology of the owner's prior watcher and callback scripts."
tags: [mission-control, research, materialization-observation]
---

# Mission Control observation, events and callbacks: codebase audit and gap inventory

Date: 2026-10-12. This audit was read-only. Repo: `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control` (paths below are relative to it unless absolute). `src/mission_control/` is shortened to `mc/`.

Status legend:
- **WIRED+TESTED**: composed in a production entry point, and a test exercises it.
- **WIRED-UNTESTED**: composed, but no test exercises the composed path.
- **TESTED-UNWIRED**: the code and unit tests exist, but production composition does not connect it.
- **DESIGNED-ONLY**: a schema or spec exists, but no runtime consumer.
- **ABSENT**: nothing exists.

Tests I ran:
- `uv run pytest tests/unit/subscriptions tests/unit/streams tests/unit/coordinator/test_mission_subscribe_mcp.py tests/unit/harness/test_hook_callback.py tests/unit/deep_agents/test_hook_middleware.py`: **150 passed**.
- `tests/integration/cursor/test_kernel_hook_roundtrip.py`, `tests/unit/harness/test_cursor_local.py` and `tests/unit/claude/test_claude_controls.py`: **42 passed**.
- PostgreSQL integration suites (`test_mp15_coordinator_inbox_postgres.py`, `test_mp15_webhook_callbacks_postgres.py`, `test_subscriptions.py`): **blocked**, because `MISSION_CONTROL_TEST_ADMIN_DSN` is unset (10 errors at fixture setup). The implementation status doc reports them passing on real PostgreSQL (`docs/specs/archive/mc-surfaces-2026-10/docs/MISSION_CONTROL_IMPLEMENTATION_STATUS.md:68-70`).

---

## 1. Current architecture: events → store → stream → subscribers

```
 provider session (Cursor SDK / Cursor Cloud SSE / Claude Agent SDK / Codex app-server / LangGraph)
        │  native messages            in-session hooks
        ▼                                   │
 lane harness `observe` (worker) ◄──────────┘ cursor_local: kernel.py → 127.0.0.1:47555 (loopback only)
        │                                     claude_agent_sdk: in-process SDK callbacks
        │                                     deep_agents: HookScriptMiddleware (in-process)
        ▼
 Native Event Store  mission_control.provider_frame  (ADR-0028; verbatim, digested, 30-day retention)
        │  closing frames only
        ▼
 reducer → ledger_commit + mission events + outbox rows (one transaction; canonical.py::append_events)
        │
        ├─► SSE   GET /v1/applications/{app}/missions/{id}/events   (`missionctl events watch`)
        ├─► Socket.IO /missions (dashboard; PG replay; PG LISTEN / Redis hints; MP-14)
        ├─► SubscriptionRelay (API process, opt-in MISSION_CONTROL_SUBSCRIPTION_RELAY=1, 2 s poll)
        │       ├─ webhook   (HMAC, egress-guarded, at-least-once, 12 failures → dead letter)
        │       ├─ mcp_session (notifications/mission/event)  ← notifier not composed (see G1)
        │       └─ stream_ticket (client pulls)
        ├─► CoordinatorInboxService.run_once (same relay loop; MP-15)
        │       significance classification, batching, per-run rate cap, recursion cap
        │       delivery: poll (default) | webhook | mcp_session hint | prompt into coordinator run's mailbox
        └─► Transcript materialization (read view: events + frames + artifacts), run list/search
```

Key properties:
- The mission journal is authoritative. Hints (PG LISTEN, Redis) only wake consumers. Delivery is at least once with dedupe by `event_id`, and `CURSOR_EXPIRED` means "resync from inspection" (`mc/application/subscriptions/relay.py:1-17`, `mc/application/subscriptions/service.py:124-175`).
- Envelopes carry references only: `payload_ref` and digest, never the body (`docs/knowledge/events-and-commands.md:15-25`). A webhook receiver learns *that* something happened and must call Mission Control back, with a token, to learn *what*.
- Public alias projection: `run.completed ← workflow_run.terminalize`, `activation.completed ← attempt.completed`, `human_task.opened ← human_task.created` (`mc/application/subscriptions/aliases.py`). This closed the earlier gap B7.
- Coordinator significance kinds: `review_required` (human_task.opened/escalated), `blocked` (human_task.expired, command.in_doubt, subscription.dead_lettered), `failed` (session.continuation_failed), `terminal_result` (run.completed, chain.completed), `accepted_output`, `child_lifecycle`, `review_closed`, `progress` (batched) and `rate_limited`. Tool and token deltas are off by default (`mc/application/subscriptions/coordinator.py:52-120`).

## 2. Per-provider event sources (6 lane profiles + deep_agents = 7 `LaneProfile` values, `mc/domain/capabilities/host_support.py:20-31`)

| Profile | Native frames (how) | In-session hook → MC | Polling | Status |
|---|---|---|---|---|
| `deep_agents` | LangGraph stream events → frames, worker-local | Kernel and catalog hooks in-process (`HookScriptMiddleware`, `mc/adapters/deep_agents/hooks.py`). A catalog hook's `callback: service` is never populated (the `HookContext` built at `mc/adapters/deep_agents/materializer.py:421-429` has no `callback`) | n/a | Frames and kernel hooks WIRED+TESTED. Hook→service callback DESIGNED-ONLY |
| `cursor_local` | Cursor SDK bridge stream (`mc/adapters/cursor/local.py`, `frames.py`) | **Yes**: `.cursor/hooks.json` → `.mission/hooks/kernel.py` → `POST http://127.0.0.1:47555/v1/applications/{app}/internal/hook-callback` with a per-execution bearer token from `.mission/bin/.token` (`mc/adapters/cursor/kernel_hook_script.py:56-70`; `mc/interfaces/http/hook_callback.py`; listener `mc/bootstrap/worker.py:596-617`, port `mc/bootstrap/settings.py:318`). Persisted as `hook.invoked`/`hook.result` frames. Fail-closed on permission events | n/a | WIRED+TESTED (`tests/integration/cursor/test_kernel_hook_roundtrip.py`, `tests/unit/harness/test_hook_callback.py`). Not qualified live (B5). Needs a Proactor or Unix event loop (B6) |
| `cursor_cloud` | Cloud Agents API v1 run SSE, read by the worker with `Last-Event-ID`. After `410 stream_expired`, it polls `GET run` at a bounded interval (`mc/adapters/cursor/cloud.py:20-27, 791-950`) | **No.** "Kernel Hooks cannot call the worker's loopback listener from the cloud VM" (`cloud.py:41-43`). Composition passes `kernel_hooks=()` (`mc/adapters/temporal/deployment_composition.py:627-633`). Catalog command hooks still run in the VM but report nowhere. Cursor's v0 `statusChange` webhook is unused (`mission-control-general/runtime-facts/CURSOR_SDK_FACTS.md:78`) | Worker pulls the SSE stream, then polls the run record | Observation WIRED+TESTED against fakes, `qualified=False`. Hook push ABSENT |
| `claude_agent_sdk` | SDK `Message` union → frames (`mc/adapters/claude/frames.py`) | **Yes, in-process**: kernel hooks are `ClaudeAgentOptions.hooks` callbacks, outside agent-writable files (`mc/adapters/claude/hooks.py:1-25`). Catalog hooks are projected into `.claude/settings.json` via `run.py` and report nothing back | n/a | WIRED+TESTED (unit). Refused on a Windows host (`mc/adapters/claude/compose.py:87`); Linux/WSL only |
| `codex` | app-server JSON-RPC notifications → frames, with live and history cursors (`mc/adapters/codex/frames.py:1-26`) | Projection writes `.codex/hooks.json` with **kernel** commands (`python .mission/hooks/kernel.py …`, fixture `tests/fixtures/projections/codex/.codex/hooks.json`), but the Codex lane never writes `kernel.py`, `context.json` or the token, and no `HookCallbackService` is composed for it. Only `cursor_local` writes them (`mc/adapters/cursor/local.py:386, 536`). Approvals go through app-server server-requests instead (MP-11) | n/a | Frames WIRED+TESTED (unit). Kernel hook path **inconsistent, possibly dangling** (needs live verification: a missing script exits 2, which Codex treats as a PreToolUse block) |
| `claude_cloud` | None. A stub profile (`V2_STUB_LANE_PROFILES`, `mc/application/execution/harness/describe.py:643`); launch is refused | Documented possibility: repo-committed `type: "http"` hooks (PostToolUse, Stop, SubagentStop, SessionEnd) fire in cloud sessions and POST to "an endpoint we host" (`docs/specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/claude_cloud/FEASIBILITY.md:86, 109, 118`). OTel push is a second channel. Projection refuses kernel hooks (`mc/application/agentic_components/projections.py:896-901`) | No status API exists (`FEASIBILITY.md:102-109`) | ABSENT. The owner's "hook back to MC from the cloud" idea is the *only* documented observation channel here |
| `codex_cloud` | None. Stub | Hooks are unsupported under cloud orchestration (`projections.py:938`; `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/codex_cloud/FEASIBILITY.md:83, 89`) | `list`/`status` polling only | ABSENT (feasibility outcome: no integration) |

## 3. How a coordinator agent (for example a Claude Code session using the skill or MCP) is notified today

| Mechanism | Push or poll | Wakes a Claude Code agent? | Status and evidence |
|---|---|---|---|
| `missionctl run inspect ID --wait N` (N ≤ 3600) | Client-side poll every 0.5 s; returns on a lifecycle/phase/outcome change | Only if the agent runs it as a background or blocking command | WIRED (`mc/interfaces/cli/main.py:499-508, 1038-1048`). The skill documents it |
| `missionctl run transcript --follow` | Client poll | Same | WIRED (`main.py:629-654`) |
| `missionctl events watch MISSION --after-seq` (SSE) | Server push over a long-lived HTTP stream | Only through a host primitive that tails a stream (Claude Code `Monitor` or a background task). No such guidance exists | WIRED+TESTED (`mc/interfaces/http/subscriptions.py:114-149`) |
| Webhook subscription (`missionctl subscribe --webhook --secret-ref`, `POST /subscriptions`) | Push (signed, at least once) | No. Needs an https **global** receiver. Loopback only with `webhook_allow_loopback` (`mc/bootstrap/settings.py:383-386`; `mc/domain/subscriptions/contracts.py:66-83`). The relay is opt-in (`mc/bootstrap/subscriptions.py:89-90`) | WIRED+TESTED (unit; PG suites per status doc) |
| MCP `mission_subscribe` → `notifications/mission/event` | Push | **No.** Both MCP servers run `stateless_http=True` (`mc/interfaces/mcp/__main__.py:166-174`; `mc/interfaces/mcp/coordinator_bootstrap.py:57-63`). The API relay is started **without** a notifier (`mc/bootstrap/api.py:566-571` → `run_subscription_relays(..., inboxes=...)`, notifier defaults to None). The MCP process creates an `McpSessionHub` (`__main__.py:258-263`) but runs no relay. So `relay.py:149-159` pauses every mcp_session subscription on its first event. Even if delivered, a custom notification method is not model input in Claude Code | **TESTED-UNWIRED** (unit tests pass a hub explicitly: `tests/unit/coordinator/test_mission_subscribe_mcp.py:79-124`) |
| MCP/HTTP coordinator inbox: `coordinator_inbox_subscribe/poll/ack/command` (`mc/interfaces/mcp/subscriptions.py:288-439`; HTTP `mc/interfaces/http/coordinator_inbox.py:94-197`) | Durable inbox. Poll by default; webhook or mcp_session hint optional | Poll only. No long-poll or `wait` parameter on poll (`coordinator_inbox.py:133-147`). No CLI verb. The observe skill does not mention it. Registered only on the **dev** MCP server (static principal, no auth, no run_control). The authenticated mount has run_control but no inbox or subscriptions (HANDOFF C8, `docs/specs/archive/multi-provider-2026-10/HANDOFF-2026-10-10.md:169`) | WIRED (HTTP API) / partially composed (MCP) |
| Inbox `prompt_mode` → `queue_instruction` into the **coordinator's own run** mailbox | Push into an MC-managed agent | Only when the coordinator is itself a Mission Control run (`coordinator_run_ref` required, `mc/application/subscriptions/coordinator_service.py:124-131, 437-500`). An external Claude Code session is not | WIRED (API composes `commands=services.lifecycle`, `api.py:479-497`) |
| Auto-subscribe when the coordinator launches a run | Push | Claimed by ADR-0032 ("the coordinator skill registers one automatically when it starts a run"), but no caller exists. Only manifest-declared subscriptions register (`mc/application/authoring/manifest_submit.py:459-504`) | DESIGNED-ONLY |
| Callback command, file drop or sentinel, local exec on event | n/a | n/a | ABSENT |
| Claude Code channel or `ScheduleWakeup` integration | n/a | n/a | ABSENT (no reference anywhere in the workspace) |

**Answer (1):** today it is **poll, or block on a CLI wait**. The push paths are a webhook (needs a public https endpoint plus an opt-in relay env var) and the MCP notification (broken in composition, and not model-visible anyway). Nothing wakes an idle Claude Code session. The cheapest working wake today is `missionctl run inspect ID --wait 3600` launched as a background task, whose exit notifies the session, or `events watch` under a stream-tailing tool. Neither is documented in the skill.

**Answer (2):** in-environment hooks post back only on `cursor_local` (loopback HTTP, per-execution bearer token minted at prepare, bound to scope/run/attempt/generation/execution, digest-only storage). On `claude_agent_sdk` and `deep_agents` they are in-process. No cloud lane posts back. The listener binds 127.0.0.1 inside the worker (`worker.py:596-604`), and there is no public, authenticated ingress for provider hooks. Reaching Mission Control from a provider VM would need a public URL (tunnel or hosted API), a scoped short-lived per-run ingest credential delivered as a provider secret or env var, and egress allow-listing on the provider side (Claude cloud environments need network access to the collector, per `FEASIBILITY.md:117`). None of these exist. The hook-script contract already has a slot for it (`HookCallbackEndpoint{url, token_path}`, `mc/contracts/hooks.py:49-69`), but nothing populates it.

## 4. Manifest and workflow-level declarations available

| Declaration | Schema | Runtime consumer | Status |
|---|---|---|---|
| `controls.subscriptions[]: {events, channel: stream \| mcp \| {webhook, secret_ref}, node_keys}` | `mc/domain/authoring/manifest.py:900-920` | Registered on the run before launch (`manifest_submit.py:459-512`). `channel: mcp` creates `session_ref = manifest:{run}:{i}`, which no MCP session ever registers, so it is dead (`manifest_submit.py:509-510`). `stream` creates a ticket a client must pull | Webhook WIRED. mcp effectively dead. stream needs a client |
| `controls.notifications: {on, channel}` (cheatsheet shows `channel: inbox`) | `manifest.py:911-919`; `skills/mission-control-author/references/manifest-cheatsheet.md:38` | Copied into `MissionDefinition` (`mc/domain/authoring/mission_definition.py:269, 627`), consumed nowhere | DESIGNED-ONLY (and taught by the skill) |
| `controls.commands_allowed` | `manifest.py:917` | Command admission | WIRED |
| Environment `hooks[]: {pin, events (ADR-0026 vocabulary), matcher, fail_closed}` | `manifest.py:330-350, 482-486, 573` | Projected per lane into the native hook file plus `.mission/hooks/run.py`. Outputs answer the provider locally and are **not** forwarded to MC | WIRED for local lanes. "Report back" ABSENT |
| `HookScriptDefinition.callback: none \| service` | `mc/domain/authoring/contracts.py:1816-1835`; `mc/domain/capabilities/hooks.py:45-47` | Never results in an endpoint (see deep_agents above) | DESIGNED-ONLY |
| Program node `event_wait {event_type, match, timeout, on_timeout, mode}` and `timer` | `manifest.py:816-833` | Lowered to a generic `wait` node (`mc/adapters/postgres/control_plane/mission_revisions.py:302-303`), satisfied only by a manual `satisfy_wait` command. No external-event ingress, and no evidence that `match`, `timeout` or `rearm` are honored | Partial (wait only) |
| Coordinator profile (rate cap per run, batch window, recursion depth, kinds, prompt mode and limits) | `mc.coordinator_profile.v1`, `coordinator.py` | Only through the runtime `coordinator_inbox_subscribe` call. **Not declarable in a manifest** | Runtime-only |
| Watchers, triggers, conditions, callback commands, recipients, per-event boundaries | none | none | ABSENT |

**Answer (3):** a manifest can declare filtered subscriptions (event types plus node keys) to a webhook. It cannot declare coordinator-inbox delivery, rate or recursion bounds, recipients (which agent or session), conditions or expressions, local callback commands, or provider-side hook reporting. Boundaries such as rate limits exist only in the runtime coordinator profile.

## 5. Status matrix (summary)

| Capability | Status | Evidence |
|---|---|---|
| Native Event Store, frames, transcript, search | WIRED+TESTED | ADR-0028; `docs/knowledge/provider-frames-and-transcript.md` |
| Outbox → SSE `events watch` | WIRED+TESTED | `mc/interfaces/http/subscriptions.py:114` |
| Socket.IO `/missions` (dashboard) | WIRED+TESTED (no browser interop or load test; Redis publishers unwired) | `docs/knowledge/mission-stream.md:144-152`; status doc :69 |
| Webhook subscriptions + relay | WIRED+TESTED, but opt-in env and https/global-only egress | `bootstrap/subscriptions.py:41, 89-130` |
| Coordinator inbox (poll/ack/command/prompt) | WIRED+TESTED via HTTP. MCP only on the unauthenticated dev server | `mcp/__main__.py:242-263`; HANDOFF C8 |
| MCP session push (`mission_subscribe`, inbox hint) | TESTED-UNWIRED | `api.py:566-571`; `mcp/__main__.py:173` |
| Manifest `controls.subscriptions` webhook | WIRED | `manifest_submit.py:459` |
| Manifest `channel: mcp` / `stream` | Dead or client-dependent | `manifest_submit.py:505-512` |
| Manifest `controls.notifications` | DESIGNED-ONLY | `mission_definition.py:269` |
| Hook-script `callback: service` | DESIGNED-ONLY | `contracts/hooks.py:49`; `materializer.py:421` |
| Kernel hook loopback callback (cursor_local) | WIRED+TESTED | `test_kernel_hook_roundtrip.py` |
| Kernel hooks on codex local | Projected, not backed (verify) | fixture `.codex/hooks.json`; `cursor/local.py:386` only |
| Cloud hook ingress (cursor_cloud, claude_cloud) | ABSENT | `cloud.py:41-43`; `projections.py:896-901` |
| Cursor v0 `statusChange` webhook | ABSENT (not used) | `CURSOR_SDK_FACTS.md:78` |
| Coordinator auto-subscribe on launch | DESIGNED-ONLY (ADR-0032) | no caller of `subscribe(` in `application/coordinator` |
| `event_wait` from external events | Partial (manual `satisfy_wait`) | `mission_revisions.py:302` |
| Agent-facing "wait for next notification" tool or long-poll | ABSENT | `coordinator_inbox.py:133` |
| Skill guidance on waiting or waking (Monitor, background wait, inbox) | ABSENT | `skills/mission-control-observe/SKILL.md` (no inbox; advertises `mission_subscribe`) |

## 6. Archaeology: the owner's prior watcher and callback patterns

All paths below are under `C:\Users\Pinda\Proyectos\BellLabs\`. A subagent swept the workspace; key items were spot-referenced.

**A. Supervisor or watchdog that polls processes (the richest example)**
- `aiengineer\research_starter_pre_research_agent\scripts\platform\watch-local-drain.ps1`
  - Supervises 1–4 Node drain workers on a 15 s tick.
  - A worker counts as stalled when its stdout hasn't changed for 2400 s.
  - Restarts a failed worker after 15 s and keeps the machine awake.
  - Logs JSONL to `outputs\local-drain\watchdog.log`: about 1,981 `worker_started` and 1,969 `worker_exited` events.
- `...\scripts\platform\stop-local-worker-after-result.ps1`
  - Tails the worker's stdout from a byte offset, polling every 100 ms, for a `"event":"video_result"` marker.
  - Then writes the stop file `stop-after-result.json`, waits up to 10 s, and force-kills the worker if needed.
- Documented failures:
  - `.claude\error-solutions\boundary-stop-successor-lease-race.yaml`: the stop arrived after the next job was claimed, leaving an orphaned 30-minute lease. The fix was a cooperative stop file and exit code 75.
  - A UTF-8 BOM written by `Set-Content` made the worker ignore the stop file (`operations.md:156`).
  - Stale PIDs.
  - "Empty stderr" used as a health signal produced a false alarm (`review-deferral-stderr-false-positive.yaml`).
  - The watchdog restart masked a retry bug.
  - Watchdog shutdown ordering left a slot with no replacement worker (`HANDOFF-2026-08-25-SLIM-62-STOPPED.md`).

**B. Scheduled or cron wakeups**
- KS Git maintenance watcher: `platform\knowledge-services\tools\maintenance\{install-watcher.ps1, run-watcher.ps1, run-watcher-hidden.vbs, policy.json}`.
  - A Windows scheduled task runs every minute; the work is a SQLite leased queue.
  - Failure: an orphaned task still pointed at the old repo path (`CLEANUP-RUNBOOK.md:171`).
  - Failure: scheduled tasks don't inherit PATH.
  - Failure: it needs the user signed in.
- Eve/Vercel cron `pre-research-next` (`agent\schedules\pre-research-next.ts`, `controller\scheduled-pre-research.ts`, which uses an advisory lock and `overlap_skipped`).
  - Failure: the cron route token rotated on every deploy.
  - Failure: Vercel killed a run at 300 s.
  - Failure: the cron and the local watchdog were kept apart only by convention.

**C. HTTP callback and stream waiters**
- Eve durable callbacks (`HANDOFF-2026-08-21-PRE-RESEARCH.md:258-536`): a late model step is picked up by the next cron tick.
- `scripts\archive\run-pre-research-session.mjs:39-73` reads the session stream until `turn.completed` or `session.waiting`.
- Knowledge Services already ships signed A2A callbacks with a replay ledger, a reusable precedent:
  - `platform\knowledge-services\packages\application\src\operations\a2a-callbacks.ts` (HMAC; https/loopback-only targets)
  - `packages\persistence\src\callback-replay.ts`
  - `aiengineer\ai-engineer-db-contract\...\callback_delivery.md`

**D. Poll until a final status**
- `platform\knowledge-services\.github\maintenance\cursor-run.mjs`
  - Polls a Cursor Cloud run every 30 s for at most 10 minutes.
  - When the budget runs out it returns `pending` with `waitBudgetExhausted`.
  - Documented: "a successful launch is not completion".
- Biotech receipt poller `runs\release-v2\eval-runs\...\WR-23.mjs`.
- Biotech soak watchdog `runs\release-v2\custody\s9\run-soak.mjs`: writes `progress.json` once a minute and stops itself on error or latency thresholds.
- Mission Control experiments' outbox wake dispatchers (`experiments\langgraph_temporal_stagegraph\wake_dispatcher.py`): wakes were being consumed by the wrong run.

**E. Agent lifecycle hooks (Cursor)**
- `platform\knowledge-services\.cursor\hooks.json` and `aiengineer\.cursor\hooks.json` call `tools\maintenance\cursor-hooks.mjs` on `beforeSubmitPrompt`, `afterFileEdit`, `afterShellExecution` and `stop` (`loop_limit` 1).
- The `stop` hook enqueues a follow-up job. Recursion is blocked with fingerprints. Git hooks feed the same queue, and the scheduled task is the fallback.
- No Claude Code hooks exist in the workspace (`.claude\settings.local.json` holds permissions only).

**F. Markdown ledgers and handoff files**
- AI Engineer `internal\starter-research-local\*\PROGRESS.md` and per-video `STATUS.md`. Failure: double-claim risk.
- Mission Control team ledger `.scratch\multi-provider-2026-10-08\team\{LEDGER.md, claims\, handoffs\}` with background Task subagents.
  - Failure: handoffs lost when the session hit its usage limit.
  - Failure: MP-08 had to be reconstructed afterward.
- Biotech `docs\plans\schema-v2-service-release\STATUS.md`.
- Ontology-lab run conflict ledger.

**Not found:** `ScheduleWakeup`, `run_in_background`, Monitor-tool usage, desktop or push notifications, and FileSystemWatcher. `archive\` and `internal_hidden_docs\` are empty.

**Recurring shape:**
- *Watched:* a process, a log line or a remote job status.
- *Signal back:* a file or log line (JSONL, stdout marker, stop JSON, STATUS.md) or an exit code. Never a push to the orchestrating agent.
- *Triggered:* a restart, the next job, a follow-up agent turn, or a human reading the ledger.
- *Failure modes:*
  - races between the stop signal and the next claim
  - wrong-process or wrong-run targeting
  - orphaned schedulers
  - Windows quirks (BOM, PATH, sleep, sign-in)
  - rotating auth
  - weak health signals
  - budget-limited pollers abandoning still-running work
  - lost handoffs when the orchestrator dies

Mission Control's journal, inbox and subscriptions already solve durability, dedupe and recursion. What is missing is the **last mile**: waking the orchestrating agent, and getting signals in from remote environments.

## 7. Ranked gaps (impact on "formalize watchers/callbacks into MC")

1. **G1. No way to wake the orchestrating agent.**
   - The MCP push is unwired: there is no notifier in the relay (`api.py:566-571`), and both MCP servers are `stateless_http=True`.
   - Even if delivered, a custom `notifications/mission/event` is not model input in Claude Code.
   - Needed: a first-class "await" surface, for example `missionctl wait --run/--inbox --until kinds=… --timeout`, a long-poll on the inbox, and an MCP `coordinator_inbox_wait` tool.
   - The skill should then teach the host primitives (background task or Monitor, and optionally a Claude Code channel) as the wake mechanism.
2. **G2. No public, authenticated ingress for in-environment provider hooks.**
   - The kernel callback is 127.0.0.1-only (`worker.py:596`).
   - Cloud lanes can't report (`cloud.py:41-43`, `projections.py:896-901`).
   - Needed: an API-hosted `POST /v1/applications/{app}/runs/{id}/hook-events` (or an ingest relay) with a per-run, short-lived, event-scoped, HMAC or bearer credential, idempotency keys, size caps, and frames written as `hook.invoked` with `observation.source=remote_hook`.
   - This unlocks claude_cloud (http hooks are its only documented observation channel) and cursor_cloud hooks.
3. **G3. Manifest cannot declare watchers or callbacks with boundaries.**
   - `controls.notifications` is parsed but never consumed. `channel: mcp` is dead.
   - The coordinator profile (kinds, rate cap, batch, recursion, prompt mode) cannot be declared. There are no recipients, conditions or triggers.
   - Needed: a `controls.watch` / `observers` block that compiles to inbox subscriptions with profile and recipient, rate and recursion budgets, and validation in the compile report.
4. **G4. Coordinator auto-subscribe on launch is missing.** ADR-0032 promises it; nothing calls `subscribe` from coordinator launch. Every run launched by an agent should get a default coordinator inbox bound to that agent's identity.
5. **G5. The observe skill is stale and under-specified.**
   - It advertises `mission_subscribe`, which does not work in deployment.
   - It omits the coordinator inbox (poll/ack/command), and teaches `controls.notifications`, a dead field.
   - It gives no waiting or wake recipe (background `inspect --wait`, `events watch` under Monitor), no "check inbox at turn boundary" protocol, and no Windows-safe guidance.
6. **G6. The MCP surface is split.** The authenticated mount has run_control but no inbox, subscriptions or transcripts. The dev server has inbox and transcripts but no auth and no run_control (HANDOFF C8). An agent cannot do observe + act + ack over one authenticated MCP.
7. **G7. Catalog hook outputs never report back.** `run.py` answers the provider locally; `callback: service` is DESIGNED-ONLY (`contracts/hooks.py:49`, `materializer.py:421`). So user "watcher hooks" (for example "on Stop, tell MC the summary"; "on afterFileEdit of X, raise milestone") cannot emit events.
8. **G8. No agent-emitted custom or milestone events.** No `report_progress`/`emit_event` capability exists for a running mission agent, so "needs input", "milestone", "blocked on X" from inside a session become only free text in frames. Human tasks cover approvals only.
9. **G9. The webhook path is hard to use locally.** The relay is opt-in via env (`MISSION_CONTROL_SUBSCRIPTION_RELAY=1`). Egress is https/global only; loopback needs `webhook_allow_loopback`. Payloads are reference-only, so the receiver needs an MC token to read anything. No local "callback command" executor exists (run a shell command or file-drop on event), which is the pattern the owner's scripts used.
10. **G10. Provider-native completion signals are unused.** Cursor v0 `statusChange` webhooks are ignored. claude_cloud OTel and http hooks have no receiver. The worker holds an open SSE per cursor_cloud run, and after expiry polls the run record. There is no push ingress to reduce polling or survive worker loss.
11. **G11. `event_wait` and triggers are not externally driven.** `event_wait.match`, `timeout`, `on_timeout` and `rearm` lower to a manual-satisfy wait. There is no external event ingress (for example "wake when a PR is merged or a file appears"), which is what many prior watchers did.
12. **G12. Lane-level inconsistencies and qualification gaps.**
    - Codex local projects kernel command hooks without `kernel.py`, `context.json`, a token or a callback service. This needs live verification (possible PreToolUse blocking or silent loss).
    - `claude_agent_sdk` and `codex` are Linux/WSL only, while the owner's host is Windows.
    - Cursor lanes are unqualified (B5/B6).
    - Socket.IO has no browser interop test and Redis publishers are unwired.
    - The PG subscription suites were not rerunnable here.

**Lower-priority observations:**
- Inspection `--wait` is 0.5 s client polling, not server long-poll.
- Inbox poll has no `wait` parameter.
- The subscription relay polls every 2 s in-process (no LISTEN-driven relay).
- No dashboard or alerting on `subscription.dead_lettered`, beyond it becoming a `blocked` inbox notification.
