# [MO-03] Back Codex kernel hooks and handle Codex hook trust

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** MO-01  
**Specification:** [SPEC-02-cognition.md](../SPEC-02-cognition.md)

## Problem

.codex/hooks.json calls .mission/hooks/kernel.py which the Codex lane never writes; no hook callback service or token is composed; non-managed hooks need hash trust (gap G11).

## Work

- Write kernel.py, context.json and the per-execution token in the Codex lane exactly as cursor_local does; compose HookCallbackService for codex.
- Record hook trust for exact digests in the isolated CODEX_HOME or install kernel hooks as managed requirements (resolve Q-X2).
- Correct the release statement until a live drill proves fail-closed hooks.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/codex/harness.py`
- `adapters/codex/compose.py`
- `adapters/cursor/kernel_hook_script.py`
- `interfaces/http/hook_callback.py`
- `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md`

## Acceptance

- [ ] Live Codex CLI drill: kernel before_tool deny enforced end to end.
- [ ] Release statement matches evidence.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
