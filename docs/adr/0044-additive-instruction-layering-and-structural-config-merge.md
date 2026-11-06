---
type: Decision Record
title: "Additive instruction layering and structural config merge: the repository's own instructions load unchanged, the mission overlay goes through each provider's additive channel, and shared config files are merged under a declared conflict policy"
description: "Accepted for the materialization-observation sprint (SPEC-02 section 4, gap G8, MO-02): no lane writes AGENTS.md or CLAUDE.md; Cursor reads an always-apply rule, the Claude SDK appends to the claude_code preset, Codex gets developerInstructions, claude_cloud a .claude/rules file and codex_cloud a merged AGENTS.override.md; .claude/settings.json, .cursor/hooks.json, .codex/hooks.json, .mcp.json, .cursor/mcp.json and .codex/config.toml are merged with provenance markers, conflicts resolve by the manifest's materialization.conflicts, the receipt lists merged keys and discovered repository and mission items, and local lanes restore the repository bytes before custody."
tags: [mission-control, adr, accepted, capabilities, materialization, lanes]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-02-cognition.md (sections 3, 4, 6 and 9); docs/specs/archive/materialization-observation-2026-10/GAP-REPORT.md (G8); docs/specs/archive/materialization-observation-2026-10/research/codebase-materialization.md; research/claude-code.md, codex.md, cursor.md; DECISIONS Proposed ADRs 0044; MO-02; ADR-0023; ADR-0026; ADR-0027
---

# Additive instruction layering and structural config merge

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. 

Mission Control renders one Host Projection per lane profile (ADR-0023). Until now it placed
that projection as if the workspace were empty: Cursor overwrote the repository's `AGENTS.md`,
and the Claude and Codex lanes refused any repository that already had an `AGENTS.md`,
`CLAUDE.md`, `.mcp.json` or settings file. Real repositories, this one included, have all of
them. Creating a `CLAUDE.md` is worse than it looks: Claude Code reads `AGENTS.md` natively only
while no `CLAUDE.md` exists, so the shim silently drops the repository's instructions.

**The repository's own instructions always load unchanged; the mission overlay is added
through the provider's additive mechanism.**

| Lane profile | Instruction Overlay | Delivery |
| --- | --- | --- |
| `cursor_local`, `cursor_cloud` | `.cursor/rules/mc-mission.mdc`, `alwaysApply: true` (a plain `.md` in `.cursor/rules` is ignored) | worktree write / branch commit |
| `claude_agent_sdk` | `system_prompt={"type": "preset", "preset": "claude_code", "append": overlay}` (the CLI's `--append-system-prompt`) | inline launch |
| `claude_cloud` | `.claude/rules/mc-mission.md` | branch commit |
| `codex` | `thread/start.developerInstructions` | inline launch |
| `codex_cloud` | `AGENTS.override.md`: the repository's `AGENTS.md` verbatim, then a delimited mission section; over 32 KiB the section becomes a pointer at `.mission/operating-contract.md` | branch commit |

`AGENTS.override.md` replaces `AGENTS.md` for its directory, so on `codex_cloud` the merge is
mandatory. The table is data (`domain/agentic_components/layering.py::LAYERING_LAYOUTS`, with
each lane's repository instruction files, skill and subagent roots and config files) so the
per-lane layout table (MO-30) absorbs it as rows.

**Layering.** The renderer stays pure and never sees the repository. A separate step,
`application/agentic_components/layering.py::layer_projection`, reads the repository through a
`RepoView` (the worktree on disk for local lanes, the base ref's tree for `cursor_cloud`) right
before the lane places the files, and decides per projected file:

- **Merged files** are parsed and merged structurally: `.claude/settings.json` and
  `.codex/hooks.json` (matcher groups), `.cursor/hooks.json` (handlers), `.mcp.json` and
  `.cursor/mcp.json` (`mcpServers`), `.codex/config.toml` (`[mcp_servers.*]` tables) and
  `AGENTS.override.md`. Repository entries are kept as they are. Mission Control's entries
  carry a **provenance marker**: hook entries run a script under `.mission/hooks/`; MCP servers
  are named `mc-<name>` in every provider file; the Codex tables sit in a marked comment block
  appended after the repository's own text; the instruction section is delimited. Mission
  Control's hook entries come first in every event array (Kernel Hooks first, ADR-0026). A merge
  first drops the entries an earlier layering left, so layering its own output changes nothing,
  and a merge that adds nothing keeps the repository's exact bytes.
- **Owned files** (under `.mission/` or named `mc-*`) are placed as projected.
- **Everything else**, grouped per skill directory or subagent file, is placed when the path is
  free or already holds the same bytes, and otherwise is a conflict. Mission Control never
  deletes a repository file.

We did not inject an `_mc` key into provider entries: whether Claude Code, Cursor and Codex
accept unknown keys in their hook and MCP schemas is unverified, while a name prefix and an
owned script path need no such fact.

**Conflicts** resolve by the manifest's `materialization.conflicts`
(`refuse | mission_wins | repo_wins`), declared on the mission/v2 environment, carried in the
node selections and sealed as an optional `materialization` field on `mc.execution_binding.v2`
and `mc.cursor_binding.v1` (absent from dumps and digests when undeclared, so earlier bindings
keep their bytes). Undeclared, permission and hook conflicts `refuse` and everything else
`repo_wins`; a declared value applies to every category. `refuse` raises before anything is
written and the lane refuses `prepare` with `MATERIALIZATION_CONFLICT`; `repo_wins` keeps the
repository's entry and skips Mission Control's; `mission_wins` places Mission Control's.

**Receipt and discovery.** `mc.layering_receipt.v1` (on `mc.projection_materialization.v1`)
lists, per merged file, the keys Mission Control added, the repository keys preserved, those
overridden and those kept; every conflict with its category and resolution; the skipped paths;
and what the lane's native roots hold afterwards from the repository and from the mission
(instructions and rules, skills, subagents, hook events, MCP servers). Its digest is recorded in
the prepared session's projection digests on every lane. Provider-side discovery proof by
mechanism is MO-34; the recorded local Claude Code discovery fixture already shows the
repository's skill and the mission's discovered side by side and both `SessionStart` hooks of
the merged settings firing.

**Restore.** Local lanes keep the repository bytes of every file layering changed in a record
under `.mission/` and put them back at `end_session`, before custody, unless the session itself
changed the file since. The run leaves repository files byte-identical and the patch artifact
free of Mission Control's merges. `cursor_cloud` commits the merged files on the mission branch
and excludes them from its patch as before.

We rejected writing the overlay into `AGENTS.md`/`CLAUDE.md` with markers (it rewrites
repository files and, for `CLAUDE.md`, hides the repository's `AGENTS.md`), refusing repositories
that own these files (most real repositories), and Claude's `.claude/settings.local.json` for the
mission's hooks (the lane loads only the `project` setting source).

## Consequences

- MCP server names in provider files gain the `mc-` prefix, so tool names read
  `mcp__mc-<name>__<tool>`; Deep Agents connections keep their names.
- The Cursor binding's `agents_digest` no longer covers an `AGENTS.md`; bindings sealed before
  this change re-seal on their next launch (their pinned digests no longer match the render).
- The `claude_agent_sdk` lane now runs on the `claude_code` system prompt preset instead of the
  SDK's empty system prompt.
- The persisted lane describes still list `CLAUDE.md` and `AGENTS.md` among the instruction
  channels of `claude_agent_sdk`, `claude_cloud` and `codex_cloud`; correcting them needs a
  lane-describe migration, which the integrator allocates.
- Ambient cognition the providers load from outside the projection (user homes, other
  providers' directories) is inventoried by MO-33, not here.
