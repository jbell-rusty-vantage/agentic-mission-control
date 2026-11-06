---
type: Specification
title: "SPEC-06: API-billed hosted lanes — Anthropic Managed Agents, OpenAI Agents API (Codex harness) and Sandbox Host placement"
description: "Profiles claude_managed and codex_agents with full lifecycle mapping, the SandboxHost port for self-hosted executors and for running the Claude Code and Codex harnesses on rented compute, a shared Remote Session Lane base, effect gating on closed harnesses, cognition and environment projection through APIs, data-class policy and acceptance."
tags: [mission-control, specifications, providers, lanes, anthropic, openai, sandbox]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: nothing beyond the already-done conformance-against-fakes and describe clauses. Carried forward in full: `claude_managed` cloud drill (S2/HL-24), `codex_agents` drills (S3/HL-25), policy refusals on live lanes; funding-held: self-hosted/SandboxHost (S4). Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-06: API-billed hosted lanes

Decisions R1, R3, R4 and R7, corrections C1–C3, and open decisions O1–O3 are in [DECISIONS](DECISIONS.md). Evidence:

- [Anthropic Managed Agents](research/anthropic-managed-agents.md)
- [OpenAI hosted agents](research/openai-hosted-agents.md)
- [Codebase touch points](research/codebase-new-lanes.md)
- [Provider smoke](research/provider-smoke-2026-10.md) (HL-23): the request shapes, Q-M1 and Q-O2 below were confirmed live

Facts were read on 2026-10-12. Both APIs are beta; their headers and versions are pinned in the binding.

## 1. Profiles and placements

| Profile (lane) | Who runs the agent loop | Where tools execute | Harness | Use for |
| --- | --- | --- | --- | --- |
| `claude_managed` (`claude`), placement `cloud` | Anthropic | Anthropic cloud sandbox | Managed Agents (not Claude Code) | Knowledge, research and content work; GitHub-only code tasks with Mission Control-gated publication |
| `claude_managed`, placement `self_hosted` (**funding-gated**, R31) | Anthropic | **Our Sandbox Host**, through the work queue and our tool implementations | Managed Agents | Code work needing worktrees, any git remote, services, full tool interception |
| `codex_agents` (`codex`), placement `openai_hosted` | OpenAI | OpenAI hosted sandbox | **Codex harness**, closed | Knowledge work and bounded code tasks without repo-write custody needs |
| `codex_agents`, placement `self_hosted` (**funding-gated**, R31) | OpenAI | **Our Sandbox Host** running `codex exec-server --remote` | Codex harness, closed | Code work with our image, worktrees and snapshots |
| `claude_agent_sdk` (existing), kind `sandbox_host` (O1, **funding-gated**) | **Us** (SDK in the worker) | Claude Code CLI inside our Sandbox Host | **Claude Code**, full | Everything that needs the real Claude Code harness: hooks, `.claude/agents`, AGENTS.md, Task subagents, plugins |
| `codex` (existing app-server), kind `sandbox_host` (O1, **funding-gated**) | **Us** (app-server in the worker) | `codex exec-server` in our Sandbox Host via `environment/add` (experimental) | **Codex**, full | Full Codex control plane: steer, per-command approvals, hooks, fork, diffs |

**Lane choice.** A manifest states requirements (`requires.controls`, `approvals`, `observation`). The resolver picks the first profile in `lanes:` whose declared matrix (§9) satisfies them. Example: a mission requiring `approvals: [per_command]` cannot resolve to `codex_agents` and falls through to `codex`.

## 2. SandboxHost port (O1, O2)

`application/execution/ports.py::SandboxHost` is implemented by adapters in `adapters/sandboxes/<provider>/`: Docker first, then the provider chosen by spike HL-01.

```python
class SandboxHost(Protocol):
    async def create(self, spec: SandboxSpec) -> SandboxHandle: ...   # image|kit digest, cpu/mem/disk, ttl, egress policy, labels{run,unit}
    async def exec(self, h: SandboxHandle, argv: Sequence[str], *, cwd: str, env: Mapping[str, str],
                   stdin: AsyncIterator[bytes] | None, timeout_s: float | None) -> ExecStream: ...  # streaming stdout/stderr/exit
    async def put_files(self, h, files: Mapping[str, bytes]) -> None: ...
    async def get_files(self, h, paths: Sequence[str]) -> Mapping[str, bytes]: ...
    async def snapshot(self, h) -> SandboxSnapshotRef: ...            # optional capability flag
    async def restore(self, ref: SandboxSnapshotRef, spec: SandboxSpec) -> SandboxHandle: ...
    async def terminate(self, h) -> None: ...
    def describe(self) -> SandboxHostDescribe: ...                    # egress control, snapshot, max ttl, regions
```

Rules:

- **One workspace per lease.** A sandbox holds one Workspace Lease: Mission Control clones the repo, then creates a worktree for each unit (SPEC-03), and the snapshot covers the worktree.
- **Kits apply here too.** Environment Kits (SPEC-01) build the sandbox image or run the base layer at create; the mission layer runs before the agent starts.
- **No organisation API keys inside a sandbox.**
  - Claude CLI in a sandbox reaches the model through the **Model Gateway**: `ANTHROPIC_BASE_URL` points at a Mission Control egress proxy that authenticates a per-run minted token and injects the real key.
  - `codex exec-server` uses an OpenAI *environment key*, scoped to `api.agents.environments.connect` only.
  - Managed Agents self-hosted workers use the Anthropic *environment key*, generated in the Console.
- **Default egress** is the kit allowlist plus the Model Gateway and Signal Ingress hosts. Package mirrors are added only when the kit requests them.
  - **Daytona below Tier 3 (this sprint, R16):** per-sandbox allowlists are unavailable and the organisation's essential-services list applies. It includes `*.vercel.app`, `*.anthropic.com`, `*.openai.com`, `*.chatgpt.com`, GitHub and the package registries. The Model Gateway and Signal Ingress are therefore served from the Vercel project's `*.vercel.app` host. A kit that needs any other host is refused on Daytona with `SANDBOX_EGRESS_UNAVAILABLE` until Tier 3, and runs on Docker on WSL2 instead.
- **Lifecycle.** The sandbox lifetime is bound to the lease. It is terminated after custody, or retained for the failure-retention interval. An orphan sweep matches sandboxes by their `run` and `unit` labels.

## 3. Remote Session Lane base (shared machinery)

Extract the provider-neutral parts of `adapters/cursor/cloud.py` into `adapters/remote_session/` (ADR-0052):

- the SSE reader;
- the stream-then-reconcile-from-history loop;
- deterministic create ids and reconcile-by-metadata, for providers without idempotency keys;
- the typed HTTP error set: 429 → `ProviderCapacityLimited` with `retry_after`, 409 → busy or conflict, 401/403 → non-retryable;
- the closing-facts reader;
- usage settled only when reported;
- webhook-as-wake: verify, dedupe, then re-read the resource, never trusting the payload;
- the branch or bundle custody helpers.

Each provider adapter supplies:

- an event classifier (`KIND_TABLES` and `DEDUPE_KEY_RULES` rows);
- a cursor codec;
- create, send and cancel mappers;
- a usage reader.

**Lane conformance suite (required before either new lane merges).** `tests/conformance/lanes/` runs the same scenarios against every lane's fake:

- describe honesty;
- start, observe and settle;
- reattach mid-stream with no duplicate frames;
- `send_turn` while busy;
- cancel;
- `interrupt_and_inject`;
- approval round trip;
- budget stop;
- fork emulation;
- continuation hand-over;
- unknown usage staying unknown.

`test_describe_honesty.py` currently covers Cursor only, and is generalised into this suite.

## 4. `claude_managed`

### 4.1 Resource mapping (prepare)

| Mission Control concept | Managed Agents resource | Keying and reuse |
| --- | --- | --- |
| Cognition Pack + model profile | **Agent** (versioned): `model`, `system` (instruction overlay plus *rendered repo AGENTS.md*, because Managed Agents does not read it), `tools` (agent toolset with per-tool `permission_policy`; Mission Control custom tools; `mcp_toolset`s), `mcp_servers`, `skills`, `multiagent` (null by default) | One agent per `materialization_digest` (`metadata.mc_pack`). Updates use optimistic `version`. Sessions pin `{type: agent, id, version}`. |
| Skill bundles | **Skills API** custom skills (`client.skills`, a stable namespace with no beta header), versioned (`POST /v1/skills/{id}/versions`) | Keyed by bundle digest. Skills have no `metadata`, so the digest goes in `display_name`. The version is pinned in the agent by `latest_version_id`. Deleting the skill removes its only version; deleting that version alone returns 400. |
| Environment Kit (cloud placement) | **Environment** `config{type: cloud, networking: {type: limited, allowed_hosts, allow_package_managers, allow_mcp_servers}, packages{apt,pip,npm,…}}`. **Networking is always explicit** (the API default is `unrestricted`). | `mc-<kit>-<digest8>`. Not versioned, so a new digest means a new environment. There are no setup scripts: the mission layer runs as the first `bash` call issued by the Mission Control preamble tool (§4.4), and readiness waits for its receipt. |
| Environment Kit (self-hosted) | **Environment** `config{type: self_hosted}` plus our SandboxHost image | Our worker claims work (`environments.work.poll/ack/heartbeat`) and runs tools in the lease |
| Secrets | **Vault** credentials `{display_name, auth: {type, …}}`: `environment_variable` (egress-substituted, cloud only), `static_bearer`/`mcp_oauth` for MCP. An `environment_variable`'s `networking.allowed_hosts` must also be in the environment's `allowed_hosts`, or the session reports `session.error` `credential_host_unreachable_error` (HL-23). | Vault per (installation, secret-set digest). Secret Broker delivery channel `provider_vault`. |
| Repo (cloud) | Session resource `github_repository{url, authorization_token, checkout{branch: mc/{run}/{unit}}, mount_path}` | **Read-only fine-grained PAT** by default (§4.5). The token is rotated with `resources.update`. |
| Inputs | Files API `file` resources (read-only, `/mnt/session/uploads`) | Large inputs; artifacts per SPEC-03 |
| Knowledge memory (optional) | Memory stores, read-only | For long-lived shared knowledge only. Never authoritative state (ADR-0007). |

### 4.2 Lifecycle mapping

| Mission Control operation | Implementation |
| --- | --- |
| `start` | `POST /v1/sessions` with `agent`, `environment_id`, `resources`, `vault_ids`, `budget{max_list_cost}` (**always set**: the attempt budget, and the only way to get pause), `metadata{mc_run, mc_unit, mc_generation, mc_dispatch}`, and `initial_events=[user.message(packet prompt)]`. There is no idempotency key: before retrying, list sessions by `agent_id` and `created_at`, and match `metadata` on the client. |
| `observe` | SSE `…/events/stream` plus paged `…/events` history. The cursor is `(last_event_created_at, last_event_id, open_thread_ids)`. Resume opens the stream first, then lists history from the cursor and dedupes by event `id` and `processed_at` (a client-sent event appears twice: queued, then processed). Per-thread streams appear only when multiagent is enabled, but the session stream always carries `session.thread_status_*` for the primary thread. `span.model_request_start/end` bracket every model request, and a `session.usage` event precedes every `session.status_idle` (HL-23). |
| `reattach` | Native: the session is server-side. Retrieve it, then observe from the cursor. |
| `send_turn` / `queue_instruction` | `user.message`. It stays queued (`processed_at` null) until consumed. The delivery report records `queued` and later `processed_at`. **Q-M1 (HL-23):** a message sent while `running` is consumed at the next model-request boundary of the **current** turn, and the turn's answer reflects it; no extra turn starts. `send_turn` while running therefore steers, and a true next-turn queue needs `wait_then_send` gated on idle. A `user.message` sent while the session waits on a tool answer (`idle{requires_action}`, or just after `user.custom_tool_result` until `session.status_running`) returns 400 "waiting on responses to events", so gate sends on `session.status_running`. |
| `cancel_turn` | `user.interrupt`, then wait for `session.status_idle{end_turn}` correlated after the interrupt's `processed_at` |
| `interrupt_and_inject` | `[user.interrupt, user.message]` in one send (documented order) for cancel-and-replace. A plain mid-turn `user.message` is the cooperative inject (Q-M1). An interrupt lets the in-flight model request finish, then idles with `end_turn` (HL-23). |
| `pause` / `resume` | **Budget gate**: lower `max_list_cost` to just above spend, which yields `budget_reached`; raise it to resume. Fallback: interrupt plus a held message. Declared `emulated`. |
| Approvals / Human Gate | `permission_policy: always_ask` on gated tools. `session.status_idle{requires_action, event_ids}` opens a Human Task. The decision goes back as `user.tool_confirmation{allow\|deny, deny_message}`. The wait is durable server-side. Input cannot be rewritten (declared). |
| Mission Control custom tools | `mc_signal`, `mc_request_approval`, `mc_checkpoint`, `mc_record_intent`, `mc_publish` (§4.5) are answered by the lane through `user.custom_tool_result`. The Stop Fence is checked before every answer. |
| `fork` | Emulated: a new session on the same agent version, with the repo at the pushed snapshot commit and a seeded context summary in `initial_events`. Declared `emulated`. |
| `snapshot` | Cloud: the agent's `git bundle` in `/mnt/session/outputs`, downloaded with the Files API (`scope_id`). Self-hosted: SandboxHost snapshot of the lease. |
| Continuation / compaction | Native compaction is automatic (`agent.thread_context_compacted` recorded as observed native compaction). A sealed continuation creates a new session with the packet hand-over (ADR-0039). Context occupancy comes from `session.usage` where the window is known, otherwise `unknown`. |
| `usage` | `session.usage` events and `GET session.usage`: tokens, cache, `list_cost` (minor units, so whole cents: a short session settles as `"1"`), `active_seconds`. Cost is settled from `list_cost`; runtime at $0.08 per session-hour is included in session `list_cost` and metered while `running`; per-thread figures exclude it (Q-M3 resolved). |
| `end_session` | Interrupt until idle, then custody (outputs, bundle, PR), then `archive`. `delete` runs after the retention interval. Self-hosted: `work/{id}/stop`. |
| Webhooks | Console-registered endpoint → Signal Ingress `/v1/ingress/provider/anthropic` (standard-webhooks verify). Used only as wake-ups. |
| `multiagent` | Off for code attempts. Read-only knowledge missions may turn it on (R33). When on, `idle` is not done while `workflow_run.*` is open, and the reducer must check this. |
| Outcomes (`user.define_outcome`) | Optional evidence feeding the Completion Contract. **Never** acceptance by itself. |

### 4.3 Self-hosted placement specifics

- **Worker.** A Mission Control worker activity runs `EnvironmentWorker`, with **our** tool implementations wrapping the SDK toolset (`AgentToolContext(workdir=lease, allowed_roots, read_only_roots)`).
  - **Before** each tool: Stop Fence check, Operation Intent for side-effect classes, kernel policy (deny or rewrite).
  - **After** each tool: frame capture.
- **Work-queue protocol.** Resolved from `anthropic` 1.13.0 source:
  - `poll` (`block_ms` 1–999, `reclaim_older_than_ms` default 5000, `Anthropic-Worker-ID` header);
  - `ack` (queued → starting);
  - `heartbeat` every `min(ttl/2, 30 s)`, echoing the server's `last_heartbeat`; **412 means the lease was lost**; use the returned `ttl_seconds`;
  - `stop(force)`.

  Each work item carries a per-item `sessions_token` secret, so session calls never need the org key. Tool calls arrive as `agent.tool_use` and are answered with `user.tool_result`; `agent.custom_tool_use` is answered with `user.custom_tool_result`. Calls that need confirmation wait for `user.tool_confirmation`. Tools the worker does not own are left pending for the lane to answer (the `mc_*` tools).
- **Timeouts and concurrency.** Write our own runner: the SDK `SessionToolRunner` caps tools at 150 s and runs them sequentially. The server-side wait for a tool result is undocumented (Q-M2, measured in a drill).
- **Worker death.** The lease expires and the item becomes reclaimable. Re-attaching re-sends unanswered tool calls, so **every tool must be idempotent**, keyed by Operation Intent on `(session, tool_use_id)`.
- **Repos.** Sessions accept only memory-store resources, so Mission Control stages repos and files in the lease itself and passes references in metadata.

### 4.4 Mission layer and preamble

Cloud Managed Agents has no setup hook. The agent's first instruction asks it to call `mc_prepare`, a custom tool. Mission Control answers with the exact command list (`bash .mission/setup/run`) and requires the receipt through `mc_signal env.prepared` before any other tool call is approved.

Enforcement uses `always_ask` on `bash`, `write` and `edit` until readiness is reached. The policy then switches to the steady-state policy through `sessions.update` while the session is idle. Only this sequence counts as enforcement.

### 4.5 Effects and publication

- **Read-only repo access.** By default the repo PAT is read-only, so the agent cannot push.
- **Publishing.** The agent commits locally and calls `mc_publish{branch, message}`. Mission Control then:
  1. checks the fence and records an Operation Intent;
  2. asks the agent, through the tool result, to write `git bundle create /mnt/session/outputs/mc.bundle mc/{run}/{unit}`;
  3. downloads and verifies the bundle;
  4. pushes with its own GitHub credential;
  5. opens the PR through the `repo_pr` Governed Effect.
- **Write PAT exception.** A write PAT in the sandbox is allowed only when the mission sets `effects.publication: agent` and the Spawn Grant allows it.

## 5. `codex_agents`

### 5.1 Resource mapping

| Mission Control concept | Agents API resource |
| --- | --- |
| Cognition Pack + model | **Saved agent**: `model` (`gpt-6-luna` accepted, HL-23), `instructions` (appended to the Codex base instructions), `tools` (function tools `mc_*` with a required `description`, MCP), `multi_agent{enabled: false}` by default, `reasoning`, `service_tier`, `metadata.mc_pack`. **Q-O2 (HL-23):** a `/workspace/AGENTS.md` is honoured once the hosted environment is connected, but a turn answered before `agent.session.environment.ready` does not see it. Mission Control therefore still inlines the critical repo rules in `instructions`. |
| Skills | `openai_hosted`: `skills[{type: skill_reference, skill_id, version?}]`/`plugins[]`. `/v1/skills` takes `files` only (name and description come from `SKILL.md`; no `metadata`). `self_hosted`: `capability_directories` in the exec-server environment. |
| Environment Kit (`openai_hosted`) | **Environment template** (setup commands, packages, network allowlist), plus optional **prewarm** (`POST /v1/agents/environments` with `Idempotency-Key`). Sessions also accept an inline `environment{type: openai_hosted, …}` without a template. The sandbox comes up lazily (`environment.ready`/`connected` arrive when a turn first needs it, HL-23). Sandboxes are deleted after 1 h idle and may `reset` (files lost), so custody happens per turn (§5.3). |
| Environment Kit (`self_hosted`) | SandboxHost runs `codex exec-server --remote … --environment-id …` with the OpenAI environment key. It must connect within 5 minutes. The version is pinned and checked. |
| Secrets | Agents vault credentials: `environment_variable` (hosted only, egress-substituted) or MCP `static_bearer`/`mcp_oauth`. Self-hosted gets secrets from the Secret Broker into the sandbox env allowlist. |
| Repo | `self_hosted`: Mission Control clones into the lease. `openai_hosted`: upload through environment files (small repos), or a setup command cloning with a **read-only** token from the vault (Q-O3: does a vault placeholder work for git HTTPS?). |

### 5.2 Lifecycle mapping

| Operation | Implementation |
| --- | --- |
| `start` | `POST /v1/agents/sessions{agent_id, environment, input?, metadata, vault_ids}`. Without `input` the session is created `idle`, so the lane opens the stream first and then sends the packet prompt as `agent.session.input.message{input: [{role: user, content: [{type: input_text, text}]}]}` with an `Idempotency-Key` (HL-23). Create is not idempotent (undocumented), so reconcile by listing on `agent_id` and matching metadata. |
| `observe` | SSE `…/events?stream=true` (no cursor, no replay, no sequence numbers). The lane cursor is `(last_item_id, open_turn_ids)`. Recovery recipe: buffer the new stream, retrieve the session, list `items?after=`, restore by `item_id`, apply the buffer, restore `required_actions`. Closing facts come only from `item.done` and turn terminal events. |
| `send_turn` | `agent.session.input.message` with an `Idempotency-Key`. When the session is `idle`, it starts a turn. When `in_progress`, it **steers**: HL-23 saw the message land as a `message:user` item in the same turn, before its `final_answer`, with no new turn. The lane gates on status for `wait_then_send` semantics. `active_turn_not_steerable` means wait. |
| `cancel_turn` | `agent.session.input.cancel` → `agent.session.turn.cancelled` (202 means accepted only). A cancel racing the turn start returns **409** `conflict_error` ("active session turn changed during cancellation; retry the request"), so the lane retries it (HL-23). |
| `interrupt_and_inject` | Steer (send during the turn), or cancel then send. Declared per mission. |
| `pause` | Unsupported for the built-in shell. Emulated only at Mission Control function-tool gates (`pause_at_tool_gate`). |
| Approvals | `required_actions` for Mission Control function tools only. Per-command approval is **unsupported**: missions needing it resolve to the `codex` lane. |
| `fork` | Emulated by hydration (new session, seeded summary, snapshot or git ref) |
| `snapshot` | Self-hosted: SandboxHost snapshot. Hosted: the agent writes `git bundle`/`format-patch` to `/workspace/outputs`, published per turn as artifacts. |
| `usage` | Per-turn usage from `turns.list` (per `subagent_id`). In HL-23 the session `usage` was `null` after three turns, and a cancelled turn's usage was `null`. Those stay `unknown`. Cost is estimated from the price table. `spend_control` is absent from SDK 3.29.0 and is used only if verified (Q-O4). |
| `end_session` | `DELETE` session (retry on 409), stop SandboxHost compute, then artifact custody |
| Webhooks | `agent.session.{created, action_required, in_progress, idle, failed}`, Standard Webhooks, retried for 72 h → ingress `/v1/ingress/provider/openai`. Used only as wake-ups; turn outcomes come from the stream and history. |
| Traces | `GET …/traces` (OTLP) when org trace export is enabled. Stored as frames of kind `trace`. |

### 5.3 Effects

The sandbox is **credential-free by construction**: no push token, and the network restricted to the kit allowlist plus mirrors. Every external effect is a Mission Control function tool executed after the Stop Fence check and an Operation Intent keyed on `(session_id, turn_id, call_id)`:

- `mc_publish` (bundle → verify → push);
- `mc_open_pr`;
- `mc_comment`;
- `mc_signal`;
- `mc_request_approval`;
- `mc_upload_artifact`.

**Subagents cannot call function tools**, so `multi_agent` stays off unless the mission is read-only.

## 6. `claude_agent_sdk` on Sandbox Host (real Claude Code harness)

The Python Agent SDK (pinned 0.2.165) stays **in the worker**. The Claude Code CLI runs **in the sandbox**.

- **Transport (Q-S1 resolved).** `claude_agent_sdk.Transport` is exported, and both `ClaudeSDKClient(options, transport=)` and `query(..., transport=)` accept it. Its methods are `connect`, `write`, `read_messages`, `close`, `is_ready` and `end_input`; the docstring calls it internal, so pin the SDK. The repo's `ExplicitEnvironmentCliTransport` already takes an injectable `spawn`, and a `SandboxProcess` adapter over `SandboxHost.exec` plugs in there, with `cli_path` set to the in-sandbox CLI and the version check done separately. All control traffic (`can_use_tool`, hook callbacks, in-process MCP, interrupt, session-mirror frames) flows over that stdio. Catches:
  - With a custom transport, the SDK does **not** apply CLI-flag options for us.
  - It skips the SessionStore resume, so cross-host resume means writing the transcript into the sandbox and passing `resume=<id>`.
  - Set `CLAUDE_CONFIG_DIR` in `options.env`.
  - The existing local lane already uses a custom transport, so it likely never restores from SessionStore on resume; issue MO-73 verifies this.
- **Daytona stdin fit.** Daytona sessions accept stdin as text lines only and cannot send EOF. That matches stream-json input (newline-delimited JSON). Rules:
  - Echo must be suppressed (`suppress_input_echo=True`).
  - `end_input` maps to session termination.
  - Timeouts and kill are enforced by the adapter.
- **What this preserves.** Because control messages still flow through the worker:
  - in-process Kernel Hooks;
  - `can_use_tool`;
  - interrupt receipts;
  - `fork_session`;
  - the full `.claude/` cognition, SPEC-02 layout.
- **Model access.** The CLI calls Anthropic through the Model Gateway (§2), so the org key never enters the sandbox.
- **Session files.** The CLI writes them in the sandbox. Mission Control mirrors them through the SDK `SessionStore` (`session_store_flush="eager"`), so a resume can move hosts.

This is the recommended lane whenever the owner wants Claude Code's own behaviour in the cloud.

## 7. `codex` app-server with a remote executor

App-server runs in the worker with `OPENAI_API_KEY` from the Secret Broker. `environment/add{environmentId, execServerUrl: wss://…, authBearerToken}` points at `codex exec-server --listen` inside the SandboxHost, and threads select it through `TurnEnvironmentParams`.

- **Resolved from source (Q-S2), still experimental.** `environment/add{environmentId, execServerUrl, authBearerToken?, connectTimeoutMs?, skills?}` requires the `experimentalApi` capability; a token requires `wss://` or loopback. Threads and turns select environments with `{environmentId, cwd, runtimeWorkspaceRoots?}`.
  - **What executes remotely:** shell, filesystem reads, AGENTS.md discovery and command sandboxing. `apply_patch` is verified and approved in core, then applied through the remote filesystem.
  - **What stays worker-side:** approvals and hooks (`hook_runtime.rs`: "Hooks run on the host").
  - **Exec-server:** auth is `--ws-auth capability-token --ws-token-sha256`. A disconnected session is retained for 30 s; stdio cannot resume.
  - **Versions:** there is no hard version gate, so pin the same Codex release on both sides and check `executorVersion`.
  - **Daytona connectivity:** either the worker reaches the exec-server inside Daytona through a **signed preview URL** (one port, revocable, 24 h maximum; never the standard preview token, which unlocks the whole sandbox), or the worker runs a loopback relay over a stdio exec (no session resume). Whether the bearer header survives Daytona's proxy is checked in HL-16.
- **Fallback:** app-server inside the sandbox, reached over WebSocket. Codex supports `openai_base_url` and custom `model_providers{base_url, env_key}`, so the Model Gateway pattern applies.

## 8. Data-class policy (C3)

Every mission carries `data_class: public | internal | confidential | phi | secret`.

- `claude_managed` and `codex_agents` admit only `public` and `internal` by default. The owner may widen the list per Application up to `confidential`, never `phi` or `secret`.
- Sandbox Host lanes inherit the policy of the chosen sandbox provider.
- **Biotech missions are refused on these lanes unless the manifest declares a non-PHI class and the Application Binding allows it.**
- Sessions are deleted after custody plus the retention interval.

## 9. Declared matrices (summary)

`N` = native, `E` = emulated, `U` = unsupported, `?` = unqualified pending a drill.

| Control or feature | claude_managed cloud | claude_managed self_hosted | codex_agents hosted | codex_agents self_hosted | claude_agent_sdk @sandbox | codex @sandbox |
| --- | --- | --- | --- | --- | --- | --- |
| reattach | N | N | N | N | E (SessionStore) | E (thread resume) |
| send_turn (queue) | N | N | E (status-gated) | E | N | N |
| steer / inject | ? (mid-turn `user.message` injection observed in HL-23; native once HL-24 qualifies it) | E | N (steer) | N | E | N (`turn/steer`) |
| cancel | N | N | N | N | N | N |
| pause | E (budget gate) | E | E (tool gate only) | E | E (defer/tool gate) | E |
| per-tool approval | N (allow/deny) | N (full, our tools) | U (function tools only) | U | N | N |
| hooks (kernel) | U → custom tools | N (our tool wrappers) | U → function tools | U | N (in-process) | N (worker-side) |
| fork | E | E | E | E | N (conversation) + E (workspace) | N (`thread/fork`) |
| event replay | E (history list) | E | E (items list) | E | N (frames) | N |
| usage / cost | N / N (`list_cost`) | N / ? | N / E | N / E | N / E | N / E |
| budgets | N (hard, at create) | N | ? (`spend_control`) | ? | E (Mission Control governor) | E |
| repo / worktrees | GitHub mount; `git worktree` ? | N (lease) | E (upload/clone) | N (lease) | N (lease) | N (lease) |
| ZDR | U | U | U | U | provider-dependent | provider-dependent |

## 10. Owner prerequisites (added to the SPEC-05 catalog)

| # | Step | Verification |
| --- | --- | --- |
| MA1 | Console org and workspace; `ANTHROPIC_API_KEY` stored in the Secret Broker; spend limits | api_probe (`GET /v1/agents`) |
| MA2 | Console → Webhooks: register `https://<ingress>/v1/ingress/provider/anthropic`; store the `whsec_` secret | probe_mission (webhook received) |
| MA3 | Self-hosted only: Console → environment key for each self-hosted environment | api_probe (work poll) |
| MA4 | Fine-grained GitHub PATs (read-only per repo; a write PAT only if `publication: agent`) | api_probe (GitHub) |
| MA5 | MCP OAuth grants for any OAuth MCP servers (interactive) | api_probe (`mcp_oauth_validate`) |
| OA1 | Dedicated OpenAI project; restricted key with `api.agents.read/write` and `api.responses.write` (plus `api.vaults.*`, `api.traces.read`); project spend limit | api_probe |
| OA2 | Webhook endpoint `…/v1/ingress/provider/openai`; signing secret stored | probe_mission |
| OA3 | Self-hosted: environment key (`api.agents.environments.connect` only); sandbox egress to `api.openai.com` and `codex-cloud-environments.chatgpt.com` | api_probe (executor connects) |
| OA4 | Ask OpenAI to enable trace export (optional) | api_probe |
| SH1 | Sandbox provider account and API key (after HL-01), or Docker on the WSL2 worker | api_probe (create/exec/terminate) |
| SH2 | Model Gateway reachable from sandboxes: Docker via `host.docker.internal`; Daytona through the Vercel-hosted gateway on `*.vercel.app`, which is on the essential-services list for every tier (R16, R17) | probe_mission |
| SH3 | Record the Daytona tier from the dashboard limits page. It is informational: below Tier 3, `describe()` reports `egress_control: org_essential_services_only` | attestation |

## 11. Acceptance

The cloud placements are drilled in HL-24 (`claude_managed`) and HL-25 (`codex_agents`), launched remotely through the AWS worker (SPRINT S2, S3). The self-hosted and Sandbox Host drills are HL-20, funding-gated (R31). Prepare starts from pack files (R30, HL-07, HL-11) and moves to the full projection in HL-21.

- Both new profiles pass the lane conformance suite against fakes, and describe honestly per §9.
- **`claude_managed` cloud drill:**
  - A knowledge mission uploads skills, runs `mc_prepare`, emits signals, produces an output file, and settles usage and cost from `list_cost`.
  - The budget-gate pause and resume works.
  - An interrupt-and-inject works.
- **`claude_managed` self-hosted drill:**
  - A code mission on a Docker SandboxHost runs in a worktree lease.
  - The kernel deny works through the tool wrapper.
  - `mc_publish` pushes a verified bundle and the PR is created through the effect.
- **`codex_agents` drills:**
  - Hosted: a knowledge mission with artifacts.
  - Self-hosted: a code mission with exec-server in Docker.
  - Cancel, steer and the function-tool approval round trip.
  - Recovery after killing the worker mid-stream reconciles from items with no duplicate frames.
- **`claude_agent_sdk` @sandbox drill:** the Claude Code CLI in Docker through the Model Gateway; hooks fire in-process; resume on a different worker through `SessionStore`.
- **Policy refusals:**
  - A PHI-classed mission is refused on all API lanes.
  - No org API key is present in any sandbox env or file (sentinel test).


## 12. Resolved details from the final research pass (2026-10-12)

Sources:

- [research/daytona.md](research/daytona.md)
- [research/harness-in-sandbox.md](research/harness-in-sandbox.md)
- [research/vercel-ingress.md](research/vercel-ingress.md)

### 12.1 Daytona SandboxHost adapter (HL-02)

| Port method | Daytona mapping (`daytona` Python SDK 0.224.0, async) |
| --- | --- |
| `create` | From a **kit snapshot** (one per resource size; a snapshot fixes the resources). Name `mc-{run}-{unit}-{gen}`, labels `{run, unit, gen}`. `auto_stop_interval=0` with a hard TTL enforced by our reaper, because auto-stop ignores background processes and sockets. Never `public`. Network: `network_allow_list` (Tier 3+) or `network_block_all`; on Tier 1/2 only Daytona's essential-services list is reachable. Pass the key, URL and target explicitly: the SDK reads `.env` from the cwd and ignores `DAYTONA_API_URL`. |
| `exec` | One session per call; `execute_session_command(async)` with `suppress_input_echo=True`; stdout and stderr from the log WebSocket (replays from start on reconnect, so dedupe by offset); stdin as text lines through `send_session_command_input`. There is no EOF, no per-command kill and no session-command timeout: the adapter enforces timeouts by deleting the session. The exit code comes from command status. `process.exec` (blocking, 10 s default timeout, merged output) is used only for short probes. |
| `put_files` / `get_files` | Batch fs upload and download |
| `snapshot` / `restore` | Container sandboxes: stop, snapshot the filesystem only, then create a new sandbox from it. Unused snapshots go inactive after 2 weeks and still bill for storage. |
| `terminate` | Delete and wait; on failure, stop plus an auto-delete after the retention period |
| `describe` | `stdin: text_lines`, `snapshot: cold_filesystem`, `egress_control: org_essential_services_only` below Tier 3 (this sprint) or `domain_allowlist` from Tier 3, `max: 4 vCPU / 8 GiB / 10 GiB` |

Further facts:

- **Pricing:** about $0.0504 per vCPU-hour plus $0.0162 per GiB-hour, billed per second; 2 vCPU / 4 GiB costs about $0.17/h. $200 free credit.
- **Pools:** 10 vCPU (Tier 1) up to 500 vCPU (Tier 4).
- **Open source:** the repo was archived in June 2026 and development moved private, so there is no self-host fallback; the SDKs remain Apache-2.0.
- **Docker-on-WSL2 adapter parity:** it adds its own TTL reaper, an egress-proxy sidecar for allowlists, committed images as snapshots, local ports in place of preview URLs, and the same text-line stdin contract. Disk quotas are not enforceable on WSL2.

### 12.2 Model Gateway (HL-03)

- **Endpoints and headers:**
  - Accept `POST /v1/messages?beta=true` and optionally `/v1/messages/count_tokens`; reject other paths. `/v1/models` is called only when discovery is enabled.
  - Forward `anthropic-version`, `anthropic-beta` and the body **byte for byte**.
  - Stream responses unbuffered and keep `ping` events.
  - Pass through `retry-after` (integer seconds; above 60 stops Claude Code's retries), `x-should-retry` and error bodies unchanged.
- **Auth:** strip the per-run `ANTHROPIC_AUTH_TOKEN` (minted, digest-checked) and inject `x-api-key` with the org key.
- **Accounting:** capture usage per run, and return a hard 429 when the run budget is exhausted.
- **Sandbox env:**
  - `ANTHROPIC_BASE_URL=<gateway>`;
  - `ANTHROPIC_AUTH_TOKEN=<run token>`;
  - `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1`, so repo settings cannot redirect the base URL;
  - `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`;
  - `CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS=1`;
  - settings `skipWebFetchPreflight: true`. The WebFetch and fast-mode checks call `api.anthropic.com` directly.
- **What breaks it:** stripping beta headers while forwarding the body gives 400s; rewriting the body breaks preserved thinking.
- **Placement this sprint (R16, R17).** One module, two placements:
  - the **worker host**, for Docker on WSL2 through `host.docker.internal`;
  - **routes in the Vercel ingress project**, at `https://<project>.vercel.app/v1/gateway/anthropic`, for Daytona sandboxes on any tier.
- **Vercel placement constraints:**
  - The per-run token is checked in Postgres (`ingress_credential`, purpose `model_gateway`).
  - The org keys exist only as Production sensitive env vars, never in a sandbox.
  - `maxDuration` is 800 s (Pro) for streamed turns.
  - Requests above Vercel's 4.5 MB body cap get a typed 413 that states the size. Compaction keeps Claude Code well below it; large-context missions use the Docker placement.
  - Data class `internal` or lower only. PHI never routes through Vercel.

### 12.3 OpenAI self-hosted executor (HL-14)

- The executor registers through `/cloud/environment/{id}/register|connect|validate` with the environment key as `CODEX_API_KEY`, over an encrypted relay, reconnecting with 1–30 s backoff.
- Daytona's essential-services list includes `*.openai.com` and `*.chatgpt.com`, so this works on every Daytona tier.
- Treat in-flight calls as lost after a disconnect longer than 30 s; enforce the 5-minute connect deadline.
- **Do not** follow Daytona's guide of placing a broad key in the sandbox env: use only the environment key, whose scope is `connect` only.

### 12.4 Managed Agents self-hosted on Daytona (HL-10)

- Keep the worker on our side (local or a lane-only worker, MO-63). It polls Anthropic and executes tools through `SandboxHost.exec` in Daytona, so the sandbox needs no Anthropic credentials and only package egress.
- Daytona's guide runs the worker inside the sandbox with the environment key, where the agent could read it. Rejected.
