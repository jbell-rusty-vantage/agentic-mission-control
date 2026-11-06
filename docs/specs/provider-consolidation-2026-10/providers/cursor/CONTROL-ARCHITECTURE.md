---
type: Specification
title: "Cursor control architecture: cognition points, time travel and intervention on cursor_local and cursor_cloud"
description: "How the Cursor lanes (cursor-sdk 1.0.37 bridge on a worker; Cloud Agents API v1) write one session_cursor point per step of a run from their persisted frames plus the turn-close workspace_snapshot, read state as of a point and seed forks at R2 (reconstructed transcript plus the turn-close snapshot or branch head), and map queue, cancel-and-replace and the Stop Fence onto the SDK and the API; with the honest implemented / tested / integrated / blocked table and the kernel notes (K1 to K3, built by the same agent)."
tags: [mission-control, providers, consolidation, cursor, cursor-local, cursor-cloud, cognition-points, time-travel, interventions]
status: active
date: 2026-11-05
---

# Cursor control architecture

Part of [cross-provider control](../cross-provider-control/DESIGN.md) (Agent A, 2026-11-05).
Lane concept: [cursor-lane](../../../../knowledge/cursor-lane.md). Kernel conventions this
lane and every other session lane follow: [DESIGN §3](../cross-provider-control/DESIGN.md#3-kernel-plumbing-still-to-build-owned-by-the-cursor-agent-6).

## 1. What this closes and what remains

Closed: both Cursor profiles now have what Deep Agents has in shape. Every settled turn writes
one `mc.cognition_point.v1` row per step boundary from the persisted frames (the Temporal
`lane.turn` settlement writes them in the lineage transaction, `written_by: adapter`), each
turn's workspace snapshot is a `workspace_snapshot` point joined to the turn, `state-as-of`
reconstructs the transcript to the step and lists the turn-close files (R2), a fork seeded at
any step stages the snapshot and a reconstructed transcript prompt that the derived unit's
fresh lease and agent continue from (R2), and an interrupted turn and its replacement carry
`interrupted` / `replacement_start` from the dispatch journal.

Remaining: the describe-refresh migration for the new `time_travel` cells (integrator, release
1.14.0 / 0073); a `lane.turn` run of a Cursor profile on real Temporal with the Postgres
lineage composed (the kernel proof runs the scripted session lane on Temporal and the Cursor
fold on the in-memory lineage; the Postgres proof writes a Cursor-shaped batch directly); the
owner-run paid drill (OVE-55) that would qualify any of it; `session_turn.point_ref` for session
lanes (kernel note K6); cloud R2 reads need the SCM reader composed (the worker has it, the
APIs do not: they answer R1 with the branch head named).

## 2. Provider lifecycle and hook events to point boundaries

Both profiles persist every provider event as a frame (`adapters/cursor/frames.py`,
`adapters/remote_session/lane.py`); the fold (`adapters/cursor/cognition_points.py::
cursor_turn_points` over the kernel's `frame_boundary_points`) turns the step frames into points.

| Cursor event (local bridge `ObserveRun` / cloud SSE) | Frame kind | Point boundary | Role |
| --- | --- | --- | --- |
| `sdkMessage.type=system` (init), `status`, `step` | `session_init` / `status` | none (folded into the next boundary's frame range) | |
| `send.accepted` (local synthetic), `run.created` (cloud) | `turn_started` | yes | `input` on the first point |
| `interactionUpdate.text-delta`, cloud `assistant` | `message_delta` | none (counted into the next message) | |
| `sdkMessage.type=assistant` / `user` (local) | `message` | yes | `intermediate` |
| `tool_call` `status=running`, `tool-call-started` | `tool_call_started` | none | |
| `tool_call` `status=completed` / `error`, `tool-call-completed` | `tool_call_completed` / `tool_call_failed` | yes | `intermediate` |
| `request` / `request.resolved` (local only) | `approval_requested` / `approval_resolved` | resolved: yes | |
| `summary-started` / `summary-completed` | `before_compaction` / `after_compaction` | after: yes (`source: compaction`) | |
| `turn-ended`, `TurnEndedUpdate` | `turn_ended` | yes; carries the token counts when no `usage` frame exists | |
| `sdkMessage.type=usage` (local) | `usage` | none; its counts become the next boundary's `usage_delta` | |
| `result` / `RunResult` / `run.final` | `run_result` | yes | `leaf`, `result` (last turn of the generation) |
| `error` | `error` | yes (`source: interrupt`) | `leaf` |
| Kernel Hook frames (`hook_invoked`, `hook_result`; local only) | hook kinds | none; folded into the boundary they precede | |
| `end_session` freezes the lease (`cursor-snapshot:<ref>`) / records the branch head (`branch:<b>@<sha>`) | (no frame) | one `workspace_snapshot` point after the result, `closes_turn` = the run | |

Subagents: the local hook `subagentStart`/`subagentStop` reach the frames as hook frames; the
Cursor SDK reports no `subordinate_ref` on run events, so no point names a subordinate (the
fold keeps `subordinate_ref` from the frame when a lane reports one).

## 3. Identity

| Profile | `session_ref` | `turn_ref` | `step_ref` | Provider key the step is read from |
| --- | --- | --- | --- | --- |
| `cursor_local` | SDK `agent_id` | `run_id` | the bridge offset of the step frame (`bridge:<run>:<offset>`); a synthetic frame (`:lifecycle.*`, `:final`) keeps the kernel default `<arrival_ordinal>:<kind>` | `frames.offset_of` |
| `cursor_cloud` | cloud `agentId` | `run_id` | the SSE event id (`sse:<run>:<id>`); `run:<run>:final` keeps the default | `cognition_points.cloud_step_ref` |

Locator: `<agent>#<run>#<step>` (`SessionCursorPoint`); the workspace point's locator is the
snapshot ref. Every step point of a closed turn carries `channel_facts.turn_snapshot_ref`; the
result point carries it as `workspace_checkpoint_ref` so `GET .../state-as-of` and the Workspace
Closure reads find it. The cloud points also carry `repository`, `branch`, `head`.

## 4. Restore levels and why

| Read / seed | Level | Mechanism |
| --- | --- | --- |
| `read_as_of` of a step point | R1 (messages) + R2 files of the *turn's close* | messages reconstructed from the frames of the run up to the point's last frame (`frames.to_ordinal`, else `channel_facts.arrival_ordinal`): assistant text, tool calls with argument digests, tool results, final text, `history=reconstructed`; files from the `mc.cursor_snapshot.v1` manifest (local: paths, sizes, digests; patch digest and base commit in `channels.workspace_snapshot`) or the branch tree at the recorded head (cloud, `SNAPSHOT_ROOTS`, when a branch reader is composed). An intermediate point says in `withheld` that the files are the turn's close. Without a snapshot store (the APIs) the read is R1 and says so. |
| `read_as_of` of a workspace point | R2 | the whole turn's transcript plus the snapshot files |
| `seed_fork` | R2 (R1 when the turn recorded no snapshot) | nothing is written in the source. The lane stages one artifact, the hydration prompt (`HYDRATION_HEADER` + the reconstructed transcript to the point + `[operator] <message>`), and returns `native_artifacts = {snapshot_ref, transcript_ref, source_session_ref, source_turn_ref, source_step_ref, seed_head, seed_head_message_count}` with `derived = WorkspaceSnapshotPoint(snapshot_ref, session_ref, turn_ref)` on the derived run. Idempotent per `(fork_request_id, derived_unit_key)` in the process and content-addressed in the payload store; the seed service replays a recorded `fork_seed` point across processes. |
| `prepare(seed)` / `start(seed)` | | local: the `cursor-snapshot:` is restored into the fresh lease (digest-verified) before the packet's own workspace item, the transcript is read from the snapshot store and sent as the prefix of the first turn (`send_turn`, once). Cloud: the branch starts at the recorded `@<sha>` (`forked_from`), the transcript is read from the artifact reader and prefixed to the create prompt. |

R3 is not reachable: `cursor-sdk 1.0.37` has no conversation fork and the Cloud Agents API no
session copy (the describe says `time_travel=LaneTimeTravel(read="R2", fork="R2")`, `fork`
control `emulated`).

## 5. Intervention mapping

| Intervention | `cursor_local` | `cursor_cloud` |
| --- | --- | --- |
| queue (`queue_instruction`) | `wait_then_send`: the next send at the turn boundary carries it (unchanged, conformance `SEND_TURN_WHILE_BUSY`) | same |
| steer | none native (`SteeringLane` not implemented; the SDK sends a new run only) | none native |
| interrupt_and_inject | `cancel_and_replace` (unchanged): the run is cancelled, Uncertain Effects settle, the replacement run is sent under `<execution>:<generation>:replace:<run>`; **K1 reads that journal key at settlement**, so the interrupted run's leaf carries `interrupted` and the replacement's first point `replacement_start`, chained by `parent_locator` | same |
| immediate cancel / Stop Fence | the fail-closed Kernel Hook (`.mission/hooks/kernel.py`) asks the fence before every gated effect and the loopback callback answers; `lane.cancel` posts the SDK cancel; a cancelled turn still writes its points | **no fail-closed hook**: the cloud VM cannot reach the worker (`fail_closed=False`, catalog command hooks only); the Stop Fence reaches a cloud run only through `POST .../cancel` at the next boundary. Documented in the describe; unchanged. |

## 6. Implemented / tested / integrated / blocked

| Item | Implemented | Tested (command → result) | Integrated | Blocked / not done |
| --- | --- | --- | --- | --- |
| `cursor_turn_points` (both profiles), `turn_points` on both harnesses, end-session memo of the snapshot / branch head | yes | `uv run pytest tests/unit/cursor/test_cognition_points.py -q` → 2 passed (local full run: 5 step points keyed by offsets 5, 7, 8, 9, 11 + the `cursor-snapshot:` workspace point; cloud: events 4, 6, 7, 8 + `branch:mc/...@<sha>`) | through `LaneTurnService._settle` (K1) on the in-memory lineage; Postgres batch shape proven by `tests/integration/postgres/test_session_lane_points_postgres.py` → 1 passed | a Cursor profile through `lane.turn` on real Temporal **with the Postgres lineage composed** is not run (the Temporal proof uses the scripted lane) |
| `CursorTimeTravel.read_as_of` (R2 local, R2 cloud with a branch reader) | yes | `uv run pytest tests/unit/cursor/test_time_travel.py -q` → 5 passed | registered in the worker, the operator API and the technical API (K3) | cloud R2 read exercised only through the local manifest path in unit tests; the cloud branch-tree read is implemented, not unit-tested against the fake SCM |
| `CursorTimeTravel.seed_fork` + `prepare`/`start`/`send_turn` honouring the seed | yes | same suite: the seed stages the transcript, names the snapshot, repeats idempotently; a derived lease restores `outputs/report.md` and `src/feature.py` and its first send starts with the hydration header and ends with the unit's instruction | the seed service records `channel_facts.seed_head` (K2) and the turn service hands it to `prepare`/`start` (K2); `tests/unit/harness/test_lane_turn_points.py` → 9 passed, `tests/unit/recovery/test_session_lane_seed.py` → 2 passed | a seeded fork of a Cursor run through `missionctl run fork --point` on real services is not run; cloud `prepare(seed)` is implemented, not unit-tested (the branch snapshot path is the FT-F4 fork path) |
| `collect_points` (reconciler convention) | yes | same suite: re-folds the generation to the settlement's locators | `point_reconciliation.py` passes `namespace=<heid>`, `checkpointer_ref_digest=str(generation)` for non-checkpoint rows | the reconciler walks only generations with a checkpoint transition, so a session-lane generation is never re-derived by `points:reconcile` today (kernel note) |
| describe cells | `time_travel=LaneTimeTravel(read="R2", fork="R2")` on `CURSOR_LOCAL_DESCRIBE_V1` / `CURSOR_CLOUD_DESCRIBE_V1` (v2 inherits) | `tests/unit/harness/test_describe_honesty.py` passes; `tests/unit/harness/test_lane_contracts.py` (2) fail until the describe-refresh migration exists | | integrator renders the migration from the final matrices |
| interrupted / replacement roles | K1 (`_replacement_map`, `fold_generation_points`) | `test_lane_turn_points.py::test_fold_chains_an_interrupted_turn_and_its_replacement` | | not driven through a Cursor inject on real services in this session (`tests/integration/postgres/test_ft_f2_inject_postgres.py` → 1 passed, without a points assertion) |
| conformance registration | unchanged (`tests/conformance/lanes/adapters/cursor.py`): the contract has no time-travel scenario; `FORK_EMULATION` already covers the snapshot restore | `uv run pytest tests/conformance/lanes -q` inside the floor run → passed | | |

Pre-existing failures on `main` reproduced against `HEAD`'s exported source (not caused here):
`tests/unit/harness/test_cursor_local.py::test_closing_facts_map_every_run_result_status[*]` (4),
`tests/integration/cursor/test_cursor_local_fixtures.py::...[precompact]` and both
`tests/integration/cursor/test_mp09_cloud_segment_loop_real_services.py` tests (the usage rule in
`adapters/cursor/usage.py` reads `inputTokens`/`outputTokens` without a total as `unknown`, so no
budget is exceeded; the cloud suite fails on `history close execution is no longer live`).

## 7. Kernel notes (K1 to K3, built here)

- K1: `LaneTurnService._settle` → `_turn_points` → `fold_generation_points(frames, collect=harness.turn_points, ...)`; `settle_lane_session(points=...)` admits the attempt against the lineage (`admit_attempt`, the claim lease) so `record_result(admitted, points=..., lane_profile=lane_profile_for(binding))` writes the batch beside the result (no transition), then releases the lease. A fold or admission failure logs and settles without points. Cancelled turns (`cancel()` and the fenced `_interrupt` path) go through the same `_settle`.
- K2: `CognitiveSeedService.resolve` admits `time_travel.fork` ≥ R1; `seed` records `channel_facts.seed_head` (`mc.lane_seed_head.v1`) for a non-checkpoint head, skips `seed_namespace_head`, records the receipt's `restore_level`/`history`, replays an existing `fork_seed` point; `LaneTurnService._start_and_send` passes `seed=` from that point for generation 1.
- K3: `TimeTravelRegistry.lane(profile, request_scope=...)` binds a `ScopedTimeTravelLane` (`for_scope`); `ForkSeedRequest.request_scope`; `bootstrap/session_time_travel.py::session_lane_time_travel` registers every session lane in the worker, the operator API (`ApplicationFrameReaders` routes frames and snapshot bytes by the scope's application) and the technical API.
- K6 (note, not done): `session_turn.point_ref` for session lanes. The frame writer enriches it for Deep Agents from the recorder; a session lane's result point is known only at settlement, after the turn row was written, so it needs an `enrich`-style update of `session_turn` keyed by `(harness_execution_id, native_turn_ref)` after `record_result`; not cheap in the existing path, left for the integrator.

## 8. Provider facts not verified this session

No paid Cursor call was made. The step identities (bridge offsets, SSE event ids) and the
snapshot refs come from the recorded-shape fixtures (`tests/integration/cursor/fixtures/*`,
marked synthetic); a scrubbed recording from the owner-run drill is still the FT-G6 debt.
