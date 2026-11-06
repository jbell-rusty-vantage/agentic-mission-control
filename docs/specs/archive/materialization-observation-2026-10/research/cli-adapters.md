---
type: Research Note
title: "Local CLI adapter specifications for Claude Code, Codex and Cursor (2026-10-12)"
description: "Validated argv templates per permission profile and mode, streaming event schemas, exit codes and failure signatures, prompt delivery, session capture, env scrubbing, Windows launch and kill, WSL notes, the adapter contract and synthetic fixtures."
tags: [mission-control, research, materialization-observation]
---

# CLI adapter specifications for `agentjob.py` (SPEC-08)

Research date: **2026-10-12**. Machine: Windows 11 (10.0.26300), Git Bash + PowerShell 5.1, WSL2 Ubuntu.
Companion to [SPEC-08](../SPEC-08-local-cli-skills.md) and [research/local-cli-skills.md](local-cli-skills.md); this note
**supersedes** the argv/permission rows of SPEC-08 §5 where they disagree (see §0.2).

**No model call was made.** Allowed probes only: `--help`/`-h`, `--version`, `claude auth status`, `codex login status`,
`agent status --format json`, `codex features list`, clap parse checks (`codex exec <flags> --help`, which rejects bad
flags before printing help), `claude -p … </dev/null` (fails at the input check before setup or any API request), string
inspection of the installed bundles, and upstream source and docs.

Evidence tags:

| Tag | Meaning |
| --- | --- |
| **[help]** | Captured from the local binary today (`research3/help/*.txt` next to this file) |
| **[probe]** | Local, model-free parse or exit-code probe run today |
| **[bundle]** | String or code read from the installed package (Claude `claude.exe` embedded JS; Cursor `versions/2026.10.01-14929f9/*.js`; Codex `codex.exe` and `bin/codex.js`) |
| **[src]** | Upstream source at a pinned tag: `openai/codex@rust-v0.162.1`, `openai/codex-plugin-cc@main` (pushed 2026-07-08) |
| **[doc]** | Official docs page |
| **[inferred]** | Derived from the above; not observed in a live run. Must be confirmed by the owner-authorized smoke (§9) |

---

## 0. Local facts and SPEC-08 corrections

### 0.1 Installed binaries and auth (method only, no secrets)

| CLI | Launch target on Windows | Version | Auth status today | Action needed |
| --- | --- | --- | --- | --- |
| Claude Code | `C:\Users\Pinda\.local\bin\claude.exe` (native, 260 MB, embedded Bun JS) | `2.1.296 (Claude Code)` [help] | `claude auth status` exit 0: `loggedIn:true`, `authMethod:"claude.ai"`, `apiProvider:"firstParty"`, `subscriptionType:"max"` [probe] | none |
| Codex CLI | `%APPDATA%\npm\codex.cmd` → `node …\@openai\codex\bin\codex.js` → **native** `…\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe` | `codex-cli 0.162.1` [help] | `codex login status` exit 0: **"Logged in using ChatGPT"**; `~/.codex/auth.json` has `auth_mode:"chatgpt"`, and no API key is stored [probe] | **`codex login` is NOT needed on Windows.** WSL has no working Codex (§8). |
| Cursor agent | `%LOCALAPPDATA%\cursor-agent\agent.cmd` → `powershell -File cursor-agent.ps1` → `versions\2026.10.01-14929f9\node.exe …\index.js` (4 version dirs present; the ps1 picks the newest by date) | `2026.10.01-14929f9` [probe] | `agent status --format json` exit 0: `status:"authenticated"`, access and refresh tokens present (browser login). `CURSOR_API_KEY` is **not** set in user or process env [probe] | none (login works); `CURSOR_API_KEY` is optional |

Env presence in the caller (Claude Code session): `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT` are **set**. Every
`ANTHROPIC_*`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `CODEX_HOME`, `CURSOR_API_KEY` and `CURSOR_AUTH_TOKEN` is unset [probe].

Codex user config (`~/.codex/config.toml`, shared with the Codex desktop app; header and key names only): it sets
**`sandbox_mode = "danger-full-access"`**, `approval_policy = "never"`, `model`, `model_reasoning_effort`,
`[windows] sandbox = "elevated"`, eight `[mcp_servers.*]` (e.g. blender, mongo, node_repl), and twelve `[plugins.*]` plus
`[hooks.state]` trust entries for `~/.codex/hooks.json` [probe]. **Consequence: any Codex launch that does not pass `-s`
runs with full access and starts eight MCP servers.**

### 0.2 Corrections to SPEC-08 §4–§5 (validated today)

| # | SPEC-08 says | Reality (evidence) | Fix |
| --- | --- | --- | --- |
| C1 | Codex read-only `-s read-only -a never` | `codex exec -a never …` → **exit 2** `error: unexpected argument '-a' found` [probe]. `-a/--ask-for-approval` exists only on top-level `codex` [help]. `exec` hard-codes `approval_policy: Some(AskForApproval::Never)` [src `exec/src/lib.rs:591`]. | Drop `-a`. To be explicit, use `-c approval_policy="never"`. |
| C2 | (research) `--full-auto` deprecated | `codex exec --full-auto` → **exit 2** in 0.162.1 [probe]. The docs page still calls it a deprecated compat flag [doc non-interactive], so the docs are stale. | Never emit `--full-auto`. |
| C3 | Resume = `codex exec resume <id>` with profile flags | `-s`, `-C`, `--add-dir`, `-p`, `--approve-for-me` and `--oss` are **not accepted after `resume`** (`codex exec resume -s read-only` → exit 2). They **are** accepted **before** the subcommand: `codex exec -s workspace-write -C . --json resume …` parses [probe]. Global args (`--json`, `-o`, `--output-schema`, `-m`, `-c`, `--ephemeral`, `--ignore-user-config`, `--skip-git-repo-check`, `--yolo`) work in either position [src `exec/src/cli.rs` `global = true`]. | Put **all** options before `resume` (§3a). |
| C4 | Codex read-only adds `--ephemeral` | `--ephemeral` writes no rollout, so the session **cannot be resumed** [help][doc] and the goal loop breaks. | Use `--ephemeral` only when `budget.max_iterations == 1`. |
| C5 | `host: auto` → Codex runs in WSL on Windows | WSL `codex` resolves to the **Windows npm shell shim** `/mnt/c/…/npm/codex`, which needs `node`, and WSL has no node. WSL has no `~/.codex` login [probe]. Native Windows Codex is installed, logged in, and has the elevated Windows sandbox configured. | `host: auto` → **native** for all three CLIs on this machine; WSL is opt-in after setup (§8). |
| C6 | Claude read-only `--permission-mode plan` | Works, but in `-p` plan mode the model may call `ExitPlanMode`. That is denied under `--permission-prompts none`, wastes a turn, and logs a denial [doc headless, inferred]. `dontAsk` denies everything that would prompt, yet still allows reads and the read-only command set [doc headless]. | Read-only default: `--permission-mode dontAsk`. `plan` stays allowed as `read-only-plan`. |
| C7 | Claude `--max-turns` | Absent from `--help`, but present as a **hidden** option (`.hideHelp()`, "only works with --print") [bundle]. | Keep it. Pin and re-check on upgrade. |
| C8 | Cursor stdin prompt unknown | `src/commands/build-prompt.ts`: prompt = positionals joined by `" "`. **If that is empty and stdin is not a TTY, it reads stdin to EOF, trims it, and uses it as the prompt** [bundle]. Print mode is also auto-inferred when stdin is piped or stdout is not a TTY [bundle][doc output-format]. | Prompt via stdin; write it and close stdin. Live-confirm in the smoke. |
| C9 | Cursor has no usage telemetry | Build 2026.10.01 adds `usage:{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens}` to `result` when the server reports it (`turnEnded`) [bundle]. It is undocumented [doc]. | Parse it when present. |
| C10 | Cursor final text `.result` | `result` = **concatenation of all assistant text deltas for the whole run** [doc][bundle]. It is not the last message. | Report extraction uses the **last** `assistant` event, or the last JSON object in `result` (§4b). |
| C11 | Codex subscription guard `-c forced_login_method="chatgpt"` | Enforcement message: *"ChatGPT login is required, but an API key is currently being used. **Logging out.**"* [bundle]. With an API key in env, the guard can **clear the stored ChatGPT login**. | **Scrub env first** (allowlist), then pass the guard. Never pass it while any `*_API_KEY` could reach the child. |

---

## 1. Shared runner model (all adapters)

**Prompt delivery.** All three CLIs read the prompt from stdin. The runner renders `prompt-<n>.md` and passes its UTF-8 bytes as
`stdin_bytes`, writes them, and **closes stdin**. Positional prompts are never used, which avoids:

- Windows quoting;
- the 32,767-char CreateProcess cap (and the 8,191-char cmd.exe cap if a `.cmd` shim were used);
- commander variadic options (`--allowedTools <tools...>`, `--add-dir <dirs...>`) swallowing a trailing positional.

**Output.** Each adapter selects its line-delimited JSON mode:

| CLI | Flags |
| --- | --- |
| Claude | `--output-format stream-json --verbose` |
| Codex | `--json` |
| Cursor | `--output-format stream-json` |

**Read rules.**

- Read stdout as **bytes** and split on `\n`. Decode each line as UTF-8 (never use the locale codec; cp1252 breaks on `→`
  and similar characters).
- Tee the raw line to `run.jsonl` (redacted).
- Keep the stderr tail (last 64 KiB) for classification.

**Process.** One process per iteration. The runner owns the wall clock, kills the process tree, and runs `verify` itself.
The adapter is pure: it builds argv, stdin and env, parses lines, and folds them into a `FinalReport`.

---

## 2. Claude Code adapter (`claude -p`, 2.1.296)

### 2a. Argv templates (validated against `--help` [help]; hidden flags against the bundle)

The binary is `claude.exe`, launched directly with no shell. Order is free (commander), but **every variadic flag must be
followed by another `--flag`**. The template keeps `--output-format …` last for that reason.

**Common prefix:**

```text
claude.exe -p
  --permission-prompts none                 # v2.1.259+: auto-deny anything that would prompt; removes AskUserQuestion [doc headless]
  --max-turns {budget.max_turns_per_iteration}        # hidden option [bundle]
  [--model {model.name}] [--effort {low|medium|high|xhigh|max}]
  [--max-budget-usd {budget.max_usd_remaining}]       # client-side estimate, cumulative per conversation [doc headless]
  [--setting-sources project,local --strict-mcp-config]   # isolation=project-only (skips ~/.claude hooks/plugins/MCP)
  {PROFILE FLAGS}
  {MODE FLAGS}
  [--json-schema '{inline JSON}']           # structured mode; INLINE JSON ONLY (JSON.parse of argv; not a path) [bundle]
  --output-format stream-json --verbose     # stream-json requires --verbose under -p [bundle error string]
```

**Profile flags:**

| Profile | Flags |
| --- | --- |
| `read-only` | `--permission-mode dontAsk` (alternative `read-only-plan`: `--permission-mode plan`) |
| `edit` | `--permission-mode acceptEdits --allowedTools Read Edit Write "Bash({cmd})" "PowerShell({cmd})" …` (one `Bash(…)` and, on Windows, one `PowerShell(…)` per `allow_commands` glob; the rule syntax uses a space before `*` [doc headless]) |
| `full` | `--permission-mode bypassPermissions` (equivalent to `--dangerously-skip-permissions`) |

`--permission-mode` choices are `acceptEdits|auto|bypassPermissions|manual|dontAsk|plan` [help]. **Always pass one**: with
none, `-p` takes the built-in starting mode, "which can be `auto`" [doc headless].

**Mode flags:**

| Mode | Flags |
| --- | --- |
| new | `--session-id {uuid4 generated by runner}` (must be a valid UUID; "already in use" fails with exit 1 [bundle]) |
| resume | `--resume {session_id}` (same id continues; the transcript is found in any project [doc headless]) |
| resume-fork (sealed restart variant) | `--resume {id} --fork-session --session-id {new uuid4}` (allowed combination [bundle]) |
| structured | add `--json-schema '<schema>'` and read `result.structured_output` [doc headless] |

Do **not** use:

- `--bare` (it never reads OAuth, so it cannot use the subscription [help][doc]);
- `--bg` (rejected with `-p`);
- `--no-session-persistence` (it breaks resume);
- `--include-partial-messages` (noise).

Probes [probe], with `stdin=/dev/null`:

- every flag combination above is accepted, and the run fails only at the input check with exit 1;
- `--bogus-flag` gives exit 1 and `error: unknown option '--bogus-flag'` on stderr;
- an invalid `--json-schema` gives exit 1 and `Error: --json-schema is not valid JSON: …` on stderr.

### 2b. Event schema (stream-json) and mapping

Schemas are read from the zod definitions in the bundle [bundle] and the headless doc [doc headless]. Every line carries
`session_id` and `uuid`.

| Event | Key fields | Runner mapping |
| --- | --- | --- |
| `system/hook_started`, `system/hook_response` | `hook_name`, `hook_event`, `exit_code`, `outcome` | These **can precede `init`** (SessionStart hooks; seen in the probe). `session_id` is already present. Log only. |
| `system/init` | `session_id`, `cwd`, `model`, `permissionMode`, `tools[]`, `mcp_servers[{name,status}]`, `plugins[]`, `plugin_errors?`, `mcp_server_errors?`, `apiKeySource`, `claude_code_version`, `skills[]`, `capabilities?` | `SESSION`. **Billing guard:** with `auth: subscription`, kill and fail when `apiKeySource ∈ {"ANTHROPIC_API_KEY","apiKeyHelper","/login managed key"}` (enum [bundle]). |
| `assistant` | `message` (Anthropic Message: `content[]` of `text` / `tool_use{id,name,input}` / `thinking`, `usage`), `parent_tool_use_id` (null = main loop), `error?` | `TEXT` (main-loop text blocks only) and `TOOL_START` per `tool_use`. If `error` is set, emit `ERROR(code=error)`. |
| `user` | `message.content[]` with `tool_result{tool_use_id, content, is_error}`, `tool_use_result?` | `TOOL_END(id, is_error)` |
| `system/api_retry` | `attempt`, `max_retries`, `retry_delay_ms`, `error_status`, `error` | `RETRY` (non-fatal) |
| `system/permission_denied` | `tool_name`, `tool_use_id`, `decision_reason_type?` | `PERMISSION_DENIED` |
| `system/compact_boundary` | `compact_metadata{trigger: manual\|auto, pre_tokens, post_tokens?}` | `COMPACTION` |
| `stream_event` | Only emitted with `--include-partial-messages` | ignore |
| `result` (last line) | `subtype ∈ {success, error_during_execution, error_max_turns, error_max_budget_usd, error_max_structured_output_retries}`, `is_error`, `num_turns`, `result` (string, success only), `structured_output?`, `errors[]` (error subtypes), `stop_reason`, `terminal_reason?`, `total_cost_usd`, `usage`, `modelUsage{model:{inputTokens,outputTokens,cacheReadInputTokens,cacheCreationInputTokens,costUSD,…}}`, `permission_denials[]`, `api_error_status?`, `duration_ms`, `duration_api_ms` | `FINAL` |

The `error` category enum (on `assistant` and `api_retry`) is: `authentication_failed`, `oauth_org_not_allowed`,
`account_on_hold`, `verification_required`, `billing_error`, `rate_limit`, `overloaded`, `invalid_request`,
`model_not_found`, `server_error`, `unknown`, `max_output_tokens`, `cloud_credential_error`.

`terminal_reason` enum [bundle]:

- normal: `completed`, `max_turns`, `aborted_streaming`, `aborted_tools`, `stop_hook_prevented`, `hook_stopped`, `tool_deferred`,
  `background_requested`;
- failure: `blocking_limit`, `rapid_refill_breaker`, `prompt_too_long`, `image_error`, `model_error`, `api_error`,
  `malformed_tool_use_exhausted`, `budget_exhausted`, `structured_output_retry_exhausted`, `tool_deferred_unavailable`,
  `turn_setup_failed`.

**Mapping to `result.json`:**

| `result.json` field | Source |
| --- | --- |
| `session_id` | the pre-assigned uuid (verify it equals `init.session_id`) |
| `report` | `structured_output` if present, else extract the last JSON object from `result` |
| `usage.cost_usd` | `total_cost_usd` **minus the previous iteration's value**: the figure is cumulative across a resumed conversation [doc headless] |
| `usage.tokens` | sum over `modelUsage[*]` (includes subagents; `usage` covers the main loop only [bundle describe text]) |
| tool calls | count of `tool_use` blocks with `parent_tool_use_id == null` |

### 2c. Exit codes and failure signatures

| Situation | Exit | Signature | `FailureKind` |
| --- | --- | --- | --- |
| Success | 0 | `result.subtype=="success" && !is_error` | — |
| Bad flag or usage | 1 | stderr `error: unknown option …` or `Error: …`; no stdout JSON [probe] | `CLI_USAGE` |
| No prompt | 1 | stderr `Error: Input must be provided either through stdin or as a prompt argument when using --print` [probe] | `CLI_USAGE` |
| Invalid `--json-schema` | 1 | stderr `Error: --json-schema is not valid JSON` / `must be a JSON object` / `is not a valid JSON Schema` [probe][doc] | `SCHEMA` |
| Auth failure in the run | ≠0 [doc] | The failure "is printed as the result on stdout" [doc headless]: `assistant.error=="authentication_failed"` (or `oauth_org_not_allowed`, `account_on_hold`, `verification_required`), then `result{subtype:"success", is_error:true, api_error_status:401\|403}` [bundle, inferred]. Text like "Not logged in · Please run /login". | `AUTH` |
| Subscription limit | ≠0 | `terminal_reason ∈ {blocking_limit, rapid_refill_breaker}`, or `error ∈ {rate_limit, billing_error}` with retries exhausted | `QUOTA` |
| Max turns | ≠0 [inferred] | `subtype:"error_max_turns"`, `errors:["Reached maximum number of turns (N)"]`, `terminal_reason:"max_turns"` [bundle] | `MAX_TURNS` (resumable) |
| Budget cap | ≠0 [inferred] | `subtype:"error_max_budget_usd"` / `terminal_reason:"budget_exhausted"` | `BUDGET` |
| Schema never satisfied | ≠0 [inferred] | `subtype:"error_max_structured_output_retries"`, `terminal_reason:"structured_output_retry_exhausted"` [bundle] | `SCHEMA` |
| Context overflow | ≠0 | `terminal_reason:"prompt_too_long"` | `CONTEXT` → sealed fresh session |
| Permission or sandbox denial | 0 (non-fatal) | `system/permission_denied` events; `result.permission_denials[]` non-empty | recorded in `blockers` |
| SIGTERM | 143 | No `result`; the interrupted turn is unrecorded [doc headless] | `TIMEOUT`/`CANCELLED` |

### 2d. Prompt supply (Windows)

- Prompt bytes go to stdin, then stdin is closed. Do not pass a positional prompt.
- Cap: **10 MB** piped stdin, beyond which it exits non-zero [doc headless].
- If stdin were also a pipe alongside a positional prompt, it would become context. The runner never does that.
- `--json-schema` must be inline. Keep it under 8 KB and pass it as a single argv element. `subprocess` list-to-cmdline
  quoting is correct for `claude.exe` (an MSVCRT/Bun argv parser) because no shell is involved.
- `--allowedTools` values with spaces (`Bash(uv run pytest *)`) are single argv elements. No shell quoting is needed.

### 2e. Session id and resume semantics

- **Before completion:** the runner pre-assigns `--session-id`, so the id is known before launch. Every event, including the
  hook events before `init`, carries it [probe].
- Resume continues the same id and transcript, compacted history included. Auto-compact is on by default. The recorded system
  prompt is reused verbatim until compaction (`--system-prompt-snapshot on` default [help]), so `--append-system-prompt`
  changes on resume are ignored. Put iteration feedback in the stdin prompt.
- Per launch, the runner must re-pass permission mode, allowed tools, `--max-turns`, `--json-schema` and model. **None of
  them are persisted.**
- `total_cost_usd` on resume covers the whole conversation [doc headless].

### 2f. Env (auth and billing)

**Scrub** (the allowlist drops them anyway):

| Group | Variables |
| --- | --- |
| Anthropic | `ANTHROPIC_*` (all: `API_KEY`, `AUTH_TOKEN`, `BASE_URL`, `CUSTOM_HEADERS`, `MODEL`, `PROFILE`, `CONFIG_DIR`, `FOUNDRY_*`, `BEDROCK_*`, `VERTEX_*`, `AWS_*`, `GOOGLE_CLOUD_*`, `IDENTITY_TOKEN*`, `ORGANIZATION_ID`, `WORKSPACE_ID`, `UNIX_SOCKET`) |
| Cloud providers | `CLAUDE_CODE_USE_{BEDROCK,VERTEX,FOUNDRY,GATEWAY,MANTLE,ANTHROPIC_AWS,ANTHROPIC_GOOGLE_CLOUD}`, `AWS_BEARER_TOKEN_BEDROCK` |
| API-key fds | `CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR` |
| Session and nesting markers | `CLAUDE_CODE_SESSION_ACCESS_TOKEN`, `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_SIMPLE`, `CLAUDE_CODE_SAFE_MODE` |

These names are enumerated from the bundle; the precedence is documented in [doc authentication].

**Keep** (subscription paths): `CLAUDE_CODE_OAUTH_TOKEN` (when the owner uses `claude setup-token`) and `CLAUDE_CONFIG_DIR`
(if non-default).

**Set:** `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=60000`, so a forgotten background shell does not hold the run for 10 minutes
[doc headless]. `apiKeyHelper` in settings cannot be scrubbed through env: the preflight `claude auth status` must show
`authMethod ∈ {claude.ai, oauth_token}` (`api_key_helper` fails it), and the `init.apiKeySource` guard is the in-run backstop.

### 2g. Windows launch and kill

- `shutil.which("claude")` resolves `C:\Users\Pinda\.local\bin\claude.exe`. Spawn it directly with
  `creationflags=CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW`.
- Bash tool calls spawn Git Bash children, and Claude kills its Bash process tree on SIGTERM [doc]. On Windows the runner
  cannot send POSIX SIGTERM. It uses `taskkill /PID <pid> /T /F` (exit code then 1; the runner records `TIMEOUT` itself),
  optionally preceded by `CTRL_BREAK_EVENT` with a 10 s grace (an unverified clean-shutdown path).
- Hardening: assign the child to a Win32 Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes), so the tree dies
  even if the runner crashes.

### 2h. WSL

Claude is **not installed in WSL** [probe]. Use native Windows. If added later: `curl -fsSL https://claude.ai/install.sh | bash`
inside WSL, a separate login (credentials in `~/.claude/.credentials.json` on the Linux side), and the same argv.

---

## 3. Codex adapter (`codex exec`, 0.162.1)

### 3a. Argv templates (each validated by clap parse probes [probe] and `--help` [help])

All options go **before** the subcommand (see C3). The prompt is always `-` (stdin forced) [help][src
`StdinPromptBehavior::Forced`].

**Common prefix:**

```text
{codex.exe} exec
  --json --color never
  --ignore-user-config                     # don't load ~/.codex/config.toml (danger-full-access default, 8 MCP servers, plugins, hook trust); auth still from CODEX_HOME [help]
  -c forced_login_method="chatgpt"         # auth=subscription only, AFTER env scrub (C11)
  -c windows.sandbox="elevated"            # Windows only: re-supply the setting dropped by --ignore-user-config (enum elevated|unelevated|mxc [bundle])
  -c approval_policy="never"               # explicit; exec already forces Never [src lib.rs:591]
  -C {worktree}                            # also set the process cwd = worktree
  [-m {model.name}] [-c model_reasoning_effort="{effort}"]
  -o {iter_dir}/last-message.txt           # written at shutdown when the turn completes [src event_processor.rs]
  [--output-schema {iter_dir}/schema.json] # structured mode (file path, JSON)
  {PROFILE FLAGS}
  {MODE TAIL}
```

**Profile flags:**

| Profile | Flags |
| --- | --- |
| `read-only` | `-s read-only` (+ `--ephemeral` only if `max_iterations == 1`, per C4) |
| `edit` | `-s workspace-write`. Add `[-c sandbox_workspace_write.network_access=true]` only when the job needs network (e.g. `uv sync`); the default is no network [inferred from config key `sandbox_workspace_write` [bundle]]. `[--add-dir {dir}]` for extra writable roots. |
| `full` | `--dangerously-bypass-approvals-and-sandbox` (hidden alias `--yolo` parses [probe]; it also skips the git-repo check [src lib.rs:1013]) |

**Mode tails:**

| Mode | Tail |
| --- | --- |
| new | `-` |
| resume | `resume {thread_id} -` |
| fork (sealed restart alternative) | `fork {thread_id} -` |

A user-config opt-in (`codex.use_user_config: true`) drops `--ignore-user-config`. **`-s` must then always be present,
including on resume**, because the user default is `danger-full-access`.

Never emit:

- `-a …` and `--full-auto` (both exit 2);
- `--worktree` (feature-gated, and rejected with `exec resume`, `--ephemeral` and `--ignore-user-config` [src lib.rs:312-324]);
- `--dangerously-bypass-hook-trust`;
- `--approve-for-me`, unless the job asks for auto-review.

### 3b. Event schema (`--json`) [src `exec/src/exec_events.rs`]

| Event | Fields | Mapping |
| --- | --- | --- |
| `thread.started` | `thread_id` | `SESSION` (first line; resume id) |
| `turn.started` | — | ignore |
| `item.started` / `item.updated` / `item.completed` | `item{id, type, …}` | see the item table below |
| `turn.completed` | `usage{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens}` | `USAGE`, then `FINAL(ok)`. **These are thread-cumulative totals** (`usage.total` [src `usage_from_last_total`]). Compute the per-iteration delta. |
| `turn.failed` | `error{message}` | `FINAL(error)` |
| `error` | `message` | `ERROR` (`last_critical_error`; the stream may continue with `will_retry`) |

Item types:

| Item `type` | Fields | Mapping |
| --- | --- | --- |
| `agent_message` | `text` (a JSON string when `--output-schema` is set) | `TEXT`; the last one is the final text |
| `reasoning` | `text` | ignore |
| `command_execution` | `command`, `aggregated_output`, `exit_code?`, `status ∈ in_progress\|completed\|failed\|declined` | `TOOL_START`/`TOOL_END`; `declined` → `PERMISSION_DENIED` |
| `file_change` | `changes[{path, kind: add\|delete\|update}]`, `status ∈ in_progress\|completed\|failed` | `TOOL_END` (only `item.completed`) |
| `mcp_tool_call` | `server`, `tool`, `arguments`, `result?{content[], structured_content}`, `error?{message}`, `status` | `TOOL_*` |
| `collab_tool_call` | `tool ∈ spawn_agent\|send_input\|wait\|close_agent`, `receiver_thread_ids`, `status` | `TOOL_*` |
| `web_search` | `query`, `action` | `TOOL_*` |
| `todo_list` | `items[{text, completed}]` | ignore (progress) |
| `error` | `message` | **non-fatal** warning (config warnings and deprecations are also emitted as `error` items [src]) → `RETRY`/`WARN` |

Stdout carries only JSONL with `--json`. Progress and warnings go to **stderr** [doc][src].

**Mapping to `result.json`:**

| `result.json` field | Source |
| --- | --- |
| `session_id` | `thread_id` |
| `report` | last `agent_message.text` (or the `-o` file), parsed as JSON when a schema is set |
| `usage.tokens` | the `turn.completed.usage` delta |
| `usage.cost_usd` | `null` (not reported) |

### 3c. Exit codes and failure signatures [src `exec/src/lib.rs`]

| Situation | Exit | Signature | `FailureKind` |
| --- | --- | --- | --- |
| Success | 0 | `turn.completed` | — |
| clap usage | **2** | stderr `error: unexpected argument …` [probe] | `CLI_USAGE` |
| Bad `-c` | 1 | `Error parsing -c overrides` | `CLI_USAGE` |
| Not in a git repo | 1 | `Not inside a trusted directory and --skip-git-repo-check was not specified.` | `CLI_USAGE` |
| Empty stdin prompt | 1 | `No prompt provided via stdin.` | `CLI_USAGE` |
| Schema file unreadable or not JSON | 1 | `Failed to read output schema file …` / `Output schema file … is not valid JSON` | `SCHEMA` |
| Schema rejected by the API (strict-mode constraints) | 1 | `turn.failed` whose message mentions `invalid request` / `invalid schema` [inferred] | `SCHEMA` |
| execpolicy rules error | 1 | `Error loading rules:` | `CLI_USAGE` |
| Wrong login type under the guard | 1 | `ChatGPT login is required, but an API key is currently being used. Logging out.` [bundle] (**destructive**, per C11) | `AUTH` |
| Not logged in / refresh failure | 1 | Preflight `codex login status` ≠ 0 (stdout `Not logged in`); in-run `error`/`turn.failed` containing `Failed to refresh token` or `401` [bundle strings, inferred] | `AUTH` |
| Plan quota | 1 | `turn.failed` message containing `usage limit`, `quota exceeded`, `usage not included` or `rate limit exceeded` [bundle strings, inferred] | `QUOTA` |
| Context overflow | 1 | message containing `context window exceeded` [bundle string] | `CONTEXT` → sealed restart |
| Required MCP server fails | 1 | startup error [doc] | `CLI_USAGE` |
| Turn failed or interrupted, or a non-retry `error` | **1** | `turn.failed{error}`; `error_seen` → `exit(1)` [src lib.rs:1346-1403] | per message |
| Sandbox denial | 0 (non-fatal) | `command_execution{status:"failed", exit_code≠0}` with the sandbox message in `aggregated_output`, or `status:"declined"`; `file_change{status:"failed"}` | blockers |
| No max-turns or budget flags | — | the runner enforces the wall clock | `TIMEOUT` |

Ctrl-C is handled as a turn interrupt [src lib.rs:1192]. No `turn.completed` follows, and the exit code is 1.

### 3d. Prompt supply

- `codex exec … -` reads stdin to EOF (forced).
- An empty prompt exits 1.
- If a positional prompt is given and stdin is any non-TTY, stdin is appended as a `<stdin>…</stdin>` block. A pipe that is
  never closed is the classic hang [src `resolve_prompt`][doc].
- The runner always uses `-` and closes stdin after writing. The schema is a file (`--output-schema`). Neither the prompt
  nor the schema is length-limited by argv.

### 3e. Session id and resume

- The id is `thread.started.thread_id`, the **first stdout line**, emitted before any model output. Persist it immediately.
  If the process dies before that line, no resumable session exists.
- There is no flag to pre-assign an id (`--thread-source` only classifies the thread).
- `resume {thread_id} -` continues the rollout, compacted history included (`model_auto_compact_token_limit` [research
  B.2]). `ThreadResumeParams` re-sends model, cwd, sandbox and approval from the **current** launch [src lib.rs:1471-1492],
  so the runner must re-pass every option on each resume.
- `--output-schema` applies per turn; pass it again.
- Rollouts live under `CODEX_HOME` (`~/.codex/sessions`, `thread_history_1.sqlite`).

### 3f. Env (auth and billing)

**Scrub:**

- `OPENAI_API_KEY`, `CODEX_API_KEY` and `CODEX_ACCESS_TOKEN` (API pricing or alternate auth [doc][bundle]);
- `OPENAI_BASE_URL` and any `OPENAI_*`;
- `CODEX_EXEC_SERVER_URL` and `CODEX_URL`;
- `CODEX_INTERNAL_ORIGINATOR_OVERRIDE`;
- `CLAUDECODE` (the peer misreports its host [research]).

**Keep:** `CODEX_HOME` (if set; default `%USERPROFILE%\.codex`) and `CODEX_SQLITE_HOME`.

**Set** (parity with `codex.js`, only for update hints): `CODEX_MANAGED_BY_NPM=1` and
`CODEX_MANAGED_PACKAGE_ROOT={npm root}\@openai\codex` [bundle codex.js].

**Preflight:** `codex login status` must exit 0 with stdout containing `ChatGPT` [probe].

### 3g. Windows launch and kill

- **Do not launch `codex.cmd`.** It runs through `cmd.exe`, which brings the 8,191-char limit, `%`/`^`/`!` expansion and a
  `Terminate batch job (Y/N)?` prompt on Ctrl-C. It is also an extra node hop.
- Resolve the native exe instead:
  `$(npm root -g)\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe`.
  `codex.js` only spawns this exe with `stdio:"inherit"`, forwards signals, adds two env vars and changes no PATH [bundle].
- Fallback: `node.exe {npm root}\@openai\codex\bin\codex.js`.
- Sibling helpers (`codex-command-runner.exe`, `codex-windows-sandbox-setup.exe`, `codex-path\rg.exe`) are located relative
  to the exe.
- Kill: `taskkill /PID <pid> /T /F` (the same pattern the official plugin uses in `scripts/lib/process.mjs
  terminateProcessTree` [src plugin]) plus a Job Object.
- **Open:** with `windows.sandbox="elevated"`, commands run as a separate sandbox user via `codex-command-runner.exe`. Whether
  `taskkill /T` from the owner's token can reach them is unverified (§9). The Job Object is the more reliable kill.

How the official plugin drives Codex [src openai/codex-plugin-cc]:

- `/codex:setup` runs `node codex-companion.mjs setup --json`. If Codex is missing it offers `npm install -g @openai/codex`;
  if unauthenticated it tells the user to run `!codex login`.
- Auth is checked through `codex app-server` JSON-RPC (`account/read {refreshToken:false}` plus `config/read`), not the
  login-status text.
- It spawns `codex app-server` with `shell: true` on Windows (so the `.cmd` resolves), `windowsHide:true`, and kills the tree
  with `taskkill /PID /T /F`.
- Threads start with `approvalPolicy:"never"`, `sandbox:"read-only"` (review) or `"workspace-write"` (`--write` tasks), and
  `ephemeral:true` for reviews. Persistent named threads are used for resumable tasks, and resume uses `thread/resume` on
  the latest thread.

Pattern to adopt: **check auth before work**, use a read-only plus ephemeral default for review, and persist only what must
be resumed. Our runner uses `exec --json` rather than app-server to stay stdlib-only; app-server stays an optional v2
transport.

### 3h. WSL

- Today: **not usable** (C5).
- Setup: install Linux node or the standalone release binary in WSL, then `npm i -g @openai/codex@0.162.1`.
- Auth: `codex login --device-auth` inside WSL (a separate `~/.codex`; do not copy `auth.json`, per SPEC-08 §6).
- In WSL the sandbox is Linux bubblewrap/landlock instead of the Windows elevated sandbox. Drop `-c windows.sandbox`.
- Run the worktree on ext4 (§8).

---

## 4. Cursor adapter (`agent -p`, 2026.10.01-14929f9)

### 4a. Argv templates (flags present in `--help` [help]; hidden flags from the bundle option table [bundle])

The binary is `{ver}\node.exe {ver}\index.js` (§4g). The prompt is **stdin** (C8). There is no positional prompt.

**Common prefix:**

```text
node.exe index.js -p
  --output-format stream-json
  --trust                                  # headless-only; untrusted fresh workspace otherwise hangs/blocks [help][research]
  --workspace {worktree}                   # also set the process cwd = worktree
  [--model {model.name}[effort brackets]]  # e.g. 'claude-opus-4-8[context=1m,effort=high]' — effort lives in the model string [help]
  {PROFILE FLAGS}
  {MODE FLAGS}
```

**Profile flags:**

| Profile | Flags |
| --- | --- |
| `read-only` | `--mode ask --sandbox enabled` (no `--force`). Alternative `read-only-plan`: `--mode plan`. |
| `edit` | `--force --sandbox enabled` plus a generated `{worktree}/.cursor/cli.json` `{"permissions":{"allow":["Shell(uv run pytest *)",…],"deny":["Shell(git push *)","Shell(git commit *)",…]}}`. `--force` = "allow commands unless explicitly denied" [help], so the **deny** list is the operative control. The `.cursor/cli.json` file is project permissions only [doc configuration]. Never pass `--disable-project-configs` (hidden; it ignores that file [bundle]). |
| `full` | `--force --sandbox disabled` |

**Mode flags:**

| Mode | Flags |
| --- | --- |
| new | (none). Optionally `--new-session-id {uuid4}` (hidden: "Create a new session with a caller-provided ID" [bundle]), or the documented route: `agent create-chat` → id → `--resume {id}` [help]. |
| resume | `--resume {session_id}` |
| structured | no native flag. The prompt demands a final fenced JSON object, which the adapter extracts and validates. |

**Optional hidden bounds** (unstable, so feature-gate on a version check):

- `--single-turn`: "finish after the initial user turn and delegated subagents (skip background shell wait and other
  follow-up turns)";
- `--background-shell-timeout <s>` [bundle].

**Never pass:**

- `--approve-mcps`;
- `--auto-review` (server classifier);
- `--printenv` (hidden; puts a **full env snapshot** into `tool_call.completed.env` [bundle]);
- `--stream-partial-output` (duplicate-text handling [doc]);
- `--api-key` (puts the key in argv; use env instead).

### 4b. Event schema (stream-json) [doc output-format][bundle `2571.index.js`]

| Event | Fields | Mapping |
| --- | --- | --- |
| `system/init` | `apiKeySource ∈ env\|flag\|login`, `cwd`, `session_id`, `model` (display name), `permissionMode:"default"` | `SESSION` (first line) |
| `user` | `message{role:"user", content[{type:"text", text}]}`, `session_id` | ignore (echo of the prompt; redact) |
| `assistant` | `message{role:"assistant", content[{type:"text", text}]}`, `session_id`, `model_call_id?`, `timestamp_ms?` (one line per complete message between tool calls when partial output is off) | `TEXT`; **the last one is the final text** |
| `tool_call/started` | `call_id`, `tool_call{<kind>ToolCall:{args}}`, `model_call_id`, `timestamp_ms` | `TOOL_START(name=<kind>)` |
| `tool_call/completed` | `call_id`, `tool_call{<kind>ToolCall:{args, result:{success\|failure\|rejected\|permissionDenied\|spawnError\|timeout: …}}}` | `TOOL_END`. `rejected`/`permissionDenied` → `PERMISSION_DENIED`. For shell, `success` carries an `exitCode`. |
| `thinking/delta`, `thinking/completed` | `text` | ignore (doc says they are suppressed in print mode; the code emits them with stream-json) |
| `retry/{starting\|resuming}` | `attempt`, `is_resume?`, `checkpoint_turn_count?` | `RETRY` |
| `connection/reconnecting` | `attempt`, `endpoint_url?` | `RETRY` |
| `interaction_query/{request\|response}` | `query_type`, `query`/`response` | log (headless auto-answers: questions are skipped; web search/fetch are approved only with `--force` [bundle]) |
| `system/task_notification`, `system/background_shell_timeout` | — | log |
| `result/success` (success only) | `is_error:false`, `duration_ms`, `duration_api_ms`, `result` (concatenation of **all** assistant text), `session_id`, `request_id?`, `usage?{inputTokens (excl. cache), outputTokens, cacheReadTokens, cacheWriteTokens}` | `FINAL(ok)` |

`<kind>` values seen in the bundle:

- tools: `shell`, `read`, `edit`, `delete`, `ls`, `glob`, `grep`, `semSearch`, `readLints`, `mcp`, `webSearch`, `webFetch`,
  `task`;
- planning and goals: `createPlan`, `updateTodos`, `readTodos`, `createGoal`, `updateGoal`;
- control and misc: `askQuestion`, `switchMode`, `await`, `writeShellStdin`, `generateImage`, `getMcpTools`,
  `readMcpResource`, `listMcpResources`, `communicateUpdate`, `aiAttribution`, `partial`.

The docs also show `writeToolCall` and the generic `function{name, arguments}` [doc].

**Mapping to `result.json`:**

| `result.json` field | Source |
| --- | --- |
| `session_id` | `init.session_id` |
| `report` | last JSON object in the last `assistant` text, falling back to the last JSON object in `result` |
| `usage.tokens` | `result.usage`, when present (the value from the last `turnEnded`; may undercount a multi-turn run [inferred]) |
| `usage.cost_usd` | `null` |

### 4c. Exit codes and failure signatures [bundle]

| Situation | Exit | Signature | `FailureKind` |
| --- | --- | --- | --- |
| Success | 0 | `result/success` | — |
| Any run error | **1** | Message on **stderr**. **No `result` event**; the stream may end after `init` [doc][bundle `GZ({code:1})`]. | by stderr text |
| Auth failure | 1 | stderr `…Please run 'agent login' to authenticate.` or `Authentication required. Please run 'agent login' to authenticate.` [bundle] | `AUTH` |
| Bad option | 1 (commander) | stderr `error: unknown option …` | `CLI_USAGE` |
| `--output-format` without print | 1 | `Error: --output-format can only be used with --print` | `CLI_USAGE` |
| Resume of a running persistent chat | 1 | `Chat {id} may still be running, but Cursor could not verify its persistent session` | `CLI_USAGE` |
| SIGINT | **130** | `Operation cancelled` | `CANCELLED` |
| SIGTERM | **143** | — | `TIMEOUT` |
| Quota, usage limit or model errors | 1 | stderr text [inferred] | `QUOTA`/`API` |
| No max-turns, no budget, no schema | — | the runner enforces the wall clock and validates the report | — |

### 4d. Prompt supply

- Stdin, written then closed (C8). With a positional prompt, stdin is ignored (never read).
- With no positional prompt and stdin left open, the CLI waits for EOF forever.
- There is no documented length cap; it is Node string memory.
- Do **not** go through `agent.cmd` → PowerShell `$args`. That path re-splits and re-quotes arguments and inherits the
  8,191-char cmd limit.
- `@file` references inside the prompt are an alternative for very large context.

### 4e. Session id and resume

- `system/init.session_id` is the first stdout line. For a pre-known id, use `agent create-chat` (documented; prints an id,
  with no model call [help]) and then `--resume {id}` on iteration 1, or the hidden `--new-session-id`.
- `--resume {chatId}` with `-p` continues the chat; re-pass every flag.
- Headless auto-summarization is undocumented [research B.3]. Keep SPEC-08's **sealed restart** for Cursor: start a fresh
  chat seeded with the `handoff` after 3 iterations or on any context error.

### 4f. Env (auth and billing)

**Scrub:**

- `CURSOR_API_ENDPOINT`, `CURSOR_API_URL` and `CURSOR_WEBSITE_URL` (redirect the backend);
- `CURSOR_AUTH_TOKEN` and `CURSOR_AUTH_TOKEN_EXPIRES_AT`;
- `CURSOR_LOCAL_AGENT_*`;
- the nested-session markers `CURSOR_AGENT`, `CURSOR_CONVERSATION_ID`, `CURSOR_AGENT_WORKER_ID` and `CURSOR_REQUEST_ID`,
  which are set inside Cursor-spawned shells [bundle];
- `CLAUDECODE`.

**Pass** `CURSOR_API_KEY` only when `auth: api`, or when the owner chooses key auth. Today the browser login works without it
(`apiKeySource` is then `login`).

**Billing guard:** with `auth: subscription` and no key intended, fail if `init.apiKeySource != "login"`.

**Set** `CURSOR_INVOKED_AS=agent` (the ps1 sets it; used in messages) and optionally
`NODE_COMPILE_CACHE=%LOCALAPPDATA%\cursor-compile-cache` [bundle ps1].

### 4g. Windows launch and kill

Resolution replicates `cursor-agent.ps1` [bundle]:

1. List `%LOCALAPPDATA%\cursor-agent\versions\*` directories matching
   `^\d{4}\.\d{1,2}\.\d{1,2}(-\d{2}-\d{2}-\d{2})?-[a-f0-9]+$`.
2. Sort by `YYYYMMDD` and take the newest. **Pin it for the whole job** and record it, because `agent update` can add a
   version mid-run.
3. Launch argv `[ver\node.exe, ver\index.js, …]` with cwd = worktree.

Kill: `taskkill /PID /T /F` plus a Job Object. The bundled `node.exe` spawns `rg.exe`, `cursorsandbox.exe` and shells.

### 4h. WSL

`~/.local/bin/cursor-agent` exists in WSL but is **2025.10.02-bd871ac**, a year old. Its `status` lacks `--format`
[probe]. Before any WSL use, run `cursor-agent update` and `agent login` inside WSL (a separate credential store). The argv is
the same; the binary is `~/.local/bin/agent` (or `cursor-agent`).

---

## 5. Cross-cutting: child env allowlist (Windows)

SPEC-08 §6's allowlist is **too small for Windows**. Node, Bun and Rust on Windows need these to locate profile, temp and
system dirs.

**Base allowlist** (copy only those present):

- profile and home: `PATH`, `PATHEXT`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`,
  `HOME` (Git Bash), `USERNAME`, `USERDOMAIN`;
- app data and temp: `APPDATA`, `LOCALAPPDATA`, `PROGRAMDATA`, `ProgramFiles`, `ProgramFiles(x86)`, `CommonProgramFiles`,
  `TEMP`, `TMP`;
- machine: `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`, `OS`;
- language: `LANG`, `LC_ALL`;
- tooling the agent will need for `verify`-like commands: `UV_CACHE_DIR`, `UV_PYTHON` (if set);
- per CLI: Claude `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_OAUTH_TOKEN`; Codex `CODEX_HOME`, `CODEX_SQLITE_HOME`; Cursor
  `CURSOR_API_KEY` (conditional).

**Then force-delete** the per-CLI scrub lists above (defense in depth), and set the per-CLI additions. Never log env.
Redact values of `CURSOR_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` and token-shaped strings (`sk-…`, `sk-ant-…`, `key_…`,
`Bearer …`, `eyJ…` JWTs) in `run.jsonl`.

---

## 6. Adapter contract (Python, stdlib-only plus `jsonschema`)

```python
# scripts/adapters/base.py  (PEP 604 types; Python 3.12)
from __future__ import annotations
import enum, json, re, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

Profile = Literal["read-only", "read-only-plan", "edit", "full"]

@dataclass(frozen=True)
class Budget:
    max_iterations: int = 4
    max_turns_per_iteration: int = 40      # Claude only (hidden --max-turns)
    wall_clock_min: int = 45               # runner-enforced, all CLIs
    max_usd: float | None = None           # Claude only (--max-budget-usd, remaining)

@dataclass(frozen=True)
class Job:
    id: str
    cli: Literal["claude", "codex", "cursor"]
    goal: str
    permissions: Profile
    allow_commands: tuple[str, ...]
    deny_commands: tuple[str, ...]         # used by cursor cli.json (+ claude --disallowedTools)
    model_name: str | None
    model_effort: str | None
    output_schema: dict[str, Any] | None   # JSON Schema of the final report
    budget: Budget
    auth: Literal["subscription", "api"]
    host: Literal["native", "wsl"]
    isolation: Literal["inherit", "project-only"] = "inherit"
    worktree: Path = Path(".")
    run_dir: Path = Path(".tmp/agent-jobs")  # .tmp/agent-jobs/<id>/

    def iter_dir(self, n: int) -> Path: return self.run_dir / self.id / f"iter-{n}"
    def prompt_path(self, n: int) -> Path: return self.iter_dir(n) / f"prompt-{n}.md"  # rendered by runner

class Kind(enum.Enum):
    SESSION = "session"; TEXT = "text"; TOOL_START = "tool_start"; TOOL_END = "tool_end"
    USAGE = "usage"; PERMISSION_DENIED = "permission_denied"; RETRY = "retry"; WARN = "warn"
    ERROR = "error"; COMPACTION = "compaction"; FINAL = "final"; IGNORE = "ignore"; UNPARSEABLE = "unparseable"

class FailureKind(enum.Enum):
    AUTH = "auth"; QUOTA = "quota"; MAX_TURNS = "max_turns"; BUDGET = "budget"; SCHEMA = "schema"
    CONTEXT = "context"; API = "api"; CLI_USAGE = "cli_usage"; TIMEOUT = "timeout"
    CANCELLED = "cancelled"; NO_RESULT = "no_result"; BILLING_GUARD = "billing_guard"; UNKNOWN = "unknown"

@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0; output_tokens: int = 0; cache_read_tokens: int = 0
    cache_write_tokens: int = 0; reasoning_tokens: int = 0
    cost_usd: float | None = None
    cumulative: bool = False               # True: Claude cost & Codex tokens are conversation/thread totals

@dataclass(frozen=True)
class RunnerEvent:
    kind: Kind
    session_id: str | None = None
    text: str | None = None                # TEXT: main-loop assistant text only
    tool_name: str | None = None; tool_id: str | None = None
    tool_status: str | None = None; tool_exit_code: int | None = None
    usage: Usage | None = None
    error_code: str | None = None          # CLI-native category (claude `error`, cursor result case, ...)
    message: str | None = None
    fatal: bool = False
    final_ok: bool | None = None           # FINAL only
    final_payload: dict[str, Any] | None = None  # raw terminal object (claude result / codex turn.* / cursor result)
    raw: dict[str, Any] | None = None

@dataclass
class FinalReport:
    ok: bool
    session_id: str | None
    final_text: str | None
    structured: dict[str, Any] | None      # validated against job.output_schema when given
    usage: Usage
    num_turns: int | None
    tool_calls: int
    permission_denials: list[dict[str, Any]] = field(default_factory=list)
    failure: FailureKind | None = None
    failure_detail: str | None = None
    resumable: bool = True                 # False: AUTH, CLI_USAGE, BILLING_GUARD, ephemeral codex

class Adapter(Protocol):
    name: str
    def resolve_binary(self, host: str) -> list[str]: ...                 # argv prefix, e.g. [node.exe, index.js]
    def preflight(self, job: Job) -> tuple[bool, str]: ...                # auth/version checks (no model calls)
    def prepare(self, job: Job, iteration: int) -> None: ...              # side files: schema.json, .cursor/cli.json
    def build_argv(self, job: Job, iteration: int, resume_id: str | None
                   ) -> tuple[list[str], bytes, dict[str, str]]: ...      # (argv, stdin_bytes, env)
    def parse_event(self, line: bytes) -> RunnerEvent: ...
    def final(self, events: Sequence[RunnerEvent], exit_code: int | None,
              stderr_tail: str, timed_out: bool) -> FinalReport: ...

# ---------- shared helpers ----------
SECRET_RE = re.compile(r"(sk-(ant-)?[A-Za-z0-9_\-]{16,}|key_[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")
BASE_ENV_ALLOW = ("PATH PATHEXT SYSTEMROOT SYSTEMDRIVE WINDIR COMSPEC USERPROFILE HOMEDRIVE HOMEPATH HOME USERNAME "
                  "USERDOMAIN APPDATA LOCALAPPDATA PROGRAMDATA ProgramFiles ProgramFiles(x86) CommonProgramFiles "
                  "TEMP TMP NUMBER_OF_PROCESSORS PROCESSOR_ARCHITECTURE OS LANG LC_ALL UV_CACHE_DIR").split()

def child_env(parent: dict[str, str], extra_allow: Sequence[str], scrub_prefixes: Sequence[str],
              scrub_exact: Sequence[str], set_: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in parent.items() if k in BASE_ENV_ALLOW or k in extra_allow}
    for k in list(env):
        if k in scrub_exact or any(k.startswith(p) for p in scrub_prefixes):
            del env[k]
    env.update(set_)
    return env

def last_json_object(text: str) -> dict[str, Any] | None:
    """Prefer the last ```json fenced block; else scan backwards for a balanced {...} that json-parses."""
    fences = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    for cand in reversed(fences):
        try: return json.loads(cand)
        except ValueError: pass
    for i in range(len(text) - 1, -1, -1):
        if text[i] == "{":
            try:
                obj, end = json.JSONDecoder().raw_decode(text[i:])
                if isinstance(obj, dict) and not text[i + end:].strip(): return obj
            except ValueError: continue
    return None
```

```python
# scripts/adapters/claude.py  (abridged; exact flags from §2a)
class ClaudeAdapter:
    name = "claude"
    def build_argv(self, job, iteration, resume_id):
        argv = [*self.resolve_binary(job.host), "-p", "--permission-prompts", "none",
                "--max-turns", str(job.budget.max_turns_per_iteration)]
        if job.model_name:   argv += ["--model", job.model_name]
        if job.model_effort: argv += ["--effort", job.model_effort]
        if job.budget.max_usd is not None: argv += ["--max-budget-usd", f"{self.remaining_usd(job):.2f}"]
        if job.isolation == "project-only": argv += ["--setting-sources", "project,local", "--strict-mcp-config"]
        argv += {"read-only": ["--permission-mode", "dontAsk"],
                 "read-only-plan": ["--permission-mode", "plan"],
                 "edit": ["--permission-mode", "acceptEdits"],
                 "full": ["--permission-mode", "bypassPermissions"]}[job.permissions]
        if job.permissions == "edit":
            rules = ["Read", "Edit", "Write"] + [f"Bash({c})" for c in job.allow_commands] \
                    + [f"PowerShell({c})" for c in job.allow_commands]
            argv += ["--allowedTools", *rules]                 # variadic: MUST be followed by another --flag
        if job.deny_commands:
            argv += ["--disallowedTools", *[f"Bash({c})" for c in job.deny_commands]]
        if resume_id: argv += ["--resume", resume_id]
        else:         self.session_id = str(uuid.uuid4()); argv += ["--session-id", self.session_id]
        if job.output_schema: argv += ["--json-schema", json.dumps(job.output_schema, separators=(",", ":"))]
        argv += ["--output-format", "stream-json", "--verbose"]  # terminates any variadic list
        stdin = job.prompt_path(iteration).read_bytes()
        env = child_env(os.environ, ["CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN"],
                        scrub_prefixes=["ANTHROPIC_", "CLAUDE_CODE_USE_"],
                        scrub_exact=["AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
                                     "CLAUDE_CODE_SESSION_ACCESS_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                                     "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_SAFE_MODE"],
                        set_={"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "60000"})
        return argv, stdin, env

    def parse_event(self, line):
        try: o = json.loads(line)
        except ValueError: return RunnerEvent(Kind.UNPARSEABLE, message=line[:500].decode("utf-8", "replace"))
        t, st, sid = o.get("type"), o.get("subtype"), o.get("session_id")
        if t == "system" and st == "init":
            bad = o.get("apiKeySource") in {"ANTHROPIC_API_KEY", "apiKeyHelper", "/login managed key"}
            return RunnerEvent(Kind.ERROR if bad else Kind.SESSION, session_id=sid, fatal=bad,
                               error_code="billing_guard" if bad else None, raw=o)
        if t == "system" and st == "api_retry":
            return RunnerEvent(Kind.RETRY, session_id=sid, error_code=o.get("error"), raw=o)
        if t == "system" and st == "permission_denied":
            return RunnerEvent(Kind.PERMISSION_DENIED, session_id=sid, tool_name=o.get("tool_name"),
                               tool_id=o.get("tool_use_id"), raw=o)
        if t == "system" and st == "compact_boundary":
            return RunnerEvent(Kind.COMPACTION, session_id=sid, raw=o)
        if t == "assistant":
            if o.get("error"):
                return RunnerEvent(Kind.ERROR, session_id=sid, error_code=o["error"], raw=o)
            if o.get("parent_tool_use_id") is None:
                blocks = o["message"].get("content", [])
                # emit one TEXT for text blocks; TOOL_START per tool_use (runner may expand list)
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                tools = [b for b in blocks if b.get("type") == "tool_use"]
                if tools: return RunnerEvent(Kind.TOOL_START, session_id=sid, tool_name=tools[-1]["name"],
                                             tool_id=tools[-1]["id"], text=text or None, raw=o)
                return RunnerEvent(Kind.TEXT, session_id=sid, text=text, raw=o)
            return RunnerEvent(Kind.IGNORE, session_id=sid, raw=o)
        if t == "user":
            res = [b for b in o.get("message", {}).get("content", []) if isinstance(b, dict) and b.get("type") == "tool_result"]
            if res and o.get("parent_tool_use_id") is None:
                return RunnerEvent(Kind.TOOL_END, session_id=sid, tool_id=res[-1].get("tool_use_id"),
                                   tool_status="error" if res[-1].get("is_error") else "ok", raw=o)
            return RunnerEvent(Kind.IGNORE, session_id=sid, raw=o)
        if t == "result":
            return RunnerEvent(Kind.FINAL, session_id=sid, final_ok=(st == "success" and not o.get("is_error")),
                               final_payload=o, raw=o)
        return RunnerEvent(Kind.IGNORE, session_id=sid, raw=o)

    def final(self, events, exit_code, stderr_tail, timed_out):
        fin = next((e for e in reversed(events) if e.kind is Kind.FINAL), None)
        err_codes = {e.error_code for e in events if e.kind in (Kind.ERROR, Kind.RETRY) and e.error_code}
        denials = [e.raw for e in events if e.kind is Kind.PERMISSION_DENIED]
        if any(e.error_code == "billing_guard" for e in events): return self._fail(FailureKind.BILLING_GUARD, events)
        if fin is None:
            kind = (FailureKind.TIMEOUT if timed_out else FailureKind.CANCELLED if exit_code == 143
                    else FailureKind.SCHEMA if "--json-schema" in stderr_tail
                    else FailureKind.CLI_USAGE if exit_code == 1 and stderr_tail else FailureKind.NO_RESULT)
            return self._fail(kind, events, stderr_tail)
        r = fin.final_payload
        mu = r.get("modelUsage") or {}
        usage = Usage(input_tokens=sum(m.get("inputTokens", 0) for m in mu.values()),
                      output_tokens=sum(m.get("outputTokens", 0) for m in mu.values()),
                      cache_read_tokens=sum(m.get("cacheReadInputTokens", 0) for m in mu.values()),
                      cache_write_tokens=sum(m.get("cacheCreationInputTokens", 0) for m in mu.values()),
                      cost_usd=r.get("total_cost_usd"), cumulative=True)
        sub, tr = r.get("subtype"), r.get("terminal_reason")
        failure = None
        if fin.final_ok is False:
            failure = (FailureKind.MAX_TURNS if sub == "error_max_turns" or tr == "max_turns"
                  else FailureKind.BUDGET if sub == "error_max_budget_usd" or tr == "budget_exhausted"
                  else FailureKind.SCHEMA if sub == "error_max_structured_output_retries"
                  else FailureKind.CONTEXT if tr == "prompt_too_long"
                  else FailureKind.AUTH if err_codes & {"authentication_failed", "oauth_org_not_allowed",
                                                        "account_on_hold", "verification_required"}
                                           or r.get("api_error_status") in (401, 403)
                  else FailureKind.QUOTA if tr in {"blocking_limit", "rapid_refill_breaker"}
                                            or err_codes & {"rate_limit", "billing_error"}
                  else FailureKind.API)
        text = r.get("result")
        structured = r.get("structured_output") or (last_json_object(text) if text else None)
        return FinalReport(ok=failure is None, session_id=r.get("session_id"), final_text=text,
                           structured=structured, usage=usage, num_turns=r.get("num_turns"),
                           tool_calls=sum(1 for e in events if e.kind is Kind.TOOL_START),
                           permission_denials=r.get("permission_denials") or denials, failure=failure,
                           failure_detail="; ".join(r.get("errors") or []) or tr,
                           resumable=failure not in (FailureKind.AUTH, FailureKind.CLI_USAGE))
```

```python
# scripts/adapters/codex.py  (abridged; exact flags from §3a)
class CodexAdapter:
    name = "codex"
    def prepare(self, job, iteration):
        if job.output_schema:
            (job.iter_dir(iteration) / "schema.json").write_text(json.dumps(job.output_schema), "utf-8")
    def build_argv(self, job, iteration, resume_id):
        d = job.iter_dir(iteration)
        argv = [*self.resolve_binary(job.host), "exec", "--json", "--color", "never", "--ignore-user-config",
                "-c", 'approval_policy="never"', "-C", str(job.worktree), "-o", str(d / "last-message.txt")]
        if job.auth == "subscription": argv += ["-c", 'forced_login_method="chatgpt"']   # env already scrubbed
        if os.name == "nt" and job.host == "native": argv += ["-c", 'windows.sandbox="elevated"']
        if job.model_name:   argv += ["-m", job.model_name]
        if job.model_effort: argv += ["-c", f'model_reasoning_effort="{job.model_effort}"']
        if job.output_schema: argv += ["--output-schema", str(d / "schema.json")]
        argv += {"read-only": ["-s", "read-only"], "read-only-plan": ["-s", "read-only"],
                 "edit": ["-s", "workspace-write"],
                 "full": ["--dangerously-bypass-approvals-and-sandbox"]}[job.permissions]
        if job.permissions.startswith("read-only") and job.budget.max_iterations == 1 and not resume_id:
            argv += ["--ephemeral"]
        argv += ["resume", resume_id, "-"] if resume_id else ["-"]   # ALL options precede `resume`
        env = child_env(os.environ, ["CODEX_HOME", "CODEX_SQLITE_HOME"], scrub_prefixes=["OPENAI_"],
                        scrub_exact=["CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CODEX_EXEC_SERVER_URL", "CODEX_URL",
                                     "CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"],
                        set_={"CODEX_MANAGED_BY_NPM": "1"})
        return argv, job.prompt_path(iteration).read_bytes(), env

    def parse_event(self, line):
        try: o = json.loads(line)
        except ValueError: return RunnerEvent(Kind.UNPARSEABLE, message=line[:500].decode("utf-8", "replace"))
        t = o.get("type")
        if t == "thread.started": return RunnerEvent(Kind.SESSION, session_id=o["thread_id"], raw=o)
        if t == "turn.completed":
            u = o.get("usage", {})
            return RunnerEvent(Kind.FINAL, final_ok=True, final_payload=o, raw=o, usage=Usage(
                input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                cache_read_tokens=u.get("cached_input_tokens", 0),
                cache_write_tokens=u.get("cache_write_input_tokens", 0),
                reasoning_tokens=u.get("reasoning_output_tokens", 0), cumulative=True))
        if t == "turn.failed":
            return RunnerEvent(Kind.FINAL, final_ok=False, message=o["error"]["message"], final_payload=o, raw=o)
        if t == "error": return RunnerEvent(Kind.ERROR, message=o.get("message"), raw=o)
        if t in ("item.started", "item.updated", "item.completed"):
            it = o["item"]; ty = it.get("type")
            if ty == "agent_message" and t == "item.completed": return RunnerEvent(Kind.TEXT, text=it["text"], raw=o)
            if ty in ("command_execution", "mcp_tool_call", "web_search", "collab_tool_call", "file_change"):
                st = it.get("status")
                if st == "declined": return RunnerEvent(Kind.PERMISSION_DENIED, tool_name=ty, tool_id=it["id"], raw=o)
                kind = Kind.TOOL_START if t == "item.started" else Kind.TOOL_END if t == "item.completed" else Kind.IGNORE
                return RunnerEvent(kind, tool_name=ty, tool_id=it["id"], tool_status=st,
                                   tool_exit_code=it.get("exit_code"), raw=o)
            if ty == "error": return RunnerEvent(Kind.WARN, message=it.get("message"), raw=o)
        return RunnerEvent(Kind.IGNORE, raw=o)

    QUOTA_RE = re.compile(r"usage limit|quota exceeded|usage not included|rate limit", re.I)
    AUTH_RE = re.compile(r"refresh token|401|unauthori[sz]ed|log ?in|logging out|API key", re.I)
    def final(self, events, exit_code, stderr_tail, timed_out):
        sid = next((e.session_id for e in events if e.kind is Kind.SESSION), None)
        fin = next((e for e in reversed(events) if e.kind is Kind.FINAL), None)
        text = next((e.text for e in reversed(events) if e.kind is Kind.TEXT), None)
        msg = (fin.message if fin and not fin.final_ok else None) or \
              next((e.message for e in reversed(events) if e.kind is Kind.ERROR), None) or stderr_tail
        failure = None
        if fin is None or not fin.final_ok:
            failure = (FailureKind.TIMEOUT if timed_out else FailureKind.CLI_USAGE if exit_code == 2
                  else FailureKind.SCHEMA if msg and "schema" in msg.lower()
                  else FailureKind.CONTEXT if msg and "context window" in msg.lower()
                  else FailureKind.QUOTA if msg and self.QUOTA_RE.search(msg)
                  else FailureKind.AUTH if msg and self.AUTH_RE.search(msg)
                  else FailureKind.CLI_USAGE if sid is None and exit_code == 1
                  else FailureKind.API if fin is not None else FailureKind.NO_RESULT)
        structured = None
        if text:
            try: structured = json.loads(text)          # --output-schema → agent_message is JSON text
            except ValueError: structured = last_json_object(text)
        return FinalReport(ok=failure is None, session_id=sid, final_text=text, structured=structured,
                           usage=fin.usage if fin and fin.usage else Usage(cumulative=True), num_turns=None,
                           tool_calls=sum(1 for e in events if e.kind is Kind.TOOL_START),
                           permission_denials=[e.raw for e in events if e.kind is Kind.PERMISSION_DENIED],
                           failure=failure, failure_detail=msg,
                           resumable=sid is not None and failure not in (FailureKind.AUTH, FailureKind.CLI_USAGE))
```

```python
# scripts/adapters/cursor.py  (abridged; exact flags from §4a)
VERSION_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:-\d{2}-\d{2}-\d{2})?-[a-f0-9]+$")
class CursorAdapter:
    name = "cursor"
    def resolve_binary(self, host):
        if host == "wsl": return ["wsl.exe", "-e", "/home/<user>/.local/bin/agent"]
        root = Path(os.environ["LOCALAPPDATA"]) / "cursor-agent" / "versions"
        vers = [p for p in root.iterdir() if p.is_dir() and VERSION_RE.match(p.name)]
        newest = max(vers, key=lambda p: tuple(int(x) for x in VERSION_RE.match(p.name).groups()))
        self.pinned = newest                                   # pin for the whole job
        return [str(newest / "node.exe"), str(newest / "index.js")]
    def prepare(self, job, iteration):
        if job.permissions == "edit":
            cfg = {"permissions": {"allow": [f"Shell({c})" for c in job.allow_commands],
                                   "deny": [f"Shell({c})" for c in job.deny_commands]}}
            p = job.worktree / ".cursor" / "cli.json"; p.parent.mkdir(exist_ok=True)
            p.write_text(json.dumps(cfg, indent=2), "utf-8")   # untracked in the job worktree; exclude from diffstat
    def build_argv(self, job, iteration, resume_id):
        argv = [*self.resolve_binary(job.host), "-p", "--output-format", "stream-json", "--trust",
                "--workspace", str(job.worktree)]
        if job.model_name: argv += ["--model", job.model_name]   # effort via brackets in the name
        argv += {"read-only": ["--mode", "ask", "--sandbox", "enabled"],
                 "read-only-plan": ["--mode", "plan", "--sandbox", "enabled"],
                 "edit": ["--force", "--sandbox", "enabled"],
                 "full": ["--force", "--sandbox", "disabled"]}[job.permissions]
        if resume_id: argv += ["--resume", resume_id]
        extra = ["CURSOR_API_KEY"] if job.auth == "api" else []
        env = child_env(os.environ, extra, scrub_prefixes=["CURSOR_LOCAL_AGENT_"],
                        scrub_exact=["CURSOR_API_ENDPOINT", "CURSOR_API_URL", "CURSOR_WEBSITE_URL",
                                     "CURSOR_AUTH_TOKEN", "CURSOR_AUTH_TOKEN_EXPIRES_AT", "CURSOR_AGENT",
                                     "CURSOR_CONVERSATION_ID", "CURSOR_AGENT_WORKER_ID", "CURSOR_REQUEST_ID",
                                     "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"],
                        set_={"CURSOR_INVOKED_AS": "agent"})
        return argv, job.prompt_path(iteration).read_bytes(), env
    def parse_event(self, line):
        try: o = json.loads(line)
        except ValueError: return RunnerEvent(Kind.UNPARSEABLE, message=line[:500].decode("utf-8", "replace"))
        t, st, sid = o.get("type"), o.get("subtype"), o.get("session_id")
        if t == "system" and st == "init":
            src = o.get("apiKeySource")
            bad = self.job_auth == "subscription" and src != "login"
            return RunnerEvent(Kind.ERROR if bad else Kind.SESSION, session_id=sid, fatal=bad,
                               error_code="billing_guard" if bad else None, raw=o)
        if t == "assistant":
            txt = "".join(c.get("text", "") for c in o["message"].get("content", []))
            return RunnerEvent(Kind.TEXT, session_id=sid, text=txt, raw=o)
        if t == "tool_call":
            (kind_key, body), = o["tool_call"].items() if len(o["tool_call"]) == 1 else (("unknown", {}),)
            res = body.get("result") or {}
            case = next(iter(res), None)                       # success|failure|rejected|permissionDenied|spawnError|timeout
            if st == "completed" and case in ("rejected", "permissionDenied"):
                return RunnerEvent(Kind.PERMISSION_DENIED, session_id=sid, tool_name=kind_key, tool_id=o["call_id"], raw=o)
            ec = (res.get("success") or {}).get("exitCode") if isinstance(res.get("success"), dict) else None
            return RunnerEvent(Kind.TOOL_START if st == "started" else Kind.TOOL_END, session_id=sid,
                               tool_name=kind_key, tool_id=o["call_id"], tool_status=case, tool_exit_code=ec, raw=o)
        if t in ("retry", "connection"): return RunnerEvent(Kind.RETRY, session_id=sid, raw=o)
        if t == "result":
            u = o.get("usage") or {}
            return RunnerEvent(Kind.FINAL, session_id=sid, final_ok=not o.get("is_error"), final_payload=o, raw=o,
                               usage=Usage(input_tokens=u.get("inputTokens", 0), output_tokens=u.get("outputTokens", 0),
                                           cache_read_tokens=u.get("cacheReadTokens", 0),
                                           cache_write_tokens=u.get("cacheWriteTokens", 0)))
        return RunnerEvent(Kind.IGNORE, session_id=sid, raw=o)
    def final(self, events, exit_code, stderr_tail, timed_out):
        sid = next((e.session_id for e in events if e.kind is Kind.SESSION), None)
        fin = next((e for e in reversed(events) if e.kind is Kind.FINAL), None)
        last_msg = next((e.text for e in reversed(events) if e.kind is Kind.TEXT), None)
        failure = None
        if any(e.error_code == "billing_guard" for e in events): failure = FailureKind.BILLING_GUARD
        elif fin is None:      # cursor: errors → exit 1 + stderr, no result event
            s = stderr_tail.lower()
            failure = (FailureKind.TIMEOUT if timed_out else FailureKind.CANCELLED if exit_code in (130, 143)
                  else FailureKind.AUTH if "login" in s and "authenticat" in s
                  else FailureKind.CLI_USAGE if "unknown option" in s or "can only be used" in s
                  else FailureKind.QUOTA if re.search(r"usage limit|quota|rate limit", s)
                  else FailureKind.API if exit_code == 1 else FailureKind.NO_RESULT)
        text = last_msg or (fin.final_payload.get("result") if fin else None)
        structured = last_json_object(last_msg or "") or (last_json_object(fin.final_payload["result"]) if fin else None)
        return FinalReport(ok=failure is None, session_id=sid, final_text=text, structured=structured,
                           usage=fin.usage if fin and fin.usage else Usage(), num_turns=None,
                           tool_calls=sum(1 for e in events if e.kind is Kind.TOOL_START),
                           permission_denials=[e.raw for e in events if e.kind is Kind.PERMISSION_DENIED],
                           failure=failure, failure_detail=stderr_tail[-2000:] if failure else None,
                           resumable=sid is not None and failure not in (FailureKind.AUTH, FailureKind.CLI_USAGE))
```

**Runner-side duties** (not in the adapters):

- validate `FinalReport.structured` against `job.output_schema` with `jsonschema`. A validation failure becomes `SCHEMA` and
  triggers resume feedback;
- turn cumulative usage into per-iteration deltas;
- decide resume versus sealed restart: Cursor after 3 iterations; any CLI on `CONTEXT`; never resume `AUTH`, `CLI_USAGE` or
  `BILLING_GUARD`;
- **launch** (Windows):

  ```python
  subprocess.Popen(argv, cwd=job.worktree, env=env, stdin=PIPE, stdout=PIPE, stderr=PIPE,
                   creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
  ```

  Then `proc.stdin.write(stdin_bytes); proc.stdin.close()`, assign the process to a Job Object, read stdout lines in one
  thread and stderr into a ring buffer in another;
- on deadline, `taskkill /PID {pid} /T /F` and mark `timed_out=True`.

---

## 7. Fake-CLI fixtures (SYNTHETIC — composed from the documented and source schemas above, not captured output)

**Harness convention:** each fixture is a `.jsonl` file. Lines whose only key is `"__fake__"` are directives for the fake
binary and are **not** printed:

- `{"__fake__":{"sleep_ms":N}}`
- `{"__fake__":{"stderr":"text"}}`
- `{"__fake__":{"exit":N}}` (must be last)
- `{"__fake__":{"expect_stdin_contains":"…"}}`
- `{"__fake__":{"hang":true}}` (wall-clock test)

The fake binary also asserts that its argv matches a golden argv file for the scenario. Ids are fixed fake UUIDs.

### 7.1 Claude — `claude/success-structured.jsonl` (SYNTHETIC)

```jsonl
{"__fake__":{"expect_stdin_contains":"end with a JSON report"}}
{"type":"system","subtype":"init","cwd":"C:\\w\\.worktrees\\fix-relay","session_id":"11111111-1111-4111-8111-111111111111","tools":["Read","Edit","Write","Bash","Glob","Grep"],"mcp_servers":[],"model":"claude-opus-5-5","permissionMode":"acceptEdits","slash_commands":[],"apiKeySource":"none","claude_code_version":"2.1.296","output_style":"default","skills":[],"plugins":[],"uuid":"aaaaaaaa-0000-4000-8000-000000000001"}
{"type":"assistant","message":{"id":"msg_01","type":"message","role":"assistant","model":"claude-opus-5-5","content":[{"type":"text","text":"Running the failing test."},{"type":"tool_use","id":"toolu_01","name":"Bash","input":{"command":"uv run pytest tests/unit/outbox/test_relay.py -q"}}],"stop_reason":"tool_use","usage":{"input_tokens":3200,"output_tokens":60}},"parent_tool_use_id":null,"session_id":"11111111-1111-4111-8111-111111111111","uuid":"aaaaaaaa-0000-4000-8000-000000000002"}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01","content":"1 failed, 3 passed","is_error":false}]},"parent_tool_use_id":null,"session_id":"11111111-1111-4111-8111-111111111111","uuid":"aaaaaaaa-0000-4000-8000-000000000003"}
{"type":"assistant","message":{"id":"msg_02","type":"message","role":"assistant","model":"claude-opus-5-5","content":[{"type":"tool_use","id":"toolu_02","name":"Edit","input":{"file_path":"src/outbox/relay.py","old_string":"retry=0","new_string":"retry=attempt"}}],"stop_reason":"tool_use","usage":{"input_tokens":3500,"output_tokens":80}},"parent_tool_use_id":null,"session_id":"11111111-1111-4111-8111-111111111111","uuid":"aaaaaaaa-0000-4000-8000-000000000004"}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_02","content":"The file src/outbox/relay.py has been updated.","is_error":false}]},"parent_tool_use_id":null,"session_id":"11111111-1111-4111-8111-111111111111","uuid":"aaaaaaaa-0000-4000-8000-000000000005"}
{"type":"assistant","message":{"id":"msg_03","type":"message","role":"assistant","model":"claude-opus-5-5","content":[{"type":"text","text":"Fixed the retry counter."}],"stop_reason":"end_turn","usage":{"input_tokens":3700,"output_tokens":120}},"parent_tool_use_id":null,"session_id":"11111111-1111-4111-8111-111111111111","uuid":"aaaaaaaa-0000-4000-8000-000000000006"}
{"type":"result","subtype":"success","is_error":false,"duration_ms":48210,"duration_api_ms":30110,"num_turns":3,"result":"Fixed the retry counter.","stop_reason":"end_turn","session_id":"11111111-1111-4111-8111-111111111111","total_cost_usd":0.4123,"usage":{"input_tokens":10400,"cache_creation_input_tokens":0,"cache_read_input_tokens":2048,"output_tokens":260},"modelUsage":{"claude-opus-5-5":{"inputTokens":10400,"outputTokens":260,"cacheReadInputTokens":2048,"cacheCreationInputTokens":0,"webSearchRequests":0,"costUSD":0.4123}},"permission_denials":[],"structured_output":{"status":"done","summary":"Retry counter now uses attempt index.","handoff":"","blockers":[]},"terminal_reason":"completed","uuid":"aaaaaaaa-0000-4000-8000-000000000007"}
{"__fake__":{"exit":0}}
```

### 7.2 Claude — `claude/max-turns.jsonl` (SYNTHETIC; exit code [inferred])

```jsonl
{"type":"system","subtype":"init","cwd":"C:\\w\\.worktrees\\fix-relay","session_id":"11111111-1111-4111-8111-111111111111","tools":["Read","Edit","Bash"],"mcp_servers":[],"model":"claude-opus-5-5","permissionMode":"acceptEdits","slash_commands":[],"apiKeySource":"none","claude_code_version":"2.1.296","output_style":"default","skills":[],"plugins":[],"uuid":"bbbbbbbb-0000-4000-8000-000000000001"}
{"type":"system","subtype":"permission_denied","tool_name":"Bash","tool_use_id":"toolu_09","decision_reason_type":"mode","uuid":"bbbbbbbb-0000-4000-8000-000000000002","session_id":"11111111-1111-4111-8111-111111111111"}
{"type":"result","subtype":"error_max_turns","is_error":true,"duration_ms":120000,"duration_api_ms":90000,"num_turns":40,"stop_reason":"tool_use","session_id":"11111111-1111-4111-8111-111111111111","total_cost_usd":1.92,"usage":{"input_tokens":90000,"cache_creation_input_tokens":0,"cache_read_input_tokens":40000,"output_tokens":5000},"modelUsage":{"claude-opus-5-5":{"inputTokens":90000,"outputTokens":5000,"cacheReadInputTokens":40000,"cacheCreationInputTokens":0,"costUSD":1.92}},"permission_denials":[{"tool_name":"Bash","tool_use_id":"toolu_09","tool_input":{"command":"git push"}}],"errors":["Reached maximum number of turns (40)"],"terminal_reason":"max_turns","uuid":"bbbbbbbb-0000-4000-8000-000000000003"}
{"__fake__":{"exit":1}}
```

### 7.3 Claude — `claude/auth-failure.jsonl` (SYNTHETIC; shape [inferred] from the bundle and docs)

```jsonl
{"type":"system","subtype":"init","cwd":"C:\\w\\.worktrees\\x","session_id":"11111111-1111-4111-8111-111111111112","tools":[],"mcp_servers":[],"model":"claude-opus-5-5","permissionMode":"dontAsk","slash_commands":[],"apiKeySource":"none","claude_code_version":"2.1.296","output_style":"default","skills":[],"plugins":[],"uuid":"cccccccc-0000-4000-8000-000000000001"}
{"type":"assistant","message":{"id":"msg_err","type":"message","role":"assistant","model":"<synthetic>","content":[{"type":"text","text":"Not logged in · Please run /login"}],"stop_reason":"stop_sequence","usage":{"input_tokens":0,"output_tokens":0}},"parent_tool_use_id":null,"error":"authentication_failed","session_id":"11111111-1111-4111-8111-111111111112","uuid":"cccccccc-0000-4000-8000-000000000002"}
{"type":"result","subtype":"success","is_error":true,"api_error_status":401,"duration_ms":900,"duration_api_ms":0,"num_turns":1,"result":"Not logged in · Please run /login","stop_reason":"stop_sequence","session_id":"11111111-1111-4111-8111-111111111112","total_cost_usd":0,"usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"modelUsage":{},"permission_denials":[],"uuid":"cccccccc-0000-4000-8000-000000000003"}
{"__fake__":{"exit":1}}
```

### 7.4 Claude — `claude/bad-flag.jsonl` (SYNTHETIC; text from [probe])

```jsonl
{"__fake__":{"stderr":"error: unknown option '--bogus-flag'\n"}}
{"__fake__":{"exit":1}}
```

### 7.5 Codex — `codex/success-structured.jsonl` (SYNTHETIC)

```jsonl
{"__fake__":{"expect_stdin_contains":"end with a JSON report"}}
{"type":"thread.started","thread_id":"0199a213-81c0-7800-8aa1-bbab2a035a53"}
{"type":"turn.started"}
{"type":"item.started","item":{"id":"item_0","type":"command_execution","command":"\"C:\\\\WINDOWS\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe\" -Command \"uv run pytest tests/unit/outbox/test_relay.py -q\"","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_0","type":"command_execution","command":"\"C:\\\\WINDOWS\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe\" -Command \"uv run pytest tests/unit/outbox/test_relay.py -q\"","aggregated_output":"1 failed, 3 passed\n","exit_code":1,"status":"failed"}}
{"type":"item.completed","item":{"id":"item_1","type":"file_change","changes":[{"path":"src/outbox/relay.py","kind":"update"}],"status":"completed"}}
{"type":"item.completed","item":{"id":"item_2","type":"command_execution","command":"\"C:\\\\WINDOWS\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe\" -Command \"uv run pytest tests/unit/outbox/test_relay.py -q\"","aggregated_output":"4 passed\n","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":"{\"status\":\"done\",\"summary\":\"Retry counter now uses attempt index.\",\"handoff\":\"\",\"blockers\":[]}"}}
{"type":"turn.completed","usage":{"input_tokens":24763,"cached_input_tokens":24448,"cache_write_input_tokens":0,"output_tokens":622,"reasoning_output_tokens":210}}
{"__fake__":{"exit":0}}
```

### 7.6 Codex — `codex/turn-failed-quota.jsonl` (SYNTHETIC; message text [inferred])

```jsonl
{"type":"thread.started","thread_id":"0199a213-81c0-7800-8aa1-bbab2a035a54"}
{"type":"turn.started"}
{"type":"error","message":"You've hit your usage limit. Try again later. (usage limit)"}
{"type":"turn.failed","error":{"message":"You've hit your usage limit. Try again later. (usage limit)"}}
{"__fake__":{"exit":1}}
```

### 7.7 Codex — `codex/sandbox-denied.jsonl` (SYNTHETIC; non-fatal)

```jsonl
{"type":"thread.started","thread_id":"0199a213-81c0-7800-8aa1-bbab2a035a55"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"command_execution","command":"git push origin HEAD","aggregated_output":"","exit_code":null,"status":"declined"}}
{"type":"item.completed","item":{"id":"item_1","type":"error","message":"command was not run: sandbox policy (synthetic)"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"I could not push; leaving changes in the worktree.\n```json\n{\"status\":\"blocked\",\"summary\":\"push not permitted\",\"handoff\":\"run git push manually\",\"blockers\":[\"sandbox denied git push\"]}\n```"}}
{"type":"turn.completed","usage":{"input_tokens":8000,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":90,"reasoning_output_tokens":0}}
{"__fake__":{"exit":0}}
```

### 7.8 Codex — `codex/usage-error.jsonl` (SYNTHETIC; text from [probe])

```jsonl
{"__fake__":{"stderr":"error: unexpected argument '-a' found\n\n  tip: to pass '-a' as a value, use '-- -a'\n"}}
{"__fake__":{"exit":2}}
```

### 7.9 Cursor — `cursor/success.jsonl` (SYNTHETIC)

```jsonl
{"__fake__":{"expect_stdin_contains":"end with a JSON report"}}
{"type":"system","subtype":"init","apiKeySource":"login","cwd":"C:\\w\\.worktrees\\review-x","session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff","model":"Claude Opus 4.8","permissionMode":"default"}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"<prompt redacted>"}]},"session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Reading the relay module."}]},"session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff"}
{"type":"tool_call","subtype":"started","call_id":"toolu_vrtx_01","tool_call":{"readToolCall":{"args":{"path":"src/outbox/relay.py"}}},"model_call_id":"mc_1","session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff","timestamp_ms":1791820000000}
{"type":"tool_call","subtype":"completed","call_id":"toolu_vrtx_01","tool_call":{"readToolCall":{"args":{"path":"src/outbox/relay.py"},"result":{"success":{"content":"...","isEmpty":false,"exceededLimit":false,"totalLines":120,"totalChars":4100}}}},"model_call_id":"mc_1","session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff","timestamp_ms":1791820000400}
{"type":"tool_call","subtype":"started","call_id":"toolu_vrtx_02","tool_call":{"shellToolCall":{"args":{"command":"uv run pytest tests/unit/outbox -q"}}},"model_call_id":"mc_2","session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff","timestamp_ms":1791820001000}
{"type":"tool_call","subtype":"completed","call_id":"toolu_vrtx_02","tool_call":{"shellToolCall":{"args":{"command":"uv run pytest tests/unit/outbox -q"},"result":{"success":{"exitCode":0,"stdout":"12 passed\n","stderr":""}}}},"model_call_id":"mc_2","session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff","timestamp_ms":1791820009000}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Review complete.\n```json\n{\"status\":\"done\",\"summary\":\"No defects found in relay retry path.\",\"handoff\":\"\",\"blockers\":[]}\n```"}]},"session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff"}
{"type":"result","subtype":"success","duration_ms":15234,"duration_api_ms":15234,"is_error":false,"result":"Reading the relay module.Review complete.\n```json\n{\"status\":\"done\",\"summary\":\"No defects found in relay retry path.\",\"handoff\":\"\",\"blockers\":[]}\n```","session_id":"c6b62c6f-7ead-4fd6-9922-e952131177ff","request_id":"10e11780-df2f-45dc-a1ff-4540af32e9c0","usage":{"inputTokens":18000,"outputTokens":420,"cacheReadTokens":9000,"cacheWriteTokens":0}}
{"__fake__":{"exit":0}}
```

### 7.10 Cursor — `cursor/denied-then-success.jsonl` (SYNTHETIC; tests the `rejected` case)

```jsonl
{"type":"system","subtype":"init","apiKeySource":"login","cwd":"C:\\w\\.worktrees\\fix-y","session_id":"d0000000-0000-4000-8000-000000000001","model":"Auto","permissionMode":"default"}
{"type":"tool_call","subtype":"started","call_id":"c1","tool_call":{"shellToolCall":{"args":{"command":"git push"}}},"model_call_id":"m1","session_id":"d0000000-0000-4000-8000-000000000001","timestamp_ms":1791820000000}
{"type":"tool_call","subtype":"completed","call_id":"c1","tool_call":{"shellToolCall":{"args":{"command":"git push"},"result":{"rejected":{"reason":"denied by permissions.deny (synthetic)"}}}},"model_call_id":"m1","session_id":"d0000000-0000-4000-8000-000000000001","timestamp_ms":1791820000100}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"```json\n{\"status\":\"blocked\",\"summary\":\"push denied\",\"handoff\":\"push manually\",\"blockers\":[\"git push denied\"]}\n```"}]},"session_id":"d0000000-0000-4000-8000-000000000001"}
{"type":"result","subtype":"success","duration_ms":3000,"duration_api_ms":3000,"is_error":false,"result":"```json\n{\"status\":\"blocked\",\"summary\":\"push denied\",\"handoff\":\"push manually\",\"blockers\":[\"git push denied\"]}\n```","session_id":"d0000000-0000-4000-8000-000000000001"}
{"__fake__":{"exit":0}}
```

### 7.11 Cursor — `cursor/auth-failure.jsonl` (SYNTHETIC; text from [bundle])

```jsonl
{"__fake__":{"stderr":"Authentication required. Please run 'agent login' to authenticate.\n"}}
{"__fake__":{"exit":1}}
```

### 7.12 Cursor — `cursor/error-midstream.jsonl` (SYNTHETIC; no result event, per the docs)

```jsonl
{"type":"system","subtype":"init","apiKeySource":"login","cwd":"C:\\w\\.worktrees\\fix-z","session_id":"e0000000-0000-4000-8000-000000000001","model":"Auto","permissionMode":"default"}
{"type":"retry","subtype":"starting","attempt":1,"is_resume":false,"session_id":"e0000000-0000-4000-8000-000000000001","timestamp_ms":1791820000000}
{"__fake__":{"stderr":"Error: model request failed (synthetic)\n"}}
{"__fake__":{"exit":1}}
```

### 7.13 Any CLI — `common/hang.jsonl` (wall clock and kill-tree test)

```jsonl
{"type":"system","subtype":"init","session_id":"f0000000-0000-4000-8000-000000000001","apiKeySource":"login","cwd":".","model":"x","permissionMode":"default"}
{"__fake__":{"hang":true}}
```

Expected adapter outputs: 7.1, 7.5 and 7.9 give `ok`. 7.2 gives `MAX_TURNS` (resumable). 7.3 and 7.11 give `AUTH` (not
resumable). 7.4 and 7.8 give `CLI_USAGE`. 7.6 gives `QUOTA`. 7.7 and 7.10 give `ok` with permission denials and a `blocked`
report. 7.12 gives `API` (resumable, because `session_id` is known). 7.13 gives `TIMEOUT` once the runner kills the tree.

---

## 8. WSL variant (all CLIs)

- **Status today:** no CLI is usable in WSL without setup (§2h, §3h, §4h). Keep `host: native` as the default on this machine.
- **Launch:** `wsl.exe -d Ubuntu --cd <linux-path> -e <abs-binary> <args…>`. Use absolute binaries: `-e` runs without a
  login shell, so `~/.profile` PATH edits are absent. stdin and stdout pipes cross `wsl.exe` unchanged.
- **Env:** a Windows env does not cross the boundary except through `WSLENV`. Pass only `CURSOR_API_KEY/u` when needed and
  nothing else. Scrub on the Linux side by prefixing `env -i HOME=… PATH=… LANG=C.UTF-8` (an allowlist).
- **Worktree:** create it **inside WSL with WSL git** on ext4 (`~/agent-jobs/<id>`). A Windows-created `git worktree` records
  Windows gitdir paths that Linux git cannot follow, and `/mnt/c` is slow and has permission-mapping issues. `verify` then
  runs in WSL too.
- **Kill:** killing `wsl.exe` does not reliably kill the Linux tree. Launch with `-e setsid --wait <bin> …`, write the pgid to
  a pidfile through a tiny wrapper, and on timeout run `wsl.exe -e kill -TERM -<pgid>`, then `-KILL` after 10 s.
- **Paths in events:** `cwd` and file paths are Linux paths. Map them with `wslpath -w` for `result.json`.

---

## 9. Still open (owner-authorized live smoke, cheap prompts)

1. Claude: the exit code for `error_max_turns`, `error_max_budget_usd` and the auth-failure result (assumed non-zero). Is
   `apiKeySource` `"none"` or `"oauth"` under a claude.ai login? (The guard only blocks API-key sources, so either passes.)
2. Codex native Windows: does `-s workspace-write` with `windows.sandbox="elevated"` under `--ignore-user-config` run
   `uv run pytest`? Is network off by default? Can `taskkill /T` (or a Job Object) kill commands run as the sandbox user?
   What is the exact `turn.failed` text for a usage limit?
3. Cursor: confirm the stdin prompt (C8) live. Can `--mode ask` without `--force` still run read-only shell commands? How
   does `.cursor/cli.json` `deny` interact with `--force`? Is `usage` present in `result`? Does `--resume` keep
   `--mode`/`--force` state or need them re-passed (the adapter re-passes them regardless)?
4. Re-verify hidden flags (`--max-turns`, `--new-session-id`, `--single-turn`) on every CLI upgrade. The runner `doctor`
   should grep the bundle or `--help` and record the result.

---

## Sources

- **Local [help]/[probe]** (captures in `research3/help/`):
  - Claude: `claude --help`, `claude auth --help`, `claude auth status`;
  - Codex: `codex --help`, `codex exec --help`, `codex exec resume|fork|review --help`, `codex login --help`,
    `codex login status`, `codex features list`, `codex app-server --help`, plus the clap parse probes in §0.2;
  - Cursor: `node.exe index.js --help|--version|status --format json` and its `sandbox|create-chat|resume|ls|status|persist|login --help`;
  - environment: `wsl.exe -l -v` and WSL `command -v`.
- **Bundles [bundle]:**
  - `C:\Users\Pinda\.local\bin\claude.exe` (zod schemas `system/init`, `result`, `api_retry`, `permission_denied`,
    `compact_boundary`, the error enum, the terminal-reason enum, the apiKeySource enum, hidden `--max-turns`, and the
    print-mode error strings);
  - `%APPDATA%\npm\node_modules\@openai\codex\bin\codex.js` and `…\codex-win32-x64\vendor\…\codex.exe` (env names,
    WindowsSandboxModeToml, login-restriction and error strings);
  - `%LOCALAPPDATA%\cursor-agent\{agent.cmd,cursor-agent.ps1}` and `versions\2026.10.01-14929f9\{index.js,2571.index.js}`
    (`build-prompt.ts`, the stream-json emitters, the option table, exit codes `SUCCESS:0,SIGINT:130,SIGTERM:143`,
    tool-result cases).
- **Codex source [src]** at tag `rust-v0.162.1`: `codex-rs/exec/src/{exec_events.rs, cli.rs, lib.rs, event_processor.rs,
  event_processor_with_jsonl_output.rs}` — <https://github.com/openai/codex/tree/rust-v0.162.1/codex-rs/exec/src>.
- **Official plugin [src]:** <https://github.com/openai/codex-plugin-cc>
  - `README.md`, `plugins/codex/commands/setup.md`;
  - `scripts/codex-companion.mjs`, `scripts/lib/{app-server.mjs, codex.mjs, process.mjs, job-control.mjs}`.
- **Docs [doc]:**
  - Claude Code: <https://code.claude.com/docs/en/headless>, <https://code.claude.com/docs/en/cli-reference>,
    <https://code.claude.com/docs/en/authentication> (via research/local-cli-skills.md).
  - Codex: <https://developers.openai.com/codex/noninteractive>, which redirects to
    <https://learn.chatgpt.com/docs/non-interactive-mode>.
  - Cursor: <https://cursor.com/docs/cli/reference/output-format>, <https://cursor.com/docs/cli/headless>,
    <https://cursor.com/docs/cli/reference/configuration> (via research/local-cli-skills.md).
