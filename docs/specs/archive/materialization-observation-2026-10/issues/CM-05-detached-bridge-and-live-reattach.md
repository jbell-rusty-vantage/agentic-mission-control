# [CM-05] Detached bridge and live reattach

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** L  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** CM-04  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

The local bridge dies with the worker, leaving in-flight runs in_doubt.

## Work

- Sidecar bridge per lease with 0600 discovery file; connect on reattach; list_runs reconciliation; orphan sweep at worker start.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/bridge.py`
- `adapters/cursor/local.py`

## Acceptance

- [ ] Killing the worker mid-run and restarting resumes the same live run with no duplicate frames.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
