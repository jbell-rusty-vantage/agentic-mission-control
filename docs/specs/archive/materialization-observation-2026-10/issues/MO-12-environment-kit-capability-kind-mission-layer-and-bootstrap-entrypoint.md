# [MO-12] Environment Kit capability kind, mission layer and bootstrap entrypoint

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** L  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-01, MO-10  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

Nothing provisions packages/runtimes or runs setup; no readiness receipt (gap G2/G3).

## Work

- Add Capability Kind environment_kit with mc.environment_kit.v1 manifest.
- Render .mission/setup/run from kit mission steps; receipt.json contract; bootstrap entrypoint per lane.
- Publish starter kits: python-uv, node, python-uv-node, mission-control-dev, knowledge-research, biotech-backend.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `domain/capabilities/`
- `application/capabilities/`
- `application/environments/`
- `skills/ or catalog seeds`
- `packages/mission-control-db-contract`

## Acceptance

- [ ] Local lanes reach readiness 'prepared' with a receipt; kits searchable in the catalog with host_support.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
