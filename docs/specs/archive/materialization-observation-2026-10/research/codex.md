---
type: Research Note
title: "Codex fact sheet: CLI, app-server, SDK, desktop app and Codex Cloud (read 2026-10-12)"
description: "Primary-source facts for current and legacy Codex Cloud environments, cloud launch surfaces, AGENTS.md, skills, custom agents, hooks and trust, config layers, worktrees, notify/OTel, owner-only prerequisites and billing; re-validates codex_cloud Outcome 3."
tags: [mission-control, research, materialization-observation]
---

# OpenAI Codex fact sheet (CLI, app-server, SDK, desktop app, Codex Cloud)

Retrieved 2026-10-12. Every claim has a source tag; the source list is at the bottom. UNVERIFIED marks a claim
that no official doc or source file confirms. No login, task, or paid call was made.

**Version anchors (2026-10-12):**
- Latest stable release: `rust-v0.162.1`, published 2026-10-09T19:44:51Z. Prereleases go up to `rust-v0.163.0-alpha.5` (2026-10-10).
- `main` HEAD: `c308e127e0e8` (2026-10-12T18:21Z).
- Packages: npm `@openai/codex` 0.162.1; npm `@openai/codex-sdk` 0.162.1 (2026-10-09T19:51Z); PyPI `openai-codex` 0.162.1 (2026-10-09T20:00Z) [G1].
- Docs: `developers.openai.com/codex/*` redirects to `learn.chatgpt.com/docs/*`. Every page has a Markdown twin at `<url>.md` [D0]. The pages carry no dates, so read them as "as of 2026-10-12".

---

## 1. Codex Cloud environments

There are two products, and the user's question mixes their facts:

| Aspect | **Codex Cloud (current)** [D2, D1] | **Codex Cloud (Legacy)** [D3, D4] |
| --- | --- | --- |
| Status | Current web, mobile and desktop experience. Launched at DevDay 2026 (2026-09-29) as "Reusable cloud environments" [D30]. | Kept only for Code Review and the Linear and GitHub integrations. "We plan to deprecate this experience." [D2, D3] |
| Definition | A reusable setup: repositories, dependencies, tools and access settings. Codex inspects the repos, prepares the setup and tests it with you. Each new task gets an isolated workspace from the published environment's prepared filesystem. | A container with the repo checked out at a branch or SHA, then the setup script, then an optional maintenance script. |
| Base image | Not documented. The legacy `#default-universal-image` anchor still exists on the page but its section is gone. UNVERIFIED whether `universal` is still the base. | `universal` (reference: github.com/openai/codex-universal). "Set package versions" pins Python, Node and other runtimes. |
| Setup | **Install script** (install dependencies) and **Start skill** (start services and check readiness). Both are recorded by Codex from the setup conversation; you don't need to write them yourself. | **Setup script**, plus a **maintenance script** that runs when a cached container resumes. Setup runs in a separate Bash session, so `export` doesn't persist into the agent phase. |
| Env vars vs secrets | **Environment variable:** passed directly to programs. **Network secret:** programs get a placeholder, and the proxy substitutes the real value for the allowed domains (HTTPS on port 443 only) "during setup and tasks". **Personal vault** holds per-user values for shared environments. | **Env vars** apply to the whole task. **Secrets** are "only available to setup scripts … removed before the agent phase starts." |
| Agent internet | Toggle "Allow Codex to access internet". Then choose **Package managers** preset, **Custom domains only**, or **All (unrestricted)**, plus "Additional allowed domains". Network secrets add their domains automatically. Agent egress IP feed: `https://openai.com/chatgpt-agents.json`. VPN: Tailscale only (reusable + ephemeral key). OIDC: Enterprise, by request. No HTTP-method restriction is documented for the current product. | Off by default during the agent phase. Setup always has internet. Presets **None**, **Common dependencies**, **All**. Optional **HTTP method limit to GET/HEAD/OPTIONS** [D4]. All traffic goes through an HTTP/HTTPS proxy. |
| Caching / state | A new task starts from the published prepared filesystem. An existing task keeps its own files. Saved VM state is recoverable for up to **7 days** after the last turn or resume. Repository refresh runs in the background. | Container cache for **up to 12 h**. Invalidated by changes to the setup or maintenance script, env vars or secrets; "Reset cache" is also available. Business and Enterprise share the cache across users. |
| VM size | Plus: 2 vCPU / 8 GiB / 8 GiB. Pro, Business, Enterprise and Edu: 4 / 16 / 32. Larger sizes on request for Enterprise. | n/a |
| Create / edit | **UI only:** web or desktop "Work in > Cloud > Create environment", or Settings > Codex Cloud > Environments. Publish and republish are UI actions. No create, edit or publish API or CLI is documented [D1, D5, D6]. | UI at chatgpt.com/codex/settings/environments [D3]. |
| Multiple per repo | Yes. An environment selects "GitHub repositories" (plural), and you can create several environments. Linear and Slack choose among them by context or most-recent use [D1, D13]. Multiple environments for one repo is implied, not explicitly stated. | Has a "repo map". The first repo listed is the default [D13]. |
| Sharing | Enterprise: Privacy > Who can use. RBAC permissions: "Use Codex in the cloud" and "Manage workspace environments". | — |
| Limits | No computer or browser use. No GitLab or GitHub Enterprise Server. | — |

## 2. Programmatic launch, observe and control of cloud tasks

**CLI** [D5]:
- `codex cloud` (alias `cloud-tasks`) is labelled **Experimental**.
- Documented subcommands are `exec --env ENV_ID [--attempts 1-4] [QUERY]` and `list [--env] [--limit 1-20] [--cursor] --json`.
- `list --json` returns `tasks[]{id,url,title,status,updated_at,environment_id,environment_label,summary,is_review,attempt_total}` and `cursor`.
- `codex apply TASK_ID` is **Stable** and runs a local `git apply` of the latest cloud diff.

**Source at main `c308e127e0e8`** [G2]:
- The `Command` enum is `Exec | Status | List | Apply | Diff`. `status`, `diff`, `cloud apply` and `exec --branch` exist in source but are undocumented.
- The `CloudBackend` trait still has only these methods: `list_tasks`, `get_task_summary`, `get_task_diff`, `get_task_messages`, `get_task_text`, `list_sibling_attempts`, `apply_task_preflight`, `apply_task`, `create_task`. There is **no follow-up, cancel, archive or approval method**.
- The last commit touching `codex-rs/cloud-tasks` is `3a16c0b70769` (2026-09-29), and the last touching `cloud-tasks-client` is `3ae4225b1761` (2026-08-28). Nothing changed since the repo's 2026-10-09 revalidation.

**REST API:**
- No public Codex Cloud task or environment API is listed in `learn.chatgpt.com/llms.txt` [D0].
- The CLI calls private `chatgpt.com/backend-api/wham/*` routes (already established in the repo).
- Open feature requests confirm the gap, with no OpenAI response as of 2026-10-12:
  - #24777 "scriptable Codex Cloud environment and task lifecycle" (updated 2026-10-09)
  - #51948 "supported task cancellation" (2026-10-08)
  - #47660 "per-task model … scheduled tasks in a cloud environment" (2026-10-11)
  - [G3]

**SDK:**
- TypeScript `@openai/codex-sdk` "lets your application start, continue, and resume **local** Codex threads". At main it still spawns `codex exec --experimental-json` [D7, G4].
- Python `openai-codex` "controls the **local** Codex app-server over JSON-RPC". It is now a **stable** release with a pinned CLI runtime [D7].
- Neither SDK targets cloud.

**App-server:**
- No cloud-task methods at main [G5].
- New `environment/add|info|status` (experimental) target **self-hosted remote exec-server environments** (`execServerUrl`, `authBearerToken`), not Codex Cloud [D8, G5].
- Desktop handoff "to a Codex cloud environment isn't supported" [D9].
- UNVERIFIED inference: issue #53381 (2026-10-12) shows the desktop app reaching cloud tasks through an app-server host `hostId=durable` over WebSocket. That would mean cloud tasks may internally speak the app-server protocol, but through a private endpoint [G3].

**Integrations (start Codex work from another system):**
- **GitHub:**
  - `@codex review` posts a review. `@codex <anything else>` "starts a **legacy** cloud chat using your pull request as context". `@codex fix …` "can push a fix back to the branch when it has permission" [D10].
  - This can be scripted through the GitHub REST API by posting a PR comment.
  - The only completion signal is the GitHub reaction or review.
- **Linear:**
  - Assign an issue to Codex or mention `@Codex`. This "creates a cloud chat and replies with progress and results". "Follow up in the thread to continue the same chat." Triage rules auto-delegate.
  - It runs against the default branch of the first repo in the environment's repo map. When finished it posts a summary and a link [D11].
  - This can be scripted through the Linear API. It uses the legacy product.
- **Slack/Teams (Enterprise):**
  - `@ChatGPT` delegation picks a **workspace-shared** environment.
  - "Follow along" and "Cancel" controls appear for the requester. Follow-up must come from the same account [D1, D12].
- **Scheduled / event-triggered tasks:** ChatGPT web (Gmail, Slack and GitHub triggers) and desktop (local or worktree). These are **not** Codex Cloud tasks [D14]. Team Tasks run "in the cloud through the team's service account" but don't document Codex Cloud [D15].
- **Workspace Agents trigger API:** `POST https://api.chatgpt.com/v1/workspace_agents/{agent_id}/trigger` with a Workspace Agents-scoped token. Whether such an agent can run Codex Cloud tasks is UNVERIFIED [W2].

**Other controls:**
- **Best-of-N:** `--attempts 1-4` and `attempt_total` [D5].
- **Follow-ups:** available in the UI, Linear, Slack and from dots. Not available from the CLI or any API [D1, G3].
- **Cancel:** Slack button only.
- **Logs and transcripts:** UI only. The client has `get_task_messages`/`get_task_text`, but only the interactive TUI uses them [G2].
- **Notifications and webhooks on completion:** none for Codex Cloud tasks. The `notify` setting is local only (see §6).

**Separate product, the Agents API** [W1, W3]:
- It is the "Codex harness through an OpenAI-managed API" (`POST /v1/agents/sessions`, `OpenAI-Beta: agents=v1`, API key).
- Sessions support follow-up turns, steering, streaming events, and webhooks for "finishes or needs input".
- `openai_hosted` environments are fully programmatic: `setup_commands`, `packages`, `files`, `env`, vault secrets, `network.access = enabled | disabled | restricted` with 1–100 `allowed_domains`, `container_size`, `skills`, `plugins` and `environment_template_id`.
- A sandbox is deleted after 1 h idle. `/workspace/outputs` files are kept as artifacts.
- **Corrected later the same day ([openai-hosted-agents.md](openai-hosted-agents.md)):** cancel *is* documented (`agent.session.input.cancel` → `agent.session.turn.cancelled`). "Closing an event stream does not cancel the task." Deleting a session can return 409.
- It does **not** create or control Codex Cloud tasks or environments.

## 3. Git access in cloud tasks

- **Current product:**
  - Connect GitHub when prompted and select repositories [D1, D2].
  - "Review changes and test results before committing or opening a pull request." Commit and PR are user actions in the UI.
  - Whether the agent can `git push` from inside the VM is UNVERIFIED.
  - "Repository access and personal connections depend on the account running the task" [D1].
  - GitLab and GitHub Enterprise Server are not supported [D1].
  - Multiple repos per environment are supported [D1].
- **Private dependencies:**
  - Network secrets: proxy substitution for allowed HTTPS:443 hosts.
  - Env vars, for raw values.
  - Tailscale VPN, for private registries.
  - OIDC, for cloud resources (Enterprise).
  - The Package-managers preset includes `github.com`, `codeload.github.com` and release and LFS hosts [D1].
- **Legacy:** "Codex creates a container and checks out your repo at the selected branch or commit SHA … You can open a PR" [D3]. GitHub `@codex` can push to the PR branch with permission [D10].
- **Programmatic result:** only the diff is retrievable, via `codex cloud diff` (source-only) or `codex apply`. No PR URL, branch or SHA is exposed [G2, D5].

## 4. Cognition materialization (local vs cloud)

**AGENTS.md** [D16, D17]:
- Global: `$CODEX_HOME/AGENTS.override.md`, otherwise `AGENTS.md` (first non-empty file).
- Project: from the project root (the `.git` marker, configurable through `project_root_markers`) down to the cwd. In each directory Codex reads `AGENTS.override.md`, then `AGENTS.md`, then names in `project_doc_fallback_filenames`, and takes at most one file per directory.
- Files are concatenated root first. Combined size is capped by `project_doc_max_bytes`, 32 KiB by default.
- `codex debug prompt-input` renders the exact model-visible input [D5].
- GitHub review uses `## Code Review Rules` sections [D10].
- Cloud: the legacy agent "uses AGENTS.md" [D3]. The current product reads it from the checked-out repo (repo-established; not separately restated in current docs, so UNVERIFIED wording).

**Skills** [D18, G6]:
- Format: a directory with `SKILL.md` (YAML `name` and `description` required) plus optional `scripts/`, `references/`, `assets/`, and `agents/openai.yaml` for UI metadata, `policy.allow_implicit_invocation` and MCP `dependencies`. Built on agentskills.io.
- Discovery roots:
  - `.agents/skills` in every directory from the cwd up to the repo root (REPO).
  - `$HOME/.agents/skills` (USER).
  - `/etc/codex/skills` (ADMIN).
  - Bundled system skills.
  - Source also loads `<project>/.codex/skills` (Repo scope, project config layer) and **deprecated** `$CODEX_HOME/skills` (User) [G6].
- Disable a skill with `[[skills.config]] path=… enabled=false`.
- Prompt budget: 2% of context or 8,000 chars for the initial list.
- App-server: `skills/list`, `skills/extraRoots/set`, and `{type:"skill"}` input items [D8].
- Cloud: "Skills stored in your repository are available in cloud tasks. Personal skills … aren't synced" [D1]. Issue #51485 reports a desktop-Cloud bug that strips selected skills.

**Custom prompts:** `~/.codex/prompts/*.md` slash commands are **deprecated**; use skills [D19]. They are user-home only, so they never reach cloud.

**Subagents / custom agents** [D20, D21]:
- On by default (`agents.enabled = true`).
- Built-in agents: `default`, `worker`, `explorer`.
- Custom agents are TOML files in `~/.codex/agents/` or `.codex/agents/`. Each needs `name`, `description` and `developer_instructions`, and can set any config key (`model`, `model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `skills.config`).
- `[agents]` keys: `max_concurrent_threads_per_session` (legacy `max_threads`), `default_subagent_model`, `default_subagent_reasoning_effort`, `interrupt_message`, plus `agents.<name>.description` and `agents.<name>.config_file`.
- Subagents inherit the sandbox and runtime overrides. In non-interactive runs, a new approval fails back to the parent.
- App-server exposes `subAgentActivity` and `parentThreadId` filters [D8].
- Cloud: UNVERIFIED (no doc on custom agents in Codex Cloud).

**Hooks** [D22]:
- On by default (`[features] hooks`).
- Events: `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`.
- Sources: `hooks.json` or inline `[hooks]` next to every active config layer (`~/.codex/`, `<repo>/.codex/` when trusted, `/etc/codex`), plugins, and managed `requirements.toml`. All sources load; nothing is replaced.
- Handlers: `command` and `mcp_tool` only. `prompt` and `agent` are parsed but skipped. `async: true` runs a hook in the background.
- **Non-managed hooks need hash-based trust** (through `/hooks`). `codex exec --dangerously-bypass-hook-trust` skips that for one run.
- Timeouts: 600 s default. `SessionEnd` and `Interrupt` default to 1 s, with a 3 s maximum.
- `PreToolUse` returns `permissionDecision allow|deny` plus `updatedInput`. Exit code 2 or `decision:"block"` blocks.
- Hosted tools (WebSearch) are not hooked. "Not a complete enforcement boundary."
- Stdin JSON carries `session_id`, `transcript_path` (unstable format), `cwd`, `hook_event_name`, `model` and `turn_id`.
- App-server: `hook/started` and `hook/completed` (not emitted for async hooks), and `hooks/list` [D8].
- Cloud: only admin-managed `mcp_tool` hooks on the cloud orchestrator, for Work Cloud with local access and dots. Command hooks and local, plugin or repo hooks are "not supported with cloud orchestration". Whether Codex Cloud tasks run repo `.codex/hooks.json` is not stated (UNVERIFIED).

**Config layers** (highest precedence first) [D23]:
1. CLI flags and `-c`
2. Project `.codex/config.toml`, root to cwd, closest wins, **trusted projects only**
3. Profile `~/.codex/<name>.config.toml`, selected with `--profile`
4. `~/.codex/config.toml`
5. Cloud-managed defaults
6. `/etc/codex/config.toml`
7. Built-in defaults

Constraints on layers [D17, D24]:
- **Profiles changed in 0.134.0:** `[profiles.x]` and `profile = …` are no longer read.
- Project config **ignores** `notify`, `otel`, `profile(s)`, `model_provider(s)`, `openai_base_url` and `chatgpt_base_url`, and prints a startup warning when it sees them.
- Trust is set per project with `projects.<path>.trust_level = "trusted"|"untrusted"`.
- Managed `requirements.toml` constrains all of the above.

**Sandbox and approvals** [D24, D25, G7]:
- `sandbox_mode` is `read-only`, `workspace-write` or `danger-full-access`.
- `[sandbox_workspace_write] writable_roots`, `network_access`, `exclude_tmpdir_env_var` and `exclude_slash_tmp`.
- Beta named permission profiles: `default_permissions` and `[permissions.<name>]` with filesystem and network domains, proxied.
- `approval_policy` is `on-request`, `never` or `{granular={sandbox_approval,rules,mcp_elicitations,request_permissions,skill_approval}}`.
- **`untrusted` is "retired"** in the docs, yet the generated schema at 0.162.1 and main still lists `"untrusted"`.
- The app-server docs show camelCase values (`onRequest`, `unlessTrusted`) that don't match the schema's `on-request`. Verify against the pinned schema.
- `approvals_reviewer = "user" | "auto_review"`.
- In workspace-write mode, `.git/` and `.codex/` may stay read-only.

**Rules (execpolicy, experimental)** [D26]:
- `rules/*.rules` (Starlark `prefix_rule(pattern, decision=allow|prompt|forbidden, justification, match, not_match)`) next to every active config layer, including `<repo>/.codex/rules/` when trusted.
- The TUI's "allow" writes `~/.codex/rules/default.rules`.
- `--ignore-rules` skips them. The `codex execpolicy` command is Experimental [D5].

**MCP:**
- `[mcp_servers.<id>]` (stdio `command`/`args`/`env`, or `url` with auth, bearer env var or headers; `required`, `enabled_tools`, per-tool `approval_mode`) [D24].
- App-server `config/mcpServer/reload`.
- Cloud: "Local MCP servers and transports may not be available in the cloud" [D27].

**Network (local):** governed by the sandbox `network_access`, permission-profile domains and the proxy. Codex Cloud uses only its environment's network settings [D25].

## 5. Worktrees and parallelism

- **Desktop app worktrees** [D9b]:
  - Location `$CODEX_HOME/worktrees`, configurable under Settings > Worktrees > Worktree root.
  - Detached HEAD from the selected branch's HEAD; uncommitted changes are applied.
  - The 15 most recent managed worktrees are kept and snapshotted before deletion. Permanent worktrees are a separate project type.
  - **Handoff** moves a chat between Local and Worktree.
  - `.worktreeinclude` (gitignore-style patterns) copies ignored files. An ignored `AGENTS.override.md` is copied automatically.
- **Local environments** (desktop app only) [D28]:
  - Stored in the `.codex` folder at the project root. In practice the file is `.codex/environments/environment.toml`, "AUTOGENERATED": `version=1`, `name`, `[setup] script`, `[[actions]] name/icon/command/platform`. The filename is observed in public repos, not stated in the docs [G8].
  - Setup scripts run when a new worktree is created. Per-OS overrides are supported.
- **Local ↔ cloud:** handoff to a cloud environment is **not supported** [D9]. Local work cannot be pushed into a cloud task except through the source-only `CODEX_STARTING_DIFF` (repo-established).
- **CLI in a git worktree:**
  - Works like any cwd. The project root is the nearest `.git` marker. A worktree's `.git` is a file, and the marker is presence-based (UNVERIFIED for file vs directory).
  - Trust is per path, so each new worktree path needs `projects.<path>.trust_level = "trusted"` (or `-c`) before project `.codex/` config, hooks and rules load [D24].
- **App-server:**
  - Threads take a per-thread and per-turn `cwd`, so one app-server can host thread-per-worktree.
  - `thread/list` filters by `cwd`.
  - Experimental `thread/settings/update`, `project/*` and `thread/queue/*` are available [D8, G5].

## 6. Callbacks and observation

- **`notify`** (user `config.toml` only; ignored in project config):
  - Runs `argv + JSON` for `agent-turn-complete` only.
  - Payload fields: `type`, `thread-id`, `turn-id`, `cwd`, `input-messages`, `last-assistant-message` [D17].
- **Hooks:** see §4. `Stop` and `SessionEnd` are the completion callbacks. Async hooks can call a webhook without blocking.
- **App-server notifications:**
  - Thread and turn: `thread/started`, `thread/status/changed`, `thread/tokenUsage/updated`, `turn/started`, `turn/completed`, `turn/diff/updated`, `turn/plan/updated`.
  - Items: `item/started`, `item/completed`, deltas, `serverRequest/resolved`, `hook/*`.
  - Other: `model/rerouted`, `error`.
  - New since 2026-10-07: `thread/turns/list`, `thread/items/list`, `thread/inject_items`, `thread/settings/updated`, `turn/moderationMetadata`, `thread/environment/connected|disconnected`, `model/safetyBuffering/updated` [D8, G5].
- **`codex exec --json`:** JSONL events `thread.started`, `turn.started`, `turn.completed{usage}`, `turn.failed`, `item.*`, `error`. Use `--output-schema` and `-o` for the final message. `exec resume` continues a run [D29].
- **OpenTelemetry `[otel]`** (user config only):
  - Exporters `otlp-http` or `otlp-grpc` for logs, `trace_exporter`, and `metrics_exporter` (default `statsig`). Settings: `environment`, `log_user_prompt`.
  - Log events: `codex.conversation_starts`, `codex.api_request`, `codex.sse_event`, `codex.websocket_request`/`_event`, `codex.user_prompt` (redacted by default), `codex.tool_decision`, `codex.tool_result`.
  - Metrics: `codex.api_request(.duration_ms)`, `codex.sse_event(.duration_ms)`, `codex.websocket.*`, `codex.tool.call(.duration_ms)`.
  - Tags: `auth_mode`, `originator`, `session_source`, `model`, `app.version` [D17].
- **Cloud egress to an external HTTPS endpoint:**
  - Possible. Enable internet, add the host under Custom domains, and optionally add a network secret for auth headers (HTTPS:443).
  - Source IPs come from `https://openai.com/chatgpt-agents.json`, which is shared across customers [D1].
  - Use DNS hostnames, not IP literals: open bug #53406 (2026-10-12) reports the proxy mis-encoding IPv4 literals in certificate SANs. Open bug #50986 reports proxy:8080 unreachable [G3].
  - Nothing pushes a completion callback from Codex Cloud. An agent prompt could `curl` your endpoint, but that is advisory, not a mechanism.

## 7. Manual-only prerequisites before automation can launch cloud tasks

1. **ChatGPT plan with Codex Cloud:** Plus, Pro, Business, Enterprise or Edu. API-key accounts are "unavailable" [D31]. Enterprise needs an admin to enable Codex Cloud and RBAC [D1].
2. **GitHub connected** to ChatGPT (UI), with repos selected. Not GitLab or GHES [D1, D2].
3. **Create, test and Publish an environment** in the web or desktop UI: install script, start skill, env vars, network secrets, internet allowlist, VPN, OIDC. Any edit requires a UI Republish [D1].
4. **Internet access and secrets** configured in the environment UI. Personal vault values are entered per user [D1].
5. **CLI auth with ChatGPT sign-in:** `codex login` (browser) or `codex login --device-auth`. "Codex cloud requires signing in with ChatGPT" [D32]. For headless runners, seed `auth.json` from a trusted machine and persist the refreshed file; Codex refreshes when `last_refresh` is about 8 days old or on a 401 [D33].
6. **Optional non-human credentials:**
   - Access tokens: Business and Enterprise; `CODEX_ACCESS_TOKEN` or `codex login --with-access-token` [D34].
   - Service accounts: pay-as-you-go plans only [D35].
   - Both are documented for "trusted non-interactive **local** workflows". Their use for cloud tasks is UNVERIFIED.
7. **Record the `ENV_ID`** from the interactive `codex cloud` picker or from `list --json` [D5].

## 8. Billing and auth

- **ChatGPT sign-in:**
  - Subscription allowance for the desktop app, CLI, IDE, SDK and `codex exec`, which are "available" on Plus and Pro [D31].
  - Local messages and cloud chats share the plan allowance, and "cloud tasks may use more" [D31].
  - Credits extend usage.
  - Subscription use for headless local automation is explicitly supported (the `auth.json` CI pattern), though "the right way to authenticate automation is with an API key" [D33].
- **API key** (`codex login --with-api-key`, `CODEX_API_KEY`, `OPENAI_API_KEY`):
  - Billed at standard API rates.
  - **No cloud features** (Codex Cloud, GitHub review, Slack) [D31, D32].
- **Codex Cloud:** ChatGPT sign-in only. Consumes plan allowance. No per-task usage is exposed [D32, G2].
- **Agents API:** API key. Model at API rates plus container rates [W1, W3].

---

## Delta vs repo beliefs

**codex_cloud Outcome 3** (from FEASIBILITY.md 2026-10-08 and REVALIDATION-2026-10-09):
- **Confirmed unchanged on 2026-10-12. Do not flip.**
- No new release since `rust-v0.162.1`.
- `cloud-tasks` code is untouched since 2026-09-29 at main `c308e127e0e8`.
- The docs still list only `exec`/`list` (Experimental) plus `apply` (Stable).
- No public task or environment API exists.
- Public open feature requests (#24777, #51948, #47660) from 2026-10-08 to 2026-10-11 restate the missing follow-up, cancel, environment-lifecycle and per-task-config operations, and none has an OpenAI response.

Deltas to note:
1. **Repo matrix gap: GitHub `@codex` and Linear as public-API-driven launch paths.**
   - Both are documented, and both can be scripted through GitHub's and Linear's own public APIs.
   - Linear supports launch, follow-up (thread reply) and coarse progress (issue Activity plus summary).
   - Both run on **Codex Cloud (Legacy)**, which is slated for deprecation. Neither offers cancel, structured events, idempotency or SHA custody.
   - The repo only evaluated Slack/Teams.
   - This does not meet the revisit trigger (documented follow-up **and** cancel on a non-experimental surface with a server-side credential), but it should be added to the non-qualifying table with that reason.
2. **Agents API** (Codex harness, API key) now documents follow-up, steering, streaming, **webhooks**, and fully programmatic hosted environments (`setup_commands`, network allowlist, templates) [W1, W3].
   - Under the owner rule it stays non-qualifying for `codex_cloud`.
   - It is the only programmatic hosted Codex-harness surface, and a candidate for a separately named hosted profile. Cancel is undocumented.
3. **UNVERIFIED:** the desktop app connects to new Codex Cloud tasks through an app-server "durable" WebSocket host (#53381). If true, the protocol is app-server, but the endpoint is private, so the verdict doesn't change.
4. **Dots** (ChatGPT always-on agents) can create and follow up Codex Cloud tasks, per user reports in #24777 and #52374. These are internal product tools, not an API. Non-qualifying.
5. **Legacy vs current facts:**
   - The user's checklist items (universal image, maintenance script, secrets setup-only, GET/HEAD/OPTIONS limit, 12 h cache) are **legacy-only**.
   - In the current product, network secrets work **during setup and tasks** through proxy substitution, and saved state lasts 7 days.
   - The repo's FEASIBILITY.md already keeps legacy separate. SPEC-02's Codex-hosted row is still accurate.

**coding-lane survey 2026-10-07 (local):**
1. Approval policy `untrusted` is **retired** in the docs. Remove it from the wire-value list, or treat it as schema-only.
2. Profiles are now separate files (`~/.codex/<name>.config.toml`). `[profiles.*]` is ignored since 0.134.0.
3. Project `.codex/config.toml` ignores `notify` and `otel`. Mission Control must set them in the user layer or a profile file, or via `-c`.
4. Non-managed hooks need **hash-based trust**. Headless `codex exec` needs `--dangerously-bypass-hook-trust` or pre-trusted hooks.
5. Hook handler types: `command` and `mcp_tool` only. `prompt` and `agent` are skipped. `async` hooks exist and emit no `hook/*` events.
6. New app-server methods: `thread/turns/list`, `thread/items/list`, `thread/inject_items`, `environment/*` (self-hosted exec-server), `skills/extraRoots/set`, `hooks/list`, `thread/settings/update`.
7. The Python SDK is stable and bundles a pinned CLI. `codex mcp-server` is removed.
8. Versions moved from 0.161.0 to **0.162.1**.

**SPEC-02 skill roots:**
- Add `.codex/skills` (project layer) and deprecated `$CODEX_HOME/skills`. The canonical user root is `~/.agents/skills`.
- Custom agents are `.codex/agents/*.toml`.
- Custom prompts are deprecated.
- Local environments use `.codex/environments/environment.toml`.

## Materialization map

| Artifact | Path / API | Local CLI / app-server honored? | Codex Cloud honored? | Automatable? | Source |
| --- | --- | --- | --- | --- | --- |
| Instructions | `AGENTS.md` / `AGENTS.override.md`, root to cwd; `~/.codex/AGENTS.md`; `project_doc_max_bytes` 32 KiB | Yes | Yes, if committed in the repo (legacy explicit; current UNVERIFIED wording) | Yes (file or commit) | D16, D3 |
| Developer instructions | app-server `thread/start.developerInstructions` / `baseInstructions`; `-c` | Yes | No per-task override | Local yes | D8, G2 |
| Skills | `.agents/skills` (cwd to root), `.codex/skills`, `~/.agents/skills`, `/etc/codex/skills`, deprecated `~/.codex/skills`; `skills/extraRoots/set` | Yes | Repo skills yes; personal skills no | Yes (repo commit) | D18, G6, D1 |
| Custom prompts | `~/.codex/prompts/*.md` (deprecated) | Yes, CLI and IDE | No | Local only | D19 |
| Custom agents | `.codex/agents/*.toml`, `~/.codex/agents/`; `[agents]` | Yes (project only when trusted) | UNVERIFIED | Local yes | D20, D21 |
| Hooks | `<layer>/hooks.json` or `[hooks]`; plugins; `requirements.toml` | Yes, after trust or bypass flag | Command and repo hooks UNVERIFIED for Codex Cloud; not supported under cloud orchestration (Work Cloud) | Local yes (trust gate) | D22 |
| Project config | `.codex/config.toml` (trusted only; ignores notify, otel, profile, provider) | Yes | UNVERIFIED; no per-task overrides on `exec` | Local yes | D23, D24, G2 |
| Profiles | `~/.codex/<name>.config.toml` + `--profile` | Yes | n/a | Local yes | D23 |
| MCP servers | `[mcp_servers.<id>]`; `config/mcpServer/reload` | Yes | Local servers "may not be available" | Local yes | D24, D27 |
| Rules / execpolicy | `<layer>/rules/*.rules` | Yes (experimental) | UNVERIFIED | Local yes | D26 |
| Sandbox / approval / network | `sandbox_mode`, `writable_roots`, `network_access`, `[permissions.*]`, `approval_policy` | Yes | No. The environment network UI applies; approvals are UI only | Local yes; cloud UI only | D24, D25, D1 |
| notify / otel | user `config.toml` only | Yes | No | Local yes | D17 |
| Worktree setup | `.codex/environments/environment.toml` (desktop app) | Desktop app only (not the CLI) | No | File yes, but app-driven | D28, G8 |
| Cloud environment | UI: install script, start skill, env vars, network secrets, allowlist, VPN, OIDC | n/a | Yes (environment-level) | **No** (UI only; no API) | D1, D2 |
| Cloud task launch | `codex cloud exec --env [--attempts]` (Experimental); GitHub `@codex`; Linear | n/a | Yes | Partial (CLI over a private backend; no idempotency) | D5, D10, D11, G2 |
| Cloud follow-up / cancel / events | UI, Slack, Linear only | n/a | n/a | **No** | D1, D12, G2, G3 |
| Cloud artifacts | `codex apply`; source-only `codex cloud diff` | n/a | Diff only | Partial | D5, G2 |
| Hosted alternative | Agents API `/v1/agents/sessions` + `openai_hosted` env | n/a | Not Codex Cloud | Yes (API key) | W1, W3 |

## Sources (all retrieved 2026-10-12)

- D0 https://learn.chatgpt.com/llms.txt
- D1 https://learn.chatgpt.com/docs/environments/cloud-environments (.md)
- D2 https://learn.chatgpt.com/docs/cloud
- D3 https://learn.chatgpt.com/docs/environments/cloud-environment (Legacy)
- D4 https://learn.chatgpt.com/docs/cloud/internet-access (Legacy)
- D5 https://learn.chatgpt.com/docs/developer-commands?surface=cli (rendered page + .md)
- D6 https://learn.chatgpt.com/docs/environments/modes
- D7 https://learn.chatgpt.com/docs/codex-sdk
- D8 https://learn.chatgpt.com/docs/app-server
- D9 https://learn.chatgpt.com/docs/remote-connections ("handoff to a Codex cloud environment isn't supported")
- D9b https://learn.chatgpt.com/docs/environments/git-worktrees
- D10 https://learn.chatgpt.com/docs/third-party/github
- D11 https://learn.chatgpt.com/docs/third-party/linear
- D12 https://learn.chatgpt.com/docs/third-party/slack
- D13 Linear environment and repo-map section (D11)
- D14 https://learn.chatgpt.com/docs/automations
- D15 https://learn.chatgpt.com/docs/enterprise/teams
- D16 https://learn.chatgpt.com/docs/agent-configuration/agents-md
- D17 https://learn.chatgpt.com/docs/config-file/config-advanced
- D18 https://learn.chatgpt.com/docs/build-skills
- D19 https://learn.chatgpt.com/docs/custom-prompts
- D20 https://learn.chatgpt.com/docs/agent-configuration/subagents
- D21 https://learn.chatgpt.com/docs/config-file/config-reference (`agents.*`)
- D22 https://learn.chatgpt.com/docs/hooks
- D23 https://learn.chatgpt.com/docs/config-file/config-basic
- D24 https://learn.chatgpt.com/docs/config-file/config-reference
- D25 https://learn.chatgpt.com/docs/permissions ; https://learn.chatgpt.com/docs/agent-approvals-security
- D26 https://learn.chatgpt.com/docs/agent-configuration/rules
- D27 https://learn.chatgpt.com/docs/extend/mcp
- D28 https://learn.chatgpt.com/docs/environments/local-environment
- D29 https://learn.chatgpt.com/docs/non-interactive-mode
- D30 https://learn.chatgpt.com/docs/whats-new/devday-2026 (dated September 29, 2026)
- D31 https://learn.chatgpt.com/docs/pricing (feature-availability matrix)
- D32 https://learn.chatgpt.com/docs/auth
- D33 https://learn.chatgpt.com/docs/auth/ci-cd-auth
- D34 https://learn.chatgpt.com/docs/enterprise/access-tokens
- D35 https://learn.chatgpt.com/docs/enterprise/service-accounts
- G1 https://api.github.com/repos/openai/codex/releases (rust-v0.162.1, 2026-10-09T19:44:51Z); npm and PyPI registries
- G2 https://github.com/openai/codex/blob/main/codex-rs/cloud-tasks/src/cli.rs and .../cloud-tasks-client/src/api.rs at `c308e127e0e8`; commit history for those paths
- G3 openai/codex issues #24777, #51948, #47660, #51129, #53381, #53406, #50986, #51485, #52374 (states as of 2026-10-12)
- G4 https://github.com/openai/codex/blob/main/sdk/typescript/src/exec.ts (`["exec","--experimental-json"]`)
- G5 https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/common.rs (method list)
- G6 https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/host_roots.rs
- G7 https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server-protocol/schema/typescript/v2/AskForApproval.ts (and main)
- G8 e.g. https://github.com/GetStream/stream-video-swift/blob/HEAD/.codex/environments/environment.toml (third-party observation)
- W1 https://developers.openai.com/api/docs/guides/agents-api/overview
- W2 https://developers.openai.com/workspace-agents/authentication
- W3 https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted
