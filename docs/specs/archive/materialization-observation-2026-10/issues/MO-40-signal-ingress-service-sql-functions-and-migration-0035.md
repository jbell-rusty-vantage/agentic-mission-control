# [MO-40] Signal Ingress service, SQL functions and migration 0035

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** L  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-11  
**Specification:** [SPEC-10-ingress-on-vercel.md](../SPEC-10-ingress-on-vercel.md)

## Problem

No authenticated public ingress; cloud lanes are blind beyond provider APIs (gap G6).

## Work

- Migration 0035 (component 1.4.0): ingress_credential, ingress_session_binding, ingress_inbox (+ pg_notify trigger), ingress_artifact_upload; NOLOGIN role with EXECUTE-only SECURITY DEFINER functions ingress_accept, ingress_gate (intent before allow), ingress_webhook, ingress_artifact_prepare/commit.
- Application ingress service and HTTP router for /v1/ingress/{app}/… with tiers run_token, Cursor OIDC (JWKS), standard-webhooks/HMAC, environment-key HMAC with session binding; derived secrets.
- Unify the loopback hook callback onto the same handlers.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `application/signals/`
- `adapters/postgres/ingress.py`
- `interfaces/http/ingress.py`
- `packages/mission-control-db-contract/component/migrations/0035_signal_ingress.sql`
- `interfaces/http/hook_callback.py`

## Acceptance

- [ ] Per-tier accept/reject, dedupe, size and rate tests; real PostgreSQL tests for every SQL function including gate ordering and token revocation.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
