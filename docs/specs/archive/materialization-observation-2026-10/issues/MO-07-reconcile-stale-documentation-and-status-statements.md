# [MO-07] Reconcile stale documentation and status statements

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [GAP-REPORT.md](../GAP-REPORT.md)

## Problem

Several docs claim behaviour the code does not have (gap G17).

## Work

- Fix each statement listed in research/codebase-materialization.md §4 and codebase-observation.md §7.
- Remove or flag controls.notifications and mission_subscribe guidance until wired.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/knowledge/capabilities.md`
- `docs/knowledge/cursor-lane.md`
- `docs/knowledge/lanes-and-harness.md`
- `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md`
- `skills/mission-control-author/references/manifest-cheatsheet.md`
- `skills/mission-control-observe/SKILL.md`

## Acceptance

- [ ] python docs/tools/validate_okf.py passes; every corrected statement cites code.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Historical packet kickoff, migration allocation and describe/module prose conflict with Run 1 delivered code; original records remain provenance.

Reconcile active navigation and qualification claims from current code without rewriting immutable historical evidence or reopening completed scope.

**Non-goals:** No changes to historical receipt facts, completed Specs 1-6 contracts, provider wire IDs or live readiness.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `docs/`
- `AGENTS.md (generated index only)`

### Additional acceptance and negative cases

- [ ] Document hosted Agents API vs SDK/Responses and standard openai dependency vs historical wire pin; no wire lane rename.
- [ ] CM-10 closure reflects existing cloud unit branches and separately verifies local isolation; no duplicated allocator.
- [ ] Managed budget-pause unsupported/wiring blocker, release 1.4.0 live disposition and unknown S3 spend remain visible.
- [ ] Active kickoff uses fresh remaining issues and migration authority; preserved historical smoke endpoint discrepancy is labelled, not silently altered.

### Minimum verification (future commands, not executed)

- python docs/tools/agents_docs_index.py --check
- python docs/tools/validate_okf.py
- Read-only issue/spec/links/scope consistency audit; do not regenerate historical baseline over approved Run 2 plans.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
