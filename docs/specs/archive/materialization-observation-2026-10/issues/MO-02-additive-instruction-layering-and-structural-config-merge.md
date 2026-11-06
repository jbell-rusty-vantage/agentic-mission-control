# [MO-02] Additive instruction layering and structural config merge

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** MO-01  
**Specification:** [SPEC-02-cognition.md](../SPEC-02-cognition.md)

## Problem

Cursor overwrites the repo AGENTS.md; Claude/Codex refuse repos that already have AGENTS.md, CLAUDE.md, .mcp.json or settings (gap G8).

## Work

- Cursor: mission overlay as .cursor/rules/mc-mission.mdc (alwaysApply); never touch AGENTS.md.
- Claude: never create CLAUDE.md; local overlay through system_prompt preset append; cloud overlay .claude/rules/mc-mission.md.
- Codex: developerInstructions on thread/start locally; merged AGENTS.override.md (repo AGENTS.md + delimited mission section, <=32 KiB) for cloud.
- Structural merge for .claude/settings.json, .cursor/hooks.json, .codex/hooks.json, .mcp.json, .codex/config.toml with provenance markers and materialization.conflicts policy; receipt lists merged keys.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `application/agentic_components/materialization.py`
- `application/agentic_components/projections.py`
- `adapters/cursor/projection.py`
- `adapters/claude/harness.py`
- `adapters/codex/harness.py`

## Acceptance

- [ ] A fixture repo with its own AGENTS.md, .claude/skills and .cursor/hooks.json launches on all three local lanes; repo files are byte-identical after the run.
- [ ] Discovery reports both repo and mission items; conflicts follow the declared policy.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
