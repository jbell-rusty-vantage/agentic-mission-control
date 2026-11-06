---
type: Reference
title: "Sprint OC environments and databases: which system, which database, which env file and variable"
description: "One map of every database/graph/service Sprint OC touches, which BellLabs .env file and variable points at it, which generated runtime env file each Mission Control process loads, and the Biotech ES256 signing-key procedure. Names and hosts only; no values."
date: 2026-10-28
status: active
---

# Environments and databases (Sprint OC)

Values never appear here. Hosts were read from the files on 2026-10-28 by name and host only.
Companion: [RUNTIME-ENVIRONMENT](RUNTIME-ENVIRONMENT.md) (process/port detail and the generator),
[HANDOFF](../../../archive/provider-consolidation-2026-10/docs/HANDOFF-2026-10-28.md).

## 1. The systems (what is what)

| Plain name | System | Identity | Holds (after the W0 install) | Sprint OC role |
| --- | --- | --- | --- | --- |
| **Biotech Mission Control database** | Supabase project `biotech-research-ingestion` (Pro, Vercel-managed org "Overton's projects") | ref `bxnetwiimwhtlrjlbtab`, host `db.bxnetwiimwhtlrjlbtab.supabase.co`, MC installation `01a103c0-9a9e-7a95-961b-29dda83c842b` | `mission_control`, `mission_control_search` (MC common 1.7.0), `knowledge_verification` (KS component 2.5.0), Storage bucket `capability-bundles`; `mission_control_runtime` (LangGraph saver) still to create. **No Biotech domain tables here** — the Biotech domain lives in the graph. | Disposable W0–W5 target |
| **Biotech knowledge graph** | Neo4j Aura "Biotech KG" | host `8032ec07.databases.neo4j.io` (pinned in `deployments/biotech/graph.toml`) | BKS graph schema `biotech-schema-v2.2.0` (empty of content) | Disposable W0–W5 target |
| **AI Engineer Mission Control + knowledge database** | Supabase project `supabase-blue-ocean` (same org) | ref `wkythqbofmckbuoothhn`, pooler host `aws-1-us-east-1.pooler.supabase.com`, login `postgres.wkythqbofmckbuoothhn`, MC installation `01a103c0-9a9e-70f3-9398-eb1573a98324` | MC common 1.7.0 schemas, KS `knowledge_service` + `knowledge_verification` 2.5.0, **the 18 AIDB domain schemas** (api, content, corpus, curriculum, evaluation, evidence, knowledge, observability, orchestration, provenance, ranking, research, research_private, retrieval, staging, taxonomy, temporal, util) plus AIDB tables in `public` (AIDB contract head `20261025010200`); Storage (`capability-bundles` + 8 legacy buckets with 34,773 unreferenced objects) | Disposable W0–W5 target |
| AI Engineer knowledge graph | Neo4j Aura | host `4773dc72.databases.neo4j.io` | AI Engineer apps' graph | **Not a Sprint OC target. Never wipe or write.** |
| Sprint test database | Docker `sprint-v-pg17` (PostgreSQL 17) | `127.0.0.1:55433`, superuser from the container env (`POSTGRES_USER=sprintv`) | per-test disposable databases | Every local proof, `mission-db release-build` |
| Owner local application DB | Docker/local Postgres | `127.0.0.1:55432` | owner's local data (not running on 2026-10-28) | Not used by Sprint OC |
| Temporal | local dev server / Python SDK test server | `127.0.0.1:7233` (dev), `7341` (test server) | workflow histories | W1 runtime (dev), integration tests (test server) |
| Agent Server | local LangGraph Agent Server | `127.0.0.1:2024` (`TOY_AGENT_SERVER_URL`) | runtime persistence | W1 runtime |
| Redis | local | `127.0.0.1:16379` (`REDIS_URL`) | stream fan-out | W1 runtime (local) |
| Other external services in owner `.env` files | MongoDB `biohack…`, Upstash Redis/Vector, LangSmith, Unstructured, third Aura `9c6755c0` (`NEO4J_AURA_QUERY_API`), Aura `e40f2c21` (agents_dashboard) | — | — | Not part of Sprint OC (LangSmith only for tracing) |

The Supabase org is a **Vercel Marketplace** organization (`vercel_icfg_SIEqFciu9zf7npelC0RqFUee`): open the
dashboard from Vercel (Storage/Integrations → Supabase → open), not via GitHub sign-in.

## 2. Owner `.env` files: which database each one points at

| File | Points at | Key names (all → that system) | Watch out |
| --- | --- | --- | --- |
| `platform/mission-control/.env` | **Biotech** Supabase + **Biotech** Aura | `DATABASE_DIRECT`, `DATABASE_URL`, `DIRECT_URL`, `SUPABASE_URL`, `SUPABASE_JWKS_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `NEO4J_URI`, `NEO4J_AURA_*`; model keys `ANTHROPIC_API_KEY`, `SECOND_ANTHROPIC_API_KEY` (independent auditor), `OPENAI_API_KEY`; `LANGSMITH_*` | `APPLICATION_DATABASE_DIRECT` / `APPLICATION_MIGRATION_DATABASE_DIRECT` → **local 55432**, not a Supabase project. `NEO4J_AURA_QUERY_API` → a different Aura (`9c6755c0`). MC itself layers this file under every process, so the generated runtime env blanks everything MC should not inherit (RUNTIME-ENVIRONMENT). Lacks `MISSION_CONTROL_APPLICATION`; its `TEMPORAL_TASK_QUEUE` differs from the profiles. |
| `biotech/biotech-knowledge-services/.env` | **Biotech** Supabase + **Biotech** Aura | same names as MC's (`DATABASE_DIRECT`, `NEO4J_URI`, `NEO4J_AURA_USERNAME`, `NEO4J_AURA_PASSWORD`, …) | Same local-55432 `APPLICATION_*` and third-Aura caveats. |
| `aiengineer/.env` (and `aiengineer/{agents_dashboard,internal,research_starter_pre_research_agent,ai-engineer-industry-cloud-automated-research}/.env`) | **AI Engineer** Supabase + **AI Engineer** Aura | `POSTGRES_URL_NON_POOLING` (admin, used by installers), `POSTGRES_URL`, `POSTGRES_PRISMA_URL`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET` (legacy HS256, **still trusted**: probe 2026-10-28 returned 200), `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `NEO4J_AURA_URI` (= `4773dc72`, not a target) | `agents_dashboard` also names Aura `e40f2c21`. |
| `platform/knowledge-services/.env` | **AI Engineer** Supabase + **AI Engineer** Aura | `POSTGRES_URL*`, `SUPABASE_URL`, `NEO4J_AURA_URI`, `KNOWLEDGE_API_URL` (local 4100) | **Never use it for Biotech.** The KS executor for Sprint OC takes its config from the generated `ks-executor.env`, not this file. |

Rule: **a database name in a `.env` key never tells you the project** (`DATABASE_DIRECT` is Biotech in the MC file;
`POSTGRES_URL_NON_POOLING` is AI Engineer). Trust the host/login project ref, which every installer and the generator check.

## 3. What each Sprint OC tool reads

| Tool / process | Reads | Target |
| --- | --- | --- |
| AIDB installer `aiengineer/ai-engineer-db-contract/scripts/install-ai-engineer.mjs` | `MC_AI_ENGINEER_MIGRATION_DATABASE_URL` (= `deployments/ai-engineer/target.toml` `database_url_env`), filled by runner from `aiengineer/.env` `POSTGRES_URL_NON_POOLING` + `sslmode=verify-full&sslrootcert=<Supabase CA>` | AI Engineer Supabase |
| BKS installer `biotech/biotech-knowledge-services/scripts/install-biotech.mjs` | `MC_BIOTECH_MIGRATION_DATABASE_URL` (from MC `.env` `DATABASE_DIRECT` + verify-full), `NEO4J_URI`, the Aura password via `--neo4j-password-env`, `BKS_TARGET=production`, and the generated `runtime/biotech/install.env` | Biotech Supabase + Biotech Aura |
| Runners (MC `.scratch/sprint-oc/runners/run_{aidb,bks}_{wipe,install}.py`) | load the above from the owner `.env` files into the child process only; assert host/login; scrub output | — |
| `mission-db` (MC `.venv/Scripts/mission-db.exe`) | admin DSN via `--admin-dsn-env NAME` (name only) | whichever DSN the name holds |
| Runtime env generator `scripts/sprint_oc_runtime_env.py` | owner `.env` files (MC, BKS, aiengineer), `deployments/<app>/*.toml`, install receipts / `--component-installation-id` | writes ignored files below |
| Bundle token mint `scripts/sprint_oc_mint_bundle_tokens.py` (branch `sprint-oc-w0-custody`) | `--secret-env-file aiengineer/.env --secret-env SUPABASE_JWT_SECRET` (AI Engineer), or the Biotech ES256 key (§5) | writes `runtime/<app>/bundle-custody.env` |
| Model probes `.scratch/sprint-oc/runners/model_probes.py` | MC `.env` `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | vendor APIs |

## 4. Generated runtime env files (ignored; `platform/mission-control/.scratch/sprint-oc/runtime/<app>/`)

| File | Loaded by | Contains (names) |
| --- | --- | --- |
| `install.env` | BKS installer `executor-config` step | `KS_KNOWLEDGE_BINDINGS_JSON`, `KS_BIOTECH_EXECUTOR_URL/TOKEN/READ_TOKEN`, `NEO4J_*`, `BKS_EXECUTOR_TOKENS`, `BKS_VERIFICATION_DSN`, `BKS_VERIFICATION_TENANTS` |
| `ks-executor.env` | KS `verification-executor serve` (one per app, ports 4310 ai-engineer / 4311 biotech) and the live-describe capture | issuer/audience, JWKS file, bindings JSON, component DSN, seal key |
| `bks-executor.env` | BKS executor (biotech, port 4020; firewall it) | Aura URI/user/password, executor tokens, verification DSN/tenant |
| `mission-control.env` | MC API and MC worker | application id, task queue, knowledge gateway, DSNs (runtime/family-writer/checkpointer — integrator logins still missing, so written as `.incomplete` + exit 3), reader bundle token, blanks for everything MC must not inherit |
| `agent-server.env` | Agent Server | as `mission-control.env` without `SUPABASE_URL`/bundle tokens (keeps Agent Server auth off) |
| `bundle-publisher.env` | `seeds_publish_bundles.py --env-file`, `register_supabase_skill_bundle.py --env-file` only | publisher bundle token, that app's `SUPABASE_URL` + publishable key |
| `bundle-custody.env` | generator input | minted publisher/reader tokens |
| `minted.env`, `knowledge-issuer.jwk.json`, `ks-seal.pem` | generator (reused across runs) | minted service tokens and keys |
| `manifest.json` | humans | which names were set, from where, and what is missing |

Also ignored: `runtime/supabase-prod-ca-2021.crt` (Supabase public root CA), `runtime/installation-ids.json`,
`evidence/preflight/{aidb,bks}-identity-evidence.json` (management-API identity, refresh before reuse),
`secrets/biotech/biotech-es256-signing-key.jwk.json` (§5).

## 5. Biotech ES256 signing key (owner steps)

> **Resolved 2026-10-28 by Option A.** The owner placed the Biotech legacy JWT secret in
> `.scratch/sprint-oc/secrets/biotech/legacy-jwt.env`; an HS256 reader token got Storage `200`. The prepared ES256 key was
> never imported and has been deleted. The dashboard offers only "Create standby key" (Supabase-held private key), which
> could not have worked. Credential consolidation going forward: BellLabs `docs/navigation/DATA-PLANES-AND-CREDENTIALS.md`.

**Why:** Mission Control uploads and reads skill/hook bundle bytes in each project's `capability-bundles` bucket
with two scoped JWTs (claim `mc_capability_role` = `publisher` or `reader`, `role=authenticated`); the service key is
never used. Both projects already sign with Supabase-generated ES256 keys whose private halves cannot be exported
(Biotech current kid `80f4bcd4-…`, AI Engineer `441971de-…`). AI Engineer still trusts its legacy HS256 secret, so
its tokens can be minted. Biotech needs signing material we hold. **Supabase only trusts a standby key after it is
rotated to current** (an imported standby key is published in JWKS but not accepted until rotation), and rotation
keeps the old key trusted as "previously used".

**Prepared for you:** an ES256 private JWK generated with the pinned Supabase CLI 2.115
(`supabase gen signing-key --algorithm ES256`), kid **`ec0f6038-b8d9-468c-b1b1-f57ab8f60245`**, at
`platform/mission-control/.scratch/sprint-oc/secrets/biotech/biotech-es256-signing-key.jwk.json`
(ignored, ACL = your user only).

**Option A (try first, no project change):** Vercel → Supabase → project **biotech-research-ingestion** →
Project Settings → **JWT Keys** → the **Legacy JWT Secret** tab. If a legacy secret is shown and it is not under
"Revoked", copy it into a new file `platform/mission-control/.scratch/sprint-oc/secrets/biotech/legacy-jwt.env` as one
line `SUPABASE_JWT_SECRET=<value>` and tell the session. The session probes it the same way it proved AI Engineer
(one read-only Storage list). If it works, you are done and the prepared ES256 key is not needed.

**Option B (if A is revoked or absent):**
1. Same page → **JWT Signing Keys** → create a new standby key by **importing** a private key; paste the full
   contents of `biotech-es256-signing-key.jwk.json` (one JSON object with `kty`, `crv`, `x`, `y`, `d`, `kid`).
   Keep the kid as is.
2. Click **Rotate keys** so the imported key becomes **Current**. The Supabase-generated key moves to
   "Previously used" and stays trusted; existing sessions are unaffected. State changes are throttled ~5 min.
3. Do **not** revoke the old key or the legacy secret (revoking the legacy secret requires disabling the `anon` and
   `service_role` keys).
4. Tell the session "Biotech key rotated". It mints tokens with `--es256-key-file`/`--kid`
   (the mint script currently takes a PEM; the session converts the JWK or adds a `--es256-jwk-file` option) and
   probes Storage before publishing.

After either option, the Biotech custody upload (`seeds_publish_bundles.py --target biotech --storage supabase
--env-file …/biotech/bundle-publisher.env`, twice) clears the H2 blocker on OVE-168.
