# LS-07 and LS-08: default-off live handoffs

Disposition: **unrun**. Synthetic tests do not qualify installed CLIs, subscriptions, permissions, WSL or caller wakeup. Obtain action-specific owner authority for the exact prompts/accounts/versions and reconcile unknown spend before `--allow-live`. No install or global auth/config change is included.

LS-07 prerequisites: trusted disposable repository with one tracked file/test; native CLI version/help/auth receipts from doctor; explicit model (or documented native default), auth route and least permission; selected account quota/billing pool evidence; bounded wall clock/iterations; cleanup owner for retained branches/worktrees. Keep raw session receipts private and redact public summaries.

Run the review example first with its repo replaced by the disposable repo. Repeat individually for Claude/Codex/Cursor using the same exact job and capture result identity, binary/version, stdout/stderr exit, permission denials, terminal event, usage/cost or unknown, independently checked workspace state and cleanup. Additional probes require their own reviewed job:

| Probe | Evidence required |
| --- | --- |
| Claude max-turns, max-budget and auth failure | actual result subtype/terminal reason/exit; subscription apiKeySource; schema-error behavior |
| Claude subscription usage pool | account read-back attribution after 2026-10-07; unknown remains unknown without evidence |
| Codex native Windows workspace-write | runner-owned test success under ignore-user-config/elevated sandbox; network and sandbox behavior |
| Codex sandbox child cancellation | bounded child marker process; Job Object/taskkill stops descendants; independent no-process read-back |
| Codex WSL | explicit selected distro/ext4 repo/worktree root/Linux binary/home/PATH and subscription auth; exercise workspace/env/PGID behavior on that exact placement |
| Cursor stdin/read-only | exact received marker prompt; --mode ask without --force shell behavior; no write under review profile |
| Cursor permissions/resume/usage | actual deny vs --force, repeat profile on resume, last-assistant report and token usage presence |
| CLI upgrade hidden options | re-check max-turns/new-session-id/single-turn against actual pinned release before admission |

LS-08 follows satisfied LS-07 and discovery in an actual Claude Code session. Review the two example jobs for a disposable fixture: a Codex fix with runner-owned verify and a Cursor read-only review with different IDs. Authorize the exact two subscription calls and parallel quota. In Claude Bash launch `uv run --script .agents/skills/coding-cli-jobs/scripts/agentjob.py run examples/fix-tests.yaml examples/parallel.yaml --max-parallel 2 --allow-live` with paths resolved to this skill and `run_in_background: true`. Record actual completion wakeup, both result files, requested/observed identity, independent checks, retained diff and cleanup. This document is a procedure, not a transcript or acceptance receipt.
