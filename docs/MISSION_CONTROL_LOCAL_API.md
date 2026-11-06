---
type: Operator Guide
title: Configured Mission Control API
description: "The configured entrypoint is mission_control.bootstrap.api:create_app. It serves the scoped API and uses real asymmetric JWT verification, restricted PostgreSQL services, and the Temporal submitter when configured.…"
tags: [mission-control, operations]
---
# Configured Mission Control API

The configured entrypoint is `mission_control.bootstrap.api:create_app`. It serves the scoped
API and uses real asymmetric JWT verification, restricted PostgreSQL services, and
the Temporal submitter when configured. Startup performs no migration or seed writes.

The only storage mode is `production_common`: the common `mission_control` component
(business authority) and `mission_control_search` (rebuildable projection), installed
by `mission-db` from `packages/mission-control-db-contract/`. Startup verifies the
persisted installation identity, the complete attested release and its schema
fingerprint, this build's writer version (`mission-control-runtime/1`) and the
restricted pool roles (`bootstrap/common_installation.py`), and fails closed otherwise.
There is no transitional fallback. The newest built release is 1.12.0; the two disposable Sprint OC remotes carry 1.8.0, and
the deployment locks of the two applications still pin older releases ([database component](knowledge/database-component.md)
lists the release table, the locks and what is installed where). A binding pins `required_component_version` to run against a
release. A local disposable proof is not a live installation. The three fast-track owner missions have not run; their runbook is
archived: [owner fixture runbook](specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md).

Operator-relative assets resolve from `MISSION_CONTROL_HOME`, defaulting to the
current working directory, rather than the installed package directory.

Each application's **Application Profile** is `deployments/<app>/application.toml` (OC-R4,
ADR-0063), read from `MISSION_CONTROL_DEPLOYMENTS_ROOT` (default
`<MISSION_CONTROL_HOME>/deployments`). The API and workers load exactly the profile of the
Application Binding they compose; a mission naming another application is refused at compile.
`MISSION_CONTROL_APPLICATION=<app>` selects the profile whose `[installation]` table supplies
`TEMPORAL_TASK_QUEUE`, `LANGSMITH_PROJECT`, `AGENT_SERVER_LANGSMITH_PROJECT` and the capability
resource owner (`MISSION_CONTROL_WORKSPACE_ROOT`) when those are not set (`.env` applies to
all of them). The LangSmith projects fall back to `MissionControl` /
`MissionControl-AgentServer-Local`; the task queue and the capability resource owner have no
neutral default: a process that needs one and has none fails with
`InstallationDefaultUnavailable`. The configured API derives its coordinator and maintenance
queues from the deployment's `temporal` section, as the worker does, and the API and the
worker refuse to start when `MISSION_CONTROL_APPLICATION` names another application than the
binding, and when `TEMPORAL_TASK_QUEUE` (or the selected profile's queue) differs from the
installation's queue base. The environment always wins over the profile.

**Required now.** Live scripts, the local worker and the technical API
(`bootstrap/technical_api.py`, `runtime_control.py`, the owner probe) have no installation
`temporal` section to derive a queue from: they are the local technical surface and need
`MISSION_CONTROL_APPLICATION=<app>`, or both `MISSION_CONTROL_WORKSPACE_ROOT` and
`TEMPORAL_TASK_QUEUE`. Without them startup fails with `InstallationDefaultUnavailable`
(the worker reports it as `InstallationUnavailable: worker startup refused by readiness`).
A local BellLabs stack sets `MISSION_CONTROL_APPLICATION=biotech` to keep the previous values.

Mission `value_ref: config:<key>` references resolve from the installation configuration
file named by `MISSION_CONTROL_INSTALLATION_CONFIG_PATH`
(`bootstrap/installation_config.py`). The file is `mc.installation_config.v1`: top-level
`schema` (key `schema`, not `schema_version`), an optional `$comment`, and
`applications: {<application id>: {<key>: <value>}}`. Composition hands each Application only
its own mapping (`bootstrap/manifests.py`). Unknown fields, secret-like keys
(key/token/secret/password/passwd/dsn/credential) and a UTF-8 BOM are refused at load. Compile
reports an unknown key as `config_unresolved` and a secret-like one as `config_secret_like`.
Values never appear in reports. A missing or invalid file fails manifest composition for
every lane. The values are compile-time only and are not delivered to a lane's runtime
environment. Example: `deployments/examples/installation-config.example.json`. For a Windows
host with a WSL2 worker, see the [WSL2 worker runbook](WSL2_WORKER_RUNBOOK.md).

## Operator configuration

Create an operator JSON file outside version control using the typed models below.
All database settings are environment **variable names**, never DSNs in this file.
The public JWKS file contains only trusted RSA/EC/OKP public keys with unique `kid`s.
Supported configured algorithms are RS256, ES256, and EdDSA. Replace every example
identity with the installation's actual operator-owned identity before use.

```python
from pathlib import Path
from uuid import UUID
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.bootstrap.api import ApplicationDeployment, MissionDeployment

binding = ApplicationBinding.seal(
    application_id="biotech",
    # Must equal deployments/<app>/target.toml installation_id (allocated once, UUIDv7).
    installation_id=UUID("11111111-1111-4111-8111-111111111111"),
    binding_version="1",
    supabase_project_ref="VERIFIED_PROJECT_REF",  # equals target.toml project_ref
    database_secret_ref="MC_BIOTECH_RUNTIME_DSN",
    accepted_issuers={"https://YOUR_PROJECT.supabase.co/auth/v1"},
    accepted_audiences={"authenticated"},
    required_component_version="1.0.0",
)
auth = ApplicationAuthentication(
    binding=binding,
    issuer="https://YOUR_PROJECT.supabase.co/auth/v1",
    audience="authenticated",
    public_jwks_file=Path("public-jwks.json"),
    algorithms={"RS256"},
    grants=(ActorGrant(
        subject="VERIFIED_ISSUER_SUBJECT",
        actor_id="operator",
        tenant_ids={UUID("22222222-2222-4222-8222-222222222222")},
        permissions={"workflow_run.read"},
    ),),
)
deployment = MissionDeployment(
    storage_mode="production_common",
    max_request_bytes=1_000_000,
    applications=(ApplicationDeployment(authentication=auth),),
)
Path("deployment.json").write_text(deployment.model_dump_json(indent=2))
Path("binding.json").write_text(binding.model_dump_json(indent=2))
```

`binding_digest` is computed over the exact binding by `seal` and verified when loaded.
Claims must include `iss`, `aud`, `sub`, `exp`, and signed
`app_metadata.application_id` / `app_metadata.tenant_id`. Claim paths are configurable;
user-editable `user_metadata` is rejected as a scope source. The operator grants map
verified subjects to exact tenants, actor permissions, authority, sponsorship, and
approval references. Token `permissions` fields are ignored. Changing a path cannot
change an application's issuer or obtain another tenant's configured grant.

Pin trusted public keys from the issuer through the operator's provisioning process.
Key rotation and grant changes require reloading the deployment; restarting invalidates
the old in-process grant map. Token-supplied keys and JWKS URLs are never fetched.

## Application profiles and the Model Catalog (Sprint OC)

Two operator files per application, both read at startup from the deployments root
(`MISSION_CONTROL_DEPLOYMENTS_ROOT`, default `<MISSION_CONTROL_HOME>/deployments`); ADR-0063,
[Application Profile](knowledge/application-profile.md), [model catalog](knowledge/model-catalog.md).

`deployments/<app>/application.toml` (`mc.application_profile.v1`):

| Field | Meaning |
| --- | --- |
| `application_id`, `revision` | the application this file belongs to (must match its directory); the revision enters every resolved runtime's digest |
| `data_class_ceiling` | the most sensitive Data Class a mission of this application may carry; an undeclared mission is treated as the ceiling (`data_class_source = ceiling_default`) |
| `hosted_session_retention_days` | declared, **not yet consumed**: the hosted session retention in force is the 7-day default (`DEFAULT_SESSION_RETENTION_POLICY`); the hosted lane composition passes no policy, so the Application Binding's `hosted_agent_apis.session_retention_seconds` is not read either |
| `[knowledge]` `binding_id`, `apply_contract_name`, `apply_contract_version`, `intent_schema_ref`, `storage_class`, `write_atomicity`, `readback_capability` | the KS binding and its apply contract, the native payload layout the gateway builds, and the backend's storage facts; `readback_capability` is `unsupported` (no KS backend can serve it) |
| `[outputs]` `assessment_pin`, `required_review_classes`, `consequential_signoff_classes`, `allowed_forms` | output-contract minimums (annex OUTPUT-CONTRACTS §5, in KS use classes); authors may tighten, never weaken |
| `[transfer]` `custody_backend`, `inline_bytes_ceiling`, `file_capable`, `binary_capable` | transfer defaults; `file_capable` and `binary_capable` are carried but not yet read |
| `[installation]` `temporal_task_queue`, `langsmith_project`, `agent_server_langsmith_project`, `capability_workspace_root` | operator defaults for the named settings; the environment always wins (loader only, not part of the profile type) |

`deployments/<app>/models.toml` (`mc.model_catalog.v1`): one `[[models]]` row per Model Profile
(`profile`, `vendor`, `model_id`, `context_window_tokens`, `max_input_tokens`, prices, optional
`[[models.price_tiers]]`, `supports`, `data_class_ceiling`). The launch bindings' Deep Agents
`model_profiles` keys are these row names (`producer.default`, ...), each with the exact served
`ref` and default `settings`; the capability-pin file's `models[]` entry for that ref must state the
row's vendor (`provider`) and `model_id`.

**Fail-closed.** Nothing falls back. A missing, invalid or misplaced `application.toml` stops the
API, the workers and the launch author (`ApplicationProfileError`); a profile below the annex
minimums is refused at registration; a `MISSION_CONTROL_APPLICATION` other than the binding's stops
startup (`ApplicationSelectionMismatch`); a mission naming an application the installation does not
hold is refused at compile (`APPLICATION_FORBIDDEN`); a Data Class above the ceiling is refused at
resolution. A missing or invalid `models.toml` stops the API and the launch author; an uncatalogued
profile, an unrouted vendor (`MODEL_ROUTE_UNSUPPORTED`) and a pin whose vendor or model id differs
from the row (`MODEL_PIN_VENDOR_MISMATCH`, `MODEL_PIN_MODEL_MISMATCH`) are refused at readiness,
composition or start. Knowledge composition fails naming any missing `KNOWLEDGE_*` variable or the
missing profile.

**Updating the KS descriptor fixture.** `tests/conformance/applications/ks_backend_descriptors.json`
is a hand copy of each KS binding's `BACKEND.describe()` (`packages/bindings/<binding>/src/backend.ts`,
with `nativeContract` resolved from the binding's apply contract constant), with the KS repository,
branch, commit and source files in its `source` block. When a KS binding's describe changes: copy
the new `id`, `capabilities`, `conditionalCapabilities`, `storageClass`, `writeAtomicity`,
`nativeCancellation`, `nativeContract` and `researchStore` into the matching `backends[]` entry,
update `source.commit`, change the affected `application.toml` `[knowledge]` values in the same
commit, and run `uv run pytest tests/conformance/applications`. This is an offline drift guard; the
check against the live `knowledge.describe` is W0's.

## Install the common component (`mission-db`)

`mission-db` (distribution `mission-control-db-contract`, `uv sync --group dbcontract`)
is the only installer. Exit code 0 means passed, 2 means a blocked gate. It never runs
`supabase db reset`, unscoped pushes or domain SQL, and it never reads a DSN from a
file or argument: targets name an environment variable.

### Target manifest: `deployments/<app>/target.toml`

One authoritative file per app (`deployments/biotech/`, `deployments/ai-engineer/`):

```toml
format_version = 1

[target]
app = "biotech"                       # biotech | ai-engineer; equals application_id
application_id = "biotech"
project_label = "biotech-research-ingestion"
project_ref = "<verified project ref>"
installation_id = "<UUIDv7 allocated once; never regenerate>"
environment = "disposable"            # disposable | development | staging | production
database_host = "<direct or session host>"
database_port = 5432
database_name = "postgres"
database_user = "<approved migration login>"
database_url_env = "MC_BIOTECH_MIGRATION_DATABASE_URL"   # NAME only

[approval]
approved_by = "<approver reference>"
identity_evidence = "<identity evidence reference>"
```

Every field is required; unknown fields and any `REPLACE`/placeholder value are
refused. The DSN in `database_url_env` must match host, port, user and database
exactly. Optional `database_session_user` covers Supabase session-pooler logins
(`postgres.<project_ref>` connects as session user `postgres`); it is accepted only when
the login is exactly `<session_user>.<project_ref>` of the same target. Both tracked
live manifests were approved and filled on 2026-10-03 (Biotech direct route, Blue Ocean
session pooler); credentials stay in the existing `.env` sources and are referenced by
variable name only.

### Release, lock, plan, apply, verify

```powershell
$pkg = 'packages\mission-control-db-contract'
# Build manifest + generated contract on a loopback PostgreSQL 17 scratch database
uv run --no-sync mission-db release-build --component-root $pkg\component --admin-dsn-env MC_RELEASE_ADMIN_DSN
uv run --no-sync mission-db lock --app biotech --component-root $pkg\component --deployments-root deployments
uv run --no-sync mission-db inspect --deployment-dir deployments\biotech
uv run --no-sync mission-db plan --deployment-dir deployments\biotech --out plan.json
uv run --no-sync mission-db apply --deployment-dir deployments\biotech `
  --expected-plan-digest <plan_digest from plan.json> --confirm-target <project_ref>:<installation_id>
uv run --no-sync mission-db verify --deployment-dir deployments\biotech
```

`plan` is read-only and bound to the before-fingerprint, identity, receipts and
release digests. `apply` re-observes under the migration advisory lock, rejects a
stale plan, and commits migrations, `component_release` receipts, the
`application_installation` identity row and the `release_attestation` atomically; a
repeat is a verified no-op. Unknown history, checksum drift, an owned schema without
receipts or a `mission_control_*` role with LOGIN/SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB
holds the install. `vector` must already exist in schema `extensions`.

### Runtime phase (LangGraph saver/store)

```powershell
uv run --no-sync mission-db runtime-plan --deployment-dir deployments\biotech `
  --descriptor $pkg\runtime\descriptor.json
uv run --no-sync mission-db runtime-apply --deployment-dir deployments\biotech `
  --descriptor $pkg\runtime\descriptor.json --confirm-target <project_ref>:<installation_id> `
  --receipt-out runtime-receipts.json
```

This separate phase provisions the pinned `langgraph-checkpoint-postgres` saver/store
in the private schema `mission_control_runtime` (role `mission_control_checkpointer`)
on a dedicated session, including `CREATE INDEX CONCURRENTLY`; it records per-step
progress. After an interruption inspect with `runtime-plan` (invalid indexes are
reported) instead of blindly retrying. Workers never call vendor `setup()`.

### Seeds

```powershell
uv run --no-sync mission-db seed-plan --deployment-dir deployments\biotech `
  --bundle $pkg\seeds\common --bundle $pkg\seeds\biotech
uv run --no-sync mission-db seed-apply --deployment-dir deployments\biotech `
  --bundle $pkg\seeds\common --bundle $pkg\seeds\biotech --confirm-target <project_ref>:<installation_id>
```

Seeds run after `verify`, one transaction per dependency-closed bundle, recorded in
`installation_seed_receipt`. The same digest replays; changed bytes under an existing
key/version conflict. Bundles and exclusions are listed in
`packages/mission-control-db-contract/seeds/README.md`; `seeds/qualification/` is
opt-in for disposable or approved qualification tenants only. No tenant, actor or
grant mapping for a real user is seeded until the owner approves it.

### Storage reconciliation and protected-data evidence

Buckets `capability-bundles` and `mission-artifacts` are private, app-local stores;
`knowledge-artifacts` stays with its domain owner. Bucket and `storage.objects`
policy differences are reconciled separately from the SQL transaction and must be
listed in an operator-approved allowed-differences manifest.

```powershell
uv run --no-sync mission-db snapshot --deployment-dir deployments\biotech --out before.json
uv run --no-sync mission-db compare --before before.json --after after.json --allowed allowed-differences.json
uv run --no-sync mission-db qualify --deployment-dir deployments\biotech --phase before `
  --out-dir docs\qualification\two-project\<target>\<run-id>
```

Snapshots publish hashes only (catalog inventory, per-relation row digests, sequence
states). On a live, concurrently written project equality is meaningful only inside a
quiescent or attributable window.

### Two-disposable driver

`scripts/qualify_two_disposables.py` runs the whole CLI sequence (qualify before,
plan, apply, replay, verify, runtime-plan/apply + replay, seed-plan/apply + replay,
qualify after) against two loopback PostgreSQL 17 + pgvector clusters with different
protected domain fixtures, and writes `docs/qualification/two-project/<target>/<run-id>/`
plus a cross-target `comparison-<run-id>.json`:

```powershell
uv run --no-sync python scripts/qualify_two_disposables.py `
  --biotech-admin-dsn-env MC_PROOF_BIO_ADMIN --ai-engineer-admin-dsn-env MC_PROOF_AIE_ADMIN `
  --run-id <run-id>
```

The independent reviewer suite is `tests/qualification/two_project/` (requires
`MISSION_CONTROL_TEST_ADMIN_DSN` naming a loopback disposable server; it fails, never
skips, without it).

### Restricted pool roles

Login identities are granted membership in exactly one NOLOGIN capability role, only in
disposable tests or after the access-expansion approval:

| Capability role | Use | Must not |
| --- | --- | --- |
| `mission_control_runtime` | API/worker business reads/writes (`binding.database_secret_ref`) | own objects, BYPASSRLS, inherit family/catalog roles |
| `mission_control_family_writer` | atomic family admission (`family_writer_secret_ref`) | be held by the runtime login |
| `mission_control_catalog_writer` | catalog admission and projection writes | tenant business writes |
| `mission_control_outbox_worker` | outbox/projection claims and acknowledgement | mission state mutation |
| `mission_control_readonly` | inspection | any write |
| `mission_control_checkpointer` | `mission_control_runtime` schema only (`LANGGRAPH_CHECKPOINT_DATABASE_DIRECT`) | any `mission_control` access |

Startup asserts NOSUPERUSER, NOBYPASSRLS, the expected single membership and no
ownership of component objects. The installation identity row is written by
`mission-db apply`; the transitional `python -m mission_control.bootstrap.installation`
registration command was removed with the legacy schema runner.

## Start and use

Populate the configured DSN environment reference through the normal secret mechanism.
Then:

```powershell
$env:MISSION_CONTROL_DEPLOYMENT_FILE = 'C:\operator\deployment.json'
uv run uvicorn mission_control.bootstrap.api:create_app --factory --loop mission_control.bootstrap.api:api_loop_factory --host 127.0.0.1 --port 8000
```

The `--loop` factory runs a `SelectorEventLoop` on Windows (psycopg's async adapter, which the
time-travel saver uses, cannot open on uvicorn's default `ProactorEventLoop`); elsewhere it is
uvicorn's `auto` loop. Without it the API logs that time travel is unavailable.

`/health/live` checks process availability. `/health/ready` reports checked local
readiness and whether launch is configured. OpenAPI is at `/docs`.

Set `MISSION_CONTROL_APPLICATION_ID`, `MISSION_CONTROL_URL`, and an issuer-signed
`MISSION_CONTROL_TOKEN` in the CLI process. Then use `missionctl run inspect RUN_ID`.
No placeholder token or development authentication bypass is provided.

For execution, configure `ApplicationDeployment.temporal` with the exact namespace,
address, and root/StageGraph/GoalDirected queues; required Search Attributes are
verified before use. Start the corresponding worker separately. Without Temporal,
inspection and durable command admission work, but launch fails explicitly and
boundary delivery stays pending.

Local Temporal and Temporal Cloud run the same workflow code. Each run stays pinned to the
cluster it first started on. A cloud outage never triggers an automatic cross-cluster replay:
new runs may target the local cluster (`new_run_cluster` in the `mc.local_run_profile.v1`
profile), and an active run either resumes on its original cluster after recovery or moves
through an explicit, reconciled successor run. The successor gets a new run id, so it also has
a new workflow id. The procedure and its guard are described in
[runbook 2.9](specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md).

Supply accepted admission policies, extension validators, payload storage, and fork
patch policies through the `create_application(..., runtime_options={...})` Python
composition hook. Default empty policy/extension registries fail closed for unknown
executable contracts; the API does not invent catalog definitions or policy grants.
The standard factory therefore provides a configured inspection/control deployment;
an execution deployment must install its accepted runtime options and definitions.

The standard ASGI factory can load those options from one explicitly installed,
operator-reviewed module using `MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY=package.module:build`.
The callable receives the validated `MissionDeployment` and must return exactly one
typed `RuntimeOptions` for every configured application. Unknown, missing, or untyped
entries fail startup. Requests, JWT claims, catalog content and skill bundles cannot
select this module. For example, the installed module can expose:

```python
def build(deployment):
    return {
        "biotech": RuntimeOptions(
            admission_policies=accepted_admission_policies(),
            extensions=accepted_extension_registry(),
            payload_store=configured_payload_store(),
            family_admissions=accepted_family_admission_registry(),
            fork_policies=accepted_fork_patch_registry(),
        )
    }
```

These factory functions belong to the reviewed deployment package and must register
the exact admitted contracts. The deterministic acceptance proof demonstrates this
with the existing technical admission policies and real StageGraph/GoalDirected
family mutation registries, without substituting model prompts for policy.

## Worker startup

Use the same deployment file and reviewed runtime-options factory for the API and
worker. Set `ApplicationDeployment.family_writer_secret_ref` and configure its
Temporal namespace and queues. The worker selects exactly one application; queues
shared by different configured applications are rejected.

Provide these environment settings through the operator configuration/secret manager:

- `MISSION_CONTROL_DEPLOYMENT_FILE`, `MISSION_CONTROL_WORKER_APPLICATION_ID`, and
  `MISSION_CONTROL_WORKER_BINDING_DIGEST` (the exact sealed binding digest).
- `COORDINATOR_LAUNCH_ENABLED=true`.
- `LANGGRAPH_CHECKPOINT_DATABASE_DIRECT`: a dedicated login in
  `mission_control_checkpointer` to the same selected installation database, distinct
  from runtime/family authority.
- `LANGGRAPH_CHECKPOINT_SCHEMA=mission_control_runtime` (the default; `public`, the
  business schemas and the retired legacy schemas are refused).
- `LANGGRAPH_CHECKPOINT_SETUP=false`: schema setup is never a worker startup action.
- `MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY`, when using an accepted operator
  registry package; both processes resolve the same typed per-application options.

Provision the pinned official LangGraph PostgresSaver and PostgresStore migrations
with `mission-db runtime-apply` before starting the worker. Readiness checks
their actual migration versions and rejects owner/superuser/BYPASSRLS credentials,
business authority privileges, missing schemas and mismatched installation data.
Select model/backend credentials only for the providers this deployment uses.

```powershell
uv run python -m mission_control.bootstrap.worker
```

The worker uses a Psycopg-compatible selector event loop on Windows. The configured
entrypoint has been exercised with real PostgreSQL and Temporal, including root,
both family and linked-run pollers, without creating schema during startup.

### WSL2 worker for the local Claude and Codex lanes

`claude_agent_sdk` and `codex` spawn asyncio subprocesses, which the Windows selector loop
cannot do, so a Windows host runs them on a WSL2 worker (decision D5;
[SPEC-09](specs/archive/materialization-observation-2026-10/SPEC-09-local-harness-path.md) §2 and §6).
The API, Docker services and agent sessions stay on Windows; WSL2 reaches them on `127.0.0.1`.

1. **Toolchain** (inside WSL, as the worker user, from the Windows checkout):
   `bash scripts/wsl/install_worker_toolchain.sh`. It self-updates uv, installs Python 3.12
   (uv-managed), Node LTS (nvm), Codex `0.162.1` (`CODEX_VERSION`, DECISIONS R21) and the
   Claude Code CLI; adds a `~/.profile` block that puts the Linux binaries ahead of the
   Windows `PATH` WSL appends; makes `~/mc-leases/{claude,codex,cursor}` and `~/mc-fixtures`;
   and syncs a separate Linux venv at `$HOME/.venvs/mission-control`. It never logs in and
   never calls a model. Removing the Windows `PATH` entirely needs `[interop]
   appendWindowsPath=false` in `/etc/wsl.conf` (sudo) and `wsl --shutdown`.
2. **Same tree.** Run the worker from the `/mnt/c` checkout with
   `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/mission-control` (never sync into the Windows `.venv`),
   or from a clean clone of the checkpoint commit the API runs. Build ids must match. The
   shared venv is an editable install of the checkout it was last synced from: re-run the
   script (or `uv sync`) from the checkout the worker runs whenever that changes.
3. **Auth** (names only; R21). Claude uses the `api_key` route: export `ANTHROPIC_API_KEY`
   into the worker process (a value only in `.env` does not reach the child). Codex uses the
   ChatGPT login: run `codex login --device-auth` once inside WSL, and set
   `MISSION_CONTROL_CODEX_HOME_MODE=owner`, `MISSION_CONTROL_CODEX_OWNER_HOME=$HOME/.codex`. The
   `api_key` route (`OPENAI_API_KEY`) also works in isolated mode. Select the profiles in an
   `mc.auth_profile.v1` file (`MISSION_CONTROL_AUTH_PROFILES_PATH`, shape in
   `deployments/examples/provider-auth-profiles.example.json`).
4. **Worker environment:** `MISSION_CONTROL_CLAUDE_LEASE_ROOT=$HOME/mc-leases/claude`,
   `MISSION_CONTROL_CODEX_LEASE_ROOT=$HOME/mc-leases/codex`,
   `MISSION_CONTROL_CODEX_BINARY=$(command -v codex)`, `MISSION_CONTROL_AUTH_STATUS_PROBE=true`
   and the worker settings above. Lease roots must be on the Linux filesystem and outside
   `~/.cursor/worktrees` and `$CODEX_HOME/worktrees`.
5. **Host preflight** (read-only; version and status commands only):

   ```bash
   UV_PROJECT_ENVIRONMENT=$HOME/.venvs/mission-control uv run --no-sync \
     python -m mission_control.bootstrap.preflight host \
     --auth-profiles <mc.auth_profile.v1 file> \
     --auth-profile claude_agent_sdk=<profile id> --auth-profile codex=<profile id>
   ```

   Run it from the checkout the worker runs. `--auth-profiles` defaults to
   `MISSION_CONTROL_AUTH_PROFILES_PATH`; `--checkpoint` (default `origin/main`, R19) names the
   commit a worker clone must be at. It prints an `mc.local_readiness.v1` report and exits 2
   when blocked. Checks and codes: the OS per lane (`LANE_UNSUPPORTED_OS`), Python 3.12
   (`PYTHON_UNSUPPORTED`), `uv lock --check --offline` (`UV_LOCK_INCOMPATIBLE`), a maintained
   Node LTS release by its own `process.release.lts` (`NODE_NOT_LTS`), every CLI resolving to
   a Linux binary rather than a shim under a Windows drive mount (`/mnt/<drive>`, or the
   `[automount] root` of `/etc/wsl.conf`; `TOOL_MISSING`, `TOOL_WINDOWS_SHIM`), `codex
   --version` against the launcher's pin (`CODEX_PIN_MISMATCH`, or advisory
   `CODEX_PIN_OVERRIDDEN` under `MISSION_CONTROL_CODEX_ALLOW_VERSION_MISMATCH`), the
   SDK-bundled Claude Code (`CLAUDE_BUNDLED_CLI_MISMATCH`), the same-tree rule (the venv
   imports `mission_control` from this checkout's `src`: `VENV_OTHER_TREE`; the venv is on the
   Linux filesystem: `VENV_ON_WINDOWS_FS`; a clone is a clean checkout of the checkpoint:
   `CLONE_NOT_CHECKPOINT`), lease roots as the worker composes them
   (`LEASE_ROOT_ON_WINDOWS_FS`, `LEASE_ROOT_PROVIDER_OWNED`) and auth per lane through the
   worker's own admission with the status probe on (`AUTH_*`, as a launch would refuse).
   Mission Control pins Codex 0.162.0 (`adapters/codex/protocol.py`) until MO-66 re-pins it
   to 0.162.1; until then a 0.162.1 worker needs the override.

## Multi-provider entrypoints and configuration (2026-10 packet)

Names only; values come from the operator environment. See
`docs/specs/archive/multi-provider-2026-10/` and the ledger for evidence status.

- `uvicorn mission_control.bootstrap.realtime:create_asgi_app --factory`: the public API
  wrapped once with the `/missions` Socket.IO namespace (SPEC-04). `bootstrap.api:create_app`
  keeps working without the socket. `MISSION_SOCKET_REDIS_FANOUT=true` relays presence and
  commit hints between API processes over `REDIS_URL`; PostgreSQL stays the replay ledger.
  `MISSION_SOCKET_POSTGRES_HINTS` (default true) listens on the 0032 `mc_stream_hint`
  channel of every configured application database to wake the same pumps.
  `MISSION_SOCKET_REAUTHORIZE_SECONDS` (5) re-verifies an idle connection's credential;
  `MISSION_SOCKET_COMMAND_FOLLOW_SECONDS` (120) bounds how long a socket command's
  accepted/delivered/applied receipts are followed.
- `GET|POST /v1/applications/{app}/human-tasks[...]` (MP-10): Human Gate tasks and the one
  resolution path; MCP tools `mission_human_task_*` and the socket event
  `resolve_human_task` call the same service. Both family workers register the
  `mc.human_gate.v1` control activation and its activities. A Goal Loop whose acceptance
  requires `human` and whose manifest names no gate reviewer is reviewed by the `owner`
  reviewer role (principal `owner` or a verified `reviewer:owner` grant).
- Native approvals and governed effects (MP-11, release 1.2.0):
  `POST /v1/applications/{app}/human-tasks/{id}/approval-resolutions` takes the extended body
  (approve with edited arguments, question answers, elicitation content, cancel); the same
  `resolve_human_task` socket event accepts it. MCP: `mission_governed_prepare`,
  `mission_governed_execute`, `mission_governed_status`, `mission_approval_resolve`. Governed
  tools are trusted Python composition (`RuntimeOptions.governed_tools`); none is registered by
  default. An admitted cancel closes the run's open approval tasks.
  `MISSION_CONTROL_APPROVAL_WAIT_S` (300) bounds a native permission callback's wait inside a
  `lane.turn` segment; the Human Task stays open after it.
- Coordinator inbox (MP-15, release 1.2.0): `POST /v1/applications/{app}/coordinator-inboxes`,
  `GET .../coordinator-inboxes/{id}/notifications`, `POST .../{id}/acks`,
  `POST .../{id}/notifications/{nid}/commands`, `DELETE .../{id}`,
  `GET .../coordinator-inboxes?target=run|mission&target_id=` (the caller's open inboxes). Composed
  only where the application database has `mission_control.coordinator_inbox`; otherwise the routes
  answer `503 inbox_unavailable`. Webhook callbacks are egress-guarded
  (`WEBHOOK_ALLOW_LOOPBACK`, `WEBHOOK_ALLOWED_NETWORKS`); `webhook_payload: summary` adds the
  rendered reference-only summary.
- Wake channels (MO-43, SPEC-04 §6): every launch through this API subscribes the launcher's
  coordinator inbox over the run first (`?notify=none`, `missionctl ... start --notify none`, or
  MCP `notify: none` opts out); the receipt's `coordinator_inbox` names it. Wait with
  `GET .../coordinator-inboxes/{id}/notifications?wait=<s>&kinds=terminal_result,blocked` or
  `missionctl wait --run RUN --kinds terminal_result,blocked,review_required` (one JSON line per
  notification; exit 0, or 6 at the `--wait` deadline, default 3600 s; `--follow` streams;
  acknowledge with `--ack` or `missionctl inbox ack ID --through SEQ`). From Claude Code, run
  `missionctl wait` as a background task: its exit wakes the session.
- Coordinator attention (WI-19, needs the candidate migration 0063; apply it before upgrading, see
  the 1.8.0 note in `packages/mission-control-db-contract/releases/README.md`): every delivery carries
  a fresh `delivery_nonce` in its payload only; an HTTP or MCP answer and every webhook attempt record
  a transport observation (a webhook 2xx never acknowledges, so webhook inboxes keep notices pending
  until acknowledged). The host attests its idle wake, then the model-visible payload, with
  `POST .../coordinator-inboxes/{id}/notifications/{nid}/observations` or `missionctl inbox observe
  ID --id N --stage wake|visible --nonce K [--idle-since T0 --at T1]`; bounded excerpts of the exact
  accepted revisions a notice references come from `POST .../notifications/{nid}/content` or
  `missionctl inbox content ID --id N --obligation KEY` (grant `workflow.result.read`; the purpose is
  the one the inbox declared in `profile.content.purpose` at subscribe time);
  `GET .../coordinator-inboxes/{id}/attention` or `missionctl inbox attention ID` reports the six
  stages and the verdict. Without 0063 these answer `503 unavailable` and webhooks post nothing. See
  `docs/knowledge/coordinator-attention.md` (including the C14 host procedure).
- Output inspection (WI-19, `workflow_run.read`): `GET .../runs/{id}/outputs` (promises, accepted
  revisions, fulfillment, assessments, plans, actionable items), `.../outputs/{key}/revisions`,
  `.../output-events`, `.../transfer-plans` and `GET .../transfer-plans/{plan_id}`; `missionctl
  outputs show|revisions|events|plans|plan`; MCP `mission_run_outputs`,
  `mission_run_output_revisions`, `mission_run_output_events`, `mission_transfer_plan`.
- Operator MCP (MO-43): Streamable HTTP at `/v1/applications/{app}/mcp/` (stateless, JSON
  responses) with the same bearer token as the HTTP routes, verified before any MCP message is read.
  Tools: `coordinator_inbox_subscribe|list|poll|wait|ack|command|observe|content|attention`,
  the output inspection tools, `mission_run_transcript|search|list`,
  `mission_manifest_compile|submit`, `mission_run_start`, `mission_command_send`,
  `mission_run_inspect`, `mission_run_fork`, `mission_chain_inspect`, `mission_human_task_*` and the
  governed tools. `mission_subscribe` is deprecated (proposed ADR-0049) and only the development
  MCP server still offers it.
- Continuation (MP-12): the worker serves `continuation.*` on the cognitive queue and drives
  Session Lane transfers from the operation workflow. Context policy:
  `MISSION_CONTROL_CONTEXT_SOFT_RATIO` (0.70), `..._HARD_RATIO` (0.85), `..._RESERVE_RATIO`
  (0.15), `MISSION_CONTROL_CONTEXT_MAX_SESSION_TURNS`,
  `MISSION_CONTROL_CONTINUATION_MAX_TRANSFERS` (8),
  `MISSION_CONTROL_CONTINUATION_MAX_COMPACTION_FAILURES` (2),
  `MISSION_CONTROL_NATIVE_COMPACTION` (`preferred|disabled|required`).
- Local Claude and Codex lanes (MP-07/MP-08; Linux/WSL workers only):
  `MISSION_CONTROL_CLAUDE_LANE=true` with `MISSION_CONTROL_CLAUDE_LEASE_ROOT`,
  `..._CLAUDE_INIT_TIMEOUT_S`, `..._CLAUDE_DRAIN_TIMEOUT_S`; `MISSION_CONTROL_CODEX_LANE=true`
  with `MISSION_CONTROL_CODEX_BINARY`, `..._CODEX_LEASE_ROOT`, `..._CODEX_HOME_MODE`
  (`isolated|owner`), `..._CODEX_OWNER_HOME`, `..._CODEX_REPOSITORY`. Both also need
  `MISSION_CONTROL_AUTH_PROFILES_PATH`; neither is qualified, so the registry admits them only
  with `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES`. Claude/Codex/Cursor units always run through
  `lane.turn` segments on their binding's task queue.
- Session ownership (MP-06): `MISSION_CONTROL_SESSION_LEASE_MIN_S` (10),
  `MISSION_CONTROL_SESSION_LEASE_HEARTBEATS` (2),
  `MISSION_CONTROL_DISPATCH_RECEIPT_GRACE_S` (10). Every new native dispatch is admitted
  against the run's Stop Fence before it is issued.
- Auth routes and capacity waits (MP-05): `MISSION_CONTROL_AUTH_PROFILES_PATH`,
  `MISSION_CONTROL_ALLOW_UNQUALIFIED_AUTH_ROUTES`, `MISSION_CONTROL_AUTH_STATUS_PROBE`,
  `MISSION_CONTROL_AUTH_STATUS_TIMEOUT_S`, `MISSION_CONTROL_CAPACITY_*`. The capacity bounds
  travel with every operation request (`OperationWorkflowRequest.capacity_wait`) into the
  workflow's provider-limit planner.
- Local readiness (MP-22): `MISSION_CONTROL_LOCAL_RUN_PROFILE` (an
  `mc.local_run_profile.v1` file) and `MISSION_CONTROL_PREFLIGHT_WORKSPACE_ROOT`. The worker
  verifies capability pins and, with a profile, lane hosts before it polls
  (`PIN_DRIFT` / `LANE_UNSUPPORTED_OS` refuse startup); `python -m
  mission_control.bootstrap.preflight readiness` prints the same report. Every launch binds
  the run to its Temporal cluster in `mission_control.run_cluster_binding` (migration 0032);
  a launch from a service bound to another cluster is refused
  (`run_bound_to_other_cluster`) instead of starting a second copy.
- Workspace resource roots: `workspace://` pin locators resolve under the checkout's parent
  (BellLabs: `platform/`). The declared resource roots `.agents` and `.tools`
  (`capability_pins.WORKSPACE_RESOURCE_ROOTS`) may be directory links, as the BellLabs
  `platform/.agents` and `platform/.tools` junctions to the Biotech-owned directories are.
  A locator under one must stay inside that link's target, and the target must keep the
  root's name. Every other locator must stay inside the workspace's real path, so nested
  links, undeclared top-level links and `..` spellings are refused. Pinned bytes are verified
  at the resolved real path.
- Biotech schema source: the Biotech integration reads the authoritative graph SDL from
  `BIOTECH_SCHEMA_SDL_PATH` when set, otherwise from
  `<BellLabs>/biotech/biotech-knowledge-services/schema/pinned/release/sdl/assembled.graphql`.
  The owner selected release `biotech-schema-v2.0.2`, whose source digest matches the Fly
  API identity. Source bytes and the semantic overlay must match
  `resources/schema-catalog/source-reference.v2.json`; a mismatch refuses use. The
  derived executable GraphQL schema and installed graph release are separate identities.
  Historical v1 references remain unchanged; Mission Control does not copy the owning SDL.
- Release: frozen `component/` is 1.4.0; the additive Run 2 successor is under
  `packages/mission-control-db-contract/releases/1.4.2/component/`. It preserves 1.4.1
  and adds launch-request body conflict checks in migration 0044. Deployment locks
  still select 1.3.0. Local successor proof does not apply a live migration; startup
  must match the selected target and release. See [persistence](knowledge/persistence.md)
  and the [successor plan](specs/archive/materialization-observation-2026-10/runs/CODEX-DESCRIBE-SUCCESSOR.md).
- Per-profile status: [multi-provider release statement](specs/archive/mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md).

## Fast-track entrypoints and configuration

This section lists names only. Values come from the process environment, `mission-control/.env` or
the operator's secret manager; never write a value into a manifest, seed, deployment file under
version control, Linear comment or document. Settings names are case-insensitive environment
variables (`bootstrap/settings.py`).

**API process** (`make server`):

| Name | Effect |
| --- | --- |
| `MISSION_CONTROL_SUBSCRIPTION_RELAY` | the subscription relay (webhook callbacks, MCP delivery, coordinator prompts) runs inside the API by default; `0` turns it off. SSE `events watch` and `missionctl wait` need no relay |
| `CURSOR_API_KEY`, `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES` | only so `lane list` and `lane describe` show the Cursor profiles and mirror the worker's admission policy |
| `CAPABILITY_EMBEDDING_PROFILE` | unset: capability search is lexical-only; `embedding.openai.text-embedding-3-small` embeds each query (needs `OPENAI_API_KEY`, a small paid effect) |
| `MISSION_CONTROL_CATALOG_SCOPE` | installation catalog scope used by the projection scripts (`mc/<installation>/<app>/catalog`) |
| `CAPABILITY_BUNDLE_BACKEND`, `CAPABILITY_BUNDLE_NAMESPACE`, `CAPABILITY_BUNDLE_LOCAL_ROOT`, `CAPABILITY_BUNDLE_PUBLISHER_TOKEN`, `CAPABILITY_BUNDLE_READER_TOKEN` | bundle custody backend (`local` or `supabase`) and its publisher or reader credentials, never the service key; the configured API does not yet expose publish routes. The launch author reads skill bundles and hook scripts through the local root or the reader credential; without either, `mission start` of a mission selecting one answers `409 start_unavailable` (`bundle_custody_unavailable`) |

**Worker process** (`make worker`; `cursor_local`, `claude_agent_sdk` and `codex` need a WSL or Linux
worker because the Windows worker runs a selector event loop that cannot spawn asyncio subprocesses;
the readiness gate refuses them on Windows with `LANE_UNSUPPORTED_OS`):

| Name | Effect |
| --- | --- |
| `CURSOR_API_KEY` | registers the `cursor_local` and `cursor_cloud` lane profiles |
| `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES` | `true` admits unqualified lanes for a local proof; both Cursor profiles are unqualified, and the refusal names this flag |
| `MISSION_CONTROL_LANE_SEGMENT_LOOP` | default `false`; `true` moves Deep Agents units onto `lane.turn` (Cursor units always use it) |
| `MISSION_CONTROL_FRAMES_EXPIRE_SCHEDULE` | default `true`: serve `mc.frames_expire.v1` on `<base>-maintenance` and keep the daily retention Schedule |
| `CURSOR_LEASE_ROOT`, `CURSOR_LOCAL_REPOSITORY` | where `cursor_local` leases git worktrees, and the worker-local checkout used when a binding names no repository |
| `MISSION_CONTROL_HOOK_CALLBACK_PORT` | loopback port (default 47555) of the Kernel Hook callback listener |
| `CAPABILITY_PINS_PATH`, `WEB_RESEARCH_AGENT_BROWSER_NODE` | the worker's pin file of launchable components and the node binary for the pinned `agent-browser` tool |
| `CAPABILITY_BUNDLE_LOCAL_ROOT`, `CAPABILITY_BUNDLE_READER_TOKEN` | the bundle custody every lane re-renders skill bundles and hook scripts from at `prepare` (the same backend as the API's launch author; `scripts/seeds_publish_bundles.py --storage local:DIR` fills a local root) |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TARGET`, `TEMPORAL_CLOUD_API_KEY` | `TEMPORAL_TARGET` is `local` by default (the `make temporal-up` server); `cloud` only on purpose |
| `TEMPORAL_WORKER_VERSIONING`, `TEMPORAL_DEPLOYMENT_NAME`, `TEMPORAL_BUILD_ID`, `TEMPORAL_PROMOTE_ON_START` | Worker Deployment versioning (`temporalio` 1.34): default on, deployment `mission-control`, build id defaults to the package version, promote on start; production operators may set promotion off and promote deliberately |
| `OPENAI_API_KEY`, `TAVILY_API_KEY`, `FIRECRAWL_API_KEY` | Mission 1 model and retrieval secrets (paid) |
| `NCBI_API_KEY`, `EDGAR_IDENTITY` | secret references for the PubMed and EDGAR MCP seeds; not set today (keyless PubMed works at a low rate; EDGAR is unused by the three missions) |

Capability bundle tokens, webhook secrets and MCP secrets are referenced by name
(`environment:<NAME>` for a subscription webhook) and resolved at the point of use.

**Client** (`missionctl`): `MISSION_CONTROL_URL`, `MISSION_CONTROL_APPLICATION_ID`,
`MISSION_CONTROL_TOKEN` (an issuer-signed token; load it from a file without echoing it). New
groups: `mission compile|submit|start|schema`, `chain inspect`, `subscribe`, `events watch`,
`lane list|describe`, `model list|describe`, `run transcript|frames|list|search|checkpoint|fork`,
`command queue|inject|cancel`, `catalog pin|render|publish`
([interfaces](knowledge/interfaces.md)). `mission start` answers `409 start_unavailable` in the
configured deployment until a production launch input author is composed (blocker B1).

**Models** (OC-R6): the installation's Model Catalog is `deployments/<app>/models.toml`
(read at startup; a missing or invalid file stops the API and the launch author). `missionctl
model list --json` (`GET /v1/applications/<app>/models`) prints every profile with vendor, model
id, context window, prices per million tokens and a route verdict per lane profile (`native`,
`emulated`, `unsupported`, or `unregistered` when this process has no package registration for
the lane); `missionctl model describe PROFILE --json` adds each lane's mechanism, and `lane
describe LANE` its `model_routes`. A manifest names a profile, never a model id; the launch
bindings' Deep Agents `model_profiles` name catalog profiles with only the served `ref` and
default `settings`. To substitute a PROOFS §6 fallback, select `<role>.fallback` or edit the
`<role>.default` row ([model catalog](knowledge/model-catalog.md)).

Every served model pin (`infra/capability-pins/*.json` `models[]`) carries its `provider` and
`model_id` (the pin script takes `model@<vendor>@<model_id>:<logical_id>:<revision>:<digest>`), and
both are enforced: a launch binding whose served definition does not serve its catalog row's
vendor and model id is refused at composition and readiness (`MODEL_PIN_VENDOR_MISMATCH`,
`MODEL_PIN_MODEL_MISMATCH` at `#/model_profiles/<name>/ref`) and by the worker's factory; a served
digest without a declared identity is refused (`MODEL_PIN_UNDECLARED`). A component registered
beside the pins (`DeploymentCapabilityComponents.model_factories`) must declare
`model_identities` and may not replace a pinned definition's factory
(`MODEL_FACTORY_COLLISION`); only a composition explicitly flagged `qualification=True` (tests,
qualification harnesses with deterministic models) is exempt. The pin file pins one served
definition per installed catalog model; `model.wp-cp-040` is the WP-CP-040 qualification slot
(`fixture-model`), which no installed catalog row binds.

**Make targets and scripts:**

| Command | Purpose |
| --- | --- |
| `make lane-qualify PROFILE=cursor_local\|cursor_cloud` | offline fixture, describe-honesty and replay suites; `LIVE=1` adds the paid drill (`CURSOR_API_KEY`, finite `MC_PAID_BUDGET_USD`, for cloud `MC_CURSOR_CLOUD_REPO`; optional `MC_LANE_DRILL_APPROVAL_URL`); see [lane qualification](qualification/lanes/README.md) |
| `make skills-check` / `make skills-manifest` | fail on, or rewrite, drifted `skills/*/manifest.json` digests (LF-canonical) |
| `make seeds-validate` | fail if a seed Capability Pin does not parse or a tools/list digest drifted |
| `python -m mission_control.bootstrap.preflight --profile <file> readiness` | MP-22 readiness gate (`mc.local_readiness.v1`): lists every unresolved pointer of a real local run (profile, lane OS, launch bindings, auth routes, capability pins under `--workspace-root`, release lock and, with `--db-dsn-env <NAME>`, the installed release fingerprint) before any composition or paid call; exit 2 when blocked. `MISSION_CONTROL_LOCAL_RUN_PROFILE` makes `make preflight` run it first |
| `... preflight host [--lane claude_agent_sdk\|codex] --auth-profiles <file> --auth-profile <lane>=<id> [--checkpoint <rev>]` | MO-08 worker-host check for the local Claude and Codex lanes on a WSL2 or Linux worker (see "WSL2 worker for the local Claude and Codex lanes"); exit 2 when blocked |
| `scripts/wsl/install_worker_toolchain.sh` | installs the WSL2 worker toolchain (uv, Python 3.12, Node LTS, pinned Codex, Claude Code CLI) and a separate Linux venv; no login, no model call |
| `... preflight compose-bindings`, `... preflight guard-launch` | re-seal an owner's `mc.manifest_launch_bindings.v1` from `deployments/examples/manifest-launch-bindings.deep-agents.example.json` plus a `{pointer: value}` selections file; bind a run to one Temporal cluster before its start and refuse a second copy elsewhere ([runbook 2.8–2.9](specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md)) |
| `make temporal-up`, `make temporal-search-attributes` | start the local Temporal stack and register the Search Attributes (`mc_mission_id`, `mc_run_id`, `mc_lane`, `mc_phase`, `ForkedFromRunId` among them) |
| `scripts/rebuild_capability_search_projection.py --tenant <scope> --lexical-only` | build the capability search projection without a paid embedding batch |
| `scripts/fast_track_dry_run.py [--with-fixture-rows]` | unpaid dry run on scratch installs (`MISSION_CONTROL_TEST_ADMIN_DSN` names the loopback admin DSN; refuses while `CAPABILITY_EMBEDDING_PROFILE` is set) |

Installing release 1.1.0 uses the `mission-db` commands above against a local target outside
version control for fixtures (never the live `deployments/<app>` targets), after `vector` and
`pg_trgm` exist in schema `extensions`. The exact local-stack procedure, the mission commands, the
paid-unit budget policy, how to stop safely and the open owner decisions are in the
[owner fixture runbook](specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md).

### Local telemetry ingress

An application deployment may declare `signal_ingress_secret_ref` naming an environment
variable containing its dedicated `mission_control_ingress` login DSN. Provision that login
through the database operator procedure; startup never grants roles. The API mounts
`/v1/ingress/{app}/signals` and `/v1/ingress/{app}/mcp`; the worker mounts the same handlers
on `127.0.0.1:MISSION_CONTROL_HOOK_CALLBACK_PORT` beside Kernel Hooks. Startup rejects a
superuser, BYPASSRLS login, missing ingress membership or credential-table reader.

When configured, Codex and Cursor-local child processes receive `MC_SIGNAL_URL` and a
per-attempt `MC_SIGNAL_TOKEN`, minted into the shared digest-only credential store and
redacted by the Secret Broker. The worker environment never receives that token. Without
the dedicated binding the pack spools locally. Provider signing tiers and public cloud
reachability need separate edge configuration; the local composition serves run tokens.

In `mission/v2`, `environment.observation.in_environment: "off"` disables the pack; node
environments inherit or override the selection. Both launch-time projection digests and
runtime rendering use the sealed selection. Omit it for the default pack. The additive
`mc.app.<app>.signal-skills@1.0.0` seeds register `skill.mc-signals` without rewriting applied
agent-skills seeds. Check them with `python packages/mission-control-db-contract/seeds/signal_skills.py`
and publish through the existing `scripts/seeds_publish_bundles.py` custody command.

For synchronous gates, declare `environment.observation.gates: {fail_closed: true}`;
`events` defaults to `[before_tool]` and may also name `before_shell` or `before_mcp` when
the lane enforces them. Gate answers come from the same SQL Stop Fence and effect-intent
ledger; an unreachable ingress returns a native deny when `fail_closed` is true.

Cursor cloud also needs `MISSION_CONTROL_SIGNAL_INGRESS_ORIGIN=https://<configured-host>`,
a network policy admitting that host, the account's launch-envVars prerequisite, and
`client_agent_id: false` on its bound cloud options. The worker mints the attempt's credential
and sends it in create-request envVars with trusted harness context. Preflight and launch
network resolution use the same configured host. Missing delivery or excluded egress refuses
the gated launch. This configuration does not deploy or expose the ingress publicly.

## Operational capability catalog

The configured API includes the application catalog at
`/v1/applications/{application_id}/catalog`: GET `definitions` and POST `resolve`,
`search`, `discover`, `inspect` and `components/search`; the fast-track surface adds `pin`,
`render`, `publish:prepare`/`publish:complete` and `GET pins/{pin}`. `missionctl catalog`
provides corresponding `list`, `resolve`, `search`, `discover`, `inspect`, `components`, `pin`,
`render` and `publish` commands. Requests use the same trusted installation/tenant identity;
permissions remain explicit (`catalog:read`, `catalog:discover`, `catalog:inspect`).

Default composition supports list/resolve over the admitted application catalog
without additional provider credentials. Search requires a trusted
`RuntimeOptions.catalog_factory` supplying an embedding port. External discovery,
inspection and plugin/component search require their explicitly configured adapters
in the same factory. Missing adapters fail explicitly; runtime does not fabricate
credentials or choose a provider fallback.

Discovery candidates remain quarantined and inspection does not promote or execute
them. Plugin filtering preserves existing trust, host, OS, architecture and required
capability constraints. Marketplace installation is not provided by these commands.

## Agent Server

Use the sole registration file `agent_server/langgraph.json`:

```powershell
uv run langgraph dev --config agent_server/langgraph.json --host 127.0.0.1 --port 2024 --no-browser
```

`MISSION_CONTROL_AGENT_SERVER_PROFILE` selects `runtime` (default, bounded child),
`qualification` (three diagnostic graphs), or `qualification_n1` (N1 only).
Profile-denied run creation returns 403; a registered diagnostic graph is not
implicitly available to the runtime profile. These graphs never schedule missions.

Supply secrets through the operator environment; tracked `agent_server/runtime.env`
contains references only. Runtime subordinate authentication uses the exact
`BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN` signing-secret reference and scoped claims,
or the configured existing JWT verifier. Qualification uses
`BELL_LABS_AGENT_AUTH_ISSUER`, `BELL_LABS_AGENT_AUTH_PUBLIC_KEY_B64` (or PEM
`BELL_LABS_AGENT_AUTH_PUBLIC_KEY`) and its audience/algorithm settings.

An explicit `MISSION_CONTROL_AGENT_HOSTING_FACTORY=installed.module:callable`
returns the typed `HostedGraph` and exact bounded child definition. This is trusted
operator code, never selected by a request or downloaded bundle. The default
production graph resolves its configured model only when invoked; local
qualification uses deterministic factories and does not exercise a paid model.

**The runtime technical child's model (OC-R6).** The default child runs on the
installation's `child.default` Model Profile, read from `deployments/<app>/models.toml`
when the graph is first built (today `claude-haiku-5-5`, an Anthropic model). The Agent
Server environment therefore needs `MISSION_CONTROL_APPLICATION` (the application id), a
deployments root that holds that application's `application.toml` and `models.toml`
(`MISSION_CONTROL_DEPLOYMENTS_ROOT`, default `<MISSION_CONTROL_HOME>/deployments`), and the
credential of the row's vendor (`ANTHROPIC_API_KEY` for the pinned child; `OPENAI_API_KEY`
for an OpenAI row). Without an application the graph refuses to build; there is no model in
code and `MISSION_CONTROL_ASYNC_TECHNICAL_CHILD_MODEL` is gone. The vendor and model id are
part of the exact binding, so the served graph digest changed with R6 and changes with every
edit of that row: after either, re-run `missionctl lane async-graphs --agent-server URL
--scope S` against the running server and paste the printed `deep_agents_async_graphs` block
into the launch bindings (a stale digest refuses the parent's spawn). Substituting the PROOFS
§6 fallback is an edit of the `child.default` row.

`MISSION_CONTROL_AGENT_AUTHORITY_ENABLED=1` opts into the separately configured
PostgreSQL authority bootstrap. It defaults to disabled: native bounded graph
hosting does not acquire ambient application database authority.

The development command is a local service check, not proof of production hosted
persistence or restart durability. See implementation status for exact evidence.

**Topology blocker.** The pinned Agent Server (`langgraph-api==0.12.0`) has no schema
setting, applies its own unqualified migrations at startup (including `checkpoints` and
`store` tables that collide with the standalone saver/store) and needs extension and
`CREATE` privileges. It therefore cannot use a private schema of the business database,
and `mission_control_agent_server` is not created by any release. Production native
persistence needs an owner topology decision (preferred: a separate database per
installation with its own owner/login and no access to the business database) and a
license decision. See
`packages/mission-control-db-contract/runtime/AGENT_SERVER_TOPOLOGY.md`.

## Evidence

`tests/integration/postgres/test_mission_control_bootstrap_postgres.py` creates its
own disposable database and restricted login, runs actual migrations, registers and
replays the identity seed, starts the real factory, and reads through the API with
a signed JWT. It verifies missing authentication, cross-application rejection,
actual database access, and shutdown readiness. Authentication tests additionally
cover wrong issuer/audience, expiry, unsigned/tampered tokens, tenant denial, and
operator-only grants. These local proofs do not imply live Supabase deployment.

`tests/acceptance/mission_control/test_authenticated_scoped_runtime.py` also passes
with the real configured JWT verifier, restricted PostgreSQL repositories, cached
local Temporal server, and production worker composition. The scoped API admits
and launches StageGraph and GoalDirected runs through `mc.mission_run.v1` and
`mc.operation.v1`. The proof completes two StageGraph operations and four
GoalDirected operations, applies pause/resume/wait satisfaction with durable command
replay, and replays the recorded mission and operation histories. Its 30 model
events use deterministic local models; it does not call a paid provider. It requires
`MISSION_CONTROL_E2E_POSTGRES_DSN` pointing to the authorized disposable local
PostgreSQL owner connection and `MISSION_CONTROL_TEMPORAL_CLI` pointing to the
installed Temporal CLI. Run it with `pytest
tests/acceptance/mission_control/test_authenticated_scoped_runtime.py -q -s`.
These acceptance proofs are being re-run on the common component; their current
results are recorded only in the implementation status "Final qualification results"
section. Local disposable proofs never imply a live Supabase installation.

## Persisted run evidence and inputs

The configured API exposes `GET /v1/applications/{application_id}/runs/{run_id}/evidence`
and `GET /v1/applications/{application_id}/runs/{run_id}/inputs`. Both require
`workflow_run.read` and `workflow.result.read` in the authenticated scope. The first
joins persisted inspection, input-contract digests, typed results and continuation
manifest references. The second returns the frozen semantic input payloads and separately
typed `native_templates`. Native template binding comes from the durable Temporal root
start input, verified against the admitted scope/run/configuration; template skeleton
placeholders are preserved. This surface needs retained root history and does not infer
a binding from its name. The evidence summary includes `native_template_count`.

`GET .../completion-evidence?after_family_version=0&limit=100` reads committed
Stage Graph completion checks from the existing family admission journal. Its
records include exact schema/artifact digests, per-output and per-criterion reasons
when the validator recorded them. Follow `next_after_family_version` until null;
the aggregate `/evidence` includes only the first bounded page. Records are historical
observations, not a mission-wide fulfillment verdict. An older `not_evaluated`
record is preserved as such, and a validator still retrying publication may have no
committed check yet. The endpoint uses the same two read grants, checks receipt
fingerprints and scope, and never reads artifact bytes or calls providers.

`GET .../goal-completion-evidence?limit=100` returns schema checks from existing immutable
Goal Directed verification documents. Follow `next_verification_id` with
`after_verification_id`. Each record carries document/request digests, the verifier result,
and per-output/per-criterion validation. The same two read grants and run scope apply.
These receipts remain separate from reducer-owned acceptance. Multiple Goal Directed output
slots require explicit `output_bindings` mapping each declared slot to its returned durable
references. Every reference must be bound and each emitted output must pass its own pinned
schema. Existing single-output observations can omit the bindings. Deep Agents multi-output
launches require the configured `GoalNamedExecutorObservation` structured-output schema;
the [prepared binding fragment](../deployments/cloud_runtime/goal-named-output-binding.json)
does not modify any existing operator configuration. Its revision is 2; the original revision
1 schema remains registered with its unchanged digest.

Cancellation acceptance, Temporal delivery and application remain separate receipts.
If cancellation is accepted while a verifier is admitted but not yet dispatched, the
operation refuses cognition and waits for delivery. After delivery, the existing governed
cancellation path settles its claim and releases its reservation. A run remaining
`cancelling` with an accepted but undelivered command requires recovery of command/outbox
delivery; do not resume provider execution or treat the refused activity as mission failure.
The new operation workflow patch preserves replay behavior for earlier histories.

Treat `missing_terminal_result` as a materialization/reconciliation gap, not a
successful result. `unavailable` means the source is not composed; `not_recorded`
means the composed source has no matching record. A `409 run_evidence_inconsistent`
requires re-reading or reconciling conflicting durable records. Artifact bytes,
sandbox state and present checkpoint resumability are not verified by this read.
Existing transcript/checkpoint endpoints provide their separate histories.

See the [2026-10-11 reliability handoff](specs/archive/mc-surfaces-2026-10/docs/LIFECYCLE_RELIABILITY_2026-10-11.md) for
storage boundaries, provider support and limitations, and the
[cloud runtime package](../deployments/cloud_runtime/README.md) for prepared
deployment inputs and outstanding approval/readiness gates. No cloud deployment
is implied by the local tests or generated ECS review inputs.

## Reading, replaying and forking a run (tracing)

The commands below need `MISSION_CONTROL_URL`, `MISSION_CONTROL_APPLICATION_ID` and
`MISSION_CONTROL_TOKEN` in the CLI process (see "Start and use"). The flags are those of
`interfaces/cli/main.py`; the concepts are [the transcript](knowledge/provider-frames-and-transcript.md)
and [the precise fork](knowledge/precise-fork.md).

**`missionctl run inspect RUN_ID`** prints `mc.inspection.v1`. Besides the lifecycle it carries
`unit_failures` (each unit that settled failed with a typed reason, for example
`output_unparseable`, and its full failure reference), `points_incomplete` (a settlement whose
points write failed and awaits the reconciler) and `budget` (per dimension: hard cap, reserved,
consumed, pending, exhausted). A section whose source is not composed is left out or marked
unavailable, never shown as empty.

**`missionctl run transcript RUN_ID [--full] [--format jsonl|md] [--by LEVEL] [--limit N]`**
prints the run's `mc.transcript_entry.v2` entries.

- `--full` resolves the bodies entries refer to. A model request then shows what the model saw
  (the system prompt and each message, beside their `frame-body://` references); each reference
  is read once per page under a 16 MiB page budget. An `expired` placeholder is never resolved.
  It needs the artifact read grant (`workflow.result.read`); a deployment without a body reader
  answers `501`.
- `--limit` is the total number of entries (default 500). The route returns at most 5 000 per
  request; the CLI follows the page cursor until the limit is met or the run has no more.
- `--by step|turn|attempt|stage|iteration|mission` prints one JSONL line (or one Markdown
  heading) per group. `--point ID` and `--unit KEY` restrict to one point (and its children) or
  one unit; `--follow` tails new entries; `--canonical-only`, `--kinds`, `--node`,
  `--activation`, `--subordinate` and `--since CURSOR` filter.

**`missionctl run points RUN_ID`** lists cognition points as one JSON page with `next_cursor`.
`--limit` (default 100) is the total wanted; the CLI reads pages of at most 500 and follows the
cursor. Filters: `--unit-key`, `--generation`, `--node`, `--iteration`, `--cycle`,
`--session-generation`, `--kind`, `--role`, `--seedable`, `--cursor`; `--reconcile` re-derives a
run's missing points instead. `run state-as-of RUN --point ID` reads the state at a point (404
`point_state_missing` when the saver no longer holds it) and
`run replay RUN --point ID --dry-run` rebuilds one model input from the transcript and compares
digests; no model is called.

**Downloading a body.** `GET /v1/applications/{app}/runs/{run_id}/artifacts/{ref}` returns the
verified bytes of a `frame-body://sha256:<hex>?bytes=<n>&type=<media>` or `artifact://...`
reference, the reference URL-encoded in the path. The caller needs `workflow_run.read` and
`workflow.result.read`. A `frame-body://` digest must be referenced by a frame of that run in the
caller's scope (else `404 artifact_unavailable`); the media type and size are the frame's, not the
reference's; the answer is an attachment with `X-Content-Digest`, and a body over 4 000 000 bytes
is `413`. `missionctl run artifact RUN_ID REF --out FILE` does the same and prints the receipt.

**`missionctl run fork RUN_ID`** derives a new run from the latest safe Snapshot
(`--from-snapshot ID` names another).

| Flag | Effect |
| --- | --- |
| `--at stage:S2,cycle:2` or `--at iteration:3[,session:1]` | resume at that position; derived from `--point` when omitted |
| `--point ID` | seed the derived unit's cognition from that cognition point (its unit and key) |
| `--inject FILE` | the message: with `--point` the seed head's last human message, otherwise a mailbox instruction (`--instruction-file` is the older spelling) |
| `--frontier STAGE` (repeatable), `--frontier-policy close\|strict` | stages to re-run; `close` (default) adds their consumers, `strict` refuses a narrower frontier |
| `--baseline-reservation DIMENSION=AMOUNT` (repeatable) | override one dimension of the derived run's baseline hold |
| `--sponsorship-ref`, `--approval-ref`, `--reason`, `--request-id`, `--request-file` | admission claims and identity |

Without `--baseline-reservation` the derived run holds the source run's admitted baseline.
The fork is admitted and, with `--point`, seeded before its receipt is recorded; `run start` stays
separate. If the start answers `fork_seed_pending`, repeat the fork (the same request is
idempotent), then the start. A saver that did not answer is `503 cognitive_seed_unavailable`;
position, closure and seed refusals are 422 with a code (`fork_position_unavailable`,
`frontier_not_closed`, `cognitive_seed_not_supported`). The kernel route
`POST /run-control/v1/runs/{id}/forks` refuses a `message`.

## Owner setup and preflight

Run `missionctl preflight mission.yml --json` before starting a provider mission. Its
`mc.preflight.v1` report includes owner steps, generated paste blocks, freshness and readiness.
Missing owner setup returns exit 2; launch refuses with `PREREQUISITES_UNMET` and the same list.

To prepare the human procedure, run
`missionctl setup claude_managed --manifest mission.yml --script owner-setup.sh`, then review
and run `bash owner-setup.sh`. `cursor`, `anthropic`, `openai` or an individual lane are accepted.
The wizard opens provider portals, prints steps, waits for owner confirmation and asks the
server to verify. It never captures credentials. Use `--json` to inspect without generating
or running a wizard. An account-only checklist without `--manifest` does not prove a mission's
environment is ready.

Provision an owner credential with `prerequisite.read`, `prerequisite.attest` and
`prerequisite.verify`; manifest setup also needs manifest read and catalog grants. Do not add
these attestation grants to ordinary coordinator credentials. Manual attestation uses
`missionctl prereq attest ID --definition-digest DIGEST [--value env_ID]`; the value must be a
public identifier. `prereq verify` accepts the same identity/digest and runs the installation's
trusted probe. Missing probes return `probe_unavailable`; this is not successful verification.

Provider concurrency and v2 lane alternatives are described in [Placement admission](knowledge/placement-admission.md). Configure MISSION_CONTROL_PLACEMENT_LIMITS as per-profile JSON before starting workers. Alternatives require recorded lane qualification and fresh scoped owner evidence; runtime capacity refusal waits on Temporal timers.

The worker accepts explicit trusted external source registrations through
`MISSION_CONTROL_SOURCE_WATCHES` (JSON list, at most 16). See
[watcher source configuration](knowledge/watchers.md) for the required admitted
execution binding and resource fields. Registrations are sampled by the existing
Temporal watcher activity; they cannot create or revive runs. GitHub polling uses
configured GitHub App credentials. Verified provider webhooks persist normalized
inbox evidence. The opt-in base-worker drainer consumes this inbox through normal
admission and bounded reconciliation; see the Run 2 configuration below.

For initial provider ingress evidence, use the bounded, explicit operator procedure in
[Owner probe bootstrap](knowledge/owner-probe-bootstrap.md). Its paid execution flag is
separate from ordinary launch; review the admitted plan and trusted probe bindings first.

## Run 2 operator configuration

These entrypoints are offline implemented; their exact deployed installation remains
unqualified. See [Run 2 evidence and remaining gates](specs/archive/materialization-observation-2026-10/runs/RUN-2-REPORT.md).

The local run profile accepts optional `deployment_dir`, resolved from the profile's
directory. It selects that directory's target and release lock. Omission preserves the
existing deployment lookup. Do not copy a Windows virtual environment into WSL.

`python -m mission_control.bootstrap.preflight compose-bindings --base <bindings.json>
--selections <reviewed-selections.json> --out <resolved.json> --summary-out <identity.json>`
emits a separate, secret-free identity summary. Repeated `--digest-file POINTER=PATH`
arguments bind the SHA-256 of reviewed file bytes to explicit selection pointers.
They do not discover owner choices or prove a container image, agent version, loaded
configuration, materialization, serving model or fresh prerequisites. Unresolved values
refuse output. Keep selected files and summaries outside source control when private.

`missionctl token mint --auth-config <public-config.json> --private-key-file <key.pem>
--key-id <kid> --subject <configured-subject> --tenant <uuid> --scope <permission>
--out <new-private-file>` writes an attenuated token without printing it. Repeat `--scope`
for additional already-authorized permissions. Default expiry is 900 seconds; the maximum
is 3600. The selected public verifier must validate the token. Existing output files are
not overwritten. Keep the key and token private; on Windows use a private directory ACL.

Codex owner login requires `MISSION_CONTROL_CODEX_HOME_MODE=owner` and an explicit
`MISSION_CONTROL_CODEX_OWNER_HOME`. Topology guards always apply. The explicit host
readiness command probes that home and `MISSION_CONTROL_CODEX_BINARY`; runtime auth
admission enables the vendor status probe with `MISSION_CONTROL_AUTH_STATUS_PROBE=true`.
Isolated homes never copy owner credentials.
For an explicitly selected Codex API-key route, use an `mc.auth_profile.v1` profile
with `route=api_key`, `billing_mode=api` and an approved environment credential ref.
The key must reach the actual Linux worker process environment; its presence only in
Windows Settings or a repository `.env` is insufficient for the Codex child launcher.
Use a process-only transfer, never a command-line value or generated owner auth file,
and remove competing Codex credential variables from the selected child environment.
The chosen native Node directory must be on PATH for an npm-installed Codex binary.
The current app-server pin is 0.162.1. The versioned example is
[Codex 0.162.1 bindings](../deployments/examples/manifest-launch-bindings.multi-provider.codex-0.162.1.example.json).
Old examples and sealed bindings remain immutable and may fail the new compatibility guard.

`MISSION_CONTROL_WORKER_ROLE=lane` serves only explicitly configured non-base lane queues.
It cannot poll root, coordinator, artifact, maintenance, watcher or linked-run queues.
Use exactly one base worker for an application and namespace. For split hosts, set
`MISSION_CONTROL_SPLIT_HOST=true`; choose S3 or an actually shared payload root containing
`.mission-control-payload-root` matching `MISSION_CONTROL_PAYLOAD_SHARED_ID`. Matching
local path strings alone are insufficient. The marker check does not prove a remote mount.

`INGRESS_DRAINER_ENABLED=true` enables the drainer on the base worker. Supply reviewed
`INGRESS_MANIFEST_PATHS`, normal manifest launch bindings and the exact ingress origin.
Remote requests use ordinary grants, prerequisites and admission. Optional LISTEN uses
`INGRESS_LISTEN_SECRET_REF`; a five-second PostgreSQL polling fallback remains active.
Verified webhook hints are durably queued for the current native turn. Its fenced owner
persists a finite native-history pass before acknowledging the hint; only that durable
acknowledgment permits wake delivery. Each pass is bounded to 5,000 frames and 15 seconds,
with at most three passes per segment. Timeout or overflow remains pending. OpenAI uses
a bounded full-turn rescan; Cursor Cloud requires an authoritative terminal native record
and does not claim complete SSE history. Revoked or expired binding hints receive an
auditable rejection, permitting closure without acknowledgment or wake. Neither a hint
nor a wake accepts the mission or sends a new provider turn. Live qualification is unrun.

Artifact custody additionally needs `INGRESS_QUARANTINE_BUCKET`, `INGRESS_CUSTODY_BUCKET`,
`INGRESS_STORAGE_CREDENTIAL` and `SUPABASE_URL`, with separate buckets. Upload completion
does not establish custody: the worker checks bytes, digest, size, scope and expiry before
normal immutable registration. Review/publication retain their separate authority.

Cursor Windows support (`MISSION_CONTROL_CURSOR_WINDOWS`), missing-output followup
(`CURSOR_MISSING_OUTPUT_FOLLOWUP`) and delayed cost reconciliation
(`CURSOR_COST_SETTLEMENT`) default off. Unknown charged costs retain the reservation;
bounded reconciliation may leave an explicit liability. Local billing after bridge
shutdown uses a separately owned read-only HTTP client and the existing configured
Cursor key. Complete persisted native history must establish the exact agent and billing
UUIDs first. Responses are bounded to 15 seconds, 1 MiB and 5,000 entries; partial,
duplicate or mismatched evidence remains unknown. No bridge is started or resumed for
billing. No flag grants qualification.

`MISSION_CONTROL_CURSOR_BRIDGE_SWEEP_SCOPES` optionally supplies a JSON list of at most
16 canonical tenant request scopes for the selected application. Empty (the default)
does nothing. When the local Cursor lane is composed, startup examines at most 64
active/released leases across those scopes under a 30-second deadline. It checks the configured
host allocator/root, serializes against new acquisition, protects newer/active/shared
holders, and shuts down only the exact validated loopback endpoint. It preserves files
and records confirmed shutdown or discovery absence in the existing lease detail so
completed candidates do not monopolize later batches. It logs bounded per-lease
dispositions; timeout or unavailable endpoints remain cleanup
liabilities. Active inspection rechecks the lease fence, execution generation, session
owner, journal anchor and exact native session, then notifies only the matching running
operation workflow in its stored cluster. Notification is a recovery hint; ordinary
workflow retry and reattachment still own progress. Live owners, ambiguous evidence,
missing/closed workflows and incomplete custody retain the active lease. Expiry or native
completion alone never authorizes shutdown or release. The installed worker-kill drill
remains unqualified.

Local Cursor file and bridge operations revalidate the current scoped workspace lease.
An expired active Cursor lease still blocks replacement: recover its exact session or
complete an authoritative release before allocating a successor. Expiry alone does not
prove that the detached process stopped. A stale owner fails before staged instruction
or continuation file access, including when its bridge client was already cached.

Managed pause/resume can explicitly select `decision.budget_gate` with schema version
`mc.managed-budget-control.v1` and mode `budget_gate`. A hold accepts no resume fields.
Resume must include `hold_command_id` and `hold_command_issuer`; its optional positive
`target_cap_minor_units` cannot exceed the original binding ceiling. This path needs
the operation's existing currency reservation and fresh authority, approval and fence
checks. An accepted command, matching native cap and observed budget boundary are
separate facts. Ambiguous updates remain in the durable journal and use readback only;
do not manually repeat them or raise a cap to make cancellation finish. Partial family
fan-out can leave held children requiring reconciliation. Existing boundary pause
remains the default. This wiring does not promote live qualification.

For Temporal Cloud, startup checks required search attributes through Cloud Ops using
`TEMPORAL_CLOUD_API_KEY`; local Temporal keeps the Operator API. Prepare the exact dev
namespace proposal with `python -m scripts.temporal_cloud.configure_search_attributes
--plan <new-private-plan.json>`. Planning is read-only and refuses an existing output.
After approval, the same command with `--apply` submits only the reviewed additions;
configuration drift refuses the update. Verify completed namespace readback before
running the separately authorized `python -m scripts.temporal_cloud.probe --execute-noop`.
The probe requires the exact Cloud target/address/namespace environment and has a
60-second workflow execution limit. A submitted update is not readiness proof.

Review the [slim ingress plan](../deployments/ingress-vercel/README.md) and
[AWS worker plan](../deployments/worker-aws/README.md) before any deployment. Current
resource, secret, network, namespace and spend authority is still required. Common
component 1.4.2 adds the reviewed launch-idempotency correction over frozen 1.4.1.
See the Run 2 report for exact installer/admission proof; both live application
attestations still report 1.3.0. New seed bundles are not an installation receipt.

When a protocol lane cannot establish whether native creation or a turn was accepted,
cancellation preserves the dispatch uncertainty. A cancellation activity carrying its
real execution attempt can record an `ambiguous_native_effect` unit incident through
the existing fenced lineage authority. Inspect that incident before using the privileged
`reconcile-unit` operation; a missing incident cannot be replaced with an invented one.
The accepted `abandon_unit` decision disposes of the operation through normal cancellation
without contacting the provider. It does not establish native cancellation or zero usage:
the settlement retains an `operator_abandonment` record with the incident and decision
identities, unknown native outcome and usage, and no provider acknowledgement. An empty
attributed usage map is not evidence of no spend. Separately unsettled consequential effects
remain pending. Repeated cancellation retains this distinction, and workspace cleanup
retains abandoned or ambiguous native state for subsequent evidence reconciliation.

For an existing `cancelling` StageGraph whose exact Temporal executions have already
closed, the normal authenticated API provides
`POST /v1/applications/{application_id}/runs/{run_id}/recover-closed-workflow`.
It requires the scoped `workflow_run.terminalize` permission and a JSON body containing
`schema_version: "mc.closed_workflow_recovery.v1"`, a fresh UUID `request_id`, and the
current `expected_version`. If supplied, `Idempotency-Key` must equal `request_id`.
The caller cannot supply settlement or workflow-closure facts. The server reads the
exact root, family, operation and continuation histories, checks their latest execution
identities, and joins the persisted family, claims, bindings, native sessions and turns.
Unresolved producer, dispatch, budget, effect, wait or boundary-command authority refuses
recovery. This bounded repair supports settled native session-lane producers only.

An accepted recovery uses the existing cancellation terminalization reducer and retains
the exact closed-execution evidence in the transition. It neither restarts workflows nor
dispatches provider work, and it does not establish provider cancellation acknowledgement
or human acceptance. The API must have its trusted Temporal observer configured;
otherwise it fails closed. After a timeout, inspect
`GET /v1/applications/{application_id}/runs/{run_id}/closed-workflow-recovery/{request_id}`
under the same authenticated actor, and inspect the run before taking further action.
An accepted identical request returns its retained result; reusing an identity for a
different request conflicts. A missing result alone does not prove the original request
has stopped. Local tests and saved-history inspection do not qualify a live recovery.

## Knowledge gateway configuration (Sprint V, SV-16/SV-17)

Mission Control reaches an application's knowledge service only through K01
`ks.knowledge_operation.v2` on the Knowledge Services executor. The lane is composed
by `bootstrap/composition.py::compose_knowledge_lane` from these settings; with none set
it is not composed, and with any set (or `KNOWLEDGE_GATEWAY_REQUIRED`) the first four are
required and a refusal names only the missing variables:

| Setting | Meaning |
| --- | --- |
| `KNOWLEDGE_BINDING_URL` | Executor base URL serving `/knowledge-operation/v2` |
| `KNOWLEDGE_BINDING_AUDIENCE` | Exact K07 credential audience the executor expects (a K01 `Name`, e.g. `knowledge-services-executor.<app>`) |
| `KNOWLEDGE_ISSUER` | Credential issuer (the executor pins it with its JWKS; a K01 `Name`, e.g. `mission-control.<app>`, never `/`) |
| (API process) | The API composes the operator review route (`POST /runs/{run_id}/knowledge-reviews`, `missionctl knowledge review`, operator MCP `knowledge_review`) from these same settings: it holds the issuer key and mints each reviewer's K01 credential. The reviewer must hold `knowledge.review` and must not be the run's launcher, a revision author, the producer or an evaluator; the decision must be cited by a trusted assessment of that run |
| `KNOWLEDGE_COMPONENT_INSTALLATION_ID` | The KS component installation the executor installs (its `KS_KNOWLEDGE_BINDINGS_JSON` `installationId`); every K01 origin names it. Required with `KNOWLEDGE_GATEWAY_REQUIRED`; unset otherwise means the MC installation id |
| `KNOWLEDGE_ISSUER_KEY_FILE`, `KNOWLEDGE_ISSUER_KEY_ID` | Active Ed25519 signing key (file path only; never printed) |
| `KNOWLEDGE_ISSUER_RETIRING_KEY_FILE`, `KNOWLEDGE_ISSUER_RETIRING_KEY_ID` | Optional retiring key, published but never used to sign |
| `KNOWLEDGE_CREDENTIAL_LIFETIME_SECONDS` (300), `KNOWLEDGE_CREDENTIAL_SKEW_SECONDS` (30) | Credential window |
| `KNOWLEDGE_SUBJECT`, `KNOWLEDGE_DESCRIBE_TENANT` | Credential subject and the tenant of the `describe` preflight |
| `KNOWLEDGE_GATEWAY_MAX_POLLS`, `KNOWLEDGE_BINDING_TIMEOUT_SECONDS` | Bounded receipt-first polling and the HTTP timeout |
| `KNOWLEDGE_GATEWAY_REQUIRED` | Refuse startup when the lane cannot be composed |

The binding id, apply contract and payload layout are not settings (OC-R4): they are the
application's profile, `deployments/<app>/application.toml` `[knowledge]`, read for the
composing application from the deployments root (`MISSION_CONTROL_DEPLOYMENTS_ROOT`, default
`<MISSION_CONTROL_HOME>/deployments`). An application without a profile fails composition;
`KNOWLEDGE_BINDING_IDS` is retired.

The executor side needs the component `knowledge_verification` 2.4.0 or later. SV-17
retired the Knowledge Services `verification.v1` claims, report, metric, adjudication,
audit-bundle, semantic, run/case read, drift and recovery surfaces; Mission Control must
not call their old `/v1/verification/*` routes or the internal
`/v1/system/verification-drift-*` queue. The K01 `verify.claims` operation now answers
`SCHEMA_UNSUPPORTED` (the executor's file-store verifier chain behind it was retired), so
the `verify_claims` knowledge tool receives a typed refusal until a component-native
replacement exists. Removed paths are listed in the
[removal guide](specs/archive/mc-surfaces-2026-10/docs/REMOVAL_GUIDE.md#knowledge-services-verificationv1-retirement-sv-17-2026-10-25).

### Canonical annex: `ks.knowledge_operation.v2` operations after SV-17

K01 is the only Knowledge Services contract Mission Control uses for verification and
knowledge effects. The schema authority is Knowledge Services
(`packages/knowledge-operation-protocol`, published JSON Schemas and golden vectors); the
byte copies under `tests/fixtures/knowledge_protocol` are verification fixtures, not a second
authority.

| Operation | Knowledge Services behaviour (component `knowledge_verification` 2.4.0) | Gateway use |
| --- | --- | --- |
| `report.register` | Binds the effect, opens a run, registers evidence and the report against its K08 kind | `report_register` tool |
| `report.assess` | Independent census and aggregation; refuses `INDEPENDENCE_UNPROVEN` without an auditor | Node-completion assessment |
| `report.derive` | Deterministic compiler over the exact revision | `report_derive` tool |
| `knowledge.read` | Exact revision package with body/ledger digests re-verified | `knowledge_read` tool, exact delivery |
| `knowledge.apply` | Exact-use admission inside the native transaction (AI Engineer AIDB guard; Biotech outbox, `pending_dispatch` until the BKS ack verifies); K08 use classes enforced, official/consequential use without `exactUse` refuses `REVIEW_REQUIRED` | `knowledge_apply` tool |
| `verify.claims` | Retired in SV-17 with the executor's file-store verifier chain; answers `SCHEMA_UNSUPPORTED` | `verify_claims` tool receives the refusal |
| `operation.get` / `cancel`, `receipt.get`, `describe` | Durable handles, receipt-by-effect-key lookup, binding descriptor | Gateway settlement and preflight |
