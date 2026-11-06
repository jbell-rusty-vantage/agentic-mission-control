---
type: Report
title: "Deployment options report: API and MCP, Deep Agents workers and Agent Server, Temporal Cloud workers, and the per-provider worker and environment matrix"
description: "Owner-facing deployment report (2026-10-12) that maps every Mission Control process role to the owner's accounts (AWS, Vercel Pro, Temporal Cloud, LangSmith Plus, Supabase, Daytona, WSL2), answers the four questions asked before the materialization-observation sprint, assesses Managed Deep Agents, and recommends a staged path to remotely spawned long-running missions."
tags: [mission-control, deployment, operations, report, agent-server, temporal, vercel, aws, langsmith]
---

# Deployment options report (2026-10-12)

Prepared for the owner before the [materialization-observation sprint](specs/archive/materialization-observation-2026-10/SPRINT.md).
This is an assessment, not a deployment instruction and not an authorization. Nothing was
deployed, created, purchased or changed while preparing it. Codebase facts come from the working
tree at the 2026-10-12 checkpoint; vendor facts were read from official documentation on
2026-10-12 and are cited inline. Anything marked **UNVERIFIED** could not be confirmed from a
primary source or from this account.

## 1. The short answers

| Question | Answer |
| --- | --- |
| How do we deploy the Mission Control API and MCP server? | Both are long-lived processes with Supabase pools, Temporal clients and installation checks at startup. They belong on always-on compute: the owner machine now (slice S0), then AWS. Vercel hosts only the thin Signal Ingress and Model Gateway this sprint ([SPEC-10](specs/archive/materialization-observation-2026-10/SPEC-10-ingress-on-vercel.md)); the operator API on Vercel is a conditional later phase. Recommended first remote target: one small AWS host in `us-east-1` running API, authenticated MCP and worker from the existing `deployments/cloud_runtime` image, behind TLS, before the ECS/Fargate layout. See §4. |
| How do we deploy a Deep Agents server and worker, and do we need two Postgres databases? | There are two different things. The **Mission Control worker** is a Temporal worker that runs the Deep Agents *parent* in-process and persists its LangGraph checkpoints in the private `mission_control_runtime` schema of each app's Supabase database, which `mission-db runtime-apply` already provisions. The **Agent Server** is a separate `langgraph-api` process that hosts only the *asynchronous subordinate* graph (ADR-0006) and needs its own Postgres and Redis per app (ADR-0017). Self-hosting that server now requires an Enterprise license, so on your Plus plan the viable host is a LangSmith Cloud deployment per app, where LangChain supplies Postgres and Redis and you provision nothing. The "two separate databases" requirement therefore only materialises if you self-host. See §5. |
| Does Temporal Cloud provide workers? | No. Temporal Cloud runs the service (frontend, history, matching, persistence) and never your Workers. Workers are processes you run anywhere with outbound gRPC; no inbound port is needed. Temporal's "Serverless Workers" feature invokes compute in *your* AWS or GCP account and is a poor fit for subprocess-spawning lanes. See §6. |
| What workers and environments must we provide per provider? | One Mission Control worker process per application (monolithic today; a lane-only role arrives with MO-63), one Agent Server deployment per application if Deep Agents async subordinates are used, the Vercel ingress and gateway project, Daytona sandboxes for self-hosted executors and Sandbox Host lanes, and per-lane credentials delivered by the Secret Broker. The full matrix is in §7. |

**Correction to two impressions in the brief.**

- "The LangSmith serverless deployment won't work for a remotely deployed Mission Control." Correct for the API and the Temporal worker: a LangSmith deployment is an Agent Server, not a general container host, it scales to zero and it caps API requests at one hour. It is, however, exactly the right host for the one thing Mission Control needs an Agent Server for, the async subordinate graph, which the worker reaches outbound over HTTPS with custom auth.
- "A Deep Agents harness that uses async subagents needs an agent server." Correct. `AsyncSubAgentMiddleware` starts background runs through `langgraph_sdk` on an Agent Protocol server. Synchronous subagents run in-process and need no server. ADR-0006 chose the server-hosted form because in-process subagents cannot survive worker loss.

## 2. What you have today

### 2.1 Accounts (read-only discovery, 2026-10-12)

| Account | State | Relevance |
| --- | --- | --- |
| AWS `298199649527` | Default region `us-east-2`. No Mission Control compute, ECR repository, ACM certificate or hosted zone. One unrelated ECS cluster and scraper task definitions ([INVENTORY](specs/archive/mc-surfaces-2026-10/deployments/cloud_runtime/INVENTORY.md)). | Target for API, MCP and workers. |
| Vercel Pro, team `overtons-projects` | 0 projects (confirmed again today through the Vercel connector). CLI scope defaults to another team, so every command passes `--scope overtons-projects` (R17). | Signal Ingress and Model Gateway project (`deployments/ingress-vercel`, not yet created). |
| Temporal Cloud account `ih0e7` | Namespaces `mission-control-dev.ih0e7` (7-day retention) and `mission-control-prod.ih0e7` (30-day), `aws-us-east-1`, API-key auth, endpoint `us-east-1.aws.api.temporal.io:7233` (R20). Never exercised by this code yet (MO-67). | Sole scheduler. Provides no workers. |
| LangSmith Plus | One included Serverless (Small) deployment per the public pricing page. Account entitlement, region and slot consumption were **not** verified from inside the account (no connector). | Agent Server host; tracing; LangSmith Sandboxes; Managed Deep Agents beta. |
| Supabase | `biotech-research-ingestion` (`bxnetwiimwhtlrjlbtab`) and `supabase-blue-ocean` (`wkythqbofmckbuoothhn`, AI Engineer), both Postgres 17, `us-east-1`, healthy, in a Vercel-Marketplace-managed organization. Common component **1.3.0** applied to both (R18). | Application authority plus the `mission_control_runtime` saver/store schema. |
| Neon | Two free organizations ("Vercel: Overton's projects", managed by Vercel, and a personal one) with one unrelated project. | Candidate host for Agent Server databases only if self-hosting ever becomes licensed. |
| Daytona | `DAYTONA_API_KEY` in `.env`, Tier 1/2, $200 free credit (R16). | Sandbox Host for S4 and self-hosted executors. |
| Owner machine | Windows 11 with WSL2; Docker Desktop; Codex CLI 0.162.1; Claude Code; Cursor. WSL toolchain install is MO-08. | The only worker host today. |

### 2.2 Processes the repository can start

From the [Makefile](../Makefile), [operations](knowledge/operations.md) and the S0 research:

| Process | Entry | Nature | Hosting needs |
| --- | --- | --- | --- |
| API | `uvicorn mission_control.bootstrap.api:create_app --factory` | ASGI; verifies installation, release fingerprint and roles at startup; Temporal submitter; subscription relay | Always-on; inbound HTTPS; Supabase and Temporal egress |
| Realtime API | `mission_control.bootstrap.realtime:create_asgi_app` | Same API plus the `/missions` Socket.IO namespace, Postgres `LISTEN` hints, optional Redis fan-out | Always-on; WebSockets; session-mode Postgres connection |
| Worker | `python -m mission_control.bootstrap.worker` | One application binding; polls every Temporal queue of its deployment; runs Deep Agents in `operation.execute`, lane activities (`lane.*`), the chain relay, frames retention; serves the loopback hook callback on `127.0.0.1:47555`; spawns Claude Code, `codex app-server` and the Cursor bridge | Always-on; no inbound; needs runtime, family-writer and checkpointer DSNs; Linux, macOS or WSL for the subprocess lanes |
| Agent Server | `langgraph dev --config agent_server/langgraph.json` | In-memory development server for the four registered graphs; **not** a production runtime | Production form is `langgraph-api` with Postgres and Redis, or a LangSmith deployment |
| Coordinator MCP (dev) | `python -m mission_control.interfaces.mcp` | FastMCP Streamable HTTP with a static principal, compile-only manifests; the API also mounts `/mcp/coordinator` when `COORDINATOR_MCP_ENABLED=true` | Authenticated submit, start and intervene arrive with MO-21/MO-43 |
| Signal Ingress (planned) | `deployments/ingress-vercel/app.py` | Slim FastAPI closure; one SQL round trip per request through `SECURITY DEFINER` functions | Vercel Fluid, `iad1`, Pro |
| Model Gateway (planned) | Routes in the same Vercel project, and a worker-host placement for Docker sandboxes | Streaming passthrough to Anthropic with per-run minted tokens | Vercel Pro (800 s streams) or the worker host |
| `missionctl` | installed script | HTTP client; loopback-only today | Any agent session |
| `mission-db` | `packages/mission-control-db-contract` | Installer with plan, apply and verify | Operator workstation |

Already prepared but not deployed: a reviewed Linux/amd64 base image and ECS task renderer in [`deployments/cloud_runtime`](../deployments/cloud_runtime/README.md) with a concrete Ohio approval plan ([APPROVAL_PLAN](specs/archive/mc-surfaces-2026-10/deployments/cloud_runtime/APPROVAL_PLAN.md)).

## 3. A mental model of the pieces

```text
Owner tools (Claude Code / Codex / Cursor / phone)
   │  missionctl, authenticated MCP, HTTP            ─────────── control plane you host ──────────
   ▼
Mission Control API (+ realtime stream, + MCP mount)  ── Supabase <app> DB (mission_control schema, authority)
   │  Temporal client (outbound gRPC, API key)        ── Temporal Cloud namespace (histories, timers, signals)
   ▼
Temporal Cloud ──► Mission Control worker(s)          ── Supabase <app> DB (mission_control_runtime saver/store)
                    ├─ deep_agents lane: parent agent in-process ──► Agent Server (async child graph, own Postgres+Redis)
                    ├─ claude_agent_sdk / codex / cursor_local: subprocesses on the worker host
                    ├─ cursor_cloud / claude_managed / codex_agents: provider-hosted loops, polled or webhook-woken
                    ├─ Sandbox Host lanes: harness in Daytona or Docker, model calls via the Model Gateway
                    └─ IngressDrainer: LISTEN on the inbox, writes frames, wakes Temporal
Public edge (Vercel): Signal Ingress + Model Gateway  ── writes only ingress_* rows; holds no Temporal credentials
```

Three rules from AGENTS.md shape every option below: Temporal alone schedules; the application
database and Temporal persistence are separate; workers only dial out, so nothing on the owner
machine or in a sandbox needs an inbound port.

## 4. Deploying the Mission Control API and the MCP server

### 4.1 Where the API can live

| Option | What it gives | Cost (monthly, sources in §9) | Verdict |
| --- | --- | --- | --- |
| **A. Owner machine + Temporal Cloud + Supabase** (slice S0) | API on Windows, worker in WSL2, `missionctl` from local agent sessions. No public endpoint. | $0 compute; Temporal and model usage only | **Now.** It is the sprint's S0 and needs no new infrastructure. Remote spawn works only from the machine itself. |
| **A'. Option A plus a private tunnel** (Tailscale, Cloudflare Tunnel) | Reach the local API from a phone or another machine without exposing a port. | $0 to small | Bridge until AWS. The sprint already reserves a tunnel for local-Docker ingress drills. Not for provider webhooks: those go to Vercel. |
| **B. One AWS host** (Lightsail 2 vCPU / 4 GiB, $24, or 8 GiB, $44) | API, authenticated MCP and worker as supervised containers from the `cloud_runtime` image; Caddy or nginx for TLS; outbound-only worker. | $24–44 plus about $4 snapshots | **First remote target.** Cheapest way to a public, authenticated API. Single point of failure; you manage the OS. Prefer `us-east-1` over the plan's `us-east-2` so the API, Supabase and the Temporal namespace share a region. |
| **C. ECS Fargate per the prepared plan** | Separate API task (0.5 vCPU / 2 GiB) and one worker task per app (1 vCPU / 2 GiB), ALB with TLS, NAT, Secrets Manager, S3 artifact buckets, CloudWatch. | $166–185 two apps; $130–149 one app (APPROVAL_PLAN) | **Later.** Right shape for two isolated app workers and secret injection by task role; the ALB and NAT dominate the fixed cost. |
| D. App Runner | HTTP-triggered service. | — | No. A worker with no inbound traffic is CPU-throttled; the API alone could run there, but the worker cannot. |
| E. Vercel | Python Fluid functions, 800 s max (1800 s beta), 4.5 MB bodies. | Pro plan already paid | **Only the Signal Ingress and Model Gateway** (SPEC-10 phase 1, HL-03). The operator API is phase 3 and conditional on Temporal Cloud, a slim import closure and cheap startup verification. Streams, workers and stateful MCP sessions never. |
| F. LangSmith deployment | Agent Server only. | included slot | No. Not a container host; scale-to-zero; one-hour request limit. |

Why not Vercel for the API today, in one paragraph: `create_app` verifies the installation
identity, release fingerprint and restricted roles against Supabase, composes Temporal
submitters and relay pumps, and imports the full dependency closure (`claude-agent-sdk`,
`langgraph-api`, `deepagents`, `temporalio`, `cursor-sdk`). That is a 500 MB-class bundle with
slow cold starts, and the realtime stream needs a session-mode `LISTEN` connection and
WebSocket affinity that Vercel does not give (vercel-ingress research §6).

### 4.2 The MCP server specifically

- What exists: the coordinator MCP server (`interfaces/mcp/coordinator_server.py`) with manifest, run-control, transcript and subscription tools, a dev runner with a static principal, and an optional mount inside the API (`COORDINATOR_MCP_ENABLED`, `/mcp/coordinator`). ADR-0015 requires resource-bound OAuth with PKCE for remote onboarding; no OAuth adapter exists yet, and the server trusts whatever verified bearer token FastMCP presents ([interfaces](knowledge/interfaces.md)).
- What the sprint adds: MO-21/MO-43 make the authenticated server able to submit, start and intervene; SPEC-04 §6 adds `inbox_wait` and deprecates `mission_subscribe` push.
- Hosting: run it as the API's mount, in the same container as the API, so there is one TLS endpoint, one JWT verifier and one Supabase pool set. Streamable HTTP sessions pin to an instance, which is fine on one host and acceptable on one Fargate task; it is the reason the MCP server cannot live on Vercel.
- Remote onboarding from Claude Code or Codex needs a token. Today the CLI sends a bearer it never minted; MO-70 adds `missionctl token mint` from an operator key. Until the OAuth adapter exists, issue scoped service tokens from the pinned JWKS issuer and treat them as secrets.

### 4.3 What the API host must be able to reach

Supabase (direct host or pooler, TLS), Temporal Cloud `*.api.temporal.io:7233`, S3 if `S3_BUCKET` is set, the Agent Server endpoint, and provider APIs only if lanes run on the same host. No provider callback lands on the API: callbacks go to the Vercel ingress.

## 5. Deep Agents: worker, Agent Server and the databases

### 5.1 Two persistence subsystems, not one

| Subsystem | Lives in | Provisioned by | Status |
| --- | --- | --- | --- |
| Standalone LangGraph saver and store used by the **worker's in-process Deep Agents parent** | `mission_control_runtime` schema of each app's Supabase database, bound with `search_path` through one libpq option, owned by a NOLOGIN checkpointer role ([persistence](knowledge/persistence.md), `adapters/deep_agents/persistence.py`) | `mission-db runtime-apply` from the pinned runtime descriptor | Qualified; the worker refuses the vendor `setup()` in production |
| **Agent Server native persistence** (`assistant`, `thread`, `run`, `checkpoints`, `store`, …) for the async subordinate graph | A database only the Agent Server uses | The server itself migrates at startup (63 migrations, `CREATE EXTENSION`, `CREATE INDEX CONCURRENTLY`) | Blocked on a topology and license decision ([topology audit](../packages/mission-control-db-contract/runtime/AGENT_SERVER_TOPOLOGY.md)) |

The advice you received, "do not create a custom schema space, let the server write its own
tables", is right for the Agent Server and wrong for the worker. The Agent Server has no schema
setting, its SQL is unqualified and collides with the standalone saver's table names, and the
official docs say multiple deployments can share a Postgres *instance* but never a *database*
([deploy-standalone-server](https://docs.langchain.com/langsmith/deploy-standalone-server)). The
worker's saver, by contrast, is deliberately confined to a private schema with a restricted role,
and that is what the release qualifies. Keep both as they are.

### 5.2 Hosting the Agent Server: options on a Plus plan

| Option | Postgres and Redis | Plan and licence | Per-app isolation | Verdict |
| --- | --- | --- | --- | --- |
| **LangSmith Cloud deployment, one per app** | LangChain-hosted; Serverless uses a shared multi-tenant database, Dedicated gets its own | Plus or above; one Serverless (Small) included, extra deployments billed at 0.0675 LSU/vCPU-h plus 0.009 LSU/GiB-h runtime (about $62/month for a Small that stays provisioned; less with scale-to-zero, which is beta) | Two deployments give two separate native databases bound to one app each, satisfying ADR-0017's "never shared" rule; the vendor still hosts the bytes | **Recommended.** Custom auth (`auth.path`) and the custom `http.app` are supported on Cloud. The worker reaches `https://<deployment>.us.langgraph.app` outbound. |
| Self-hosted standalone container on AWS | Yours: one database per deployment (Neon, RDS or a second Supabase project) plus Redis | **Enterprise plan and licence key** per the current docs; a free "Lite" tier is **UNVERIFIED** and no longer documented | Full control | Not available to you today. Revisit only if LangChain reinstates a non-Enterprise standalone path. |
| `langgraph dev` on the worker host | In-memory | None | None | Development and local proof only; the Makefile target. |
| In-process ASGI transport (no `url`) | Served by the same Agent Server | — | — | Does not apply: it requires the parent to run inside the Agent Server. Mission Control's parent runs inside a Temporal activity. |
| No async subagents | — | — | — | A real lever. Synchronous subagents need no server, but ADR-0006 rejected them for durability. Reconsider only in the pending Deep Agents brief (D7). |

Facts that constrain the Cloud option:

- Deployment regions: GCP US by default; the AWS US LangSmith region does not yet support deployments. Your workers in `us-east-1` call GCP US over the public internet, which is acceptable for a background queue.
- The repository pins `langgraph-api==0.12.0` and `api_version` `0.12.0` in `agent_server/langgraph.json`. Scale-to-zero deployments reject revisions below Agent Server 0.13.0, and the current server line is 0.17. Using the included slot with scale-to-zero means re-pinning and re-running the Block C N/N+1 drills; without scale-to-zero the deployment bills while provisioned.
- Custom auth on Cloud today is the signed scope claim in `agent_server/async_subagents/auth.py`. Its symmetric key is shared by all workers and the server; the module's own docstring asks for asymmetric or per-scope keys before production. Treat that as a prerequisite for a Cloud deployment that serves both apps' workers.
- Data class: Serverless shares database infrastructure with other LangChain tenants, and `LANGSMITH_HIDE_INPUTS`/`HIDE_OUTPUTS` are already the fail-closed baseline. Keep the `deep_agents` lane at data class `internal` or lower until a Dedicated deployment or an owner decision says otherwise.
- The run timeout for a background run defaults to 24 hours; API requests and streams cap at one hour, so the worker must reconnect to `thread_id` and `run_id` rather than hold one stream. The adapter already persists both and reconciles by spawn key.

### 5.3 Managed Deep Agents (public beta)

Managed Deep Agents (MDA) is LangChain running the open-source Deep Agents harness for you on
Agent Server: you upload a project folder (`agent.py` with `define_deep_agent`, `instructions.md`,
`skills/`, `tools/`, `middleware/`, optional `sandbox/`, `memory.py`, `identity.py`, `channels/`,
`schedules/`) with the `mda` CLI, and LangSmith compiles it with `create_deep_agent`, supplies the
checkpointer, store and backend, and hosts it with the Agent Server API and an MCP endpoint at
`/mcp` ([overview](https://docs.langchain.com/langsmith/python/managed-deep-agents-overview),
[deploy](https://docs.langchain.com/langsmith/python/managed-deep-agents-deploy)). It is in public
beta on LangSmith Cloud, GCP regions only; billing for MDA deployments is **UNVERIFIED** (not
stated on the pages read; assume ordinary deployment and sandbox meters until confirmed).

What it gives and what it takes away, measured against the Deep Agents lane as built:

| Mission Control needs | MDA |
| --- | --- |
| Exact, digest-pinned materialization (model factory, tools, middleware, subordinate profiles) | Tools, middleware and `subagents` carry over unchanged; the runtime compiles them. A graph factory can select instructions, skills, MCP servers and sandbox per run from `context`. |
| Private `mission_control_runtime` saver and store | **Dropped.** "Threads, runs and persistence come from Agent Server"; `store` and `checkpointer` parameters are removed. |
| Custom state schema (`DeepAgentState` extensions, `belllabs_*` state keys) | **Not accepted** in Python (`state_schema` has no equivalent). |
| Custom auth module and custom HTTP routes (`deployment_auth:auth`, `http_app:app`, the served-graphs endpoint) | **Not available.** Identity is one of three modes: LangSmith API key, Supabase JWT (verified against `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json`), or a backend shared secret with `x-mda-user-id`. Custom routes require an ordinary LangSmith deployment. |
| Docker or LangSmith sandbox chosen by binding | One managed LangSmith Sandbox per durable thread, declared in `sandbox/`, with a snapshot baked from `setup.sh`, an auth proxy that injects workspace secrets into outbound calls, and an allowlist. No other backend. |
| Kernel Hooks middleware, compaction observer, frame recorder | Middleware carries over; frame capture happens client-side from the run stream, so it keeps working. |
| Human gates | `interrupt_on` is supported. |

Assessment:

1. **MDA is not a drop-in host for the existing async child graph.** The child graph depends on custom auth, a custom HTTP route and custom state keys, all of which MDA removes. Moving it would be a redesign, and the ordinary LangSmith deployment (§5.2) hosts it as is.
2. **MDA is a credible new *provider-hosted lane*, not a replacement for the worker.** It behaves like `claude_managed` with a Deep Agents harness: LangChain runs the loop, Mission Control drives it through the Agent Server API (threads, runs, stream, cancel, `interrupt_on`), executes gated effects through Mission Control-owned tools, and treats native threads as recovery state. It would fit SPEC-06's Remote Session Lane base and the data-class policy, and its Supabase identity mode matches how Mission Control already verifies callers. This belongs in the pending Deep Agents brief (D7), not in this sprint.
3. **MDA's MCP endpoint is a direct-to-provider path** in the spirit of SPEC-08: a Claude Code session can call a deployed agent as a tool with `claude mcp add --transport http … --header "x-api-key: $LANGSMITH_API_KEY"`. The endpoint is stateless per call and the key is a workspace-wide secret, so it suits the owner's own sessions, not multi-tenant exposure.

### 5.4 The worker side of Deep Agents

Nothing about the worker changes with any Agent Server choice. It needs, per application: the runtime DSN, the family-writer DSN and the checkpointer DSN on the same Supabase host, the Temporal namespace, `CAPABILITY_PINS_PATH`, the deployment file and binding digest, the model keys the bindings name, the Agent Server endpoint and credential reference, and `S3_BUCKET` once API and worker are on different hosts (split-host payload custody, MO-64). Sizing from the prepared plan is 1 vCPU / 2 GiB per app worker, unmeasured.

## 6. Temporal Cloud and workers

- Temporal Cloud "runs the Temporal Server as a managed service. It does not run or manage your applications or Workers" ([security](https://docs.temporal.io/evaluate/cloud/security)). Workers poll task queues over outbound gRPC with TLS; Temporal needs to know nothing about their network, and no inbound connectivity is required ([serverless workers](https://docs.temporal.io/serverless-workers)).
- **Serverless Workers** exist: Temporal's Worker Controller invokes compute in *your* account on AWS Lambda (15-minute invocation cap), Amazon Bedrock AgentCore Runtime (8-hour session) or GCP Cloud Run worker pools, Python supported, Worker Versioning required. Temporal's own guidance excludes workloads that need persistent connections or exceed the provider limit. Mission Control's lane activities hold `codex app-server` and Claude Code subprocesses for hours and keep a loopback hook listener, so this is not a fit. Release stage **UNVERIFIED**.
- Temporal Nexus is cross-namespace service calling, not worker hosting.
- The only Vercel-related Temporal integration is the TypeScript `@temporalio/ai-sdk` plugin. No product runs Temporal Workers on Vercel Fluid compute, and nothing exists for Python (**UNVERIFIED** beyond "none found").
- Cloud facts the sprint relies on: API-key auth with `tls=True` (the code refuses a split between the deployment's address and the environment), the namespace endpoint `<ns>.<account>.tmprl.cloud:7233` or the regional `us-east-1.aws.api.temporal.io:7233`, custom search attributes added through the Cloud UI or `tcld` (removal unsupported; limits apply), Worker Versioning labelled **Preview** on the pricing page although the Python SDK supports it from 1.11. The worker promotes a Worker Deployment version on start (`TEMPORAL_PROMOTE_ON_START`); treat that as preview behaviour on Cloud and keep the two namespaces as the blast-radius boundary.
- Pricing (pay-as-you-go page, 2026-10-12): $50 per million Actions, $0.042/GBh active storage, $0.00105/GBh retained, plus 10% of usage for support, with $150 of credits for 90 days. The repository's worked example lands near $10/month at 100k actions.

So the worker runs where you put it: WSL2 now, an AWS host or Fargate task next, and a lane-only worker (MO-63) on Daytona later for the self-hosted executors.

## 7. Workers and environments per provider

| Lane profile | Who runs the agent loop | Mission Control process you must host | Inbound needed | Sandbox or workspace | Credentials (delivered by the Secret Broker, never in prompts) |
| --- | --- | --- | --- | --- | --- |
| `deep_agents` | Mission Control worker (parent, in-process) and the Agent Server (async children) | Worker; Agent Server deployment per app (§5.2) | None | `StateBackend`, LangSmith Sandbox or network-isolated Docker, chosen by binding | Model keys on the worker; `BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN` signing secret; `LANGSMITH_API_KEY` for tracing |
| `cursor_local` | Cursor bridge subprocess on the worker | Worker on Linux, macOS or WSL (Windows after CM-04) | None | Worktree leases on the Linux filesystem (`CURSOR_LEASE_ROOT`) | `CURSOR_API_KEY` |
| `cursor_cloud` | Cursor | Worker (reconcile, relay); Vercel ingress for OIDC-signed hook signals and v0 webhooks | **Public ingress** | Cursor's repository environment, synced `.cursor/environment.json` | `CURSOR_API_KEY`; GitHub app or PAT |
| `claude_agent_sdk` (local) | Claude Agent SDK on the worker driving its bundled CLI | Worker in WSL2 | None | Leases under `MISSION_CONTROL_CLAUDE_LEASE_ROOT` | `ANTHROPIC_API_KEY` (R21) |
| `claude_agent_sdk` (Sandbox Host, S4) | Same SDK on the worker, CLI inside Daytona or Docker via the `SandboxHost.exec` transport | Worker; Model Gateway (Vercel routes for Daytona, worker host for Docker); kit snapshot | Public gateway on `*.vercel.app` | Daytona sandbox per lease (Tier 1/2: essential-services egress only) | Per-run minted gateway token as `ANTHROPIC_AUTH_TOKEN`; org key only in Vercel production env or on the worker |
| `codex` (local) | `codex app-server` on the worker | Worker in WSL2, Codex pinned 0.162.1 | None | Leases under `MISSION_CONTROL_CODEX_LEASE_ROOT` | ChatGPT login in owner home mode, or `OPENAI_API_KEY` isolated |
| `codex` (remote executor, S4) | `codex app-server` on the worker, `codex exec-server` in the sandbox over `environment/add` | Worker; SandboxHost | None if the worker-local relay is used; otherwise a `wss://` port exposed by the sandbox provider | Daytona or Docker, same Codex release on both sides | Capability token for the executor; `OPENAI_API_KEY` on the worker |
| `claude_managed` cloud | Anthropic Managed Agents | Worker (session API client, reconcile); Vercel ingress for Standard-Webhooks wake-ups | Public ingress | Anthropic cloud sandbox | `ANTHROPIC_API_KEY`; Console webhook secret |
| `claude_managed` self-hosted | Anthropic runs the loop; the worker polls the work queue and executes every tool in Daytona | Worker (or lane-only worker) with the environment key; SandboxHost | Public ingress for wakes | Daytona, no Anthropic credentials inside | Environment key on the worker only |
| `codex_agents` OpenAI-hosted | OpenAI Agents API with the closed Codex harness | Worker; ingress for `agent.session.*` webhooks | Public ingress | OpenAI sandbox | Dedicated OpenAI project key, restricted scopes |
| `codex_agents` self-hosted | OpenAI runs the loop; `codex exec-server --remote` inside Daytona connects out | Worker; SandboxHost; ingress | Public ingress | Daytona, connect-only environment key | Environment key (`api.agents.environments.connect`) |
| `claude_cloud`, `codex_cloud` | Subscription products | Deferred (SC-01 to SC-03) | — | — | — |
| Local CLI job skills (SPEC-08) | The CLIs themselves, outside Mission Control | None (no Mission Control runtime dependency) | None | Parallel worktrees on the owner machine | Owner subscriptions and `CURSOR_API_KEY` |

Shared pieces every cloud lane needs: Environment Kits with base and mission layers (SPEC-01),
the Secret Broker and minted run tokens, the Vercel ingress with `ingress_*` tables from
migration 0035 (component 1.4.0, pre-approved), the IngressDrainer in the worker, wake channels
(`missionctl wait`, MCP `inbox_wait`), and a payload store that both API and worker can reach
(filesystem on one host, S3 across hosts).

## 8. The path to remotely spawning long-running missions

Ordered so each step is useful on its own and matches the sprint's slices.

1. **Stage 0, this sprint's S0 (owner machine, Temporal Cloud).** API on Windows, worker in WSL2, Supabase at 1.3.0, `TEMPORAL_TARGET=cloud` against `mission-control-dev.ih0e7`. Launch from Claude Code, Codex or Cursor through `missionctl` and the authenticated MCP; wake through `missionctl wait`. What you get: real Claude Code, Codex and Cursor harnesses running under durable Temporal control, with no inbound exposure. What you do not get: launching from anywhere else, or provider callbacks.
2. **Stage 1, S1 (Vercel ingress and gateway).** Create the `overtons-projects` Vercel project with root `deployments/ingress-vercel`, region `iad1`, production-only sensitive env vars, trailing-slash redirects off, one firewall rule; apply 1.4.0 and the restricted `mc_ingress_<app>` login; register Anthropic, OpenAI, GitHub webhooks. This makes `cursor_cloud` and the hosted API lanes observable and gives Daytona sandboxes a reachable gateway host.
3. **Stage 2, remote control plane (AWS).** Put API, MCP mount and one worker per app on one `us-east-1` host from the `cloud_runtime` image, TLS in front, secrets injected at start, `S3_BUCKET` set on API and worker. Register search attributes on the Cloud namespace, keep the WSL2 worker as a second worker on its own lane queue (`MISSION_CONTROL_LANE_TASK_QUEUES`) while the AWS worker handles base queues, or move everything to AWS once the Linux subprocess lanes are proven there. From this point missions can be spawned from any authenticated client.
4. **Stage 3, Agent Server on LangSmith Cloud.** Deploy `agent_server/langgraph.json` as one deployment per app, starting with the included Serverless (Small) for Biotech; set `AGENT_SERVER_ENDPOINT` and the signing secret on each worker; run the Block C qualification drills against the real deployment; decide on scale-to-zero (requires re-pinning `langgraph-api` to 0.13 or later). Only then flip `async_subagent_spawning_enabled`.
5. **Stage 4, S4 Sandbox Host.** Daytona kit snapshots, the SandboxHost port, lane-only workers (MO-63) so that Daytona-side workers hold only the runtime role.
6. **Stage 5, graduate.** Move from the single host to the ECS/Fargate layout when a second worker per app, task-role secrets or zero-downtime deploys matter; move the Agent Server to a Dedicated deployment if data class or isolation demands it; promote to `mission-control-prod.ih0e7` after qualification.

## 9. Cost sketch for the recommended path

Monthly, on-demand, before model usage, taxes and the existing Supabase and LangSmith seats. Figures are vendor list prices read on 2026-10-12 or the repository's verified regional estimates; none is a cap.

| Component | Choice | Estimate | Source |
| --- | --- | --- | --- |
| Control plane host | Lightsail 2 vCPU / 4 GiB (or 8 GiB) | $24 (or $44) plus about $4 snapshots | [Lightsail pricing](https://aws.amazon.com/lightsail/pricing/); APPROVAL_PLAN |
| Alternative: Fargate | API 0.5 vCPU / 2 GiB plus two 1 vCPU / 2 GiB workers, ALB, NAT, secrets, logs | $166–185 | APPROVAL_PLAN verified `us-east-2` estimate |
| Temporal Cloud | 100k actions, small histories | about $10 | [Temporal pricing](https://temporal.io/pricing) |
| Agent Server | Included Serverless (Small) for one app; second app Serverless (Small) provisioned | $0 plus about $62 if the second stays provisioned (less with scale-to-zero) | [LangSmith pricing](https://www.langchain.com/pricing) |
| Vercel | Pro, already paid; ingress and gateway function time | within Pro allowances for the sprint's volumes | [Fluid limits](https://vercel.com/docs/functions/limitations) |
| Daytona | 2 vCPU / 4 GiB about $0.17/h, per second, $200 credit | drills within credit | [Daytona pricing](https://www.daytona.io/pricing) |
| S3 and secrets | 20 GB artifacts, 16 secrets | about $7 | APPROVAL_PLAN |

## 10. Decisions the owner still has to make

1. **First AWS target:** one Lightsail host in `us-east-1` (recommended) versus the prepared Ohio ECS plan. The ECS renderer prepares task definitions only; a host needs its own supervision config and a reviewed public TLS approval.
2. **Agent Server placement:** confirm the Plus entitlement and the unused included slot inside the LangSmith account, and choose per-app deployments on Cloud versus deferring async subordinates until the Deep Agents brief (D7).
3. **Agent Server version:** keep `langgraph-api` 0.12.0 and run provisioned, or re-pin to 0.13 or later for scale-to-zero and redo the N/N+1 drills.
4. **Signing key design** for the async subordinate server before two apps' workers share one Cloud deployment family (asymmetric or per-scope keys).
5. **Managed Deep Agents:** record it as a candidate provider-hosted lane for the D7 brief; not in this sprint.
6. **Storage bucket seed** `mc.storage.capability-bundles` (one yes, needed in wave C).
7. **Region alignment:** Supabase and Temporal are in `us-east-1`; the AWS plan says `us-east-2`; LangSmith deployments are GCP US. Accept the cross-region hops or move the AWS plan to `us-east-1`.

## 11. Open verification items

- LangSmith account facts: plan, region, deployment list, included-slot consumption, MDA beta access. No connector exposed them.
- Whether a non-Enterprise standalone Agent Server path still exists ("Lite" tier): docs say Enterprise only.
- Managed Deep Agents billing meters and whether an MDA deployment consumes the included Serverless slot.
- Temporal Serverless Workers release stage; Worker Versioning behaviour against Cloud with an API key.
- Vercel Python preset support for `buildCommand` and outside-root sources in a monorepo (SPEC-10 V1), measured cold start of the slim closure (V2).
- Cold-start and p99 of the gate route; DEPLOYMENT-AND-RELEASE forbids unmeasured SLOs.

## 12. Sources

Repository: [AGENTS.md](../AGENTS.md); [SPRINT](specs/archive/materialization-observation-2026-10/SPRINT.md), [DECISIONS](specs/archive/materialization-observation-2026-10/DECISIONS.md), [SPEC-06](specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md), [SPEC-09](specs/archive/materialization-observation-2026-10/SPEC-09-local-harness-path.md), [SPEC-10](specs/archive/materialization-observation-2026-10/SPEC-10-ingress-on-vercel.md); research notes [vercel-ingress](specs/archive/materialization-observation-2026-10/research/vercel-ingress.md), [s0-local-harness](specs/archive/materialization-observation-2026-10/research/s0-local-harness.md), [harness-in-sandbox](specs/archive/materialization-observation-2026-10/research/harness-in-sandbox.md); ADRs [0002](adr/0002-one-service-two-applications-schema-per-app-database.md), [0006](adr/0006-agent-server-required-execution-host-not-scheduler.md), [0015](adr/0015-remote-mcp-oauth-no-jwt-forwarding.md), [0017](adr/0017-agent-server-runtime-persistence-separate-database.md), [0019](adr/0019-coding-lanes-worker-hosted-local-first.md); knowledge [operations](knowledge/operations.md), [persistence](knowledge/persistence.md), [deep-agents-lane](knowledge/deep-agents-lane.md), [lanes-and-harness](knowledge/lanes-and-harness.md), [interfaces](knowledge/interfaces.md); [DEPLOYMENT-AND-RELEASE](knowledge/deployment.md); [cloud_runtime README](../deployments/cloud_runtime/README.md), [APPROVAL_PLAN](specs/archive/mc-surfaces-2026-10/deployments/cloud_runtime/APPROVAL_PLAN.md), [INVENTORY](specs/archive/mc-surfaces-2026-10/deployments/cloud_runtime/INVENTORY.md); [Agent Server topology audit](../packages/mission-control-db-contract/runtime/AGENT_SERVER_TOPOLOGY.md); `agent_server/langgraph.json`, `adapters/agent_server/*`, `adapters/deep_agents/{persistence,async_subagents}.py`, `bootstrap/{worker,settings}.py`, `docker-compose.yml`, `Makefile`, `pyproject.toml`.

LangChain (read 2026-10-12): [deployment options](https://docs.langchain.com/langsmith/deployment), [self-hosted overview](https://docs.langchain.com/langsmith/deploy-to-self-hosted-overview), [standalone server](https://docs.langchain.com/langsmith/deploy-standalone-server), [self-hosted env vars](https://docs.langchain.com/langsmith/env-var-self-hosted), [cloud env vars](https://docs.langchain.com/langsmith/env-var-cloud), [cloud features](https://docs.langchain.com/langsmith/cloud-platform-features), [billing](https://docs.langchain.com/langsmith/billing), [changelog](https://docs.langchain.com/langsmith/changelog), [custom auth](https://docs.langchain.com/langsmith/custom-auth), [custom routes](https://docs.langchain.com/langsmith/custom-routes), [async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents), [`AsyncSubAgent` reference](https://reference.langchain.com/python/deepagents/middleware/async_subagents/AsyncSubAgent), [pricing](https://www.langchain.com/pricing), Managed Deep Agents [overview](https://docs.langchain.com/langsmith/python/managed-deep-agents-overview), [quickstart](https://docs.langchain.com/langsmith/python/managed-deep-agents-quickstart), [migrate](https://docs.langchain.com/langsmith/python/managed-deep-agents-migrate), [agent definition](https://docs.langchain.com/langsmith/python/managed-deep-agents-agent-definition), [sandboxes](https://docs.langchain.com/langsmith/python/managed-deep-agents-sandboxes), [identity](https://docs.langchain.com/langsmith/python/managed-deep-agents-identity), [MCP endpoint](https://docs.langchain.com/langsmith/python/managed-deep-agents-mcp-endpoint), [deploy](https://docs.langchain.com/langsmith/python/managed-deep-agents-deploy).

Temporal: [Cloud security](https://docs.temporal.io/evaluate/cloud/security), [serverless workers](https://docs.temporal.io/serverless-workers), [serverless workers feature](https://docs.temporal.io/evaluate/features/serverless-workers), [namespaces](https://docs.temporal.io/cloud/namespaces), [worker versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning), [Python client](https://docs.temporal.io/develop/python/client/temporal-client), [search attributes](https://docs.temporal.io/search-attribute), [pricing](https://temporal.io/pricing), [Nexus](https://docs.temporal.io/nexus).

Vercel and AWS: [functions limitations](https://vercel.com/docs/functions/limitations), [Fluid compute](https://vercel.com/docs/fluid-compute), [WebSockets](https://vercel.com/docs/functions/websockets), [Sandbox pricing](https://vercel.com/docs/sandbox/pricing), [Sandbox Python SDK](https://vercel.com/docs/sandbox/python-sdk-reference), [Workflows](https://vercel.com/docs/workflows), [Fargate pricing](https://aws.amazon.com/fargate/pricing/), [App Runner pricing](https://aws.amazon.com/apprunner/pricing/), [Lightsail pricing](https://aws.amazon.com/lightsail/pricing/), [Daytona pricing](https://www.daytona.io/pricing).
