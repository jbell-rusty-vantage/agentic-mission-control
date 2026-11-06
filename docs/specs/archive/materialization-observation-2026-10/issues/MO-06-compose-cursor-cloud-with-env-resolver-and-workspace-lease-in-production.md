# [MO-06] Compose cursor_cloud with env resolver and workspace lease in production

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** None  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

cursor_cloud is composed without env_resolver and workspaces, so env_vars_ref is UNSUPPORTED_BEHAVIOR and no provider-workspace lease is recorded.

## Work

- Compose env_resolver (Secret Broker adapter once MO-11 lands; worker env meanwhile) and the WorkspaceAllocator into compose_cursor_cloud.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/temporal/deployment_composition.py`
- `adapters/cursor/cloud.py`

## Acceptance

- [ ] Production-composition test records a provider-workspace lease and resolves env_vars_ref.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
