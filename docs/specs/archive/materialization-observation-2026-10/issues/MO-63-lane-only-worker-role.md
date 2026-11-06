# [MO-63] Lane-only worker role

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** None  
**Specification:** [SPEC-09-local-harness-path.md](../SPEC-09-local-harness-path.md)

## Problem

Every worker is monolithic: it polls root and family queues and needs family-writer and checkpointer DB logins, which blocks safe workers on other hosts (Daytona).

## Work

- MISSION_CONTROL_WORKER_ROLE=lane serves only MISSION_CONTROL_LANE_TASK_QUEUES with the runtime DB role only.
- Same build id enforcement; readiness reports the role.
- This role is how the WSL2 worker coexists with the AWS base worker (SPEC-11 §3): it serves only mc-s0-<app>-lane-wsl.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `bootstrap/worker.py`
- `adapters/temporal/worker.py`
- `adapters/temporal/deployment_composition.py`
- `bootstrap/settings.py`

## Acceptance

- [ ] A second worker serving only lane queues runs lane.turn without the family-writer DSN and starts no root or family pollers.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
