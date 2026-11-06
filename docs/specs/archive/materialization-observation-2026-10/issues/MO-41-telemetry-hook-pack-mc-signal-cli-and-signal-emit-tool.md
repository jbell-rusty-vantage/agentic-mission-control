# [MO-41] Telemetry Hook Pack, mc-signal CLI and signal_emit tool

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-40, MO-30  
**Specification:** [SPEC-04-watchers-and-callbacks.md](../SPEC-04-watchers-and-callbacks.md)

## Problem

Agents and hooks have no formal channel back to Mission Control (replaces ad hoc watcher/status files).

## Work

- Dependency-free signal script with spool, seq and batching; mc-signal CLI; signal_emit MCP tool; mc-signals skill.
- Native projection per lane per SPEC-04 §4.2.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `skills/mc-signals/`
- `application/agentic_components/`
- `interfaces/mcp/`

## Acceptance

- [ ] cursor_cloud drill: session.started, materialization.observed and stop arrive ordered with no gaps.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
