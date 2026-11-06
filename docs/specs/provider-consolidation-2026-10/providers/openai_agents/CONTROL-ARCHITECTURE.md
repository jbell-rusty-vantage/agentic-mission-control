---
type: Specification
title: "codex_agents control architecture: cognition points, time travel and intervention on the OpenAI Agents API"
description: "How the codex_agents lane (OpenAI Agents API running the Codex harness, openai 3.29.0 wire shapes) writes one thread_item point per completed item of a turn from its persisted frames, reads state as of a point and seeds forks at R1 over those frames, and maps queue, steer, cancel-and-replace and the Stop Fence onto the session API; with the honest implemented / tested / integrated / blocked table and the kernel requests."
tags: [mission-control, providers, consolidation, codex-agents, openai-agents-api, cognition-points, time-travel, interventions]
status: active
date: 2026-11-05
---

# `codex_agents` control architecture

Part of [cross-provider control](../cross-provider-control/DESIGN.md) (Agent B, 2026-11-05).
Code: `src/mission_control/adapters/openai_agents/{cognition_points,time_travel,harness,describe}.py`
over the shared base `src/mission_control/adapters/remote_session/{cognition_points,time_travel}.py`.
Provider facts: the pinned `openai` 3.29.0 shapes, [OPENAI-AGENTS-API-SURFACE-2026-10-30](../../OPENAI-AGENTS-API-SURFACE-2026-10-30.md)
and [OPENAI-AGENTS-API-DESIGN](../../OPENAI-AGENTS-API-DESIGN.md) (decisions OA-D4, OA-D5);
what no source states is marked **unverified**.

## 1. What this closes and what remains

The lane now has Deep Agents' control shape over its only native lineage, the durable items
and turn records persisted as Provider Frames: one point per completed item and per turn
close (`cognition_points.py`), R1 reads and seeds (`time_travel.py`), a native steer on the
harness and the existing cancel-and-replace. Remaining for the goal: the kernel wiring (K1,
K2, K3: Agent A), the describe-refresh migration the describe cells need (KR4), a captured
workspace scope before any R2 claim (OA-D4), and a paid drill that qualifies the steer race
and a seeded fork against the real API (none authorized this session).

## 2. Provider lifecycle to point boundaries

A turn is one root turn record (`subagent_id` null) of the session; its durable history is
the item list (`GET …/turns/{turn}/items`), its close the turn's terminal status. The stream
has no replay: every subscription restores items, then applies live notifications; the lane
stores each completed item once under `agents:<turn>:item~<item id>` (live or recovered) and
the terminal under `agents:<turn>:done`. `application/frames/kinds.py::CODEX_AGENTS_KINDS`
classifies the notifications; the kernel fold makes every `STEP_KINDS` frame a point.

| Agents API notification (raw kind) | Frame kind | Point? | Role / facts |
| --- | --- | --- | --- |
| `agent.session.created/in_progress/idle`, `agent.session.turn.created/in_progress`, `agent.session.turn.item.added`, content and reasoning part events, `agent.session.environment.*` (except `failed`), `agent.session.subagent.*`, `agent.session.requires_action`, `status` | `status` | no, folded into the next point's range | |
| `agent.session.turn.output_text.delta`, `…reasoning_summary_text.delta`, `agent.output.command_execution_output.delta` | `message_delta` / `thinking_delta` / `tool_call_delta` | no | |
| `agent.session.turn.item.done` with `item.type == message`, `item.role == user` | `message` | **yes** | `input` (the hosted fold's correction: no `turn_started` frame exists); this is the turn's own input item (or a steer's, later in the turn) |
| `agent.session.turn.item.done` with `item.type == message`, `item.role == assistant` | `message` | yes | `intermediate`; facts `item_phase` (`final_answer`), `item_status` |
| `agent.session.turn.item.done` with `item.type == reasoning` | `status` | no | |
| `agent.session.turn.item.done`, any other item (`command_execution`, `file_change`, `web_search`, `mcp_tool_call`, `function_call`, `function_call_output`) | `tool_call_completed` | yes | `intermediate`; facts `item_type`, `item_status`, `recovered`; `tool_call_ref` = `call_id` when present |
| `agent.session.turn.completed` / `failed` / `cancelled`, `turn.final` (synthesized from the turn record) | `run_result` | yes | `leaf` + `result`; facts `turn_status`; `usage_delta` = `turn.usage` as `tokens.<name>` |
| `agent.session.failed`, `agent.session.environment.failed`, `error` | `error` | yes | `source: interrupt` |

Granularity reached on the fixture turn (`tests/unit/openai_agents/test_cognition_points.py`):
three `command_execution` items → the `final_answer` message → the completed turn record,
with the turn's usage on the result only (the API reports usage per turn, not per item).
Child turns (`subagent_id` set) are filtered out by the harness today (`root_turn`), so no
`subordinate_ref` points are produced: honest `subordinate_visibility: unqualified`.

## 3. Identity

| Field | Value | Where it comes from |
| --- | --- | --- |
| point kind | `thread_item` | |
| `thread_ref` | Agents session id (`sess_…`) | `TurnPointsRequest.native.session_ref` |
| `item_ref` | `<turn_id>#<item_id>` | the turn id from `native.turn_ref`; the item id from the frame key `agents:<turn>:item~<item id>`; `done` for the terminal record; a live event id for an item-less notification; the kernel default `<arrival_ordinal>:<kind>` for a content-keyed frame |
| locator | `session#turn#item` | `ThreadItemPoint.locator`, parallel to the session cursor's `session#turn#step`; `split_item_ref` reads the turn back |
| transcript join | `frame_keys` of the point are the exact stored provider keys | `provider_key` also in `channel_facts` |

The domain `ThreadItemPoint` has no turn field (DESIGN section 5 names the triple); encoding
the turn in `item_ref` keeps the locator unique across turns and lets a seed name its turn
without the kernel's turn ledger. `collect_points(namespace=<harness execution id>,
checkpointer_ref_digest=<generation>)` re-derives the same rows.

## 4. Restore levels and why

| Operation | Level | History | Why |
| --- | --- | --- | --- |
| `read_as_of` | **R1** | `reconstructed` | messages rebuilt from the persisted items up to the point: user and assistant `message` items, each tool item as an assistant tool call plus a tool message with its outcome (`status`, `exit_code`, `output`), `function_call`/`function_call_output` pairs. **No files**: the provider environment is not captured by this lane; OA-D4 allows R2 only for a complete captured workspace scope, which does not exist yet. |
| `seed_fork` | **R1** | `reconstructed` | the surface has **no session-fork, checkpoint selection/restore, history-edit or rollback endpoint** (SURFACE "Checkpoints, inspection and fork limits"; OA-D4 refuses R3). The derived unit gets a **hydration prompt** (preamble + transcript to the point + injected message or a continue line) in `native_artifacts["seed_prompt"]`, bounded and digested. `seed_fork` writes nothing; it is a pure function of the frames and the request (idempotent; the source session is never touched). |
| `prepare` / `start` with `seed` | | | `prepare` keeps the seed; `start` creates a **new** session stamped `mc_fork_request`, `mc_fork_source`, `mc_fork_point`; the first `send_turn` sends the seed prompt as the `agent.session.input.message`. Proven on the fixture. |
| R3 | refused | | `TimeTravelUnsupported(point_kind_not_thread_item)` for other kinds; no native fork (**verified absent in the public surface**, private checkpoints do not qualify). |

The derived coordinate the `fork_seed` point stands at is
`thread_item(thread_ref=<derived namespace>, item_ref="fork-seed#<fork request id>")`.

## 5. Intervention mapping

| Command | Lane semantics (declared) | Mechanism | Point evidence |
| --- | --- | --- | --- |
| queue | `wait_then_send` | input is sent only while the session is `idle` with no required action; idle input starts a turn | the new turn's items are its points |
| steer | **implemented, not declared** (`SteeringLane.steer`) | input during `in_progress` lands as a `message:user` item of the active turn (HL-23). The API has **no expected-turn compare-and-swap** (OA-D5): the guard is a read before (session `in_progress`, no required action, latest root turn is the target) and after (a new root turn means the input started a turn: `stale_target` with the new turn named, effects reported not hidden); `409 active_turn_not_steerable` is `stale_target`. Proven on the fake (`test_steer_sends_into_the_active_turn_and_is_stale_otherwise`). | the steer is a `message:user` item of the same turn, so an `input`-shaped point inside it |
| `interrupt_and_inject` | `cancel_and_replace` (unchanged) | `agent.session.input.cancel`, wait until terminal, replacement input; the kernel passes `interrupted_turn_ref` | the cancelled turn's record is `cancelled` and its leaf gets `interrupted` (K1); the replacement's first point carries `replacement_start` |
| cancel | `turn_boundary_guaranteed` | `agent.session.input.cancel`, retried on `409` | the cancelled turn still folds to points |
| Stop Fence | reach: **function tools only** | no hook runs at OpenAI (`LaneHooks(mechanism="none")`). The fence point is `HostedToolGate` answering Mission Control function tools (`required_actions`) through `PostgresStopFenceRepository`; the built-in shell and file tools run inside the provider with no per-command approval (`enforcement_coverage: shell/file unsupported`) and stop only through the asynchronous cancel. |
| pause / resume | `unsupported` / `wait_then_send` | only the function-tool gate holds a turn mid-run | a `requires_action` is a status frame, not a point |

Why `interrupt_and_inject` is not flipped to `cooperative_inject`: OA-D5 ("expose
cooperative steering only with its actual race semantics"), the conformance suite proves only
`cancel_and_replace`, and the kernel's `_steer` does not stage the instruction text (KR3).

## 6. Implemented / tested / integrated / blocked

| Item | Implemented | Tested (command, result) | Integrated | Blocked / unverified |
| --- | --- | --- | --- | --- |
| `turn_points` (`PointCollectingLane`) | yes, `harness.py` → `cognition_points.py` | `uv run pytest tests/unit/openai_agents/test_cognition_points.py -q -p no:cacheprovider`: 5 passed | no: K1 is Agent A's | |
| `read_as_of` R1 | yes, `time_travel.py` | `tests/unit/openai_agents/test_time_travel.py`: 5 passed (with the items below) | no: K3 (`compose_hosted_time_travel`) | KR1 scope |
| `seed_fork` R1, idempotent, source untouched | yes | same file | no: K2/K3 | |
| `prepare`/`start`/`send_turn` honor `seed` | yes | same file | no: K2 passes `seed=` | |
| `steer` (`SteeringLane`) | yes | same file (fake extended: input during a held turn becomes a `message:user` item of it) | not declared; `cancel_and_replace` kept | race unqualified (OA-P3), KR3 |
| `collect_points` | yes | `test_collect_points_re_derives_the_settlement_fold` | no | |
| describe `time_travel=R1/R1` | yes | `test_describe_honesty.py` passes; `test_lane_contracts.py` fails 2 (persisted describes vs declared) | no | KR4 migration |
| composition factory | yes | mypy clean | no: A wires the registries | |
| integration (`tests/integration/openai_agents`) | n/a | 1 failed, 3 skipped (paid opt-in) before and after this work; the failure is the worker-loss reattach raising `history close execution is no longer live` (`adapters/postgres/lanes/execution_state.py:151`), a baseline defect outside this lane | | baseline failure to triage |
| paid qualification | no | none (not authorized) | no | steer race, seeded fork, per-item usage absence confirmed live |

## 6a. F3-G1: the first turn was never sent (2026-11-06)

Live HL-13 (`tests/integration/openai_agents/test_function_tools_live.py`, segment heartbeat
timeout 5 s) created templates, two agents and a session, then never sent input. Cause, from
timestamped request logs and the workflow history: this lane's prepare (template create,
readback polling, agent create, readback polling) takes about 5 to 9 s, and `lane.turn` sent no
heartbeat until observation began. Temporal timed attempt 1 out (`activity Heartbeat timeout`)
and ran attempt 2 (in one rerun also attempt 3) beside it on the same worker, under the same
owner ref. The attempts synced the pack twice (the second agent) and raced the dispatch journal:
the later attempt reconciled the earlier attempt's create (or send) while it was still in flight,
found nothing, and parked the unit `in_doubt` (`create_dispatch_ambiguous`, or
`send_dispatch_ambiguous`). The workflow then waited for an operator `reconcile_unit` hint,
which the drill never read. Managed Agents passes the same drill because its prepare finishes
inside the heartbeat timeout.

Fix (kernel, every Session Lane): `LaneTurnService._beating` heartbeats (prior cursor hint)
and renews the session lease through prepare, start and the first send, and bounds that phase
by `max_duration_s`; past it the attempt fails as `LaneStartStalled` and the retry reconciles
the journal. Regression tests: `tests/unit/harness/test_lane_turn_service.py`
(`test_a_slow_prepare_heartbeats_before_the_first_send`, failed before the fix;
`test_a_start_that_never_sends_fails_typed_within_the_segment_duration`). The drill now reads
the workflow each 5 s and fails at once on an `in_doubt` park, recording `lane_progress`
(attempt, last failure, park code) in its evidence. Live rerun after the fix (2026-11-06,
`gpt-6.1-sol`): **passed** in 62 s on one attempt, one agent and one session: one input
message, the function approval reached a Human Task, the turn resumed on a restarted worker
and completed (`disposition completed`, 25 frames, 0 duplicate keys, one tool result
`allow`), usage 17,814 input (16,833 cached) and 62 output tokens, cost not reported by the
API (`unknown`), every resource deleted. (The drill's resolved-task read also had to call
`get_task`.) Not fixed here: two attempts of one
activity on one worker still share an owner ref, so only the heartbeat keeps them apart.

## 7. Composition for Agent A and kernel requests

Composition: section 7 of the [claude_managed document](../anthropic_managed/CONTROL-ARCHITECTURE.md)
(`compose_hosted_time_travel` returns both lanes). Kernel requests KR1 to KR6 are listed
there once and apply to this lane identically; the one Agents-specific note: K1's
`TurnPointsRequest.native.turn_ref` must be the **root** turn id the lane acknowledged
(`send_turn` already filters `subagent_id`).

## 8. Provider facts not verified this session

- Whether a `message:user` item for the turn's own input appears in the item list of a
  real turn (the fixture records none, so the first point is `intermediate` with `source:
  input`; with a real user item it becomes `input`): **unverified**, both paths are handled.
- Item ids being unique across turns of a session (assumed; the locator carries the turn
  anyway).
- Steering a turn that waits on a function tool (`required_actions`): refused by the guard
  before any send; the provider's own answer is unverified.
