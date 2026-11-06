# [MO-71] S0 probe manifests for all three local lanes

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** MO-69  
**Specification:** [SPEC-09-local-harness-path.md](../SPEC-09-local-harness-path.md)

## Problem

Existing examples depend on test-only schemas.

## Work

- One probe manifest per lane (claude_agent_sdk, codex, cursor_local) against a fixture repo, compiling on production and qualification seeds; exercises inject and cancel.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `tests/fixtures/manifests/materialization-observation/`
- `packages/mission-control-db-contract (seeds, if needed)`

## Acceptance

- [ ] compile reports 0 blockers on the local install for all three lanes.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

S0 requires owner-selected bindings and production/qualification seeds; delivery does not prove provider loading.

Add exact local Anthropic identity/tool/configuration and evidence requirements to the three S0 probe manifests.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Requires MO-69 output and integrated MO-04/05/08/21/34; retain issue deps and verify these evidence joins before S0.

### Affected interfaces (existing seams unless explicitly proposed)

- `deployments/ (S0 probe manifests; integrator selects exact path)`
- `bootstrap/preflight.py`
- `application/agentic_components/projections.py (reuse)`

### Additional acceptance and negative cases

- [ ] Each manifest compiles from reviewed selections with zero unresolved bindings and names actual host/CLI/SDK/auth/model, required tool-family enforcement and output channel.
- [ ] Claude probe preserves repo instructions and exercises one admitted skill and a governed permission decision; report delivered/read-back/exercised separately.
- [ ] Unsupported required enforcement and optional-degradation cases are explicit; no probe substitutes an attestation for a required trusted method.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/authoring tests/unit/agentic_components/test_discovery_proof.py tests/unit/claude -q
- Compile proposed manifests against deterministic registry fixtures; assert no provider create for negative cases.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small-medium: select existing capabilities and add qualification cases.
