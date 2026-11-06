# One skill tree, three harnesses

Skills are written once under `.agents/skills/<name>/` (the open Agent Skills layout: `SKILL.md`
with `name` and `description`, optional sibling files, `agents/openai.yaml` for Codex metadata).
Each harness reaches the same files, so a session in Claude Code, Cursor or Codex starts from the
same state.

| Harness | How it finds the skills | Repository instructions | Linear | Notes |
| --- | --- | --- | --- | --- |
| **Codex** | Scans `.agents/skills` in every directory from the working directory up to the repository root; `agents/openai.yaml` supplies the display name and the implicit-invocation policy | `AGENTS.md` (root and the closest subsystem file) | `[mcp_servers.linear]` in the user's `~/.codex/config.toml` | Launch Codex inside `platform/mission-control` so the repo-scoped skills resolve |
| **Cursor** | Reads `.agents/skills/` and `.cursor/skills/` recursively at project and user level | `AGENTS.md`, plus `.cursor/rules/*.mdc` as pointers only (never restated content) | the `linear` entry in the user-level `~/.cursor/mcp.json` | `project-organization.mdc` is always on; `documentation-surfaces.mdc` points here |
| **Claude Code** | `.claude/skills/<name>` symlinks onto `.agents/skills/<name>` (machine-local, git-ignored) | `AGENTS.md` | the `linear` server in `.mcp.json` | Create missing links with `python scripts/dev/link_claude_skills.py` (`--check` only reports) |

Verify the wiring after adding a skill:

```text
python scripts/dev/link_claude_skills.py --check     # every .agents/skills/<name> has its .claude/skills link
python scripts/dev/check_matt_pocock_skills.py       # upstream set byte-identical (network)
```

## Hooks and automation

`python docs/tools/check_docs.py` verifies every documentation surface offline and exits 1 on a
failure; `--hook` exits 2 and prints the failures to stderr, which is the shape a session-stop hook
needs to make the agent fix them before it stops. Wire a hook only once the baseline is green, or
scope it with `--only <names>` (names from `--list`).

**Claude Code** (`.claude/settings.local.json`, or the user settings): a `Stop` hook runs when the
agent finishes a turn; exit 2 blocks the stop and feeds stderr back to the agent.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python docs/tools/check_docs.py --hook --only ledgers,index,okf" }
        ]
      }
    ]
  }
}
```

**Git** (`.pre-commit-config.yaml`, a `local` hook, runs under `prek`): fails the commit when a
touched document breaks a surface. Keep it scoped to the fast checks.

```yaml
  - repo: local
    hooks:
      - id: docs-check
        name: documentation surfaces (ledgers, index, OKF)
        entry: python docs/tools/check_docs.py --only ledgers,index,okf
        language: system
        files: ^(docs/|AGENTS\.md$|.*/AGENTS\.md$|\.agents/skills/|skills/)
        pass_filenames: false
```

**Cursor and Codex** both have lifecycle hooks with a stop or turn-end event; the same command
works there. Use each product's hooks reference for the exact file and event names rather than
guessing them.

**Scheduled runs.** The full check (`check_docs.py --upstream`) and the provider-research digest
(the running proposal's tier 0 detectors) are time-based: a local scheduler first (Task Scheduler
on this Windows host, cron on WSL2), weekly to start, on demand per lane and at the start of a
provider sprint. Digests land under `.scratch/`, never in git; only the resulting sheet and
register rows are committed.
