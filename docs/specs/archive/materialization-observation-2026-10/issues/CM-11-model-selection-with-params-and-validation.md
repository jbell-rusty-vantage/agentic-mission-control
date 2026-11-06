# [CM-11] Model selection with params and validation

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** S  
**Sprint:** deferred  
**Blocked by:** None  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

Only a model id is passed; no params or validation.

## Work

- Additive model_params; validate against models.list() or /v1/models with MODEL_UNAVAILABLE; resolved model in closing facts.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `application/authoring/cursor_launch.py`
- `adapters/cursor/bridge.py`
- `adapters/cursor/cloud.py`

## Acceptance

- [ ] Invalid params refused before launch.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
