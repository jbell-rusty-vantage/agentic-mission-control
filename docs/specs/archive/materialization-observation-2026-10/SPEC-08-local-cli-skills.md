---
type: Specification
title: "SPEC-08: Local CLI job skills — teaching any agent to drive Claude Code, Codex and Cursor CLIs headlessly, outside Mission Control"
description: "A router skill plus three per-CLI skills and a uv-runnable job runner that turns a YAML job (goal, worktree, permissions, verify, budget) into a goal-directed loop over claude -p, codex exec and Cursor agent -p, using native compaction, subscription-safe auth guards and background waiting."
tags: [mission-control, specifications, skills, cli, claude-code, codex, cursor]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L in full: remaining LS-07 live-smoke cells and the LS-08 end-to-end clause. The Claude Code lead session is the caller of the end-to-end clause. Cursor LS slice hold released 2026-10-18 (D4). Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-08: Local CLI job skills

Owner decision R6: local skills that let the agent session the owner is talking to (Claude Code, Codex or Cursor) run the *other* CLIs and get work done.

- They have **no Mission Control lifecycle** and **no Mission Control runtime dependency**.
- They use local credentials: `CURSOR_API_KEY`, the Claude subscription and the ChatGPT/Codex subscription.
- They live in this repo and are shareable with others.

Evidence: [research/local-cli-skills.md](research/local-cli-skills.md).

## 1. Adopt, reference, write

| Source | Decision |
| --- | --- |
| [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) (official, Apache-2.0) | **Adopt at user scope** for interactive Claude Code → Codex review and rescue (`/codex:review`, `/codex:rescue`). Document it in the router skill. Not vendored. |
| [freema/cursor-plugin-cc](https://github.com/freema/cursor-plugin-cc) (MIT) | Optional trial after a code read. It is the only Claude → Cursor bridge found. |
| skill-codex, hermes-agent, daymade local-codex, steipete codex-first, EveryInc docs (MIT) | Crib specific gotchas, with attribution in `NOTICE.md` inside the skill folder |
| trailofbits second-opinion (CC-BY-SA) | Reference only (link). Do not copy text, because of share-alike. |
| Nothing found that is cross-directional, Windows-aware and job-config driven | **Write first-party:** one router, three per-CLI skills and one runner |

## 2. Layout

The skills go in `.agents/skills/`, which is tracked. Codex and Cursor read it natively; Claude reads it through the existing machine-local `.claude/skills` symlinks.

```text
.agents/skills/
  coding-cli-jobs/                  # router (model-invoked)
    SKILL.md                        # when to delegate, which CLI, job contract, waiting, safety summary
    NOTICE.md                       # attributions for cribbed MIT material
    references/job-schema.md
    references/safety.md
    references/recipes.md           # review, fix-tests, parallel best-of-N, research-note, migrate
    schemas/job.schema.json
    schemas/result.schema.json
    scripts/agentjob.py             # PEP 723; `uv run --script`; deps: pyyaml, jsonschema
    scripts/adapters/{claude,codex,cursor}.py
    examples/{review.yaml, fix-tests.yaml, parallel.yaml, research.yaml}
  claude-code-headless/SKILL.md     # cheat-sheet: claude -p flags, outputs, sessions, permissions, auth guard
  codex-exec/SKILL.md               # cheat-sheet: codex exec, --json events, resume, sandbox, auth guard
  cursor-agent-headless/SKILL.md    # cheat-sheet: agent -p, stream-json, --force/--trust, Windows launch
```

- Keep them **out of `skills/`**, which holds Mission Control catalog bundles, digest-checked by `make check`, and out of `skills-lock.json`, which records externally installed skills only.
- Run artifacts go to a gitignored `.tmp/agent-jobs/<job-id>/`.
- A later option: if the owner wants these skills materialized into provider sessions by Mission Control, publish them as `skill_bundle` seeds through `scripts/skills_manifest.py --write`. Their content does not change.

## 3. Job contract

`schemas/job.schema.json`:

```yaml
id: fix-flaky-relay-test             # also branch/worktree name
cli: codex                           # claude | codex | cursor
goal: |
  Make tests/unit/outbox/test_relay.py::test_retry pass without weakening assertions.
context_files: [docs/knowledge/events-and-commands.md]
repo: .                              # path; resolved to the git root
worktree: {mode: git, base: HEAD, keep: on_change}   # git | native | none
host: auto                           # auto | native | wsl   (auto: native when the CLI is installed natively; see §10)
model: {name: null, effort: null}    # passed through when set; never defaulted by the runner
permissions: edit                    # read-only | edit | full  (full requires worktree + --i-understand flag)
allow_commands: ["uv run pytest *", "uv run ruff *"]
verify: ["uv run pytest tests/unit/outbox/test_relay.py -q"]
done_when: verify_pass_and_agent_done  # verify_pass | agent_done | schema:<jsonpath>
output_schema: null                  # optional JSON Schema for the agent's final report
budget: {max_iterations: 4, max_turns_per_iteration: 40, wall_clock_min: 45, max_usd: null}
resume_id: null
auth: subscription                   # subscription | api  (cursor: api means CURSOR_API_KEY)
```

`schemas/result.schema.json` (written to `result.json`):

```json
{"id": "...", "cli": "codex", "status": "done|blocked|budget_exhausted|failed|cancelled",
 "session_id": "...", "iterations": 2,
 "verify": [{"cmd": "...", "exit": 0}],
 "worktree": "...", "branch": "agentjob/<id>", "diffstat": "...",
 "report": {"summary": "...", "handoff": "...", "blockers": []},
 "usage": {"cost_usd": null, "tokens": null}, "artifacts": ["run.jsonl", "prompt-1.md"]}
```

## 4. Runner behaviour

Invocation: `uv run --script .agents/skills/coding-cli-jobs/scripts/agentjob.py run job.yaml [job2.yaml …] --max-parallel N`. Subcommands: `run`, `status <id>`, `cancel <id>`, `doctor`.

1. **Preflight (`doctor` runs the same checks).**
   - Resolve the binaries:
     - `claude` through `shutil.which`;
     - `codex` natively, or as `wsl -e codex`;
     - Cursor `agent`: on Windows, call `versions\<ver>\node.exe index.js` directly, avoiding the `agent.cmd` → PowerShell quoting and 8,191-character limits.
   - Record the versions.
   - **Auth guard**, according to the `auth` field:
     - Claude subscription: `claude auth status` must show OAuth or `CLAUDE_CODE_OAUTH_TOKEN`. `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` are scrubbed from the child env, and `--bare` is never used.
     - Codex subscription: `codex login status` must show ChatGPT, and `-c forced_login_method="chatgpt"` is passed. `OPENAI_API_KEY`/`CODEX_API_KEY` are scrubbed.
     - Cursor: `agent status --format json` must be authenticated, or `CURSOR_API_KEY` must be set.
2. **Workspace.**
   - `git worktree add .worktrees/<id> -b agentjob/<id> <base>` is used uniformly. Native `-w` is not used, because Codex `--worktree` is feature-gated and incompatible with resume.
   - Dirty base checkouts are allowed (the worktree is clean).
   - The runner never touches the caller's checkout.
3. **Iteration.**
   - Render `prompt-<n>.md`: goal, context file pointers, constraints, verify commands, and "end with a JSON report {status, summary, handoff, blockers}".
   - Launch with stdin closed and an allowlisted child env (§6).
   - Stream JSONL to the redacted `run.jsonl`.
   - Capture the session id from the first event: Claude `system/init`, Codex `thread.started`, Cursor `system/init`.
   - Write a `status.json` heartbeat every 10 s.
   - Enforce the wall clock by killing the process tree (`taskkill /T /F` on Windows, process group on POSIX).
4. **Check.**
   - Parse the final report: Claude `--json-schema`/`structured_output`; Codex `--output-schema`/`-o`; Cursor extract-and-validate.
   - Run `verify` **in the worktree, in the runner**. The agent's self-report is a claim, not proof.
5. **Continue (goal-directed loop).** If the job is not done and budget remains, **resume the same session** (`claude --resume <id>`, `codex exec resume <id>`, `agent --resume <id>`). The feedback is bounded: the failing command plus the output tail.
   - **Native compaction handles long sessions** for Claude (auto-compact on by default) and Codex (`model_auto_compact_token_limit`). The runner adds no compaction of its own.
   - **Sealed hand-over** (ADR-0039-style, without Mission Control): for Cursor, whose headless auto-summarization is undocumented, after a context or compaction error, or when `iterations > 3`, start a **fresh session** seeded with the previous report's `handoff`.
6. **Result.** Write `result.json`. **Never push, merge or open a PR.** Leave the worktree for review (`keep: on_change`, otherwise removed).
7. **Parallel.** An `asyncio` semaphore runs N jobs, each with its own worktree and its own `.tmp/agent-jobs/<id>/`. Subscription quota scales with N, and the router skill warns about it.

## 5. Permission profiles

| Profile | Claude | Codex | Cursor |
| --- | --- | --- | --- |
| `read-only` (default for review/consult) | `--permission-mode dontAsk --allowedTools "Read,Grep,Glob" --permission-prompts none` (or `plan`) | `--ignore-user-config -s read-only` (+ `--ephemeral` only for single-iteration jobs) | `--mode ask --trust` (no `--force`) |
| `edit` (default for implementation; worktree required) | `--permission-mode acceptEdits --permission-prompts none --allowedTools <allow_commands>` (always followed by another `--flag`) | `--ignore-user-config -s workspace-write` (`exec` already forces approval `never`; `-a` is invalid on `exec`) | `--force --sandbox enabled --trust` plus a generated `.cursor/cli.json` allow/deny in the worktree |
| `full` (explicit opt-in; disposable worktree or WSL only) | `--dangerously-skip-permissions` | `--ignore-user-config --dangerously-bypass-approvals-and-sandbox` (alias `--yolo`) | `--force --sandbox disabled` |

- Never default to `--approve-mcps` or `--dangerously-bypass-hook-trust`.
- Claude `-p` loads repo hooks and MCP without a trust prompt, so run jobs only in trusted repos, or pass `--strict-mcp-config`/`--setting-sources` from the job.

## 6. Safety

- **Child env is an allowlist:** `PATH`, `HOME`/`USERPROFILE`, `SYSTEMROOT`, `TEMP`/`TMP`, `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and `CURSOR_API_KEY` only when `cli: cursor`. Scrub `CLAUDECODE` so Claude can launch Codex, and any `.env` DB URLs.
- **Redaction.** Token-shaped strings (`sk-…`, `key_…`, bearer tokens, the `CURSOR_API_KEY` value) are redacted in `run.jsonl` and `result.json`. Env is never logged. `auth.json` and `.credentials.json` are never copied.
- **Background mode.** Jobs never use `claude --bg`: it commits and pushes by design and has no result field.
- **Repo rules.** Jobs respect repo `AGENTS.md`. The router tells the calling agent to report passed, failed, blocked and unrun separately and to review the diff before using it.

## 7. How the calling agent waits

- **Claude Code:** run the runner with Bash `run_in_background: true`. The completion notification wakes the session, which then reads only `result.json` and `git -C <worktree> diff --stat`. For many jobs, use Monitor over `agentjob.py status --follow`, which prints one line per state change, including failure states.
- **Codex and Cursor callers:** a blocking call, or a background shell with periodic `status`.
- **Never** stream `run.jsonl` into the caller's context.

## 8. Per-CLI skill content (minimum)

Each per-CLI `SKILL.md` covers, from the research cheat-sheets:

- install and version check;
- auth modes and the subscription guard;
- invocation (argument, stdin, file);
- output formats and event schema;
- structured output;
- session id, resume and fork;
- model and effort flags;
- permission profiles;
- worktree flags and their caveats;
- limits: Claude `--max-turns`/`--max-budget-usd`; Codex and Cursor have none, so the runner enforces wall clock;
- compaction behaviour;
- MCP, skills and hooks loading in headless mode;
- exit codes;
- Windows notes;
- known gotchas: close stdin for Codex; `json` output buffers until the end; Cursor hangs in an untrusted folder without `--trust`.

## 9. Verification

- **Offline:**
  - Unit tests for the job schema validation, adapter argv construction for every profile and OS, the env allowlist and redaction, and the result schema.
  - A fake-CLI harness: scripted executables emitting recorded JSONL drive the loop through done, blocked, budget and timeout.
- **Live smoke (owner-authorized, cheap prompts, subscription accounts), to answer the open items:**
  - Cursor: does `-p` write without `--force`? Does it read the prompt from stdin?
  - Codex: exit codes and sandbox on Windows vs WSL.
  - Claude: `result.subtype` on max-turns and schema failure.
  - Which usage pool `claude -p` draws from after 2026-10-07.
- **End-to-end:** a Claude Code session launches two parallel jobs (a Codex fix and a Cursor review) in the background, is woken on completion, and reads both results.


## 10. Adapter corrections from CLI verification (authoritative over §4–§6 where they differ)

Source: [research/cli-adapters.md](research/cli-adapters.md). Everything was validated offline against Claude Code 2.1.296, Codex 0.162.1 and Cursor agent 2026.10.01 on this machine, with no model calls.

### All CLIs

- **Prompt delivery.** Always write the prompt to `prompt-<n>.md` and pipe it on **stdin**, then close stdin. This avoids Windows quoting and the 8,191-character limit, and Codex hangs without EOF.
- **`host: auto`.** Means **native on Windows for all three CLIs** on this machine. WSL `codex` resolves to the Windows npm shim with no Node, Claude is absent in WSL, and the WSL cursor-agent is a year old. WSL becomes available only after MO-08 installs the toolchain.
- **Child env on Windows.** Beyond §6, the allowlist must also keep `APPDATA`, `LOCALAPPDATA`, `SYSTEMROOT`, `COMSPEC`, `PATHEXT`, `WINDIR`, `PROGRAMDATA`, `USERPROFILE`, `TEMP`, `TMP`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE` and `OS` (Node, Bun and Rust need them). Always scrub `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT`, which are set in Claude Code sessions.
- **Process control.** Launch binaries directly:
  - `claude.exe`;
  - the native `codex.exe` from the npm package, not `codex.cmd`;
  - Cursor's pinned `versions\<v>\node.exe index.js`.

  Kill with a Windows Job Object plus `taskkill /T /F`; on POSIX, kill the process group.

### Claude Code

- Always pass `--permission-mode`; otherwise `-p` may start in `auto`.
- Assign the session id up front with `--session-id <uuid>`, so it is known before any output.
- `--json-schema` takes **inline JSON**, not a file path.
- `--allowedTools` consumes the following arguments, so always follow it with another `--flag`.
- `--max-turns` exists but is hidden.
- Cost is a running total across resumes.
- The `result` event carries `subtype` (`success`, `error_max_turns`, `error_during_execution`, …), `terminal_reason`, `structured_output` and `permission_denials`.

### Codex

- **Argument order on resume:** `codex exec <all options> resume <id> -`. Options after `resume` are rejected.
- **Removed or invalid flags:** `--full-auto` is removed (exit 2) and `-a` is invalid on `exec`.
- **User config:** the owner's `~/.codex/config.toml` sets `sandbox_mode = "danger-full-access"` and starts 8 MCP servers. Every launch, including resumes, passes `--ignore-user-config` and explicit `-c` overrides, including `windows.sandbox="elevated"` on Windows, so the user default never applies.
- **Subscription guard is destructive.** With an API key present, `forced_login_method="chatgpt"` prints "…Logging out." and may wipe the ChatGPT login. Scrub `OPENAI_API_KEY`/`CODEX_API_KEY` **before** applying the guard; the runner never passes a key to a subscription job.
- **Session id:** comes from the first event, `thread.started.thread_id`. Token usage is cumulative across resumes.
- **`--ephemeral` sessions cannot be resumed.** Use them only for single-iteration jobs.
- **Auth on this machine:** ChatGPT login is already present on Windows, so `codex login` is not needed there.

### Cursor

- With no prompt argument, Cursor reads the prompt from stdin.
- **Session id:** from `system/init`, or pre-created with `agent create-chat`.
- `result` concatenates all assistant text from the run, so read the final report from the **last `assistant` event**. `result` now includes token usage.
- **Exit codes:** 0, 1 (error on stderr, no result event), 130 and 143.
- **Never pass `--printenv`.** It dumps the full environment into tool events.
- **Auth on this machine:** browser login; `CURSOR_API_KEY` is optional.

### Fixtures

Thirteen synthetic JSONL fixtures (success, max turns, auth failure, bad flag, quota, sandbox denial, mid-stream error, hang) and the `Adapter` contract (`build_argv`, `parse_event`, `final`, with `Job`, `RunnerEvent`, `Usage`, `FinalReport` and a failure enum) are in the research file. Copy them into `.agents/skills/coding-cli-jobs/tests/fixtures/` as the fake-CLI harness inputs.

## Run 2 approved refinements (2026-10-14)

LS-01..06 results/doctor/argv now record CLI/version/host, requested model/effort, observed model or unknown, auth/permission profile and effective configuration sources. Unsupported supplied options refuse before spawn. An omitted model retains the disclosed native default; resume preserves explicit config. Section 10 overrides earlier examples. Skills distinguish direct CLI jobs from Mission Control missions and Agent SDK/Claude Code harness overlap. No mission_control imports or hosted cloud adapters; LS-07/08 live checks remain separately authorized.

[Detailed approved rules and issue mapping](runs/RUN-2-PLANNING-AMENDMENTS.md). These refine remaining acceptance and grant no new execution, spending or deployment authority.
