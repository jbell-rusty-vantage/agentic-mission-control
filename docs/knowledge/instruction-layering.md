---
type: Concept
category: execution
title: Instruction layering and structural config merge
description: How a lane places its Host Projection into a repository that already owns AGENTS.md, CLAUDE.md, skills, hooks and MCP config - the per-lane Instruction Overlay channel, the structural merge with provenance markers, the materialization.conflicts policy, the layering receipt with discovered repository and mission items, and the restore before custody (MO-02, proposed ADR-0044).
tags: [mission-control, capabilities, materialization, lanes, implementation]
aliases: [instruction overlay, structural merge, layering receipt, ambient cognition]
questions:
  - How does a lane merge its projection into a repo's AGENTS.md?
  - Is the repository byte-identical after a local lane run?
  - Does Deep Agents layer instructions into a repository?
  - What ambient cognition does the inventory report?
updated: 2026-11-01
---

# Instruction layering and structural config merge

The [Host Projection](../../GLOSSARY.md) renderer is pure and never sees the repository
([capabilities](capabilities.md)). [Layering](../../GLOSSARY.md) is the step between the render
and the lane placing the files: it reads the repository and merges instead of overwriting or
refusing (SPEC-02 §4, gap G8, proposed
[ADR-0044](../adr/0044-additive-instruction-layering-and-structural-config-merge.md)).

**Instruction Overlay.** No lane writes `AGENTS.md` or `CLAUDE.md`; the repository's own
instructions load unchanged (Claude Code reads `AGENTS.md` only while no `CLAUDE.md` exists).
The mission's operating contract goes through each lane's additive channel
(`LAYERING_LAYOUTS`, the repository-delivered rows of the per-lane layout table in
`domain/capabilities/layouts.py`):

| Lane profile | Channel |
| --- | --- |
| `cursor_local`, `cursor_cloud` | `.cursor/rules/mc-mission.mdc` with `alwaysApply: true` |
| `claude_agent_sdk` | `send_options.system_prompt`: the `claude_code` preset with the overlay as `append` (`ClaudeAgentOptions.system_prompt`, the CLI's `--append-system-prompt`) |
| `claude_cloud` | `.claude/rules/mc-mission.md` |
| `codex` | `send_options.developer_instructions`, sent as `thread/start.developerInstructions` |
| `codex_cloud` | `AGENTS.override.md`: the repository's `AGENTS.md` verbatim, then a delimited mission section; over 32 KiB the section is a pointer at `.mission/operating-contract.md` |

**Structural merge.** `application/agentic_components/layering.py::layer_projection` takes the
projection, a `RepoView` (`DirectoryView` over the worktree on local lanes, `TreeView` over the
base ref's files on `cursor_cloud`) and the binding's `MaterializationPolicy`:

- `.claude/settings.json`, `.codex/hooks.json` (matcher groups), `.cursor/hooks.json`,
  `.mcp.json`, `.cursor/mcp.json` and `.codex/config.toml` are parsed and merged. Repository
  entries are kept as they are; Mission Control's carry a provenance marker: hook entries run a
  script under `.mission/hooks/` and come first in every event array, MCP servers are named
  `mc-<name>` in every provider file, the Codex tables sit in a marked block after the
  repository's own text. Entries an earlier layering left are replaced, so layering its own
  output changes nothing; a merge that adds nothing keeps the repository's exact bytes.
- Files under `.mission/` or named `mc-*` are Mission Control's and placed as projected.
- Anything else, grouped per skill directory or subagent file, is placed when the path is free
  or holds the same bytes; otherwise it is a conflict. Repository files are never deleted.

**Conflicts** resolve by the manifest's `materialization.conflicts` (`refuse | mission_wins |
repo_wins`, on the mission/v2 environment, sealed as `materialization` on
`mc.execution_binding.v2` and `mc.cursor_binding.v2`; [mission manifest](mission-manifest.md)).
Undeclared: `refuse` for permission and hook conflicts, `repo_wins` for the rest. `refuse`
raises `LayeringRefused` before anything is written and the lane refuses `prepare` with
`MATERIALIZATION_CONFLICT`; `repo_wins` skips Mission Control's entry; `mission_wins` places it.

**Receipt and discovery.** `mc.layering_receipt.v1` rides on
`mc.projection_materialization.v1` (`materialize_projection`, used by `cursor_local`,
`claude_agent_sdk` and `codex`; `cursor_cloud` records its digest as `layering_digest`): per
merged file the keys Mission Control added, the repository keys kept, those overridden and those
kept from the repository; each conflict with its category and resolution; skipped paths; and
the instructions, rules, skills, subagents, hook events and MCP servers the lane's native roots
hold from the repository and from the mission. The local lanes record its digest as
`materialization_digest` in the prepared session. The lane's
[Discovery Proof](environment-preparation.md#discovery-proof) compares what the provider reports
loaded with the receipt's mission items (MO-34).

**Restore.** `materialize_projection` keeps the repository bytes of every file it changed in
`.mission/layering.json`; `end_session` on the three local lanes calls
`restore_repository_files` before custody, leaving a file the session itself changed as it is.
The repository is byte-identical after the run and the patch carries no merge.

The ambient inventory is built (MO-33): `application/agentic_components/ambient.py::inventory_ambient` and `ambient_conflicts` record cognition outside the projection without retaining its contents or
following symlinks, and `materialization.py` carries the result (`ambient`, `ambient_home`). Not yet: the persisted lane describes still name `CLAUDE.md`/`AGENTS.md` instruction channels for
`claude_agent_sdk`, `claude_cloud` and `codex_cloud` (a lane-describe migration).

**Deep Agents has no layering.** It places no files in a repository: its instruction channel is the `system_prompt` (`adapters/deep_agents/describe.py:105`) and its Host Projection writer
(`host_files.py`) generates configuration for other hosts only ([Deep Agents lane](deep-agents-lane.md)). Layering applies to the three local lanes, `cursor_local`, `claude_agent_sdk` and `codex` ([cursor lane](cursor-lane.md), [provider lanes](provider-lanes.md)).

Built / specified / goal: layering, restore and ambient inventory built and tested with FIXTURE transports; no live repository run is cited here.

## Citations

- Spec: [SPEC-02 §4 and §9](../specs/archive/materialization-observation-2026-10/SPEC-02-cognition.md), [MO-02](../specs/archive/materialization-observation-2026-10/issues/MO-02-additive-instruction-layering-and-structural-config-merge.md); ADR [0044](../adr/0044-additive-instruction-layering-and-structural-config-merge.md) (proposed).
- Code: [layering policy](../../src/mission_control/domain/agentic_components/layering.py), [per-lane layout table](../../src/mission_control/domain/capabilities/layouts.py), [layering](../../src/mission_control/application/agentic_components/layering.py), [materialization](../../src/mission_control/application/agentic_components/materialization.py), [renderer](../../src/mission_control/application/agentic_components/projections.py), lanes [cursor_local](../../src/mission_control/adapters/cursor/local.py), [cursor_cloud](../../src/mission_control/adapters/cursor/cloud.py), [claude_agent_sdk](../../src/mission_control/adapters/claude/harness.py), [codex](../../src/mission_control/adapters/codex/harness.py).
- Tests: [layering unit tests](../../tests/unit/agentic_components/test_layering.py), [three local lanes over a repository owning its cognition](../../tests/unit/harness/test_layered_local_lanes.py) (FIXTURE transports), [manifest policy to binding](../../tests/unit/authoring/test_manifest_materialization_policy.py), and the [recorded Claude Code discovery fixture](../../tests/fixtures/projections/discovery/claude_agent_sdk.recorded.json): Claude Code 2.1.296, no provider call, discovers the repository's skill beside the mission's, fires both `SessionStart` hooks of the merged settings, and leaves the repository byte-identical.
