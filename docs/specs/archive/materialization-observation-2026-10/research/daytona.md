---
type: Research Note
title: "Daytona fact sheet and SandboxHost adapter design (read 2026-10-12)"
description: "Daytona Python SDK, process sessions and stdin limits, files and git, egress tiers, preview URLs, snapshots, lifecycle, limits, pricing, official guides, Docker-on-WSL2 parity and a method-by-method SandboxHost adapter design."
tags: [mission-control, research, materialization-observation]
---

# Daytona as the managed SandboxHost provider

Everything below was read on 2026-10-12. The citation keys are listed in §11. **VERIFIED** means it was read in a primary source (SDK source, OpenAPI, official docs or guide). **UNVERIFIED** means it was inferred or not found. **SRC** means it was read in code.

## 0. Headline findings

1. **The SDK is current and async-capable.** The `daytona` package is at **0.224.0**, released 2026-10-12 [S1]. `daytona_sdk` 0.224.0 is a deprecated alias [S1]. `AsyncDaytona` and `AsyncSandbox` are first-class [S2].
2. **The open-source repo is frozen.** The `daytonaio/daytona` GitHub repository is **archived**: "As of June 2026, Daytona's core development has moved to a private codebase". The last public tag is v0.190.0 [S5]. The SDKs remain Apache-2.0 on PyPI and npm. A self-hosted Daytona is therefore no longer a viable fallback; the only path to our own compute is the enterprise "bring your own compute" offering [D-byoc].
3. **Streaming stdin is possible, but line-oriented text only.**
   - An async session command reads stdin from a FIFO.
   - `send_session_command_input(session, cmd, data: str)` appends `\n` if it is missing.
   - It echoes the input into stdout unless `suppress_input_echo=True`.
   - Sources: [S2, S3, S5 `session/input.go`].
   - That is enough for Claude Code `--input-format stream-json`, which is newline-delimited JSON. It cannot send binary data, and it has no stdin-EOF or close-stdin call.
4. **Egress allowlisting depends on the tier.** Tier 1 and Tier 2 **cannot override** the organisation network policy: only the fixed "essential services" list is reachable, so a custom Model Gateway host is **not** reachable. Tier 3+ (a $500 top-up) gets strict per-sandbox `domain_allow_list` (up to 100 domains, wildcards), `network_allow_list` (up to 10 IPv4 CIDRs) or `network_block_all` [D-network, D-limits].
5. **Outbound WebSockets work.** The Agents API `codex exec-server --remote` pattern is Daytona's own guide [G-oai]. The Managed Agents worker pattern is also Daytona's own guide [G-cma].
6. **Inbound WebSockets also work.** Preview URLs "fully support WebSocket connections" [D-proxy], so a worker can reach `codex exec-server --listen` at `wss://<port>-<token>.<proxy-domain>`. Daytona secret substitution does **not** work on upgraded WebSocket connections [G-oai §6].
7. **Snapshot and restore are cold only on containers.**
   - On container sandboxes, `sandbox.create_snapshot(name)` captures the filesystem only. The docs table requires the sandbox to be **Stopped**.
   - `fork`, pause and memory snapshots are **VM-sandbox-only**.
   - A snapshot is restored by creating a new sandbox from the named snapshot.
   - Unused snapshots go inactive after 2 weeks.
   - Sources: [D-snapshots, D-sandboxes, S2].
8. **Price.** $0.0504 per vCPU-hour, $0.0162 per GiB-hour of RAM, and $0.000108 per GiB-hour of disk after the first 5 GiB free, billed per second. There is $200 of free compute [P-pricing]. A 2 vCPU / 4 GiB / 10 GiB sandbox costs about **$0.166/h** while running.
9. **Credential check (one free, read-only call).**
   - The call was `GET https://app.daytona.io/api/sandbox?limit=20` and returned **200 with 0 sandboxes**.
   - The response header was `X-RateLimit-Limit-authenticated: 50000`, which equals the documented Tier 4 general rate. The actual tier is **UNVERIFIED**; check it at app.daytona.io/dashboard/limits, because egress control depends on it.

## 1. Python SDK and client init

| Item | Fact | Source |
| --- | --- | --- |
| Package | `daytona` 0.224.0 (requires Python >=3.10,<4). The 0.22x line ships almost daily (0.216.1 on 09-23 → 0.224.0 on 10-12). `daytona_sdk` 0.224.0 is the summary "Deprecated: please migrate to the 'daytona' package". npm: `@daytona/sdk` 0.224.0. | S1 |
| Dependencies | aiohttp, httpx, httpx-ws, python-socketio, obstore, python-dotenv, OTel, and generated `daytona-api-client(-async)` / `daytona-toolbox-api-client(-async)` 0.224.0 | S1 |
| Async | `from daytona import AsyncDaytona, AsyncSandbox`, with `async with AsyncDaytona() as d:`. Sync `Daytona` mirrors it. | S2 `__init__.py`, `_async/daytona.py` |
| `DaytonaConfig` | `api_key`, `api_url` (default `https://app.daytona.io/api`), `target`, `jwt_token` + `organization_id`, `connection_pool_maxsize=250` (set `None` for many concurrent long `exec`s), `otel_enabled`, `use_deprecated_polling` (sandbox state now arrives by WebSocket events, with a polling fallback) | S2 `common/daytona.py` |
| Environment variables | `DAYTONA_API_KEY`, `DAYTONA_API_URL` (older name `DAYTONA_SERVER_URL`, deprecated), `DAYTONA_TARGET`, `DAYTONA_JWT_TOKEN`, `DAYTONA_ORGANIZATION_ID`, `DAYTONA_OTEL_ENABLED`, `DAYTONA_USE_DEPRECATED_POLLING`, `DAYTONA_HAPPY_EYEBALLS_DELAY` | S2 `_async/daytona.py` L169-272 |
| **dotenv auto-load** | `DaytonaEnvReader` parses `.env.local` and `.env` **from the current working directory** at construction. The precedence is process env → `.env.local` → `.env`. **`DAYTONA_API_URL` is never read from dotenv files** (process env only). So a `Daytona()` built with cwd=`platform/mission-control` silently picks up `DAYTONA_API_KEY` from `.env`. The adapter must pass `DaytonaConfig(api_key=…, api_url=…, target=…)` explicitly from the Secret Broker. | S2 `_utils/env.py`; changelog 0.211.2 "stops resolving the API URL from .env" [C] |
| Regions (targets) | Shared regions `us` and `eu`. The GPU "Earth" region is shared. Custom regions are BYOC (enterprise) [D-regions, D-byoc]. The per-call `target` overrides the client target, which overrides the org default. | S2, D-regions |
| Errors | `DaytonaError`, `DaytonaNotFoundError`, `DaytonaRateLimitError` (with `.headers`), `DaytonaTimeoutError`, `DaytonaConnectionError`, and process errors `PROCESS_EXECUTION_TIMEOUT`, `SESSION_ENDED` (410), `COMMAND_ALREADY_COMPLETED` (410) | S2 `common/errors.py`, D-troubleshooting |

### 1.1 Sandbox create parameters (SDK 0.224.0 `CreateSandboxBaseParams`) [S2 `common/daytona.py`]

**Source and identity**

- `name`
- `language` (python, typescript or javascript; this only selects the code-run toolbox)
- `os_user`
- `env_vars: dict`
- `labels: dict`
- `public`

**Lifecycle**

- `auto_stop_interval`: minutes. The default is 15; `0` disables it. Pause-capable VM classes default to auto-pause 60 instead.
- `auto_pause_interval`: VM only, and mutually exclusive with auto-stop.
- `auto_archive_interval`: the default is 7 days; `0` means the maximum.
- `auto_delete_interval`: disabled by default; a negative value disables it and `0` deletes immediately on stop.
- `ttl_minutes`: a **wall-clock hard deadline** that destroys the sandbox in any state; `set_ttl` resets it.
- `ephemeral`: forces `auto_delete_interval=0`.
- `queue_timeout`: minutes to wait for a runner.
- `timeout` (on `create()`): seconds to wait for started. The default is 60; `0` waits forever.

**Storage and secrets**

- `volumes: list[VolumeMount]`
- `secrets: dict[env_var → org Secret name]`: the environment variable holds the placeholder `dtn_secret_…`, which a proxy substitutes in **HTTPS request headers only**, toward the secret's `hosts` [D-secrets].

**Network**

- `network_block_all`
- `network_allow_list`: up to 10 IPv4 CIDRs.
- `domain_allow_list`: up to 100 domains, `*.` wildcards.
- The three are **mutually exclusive**; sending a conflicting combination returns 400.
- `outbound_proxy_url`: sets `HTTP(S)_PROXY` only. It is "not a security boundary on its own" and can only be set at create time.

**Other**

- `otel_endpoint_override`
- `kvm`: Linux VM only.
- `spot`: GPU only.
- `linked_sandbox`: the child joins the parent's runner and a private link network; children must be ephemeral.
- `target`

**Image vs snapshot**

- `CreateSandboxFromImageParams(image: str | Image, resources: Resources)`.
  - `Resources(cpu, memory GiB, disk GiB, gpu, gpu_type)`.
  - An `Image` object is the **declarative builder**: `Image.debian_slim("3.12")`, `Image.base(...)`, `Image.from_dockerfile(...)`, then `.pip_install`, `.run_commands`, `.add_local_dir/file`, `.env`, `.workdir`, `.entrypoint`, `.dockerfile_commands`.
  - Built images are cached for 24 h per runner [D-builder].
  - The image must be public, or in a registered private registry, and must carry a tag or digest. `latest`, `lts` and `stable` are rejected [D-sandboxes].
- `CreateSandboxFromSnapshotParams(snapshot: str)`.
  - This has **no `resources` field in the SDK**, so resources come from the snapshot (`CreateSnapshotParams(name, image, resources, entrypoint, region_id, sandbox_class)`).
  - The REST `CreateSandbox` schema does accept `cpu`, `memory` and `disk` next to `snapshot` [S4]. Whether they are honoured is **UNVERIFIED**.
  - `sandbox.resize(Resources)`: CPU and memory can be increased while started; disk can only be increased while stopped [D-sandboxes].

**Defaults and limits**

- The default is 1 vCPU / 1 GiB / 3 GiB. The per-sandbox organisation maximum is **4 vCPU / 8 GiB / 10 GiB** [D-sandboxes §Resources].
- Default snapshots `daytona-small/medium/large` are 1/1/3, 2/4/8 and 4/8/10. They pre-install `@anthropic-ai/claude-code` 2.1.220, `@openai/codex` 0.146.0, `claude-agent-sdk` 0.2.130, `anthropic`, `openai-agents` and others [D-snapshots].

**Sandbox classes**

- Container (the default; namespaces, runs as root inside).
- Linux VM and Windows: own kernel; fork, pause and hot snapshots.
- macOS.
- GPU: ephemeral, deleted on stop.
- Sources: [D-sandboxes, D-isolation].

## 2. Process execution

| API | Behaviour | Port relevance | Source |
| --- | --- | --- | --- |
| `process.exec(command: str, cwd, env, timeout)` | Runs through zsh/bash/sh. **Blocks until exit** and returns `ExecuteResponse(exit_code, result)`. The output is not split into stdout and stderr, and it is **not streaming**. The default server timeout is **10 s** when unset ("Timeout in seconds, defaults to 10 seconds"). A background `cmd &` without redirect can block. `nproc` shows host CPUs, so read the cgroup instead. | Use only for short setup steps | S2 `_async/process.py`, S3 `execute_request.py`, D-process |
| `create_session(id)` + `execute_session_command(id, SessionExecuteRequest(command, run_async=True, suppress_input_echo=True))` → `cmd_id` | A persistent shell (`Setpgid`); state such as cwd and env carries across commands. The async command gets stdin from a FIFO kept open (`while :; do sleep 3600; done > "$ip" &`). Output goes to a log file with 3-byte stdout/stderr prefixes plus an exit-code file. **There is no server-side timeout for session commands.** | **Primary `exec` mapping** | S2, S5 `session/execute.go`, `create.go` |
| `get_session_command_logs_async(session, cmd, on_stdout, on_stderr)` | A WebSocket `…/logs?follow=true`. The SDK demuxes stdout and stderr. The daemon opens the log **from byte 0**, so a reconnect replays everything (dedupe by byte offset). The stream ends when the exit-code file appears. | Streaming stdout/stderr, and reattach | S2, S5 `session/log.go` |
| `send_session_command_input(session, cmd, data: str)` | Writes to the FIFO and appends `\n` if it is missing. **Text only.** Returns 410 if the command has already exited. With the echo default (`suppress_input_echo=False`), the input is copied into **stdout**, which would corrupt a stream-json parser. | **stdin** for Claude Code `--input-format stream-json` | S2, S3, S5 `session/input.go` |
| `get_session_command(session, cmd)` → `Command(id, command, exit_code)` | The exit code arrives once it is done. | Exit code | S3 `command.py` |
| `delete_session(id)` | Cancels the session context, which kills the shell. Whether child process groups die is **UNVERIFIED**. There is **no per-command kill endpoint**. | Cancel and timeout | S3 process_api op list, S5 |
| PTY: `create_pty_session(id, on_data, cwd, envs, pty_size)` → `AsyncPtyHandle.send_input(str\|bytes)`, `.wait()`, `.exit_code`, `.kill()`, `.resize()` | A WebSocket with bytes in both directions, exit code delivered over the control channel. Version 0.222.0 added WebSocket keepalive pings. **Caveats:** tty line discipline (echo, CRLF, canonical line limit) needs `stty raw -echo`. Daytona's own "Claude Code stream logs" guide uses a PTY with `-p … --output-format stream-json`. | Fallback for byte-exact stdin. Interactive. | S2, D-pty, C (0.222.0), G-cc-stream |
| SSH: `create_ssh_access(expires_in_minutes)` → `ssh <token>@ssh.app.daytona.io` | True SSH. The default token lifetime is 60 min (configurable), revocable. Active SSH connections reset the auto-stop timer. Non-interactive `ssh host cmd` exec through the gateway is **UNVERIFIED**. | Candidate stdio transport: worker-side `cli_path` wrapper running `ssh -T … claude …` | D-ssh, D-sandboxes |
| `code_run` / interpreter contexts | Python/TS REPL (default timeout 600 s) | Not used | D-process |

**Can stdin be streamed to a long-running process?** Yes, with sessions: the command uses `run_async=True` and `suppress_input_echo=True`, and each NDJSON line is one `send_session_command_input` call. Calls must be serialised to keep their order.

- Every message is an HTTPS round-trip to the toolbox proxy.
- There is no stdin close, so the CLI must be stopped by a control message or a kill.
- **Q-S1 on Daytona:** the Claude Agent SDK's subprocess transport wants a local process. Bridge it through a custom `Transport` or a local relay executable whose stdin and stdout are piped to these calls, or through SSH (UNVERIFIED).

**Timeouts.** Our adapter enforces `timeout_s` itself. When it expires, it kills the process group with `exec("kill -TERM -<pgid>")`, using a PID file written by a wrapper, or it deletes the session.

**Exit codes.** `ExecuteResponse.exit_code` (sync), `Command.exit_code` (async) and `PtyResult.exit_code` (PTY).

## 3. Files and git

- **Files** [S2 `_async/filesystem.py`, D-fs]:
  - Upload: `upload_file(bytes|local_path, remote, timeout=1800)`, `upload_files(list[FileUpload(source, destination)])` (multipart batch), `upload_file_stream(source, remote, on_progress, cancel_event)`.
  - Download: `download_file(remote)` → bytes, `download_files(list[FileDownloadRequest])` → per-file result or error, `download_file_stream(...)` → `AsyncIterator[bytes]`.
  - Other operations: `list_files`, `get_file_info`, `find_files` (grep), `search_files` (glob), `replace_in_files`, `move_files`, `delete_file(recursive)`, `create_folder`, `set_file_permissions`.
  - Pre-signed `sandbox.upload_url` and `download_url(path, ttl_seconds=3600)` need no headers. They work while the sandbox runs and are invalidated by `rotate_signing_key()`.
  - Relative paths resolve against the sandbox user's home or working directory: `get_work_dir`, `get_user_home_dir`.
- **Git** [S2 `_async/git.py`, S3 git models, D-git]:
  - `clone(url, path, branch, commit_id, username, password, depth, insecure_skip_tls)`.
  - `create_branch`, `checkout_branch`, `delete_branch`, `branches`.
  - `add`, `commit(path, message, author, email, allow_empty)`, `status`, `reset`, `restore`.
  - `push(path, username, password, branch, remote, set_upstream)`, `pull(...)`.
  - `remote_add`, `remotes`, `set_config`, `get_config`, `configure_user`.
  - `dangerously_authenticate(username, password, host)` stores credentials in the sandbox.
  - Credentials travel per call in the request body to the in-sandbox daemon. **The sandbox can see them**, so this conflicts with our credential-free rule.
  - There is no `worktree` helper; use `exec("git worktree add …")`.
  - Under a secret, git Basic auth works only by storing `base64(user:token)` as the secret and sending `Authorization: Basic $VAR` (`-c http.extraHeader`). Helpers that base64-encode the placeholder break substitution [D-secrets §HTTP Basic Auth].

## 4. Networking

- **Egress granularity** [D-network, D-isolation, D-limits]:
  - Tier 1 and Tier 2 (the latter needs a card and a $25 top-up): **organisation policy only**. Per-sandbox allow lists are ignored, and `update_network_settings` returns an error. Reachable hosts are the "essential services" list: package registries, GitHub, GitLab, Bitbucket, Azure DevOps, `*.anthropic.com`, `claude.ai`, `*.openai.com`, `*.chatgpt.com`, `*.workers.dev`, `*.vercel.app`, `*.supabase.co`, `*.amazonaws.com` in listed regions, `*.googleapis.com`, Docker registries and others.
  - Tier 3 and Tier 4: full internet by default. A per-sandbox `domain_allow_list`, `network_allow_list` or `network_block_all` is **strictly** enforced; essential services are not auto-added. These settings are mutable at runtime through `update_network_settings` with no restart.
- **Outbound WebSockets: yes.**
  - The OpenAI executor connects "HTTPS to `api.openai.com` to register, and a WebSocket to `codex-cloud-environments.chatgpt.com`", with "no inbound ports" [G-oai, OAI-daytona].
  - The Anthropic worker needs outbound HTTPS only [ANT-shs; G-cma polling orchestrator].
  - Both hosts are in the essential-services list (Tier 1/2), or must be allowlisted on Tier 3+.
  - Daytona's inactivity tracker **does not see** outbound sockets, so set `auto_stop_interval=0` and use `ttl_minutes` as the backstop [G-oai, OAI-daytona, D-sandboxes "What resets the timer"].
- **Inbound** [D-preview, D-proxy]. Any port from 1 to 65535 is reachable.
  - **Standard URL**: `https://{port}-{sandboxId}.{proxyDomain}`, authenticated by `x-daytona-preview-token`, or by `Authorization: Bearer <Daytona API key>` [S2 docstring]. The standard token is **sandbox-wide**: it also unlocks toolbox port 2280 and terminal port 22222, so it amounts to full control. It cannot be revoked and changes on stop and start.
  - **Signed URL**: `https://{port}-{token}.{proxyDomain}` from `create_signed_preview_url(port, expires_in_seconds)`. The expiry defaults to 60 s with a **maximum of 86,400 s**; the URL is bound to one port and revocable.
  - The proxy "fully supports WebSocket connections".
- **Could the worker reach an exec-server inside the sandbox over wss? Yes, in principle.**
  1. Run `codex exec-server --listen ws://0.0.0.0:<P>`.
  2. Mint a signed preview URL for `<P>`.
  3. Pass `execServerUrl=wss://<P>-<token>.<proxyDomain>` to app-server `environment/add`.
  - **UNVERIFIED**:
    - (a) whether Daytona's proxy forwards or interferes with `Authorization: Bearer <authBearerToken>` on the upgrade;
    - (b) the proxy's idle-timeout on long WebSockets;
    - (c) the need to rotate URLs before 24 h.
  - Preview traffic resets the auto-stop timer; the header `X-Daytona-Skip-Last-Activity-Update` opts out.
- **Secrets and WebSockets.** Placeholder substitution is not supported on upgraded WebSocket connections [G-oai §6]. The executor key must therefore be a plain environment variable `CODEX_API_KEY`, scoped to `api.agents.environments.connect` only.

## 5. Snapshots, archive, volumes

| Feature | Container | Linux VM / Windows | Source |
| --- | --- | --- | --- |
| Snapshot from sandbox | Filesystem only ("cold"). The docs table says the sandbox must be **Stopped**. The SDK docstring and API description imply a running sandbox may work: `snapshotting` then returns to its prior state (conflicting; **stop first**). | Cold (stopped), or hot with `includeMemory` (started). The SDK `create_snapshot(name)` does not expose `include_memory`; the raw API `CreateSandboxSnapshot.include_memory` does. | D-snapshots, S2, S3 |
| Restore | `create(CreateSandboxFromSnapshotParams(snapshot=name))` gives a **new sandbox**. There is no in-place rollback. | Same, or `fork()` (copy-on-write filesystem plus memory). | D-sandboxes |
| Pause | ✗ | ✓ (disk billed only) | D-sandboxes |
| Archive | ✓: the filesystem moves to object storage; not billed; restored on `start`. Auto-archive defaults to 7 days. | ✗ (stop already offloads) | D-sandboxes, D-billing |
| Snapshot retention | Snapshots stay billed for storage after the sandbox is deleted [D-billing]. They **go inactive after 2 weeks unused** (re-`activate`). | | D-snapshots |
| Image vs snapshot | A snapshot is Daytona's pre-pulled or pre-built, registered base image with resources. An image is a raw OCI reference or declarative build, turned into a snapshot on the fly (cached 24 h). Warm pools hold N running sandboxes per (snapshot, region). | | D-snapshots, D-builder, D-warm |
| Volumes | FUSE mounts backed by S3. Shared across sandboxes, with per-tenant `subpath`. Up to 100 per organisation, free, and they do not count toward storage quota. They outlive sandboxes, but FUSE semantics are a poor fit for git worktrees (UNVERIFIED performance). | | D-volumes |

## 6. Lifecycle, limits, quotas, pricing, compliance

- **States** [D-sandboxes]: creating, started, stopping, stopped, archiving, archived, restoring, snapshotting, resizing, forking, pausing, paused (VM), deleting, deleted, error (`recover()`), build_failed. `delete(wait=True)` blocks until destroyed.
- **The auto-stop timer resets only on** lifecycle changes, preview requests, active SSH and toolbox API calls. Background processes do not reset it. `refresh_activity()` resets it manually.
- **Tiers** [D-limits], per region:
  - Tier 1: 10 vCPU / 10 GiB in the prose table but 20 GiB in the summary table (inconsistent) / 30 GiB. Email verification.
  - Tier 2: 100 / 200 / 300. Card plus $25.
  - Tier 3: 250 / 500 / 2000. $500.
  - Tier 4: 500 / 1000 / 5000. $2000 every 30 days.
  - Stopped containers keep their disk quota until archived.
- **Rate limits (per minute)** [D-limits]: general requests 10k/20k/40k/50k; sandbox creates 300/400/500/600; lifecycle operations 10k to 50k. Exceeding them returns 429 with `Retry-After-{throttler}`.
- **Concurrency** is bounded only by the tier pool. For example, Tier 2 at 2 vCPU per sandbox allows about 50 concurrent sandboxes.
- **Pricing** [P-pricing]:
  - Rates: vCPU $0.0504/h; RAM $0.0162/GiB-h; disk $0.000108/GiB-h after 5 GiB free; Windows $0.0858/vCPU-h.
  - Per-second billing; $200 of free compute; a startup programme of up to $50k.
  - Started states bill CPU, RAM and disk. Stopped and paused states bill disk only. Archived and deleted states are free, apart from snapshots [D-billing].
  - Worked example: a 2 vCPU, 4 GiB, 10 GiB sandbox costs about $0.166/h running and about $0.0005/h stopped.
- **Compliance** [T-trust]: the Trust Center lists SOC 2 Type 1 and Type 2, ISO/IEC 27001, GDPR and HIPAA. Whether a BAA is available, and on which plan, is **UNVERIFIED**. Subprocessors are Latitude.sh, OVHcloud, AWS, Stripe and Lago.
- **Retention.** Stopped, paused and archived sandboxes are retained until deleted [D-persistence]. No ZDR statement was found (UNVERIFIED). Audit logs and SSO are Enterprise features.
- **Webhooks** [D-webhooks]: `sandbox.created`, `sandbox.state.updated`, `snapshot.created`, `snapshot.state.updated`, `snapshot.removed`, `volume.created`, `volume.state.updated`.

## 7. Official integration guides: recommended patterns

- **Claude Managed Agents self-hosted** [G-cma, ANT-shs lists Daytona as a platform guide; reference code at `github.com/daytona/guides/python/claude/claude-managed-agents`]:
  - A host **orchestrator** long-polls the environment work queue (environment key only, NAT-safe) or receives `session.status_run_started` webhooks.
  - For each work item it gets or creates a sandbox named `byoc-<session_id>` from a hashed-Dockerfile snapshot, with labels.
  - It uploads `sandbox_runner.py` and launches it with `nohup`. The runner uses `client.beta.environments.work.worker(environment_key, workdir="/mnt/session").handle_item()` **inside the sandbox**, with **the environment key in the sandbox environment**.
  - Idle sandboxes are stopped and later restarted. They are archived on session end; deletion follows after 30 days stopped.
  - Two session metadata keys are supported: `daytona.snapshot_name` and `daytona.sandbox_id` (a prepared sandbox, for example one with a cloned repo).
  - Memory stores are not yet supported on this path.
  - **Contrast with SPEC-06 §4.3.** Our design runs the `EnvironmentWorker` in a **Mission Control worker** with our tool wrappers. On Daytona, that means remote tool implementations over `SandboxHost.exec` and `put_files`: the Stop Fence and Operation Intent stay worker-side, and the environment key never enters the sandbox. The Daytona pattern is simpler, but it puts the environment key where agent `bash` can read it.
- **OpenAI Agents API self-hosted** [G-oai, OAI-daytona; cookbook `openai-cookbook/examples/agents_api/sandboxes/daytona/{application_managed,webhook_managed}`]:
  1. Create a session with `environment={"type":"self_hosted","workspace_directory":…}`.
  2. Create a sandbox with `env_vars={"CODEX_API_KEY": executor_key}`, the label `agents-api-environment-id`, `auto_stop_interval=0` and `ttl_minutes`.
  3. Run `codex exec-server --remote <remote_url> --environment-id <id>` as a `run_async` session command.
  4. Wait for `agent.session.environment.connected`.
  - Webhook-managed variant: stop on `agent.session.idle`, and restart plus relaunch on the `agent.session.action_required` (`environment_connection`) webhook.
  - Bake Codex and ripgrep into a snapshot.
- **Claude Agent SDK and Claude Code** [G-claude-*, G-cc-stream]. Every guide runs the SDK or CLI **inside** the sandbox: a PTY running `claude -p … --output-format stream-json`, or a Python or TypeScript agent in the sandbox. The key is passed as a plain environment variable, or (recommended) as a Daytona **Secret** with `hosts: ["api.anthropic.com"]` (SDK ≥0.192). **No guide bridges a worker-side SDK to an in-sandbox CLI over stdio**, so our §6 design is novel on Daytona. Q-S1 remains open.
- **OpenAI Agents SDK**: `pip install openai-agents[daytona]` provides `agents.extensions.sandbox.DaytonaSandboxClient` (openai-agents 0.23.1). This is not Codex [G-oai-sdk].
- **Codex SDK**: a Node agent inside the sandbox [G-codex-sdk].
- **LangChain Deep Agents**: `langchain-daytona` 0.0.8, `DaytonaSandbox(sandbox=Daytona().create())` as the `backend` [LC]. This is the reference for "sandbox as backend protocol".

## 8. Docker-on-WSL2 parity: what our Docker adapter must emulate

| Daytona feature we rely on | Docker adapter emulation |
| --- | --- |
| Labels plus list-by-label (orphan sweep) | Container labels `mc.run`, `mc.unit`, `mc.lease`, `mc.deadline`; `docker ps --filter label=` |
| `ttl_minutes` hard deadline, `auto_stop_interval=0` | A reaper loop on the `mc.deadline` label (Docker has neither) |
| Retain after failure, then delete | Stop (not `--rm`) and remove after the retention interval; no archive tier |
| `domain_allow_list` / `network_block_all` | `--network none` for block-all. For an allowlist: an internal bridge with no default route plus an egress proxy sidecar enforcing domains (CONNECT/SNI), plus `HTTP(S)_PROXY`; CIDR rules via `DOCKER-USER` iptables. Declare `egress_control: proxy_enforced` |
| Model Gateway reachability | `--add-host=host.docker.internal:host-gateway` on native WSL2 dockerd; the gateway host on the allowlist |
| Session exec with streaming stdin | Docker exec API with attach (hijacked stream; `stdcopy` demux; **binary-safe and supports close-stdin**). Parity means the port contract must be the **weaker** Daytona one: text lines, no EOF |
| Preview URL plus token for inbound wss | Publish to `127.0.0.1:<port>`; the worker dials `ws://localhost:<port>` directly (exec-server `--listen`) |
| `put_files` / `get_files` | `put_archive` / `get_archive` (tar) |
| Cold snapshot (filesystem) / restore = new sandbox | `docker commit` → local image tag `mc-snap/<lease>:<digest>` (excludes volumes, captures container filesystem); restore = run from it. No memory snapshot |
| Resources cpu/mem/disk | `--cpus`, `--memory`. **Disk quota is not enforceable** on WSL2 ext4/overlay2 (needs xfs pquota), so declare it `unsupported` |
| Snapshot-as-kit image (per kit digest × size) | Build or tag the image `mc-kit/<digest>`; resources are passed at run time |
| Default user and paths | Mirror Daytona's `daytona` user, `/home/daytona` and workdir, so kits and mission layers are portable |
| Rate limits and quotas | A local concurrency semaphore; describe `max_concurrent` |
| Secrets placeholder proxy | Not emulated; both adapters use Model Gateway per-run tokens instead |
| Isolation | Optionally `--runtime=runsc` (gVisor) for closer parity; containers run as root on both |

## 9. SandboxHost adapter design (`adapters/sandboxes/daytona/`)

**Client.** Use one `AsyncDaytona(DaytonaConfig(api_key=<Secret Broker>, api_url="https://app.daytona.io/api", target=<spec.region or "us">, connection_pool_maxsize=None))` per worker process.

- Never rely on cwd `.env` auto-load.
- Pin `daytona==0.224.0`, since the API moves daily.

### 9.1 Method mapping

| Port method | Daytona implementation | Notes and gaps |
| --- | --- | --- |
| `create(spec)` | `create(CreateSandboxFromSnapshotParams(...), timeout=create_timeout)`. Parameters are below this table. | Native. Resources come from the snapshot; a size override needs one snapshot per size or `resize()` after create. Kit image build: `daytona.snapshot.create(CreateSnapshotParams(name=f"mc-kit-{digest8}-{size}", image=Image.from_dockerfile(...) or an OCI ref with a digest, resources=..., region_id=...))`, idempotent by name |
| `exec(h, argv, cwd, env, stdin, timeout_s)` → `ExecStream` | One session per exec (`mc-<uuid>`). Command: `cd <cwd> && exec env K=V … <shlex.join(argv)>`, behind a tiny wrapper that writes its PGID. Request: `run_async=True, suppress_input_echo=True`. Stdout and stderr come from `get_session_command_logs_async`; stdin is a pump task calling `send_session_command_input` line by line, serially. The exit code comes from `get_session_command` after log EOF. Timeout: our own timer kills the PGID through a short `process.exec`, then `delete_session`. | **Gaps:** text and line-framed stdin only (no bytes, no EOF); input `\n` auto-append; each line is an HTTPS call (latency). Advertise `describe().exec_stdin = "text_lines"`. Reattach after a worker crash replays the log from byte 0 (dedupe by offset). Short non-stdin commands may use `process.exec(timeout=...)`, but **always pass `timeout`**: the default is 10 s |
| `put_files(h, files)` | `fs.upload_files([FileUpload(source=bytes, destination=path)])`; large files use `upload_file_stream` | Native |
| `get_files(h, paths)` | `fs.download_files([FileDownloadRequest(source=p)])`; per-file `error` maps to missing | Native |
| `snapshot(h)` | `sandbox.stop()` → `sandbox.create_snapshot(f"mc-snap-{lease}-{n}", timeout=…)` → optionally `start()`. Returns `SandboxSnapshotRef(provider="daytona", name, region, created_at)` | Containers capture the filesystem only and need **stopping**, so processes die. The capability flag is `snapshot: "fs_cold"`. Snapshots bill for storage and go inactive after 14 days unused, so delete them per the retention policy |
| `restore(ref, spec)` | `create(CreateSandboxFromSnapshotParams(snapshot=ref.name, ...spec))`, after `snapshot.activate(name)` if the snapshot is inactive | A new sandbox ID; the lease rebinds |
| `terminate(h)` | `sandbox.delete(wait=True)`. For failure retention: `stop()` plus `set_auto_delete_interval(retention_minutes)` (or `archive()` for long retention) | Delete is fire-and-forget unless `wait=True` |
| `describe()` | `{provider: "daytona", regions: ["us", "eu"], egress_control: "domain_allowlist" if tier ≥ 3 else "org_essential_services_only", snapshot: "fs_cold", fork: False (container), pause: False, max_ttl: None (ttl_minutes arbitrary), exec_stdin: "text_lines", inbound: "preview_wss_signed_24h", max_resources: {cpu: 4, mem_gib: 8, disk_gib: 10} (org per-sandbox maximum), data_class_max: "internal"}` | The tier must be configured or probed (§10) |

`create(spec)` passes these parameters:

- `snapshot=f"mc-kit-{kit_digest8}-{size}"`
- `name=f"mc-{run}-{unit}-{gen}"` (idempotent: on 409, `get(name)`)
- `labels={"mc.run", "mc.unit", "mc.lease", "mc.kit", "mc.owner": "mission-control"}`
- `env_vars=` non-secret variables plus `ANTHROPIC_BASE_URL` / `MC_RUN_TOKEN`
- `auto_stop_interval=0`, `ttl_minutes=spec.ttl`, `auto_archive_interval=60`, `auto_delete_interval=spec.retention`
- `domain_allow_list=",".join(kit_hosts + [gateway, ingress])`, or `network_block_all=True`
- `target=spec.region`

**Lane helpers built on the port (not port methods):**

- `expose_ws(h, port, ttl ≤ 86400)` → `create_signed_preview_url` (§7 app-server remote executor). Revoke with `expire_signed_preview_url`.
- `refresh_activity` heartbeat is not needed when `auto_stop_interval=0`.
- `orphan_sweep()` → `list(ListSandboxesQuery(labels={"mc.owner": "mission-control"}))` and compare against active leases.
- Webhook `sandbox.state.updated` → Signal Ingress as a wake-up only.

### 9.2 Per-lane recipe

1. **`codex_agents` self_hosted**: follow the Daytona and OpenAI guide exactly.
   - `CODEX_API_KEY` is the environment key, as a plain environment variable; secrets do not work over WebSocket.
   - Egress: `api.openai.com` plus `codex-cloud-environments.chatgpt.com` (or `*.chatgpt.com`).
   - Set `auto_stop_interval=0` and a TTL.
   - The 5-minute connect deadline is easily met when Codex is baked into the kit snapshot. The default Daytona snapshots ship `@openai/codex` 0.146.0, but we pin our own.
2. **`claude_managed` self_hosted**: keep the SPEC-06 design (worker-side `EnvironmentWorker` and our tool implementations over the port). The environment key stays out of the sandbox.
   - `bash` → `exec`.
   - `read`/`write`/`edit` → `get_files`/`put_files`.
   - `glob`/`grep` → `fs.search_files`/`fs.find_files`, or `exec rg`.
   - The Daytona in-sandbox runner is the fallback when latency hurts, with one environment per mission.
3. **`claude_agent_sdk` @sandbox**: run the CLI as a session command, `claude --input-format stream-json --output-format stream-json --verbose …`, with `suppress_input_echo=True`. Bridge the SDK through a custom transport (Q-S1) or a local relay.
   - Model access: `ANTHROPIC_BASE_URL` points at the Model Gateway with a per-run token. This needs a Tier 3+ allowlist, or a gateway hosted on an essential-services domain such as `*.workers.dev` for Tier 1/2.
   - Fallback: a Daytona Secret holding the Anthropic key with `hosts=["api.anthropic.com"]`. The raw key is never in the sandbox, but this moves away from per-run tokens.
4. **`codex` app-server with a remote executor**: `codex exec-server --listen ws://0.0.0.0:P` → signed preview `wss://P-<token>.proxy…` → `environment/add`. Drill for Authorization-header passthrough and idle timeouts.

### 9.3 Recommended defaults

- Container class; `us` region; kit snapshots at 2 vCPU / 4 GiB / 10 GiB.
- `auto_stop_interval=0`; `ttl_minutes = attempt budget + 30`.
- On failure: `stop` + `auto_delete_interval = retention` (default 1440); `auto_archive_interval=60`.
- On success: `delete(wait=True)` after custody.
- Egress: `domain_allow_list` (requires Tier 3). Never set `public=True`.
- Use signed preview URLs only; never hand out the standard preview token, which is sandbox-wide.
- No git credentials in the sandbox: Mission Control pulls the bundle through `get_files` and pushes it itself.
- `data_class` maximum `internal` until a BAA is confirmed; PHI is refused.

## 10. Owner credential check and the `.env` question

- **The `.env` file holds one `DAYTONA_API_KEY`, not three.**
  - The current `platform/mission-control/.env` (125 lines, CRLF, no BOM, modified 2026-10-12 16:57 local) has exactly **one** `DAYTONA_API_KEY` assignment, at **line 125**: value length 68, sha256 prefix `63c2aaed02e8`.
  - A loose substring search confirms only one occurrence.
  - Lines 70 and 71 define `DAYTONA_SNAPSHOT` and `DAYTONA_IDLE_TTL_SECONDS`, which are not SDK variables.
  - The triple definition described in the brief is not present now; it was probably already de-duplicated.
- **Duplicate-key semantics, verified on a synthetic file:**
  - python-dotenv **1.2.1** `dotenv_values` returns the **last** occurrence (`first/second/third` → `third`).
  - `load_dotenv(override=False)` also uses the last file value, but never overrides a variable already in the process environment.
  - pydantic-settings (`bootstrap/settings.py` `env_file=PROJECT_ROOT/.env`) and Daytona's `DaytonaEnvReader` both use `dotenv_values`, so last wins there too, and process env beats the file.
- **API probe.**
  - Call: `GET https://app.daytona.io/api/sandbox?limit=20` with that key returned **HTTP 200** and `items: []`, with no `nextCursor`.
  - The key is valid and the organisation has **0 sandboxes**, so there is no running cost.
  - Header: `X-RateLimit-Limit-authenticated: 50000`, which matches the documented Tier 4 general limit. The tier is **UNVERIFIED**; confirm it in the dashboard before relying on per-sandbox egress allowlists.
  - No values were printed and nothing was created.

## 11. Sources

**Packages, code and API**

- **S1**: https://pypi.org/project/daytona/0.224.0/ (2026-10-12), https://pypi.org/project/daytona-sdk/ (0.224.0, deprecated alias), npm `@daytona/sdk` 0.224.0.
- **S2**: wheel `daytona-0.224.0-py3-none-any.whl`: `daytona/common/{daytona,sandbox,process,filesystem,snapshot}.py`, `daytona/_async/{daytona,sandbox,process,filesystem,git,snapshot}.py`, `daytona/handle/async_pty_handle.py`, `daytona/_utils/env.py`.
- **S3**: `daytona-toolbox-api-client` 0.224.0 models (`execute_request`, `session_execute_request`, `session_send_input_request`, `command`, `git_clone_request`, `git_push_request`); `daytona-api-client` 0.224.0 `create_sandbox_snapshot.py`.
- **S4**: https://www.daytona.io/docs/openapi.json (fetched 2026-10-12; `CreateSandbox`, `/sandbox`, `/api-keys/current`).
- **S5**: https://github.com/daytonaio/daytona at tag v0.190.0 (archived; README "no longer maintained … moved to a private codebase"): `apps/daemon/pkg/session/{execute,input,create,log}.go`. This is the last public daemon code; current SaaS behaviour may differ (UNVERIFIED).

**Daytona docs** (all `https://www.daytona.io/docs/en/<page>.md`, fetched 2026-10-12)

- **D-sandboxes**: `sandboxes`
- **D-limits**: `limits`
- **D-billing**: `billing`
- **D-network**: `network-limits`
- **D-preview**: `preview`
- **D-proxy**: `custom-preview-proxy`
- **D-snapshots**: `snapshots`
- **D-volumes**: `volumes`
- **D-persistence**: `persistence`
- **D-regions**: `regions`
- **D-process**: `process-code-execution`
- **D-pty**: `pty`
- **D-fs**: `file-system-operations`
- **D-git**: `git-operations`
- **D-secrets**: `secrets`
- **D-isolation**: `isolation`
- **D-ssh**: `ssh-access`
- **D-webhooks**: `webhooks`
- **D-warm**: `warm-pools`
- **D-builder**: `declarative-builder`
- **D-troubleshooting**: `troubleshooting`
- **D-byoc**: `bring-your-own-compute`

**Daytona guides** (`https://www.daytona.io/docs/en/guides/<path>.md`)

- **G-cma**: `claude/claude-managed-agents`
- **G-oai**: `openai/openai-agents-api-self-hosted-sandbox`
- **G-claude-***: `claude/claude-agent-sdk-{interactive-terminal,connect-service}-sandbox`
- **G-cc-stream**: `claude/claude-code-run-tasks-stream-logs-sandbox`
- **G-oai-sdk**: `openai/openai-agents-sdk-with-sandboxes`
- **G-codex-sdk**: `openai/codex-sdk-interactive-terminal-sandbox`

**Other**

- **P-pricing**: https://www.daytona.io/pricing (2026-10-12).
- **T-trust**: https://trust.daytona.io/ (SafeBase, updated 2026-10-12).
- **C**: https://www.daytona.io/changelog (0.211.2 to 0.223.0).
- **OAI-daytona**: https://developers.openai.com/api/docs/guides/agents-api/environments/providers/daytona.md
- **ANT-shs**: https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes (platform guides list Daytona).
- **LC**: https://docs.langchain.com/oss/python/deepagents/sandboxes and PyPI `langchain-daytona` 0.0.8.
