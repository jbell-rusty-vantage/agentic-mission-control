---
type: Agent Configuration
title: "Sprint V start here: repositories, databases and runtime state"
description: "Minimal navigation and verified topology distinctions for implementing the accepted Sprint V specification without confusing business, graph, checkpoint and scheduler stores."
tags: [mission-control, knowledge-services, sprint-v, navigation, persistence]
date: 2026-10-24
status: active
---

# Start here

For continuation after the 2026-10-25 checkpoint, read [NEXT-SESSION.md](NEXT-SESSION.md) first.
This page remains the topology/ownership map, not the latest implementation status.

1. Read [ANSWERS.md](../answer-sets/sprint-v/codex-gpt-6-2026-10-24/ANSWERS.md), then the
   [plan](../sessions/SPRINT-V-PLAN.md) and [team claims](TEAM-WORKSPACE.md). The owner accepted the packet.
2. Read the destination repository's AGENTS.md and one relevant knowledge concept. Use the table below
   to choose the owner before searching. Run Git/dependency commands there, not at BellLabs root.
3. [WORK-ITEMS.json](WORK-ITEMS.json) is the dependency frontier; [design](../specs/SPRINT-V-DESIGN.md) defines
   the contracts. Existing data/history is disposable. Dirty source work from other sessions is not.
4. Real research/ingestion/retrieval experiments remain closed until all four workflows, output/context
   transfer and Deep Agents are complete. Use disposable engineering fixtures before that gate.

## Database map

This is source/configuration evidence checked 2026-10-24, **not a fresh live-deployment probe**. A schema
is a namespace within a database; a Supabase project, Neo4j database and Fly service are different things.
Paths below are BellLabs-relative. The two Supabase targets both call their database `postgres`.

| What | Where / authority | Smallest useful entrypoint |
| --- | --- | --- |
| AI Engineer Mission Control | AI Engineer Supabase project; `mission_control` and `mission_control_search`. Common MC SQL has its own owner/release. | MC `deployments/ai-engineer/target.toml` + `release.lock.json`; `packages/mission-control-db-contract/README.md` |
| AI Engineer knowledge graph, assertions, reports | Same declared AI Engineer Supabase project, separate domain schemas such as `knowledge`, `research`, `corpus`, `evidence`, `orchestration`. AIDB owns domain SQL/types. | `aiengineer/ai-engineer-db-contract/README.md` → `workspace/START_HERE.md`; KS `knowledge/schema-read-and-ingestion.md` |
| Biotech Mission Control | Biotech Supabase project, separate from AI Engineer; same common MC schema names. | MC `deployments/biotech/target.toml` + `release.lock.json`; avoid the thin consumer README's stale release-status paragraph |
| Shared KS operational verification records | Existing binding is AI Engineer PostgreSQL. Sprint V creates one common component installed in each app's PostgreSQL; this is **target work**, not already-deployed Biotech SQL. | KS `knowledge/verification-and-admission.md`; plan §3; K09/SV-03 |
| Biotech canonical knowledge | Neo4j Aura, database `neo4j`. Versioned Neo4j GraphQL SDL describes it; SDL is not the database. BKS is now schema author. | BKS `docs/NAVIGATION.md` → `schema/pinned/PIN.json` and `schema/pinned/release/sdl/assembled.graphql`; author next release in `schema/source/` |
| Biotech service hosting | Fly runs native executor `bks-biotech-executor` and consumer read API `bks-biotech-graphql-api`. Those services connect to Aura; Fly is not the graph store. | BKS `docs/deployment/executor.md`, `docs/deployment/graphql-api.md`; `docs/plans/schema-v2-service-release/RELEASE-MANIFEST.md` S9 records dated deployment proof |
| Standalone Deep Agents checkpoints/store | PostgreSQL schema `mission_control_runtime`. `LANGGRAPH_CHECKPOINT_DATABASE_DIRECT` overrides the application DSN; otherwise it uses application PostgreSQL. Could therefore be local or remote, including app Supabase in a separate schema. | MC `src/mission_control/bootstrap/settings.py` property `langgraph_checkpoint_dsn`; `adapters/deep_agents/persistence.py`; topology note linked below |
| Agent Server native threads/checkpoints | Separate from the standalone saver. Current topology note describes local `langgraph dev` in-memory/pickle edition. Durable PostgreSQL edition requires a separate app-bound database; `mission_control_agent_server` shared-schema workaround is unsupported. | MC `docs/adr/0017-agent-server-runtime-persistence-separate-database.md`; `packages/mission-control-db-contract/runtime/AGENT_SERVER_TOPOLOGY.md` |
| Temporal workflow history | Separate Temporal persistence. Local Compose has its own PostgreSQL service/volume; cloud target is configurable. A Temporal namespace is not a PostgreSQL schema. | MC `docker-compose.temporal.yml`; `bootstrap/settings.py` Temporal settings |
| Large immutable artifact bytes | AI report bytes: Supabase Storage `research-reports`. BKS executor currently configured for Fly volume `/data/runs`; Supabase `knowledge-artifacts` custody is an adapter/target, not proven default deployment. | KS report service/custody; BKS `apps/executor/fly.toml` and `packages/kg-ops/src/admission/custody-supabase.ts` |

**Deep Agents is the ambiguous phrase:** the parent LangGraph saver, Agent Server's own persistence and
Temporal history are three stores. A local worker process may connect to remote PostgreSQL. Never infer
database placement from where Python runs. The older general-spec private-schema assumption for Agent
Server is superseded by ADR 0017; it must not be confused with the still-supported standalone saver.

## Follow only the relevant route

| Work | Read first |
| --- | --- |
| MC ports, origin, submission | [MC guide](../../../../../AGENTS.md) → [knowledge-services concept](../../../../knowledge/knowledge-services.md) → design M01..M06 |
| KS algorithms/reports/admission | [KS guide](../../../../../../knowledge-services/AGENTS.md) → [verification concept](../../../../../../knowledge-services/knowledge/verification-and-admission.md) → K01..K09 |
| AI SQL and generated types | [AIDB guide](../../../../../../../aiengineer/ai-engineer-db-contract/AGENTS.md) → [schema workspace](../../../../../../../aiengineer/ai-engineer-db-contract/workspace/START_HERE.md) |
| Biotech SDL/native API/Fly | [BKS guide](../../../../../../../biotech/biotech-knowledge-services/AGENTS.md) → [navigation](../../../../../../../biotech/biotech-knowledge-services/docs/NAVIGATION.md) |
| Saver versus Agent Server | [topology note](../../../provider-consolidation-2026-10/providers/deep_agents/TOPOLOGY-NOTE.md) → ADR 0017 → actual launch settings |

## Before touching a database

Resolve the intended **application + environment + database role + schema**, then the owning installer.
Do not dump environment files, settings objects, raw DSNs, `docker inspect` or `docker compose config`.
Container names/status via `docker compose ps` are safe navigation. If live placement is needed, use an
in-process diagnostic in the actual launch environment that emits only role, host, port, database,
schema and local/remote classification, never credentials. Settings loaded in a new shell do not prove
what an already-running service uses. Apply/reset only the explicitly resolved intended test target.

Historical Fly/Aura evidence is dated 2026-10-12 and reports incomplete soak qualification; target files
and component locks do not establish today's deployed version. Recheck live status only when the work
requires that claim. The accepted clean refactor does not itself choose a new physical hosting topology.
