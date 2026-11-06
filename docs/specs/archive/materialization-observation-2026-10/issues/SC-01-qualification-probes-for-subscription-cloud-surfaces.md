# [SC-01] Qualification probes for subscription cloud surfaces

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** E — Qualification drills  
**Size:** S  
**Sprint:** deferred  
**Blocked by:** MO-40  
**Specification:** [DECISIONS.md](../DECISIONS.md)

## Problem

Experimental lanes depend on unverified behaviours (Q-L1, Q-L2, Q-X1, Q-X3).

## Work

- Run owner-authorized probes and record results.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/claude_cloud/`
- `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/codex_cloud/`

## Acceptance

- [ ] Each question answered with evidence.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
