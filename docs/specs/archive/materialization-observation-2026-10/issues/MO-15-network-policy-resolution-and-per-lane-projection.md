# [MO-15] Network policy resolution and per-lane projection

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** S  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-10  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

sandbox.egress only enters a policy digest; nothing is enforced (gap G2).

## Work

- Resolve network policy; project to Cursor egress fields, Codex sandbox network, Claude sandbox settings, Managed Agents limited networking, OpenAI environment allowlists, SandboxHost egress.
- Record enforced/advisory/unsupported per lane in the receipt.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `application/environments/`
- `adapters/cursor/`
- `adapters/codex/`
- `adapters/claude/`

## Acceptance

- [ ] Receipt honest per lane; Signal Ingress and Model Gateway hosts always included when required.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
