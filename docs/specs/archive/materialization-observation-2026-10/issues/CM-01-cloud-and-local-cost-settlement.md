# [CM-01] Cloud and local cost settlement

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** CM-02, CM-04  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

Cloud cost reader is never composed; local cost read once though it settles late.

## Work

- Settle from charged_cents; estimated until reported; bounded delayed re-read; budget charged once; compose cost_reader.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/cost.py`
- `adapters/temporal/deployment_composition.py`

## Acceptance

- [ ] Describe cost estimated_then_settled true in production; no zero-fill.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Existing cost_reader/usage paths and Run 1 composition must be inspected; charged_cents settlement may arrive later than completion.

Settle each attributable provider run once and expose unknown/estimated/settled evidence honestly.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `adapters/cursor/cost.py`
- `adapters/temporal/deployment_composition.py (integrator-only)`

### Additional acceptance and negative cases

- [ ] Missing charged_cents is unknown/estimated with source, never zero; delayed settlement uses bounded rereads.
- [ ] Replay, duplicate settlement and replaced/continued turns do not double debit budget.
- [ ] Receipt preserves requested and observed model when available; cost cannot imply model identity or free execution.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/cursor/test_cloud_usage_unknown.py tests/unit/cursor -q
- Add delayed-settlement, multi-turn replay and single-budget-debit fixtures beside cost tests.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
