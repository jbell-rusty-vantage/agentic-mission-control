---
type: Concept
category: boundaries
title: Applications served by Mission Control
description: How AI Engineer and Biotech are placed against Mission Control (one service, two Application Bindings, the common schema inside each application's own Supabase PostgreSQL), which data plane and Knowledge Services binding each uses, where each application's schema authority lives, and pointer lines to the Knowledge Services, AIDB and BKS repositories for cross-repository navigation.
tags: [mission-control, applications, ai-engineer, biotech, knowledge-services, navigation]
aliases: [AI Engineer placement, Biotech placement, application binding, data planes, cross-repo pointers]
questions:
  - Which application database and graph does a mission use?
  - Where does each application's schema and knowledge code live?
  - How do I find Knowledge Services, AIDB or BKS code from Mission Control?
  - Why does an AI Engineer mission never touch the Biotech graph?
updated: 2026-11-01
---

# Applications served by Mission Control

One shared service serves two applications through immutable, operator-managed **Application
Bindings** (ADR-0002); the identical common schema is installed into each application's existing
Supabase PostgreSQL, with private Storage buckets in the same project. Resource identity is always
(installation, application, tenant, resource), so a token for one application never acquires the
other's authority. What may differ per application is data, not code
([application profile](application-profile.md)); the kernel names no application
(`tests/architecture/test_package_boundaries.py:475`).

## Placement

| | AI Engineer (`ai-engineer`) | Biotech (`biotech`) |
| --- | --- | --- |
| Mission Control data plane | **aieng-db**: Supabase `supabase-blue-ocean`; `mission_control` schema beside KS `knowledge_verification` and the AIDB domain schemas | **biotech-db**: Supabase `biotech-research-ingestion`; `mission_control`, `mission_control_search`, KS `knowledge_verification`; no domain tables |
| Domain knowledge store | PostgreSQL (AIDB schemas, same database) | Neo4j Aura graph **biotech-graph** (BKS schema `biotech-schema-v2.2.0`) |
| KS binding | `aiengineer-postgres` (apply: storage class relational, single transaction) | `biotech-graph` (graph, marker plus outbox) |
| MC installation and profile | `deployments/ai-engineer/{target,application,models}.toml`, `release.lock.json` | `deployments/biotech/{target,application,graph,models}.toml`, `release.lock.json` |
| Entity writes | AIDB, behind KS apply | BKS, behind KS apply |

The AI Engineer graph (`aieng-graph`, Aura `4773dc72`) is not a Mission Control target and is never
written; `deployments/biotech/graph.toml` refuses it. Identities, credential names and MCP servers per
plane: `BellLabs/docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` (data planes and credentials). Both
Supabase projects are currently disposable targets (Sprint OC rule). Standalone Deep Agents checkpoints
use `mission_control_runtime` in the application database (or a resolved saver DSN); Agent Server and
Temporal persistence are separate stores ([persistence](persistence.md), ADR-0017).

## Where each side lives (pointer lines)

- **Knowledge Services (KS)**: `platform/knowledge-services`. Shared operations, K01 protocol,
  `knowledge_verification` component (2.5.0 at W0), bindings under `packages/bindings/`. Start at its
  `AGENTS.md`; the Mission Control side is [knowledge services](knowledge-services.md).
- **AI Engineer database contract (AIDB)**: `aiengineer/ai-engineer-db-contract`. Sole schema and
  migration authority for the AI Engineer entity chain (contract 0.5.0, head `20261025010200` at W0);
  `scripts/install-ai-engineer.mjs` is the release path. Mission Control never invokes its migrations.
- **Biotech Knowledge Services (BKS)**: `biotech/biotech-knowledge-services`. Schema author and pin
  (`schema/pinned/PIN.json`), read and ingest executor, GraphQL API; `scripts/install-biotech.mjs`.
  `biotech/biotech-postgres-db-contract` is only the Biotech deployment wrapper around `mission-db`.
- **Application ports and cards**: [APPLICATION-PORTS](../specs/provider-consolidation-2026-10/sprint-oc/APPLICATION-PORTS.md),
  [AI Engineer card](../specs/provider-consolidation-2026-10/sprint-oc/SCHEMA-AI-ENGINEER.md),
  [Biotech card](../specs/provider-consolidation-2026-10/sprint-oc/SCHEMA-BIOTECH.md) separate operational
  reports, native knowledge and persistence without loading entire schemas.
- **How the common release reaches each application**: [database component](database-component.md).

## Cross-repository navigation

The pointer lines above stand in for a workspace-wide search: until the navigation program (S1) indexes
sibling repositories, an agent reading Mission Control concepts reaches KS, AIDB and BKS only through these
lines and each repository's own `AGENTS.md`. `search --workspace` is specified, not built.

## Boundaries that hold

- Co-location in one PostgreSQL database does not make Mission Control state, KS operational reports and
  AIDB domain tables one authority; there are no foreign keys between them. Mission Control records who
  ran and what settled; KS owns reports, verification and permitted use; the application owns entities.
- The application goals (AI Engineer course platform, Biotech knowledge) are carried by their own
  repositories; see [goals](goals.md#goal-applications-fed-by-missions).

Built / specified / goal: both bindings, profiles and installs on the disposable targets are implemented
and W0-released with recorded limitations ([qualification](qualification.md)); production per-invocation
Biotech authority and W1 qualification are not done; workspace search across repositories is specified.

## Citations

- Decisions: [ADR-0002](../adr/0002-one-service-two-applications-schema-per-app-database.md),
  [ADR-0003](../adr/0003-common-sql-owned-by-db-contract-package.md),
  [ADR-0009](../adr/0009-common-release-separate-app-authority.md),
  [ADR-0017](../adr/0017-agent-server-runtime-persistence-separate-database.md),
  [ADR-0059](../adr/0059-application-content-and-shared-knowledge-authority.md).
- Data: [AI Engineer target](../../deployments/ai-engineer/target.toml),
  [Biotech target](../../deployments/biotech/target.toml), [Biotech graph](../../deployments/biotech/graph.toml),
  [AI Engineer profile](../../deployments/ai-engineer/application.toml),
  [Biotech profile](../../deployments/biotech/application.toml).
- Sibling repositories (outside this repository): `../../../knowledge-services/AGENTS.md`,
  `../../../../aiengineer/ai-engineer-db-contract/AGENTS.md`,
  `../../../../biotech/biotech-knowledge-services/AGENTS.md`.
- Proof: [W0 release bundle](../specs/provider-consolidation-2026-10/sprint-oc/release/RELEASE-BUNDLE.md).
- Tests: [kernel names no application](../../tests/architecture/test_package_boundaries.py),
  [profile conformance](../../tests/conformance/applications/test_application_profiles.py).
