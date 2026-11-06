---
type: Research Note
title: "Slice S0 audit: the local harness path on the owner's machine (2026-10-12)"
description: "Process topology, task-queue routing, Temporal Cloud path, machine state, missing inputs and gates, a step-by-step runbook and issue-ready gaps for running claude_agent_sdk, codex and cursor_local through Mission Control locally."
tags: [mission-control, research, materialization-observation]
---

# S0 — the local harness path: audit (2026-10-12)

Read-only audit of `platform/mission-control` (branch `main`, HEAD `2d20f62`, 154 dirty paths incl. component 1.3.0 / migration 0034). No files edited, no paid calls, no logins. Machine probes: `wsl -l -v`, a WSL tool probe script, Windows tool versions, `.env` key names (values never printed; only booleans about shape), `missionctl --help`, `preflight --help`, and the read-only `preflight readiness` gate on a scratch profile (`research3/s0-profile.json`, reports `readiness-{Linux,Windows,bio}.json` beside this file).

S0 = an orchestrating agent session on Windows 11 (Claude Code / Codex / Cursor) launches Mission Control missions that run `claude_agent_sdk`, `codex` and `cursor_local` on a local worker, under local Temporal (`make temporal-up`) or Temporal Cloud (`TEMPORAL_TARGET=cloud`), then waits/is woken and intervenes (cancel, inject, fork). Decision R13 (`docs/specs/archive/materialization-observation-2026-10/DECISIONS.md`) created this slice; it has no issue of its own yet.

---

## 1. Process topology

### What exists (code facts)

| Process | Entry | Notes |
| --- | --- | --- |
| API | `uvicorn mission_control.bootstrap.api:create_app --factory` (`make server`), or `bootstrap.realtime:create_asgi_app` for the `/missions` Socket.IO | Authors launch inputs from `MANIFEST_LAUNCH_BINDINGS_PATH` (`bootstrap/manifests.compose_manifest_launch_inputs`); binds each run to its Temporal cluster (`run_cluster_binding`, 0032); runs the subscription relay only with `MISSION_CONTROL_SUBSCRIPTION_RELAY=1`; lists lanes from a describe-only registry mirrored from `CURSOR_API_KEY`, `MISSION_CONTROL_CLAUDE_LANE`, `MISSION_CONTROL_CODEX_LANE`, `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES` (`api.py:605`). Loads capability pins on its host (needs the workspace root). |
| Worker | `python -m mission_control.bootstrap.worker` (`make worker`) | **Monolithic; there is no worker role setting.** One process per application polls: `<base>-coordinator-family-stagegraph`, `<base>-coordinator-family-goal-directed`, the root queue (MissionRunWorkflow) if distinct, `<base>-agent-cognitive` (operation.execute/cancel, `lane.*`, `continuation.*`), `<base>-generic-artifact`, `<base>-linked-runs`, `<base>-maintenance` (frames expire + daily Schedule), plus every queue in `MISSION_CONTROL_LANE_TASK_QUEUES` (same activities as cognitive) (`adapters/temporal/worker.py`, `bootstrap/worker.py:354-512`). `<base>` = deployment stagegraph queue minus `-coordinator-family-stagegraph`. Needs runtime DSN, family-writer DSN and a checkpointer DSN on the same DB host/port/path; `COORDINATOR_LAUNCH_ENABLED=true`. Serves the Kernel Hook callback on `127.0.0.1:47555` (cursor_local). One `ApprovalBroker` per process. Polls as Worker Deployment version `mission-control/<package version>` and promotes on start. |
| Temporal | `make temporal-up` (Docker Desktop: Temporal 1.31 + PG16 persistence + UI :8080) | 127.0.0.1:7233, namespace `default`; `make temporal-search-attributes` registers `mc_*` attributes; worker verifies them before polling. |
| App PostgreSQL | **PG17 required** (release ≥1.1.0): container `mc-ft-disposable-pg17` on 127.0.0.1:55433 | compose `application-postgres` (55432) is PG16 and cannot install it. |
| Redis | 127.0.0.1:16379 | only for `MISSION_SOCKET_REDIS_FANOUT`. |
| Coordinator MCP | `python -m mission_control.interfaces.mcp` (`make mcp-server`, :8010/mcp) | **Development server**: direct DB pools, static principal, `coordinator_launch_enabled=False`; manifests = compile only ("Submit and start need run control and a launcher; the API composes them, this development server does not"). Not usable to launch/intervene in S0. |
| Relays | subscription relay (API, opt-in); chain relay (worker, `CHAIN_RELAY_ENABLED`, needs `MANIFEST_LAUNCH_BINDINGS_PATH` on the worker) | Webhooks to loopback need `WEBHOOK_ALLOW_LOOPBACK=true`. |
| Client | `missionctl` (`MISSION_CONTROL_URL`, `MISSION_CONTROL_APPLICATION_ID`, `MISSION_CONTROL_TOKEN`) | groups: run, command (send/list/queue/inject/cancel), mission, chain, subscribe, events (watch), catalog, lane. No `wait`, no inbox, no human-task group. |

Windows refusal: the worker runs a `SelectorEventLoop` on Windows (psycopg), which cannot spawn asyncio subprocesses, so `claude_agent_sdk`, `codex` and `cursor_local` are refused on a Windows worker (`LANE_UNSUPPORTED_OS` in readiness; `compose_claude_local_lane`/`compose_codex_local_lane` silently return `None`, then admission refuses the profile; Cursor `bridge.host_gate`). Confirmed by readiness `--platform Windows`: 3 × `LANE_UNSUPPORTED_OS`.

### Recommended S0 topology (owner machine)

```
Windows 11                                         WSL 2 Ubuntu 22.04 (NAT, no .wslconfig)
-------------------------------------------        ------------------------------------------
Agent session (Claude Code/Codex/Cursor)            Worker (only worker; serves base queues
  missionctl --url http://127.0.0.1:8000              + lane queue mc-s0-<app>-lane-wsl)
API  :8000 (Windows .venv, make server)              spawns: Claude Code (SDK-bundled 2.1.294),
Docker Desktop: Temporal :7233, UI :8080,             codex app-server 0.162.0, cursor-sdk bridge
  PG17 :55433, Redis :16379                          leases: ~/mc-leases/{claude,codex,cursor}
Shared artifact root C:\Users\Pinda\mc-s0\artifacts   fixture repos: ~/mc-fixtures/<repo>
                                                     hook callback 127.0.0.1:47555 (WSL loopback)
```

- **Agent → API**: API on Windows means `missionctl` talks to `127.0.0.1:8000` directly. If the API runs in WSL instead, WSL2 NAT mode with the default `localhostForwarding=true` (no `.wslconfig` on this machine) forwards Windows `localhost:8000` to a WSL listener on 127.0.0.1/0.0.0.0. Use `127.0.0.1`, not `localhost` (IPv6), and verify with `curl http://127.0.0.1:8000/health/live` from PowerShell; fallbacks: `.wslconfig` `networkingMode=mirrored`, or bind 0.0.0.0 and use the WSL IP (172.22.115.180 today; changes per boot).
- **WSL → Docker services**: verified from WSL: 127.0.0.1:7233, :55432, :55433, :16379, :8080 are open (Docker Desktop WSL integration publishes into the distro). No host-IP plumbing needed.
- **Same code on both hosts**: API and worker must run the same tree. A fresh WSL `git clone` gets only HEAD `2d20f62`, not the dirty tree (component 1.3.0, 0034, lifecycle reliability work). For S0 either run the WSL worker from the Windows checkout (`/mnt/c/.../mission-control`) with a separate Linux venv (`UV_PROJECT_ENVIRONMENT=$HOME/.venvs/mission-control`, never `uv sync` into the Windows `.venv`), or checkpoint the dirty tree first (owner-authorized commit) and clone. The /mnt/c route also makes the default `WORKSPACE_ROOT` resolve to `/mnt/c/.../BellLabs/biotech` (settings.py:19 checks parent `platform`, grandparent `BellLabs`), so pin bytes and digests are identical on both hosts.
- **CLIs live in WSL only**: Linux `codex` 0.162.0, `git`, a `claude` CLI on PATH (for the auth status probe and `/login`; sessions use the SDK-bundled 2.1.294 from the Linux wheel), Node (only for npm-installing codex and for node-based MCP/tool pins). The cursor-sdk Linux wheel bundles its own node bridge.
- **Worktrees/leases**: on the Linux filesystem (`MISSION_CONTROL_CLAUDE_LEASE_ROOT`, `MISSION_CONTROL_CODEX_LEASE_ROOT`, `CURSOR_LEASE_ROOT`), never under `/mnt/c`. Defaults are `PROJECT_ROOT/.workspaces/<lane>-leases` (= /mnt/c if run from the Windows tree), so set them. Repositories: `MISSION_CONTROL_CODEX_REPOSITORY`, `CURSOR_LOCAL_REPOSITORY`, or the binding's `workspace`/manifest `repo`, all WSL paths/URLs (dedicated fixture clones, not the primary checkout).
- **Artifact payloads**: with no `S3_BUCKET`, every process uses `FilesystemArtifactPayloadStore` at `ARTIFACT_PAYLOAD_ROOT` (default `PROJECT_ROOT/.artifact-payloads`; docstring: "a directory every worker and the API can reach"). Set the same physical directory on both (`C:\Users\Pinda\mc-s0\artifacts` on Windows and `/mnt/c/Users/Pinda/mc-s0/artifacts` in WSL).

---

## 2. Task queue routing

- The queue is chosen **per lane profile in the operator's launch-bindings file**: `providers.{claude_agent_sdk,codex}.task_queue` (`ProviderLaneBinding`, `application/authoring/provider_launch.py:98`) and `providers.cursor_local.task_queue` (`cursor_launch.py:130`). Free string, 1–255 chars. The example uses `biotech-research-ingestion-lane-{claude-agent-sdk,codex,cursor-local,cursor-cloud}`.
- At `mission start` the API's `ManifestLaunchInputAuthor` seals it into `mc.execution_binding.v2` / `mc.cursor_binding.v1`; `OperationWorkflowRequest.activity_task_queue` reads `provider_binding.task_queue`, so every `lane.turn` / `lane.status` / `lane.cancel` of a Session Lane unit (`SESSION_LANE_RUNTIMES={cursor,claude,codex}`) is scheduled there. The operation workflow itself stays on the base queues.
- A worker serves a dedicated lane queue only if it is listed in `MISSION_CONTROL_LANE_TASK_QUEUES` (JSON list for pydantic-settings, e.g. `'["mc-s0-aie-lane-wsl"]'`). An unserved queue just waits (schedule-to-start).
- **Multiple hosts on separate queues: yes, for lane activities.** A WSL worker can list the local lane queues and a future Daytona worker a different queue. Constraints:
  1. Every worker is monolithic. A second host also polls root/family/cognitive/artifact/linked/maintenance queues and needs runtime + family-writer + checkpointer DSNs. There is no lane-only role (gap S0-G4).
  2. All workers of a deployment must share the Worker Deployment build id (`TEMPORAL_BUILD_ID`, default package version) or `TEMPORAL_PROMOTE_ON_START` makes the last starter current and drains the other.
  3. With two workers on one host family, Claude/Codex/Cursor units must be on a queue served only by a host that registers those lanes. `<base>-agent-cognitive` is polled by every worker, so a Windows worker would pick up and fail lane activities routed there.
  4. Filesystem payload store does not span hosts. Use S3 for remote workers.
- **"API elsewhere + Temporal Cloud + worker on owner machine"** needs:
  - Temporal Cloud namespace and API key on API and worker, with `TEMPORAL_ADDRESS`/`TEMPORAL_NAMESPACE` equal to `deployment.temporal`; the cloud target refuses a split.
  - Search attributes registered on the cloud namespace.
  - One installation DB reachable from both. Today that is Supabase, which holds 1.0.0, while the tree needs 1.3.0 (O6).
  - Worker DSNs for runtime, family and checkpointer, with the checkpointer on the same host/port/path as the runtime DSN (`_settings_for_application`).
  - The same `deployment.json` and binding digest on both.
  - S3 payloads (`S3_BUCKET` + AWS creds on both).
  - Bundle custody if skills or hooks are used (MO-01).
  - A launch-bindings file on the API host naming the owner machine's lane queue, and a worker listing it.
  - No inbound ports on the owner machine: the worker only dials out. The hook callback stays loopback.
  - Tokens from a real issuer whose public keys are pinned in the API's JWKS file.

---

## 3. Temporal Cloud path

- **Settings**:
  - `TEMPORAL_TARGET=cloud`, `TEMPORAL_CLOUD_API_KEY`, `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE` (`bootstrap/settings.py:291-302`).
  - `adapters/temporal/client.resolve_temporal_connection` connects with `api_key=` and `tls=True`. It refuses a missing or empty key and a deployment whose address or namespace differs from the env values.
  - `make preflight` reports the target without the key. Local remains the default even if the key is present.
- **Auth**: API key only. There is no mTLS client cert/key setting, so an mTLS-only namespace is unsupported (gap). The example profile hints at the endpoint `<ns>.<acct>.tmprl.cloud:7233`. Whether the namespace accepts API keys there or needs the regional `*.api.temporal.io` endpoint is an owner check.
- **Namespace**: the cloud form `<ns>.<acct>`. Search attributes come from `scripts/register_belllabs_search_attributes.py` (it honors `TEMPORAL_TARGET=cloud`). It is UNVERIFIED whether Cloud permits operator `AddSearchAttributes` with an API key; otherwise use `tcld`/UI. `make temporal-search-attributes` is local-only (`--address 127.0.0.1:7233`). Worker versioning promotion on Cloud needs a key with namespace write rights (UNVERIFIED).
- **Tested**:
  - Unit tests only for cloud (`tests/unit/runtime/test_ft_g7_temporal_upgrade.py`): resolution, refusal, a mocked `connect` carrying key and TLS, preflight redaction.
  - The outage/cluster-guard drill (`tests/integration/temporal/test_mp22_outage_drill.py`) uses two local namespaces.
  - Release notes say: "Temporal Cloud itself was not exercised".
- **Current `.env` shape**: `TEMPORAL_CLOUD_API_KEY` is set; `TEMPORAL_ADDRESS` is localhost; `TEMPORAL_NAMESPACE` has no account suffix; `TEMPORAL_TASK_QUEUE` is a non-default value. Cloud address and namespace are not configured yet. Keep them in a separate cloud shell profile, because a cloud target with a local address fails the split check.
- **Run pinning**: each run is bound to its first cluster (`run_cluster_binding`); there is no cross-cluster failover. `mc.local_run_profile.v1` holds `temporal_clusters[]` + `new_run_cluster`; `preflight guard-launch` writes a file ledger (runbook 2.9).

---

## 4. Everything missing to run S0 for real

### Machine state (probed 2026-10-12)

| Item | Windows | WSL Ubuntu 22.04 (WSL2, kernel 6.18, 16 CPU, 7 GB RAM, systemd on, NAT) |
| --- | --- | --- |
| Python | 3.12.2 | system 3.10.12 only (uv can install 3.12) |
| uv | 0.12.23 | **0.9.0** (uv.lock is revision 5 → `uv self update`) |
| Docker | 29.7.2 / compose v5.3.1, containers up: Temporal+UI, PG16 :55432, PG17 :55433, Redis, mcdb-a/b | docker CLI via Desktop integration; all ports reachable |
| Node | v24.18.0 | **missing** (only Windows npm shim via interop) |
| codex | **0.162.1** (pin is 0.162.0 → `PROVIDER_PIN_MISMATCH` if ever used) | **broken**: PATH resolves the Windows npm shim `/mnt/c/.../npm/codex` → `node: not found` |
| claude | 2.1.296 (not used by the lane) | **missing**; `~/.claude/.credentials.json` absent |
| Codex login | n/a | `~/.codex` absent (no `auth.json`) |
| temporal CLI | missing (use `make temporal ARGS=...` container) | missing |
| git / make | — | 2.34.1 / 4.3 |
| repo | Windows checkout (dirty) | no clone; home has `bin/`, `kafka_2.13-4.0.0/` |

### Inputs and gates

| # | Missing | State / evidence |
| --- | --- | --- |
| a | **Launch-bindings file (O7)** `mc.manifest_launch_bindings.v2` with `providers.{claude_agent_sdk,codex,cursor_local}` | None exists. Readiness on the multi-provider example: 62 `BINDING_UNRESOLVED`: per lane `model_id`, 5 reviewed digests (`agent_profile_ref`, workspace `environment/image/package/runtime` digests are `sha256:000…`), tracing/sensitive-data/snapshot policy refs, worker egress policy ref, workspace provider, plus the deep_agents block. `preflight compose-bindings --base <example> --selections <json>` re-seals. Unclear who computes the workspace digests for a `local_workspace` host. |
| b | **Auth profiles (O3)** `MISSION_CONTROL_AUTH_PROFILES_PATH` | None exists. The example yields `AUTH_ROUTE_POLICY_RESTRICTED` for Claude `owner_cli_login` without `owner_attestation_ref`, and `AUTH_STATUS_UNPROBED` for login routes. Login routes are admitted only with `MISSION_CONTROL_AUTH_STATUS_PROBE=true` (environment scan never proves `signed_in`), which runs `claude auth status --json` / `codex login status` **from PATH** with a PATH/HOME-only env. |
| c | **Opt-ins** | worker: `MISSION_CONTROL_CLAUDE_LANE=true`, `MISSION_CONTROL_CODEX_LANE=true`, `CURSOR_API_KEY` (in `.env`, non-empty), `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES=true`, `MISSION_CONTROL_LANE_TASK_QUEUES`, `COORDINATOR_LAUNCH_ENABLED=true`; API: same lane flags, `MANIFEST_LAUNCH_BINDINGS_PATH`, `MISSION_CONTROL_SUBSCRIPTION_RELAY=1`. Every lane is `qualified=False`. |
| d | **DB release** | Tree builds **1.3.0** (0001-0034, fingerprint `sha256:3154fa8d…`, PG17, `vector`+`pg_trgm`); tracked locks pin 1.1.0; live Supabase holds 1.0.0; docs still say 1.2.0. Local S0 needs a disposable target outside VCS (runbook 2.2) with `required_component_version="1.3.0"`, plus runtime-apply, seeds (common + app + qualification), three logins, lexical catalog projection. |
| e | **Preflight failures today** (scratch profile, `--platform Linux`) | `capability_pins` passes with `--workspace-root …/biotech` (**O4 resolved**). It fails with `…/platform`, because `platform/.agents` and `platform/.tools` junctions do not exist, contrary to the docs. Other blockers: `RELEASE_LOCK_DRIFT` (readiness reads only the tracked `deployments/<app>/release.lock.json`, so it stays red for a local 1.3.0 target), `launch_bindings` (62), `auth_routes`. `lane_hosts` and `temporal` pass. The worker startup gate checks only pins and lane hosts, so lock drift does not stop the worker. |
| f | **Windows refusals** | all three lanes `LANE_UNSUPPORTED_OS`. Fix by placement in WSL (MO-08), or CM-04 for cursor_local only. |
| g | **WSL installs** | `uv self update`, Python 3.12 (uv-managed), Linux Node (nvm), `npm i -g @openai/codex@0.162.0` (or the release binary), Claude Code native CLI, and `[interop] appendWindowsPath=false` in `/etc/wsl.conf` (or Linux bins first on PATH) so Windows shims never shadow. Set `MISSION_CONTROL_CODEX_BINARY` to an absolute path. |
| h | **Claude auth on the worker** | `api_key`: documented, metered. `ANTHROPIC_API_KEY` must be **exported** into the worker's process env; pydantic reads `.env` into settings but the child env and detection read `os.environ`. The config dir moves under the lease. `owner_cli_login`: `/login` inside WSL → `~/.claude/.credentials.json`. It is `policy_restricted` (Agent SDK terms), so the profile needs `owner_attestation_ref`, and the status probe is required. Do not export `ANTHROPIC_API_KEY`, or set `shadowing:"unset"`. `setup-token` (`CLAUDE_CODE_OAUTH_TOKEN`) = route `oauth_token_env`, also `policy_restricted` + attestation; the live drill supports only `api_key\|owner_cli_login`. Today the Claude child inherits the whole worker env, including DB DSNs (MO-04). |
| i | **Codex auth in WSL** | ChatGPT: `codex login` (or `--device-auth`) → `~/.codex/auth.json`. **Must** run with `MISSION_CONTROL_CODEX_HOME_MODE=owner` and `MISSION_CONTROL_CODEX_OWNER_HOME=$HOME/.codex`. The default `isolated` mode gives the app-server a fresh `CODEX_HOME` with no `auth.json`, while the preflight observes the owner's login, so admission passes and the launch is unauthenticated (no guard; gap S0-G2). API key route: `OPENAI_API_KEY`/`CODEX_API_KEY` exported; works with `isolated`. |
| j | **Cursor key** | `CURSOR_API_KEY` is in `.env` and non-empty. It reaches settings only if the worker reads that `.env` (true when run from the Windows tree; a WSL clone has no `.env`). Profile `cursor-local-key` = `settings:cursor_api_key`, documented; billing `unknown`. |
| k | **Operator identity** | No `deployment.json`, binding, JWKS, keys or token exist (`.scratch/local-stack` absent). No token-mint helper beyond `scripts/fast_track_dry_run.py` code. |
| l | **Probe manifests** | Example v2 manifests (`tests/fixtures/manifests/multi-provider/{claude-agent-sdk,codex,cursor-local}.*.mission.yml`) compile only against test fixture catalogs: schemas like `patch_report@1` exist only in tests; the repo URL `Overton77/mission-control-fixture` is unverified. S0 needs minimal manifests that compile on production + qualification seeds. |
| m | **Budget / qualification** | O1: a finite `MC_PAID_BUDGET_USD` approved in Linear (OVE-70 Claude, OVE-71 Codex, OVE-55 Cursor) before any live turn. |

### Intervention support (declared, all `qualified=False`)

| Lane | cancel | inject (cancel_and_replace) | queue | fork (run-level) | conversation fork | pause |
| --- | --- | --- | --- | --- | --- | --- |
| claude_agent_sdk | turn_boundary_guaranteed | yes | turn_boundary_guaranteed | emulated (snapshot + packet → fresh session) | unqualified | unqualified |
| codex | turn_boundary_guaranteed | yes (+ native `turn/steer`) | wait_then_send | emulated | unqualified | emulated |
| cursor_local | turn_boundary_guaranteed | yes | wait_then_send | emulated (frozen `cursor-snapshot:`) | — | unsupported |

---

## 5. Runbook (owner + agent)

Conventions: operator files outside VCS in `C:\Users\Pinda\mc-s0\` (WSL `/mnt/c/Users/Pinda/mc-s0/`); app `ai-engineer` for coding probes (or `biotech`); queue base `mc-s0-aie`; one lane queue `mc-s0-aie-lane-wsl` for all three lanes. Never print secrets.

**Step 0: owner decisions.**
- Claude route: `api_key`, or `owner_cli_login` with an attestation ref.
- Codex route: ChatGPT with owner home, or API key.
- Model ids per lane.
- Fixture repo(s).
- Budget comment in Linear.
- Whether to checkpoint the dirty tree (commit) or run the worker from `/mnt/c`.

**Step 1: WSL host (owner runs, agent may script).**
```bash
sudo tee -a /etc/wsl.conf <<'EOF'
[interop]
appendWindowsPath=false
EOF
# then in PowerShell: wsl --shutdown; reopen Ubuntu
uv self update && uv python install 3.12
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash && nvm install --lts
npm i -g @openai/codex@0.162.0 && codex --version        # must print codex-cli 0.162.0
curl -fsSL https://claude.ai/install.sh | bash && claude --version
codex login            # ChatGPT route (or --device-auth); creates ~/.codex/auth.json
claude                 # /login for owner_cli_login (skip for api_key)
mkdir -p ~/mc-leases/{claude,codex,cursor} ~/mc-fixtures ~/.venvs
git clone <fixture repo> ~/mc-fixtures/<repo>
cd /mnt/c/Users/Pinda/Proyectos/BellLabs/platform/mission-control
export UV_PROJECT_ENVIRONMENT=$HOME/.venvs/mission-control
uv sync --frozen --group dbcontract --group biotech
```

**Step 2: local DB 1.3.0 (agent, Windows, runbook 2.2–2.3).**
- `docker start mc-ft-disposable-pg17`.
- Create database `mc_s0_aie` with schema `extensions` holding `vector` and `pg_trgm`.
- Write `.scratch/local-stack/deployments/ai-engineer/target.toml` with a local `project_ref` and a UUIDv7 `installation_id`.
- Run `mission-db lock --deployments-root .scratch\local-stack\deployments`, then `plan`, `apply --expected-plan-digest --confirm-target`, `verify`.
- Run `seed-apply` with the common, ai-engineer and qualification bundles, then `runtime-apply`.
- Create the logins `mc_s0_runtime`, `mc_s0_family` and `mc_s0_ckpt`.
- Run `scripts/rebuild_capability_search_projection.py --lexical-only`.

**Step 3: operator files (agent drafts, owner reviews).**
- RSA key and public JWKS (from `fast_track_dry_run.py`).
- `deployment.json` and `binding.json`: `required_component_version="1.3.0"`, `TemporalDeployment(address="127.0.0.1:7233", namespace="default", root/stagegraph/goal_directed = mc-s0-aie-root / mc-s0-aie-coordinator-family-stagegraph / mc-s0-aie-coordinator-family-goal-directed)`, `family_writer_secret_ref`, and an ActorGrant with the runbook 2.4 permission set plus sponsorship and approval refs.
- `auth-profiles.json`: the real routes from Step 0.
- `launch-binding-selections.json`, then compose the bindings:
  ```
  uv run --no-sync python -m mission_control.bootstrap.preflight compose-bindings --base deployments/examples/manifest-launch-bindings.multi-provider.example.json --selections C:\Users\Pinda\mc-s0\launch-binding-selections.json --out C:\Users\Pinda\mc-s0\manifest-launch-bindings.json
  ```
  In the selections, every `providers.*.task_queue` = `mc-s0-aie-lane-wsl`.
- `local-run-profile.json`: lanes claude_agent_sdk/codex/cursor_local, cluster `local`, `new_run_cluster: local`.
- A short-lived token written to a file.

**Step 4: start (Windows, API).**
```powershell
make temporal-up            # idempotent; registers Search Attributes
$env:MISSION_CONTROL_DEPLOYMENT_FILE='C:\Users\Pinda\mc-s0\deployment.json'
# DSN env names from the binding set via your secret mechanism (not echoed)
$env:MANIFEST_LAUNCH_BINDINGS_PATH='C:\Users\Pinda\mc-s0\manifest-launch-bindings.json'
$env:MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES='true'; $env:MISSION_CONTROL_CLAUDE_LANE='true'; $env:MISSION_CONTROL_CODEX_LANE='true'
$env:MISSION_CONTROL_SUBSCRIPTION_RELAY='1'; $env:ARTIFACT_PAYLOAD_ROOT='C:\Users\Pinda\mc-s0\artifacts'
make server
```

**Step 5: start (WSL, worker).**
```bash
export MISSION_CONTROL_DEPLOYMENT_FILE=/mnt/c/Users/Pinda/mc-s0/deployment.json
export MISSION_CONTROL_WORKER_APPLICATION_ID=ai-engineer MISSION_CONTROL_WORKER_BINDING_DIGEST=<sha256:…>
export COORDINATOR_LAUNCH_ENABLED=true LANGGRAPH_CHECKPOINT_SETUP=false   # + runtime/family/ckpt DSNs via secret mechanism
export MISSION_CONTROL_LANE_TASK_QUEUES='["mc-s0-aie-lane-wsl"]' MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES=true
export MISSION_CONTROL_AUTH_PROFILES_PATH=/mnt/c/Users/Pinda/mc-s0/auth-profiles.json MISSION_CONTROL_AUTH_STATUS_PROBE=true
export MISSION_CONTROL_CLAUDE_LANE=true MISSION_CONTROL_CLAUDE_LEASE_ROOT=$HOME/mc-leases/claude
export MISSION_CONTROL_CODEX_LANE=true MISSION_CONTROL_CODEX_BINARY=$(command -v codex) MISSION_CONTROL_CODEX_LEASE_ROOT=$HOME/mc-leases/codex
export MISSION_CONTROL_CODEX_HOME_MODE=owner MISSION_CONTROL_CODEX_OWNER_HOME=$HOME/.codex MISSION_CONTROL_CODEX_REPOSITORY=$HOME/mc-fixtures/<repo>
export CURSOR_LEASE_ROOT=$HOME/mc-leases/cursor CURSOR_LOCAL_REPOSITORY=$HOME/mc-fixtures/<repo>
export ARTIFACT_PAYLOAD_ROOT=/mnt/c/Users/Pinda/mc-s0/artifacts MISSION_CONTROL_LOCAL_RUN_PROFILE=/mnt/c/Users/Pinda/mc-s0/local-run-profile.json
# api_key route only: export ANTHROPIC_API_KEY (never for owner_cli_login with shadowing=reject)
uv run --no-sync python -m mission_control.bootstrap.preflight --profile $MISSION_CONTROL_LOCAL_RUN_PROFILE \
  --db-dsn-env <RUNTIME_DSN_NAME> readiness          # expect only RELEASE_LOCK_DRIFT (gap S0-G3)
uv run --no-sync python -m mission_control.bootstrap.worker
```

**Step 6: agent loop (Windows).**
```powershell
$env:MISSION_CONTROL_URL='http://127.0.0.1:8000'; $env:MISSION_CONTROL_APPLICATION_ID='ai-engineer'  # token loaded from file, not echoed
uv run --no-sync missionctl lane list --json
uv run --no-sync missionctl mission compile <s0-codex.mission.yml> --json
uv run --no-sync missionctl mission submit  <s0-codex.mission.yml> --json
uv run --no-sync missionctl mission start <RUN_ID> --json
uv run --no-sync missionctl events watch <MISSION_ID> --types "workflow_run.*,session.*,command.*"   # run in background; agent monitors
uv run --no-sync missionctl run inspect <RUN_ID> --wait 300 --json
uv run --no-sync missionctl command inject <RUN_ID> --file inject.json --json
uv run --no-sync missionctl run fork <RUN_ID> --instruction-file fork.md --sponsorship-ref <ref> --approval-ref <ref> --json
uv run --no-sync missionctl command cancel <RUN_ID> --urgency immediate --reason "S0 drill" --json
```
Repeat with the Claude and cursor_local manifests. Native approvals are resolved through `POST /v1/applications/{app}/human-tasks/{id}/approval-resolutions` (no CLI).

**Step 7: Temporal Cloud variant.** Put these in both shells, API and worker:
- `TEMPORAL_TARGET=cloud`, `TEMPORAL_ADDRESS=<endpoint>`, `TEMPORAL_NAMESPACE=<ns.acct>`, and the key.

Then:
1. Register search attributes: `uv run --no-sync python scripts/register_belllabs_search_attributes.py`, or `tcld`/UI if refused.
2. Point `deployment.json` temporal at the same address and namespace. The binding is unchanged; deployment files are not digest-sealed beyond the binding.
3. Add cluster `cloud` to the run profile and set `new_run_cluster: cloud`.
4. Run `preflight guard-launch` per run.

Never move an active run between clusters.

---

## 6. Gap list (issue-ready)

| ID | Title | Files | Acceptance | Deps / packet mapping |
| --- | --- | --- | --- | --- |
| S0-G1 | WSL2 worker runbook + host preflight: CLI pins, PATH shadowing by Windows shims, auth status, lease roots on Linux FS, same-tree rule | `docs/MISSION_CONTROL_LOCAL_API.md`, `bootstrap/preflight.py`, `scripts/` | readiness on the owner's WSL reports `codex 0.162.0` found and not a `/mnt/c` shim, `claude` present, signed-in status per route, lease roots not under `/mnt/c` | **MO-08** |
| S0-G2 | Refuse Codex `owner_cli_login` in `isolated` CODEX_HOME (or auto owner mode) | `adapters/codex/harness.py`, `adapters/codex/compose.py`, `bootstrap/preflight.py` | profile `codex-owner-chatgpt` + `isolated` → typed refusal at preflight and admission; owner mode launches signed in | new; relates MO-08, MO-04 |
| S0-G3 | Preflight `db_release` accepts a local deployments root / profile `deployment_dir` | `bootstrap/preflight.py` (lock path `deployments/<app>`) | readiness green for a `.scratch/local-stack` 1.3.0 install without touching tracked locks | new; relates MO-21; O6 |
| S0-G4 | Lane-only worker role (serve only `MISSION_CONTROL_LANE_TASK_QUEUES`, runtime role only, no family or checkpointer) | `bootstrap/worker.py`, `adapters/temporal/worker.py`, `deployment_composition.py` | a second worker serving only lane queues runs lane.turn without the family-writer DSN; no root or family pollers | new; prerequisite for Daytona (HL-02, MO-52) |
| S0-G5 | Split-host payload custody: fail fast when API and worker filesystem roots differ; require S3 off-host | `deployment_composition.artifact_payload_store`, `bootstrap/preflight.py` | preflight flags a non-shared `ARTIFACT_PAYLOAD_ROOT`; the S3 path is documented for remote workers | new |
| S0-G6 | Wake channel for the orchestrating agent (`missionctl wait`, inbox long-poll, MCP `inbox_wait` on the authenticated server, auto-subscribe) | `interfaces/cli`, `interfaces/http/coordinator_inbox.py`, `interfaces/mcp/` | a Claude Code session is woken by `run.completed` | **MO-43** |
| S0-G7 | Authenticated MCP with submit, start and intervene (the dev MCP compiles only and uses a static principal) | `interfaces/mcp/__main__.py`, `coordinator_server.py` | agent launches and cancels via MCP with JWT scope | MO-43 / **MO-21** |
| S0-G8 | Provider child env allowlist (the Claude CLI inherits DSNs and keys) | `bootstrap/provider_auth.py`, `adapters/claude/transport.py`, `adapters/codex/launcher.py`, `adapters/cursor/bridge.py` | sentinel test | **MO-04** |
| S0-G9 | Codex and Cursor local honor manifest workspace policy and cleanup | `adapters/codex/harness.py`, `adapters/cursor/local.py` | within_run reuse and cleanup | **MO-05** |
| S0-G10 | Bundle custody in rows resolvers (only if S0 manifests use skills or hooks) | `bootstrap/manifests.py`, `provider_lane_composition.py` | skill and hook pins materialize on all three lanes | **MO-01** |
| S0-G11 | Codex kernel hooks and trust | `adapters/codex/*` | live before_tool deny | **MO-03** |
| S0-G12 | cursor_local on a Windows worker (removes WSL need for Cursor only) | `adapters/cursor/bridge.py` | fixture bridge on SelectorEventLoop | **CM-04** (→ CM-05) |
| S0-G13 | Temporal Cloud qualification: a real connect, search-attribute registration path (API key vs `tcld`), versioning promote permission, mTLS decision | `adapters/temporal/client.py`, `scripts/register_belllabs_search_attributes.py`, docs | one fixture run on a Cloud namespace, recorded | new |
| S0-G14 | Local dev issuer and token helper (`missionctl token mint` from an operator key) | `scripts/` or `interfaces/cli` | no hand-written JWT code needed for S0 | new; relates MO-22 |
| S0-G15 | S0 probe manifests per lane that compile on production + qualification seeds (schemas, fixture repo) | `docs/specs/.../examples`, seeds | `compile` reports 0 blockers on the local install for all three lanes | new; B2 |
| S0-G16 | Launch-bindings digests for `local_workspace` hosts: tool to compute environment, image, package and runtime digests and reviewed `agent_profile_ref` digests | `bootstrap/preflight.py compose-bindings` | `compose-bindings` produces a file with 0 `BINDING_UNRESOLVED` from owner selections only | **O7**; relates MO-20 |
| S0-G17 | Docs drift: component 1.3.0/0034 vs "1.2.0"; `platform/.agents` and `.tools` junctions documented but absent; local-profiles README stale (C20) | `MISSION_CONTROL_LOCAL_API.md`, `knowledge/persistence.md` | links and claims match the tree | **MO-07** |
| S0-G18 | Codex pin drift: Windows has 0.162.1; decide pin 0.162.0 in WSL vs re-pin with regenerated schema | `application/execution/harness/describe.py`, `tests/fixtures/provider_frames/codex/schema` | the WSL `codex --version` equals the pin | new; O2 |
| S0-G19 | Live drills (owner, paid) | `make lane-qualify PROFILE=… LIVE=1` | records under `docs/qualification/lanes/` | **O1** |
| S0-G20 | Checkpoint the dirty tree so the API and every worker run identical code and build ids | git (owner) | worker build id and code equal on all hosts | O9 (owner) |

Owner actions still open from HANDOFF-2026-10-10:
- O1 budgets and drills.
- O2 WSL worker: this audit details it.
- O3 auth profiles.
- O5 CRLF.
- O6 release apply: local now needs 1.3.0.
- O7 bindings.
- O8 Linear.
- O9 ADRs and checkpoint.

O4 (the agent-browser drift) appears resolved: pins pass under the biotech root.
