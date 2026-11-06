---
type: Specification
title: "SPEC-02: Cognition materialization — skills, subagents, hooks, instructions, MCP and plugins per provider"
description: "Cognition Packs projected into each provider's native layout through five delivery modes, additive instruction layering instead of overwrite/refuse, a hook mapping with trust and fail-closed semantics, ambient-cognition inventory and discovery proof levels."
tags: [mission-control, specifications, capabilities, skills, hooks, subagents, materialization]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: the golden-fixture clause (done, MO-01/02), the **Local** fixture-repo clauses on all three local lanes, and the **Codex** hook-deny clause, proven on the S0 cells and fixture F3. Carried forward: the **cursor_cloud drill** clauses (S1). Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-02: Cognition materialization

Gaps closed: G1, G8, G11, G13 and G14 ([gap report](GAP-REPORT.md)).

This spec reuses:

- the catalog, Capability Kinds, pins and bundle custody (ADR-0020/0023/0024);
- the single Host Projection renderer (`render_host_files`);
- the one Hook Event vocabulary (ADR-0026);
- the multi-provider SPEC-02 rules on bundles, MCP and kernel controls.

## 1. Cognition Pack

A **Cognition Pack** is the resolved, pinned set of cognition for one execution unit:

- skill bundles;
- subagent profiles;
- hook scripts (catalog and kernel), plus the Telemetry Hook Pack from [SPEC-04](SPEC-04-watchers-and-callbacks.md);
- an instruction overlay (the mission operating contract and packet pointer);
- MCP servers;
- plugins, after expansion.

It is resolved at compile time and sealed into the binding as a `materialization_digest`, as today. Nothing here creates a new resolution path.

**Cognition Profiles** are catalog-published templates: plugins or workflow templates of kind `plugin`, which already exists. They give the two task families a default pack the manifest can extend.

| Profile | Default contents |
| --- | --- |
| `cognition/sdlc` | tdd, code-review, pr, diagnosing-bugs skills; reviewer and test-runner subagents; kernel and telemetry hooks; repo-native instructions |
| `cognition/knowledge` | research, cite-and-verify, ingest and Knowledge Services skills; source-verifier and summarizer subagents; Knowledge Services MCP (remote); telemetry hooks with `artifact.ready` emission |
| `cognition/mixed` | union, with the subagent set sized to the lane's limits (Cursor inline ≤20) |

## 2. Prerequisite fix: bundle custody (G1, P0)

Pass the bundle custody service into every production rows resolver:

- `bootstrap/manifests.py:213`;
- `adapters/temporal/provider_lane_composition.py:103,163`;
- `adapters/temporal/deployment_composition.py:628,672`.

Workers fetch bundles through signed URLs (ADR-0024).

**Acceptance:** an integration test selects one skill bundle and one hook script for each local lane, launches through the production composition and asserts the files exist with matching digests. Until this lands, every other item in this spec is untestable.

## 3. Native layouts

Mission Control renders each Capability Kind into these paths. "Cloud" means files committed on the mission branch unless a delivery mode says otherwise.

| Kind | cursor_local / cursor_cloud | claude_agent_sdk / claude_cloud | codex / codex_cloud |
| --- | --- | --- | --- |
| Skill bundle | `.agents/skills/<name>/` (Cursor also reads `.cursor/skills`) | `.claude/skills/<name>/` | `.agents/skills/<name>/` |
| Subagent profile | `.cursor/agents/<name>.md`. Frontmatter: `name`, `description`, `model`, `readonly`, `is_background`. Cloud alternative: inline `customSubagents` (≤20; no `readonly`/`is_background`). | `.claude/agents/<name>.md`. Frontmatter: `tools`, `disallowedTools`, `model`, `permissionMode`, `skills`, `mcpServers`, `hooks`, `isolation`, `maxTurns`, `effort`, `memory`, `background`. SDK alternative: `agents=` (no `isolation`/`hooks`). | `.codex/agents/<name>.toml` (`name`, `description`, `developer_instructions`, any config key). Cloud: UNVERIFIED. |
| Hook config | `.cursor/hooks.json` (`version:1`; `failClosed`, `matcher`, `timeout`, `loop_limit`) | `.claude/settings.json` `hooks` (`command`/`http`; `onFailure: "block"`; `async`). SDK: in-process callbacks for kernel hooks. | `.codex/hooks.json` (`command`/`mcp_tool`; trust gate §5) |
| Hook script bodies | `.mission/hooks/` (Mission Control-owned) | same | same |
| Instruction overlay | `.cursor/rules/mc-mission.mdc` (`alwaysApply: true`) | local: SDK `system_prompt` append; cloud: `.claude/rules/mc-mission.md` | local: `thread/start.developerInstructions`; cloud: merged `AGENTS.override.md` (§4) |
| MCP | local: `.cursor/mcp.json`; cloud: **inline `mcpServers` on every create and run**, because cloud ignores the file | `.mcp.json` (cloud: single-repo sessions only, no localhost); SDK `mcp_servers` + `strict_mcp_config` | local: `[mcp_servers]` in project `.codex/config.toml` (trusted) or `-c`; cloud: local servers unavailable |
| Plugin | Expanded into its parts (§7); native `.cursor-plugin` only after separate qualification | Expanded; SDK `plugins=[{type: local}]` locally; **cloud never installs repo plugins** | Expanded |

The renderer stays a pure function. A per-lane **layout table**, a data module beside `host_support.py`, holds these paths, so a provider change is a data change plus a fixture. The lane-neutral helpers that currently live in `adapters/cursor/projection.py` (C14) move to `application/agentic_components/`.

## 4. Instruction layering: additive, never overwrite or refuse (G8)

Today Cursor overwrites `AGENTS.md`, and Claude and Codex refuse a repo that has one. Both are wrong for real repos, this one included. The rule:

**The repo's own instructions always load unchanged. The mission overlay is added through the provider's additive mechanism.**

- **Cursor:** `.cursor/rules/mc-mission.mdc` with `alwaysApply: true`. Never touch `AGENTS.md`. Do not use a `.md` file in `.cursor/rules/`, because Cursor ignores it.
- **Claude:**
  - **Never create `CLAUDE.md`.** Claude Code reads `AGENTS.md` natively only when no `CLAUDE.md` exists, so creating one would silently drop the repo's `AGENTS.md`.
  - Local: SDK `system_prompt={"type":"preset","preset":"claude_code","append": overlay}`.
  - Cloud: `.claude/rules/mc-mission.md` on the mission branch.
- **Codex:**
  - Local: `developerInstructions` on `thread/start`, with no file written.
  - Cloud has no per-task override. Mission Control commits `AGENTS.override.md` at the root, containing the repo root `AGENTS.md` verbatim followed by a delimited mission section. It is capped at 32 KiB; on overflow the mission section shrinks to a pointer at `.mission/operating-contract.md`.
  - `AGENTS.override.md` replaces `AGENTS.md` for that directory, so this merge is mandatory, not optional.

**Structured config files** (`.claude/settings.json`, `.cursor/hooks.json`, `.codex/hooks.json`, `.mcp.json`, `.codex/config.toml`) are **merged structurally**:

- Repo entries are preserved.
- Mission Control entries carry a provenance marker: an `mc-` name prefix, or a `_mc` key where the format allows unknown keys.
- Conflicts resolve by the manifest's `materialization.conflicts: refuse | mission_wins | repo_wins`. The default is `refuse` for permission and hook conflicts, and `repo_wins` for the rest.
- The receipt lists every merged and overridden key.

**Files Mission Control owns outright** live under `.mission/` or carry the `mc-` prefix. A same-named repo skill or agent is a conflict handled by the same policy. Mission Control never deletes repo files.

## 5. Hooks: three origins, one vocabulary

| Origin | Purpose | Where it runs | Reports to Mission Control |
| --- | --- | --- | --- |
| Kernel Hooks (`mc.stop_fence`, `mc.operation_intent`, `mc.frame_capture`, `mc.usage`) | Enforcement and capture | SDK in-process (Claude local, Deep Agents) or command hook → `.mission/hooks/kernel.py` | Yes. Local loopback today; Signal Ingress for remote. |
| Catalog Hook Scripts | Owner and team policies and automations | `.mission/hooks/run.py <pin>` per lane | Optional, through `callback: service` (now populated, SPEC-04) |
| **Telemetry Hook Pack** (new, SPEC-04) | Observation: forwards selected events | Native hook entry → `.mission/hooks/signal` | Always, asynchronously and batched |

Mapping and semantics:

- **Event mapping.** `HOOK_EVENT_MAPPING` is rebuilt from the [fact sheets](research), replacing `_CODEX`, which was copied from `_CLAUDE`. Each entry records the native event, `enforce | observe`, cloud support, timeout default and fail-closed form:
  - Claude: `onFailure: "block"` or exit 2.
  - Cursor: `failClosed: true` or exit 2.
  - Codex: exit 2 or `decision: "block"`.
- **Cloud gaps are declared, not hidden.** Cursor cloud has no `sessionStart`, `sessionEnd` or MCP hooks, and no hooks during its early read-only turns. A manifest requiring `before_mcp_call` enforcement on cursor_cloud fails validation.
- **Codex trust.** Non-managed hooks need hash trust. Mission Control writes trust records for the exact hook digests into the isolated `CODEX_HOME`, or installs kernel hooks as managed (`requirements.toml`) in that home. Which of the two is honoured by app-server is qualification item Q-X2. `--dangerously-bypass-hook-trust` is allowed only for `codex exec` drills, never as the default.
- **Codex `kernel.py` (G11).** The Codex lane writes `.mission/hooks/kernel.py`, `context.json` and the token exactly as cursor_local does, and composes the hook callback service. Until that lands, the release statement's "Codex hooks fail closed: yes" is corrected to "no".
- **Cursor binding** (`mc.cursor_binding.v1` → v2) gains `hook_script_pins` and `plugin_expansion_digest`, so Missions 2 and 3 launch as authored (parity gap 15).
- **Not a security boundary.** Native hooks are interception points only, since hosted tools bypass them. Required write approvals still need the governed gateway (multi-provider SPEC-02, last section).

## 6. Delivery modes and discovery proof (G14)

| Delivery mode | Used for | Proof that it was delivered |
| --- | --- | --- |
| `worktree_write` | Local lanes | Path digests in the worktree |
| `branch_commit` | Cloud lanes (existing `GitBranchPublisher`) | Commit SHA on `mc/{run}` containing the files |
| `inline_launch` | Cursor `customSubagents`/`mcpServers`/`envVars`; Claude SDK `agents`/`hooks`/`system_prompt`; Codex `developerInstructions`/`-c` | Digest of the launch request |
| `provider_registry` | Cursor environments and secrets API | API read-back digest |
| `owner_prerequisite` | UI-only settings ([SPEC-05](SPEC-05-owner-prerequisites.md)) | Owner attestation plus a probe |

**Discovery.** Proof that the provider actually loaded the files is gathered by mechanism, never by asking the model.

| Lane | Mechanism |
| --- | --- |
| claude_agent_sdk | `system/init` (tools, `mcp_servers`, plugins, agents, skills where listed); `InstructionsLoaded` hook; `include_hook_events` |
| codex | app-server `skills/list`, `hooks/list` and `config/read` after `thread/start`; `codex debug prompt-input` in qualification |
| cursor_local | SDK `setting_sources` read-back and hook fire |
| cursor_cloud, claude_cloud | The Telemetry Hook Pack's first signal carries `materialization.observed`: digests of the instruction overlay and hook config as read from disk inside the VM, plus the skill directory listing. A later `skill.invoked` or `subagent.started` signal raises the level to `exercised`. |
| codex_cloud | Only `delivered` is provable. Recorded as such. |

## 7. Plugins: expand for portability

The provider plugin formats are not interchangeable, and Claude cloud ignores repo-declared plugins. For every lane, Mission Control **expands** a catalog plugin into its constituent skills, agents, hooks and MCP servers, then projects those parts natively. Native plugin loading (Claude `plugins=[local]`, Cursor `.cursor-plugin`) is an optional optimisation per lane after a separate qualification. Expansion rejects cycles and name collisions, as today.

## 8. Ambient cognition (G13)

Providers load cognition that Mission Control did not place. Examples:

- Cursor reads `.claude/skills`, `.claude/agents`, `.codex/agents` and, when third-party imports are on (the default), `.claude/settings.json` hooks.
- Claude reads user-level `~/.claude` locally.
- Codex reads `~/.codex` and `~/.agents/skills`.

Rules:

- **Inventory.** At prepare time, Mission Control lists every root the lane loads (project roots, plus home roots for local lanes) and records an **ambient inventory** in the receipt: name, path, digest and origin.
- **Policy.** `materialization.ambient: allow | inventory (default) | refuse_conflicts`. With `refuse_conflicts`, launch fails when an ambient item shares a name with a pack item or adds hooks on enforced events.
- **Local suppression where providers allow it:**
  - Claude SDK `setting_sources=["project"]` (no user settings);
  - Codex isolated `CODEX_HOME` (exists);
  - Cursor SDK `setting_sources`.
- **Cursor's third-party import toggle** is a user setting. It goes on the owner prerequisite list (SPEC-05) when the owner wants strict isolation.

## 9. Acceptance

- One manifest selecting a skill, a subagent, a catalog hook, an MCP server and a plugin renders golden fixtures for all six profiles, with a degradation report per lane. Fixtures are re-recorded from the fact sheets.
- **Local, against a fixture repo with its own `AGENTS.md`, `.claude/skills/x` and `.cursor/hooks.json`:**
  - Launch succeeds on all three local lanes.
  - The repo files are byte-identical afterwards.
  - The mission overlay is present.
  - Discovery reports both the repo and the mission items.
- **Codex:**
  - The kernel `before_tool` hook denies a forbidden command end-to-end on a live CLI drill, with trust handled.
  - The release statement is updated to match the result.
- **cursor_cloud drill:**
  - Inline `mcpServers` reach the agent.
  - `.cursor/rules/mc-mission.mdc` is honoured.
  - A `materialization.observed` signal arrives (needs SPEC-04 ingress).
