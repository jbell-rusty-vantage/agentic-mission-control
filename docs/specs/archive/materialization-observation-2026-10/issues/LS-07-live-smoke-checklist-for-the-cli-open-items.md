# [LS-07] Live smoke checklist for the CLI open items

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Skills  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** S  
**Sprint:** in — slice LS (Local CLI job skills)  
**Blocked by:** LS-02, LS-03, LS-04  
**Specification:** [SPEC-08-local-cli-skills.md](../SPEC-08-local-cli-skills.md)

## Problem

Remaining live unknowns: Claude exit codes on max-turns/auth failure, Codex Windows sandbox under --ignore-user-config and kill reach, Cursor stdin prompt and read-only shell behaviour, claude -p usage pool after 2026-10-07.

## Work

- Owner-authorized cheap prompts; record results in references; adjust adapters.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `.agents/skills/coding-cli-jobs/references/`

## Acceptance

- [ ] Every open item in SPEC-08 §9 answered.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
