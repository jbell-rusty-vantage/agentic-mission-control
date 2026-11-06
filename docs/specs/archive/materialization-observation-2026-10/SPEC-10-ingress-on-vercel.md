---
type: Specification
title: "SPEC-10: Signal Ingress on Vercel — routes, authentication, database functions, drainer, artifacts and deployment"
description: "A thin Python ingress on Vercel that verifies callers and records signals, gates, webhooks and artifact uploads through least-privilege SECURITY DEFINER functions in the application's Supabase Postgres, drained by a worker-side IngressDrainer that writes frames and wakes Temporal; plus what must stay off Vercel."
tags: [mission-control, specifications, ingress, vercel, deployment, observation]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: per-route tests, import-closure test and real local PostgreSQL SQL tests (done, MO-40). Carried forward: **Drill S1** deployed clauses (ordered signals, gate p99, one-tool stop, >4.5 MB upload) with the next deployment session. Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-10: Signal Ingress on Vercel

This spec implements SPEC-04 §3, under owner decision R11 (Vercel, Overton account).

Evidence: [research/vercel-ingress.md](research/vercel-ingress.md). It covers the platform facts, the owner's account state, and the full migration and function sketch.

## 1. Principle

**Vercel verifies callers and records what they sent; it decides nothing beyond a gate answer computed in SQL.**

- The edge holds no Temporal credentials and writes no provider frames.
- One round trip to Postgres per request.
- The worker turns inbox rows into frames, watcher input, reconciliation, admissions (launch requests) and Temporal wake-ups. From slice R, that worker is the AWS ECS Fargate service (SPEC-11).

## 2. Routes (phase 1)

These are per-application routes, matching the existing `/v1/applications/{app}/…` convention. They supersede the SPEC-04 §3 paths.

| Route | Authentication | Reply | Notes |
| --- | --- | --- | --- |
| `POST /v1/ingress/{app}/signals` | Run token (digest lookup), Cursor OIDC JWT (published keys at `https://api.cursor.com/keys`, `aud` = ingress host), environment-key HMAC | 202 | Batched; dedupe on `(credential_ref, dedupe_key)`; size-capped |
| `POST /v1/ingress/{app}/signals?gate=1` | Run token or Cursor OIDC only | 200 `{decision: allow\|deny\|stop, reason}` | Synchronous, computed by `ingress_gate()` in SQL |
| `POST /v1/ingress/{app}/missions:request` (R29, MO-79) | Minted operator launch credential (`ingress_credential` purpose `mission_request`) | 202 `{request_id}` | Writes an inbox row of kind `mission_request` (manifest reference, inputs digest, idempotency key). The IngressDrainer admits it through the same application handler as the API. |
| `GET /v1/ingress/{app}/missions:request/{id}` | Same credential | 200 `{state, mission_id?, lifecycle?}` | Read-only SQL view: queued, admitted or refused (typed reason), then the mission's lifecycle state |
| `POST /v1/ingress/{app}/artifacts:prepare` and `artifacts:commit` | Run token or Cursor OIDC | prepare → signed upload URL; commit → 202 | Bodies over 4.5 MB never cross Vercel. Uploads go to a Supabase Storage **quarantine** bucket; the worker verifies the digest and moves the file into custody. |
| `POST /v1/ingress/{app}/provider/anthropic` and `…/provider/openai` | Standard Webhooks signature (`webhook-id`, `webhook-timestamp`, `webhook-signature`) | 204 (also for duplicates) | Wake-ups only |
| `POST /v1/ingress/{app}/provider/cursor/{run_ref}` | Cursor v0 webhook HMAC with a per-run derived secret | 204 | `statusChange` |
| `POST /v1/ingress/{app}/github` | GitHub HMAC (`X-Hub-Signature-256`) | 204 | Checks, PRs and pushes for watchers |

**Derived secrets.** Environment keys and Cursor webhook secrets are derived as `HMAC(master, purpose‖id)`, so Vercel stores one master secret per purpose rather than per-environment keys.

## 3. Database (db-contract migration `0035_signal_ingress.sql`, component 1.4.0)

All in the `mission_control` common component, owned by `packages/mission-control-db-contract`.

**Tables:**

- `ingress_credential`: digest-only run tokens with scope, run, unit, generation, expiry, revocation and rate-window counters.
- `ingress_session_binding`: unique `(provider, session_id) → run`, stored with a nonce hash.
- `ingress_inbox`: append-only accepted messages. Key columns are `trust_tier`, `kind`, `credential_ref`, the dedupe key, the body digest, the redacted payload, `seq`, and `state` (`pending`, `drained`, `rejected` or `dead`).
- `ingress_artifact_upload`.

**Trigger.** `AFTER INSERT` on the inbox calls `pg_notify('mc_ingress', …)`.

**Least privilege.**

- A `NOLOGIN` role `mission_control_ingress` with **no table grants**. It may only EXECUTE these SECURITY DEFINER functions (`search_path = pg_catalog`):
  - `ingress_accept`;
  - `ingress_gate`: in one transaction it checks the token, reads the stop fence, checks disallowed tools, inserts the Operation Intent *before* answering `allow`, and writes the decision row;
  - `ingress_webhook`;
  - `ingress_artifact_prepare` and `ingress_artifact_commit`.
- One login role per installation, `mc_ingress_<app>`, connecting through the **Supabase shared pooler in transaction mode (port 6543)** with prepared statements off.

**Token lifecycle.** Run tokens are minted in the same transaction as the materialization receipt (SPEC-01 §4). They are revoked on a generation change or a terminal state, so revocation takes effect at the edge immediately.

## 4. IngressDrainer (worker role)

1. Hold `LISTEN mc_ingress` on a session connection (direct host, or the session pooler on 5432), with a 5 s polling fallback.
2. Claim a batch with `FOR UPDATE SKIP LOCKED LIMIT 100`.
3. Map rows:
   - `signal.*` and `gate.decision` become provider frames through the existing `FrameWriter`, with `provider_key = ingress:<credential_ref>:<dedupe_key>`, so a replay is a no-op;
   - `webhook.*` resolves the provider session to its run, then runs the lane's reconcile-from-history activity;
   - `artifact.committed` starts the custody activity.
4. Signal the owning operation workflow (`ingress_wake`) with the worker's own Temporal client.
5. Mark the row drained. After N failures it becomes `dead` and raises telemetry.

**Expected latency:** 50–200 ms from accept to frame while LISTEN is connected; at most 5 s under polling.

## 5. Gate latency budget

| Measure | Value | Notes |
| --- | --- | --- |
| Warm | about 30–100 ms | Vercel `iad1` next to Supabase us-east-1. Estimate; measured in drill S1. |
| Target p99 | 400 ms | — |
| Cold start | plus 0.3–1.2 s | — |
| Hook-side client timeout | 3 s | Fails closed only where the hook policy says so |

## 6. Project layout and deployment

```text
deployments/ingress-vercel/
  app.py                    # FastAPI app factory import (slim), Vercel entrypoint
  pyproject.toml, uv.lock   # fastapi, pydantic, psycopg[binary], joserfc, httpx only
  .python-version           # 3.12
  vercel.json               # fluid compute, regions ["iad1"], maxDuration 30, trailingSlash false
  scripts/vendor_closure.py # copies the slim ingress modules from src/mission_control
  tests/test_import_closure.py  # fails if the closure imports SDKs, Temporal, LangGraph, provider adapters
```

- **Code location.** The code lives in `src/mission_control/`: the application ingress service, the Postgres ingress adapter, the HTTP router and a slim app factory. The Vercel project vendors only that closure.
- **Environment variables.** Production only and marked sensitive:
  - the ingress DSN;
  - signing masters;
  - provider webhook secrets;
  - the Cursor JWKS URL and audience;
  - the storage bucket and service credentials for signed uploads.

  Preview deployments get no production DSN.
- **Webhook hazards.**
  - Trailing-slash redirects must be off: Anthropic disables endpoints that redirect.
  - Standard Deployment Protection leaves production public. Never put the bypass secret into provider URLs.
  - Do **not** connect the Supabase Marketplace integration to this project; it injects privileged URLs.
- **Rate limiting.** Done per credential inside `ingress_accept`/`ingress_gate`. Below Enterprise, the Vercel firewall rule is IP-based only.
- **Fallback.** Local Docker drills use an owner-approved tunnel to a locally served ingress, because Vercel cannot reach a local Postgres.

## 7. What stays off Vercel (and why)

| Component | Reason |
| --- | --- |
| Temporal workers, IngressDrainer, relays, reconcilers, Watcher Evaluator | Long-running loops with persistent connections |
| Socket.IO and SSE streams | WebSockets are beta and capped at max duration; `LISTEN` cannot pass the transaction pooler |
| Stateful MCP sessions | Tied to one instance |
| Lanes, SandboxHost, Agent Server | Subprocesses and heavy binaries; the full package is far beyond a lean function |
| Loopback hook callback | Must stay worker-local |
| Vercel Queues as the inbox | Would be a third durable store; beta; 7-day retention; gates need the database anyway |
| Signalling Temporal from the edge | Bypasses the outbox and puts Temporal credentials at the public edge |

## 8. Later phases (not this sprint)

- **Phase 2:**
  - Coordinator inbox read and acknowledge.
  - Long-polls of 55 s or less.
  - Stateless MCP read tools.
- **Phase 3:** the operator API, once Temporal Cloud is live, a slim code closure exists and startup verification is cheap.

The **Model Gateway routes moved into this sprint** (R16, R17):

- Docker sandboxes use the worker-host placement through `host.docker.internal`.
- Daytona sandboxes use the routes in this Vercel project. The `*.vercel.app` host is on Daytona's essential-services list, so no Tier 3 allowlist and no tunnel are needed.
- Constraints and env vars are in SPEC-06 §12.2: Pro only, `internal` data class or lower, 800 s streams, and the 4.5 MB request cap.

## 9. Owner steps

1. ✅ Vercel plan: **Pro**, team `overtons-projects` (R17). The CLI's current scope is another team, so every command passes `--scope overtons-projects`.
2. ✅ Host: the project's production `*.vercel.app` domain. No custom subdomain, because Daytona Tier 1/2 sandboxes can reach only `*.vercel.app` (R16).
3. Quarantine store: Supabase Storage (default, chosen by the integrator unless the owner objects).
4. ✅ Live Supabase migration approved (R18): 1.3.0 applied with the checkpoint; 1.4.0 and the ingress login role pre-approved after local proofs.
5. Import the project with root `deployments/ingress-vercel`, region `iad1`, Production-only sensitive env vars, standard protection, one firewall rule.
6. Register webhooks: Anthropic Console, OpenAI, GitHub; Cursor is registered per launch automatically.
7. Add the ingress host to the Environment Kit egress lists. This happens automatically through `include_signal_ingress`.

## 10. Acceptance

- **Per route:** tier accept and reject tests, dedupe, size and rate limits, and forged or replayed webhook rejection (fixture deliveries).
- **The import-closure test passes**; the Vercel build is under the size limit.
- **Real local PostgreSQL tests** for every SQL function, including the gate's intent-before-allow ordering and token revocation.
- **Drill S1:**
  - Cursor cloud hooks deliver ordered signals through the deployed ingress.
  - The gate's measured p99 is recorded.
  - A stop takes effect within one tool call.
  - An artifact over 4.5 MB arrives through the signed upload and is verified into custody.

## Run 2 approved refinements (2026-10-14)

MO-74/75/79 retain PostgreSQL ingress_inbox, outbox, normal admission and worker-side reconciliation; there is no Vercel Queues replacement. Webhook interpretation is qualified to the bound product/API version/session. Duplicate/reordered/stale-generation webhook deliveries only wake reconciliation; they never grant approval, completion or a new mission. Prove crash-after-persist/before-wake idempotency and queued/admitted/refused/applied distinctions. MO-76 verifies actual size/digest/scope before custody, including mismatch/replay/expired/cross-scope negatives. Bytes in a file are not automatically inline model context. Upload acknowledgement/path/provider done is not review or acceptance; publication is a separate admitted effect.

[Detailed approved rules and issue mapping](runs/RUN-2-PLANNING-AMENDMENTS.md). These refine remaining acceptance and grant no new execution, spending or deployment authority.
