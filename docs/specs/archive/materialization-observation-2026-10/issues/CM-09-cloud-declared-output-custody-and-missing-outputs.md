# [CM-09] Cloud declared-output custody and missing outputs

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** M  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

Cloud registers only artifacts/, never outputs/ from the branch.

## Work

- Register outputs/* at branch head as candidate refs with digests; missing_outputs closing fact; optional single follow-up; persist prUrl before archive.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/cloud.py`
- `adapters/cursor/scm.py`

## Acceptance

- [ ] Outputs registered; missing-output follow-up fires once; prUrl persisted.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Artifact API staging and branch-head recording exist; declared outputs/ registration and missing-output semantics must be checked at current code.

Collect declared output bytes through the admitted channel and prove immutable custody before cleanup/archive.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `adapters/cursor/cloud.py`
- `application/artifacts/artifact_promotion.py (reuse)`
- `domain/programs/human_gate.py (reuse)`

### Additional acceptance and negative cases

- [ ] Branch outputs cite exact head; API outputs cite session/run/turn and digest; missing declared outputs produce an explicit fact.
- [ ] Follow-up is at most the authored bounded allowance; provider done/path/prUrl alone cannot satisfy acceptance.
- [ ] Registered output/version is what review binds; review acceptance does not grant repo publication; cleanup only follows verified custody.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/cursor/test_knowledge_output_channels.py tests/unit/workspaces/test_artifact_promotion.py tests/unit/human_tasks/test_human_gate_rules.py -q
- Add missing-output, changed branch head, digest mismatch, duplicate registration and stale-review packet cases.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small-medium custody/evidence join; no new viewer.
