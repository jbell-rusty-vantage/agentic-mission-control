# [MO-31] Evidence-based hook event mapping and Cursor binding v2

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-03  
**Specification:** [SPEC-02-cognition.md](../SPEC-02-cognition.md)

## Problem

_CODEX mapping was copied from _CLAUDE; Cursor binding cannot carry hook scripts or plugins (parity gap 15).

## Work

- Rebuild HOOK_EVENT_MAPPING per profile with enforce/observe, cloud support, timeouts, fail-closed form.
- mc.cursor_binding.v2 with hook_script_pins and plugin_expansion_digest.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `domain/capabilities/hooks.py`
- `domain/execution/lanes.py`
- `application/authoring/cursor_launch.py`

## Acceptance

- [ ] Missions 2 and 3 launch on Cursor as authored; validation rejects unsupported enforced events per lane.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
