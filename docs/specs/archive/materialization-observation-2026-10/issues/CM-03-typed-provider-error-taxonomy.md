# [CM-03] Typed provider error taxonomy

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Runtime  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** S  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-07-cursor-maturity.md](../SPEC-07-cursor-maturity.md)

## Problem

Local maps no rate-limit/auth/network errors; cloud maps only 429.

## Work

- Map SDK and HTTP errors to typed retryable/non-retryable errors with retry_after and request_id; wire ADR-0011 classifier.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/cursor/bridge.py`
- `adapters/cursor/cloud_api.py`

## Acceptance

- [ ] Each class routes to the correct retry counter; no secrets in messages.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Remote-session typed errors already exist; Cursor adapter-specific mappings and exact retry owner still need validation.

Classify native auth/quota/rate/network/archived/configuration failures without leaking prose/secrets or unsafe create replay.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `adapters/cursor/bridge.py`
- `adapters/cursor/cloud.py`
- `adapters/remote_session/errors.py (reuse)`

### Additional acceptance and negative cases

- [ ] Recorded 429/auth/network/archived/unsupported-option errors map to ADR-0011 decisions with bounded retries.
- [ ] Ambiguous create reconciles native identity before retry; auth/configuration refusal is not hidden by fallback.
- [ ] Receipt preserves unknown usage/cost on failed/cancelled requests; diagnostics identify product/profile/version.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/cursor tests/unit/remote_session -q
- Add parameter/auth refusal before-create and ambiguous-create fixtures; no live retries required.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
