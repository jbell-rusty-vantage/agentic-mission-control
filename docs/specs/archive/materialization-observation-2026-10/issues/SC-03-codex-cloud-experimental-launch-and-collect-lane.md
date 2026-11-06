# [SC-03] codex_cloud experimental launch-and-collect lane

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** E — Qualification drills  
**Size:** M  
**Sprint:** deferred  
**Blocked by:** SC-01, MO-50, MO-20  
**Specification:** [DECISIONS.md](../DECISIONS.md)

## Problem

Owner decision R5: Codex Cloud as an experimental lane after API lanes.

## Work

- codex cloud exec with env and branch; status/list --json poll; diff/apply collection; Start-skill entrypoint; strict max_active_tasks.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/codex_cloud/`

## Acceptance

- [ ] Bounded task completes and is collected; describe declares no cancel or observation.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
