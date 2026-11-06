# [MO-79] Remote launch-request route on the Signal Ingress

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice R (Remote operation: thin Temporal worker on AWS and remote launch)  
**Blocked by:** MO-40, MO-75, MO-70  
**Specification:** [SPEC-10-ingress-on-vercel.md](../SPEC-10-ingress-on-vercel.md)

## Problem

The operator API is local-only and SPEC-10 keeps Temporal credentials off Vercel, so nothing outside the owner's machine can start a mission (gap G-R1, decision R29).

## Work

- POST /v1/ingress/{app}/missions:request authenticated by a minted operator launch credential (ingress_credential purpose mission_request, scoped to app and manifest set, expiring); writes an inbox row of kind mission_request carrying the manifest reference, inputs digest and idempotency key; replies 202 with the request id.
- GET /v1/ingress/{app}/missions:request/{id} returns request state (queued, admitted, refused with typed reason) and, once admitted, the mission id and lifecycle state from a read-only SQL view.
- The IngressDrainer admits the request by calling the same application admission handler the API uses (data_class, Spawn Grant and preflight checks included); a refusal is recorded, never retried silently.
- missionctl remote launch --app <app> --manifest <ref> mints nothing itself: it uses an operator-minted credential (MO-70) and polls the status route.
- Reuse the integrated 0035 mission_request kind and credential purpose; no SQL migration is needed for this route. Never edit applied 0035 or occupied 0040. A demonstrated new schema need requires integrator review and fresh additive release allocation.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `interfaces/http/ingress.py`
- `application/signals/`
- `application/missions/`
- `adapters/postgres/ingress.py`
- `deployments/ingress-vercel/ (route; leased from the integrator)`
- `interfaces/cli/ (missionctl remote launch)`

## Acceptance

- [ ] Real PostgreSQL tests: forged, expired and wrong-app requests refuse; replay of an identical idempotent request admits once, while reuse with a conflicting body is refused.
- [ ] A request sent from outside the owner's network is admitted by the AWS worker and its mission id is readable from the status route.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

MO-40 already owns mission_request credential purpose/inbox kind; normal admission includes fresh prerequisites and exact binding seals.

Expose queued/admitted/refused and lifecycle states while admitting launch requests through existing handlers.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `interfaces/http/ingress.py`
- `application/signals/`
- `application/missions/admission.py (reuse)`
- `bootstrap/ (integrator-only)`

### Additional acceptance and negative cases

- [ ] 202 means queued only; status distinguishes typed admission/refusal and lifecycle; no fabricated accepted completion.
- [ ] Same request replay yields one admission, including drainer crash; body conflict, wrong scope and revoked/expired credential refuse.
- [ ] Admission rechecks current prerequisites/configuration; unsupported selection creates no provider session and no implicit lane/model fallback.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/prerequisites/test_preflight.py tests/unit/signals -q
- Future disposable PostgreSQL/Temporal launch fixture: assert inbox-to-normal-handler idempotency and stale prerequisite refusal; record exact module after implementation.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small acceptance refinement; existing implementation scope remains.
