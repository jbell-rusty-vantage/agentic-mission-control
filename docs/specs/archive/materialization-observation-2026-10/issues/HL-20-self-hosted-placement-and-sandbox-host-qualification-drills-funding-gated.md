# [HL-20] Self-hosted placement and Sandbox Host qualification drills (funding-gated)

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** E — Qualification drills  
**Size:** M  
**Sprint:** in — slice Q (Qualification drills)  
**Blocked by:** HL-10, HL-14, HL-15, HL-16  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

The cloud placements qualify in HL-24 and HL-25. The self-hosted placements and the self-run harnesses on Sandbox Host qualify only when the owner releases slice S4 (R31). Open questions Q-M2, Q-M3, Q-S1 and Q-S2 need these drills.

## Work

- Owner-authorized, finite-budget drills per SPEC-06 §11; record transcripts, frames, usage disposition.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/qualification/lanes/claude_managed/`
- `docs/qualification/lanes/codex_agents/`

## Acceptance

- [ ] Each profile/placement has a drill record; describe matrices updated from evidence.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
