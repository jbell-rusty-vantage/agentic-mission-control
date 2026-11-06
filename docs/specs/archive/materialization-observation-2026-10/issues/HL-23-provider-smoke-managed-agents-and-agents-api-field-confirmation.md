# [HL-23] Provider smoke: Managed Agents and Agents API field confirmation

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice S2 (claude_managed cloud, launched remotely)  
**Blocked by:** None  
**Specification:** [MANAGED-AGENTS-REMOTE-PATH.md](../MANAGED-AGENTS-REMOTE-PATH.md)

## Problem

Lane code would otherwise be written against unconfirmed request shapes (MANAGED-AGENTS-REMOTE-PATH §3 sketches), open questions Q-M1 and Q-O2, and an unconfirmed model (gpt-6-luna on the Agents API).

## Work

- One script per provider (anthropic 1.13.0, openai 3.29.0 pinned), keys from the environment, nothing printed but ids and statuses: create a skill, a vault with one credential, an agent and an environment; start a session with a one-turn read-only prompt; stream; answer one custom/function tool; send a mid-turn user.message (Q-M1); interrupt; read usage; delete the session and archive test resources.
- OpenAI: confirm gpt-6-luna is accepted for the Codex harness; if refused, stop and ask the owner (SPRINT drill table). Check whether an AGENTS.md placed in the hosted workspace is honoured (Q-O2).
- Record exact working request shapes, ids returned, event names seen and usage in research/provider-smoke-2026-10.md.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `scripts/provider_smoke/`
- `docs/specs/archive/materialization-observation-2026-10/research/provider-smoke-2026-10.md`

## Acceptance

- [ ] Both smokes complete under $1 each (charged to the S2 and S3 budgets) with usage recorded; every created resource is deleted or archived.
- [ ] MANAGED-AGENTS-REMOTE-PATH §3 and SPEC-06 are corrected wherever a field differs.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
