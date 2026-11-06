# [CM-02] Per-run token attribution across all turns

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

Local charges agent totals; cloud counts only the final run; cache tokens dropped.

## Work

- Per-run usage summed across replaced and continuation turns; additive cache_read/cache_write tokens; unknown stays unknown.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/bridge.py`
- `adapters/cursor/local.py`
- `adapters/cursor/cloud.py`
- `application/execution/harness/lane_turns.py`
- `domain/execution/lanes.py`

## Acceptance

- [ ] Cancel-and-replace plus continuation fixture charges each run once.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Per-run totals must include every replaced and continuation turn; session aggregates alone do not prove turn attribution.

Use attributable native run/turn identities for token/cache accounting and preserve unavailable counters.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `adapters/cursor/bridge.py`
- `adapters/cursor/local.py`
- `adapters/cursor/cloud.py`
- `application/execution/harness/lane_turns.py`

### Additional acceptance and negative cases

- [ ] Two turns, cancel-and-replace, continuation and reconnect fixture count each native run once.
- [ ] Absent input/output/cache fields remain unknown; partial totals are disclosed.
- [ ] Native usage and model evidence identify source/version; duplicate SSE families cannot inflate totals.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/cursor tests/conformance/lanes -q
- Add replaced/continuation-turn, missing-counter and replay cases; coordinate frame fixtures with CM-13.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
