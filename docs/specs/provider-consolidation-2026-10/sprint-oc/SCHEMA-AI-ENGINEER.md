---
type: Navigation Guide
title: "AI Engineer application card: exact report, SQL knowledge and native receipt routes"
description: "Small schema entrypoints for Sprint OC and F3, separating common KS records from domain projections and historical orchestration IDs."
tags: [sprint, ai-engineer, schema, navigation]
date: 2026-10-27
---

# AI Engineer: one application slice

Start with [the port map](APPLICATION-PORTS.md). Application ID is `ai-engineer`; the configured shared
KS binding is `aiengineer-postgres`. MC's [target](../../../../deployments/ai-engineer/target.toml)
names `supabase-blue-ocean`. Source presence and target configuration do not prove today's installation.

## Read only the schema you need

Read the [domain guide](../../../../../../aiengineer/AGENTS.md), then
[AIDB AGENTS](../../../../../../aiengineer/ai-engineer-db-contract/AGENTS.md) before changes.
[workspace/START_HERE](../../../../../../aiengineer/ai-engineer-db-contract/workspace/START_HERE.md)
is the current generated catalog entry: contract **0.5.0**, migration head **20261025010200** at this audit.
Search → domain/task page → one relation/function page. Do not read the whole SQL/type dump or search index.

| Question | Minimal route in AIDB `workspace/` |
| --- | --- |
| Reports and their exact native projection | [research-v2](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/research-v2.md), then [report_v2_revision](../../../../../../aiengineer/ai-engineer-db-contract/workspace/relations/research/report_v2_revision.md), `report_v2_assertion`, `report_v2_ingestion` |
| Use admission for native ingestion | [use_admission](../../../../../../aiengineer/ai-engineer-db-contract/workspace/relations/research/use_admission.md), then the migration guards below |
| Operational ownership and historical IDs | [knowledge-service-runtime](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/knowledge-service-runtime.md), then [knowledge_service.operation](../../../../../../aiengineer/ai-engineer-db-contract/workspace/relations/knowledge_service/operation.md) |
| Entity/technical assertions and source evidence | [knowledge-records](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/knowledge-records.md), [evidence](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/evidence.md), [provenance](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/provenance.md) |
| F3 model/version/offering/benchmark and ranking | Search `relations.txt` for `model`, `benchmark`, `metric_observation`; then [ranking](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/ranking.md) and [retrieval](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/retrieval.md) |
| Later product/user/content readiness | [identity](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/identity.md), [content](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/content.md), [curriculum](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/curriculum.md), [API surface](../../../../../../aiengineer/ai-engineer-db-contract/workspace/domains/api-surface.md); discovery only, not proof that a learner app exists |

From `aiengineer/ai-engineer-db-contract`:

```powershell
rg -n 'report_v2|use_admission|knowledge_service.operation' workspace/search/index.json
rg -n 'model|benchmark|metric_observation|operation_receipt' workspace/relations.txt
rg -n 'report|receipt|mission|model|benchmark' workspace/queries/README.md
rg -n 'report_v2|use_admission|bound_effect_digest|verification_component_binding' supabase/migrations -g '20261024*.sql' -g '20261025*.sql'
```

Use `rg` results to select a bounded page. Named queries/native executor interfaces own access; these
commands are source navigation, not authorization to write tables. Migration SQL is authoritative;
generated cards and types are projections. Older `SCHEMA-SUMMARY.md`/`MIGRATION-RESULT.md` describe
0.3.0 and must not override the current catalog. Keep curated workspace guidance subordinate to current SQL.

## What actually connects to MC

MC is self-contained; there is no generic FK from `mission_control` into the domain. The shared KS
[protocol origin](../../../../../knowledge-services/packages/knowledge-operation-protocol/src/origin.ts)
carries installation/application/tenant plus mission/run/activation/operation/attempt/generation and
authenticated issuer/invocation identity. KS operational rows retain that attribution. MC retains exact
handles, digests, effect keys, receipts and content lineage; native projections bind admitted content.

Do not equate every `run_id` or `mission_id`: KS verification runs, MC runs and domain orchestration
records have different owners. In particular, `knowledge_service.operation.attempt_id/work_item_id`
refer to AIDB `orchestration.attempt/work_item`. The legacy
[verification ownership resolver](../../../../../knowledge-services/packages/application/src/verification/operations/verification-ownership.ts)
joins that domain orchestration ledger. These fields are not evidence of a direct MC mission FK.

The concrete native bridge lives in these AIDB migrations:

- [20261024010000_knowledge_component_binding](../../../../../../aiengineer/ai-engineer-db-contract/supabase/migrations/20261024010000_knowledge_component_binding.sql): consume installed common KS 2.x and record its binding; do not copy its DDL into AIDB.
- [20261024010100_research_report_v2_projection](../../../../../../aiengineer/ai-engineer-db-contract/supabase/migrations/20261024010100_research_report_v2_projection.sql): exact `(tenant, report, revision)` projection, assertion/ingestion links and `research.use_admission`; enforced checks against common authority, not cross-component FKs.
- Read subsequent migrations through current head for additional guards. `orchestration.operation_receipt` records required admission/use decision/bound effect; transactional guards prevent canonical writes without corresponding admission.

## Follow one report and one native effect

1. MC's live origin calls the application's shared KS host. Operational report registration/read uses
   the common `knowledge_verification` store and custody, via
   [service.ts](../../../../../knowledge-services/packages/host/src/knowledge-operation/service.ts) and
   [research binding](../../../../../knowledge-services/packages/bindings/aiengineer-postgres/src/research-binding.ts).
2. An exact operational report read returns body/ledger/manifest; MC validates and materializes them.
   It does not search entity tables or require a native projection merely to transfer that report.
3. If the obligation promises native ingestion, KS
   [ingestion apply port](../../../../../knowledge-services/packages/bindings/aiengineer-postgres/src/ingestion-apply.ts) (moved from the host by R5)
   invoke the AIDB ingestion executor. [Exact-use admission](../../../../../knowledge-services/packages/knowledge-db/src/ingestion/exact-use-admission.ts)
   and native transaction guards bind the intended normalized values, use decision and effect.
4. For entity context or promised readback, use the native query/entity route selected from the workspace.
   Retain exact returned refs/digests as inputs; SQL co-location does not permit a broad MC join or direct agent writer.
5. Lost protocol acknowledgment after native commit remains WI-05/RV-06 work. Recover the original
   effect and native result; do not mint a new write because the MC caller lacks a receipt.

For common KS tables, use [component migrations](../../../../../knowledge-services/packages/knowledge-db-contract/component/migrations):
`0001` origin/effect/verification foundation; `0002` reports/observations/custody; `0004` operations/assessments;
`0006` credential-use/protocol receipts. These are common KS authority, not AIDB-owned duplicated tables.

For F3, native model/benchmark commit and readback precede ranking. Existing read-only ranking grants
do not imply an autonomous writer. Follow [PROOFS §10](PROOFS.md#10-f3--model-ingestion-then-database-grounded-ranking-wi-2930)
for required schema fit and evaluation; broader product architecture remains later work.
