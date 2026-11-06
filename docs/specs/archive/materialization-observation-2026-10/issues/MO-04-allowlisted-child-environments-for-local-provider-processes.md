# [MO-04] Allowlisted child environments for local provider processes

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

The Claude CLI inherits the whole worker environment (DB DSNs, other provider keys); Codex strips secrets its MCP servers need (gap G12).

## Work

- Start every provider child from an empty env plus an explicit allowlist (auth route, kit-declared variables, per-MCP env).
- Pass declared MCP secret env to Codex servers.
- Correct HANDOFF-2026-10-10 'credential-free' statement.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `bootstrap/provider_auth.py`
- `adapters/claude/transport.py`
- `adapters/codex/launcher.py`
- `adapters/cursor/bridge.py`

## Acceptance

- [ ] Sentinel test proves only allowlisted names reach each child process on all local lanes.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
