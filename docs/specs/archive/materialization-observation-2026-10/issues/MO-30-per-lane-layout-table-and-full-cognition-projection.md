# [MO-30] Per-lane layout table and full cognition projection

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-01, MO-02  
**Specification:** [SPEC-02-cognition.md](../SPEC-02-cognition.md)

## Problem

Native layouts are hard-coded and partially wrong per provider; API lanes need non-file projection.

## Work

- Data-driven layout table per profile (paths, frontmatter fields, limits).
- Full subagent field mapping per provider with degradation reports; skills placement; Cursor cloud inline customSubagents/mcpServers re-sent every run.
- API projection targets for claude_managed (agent/skills/MCP) and codex_agents (saved agent/skills/tools).
- Move C14 lane-neutral helpers out of adapters/cursor.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `domain/capabilities/layouts.py`
- `application/agentic_components/projections.py`
- `adapters/cursor/projection.py`
- `tests/fixtures/projections/`

## Acceptance

- [ ] Golden fixtures for all nine profiles re-recorded from the fact sheets with degradation reports.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
