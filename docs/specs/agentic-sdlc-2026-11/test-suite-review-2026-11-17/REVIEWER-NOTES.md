---
type: Working Notes
title: "Test suite review 2026-11-17: reviewer notes per slice"
description: "The ten reviewer write-ups behind RECOMMENDATION.md: canonical doubles, exact builder names to move out of test modules, patterns and gaps per slice of tests/."
tags: [mission-control, tests, sdlc]
---

# Test suite review: reviewer notes per slice

Working notes behind [RECOMMENDATION.md](RECOMMENDATION.md). Each section is one slice of `tests/`, written by one reviewer against the shared rubric; per-file verdicts are in [verdicts.tsv](verdicts.tsv). Claims here are **reviewed**, not re-verified, unless RECOMMENDATION.md says so; one claim in slice G (that the kernel imports `biotech_mission_adapters`) was checked and is wrong.

## A-fixtures


Scope: 126 Python helper files (tests/fixtures/**/*.py, tests/conftest.py, tests/schema_context_helpers.py; about 36k lines in tests/fixtures top level) and 30 fixture data directories. These are helpers, not tests, so they hold no test functions. The verdicts decide what the rest of the suite may keep importing.

### Counts

| | KEEP | REWRITE | MERGE | DELETE |
|---|---|---|---|---|
| Python helpers (126) | 62 (16 are projection golden files, 5 are recorders/regen) | 51 | 11 | 2 |
| Data dirs (30) | 25 | 4 (rename sprint-oc-w1/w2/w3/w5) | 0 | 1 (codex/schema 0.162.0) |

- 13 of the REWRITEs are a relocation, not a rewrite: the qualia+aieng cluster (8.6k lines) is the owner's paid knowledge-loop driver (Build 08), not a test helper. Move it to `experiments/knowledge_loop/`. Do not delete it, because loops 7 and 8 are still awaiting review. Its only test consumers are `tests/unit/test_qualia_*.py` and `test_aieng_*.py`, which test the fixture itself.
- 16 overnight_* modules (4.5k lines) support live acceptance cases on the Deep Agents path (held report blocks the consumer, saved consumer survives a worker restart, lost-ack redelivery starts one consumer, source correction after seal). Verdicts: merge the scripted cognition into `models.py`, merge the probes into `scenarios/{stagegraph,goal_directed,linked}.py`, and delete only the readable-evidence rendering (`overnight_config_readable`) and `stage2_outputs`.

### Target layout: tests/support/ (one module per real boundary)

| Module | Becomes canonical from | Real boundary it replaces / why it must exist |
|---|---|---|
| `ids.py` | `canonical_scope/tenant_id/catalog_scope` from mission_control_common_db, the SCOPE/INSTALLATION/TENANT constants in lane_turns, provider_frames and rrm009_production_stack, plus one `Clock` | Ids and wall clock. Today 3 different SCOPE UUID sets exist, and 25 importers (17 unit tests) import the DB module only for scope strings. There are 21 local `*Clock` classes (15 `Clock`, 2 `StepClock`, 2 `MutableClock`, `SteppingClock`, `FakeClock`). |
| `db.py` | `mission_control_common_db.py` (+ db_env, tcp_proxy) | Disposable PostgreSQL with the released common component and role logins (REAL-INFRA). It is the only way to prove migrations, RLS and roles. |
| `temporal.py` | `temporal_history.py` + `operation_activities.py` + `FixtureChildWorkflow` from tests/integration/temporal/test_linked_runs.py | WorkflowEnvironment helpers, history inspection and activity stubs. Workflow tests must stub activities, never internals. |
| `stack.py` | `mission_control_production_stack.open_postgres_production_stack`, absorbing rrm009_production_harness.ProductionStack (inspection), scoped_api_stack.ScopedStack (signed mode), overnight_read_api and prerequisite_preflight | The production API and worker over real PG and Temporal. Today there are 4 overlapping stack builders (4.6k lines incl. mp20 ParityStack). One stack with modes (`signed=`, `saver_proxy=`, `lanes=`) is enough. |
| `models.py` | `_LoggedModel` from rrm009_production_stack as the single `ScriptedChatModel(script=...)`; checkpoint fault hooks (`before_call/fail_on/gate_on`) from checkpoint_recovery.ScriptedRecoveryModel; the model-catalog half from fixtures/models.py | The LLM. 26 BaseChatModel subclasses across 29 test files today. A script should be data (a callable from observed messages to reply), not a subclass per sprint, and never an env-var branch. |
| `deep_agents.py` | `exact_fixture/skill_bundle/registry/unit_bound/planned_invocation` from tests/acceptance/control_plane/test_wp_cp_040.py, `TechnicalBinding/TechnicalCatalog/publish_technical_catalog/blueprints` from rrm009_production_stack, and `RecoveryHarness/CrashingSaver` from checkpoint_recovery | Builds an exact, sealed Deep Agents binding and the governed recovery harness. It is the owner's main path, and its builder currently lives inside an acceptance test. |
| `lanes.py` | `ScriptedSessionLane` (lane_turns) absorbing mp06_lanes/mp12_lanes as modes; `lane_fields` (lane_bindings); compositions from cursor_controls, managed_lane, agents_lane, discovery_lanes | The provider session (SessionLane protocol). Exactly one fake lane, plus one boundary fake per provider API (next section). |
| `knowledge.py` | `FakeKnowledgeBinding` + `knowledge_http_app` + `Issuer` (knowledge_binding), `TrustedKnowledgeDouble` (trusted_knowledge), `install_scripted_trusted` (overnight_trusted), `ScopedBridge` (native_receipt_selection) | Knowledge Services, over the real `HttpKnowledgeBindingClient` and real credential verification. The six InMemory* knowledge stores move to src next to their ports. |
| `builders.py` | run-control and operation builders out of test_run_control / test_operation_execution; checkpoint_lineage builders and contract asserts; runtime_inspection seed world; registration builders (`fresh_registration/model_content/model_report`) | Pure value builders. Today 150 files import a test module to get them. |
| `settings.py`, `processes.py`, `catalog.py`, `frames.py`, `schema.py` | isolated_settings; owned_process + validation_restart_worker; catalog/fast_track_catalog + projections/rows + capability_search_catalog; provider_frames + transcripts; schema_context_helpers | Small helpers that already exist. They are renamed by behaviour. |
| `scenarios/` | stagegraph.py, goal_directed.py, linked.py, async_children.py (rrm009_cancellation, rrm013_live_stack), knowledge_watch.py (aieng_watch_tools) | Multi-step scenario drivers for the acceptance tests that stay. They are named by behaviour, not by sprint. |

### Canonical doubles (one per boundary)

- **Provider APIs (keep one each):** Cursor Cloud = `tests/fixtures/cursor_cloud.py::FakeCloudApi`; Cursor local = `cursor_local.py::ReplayBridge`; Anthropic Managed = `managed_agents.py::FakeManagedAgentsApi`; OpenAI Agents = `tests/unit/openai_agents/support.py::FakeAgentsApi` (move it into support; agents_lane only subclasses it); Codex = `tests/unit/codex/fixture_app_server.py::FixtureAppServer`; Claude SDK = `tests/unit/claude/fixtures.py::FixtureClient`. mp20_parity wraps all six again as Responder* subclasses. Fold that into script options.
- **Agent Server / Agent Protocol:** `fake_agent_protocol.py::FakeAgentProtocolClient`. For a real server, use `mission_control_local_agent_server.py` and `wi23_sealed_child_hosting.py`.
- **MCP:** `rrm009_mcp_server.py` (stdio server with a large result) and `projections/discovery/mcp_stub.py`. These are real processes, not mocks.
- **Embeddings:** `capability_search_catalog.py::DeterministicEmbeddings`.
- **Port fakes to fold:** `checkpoint_recovery.MemoryOperationJournal` goes into src `InMemoryAtomicOperationJournalRepository` (check the API first). `AcceptingAuthority` goes into src `ConformanceAuthority`. The 3 `MemoryArtifacts` copies (cursor_local, tests/unit/codex/support.py, tests/unit/workspaces/workspace_fixtures.py) become one. `continuation.FakeStaging` and `knowledge_binding.InMemoryStaging` become one content-addressed staging. `output_contracts.InMemoryOutputContractStore` (499 lines), the six knowledge stores and `workspace_closures.InMemoryWorkspaceClosures` move to src as `InMemory*`, each pinned by a contract suite that also runs against the Postgres store. `checkpoint_lineage.assert_*_repository_contract` is the model to copy.
- **INTERNAL-MOCK to shrink:** `lane_bindings.FakeSealedBinding` lets unit tests pass a SimpleNamespace as a "sealed" binding. Replace those uses with the real exact-binding builder.

### Builders that must leave test modules (traced cross-imports)

- `tests/unit/run_control/test_run_control.py` (150 importers): `service` 91, `request` 81, `command` 75, `actor` 58, `WORKFLOW_DIGEST`, `NOW`, `ALL_PERMISSIONS`, `ConfigurationVerifier`, `EMPTY_EVIDENCE_DIGEST`, `INITIAL_EVIDENCE_FRONTIER`, `reconciler_command`, `operator_wait`, `reconcile`. These move to `builders.py`. Fixture importers: checkpoint_recovery, cursor_controls, goal_directed_journaled, rrm009_production_stack, rrm013_live_stack, run_forks, runtime_inspection.
- `tests/unit/operations/test_operation_execution.py` (50): `operation_request` 47, `MCP_DIGEST`/`SKILL_DIGEST` 8, `service_fixture`, `_workflow_request`. These move to `builders.py`. lane_turns imports them at module top and inside `cursor_operation`, so all 112 lane_turns consumers transitively load a 1,557-line test module. The same applies to checkpoint_recovery, goal_directed_journaled, managed_lane, agents_lane, rrm009_production_stack and rrm013_live_stack.
- `tests/acceptance/control_plane/test_wp_cp_040.py` (36): `exact_fixture` 34, `registry`, `unit_bound`, `planned_invocation`, `SkillReadingModel`. These move to `deep_agents.py`. They are imported lazily by checkpoint_recovery and goal_directed_journaled, and at top level by rrm009_production_stack.
- `tests/integration/temporal/test_manifest_launch_production.py` (16): `host_pins` 15, `missions_app`, `submit`, `post`. These move to `manifest_runtime.py`. Users: qualia_stagegraph, aieng_stagegraph, mp20_parity.
- `tests/acceptance/mission_control/test_overnight_stagegraph.py` (`run_stagegraph_fixture`, `stagegraph_manifest`, `production_lifecycle`) and `test_overnight_goal_directed.goal_manifest` move to `scenarios/`.
- Smaller cross-imports, each moving to the named module:
  - `tests/unit/harness/test_hosted_agent_api_profiles.py` (`AGENTS`, `MANAGED`, private `_hosted_binding`) to lanes.py.
  - `tests/unit/knowledge/test_native_write.py` and `test_knowledge_tools.py` to knowledge.py.
  - `tests/integration/deep_agents/test_report_source_real_service.response` to knowledge.py.
  - `tests/integration/postgres/test_completion_validation_postgres.recompose`, `tests/unit/orchestration/test_artifact_schema_validation` and `test_completion_validation_service.OUTPUT` (used by validation_restart_worker) to builders.py.
  - `tests/integration/temporal/test_manifest_v2_provider_launch` (`AUTH_PROFILES`, `_PayloadInputs`, `provider_lane`) to lanes.py.

### Patterns

- **Good:**
  - Contract assertions shared by the in-memory and PG suites (`checkpoint_lineage.py`, `hook_contributions.py`, `runtime_inspection.py`).
  - `isolated_settings.py` builds Settings with no .env leakage.
  - Provider fakes behind `httpx.MockTransport` drive the real adapter (`cursor_cloud.py`, `managed_agents.py`).
  - `knowledge_binding.http_client_over` runs the real HTTP client over the fake.
  - Replaying captured Temporal histories against the production workflows (`histories/` + test_replay_histories).
- **Bad: env-switched scripts inside a shared model.** `rrm009_production_stack.TechnicalModel` branches on `MISSION_CONTROL_TECHNICAL_KNOWLEDGE` and `MISSION_CONTROL_TECHNICAL_AIENG_WATCH`, and lazily imports knowledge_binding and aieng_watch_tools. Every new mission adds a branch to one model.
- **Bad: evidence writers in fixtures.** `stage2_outputs.write_outputs` and `overnight_*_evidence.export_*` write owner-readable packets. Keep the gap assertions and drop the files.
- **Bad: global and filename-keyed config.** `tests/conftest.py` loads `pytest_plugins = ["tests.fixtures.agent_server_block_c"]` for the whole suite, and it keys the Windows selector loop off a hard-coded list of 42 file names (mostly sprint-named). Any rename silently breaks psycopg on Windows. Replace the list with a marker.
- **Bad: src points into tests/.**
  - `adapters/codex/protocol.SCHEMA_FIXTURE_DIR` points at tests/fixtures/provider_frames/codex/schema-0.162.1.
  - `application/environments/bootstrap.py` uses `tests/fixtures/projections/...` as evidence refs.
  - `packages/mission-control-db-contract/seeds/agent_skills.py` and `agent_capabilities.py` use `tests/fixtures/skills/*` and `tests/fixtures/mcp/*` as custody sources for real seeds.
  - These are production inputs, so move them out of tests/.
- **Bad: tests of fixtures.** tests/unit/test_qualia_*.py, test_aieng_*.py and test_overnight_*.py (21 files, 147 test functions) mostly verify the helper modules themselves. They go with their helpers.

### Deep Agents path: essential protection in this slice

- `rrm009_production_stack` together with the stack modules carries the deterministic technical Deep Agents model on the production API/worker over PG and Temporal (43 consumers).
- Supporting pieces:
  - `manifest_runtime` (manifest, compile, launch).
  - `catalog/fast_track_catalog` + `tests/golden/manifests` + `manifests/fast-track` (compile resolutions).
  - `lane_bindings` (sealed binding into lane dispatch).
  - `checkpoint_recovery` (crash windows behind the operation boundary).
  - `goal_directed_journaled` (GoalDirected).
  - `histories/` (workflow replay determinism).
  - `mission_control_local_agent_server` + `wi23_sealed_child_hosting` + `fake_agent_protocol` (async children).
  - `continuation_graph` (compaction).
- Gaps:
  1. The canonical exact Deep Agents binding builder is `exact_fixture` in an acceptance test file. A support module needs to own it before anything is deleted.
  2. No contract suite pins the in-memory knowledge stores or `InMemoryOutputContractStore` against their Postgres adapters, though both sit on settlement.
  3. The scripted Deep Agents model has no stable script API, so a cognition change means editing a 1,368-line fixture.
  4. Behaviours carried only by sprint-named acceptance drivers (overnight_*, rrm009_cancellation) are at risk in a rename-only cleanup. Move them into `scenarios/` before deleting any sprint test.

### Uncertain calls for the coordinator

- The qualia/aieng cluster: relocate (my call) or delete outright? It depends on whether the owner still runs the paid drivers after the Build 08 review. `tests/unit/authoring/test_schema_only_stage_inputs.py` and `tests/integration/postgres/test_manifest_fork_admission.py` (via qualia_fork_contract) are real tests that depend on it and need their own small fixtures first.
- `mp20_parity.py`: keep a workflow-level all-lanes parity if `tests/conformance/lanes` does not drive Temporal workflows; otherwise delete. I did not verify which.
- `agent_server_block_c.py`: the Block C graphs are still registered in `agent_server/langgraph.json`. The live drills' fate belongs to the agent_server slice.
- `live_models.py`: delete with the paid tracing drill if that drill goes.
- `overnight_linked_biotech.py`: may duplicate the AI Engineer linked variant.
- The `MemoryOperationJournal` to src journal fold assumes API parity (`commit/get_claim/get_settlement`, `record_reconciliation_applied`). Check this before merging.
- `tests/fixtures/provider_frames/codex/schema/` (0.162.0): delete it, and also fix the three docstrings that still name it. Codex integration drills still report `app_server_schema_version v2@0.162.0` in payloads, which is string data only.

## B-ops-orchestration


110 files, about 833 test functions (metrics regex count).

| Verdict | Files | Approx. tests |
| --- | --- | --- |
| KEEP | 65 | 457 |
| REWRITE | 34 | 336 |
| DELETE | 7 | 35 |
| MERGE | 4 | 5 |

Most REWRITEs keep every test. They need the shared builders moved out of `test_*.py` modules (TEST-AS-LIBRARY), and in a few files internal monkeypatches replaced. Only a handful of files need test logic changed: d39, cancel_delivery_race, fork_human_gate_admission, closed_workflow_postgres_authority, async_child_parent_completion, rrm_009 and bounded_queued_turn.

### Canonical doubles this slice needs

- **Scripted chat model** (boundary: the LLM).
  - Keep `ScriptedRecoveryModel` in `tests/fixtures/checkpoint_recovery.py`.
  - Fold in its subclasses `RecordingModel` (test_ft_f2), `FailingQueuedModel` (test_bounded_queued_turn) and `GoalScriptedModel` (`fixtures/goal_directed_journaled.py`) as options or subclasses that live in that same fixture.
  - Why it is needed: it drives a real `create_deep_agent` graph deterministically. This is the main Deep Agents double.
- **Conformance runtime and ports** (boundary: provider runtime, sandbox, secrets, MCP/asset digests).
  - Keep `src/mission_control/adapters/operations/conformance.py` `Conformance*`, the src canonical set, used by `service_fixture`.
  - No duplicates in this slice.
- **Operation journal repository** (port: `OperationJournalService` repository). There are three copies:
  - `MemoryOperationJournal` in `tests/fixtures/checkpoint_recovery.py`
  - `RejectionJournal` in `tests/unit/operations/test_lane_admission_rejection.py`, which adds crash flags
  - src `InMemoryAtomicOperationJournalRepository` in `application/execution/operations/operation_journal.py`, which is richer and also models run versions and budgets.

  Keep one. Prefer the src class if `seed_run` is cheap enough for these tests; otherwise keep `MemoryOperationJournal` and add `crash_claim`/`crash_settlement` flags to it. Pin it with a contract test against the PG journal.
- **Coordinator-level journal** (port: `OperationExecutionJournalPort`, acquire/settle). `FakeJournal` and `LoseWorkerBeforeSettlement` in `test_operation_execution.py` duplicate what `JournaledOperationExecutionCoordinator(OperationJournalService(<canonical repo>))` gives for real. Replace them with that composition plus a crash wrapper.
- **Context pack ports** (artifact contents, selection records, staging). No src InMemory exists. Keep `FakeArtifacts`/`FakeSelections`/`FakeStaging` from `test_ft_b2_stage_handoff.py`, which 6 files already import, and move them to `tests/support/context_pack.py`.
- **Artifact custody** (port: captured-output custody reader). Keep `Custody`/`captured` from `test_artifact_schema_validation.py` and move them to `tests/support/artifact_custody.py`. Fold `ScopedCustody` (test_goal_schema_completion) into it.
- **Frame store** (port: FrameStore/FrameReader). Keep src `InMemoryFrameStore` (`application/frames/sink.py`). Fold `FakeFrames` (test_point_reconciliation) into it.
- **Session hydrator** (boundary: lane session restore).
  - Keep `FakeHydrator` in `tests/fixtures/mp12_lanes.py`, renamed `continuation_lanes.py`.
  - Fold in the duplicates `FakeHydrator` (continuation/test_hydrator_registry, operations/test_continuation_service) and `Hydrator` (operations/test_continuation_activities).
- **GitHub and git** (boundary: GitHub REST plus remote). Keep `tests/unit/effects/support.py` (`FakeGitHub` over `httpx.MockTransport`, a local bare remote, `StaticCredentials`). Move `NoCredential` (test_hosted_bundle_publication) into it.
- **Temporal client history** (boundary: Temporal client). `Client`/`Handle`/`history` in `recovery/test_closed_workflow_temporal.py` are acceptable. For workflow logic, use `WorkflowEnvironment.start_time_skipping` instead of patching `temporalio.workflow.*`, which test_d39_claim_held_retry and test_operation_cancel_delivery_race do today.
- **StageGraph run builder** (real `RunControlService` over `InMemoryRunControlRepository`, `FamilyAdmissionRegistry` plus stagegraph mutations, `StageGraphDecisionService`). Four near-copies:
  - `prepared` in test_completion_validation_service
  - `fixture` in test_human_gate_budget_admission
  - `prepared` in test_budget_admission_failure
  - `harness`/`admission` in test_stagegraph_parallel_admission_binding

  Make one `tests/support/stagegraph_run.py`. These are real src services, not fakes.
- **Asyncpg fakes**: `Connection`/`Pool` in recovery/test_closed_workflow_postgres_authority, test_terminal_frame_fencing, test_terminal_turn_usage and test_terminal_adoption_readers match SQL strings. They are INTERNAL-MOCKs. Remove them; the real-PG integration tests already exist.

### Shared builders that must move out of test modules

- `tests.unit.operations.test_operation_execution` (50 importers) -> `tests/support/operations.py`:
  - `operation_request` (47 importers), `MCP_DIGEST` (8), `SKILL_DIGEST` (8), `service_fixture` (4), `_workflow_request` (3), `DIGEST` (2), `exact` (2).
  - Also move `NOW` and `SECRET_VALUE`, which the builders need.
  - `operation_request` itself depends on `tests.unit.run_control.test_run_control` only through the test bodies, not the builder, so it moves cleanly.
  - Importers include fixtures (`checkpoint_recovery`, `goal_directed_journaled`, `lane_turns`, `managed_lane`, `agents_lane`, `rrm009_production_stack`, `rrm013_live_stack`), `tests/unit/claude/fixtures.py`, `tests/unit/codex/support.py` and integration/acceptance files. After the move, every fixture module stops importing a test module.
- `test_rrm_016_goal_directed_settlement` (14 importers) -> `tests/fixtures/goal_directed_journaled.py`: `_preparation`, `_claim`, `_composition`, `_reconciliation`, `_run_iteration_one`.
- `test_ft_b2_stage_handoff` (9) -> `tests/support/context_pack.py`: `FakeArtifacts`, `FakeSelections`, `FakeStaging`, `_downstream_request`, `_compiled_template`, `_service`, `FAST_REF`. It also stops importing `_blueprint`/`_operation`/`RecordingOperationBindings` from `tests.integration.temporal.test_wp_bp_010_temporal`; move those to the same support module.
- `test_completion_validation_service` (7), `test_human_gate_budget_admission` (3), `test_budget_admission_failure` (2), `test_mp20_stagegraph_concluded_failure` (1), `test_stagegraph_v2.operation_slot` (2) and `test_fork_templates.MemoryTemplates/_patch` (2) -> `tests/support/stagegraph_run.py`.
- `test_artifact_schema_validation` (5: `Custody`, `captured`, `SCHEMA`) -> `tests/support/artifact_custody.py`. `tests/fixtures/validation_restart_worker.py` imports it too.
- `test_goal_schema_completion` (4: `multi_goal_request`, `goal_request`, `OUTPUT`, `SUMMARY`, `ScopedCustody`) -> `tests/support/goal_completion.py`.
- `test_wp_bp_020_goal_directed` (4: `_execution`, `_verification`, `_blueprint`, `_claim`, `_revision`, `_run_input`) -> `tests/support/goal_directed_domain.py`.
- `test_async_child_parent_budget` (5: `spawn`, `admitted_parent`), `test_async_child_check_time_admission._sealed_contract` (3) and `test_async_child_parent_completion.Lineage` -> `tests/support/async_children.py`. Bring along the acceptance-module imports `DeterministicProvider` (test_wp_cp_045) and `exact_fixture`/`planned_invocation`/`unit_bound` (test_wp_cp_040).
- `test_checkpoint_recovery_classification` (3: `_namespace`, `_write_foreign_root_checkpoint`, `_chain`, `_leaf_id`, `_root_checkpoints`, `AFTER_TOOL_CHECKPOINT`), `test_rrm_008_cancellation` (`_liability`, `_settlements`), `test_rrm_016_goal_directed_recovery._Templates` and `test_ft_f2_interrupt_and_inject` (`RecordingModel`, `harness_with_injections`, `facade`, `operator`, `states`, `status_of`, `FAST`) -> `tests/fixtures/checkpoint_recovery.py`.
- `test_lane_admission_rejection.RejectionJournal` (2) -> folded into the canonical journal fake.
- Small single-importer exports, moved next to their behaviour:
  - `test_lane_outputs.compiled/custody` -> `tests/support/operations.py`
  - `test_lane_reconciliation.NativeRecovery` -> `tests/fixtures/lane_turns.py`
  - `test_native_receipt_evidence` constants -> `tests/fixtures/saved_settlement.py`
  - `test_reaction_planning` builders -> `tests/unit/reactions/support.py`
  - `test_wi13_nested_runtime.body/parent_with_reservation` -> `tests/support/nested_bodies.py`
  - `test_closed_workflow.setup_recovery` -> `tests/unit/recovery/support.py`
  - `test_closed_workflow_temporal.Client/Handle/history` -> same
  - `test_stage_named_outputs.setup` -> `tests/unit/outputs/scenario.py`
  - `test_goal_exact_context.fixture`, `test_wi08_graph_routes.Driver`, `test_w1_goal_failure_paths._executor_dispatch`, `test_wi13_round2.Lineage/Submissions`, `test_hosted_bundle_publication.NoCredential/repository`, `test_seeded_fork_saga.saga`
- Outside this slice but consumed heavily here: `tests.unit.run_control.test_run_control` (`actor`, `command`, `request`, `service`, `ConfigurationVerifier`, `DIGEST`, `NOW`, `reconciler_command`). It is imported by about 35 files in this slice and needs the same treatment from slice owner A or C.

### Patterns

- **Good: one contract, many adapters.** `operations/test_checkpoint_lineage.py` runs `assert_checkpoint_lineage_repository_contract` against the src in-memory repository; the PG adapter runs the same contract. Copy this for the journal fake.
- **Good: a real Deep Agents graph behind the full boundary with only the model scripted.** `tests/fixtures/checkpoint_recovery.py` (`recovery_harness`) is used by test_checkpoint_recovery_classification, test_rrm_008_cancellation and test_wi04_saved_settlement. Real `create_deep_agent`, real journaled coordinator, real lineage, in-memory run control, scripted model.
- **Good: boundary-only doubles over real git.** `effects/*` use a local bare remote plus `httpx.MockTransport`, with no internal patches.
- **Bad: faking the Temporal SDK module.** `test_d39_claim_held_retry.py` and `test_operation_cancel_delivery_race.py` monkeypatch `workflow.start_activity/wait_condition/now/patched`. The time-skipping environment is already used in `test_operation_execution.py`.
- **Bad: replacing parsers and digests inside the unit under test.** `test_fork_human_gate_admission.py` patches `MissionDefinition`, `StageGraphBlueprint` and `sha256_digest`. `test_mp20_authored_stage_inputs.py` patches `MissionDefinition`.
- **Bad: asyncpg fakes that match SQL text.** `recovery/test_terminal_turn_usage.py` and `recovery/test_closed_workflow_postgres_authority.py` break on any query rewrite and prove nothing the PG integration tests do not.
- **Bad: patching composition-module internals.** `test_rrm_009_cancellation_composition.py` and `test_async_child_parent_completion.py` patch `composition.AsyncChildCompletion`, `PostgresAsyncSubagentAuthority` and `StandalonePersistenceLifespan`.
- **Mixed: fault injection by monkeypatching methods of src in-memory repositories.** Examples: `test_stagegraph_completion_replay.py` and `test_parallel_stage_authority.py` patch `commit_family_admission` and `commit_command`. It is acceptable, but a reusable `FaultyRunControlRepository` wrapper would remove about 15 ad hoc patches. `test_stagegraph_completion_replay` also patches the private `service._mutation`.
- **Misplaced.** Script tests live under `tests/unit/operations`: test_local_installation, test_local_stack, test_sprint_oc_runtime_env, test_sprint_oc_deployment_file, test_sprint_oc_mint_bundle_tokens and test_tenant_binding_digest. The scripts are live (`make` install-local targets, and `scripts/dev/local_installation.py` imports `sprint_oc_*`). Move them to `tests/unit/scripts/` with behaviour names.
- **Private-symbol coupling** is widespread. Examples: `_binding_for`, `_lane_settlement`, `_concluded_failed`, `_noncognitive_gate_keys`, `_context_instance`, `_bind_handoff`, `_undelivered_verification`, `_recover_handoff_compaction`, `_completion_payload`, `_fork_position`, `_effect_claim_id`. These tests are not wrong, but they block refactors of those modules.

### Deep Agents path (operation request -> lane -> settlement)

Essential protection in this slice. Never delete these:

1. `operations/test_operation_execution.py`: the only tests here of `OperationExecutionService` and `OperationWorkflow` together on Temporal time-skipping. It covers binding before effects, exact idempotent retry, budget violations, the claimed-unsettled no-repeat rule, lost-holder takeover and the cross-queue activity route. The lane is `DeepAgentsHarness(ConformanceRuntime)`.
2. `operations/test_checkpoint_recovery_classification.py`, `test_rrm_008_cancellation.py`, `test_wi04_saved_settlement.py`, `test_fenced_turn.py` and `test_in_turn_run_budget.py`: a real Deep Agents graph through the whole boundary, covering crash windows, cancellation, saved results, stop fence and in-turn budget.
3. `operations/test_bounded_queued_turn.py` and `test_ft_f2_interrupt_and_inject.py`: Deep Agents cooperative steer and queued turns.
4. `orchestration/test_rrm_016_goal_directed_settlement.py` and `operations/test_rrm_016_goal_directed_recovery.py`: GoalDirected executor and verifier on a real Deep Agents graph, settling once.
5. `orchestration/test_live_invocation_origin.py`: the Deep Agents materializer context names the live attempt and generation, not the template. This is configuration protection.
6. `operations/test_async_child_*`: Deep Agents async subagents as parent effects.
7. Family-level protection: `test_ft_b2_stage_handoff.py` (Deep Agents packet mount map), `test_stagegraph_v2.py`, `test_completion_validation_service.py` and `test_wp_bp_020_goal_directed.py`.

Overlaps worth knowing; keep both sides because they run at different levels:
- Lease takeover is tested at the Conformance level (`test_operation_execution::test_lost_native_holder_is_taken_over_by_fence_and_parked_in_doubt`) and on a real graph (`test_checkpoint_recovery_classification::test_lost_worker_lease_is_honored_until_it_expires` / `test_zombie_holder...`).
- Cancel-with-saved-result appears in both `test_wi04` (window 5) and `test_rrm_008`.
- `test_fenced_turn` and `test_rrm_008` both settle fenced cancels.

Gaps:
- (a) `operation_request()` is hand-built. Its model policy is `openai/gpt-5-mini`, its workspace provider is `conformance-sandbox`, and the lane fields come from `lane_fields` patches. It is not produced by manifest -> compile -> sealed Deep Agents binding, so no test here shows that the request the lane receives is what compile seals. The proposed `tests/support/operations.py` should offer a builder derived from `tests/unit/authoring/manifest_launch_fixture.deep_agents_chain`.
- (b) No test in this slice runs `OperationWorkflow` on Temporal with the real `DeepAgentRuntimeAdapter`. Either the Temporal half uses Conformance, or the real-graph half has no workflow. This join presumably lives in `tests/integration/deep_agents`; the coordinator should confirm.
- (c) `test_operation_cancel_delivery_race.py` is the only test of "accepted but undelivered cancel waits durably", and it fakes the SDK. Rewrite it; do not delete it.

### Uncertain calls for the coordinator

- **Terminal-adoption cluster (all 7 DELETEs).** Files: recovery/test_pending_family_inputs, test_pending_family_settlement, test_private_file_capture, test_terminal_adoption_readers, test_terminal_evidence_adoption, test_terminal_evidence_capture, test_terminal_lane_adoption.
  - Evidence: `compose_terminal_evidence_adoption` (`src/mission_control/bootstrap/terminal_adoption.py`) has no caller in src, scripts or tests.
  - `TemporalPendingResultInputReader`, `PrivateFilePayloadReader` and `ApprovedTerminalCaptureReader` are referenced only by these tests.
  - The src modules should be removed in the same change.
  - If the owner wants to keep the operator path, keep `test_terminal_evidence_adoption.py` instead, as REWRITE.
- **Reactions (WI-22).** `AdmittedReactionOperations` and `TemporalReactionStarter` are not composed in bootstrap. I kept the tests (REWRITE / KEEP) because the feature looks unfinished rather than retired; confirm.
- **Legacy-path tests.** Check that these src branches still have live callers (Temporal patch markers or pre-change histories):
  - `test_budget_admission_failure::test_old_admission_path...` and `test_absent_admission_rejection_keeps_legacy_projection_digest...`
  - `test_human_gate_budget_admission::test_temporal_patch_compatibility...` and `test_legacy_and_fork_interpretation...`
  - `test_goal_schema_completion::test_legacy_goal_wire_document...`
- **Pre-change composition.** `test_rrm_016_goal_directed_settlement::test_usage_accounting_before_and_after_the_governed_composition` exercises `journal=None`, a composition production never builds (`deployment_composition.py:1673,1723` always pass `journal=`). I recommend deleting that one test. The `journal is None` branches in `operation_execution.py` may then be removable.
- **test_terminal_frame_fencing / test_terminal_turn_usage MERGE** relies on `tests/integration/postgres/test_run2_terminal_frames_postgres.py` covering stale owner and snapshot usage. That test has a single test function; confirm it asserts the stale-owner refusal per changed field before deleting the unit copies.

## C-runcontrol-harness


### Counts (97 files, ~753 test functions by metrics)
| Verdict | Files | ~Tests |
|---|---|---|
| KEEP | 63 | 478 |
| REWRITE | 21 | 225 |
| DELETE | 12 | 47 |
| MERGE | 1 (test_run2_worker_roles -> test_lane_task_queue_workers) | 3 |

About a third of the REWRITEs need no change to their own assertions. They are test-as-library sources (test_run_control, test_boundary_commands, test_atomic_family_admission, test_boundary_interventions, test_ft_f1_command_mailbox, test_cursor_local, test_lane_cleanup, test_managed_budget_controls, test_mp22_local_readiness): move the builders out and keep the tests.

### Canonical doubles this slice needs
- **Run-control repository**: use src `InMemoryRunControlRepository` (application/execution/run_control_repository.py). Every run_control test already uses it, so there are no duplicates to fold in. It stands in for the Postgres repository in reducer tests. It still needs a contract test against `adapters/postgres/run_control`, which another slice may own.
- **RunConfigurationVerifier**: `ConfigurationVerifier` in test_run_control.py, plus subclasses (`ManifestConfigurationVerifier` in test_worker_manifest_admission, `FixtureConfiguration` in tests/unit/recovery). Move it to tests/fixtures/run_control.py. The only src implementation (`F1RunConfigurationVerifier`) needs a real committed definition.
- **Session lane (provider boundary)**: `ScriptedSessionLane` and `PreparingLane` in tests/fixtures/lane_turns.py, with `SimulatedWorkerLoss` and `RecordingSignals`. Subclasses are spread around: CleaningLane, HistoryLane, PointLane, SeedAwareLane, _UnknownUsageLane, _FinalTextLane, _CancelTailLane, _SteeringLane, ControlledManagedLane. Keep them as local subclasses. Move only CleaningLane to fixtures, because another file imports it. This is the one place to script provider frames for lane.turn.
- **Deep Agents runtime**: src `ConformanceRuntime` (adapters/operations/conformance.py), used through `DeepAgentsHarness` in test_lane_registry, test_lane_dispatch and lane_turns.lane_stack. `SlowRuntime` and `Observing` are tiny subclasses. No duplicates.
- **Lane state, frames and environment**: src `InMemoryLaneExecutionStateStore`, `InMemoryFrameStore`, `InMemoryEnvironmentPreparationRepository`, `InMemoryCognitionPointRepository`, `InMemoryStopFenceRepository` and `InMemoryHook*`. test_codex_usage_settlement monkeypatches methods on these to inject races. Replace that with one `FaultInjectingLaneState` wrapper in lane_turns.py.
- **Temporal client for boundary delivery**: `ScriptedTransport`, `ScriptedClient` and `ScriptedHandle` (test_boundary_interventions). Move them to tests/fixtures/boundary_commands.py. `FakeClient`/`FakeHandle` in tests/unit/temporal/test_fork_seed_runner.py does the same job for a different client API. Keep it local, or fold it in if the shapes converge.
- **Temporal start submitter**: `RecordingSubmitter` (test_run_launch), imported by 3 files. Move it to tests/fixtures/run_control.py.
- **Managed-agents provider**: `Provider`, `Authority` and `Approvals` (test_managed_budget_controls), imported by 2 temporal tests. Move them to tests/fixtures/managed_lane.py.
- **Hand-rolled asyncpg `Pool`/`Connection`** (test_run2_ingress_composition, test_run_fence_backing): remove them and use disposable Postgres via tests/fixtures/mission_control_common_db.py.

### Shared builders that must move out of test modules
- **tests/unit/run_control/test_run_control.py (150 importers) -> tests/fixtures/run_control.py.** Imported names and how many import sites use each: `service` 92, `request` 84, `command` 77, `actor` 58, `WORKFLOW_DIGEST` 19, `NOW` 15, `ALL_PERMISSIONS` 14, `ConfigurationVerifier` 11, `EMPTY_EVIDENCE_DIGEST` 8, `INITIAL_EVIDENCE_FRONTIER` 7, `reconciler_command` 6, `DIGEST` 5, `operator_wait` 4, `reconcile` 3, plus re-exports of the src types `SetWaitAction` and `StartAction` (1 each; import those from mission_control.domain.policies.contracts instead). Common aliases are `service as run_control_service`, `request as run_request`, `actor as control_actor/journal_actor` and `command as unit_command/lifecycle`. Move along with them the private helpers they depend on: `workflow_ref`, `manifest_ref`, `MANIFEST_DIGEST`, `UNIT_KEY`, `RECONCILE_PERMISSIONS`, `INCIDENT_ID`, `set_wait`, `_started_run`. Importers by directory: integration/postgres 44, unit/run_control 20, unit/operations 17, integration/temporal 11, unit/orchestration 10, unit/recovery 8, acceptance/control_plane 5, unit/mission_control 4, integration/deep_agents 3, unit/frames 3, and about 25 others, including 7 tests/fixtures modules (checkpoint_recovery, cursor_controls, goal_directed_journaled, rrm009_production_stack, rrm013_live_stack, runtime_inspection, run_forks).
- **tests/unit/run_control/test_boundary_commands.py (27 importers) -> tests/fixtures/boundary_commands.py.** Names and import-site counts: `TARGET` 25, `pause` 11, `started` 10, `declared_wait` 6, `states` 6, `apply` 3, `boundary_command` 3, `delivered` 3, `FAMILY_WORKFLOW_ID` 3, `resume` 2, `ROOT_WORKFLOW_ID` 2, `BOUNDARY_PERMISSIONS` 1. Importers: integration/postgres 14, unit/run_control 7, unit/operations 2, plus acceptance/control_plane, unit/frames, unit/runtime and unit/socketio (1 each). Also move ScriptedTransport, ScriptedClient, ScriptedHandle and `_status` from test_boundary_interventions.
- **test_atomic_family_admission.py (8 importers) -> tests/fixtures/run_control.py.** Move `admission_policies` (7), `family_service`, `family_mutation`, `authority_batch` and `TestFamilyMutation`. Rename the last one to `FixtureFamilyMutation`: a `Test*` class gets a collection attempt in every importer.
- **test_ft_f1_command_mailbox.py -> tests/fixtures/command_mailbox.py**: `World`, `_app`, `SCOPE`, `operator`, `Resolver`.
- **test_cursor_local.py -> tests/fixtures/cursor_local.py**: `_identity`, `_service`, `_turn`. Move `CleaningLane` (test_lane_cleanup) to tests/fixtures/lane_turns.py.
- **test_managed_budget_controls.py -> tests/fixtures/managed_lane.py**: `NOW`, `Approvals`, `Authority`, `Provider`, `stack`, `queue`.
- **test_mp22_local_readiness.py -> tests/fixtures/local_readiness.py**: `BINDINGS_EXAMPLE`, `AUTH_EXAMPLE`, `PROFILE_EXAMPLE`, `owner_selections`, `profile`.
- **test_run_launch.py -> tests/fixtures/run_control.py**: `_input`, `RecordingSubmitter`.
- **Smaller cases**: test_mission_control_facade (`pause_request`, `actor`) and test_stop_fence (`_cancel`, `admin`) go to tests/fixtures/run_control.py.
- **Imports into this slice from other slices' test modules** (owned elsewhere; listed so they move together): tests.unit.operations.test_operation_execution (`operation_request`, `service_fixture`), tests.acceptance.control_plane.test_wp_cp_040 and test_wp_cp_045, tests.unit.coordinator.test_coordinator_mcp_read_surface (`FakeFacade`), tests.unit.mission_control.test_authentication (`authenticated_world`, `NOW`), tests.conformance.resolution.test_resolver_conformance (`_registration`), tests.unit.codex.test_kernel_hooks (`memory_hooks`), tests.unit.signals.test_drainer (`item`), tests.unit.operations.test_lane_reconciliation (`NativeRecovery`).

### Patterns
- **Good: behaviour over src in-memory ports.** run_control/* drive `RunControlService` over `InMemoryRunControlRepository` and assert receipts and phases (test_run_control, test_rrm_008_cancellation_authority, test_transcript_joinability). harness/test_lane_turn_service.py drives `LaneTurnService` with only the provider scripted.
- **Good: process and host boundaries faked at the edge.** test_local_lane_child_environments and test_lane_network_projection patch only `asyncio.create_subprocess_exec`. test_mo08_worker_host_preflight injects a `ToolProbe`.
- **Bad: patching the temporalio workflow API instead of WorkflowEnvironment.** test_run2_ingress_wake builds `object.__new__(OperationWorkflow)` and patches `_lane_payload`, `_next_segment` and `workflow.patched`. test_managed_budget_routing, test_run2_cursor_costs (workflow part) and test_run2_integration_joins do the same.
- **Bad: replacing private methods of the service under test.** test_history_reconciliation patches `service._watch_history`, `_take` and `lane_turns.unit_boundary`. test_lane_operator_abandonment patches `service._session_lane`.
- **Bad: half-constructed objects and fake asyncpg.** test_run2_ingress_composition (`object.__new__(ManifestSubmitService)` plus a fake Pool) and test_run2_cursor_costs (`repository._bindings = SimpleNamespace(...)`).
- **xdist breaker:** test_run2_cursor_costs.py line ~346, `parametrize(..., [(str(uuid4()), True), ...])`. Replace it with a literal UUID string.
- **Dead "Stage 3" kernel.** Several application/recovery modules are tested but never composed in src: graph_runtime_dispatch, runtime_events, runtime_interventions, runtime_resources, runtime_run_plan, the RuntimeIncidentReconciler service, the DurableDecisionService service, BellLabsAgentServerActionResolver, and agent_server/reducers.py. Delete the tests together with the modules.
- **Run 2 judgement:** the cursor-costs, ingress, bridge and worker-role behaviour is still live in src. The two release-preparation scripts (1.4.1) are historical. The `test_run2_*` names should become behaviour names.

### Deep Agents path: essential protection in this slice
1. **Manifest compile and sealed binding.** resolution/test_resolution_types, resolution/test_sealed_lane_binding, resolution/test_w1_d24_api_surface (Deep Agents compile to the OpenAI Responses client), harness/test_model_listing (Deep-Agents-only installation).
2. **Deep Agents lane harness and dispatch.** harness/test_lane_registry (the four `test_deep_agents_*` tests: execute path, session turn, cancel, reattach), harness/test_lane_dispatch (dispatch through the registry), harness/test_lane_contracts (DEEP_AGENTS_DESCRIBE), harness/test_multi_provider_contracts.
3. **Run control: provider-neutral, every Deep Agents run passes through it.** test_run_control, test_atomic_family_admission, test_boundary_commands, test_boundary_interventions, test_rrm_008_cancellation_authority, test_stop_fence, test_run_fence_backing (the stop fence that ends a Deep Agents turn), test_worker_manifest_admission (nested Goal Loop and Stage Graph bodies), test_run_launch, test_family_mutation_fingerprint_set_order.
4. **Snapshot, fork and inspection.** runtime/test_run_snapshot_manifest (real `create_deep_agent` graph with a scripted model), run_control/test_runtime_inspection_reads (LangGraph checkpoint history), runtime/test_runtime_recovery_stage3 (RuntimeForkService).

**Gaps:**
- **LaneTurnService is not on the Deep Agents path today.** `OperationWorkflowRequest.segment_driven` is true only for SESSION_LANE_RUNTIMES (cursor, claude, codex) or when `segments` is set (bootstrap_probe). Deep Agents runs the governed body through OperationExecutionService. So test_lane_turn_service and its siblings protect the secondary lanes, and the DeepAgentsHarness session-protocol tests cover only the harness, not lane.turn.
- **No Deep-Agents-runtime operation through LaneTurnService.** `lane_stack` defaults to `cursor_operation`. Nothing in this slice runs a Deep Agents operation through LaneTurnService, nor through the OperationWorkflow segment loop under WorkflowEnvironment.
- **ingress_wake has only an internal-mock test.** OperationWorkflow.ingress_wake (INGRESS_STATUS_PATCH) is provider-neutral, but its only test is test_run2_ingress_wake.
- **No reducer-vs-Postgres contract test in this slice.** InMemoryRunControlRepository has none pinning it against the Postgres repository (it may live in integration/postgres).

### Uncertain calls for the coordinator
- **test_qualia_* (3 DELETEs).** Qualia fixtures are still imported by tests/fixtures/aieng_* and integration/postgres/test_manifest_fork_admission. If the Qualia drivers survive, their self-tests may be wanted.
- **Stage 3 DELETEs (runtime_decisions, runtime_incident_reconciliation, runtime_interventions, agent_server_actions).** Their record types are still persisted by adapters/postgres/runtime/stage3_kernel_repository. The services themselves are never instantiated. Confirm with whoever owns the agent_server adapter (used by deep_agents/async_subagents).
- **test_runtime_bootstrap_stage3 (KEEP).** It is live only if adapters/agent_server/http_app.py is deployed, and I found no deploy config that references it.
- **test_run2_canonical_release and test_run2_release_candidate (DELETE).** The db-contract package's own tests may already guard frozen releases. If you delete these, also delete scripts/prepare_run2_release.py and scripts/prepare_codex_describe_successor.py.
- **test_lane_dispatch and test_model_listing (KEEP).** Both bypass `authorize_application` by monkeypatch. That is minor, but it is the pattern repeated across route tests, and a shared authenticated-principal fixture would remove it.

## D-authoring-deepagents


94 files (91 test modules, 3 helper modules), ~779 test functions. Read-only review; no pytest run.

### Counts
| Verdict | Files | ~Tests |
|---|---|---|
| KEEP | 70 | ~542 |
| REWRITE | 17 | ~189 (most of these are restructure-only: the tests stay and their builders move) |
| MERGE | 4 | ~8 |
| DELETE | 3 | ~40 |

### Canonical doubles this slice needs
- **LLM: `ScriptedChatModel`.** It stands in for the paid chat model. Build it from `Scripted` in `tests/unit/deep_agents/test_turn_stops.py`, move it to `tests/fixtures/chat_models.py`, and give it these features:
  - `respond(messages, call) -> AIMessage`
  - call counting and a loop guard
  - stable message ids
  - default `usage_metadata`
  - `bind_tools` that returns self and records the bound tools and kwargs (needed by `test_structured_output_strategy`)
  - a `seen` list of input batches
  - `from_messages([...])` for fixed scripts
  - async support, so the GenericFakeChatModel callers still work

  These copies fold into it:
  - In this slice: ScriptedModel (`test_hook_graph`, `test_hook_contributions_graph`), ScriptedChildModel (`agent_server/test_async_subagent_server_offline`, also imported by `test_sealed_child_graph`), ThreeCallModel, AlwaysCallsTools, PromptDrivenVerifier, RecordingModel (FakeMessagesListChatModel), and ToolModel, _ToolModel, _RecordingModel, _AutoModel and _Scripted (all GenericFakeChatModel).
  - Outside this slice: SkillReadingModel and SessionProbeModel (`tests/acceptance/control_plane/test_wp_cp_040.py`), ScriptedRecoveryModel, ScriptedWorker, SealedLocalChild and about ten more.

  There are 26 BaseChatModel subclasses in total.
- **The model catalog is not the LLM double.** `tests/fixtures/models.py` (`fixture_model_catalog`, `bindings_catalog`, `checked_in_catalog`) is deployment configuration. It maps profiles to the `fixture-model` row for WP-CP-040. Keep it as the one catalog fixture.
- **Deployment launch bindings: `tests/unit/authoring/manifest_launch_fixture.py`.** It is a BOUNDARY-config fixture with 24 consumers. Move it to `tests/fixtures/manifest_launch.py`. Its upstream builders also move: `exact_fixture`, `skill_bundle` and `registry` go from the acceptance module `test_wp_cp_040` to `tests/fixtures/deep_agents_exact.py`, and `operation_request` goes out of `tests/unit/operations/test_operation_execution`.
- **MCP client: the FakeClient in `test_materializer_mcp_filter`.** It patches `materializer.MultiServerMCPClient`, which is the real boundary. Move it to `tests/fixtures/mcp_client.py`. `test_materializer_children` must use it instead of patching the private `_load_mcp_tools`.
- **Capability catalog: `tests/fixtures/catalog/fast_track_catalog`.** This is the in-memory definitions and lexical search. Keep it as the only compile catalog. `compile_programs` (in `test_manifest_launch_inputs`) and `service` (in `test_manifest_compile`) both rebuild the same `ManifestCompileService` over it. Fold them into one builder that takes a catalog parameter; that also removes the monkeypatch in `test_schema_only_stage_inputs`.
- **Coordinator and subscription ports: `tests/unit/subscriptions/fakes.py` and `coordinator_fakes.py`.** These are the single copies: InMemoryStore, FakeWebhook, StaticSecrets, InMemoryInboxStore, InMemoryAttentionStore and FakeGateway. Their PostgreSQL counterparts are proven in `tests/integration/postgres/test_mp15_*` and `test_wi19_*`. Move both files to `tests/fixtures/`, because watchers and coordinator tests import them.
- **Agent Server SDK: FakeThreads, FakeRuns and FakeSDK** (in `test_langgraph_agent_server_stage3`). They go away with that file. If the client survives, keep them as the one langgraph_sdk double.
- **Docker: FakeDockerSandbox** (in `test_workspace_closure`). Keep it; it is a legitimate boundary double.

### Shared builders to move out of test modules
| Source test module | Names imported elsewhere | Move to |
|---|---|---|
| authoring/test_manifest_v2_launch (17 users) | example, EXAMPLES, compile_yaml, _compile, compiled_ok, edited, blockers, templates_of, bindings, served, resolver, stub_author, bundle_selection, SCOPE, AT, BINDINGS, V1_BINDINGS, DEFAULT_DATA_CLASS_POLICY (re-export) | tests/fixtures/manifest_compile.py (compile side), tests/fixtures/manifest_launch.py (launch side) |
| authoring/test_manifest_compile (15) | scope, service, minimal, text, reasons, MINIMAL, AT, http_app | tests/fixtures/manifest_compile.py |
| authoring/test_manifest_launch_inputs (14) | admitted, compile_programs, resolver, pubmed_resolver, served_with_mcp, pubmed_digest, MINIMAL, SCOPE, MISSION_2, chain, fixture_served (re-export) | tests/fixtures/manifest_launch.py (unify `resolver` with v2_launch.resolver) |
| authoring/manifest_launch_fixture (24) | fixture_bindings, fixture_served, pubmed_bound, deep_agents_chain, unserved_model_ref | tests/fixtures/manifest_launch.py |
| authoring/test_manifest_v2_environment (3) | manifest, compile_text, _set, blockers, AT, ENV, NODE, SCOPE, KIT_PIN, RESOLVED, SECRET_REFS, _sdk_templates, CONFIG | tests/fixtures/manifest_environment.py |
| authoring/test_manifest_interfaces (3) | FakeLifecycle, manifests, principal | tests/fixtures/manifest_lifecycle.py (compare with the FakeLifecycle in unit/web_research) |
| authoring/test_manifest_cursor_launch (3) | LOCAL, CLOUD, seeds_publish_module | tests/fixtures/manifest_launch.py |
| authoring/test_experiment_loop_fixtures (3) | rendered, FIXTURES, compiled | tests/fixtures/manifest_compile.py |
| authoring/test_mission_brief (2), test_manifest_schema, test_completion_support, test_wi13_nested_authoring, test_output_promises_compile, test_l1_06_goal_verifier_objective (1 each) | BRIEF, document, minimal, definition, compiled_configuration, E4, loop_templates, text_of | tests/fixtures/manifest_compile.py |
| deep_agents/test_lane_adapter (3), test_lane_adapter_children (1) | _inputs, _profile, _selected, POINTER, _graph, _seed_server, _seed_skill | tests/fixtures/deep_agents_lane.py |
| deep_agents/test_cognition_points_collector (2) | THREAD, DIGEST, _graph, _plan, _lineage | tests/fixtures/checkpoint_graphs.py |
| deep_agents/test_hook_middleware (1) | _binding, _bound_binding, _hook_bundles | tests/fixtures/hook_bindings.py |
| deep_agents/test_workspace_closure (1, integration) | _workspace | tests/fixtures/workspace_closures.py (exists) |
| agent_server/test_async_subagent_server_offline (1) | ScriptedChildModel | tests/fixtures/chat_models.py |
| subscriptions/test_mo43_wake_channels (3) | missionctl, KEY, _registry, INSTALLATION, TENANT, LAUNCHER, _principal, inbox_app, operator_client, run_inbox, terminal | tests/fixtures/coordinator_surface.py |
| subscriptions/test_mp15_coordinator (2), test_wi19_attention (1), test_wi19_interfaces (1) | classify_type, Outputs, output, FakeReader | tests/fixtures/coordinator_surface.py |

### Patterns
**Good**
- Real LangGraph machinery with only the model scripted: InMemorySaver, compiled `create_deep_agent`, and real hook subprocesses. Examples: `test_turn_stops`, `test_cognition_points_collector`, `test_hook_contributions_graph`, `test_continuation_graph`.
- The src in-memory ports are used where they exist: InMemoryStopFenceRepository, InMemoryHookIntentLedger, InMemoryCheckpointLineageRepository and InMemoryPayloadStore. Examples: `test_kernel_hook_ports`, `test_model_request_observer`.
- Pointer-exact refusal tests through the real compile service and launch author. Examples: `test_manifest_launch_inputs`, `test_manifest_launch_resolution`.

**Bad**
- Spies on `RuntimeResolver.resolve` and `RuntimeResolver.admit` that only prove an internal call happened: `test_launch_admission_coverage`, `test_hosted_launch_bindings`.
- AsyncMock or private-attribute replacement where an InMemory class exists:
  - `test_artifact_schema_definition`: `ControlPlaneService(AsyncMock(), Mock(), Mock())`
  - `test_output_schema_binding`: `compiler._definitions = AsyncMock(...)`
  - `test_materializer_children`: `monkeypatch(materializer._load_mcp_tools)`
- A fake database connection that asserts SQL substrings: `test_run2_caller_identity`.
- Chains of test modules used as libraries, including acceptance tests imported into unit tests. `test_purpose_card_launch` imports six test modules; `test_sealed_child_graph` imports `test_wp_cp_040` and `test_async_child_check_time_admission`.
- Sprint scripts re-run inside unit tests: `test_hosted_stagegraph_fixtures` loads `scripts/sprint_oc_w1_bindings.py`.
- A file-inventory test: `test_experiment_loop_fixtures::test_the_fixture_set_is_exactly_e1_to_e5`.
- Persistence tests filed under `agent_server/`: `test_langgraph_persistence_stage3` and `test_runtime_checkpoint_binding` target `adapters/deep_agents/persistence.py`.

### Deep Agents path: the single best test per behaviour
1. **Manifest parse:**
   - `test_manifest_schema::test_owner_manifests_parse_with_no_structural_blockers`
   - `test_manifest_v2::test_v1_fixture_parses_identically_as_v1_and_v2`
2. **Compile to definitions and pinned programs:**
   - `test_manifest_compile::test_owner_manifests_compile_with_zero_blockers_deterministically`
   - lane support: `::test_lane_support_matrix`
3. **Launch inputs (sealed DeepAgentExecutionBinding per stage and goal role):**
   - `test_manifest_launch_inputs::test_stage_templates_bind_each_node_environment`
   - `::test_goal_templates_bind_executor_and_verifier`
   - refusal pointers: `test_manifest_launch_resolution::test_each_pointer_class_maps_to_its_manifest_pointer`
   - data class: `::test_an_undeclared_mission_fails_closed_to_the_application_ceiling`
4. **Sealed lane binding:**
   - `test_compile::test_the_template_step_seals_the_exact_binding_for_the_template_coordinates`
   - rebind: `::test_the_rebind_reseals_the_template_for_one_live_attempt_by_digest`
   - envelope decode: `::test_admission_refuses_an_envelope_drift_before_authority_or_binding`
5. **Lane adapter and agent configuration:**
   - `test_lane_adapter::test_the_adaptation_is_an_exact_binding_input`
   - `test_lane_adapter_features::test_the_configuration_is_part_of_the_exact_binding_digest`
   - network authority: `test_deep_agents_network_grants::test_stage_network_allowlist_reaches_exact_binding_and_child_none_is_narrowed`
6. **Children:**
   - `test_subagent_seeds_compile_and_launch::test_launch_routes_seeds_to_the_child_and_receipts_them`
   - `test_async_child_sealed_binding::test_a_seeded_async_child_seals_its_own_prompt_model_and_components`
   - `test_materializer_children::test_the_implicit_general_purpose_child_is_never_added`
7. **Materialization:**
   - `test_agent_configuration_materialization::test_provider_tools_and_model_settings_reach_the_model`
   - MCP: `test_materializer_mcp_filter::test_a_changed_schema_of_a_bound_tool_is_refused_in_either_mode`
   - model: `test_model_routes::test_the_worker_factory_refuses_a_binding_sealed_for_another_vendor`
   - structured output: `test_structured_output_strategy::test_the_materializer_wraps_the_schema_in_the_declared_strategy`
8. **Turn on the lane:**
   - `test_model_request_observer::test_three_model_calls_leave_three_model_request_frames_before_their_responses` (the only in-slice run of DeepAgentRuntimeAdapter)
   - stops: `test_turn_stops::test_past_the_cap_the_summarizer_makes_no_paid_call_before_the_stop`
   - budget: `test_in_turn_run_budget::test_a_turn_that_keeps_calling_tools_stops_at_the_run_tool_call_budget`
9. **Agent Server host:**
   - `test_canonical_deployment::test_profiles_select_exact_graphs`
   - `test_async_subagent_server_offline::test_hosted_graph_is_built_through_the_canonical_adapter_and_stamps_identity`
   - `test_sealed_child_graph::test_a_run_resolves_exactly_its_scopes_sealed_binding_and_is_compiled_once`

**Gaps**
- **No end-to-end test from manifest to a scripted Deep Agents turn.** No unit test takes one manifest through compile, the launch author, the DeepAgentsCompileAdapter template step, harness decode, materialization and a scripted turn.
  - `test_subagent_seeds_compile_and_launch` stops at the sealed binding.
  - `test_wp_cp_040` (acceptance) runs the turn from a hand-built `exact_fixture`, not a compiled manifest.
  - Add one `tests/unit/deep_agents/test_manifest_to_turn.py` using ScriptedChatModel. It should assert that the agent receives the Purpose Card and authored prompt, exactly the bound tools, Skills and MCP tools, the catalog pin's model id, and the sealed budget.
- **The harness run path is untested here.** `adapters/deep_agents/harness.py` (356 lines) appears in this slice only through `ValidatesOperationRequest` in `test_compile`. Its run path is covered only by `tests/acceptance/control_plane/test_wp_cp_040.py` and `tests/conformance/lanes/adapters/governed.py`, so `make check` depends on conformance for it.
- **Deep Agents adapter modules with no direct test import:** `child_adoption.py` (90 lines), `transfer.py` (166), `host_files.py` (164) and `checkpoint_verifier.py` (71, integration only).
- **Agent Server modules with no test and no src importer:** `bootstrap.py`, `graph_factory.py` and `common.py`. `runtime_composition.py` is imported only by `bootstrap.py` and `http_app.py`. These look like dead src.
- **Tested only indirectly.** These are reached only through `ManifestCompileService` or `ControlPlaneService`, which is acceptable: `application/authoring/manifest_v2_admission.py` (457 lines), `domain/authoring/compiler.py` (1004) and `goal_verifier_objective.py`.

### Uncertain calls for the coordinator
- **`agent_server/test_langgraph_agent_server_stage3` (DELETE).** Grep finds no src importer of `adapters/agent_server/client.py` or of `GraphRuntimeDispatchService`. Confirm the Stage 3 dispatch client is not a planned route, then delete the src modules and `tests/unit/runtime/test_graph_runtime_dispatch.py` and `test_runtime_interventions_stage3.py` together.
- **`agent_server/test_agent_server_block_c_unit` (DELETE).** Only valid if the owner retires the qualification profile and `block_c_qualification/` (registered in `agent_server/langgraph.json`). Otherwise KEEP.
- **`agent_server/test_agent_server_block_c_persistent` (DELETE).** It does not belong in unit in any case: it is a live drill that is skipped in every make target. If the owner wants the evidence kept, move it to `tests/qualification/agent_server_block_c/`.
- **`authoring/test_sprint_oc_w3_fixtures` (MERGE).** Check `tests/unit/knowledge/test_wi07_report_collections.py`. If it already lowers a goal-scoped collection plus an iteration-scoped note, DELETE instead.
- **`deep_agents/test_l1_06_verifier_decides` (MERGE).** The value is in the prompt-text assertions; the fake model loop mostly tests the fake.
- **FakeLifecycle duplication.** Unverified whether the FakeLifecycle in `tests/unit/web_research/test_web_research_semantic_handlers.py` fakes the same port.

## E-knowledge-context


90 files (88 test modules + 2 helper modules), about 780 test functions.

### Counts by verdict

| Verdict | Files | Approx. tests |
| --- | --- | --- |
| KEEP | 63 (incl. helpers `outputs/scenario.py`, `context/packets.py`) | 558 |
| REWRITE | 23 | 210 |
| MERGE | 3 | 7 |
| DELETE | 1 | 5 |

Most REWRITEs keep every test. Two things need fixing: test-as-library modules lose their builders, and a few internal fakes are swapped for the canonical boundary double. A consumer whose only problem is importing builders from another test is KEEP, because its fix is a mechanical import change.

### Canonical doubles this slice needs

1. **Knowledge Services: one double.** Keep `FakeKnowledgeBinding` (tests/fixtures/knowledge_binding.py). It verifies real Ed25519 credentials and runs K01 dispatch admission, and `knowledge_http_app` serves the same fake over HTTP, so direct and HTTP transports run the same scenarios.
   - Fold in: `TrustedKnowledgeDouble` (tests/fixtures/trusted_knowledge.py, 381 lines; a second `KnowledgeBindingClient` for trusted-assessment operations). It should become an operation module of `FakeKnowledgeBinding`. Also fold in the third `operation_get` implementer, `tests/unit/test_aieng_knowledge.py` (outside this slice).
   - Why the double is needed: KS is a separate service with its own credentials and deployment. `parity_target` already swaps in the real executor when the KNOWLEDGE_BINDING_* variables are set.
   - Wire-level only: `httpx.MockTransport` in test_http_client.py and `OpenAITransport` in test_w1_d23 are legitimate boundary doubles for the HTTP clients themselves.
2. **LLM evaluator.** Keep `ScriptedRunner` (test_trusted_judgment.py; 9 importers) and `Invoker` (test_independent_evaluators.py), moved to a support module.
3. **Clock and credentials.** Keep `SteppingClock`, `Issuer` and `RecordingMinter` from knowledge_binding.py.
4. **KS-side port fakes.** `InMemoryKnowledgeJournal`, `InMemoryKnowledgeHandleStore`, `InMemorySubmissionStore`, `InMemoryTransferPlanStore`, `InMemoryLineageStore`, `InMemoryRetainedReadStore` and `InMemoryStaging` are each the only copy for their port. src has no InMemory version. The precedent is `adapters/knowledge/decisions.InMemoryUseDecisionStore` and `invocation_locator.InMemoryInvocationLocator`, both already in src. Recommendation: promote these stores to `src/mission_control/adapters/knowledge/memory.py`, and pin them with the PostgreSQL proofs that already reuse the same scenarios (integration/postgres/test_knowledge_gateway_postgres.py imports test_gateway).
5. **Output contracts.** Keep `InMemoryOutputContractStore` (tests/fixtures/output_contracts.py, 499 lines; 23 importers; PostgreSQL proof is test_output_contracts_postgres.py). Fold in `FakeOutputs` from test_transfer_materializer.py: it is a partial duplicate, which is why test_authorized_subjects and test_linked_transfer monkeypatch the methods it lacks.
6. **Receiving backend.** One `FakeBackend` (test_transfer_materializer.py) is used by 6 files. Move it to the support module. The backend is a lane sandbox/workspace port, so a port fake is legitimate.
7. **Embeddings.** Keep `DeterministicEmbeddings` (tests/fixtures/capability_search_catalog.py). Fold in `FakeEmbeddings` (test_capability_hybrid_search), `FailingEmbeddings` (test_capability_search) and `BatchEmbeddings` (test_catalog_projection_reliability) as options of it.
8. **Artifacts/staging duplicates.** `FakeArtifacts` exists in test_transfer_materializer and in test_ft_b2_stage_handoff (used by test_fork_conversation_custody). `FakeStaging` duplicates `InMemoryStaging`. Keep one artifacts fake beside `InMemoryStaging`.

**Does this slice need knowledge_binding.py's 1,984 lines?** Only the KS-seam files do: test_gateway, test_knowledge_tools, test_read_intent, test_report_package_extension, test_submission_assessment and test_transfer_materializer. Every other user imports only content builders (`report_package`, `model_report`, `describe_document`) or one in-memory store. Split the file into:
- `binding.py`: the fake, the HTTP app and the parity target
- `credentials.py`
- `stores.py` (or src, per item 4)
- `content.py`: the report/registration builders

Then pure output and transfer tests stop loading the KS fake. output_contracts.py is the right weight and imports `InMemorySubmissionStore` only to share submission rows.

### Shared builders that must move out of test modules

| Source test module (importers) | Names imported | Proposed support module |
| --- | --- | --- |
| knowledge/test_gateway.py (35) | origin(25), TENANT(13), harness(8), call(6), INSTALLATION, AUDIENCE, BINDING, TRANSPORTS | tests/support/knowledge.py |
| knowledge/test_knowledge_tools.py (20) | lane(19), RUN(7), MISSION, _runtime_invocation, BINDING, TOOL_NAMES, Lane | tests/support/knowledge.py (Deep Agents lane harness) |
| outputs/scenario.py (40, already a helper) | obligation(36), build_stack(22), text(18), promises, Stack, fulfillment, host_access, codes, digest_of, schema, structured, code_change, TRUSTED_VALIDATORS, eight_forms, REPO, CLAIMS_SCHEMA, BASE, HEAD, INDEX_SCHEMA | tests/support/outputs.py (together with output_contracts.InMemoryOutputContractStore) |
| context/test_transfer_materializer.py (9) | dependent, FakeBackend, seam, REPORT_INPUT, _trusted, RUN, FakeOutputs, OVERHEAD | tests/support/context_transfer.py (drop FakeOutputs) |
| knowledge/test_trusted_judgment.py (9) | ScriptedRunner, world, evaluators, head_of, PRODUCER, World, JUDGE_PIN, PROFILES | tests/support/trusted_knowledge.py |
| knowledge/test_native_write.py (4) | DIGEST, HANDLE, PLAN, RUN_DECISION, Bridge, service, Applier, Preview, accepted_report, ... | delete with the rewrite (internal fakes); keep constants in tests/support/knowledge.py |
| outputs/test_output_fulfillment.py (5) | invocation, make_stack | tests/support/outputs.py |
| context/test_transfer_plan.py (4) | report_input, report_members, selection, seal, OVERHEAD, _deliveries, member | tests/support/context_transfer.py |
| knowledge/test_wi07_report_collections.py (3) | PIN, ScriptedBridge, settlement, handle, run_iteration, stack_with | tests/support/outputs.py (ScriptedBridge goes away) |
| outputs/test_w1_d28_d29.py (2) | bridge_judges, report_candidate, report_promise, PIN, HANDLE, make_stack | tests/support/outputs.py |
| context/test_linked_transfer.py (2), outputs/test_collections.py (2), knowledge/test_independent_evaluators.py (2) | setup, RUN; collection, report, collection_promise, TRUSTED_PIN, VERIFIED; bindings, NOW, Invoker, subject, verdict | the support module of the same area |
| singles: test_http_client.VECTORS, test_submission_assessment.report_selection, test_knowledge_manifest.MANIFEST/SCOPE, test_w1_tool_boundary._calls, test_w1_convergence_fulfillment._observation, test_chain_reducer.accepted/apply/build/document/reduce, test_native_write_recovery.IntentPreview | | same area support module |
| context/packets.py (2, helper) | target, worked_example_request, SEALED_AT, profile | tests/support/context_packets.py |

This slice also consumes libraries from other slices: test_manifest_launch_inputs, test_run_control, test_ft_b2_stage_handoff, test_wp_bp_020_goal_directed, test_wi13_round2, test_stage_named_outputs, test_goal_exact_context, test_mo43_wake_channels, test_coordinator_facade, test_resolution_types, test_experiment_loop_fixtures and acceptance/test_overnight_linked.

### Patterns worth reporting

- **Good: one fake, two transports, optional real target.** test_gateway.py runs every scenario as `TRANSPORTS = ["direct", "http"]` over the same `FakeKnowledgeBinding` with real Ed25519 verification, and integration/postgres reuses the scenarios. This is the model for every boundary.
- **Good: golden vectors produced by the other service.** test_ks_operation_id_parity, test_report_registration (ks-registration-parity.json) and test_evaluator_parity pin the cross-service contract without a network call. test_w1_d22_handle_operations reads the sibling KS checkout instead and silently skips without it (`pytest.skip`). Convert it to a golden vector.
- **Good: through the real Deep Agents tool binding.** test_submission_foundation and test_w1_tool_boundary call the LangChain StructuredTool the agent sees, not the toolset.
- **Bad: hand-written fakes of concrete internal services.**
  - test_native_write `Bridge`/`Reports` fake TrustedJudgmentBridge/ContentResolutionService; test_native_write_recovery depends on them.
  - test_wi07_report_collections `ScriptedBridge`.
  - test_chain_cancellation `Control` (RunControlService) and test_chain_watcher_start `Launches` (RunLaunchService).
  - Fix: use the real service over the boundary doubles, as test_trusted_judgment and test_unstarted_cancellation already do.
- **Bad: patching what a partial fake lacks.** test_authorized_subjects and test_linked_transfer use `monkeypatch.setattr(s.outputs, "...", ..., raising=False)` on `FakeOutputs`. test_linked_transfer also patches the private `_recheck`, even though `LinkedExportResolver` already takes `recheck=` in its constructor.
- **Bad: patching mission_control internals.**
  - test_trusted_judgment patches `trusted_settlement.report_ref`.
  - test_verifier_role_separation patches `_selected_capabilities` and `PRODUCER_TOOL_CAPABILITIES`.
  - test_plugin_portability patches `catalog.find_published_by_pin` and asserts its `await_count`.
  - test_knowledge_served_components spies on `compose_manifest_launch_resolver`.
  - test_search_unavailable patches `routes.permitted`.
  - test_chain_start_gate mocks `canonical.begin` and a fake asyncpg Connection.
- **Bad: seed-history tests.** test_agent_skill_seeds (test_seed_105/106/107, test_run2_skill_successor, stale charter), test_cognition_profile_seeds (revision two/three/four) and test_agent_capability_seeds (revision three recapture) assert the contents of frozen historical seed versions. Keep only the drift checks (bundle equals source), admission and publish-idempotence checks.
- **Naming.** test_w1_*, test_wi0x_* and test_d21_* protect live behaviour. Rename them by behaviour (suggestions are in the TSV reason column) rather than deleting them.

### Deep Agents path: essential protection in this slice

- **Manifest -> compile -> Deep Agents binding:**
  - test_knowledge_manifest: catalog tool rows bind by digest into DeepAgentExecutionBinding; an unbound tool is refused at launch.
  - test_knowledge_served_components: API, relay and worker serve the same components.
  - test_agent_feature_registry: lane features and model tools resolve to a sealed configuration.
  - test_subagent_profile_kinds: Deep Agents overrides.
  - test_chain_compile.
- **Output contracts:**
  - Model-facing boundary: test_submission_foundation (real StructuredTool) and test_w1_tool_boundary.
  - Lane wiring to settlement: test_wi04_lane_settlement (pins at begin, effect/review waits) and test_output_submission_without_knowledge.
  - Contract rules: test_output_fulfillment.
  - GoalDirected convergence: test_w1_convergence_fulfillment and test_d21_iteration_records.
  - Fail-closed without evaluator credentials: test_w1_d30_uncomposed_evaluators.
  - Role separation: test_verifier_role_separation.
- **Context transfer:**
  - The one materializer: test_transfer_materializer.
  - Pure sealed-plan rules: test_transfer_plan.
  - Per-boundary selections: test_transfer_builders and test_wi08_dependent_release.
  - Evaluator isolation and the Deep Agents read tool: test_transfer_review_guards.
  - Verifier current set: test_wi07_current_set_transfer.
  - Packet and seal: test_packer and test_render.
- **Knowledge seam on the lane:** test_knowledge_tools (journal first, exact-digest tool resolution, stop/retry reconciliation), test_gateway, test_independent_evaluators (the evaluator is a Deep Agent with a structured response and no tools).

Gaps:
1. No single in-memory test drives one manifest with named promises through compile, Deep Agents tool projection, `submit_output`, settlement and fulfillment. The pieces are proven separately and joined only in integration/deep_agents/test_wi02_* (outside this slice). A short end-to-end unit test over `tests/support/{knowledge,outputs}.py` would protect the chain at the cheapest level.
2. test_transfer_materializer uses its own `FakeOutputs`, so transfer and fulfillment are not pinned against the same store rules that test_output_fulfillment uses.
3. `LinkedOutputAdoptionService` has no production caller, so linked adoption is reachable only from a test fixture.

### Uncertain calls for the coordinator

- **test_linked_adoption.py DELETE.** `src/mission_control/application/outputs/linked_adoption.py` is never imported in src; only `tests/fixtures/overnight_linked_adoption.py` (used by acceptance/test_overnight_linked) composes it. Either wire it into production (keep the test) or delete the service, the fixture and the test together.
- **test_chain_watcher_start.py REWRITE.** It is 95 lines and cheap; its only problem is a hand-written RunLaunchService. KEEP is defensible.
- **test_unstarted_cancellation.py KEEP.** It wraps `control.execute` to inject a race on the real service. I judged that acceptable for concurrency injection.
- **test_submission_assessment.py KEEP.** It covers the legacy `OutputSelection` path, which toolset.py:1720 still serves when no promises are registered. If that path is being retired, this file and test_output_fulfillment's legacy-refusal test go with it.
- **test_hook_event_mapping.py KEEP.** The mapping is used by the cursor kernel hook script, but `enforcement_gaps` has no src caller even though its docstring says compile uses it.
- **test_overnight_linked_repair.py MERGE.** Check that acceptance/test_overnight_linked.py actually runs the completion-support preflight on that manifest before deleting the unit test.

## F-lanes-conformance


144 files (~817 test functions by metrics.csv). Read-only review; nothing run except one import-only
Python call that printed which scenarios each registered lane runs.

### Counts

| Verdict | Files | Test functions (approx) |
| --- | --- | --- |
| KEEP | 106 | ~572 |
| REWRITE | 34 | ~226 (about 45 of them are cut as conformance duplicates; the rest stay with new imports or doubles) |
| DELETE | 4 | 19 (provider_smoke x3 = 16, cursor/test_relocation = 3) |
| MERGE | 0 as a file verdict | the 3 per-lane mission-layer files are REWRITE with target `tests/conformance/lanes/test_session_controls.py` (9 tests become about 3 parametrized ones) |

Net effect: about 65 test functions go. The structure is already close to what we want. The
conformance suite is one shared contract. Each lane's adapter in `tests/conformance/lanes/adapters/`
puts one fake per provider behind `LaneFake`. Which scenarios a lane must pass comes from its
declared describe, not from the lane itself. The waste is per-lane unit tests that run those same
scenarios again, plus fakes that live in unit directories.

Scenarios the conformance suite runs now (computed from `lanes_for`):
- cursor_local and cursor_cloud: all 11.
- claude_agent_sdk and codex: all except fork_emulation. That one is a declared exception citing `tests/unit/{claude,codex}/test_time_travel.py` and `test_cognition_points.py`, so those 4 files must stay.
- claude_managed: 9 scenarios, no fork and no continuation.
- codex_agents: 8 scenarios.
- deep_agents: describe honesty only. Its other 8 scenarios are exceptions citing files outside this slice.

### Per-lane duplicates to cut (contract already in conformance)

- codex/test_harness: full turn settles, busy send, cancel_turn interrupts, the describe matrix cell by cell (keep the version and identity pins), the interrupt cell following the frozen table (it also monkeypatches `LANE_COMMAND_SEMANTICS`), and cancel without usage. The last one has a stronger twin inside `conformance/lanes/test_session_turns.py::test_codex_interrupted_without_counters...`. That twin is codex-only, so move it to `tests/unit/codex/test_usage.py`.
- codex/test_continuation and claude/test_claude_continuation: the hand-over tests (test_session_controls covers them).
- claude/test_claude_harness: the describe-honesty test and the full-turn test. claude/test_claude_controls: the interrupt_and_inject test.
- anthropic_managed/test_harness: turn settles, unknown usage, no send while busy, reattach, cancel (5 tests).
- openai_agents/test_harness: start/observe/settle, busy/cancel, reattach, unknown usage (4 tests).
- cursor: the busy test in test_cloud_capacity_and_busy, the unknown-usage test in test_cloud_usage_unknown, and the v2 describe-honesty test in test_qualification.
- Mission layer runs before start, an unprepared kit refuses: the same 3 behaviours sit in claude/, codex/ and cursor/ mission-layer files. Make them one conformance scenario parametrized by lane.

After these cuts, each lane keeps only its translation tests: frames and closing facts, wire,
transport, usage accounting, dispatch reconciliation, auth and secret boundaries, discovery, cognition
points, time travel and pack/prepare.

### Canonical doubles (one fake per provider)

| Boundary | Keep (path) | Fold in / fix | Replays recorded real frames? |
| --- | --- | --- | --- |
| Codex app-server | `tests/unit/codex/fixture_app_server.py` (`FixtureLauncher`, `FixtureAppServer`, `MemoryChannel`) plus `fixture_hooks.py`; scripts in `tests/fixtures/provider_frames/codex/scripts/*.jsonl` | Move to `tests/fixtures/codex_app_server.py` (22 users, including conformance and integration) | Partly. The scripts are hand-written (`"recorded": false`), but `test_schema_pin.py` validates every emitted event against the real JSON schema generated from codex-cli 0.162.x. `hooks_list/trust-0.162.1.json` and `projections/discovery/codex.recorded.json` are real recordings (`test_hook_trust`, `test_discovery`). This is the best lane and the model for the others. |
| Claude Agent SDK | `tests/unit/claude/fixtures.py::FixtureClient` (replays `provider_frames/claude/*.jsonl` through the real `parse_message`) for in-process work; `fake_cli.py::FakeCli` (a subprocess driven by the real `ClaudeSDKClient` and transport) for the resume proof | Move FixtureClient to `tests/fixtures/claude_sdk.py` (29 users). FakeCli should replay the same jsonl records so there is one frame source. | No. All 9 jsonl files are hand-written from the pinned SDK 0.2.165 (`"recorded": false`). The real SDK parser checks their shape. `discovery/claude_agent_sdk.recorded.json` is real but serves discovery only. |
| Cursor SDK bridge (local) | `tests/fixtures/cursor_local.py::ReplayBridge` / `ReplayBridgeLauncher` over `tests/integration/cursor/fixtures/local/*.jsonl` | none | No. Every file says "synthetic: hand-authored ... replace with a scrubbed recording in FT-G6". |
| Cursor Cloud Agents API | `tests/fixtures/cursor_cloud.py::FakeCloudApi` (an `httpx.MockTransport` over `integration/cursor/fixtures/cloud/*.sse` and `*.json`) | Replace the private-attribute AsyncMocks in test_cloud_workspace_and_resume and test_run2_cursor with FakeCloudApi state | No (synthetic SSE, same FT-G6 note). |
| Cursor environments API | `tests/fixtures/cursor_environments.py::FakeEnvironmentsApi` | none | No (shapes from the MO-13 drill notes). |
| Anthropic Managed Agents | `tests/fixtures/managed_agents.py::FakeManagedAgentsApi`, with `tests/fixtures/managed_lane.py` as the stack builder | Move `_started` (test_harness) and the `prepare` helper (test_prepare) into managed_lane | No. Shapes come from the pinned anthropic 1.13.0 types and the HL-23 smoke sequence. The paid smoke ran, but its frames were never committed as fixtures. |
| OpenAI Agents API | `tests/unit/openai_agents/support.py::FakeAgentsApi`, extended by `tests/fixtures/agents_lane.py::SessionsApi` | Move FakeAgentsApi, Recorded and SHIPPED_PACK to `tests/fixtures/agents_api.py`. Right now a `tests/fixtures` module imports a unit module, which inverts the layering. | No (shapes from the pinned openai 3.29.0 source). |
| Remote Session base hooks | `tests/unit/remote_session/support.py::ScriptedRemoteLane` | none | Not applicable. It is the right provider-neutral fake for the base. |
| Frames reader | `remote_session/hosted_support.py::InMemoryFramesOf` | Could become the src `adapters/remote_session/time_travel.ScopedFrameReader` over `InMemoryFrameStore` | Not applicable. |
| Artifacts port | `tests/fixtures/cursor_local.py::MemoryArtifacts` | Delete the duplicate `tests/unit/codex/support.py::MemoryArtifacts`, which `claude/test_time_travel` imports | Not applicable. |
| Clock | many | `provider_auth/test_usage_admission.py::FakeClock` and `secrets/test_minting.py::Clock` should become one clock in tests/fixtures | Not applicable. |

The highest-value next step is recorded replay. Capture one scrubbed real session per secondary
lane: Cursor local (`FT-G6`), Cursor cloud, Claude, Managed and Agents. Commit each with a pin file,
the way Codex does, and add a `test_schema_pin`-style check that the fake's frames validate against
the recording or schema.

### Shared builders that must move out of test modules

- `tests/unit/operations/test_operation_execution.operation_request`: imported by `claude/fixtures.py` and `codex/support.py`. Move it to tests/fixtures. Another slice owns the source file.
- `conformance/resolution/test_resolver_conformance` (`_registration`, `_resolver`, `_selection`): move to `conformance/resolution/fixtures.py`. Used by test_model_catalog_pairing and unit/harness/test_model_listing.
- `codex/test_kernel_hooks` (`kernel_projection`, `kernel_operation`, `HookRig`, `hook_rig`, `kernel_stack`, `run_turn`): move to the codex fixture module. Used by 3 integration files and harness/test_local_lane_child_environments.
- `codex/test_harness.BOUNDS`, `claude/test_claude_harness` (`_frames`, `_identity`, `_turn`, `_fields`) and `frames/test_frame_boundary_points.frame`: move to the lane fixture modules.
- `anthropic_managed/test_harness._started` and `test_prepare` (`AI_ENGINEER_PACK`, `prepare`): move to `tests/fixtures/managed_lane.py`. `openai_agents/test_prepare._preparer` moves to `tests/fixtures/agents_api.py`.
- `approvals/test_approval_broker` (`OWNER`, `_compose`) and `effects/test_hosted_bundle_publication`: imported by both lanes' test_tools. They need a `tests/fixtures/approvals.py`.
- `harness/test_hook_callback` (`Stack`, `_context`), `harness/test_cursor_cloud`, `harness/test_lane_turn_points._attempt` and `operations/test_lane_outputs`: imported by codex/test_codex_hook_mapper and by cursor's cognition-points and knowledge-output-channels tests.
- Sibling imports inside cursor/: `test_local_reconcile_and_rehydration._fresh`, `test_run2_released_bridge_sweep.lease` and `test_cognition_points` (`settled_points`, `unit_changes`). Move them to `tests/unit/cursor/support.py`.
- `integration/claude/test_claude_live_qualification._operation`: imported by `unit/claude/test_claude_live_drill.py`.

### Patterns

- Good: conformance claims are derived from the describe, and exceptions must cite evidence that exists (`contract.py`, `test_registry.py`). Session scenarios drive the production `LaneTurnService` and the mailbox, not the fake alone (`test_session_turns.py`).
- Good: the fake is checked against a real artifact. See `codex/test_schema_pin.py` (generated schema) and `codex/test_hook_trust.py` (recorded hooks/list). Both are also labelled honestly (`"recorded": false` / `synthetic`), and `codex/test_harness::test_fixture_scripts_are_labelled...` enforces the labels.
- Good: the provider-neutral base is tested with a scripted provider (`remote_session/test_lane.py`), and each lane then only adds translation.
- Bad: per-lane suites run the conformance scenarios again (see the list above). Examples: `anthropic_managed/test_harness.py` and `openai_agents/test_harness.py`.
- Bad: internal mocks in secondary-lane tests. `openai_agents/test_harness.py` patches `harness._client.retrieve_*` and `harness._root_turns`, then calls the private `_initial_action_turn`. `cursor/test_cloud_workspace_and_resume.py` replaces `harness._publisher.head` and `harness._read_turn` with AsyncMocks. `cursor/test_run2_released_bridge_sweep.py` patches `workspace_leases.begin` and `advisory_lock`; that Postgres guard belongs in an integration test on the disposable DB.
- Bad: canonical fakes live under `tests/unit/<lane>/` while conformance and integration import them (codex support, used by 34 files; claude fixtures, used by 29).
- Bad: `cursor/test_run2_*`. Six files carry sprint names over live behaviour: bridge errors, bridge recovery, cost, conversation. Rename them and keep the behaviour.
- Bad: a compatibility shim that only tests use (`adapters/cursor/git_workspaces`, pinned by `test_relocation.py`).

### Deep Agents path

Two parts of this slice are essential for Deep Agents:
- `conformance/lanes/compile/*`: `deep_agents.py` is the real compile on the canonical items and vendor pins, and is also imported by unit/deep_agents/test_compile and test_model_routes.
- `test_compile_conformance.py`, `test_registrations.py`, `conformance/resolution/*`, the deep_agents describe honesty (`adapters/governed.py`), and the lane-neutral `provider_auth/*` and `secrets/*` contracts.

Gap: deep_agents runs describe honesty only in the shared session contract. Its 8 other scenarios are
exceptions citing `tests/unit/harness/test_lane_registry.py`, `tests/acceptance/control_plane/test_wp_cp_040.py`,
`tests/unit/operations/test_rrm_009_cancellation_composition.py`, `test_rrm_008_cancellation.py`,
`tests/unit/run_control/test_ft_f1_command_mailbox.py`, `test_ft_f4_fork_instruction.py`,
`tests/unit/operations/test_ft_f2_interrupt_and_inject.py`, `test_fork_reuse_execution.py` and
`test_operation_execution.py`. Most of those are sprint-named, so other slices may delete or rename them.
`test_registry.py` will then fail until `governed.py` is updated in the same change.

The stronger fix is a Deep Agents `LaneAdapter.open()` over the scripted chat model and the
`ConformanceRuntime` (src `adapters/operations/conformance.py`). With it, the primary lane passes the
same start/observe/settle, cancel, budget-stop and unknown-usage scenarios as every secondary lane,
instead of being exempt.

### Uncertain calls for the coordinator

- `provider_smoke/*` DELETE: these test the offline logic of the one-off paid smoke scripts in `scripts/provider_smoke`, which only archived docs reference. Delete the scripts too, unless the owner still re-runs them before qualifying claude_managed or codex_agents.
- `applications/test_live_describe_conformance.py` REWRITE: the KS-capture conformance is valuable, but about half the tests cover the CLI of `scripts/sprint_oc_describe_conformance.py`, and no make target runs that script.
- `claude/test_claude_live_drill.py` REWRITE, not DELETE: it ties the drill's record writer to the gate in `conformance/lanes/records.py` that flips `qualified`.
- `cursor/test_relocation.py` DELETE requires repointing 3 test imports (`tests/unit/workspaces/*` and `tests/integration/postgres/test_workspace_lease_races.py`) and removing the shim module in the same change.
- `cursor/test_run2_released_bridge_sweep.py` and `test_run2_active_bridge_recovery.py` protect safety rules (never kill a pid, refuse uncertain ownership). Rewrite them rather than cut them, even though the lane is secondary.

## G-unit-misc1


115 files (113 test modules plus 2 helper modules under tests/unit/workspaces). Every `mission_control.*` and `biotech_mission_adapters.*` module these files import still exists in src, integrations/biotech/src or packages, so no file here tests a deleted code path.

### Counts

| Verdict | Files | Test functions (approx) |
| --- | --- | --- |
| KEEP | 81 | 553 |
| REWRITE | 32 | 251 |
| DELETE | 2 | 5 |
| MERGE | 0 | 0 |

22 of the 32 REWRITEs are restructure-only. Their assertions and doubles are fine, but they import builders from other `test_*.py` modules. The other 10 need real double changes: test_contract_digest_set_order, test_coordinator_security_audit, test_root_result_materialization, both test_w1_* files, test_transcript_projection_trigger, test_bootstrap_dispatch, test_cursor_native_identity, test_preflight and test_runtime_definition.

The two DELETEs are test_coordinator_acceptance_evaluator and test_coordinator_evaluation_dataset. They test `scripts/evaluate_coordinator_acceptance.py` and a JSON dataset. No Makefile, dev script or src file references either one; grep finds them only in the archived `docs/specs/archive/mc-surfaces-2026-10/docs/REMOVAL_GUIDE.md`. The two scripts and `tests/fixtures/coordinator_retrieval_evaluation.json` can go with them.

### Canonical doubles this slice needs

| Boundary or port | Keep | Fold in | Why it is needed |
| --- | --- | --- | --- |
| Frame store and reader (FrameSink / FrameReader) | src `application/frames/sink.py:InMemoryFrameStore` for write paths; `tests/fixtures/transcripts.py:StaticFrames` for fixed-list reads (or add an `InMemoryFrameStore.seeded(frames)`) | `FakeFrames` (frames/test_replay.py), `_Frames` (frames/test_run_cost.py), `FakeFrames` (operations/test_point_reconciliation.py) | Pure frame-to-fact, transcript, replay and cost tests without PostgreSQL. No shared scenario module pins InMemoryFrameStore to the Postgres frame store (see Deep Agents gap). |
| Artifact metadata repository | src `application/artifacts/artifact_promotion.py:InMemoryArtifactMetadataRepository` | `Metadata` (test_artifact_download, test_transcript_full_bodies), `NoMetadata` (test_replay), `_NoMetadata` (test_frame_writer) | The grant-checked body reader needs a metadata lookup. |
| Transcript document store | `MemoryDocuments` (frames/test_run_list_and_search.py), moved to tests/fixtures/transcripts.py | `_Documents` (frames/test_transcript_projection_trigger.py) | Search and projection without Postgres FTS. |
| Mission events | `tests/fixtures/transcripts.py:InMemoryMissionEvents` | none | Already canonical. |
| Coordinator facade (MCP interface tests) | `FakeFacade` (coordinator/test_coordinator_mcp_read_surface.py), moved to tests/fixtures/coordinator_facade.py | none; 8 importers | Interface tests for the MCP tool, resource and auth shapes without composing the real facade. `concrete_facade` (test_coordinator_facade) stays the real-composition path. |
| Workspace provisioner | `RecordingProvisioner` (workspaces/test_workspace_materialization.py), moved to tests/fixtures/workspace_materialization.py | none; 5 importers | Stands in for the sandbox or filesystem provisioner; the real filesystem provisioner is exercised beside it. |
| Owner prerequisite repository | src `application/prerequisites/service.py:InMemoryOwnerPrerequisiteRepository` | Replace the `AsyncMock` stored/check collaborators in test_runtime_definition and the four composition patches in test_preflight and test_cursor_native_identity | The same flows run on Postgres in integration/postgres/test_owner_prerequisites.py, which is a good pairing. |
| Scripted chat model (LLM boundary) | One module, e.g. tests/fixtures/scripted_models.py | `SkillReadingModel` (tests/acceptance/control_plane/test_wp_cp_040.py) and the local `Scripted` model in frames/test_deep_agents_frames.py | The LLM is the boundary for real `create_deep_agent` runs. Check other slices for more copies. |
| Temporal client in bootstrap probe | Inject a client and an `InMemoryRunControlRepository` into `InstalledBootstrapProbe` | Patches of `owner_probe.Client.connect`, `owner_probe.PostgresRunControlRepository` and `owner_probe.asyncio.wait_for` | Lets the sanitized-failure and timeout-cancel rules be tested without patching module globals. |
| Provider HTTP (Managed Agents, trusted probes, CLI-to-API) | `httpx.MockTransport`, and the ASGI bridge in test_transcript_interfaces | none | Already the right boundary. |
| S3 / Neo4j / embeddings / external registry | `_S3` (control_plane), the Neo4j `_Driver`/`_Session` (schema), `DeterministicEmbeddings`, `FakeDiscovery`/`FakeInspection` | none | True boundaries, one copy each in this slice. |

### Shared builders to move out of test modules

- `tests/unit/run_control/test_run_control.py` (service, command, request, actor, ALL_PERMISSIONS) -> tests/fixtures/run_control.py. Imported here by test_frame_facts, test_frame_ordering, test_run_list_and_search, test_w1_*, test_runtime_definition and test_contract_digest_set_order.
- `tests/unit/authoring/test_manifest_v2_launch.py` (_compile, example, bindings, templates_of, SCOPE), `test_manifest_v2_environment.py` (KIT_PIN, RESOLVED, SECRET_REFS, compile_text, manifest), `test_manifest_compile.py` (http_app, minimal, service) and `test_manifest_interfaces.py` (FakeLifecycle, manifests) -> tests/fixtures/manifests.py.
- `test_preflight.definition`, `test_owner_bootstrap.probe_template`, `test_trusted_probes.record_for/configured` -> tests/fixtures/owner_prerequisites.py (already exists).
- `test_coordinator_launch_preparation` (launch_fixture, FixtureSemanticBindingProvider, NOW, SCOPE), `test_coordinator_facade.concrete_facade` and `test_coordinator_mcp_read_surface.FakeFacade` -> tests/fixtures/coordinator_launch.py and coordinator_facade.py.
- `test_root_result_materialization` (root, family_result, SCOPE), `test_w1_family_failure_terminalization._request`, `test_w1_d26._stuck_unit` and `test_rrm_016` (_claim, _composition, _preparation) -> tests/fixtures/goal_directed_journaled.py. Integration temporal tests import these too.
- `test_transcript_interfaces` (transcript_service, http_app, _cli_transport) and `test_run_list_and_search.MemoryDocuments` -> tests/fixtures/transcripts.py.
- `test_provider_lanes` (load, claude_observations, codex_app_observations, persisted) -> tests/fixtures/provider_lane_observations.py. Postgres lineage tests import these.
- `test_frame_boundary_points` (frame, a_turn, usage) -> tests/fixtures/provider_frames.py.
- `test_harness` (compatibility, mcp_release) -> tests/fixtures/projections.
- `test_control_plane` (configured_service, invocation, publish, authority) and `test_agentic_asset_definitions` (skill/server/tool definitions, service, publish) -> tests/fixtures/control_plane.py.
- `test_workspace_materialization` (RecordingProvisioner, owner, request, service), `test_goal_role_slot_ownership._goal_request` and `test_artifact_promotion.promotion_fixture/CONTENT` -> tests/fixtures/workspace_materialization.py.
- `tests/unit/workspaces/workspace_fixtures.py` (12 importers, including integration) -> tests/fixtures/git_workspaces.py. `lease_scenarios.py` -> tests/conformance/workspace_leases.py.
- `test_schema_grounding_services._reconciliation_fixture` -> tests/schema_context_helpers.py.
- `tests/integration/postgres/test_operation_journal_stage1` builders, which a unit test (test_transcript_projection_trigger) imports -> tests/fixtures/operation_journal.py.

### Patterns

Good:
- Shared scenario functions run against both the in-memory and the PostgreSQL store: workspaces/lease_scenarios.py, used by test_workspace_lease_ledger and integration/postgres/test_workspace_lease_races. This is the model for every port fake, and the frame store should get the same.
- Fault injection by subclassing the src InMemory* class, not with a new fake: `FailOnceRetrievePayloadStore(InMemoryArtifactPayloadStore)` and `LoseFirstAdmissionResponse(InMemoryArtifactDurableReferences)` in test_artifact_promotion.
- Real infrastructure instead of mocks: real git (test_workspace_allocation, test_workspace_snapshots), real bash (test_mission_layer), the projected hook scripts run as subprocesses against a stdlib HTTP listener (test_signal_hook, test_hook_runner), and the real FastAPI app over an ASGI transport (test_transcript_interfaces).
- In prerequisites, AsyncMock mostly appears as "a secret broker that raises if called" (test_claude_native, test_cursor_native). That proves the credential boundary is never touched and is legitimate.

Bad:
- Unit tests of the `mission_run` root workflow that patch `temporalio.workflow.execute_activity/start_activity/now/patched/info` and `BellLabsRunWorkflow.run` (test_root_result_materialization, test_w1_family_failure_terminalization). Real-server tests already exist in tests/integration/temporal/test_w1_family_failure_root.py.
- Patching composition module globals instead of injecting them: four `monkeypatch.setattr(composition, ...)` calls repeated in test_preflight (twice) and test_cursor_native_identity.
- A unit test importing integration-test builders (test_transcript_projection_trigger), and a digest test importing 9 test modules (test_contract_digest_set_order).
- A fake asyncpg pool standing in for a Postgres repository with no integration counterpart (test_coordinator_security_audit, `_AuditPool`).
- Sprint names on live behaviour: test_w1_d26_liability_terminalization and test_w1_family_failure_terminalization should become one test_family_failure_terminalization.py.

### Deep Agents path: essential protection in this slice

- Frames: test_deep_agents_frames (a real `create_deep_agent` run produces ordered, deduplicated frames with subagent namespaces, and a stop is told apart from a model answer), test_frame_writer, test_frame_facts (Deep Agents lifecycle synthesis rows, facts applied once to the reducer), test_frame_contracts_and_body, test_run_cost (Deep Agents usage frames).
- Configuration and binding: test_host_projection (Deep Agents secret refs stay unresolved; skill source order), test_network_policy (finite worker tool grants), test_environment_preparation (Deep Agents roles are not cited), test_preflight (Deep Agents needs no unselected accounts), test_generators, test_control_plane (publish/compile/ERC), test_contract_digest_set_order and test_digest_set_order_guard (sealed digests stable).
- Launch and settlement: test_coordinator_launch_preparation, test_coordinator_launch_idempotency, test_coordinator_semantic_binding_integration, test_coordinator_result_completion, the family-failure service tests (both w1 files), and test_transcript_projection_trigger (settlement outbox to projection).
- Gaps:
  1. No shared scenario module runs the same frame append/read/generation-fence cases on InMemoryFrameStore and the Postgres frame store. Only the provider_lanes observations are reused, through test-as-library.
  2. The Deep Agents frames-to-facts-to-settlement chain is proven in pieces (writer, facts, reducer). No unit-level test feeds `deep_agents_turn_frames` through the reducer to an attempt settlement and transcript projection in one flow. Check whether integration covers it.
  3. If the 2 patched root tests in test_root_result_materialization are deleted, "the root waits for the persisted result" must be proven on WorkflowEnvironment. I could not confirm that integration covers that exact case.

### Uncertain calls for the coordinator

- test_root_result_materialization: whether tests/integration/temporal (test_wi13_nested_temporal, test_ft_c4_run_list, test_w1_family_failure_root) covers "root waits for persisted result with a retryable same payload" and the "pre-patch replay has no new activity" case. If not, write that test before removing the patched unit tests.
- tests/unit/schema (17 files, about 70 tests) test `biotech_mission_adapters` from integrations/biotech, not the kernel. They are KEEP for the integration's sake, but they are secondary to the owner goal and belong in an integrations/biotech test tree. They depend on the environment: 7 tests (catalog_core 3, workspace 2, source 1, authority_issuance 1) skip unless `BIOTECH_SCHEMA_SDL_PATH` names the sibling Biotech checkout (tests/fixtures/sibling_checkouts.py). In a CI checkout of this repository alone they never run. Either vendor a pinned copy for CI or accept them as opt-in.
- Also noted in passing: integrations/biotech/AGENTS.md says the kernel must never import `biotech_mission_adapters`, but `src/mission_control/adapters/deep_agents/runtime_persistence_verifier.py` does. This is outside the test review but on the Deep Agents adapter.
- test_catalog_seed_bundles::test_every_applied_seed_matches_recorded_live_130_receipts pins a dated qualification receipt file. It could be deleted if the "never rewrite an applied logical key" tests are judged sufficient.
- test_frame_retention::test_expire_activity_keeps_the_pre_144_report_shape_additively is a compatibility pin. Delete it if startup mode drops the old report shape.
- test_bootstrap_dispatch: the first test duplicates integration/temporal/test_owner_bootstrap_runtime. The other two (sanitized failure, timeout-cancel ordering) exist only here, so they should be rewritten, not deleted.

## H-unit-misc2


129 files: 120 test modules and 9 support modules (approvals/fixtures, human_tasks/fixtures, guide/support, socketio/harness, streams/fakes, watchers/fakes, and others). Counts come from metrics.csv `tests`. These are regex counts of test functions; parametrized cases are not expanded.

| Verdict | Files | Test functions | Lines |
| --- | --- | --- | --- |
| KEEP | 70 (9 of them support modules) | ~470 | ~15.6k |
| REWRITE | 35 | ~250 | ~9.1k |
| DELETE | 24 | ~153 | ~5.5k |

Almost every REWRITE is a restructure only. The assertions stay. The change is to stop importing builders from other `test_*.py` modules. Only four REWRITEs replace an internal mock: `human_tasks/test_manifest_gate_lowering`, `socketio/test_realtime_controls`, `mission_control/test_completion_evidence` and `config_api/test_server`.

The 24 DELETEs are the top-level `test_qualia_*` (9), `test_overnight_*` except `test_overnight_evidence` (9), `test_aieng_*` (3) and `test_report_source_*` (4). Each one tests a scenario-builder module under `tests/fixtures` or a fixture-setup script, not `src`. Removing them also frees about 13k lines of `tests/fixtures/{qualia,overnight,aieng}_*.py`, but there are dependencies, covered under the uncertain calls below.

### Top-level scenario drills: what each actually protects
- **Re-prove historical evidence (DELETE).** All `qualia_*`, `overnight_*` (except `test_overnight_evidence`), `aieng_*` and `report_source_*` files. They exercise fixture code: `QualiaKnowledgeBridge`, `qualia_web_tools`, `SpendLedger`, `QualiaForkPrograms`, the `overnight_*` probes and scripted models, and the `scripts/report_source_*` setup.
  - Where they touch `src`, the behaviour is already covered:
    - The knowledge gateway and tools: `tests/unit/knowledge/test_gateway.py`, `test_knowledge_tools.py`, `test_trusted_judgment.py`.
    - Browser network grants: `integrations/test_capability_pins_and_runtime_ports.py`.
    - F1 verifier and fork admission: `integration/postgres/test_manifest_fork_admission.py`, `test_manifest_submit.py`.
    - Manifest compile: `tests/unit/authoring`, `guide/test_mission_templates.py`.
  - Several of them assert errors raised by the fixture itself. Examples: `test_qualia_fork_contract` expects `AssertionError("unprepared fixture variant")`, and `test_overnight_linked_cancellation` patches `RunControlLifecycleGateway.execute` and tests the probe.
- **Protect live operator tooling (KEEP, move to `tests/unit/scripts/`).**
  - `test_experiment_loop_driver.py`: the Sprint OC experiment loop, which still has open iteration-3 items.
  - `test_sprint_oc_fixture_driver.py`: the W1 driver, and W1 is unreleased. It asserts that terminal success is not acceptance.
  - `test_overnight_evidence.py`: `scripts/overnight_evidence.py`, which both drivers import. Rename it `test_evidence_export.py`.
  - `test_documentation_retrieval.py`: docs tooling. Move it to `docs_tools/`.

### Canonical doubles this slice needs
| Boundary | Keep (path) | Fold in | Why needed |
| --- | --- | --- | --- |
| Wall clock | new `tests/fixtures/clock.py` built from `tests/fixtures/checkpoint_recovery.MutableClock` (settable plus advance) | `Clock` in approvals/fixtures.py and integrations/test_async_subagent_submission_fence.py, plus 8 more `class Clock` outside this slice (harness, prerequisites, run_control, secrets, subscriptions x3), `StepClock` x2, `SteppingClock` | Deadlines, leases and expiry need deterministic time. |
| LLM (scripted chat model) | `tests/fixtures/checkpoint_recovery.ScriptedRecoveryModel`, moved to `tests/fixtures/scripted_models.py` | `_Scripted`/`ParentModel`/`ChildModel` (integrations/test_sync_subagent_usage_and_lineage), `GoalScriptedModel`, `ScriptedWorker` | Deep Agents cognition without provider spend. |
| Agent Protocol server (async children) | `tests/fixtures/fake_agent_protocol.FakeAgentProtocolClient` | none in this slice | Hosted async subagent runs. |
| Stream source port | `tests/unit/streams/fakes.FakeStreamSource` | none (it is already canonical, with a PostgreSQL twin in integration) | Socket and stream tests. |
| Signal ingress store port | `FakeStore` in `signals/test_ingress_service.py`, moved to `tests/unit/signals/support.py` | `DedupingStore` (test_provider_wake) can subclass it | No src InMemory store exists for signals. |
| Watcher store and run gateway | `tests/unit/watchers/fakes.{MemoryWatcherStore,FakeRunGateway}` | none | Already canonical. |
| Definitions and search ports | src `InMemoryDefinitionRepository` and `InMemoryCatalogSearchRepository` | `FakeDefinitions`/`FakeSearch` in selection/test_selection_workspace, which used by 8 files. Keep `FakeSearch` only for the "unavailable" mode. | Prefer the src fakes. |
| External candidate repository | src `InMemoryExternalCandidateRepository` | `RecordingCandidates` (web_research/test_external_capability_discovery) | One port fake. |
| Approval, human-task and stop-fence ports | src `InMemoryApprovalStore`, `InMemoryHumanTaskRepository`, `InMemoryStopFenceRepository` | none | Already used correctly. |
| Neo4j driver | the local `_Driver`/`_Session`/`_Cursor` pairs in both integrations/test_neo4j_* | merge into one `integrations/biotech/tests/neo4j_fakes.py` | External database driver. |
| Temporal client | `RecordingTemporalClient` (mission_control/test_temporal_identities), plus `WorkflowEnvironment` elsewhere | none in this slice | Submission identity without a server. |

### Shared builders that must move out of test modules
- `tests/unit/run_control/test_run_control` (`request`, `service`, `actor`, `command`, `DIGEST`, `WORKFLOW_DIGEST`) -> `tests/support/run_control.py`. In this slice it is used by config_api/test_server, mission_control/test_public_interfaces, test_run_evidence, test_runtime_interfaces, test_temporal_identities, socketio/test_realtime_controls and integrations/test_async_subagent_submission_fence.
- `selection/test_selection_workspace` (CATALOG_SCOPE, ROWS, RESEARCH, REVIEW, OPEN/NARROW_WORKFLOW, FakeDefinitions, FakeSearch, _pin, _published, _registration, _workspace, _draft) -> `tests/unit/selection/support.py`. Used by guide/support.py and 6 guide and selection tests.
- `authoring/test_manifest_compile` (scope, service, AT, minimal, text) -> `tests/unit/authoring/support.py`. Used by guide/test_manifest_reference, guide/test_mission_templates and watchers/test_watcher_catalog.
- `architecture/test_package_boundaries.APPLICATION_NEEDLES` -> `tests/support/boundaries.py`. Used by guide/test_guide_service and test_mission_templates.
- `acceptance/control_plane/test_wp_cp_040` (exact, exact_fixture, planned_invocation, registry, unit_bound) and `test_wp_cp_045` (contract, request, SERVED, GRAPH_BINDING_DIGEST), `unit/operations/test_async_child_parent_budget` (admitted_parent, spawn) and `fixtures/rrm013_live_stack.reconciler` -> `tests/fixtures/deep_agents_subagents.py`. Used by integrations/test_async_subagent_submission_fence, test_sync_subagent_usage_and_lineage and test_capability_directory_bundles.
- Goal review builders:
  - `orchestration/test_rrm_016_goal_directed_settlement._preparation` and `orchestration/test_wp_bp_020_goal_directed` (_blueprint, _claim, _execution, _verification) -> `tests/fixtures/goal_directed.py`. Used by human_tasks/test_goal_review.
  - `operations/test_operation_execution` (operation_request, MCP_DIGEST, SKILL_DIGEST, service_fixture) -> `tests/fixtures/operation_execution.py`. Used by test_goal_review and integrations/test_capability_pins_and_runtime_ports.
- `approvals/test_approval_task_interfaces` (_app, _compose, _principal, BASE) -> `approvals/fixtures.py`.
- `socketio/test_mission_socket` (FixtureResolver, Lifecycle, auth, build) -> `socketio/harness.py`.
- `streams/test_stream_service` (service, subscription, mission_at, frames_at, READER, execution_subscription), `test_stream_pump` (FAST, Recorder, until) and `test_stream_lineage` (run_pump, stop, rekeyed) -> `streams/fakes.py`. Also `frames/test_lineage_stream` (claude_frames, codex_frames) -> `tests/fixtures/provider_frames`.
- `signals/test_ingress_service` (FakeStore, TOKEN, service) and `test_drainer.item` -> `signals/support.py`.
- `watchers/test_watcher_planner` (plan, watcher, signal) and `test_watcher_manifest` (definition, event_wait_document) -> `watchers/fakes.py`.
- `mission_control/test_run_evidence` (ACTOR, DIGEST, NOW, setup) -> `mission_control/support.py`.
- Smaller moves: `integrations/test_capability_directory_bundles.source` -> `tests/fixtures/capability_bundles.py`. `schema/test_graph_query_intents._intent` -> the biotech test support. `web_research/test_web_research_semantic_handlers` runtime constants -> the biotech test support.

### Patterns worth reporting
- **Good: real transports in process.**
  - approvals/test_governed_gateway runs the real fastmcp protocol over the in-memory transport.
  - socketio/test_mission_socket uses a real uvicorn server with python-socketio clients.
  - guide/test_guide_interfaces and selection/test_selection_interfaces route `missionctl` into a TestClient, which gives HTTP, CLI and MCP parity with no mocks.
- **Good: anti-drift tests against the real surface.** guide/test_guide_surface and skills/test_coordinator_bundles check every operation, tool and command a page names against the real operator server and the argparse tree.
- **Bad: product code living in tests/fixtures.**
  - `scripts/aieng_watch_mission.py` (the current 2026-11-15 watch) imports `tests.fixtures.aieng_watch_tools` and `scoped_api_stack`. The deterministic watch model sits in `tests/fixtures/rrm009_production_stack`.
  - `scripts/{aieng,qualia}_stagegraph.py` import `tests.fixtures.{aieng,qualia}_stagegraph`, and `tests/fixtures/qualia_knowledge` imports `scripts.overnight_evidence`.
  - The live Tavily/Firecrawl/KS-bridge Deep Agents tool components exist only as fixtures.
- **Bad: tests of test helpers.** All the qualia, overnight and aieng unit tests, and fixtures/test_tcp_proxy (acceptable because acceptance tracing uses it).
- **Bad: Biotech application tests in the kernel unit tree.** These files import `biotech_mission_adapters`: web_research/{admission, live_adapters, semantic_handlers, scenario_d, run_..._live}, reference_research/* and integrations/test_neo4j_*. `integrations/biotech/AGENTS.md` says to retain them, so the verdict is KEEP plus relocate to `integrations/biotech/tests`. The directory `web_research/` also holds three kernel files (external_candidate_quarantine, external_capability_discovery, quarantine_static_inspection), which belong in `unit/capabilities/`.
- **Bad: internal patches where injection exists.** `monkeypatch(socket_commands.mission_service)` in socketio/test_realtime_controls. `monkeypatch(goal_human_review, _human_gate_nodes)` in human_tasks/test_manifest_gate_lowering. The private `_decision` in mission_control/test_completion_evidence.

### Deep Agents path: essential protection in this slice
- integrations/test_async_subagent_submission_fence (23 tests): async children fence, in_doubt, orphan, adopt and pending usage.
- integrations/test_sync_subagent_usage_and_lineage: a real `create_deep_agent` sync child, usage charged to the parent, and credential lineage.
- integrations/test_capability_directory_bundles, test_capability_pin_forms and test_capability_pins_and_runtime_ports: skill and MCP pins, materializer compatibility and browser host grants.
- human_tasks/test_goal_review and test_manifest_gate_lowering: GoalDirected review and lowering manifest gates to StageGraph gates.
- mission_control/test_temporal_identities: Temporal ids and linked roots. test_api_event_loop: the Deep Agents time-travel loop guard.
- guide/test_mission_templates: every template compiles on the real compile service. domain/knowledge/test_knowledge_identities.
- **Gaps:**
  - The current AI Engineer watch tools (`tests/fixtures/aieng_watch_tools.py`, the Build 08 loop 8 Deep Agents node tools) have no unit test, and they live outside `src`.
  - Deleting the qualia tests removes the only tests of the Deep Agents web-search tool components (shared spend ceiling, repairable versus fatal vendor errors, citation provenance). If those tools are meant to be product, they need a `src` home (`adapters/deep_agents/web_tools`) and fresh behaviour tests.

### Uncertain calls for the coordinator
1. Qualia, overnight and aieng DELETEs have dependencies that break if the fixtures are removed:
   - `scripts/qualia_stagegraph.py` and `scripts/aieng_stagegraph.py`, both completed paid fixtures.
   - `tests/acceptance/mission_control/test_overnight_{stagegraph,goal_directed,linked}.py`.
   - `tests/unit/run_control/test_qualia_{controls,control_api,scenarios}.py`, `integration/postgres/test_manifest_fork_admission.py` and `unit/authoring/test_schema_only_stage_inputs.py`.
   - Decide them together with the slices that own those files. `tests/fixtures/aieng_watch_tools.py` does not depend on qualia and must survive.
2. `test_report_source_*`: delete them together with `scripts/report_source_*.py` and docs/REPORT_SOURCE_FOUNDATION.md. Keep them only if the W1/W2 foundation fixture is still planned.
3. `web_research/test_run_web_research_coordinator_live.py` and `test_scenario_d_execution_correction.py` are scenario-named Biotech runner tests. I kept them for relocation; the alternative is to delete them if the Biotech Viome/Scenario-D runner is retired.
4. `test_sprint_oc_fixture_driver.py` and `test_experiment_loop_driver.py` are kept only while W1 and the experiment loop are open. Retire them with those programs.
5. integrations/test_capability_pins_and_runtime_ports has four `pytest.skip`s on the workspace layout. These conflict with the rule against hiding a missing checkout behind a default skip.

## I-integration-postgres


All files run on a real disposable PostgreSQL 17. `common_db` installs the **newest built release**
(`releases/1.16.0`), so a file pins current behaviour unless it builds a dated release itself.
Every `mission_control.*` import in the slice resolves (an AST check against `src/`), and no file
tests a retired module. The suite was not run, so a pass or fail on any file is unknown.

### Counts
| Verdict | Files | Test fns |
|---|---|---|
| KEEP | 119 | ~346 |
| REWRITE | 23 (5 helpers + 18 tests) | ~63 |
| MERGE | 7 | ~16 |
| DELETE | 5 | ~8 |

KEEP target column = the proposed consolidated home (organisational move only; no test is dropped).
MERGE = the behaviour is already covered or belongs in the target file; move only what the reason says.
Single tests to drop inside REWRITE files:
- `test_chain_release::test_legacy_packet_fixture_explicitly_preserves_historical_binding_scope` (it asserts its own fixture).
- `test_postgres_workflow_result_repository::test_production_composition_uses_only_application_pool_for_results` (private attributes, fake pools).
- `test_wi07_collections_postgres::test_the_released_guard_refuses_collection_members_that_0066_admits` (a 1.8.0 vs 0066 diff).
- The upgrade case in `test_capability_search_release_1160`.

### (1) Dated release proofs vs current behaviour
Dated (they install `releases/<x.y.z>` or a candidate migration, not the newest release):
- **DELETE** (install/upgrade only; package `test_install`, `test_release_*_prefix` and the newest-release adapter tests cover them): run2_release_142/143/144, sprint_oc_release_1130/180.
- **MERGE**: cross_provider_release_1140 goes to test_lane_bindings. sprint_oc_release_190 goes to package test_release_190_handle_operations. run2_ingress_request_idempotency goes to test_signal_ingress. wi08_graph_route_schema_seed goes to test_catalog_seed_bundles.
- **REWRITE into `packages/mission-control-db-contract/tests/test_schema_guards.py` on the newest release**: sprint_v_release_150/160, sprint_oc_release_170/1100/1110/1120. Their SQL-guard assertions are real, but they run on the dated release. A later migration that changed a guard (0067 changed the handle check after 1.6.0) would leave them green while current behaviour differs.
- **run2_release_141** (imported by 16 files): replace it with one package test, `test_upgrade_from_deployed_locks.py`. The test installs each **deployed** lock (`deployments/biotech` = 1.3.0, `deployments/ai-engineer` = 1.4.2; both are in `releases/`) and upgrades it to the newest release. That is the only live upgrade path. `retained_release_130` restores 1.3.0 with `git show a3a78441…`. That commit predates the 2026-11-06 clean-slate move: it resolves in this checkout but will not exist in a fresh clone. The helpers (disposable, install, release_at, VERSIONS, as_role, create_tenant, raises_sqlstate) duplicate the package conftest, so delete them.
- Pure schema/grant checks with no Mission Control code go to the package (MERGE): pre_stage3_database_authority_integration, mission_chain_tables, and the guard parts of release_0033.
- **Stale and probably failing; check on the next run:**
  - `test_lane_bindings::test_lane_profiles_are_seeded_with_their_declared_describes` installs 1.4.1 and compares it with today's `DECLARED_LANE_MATRICES`, which 0073 changed.
  - `test_release_0033::test_lane_profiles_equal_frozen_describes…` compares newest-release rows with the frozen 1.4.0 describes.
  - The live invariant behind both: DB `lane_profile` == code describe matrix, only `deep_agents` qualified. It should be one test on `common_db` (the REWRITE of test_lane_bindings).
- Candidate-migration wrappers whose candidate is now released (`migration_paths_with(MIGRATION)`) reduce to plain `common_db`: wi07, wi13, wi19, wi22, native_plan_decisions, mp15_webhook. `mp11_db` is an exact duplicate of `common_db`.
- Already current (keep; rename only): release_0032 → cluster bindings and stream hints, catalog_kinds_0025, every run2_*/w1_*/wi*/mo*/mp*/ft_* behaviour file.

### (2) Consolidated set by adapter (`src/mission_control/adapters/postgres`)
Proposed layout `tests/integration/postgres/<area>/test_<adapter>.py`. Each targets one adapter. Where src has an InMemory port, it runs a shared contract on both:
- run_control_repository: run_control_postgres_integration (canonical) + atomic_family_admission, budget_admission_failure, human_gate_budget_admission, completion_evidence/validation, w1_family_failure, wi08_revisit, rrm_009, run_evidence. Contract: `InMemoryRunControlRepository`.
- mailbox + stop_fence: command_mailbox, ft_f2_inject, boundary_commands, stop_fence, gate_hook_stop_fence, mission_control_lifecycle (`InMemoryCommandMailbox`, `InMemoryStopFenceRepository`).
- frames.repository: provider_frames (canonical) + frame_facts, frame_lifecycle_recovery, frame_session_lifecycle, run2_terminal_frames, provider_lineage (`InMemoryFrameStore`, **no shared contract today**).
- frames transcript: transcript, transcript_entries, transcript_search.
- lanes.execution_state/placement: lane_execution_state, managed_budget_controls, mp06_dispatch_journal, ft_g4_lane_controls, placement_capacity (`InMemoryLaneExecutionStateStore`, `InMemoryPlacementStore`).
- lanes.workspace_leases: workspace_lease, workspace_lease_races (already uses shared `tests/unit/workspaces/lease_scenarios.py`), local_lane_workspaces, run2_active_bridge_recovery, run2_released_bridge_sweep.
- operations.operation_journal: operation_journal_stage1 (REWRITE as an InMemory/PG contract), parallel_operation_authority.
- checkpoint_lineage + cognition_points: checkpoint_lineage (the model contract), session_lane_points.
- knowledge.output_contracts/fulfillment/inspection: output_contracts (canonical), trusted_judgment, knowledge_review, w1_d20/d28_d29/d30/fixg/fulfillment, wi07.
- knowledge gateway/locator/reads/use_decisions: knowledge_gateway, invocation_locator, retained_reads, native_plan_decisions.
- subscriptions/coordinator inbox/attention: subscriptions, mp15_inbox, mp15_webhook, mo43, wi19.
- approvals/human_tasks: mp11_approvals, mp11_governed, hosted_approval_context, mo14, human_gate_tasks.
- watchers: mo44, mo45, mo46. ingress: signal_ingress, run2_ingress_drainer, telemetry_pack.
- realtime: mission_socket, realtime_acceptance, realtime_channels (+ realtime_process_app).
- control_plane catalog/manifest: definition_catalog, catalog_kinds, catalog_seed_bundles, manifest_submit. capability search/bundles: capability_search_*, environment_kits, external_capability_custody, capability_bundle_*, bundle_custody_composition, skill_bundle_materialization.
- runtime kernel/forks: stage3_kernel, run_forks, ft_f4_fork, fork_completion, manifest_fork_admission. context: continuation, ft_b2_context_handoff, hook_candidate_installs.
- Composition/bootstrap (not per adapter): mission_control_bootstrap/composition, mission_worker_startup, mp22_preflight, local_signal_composition, secret_broker_vault, cursor_cloud_*.
- PG adapters with no PG test in this slice:
  - Used: `orchestration/native_inputs.py` (PostgresNativeInputReader, wired in bootstrap/api.py), `knowledge/attention_events.py`, `chains/exports.py`. Tested only outside the slice or not at all.
  - Apparently unused by src: `coordinator/launch_ticket_repository.py`, `workspaces/snapshot_repository.py` (its docstring says "Retired"), `approvals/proposed_0033.py` (a pointer only). These are src cleanup candidates.

### (3) Shared helpers
- **runtime_common.py** (131 importers):
  - Provides the common_db/poisoned_db/runtime_pool/family_pool fixtures and scoped_request/scoped_command (they wrap `tests.unit.run_control.test_run_control.request/command`), owner_rows, scoped_count, assert_admission_lineage.
  - Most importers only want the `common_db` fixture (hence `# noqa: F811` everywhere).
  - Move: fixtures → a pytest plugin `tests/fixtures/common_db_pytest.py` registered in `tests/conftest.py` `pytest_plugins` (the slice is also used from acceptance/ and other integration dirs, so a dir conftest is not enough); builders → **`tests/fixtures/db_builders.py`, the canonical DB-builders module**.
- **frames_common.py** (43): AdmittedUnit/admit_unit_attempt. It admits and starts a real run, then records one unit attempt; the default lane is DEEP_AGENTS. Move to db_builders.
- **catalog_common.py** (17): catalog_db (+ a disabled ai-engineer installation), runtime_pool and catalog_writer_pool, apply_seed_bundle (private `seeds._apply_record`), insert_fixture_run, seeds_publish_module.
  - Its `runtime_pool` fixture has the same name as runtime_common's but a different parent DB: rename it `catalog_runtime_pool`.
  - Merge into the same plugin and builders module.
- mp06_common → db_builders `lane_unit_on_postgres`; it is Cursor-shaped only.
- Builders duplicated across test modules, to move into db_builders:
  - `access_for` (output_contracts, trusted_judgment, wi07, wi19, knowledge_gateway).
  - `admitted_run`/`_admitted_run` (mp11, human_gate_tasks, release_0032, release_0033).
  - From mp15_coordinator_inbox (7 importers): started_run/owner_fetch/mission_service/inbox_service/append_fixture_events.
  - From test_manifest_submit (3): Stack/request/RecordingSubmitter.
  - From test_signal_ingress (7): `Ingress`/`ingress`. From test_subscriptions: Receiver/Clock.
  - From test_mission_chain_tables: insert_mission/insert_chain. From test_mo44: FixedProgram/eventually/local_temporal.
  - From test_mission_socket: deployment/stack/auth. From test_operation_journal_stage1: claim/_SCOPE. From test_environment_kits: _seed.
- Test modules from other slices imported here as libraries (they must move first): tests.unit.run_control.test_run_control (via runtime_common), test_boundary_commands, test_atomic_family_admission, tests.unit.outputs.scenario, tests.unit.knowledge.test_gateway/test_trusted_judgment, tests.acceptance.control_plane.test_wp_cp_040/045, tests.integration.temporal.test_wp_bp_010_temporal.

### Canonical doubles this slice needs
- Clock: there are 6 copies (`Clock` in test_subscriptions, test_owner_prerequisites, test_mp15_webhook and tests.unit.approvals.fixtures, plus `StepClock`, `SteppingClock`, `MutableClock`). Keep `tests.fixtures.provider_frames.StepClock` as the one deterministic clock (`tests/fixtures/clock.py`).
- Temporal start port: `RecordingStarter` is defined 3 times (chain_release, mo44, transcript_entries `_RecordingStarter`). Plus `RecordingSubmitter` (manifest_submit). Keep one Recording starter in db_builders.
- Knowledge Services: `tests.fixtures.knowledge_binding.FakeKnowledgeBinding` (BOUNDARY). Keep `ScriptedRunner` (KS trusted judge) too, but move it out of `tests.unit.knowledge.test_trusted_judgment`.
- Provider lanes: `tests.fixtures.lane_turns.ScriptedSessionLane` (BOUNDARY). Cursor/GitHub/OIDC/webhook receivers: FakeCloudApi, FakeEnvironmentsApi, FakeGitHub, FakeOidc, Receiver/ScriptedReceiver (BOUNDARY, loopback). Embeddings: DeterministicEmbeddings.
- Staging port: `tests.fixtures.knowledge_binding.InMemoryStaging` versus `tests.fixtures.continuation.FakeStaging`/MemorySnapshots/NoArtifacts. These are duplicate PORT-FAKEs; keep one and prefer a src InMemory store if one exists.
- `TargetedControls`/`Signals` are copied between closed_workflow_recovery and run2_terminal_context; fold them into one support class.
- Fault-injection wrappers over the real adapter (CrashingStore, BarrierStore, CrashAfter*, DiesBeforeRecord, FailingHook, `_SynchronizedWriters`, the commit_command barrier) are legitimate. Keep them local to their tests.

### Patterns
- Good, the target shape:
  - test_checkpoint_lineage_postgres runs `assert_checkpoint_lineage_repository_contract`, which also runs on the in-memory repository.
  - test_workspace_lease_races runs the same `lease_scenarios` as tests/unit/workspaces/test_workspace_lease_ledger.
  - Per-adapter files that pin grants, RLS and behaviour together: test_environment_preparation, test_owner_prerequisites.
- Bad:
  - Unit tests in the integration dir: test_operation_journal_stage1, where 11 of 13 tests use `InMemoryAtomicOperationJournalRepository` and the in-memory run service. These are the journal's only unit tests.
  - Monkeypatched module constructors to inject a provider transport: test_cursor_cloud_composition and test_cursor_cloud_environment_sync patch `deployment_composition.CloudAgentsClient`. A transport-factory seam is needed.
  - Private-member patches: `service._session_lane` (lane_operator_reconciliation); four seed-engine internals (capability_bundles_publish::bucket_seed_blocked); `states._merge_identity` (ingress_drainer barrier).
  - A global hook registry reset (`_POST_APPEND_HOOKS`, chain_release) suggests src should inject the registry.
  - Stale docstrings: mp11/mp15/mo14 say "scratch DB built from 0001..0033", but they use the newest release.

### Deep Agents path (essential protection in this slice)
- manifest_submit (submit/start)
- bundle_custody_composition and skill_bundle_materialization (manifest v2 → custody → Deep Agents materializer)
- lane_bindings (bindings default to deep_agents; the describes test needs the REWRITE)
- immutable_runtime_documents (operation binding claim and settlement)
- checkpoint_lineage (LangGraph namespace contract)
- runtime_inspection (checkpoint history)
- invocation_locator (Deep Agents knowledge-tool origin)
- wi04_saved_settlement (resume without cognition)
- wi23_async_children and async_subagent_* (sealed child binding)
- workspace_closures
- run_control/atomic_family_admission (settlement)
- mission_worker_startup

Gaps:
- No InMemoryFrameStore/PG frame contract. frames_common and mp06_common lane units are Cursor-shaped: there is no deep_agents binding variant. The Deep Agents lane itself on PG is in tests/integration/deep_agents (another slice).
- The operation journal has no InMemory/PG parity contract.
- PostgresNativeInputReader has no direct test.

### Uncertain calls (coordinator should double-check)
- Whether test_lane_bindings (1.4.1 describes) and test_release_0033 (frozen describes) currently pass. I expect both fail since 0073.
- `retained_release_130` depends on pre-move commit a3a78441 being present locally. It resolves here; it will not after a fresh clone.
- test_operation_journal_stage1::test_legacy_settlement_digest_is_explicit…: I kept it in the REWRITE. It is unclear whether legacy settlement digests can still occur in live rows.
- The schema-guard moves (150/160/170/1100/1110/1120, chain tables, pre_stage3, 0033) assume the package conftest (MCDB_TEST_ADMIN_DSN_A/B clusters) is acceptable for them. If not, keep them here on `common_db` under the same rewrite.
- test_biotech_adapter_records: kept, but it belongs in integrations/biotech tests; check that package runs a common_db target.

## J-integration-acceptance


153 files. Test-function counts are `def test_*` counts (parametrize expands them further).

| Verdict | Files | Test functions |
| --- | --- | --- |
| KEEP | 105 | ~262 |
| REWRITE | 19 | ~111 |
| MERGE | 16 | ~23 |
| DELETE | 13 | ~28 |

Most of this slice is legitimate REAL-INFRA work (time-skipping or local Temporal, disposable PG, Agent Server, Docker). The cost is structure: test modules used as libraries, two production harnesses, a dozen replay or live duplicates, and evidence-writing drills. There are few internal mocks.

### Answers to the slice questions

**(1) Temporal determinism (essential, keep all):**
- `integration/temporal/test_replay_histories.py`: replays every capture under `tests/fixtures/histories/*` and `integration/temporal/histories/temporalio_1_30`, and asserts that every family is covered. Make it the single replay-all module.
- `test_lane_replay_histories.py`: 15 `ft_lanes` operation histories, including Deep Agents through `lane.turn`, fork, inject and continuation. Used by `make lane-qualify`.
- `test_worker_versioning.py`: rolled worker with a patched branch, AUTO_UPGRADE, then replay.
- `test_lane_turn.py`: the generator of `ft_lanes` (`MC_CAPTURE_LANE_HISTORIES=1`).

Fold into the replay-all module as per-directory marker assertions: `test_rrm_007_replay_pre_change_histories`, `test_rrm_021_replay_pre_change_histories`, `test_wi08_legacy_stagegraph_replay`, and the four replay functions inside `test_rrm_016_goal_directed_journaled`. They replay files that `test_replay_histories` already replays.

High-value WorkflowEnvironment behaviour suites:
- `test_wp_bp_010_temporal` (StageGraph) and `test_wp_bp_020_temporal` (GoalDirected)
- `test_rrm_007_boundary_interventions`
- `test_rrm_008_family_cancellation` and `test_rrm_008_operation_workflow_cancellation`
- `test_rrm_016_goal_directed_journaled`: the best-shaped one, with production activities over in-memory ports
- `test_wi04_saved_settlement_restart`, `test_command_mailbox`, `test_ft_f2_inject`

The replay-all module also needs `FixtureChildWorkflow`, which today it imports from `test_linked_runs`.

**(2) Canonical end-to-end acceptance.** Keep two:
1. `acceptance/mission_control/test_chain_two_goal_loops.py::test_research_acceptance_releases_ingestion_with_its_packet_and_completes_the_chain`. Manifest compile, submit, governed start, sealed Deep Agents binding, GoalDirected on the Temporal dev server, acceptance, chain release, consumer completed. Real PG, scripted model. This is the owner's path end to end.
2. `acceptance/mission_control/test_authenticated_scoped_runtime.py`. Signed scoped HTTP; StageGraph and GoalDirected; pause/resume; settlement counts; persisted evidence; Replayer over every root, family and operation history.

Redundant drills:
- Merge `test_manifest_lifecycle` (a prefix of 1) into 1.
- Merge `test_postgres_runtime_parity` (the older rrm009 harness), `test_ft_g2_segment_loop` (turn it into a segment-loop parameter) and `acceptance/control_plane/test_rrm_007_interventions` into 2.
- Delete every paid drill: `test_wp_bp_010_live`, `test_wp_bp_020_live`, `test_wp_cp_040_live`, `test_manifest_async_child_live`, `test_tracing_live` (1,620 lines), `deep_agents/test_hooks_local_model`.
- Rewrite `test_tracing.py` (3,041 lines, 11 drills writing `.scratch/tracing-stage-1` evidence) into behaviour tests plus a support module.
- Rewrite `test_overnight_*` (KS-subprocess drills with evidence export) at integration level.

**(3) `tests/architecture/test_package_boundaries.py`: KEEP.** It is cheap, run by `make check` and `make ci`, and fails on an empty scan. Only `APPLICATION_NEEDLES` (imported by 3 unit tests) should move. It already covers the import-guard tests duplicated in `acceptance/control_plane/test_wp_cp_020.py` and `test_wp_cp_030.py`; drop those duplicates.

**(4) `qualification/two_project`: KEEP all 9 files.** They are reviewer-owned per tests/AGENTS.md and fail rather than skip without an admin DSN. One note for the owner: `disposable.py` and `release_install.py` are imported by four `tests/integration/postgres` modules. That couples implementation tests to the reviewer's independent harness, so those modules should get their own fixture.

**(5) `tests/experiments`: does not belong in the suite.**
- `test_dynamic_research_swarm` and `test_langgraph_temporal_stagegraph` test `experiments/`. src never imports it, and ruff excludes it as non-gate code. DELETE, or move them beside the experiment.
- `test_schema_context_run_comparison` tests Biotech qualification code: MERGE into `tests/unit/schema`.
- Update the `experiments/` line in tests/AGENTS.md.

**Live and paid drills: which make target runs them.**
- Only `make lane-qualify PROFILE=... LIVE=1` (`scripts/lane_qualify.py`) runs any of them: `cursor/test_lane_qualification_live`, `codex/test_codex_live_qualification` and `claude/test_claude_live_qualification`. KEEP those with their `live_drill.py` helpers.
- `make test-integration` and `make test-acceptance` collect everything else, but each test skips behind its own env gate: `BELLABS_RUN_*`, `MC_*_LIVE`, `MC_LIVE_HOOK_MODEL`, `MC_HL*`, `MC_CODEX_HOOK_DRILL`, `MC_TEST_S3_*`.
- Keep three outside lane-qualify, one per lane plus Deep Agents, and wire them into a target: `deep_agents/test_agent_configuration_live` (production model factories against real APIs, with its own spend ceiling), `anthropic_managed/test_session_lifecycle_live` and `openai_agents/test_function_tools_live`.
- Delete the rest: cursor `cloud_live` and `local_live` (subsumed by lane qualification), managed `pack_sync` and `approval_publication`, and openai `projection_live`.

### Canonical doubles this slice needs

| Boundary | Keep (canonical) | Fold in | Why needed |
| --- | --- | --- | --- |
| LLM, in-process graph | `tests/fixtures/checkpoint_recovery.ScriptedRecoveryModel` (and `GoalScriptedModel`) | SkillReadingModel, SessionProbeModel (wp_cp_040), PlanReadingModel (wi02), FullContextReader, SandboxSkillReader, InputListingModel, ToolCallingUsageModel, SandboxedFileModel, GoalSandboxModel, SteerableModel | No paid calls; script tool calls and record the messages seen |
| LLM, production stack | `tests/fixtures/rrm009_production_stack._LoggedModel` / `TechnicalModel` (registered through the production capability hook) | ChainModel, GoalModel, StageGraphModel, Spawning/CheckingChainModel, the overnight_* models | Same, behind the real worker composition |
| Temporal server | one shared fixture in `tests/integration/temporal/conftest.py` around `WorkflowEnvironment.start_time_skipping`, plus `tests/fixtures/mission_control_production_stack.start_local` | the ~25 copies of `try: start_time_skipping() except RuntimeError: pytest.skip(...)`; `test_rrm_005._start_local` | REAL-INFRA. The per-test skip hides a missing service, which tests/AGENTS.md forbids |
| Session lane | `tests/fixtures/lane_turns.ScriptedSessionLane` | mp06_lanes and mp12_lanes variants as subclasses | Provider-neutral lane boundary |
| Family activities | production `compose_goal_directed_activities` over in-memory run control (as in rrm_016); otherwise one `tests/support/family_activities.py` | FakeStageGraphActivities, FakeGoalDirectedActivities, Governed*, Cancellable*, UnitBound*, Review*, Managed*, Routed, Nested, BaselineSettling | PORT-FAKE; today a 4-level subclass chain spread across test modules |
| Provider APIs | `fixtures/cursor_cloud.FakeCloudApi`, `fixtures/managed_agents.FakeManagedAgentsApi`, `unit/codex/fixture_app_server.FixtureLauncher`, `unit/claude/fixtures`, `fixtures/fake_agent_protocol.FakeAgentProtocolClient`, `fixtures/agents_lane` | none | BOUNDARY. Move the codex and claude ones from tests/unit to tests/fixtures |
| Knowledge Services | `fixtures/knowledge_binding.FakeKnowledgeBinding`; the KS TS fixture host for one joined proof | the KS verification-executor subprocess in the overnight drills | Cross-repo boundary |
| Production stack | `tests/fixtures/scoped_api_stack` (signed) | `rrm009_production_harness.open_postgres_production_stack` / `ProductionStack` (used by 14 files) | Two harnesses for one composition |

### Shared builders that must move out of test modules

- `acceptance/control_plane/test_wp_cp_040.py` (36 importers): `exact_fixture`, `registry`, `unit_bound`, `planned_invocation`, `SessionProbeModel`, `SkillReadingModel` -> `tests/support/deep_agents_binding.py`.
- `integration/temporal/test_wp_bp_010_temporal.py` (19): `QUEUE`, `DIGEST`, `_blueprint`, `_run_input`, `_operation`, `FakeStageGraphActivities` -> `tests/support/stagegraph_family.py`.
- `test_wp_bp_020_temporal.py` (11): `FakeGoalDirectedActivities`, `_run_input`, `fake_settlement` -> `tests/support/goal_family.py`.
- `test_rrm_007_boundary_interventions.py` (7): `Authority`, `Governed*Activities`, `until`, `replay`, `pause`, `resume`, `_state_is`, `_phase_is`, `_has_wait`, `SCOPE`, `ROOT_WORKFLOWS` -> `tests/support/family_control.py`.
- `test_manifest_launch_production.py` (16): `host_pins`, `missions_app`, `post`, `submit`, `MISSION_2`, `OUTPUT_SCHEMAS`, `evaluable`, `LaunchStack`, `CountingAuthor`, `delivered`, `fetch`, `relay_pump`, `root_executions`, `write_bindings` -> `tests/support/manifest_launch.py`.
- `acceptance/control_plane/test_wp_cp_045.py` (10): `DeterministicProvider`, `OrderedDetails`, `OrderedAuthority` -> `tests/support/async_subagents.py`.
- `test_cognition_points.py` (6) and `test_tracing.py` (4): point and tracing query helpers -> `tests/support/points.py` and `tests/support/tracing_queries.py`.
- `test_report_source_real_service.py` (6): `response`, `command` -> `tests/fixtures/ks_fixture_host.py`.
- `test_wi02_transfer_plan_lane.py` (5): `PlanReadingModel`, `_invocation`, `_selection`, `_materializer` -> deep_agents_binding support.
- Lane workers and clients in `test_managed_segment_loop_real_services`, `test_mp06_dispatch_recovery` and `test_mp07_claude_lane_turns` (near-identical `_activity_worker`, `_workflow_worker`, `_client`, `_replayed`, `_request`) -> `tests/fixtures/lane_temporal.py`.
- `anthropic_managed/test_session_lifecycle_live.py` (imported by 3, including the non-live `test_owner_bootstrap_runtime`) -> `tests/fixtures/managed_lane.py`.
- Smaller moves:
  - `test_linked_runs.FixtureChildWorkflow`
  - `test_chain_start_idempotent` (`AdmittedRunInputs`, `OneShotStore`, `NOW`)
  - `test_rrm_008_*` (`_Stack`, `_replays`, `_scheduled`, `CancellableStageGraphActivities`)
  - `test_wi04_saved_settlement_restart` (`_Stack`, `_environment`)
  - `test_manifest_async_child` (`AsyncLaunchStack`, `async_profile_*`)
  - `test_overnight_stagegraph` / `test_overnight_goal_directed` (manifests and launch bindings)
  - `architecture.APPLICATION_NEEDLES`
- Upstream, `tests.unit.run_control.test_run_control` (`service`, `request`, `command`, `actor`) and `tests.unit.operations.test_operation_execution` (`operation_request`, `MCP_DIGEST`, `SKILL_DIGEST`) feed about 40 files in this slice.

### Patterns

- **Good: production code over in-memory ports on real Temporal.** `test_rrm_016_goal_directed_journaled` and `test_command_mailbox` (`compose_goal_directed_activities` plus a real `create_deep_agent` graph plus Replayer).
- **Good: fakes only at provider edges.** `test_mp09_cloud_segment_loop_real_services` and `test_managed_segment_loop_real_services` (provider faked via `httpx.MockTransport`, everything else real, every history replayed).
- **Good: fail rather than skip.** `qualification/two_project/disposable.py` turns a missing DSN into a failure.
- **Bad: test functions imported as scenarios.** `test_ft_g2_segment_loop` imports and calls `test_postgres_runtime_parity`'s test function. `test_rrm_007_interventions` monkeypatches `SCOPE` and `request` inside another test module.
- **Bad: internal mocks.**
  - `test_goal_schema_runtime` patches `PostgresArtifactBytes.capture`, `GoalDirectedOperationPreparationService.prepare` and `TemporalBoundaryCommandTransport._deliver_cancel`.
  - `test_parallel_stage_authority` patches `PostgresRunControlRepository.commit_command`.
  - `test_lane_operator_reconciliation` patches `service._session_lane`.
  - `test_wp_cp_040` spies on `create_deep_agent`, and `test_create_deep_agent_has_one_non_experiment_production_call_site` counts source text.
- **Bad: drills, not tests.** `test_tracing.py` and the `overnight_*` files write evidence JSON and print paths. The `overnight_*` drills need `../knowledge-services` on disk.
- **Bad: misfiled unit tests.**
  - `acceptance/control_plane/test_wp_cp_010/020/030/045.py` and `integration/temporal/test_pre_stage3_temporal_contracts.py` need no infrastructure but sit under acceptance or integration.
  - `integration/cursor/test_cursor_local_fixtures` duplicates `tests/unit/harness/test_lane_qualification_fixtures.py`.
- **Stale config.** `tests/conftest.py` `_PSYCOPG_SELECTOR_MODULES` names modules that no longer exist (for example `test_rrm_004_worker_restart_recovery`, `test_rrm_013_async_subagent_live` and `control_plane/test_rrm_005_inspection` / `_009_*` / `_010_*` / `_016_*` / `_020_*`). Prune it.

### Deep Agents path: essential protection in this slice

1. **Lane and binding:**
   - `test_wp_cp_040` (rewrite and move)
   - `deep_agents/test_ft_b2_packet_seeding`
   - `test_wi02_transfer_plan_lane`, `test_wi02_dependent_stage_transfer`
   - `test_provider_frames_deep_agents`
   - `test_docker_sandbox`, `test_wp_bp_020_sandbox_rollover`
2. **Children:**
   - `test_wp_cp_045`
   - `agent_server/test_canonical_server_local`, `test_wi23_sealed_child_server`
   - `test_manifest_async_child`, `test_manifest_sealed_async_child`
3. **Persistence:**
   - `test_checkpoint_lineage_postgres_saver`
   - `test_runtime_persistence_postgres`
   - `test_continuation_deep_agents`
4. **Temporal:**
   - `test_wp_bp_010_temporal`, `test_wp_bp_020_temporal`
   - `test_rrm_008_*`, `test_rrm_016_*`
   - `test_lane_turn`
   - `test_wi04_saved_settlement_restart`
   - the replay modules
5. **End to end:** the two canonical acceptance tests.

Gaps:
- **No CI coverage of the manifest -> sealed binding -> settlement path.** Both canonical tests need `MISSION_CONTROL_TEST_ADMIN_DSN` plus a Temporal CLI. `make ci` and `make check` run neither, so that path is proven only when someone runs `make test-acceptance`.
- **Segment loop off in production by default.** `mission_control_lane_segment_loop` defaults to False, so Deep Agents through `lane.turn` is the non-default path. Only `test_lane_turn` (time-skipping) and `test_ft_g2_segment_loop` cover it on the full stack.
- **No live Deep Agents target.** `test_agent_configuration_live` is the only Deep Agents test against real provider wire, and no make target runs it.

### Uncertain calls for the coordinator

- **Session-ownership-only verdict.** `test_manifest_async_child` vs `test_manifest_sealed_async_child`: merge if the unsealed async binding mode is retired (`binding_mode` other than `sealed_child`); I did not confirm that.
- **Unique invariants in the overnight drills.** `test_overnight_linked` (source correction after seal, adoption stays a draft) and `test_overnight_goal_directed` (repair bounds): marked REWRITE, not DELETE, because I found no other test of these invariants. Check against slice owners for tests/unit/context and tests/integration/postgres.
- **Live-drill selection.** Which secondary-lane live drills survive (`test_session_lifecycle_live`, `test_function_tools_live` kept; `pack_sync`, `approval_publication`, `projection` deleted) is a policy call: one owner-run qualification per lane.
- **mp05 merge.** `test_mp05_limit_wait` -> mp06: confirm that mp06 or `tests/unit` covers "a cancel signal wakes a long reset wait" on the production `OperationWorkflow` before deleting.
- **Visibility merge.** `test_ft_g7_visibility` -> `test_ft_c4_run_list`: both start a local server; the merge saves a server start but slightly broadens one test.
- **Windows skip.** `test_wp_bp_010_recovery` is skipped on win32 and so never runs on the owner's Windows host; confirm that the WSL runtime actually runs it.

