---
type: Working Draft
title: "Infrastructure map draft: every data plane, credential location, remote, MCP server, local service and CLI"
description: "Sitting II pre-question draft (item 2 of 'Before the first question'): the AGENTS-MD-GRAMMAR-DRAFT §4 table filled for the BellLabs workspace and each repository, an env-variable name matrix (names only, never values) against code readers, the naming inconsistencies that make planes non-obvious, and the unknown or stale entries. Input to Q11 (one infrastructure surface) and Q12 (one name per plane)."
tags: [workspace, infrastructure, sdlc, draft]
date: 2026-11-01
status: draft
---

# Infrastructure map draft (2026-11-01)

> **Update 2026-11-06 (GitHub home):** the `git@github-legacy:Overton77/<repo>.git` remotes below are superseded for the
> repositories that moved to `jbell-rusty-vantage` as clean slates (`main` only, HTTPS through the `gh` credential helper, no
> pre-move commit IDs): Mission Control → `agentic-mission-control`, Knowledge Services → `agent-knowledge-services`, AI Engineer
> DB contract → `agent-engineer-db-contract` (its `contract.yml` now checks out `agent-knowledge-services`), Agentic SDLC →
> `agentic-sdlc`. All four are public. Biotech KS and the other rows still name their Overton77 remotes until they move. Current
> status: [worktree routing](../../../../../docs/navigation/WORKTREES.md#github-move-and-clean-slate-2026-11-06).

Input to sitting II, Q11 and Q12 (`INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md:41-46`,
`:122-130`). Table shape: `AGENTS-MD-GRAMMAR-DRAFT-2026-11-01.md:97-114`. Seed registry:
`docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` (cited below as **DPC**). Paths are relative to
`C:\Users\Pinda\Proyectos\BellLabs`.

**How this was gathered (read-only, 2026-11-01).** Names were taken from `.env*` files with a
`NAME=` pattern match; values were never printed or recorded. A DB or graph variable's plane is
shown only where DPC states it. Where DPC is silent, the column says "observed": a script matched
the value against the known project refs and Aura ids and printed only the matching label. No
database, graph or MCP server was contacted. "Read in code" means the name appears in tracked
code or config (`.py/.ts/.js/.mjs/.sh/.toml/.json/.yml`), tests included. It is a reference, not
proof the variable is loaded at runtime.

## 1. Workspace, one screen

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| **biotech-db** (disposable) | Supabase `biotech-research-ingestion`, ref `bxnetwiimwhtlrjlbtab`, MC installation `01a103c0-…-29dda83c842b` (DPC:11) | MC and BKS `.env` as `DATABASE_DIRECT`, `DATABASE_URL`, `DIRECT_URL`, `SUPABASE_*` (DPC:30,35); legacy JWT in `platform/mission-control/.scratch/sprint-oc/secrets/biotech/legacy-jwt.env` (DPC:39) / no CI / none | MCP `supabase-biotech` (read-only, PAT header `${SUPABASE_MCP_ACCESS_TOKEN}`, `.mcp.json:7`); DSNs through `scripts/sprint_oc_runtime_env.py` | DPC §1, `ENVIRONMENT-AND-DATABASES.md:19` |
| **biotech-graph** (disposable) | Aura "Biotech KG" `8032ec07` (DPC:12; pinned `deployments/biotech/graph.toml:12`) | MC and BKS `.env` `NEO4J_URI`, `NEO4J_AURA_USERNAME`, `NEO4J_AURA_PASSWORD` (DPC:31); generated `runtime/biotech/install.env:21-23` / none / none | No MCP. The planned `neo4j-biotech` (DPC:77) is absent from every `.mcp.json`. Access is through BKS kg-ops/executor. | DPC §2.2 |
| **aieng-db** (disposable) | Supabase `supabase-blue-ocean`, ref `wkythqbofmckbuoothhn`, pooler login `postgres.wkythqbofmckbuoothhn` (DPC:13) | `aiengineer/.env` (not in any git repo) and every `aiengineer/*/.env`, plus KS `.env`, as `POSTGRES_URL*`, `SUPABASE_*` (DPC:36,38) / none / Vercel project env (two linked projects, §2.7) | MCP `supabase-aieng` (`.mcp.json:3`, OAuth, **no header, so not authenticated in this session**); DSNs through the generator (`sprint_oc_runtime_env.py:107`) | DPC §1 |
| **aieng-graph**: NEVER WRITE | Aura `4773dc72` (DPC:14); refused by `deployments/biotech/graph.toml:17` | `aiengineer/*/.env` and KS `.env` `NEO4J_AURA_URI`, `NEO4J_AURA_USERNAME`, `NEO4J_AURA_PASSWORD` (DPC:37-38) / none / none | Not reached; no MCP (DPC:79-80) | DPC:14 |
| Supabase org | Vercel-managed "Overton's projects" `vercel_icfg_SIEqFciu9zf7npelC0RqFUee` (DPC:16) | `SUPABASE_MCP_ACCESS_TOKEN`: Windows user env (set) **and** MC `.env:163` | Dashboard via Vercel → Storage → Supabase (DPC:17). Also the claude.ai Supabase connector, which is org-wide and exposes write tools (DPC:85-86) | DPC §2.1 |
| GitHub | `git@github-legacy:Overton77/<repo>.git` (§2); ssh alias `github-legacy` → `~/.ssh/id_rsa_legacy` (`~/.ssh/config:2`) | ssh key local / `KS_READ_TOKEN`, `MAINTENANCE_APP_PRIVATE_KEY`, `CURSOR_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` repo secrets (KS, AIDB workflows) / GitHub App `MC_GITHUB_APP_*` names in MC `.env` | git over ssh. `gh` CLI: **active account `jbell-rusty-vantage`**, while `Overton77` is logged in but inactive | SPEC-01 §10 |
| Linear | workspace `overtonbell`, team `OVE` (`docs/agents/issue-tracker.md:9`) | MC `.env` `LINEAR_API_KEY:123` (also in BKS `.env`) / repo secret (planned, SPEC-01 §10) / network secret (planned) | MCP `linear`, in both `platform/mission-control/.mcp.json:3` and user `~/.claude.json`; GraphQL | `issue-tracker.md` |
| Model vendors | Anthropic producer, Anthropic auditor, OpenAI judge (DPC:34) | MC `.env` `ANTHROPIC_API_KEY:110`, `SECOND_ANTHROPIC_API_KEY:161`, `OPENAI_API_KEY:1`; generated as `MC_AUDITOR_ANTHROPIC_API_KEY`, `MC_JUDGE_OPENAI_API_KEY` (`sprint_oc_runtime_env.py:101-102`) / KS repo secrets / none | env injection by the generator | DPC:34, DPC:103 |
| Cursor adapter | `agent` CLI 2026.10.01-14929f9 | `CURSOR_API_KEY` in MC `.env` **twice with different values** (`:29`, `:147`), and in KS, BKS and `aiengineer/*` `.env` / KS repo secret / Cursor account | `agent` CLI; `.sdlc/cli.mjs propose` is planned | SPEC-01 §8, §10 |
| LangSmith | project names `LANGSMITH_PROJECT`, `AGENT_SERVER_LANGSMITH_PROJECT` | MC and BKS `.env` `LANGSMITH_API_KEY` / none / none | env | `ENVIRONMENT-AND-DATABASES.md:28` |
| Temporal | local dev `127.0.0.1:7233`, UI `:8080` (`docker-compose.yml:97,125`); SDK test server `7341` (`ENVIRONMENT-AND-DATABASES.md:25`); Temporal Cloud namespaces named in MC `.env:121,129-131,140` (identity not in registry) | `TEMPORAL_CLOUD_API_KEY` (MC, BKS, KS, `aiengineer` `.env`) / none / none | compose; `TEMPORAL_TARGET=cloud` re-pointing (`WSL2_WORKER_RUNBOOK.md:109-112`). `temporal` CLI is not on the Windows PATH. Not running at check time. | `WSL2_WORKER_RUNBOOK.md` §6 |
| Agent Server (LangGraph) | `127.0.0.1:2024` ai-engineer, `:2025` biotech (`sprint_oc_runtime_env.py:95-96`); `agent_server/langgraph.json` | generated `runtime/<app>/agent-server.env` | `langgraph` CLI 0.4.7 | `ENVIRONMENT-AND-DATABASES.md:26` |
| Local Postgres / Redis | `sprint-v-pg17` `127.0.0.1:55433` (**running**); owner app DB `:55432` (`APPLICATION_*`, **not running**); Redis `:16379` | container env (`POSTGRES_USER=sprintv`) | docker | DPC:21-22 |
| Unregistered local containers | `mc-overnight-20261029-pg17` `127.0.0.1:55434`; Supabase local stack `disposable-overnight-20261029`, kong `0.0.0.0:54821`, db `0.0.0.0:54822` (running, `docker ps`) | unknown | docker | none (§5) |
| WSL2 | `Ubuntu` (Running, v2, default), `docker-desktop` (Running, v2); MC API `127.0.0.1:18090` in WSL (`WSL2_WORKER_RUNBOOK.md:23`) | in memory over stdin from the private operator script (`WSL2_WORKER_RUNBOOK.md:61-62`) | `wsl` | `WSL2_WORKER_RUNBOOK.md` |
| Cloud environments | Cursor `platform/mission-control/.cursor/environment.json` (`mc:envkit.mission-control-dev@1`, ports 8000/8080); `aiengineer/ai-engineer-industry-cloud-automated-research/.cursor/environment.json` (port 4848); **no Claude Code cloud environment found** | per environment (Cursor account secrets; not inspectable from disk) | the session | SPEC-01 §10 (one per repository is planned for the last slice) |
| `.secrets/` (proposed) | `BellLabs/.secrets/{biotech-db,biotech-graph,aieng-db,aieng-graph,models,supabase-account}.env` (DPC:94-104) | **does not exist** (checked 2026-11-01) | none | DPC §3 |

### 1b. Host CLIs (Windows, `--version` on 2026-11-01)

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| `claude` | 2.1.316, `~/.local/bin/claude.exe`. The WSL SDK bundles 2.1.294 (`WSL2_WORKER_RUNBOOK.md:30`). | `/login` session; `CLAUDE_CODE_OAUTH_TOKEN` for CI (planned) | PATH | SPEC-01 §10 |
| `agent` / `cursor-agent` | 2026.10.01-14929f9, `%LOCALAPPDATA%\cursor-agent\` | `CURSOR_API_KEY` | PATH | SPEC-01 §8 |
| `codex` | codex-cli 0.162.1, which equals the WSL pin (`WSL2_WORKER_RUNBOOK.md:31`) | `OPENAI_API_KEY` | PATH | runbook |
| `uv`, `python` | uv 0.12.23; Python 3.12.2 | n/a | PATH | n/a |
| `node`, `pnpm` | node v24.18.0. The Cursor bridge in WSL pins v24.5.0 (`WSL2_WORKER_RUNBOOK.md:33`). pnpm 11.15.1. | n/a | PATH | n/a |
| `gh` | 2.87.2; accounts `jbell-rusty-vantage` (active) and `Overton77` | Windows keyring | PATH | n/a |
| `docker` | 29.8.2 (Docker Desktop) | n/a | PATH | n/a |
| `supabase`, `langgraph` | supabase 2.98.2 (scoop); LangGraph CLI 0.4.7 | n/a | PATH | n/a |
| User-level MCP | `~/.claude.json`: `linear`, `edgartools`, `tavily`, `firecrawl`; `~/.cursor/mcp.json`: 16 servers incl. `linear`, `tavily`, `firecrawl` | inside those files (not read) | client | none |

## 2. Per repository

### 2.1 `platform/mission-control` (branch `sprint-oc`)

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| Remote | `git@github-legacy:Overton77/mission-control.git`; retained worktree `.claude/worktrees/agent-a3ad8c12b136e094c` on `sprint-oc-selection-workspace` | ssh key / **no `.github/workflows`** (no CI) / none | git | `docs/navigation/WORKTREES.md` |
| `.env` | 86 names; points at **biotech-db + biotech-graph** (DPC:30-31) | `.env` (gitignored) | owner file read by the generator (`scripts/sprint_oc_runtime_env.py:89`) | DPC §1a |
| `.env.example` | 104 names; 11 names are read in code but exist only in the example (§3) | tracked | n/a | n/a |
| Generated runtime env | `.scratch/sprint-oc/runtime/{ai-engineer,biotech}/{install,mission-control,agent-server,ks-executor,bks-executor,bundle-*,logins,minted}.env` (ignored, `.gitignore:149`) | local only | `sprint_oc_runtime_env.py` | `ENVIRONMENT-AND-DATABASES.md` §4 |
| Tracked `agent_server/runtime.env` | 18 names, all `${…}` interpolations (no values) | tracked | `langgraph` | n/a |
| Deployment targets | `deployments/biotech/target.toml:11` ref `bxnetwiimwhtlrjlbtab`, `database_url_env = MC_BIOTECH_MIGRATION_DATABASE_URL` (`:20`); `deployments/ai-engineer/target.toml:12` ref `wkythqbofmckbuoothhn`, `MC_AI_ENGINEER_MIGRATION_DATABASE_URL` (`:24`); graph pin `deployments/biotech/graph.toml:12` | names filled by the generator | `mission-db` installers | DPC:106-109 |
| MCP | `linear` (`.mcp.json:3`) | OAuth | client | `issue-tracker.md` |
| Compose | `docker-compose.yml`: `application-postgres` `127.0.0.1:${APPLICATION_POSTGRES_PORT:-55432}` (`:15`), `redis` `127.0.0.1:${REDIS_PORT:-16379}` (`:31`), `temporal` `:7233` (`:97`), `temporal-ui` `:8080` (`:125`); `docker-compose.temporal.yml` (Temporal only, same ports) | compose env | `docker compose` | `WSL2_WORKER_RUNBOOK.md` |
| Runtime ports | MC API 8000 (ai-engineer) / 8001 (biotech); KS executor 4310 / 4311; BKS executor 4020; Agent Server 2024 / 2025 (`sprint_oc_runtime_env.py:95-96`); WSL API 18090 (`WSL2_WORKER_RUNBOOK.md:23`) | n/a | local | `ENVIRONMENT-AND-DATABASES.md` §4 |
| Cloud | Cursor `.cursor/environment.json` (Dockerfile, `cloud-install/start/infra.sh`); deployments `cloud_runtime`, `worker-aws`, `ingress-vercel` (templates; no deployment checked) | Cursor account | Cursor cloud agent | SPEC-01 §10 |

### 2.2 `platform/knowledge-services` (branch `sprint-oc`)

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| Remote | `git@github-legacy:Overton77/ai-engineer-knowledge-services.git` | ssh / CI `verify.yml`, `agent-maintenance.yml`, … use `secrets.{ANTHROPIC_API_KEY,CURSOR_API_KEY,OPENAI_API_KEY,MAINTENANCE_APP_PRIVATE_KEY}`, `vars.MAINTENANCE_APP_ID` / none | git | n/a |
| `.env` | 45 names; points at **aieng-db + aieng-graph** (DPC:38); "never for Biotech" (`ENVIRONMENT-AND-DATABASES.md:40`) | `.env` (gitignored); loaded by `node/tsx --env-file=.env` (`package.json:47-61`) | env file | DPC:38 |
| Sprint OC executor | `ks-executor.env` per app, ports 4310 / 4311 | generated (MC `.scratch`) | `verification-executor serve` | `ENVIRONMENT-AND-DATABASES.md:62` |
| Local API | `KNOWLEDGE_API_URL` → `127.0.0.1:4100` (KS `.env:63`) | `.env` | HTTP | n/a |
| Compose | `services/docling/compose.yaml`: `docling-serve` `127.0.0.1:5001` (`:7`) | none | docker | n/a |
| MCP | none in repo | n/a | n/a | n/a |

### 2.3 `platform/agentic-sdlc` (branch `main`)

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| Remote | `git@github-legacy:Overton77/belllabs-agentic-sdlc.git` | ssh / no CI yet / none | git | SPEC-01 §10 |
| Env, MCP, compose | none (no `.env`, no `.mcp.json`; 0 env reads in code) | n/a | n/a | `AGENTS.md` |

### 2.4 `biotech/biotech-knowledge-services` (branch `sprint-oc`)

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| Remote | `git@github-legacy:Overton77/biotech-knowledge-services.git` | ssh / `ci.yml` (no secrets referenced) / none | git | n/a |
| `.env` | 72 names, **a near-copy of MC `.env`**; **biotech-db + biotech-graph** (DPC:35); 57 of its names are not referenced in BKS code | `.env` (gitignored) | read by the MC generator (`sprint_oc_runtime_env.py:90,805-807`) | DPC:35 |
| `.env.example` | 78 names (`BKS_*`, `NEO4J_USERNAME/PASSWORD/DATABASE`, `GRAPHQL_*`); 60 are read in code but absent from `.env` | tracked | n/a | n/a |
| Production custody | `runs/release-v2/custody/s9/secrets/{admission-authority,bff-production,executor-production,graphql-production,migrator-production,verifier-signing-key}.env` (ignored by `.gitignore:9 runs/`) | local only | release tooling | schema-v2 release handoff |
| Compose | `apps/graphql-api/docker-compose.yml`: `neo4j` `7474`, `7687` (**all interfaces**, `:14-15`), `graphql-api` `4010` (`:36`) | compose env | docker | n/a |
| Executor | port 4020 ("firewall it", `ENVIRONMENT-AND-DATABASES.md:63`) | generated `bks-executor.env` | HTTP/MCP | n/a |
| MCP | `pubmed`, `pubchem`, `clinicaltrialsgov` (http), `edgartools` (uvx, env `EDGAR_IDENTITY`) (`.mcp.json:3-6`) | `EDGAR_IDENTITY` in BKS `.env` | client | DPC:84-85 |

### 2.5 `aiengineer/ai-engineer-db-contract` (branch `sprint-oc`)

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| Remote | `git@github-legacy:Overton77/ai-engineer-db-contract.git` | ssh / `contract.yml` uses `secrets.KS_READ_TOKEN`, `vars.KS_COMPONENT_REF` / none | git | n/a |
| DB access | **No `.env`**. Code reads ambient `POSTGRES_URL_NON_POOLING ?? POSTGRES_URL` (`scripts/schema-workspace/lib/db.mjs:9`) and says "no .env file is loaded" (`scripts/generate-types.mjs:53`). In practice the source is `aiengineer/.env` (aieng-db, DPC:36), outside this repo. | `aiengineer/.env` | `--db-url` or env | DPC:36 |

### 2.6 `aiengineer/ai-engineer-meta` (branch `main`)

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| Remote | **none**; `main` has **no commits**. The remote is listed "to create" in SPEC-01 §10. | n/a | n/a | SPEC-01 §10 |
| Env, MCP, compose | none (0 env reads in code) | n/a | n/a | n/a |

### 2.7 Other directories with `.git`

- `aiengineer/agents_dashboard`: `Overton77/ai-engineer-app-operations-dashboard`; Vercel project `ai-engineer-app-operations-dashboard`; `.env` names Aura **`e40f2c21`** (unknown) and aieng-db/aieng-graph; MCP `next-devtools`.
- `aiengineer/ai-engineer-industry-cloud-automated-research`: `Overton77/bell-missions-ai-engineer`; Cursor cloud env (port 4848); `.env` aieng-db/aieng-graph plus `OVERTON77_GITHUB_PAT`.
- `aiengineer/research_starter_pre_research_agent`: `Overton77/ai-engineer-channel-entity-video-intake-agent`; Vercel project `research-starter-pre-research-agent`; `.vercel/.env.production.local` (plane unknown, see §5).
- `sites/ai-research-field-guide`, `sites/knowledge-schema-workbench`: no remote.
- `biotech/.git` is an **empty directory**, so `biotech/` is not a repository. `biotech/biotech-postgres-db-contract` has no `.git` (SPEC-01 §10 lists it "to create").
- Not repos but credential-bearing: `aiengineer/.env` (the aieng-db source file the generator reads, `sprint_oc_runtime_env.py:91`), `aiengineer/internal/.env`, `aiengineer/internal/secrets/.env`, `aiengineer/becoming-master-ai-engineer/.env`, `biotech/.env.local`, and a Google OAuth `client_secret_<id>.apps.googleusercontent.com.json` at `biotech/` root.

## 3. Env variable name matrix

Columns: MC = `platform/mission-control`, KS = `platform/knowledge-services`, BKS =
`biotech/biotech-knowledge-services`, AIDB = `aiengineer/ai-engineer-db-contract`, DASH =
`agents_dashboard`, CLOUD = `ai-engineer-industry-cloud-automated-research`, PRE =
`research_starter_pre_research_agent`, AIE = the non-repo `aiengineer/.env`. `agentic-sdlc` and
`ai-engineer-meta` have no `.env` and no env reads, so they are omitted. Cells: **E** = in that
repo's `.env`/`.env.local`; **x** = only in `.env.example`; **C** = referenced in tracked
code/config; **E+C** = both; **·** = neither. Rows: every name in any real `.env` (159). Plane:
DPC citation, or "observed" (host match), or blank.

| Name | MC | KS | BKS | AIDB | DASH | CLOUD | PRE | AIE | One reader (file:line) | Plane |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AGENT_SERVER_LANGSMITH_PROJECT` | E+C | · | E | · | · | · | · | · | `platform/mission-control/scripts/sprint_oc_runtime_env.py:972` |  |
| `AI_GATEWAY_API_KEY` | · | E+C | · | · | · | E | E | E | `platform/knowledge-services/apps/jev/src/index.ts:29` |  |
| `AMAZON_Account` | E | · | E | · | · | · | · | · | none found |  |
| `AMAZON_ARN` | E | · | E | · | · | · | · | · | none found |  |
| `AMAZON_USER_ID` | E | · | E | · | · | · | · | · | none found |  |
| `ANTHROPIC_API_KEY` | E+C | C | E | · | · | · | · | · | `platform/mission-control/.agents/skills/coding-cli-jobs/scripts/adapters/common.py:54` | model vendor (DPC:34) |
| `APIFY_API_KEY` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/apify-transcript-ingest/ingest.mts:384` |  |
| `APIFY_USER_ID` | · | · | · | · | · | · | E | · | none found |  |
| `APPLICATION_DATABASE_DIRECT` | E+C | · | E | · | · | · | · | · | `platform/mission-control/experiments/langgraph_temporal_stagegraph/config.py:27` | MC/BKS: local 127.0.0.1:55432 (DPC:32) |
| `APPLICATION_DATABASE_URL` | E+C | · | E | · | · | · | · | · | `platform/mission-control/experiments/langgraph_temporal_stagegraph/config.py:28` | registry silent; empty in MC/BKS .env |
| `APPLICATION_MIGRATION_DATABASE_DIRECT` | E+C | · | E | · | · | · | · | · | `platform/mission-control/experiments/langgraph_temporal_stagegraph/config.py:35` | MC/BKS: local 127.0.0.1:55432 (DPC:32) |
| `APPLICATION_POSTGRES_PORT` | E+C | · | E | · | · | · | · | · | `platform/mission-control/docker-compose.yml:21` |  |
| `AURA_INSTANCEID` | · | · | · | · | E | · | · | · | none found | registry names e40f2c21 for agents_dashboard (DPC:18,37); observed = UNKNOWN e40f2c21 |
| `AURA_INSTANCENAME` | · | · | · | · | E | · | · | · | none found |  |
| `AWS_BEARER_TOKEN_BEDROCK` | E | E | E | · | E | E | E | E | none found |  |
| `AWS_REGION` | E+C | E | E | · | E | E | E | E | `platform/mission-control/deployments/cloud_runtime/plan.py:51` |  |
| `BEDROCK_EMBEDDING_MODEL_ID` | E | · | E | · | · | · | · | · | none found |  |
| `BEDROCK_EMBEDDING_MODEL_ID_FALLBACK` | E | · | E | · | · | · | · | · | none found |  |
| `CANONICAL_LOCAL_ONLY` | · | E+C | · | · | · | · | · | E | `platform/knowledge-services/packages/host/src/server/shared.ts:16` |  |
| `CLERK_SECRET_KEY` | E | · | E | · | · | · | · | · | none found |  |
| `CODEX_EMAIL` | E | · | · | · | · | · | · | · | none found |  |
| `CONTEXT7_API_KEY` | C | E | · | · | · | E+C | E | E | `platform/mission-control/scripts/aieng_stagegraph.py:62` |  |
| `CURSOR_API_KEY` | E+C | E+C | E | · | E | E | · | E | `platform/mission-control/.agents/skills/coding-cli-jobs/scripts/agentjob.py:41` |  |
| `CURSOR_EMAIL` | E | · | · | · | · | · | · | · | none found |  |
| `CURSOR_PASSWORD` | E | · | · | · | · | · | · | · | none found |  |
| `DATABASE_DIRECT` | E+C | C | E | · | · | · | · | · | `platform/mission-control/scripts/fast_track_dry_run.py:292` | MC/BKS: biotech-db (DPC:30,35) |
| `DATABASE_URL` | E+C | · | E | · | · | · | · | · | `platform/mission-control/scripts/report_source_proof.py:43` | MC/BKS: biotech-db (DPC:30,35) |
| `DAYTONA_API_KEY` | E+C | · | E | · | · | · | · | · | `platform/mission-control/src/mission_control/domain/frames/body.py:41` |  |
| `DAYTONA_IDLE_TTL_SECONDS` | E | · | E | · | · | · | · | · | none found |  |
| `DAYTONA_SNAPSHOT` | E | · | E | · | · | · | · | · | none found |  |
| `DIRECT_URL` | E+C | · | E | · | · | · | · | · | `platform/mission-control/scripts/report_source_proof.py:44` | MC/BKS: biotech-db (DPC:30,35) |
| `EDGAR_IDENTITY` | C | · | E+C | · | · | · | · | · | `platform/mission-control/packages/mission-control-db-contract/seeds/agent_capabilities.py:196` |  |
| `EMBEDDING_MODEL_COHERE` | · | E | · | · | E | E | E | E | none found |  |
| `EVE_TRACES` | · | · | · | · | · | · | E | · | none found |  |
| `EVE_TRACES_CONTENT` | · | · | · | · | · | · | E | · | none found |  |
| `EXA_API_KEY` | E+C | E | E+C | · | · | E | E | · | `platform/mission-control/src/mission_control/domain/frames/body.py:37` |  |
| `FIRECRAWL_API_KEY` | E+C | E+C | E+C | · | E | E+C | E | E | `platform/mission-control/integrations/biotech/src/biotech_mission_adapters/adapters/infrastructure/web_research_runtime.py:502` |  |
| `FLY_TOKEN` | · | · | E+C | · | · | · | · | · | `biotech/biotech-knowledge-services/scripts/fly.sh:3` |  |
| `GH_TOKEN` | C | · | · | · | · | · | E+C | · | `platform/mission-control/src/mission_control/adapters/github/credentials.py:11` |  |
| `GITHUB_API_URL` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/scripts/dev/probe-entity-metrics.mjs:88` |  |
| `GITHUB_TOKEN` | C | · | · | · | · | · | E+C | · | `platform/mission-control/scripts/aieng_stagegraph.py:63` |  |
| `GITHUB_USERNAME` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/scripts/dev/probe-entity-metrics.mjs:18` |  |
| `GITKRAKEN_TOKEN` | · | · | E | · | · | · | · | · | none found |  |
| `GOOGLE_API_KEY` | · | · | · | · | E | · | · | · | none found |  |
| `GOOGLE_CLOUD_PROJECT` | · | · | · | · | E | · | · | · | none found |  |
| `GRAPHQL_API_KEY` | · | · | E+C | · | · | · | · | · | `biotech/biotech-knowledge-services/apps/graphql-api/bench/common.ts:128` |  |
| `HERENOW_API_KEY` | · | · | · | · | · | · | · | E | none found |  |
| `HUMANUPGRADE_RESEARCH_REPORTS_BUCKET` | E | · | E | · | · | · | · | · | none found |  |
| `INTERFAZE_API_KEY` | · | E+C | · | · | · | · | · | · | `platform/knowledge-services/apps/worker/src/verification-structured-extraction-runtime.ts:84` |  |
| `JEV_API_KEY` | E | E+C | E | · | · | · | · | · | `platform/knowledge-services/apps/jev/src/index.ts:29` |  |
| `KNOWLEDGE_API_IDENTITIES` | · | E+C | · | · | · | · | · | E | `platform/knowledge-services/apps/api/src/index.ts:44` |  |
| `KNOWLEDGE_API_TOKEN` | · | E+C | · | · | · | · | · | E | `platform/knowledge-services/apps/cli/src/benchmark-capture.ts:190` |  |
| `KNOWLEDGE_API_URL` | · | E+C | · | · | · | · | · | E | `platform/knowledge-services/apps/api/src/index.ts:39` |  |
| `KNOWLEDGE_PERSISTENCE_MODE` | · | E+C | · | · | · | · | · | E | `platform/knowledge-services/packages/host/src/server/worker.ts:31` |  |
| `LANGSMITH_API_KEY` | E+C | · | E | · | · | · | · | · | `platform/mission-control/scripts/sprint_oc_runtime_env.py:1033` |  |
| `LANGSMITH_ENDPOINT` | E+C | · | E | · | · | · | · | · | `platform/mission-control/scripts/sprint_oc_runtime_env.py:168` |  |
| `LANGSMITH_HIDE_INPUTS` | E+C | · | E | · | · | · | · | · | `platform/mission-control/src/mission_control/adapters/agent_server/health.py:40` |  |
| `LANGSMITH_HIDE_OUTPUTS` | E+C | · | E | · | · | · | · | · | `platform/mission-control/src/mission_control/adapters/agent_server/health.py:40` |  |
| `LANGSMITH_PROJECT` | E+C | · | E | · | · | · | · | · | `platform/mission-control/deployments/cloud_runtime/plan.py:25` |  |
| `LANGSMITH_TRACING` | E+C | C | E | · | · | · | · | · | `platform/mission-control/deployments/cloud_runtime/plan.py:27` |  |
| `LINEAR_API_KEY` | E+C | · | E | · | · | · | · | · | `platform/mission-control/docs/specs/archive/fast-track-2026-10/linear_note.py:9` |  |
| `MC_GITHUB_APP_ID` | E+C | · | · | · | · | · | · | · | `platform/mission-control/src/mission_control/adapters/github/credentials.py:7` |  |
| `MC_GITHUB_APP_INSTALLATION_ID` | E+C | · | · | · | · | · | · | · | `platform/mission-control/src/mission_control/adapters/github/credentials.py:7` |  |
| `MC_GITHUB_APP_PRIVATE_KEY_PATH` | E+C | · | · | · | · | · | · | · | `platform/mission-control/src/mission_control/adapters/github/credentials.py:8` |  |
| `MC_GITHUB_CLIENT_ID` | E | · | · | · | · | · | · | · | none found |  |
| `MC_GITHUB_CLIENT_SECRET` | E | · | · | · | · | · | · | · | none found |  |
| `MEM0_API_KEY` | E | · | E | · | · | · | · | · | none found |  |
| `MONGODB_URI` | E | · | E | · | · | · | · | · | none found | registry silent; MongoDB host (unregistered) |
| `MONGO_URI` | E | · | E | · | E | · | · | · | none found | registry silent; MongoDB host (unregistered) |
| `NEO4J_AURA_INSTANCE_ID` | E | · | E | · | · | · | · | · | none found | MC/BKS: biotech-graph (DPC:31,35) |
| `NEO4J_AURA_INSTANCE_NAME` | E | · | E | · | · | · | · | · | none found |  |
| `NEO4J_AURA_MCP` | · | E | · | · | E | E | E | E | none found | registry silent; host observed = aieng-graph 4773dc72 |
| `NEO4J_AURA_PASSWORD` | E+C | E | E+C | · | E | E | E | E | `platform/mission-control/integrations/biotech/src/biotech_mission_adapters/adapters/infrastructure/neo4j.py:18` | MC/BKS: biotech-graph (DPC:31); aiengineer/* and KS: aieng-graph (DPC:37) |
| `NEO4J_AURA_QUERY_API` | E | · | E | · | · | · | · | · | none found | MC/BKS: UNKNOWN Aura 9c6755c0 (DPC:33) |
| `NEO4J_AURA_URI` | C | E | · | · | E | E | E | E | `platform/mission-control/deployments/biotech/graph.toml:16` | aiengineer/* and KS: aieng-graph (DPC:37,38) |
| `NEO4J_AURA_USERNAME` | E+C | E | E+C | · | E | E | E | E | `platform/mission-control/integrations/biotech/src/biotech_mission_adapters/adapters/infrastructure/neo4j.py:18` | MC/BKS: biotech-graph (DPC:31); aiengineer/* and KS: aieng-graph (DPC:37) |
| `NEO4J_DATABASE` | C | · | x+C | · | E | · | · | · | `platform/mission-control/tests/fixtures/qualia_stagegraph.py:335` |  |
| `NEO4J_LOCAL_DBNAME` | · | · | · | · | E | · | · | · | none found |  |
| `NEO4J_LOCAL_PASSWORD` | · | · | · | · | E | · | · | · | none found |  |
| `NEO4J_LOCAL_URI` | · | · | · | · | E | · | · | · | none found |  |
| `NEO4J_LOCAL_USER` | · | · | · | · | E | · | · | · | none found |  |
| `NEO4J_PASSWORD` | C | · | x+C | · | E | · | · | · | `platform/mission-control/scripts/sprint_oc_runtime_env.py:807` |  |
| `NEO4J_QUERY_API_URL` | · | E | · | · | E | E | E | E | none found | registry silent; host observed = aieng-graph 4773dc72 |
| `NEO4J_URI` | E+C | C | E+C | · | E | · | · | · | `platform/mission-control/integrations/biotech/src/biotech_mission_adapters/adapters/infrastructure/neo4j.py:18` | MC/BKS: biotech-graph (DPC:31,35); DASH: observed UNKNOWN e40f2c21 (DPC:18-19) |
| `NEO4J_USERNAME` | C | · | x+C | · | E | · | · | · | `platform/mission-control/scripts/sprint_oc_runtime_env.py:806` |  |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | E | · | E | · | · | · | · | · | none found |  |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | · | E | · | · | E | E | E | E | none found |  |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | · | E | · | · | E | E | E | E | none found |  |
| `NEXT_PUBLIC_SUPABASE_URL` | · | E | · | · | E | E | E | E | none found | registry silent; host observed = aieng-db |
| `NODE_ENV` | E | x+C | E+C | · | C | · | · | · | `platform/knowledge-services/apps/api/src/index.ts:39` |  |
| `OPENAI_API_KEY` | E+C | C | E+C | C | E | · | · | · | `platform/mission-control/.agents/skills/coding-cli-jobs/scripts/agentjob.py:45` | model vendor (DPC:34) |
| `OPENAI_HUMAN_UPGRADE_VECTOR_STORE_ID` | E | · | E | · | · | · | · | · | none found |  |
| `OTHER_OPENAI_API_KEY` | E | · | · | · | · | · | · | · | none found |  |
| `OVERTON77_GITHUB_PAT` | · | · | · | · | · | E | · | · | none found |  |
| `PAT` | · | E | · | · | · | · | · | E | none found |  |
| `POSTGRES_DATABASE` | · | E | · | · | E | E | E | E | none found |  |
| `POSTGRES_HOST` | · | E | · | · | E | E | E | E | none found | registry silent; host observed = aieng-db |
| `POSTGRES_PASSWORD` | C | E | · | · | E | E | E | E | `platform/mission-control/packages/mission-control-db-contract/scripts/disposable.py:49` |  |
| `POSTGRES_PRISMA_URL` | · | E | · | · | E+C | E | E | E | `aiengineer/agents_dashboard/src/features/research-capability/server/postgres.ts:19` | aiengineer/* and KS: aieng-db (DPC:36,38) |
| `POSTGRES_URL` | C | E+C | · | C | E+C | E+C | E+C | E | `platform/mission-control/scripts/report_source_proof.py:45` | aiengineer/* and KS: aieng-db (DPC:36,38) |
| `POSTGRES_URL_NON_POOLING` | C | E | · | C | E+C | E+C | E+C | E | `platform/mission-control/scripts/sprint_oc_runtime_env.py:107` | aiengineer/* and KS: aieng-db (DPC:36,38) |
| `POSTGRES_USER` | C | E | · | · | E | E | E | E | `platform/mission-control/infra/temporal/scripts/setup-postgres.sh:6` |  |
| `PRE_RESEARCH_CONTROLLER_STAGE_WAIT_MS` | · | · | · | · | · | · | E | · | none found |  |
| `PRE_RESEARCH_LOCAL_EVE_START` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/agent/channels/eve.ts:5` |  |
| `PRE_RESEARCH_MIN_FREE_GB` | · | · | · | · | · | · | E | · | none found |  |
| `PRE_RESEARCH_SCHEDULE_ENABLED` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/controller/scheduled-pre-research.ts:134` |  |
| `PRE_RESEARCH_SCHEDULE_INVOCATION_BUDGET_MS` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/controller/scheduled-pre-research.ts:27` |  |
| `PRE_RESEARCH_SCHEDULE_RETRY_COOLDOWN_MINUTES` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/controller/pre-research-pipeline.ts:93` |  |
| `PRE_RESEARCH_TRANSCRIPT_CHUNK_CHARACTERS` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/agent/lib/video-context.ts:88` |  |
| `PRODUCTION_API_KEY` | E | · | E | · | · | · | · | · | none found |  |
| `PROJECT_ID` | · | · | · | · | E | · | · | · | none found |  |
| `RECOMMENDATION_DRAIN_SECRET` | · | · | · | · | E | · | · | · | none found |  |
| `REDIS_PORT` | E+C | · | E | · | · | · | · | · | `platform/mission-control/docker-compose.yml:37` |  |
| `REDIS_URL` | E+C | · | E | · | · | · | · | · | `platform/mission-control/scripts/sprint_oc_runtime_env.py:1004` | local 127.0.0.1:16379 (DPC:22) |
| `REDIS_URL_UPSTASH` | E | · | E | · | · | · | · | · | none found |  |
| `RUNWAYML_API_SECRET` | E | · | · | · | · | · | · | · | none found |  |
| `SECOND_ANTHROPIC_API_KEY` | E+C | · | · | · | · | · | · | · | `platform/mission-control/scripts/sprint_oc_runtime_env.py:1032` | model vendor (DPC:34) |
| `SEMANTIC_API_KEY` | E | E | E+C | · | · | · | · | E | `biotech/biotech-knowledge-services/schema/pinned/release/tooling/action-space.yaml:3438` |  |
| `SMITHERY_API_KEY` | · | · | · | · | E | · | · | · | none found |  |
| `SMITHERY_PROFILE` | · | · | · | · | E | · | · | · | none found |  |
| `SUPABASE_ACCOUNT_PASSWORD` | E | · | · | · | · | · | · | · | none found |  |
| `SUPABASE_ANON_KEY` | · | E | · | · | E | E | E | E | none found |  |
| `SUPABASE_API_KEY` | · | E | · | · | E | E | E | E | none found |  |
| `SUPABASE_JWKS_URL` | E | · | E+C | · | · | · | · | · | `biotech/biotech-knowledge-services/apps/product-bff/src/config.ts:44` | MC/BKS: biotech-db (DPC:30,35) |
| `SUPABASE_JWT_SECRET` | C | E | · | · | E | E | E | E | `platform/mission-control/scripts/sprint_oc_mint_bundle_tokens.py:14` | aiengineer/* and KS: aieng-db (DPC:36,38) |
| `SUPABASE_MCP_ACCESS_TOKEN` | E | · | · | · | · | · | · | · | none found |  |
| `SUPABASE_PASSWORD` | E | · | E | · | · | · | · | · | none found |  |
| `SUPABASE_PUBLISHABLE_KEY` | E+C | E | E | · | E | E | E | E | `platform/mission-control/scripts/sprint_oc_runtime_env.py:137` | MC/BKS: biotech-db (DPC:30); aiengineer/* and KS: aieng-db (DPC:36,38) |
| `SUPABASE_SECRET_KEY` | E+C | E+C | E+C | · | E | E+C | E | E | `platform/mission-control/scripts/sprint_oc_runtime_env.py:138` | MC/BKS: biotech-db (DPC:30); aiengineer/* and KS: aieng-db (DPC:36,38) |
| `SUPABASE_SERVICE_ROLE_KEY` | C | E+C | · | · | E+C | E+C | E+C | E | `platform/mission-control/tests/unit/harness/test_local_lane_child_environments.py:95` | aiengineer/* and KS: aieng-db (DPC:36,38) |
| `SUPABASE_URL` | E+C | E+C | E+C | · | E+C | E+C | E+C | E | `platform/mission-control/scripts/register_supabase_skill_bundle.py:3` | MC/BKS: biotech-db (DPC:30); aiengineer/* and KS: aieng-db (DPC:36,38) |
| `TAVILY_API_KEY` | E+C | E+C | E+C | · | E | E+C | E+C | E | `platform/mission-control/experiments/dynamic_research_swarm/config.py:25` |  |
| `TEMPORAL_ADDRESS` | E+C | · | E | · | · | · | · | · | `platform/mission-control/deployments/cloud_runtime/plan.py:23` | local 7233 (DPC:22) |
| `TEMPORAL_CLOUD_ADDRESS` | E | · | · | · | · | · | · | · | none found |  |
| `TEMPORAL_CLOUD_API_KEY` | E+C | E | E | · | · | · | · | E | `platform/mission-control/deployments/cloud_runtime/plan.py:103` |  |
| `TEMPORAL_CLOUD_API_SECOND_KEY` | E | · | · | · | · | · | · | · | none found |  |
| `TEMPORAL_CLOUD_NAMESPACE` | E | · | · | · | · | · | · | · | none found |  |
| `TEMPORAL_CLOUD_NAMESPACE_PROD` | E | · | · | · | · | · | · | · | none found |  |
| `TEMPORAL_NAMESPACE` | E+C | · | E | · | · | · | · | · | `platform/mission-control/deployments/cloud_runtime/plan.py:24` |  |
| `TEMPORAL_TASK_QUEUE` | E+C | · | E | · | · | · | · | · | `platform/mission-control/scripts/offline_operator_stack.py:22` |  |
| `TOY_AGENT_SERVER_URL` | E | · | E | · | · | · | · | · | none found | local 2024 (ENVIRONMENT-AND-DATABASES.md:26) |
| `TOY_MODEL` | E | · | E | · | · | · | · | · | none found |  |
| `TOY_STEP_DELAY_SECONDS` | E | · | E | · | · | · | · | · | none found |  |
| `UNSTRUCTURED_API_KEY` | · | E+C | · | · | · | · | · | · | `platform/knowledge-services/packages/host/src/server/worker.ts:190` |  |
| `UNSTRUCTURED_URL` | · | E | · | · | · | · | · | · | none found |  |
| `UPSTASH_API_KEY` | E | · | E | · | · | · | · | · | none found |  |
| `UPSTASH_REDIS_REST_TOKEN` | E | · | E | · | · | · | · | · | none found |  |
| `UPSTASH_REDIS_REST_URL` | E | · | E | · | · | · | · | · | none found |  |
| `UPSTASH_REDIS_URL` | E | · | · | · | · | · | · | · | none found |  |
| `UPSTASH_VECTOR_REST_TOKEN` | E | · | E | · | · | · | · | · | none found |  |
| `UPSTASH_VECTOR_REST_URL` | E | · | E | · | · | · | · | · | none found |  |
| `VERCEL_OIDC_TOKEN` | · | C | · | · | E | · | E+C | · | `platform/knowledge-services/packages/host/src/server/knowledge.ts:47` |  |
| `VERCEL_TOKEN` | · | · | · | · | · | · | · | E | none found |  |
| `WEAVIATE_API_KEY` | · | · | · | · | E | · | · | · | none found |  |
| `WEAVIATE_URL` | · | · | · | · | E | · | · | · | none found |  |
| `WORKER_ID` | · | E+C | · | · | · | · | · | E | `platform/knowledge-services/packages/host/src/server/worker.ts:239` |  |
| `WORKER_TENANT_ID` | · | E+C | · | · | · | · | · | E | `platform/knowledge-services/apps/worker/src/process-restart-fixture.ts:5` |  |
| `XAI_API_KEY` | · | · | · | · | · | · | E+C | · | `aiengineer/research_starter_pre_research_agent/scripts/dev/probe-entity-metrics.mjs:310` |  |
| `YOUTUBE_API_KEY` | · | · | · | · | · | · | E | · | none found |  |

**Read in code, absent from that repo's `.env` and `.env.example`** (infrastructure-bearing
subset; the full lists are 150 MC, 127 KS, 88 BKS names, most being test or proof switches):

- MC: `MC_INGRESS_DSN`, `MC_RESTART_RUNTIME_DSN`, `MC_RESTART_WRITER_DSN`, `MISSION_CONTROL_TEST_ADMIN_DSN`, `KNOWLEDGE_DB_CONTRACT_ADMIN_DSN`, `AIENG_FIXTURE_DATABASE_URL`, `WI23_TEST_CUSTODY_DSN`, `MCDB_UNIT_URL`, `MC_TEMPORAL_TEST_ADDRESS`, `TEMPORAL_TARGET`, `GITHUB_TOKEN`, `GH_TOKEN`, `CONTEXT7_API_KEY`, `MISSION_CONTROL_DEPLOYMENT_FILE`, `MANIFEST_LAUNCH_BINDINGS_PATH`, `MISSION_CONTROL_AUTH_PROFILES_PATH`, `BELL_LABS_AGENT_AUTH_PRIVATE_KEY`, `MC_TEST_S3_*`.
- KS: `NEO4J_URI` (KS `.env` has only `NEO4J_AURA_URI`), `KNOWLEDGE_DB_URL`, `KS_TEST_DATABASE_URL`, `KS_TEST_SUPABASE_URL`, `KS_TEST_SUPABASE_SECRET_KEY`, `KNOWLEDGE_DB_CONTRACT_ADMIN_DSN`, `AIENG_FIXTURE_DATABASE_URL`, `WI05_{ADMIN,FENCE,KS,OUTBOX}_DSN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MISSION_CONTROL_API_URL`, `MISSION_CONTROL_API_TOKEN`, `KS_KNOWLEDGE_*`, `BIOTECH_GRAPH_T1_*`.
- BKS: `NEO4J_READER_{URI,USERNAME,PASSWORD}`, `NEO4J_USER`, `NEO4J_AURA_DATABASE_NAME`, `BKS_EXPORT_*`, `BKS_RESTORE_*`, `BKS_TEST_REMOTE_DSN`, `INSTALL_{SEAL,WIPE}_PG_ADMIN_DSN`, `INSTALL_WIPE_TARGET_DSN`, `MC_INSTALL_DISPOSABLE_DSN`, `SV11_PG_ADMIN_DSN`, `AURA_{CLIENT_ID,CLIENT_SECRET,ORG_ID,PROJECT_ID,AGENT_ID}`, `BFF_*`, `GRAPHQL_ACTOR_*`; plus 60 `BKS_*`/`GRAPHQL_*`/`NEO4J_{USERNAME,PASSWORD,DATABASE}` documented only in `.env.example`.
- AIDB: `POSTGRES_URL`, `POSTGRES_URL_NON_POOLING`, `INSTALL_*_DSN`, `MC_INSTALL_DISPOSABLE_DSN` (no `.env` at all).

**In `.env`, referenced nowhere in that repo's tracked code** (candidates to delete or move):
MC 47 (e.g. `NEO4J_AURA_QUERY_API`, `NEO4J_AURA_INSTANCE_ID`, `SUPABASE_JWKS_URL`,
`MONGODB_URI`, `MONGO_URI`, `UPSTASH_*`, `CLERK_SECRET_KEY`, `CURSOR_EMAIL`, `CURSOR_PASSWORD`,
`SUPABASE_ACCOUNT_PASSWORD`, `SUPABASE_PASSWORD`, `TEMPORAL_CLOUD_*`, `OTHER_OPENAI_API_KEY`);
KS 27 (all `NEO4J_AURA_*`, `POSTGRES_*` except `POSTGRES_URL`, `SUPABASE_JWT_SECRET`, …); BKS 57
(including every DB name: `DATABASE_DIRECT`, `DATABASE_URL`, `DIRECT_URL`, `APPLICATION_*`,
`REDIS_URL`, `TEMPORAL_*`, `LINEAR_API_KEY`); DASH 44 of 48; CLOUD 24 of 32; PRE 31 of 45.

## 4. Inconsistencies and naming problems (input to Q12)

1. **The same name means different planes.** `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `SUPABASE_PUBLISHABLE_KEY` mean biotech-db in MC and BKS (DPC:30,35; observed MC `.env:8`) and aieng-db in KS and `aiengineer/*` (DPC:36,38; observed KS `.env:26`). `NEO4J_AURA_USERNAME` and `NEO4J_AURA_PASSWORD` mean biotech-graph in MC and BKS (DPC:31) and aieng-graph everywhere else (DPC:37). `NEO4J_URI` means biotech-graph in MC and BKS, but observed unknown Aura `e40f2c21` in `agents_dashboard/.env:1`.
2. **`APPLICATION_DATABASE_DIRECT` is three planes.** It is local `127.0.0.1:55432` in the owner MC and BKS `.env` (DPC:32; MC `.env:91`). In the generated files it is biotech-db (`.scratch/sprint-oc/runtime/biotech/mission-control.env:47`) or aieng-db (`runtime/ai-engineer/mission-control.env:47`).
3. **biotech-db goes by at least eleven names:** `DATABASE_DIRECT`, `DATABASE_URL`, `DIRECT_URL`, `SUPABASE_URL` (owner `.env`); `KS_BIOTECH_COMPONENT_DSN`, `BKS_VERIFICATION_DSN` (`runtime/biotech/install.env:10,26`); `MC_BIOTECH_RUNTIME_DSN`, `MC_BIOTECH_FAMILY_WRITER_DSN`, `APPLICATION_FAMILY_WRITER_DATABASE_DIRECT`, `LANGGRAPH_CHECKPOINT_DATABASE_DIRECT` (`runtime/biotech/mission-control.env:48-51`); `MC_BIOTECH_MIGRATION_DATABASE_URL` (`deployments/biotech/target.toml:20`). The translation lives in one place, `sprint_oc_runtime_env.py:105-108`.
4. **aieng-db's source of truth is outside every repository.** `aiengineer/.env` holds `POSTGRES_URL_NON_POOLING` (the installer admin DSN, DPC:36). The generator reads it (`sprint_oc_runtime_env.py:91,107,739`), AIDB reads it from ambient env (`lib/db.mjs:9`), and the same names are copied into five more `aiengineer/*/.env` files and KS `.env`.
5. **Graph names fork.** biotech-graph uses `NEO4J_URI` plus `NEO4J_AURA_*` in `.env`, while BKS code also takes `NEO4J_USERNAME`/`NEO4J_PASSWORD` (`packages/kg-ops/src/neo4j.ts:27`), `NEO4J_READER_*` (`apps/graphql-api/src/config.ts:85-88`) and `BKS_EXPORT_*`. aieng-graph uses `NEO4J_AURA_URI` (not `NEO4J_URI`). The Query API is `NEO4J_AURA_QUERY_API` (MC and BKS, unknown `9c6755c0`) versus `NEO4J_QUERY_API_URL` (`aiengineer`, aieng-graph). KS code reads `NEO4J_URI`, which its `.env` lacks.
6. **BKS `.env` is an MC copy.** 57 of 72 names are unreferenced in BKS code. BKS's real configuration (`BKS_*`, `NEO4J_USERNAME`) is only in `.env.example` and the generated `bks-executor.env`.
7. **Duplicate definitions with different values.** In MC `.env`, `CURSOR_API_KEY` at `:29` and `:147` differ (`:147` equals KS's). `UPSTASH_REDIS_REST_URL` at `:51` and `:156` also differ. A first-match reader (the SPEC-01 §10 hook "reads `.env` with a pattern match") gets `:29`, while dotenv loaders keep the last. More duplicates, same-name only: `MEM0_API_KEY`, `TAVILY_API_KEY`, `UPSTASH_API_KEY`, `OPENAI_HUMAN_UPGRADE_VECTOR_STORE_ID` (MC and BKS); `DAYTONA_API_KEY` (BKS); `FIRECRAWL_API_KEY` (DASH).
8. **Role names drift for model keys.** The auditor is `SECOND_ANTHROPIC_API_KEY` in the owner `.env` and `MC_AUDITOR_ANTHROPIC_API_KEY` in generated files. The judge is `OPENAI_API_KEY` in the owner `.env` and `MC_JUDGE_OPENAI_API_KEY` in generated files (`sprint_oc_runtime_env.py:101-102,1027-1032`). DPC:103 proposes a third set (`ANTHROPIC_AUDITOR_API_KEY`, …).
9. **GitHub identity is split.** Remotes use the ssh alias `github-legacy` (Overton77), but the active `gh` account is `jbell-rusty-vantage`, so `gh pr create` would act as the wrong user. Token names: `GH_TOKEN`, `GITHUB_TOKEN`, `PAT`, `OVERTON77_GITHUB_PAT`, `MC_GITHUB_APP_*`.
10. **Ports disagree across docs.** The MC API is `18090` (WSL runbook:23), `8000`/`8001` (generator:95-96) and `8000` (Cursor env). DPC:22 names Agent Server `2024` only, but biotech uses `2025`.
11. **Cosmetic or typo names:** `BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN` versus `BELL_LABS_*` (`agent_server/runtime.env:9` vs `:4`); mixed case `AMAZON_Account`; lowercase `host`/`port`/`database` in `becoming-master-ai-engineer/.env:7-9`.
12. **Access asymmetry.** `supabase-biotech` uses a PAT header, while `supabase-aieng` relies on OAuth and is not authenticated in this session. `linear` is configured twice (MC `.mcp.json` and user `~/.claude.json`). The org-wide claude.ai Supabase connector exposes write tools (`apply_migration`, `execute_sql`), against the DPC:47-49 read-only rule.

**Shape a Q12 answer can adopt:** DPC §3 (DPC:97-104) already lists one prefix per plane
(`BIOTECH_DB_*`, `BIOTECH_GRAPH_*`, `AIENG_DB_*`, `AIENG_GRAPH_*`) plus role-named model keys. The
mapping work is small because `sprint_oc_runtime_env.py` is already the single translation point
(`:105-108`, `:792-807`, `:1027-1032`). Repoint its `owner(...)` sources to `.secrets/*.env`, and
the eleven biotech-db names above collapse to one source name per role (`ADMIN_DIRECT_DSN`,
`POOLER_DSN`, …), with the process-level names kept as generated outputs.

## 5. Unknown and stale entries

| Entry | Where (names only) | Status |
| --- | --- | --- |
| Aura `9c6755c0` | `NEO4J_AURA_QUERY_API`: MC `.env:81`, BKS `.env:80` | **Unknown, stale** (DPC:18,33). Referenced in no code in either repo. |
| Aura `e40f2c21` | `agents_dashboard/.env:1` `NEO4J_URI`, `:5` `AURA_INSTANCEID` | **Unknown, stale** (DPC:18-19). Not referenced in DASH code. |
| Supabase ref `vkymrpurgcmfawrvsknr` | `aiengineer/becoming-master-ai-engineer/.env:5,7,18,21` (`DIRECT_URL`, `host`, `SUPABASE_URL`, `SUPABASE_JWKS_URL`) | **Unregistered third Supabase project**; DPC does not mention it. |
| `.vercel/.env.production.local` DB names | `research_starter_pre_research_agent/.vercel/.env.production.local:3-7` | **Plane unknown**: values are 13 characters long (placeholders?) and match no known ref |
| MongoDB, Upstash Redis/Vector, Weaviate, Daytona, Clerk, Mem0, Runway | MC and BKS `.env` (`MONGODB_URI:3`, `MONGO_URI:30`, `UPSTASH_*`), DASH `.env` (`WEAVIATE_*`) | Named only as "other external services" (`ENVIRONMENT-AND-DATABASES.md:28`); mostly unreferenced in code |
| Temporal Cloud namespaces | MC `.env:121,129-131,140` `TEMPORAL_CLOUD_{ADDRESS,NAMESPACE,NAMESPACE_PROD,API_KEY,API_SECOND_KEY}` | Exists by name; identity not in any registry; unreferenced in MC code except `TEMPORAL_CLOUD_API_KEY` |
| Containers `mc-overnight-20261029-pg17` (`:55434`), `supabase_*_disposable-overnight-20261029` (`:54821`, `:54822` on all interfaces) | `docker ps` | **Running, unregistered**; leftover from 2026-10-29? |
| Owner app DB `127.0.0.1:55432` | `APPLICATION_*` in MC and BKS `.env` | Not running (no container), as on 2026-10-28 (`ENVIRONMENT-AND-DATABASES.md:24`) |
| `neo4j-biotech` MCP | DPC:77 | Planned, **absent** |
| `.secrets/` | DPC:94 | Proposed, **absent** |
| Claude Code cloud environment | SPEC-01 §10 | **None found**; not discoverable from disk |
| `aiengineer/ai-engineer-meta` remote | `git remote -v` empty, no commits | **Missing** (SPEC-01 §10 "to create") |
| `biotech/.git` | empty directory | Not a repository; misleading |
| `biotech/biotech-postgres-db-contract` | no `.git` | No repository (SPEC-01 §10 "to create") |
| Google OAuth client file | `biotech/client_secret_<id>.apps.googleusercontent.com.json` | Unregistered credential file in a non-git directory |
| Retained MC worktree | `.claude/worktrees/agent-a3ad8c12b136e094c` (`sprint-oc-selection-workspace`) | Retained; preserve |
