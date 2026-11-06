---
name: coding-cli-jobs
description: Delegate bounded local coding, review, test repair or research to Claude Code, Codex or Cursor CLI using isolated worktrees, then verify and review the returned result.
---

Use a direct CLI job when a concrete goal fits one repository and the caller can independently verify its outcome. Keep tightly coupled changes in the current session. Give parallel jobs disjoint goals; each consumes account quota. These jobs have no Mission Control lifecycle. The Claude Agent SDK also drives the Claude Code harness, but this runner uses direct CLI subprocesses. OpenAI hosted Agents API and application-run Agents SDK are separate products.

1. Read the repository's AGENTS.md and choose a trusted repository, CLI, explicit auth route and smallest permission profile. Read [safety](references/safety.md) before launching. Consult the corresponding `claude-code-headless`, `codex-exec` or `cursor-agent-headless` skill for provider caveats.
2. Write a job using [the contract](references/job-schema.md). Leave model/effort null to retain the disclosed native default, or supply owner-selected values exactly. The runner refuses unsupported controls before inference. WSL Codex requires explicit distro, Linux repo/ext4 workspace, binary, auth home and PATH; native remains the auto default.
3. Review `doctor job.yaml`. It performs read-only version/help/auth probes with the scrubbed child environment. Check exact binary/version/host, auth and configuration sources. Doctor does not qualify sandbox behavior or prove account billing pools.
4. Establish action-specific authority for inference, then run `uv run --script .agents/skills/coding-cli-jobs/scripts/agentjob.py run job.yaml --allow-live`. `--allow-live` is an execution gate, not authorization by itself. Full permissions additionally require `--i-understand` and a disposable Git worktree.
5. Wait for the runner. In Claude Code use Bash `run_in_background: true`; completion wakes the caller. For several jobs Monitor may follow `status <id> --follow`. Codex/Cursor callers may block or poll status. Read `result.json` and the retained worktree diff; keep raw JSONL out of caller context.
6. Independently review the changes and verification. Report passed, failed, blocked and unrun separately. A provider's done report is a claim. The runner never pushes, merges or opens a PR; review custody remains with the caller.

Use [recipes](references/recipes.md) for review, repair, research and parallel alternatives. [Live handoffs](references/live-handoffs.md) preserve LS-07/08's unrun qualification criteria.

For interactive Claude-to-Codex review/rescue, the official [codex-plugin-cc](https://github.com/openai/codex-plugin-cc) is the preferred user-scope plugin. Adoption/install is a separate owner action; it is not vendored. The optional [Cursor bridge](https://github.com/freema/cursor-plugin-cc) needs a code review before adoption. [Trail of Bits second-opinion](https://github.com/trailofbits/skills/tree/main/plugins/second-opinion) is reference only. Attribution: [NOTICE](NOTICE.md).
