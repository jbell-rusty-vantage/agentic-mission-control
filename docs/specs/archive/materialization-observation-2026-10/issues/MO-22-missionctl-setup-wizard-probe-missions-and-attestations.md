# [MO-22] missionctl setup wizard, probe missions and attestations

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-21  
**Specification:** [SPEC-05-owner-prerequisites.md](../SPEC-05-owner-prerequisites.md)

## Problem

Owner needs a guided path to complete and verify setup.

## Work

- Wizard per provider (open URL, paste block, attest, verify) following the repo wizard skill pattern.
- Probe missions per cloud/API lane emitting readiness signals; prereq attest command.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `interfaces/cli/`
- `scripts/`
- `missions/probes/`

## Acceptance

- [ ] Owner completes Cursor and Anthropic setup through the wizard; probes flip items to verified.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
