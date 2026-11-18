# Mission Control test suite review: which test doubles to keep and what to remove

Date: 2026-11-17. Part of the agentic SDLC upgrade. Status: accepted for implementation (AS-D50, OVE-238).

## Where this leaves the owner goal

The goal is complete Deep Agents workflow and agent configuration logic. That path runs manifest → compile → sealed binding → Deep Agents lane → Temporal workflows → settlement. The suite protects each step of that path, but in separate pieces. Three proofs are missing:

1. No test takes one manifest through compile, the sealed binding and materialization to a scripted Deep Agents turn.
2. The two end-to-end acceptance tests that do cover manifest → settlement on real PostgreSQL and Temporal do not run in `make ci`.
3. Each in-memory store that unit tests rely on should be checked against its PostgreSQL store by one shared contract test. Five such stores have no contract test.

This review has two parts. First, it sorts every test file into keep, rewrite, merge or delete. Second, it names the small set of test doubles worth keeping, so the next proofs can be written against one stable support layer. The next blocker after that is writing gap test G1 (step 5).

Evidence labels used below: **verified** means I ran it or grepped it myself; **reviewed** means a reviewer read the code and I did not re-check it; **unrun** means nobody executed it.

## The short answer

- **The tests are mostly right. The support code around them is what is overgrown.**
  - The suite holds 9,672 collected tests in 1,212 Python files, about 350k lines, which is about the size of `src/` (339k).
  - Ten parallel reviewers read every file. Measured in test functions, the verdicts are: keep 4,238, rewrite 1,862, merge 62, delete 340.
  - Most rewrites keep every assertion and only change where builders and fakes come from.
  - Deleting most tests would remove real protection, so I do not recommend it.
- **"Remove most of them" does apply to the fixtures and mocks.** Today there are:
  - about 126 helper modules in `tests/fixtures/`
  - about 180 local fake classes
  - 46 separate fake LLM classes in 39 files
  - 21 clock classes
  - 4 overlapping production-stack builders
  - 515 test files that import *other test files* to get builders (150 of them import `test_run_control.py`).

  These collapse into about 16 support modules, listed in [section 3](#3-the-test-doubles-to-keep).
- **Step 1 can run today.** 68 test files (329 test functions, 17k lines) can go without touching anything else. Collection drops from 9,672 to 9,130 items with no import errors (verified with `pytest --collect-only`). 23 of those files need no decision from you; 45 need a yes on one of four questions in [section 7](#7-decisions-for-the-owner).

## 1. How to decide what a test may fake

This is the rule the whole review applied. It answers "which fixtures and mocks do we really need".

A test double stands in for something real. A double is worth having only when the real thing is one of these:

1. **Outside our process and outside our control.** The LLM, the Codex app-server, the Claude Agent SDK, the Cursor bridge and Cloud API, Anthropic Managed Agents, the OpenAI Agents API, Knowledge Services, GitHub, MCP servers.
2. **Slow or paid,** like the same LLM calls.
3. **Nondeterministic,** like the wall clock, random ids and network timing.

For each of those there should be **exactly one** fake per boundary. It should be as close to the real wire format as possible, ideally replaying a recorded real session.

What we own, we do not fake. PostgreSQL (grants, row-level security, migrations, SQL) and Temporal (determinism, durable timers, replay) are where our real bugs live. A fake database that matches SQL strings passes when the query is wrong and fails when the query is merely rewritten. So database behaviour is tested on a disposable PostgreSQL 17, and workflow behaviour on Temporal's time-skipping test server or a replay of a recorded history.

Inside our own code, use the real classes. An in-memory port implementation, for example `InMemoryRunControlRepository`, is acceptable in a unit test only if two things hold:

- **one copy per port** (preferably the `src` one), and
- **a shared contract test** that runs the same scenarios against the in-memory store and the PostgreSQL store, so the fake cannot drift from the real one.

The repository already has this pattern three times, and those are the models to copy:

- `assert_checkpoint_lineage_repository_contract` in [tests/fixtures/checkpoint_lineage.py](../../../../tests/support/checkpoint_lineage.py)
- [tests/unit/workspaces/lease_scenarios.py](../../../../tests/unit/workspaces/lease_scenarios.py)
- [tests/fixtures/hook_contributions.py](../../../../tests/support/hook_contributions.py)

Never do any of the following:

- patch a private function
- replace a method of the object under test
- monkeypatch a module global to inject a collaborator
- assert that an internal function "was called"

Such tests stay green when the behaviour is broken and go red when the code is refactored, which is the opposite of what a test is for. When a test needs to inject something, the fix is a constructor parameter (a seam) in `src`, not a patch.

## 2. What the reviewers found

Per-file verdicts, with the behaviour each file tests, its doubles and the reason, are in [verdicts.tsv](verdicts.tsv). The reviewers' working notes, including the exact builder names to move, are in [REVIEWER-NOTES](REVIEWER-NOTES.md#a-fixtures).

| Verdict | Files | Test functions | Meaning |
| --- | --- | --- | --- |
| KEEP | 829 | 4,238 | Protects live behaviour with legitimate doubles. Includes 87 helper modules and data directories. |
| REWRITE | 293 | 1,862 | Behaviour matters; the doubles or the imports are wrong. About two thirds only need builders moved out of other test files. |
| MERGE | 46 | 62 | The same behaviour is covered by a stronger test named in `target`. |
| DELETE | 74 | 340 | Tests dead code, tests a fixture itself, re-proves a dated release, or is a paid drill that no make target runs. |

The reviewers' main observations, in order of importance:

1. **Test files are used as libraries.** 515 files import builders from other `test_*.py` files. The heaviest are:
   - `test_run_control.py`, 150 importers (`service`, `request`, `command`, `actor`…)
   - `integration/postgres/runtime_common.py`, 131 importers
   - `test_operation_execution.py`, 50 importers (`operation_request`…)
   - `acceptance/control_plane/test_wp_cp_040.py`, 36 importers. It holds `exact_fixture`, the canonical builder for an exact Deep Agents binding, inside an acceptance test.

   This is the main reason the suite is hard to change: editing one test breaks a hundred others. It is also why `lane_turns.py`'s 112 consumers all load a 1,557-line test module.
2. **One boundary, many fakes.**
   - The LLM is faked by 46 classes. Every new scenario added a subclass instead of a script.
   - There are 21 clocks.
   - Knowledge Services has 3 fakes.
   - The production stack has 4 builders.
   - The Temporal test-server start is copied into 28 files, each one *skipping* when the server does not start (verified). That breaks the rule in [tests/AGENTS.md](../../../../tests/AGENTS.md): never hide a missing service behind a skip.
3. **Internal mocks are rare but concentrated** (patterns in [section 4](#4-what-to-remove-and-why)). MagicMock appears 148 times and `mock.patch` never does. The 423 `monkeypatch.setattr` calls are mostly legitimate environment or fault injection; the rest are listed per file in `verdicts.tsv`.
4. **Scenario drills named after sprints.** About 188 test files and most of `tests/fixtures` are named after work packages (`rrm009`, `qualia`, `overnight_*`, `mp20`, `wi23`, `run2_*`). Most protect live behaviour and only need behaviour names. The top-level `test_qualia_*`, `test_overnight_*` and `test_aieng_*` files mostly test the fixture modules themselves.
5. **The pieces that are already right:**
   - Disposable PostgreSQL with real role logins.
   - Temporal history replay ([test_replay_histories.py](../../../../tests/integration/temporal/test_replay_histories.py) replays every capture in [tests/fixtures/histories](../../../../tests/fixtures/histories)).
   - The lane conformance suite: one shared contract, one fake per provider, with claims derived from each lane's declared describe.
   - The Codex fake validated against the real generated JSON schema.
   - Knowledge Services scenarios run over both a direct call and HTTP.
   - The architecture test.

## 3. The test doubles to keep

These are the ones to include. Everything else either folds into one of them or goes.

Python helpers move to a new `tests/support/` package. `tests/fixtures/` keeps only data (recorded frames, histories, manifests, golden files). That rule makes the difference between code and data visible.

### 3.1 Real infrastructure: not mocks, and the most important to keep

| Keep as | Built from | What it stands for, and why it must exist | Tests that need it |
| --- | --- | --- | --- |
| `tests/support/db.py` plus a pytest plugin registered in [tests/conftest.py](../../../../tests/conftest.py) | [mission_control_common_db.py](../../../../tests/support/db.py) (197 consumers), the fixtures in [integration/postgres/runtime_common.py](../../../../tests/support/db_plugin.py), `db_env.py`, `tcp_proxy.py` | A fresh disposable PostgreSQL 17 database per test with the **newest built** common component and one login per capability role. It is the only way to prove migrations, grants, forced row-level security and SQL. It fails rather than skips without `MISSION_CONTROL_TEST_ADMIN_DSN`. | All of `tests/integration/postgres`, acceptance, qualification |
| `tests/support/temporal.py` | [temporal_history.py](../../../../tests/support/temporal.py), [operation_activities.py](../../../../tests/support/temporal.py), `FixtureChildWorkflow` from `test_linked_runs.py`, plus **one** `workflow_env` fixture around `WorkflowEnvironment.start_time_skipping()` that fails instead of skipping (replacing the 28 copies) | Temporal's own test server. It is the only honest way to test workflow logic: timers, signals, activity retries, cancellation. History replay proves that a code change does not break running workflows (non-determinism). | All `tests/integration/temporal`, the replay modules |
| `tests/fixtures/histories/` (data) | as is | Recorded workflow histories replayed against today's workflow code. This is the cheapest guard against breaking in-flight missions on deploy. | `test_replay_histories.py`, `test_lane_replay_histories.py`, `test_worker_versioning.py` |
| `tests/support/stack.py` | [mission_control_production_stack.py](../../../../tests/support/stack.py), absorbing `rrm009_production_harness.ProductionStack`, [scoped_api_stack.py](../../../../tests/support/stack.py) (signed mode) and `mp20_parity.ParityStack` as options (`signed=`, `lanes=`, `saver_proxy=`) | The real API and worker composition over real PostgreSQL and Temporal. One builder for one composition. Today four builders overlap, about 4.6k lines. | The surviving acceptance tests. Also the operator scripts `offline_operator_stack.py` and `aieng_watch_mission.py`, which import it today (verified). |

### 3.2 Boundary doubles: one per thing we do not control

| Keep as | Canonical class today | Folds in | Why it is needed |
| --- | --- | --- | --- |
| `tests/support/models.py` → `ScriptedChatModel` | Base: `ScriptedRecoveryModel` in [checkpoint_recovery.py](../../../../tests/support/checkpoint_recovery.py) (47 consumers; has `before_call/fail_on/gate_on` fault hooks). API from `Scripted` in [test_turn_stops.py](../../../../tests/unit/deep_agents/test_turn_stops.py): a script is **data**, a callable from the observed messages to the next `AIMessage`. It records bound tools and the inputs seen, sets stable ids and default `usage_metadata`, guards against loops, and works async. The fixture model catalog in [tests/fixtures/models.py](../../../../tests/support/model_catalog.py) moves beside it. It is configuration, not an LLM. | The other 45 chat-model classes, including `SkillReadingModel`/`SessionProbeModel` (test_wp_cp_040), `_LoggedModel`/`TechnicalModel` (rrm009_production_stack), `GoalScriptedModel`, `ScriptedChildModel`, `ThreeCallModel`, `PlanReadingModel` and the `overnight_*` models. `TechnicalModel`'s environment-variable branches become scripts. | The LLM is the main external boundary of a Deep Agents run. With it scripted, the **real** `create_deep_agent` graph, tools, checkpointer and our harness run without spend. Today one cognition change means editing a 1,368-line fixture. |
| `tests/support/knowledge.py` → `FakeKnowledgeBinding` | [knowledge_binding.py](../../../../tests/support/knowledge/binding.py): verifies real Ed25519 credentials, runs dispatch admission, and is served over HTTP by `knowledge_http_app` | `TrustedKnowledgeDouble` ([trusted_knowledge.py](../../../../tests/support/knowledge/trusted.py)) and the double inside `tests/unit/test_aieng_knowledge.py`. Split the 1,984-line file into binding, credentials, stores and content builders. | Knowledge Services is a separate service with its own credentials. The fake already runs every scenario over a direct call and over HTTP, which is the model for every boundary. |
| `tests/support/lanes.py` → `ScriptedSessionLane` | [lane_turns.py](../../../../tests/support/lanes.py), plus `lane_fields`/`LANE_REBINDERS` from [lane_bindings.py](../../../../tests/support/lane_bindings.py) | The `mp06_lanes`/`mp12_lanes` variants become options. Per-test subclasses that only override one frame may stay local. | A protocol-complete provider session (`SessionLane`) for the provider-neutral harness. Note: Deep Agents does not run through `LaneTurnService` in production (reviewed), so this fake protects the secondary lanes. |
| One fake per provider API, under `tests/support/providers/` | Codex: `FixtureAppServer` ([fixture_app_server.py](../../../../tests/support/providers/codex.py)). Claude SDK: `FixtureClient` ([fixtures.py](../../../../tests/support/providers/claude.py)). Cursor local: `ReplayBridge` ([cursor_local.py](../../../../tests/support/providers/cursor.py)). Cursor Cloud: `FakeCloudApi` ([cursor_cloud.py](../../../../tests/support/providers/cursor.py)) and `FakeEnvironmentsApi`. Managed Agents: `FakeManagedAgentsApi` ([managed_agents.py](../../../../tests/support/providers/managed_agents.py)). OpenAI Agents: `FakeAgentsApi` ([support.py](../../../../tests/support/providers/openai_agents.py)). | `mp20_parity`'s `Responder*` wrappers. The second `MemoryArtifacts`. The private-attribute `AsyncMock`s in cursor and openai tests. | Each lane adapter must be driven against its provider's wire format. Only Codex is checked against a real provider artifact today, so the follow-up is to record one scrubbed real session per secondary lane, the way Codex does. These live under `tests/unit/<lane>/` today while conformance and integration import them, so they must move. |
| `tests/support/agent_protocol.py` | `FakeAgentProtocolClient` ([fake_agent_protocol.py](../../../../tests/support/providers/agent_protocol.py)) | none | Hosted async subagent runs through the Agent Protocol. The real local Agent Server ([mission_control_local_agent_server.py](../../../../tests/support/local_agent_server.py)) stays for integration. |
| `tests/support/clock.py` and `tests/support/ids.py` | `MutableClock` (settable, advanceable) from checkpoint_recovery. The scope helpers `canonical_scope`/`tenant_id` from mission_control_common_db. | 21 clock classes and 3 different sets of `SCOPE`/`INSTALLATION`/`TENANT` constants. 25 files import the database module only to get scope strings. | Deadlines, leases and expiry need controllable time. One set of ids keeps fixtures joinable. |
| Small true boundaries, each kept once where it is | `DeterministicEmbeddings` ([capability_search_catalog.py](../../../../tests/support/capability_search.py)); `FakeGitHub` over `httpx.MockTransport` plus a local bare git remote ([effects/support.py](../../../../tests/unit/effects/support.py)); `FakeDockerSandbox`; the MCP stub servers (real processes); `httpx.MockTransport` for each HTTP client; the Neo4j driver fake (Biotech) | the 3 other embeddings fakes, as options | Embedding APIs, GitHub, Docker and Neo4j are external. |

### 3.3 Port fakes: allowed only with a contract test

Use the `src` `InMemory*` implementation of each application port. Fault injection subclasses it, as `FailOnceRetrievePayloadStore` does, rather than writing a new fake. Each port fake is pinned by one shared scenario module that also runs against the PostgreSQL adapter.

| Port | Canonical fake | Contract against PostgreSQL |
| --- | --- | --- |
| Checkpoint lineage, workspace leases, hook contributions | src `InMemory*` | exists |
| Run control | src `InMemoryRunControlRepository` | **missing**: write it |
| Operation journal | src `InMemoryAtomicOperationJournalRepository` (fold in `MemoryOperationJournal`, `RejectionJournal`, `FakeJournal` after checking API parity) | **missing** |
| Frame store | src `InMemoryFrameStore` (fold in 3 `FakeFrames`) | **missing** |
| Output contracts | `InMemoryOutputContractStore` ([output_contracts.py](../../../../tests/support/contracts/output_contracts.py)), promoted to `src` (fold in `FakeOutputs`) | **missing** |
| Knowledge stores (journal, handles, submissions, transfer plans, lineage, retained reads, staging) | promote the single test copies to `src/mission_control/adapters/knowledge/memory.py` | **missing**: the PostgreSQL tests already reuse the scenarios |
| Others: approvals, human tasks, stop fence, definitions, catalog search, external candidates, artifact metadata, owner prerequisites, staging | src `InMemory*` | add when the port changes |

`src/mission_control/adapters/operations/conformance.py` (the `Conformance*` runtime, sandbox, secrets and budget fakes) is imported by nothing in `src` (verified). It is test-only code shipped in the product. Move it to `tests/support/deep_agents.py`.

### 3.4 Builders: plain value constructors, not doubles

| Keep as | Moves from |
| --- | --- |
| `tests/support/builders.py` | `test_run_control.py` (`service`, `request`, `command`, `actor`, `WORKFLOW_DIGEST`, `NOW`, `ALL_PERMISSIONS`, `ConfigurationVerifier`…), `test_operation_execution.py` (`operation_request`, `MCP_DIGEST`, `SKILL_DIGEST`, `service_fixture`), `test_boundary_commands.py` (`TARGET`, `pause`, `started`…), `test_atomic_family_admission.py`; the database builders in `runtime_common`/`frames_common`/`catalog_common` go to `tests/support/db_builders.py` |
| `tests/support/deep_agents.py` | `exact_fixture`, `registry`, `unit_bound`, `planned_invocation` from `test_wp_cp_040.py`; `RecoveryHarness`/`CrashingSaver` from checkpoint_recovery; `TechnicalBinding`/`TechnicalCatalog` from rrm009_production_stack; the conformance runtime from `src` |
| `tests/support/manifests.py` | `manifest_launch_fixture.py`, `test_manifest_v2_launch.py`, `test_manifest_compile.py`, `test_manifest_launch_inputs.py`, `host_pins` from `test_manifest_launch_production.py`. Unify the two `resolver` builders. |
| `tests/support/settings.py` | [isolated_settings.py](../../../../tests/support/settings.py) as is (Settings with no `.env` leakage) |
| `tests/support/scenarios/` | Multi-step drivers for the acceptance tests that stay: `stagegraph`, `goal_directed`, `linked`, `async_children`, `knowledge_watch` (from `aieng_watch_tools.py`, which the live watch script imports). Named by behaviour. |

The exact names each builder module must export are in the slice notes: [B](REVIEWER-NOTES.md#b-ops-orchestration), [C](REVIEWER-NOTES.md#c-runcontrol-harness), [D](REVIEWER-NOTES.md#d-authoring-deepagents), [E](REVIEWER-NOTES.md#e-knowledge-context), [I](REVIEWER-NOTES.md#i-integration-postgres), [J](REVIEWER-NOTES.md#j-integration-acceptance).

## 4. What to remove, and why

| Remove | Why | Examples (more in `verdicts.tsv`) | Replace with |
| --- | --- | --- | --- |
| Patching the `temporalio.workflow` API or `object.__new__(SomeWorkflow)` | Tests a hand-made imitation of Temporal, not the workflow | `test_d39_claim_held_retry`, `test_operation_cancel_delivery_race`, `test_run2_ingress_wake`, `test_managed_budget_routing`, `test_root_result_materialization`, `test_w1_family_failure_terminalization` | `workflow_env` (time-skipping). Write the replacement **before** deleting, because some of these are the only test of their behaviour. |
| Fake asyncpg pools that match SQL text | Green on wrong SQL, red on harmless rewrites | `recovery/test_terminal_turn_usage`, `test_closed_workflow_postgres_authority`, `test_run2_ingress_composition`, `test_run_fence_backing`, `test_coordinator_security_audit`, `test_chain_start_gate`, `test_run2_caller_identity` | Disposable PostgreSQL |
| Replacing private methods of the object under test | Tests the patch, blocks refactors | `test_history_reconciliation` (`_watch_history`), `test_lane_operator_abandonment` (`_session_lane`), `test_stagegraph_completion_replay` (`_mutation`), `test_linked_transfer` (`_recheck`, which the constructor already accepts), `openai_agents/test_harness`, `cursor/test_cloud_workspace_and_resume` | Public API or a constructor seam |
| Monkeypatching composition-module globals | Hides a missing seam | `test_preflight`, `test_cursor_native_identity`, `test_rrm_009_cancellation_composition`, `test_async_child_parent_completion`, `test_cursor_cloud_composition` (transport factory) | Add an injection parameter in `src` |
| Spies that only prove an internal call happened | Says nothing about the outcome | `test_launch_admission_coverage`, `test_hosted_launch_bindings`, `test_plugin_portability` (`await_count`), `test_knowledge_served_components`, the `create_deep_agent` spy in `test_wp_cp_040` | Assert the result |
| Partial fakes patched with `raising=False` to fill gaps | Two half fakes of one port | `FakeOutputs` in `test_transfer_materializer` (patched by `test_authorized_subjects`, `test_linked_transfer`) | The canonical store |
| `FakeSealedBinding` (a `SimpleNamespace` carried "as if sealed") | A unit test can pass a binding no compile would produce | [lane_bindings.py](../../../../tests/support/lane_bindings.py) | The real exact-binding builder in `tests/support/deep_agents.py` |
| Hand-written fakes of our own services | Duplicates real logic | `Bridge`/`Reports` (test_native_write), `ScriptedBridge` (test_wi07_report_collections), `Control`/`Launches` (chain tests) | Real service over the boundary doubles |
| Evidence writers in fixtures | Tests write owner packets to `.scratch` | `stage2_outputs`, `overnight_*_evidence`, `test_tracing.py` (3,041 lines, 11 drills) | Keep the assertions, drop the files |
| Tests of the fixtures themselves | Prove the helper, not the product | `test_qualia_*`, `test_overnight_*`, `test_aieng_*`, `test_report_source_*` | Nothing; see decision 1 |
| Tests of code nothing calls | Protect dead code | Terminal-evidence adoption (7 files), Stage 3 recovery services (8), `LinkedOutputAdoptionService`, the Agent Server Stage 3 client, Block C | Delete the `src` modules too (decision 2) |
| Dated release proofs | Re-prove an old install. They can stay green while current behaviour differs. | `test_run2_release_14x`, `test_sprint_oc_release_*`, `test_run2_canonical_release` | One upgrade test from each deployed lock (1.3.0, 1.4.2) to the newest release, plus one schema-guard suite on the newest release, in `packages/mission-control-db-contract/tests` |
| Paid drills that no make target runs | Never executed, duplicate offline tests | 12 `*_live.py` files, `test_hooks_local_model`, `test_agent_server_block_c_persistent` | Keep one owner-run drill per lane through `make lane-qualify LIVE=1`, plus `deep_agents/test_agent_configuration_live` wired to a target (decision 3) |
| `tests/experiments/` | Tests code outside the distribution | `test_dynamic_research_swarm`, `test_langgraph_temporal_stagegraph` | Move beside `experiments/` if wanted |
| Fixture data: `tests/fixtures/provider_frames/codex/schema/` (0.162.0) | No code reads it; `src` pins `schema-0.162.1` | — | Delete (in step 1, group A) |

## 5. The order to do it in

Each step leaves the suite green and can be committed on its own. Run `make check` after every step. Run `make test-integration` and `make test-acceptance` after steps 1, 2 and 4 (they need `make dev`).

**Step 0: two defects (minutes, no decision).**
- `tests/unit/runtime/test_run2_cursor_costs.py:346` puts `uuid4()` inside a `parametrize` list. Each pytest-xdist worker therefore collects different test ids, so `make test-unit-fast` fails while collecting (verified by running it). Replace it with a literal UUID string.
- `_PSYCOPG_SELECTOR_MODULES` in [tests/conftest.py](../../../../tests/conftest.py) names 12 files that no longer exist, out of 41 (verified). Any rename silently breaks psycopg on Windows. Replace the file-name list with a marker, for example `@pytest.mark.psycopg_selector`.
- Fix the two unit tests that fail today (see "How this review was made" at the end):
  - build the composition test's settings with `isolated_settings()` instead of a `SimpleNamespace`;
  - give the runtime-env poison test a value that passes the `langgraph_checkpoint_locator` pattern.

**Step 1: delete (an hour).** The manifest is [step1-deletions.tsv](step1-deletions.tsv), and [apply_step1.py](apply_step1.py) stages the deletions with `git rm` and then re-collects the suite:

```
python docs/specs/agentic-sdlc-2026-11/test-suite-review-2026-11-17/apply_step1.py --dry-run
python docs/specs/agentic-sdlc-2026-11/test-suite-review-2026-11-17/apply_step1.py --groups A-no-decision
```

| Group | Files | Test functions | Needs |
| --- | --- | --- | --- |
| `A-no-decision`: overnight fixture self-tests, dated release proofs, experiments, unreferenced scripts' tests (coordinator evaluator, provider smoke), 1.4.1 release-prep tests, the cursor relocation shim test, plus the Codex 0.162.0 schema directory | 23 | 88 | nothing |
| `B-dead-src-tests` | 17 | 92 | decision 2. Delete with the `src` modules listed there. |
| `B-paid-and-live-drills` | 12 | 34 | decision 3 |
| `B-qualia-aieng-self-tests` | 13 | 109 | decision 1 |
| `B-report-source-foundation` | 3 | 6 | decision 4. `scripts/report_source_proof.py` runs these tests, so they go together. |

What I checked about this list (verified):
- No surviving test, script, `src` module or `pytest_plugins` entry imports any of these 68 files.
- None is cited as lane-describe evidence: `src` and `tests/conformance` cite 39 test paths, and none is in the list.
- Collection goes from 9,672 to 9,130 with no errors.

Five other DELETE verdicts stay blocked until step 2 because live files still import them: `overnight_config_readable.py`, `stage2_outputs.py`, `test_run2_release_142.py`, `test_qualia_fork_contract.py`, `test_report_source_context.py`.

**Step 2: build `tests/support/` and move builders out of test files (one agent session per hub, mechanical).** Work in fan-in order:
1. `test_run_control` (150)
2. `runtime_common` (131, as a plugin)
3. `test_operation_execution` (50)
4. `test_wp_cp_040` (36)
5. `outputs/scenario.py` (40)
6. `knowledge/test_gateway` (35)
7. `test_boundary_commands` (27)
8. the manifest builders
9. the rest

Each move is: copy the names into the support module, rewrite the imports, run the affected selection, delete the copy.

Also:
- Rename `TestFamilyMutation` to `FixtureFamilyMutation`. Any `Test*` class name is collected again in every importer.
- When renaming or moving a test file, update the evidence paths that cite it in the lane describes and in `tests/conformance/lanes/adapters/governed.py`. 22 cited files have a REWRITE verdict. `tests/conformance/lanes/test_registry.py` fails when a cited path disappears, which is the guard you want.

Done when `grep -rE "from tests\.[a-z_.]*\.test_[a-z0-9_]+ import" tests scripts` returns nothing.

**Step 3: collapse the doubles to the canonical set in section 3.** Work in this order:
1. `ScriptedChatModel`
2. `workflow_env` that fails instead of skipping
3. clock and ids
4. `FakeKnowledgeBinding`
5. one stack
6. the provider fakes out of `tests/unit/<lane>/`

Also move the product code that lives in tests:
- the scripts that import `tests.fixtures` (verified: `aieng_stagegraph.py`, `aieng_watch_mission.py`, `offline_operator_stack.py`, `qualia_stagegraph.py`, `qualify_two_disposables.py`)
- `src` reading `tests/fixtures/...` (`adapters/codex/protocol.SCHEMA_FIXTURE_DIR`, and the db-contract seeds that use `tests/fixtures/skills` and `tests/fixtures/mcp` as custody sources)

**Step 4: replace the internal mocks** in the files named in section 4 and in the `doubles` column of `verdicts.tsv` (search for `INTERNAL-MOCK`).

**Step 5: write the missing proofs.** These close the owner-goal gaps.
- **G1** `tests/unit/deep_agents/test_manifest_to_turn.py`. One manifest goes through compile, the launch author, the Deep Agents template step, harness decode, materialization and one `ScriptedChatModel` turn. Assert that the agent receives:
  - the Purpose Card and the authored prompt
  - exactly the bound tools, Skills and MCP tools
  - the catalog's model id
  - the sealed budget

  It runs in `make check`, in seconds.
- **G2** The same over named output promises: compile → Deep Agents tool projection → `submit_output` → settlement → fulfillment, in memory.
- **G3** The five missing InMemory-versus-PostgreSQL contract suites (section 3.3).
- **G4** Real-Temporal tests that replace the patched-workflow tests before they are deleted:
  - the root waits for the persisted result
  - `ingress_wake`
  - an accepted but undelivered cancel waits durably
  - a claim held during retry (d39)
- **G5** Run the two canonical end-to-end acceptance tests in CI. CI already starts PostgreSQL for `make local-eval`:
  - `tests/acceptance/mission_control/test_chain_two_goal_loops.py::test_research_acceptance_releases_ingestion_with_its_packet_and_completes_the_chain`
  - `tests/acceptance/mission_control/test_authenticated_scoped_runtime.py`

**Step 6: merges and names.**
- Apply the 46 MERGE verdicts.
- Rename sprint-named files by behaviour (the TSV `reason` column suggests names).
- Fold the 7 replay re-runs into `test_replay_histories.py`.
- Move the Biotech tests (`web_research`, `reference_research`, `schema`, `integrations/test_neo4j_*`) to `integrations/biotech/tests`.
- Move the infrastructure-free tests out of `acceptance/control_plane` (wp_cp_010/020/030/045) into `unit`.

## 6. The Deep Agents tests that must never be deleted

These are the essential protection of the owner's path. They were named by the reviewers, and each is KEEP or REWRITE-with-tests-kept in `verdicts.tsv`.

| Step on the path | Test (best single test first) |
| --- | --- |
| Manifest parse and compile | `unit/authoring/test_manifest_schema.py::test_owner_manifests_parse_with_no_structural_blockers`, `test_manifest_compile.py::test_owner_manifests_compile_with_zero_blockers_deterministically` |
| Launch inputs: one sealed binding per stage and goal role | `test_manifest_launch_inputs.py::test_stage_templates_bind_each_node_environment`, `::test_goal_templates_bind_executor_and_verifier`, `test_manifest_launch_resolution.py` |
| Sealed lane binding | `unit/deep_agents/test_compile.py::test_the_template_step_seals_the_exact_binding_for_the_template_coordinates`, `::test_the_rebind_reseals_the_template_for_one_live_attempt_by_digest`, `unit/resolution/test_sealed_lane_binding.py` |
| Agent configuration | `test_lane_adapter.py::test_the_adaptation_is_an_exact_binding_input`, `test_lane_adapter_features.py::test_the_configuration_is_part_of_the_exact_binding_digest`, `test_deep_agents_network_grants.py`, `test_agent_configuration_materialization.py`, `test_materializer_mcp_filter.py`, `test_model_routes.py`, `test_structured_output_strategy.py` |
| Children | `test_subagent_seeds_compile_and_launch.py`, `test_async_child_sealed_binding.py`, `unit/operations/test_async_child_*`, `acceptance/control_plane/test_wp_cp_045.py`, `integration/agent_server/test_wi23_sealed_child_server.py` |
| Turn on the lane | `test_model_request_observer.py`, `test_turn_stops.py`, `test_in_turn_run_budget.py`, `acceptance/control_plane/test_wp_cp_040.py` (the lane run; rewrite and move its builders) |
| Operation execution and recovery | `unit/operations/test_operation_execution.py` (service and workflow on time-skipping Temporal), `test_checkpoint_recovery_classification.py`, `test_rrm_008_cancellation.py`, `test_wi04_saved_settlement.py`, `test_fenced_turn.py`, `test_bounded_queued_turn.py`, `test_ft_f2_interrupt_and_inject.py` |
| Families on Temporal | `integration/temporal/test_wp_bp_010_temporal.py` (Stage Graph), `test_wp_bp_020_temporal.py` (GoalDirected), `test_rrm_016_goal_directed_journaled.py`, `test_rrm_008_*`, `test_wi04_saved_settlement_restart.py`, the replay modules |
| Output contracts and context transfer | `test_submission_foundation.py`, `test_w1_tool_boundary.py`, `test_wi04_lane_settlement.py`, `test_output_fulfillment.py`, `test_transfer_materializer.py`, `test_transfer_plan.py` |
| Persistence | `integration/deep_agents/test_checkpoint_lineage_postgres_saver.py`, `test_runtime_persistence_postgres.py`, `integration/postgres/test_checkpoint_lineage_postgres.py`, `test_manifest_submit.py`, `test_skill_bundle_materialization.py` |
| End to end | the two acceptance tests in step 5 G5 |

## 7. Decisions for the owner

Everything else in this document is a default I would apply in startup mode.

1. **Qualia and AI Engineer paid-fixture cluster** (`tests/fixtures/qualia_*`, `aieng_*`, 8.6k lines, plus 13 self-test files).
   - **Recommended:** move the drivers to `experiments/knowledge_loop/`, where `scripts/qualia_stagegraph.py` and `scripts/aieng_stagegraph.py` can still import them, and delete the self-tests.
   - The alternative is to delete everything once Build 08 loops 7 and 8 are reviewed.
   - Before either, give `unit/authoring/test_schema_only_stage_inputs.py` and `integration/postgres/test_manifest_fork_admission.py` their own small fixtures, because they import this cluster today.
2. **Dead `src` with its tests.** Recommended: yes, delete together. None of these has a caller (verified by grep):
   - `bootstrap/terminal_adoption.py` and the terminal-evidence adoption readers
   - `application/outputs/linked_adoption.py`
   - `application/recovery/graph_runtime_dispatch.py`, `runtime_reconciliation.py`, `runtime_decisions.py`, `agent_server_actions.py`, `runtime_events`, `runtime_interventions`, `runtime_resources`
   - `adapters/agent_server/client.py`
   - the Block C qualification package, if you retire that profile

   Run `make typecheck` and `make test-integration` after the removal.
3. **Paid drills.** Recommended: delete the 12 listed. Keep one owner-run drill per lane through `make lane-qualify LIVE=1`, and wire `deep_agents/test_agent_configuration_live.py` to a target. It is the only Deep Agents test against the real provider wire, and nothing runs it today.
4. **Report-source foundation fixture.** Recommended: delete the three `test_report_source_*` files together with `scripts/report_source_*.py`, unless that W1/W2 foundation fixture is still planned.

## 8. Defects found along the way

| Defect | Status |
| --- | --- |
| `make test-unit-fast` (xdist) cannot collect: `uuid4()` in a `parametrize` list | verified by running it |
| 2 unit tests fail today after the `langgraph_checkpoint_locator` setting was added (one uses a `SimpleNamespace` in place of `Settings`) | verified by running it |
| The fast suites take 38.5 minutes serially, and the parallel target is broken (first row), so `make check` is slow in practice | verified |
| 12 of 41 entries in the conftest psycopg selector list name missing files | verified |
| 28 test files skip when the Temporal time-skipping server fails to start | verified by grep |
| Five operator scripts import `tests.*`; two are the zero-cost Deep Agents drill and the live AI Engineer watch | verified |
| `src` reads fixture data from `tests/fixtures` (Codex schema dir, db-contract seed custody sources) | verified |
| `src/mission_control/adapters/operations/conformance.py` is test-only code in the product | verified |
| `integration/postgres/test_lane_bindings.py` and `test_release_0033.py` compare against describes that migration 0073 changed and are probably failing | reviewed, unrun |
| `test_run2_release_141`'s `retained_release_130` restores 1.3.0 from pre-move commit `a3a78441`, which a fresh clone will not have | reviewed |
| 7 Biotech schema tests skip unless `BIOTECH_SCHEMA_SDL_PATH` names a sibling checkout, so they never run in CI | reviewed |
| `test_wp_bp_010_recovery` is skipped on win32 | reviewed |

## How this review was made

- Per-file metrics (size, test count, doubles, cross-test imports) and an import graph were computed over all 1,212 files.
- Ten reviewers each read one disjoint slice in full against one rubric. They classified every double as boundary, real infrastructure, port fake, internal mock, scenario builder or test-as-library, and gave every file a verdict.
- I checked the highest-impact claims myself: dead-code callers, scripts importing tests, the step 1 import closure and collection, and the evidence citations. One reviewer claim was wrong and was dropped: `runtime_persistence_verifier.py` names `biotech_mission_adapters` only in a list of forbidden schemas, not as an import.
- Baseline, before any change (verified): `pytest tests/unit tests/architecture tests/conformance`, run serially on the owner's Windows host, gave **8,577 passed, 2 failed, 50 skipped, 2 xfailed in 38.5 minutes**. Integration, acceptance and qualification were not run (they need `make dev`).
  - Both failures come from the new `langgraph_checkpoint_locator` setting.
  - `unit/operations/test_rrm_009_cancellation_composition.py::test_composition_resources_are_closed_when_build_or_worker_start_fails` builds settings as a `SimpleNamespace`, which lacks the new field. This is the drift section 1 warns about: a hand-made stand-in for our own `Settings` instead of `isolated_settings()`.
  - `unit/operations/test_sprint_oc_runtime_env.py::test_real_settings_loader_takes_nothing_unlisted_from_an_owner_env` writes the value `poison61` into every field, and the new field's host:port pattern rejects it.
  - Both belong in step 0.
