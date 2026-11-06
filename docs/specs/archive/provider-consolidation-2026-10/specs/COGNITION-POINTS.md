---
type: Specification
title: "P1 deep_agents turn 4 packet: the cognition coordinate (model, write, read), forks from a point, intervention into running cognition, Goal Directed continuation and Stage Graph cycles with Deep Agents inside, and the skill-origin audit (plan for owner confirmation, 2026-10-21)"
description: "Turn 4's plan, written after the audit of main at b1427b7b. Starting state with citations; the proposed data model (one cognition_point table for both families, the mc.cognition_coordinate.v1 contract with its discriminated point union), its writers (the Deep Agents adapter at settlement, the frame recorder, a reconciler from the saver) and readers (read_as_of lane port, operator HTTP, CLI and MCP); fork from a point by thread copy and branch in the copy; intervention delivery reports that name points; what Goal Directed continuation and Stage Graph cycles do today and what this turn changes; the skill materialization origin audit (part A); the decisions asked of the owner; the work packages, fixtures and tiers."
tags: [mission-control, providers, consolidation, deep-agents, time-travel, forks, interventions, continuation, P1]
status: archived
archived: 2026-11-02
archived_from: providers/deep_agents/COGNITION-POINTS.md
archived_reason: "built (turn 4); concepts precise-fork and interventions"
---

> **Archived 2026-11-02** (built (turn 4); concepts precise-fork and interventions). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# P1 turn 4 packet: the cognition coordinate

Companion to [DESIGN.md](../../../provider-consolidation-2026-10/providers/deep_agents/DESIGN.md) §3 (positions P1-S4..S6), [AUDIT.md](../docs/AUDIT.md) §5–§6 and
the [ledger](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md). Paths are relative to `src/mission_control/` unless they start with
`tests/`, `docs/`, `scripts/` or `packages/`. Nothing here is built until the ledger says so.

## 0. The goal, in the owner's words

Goal Directed and Stage Graph workflows run with Deep Agents cognition inside. We need one
final way to **model** the coordinate that relates a Temporal workflow, its activity attempt,
the Deep Agents checkpoint and the state at that point; to **write** it as the run progresses;
and to **read** it back as of any point. Then we **fork** from a point, demonstrated. Then we
**intervene** into a running workflow and its cognition, demonstrated. Stage cycles and the
Goal Directed iteration continuation (the context-limit transfer behaviour) must be understood
and the coordinate must survive both. The session after this one does advanced context
materialization and transfer between dependent stages.

## 1. Starting state (audited 2026-10-21, `main` at `b1427b7b`)

### 1.1 What already relates the chain (verified on the drill database, AUDIT §5)

| Link | Persisted today | Where |
| --- | --- | --- |
| Temporal workflow → activity attempt | `activity_attempt_observation` (workflow id, run id, activity id, attempt, worker) | `adapters/temporal/operation_activities.py:150-161` builds it from `activity.info()`; `adapters/postgres/operations/checkpoint_lineage.py:87` records it; `task_queue` is **not** recorded |
| attempt → unit generation | `runtime_unit_generation` (`unit_key`, `execution_generation`, `cognitive_namespace` = thread id, `lease_holder` = observation id) | migration 0012 |
| unit generation → checkpoint lineage | every root checkpoint stamped `belllabs_unit_key`, `_execution_generation`, `_invocation_id`, `_binding_digest`, `_state_schema_digest`, `_attempt_ref` | `domain/execution/checkpoint_lineage.py:31-42, 320-335`; `adapters/deep_agents/adapter.py:300-304` |
| unit generation → source and result | one `checkpoint_transition` per generation (`source_checkpoint_key`, `result_checkpoint_key`, `result_parent_checkpoint_key`, `seedable`) and the namespace head | `adapters/postgres/operations/checkpoint_lineage.py:976-1036` |
| harness execution → session → turn → frames | `harness_execution`, `agent_session` (`checkpoint_namespace`, `checkpoint_ref` always NULL), `session_turn` (`turn_no`, `native_turn_ref` = invocation id; no checkpoint column), `provider_frame` (`langgraph_step` in the key; no checkpoint id) | `adapters/postgres/frames/identity.py:444-473`; `adapters/deep_agents/frames.py:173-205` |
| run → Temporal root | derived, never written (`mission_run.temporal_workflow_id/run_id` NULL) | AUDIT §5 |

The saver (`mission_control_runtime.checkpoints`, `metadata jsonb` with the stamps and
LangGraph's `step` and `source`) holds every intermediate point. Reads below the unit exist only
in the technical facade: `GET /runs/{id}/units/{unit}/checkpoints` and
`.../checkpoints/{id}/summary` (`interfaces/http/runtime_inspection.py:145-194`, mounted at
`bootstrap/technical_api.py:259`), over `LangGraphCheckpointHistoryReader`
(`adapters/deep_agents/checkpoint_history.py`), which folds the `messages` delta channel into
identities (counts only, `_fold_delta`).

### 1.2 Goal Directed with Deep Agents inside (the continuation behaviour)

- Every iteration's executor and verifier run at **execution generation 1** and continue **one
  shared thread per role per session generation**
  (`belllabs/goal/{run}/epoch/{e}/session/{sg}/role/{role}`,
  `domain/execution/checkpoint_lineage.py:133-145`). The pin is implicit: `record_attempt` sets
  `expected_source` to the namespace head the previous same-role unit left
  (`adapters/postgres/operations/checkpoint_lineage.py:221`), so iteration N+1 starts from
  iteration N's result checkpoint and the thread is one linear lineage (drill: 44 root
  checkpoints, steps −1..20 in two threads).
- The unit key is `goal-iteration/{n}/{role}` plus `agent_run` and `session_generation` hashed
  (`domain/programs/runtime_units.py:35-87`); generation never leaves 1 from the family
  (`adapters/temporal/workflows/goal_directed.py:1755-1789` hard-codes it); the
  `.../unit/{key}/gen/{N}` namespace is reachable only through an operator
  `start_new_generation` decision.
- **Session rollover is a token counter**, not a measurement: `session_token_usage` sums the
  executor's settled `tokens.total`; at the iteration boundary, if it reaches
  `fresh_agent_token_threshold` (100 000) and `rollover_count >= max_rollovers`, the family
  **fails** (`domain/programs/goal_directed.py:370-382`). Manifest lowering hard-codes
  `max_rollovers=0` (`domain/authoring/manifest_lowering.py:253-259`, K02), and no manifest
  field sets the threshold. A rollover, when allowed, bumps `session_generation`, resets the
  counter, and the next claim's roles start **fresh threads** seeded by the iteration packet
  (`HANDOFF.md`, `checkpoint.json`, loop state) — `fresh_from_handoff` is the only mode that
  does anything; `claim.session_mode` is never read.
- Native compaction (`ObservedSummarizationMiddleware`) runs inside the thread and is observation
  only; `ContextPressurePolicy` is consulted only by the segment loop
  (`application/execution/harness/lane_turns.py:2209-2323`), which Deep Agents does not use by
  default (`MISSION_CONTROL_LANE_SEGMENT_LOOP=false`), and `DeepAgentsHarness` reports no
  occupancy. `DeepAgentsSessionHydrator` and `StateBackendWorkspaceSnapshots` are constructed only
  in tests; `request_continuation` on this lane is recorded and never driven (ADR 0041
  consequence). The describe's `request_continuation: emulated` is not backed by a registration.
- Verifier findings never reach the next executor's packet (K04); a missing executor handoff
  silently re-sends the previous one.
- Continue-As-New carries the counters (`session_generation`, `rollover_count`, handoffs) and
  never moves them; unit keys and namespaces are byte-identical across segments.

So the "context limit transfer" that exists for this lane is the **iteration-boundary session
rollover from the handoff packet**, and it is unreachable from a manifest because the cap is 0.
Mid-iteration transfer (K03, ADR 0039/0041 phase machine) has no Deep Agents hydrator registered
and no safe boundary inside the governed activity.

### 1.3 Stage Graph with Deep Agents inside (cycles)

- A stage has no back-edge. A cycle is an **invalidation**: `evaluation: "cycle"` from a stage
  or a Human Gate `request_changes` → `stagegraph.apply_cycle` → the cycling stage and its
  descendants get **new candidates** with `stage_cycle_ordinal + 1` (stage scope) or
  `workflow_cycle_ordinal + 1` (workflow scope) (`domain/programs/interpreter.py:586-675`).
- Both cycle ordinals are part of the unit identity (`StageGraphUnitLocation`,
  `domain/graph_runtime/identities.py:147-155`) and of `semantic_operation_id`, so **each visit
  is a new unit key at generation 1 in a fresh thread** `belllabs/stage/{unit_key}/gen/1`.
  Nothing carries the previous visit's conversation; `prior_result_refs` and
  `unmet_obligation_refs` are computed (`interpreter.py:562-583`) and never delivered (K05); the
  cap raises `StageGraphExecutionError` instead of settling (K05); no manifest path sets a cycle
  policy. Declared waits are keyed by `wait_id` alone, so a re-entered gate stage is not held
  again (inferred, untested).
- Dependent input: `pack_for_stage` binds the producer's **latest accepted result across all
  cycles** as `/inputs/<binding>/` files (`application/context/pack_service.py:304-388`,
  `interpreter.py:1179-1191`), one `context_selection` row per
  `(run, activation = operation id incl. cycle ordinals, attempt, generation, purpose)`.

Consequence for the coordinate: cycles and iterations are **filters over unit identity**, not a
second lineage dimension. One table serves both families if it denormalizes the location.

### 1.4 Forks and interventions today

- Forks: snapshot at a safe boundary → `SemanticForkService.prepare` → derived run admitted with
  reuse decisions → `fork_seed` writes a `queue_instruction` and an `add_context{workspace}` into
  the derived mailbox. `cognitive_seed` is refused `cognitive_seed_not_supported`
  (`domain/policies/forks.py:491-496`). A reused unit settles from the source manifest without
  cognition and without a transition (`operation_execution.py:2265-2291`), so the derived
  namespace has no head and the first invalidated unit starts a fresh thread (R0/R1).
- The drill's fork returned 403 because the fixture grant lacks `workflow_run.control`, which a
  fork **with an instruction** needs (`application/missions/runtime.py:94-105`; P1-A6).
- Intervention: `interrupt_and_inject` on Deep Agents is `cancel_and_replace`
  (`application/execution/harness/inject.py:161-258`): cancel the task, settle uncertain effects,
  run a replacement `execute` with `invocation.follow_up`; the adapter continues the interrupted
  leaf with one more user message (`adapter.py:254-312`). Proven on time-skipping Temporal with
  in-memory stores (`tests/integration/temporal/test_ft_f2_inject.py`), never on the production
  stack, and the delivery report names turns (`turn:N`), not points. `queue_instruction` and
  `add_context` are delivered at `next_turn` / `next_iteration` boundaries.
- The saver supports `acopy_thread(source, target)` (`langgraph/checkpoint/base`, "the copy must
  carry the complete parent chain") and `stream_mode="checkpoints"` emits a part per created
  checkpoint (`langgraph/types.py:121-131`), which the frame recorder does not consume yet.

## 2. The model: `mc.cognition_coordinate.v1` and `cognition_point`

### 2.1 Position (restates P1-S4/S5, accepted as the plan)

The provider lifecycle is indexed, not abstracted. The kernel owns the **coordinate**, the
**table** and the **two behaviours** (`read_as_of`, `seed_fork`); the lane owns what a point
*is* and how its state is read or copied.

```text
CognitionCoordinate                       lane-neutral
  run_id, unit_key, execution_generation
  harness_execution_id?, turn_no?
  point: discriminated by `kind`
    checkpoint         {thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpointer_ref_digest}   deep_agents
    session_cursor     {session_ref, turn_ref}                                                                     claude_agent_sdk, hosted
    thread_item        {thread_ref, item_ref}                                                                      codex
    workspace_snapshot {snapshot_ref}                                                                              cursor_local, cursor_cloud
```

For a lane without provider-side state (Cursor SDK) the coordinate's substance **is** our
`session_turn` plus the `provider_frame` range plus the workspace snapshot; the `lane.turn` loop
advances it. That is the `workspace_snapshot` point kind with `turn_no` set; nothing else is
invented for those lanes this turn (assumption A4 below).

### 2.2 The table (migration 0045, release 1.4.3)

One tenant table `mission_control.cognition_point`, forced RLS, runtime INSERT/SELECT, a
column-limited UPDATE for the reconciler, no deletes except retention (K11 pin).

| Column | Meaning | Source |
| --- | --- | --- |
| `point_id uuid PK` | `uuid5(scope, unit_key, generation, kind, locator)` | kernel |
| `run_id`, `unit_key`, `execution_generation` | the unit generation (FK `runtime_unit_generation`) | binding |
| `family`, `node_key`, `iteration`, `cycle`, `session_generation` | denormalized location for filters: `stage_id` or `operation_role`; `workflow_cycle_ordinal` or `goal_iteration`; `stage_cycle_ordinal` or 0; GD session generation | `RuntimeUnitIdentity.location` |
| `lane_profile`, `point_kind`, `point_ref jsonb`, `point_locator text`, `parent_point_id` | the lane's exact point (`QualifiedCheckpointKey` for Deep Agents) and its parent | lane |
| `ordinal`, `source` | LangGraph `metadata.step` and `source` (`input`, `loop`, `update`, `fork`) | lane |
| `roles text[]` | `source`, `result`, `leaf`, `intermediate`, `interrupted`, `replacement_start`, `fork_seed` | kernel |
| `harness_execution_id`, `turn_id`, `turn_no` | the session turn the point belongs to | frame identity |
| `activity_attempt_observation_id`, `temporal_workflow_id`, `temporal_run_id`, `temporal_activity_id`, `activity_attempt`, `task_queue` | the attempt that wrote it (from the `belllabs_attempt_ref` stamp; Temporal ids denormalized so one row answers) | attempt observation; `task_queue` is new on `activity_attempt_observation` too |
| `frame_from_ordinal`, `frame_to_ordinal` | frames recorded while this step ran (arrival ordinals in the execution) | frame recorder |
| `message_count`, `channel_facts jsonb`, `files_digest`, `usage_delta jsonb` | redacted facts (`RedactedStateFacts` shape; message identities count, file manifest digest, usage between this point and its parent) | saver fold at write time |
| `budget_snapshot jsonb`, `workspace_checkpoint_ref` | optional (K11; NULL on this lane until the per-step workspace checkpoint exists) | kernel |
| `seedable` | `seed_fork` may use it: stamped, verified, not pending an interrupt, lineage settled | kernel |
| `written_by` (`adapter`, `frame_writer`, `reconciler`, `fork_seed`), `recorded_at`, `version` | provenance of the row | kernel |

Unique on `(scope, unit_key, execution_generation, point_kind, point_locator)`; indexes on
`(scope, run_id, family, node_key, iteration, cycle)` and `(scope, run_id, recorded_at)`.

Dead columns filled by the same migration's writers: `session_turn.point_ref jsonb` (new),
`agent_session.checkpoint_namespace/checkpoint_ref` (existing), `mission_run.temporal_*`
(existing, written at launch), `activity_attempt_observation.task_queue` (new).

### 2.3 Writers (where in the sequence)

```text
operation.execute activity (adapters/temporal/operation_activities.py:150)   ← attempt + task_queue
  └ OperationExecutionService._dispatch_and_settle
      └ DeepAgentsHarness.execute → DeepAgentRuntimeAdapter.execute
          ├ recorder consumes astream v2 parts incl. the new "checkpoints" mode   ← step → checkpoint id, frame ordinals per step
          └ _capture_result walks result→source                                   ← CognitionPointCollector folds every stamped root checkpoint
      └ RuntimeResult.cognition_points (additive)                                  ← lane-neutral tuple of CognitionPointObservation
  └ _settle → lineage.record_result(plan, capture, points)                         ← one transaction: transition, result, points (written_by=adapter)
Frame identity writer (_close_turn)                                                ← session_turn.point_ref = result key; agent_session.checkpoint_*
Reconciler (missionctl run points --reconcile; operation.cancel path)             ← rows from the saver for lineages a crash left unsettled (written_by=reconciler)
```

Router rule respected: the settlement does not know what a point is; it stores the tuple the
lane returned. Only `adapters/deep_agents/cognition_points.py` interprets a `checkpoint` point.

### 2.4 Readers

- `GET /v1/applications/{app}/runs/{id}/points` with filters `unit_key`, `iteration`, `stage`,
  `cycle`, `role`, `session_generation`, `kind`, paging (`workflow_run.read`). Operator API, MCP
  `mission_run_points`, `missionctl run points RUN [--iteration N] [--stage S] [--cycle C]
  [--role R]`.
- `GET .../runs/{id}/points/{point_id}/state-as-of` → `mc.state_as_of.v1`: the coordinate, the
  attempt, the frames range, usage to that point, `restore_level` reached, and the lane's state
  read: messages (identity, role, tool names; bodies per decision Q2), files (path, digest),
  channel facts. Permission `workflow_run.read_checkpoint_summary` for facts, a new
  `workflow_run.read_checkpoint_state` for bodies. CLI `missionctl run state-as-of RUN --point
  ID [--bodies]`, MCP `mission_run_state_as_of`.
- Lane port `TimeTravelLane` (`application/execution/harness/time_travel.py`): `read_as_of`,
  `seed_fork`; registry keyed by lane profile (one router), Deep Agents implementation in
  `adapters/deep_agents/time_travel.py` over the saver's delta fold; describe declares
  `time_travel: {read: R3, fork: R3}`.
- The technical facade's per-unit history becomes a view over the table and is mounted on the
  operator API (K15, P1-A1).
- Events: `provider_frame` server events and `mc.realtime.v1` gain `lane_profile` and `point_ref`
  (additive) so a coordinator can jump from a `tool_call` to its point (ADR 0040).

## 3. Fork from a point (P1-S6, WP-2)

`ForkRequest.cognitive_seed` is admitted when the source unit's lane declares
`time_travel.fork >= R3` and the named point row is `seedable`. After the fork saga admits the
derived run and before `fork_seed` writes the mailbox, the kernel calls `seed_fork` for the
derived unit whose identity it already computes (`derived_unit_identity`): Stage Graph →
`belllabs/stage/{derived_unit_key}/gen/1`; Goal Directed → the derived role thread
`belllabs/goal/{derived_run}/epoch/1/session/{sg}/role/{role}`.

Deep Agents `seed_fork` (recommended, Q1): `acopy_thread(source_thread, derived_thread)`, then
`aupdate_state` **in the copy** at point X with the patch (an added human message, extra `files`,
an edited `artifact_index`) as the last node, stamped with the derived unit's metadata, producing
X'. The derived namespace head is set to X' (`cognitive_namespace` + a `cognition_point` row with
role `fork_seed`, `parent_point_id` = X, `source = fork`). The derived unit's first attempt then
classifies `not_submitted` with `expected_source = X'` and submits its packet pinned to X', so its
first model call sees the copied conversation plus the patch. The source thread is never
written. Lineage records `restore_level: R3` with the source coordinate. Fallback if the
Postgres saver's `acopy_thread` does not carry the `messages` delta history: reconstruct a fresh
thread with the folded values at X through `aupdate_state(as_node="__start__")` (the hydrator's
pattern), recorded as `restore_level: R3, history: reconstructed`.

Goal Directed detail: the derived run re-runs from iteration 1 with iteration-1 units reused by
ref (no transition, head untouched), so the first invalidated unit of the role is the one that
pins to X'. The fixture grant gains `workflow_run.control` (P1-A6) so the fork is callable from
the operator API.

## 4. Intervention into running cognition

Demonstrated on the production offline stack (real Postgres 17, real Temporal, production
worker, scripted model with a configurable per-call delay so a turn is long enough to hit):

1. `missionctl command inject RUN --file msg.json` while the iteration-2 executor runs → the
   delivery report says `cancel_and_replace`, and **now names the points**: the interrupted leaf
   (role `interrupted`) and the replacement's first checkpoint (role `replacement_start`,
   `parent_point_id` = the leaf). The thread stays one lineage; `run points` shows both.
2. `missionctl command queue RUN --boundary next_iteration --file note.json` → delivered at the
   next iteration boundary; the point rows of the next unit show the packet-bearing `input`
   point.
3. `cancel --urgency immediate` is already proven (FT-F3); not repeated.

General change: `mc.delivery_report` entries carry `point_ref` where the lane can name one;
nothing else in the intervention path changes this turn (K13/K14 stay open).

## 5. Goal Directed continuation with Deep Agents inside: what this turn changes

Decision Q3 picks the scope. Recommended (K02 only, proven on T0):

- `continuation` on the manifest (v2 block already parsed, ignored for this lane) lowers to
  `GoalSessionRolloverPolicy`: `fresh_agent_token_threshold`, `max_rollovers` (default 3), the
  rest unchanged; the hard-coded `max_rollovers=0` goes away. Crossing the threshold with
  rollovers left **rolls** (session generation + 1, fresh role threads seeded by the handoff
  packet) and records a `session.rollover` fact; exhausting the cap pauses with a receipt instead
  of failing the family (the existing `compaction_failure_action=pause` path).
- Points make the rollover visible: `session_generation` changes between iteration 1 and 2 rows,
  and the iteration-2 executor's `input` point has no `parent_point_id` (fresh thread) with
  `parent_coordinate` recorded as the previous session's result point (a **cross-thread link**,
  the general shape every lane's transfer will use).
- Production composition registers the Deep Agents hydrator and `StateBackendWorkspaceSnapshots`
  so `request_continuation` on this lane stops being a label; driving it mid-iteration (K03) is
  WP-4 and stays open.

Not this turn: measured occupancy on this lane, mid-iteration transfer, verifier findings in the
packet (K04). All are recorded in the ledger's honest list.

## 6. Cycles: what this turn changes

Nothing in the cycle mechanics. The point table denormalizes `cycle` and `iteration` so
`run points --stage review --cycle 1` works, and the Stage Graph T0 proof (FX-DA-POINTS-SG)
asserts one row per root checkpoint of each stage unit with its attempt and frame range. The
cycle deliveries and the governed cap (K05) go with the next session's context-transfer work,
where "what a re-run stage receives" is the same question as "what a dependent stage receives".

## 7. Part A: skill materialization origins (audit only)

Claim audited: "every lane materializes a Skill from custody by digest, never from the origin".
**False end to end.** No code reads `source_provenance.source` at run time; the origin enters
through locators and inline bytes:

| Stage | Reads from | By digest | Origin visible |
| --- | --- | --- | --- |
| Publish (`seeds_publish_bundles.py`, `missionctl catalog publish`) | local directories → ADR 0024 paths | yes | provenance only |
| Publish (`scripts/publish_skill_bundle.py`, `register_supabase_skill_bundle.py`) | local directory → an older hash-only layout, not ADR 0024 | yes (other scheme) | no provenance recorded |
| Admission (`POST /control-plane/definitions`, `/drafts/publish`) | any definition JSON | `manifest_digest` only | yes: `bundle_ref.uri` may be `workspace://` (the coordinator skill is published that way, `application/coordinator/coordinator_surface_promotion.py:59-90`) |
| Compile / pin | catalog digest + deployment pin file; `bundle_ref` never consulted | definition digest | not checked |
| Deep Agents mount | pin file → `workspace://.agents/skills/agent-browser` read at worker start (`adapters/capabilities/capability_pins.py:204-207`, `infra/capability-pins/research-capabilities.json`); a `capability-bundles://` pin falls back to `.runtime/capability-bundles` (`:186-189`) | `bundle_digest`, not the row's manifest | **yes** |
| File lanes | catalog row → `BundleMaterializer` → ADR 0024 paths with per-file checks | yes | no, except `mc-signals` written from package source when no row provides it (`projections.py:519-520`) |
| Hosted lanes | catalog rows from custody **plus inline skill bytes** from checked-in packs (`adapters/remote_session/projection.py:136-148, 178-188`) | rows yes; inline no | **yes** |

Acquisition entrypoints today: the seed publisher, `missionctl catalog publish`, the two older
scripts, `pin_research_capabilities.py`, `promote_coordinator_surface.py`, the definitions
routes and the checked-in hosted packs. None acquires through `npx skills add`, `git clone` or
the MCP registry; those are discovery only (`adapters/capabilities/npx_skills_discovery.py`).

Options (Q4): **O1 (recommended)** custody is the only materialization source: pins carry only
`capability-bundles://` manifests resolved through `BundleMaterializer` and must equal the
catalog row's `manifest_digest`; compile refuses a row whose `bundle_ref` is not custody; hosted
packs' skills become rows; `npx skills` and GitHub become **acquisition** commands
(`missionctl catalog acquire --from npx:<pkg>|git:<url>@<sha>`) that import into custody as a
reviewed draft with provenance, commit digest and license, then publish. Recorded this turn,
built in a dedicated turn. **O2** keep workspace origins as a development mode that the
materialization receipt reports `degraded: origin_workspace`. **O3** leave as is.

## 8. Decisions asked (2026-10-21)

| ID | Question | Recommendation |
| --- | --- | --- |
| Q1 (P1-D1 + P1-D2) | Accept the coordinate, the point union and `cognition_point` as the kernel index, and `cognitive_seed` forks by thread copy + branch in the copy for lanes declaring R3 | accept both |
| Q2 | What `state-as-of` returns for messages | identities, roles and tool names by default; redacted bodies behind a new `workflow_run.read_checkpoint_state` permission |
| Q3 | Scope beyond WP-1, WP-2 and the intervention demo | add K02 (authorable threshold and `max_rollovers`, crossing rolls, cap pauses) proven on T0; K03 stays open |
| Q4 | Part A disposition | O1, recorded now, built in a dedicated turn |

**Answers recorded 2026-10-21 (owner):**

- **Q1: accept both.** The index and copy-and-branch forks are built; folded-state reconstruction
  is the recorded fallback only if the Postgres saver's thread copy drops the delta history.
- **Q2: no new permission; make the read useful.** The owner's words: permissions gate the HTTP
  route and therefore the CLI; "we can start creating permissions but don't overcomplicate it";
  for Deep Agents cognition "we should be reading some form of the graph state with certain
  things hidden"; "make sure the state-as-of and generally these state inspections are robust
  and useful". Disposition: the existing `workflow_run.read_checkpoint_summary` gates
  `state-as-of` in full. It returns the graph state at the point with secrets and oversized
  content hidden, never counts only: messages with id, role, name, tool calls (name, arguments
  under an excerpt cap) and content text through the frame body redactor and excerpt cap with
  digests; files with path, size and digest; the `todos`, `artifact_index`,
  `child_result_index`, `context_manifest` and `skills_metadata` channels as redacted values;
  pending tasks and interrupts; step, source and stamps; the attempt, frame range and usage.
- **Q3: add K02**, proven on T0; K03 stays open.
- **Q4: O1**, recorded now, built in a dedicated turn (the six leaks of §7 go to the ledger's
  register as P1-A8..A13).

Assumptions stated unless the owner objects:

- **A1** Release `1.4.3` under `packages/mission-control-db-contract/releases/1.4.3/component`
  with `0045_cognition_points.sql` and `0046_lane_describe_subagent_fields.sql`; the common-db
  test fixture and the offline stack install the **newest release** (today they install the
  frozen 1.4.0 tree); deployment locks are untouched.
- **A2** Q8 (decided): `LaneSubagents.fields` and `LaneDescribe.time_travel` are additive,
  digest-neutral (`exclude_if`) fields valid on v1 and v2; 0046 is generated by a generalized
  `lane_describe_refresh.py` (`--migration`, `--profiles`), refreshes the eight unqualified rows
  with the exact-prior-literal guard of 0042, and the qualified `deep_agents` row under an
  explicit guard; `deep_agents` stays v1 and qualified this turn (v2 evidence is WP-8).
- **A3** Spend: T0 only, zero. No real model is needed for any proof; F-T3-1 still blocks a real
  Goal Directed run and is not fixed here.
- **A4** Lanes without native persistence: `session_turn` + `provider_frame` range +
  workspace snapshot is the point; the Cursor adapter is not touched this turn.
- **A5** Frames: the recorder adds `stream_mode="checkpoints"` to key every step's frames by
  checkpoint id (`provider_key` already reserves the slot); `session_turn.point_ref` is written
  at turn close.

## 9. Work packages, order and proof

| WP | Builds | Proof | Tier |
| --- | --- | --- | --- |
| T4-0 | Release 1.4.3 skeleton; 0045; 0046 + generator; describe fields; fixture root → newest release; `test_lane_contracts` extended; release-build on the disposable cluster | package tests, `test_run2_release_143`, conformance | T0 |
| T4-1 | `mc.cognition_coordinate.v1`, `cognition_point` repositories (Postgres, in-memory), adapter collector, settlement writer, reconciler, frame `checkpoints` mode, turn/session/run dead columns, operator `points` + `state-as-of` (HTTP, CLI, MCP), `TimeTravelLane` port + registry, stream `point_ref` | **FX-DA-POINTS** (GD: every root checkpoint of iteration 2 has one row with attempt, frame range, message count; `state-as-of` returns the saver's identities) and **FX-DA-POINTS-SG** (stage 2) on the production offline stack as acceptance tests | T0 |
| T4-2 | `seed_fork`, Deep Agents copy + branch, policy lift for R3 lanes, lineage `restore_level`, fixture grant | **FX-DA-FORK**: fork from (iteration 2, executor, step K) with one added message and one file; derived first checkpoint's parent is the copied point; derived executor's first model call sees the message | T0 |
| T4-3 | Intervention demo: scripted-model delay, delivery report `point_ref`s, drill script | **FX-DA-INJECT**: inject mid-turn on the stack; points show interrupted leaf and replacement start; queued instruction at `next_iteration` | T0 |
| T4-4 (Q3) | K02 authorable rollover; hydrator registration; cross-thread `parent_coordinate` | **FX-DA-ROLLOVER**: threshold 30 tokens on the scripted model; iteration 2 runs in session generation 2 with fresh threads and the handoff packet; points link across threads | T0 |
| T4-5 | Ledger, knowledge concepts (`deep-agents-lane`, `recovery`, `context-and-continuation`, `interventions`), docs index, OKF validation, `NEXT-SESSION.md` | — | — |

Host rule: one heavy job at a time (2.8 GB free at audit time); the full unit sweep is not run
beside the live stack.

## 10. Built (2026-10-21)

T4-0 to T4-3 are built and proven on the production offline stack; T4-4 (K02) is built and
proven at the interpreter level (the live rollover needs an executor handoff the scripted fixture
does not emit). The ledger entry in [CHANGES.md](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md) ("Turn 4") lists every change with
its finished part and proof, the findings F-T4-1..3 and the honest list. Differences from the
plan above: the frame range is resolved by the repository from the step's provider keys (not
written by the frame writer); `state-as-of` needs no new permission (Q2); the intervention's
delivery report keeps turn refs and the point rows carry the roles (F-T4-3); the reconciler, the
stream `point_ref`, K11's budget and workspace refs, and the cross-session `rollover_start` link
are declared and not yet written.
