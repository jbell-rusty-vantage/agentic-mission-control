# [CM-08] Continuation and fork agent parity on cloud

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

Continuation agent drops subagents, env and metadata; source never archived.

## Work

- Verify start/hydrate body parity; factor a shared builder only where needed. Preserve admitted options and idempotent env delivery; archive source after successful handover/custody.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/cloud.py`
- `adapters/cursor/controls.py`

## Acceptance

- [ ] Body parity test; source archived idempotently.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Cloud start already projects MCP/customSubagents and per-unit branch; inspect start versus hydrate/continuation for remaining env/metadata differences.

Preserve the entire admitted supported create configuration through continuation without treating code factoring as proof.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `adapters/cursor/cloud.py`
- `adapters/cursor/controls.py`

### Additional acceptance and negative cases

- [ ] Golden start/hydrate bodies preserve model, mode, environment, inline MCP/subagents, metadata and secret-reference delivery semantics.
- [ ] Worker-loss reattach uses sealed configuration; drift or unsupported transfer refuses rather than dropping options.
- [ ] Source archive happens idempotently only after successful handover/custody; no duplicate session/turn or budget reset.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/cursor/test_cloud_workspace_and_resume.py tests/unit/cursor/test_local_reconcile_and_rehydration.py tests/unit/cursor/test_cloud_inline_options.py -q
- Add body-parity negative cases for missing required option and source archive retry.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
