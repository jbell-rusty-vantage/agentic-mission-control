---
type: Specification
title: "Tracing proposal: the Mission Transcript and the precise fork, as an implementation plan in three stages (capture model, schema delta, write path, read model, precise fork, remote saver, agent-side writes, retention outline, determinism, proofs, decisions; then real fixtures on a budget; then review, clean code, tests and documentation)"
description: "The ready-to-implement proposal the tracing and observability brief asked for, researched and audited on main (2714ae0f) on 2026-10-21. Part A restates the goal and the audit corrections. Part B is the proposal in the brief's order P1-P11: one capture row per lifecycle moment of both workflow families with Deep Agents inside; the release 1.4.4 migrations; the writers as deep modules behind the existing routers; the Transcript read model with a worked example at the seven granularities; the precise fork for Stage Graph and Goal Directed; the remote saver outcomes; the agent-side writes; the retention outline; the determinism table; the FX-TR proofs; the TR-D decisions with recommendations; the honest list. Part C is the owner's three stages: implementation with minimal verification (one session over work packages WP-TR-1..5, write side before read side and fork, a commit per package), real fixtures on a 10 USD cognition budget, then adversarial review, clean code, tests and documentation. Every decision is closed in P10 (2026-10-21)."
tags: [mission-control, providers, consolidation, deep-agents, tracing, transcript, cognition-points, forks, proposal, P1]
status: archived
archived: 2026-11-02
archived_from: TRACING-PROPOSAL.md
archived_reason: "built and merged 2026-10-22; facts in the transcript and precise-fork concepts and ADR-0054..0057"
---

> **Archived 2026-11-02** (built and merged 2026-10-22; facts in the transcript and precise-fork concepts and ADR-0054..0057). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Tracing proposal: the Mission Transcript and the precise fork

**Status (2026-10-21):** proposal for owner confirmation (PROCESS step 4). Nothing in this
document is built. It answers [archive/specs/TRACING-AND-OBSERVABILITY.md](../specs/TRACING-AND-OBSERVABILITY.md)
Part III and is the plan a session can start from once the decisions in §P10 are recorded.

Paths are relative to `platform/mission-control`; `src/` prefixes are dropped under
`src/mission_control/`. `M/` is `packages/mission-control-db-contract/component/migrations/`,
`M143/` is `packages/mission-control-db-contract/releases/1.4.3/component/migrations/`.
Installed versions read on 2026-10-21: `deepagents 0.7.5`, `langchain 1.3.14`,
`langchain-core 1.5.3`, `langgraph 1.2.10`, `langgraph-checkpoint-postgres 3.1.1`,
`langgraph-api 0.12.0`, `langgraph-runtime-inmem 0.32.0`, `temporalio 1.34.0`. Every
`file:line` below was read on `main` at `2714ae0f` on 2026-10-21; library claims cite the
installed file or a page fetched that day. Vocabulary follows `GLOSSARY.md`: **Transcript**
(never "trace"), **Provider Frame**, **Closing Frame**, **Native Event Store**, **Activation**,
**Snapshot**, **Fork**; **Cognition Point** is the turn 4 term for one root checkpoint of a
unit generation.

## Part A. Orientation and audit

### A.1 The goal, restated

The owner wants to read a literal, complete record of every step a mission went through,
written by the harness and never by the working agent, from Mission Control's own tables,
granular enough that "Temporal activity attempt → Deep Agents graph step" resolves to the
exact state at that point and the exact input and output of that step, with the sandbox
state and the lifecycle decisions around it. And the owner wants to fork a Stage Graph run
from Stage 2 cycle 2 at a chosen point, inject a message, and run the result as a new
workflow that reuses everything before that point without re-running it. The first is the
substrate for recursive self-improvement; the second is the way to use it.

### A.2 What the audit changed in the brief (read before the rest)

The brief's Part I holds, with these corrections, each cited:

| Brief said | What the code does | Where |
| --- | --- | --- |
| "`point_ref` on stream frames is declared, not written" | `mc.stream_envelope.v1` has no `point_ref` field at all; the declared-and-unwritten field is `payload_ref` | `domain/subscriptions/streams.py:165-185`; `application/frames/streams.py:218-228` |
| "no caller passes the `FrameWriter` promoter" | true, and there is no `FrameBodyPromoter` implementation in `src` either; the writer's promotion branch is complete but dead (eight constructor sites, none pass `promoter=`) | `application/frames/writer.py:82-99,136-149`; `adapters/deep_agents/adapter.py:601-606` |
| "the application docstring says one transaction" | the docstring says points are recorded "right after the result" and that "a points write failure is logged, not raised"; the transition and the result are one transaction, points a second, `operation_settlement` a third | `application/execution/operations/checkpoint_lineage.py:1138-1143,1177-1179,1222-1227`; `adapters/postgres/operations/checkpoint_lineage.py:339-437`; `adapters/postgres/operations/cognition_points.py:73`; `application/execution/operations/operation_journal.py:393-446` |
| "`checkpointer_ref_digest` is stamped on every root checkpoint" | it is part of `QualifiedCheckpointKey` and the plan check, not a checkpoint metadata stamp; the stamps are the invocation stamps and the state-schema digest | `adapters/deep_agents/adapter.py:881-898,911,955` |
| "the compatibility check compares `binding_digest`" | it compares `reuse_compatibility_digest` (the binding with run-scoped fields stripped, `prompt_sources` kept) and `state_schema_digest`; a mismatch settles the reused unit `failed` with `incompatible_restore` | `application/recovery/run_forks.py:1478-1496,1587-1603`; `application/execution/operations/operation_execution.py:1524-1535` |
| "an `activation` row per unit at admission" | the only `activation` insert is per attempt, in `record_attempt` | `adapters/postgres/operations/checkpoint_lineage.py:106-131` |
| "`mission_event` in `M/0003`" | `mission_event` is created in `M/0005_commands_effects_recovery.sql:52-84`; `activation_id` is nullable and never populated | `adapters/postgres/run_control/canonical.py:559,735` |
| "the fork request is `mc.fork_request`" | the scoped contract is `mc.runtime_fork.v1` (`MissionForkRequest`); the kernel route has the same fields minus `instruction` | `contracts/runtime_contracts.py:18-41`; `interfaces/http/run_forks.py:198-212` |
| "the Agent Server children run on the server's own saver" | in this repository the Agent Server is the in-memory runtime edition: its checkpointer pickles to `.langgraph_api/.langgraph_checkpoint.N.pckl`; the Postgres runtime is a separate package that is not installed | installed `langgraph_api/cli.py:195,485-487`; `langgraph_runtime_inmem/checkpoint.py:51-80` |
| "a `wrap_model_call` middleware placed after the summarizer sees the model input" | a middleware passed through `create_deep_agent` is inserted after the core middleware and **before** the prompt-caching, memory and tool-exclusion tail, so it does not see the final `model_settings`, memory text or tool exclusion; the exact provider input exists only at the chat-model boundary | installed `deepagents/graph.py:201-235,855-893`; `langchain/agents/factory.py:235-324,1406-1431` |

Two more facts the brief did not have:

- The adapter already attaches two callback handlers at the chat-model boundary on every
  invocation (`_SkillDisclosureObserver.on_chat_model_start`, `_ModelCallObserver.on_llm_end`),
  with `run_inline = True`, through `config["callbacks"]`
  (`adapters/deep_agents/adapter.py:253,310,342,1498-1560`). LangGraph stamps
  `langgraph_step`, `langgraph_node` and `langgraph_checkpoint_ns` on the callback metadata of
  every task (installed `langgraph/pregel/_algo.py:655-659`). The model-input record therefore
  has a precise, order-independent home: a third observer on the same config.
- The Stage Graph workflow accepts a full `initial_projection` input and skips
  `stagegraph.initialize` when it is given; it is used only by continue-as-new
  (`adapters/temporal/workflows/stagegraph.py:341-380,1421-1427`;
  `domain/programs/contracts.py:1023`). The interpreter's `_descendants` already closes a
  cycle's invalidation over dependants (`domain/programs/interpreter.py:506-508,556,1225-1240`);
  the fork policy never sees the blueprint (`domain/policies/forks.py:576-627`).

### A.3 Research findings that shape the design (R1-R5)

- **R1.** The exact input of a model call is `[system_message, *messages]` with the tools,
  tool choice and `model_settings` bound at the innermost handler
  (`langchain/agents/factory.py:1415-1419,1389-1404`). Summarization on this lane rewrites
  `messages` inside `wrap_model_call` without touching state
  (`deepagents/middleware/summarization.py:1341-1343,1381`). No release note between
  `langchain 1.3.14` and `1.4.6` (2026-10-14) changes `ModelRequest`, `override()` or the
  composition order; `deepagents 0.7.19` adds a multimodal-filter middleware whose position
  relative to user middleware is unverified. Conclusion: record at the chat-model boundary
  (callback), not in a middleware.
- **R2.** `AsyncPostgresSaver 3.1.1`: `aget_tuple` and `alist` are one SQL statement each
  (`langgraph/checkpoint/postgres/aio.py:119-230`; `base.py:93-118`); `aput` is one pipelined
  batch (`aio.py:232-305`); every operation takes one `asyncio.Lock` (`aio.py:374`); the
  `messages` channel is a `DeltaChannel(snapshot_frequency=50)` whose per-step content lives in
  `checkpoint_writes` rows (`deepagents/graph.py:71-73`; `langgraph/pregel/_checkpoint.py:159-166`);
  there is no `acopy_thread`, `aprune` or TTL in 3.1.1 (`prune` arrived in 3.2.0 on
  2026-10-14). Conclusion: the settlement walk is N round trips of one query each; the copy in
  `seed_fork` is 2N; both are bounded and budgetable.
- **R3.** Temporal history is retention-scoped (3 days self-hosted default, 30 on Cloud) and
  holds only the final attempt's Started and Completed events, with `attempt` and
  `last_failure` on `ActivityTaskStarted`; continue-as-new links segments by
  `continued_execution_run_id` (`temporalio/api/history/v1/message_pb2.pyi:113-132`;
  https://docs.temporal.io/temporal-service/temporal-server#retention-period). Conclusion:
  the Transcript keeps its own attempt rows (it does); history is a cross-check, never a source.
- **R4.** LangSmith, Braintrust, OpenAI Agents, Inspect and Claude Code converge on one
  minimal replay record: step id, parent id, type, timestamps, attempt, the exact serialized
  input, the output or failure, provenance, with large bodies offloaded to a blob store and
  retention defaults of 3-30 days. Conclusion: the Transcript step entry (§P4) follows that
  shape; bodies go to the payload store by digest; retention follows the mission (§P8a).
- **R5.** The Agent Server here persists in memory; the platform's Postgres runtime would use
  the same unqualified table names as the OSS saver (`langgraph_api/schema.py:389-393`), and
  sharing one schema is an open upstream issue (#7345). Thread TTL exists only on the server
  (`strategy delete|keep_latest`, minutes). Conclusion: do not share a schema; read child
  state through the server's API (§P6).

### A.4 Gap labels (general or provider-specific)

| Gap | Label | Closed by |
| --- | --- | --- |
| TR-G1 model input | provider-specific capture (deep_agents observer), general frame kind | TR-2 |
| TR-G2 full bodies | general (promoter, reader, download route) | TR-2, TR-3 |
| TR-G3 retention | general (policy classes, expiry) | TR-3 |
| TR-G4 hook ports | provider-specific wiring, general callback service | TR-2 |
| TR-G5 subagent steps | provider-specific (recorder, collector), general contract relaxation | TR-2 |
| TR-G6 points transaction, reconciler | general | TR-1 |
| TR-G7 joinability | general | TR-1 |
| TR-G8 environment | provider-specific manifest, general point columns | TR-2 |
| TR-G9 lifecycle writers | general | TR-1 |
| TR-G10 reads | general | TR-3 |
| TR-G11 submission | queued session | later |
| TR-G12 other lanes | by construction (ports, contracts) | later sprints |
| TR-G13, G14 precise fork | general | TR-4 |
| TR-G15, G16 saver locality, pruning | general outline, provider-specific outcomes | TR-5, later |

## Part B. The proposal

### P1 Capture model

One row per lifecycle moment of brief §2, per family. "Txn" names the transaction the write
belongs to; "Q" names which of the six questions (who, in, out, environment, control,
lifecycle) the row answers. **exists** means proven on T0 today; **change** means an existing
writer changes; **new** means a new writer.

#### P1.1 Stage Graph with Deep Agents inside

| Moment | Trigger | Written | Stable key | Writer | Txn | Q | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Run start | `POST runs/{id}/launch` → `stagegraph.initialize` | `workflow_run.start` event, `run_lifecycle_transition`, `mission_run` CAS | command `stagegraph:{run}:start`; event `seq` | `ProgramService.initialize` → `commit_command` | one (`_apply_transition`) | lifecycle | exists (`application/programs/service.py:327-363`; `run_control_repository.py:236-333`) |
| Run start | after `start_workflow` returns | `mission_run.temporal_workflow_id`, `temporal_run_id` | run id | `RunLaunchService.launch` → new `update_temporal_ids` | own, idempotent (same values) | who | **new** (F-T4-2; columns `M/0003:22-23`) |
| Unit released | join released in the interpreter | family journal `operation_admitted` (proposal with `frozen_input_bindings`, projection), `workflow_run.reserve_budget` event, `family_admission_head` | `mutation_id = admit-{sha7(semantic_key)}`; `(run_key, family_kind, mutation_key)` | `admit_operation` → `commit_family_admission` | one | lifecycle | exists (`service.py:365-492`; `run_control_repository.py:575-787`) |
| Unit released | same | proposal gains typed `released_by: [{dependency_id, join_id, producer_unit_key, producer_output_slot_id, accepted_decision_ref}]` built from `frozen_input_bindings`; the event gains `unit_key` | same mutation | interpreter `operation_proposal`; event envelope | same | lifecycle, who | **change** (data already in `StageInputBinding`, `contracts.py:482-495`; `interpreter.py:1180-1191`) |
| Unit released | before admission | sealed Context Packet (`context_selection`: packet, selection, digests) | `selection_key`, `packet_key` | `pack_for_stage` → `seal` | own (before the admission txn) | in | exists (`pack_service.py:304-388,1002-1053`; `M/0027:247-285`) |
| Unit released | after admission | `operation.binding/1` and `operation.binding-index/1` documents | `semantic_attempt_key`, `binding_id` | `operation_binding_repository` | own | in | exists (`operation_binding_repository.py:65-119`) |
| Attempt starts | `operation.execute` activity admission | `activation` (key = unit key), `attempt`, `activity_attempt_observation` (workflow, run, activity, attempt, worker, task queue) | `activation_key`; attempt observation key | `record_attempt` | one | who | exists (`adapters/postgres/operations/checkpoint_lineage.py:106-131,245-257,748-767`) |
| Attempt starts | recorder `begin` | `session_init`, `turn_started` frames; `harness_execution`, `agent_session`, `session_turn` identity rows | `(harness_execution_id, generation, provider_key)` | `DeepAgentFrameRecorder` → `FrameWriter` → `PostgresFrameRepository` | one per append | who | exists (`adapter.py:271-277`; `frames/repository.py:429-430,469-473`) |
| Attempt starts | materializer seeded the backend | **`environment_materialized` frame**: `[{path, slot, bytes, digest, destination: state_channel \| sandbox_upload}]`, skill mounts, MCP servers connected, model resolved; body promoted when over the cap | `provider_key = materialization:{invocation_id}` | materializer returns the manifest; the adapter records it right after `begin` | frame append | environment | **new** (manifest data exists in `materializer.py:911-931`; the frame kind is new) |
| Each model call | chat model starts (`on_chat_model_start`) | **`model_request` frame**: `{langgraph: {step, node, checkpoint_ns}, model: {name, provider, invocation_params_digest}, system: {digest, bytes}, messages: [{id, type, digest, bytes}], tools: [{name, schema_digest}], tool_choice, follow_up: bool}`; full request promoted (§P3.3) | `deep_agents_key(thread, ns, None, step, "call:{n}", "model_request")` | `_ModelRequestObserver` → recorder → writer | frame append | in | **new** (TR-G1) |
| Each model call | AI message arrives | `message_delta`, `message` (content, tool calls, usage, model) | existing keys | recorder | frame append | out | exists (`frames.py:509-563`) |
| Each tool call | tool call start, tool message | `tool_call_started`, `tool_call_completed \| failed` (body under the cap; **full body promoted** over it) | existing keys | recorder, writer with promoter | frame append | out | **change** (TR-G2; `writer.py:136-149`) |
| Subagent (sync) | `task` tool call start and its tool message | **`subagent_started`** (name, description, tool call ref, `subordinate_ref`) and **`subagent_ended`** (closing; status, result digest, usage) frames; nested-namespace checkpoints become **points** with `subordinate_ref` and `parent_point_id` | existing keys plus the nested checkpoint key | recorder; `collect_points` over nested namespaces | frame append; settlement txn | out, who | **new** (TR-G5; `frames.py:184-202,249-252`; `cognition_points.py:76`) |
| Subagent (async) | spawn, admit, settle | `subordinate_execution` row, lineage edge; **`subagent_started/ended`** frames from the async middleware; points `lifecycle_only` (see §P6) | child execution id | async middleware → recorder | frame append | out, who | **change** (`adapters/postgres/async_subagents/async_subagents.py:83`) |
| Hook invoked | hook dispatcher event | `hook_invoked`, `hook_result` frames (kinds exist, ports Null) | `custom.mc.hook_*` keys | kernel hook ports → stream writer → recorder | frame append | out | **change** (TR-G4; `hooks.py:235-242`; `kinds.py:94-95`) |
| Compaction, approval, usage | existing custom events | `before/after_compaction`, `approval_requested/resolved`, `usage` | existing | existing | frame append | out, control | exists |
| Each graph step | `checkpoints` stream part | the recorder keys the step's frames by the root checkpoint id (pending keys → `frame_from/to_ordinal` at settlement) | checkpoint id | recorder | in memory until settlement | who | exists (`frames.py:184-202`) |
| Attempt settles | `_settle` | `checkpoint_transition`, `unit_result_observation`, **`cognition_point` rows in the same transaction**; result point gains `workspace_checkpoint_ref` and `budget_snapshot`; `session_turn.point_ref`, `agent_session.checkpoint_*` on the closing frames | point id `uuid5(scope, unit_key, generation, kind, locator)`; transition id | `CheckpointLineageService.record_result` → `PostgresCheckpointLineageRepository.record_result(…, points)` | **one** | who, environment | **change** (TR-G6; today `checkpoint_lineage.py:1177-1179`) |
| Attempt settles | same | `operation_settlement` (usage, manifest ref; output in the payload store), `operation_receipt`; derived events `session.*`, `tool_call.completed`, `attempt.completed` **with `activation_id`, `unit_key` and `point_ref`** | settlement id; `seq` | journal; `FrameFactProjector` | later txn; event txn | out, who | **change** (TR-G7; `canonical.py:559,735`) |
| Decision over a result | `result_decided` | journal mutation (proposal, observation digest, completion validation), `workflow_run.apply_authority_batch` event with `unit_key`; **`completion_decision` row** (`decision_key = mutation_id`, disposition, reason codes, activation) and **`completion_candidate`** (from the settlement's result manifest) | `result-{sha7}`; `decision_key` | `result_decided` → `commit_family_admission` + new completion repository | one | lifecycle | **new** writer over existing tables (TR-G9; `M/0003:381-432`) |
| Cycle advance | `cycle_decided` | journal mutation (proposal with `prior_result_refs`, `unmet_obligation_refs`, `next_objective`), `RecordUsage` event; new candidates at `stage_cycle_ordinal + 1`; the re-admitted unit's proposal gains **`continues_from: {prior_unit_key, prior_result_ref}`**; the new cycle's input point gets `parent_coordinate` = the prior cycle's result point with role **`cycle_start`** | `cycle-{run}-{scope}-{stage}-{ordinal}` | interpreter; points repository at settlement | admission txn; settlement txn | lifecycle, who | **change** (`service.py:860-960`; `interpreter.py:562-579`); K05 delivery stays with the queued session |
| Intervention | mailbox delivery | `command`, `delivery_report`, `runtime_intervention`, `command.*` events; inject marks `interrupted` and `replacement_start` points; delivery report gains `point_ref` of the interrupted leaf | command id | existing | existing | control | **change** (F-T4-3) |
| Run end | completion | `workflow_run.complete` transition, `run.completed` projection | command id | existing | one | lifecycle | exists |
| After the clock | `frames.expire` | **delta-class frames only** deleted by `retain_days`; step-class frames kept for the mission's evidence life (`step_retain_days` NULL) | — | expiry function | own | — | **change** (TR-G3; `M/0027:205-216`) |

#### P1.2 Goal Directed with Deep Agents inside (differences only)

| Moment | Written | Status |
| --- | --- | --- |
| Run start | `goal.revision/1` document (`_key(run_id, revision_id)`), start command `goal:{run}:epoch:{e}:segment:{s}:start` from the workflow | exists (`goal_directed_repository.py:42`; `workflows/goal_directed.py:347-369`) |
| Unit released | `GoalFamilyDecisionMutation` (`{run}.goal.{iteration}.{role}.{attempt}`), executor and verifier bindings, packet; the proposal gains `released_by: {kind: iteration_start \| verifier_after_executor \| executor_after_verification, prior_unit_key, handoff_ref}` | **change** (`application/programs/goal_directed.py:426-537`) |
| Attempt and steps | identical to Stage Graph (same activity, same settlement: `operation.py:508-510,1081`) | same rows |
| Decision | `goal.iteration/1`, `goal.verification/1`, `goal.handoff/1` documents; **`completion_decision`** from the verifier's decision (`decision_key = verification_id`) | **new** writer |
| Iteration advance | points of iteration N+1 link to N's result on the same thread (exists); the first point of a fresh session generation gets `parent_coordinate` to the previous generation's result point with role `rollover_start` | **change** (declared in turn 4, not written) |
| Continue-as-new | **`workflow_run.record_rollover` event** (payload: technical segment, session generation, rollover count, handoff ref, closing Temporal run id) committed by a new boundary activity before `continue_as_new`; idempotent by command id `goal:{run}:epoch:{e}:segment:{s}:rollover` | **new** (TR-G9; `workflows/goal_directed.py:405-407,420-422,605-607`) |

#### P1.3 Rows that stay unwritten, and why

- `journal_segment` (`M/0003:318-335`): the Transcript projection (§P4) supersedes it; it
  stays unwritten and is a candidate for removal in a later cleanup.
- A per-step workspace snapshot on a sandbox backend: cost (TR-D8); the step keeps
  `files_digest`, the attempt end keeps the candidates; the materialization manifest names what
  was uploaded. A per-step snapshot is K11's later work.
- The system prompt as a mission event: never; it is a frame body under the artifact policy.
- Mission events for every frame: never (ADR 0028); the Transcript joins them.

### P2 Schema delta: release 1.4.4

Authored in `scripts/release_144/` and prepared by `scripts/prepare_release_144.py` on the
pattern of `prepare_release_143.py` (byte-identical 1.4.3 prefix, new files appended, built
on the disposable cluster with `mission-db release-build`, `release-spec.json` gains the 1.4.3
fingerprint in `compatible_previous_fingerprints`). Three migrations; RLS and grants in the
style of `M143/0045_cognition_points.sql:126-143` (quoted there). No lane-describe migration
is needed: nothing in `mc.lane_describe` changes.

#### 0047_transcript_joinability.sql

```sql
-- mission_event: the unit and the point an event belongs to (additive, NULL before 1.4.4).
-- The immutable trigger forbids UPDATE, not ALTER; writers fill the columns at insert.
ALTER TABLE mission_control.mission_event
    ADD COLUMN IF NOT EXISTS unit_key text
        CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    ADD COLUMN IF NOT EXISTS point_ref jsonb
        CHECK (point_ref IS NULL OR jsonb_typeof(point_ref) = 'object');
CREATE INDEX mission_event_run_unit_idx ON mission_control.mission_event
    (installation_id, application_id, tenant_id, run_id, unit_key, seq) WHERE unit_key IS NOT NULL;

-- cognition_point: subagent points, the restore level as a column, the prune reservation
-- (TR-D17: columns only; no writer this release), and the new roles are text[] already.
ALTER TABLE mission_control.cognition_point
    ADD COLUMN IF NOT EXISTS subordinate_ref text CHECK (subordinate_ref IS NULL OR subordinate_ref <> ''),
    ADD COLUMN IF NOT EXISTS restore_level text NOT NULL DEFAULT 'R3'
        CHECK (restore_level IN ('R0', 'R1', 'R2', 'R3')),
    ADD COLUMN IF NOT EXISTS pruned_at timestamptz,
    ADD COLUMN IF NOT EXISTS prune_policy text CHECK (prune_policy IS NULL OR prune_policy <> '');
GRANT UPDATE (subordinate_ref, restore_level, pruned_at, prune_policy)
    ON mission_control.cognition_point TO mission_control_runtime;
-- The guard trigger (0045) keeps identity fixed and forbids DELETE; unchanged.

-- provider_frame: the new kinds and the retention class. The closing rule is a table CHECK
-- without a name; it is located through pg_constraint and replaced by a named one.
DO $kinds$
DECLARE old_name text;
BEGIN
    SELECT conname INTO old_name FROM pg_constraint
    WHERE conrelid = 'mission_control.provider_frame'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%closing = (kind%';
    EXECUTE format('ALTER TABLE mission_control.provider_frame DROP CONSTRAINT %I', old_name);
END
$kinds$;
ALTER TABLE mission_control.provider_frame ADD CONSTRAINT provider_frame_closing_rule
    CHECK (closing = (kind IN (
        'tool_call_completed', 'tool_call_failed', 'approval_resolved', 'hook_result',
        'after_compaction', 'usage', 'turn_ended', 'run_result', 'session_state', 'error',
        'subagent_ended')));
-- Generated, so no backfill and no conflict with the reject_mutation trigger (0027:113-115).
ALTER TABLE mission_control.provider_frame
    ADD COLUMN IF NOT EXISTS retention_class text GENERATED ALWAYS AS (
        CASE WHEN kind IN ('message_delta', 'thinking_delta', 'tool_call_delta', 'heartbeat', 'status')
             THEN 'delta' ELSE 'step' END) STORED;
CREATE INDEX provider_frame_delta_expiry_idx ON mission_control.provider_frame
    (installation_id, application_id, tenant_id, observed_at) WHERE retention_class = 'delta';

-- frame_retention_policy: retain_days now governs the delta class; step frames live for the
-- mission's evidence life unless step_retain_days is set (TR-D1).
ALTER TABLE mission_control.frame_retention_policy
    ADD COLUMN IF NOT EXISTS step_retain_days integer
        CHECK (step_retain_days IS NULL OR step_retain_days >= 30),
    ADD COLUMN IF NOT EXISTS prune_mode text NOT NULL DEFAULT 'delete'
        CHECK (prune_mode IN ('delete', 'tombstone'));
-- The expiry function is replaced (CREATE OR REPLACE): deletes `retention_class = 'delta'`
-- older than retain_days, and step frames only when step_retain_days is set and the frame's
-- run is terminal and not pinned (pins arrive with TR-D17; until then step frames never expire).

-- mission_run.temporal ids: the runtime role may now fill them once.
GRANT UPDATE (temporal_workflow_id, temporal_run_id) ON mission_control.mission_run TO mission_control_runtime;

-- completion tables: the family writer inserts decisions and candidates (grants verified at
-- build against 0003; added here if absent).
GRANT SELECT, INSERT ON mission_control.completion_candidate, mission_control.completion_decision
    TO mission_control_runtime, mission_control_family_writer;
```

The new frame kinds in `domain/frames/contracts.py::FrameKind`: `MODEL_REQUEST`,
`ENVIRONMENT_MATERIALIZED`, `SUBAGENT_STARTED`, `SUBAGENT_ENDED` (closing), `PROGRESS_NOTE`
(reserved, §P7). `FULL_BODY_KINDS` gains `MODEL_REQUEST`, `ENVIRONMENT_MATERIALIZED`,
`TOOL_CALL_FAILED`, `SUBAGENT_ENDED`. The `CLOSING_KINDS` set gains `SUBAGENT_ENDED` and
the reducer derives `subordinate.ended` from it (ADR 0040's normalized vocabulary). The point
roles gain `cycle_start`, `reused`, `subagent_root`; `CheckpointPoint.root_only`
(`domain/execution/cognition_points.py`) becomes "root, or nested with a `subordinate_ref`".

#### 0048_transcript_entry.sql

```sql
-- The persisted Transcript projection (TR-D10): one row per entry of a finished attempt,
-- cursor-addressable, point-addressable, refreshed by the transcript.project activity.
-- Replaced per run under the same advisory lock the search projection uses (0027:136-157).
CREATE TABLE mission_control.transcript_entry (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    cursor text NOT NULL CHECK (cursor ~ '^tc1:'),
    entry_seq bigint NOT NULL CHECK (entry_seq >= 1),
    unit_key text CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    activation_id uuid,
    point_id uuid,
    parent_point_id uuid,
    node_key text,
    iteration bigint,
    cycle bigint,
    session_generation bigint,
    subordinate_ref text,
    source text NOT NULL CHECK (source IN ('mission_event', 'provider_frame', 'artifact', 'human', 'command')),
    kind text NOT NULL,
    role text NOT NULL,
    canonical boolean NOT NULL,
    at timestamptz NOT NULL,
    body_state text NOT NULL CHECK (body_state IN ('inline', 'excerpt', 'artifact', 'expired', 'pruned')),
    entry jsonb NOT NULL CHECK (jsonb_typeof(entry) = 'object' AND entry->>'schema_version' = 'mc.transcript_entry.v2'),
    projected_at timestamptz NOT NULL,
    projection_version integer NOT NULL CHECK (projection_version >= 1),
    PRIMARY KEY (installation_id, application_id, tenant_id, run_id, cursor),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_id)
);
CREATE INDEX transcript_entry_point_idx ON mission_control.transcript_entry
    (installation_id, application_id, tenant_id, run_id, point_id, entry_seq);
CREATE INDEX transcript_entry_unit_idx ON mission_control.transcript_entry
    (installation_id, application_id, tenant_id, run_id, unit_key, entry_seq);
-- RLS (ENABLE, FORCE, policy on the scope columns) and grants: SELECT, INSERT, DELETE to
-- mission_control_runtime (replace-by-run), SELECT to mission_control_readonly.
CREATE TABLE mission_control.transcript_projection_state (
    installation_id uuid NOT NULL, application_id text NOT NULL, tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    projected_through_seq bigint NOT NULL,
    projected_through_frame jsonb,
    projection_version integer NOT NULL,
    projected_at timestamptz NOT NULL,
    PRIMARY KEY (installation_id, application_id, tenant_id, run_id)
);
```

#### 0049_frame_body_refs.sql

Nothing structural: `provider_frame.body_artifact_ref` exists (`M/0027:81`). The migration
only documents the `frame-body://sha256:<hex>?bytes=<n>&type=<media>` reference scheme in a
comment and adds `COMMENT ON COLUMN`. If the owner picks governed artifacts for frame bodies
(§P10 TR-D3), this file is dropped.

### P3 Write path

Deep modules behind the existing routers; general changes are kernel modules, provider
changes stay in `adapters/deep_agents/` and read only their own discriminated container.
Each item names the module that is its finished part and the test that proves it.

#### P3.1 General: settlement in one transaction, and the reconciler (TR-D6)

- `application/execution/operations/checkpoint_lineage.py::record_result` passes the lane's
  points into the repository call instead of a second write
  (today `:1177-1179`, `_record_points :1222-1227`). The port `CheckpointLineageRepository.record_result`
  gains `points: tuple[CognitionPointObservation, ...]`.
- `adapters/postgres/operations/checkpoint_lineage.py::record_result` (`:339-437`) inserts the
  transition, the result observation and then the point rows on the same connection and
  transaction, using the existing `PostgresCognitionPointRepository` insert statement
  (`cognition_points.py:308`, `ON CONFLICT (…, point_id) DO NOTHING`) through a new
  `record_in(connection, …)` entry point; the parent-by-locator, turn-by-native-ref and
  frame-range resolution stay as they are. A failure rolls everything back and raises; the
  activity error maps to the existing non-retryable `checkpoint_lineage_conflict` class
  (`adapters/temporal/operation_activities.py:186-212`), so the unit goes `in_doubt` with an
  incident and the reconciler repairs it. A transient failure retries the activity; the
  classifier then finds the stamped leaf and reconstructs without re-running cognition
  (`TERMINAL_UNOBSERVED`, `adapter.py:1113-1150`), which is why the transaction is safe to
  retry.
- The result point gets `workspace_checkpoint_ref = "workspace-candidates://{harness_execution_id}/{generation}#{digest}"`
  (a digest over the attempt's `workspace_candidate_descriptor` rows, which the adapter
  registers before the result, `adapter.py:393-395`) and `budget_snapshot` from the
  settlement's usage (settled amounts, reservation id) through the repository's existing
  `_ENRICHABLE` path (`cognition_points.py:45-46`, `.enrich` has no caller today).
- New `application/execution/operations/point_reconciliation.py::PointReconciler`:
  for a run (optionally one unit), every settled generation whose transition exists and whose
  point rows are missing, fewer than the stamped checkpoint count, or lack a frame range, is
  re-derived through a new `TimeTravelLane.collect_points(namespace, source_key, result_key)`
  port method (the Deep Agents implementation is `collect_points` as it is,
  `adapters/deep_agents/cognition_points.py:51-157`), frame ranges resolved from the frame
  store by provider keys, rows written with `written_by = reconciler`. It distinguishes
  `pruned` (`pruned_at` set) from `missing`. Outcome `mc.points_reconciliation.v1`:
  `{generations_checked, points_added, frame_ranges_filled, pruned, saver_unreachable: [unit…]}`.
  Surfaces: `POST runs/{id}/points:reconcile` (permission `workflow_run.reconcile_unit`, the
  existing reconciliation grant), `missionctl run points RUN --reconcile`, MCP
  `mission_run_points_reconcile`. Test: a unit test with the in-memory repositories and a
  fake lane; FX-TR-RECONCILE on T0.
- Finished part: `application/execution/operations/checkpoint_lineage.py` (reading order:
  `RuntimeResult.cognition_points` → `record_result` → the Postgres repository → the rows),
  proven by `tests/unit/operations/test_cognition_points.py` (transaction case) and FX-TR-STEP.

#### P3.2 General: joinability on mission events (TR-D7)

- `DomainEventEnvelope` (produced by `reduce_lifecycle`, `domain/policies/reducer.py:666-683`)
  gains optional `unit_key`, `activation_id`, `point_ref`. `canonical.append_events` and
  `append_mission_events` bind them (`canonical.py:551-575,727-750`) instead of the literal
  NULL.
- Who fills them: the family admission, result, cycle and completion commands pass the
  proposal's unit key (`application/programs/service.py:425-475,680-704,926,1074`); the
  `FrameFactProjector` passes the frame handle's `activation_id`, the unit key resolved from
  the activation row, and for closing frames that carry a checkpoint (`turn_ended`,
  `run_result` with `result_checkpoint_id`, `frames.py:324-328`) the point ref; the
  Temporal attempt path passes the activation. Run-level events keep NULLs.
- Transcript placement changes from "by time under the last event" to "by unit and point when
  known, by time otherwise" (`application/frames/transcript.py:454-455`).
- `mission_run.temporal_workflow_id/run_id`: `RunLaunchService.launch` records them after
  `start_workflow` through `RunControlRepository.record_temporal_ids` (idempotent on equal
  values; a different run id on a re-launch is a refusal). Test: `tests/unit/execution/test_run_launch*.py`.

#### P3.3 General: the promoter and the body reader (TR-D2, TR-D3)

- `adapters/storage/frame_body_promoter.py::PayloadStoreFrameBodyPromoter` implements
  `FrameBodyPromoter.promote_frame_body` (`application/frames/writer.py:40-50`): stages the
  canonical body bytes in the `ArtifactPayloadPort` (content-addressed `sha256`, the same
  store the settlement output uses, `application/artifacts/artifact_promotion.py:64-74`) and
  returns `frame-body://sha256:<hex>?bytes=<n>&type=<media>`. No `artifact_metadata_revision`
  row: a frame body is evidence of a frame, already registered by the frame row (digest,
  bytes, media type), not a governed artifact. The governed path stays for artifacts the
  agent submits.
- `FullBodyPolicy` (`writer.py:55-69`) is selected by a **system lever, never by a manifest**
  (owner, 2026-10-21: coordinator agents do not choose capture behaviour). A new deep module
  `application/frames/capture_policy.py` holds a `FrameCapturePolicy` registry keyed by
  profile name; the deployment setting `MISSION_CONTROL_FRAME_CAPTURE_PROFILE`
  (`bootstrap/settings.py`) picks one at composition and every `FrameWriter` site receives
  the policy and the promoter from composition. Two profiles ship: `standard` (cap 8 KiB;
  promote `model_request` per-message objects and batch digest, `tool_call_completed`,
  `tool_call_failed`, `message`, `run_result`, `environment_materialized`, `subagent_ended`;
  max body 2 MiB) and `full_requests` (`standard` plus the whole batch of every
  `model_request`). The profile name is recorded on `harness_execution.native_identity` so a
  Transcript reader knows what was captured. `provider_options` carries nothing about capture.
- The two extension points for "different transcript storage behaviour" (owner, 2026-10-21):
  the `FrameCapturePolicy` (what is promoted, at which cap, which kinds) and the
  `FrameBodyPromoter` port (where promoted bodies go and how they are referenced). A new
  storage behaviour is a new policy entry or a new promoter implementation registered in
  composition; the writer, the recorder and the Transcript reader do not change.
- Every production `FrameWriter(` site that observes a lane with bodies passes the promoter
  (`adapter.py:601-606` first; the seven other sites get it when their lanes are consolidated).
- `GrantedArtifactBodyReader.read` (`application/frames/artifact_bodies.py:74-104`) learns the
  `frame-body://` scheme: resolve the frame row by digest within the run's scope (the caller
  names the run), check `workflow.result.read`, retrieve by digest and verify bytes. The
  4 000 000-byte cap stays.
- Finished part: `adapters/storage/frame_body_promoter.py` with
  `tests/unit/frames/test_frame_writer.py` (promotion through a real in-memory payload store)
  and FX-TR-STEP (`--full` resolves a 100 KiB tool result).

#### P3.4 Deep Agents: the model-input record (TR-G1, TR-D2)

- `adapters/deep_agents/adapter.py::_ModelRequestObserver(BaseCallbackHandler)`, `run_inline = True`,
  attached beside `_SkillDisclosureObserver` and `_ModelCallObserver` on every `config["callbacks"]`
  (`adapter.py:253,310,342`). On `on_chat_model_start(serialized, messages, run_id, parent_run_id, metadata, **kwargs)`
  it reads `metadata["langgraph_step" | "langgraph_node" | "langgraph_checkpoint_ns"]`
  (installed `langgraph/pregel/_algo.py:655-659`) and `kwargs["invocation_params"]` (the bound
  tools and model settings; verified at build for the OpenAI and Anthropic chat models,
  `langchain_core/language_models/chat_models.py:1465-1472`), and hands the recorder one
  `FrameObservation(kind=MODEL_REQUEST, raw_kind="model.request", provider_key=deep_agents_key(thread, ns, None, step, f"call:{n}", "model_request"), subordinate_ref=…)`
  with the body of §P1 and, for promotion, the exact batch `[system_message, *messages]` plus
  the tool schemas as canonical JSON. `n` counts calls within the step (one per model call,
  retries included). The callback runs on the event loop thread before the model is called, so
  the frame's arrival ordinal precedes the response frames.
- Why a callback and not a middleware: §A.2 last row and §A.3 R1. The callback sees the
  literal provider input after every middleware, including the prompt-caching tail.
- Message bodies: every message id in the request is either already a frame (AI and tool
  messages are frames with digests) or a human or system message. The observer promotes the
  human and system message bodies once per attempt by digest (content-addressed, so a system
  message repeated on every call costs one object), and the `model_request` body lists ids and
  digests. Replay (§P4.3) reconstructs the batch from the frames and those objects; the
  promoted full batch is the byte-exact check. Decision TR-D2a (§P10): promote the full batch
  on every call, or only the per-message objects plus the batch digest.
- Finished part: `adapters/deep_agents/adapter.py::_ModelRequestObserver` and
  `adapters/deep_agents/frames.py::model_request_body`, proven by
  `tests/unit/deep_agents/test_frame_recorder.py` (a scripted model, three calls, three frames
  with the right step keys) and FX-TR-REPLAY.

#### P3.5 Deep Agents: hook ports and the callback (TR-G4, TR-D4)

- `adapters/temporal/deployment_composition.py:436-445` builds `ExactComponentRegistry(... kernel_hooks=KernelHookPorts(...))`
  with real ports: `stop_fence = KernelHookFenceGate(PostgresStopFenceRepository(pool))`
  (`application/execution/stop_fence.py:77`), `intents = HookIntentLedgerShim(PostgresHookIntentLedger(pool))`
  (adapts `OperationIntentLedger.record_intent(hook_input)` to the ledger the callback service
  uses, `adapters/postgres/lanes/hook_tokens.py:127`), `frames = StreamFrameSink` (emits
  `custom.mc.hook_invoked` / `custom.mc.hook_result` through the graph's stream writer, which
  the recorder already maps, `application/frames/kinds.py:94-95`; no new write path),
  `usage = StreamUsageRecorder` (emits `model.usage` custom events for hook-observed usage;
  the first production `UsageRecorder`). The ports are per-deployment and scope-aware through
  the `HookInput` they receive (`adapters/deep_agents/hooks.py:392`).
- `materializer._hook_dispatcher` (`:441-449`) fills `HookContext.native_session_ref`
  (the namespace), `workspace_root`, and `callback = HookCallbackEndpoint(url, token_path)`
  minted through `HookCallbackService` at `prepare`, the way `cursor_local` does
  (`deployment_composition.py:805-818,859`), so a catalog hook script on this lane can write
  a frame or an intent and never a table. `HookCallbackService` gains a `deep_agents` mapper
  (the hook input is already `mc.hook_input.v1`; the mapper is the identity plus the lane's
  context index).
- Finished part: `adapters/deep_agents/hooks.py` (ports) and the composition lines, proven by
  `tests/unit/deep_agents/test_hook_middleware.py` (real ports over in-memory repositories)
  and FX-TR-HOOK.

#### P3.6 Deep Agents: subagents as steps (TR-G5, TR-D5)

- `adapters/deep_agents/frames.py`: a `task` tool call start (`updates.ai_tool_call` with
  `name == "task"`) also yields `subagent_started` (`raw_kind = "subagent.started"`, body:
  child name, description, tool call id; `subordinate_ref` from the child's namespace once it
  appears); the matching tool message yields `subagent_ended` (closing; status, result digest,
  usage summed from the child's `message` frames). `observe_checkpoint` (`:184-202`) records
  nested-namespace checkpoints too, keyed by `(ns, checkpoint_id)` with the pending frame keys of
  that namespace, instead of returning on `ns`.
- `adapters/deep_agents/cognition_points.py::collect_points` walks, for every `tools:<id>`
  namespace the recorder observed in the attempt, that namespace's checkpoints
  (`alist` with `checkpoint_ns` set, one query, bounded by the recorder's observed ids) and
  yields points with `subordinate_ref`, `parent_point_id` = the root checkpoint of the step
  whose frames hold the `task` call, roles `subagent_root` on the child's first checkpoint.
  `CheckpointPoint.root_only` becomes "root or nested with a subordinate ref"
  (`domain/execution/cognition_points.py`).
- Async children (`AsyncSubAgentMiddleware`, `adapters/deep_agents/async_subagents.py`): the
  spawn and the admit emit `subagent_started/ended` custom events with the child execution id;
  the child's own steps stay `lifecycle_only` (§P6.4) until the server exposes them.
- The reducer derives `subordinate.started/ended` facts from the closing frame (ADR 0040) and
  the lineage graph gets its `visibility` from the points (`full` when child points exist).
- Finished part: `adapters/deep_agents/cognition_points.py` (nested walk) proven by
  `tests/unit/deep_agents/test_cognition_points_collector.py` (real saver, one child) and
  FX-TR-SUB.

#### P3.7 Deep Agents: the environment (TR-G8, TR-D8)

- `ExactDeepAgentMaterializer.prepare` returns the materialization manifest it already builds
  while seeding (`materializer.py:911-931`: paths, bytes, digests, destination state channel
  or sandbox upload; skill mounts; MCP servers connected; model resolved). The adapter records
  it as the `environment_materialized` frame right after `recorder.begin` (`adapter.py:271-277`)
  and copies its digest into the input point's `channel_facts.materialization_digest`.
- `state-as-of` on a sandbox backend lists the manifest's uploaded files beside the `files`
  channel with `source: sandbox_upload` (digests, no contents), which closes the fixture
  blind spot the brief found (`tests/acceptance/mission_control/test_cognition_points.py:293-297`).
- Finished part: `adapters/deep_agents/materializer.py::MaterializationManifest`, proven by
  `tests/unit/deep_agents/test_materializer_children.py` (manifest digest stable across two
  prepares of the same binding) and FX-TR-STEP (environment question).

#### P3.8 General: lifecycle writers (TR-G9)

- `released_by` and `continues_from` on the Stage Graph proposal
  (`domain/programs/contracts.py` `StageOperationProposal`; built in
  `domain/programs/interpreter.py` beside `frozen_input_bindings`, `:1180-1191`, and in
  `apply_stage_invalidation`, `:585-635`); the Goal Directed `released_by` on the role
  proposal (`application/programs/goal_directed.py:493-511`). Pure domain changes with golden
  updates (`tests/golden/manifests`).
- `adapters/postgres/orchestration/completion_repository.py` (new): `record_decision` and
  `record_candidate` with `ON CONFLICT (…, decision_key) DO NOTHING`, called inside the family
  transaction by `result_decided` (Stage Graph) and `apply_verification` (Goal Directed)
  through a new `CompletionRecordPort` on `ProgramService`. Dispositions map
  `completion_validation` and the verifier decision onto the table's
  `accepted | rejected | needs_more_work | abandoned` (`M/0003:409-432`).
- `record_rollover`: `domain/policies/reducer.py` gains the action kind `record_rollover`
  (no phase change, one event `workflow_run.record_rollover`, permission `workflow_run.control`
  for the family writer); `adapters/temporal/workflows/goal_directed.py` executes the
  existing boundary lifecycle activity with that action before each `continue_as_new`
  (`:405-407,420-422,605-607`), command id `goal:{run}:epoch:{e}:segment:{s}:rollover`.
  Idempotent through the command receipt.
- `rollover_start` and `cycle_start` parents: `PostgresCognitionPointRepository.record`
  resolves the lineage root's parent by locator in the run today; when none exists and the
  unit's location says cycle > 0 (Stage Graph) or session generation > 1 (Goal Directed), it
  looks up the latest result point of the prior cycle or generation of the same node or role
  and writes `parent_coordinate` with the role. Deterministic from the location alone.
- Finished part: `adapters/postgres/orchestration/completion_repository.py`, proven by
  `tests/unit/orchestration/test_stagegraph_v2.py` (released_by and continues_from on the
  proposals) and FX-TR-STEP (lifecycle question).

#### P3.9 General: the Transcript projection (TR-D10)

- `adapters/temporal/activities/transcript_projection.py::TranscriptProjectionActivities`
  is registered on the maintenance worker beside `FramesExpire`
  (`bootstrap/worker.py:550-556`). It is triggered at every settlement: the settlement path
  enqueues a `transcript.project` request for the run through the outbox (the existing
  outbox-released pattern of ADR 0004), so the projection is seconds behind the settlement;
  `POST runs/{id}/transcript/refresh` projects on demand (the route exists for search,
  `interfaces/http/transcript.py:322`). No schedule (owner, 2026-10-21). The projection
  advances `transcript_projection_state.projected_through_seq` and the last frame cursor, so
  a repeated trigger is idempotent.
- `adapters/postgres/frames/transcript_entries.py` (new) replaces a run's rows under the
  advisory lock pattern of `transcript_projection.py:43-80`; the materializer is the existing
  `merge` (`application/frames/transcript.py:414-466`) extended with the v2 fields and the
  by-unit-and-point placement.
- `GET runs/{id}/transcript` serves from the table when the run's projection is current
  (projected through the latest `seq` and frame cursor), else from the on-demand view; live
  tails stay on the view and SSE.
- Finished part: `application/frames/transcript.py` (v2 entries) proven by
  `tests/unit/frames/test_transcript.py` and FX-TR-STEP.

### P4 Read model

#### P4.1 `mc.transcript_entry.v2` (additive over v1, `domain/frames/transcript.py:70-89`)

```json
{
  "schema_version": "mc.transcript_entry.v2",
  "cursor": "tc1:000000000217:00001761040112345678:000000000041:9f3c1a2b",
  "entry_seq": 318,
  "run_id": "…", "unit_key": "bl-unit-v1:…", "activation_id": "…", "attempt_no": 1,
  "node_key": "S2", "cycle": 2, "iteration": 0, "session_generation": null,
  "point_id": "…", "parent_point_id": "…", "subordinate_ref": null,
  "reused_from": null,
  "at": "2026-10-21T14:08:32.123456Z",
  "source": "provider_frame", "kind": "model_request", "role": "mission_control",
  "title": "model request: gpt-6-sol, step 7, 23 messages, 6 tools",
  "body_excerpt": "{…first 2048 chars…}",
  "body": {"state": "artifact", "bytes": 48213, "media_type": "application/json",
           "artifact_ref": "frame-body://sha256:…?bytes=48213&type=application/json"},
  "execution": {"harness_execution_id": "…", "generation": 1, "arrival_ordinal": 41,
                "temporal": {"workflow_id": "…", "run_id": "…", "activity_id": "…", "attempt": 1}},
  "refs": {"frame_id": "…", "native_event_ref": "provider_frame:…", "body_digest": "sha256:…",
           "tool_call_ref": null, "command_id": null, "human_task_id": null, "event_id": null},
  "usage": null, "canonical": false
}
```

`body.state` is one of `inline` (whole body in the excerpt), `excerpt` (capped, no artifact),
`artifact` (full body resolvable), `expired` (delta frame expired), `pruned` (TR-D17).

#### P4.2 Commands and routes

| Surface | Returns |
| --- | --- |
| `missionctl run transcript RUN [--by step\|turn\|attempt\|stage\|iteration\|mission] [--point ID] [--unit KEY] [--full]` → `GET runs/{id}/transcript?by=&point=&unit=&full=` | entries grouped at the level asked: `--by step` emits one group per point with its frames (`model_request`, `message`, tool calls, hooks, subagent frames) and the lifecycle events joined to that unit; `--by stage` emits one group per unit with its released-by, decision and cycle facts; `--full` resolves `body.artifact_ref` through the reader |
| `GET runs/{id}/points/{pid}/frames` | the frames in the point's range, same entry contract |
| `GET runs/{id}/points/{pid}/transcript` | the step group of one point (the `--by step --point` shortcut) |
| `GET runs/{id}/artifacts/{ref}` (`workflow.result.read`) | the bytes of a `frame-body://` or `artifact://` reference, streamed, 4 MB cap, digest verified; `missionctl run artifact RUN REF --out FILE` |
| `missionctl run replay RUN --point ID --dry-run` → `GET runs/{id}/points/{pid}/replay` | §P4.3 |
| `missionctl run points RUN --reconcile` → `POST runs/{id}/points:reconcile` | §P3.1 |
| Socket.IO `provider_frame` | payload gains `after_point_ref` (the last root checkpoint the recorder had seen when the frame was observed) and `lane_profile`; `lineage` notices gain `child_point_refs` when child points exist |
| `state-as-of` | gains `files[].source` (`state_channel` or `sandbox_upload`), `materialization_digest`, and `withheld` (§P6, §P8a) |

#### P4.3 Replay (TR-D11)

`replay --dry-run` reconstructs the model input of the step at point P from the Transcript
alone: the `model_request` frame(s) of the point's frame range give the ordered message ids
and digests, the system digest and the tool schema digests; each id resolves to a frame body
(AI and tool messages) or a promoted object (human and system messages); the reconstruction
is serialized the way `_execute_model_sync` sends it (`langchain/agents/factory.py:1415-1419`)
and its digest compared with the promoted batch digest. Output: the batch, the digests, and
`exact: true | false` with the first differing message. With `--model NAME` (later decision)
the batch is sent once outside any mission and the comparison stored as an inspection
artifact, never as a run artifact.

#### P4.4 The worked example (the §1 mission, Stage 2 cycle 2, step 7)

```text
mission  m-trudx            run r-01 (Stage Graph, 4 stages, S2 cycled twice)
 run     r-01               events 1..612; units 7 (S1@c0, S2@c0, S2@c1, S2@c2, S3@c0, S3@c1*, S4@c0)
 stage   S2 cycle 2         unit bl-unit-v1:7c…; released_by S1@c0 (draft-ready, stage-result:…:admit);
                            continues_from S2@c1 (result point p-9a…); decision: accepted, completion_decision d-…
 attempt S2@c2 attempt 1    temporal wf mc:…:r-01 run 3f…, activity op-exec-…, task queue mc-deep-agents-ops;
                            environment: 14 files materialized (manifest sha256:4b…, 2 sandbox uploads)
 turn    turn 1             points 0..12; usage 18 431 in / 2 902 out
 step    point p-c4… (step 7, loop)    parent p-b2…; frames 39..47; files_digest sha256:91…
   39 model_request   gpt-6-sol, 23 messages, 6 tools, system sha256:aa…, body artifact 48 KiB
   40 message_delta ×n (expired after 30 days)
   41 message         ai: tool_call task(researcher, "rank the 40 candidates…")
   42 subagent_started researcher (tools:call_7f…)        ┐ child points p-c4…/0..4 under p-c4…
   43..45 message/tool_call_* with subordinate_ref=researcher ┘ (child's model_request frames included)
   46 subagent_ended   researcher, result sha256:…, usage 6 102 / 811 (closing)
   47 tool_call_completed task → body artifact 31 KiB
   event 217 tool_call.completed{status: completed} unit S2@c2 point p-c4…
 frame   47              tc1:000000000217:…:000000000047:9f3c1a2b
```

`*` S3@c1 exists because S2's cycle invalidated S3 and S4 (`interpreter.py:556`).

### P5 The precise fork (TR-G13, TR-G14, TR-D12..14)

#### P5.1 The request

`mc.runtime_fork.v1` (`contracts/runtime_contracts.py:18-41`) gains, additively:

```yaml
at: {stage: S2, cycle: 2}            # or {iteration: 3, session_generation: 1}
cognitive_seed: {unit_key: …, checkpoint: {thread_id, checkpoint_ns: "", checkpoint_id}}   # exists
message: {text: "…"} | {content_ref: …}  # one field; `instruction` stays as a deprecated alias
frontier_policy: close | strict       # default close
```

`missionctl run fork RUN --at stage:S2,cycle:2 --point ID --inject msg.json` fills `at`,
`cognitive_seed` (the point's unit key and key, looked up) and `message`. `--at` is derived
from the point when omitted. Delivery is decided by the seed (owner, 2026-10-21): with
`cognitive_seed` the message becomes the seed head's last human message (§P5.3); without a
seed it is queued to the derived mailbox as today. The receipt records `message_delivery:
seed_head | mailbox`.

#### P5.2 Frontier closure (TR-D12)

`SemanticForkService.prepare` (`application/recovery/run_forks.py:941-1009`) reads the source
blueprint through `ForkSourceReader` (it already carries `blueprint_digest`,
`run_forks.py:156-160`; the blueprint itself is read from the run's family input the way
`RunLaunchService` reads it) and computes `closure = frontier ∪ descendants(frontier)` with a
pure `stage_descendants(blueprint, stage_ids)` lifted from `interpreter._descendants`
(`domain/programs/interpreter.py:1225-1240`) into `domain/programs/dependencies.py`. For a
seeded fork the frontier starts as `{at.stage}`. With `frontier_policy: close` the closed set
is used and recorded; with `strict`, a caller-supplied frontier narrower than its closure is
refused `frontier_not_closed` naming the missing stages. `compute_reuse_decisions`
(`domain/policies/forks.py:576-627`) is unchanged except for Goal Directed (§P5.4). The
receipt (`_record_receipt`, `run_forks.py:494-522`) gains `frontier_requested`,
`frontier_closed`, `reused_units[{unit_key, source_result_point}]`, `seed_point`,
`start_position`.

The run-time safety net stays: `incompatible_restore` (`run_forks.py:1597-1603`) still fails a
reused unit whose packet digest drifted, but with closure it no longer fires for the owner's
scenario.

#### P5.3 Family position carry (TR-D13)

- `StageGraphRunInput` (`domain/programs/contracts.py:1003-1043`) gains
  `start_position: StageGraphStartPosition | None` with `workflow_cycle_ordinal`,
  `stage_cycle_ordinals: {stage_id: n}`, `stage_objectives: {stage_id: text}` (the cycle's
  `next_objective` from the source's `cycle_decided` proposal, so the seeded unit's
  `objective_override` segment is reproducible, `service.py:1510-1523`).
- `interpreter.initial_projection(identity, run_version, start=…)` (`:95-130`) starts the
  candidates of stage S at `stage_cycle_ordinals.get(S, 0)` and the projection at the given
  workflow cycle. `stagegraph.initialize` still runs (the continue-as-new `initial_projection`
  path is not reused; the agent's assessment stands: it would skip the family head).
- `RunLaunchService._apply_fork` (`application/execution/run_launch.py:373-408`) fills
  `start_position` from the fork receipt: for every invalidated unit of the `at` stage, the
  maximum `stage_cycle_ordinal` among the units that were invalidated at or above the seed
  (so S2 starts at cycle 2, S3 and S4 at 0), and the snapshot's `FamilyPosition.workflow_cycle_ordinal`
  (`forks.py:145`, its first reader).
- With that, `derived_unit_identity` (`forks.py:525-530`) already yields the seeded unit's
  key (same location, new run and epoch), the namespace `seed_fork` restored into is the one
  the derived S2 cycle 2 unit addresses (`domain/execution/checkpoint_lineage.py:138-139`),
  and `cognitive_seed.py:132-141` needs no change. S2 cycles 0 and 1 are never admitted in the
  derived run; S1 is reused by ref; S3 and S4 run fresh.
- The injected message: `ForkSeedRequest.message` (declared, never read,
  `application/execution/harness/time_travel.py:48-50`) is finally honoured by `seed_fork`
  (`adapters/deep_agents/time_travel.py:153-254`): after the copy, one `aput` of a new root
  checkpoint on the derived thread whose `messages` write is the injected `HumanMessage`,
  stamped with the derived unit's metadata, becomes the seeded head (role `fork_seed`,
  `source: fork`). The derived unit's first attempt classifies `not_submitted` with that head
  as `expected_source` and its first model call sees the copied conversation plus the message
  as the last human message, exactly as the bar in brief §0 states. The mailbox path is not
  used for a seeded fork, so no other unit can claim the message.

#### P5.4 Goal Directed (TR-D14)

Both options were costed (E3 assessment, §A.2):

| Option | Touches | Risk |
| --- | --- | --- |
| A. Run-independent revision identity | `service.py:1854-1862` minting (five lines) plus every consumer of `goal_revision_id` and the revision and handoff digests (`contracts.py:1120-1139,1217`; `goal_directed.py:60-70,558`; the documents' identities; every Goal fixture and golden) | changes canonical digests of every Goal run; the generation-1 namespace is role-and-session based (`checkpoint_lineage.py:143-144`), so equal unit keys across runs still land on different threads and nothing is gained for the seed |
| B. Reuse by iteration | `compute_reuse_decisions` (`forks.py:616-620`): a Goal Directed candidate with `goal_iteration < at.iteration` (and the verifier of `at.iteration - 1`) is `reuse` under a derived identity that substitutes run, epoch and `goal_revision_id` (minted for the derived run by the same function); `derived_unit_identity` gains the substitution; `decision_is_exact` (`:568-572`) compares after substitution; `GoalDirectedRunInput.start_position {goal_iteration, session_generation, agent_run}` honoured by `initial_state` (`goal_directed.py:109-123`); `run_launch` fills it | contained in the fork policy and the start path; the packet compatibility digest is run-relative only through `{run_id}` (`run_forks.py:1478-1496`), so reused iterations pass the check |

**Recommendation: B.** The derived run starts at iteration N with the executor thread seeded
at P plus the injected message; iterations 1..N-1 settle by ref with `reused` points; the
verifier of N-1 is reused too, so the handoff into N is the source's.

#### P5.5 Provenance (`reused_from`)

`_settle_reused` (`operation_execution.py:2273-2299`) also records one point per reused unit:
`roles = (reused,)`, `source = fork`, `parent_coordinate` = the source unit's result point,
`point_ref` = the source result key, `written_by = fork_seed`. The derived Transcript shows the
unit as `reused_from: <source point>` at the stage level and the derived `run points` lists
it; nothing of the source's cognition is copied.

#### P5.6 Worked example, Stage Graph

```text
source r-01: S1@c0 ✓  S2@c0 ✓ S2@c1 ✓ S2@c2 ✓(P = step 7)  S3@c1 ✓ S4@c1 ✓
fork --at stage:S2,cycle:2 --point P --inject "Prefer companies with CLIA labs"
  frontier_requested {S2} → frontier_closed {S2, S3, S4}
  reuse: S1@c0 reuse (source point p-S1-result)      invalidated: S2@c0, S2@c1, S2@c2, S3@c1, S4@c1
  start_position: {workflow_cycle_ordinal: 0, stage_cycle_ordinals: {S2: 2}, stage_objectives: {S2: "…cycle 2 objective…"}}
  seed: thread belllabs/stage/<derived S2@c2 unit>/gen/1 ← copy of source lineage to P + head H(messages += human "Prefer…")
derived r-02: admits S1@c0 → settles by ref (point reused ← p-S1-result)
              admits S2@c2 → first attempt: expected_source H; first model_request lists …, "Prefer…" last
              S2 settles → S3@c0, S4@c0 run fresh (released_by S2@c2 of r-02)
transcript r-02 --by stage: S1 reused_from r-01/p-S1-result; S2 cycle 2 fork_seed parent_coordinate r-01/P
```

#### P5.7 Worked example, Goal Directed

```text
source g-01: iterations 1..5 (executor/verifier on session 1 threads)
fork --at iteration:3 --point P (executor, iteration 3, step 9) --inject "Stop after one more revision"
  reuse: executor@1, verifier@1, executor@2, verifier@2 reuse (derived revision id substituted)
  invalidated: executor@3.., verifier@3..
  start_position: {goal_iteration: 3, session_generation: 1, agent_run: 5}
  seed: thread belllabs/goal/g-02/epoch/1/session/1/role/executor ← copy to P + head H(+ human message)
derived g-02: iterations 1, 2 settle by ref (points reused); iteration 3 executor pins to H; verifier 3 runs
```

### P6 The remote saver (TR-G15, TR-D15)

#### P6.1 Every call site, with its cost and its typed outcome

The saver is one `AsyncConnection` per process, every operation serialized by an
`asyncio.Lock`, no pool and no timeouts on the conninfo (`adapters/deep_agents/persistence.py:118-175`;
installed `langgraph/checkpoint/postgres/aio.py:81-83,374`). `aget_tuple` and `alist` are one
query each; `aget_delta_channel_history` at least two; `aput` one pipelined batch.

| Site | When | Round trips today | Outcome when the saver is slow or unreachable |
| --- | --- | --- | --- |
| `_classify` (`adapter.py:924-1017`, also `observe_latest :517`, failure path `:1113-1150`) | activity start | 1 `aget_tuple` + 1 **unbounded** `alist` over the thread + 1 `aget_state` | activity fails before cognition: `RuntimeInvocationFailure(saver_unreachable)`, retryable; **change**: bound the `alist` with `limit` and `before` (the lineage walk needs only the suffix after the expected source) |
| heartbeat reader (`adapter.py:284,1152-1171`) | every heartbeat | 1 `aget_tuple` | heartbeat carries `checkpoint_read: stale` instead of failing the attempt |
| the graph run (`_invoke :763-800`, `durability="sync"`) | each super-step | 1 `aput` + 1 `aput_writes` | LangGraph raises; the attempt fails `saver_write_failed`, retryable; the frames already written stay (the Transcript is not affected) |
| `_own_result_config` + `aget_state` (`:1052-1092,319-321`) | after cognition | 1 unbounded `alist` + ≥3 | **change**: bound as above |
| `_capture_result` (`:1238-1300`) | after cognition | N `aget_tuple` | `capture_incomplete`: the attempt fails after cognition, retried; the classifier reconstructs from the stamped leaf (`TERMINAL_UNOBSERVED`) |
| `collect_points` (`cognition_points.py:51-157`) | before settlement | ~3N+ (per checkpoint `aget_tuple` + delta history) | **change**: one `alist` for the lineage, delta history once for the result and folded backwards (the fold is pure), under a budget (`points_walk_budget_ms`, default 5 000, lane option); on exhaustion the settlement proceeds with the points collected and `unit_result_observation.points_status = incomplete`; the reconciler clears it (`points_incomplete` is a typed outcome on `run inspect`) |
| `is_stamped_descendant` (`checkpoint_verifier.py:36-77`) | reconciliation | ≤ `MAX_LINEAGE_WALK` `aget_tuple` | `reconcile` reports `saver_unreachable` for the unit, never `in_doubt` by itself |
| `list_root_checkpoints`, `read_redacted_state` (`checkpoint_history.py:65-131`) | API reads | 1 `alist(limit=2001)`; 1 + ≥2 | `503 state_unavailable{reason: saver_unreachable, saver: <digest>}`; the Transcript and points routes answer |
| `read_as_of` (`time_travel.py:71-151`) | `state-as-of` | 1 + ≥2 | `503 state_unavailable` with the point's `restore_level` and a `withheld` block naming what the Transcript still answers |
| `seed_fork` (`time_travel.py:153-254`, on the API process) | fork | M `aget_tuple` + M (`aput` + `aput_writes`) | the fork saga refuses `cognitive_seed_unavailable{saver_unreachable}` before admitting the derived run; **change**: run the copy inside the saga's materialize step on a worker activity (idempotent, `:196-198`) rather than on the API request thread, with a budget and `copy_incomplete` as a retryable outcome |

#### P6.2 Naming the saver on every point

`checkpointer_ref_digest` is a catalog definition digest (`ExactDefinitionRef.digest`,
`checkpoint_lineage.py:1389`; `domain/authoring/contracts.py:113-120`), resolved by lookup in
`pins.checkpointers` (`deployment_composition.py:434`; `api.py:317`). It does not change with
the DSN. Proposal: the pinned checkpointer definition gains a `locator_digest =
sha256(host, port, dbname, schema)` computed at composition from the bound conninfo (never the
DSN itself), stored on `PinnedPersistence` and on every `QualifiedCheckpointKey` as
`saver_locator_digest`; `read_as_of`, `seed_fork` and the reconciler refuse a point whose
locator digest no saver in the registry serves (`saver_not_served`). Moving the saver is then
a new pin revision, and old points name the old location honestly.

#### P6.3 What moves, and what the Transcript guarantees

After TR-2 the Transcript holds every input (`model_request`, promoted bodies, packet),
every output (frames), the environment manifest and the lifecycle facts in Mission Control's
own tables and payload store. The saver holds the native lineage needed for R3 reads and R3
forks. If the remote saver is purged, `state-as-of` degrades to the Transcript's
reconstruction (`restore_level: R2`, `withheld.reason: saver_purged`) and a fork at that point
is refused `point_pruned` with the nearest seedable point (the TR-D17 outcomes). Nothing the
owner reads depends on the saver being alive.

#### P6.4 Agent Server topology (TR-D15, R5)

Today the server is `langgraph dev` in the in-memory edition (pickle files); the Postgres
edition is a separate, uninstalled package whose tables share names with the standalone saver
and cannot be confined to a schema (`AGENT_SERVER_TOPOLOGY.md:3-36`). Recommendation: keep
ADR 0017's position, two databases on the same remote server when the server moves to the
Postgres edition (the parent saver in `mission_control_runtime` of the runtime database; the
Agent Server in its own database), never a shared schema; read async-child state through the
server's API (`threads.get_state`, `threads.get_history` on the child's `native_thread_ref`,
which `subordinate_execution` records) and write child points as `lifecycle_only` entries
with the server thread ref until that read is built. The server's thread TTL is enabled only
after TR-2 closes TR-G1 and TR-G2.

### P7 Agent-side writes (TR-D9)

Nothing in this proposal makes a working agent responsible for a table write. Two agent-facing
surfaces are reserved, both single idempotent calls the harness completes:

- **Submission** belongs to the queued output-contracts session (TR-G11). Its shape is fixed
  here so the Transcript can carry it: the agent's declared outputs arrive as a `run_result`
  frame body (the Deep Agents result) and as the settlement's output payload; the reducer, not
  the agent, writes `completion_candidate` from them (§P3.8). The agent never names a point;
  the harness stamps the result point on the settlement.
- **`progress_note`** (optional): a Deep Agents tool `progress_note(note: str, tags: [str])`
  materialized by the lane adapter when `provider_options.deep_agents.progress_notes: true`.
  It emits one custom stream event `mc.progress_note` that the recorder turns into a
  `progress_note` frame keyed `deep_agents_key(thread, ns, None, step, f"note:{n}", "progress_note")`,
  so it is idempotent by provider key, carries the step (and so the point) from the harness,
  and is visible in the Transcript, the stream and `--by step`. It writes no table and returns
  the frame's provider key to the agent. Recommendation: reserve the frame kind now (§P2),
  build the tool in the queued session with the submission surface.

### P8a Retention and degradation (outline; completed by the pruning session, TR-D17)

Reserved here so the schema does not change twice:

| Class | What | Clock | Prune action |
| --- | --- | --- | --- |
| delta | `message_delta`, `thinking_delta`, `tool_call_delta`, `heartbeat`, `status` frames | `retain_days` (30) | delete (today's function, narrowed to the class) |
| step | every other frame, their promoted bodies, `model_request` | mission evidence life (`step_retain_days` NULL); when set, only terminal runs, never pinned points | `tombstone` mode (TR-D17): the frame row stays, the body object is removed, `body_state: pruned` |
| ledger | events, points, settlements, journal, documents, candidates, decisions | never | bodies move cold; rows stay |
| saver | native lineage | server or saver TTL, introduced after TR-2 | `restore_level` lowered in place on the points (`R3 → R2 → R1 → R0`), `pruned_at`, `prune_policy` recorded |

Pins (a derived run's live fork seed, an evidence or evaluation hold, a pending human task) and
the typed outcomes (`withheld` on `state-as-of`, `point_pruned` on fork, `pruned` entries in
sequence, the reconciler's `pruned` versus `missing`) are specified in TR-D17 and built later;
this proposal only reserves `cognition_point.restore_level`, `pruned_at`, `prune_policy`,
`frame_retention_policy.step_retain_days`, `prune_mode`, and the `body_state` vocabulary.

### P8 Determinism and reconciliation

| Writer | Idempotency key | Crash between writes leaves | Repair |
| --- | --- | --- | --- |
| mission events (reducer, `append_events`) | command receipt `(run_key, issuer, command_key)`; `seq` from the ledger commit | nothing partial (one transaction) | replay returns the stored receipt |
| family journal, head, admission result | `(run_key, family_kind, mutation_key)` | nothing partial | pre-check by `mutation_key` |
| `completion_decision`, `completion_candidate` | `decision_key = mutation_id`; `candidate_key = settlement_id` | nothing partial (family transaction) | ON CONFLICT DO NOTHING |
| `runtime_document` (`goal.*`, `operation.binding/1`) | `(contract, identity)` | a document without its admission (harmless: re-admission re-reads it) | digest-compared re-put |
| `context_selection` | `selection_key` | a packet without its admission | re-pack compares `packet_digest` |
| `activation`, `attempt`, `activity_attempt_observation` | `activation_key`; attempt observation key | nothing partial | ON CONFLICT DO NOTHING |
| frames | `(harness_execution_id, generation, provider_key)`; arrival ordinal | frames of a step whose checkpoint never landed (the attempt retries: duplicates are counted, not stored) | none needed; the reconciler's frame ranges use provider keys |
| promoted bodies | content digest | an object without a frame (orphan, harmless) | a sweep lists orphans; never deleted by the runtime |
| `environment_materialized`, `model_request`, `subagent_*`, hook frames | provider keys above | same as frames | same |
| transition + result + points | transition id; point id `uuid5(scope, unit_key, generation, kind, locator)` | **nothing partial** (one transaction, §P3.1) | the reconciler re-derives points for a transition whose rows are short |
| `operation_settlement`, receipt | settlement id | a transition without a settlement (today's known window) | existing unit reconciliation (`unit_reconciliation.py`) |
| `session_turn.point_ref`, `agent_session.checkpoint_*` | immutable row on `turn_ended`; `COALESCE` on `run_result` | a turn without its point ref | the reconciler fills `point_ref` from the result point |
| `mission_run.temporal_*` | run id, equal values | NULL | re-launch path refuses a different run id; `run inspect` shows NULL honestly |
| `workflow_run.record_rollover` | command id per segment | a segment without its event (the activity failed before continue-as-new; Temporal retries the activity) | the event is re-issued on retry with the same command id |
| `cycle_start`, `rollover_start` parents | derived from the location at write time | a point without its cross-cycle parent (prior result point not yet settled: impossible in order, possible after a crash) | the reconciler recomputes parents for points whose `parent_point_id` and `parent_coordinate` are both NULL and whose location is not the first cycle or generation |
| fork receipt, `reused` points, seed head | fork request id; point ids | a derived run admitted without its seed (the saga's materialize step failed) | the fork saga's existing `fork_not_materialized` retry (`operation_activities.py:186-212`) covers the seed too |
| Transcript projection | `(run_id, cursor)` replaced per run under the advisory lock | a half-projected run | `projected_through_seq` drives the next refresh; readers fall back to the view when the state is behind |

### P9 Proof plan (T0, scripted cognition, real Postgres 17 and local Temporal)

Fixture work first: the four-stage Stage Graph blueprint (`S1 → S2 → {S3, S4}`) with a
`StageCyclePolicy(max_cycles=3)` on S2 and a scripted stage result that returns
`evaluation: cycle` for S2 twice (`domain/programs/contracts.py:791`; today's
`stage_blueprint` has two stages and no cycle policy, `tests/fixtures/rrm009_production_stack.py:163-215`);
the scripted `TechnicalModel` already spawns one sync child, writes a file and calls one MCP
tool per turn (`:793-860`); a catalog hook script fixture that allows and annotates one tool
call; the stack's `langgraph_checkpoint_dsn` pointed at a closable pool so "saver stopped"
is `pool.close()` plus a registry whose DSN resolves to a closed port.

| Fixture | Assertions |
| --- | --- |
| **FX-TR-STEP** | for every point of S2 cycle 1 (root and child): the `model_request` frames of its range list ids whose bodies resolve; the `message` and `tool_call_completed` frames resolve `--full` (one tool result over 8 KiB); `environment_materialized` names the seeded files with digests equal to the packet's; the released-by, decision and cycle facts appear in `--by stage`; the derived events carry `activation_id`, `unit_key` and `point_ref`; all read with the saver pool closed |
| **FX-TR-REPLAY** | `replay --dry-run` at a tool-calling step of S2 reproduces the batch digest the live saver's `state-as-of` yields before the pool is closed; `exact: true` |
| **FX-TR-SUB** | the sync child's `subagent_started`, its points (with `subordinate_ref`, `parent_point_id` = the parent's step point), its own `model_request`, and `subagent_ended` with the summed usage appear under the parent step; the lineage notice says `visibility: full` |
| **FX-TR-HOOK** | the catalog hook's `hook_invoked` and `hook_result` frames exist with the kernel hooks' ids first; the `usage` port's frame matches the model observer's counts; the stop fence port refuses a tool call after `cancel --urgency immediate` |
| **FX-TR-RETAIN** | with `retain_days = 0` the expiry run deletes only `delta` frames; every step frame of the run survives; the transcript shows `expired` only on deltas |
| **FX-TR-RECONCILE** | a fault injected between the transition and the points (test-only hook in the repository) leaves the unit `in_doubt` with `points_write_failed`; `run points --reconcile` restores every point and frame range; `written_by = reconciler` |
| **FX-TR-FORK-CYCLE** | fork from S2 cycle 2 at an intermediate point with an injected message: the receipt shows `frontier_closed = {S2, S3, S4}`, `reused_units = [S1@c0]`, `start_position.stage_cycle_ordinals = {S2: 2}`; the derived run settles S1 by ref with a `reused` point naming the source result point; admits no S2 cycle 0 or 1; S2's first `model_request` lists the copied ids and the injected text last; S3 and S4 run with `released_by` naming the derived S2; the derived Transcript's `fork_seed` entry names the source point |
| **FX-TR-FORK-GD** | fork a 5-iteration Goal Loop at iteration 3 (executor, mid-step): iterations 1 and 2 settle by ref (no cognition frames in the derived run); iteration 3's executor starts from the copied thread plus the message; the verifier of 3 runs; the derived run completes |
| **FX-TR-REMOTE** | with the saver DSN pointed at a latency-injecting proxy (`toxiproxy` or a `socat` delay) set above the points budget, settlement yields `points_status: incomplete`; `run inspect` shows `points_incomplete`; `--reconcile` with the proxy removed completes the points; with the proxy closed, `state-as-of` answers `503 state_unavailable` and `run transcript --by step --full` still answers |

The four FX-DA tests (`test_cognition_points.py:172,248,310,439`) stay green.

### P10 Decisions (TR-D1..17)

Asked of the owner in one round; the answers are recorded in this section with their date.
"Changes" says what each answer alters in the plan.

| # | Decision | Recommendation | Changes |
| --- | --- | --- | --- |
| TR-D1 | Retention classes | delta 30 days; step frames for the mission's evidence life; per-application policy with classes (no lane-profile retention field) | a lane field would need a describe migration and a second policy source |
| TR-D2 | Model-input record | the `model_request` frame from a callback at the chat-model boundary (§P3.4), not a middleware | a middleware would miss the prompt-caching tail (§A.3 R1) |
| TR-D2a | What the record holds | **(a)** per-message objects promoted once by digest plus the batch digest on every call (cheap, exact by reconstruction) versus **(b)** the full batch promoted on every call (bytes grow with the square of the turn length). Recommendation: (a) by default, (b) as the `full_requests` capture profile for T0 proofs and investigations | storage cost per turn; the replay test runs under (b) once to prove (a) |
| TR-D3 | Full-body promotion | the light `frame-body://` scheme over the payload store (§P3.3), gated by `workflow.result.read`; governed artifacts stay for submissions | governed artifacts per frame would add a revision row and a durable-reference admit per body |
| TR-D4 | Hook ports | real ports in the deployment composition, the stream-writer sink for frames, the callback endpoint minted at prepare (§P3.5) | none if accepted |
| TR-D5 | Subagents as steps | nested points with `subordinate_ref`; async children `lifecycle_only` until the server read exists | the contract relaxation in `CheckpointPoint` |
| TR-D6 | Points in the settlement transaction, reconciler | yes to both; a write failure is `in_doubt` with an incident, never a log line | none |
| TR-D7 | Joinability | `unit_key`, `activation_id`, `point_ref` on events; `after_point_ref` on stream frames; `point_id` on entries | none |
| TR-D8 | Environment | manifest frame on the input point, `workspace_checkpoint_ref` from the candidates on the result point, no per-step sandbox snapshot | K11 later |
| TR-D9 | Agent-side writes | none; `progress_note` reserved, built with the submission surface | the tool moves into TR-2 if wanted now |
| TR-D10 | Transcript materialization | the projection table, refreshed at every settlement through the outbox and on demand; the view for live tails | none |
| TR-D11 | Replay | `--dry-run` in TR-3; a paid replay later | none |
| TR-D12 | Frontier closure | `frontier_policy: close` by default (auto-close, recorded); `strict` refuses a narrower frontier | `strict` by default costs one refusal round trip per fork |
| TR-D13 | Family position carry | `start_position` honoured by the interpreter, filled from the receipt | none |
| TR-D14 | Goal Directed fork identity | option B, reuse by iteration (§P5.4) | option A rewrites every Goal digest |
| TR-D15 | Remote saver | locator digest on pins and keys; bounded walks with budgets; the copy on a worker; two databases, never a shared schema; child state through the server API | none |
| TR-D16 | Scope | `deep_agents` first; every general item is lane-neutral by construction (ports, contracts, tables) | none |
| TR-D17 | Pruning by degradation | columns and the `body_state` vocabulary reserved here; the pruning session completes it after TR-2 | none |
| TR-D18 (new) | Stage shape and release | three stages (Part C); Stage 1 as two sessions (1A write side, 1B read side and fork) over work packages WP-TR-1..5, one allowed; one release 1.4.4 cut first carrying every migration so the rest is code-only | one session makes a longer proof run and a larger diff for Stage 3; a release per package costs a build and lock change each time |
| TR-D19 (new) | Spend | T0 only for every FX-TR proof; no model named | a paid replay (TR-D11) would need a model and a ceiling |

**Answers recorded 2026-10-21 (owner):**

- **TR-D18: accepted, then reshaped the same day.** First answer: five sequential sessions
  with one release 1.4.4 cut first. Second answer (later on 2026-10-21): three stages instead
  (Part C): (1) implementation and minimal verification, split into tasks as the session sees
  fit, with Fable 5.1 free to spawn subagents (the proposal recommends two sessions, 1A write
  side and 1B read side and fork; one session is allowed); (2) real fixtures on a 10 USD
  cognition budget, fixing what they expose; (3) adversarial review, clean code, tests and the
  documentation pass. The five work packages keep their content and order inside Stage 1; one
  release 1.4.4 is still cut first.
- **TR-D2a: (a) by default, (b) as a profile.** The owner's words: "We will make this a
  system lever so coordinator agents won't choose this. I will mostly use a. I just want us to
  start setting up extension points because we might want different 'transcript trace'
  storage behavior so we can start supporting the variation." Disposition: the capture profile
  is a deployment setting (`MISSION_CONTROL_FRAME_CAPTURE_PROFILE`, `standard` by default),
  never a manifest field; `FrameCapturePolicy` and `FrameBodyPromoter` are the two extension
  points (§P3.3); the profile used is recorded on the harness execution.
- **TR-D12: auto-close and record.** `frontier_policy: close` is the default; `strict` stays
  available.
- **TR-D14: reuse by iteration (option B).**
- **Stated assumptions, not asked (the owner may correct them in the TR-1 session):** TR-D1
  (per-application retention classes, no lane field), TR-D3 (the `frame-body://` scheme over
  the payload store, not governed artifacts), TR-D4..D8, TR-D10, TR-D11 (dry-run only),
  TR-D13, TR-D15 (two databases, never a shared schema; child state through the server API),
  TR-D16, TR-D17 (columns reserved only), TR-D9 (`progress_note` reserved, built with the
  submission surface), TR-D19 (T0 only, zero spend).

**Answers recorded 2026-10-21 (owner interview before Stage 1; all accepted, nothing left open):**

- **Stage 1 shape:** the owner runs all five work packages in **one session** (Fable 5.1,
  subagents at the session's discretion). The two-session recommendation in §C.1 stays as the
  internal order: 1A's packages before 1B's.
- **TR-D1 retention columns:** as proposed. `retain_days` governs the delta class,
  `step_retain_days` (nullable, NULL = the mission's evidence life) governs step frames,
  `prune_mode` is reserved. Per application; no lane field.
- **TR-D3 frame bodies:** the light scheme `frame-body://sha256:<hex>?bytes=<n>&type=<media>`
  over the content-addressed payload store, read under `workflow.result.read`; no
  `artifact_metadata_revision` row; 0049 documents the scheme.
- **Decision table:** reuse the existing `completion_candidate` and `completion_decision`
  (`M/0003:381-432`); unused columns stay NULL. The owner's perspective, recorded verbatim in
  substance: these tables predate the output-contract, verification and acceptance design and
  the context-transfer and materialization work, which belong to the queued
  output-contracts and context-transfer session; Stage 1 does the best it can with them and
  accepts that improvements come in that session.
- **TR-D10 projection freshness:** refreshed at every settlement (the settlement path
  enqueues the run's projection through the outbox; seconds behind) and on demand through
  `POST runs/{id}/transcript/refresh`; the live tail stays on the view; no schedule. Table
  names as proposed: `mission_control.transcript_entry`, `mission_control.transcript_projection_state`.
- **Fork message:** one field. `mc.runtime_fork.v1` gains `message`; `instruction` stays as
  a deprecated alias. With `cognitive_seed` the message becomes the seed head's last human
  message; without a seed it is queued to the mailbox as today. One CLI flag `--inject FILE`.
  The receipt names the delivery that happened (`seed_head` or `mailbox`).
- **Commit cadence:** commit after each work package on the sprint branch (release 1.4.4
  first), no push and no merge until the owner says so.
- **Consideration to keep in mind (owner):** Deep Agents is unlikely to be used for code
  work over Claude Code, Cursor or Codex, but it is not forbidden (it is an agent-skill,
  environment and MCP-server matter, and Deep Agents has its own CLI for code work). Nothing
  in Stage 1 may assume the lane never edits code: the environment manifest, the workspace
  checkpoint ref and the promoted tool results must hold for file-editing tools too.

### P11 Honest list

- **Not in this proposal:** the per-step sandbox snapshot (K11), K05 cycle deliveries and K04
  verifier findings (queued session), the submission check and output contracts (TR-G11), the
  `progress_note` tool itself, the pruning session's pins and outcomes (TR-D17), the Agent
  Server's move to the Postgres edition and the child-state read through its API, other lanes'
  `model_request` observers, the mid-iteration continuation hydrator (K03), the Linear issues
  (`PC-deep_agents-NN`, created per task at build time).
- **Unverified until build:** that `invocation_params` on `on_chat_model_start` carries the
  bound tools for both chat model classes (verified by the first unit test of TR-2); the
  nullability of `completion_decision.candidate_id` and the existing grants on the completion
  tables (`M/0003:381-432`, read at build); whether `deepagents 0.7.19`'s multimodal-filter
  middleware changes anything a callback sees (it cannot: the callback is after every
  middleware); the exact Temporal activity the boundary lifecycle command uses for
  `record_rollover` (reuse of `BoundaryLifecycleRequest`, `domain/programs/contracts.py:198-223`).
- **Known limits that stay:** `alist` without a bound in `_classify` and `_own_result_config`
  until TR-5 bounds them; frames placed by time for run-level events; the on-demand view's
  20 000 and 50 000 bounds for runs whose projection is behind; the 4 MB body cap.

## Part C. The three stages (owner, 2026-10-21, second decision of the day)

The owner replaced the five-session sequence with **three stages**: (1) implementation and
minimal verification, (2) real fixtures on a 10 USD cognition budget that prove it works, with
fixes for whatever they expose, (3) adversarial review, clean code, tests and documentation.
The five work packages below keep their content and order but are no longer sessions; they
are the build order inside Stage 1.

### C.1 Stage 1: implementation and minimal verification

**Recommended shape: two sessions, 1A and 1B, each fanning out subagents on independent
module sets.** One session can do the whole of Stage 1; the two-session shape was recommended
because release 1.4.4 must be right before anything consumes it (an applied migration is
never edited), because the nine T0 proofs run serially on this host at 40-100 s each, and
because Stage 3's review needs a diff a reviewer can hold. **Owner's choice (2026-10-21,
interview): one session runs all five work packages**, 1A's before 1B's, committing after
each package on the sprint branch; the per-package commits give Stage 3 its reviewable units.

| Session | Work packages | Parallel streams after the shared step | Minimal verification |
| --- | --- | --- | --- |
| **1A, the write side** | WP-TR-1 (release 1.4.4, settlement transaction, reconciler, joinable events, lifecycle writers, rollover event, reused points) then WP-TR-2 (model-input frames, promoter and capture profiles, hook ports and callback, subagent points, environment manifest, stream `after_point_ref`) | shared step: the three migrations, the release build, the contract changes (`FrameKind`, point roles, `DomainEventEnvelope`, `RuntimeResult`); then stream K (kernel: settlement, reconciler, events, lifecycle writers) beside stream D (Deep Agents: observer, recorder, collector, materializer, hooks) | unit tests per module; `tests/integration/postgres` release proof; FX-TR-RECONCILE, FX-TR-STEP, FX-TR-SUB, FX-TR-HOOK; the four FX-DA proofs green on 1.4.4 |
| **1B, the read side and the fork** | WP-TR-3 (transcript v2, `--by`, frames-by-point, artifact download, replay dry-run, projection activity and table, retention classes and the narrowed expiry, `state-as-of` additions) then WP-TR-4 (closure, start position for both families, the seed head with the injected message, the Goal Directed reuse rule, the receipt, the fork CLI) then WP-TR-5 (locator digest, bounded walks and budgets, `points_incomplete`, the copy on a worker, the typed read and fork outcomes) | shared step: `mc.transcript_entry.v2` and the fork request contract; then stream R (reads, projection, retention, replay) beside stream F (fork and start position) and stream S (saver bounds and outcomes) | FX-TR-RETAIN, FX-TR-REPLAY, FX-TR-FORK-CYCLE, FX-TR-FORK-GD, FX-TR-REMOTE; FX-DA-FORK green |

"Minimal verification" means: ruff, mypy on changed modules, the architecture tests, the unit
suites of the touched packages, and the acceptance proofs named, reported as passed, failed,
blocked and unrun. No live model. Each session still ends with one finished part to read, the
sequence it sits in, and one command with what the owner sees, and records its ledger entry;
the full documentation pass is Stage 3.

### C.2 Stage 2: real fixtures, 10 USD of cognition

The §1 mission scaled to fit the budget, on `deep_agents` with the models the owner names
(turn 3 precedent: GPT-6 Sol as the parent, GPT-6 Luna as the subagent), on T2 (real provider,
local worker, the production offline stack otherwise): a four-stage Stage Graph with one
cycle on S2, one sync subagent, one inject mid-turn, then the fork from S2 cycle 2 with an
injected message and the derived run to completion; a three-iteration Goal Loop and its fork
at iteration 2. Every run records its id, manifest digest, worker commit, receipts digests and
spend in the ledger; reservations are sized so the whole stage stays under 10 USD (the turn 3
live drill consumed 1 935 tokens for one parent turn and one child answer). The proof is the
same assertions as the FX-TR fixtures, read through the public API, plus `replay --dry-run`
at a real tool-calling step and `--full` on a real tool result above the cap. Whatever a real
model exposes (parsing, timing, cost, provider frames the scripted model never emitted) is
fixed in the same stage and recorded as findings.

**Known blocker for the Goal Directed live fixture:** F-T3-1 (`CHANGES.md` turn 3): a real
executor whose final message does not parse as `GoalNamedExecutorObservation` makes
`reconcile_operation` retry without bound. Stage 2 fixes it (a retry classifier case that
settles the operation `failed` with a reason) or binds a structured output before the Goal
Directed run; the Stage Graph fixtures have no such blocker.

### C.3 Stage 3: adversarial review, clean code, tests, documentation

An adversarial review of the Stage 1 and Stage 2 diff (correctness first: the settlement
transaction, idempotency keys of §P8, the closure algorithm, the seed head, the typed
outcomes), then simplification without behaviour change, then the test gaps the review names,
then the documentation: ledger consolidation, the knowledge concepts
(`provider-frames-and-transcript`, `events-and-commands`, `recovery`, `deep-agents-lane`,
`execution`), ADR candidates (the Transcript as the replayable record; retention follows the
mission; agents never write tables; the precise fork with closure and family position), the
operator guide for the new commands and the capture profile setting, `validate_okf.py`,
`agents_docs_index.py`, and the describe matrix flipped from what Stage 2 proved. The queued
output-contracts and context-transfer session follows Stage 3 with TR-G11 first.

### C.4 The work packages (content and order inside Stage 1)

| Work package | Builds | Proves | Finished part to read | Command the owner runs |
| --- | --- | --- | --- | --- |
| **WP-TR-1 Joinable, transactional, lifecycle-complete** | release 1.4.4 (0047, 0048, 0049); points in the settlement transaction; the reconciler; `unit_key`, `activation_id`, `point_ref` on events; `released_by`, `continues_from`, `completion_decision` and `completion_candidate` writers; `record_rollover`; `cycle_start` and `rollover_start` parents; `mission_run.temporal_*`; `reused_from` points on the existing fork path | FX-TR-RECONCILE; FX-TR-STEP (lifecycle, who); FX-DA-* green on 1.4.4 | `application/execution/operations/checkpoint_lineage.py` → `adapters/postgres/operations/checkpoint_lineage.py` → `point_reconciliation.py` | `missionctl run points RUN --reconcile` then `missionctl run transcript RUN --by stage` (released-by and decisions per stage) |
| **WP-TR-2 Capture completeness** | `_ModelRequestObserver` and `model_request` frames; the promoter and `frame-body://` reader; hook ports and the callback on this lane; `subagent_started/ended` and nested points; `environment_materialized` and `workspace_checkpoint_ref`; `after_point_ref` on the stream | FX-TR-STEP (all six questions, saver closed); FX-TR-SUB; FX-TR-HOOK; FX-TR-REPLAY (digest only, via `state-as-of`) | `adapters/deep_agents/adapter.py::_ModelRequestObserver` → `frames.py` → `writer.py` (promoter) → `cognition_points.py` (nested) | `missionctl run transcript RUN --by step --point ID --full` (the model request, the whole tool result, the child's steps under the parent) |
| **WP-TR-3 Read model and retention** | `mc.transcript_entry.v2`; `--by`; frames-by-point; artifact download; `replay --dry-run`; the projection activity and table; the retention classes and the narrowed expiry; `state-as-of` with `withheld` and sandbox files | FX-TR-RETAIN; FX-TR-REPLAY (CLI); FX-TR-STEP on the projection | `application/frames/transcript.py` → `adapters/postgres/frames/transcript_entries.py` → `interfaces/http/transcript.py` | `missionctl run replay RUN --point ID --dry-run` (the exact batch, `exact: true`) |
| **WP-TR-4 The precise fork** | `at`, `inject`, `frontier_policy` on the request; closure; `start_position` for both families; the seed head with the injected message; the Goal Directed reuse rule; the receipt; `run fork --at --point --inject` | FX-TR-FORK-CYCLE; FX-TR-FORK-GD; FX-DA-FORK green | `application/recovery/run_forks.py::prepare` → `domain/programs/dependencies.py` → `domain/policies/forks.py` → `run_launch.py::_apply_fork` → `interpreter.initial_projection` → `time_travel.py::seed_fork` | `missionctl run fork RUN --at stage:S2,cycle:2 --point ID --inject msg.json` then `missionctl run transcript DERIVED --by stage` (S1 `reused_from`, S2 cycle 2 seeded, S3 and S4 fresh) |
| **WP-TR-5 The remote saver** | locator digest on pins and keys; bounded walks and the points budget; `points_incomplete`; the copy on a worker; `503 state_unavailable` and `cognitive_seed_unavailable`; the topology ADR | FX-TR-REMOTE | `adapters/deep_agents/persistence.py` → `cognition_points.py` (bounded walk) → `time_travel.py` → the typed outcomes in `cognition_point_reads.py` | `missionctl run inspect RUN` showing `points_incomplete`, then `--reconcile` |

Documentation inside Stage 1 is the ledger entry per session only; the knowledge concepts,
ADR candidates, operator guide and describe matrix are Stage 3 (§C.3).

## The sequence, for the owner

```text
POST runs/{id}/launch ──────────────────────── mission_run.temporal_* (WP-TR-1)
Temporal family workflow
  ├ admit_operation ─ journal operation_admitted{released_by, continues_from} + event{unit_key} (WP-TR-1)
  ├ operation.execute activity
  │   ├ record_attempt ─ activation, attempt, attempt observation (exists)
  │   ├ adapter.execute
  │   │   ├ materializer.prepare ─ environment_materialized frame (WP-TR-2)
  │   │   ├ recorder.begin ─ session_init, turn_started (exists)
  │   │   ├ astream ─ per step: model_request (callback, TR-2) → message → tool_call_* (promoted, TR-2)
  │   │   │           → subagent_started … subagent_ended (WP-TR-2) → hook_invoked/result (ports, TR-2)
  │   │   │           → checkpoints part keys the step's frames (exists)
  │   │   ├ _capture_result, collect_points (root + nested, TR-2; bounded, TR-5)
  │   │   └ recorder.finish ─ turn_ended, run_result (exists)
  │   └ settle ─ ONE transaction: transition, result, points{workspace_checkpoint_ref, budget_snapshot} (WP-TR-1)
  │              then settlement, derived events{activation_id, unit_key, point_ref} (WP-TR-1)
  ├ result_decided ─ journal + completion_decision + completion_candidate (WP-TR-1)
  ├ cycle_decided ─ journal; next cycle's input point parent_coordinate = prior result (WP-TR-1)
  └ continue_as_new (Goal) ─ workflow_run.record_rollover (WP-TR-1)
Settlement ─ outbox → transcript.project → transcript_entry (WP-TR-3, seconds behind; refresh on demand); frames.expire deletes deltas only (WP-TR-3)
Reads ─ run transcript --by step --full (WP-TR-3) · run replay --dry-run (WP-TR-3) · run points --reconcile (WP-TR-1)
Fork ─ run fork --at --point --inject → closure, start_position, seed head, reused points (WP-TR-4)
```
