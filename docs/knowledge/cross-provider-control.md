---
type: Concept
category: execution
title: Cross-provider control - points, time travel and intervention on every lane
description: How every Session Lane (Cursor local and cloud, Claude Agent SDK, Codex, Managed Agents, Agents API) gets the control Deep Agents has - one cognition point per step boundary folded from its persisted Provider Frames in the lane.turn settlement, state-as-of reads and seeded forks at the restore level each provider reaches (R1 reconstructed transcript, R2 plus workspace, R3 native thread or session), and steering or cancel-and-replace through its native lifecycle - with the kernel seams, the per-lane identities and what is built, tested, integrated and still unqualified.
tags: [mission-control, lanes, cognition-points, time-travel, fork, interventions, cross-provider, implementation]
aliases: [session-lane points, PointCollectingLane, frame boundary points, lane seed head, point seed, restore level]
questions:
  - How does a session lane write cognition points and fork from them?
  - Which restore level does each lane reach for state-as-of and seeded forks?
  - How does a fork seed a Cursor, Codex, Claude or hosted-API session?
  - Which lanes steer a running turn and which cancel and replace?
updated: 2026-11-05
---

# Cross-provider control - points, time travel and intervention on every lane

Deep Agents indexes its lifecycle as one [cognition point](recovery.md#cognition-points-and-forks-from-a-point) per LangGraph
root checkpoint, reads the state at a point and seeds forks from it ([precise fork](precise-fork.md)), and is steered by
queue, inject and the Stop Fence ([interventions](interventions.md)). Since 2026-11-05 (OVE-224, ADR-0069) the eight other
lane profiles have the same control over their only native lineage, the persisted [Provider Frames](provider-frames-and-transcript.md):
the kernel index, reads, fork saga and transcript joins are shared, the native semantics stay lane-owned. The design and the
per-lane records: [cross-provider control design](../specs/provider-consolidation-2026-10/providers/cross-provider-control/DESIGN.md)
and `providers/<lane>/CONTROL-ARCHITECTURE.md`.

## Points at settlement

A Session Lane implements `PointCollectingLane.turn_points` (`application/execution/harness/points.py`). At settlement
`LaneTurnService._settle` reads the generation's frames, builds one `TurnPointsRequest` per native turn (native session and
turn refs, the closing facts, the activity attempt, `terminal` on the last turn, `interrupted`/`interrupted_turn_ref` from the
dispatch journal when a `cancel_and_replace` replaced it, `source_point` = the previous generation's result point or the
`fork_seed` point) and `settle_lane_session(points=...)` writes the rows in the settlement transaction (`written_by: adapter`);
a fold failure never fails the settlement. The shared fold `frame_boundary_points` makes one point per step frame
(`turn_started`, `message`, `tool_call_completed|failed`, `approval_resolved`, `after_compaction`, `subagent_ended`,
`turn_ended`, `run_result`, `error`), chains `parent_locator`, folds the frame keys, usage and message count since the previous
boundary, and gives the roles `input`, `intermediate`, `leaf`, `result`, `interrupted` and `replacement_start`. The reconciler
re-derives a session-lane generation through `collect_points(namespace=<harness execution id>,
checkpointer_ref_digest=str(generation), ...)`; it does not yet walk session-lane generations on its own (checkpoint
transitions only).

| Lane profile | Point kind and locator | read / fork | Fork head |
| --- | --- | --- | --- |
| `cursor_local`, `cursor_cloud` | `session_cursor` `agent#run#<bridge offset or SSE event id>` per step, plus the turn-close `workspace_snapshot` (`cursor-snapshot:` ref or `branch@sha`) | R2 / R2 | a new agent in a restored lease or on the branch, with the reconstructed transcript staged as the hydration turn |
| `claude_agent_sdk` | `session_cursor` `session#user-uuid#<step key>` | R3 / R3 | the state-root transcript mirror truncated at the point under a new session id, started with `resume=<new id>` |
| `codex` | `thread_item` `thread#<item id>` | R3 / R3 | `thread/fork` at the turn the point closes (native), else the previous turn plus a hydration preamble, else a transcript |
| `claude_managed` | `session_cursor` `session#user-message-event#<event id>` | R1 / R1 | a new session whose first message is the transcript to the point (the API forks no session) |
| `codex_agents` | `thread_item` `session#turn#item` | R1 / R1 | a new session seeded the same way |
| `claude_cloud`, `codex_cloud` | architecture only | unqualified | undocumented lifecycle |

## Reads and seeds

`CognitionPointReadService.state_as_of` routes by the point's `lane_profile` through `TimeTravelRegistry.lane(profile,
request_scope=)`, which binds a scope-aware lane (`ScopedTimeTravelLane.for_scope`); Deep Agents ignores the scope. R1 is the
transcript to the point reconstructed from frames (`history: reconstructed`), R2 adds the files of the turn's workspace snapshot,
R3 the provider's own state. A fork names any lane's point with `CognitivePointSeed(unit_key, point)` beside the Deep Agents
`CognitiveSeed(unit_key, checkpoint)`; `CognitiveSeedService` admits it at the lane's declared `time_travel.fork` level (R1 or
above), the lane's `seed_fork` creates the derived unit's own namespace (a new session, thread, branch or lease; the source is
never written; a repeated seeded fork is idempotent), and the kernel records a `LaneSeedHead` (`mc.lane_seed_head.v1`) on the
derived run's `fork_seed` point and hands it to the lane's `prepare`/`start` as `seed`. `missionctl run fork --point ID` sends the
point form for non-checkpoint points.

## Interventions

Queueing and the Stop Fence are unchanged per lane ([interventions](interventions.md)). Every profile still declares
`interrupt_and_inject: cancel_and_replace`; the interrupted turn's last point carries `interrupted` and the replacement's first
`replacement_start`. Native steering (`SteeringLane.steer`) is implemented on Codex (`turn/steer`), Managed Agents and the Agents
API (a message during the turn) and `LaneTurnService._steer` now stages the text before steering, but no lane declares
`cooperative_inject` until the conformance suite's interrupt expectation covers it and a drill proves the provider race rules.

## Persistence

No new table: `mission_control.cognition_point` (0045/0047) already partitions by `point_kind` and `lane_profile`; release
1.14.0 (`0073_cross_provider_lane_describes.sql`) refreshes the six session-lane describes with their `time_travel` and fork
cells ([database component](database-component.md)).

Built / specified / goal: kernel seams, the six lanes' folds, time travel and seed handling built and unit-tested (FIXTURE
clients); integrated on real PostgreSQL and Temporal for the scripted session lane (`test_lane_turn.py`,
`test_session_lane_points_postgres.py`) and the 1.14.0 release proof; a Cursor, Codex or Claude unit through `OperationWorkflow`
with the Postgres lineage, a seeded fork through `run fork --point` on real services, declared steering, `session_turn.point_ref`
for session lanes and the paid drills are not done; nothing is qualified; the cloud stubs are architecture only.

## Citations

- Decision: [ADR-0069](../adr/0069-cross-provider-control-cognition-points-time-travel-and-intervention-on-every-lane.md); program:
  [design](../specs/provider-consolidation-2026-10/providers/cross-provider-control/DESIGN.md),
  [ledger](../specs/provider-consolidation-2026-10/providers/cross-provider-control/LEDGER.md).
- Code: [shared fold and port](../../src/mission_control/application/execution/harness/points.py),
  [time-travel port and registry](../../src/mission_control/application/execution/harness/time_travel.py),
  [lane turns](../../src/mission_control/application/execution/harness/lane_turns.py),
  [cognitive seed](../../src/mission_control/application/recovery/cognitive_seed.py),
  [seed contracts](../../src/mission_control/domain/policies/forks.py),
  [session time travel composition](../../src/mission_control/bootstrap/session_time_travel.py),
  [Cursor](../../src/mission_control/adapters/cursor/time_travel.py), [Claude](../../src/mission_control/adapters/claude/time_travel.py),
  [Codex](../../src/mission_control/adapters/codex/time_travel.py), [hosted base](../../src/mission_control/adapters/remote_session/time_travel.py).
- Tests: [fold](../../tests/unit/frames/test_frame_boundary_points.py), [lane turn points](../../tests/unit/harness/test_lane_turn_points.py),
  [session lane seed](../../tests/unit/recovery/test_session_lane_seed.py), [points on Temporal](../../tests/integration/temporal/test_lane_turn.py),
  [points on PostgreSQL](../../tests/integration/postgres/test_session_lane_points_postgres.py),
  [release 1.14.0](../../tests/integration/postgres/test_cross_provider_release_1140.py), [lane contracts](../../tests/unit/harness/test_lane_contracts.py).
