# [MO-35] Publish Cognition Profiles for SDLC, knowledge and mixed work

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** S  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-30  
**Specification:** [SPEC-02-cognition.md](../SPEC-02-cognition.md)

## Problem

Task families need default cognition packs.

## Work

- Publish cognition/sdlc, cognition/knowledge, cognition/mixed as plugins/workflow templates sized to lane limits.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `skills/`
- `catalog seeds`

## Acceptance

- [ ] Manifests reference them; capability search finds them.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
