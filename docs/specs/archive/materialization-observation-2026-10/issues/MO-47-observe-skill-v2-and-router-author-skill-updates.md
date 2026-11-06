# [MO-47] Observe skill v2 and router/author skill updates

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** S  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-43, MO-44  
**Specification:** [SPEC-04-watchers-and-callbacks.md](../SPEC-04-watchers-and-callbacks.md)

## Problem

Observe skill advertises a broken push and lacks wait recipes.

## Work

- Rewrite around launch-then-wait, supervise-many, inspect-on-wake, declare-watchers; follow writing-for-agents; update manifest digests.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `skills/mission-control-observe/`
- `skills/mission-control/`
- `skills/mission-control-author/`

## Acceptance

- [ ] Recipes executed in a recorded session; make skills-check passes.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
