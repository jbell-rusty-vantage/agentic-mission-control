# [HL-06] Profile vocabulary for claude_managed and codex_agents, data class and ADR-0050

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** HL-05  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

New profiles touch every vocabulary listed in research/codebase-new-lanes.md §2.

## Work

- Add both profiles on existing lanes (claude, codex) with placements; describe matrices per SPEC-06 §9; options classes; api_key auth routes with billing consent.
- Add data_class to missions and enforce per-lane admission (SPEC-06 §8).
- DB migration after 0034 widening profile checks; regenerate schemas; ADR-0050 proposed.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `domain/capabilities/host_support.py`
- `domain/execution/lanes.py`
- `domain/execution/bindings.py`
- `domain/authoring/manifest.py`
- `domain/authoring/manifest_v2.py`
- `application/execution/harness/describe.py`
- `application/authoring/provider_launch.py`
- `bootstrap/provider_auth.py`
- `packages/mission-control-db-contract`

## Acceptance

- [ ] Import-time guards pass; describe-only registry lists both profiles unqualified; PHI-classed mission refused.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
