---
type: Specification
title: "Managed agents and the remote path: how Anthropic Managed Agents and the OpenAI Agents API fit Mission Control, Vercel and Temporal, and the fastest way to run workflows remotely"
description: "Breaks agent systems into layers and places every product on them (harness, managed agent, SDK, sandbox, orchestrator). Shows how to seed skills, MCP, tools, environments and secrets on both providers, with and without Temporal. Cross-references the materialization-observation sprint and proposes amendments for remote knowledge work without deploying agent compute."
tags: [mission-control, specifications, providers, anthropic, openai, temporal, vercel, remote]
---

# Managed agents and the remote path

**Status:** accepted and folded into the sprint (2026-10-12): R-NEW-1 to R-NEW-5 became DECISIONS R29–R33, and the thin worker was decided as AWS ECS Fargate (R28, [SPEC-11](SPEC-11-remote-worker-on-aws.md)). Section 8 is kept as the record of the cross-reference. Facts come from this packet's evidence ([Anthropic Managed Agents](research/anthropic-managed-agents.md), [OpenAI hosted agents](research/openai-hosted-agents.md), [Vercel ingress](research/vercel-ingress.md)), read 2026-10-12, plus three primary sources read the same day:

- Temporal Serverless Workers: <https://docs.temporal.io/evaluate/features/serverless-workers>
- Vercel Workflows: <https://vercel.com/docs/workflows>
- The provider overviews: <https://platform.claude.com/docs/en/managed-agents/overview>, <https://developers.openai.com/api/docs/guides/agents-api/overview>, <https://developers.openai.com/api/docs/guides/agents/sdk>

No paid calls were made for this page itself. The SDK pins are `anthropic` 1.13.0 and `openai` 3.29.0. Step 1 of §7, the HL-23 provider smoke, has since run against both APIs, and the §3 shapes below are the ones it confirmed. The ids, events, usage and corrections are in [research/provider-smoke-2026-10.md](research/provider-smoke-2026-10.md).

## 1. The short answer

| Question | Answer |
| --- | --- |
| Can a Vercel server call the managed agents? | **Yes.** Creating sessions, sending events and receiving provider webhooks are ordinary HTTPS calls, and Vercel Functions handle them well. |
| Can Temporal be the macro runtime over them? | **Yes.** Each managed-agent session becomes one step (or one child workflow) in a Temporal workflow. Mission Control is already designed this way: Temporal is the sole scheduler (ADR-0004), and `claude_managed` and `codex_agents` are lanes (SPEC-06). |
| Do we still need a worker deployment? | **Yes, but only a small one.** Managed agents remove the **agent-compute worker**: the harness, sandbox, tools, CLIs and images. They do **not** remove the **orchestrator worker**, because Temporal Cloud stores workflow state but never runs your code; a worker process must. With managed agents that worker only makes HTTP calls and waits, so it can be your WSL2 machine (free), a small container, or a Temporal Serverless Worker (scales to zero). **It cannot be a Vercel Function**, because a Temporal worker is a long-polling process. |
| Is there a path with no worker at all? | **Yes, but outside Temporal:** Vercel Workflows runs durable workflow code (TypeScript or Python) on Vercel Functions with sleeps, hooks and webhooks. That would be a second durable runtime beside Mission Control's Temporal (§5, pattern B). |
| How is the Claude Code harness different from Managed Agents? | Claude Code is a **program you run** (the CLI or Agent SDK) that contains the agent loop. Managed Agents is **Anthropic running a different agent loop for you** behind an API. It does not read `CLAUDE.md`/`AGENTS.md`, `.claude/agents`, hooks or plugins (correction C1). |
| And Codex compared with the OpenAI Agents API? | The OpenAI Agents API **is** the Codex harness, run by OpenAI behind an API, with a narrower control surface: no hooks, no per-command approvals, no fork (C2). The **OpenAI Agents SDK is not hosted**: it is a library whose loop runs in your process, the same category as the Claude Agent SDK and Deep Agents. |

## 2. First principles: six layers

Every agent system answers six questions. Most of the confusion between products comes from them covering different layers under similar names.

| # | Layer | Question it answers | Examples |
| --- | --- | --- | --- |
| 1 | **Model** | Who thinks? | Claude Sonnet 5.5, GPT-6 Luna, Grok 4.7 |
| 2 | **Harness** (agent loop) | Who calls the model, runs tools, compacts context and decides when a turn ends? | Claude Code, Codex, Cursor agent, Deep Agents, the Managed Agents loop, the OpenAI Agents SDK runner |
| 3 | **Sandbox** (tool execution) | Where do `bash`, file edits and `git` actually run? | Anthropic cloud sandbox, OpenAI hosted sandbox, Cursor cloud VM, Daytona, Docker on WSL2, your laptop |
| 4 | **Capability configuration** | What does the agent know and what can it touch? | System prompt or instructions, skills, MCP servers, custom/function tools, packages, network policy, secrets, repos, files |
| 5 | **Orchestrator** (macro runtime) | Who strings many agent runs into a durable workflow with retries, waits, approvals and fan-out? | Temporal (Mission Control), Vercel Workflows, the providers' own multi-agent features |
| 6 | **Control plane and records** | How is work triggered, observed, approved, and recorded as authoritative? | Mission Control API, Signal Ingress, PostgreSQL (Supabase), Linear |

**The rule that settles the "extra worker" question:** whoever owns a layer must run compute for it. A managed agent takes layers 2 and 3 off your hands. Layers 5 and 6 remain yours. Layer 5 is cheap when layers 2 and 3 are someone else's.

### 2.1 Where every product sits

| Product | Harness (2) runs at | Tools (3) run at | You must host | Billing | In this packet |
| --- | --- | --- | --- | --- | --- |
| Claude Messages API | You write the loop | Your code | Everything | Anthropic API | — |
| **Claude Code CLI / Claude Agent SDK** | **Your process** | Your machine or your sandbox | Harness + sandbox | API key, or subscription locally | `claude_agent_sdk` (S0 local, S4 Sandbox Host) |
| Claude Code GitHub Action | GitHub runner | GitHub runner | Nothing (GitHub hosts the runner) | API key | Not used; noted in §6 |
| Claude Code cloud sessions and routines | Anthropic | Anthropic | Nothing | **Subscription only** | `claude_cloud` (deferred, SC) |
| **Anthropic Managed Agents, `cloud`** | **Anthropic** | **Anthropic sandbox** | **Nothing** | API key: tokens + $0.08 per running session-hour | `claude_managed` cloud (S2) |
| Anthropic Managed Agents, `self_hosted` | Anthropic | **Your worker** polls a work queue and runs every tool | A tool worker + sandbox | API key | `claude_managed` self_hosted (HL-10) |
| **Codex CLI / app-server** | **Your process** | Your machine or your sandbox | Harness + sandbox | API key or ChatGPT login | `codex` (S0 local, S4 Sandbox Host) |
| Codex cloud | OpenAI | OpenAI | Nothing | **Subscription only** | `codex_cloud` (deferred, SC) |
| **OpenAI Agents API, `openai_hosted`** | **OpenAI (Codex harness)** | **OpenAI sandbox** | **Nothing** | API key: tokens + container rates | `codex_agents` hosted (S3) |
| OpenAI Agents API, `self_hosted` | OpenAI | Your `codex exec-server` | Executor + sandbox | API key | `codex_agents` self_hosted (HL-14) |
| **OpenAI Agents SDK** (incl. "sandbox agents") | **Your process** | Your machine or a sandbox client (Docker, Daytona, E2B, Modal, Vercel…) | Harness + sandbox | API key | Not a lane (C2) |
| **Cursor SDK, `cursor_cloud`** | Cursor | Cursor VM | Nothing | Cursor key | `cursor_cloud` (S1) |
| Cursor SDK, `cursor_local` | Your machine (bridge) | Your machine | Harness | Cursor key | `cursor_local` (S0) |
| **Deep Agents** | **Your process** | Your process or a sandbox | Harness + sandbox | Per model route | `deep_agents` (D7, awaiting brief) |
| Temporal Cloud | — | — | **A worker** for workflow code | Temporal Cloud | Mission Control scheduler (R20) |
| Vercel Functions | — | — | Nothing | Vercel Pro | Signal Ingress, Model Gateway (SPEC-10) |
| Vercel Workflows | — | — | Nothing | Vercel usage | Not used (pattern B, §5) |
| Daytona / Vercel Sandbox | — | Rented sandbox | The harness that drives it | Per vCPU-hour | Sandbox Host (S4) |

**Read the bold rows as two groups.** "Harness runs in your process" (Claude Code, Codex app-server, OpenAI Agents SDK, Deep Agents, `cursor_local`) means you pay for and operate compute before anything runs remotely. "Harness runs at the provider" (Managed Agents cloud, Agents API hosted, `cursor_cloud`) means a single HTTPS call starts remote work. You already have one of the second group in the sprint: `cursor_cloud` is a managed agent in all but name, and S1 builds exactly the pattern that S2 and S3 reuse (HL-04 extracts it as the Remote Session Lane base).

### 2.2 What a "harness" gives you, and what you lose by renting one

| Feature | Claude Code (you run it) | Managed Agents (Anthropic runs it) | Codex app-server (you run it) | Agents API (OpenAI runs Codex) |
| --- | --- | --- | --- | --- |
| Reads `CLAUDE.md` / `AGENTS.md` | Yes | **No**: render it into `system` | Yes | **Yes, once the hosted environment is connected** (HL-23, Q-O2). A turn answered before `environment.ready` does not see it, so still inline critical rules into `instructions` |
| Skills | `.claude/skills`, plugins | Skills API (versioned) + repo root `.claude/skills` | `capability_directories`, plugins | Skills API refs or ZIPs on the environment; plugins |
| Hooks (pre/post tool) | Yes, in-process | **No**: `always_ask` approval or custom tools | Yes, worker-side | **No**: function tools only |
| Per-tool approval | Yes | Allow/deny, durable server-side wait | Per command | Function tools only |
| Subagents | Task tool, `.claude/agents` | `multiagent_20261001` threads and server-run "dynamic workflows" | Yes | `multi_agent` subagents (cannot call function tools) |
| Fork, snapshot | Yes | Emulated | `thread/fork` | Emulated |
| Custom image | Yours | **No** (fixed Ubuntu 24.04 + `packages`) | Yours | **No** in hosted (`self_hosted` for your own image) |
| Infrastructure you run | Harness + sandbox | **None** | Harness + sandbox | **None** |

The trade is plain: renting the harness removes all agent compute and costs you the deep control levers. For **knowledge, research, ingestion and content work**, the rented harness loses almost nothing that matters. For **SDLC work that needs hooks, per-command approval and worktrees**, the self-run harnesses (S0 and S4) remain the right lanes, and that is the expensive part you defer until funding allows.

## 3. Seeding agent configuration and capabilities

Both providers have the same four objects: **agent** (model, instructions, tools, MCP, skills), **environment** (sandbox config), **session** (a running instance) and **events** (in and out). Mission Control's prepare step maps its Cognition Pack and Environment Kit onto them (HL-07, HL-11).

### 3.1 Side by side

| Capability | Anthropic Managed Agents | OpenAI Agents API |
| --- | --- | --- |
| Beta header | `anthropic-beta: managed-agents-2026-04-01`, which the SDK sets. Skills and Files are stable namespaces in `anthropic` 1.13.0 (`client.skills`, `client.files`) and take no beta header | `OpenAI-Beta: agents=v1`, which the SDK sets |
| Instructions | Agent `system` (one string, versioned). Mid-session `system.message` appends. | Saved agent `instructions`, appended to the Codex base instructions |
| Skills | `POST /v1/skills` (`display_name`, `files` under one top directory with `SKILL.md`; + `/versions`), attached on the **agent** `{type: custom, skill_id, version: latest_version_id \| "latest"}`; ≤20 per agent per the current tools docs (not drilled). No `metadata` field. Anthropic `pptx/xlsx/docx/pdf` built in. | `POST /v1/skills` (`files` only; name and description come from `SKILL.md`; no `metadata`), attached on the **environment** as `skills[{type: skill_reference, skill_id, version?}]` (hosted) or `capability_directories` (self-hosted, ≤32); plugins (`.codex-plugin/plugin.json` + `skills/` + `.mcp.json`) as ZIPs |
| MCP | Agent `mcp_servers` (≤20, remote streamable HTTP) + an `mcp_toolset` tool entry; auth only through vault credentials (`mcp_oauth` with refresh, `static_bearer`). Defaults to `always_ask`. | Agent `tools[{type: mcp, server_label, transport{type: http, server_url}}]`; auth through vault credentials |
| Your own tools | `{type: custom, name, description, input_schema}` → `agent.custom_tool_use` → you reply `user.custom_tool_result{custom_tool_use_id, content}` | `{type: function, name, description, parameters}` (`description` is required) → `required_actions[{type: function_call, call_id, turn_id, name, arguments}]` → you reply `agent.session.input.tool_result{turn_id, call_id, success, output}` |
| Built-in tools | `agent_toolset_20260401`: `bash, read, write, edit, glob, grep, web_fetch, web_search`, each with a `permission_policy` | Codex shell and patch; `web_search`; `computer_use`; `programmatic_tool_calling` |
| Environment | `config{type: cloud, networking{type: limited, allowed_hosts, allow_package_managers, allow_mcp_servers}, packages{apt, pip, npm, …}}`. Not versioned. **No setup script, no custom image.** | **Environment template** (setup commands, packages, network allowlist), optional prewarm. Hosted sandbox deleted after 1 h idle. |
| Secrets | Vaults (`display_name`, `metadata`); credentials `{display_name, auth: {type: environment_variable \| static_bearer \| mcp_oauth, …}}`. An `environment_variable` is substituted at egress, cloud only, and its `networking.allowed_hosts` must also be reachable from the environment, or the session reports `credential_host_unreachable_error` | Vaults at `/v1/agents/vaults` (`name`, `metadata`); credentials `{name (required), auth: {type: environment_variable \| static_bearer \| mcp_oauth, …}}`; `environment_variable` hosted only |
| Repos | `github_repository` session resource with a PAT, branch or commit checkout (github.com only) | Upload files to the environment, or clone in a setup command |
| Files in / out | Files API → `/mnt/session/uploads` (read-only); outputs in `/mnt/session/outputs` | Environment files in; `/workspace/outputs` published as artifacts per turn |
| Memory | Memory stores mounted at `/mnt/memory/` (≤8 per session) | — |
| Multi-agent | `multiagent_20261001`: ≤20 predefined agents, ≤25 threads, server-run dynamic workflows (24 h default lifetime), advisor model | `multi_agent{enabled, max_concurrent_subagents}` |
| Grading | `user.define_outcome` (rubric, separate grader context) | — |
| Budgets | `budget{type: limit, max_list_cost{amount: "<cents>", currency: "USD"}}` hard cap, set at create; `list_cost` is reported in whole cents | `spend_control` is absent from the SDK 3.29.0 session model; how to set it is unverified (Q-O4). Session `usage` was `null` in the smoke; per-turn usage comes from `turns.list` |
| Scheduling | **Deployments**: cron per agent, ≤1,000 per org | — |
| Webhooks | Console-registered; ≤3 attempts, then dropped | Project settings; retried for 72 h |
| Data | Not ZDR, not HIPAA BAA | Not ZDR, US residency only |

### 3.2 Anthropic: seed once, run many

```python
from anthropic import Anthropic

client = Anthropic()  # ANTHROPIC_API_KEY from the Secret Broker; SDK sets the Managed Agents beta header

skill = client.skills.create(                                    # stable namespace, no beta header
    display_name="cited-report",
    files=[("cited-report/SKILL.md", skill_md, "text/markdown"), ...],  # one top directory
)
vault = client.beta.vaults.create(display_name="mc-knowledge", metadata={"mc_pack": pack_digest})
client.beta.vaults.credentials.create(
    vault.id,
    display_name="knowledge-mcp",
    auth={"type": "static_bearer", "mcp_server_url": "https://<knowledge-services>/mcp", "token": ...},
)

agent = client.beta.agents.create(
    name="mc-knowledge-researcher",
    model="claude-sonnet-5-5",
    system=rendered_agents_md + mission_overlay,          # Managed Agents does not read AGENTS.md
    tools=[
        {"type": "agent_toolset_20260401",
         "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
         "configs": [{"name": "bash", "permission_policy": {"type": "always_ask"}}]},
        {"type": "mcp_toolset", "mcp_server_name": "knowledge"},
        {"type": "custom", "name": "mc_signal", "description": "...", "input_schema": {...}},
    ],
    mcp_servers=[{"type": "url", "name": "knowledge", "url": "https://<knowledge-services>/mcp"}],
    skills=[{"type": "custom", "skill_id": skill.id, "version": skill.latest_version_id}],
    metadata={"mc_pack": pack_digest},
)

env = client.beta.environments.create(
    name=f"mc-knowledge-{kit_digest[:8]}",
    config={
        "type": "cloud",
        "networking": {"type": "limited", "allowed_hosts": ["<ingress>.vercel.app"],
                       "allow_package_managers": True, "allow_mcp_servers": True},
        "packages": {"pip": ["pypdf", "pandas"]},
    },
    metadata={"mc_kit": kit_digest},
)

session = client.beta.sessions.create(
    agent={"type": "agent", "id": agent.id, "version": agent.version},
    environment_id=env.id,
    vault_ids=[vault.id],
    budget={"type": "limit", "max_list_cost": {"amount": "300", "currency": "USD"}},  # cents
    metadata={"mc_run": run_id, "mc_unit": unit_id},
    initial_events=[{"type": "user.message", "content": [{"type": "text", "text": packet_prompt}]}],
)
```

Agents, skills, vaults and environments are **created once and reused by id**. Each mission then costs one `sessions.create`. Anthropic's `ant apply` CLI can manage the same objects as version-controlled files with a lock file, which is a usable stopgap before HL-07 lands.

### 3.3 OpenAI: same shape, skills on the environment

```python
from openai import OpenAI

client = OpenAI()  # OPENAI_API_KEY: a restricted project key (OA1); SDK sets OpenAI-Beta: agents=v1

agent = client.beta.agents.create(
    model="gpt-6-luna",                                 # accepted by the Agents API (HL-23)
    name="mc-knowledge-researcher",
    instructions=critical_repo_rules + mission_overlay,
    tools=[
        {"type": "mcp", "server_label": "knowledge",
         "transport": {"type": "http", "server_url": "https://<knowledge-services>/mcp"}},
        {"type": "function", "name": "mc_signal", "description": "...", "parameters": {...}},
        {"type": "web_search"},
    ],
    multi_agent={"enabled": False},                     # subagents cannot call function tools
    metadata={"mc_pack": pack_digest},
)

session = client.beta.agents.sessions.create(
    agent_id=agent.id,
    environment={"type": "openai_hosted", "environment_template_id": template.id,  # or inline fields
                 "skills": [{"type": "skill_reference", "skill_id": skill.id, "version": skill_version}]},
    vault_ids=[vault.id],
    metadata={"mc_run": run_id},
)                                                       # created idle; open the stream, then send
client.beta.agents.sessions.events.create(
    session.id,
    events=[{"type": "agent.session.input.message",
             "input": [{"role": "user", "content": [{"type": "input_text", "text": packet_prompt}]}]}],
    idempotency_key=intent_key,
)
```

## 4. How the pieces talk at run time

```text
           trigger (you, Linear, a schedule, another agent)
                              │
                              ▼
 ┌──────────────── Vercel (already Pro, SPEC-10) ────────────────┐
 │ Signal Ingress: verifies callers, writes inbox rows (Postgres) │◄── provider webhooks
 │ + proposed launch-request route (§8, R-NEW-1)                  │    (Anthropic, OpenAI, Cursor)
 └──────────────────────────────┬─────────────────────────────────┘
                                │ inbox rows (Supabase Postgres)
                                ▼
 ┌──── lane-only worker (MO-63): WSL2 now; small container or Temporal Serverless Worker later ────┐
 │ IngressDrainer → admit mission / signal workflow ("ingress_wake")                               │
 │ Temporal workflow code + lane activities: start session, send event, reconcile, answer mc_* tools│
 └───────┬───────────────────────────────────────────────┬──────────────────────────────────────────┘
         │ workflow state                                │ HTTPS only (no sandbox, no CLI)
         ▼                                               ▼
   Temporal Cloud (R20)                Anthropic Managed Agents · OpenAI Agents API · Cursor cloud
   mission-control-dev.ih0e7           (the harness and the sandbox run here, for minutes or hours)
```

**Why the worker can be tiny.** Every activity is a short HTTPS call: create a session, send an event, list events since a cursor, answer a custom tool. Long waits are **workflow waits** (a signal from a provider webhook or a timer that triggers a reconcile), not long-running activities. While a session runs at the provider, the worker does nothing and holds nothing. If the worker stops, for example when your laptop sleeps, **the provider session keeps running**. Sessions are server-side and `reattach` is native on all three hosted lanes, so the workflow reconciles from the provider's history when the worker returns. The one exception: a session waiting on an `mc_*` custom tool answer stays parked in `requires_action` until the worker answers. That costs nothing, because Managed Agents bills runtime only while `running`.

**Webhook caveat.** Anthropic retries a webhook at most three times and then drops it, and a webhook payload carries only `type` and `id`. Webhooks are therefore wake-ups only. A timer-driven reconcile (for example every 10 minutes) is the safety net, as SPEC-06 §3 already requires.

## 5. Three ways to compose managed agents

| | **A. Provider-native** | **B. Vercel Workflows** | **C. Temporal + thin worker (Mission Control)** |
| --- | --- | --- | --- |
| Macro runtime | The provider: one session with multi-agent threads, Outcomes, or a cron Deployment | Vercel Workflows (`"use workflow"` / `@wf.workflow`, TypeScript or Python) | Temporal Cloud |
| Worker to deploy | None | None | One small worker (or a Temporal Serverless Worker) |
| Multi-provider in one workflow | No | Yes | Yes |
| Durable approvals and waits | Inside one session only | `createHook`, `createWebhook`, `sleep` | Signals, timers, Human Tasks |
| Records and acceptance | Provider history only | Vercel run log + whatever you write | Mission Control reducers, frames, custody, Completion Contracts |
| Fits ADR-0004 (Temporal sole scheduler) | Yes, as one lane turn | **No**: a second scheduler | Yes |
| Time to first remote run | Hours | Days | The sprint's S2/S3 critical path (§8) |
| Best for | One large research task; a nightly job | A standalone "remote runs" service, if Mission Control is not ready | The long-term system |

### A. Provider-native, no orchestrator

One Managed Agents session can already run a multi-step job: `multiagent_20261001` gives up to 20 predefined subagents and server-run dynamic workflows, `user.define_outcome` adds a grader loop, and a **Deployment** runs an agent on a cron. A Vercel route that calls `sessions.create`, plus a webhook route that records the result, is a complete remote system. Its limits are a single provider per workflow, no cross-session state of your own, and acceptance that lives only in the provider's transcript. Inside Mission Control, this pattern is still useful as **one lane turn** with `multiagent` turned on for read-only knowledge missions (SPEC-06 keeps it off for code).

### B. Vercel Workflows, no worker

```ts
// app/workflows/research.ts: a sketch, not a proposal for the Mission Control repo
import { createHook, sleep } from "workflow";

export async function research(topic: string) {
  "use workflow";
  const sid = await startManagedSession(topic);                 // "use step": sessions.create
  for (;;) {
    const wake = createHook<{ type: string }>({ token: sid });  // the provider-webhook route calls resumeHook(sid, body)
    await Promise.race([wake, sleep("10m")]);                   // webhook, or a reconcile timer
    const state = await reconcileSession(sid);                  // "use step": retrieve + list events
    if (state.toolCalls.length) await answerTools(sid, state.toolCalls);
    if (state.done) break;
  }
  const review = await startOpenAISession(await collectOutputs(sid));  // next stage, other provider
  return await waitForSession(review);
}
```

This is the fastest route to multi-step, multi-provider remote workflows with **nothing to deploy beyond your existing Vercel Pro project**. Its cost is architectural: it creates a second durable runtime and a second record store beside Mission Control. Use it only as a deliberately separate, disposable service, and never as a second scheduler inside Mission Control.

### C. Temporal + thin worker (the sprint's design)

Mission Control already expresses this: a mission's lane turn is `lane.turn` / `lane.status` / `lane.cancel` activities on a lane task queue (SPEC-09 §3), provider webhooks become `ingress_wake` signals through the drainer (SPEC-10 §4), and reducers, not executions, decide acceptance. The worker-hosting choices, cheapest first:

| Worker placement | Monthly cost | Notes |
| --- | --- | --- |
| Your WSL2 machine (S0 already targets it) | $0 | Agents keep running at the provider while the machine sleeps. Orchestration resumes when it wakes. |
| **Temporal Serverless Worker on GCP Cloud Run** | Near $0 when idle | Listed in Temporal's docs with a Python guide. Temporal resizes a pool of long-lived instances and **scales it to zero** with no work. Its release stage is not stated on the page read; confirm before relying on it. |
| Temporal Serverless Worker on AWS Lambda | Near $0 when idle | Public preview since July 2026. 15-minute invocation limit, fine for short HTTP activities; no persistent connection per invocation. |
| A small always-on container (Fly.io, Railway, Render, a VM) | Single-digit to low double-digit dollars | Simplest mental model; needs the slim lane-only image (MO-63). |

**Design rule that keeps every option open:** activities stay short and idempotent (keyed by Operation Intent on `(session, event or tool_use id)`), and long waits are workflow-level. SPEC-06 already requires this. It is also what lets a serverless worker work at all.

## 6. Cost from first principles

| Item | What you pay | Source |
| --- | --- | --- |
| Managed Agents session runtime | **$0.08 per session-hour, only while `running`** (idle and waiting are free), plus tokens at list price; web search $10 per 1,000 | research/anthropic-managed-agents.md §7 |
| OpenAI Agents API | Tokens at model rates; hosted sandboxes at standard container rates | Agents API overview (Pricing) |
| Cursor cloud | Cursor usage | SPEC-07 |
| Temporal Cloud | Already provisioned (R20); cost scales with workflow actions | R20 |
| Orchestrator worker | $0 to low double digits per month (§5 C) | — |
| Vercel | Already on Pro (R17) | R17 |
| **Deferred** (self-run harnesses on rented compute) | Daytona about $0.17/h for 2 vCPU / 4 GiB, plus the Model Gateway, images and the Sandbox Host adapters | SPEC-06 §12.1 |

Example: one hour of `claude-sonnet-5-5` Managed Agents research costs $0.08 of runtime plus that hour's tokens. The infrastructure part of a remote knowledge mission is therefore cents, and the model tokens dominate.

**Zero-infrastructure option for real Claude Code:** the Claude Code GitHub Action runs the full Claude Code harness on GitHub's runners with an API key. For a repo-scoped SDLC task triggered by an issue or PR comment, that is real Claude Code remotely without deploying anything. It is not a Mission Control lane today. Record it as an option for the SDLC side while S4 is unfunded.

## 7. Fastest path to running workflows remotely

Each step is useful on its own, and none of them throws work away.

1. **Provider smoke (hours, about $1).** One script per provider, using the keys already in `mission-control/.env`:
   - create a skill, a vault, an agent and an environment;
   - start a session, stream it, answer one custom/function tool, interrupt it, read usage, delete it.

   **Done (HL-23, 2026-10-12):** [research/provider-smoke-2026-10.md](research/provider-smoke-2026-10.md). The Agents API accepts `gpt-6-luna`. Q-M1: a `user.message` sent while `running` is injected at the next model request of the same turn. Q-O2: the Agents API honours a workspace `AGENTS.md` once the hosted environment is connected. The §3 shapes above were corrected to the confirmed field names.
2. **Capability packs as files.** Put one knowledge Cognition Pack and one Environment Kit for each provider into the repo as declarative files. A small sync script (or `ant apply` for Anthropic) creates or updates agents, skills, environments and vaults keyed by digest. This is the minimal core of HL-07 and HL-11, before the full MO-30 projection.
3. **Lanes on Temporal, worker local.** Build `claude_managed` cloud (HL-08, HL-09) and `codex_agents` hosted (HL-12, HL-13) on the HL-04 base, passing HL-05. Run them on the **lane-only worker (MO-63)** on WSL2 against **Temporal Cloud** (MO-67). From here, missions run remotely: the agents execute in the providers' clouds and survive your laptop sleeping.
4. **Remote trigger.** Deploy the Signal Ingress (MO-40, MO-74, MO-75) and register the provider webhooks (HL-17). Add one **launch-request route** (R-NEW-1, §8) so a phone, Linear or another agent can request a mission without reaching the local operator API.
5. **Lift the worker off the laptop** only when you want orchestration to continue while the machine is off: a Temporal Serverless Worker on Cloud Run, or a small container (R-NEW-2).
6. **Later, as funding allows:** the self-hosted placements and the real harnesses on rented compute (HL-01–03, HL-10, HL-14–16, Deep Agents). These are the "deploy deep agents and workers" items, and nothing in steps 1–5 depends on them.

**If you need remote runs before step 3 lands,** use pattern A (one session triggered from a Vercel route) for single large tasks. Build pattern B only as a separate, disposable service, and only after deciding that a second runtime is worth it.

## 8. Cross-reference with this sprint

### 8.1 Where the question and the plan already agree

| Owner's question | What the packet already says | Verdict |
| --- | --- | --- |
| Call managed agents from a deployed server | `claude_managed` and `codex_agents` are lanes (SPEC-06, R3, R4); Vercel serves the ingress and webhooks (SPEC-10, R11, HL-17) | Aligned |
| Temporal as the macro runtime | ADR-0004; Temporal Cloud namespaces exist (R20); MO-67 qualifies them | Aligned |
| Seed skills, MCP, environments and secrets | HL-07 (agents, skills, environments, vaults), HL-11 (saved agents, templates, prewarm, vaults), MO-30 (cognition projection), MO-12 (Environment Kits), MO-11 (Secret Broker → `provider_vault`) | Aligned, but heavy (8.3) |
| Managed Agents is not Claude Code; the Agents API is a closed Codex | Corrections C1, C2 | Aligned |
| Biotech data on hosted APIs | C3, SPEC-06 §8, HL-18: PHI and secret-bearing missions are refused | Aligned. Remote biotech work must be `public` or `internal`. |

### 8.2 Gaps the question exposes

| # | Gap | Evidence | Proposed fix |
| --- | --- | --- | --- |
| G-R1 | **No remote way to start a mission.** The operator API is local-only. Its public hosting is SPEC-10 phase 3, out of scope, and Vercel must hold no Temporal credentials (SPEC-10 §7). | SPRINT "Out of scope"; SPEC-10 §1, §7 | **R-NEW-1:** a launch-request ingress route. It authenticates the owner, writes an `admission_request` inbox row, and the IngressDrainer admits it through the normal application handler. Vercel still decides nothing. |
| G-R2 | **No decision on where the worker lives off the laptop.** Only WSL2 (S0) and Daytona (for sandboxes) are named. | SPEC-09 §3; DECISIONS D5 | **R-NEW-2:** keep WSL2 for the sprint. Qualify one off-machine worker placement for the lane-only role, recommended: Temporal Serverless Worker on Cloud Run (preview), with a small container as fallback. Needs the slim image that MO-63 implies. |
| G-R3 | **The hosted lanes wait on the S1 foundations.** HL-07 and HL-11 depend on MO-30 and MO-11; HL-09 and HL-13 on MO-14; S2/S3 are scheduled after S1 in wave C. | PLAN critical paths; ISSUES wave C | **R-NEW-3:** allow a minimal prepare from checked-in pack files (§7 step 2) so S2/S3 cloud can start in parallel with S1. The full MO-30 projection replaces it later. |
| G-R4 | **The provider-native composition (pattern A) is unnamed.** SPEC-06 turns `multiagent` off by default and does not use Outcomes or Deployments. | SPEC-06 §4.2 | Declare, for read-only knowledge missions, `multiagent` on and `user.define_outcome` as evidence (never acceptance). Map MA Deployments to Mission Control schedules later, not now. |
| G-R5 | **The "do it later" bucket is not labelled as such.** S4 and the self-hosted placements carry most of the infrastructure cost. | PLAN wave D | **R-NEW-4:** when the owner wants to save money, wave D (HL-01–03, HL-10, HL-14–16) moves to `deferred` without blocking S2/S3 cloud. Only HL-20's dependency list changes. |

### 8.3 Proposed decisions (owner to accept or reject)

| # | Decision | Effect if accepted |
| --- | --- | --- |
| R-NEW-1 | Add the launch-request ingress route. | One new issue (Events, size S, after MO-40 and MO-75). SPEC-10 §2 gains a row. |
| R-NEW-2 | Remote orchestration uses the lane-only worker; qualify a Temporal Serverless Worker (Cloud Run, or Lambda if Cloud Run is not yet available to the account) as its off-machine placement after S0. | One new issue (Runtime, size M, after MO-63 and MO-67). DECISIONS D5 notes the placement. |
| R-NEW-3 | Allow a minimal file-based prepare for `claude_managed` cloud and `codex_agents` hosted. | HL-07 and HL-11 split into "minimal" (wave B) and "full projection" (wave C). S2/S3 cloud drills can run before S1. |
| R-NEW-4 | Mark wave D as the funding-gated bucket. | No change now. If invoked, HL-10, HL-14, HL-15, HL-16, HL-01–03 become `deferred`, and HL-20 drops them. |
| R-NEW-5 | Vercel Workflows is not used inside Mission Control. A separate pattern B service needs its own decision. | Keeps ADR-0004 intact. |

When accepted, `generate_issues.py` gains the new issues and the dependency edits, and [SPRINT](SPRINT.md), [PLAN](PLAN.md) and [DECISIONS](DECISIONS.md) are updated to match. None of these changes has been applied yet.

## 9. Glossary for this page

- **Harness:** the program that runs the agent loop (calls the model, runs tools, manages context). Examples: Claude Code, Codex, Deep Agents.
- **Managed agent:** a harness plus a sandbox that a provider runs for you behind an API (Anthropic Managed Agents, the OpenAI Agents API, Cursor cloud agents).
- **Agent SDK:** a library that runs a harness inside your process (Claude Agent SDK, OpenAI Agents SDK). It is not hosted.
- **Sandbox:** the machine where tool calls execute.
- **Orchestrator worker:** the process that runs Temporal workflow and activity code. Temporal Cloud stores history but never runs this code.
- **Agent-compute worker:** a machine that runs a harness or sandbox. Managed agents remove the need for one.
