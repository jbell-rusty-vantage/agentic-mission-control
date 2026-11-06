---
type: Research Note
title: "Local skills for driving Claude Code, Codex and Cursor CLIs headlessly (2026-10-12)"
description: "Existing community and official skills and plugins, per-CLI headless cheat-sheets, subscription-safety, and a recommended router skill plus job runner design."
tags: [mission-control, research, materialization-observation]
---

# Local agent skills for driving Claude Code, Codex and Cursor CLIs headlessly

Research date: 2026-10-12. Scope: skills/scripts that let any coding agent (Claude Code, Codex, Cursor) drive the
*other* coding CLIs non-interactively, **without Mission Control lifecycle**, composed into
`platform/mission-control`.

Evidence levels used below: **[help]** = captured from the locally installed binary's `--help` today;
**[src]** = read from upstream source at a release tag; **[doc]** = official docs page; **[3p]** = community /
third-party (treat as a lead). No billed model calls were made; nothing here was verified by a live run.

Local machine facts (2026-10-12):

| CLI | Installed? | Version | Auth state |
| --- | --- | --- | --- |
| Claude Code | `C:\Users\Pinda\.local\bin\claude.exe` (native Windows) | 2.1.296 | `claude auth status`: `authMethod: claude.ai`, `subscriptionType: max` |
| Cursor CLI | `%LOCALAPPDATA%\cursor-agent\agent.cmd` → PowerShell → `versions\2026.10.01-14929f9\node.exe index.js` | 2026.10.01-14929f9 | `agent status --format json`: authenticated (browser login) |
| Codex CLI | **not on Windows PATH, not in WSL PATH** | latest stable upstream is `rust-v0.162.1` (2026-10-09); repo docs pin `codex-cli 0.162.0` | n/a |

Raw help captures: `research2/claude-help.txt`, `research2/agent-help.txt` (same folder as this file).

---

## Part A — Existing skills, plugins and bridges

### A.1 What the repo already has and how skills are installed

- `skills-lock.json` (version 1) is the **Vercel `npx skills` lock** format: per skill `source` (GitHub
  `owner/repo`), `sourceType`, `skillPath`, `computedHash`. Current sources: `mattpocock/skills`,
  `langchain-ai/langchain-skills`, `langchain-ai/langsmith-skills`, `coleam00/excalidraw-diagram-skill`. Nothing
  about driving coding CLIs is installed.
- `.agents/skills/<name>/` is the **canonical, committed** copy (npx skills' project path for Codex, Cursor and
  "universal" agents). `.claude/skills/<name>` are **machine-local symlinks** into `.agents/skills` and
  `.claude/skills/` is gitignored (`.gitignore` line 223-224). First-party local skills already live here
  (`mission-control-local-setup` with `scripts/` and a gitignored `ledger/`; the retired
  `mission-control-coordinator` with `scripts/`, `schemas/`, `agents/openai.yaml`).
- `skills/<bundle>/` is a **different thing**: Mission Control catalog bundles (`mc.skill_bundle.v1`
  `manifest.json` with sha256 file digests, `version`, `service_contract_range`), enforced by
  `scripts/skills_manifest.py --check` in `make check`, published/pinned via the catalog (SPEC-08, ADR-0033,
  ADR-0024). Anything placed under `skills/` is coupled to MC custody and versioning.
- Implication: CLI-driving skills that must work **without MC lifecycle** belong in `.agents/skills/`
  (committed, symlinked to `.claude/skills` per machine). They can be promoted to `skills/` later by adding a
  `manifest.json` if MC ever wants to pin them.
- `npx skills` agent table ([vercel-labs/skills README](https://github.com/vercel-labs/skills)): Codex and
  Cursor project path = `.agents/skills/`; global = `~/.agents/skills` (Codex) and `~/.cursor/skills` (Cursor).
  Install form: `npx skills add <owner/repo> --skill <name> -a claude-code -a codex -a cursor` (symlink mode
  default; `--copy` available); `npx skills update`. A Cursor forum report says the headless CLI does not see
  plugin-bundled skills, only fixed directories ([forum](https://forum.cursor.com/t/cursor-agent-cli-does-not-register-skills-from-plugins-ide-does-parity-gap/158947)) [3p].

### A.2 Candidates (GitHub metadata fetched 2026-10-12 via `gh api`)

| Candidate | What it covers | License | Stars / last push | Install | Assessment |
| --- | --- | --- | --- | --- | --- |
| [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) | **Official OpenAI** Claude Code plugin: `/codex:review`, `/codex:adversarial-review`, `/codex:rescue` (delegate via `codex:codex-rescue` subagent), `/codex:transfer` (Claude session → Codex thread), `/codex:status\|result\|cancel` background jobs, stop-review-gate hook. Talks to Codex through `codex app-server` via a Node broker (`scripts/codex-companion.mjs`, `app-server-broker.mjs`). Skills: `codex-cli-runtime`, `codex-result-handling`, `gpt-5-4-prompting`. | Apache-2.0 | 34.1k / 2026-07-08 | `/plugin marketplace add openai/codex-plugin-cc` → `/plugin install codex@openai-codex` → `/reload-plugins` → `/codex:setup` | **Adopt** for interactive Claude→Codex review/rescue. Claude-Code-only (plugin, not portable SKILL.md); job state is its own; no goal loop; launch-day command-injection fix reported ([3p](https://codex.danielvaughan.com/2026/03/31/codex-plugin-cc-cross-model-bridge/)). Uses ChatGPT subscription or API key. |
| [skills-directory/skill-codex](https://github.com/skills-directory/skill-codex) | Single `codex` SKILL.md: `codex exec` flags, sandbox table, `resume --last` via stdin, **stdin must be closed** (`</dev/null`) or Codex hangs, effort-based timeouts, "colleague not authority" guidance. | MIT | 1.46k / 2026-09-13 | Claude plugin marketplace or copy SKILL.md | Good, concise reference; hard-codes model menu and asks the user questions on every run (not unattended-friendly). Borrow gotchas. |
| [trailofbits/skills `second-opinion`](https://github.com/trailofbits/skills/tree/main/plugins/second-opinion) | Read-only cross-model review via `codex exec --sandbox read-only --ephemeral --output-schema … -o … - < prompt` (+ Antigravity/Gemini). Clear failure taxonomy. Notes `codex mcp-server` removed in 0.154.0. | **CC-BY-SA-4.0** | 7.5k / 2026-10-09 | Claude plugin | Highest-quality review recipe. Share-alike license: **reference, don't vendor** into the repo. |
| [NousResearch/hermes-agent `skills/autonomous-ai-agents/{claude-code,codex}`](https://github.com/NousResearch/hermes-agent/tree/main/skills/autonomous-ai-agents) | Deep `claude -p` guide (json/stream-json fields, `--json-schema`, `--max-turns`, budgets, auth modes) and Codex delegation; PTY/tmux mode for interactive. | MIT | 253k / 2026-10-12 | Bundled with Hermes; copy SKILL.md | Well-maintained content source (Hermes-specific `terminal()` calls). Good to crib. |
| [daymade/claude-code-skills `local-codex`](https://github.com/daymade/claude-code-skills) | Claude→Codex via `codex exec` on ChatGPT OAuth; explicitly refuses API keys to avoid pay-per-use; `CODEX_BIN` resolution; wrapper returns JSON errors. | MIT | 1.45k / 2026-10-12 | Claude plugin marketplace | Good **subscription-safety** pattern. macOS-centric paths. |
| [steipete/agent-scripts `codex-first`](https://github.com/steipete/agent-scripts) | Routing policy: what to delegate to Codex vs keep in Claude; fresh `codex exec` per work order; parallel `-o` files. | MIT | 7.35k / 2026-10-12 | copy | Useful **router heuristics**; not a runner. |
| [freema/cursor-plugin-cc](https://github.com/freema/cursor-plugin-cc) | Claude Code plugin → `cursor-agent -p --force`; plan→delegate→review; `/cursor:delegate\|from-plan\|resume\|review\|status\|result\|cancel`; zero-dep Node scripts; review schema. | MIT | 35 / 2026-09-18 | `/plugin marketplace add freema/cursor-plugin-cc` → `/plugin install cursor@tomas-cursor` | Only real Cursor bridge found; small project — **review code before adopting**. Claude-only. |
| [felipeinf/cursor-for-claude](https://github.com/felipeinf/cursor-for-claude) | Background Cursor jobs from Claude Code. | MIT | 7 / 2026-05-05 | plugin | Too small/stale. Skip. |
| [kortix-ai/suna `.agents/skills/codex-cli`](https://github.com/kortix-ai/suna) | "Codex is a disposable sub-agent; its self-report is a claim" + `-o` capture, stderr to log. | NOASSERTION | 20k / 2026-10-12 | copy | Good doctrine, unclear license → reference only. |
| [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) docs | Measured headless gotchas: `claude -p --output-format json` and `cursor-agent … json` are fully buffered; `stream-json` streams; `codex exec` blocks on open stdin; Cursor hangs on untrusted fresh workspace; `env -u CLAUDECODE` before launching Codex from Claude. | MIT | 25.5k / 2026-10-12 | n/a | Excellent **gotcha list** ([buffering](https://github.com/everyinc/compound-engineering-plugin/blob/main/docs/solutions/skill-design/cli-output-buffering-for-progress-detection.md), [harness table](https://github.com/everyinc/compound-engineering-plugin/blob/main/docs/solutions/skill-design/size-driven-skill-restructure.md)). |
| [gmickel/flow-next](https://github.com/gmickel/flow-next) | Cross-model review backends incl. `cursor-agent -p --output-format json` with receipts for session continuity. | MIT | 709 / 2026-10-12 | plugin | Pattern reference (receipts). |
| [dsifry/metaswarm `external-tools`](https://github.com/dsifry/metaswarm) | "One job per invocation, minimal permissions, orchestrator verifies independently" for Codex/Gemini. | MIT | 420 / 2026-06-19 | plugin | Principles worth adopting. |
| Orchestrators: [coder/agentapi](https://github.com/coder/agentapi) (MIT, 1.5k), [kbwo/ccmanager](https://github.com/kbwo/ccmanager) (MIT, 1.3k, includes Cursor Agent), [smtg-ai/claude-squad](https://github.com/smtg-ai/claude-squad) (AGPL), [BloopAI/vibe-kanban](https://github.com/BloopAI/vibe-kanban) (Apache, 28k) | TUI/HTTP session managers over PTYs and worktrees. | — | — | — | Out of scope (human-facing, PTY-driven); confirm the worktree-per-agent pattern. |

Protocol bridges (not skills):

- **Codex `mcp-server` is removed** (0.154.0); use `codex app-server` (JSON-RPC v2 over stdio/ws) instead
  ([CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli), [trailofbits note](https://github.com/trailofbits/skills/blob/main/plugins/second-opinion/skills/second-opinion/references/codex-invocation.md)). MC's own codex lane already speaks app-server v2 of 0.162.0 (`docs/knowledge/provider-lanes.md`).
- **Cursor `agent acp`** — "Start ACP server mode (advanced, hidden command)" ([parameters](https://cursor.com/docs/cli/reference/parameters)).
- **Claude via ACP**: [agentclientprotocol/claude-agent-acp](https://github.com/agentclientprotocol/claude-agent-acp) (Apache-2.0, 2.6k). `claude mcp serve` was not re-verified today; [steipete/claude-code-mcp](https://github.com/steipete/claude-code-mcp) is **archived**.
- No **official** Anthropic or Cursor skill for driving the other CLIs was found; `openai/skills` and
  `anthropics/skills` have none either (trees listed 2026-10-12).

---

## Part B — Headless CLI cheat-sheets

### B.1 Claude Code CLI (`claude -p`) — v2.1.296 local

**Install/version.** Native installer / `claude install [stable|latest|x.y.z]`; `claude update`; Windows native
(credentials in `%USERPROFILE%\.claude\.credentials.json`) [doc][help].

**Auth & billing** ([authentication](https://code.claude.com/docs/en/authentication)):

- Precedence: cloud provider env → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY` (**in `-p` it is always used
  when present**) → `apiKeyHelper` → `CLAUDE_CODE_OAUTH_TOKEN` → Anthropic profiles → `/login` subscription OAuth.
- `claude setup-token` mints a **1-year subscription OAuth token** (Pro/Max/Team/Enterprise), printed once, used as
  `CLAUDE_CODE_OAUTH_TOKEN`; model requests only (no Remote Control / claude.ai connectors).
- **`--bare` never reads OAuth or `CLAUDE_CODE_OAUTH_TOKEN`** → API key only → *not subscription-safe*, even though
  docs recommend it for scripts.
- `claude auth status` → JSON with `authMethod` (`none|claude.ai|oauth_token|api_key|api_key_helper|third_party`);
  exit 0 logged-in, 1 not. Use it as a preflight guard.
- Subscription use of `claude -p`: the support article says Agent SDK / `claude -p` / third-party apps can be used
  with subscription limits (June 15, 2026 pause of the announced change) and, as of **Oct 7, 2026, Max and Team
  plans include monthly API credits covering the Agent SDK and `claude -p`** ([support](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)). Pool attribution is not
  spelled out; treat as a moving target and re-check. Background sessions consume quota like interactive ones
  ([agent view](https://code.claude.com/docs/en/agent-view)).

**Invocation & input** ([headless](https://code.claude.com/docs/en/headless)): `claude -p "prompt"`; stdin is read
(piped content becomes context; cap **10 MB**); `--input-format stream-json` for multi-message streaming input;
user-invocable skills work by writing `/skill-name` in the prompt.

**Output.** `--output-format text|json|stream-json` (stream-json needs `--verbose`; `--include-partial-messages`
for token deltas). `json` result fields: `type:"result"`, `subtype` (`success`, `error_max_turns`, budget errors),
`result`, `session_id`, `num_turns`, `total_cost_usd` (client estimate), `duration_ms`, `usage`, `modelUsage`,
`stop_reason`, `terminal_reason`, `permission_denials`, `structured_output` ([hermes 3p](https://github.com/NousResearch/hermes-agent/blob/main/skills/autonomous-ai-agents/claude-code/SKILL.md) + [doc]). `stream-json` events:
`system/init` (model, tools, `mcp_servers`, `plugins`, `plugin_errors`, `mcp_server_errors`, `capabilities`),
`system/api_retry` (`attempt`, `max_retries`, `retry_delay_ms`, `error_status`, `error` category incl.
`rate_limit`, `billing_error`, `authentication_failed`), `permission_denied`, `assistant`/`user` (with
`parent_tool_use_id` for subagents; `--forward-subagent-text`), `stream_event`, hook events
(`--include-hook-events`), final `result`. `json` is fully buffered until the end — use `stream-json` for liveness
([3p](https://github.com/everyinc/compound-engineering-plugin/blob/main/docs/solutions/skill-design/cli-output-buffering-for-progress-detection.md)).

**Structured output.** `--json-schema '<schema>'` (print mode) → `structured_output`; invalid schema exits with an
error; `format` keyword is annotation only [doc].

**Sessions.** `--session-id <uuid>` (pre-assign → deterministic resume), `-r/--resume <id|name|/abs/path.jsonl>`
(searches all projects), `-c/--continue` (with `-p` includes `-p`/SDK sessions), `--fork-session`,
`--no-session-persistence`, `-n/--name` [doc][help].

**Model/effort.** `--model` aliases `default|best|fable|opus|sonnet|haiku|opusplan|sonnet[1m]|opus[1m]` or full IDs;
`--effort low|medium|high|xhigh|max|ultracode`; `--fallback-model a,b` ([model-config](https://code.claude.com/docs/en/model-config)).

**Permissions for unattended runs.** `--permission-mode default(manual)|acceptEdits|plan|auto|dontAsk|bypassPermissions`;
`--permission-prompts none` (v2.1.259+: deny anything that would prompt, remove `AskUserQuestion`);
`--allowedTools "Bash(uv run pytest *)" Read Edit`, `--disallowedTools`, `--tools`; `--dangerously-skip-permissions`;
`--restricted` (no code-running tools, confined file tools, ignores user/project settings);
`--safe-mode` (no customizations, auth still normal). Recommended unattended default:
`--permission-mode auto --permission-prompts none` (classifier) or `acceptEdits` + explicit allowlist [doc].

**cwd / dirs / worktrees.** Runs in process cwd; `--add-dir`; `-w/--worktree [name]` → `<repo>/.claude/worktrees/<name>`
(also `#PR`/PR URL) [doc].

**Background/detached.** `claude --bg "prompt"` (rejected with `-p`) prints a short id; `claude agents --json [--all]`
→ `[{cwd, kind, startedAt, id, state: working|blocked|done|failed|stopped, pid, status: busy|waiting|idle,
waitingFor, sessionId, name}]`; `claude logs|attach|stop|rm|respawn <id>`. No result field in JSON (read logs or
`claude -p --resume <sessionId>`). Dispatched sessions auto-isolate into `.claude/worktrees/`, and **commit and push
before finishing (may open a draft PR)**; idle processes stop after ~1 h; in untrusted dirs `--bg` from a script
fails with `Workspace not trusted` ([agent view](https://code.claude.com/docs/en/agent-view)).

**Limits.** `--max-turns N` (exit error), `--max-budget-usd X` (client-side estimate, includes subagents);
background-work wait after the turn capped by `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` (default 10 min); no wall-clock
timeout flag — enforce externally [doc].

**Compaction.** Auto-compact at model context limit by default (~967K for native-1M models: Fable, Sonnet 5+, Opus
4.7+; 200K for 4.6 models); per-launch `--autocompact <auto|100k–1M>`, env `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
(overrides all), `DISABLE_COMPACT=1`. The recorded system prompt is reused across `--resume` *until compaction*
([cli-reference](https://code.claude.com/docs/en/cli-reference), [model-config](https://code.claude.com/docs/en/model-config)). Compaction is native in `-p`; resume continues the same transcript (incl. compacted
state) — nothing extra needed from the wrapper.

**What loads in `-p`.** Without `--bare`, `-p` loads CLAUDE.md, hooks, skills, plugins, `.mcp.json` of the cwd
**with no trust dialog** — only run in trusted repos; use `--setting-sources`, `--strict-mcp-config --mcp-config`,
`--safe-mode` to control [doc].

**Exit codes.** 0 success; non-zero on failure; failures inside the run are printed *as the result on stdout*;
SIGTERM → 143 (turn left unfinished; send SIGINT first to end the turn cleanly) [doc].

**Windows.** Native; stdin unreadable no longer crashes (≥2.1.211); `--desktop` x64 Windows.

### B.2 OpenAI Codex CLI (`codex exec`) — upstream stable 0.162.1

**Install/version.** `npm i -g @openai/codex` (or release binaries/DotSlash). Repo `docs/install.md` still lists
"Windows 11 via WSL2"; the Windows app/CLI ship a native Windows sandbox (restricted token / elevated vs unelevated)
([3p](https://codex.danielvaughan.com/2026/04/01/codex-cli-windows-native-sandbox-wsl/)). MC already gates its
codex lane to Linux/WSL. **Not installed here** — recommend installing in WSL (`npm i -g @openai/codex` inside WSL)
and optionally on Windows.

**Auth & billing** ([auth](https://learn.chatgpt.com/docs/auth)): `codex login` (ChatGPT → **plan credits/limits**),
`codex login --device-auth`, `--with-api-key` (stdin, **API pricing**), `--with-access-token`; `codex login status`
exits 0 when logged in; `CODEX_API_KEY` can be set for a single `codex exec` ([non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode)).
Storage: `cli_auth_credentials_store = file|keyring|auto|ephemeral`, `auth.json` under `CODEX_HOME` (treat as a
password). `forced_login_method = "chatgpt"` makes Codex refuse API-key auth — use it as a subscription guard.
Headless ChatGPT auth = copy `auth.json`; tokens auto-refresh.

**Invocation & input** [src `codex-rs/exec/src/cli.rs`]: `codex exec [OPTIONS] [PROMPT]`; `-` or no prompt → read
stdin; if stdin is piped *and* a prompt is given, stdin is appended as a `<stdin>` block → **always close stdin**
(`stdin=DEVNULL`) or pass the prompt via `-` (community: open stdin = hang forever). Progress → stderr, final message
→ stdout. Must run inside git unless `--skip-git-repo-check`.

**Output.** `--json` JSONL [src `exec_events.rs`]: `thread.started{thread_id}`, `turn.started`,
`turn.completed{usage{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens,
reasoning_output_tokens}}`, `turn.failed{error{message}}`, `item.started|item.updated|item.completed{item{id, type,
…}}` with `type` ∈ `agent_message{text}`, `reasoning{text}`, `command_execution{command, aggregated_output,
exit_code, status}`, `file_change{changes[{path,kind}], status}`, `mcp_tool_call{server, tool, arguments, result,
error, status}`, `collab_tool_call`, `web_search`, `todo_list{items[{text,completed}]}`, `error`; top-level
`error{message}`. `-o/--output-last-message FILE`; `--output-schema FILE` (final message must match JSON Schema).

**Sessions.** `codex exec resume <SESSION_ID|thread name> [PROMPT|-]` or `resume --last [--all]`;
`codex exec fork <SESSION_ID> [PROMPT]`; `codex exec review --uncommitted|--base <br>|--commit <sha>`;
`--ephemeral` = no rollout files (cannot resume). `thread_id` from `thread.started` is the resume id.

**Model/effort.** `-m <model>`, `-c model_reasoning_effort="high"` (values seen in community skills: `low…xhigh`,
plus `max/ultra` on newer models [3p]); `-p/--profile <name>` layers `$CODEX_HOME/<name>.config.toml`; `--search`;
`-i` images; `--oss`.

**Permissions.** `-s/--sandbox read-only|workspace-write|danger-full-access` (**exec defaults to read-only**);
`-a/--ask-for-approval on-request|never`; `--full-auto` **deprecated** (prints warning; use
`--sandbox workspace-write`); `--approve-for-me` (auto-review approvals, implies workspace-write);
`--dangerously-bypass-approvals-and-sandbox`/`--yolo`; `--dangerously-bypass-hook-trust`; `--ignore-user-config`,
`--ignore-rules`, `--strict-config` [src][doc].

**cwd / dirs / worktrees.** `-C/--cd DIR`, `--add-dir DIR` (writable). `--worktree` exists in 0.162.1 but
**requires `--enable worktrees`** and is rejected with `exec resume`, `exec review`, `--ephemeral`,
`--ignore-user-config` [src `exec/src/lib.rs`] → a resume loop needs a wrapper-managed `git worktree`.

**Background/limits.** No detached mode, no timeout, no max-turns, no budget flag in `exec` → wrapper enforces
wall-clock and iteration caps. `codex cloud` exists for remote tasks.

**Compaction.** Core auto-compaction runs in exec sessions: `model_auto_compact_token_limit` with
`model_auto_compact_token_limit_scope = total|body_after_prefix`, hard-capped by the model's effective context
window percent [src `core/src/session/context_window.rs`]; `/compact` interactive only. Resume continues the rollout
(including compacted history).

**MCP/skills/hooks.** `codex mcp add|get|list|login|logout|remove`; a *required* MCP server failing to start fails
the run; hooks need trust (`--dangerously-bypass-hook-trust`); skills from `.agents/skills` + AGENTS.md.

**Gotchas.** Unset `CLAUDECODE` when launching from Claude Code (peer misreports host) [3p]; don't reuse a saturated
long session for new work orders — fresh `exec` per order [3p steipete].

### B.3 Cursor CLI (`agent`, formerly `cursor-agent`) — 2026.10.01-14929f9 local

**Install.** Windows `irm 'https://cursor.com/install?win32=true' | iex`; macOS/Linux/WSL
`curl https://cursor.com/install -fsS | bash`; `agent update` ([overview](https://cursor.com/docs/cli/overview)). On
Windows `agent.cmd` → `powershell -File cursor-agent.ps1` → newest `versions\<ver>\node.exe index.js` (local
inspection) — a wrapper should call `node.exe index.js` directly to avoid cmd.exe quoting and its 8,191-char limit.

**Auth & billing** ([authentication](https://cursor.com/docs/cli/reference/authentication)): `agent login`
(`NO_OPEN_BROWSER=1` prints URL), `agent logout`, `agent status|whoami --format json`; automation via
`CURSOR_API_KEY` or `--api-key` (user API key from dashboard). Billing follows the key's account plan (included
usage, then on-demand) per Cursor staff forum reply + 3p ([search summary](https://cursor.com/help/models-and-usage/usage-limits)) [3p].

**Invocation** [help][doc headless](https://cursor.com/docs/cli/headless): `agent -p "prompt"`;
`--output-format text|json|stream-json`, `--stream-partial-output` (stream-json only). Prompt as argument; files are
referenced by path/`@path` in the prompt (stdin prompt support is undocumented — use a prompt file reference).

**Output** ([output-format](https://cursor.com/docs/cli/reference/output-format)): `json` = one object on success
`{type:"result", subtype:"success", is_error:false, duration_ms, duration_api_ms, result, session_id, request_id?}`;
**on failure: non-zero exit, stderr, no JSON**. `stream-json` NDJSON: `system/init{apiKeySource, cwd, session_id,
model, permissionMode}`, `user`, `assistant` (with partial flags `timestamp_ms`/`model_call_id`),
`tool_call/started|completed{call_id, tool_call{readToolCall|writeToolCall|function…}}`, `result/success`. **No
usage/token fields, no error event schema.** No `--output-schema`: schema must be prompt-level + wrapper validation.

**Sessions.** `--resume [chatId]`, `--continue`, `agent resume`, `agent ls`, **`agent create-chat`** (returns an ID
→ pre-allocate for deterministic resume) [help]; `session_id` from events is the chat id.

**Model.** `--model <id>` with bracket overrides e.g. `'claude-opus-4-8[context=1m,effort=high,fast=false]'`;
`--list-models` / `agent models` [help].

**Permissions.** `-f/--force` (`--yolo`) "force allow commands unless explicitly denied" — docs say writes in `-p`
are only *proposed* without it, help says `-p` "has access to all tools" (inconsistent; pass `--force` explicitly
for edit jobs, omit + `--mode ask|plan` for read-only); `--auto-review` (server classifier); `--sandbox
enabled|disabled`; `--approve-mcps`; **`--trust` (headless only — without it a fresh workspace can hang)**. Config
`~/.cursor/cli-config.json` (Windows `%USERPROFILE%\.cursor\cli-config.json`), project `.cursor/cli.json`
(permissions only): `permissions.allow|deny: ["Shell(ls)", …]`, `approvalMode: allowlist|auto-review|unrestricted`,
`sandbox.mode|networkAccess|readBoundary` ([configuration](https://cursor.com/docs/cli/reference/configuration)).

**cwd / worktrees.** `--workspace <path>`, `--add-dir`; `-w/--worktree [name]` → `~/.cursor/worktrees/<repo>/<name>`,
`--worktree-base <ref>`, `--skip-worktree-setup` (`.cursor/worktrees.json` setup scripts) [help].

**Background.** `agent persist [prompt]` / `persist list|attach|stop` (survives disconnects); `&`-prefix hands to a
Cloud Agent (interactive); `agent worker` self-hosted cloud worker [help].

**Limits.** No timeout, max-turns or budget flags → wrapper enforces wall clock; sandbox `run` has its own options.

**Context/compaction.** `/summarize` (alias `/compress`) is manual/interactive ([using](https://cursor.com/docs/cli/using));
automatic summarization is documented for the IDE, **not** for `-p` → keep Cursor iterations short and re-seed each
iteration with a handoff file. Loads `.cursor/rules`, `AGENTS.md`, `CLAUDE.md`, `mcp.json`.

**Gotchas.** Untrusted fresh workspace hang; `json` buffered (use stream-json for liveness); reasoning effort is
baked into model name/brackets.

### B.4 Cross-CLI quick map

| Concern | Claude Code | Codex | Cursor |
| --- | --- | --- | --- |
| One-shot | `claude -p` | `codex exec` | `agent -p` |
| Prompt via stdin | yes (≤10 MB) | `-` (and must close stdin otherwise) | use `@prompt.md` reference |
| Event stream | `--output-format stream-json --verbose` | `--json` | `--output-format stream-json` |
| Final text | `.result` | `-o file` / last `agent_message` | `.result` |
| Native schema | `--json-schema` → `structured_output` | `--output-schema FILE` | none (prompt + validate) |
| Session id | `session_id` (or pre-set `--session-id`) | `thread.started.thread_id` | `session_id` (or `agent create-chat`) |
| Resume | `-p --resume <id>` | `exec resume <id> -` | `-p --resume <id>` |
| Fork | `--resume <id> --fork-session` | `exec fork <id>` | — |
| Read-only | `--permission-mode plan` or `dontAsk` + read tools | `-s read-only` | `--mode ask\|plan`, no `--force` |
| Edit, unattended | `--permission-mode acceptEdits\|auto --permission-prompts none` + allowlist | `-s workspace-write -a never` | `--force --sandbox enabled --trust` + `.cursor/cli.json` deny list |
| Full bypass | `--dangerously-skip-permissions` | `--yolo` | `--force --sandbox disabled` |
| Worktree flag | `-w name` | `--worktree` (feature-gated, no resume) | `-w name --worktree-base ref` |
| Turn/budget caps | `--max-turns`, `--max-budget-usd` | none | none |
| Auto-compaction | yes, `--autocompact` | yes, `model_auto_compact_token_limit` | undocumented headless |
| Subscription auth | `/login` or `CLAUDE_CODE_OAUTH_TOKEN`; no `--bare`; unset `ANTHROPIC_API_KEY` | `codex login`; unset `OPENAI_API_KEY`/`CODEX_API_KEY`; `forced_login_method="chatgpt"` | `agent login` or `CURSOR_API_KEY` (same account plan) |
| Usage telemetry | cost + usage | token usage per turn | none |

---

## Part C — Recommendation

### C.1 Adopt vs write

- **Adopt (user-scope plugin, not vendored):** `openai/codex-plugin-cc` for interactive Claude→Codex review and
  rescue. It is official, maintained and subscription-compatible; it does not cover Cursor, goal loops or
  Codex/Cursor as *callers*.
- **Optionally trial:** `freema/cursor-plugin-cc` (MIT) after a code read; it is the only Cursor bridge.
- **Reference, don't vendor:** trailofbits `second-opinion` (CC-BY-SA), kortix `codex-cli` (no clear license).
- **Crib (MIT, attribute in a NOTICE line):** skill-codex stdin/resume gotchas, hermes `claude-code` print-mode
  fields, daymade OAuth-only guard, steipete routing heuristics, EveryInc buffering/trust gotchas.
- **Write first-party** (nothing existing is cross-directional, Windows-aware and job-config driven): one router +
  three per-CLI skills + one Python runner with three adapters.

### C.2 Layout (in `platform/mission-control`)

```text
.agents/skills/
  coding-cli-jobs/                 # router (model-invoked): when to delegate, which CLI, job contract, waiting
    SKILL.md
    references/job-schema.md       # YAML fields + examples
    references/safety.md           # auth guards, permission profiles, secrets
    schemas/job.schema.json
    schemas/result.schema.json     # what the runner returns
    scripts/agentjob.py            # PEP 723 `uv run --script`, stdlib + pyyaml + jsonschema
    scripts/adapters/{claude,codex,cursor}.py
    examples/{review.yaml, fix-tests.yaml, parallel.yaml}
  claude-code-headless/SKILL.md    # cheat-sheet B.1 + when to call adapter directly
  codex-exec/SKILL.md              # cheat-sheet B.2
  cursor-agent-headless/SKILL.md   # cheat-sheet B.3
```

Keep them out of `skills/` (MC bundles, digest-checked, catalog-coupled). `.claude/skills/` gets machine-local
symlinks like the others; Codex and Cursor read `.agents/skills` natively. Run artifacts go to a gitignored
`.tmp/agent-jobs/<job-id>/` (or `.scratch/`). If MC later wants to pin them, add `manifest.json` and move to
`skills/` via `scripts/skills_manifest.py --write`.

### C.3 Job config (YAML/JSON)

```yaml
id: fix-flaky-outbox-test          # also worktree/branch name
cli: codex                         # claude | codex | cursor
goal: |
  Make tests/unit/outbox/test_relay.py::test_retry pass without weakening assertions.
context_files: [docs/knowledge/events-and-commands.md]
repo: C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control
worktree: {mode: git, base: HEAD, keep: on_change}   # git | native | none
host: wsl                          # native | wsl  (Codex default wsl)
model: {name: gpt-5.6-sol, effort: high}   # passed through, never defaulted by the runner
permissions: edit                  # read-only | edit | full  (full requires worktree + explicit ack)
allow_commands: ["uv run pytest *", "uv run ruff *"]
verify:
  - uv run pytest tests/unit/outbox/test_relay.py -q
done_when: verify_pass_and_agent_done   # or schema field, or verify only
output_schema: schemas/result.schema.json
budget: {max_iterations: 4, max_turns_per_iteration: 40, wall_clock_min: 45, max_usd: null}
resume_id: null
artifacts_dir: .tmp/agent-jobs
auth: subscription                 # subscription | api — enforced by preflight
```

### C.4 Runner behaviour (`agentjob.py run job.yaml [more.yaml] --max-parallel N`)

1. **Preflight**: resolve binary (`shutil.which` with PATHEXT; Cursor → `node.exe index.js`; Codex → `wsl -e codex`
   when `host: wsl`); version check; auth guard (`claude auth status` → `authMethod ∈ {claude.ai, oauth_token}`;
   `codex login status` + `-c forced_login_method="chatgpt"`; `agent status --format json`); refuse if
   `auth: subscription` and API-key env vars are present (scrub them from the child env instead of trusting).
2. **Workspace**: `git worktree add .worktrees/<id> -b agentjob/<id> <base>` (uniform across CLIs; needed because
   Codex `--worktree` is feature-gated and incompatible with resume). Native `-w` only for one-shot jobs.
3. **Iteration**: write `prompt.md` (goal, constraints, verify commands, "report done/blocked/handoff in the
   schema"), launch with stdin closed/redirected, stream JSONL to `run.jsonl` (redacted), capture session id from the
   first event, enforce wall-clock (kill process tree: `taskkill /T /F` on Windows, process group on POSIX), write
   `status.json` heartbeat.
4. **Check**: parse final result (native schema for Claude/Codex; extract-and-validate JSON for Cursor); run
   `verify` commands in the worktree (runner-owned — the agent's self-report is a claim, not proof).
5. **Continue**: if not done and budget remains, resume the *same* session with feedback (failing command + tail
   of output, bounded) — native compaction handles long sessions in Claude and Codex. For Cursor, or after a
   context/compaction error, or when iterations > N, start a **fresh session seeded with the previous `handoff`
   field** (sealed continuation, mirroring ADR-0039's "compaction native-first, continuation sealed").
6. **Result**: `result.json` = `{id, cli, status: done|blocked|budget_exhausted|failed, session_id, iterations,
   verify: [{cmd, exit}], worktree, branch, diffstat, usage/cost if available, artifacts}`; never auto-merge or
   push; leave the worktree for review (`keep: on_change`).
7. **Parallel**: `asyncio` semaphore over jobs, one worktree each; quota scales linearly with parallelism.

### C.5 Permission defaults

| Profile | Claude | Codex | Cursor |
| --- | --- | --- | --- |
| read-only (default for review/consult) | `--permission-mode plan` (or `dontAsk`) `--permission-prompts none` | `-s read-only -a never --ephemeral` | `--mode ask --trust` (no `--force`) |
| edit (default for implementation, worktree required) | `--permission-mode acceptEdits --permission-prompts none --allowedTools <allow_commands>` (or `auto`) | `-s workspace-write -a never` | `--force --sandbox enabled --trust` + generated `.cursor/cli.json` allow/deny |
| full (explicit opt-in, disposable worktree/WSL only) | `--dangerously-skip-permissions` | `--yolo` | `--force --sandbox disabled` |

Never pass `--approve-mcps`/`--dangerously-bypass-hook-trust` by default; Claude `-p` already loads repo hooks and
MCP without a trust prompt, so only run jobs in trusted repos, or use `--strict-mcp-config`/`--setting-sources`.

### C.6 Safety

- Child env = allowlist (PATH, HOME/USERPROFILE, SYSTEMROOT, TEMP, CODEX_HOME, CLAUDE_CONFIG_DIR, CURSOR_API_KEY
  when cli=cursor). Scrub `ANTHROPIC_*`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `CLAUDECODE`, DB URLs from `.env`.
- Redact token-shaped strings in `run.jsonl` (`sk-…`, `key_…`, bearer tokens, `CURSOR_API_KEY` value); never log
  env; artifacts dir gitignored; don't copy `auth.json`/`.credentials.json` anywhere.
- No push/merge/PR from the runner; avoid `claude --bg` for jobs (it commits and pushes by design).
- Respect repo AGENTS.md: real tests only, report passed/failed/blocked/unrun separately.

### C.7 How the calling agent should wait

- Launch the runner as a **background process** (Claude Code: Bash `run_in_background: true` → completion
  notification; Codex/Cursor: background shell + poll `status.json`), never stream JSONL into the caller's context.
- On completion read only `result.json` (and the diff), then decide; for long jobs poll `status.json` sparingly.
- Use `claude --bg` + `claude agents --json` only when a human should be able to `claude attach`; it has no result
  field.

### C.8 Subscription-safety summary

- **Claude**: safe with `/login` OAuth or `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`), *without* `--bare` and
  with `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` unset. Terms changed twice in 2026 (June pause; Oct 7 monthly API
  credits for Max/Team covering `claude -p`) — re-check before heavy automation; `--max-budget-usd` is an estimate.
- **Codex**: safe with `codex login` (ChatGPT) and API-key env unset; enforce `forced_login_method="chatgpt"`.
- **Cursor**: `CURSOR_API_KEY` bills the owner's Cursor account (plan, then on-demand if enabled) — that is the
  requested mode; monitor dashboard usage because the CLI emits no usage telemetry.

### C.9 Open items to verify by a live smoke (cheap prompts)

1. Cursor: does `-p` write without `--force`? Does it read the prompt from stdin? Behaviour of `--resume` with
   `--output-format json`; exit code on auth failure.
2. Codex 0.162.x on native Windows vs WSL: sandbox modes under `workspace-write`; exit code on `turn.failed`.
3. Claude: confirm `result.subtype` values for `--max-turns` exhaustion and `--json-schema` failure on 2.1.296.
4. Re-read the Anthropic support article for the pool that `claude -p` draws from after Oct 7, 2026.

## Sources

- Local: `claude --help`, `claude agents --help`, `agent --help`, `agent persist --help`, `agent status --format json`,
  `claude auth status`; repo `skills-lock.json`, `.agents/skills`, `.claude/skills`, `skills/*/manifest.json`,
  `scripts/skills_manifest.py`, `docs/specs/archive/fast-track-2026-10/SPEC-08-agent-skills.md`, `.gitignore`,
  `docs/knowledge/provider-lanes.md`.
- Claude Code: [headless](https://code.claude.com/docs/en/headless), [cli-reference](https://code.claude.com/docs/en/cli-reference),
  [authentication](https://code.claude.com/docs/en/authentication), [agent-view](https://code.claude.com/docs/en/agent-view),
  [model-config](https://code.claude.com/docs/en/model-config), [support: Agent SDK with your plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan).
- Codex: [non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode), [CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli),
  [auth](https://learn.chatgpt.com/docs/auth), source at tag `rust-v0.162.1`: `codex-rs/exec/src/cli.rs`,
  `exec_events.rs`, `lib.rs`, `codex-rs/utils/cli/src/shared_options.rs`, `core/src/session/context_window.rs`;
  [releases](https://github.com/openai/codex/releases).
- Cursor: [headless](https://cursor.com/docs/cli/headless), [output-format](https://cursor.com/docs/cli/reference/output-format),
  [parameters](https://cursor.com/docs/cli/reference/parameters), [authentication](https://cursor.com/docs/cli/reference/authentication),
  [configuration](https://cursor.com/docs/cli/reference/configuration), [using](https://cursor.com/docs/cli/using),
  [overview](https://cursor.com/docs/cli/overview), [usage limits](https://cursor.com/help/models-and-usage/usage-limits).
- Skills/plugins: links in table A.2; [vercel-labs/skills](https://github.com/vercel-labs/skills).
