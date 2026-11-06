# [MO-08] WSL2 worker runbook and host preflight for local Claude and Codex lanes

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** None  
**Specification:** [SPEC-03-workspaces-and-placement.md](../SPEC-03-workspaces-and-placement.md)

## Problem

Local Claude and Codex lanes refuse Windows hosts; the owner's machine is Windows (gap G16, decision D5).

## Work

- Document and script a WSL2 worker with the workspace root on the WSL filesystem and pinned CLIs.
- Preflight checks host OS, CLI versions and auth per lane.
- Install in WSL: uv (lock-compatible), Python 3.12, Node LTS, pinned Codex, Claude Code CLI; detect Windows shims leaking via /mnt/c on PATH; lease roots on Linux FS; same-tree rule (run from /mnt/c with a separate venv or checkpointed clone).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/MISSION_CONTROL_LOCAL_API.md`
- `bootstrap/preflight`
- `scripts/`

## Acceptance

- [ ] Preflight passes on the owner's WSL2 worker for claude_agent_sdk and codex.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
