# [HL-21] Hosted lanes: full Cognition Pack and Secret Broker projection

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S3 (codex_agents hosted, launched remotely)  
**Blocked by:** HL-07, HL-11, MO-30, MO-11  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

HL-07 and HL-11 start from checked-in pack files (R30) so S2 and S3 need not wait for the S1 foundations; the general projection must replace them once MO-30 and MO-11 land.

## Work

- Drive agent, skill, environment and vault sync from the MO-30 projection targets and the Secret Broker provider_vault delivery channel instead of pack files.
- Keep digest keys identical so resources created from pack files are reused, not duplicated.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/anthropic_managed/prepare.py`
- `adapters/openai_agents/prepare.py`
- `deployments/hosted-packs/`

## Acceptance

- [ ] The S2 and S3 drill missions re-run through the projection with zero new provider resources created when nothing changed.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
