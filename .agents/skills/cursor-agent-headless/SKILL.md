---
name: cursor-agent-headless
description: Run Cursor agent headlessly for local review or edits; consult for direct Windows node launch, stream JSON, permission configuration, final assistant reports and sealed handoff.
---

Start with `coding-cli-jobs` and its safety reference. Check actual version with doctor; research baseline is 2026.10.01-14929f9. Installation/login/update need separate owner authority. This is the local CLI, separate from Cursor cloud sessions and Mission Control lifecycle.

Windows launch is the resolved `versions/<version>/node.exe index.js`; bypass agent.cmd/PowerShell quoting and length limits. On POSIX resolve agent directly. Use `-p --output-format stream-json --trust` without a prompt argument, then send prompt file bytes on stdin and close it. --trust avoids an unattended trust hang; use only trusted repos. JSON output buffers. Never --printenv.

system/init carries session_id/model. Read the final report from the last assistant message: result concatenates all assistant text. Extract and validate the report schema locally. result usage may provide tokens; absent cost remains null. Known exits are 0, 1 (stderr and possibly no result), 130, 143; verify installed behavior live. --model passes an explicit owner value exactly. Independent effort control is unsupported and refuses before launch. Omitted model retains a disclosed native default.

Subscription preflight requires authenticated `status --format json`. Explicit API mode requires CURSOR_API_KEY; the key is delivered only to the selected Cursor child and redacted from artifacts. Auth credentials are referenced through native home, never copied.

Read-only uses --mode ask --trust without --force. Edit uses --force --sandbox enabled and a generated worktree .cursor/cli.json allow/deny; an existing file refuses pending reviewed merge. Full uses --force --sandbox disabled with isolated worktree/acknowledgement. Exact --force/deny and read-only shell behavior require LS-07 live evidence. Repo skills, instructions, MCP and hooks can affect execution; doctor only validates options/auth, not loaded capabilities.

Resume with --resume <id>, repeating all explicit model/permission flags. No native max-turn/cost bound is assumed; runner wall clock applies. Headless auto-summarization is undocumented. After iteration three, the runner starts a fresh session from the preceding validated handoff; this is a sealed continuation, not a native fork. A recognized context/compaction error starts a fresh session only when a prior validated handoff exists. Uniform Git worktrees preserve diff review. WSL is currently supported only for Codex; this adapter refuses it.
