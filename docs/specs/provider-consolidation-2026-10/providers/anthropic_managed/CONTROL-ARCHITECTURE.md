---
type: Specification
title: "claude_managed control architecture: cognition points, time travel and intervention on Anthropic Managed Agents"
description: "How the claude_managed lane (Anthropic Managed Agents, anthropic 1.13.0 wire shapes, beta managed-agents-2026-04-01) writes one session_cursor point per step of a turn from its persisted events, reads state as of a point and seeds forks at R1 over those frames, and maps queue, steer, cancel-and-replace and the Stop Fence onto the session API; with the honest implemented / tested / integrated / blocked table and the kernel requests."
tags: [mission-control, providers, consolidation, claude-managed, anthropic-managed-agents, cognition-points, time-travel, interventions]
status: active
date: 2026-11-05
---

# `claude_managed` control architecture

Part of [cross-provider control](../cross-provider-control/DESIGN.md) (Agent B, 2026-11-05).
Code: `src/mission_control/adapters/anthropic_managed/{cognition_points,time_travel,harness,describe}.py`
over the shared base `src/mission_control/adapters/remote_session/{cognition_points,time_travel}.py`.
Provider facts come from the pinned `anthropic` 1.13.0 shapes and the HL-23 smoke
([SPEC-06 section 4.2](../../../archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md));
what no source states is marked **unverified**.

## 1. What this closes and what remains

Deep Agents has granular checkpoints, state-as-of reads, seeded forks and interventions on
its LangGraph cycle. This lane now has the same shape over its only native lineage, the
Managed session event log persisted as Provider Frames: one point per step boundary
(`cognition_points.py`), R1 reads and seeds (`time_travel.py`), a native steer on the harness
and the existing cancel-and-replace. Remaining for the goal: the kernel wiring (K1 settlement
points, K2 seed head, K3 registry: Agent A), the describe-refresh migration the describe
cells need (section 6, request KR4), and a paid drill that qualifies Q-M1 steering and a
seeded fork against the real API (none authorized this session).

## 2. Provider lifecycle to point boundaries

A Managed session is one event log shared by every turn; the lane's turn is the
`user.message` it sent (its event id is the native turn ref) and ends at the first
`session.status_idle` with an ending stop reason (`end_turn`, `retries_exhausted`,
`refusal`) or `session.status_terminated` (`frames.TurnFold`). The frame writer classifies
each event through `application/frames/kinds.py::CLAUDE_MANAGED_KINDS`; the kernel fold
`frame_boundary_points` makes every `STEP_KINDS` frame a point.

| Managed event (raw kind) | Frame kind | Point? | Role / facts |
| --- | --- | --- | --- |
| `session.status_running`, `span.model_request_start`, `session.thread_status_*`, `session.updated`, `workflow_run.*`, `status` (stream opened/expired) | `status` | no, folded into the next point's frame range | |
| `user.message` (the turn's own, processed) | `message` | **yes** | `input` (the hosted fold's correction: no `turn_started` exists here); `message_count` 1 |
| `agent.message` | `message` | yes | `intermediate`; text digest at read time |
| `agent.thinking` | `thinking_delta` | no | |
| `agent.tool_use`, `agent.mcp_tool_use` (`evaluated_permission: allow`), `agent.custom_tool_use` | `tool_call_started` | no (the close is the point) | `tool_call_ref` = tool use event id |
| `agent.tool_use` with `evaluated_permission: ask` | `approval_requested` | no | the approval the gate answers |
| `user.tool_confirmation` | `approval_resolved` | yes | `intermediate`; facts `tool_name` |
| `agent.tool_result`, `agent.mcp_tool_result`, `user.custom_tool_result` | `tool_call_completed` / `tool_call_failed` (`is_error`) | yes | `intermediate`; facts `is_error`, `tool_call_ref` |
| `span.model_request_end` (`model_usage`) | `status` | no | its tokens are summed into the point that folds it (`usage_delta` `tokens.<name>`) |
| `session.usage` (cumulative `list_cost`) | `usage` | no | cumulative, ignored per step; the turn's own cost comes from the close |
| `agent.thread_context_compacted` | `after_compaction` | yes | `source: compaction` |
| `session.error` | `error` | yes | `source: interrupt` |
| `session.status_idle{end_turn|retries_exhausted|refusal}`, `session.status_terminated`, `turn.final` (synthesized from history) | `run_result` | yes | `leaf` + `result`; facts `stop_reason`, `turn_status`, `interrupted`; `usage_delta` gains `cost.list_cost_minor_units` from `mc_turn.list_cost_minor_units` |
| `session.status_idle{requires_action|budget_reached}`, `session.status_idle.runs_open` | `status` | no | the turn waits (approval, budget gate, open workflow run) |
| `user.interrupt` (processed inside the turn) | `status` | no | makes the close `cancelled` (`mc_turn.interrupted`) |

Granularity reached on the fixture turn (`tests/unit/anthropic_managed/test_cognition_points.py`):
`user.message` → `agent.message` → `session.status_idle{end_turn}`, with the model request's
tokens on the point that folded its end span and the turn's cost on the result. With
multiagent on (read-only knowledge work, DECISIONS R33), per-thread events arrive on the
session stream as `session.thread_*` / `workflow_run.*` status frames: no `subordinate_ref`
is written today (the frame writer records none for this lane), so subagent points are
**not** produced; this is honest `subordinate_visibility: unqualified`.

## 3. Identity

| Field | Value | Where it comes from |
| --- | --- | --- |
| point kind | `session_cursor` | |
| `session_ref` | Managed session id (`sesn_…`) | `TurnPointsRequest.native.session_ref` |
| `turn_ref` | the turn's `user.message` event id | `native.turn_ref` (`send_turn` echo id) |
| `step_ref` | the **event id** of the step frame | parsed from the frame key `managed:<turn>:<processed_at micros>.<event id>`; `final` for the history-synthesized close `managed:<turn>:final`; kernel default `<arrival_ordinal>:<kind>` for a content-keyed frame |
| locator | `session#turn#event` | `SessionCursorPoint.locator` |
| transcript join | `frame_keys` of the point are the exact provider keys the frame writer stored | `provider_key` also in `channel_facts` |

The same point is folded again by `collect_points(namespace=<harness execution id>,
checkpointer_ref_digest=<generation>)` (the K3 convention), so a reconciler re-derives the
rows the settlement wrote (`test_collect_points_re_derives_the_settlement_fold`).

## 4. Restore levels and why

| Operation | Level | History | Why |
| --- | --- | --- | --- |
| `read_as_of` | **R1** | `reconstructed` | the transcript is rebuilt from the persisted frames up to the point (user and agent messages, tool uses with their inputs, tool results); `channels.native` names the session, turn, locator and frame counts; `usage_to_point` sums the points' deltas. **No files**: the provider environment's filesystem is not captured by this lane (`workspace_files_not_captured` in `withheld`). R2 would need a Managed session file capture (`client.session_files` exists for custody at `end_session`, not per turn). |
| `seed_fork` | **R1** | `reconstructed` | Managed Agents has **no session fork, no history import on `create_session` and no replay into another session** in the pinned 1.13.0 surface (only `user.*` events can be sent). The derived unit gets a **hydration prompt**: preamble + the transcript to the point + the injected message (or a continue line), bounded (`MAX_SEED_PROMPT_CHARS`), digested, in `native_artifacts["seed_prompt"]`. `seed_fork` writes nothing anywhere and is a pure function of the frames: repeating it is idempotent and the source session is never touched. |
| `prepare` / `start` with `seed` | | | `prepare` keeps the seed; `start` creates a **new** session as usual, stamped `mc_fork_request`, `mc_fork_source`, `mc_fork_point` in its metadata; the first `send_turn` sends the seed prompt (`seed_turn_text`) instead of the operation's turn text. Proven on the fixture: `test_a_seeded_unit_starts_a_new_session_and_sends_the_prompt_first`. |
| R3 | refused | | **unverified**: no evidence of a native fork or replay; `TimeTravelUnsupported(point_kind_not_session_cursor)` for other kinds. |

The derived coordinate the `fork_seed` point stands at is
`session_cursor(session_ref=<derived namespace>, turn_ref="fork-seed:<fork request id>")`:
the real session exists only after `start`.

## 5. Intervention mapping

| Command | Lane semantics (declared) | Mechanism | Point evidence |
| --- | --- | --- | --- |
| queue (`queue_instruction`) | `wait_then_send` | a `user.message` is sent only while the session is `idle` and waits on nothing (`_accepts_message`); the next turn is a new `user.message` | the new turn's first point is `input` |
| steer | **implemented, not declared** (`SteeringLane.steer`) | Q-M1 (HL-23): a `user.message` while `running` is consumed at the next model request of the current turn. Guard: session `running`, latest turn-starting `user.message` is the target (steer ids are remembered and excluded from `_reconcile_send`), else `stale_target`. Proven on the fake (`test_steer_sends_into_the_running_turn_and_is_stale_otherwise`). | the steer is a `user.message` frame inside the same turn (a `message` point of that turn) |
| `interrupt_and_inject` | `cancel_and_replace` (unchanged) | `user.interrupt`, wait until not `running`, replacement `user.message`; the kernel passes `interrupted_turn_ref` | the interrupted turn's close has `mc_turn.interrupted=true` and its leaf gets `interrupted` (K1); the replacement's first point carries `replacement_start` (`test_a_replacement_turn_names_its_source_and_replacement_start`) |
| cancel | `turn_boundary_guaranteed` | `user.interrupt` ends the turn after the in-flight model request (`end_turn`, read as `cancelled`) | the cancelled turn still folds to points (K1 writes them) |
| Stop Fence | reach: **custom tools only** | no hook runs at Anthropic (`LaneHooks(mechanism="none")`). The fence point is `HostedToolGate` answering Mission Control custom tools (`mc_*`) through `PostgresStopFenceRepository`; built-in tools (`bash`, `read`, `web_search`, MCP) run inside the provider and are stopped only by the cancel path at the next model request. Immediate stop is therefore bounded by one in-flight model request plus one running built-in tool. |
| pause / resume | `unsupported` / `wait_then_send` | budget gate emulation (`hold_budget`) is the only mid-run pause | a `budget_reached` idle is a status frame, not a point |

Why `interrupt_and_inject` is not flipped to `cooperative_inject`: Q-M1 is observed in
HL-23 but not qualified (HL-24), exact-target semantics rest on a read-then-send race, the
conformance suite proves only `cancel_and_replace` (`INTERRUPT_SEMANTICS`), and the kernel's
`_steer` never stages the instruction text for a `SteeringLane` (request KR3). The harness
`steer` is ready for the flip once those hold.

## 6. Implemented / tested / integrated / blocked

| Item | Implemented | Tested (command, result) | Integrated | Blocked / unverified |
| --- | --- | --- | --- | --- |
| `turn_points` (`PointCollectingLane`) | yes, `harness.py` → `cognition_points.py` | `uv run pytest tests/unit/anthropic_managed/test_cognition_points.py -q -p no:cacheprovider`: 5 passed | no: K1 (`LaneTurnService._settle`) is Agent A's | |
| `read_as_of` R1 | yes, `time_travel.py` | `tests/unit/anthropic_managed/test_time_travel.py`: 5 passed (with the items below) | no: K3 registry (`compose_hosted_time_travel`, section 7) | request scope for the frame reader (KR1) |
| `seed_fork` R1, idempotent, source untouched | yes | same file | no: K2/K3 | |
| `prepare`/`start`/`send_turn` honor `seed` | yes, `harness.py` | same file | no: K2 passes `seed=` | |
| `steer` (`SteeringLane`) | yes | same file (fake extended: a `user.message` during a held turn is consumed by it) | not declared; `cancel_and_replace` kept | Q-M1 unqualified (HL-24), KR3 |
| `collect_points` | yes | `test_collect_points_re_derives_the_settlement_fold` | no | |
| describe `time_travel=R1/R1` | yes, `describe.py` | `tests/unit/harness/test_describe_honesty.py` passes; `tests/unit/harness/test_lane_contracts.py` **fails 2** (the persisted describe documents in the 1.4.3 migrations are no longer the declared ones) | no | needs the describe-refresh migration (KR4; candidate rendered) |
| composition factory | yes, `hosted_lane_composition.py::compose_hosted_time_travel` | mypy clean | no: A wires `_worker_time_travel`, `bootstrap/api.py`, `bootstrap/runtime_control.py` | |
| integration (`tests/integration/anthropic_managed`) | n/a | `tests/integration/anthropic_managed`: 1 failed, 3 skipped (paid opt-in) before and after this work; the failure is the worker-loss reattach raising `history close execution is no longer live` (`adapters/postgres/lanes/execution_state.py:151`), a baseline defect outside this lane's files | | baseline failure to triage (kernel/postgres) |
| paid qualification | no | none (not authorized) | no | steering, seeded fork, cost per point against the real API |

## 7. Composition for Agent A (K3)

`adapters/temporal/hosted_lane_composition.py::compose_hosted_time_travel(frames=<FrameReader>,
request_scope=<scope>, claude_managed=True, codex_agents=True) -> dict[str, TimeTravelLane]`
returns the two lanes over a `ScopedFrameReader`; register them in `TimeTravelRegistry`
beside `deep_agents` in `_worker_time_travel`, `bootstrap/api.py` and `bootstrap/runtime_control.py`.
Needs only the frame reader and the scope: no client, no credential, no paid call.

## 8. Kernel requests (for Agent A)

- **KR1 — scope for frame-backed reads.** `TimeTravelLane.read_as_of(record)` and
  `seed_fork(request)` carry no request scope, but `FrameReader.frames_for_execution` needs
  one. Either pass it (`application/execution/cognition_point_reads.py::state_as_of` has
  `self._scope`; `application/recovery/cognitive_seed.py::seed` knows the derived run's
  scope) or compose the registry per scope (`CognitionPointReadService.with_time_travel(...)`
  with `compose_hosted_time_travel(frames, request_scope=...)`). Until then the hosted lanes
  are composed with one scope per deployment.
- **KR2 — `frame_boundary_points` input role.** `application/execution/harness/points.py`:
  accept an `is_input: Callable[[ProviderFrame], bool]` (or `input_kinds`) so a lane without
  a `turn_started` frame marks its opening user message `input`; the hosted fold corrects it
  afterwards today (`remote_session/cognition_points.py::hosted_turn_points`).
- **KR3 — stage the text before steering.** `application/execution/harness/lane_turns.py::_steer`
  calls `harness.steer(turn, instruction_ref=key)` without `harness.stage_turn(heid, key,
  text)` (the cancel-and-replace path stages at the `follow_up` send). A `SteeringLane`
  therefore answers `stale_target: instruction text not staged` forever. Stage the delivered
  entry's content first; add the `cooperative_inject` expectation to
  `tests/conformance/lanes/test_session_turns.py::INTERRUPT_SEMANTICS` before any lane flips.
- **KR4 — describe refresh migration.** The `time_travel` cells change the persisted describe
  documents. One successor migration for every lane whose describe changed this session,
  rendered by `packages/mission-control-db-contract/scripts/lane_describe_refresh.py::
  render_successor_section(... prior=persisted_documents(<1.9.0 migrations>), profiles=(...))`,
  and `tests/unit/harness/test_lane_contracts.py` taught that the end state is that migration.
  A candidate for the two hosted profiles is rendered at
  `C:/Users/Pinda/AppData/Local/Temp/claude/4f511ac37dc0533e/1e7f158b-02f9-4fbe-a2c0-a63bd3fe2d9d/scratchpad/0068_hosted_lane_time_travel_describes.sql`
  (not placed in the package: the integrator merges it with Agent C's describes).
- **KR5 — K1 request shape.** `TurnPointsRequest.native` must carry both `session_ref` and
  `turn_ref` (the hosted fold returns no point without them); `source_point` for turn n>1 is
  the previous turn's result point; `interrupted_turn_ref` from `inject.py`.
- **KR6 — `session_turn.point_ref`.** Not done here; the result point's locator is
  `session#turn#<close event id>` when the enrichment path wants it.

## 9. Provider facts not verified this session

- A Managed session fork, history import or event replay into another session: not in the
  pinned surface; assumed absent (R3 refused).
- Q-M1 steering under a real turn with an open custom tool (`requires_action`): the 1.13.0
  docs say such a send is refused `400`; the harness checks `running` first.
- Per-thread (multiagent) event identity for `subordinate_ref`: not recorded by the frame
  writer; no subagent points.
