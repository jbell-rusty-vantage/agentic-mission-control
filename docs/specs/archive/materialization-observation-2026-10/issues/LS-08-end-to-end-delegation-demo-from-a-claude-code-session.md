# [LS-08] End-to-end delegation demo from a Claude Code session

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Skills  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** S  
**Sprint:** in — slice LS (Local CLI job skills)  
**Blocked by:** LS-05, LS-06, LS-07  
**Specification:** [SPEC-08-local-cli-skills.md](../SPEC-08-local-cli-skills.md)

## Problem

Prove the owner workflow.

## Work

- Claude Code launches a Codex fix job and a Cursor review job in parallel in the background, is woken on completion and reads both results.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `.agents/skills/coding-cli-jobs/examples/`

## Acceptance

- [ ] Recorded session transcript and result files.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
