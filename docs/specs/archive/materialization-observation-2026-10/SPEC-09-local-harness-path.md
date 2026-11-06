---
type: Specification
title: "SPEC-09: Local harness path (slice S0) — Claude Code, Codex and Cursor harnesses through Mission Control on a WSL2 worker with local or Cloud Temporal"
description: "Topology, task-queue routing, toolchain and auth per lane, Temporal local and Cloud variants, the lane-only worker role, shared payload custody, the S0 runbook outline and the gaps that must close for agents on the owner's machine to run the real harnesses programmatically."
tags: [mission-control, specifications, lanes, local, temporal, wsl]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L in full: readiness, all nine local-Temporal cells, all nine Temporal Cloud cells (namespace `mission-control-dev.ih0e7`, no AWS), no-secret clause. Both the SPRINT cancel-or-completion clause and this SPEC's probe-completion plus clean-cancel clauses must be satisfied per `runs/FINAL-CAPABILITY-S0-18-CELLS.json`. Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-09: Local harness path (slice S0)

Owner decision R13: Mission Control keeps a programmatic local path for the real harnesses. This is separate from the direct CLI skills in SPEC-08.

Evidence: [research/s0-local-harness.md](research/s0-local-harness.md). It covers the probed machine state, the runbook commands and the readiness output.

## 1. What runs

| Owner's tool calls | Lane | Harness process (in WSL) |
| --- | --- | --- |
| `missionctl` / MCP → API | `claude_agent_sdk` | Claude Agent SDK (pinned 0.2.165) driving its bundled Claude Code CLI 2.1.294 over stdio |
| same | `codex` | `codex app-server` (pinned 0.162.0, see §6) over JSON-RPC |
| same | `cursor_local` | cursor-sdk bridge (its Linux wheel bundles the node bridge). It also runs on a Windows worker after CM-04. |

## 2. Topology

```text
Windows 11                                        WSL2 Ubuntu (NAT, localhost forwarding)
------------------------------------------        -------------------------------------------
Agent session (Claude Code / Codex / Cursor)      Worker (sole worker for S0)
  missionctl --url http://127.0.0.1:8000            base queues + lane queue mc-s0-<app>-lane-wsl
API :8000 (make server)                             spawns Claude Code CLI, codex app-server, cursor bridge
Docker Desktop: Temporal :7233 (local variant),     leases on Linux FS: ~/mc-leases/{claude,codex,cursor}
  PG17 :55433, Redis :16379                         fixture repos: ~/mc-fixtures/<repo>
Shared artifact root (C:\...\mc-s0\artifacts =      hook callback listener 127.0.0.1:47555 (WSL loopback)
  /mnt/c/.../mc-s0/artifacts in WSL)
```

- **Agent → API.** Use `127.0.0.1`, not `localhost`. If the API moves into WSL, Windows reaches it through NAT localhost forwarding; the fallback is `.wslconfig networkingMode=mirrored`.
- **Same code on both hosts.** Either run the worker from the `/mnt/c` checkout with a separate Linux venv (`UV_PROJECT_ENVIRONMENT=$HOME/.venvs/mission-control`, never syncing into the Windows `.venv`), or checkpoint the dirty tree and clone (owner commit). Build ids must match.
- **Leases live on the Linux filesystem.** Set `MISSION_CONTROL_CLAUDE_LEASE_ROOT`, `MISSION_CONTROL_CODEX_LEASE_ROOT` and `CURSOR_LEASE_ROOT`; the defaults would land under `/mnt/c`.

## 3. Task queues and worker roles

- **Queue routing.** Each lane's `task_queue` is a free string in the launch-bindings file (`providers.<lane>.task_queue`), sealed into the binding. `lane.turn`, `lane.status` and `lane.cancel` run there. A worker serves it when the queue is listed in `MISSION_CONTROL_LANE_TASK_QUEUES`.
- **S0 layout.** One worker serves the base queues plus `mc-s0-<app>-lane-wsl`.
- **New: lane-only worker role (MO-63).** Today every worker is monolithic and needs the family-writer and checkpointer database logins. A `MISSION_CONTROL_WORKER_ROLE=lane` worker serves only the lane queues, with the runtime role only. This is required before workers run on other hosts (Daytona) and is useful locally.
- **After slice R (SPEC-11 §3).** The AWS worker serves AI Engineer's base queues and the hosted lane queue. The WSL2 worker then runs `MISSION_CONTROL_WORKER_ROLE=lane` for `mc-s0-<app>-lane-wsl` only. There is exactly one base worker per (namespace, application).
- **Split-host payload custody (MO-64).** Preflight fails when API and worker filesystem payload roots differ and no S3 store is configured.

## 4. Temporal variants

| Variant | Settings | Notes |
| --- | --- | --- |
| Local | `TEMPORAL_TARGET=local`, `TEMPORAL_ADDRESS=127.0.0.1:7233` | `make temporal-up`; reachable from WSL |
| Cloud | `TEMPORAL_TARGET=cloud`, `TEMPORAL_CLOUD_API_KEY`, `TEMPORAL_ADDRESS=<ns>.<acct>.tmprl.cloud:7233`, `TEMPORAL_NAMESPACE=<ns>.<acct>` | API-key plus TLS only; there is no mTLS support. The client refuses a deployment naming another frontend. Search attributes must be registered on the namespace. Never exercised against Cloud before (MO-67). The worker only needs outbound connections, so the API can live elsewhere later with no inbound path to the owner's machine. |

## 5. Auth per lane (worker side)

- **`claude_agent_sdk`.**
  - Recommended route: `api_key`, with `ANTHROPIC_API_KEY` delivered by the Secret Broker or exported in the worker env. A value present only in `.env` is not enough today.
  - Alternative: the subscription route, with `/login` or a setup-token in WSL plus an owner attestation ref. Its billing terms are unsettled.
  - The child env must be allowlisted (MO-04): today it inherits DSNs.
- **`codex`.**
  - ChatGPT login requires `MISSION_CONTROL_CODEX_HOME_MODE=owner`. Isolated homes have no `auth.json` and currently launch signed out without a guard; MO-65 refuses this.
  - The alternative is `OPENAI_API_KEY` in isolated mode.
- **`cursor_local`.** `CURSOR_API_KEY` (present in `.env`) or the CLI login.
- **Auth probe.** `MISSION_CONTROL_AUTH_STATUS_PROBE=true` needs the `claude` and `codex` CLIs on the WSL PATH, and not the Windows shims that leak in through `/mnt/c` (MO-08 checks this).

## 6. WSL toolchain (MO-08)

Probed state:

- uv 0.9.0, older than the lockfile needs;
- Python 3.10 only;
- no Node and no `claude`;
- `codex` resolves to the Windows npm shim and fails.

Required:

| Tool | Version |
| --- | --- |
| uv | ≥ lock requirement |
| Python | 3.12 (via uv) |
| Node | LTS (for the npm Codex install and node-based MCP pins) |
| Codex | **pinned version**, `codex --version` checked against the pin |
| Claude Code CLI | on PATH, for login and the probe; sessions use the SDK-bundled CLI |
| git | — |
| Docker | Docker Desktop WSL integration, for S4 and the Docker SandboxHost |

**Pin decision (MO-66).** Mission Control pins Codex 0.162.0, while Windows has 0.162.1. Either install 0.162.0 in WSL, or re-pin to 0.162.1 with a regenerated app-server schema fixture. Recommendation: **re-pin to 0.162.1**, so the LS skills and the lane share one version.

## 7. Operator inputs (owner + agent)

- **Local database at component 1.3.0.** The tree builds 1.3.0; the docs still say 1.2.0. Use a disposable local install, and give preflight a local deployments root instead of tracked locks (MO-68).
- **Auth profiles document** (O3). Generate it through `preflight compose-bindings`.
- **Launch-bindings file** (O7). It needs 62 values resolved, including model ids, digests and policy refs. **MO-69** adds a tool that computes environment, image, package and runtime digests and the reviewed agent profile digests from owner selections, so nothing is hand-edited.
- **Token helper (MO-70).** `missionctl token mint` from an operator key, so no hand-written JWTs.
- **S0 probe manifests (MO-71).** One per lane, compiling with zero blockers on the production and qualification seeds, against a fixture repo.
- **Authenticated MCP with submit, start and intervene (MO-21/MO-43).** Agents use it instead of the dev MCP server, which only compiles.

## 8. Runbook outline

Full commands are in research §5.

1. **Owner decisions:** auth routes, Codex pin and the checkpoint are decided (see Owner selections below).
2. **WSL toolchain install and logins** (MO-08 script).
3. **Local stack:** `make temporal-up`, PG17, then install component 1.3.0 into a disposable database.
4. **Operator files:** `preflight compose-bindings` produces the deployment, auth profiles and launch bindings with zero unresolved values.
5. **Windows:** API env plus `make server`.
6. **WSL:** worker env (queues, lease roots, payload root, auth) plus `readiness`.
7. **From each agent tool:**
   1. `missionctl compile`, `submit` and `start`;
   2. background `missionctl wait`;
   3. `inject`;
   4. `fork`;
   5. `cancel` or completion.
8. **Cloud variant:** switch to `TEMPORAL_TARGET=cloud`, register the search attributes, and repeat step 7.

## 9. Acceptance (slice S0)

> **Amended 2026-10-19 by owner decisions E1–E3**
> ([finish instructions](RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md) §2–3):
> - The caller is the sprint harness only. The "from each tool" runs are withdrawn.
> - Acceptance is one materialize-and-run cell per lane: Claude and Codex required, one guarded Cursor
>   attempt.
> - The cells are repeated on Temporal Cloud for the lanes that passed.
> - Inject is no longer a cell requirement.
>
> The text below is the original acceptance, kept for the record.

- **Readiness is green on the WSL worker for all three lanes:**
  - the CLIs found at pinned versions, not Windows shims;
  - auth per route;
  - lease roots on the Linux filesystem.
- **Each lane completes a probe mission launched from each tool** (Claude Code, Codex, Cursor) on Windows, which is nine runs. In each run:
  - the caller is woken by `missionctl wait`;
  - one inject is delivered and recorded;
  - one run is cancelled cleanly;
  - the worktrees are cleaned after custody.
- **The same three-lane probe set passes on Temporal Cloud.**
- **No secret appears in frames or logs; the child envs contain only the allowlist.**

## Owner selections (2026-10-12, R19–R22)

- **Same tree:** the checkpoint commit on `origin/main` (R19). The WSL worker runs a clone or worktree of that commit.
- **Claude auth:** `ANTHROPIC_API_KEY` (R21). The worker does not use a subscription login.
- **Codex:** pinned at 0.162.1 (R21), logged in with ChatGPT on the worker.
- **Temporal Cloud variant (MO-67):** `TEMPORAL_TARGET=cloud`, `TEMPORAL_ADDRESS=us-east-1.aws.api.temporal.io:7233`, `TEMPORAL_NAMESPACE=mission-control-dev.ih0e7`, with `TEMPORAL_CLOUD_API_KEY` from `.env` (R20). `.env` carries the non-secret `TEMPORAL_CLOUD_ADDRESS` and `TEMPORAL_CLOUD_NAMESPACE` for this.
- **Models and budget:** S0 has $10. Models are `claude-sonnet-5-5`, `gpt-6-luna`, and Cursor Auto plus one run on `grok-4.7` (R22).

## Run 2 approved refinements (2026-10-14)

MO-69 emits a derived secret-free configuration/identity summary using existing binding pins; no new canonical schema is required. MO-71/72 make the first local Anthropic probe identify actual SDK/bundled CLI/WSL host/auth/model, preserve repo instructions, distinguish delivered/read-back/exercised skill evidence, demonstrate exact tool-family deny/allow and inject/cancel, and register immutable output before cleanup. Refuse unsupported required enforcement before create. All original caller/lane S0 runs remain required; a partial Anthropic proof is not full S0 qualification. Current component 1.4.0 is built/locally proven, not applied live; old 1.3.0 baseline prose above is historical and must not select an obsolete artifact. Pin decisions follow owner selections and MO-66, not outdated prose.

[Detailed approved rules and issue mapping](runs/RUN-2-PLANNING-AMENDMENTS.md). These refine remaining acceptance and grant no new execution, spending or deployment authority.
