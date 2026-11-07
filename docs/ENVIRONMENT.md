# Environment

Scope of this page: the **database variables**, the **GitHub credentials** and the **Biotech graph login**. Other variables are listed in `.env.example` and described where they are used (see the [operator guide](MISSION_CONTROL_LOCAL_API.md#fast-track-entrypoints-and-configuration)). This page and [`config/env.registry.yaml`](../config/env.registry.yaml) are the whole contract: one registry entry per variable with kind, secrecy, plane or scope, status and reader paths. `make env-check` fails when the registry, the `Settings` fields and the database block of `.env.example` list different database names, or when a registry name is missing from `.env.example`.

## Database

Mission Control reads its database variables **only** under `MC_{AIENG,BIOTECH,LOCAL}_DB_*`, through `Settings.db` (`src/mission_control/bootstrap/settings.py`). There are no aliases and no fallback to older names (`DATABASE_DIRECT`, `APPLICATION_DATABASE_DIRECT`, `SUPABASE_URL`, `LANGGRAPH_CHECKPOINT_DATABASE_DIRECT` and the rest are not read).

### Which plane a process reads

`MISSION_CONTROL_APPLICATION` selects the plane. The other planes' variables are never read.

| `MISSION_CONTROL_APPLICATION` | Plane | Database |
| --- | --- | --- |
| `ai-engineer` | `AIENG` | Supabase `supabase-blue-ocean` |
| `biotech` | `BIOTECH` | Supabase `biotech-research-ingestion` |
| unset | `LOCAL` | the Docker Postgres on `127.0.0.1:55432` (no Supabase, no keys) |
| anything else | none | `Settings` builds, but the first database read fails with `selects no database plane` |

### Names

For `P` in `AIENG`, `BIOTECH` (`LOCAL` has only the five DSNs and the port):

| Name | Secret | Read by | If unset |
| --- | --- | --- | --- |
| `MC_P_DB_PROJECT_REF` | no | the startup check below | the check is skipped |
| `MC_P_DB_URL` | no | Supabase storage client, bundle custody (reader), ingress custody, coordinator and Agent Server issuer (`<url>/auth/v1`) | those surfaces refuse, naming this variable; a Supabase bundle backend fails at composition |
| `MC_P_DB_PUBLISHABLE_KEY` | no | Supabase client and bundle store (optional `apikey` header) | the unprivileged client refuses |
| `MC_P_DB_SECRET_KEY` | yes | privileged Supabase client; checkpoint-signing fallback | privileged client refuses; checkpoint signing needs `RUNTIME_CHECKPOINT_SIGNING_KEY` |
| `MC_P_DB_LEGACY_JWT_SECRET` | yes | reserved: no Mission Control process reads it (`sprint_oc_mint_bundle_tokens.py` takes the signing secret from an owner file by `--secret-env`) | nothing |
| `MC_P_DB_ADMIN_DSN` | yes | `Settings.postgres_dsn` (common-database connection) and migrations; schema owner | the common connection and migrations refuse |
| `MC_P_DB_RUNTIME_DSN` | yes | the runtime pool; Agent Server authority probe; worker (through the binding's `database_secret_ref`) | the API and worker refuse to start; the Agent Server runs without authority |
| `MC_P_DB_FAMILY_WRITER_DSN` | yes | atomic family admission pool (through `family_writer_secret_ref` for the API and worker) | family admission refuses |
| `MC_P_DB_BACKFILL_DSN` | yes | reserved: only `Settings` exposes it | nothing |
| `MC_P_DB_CHECKPOINT_DSN` | yes | LangGraph saver/store in `mission_control_runtime` | blank falls back to the runtime DSN (the generated env refuses that without `--allow-checkpoint-fallback`; a base worker requires it) |
| `MC_LOCAL_DB_PORT` | no | `docker-compose.yml`, `Makefile` (default `55432`) | `55432` |

`MC_P_DB_ADMIN_DSN` is also the migration authority: there is one name for the schema owner. The install target files name the **installer's** variable instead (`deployments/ai-engineer/target.toml` `AIENG_DB_ADMIN_DSN`, `deployments/biotech/target.toml` `BIOTECH_DB_ADMIN_DSN`); pass the same login from `MC_AIENG_DB_ADMIN_DSN` or `MC_BIOTECH_DB_ADMIN_DSN` to Mission Control's own tooling.

### The runtime login

`MC_P_DB_RUNTIME_DSN` must be the **restricted, non-bypass login that is a member of `mission_control_runtime`** (and of nothing else that grants more). The pool checks `pg_has_role(current_user, 'mission_control_runtime', 'MEMBER')` and never `SET ROLE`, so the pooler `postgres.<ref>` login (a development `.env` placeholder) does **not** pass the check. The real value comes from the generated runtime env: `mission-db login-apply` writes `MC_P_DB_RUNTIME_DSN`, `MC_P_DB_FAMILY_WRITER_DSN`, `MC_P_DB_CHECKPOINT_DSN` (and `MC_INGRESS_DSN`, a Vercel variable outside this contract) to an ignored env file for the target's plane, and `scripts/sprint_oc_runtime_env.py --integrator-env <that file>` copies them, with `MC_P_DB_PROJECT_REF`, into `.scratch/sprint-oc/runtime/<app>/mission-control.env`. The generator also writes an explicit blank for every other database variable so an owner `.env` cannot be inherited. The same names are the `database_secret_ref` and `family_writer_secret_ref` of the operator deployment file (`sprint_oc_deployment_file.py`).

### Startup check

`Settings` refuses to construct when the selected Supabase plane's `MC_P_DB_PROJECT_REF` is set and does not appear in the host or login of a sibling `URL` or DSN that is set (pooler logins `<role>.<ref>`, direct hosts `db.<ref>.supabase.co`, `<ref>.supabase.co`). The error names the plane, the ref, the variable and the host; never a credential. `LOCAL` has no project and no check.

### Where each file puts them

- `.env` / `.env.example`: development values; the example holds the names with empty values (and the fake local Docker defaults).
- `agent_server/runtime.env`: `${VAR}` placeholders for the three planes' `MC_*_DB_RUNTIME_DSN`; values come from the Agent Server's process environment. The Agent Server does not receive a plane URL in the generated environment, so its Supabase JWT auth stays off.
- `deployments/cloud_runtime` and `deployments/worker-aws`: the secret names are `MC_<PLANE>_DB_RUNTIME_DSN`, `_FAMILY_WRITER_DSN`, `_CHECKPOINT_DSN` (the plan validator derives the checkpoint name from the runtime name).
- Tests build `Settings` from explicit values (`tests/fixtures/isolated_settings.py`); `tests/fixtures/db_env.py` gives a fixture the plane-qualified name for an application.

## GitHub

Values live in `BellLabs/.secrets/github.env` and the MC `.env`; never in a tracked file.

| Name | Secret | Read by | If unset |
| --- | --- | --- | --- |
| `MC_GITHUB_APP_ID` | no | `adapters/github/credentials.py` (git write path) | the App source is unconfigured; `github_credentials` refuses a partial App configuration |
| `MC_GITHUB_APP_INSTALLATION_ID` | no | same | same |
| `MC_GITHUB_APP_PRIVATE_KEY_PATH` | no (the `.pem` it names is) | same; the key file lives outside every repository | same |
| `MC_GITHUB_READONLY_TOKEN` | yes | the `codex_agents` pack's vault credential `GITHUB_TOKEN` (`source_env`, `deployments/hosted-packs/ai-engineer/codex_agents/pack.yaml`), resolved by `adapters/openai_agents/prepare.py` | the Agents API launch refuses, naming the variable |

The three `MC_GITHUB_APP_*` names configure the GitHub App `agentic-mission-control-app` on the `jbell-rusty-vantage` account (Contents read/write, Pull requests read/write, Metadata read). Each exchange yields an installation token restricted to one target repository. Without the App, an owner-attested fallback reads `gh auth token --user jbell-rusty-vantage`. `MC_GITHUB_READONLY_TOKEN` is a fine-grained token with Contents read and Metadata read on one repository, the fixture repository `jbell-rusty-vantage/mission-control-fixtures`.

Provider cloud agents (Cursor cloud, Codex cloud, Claude Code web) reach repositories through their own GitHub app installs on the account, not through these environment values.

## Biotech graph

| Name | Secret | Read by |
| --- | --- | --- |
| `MC_BIOTECH_GRAPH_URI` | no | the optional Biotech integration (`integrations/biotech`, `BiotechSettings`); `scripts/sprint_oc_runtime_env.py` |
| `MC_BIOTECH_GRAPH_USERNAME` | no | same |
| `MC_BIOTECH_GRAPH_PASSWORD` | yes | same |

The graph is Aura biotech-graph, pinned in `deployments/biotech/graph.toml`; the AI Engineer graph is refused there. The Biotech integration refuses to create a driver when any of the three is blank. The runtime env generator reads them from the MC `.env` and writes them into the BKS executor's file under the names BKS reads (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`), only after `--confirm-graph` names the pinned host.

## Not covered here

`MC_INGRESS_DSN` and the per-application `MC_<APP>_INGRESS_DSN` signal-ingress login are outside this page. The runtime env generator writes Knowledge Services names as KS reads them (`KS_<PLANE>_DB_COMPONENT_DSN` for a binding's `databaseUrlEnv`, `KS_AIENG_DB_RUNTIME_DSN` for the AI Engineer knowledge database) and Biotech Knowledge Services names as BKS reads them today (`NEO4J_*`, `BKS_VERIFICATION_DSN`, `BKS_TARGET`).
