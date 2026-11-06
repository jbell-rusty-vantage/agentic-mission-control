# [HL-12] codex_agents session lifecycle, recovery recipe and frame classifier

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** L  
**Sprint:** in — slice S3 (codex_agents hosted, launched remotely)  
**Blocked by:** HL-04, HL-11  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Full harness operations on Agents API sessions without replay cursors.

## Work

- start with metadata reconcile; observe SSE with documented buffer→retrieve→items?after→apply recovery; status-gated send vs steer; cancel; usage; DELETE end; environment state events (suspended/expired/reset) handled.
- Closing facts only from item.done and turn terminal events.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/openai_agents/harness.py`
- `adapters/openai_agents/frames.py`
- `application/frames/kinds.py`

## Acceptance

- [ ] Conformance suite passes; worker-kill recovery reconciles with no duplicates.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
