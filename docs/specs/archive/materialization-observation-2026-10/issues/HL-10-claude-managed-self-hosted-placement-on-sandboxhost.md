# [HL-10] claude_managed self_hosted placement on SandboxHost

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** L  
**Sprint:** in — slice S4 (Funding-gated: self-hosted placements and real harnesses on Sandbox Host)  
**Blocked by:** HL-08, HL-02  
**Gate:** funding — start only when the owner releases slice S4 (DECISIONS R31)  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Code work needs our worktrees, remotes, services and real tool interception.

## Work

- Environment worker with our wrapped tool implementations (Stop Fence, Operation Intent, kernel policy, frame capture) over SandboxHost exec in the lease.
- Own runner without the 150 s cap; staged repos; environment key from Secret Broker.
- Own poll/ack/heartbeat loop per SPEC-06 §4.3 (412 = lease lost, ttl_seconds, per-item sessions_token); idempotent tools keyed (session, tool_use_id); worker stays outside the sandbox.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/anthropic_managed/worker.py`
- `adapters/temporal/activities/`

## Acceptance

- [ ] Drill: code mission in a Docker lease with kernel deny and verified publication.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
