# [MO-14] Git write path: scoped credentials, pre-push guard, repo_pr effect and head SHA artifacts

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-05  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

No push/PR path for local lanes; repo_commit never pinned; cloud push uses ambient worker credentials.

## Work

- Worktree-scoped credential helper using a Mission Control GitHub App installation token (owner gh fallback).
- Mission Control-owned pre-push guard allowing only mc/{run}/*.
- repo_pr Governed Effect; head SHA artifacts for every lane (Claude-Session trailer, Cursor branch lookup).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/workspaces/git_workspaces.py`
- `application/effects/`
- `adapters/github/`
- `adapters/cursor/scm.py`

## Acceptance

- [ ] Push to a non-mc ref rejected; draft PR created through the effect and recorded with SHA.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
