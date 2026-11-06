---
type: Research Note
title: "Anthropic Managed Agents fact sheet: hosted harness, API surface and lane mapping (read 2026-10-12)"
description: "API-key-billed Anthropic surfaces: harness identity (not Claude Code), agents/environments/sessions/events/vaults/skills/files API, cloud vs self-hosted sandboxes, lifecycle, pricing, owner steps and Mission Control lane implications."
tags: [mission-control, research, materialization-observation]
---

# Anthropic hosted agent surfaces (API-key billed): fact sheet

I read everything below on 2026-10-12 from official sources only. There was no login and no paid call. Pages were fetched as `.md` from
platform.claude.com, which is the canonical host; docs.anthropic.com and docs.claude.com redirect there. Raw copies were kept in a session scratchpad (not retained)
under `research2/raw/` and are not for the repo. The docs pages carry no dates, so the date of each claim is the read date.

Abbreviations: **MA** = `https://platform.claude.com/docs/en/managed-agents/`; **API** = `https://platform.claude.com/docs/en/api/beta/`;
**CC** = `https://code.claude.com/docs/en/`; **ENG** = https://www.anthropic.com/engineering/managed-agents (Apr 08, 2026).
VERIFIED means I quoted or paraphrased it from the cited page. UNVERIFIED means a primary source does not state it, or I inferred it.

## Version pins (2026-10-12)

| Artifact | Version / date | Source |
| --- | --- | --- |
| MA beta header | `managed-agents-2026-04-01` (all MA endpoints; SDK sets it) | MA+overview |
| Agent toolset type | `agent_toolset_20260401` | MA+tools |
| Multiagent type | `multiagent_20261001` | MA+agent-setup |
| `anthropic` (Python SDK) | 1.13.0, uploaded 2026-10-09T15:29Z | https://pypi.org/pypi/anthropic/json |
| `ant` CLI | v1.40.0, 2026-10-09T15:51Z (`ant beta:sessions connect` needs ≥1.32.0) | https://github.com/anthropics/anthropic-cli/releases ; https://platform.claude.com/docs/en/cli-sdks-libraries/cli/sessions-connect |
| `claude-agent-sdk` (Python) | 0.2.165, 2026-10-08T18:18Z | https://pypi.org/pypi/claude-agent-sdk/json |
| `@anthropic-ai/claude-code` | latest/next 2.1.296 (2026-10-09T16:58Z), stable 2.1.287 | https://registry.npmjs.org/@anthropic-ai/claude-code |
| Claude Code CHANGELOG head | 2.1.296. MA appears only through the `/claude-api` skill (e.g. `/claude-api managed-agents-onboard`) | https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md |

---

## 1. Harness identity

### Verdict
**Managed Agents runs Anthropic's own hosted harness. It is not the Claude Code CLI or the Claude Agent SDK, you cannot swap it, and it is not "Claude Code as a service."** Evidence:

- MA describes itself as a "Pre-built, configurable agent harness that runs in managed infrastructure". The harness "supports built-in prompt caching, compaction, and other performance optimizations" (MA+overview).
- ENG (Apr 2026) calls MA "a meta-harness … unopinionated about the specific harness". It also says "Claude Code is an excellent harness that we use widely … Managed Agents can accommodate any of these". That statement is about the architecture. The public API has no field to choose a harness: `POST /v1/agents` accepts only `name, model, system, tools, mcp_servers, skills, multiagent, description, metadata` (API+agents/create). VERIFIED absence.
- The migration guide treats MA and the Agent SDK as different products. "the SDK runs in a process you operate, while Managed Agents runs in Anthropic's infrastructure". `system_prompt` and "the `CLAUDE.md` hierarchy" become "A single `system` string on the Agent". `PreToolUse`/`PostToolUse` hooks become client logic or `always_ask`. Plan mode, output styles and slash commands "move to your client". `max_turns` is counted client-side (MA+migration).
- The Agent SDK hosting page says: "If you don't need to run the agent loop itself on your own infrastructure, consider Managed Agents … Anthropic hosts the agent loop" (CC+agent-sdk/hosting).
- Branding rules forbid presenting an MA product as "Claude Code" (MA+reference, Branding).

### What the MA harness has
- **Built-in tools** (`agent_toolset_20260401`): `bash`, `read`, `write`, `edit`, `glob`, `grep`, `web_fetch`, `web_search`. Each can be toggled or configured through `default_config`/`configs`. Output over 100,000 chars is spilled to a sandbox file (MA+tools). The names match Claude Code tools, but there is **no Task/Agent tool, TodoWrite, NotebookEdit, plan mode, hooks, CLAUDE.md/AGENTS.md loading, `.claude/agents`, `.claude/settings.json`, `.mcp.json`, plugins, or slash commands**. My grep across all 37 MA pages found no CLAUDE.md or AGENTS.md loading. VERIFIED absence in docs.
- **Repo skills**: a mounted GitHub repo's root `.claude/skills/<name>/SKILL.md` is discovered once at session start (cloud only). Nested `.claude/skills` dirs are not announced (MA+skills).
- **Subagents** are not a Task tool. They are configured with `multiagent_20261001`: subagents (persistent session threads, up to 20 predefined agents, at most 25 child threads), "dynamic workflows" (server-run programs of many agents; run lifetime 24 h default), and an `advisor` model. All threads share one sandbox and filesystem (MA+multiagent-orchestration, MA+session-threads, MA+workflow-runs).
- **Compaction**: automatic and server-side. It is visible as the `agent.thread_context_compacted` event and you cannot configure it (MA+reference). `max_tokens` and `thinking` "are handled by the Claude Managed Agents runtime. These fields are not exposed" (MA+migration). `effort`, `speed` (fast) and `inference_geo` are set on the `model` object (MA+agent-setup).

### Can we bring Claude Code or the Agent SDK into an MA sandbox?
- **Documented: no.** No page describes it. **Technically plausible, UNVERIFIED.** You would add `packages: {npm: ["@anthropic-ai/claude-code"]}` (allowed: npm is in the package-manager host list) and put `api.anthropic.com` in `allowed_hosts`. You would supply `ANTHROPIC_API_KEY` as a vault `environment_variable` credential: the placeholder is substituted at egress in the header, and "clients that validate the credential format at startup may reject it" (MA+vaults). The outer MA agent then has to run `claude -p` through its `bash` tool. Cloud bash timeouts are undocumented, and background processes do not survive idle checkpoints (UNVERIFIED). Costs: you pay twice for model tokens (the outer MA loop and the inner CLI), MA cannot observe the inner loop, and the docs say nothing about whether this violates terms. **Not recommended.**
- **Anthropic code-execution containers** (Messages API `code_execution_*`) cannot host the Agent SDK. "The container has no internet access" (https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool). VERIFIED.

### "Claude Code as a service" on an API key: what exists
| Surface | Harness | API key? | Hosted by Anthropic? | Source |
| --- | --- | --- | --- | --- |
| Claude Agent SDK / `claude -p` in **any container you run** | Claude Code (full: hooks, CLAUDE.md, skills, subagents, worktrees) | **Yes**; "Developers building products … should use API key authentication through Claude Console" | No: you host it. SDK hosting doc lists sandbox-as-a-service providers and Docker, gVisor or Firecracker | CC+agent-sdk/hosting, CC+legal-and-compliance |
| Claude Code GitHub Actions (`anthropics/claude-code-action@v1`) | Claude Code CLI on GitHub runners | **Yes** (`anthropic_api_key`) or `claude_code_oauth_token` | No (GitHub-hosted runner) | CC+github-actions |
| Claude Code cloud sessions (`env_`) and routines | Claude Code | **No**: "Cloud sessions always use your subscription credentials" | Yes | CC+authentication, prior note |
| Claude Code self-hosted environments (`ccpool_`) | Claude Code on your runners | **No**: claude.ai Team/Enterprise public beta, session-scoped OAuth token, consumes Claude Code plan usage | Control plane only | CC+self-hosted-environments |
| **Managed Agents** (cloud or self-hosted sandbox) | **MA harness (not Claude Code)** | **Yes** (only API key; Console billing) | Loop always; tools in cloud or on your worker | MA+overview |

**For the owner's hope ("they supply their harnesses outright so we can customize the coding work").** Anthropic supplies the Claude Code harness only as software you run yourself: the CLI or Agent SDK, which accept API-key billing in any container. This is the existing `claude_agent_sdk` lane. The only hosted, API-billed harness is MA, and its loop cannot be customized beyond configuration. The closest middle ground is an MA **self-hosted sandbox**, described in section 3b. Anthropic runs the loop, and **our worker executes every built-in tool call in our own filesystem**. That gives us full control of repo, worktrees, processes and pre/post tool interception, but not of the loop itself.

---

## 2. Full MA API surface

Base `https://api.anthropic.com`. Headers: `x-api-key`, `anthropic-version: 2023-06-01`, `anthropic-beta: managed-agents-2026-04-01`. The Files API also needs `files-api-2025-04-14`, and the Skills API `skills-2025-10-02` (https://platform.claude.com/docs/en/build-with-claude/files, …/skills-guide). The Python namespace is `client.beta.*`, with methods taken from `anthropic-sdk-python` `main` `src/anthropic/resources/beta/**`. Rate limits per org: **create endpoints 300 rpm, read endpoints (retrieve, list, stream) 1,200 rpm**, plus org spend and tier limits (MA+reference, https://platform.claude.com/docs/en/api/rate-limits).

**Pagination**: `limit`, opaque `page` cursor, `next_page`. Only `GET /v1/sessions` also has `prev_page`. Cursors encode `order` (https://platform.claude.com/docs/en/api/overview#pagination, MA+session-operations).
**Idempotency**: **none**. No idempotency-key field or header is documented on any MA create, and the Python client's `_idempotency_header = None` (sdk `_base_client.py`). The SDK retries POSTs by default, so create is at-least-once. Reconcile with `metadata` plus list filters (`agent_id`, `created_at[...]`, `statuses`). The session list has no metadata filter, so metadata must be matched client-side. VERIFIED absence.

| Resource | Endpoints (method path) | Python | Key fields / notes |
| --- | --- | --- | --- |
| Agents | `POST /v1/agents`; `GET /v1/agents`; `GET/POST /v1/agents/{id}`; `POST /v1/agents/{id}/archive`; `GET /v1/agents/{id}/versions` | `agents.create/list/retrieve/update/archive`, `agents.versions.list` | `name`, `model` (id or `{id, effort, speed, inference_geo}`), `system`, `tools` (≤128 entries), `mcp_servers` (≤20), `skills`, `multiagent`, `description`, `metadata`. Versioned: an update with `version` gives optimistic concurrency (409 on mismatch); without it, last write wins; no-op updates make no new version. Archive is irreversible (MA+agent-setup) |
| Environments | `POST/GET /v1/environments`; `GET/POST/DELETE /v1/environments/{id}`; `POST …/archive` | `environments.create/list/retrieve/update/delete/archive` | `name`, `config` = `{type:"cloud", networking, packages}` or `{type:"self_hosted"}`, `description`, `metadata`, `scope`. **Not versioned.** Delete only if no session references it (MA+environments, API+environments/create) |
| Env work queue (self-hosted) | `GET …/work/poll`, `GET …/work`, `GET/POST …/work/{work_id}`, `POST …/work/{id}/ack`, `…/heartbeat`, `…/stop` (`force`), `GET …/work/stats` | `environments.work.*`, `work.poller()`, `work.worker()` | Lease heartbeat (default 30 s, TTL ~90 s, per SDK `_worker.py`). Auth with an environment key (Console-generated) or org API key (MA+self-hosted-sandboxes-operations) |
| Sessions | `POST/GET /v1/sessions`; `GET/POST/DELETE /v1/sessions/{id}`; `POST …/archive` | `sessions.create/list/retrieve/update/delete/archive` | Create: `agent` (string / `{type:"agent",id,version}` / `{type:"agent_with_overrides", …}`), `environment_id`, `resources[]` (github_repository, file, memory_store), `initial_events` (≤50; user.message or user.define_outcome), `vault_ids`, `budget`, `title`, `metadata`. Object fields: `status` (`idle, running, rescheduling, terminated`), `usage`, `stats`, `outcome_evaluations`, `resources`, `agent` (resolved snapshot), `deployment_id`. List filters: `agent_id`, `agent_version`, `deployment_id`, `memory_store_id`, `statuses[]`, `created_at[gt/gte/lt/lte]`, `include_archived`, `order`. Update: `agent.tools`/`agent.mcp_servers` (idle only), `budget`, `metadata`, `title`, `vault_ids` (API+sessions/*) |
| Events | `POST /v1/sessions/{id}/events`; `GET …/events` (list); `GET …/events/stream` (SSE, opt-in `event_deltas` for `agent.message`/`agent.thinking`) | `sessions.events.send/list/stream/tool_runner` | List filters: `types[]`, `created_at[...]`, `order`, `page`, `limit`. Events carry `id` and `processed_at`, but **no sequence number**. The stream delivers only events after connect; **there is no `Last-Event-ID` resume** (MA+events-and-streaming) |
| Threads | `GET …/threads`; `GET …/threads/{tid}`; `POST …/threads/{tid}/archive`; `GET …/threads/{tid}/events`; `GET …/threads/{tid}/stream` | `sessions.threads.list/retrieve/archive`, `threads.events.list/stream` | Per-agent context-isolated threads. `statuses[]` filter (MA+session-threads) |
| Session resources | `POST …/resources` (add: **file only**); `GET …/resources`; `GET/POST/DELETE …/resources/{rid}` | `sessions.resources.add/list/retrieve/update/delete` | Repos are fixed for the session's lifetime; only token rotation is allowed. Memory stores attach at create only (MA+github, MA+memory) |
| Vaults / credentials | `/v1/vaults` CRUD + archive; `/v1/vaults/{id}/credentials` CRUD + archive + `…/mcp_oauth_validate` | `vaults.*`, `vaults.credentials.*` | Credential types `mcp_oauth` (with refresh), `static_bearer`, `environment_variable` (`secret_name`, `networking`, `injection_location {header, body}`). ≤20 credentials per vault. Workspace-scoped. Secrets write-only (MA+vaults) |
| Files | `POST/GET /v1/files`, `GET /v1/files/{id}`, `GET …/content`, `DELETE` | `beta.files.upload/list/retrieve_metadata/download/delete` | Mount as `file` resources (≤500 per session) at `/mnt/session/uploads/…`, read-only. Agent outputs go to `/mnt/session/outputs/` and are listed with `scope_id=sesn_…` (MA+files) |
| Skills | `POST/GET /v1/skills`, `GET/DELETE /v1/skills/{id}`, `POST/GET /v1/skills/{id}/versions`, `GET/DELETE …/versions/{v}`, `GET …/versions/{v}/content` | `skills.*`, `skills.versions.*` | A directory with `SKILL.md`, uploaded as zip or files, max 30 MB uncompressed. Attach `{type: anthropic\|custom, skill_id, version\|latest}`; ≤500 per session (MA+skills, skills-guide) |
| Memory stores | `/v1/memory_stores` CRUD + archive; `…/memories` CRUD; `…/memory_versions` list/retrieve/redact | `memory_stores.*` | Mounted at `/mnt/memory/<store>/`. ≤8 per session. 100 kB per memory, 10,000 memories per store. Versions retained 30 days (MA+memory) |
| Outcomes | `user.define_outcome` event (`description`, rubric text or file, `max_iterations`) | events.send | Separate grader context. `span.outcome_evaluation_*` events. Result `satisfied / needs_revision / max_iterations_reached / failed / interrupted` (MA+define-outcomes, MA+reference) |
| Deployments (cron) | `POST/GET /v1/deployments`, `GET/POST /v1/deployments/{id}`, `…/pause`, `…/unpause`, `…/run`, `…/archive` | `deployments.*`, `deployment_runs` | POSIX cron + IANA timezone, minute granularity. Jitter up to 15% of the interval (5 s min, 9 min max). ≤1,000 per org. Per-run budget (MA+scheduled-deployments) |
| Webhooks | **No management API.** Endpoints are registered in Console (Manage > Webhooks). `client.beta.webhooks.unwrap()` verifies | `webhooks.unwrap/parse_unverified` | Standard-webhooks headers (`webhook-id`, `-timestamp`, `-signature`), `whsec_` secret shown once. The payload carries only `type` and `id`. ≤3 attempts with 5–120 s backoff, then dropped. Unordered, may duplicate. 3xx or a non-public IP auto-disables the endpoint (MA+webhooks) |
| Dreams | `client.beta.dreams` (research preview, request access) | — | Out of scope (MA+dreams, MA+overview) |

**CLI**: `ant beta:sessions connect <id> [--web]` gives an interactive follow, steer and approve view. For scripts, use `ant beta:sessions:events stream|send`. `ant apply` manages agents, environments, vaults, skills and deployments as version-controlled files plus `claude-lock.json` (https://platform.claude.com/docs/en/cli-sdks-libraries/cli/sessions-connect, MA+skills, MA+vaults).

---

## 3. Environments

### 3a. Cloud (`type: "cloud"`), per MA+environments, MA+cloud-sandboxes-reference, API+environments/create
- **Image**: fixed. Ubuntu 24.04 LTS, x86_64. Python 3.10–3.13 (pip, uv, poetry); Node 20/21/22; Go 1.24/1.25; Rust; Java 21; Ruby 3.1–3.3; PHP 8.3; GCC 13 and Clang; git, curl, jq, yq, tmux, ripgrep, make, cmake. `docker` is "(limited availability)". PostgreSQL 16 and Redis 7 are installed but not running. Also Playwright with Chromium, ffmpeg, pandoc, LibreOffice and TeX Live. **No custom base image.** VERIFIED absence: the config has only `networking` and `packages`.
- **Packages**: `packages.{apt,cargo,gem,go,npm,pip}` with optional pins, installed in alphabetical manager order and cached across sessions that share the environment. Under `limited` networking they require `allow_package_managers: true`.
- **Setup commands / init script**: **none**. **Plain env vars**: **none**. The only env vars are vault `environment_variable` secrets, which appear as an opaque placeholder that is substituted at egress. They do not work with clients that sign requests (e.g. AWS SigV4) or that validate the format locally (MA+vaults). Any setup has to happen through the agent's bash, a skill, or the system prompt. UNVERIFIED whether a better route exists.
- **Network**: `unrestricted` is the **default when omitted in the API**, with a "general safety blocklist". `limited` uses `allowed_hosts` (exact host or `*.domain`) plus `allow_package_managers` (a GitHub, GitLab, Bitbucket, registries and Ubuntu list) plus `allow_mcp_servers`. A blocked request on port 80/443 returns 403 naming the host. `allowed_hosts` also restricts `web_fetch`/`web_search`, which run on Anthropic servers. Access is per host, not per operation (`git push` to an allowed host works).
- **Resources**: memory up to 8 GB, disk up to 10 GB. **CPU count: UNVERIFIED** (not stated).
- **Lifetime and persistence**: each session gets its own fresh container. "When a session goes idle, its sandbox is checkpointed … filesystem, installed packages". Sandbox state lasts **30 days from sandbox creation; activity does not extend it**. After that, a resumed session gets a fresh sandbox (MA+events-and-streaming). First-party MA "has no autonomous-session runtime limit"; on AWS the limit is 6 h (https://platform.claude.com/docs/en/build-with-claude/claude-platform-on-aws). Snapshot or fork of the sandbox is **not exposed**. VERIFIED absence.
- **File mounts**: Files API `file` resources, read-only at `/mnt/session/uploads/…`; outputs go to `/mnt/session/outputs/`. Files can be added or removed mid-session.
- **GitHub repos** (MA+github): resource `{type:"github_repository", url:"https://github.com/<owner>/<repo>", authorization_token, mount_path (under /workspace, default /workspace/<repo>), checkout:{type:"branch",name}|{type:"commit",sha}}`. Multiple repos are allowed, and the set is fixed for the session. Repos are cached across sessions. The token can be rotated through `resources.update`. Only `github.com` HTTPS URLs are accepted; SSH and other forms get `invalid_request_error`. **Push**: ENG says "we use each repository's access token to clone the repo during sandbox initialization and wire it into the local git remote. Git push and pull work from inside the sandbox without the agent ever handling the token itself." Branch, commit and push are documented "With the GitHub MCP server" (`https://api.githubcopilot.com/mcp/`, with a vault credential). PR creation needs GitHub MCP or the API. A fine-grained PAT is recommended; there is **no GitHub App flow**. GitLab, Bitbucket and GHES as resources: unsupported (URL form). Git basic auth via a vault env-var placeholder is likely broken by base64 encoding (UNVERIFIED).
- **Worktrees and processes**: git is installed and the agent has bash, so `git worktree add` inside `/workspace/<repo>` should work. That is UNVERIFIED by drill, and the docs do not discuss it. Arbitrary processes run through `bash`. Long-lived services across idle checkpoints: UNVERIFIED (likely lost). Cloud bash timeouts: undocumented.

### 3b. Self-hosted sandbox (`type: "self_hosted"`), per MA+self-hosted-sandboxes*, SDK `lib/environments`, `lib/tools/agent_toolset.py`
- "Self-hosted sandboxes keep the orchestration on Anthropic's side but move tool execution into infrastructure you control." The environment is a **work queue**. Our worker (the `ant beta:worker poll|run` CLI, or SDK `EnvironmentWorker` / `work.poller()` / `sessions.events.tool_runner()`, or the raw Work endpoints) claims a session, downloads skills to `<workdir>/skills/`, syncs memory stores to `/mnt/memory/`, **executes `bash/read/write/edit/glob/grep` locally and posts `user.tool_result`**. `web_search`/`web_fetch` still run server-side.
- **Full control**: any image you choose (needs `/bin/bash`); any repos, branches, worktrees and services; any network. The SDK toolset is open-source reference code: `beta_bash_tool(env)` and so on, with an `AgentToolContext(workdir, allowed_roots, read_only_roots)`. You can **wrap or replace each built-in tool** with `EnvironmentWorker(…, tools=lambda env: [...])`, which gives real pre and post interception, input rewriting, and Stop Fence checks in our code. You can also serve **custom tools from the worker**, including MCP servers wrapped as custom tools.
- Limits: sessions accept **`memory_store` resources only**. A `file` or `github_repository` resource gets a 400, so stage repos yourself and pass references in `metadata`. Vault `environment_variable` credentials are **not supported** there. The Python `SessionToolRunner` bounds every tool call at `TOOL_TIMEOUT = 150.0` s and runs calls one at a time (SDK `_beta_session_runner.py`); a custom runner avoids this. The server-side wait for a tool result is UNVERIFIED. The environment key can **only be generated in Console**. Patterns are always-on polling, webhook-triggered (`session.status_run_started`), or a sandbox per session. `work/stop` (`force`) stops a session on the worker. `work/stats` exposes `depth`, `pending`, `workers_polling` and `oldest_queued_at`.
- Data: "Tool inputs and outputs still flow to Anthropic's control plane". Not ZDR or HIPAA eligible, "including Self-hosted sandboxes" (https://platform.claude.com/docs/en/manage-claude/api-and-data-retention). Third-party worker guides: AWS Lambda MicroVMs, Blaxel, Cloudflare, Daytona, E2B, Fly.io, GKE, Modal, Namespace, Superserve, Vercel.
- Billing for self-hosted runtime ($0.08/h?): **UNVERIFIED**. The pricing page does not distinguish it.

---

## 4. Cognition

- **System prompt**: one `system` string per agent version. Per-session override with `agent_with_overrides` (model, system, tools, mcp_servers, skills; full replace, never merged). Mid-session `system.message` events append system context on supported models (Fable/Mythos 5.x, Opus 5.5/5/4.8, Sonnet 5.5, Haiku 5.5) (MA+sessions, MA+events-and-streaming).
- **Skills**: Anthropic (`pptx`, `xlsx`, `docx`, `pdf`) or custom (`POST /v1/skills` plus versions), or repo `.claude/skills` discovery. Pinning by `version` or `latest`. Skills need the `read` tool (MA+skills).
- **Subagents / multi-agent**: `multiagent_20261001` gives subagents (`predefined_agents` ≤20, `inline_agents` toggle), dynamic workflows (on by default with this type), and `advisor`. Shared sandbox and vaults; per-thread context; ≤25 child threads; one shared budget (MA+multiagent-orchestration).
- **Custom tools** (client-executed): `{type:"custom", name, description, input_schema}`. The agent emits `agent.custom_tool_use`, we answer with `user.custom_tool_result`, and the session waits on `requires_action`. Names cannot start with `mcp__`/`ant__` or collide with built-ins (MA+tools). This is the cleanest hook for Mission Control-specific actions (checkpoint, request approval, write intent).
- **MCP**: remote streamable-HTTP only (SSE fallback); private servers via MCP tunnels (research preview). Declared in `mcp_servers` with a matching `mcp_toolset` entry. Auth only through session vaults (`mcp_oauth` with automatic refresh, `static_bearer`). MCP toolsets default to `always_ask` (MA+mcp-connector, MA+reference).
- **Hooks / interception**: **no hooks**. Equivalents:
  - `permission_policy` per toolset or tool: `always_allow` (the default for the agent toolset), `always_ask` (the default for MCP), and `auto` (the server decides allow, deny or ask; we cannot override a server deny).
  - An `ask` produces `agent.tool_use` or `agent.mcp_tool_use` with `evaluated_permission:"ask"`, then `session.status_idle{stop_reason:{type:"requires_action", event_ids}}`. "The session waits indefinitely". We answer with `user.tool_confirmation{tool_use_id, result: allow|deny, deny_message}`. **We cannot rewrite input.** Policies are frozen per session at create and can change only while idle through `sessions.update` (MA+permission-policies, MA+session-operations).
  - Post-tool hooks: observe-only, via `agent.tool_result` events.
  - Self-hosted: full interception in our tool code (see 3b).
- **Context management**: automatic compaction (`agent.thread_context_compacted`) and server prompt caching. No knobs (MA+overview, MA+migration). Memory stores give cross-session memory (MA+memory).

---

## 5. Lifecycle control

| Need | MA mechanism (VERIFIED unless marked) | Source |
| --- | --- | --- |
| Create + first turn | `POST /v1/sessions` with `initial_events` (≤50, all-or-nothing validation, creates in `running`). Otherwise the session is created `idle` and the sandbox provisions immediately | MA+sessions |
| Follow-up mid-run | `POST …/events` with `user.message`. "`processed_at` is null while the event is still queued behind earlier events", so this is **queued**. Whether it is injected between tool calls or held until the turn ends: **UNVERIFIED** | MA+events-and-streaming |
| Interrupt / cancel | `user.interrupt` (optionally `session_thread_id`). Asynchronous: the model stops immediately, tools may take longer, then the session goes `session.status_idle` with `stop_reason end_turn`. Interrupt plus `user.message` in one request = cancel-and-replace (documented order). It does not end workflow runs. No receipt listing cancelled queued messages | MA+events-and-streaming, MA+session-threads |
| Pause / resume | **No pause primitive.** Emulations: (a) **budget gate**: lower `budget.max_list_cost` to just above consumed cost and every thread pauses before its next model request (`budget_reached`); raise or remove it and the session auto-resumes. Only for sessions created with a budget, and the request in flight still finishes. (b) Tool gate: `always_ask` waits indefinitely. (c) Interrupt, then later a `user.message` | MA+budgets, MA+permission-policies |
| Approvals | `always_ask`/`auto` with `requires_action` and `user.tool_confirmation`. Durable server-side wait. Also available interactively in `ant beta:sessions connect` and the Console viewer | MA+permission-policies |
| Event stream + replay | SSE `GET …/events/stream` (only events after connect). Resume = open a new stream, list history (`created_at[gte]`, `types`, `page`) and dedupe by event `id`. Per-thread streams. `event_deltas` previews are stream-only and never persisted | MA+events-and-streaming, MA+event-deltas |
| Status | `GET /v1/sessions/{id}`.status (`idle/running/rescheduling/terminated`). The stop reason only appears on the latest `session.status_idle` event. `idle` does not mean done while workflow runs are open | MA+session-operations |
| Archive / delete | Archive keeps history and blocks new events. Delete removes the record, events, sandbox and session-scoped output files. Both require **not `running`** (interrupt first). Workflow runs can block them | MA+session-operations |
| Fork / branch | **Not available.** VERIFIED absence | — |
| Budgets | `budget{type:"limit", max_list_cost{amount:"<cents>", currency:"USD"}}`, set at create only. Changeable, removable once. Enforced between model requests at list prices (tokens + web search $10/1k + runtime $0.08/h). Only settle events are accepted at the cap | MA+budgets |
| Usage / cost | `session.usage` (`input/output/cache_*` tokens, `list_cost` in cents, `active_seconds`, `server_tool_use`). `session.usage` event before every idle. Per-thread usage. Console session viewer (Developer/Admin) | MA+session-observability |
| Webhooks | Session: `status_run_started`, `status_idled`, `budget_reached`, `status_rescheduled`, `status_terminated`, `thread_created/idled/terminated`, `outcome_evaluation_ended`, `updated`, `deleted`. Also vault, credential, agent, deployment, deployment_run, environment and memory_store events. Not a durable log | MA+webhooks |
| Limits | 300 create / 1,200 read rpm per org. Org spend limits. Concurrent-session cap: **UNVERIFIED** (none documented) | MA+reference |

---

## 6. Mission Control harness operations mapped to MA

Operations are from `application/execution/harness/protocol.py::AgentHarness` (`describe` + `prepare, start, reattach, send_turn, cancel_turn, observe, snapshot, usage, end_session`) plus the command semantics in `docs/research/2026-10-07-coding-lane-surfaces.md` (`queue_instruction, interrupt_and_inject, pause, fork`, custom permission decider). "Cloud" means an MA cloud environment; "SH" means an MA self-hosted environment.

| MC operation | Support | Exact MA API | Notes |
| --- | --- | --- | --- |
| `describe` | emulated | `GET /v1/agents/{id}` (+ `versions`), `GET /v1/environments/{id}`, session `agent` snapshot | Static matrix plus the pinned agent version. No capability handshake |
| `prepare` | **native** | `POST /v1/agents` (versioned, `version` 409 guard), `POST /v1/environments`, `/v1/vaults`+credentials, `/v1/skills`(+versions), `/v1/files`, `/v1/memory_stores`; or `ant apply` | No idempotency key, so use name/metadata lookup. Environments are unversioned, so record the config digest ourselves |
| `start` | **native** (non-idempotent) | `POST /v1/sessions {agent:{type:"agent",id,version}, environment_id, resources, vault_ids, budget, metadata:{mc_attempt_id…}, initial_events:[user.message]}` | At-least-once. Reconcile via `GET /v1/sessions?agent_id&created_at[gte]` plus a client-side metadata match. Disable SDK auto-retry on create, or reconcile before retrying |
| `reattach` | **native** | `GET /v1/sessions/{id}`, then open `…/events/stream`, then `GET …/events?created_at[gte]=…` and dedupe ids | The session lives server-side and survives worker crashes. In SH, a new worker reclaims the work item via the lease (`reclaim_older_than_ms`) |
| `send_turn` / `queue_instruction` | **native**, queued | `POST …/events [{type:"user.message"}]` | `processed_at` null while queued. Turn-boundary vs mid-turn delivery UNVERIFIED. Rejected while at budget cap |
| `cancel_turn` | **native** (async, no receipt) | `POST …/events [{type:"user.interrupt"[, session_thread_id]}]` → `session.status_idle{end_turn}` | Wait for the idle event; the interrupt's `processed_at` marks when it was applied. Does not stop workflow runs |
| `interrupt_and_inject` | **native `cancel_and_replace`**; cooperative inject emulated / UNVERIFIED | `POST …/events [{user.interrupt},{user.message}]` (order documented); `system.message` for privileged context | `system.message` applies "to the accompanying turn and all subsequent turns" |
| `pause` | **emulated** | (a) `POST /v1/sessions/{id} {budget:{max_list_cost:{amount: consumed+δ}}}` → `budget_reached`, resume by raising; (b) `always_ask` tool gate; (c) interrupt | (a) needs a budget set at create; one in-flight model request finishes. SH: the worker can also delay `user.tool_result` (Python runner caps at 150 s) |
| `observe` | **native** | SSE `GET …/events/stream[?event_deltas=…]`; history `GET …/events` (`types`, `created_at`, `order`, `page`); per-thread `…/threads/{tid}/stream`; webhooks for wakeups | Cursor = (last `created_at`, event id set) plus the opaque `page`. No sequence number, no `Last-Event-ID` |
| `snapshot` | cloud: **unsupported** (automatic idle checkpoint is not addressable) / emulated; SH: **native in our infra** | Emulate with git commit/push from the sandbox (token wired into the remote), `/mnt/session/outputs/` and `GET /v1/files?scope_id=sesn_…`, memory store versions | Cloud sandbox state expires 30 days after creation |
| `usage` | **native** | `session.usage` event; `GET /v1/sessions/{id}`.usage/.stats; thread usage; `budget` | `list_cost` is list price, not contracted price |
| `end_session` | **native** | `user.interrupt` until idle, then `POST /v1/sessions/{id}/archive` or `DELETE /v1/sessions/{id}`; SH also `POST …/work/{id}/stop` | Download outputs before delete. Workflow runs can block archive/delete |
| `fork` | **unsupported**, emulated | New `POST /v1/sessions` with the same agent version, repo `checkout:{commit}` from a pushed branch, files, and `initial_events` carrying a context digest | Conversation history and sandbox cannot be cloned |
| Custom permission decider | **native** (allow/deny only) | `permission_policy: always_ask` + `user.tool_confirmation{allow\|deny, deny_message}`; custom tools fully ours; SH: wrap tools in `EnvironmentWorker(tools=…)` | No `updatedInput`. `auto` server denials cannot be overridden. Stop Fence / Operation Intent fits the confirmation handler (cloud) or the tool wrapper (SH) |

---

## 7. Pricing, limits, regions, retention

- **Pricing** (https://platform.claude.com/docs/en/about-claude/pricing#claude-managed-agents-pricing): model tokens at standard rates, with caching multipliers. Web search $10 per 1,000. **Session runtime $0.08 per session-hour**, metered to the millisecond **only while `running`** (idle, rescheduling and terminated are free). It "replaces the code execution container-hour billing". No batch discount, and not available on partner clouds (Bedrock/Vertex pricing does not apply). A `us` `inference_geo` pin bills tokens at 1.1x. Fast mode premium applies. Worked example: 1 h of Opus 5 with 50k input and 15k output tokens costs $0.705.
- **Limits**: 300 create / 1,200 read rpm; ≤50 initial events; request body ≤32 MB; ≤100 file-sourced documents in `initial_events`; ≤500 files per session; ≤500 skills per session; ≤8 memory stores; ≤20 MCP servers; ≤128 tool entries; ≤25 child threads; ≤20 vault credentials; ≤1,000 deployments per org; 8 GB RAM / 10 GB disk.
- **Regions**: `model.inference_geo` `"us"` or `"global"`, validated against the workspace `allowed_inference_geos` (MA+agent-setup). Sandbox hosting region: **UNVERIFIED**. Also available as Claude Platform on AWS (6 h autonomous-run reauth; no memory stores on self-hosted there).
- **Retention / ZDR**: **not ZDR- or HIPAA-BAA-eligible**, including self-hosted sandboxes. "transcripts persist until you delete them". Sandbox state lasts 30 days. Memory versions are retained 30 days (https://platform.claude.com/docs/en/manage-claude/api-and-data-retention, MA+overview, MA+memory).

## 8. Manual owner actions

1. A Console org and workspace, plus an API key (https://platform.claude.com/settings/keys). MA is "enabled by default for all API accounts". Set org spend limits in Console.
2. Request research-preview access only if you need **MCP tunnels** or **dreaming** (https://claude.com/form/claude-managed-agents).
3. **Webhooks**: register the endpoint in Console > Manage > Webhooks (no API). It must be public HTTPS on port 443. Store the `whsec_` secret, which is shown once.
4. **GitHub**: create fine-grained PATs per repo, for mounts and for the GitHub MCP vault credential. There is no GitHub App install flow.
5. **MCP OAuth**: complete the OAuth grant yourself, then store the access and refresh tokens in a vault (`mcp_oauth`). Anthropic handles refresh after that.
6. **Self-hosted environment**: generate the environment key **in Console only** ("even for an environment you created through the API"). Run the worker fleet. Memory-on-self-hosted may need org enablement (the troubleshooting page mentions it).
7. Optional: workspace data-residency settings (`allowed_inference_geos`). Developer/Admin role for the Console session viewer.
8. No beta enrollment beyond sending the header.

---

## Lane design implications for Mission Control

1. **Treat this as a separate lane profile, not a re-qualification of `claude_cloud`.** The MA harness is not Claude Code, so it cannot satisfy "Anthropic-hosted Claude Code" (consistent with the 2026-10-12 `claude-code.md` delta D11). Proposed name: `claude_managed_agents`, with two placements: `cloud` (Anthropic sandbox) and `self_hosted` (our worker). Owner decision required (ADR).
2. **Placement preference for coding work:** **`self_hosted` placement first.** Our worker executes every built-in tool in a filesystem we allocate. That gives us our managed worktree policy (one worktree per session, or per subagent thread via our own bash/edit implementation), any git remote including non-GitHub, local services, our image, and real pre/post tool interception for the Stop Fence and Operation Intents by wrapping `beta_agent_toolset_20260401` tools. Costs: we run the worker; the 150 s per-tool cap in the Python `SessionToolRunner` (write our own runner or patch the timeout for long builds; server-side tolerance UNVERIFIED); no repo/file resources (stage them ourselves); no vault env-var secrets; Console-only environment key. `cloud` placement suits research or analysis-style tasks and GitHub-only repos.
3. **If the owner wants the Claude Code harness itself** (CLAUDE.md/AGENTS.md, hooks, `.claude/agents`, Task subagents, worktree isolation, plugins), Anthropic provides it only as self-run software. Keep or extend the `claude_agent_sdk` lane on API-key billing in our own sandboxes (worker-hosted, or a sandbox provider such as E2B, Modal or Daytona per CC+agent-sdk/hosting). Running `claude` inside an MA sandbox is undocumented, pays for tokens twice, and is not recommended.
4. **Lifecycle fit is strong.** Server-side sessions (`reattach` native), paged replayable history, durable approvals, hard budgets, per-session usage and cost, archive/delete, webhooks as wakeups. Gaps to emulate: `fork` (seeded new session), `snapshot` (git push / outputs in cloud; native in self-hosted), `pause` (budget-gate trick or tool gate), idempotent `start` (metadata reconcile), no event sequence numbers (dedupe by id, order by `created_at` and list order).
5. **Reducer design.** Drive attempt state from fetched resources and the event history, not from webhooks (unordered, ≤3 attempts, then dropped). Treat `session.status_idle{requires_action}` plus `stop_reason.event_ids` as the approval gate. Treat `end_turn` as turn done. Note that `end_turn` also follows an interrupt, so correlate with our interrupt's `processed_at`. Treat `budget_reached` as paused. Remember that `idle` is not "done" while `workflow_run.*` runs are open, so disable dynamic workflows (`multiagent` null or `workflows` off) for deterministic coding attempts unless they are wanted.
6. **Security defaults for the lane.** Explicit `limited` networking (the API default is `unrestricted`). `always_ask` or a wrapped gate on `bash` for side-effecting attempts. Fine-grained PAT per repo, rotated with `resources.update`. Read-only memory stores for shared knowledge. Never put the org API key on a self-hosted worker host (use the environment key or per-work `secret`).
7. **Cognition materialization.** Agent `system` (rendered from AGENTS.md by Mission Control, because MA does not read it), custom skills via the Skills API (versioned, pin `version`), repo `.claude/skills` (cloud mounts only, root level only), MCP servers plus vault credentials, Mission Control custom tools (`mc_checkpoint`, `mc_request_approval`, `mc_record_intent`) answered by our worker or controller.
8. **Data policy.** Not ZDR or HIPAA, and transcripts persist until deleted. The lane must refuse PHI and secret-bearing workloads by policy (BellLabs AGENTS.md: keep PHI and secrets out), and should delete sessions after output custody completes.
9. **Cost model for admission.** $0.08/h only while running, plus tokens at list price. The budget is a hard cap, so map the Mission Control attempt budget onto `budget.max_list_cost` at create. It cannot be added later, so always set one to keep the pause-by-budget option.

## Open questions (UNVERIFIED; resolve by a cheap live drill once the owner approves spend)
1. Does a `user.message` sent while `running` inject between tool calls or wait for the turn's end? **Answered (HL-23 [provider smoke](provider-smoke-2026-10.md)):** injected at the next model request of the same turn.
2. Cloud: bash tool timeout, CPU count, and whether background processes survive idle checkpoints; does `git worktree` behave normally in `/workspace/<repo>`?
3. Self-hosted: server-side maximum wait for a `user.tool_result`; is runtime billed at $0.08/h?
4. Does `user.interrupt` drop or keep `user.message` events queued before it?
5. Is there any concurrent-session cap per org?
