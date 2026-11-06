# [MO-44] Watchers: schema, compiled descriptors, evaluator, actions and boundaries

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** L  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-43  
**Specification:** [SPEC-04-watchers-and-callbacks.md](../SPEC-04-watchers-and-callbacks.md)

## Problem

Manifests cannot declare watchers/callbacks/limits; controls.notifications is dead; event_wait only releases manually (gap G7).

## Work

- controls.watchers with closed ADR-0010 conditions, typed actions and mandatory boundaries; Capability Kind watcher.
- Deterministic Watcher Evaluator over outbox/frames/timers; watcher.fired/failed events; dedupe key (watcher_id, trigger_event_id).
- controls.notifications consumed as sugar; event_wait satisfiable by watcher.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `domain/authoring/manifest_v2.py`
- `domain/programs/`
- `application/watchers/`
- `adapters/temporal/`

## Acceptance

- [ ] Temporal test env: sample watchers fire deterministically; replay causes no duplicate actions; limits enforced.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
