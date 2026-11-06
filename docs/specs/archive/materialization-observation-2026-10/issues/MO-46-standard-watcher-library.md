# [MO-46] Standard watcher library

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** S  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-44  
**Specification:** [SPEC-04-watchers-and-callbacks.md](../SPEC-04-watchers-and-callbacks.md)

## Problem

Replace the owner's ad hoc supervisor/poll/stop scripts with reusable templates.

## Work

- stall-detector, result-marker-stop, ci-watch, pr-merged-release-wait, artifact-pipeline, budget-guard, heartbeat-progress.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `skills/ or catalog seeds`

## Acceptance

- [ ] Each template has an example manifest and a test.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
