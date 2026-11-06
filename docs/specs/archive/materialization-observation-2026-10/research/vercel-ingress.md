---
type: Research Note
title: "Signal Ingress on Vercel: design and hosting assessment (2026-10-12)"
description: "Vercel Python runtime facts, the owner's Vercel and Supabase state, ingress routes and authentication, migration 0035 signal-ingress tables and SECURITY DEFINER functions, IngressDrainer, gate latency, artifacts over 4.5 MB, project layout, hazards and phased hosting."
tags: [mission-control, research, materialization-observation]
---

# Signal Ingress on Vercel: design and hosting assessment

Read-only research and audit, 2026-10-12. Nothing was deployed, created or changed.
Decision context: DECISIONS R11 (deploy the public callback endpoints on Vercel with the
owner's Overton account; the rest of the API is reviewed in the plan pass) and D3.

Labels: **[V]** Vercel primary docs, **[S]** Supabase docs, **[R]** repo file, **[L]** live
read-only discovery (Vercel MCP / Supabase MCP), **[I]** inference or recommendation.

---

## 0. Findings that shape the design

| # | Finding | Source |
|---|---|---|
| F1 | Vercel team `Overton's projects` (`overtons-projects`, `team id redacted`) is the only team. It currently has **0 projects, 0 domains, 0 integration configurations** visible to the MCP token. The two `.vercel/project.json` files in `aiengineer/` point to project ids that now return 404 (deleted or another scope). | [L] list_teams, list_projects, list_domains, list_integration_configurations, get_project |
| F2 | The authenticated user's billing record shows plan **`hobby`**. Hobby is "restricted to non-commercial personal use only"; commercial use (financial gain of anyone involved, including paid contributors) requires Pro. Hobby caps function duration at 300 s and allows 1 WAF rate-limit rule per project. | [L] get_auth_user; [V] fair-use-guidelines, functions/limitations, waf/rate-limiting |
| F3 | Both application databases are Supabase, **region `us-east-1`**, Postgres 17: `biotech-research-ingestion` (`bxnetwiimwhtlrjlbtab`) and `supabase-blue-ocean` (`wkythqbofmckbuoothhn`, AI Engineer). Their Supabase organization slug is `vercel_icfg_…`, i.e. created through the Vercel Marketplace integration, but no integration configuration is visible from the MCP token (verify in dashboard). | [L] Supabase get_project; [R] deployments/{biotech,ai-engineer}/target.toml |
| F4 | Biotech's installation target uses the **direct host** `db.<ref>.supabase.co` (IPv6 unless the IPv4 add-on). Vercel Functions must use the **shared pooler** (IPv4 on every plan), **transaction mode port 6543** for serverless; transaction mode does not support prepared statements or pipelining. | [R] target.toml; [S] connecting-to-postgres |
| F5 | Live Supabase projects carry component release **1.0.0** only; 1.1.0 is "built and proven on scratch databases only"; the repo manifest is now **1.3.0** (migrations to 0034). Any ingress tables therefore require an owner-approved live migration chain. | [R] docs/MISSION_CONTROL_LOCAL_API.md lines 18-25; packages/mission-control-db-contract/component/manifest.json |
| F6 | Local development authority is a Docker `pgvector:pg16` on `127.0.0.1:55432` and local Temporal (`localhost:7233`). Neither is reachable from Vercel. `TEMPORAL_TARGET=cloud` exists in settings but Temporal Cloud is not provisioned. | [R] docker-compose.yml; bootstrap/settings.py 291-296; deployments/cloud_runtime/README.md |
| F7 | Existing deployment plan targets **AWS** (ECS/Fargate or one Lightsail host) for the API and workers, prepared but not deployed. No Vercel artifact exists for Mission Control. Knowledge Services has two Node Vercel apps (`apps/api`, `apps/mcp`) with `fluid: true`, `regions: ["iad1"]`, `maxDuration: 300`. | [R] deployments/cloud_runtime/*; expansion/DEPLOYMENT-AND-RELEASE.md; platform/knowledge-services/apps/*/vercel.json |
| F8 | The gate path is fully **database-decidable**: token digests (`hook_task_token`, with `context` jsonb carrying `disallowed_tools`), the Stop Fence (`stop_fence` keyed by run and generation) and the intent ledger (`hook_effect_intent`) are all Postgres tables. | [R] migrations 0029, 0030; application/execution/harness/hook_callbacks.py |
| F9 | `provider_frame` enforces `UNIQUE (harness_execution_id, generation, arrival_ordinal)`: frames have a **single writer per execution**. A public edge must not write frames directly; it needs an inbox drained by the worker. | [R] migration 0027 |
| F10 | `mc_stream_hint` already uses `pg_notify` triggers (0032) and the API LISTENs with asyncpg. The same pattern gives the worker a wake for ingress rows. LISTEN needs a session connection (direct or session pooler), not transaction mode. | [R] migration 0032; adapters/realtime/stream_hints_postgres.py; [S] |
| F11 | The full `mission_control` dependency closure includes `claude-agent-sdk`, `langgraph-api`, `langgraph-cli[inmem]`, `deepagents`, `temporalio`, `langsmith[pytest,sandbox]`, `cursor-sdk`. That is the wrong shape for a 500 MB Python function with fast cold starts. | [R] pyproject.toml; [V] functions/limitations |

---

## 1. Vercel platform facts (primary sources, read 2026-10-12)

| Topic | Fact | Source |
|---|---|---|
| Python runtime | Runs ASGI and WSGI apps. Framework presets detect FastAPI from `requirements.txt`, `pyproject.toml` or `Pipfile`. Entrypoints: `app.py`, `index.py`, `server.py`, `main.py`, `wsgi.py`, `asgi.py` (also under `src/` or `app/`), or `[tool.vercel] entrypoint = "pkg.module:app"`. The `/api` directory is supported for **existing** projects only. | vercel.com/docs/functions/runtimes/python |
| Versions | 3.12 (default), 3.13, 3.14; set via `requires-python`, `.python-version` or `Pipfile.lock`. | same |
| Dependencies | `pyproject.toml` (with or without `uv.lock`), `requirements.txt`, or Pipfile. uv is used with zero configuration (changelog). | same |
| Bundle | 500 MB uncompressed for Python, with no tree-shaking; Large Functions (beta) go up to 5 GB. Bytecode is precompiled automatically. Use `excludeFiles` to trim. | same; functions/limitations |
| Duration (Fluid) | Hobby: 300 s default and max. Pro/Enterprise: 300 s default, 800 s max, 1800 s beta. Overrun returns a 504 `FUNCTION_INVOCATION_TIMEOUT`. Streaming time counts. | functions/limitations |
| Memory | Hobby 2 GB / 1 vCPU. Pro 2 GB default, 4 GB / 2 vCPU max. | same |
| Body | **4.5 MB** maximum for both request and response body (413 `FUNCTION_PAYLOAD_TOO_LARGE`). Large payloads should use presigned URLs or Blob client uploads. | functions/limitations; kb how-to-bypass-vercel-body-size-limit |
| Fluid | Optimized in-function concurrency (Node.js and Python); `waitUntil` background work; automatic bytecode optimization and **pre-warming on production**; AZ then region failover; error isolation. Billing is active CPU plus provisioned memory time, and I/O wait is not active CPU. | fluid-compute; functions/limitations |
| Region | Default `iad1`; Pro can set multiple. `iad1` is co-located with Supabase `us-east-1`. | functions/limitations; [L] F3 |
| Streaming | Python streaming is supported, and on by default per changelog. | functions/streaming-functions; runtimes/python |
| WebSockets | **Beta, all plans.** python-socketio works over ASGI. Connections close at max duration, and new connections are not guaranteed to reach the same instance. Billed as function time. | functions/websockets |
| Deployment Protection | Standard Protection "protects all deployments except production domains". With it on, the production *generated deployment URL* becomes restricted. Automation bypass uses the `x-vercel-protection-bypass` header or query parameter. | deployment-protection; protection-bypass-automation |
| Env vars | Sensitive env vars exist for Preview and Production only and cannot be read back. `vercel env add … --no-sensitive` opts out. | environment-variables/sensitive-environment-variables; cli/env |
| WAF rate limit | Hobby: 1 rule per project, IP/JA4 keys, 10 s–10 min fixed window, 1M allowed requests included. Pro: 40 rules, then $0.50 per 1M. Header keys are Enterprise only. | vercel-firewall/vercel-waf/rate-limiting |
| Queues | **Beta, all plans.** Durable append-only topic, at-least-once delivery, push or poll ("run your own workers"), Python SDK `vercel-queue`. Poll is region-scoped, at most 10 messages per receive. Retention 60 s–7 d (default 24 h); visibility timeout up to 60 min. Metered in 4 KiB units; Hobby includes 1M operations. | queues; queues/poll-mode; queues/pricing |
| Cron / schedules | `crons` in vercel.json; dynamic schedules target Queue topics. | cron-jobs docs; doc search |
| DB pooling | `attachDatabasePool` (JS) releases idle clients before suspension. For Python, Supabase transaction mode is the documented serverless path. | functions-api-reference/vercel-functions-package; [S] |
| Blob | Private stores; client and presigned uploads stream directly to storage, bypassing the function. Python `vercel.blob.AsyncBlobClient` supports multipart. | vercel-blob/using-blob-sdk; vercel-blob/vercel-signed-urls |
| Static IPs | Pro/Enterprise shared egress IPs, configured per region. Needed only if Supabase network restrictions are enabled. | networking/static-ips |
| Trailing slash | `trailingSlash: true` 308-redirects. Keep it unset or false for webhook paths, because Anthropic auto-disables endpoints that return 3xx. | vercel.json docs; [R] research/anthropic-managed-agents.md:89 |
| AI Gateway | Anthropic-Messages-compatible `https://ai-gateway.vercel.sh/v1/messages` with BYOK. Gateway keys are not per-run minted credentials. | ai-gateway/authentication-and-byok/byok |

---

## 2. Architecture

```text
 Provider VMs / webhooks (public HTTPS only)
   │  run_token · Cursor OIDC JWT · env-key HMAC · standard-webhooks · GitHub HMAC · Cursor v0 HMAC
   ▼
 Vercel project "mc-ingress" (iad1, Fluid, Python 3.12, FastAPI)        ← stateless, no Temporal, no frames
   │  1 SQL round trip per request through a SECURITY DEFINER function
   ▼  Supavisor transaction mode :6543 (IPv4), login role mc_ingress_<app>
 Supabase Postgres (per app, us-east-1): mission_control.ingress_* tables (db-contract 0035)
   │  AFTER INSERT trigger → pg_notify('mc_ingress', {scope, ingress_id})
   ▼  LISTEN on a session connection + 5 s SKIP LOCKED poll fallback
 Mission Control worker (local WSL2 now; AWS later): IngressDrainer
   → FrameWriter (single writer: provider_frame source=ingress, kind signal.<type>)
   → Watcher Evaluator / coordinator inbox / outbox
   → Temporal signal or update to the owning operation workflow (local Temporal or Temporal Cloud)
   → lane reconcile-from-history for provider webhook wakes (never trust the payload)
```

Principles kept from AGENTS.md and the specs:

- Signals are evidence, and Temporal alone schedules. The edge never signals Temporal.
- Common SQL lives in `packages/mission-control-db-contract` (ADR-0003).
- No third authoritative store. Vercel Queues is not used as the mailbox (§5).

### 2.1 What goes on Vercel (phase 1)

Routes are **application-scoped**. This is an [I] amendment to SPEC-04 §3, whose paths name no app; app scoping matches the existing `/v1/applications/{app}/…` convention and selects the DSN without a lookup fan-out.

| Route | Purpose | Trust tier(s) | Reply |
|---|---|---|---|
| `POST /v1/ingress/{app}/signals` | single or batch `mc.signal.v1` | run_token, provider_oidc, environment_key | `202 {accepted, duplicates}` |
| `POST /v1/ingress/{app}/signals?gate=1` | **synchronous gate** (PreToolUse etc.) | run_token, provider_oidc (environment_key: `stop` honoured, `allow` never overrides local policy) | `200 {decision: allow\|deny\|stop, reason}` |
| `POST /v1/ingress/{app}/artifacts:prepare` | presigned upload slot (digest, size, media type) | run_token, provider_oidc | `200 {upload_url, expires_at, artifact_ref}` |
| `POST /v1/ingress/{app}/artifacts:commit` | declares upload done; worker verifies digest | run_token, provider_oidc | `202` |
| `POST /v1/ingress/{app}/provider/anthropic` | Managed Agents webhooks (wake only) | provider_signed (standard-webhooks, `whsec_`) | `204` fast, also on duplicate |
| `POST /v1/ingress/{app}/provider/openai` | Agents API webhooks `agent.session.*`, `agent.environment.*` | provider_signed (standard-webhooks) | `204` |
| `POST /v1/ingress/{app}/provider/cursor/{run_ref}` | Cursor v0 `statusChange` | provider_signed (`X-Webhook-Signature: sha256=` HMAC of raw body) | `204` |
| `POST /v1/ingress/{app}/github` | `check_suite`, `pull_request`, `push` | provider_signed (`X-Hub-Signature-256`) | `204` |
| `GET /health/live` | process only, no DB | none | `200` |
| `GET /health/ready` | per-app DB ping | bypass header or owner bearer | `200/503` |

The Model Gateway is **not** in phase 1 (§6). The loopback hook callback stays on the worker (`hook_callback.py`, cursor_local), and the ingress handler shares its application service per SPEC-04 §3.

### 2.2 Authentication (verification happens in the function; authority in SQL)

| Tier | Verification on Vercel | DB lookup |
|---|---|---|
| `run_token` | `Authorization: Bearer mcs1.<app>.<base64url 32 B>`. App segment must equal the path. `sha256:` digest. Constant-time compare not needed because lookup is by digest. | `ingress_credential` (kind `run_token`): unexpired, unrevoked, current generation, scope `signal:write`; binds run, unit, generation. |
| `provider_oidc` (Cursor) | JWT RS256. `iss=https://api.cursor.com`, JWKS `https://api.cursor.com/keys` cached in module scope (Fluid reuses instances; refresh on unknown `kid`, at most once a minute). `aud` = this ingress origin. `exp` ≤ 5 min plus 30 s skew. Claims `cloud_agent_id`/`sub`, `environment_id`. Uses `joserfc` (already a dependency). | `cloud_agent_id` → run through the lane/session binding (`native_session_ref`). Reject if unbound. |
| `environment_key` | `X-MC-Signature: v1=<hex HMAC-SHA256(key_env, ts + "." + raw_body)>`, `X-MC-Timestamp` within ±300 s. `key_env = HMAC(MC_ENV_KEY_MASTER, "<app>/<provider>/<environment_id>")` (a KDF, so Vercel stores one master instead of N keys; the Secret Broker derives the same key when it writes the environment secret). | `ingress_session_binding`: provider session id (`CLAUDE_CODE_REMOTE_SESSION_ID`) → run. Bound only by the first `session.started` carrying the run nonce digest from `.mission/run.json`. |
| `provider_signed` Anthropic / OpenAI | Standard Webhooks: `webhook-id`, `webhook-timestamp`, `webhook-signature: v1,<base64>`, HMAC-SHA256 over `id.timestamp.body` with base64-decoded `whsec_` secret. ±5 min tolerance. Dedupe on `webhook-id`. | none for auth; the payload's session id is resolved by the drainer. |
| `provider_signed` Cursor v0 | HMAC-SHA256(raw body) hex in `X-Webhook-Signature`. Secret per run: `HMAC(MC_CURSOR_WEBHOOK_MASTER, "<app>/<run_ref>")`, so the URL path carries `run_ref` and no table lookup is needed to verify. | none |
| `provider_signed` GitHub | `X-Hub-Signature-256: sha256=<hex>` with a per-app repo/app webhook secret. Dedupe on `X-GitHub-Delivery`. | none |

Raw body: handlers read `await request.body()` before parsing, with a hard cap enforced before the read completes: 256 KiB per signal call, 1 MiB per batch or webhook. The platform hard cap is 4.5 MB.

### 2.3 Persistence: db-contract migration `0035_signal_ingress.sql` (component 1.4.0)

Tables live in `mission_control` (common component), owned by `packages/mission-control-db-contract`:

- `ingress_credential` holds credentials by digest only, in a column `credential_hash` constrained to the `^sha256:` pattern. Other columns: `kind` (`run_token`), `run_id`, `unit_ref`, `generation`, `scopes`, `issued_at`, `expires_at`, `revoked_at`, plus per-credential rate counters `window_start` and `window_count`.
- `ingress_session_binding` maps `(provider, session_id)` to a run. It stores `nonce_hash` and `bound_at`, and is unique on `(provider, session_id)`.
- `ingress_inbox` holds the accepted messages. Columns:
  - `ingress_id` (uuid v7), `received_at`;
  - `app`, `tenant_id`, `run_id` (nullable for unresolved webhooks), `trust_tier`, `kind` (`signal.<type>`, `gate.decision`, `webhook.<provider>`, `artifact.committed`);
  - `credential_ref` (a digest ref, never the token), `dedupe_key` (unique per `(credential_ref, dedupe_key)`);
  - `body_sha256`, `payload jsonb` (redacted, size-checked), `seq` (the sender's per-session sequence);
  - `state` (`pending|drained|rejected|dead`), `attempts`, `drained_at`.
- `ingress_artifact_upload` tracks `artifact_ref`, the declared digest, size, `media_type`, `storage_key`, `expires_at` and `state`.
- An `AFTER INSERT` trigger on `ingress_inbox` calls `pg_notify('mc_ingress', json {scope, ingress_id})`, the same idiom as 0032.

Least privilege: one `NOLOGIN` role `mission_control_ingress`, granted only EXECUTE on SECURITY DEFINER functions (`SET search_path = pg_catalog`) and **no table grants**:

- `ingress_accept(app, credential_hash|binding, items jsonb) → accepted/duplicate counts`. It checks rate counters atomically.
- `ingress_gate(credential_hash, generation, effect_ref, effect_kind, tool, input_digest) → decision`. In one transaction it does the token check, the `stop_fence` read for `(run, generation)`, the `disallowed_tools` check from the token context, the `hook_effect_intent` insert **before** answering `allow`, and the `gate.decision` inbox row.
- `ingress_webhook(app, provider, delivery_id, body_sha256, payload) → accepted|duplicate`.
- `ingress_artifact_prepare(...)` and `ingress_artifact_commit(...)`.

There is one login role per installation (`mc_ingress_<app>`, member of `mission_control_ingress`). Its DSN uses the shared pooler in transaction mode on port 6543, with `prepare_threshold=None` (psycopg) or `statement_cache_size=0` (asyncpg). Each request is one function call, so there is one round trip and pooler semantics do not matter.

Run tokens: `mint:signal_token` (SPEC-01 §4) writes the digest row in the same transaction as the run's materialization receipt. The worker revokes on generation change or terminal state, which also revokes the token at the edge immediately.

### 2.4 How the worker picks rows up

A new `IngressDrainer` runs in the worker process role (one per application binding, as workers already are):

1. **Wake.** It holds `LISTEN mc_ingress` on a session connection: Biotech direct (IPv6 from WSL2 works today) or the AI Engineer session pooler on 5432. On every notify, and every 5 s as a fallback, it claims a batch with `SELECT … FROM ingress_inbox WHERE state='pending' ORDER BY received_at FOR UPDATE SKIP LOCKED LIMIT 100`.
2. **Map.** `signal.*` and `gate.decision` become `provider_frame` rows through `FrameWriter`. Ordering comes from the arrival ordinal per execution, and `provider_key` is `ingress:<credential_ref>:<dedupe_key>`, so a replay is a no-op under `provider_frame_dedupe_key`.
3. **React.**
   - Watchers and the coordinator inbox evaluate the new frames through the existing outbox loop.
   - `webhook.*` resolves provider session → run, then runs the lane's reconcile-from-history activity: webhook-as-wake, never trusting the payload (SPEC-06 §3).
   - `artifact.committed` starts a custody activity: download, verify digest, copy to Supabase custody (ADR-0024), delete quarantine.
4. **Wake Temporal.** The drainer signals or updates the owning operation workflow (for example `ingress_wake{run, generation, kinds}`) using the worker's own Temporal client, local now or Cloud later. The edge never holds Temporal credentials.
5. Each row is marked `drained`. After N failures it becomes `dead` and emits `watcher.failed`-style telemetry.

The latency from edge accept to worker is about 50–200 ms while LISTEN is connected, and at most 5 s under polling. The latency to a watcher action adds evaluator time only.

### 2.5 Synchronous gate latency budget

| Leg | Warm estimate [I] |
|---|---|
| Provider VM → Vercel edge → `iad1` function: TLS reuse not guaranteed from hook scripts | 20–80 ms |
| FastAPI parse, JWT or digest, policy mapping (`NativeHookMapper` pure Python) | 2–5 ms |
| One SQL call `ingress_gate` via Supavisor, `iad1` ↔ `us-east-1` | 3–15 ms |
| **Total warm** | **≈ 30–100 ms p50, target p99 ≤ 400 ms** |
| Cold start (slim closure, bytecode precompiled, production pre-warming) | +300–1200 ms, unmeasured |

Rules:

- The gate client timeout is 3 s (non-gate signals keep SPEC-04's 2 s).
- The client applies the lane's fail mode on timeout or 5xx: Claude `onFailure: "block"` and Cursor `failClosed` only where policy says so.
- Gate traffic counts against a per-credential limit inside `ingress_gate`, not the WAF, because Hobby/Pro WAF keys are IP or JA4 only.
- Measure in the cursor_cloud drill before declaring an SLO; DEPLOYMENT-AND-RELEASE forbids unmeasured SLOs.
- A `stop` answer is produced when a `stop_fence` row exists for (run, generation) or the credential is revoked.

### 2.6 Artifacts (above 4.5 MB)

| Option | How | Trade-off |
|---|---|---|
| **A (recommended): Supabase Storage quarantine bucket** | `artifacts:prepare` returns a Supabase signed upload URL for `mc-ingress-quarantine/<app>/<run>/<sha256>`. The client PUTs directly; `artifacts:commit` records it; the worker verifies and moves it into custody (ADR-0024 paths). | Keeps bytes inside the app's existing authority project; no new vendor store. The signing key is a Supabase secret key, which is broad, so restrict it to a dedicated bucket with RLS-free signing done in the function and rotate it. |
| B: Vercel Blob private store as quarantine | `handleUploadPresigned` / Python `AsyncBlobClient`; `BLOB_READ_WRITE_TOKEN` is scoped to one store. | Better least privilege at the edge, but a second byte store and egress cost; the worker needs the Blob token too. |

Small outputs (≤ 256 KiB) may ride inline in a signal as `artifact.ready` with a digest.

---

## 3. Project layout (proposed, not created)

```text
platform/mission-control/
  src/mission_control/
    application/ingress/          # pure: verifiers (oidc, standard-webhooks, hmac, kdf), policy mapping, schemas
    adapters/postgres/ingress.py  # calls the 0035 SECURITY DEFINER functions (psycopg, no prepare)
    interfaces/http/ingress.py    # FastAPI router; shared by the Vercel app and the loopback/local mount
    bootstrap/ingress.py          # create_ingress_app(IngressSettings) — slim composition root, no Temporal/LLM imports
  packages/mission-control-db-contract/component/migrations/0035_signal_ingress.sql
  deployments/ingress-vercel/
    app.py                        # from _vendor.mission_control.bootstrap.ingress import create_ingress_app; app = create_ingress_app()
    pyproject.toml                # requires-python ">=3.12,<3.13"; deps: fastapi, pydantic, pydantic-settings,
                                  #   psycopg[binary]==3.3.4, joserfc, httpx (JWKS) — nothing else
    uv.lock
    .python-version               # 3.12
    vercel.json
    scripts/vendor_closure.py     # copies the allowlisted mission_control subtrees into _vendor/ (build step)
    tests/test_import_closure.py  # fails if the closure imports temporalio, langchain*, deepagents, claude_agent_sdk, supabase, redis
```

The Vercel docs list `api/index.py` only for existing projects, so new projects should use the `app.py` (or `[tool.vercel] entrypoint`) form. ADR-0001 holds: the code lives in the one distribution and the deployment only vendors a checked import closure. To be verified on the first preview deploy: the Python preset honours `buildCommand`, and Root Directory `deployments/ingress-vercel` can read `../../src` ("include files outside root directory"). The fallback is to commit the vendored closure via `make ingress-vendor` with a CI drift check.

`vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "fluid": true,
  "regions": ["iad1"],
  "buildCommand": "python scripts/vendor_closure.py",
  "trailingSlash": false,
  "functions": {
    "app.py": { "maxDuration": 30, "excludeFiles": "{tests/**,scripts/**}" }
  },
  "headers": [
    { "source": "/(.*)", "headers": [
      { "key": "X-Content-Type-Options", "value": "nosniff" },
      { "key": "Referrer-Policy", "value": "no-referrer" },
      { "key": "Cache-Control", "value": "private, no-store" }
    ]}
  ]
}
```

### 3.1 Environment variables

All variables are Production scope only. Preview deployments get no production DSN or secrets.

| Name | Type | Notes |
|---|---|---|
| `MC_INGRESS_APPS` | plain | `biotech,ai-engineer` |
| `MC_INGRESS_INSTALLATION_BIOTECH`, `…_AI_ENGINEER` | plain | installation UUIDs from target.toml, checked in each SQL call |
| `MC_INGRESS_DB_URL_BIOTECH`, `…_AI_ENGINEER` | **sensitive** | `postgresql://mc_ingress_<app>.<ref>:<pw>@aws-…-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require` |
| `MC_INGRESS_PUBLIC_ORIGIN` | plain | `https://ingress.<domain>`; also the OIDC `aud` |
| `MC_CURSOR_OIDC_ISSUER`, `MC_CURSOR_JWKS_URL` | plain | `https://api.cursor.com`, `https://api.cursor.com/keys` |
| `MC_ENV_KEY_MASTER` | **sensitive** | KDF master for `environment_key`; the same value lives in the worker's Secret Broker |
| `MC_CURSOR_WEBHOOK_MASTER` | **sensitive** | KDF master for per-run Cursor v0 secrets |
| `MC_WEBHOOK_SECRET_ANTHROPIC_<APP>`, `…_OPENAI_<APP>`, `…_GITHUB_<APP>` | **sensitive** | `whsec_…` / OpenAI signing secret / GitHub secret |
| `MC_SUPABASE_URL_<APP>`, `MC_STORAGE_SIGNING_KEY_<APP>` (option A) or `BLOB_READ_WRITE_TOKEN` (option B) | **sensitive** | artifact presign only |
| `MC_INGRESS_MAX_SIGNAL_BYTES` (262144), `MC_INGRESS_MAX_BATCH_BYTES` (1048576) | plain | caps |

Do **not** connect the Supabase Marketplace resource to this project. Marketplace connection injects the project's privileged Postgres URLs, which bypass the restricted-role model. [I] Whether that integration is still installed could not be confirmed (F3).

---

## 4. Webhook-specific hazards

- **Anthropic** auto-disables an endpoint that returns 3xx or resolves to a non-public IP. It makes at most 3 attempts with 5–120 s backoff, then drops the event. Therefore: production custom domain, `trailingSlash: false`, exact path, no Deployment Protection on the production domain, and a fast 2xx even on duplicates. [R] research/anthropic-managed-agents.md:89,188
- **OpenAI** retries for 72 h and may duplicate. Dedupe on `webhook-id`. [R] research/openai-hosted-agents.md:156-161
- **Cursor** webhooks are v0-only; v1 says "coming soon". Interop between v0 and v1 is unverified (CD-20). [R] research/cursor.md:332-341
- **Deployment Protection:** Standard Protection leaves production domains public and protects previews. Never put the automation bypass secret into a provider URL; use it only for preview drills with the header form. [V]
- The production generated deployment URL becomes restricted under Standard Protection, so give providers the custom domain, not a per-deployment URL. [V]

---

## 5. Rejected alternatives

| Alternative | Why not |
|---|---|
| Vercel Queues as the ingress mailbox | It would be a third durable store beside Postgres and Temporal (violates "no third authoritative mission database"). It is beta, poll is region-bound, retention is ≤ 7 days, and the worker would need Vercel credentials. Gates need DB state anyway. Reconsider only as a buffer if DB outages at the edge prove material. |
| Vercel function signals Temporal directly | Puts Temporal Cloud credentials at the public edge, bypasses the outbox (ADR-0004), and the local Temporal is unreachable anyway. |
| Vercel writes `provider_frame` directly | Breaks the single-writer arrival ordinal (F9). |
| Deploy the full `mission_control` package | Dependency closure (F11) blows the bundle and cold start, and needs Temporal and installation checks at startup. |
| Tunnel only (Cloudflare/Tailscale) | Still valid for **local-Docker-DB** drills (F6), but superseded for Supabase-backed runs by R11. |

Note on local-only installs: Vercel can only reach a run whose authority DB is Supabase. Runs on the local Docker Postgres keep the SPEC-04 tunnel path. A later "relay mode", where the worker mirrors token digests and fences to Supabase and pulls inbox rows, is possible but not recommended now.

---

## 6. What else can live on Vercel

| Surface | Verdict | Reason |
|---|---|---|
| Signal Ingress (§2) | **Phase 1** | Short, stateless, DB-decidable, co-located with Supabase. |
| Model Gateway (SPEC-06 §2) | **Phase 2, Pro only, data_class ≤ internal** | Streaming works and Pro allows 800 s. However: Hobby's 300 s cap and commercial terms rule it out; long thinking/output streams can approach the cap; the org Anthropic key would live in Vercel env; all prompt bytes traverse Vercel (PHI never); memory-time is billed while streaming. Vercel AI Gateway BYOK cannot bind per-run minted tokens, so it is not a substitute. Alternative: run it on the worker or AWS host. |
| Coordinator inbox read/ack, W1 HTTP long-poll `GET …/inbox?wait=` (≤ 55 s), authenticated MCP **stateless** read tools | **Phase 2 candidate** | DB-only. Long-poll costs provisioned memory, and LISTEN is impossible through transaction mode, so it is poll-backed. Needs the slim closure and JWT verification (JWKS pinned file → env). |
| Operator API `bootstrap.api:create_app` (missions, runs, commands, human tasks) | **Phase 3, conditional** | Only after Temporal Cloud exists (submitter), a slim dependency closure, startup installation and release verification made cheap or cached per instance, and pools that are transaction-pooler-safe. AWS remains the documented target (cloud_runtime). |
| Socket.IO `/missions` stream, SSE transcript follow | **No** | WebSockets are beta, connections drop at max duration, there is no instance affinity, and LISTEN hints need persistent session connections; Redis fan-out plus reconnect churn every ≤ 300/800 s. |
| Temporal workers, IngressDrainer, outbox/subscription relays, reconcilers, watcher evaluator | **No** | Long-lived pollers and LISTEN loops; Temporal requires persistent workers. |
| Lanes (Claude Agent SDK CLI, Codex app-server, Cursor bridge), Sandbox Host, Agent Server | **No** | Subprocesses, stdio bridges, durable sessions, heavy binaries. |
| Stateful MCP sessions, `mission_subscribe` | **No** | Sessions pin to instances. SPEC-04 already recommends deprecating it. |
| Loopback hook callback | **No (by design)** | Must stay on the worker's `127.0.0.1` listener. |

---

## 7. Phased recommendation

1. **P0 — owner decisions:**
   - Plan: Hobby (non-commercial only, 300 s, 1 WAF rule) or Pro (commercial, 800 s, 40 rules, Static IPs).
   - Domain: a custom subdomain, for example `ingress.<owned-domain>` (the team has none today).
   - Artifact option A or B.
2. **P1 — db-contract:**
   - Write `0035_signal_ingress.sql` as release 1.4.0.
   - Prove it on scratch PostgreSQL 17.
   - Owner-approved live apply of 1.1→1.4 to both Supabase projects (F5).
   - Create the `mc_ingress_<app>` logins.
3. **P1 — code:**
   - `application/ingress`, `adapters/postgres/ingress.py`, the ingress router and `bootstrap/ingress.py`.
   - `IngressDrainer` in the worker.
   - Mint, revoke and KDF in the Secret Broker.
   - `.mission/hooks/signal` gate client.
   - Conformance tests for each tier, including rejection cases (SPEC-04 §8).
   - Import-closure test.
4. **P1 — Vercel (owner-run; Claude must not deploy):**
   - Import the repo.
   - Root Directory `deployments/ingress-vercel`.
   - Region `iad1`, Fluid on.
   - Production env vars (sensitive).
   - Custom domain.
   - Standard Protection (previews protected).
   - One WAF rule `/v1/ingress/*` IP ≤ 600 req/min.
   - Preview drill with the bypass header, then promote.
5. **P1 — providers:**
   - MA2 Anthropic Console webhook.
   - OA2 OpenAI webhook.
   - GitHub webhook per repo.
   - Cursor v0 webhook URL plus derived secret per launch.
   - Add the ingress host to every environment kit's egress allowlist (SPEC-01 §5).
   - Run the SPEC-04 §8 drills, including gate `stop` within one tool call, and record gate p50/p99.
6. **P2:** read-only inbox, long-poll and MCP read tools. Model Gateway on Pro if the drills justify it.
7. **P3:** reassess the operator API on Vercel versus AWS after Temporal Cloud. Workers and streams stay off Vercel.

---

## 8. Open verification items

- V1: Python preset support for `buildCommand` and outside-root source access in a monorepo root directory.
- V2: measured cold start of the slim closure.
- V3: whether the Supabase–Vercel Marketplace integration is installed under another scope (F3), and whether the team's plan differs from the user record's `hobby`.
- V4: Supabase signed upload URL lifetime and size limits for option A.
- V5: Cursor v0 webhook retry policy.
- V6: Claude Code `http` hook timeout semantics versus command hooks for gates.
- V7: Fluid in-function concurrency for Python is noted as beta in the changelog; confirm before relying on it.

## Sources

Vercel:
- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/functions/limitations
- https://vercel.com/docs/fluid-compute
- https://vercel.com/docs/functions/streaming-functions
- https://vercel.com/docs/functions/websockets
- https://vercel.com/docs/deployment-protection
- https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/protection-bypass-automation
- https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting
- https://vercel.com/docs/queues
- https://vercel.com/docs/queues/poll-mode
- https://vercel.com/docs/queues/pricing
- https://vercel.com/docs/functions/functions-api-reference/vercel-functions-package
- https://vercel.com/docs/vercel-blob/using-blob-sdk
- https://vercel.com/docs/vercel-blob/vercel-signed-urls
- https://vercel.com/kb/guide/how-to-bypass-vercel-body-size-limit-serverless-functions
- https://vercel.com/docs/limits/fair-use-guidelines
- https://vercel.com/docs/environment-variables/sensitive-environment-variables
- https://vercel.com/docs/networking/static-ips
- https://vercel.com/docs/ai-gateway/authentication-and-byok/byok

Supabase:
- https://supabase.com/docs/guides/database/connecting-to-postgres

Repo:
- AGENTS.md
- SPEC-01 §4, SPEC-04 §3/§6/§8, SPEC-06 §2/§3/§4.2/§5.2/§10, DECISIONS R11/D3
- research/{cursor,anthropic-managed-agents,openai-hosted-agents}.md
- interfaces/http/hook_callback.py, application/execution/harness/hook_callbacks.py
- migrations 0027/0029/0030/0032, component/manifest.json
- bootstrap/settings.py, docker-compose.yml, deployments/{cloud_runtime,biotech,ai-engineer}
- docs/MISSION_CONTROL_LOCAL_API.md, expansion/DEPLOYMENT-AND-RELEASE.md
- platform/knowledge-services/apps/{api,mcp}/vercel.json

Live discovery (read-only): Vercel list_teams, get_team, get_auth_user, list_projects, get_project, list_domains, list_integration_configurations; Supabase get_project ×2.
