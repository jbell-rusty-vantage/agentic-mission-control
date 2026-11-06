# [MO-69] Binding digest tool for compose-bindings

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** M  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** None  
**Specification:** [SPEC-09-local-harness-path.md](../SPEC-09-local-harness-path.md)

## Problem

The launch-bindings file needs 62 hand-resolved values (model ids, digests, policy refs) (owner action O7).

## Work

- Compute environment, image, package and runtime digests and reviewed agent_profile_ref digests from owner selections; emit a file with zero BINDING_UNRESOLVED.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `bootstrap/preflight.py`
- `application/authoring/provider_launch.py`
- `scripts/`

## Acceptance

- [ ] compose-bindings produces a valid three-lane local file from owner selections only.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

ModelPin/AuthPin, typed ProviderLaneBinding, REQUIRED_PINS and Cursor bindings already exist; compose-bindings still needs reviewed owner selections and exact digests.

Emit a secret-free derived identity/configuration summary alongside valid three-lane bindings, without altering canonical binding shape.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `bootstrap/preflight.py`
- `application/authoring/provider_launch.py`
- `application/authoring/cursor_launch.py`
- `domain/execution/bindings.py (integrator-only; reuse)`

### Additional acceptance and negative cases

- [ ] Summary names runtime/lane, placement, requested model, auth/billing profile, SDK/CLI/schema pins, binding/materialization/describe digests and prerequisite freshness.
- [ ] Provider-reported serving model is separately identified or unknown; no provider-name translation or implicit fallback.
- [ ] Missing selection, pin mismatch or unsupported required control is refused before any provider create; no secret appears in output.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/authoring/test_hosted_launch_bindings.py tests/unit/prerequisites/test_preflight.py -q
- Add deterministic compose-summary, omitted-field digest, drift and redaction cases beside existing preflight tests; command cannot claim tests exist before added.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small-medium: derive existing heterogeneous pins, not a live model catalog.
