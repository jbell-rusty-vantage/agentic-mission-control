---
type: Specification
title: "Cross-provider control: granular cognition points, time travel and intervention on every lane, shaped like Deep Agents"
description: "Design and work split (2026-11-05) for giving Cursor (local, cloud), Anthropic Managed Agents, the OpenAI Agents API, Codex (local, cloud) and Claude Code (local, cloud) the same control Deep Agents has: one mc.cognition_point.v1 row per observable step of a turn written by the Temporal lane.turn settlement, state-as-of reads, seeded forks (time travel) at the restore level each provider reaches, and intervention (queue, steer or cancel-and-replace, Stop Fence) mapped onto each provider's native lifecycle and hooks."
tags: [mission-control, providers, consolidation, cross-provider, cognition-points, time-travel, interventions, design]
status: active
date: 2026-11-05
---

# Cross-provider control

**Owner goal (2026-11-05).** Mission Control's novel architecture (Temporal workflows wrapping the
Deep Agents LangGraph cycle into granular checkpoints that can be inspected, forked and steered) must
exist for every other provider: Cursor SDK local and cloud, Anthropic Managed Agents, the OpenAI Agents
API, Codex local and cloud, Claude Code local and cloud, in that order. Materializing skills, MCP
servers, subagents, instructions and sandboxes is already general; what is prioritized here is using
each provider's lifecycle and hooks to **write granular checkpoints into our data model and read them
back for forking (time travel) and intervention (queueing and steering)**, across local and cloud.

This document is the shared brief for the agents building it. Read it whole before touching code.

## 1. The reference: what Deep Agents has

| Capability | Deep Agents mechanism | Kernel surface it lands in |
| --- | --- | --- |
| Granular checkpoints | one LangGraph root checkpoint per step; `adapters/deep_agents/cognition_points.py::collect_points` folds them into `CognitionPointObservation`s returned on `RuntimeResult.cognition_points` | `mission_control.cognition_point` (migration 0045/0047, release ≥1.4.4), written in the settlement transaction (`CheckpointLineageService.record_result` → `PostgresCognitionPointRepository.record_points_in`), `written_by: adapter`; enriched by the frame writer; re-derived by the reconciler (`point_reconciliation.py`) |
| State inspection | `adapters/deep_agents/time_travel.py::DeepAgentsTimeTravel.read_as_of` (R3: graph state at the point, redacted) | `TimeTravelRegistry` (`application/execution/harness/time_travel.py`) → `CognitionPointReadService.state_as_of` → `GET /runs/{id}/points/{point}/state-as-of`, `missionctl run state-as-of`, MCP `mission_run_state_as_of` |
| Forking (time travel) | `seed_fork`: copy the thread's lineage to the point into the derived unit's namespace, optionally append an injected human message as the seed head | fork saga (`application/recovery/run_forks.py`) → `CognitiveSeedService` (`recovery/cognitive_seed.py`) → `mc.fork_seed.v1` workflow / `fork_seed.copy` activity on the maintenance worker; the derived run's `fork_seed` point; `run fork --point ID --inject FILE` |
| Intervention | queue (`command_mailbox`, consumed at `next_turn`), interrupt-and-inject (`cancel_and_replace`: cancel, settle uncertain effects, replacement turn on the same thread; the interrupted leaf gets role `interrupted`, the replacement's first checkpoint `replacement_start`), immediate cancel behind the Stop Fence (`FenceStopMiddleware` stops the next model call; every Kernel Hook asks the fence) | `application/execution/harness/inject.py`, `mailbox.py`, `stop_fence.py`; `LANE_COMMAND_SEMANTICS` (`domain/execution/lane_turns.py`); each lane's `describe.delivery_semantics` |
| Transcript joinability | every event and frame names its unit and point | `transcript_entry.point_id`, `mission_event.point_ref` (0047/0048) |

Concepts: [temporal-synthesis](../../../../knowledge/temporal-synthesis.md), [precise-fork](../../../../knowledge/precise-fork.md),
[interventions](../../../../knowledge/interventions.md), [recovery](../../../../knowledge/recovery.md),
[lanes-and-harness](../../../../knowledge/lanes-and-harness.md), [provider-frames-and-transcript](../../../../knowledge/provider-frames-and-transcript.md).

## 2. The data model is already provider-neutral

Nothing new is needed in SQL for the first slice. `mission_control.cognition_point` (0045) keys a row by
`(unit_key, execution_generation, point_kind, point_locator)` with `point_kind IN ('checkpoint',
'session_cursor', 'thread_item', 'workspace_snapshot')` and `lane_profile` as a foreign key; `restore_level`,
`history` (`native | reconstructed`), `subordinate_ref`, `roles`, `frame_from/to_ordinal`, `usage_delta`,
`channel_facts`, `files_digest`, `workspace_checkpoint_ref` and `seedable` are all lane-agnostic.
The domain union (`domain/execution/cognition_points.py`) has `CheckpointPoint`, `SessionCursorPoint`,
`ThreadItemPoint`, `WorkspaceSnapshotPoint`. The Native Event Store (`provider_frame`, 0027/0034/0047) already
holds every lane's frames with `native_session_ref`, `native_turn_ref`, `provider_key`, `arrival_ordinal`.

**Changes landed in this session (shared contracts, 2026-11-05, uncommitted on `main`):**

- `SessionCursorPoint.step_ref` (optional): one point per step inside a turn; locator `session#turn#step`.
  `WorkspaceSnapshotPoint.session_ref/turn_ref` (optional) so a workspace point joins its turn.
- `domain/execution/lanes.py::LaneSeedHead` (`mc.lane_seed_head.v1`) and `seed: LaneSeedHead | None` on
  `PrepareRequest` and `StartRequest`: what a derived unit's first session continues from after a fork of a
  session-lane point (source coordinate, restore level, history, the lane's `native_artifacts`, the injected
  message).
- `domain/policies/forks.py::CognitivePointSeed(unit_key, point)` beside the unchanged `CognitiveSeed(unit_key,
  checkpoint)`; `AnyCognitiveSeed` is the union on `RunForkPatch`, `RunForkRequest`, the HTTP fork body and the
  runtime contract. `CognitiveSeedService.resolve` finds the row by `(seed.kind, seed.locator)` for both forms.
  `missionctl run fork --point ID` sends the `point` form for non-checkpoint points.
- `application/execution/harness/points.py`: the `PointCollectingLane` port (`turn_points(TurnPointsRequest)`),
  `TurnPointsRequest`, and the shared pure fold `frame_boundary_points(...)`: one point per step frame
  (`STEP_KINDS`: `turn_started`, `message`, `tool_call_completed|failed`, `approval_resolved`,
  `after_compaction`, `subagent_ended`, `turn_ended`, `run_result`, `error`), frame keys since the previous
  boundary, running message count, usage delta from `usage` frames, roles `input`/`intermediate`/`leaf`/`result`,
  `replacement_start` when the turn replaced an interrupted one, `parent_locator` chain, `source_point` as the
  first point's parent outside the generation. Default step ref `<arrival_ordinal>:<kind>`; a lane with a
  native per-step id passes `point_for`.

## 3. Kernel plumbing still to build (owned by the Cursor agent, §6)

K1. **Session-lane points at settlement.** `LaneTurnService._settle` (`application/execution/harness/lane_turns.py`):
when `isinstance(harness, PointCollectingLane)`, read the generation's frames (`self._frames_of(identity, generation)`),
build a `TurnPointsRequest` (native refs, turn_no, closing facts, attempt ref, the interrupted turn ref recorded by
`inject.py` when this turn is a replacement, the previous turn's result point as `source_point` via the lineage/points
repository when available) and pass `points=` to `settle_lane_session`. `settle_lane_session` gains
`points: tuple[CognitionPointObservation, ...] = ()` and hands them to `_settle(points=..., points_written_by="adapter")`
(the `_settle` keyword already exists). Cancelled turns (`cancelled_by_command`) write their points too (the leaf gets
`interrupted` when an inject follows; `_settle_fenced_turn` is the Deep Agents precedent). Points are evidence: a
points write failure must not fail the settlement (the savepoint rule of `cognition_points.py` already applies).
Also record each turn's result point on `session_turn.point_ref` the way the frame writer does for Deep Agents, if
the existing enrichment path makes that cheap; otherwise leave a note.

K2. **Seed head for session lanes.** `CognitiveSeedService.seed`: for a non-`CheckpointPoint` head, skip
`seed_namespace_head` (no LangGraph namespace) and instead record the `LaneSeedHead` in the `fork_seed` point's
`channel_facts["seed_head"]` (serialized `mc.lane_seed_head.v1`). `LaneTurnService` start path (`_start`, around
`PrepareRequest(...)`/`StartRequest(...)`): when the unit's generation is 1 and the derived run has a `fork_seed`
point for this unit (`points.list_points(run, unit_key=..., role="fork_seed")`), pass it as `seed=`. Admit seeds at
every declared `time_travel.fork` level ≥ `R1` (not only R3) and record the receipt's `restore_level`/`history` on
the `fork_seed` point (fields exist). Keep the Goal Directed verifier refusal.

K3. **Registry composition.** `_worker_time_travel` (`adapters/temporal/deployment_composition.py`),
`bootstrap/api.py` and `bootstrap/runtime_control.py` register every composed lane's `TimeTravelLane`. Each lane
package exports a factory (`time_travel.py::<Lane>TimeTravel(frames=FrameReader, ...)`), composed in
`provider_lane_composition.py` (Claude, Codex), `hosted_lane_composition.py` (Managed, Agents) and the Cursor
composition; R1/R2 reads need only the frame reader and the snapshot store, R3 seeds need the provider client.
The reconciler (`point_reconciliation.py`) calls `collect_points(namespace=..., checkpointer_ref_digest=...,
source_locator=..., result_locator=...)`; for session lanes `namespace` is the harness execution id and
`checkpointer_ref_digest` the generation (document the convention in the port's docstring).

**Built (Agent A, 2026-11-05; see the [ledger](LEDGER.md) for the proofs):** K1 is
`LaneTurnService._turn_points` → `points.fold_generation_points` (every native turn of the
generation chained; `_replacement_map` from the dispatch journal gives `interrupted` /
`replacement_start`; `_source_point` from the index) → `settle_lane_session(points=)` →
`_settle(points=, points_written_by="adapter", admitted=admit_attempt(...))`. K2 is
`CognitiveSeedService` (fork ≥ R1, `channel_facts.seed_head`, replay of a recorded seed) and
`LaneTurnService._seed_head` → `PrepareRequest.seed`/`StartRequest.seed`. K3 is
`ScopedTimeTravelLane.for_scope` bound by `TimeTravelRegistry.lane(profile, request_scope=)`,
`ForkSeedRequest.request_scope`, `TimeTravelRegistry.register_all`, `scoped_lane(profile,
factory)` for per-scope factories, and `bootstrap/session_time_travel.py::session_lane_time_travel`
registered by the worker, the operator API (`ApplicationFrameReaders`) and the technical API.
`TurnPointsRequest` gained `terminal`, `interrupted` and an optional `operation`;
`frame_boundary_points` gained `interrupted_leaf`, `is_input` (KR2) and `usage_kinds`; KR3
(`_steer` stages the text first) is in. K6 (`session_turn.point_ref` for session lanes) is a note.

K4. **`LANE_COMMAND_SEMANTICS` and describe cells** are edited per lane by its agent (different rows, low
collision risk); `resolve_interrupt_mode` (`inject.py`) already supports `cooperative_inject` through `SteeringLane`.

K5. **Reads.** `CognitionPointReadService.state_as_of` already routes by `record.lane_profile`; nothing to change
beyond registering lanes. `interfaces/http/cognition_points.py` returns the lane's `StateAsOf` as is.

## 4. What every lane delivers (same shape as `adapters/deep_agents`)

For each lane package `adapters/<lane>/`:

1. `cognition_points.py`: `turn_points(TurnPointsRequest)` on the harness (implements `PointCollectingLane`) using
   `frame_boundary_points` with the lane's native identity (`point_for`), usage parser (`usage_of`) and redacted
   facts (`facts_of`). Granularity target: one point per tool call close, model message, approval resolution,
   compaction, subagent end and turn end. Subagents: `subordinate_ref` from the frame when the lane reports one.
2. `time_travel.py`: a `TimeTravelLane` (`lane_profile`, `read_as_of`, `seed_fork`, `collect_points`).
   - `read_as_of` at the level the lane reaches: **R1** = `GraphStateAsOf.messages` reconstructed from the
     frames up to the point (through `FrameReader.frames_for_execution`, bodies redacted with
     `domain/frames/body.py`), `history="reconstructed"`; **R2** = plus `files` from the workspace snapshot the
     lane recorded for that turn (`mc.cursor_snapshot.v1`, the Claude/Codex continuation snapshots, a cloud
     `branch@sha`); **R3** = the provider's own state (a forkable session or thread).
   - `seed_fork`: create the derived unit's native starting state and return `ForkSeedReceipt(restore_level,
     history, derived=CognitionCoordinate(... point=<derived lane point>), native_artifacts={...})`. The
     `native_artifacts` must let the lane's `prepare`/`start` continue from it when handed back as
     `LaneSeedHead.native_artifacts` (never a credential).
   - `collect_points`: re-derive one settled generation's points from the persisted frames (the same fold).
3. `describe.py`: `time_travel=LaneTimeTravel(read=..., fork=...)`, the `fork` control cell, interrupt and queue
   delivery semantics that match what the harness implements; keep every cell honest (`unqualified` where no code
   or no provider surface exists, with the evidence note).
4. Intervention: `SteeringLane.steer` where the provider steers a running turn natively (Codex `turn/steer`,
   Managed Agents `user.message` while running, Agents API input during a turn); otherwise keep
   `cancel_and_replace` and make sure the interrupted turn's last point carries `interrupted` and the
   replacement's first point `replacement_start` (K1 passes `interrupted_turn_ref`). Queueing already exists
   (`turn_boundary_guaranteed` / `wait_then_send`); verify it on your lane in the conformance suite.
5. Tests: unit tests under `tests/unit/<lane>/test_cognition_points.py` (fold from recorded fixture frames; roles,
   parents, usage, message count, step refs), `tests/unit/<lane>/test_time_travel.py` (read_as_of from frames and
   snapshots; seed_fork against the lane's FIXTURE client; idempotent repeat), and the conformance registration
   (`tests/conformance/lanes/adapters/<lane>.py`) for fork emulation / time travel when claimed. Integration against
   real PostgreSQL + Temporal (`make dev`, `tests/integration/<lane>/`) is the stretch goal; it needs Docker
   running, which may not be available in this session: report `blocked` honestly if so.
6. `docs/specs/provider-consolidation-2026-10/providers/<lane>/CONTROL-ARCHITECTURE.md`: the architecture as
   faithfully as possible, even where code could not run: the provider lifecycle and hook events mapped to point
   boundaries, the native identity used as locator, the restore level per read/fork and why, the intervention
   mapping (queue, steer, cancel-and-replace, Stop Fence reach), local vs cloud differences, and an honest
   implemented / tested / integrated / blocked table. Cloud profiles with undocumented lifecycles (`claude_cloud`,
   `codex_cloud`) get architecture only.

## 5. Point identity per lane (fix these so forks and transcript joins are stable)

| Lane profile | Point kind | session_ref | turn_ref | step_ref / item_ref | Fork head (R level) |
| --- | --- | --- | --- | --- | --- |
| `cursor_local` | `session_cursor` (steps) + `workspace_snapshot` (turn close) | SDK `agent_id` | `run_id` | bridge offset of the step frame | new agent in a restored lease from the turn's `cursor-snapshot:` + reconstructed transcript prompt (R2); the SDK has no conversation fork |
| `cursor_cloud` | `session_cursor` + `workspace_snapshot` | cloud `agentId` | `run_id` | SSE event id | new cloud agent on `branch@sha` of the turn + hydration prompt (R2) |
| `claude_managed` | `session_cursor` | `session_id` | user message event id | event id of the step | new session with the transcript replayed as history (R1/R2); R3 only if the API forks sessions |
| `codex_agents` | `thread_item` | `session_id` | `turn_id` | `item_id` | new session seeded with items to the point (R1); R3 if the Agents API supports session forks |
| `codex` | `thread_item` | `thread_id` | `turn_id` | `item_id` | `thread/fork` at the item when the pinned app-server protocol supports it (R3), else `thread/resume` of a copied rollout (R3 reconstructed) |
| `claude_agent_sdk` | `session_cursor` | `session_id` | user message uuid | the step frame's provider key tail | `ClaudeAgentOptions(resume=<session>, fork_session=True)` into a fresh process with the state-root transcript mirror truncated at the point (R3 reconstructed) |
| `claude_cloud`, `codex_cloud` | architecture only | | | | undocumented lifecycle; `unqualified` |

Every lane keeps the Deep Agents rule: the source session or thread is never written by a fork; the derived unit
gets its own namespace (a new session, thread, branch or lease), and repeating the same seeded fork is idempotent.

## 6. Work split and file ownership (three parallel agents, no worktrees)

| Agent | Lanes | Owns exclusively | Must not edit |
| --- | --- | --- | --- |
| A | `cursor_local`, `cursor_cloud` **plus the kernel plumbing K1-K3** | `adapters/cursor/**`, `application/execution/harness/lane_turns.py`, `application/execution/harness/points.py`, `application/execution/operations/operation_execution.py`, `application/execution/operations/point_reconciliation.py`, `application/recovery/cognitive_seed.py`, `adapters/temporal/deployment_composition.py`, `bootstrap/api.py`, `bootstrap/runtime_control.py`, `tests/unit/cursor/**`, `tests/unit/harness/**`, `tests/unit/operations/**`, `tests/conformance/lanes/adapters/cursor.py` | other lanes' packages |
| B | `claude_managed` (Anthropic Managed Agents), `codex_agents` (OpenAI Agents API) | `adapters/anthropic_managed/**`, `adapters/openai_agents/**`, `adapters/remote_session/**`, `adapters/temporal/hosted_lane_composition.py`, `tests/unit/anthropic_managed/**`, `tests/unit/openai_agents/**`, `tests/unit/remote_session/**`, `tests/conformance/lanes/adapters/{managed,agents}.py` | kernel files owned by A |
| C | `codex`, `codex_cloud`, `claude_agent_sdk`, `claude_cloud` | `adapters/codex/**`, `adapters/claude/**`, `adapters/temporal/provider_lane_composition.py`, `tests/unit/codex/**`, `tests/unit/claude/**`, `tests/conformance/lanes/adapters/{codex,claude}.py` | kernel files owned by A |

Shared rows (one line each, different rows per lane, keep edits minimal and additive): `domain/execution/lane_turns.py::LANE_COMMAND_SEMANTICS`,
`application/frames/kinds.py` (new raw kinds if a lane maps new events), `tests/conformance/lanes/registry.py`.
When B or C needs a kernel change beyond §2, write it under "Kernel requests" in their CONTROL-ARCHITECTURE.md with the
exact file, function and reason; do not edit A's files. B and C can test their `turn_points` and `time_travel`
pure code and FIXTURE clients without K1-K3; wiring into `_settle` and the registries is A's (and the integrator's).

Agent A also touched, additively, three kernel files outside the table (one line or one helper each,
recorded in the ledger): `application/execution/cognition_points.py` (`compose_points` derives a
cross-kind parent id with the parent's kind), `application/execution/cognition_point_reads.py` (the
read service binds the lane to its scope) and `adapters/temporal/activities/fork_seed.py` (the
activity binds the lane to the request's scope); and `tests/fixtures/lane_turns.py`
(`lane_stack(points=)`), `tests/integration/temporal/test_lane_turn.py` (a points proof) and a new
`tests/integration/postgres/test_session_lane_points_postgres.py`.

Each agent writes `docs/specs/provider-consolidation-2026-10/providers/<lane>/CONTROL-ARCHITECTURE.md` and appends a
section to `docs/specs/provider-consolidation-2026-10/providers/cross-provider-control/LEDGER.md` (create if absent):
what was implemented, tested (command + result), integrated, blocked, and the kernel requests.

## 7. Verification floor

Per agent: `uv run ruff check <files>`, `uv run ruff format <files>`, `uv run mypy <touched modules>`,
`uv run pytest tests/unit/<lane> tests/conformance/lanes -q -p no:cacheprovider` (unit tests run on this Windows
host; `make check` as a whole may take long, run it when the lane is done). Paid provider calls are **not
authorized** in this session; FIXTURE clients only. Integration suites need `make dev` (Docker); report blocked
if Docker is not running rather than skipping silently.

## 8. Reporting (owner reporting directive)

Lead with what remains to reach the goal (the same control on every lane), which gap this work closes, and
the next blocker or proof. Distinguish implemented, tested, integrated and qualified. No activity counts, no
percentages. Name the finished part to read, the test that proves it and the sequence it sits in.
