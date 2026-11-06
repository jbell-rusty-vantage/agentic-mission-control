# [CM-10] Parallel Cursor units in one run get distinct workspaces

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

Historical defect: units shared workspace identity. Run 1 cloud prepare now uses operation_id in per-unit branch construction; verify local isolation and remaining production/qualification evidence before changing allocation.

## Work

- Per-unit lease key and branch mc/{run}/{unit}; retries reuse their own lease; reattach finds per-unit branch.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/workspace.py`
- `adapters/cursor/cloud.py`
- `adapters/cursor/scm.py`
- `application/workspaces/policy.py`

## Acceptance

- [ ] Stage Graph with two parallel local and two parallel cloud stages gets four distinct leases and branches.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Cloud prepare already calls run_branch(binding, run_id, operation_id), backed by mission_branch. Original cloud-only defect statement is stale; inspect local lease identity separately.

Verify existing per-unit isolation, fixing only demonstrated gaps without replacing the common allocator.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `adapters/cursor/cloud.py`
- `adapters/cursor/workspace.py`
- `application/workspaces/cloud_branches.py`
- `application/workspaces/service.py (reuse)`

### Additional acceptance and negative cases

- [ ] Parallel local/cloud units in one run have distinct writable leases/branches; retries reuse only the same unit.
- [ ] Reattach locates the sealed unit branch; cleanup of one unit cannot affect another.
- [ ] Cite already integrated source/tests when sufficient; preserve original acceptance without redundant branch/allocator design.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/cursor/test_cloud_workspace_and_resume.py tests/unit/cursor/test_local_reconcile_and_rehydration.py tests/unit/workspaces -q
- Add production-composition parallel-unit/retry/cleanup fixture only where current tests do not establish the criterion.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
