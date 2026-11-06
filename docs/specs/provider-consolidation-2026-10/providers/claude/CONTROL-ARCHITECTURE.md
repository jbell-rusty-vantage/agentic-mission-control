---
type: Specification
title: "Claude lanes: cognition points, time travel and intervention (claude_agent_sdk, claude_cloud)"
description: "Cross-provider control (2026-11-05) on the Claude Agent SDK lane: one session_cursor point per step boundary of a turn folded from the persisted frames at settlement, state-as-of reads at R1/R2/R3, seeded forks from the state-root transcript mirror truncated at the point and resumed under a new session id, the intervention mapping (queue, cancel-and-replace, Stop Fence through the in-process Kernel Hook callbacks) and the honest implemented/tested/integrated/blocked table; claude_cloud is architecture only."
tags: [mission-control, providers, claude_agent_sdk, claude_cloud, cognition-points, time-travel, interventions, cross-provider]
status: active
date: 2026-11-05
---

# Claude lanes: control architecture

Part of [cross-provider control](../cross-provider-control/DESIGN.md) (owner goal 2026-11-05) and
[ADR-0069](../../../../adr/0069-cross-provider-control-cognition-points-time-travel-and-intervention-on-every-lane.md).
Lane: `claude_agent_sdk` (claude-agent-sdk 0.2.165 Python over the bundled Claude Code 2.1.294, one
`ClaudeSDKClient` subprocess per session on a Linux/WSL worker); stub: `claude_cloud` (architecture only).
Owner framing: the control below does not depend on whether the session writes a report or commits.

## What remains for the goal, what this closes, the next proof

- **Remains**: the kernel wiring (K1 settlement call, K2 seed head to `prepare`/`start`, K3 registry
  composition) is Agent A's; no live CLI has resumed a transcript Mission Control truncated (drill below);
  the derived unit's workspace is not restored by a conversation fork; `pause` stays `unqualified`.
- **Closed here**: the lane-side half of DESIGN §4: `adapters/claude/cognition_points.py` (`turn_points`,
  `generation_points`), `adapters/claude/time_travel.py` (`ClaudeTimeTravel`: `read_as_of` R1/R2/R3,
  `seed_fork` R3 reconstructed / R1, `collect_points`), the harness port (`transcript_entries`) and seed
  honouring (`prepare` writes the staged transcript under the derived session id, `start` resumes it,
  the first `send_turn` carries the injected message), the describe cells (`fork: emulated`,
  `time_travel: R3/R3`), the FIXTURE client's `resume` and transcript mirroring, and the unit suites.
- **Next proof**: an integrated run on real PostgreSQL + Temporal once K1–K3 land (`tests/integration/
  temporal/test_mp07_claude_lane_turns.py` extended with a points read), then the fake-CLI resume worker
  (`tests/unit/claude/resume_worker.py`, Linux) driving a truncated transcript, then the owner-run drill.

## SDK messages and hook callbacks to point boundaries

The lane persists every SDK message as a Provider Frame (`adapters/claude/frames.py`, MP-13 keys
`claude:<message uuid>[:<block>]:<raw_kind>`; the lane's own `claude:<session>:lane:<n>:<raw_kind>` for
hook and permission frames). The fold (`frame_boundary_points`) runs with `CLAUDE_STEP_KINDS =
STEP_KINDS ∪ {before_compaction}`.

| SDK message / hook callback | Frame kind | Point boundary | `step_ref` of the point |
| --- | --- | --- | --- |
| `SystemMessage(init)` + the Discovery Proof | `session_init`, `status` | no (folded into the first boundary) | |
| (the user prompt the lane sends: the SDK does not echo it) | — | no `turn_started` frame exists: the first point of a turn is its first boundary, `source: input`, role `intermediate` | |
| `AssistantMessage` (text, `tool_use` blocks) | `message` (+ `tool_call_started` per `tool_use` block) | yes | `<uuid>::assistant` |
| `UserMessage` with `tool_result` blocks (`is_error`) | `tool_call_completed` / `tool_call_failed` per block | yes | `<uuid>:<block>:user.tool_result` (`tool_call_ref` = `tool_use_id`) |
| `UserMessage` text (a prompt the session injected) | `message` | yes | `<uuid>::user` |
| Kernel Hook callbacks (`PreToolUse` → `before_tool` / `before_shell` / `before_mcp`, `PostToolUse`, `SubagentStart/Stop`, `Stop`, `SessionStart/End`, `UserPromptSubmit`; `hooks.py`) | `hook_invoked` / `hook_result` | no (folded into the tool close they gate); `before_compaction` from `PreCompact` **is** a boundary | `<session>:lane:<n>:hook.invoked` |
| `can_use_tool` permission (MP-11) | `approval_requested` / `approval_resolved` | resolved: yes | `<session>:lane:<n>:permission.resolved` |
| `Task*Message`, `system.hook_*`, `rate_limit_event`, `conversation_reset`, `api_retry`, `StreamEvent` | status / deltas | no | |
| messages of a subagent (`parent_tool_use_id`) | as above with `subordinate_ref = claude:task:<tool_use_id>` | yes, facts carry `subordinate_ref`, never seedable | |
| `ResultMessage` | `result.turn_ended` → `turn_ended`; `result` → `run_result` | yes; the result point carries `leaf`, `result` | `<uuid>::result.turn_ended`, `<uuid>::result` |
| the lane's synthesized `result` after a process exit | `turn_ended`, `run_result` (`synthesized_from: process_exit`) | yes, source `loop`, facts `terminal_reason` | `mc-synth-<turn>::result` |

Identity (DESIGN §5): `SessionCursorPoint(session_ref=<session_id>, turn_ref=<user message uuid the lane
stamped on the send>, step_ref=<provider key tail>)`. Usage: the SDK emits no `usage` frame; each
`assistant` message carries that model call's `usage`, so a point's `usage_delta` is the sum over the
assistant frames of its range (`tokens.input/output/cache_read/cache_creation/total`); the `result`'s
totals are facts (`result_usage`), never added. Facts: `session_id`, `message_uuid`, `model`,
`stop_reason`, `tool_names`, `text_bytes`/`text_digest` (never text), `tool_use_id`, `is_error`,
`result_digest`, `subtype`, `num_turns`, `duration_ms`, `terminal_reason`, `hook_event`,
`permission_decision`; `redact_value` runs over them. Several native turns in one generation fold through
`generation_points` → `fold_generation_points` (`interrupted`, `replacement_start`, one `result`).

## Restore levels

| Port | Level | Mechanism | Why not higher |
| --- | --- | --- | --- |
| `read_as_of` | R1 (always) | messages reconstructed from the frames to the point: assistant text + `ToolCallFact`s (redacted `input`), tool results, user prompts, errors; `history: reconstructed` | excerpted bodies are withheld with a digest |
| `read_as_of` | R2 | plus `files` of the continuation workspace snapshot the point names (`claude-workspace:<manifest ref>`) | the MP-04 custody snapshot is a git patch, not a file list |
| `read_as_of` | R3 | the state-root transcript mirror (`.mission/state/claude/sessions/<project>/<session>.jsonl`, written by the SDK through `ClaudeAgentOptions.session_store`) read through the harness (`transcript_entries`) and cut at the point's message uuid (`truncate_entries`; a uuid the mirror lacks falls back to R1, never a guessed cut); `history: native` | the mirror lives in the lease; after cleanup only the frames remain |
| `seed_fork` | R3 reconstructed | the mirror through the point's uuid, every entry rewritten to the derived session id (`uuid5(fork_request_id)`, deterministic), staged as `<derived>.jsonl`; the derived `prepare` writes it under its own state root (`project_key_for_directory(lease)`), `start` runs `ClaudeAgentOptions(resume=<derived id>)` and the transport restores the mirror into the CLI config dir before the spawn (`restore_resume_session`, MO-73); `fork_session` is **not** set (the id is minted here; the source id is never resumed) | the CLI loads a transcript Mission Control truncated: provider-owned state, Mission-Control-made history |
| `seed_fork` | R1 | no mirror readable: the transcript rebuilt from the `user`/`assistant`/`user.tool_result` frames (`entries_from_frames`, `reconstructed_from: frames`, tool-result blocks of one uuid merged) | fidelity of a rebuilt transcript on the real CLI is unverified |

The SDK also offers `resume_session_at` + `resume_drops_turn` + `fork_session` (a CLI-side truncating
fork). Not used here: it keeps the source id as the resume target and lets the CLI mint the derived id
after the fact, which the fork saga cannot record before `start`; the chosen path keeps the derived id
known at seed time and the source transcript untouched. Native artifacts: `seed_kind`
(`transcript_mirror` | `transcript_frames`), `source_session_id`, `derived_session_id`, `transcript_ref`,
`transcript_entries`, `truncated_at_uuid`, `truncation` (`exact` | `point_not_in_mirror`),
`point_turn_uuid`, `seed_head`, `seed_head_message_count`. The injected message is the first turn's
preamble (`seed_prefix`), not a transcript entry (an unanswered user entry would replay as a pending
prompt). Derived `start`: resumed → `native_details.seed_restore = "R3"`; the CLI refuses the resume
(`SessionEnded`) → fresh session, `seed_restore = "R1"`, logged; `forked_from` names the source session.

## Interventions

| Intervention | Mechanism on `claude_agent_sdk` | Row / cell | Evidence |
| --- | --- | --- | --- |
| queue | `command_mailbox` at the turn boundary; `send_turn` while a turn (or its interrupted drain) runs answers `busy` | `queue_instruction: turn_boundary_guaranteed`, `resume: turn_boundary_guaranteed` | conformance `send_turn while busy` |
| steer | none: the SDK has no steer-into-running-turn operation (`query` during a turn queues; `interrupt` aborts) | `interrupt_and_inject: cancel_and_replace` (unchanged) | `tests/unit/claude/test_claude_controls.py::test_interrupt_and_inject_through_lane_turn_replaces_inside_the_segment` |
| cancel-and-replace | `cancel_turn`: `ClaudeSDKClient.interrupt()`, the aborted `ResultMessage` (`terminal_reason` `aborted_streaming` / `aborted_tools`) drained before the replacement send; K1 passes `interrupted_turn_ref`: the cancelled leaf carries `interrupted`, the replacement's first point `replacement_start` | `cancel: turn_boundary_guaranteed` | `tests/unit/claude/test_cognition_points.py::test_replacement_and_interrupted_roles_and_the_source_point` |
| Stop Fence | in-process Kernel Hook callbacks (`hooks.py`: `mc.stop_fence` / gated `mc.operation_intent` on `before_tool`, `before_shell`, `before_mcp`, `subagent_start` ask `KernelHookFenceGate.before_effect`; a fenced effect is denied with `permissionDecision: deny`, `STOP_FENCED`); `can_use_tool` never allows a fenced run | `fail_closed: true` | `tests/unit/claude/test_claude_approvals.py` (fence never allows), `test_claude_harness.py` (hook ran in-process) |
| fork | `seed_fork` above through the fork saga and `LaneSeedHead` | `fork: emulated` (control and delivery), `time_travel: R3/R3` | `tests/unit/claude/test_time_travel.py` |

## Local vs cloud

`claude_agent_sdk` (local): everything above. `claude_cloud`: architecture only. Evidence
(`docs/specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/claude_cloud/REVALIDATION-2026-10-09.md`,
MP-18): no public operation for status, cancel/interrupt, event replay, idempotent create or a pending
approval answer on Anthropic-hosted sessions; follow-up is `claude --cloud` queueing a message (no
message id); hooks fire in cloud sessions but only repository-committed hooks reaching our endpoint
through the environment's network allowlist; usage is push-only telemetry; `--teleport` pulls a session
local (interactive). Hence:

- points: one `session_cursor` per queued follow-up and per hook callback our endpoint receives (push,
  no cursor, no replay); no observable per-step stream to fold;
- reads: R0 on the stub (`time_travel` absent); a teleported session would be a *local* `claude_agent_sdk`
  session from then on, which is the local→cloud→local continuity goal, not this record;
- forks: none (no fork/continue API; `--teleport` is interactive);
- interventions: `queue_instruction: wait_then_send` (the queued message), `interrupt_and_inject:
  cancel_and_replace` only in intent (no cancel exists: `cancel: unsupported`), `pause`/`resume`
  boundary-only; the Stop Fence reaches a cloud session only through a repository-committed `PreToolUse`
  hook calling our endpoint (`fail_closed: false` on the stub: the hook may not run), so a fence cannot be
  promised there.

Nothing of `claude_cloud` is implemented or tested by this record; every cell stays `unqualified` /
`unsupported`.

## Implemented / tested / integrated / blocked

| Item | Implemented | Tested (command → result) | Integrated | Blocked / unverified |
| --- | --- | --- | --- | --- |
| `turn_points` / `generation_points` (`adapters/claude/cognition_points.py`; harness `turn_points`, `PointCollectingLane`) | yes | `uv run pytest tests/unit/claude/test_cognition_points.py -q -p no:cacheprovider` → 5 passed (frames from a real `lane.turn` over the FIXTURE client, incl. the subagent fixture) | no: K1 is Agent A's | |
| `ClaudeTimeTravel.read_as_of` R1/R2/R3 | yes | `uv run pytest tests/unit/claude/test_time_travel.py -q -p no:cacheprovider` → 11 passed | no: K3 registration; `state_as_of` must bind the request scope | R3 only while a lease on the reading worker holds the mirror |
| `ClaudeTimeTravel.seed_fork` (R3 reconstructed, R1), deterministic derived id, idempotent per fork request | yes | same suite: `test_seed_fork_truncates_the_mirror_under_a_new_session_id_and_is_idempotent`, `test_without_a_mirror_the_transcript_is_rebuilt_from_frames`, `test_truncation_never_guesses_a_later_cut` | no: K2 | a truncated mirror resumed by the real CLI (fixture only); cross-process idempotency by memo |
| harness `prepare`/`start`/`send_turn` honour `request.seed` | yes | same suite: `test_the_derived_start_resumes_the_staged_transcript`, `test_a_seed_without_a_transcript_starts_a_fresh_session`, `test_a_resume_the_cli_refuses_falls_back_to_a_fresh_session` | no: the seed head reaches `PrepareRequest.seed` only through K2 | real `--resume` of the staged file (the FIXTURE refuses a resume the store never mirrored, as the CLI does) |
| `transcript_entries` port; FIXTURE client `resume` + mirroring under `project_key_for_directory(cwd)` | yes | `uv run pytest tests/unit/claude -q -p no:cacheprovider` → 159 passed (existing suites unchanged in outcome) | | |
| `collect_points` (K3 convention) | yes | `test_collect_points_re_derives_the_settlements_fold` | no: reconciler convention (Agent A) | |
| describe cells `fork: emulated`, `time_travel R3/R3` | yes | `test_claude_harness.py::test_the_proposed_describe_is_honest_and_unqualified` | describe aggregated by the existing registry | |
| conformance registration | exception `FORK_EMULATION` citing this lane's suites | `uv run pytest tests/conformance/lanes -q -p no:cacheprovider` (count in LEDGER) | | |
| integration (`tests/integration/claude`, `tests/integration/temporal/test_mp07_claude_lane_turns.py`) | n/a | run on the live compose stack: see LEDGER | | live drills (paid qualification) unauthorised; subprocess drills blocked on Windows |

## Kernel requests (for Agent A)

1. `_settle`: `TurnPointsRequest(native=NativeRefs(session_ref=<session_id>, turn_ref=<stamped user
   message uuid>), terminal=..., interrupted=..., interrupted_turn_ref=<from the replace journal>)`; the
   fold needs the turn's frames only (`frames_of_turn` by `native_turn_ref`; the lane attributes hook and
   permission frames to the active turn already).
2. `state_as_of` / `cognitive_seed.py`: `registry.lane(profile, request_scope=...)` and
   `ForkSeedRequest.request_scope` (unscoped reads are refused `request_scope_required`).
3. `cognitive_seed.py`: admit `fork ≥ R1`; record `restore_level`/`history`; replay the recorded
   `seed_head` as the memo for cross-process idempotency (the derived session id is deterministic, so a
   repeat stages the same file under the same name).
4. Composition: `TimeTravelRegistry(...).register_all(provider_time_travel_lanes(frames, payload_store,
   claude=<harness or None>, codex=<harness or None>))`.
5. `point_reconciliation.py`: `collect_points(namespace=<harness execution id>,
   checkpointer_ref_digest=str(generation), ...)`; locators are `<session>#<turn uuid>#<step_ref>`.
6. The derived unit's `harness_execution_id` differs from the source's: the transcript mirror a fork
   reads is the *source lease's*; the seed artifact carries it across leases, so cleanup of the source
   lease after the fork is safe.

## Provider facts not verified in this session

- That Claude Code 2.1.294 resumes a transcript whose tail Mission Control removed (`--resume=<new id>`
  over a file the SDK did not write) and continues from its last assistant entry; the fake CLI
  (`tests/unit/claude/fake_cli.py`) does, the real one was not run (Windows worker, no paid call).
- The exact JSONL entry shape the SDK mirrors (`sessionId` vs `session_id`, `parentUuid` chains); the
  lane rewrites both spellings and leaves other fields untouched.
- `fork_session` + `resume_session_at` behaviour (documented in `claude_agent_sdk.types`; not exercised).
