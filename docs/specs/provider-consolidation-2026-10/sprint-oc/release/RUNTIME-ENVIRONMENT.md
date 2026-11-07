---
type: Implementation Evidence
title: "Sprint OC runtime environment: the local W1 process topology and every variable by name"
description: "WI-24 (OVE-168) composition of the runtime the W0 install's executor-config step checks and the first paid W1 run (OVE-169) uses: which processes run where, every environment variable by NAME with its source (owner .env, installation-minted, install receipt or profile, integrator, blank, missing), owner .env isolation, the pinned Biotech graph, the real formats of KS_KNOWLEDGE_BINDINGS_JSON and BKS_EXECUTOR_TOKENS, and the generator scripts/sprint_oc_runtime_env.py. No values."
tags: [mission-control, knowledge-services, biotech, sprint-oc, wi-24, w0, w1, runtime, configuration]
status: active
date: 2026-10-28
---

# Sprint OC runtime environment (WI-24, W0 → W1)

This page lists names only and never values. It describes a **local** W1 topology. All processes run
on the owner's laptop on loopback ports. They talk to the two **remote disposable targets**
([IMPLEMENTATION §4.1](../IMPLEMENTATION.md)): the Supabase projects in `deployments/<app>/target.toml`
and the Biotech Aura graph pinned in `deployments/biotech/graph.toml`. Credentials are the names
already in the owner's `.env` files ([§4 item 7](../IMPLEMENTATION.md)). A missing value follows
[ESCALATION H2](../ESCALATION.md).

[`scripts/sprint_oc_runtime_env.py`](../../../../../scripts/sprint_oc_runtime_env.py) produces every
file this page names. It writes them under `.scratch/sprint-oc/runtime/<app>/`, which Git ignores. It
refuses to write a path that is not ignored or is tracked.

W0 used the generator to install Biotech, and the `executor-config` step verified. The review found
items to fix before W1; this revision makes those fixes. No W1 process has been started.

## 1. Processes and ports

| Process | Repository, start command (from that repository's root) | Listens | Env file |
| --- | --- | --- | --- |
| Temporal dev server | `temporal server start-dev` (or MC `make temporal-up`); register Search Attributes with `make temporal-search-attributes` | gRPC `127.0.0.1:7233`, UI 8233 (compose UI 8080) | none |
| KS executor (K01 host) | KS `node --env-file=<out>/ks-executor.env apps/verification-executor/dist/index.js serve` (after `pnpm build`) | `VERIFY_HOST:VERIFY_PORT`; ai-engineer **4310**, biotech **4311** | `ks-executor.env` |
| BKS executor (biotech only) | BKS `node --env-file=<out>/bks-executor.env apps/executor/dist/index.js` (after `pnpm build`) | `EXECUTOR_PORT` **4020**, on **all interfaces** (see the warning below) | `bks-executor.env` |
| MC API | MC `uv run --no-sync --env-file <out>/mission-control.env uvicorn mission_control.bootstrap.api:create_app --factory --loop mission_control.bootstrap.api:api_loop_factory --host 127.0.0.1 --port <port>` (the `--loop` factory runs a selector loop on Windows; without it time travel is unavailable, W1 D3) | ai-engineer **8000**, biotech **8001** (W1 sessions use **8010** for ai-engineer: 8000 is held by the owner's docling MCP server; operator bearers expire, re-mint them each session with `scripts/sprint_oc_deployment_file.py ... token`) | `mission-control.env` |
| MC worker | MC `uv run --no-sync --env-file <out>/mission-control.env python -m mission_control.bootstrap.worker` | no port (Temporal poller) | `mission-control.env` |
| Agent Server | MC `uv run --no-sync --env-file <out>/agent-server.env langgraph dev --config agent_server/langgraph.json --host 127.0.0.1 --port <port> --no-browser` | ai-engineer **2024**, biotech **2025** | `agent-server.env` (mission-control.env without the Supabase and custody names; see section 3) |

`biotech-graph` has a single "KS host": the verification executor. KS K01 runs inside it
(`packages/host/src/knowledge-operation`). No separate KS biotech-executor process exists. The BKS
executor is the graph side.

> **Warning: firewall BKS port 4020 for W1.** The BKS executor has no host setting and `serve()` binds no
> hostname, so it listens on every interface. Before W1 starts it, block inbound TCP 4020 from
> anything but loopback, for example:
>
> ```powershell
> New-NetFirewallRule -DisplayName "BKS executor 4020 loopback only" -Direction Inbound -Protocol TCP -LocalPort 4020 -RemoteAddress Any -Action Block
> ```
>
> Loopback traffic is not filtered. Its tokens are strong, but it must not be reachable from the
> network.

**Queue collision (resolved by namespace, OVE-169).** Both Application Profiles name the Temporal
queue `biotech-research-ingestion`. The operator deployment file
([`scripts/sprint_oc_deployment_file.py`](../../../../../scripts/sprint_oc_deployment_file.py))
gives each application its own namespace (default `mc-<app>`), and the generator copies it into
`TEMPORAL_NAMESPACE`; the API and worker connect to the deployment's namespace. Create each
namespace and register its Search Attributes before its worker starts
(`temporal operator namespace create --namespace mc-<app>`, then
`uv run --no-sync python scripts/register_belllabs_search_attributes.py` with
`TEMPORAL_NAMESPACE=mc-<app>`).

**Owner `.env` isolation.** MC settings always layer an owner `.env` beneath the process environment:
`env_file = <MISSION_CONTROL_HOME or cwd>/.env`. Any variable that is present in the process
environment wins, **even when it is empty**. Pointing `MISSION_CONTROL_HOME` at a directory with
no `.env` was rejected, because it also relocates `PROJECT_ROOT`, and with it:

- the capability-pin file;
- the hard-coded local bundle store `PROJECT_ROOT/.runtime/capability-bundles`;
- the preflight root;
- the default payload and workspace roots.

Instead, `mission-control.env` names **every** database, storage, bucket, vault and credential
setting that MC reads, and nothing is inherited:

- **Explicit value:** what this topology uses.
- **Explicit blank** (`NAME=`): what this topology must not inherit. These consumers treat an empty
  value as unconfigured and fail closed.
- **Missing required name:** also written as a blank, with a `# MISSING` comment.

The blanked names are `DATABASE_DIRECT`, `DATABASE_URL`, `APPLICATION_DATABASE_URL`,
`APPLICATION_MIGRATION_DATABASE_DIRECT`, `APPLICATION_BACKFILL_DATABASE_DIRECT`, `SUPABASE_URL`,
`SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`,
`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `INGRESS_QUARANTINE_BUCKET`,
`INGRESS_CUSTODY_BUCKET`, `INGRESS_STORAGE_CREDENTIAL`, `INGRESS_LISTEN_SECRET_REF`,
`MISSION_CONTROL_SECRET_VAULT_DSN`, `CAPABILITY_BUNDLE_PUBLISHER_TOKEN`,
`CAPABILITY_BUNDLE_READER_TOKEN`, `INSPECTION_CURSOR_KEY`, `BELL_LABS_TRACE_PSEUDONYM_KEY`,
`BELL_LABS_AGENT_AUTH_PUBLIC_KEY`, `TEMPORAL_CLOUD_API_KEY` and `CURSOR_API_KEY`.

When `bundle-custody.env` exists (see "Bundle custody" in section 3), the **reader** token,
`CAPABILITY_BUNDLE_NAMESPACE`, `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are written from it
and from the application's own project instead of being blanked. The publisher token is never in a
runtime file; it goes only to the operator file `bundle-publisher.env`.

The same blank treatment covers `str | None` settings whose readers treat a blank as unset:
`COORDINATOR_MCP_JWT_ISSUER`, `LANGSMITH_WORKSPACE_ID`, `CAPABILITY_BUNDLE_NAMESPACE`,
`TEMPORAL_BUILD_ID`, `KNOWLEDGE_ISSUER_RETIRING_KEY_ID` and `MISSION_CONTROL_PAYLOAD_SHARED_ID`.

MC settings treat a blank secret as unset. A model validator, `_blank_secrets_are_unset`, stores
every optional `SecretStr` that is present but blank as `None`, so each reader's `is not None`
check holds. Readers that rely on this:

- `bootstrap/lanes.py` and the `deployment_composition.py` Cursor sites: a blank `CURSOR_API_KEY`
  binds and composes no Cursor lane;
- `bundle_custody.py`: a blank bundle reader or publisher token reads as absent;
- the Temporal Cloud key: blank is `requires TEMPORAL_CLOUD_API_KEY`;
- the model keys.

On top of that, `settings.configured()` is applied in the DSN properties,
`has_application_postgres`, the checkpoint DSN, the inspection cursor key and the Supabase Vault
DSN. A blank `APPLICATION_DATABASE_URL` is therefore not a configured database, so the Agent
Server's `http_app.py` does not try to build a DSN from it. `INGRESS_LISTEN_SECRET_REF` (a
`str`) and `INGRESS_STORAGE_CREDENTIAL` are read by truthiness. Unit tests blank each of these
settings.

Other settings are handled as follows:

- **Non-None defaults.** Every `str` or `Path` setting with a non-None default is written as that
  default (`MC_DEFAULTS`: `LANGSMITH_ENDPOINT`, `AWS_REGION`, `MISSION_CONTROL_SECRET_STORE=none`,
  …), so an owner `.env` cannot override it.
- **One Mission Control root.** `MISSION_CONTROL_HOME`, `MISSION_CONTROL_DEPLOYMENTS_ROOT`
  (`<root>/deployments`), `CAPABILITY_PINS_PATH` and the tracked `deployments/<app>` files all
  come from a single root: the script's own checkout, or `--mc-root`. **W1 runs from the
  canonical checkout** (`platform/mission-control`). A run from any other root, for example a
  worktree, records a manifest warning. The `.env` MC will layer, `<root>/.env`, is checked
  together with the owner MC `.env` for allowlisted names.
- **Web-research paths.** The three web-research module paths are written exactly as `Settings`
  would derive them from `MISSION_CONTROL_WORKSPACE_ROOT`. `WEB_RESEARCH_AGENT_BROWSER_NODE` is
  `node` on `PATH`; the generator refuses with `NODE_NOT_FOUND` if there is none.
- **The allowlist.** The remaining `str`/`Path` settings cannot be blanked: a blank `Path` reads
  as `.`, and some fields have a length check. They are listed in `MC_UNMANAGED`, each with its
  reason (lane off, no reader through `Settings`, operator file the W1 harness names, and so on).
  The generator refuses an owner MC `.env` that sets any of them
  (`OWNER_ENV_SETS_UNMANAGED:<NAMES>`). After editing the owner `.env`, rerun the generator.

`REDIS_URL` is set to the local compose default. `TEMPORAL_TASK_QUEUE`, `LANGSMITH_PROJECT` and
`AGENT_SERVER_LANGSMITH_PROJECT` come from the profile, so the owner `.env`'s differing queue
cannot win.

A unit test proves this against the real `Settings` loader. It:

1. writes a `.env` that poisons **every** `str`, `Path` and `SecretStr` field into the generated
   `MISSION_CONTROL_HOME`;
2. shows that the poison is read without the generated environment;
3. shows that, with the generated environment applied, exactly the `MC_UNMANAGED` fields still
   read it. No other field does, and there is no stale allowlist entry;
4. checks that every other field is set by the generated file, that each `MC_DEFAULTS` value
   equals the real default, and that `has_application_postgres` is `False`.

The `payloads/` and `workspaces/` directories get the same owner-only ACL as the secret files.
On Windows, the grant is inheritable by what is created inside them.

The BKS executor gets `BKS_NO_ENV_FILE=1`. The KS executor reads no `.env`.

## 2. Value sources

| Class | Meaning |
| --- | --- |
| owner | Copied from an existing owner `.env` name (H2), parsed by python-dotenv as MC's own loader parses it (quotes, escapes, interpolation). MC `.env` = `platform/mission-control/.env`, BKS `.env` = `biotech/biotech-knowledge-services/.env`, AIE `.env` = `aiengineer/.env` |
| minted | Minted once by the generator and reused from `minted.env` on every rerun. Tokens are `secrets.token_urlsafe(32)`. Ed25519 keys are written as files. The tenant is a UUIDv4 |
| derived | Taken from the install receipt or `installation-ids.json` (component installation id), from `deployments/<app>/target.toml` (MC installation id, project ref), from `application.toml` or `graph.toml`, or from a path |
| integrator | Supplied through `--integrator-env <ignored file>`, `--deployment-file`, `--confirm-graph` or `--allow-admin-verification-dsn` |
| blank | Written empty on purpose, so the owner `.env` cannot supply it (section 1) |
| constant | Fixed by this topology |

**DSNs.** Every remote PostgreSQL DSN is rewritten with `sslmode=verify-full&sslrootcert=<CA>`.
The CA is the Supabase public root,
`platform/mission-control/.scratch/sprint-oc/runtime/supabase-prod-ca-2021.crt` (ignored), or the
file given with `--ca-file`. The CA is always parsed as an X.509 PEM. node-pg treats `require` as
`verify-full` and fails without the CA; psycopg accepts the same parameters.

Each DSN must name the target project **exactly**, either as the direct host
`db.<project_ref>.supabase.co` or as a pooler login `<role>.<project_ref>` on
`*.pooler.supabase.com` (H3). A substring match does not count.

**Secret files.** These are written owner-only:

- `minted.env`, the private JWK and the seal PEM;
- every token-bearing env file: `ks-executor.env`, `bks-executor.env`, `install.env` and
  `mission-control.env`.

Each is created through `os.open(..., 0o600)` as a temporary sibling. On Windows,
`icacls /inheritance:r /grant:r <user>:F` runs before any byte is written. The file is then
renamed into place, and the result is verified: exactly one ACE, the current user's, none
inherited. A failed check refuses with `SECRET_FILE_PERMISSIONS`.

**Interrupted runs.** `minted.env`, which holds the issuer `kid`, is written before the key files. If
`minted.env` is lost while the JWK remains, the next run adopts the JWK's `kid`.

## 3. Matrix by process

### KS executor (`ks-executor.env`)

| Name | Source | Notes |
| --- | --- | --- |
| `VERIFY_HOST`, `VERIFY_PORT` | constant | `127.0.0.1`; 4310 / 4311 |
| `KS_KNOWLEDGE_ISSUER` | constant `mission-control.<app>` | Must equal MC `KNOWLEDGE_ISSUER`. A K01 `Name` (`^[a-z][a-z0-9_.-]{0,119}$`): never `/` (W1 D5; MC refuses it at configuration) |
| `KS_KNOWLEDGE_AUDIENCE` | constant `knowledge-services-executor.<app>` | Must equal MC `KNOWLEDGE_BINDING_AUDIENCE`; a K01 `Name` too |
| `KS_KNOWLEDGE_JWKS_FILE` | minted | `knowledge-issuer.jwks.json`: the public half of MC's issuer key. MC serves no JWKS endpoint, so the KS executor reads the file |
| `KS_KNOWLEDGE_BINDINGS_JSON` | derived | See the format below |
| `KS_BIOTECH_DB_COMPONENT_DSN` (biotech) | owner: MC `.env` `MC_BIOTECH_DB_ADMIN_DSN` | The binding's `databaseUrlEnv`. The login must be able to `SET ROLE knowledge_verification_writer/reader` |
| `KS_AIENG_DB_COMPONENT_DSN` (ai-engineer) | owner: AIE `.env` `AIENG_DB_ADMIN_DSN` | Required for `aiengineer-postgres` (startup throws without it) |
| `KS_AIENG_DB_RUNTIME_DSN` (ai-engineer) | owner: AIE `.env` `AIENG_DB_ADMIN_DSN` | The co-hosted knowledge database the AIDB native `knowledge.apply` port uses. Without it, apply answers `SCHEMA_UNSUPPORTED` |
| `KS_KNOWLEDGE_SEAL_KEY_ID`, `KS_KNOWLEDGE_SEAL_KEY_FILE` | minted | `ks-seal.pem`, Ed25519 PKCS#8. Without them `report.seal` refuses. The key id must also be registered (public half) in `knowledge_verification.seal_signing_key` by the root installer's `seal-key` step; until then `report.seal` refuses `CAPABILITY_UNAVAILABLE` / `seal_key_unregistered` naming the id (OVE-169 W1 D25) |
| `KS_KNOWLEDGE_SEAL_ISSUER` | constant `knowledge-services` | The descriptor `signingIssuer`; the installer registers the key under the same issuer |
| `KS_BIOTECH_EXECUTOR_URL` (biotech) | constant `http://127.0.0.1:4020` | |
| `KS_BIOTECH_EXECUTOR_TOKEN`, `KS_BIOTECH_EXECUTOR_READ_TOKEN` (biotech) | minted | Plaintext here. The BKS side holds only their SHA-256 |

Leave the scripted auditor unset (`KS_KNOWLEDGE_DISPOSABLE`, `KS_KNOWLEDGE_AUDITOR_SCRIPT_FILE`):
W1 needs a real independent auditor, and a scripted one is a W0 deterministic probe only. Also leave
unset every retired name (`VERIFY_JUDGE_MODEL`, `VERIFY_CROSS_FAMILY_JUDGE_MODEL`,
`VERIFY_PRINCIPAL_SALT`, `KNOWLEDGE_EVIDENCE_ORACLE`, `KNOWLEDGE_RECOVERY_CONFIG_JSON`,
`KNOWLEDGE_REPORT_ASSESSMENT_PINS_JSON`, `KNOWLEDGE_CONTENT_LINKS_ENABLED`,
`KNOWLEDGE_EVIDENCE_POLICY_*`); the executor refuses them at startup with
`EXECUTOR_RETIRED_CONFIGURATION`.

`KS_KNOWLEDGE_BINDINGS_JSON` is a JSON array of 1–16 strict objects (KS
`packages/host/src/knowledge-operation/config.ts`):

```json
[{"application":"biotech","binding":"biotech-graph","installationId":"<component installation id>",
  "databaseUrlEnv":"KS_BIOTECH_DB_COMPONENT_DSN","tenants":["<knowledge_verification tenant uuid>"]}]
```

- `application` matches `^[a-z][a-z0-9_.-]{0,119}$` and `binding` matches `^[a-z][a-z0-9-]{0,63}$`.
- `databaseUrlEnv` is the **name** of the variable that holds the DSN.
- The `installationId` of the biotech entry must equal the installer's `--component-installation-id`
  (`EXECUTOR_INSTALLATION_MISMATCH`). The ai-engineer entry is
  `{"application":"ai-engineer","binding":"aiengineer-postgres",...,"databaseUrlEnv":"KS_AIENG_DB_COMPONENT_DSN"}`
  and carries no `tenants`.
- MC's `KNOWLEDGE_COMPONENT_INSTALLATION_ID` carries the same component installation id (W1 D6): KS
  authorizes the K01 origin's `installationId` against this entry, so MC sends the component id, not
  its own `target.toml` installation id (the two are distinct identities by design).

### BKS executor (`bks-executor.env`, biotech)

| Name | Source | Notes |
| --- | --- | --- |
| `BKS_NO_ENV_FILE` | constant `1` | |
| `EXECUTOR_PORT` | constant `4020` | Firewall it (section 1) |
| `NEO4J_URI` | owner: MC `.env` `MC_BIOTECH_GRAPH_URI`, **only when confirmed** | See the graph rules below |
| `NEO4J_USERNAME`, `NEO4J_PASSWORD` | owner: MC `.env` `MC_BIOTECH_GRAPH_USERNAME`, `MC_BIOTECH_GRAPH_PASSWORD`, **only when confirmed** | |
| `BKS_TARGET` | constant `production`, only when confirmed | The executor exits with code 78 on an Aura URI unless `BKS_TARGET=production` |
| `BKS_EXECUTOR_TOKENS` | derived from the minted KS tokens and the tenant | See the format below |
| `BKS_VERIFICATION_DSN` | integrator `BKS_VERIFICATION_DSN`. Fallback: owner MC `.env` `MC_BIOTECH_DB_ADMIN_DSN` **only with `--allow-admin-verification-dsn`** (disposable W0) | A login that holds `knowledge_verification_outbox_worker`. It calls `claim_dispatches`, `acknowledge_dispatch`, `fail_dispatch` and `settle_dispatch`. Without either source the name is missing. The manifest records the choice as `choices.verificationDsn`: `integrator`, `admin-allowed (disposable W0)` or `missing` |
| `BKS_VERIFICATION_TENANTS` | minted tenant (or `--verification-tenant-id`) | Exactly one tenant UUID, with no prefix. The dispatch `tenantId` must equal both this value and the service principal's `tenantId` |

**Graph rules.**

- `deployments/biotech/graph.toml` pins the expected Aura instance `8032ec07` (host
  `8032ec07.databases.neo4j.io`) and refuses the AI Engineer Aura instance `4773dc72`.
- The generator refuses (`GRAPH_HOST_MISMATCH` / `GRAPH_HOST_REFUSED`) when the MC `.env`
  `MC_BIOTECH_GRAPH_URI` names any other host.
- It refuses (`GRAPH_CONFIRMATION_MISMATCH` / `GRAPH_HOST_REFUSED`) when `--confirm-graph` names
  anything but the pinned host.
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` and `BKS_TARGET` are written blank and listed as
  missing until `--confirm-graph 8032ec07.databases.neo4j.io` is given.
- `--confirm-graph` is refused for ai-engineer (`CONFIRM_GRAPH_NOT_APPLICABLE`).

The executor does not read `BKS_RUNS_DIR` (CLI only; custody is `BKS_RELEASE_RUNS_DIR`).
`BKS_VERIFICATION_DSN` and `BKS_VERIFICATION_TENANTS` must both be set, or the admission-dispatch
module is silently not mounted.

`BKS_EXECUTOR_TOKENS` is a JSON array (BKS `apps/executor/src/auth.ts`). The executor stores hashes
only:

```json
[{"tokenSha256":"<sha256 hex of KS_BIOTECH_EXECUTOR_TOKEN>","role":"writer","class":"service",
  "principalId":"ks-biotech-graph","installationId":"<component installation id>","applicationId":"biotech",
  "tenantId":"<tenant uuid>","grants":["admission.dispatch"]},
 {"tokenSha256":"<sha256 hex of KS_BIOTECH_EXECUTOR_READ_TOKEN>","role":"reader","class":"service",
  "principalId":"ks-biotech-graph-reader","installationId":"<component installation id>","applicationId":"biotech",
  "tenantId":"<tenant uuid>","grants":[]}]
```

A token authenticates to exactly one principal, and so to one `tenantId`. A second
`--verification-tenant-id` therefore refuses (`TENANT_MULTIPLE_UNSUPPORTED`) instead of producing
tokens that cannot serve the second tenant.

### Installer seal-key step (`install.env`, both apps)

`install-ai-engineer.mjs` and `install-biotech.mjs` run `seal-key` (OVE-169 W1 D25) after the
component grants: the KS CLI `knowledge-db seal-key` derives the public half of
`KS_KNOWLEDGE_SEAL_KEY_FILE` (never printed) and pins it under `KS_KNOWLEDGE_SEAL_KEY_ID` and
`KS_KNOWLEDGE_SEAL_ISSUER`. A repeat is `current`; another key under the same id refuses
`SEAL_KEY_CONFLICT`; `KS_KNOWLEDGE_SEAL_RETIRE_KEY_IDS` (or `--retire-seal-key-ids`, operator-set,
never generated) moves earlier ids to `retiring`. Flags `--seal-key-id/--seal-key-file/--seal-issuer`
override the names. With neither, the step is skipped. For ai-engineer, `install.env` holds exactly
these three names; for biotech they are part of the union below.

### Installer executor-config step (`install.env`, biotech)

`install-biotech.mjs` checks, by name in its own process, `KS_KNOWLEDGE_BINDINGS_JSON`,
`KS_BIOTECH_EXECUTOR_URL`, `KS_BIOTECH_EXECUTOR_TOKEN`, `KS_BIOTECH_EXECUTOR_READ_TOKEN`, `NEO4J_URI`,
`NEO4J_USERNAME`, `NEO4J_PASSWORD`, `BKS_EXECUTOR_TOKENS`, `BKS_VERIFICATION_DSN`,
`BKS_VERIFICATION_TENANTS` and the binding's `databaseUrlEnv`. `install.env` is the union of the
KS-executor and BKS-executor files. It is complete only with `--confirm-graph` and a verification
DSN choice.

In `--remote-reinstall` mode, the host of `NEO4J_URI` must equal the installer's
`--confirm-graph`. In disposable mode, the step refuses an Aura URI
(`EXECUTOR_TARGET_NOT_DISPOSABLE`).

### Mission Control API, worker and Agent Server (`mission-control.env`)

| Name | Source | Notes |
| --- | --- | --- |
| `MISSION_CONTROL_APPLICATION`, `MISSION_CONTROL_WORKER_APPLICATION_ID` | constant `<app>` | Selects `deployments/<app>/application.toml` and `models.toml`. A mismatch with the binding stops startup |
| `MISSION_CONTROL_DEPLOYMENTS_ROOT` | derived | This checkout's `deployments/` |
| `MISSION_CONTROL_WORKSPACE_ROOT` | derived | The profile's `capability_workspace_root` resolved against canonical MC: `BellLabs/biotech` |
| `MISSION_CONTROL_DEPLOYMENT_FILE`, `MISSION_CONTROL_WORKER_BINDING_DIGEST` | integrator `--deployment-file` | The operator `MissionDeployment` JSON written by `scripts/sprint_oc_deployment_file.py` (sealed binding with the target's `installation_id`, `project_ref`, `database_secret_ref = MC_<APP>_RUNTIME_DSN`, `family_writer_secret_ref = MC_<APP>_FAMILY_WRITER_DSN`, the installed component version; an operator EdDSA issuer `mission-control-operator/<app>` with its public JWKS; one operator grant on the minted tenant, including `knowledge.review` (W1 D2), and a second grant for the separate reviewer principal `sprint-oc-reviewer` / `reviewer:sprint-oc` (`knowledge.review`, `workflow_run.read`, `mission.read`; no launch). The launcher never reviews its own run's KS decision (`unauthorized_review`), so W1 reviews with `token --role reviewer` (`reviewer-token.txt`); KS also needs a live reviewer grant for `reviewer:sprint-oc`, provisioned by `sprint_oc_deployment_file.py --app <app> reviewer-grant [--pack <frozen pack.json>] [--uses U --audiences A --report-kinds K] [--allow-wildcard] [--run]` (it prints, or runs, KS `knowledge-verify grant-reviewer` with `node --env-file=<out>/ks-executor.env`, naming the component DSN variable only; KS writes the grant as `knowledge_verification_reviewer` in the tenant's RLS context with `granted_at` = the database `now()`, and reports an identical live grant as `existing`). Least privilege: the scope defaults to the W1 fixture task's exact use, audience and report kind (ai-engineer `engineering_reference.model_facts`/`internal`/`evidence_report`, biotech `label_reference.ingredients`/`internal`/`evidence_report`; `--pack` reads the task's use and audience from the frozen pack); `*` is refused by both MC and KS unless `--allow-wildcard`. Without the grant the review fails closed (`unauthorized_review`, KS `reviewer_not_qualified`). Reviewer independence is enforced twice: KS refuses the run's producer at review time even when it holds a grant (`assertIndependent` reads the producer from the decision's stored run context: `INDEPENDENCE_UNPROVEN / reviewer_is_producer`), and the MC route refuses the launcher, revision authors, producer and evaluators before sending; Temporal queues and namespace). The generator reads `binding_digest` from it |
| `MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY` | derived with `--deployment-file` | `mission_control.bootstrap.local_operator:runtime_options`: the GoalDirected/StageGraph family admissions and the filesystem artifact payload reader (no S3 bucket) |
| `MISSION_CONTROL_CATALOG_SCOPE` | derived `mc/<target installation_id>/<app>/catalog` | |
| `TEMPORAL_TARGET`, `TEMPORAL_ADDRESS` | constant `local`, `127.0.0.1:7233` | |
| `TEMPORAL_NAMESPACE` | derived: the deployment file's `temporal.namespace` (else `default`) | `mc-<app>` by default: one namespace per application |
| `TEMPORAL_TASK_QUEUE` | derived: `application.toml` `[installation] temporal_task_queue` | `biotech-research-ingestion` for both applications today |
| `LANGSMITH_PROJECT`, `AGENT_SERVER_LANGSMITH_PROJECT` | derived: `application.toml` | |
| `RUN_CONTROL_TEMPORAL_ENABLED`, `COORDINATOR_LAUNCH_ENABLED` | constant `true` | |
| `COORDINATOR_MCP_ENABLED` | constant `false` | The settings default, pinned so neither an owner `.env` nor bundle custody turns the coordinator MCP surface on (see "Why the coordinator MCP stays off") |
| `APPLICATION_DATABASE_DIRECT`, `MC_<APP>_RUNTIME_DSN` | integrator `MC_RUNTIME_DSN` (written by `mission-db login-apply`) | Login `mcl_runtime`, a member of exactly `mission_control_runtime` (NOSUPERUSER, NOBYPASSRLS, INHERIT TRUE, SET FALSE). Startup refuses the admin DSN. Blank until supplied |
| `APPLICATION_FAMILY_WRITER_DATABASE_DIRECT`, `MC_<APP>_FAMILY_WRITER_DSN` | integrator `MC_FAMILY_WRITER_DSN` (`login-apply`) | Login `mcl_family_writer`, holding `mission_control_family_writer`. Blank until supplied |
| `LANGGRAPH_CHECKPOINT_DATABASE_DIRECT` | integrator `MC_CHECKPOINTER_DSN` (`login-apply`) | Login `mcl_checkpointer`, holding `mission_control_checkpointer`. The saver schema is in the app's remote PostgreSQL (§4 item 6) after `mission-db runtime-apply`. When blank, MC falls back to the application (runtime) DSN, which is **not** the checkpointer role. So without it, `mission-control.env` is held as `.incomplete` (exit 3) unless `--allow-checkpoint-fallback` is given; the flag is recorded in `choices.checkpointDsn` and as a manifest warning |
| `LANGGRAPH_CHECKPOINT_SCHEMA`, `LANGGRAPH_CHECKPOINT_SETUP` | constant `mission_control_runtime`, `false` | |
| `ARTIFACT_PAYLOAD_ROOT`, `DEEP_AGENT_SANDBOX_WORKSPACE_ROOT` | derived `<out>/payloads`, `<out>/workspaces` | No S3 bucket is configured (`S3_BUCKET` is blank). The S3-compatible endpoint settings (`S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, OVE-204) are blanked too; a Supabase Storage payload bucket (`mission-payloads`, seed `mc.storage.mission-payloads`) is selected by setting all four with `S3_BUCKET` and `S3_FORCE_PATH_STYLE=true` |
| `REDIS_URL` | constant `redis://127.0.0.1:16379/0` | The compose Redis (the settings default); never the owner's |
| `KNOWLEDGE_GATEWAY_REQUIRED`, `KNOWLEDGE_DISPOSABLE_INSTALLATION` | constant `true` | The targets are identified disposable (OC-D184). The second value only *permits* a scripted KS auditor |
| `KNOWLEDGE_BINDING_URL` | constant `http://127.0.0.1:<KS port>` | |
| `KNOWLEDGE_BINDING_AUDIENCE`, `KNOWLEDGE_ISSUER` | constant | Equal to the KS values |
| `KNOWLEDGE_ISSUER_KEY_FILE`, `KNOWLEDGE_ISSUER_KEY_ID` | minted | `knowledge-issuer.jwk.json`: an Ed25519 private JWK with `kid`, the format `load_signing_key` reads. Both the worker and the **API process** hold it: the API composes the operator review route (W1 D2) and mints the K01 credential of each review itself (a `human_reviewer` evaluation grant for the authenticated reviewer, operation `review/<decision id>`). Treat the API host as holding the KS issuer key |
| `KNOWLEDGE_DESCRIBE_TENANT` | minted tenant | |
| `KNOWLEDGE_COMPONENT_INSTALLATION_ID` | derived: install receipt / `--component-installation-id` | W1 D6: the KS component installation every K01 origin names (equal to the `KS_KNOWLEDGE_BINDINGS_JSON` `installationId`). Required with `KNOWLEDGE_GATEWAY_REQUIRED`; the describe preflight under another id is refused `SCOPE_DENIED` |
| `RUNTIME_CHECKPOINT_SIGNING_KEY` | minted | Otherwise MC falls back to `SUPABASE_SECRET_KEY`, which is blanked here |
| `BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN` | minted | One HMAC secret shared by the worker (parent) and the Agent Server |
| `MISSION_CONTROL_AGENT_SERVER_PROFILE` | constant `runtime` | |
| `ANTHROPIC_API_KEY` | owner: MC `.env` | Producer `claude-sonnet-5-5`, auditor and children `claude-haiku-5-5` (PROOFS §6). The Agent Server child needs it too |
| `OPENAI_API_KEY` | owner: MC `.env` | Probes `gpt-5.6-luna` and any OpenAI child |
| `MC_JUDGE_OPENAI_API_KEY` | owner: MC `.env` `OPENAI_API_KEY` | The independent judge's own credential name (`judge.default`, `gpt-5.6-terra`). Withheld from the Agent Server |
| `MC_AUDITOR_ANTHROPIC_API_KEY` | owner: MC `.env` `SECOND_ANTHROPIC_API_KEY` | The independent auditor's own credential (`auditor.default`, `claude-haiku-5-5`). The generator refuses `AUDITOR_CREDENTIAL_SHARED` when it equals `ANTHROPIC_API_KEY`; MC startup refuses the same. Both evaluator names set: MC composes the trusted settlement. Withheld from the Agent Server |
| `LANGSMITH_API_KEY`, `FIRECRAWL_API_KEY`, `TAVILY_API_KEY` | owner: MC `.env` (optional; blank when absent) | Tracing and the web-research tools |
| The section 1 blank list | blank | Never inherited from an owner `.env` |

### Bundle custody (`bundle-custody.env`)

Seed custody upload (W0) and the worker's skill pins (W1) use the capability-bundle custody
credentials, never the service key. `scripts/sprint_oc_mint_bundle_tokens.py` mints them offline
with `joserfc`. Each is a Supabase Auth JWT with:

- `role` and `aud` set to `authenticated`;
- a stable `sub`, `uuid5(NAMESPACE_URL, "sprint-oc:<app>:<role>")`;
- `iss` set to `https://<project_ref>.supabase.co/auth/v1`;
- `iat` and `exp`;
- the top-level claim `mc_capability_role`.

| Name | `mc_capability_role` | Storage policy (seed `common/mc.storage.capability-bundles-1.0.0.json`) | Default TTL |
| --- | --- | --- | --- |
| `CAPABILITY_BUNDLE_PUBLISHER_TOKEN` | `publisher` | INSERT + SELECT, bucket `capability-bundles`, first folder = the application id | 24h (`--publisher-ttl`) |
| `CAPABILITY_BUNDLE_READER_TOKEN` | `reader` | SELECT, same prefix | 7d (`--reader-ttl`, at most 30d) |

**Signing material.**
- **ai-engineer:** HS256 with `aiengineer/.env` `SUPABASE_JWT_SECRET`
  (`--secret-env-file ../../aiengineer/.env --secret-env SUPABASE_JWT_SECRET`).
- **biotech:** no usable signing material; the project uses asymmetric keys. **Blocked on the owner
  (H2).** It needs a P-256 key imported into the project as a standby signing key, then
  `--es256-key-file <pem> --kid <kid> --url-env-file <MC .env>`.

**The script refuses:**
- when `SUPABASE_URL` in the env file is not exactly `https://<project_ref>.supabase.co` of
  `deployments/<app>/target.toml`;
- when the signing material is missing, ambiguous or too short;
- when `--es256-key-file` is unreadable or not a P-256 private key (`KEY_INVALID`, also for a
  malformed PEM or a key of another type);
- when the output is not ignored.

The HS256 secret is read literally (`dotenv_values(..., interpolate=False)`): a `${...}` inside it
is part of the secret, not a variable reference.

It writes `<out>/<app>/bundle-custody.env` owner-only, like the other secret files, and prints
only the names, `exp`, and the header and claims without a signature.

**Generator pass-through.** When `bundle-custody.env` exists, the generator checks each token's
claims without verifying the signature: the `iss` must name the target, the role must match the
name, and the token must carry a numeric `exp` that is not within 5 minutes (a missing or
non-numeric `exp` refuses with `BUNDLE_CUSTODY_INVALID`). It then writes three files:

| File | Loaded by | Custody names |
| --- | --- | --- |
| `mission-control.env` | MC API and worker | `CAPABILITY_BUNDLE_BACKEND=supabase`, the **reader** token, `CAPABILITY_BUNDLE_NAMESPACE=<app>`, `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`; the publisher token is an explicit blank |
| `agent-server.env` | Agent Server | none: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, both tokens and `BELL_LABS_AGENT_AUTH_ISSUER`/`_JWKS_URI` are explicit blanks |
| `bundle-publisher.env` | the operator scripts `seeds_publish_bundles.py` and `register_supabase_skill_bundle.py` | the **publisher** token, `SUPABASE_URL`, the publishable key, the namespace, `MISSION_CONTROL_APPLICATION`, the catalog scope and `APPLICATION_DATABASE_DIRECT`, with the same blanks as the runtime file; the reader token is an explicit blank; no model keys |

`SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are those of the application's own project:
`aiengineer/.env` for ai-engineer (never the MC `.env`, which names biotech), and the MC `.env` for
biotech.

**Why the Agent Server gets no `SUPABASE_URL`.** `agent_server/auth.py` derives an auth issuer from
`BELL_LABS_AGENT_AUTH_ISSUER`, or failing that from `SUPABASE_URL`. That makes
`authentication_is_configured()` true and verifies every bearer that is not a `bl1.` claim as an
RS256 Supabase JWT. The worker reaches the Agent Server only with `bl1.` scope claims, signed
with `BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN` and routed to the subordinate verifier first in
`deployment_auth.py`. Keeping the issuer unset keeps today's local W1 topology unchanged. A test
checks this with the real loader: `authentication_is_configured()` is `False` for the generated
`agent-server.env` and `True` for `mission-control.env`.

**Why the coordinator MCP stays off.** `Settings.coordinator_jwt_issuer` (`bootstrap/settings.py`)
uses `COORDINATOR_MCP_JWT_ISSUER`, or failing that `<SUPABASE_URL>/auth/v1`; it is read only when
`COORDINATOR_MCP_ENABLED` mounts the coordinator MCP surface (`technical_api._mount_coordinator`),
whose `JWTVerifier` then accepts Supabase JWTs of that issuer. Before custody `SUPABASE_URL` was
blank, so an enabled coordinator surface failed startup instead. Custody now writes
`SUPABASE_URL` to `mission-control.env`, so the generator pins `COORDINATOR_MCP_ENABLED=false`
(the settings default) and keeps `COORDINATOR_MCP_JWT_ISSUER` blank in both modes: enabling
custody changes no coordinator auth. W1 does not use the coordinator MCP surface; a run that
needs it must set an explicit issuer and enable it deliberately. The settings fallback itself is
unchanged. A test loads the real `Settings` from the custody file with an inherited
`COORDINATOR_MCP_ENABLED=true` and finds it off.

The namespace is the application id because the storage policies scope every object to the
application id as its first folder. Any other `SUPABASE_URL` refuses
(`SUPABASE_URL_MISMATCH`). Without the file, `CAPABILITY_BUNDLE_BACKEND=local` and the names stay
blank.

**Mission Control consumers.**
- The worker's skill-pin path (`deployment_composition.supabase_skill_bundle_reader`) now uses the
  reader credential through `configured_supabase_bundle_store(credential="reader")`, never the
  service key. It refuses without a reader token, namespace or catalog scope.
- `scripts/register_supabase_skill_bundle.py --env-file <bundle-publisher.env>` stages with the
  publisher credential.
- `scripts/seeds_publish_bundles.py --storage supabase --env-file <bundle-publisher.env>` uploads
  the seeds.
- Both refuse before any request when `SUPABASE_URL` is not the project of the target
  application.

The models come from `deployments/<app>/models.toml` (`producer.default`, `judge.default`,
`auditor.default`, `child.default`, with `*.fallback` rows). No model is set in the environment;
`manifest_provider_secret_env` maps `openai → OPENAI_API_KEY` and `anthropic → ANTHROPIC_API_KEY`.

## 4. Still missing (owner or integrator)

| Value | Who | Effect until supplied |
| --- | --- | --- |
| **KS executor build with the evaluation-context read and the dispatch drain** (KS `sprint-oc-wi06`: `knowledge.read` `evaluation-context-read/v1`, biotech dispatch drain). Read-only; no component schema change (2.5.0 stays) | integrator: merge KS `sprint-oc-wi06`, rebuild the executor dist | An older executor refuses the context read: the settlement waits `evaluator_unavailable`, nothing is spent |
| Restricted login DSNs `MC_RUNTIME_DSN`, `MC_FAMILY_WRITER_DSN`, `MC_CHECKPOINTER_DSN` for each remote | integrator: `mission-db login-apply` (section 5) on each disposable target, then `--integrator-env` | The names are blank; MC API and worker fail closed |
| `BKS_VERIFICATION_DSN` as a restricted `knowledge_verification_outbox_worker` login | integrator. For disposable W0 only, `--allow-admin-verification-dsn` (recorded in the manifest) | The name is missing; the dispatch consumer is not mounted |
| Operator deployment file (`scripts/sprint_oc_deployment_file.py`, section 5) | integrator | API is inspection-only; the worker refuses |
| `--confirm-graph 8032ec07.databases.neo4j.io` | integrator (the same host as the installer's `--confirm-graph`) | Neo4j names and `BKS_TARGET` are blank |
| Firewall rule for TCP 4020 | integrator before W1 | The BKS executor is reachable from the network |
| Biotech bundle-custody signing material: a P-256 standby key imported into the project | owner (H2) | No Biotech `bundle-custody.env`; Biotech custody stays local |

The component installation ids come from the W0 installs, which the integrator ran and gave to this
work item. Pass them with `--component-installation-id` or through `installation-ids.json`:

- ai-engineer `7ebb2034-a3d6-41aa-893d-ab655a61593f`
- biotech `a34b1309-3f91-4ce1-9eed-3030fdd57b92`

The MC installation ids are the `target.toml` values. The generator cross-checks them against a
receipt when one is given.

## 5. Generator

The integrator runs these commands from the canonical Mission Control checkout (`--mc-root`
defaults to the script's own checkout). Each prints names,
sources, choices and the missing list, never a value. Exit codes:

- **0:** written.
- **2:** refused; no env file written.
- **3:** `--require-complete` with missing names, or a missing checkpointer DSN without
  `--allow-checkpoint-fallback`. Each incomplete env file is written only as
  `<name>.incomplete`, and any runnable copy of it is removed. Complete files stay runnable.
  `agent-server.env` is held whenever `mission-control.env` is (it is derived from it). A
  generated file the current run does not produce (for example `bundle-publisher.env` after
  `bundle-custody.env` is removed) is deleted, runnable and `.incomplete` alike, so no stale
  publisher token or runtime file survives a rerun.

Without `--require-complete`, missing names are written as blanks, never left to an owner `.env`.

```powershell
# Biotech, the W0 installer's executor-config step (disposable W0 may use the admin verification DSN).
uv run --no-sync python scripts/sprint_oc_runtime_env.py --app biotech `
  --component-installation-id a34b1309-3f91-4ce1-9eed-3030fdd57b92 `
  --confirm-graph 8032ec07.databases.neo4j.io --allow-admin-verification-dsn
# Load .scratch/sprint-oc/runtime/biotech/install.env into the installer's process, then run
# node scripts/install-biotech.mjs --remote-reinstall ... (BKS). Afterwards, cross-check:
uv run --no-sync python scripts/sprint_oc_runtime_env.py --app biotech `
  --receipt <BKS>/.scratch/sprint-oc/evidence/install-state/bxnetwiimwhtlrjlbtab/install-receipt.json `
  --confirm-graph 8032ec07.databases.neo4j.io --allow-admin-verification-dsn

# AI Engineer (installed; a receipt exists).
uv run --no-sync python scripts/sprint_oc_runtime_env.py --app ai-engineer `
  --receipt <AIDB>/.scratch/sprint-oc/evidence/install-state/wkythqbofmckbuoothhn/install-receipt.json

# For W1: restricted logins, the deployment file, nothing missing, nothing runnable otherwise.
uv run --no-sync python scripts/sprint_oc_runtime_env.py --app <app> `
  --integrator-env <ignored file: MC_RUNTIME_DSN, MC_FAMILY_WRITER_DSN, MC_CHECKPOINTER_DSN[, BKS_VERIFICATION_DSN]> `
  --deployment-file <operator deployment.json> [--confirm-graph 8032ec07.databases.neo4j.io] --require-complete
```

**W1 order (OVE-169).** Per application, from the canonical checkout, with the admin DSN only in
the installer's own process (`MC_<APP>_MIGRATION_DATABASE_URL`, the `target.toml` name):

```powershell
# 1. Restricted logins (after runtime-apply). Read-only plan first, then apply with a probe.
uv run --no-sync --group dbcontract mission-db login-plan --deployment-dir deployments/<app> `
  --lock <1.7.0 lock> --reader-version mission-control-runtime/1 --writer-version mission-control-runtime/1 `
  --descriptor packages/mission-control-db-contract/runtime/descriptor.json
uv run --no-sync --group dbcontract mission-db login-apply --deployment-dir deployments/<app> `
  --lock <1.7.0 lock> --reader-version mission-control-runtime/1 --writer-version mission-control-runtime/1 `
  --descriptor packages/mission-control-db-contract/runtime/descriptor.json `
  --confirm-target <project_ref>:<installation_id> `
  --out-env .scratch/sprint-oc/runtime/<app>/logins.env `
  --ca-file .scratch/sprint-oc/runtime/supabase-prod-ca-2021.crt --probe `
  --receipt-out .scratch/sprint-oc/evidence/<app>-login-receipt.json
# 2. Operator deployment file (needs minted.env from an earlier generator run).
uv run --no-sync python scripts/sprint_oc_deployment_file.py --app <app> --component-version 1.7.0
# 3. Complete environment (biotech adds --confirm-graph; BKS_VERIFICATION_DSN goes in the same file).
uv run --no-sync python scripts/sprint_oc_runtime_env.py --app <app> `
  --integrator-env .scratch/sprint-oc/runtime/<app>/logins.env `
  --deployment-file .scratch/sprint-oc/runtime/<app>/deployment.json --require-complete
# 4. Operator bearer for launch and inspection (owner-only operator-token.txt).
uv run --no-sync python scripts/sprint_oc_deployment_file.py --app <app> token --ttl-minutes 120
```

`login-apply` writes nothing but the out-env file and the secret-free receipt; a rerun verifies
(`changed: false`), `--rotate` resets the passwords. The `--lock` must be the lock of the installed
1.7.0 release (the tracked `deployments/<app>/release.lock.json` still pins an older release).

The W0 installer runs only need `install.env`. Until the checkpointer login exists, they end
with exit 3, because `mission-control.env` is held as `.incomplete`; that is expected. No MC
process starts until W1.

```powershell
# Bundle custody (ai-engineer), then rerun the generator so mission-control.env carries it.
uv run --no-sync python scripts/sprint_oc_mint_bundle_tokens.py --app ai-engineer `
  --secret-env-file ../../aiengineer/.env --secret-env SUPABASE_JWT_SECRET
uv run --no-sync python scripts/seeds_publish_bundles.py --target ai-engineer --storage supabase `
  --env-file .scratch/sprint-oc/runtime/ai-engineer/bundle-publisher.env
```

The first successful run records `installation-ids.json` (`{"<app>": "<uuid>"}`). Later runs read it,
and any id that disagrees with it is refused.

To load a file, use `node --env-file` / `uv run --env-file`. Both take the generator's single-quoted
values (JSON, DSNs) literally. The generator writes paths with forward slashes and refuses values it
cannot quote unambiguously (`VALUE_UNQUOTABLE`).

## 6. Unverified and handed to W1

- **Bundle custody smoke checks (W1, before the first seed upload):**
  1. *HS256 on a project with asymmetric keys.* Confirm that Storage still accepts a token signed
     with the legacy `SUPABASE_JWT_SECRET`. If the project has rotated to asymmetric signing keys,
     the legacy secret may no longer be accepted.
  2. *A `sub` not in `auth.users`.* The `sub` is a stable `uuid5`, not a real user. Confirm that
     Storage RLS evaluates the `mc_capability_role` claim without an `auth.users` row, and that
     nothing that creates objects requires `owner` to name an existing user.
  3. *The standby key id is known* (biotech, once the owner imports a key). The `--kid` must be the
     key id the project lists for the imported standby key. Otherwise verification fails with an
     unknown kid.

- **Biotech dispatch drain (OVE-169).** KS `knowledge.apply` for biotech commits the admission and
  the outbox row (`pending_dispatch`) and returns. The KS executor now drains it (KS
  `packages/bindings/biotech-graph/src/drain.ts`): every `KS_BIOTECH_DISPATCH_DRAIN_INTERVAL_MS`
  (generator: 5000) at most `KS_BIOTECH_DISPATCH_DRAIN_LIMIT` (10) pending rows per tenant,
  delivering the oldest through `BiotechGraphDelivery.deliver` (consume, then receipt-first
  reconcile); the release pin is `KS_BIOTECH_SCHEMA_RELEASE_DIGEST` or the BKS `/describe`. The
  real Neo4j drain proof is unrun. With an executor built before that commit, the
  W1 native-write variant drains with the BKS CLI (same consumer; idempotent, SKIP LOCKED), run
  by the integrator after the apply from the BKS root:
  `node --env-file=<out>/bks-executor.env packages/kg-ops/dist/cli.js admission consume --once --tenant <tenant>`;
  MC's reconciliation then sees `applied`.
- **Agent Server environment.** `agent_server/runtime.env` interpolates names from the invoking
  environment. That `langgraph dev` passes through names it does not list (`MISSION_CONTROL_APPLICATION`,
  `ANTHROPIC_API_KEY`) follows the operator guide, but this work item has not observed it.
- **Login role for the component DSNs.** That the Supabase admin login can `SET ROLE` to the
  `knowledge_verification_*` roles is inferred from Sprint V; it was not checked on these remotes.
- **One DSN for two jobs.** That one DSN can serve both the component and the AIDB knowledge schema
  (`KNOWLEDGE_DB_URL`) is not verified.
- **Tenant agreement.** The W1 operator grants (`app_metadata.tenant_id`) must use the tenant in
  `minted.env` (`KNOWLEDGE_VERIFICATION_TENANT_ID`). Otherwise the dispatch tenant check fails.
- **Graph host as identity.** A host name is not identity on its own (H3). The installer's graph
  confirmation and the graph's `KsReleaseMarker` remain the install-time identity checks.
