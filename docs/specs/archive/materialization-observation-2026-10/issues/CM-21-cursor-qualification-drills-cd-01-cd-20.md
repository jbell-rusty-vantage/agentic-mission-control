# [CM-21] Cursor qualification drills CD-01..CD-20

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** E — Qualification drills  
**Size:** M  
**Sprint:** in — slice Q (Qualification drills)  
**Blocked by:** CM-01, CM-05, CM-09, CM-10  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

qualified flips only on recorded drill evidence.

## Work

- Run owner-authorized drills per research/cursor-maturity.md and carried-over README drills; record transcripts, frames, journal rows and usage disposition.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/qualification/lanes/cursor_local/`
- `docs/qualification/lanes/cursor_cloud/`

## Acceptance

- [ ] Every drill recorded; describe matrices updated from evidence.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

CD-01..20 are exact-placement qualification, not every aspirational/deferred capability; Run 1 receipts are narrower than a blanket Cursor flag.

Qualify only currently in-scope implemented cells with exact identity/configuration, accounting, recovery and custody evidence.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `docs/qualification/lanes/cursor_local/`
- `docs/qualification/lanes/cursor_cloud/`
- `application/execution/harness/describe.py (integrator-only)`

### Additional acceptance and negative cases

- [ ] Each applicable drill maps to exact profile/OS/build/configuration pins and requested/observed model; unavailable counters remain unknown.
- [ ] No deferred CM-11/12/14/15/16/17/20/22/06 capability is promoted by the matrix or a fixture.
- [ ] CM-01/05/09/10 joins and shared CM-02/08/13 regression evidence are complete before a qualified cell changes.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/cursor/test_qualification.py tests/conformance/lanes -q
- Live: use existing research/cursor-maturity CD definitions only after per-drill authorization and current budget/prerequisite reconciliation.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
