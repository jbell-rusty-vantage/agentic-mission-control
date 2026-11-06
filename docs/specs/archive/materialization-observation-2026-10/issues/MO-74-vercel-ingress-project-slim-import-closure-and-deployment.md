# [MO-74] Vercel ingress project, slim import closure and deployment

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-40  
**Specification:** [SPEC-10-ingress-on-vercel.md](../SPEC-10-ingress-on-vercel.md)

## Problem

The ingress must run on Vercel without the heavy package.

## Work

- Project layout per SPEC-10 §6 (app.py, pyproject/uv.lock, vercel.json fluid/iad1/30s/no trailing slash); vendor_closure script and import-closure test; env var contract. Model Gateway/800s routes remain S4 funding-gated and are not enabled by this issue.
- Deploy to team overtons-projects (Pro, R17), always with --scope overtons-projects because the CLI's current scope is another team; production host is the project's *.vercel.app domain; no custom domain this sprint.
- Verify actual live identity first; use the immutable built component 1.4.0 (34 migrations, manifest/fingerprint in RUN-2-HANDOFF), with ingress role through LIVE_PLAN.md and integrator-only reviewed proofs. Do not reconstruct the obsolete 0035-0039 range or overwrite the artifact. Live apply requires exact current authority/prerequisites.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `deployments/ingress-vercel/`
- `src/mission_control/interfaces/http/ingress.py`
- `tests/unit/ingress/`

## Acceptance

- [ ] Import-closure test passes; preview build succeeds; production deploy answers health and rejects unauthenticated calls.
- [ ] Live 1.4.0 qualify-before/apply/verify/qualify-after evidence recorded for both projects.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

MO-40 SQL/service already integrated. Edge must remain slim, without lane SDK/Temporal imports or a background worker.

Package/deploy only the existing ingress closure and expose product/version/session-safe webhook handling.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `deployments/ingress-vercel/`
- `interfaces/http/ingress.py (Events lease)`
- `application/signals/verification.py (reuse)`

### Additional acceptance and negative cases

- [ ] Import closure excludes Temporal/provider adapters/LangGraph; no production DSN in preview and no Temporal credentials at edge.
- [ ] Fixture webhook schema is tied to the qualified bound product/version/session; wrong scope/session and forged/replayed payloads refuse.
- [ ] No queue replacement; account/version metadata is evidence, not trusted caller-supplied authority.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/signals/test_verification.py tests/unit/signals/test_provider_wake.py -q
- Future ingress project import-closure/build checks: exact path created by MO-74; local restricted PostgreSQL route tests from SPEC-10.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
