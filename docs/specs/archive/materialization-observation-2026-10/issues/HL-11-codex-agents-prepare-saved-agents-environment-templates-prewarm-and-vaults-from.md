# [HL-11] codex_agents prepare: saved agents, environment templates, prewarm and vaults from pack files

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S3 (codex_agents hosted, launched remotely)  
**Blocked by:** HL-06, HL-23  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Project Cognition Pack and kits through the Agents API.

## Work

- Pack files under deployments/hosted-packs/<app>/codex_agents/: saved agent (instructions append plus inlined repo rules, function tools mc_*, MCP), environment template (setup commands, packages, network allowlist), skills and plugins, vault credential names.
- Saved agent per pack digest; environment templates and prewarm with Idempotency-Key; vault credentials from the worker env at sync time.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/openai_agents/prepare.py`
- `adapters/openai_agents/client.py`

## Acceptance

- [ ] Fake-API tests; drill reuse by digest.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
