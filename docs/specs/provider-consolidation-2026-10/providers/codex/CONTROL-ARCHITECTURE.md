---
type: Specification
title: "Codex lanes: cognition points, time travel and intervention (codex, codex_cloud)"
description: "Cross-provider control (2026-11-05) on the Codex app-server lane: one thread_item point per step boundary of a turn folded from the persisted frames at settlement, state-as-of reads at R1/R2/R3, seeded forks through thread/fork (lastTurnId) or a reconstructed transcript, the intervention mapping (queue, steer, cancel-and-replace, Stop Fence through the projected Kernel Hooks) and the honest implemented/tested/integrated/blocked table; codex_cloud is architecture only."
tags: [mission-control, providers, codex, codex_cloud, cognition-points, time-travel, interventions, cross-provider]
status: active
date: 2026-11-05
---

# Codex lanes: control architecture

Part of [cross-provider control](../cross-provider-control/DESIGN.md) (owner goal 2026-11-05) and
[ADR-0069](../../../../adr/0069-cross-provider-control-cognition-points-time-travel-and-intervention-on-every-lane.md).
Lane: `codex` (Codex app-server JSON-RPC v2 over stdio on a Linux/WSL worker, codex-cli 0.162.1,
pinned schema `tests/fixtures/provider_frames/codex/schema/`); stub: `codex_cloud` (architecture only).
Owner framing: the lifecycle control below is the same whether the thread produces a report or commits.

## What remains for the goal, what this closes, the next proof

- **Remains**: the kernel wiring (K1: `LaneTurnService._settle` calling `turn_points`; K2: the seed
  head reaching `prepare`/`start`; K3: `provider_time_travel_lanes` registered by the worker, API and
  runtime-control compositions) is Agent A's; the `interrupt_and_inject` row stays `cancel_and_replace`
  (see [Interventions](#interventions)); no live app-server has run `thread/fork`, `thread/resume` of
  a fork or `thread/read` on the pin (drill step below); the derived unit's workspace is not restored
  by a conversation fork.
- **Closed here**: the lane-side half of DESIGN §4: `adapters/codex/cognition_points.py`
  (`turn_points`, `generation_points`), `adapters/codex/time_travel.py` (`CodexTimeTravel`: `read_as_of`
  R1/R2/R3, `seed_fork` R3 native / R3 reconstructed / R1, `collect_points`), the harness ports
  (`thread_history`, `fork_thread`) and seed honouring (`prepare`/`start`/first `send_turn`), the
  describe cells (`fork: emulated`, `time_travel: R3/R3`), the FIXTURE app-server's `thread/fork`, and
  the unit suites that prove each piece.
- **Next proof**: an integrated run on real PostgreSQL + Temporal once K1–K3 land (`tests/integration/
  temporal/test_mp08_codex_lane_turns.py` extended with a points read), then the owner-run drill
  (`docs/qualification/lanes/codex/README.md` step on `thread/fork`).

## Provider lifecycle and hook events to point boundaries

The lane persists every app-server notification and server request as a Provider Frame
(`adapters/codex/frames.py`, MP-13 keys `codex:<thread>:<turn>:<item>:<method>`). The fold
(`application/execution/harness/points.py::frame_boundary_points`, `STEP_KINDS`) makes a point at every
boundary frame; everything between two boundaries (deltas, starts, hook frames, status) is the next
point's frame range.

| App-server event / hooks.json event | Frame kind | Point boundary | `item_ref` of the point |
| --- | --- | --- | --- |
| `turn/started` | `turn_started` | yes, role `input` | `<turn>:<ordinal>:turn/started` |
| `item/completed` `agentMessage`, `userMessage` | `message` | yes | the item id |
| `item/completed` `commandExecution`, `fileChange`, `mcpToolCall`, `webSearch`, `dynamicToolCall` (`status` completed / failed / declined) | `tool_call_completed` / `tool_call_failed` | yes | the item id (= `tool_call_ref`) |
| `item/started`, `item/*/delta`, `item/*/outputDelta`, `item/reasoning/*`, `turn/plan/updated`, `turn/diff/updated` | started / deltas / status | no (folded into the next boundary) | |
| `item/commandExecution/requestApproval`, `item/fileChange/requestApproval`, `item/tool/requestUserInput`, `mcpServer/elicitation/request`, `item/permissions/requestApproval` (server requests answered by MP-11) | `approval_requested` | no | |
| `serverRequest/resolved` | `approval_resolved` | yes | `<turn>:<ordinal>:serverRequest/resolved` |
| `thread/compacted` (and the `contextCompaction` item) | `after_compaction` (item: status) | yes, source `compaction` | `<turn>:<ordinal>:thread/compacted` |
| `thread/tokenUsage/updated` (`tokenUsage.last` = one model call) | `usage` | no; `usage_delta` of the next boundary (`tokens.input/output/total/cached_input/reasoning_output`); the lane's `:attributed:` companion frame is skipped | |
| `hook/started`, `hook/completed` (hooks.json `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`; Kernel Hooks run `.mission/hooks/kernel.py` against the loopback callback) | `hook_invoked` / `hook_result` | no (folded into the tool close they gate) | |
| events of a child thread (`threadId != root`) | any, `subordinate_ref = codex:thread:<child>` | a child's `item/completed` of a *different* turn id is outside the turn fold; a child's frames inside the root turn's range fold as facts (`subordinate_ref`), never seedable | |
| `error` | `error` | yes, source `interrupt` | `<turn>:<ordinal>:error` |
| `turn/completed` | `turn_ended` | yes | `<turn>:<ordinal>:turn/completed` |
| synthetic `turn/completed.result` (the terminal frame whose body is the `Turn`) | `run_result` | yes, roles `leaf`, `result` | `<turn>:<ordinal>:turn/completed.result` |

Identity (DESIGN §5): `ThreadItemPoint(thread_ref=<thread id>, item_ref=<item id>)`; the turn id is on the
observation's `native_turn_ref` and in `channel_facts.turn_id`. The item id is read from the persisted
provider key (stable when the body was excerpted) and confirmed from a whole body. Facts carry
`thread_id`, `turn_id`, `item_id`, `item_type`, `item_status`, `item_phase`, `item_exitcode`,
`text_bytes`/`text_digest` (never text), `command_digest` (never the command), `turn_status`,
`duration_ms`, `codex_error_info`; `redact_value` runs over them. A generation that ran several native
turns (an interrupted turn and its replacement, a `missing_output` follow-up) is folded by
`generation_points` → `fold_generation_points`: the replaced turn's leaf gets `interrupted`, the
replacement's first point `replacement_start`, only the last turn's leaf is `result`.

## Restore levels

| Port | Level | Mechanism | Why not higher |
| --- | --- | --- | --- |
| `read_as_of` | R1 (always) | messages reconstructed from the frames up to the point (`record.frames.to_ordinal`, else the fold's `arrival_ordinal` fact): agent/user messages, command executions (`$ cmd`, output, exit code), file changes (paths), MCP/dynamic calls (arguments as `ToolCallFact`, result), errors, compactions; redacted, excerpt-capped, `history: reconstructed` | an excerpted body (> 8 KiB) is withheld with a digest; a `body_artifact_ref` is named, not read |
| `read_as_of` | R2 | plus `files` (path, digest, size from the durable ref) of the continuation workspace snapshot the point names (`workspace_checkpoint_ref` / `channel_facts.workspace_snapshot_ref` = `codex-workspace:<manifest ref>`) | the lane's `end_session` git patch (`mc.workspace_snapshot.v1`) is a diff, not a file manifest; only the MP-12 continuation snapshot lists files |
| `read_as_of` | R3 | `thread/read includeTurns=true` through the harness (`thread_history`) when the thread is live in this process: the items in order up to the point (`history: native`; the user message the live stream never itemised appears) | the rollout lives in the session's isolated `CODEX_HOME` inside the lease; once the lease is released and cleaned the thread cannot be loaded (R1 then) |
| `seed_fork` | R3 native | point closes a turn (`turn_ended`/`run_result`): `thread/fork {threadId, lastTurnId=<turn>, excludeTurns=true, cwd, model, approvalPolicy, approvalsReviewer, sandbox, developerInstructions}` on the live source; the derived unit `thread/resume`s the fork | the pinned protocol forks through a *turn* (`lastTurnId`, inclusive); no item-level fork; `thread/revert` edits durable history of the *source* and is never used (the source is never written) |
| `seed_fork` | R3 reconstructed | point inside turn N (N > 1): `thread/fork` through turn N-1, plus the steps of turn N up to the point reconstructed from frames into a hydration preamble (`hydration_ref`) the derived unit's first turn carries | the app-server cannot truncate inside a turn |
| `seed_fork` | R1 | no live thread (not composed, released, or the point is inside the first turn): the transcript to the point reconstructed from frames (`seed_kind: transcript`), the derived `start` opens a fresh thread and sends the preamble ahead of its first turn | nothing of the provider's own state survives the lease |

Native artifacts (`LaneSeedHead.native_artifacts`, never a credential): `seed_kind`, `source_thread_id`,
`point_turn_id`, `point_item_id`, `last_turn_id`, `derived_thread_id`, `hydration_ref`, `seed_head`
(`injected_message`), `seed_head_message_count`, and when the server reported the fork's on-disk path
(`Thread.path`, "[UNSTABLE]" in the pin) `rollout_ref` + `rollout_relpath`, which an isolated derived
`CODEX_HOME` receives in `prepare` so `thread/resume` finds the rollout. Idempotency: the lane memoises
receipts per `fork_request_id` in process and the harness memoises `thread/fork` per fork request; a
repeat across processes forks again (reported, see kernel requests). The derived coordinate is
`ThreadItemPoint(<derived thread>, fork-seed:<fork_request_id>)` (R1: `seed:<fork_request_id>`).

Derived `start` honesty: `thread/resume` of the fork → `native_details.seed_restore = "R3"`; a refusal
(unknown thread in this home) → fresh `thread/start`, `seed_restore = "R1"`, logged; `forked_from` names the
source thread. The injected message is the last section of the preamble (`# Injected message`), never a
separate turn.

## Interventions

| Intervention | Mechanism on `codex` | Row / cell | Evidence |
| --- | --- | --- | --- |
| queue | `command_mailbox` consumed at the turn boundary; `send_turn` on an active thread answers `busy` (a `turn/start` on an active thread would steer it) | `queue_instruction: wait_then_send`, `resume: wait_then_send` | `tests/unit/codex/test_harness.py::test_a_send_on_an_active_thread_is_busy_and_never_a_turn_start`; conformance `send_turn while busy` |
| steer | `SteeringLane.steer`: `turn/steer {expectedTurnId}` lands on the exact active turn or is a typed `stale_target` (completed first, server refusal, text not staged); `LaneTurnService._steer` requeues a stale target | **kept `cancel_and_replace`** in `LANE_COMMAND_SEMANTICS` and the describe | `test_steer_lands_on_the_exact_turn_or_is_a_typed_stale_target`, `test_the_describe_interrupt_cell_follows_the_frozen_table` (flipping both to `cooperative_inject` resolves `cooperative_inject` on this harness) |
| cancel-and-replace | `cancel_turn`: `turn/interrupt`, the terminal `turn/completed` (`interrupted`) observed before the replacement `turn/start`; K1 passes `interrupted_turn_ref` so the cancelled leaf carries `interrupted` and the replacement's first point `replacement_start` | `interrupt_and_inject: cancel_and_replace`, `cancel: turn_boundary_guaranteed` | `test_cancel_turn_interrupts_and_observes_the_terminal_completion`; `tests/unit/codex/test_cognition_points.py::test_replacement_and_interrupted_roles_and_the_source_point`; conformance `interrupt_and_inject` |
| Stop Fence | reaches the thread through the projected Kernel Hooks: `.codex/hooks.json` `PreToolUse` → `.mission/hooks/kernel.py` → the worker's loopback callback (`HookCallbackService`, `mc.stop_fence` / gated `mc.operation_intent` ask `KernelHookFenceGate.before_effect`; a fenced effect is denied `STOP_FENCED`); hash trust of the handlers is verified with `hooks/list` at every launch | `fail_closed: true` | `tests/unit/codex/test_kernel_hooks.py`, `test_hook_trust.py` |
| fork | `seed_fork` above, through the fork saga and `LaneSeedHead` | `fork: emulated` (control), `fork: emulated` (delivery), `time_travel: R3/R3` | `tests/unit/codex/test_time_travel.py` |

**Why `interrupt_and_inject` is not flipped to `cooperative_inject` yet.** `resolve_interrupt_mode`
needs the frozen table and the describe to agree and the harness to implement `SteeringLane`: the last two
hold and the first is a one-row edit. It stays `cancel_and_replace` because (1) the conformance suite pins
`INTERRUPT_SEMANTICS = "cancel_and_replace"` for every lane (`tests/conformance/lanes/test_session_turns.py::
test_interrupt_and_inject_delivers_with_the_declared_semantics`, "cooperative_inject adds its expectation
here first"), a file outside this lane's ownership; (2) no test drives `InterruptAndInjectService` /
`LaneTurnService._steer` end to end with the Codex harness (the steer half is proven on the fixture, the
service half on a fake `_Steers` lane); (3) `turn/steer` semantics on codex-cli 0.162.1 (what the steered
text does to the running turn) are unverified live. Flip both rows together once (1) and (2) exist.

## Local vs cloud

`codex` (local): everything above. `codex_cloud`: architecture only. Evidence
(`docs/specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/codex_cloud/REVALIDATION-2026-10-09.md`,
MP-19): the only public automation surface is the experimental `codex cloud exec` / `codex cloud list
--json` plus local `codex apply`; follow-up, cancel, event observation, approval resume, usage and
lineage have no public operation; the automation credential for cloud tasks is undocumented. Hence:

- points: a task could carry at most `workspace_snapshot` points (the `branch@sha` a finished task applies
  to) and one `session_cursor` per task status poll; no step events exist to fold;
- reads: R0 (`time_travel` absent on the stub); a finished task's diff (`codex apply`) is a closure, not a
  state;
- forks: none; a "fork" would be a new task from the same environment and a branch, which is a new
  mission, not a seeded unit;
- interventions: `cancel`, `interrupt_and_inject`, `queue_instruction`, `pause`, `resume`, `fork`:
  `unsupported` (`LANE_COMMAND_SEMANTICS`, `CODEX_CLOUD_DESCRIBE`); the Stop Fence cannot reach a cloud
  task (no hooks run under cloud orchestration), so the fence can only refuse the next *local* effect
  that consumes the task's output.

Nothing of `codex_cloud` is implemented or tested by this record; every cell stays `unqualified` /
`unsupported`.

## Implemented / tested / integrated / blocked

| Item | Implemented | Tested (command → result) | Integrated | Blocked / unverified |
| --- | --- | --- | --- | --- |
| `turn_points` / `generation_points` (`adapters/codex/cognition_points.py`; harness `turn_points`, `PointCollectingLane`) | yes | `uv run pytest tests/unit/codex/test_cognition_points.py -q -p no:cacheprovider` → 6 passed (frames from a real `lane.turn` over the FIXTURE app-server) | no: K1 (`_settle` → `settle_lane_session(points=...)`) is Agent A's | |
| `CodexTimeTravel.read_as_of` R1/R2/R3 | yes | `uv run pytest tests/unit/codex/test_time_travel.py -q -p no:cacheprovider` → 13 passed | no: K3 registration (`provider_time_travel_lanes`) is Agent A's; `CognitionPointReadService.state_as_of` must call `registry.lane(profile, request_scope=...)` | R3 only while the thread is live in the reading process |
| `CodexTimeTravel.seed_fork` (R3 native, R3 reconstructed, R1), idempotent per fork request | yes | same suite: `test_a_turn_boundary_point_forks_the_thread_natively_and_is_idempotent`, `test_a_point_inside_a_later_turn_forks_through_the_previous_turn`, `test_a_point_inside_the_first_turn_seeds_a_reconstructed_transcript`, `test_without_a_live_thread_the_seed_is_a_transcript` | no: K2 (`CognitiveSeedService` admitting `fork ≥ R1`, recording `LaneSeedHead`) | `thread/fork` on the real app-server (schema-valid params, FIXTURE-served); `Thread.path` for the rollout copy; cross-process idempotency |
| harness `prepare`/`start`/`send_turn` honour `request.seed` | yes | same suite: `test_a_forked_thread_seed_is_resumed_by_the_derived_start`, `test_a_transcript_seed_starts_a_fresh_thread_with_the_preamble`, `test_a_fork_the_server_cannot_resume_falls_back_to_a_fresh_thread` | no: the seed head reaches `PrepareRequest.seed` only through K2 | `thread/resume` of a fork from a copied rollout on the real server |
| `collect_points` (K3 convention) | yes | `test_collect_points_re_derives_the_settlements_fold` | no: the reconciler passes `namespace`/generation per the convention (Agent A) | |
| describe cells `fork: emulated`, `time_travel R3/R3`; `thread/fork` in the protocol subset and the FIXTURE | yes | `uv run pytest tests/unit/codex -q -p no:cacheprovider` → 191 passed; `tests/unit/codex/test_schema_pin.py` validates `ThreadForkParams` against the pinned schema | describe aggregated by the existing registry | |
| conformance registration | exception `FORK_EMULATION` (conversation fork, not a workspace-snapshot restore) citing this lane's suites | `uv run pytest tests/conformance/lanes -q -p no:cacheprovider` (see LEDGER for the count) | | |
| `interrupt_and_inject` row | unchanged (`cancel_and_replace`) | existing suites | | see Interventions |
| integration (`tests/integration/codex`, `tests/integration/temporal/test_mp08_codex_lane_turns.py`) | n/a | run on the live compose stack: see LEDGER (baseline failures predate this work: `test_a_codex_turn_settles_...` asserts a child environment without `OPENAI_API_KEY` while the isolated api-key route forwards it) | | live drills (`MC_CODEX_HOOK_DRILL`, paid qualification) stay blocked on Windows / unauthorised |

## Kernel requests (for Agent A)

1. `application/execution/harness/lane_turns.py::_settle`: build `TurnPointsRequest` with
   `native=NativeRefs(session_ref=<thread id>, turn_ref=<turn id>)`, `terminal`, `interrupted` and
   `interrupted_turn_ref` from the dispatch journal, and pass `points=` to `settle_lane_session`; the
   fold reads `frames_of_turn` by `native_turn_ref`, so frames of a sub-agent thread (other turn ids)
   are excluded by construction.
2. `application/execution/cognition_point_reads.py::state_as_of` and `application/recovery/
   cognitive_seed.py`: call `registry.lane(record.lane_profile, request_scope=self._scope)` and set
   `ForkSeedRequest.request_scope`; `CodexTimeTravel` refuses an unscoped read with
   `TimeTravelUnsupported("request_scope_required")`.
3. `cognitive_seed.py`: admit `time_travel.fork ≥ R1` and record the receipt's `restore_level`/
   `history` on the `fork_seed` point; for cross-process idempotency, pass the recorded
   `fork_seed` point's `channel_facts.seed_head` back as the memo (the lane memoises in process only).
4. `adapters/temporal/deployment_composition.py`, `bootstrap/api.py`, `bootstrap/runtime_control.py`:
   `TimeTravelRegistry(...).register_all(provider_time_travel_lanes(frames, payload_store,
   codex=<harness or None>, claude=<harness or None>))` (`adapters/temporal/provider_lane_composition.py`).
5. `operations/point_reconciliation.py`: for session lanes call `collect_points(namespace=<harness
   execution id>, checkpointer_ref_digest=str(generation), ...)`; the result `thread_item` locators are
   `<thread>#<item id>` for items and `<thread>#<turn>:<ordinal>:<method>` for turn boundaries.
6. Conformance: extend `test_session_turns.py::INTERRUPT_SEMANTICS` to read the declared cell before
   `codex` flips to `cooperative_inject`.

## Provider facts not verified in this session

- `thread/fork` behaviour on codex-cli 0.162.1: that `lastTurnId` is honoured inclusively, that the forked
  thread is written to disk under the same `CODEX_HOME` and resumable by id, and the shape of `Thread.path`
  (`[UNSTABLE]` in the pinned schema). The lane validates the params against the pinned schema and the
  FIXTURE implements the documented semantics; no live call was made (paid calls not authorised, Windows
  worker cannot spawn the app-server).
- `turn/steer` effect on a running turn (text appended to the active turn's input) on the pin.
- Rollout file layout under `CODEX_HOME/sessions/` (only needed when `Thread.path` is absent).
