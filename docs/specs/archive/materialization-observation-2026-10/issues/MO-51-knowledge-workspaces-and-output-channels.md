# [MO-51] Knowledge workspaces and output channels

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-40, MO-50  
**Specification:** [SPEC-03-workspaces-and-placement.md](../SPEC-03-workspaces-and-placement.md)

## Problem

Knowledge/research/content missions cannot launch without a target code repo (gap G9).

## Work

- workspace.kind code|knowledge|mixed; Application knowledge repo binding; research lease reachable; repo-optional for API lanes and Cursor no-repo agents.
- Output channels: ingress artifact upload, branch commit, provider artifacts; Completion Contract names the evidence channel.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `domain/authoring/manifest_v2.py`
- `adapters/cursor/workspace.py`
- `application/workspaces/`
- `interfaces/http/ingress.py`

## Acceptance

- [ ] A knowledge mission with no code repo completes on cursor_cloud, claude_managed and a local lane with an accepted output Artifact.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
