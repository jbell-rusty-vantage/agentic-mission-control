# Job contract and command reference

`schemas/job.schema.json` is the closed input authority; `result.schema.json` validates output. Required: `id` (lowercase slug), `cli` and `goal`. Unknown fields refuse before launch. Defaults are in `load_job`; examples contain the common subset. Invoke from the intended repository root; `repo` is resolved relative to the caller's working directory.

`model.name`/`model.effort` are passed exactly when supplied. Omitted values retain the native CLI default and are recorded as such; `observed_model: null` means unknown. Cursor effort refuses. Non-Claude `max_usd` refuses because these CLIs cannot enforce it. Wall clock bounds every CLI and verification subprocess. Max iterations bounds the runner loop; max turns is provider-enforced only for Claude. Native compaction is retained; Cursor iterations after three start fresh from the previous report's sealed handoff.

`worktree.mode: git` creates `.worktrees/<id>` on `agentjob/<id>` from the requested base without copying dirty caller files. `keep: on_change` removes only clean runner-created worktrees and their branches; dirty worktrees remain for review. Existing IDs, paths and branches refuse. `native` mode refuses. `none` is available only for read-only jobs; verify commands remain caller-authored and can have effects, so prefer Git worktrees even for review.

`host: auto` selects native. Codex `host: wsl` requires a `wsl` object with distro, repo, worktree_root, home, path and binary. Paths are absolute Linux/ext4 paths (no /mnt mounts). The selected distro owns Git worktrees and verification; model stdin crosses wsl.exe directly, Linux env is env -i, and setsid/PGID custody kills descendants. API delivery and other WSL CLIs refuse. Linux paths in results remain Linux paths with host=wsl; raw event paths are preserved. Actual WSL toolchain/auth/kill reach remains unrun.

`output_schema` is optional inline JSON Schema. It must accept the report envelope `{status, summary, handoff, blockers}`; runner completion needs that envelope too. `done_when` supports `verify_pass_and_agent_done`, `verify_pass`, `agent_done`. Verify commands are trusted shell commands, executed by the runner, in the selected workspace with the scrubbed environment. A blocked report stops. Invalid reports and CLI failure stop with failed status. Max iterations/time return budget_exhausted; reason distinguishes timeout.

`done_when: schema:$.criteria.ready` requires an explicit `output_schema`. The selector
supports dot member names and nonnegative array indexes, such as `$.checks[0].passed`;
wildcards, filters, scripts and negative indexes refuse before launch. Completion requires
the selected value to be exactly JSON boolean `true` after schema validation. Missing or
false values continue within the existing resume/budget rules, even when agent status says
done. The schema can declare extra report fields; the required report envelope is still
validated, and validated extra fields are retained in result.json. A blocked report remains
blocked. Verification still runs; this authored completion mode chooses the schema predicate
as its success criterion, like agent_done chooses the agent's report instead of verify_pass.

Commands:

```text
agentjob.py doctor job.yaml
agentjob.py run job.yaml [job2.yaml] --max-parallel 2 --allow-live
agentjob.py status <id> --repo <repo> [--follow]
agentjob.py cancel <id> --repo <repo>
```

Cancellation writes a marker consumed by the running process; it is cooperative with the runner, not a remote provider cancel API. Result/status writes are atomic replacements. Artifacts are `.tmp/agent-jobs/<id>/`; preserve them privately. `run.jsonl`, verification output and results are redacted, and credentials are never copied. Unknown usage/cost remains null; cumulative provider usage is not summed across resumes.
