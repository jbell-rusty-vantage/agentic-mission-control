# [HL-15] claude_agent_sdk on Sandbox Host (real Claude Code harness)

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** L  
**Sprint:** in — slice S4 (Funding-gated: self-hosted placements and real harnesses on Sandbox Host)  
**Blocked by:** HL-02, HL-03, MO-73  
**Gate:** funding — start only when the owner releases slice S4 (DECISIONS R31)  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

The owner wants the Claude Code harness off the local machine on API billing.

## Work

- Bridge SDK stdio to the CLI in the sandbox (custom transport or relay, resolve Q-S1); Model Gateway for model access; SessionStore mirroring for cross-host resume.
- execution_environment.kind sandbox_host; keep in-process kernel hooks and can_use_tool.
- Use the exported Transport via ExplicitEnvironmentCliTransport spawn injection with a SandboxProcess adapter; set CLAUDE_CONFIG_DIR; restore transcript for cross-host resume (see MO-73). The Daytona variant uses the Vercel-hosted gateway on *.vercel.app and works on Tier 1/2 (R16).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/claude/transport.py`
- `adapters/claude/host.py`
- `adapters/claude/session.py`

## Acceptance

- [ ] Drill: CLI in Docker through the gateway, hooks fire in-process, resume on another worker.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
