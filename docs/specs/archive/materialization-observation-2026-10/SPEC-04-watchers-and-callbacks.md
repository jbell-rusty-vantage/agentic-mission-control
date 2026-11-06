---
type: Specification
title: "SPEC-04: Watchers, signals and callbacks — formal observation from provider environments to the orchestrating agent"
description: "Signal Ingress with trust tiers, a Telemetry Hook Pack and mc-signal emitter projected into every provider environment, manifest-declared Watchers with closed conditions, typed actions and boundaries, and wake channels that reach an idle orchestrating agent."
tags: [mission-control, specifications, observation, subscriptions, hooks, watchers, callbacks]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: **Ingress** local tests (done, MO-40), **Watchers** (done, MO-44), **Wake** with a real `run.completed` (MO-43 done; re-proven per S0 cell) and the no-dead-fields clause. Carried forward: the **cursor_cloud drill** telemetry and gate-stop clauses (S1). Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-04: Watchers, signals and callbacks

Gaps closed: G5, G6 and G7 ([gap report](GAP-REPORT.md)).

## Why this is needed

The owner's previous automation used six recurring families of ad hoc watchers and callbacks, catalogued in [research/codebase-observation.md §6](research/codebase-observation.md):

- supervisors;
- scheduled wakeups;
- HTTP callbacks;
- poll-until-done loops;
- Cursor `stop` hooks;
- Markdown ledgers.

Each one rebuilt durability, dedupe and stop semantics badly. Mission Control already owns those (journal, outbox, inbox, dedupe, recursion caps). This spec adds the two missing ends:

- **getting signals in** from wherever the agent runs;
- **getting decisions out** to whichever agent is orchestrating.

## 1. Model

```text
 Signal sources ──► Signal Ingress / native frames ──► mission journal (events, frames)
                                                           │
                                         Watchers (declared, bounded, deterministic)
                                                           │ typed actions
             ┌──────────────┬───────────────┬──────────────┼──────────────┬──────────────┐
          notify        instruct      satisfy_wait      launch        human_task      webhook/command
       (coordinator   (queue_instr.   (event_wait     (child mission   (Human Task    (external)
         inbox)         to a run)       node)          / chain link)    Service)
             │
       Wake channels ──► orchestrating agent (Claude Code / Codex / Cursor / Mission Control coordinator run)
```

Invariants:

- **Signals are evidence, not authority.** Reducers own lifecycle and settlement, and Temporal alone schedules (AGENTS.md). A signal can inform a reducer only through the existing closing-frame rules for its lane. A watcher acts only through existing commands and Governed Effects.
- **Signal payloads are untrusted data.** Anything forwarded to an agent is wrapped as data with provenance, never as instructions. The coordinator inbox renders signal text inside a quoted, labelled block, which guards against prompt injection from a compromised or confused environment.

## 2. Signal sources

| Source | Examples | Path into Mission Control |
| --- | --- | --- |
| S1 Native frames (exists) | Claude SDK messages, Codex app-server notifications, Cursor SSE | Lane `observe` → Native Event Store |
| S2 In-environment hooks (new for remote) | Stop, SubagentStop, PostToolUse(filtered), Notification/permission requests, PreCompact, SessionStart | Telemetry Hook Pack → Signal Ingress |
| S3 Agent-emitted signals (new) | `milestone`, `blocked`, `needs_input`, `artifact.ready`, `progress` | `mc-signal` CLI or the MCP `signal_emit` tool inside the environment → Signal Ingress |
| S4 Provider push (new) | Cursor v0 `statusChange` webhook (FINISHED/ERROR, HMAC); Anthropic Managed Agents and OpenAI Agents API webhooks (SPEC-06) | Ingress `/v1/ingress/provider/{provider}` with provider signature verification |
| S5 External systems (new) | GitHub `check_suite`/`pull_request`/`push` (webhook or poll), Knowledge Services artifact events, schedule/timer | Ingress `/v1/ingress/github` (webhook secret), poll activities, Temporal timers |
| S6 Worker-side watches (new; formalizes the PowerShell supervisors) | Process exit, log pattern, file appearance, URL health, "no frames for N minutes" | Temporal activities with heartbeats on the worker that owns the lease |

## 3. Signal Ingress

**Endpoint.** The ingress is served per application at `/v1/ingress/{app}/…`:

- `signals` (batched `mc.signal.v1`; `?gate=1` for synchronous gates);
- `artifacts:prepare` and `artifacts:commit` (signed uploads to a quarantine bucket);
- `provider/{anthropic|openai|cursor/{run_ref}}`;
- `github`.

Deployment, routes, SQL functions and the drainer are specified in [SPEC-10](SPEC-10-ingress-on-vercel.md), which supersedes the route list previously given here. It is deployed on Vercel this sprint (decision R11), stores into Supabase Postgres, and is drained by the worker-side IngressDrainer. The same handlers can be served locally behind a tunnel for drills against a local database.

**Reachability is a deployment requirement.** Provider VMs can reach only public HTTPS:

- This sprint: the Vercel ingress (SPEC-10) writing to the application's Supabase Postgres.
- Local-database drills: an owner-approved tunnel (Cloudflare Tunnel or Tailscale Funnel) exposing only the ingress mount.

Either way the ingress host is added to every cloud environment's egress list (SPEC-01 §5). Without it, cloud lanes fall back to S1, S4 and S5 only, and the preflight says so.

**Trust tiers.** The tier is recorded on every signal, and watchers can require a minimum tier.

| Tier | Credential | Lanes | May drive |
| --- | --- | --- | --- |
| `run_token` | Per-run `mint:signal_token` (SPEC-01 §4), bound to scope, run, unit and generation. Digest stored. Delivered by local env, `.mission/bin/.token` locally, or Cursor launch `envVars`. | local lanes, cursor_cloud (if `envVars` enabled) | Everything below, plus synchronous gates and artifact upload |
| `provider_oidc` | Cursor VM-minted JWT (`/run/cursor/api.sock`, `aud` = our ingress, ≤5 min). Verified against `api.cursor.com/keys`; `cloud_agent_id` mapped to the run. | cursor_cloud | Same as `run_token` |
| `provider_signed` | Provider webhook HMAC (Cursor v0, GitHub) | S4, S5 | Observation, `satisfy_wait` |
| `environment_key` | One HMAC key per provider environment, held as an environment secret or network secret. Signals carry the provider session id (`CLAUDE_CODE_REMOTE_SESSION_ID`). Mission Control **binds** a session id to a run on the first `session.started` signal that carries the run's nonce from `.mission/run.json` on the branch. Later signals from that session id are accepted for that run only. | claude_cloud, codex_cloud | Observation, notify, `satisfy_wait`. **Never** gates, effects or artifact acceptance. |

**Storage.** Accepted signals become provider frames (`source: ingress`, kind `signal.<type>`) in the Native Event Store, digested and redacted. Watchers and the transcript read them like any other frame. Duplicates are dropped by `(credential, signal_id)`.

**The existing loopback hook callback** (`interfaces/http/hook_callback.py`) becomes the same handler mounted on loopback. Cursor-local behaviour is unchanged.

## 4. In-environment Telemetry Hook Pack and `mc-signal`

### 4.1 Contents

Every lane's cognition pack includes, unless `observation.in_environment: off`:

- `.mission/hooks/signal`: a small, dependency-free POSIX shell script plus a Python fallback. It:
  - reads the hook JSON on stdin;
  - filters by `.mission/signal-policy.json`;
  - appends to a local spool `.mission/signals.jsonl`;
  - POSTs batches to the ingress, with a 2 s timeout and exponential backoff;
  - never blocks the agent, except on the gate events of §4.3.

  The spool is uploaded at `Stop` and at the end of the session. Gaps are detectable because every signal carries a monotonic per-session `seq`.
- `.mission/bin/mc-signal`: a CLI for agents and scripts, for example `mc-signal milestone "tests green" --data '{"passed":412}'` or `mc-signal blocked "need staging DB creds"`. It is mirrored by an MCP tool `signal_emit` on the Mission Control MCP server, for lanes that prefer tools.
- A skill, `mc-signals`, that teaches the agent *when* to emit (milestones, blocked, artifact ready) and that signals are the only channel back. It replaces ad hoc status files.

### 4.2 Native projection

| Lane | Native events wired to `signal` | Notes |
| --- | --- | --- |
| claude_agent_sdk | In-process SDK hooks feed frames directly; the pack is used for `http`-only events if needed | No ingress needed locally |
| claude_cloud | `SessionStart`, `Stop`, `StopFailure`, `SubagentStop`, `Notification`, `PermissionRequest`, `PostToolUse` (matcher-filtered), `PreCompact`, `TaskCompleted`, `SessionEnd`; `type: http` with `async: true` where the semantics allow, otherwise command | Single-repo sessions only. Network level Custom/Full with the ingress host. |
| cursor_local | Existing kernel loopback, plus the pack for catalog events | |
| cursor_cloud | `preToolUse`, `postToolUse`, `subagentStart`/`Stop`, `afterAgentResponse`, `stop`, `preCompact` | No `sessionStart`. The first fired hook emits `session.started` and `materialization.observed`. |
| codex | app-server notifications already cover most of it; the pack handles `Stop`/`SubagentStop` signals for catalog watchers | Hook trust (SPEC-02 §5) |
| codex_cloud | None (hooks unsupported). `mc-signal` from the agent is advisory only, through the `AGENTS.override.md` instruction plus network allowlisting. | Lowest observability; experimental lane, DECISIONS R5 (SC-03) |

### 4.3 Synchronous gates and the remote stop fence

On `PreToolUse` (Claude), `preToolUse`/`beforeShellExecution` (Cursor) and `PreToolUse` (Codex local), a **gate** variant calls `POST /v1/ingress/{app}/signals?gate=1` synchronously and applies the answer.

- **Answers:**
  - `allow`;
  - `deny`, with a reason;
  - `stop`, mapped to Claude `continue:false` with a `stopReason`, Cursor deny plus `stop` follow-up suppression, or Codex `decision: "block"`.
- **Requirements:** `run_token` or `provider_oidc` trust. Fail-closed only when policy says so: Claude `onFailure: "block"`, Cursor `failClosed`.
- **What it buys:**
  - A **cooperative stop and cancel** for lanes that have no cancel API, delivered within one tool call. This makes cancel feasible for claude_cloud for the experimental lane (DECISIONS R5, SC-02), gated on trust tier: with `environment_key`, `stop` is honoured but `allow` never overrides local policy.
  - Mission Control **Stop Fence** parity on remote VMs.
- **Limits.** Native hooks are not a security boundary (SPEC-02 §5), and latency is added only to gated tools.

## 5. Watchers

### 5.1 Manifest syntax

Watchers sit under `controls.watchers` at mission or node level. Reusable ones are published as catalog Capability Kind `watcher` (`mc.watcher.v1`) and referenced by pin.

```yaml
controls:
  watchers:
    - id: ci-red-fix
      on:
        signal: github.check_suite.completed
        where: "event.conclusion == 'failure' and event.head_branch == run.branch"   # closed AST (ADR-0010)
      then:
        - instruct: {target: self, text_ref: "prompts/fix-ci.md", include: [event.summary]}
      limits: {max_fires: 3, min_interval: 10m}
    - id: stalled
      on: {absence: {of: [frame, signal], for: 20m}, while: "run.phase == 'executing'"}
      then:
        - notify: {kind: blocked, text: "No progress for 20 minutes"}
        - probe: {target: self}            # emulated reattach / status read
      limits: {max_fires: 2}
    - id: artifact-to-ingest
      on: {signal: artifact.ready, where: "event.media_type == 'application/pdf'"}
      then:
        - launch: {mission_ref: "missions/ks-ingest@2", inputs: {artifact: event.artifact_ref}}
      limits: {max_fires: 50, rate: 10/h, budget: {tokens: 2000000}}
    - id: done-notify
      on: {event: run.completed}
      then: [{notify: {kind: terminal_result}}]
  notifications:                         # sugar for notify-only watchers (replaces the dead field)
    on: [run.completed, human_task.opened, blocked]
    channel: inbox
```

**Triggers:**

- `signal` (S2–S5 types);
- `event` (mission journal types, including the public aliases);
- `absence` (nothing seen for a duration);
- `schedule` (cron or interval, as a Temporal schedule);
- `watch` (S6 worker watches: `process`, `log_pattern`, `file`, `url`).

**Conditions** use the closed expression AST from ADR-0010 over `event`, `run`, `unit` and `watcher`. There is no free-form code.

**Actions** form a closed, typed set. Each maps to an existing path.

| Action | Maps to |
| --- | --- |
| `notify` | Coordinator inbox item (significance kind) → wake channels |
| `instruct` | `queue_instruction` command (or `interrupt_and_inject` where the lane supports it) |
| `satisfy_wait` | Releases an `event_wait` node. This fixes `event_wait` being releasable only by hand. |
| `launch` | Child mission or Mission Chain link through Spawn Grant and admission |
| `human_task` | Human Task Service |
| `command` | `pause`, `cancel`, `request_continuation`, through command admission and governance |
| `probe` | Lane inspection or emulated reattach |
| `webhook` | Signed outbound delivery through the existing relay |
| `run_check` | A deterministic verification activity in the lease, such as a test command or schema validator. Its result becomes a signal. |

### 5.2 Boundaries

Boundaries are mandatory, with defaults from the installation's coordinator profile.

- **Firing limits:** `max_fires`, `min_interval`/`rate`, and a debounce or `batch` window.
- **Recursion depth.** It is inherited, and a watcher-launched mission carries `watcher_depth+1`. The default maximum is 2.
- **Budget** for `launch` and `instruct`. It is charged to the parent mission's budget, with the Governor applied.
- **Allowed actions per grant.** A Spawn Grant and command grants must cover the action; validation fails otherwise.
- **Minimum trust tier** of the triggering signal (default: `provider_signed` for `command` actions).
- **Lifetime:** `until` (an event or deadline). By default watchers die with the run, except `notify` on terminal events.

### 5.3 Evaluation

Watchers are compiled into the Compiled Program as **watcher descriptors** and evaluated by one deterministic **Watcher Evaluator**:

- It reads the outbox and the frame stream (the same relay loop as the coordinator inbox), plus Temporal timers for `absence` and `schedule`.
- Each firing is recorded as an event, `watcher.fired`, with its trigger reference and actions. Actions go out through the outbox with a dedupe key `(watcher_id, trigger_event_id)`, so a replay never double-fires.
- Failures become `watcher.failed` and are dead-lettered after N attempts.

### 5.4 Standard watcher library

The catalog publishes these `mc.watcher.v1` templates, which replace the owner's old scripts:

| Template | Replaces |
| --- | --- |
| `stall-detector` (absence → notify + probe) | `watch-local-drain.ps1` stall logic |
| `result-marker-stop` (signal match → graceful `command: pause` then stop at a boundary) | `stop-local-worker-after-result.ps1`, without its stop/claim race, because Mission Control commands are fenced |
| `ci-watch` (GitHub checks → instruct or notify) | Manual PR babysitting |
| `pr-merged-release-wait` (satisfy `event_wait`) | Polling loops |
| `artifact-pipeline` (artifact.ready → launch ingest/verify mission) | Ad hoc callback chains |
| `budget-guard` (usage events → notify at 80%, pause at 100%) | Manual watching |
| `heartbeat-progress` (batch progress → notify every N minutes) | STATUS.md ledgers |

## 6. Wake channels: reaching the orchestrating agent (G5)

Mission Control cannot interrupt an arbitrary idle agent. It offers channels that work with each orchestrator's own primitives. The coordinator inbox is the single durable source for all of them. Every channel is a cursor over it, and acknowledgement is explicit.

| Channel | How it wakes | Use from |
| --- | --- | --- |
| **W1 `missionctl wait`** (new CLI verb) plus HTTP long-poll `GET /coordinator-inboxes/{id}/notifications?wait=<s>&kinds=` | Blocks until the next matching item, prints one JSON line per item, exits 0 (or 6 on timeout, the general CLI's wait-timeout code; corrected by MO-43). `--follow` streams lines. | **Claude Code:** run as a background Bash task (completion notification wakes the session), or under the Monitor tool with `--follow` (one notification per item). **Codex / Cursor orchestrators:** a blocking call between turns. |
| **W2 MCP `inbox_wait`** tool (`coordinator_inbox_wait`) on the **authenticated** Mission Control MCP server | Long-poll tool call that returns items as the tool result, which is model-visible | Any MCP-capable orchestrator; replaces the non-model-visible `mission_subscribe` notification |
| **W3 Claude Code channel** | An MCP server that pushes inbox items into a *running local* Claude Code session through Claude Code's channels feature | Interactive local Claude Code coordinator. Qualify against the docs first (Q-O1); optional. |
| **W4 Webhook** | Existing signed relay; optionally with an inline redacted summary (`payload: summary`) so receivers need not call back | Orchestrators that host an endpoint (CI, Slack bridge, phone push service) |
| **W5 Prompt mode** (exists) | `queue_instruction` into a coordinator that is itself a Mission Control run | Mission Control-run coordinators (Deep Agents or provider lanes) |

Fixes bundled with this section:

- **Unify the MCP surface.** The authenticated server gains the inbox, `inbox_wait`, transcripts and `signal_emit`. The dev server keeps parity for local development (HANDOFF C8).
- **`mission_subscribe`.** Either compose a notifier with stateful sessions, or deprecate it in favour of W2. Recommendation: deprecate. It is not model-visible in Claude Code, and its stateless HTTP transport cannot carry it.
- **Auto-subscribe on launch (ADR-0032).** Every run launched through the coordinator API registers an inbox subscription for its launcher with the launcher's coordinator profile, unless the launch sets `notify: none`.
- **Relay.** The subscription relay is on by default in API processes (`MISSION_CONTROL_SUBSCRIPTION_RELAY` defaults to `1`). Loopback webhooks are allowed for `local_dev` installations.

## 7. Observe skill v2

Rewrite `skills/mission-control-observe` around these recipes, and update the router skill and author cheatsheet:

1. **Launch then wait:** start `missionctl wait --run <id> --kinds terminal_result,blocked,review_required` as a background task, then continue other work. The notification arrives on exit.
2. **Supervise many:** `missionctl wait --follow --coordinator <me>` under Monitor, with a filter so every terminal state, including failure, emits a line.
3. **Inspect on wake:** `run inspect`, `run transcript --since`, `events --after-seq`.
4. **Intervene:** route to the intervene skill.
5. **Declare instead of babysit:** author watchers in the manifest (author skill) rather than running ad hoc loops. Use the standard library first.
6. **Never** write poll loops with sleeps, status files or stop files; the reasons are listed in the archaeology.
7. Remove `mission_subscribe` and `controls.notifications`-as-inbox guidance until those paths are verified working end-to-end.

## 8. Acceptance

- **Ingress:**
  - Run-token, Cursor-OIDC, provider-HMAC and environment-key signals are each accepted at their tier and rejected when wrong.
  - Duplicates are dropped.
  - Payload limits are enforced.
  - Frames are persisted and visible in the transcript.
- **cursor_cloud drill:**
  - The Telemetry Hook Pack delivers `session.started`, `materialization.observed` and `stop` signals through the tunnel.
  - A gate hook enforces a `stop` within one tool call.
- **Watchers:**
  - `ci-red-fix`, `stalled` and `artifact-to-ingest` fire deterministically in a Temporal test environment.
  - They respect `max_fires`, rate, recursion and budget.
  - A replay produces no duplicate actions.
- **Wake:** a Claude Code coordinator using recipe 1 is woken by a real `run.completed` without polling in its own context. Recorded as a qualification transcript.
- **No dead fields:** `controls.notifications` is consumed, and `channel: mcp` either works or is rejected by validation.
