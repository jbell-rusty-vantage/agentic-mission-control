---
type: Research Note
title: "Harnesses with tools in remote sandboxes: SDK transport, Model Gateway, Codex exec-server, Managed Agents work queue (2026-10-12)"
description: "Source-level answers for the Claude Agent SDK custom transport, Claude Code LLM gateway requirements, Codex environment/add and exec-server, OpenAI self-hosted executors and the Managed Agents self-hosted work queue, with recommended designs for HL-03, HL-10, HL-14, HL-15 and HL-16."
tags: [mission-control, research, materialization-observation]
---

# Harness-in-sandbox research (2026-10-12)

Status legend: **RESOLVED** (read in source or official doc), **PARTIAL**, **UNVERIFIED** (inference or not found).

## Sources read

| Source | Version / commit | Local copy |
| --- | --- | --- |
| `claude-agent-sdk` wheel (PyPI) | 0.2.165, bundled CLI 2.1.294 (`_cli_version.py`) | (session scratchpad, not retained) |
| `anthropic` Python SDK wheel (PyPI) | 1.13.0 | (session scratchpad, not retained) |
| `github.com/openai/codex` (sparse clone, `main`) | `0c329ad2c9d5a2592128a1d536c66e16f9397e46` (2026-10-12T19:02Z) | (session scratchpad, not retained) |
| Claude Code docs | fetched 2026-10-12 | `research3/dl/cc-llm-gateway*.md`, `cc-env-vars.md`, `cc-data-usage.md` |
| Managed Agents docs | fetched 2026-10-12 (earlier pass) | `scratchpad/ma/*.md`, `scratchpad/research/raw/ma-*.md` |
| Repo lane code | working tree | `platform/mission-control/src/mission_control/adapters/claude/{transport,host,harness}.py`, `adapters/codex/*` |

Doc URLs: https://code.claude.com/docs/en/llm-gateway-protocol, https://code.claude.com/docs/en/llm-gateway-connect, https://code.claude.com/docs/en/env-vars, https://code.claude.com/docs/en/data-usage, https://platform.claude.com/docs/en/managed-agents/events-and-streaming, https://platform.claude.com/docs/en/managed-agents/budgets, https://platform.claude.com/docs/en/about-claude/pricing, https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes(-reference).

---

## Q-S1 — Claude Agent SDK custom transport — RESOLVED

### The abstraction

`claude_agent_sdk/_internal/transport/__init__.py` defines `class Transport(ABC)`, re-exported publicly as `claude_agent_sdk.Transport` (`__init__.py:67`, `__all__` line 627). Its docstring: *"This internal API is exposed for custom transport implementations (e.g., remote Claude Code connections). The Claude Code team may change or remove this abstract class in any future release."*

Abstract methods (exact):

```python
async def connect(self) -> None
async def write(self, data: str) -> None            # JSON + "\n"
def read_messages(self) -> AsyncIterator[dict[str, Any]]
async def close(self) -> None                       # called inside a shielded anyio scope; must bound its own awaits
def is_ready(self) -> bool
async def end_input(self) -> None                   # close stdin
```

Entry points accepting it:

- `ClaudeSDKClient.__init__(self, options: ClaudeAgentOptions | None = None, transport: Transport | None = None)` (`client.py:67-71`).
- `query(*, prompt, options=None, transport: Transport | None = None)` (`query.py:12-16`).

Documented consequences of a custom transport (`query.py:63-70`, `client.py:117-128`):

1. CLI-flag options (model, cwd, permission mode, tools, ...) are **not** applied by the SDK; the transport owns the command line.
2. Hooks, `agents`, skills, `excludeDynamicSections` etc. still go through the **initialize control request** (`_internal/query.py:330-360`), so they work.
3. **Store-backed resume is skipped** (`materialize_resume_session` is only called when `transport is None`).

### What `SubprocessCLITransport` does (0.2.165)

- `_find_cli()` locates the bundled CLI unless `options.cli_path` is set.
- `_build_command()` (`subprocess_cli.py:570-795`): `[cli_path, "--output-format", "stream-json", "--verbose", ...]`. It adds `--system-prompt`/`--append-system-prompt`, `--tools`, `--allowedTools`, `--permission-prompt-tool stdio` (when `can_use_tool` is set via `_configure_can_use_tool`, `types.py:1927-1949`), `--resume=`, `--settings`, `--add-dir`, `--mcp-config` (SDK MCP servers are declared as `type: sdk` and served over the control channel), `--session-mirror` when `session_store` is set (line 723), `--setting-sources=`, plugin dirs, `--json-schema`, and always `--input-format stream-json`.
- `connect()` (lines 797-915): optional `cli -v` version probe (skipped by `CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK`); env = `{**os.environ minus CLAUDECODE, CLAUDE_CODE_ENTRYPOINT=sdk-py, **options.env, CLAUDE_AGENT_SDK_VERSION}` plus `CLAUDE_CODE_SDK_READS_SESSION_STATE=1`, optional `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING`, `PWD=cwd`, OTEL `TRACEPARENT`; spawns `anyio.open_process(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE-if-callback, cwd=cwd, env=..., user=...)`.
- Reading: NDJSON line framer over stdout, non-JSON lines skipped; after EOF `await process.wait()` and a non-zero exit raises `ProcessError`.
- `close()`: close stdin, wait 5 s, `terminate()`, wait 5 s, `kill()`; tracks children in `_ACTIVE_CHILDREN` (atexit `send_signal(SIGTERM)`).
- Process attributes used: `stdin`, `stdout`, `stderr` (anyio byte streams), `returncode`, `wait()`, `terminate()`, `kill()`, `send_signal()`.

### Does the control protocol share stdio? Yes

`_internal/query.py` handles inbound control requests `can_use_tool` (line 586), `hook_callback` (640), `mcp_message` (656) and sends outbound `interrupt`, `set_permission_mode`, `set_model`, `rewind_files`, `mcp_reconnect`, `mcp_toggle`, `stop_task`, `get_context_usage`, `mcp_status` — all through `transport.write`/`read_messages`. `transcript_mirror` frames (SessionStore write path) also arrive on stdout (line 428). **So in-process hooks, `can_use_tool`, SDK MCP tools, interrupt and SessionStore mirroring keep working over any byte pipe.** Hooks defined in the repo's `.claude/settings.json` (command hooks) execute *inside the sandbox* (the CLI spawns them); only SDK callback hooks run in the worker.

### What the repo already has

`adapters/claude/transport.py::ExplicitEnvironmentCliTransport(SubprocessCLITransport)` already overrides `connect()` and takes an injectable `spawn: Callable[..., Awaitable[Process]]` (default `anyio.open_process`), keeping `_build_command`, framing, stderr and shielded `close()`. `SdkClientFactory.create` builds `ClaudeSDKClient(configured, transport=...)`. **This is the seam for HL-15.**

### Bridging options compared

| | A. Process adapter over `SandboxHost.exec` (via existing `spawn` seam) | B. `cli_path` → local shim that proxies stdio |
| --- | --- | --- |
| Command | `_build_command()` with `options.cli_path` = in-sandbox path (e.g. `/usr/local/bin/claude`) | Shim must parse/forward argv |
| cwd | Passed to `SandboxHost.exec(cwd=sandbox path)`; nothing local needs to exist | `anyio.open_process(cwd=...)` needs a **local** existing dir; a sandbox path fails with `FileNotFoundError` → mis-mapped to `CLINotFoundError` |
| env | Explicit allowlist built by us (already the repo's pattern) | Shim receives the worker's full environment; must filter (leak risk) |
| Version probe | Disable (`check_version=False`) and probe via `exec` ourselves | `shim -v` must be proxied |
| Signals / close | Adapter maps `terminate/kill` to sandbox exec cancel/kill | Shim must propagate SIGTERM/SIGKILL remotely; double process |
| Failure visibility | Exec-channel errors typed in Python | Opaque shim exit codes |
| SDK coupling | Private class `SubprocessCLITransport` (already pinned with `_RELIED_ON` guard) | None on SDK internals, but on Windows the batch-shim rule (`_reject_windows_batch_cli`) applies |

**Recommendation: A.** It reuses code the repo already ships and keeps every control path in-process. B is only a fallback if `SubprocessCLITransport` changes shape.

Requirements A places on `SandboxHost.exec` (add to the port contract): separate stdout/stderr byte streams; **stdin half-close** (EOF must reach the CLI, used by `end_input()`/`close()`); a remote `terminate`/`kill`; exit-code delivery; back-pressure; no TTY. Docker `exec` attach with `CloseWrite` satisfies this; check each HL-01 provider.

### Resume across hosts (SessionStore)

- Mirroring works with a custom transport (frames arrive on stdout; `--session-mirror` comes from `_build_command`). `build_mirror_batcher` resolves `projects_dir` from `options.env["CLAUDE_CONFIG_DIR"]` (`session_resume.py:97-127`, `sessions.py:130-141`), then `file_path_to_session_key` uses `os.path.relpath(file_path, projects_dir)`. **Set `options.env["CLAUDE_CONFIG_DIR"]` to the sandbox path** so keys resolve; the worker must be POSIX (already enforced by `host.py`).
- Resume from the store is **not** done for custom transports. HL-15 must materialize it itself: load entries from the store, `put_files` them to `<sandbox CLAUDE_CONFIG_DIR>/projects/<project_key_for_directory(cwd)>/<session_id>.jsonl` (+ `<session_id>/subagents/agent-*.jsonl` via `list_subkeys`), then connect with `resume=<id>`. Mirror the SDK's own logic in `session_resume.py:130-195`. **Use a fixed in-sandbox cwd** (e.g. `/workspace/unit`) so `project_key` is stable across hosts.
- Note: this also means the **current local lane** (custom transport + `StateRootSessionStore`) never gets store-backed resume from the SDK; it relies on local session files. Worth a test.

---

## Model Gateway (HL-03) — RESOLVED from docs

Claude Code facts (https://code.claude.com/docs/en/llm-gateway-protocol, `llm-gateway-connect`, `env-vars`):

- **Endpoints** for the Anthropic Messages format: `POST /v1/messages` (sent as `/v1/messages?beta=true`; match on path), optional `POST /v1/messages/count_tokens` (absent → character estimate). Best-effort startup `HEAD /api/hello` (may be rejected). `GET /v1/models?limit=1000` only when `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`.
- **Forward unchanged:** `anthropic-version`, `anthropic-beta` (verbatim, do not allowlist values), all `anthropic-*` headers and body fields as open lists; keep `system` array and `cache_control` untouched.
- **Consumable headers:** `Authorization` / `x-api-key` (gateway credential), `x-claude-code-session-id`, `x-claude-code-agent-id`, `x-claude-code-parent-agent-id`; hint headers (`x-claude-code-request-class`, `-agent-type`, `-compaction`, `-prompt-id`, `-prev-tool-durations`) only with `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`.
- **Credential variables:** `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer`; `ANTHROPIC_API_KEY` → `x-api-key`; `apiKeyHelper` → both (cached 5 min, `CLAUDE_CODE_API_KEY_HELPER_TTL_MS`). `ANTHROPIC_CUSTOM_HEADERS` = newline-separated `Name: Value`.
- **Streaming:** never buffer; preserve `ping` events (idle watchdog, `CLAUDE_STREAM_IDLE_TIMEOUT_MS` min 300000); full sequence to `message_stop`; `content-type: text/event-stream`.
- **Response headers:** `retry-after` as integer seconds (>60 stops retries immediately), `x-should-retry` passthrough, `anthropic-ratelimit-unified-*` passthrough; forward **error bodies unmodified** (Claude Code's capability-rejection retry matches upstream wording).
- **What breaks:** stripping `anthropic-beta` while passing body fields → hard 400s (context management, tool `strict`/`defer_loading`, `output_config`); rewriting bodies breaks preserved-thinking (`bound to a different conversation`); buffering → stalls. MCP tool search is off behind a non-first-party base URL unless `ENABLE_TOOL_SEARCH=true`. Remote Control is disabled. Fast-mode check and the **WebFetch domain safety check call `api.anthropic.com` directly**; with egress blocked set `skipWebFetchPreflight: true` (settings) and `CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS=1`. Gateway sessions are not HIPAA-eligible.
- `CLAUDE_CODE_SKIP_{BEDROCK,VERTEX,FOUNDRY,MANTLE,ANTHROPIC_AWS}_AUTH` only matter for cloud-provider formats; not needed for an Anthropic-format gateway.
- `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`: Claude Code then **ignores endpoint/auth variables from settings files**, so a repo's `.claude/settings.json` `env` cannot redirect `ANTHROPIC_BASE_URL` (token exfiltration guard).
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` stops telemetry/updates/release notes (does not cover WebFetch preflight).

Codex (for the §7 fallback): `codex-rs/model-provider-info/src/lib.rs` supports `openai_base_url` and custom `[model_providers.<id>]` with `base_url`, `env_key`, `http_headers`, `env_http_headers`, `wire_api = "responses"`. **OpenAI base-URL override exists in source** (Responses API gateway would need `/v1/responses` streaming passthrough; UNVERIFIED end-to-end).

---

## Q-S2 — Codex app-server remote executors — RESOLVED (source), experimental

Source: `codex-rs/exec-server/README.md`, `codex-rs/app-server-protocol/src/protocol/{common.rs,v2/environment.rs,v2/turn.rs,v2/thread.rs}`, `codex-rs/exec-server-protocol/src/protocol.rs`, `codex-rs/cli/src/exec_server_command.rs`, `codex-rs/core/src/{hook_runtime.rs,agents_md.rs,tools/orchestrator.rs,tools/handlers/apply_patch.rs}` at `0c329ad`.

### App-server side (experimental; requires `initialize.capabilities.experimentalApi`)

- `environment/add` (`#[experimental("environment/add")]`, `common.rs:1224`):
  `{environmentId, execServerUrl, authBearerToken?, websocketRequestId?, connectTimeoutMs?, skills?: {required?: string[]}}` → `{}`. Token "requires a secure transport or a loopback destination", is redacted, and is reused on reconnect without refresh.
- `environment/info {environmentId}` → `{shell:{name,path}, cwd?: file-URI}` (30 s timeout).
- `environment/status {environmentId}` → `{status: ready|pending|disconnected|unknown, error?}` (no recovery triggered).
- `thread/start.environments` and `turn/start.environments`: `TurnEnvironmentParams {environmentId, cwd, runtimeWorkspaceRoots?}` (`turn.rs:96`). Omitted = sticky thread env; empty = disable env access; first entry = current turn env. Thread exposes `environments: ThreadEnvironment[]` (experimental).

### Exec-server (`codex exec-server`, marked **[EXPERIMENTAL]** in `exec_server_command.rs:31`)

- Transports: `--listen ws://IP:PORT` (default) or `--listen stdio`; `--remote URL --environment-id ID [--name]` (registry mode); `forward --connect ws://... --remote ... --environment-id ...`.
- Auth for direct listeners: app-server's `--ws-auth capability-token --ws-token-sha256 HEX`, token files, signed bearer; client sends `Authorization: Bearer TOKEN`. Auth flags do not apply to stdio.
- Lifecycle: `initialize {clientName, resumeSessionId?}` → `{sessionId, environmentInfo{shell, executorVersion, providerId?, cwd, capabilities}}`, then `initialized`. Requests sequential unless `--concurrent-requests N`.
- Methods: `process/start {processId, argv, cwd(file URI), env, tty, pipeStdin, arg0}`, `process/read`, `process/write` (base64), `process/signal`, `process/terminate`; notifications `process/output`, `process/exited {exitCode, sandboxDenied}`, `process/closed`; `fs/readFile|writeFile|open|readBlock|writeBlock|close|createDirectory|getMetadata|canonicalize|readDirectory|remove|copy|walk` (optional `sandbox` policy → helper process); `http/request` (+`bodyDelta`); `network/policyRequest|policyDecision`; `environment/info|status`; `environmentConfig/read`; `capabilities/discoverV2`, `capabilityRoots/discoverV1`.
- Retention: a detached session survives **30 s** (`server/session_registry.rs:20`); client recovery waits 25 s (`client_recovery.rs:63`). Stdio "serves exactly one connection, so detached sessions cannot be resumed" (`server/transport.rs:173`).
- Remote registration: `POST {remote}/cloud/environment/{id}/register` (Noise public key), `/connect`, `/validate` (`remote.rs:158,240,344`), bearer from `CODEX_API_KEY` (or ChatGPT login / Agent Identity / SigV4); Noise-encrypted protobuf relay frames; reconnect backoff 1 s → 30 s, stable after 120 s (`remote/reconnect_backoff.rs`).

### What runs where

| Concern | Location | Evidence |
| --- | --- | --- |
| Shell / `exec_command` / unified exec | **Executor** (`process/*`) | `core/src/tools/runtimes/unified_exec*` (`is_remote`) |
| `apply_patch` | Verified + approved in core; **applied through the executor filesystem**, sandbox `ExecutorManaged` | `tools/runtimes/apply_patch.rs:1-5`, `handlers/apply_patch.rs:486` |
| File reads, AGENTS.md discovery | **Executor filesystem** | `core/src/agents_md.rs:61-107` (`environment.get_filesystem()`) |
| Sandboxing of commands | **Executor** (Linux sandbox/bwrap in the sandbox image) | orchestrator rejects escalation if executor lacks `linux_approved_root_write_preserves_restrictions` (`orchestrator.rs:265-282`) |
| Approvals (`request_approval`) | **App-server / core (worker)** → client JSON-RPC | `tools/orchestrator.rs:127-222` |
| Hooks (`PreToolUse` etc.) | **App-server host (worker)** as local processes | `hook_runtime.rs:248-252`: "Hooks run on the host, so a remote workspace cannot replace the local fallback"; `hooks/src/engine/command_runner.rs` uses local `Command` |
| Hook config discovery | Host filesystem (`hooks/src/engine/discovery.rs:348` `std::fs`) | project `.codex` hooks inside the remote repo: UNVERIFIED (likely not discovered) |
| MCP servers | Can be bound to an `environment_id` | `core/src/config/config_tests.rs:6921-6967` |

**Version compatibility:** no hard version gate found; compatibility is capability flags (`EnvironmentCapabilities`) plus informational `executorVersion`/`providerId` (`exec-server-protocol/src/protocol.rs:140-180`). Mission Control must pin the same Codex release on both sides and assert `executorVersion` itself.

**OpenAI Agents API `self_hosted`:** the sandbox runs `codex exec-server --remote <session.environment.remote_url> --environment-id <id>` with the environment key as `CODEX_API_KEY` (scope `api.agents.environments.connect`), Noise relay to `codex-cloud-environments.chatgpt.com`, automatic reconnect, 5-minute connect window (see `research/openai-hosted-agents.md` W9/W21; registration endpoints confirmed above). A disconnect beyond the 30 s retention loses running processes; files persist only as long as our sandbox does.

---

## Anthropic Managed Agents self-hosted work queue — RESOLVED (SDK source)

Source: `anthropic` 1.13.0 `resources/beta/environments/work.py`, `lib/environments/{_poller.py,_worker.py}`, `lib/tools/{_beta_session_runner.py,agent_toolset.py}`, `types/beta/environments/*`. All calls carry `anthropic-beta: managed-agents-2026-04-01`.

### Endpoints

| Call | HTTP | Params |
| --- | --- | --- |
| `work.poll(environment_id, block_ms?, reclaim_older_than_ms?, anthropic_worker_id?)` | `GET /v1/environments/{env}/work/poll` | `block_ms` 1–999 (SDK uses 999, client jitter 1–3 s on empty); `reclaim_older_than_ms` default 5000 (re-claims *un-acked* items); header `Anthropic-Worker-ID`. Returns `BetaSelfHostedWork \| None` |
| `work.ack(work_id, environment_id)` | `POST …/work/{id}/ack` | `queued → starting`, removes from queue |
| `work.heartbeat(work_id, environment_id, desired_ttl_seconds?, expected_last_heartbeat?)` | `POST …/work/{id}/heartbeat` | Optimistic concurrency: first beat `NO_HEARTBEAT`, then echo server `last_heartbeat`; **412** = lease lost. Response `{last_heartbeat, lease_extended, state, ttl_seconds}` |
| `work.stop(work_id, environment_id, force?)` | `POST …/work/{id}/stop` | graceful or forced |
| `work.retrieve/update/list/stats` | `GET/POST …/work[/{id}]`, `…/work/stats` | |

`BetaSelfHostedWork`: `{id, state: queued|starting|active|stopping|stopped, data: {type: "session", id: session_id}, secret?, metadata, created_at, acknowledged_at, started_at, latest_heartbeat_at, stop_requested_at, stopped_at}`. The queue also sends `healthcheck` items (`_worker.py` comment). `secret` is base64url JSON containing a per-item **`sessions_token`** (bearer for heartbeat/stop/events/memory stores); the environment key is the fallback.

### Lease

- Heartbeat interval = `min(ttl/2, 30 s)`, default 30 s; assumed TTL 90 s before the first response (`_worker.py:95-98`); the runner's comment calls **300 s "the server's default work-item lease TTL"** (`_beta_session_runner.py` `SEND_RETRY_WINDOW`). Use the server-returned `ttl_seconds`; `desired_ttl_seconds` can request another value (bounds UNVERIFIED).
- Lease ends on 412 (lost), fatal 4xx, `state in (stopping, stopped)` or `lease_extended == false` (control-plane stop), or no successful beat within TTL (assumed lost).
- **Worker death:** heartbeats stop; after TTL the item can be reclaimed by another worker's poll (`reclaim_older_than_ms` covers un-acked items; reclaim of acked-but-expired leases inferred from the 412/"re-queued" wording, UNVERIFIED exact path). Sessions live server-side, so a new worker re-attaches; the runner reconciles from `events.list` and re-dispatches every unanswered tool call. **Tool execution must therefore be idempotent or guarded by Operation Intents.** Running processes/files on the dead worker are lost unless the lease (our sandbox) survives.

### Tool flow

- `SessionToolRunner` opens `events.stream`, then reconciles `events.list(limit=1000)`; dedupes by event id (`_seen`) and answered ids (`_answered`).
- `agent.tool_use` (built-in toolset) → `user.tool_result {tool_use_id, is_error, content}`; `agent.custom_tool_use` → `user.custom_tool_result {custom_tool_use_id, ...}`. `agent.mcp_tool_use` runs server-side.
- `evaluated_permission == "ask"` calls are held until `user.tool_confirmation`; `deny` never executes.
- Unowned tool names are left pending (partial-fulfillment contract: a backend can answer `mc_*` custom tools while the sandbox worker answers built-ins).
- **Limits of the SDK runner:** one call at a time, `TOOL_TIMEOUT = 150.0` s per call (must exceed `BASH_DEFAULT_TIMEOUT = 120.0`), posts an `is_error` "timed out" result; result send retried up to the lease TTL; `max_idle` default 60 s.
- **Custom implementations:** `EnvironmentWorker(client, environment_id=..., environment_key=..., tools=lambda ctx: [...], workdir=...)`; tools are `BetaAsyncFunctionTool` (e.g. wrap `beta_bash_tool(ctx)`, `beta_read_tool`, `beta_write_tool`, `beta_edit_tool`, `beta_glob_tool`, `beta_grep_tool`, or replace them). `AgentToolContext(workdir, allowed_roots, read_only_roots, max_file_bytes, client, session)`. Results from `user.tool_result`/`user.custom_tool_result` are processed on receipt (`processed_at` populated immediately).

### Q-M2 — server-side max wait for a tool result — UNVERIFIED

No documented limit. Evidence: SDK abandons a result send only after the lease TTL; workflow runs have a 24 h lifetime that counts time waiting on the client (`workflow-runs.md`). Runtime is billed only while `running`; whether a pending built-in `agent.tool_use` keeps the session `running` (billed) or idle is not stated. Needs a drill (hold a bash result for 10/30/60 min with heartbeats).

---

## Q-M1 / Q-M4 — message injection and interrupt — Q-M1 ANSWERED (HL-23), Q-M4 PARTIAL

From events-and-streaming:

- Sent events are queued: `processed_at` is null "while the event is still queued behind earlier events"; tool results/confirmations/`define_outcome` are processed on receipt.
- **Q-M1:** a `user.message` sent while `running` is queued; the docs never say it is injected between tool calls of the current turn. Treat it as **next-turn delivery** (queue semantics), observable through `processed_at`. **Superseded by the HL-23 [provider smoke](provider-smoke-2026-10.md):** the message is injected at the next model-request boundary of the current turn. A `user.message` while `idle{requires_action}` returns **400** (answer pending calls first). `system.message` exists and must trail a tool result in that state.
- **Q-M4:** interrupt order: the interrupt applies (model response stops immediately; can wait for running tool calls), the `user.interrupt` appears on the stream, the turn ends with `session.status_idle{end_turn}`, and "the agent starts its next turn with the `user.message` you sent after the interrupt". The fate of messages queued **before** the interrupt is not documented (UNVERIFIED; drill needed). Interrupt ends no workflow runs.

## Q-M3 — runtime in `list_cost` — RESOLVED (docs)

`budgets.md`: `usage.active_seconds` "is the running time its runtime cost is priced on"; per-thread figures "exclude the session's running-time cost, so they don't sum exactly to the session's `list_cost`" → session `list_cost` includes the $0.08/session-hour runtime (`pricing.md`: metered on `running` duration only).

## Q-O2..Q-O4

- **Q-O2 (AGENTS.md honoured by the Agents API harness): PARTIAL.** Open-source Codex core reads AGENTS.md through the *environment filesystem* (`agents_md.rs`), so a self-hosted executor's repo AGENTS.md would be read if the hosted service runs the same core. The hosted build is not inspectable: keep inlining critical rules. **Answered by the HL-23 [provider smoke](provider-smoke-2026-10.md):** a hosted `/workspace/AGENTS.md` is honoured once the environment is connected (not on a turn answered before `environment.ready`).
- **Q-O3 (vault placeholder for git HTTPS) and Q-O4 (`spend_control`): UNRESOLVED** by this pass (service behaviour, no source).

---

## Recommended designs

### HL-03 — Model Gateway

1. **Placement:** `interfaces/http/model_gateway.py` behind the D3 ingress, at `https://<gw>/anthropic` (base URL). Sandbox egress allowlist = gateway host only (plus kit mirrors).
2. **Token:** per-run (per lease) opaque token minted by `application/secrets`: random 256-bit, stored hashed with `{run, unit, generation, lease_id, model_allowlist, expires_at, budget_cents}`; revoked at custody/terminate. Deliver as `ANTHROPIC_AUTH_TOKEN` (Bearer). Accept `x-api-key` too (helper/discovery send both).
3. **Request handling:** allow only `POST /v1/messages`, `POST /v1/messages/count_tokens`, `HEAD /api/hello` (204); everything else 403. Verify token → strip `Authorization` and `x-api-key` → set `x-api-key: <org key from Secret Broker>` → forward all other headers (`anthropic-*` verbatim) and the **body byte-for-byte**. Model allowlist: parse a copy of the JSON, never rewrite; reject with 400 if disallowed.
4. **Response handling:** stream unbuffered (chunked passthrough, keep `ping`), no gateway idle timeout under 30 min; pass `retry-after`, `x-should-retry`, `anthropic-ratelimit-unified-*`, `request-id`, error bodies unchanged.
5. **Usage capture:** tee the SSE and record `message_start.usage` + final `message_delta.usage` per request, keyed by run and `x-claude-code-session-id`/`x-claude-code-agent-id`; settle as `observed` usage. Budget exhaustion → `429` + `retry-after: 3600` + `x-should-retry: false` (Claude Code stops retrying at >60 s).
6. **Sandbox env for the CLI:** `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN=<run token>`, `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_AUTOUPDATER=1`, `CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS=1`, `ANTHROPIC_DEFAULT_HAIKU_MODEL=<pinned>` (background model behind a bearer credential otherwise defaults to the main model), optional `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`; managed settings `skipWebFetchPreflight: true` + WebFetch permission rules. Never `ANTHROPIC_API_KEY`.
7. **Sentinel test:** scan sandbox env, `/proc/*/environ`, config dirs and mirrored transcripts for the org-key prefix.
8. **Codex:** same gateway shape on `/openai` for `/v1/responses` with `openai_base_url` or a `[model_providers.mc]` entry (`env_key = "MC_RUN_TOKEN"`); only needed for the §7 fallback.

### HL-10 — `claude_managed` self-hosted worker

1. Do **not** use `EnvironmentWorker.run()` as is. Compose: our poller (`work.poll` 999 ms, `anthropic_worker_id = mc-<worker>`), `work.ack`, our heartbeat loop copying `_heartbeat_loop` semantics (`NO_HEARTBEAT` → echo `last_heartbeat`, 412 = lost, stop on `stopping|stopped|!lease_extended`, interval `min(ttl/2, 30)`), and our runner.
2. Credentials: environment key (Console) in the worker only, never in the sandbox; prefer the per-item `sessions_token` from `secret` for session calls.
3. Runner: stream-then-reconcile with `_seen`/`_answered` dedupe (same as SDK); concurrent dispatch where safe; **no 150 s cap** (per-tool deadline from the manifest); each built-in tool implemented as a wrapper that runs Stop Fence → Operation Intent keyed `(session_id, tool_use_id)` → kernel policy → `SandboxHost.exec`/`put_files`/`get_files` in the lease → frame capture → `user.tool_result`.
4. Idempotency: a reconcile after worker death re-dispatches unanswered calls; the Operation Intent ledger decides replay vs. "already applied" result.
5. Long tools: keep heartbeating; post interim nothing (no progress event exists); drill Q-M2 before relying on > 10 min tools.
6. End: `work.stop(force=True)` unless lease lost; sandbox lifetime bound to the lease, not to the work item.

### HL-14 — `codex_agents` self-hosted executor

1. SandboxHost image with the **pinned** Codex release; start `CODEX_API_KEY=<environment key> codex exec-server --remote <remote_url> --environment-id <id> --name mc-<run>-<unit>` via `SandboxHost.exec` immediately on `action_required{environment_connection}` (webhook wake) or before input; enforce the 5-minute connect deadline with a timer that fails the attempt.
2. Environment key from the Secret Broker, scope `api.agents.environments.connect` only; egress allowlist `api.openai.com`, `codex-cloud-environments.chatgpt.com`.
3. Reconnect: the executor reconnects itself (backoff 1–30 s); processes survive only 30 s detached. On executor restart, treat in-flight tool calls as lost (the harness may fail them) and reconcile from items.
4. Version: read `executorVersion` from executor logs or a probe `codex --version` in the sandbox and record it; refuse unpinned images.
5. Snapshot via SandboxHost; files persist with our sandbox regardless of session state.

### HL-15 — `claude_agent_sdk` on Sandbox Host

1. Add `SandboxProcess` (anyio `Process` duck type: `stdin`, `stdout`, `stderr`, `returncode`, `wait`, `terminate`, `kill`, `send_signal`) over `SandboxHost.exec(argv, cwd, env, stdin=…)`; pass `spawn=sandbox_spawn(handle)` and `check_version=False` to `ExplicitEnvironmentCliTransport`. Do the version probe with a separate `exec(["claude","-v"])` and compare to `BUNDLED_CLI_VERSION`.
2. Options: `cli_path=/usr/local/bin/claude` (pinned in the kit image), `cwd=/workspace/unit` (fixed), `env` = gateway set (HL-03) + `CLAUDE_CONFIG_DIR=/home/agent/.claude-mc`; `session_store=StateRootSessionStore`, `session_store_flush="eager"`.
3. All paths in `--add-dir`, `--mcp-config` (non-SDK servers), `--settings`, plugin dirs must be sandbox paths; materialize the `.claude/` projection into the sandbox with `put_files`.
4. Cross-host resume: our own materialization (store → `put_files` JSONL under `projects/<project_key>/`) then `resume=<id>`; never copy credentials (gateway token is re-minted).
5. Extend the `SandboxHost.exec` contract: stdin half-close, kill, exit code, separate stderr; add a conformance test that `end_input()` reaches the CLI and that an `interrupt` control request round-trips.
6. Remove the Windows host gate only for this path if the exec channel is not a local subprocess (UNVERIFIED: `host.py` gate exists because of local spawning on Windows selector loops; a pure-network exec channel avoids it).

### HL-16 — Codex app-server with a remote exec-server

1. Keep `codex app-server` in the worker (approvals, hooks, `turn/steer`, `thread/fork` all stay worker-side — confirmed). Initialize with `capabilities.experimentalApi = true`.
2. Executor transport, preferred: sandbox runs `codex exec-server --listen ws://0.0.0.0:PORT --ws-auth capability-token --ws-token-sha256 <sha>`; SandboxHost exposes the port over TLS (`wss://`), and the worker calls `environment/add {environmentId: "mc-<lease>", execServerUrl: "wss://…", authBearerToken, connectTimeoutMs: 300000}`. Alternative with no inbound port: a **worker-local loopback WebSocket relay** bridging to `SandboxHost.exec(["codex","exec-server","--listen","stdio"])` (loopback allows a bearer without TLS; but stdio cannot resume detached sessions, so a dropped exec channel kills all processes).
3. Threads: `thread/start.environments = [{environmentId, cwd: "/workspace/unit", runtimeWorkspaceRoots: ["/workspace/unit"]}]`; per-turn override only when switching leases.
4. Hooks: configure in the worker's `CODEX_HOME` (host-side discovery); they run on the worker with a local cwd fallback, so hook scripts must not assume the repo is local (use `environment/info` or Mission Control APIs). Repo-local `.codex` hooks are not relied on.
5. Health: poll `environment/status`; on `disconnected`, the client recovers within 25 s of the 30 s retention; beyond that mark the turn's running commands lost.
6. Pin the same Codex version for app-server and exec-server; check `initialize.environmentInfo.executorVersion` equality and required `capabilities` flags (`file_write_streaming`, `shell_snapshot_v2`, Linux restriction flags) before admitting the lane.
