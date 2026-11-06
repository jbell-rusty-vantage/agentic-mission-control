# Recipes and waiting

Review: use `examples/review.yaml`, read-only permissions and a precise requested finding format. Review the result against the diff yourself.

Repair: use `examples/fix-tests.yaml`, edit permissions, a narrow allow_commands list and an exact failing test in verify. Define which assertions must remain. The runner resumes the same provider session after a verification failure.

Research note: use `examples/research.yaml` with read-only permissions and context pointers. Require source attribution in the summary; independently verify claims before adopting them.

Migration: bound one repository, list preserved contracts in the goal, select edit permissions and contract checks in verify. Leave resulting worktree for review.

Parallel best-of-N: give independent jobs unique IDs and the same base; run multiple job files with `--max-parallel N`. Compare the retained diffs before selecting one; subscription quota multiplies with N. `examples/parallel.yaml` is a second review job, not a separate nested job schema.

Claude caller: launch the runner through Bash with `run_in_background: true`. On completion read only each `result.json` and `git -C <worktree> diff --stat`; completion notification wakes the session. Monitor can watch `status <id> --follow` and receives state changes including failures. Codex/Cursor callers can block or periodically inspect status. A stale running heartbeat after a runner crash requires manual reconciliation of worktree/process custody; do not reuse the ID automatically.
