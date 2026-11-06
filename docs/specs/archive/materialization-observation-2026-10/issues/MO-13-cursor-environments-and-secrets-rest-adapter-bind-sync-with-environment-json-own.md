# [MO-13] Cursor environments and secrets REST adapter (bind/sync) with environment.json ownership check

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-11, MO-12  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

Cursor launch sends only env.type; deployment environment_ref is never transmitted; a committed environment.json silently overrides API environments.

## Work

- Implement /v1/environments CRUD and secrets PUT/DELETE; naming mc-<kit>-<digest8>; version history read-back digest.
- Preflight check: committed .cursor/environment.json mc-owned / foreign / absent.
- Resolve Q-C1 (start on startingRef) and Q-C2 (envVars) by drill before relying on them.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/cloud_api.py`
- `adapters/cursor/environments.py`
- `application/environments/`

## Acceptance

- [ ] Drill: environment created once, reused by a second mission; foreign committed file refused; secret names synced.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
