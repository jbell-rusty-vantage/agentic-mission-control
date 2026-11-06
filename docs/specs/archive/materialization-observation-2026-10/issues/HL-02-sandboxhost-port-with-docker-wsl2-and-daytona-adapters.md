# [HL-02] SandboxHost port with Docker (WSL2) and Daytona adapters

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** M  
**Sprint:** in — slice S4 (Funding-gated: self-hosted placements and real harnesses on Sandbox Host)  
**Blocked by:** HL-01  
**Gate:** funding — start only when the owner releases slice S4 (DECISIONS R31)  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Self-hosted executors and Sandbox Host placements need one provider-neutral port.

## Work

- Port per SPEC-06 §2 and §12.1; Daytona adapter (daytona SDK 0.224.0 async, explicit key/URL/target, kit snapshots per size, TTL reaper, session exec with echo suppressed and adapter-enforced timeouts, labels and orphan sweep).
- Docker adapter on WSL2 with TTL reaper, egress-proxy sidecar, committed-image snapshots and the same text-line stdin contract.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `application/execution/ports.py`
- `adapters/sandboxes/docker/`
- `adapters/sandboxes/<provider>/`

## Acceptance

- [ ] Shared SandboxHost conformance tests pass on Docker and Daytona (Daytona run owner-authorized); orphan sweep removes labelled leftovers.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
