---
name: claude-code-headless
description: Run Claude Code headlessly for a bounded local task; consult for print-mode flags, JSON frames, OAuth guards, permission profiles and resume behavior.
---

Start with the sibling `coding-cli-jobs` router and its safety reference. Use the reviewed native installation (`claude --version`); installation/update/login are separate owner actions. Research baseline: Claude Code 2.1.296. Doctor checks actual version/help/auth. Direct CLI and Claude Agent SDK share the Claude Code harness, but this skill drives subprocess print mode.

Invoke `claude -p --output-format stream-json --verbose` with prompt file bytes on stdin and close stdin. Argument prompts are possible interactively; this runner always uses stdin to avoid Windows quoting/length limits. `json` buffers until completion. `--json-schema` takes inline JSON. The initial system/init reports session/model; result carries subtype, terminal_reason, structured_output, permission_denials and cumulative total_cost_usd. Unknown usage remains unknown.

The runner preassigns `--session-id <uuid>` and resumes with `--resume <id>`, reapplying model, effort, auth and permissions. Fork is a separate explicit new-session operation, not runner retry. Omitted model retains native selection; explicit `--model`/`--effort` values pass exactly. Native automatic compaction remains enabled. `--max-turns` is hidden and must be reverified on upgrade; `--max-budget-usd` is cumulative across resume. Wall clock is also enforced externally.

Subscription preflight requires `claude auth status` authMethod claude.ai/oauth_token. API keys/auth tokens are scrubbed before probing; OAuth token may pass through the allowlist. `--bare` bypasses OAuth and is unsuitable. API mode requires explicit ANTHROPIC_API_KEY. Subscription billing pool attribution remains LS-07 unrun; OAuth alone does not prove which pool is charged.

Read-only: dontAsk plus Read/Grep/Glob. Edit: acceptEdits plus Edit/Write and authored Bash allow patterns. Full: bypassPermissions, isolated worktree and explicit acknowledgement. Always specify permission mode/prompts. Place a following flag after allowedTools because it consumes arguments. The runner limits settings to project and strict empty MCP; repo hooks/instructions may still execute, so use trusted repos. Skills must be discoverable in the selected CLI installation. Claude discovery symlinks are machine-local and are not created by this skill.

Use direct claude.exe on Windows, not a shell shim. Uniform Git worktrees replace native -w. Never use --bg: its commit/push behavior conflicts with review custody. Error/max-turn/schema exit codes need exact live proof; synthetic result shapes are not acceptance. Review the final report and runner verification independently.
