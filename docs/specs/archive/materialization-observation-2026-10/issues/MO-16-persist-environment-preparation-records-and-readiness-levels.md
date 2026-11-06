# [MO-16] Persist environment preparation records and readiness levels

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-10  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

mc.environment_preparation.v1 is deferred (C15); readiness is copied from deployment declarations.

## Work

- Common SQL migration plus seeds in the db-contract package; repository adapter; readiness ladder declared→exercised.
- Validation Report and Launch Ticket cite the record.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `packages/mission-control-db-contract`
- `adapters/postgres/`
- `application/environments/`

## Acceptance

- [ ] Real local PostgreSQL test; launch policy enforces the minimum readiness level.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
