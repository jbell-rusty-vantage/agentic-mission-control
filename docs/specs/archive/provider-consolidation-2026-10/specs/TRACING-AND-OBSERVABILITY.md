---
type: Specification Candidate
title: "Mission tracing and observability: the brief for the session that researches, explores the code, reasons and returns a ready-to-implement proposal for capturing, writing and reading the full Mission Transcript across Stage Graph and Goal Directed with Deep Agents cognition inside, and for inspecting and forking with precision"
description: "Audited 2026-10-21 on main after P1 turn 4 and widened the same day. Part I is the verified current functionality: what each workflow type writes about its lifecycle with Deep Agents inside, the read surfaces, the controls, the fork path traced for the owner's scenario (fork from Stage 2 cycle 2, inject a message, start a new run), and the LangGraph persistence that is local now and remote soon. Part II states the target: the Mission Transcript (replayable, harness-written, point-addressed) and the precise fork. Part III is the explicit brief: the research questions, the code explorations, the reasoning the proposal must contain, its acceptance criteria, the owner decisions TR-D1..16, and the build and proof plan. This precedes the queued output-contracts and context-transfer session."
tags: [mission-control, providers, consolidation, deep-agents, tracing, observability, transcript, cognition-points, forks, temporal, langgraph-persistence, P1]
status: archived
archived: 2026-10-23
archived_from: TRACING-AND-OBSERVABILITY.md
archived_reason: "answered by TRACING-PROPOSAL; Tracing Stages 1-3 done"
---

> **Archived 2026-10-23** (answered by TRACING-PROPOSAL; Tracing Stages 1-3 done). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Mission tracing and observability

**Status (2026-10-21, later the same day):** the research and proposal session has run; its
output is [TRACING-PROPOSAL.md](../proposals/TRACING-PROPOSAL.md) (audit corrections in its §A.2, the plan
in P1-P11, the owner's three stages in Part C with the recorded answers in P10) and the Stage 1
instruction [archive/sessions/SESSION-STAGE-1.md](../sessions/SESSION-STAGE-1.md). The owner
decided on 2026-10-21 to finish the Temporal workflow activity cognition state (read, write,
control) and this tracing surface *before* the queued
[output-contracts and context-transfer session](SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md),
so that no incomplete surface is left behind. Turn 4 of P1 ([CHANGES.md](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md),
[COGNITION-POINTS.md](COGNITION-POINTS.md)) built the cognition
coordinate, `state-as-of` and forks from a point; this document starts from there.

Paths are relative to `platform/mission-control`. `M/` is
`packages/mission-control-db-contract/component/migrations/`; `M143/` is
`packages/mission-control-db-contract/releases/1.4.3/component/migrations/`. `src/` prefixes are
dropped under `src/mission_control/`. Every claim in Part I was read in the code on 2026-10-21.
Vocabulary: the glossary term for the record is **Transcript** (its Avoid list has "trace",
LangSmith's word); "tracing and observability" in the title is the owner's name for the
capability, and the body uses Transcript for the artifact.

## 0. The goal, in the owner's words, and what the session must return

> We need to be able to read a literal trace report. This is what is going to set us up fully
> for recursive self improvement. [...] Are we writing / saving workflow state granularly for
> both goal directed and stage graph workflows with deep agents cognition so that we can
> literally retrieve temporal workflow activity → deep agents graph step checkpoint == exact
> state at that point (and exact state up to that point if desired)? [...] Deterministic delta
> updating of mission control tables throughout the mission which will enable us to query for
> and build that transcript. [...] We DO NOT WANT to put any mission control updating
> responsibility on actual working agents. [...] If we do we should make it highly sequenced and
> easy. [...] What do we save? Agent events and framework events, that includes tool call
> results. Then we have sandbox snapshots. And soon we should have a way to verify or at least
> check for final output fulfillment. [...] We literally want to understand each step a mission
> went through throughout its lifetime.

> When we decide to fork from say Stage 2 Cycle 2 of Stage Graph workflow xyz and inject some
> message into the context and start a new run, can we do that? I don't think we have that fully
> created. Doesn't that require creating an entirely new Workflow with the same IO up to that
> point and then let it run as that new workflow and go through its lifetime.

The session returns **one ready-to-implement proposal** with two halves that share one model:

- **Deliverable A, capture and transcript.** For each workflow type (Stage Graph, Goal
  Directed) with Temporal driving Deep Agents cognition: the exact moments at which state is
  captured, what is written at each moment, under which keys, by which writer, in which
  transaction; how it is read back as the Mission Transcript at every granularity; and how the
  model stays deterministic (idempotent delta writes, reconcilable after a crash).
- **Deliverable B, precise inspection and fork.** A critique of today's write, read, inspect and
  fork behaviour against the scenario above, and the design that makes "fork from stage S cycle
  C (or iteration N) at point P, inject a message, run as a new workflow with the same inputs
  and outputs up to that point" exact, proven on T0.

The bar for "complete" adopted here: **a reader with the Transcript to point P can reproduce
the exact input of the step at P, see its exact output, and see the environment and lifecycle
facts around it, without the LangGraph saver or the sandbox being alive.** A fork is "precise"
when the derived run's first model call at the seeded unit sees exactly the source state at P
plus the injected message, every unit before P is reused with the source's outputs, and the
derived Transcript names the source point it continued from.

## Part I. Current functionality (verified 2026-10-21)

### 1. The worked mission, traced through what is written today

Mission: *find 20 diagnostics companies like TruDiagnostic and produce evidenced product,
leadership, operations and case-study reports.* Stage Graph: S1 discover 40 candidates; S2
(depends on S1) rank to 20; S3 and S4 (depend on S2) full research and ingestion for 10 each,
each a deep-seeded Deep Agents profile with specialist subagents and a cycle region.

| Step in the mission | Written today | Not written (or not retrievable) | Where |
| --- | --- | --- | --- |
| Admission and launch | `workflow_run.start` mission event; `run_lifecycle_transition` with the prior and resulting projection; `runtime_document` templates (`stagegraph.template/1` with the prompt segment text); an `activation` row per unit at admission | `mission_run.temporal_workflow_id/run_id` (F-T4-2); `mission_event.activation_id` is hard-coded NULL by both event writers | `application/programs/service.py:327-363`; `adapters/postgres/run_control/canonical.py:557,733`; `adapters/postgres/operations/checkpoint_lineage.py:108` |
| S1 released | family journal mutation `operation_admitted` with the proposal; `workflow_run.reserve_budget`; the sealed Context Packet with inline item text in `context_selection.packet`; the binding (`operation.binding/1`) with `prompt_sources` only | the rendered prompt plan (digest only); which dependency kind released the stage (not a typed fact) | `application/programs/service.py:425-475`; `M/0027_provider_frames.sql:264-268`; `domain/execution/contracts.py:1554` |
| S1 executes (`operation.execute` activity) | `activity_attempt_observation` (workflow, run, activity, attempt, worker, `task_queue`); `harness_execution`, `agent_session` (thread), `session_turn` (invocation); frames in arrival order: `session_init`, `turn_started`, coalesced `message_delta`/`thinking_delta`, `message` (content, tool calls with args, usage, model), `tool_call_started` (args), `tool_call_completed`/`failed` (content ≤ 8 KiB, digest), `usage`, `after_compaction`, `approval_requested`, `turn_ended` (outcome, result checkpoint id, summed usage), `run_result` (digest and bytes only) | **no model-input frame**: the system prompt, the user prompt, the injected follow-up and the message list sent to the model are never framed (recorder handles `AIMessage` and `ToolMessage` only); **no model-start frame**; **no hook frames**: `mc.hook_invoked/result` kinds exist but the Deep Agents kernel hook ports are the Null defaults in production (`kernel_hooks=()`), so stop fence, operation intent, frame capture and usage hooks write nothing durable; full tool results above 8 KiB are kept as digest only, because no caller passes the `FrameWriter` promoter and `body_artifact_ref` is never set | `adapters/deep_agents/adapter.py:551-609,710-725`; `adapters/deep_agents/frames.py:261-347,509-563`; `application/frames/writer.py:39-72,107-183`; `domain/frames/contracts.py:34`; `adapters/deep_agents/materializer.py:156,440-456`; `adapters/deep_agents/hooks.py:205-242`; `adapters/temporal/deployment_composition.py:778` |
| S1 settles | `checkpoint_transition` (source and result checkpoint keys, a redacted summary digest); `unit_result_observation` (status, manifest ref); `operation_settlement` (usage, manifest ref; `output_text` and `structured_output` go to the payload store, not Postgres); `cognition_point` rows, one per root LangGraph checkpoint of the attempt (step, source, roles, message count, files digest, usage delta, frame ordinal range, turn, Temporal attempt); writable-slot files as `workspace_candidate_descriptor` (bytes in the payload store); derived events from closing frames only: `session.*`, `tool_call.completed` (digests), `attempt.completed`, `activation.*` | points are written in **their own transaction after** the transition and result, and a failure is only logged (the application docstring says one transaction; the code does not); `budget_snapshot`, `workspace_checkpoint_ref` always NULL; no `workflow_run.*` event names the point | `application/execution/operations/checkpoint_lineage.py:1124-1235`; `adapters/postgres/operations/cognition_points.py:63-91`; `application/execution/operations/operation_execution.py:2004,2808-2819`; `application/frames/reducer.py:1-31` |
| S2 decides over S1 | `result_decided` mutation (proposal, observation digest, completion validation); later `cycle_decided`, `completion_proposed`; the packet for S2 binds S1's latest accepted result as `/inputs/<binding>/` files | `completion_candidate` and `completion_decision` tables have **no writer**; `journal_segment` has no writer; no typed "which dependency released S2" fact | `application/programs/service.py:680-704,926,1074`; `M/0003_execution.sql:318-341,381-441`; `application/context/pack_service.py:304-388` |
| S3 and S4 subagents (specialists) | sync subagent frames carry `subordinate_ref` from the `tools:<task_id>` namespace; async children get a `subordinate_execution` row and run on the Agent Server's own saver | **no `subagent_start`/`subagent_stop` frames or normalized facts**: a spawn is visible only as the `task` tool call and its result; **no points for nested namespaces** (points are root-only); the Agent Server saver topology is blocked on an owner decision | `adapters/deep_agents/frames.py:21-22,188-189,249-252`; `adapters/deep_agents/cognition_points.py:84-88`; `adapters/postgres/async_subagents/async_subagents.py:83`; `packages/mission-control-db-contract/runtime/AGENT_SERVER_TOPOLOGY.md:3-6` |
| S3 cycles (region re-run) | the cycling stage and its descendants get new candidates with `stage_cycle_ordinal + 1`; each visit is a **new unit key, generation 1, fresh thread** | nothing carries the previous visit's conversation; `prior_result_refs` and `unmet_obligation_refs` are computed and never delivered (K05); no cross-cycle point link | `domain/programs/interpreter.py:562-675`; COGNITION-POINTS §1.3 |
| Inside the sandbox | per step: `cognition_point.files_digest` only (the `files` channel); end of attempt: writable-slot candidates | **no per-step workspace snapshot**; on a sandbox backend the materialized files are uploaded to the sandbox and are **not in the `files` channel**, so `state-as-of` cannot list them (the acceptance test sees `.mission/*` only because the fixture uses the state backend); `DeepAgentsHarness.snapshot` is emulated and persists nothing; `StateBackendWorkspaceSnapshots`, `DeepAgentsSessionHydrator`, `archive_conversation_history` are never constructed in `src` | `adapters/deep_agents/materializer.py:911-931`; `adapters/deep_agents/adapter.py:245-251,394-397,663-686`; `application/execution/harness/deep_agents_harness.py:264-284`; `adapters/deep_agents/compaction.py:413-453,587-639`; `tests/acceptance/mission_control/test_cognition_points.py:293-297` |
| Interventions | `command`, `delivery_report`, `command_mailbox`, `runtime_intervention`; `command.*` events; inject marks `interrupted` and `replacement_start` on point rows | the delivery report names `turn:N`, not points (F-T4-3) | `application/execution/mailbox.py`; `domain/policies/contracts.py:816-840` |
| Goal Directed (if S3 were a Goal Loop) | `goal.iteration/1`, `goal.verification/1`, `goal.handoff/1`, `goal.revision/1` as `runtime_document` rows; lifecycle through `apply_lifecycle_command`; points link iteration N+1's root to iteration N's result on the same role thread | the Temporal continue-as-new rollover writes **no event**; verifier findings never reach the next executor packet (K04); `rollover_start` link declared, not written | `adapters/postgres/orchestration/goal_directed_repository.py:32-116`; `adapters/temporal/workflows/goal_directed.py:127-132` |
| 30 days later | `frame_retention_policy` default: keep 30 days, keep closing frames, 8 192-byte excerpt; the expiry schedule is created by the production worker | **non-closing frames are deleted**: every `message`, delta and `tool_call_started` row goes; the transcript shows `frame_expired` placeholders; mission events survive | `M/0027_provider_frames.sql:118-132,205-216`; `bootstrap/worker.py:728` |

The LangGraph state itself (every message body, every file in the `files` channel, every
channel value) lives only in the private `mission_control_runtime` schema of the standalone
`AsyncPostgresSaver` (`adapters/deep_agents/persistence.py:1-29`; ADR 0017). Mission Control
stores checkpoint ids and keys, never a copy, and reads the state live through `read_as_of`
(`adapters/deep_agents/time_travel.py:71-119`). The bar in §0 is therefore not met today:
without the saver alive, the inputs of a step cannot be reproduced.

### 2. Lifecycle saving and controls, per workflow type, with Deep Agents inside

The matrix the proposal must complete. "Written" is what reaches Mission Control's own tables.

| Lifecycle moment | Stage Graph writes | Goal Directed writes | Deep Agents cognition writes (both) | Read today | Control today |
| --- | --- | --- | --- | --- | --- |
| Run start | `workflow_run.start`; transition row; templates; activations at admission | same; initial `goal.revision/1` | — | `run inspect`, `events watch` | `run start`, `command cancel` |
| Unit released | journal `operation_admitted` (proposal); budget reservation; packet (`context_selection`); binding doc | iteration document `goal.iteration/N`; executor and verifier bindings; packet | the packet seeded as backend files (`.mission/context.md`, `inputs.json`, `/inputs/**`, `/skills`) **in the `files` channel on the state backend, uploaded and unrecorded on a sandbox backend** | transcript (events only), `run points` after settlement | `command queue --boundary next_turn\|next_iteration`, `add_context` |
| Attempt starts (Temporal `operation.execute`) | `activity_attempt_observation` (+ `task_queue`); `harness_execution`; `agent_session` | same | `session_init`, `turn_started` frames; stamped root checkpoint (`belllabs_*` metadata) in the saver | `run frames --tail` (live only) | `command inject` (`cancel_and_replace`), `cancel --urgency immediate` (stop fence) |
| Each graph step (root checkpoint) | — | — | a saver checkpoint (state); frames for AI messages, tool calls and results (capped), usage, compaction, interrupts; **no model-input frame, no hook frame, no subagent lifecycle frame** | after settlement: `run points`, `state-as-of` (live saver read) | none mid-step except inject and cancel |
| Subagent (sync) | — | — | frames with `subordinate_ref` under the `tools:<id>` namespace; nested checkpoints in the saver with no point rows | transcript `--subordinate`, inspection `sessions[].subordinates` | none |
| Subagent (async, Agent Server) | — | — | `subordinate_execution` row; frames and checkpoints on the server's own saver | lineage notice | none |
| Attempt settles | `checkpoint_transition`, `unit_result_observation`, `operation_settlement`, candidates, points (separate transaction), derived `session.*`/`tool_call.completed`/`attempt.completed` events | same, plus `goal.verification/N`, `goal.handoff/N` documents | `turn_ended`, `run_result` frames; `session_turn.point_ref`; `agent_session.checkpoint_*` | `run points`, `run inspect`, transcript | `run snapshot` (only when quiescent) |
| Decision over a result | journal `result_decided` (proposal, observation digest, completion validation); `cycle_decided`; `completion_proposed`; **no `completion_decision` row** | `apply_verification` outcome in the iteration document; rollover decision (`rollover_limit` / `handoff_missing` pause) | — | `run inspect` (projection), journal via technical API | human gates: `satisfy_wait` |
| Cycle or iteration advance | new candidates with `stage_cycle_ordinal + 1` / `workflow_cycle_ordinal + 1`; new unit keys, fresh threads; prior results and unmet obligations computed, not delivered | iteration N+1 continues the role thread from iteration N's result (pin by `expected_source`); `session_generation` bump on rollover, fresh threads from the handoff | points of iteration N+1 link to N's result (same thread); **no cross-cycle link** for stages; **no `rollover_start` link** | `run points --cycle C` / `--iteration N` | none |
| Continue-as-new (Temporal) | carries counters; unit keys and namespaces byte-identical across segments | same; **writes no event** | — | Temporal history only | — |
| Run end | `workflow_run.complete` transition; `run.completed` projection | same | — | `run inspect` | `recover-closed-workflow` |
| After 30 days | mission events survive; non-closing frames deleted | same | the saver keeps everything (no retention of its own) | transcript with `frame_expired` | — |

### 3. Read surfaces today

| Surface | What it returns | What it cannot return | Where |
| --- | --- | --- | --- |
| `missionctl run transcript RUN [--format jsonl\|md] [--since] [--activation] [--node] [--kinds] [--canonical-only] [--subordinate] [--limit 500] [--follow] [--full]` → `GET runs/{id}/transcript` | a **view, never persisted**: mission events by `seq`, provider frames by arrival placed under the last event at or before them, `artifact.*` events as artifact entries, `frame_expired` placeholders; cursor `tc1:<seq>:<observed_us>:<ordinal>:<tag>`; bounds 20 000 events and 50 000 frames; entries carry `activation_id`, `attempt_no`, `node_key`, `subordinate_ref`, refs (event, frame, native, artifact, tool call, command, human task, digest), usage | model inputs; hook frames; point ids (`TranscriptRefs` has none; frame entries never set `iteration_id`); bodies beyond 2 048 characters (`--full` needs an artifact ref that no frame ever has, so it is 501 in practice); frames are placed by time because events carry NULL `activation_id` | `interfaces/cli/main.py:914-925,713-739`; `application/frames/transcript.py:1-16,58-63,414-466,526-554`; `domain/frames/transcript.py:7-12,59-89` |
| `missionctl run points RUN [filters]` → `GET runs/{id}/points` | `mc.cognition_point.v1` pages: unit location, point, parent, roles, attempt, turn, frame range, redacted facts | `--reconcile` (**not in the parser**); nested or subagent points | `interfaces/cli/main.py:947-961`; `interfaces/http/cognition_points.py:80-127` |
| `missionctl run state-as-of RUN --point ID` → `GET .../points/{pid}/state-as-of` | `mc.state_as_of.v1`: messages (role, name, tool calls, redacted text ≤ 8 KiB with digests), files as path, size, digest, encoding, other channels redacted ≤ 64 KiB, pending tasks, interrupts, step, source, stamps, usage to point, `restore_level: R3` | file **contents**; files on a sandbox backend; point kinds other than `checkpoint`; lanes other than `deep_agents` (time travel is composed only for it); the system prompt | `application/execution/cognition_point_reads.py:76-82`; `adapters/deep_agents/time_travel.py:71-151,258-348`; `bootstrap/api.py:307-327` |
| `missionctl run frames RUN --tail` → `GET runs/{id}/frames/tail` (SSE, non-canonical) | live frames with excerpts | history | `interfaces/http/transcript.py:253-295` |
| `missionctl run inspect RUN` → `GET runs/{id}/inspection` | lifecycle, phase, projection, lineage, lane, sessions (with `subordinates`), mailbox, delivery reports, frames cursor, chain, subscriptions, stop fence | step-level anything | `contracts/contracts.py:307-331`; `application/frames/transcript.py:117-132` |
| `missionctl run checkpoint RUN --list\|--get` → `GET runs/{id}/checkpoints` | SPEC-02 continuation checkpoints (not LangGraph) | — | `interfaces/http/continuation.py:54,67` |
| Technical `/run-control/v1`: `runs`, `units`, `units/{uk}/checkpoints`, `checkpoints/{cid}/summary`, `transitions`, `effect-ledger` | LangGraph history per unit (counts only, `_fold_delta`), transitions, effects | bodies | `interfaces/http/runtime_inspection.py:109-194`; `interfaces/http/run_control.py:717-740` |
| `missionctl run search RUN --query` → `GET runs/{id}/transcript/search` | ranked entries over `mission_control_search.transcript_document` (excerpts ≤ 16 KiB, refreshed on demand; the `transcript.project` activity is not constructed) | — | `adapters/postgres/frames/transcript_projection.py:36-92`; `adapters/temporal/activities/transcript_projection.py:4-7` |
| `missionctl events watch MISSION` → `GET missions/{id}/events` (SSE) | mission events after a `seq`, `resync_required` on gap | — | `interfaces/cli/main.py:532-560,1039-1043` |
| Socket.IO `mc.stream_envelope.v1`: `mission_event`, `provider_frame`, `lineage`, `command_receipt`, `human_task_receipt`, `presence`, `snapshot`, `resync_required` | frame payload: raw kind, closing, native ref, digest, bytes, turn ref, tool call ref, normalized facts, excerpt unless tool detail is not `full`; `lineage` notices with refs, lifecycle, frame counts, usage rule, never child content | **`point_ref` on frames** (declared, not written); a lineage HTTP endpoint | `interfaces/socketio/server.py:9-15,195-209`; `application/frames/streams.py:201-213`; `application/streams/service.py:730-776,973-990` |
| Evidence: `GET runs/{id}/evidence \| inputs \| completion-evidence \| goal-completion-evidence` | evidence refs | artifact **bodies**: there is no artifact download endpoint (ingress has `artifacts:prepare\|commit` only); bodies are reachable only through transcript `--full`, which never resolves | `interfaces/http/run_evidence.py:46-86`; `interfaces/http/ingress.py:79,90` |

Grants: `state_inspector` = `workflow_run.read` + `workflow_run.read_checkpoint_summary`;
`fork_operator` = read, snapshot, fork; `workflow_run.control` for a fork with an instruction and
for `queue_instruction`, `add_context`, `interrupt_and_inject`; `workflow.result.read` for full
tool detail and evidence (`interfaces/http/run_control.py:145-163`; `domain/policies/reducer.py:107-148`;
`application/streams/service.py:300-303`).

### 4. Control surfaces today

| Control | What it does | Limits | Where |
| --- | --- | --- | --- |
| `run snapshot` → `POST runs/{id}/snapshots` | macro snapshot at `stage_settled` or `goal_verifier_settled` into `continuation_checkpoint` and `run_snapshot`; refused `snapshot_not_quiescent` while any stage is active, a producer liability is open, usage is pending settlement, a command is unapplied, or the run is cancelling | boundary only, never mid-step; a running stage must settle (or be cancelled) first | `application/recovery/run_forks.py:366-432,655-719,736-805`; `M/0013_snapshot_fork_support.sql:8-36` |
| `run fork` → `POST runs/{id}/forks` | saga: a **new BellLabs run and a new Temporal workflow** admitted with reuse decisions; `ForkSeedService` writes the instruction as `queue_instruction` and the snapshot restore as `add_context{workspace}` into the derived mailbox; with `cognitive_seed`, `seed_fork` copies the source thread's root lineage up to the point into the derived thread (R3, native) and writes a `fork_seed` point | see §5 for the scenario; no `--point` CLI flag (request file only); `ForkSeedRequest.message/files` exist and are never read; Goal Directed units are never reused (`goal_revision_identity_is_run_bound`, F-T4-1); source mailbox, children and in-flight commands dropped | `domain/policies/forks.py:525-631`; `application/recovery/fork_seed.py:87-178`; `application/recovery/cognitive_seed.py:81-206`; `adapters/deep_agents/time_travel.py:153-254` |
| `command send` (`pause`, `resume`, `satisfy_wait`, `request_continuation`), `command queue`, `command inject`, `command cancel` | mailbox receipts `queued → delivered → observed → applied`; inject is `cancel_and_replace` and marks the points; cancel writes the stop fence first | `request_continuation` on this lane is recorded and never driven (no hydrator registered); delivery reports name turns | `application/execution/harness/inject.py:161-258`; `application/missions/service.py:225-269` |
| `run reconcile` → `POST runs/{id}/reconcile-unit` | unit reconciliation and checkpoint incidents | a reconciler that re-derives **points** from the saver after a crash: not built | `application/execution/operations/unit_reconciliation.py`; `application/execution/operations/checkpoint_lineage.py:143-153,451-489` |
| Hook scripts (ADR 0026) | 17 events, kernel hooks first (`mc.stop_fence`, `mc.operation_intent`, `mc.frame_capture`, `mc.usage`); a script can allow, deny, defer, add context, rewrite input | on Deep Agents a script has **no callback** to Mission Control (`HookContext.callback` never set; the callback service serves Cursor and Codex), and the kernel hooks' ports are Null | `domain/capabilities/hooks.py:38-55,402-423`; `contracts/hooks.py:49-69`; `application/execution/harness/hook_callbacks.py:1-21` |

### 5. The owner's scenario, traced: fork from Stage 2, cycle 2, inject a message, new run

Answer first: **yes, it is a new workflow**, and **no, it is not fully created**. The fork saga
already does what the owner describes (a new BellLabs run on a new Temporal workflow, units
before the frontier reused with the source's outputs, the seeded unit continuing from the
copied conversation plus the injected instruction), and FX-DA-FORK proves it for a last stage at
cycle 0. For cycle 2 it is admitted and mis-targeted. Step by step:

1. **Quiescence.** The snapshot is refused while Stage 2 (or any stage) is active
   (`stage_active:*`, `run_forks.py:674-679,426-431`). The owner must wait for `stage_settled`
   or cancel. There is no "snapshot the running stage at its last checkpoint" path; inject is the
   only in-flight control.
2. **Reuse decisions are by stage id, not by cycle.** `compute_reuse_decisions` invalidates
   every unit whose stage is in the caller-supplied `invalidation_frontier` and reuses every
   other settled unit (`forks.py:576-631`). The frontier is validated against the patched
   fields only; **it does not close over dependent stages** (`required_invalidation_frontier`,
   `forks.py:444-495`; no descendant computation anywhere in the fork path). A caller that lists
   only `S2` leaves S3 and S4 marked `reuse`, although they consumed S2's old output. Whether the
   execution-time compatibility check on the reused candidate's `binding_digest` catches this
   (`forks.py:162`; `operation_execution.py:1518`) is unverified; the session verifies it.
3. **The derived unit keeps the source's cycle ordinal; the derived run starts at cycle 0.**
   `derived_unit_identity` substitutes run id and epoch only (`forks.py:525-531`), so the seed for
   Stage 2 cycle 2 is restored into the namespace of a derived unit with
   `stage_cycle_ordinal=2`. The derived Stage Graph interpreter starts every stage at
   `workflow_cycle_ordinal=0, stage_cycle_ordinal=0` (`interpreter.py:111-112,665`), and the
   snapshot's `FamilyPosition` (which records `workflow_cycle_ordinal` and the accepted stage
   ids) is written and **consumed by nothing** in the derived run (`run_forks.py:475`; no other
   reader). So the derived run admits Stage 2 cycle 0, whose unit key differs, finds no seeded
   head, and runs it fresh; the cycle-0 and cycle-1 units of Stage 2 are inside the frontier and
   **re-executed with cognition from scratch**; the seeded cycle-2 namespace is orphaned, and
   the fork instruction, queued into the derived mailbox, is delivered to whatever unit claims
   it first. Nothing refuses this: `seed()` only requires the seed's unit to be `invalidated`
   (`cognitive_seed.py:131-141`).
4. **The derived Transcript has no provenance for reused units.** A reused unit settles from
   the source settlement (`_settle_reused`, `operation_execution.py:2274-2295`) with
   `reused_result` on the settlement but no transition, no points and no frames in the derived
   run; the derived transcript shows the lifecycle events and nothing of the cognition, and no
   link to the source run's points.
5. **Goal Directed is worse.** Every Goal Directed unit is `not_reusable`
   (`goal_revision_identity_is_run_bound`), the derived run restarts at iteration 1, and only the
   role thread continues from the seed (F-T4-1). "Fork from iteration 7 of a Goal Loop" today
   means "re-run iterations 1 to 6 with cognition and pin the executor thread to the copied
   history".
6. **What does work** (FX-DA-FORK): last stage, cycle 0, snapshot at `stage_settled`, seed at an
   intermediate step, instruction as `queue_instruction`; the derived stage's input checkpoint
   has the copied point as parent and its first model call sees the instruction.

So the owner's intuition is right on both counts: it must be a new workflow (it is), and the
precise form ("same IO up to that point, then run its lifetime from P") does not exist for a
cycle above zero, for Goal Directed, or with provenance in the Transcript.

### 6. LangGraph persistence: local now, remote soon

- Today: a standalone `AsyncPostgresSaver` and `AsyncPostgresStore` in the private
  `mission_control_runtime` schema, provisioned by `mission-db runtime-apply`, selected per
  connection with `search_path`, keyed by `settings.langgraph_checkpoint_dsn`
  (`adapters/deep_agents/persistence.py:1-29`; `bootstrap/settings.py:549`;
  `bootstrap/worker.py:302`; `bootstrap/api.py:311`; ADR 0017). The adapter stamps every root
  checkpoint with `checkpointer_ref_digest` and refuses a plan whose digest differs from the
  binding (`adapters/deep_agents/adapter.py:590,893,911`).
- Everything that reads or copies state crosses into that database: `read_as_of`, `seed_fork`
  (`acopy`-style lineage copy with the saver primitives), the point collector's walk at
  settlement, the checkpoint history reader, the hydrator (unregistered).
- The owner will move this saver to a **remote database**. Consequences the proposal must
  address: (a) the Transcript must not depend on the saver (already the §0 bar; the remote move
  makes it urgent: latency, availability and retention of the saver are no longer ours);
  (b) the settlement walk that collects points becomes a remote read inside the activity's
  settlement window; (c) `seed_fork` becomes a remote copy, and a Goal Directed role thread's
  linear lineage grows across iterations in that remote store; (d) `checkpointer_ref_digest`
  must change with the DSN so a point names *which* saver holds it; (e) the async Agent Server
  children already live on a foreign saver, so the remote move is the moment to decide one
  topology for both (`AGENT_SERVER_TOPOLOGY.md`); (f) the kernel's own copy of what it needs
  (model inputs, bodies, file manifests) is the only durable record if the remote saver is
  purged.

### 7. What is proven (acceptance, T0, real Postgres 17 and Temporal, scripted cognition)

FX-DA-POINTS, FX-DA-POINTS-SG, FX-DA-FORK, FX-DA-INJECT in
`tests/acceptance/mission_control/test_cognition_points.py:172,248,310,439`; technical snapshot,
fork and inspection in `test_postgres_runtime_parity.py:111,505,588`; chains in
`test_chain_two_goal_loops.py:421,559`. The transcript and the Socket.IO stream have unit and
integration coverage only, no acceptance test. No test forks at a cycle above zero, forks a
non-terminal stage with dependants, or forks a Goal Loop at iteration N > 1.

### 8. Verdict on the owner's questions

- **Granular state, activity → graph step?** The *index* exists and is proven: every root
  LangGraph checkpoint of every attempt has a point row naming the Temporal workflow, run,
  activity, attempt and task queue, the turn, the step and the frame range; the state at the
  point is readable live and a fork can start from it. The *state* is not ours: it is in the
  saver, read on demand, redacted, digest-only for files, root threads only, Deep Agents only.
  Subagent steps, sandbox-backend files, model inputs and hook invocations are outside the index.
- **Can we construct the Transcript?** Not to the §0 bar. The transcript endpoint is the right
  skeleton but has no model inputs, no hook or subagent lifecycle facts, no point ids, bodies
  capped at 2 048 characters with no path to the full body, events that cannot name their
  activation, and it loses non-closing frames after 30 days.
- **Fork from Stage 2 cycle 2 with an injected message as a new run?** Admitted, new workflow,
  mis-targeted for cycle > 0, frontier not closed over dependants, no provenance, Goal Directed
  restarts. §5.

## Part II. The target

### 9. The Mission Transcript

The **Mission Transcript** is the ordered, complete, replayable record of every step a mission
went through, materialized from Mission Control's own tables (and the artifact payload store
they reference), independent of any provider saver or sandbox being alive. It is evidence,
never state; the reducers stay the authority.

It is read at seven nested granularities, each addressable by one cursor and, from the attempt
down, by one cognition point id:

```text
mission ─ run ─ stage | iteration ─ cycle | session generation ─ attempt ─ turn ─ step ─ frame
```

Each **step** entry (one root LangGraph checkpoint, one point) answers six questions:

| Question | Content | Source of truth |
| --- | --- | --- |
| Who | run, unit key, generation, family location, thread, point id, parent point, Temporal attempt, **and for a derived run the source point it continued or reused from** | `cognition_point` (exists); `parent_coordinate` across runs (declared) |
| What went in | the exact model input: system prompt digest and ref, the sealed packet ref, the message list by identity, the injected follow-up if any | **new** `model_request` frame per model call (digest, refs; full body as artifact under policy) |
| What came out | AI message (content, tool calls with args, usage), tool results **whole** (by artifact ref when above the cap), subagent spawn and finish, compaction, approvals, hook invocations and results | frames (exist; promotion, hook sinks and subagent facts to wire) |
| Environment | the workspace delta of the step (files digest exists) and, at attempt end, a workspace checkpoint ref; on a sandbox backend, the upload manifest | `cognition_point.files_digest`, `workspace_checkpoint_ref` (NULL today), **new** materialization manifest |
| Control | interventions delivered at or inside the step, by point | delivery reports with `point_ref` |
| Lifecycle | the typed decision this step contributed to: released by which dependency, result decided, cycle decided, verification, handoff, rollover, acceptance, submission check | family journal, `runtime_document`, **new** `completion_decision` writer, mission events with `activation_id` and `point_ref`, a rollover event |

### 10. The precise fork

`fork --from RUN --at <stage S, cycle C | iteration N> --point P --inject msg.json` produces a
derived run such that:

1. every unit that precedes P in the dependency order is **reused by reference** with the
   source's settlement, and the derived Transcript shows each as `reused_from: <source point>`;
2. every unit that depends on an invalidated unit is invalidated too (the frontier is the
   **downstream closure**, computed, not caller-supplied; the caller may widen it);
3. the derived family **starts at the source's family position** (the cycle ordinals and
   accepted stage ids, or the Goal Directed iteration and session generation), so the seeded
   unit's key equals the derived unit the fork restored, and no earlier cycle or iteration is
   re-executed;
4. the seeded unit's first model call sees the copied conversation to P, the injected message
   as the last human message, and the environment of P (files, inputs manifest), and its input
   point has `parent_coordinate` = P on the source run with role `fork_seed`;
5. the derived run then lives its own lifetime (own Temporal workflow, own budget, own
   Transcript) and can itself be forked.

For Goal Directed this requires run-independent revision identity (F-T4-1) or an explicit
"reuse iterations 1..N-1 by ref" rule; the proposal decides which.

### 11. Principles

1. **The harness writes; the working agent does not remember to.** Every structural fact
   (frames, points, lifecycle, environment) is observed by the adapter, the kernel hooks and the
   Temporal activities. The agent's only writes are its **submission** (its declared outputs,
   through the output-contract path of the queued session) and, if the owner wants it, one
   optional `progress_note` tool. Both are single, idempotent, sequenced calls that carry the
   current point id, never "update table X".
2. **Deterministic delta writes.** Every writer is idempotent by a stable key (frames by
   `provider_key`; points by `uuid5` point id; events by `seq`; documents by typed key) and is
   either in the settlement transaction or reconcilable from a durable source. A write that can
   silently fail (points today) is not a Transcript writer.
3. **Native first, normalized beside** (ADR 0028; ADR 0040 as proposed): the raw frame is kept
   verbatim up to the cap; the full body goes to the payload store as an artifact; a small
   normalized fact vocabulary (`execution.*`, `tool.*`, `subordinate.*`, `model.*`, `hook.*`,
   `compaction.*`) is derived from closing frames.
4. **Retention follows the mission, not the clock, and prunes by degradation.** Frames the
   Transcript needs live as long as the mission's evidence does; the 30-day default applies to
   deltas only; a prune lowers a point's `restore_level` and records why, it never deletes the
   row, and every read or fork of a degraded point returns a typed outcome (TR-D17).
5. **Subagents are steps too.** A child's lifecycle is a normalized fact with a stable ref, and a
   child thread's root checkpoints are points under the parent point (visibility `full`) or a
   `lifecycle_only` entry when the provider hides them.
6. **The Transcript is replayable.** `missionctl run replay RUN --point ID --dry-run`
   reconstructs the model input of the step from the Transcript alone. This is the test of
   completeness and the substrate for self-improvement.
7. **The saver is a cache of cognition, not the record.** Whatever moves to the remote LangGraph
   database can be lost without losing the Transcript; the kernel keeps the digests, refs and
   bodies it needs, and names the saver by digest on every point.

### 12. What writes what (target)

```text
operation.execute activity
  ├ kernel hooks (wired on this lane): mc.frame_capture → hook frames; mc.usage → usage; mc.operation_intent → intents; mc.stop_fence
  ├ model middleware (wrap_model_call): model_request frame {system_digest, packet_ref, message_ids, follow_up?} before each call
  ├ recorder (astream v2 incl. "checkpoints"): message, tool_call_*, usage, compaction, approval, subagent_started/ended, turn_ended, run_result
  │     └ FrameWriter with promoter: bodies above the cap → artifact (tool results, messages, run results, model requests)
  ├ materializer: materialization manifest (what was uploaded where, by digest) on the input point
  └ settlement, one transaction: transition, result, points (roles, frame range, workspace_checkpoint_ref, budget_snapshot), submission check
Temporal workflow (Stage Graph, Goal Directed)
  ├ family journal: operation_admitted {released_by: dependency kind}, result_decided, cycle_decided, completion_proposed
  ├ completion_decision rows (writer built); goal.* documents; rollover event; derived-run start-at-position
  └ mission events with activation_id, execution refs and point_ref
Fork saga: downstream-closed frontier; family position carried into the derived run; reused units recorded with reused_from points
Reconciler (missionctl run points --reconcile): re-derives points and frame ranges from the saver and the frame store after a crash
Transcript materializer: a persisted, cursor-addressable projection (table), refreshed by an activity, replacing the bounded on-demand view for finished runs
```

### 13. The read model (target)

- `missionctl run transcript RUN --by step|turn|attempt|stage|iteration|mission [--point ID] [--full]`:
  entries carry `point_id`, `parent_point_id`, `activation_id`, `node_key`, `cycle`, `iteration`,
  `session_generation`, `subordinate_ref`, `reused_from`; `--full` resolves bodies through the
  artifact reader.
- `missionctl run replay RUN --point ID [--model NAME --dry-run]`: prints the reconstructed model
  input; with a model, runs it once outside any mission and stores the comparison as an artifact
  of the *inspection*, never of the run.
- `missionctl run fork RUN --at <stage|iteration> --point ID --inject FILE`: the precise fork of
  §10 with a receipt that names the source point, the reused units and the frontier closure.
- `GET runs/{id}/points/{pid}/frames` (missing today); `GET runs/{id}/artifacts/{ref}` download
  (missing today); Socket.IO `provider_frame` with `point_ref`; `lineage` with child point refs;
  `state-as-of` extended with file contents under a cap and with the sandbox manifest.

## Part III. The brief for the session

The session is run by Fable 5.1 under `PROCESS.md` (orient, audit, cross-reference, plan,
**confirm with the owner**, build, prove, document). It returns the proposal first, builds only
what the owner confirms, and spends T0 only unless the owner names a model.

### 14. Research (R): current, cited, dated

| # | Question | Where to look | Why it matters |
| --- | --- | --- | --- |
| R1 | What does the pinned `deepagents==0.7.5` and its LangChain base expose for observing a model call's **input** (a `wrap_model_call` middleware's `ModelRequest`: system prompt, messages, tools), and what changed up to the latest release? | `docs/specs/archive/fast-track-2026-10/research/deepagents-middleware.md`; the installed package; the upstream changelog (fetch and cite) | the `model_request` frame (TR-G1) must come from the real request object, not a reconstruction |
| R2 | What does the LangGraph Postgres saver guarantee for `aget_tuple`, `alist`, the pending writes and the `messages` delta channel when it is **remote** (latency, pagination, consistency), and what does `acopy_thread` (or the primitive-level copy turn 4 used) cost across a network? | `langgraph-checkpoint-postgres` source and docs; `adapters/deep_agents/time_travel.py:153-254` | remote saver (§6) |
| R3 | How does Temporal expose **activity-level** history for a workflow run (event history, `task_queue`, attempt timestamps), and can the Transcript's activity rows be reconciled against Temporal's history rather than re-derived? | Temporal Python SDK docs; `adapters/temporal/operation_activities.py:150-161` | the "Temporal workflow activity" half of the owner's equation |
| R4 | What do comparable systems record per step for replay (LangSmith run trees, OpenAI Evals traces, Anthropic agent traces, Braintrust spans): fields, body handling, retention? | public docs; cite | so the Transcript schema is not invented blind, and "trace" stays LangSmith's word |
| R5 | What is the Agent Server's checkpointer and store topology for async children, and what would one remote database for both the parent saver and the server mean? | `AGENT_SERVER_TOPOLOGY.md`; LangGraph platform docs | §6 (e) |

### 15. Code exploration (E): read before reasoning

| # | Explore | Files |
| --- | --- | --- |
| E1 | The capture path end to end for one Stage Graph attempt and one Goal Directed iteration: activity → harness → adapter → recorder → writer → repository → settlement → points | `adapters/temporal/operation_activities.py`; `application/execution/harness/deep_agents_harness.py`; `adapters/deep_agents/adapter.py` (`execute`, `_invoke`, `_frame_recorder`, `_capture_result`); `adapters/deep_agents/frames.py`; `application/frames/writer.py`; `adapters/postgres/frames/{repository,identity}.py`; `application/execution/operations/{operation_execution,checkpoint_lineage}.py`; `adapters/deep_agents/cognition_points.py` |
| E2 | The lifecycle writers of both families and what each mutation carries | `application/programs/service.py`; `domain/programs/{interpreter,goal_directed}.py`; `adapters/temporal/workflows/{stagegraph,goal_directed}.py`; `adapters/postgres/orchestration/*`; `adapters/postgres/run_control/{canonical,run_control_repository}.py`; `domain/policies/reducer.py` |
| E3 | The fork path with the §5 scenario in hand: snapshot quiescence, reuse decisions, derived identity, cognitive seed, mailbox seed, and how the derived Stage Graph and Goal Directed workflows start | `application/recovery/{run_forks,fork_seed,cognitive_seed}.py`; `domain/policies/forks.py`; `application/execution/run_launch.py`; the family workflows' start paths; `tests/acceptance/mission_control/test_cognition_points.py:310-440` |
| E4 | The execution-time reuse compatibility check: does a reused candidate's `binding_digest` change when an upstream stage re-runs, and what happens if it does not match | `operation_execution.py:794-830,1518`; `domain/policies/forks.py:150-170` |
| E5 | The read model: transcript merge, cursor, bounds, search projection, streams, points and `state-as-of` | `application/frames/{transcript,streams,search,lineage,projections}.py`; `domain/frames/transcript.py`; `application/streams/service.py`; `application/execution/cognition_point_reads.py`; `adapters/deep_agents/time_travel.py` |
| E6 | Hooks on this lane: kernel hook ports, `HookContext`, the callback service, and what a `wrap_model_call` middleware would need to emit a frame through the same sink | `adapters/deep_agents/{hooks,materializer}.py`; `application/execution/harness/hook_callbacks.py`; `adapters/temporal/deployment_composition.py:434-443,778` |
| E7 | Retention, the payload store and the artifact reader: what a promoted body costs and how it is read back | `M/0027_provider_frames.sql:118-216`; `bootstrap/worker.py:728`; `application/frames/artifact_bodies.py`; `adapters/postgres/workspace_candidate_contents.py` |
| E8 | The saver boundary: every call site that touches `mission_control_runtime`, and what breaks if the DSN points at a remote host with 50 ms latency | `adapters/deep_agents/persistence.py`; grep `langgraph_checkpoint_dsn`, `checkpointer_ref_digest`, `AsyncPostgresSaver` |

### 16. Reasoning (P): what the proposal must contain

The proposal is one document (`TRACING-PROPOSAL.md` beside this file) with these sections, in
this order, each with its own `file:line` citations and its own "what changes" list:

- **P1 Capture model.** A table per workflow type with one row per lifecycle moment of §2:
  moment, trigger (Temporal event, LangGraph stream part, middleware hook, reducer decision),
  what is written (table, columns or document kind), stable key, writer, transaction, and
  "answers which of the six questions". Every row of §2 marked "not written" has a row here or
  an explicit "stays unwritten because …".
- **P2 Schema delta.** The migrations for the next release: new frame kinds (`model_request`,
  `subagent_started/ended`, hook frames wired), new columns (`mission_event.activation_id`
  populated, `point_ref` on events and stream frames, `reused_from` on points, `released_by`
  on the admission mutation), the `completion_decision` writer, the retention policy fields,
  the persisted transcript projection. Each with its RLS and grant lines, in the style of
  `M143/0045_cognition_points.sql`.
- **P3 Write path.** The code changes per writer, including the settlement transaction that
  now carries points, the promoter wiring, the kernel hook ports on this lane, the model
  middleware, the materialization manifest, the rollover event, the downstream-closed frontier,
  the family position carried into the derived run, and the reconciler. Deep modules behind the
  existing routers; nothing lane-specific outside its discriminated container.
- **P4 Read model.** The Transcript contract (`mc.transcript_entry.v2` or an additive v1), the
  `--by` levels, `replay --dry-run`, frames-by-point, artifact download, the fork CLI, and what
  each returns for the §1 mission at each of the seven granularities (a worked example, not
  prose).
- **P5 Precise fork.** The design of §10 for both families, with the Goal Directed identity
  decision argued (run-independent revision ids versus a reuse rule), the frontier closure
  algorithm, the family position carry, the derived unit identity change, and the receipt.
- **P6 Remote saver.** What changes when `langgraph_checkpoint_dsn` is remote: the settlement
  walk budget, the copy in `seed_fork`, the digest that names the saver, the Agent Server
  topology recommendation, and the failure modes (saver unreachable at settlement, at
  `state-as-of`, at fork) with the typed outcomes for each.
- **P7 Agent-side writes.** The `submit` and optional `progress_note` tools: shape, idempotency
  key, how they carry the point id, how the harness fills what the agent must not.
- **P8a Retention and degradation (outline only).** The three retention classes, the
  degradation levels, the pins and the typed outcomes of TR-D17 as a section the later pruning
  session completes; this session only reserves the columns (`pruned_at`, `prune_policy`) and
  the outcome names.
- **P8 Determinism and reconciliation.** For every writer: idempotency key, what a crash
  between writes leaves behind, and how `--reconcile` repairs it. A table.
- **P9 Proof plan.** The FX-TR fixtures (§19) with the exact assertions.
- **P10 Decisions.** TR-D1..16 answered or left to the owner with a recommendation each.
- **P11 Honest list.** What the proposal leaves out and why.

### 17. Acceptance criteria for the proposal (the owner reads these before confirming)

1. For the §1 mission, every one of the six questions is answered for every step, subagent step
   included, from Postgres and the payload store alone, with the saver container stopped. Where
   it is not, the proposal names the row and the reason.
2. The §5 scenario is designed end to end, with the derived run's first model call, its reused
   units and its Transcript provenance shown as a worked example for Stage Graph **and** for Goal
   Directed.
3. Every writer in P3 has an idempotency key and a reconciliation path in P8.
4. No proposal item makes a working agent responsible for a table write.
5. The remote-saver section names every call site and gives each a typed failure outcome.
6. Nothing changes the reducers' authority, the Temporal-only scheduling rule, or the
   "application PostgreSQL and Temporal persistence are separate" invariant.
7. Every claim about the current code cites `file:line` read in this session; every claim about
   a library cites the installed version or a fetched page with its date.

### 18. Decisions for the owner (TR-D)

| # | Decision | Recommendation |
| --- | --- | --- |
| TR-D1 | Retention of frames the Transcript needs | mission-lifetime for closing frames, `message`, `tool_call_*`, `model_request`, hook and subagent frames; 30 days for deltas only; retention becomes a lane-profile field |
| TR-D2 | Model-input record | one `model_request` frame per model call from a `wrap_model_call` middleware placed after the summarizer and before the model; body = system prompt digest and ref, packet ref, message identities, follow-up text; full body promoted under TR-D3 |
| TR-D3 | Full-body promotion | wire the promoter to the artifact payload store for `tool_call_completed`, `message`, `run_result`, `model_request`; cap raised from 8 KiB to a lane-profile value |
| TR-D4 | Kernel hook ports on Deep Agents | wire `frames`, `usage`, `intents`, `stop_fence` in `deployment_composition`; give `HookContext.callback` the same callback service Cursor and Codex use, so a catalog hook can write a frame or an intent (never a table) |
| TR-D5 | Subagents as steps | `subordinate.started/ended` normalized facts from the `task` tool frames and the async child rows; nested-namespace root checkpoints become points with `parent_point_id` = the parent's step point; Agent Server saver topology decided with TR-D14 |
| TR-D6 | Points in the settlement transaction, plus the reconciler | yes to both; a point write failure fails settlement into `reconcile_required`, not a log line |
| TR-D7 | Joinability | `activation_id`, execution refs and `point_ref` on mission events; `point_id` on transcript entries; `point_ref` on stream frames; the attempt observation joined by `observation_key` (documented pitfall) |
| TR-D8 | Environment | the materializer writes a materialization manifest on the input point; the result point gets `workspace_checkpoint_ref` from an end-of-attempt snapshot of the writable slots; per-step snapshots stay digests (cost) |
| TR-D9 | Agent-side writes | none except the submission (output contracts) and an optional `progress_note` tool; both carry the point id and are idempotent |
| TR-D10 | Transcript materialization | persisted projection table for runs past their first attempt, refreshed by the existing `transcript.project` activity (constructed); the on-demand view stays for live tails |
| TR-D11 | Replay | build `replay --dry-run` in this session as the completeness test; a paid replay is a later decision |
| TR-D12 | Frontier closure | the fork computes the downstream closure of the invalidated units and refuses a caller-supplied frontier that is narrower; the caller may widen it |
| TR-D13 | Family position carry | the derived run starts at the source's family position (cycle ordinals, accepted stage ids; iteration and session generation), carried in the fork request and honoured by the family workflow's start path |
| TR-D14 | Goal Directed fork identity | run-independent revision identity so iterations 1..N-1 reuse by ref (preferred), or an explicit reuse rule keyed by iteration with the role thread pinned; the proposal argues both and recommends one |
| TR-D15 | Remote saver | one remote database for the parent saver and the Agent Server (if R5 allows), `checkpointer_ref_digest` derived from the DSN host and schema, settlement walk bounded by a budget with `points_incomplete` as a typed outcome that the reconciler clears |
| TR-D16 | Scope | `deep_agents` first; the general parts (events, transcript, retention, completion writers, fork closure, family position) are lane-neutral by construction |
| TR-D17 | Pruning by degradation (owner insight 2026-10-21; specifics and the agent-skill exposure are **completed later**, recorded here so it is not lost) | recurring pruning is necessary, keyed on mission lifecycle with TTL as the clock inside each tier, not one wall-clock TTL: the LangGraph saver (expensive, soon remote, a cache once the Transcript holds inputs and outputs) prunes first and hardest; frames prune deltas early and keep the step-defining frames for the mission's evidence life; the ledger (events, points, settlements, journal, artifact registry) is never pruned, only bodies move cold. A prune **degrades a point's `restore_level` in place** (R3 native lineage, forkable → R2 reconstructable from the Transcript → R1 facts only → R0 lifecycle) and records policy, time and level; it never deletes the row. Pins exempt a point that is the parent of a live derived run's fork seed, under an evidence or evaluation hold, or referenced by a pending human task. The coordinator gets typed outcomes, never silent holes: `state-as-of` at a degraded point returns what remains plus a `withheld` block (level, pruned at, policy, what was lost); a fork below R3 is refused `point_pruned` with the level, the nearest seedable point above it and whether an R2 reconstructed fork is offered; Transcript entries for pruned steps stay in sequence as `pruned` with digests; the reconciler distinguishes pruned from crashed. Precondition: the saver TTL is introduced only after TR-G1 and TR-G2 are closed, because today the saver is the only holder of a step's input. The mission-control agent skill must surface these outcomes (deferred to the coordinator-surface work) |

### 19. Build and prove (after confirmation)

Build order: (a) joinability and the settlement transaction (TR-D6, TR-D7) and the reconciler;
(b) `model_request` frames and the promoter (TR-D2, TR-D3); (c) kernel hook ports and the hook
callback on this lane (TR-D4); (d) subagent facts and nested points (TR-D5); (e) environment
manifest and `workspace_checkpoint_ref` (TR-D8); (f) frontier closure, family position carry
and the precise fork CLI (TR-D12, TR-D13, TR-D14); (g) retention policy (TR-D1) as a migration in
the next release; (h) the completion and lifecycle writers (TR-G9, the rollover event);
(i) the read model: transcript `--by`, frames-by-point, artifact download, stream `point_ref`,
persisted projection, `replay --dry-run` (TR-D10, TR-D11); (j) the remote-saver outcomes (TR-D15).

Proofs on T0 (sibling of `test_cognition_points.py`, scripted cognition, the §1 mission as a
four-stage fixture with one cycle, one sync subagent and one inject; the four FX-DA tests stay
green):

- **FX-TR-STEP**: every step of the fixture answers the six questions from Postgres with the
  saver container stopped.
- **FX-TR-REPLAY**: `replay --dry-run` at a tool-calling step reproduces the model input byte for
  byte against the live saver before it is stopped.
- **FX-TR-SUB**: a sync subagent's spawn, steps and finish appear under the parent step.
- **FX-TR-HOOK**: a catalog hook's invocation and result are frames and a kernel usage hook
  writes usage.
- **FX-TR-RETAIN**: expiry at the new policy keeps every frame the Transcript needs.
- **FX-TR-RECONCILE**: a crash between result and points is repaired by `--reconcile`.
- **FX-TR-FORK-CYCLE**: fork from Stage 2 cycle 2 at an intermediate point with an injected
  message: the derived run reuses S1 by ref (with `reused_from`), does not re-run S2 cycles 0
  and 1, starts S2 at cycle 2 from the copied conversation plus the message, invalidates S3 and
  S4 by closure, and its Transcript names the source point.
- **FX-TR-FORK-GD**: fork a Goal Loop at iteration 3 of 5; the derived run does not re-run
  iterations 1 and 2 with cognition.
- **FX-TR-REMOTE**: with the saver reachable only through a latency-injecting proxy (or stopped
  at settlement), settlement yields the typed outcome and the reconciler completes the points.

Document: the ledger entry in `providers/deep_agents/CHANGES.md`; the knowledge concepts
(`provider-frames-and-transcript`, `events-and-commands`, `recovery`, `deep-agents-lane`,
`execution`); ADR candidates (the Transcript as the replayable record; retention follows the
mission; agents never write tables; the precise fork with frontier closure and family
position); `validate_okf.py`, `agents_docs_index.py`. Then re-sequence: the output-contracts and
context-transfer session follows, with TR-G11 as its first item.

End with one finished part to read, the sequence it sits in, and one command with what the
owner will see (`missionctl run transcript RUN --by step --point ID --full`, then
`missionctl run fork RUN --at stage:S2,cycle:2 --point ID --inject msg.json`).

### 20. Gap register (ranked by what blocks the §0 bar)

| # | Gap | Severity | Evidence |
| --- | --- | --- | --- |
| TR-G1 | No model-input record (system prompt, prompt, messages sent); inputs exist only in the saver | blocks replay | `adapters/deep_agents/frames.py:509-563`; `adapter.py:217-271` |
| TR-G2 | Full bodies never promoted: no promoter wired; tool results and messages above 8 KiB are digests; transcript `--full` is dead | blocks replay | `application/frames/writer.py:39-72`; `domain/frames/contracts.py:34` |
| TR-G3 | Retention deletes non-closing frames after 30 days | destroys the Transcript | `M/0027_provider_frames.sql:118-132,205-216` |
| TR-G4 | Kernel hook ports are Null on Deep Agents in production; hook frames, usage and intents from hooks are not persisted; scripts have no callback | hooks cannot write | `adapters/temporal/deployment_composition.py:778`; `adapters/deep_agents/hooks.py:205-242` |
| TR-G5 | Subagent spawn and finish are not facts; nested namespaces have no points; async children on a foreign saver | steps missing | `adapters/deep_agents/frames.py:188-189`; `cognition_points.py:84-88` |
| TR-G6 | Points written outside the settlement transaction, failure logged; no reconciler | index can be incomplete silently | `application/execution/operations/checkpoint_lineage.py:1224-1235` |
| TR-G7 | `mission_event.activation_id` NULL; transcript entries have no point id; frames have no `point_ref`; frame placement is by time | levels cannot be joined | `adapters/postgres/run_control/canonical.py:557,733`; `domain/frames/transcript.py:59-89` |
| TR-G8 | Environment: no per-step workspace snapshot; sandbox-backend files invisible to `state-as-of`; `workspace_checkpoint_ref` NULL; the harness snapshot is emulated | environment unknown | `adapters/deep_agents/materializer.py:911-931`; `deep_agents_harness.py:264-284` |
| TR-G9 | Lifecycle: no typed "released by" fact; `completion_decision`, `completion_candidate`, `journal_segment` have no writer; the Goal Loop rollover writes no event | lifecycle incomplete | `M/0003_execution.sql:318-441`; `adapters/temporal/workflows/goal_directed.py:127-132` |
| TR-G10 | Reads: no artifact download, no frames-by-point, no lineage endpoint, no `--reconcile`, the transcript is an on-demand view with hard limits | reading is partial | `interfaces/http/ingress.py:79,90`; `application/frames/transcript.py:62-63` |
| TR-G11 | Submission and output fulfilment not checked (the queued session's output contracts) | fulfilment unknown | `docs/knowledge/completion.md:21` |
| TR-G12 | Everything above is `deep_agents` only (time travel composed for one lane) | other lanes later | `bootstrap/api.py:307-327` |
| TR-G13 | Fork at a cycle above zero is admitted and mis-targeted (derived unit keeps the cycle ordinal, derived family starts at cycle 0, family position unconsumed); the frontier does not close over dependants; reused units have no Transcript provenance | precise fork absent | `domain/policies/forks.py:444-495,525-531,576-631`; `domain/programs/interpreter.py:111-112`; `application/recovery/run_forks.py:475`; `operation_execution.py:2274-2295` |
| TR-G14 | Goal Directed units never reused in a fork; the derived run restarts at iteration 1 (F-T4-1) | precise fork absent for Goal Loops | `domain/policies/forks.py:588-591,617` |
| TR-G16 | No retention policy exists for the saver or for degraded points; pruning today is a silent hole (`frame_expired`, generic `cognitive_seed_not_supported`) with no level, policy or alternative reported; see TR-D17 | coordinator cannot reason about what was pruned | `application/frames/transcript.py:526-554`; `application/recovery/cognitive_seed.py:88-120` |
| TR-G15 | The saver is the only holder of cognition state and is about to become remote; nothing names which saver a point lives in beyond a digest the adapter checks | durability and locality | `adapters/deep_agents/persistence.py`; `adapter.py:590,893` |

### 21. Relation to the queued session

The output-contracts and context-transfer session depends on this one for: point ids on every
transfer link, the environment manifest (what a dependent stage actually received), hook ports
(where a submission check can run), the precise fork (a transfer is a fork's reuse seen from
the other side), and the Transcript as the proof surface for FX-DA-TRANSFER and FX-DA-ROLLOVER.
It contributes back TR-G11 (submission and output fulfilment) and the `progress_note` tool if
the owner wants one. Neither session changes the reducers' authority or the Temporal-only
scheduling rule.
