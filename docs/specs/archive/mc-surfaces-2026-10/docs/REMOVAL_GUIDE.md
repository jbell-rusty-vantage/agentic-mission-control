---
type: Removal Guide
title: Clean-break removal and relocation guide
description: "This guide covers the owner-authorized Mission Control organization cleanup. It distinguishes source removal from deleting data. No historical Mongo backfill, record purge, live destructive migration or old…"
tags: [mission-control, removal, evidence]
---
# Clean-break removal and relocation guide

This guide covers the owner-authorized Mission Control organization cleanup.
It distinguishes source removal from deleting data. No historical Mongo backfill,
record purge, live destructive migration or old endpoint/history compatibility is
required by this clean break. Existing user data remains preserved.

## Active replacements

### Sprint OC WI-08 (OVE-171): graph routes, release groups, Revisit Regions (2026-10-29)

Removed: the `depends_on`-only side path of `application/programs/stage_inputs.py` and the
lowering (a `from: <sibling>.<output>` binding is now its own dependency; the fast-track 01 golden
blueprint digest moved because `ingest` really receives `synthesize.claim_table`), and the
`dependent_stage(required=...)` keyword (an authored `required: false` binding is the only opt-out).
No migration. Additive only: the manifest JSON schemas `mc.mission_manifest.v1.json`/`v2.json` were
regenerated in place with new optional properties (`routes`, `revisits`, `release_groups`, `facts`)
and nothing removed or narrowed; blueprints gain digest-neutral `routes`, `revisit_regions`,
`graph_semantics`, `StageNode.facts`, `StageJoin.group`. Rollback hazard: a worker built before
WI-08 cannot decode a blueprint carrying those fields (`extra="forbid"`), so roll workers back only
after every run admitted with the `oc-graph-routes-v1` marker is terminal; manifests using the new
fields must not be submitted to an older API. Blueprints without the marker replay unchanged (the
Temporal patches `oc-wi08-stagegraph-revisit-region` and `oc-wi08-stagegraph-exhaustion-hold` are
reached only by marked blueprints). Seed `mc.catalog.artifact-schemas@1.0.1` is a successor; 1.0.0
is untouched and now frozen by digest in `generate_catalog_seeds.py`. Operator note: a run held on
`route-exhausted:<route>` or `revisit-exhausted:<region>` (visible in run inspection
`active_waits` and as a `blocked` inbox notice) resumes only through `cancel` or a revision (fork or
successor revision); satisfying the wait does not change the pinned evidence. Set-wait journal
events now carry `condition_id`/`condition_kind` (additive). Deferred: per-stage revisit caps and
region wall-clock/budget guards. Recovery: revert the WI-08 commits on `sprint-oc-wi08`
(`docs/knowledge/workflow-systems.md`).

### Sprint OC WI-22 (OVE-183): durable transition reactions (2026-10-28)

Nothing is removed; the change is additive. Migration
`scripts/release_170/0061_durable_transition_reactions.sql` adds three tables, five capture
triggers on the 0056-0058 output, assessment, fulfillment, delivery and settlement tables (each a
no-op while the run has no armed reaction of that kind) and `mc.reaction.dispatch` outbox rows; it is
not yet in a built release. Recovery: revert the WI-22 commits on `sprint-oc-wi22`
(`docs/knowledge/durable-reactions.md`).

### Sprint OC WI-17 (OVE-180): hook context contributions (2026-10-27)

Nothing is removed; behaviour changes are additive and fail closed:

| Changed | Now |
| --- | --- |
| A hook result's free-form effect on the workspace (none was supported; ADR-0026 had no staging) | `mc.hook_result.v1` `staged_candidates` / `operation_requests`, observation events only; the host installs or refuses (`docs/knowledge/hook-contributions.md`) |
| `HookInput` carried no host read | `reads` (`HostRead`) for declared `host_reads` scopes only; absent from stdin and its digest when none is declared |
| `ExactDeepAgentMaterializer._hook_dispatcher(binding, stack)` | `_hook_dispatcher(binding, stack, backend)`; a binding whose hooks declare `host_reads` or `stage` with no `hook_contributions` service composed refuses to prepare (`DeepAgentMaterializationError`) |
| Post-effect hook deny wording (ADR-0026 "deny is honoured on every lane") | a deny at an observation event is a finding appended to the kept result; only before-effect guards prevent an action (ADR-0062) |

Recovery: revert the WI-17 commits on `sprint-oc-wi17`; migration
`scripts/release_170/0060_hook_candidate_installs.sql` adds two new tables only and is not yet in a
built release.

### Sprint OC WI-04 (OVE-166): saved provider results and durable settlement (2026-10-27)

| Removed | Replacement |
| --- | --- |
| `DeepAgentRuntimeAdapter.execute` calling `KnowledgeLaneSupport.complete` after cognition and discarding its `FinalizationReport` (a `blocked` report still settled `completed`; a raise settled `runtime_failed`) | `execute` returns at once; the boundary saves the result (`invocation_settlement`, 0058) and runs `settle_invocation` -> `KnowledgeLaneSupport.settle` -> `KnowledgeToolset.settle_saved`; the typed outcome is recorded (`waiting` result + `SettlementWait`, or settlement) |
| Blind successful-cognition redispatch on retry when no result manifest existed (`_recover_or_dispatch` -> `_dispatch_and_settle`) | `_recover_or_dispatch` and `_cancel_or_settle` settle the saved record first; cognition is never dispatched again for a saved result |
| `submit_output` items limited to `handle`/`path` | Also `inline` (text, structured value) and `code_change` for named promises; host-computed digests |
| The post-turn stop-fence and usage checks before the result was saved (`_turn_fence`, `_validate_bound_usage` ahead of the save) | Saved first; `_settle_saved_checked` applies the fence and usage checks to the saved record |
| An unbounded settlement wait in one history | Configurable delay cap, effect deadline -> `in_doubt` incident, review alarms (`invocation_settlement_event`), continue-as-new carrying the wait |

`KnowledgeLaneSupport.complete` and `KnowledgeToolset.settle` remain for direct callers. Recovery:
reinstall disposable databases from the rebuilt release 1.7.0 (fingerprint
`sha256:38a6ced1f5f7a77fb19450d311ace616a58841f2c5df057d2533f2e5bededb91`, after the review added `invocation_settlement_event`; superseded when WI-03 and WI-17 were integrated by the 0056–0060 build `sha256:ee099c2994f6acc91aa5b91427c3ef1e5ff235abd4b00fc675e3b4193c3164ba`). No recorded Temporal
history carries a `waiting` result, so earlier histories replay unchanged; histories with a wait carry
the `oc-wi04-saved-settlement-wait` marker (continued runs also `oc-wi04-saved-settlement-continue-as-new`; the generic artifact workflow `oc-wi04-generic-artifact-settlement-wait`). Recorded nits: the migration's credential-key check is top-level only; identity columns are duplicated in the `record` document. The operator read surface for waits and events belongs to WI-19 (OVE-182). WI-02 family inputs stay optional (no production promotion
caller yet).

### Sprint OC WI-02 (OVE-164): one sealed transfer plan (2026-10-27)

| Removed | Replacement |
| --- | --- |
| `application/context/delivery.py` (`DeliveryPlanner`, `DeliveryTarget`, one repair then block) | `application/context/materialization.py` (`TransferMaterializer`; `ContextDeliveryBlocked` moved here); no fixed repair: each attempt appends a receipt |
| `application/context/representation.py` (`ReportRepresentation`) | placement rules in `domain/context/transfer.py` (`seal_plan`) |
| `adapters/postgres/knowledge/transfers.py` (`PostgresContextTransferStore`) | `adapters/postgres/context/transfer_plans.py` (`PostgresTransferPlanStore`) |
| `KnowledgeToolset.deliver_inputs`, `delivery`, `delivery_required`, `delivery_budget_bytes`, `InputDelivery` | the receiver's `transfer` selection on the operation request, realized by the lane |
| `CURRENT_KNOWLEDGE_INPUTS`; `KnowledgeLaneSupport.begin` returning inputs | `begin` returns the live invocation; `access_for` gives the plan's exact reads a host access |
| `OutputSubmissionStore.finalized_selections`, `FinalizedSelection`, `SubmissionService.finalized_selections` (run-wide selection) | none: inputs come only from exact admitted bindings |
| `context_transfer_plan`, `context_delivery_receipt`, `context_delivery_outbox` (0054/0055) | dropped by 0057; `transfer_plan`, `transfer_delivery_receipt`, `transfer_member_delivery` |
| port types `ContextTransferStore`, `TransferPlanCandidate/Record`, `DeliveryReceiptCandidate/Record` | `TransferPlanStore`, `SealedTransferPlan`, `DeliveryReceipt` |
| `knowledge.read` native contract `research-report-package/v1` (`{report, exact}` payload, v1 manifest) | `selected-report-read/v2` (`SelectedReportRead`) answered by `research-report-package.v2`; KS refuses v1 with `SCHEMA_UNSUPPORTED` |

Recovery: the removed modules are at `sprint-oc` `6d5b27ec`. Old M04 rows were experimental and are
not migrated.

Deferred (recorded, not built in WI-02):

- **S6 omissions inspection.** Plan omissions are in the sealed plan, the `/.mission/transfer.json`
  index and the prompt section; a focused public inspection projection is WI-19.
- **S7 application sources.** No `application_selector` resolver is composed in production (an
  application source refuses `APPLICATION_SELECTOR_UNRESOLVED`), and `exact_artifact` members
  re-check only custody bytes, not current artifact access; both wait for an application binding.
- **Member-insert guard scope.** `transfer_member_delivery` accepts a member only in the
  transaction that created its receipt (`receipt.created_at = now()`). It defends against late or
  buggy appends by the runtime, not against a hostile runtime role; binding to
  `pg_current_xact_id()` is a later hardening option.
- **S8 known regression for non-Deep-Agents lanes.** Provider and Cursor lane templates carry no
  `transfer` selection, so those lanes receive no transfer inputs (the removed run-wide report
  delivery reached only Deep Agents knowledge invocations anyway) until the provider sweep
  (OVE-203).

| Previous location or authority | Current replacement | Behavioral consequence |
| --- | --- | --- |
| app/ application package | src/mission_control/{contracts,domain,application,adapters,interfaces,bootstrap} | One import namespace; callers update imports rather than relying on aliases |
| app/api | src/mission_control/interfaces/http | Application-scoped authenticated transport |
| app/temporal | src/mission_control/adapters/temporal | Same governed runtime behavior under adapter ownership |
| app/application/*/postgres_* | src/mission_control/adapters/postgres | Concrete SQL separated from application logic |
| app/migrations | src/mission_control/adapters/postgres/migrations | Ordered SQL preserved and bundled; no applied checksum rewriting |
| app/server.py | src/mission_control/bootstrap/technical_api.py | Lower-level authoring/control/realtime proof facade; not primary public startup |
| mission_control.api, worker, preflight | mission_control.bootstrap.api, worker, preflight | Configured entrypoints live at the composition boundary |
| app/experiments and packaged qualification prototypes | experiments/ | Prototype code is outside the runtime wheel |
| Biotech schema/research implementation in kernel | integrations/biotech/src/biotech_mission_adapters | Optional application integration; no kernel imports of application code |
| Competing LangGraph configuration files | agent_server/langgraph.json | One canonical bounded-graph registration surface |
| Old BellLabs README and active Cursor authority | Root/scoped AGENTS.md and docs/knowledge | General architecture and actual implementation navigation |

The redundant `bootstrap/legacy_preflight.py` is removed. The optional technical
facade preserves tested lower-level contract/realtime surfaces using the same
handlers and engine; it is not an old application fallback or second scheduler.

The versioned [organization evidence](../../../../organization/README.md) survives a fresh
checkout. It includes the complete [initial file map](../../../../organization/file-map.json),
[initial import map](../../../../organization/module-map.json),
[experiment supplement](../../../../organization/experiment-relocation.json),
[Biotech extraction](../../../../organization/biotech-module-map.json) and
[adapter regrouping](../../../../organization/adapter-module-map.json). These record the
physical move; later removals/extraction can supersede an intermediate destination.
Consult the current source and sections below.

## Mongo implementation retirement

PostgreSQL replacements own immutable definitions/configuration, operation/family
bindings, asynchronous details, workspace/artifact metadata, candidate content and
snapshots. Transitional migrations 0027-0036 establish the initial storage chain.
Cleanup adds 0037 catalog projection processing, 0038 external discovery/inspection,
0039 sandbox snapshot contract slots and 0040 snapshot identity indexes. These were
exercised against isolated local PostgreSQL; no live application is implied.

The persistence slice's exact 54 retired paths are versioned in
[the retirement inventory](../../../../organization/mongo-removals.json); none remains at its
recorded location. They include Mongo family/operation/workspace/artifact/subordinate
repositories, Beanie document models, obsolete journal-backfill/routing code and
Mongo-only fixtures/proofs. The SQL migration history is preserved.

Shared deterministic fixture models and pure/InMemory contracts remain. Mongo
bootstrap functions were removed from the retained RRM009/RRM013 harness helpers;
removing a helper is not necessary when PostgreSQL acceptance still uses its models.

Standalone sandbox snapshot semantics briefly used a transitional PostgreSQL store.
That store is now retired (see [common component cutover](#common-component-cutover-2026-10-03)):
`adapters/postgres/workspaces/snapshot_repository.py` only raises
`SandboxSnapshotPersistenceRetired`.
PostgreSQL acceptance proofs replace the old Mongo-backed fixture entrypoints;
retired tests are not counted as passing tests. Final post-move test evidence is
recorded separately from the earlier baseline in the implementation status.

Removing source is not permission to drop collections, remove volumes or copy
historic records into the new schema. Archived data must not silently become a
supported new execution history.

## Application-specific extraction

The exact namespace map is the versioned
[Biotech extraction map](../../../../organization/biotech-module-map.json). The optional Biotech
integration retains bounded schema/research interfaces and
application-specific composition. Its source must not be imported by the general
kernel. This extraction is not the deferred broad KnowledgeServices generalization
audit and does not certify every domain adapter's persistence backend.

Nine retained domain scripts moved from root `scripts/` to the optional package's
`biotech_mission_adapters.bootstrap.scripts` modules, retaining their basenames:

- `promote_schema_grounding_surface`
- `provision_schema_deployment_evidence`
- `compare_schema_context_runs`
- `diagnose_schema_deployment_snapshot`
- `load_trudiagnostic_graph`
- `reconcile_zero_count_schema_artifacts`
- `run_web_research_coordinator_live`
- `stage_schema_grounding_live_inputs`
- `promote_reviewed_web_capabilities`

Install the optional development group with `uv sync --group biotech` (plain
`uv sync` excludes the domain dependencies). Then invoke the needed module as
`python -m biotech_mission_adapters.bootstrap.scripts.<name>`. Old root-script
aliases are not retained. Their Mongo bootstrap was replaced with explicit scoped
PostgreSQL composition; no live domain script execution is claimed by this move.
The former script `run_web_research_stagegraph_local` was retired because
its fake lifecycle bypassed admission and called a stale operation API. Its
post-rewrite source is recoverable in
`.scratch/organization-checkpoint/removed-domain-scripts/`. Use governed admission
or the deterministic production-stack tests instead.

The assertion-free permanent skip
`tests/unit/schema/test_schema_grounding_services.py::test_goal_semantic_handlers_execute_and_independently_rehydrate_reconciliation`
was removed. It only skipped an already-deleted direct BoundGoal handler path;
actual operation-template/family acceptance tests retain the replacement proof.
Reviewed web-capability fixtures/promotion and reviewed payload resources also
move into the optional package, so research-specific workflow strings do not
remain generic kernel configuration.

The optional package owns its own
`src/biotech_mission_adapters/migrations/0001_scoped_records.sql` with forced RLS
and immutable scoped records. It is outside the general migration chain.
`BiotechSettings` owns Neo4j/schema credentials, and schema resources moved to the
optional package. No live domain operation or Neo4j write was executed.
See [optional integration guide](../../../../../integrations/biotech/README.md).

Application policies and extension validators must be explicitly registered by
trusted deployment composition. Missing registration fails closed; a generic API
does not insert permissive Biotech defaults.

## Composition and capability ownership

Trusted wiring moved from application/HTTP modules into bootstrap:
`coordinator_composition.py`, `operation_recovery_composition.py` and
`runtime_control.py`. No import aliases remain at their former application or
interface locations. The former infrastructure catchall is split into storage,
auth, Agent Server,
Deep Agents persistence, capabilities, realtime and operation adapter packages.
For example JWT verification is `adapters/auth/jwt.py`, and realtime transport is
`adapters/realtime/postgres_redis.py`. Framework-neutral payload protocols now live
under `application/ports/payloads.py`; provider transport errors and overwrite
values cross
that boundary as neutral application contracts. Architecture guards are in
`tests/architecture/test_package_boundaries.py`.

Generic discovery and inspection now belong in `application/capabilities`, with
scoped PostgreSQL candidate and projection persistence. The obsolete concrete
`adapters/capabilities/catalog_projection_admin.py`, `catalog_projection_events.py`
and `adapters/document_models/external_capability.py` are removed. Their durable
replacements are `adapters/postgres/capability/projection_events.py` and
`external_candidates.py`; the application projection logic remains framework-neutral. Catalog HTTP/CLI handlers
share the same trusted installation binding and application services. Their
presence does not admit an external candidate or authorize execution.

Seven general catalog scripts remain under root `scripts/`, now using explicitly
configured scoped PostgreSQL rather than Mongo bootstrap:

- `discover_external_capabilities.py`
- `rebuild_capability_search_projection.py`
- `search_capability_catalog.py`
- `process_capability_search_projection_events.py`
- `verify_capability_search_projection.py`
- `promote_coordinator_surface.py`
- `evaluate_coordinator_retrieval.py`

The eighth converted script, `promote_reviewed_web_capabilities.py`, is
application-specific and moved to the optional Biotech package listed above.
Catalog tenant arguments cannot override the configured trusted catalog scope.
The generic `scenario_b_live` runner also uses scoped PostgreSQL; no live execution
or metered discovery is implied by converting these entrypoints.

The canonical `skills/mission-control` directory manifest is now version 0.1.1 and
includes catalog operations. The design/launch helper was renamed from
`.agents/skills/belllabs-workflow-coordinator` to
`.agents/skills/mission-control-coordinator`; its authored asset identity is
`skill.mission-control-coordinator`. Promotion/source references were updated;
there is no old-name alias. Download and verify entire versioned directories,
including references and manifests.

## Agent Server consolidation

Removed root `langgraph.json`, `langgraph.async_subagents.json`,
`langgraph.block_c.json` and `langgraph.block_c_n1.json`; use only
`agent_server/langgraph.json` with an explicit runtime/qualification profile.
Two tracked environment files were consolidated into `agent_server/runtime.env`
containing environment references rather than credential values.

Removed adapter subapps `async_subagents/http_app.py` and
`block_c_qualification/http_app.py`; both now use the parent Agent Server HTTP app.
Authentication modules retain specialized verification/policy helpers, while
`deployment_auth.auth` is the sole registered authentication entrypoint. Profile
checks cover native `threads/create_run` and exact assistant UUIDs as well as graph
names. A disallowed registered graph returns 403 (the old unregistered path could
return 404); supported qualification interrupt/resume behavior is preserved.

Actual local runtime, qualification and N1-only tests pass in
`tests/integration/agent_server/test_canonical_server_local.py`; 40 unit tests pass.
The 19 skipped external PostgreSQL/hosted drills remain unproved. This consolidation
does not turn Agent Server into a mission scheduler or certify production hosting.

## Compose volume identity

The Compose project namespace intentionally remains
`biotech-research-ingestion-evaluation-system` so existing local volume identities
survive the source-directory rename. It is not the product or Python package name.
Changing it requires an explicit volume migration; do not rename it or remove
volumes as an incidental cleanup step. The Supabase project name independently
remains `biotech-research-ingestion`.

## Preserved material and recovery

- Existing unrelated working-tree changes and prior user deletions are preserved.
- Ignored `app/personal_code/` remains user-owned and was not removed.
- Original source checkpoint: `.scratch/organization-checkpoint/source-before-organization.zip`.
- Earlier implementation diff: `.scratch/mission-control-parity-checkpoint/tracked.patch`.
- Pre-documentation rewrite copies:
  `.scratch/mission-control-parity-checkpoint/documentation-before-organization/`.
- The historical discussion/WP trees were deleted by the owner (85 files, pending);
  see [pending owner documentation deletions](#pending-owner-documentation-deletions).
  Previously deleted historical documents were not recreated.

Recovery is selective: inspect the map/archive, extract the required file to a
temporary comparison directory, review it against concurrent work, and restore
only the intended content. Never use git reset/clean, whole-tree extraction over
the current workspace, or database deletion as a recovery shortcut. Do not restart
old and new workers on the same live executions without an explicit compatibility
decision.

## Common component cutover (2026-10-03)

Recorded after the implementation lanes landed; exact paths are in the inventory
below. None of these removals drops a schema, table or row: legacy data in live or
local databases stays where it is under separate persistent-data authorization.

- **Transitional composition retired.** `storage_mode` accepts only
  `production_common`; API, worker and preflight verify the installed common release
  (`bootstrap/common_installation.py`). `transitional_local`, `belllabs.request_scope`
  and `belllabs.catalog_scope` have no production use.
- **Repositories converted.** Every PostgreSQL repository uses `mission_control` /
  `mission_control_search` with transaction-local `mc.*` scope
  ([persistence map](plans/mission-control-two-project-rollout/persistence-map.json)).
- **Legacy runner removed (2026-10-03).** `apply_application_migrations`,
  `apply_capability_search_migrations` and `create_application_migration_pool` in
  `adapters/postgres/connections.py`, `scripts/migrate_application_database.py`,
  `scripts/migrate_capability_search.py` and `bootstrap/installation.py` were removed
  after every test moved to the common fixture. Precondition proof: no caller in
  `src`, `tests` or `scripts`; the independent static scan
  (`tests/qualification/two_project/test_static_architecture.py`). Recovery: the exact
  pre-removal bytes and SHA-256 are in `.scratch/two-project-rollout-checkpoint/retired-legacy-runner/` and in git at
  `f6521c1`. The historical chain itself stays as pinned bytes and is no longer
  executable from this repository.
- **Sandbox snapshot store retired.** The common release defines no sandbox snapshot
  table and nothing in production composition constructed the transitional store;
  `PostgresSandboxSnapshotRepository` now raises `SandboxSnapshotPersistenceRetired`.
  The capability is unavailable rather than silently backed by another store.
- **Runtime event relay removed** from `bootstrap/technical_api.py` (it read
  `belllabs_control.agent_runtime_events`, which had no constructed writer).
- **LangGraph saver/store** moved from `belllabs_langgraph` to `mission_control_runtime`
  (runtime phase of `mission-db`); legacy and business schemas are refused.

### Retired legacy tables

Taken verbatim from `retired_legacy_tables` in the persistence map. These transitional
tables have no destination in the common release; their code paths were removed or
had no production writer. Existing rows are not migrated or deleted.

| Legacy table (`belllabs_control`) | Evidence for retirement |
| --- | --- |
| `agent_runtime_checkpoints` | save/load/complete_checkpoint have no caller (rg 'save_checkpoint/load_checkpoint/complete_checkpoint' src integrations tests: none outside the module); methods removed |
| `agent_runtime_events` | PostgresRedisRuntimeEventBus never constructed (rg PostgresRedisRuntimeEventBus: only its own module); class removed |
| `agent_runtime_messages` | no writer in src (G0) |
| `agent_runtime_sessions` | no writer in src (G0 legacy-tables.json has_live_writer=false) |
| `execution_resource_leases` | only PostgresResourceLeaseJournal writes it; rg PostgresResourceLeaseJournal: only stage3 module and its test; class removed |
| `operation_journal_backfill_batches / _applied_batches / _quarantine` | historical backfill out of scope (G1 section 5); operation_journal_backfill.py no longer exists in src |
| `runtime_async_tasks` | no writer in src (G0) |
| `runtime_checkpoint_observations` | only a retention DELETE in the tests-only PostgresStage3RetentionRepository (G0) |
| `runtime_decision_responses (via DurableDecisionService.answer)` | converted anyway: PostgresDecisionRepository is constructed in production (runtime_authority -> agent_server/http_app.py) |
| `runtime_interrupt_decisions` | no writer in src (G0) |
| `runtime_interrupt_requests` | no writer in src (G0) |
| `runtime_lineage_records (provenance read)` | PostgresExecutionLineageRepository (append/provenance_for_result) constructed only in tests; append_lineage_in_transaction kept and converted (execution_lineage_record) |
| `runtime_repair_audit` | only PostgresRuntimeIncidentRepository writes it; rg: only stage3 module and its test; class removed |
| `runtime_retention_deletion_audit` | only PostgresStage3RetentionRepository writes it; rg: stage3 module and two tests; class removed |
| `schema_migrations` | replaced by mission_control.component_release (lead/database lane) |

## Two-project rollout removal inventory (2026-10-03)

Exact inventory for [plan section 13](plans/mission-control-two-project-rollout/IMPLEMENTATION_PLAN.md#13-removal-guide-clean-code-and-documentation-closure),
observed against HEAD `f6521c1` plus the uncommitted rollout work. Machine-readable
companions: [removal-inventory.json](../../../../organization/removal-inventory.json) and
[legacy-belllabs-control-chain.json](../../../../organization/legacy-belllabs-control-chain.json).
**"Safe later" is not permission to delete now.** Rows not marked "done" keep their
paths until the named precondition and proof exist; source cleanup never drops
schemas, rows, buckets, collections or volumes.

| Path | Exists / tracked now | Class | Replacement | Unique evidence (hash / location) | Removal precondition | Test / receipt proving it | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 54 paths in [mongo-removals.json](../../../../organization/mongo-removals.json) (table below) | all absent; none tracked | already-removed | PostgreSQL adapters per path below | `f6521c1` history; source zip `sha256:84f23f73db7446bd3bbeb9d9d2a74c0e16f1739e31d900805e8d577bde649d4c` | met | `removal-inventory.json`: `all_absent=true`, `all_untracked=true`, `replacements_missing=[]` (absence is not test evidence) | done; never recreate or count as passing tests |
| Old `app/` source tree (483 entries in [file-map.json](../../../../organization/file-map.json)) | 0 mapped sources exist; only `app/.cursor/rules/user_subagent_preference.mdc` tracked | already-removed | `src/mission_control/**`, `integrations/biotech/**` per the maps | source zip above | met | `removal-inventory.json` `app_sources_present_now=[]`; G0 resolved 159 intermediate destinations, 0 unresolved | done |
| `app/{agent_server,api,application,domain,experiments,integrations,mcp,middleware,migrations,models,temporal}/`, `app/__pycache__/` | removed 2026-10-07; were ignored bytecode only (524 `.pyc`, no source) | regenerable cache | none needed | none (bytecode of removed sources) | met (owner-approved sweep; `app/personal_code` not traversed) | absence of those directories; `app/.cursor` and `app/personal_code` remain | done |
| `app/.cursor/` (14 ignored URL maps + 1 tracked rule) | exist | preserve unique evidence / user material | none | the files | owner decision | n/a | preserve |
| `app/personal_code/` | exists, ignored | preserve (user-owned) | none | user content (not read) | never by cleanup | n/a | preserve |
| `src/mission_control/adapters/infrastructure/` | removed 2026-10-07; was 15 `.pyc` and 0 sources | regenerable cache | split adapter packages ([adapter-module-map.json](../../../../organization/adapter-module-map.json)) | none | met in the same owner-approved sweep | directory absent | done |
| Root `langgraph.json`, `langgraph.async_subagents.json`, `langgraph.block_c.json`, `langgraph.block_c_n1.json` | absent, untracked | already-removed | `agent_server/langgraph.json` + `agent_server/runtime.env` (tracked) | `f6521c1` history | met | `removal-inventory.json` `root_langgraph_configs`; `tests/integration/agent_server/test_canonical_server_local.py` | done |
| Six further removals (two Agent Server subapps, `bootstrap/legacy_preflight.py`, catalog projection admin/events, external capability document model) | absent, untracked | already-removed | sections above | `f6521c1` history | met | `removal-inventory.json` `other_removals` | done |
| `src/mission_control/adapters/postgres/migrations/` (0001-0040) | 40 files exist, tracked, unmodified | keep-until-parity | `packages/mission-control-db-contract/component/migrations/` | chain `sha256:8ca2f1504e110e7c17b6757803706d8342e59fdaee37571eb3d609d86f6436e4`; per-file SHA-256 and blob ids in [legacy-belllabs-control-chain.json](../../../../organization/legacy-belllabs-control-chain.json) | G3 parity on both disposables (met locally, run `20261003-g3-r1`); zero legacy references in production code; no caller of the legacy runner (still in `adapters/postgres/connections.py`, used by `scripts/migrate_application_database.py` and `scripts/migrate_capability_search.py`) | `tests/qualification/two_project/test_static_architecture.py` (chain pin + production scan; the scan currently fails only on `connections.py`) | keep in place; bytes never edited; never applied to live; runner removal pending |
| Transitional composition branches (`transitional_local`) | removed: `api.py`, `worker.py`, `composition.py`, `preflight.py` accept only `production_common` (`bootstrap/common_installation.py`); every repository converted to `mission_control`/`mission_control_search` | already-removed | `production_common` composition | `f6521c1` history | met; the legacy runner and `bootstrap/installation.py` were removed 2026-10-03 | production scan; poisoned/absent legacy round trip (`test_legacy_poison_round_trip.py`) passes | done |
| `tests/fixtures/mission_control_production_stack.py` | exists, tracked | keep-until-parity | `tests/fixtures/mission_control_common_db.py` + production stack on the common release | `f6521c1` blob | every importing acceptance test runs on the common component | G3 acceptance on both disposables | keep |
| `../biotech-postgres-db-contract/src/biotech_postgres_db_contract/` (`installer`, `deployment`, `fingerprint`, `preflight`, `verification`, `cli`) | exists; sibling has no git repository | replace-then-remove (separately reviewed) | `mission_control_db_contract` (`mission-db`) | archive a copy before editing (no VCS history) | thin `biotech-db` wrapper proven equivalent; integrity/recovery tests ported | DB-lane wrapper tests + `tests/qualification/two_project/test_release_parity.py` | keep until the reviewed wrapper lands |
| `../biotech-postgres-db-contract/component.lock.json` | exists (`status: blocked_missing_common_release`) | replace-then-remove | `deployments/biotech/release.lock.json` from `mission-db lock` | `sha256:0c03c6d41e1a380f4e19853f90fa49b93ca68e912fa765ee28f8ebbfc4d0bae3` | a real accepted pin exists | `load_release` verification of the accepted lock | keep (the blocked lock is truthful) |
| `experiments/` | exists; 34 tracked files | conditional prototype | governed production paths | tracked history | every consumer/proof mapped or deliberately retired | per-consumer mapping | keep; never bulk-delete |
| `src/mission_control/bootstrap/technical_api.py` | exists, tracked; runtime event relay (`belllabs:runtime:*` Redis to `belllabs_control.agent_runtime_events`) removed | conditional prototype | `bootstrap/api.py` public facade | tracked history | remaining proof surfaces mapped | production scan (passes for this file) + facade tests | keep |
| `src/mission_control/bootstrap/runners/scenario_b_live.py` | exists, tracked | conditional prototype | governed admission | tracked history | consumer retired or converted | n/a | keep |
| `.tmp-cleanup-unit/`, `.tmp-worker-poll-20261003/` | exist, untracked; access denied to this account | unclassifiable under current account: preserve | none | unknown (unreadable) | owner/creating account inspects metadata and evidence purpose | none possible now | preserve; never traverse `current` links |
| `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `__pycache__/` (182 dirs), `pytest-of-Pinda/`, `.uv-cache/`, `packages/mission-control-db-contract/.ruff_cache/` | exist, ignored | regenerable cache | regenerated by tools | none | approved sweep | n/a | keep until approved sweep |
| `.scratch/organization-checkpoint/source-before-organization.zip` | exists, ignored | preserve unique evidence | none | `sha256:84f23f73db7446bd3bbeb9d9d2a74c0e16f1739e31d900805e8d577bde649d4c` | never | n/a | preserve |
| `.scratch/mission-control-parity-checkpoint/` (incl. `tracked.patch`, `documentation-before-organization/`) | exists, ignored | preserve unique evidence | none | `tracked.patch` `sha256:42550895df3e3141f50560d67195d2f39b82029c89351897384e77d223de64db` | never | n/a | preserve |
| Other `.scratch/` trees (247 symlinks incl. pytest `current` links) | exist, ignored | preserve unique evidence | none | G0 scratch reparse-point inventory | owner review | n/a | preserve; never traverse links |
| 85 pending owner deletions under `docs/interview_and_research_result_documentation/` (20) and `docs/migrations_instructions/` (65) | absent on disk; tracked at HEAD; deletion uncommitted | already-removed (user-made) | `docs/knowledge/`, AGENTS.md, this guide | blob ids in [removal-inventory.json](../../../../organization/removal-inventory.json) | owner commits the deletion | `python docs/tools/check_links.py` | preserve the deletion; never restore; live references repointed (below) |
| Live `belllabs_control`, `capability_search` (Biotech project: 4 tables, `documents` about 542 rows per the G0 [identity evidence](../../../../qualification/two-project/biotech-research-ingestion/g0-readonly-20261003/identity.json)), `belllabs_langgraph` | live data (local and/or Biotech project) | separate persistent-data authorization | `mission_control`, `mission_control_search`, `mission_control_runtime` for new admitted runs only | the live data itself | explicit owner data decision, never part of source cleanup | protected row digests unchanged (`protected-diff.json` per target) | preserve; never dropped or migrated by source cleanup |
| Compose volumes (project `biotech-research-ingestion-evaluation-system`) | exist (local Docker) | separate persistent-data authorization | none | volume contents | explicit volume-migration decision | n/a | preserve; no rename or prune |
| Mongo records/buckets | outside this repository | separate persistent-data authorization | PostgreSQL adapters for new runs | the data | explicit owner decision | n/a | preserve; no purge |

### Retired Mongo persistence paths (validated)

<details>
<summary>All 54 entries of mongo-removals.json with their current replacement</summary>

| Retired path | Now | Replacement (G0-inferred, exists now) |
| --- | --- | --- |
| `src/mission_control/application/programs/mongo_goal_directed_repository.py` | absent, untracked | `src/mission_control/adapters/postgres/orchestration/goal_directed_repository.py` |
| `src/mission_control/application/programs/mongo_stagegraph_repository.py` | absent, untracked | `src/mission_control/adapters/postgres/orchestration/stagegraph_repository.py` |
| `src/mission_control/application/execution/operations/mongo_operation_execution_repository.py` | absent, untracked | `src/mission_control/adapters/postgres/operations/operation_journal.py`; `src/mission_control/adapters/postgres/operations/operation_binding_repository.py` |
| `src/mission_control/application/execution/operations/mongo_operation_authority_migration.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `src/mission_control/application/execution/operations/mongo_operation_journal_backfill.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `src/mission_control/application/execution/operations/operation_journal_backfill.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `src/mission_control/application/execution/operations/operation_journal_read_routing.py` | absent, untracked | `src/mission_control/adapters/postgres/operations/operation_journal.py` |
| `src/mission_control/adapters/postgres/operations/operation_journal_backfill.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `src/mission_control/application/subordinates/mongo_async_subagent_repository.py` | absent, untracked | `src/mission_control/adapters/postgres/async_subagents/async_subagent_detail_repository.py`; `src/mission_control/adapters/postgres/async_subagents/async_subagents.py` |
| `src/mission_control/application/artifacts/mongo_workspace_repository.py` | absent, untracked | `src/mission_control/adapters/postgres/workspaces/workspace_manifest_repository.py` |
| `src/mission_control/application/artifacts/mongo_snapshot_repository.py` | absent, untracked | `src/mission_control/adapters/postgres/workspaces/snapshot_repository.py` |
| `src/mission_control/application/artifacts/mongo_artifact_repository.py` | absent, untracked | `src/mission_control/adapters/postgres/workspaces/artifact_repository.py`; `src/mission_control/adapters/postgres/workspaces/artifact_metadata_repository.py` |
| `src/mission_control/adapters/infrastructure/mongodb.py` | absent, untracked | `src/mission_control/adapters/postgres/connections.py` |
| `src/mission_control/adapters/infrastructure/workspace_candidate_contents.py` | absent, untracked | `src/mission_control/adapters/postgres/workspace_candidate_contents.py` |
| `src/mission_control/adapters/document_models/artifact_promotion.py` | absent, untracked | `src/mission_control/adapters/postgres/workspaces/artifact_repository.py` |
| `src/mission_control/adapters/document_models/control_plane.py` | absent, untracked | `src/mission_control/adapters/postgres/control_plane/definition_repository.py` |
| `src/mission_control/adapters/document_models/goal_directed.py` | absent, untracked | `src/mission_control/adapters/postgres/orchestration/goal_directed_repository.py` |
| `src/mission_control/adapters/document_models/infrastructure.py` | absent, untracked | `src/mission_control/adapters/postgres/documents.py` |
| `src/mission_control/adapters/document_models/operation_execution.py` | absent, untracked | `src/mission_control/adapters/postgres/operations/operation_journal.py` |
| `src/mission_control/adapters/document_models/sandbox_snapshot.py` | absent, untracked | `src/mission_control/adapters/postgres/workspaces/snapshot_repository.py` |
| `src/mission_control/adapters/document_models/stagegraph.py` | absent, untracked | `src/mission_control/adapters/postgres/orchestration/stagegraph_repository.py` |
| `src/mission_control/adapters/document_models/workspace_materialization.py` | absent, untracked | `src/mission_control/adapters/postgres/workspaces/workspace_manifest_repository.py` |
| `tests/integration/temporal/test_rrm_004_worker_restart_recovery.py` | absent, untracked | `tests/acceptance/mission_control/test_postgres_runtime_parity.py` |
| `tests/integration/agent_server/test_rrm_013_async_subagent_live.py` | absent, untracked | `tests/integration/postgres/test_async_subagent_postgres_authority.py` |
| `tests/integration/postgres/test_operation_journal_backfill_integration.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `tests/unit/operations/test_operation_journal_backfill.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `tests/unit/orchestration/test_rrm_018_goal_document_identity.py` | absent, untracked | `tests/integration/temporal/test_rrm_016_goal_directed_journaled.py` |
| `tests/fixtures/mongo_database.py` | absent, untracked | `tests/fixtures/mission_control_production_stack.py` |
| `tests/fixtures/operation_backfill_worker.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `tests/fixtures/rrm004_persistent_stack.py` | absent, untracked | `tests/fixtures/mission_control_production_stack.py` |
| `tests/fixtures/rrm004_restart_worker.py` | absent, untracked | `tests/fixtures/mission_control_production_stack.py` |
| `tests/fixtures/rrm006_fork_stack.py` | absent, untracked | `tests/fixtures/run_forks.py` |
| `tests/fixtures/rrm013_child_worker.py` | absent, untracked | `tests/fixtures/rrm013_live_stack.py` |
| `tests/fixtures/rrm010_combined_smoke.py` | absent, untracked | `tests/fixtures/mission_control_production_stack.py` |
| `tests/integration/mongodb/test_artifact_promotion_mongodb_integration.py` | absent, untracked | `tests/integration/postgres/test_artifact_promotion_postgres_integration.py` |
| `tests/integration/mongodb/test_control_plane_mongodb_integration.py` | absent, untracked | `tests/integration/postgres/test_definition_catalog.py` |
| `tests/integration/mongodb/test_goal_directed_documents_mongodb.py` | absent, untracked | `tests/integration/postgres/test_immutable_runtime_documents.py` |
| `tests/integration/mongodb/test_operation_execution_mongodb_integration.py` | absent, untracked | `tests/integration/postgres/test_operation_journal_stage1.py` |
| `tests/integration/mongodb/test_sandbox_snapshots_mongodb_integration.py` | absent, untracked | `tests/unit/workspaces/test_sandbox_snapshots.py` |
| `tests/integration/mongodb/test_workspace_materialization_mongodb_integration.py` | absent, untracked | `tests/integration/postgres/test_workspace_artifact_documents.py` |
| `tests/integration/mongodb/__init__.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `tests/acceptance/control_plane/test_rrm_005_inspection.py` | absent, untracked | `tests/integration/postgres/test_runtime_inspection_postgres.py` |
| `tests/acceptance/control_plane/test_rrm_006_semantic_forks.py` | absent, untracked | `tests/integration/postgres/test_run_forks_postgres.py` |
| `tests/acceptance/control_plane/test_rrm_008_cancellation_demo.py` | absent, untracked | `tests/integration/temporal/test_rrm_008_family_cancellation.py` |
| `tests/acceptance/control_plane/test_rrm_009_object_store.py` | absent, untracked | `tests/acceptance/mission_control/test_postgres_children_and_artifacts.py` |
| `tests/acceptance/control_plane/test_rrm_009_live_capabilities.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `tests/acceptance/control_plane/test_rrm_009_production_composition.py` | absent, untracked | `tests/acceptance/mission_control/test_postgres_runtime_parity.py` |
| `tests/acceptance/control_plane/test_rrm_009_production_cancellation.py` | absent, untracked | `tests/unit/operations/test_rrm_009_cancellation_composition.py` |
| `tests/acceptance/control_plane/test_rrm_010_combined_smoke.py` | absent, untracked | `tests/acceptance/mission_control/test_postgres_runtime_parity.py` |
| `tests/acceptance/control_plane/test_rrm_016_goal_directed_demo.py` | absent, untracked | `tests/integration/temporal/test_rrm_016_goal_directed_journaled.py` |
| `tests/acceptance/control_plane/test_rrm_020_shared_goal_workspace.py` | absent, untracked | `tests/acceptance/mission_control/test_postgres_children_and_artifacts.py` |
| `tests/fixtures/rrm009_live_capabilities.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `scripts/reorganize_application_packages.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |
| `scripts/reorganize_tests.py` | absent, untracked | none (retired backfill / one-shot / Mongo-only / live-provider proof) |

</details>

Content of every retired path is recoverable from `f6521c1` history and the source
archive above.

### Pending owner documentation deletions

The owner deleted 85 tracked historical documents (uncommitted as of 2026-10-03,
HEAD `f6521c1`). They are user-made, preserved as deletions and must not be
restored; each remains recoverable with `git show f6521c1:<path>` (blob ids in
[removal-inventory.json](../../../../organization/removal-inventory.json)). Live references were
repointed or marked historical with that recovery command in `docs/README.md`,
`.cursor/rules/_briefings/01-api-runbook-briefing.md`,
`.cursor/rules/_briefings/02-codebase-organization-briefing.md`,
`docs/specs/archive/coordinator-surface-2026-10/mcp-plans/COORDINATOR_ARCHITECTURE_AND_PLAN.md`,
`docs/specs/archive/coordinator-surface-2026-10/mcp-plans/implementation_plans/COORDINATOR_SPEC_INDEX.md` and
`docs/specs/archive/coordinator-surface-2026-10/mcp-plans/implementation_plans/COORDINATOR_PHASES_2_3_WORKFLOW_CATALOG.md`.
Validate with `python docs/tools/check_links.py`.

## Knowledge Services verification.v1 retirement (SV-17, 2026-10-25)

Knowledge Services removed its legacy verification authority in SV-17; AI Engineer
database contract 0.5.0 (migration `20261025010000`) withdrew the tables behind it.
Mission Control source did not depend on these paths; this inventory is for operators
and agents who might otherwise route to them.

| Retired Knowledge Services path | Replacement | Consequence for Mission Control |
| --- | --- | --- |
| `verification.v1` claims, report and metric mutations (`/v1/verification/claims:verify`, `reports:verify`, `metrics:verify`; MCP `verify_citations`, `verify_report`, `verify_metric`) | `report.register` / `report.assess` over K01 on the `knowledge_verification` component | Use the knowledge gateway tools; old routes answer 404 |
| Adjudication request/decision and reads (`/v1/verification/adjudications*`, `adjudication-decisions/*`) | Component review (`waiting_review` handles) | No caller-side adjudication route |
| Audit-bundle inspection, run/manifest/case/evidence reads, claims/report result reads | `knowledge.read` (exact revision package) and `operations/{id}` over K01 | Read results through the gateway only |
| Semantic observation and reconciliation | None | Removed |
| Internal drift revalidation queue (`/v1/system/verification-drift-*`, scope `verification.drift.consume`) | None (outbox withdrawn) | `VERIFICATION_DRIFT_REVALIDATION_ENABLED`, `VERIFICATION_DRIFT_CONSUMER_SERVICE_IDENTITIES_JSON` and `VERIFICATION_COMPONENT_DRIFT_*` are refused at Knowledge Services startup |
| Executor verifier chain (`verify-claims`, `judge`, `policy`, `seal`, `status`, `/runs/:runId`), report, recovery and content-link operations | K01 on the component; the executor keeps capture/artifact tools as a non-authoritative cache | K01 `verify.claims` answers `SCHEMA_UNSUPPORTED`; the `verify_claims` tool receives that refusal |
| Eve runtime attestation for `verifyClaims` / `verifyReport` | K07 issuer credentials | `VERIFICATION_EVE_RUNTIME_ATTESTATION_KEYS_JSON` is refused |

Retired configuration is refused at startup, never ignored:
`VERIFICATION_RETIRED_CONFIGURATION:<NAME>` (Knowledge Services API and worker) or
`EXECUTOR_RETIRED_CONFIGURATION:<NAME>` (executor). The gateway's `KNOWLEDGE_*` settings
are in the [local API guide](../../../../MISSION_CONTROL_LOCAL_API.md#knowledge-gateway-configuration-sprint-v-sv-16sv-17).
The release bundle records the retired paths, pins and capability matrix:
[RELEASE-BUNDLE.md](../../provider-consolidation-2026-10/sprint-v/release/RELEASE-BUNDLE.md).

## Older Biotech knowledge path retirement (2026-10-27)

The owner's decision OC-D202 (sprint-oc/DECISIONS.md §5) deleted the parallel, pre-K01 Biotech knowledge
path. It was not wired by any committed runtime-options factory and no kernel module imported it.

| Removed | Replacement |
| --- | --- |
| MC `integrations/biotech/src/biotech_mission_adapters/knowledge/` (`adapter.py`, `canonical.py`, `capability.py`, `composition.py`, `envelope.py`, `ledger.py`, `settings.py`, `transport.py`): the `BiotechKnowledgeAdapter`, the `mc.knowledge_request.v1` envelope, `bks-canonical-json.v2`, the JSONL effect ledger and the `BIOTECH_EXECUTOR_URL` / `BIOTECH_EXECUTOR_TOKEN` / `BIOTECH_CAPABILITY_DESCRIPTOR_PATH` / `BIOTECH_KNOWLEDGE_LEDGER_PATH` settings | The shared knowledge gateway over K01 `ks.knowledge_operation.v2` to the Knowledge Services `biotech-graph` binding, which calls the BKS executor (`docs/knowledge/knowledge-services.md`) |
| MC `integrations/biotech/.../bootstrap/scripts/prove_biotech_knowledge_boundary.py` and `tests/integration/biotech/knowledge/` | The K01 golden and negative conformance tests under `tests/conformance/` and the Sprint V Biotech binding proofs |
| KS `packages/contracts/src/knowledge-request-envelope.ts`, its test, `fixtures/knowledge-request-envelope.v1.golden.json` and `packages/knowledge-db/test/conformance/knowledge-request-envelope.conformance.test.ts` | `@aiengineer/knowledge-operation-protocol` (K01); `reconcileReceipt` stays covered by `packages/knowledge-db/src/ingestion/tests/receipt-reconciliation.test.ts` |

The rest of `integrations/biotech` (schema grounding, reference research, Neo4j adapters, Temporal
activities, HTTP routers) is unchanged and remains the optional Biotech domain package.

## Boolean-only output promises and row-count completion (WI-01, 2026-10-27)

Sprint OC WI-01 (OVE-163) replaced these behaviours directly; experimental data is disposable and no
alias or fallback remains (`docs/knowledge/output-contracts.md`).

| Removed | Replacement |
| --- | --- |
| Manifest output `required: true/false` and `DefinitionOutput.required` as a field | `enforcement: required | expected | optional` plus `form`, `cardinality`, `coverage`, `requirements`, `members`, `media_type`, `repository`; `required` survives only as a read-only view of `enforcement` |
| Last-stage assignment of a required goal no stage serves (`manifest_lowering._stage_blueprint`) | Explicit ownership (stage objectives or cited output evidence); an unowned goal is the `unowned_goal` blocker |
| A `depends_on` dependency carrying the producer's first output slot; every join lowered as required `all` | The exact bound `inputs[].from` output; ordering-only `depends_on` requires every producer output; the authored `join` (`all`, `any`, quorum) |
| `SubmissionService.finalize` declaring obligations from submitted rows when none were declared, and counting a submitted row as fulfilled (`outcome_basis = submission_coverage`) | Host-declared obligations only; verdicts count; bases `declared_obligations`, `no_declared_obligations`, `assessed`, `attempt_failed` (release 1.7.0 keeps `submission_coverage` readable for old rows) |
| No inspectable promises in `EffectiveRunConfiguration` | `EffectiveRunConfiguration.output_promises` (`mc.output_promises.v1`), the `submit_output` act, CAS promotion, assessments, pinned frontiers and fulfillment decisions (`application/outputs/fulfillment.py`, common release 1.7.0 `0056_output_contracts_and_fulfillment`) |

Recovery: re-author manifests with `enforcement:` (the YAML fixtures under `tests/fixtures/manifests`
were rewritten that way) and reinstall disposable databases from release 1.7.0.

## Deep Agents compile into its lane package (OC-R1 / OVE-196, 2026-10-27)

ADR-0063's resolution seam: the application layer reaches the Deep Agents lane only through
`RuntimeResolver.resolve`, so the lane's compile moved into its package (no shim).

| Removed | Replacement |
| --- | --- |
| `application/authoring/lanes/deep_agents.py` (`DeepAgentsLaneAdapter`, `DeepAgentsNodeInputs`, `SelectedSubagent`, `SeedComponents`, `INHERIT_CHILD_PROMPT`) | `adapters/deep_agents/lane.py`: the same translations and receipt; its refusals now carry a resolution `code` and selection pointers (`/items/<i>[/...]`, `/provider_options/deep_agents/...`) that the launch author maps back to the same manifest pointers |
| `lanes/deep_agents.py::SUBAGENT_FIELDS` | `application/execution/harness/describe.py::DEEP_AGENTS_SUBAGENT_FIELDS` (beside the describe matrix that carries it), re-exported as `adapters/deep_agents/lane.py::SUBAGENT_FIELDS` |
| `lanes/deep_agents.py::AsyncSubagentGraphBinding` | `application/authoring/manifest_launch_inputs.py::AsyncSubagentGraphBinding` (the launch bindings file owns its shape) |
| `application/authoring/lanes/support.py` and the package `application/authoring/lanes/` | `application/authoring/subagent_support.py` |
| `ManifestLaunchResolver.node` with `_subagents`, `_seeds`, `_component`, `_model`, `_sandbox`, `_capabilities`, `_served_or_fail`, and `NodeLaunchBinding` | `ManifestLaunchResolver.deep_agents_node` builds the neutral selection and resolves it; the lane's `adapters/deep_agents/compile.py::DeepAgentsCompileAdapter` maps pins to deployment components; `adapters/deep_agents/template_bridge.py::deep_agent_operation_part` produced the typed request part per template (removed by OC-R2, below) |
| `ManifestLaunchResolver(bindings, served, ..., async_result_policy_refs=)` | `bootstrap/resolution.py::compose_manifest_launch_resolver(bindings, served, ...)`; `ManifestLaunchResolver(bindings, *, ..., resolution=LaunchResolution)` |
| tests `tests/unit/authoring/test_deep_agents_lane_adapter*.py` | `tests/unit/deep_agents/test_lane_adapter*.py`, plus `test_compile.py` and the compile conformance entry `tests/conformance/lanes/compile/deep_agents.py` |

`ManifestLaunchResolver.provider_node` and `cursor_node` remain until R3 relocates those lanes.

Behavior a Deep Agents launch changed with the seam (each refusal keeps a pointer that names the
selection):

- **Error-surfacing order.** The launch author first checks what admission fixed (lane, scaffold,
  model profile present and catalogued, model settings, sandbox profile present, context profile
  names, resolved and admitted pins, subagent catalog rows, a plugin with no members), then the
  resolver admits the pairing, then the lane's compile checks in its own order: model component,
  sandbox, the parent's MCP servers, tools and Skills (by kind, then name, not manifest order),
  context bundles, hook scripts, a node plugin's members, environment kits, middleware, the
  children's seed components, then the lane adapter (options, lane features, children). Before, every check ran in manifest group order inside
  `ManifestLaunchResolver.node`; a manifest with several faults may now report a different one
  first. A missing model credential is still reported last.
- **A hook script or context bundle whose capability id has a `capabilities` component binding** is
  refused (`ITEM_UNSUPPORTED_ON_LANE`, the old "has no deployment component binding ... no Deep
  Agents launch binding" message). Before, such an id was materialized as whatever MCP server, Skill
  or tool the binding named; that was not a served hook or context path.
- **A node-level plugin** is still refused at the plugin row with the old message (`plugin <id>@<v>
  has no deployment component binding ...`, now reported through its first member's
  `/items/<i>/plugin`); a plugin that expanded to no members is refused at its row by the launch
  author instead of passing.
- **A model profile missing from the deployment** is refused by the launch author against the Model
  Catalog (`... is not in the model catalog: it has no deployment model binding ...`).
- **Data Class.** The manifest's `data_class` is carried on `MissionDefinition` (additive, absent
  when undeclared) into the agent configuration; an undeclared mission resolves on Deep Agents
  under the documented stand-in `internal` (`UNDECLARED_DATA_CLASS_STAND_IN`), and a lane that
  admits only declared classes refuses `DATA_CLASS_UNDECLARED` (`launch_data_class`).
  Superseded by OC-R4 below: the stand-in is gone.

## Application names leave the kernel: the Application Profile (OC-R4 / OVE-198, 2026-10-27)

Removed, not shimmed; the replacement is `deployments/<app>/application.toml` loaded by
`bootstrap/application_profiles.py`.

- **`Settings.knowledge_binding_ids` / `KNOWLEDGE_BINDING_IDS`.** The binding id, apply contract
  and payload layout are the profile's `[knowledge]` table. An application without a profile
  file now fails knowledge composition (`no knowledge binding for application <app>: no
  Application Profile at ...`). An environment that still sets `KNOWLEDGE_BINDING_IDS` is ignored
  (settings ignore unknown names); edit the profile instead.
- **`application/knowledge/gateway.APPLY_CONTRACTS` and the Biotech branch of `apply_decision`.**
  `KnowledgeGateway(binding=...)` became `KnowledgeGateway(knowledge=KnowledgePortBinding)`;
  `apply_payload.py` builds the payload from the port's contract and `intent_schema_ref`
  (`mc.knowledge_apply_payload.plan_with_exact_use.v1`, `...intent_envelope.v1`). Both payloads
  are byte-identical to before; the envelope's `schemaVersion` is now derived as
  `<contract name>.<version>`. Refusal codes are unchanged; an unknown layout refuses
  `SCHEMA_UNSUPPORTED`.
- **`bootstrap/resolution.legacy_application_profiles`, `LEGACY_APPLICATION_REVISION`** and the
  `knowledge_binding_ids` parameters of `compose_launch_resolution` /
  `compose_manifest_launch_resolver`: both take `applications: ApplicationRegistry`;
  `compose_manifest_launch_inputs` takes `application_id` (the installation's application).
- **The manifest's closed `application: Literal["biotech", "ai-engineer"]`** (v1, v2 and
  `MissionDefinition`; both JSON Schemas regenerated): now an id `^[a-z][a-z0-9-]{0,63}$`.
  Compile refuses an id without a profile in the installation (`APPLICATION_FORBIDDEN`, reason
  `application_unknown`) before the existing authenticated-application check.
- **`UNDECLARED_DATA_CLASS_STAND_IN`.** An undeclared mission is now the most sensitive class
  its lane and its application's Data Class ceiling admit (`undeclared_data_class`). Both
  installed ceilings are `internal` (engineering default), so a declared `confidential` mission
  of either application is now refused at launch (`DATA_CLASS_NOT_ADMITTED` at
  `/mission/data_class`); raise the profile's `data_class_ceiling` deliberately to admit it.
  `AgentConfiguration` v2 gains a required `data_class_source` (`declared` |
  `ceiling_default`) in its digest, without a schema bump: v2 was introduced the same day
  (R0) and nothing persists or re-validates a v2 configuration (the sealed Deep Agents node
  binding is produced per launch; Sprint OC histories are disposable, SV-D11). A v2 payload
  written before R4 (only possible from this sprint's branch commits) is not readable. The ceiling binds at resolution (Deep Agents nodes until R3), and an Application
  Binding whose hosted widening exceeds it is refused at manifest composition.
- **Biotech-named settings defaults and the module constant `settings.WORKSPACE_ROOT`.**
  `TEMPORAL_TASK_QUEUE` and the capability resource owner have no default (review B2):
  `Settings.task_queue_base` / `Settings.workspace_root` raise
  `InstallationDefaultUnavailable` unless the environment (`.env` included) or the profile
  selected by `MISSION_CONTROL_APPLICATION=<app>` supplies them; `LANGSMITH_PROJECT` defaults
  to `MissionControl` and `AGENT_SERVER_LANGSMITH_PROJECT` to `MissionControl-AgentServer-Local`.
  The configured API takes its fork-seed maintenance queue from the deployment's `temporal`
  section (`TemporalDeployment.queue_base`), the worker's source; the API and the worker
  refuse a `MISSION_CONTROL_APPLICATION` other than the binding's. Callers of `WORKSPACE_ROOT`
  use `Settings.workspace_root` (or `capability_pins.workspace_root()`). Profiles whose
  `[installation]` table supplies them (both profiles keep the previous values:
  `biotech-research-ingestion`, `BellLabsBiotech`, `BellLabsBiotech-AgentServer-Local`,
  `../../biotech`). Recovery for a local BellLabs stack: set `MISSION_CONTROL_APPLICATION`, or the
  four variables explicitly. Production workers already take their queues from the installation.

## Three lane binding slots and the R1 template bridge (OC-R2 / OVE-197, 2026-10-27)

Direct cutover (OC-D200): the operation request carries one opaque lane binding; no compatibility
reader or alias remains.

| Removed | Replacement |
| --- | --- |
| `OperationExecutionRequest.deep_agent_binding`, `.cursor_binding`, `.provider_binding` and the same three on `OperationExecutionBinding` | `lane_binding: SealedLaneBinding` (the producing lane's canonical JSON under its raw SHA-256 digest; base64 in JSON) and `lane_dispatch: LaneDispatch` (worker queue, execution generation, heartbeat class, wall-clock bound); both absent for a `native` attempt |
| `_verify_lane_pairing`'s per-runtime branches and `RUNTIME_OF_LANE` dispatch in `lane_profile_for` | **At request validation** (domain, `_verify_lane_pairing`): the profile's lane serves the runtime (`LANE_OF_PROFILE`, `RUNTIMES_OF_LANE`), a binding is present exactly for non-`native` runtimes, its profile is the operation's and its schema is one that lane produces (`BINDING_SCHEMAS_OF_LANE`). **At dispatch** (`LaneRegistry.lane_for`): the same lane check against the registered describe (`serves_runtime`) |
| `OperationExecutionRequest`'s Deep Agents authority-envelope check (identity, configuration digest, control revision, workspace, grant, reservation, runtime unit) | `DeepAgentExecutionBinding.verify_operation_envelope`. **At admission**: `OperationExecutionService.execute` / `admit_lane_session` ask the lane (`ValidatesOperationRequest`, the Deep Agents harness) before authority, budget reservation, binding or claim. **At decode**: `adapters/deep_agents/binding.py::execution_binding` repeats it wherever the lane reads its bytes. The sealed payload itself is bounded when constructed (`SealedLaneBinding.exact_payload`: the shared run-control scan of `domain/policies/payload_bounds.py` and `MAX_SEALED_PAYLOAD_BYTES`), and each lane's `carried_by` refuses a `lane_dispatch` its bytes do not state |
| `OperationWorkflowRequest` reading the Deep Agents binding's generation and the three slots' task queues | `operation.lane_dispatch.execution_generation` and `.task_queue` |
| `operation_heartbeat_class` / `segments_for` reading the typed bindings | `lane_dispatch.heartbeat_class` and `.wall_clock_s` |
| `adapters/deep_agents/template_bridge.py::deep_agent_operation_part` and `application/authoring/lane_templates.py` (`LaneTemplatePort`, `LaneOperationPart`) | `application/resolution/lane_bindings.py` (`LaneTemplateBinder`, `LaneTemplate`, `LaneTemplateCoordinates`), implemented by `adapters/deep_agents/binding.py::DeepAgentsLaneBindings` (`DEEP_AGENTS_LANE_BINDINGS`) |
| the families' direct `rebind_deep_agent_invocation` calls | `LaneRebinders.rebind(lane_binding, lane_dispatch, LaneInvocation)`, composed with the Deep Agents rebinder in `deployment_composition` and threaded through `StageGraphCoordinatorDependencies` / `GoalDirectedCoordinatorDependencies`; GoalDirected's live binding id now digests the template's sealed digest instead of its payload's `binding_id` |
| `provider_lane_composition.provider_binding_rows` | `execution_binding_rows` |
| `LANE_CONTRACTS["cursor_binding"]`; the `seal_cursor_binding` validation context; `AsyncSubagentExecution.provider_binding_follows_submission` | `LANE_CONTRACTS["cursor_execution_binding"]`; `seal_cursor`; `provider_identity_follows_submission` |

Readers that decode a typed binding call its contract (`DeepAgentExecutionBinding`,
`CursorExecutionBinding`, `ProviderExecutionBinding` `.carried_by(operation)` / `.unseal(binding)`),
which the lane adapters do; the remaining callers outside a lane package are listed in the OC-R2
report as residuals for R3. Captured Temporal histories (`tests/integration/temporal/histories/temporalio_1_30/`,
`tests/fixtures/histories/`) were migrated in place by `scripts/oc_r2_migrate_histories.py`: each
payload's typed binding was sealed by its own contract and its dispatch stated, with events and
commands unchanged; the FT-G2/G4 lane histories (`histories/ft_lanes/`) were recaptured
(`MC_CAPTURE_LANE_HISTORIES=1 pytest tests/integration/temporal/test_lane_turn.py`). Recovery: rebuild
templates from their manifests (frozen templates carrying the old slots no longer validate) and
reinstall disposable databases.

## Model profiles leave the lane bindings: the Model Catalog (OC-R6 / OVE-200, 2026-10-27)

Direct cutover: a model is one row of `deployments/<app>/models.toml` and nothing else names its
vendor or model id ([model catalog](../../../../knowledge/model-catalog.md)).

| Removed | Replacement |
| --- | --- |
| `Settings.anthropic_model` (`claude-haiku-4.5`) and `Settings.openai_model` (`gpt-5.4-nano`), never read by the lanes | the Model Catalog rows (`producer.default` ... `probe.fallback`, the PROOFS §6 pins and fallbacks) |
| `bootstrap/resolution.py::UndeclaredModelProfile`, `legacy_model_profiles`, `UNDECLARED_CONTEXT_WINDOW`, `UNDECLARED_COST` and `tests/unit/resolution/test_undeclared_model_profiles.py` (the source scan that no runtime code read a window or price) | `bootstrap/model_profiles.py::compose_model_catalog(root, app)`; `compose_launch_resolution` / `compose_manifest_launch_resolver` take `models=`; `compose_manifest_launch_inputs` loads the installation's catalog (a test passes `models=`) |
| `mc.manifest_launch_bindings` `model_profiles.<name>` as a `DeepAgentModelComponent` (`ref`, `provider`, `model_name`, `settings`) | `DeepAgentModelBinding` (`ref`, `settings`): a reference keyed by the catalog profile; an entry still stating `provider` or `model_name` is refused at load. Remove those two keys from an operator file; bind catalog profile names |
| the deployment-binding vendor/model mismatch check in `DeepAgentsCompileAdapter._model` | the compile seals the resolved pin's vendor and model id; `DeepAgentsDeploymentFacts.from_bindings(..., models=)` pairs each binding with its row and refuses an uncatalogued profile |
| `model_factory_for(pin.provider)` per pinned model in `build_deployment_capability_registry` and the Agent Server's `hosting_registry`; a pin file `models[]` entry without a model id; registered model factories that silently replaced a pinned one | `materializer.ExactModelFactory(served_vendor, served_model_id)` per pinned definition, dispatching on the sealed binding's vendor and refusing another vendor or model id; `PinnedModel.model_id` is required (the pin file now pins one definition per catalog model); `DeploymentCapabilityComponents.model_identities` for registered factories, `MODEL_FACTORY_COLLISION` unless `qualification=True` |
| `domain/capabilities/features/anthropic.py`, `openai.py`, and `AGENT_FEATURES` in `domain/capabilities/features` | `adapters/deep_agents/routes.py` (`ANTHROPIC_MODEL_TOOLS`, `OPENAI_MODEL_TOOLS`, `VENDOR_FEATURES`, `AGENT_FEATURES`, `DEEP_AGENTS_MODEL_ROUTES`); the domain keeps `LANE_FEATURES` (the `deep_agents.*` rows). `provider_options.deep_agents.model_tools` keep the authored selection; the manifest compile refuses an unknown or misconfigured entry through the lane's `ChecksLaneOptions` (blocker `provider_options_invalid` at `.../provider_options/deep_agents/model_tools/<vendor>/<name>`), and the launch validates them again |
| `MISSION_CONTROL_ASYNC_TECHNICAL_CHILD_MODEL`, `TECHNICAL_CHILD_MODEL` and the OpenAI-only child settings | the installation's `child.default` row (`TECHNICAL_CHILD_MODEL_PROFILE`; the Agent Server needs `MISSION_CONTROL_APPLICATION`, and `ANTHROPIC_API_KEY` for the pinned Haiku child); `technical_child_definition(model=)`; settings per vendor (`TECHNICAL_CHILD_MODEL_SETTINGS`). The served graph digest changes with the row: re-author `deep_agents_async_graphs` with `missionctl lane async-graphs` |
| readiness `AUTH_SECRET_ENV_UNDECLARED` at `#/model_profiles/<name>/provider` | the same code at `#/model_profiles/<name>` for the catalog row's vendor, plus `MODEL_PROFILE_UNCATALOGUED`, `MODEL_CATALOG_UNAVAILABLE` and `MODEL_PIN_VENDOR_MISMATCH` (the pin file's `models[].provider` against the row's vendor, also refused at composition and by the worker's factory) |

The test fixtures keep the fixture profile names `frontier.*`, which the installed catalogs do
not declare: a deployment file binds catalog names. (OC-R7 renamed the deployment examples' and
cognition profiles' names to catalog rows; see the R7 section below.) The provider
and Cursor lanes' `providers.<profile>.model_profiles` (`ModelPin` with a lane-specific model id)
are unchanged here; they move with those lanes (R3 and the post-sprint provider sweep).
Recovery: restore the two settings fields or the vendor keys from the R6 base `01ac23f7`.

## Lane-owned describes, writers and runtime modules (OC-R3 / OVE-202, 2026-10-27)

Mechanical relocation (OC-D199, design D11): no behavior changes for a lane other than Deep Agents,
except that the hook scripts became lane-neutral (below). Nothing is shimmed.

| Removed | Replacement |
| --- | --- |
| The nine declared matrices in `application/execution/harness/describe.py` (`DEEP_AGENTS_DESCRIBE`, `CURSOR_*_DESCRIBE[_V1]`, `CLAUDE_AGENT_SDK_DESCRIBE`, `CODEX_DESCRIBE`, `CLAUDE_CLOUD_DESCRIBE`, `CODEX_CLOUD_DESCRIBE`, `CLAUDE_MANAGED_DESCRIBE`, `CODEX_AGENTS_DESCRIBE`, `DEEP_AGENTS_SUBAGENT_FIELDS`, the Claude/Codex version constants) | Each lane package's `describe.py` (`adapters/{deep_agents,cursor,claude,codex,anthropic_managed,openai_agents}/describe.py`), byte-identical (every describe digest unchanged), beside the lane's `LaneDeclaration` (model routes, item and family support, pins). `describe.py` is the aggregator (`DECLARED_LANES`, `DECLARED_LANE_MATRICES`, `declared_lane`, `declared_matrix`, `MISSION_V1_LANE_PROFILES`, `LAUNCH_BLOCKED_EVIDENCE`, `DESCRIBE_ONLY_LAUNCH_EVIDENCE`), the one application module allowed to import the lane describe modules (domain-only data, enforced by `tests/architecture`) |
| `adapters/deep_agents/compile.py::DEEP_AGENTS_DECLARATION` (definition) | `adapters/deep_agents/describe.py` (compile imports it) |
| `adapters/claude/describe.py::CLAUDE_AGENT_SDK_LANE_DESCRIBE`; `adapters/codex/describe.py::codex_local_describe`, `CODEX_LOCAL_DESCRIBE` | `CLAUDE_AGENT_SDK_DESCRIBE`; `adapters/codex/protocol.py::codex_local_describe` |
| `provider_launch.REQUIRED_PINS`, `MODEL_PROVIDER` | `required_pins(profile)` (the declaration's `pins`) and `model_vendor(profile)` (its native route) |
| `manifest_v2_admission.AGENTIC_BEHAVIORS`, the literal `V2_LANE_BEHAVIORS` table, `EVIDENCE_BLOCKED_HOSTED`, `HOSTED_EVIDENCE`, `DESCRIBE_ONLY_HOSTED`; `manifest_service.CURSOR_BEHAVIORS` and the literal `LANE_BEHAVIORS` | `lane_behaviors(profile)` from the declaration's `families` (`FAMILY_OF_BEHAVIOR`); `V2_LANE_BEHAVIORS` / `LANE_BEHAVIORS` are derived per `Lane`; the aggregator's evidence maps |
| `render_host_files` and its lane switch, the per-lane writers (`_deep_agents`, `_cursor`, `_claude`, `_codex`, `_codex_cloud`, `_hosted_agent_api` and their one-lane helpers) | `HostProjectors.render(...)` (same parameters, `application/agentic_components/projections.py`) over each lane package's `host_files.py` (`HOST_FILES`, a `LaneHostFiles` per profile; the hosted agent APIs' writer is `adapters/remote_session/host_files.py`), composed once in `bootstrap/host_projection.py::HOST_PROJECTORS` and passed to `RenderedProjectionSource`, `materialization_digest(..., projectors=)`, the catalog render preview, cursor launch and placement |
| `hook_runner.native_output`, `signal_hook.native_gate_output(lane, ...)` per-lane tables; `application/signals/gates.py::native_answer` (no caller) | Each lane's stdlib `adapters/{cursor,claude,codex}/hook_output.py`, placed by its writer as `.mission/hooks/native_output.py`; `run.py` and `signal` load it from their own directory. Golden projections regenerated (`run.py`, `signal`, `native_output.py`, `_projection.json`) and the Claude CLI discovery fixture re-recorded (projected files gain `native_output.py`; discovery unchanged) |
| `application/execution/harness/codex_usage.py`, `cursor_usage.py`, `cursor_costs.py`, `cursor_bridge_recovery.py`, `deep_agents_harness.py` | `adapters/codex/usage.py`, `adapters/cursor/usage.py`, `adapters/cursor/costs.py`, `adapters/cursor/bridge_recovery.py`, `adapters/deep_agents/harness.py`; the lane-neutral run aggregation is `application/execution/harness/native_run_usage.py`, and `lane_turns` asks `NativeRunUsageLane` / `CancelledCloseLane` (`harness/protocol.py`) instead of naming Cursor or Codex. `OperationExecutionService` no longer defaults its registry to a Deep Agents harness: callers pass `lanes` |
| The `claude_managed` budget-gate checks (`workflows/budget_controls.py`, `goal_directed.py`, `lane_turns`, `operation_execution.verify_budget_control`, `harness/budget_controls.py`) and the Cursor cost child's `execution_runtime == "cursor"` (`workflows/operation.py`, `operation_execution`) | `LaneDispatch.boundary_controls` (`budget_gate`, `external_cost_settlement`), stated by the lane's binding (`ProviderExecutionBinding.lane_dispatch` for Managed options, `CursorExecutionBinding.lane_dispatch`) and read deterministically from the request; the Managed ceiling is `ProviderExecutionBinding.budget_gate_ceiling()` |

Every lane package registers (`bootstrap/lanes.SESSION_LANES`, the packages' `lane.py::LANES`) with
the describe-only compile (`application/resolution/describe_only.py`); the launch author
registers all nine profiles and admits provider and Cursor nodes through
`RuntimeResolver.admit` (lane, application, declared vendor route, Data Class against the lane
policy and the application ceiling, family). Recovery: rebuild templates from their manifests;
an in-flight Managed or Cursor request captured before this change lacks the dispatch's
`boundary_controls` and is refused when its lane decodes it (histories are disposable, SV-D11).
Workflows started before R3 are not replay-compatible (no `workflow.patched` guard and no
lane-name fallback, OC-D200): drain or terminate them before upgrading a worker.

## Sprint OC R5: KS backend registration (2026-10-27)

Direct cutover in the Knowledge Services repository (KS `sprint-oc` @ `0978a85`, OVE-199); Mission
Control's K01 wire and describe output are unchanged
([Knowledge Services boundary](../../../../knowledge/knowledge-services.md#backend-registration-on-the-ks-side-sprint-oc-r5)).

| Removed | Replacement |
| --- | --- |
| The nullable sub-ports on KS `KnowledgeOperationBackend` (a backend left a port `null` when it did not serve it, and `servedCapabilities()` inferred the served set from the nulls) | `capabilities` plus the throwing accessors `research()`, `apply()`, `delivery()`, `effects()` (`native_receipt_lookup`) and `revocation()` (`BackendCapabilityMissing` for an undeclared one), built by `composeBackend`; `BackendDescriptor.conditionalCapabilities` (AI Engineer `apply` is conditional on `host_injected_apply_port`); `readback` stays in the vocabulary with no accessor, so no backend can declare it |
| The per-binding backend factories in the KS host (`packages/host/src/knowledge-operation/backends.ts`, design §9.2) | each binding package exports its `BACKEND`; `BackendRegistry` over each binding package's `BACKEND: BackendRegistration` (`packages/host/src/knowledge-operation/registry.ts`); an unknown binding is `UnknownBinding`, a descriptor mismatch `BINDING_DESCRIPTOR_MISMATCH` |
| `createKnowledgeOperationSurfaceFromEnv(env)` without a registry | `createKnowledgeOperationSurfaceFromEnv(env, injection)` requires `injection.registry`: a caller composing the surface passes the registry of the binding packages it serves |
| The `mc.knowledge_request.v1` envelope and the older Biotech path | Deleted with OC-D202 ([older Biotech knowledge path retirement](#older-biotech-knowledge-path-retirement-2026-10-27)); K01 is the only protocol |

Mission Control's offline drift guard is `tests/conformance/applications/ks_backend_descriptors.json`
(a hand copy of each `BACKEND.describe()`, KS commit recorded); refresh it when a KS binding's
describe changes ([operator guide](../../../../MISSION_CONTROL_LOCAL_API.md#application-profiles-and-the-model-catalog-sprint-oc)).
Recovery: the KS commit before the cutover restores the sub-ports; no Mission Control file depends on them.

## Sprint OC WI-03: trusted assessment and use review (OVE-165, 2026-10-27)

| Removed | Replacement |
| --- | --- |
| `InMemoryUseDecisionStore` composed by `bootstrap/composition.py` for `knowledge_apply` | `PostgresUseDecisionStore` (`adapters/postgres/knowledge/use_decisions.py`; release 1.7.0 migration `0059_recorded_use_decisions`); the in-memory class remains for unit proofs only |
| Anyone with `assessor`/`host` access could supersede an assessment | `record_assessment` refuses supersession unless the trusted bridge cites a KS successor chain of the superseded assessment's decision |
| `reference` in `DEFERRED_FORMS` (`FORM_NOT_YET_FULFILLABLE`) | `REFERENCE_USE_UNPROVEN` until the `reference_uses` port names current official-use evidence |
| `FAMILY_INPUT_REQUIRED` for dependent stages | `DEPENDENT_INPUT_REQUIRED = True` (next-iteration predecessors keep `FAMILY_INPUT_REQUIRED = False`) |
| KS blanket exclusion of recommendations/forecasts from official coverage | KS judgment policies (`catalog/research/judgment-policies.json`): a typed judgment basis, independent support and a required review; never entailment |

Recovery: the sprint-oc commit before WI-03 restores the in-memory decision store and the deferred
reference form; old experimental rows are disposable (OUTPUT-CONTRACTS §1).

## Review fixes and residuals (OC-R7 / OVE-201, 2026-10-27)

| Removed | Replacement |
| --- | --- |
| `RuntimeSelection.requirements` (never set, never read) | none: the manifest's `requires` stays admitted by `domain/execution/lane_requirements.admit_requirements` |
| A run-control `Contract` skipping a nested dict's payload scan because it had the four sealed-binding keys | the skip only when the payload decodes and hashes to its `digest`, scanning the decoded bytes (`domain/resolution/sealed.verified_serialized_binding`); otherwise the dict is scanned as data |
| `application/resolution/registries.describe_only_registry(cursor_bound=..., claude_bound=..., ...)` for the API and tests | `bootstrap/lanes.describe_only_registry(bound=..., allow_unqualified=..., registrations=...)` with `bound_lane_profiles(...)` / `settings_bound_lanes(settings)`; the lane-neutral half is `registries.describe_only_lanes`. The boolean form remains only for the placement caller in `bootstrap/manifests.py` until that file moves to the bootstrap function |
| `frontier.default`, `frontier.long_context`, `frontier.anthropic_haiku` in `deployments/examples/manifest-launch-bindings*.json` and `deployments/cognition-profiles/*.mission.yml` | Model Catalog rows: `producer.default` (the WP-CP-040 qualification slot `model.wp-cp-040`), `producer.fallback` (`model.claude-haiku-5-5` in the Deep Agents example); `frontier.long_context` is dropped (no catalog row). An operator file copied from an example renames its keys the same way |
| Seed `mc.app.<app>.agent-skills@1.0.2` as the current successor | `@1.0.3`: `skill.mission-control-author` 0.3.2 (Model Catalog authoring guidance) as revision 4; 1.0.2 frozen, its sources under `packages/mission-control-db-contract/bundle-sources/agent-skills-1.0.2/` |

Recovery: the R7 base `e66377a5`. The recorded residuals are rows in
[SELECTION-AND-ROUTING-INTERFACES §8.1](../../provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-INTERFACES.md#81-recorded-residuals-r7-review-2026-10-27).

## Unsupported behavior and release gates

This source cleanup does not implement a generic mission retry command, expanded
instruction injection or all new workflow types. Existing mapped controls retain
their explicit acceptance/delivery/apply semantics; unsupported requests fail rather
than receiving invented success.

The common component is implemented, qualified on two local disposable databases and
installed in both Supabase projects (owner-approved 2026-10-03; additive only — the
legacy `capability_search` data is untouched and remains under separate persistent-data
authority). Still separately approved: runtime login roles, storage, Agent Server
topology and license, and a verified recovery point. Live Supabase/storage policies, executable read-only mounts, production
hosted Agent Server durability and paid-provider behavior require their own evidence.
See [implementation status](MISSION_CONTROL_IMPLEMENTATION_STATUS.md) and
[operator setup](../../../../MISSION_CONTROL_LOCAL_API.md).

## Documentation verification

The standalone `docs/knowledge/` bundle follows the neighboring Biotech catalog's
minimal Open Knowledge Format v0.1 profile. The existing dependency-free validator
passed all eight concepts; a separate check resolved every concept/source/test
Markdown link and checked root/source AGENTS.md files remain below 8 KiB.
These structural checks do not prove runtime behavior. Post-organization
verification passed: fresh locked regression 1,343 passed / 23 skipped / two expected
failures / zero failures, plus the separately passed eleven unchanged end-to-end
cases. Final lint, core/optional typing and both isolated wheel checks passed.
See the implementation status for exact exclusions, the recovered first-run
failures and non-additive focused selections.
