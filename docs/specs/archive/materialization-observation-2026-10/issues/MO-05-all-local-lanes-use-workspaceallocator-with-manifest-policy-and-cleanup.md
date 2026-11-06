# [MO-05] All local lanes use WorkspaceAllocator with manifest policy and cleanup

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-03-workspaces-and-placement.md](../SPEC-03-workspaces-and-placement.md)

## Problem

Codex and Cursor local ignore the manifest workspace policy; WorkspaceAllocator.cleanup and join_shared have no production callers (gap G10).

## Work

- Route Codex and Cursor local through WorkspaceAllocator.allocate with the manifest policy.
- Invoke cleanup from the operation workflow after Artifact registration and liability settlement; never force-delete unsnapshotted dirty work.
- Make shared_checkout reachable through join_shared.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/codex/harness.py`
- `adapters/cursor/local.py`
- `adapters/temporal/provider_lane_composition.py`
- `application/workspaces/service.py`
- `adapters/temporal/workflows/`

## Acceptance

- [ ] within_run reuse and cleanup verified on all local lanes; snapshots retained; dirty work preserved.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
