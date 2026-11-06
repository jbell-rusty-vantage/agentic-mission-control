# [HL-08] claude_managed session lifecycle and frame classifier

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** L  
**Sprint:** in — slice S2 (claude_managed cloud, launched remotely)  
**Blocked by:** HL-04, HL-07  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Full harness operations on Managed Agents sessions.

## Work

- start with budget and metadata reconcile; observe SSE + history with cursor (created_at,id,threads); reattach; send_turn queue; cancel via user.interrupt; interrupt_and_inject; pause via budget gate; usage from list_cost; end via interrupt→archive→delete.
- KIND_TABLES/DEDUPE rows; closing facts from idle end_turn correlated with interrupts; multiagent off by default.
- Read-only knowledge missions may enable multiagent (dynamic workflows and subagents) and user.define_outcome; outcome results are evidence for the Completion Contract, never acceptance (R33). Code missions keep multiagent off.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/anthropic_managed/harness.py`
- `adapters/anthropic_managed/frames.py`
- `application/frames/kinds.py`

## Acceptance

- [ ] Conformance suite passes; reattach after worker kill yields no duplicate frames.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
