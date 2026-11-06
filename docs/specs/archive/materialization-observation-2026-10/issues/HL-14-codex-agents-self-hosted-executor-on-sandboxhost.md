# [HL-14] codex_agents self_hosted executor on SandboxHost

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** M  
**Sprint:** in — slice S4 (Funding-gated: self-hosted placements and real harnesses on Sandbox Host)  
**Blocked by:** HL-12, HL-02  
**Gate:** funding — start only when the owner releases slice S4 (DECISIONS R31)  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Code work needs image control, worktrees and snapshots.

## Work

- Run codex exec-server --remote with environment key in the lease; version pin and compatibility check; 5-minute connect deadline handling; snapshot via SandboxHost.
- Environment key only (connect scope) in the sandbox; 30 s disconnect retention; 5-minute connect deadline; works on all Daytona tiers (openai/chatgpt egress is essential-listed).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/openai_agents/executor.py`

## Acceptance

- [ ] Drill: code mission in Docker executor; reconnect after executor restart.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
