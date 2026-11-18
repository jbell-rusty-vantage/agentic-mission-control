# Developer tooling

How the Python toolchain is set up, what each tool is for, and the `make` targets that
drive it. Operational semantics (installation identity, roles, `mission-db`) stay in the
[operator guide](MISSION_CONTROL_LOCAL_API.md); this page is about the developer loop.

## Quick start

```powershell
make install          # uv sync (runtime + dev + dbcontract + biotech groups)
make hooks            # install the git pre-commit hook (prek)
make infra-up         # docker compose up -d, then wait until healthy
make check            # lint + format check + ty + deptry + architecture + unit + Biotech + lane conformance + skills manifests
```

`make help` lists every target with a one-line description. Variables are overridable
per call (`make server PORT=8100 RELOAD=1`, `make infra-logs SERVICE=temporal`).

## Toolchain

| Tool | Role | Command | Speed |
| --- | --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Environment, lockfile, script runner | `uv sync`, `uv run`, `uv lock` | — |
| [ruff](https://docs.astral.sh/ruff/) | Linter and formatter (flake8, isort, pyupgrade, black, bandit subset) | `make lint`, `make fmt` | < 1 s |
| [ty](https://docs.astral.sh/ty/) | Fast type feedback (editor, pre-commit, `--watch`) | `make typecheck-fast` | ~3 s |
| [mypy](https://mypy.readthedocs.io/) | Authoritative type gate (pydantic plugin) | `make typecheck`, `make typecheck-daemon` | ~80 s cold |
| [deptry](https://deptry.com/) | Declared-vs-imported dependency drift | `make deps-check` | ~1 s |
| [prek](https://github.com/j178/prek) | Git hooks (Rust reimplementation of pre-commit) | `make hooks`, `make precommit` | — |
| pytest + asyncio, xdist, timeout, cov; hypothesis | Tests | `make test-unit`, `make test-biotech` (integrations/biotech/tests), `make test-conformance`, `make coverage` | — |
| [uv-secure](https://pypi.org/project/uv-secure/) | Vulnerability scan of `uv.lock` | `make audit` | network |

### Why two type checkers

mypy with the pydantic plugin is the gate: it understands this codebase fully and runs in
`make ci`. ty is Astral's Rust checker; it finishes in seconds and powers the editor and
the pre-commit hook. Where ty still misreads LangGraph generics or dataclass default
factories, those rules are downgraded to warnings in `pyproject.toml` (`[tool.ty.rules]`)
so the fast loop stays green without hiding the signal. Re-tighten them as ty matures.

### Lint policy

Rule families and the reasons for each ignore are documented inline in
`[tool.ruff.lint]`. Prefer fixing over `# noqa`; when an exception is intentional, the
comment must say why (`# noqa: DTZ001 - naive input is the behaviour under test`).
`ruff format` is the only formatter; nothing else rewrites code.

### Dependency groups

| Group | Installed by | Contents |
| --- | --- | --- |
| (runtime) | `uv sync` | the application |
| `dev` | `uv sync` (default group) | ruff, mypy, ty, deptry, prek, pytest and plugins, hypothesis |
| `dbcontract` | `make install` | `mission-db` installer package |
| `biotech` | `make install` | Neo4j/GraphQL domain adapters; the unit suite imports them, plain `uv sync` stays independent |
| `notebooks` | `uv sync --group notebooks` | Jupyter, ipykernel, polars |

`uv run` syncs the environment to the default groups before running, which removes
optional groups you added by hand. The Makefile therefore uses `uv run --no-sync` and
`make test` adds `--group biotech` explicitly.

## Daily loop

1. Editor: Cursor/VS Code with the recommended extensions (`.vscode/extensions.json`,
   local only) gives ruff-on-save and ty diagnostics inline.
2. Before commit: the prek hook runs ruff (fix + format), ty, deptry, `uv lock` and the
   standard hygiene hooks. `make precommit` runs the same against every file.
3. Before pushing or handing off: `make ci` (adds mypy, lock check and the docs link
   checker). `make test` and the integration/acceptance targets need the compose stack.

## Infrastructure map

| Component | Make target | Host endpoint |
| --- | --- | --- |
| Application PostgreSQL 16 + pgvector | `make db-up`, `make psql` | `127.0.0.1:55432` (`belllabs/belllabs`) |
| PostgreSQL 17 + pgvector (local stack; opt-in, TLS on) | `make local-infra` | `127.0.0.1:55434` (`belllabs/belllabs`) |
| Redis 7.4 | `make redis-up`, `make redis-cli` | `127.0.0.1:16379` |
| Temporal 1.31 server | `make temporal-up`, `make temporal ARGS="..."` | `127.0.0.1:7233` |
| Temporal UI | `make temporal-ui` | `http://127.0.0.1:8080` |
| Temporal-only stack | `make temporal-only-up` | same ports; never alongside the main stack |
| Mission Control API (`mission-control api`) | `make server`, `make health`, `make openapi` | `http://127.0.0.1:8000` (`/docs`) |
| Temporal worker (`mission-control worker`) | `make worker` | — |
| Local production-shaped stack (API + worker, background) | `make local-install`, `make local-up`, `make local-eval`, `make local-down` | `http://127.0.0.1:<PORT>` |
| Agent Server (`langgraph dev`) | `make agent-server` | `http://127.0.0.1:2024` |
| Coordinator MCP (Streamable HTTP) | `make mcp-server` | `http://127.0.0.1:8010/mcp` |

`make dev` starts the compose stack, waits for health (`scripts/dev/wait_for_services.py`)
and prints the per-terminal commands. `make up` chains infra, preflight and the API.
`make infra-down` removes containers but keeps volumes; there is deliberately no target
that deletes volumes.

### Process entrypoint

`mission-control` is the one console script for the process roles (`[project.scripts]`,
`src/mission_control/bootstrap/cli.py`): `mission-control api [--host H] [--port P] [--reload]`
serves the uvicorn factory `mission_control.bootstrap.api:create_app` on the
`api_loop_factory` loop, `mission-control worker` runs the installation-bound worker and
`mission-control preflight [...]` the read-only check with its own arguments. `make server`,
`make worker` and `make preflight` call it in its module form
(`python -m mission_control.bootstrap.cli`), which works before the environment is re-synced;
the bare command exists after `make install`. The container images run the same commands.

### Local production-shaped stack

One application's API and worker, started from the real entrypoints against local
infrastructure only (a loopback PostgreSQL 17 and the local Temporal server). Nothing reads the
repository `.env`: the processes get operating-system essentials plus the installation's own
env file, whose `MISSION_CONTROL_HOME` is the installation directory.

```powershell
make local-infra                  # only PostgreSQL 17 + pgvector, 127.0.0.1:55434
make local-install                # APP=ai-engineer (default) or biotech; RECREATE=1 rebuilds
make local-up PORT=8020           # background API + worker; waits for /health/ready and a poller
make local-eval                   # consumer-surface scorecard -> <dir>/eval/scorecard.md
make local-down                   # stops only what local-up started (pid + creation time)
```

`make local-install` (`scripts/dev/local_installation.py`) writes everything under the ignored
`.scratch/local-stack/<app>/`: a database `mc_local_<app>` with the common component installed by
`mission-db` (the release is pinned in the script: the newest with a release integration test),
the runtime phase, the seed bundles, the restricted logins and the tenant; the lexical capability
search projection; local bundle custody; a sealed binding, `deployment.json`, a generated
operator key with its public JWKS and `operator-token.txt`; `mission-control.env`; and the
Temporal namespace `mc-local-<app>` with the Search Attributes. A rerun verifies and reuses.
It refuses an admin DSN that is not loopback (`MC_LOCAL_STACK_ADMIN_DSN` names another loopback
cluster) and an output directory Git does not ignore. Three things to know:

- **PostgreSQL 17 is required.** `mission-db` holds on the compose `application-postgres` (16),
  so the stack uses the opt-in `application-postgres-17` service.
- **A plain PostgreSQL has no Supabase Storage.** `seeds/common` carries two Storage bundles and
  the application's cognition profiles depend on one, so the installer creates a clearly
  labelled synthetic `storage` schema (the shape the bundle tests use) for the seeds to apply.
  Local custody is the filesystem (`bundles/`).
- **The worker needs bytes that are not in this repository:** the capability resource owner's
  pinned modules (`workspace://.tools/...`, BellLabs `biotech/.tools`), the pinned skill bundle
  of the checkout's `.runtime/capability-bundles`, and Node. The installer records whether
  they are present (`installation.json`, `worker.ready`); `make local-up WORKER=auto` (default)
  starts the worker only then, `WORKER=on` requires it and `WORKER=off` leaves it out.

No provider credential is written (explicit blanks), so the stack answers discovery, compile and
inspection; a mission that needs a model also needs a key added to the env file by hand and
operator launch bindings (`MANIFEST_LAUNCH_BINDINGS_PATH`).

Containers: `deployments/docker/Dockerfile` builds the `api` and `worker` targets from the uv
lockfile (`make image`), and `deployments/docker/compose.yml` runs both from an env file and a
mounted deployment directory. `make local-container-env` derives those two from a local
installation (container paths, `sslmode=require` DSNs on the compose network, the Temporal
address). CI (`.github/workflows/ci.yml`) runs `make ci` and, in a second job, brings this stack
up on a PostgreSQL 17 service and a Temporal dev server and uploads the scorecard.

### Temporal SDK 1.34 (FT-G7, 2026-10-07)

`temporalio[opentelemetry]>=1.34,<2` (locked 1.34.0; was 1.30.0). What changed for this repo:

- **Breaking (1.31):** payload size warnings moved from the data converter to
  `Client.connect(payload_limits=PayloadLimitsConfig(payloads_warn_size=..., memo_warn_size=...))`.
  Every client is created by `adapters/temporal/client.py` (`connect_temporal`), which sets
  512 KiB / 2 KiB; nothing configures limits on a `DataConverter`.
- **Target selection:** the local `make temporal-up` server is the default even when
  `TEMPORAL_CLOUD_API_KEY` is in `.env`. `TEMPORAL_TARGET=cloud` connects with `api_key=`
  and `tls=True` to `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` (a deployment naming another
  frontend is refused). `make preflight` prints the target per application, never the key.
- **Worker Deployment versioning:** `make worker` polls as
  `WorkerDeploymentVersion(TEMPORAL_DEPLOYMENT_NAME="mission-control", build_id=<package version or TEMPORAL_BUILD_ID>)`
  with default behavior `AUTO_UPGRADE`, and promotes its version to current on start
  (`TEMPORAL_PROMOTE_ON_START=false` leaves promotion to the CLI;
  `TEMPORAL_WORKER_VERSIONING=false` runs unversioned workers). A roll is: start the new
  worker, it becomes current, stop the old one; running executions move on their next task,
  which is why every command-structure change stays behind `workflow.patched` and the replay
  suite (`tests/integration/temporal/test_replay_histories.py`, histories captured on 1.30)
  must pass. `tests/integration/temporal/test_worker_versioning.py` proves the drain against
  the local server.
- **Search Attributes:** `make temporal-up` now runs `make temporal-search-attributes`, which
  registers (idempotently) and lists the BellLabs core plus `mc_mission_id`, `mc_lane`,
  `mc_phase` (Keyword) and `mc_run_id`, `ForkedFromRunId` (KeywordList). The postgres12
  visibility store has 10 Keyword / 3 KeywordList / 3 Int columns per namespace; the core
  uses 7 Keyword + 2 Int, so these two identifiers are KeywordLists (equality filters work
  unchanged) and no Keyword column is left free.
- **Not adopted:** `workflow.uuid7()` (no workflow hand-rolls a UUIDv7; the helper in
  `contracts/identities.py` runs outside workflows), Workflow Streams,
  `signal_with_start_workflow`, `OpenTelemetryPlugin`, Workflow Pause and the Deep Agents
  Temporal plugin (the 1.33 `deepagents.retire-result-cache` patch is irrelevant here).
  Whether a self-hosted server's Update limits match Temporal Cloud's is UNVERIFIED.
- **Rollback:** pin `temporalio[opentelemetry]==1.30.0` in `pyproject.toml`, `uv lock`, and
  restore `Client.connect(address, namespace=...)` without `payload_limits` in
  `adapters/temporal/client.py` (1.30 has no such argument); set
  `TEMPORAL_WORKER_VERSIONING=false` before rolling back so workers stop polling as a
  deployment version. Registered Search Attributes can stay.

### Database component targets

`make db-inspect`, `db-plan`, `db-verify`, `db-runtime-plan`, `db-seed-plan` and
`db-snapshot` wrap read-only `mission-db` commands for `APP=biotech` (default) or
`APP=ai-engineer`. `make db-apply` writes to a live target and refuses to run without
`PLAN_DIGEST=...` and `CONFIRM_TARGET=<project_ref>:<installation_id>`; it still requires
owner authorization as described in the operator guide.

### Fast-track targets

`make skills-check` (part of `make check`) fails when a coordinator bundle's generated
`references/guide-*.md` differs from the guide, an imported skill copy differs from its record, or a
`skills/*/manifest.json` digest drifted from the files on disk. After editing a guide page run
`make skills-references`, bump the bundle's version, then `make skills-manifest`, which rewrites the
digests. `make seeds-validate` fails when a seed
Capability Pin does not parse or a tools/list digest drifted. `make lane-qualify PROFILE=cursor_local`
(or `cursor_cloud`) runs the offline Cursor lane suites; `LIVE=1` adds the paid drill and needs
`CURSOR_API_KEY` and a finite `MC_PAID_BUDGET_USD` (see
[lane qualification](qualification/lanes/README.md)). Tests marked `common_db` need a disposable
PostgreSQL 17 with pgvector through `MISSION_CONTROL_TEST_ADMIN_DSN` (the compose
`application-postgres` is PostgreSQL 16 and cannot install release 1.1.0; the opt-in
`application-postgres-17` of `make local-infra` can). The owner mission
procedure is in the [owner fixture runbook](specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md).

## Helper scripts (`scripts/dev/`)

| Script | Purpose |
| --- | --- |
| `make_help.py` | renders `make help` from `##` comments |
| `wait_for_services.py` | waits for compose health; fails fast on a one-shot job error |
| `temporal_search_attributes.py` | registers and lists the Search Attributes on the local Temporal namespace |
| `env_check.py` | compares variable names in `.env` with `.env.example` (never values) |
| `local_installation.py` | prepares a local production-shaped installation of one application (`make local-install`) |
| `local_stack.py` | starts, evaluates and stops that installation's API and worker (`make local-up`, `local-eval`, `local-down`) |
| `clean_caches.py` | removes tool caches and coverage output, never `.venv` or volumes |

`temporal_search_attributes.py`, `local_installation.py` and `local_stack.py` use the project
environment; the others are stdlib-only so they run identically from PowerShell, Git Bash, WSL
and the Cursor cloud image.

## Canonical workspace resource owner

In BellLabs, run Mission Control from `platform/mission-control`. Capability locators
remain `workspace://.agents/...` and `workspace://.tools/...`; their owner is the
physical `BellLabs/biotech` directory when `MISSION_CONTROL_APPLICATION` selects a profile
whose `[installation] capability_workspace_root` names it (both checked-in profiles do,
`../../biotech`); with neither that nor `MISSION_CONTROL_WORKSPACE_ROOT` (`.env` applies) a
locator that needs the owner fails with `InstallationDefaultUnavailable` (OC-R4). Set
`MISSION_CONTROL_WORKSPACE_ROOT` before starting an installed deployment to select a different
resource owner. This root is
separate from `MISSION_CONTROL_HOME` (operator configuration and deployment assets).
No platform navigation aliases are required; pinned capability bytes/digests remain authoritative.
