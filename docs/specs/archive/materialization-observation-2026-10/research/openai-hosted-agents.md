---
type: Research Note
title: "OpenAI hosted agents fact sheet: Agents API Codex harness, sandboxes and lane mapping (read 2026-10-12)"
description: "API-key-billed OpenAI surfaces: Agents API (hosted Codex harness) with openai_hosted and self_hosted executors, events, cancel, approvals, environments, vaults, pricing, and why Agents SDK sandboxes and containers are not Codex."
tags: [mission-control, research, materialization-observation]
---

# OpenAI hosted and sandboxed agent surfaces (API key), read 2026-10-12

No login, no paid call. Every claim has a source tag (list at the bottom). **UNVERIFIED** marks a claim that no official doc or source file confirms. Doc pages on developers.openai.com carry no dates, so read them "as of 2026-10-12". Fetched as Markdown twins (`<url>.md`).

## Version anchors

| Artifact | Version / date | Source |
| --- | --- | --- |
| Agents API | Beta, header `OpenAI-Beta: agents=v1`; base `https://api.openai.com/v1/agents/*` | W1, W5, S1 |
| `openai` (PyPI) | 3.29.0, uploaded 2026-10-11T17:39Z; contains `client.beta.agents.*` | S1 |
| `openai` (npm) | 7.32.0, 2026-10-09T21:16Z | S2 |
| Prewarm / attach methods | need Python SDK ≥ 3.27.0, Node ≥ 7.31.0 | W12 |
| `openai-agents` (PyPI) | 0.23.1, 2026-10-02; repo `main` `125efa029b4b` (2026-10-08) | S3, G4 |
| `@openai/agents` (npm) | 0.20.0, 2026-10-08 | S2 |
| `@openai/agents-api` (npm) | **not published** (no dist-tags). It is named in the Cloudflare guide only; UNVERIFIED | S2, W17 |
| Codex CLI / SDK | stable 0.162.1 (2026-10-09); `alpha` 0.163.0-alpha.5; Python `openai-codex` 0.162.1 | S2, S3 |
| `openai/codex` `main` | `0c329ad2c9d5` (2026-10-12T19:02Z) | G1 |
| `codex-universal` image | last commit `47f4f0eb5337` (2026-05-02) | G6 |

---

## 1. Harness identity: who runs the Codex agent loop?

**Verdict.** Yes: OpenAI hosts the Codex harness and you control it with an API key. The product is the **Agents API** (`/v1/agents/sessions`, beta).

- The docs say it "gives your application access to the Codex harness through an OpenAI-managed API" [W1].
- The architecture page names the harness "the OpenAI-hosted Codex instance that runs the model and tool loop and maintains the agent's session" [W2].
- It is the only one of the five candidates that does this.

The catch is the control surface. What the API exposes is much narrower than codex-rs's app-server:

- No shell or patch approvals.
- No hooks.
- No sandbox or approval policy.
- No fork.
- No replayable event cursor.
- No file-change items.

These gaps are detailed in §2 and §5.

| Candidate | Runs the Codex loop? | Where the loop runs | Where tools execute | Verdict |
| --- | --- | --- | --- | --- |
| (a) **Agents API** sessions + environments | **Yes** ("managed Codex harness") [W1, W2, W3] | OpenAI | `none`; `openai_hosted` (OpenAI sandbox); or `self_hosted` (your compute running `codex exec-server --remote`) [W2, W9] | **Best hosted candidate.** API key only. Beta. |
| (b) Agents SDK **SandboxAgent** | **No.** The Agents SDK runner is "the harness" and runs in *your* process [W14] | Your app | Plug-in clients: `UnixLocalSandboxClient`, `DockerSandboxClient`, and extensions Blaxel, Cloudflare, Daytona, E2B, Modal, Runloop, Vercel. **No OpenAI-hosted sandbox client** [W14, G4] | Not Codex. Useful only as a non-Codex lane. |
| (c) Codex SDK / `codex exec` / app-server with API key inside an OpenAI container | The Codex loop, yes; OpenAI hosting, no | Wherever you run the binary | OpenAI hosted containers (`/v1/containers`, Hosted Shell, Code Interpreter) have **no exec or attach API**: only files endpoints. Commands run only as model `shell_call`s. Debian 12, no sudo, no TTY, no inbound path, network off by default [W15, R1] | **Not viable** as a controllable host. A process the model started cannot be attached to or driven. |
| (d) app-server `environment/*` remote executors | The Codex loop runs in *your* app-server | Your app-server | `environment/add {environmentId, execServerUrl, authBearerToken?, connectTimeoutMs?, skills.required?}` points at a WebSocket exec-server *you* run (`codex exec-server --listen ws://IP:PORT`). **No OpenAI-hosted executor is addressable**. The Agents API sandbox registers with OpenAI's relay (`wss://codex-cloud-environments.chatgpt.com`), not with your app-server [G2, G3, W9] | Full Codex control, but you host it (worker or third-party sandbox). |
| (e) Responses API `shell` / `apply_patch` / `local_shell` + hosted containers | **No.** These are model tools; you write the loop | Your app | Hosted container (`container_auto` / `container_reference`) or local | A "Direct Model" lane, not the Codex harness [W15, W16] |

The same harness is also offered on AWS as Bedrock Managed Agents: "runs the OpenAI agent harness … in Amazon Bedrock", with IAM and SigV4 auth [W22]. That is not API-key billed and is out of scope.

**Best approximations of "Codex harness hosted by OpenAI and controllable":**
1. **Agents API with `openai_hosted`.** Fully OpenAI. Reduced control.
2. **Agents API with `self_hosted`.** OpenAI runs the harness. Our sandbox (E2B, Modal, Daytona, Docker and so on) runs `codex exec-server --remote` and gives us image, git, snapshot and egress control. Harness control is the same reduced set.
3. **Not hosted by OpenAI, but full control.** Run `codex app-server` with `OPENAI_API_KEY` ourselves (the existing `codex` lane). Optionally place execution in a third-party sandbox through `environment/add` → `codex exec-server --listen`. Billed at API rates.

---

## 2. Agents API surface (beta `agents=v1`)

Auth is a project API key with scopes [W4, W13]:
- `api.agents.read` and `api.agents.write` for sessions.
- `api.responses.write` for inference.
- `api.vaults.read` and `api.vaults.write` to manage vaults.
- `api.traces.read` (or `api.agents.read`) for trace export [W20].

The SDK adds the header automatically [W4, S1].

### Resources and endpoints

Python SDK 3.29.0 paths [S1], confirmed by the docs:

| Resource | Endpoints | Notes |
| --- | --- | --- |
| Saved agents | `POST/GET /v1/agents`, `GET/POST/DELETE /v1/agents/{agent_id}` | Fields: `model` (req), `instructions` ("appended to the agent's default base instructions"), `name`, `metadata` (≤16), `multi_agent{enabled, max_concurrent_subagents=6}`, `reasoning{effort none…max, summary}`, `service_tier auto/default/flex/priority/fast`, `text{format, verbosity}`, `tools[]`. Updates apply only to *new* sessions [W5, S1] |
| Sessions | `POST /v1/agents/sessions` (`agent` and/or `agent_id`, **`environment` required**, `input`, `metadata`, `vault_ids`, `stream`); `GET /v1/agents/sessions?agent_id&after&limit&order`; `GET/POST/DELETE /v1/agents/sessions/{id}` | `POST {id}` updates only `model`, `reasoning.effort`, `service_tier`, `metadata` for later turns. Cannot change `instructions`, `tools`, `multi_agent`, `text` or `reasoning.summary` [W5, S1]. Session `status`: `idle`, `in_progress`, `requires_action`, `failed` [R2] |
| Session events (input) | `POST /v1/agents/sessions/{id}/events` with `Idempotency-Key` header, `events[]` of type: `agent.session.input.message`, `agent.session.input.cancel`, `agent.session.input.tool_result{turn_id, call_id, success, output, error}`, `agent.session.input.computer_use_approval_request_result{request_id, response}` | "HTTP 202 confirms acceptance, not durable completion". Cancel "can recover a still-open turn whose backend execution has ended" [S1, W6] |
| Session events (stream) | `GET /v1/agents/sessions/{id}/events?stream=true` (SSE) | **No cursor parameter.** "Streams do not replay missed events" [W6, W7, S1] |
| Turns | `GET …/turns`, `GET …/turns/{turn_id}`, `GET …/turns/{turn_id}/items` | Turn fields: `id`, `agent_id`, `session_id`, `subagent_id`, `status`, `created_at`, `started_at`, `completed_at`, `error{code,message}`, `usage`. Status: `queued`, `in_progress`, `waiting`, `completed`, `failed`, `cancelled` [R2, W7] |
| Items | `GET …/items?after&limit≤100&order` | Saved history. Union: `message` (phase `commentary`/`final_answer`), `reasoning`, `function_call`, `mcp_call`, `web_search_call`, `command_execution{command, cwd, exit_code, duration_ms, output, status}`, `computer_use_call`, `computer_use_approval_request`, and subagent calls (`create_`, `send_subagent_input_`, `resume_`, `wait_for_subagents_`, `interrupt_`, `close_subagent_call`). **No `file_change` or `apply_patch` item type** [R2, S1] |
| Subagents | `GET …/subagents`, `…/subagents/{sid}`, `…/subagents/{sid}/items`, `…/subagents/{sid}/turns[/{tid}[/items]]` | [S1, W18] |
| Artifacts | `GET …/artifacts`, `GET/DELETE …/artifacts/{aid}`, `GET …/artifacts/{aid}/content` | Hosted only: files under `/workspace/outputs` are published immutably when a turn completes [W10] |
| Traces | `GET /v1/agents/sessions/{id}/traces` (OTLP JSON pages) | "Trace export must be enabled for your organization" [W20] |
| Environments | `POST /v1/agents/environments` (prewarm, `Idempotency-Key` kept 24 h), `GET` list/retrieve; **no delete endpoint** | Status `pending`, `ready`, `connected`, `disconnected`, `suspended`, `expired`, `failed` [W12, R2] |
| Environment files | `POST /v1/agents/environments/{id}/files` (`file_id` or inline), `GET` list | **Upload and list only.** Live-file download is not offered; use artifacts [S1, W10] |
| Environment templates | `POST/GET /v1/agents/environments/templates[/{id}]`, update, delete | `openai_hosted` only [W11, W12] |
| Vaults | `/v1/agents/vaults[/{id}]`, credentials CRUD. Credential types: `static_bearer` / `mcp_oauth` (MCP from OpenAI, with refresh) and `environment_variable{secret_name, secret_value, networking.allowed_hosts}` (proxy substitution, hosted only, HTTPS 443/8443) | Path: the guide shows `POST /v1/vaults/{vault_id}/credentials`; the SDK uses `/agents/vaults`, which worked live in HL-23 [W13, S1] |

### Event streaming

SSE event types [R2]:

| Group | Events |
| --- | --- |
| Session | `agent.session.created`, `in_progress`, `idle`, `requires_action`, `failed` |
| Turn | `agent.session.turn.created`, `in_progress`, `completed`, `failed`, `cancelled` |
| Items | `agent.session.turn.item.added`, `item.done` |
| Text | `content_part.added` / `done`, `output_text.delta` / `done` |
| Reasoning | `reasoning_summary_part.*`, `reasoning_summary_text.*` |
| Commands | `agent.output.command_execution_output.delta{item_id, delta}` |
| Environment | `agent.session.environment.pending`, `ready`, `connected`, `disconnected`, `failed`, `suspended`, `expired`, `reset` |
| Subagents | `agent.session.subagent.created`, `active`, `closed` |
| Errors | `error` |

Two environment events need explaining:
- `environment.suspended`: "idle hosted session environment is checkpointed and stopped … can be resumed from its private checkpoint."
- `environment.reset`: "hosted sandbox is replaced. Conversation history survives; changes to the previous sandbox's files and processes do not."

Each event has `event_id`, `session_id` and `turn_id`, but **no sequence number** [R2].

**Recovery recipe** [W7]:
1. Open a new stream and buffer it.
2. Retrieve the session and its items.
3. Restore state keyed by `item_id`.
4. Apply the buffered updates.
5. Restore pending input from `required_actions`.

Missed intermediate deltas are lost. The stream "stays open across idle events" [W19].

### Follow-ups, steering, cancel

- **Follow-up and steer.** "A message sent to an idle session starts a new turn. A message sent during an active turn steers that turn" [W6]. The error `active_turn_not_steerable` means wait [W8].
- **Cancel.** Send `{"type":"agent.session.input.cancel"}`, which yields `agent.session.turn.cancelled`. The session and its prior work remain [W6].
  - **Delta vs our 2026-10-12 `codex.md`:** cancel *is* now documented.
- **Closing the stream** does not cancel [W3].
- **Deleting a session** can return 409 while setup or execution finishes. It does not stop self-hosted compute and emits no webhook [W3, W11, W21].

### Approvals and permission

`required_actions` has exactly three types [R2, W21]:
- `function_call` (your code runs it).
- `environment_connection`.
- `computer_use_approval_request` (browser origin access or authentication).

**The built-in Bash and apply-patch tools have no approval hook, sandbox mode or approval policy field.** Neither the docs nor SDK 3.29.0 types expose one [W2, S1].

### Fork, pause, resume

- **Fork:** no endpoint (SDK 3.29.0 has none) [S1].
- **Pause:** no client-callable suspend. The hosted environment auto-suspends to a private checkpoint [R2].
- **Resume:** sessions are durable. Send new input to the same `session_id`. Subagents can be closed and later resumed (`subagent.active`) [R2].

### Status and webhooks

**Webhook events:**
- Session: `agent.session.created`, `action_required` (`function_call` / `environment_connection` / `computer_use_approval_request`; details omitted, so retrieve the session), `in_progress`, `idle`, `failed` [W21].
- Environment: `agent.environment.ready`, `agent.environment.failed` (prewarm) [W12].
- Turn outcomes are **stream-only**, not webhooks [W23].

**Delivery** follows the Standard Webhooks spec [W24]:
- Headers `webhook-id`, `webhook-timestamp`, `webhook-signature: v1,<base64>`.
- Signing secret per endpoint, created in project settings.
- SDK helper `client.webhooks.verify_signature`.
- Retries with exponential backoff for up to **72 h** on non-2xx responses. Redirects are not followed.
- Duplicates are possible, so dedupe on `webhook-id`.

### Usage and cost

- Session and turn `usage{input_tokens, input_tokens_details.cached_tokens, output_tokens, output_tokens_details.reasoning_tokens, total_tokens}` is **best-effort**: "can be null … may change … not a final bill". There is no cache-write count [W19].
- Per-subagent usage comes from each turn plus `subagent_id` [W19].
- The session object carries an optional `spend_control{limit, consumed}` in USD cents. Turn error `session_budget_exceeded` exists [R2, W8]. However, `spend_control` is **absent from SDK 3.29.0 create params and types**, and how to set it is UNVERIFIED [S1].

### Limits

| Limit | Value | Source |
| --- | --- | --- |
| Agent config (instructions + tools) | < 4 MiB | W5 |
| Input + output schema per message | < 4 MiB | W6 |
| Function result | < 4 MiB | W25 |
| `metadata` | 16 pairs (keys ≤ 64, values ≤ 512 chars) | S1 |
| Session-create files | 50 per request; inline 5 MiB each / 10 MiB total; Files API copy 50 MiB | W10 |
| Artifacts | 200 MiB each; 500 MiB per publish | W10 |
| Capability directories | ≤ 32 per session | W26 |
| `allowed_domains` | 1–100 exact hosts | W3 |
| Subagents | `max_concurrent_subagents` default 6 | W18 |
| Shared prewarmed environment | ≤ 128 attached sessions | W12 |
| Self-hosted connect wait | 5 min | W21 |
| Hosted idle deletion | 1 h, not configurable | W3 |
| Unattached prewarm | expires ≈ 5 min | W12 |
| Shared environment idle lifetime | 20 min after first attach | W12 |

- Files checks consume the user's Files API rate limit (`429 files_api_rate_limit_exceeded`) [W8].
- **Agents API RPM, TPM and concurrent-session limits are not documented.** UNVERIFIED. The rate-limits guide does not mention agents [W27].

---

## 3. Environments

### `openai_hosted` [W3, S1]

**Base.** "Linux workspace with Python, Node.js, and command-line tools". Workdir `/workspace`.
- **No image selection.** Choose `self_hosted` "when you need your own image."
- Base image name: UNVERIFIED. `codex-universal` is documented for Codex Cloud only [G6].

**Packages.** `packages{python[], system[], npm[]}` (global npm), with pinnable versions.

**Setup.** `setup_commands[{command, cwd}]`:
- "Ordered, confidential … command bodies never returned".
- They run after packages and files are prepared.
- A nonzero exit blocks the agent.

**Environment variables.** `env{}` holds string values that agent code can read. Reserved names `PATH`, `CODEX_*` and `OPENAI_API_KEY` are rejected.

**Secrets.** Use vault `environment_variable` credentials. The sandbox sees a placeholder, and a proxy substitutes the real value only for `allowed_hosts` on HTTPS 443/8443.
- The placeholder is substituted in request headers only. It "cannot supply the real secret for local computation, such as signing" [W13].
- Do not set `network.access=disabled` when environment credentials are attached.

**Network.**
- `network.access`: `enabled` (the default unless a template says otherwise), `disabled`, or `restricted` with `allowed_domains`: exact hosts, no wildcards, redirect targets listed separately.
- SDK 3.29.0 also has `blocked_domains` (restricted only, mutually exclusive with `allowed_domains`) [S1].
- Hosted stdio MCP servers require `enabled` [W3, W26b].

**Sizes and lifetime.**
- `container_size`: `small` (1 vCPU / 1 GB), `medium` (2 / 4, the default), `large` (4 / 16) [W3].
- Lifetime: keep-alives run between turns. The sandbox "can be deleted" after 1 h with no activity or keep-alives.
- The reference also documents suspend-to-checkpoint, `expired`, and `reset` (sandbox replaced, files lost) [W3, R2].

**Files.**
- Input files via `environment.files` (Files API id or inline base64, path under `/workspace`).
- Add files later with the environment Files API once `connected`.
- **Output only through artifacts** (`/workspace/outputs`, published per turn and surviving expiry) [W10].

**Desktop.** `desktop.enabled` provides a managed browser for `computer_use` [W12].

**Reuse.**
- `environment_template_id`. Omitted fields inherit, and network overrides cannot broaden the template. A template saves "configuration, not a running workspace" [W3].
- Prewarm: `POST /v1/agents/environments`, then attach with `environment.environment_id`. Up to 128 sessions **share one live workspace**: files, processes and packages [W12].

**Git.**
- No `repos` field.
- Clone inside the sandbox with network access, or upload the repo as files.
- Push credentials: a vault `environment_variable` for `api.github.com` is documented [W13].
- `git push` over HTTPS to `github.com` with a proxied placeholder is **UNVERIFIED**: Basic auth base64-encodes the placeholder, so header substitution may not match.
- **Worktrees and services:** the sandbox has a shell, so `git worktree` and background services are plausible, but **UNVERIFIED** for Agents API sandboxes. For Hosted Shell, "You can run services inside the container" [W15].
- No inbound or port exposure is documented for hosted Agents API sandboxes.

**Snapshots.** No user snapshot or fork API. The private checkpoint is internal [R2].

### `self_hosted` [W9, W11, W2]

**How it connects.**
- You run `codex exec-server --remote <session.environment.remote_url> --environment-id <session.environment.id>` inside any compute.
- Authenticate with an **environment key** as `CODEX_API_KEY`. The key is created at platform.openai.com → Agents → Environments → Keys, must have the same org, project and owner, and needs only `api.agents.environments.connect` [W9, W28].
- Egress is outbound only: `https://api.openai.com` (registration) and `wss://codex-cloud-environments.chatgpt.com` (commands).
- The executor reconnects automatically.

**Install.** The docs say `npm install -g @openai/codex@alpha` [W9].
- Source check: `--remote`, `--environment-id`, `--remote-transport`, `--use-agent-identity-auth`, `--aws-sigv4` and `--listen ws://|stdio` are all present in **stable `rust-v0.162.1`** `exec_server_command.rs`.
- The subcommand is labelled "[EXPERIMENTAL]".
- API-key remote auth is restricted to HTTPS `openai.com`/`openai.org` hosts or loopback [G2].
- `409 executor_version_incompatible` signals an executor that needs upgrading [W8].

**What you get.**
- Your image, tools, worktrees, services, private network, snapshots and storage.
- Mission Control-owned git custody.
- `capability_directories` for skills and plugins.
- `workspace_directory` (absolute).

**Lifecycle.**
- Provision on `agent.session.action_required{environment_connection}` (webhook-managed), or before input (application-managed).
- One executor per session environment ID.
- "An idle event alone is not a safe shutdown signal."
- A mid-turn disconnect can fail a tool. Reusing the environment ID does not restore files.
- Session deletion does not stop compute [W11].

**Provider guides** (all `codex exec-server` based): Modal, Cloudflare, Vercel, Daytona, Blaxel, E2B, Runloop, DigitalOcean, AWS Lambda MicroVMs (suspend and resume preserve memory and disk), OCI [W9, W17].

**Not available.** Vault proxy credentials and artifacts [W10, W13].

---

## 4. Cognition

**Instructions.** `agent.instructions` is *appended* to the harness's default base instructions [S1]. There is no base-instruction override.
- **AGENTS.md:** not mentioned anywhere in Agents API docs. **Answered (HL-23 [provider smoke](provider-smoke-2026-10.md)):** the hosted harness honours `/workspace/AGENTS.md` once the environment is connected; a turn answered before `environment.ready` does not see it.
- The Agents SDK sandbox guide does recommend workspace `AGENTS.md` files, but for the SDK harness [W14].

**Skills.**
- **Agents API:** directories with `SKILL.md` placed in the sandbox and registered via `environment.capability_directories` (≤ 32, absolute, must exist). The harness discovers them and adds each name and description to context [W26].
- Hosted environments also accept `skills[]` as `skill_reference{skill_id, version}` (Skills API `/v1/skills`) or inline ZIP [S1, W3].
- **Skills API** [W26]:
  - `POST /v1/skills` (multipart or zip).
  - Versioned (`default_version`, `latest_version`).
  - Limits: 50 MB zip, 500 files, 25 MB uncompressed file.

**Plugins.** `.codex-plugin/plugin.json` plus `skills/` plus `.mcp.json`.
- Hosted: one ZIP per plugin in `environment.plugins`.
- Self-hosted: the plugin root in `capability_directories`.
- Plugin MCP auth: `bearer_token_env_var`, `env_vars`.
- Existing sessions "do not reload the tools" [W29].

**Tools** (SDK `AgentToolParam`) [S1]:
- `function` (with `defer_loading`), `tool_search`, `programmatic_tool_calling`, `mcp`, `web_search{allowed_domains, context_size, mode}` and `computer_use`.
- Built-in Bash and apply-patch need an environment [W2].

**Function tools executed by us.** `requires_action` → `function_call{turn_id, call_id, name, arguments}` → `agent.session.input.tool_result`.
- The turn waits until the result arrives. "If that handler is unavailable, the agent can remain waiting" [W2, W25].
- **Subagents cannot use function tools** [W18].

**MCP** [W26b]:
- `connection_origin: "service"` (from OpenAI, works without an environment) or `"environment"` (from the sandbox).
- `stdio{command, args, cwd}` runs in the environment.
- `allowed_tools`, `required`, `credential_id`.
- Auth by inline `transport.authorization` / `headers` (encrypted, omitted from responses), or vault (service origin only).
- Secure MCP Tunnel exists for private servers [W30].

**Subagents.** `multi_agent{enabled, max_concurrent_subagents}`.
- The harness supplies create, message, wait, interrupt and close tools.
- Subagents share the environment and inherit MCP and web search.
- Observable through `subagent.*` events and the subagent endpoints [W18].
- Codex custom agents (`.codex/agents/*.toml`) are not documented for the Agents API (UNVERIFIED).

**Hooks and guardrails.** None documented for the Agents API. Codex `hooks.json` support in the hosted harness is UNVERIFIED and should be assumed absent.
- Guardrails exist only in the Agents SDK (in-process) [W31].
- The only gates are:
  - `required_actions` (function tools, environment connection, computer use).
  - Network policy.
  - Credential brokering.

**Compaction.** Automatic in the Agents API ("Summarizing previous work to manage its context window") [W1, W32]. There is no knob and no compaction item in the public item union [R2].
- The Responses API has `context_management{compact_threshold}` server-side compaction, which emits an encrypted compaction item [W33].

---

## 5. Mission Control harness operations → Agents API

The operation set comes from `docs/knowledge/lanes-and-harness.md`: `describe` plus `prepare`, `start`, `reattach`, `send_turn`, `cancel_turn`, `observe`, `snapshot`, `usage` and `end_session`; and the controls `queue_instruction`, `interrupt_and_inject`, `pause`, `fork` and the custom permission decider.

The table also compares the self-run Codex app-server lane (C), with values from `docs/research/2026-10-07-coding-lane-surfaces.md`.

| Operation | Agents API (`openai_hosted` / `self_hosted`) | Exact API | App-server lane (C), for comparison |
| --- | --- | --- | --- |
| `describe` | emulated | Static matrix plus `GET /v1/agents/{id}`, `GET /v1/agents/sessions/{id}` (agent, tools, environment, status); pin the SDK version. No capability endpoint. | emulated |
| `prepare` | native | `POST /v1/agents` (saved agent), `POST /v1/agents/environments/templates`, `POST /v1/agents/environments` (prewarm, `Idempotency-Key`), vaults and credentials, `POST /v1/skills`, plugin ZIPs | native |
| `start` | native | `POST /v1/agents/sessions {agent_id\|agent, environment, input, metadata{mc_attempt_id}, vault_ids, stream}`. **No `Idempotency-Key` documented for session create** (UNVERIFIED). Dedupe through `GET /sessions?agent_id=` plus metadata | native |
| `observe` with replay cursor | **emulated** | Live: `GET …/events?stream=true` (no cursor, no replay, no sequence numbers). Replay: `GET …/items?after=<item_id>&order=asc`, `GET …/turns?after=`, subagent items and turns. Lane cursor = `(last_item_id, open turn ids)` | native notifications; replay via `thread/read`, `thread/items/list` |
| `reattach` | native (stronger than local) | The harness keeps running server-side. `GET session` (status, `required_actions`) → new stream → items reconcile [W7, W25] | native for history; the running turn is lost on process death |
| `send_turn` | native, but must gate | `POST …/events {agent.session.input.message}` with `Idempotency-Key`. Idle starts a new turn; active **steers**. Gate on `session.status` (or the turn ledger) for `wait_then_send` | native (same steer quirk) |
| `queue_instruction` | emulated `wait_then_send` | Turn status `queued` exists [R2]. Server-side queue semantics are UNVERIFIED | `wait_then_send` / `thread/queue/*` |
| `cancel_turn` | **native** | `POST …/events {agent.session.input.cancel}` → `agent.session.turn.cancelled`. 202 means accepted only | native `turn/interrupt` |
| `interrupt_and_inject` | native `cooperative_inject` (message during an active turn) and `cancel_and_replace` (cancel, wait for `turn.cancelled`, then message) | as above | native |
| `pause` | unsupported, or emulated `pause_at_tool_gate` for function tools only | Withhold `tool_result` while `requires_action`. No pause for Bash. Environment `suspended` is provider-driven | emulated (withhold approval) |
| `fork` | **unsupported**; emulated by hydration | New session seeded with a transcript or summary from `items`, plus workspace from artifacts or self-hosted provider snapshot. A shared environment (`environment_id` on several sessions) shares a *live* workspace, which is not a fork | native conversation; emulated workspace |
| `snapshot` | emulated | Hosted: artifacts (`/workspace/outputs`, per turn), environment files list; no live-file download. Self-hosted: provider snapshot or git | emulated |
| `usage` | native tokens (best-effort); cost estimated | Turn and session `usage`; per-subagent via `turns.subagent_id`; `spend_control` (USD cents) in the reference; trace export | native tokens; cost unsupported |
| `end_session` / close | native | `DELETE /v1/agents/sessions/{id}` (retry on 409). Self-hosted: stop compute separately. Artifacts deleted separately | native |
| inspect | native | `GET` session, turns, items, subagents, artifacts, traces; dashboard Logs → Agents | native |
| Custom permission decider | **unsupported for built-in Bash and patch**; native for function tools and computer-use approvals | `required_actions` / `tool_result` / `computer_use_approval_request_result` | native (`approval_handler`) |
| Webhook-driven lifecycle | native | `agent.session.created/action_required/in_progress/idle/failed`, `agent.environment.ready/failed`. Standard Webhooks signatures | none (`notify` / hooks local) |

### Deterministic-reducer notes

- **Dedupe keys:** `event_id` for live frames; `(session_id, turn_id, item_id)` for closing facts.
- **Closing facts:** `turn.item.done` and turn terminal events (`completed`, `failed`, `cancelled`) for the root turn, where `subagent_id` is null.
- **Phase `awaiting_human` or `awaiting_tool`:** `session.status = requires_action`.
- **Failure precedence:**
  - `agent.session.failed` is terminal for the session. Create a new one.
  - A turn `failed` is not session failure.
  - `idle` is never success on its own [W6, W8, W21].
- **Effects:**
  - `command_execution` items give command, exit code and output, but there are **no file-change diffs**. Derive diffs from git in self-hosted, or from an artifact patch in hosted.
  - Command-output truncation is not reported [W19].

---

## 6. Pricing, limits and data retention

### Model tokens

Billed at API rates, standard tier, short context, per 1M tokens: input / cached input / cache write / output [W34].

| Model | Input | Cached input | Cache write | Output |
| --- | --- | --- | --- | --- |
| `gpt-6-astra` (docs' example model) | $10.00 | $1.00 | $12.50 | $50.00 |
| `gpt-6-sol` | $2.00 | $0.20 | $2.50 | $10.00 |
| `gpt-6.1-sol` | $2.00 | $0.10 | $2.50 | $10.00 |
| `gpt-6-luna` | $0.10 | $0.01 | $0.125 | $0.50 |
| `gpt-5.6-sol` | $4.00 | $0.40 | $5.00 | $20.00 |

- Flex is about half the standard rate.
- `service_tier` is selectable per session [S1, W34].
- Subagent calls and retries add cost. Reasoning tokens bill as output [W19].

### Hosted sandbox

"Standard container rates" [W1, W3]: **1 GB $0.03, 4 GB $0.12, 16 GB $0.48 (64 GB $1.92) per 20-minute session per container**, "billed by the minute, with a 5-minute minimum per session" for eligible sessions [W34].

| `container_size` | Memory | Per 20 min | Per hour |
| --- | --- | --- | --- |
| small | 1 GB | $0.03 | $0.09 |
| medium (default) | 4 GB | $0.12 | $0.36 |
| large | 16 GB | $0.48 | $1.44 |

- The size-to-price mapping by memory is an inference (UNVERIFIED).
- Pre-warming is free until attach [W12].

### Other charges

- Web search: $10 per 1k calls plus content tokens [W34].
- Self-hosted compute is billed by the provider.

### Rate and concurrency

- **Undocumented for the Agents API** (UNVERIFIED).
- Known: `max_concurrent_subagents` default 6; shared environment ≤ 128 sessions; Files API per-user 429 [W8, W12, W18].
- Project and org spend limits surface as turn errors (`project_spend_limit_exceeded` and others) [W8].

### Data retention

- `/v1/agents`: not used for training; abuse monitoring 30 days; **application state retained until deleted**; **not ZDR-eligible**; not eligible for Private Retention [W35].
- "Supports data residency only in the United States and does not support ZDR. Choosing a self-hosted sandbox does not make the Agents API ZDR-eligible" [W1].
- Traces are on by default for new sessions [W20].
- **Implication:** no PHI or secrets in prompts or sandboxes, consistent with workspace rules.

---

## 7. Owner manual steps (one-time)

1. **Project and key.**
   - Create a dedicated OpenAI Platform project for the lane.
   - Create a **restricted project API key** with `api.agents.read`, `api.agents.write` and `api.responses.write`.
   - Add `api.vaults.read`/`write` if Mission Control manages vaults, and `api.traces.read` for trace export [W4, W13, W20].
   - Store it as `OPENAI_API_KEY` in the worker secret store. Never put it in a sandbox.
2. **Billing and limits.**
   - Credits or payment on the org.
   - Set project spend limits (they surface as turn errors) [W8].
   - Model access to the chosen model (e.g. `gpt-6-sol` or `gpt-6-astra`).
   - Organization verification for these models is **UNVERIFIED**: not mentioned in Agents API docs.
3. **Webhooks** (recommended).
   - Platform → Project settings → Webhooks: create an endpoint and subscribe to `agent.session.*` and `agent.environment.*`.
   - Store the **signing secret**, which is shown once [W24].
   - The receiver must be publicly reachable over HTTPS.
4. **Self-hosted profile only.**
   - Create an **environment key**: Agents → Environments → Keys, same org, project and owner, `api.agents.environments.connect` only, optional IP restrictions [W9, W28].
   - Provide it to the sandbox as `CODEX_API_KEY`.
   - Allow egress to `api.openai.com` and `codex-cloud-environments.chatgpt.com`.
5. **Trace export.** "Must be enabled for your organization" [W20]. The enablement path is UNVERIFIED (likely a support request).
6. **GitHub.** There is no GitHub "connection" in the Agents API. Choose one:
   - (a) Keep credentials in Mission Control and expose `git_push` / `open_pr` as **function tools** (recommended), or
   - (b) store a fine-grained PAT or GitHub App token as a vault `environment_variable` credential with `allowed_hosts` (e.g. `api.github.com`; `github.com` for git is UNVERIFIED) [W13].
7. **Data controls.** Accept that the Agents API is non-ZDR, US-only, and stores state until deleted. Make sure the deletion policy (DELETE sessions and artifacts) is implemented [W1, W35].
8. **Optional.** Upload shared skills (`/v1/skills`) and create environment templates (one-time setup, scriptable by API) [W26, W12].

---

## Lane design implications for Mission Control

### What is new vs repo beliefs

1. The Agents API now documents **cancel** (`agent.session.input.cancel`). `research/codex.md` (2026-10-12) said "No explicit cancel". Update that note.
2. **Environment states and spend control.**
   - New states `suspended` (private checkpoint), `expired` and `reset` (sandbox replaced, files lost).
   - Optional `spend_control` in USD cents.
   - The executor flags ship in stable 0.162.1, labelled experimental.
3. **The Agents API is not `codex_cloud`.**
   - It does not touch Codex Cloud tasks or environments.
   - The `codex_cloud` Outcome 3 verdict stands.
   - The Agents API should be a **new profile**, e.g. `codex_agents_api` (placements `openai_hosted` and `self_hosted`).
4. **The Agents API harness is the Codex harness, but it is closed.**
   - No hooks, approvals, sandbox policy, `config.toml`, AGENTS.md guarantee, fork, or diff items.
   - The `describe` matrix must say so honestly. These cells are *unsupported*, not "unqualified".

### Recommended architecture

There are two profiles, and you pick per mission by control requirements.

**Profile H: `codex_agents_api`.** Hosted Codex harness, API key. **Recommended default for "hosted by OpenAI".**

*Placement:* `self_hosted` on a third-party sandbox (Modal, E2B or Daytona; or Docker on the worker for local proof) in v1.
- `openai_hosted` is a cheaper-to-operate variant for tasks that need no repository write custody.
- Rationale for self-hosted: image control, real git worktrees, services, provider snapshots, egress control, and file custody (hosted gives only `/workspace/outputs` artifacts and no live-file download).
- The harness stays OpenAI-hosted and durable.

*Control pattern:*
- **Start.** The worker creates a saved agent per lane version, then sessions with `metadata{mc_attempt_id, generation}`. Dedupe by listing by `agent_id`, because session-create idempotency is undocumented.
- **Observe.**
  - Hold one SSE stream per active session in `lane.turn`, and persist every frame (FrameSink) keyed by `event_id`.
  - The lane cursor is `(last_item_id, turn_id)`.
  - On resume, follow the documented buffer, retrieve and reconcile recipe (`items?after=`). Treat lost deltas as acceptable: closing facts come from `item.done` and turn terminal events or items.
- **Webhooks.** Use `action_required` / `failed` / `idle` as wake-ups for the Temporal workflow, signature-verified and deduped on `webhook-id`. Always re-read session state; never trust the payload.
- **Effects and the Stop Fence.** The built-in Bash cannot be gated, so make the sandbox **effect-free by construction**:
  - Network `restricted` to package mirrors only.
  - No push credentials in the sandbox.
  - Every external side effect (git push, PR, issue comment, deploy) is a **function tool** that Mission Control executes after checking the Stop Fence and writing the Operation Intent keyed on `(session_id, turn_id, call_id)`. The tool result is durable before it is submitted.
  - This turns `requires_action` into the native custom permission decider and `pause_at_tool_gate`.
- **Diffs and SHA custody.**
  - The agent commits in the sandbox worktree.
  - Mission Control pulls the commit or patch through the provider file API (self-hosted), or through a `git bundle` or `format-patch` in `/workspace/outputs` (hosted).
  - Mission Control verifies and pushes. This also covers the missing `file_change` items.
- **Cognition materialization.**
  - Instructions via `agent.instructions` (appended).
  - Repo `AGENTS.md` copied into `workspace_directory` (honoring is UNVERIFIED, so also inline critical rules into `instructions`).
  - Skills via `capability_directories` (self-hosted) or `skills[]` / `plugins[]` (hosted).
  - MCP via `agent.tools`.
  - No hooks. Hook-dependent policy must move into function tools or network policy.
- **Fork** is emulated by hydration: a new session plus a seeded summary or transcript plus a provider snapshot or git ref.
- **Cancel** is native. Use `cancel_and_replace` for interrupt.
- **End.** DELETE the session, stop compute, and delete artifacts per the retention policy.

**Profile C: `codex` (existing lane), app-server with API-key auth.** For missions needing the full Codex control plane:
- `turn/steer` and `turn/interrupt`.
- Approval requests on every command and patch.
- Hooks, `config.toml`, execpolicy rules.
- `thread/fork`.
- `fileChange` diffs.
- AGENTS.md semantics.

*Placement options:*
1. **Worker-local:** the current design.
2. **Worker app-server + remote executor:** `environment/add {environmentId, execServerUrl: wss://<sandbox>/…, authBearerToken}` pointing at `codex exec-server --listen ws://0.0.0.0:PORT` inside a third-party sandbox. Threads select it via `TurnEnvironmentParams{environmentId, cwd}`.
   - This keeps the harness under Mission Control and the execution in an isolated sandbox.
   - The environment methods are **experimental** [G2, G3, D8].
3. **app-server inside the sandbox**, reached over ws/unix. This is simpler but puts the API key in the sandbox, so prefer option 2.

*Billing:* API-key rates. There are no container fees from OpenAI; provider compute fees apply.

**Not recommended:**
- Running `codex app-server` or `codex exec` inside OpenAI hosted containers (no attach or exec API).
- Agents SDK SandboxAgent (not the Codex harness).
- A Responses API shell loop (that is a Direct Model lane).

### Top constraints

1. Beta API (`agents=v1`). The docs mention a GA contract for session updates, but no GA header or version is documented.
2. Not ZDR, US-only residency, state kept until deleted.
3. No replay cursor and no event sequence numbers.
4. Built-in shell and patch cannot be approved or hooked.
5. No fork or snapshot API.
6. No diffs.
7. Hosted sandbox has a non-configurable 1 h idle deletion, possible `reset` (files lost), and no live-file download.
8. Undocumented rate and concurrency limits, and undocumented session-create idempotency.
9. Self-hosted needs a long-lived outbound WebSocket executor (experimental CLI subcommand), a 5-minute connect deadline, and executor version-compat errors.
10. Subagents cannot call function tools, so effect gating applies to the root agent only. Subagents can still run Bash in the shared environment, which is why the sandbox must be credential-free.

---

## Sources (all retrieved 2026-10-12)

- W1 https://developers.openai.com/api/docs/guides/agents-api/overview.md
- W2 https://developers.openai.com/api/docs/guides/agents-api/architecture.md
- W3 https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted.md
- W4 https://developers.openai.com/api/docs/guides/agents-api/quickstart.md (prerequisites)
- W5 https://developers.openai.com/api/docs/guides/agents-api/configuration.md
- W6 https://developers.openai.com/api/docs/guides/agents-api/sessions.md
- W7 https://developers.openai.com/api/docs/guides/agents-api/sessions/events.md
- W8 https://developers.openai.com/api/docs/guides/agents-api/errors.md
- W9 https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted.md
- W10 https://developers.openai.com/api/docs/guides/agents-api/environments/files.md
- W11 https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle.md
- W12 https://developers.openai.com/api/docs/guides/agents-api/environments/prewarmed.md
- W13 https://developers.openai.com/api/docs/guides/agents-api/tools/vaults.md ; …/environments/security.md
- W14 https://developers.openai.com/api/docs/guides/agents/sandboxes.md (Agents SDK Sandbox Agents)
- W15 https://developers.openai.com/api/docs/guides/tools-shell.md
- W16 https://developers.openai.com/api/docs/guides/tools-apply-patch.md ; tools-local-shell.md ; tools-code-interpreter.md
- W17 https://developers.openai.com/api/docs/guides/agents-api/environments/providers/{modal,cloudflare,vercel,daytona,blaxel,e2b,runloop,digitalocean,aws,oci}.md
- W18 https://developers.openai.com/api/docs/guides/agents-api/multi-agent.md
- W19 https://developers.openai.com/api/docs/guides/agents-api/observability.md
- W20 https://developers.openai.com/api/docs/guides/agents-api/tracing.md
- W21 https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks.md ; …/sessions/manage.md
- W22 https://developers.openai.com/api/docs/guides/agents-api/bedrock-managed-agents.md
- W23 https://developers.openai.com/api/docs/guides/agents-api/environments/providers/aws.md ("Turn outcomes are stream events, not webhook subscriptions")
- W24 https://developers.openai.com/api/docs/guides/webhooks.md
- W25 https://developers.openai.com/api/docs/guides/agents-api/tools/functions.md
- W26 https://developers.openai.com/api/docs/guides/tools-skills.md (Agents API section, Skills API)
- W26b https://developers.openai.com/api/docs/guides/agents-api/tools/mcp.md
- W27 https://developers.openai.com/api/docs/guides/rate-limits.md (no agents entry)
- W28 https://github.com/openai/openai-cookbook/blob/main/examples/agents_api/apps/github_issues/README.md (executor key permission `api.agents.environments.connect`)
- W29 https://developers.openai.com/api/docs/guides/agents-api/tools/plugins.md
- W30 https://developers.openai.com/api/docs/guides/secure-mcp-tunnels.md
- W31 https://developers.openai.com/api/docs/guides/agents/guardrails-approvals.md
- W32 https://developers.openai.com/api/docs/guides/agents.md (runtime comparison: Agents API "runs the Codex harness … automatic context compaction")
- W33 https://developers.openai.com/api/docs/guides/compaction.md
- W34 https://developers.openai.com/api/docs/pricing.md (model tables; "Containers | Hosted Shell and Code Interpreter")
- W35 https://developers.openai.com/api/docs/guides/your-data.md (endpoint retention table, `/v1/agents` row)
- R1 https://developers.openai.com/api/reference/llms.txt (Containers endpoints: create/list/retrieve/delete plus files only)
- R2 https://developers.openai.com/api/reference/resources/beta/subresources/agents/streaming-events.md (event, session, turn and item schemas)
- S1 PyPI `openai` 3.29.0 wheel: `openai/resources/beta/agents/**`, `openai/types/beta/**` (session_create_params, environment_param, agent_session_input_param, hosted_skill_param, agent_output_item, session_update_params, item_list_params, session_list_params)
- S2 npm registry: `openai`, `@openai/agents`, `@openai/agents-api`, `@openai/codex`, `@openai/codex-sdk`
- S3 PyPI JSON: `openai-agents`, `openai-codex`
- G1 https://api.github.com/repos/openai/codex/commits (main `0c329ad2c9d5`)
- G2 https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/cli/src/exec_server_command.rs ; …/codex-rs/exec-server/src/remote.rs (register via `/cloud/environment/{id}/register|connect|validate`); cli/src/main.rs (API-key remote auth restricted to openai.com/openai.org HTTPS or loopback)
- G3 https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/common.rs (`environment/add|info|status` experimental, `thread/environment/connected|disconnected`) ; …/protocol/v2/environment.rs (`EnvironmentAddParams`)
- G4 https://github.com/openai/openai-agents-python (main `125efa029b4b`): `src/agents/sandbox/sandboxes/{docker,unix_local}.py`, `src/agents/extensions/sandbox/{blaxel,cloudflare,daytona,e2b,modal,runloop,vercel}`, `src/agents/extensions/experimental/codex/` (wraps local `codex exec`)
- G6 https://github.com/openai/codex-universal (README; last commit 2026-05-02)
- D8 https://learn.chatgpt.com/docs/app-server.md (`environment/info` experimental; `item/permissions/requestApproval` carries `environmentId`)
- Prior repo notes: `platform/mission-control/docs/specs/materialization-observation-2026-10/research/codex.md`; `docs/research/2026-10-07-coding-lane-surfaces.md`; `docs/knowledge/lanes-and-harness.md`
