---
type: Ledger
title: "Cross-provider control ledger"
description: "Per-agent record of the 2026-11-05 cross-provider control build (cognition points, time travel and intervention on every lane): what was implemented, tested, integrated, blocked, and the kernel requests."
tags: [mission-control, providers, consolidation, cross-provider, ledger]
status: active
date: 2026-11-05
---

# Cross-provider control ledger

Brief: [DESIGN](DESIGN.md). One section per agent, appended in build order. Integrated on `main` as `0d2cc6b5`
(2026-11-06); the next session's instruction is [NEXT-SESSION-LIVE-FIXTURES](NEXT-SESSION-LIVE-FIXTURES.md).


## Agent B: `claude_managed` and `codex_agents` (2026-11-05)

Documents: [claude_managed CONTROL-ARCHITECTURE](../anthropic_managed/CONTROL-ARCHITECTURE.md),
[codex_agents CONTROL-ARCHITECTURE](../openai_agents/CONTROL-ARCHITECTURE.md) (lifecycle to point
tables, identity, restore levels, intervention mapping, kernel requests KR1 to KR6).

**Remaining for the goal on these lanes:** K1/K2/K3 wiring (Agent A), the describe-refresh
migration for the `time_travel` cells (KR4), a paid drill qualifying steering and a seeded fork.

**Implemented (new files):** `adapters/remote_session/cognition_points.py` (the shared hosted
fold over `frame_boundary_points`: input-role correction, per-step and terminal usage,
`generation_points`), `adapters/remote_session/time_travel.py` (`RemoteSessionTimeTravel`: R1
`read_as_of`, idempotent write-free `seed_fork` as a hydration prompt, `collect_points`;
`ScopedFrameReader`, `seed_turn_text`, `seed_metadata`), `adapters/anthropic_managed/
{cognition_points,time_travel}.py` (`session_cursor` keyed by event id; `ClaudeManagedTimeTravel`),
`adapters/openai_agents/{cognition_points,time_travel}.py` (`thread_item` keyed
`session#turn#item`; `CodexAgentsTimeTravel`). **Changed:** both harnesses (`turn_points`,
`steer`, seed honored by `prepare`/`start`/`send_turn`, steer ids excluded from send
reconciliation on Managed), both describes (`time_travel=LaneTimeTravel(read="R1", fork="R1")`),
`adapters/temporal/hosted_lane_composition.py::compose_hosted_time_travel`, the fakes
`tests/fixtures/managed_agents.py` and `tests/fixtures/agents_lane.py` (a message during a held
turn steers it). `LANE_COMMAND_SEMANTICS` rows unchanged (`cancel_and_replace`); conformance
claims unchanged.

**Tested:** `uv run pytest tests/unit/anthropic_managed tests/unit/openai_agents
tests/unit/remote_session tests/conformance/lanes -q -p no:cacheprovider` → 505 passed, 4 skipped,
2 failed (both `codex` lane: `test_registry[codex]`, `test_a_fork_is_emulated...[codex]`, Agent C's
concurrent fork claim, not these lanes). New tests: `tests/unit/anthropic_managed/
test_cognition_points.py` (5), `test_time_travel.py` (5), `tests/unit/openai_agents/
test_cognition_points.py` (5), `test_time_travel.py` (5), helper
`tests/unit/remote_session/hosted_support.py`. `uv run mypy src/mission_control/adapters/
anthropic_managed src/mission_control/adapters/openai_agents src/mission_control/adapters/
remote_session src/mission_control/adapters/temporal/hosted_lane_composition.py` → clean. Describe
side effect: `tests/unit/harness/test_lane_contracts.py` fails 2 (persisted describe documents no
longer equal the declared ones) until KR4's migration lands; `test_describe_honesty.py` passes.

**Integrated:** none of the above reaches settlement, reads or forks until K1 to K3 are wired.
Integration suites against the local stack (`tests/integration/anthropic_managed`,
`tests/integration/openai_agents`): 2 failed, 6 skipped (paid opt-ins) both before and after this
work; the two failures are the worker-loss reattach tests raising `history close execution is no
longer live` (`adapters/postgres/lanes/execution_state.py:151`), a baseline defect outside these
lanes.

**Blocked / unverified:** paid provider calls (not authorized); native session fork or history
import on either API (assumed absent: R3 refused); Q-M1 / OA-D5 steering races (`steer` is
implemented and fake-tested, not declared).

## Agent C: `codex`, `claude_agent_sdk` (+ `codex_cloud`, `claude_cloud` architecture) (2026-11-05)

Documents: [codex CONTROL-ARCHITECTURE](../codex/CONTROL-ARCHITECTURE.md), [claude
CONTROL-ARCHITECTURE](../claude/CONTROL-ARCHITECTURE.md) (event-to-boundary tables, identity, restore
levels, intervention mapping with the Stop Fence reach, local vs cloud, kernel requests 1 to 6).

**Remaining for the goal on these lanes:** K1/K2/K3 wiring (Agent A); the 0073 describe refresh
re-rendered after these describes moved (`uv run --no-sync python scripts/prepare_release_1140.py
--render`: `tests/unit/harness/test_lane_contracts.py` fails 2 until then,
`test_lane_profile_migrations_end_at_exactly_the_declared_describes` and
`test_frozen_0040_and_additive_0042_are_exact_generated_text`, the diff being `controls.fork`
`unqualified` → `emulated` on both lanes); the conformance pin `INTERRUPT_SEMANTICS =
"cancel_and_replace"` before `codex` can flip to `cooperative_inject` (kept `cancel_and_replace`,
reasons in the codex record); a live `thread/fork` / truncated `--resume` drill.

**Implemented (new files):** `adapters/codex/cognition_points.py` (`thread_item` points keyed by
item id, usage from `thread/tokenUsage/updated`, content-free facts, `generation_points`),
`adapters/codex/time_travel.py` (`CodexTimeTravel`: R1/R2/R3 `read_as_of`, `seed_fork` R3 native
through `thread/fork lastTurnId` at a turn boundary, R3 reconstructed inside a turn, R1 transcript
without a live thread, idempotent per fork request, rollout copy when `Thread.path` is reported;
`collect_points`), `adapters/claude/cognition_points.py` (`session_cursor` points with the provider
key tail as `step_ref`, usage from `assistant` messages, `before_compaction` as a boundary),
`adapters/claude/time_travel.py` (`ClaudeTimeTravel`: R1/R2/R3 `read_as_of` over the state-root
mirror, `seed_fork` = the mirror truncated at the point under `uuid5(fork_request_id)`, R1 rebuilt
from frames; `collect_points`). **Changed:** `adapters/codex/protocol.py` (`M_THREAD_FORK`,
`ThreadForkParams`/`ThreadForkResponse`, `Thread.path`/`forkedFromId`), both harnesses
(`turn_points`, the provider ports `thread_history`/`fork_thread` and `transcript_entries`,
`prepare`/`start`/first `send_turn` honouring `LaneSeedHead`, `seed_restore`/`forked_from` on the
handle), both describes (`fork: emulated`, `time_travel=LaneTimeTravel(read="R3", fork="R3")`),
`adapters/temporal/provider_lane_composition.py::provider_time_travel_lanes` (K3 factory for
`TimeTravelRegistry.register_all`), the FIXTURE app-server (`thread/fork` over the shared disk), the
FIXTURE SDK client (`resume` honoured, a resume the store never mirrored refused, user/assistant
messages mirrored under `project_key_for_directory(cwd)`), `tests/unit/codex/support.py` (shared
custody/inputs between a source and a derived stack), the two conformance adapters (declared
`FORK_EMULATION` exception: a conversation fork from a point, not a workspace-snapshot restore),
`tests/unit/codex/test_schema_pin.py` (`ThreadForkParams` validated against the pin) and the two
describe assertions in the existing harness suites. `LANE_COMMAND_SEMANTICS` rows unchanged.

**Tested:** `uv run pytest tests/unit/codex -q -p no:cacheprovider` → 191 passed (new:
`test_cognition_points.py` 6, `test_time_travel.py` 13); `uv run pytest tests/unit/claude -q -p
no:cacheprovider` → 159 passed (new: `test_cognition_points.py` 5, `test_time_travel.py` 11);
`uv run pytest tests/conformance/lanes -q -p no:cacheprovider` → 211 passed, 4 skipped;
`uv run pytest tests/unit/harness -q -p no:cacheprovider` → 379 passed, 6 failed (4 `test_cursor_local`
closing-facts cases, Agent A's lane; the 2 describe-refresh cases above); `uv run ruff check` /
`ruff format` on every owned file clean; `uv run mypy src/mission_control/adapters/codex
src/mission_control/adapters/claude src/mission_control/adapters/temporal/provider_lane_composition.py`
→ clean (40 files). Every proof is FIXTURE-level: no provider call, no subprocess (Windows worker).

**Integrated:** nothing reaches settlement, reads or forks until K1 to K3 land. Integration suites on
the live compose stack (PostgreSQL 16 + Temporal, disposable PG17), before this work:
`tests/integration/codex` 5 passed 3 skipped; `tests/integration/claude` 4 passed 1 skipped;
`test_mp07_claude_lane_turns.py` 3 passed; `test_mp08_codex_lane_turns.py` 2 passed 3 failed
(`test_a_codex_turn_settles_...` asserts a child environment without `OPENAI_API_KEY` while the isolated
api-key route forwards it; the other two share the stack's state); `test_mp12_continuation.py` 3 failed
in the batch run, the first failing case passing alone (timing on the shared stack). After this work:
`tests/integration/codex` 5 passed 3 skipped; `tests/integration/claude` 4 passed 1 skipped;
`test_mp07_claude_lane_turns.py` 3 passed; `test_mp08_codex_lane_turns.py` 2 passed 3 failed (the same
three as the baseline); `test_mp12_continuation.py` 3 passed. Unchanged by this work: the three
mp08 failures predate it, the mp12 batch failures were the stack's timing.

**Blocked / unverified:** paid provider calls (not authorised); `codex app-server` and the Claude CLI
cannot spawn on this Windows worker (the live drills and `tests/unit/claude/test_claude_resume.py`'s
fake-CLI worker stay unrun); `thread/fork` semantics on codex-cli 0.162.1 (`lastTurnId` inclusive, the
fork resumable by id, `Thread.path` "[UNSTABLE]"); `turn/steer`'s effect on a running turn; Claude Code
2.1.294 resuming a transcript Mission Control truncated; the exact mirrored JSONL entry shape.


## Agent A: `cursor_local`, `cursor_cloud` and the kernel K1 to K3 (2026-11-05)

Document: [cursor CONTROL-ARCHITECTURE](../cursor/CONTROL-ARCHITECTURE.md) (lifecycle and hook
events to point boundaries, identity, restore levels, intervention mapping, kernel notes).

**Remaining for the goal:** the describe-refresh migration for every lane's `time_travel` cell
(integrator, release 1.14.0 / 0073); a session-lane `lane.turn` on real Temporal *with the
Postgres lineage* (the Temporal proof runs the scripted lane on the in-memory lineage, the
Postgres proof writes a Cursor-shaped batch directly); a seeded fork through `missionctl run
fork --point` on real services; the reconciler walking session-lane generations (it walks
checkpoint transitions only); `session_turn.point_ref` for session lanes (K6); the paid drill.

**Kernel conventions settled (B and C verified against these):**
- `TurnPointsRequest` (per native turn of the generation) carries `native=NativeRefs(session_ref,
  turn_ref)`, `turn_no`, `frames` (that turn's frames, lifecycle frames assigned to the turn in
  progress), `facts`, `attempt_ref` (`activity_attempt_observation_id`), `terminal` (last turn of
  the generation), `interrupted` (this turn was cancelled by a `cancel_and_replace`),
  `interrupted_turn_ref` (the turn this one replaced), `source_point` (the previous generation's
  result point, or the `fork_seed` point, on the first turn only), `operation` (None from the
  reconciler). `frame_boundary_points` gained `interrupted_leaf`, `is_input` (KR2) and
  `usage_kinds`; `fold_generation_points` / `generation_turns` chain the turns.
- Points are written by `settle_lane_session(points=...)` → `_settle(points=..., points_written_by
  ="adapter", admitted=<admit_attempt>)`; a cross-kind parent inside the generation names
  `parent_point` beside `parent_locator` (`compose_points` derives the id with the parent's kind).
- Time travel: `TimeTravelLane` signatures unchanged; `ScopedTimeTravelLane.for_scope(scope)`;
  `TimeTravelRegistry.lane(profile, request_scope=)` binds it; `ForkSeedRequest.request_scope`;
  the read service, seed service, fork-seed activity and reconciler pass their scope;
  `TimeTravelRegistry.register_all(lanes)`; `scoped_lane(profile, factory)` wraps a per-scope
  factory (B's `compose_hosted_time_travel`). `collect_points(namespace=<harness execution id>,
  checkpointer_ref_digest=str(generation), source_locator=None, result_locator=<result locator>)`.
- Seeds: admitted at `time_travel.fork` ≥ R1; a non-checkpoint head is recorded as
  `channel_facts.seed_head` (`mc.lane_seed_head.v1`) on the `fork_seed` point with the receipt's
  `restore_level`/`history`; an existing `fork_seed` point is replayed; `LaneTurnService` hands
  the head to `prepare(seed=)`/`start(seed=)` for a generation-1 unit.
- KR3: `_steer` stages the follow-up text (`stage_turn(heid, key, text)`) before `harness.steer`.

**Implemented (new files):** `application/execution/harness/points.py` (extended: see above),
`adapters/cursor/cognition_points.py`, `adapters/cursor/time_travel.py`,
`bootstrap/session_time_travel.py`. **Changed:** `harness/lane_turns.py` (K1 `_turn_points`,
`_source_point`, `_replacement_map`; K2 `_seed_head` → `PrepareRequest.seed`/`StartRequest.seed`;
`points=` constructor arg; KR3), `operations/operation_execution.py` (`settle_lane_session(points=)`,
lane profile from the binding in `_settle`), `operations/point_reconciliation.py` (scope-bound lane,
session convention), `execution/cognition_points.py` (parent kind), `execution/cognition_point_reads.py`
(scope), `harness/time_travel.py` (`ScopedTimeTravelLane`, `ScopedLaneFactory`/`scoped_lane`,
`register_all`, `lane(request_scope=)`, `ForkSeedRequest.request_scope`, docstring convention),
`recovery/cognitive_seed.py` (K2), `adapters/temporal/activities/fork_seed.py` (scope),
`adapters/temporal/deployment_composition.py` (`_worker_time_travel(lanes=)`, `_session_time_travel`),
`bootstrap/api.py` (`compose_time_travel` always builds the registry, `ApplicationFrameReaders`,
`PayloadSnapshotReader`, per-application registration), `bootstrap/runtime_control.py`
(`register_all`), `adapters/cursor/{local,cloud,describe}.py` (seed restore and hydration, end-session
memo, `turn_points`, cloud `branches` property, `time_travel=LaneTimeTravel(read="R2", fork="R2")`),
`tests/fixtures/lane_turns.py` (`lane_stack(points=)`).

**Tested (unit):** `uv run pytest tests/unit/harness/test_lane_turn_points.py
tests/unit/recovery/test_session_lane_seed.py tests/unit/cursor/test_cognition_points.py
tests/unit/cursor/test_time_travel.py -q -p no:cacheprovider` → 18 passed;
`tests/unit/operations/test_cognition_points.py` → the new `session_cursor` batch test passes;
`uv run pytest tests/unit/cursor -q` → 216 passed; floor `uv run pytest tests/unit/harness
tests/unit/operations tests/unit/recovery tests/conformance/lanes -q -p no:cacheprovider` →
1209 passed, 14 skipped, 8 failed, all 8 pre-existing or integrator-owned: 4 ×
`test_cursor_local.py::test_closing_facts_map_every_run_result_status` and
`test_rrm_008_cancellation.py::test_cancel_before_dispatch_settles_cancelled_without_cognition`,
`test_terminal_evidence_adoption.py::test_finished_evidence_adopts_without_native_control_and_normal_family_quarantines`
(reproduced against `HEAD`'s exported `src`), 2 × `test_lane_contracts.py` (describe migration).
`ruff check`, `ruff format --check` and `mypy` pass on every touched source file.

**Tested (integration, stack up, no paid call):** `tests/integration/temporal/test_lane_turn.py` →
15 passed (incl. the new `test_a_session_lane_settlement_writes_its_cognition_points_through_the_workflow`);
`tests/integration/postgres/test_session_lane_points_postgres.py` → 1 passed (new);
`test_ft_f2_inject_postgres.py` → 1 passed; `test_ft_f4_fork_postgres.py` → 2 passed;
`test_ft_g4_lane_controls_postgres.py` → 2 passed; `test_checkpoint_lineage_postgres.py` → 4 passed;
`tests/integration/cursor/test_cursor_cloud_fixtures.py` → 2 passed; `test_kernel_hook_roundtrip.py`
→ 3 passed; `test_cursor_local_fixtures.py` → 3 passed, 1 failed (`precompact`, pre-existing);
`test_mp09_cloud_segment_loop_real_services.py` → 2 failed (pre-existing, `history close execution
is no longer live`). Both pre-existing failures reproduce with `HEAD`'s source.

**Integrated:** K1/K2/K3 wired in the worker, operator API and technical API compositions; B's and
C's lanes registered through `session_lane_time_travel`. **Not qualified:** nothing here is a
live or paid proof.

**Kernel requests (integrator):** the describe-refresh migration (0073) from the final matrices;
K6 (`session_turn.point_ref` for session lanes); the reconciler's generation walk for session lanes
(`list_run_generations` is transition-based).
