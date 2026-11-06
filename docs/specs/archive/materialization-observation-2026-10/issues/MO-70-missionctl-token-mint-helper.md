# [MO-70] missionctl token mint helper

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** None  
**Specification:** [SPEC-09-local-harness-path.md](../SPEC-09-local-harness-path.md)

## Problem

Operators hand-write JWTs to use the API locally.

## Work

- missionctl token mint from an operator key with scopes and expiry; never prints the key.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `interfaces/cli/main.py`
- `adapters/auth/`

## Acceptance

- [ ] S0 runbook needs no hand-written JWT code.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
