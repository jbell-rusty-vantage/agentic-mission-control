# [MO-45] External signal sources: GitHub, Cursor v0 webhook, schedules, worker watches

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-40, MO-44  
**Specification:** [SPEC-04-watchers-and-callbacks.md](../SPEC-04-watchers-and-callbacks.md)

## Problem

Watchers need PR/CI, provider status, timers and process/log/file watches.

## Work

- GitHub webhook + poll fallback; Cursor v0 statusChange; Temporal schedules; S6 worker watches with heartbeats.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `interfaces/http/ingress.py`
- `adapters/github/`
- `adapters/temporal/activities/`

## Acceptance

- [ ] Each source produces typed signals consumed by a watcher in tests.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
