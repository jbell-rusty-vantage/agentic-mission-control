# [MO-21] missionctl preflight and PREREQUISITES_UNMET launch refusal

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-20  
**Specification:** [SPEC-05-owner-prerequisites.md](../SPEC-05-owner-prerequisites.md)

## Problem

Launch fails late or silently degrades when human setup is missing.

## Work

- Preflight CLI, HTTP endpoint and MCP tool listing unmet/stale prerequisites, degradations and reachable readiness per lane.
- Launch API refuses with typed PREREQUISITES_UNMET carrying the same list.
- Router skill rule: relay steps to the human, never work around.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `interfaces/cli/main.py`
- `interfaces/http/`
- `interfaces/mcp/`
- `skills/mission-control/SKILL.md`

## Acceptance

- [ ] Fresh installation plus a claude_managed manifest yields the full list and non-zero exit.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
