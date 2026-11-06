---
type: Concept
category: execution
title: Lanes and the harness protocol
description: The provider-neutral AgentHarness protocol and lane registry that every provider adapts to (Deep Agents is the reference), the nine lane profiles and their describe matrices, the lane.turn segment loop, attempt recording, the one sealed lane binding, qualification flags, and the goal of one session across local and cloud lanes.
tags: [mission-control, harness, lanes, deep-agents, adapters, implementation, goal]
aliases: [AgentHarness, lane registry, lane profile, lane describe, adapter shape]
questions:
  - How does the harness drive a lane turn, and which lanes exist?
  - What shape must a new provider adapter follow?
  - Which lanes are qualified and what does the flag mean?
  - Where does a lane compile, bind and rebind its sealed binding?
  - Can one session move between a local and a cloud lane?
updated: 2026-11-01
---

# Lanes and the harness protocol

A [Harness](../../GLOSSARY.md) is the protocol; a [Lane](../../GLOSSARY.md) is one qualified
implementation of it; a [Lane Profile](../../GLOSSARY.md) is one placement of a lane with its own
control matrix; an [Agent Host](../../GLOSSARY.md) is a tool a human works in that reads generated
configuration. A host is where authoring happens; a lane is where mission work executes. Keep the
three apart when reading code, because the package directory for the Deep Agents lane is called
`adapters`.

## The protocol as implemented

`application/execution/harness/protocol.py::AgentHarness` is `describe` plus nine operations: `prepare`, `start`, `reattach`, `send_turn`, `cancel_turn`, `observe`, `snapshot`, `usage`,
`end_session`. A lane that declares an operation `unsupported` or `unqualified` raises `HarnessUnsupported` for it; any other error from it is a conformance failure. `observe` resumes
from an opaque lane cursor (LangGraph checkpoint id, bridge offset, SSE event id). Wire contracts are in `domain/execution/lanes.py` (`mc.lane_describe.v1` and `.v2`, request and handle
contracts, `mc.cursor_binding.v2`), `domain/execution/bindings.py` (`mc.execution_binding.v2`, `mc.environment_binding.v1`, `mc.workspace_snapshot.v1`) and
`domain/execution/approvals.py` (`mc.approval_binding.v1`, [ADR-0035](../adr/0035-seven-lane-profiles-versioned-provider-contracts-and-mission-v2.md)). Handles carry native identity,
never credentials. `host_support.LaneProfile` is the one profile vocabulary, nine values: `deep_agents`, `cursor_local`, `cursor_cloud`, `claude_agent_sdk`, `codex`, `claude_cloud`, `codex_cloud`,
`claude_managed`, `codex_agents` ([ADR-0050](../adr/0050-nine-lane-profiles-claude-managed-and-codex-agents-and-the-mission-data-class.md)). Native completion becomes an attempt result plus a
candidate, never accepted output; unknown native state blocks a duplicate launch until reconciliation.

## The adapter shape every provider follows

The owner's plan is to support every provider through adapters shaped like Deep Agents, the most refined ([Deep Agents lane](deep-agents-lane.md)). The shape, in order:

1. **Describe** (`adapters/<lane>/describe.py`): a matrix of controls (`native`, `emulated`, `unsupported`, `unqualified`), delivery semantics, identity map, hooks, subagents, usage, placement and
   time travel, plus a `LaneDeclaration` (model routes, item and family support, pins) the application aggregates (`application/execution/harness/describe.py`). `deep_agents` keeps the
   digest-stable `v1` matrix; the Cursor, Claude SDK, Codex, Managed and Agents profiles have `v2` matrices with per-feature evidence; `claude_cloud` and `codex_cloud` are `v2` stubs.
2. **Compile**: a pure function from the neutral `mc.agent_configuration.v2` to a sealed lane binding and a receipt ([agent configuration](agent-configuration.md)). Only Deep Agents
   compiles today; the others register the describe-only compile and are admitted against their declaration (`RuntimeResolver.admit`, OC-R3).
3. **Harness**: the nine operations over the provider's native session, with frames mapped to Provider Frames, native ids as the identity, and snapshot/fork emulated where the provider has none.
4. **Bind and rebind**: the template step and per-attempt rebind below.
5. **Conformance**: every declared profile runs the [lane conformance suite](../../tests/conformance/lanes/README.md) against its fake (`make test-conformance`), so no lane merges unexercised.

## Registry, admission and qualification

`application/resolution/registries.py::LaneRegistry` maps a profile to its harness. The worker (`adapters/temporal/deployment_composition.py`) registers `deep_agents` always, the Cursor
profiles when `CURSOR_API_KEY` is bound, and `claude_agent_sdk`/`codex` when their opt-in and an auth profiles path are set on a non-Windows worker ([provider lanes](provider-lanes.md));
`claude_managed` and `codex_agents` come from [hosted lane composition](../../src/mission_control/adapters/temporal/hosted_lane_composition.py) when opted in and bound. No harness exists for
`claude_cloud` and `codex_cloud`. The API registers describe-only entries for bound lanes (`bootstrap/lanes.describe_only_registry`) so `lane list` works without executing. Admission refuses a
profile whose describe is not `qualified` unless `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES` allows it. Only `deep_agents` is `qualified=True` (the WP-CP-040 parity suite); that is a describe flag, not
gate W1. Nothing but a reviewed release citing a live-drill record under `docs/qualification/lanes/` may flip another ([qualification](qualification.md)). Lane rows in
`mission_control.lane_profile` are regenerated from `DECLARED_LANE_MATRICES` by common-component migrations ([database component](database-component.md)). The hosted agent APIs admit a mission by
Data Class (`public`, `internal`, or `confidential` under the Application Binding's `hosted_agent_apis` terms); neither is ZDR-eligible, so `mc.hosted_session_retention.v1` deletes each session
after custody plus the retention interval (default 7 days).

**Package registrations (ADR-0063).** A lane with a `LaneRegistration` (describe, model routes, item and family support, pins, a pure compile) is registered with `register(registration, harness)`;
a runtime-only entry has none and the resolver refuses it as `LANE_UNKNOWN`. Each lane package exports `LANE`/`LANES` (`bootstrap/lanes.SESSION_LANES`). The worker registers Deep Agents with no
deployment facts (it executes sealed bindings); the launch author's seam (`bootstrap/resolution.py::compose_launch_resolution`) registers it with the facts beside the `ApplicationRegistry`
(`deployments/<app>/application.toml`) and the `ModelCatalog` (`models.toml`; [model catalog](model-catalog.md)). **One lane binding slot (OC-R2):** an `OperationExecutionRequest` carries one opaque
`lane_binding: SealedLaneBinding`, `lane_profile`, `execution_runtime` and a neutral `lane_dispatch` (`domain/execution/lanes.py`: queue, generation, heartbeat class, wall-clock bound). Validation
refuses a profile whose lane does not serve the runtime and a binding sealed for another profile; payloads are bounded and secret-scanned (`MAX_SEALED_PAYLOAD_BYTES`). The producing lane alone parses
its bytes; two ports it implements (`application/resolution/lane_bindings.py`) add the template step (`LaneTemplateBinder`) and the per-attempt rebind (`LaneRebinders`).
**Residuals (OVE-203):** the lane vocabulary is a closed `Literal`, `CursorExecutionBinding` still lives in the domain and a template guard names Deep Agents
([register](../specs/archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-INTERFACES.md#81-recorded-residuals-r7-review-2026-10-27)).

## Local and cloud (goal)

Today there is a local and a cloud split: `deep_agents` runs in the worker (`local_in_worker`) or as an Agent Server graph (`remote_langsmith_deployment`); Cursor, Claude and Codex each have
a local profile (`cursor_local`, `claude_agent_sdk`, `codex`) and a hosted one (`cursor_cloud`, `claude_managed`, `codex_agents`), and a session lives on exactly one. Fork across them is not built
(`cursor_cloud` fork restore expects a `branch:<branch>@<sha>` ref nothing records; [recovery](recovery.md)). **Goal:** one session across local and cloud lanes, across providers where possible,
using the snapshot, seeded-fork and rebind machinery ([temporal synthesis](temporal-synthesis.md)).

## One lifecycle synthesis: lane.turn

ADR-0031: the operation workflow schedules `lane.turn` segments, with `lane.status` to reconcile
and `lane.cancel` (idempotent) to stop. `application/execution/harness/lane_turns.py`
(`LaneTurnService`) admits the attempt at the operation boundary, then on `start` prepares, starts
and sends the turn, recording the native session and turn on the harness execution before observing
(`adapters/postgres/lanes/execution_state.py`, migration 0030); on `resume` it reattaches and never
sends again, because a lost native turn makes the unit `in_doubt`. Every observed [Provider
Frame](../../GLOSSARY.md) is persisted through the FrameSink before the provider cursor is
heartbeated, so persisted frames are the resume truth and the throttled heartbeat only a hint
([events-and-commands](events-and-commands.md)). Prepare, start and the first send heartbeat
and renew the lease on the same ticker (carrying the prior cursor hint), so a slow hosted prepare
is never timed out into a second, journal-racing attempt; that phase is bounded by the segment's
`max_duration_s` and otherwise fails as `LaneStartStalled` (F3-G1). A segment ends at its bound or at a terminal frame
whose closing facts end the session and settle the operation once. The activities are
`adapters/temporal/activities/lane_turn.py`, registered on the `-agent-cognitive` queue beside
`operation.execute` and `operation.cancel`. Each segment also claims fenced session ownership,
journals every native dispatch and admits it against the Stop Fence, and a provider capacity limit
becomes a bounded wait ([session ownership and dispatch](session-ownership-and-dispatch.md)).

Session Lane units (`SESSION_LANE_RUNTIMES = {cursor, claude, codex}`,
`domain/execution/contracts.py`) always run through the segment loop with segment bounds from their
own binding, and `lane.*` runs on the binding's task queue
(`OperationWorkflowRequest.activity_task_queue` reads `lane_dispatch.task_queue`); a dedicated
queue is served only when listed in `MISSION_CONTROL_LANE_TASK_QUEUES`
(`adapters/temporal/worker.py`). Admission records the attempt row the frames hang off
(`admit_lane_session(attempt=)`). A settlement carries the final JSON answer as the Completion
Candidate and registers declared `outputs/` files as `workspace-candidate://` refs
(`application/execution/operations/lane_outputs.py`). Collection takes every file under `outputs/`.
A lease reused across operations keeps the earlier files there, so a later stage can collect an
upstream report as a second candidate (seen live in Run 2; carried to provider consolidation).
Deep Agents units run `operation.execute` unless `MISSION_CONTROL_LANE_SEGMENT_LOOP=true` (default false,
`bootstrap/settings.py`) moves them onto `lane.turn`; replay histories live under `tests/integration/temporal/histories/ft_lanes/`.
Deep Agents itself: [Deep Agents lane](deep-agents-lane.md); the Temporal view: [temporal synthesis](temporal-synthesis.md).

Built / specified / goal: harness, registry, nine describes, sealed binding, `lane.turn` built and tested; since 2026-11-05 every Session Lane folds its frames into cognition points at settlement and implements time travel ([cross-provider control](cross-provider-control.md)); only Deep Agents compiles, qualifies and has live paid proof
(`NEXT-SESSION.md:32-98`); other profiles are implemented offline and unqualified; one session across local and cloud lanes is a goal.

## Other lanes and what is not built

- Cursor: [cursor lane](cursor-lane.md). Claude Agent SDK and Codex: [provider lanes](provider-lanes.md).
  The launch author seals bindings for all five local profiles ([mission manifest](mission-manifest.md)).
- `claude_cloud` and `codex_cloud` are Outcome 3, revalidated 2026-10-09: the hosted products lack
  documented lifecycle operations ([claude_cloud](../specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/claude_cloud/REVALIDATION-2026-10-09.md),
  [codex_cloud](../specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/codex_cloud/REVALIDATION-2026-10-09.md)); the environment
  launch author and workspace policy refuse them
  ([provider launch](../../src/mission_control/application/authoring/provider_launch.py),
  [workspace policy](../../src/mission_control/application/workspaces/policy.py)). A resolver's
  standalone validation does not establish a production launch path.
- Direct Model lanes are not built.

`codex_agents` is the **OpenAI hosted Agents API** over the repository's HTTP client (`/v1/agents/sessions`, [client](../../src/mission_control/adapters/openai_agents/client.py));
it is separate from the OpenAI Agents SDK, the local Codex app-server and direct Responses ([evidence](../specs/archive/materialization-observation-2026-10/runs/RUN-2-OPENAI-ARCHITECTURE.md)).
Managed Agents budget-pause is a proof blocker: `hold_budget` exists ([adapter](../../src/mission_control/adapters/anthropic_managed/harness.py)) but governed production wiring and exact receipts
are not established; boundary holding in the operation workflow does not satisfy provider budget pause.

## Citations

- Archived design: [fast-track SPEC-07](../specs/archive/fast-track-2026-10/SPEC-07-harness-and-cursor-lane.md).
- ADRs: [0005](../adr/0005-deep-agents-first-extend-not-fork.md), [0006](../adr/0006-agent-server-required-execution-host-not-scheduler.md), [0017](../adr/0017-agent-server-runtime-persistence-separate-database.md), [0018](../adr/0018-coding-agents-are-execution-lanes.md), [0019](../adr/0019-coding-lanes-worker-hosted-local-first.md),
  [0030](../adr/0030-cursor-lane-two-profiles-reducer-from-frames-hydrated-fork.md), [0031](../adr/0031-temporal-lifecycle-synthesis-observe-activity-updates-seeded-forks.md).
- Code: [protocol](../../src/mission_control/application/execution/harness/protocol.py), [describe matrices](../../src/mission_control/application/execution/harness/describe.py), [registry](../../src/mission_control/application/resolution/registries.py), [resolver](../../src/mission_control/application/resolution/resolver.py), [Deep Agents registration](../../src/mission_control/adapters/deep_agents/compile.py), [seam composition](../../src/mission_control/bootstrap/resolution.py),
  [lane turns](../../src/mission_control/application/execution/harness/lane_turns.py), [lane contracts](../../src/mission_control/domain/execution/lanes.py), [binding contracts](../../src/mission_control/domain/execution/bindings.py), [sealed lane binding](../../src/mission_control/domain/resolution/sealed.py), [lane binding ports](../../src/mission_control/application/resolution/lane_bindings.py), [Deep Agents binding](../../src/mission_control/adapters/deep_agents/binding.py), [lane turn payloads](../../src/mission_control/domain/execution/lane_turns.py),
  [lane activities](../../src/mission_control/adapters/temporal/activities/lane_turn.py), [lane state store](../../src/mission_control/adapters/postgres/lanes/execution_state.py), [lane routes](../../src/mission_control/interfaces/http/lanes.py),
  [worker lane composition](../../src/mission_control/adapters/temporal/deployment_composition.py), [lane task queue workers](../../src/mission_control/adapters/temporal/worker.py), [lane outputs](../../src/mission_control/application/execution/operations/lane_outputs.py).
- Tests: [lane contracts](../../tests/unit/harness/test_lane_contracts.py), [multi-provider contracts](../../tests/unit/harness/test_multi_provider_contracts.py), [registry](../../tests/unit/harness/test_lane_registry.py), [dispatch](../../tests/unit/harness/test_lane_dispatch.py),
  [lane turn service](../../tests/unit/harness/test_lane_turn_service.py), [lane conformance suite](../../tests/conformance/lanes/README.md), [compile conformance](../../tests/conformance/lanes/compile/test_compile_conformance.py), [registrations](../../tests/conformance/lanes/compile/test_registrations.py), [lane state in PostgreSQL](../../tests/integration/postgres/test_lane_execution_state.py), [lane bindings in PostgreSQL](../../tests/integration/postgres/test_lane_bindings.py),
  [lane turn on Temporal](../../tests/integration/temporal/test_lane_turn.py), [lane replay histories](../../tests/integration/temporal/test_lane_replay_histories.py), [segment loop acceptance](../../tests/acceptance/mission_control/test_ft_g2_segment_loop.py),
  [Session Lane routing](../../tests/unit/operations/test_session_lane_routing.py), [lane task queue workers](../../tests/unit/runtime/test_lane_task_queue_workers.py), [lane final text](../../tests/unit/harness/test_lane_final_text.py).
