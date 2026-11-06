# [MO-43] Wake channels: missionctl wait, inbox long-poll, MCP inbox_wait, auto-subscribe

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** None  
**Specification:** [SPEC-04-watchers-and-callbacks.md](../SPEC-04-watchers-and-callbacks.md)

## Problem

Nothing wakes the orchestrating agent; MCP surfaces are split; auto-subscribe missing (gap G5).

## Work

- missionctl wait (--follow); GET inbox?wait=; MCP inbox_wait on the authenticated server; unify inbox/transcripts/signal_emit onto it.
- Auto-subscribe the launcher on every coordinator launch; relay on by default; webhook payload: summary; deprecate mission_subscribe (ADR-0049).
- Authenticated MCP gains submit, start and intervene (dev MCP compiles only).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `interfaces/cli/main.py`
- `interfaces/http/coordinator_inbox.py`
- `interfaces/mcp/`
- `bootstrap/api.py`
- `application/subscriptions/`

## Acceptance

- [ ] A Claude Code coordinator is woken by background missionctl wait on run.completed (recorded transcript).

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
