# [MO-67] Temporal Cloud qualification run

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** MO-72, MO-78  
**Specification:** [SPEC-09-local-harness-path.md](../SPEC-09-local-harness-path.md)

## Problem

Temporal Cloud is only unit-tested with a mocked connection.

## Work

- Run the S0 probe set on mission-control-dev.ih0e7 using the setup and versioning rule from MO-78 (TEMPORAL_TARGET=cloud, TEMPORAL_CLOUD_API_KEY, R20); mission-control-prod.ih0e7 is untouched this sprint.
- If the AWS worker (MO-77) is already serving AI Engineer's base queues, run the S0 Cloud variant with the WSL2 worker in lane role only, so there is one base worker per (namespace, application).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/temporal/client.py`
- `scripts/register_belllabs_search_attributes.py`
- `docs/MISSION_CONTROL_LOCAL_API.md`

## Acceptance

- [ ] Three-lane S0 probe set completes on a Cloud namespace with a recorded run.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
