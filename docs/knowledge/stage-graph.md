---
type: Concept
category: domain-model
title: Stage Graph
description: How a Stage Graph schedules typed stages (joins, routes, release groups, concurrency, one bounded revisit region), what it owes as output obligations, how accepted outputs transfer between stages, and how each stage's agent runtime and capabilities are configured; the code family is StageGraph.
tags: [mission-control, workflow-systems, stage-graph, scheduling, routes, revisit, implementation]
aliases: [StageGraph, stage graph interpreter, graph routes, release groups, revisit region]
questions:
  - How does a Stage Graph release, route and revisit stages?
  - How do I run two stages in parallel and join them?
  - Why did a Stage Graph hold with route-exhausted and how do I recover?
  - What does a dependent stage receive from its producer?
  - How is each stage's model, lane and capability set chosen?
updated: 2026-11-01
---

# Stage Graph

The [Stage Graph](../../GLOSSARY.md) releases typed [stages](../../GLOSSARY.md) by dependencies, inputs and
gates. It is the only workflow system whose release logic is a pure interpreter over an immutable blueprint;
Temporal supplies waiting and recovery. [Parallel Swarm](parallel-swarm.md) is a profile of it (OC-D204); a
Goal Loop may sit inside a stage ([recursive composition](recursive-composition.md)). The system overview and
the cross-system table are in [workflow systems](workflow-systems.md).

## 1. Scheduling

**Who decides.** `StageGraphInterpreter` (`domain/programs/interpreter.py:98`) is pure: no I/O, no clock. The
Temporal workflow `belllabs.stagegraph` (`adapters/temporal/workflows/stagegraph.py:167`, a child of the root
`mc.mission_run.v1`) loads the accepted projection, asks `frontier()` which stages may be admitted, starts one
governed operation child per released stage and commits each result through activities. Reducers own lifecycle
and settlement; the interpreter only proposes ([lifecycle](lifecycle.md)).

<!-- snippet: src/mission_control/domain/programs/interpreter.py:278-284 -->
```python
    def frontier(
        self,
        projection: StageGraphAcceptedProjection,
        *,
        available_concurrency: int,
        blocked_candidate_keys: frozenset[str] = frozenset(),
    ) -> tuple[StageOperationAdmissionProposal, ...]:
```

**Release.** A stage in `blocked`/`ready` is released when its joins hold: each join is `all`, `any` or
`minimum` over its producers (`JoinKind`, `manifest_lowering.py::_join`), its route branch is true, its named
release group qualifies and its declared wait is satisfied. Stages run concurrently up to the run's
`max_concurrency` (manifest root `concurrency`, default 1, so a manifest mission runs one stage at a time unless
it asks for more; `running_concurrency` sums each slot's `concurrency_slots`, `domain/programs/interpreter.py:393`); weighted
`FairnessGroup`s order candidates; a failed producer with unreachable consumers no longer parks the run on a
declared wait (patch `tracing-s3-stagegraph-skip-unreachable-wait`, `adapters/temporal/workflows/stagegraph.py:140`).

**Routes and release groups (WI-08, OVE-171; marker `graph_semantics: oc-graph-routes-v1`).** A `from:
<sibling>.<output>` binding is itself a dependency. `routes` are `all_matching` or ordered `first_match` (+ `else`)
over typed stage `facts` the host reads from accepted, schema-validated output bytes
(`application/programs/route_facts.py`, `domain/authoring/graph_routes.py:80,142`). Evaluation is pure
(`routing.py`, `route_view` at `domain/programs/interpreter.py:1421`): true branches release while unknown ones wait, first-match
never passes an earlier unknown, `else` needs every branch false. A branch is `exhausted` only when an unknown
conjunct can never resolve; the family then records a durable held wait `route-exhausted:<route>` and holds for an
operator command instead of failing or reporting false. Not-selected targets and their required dependents are
skipped visibly. A `JoinGroup` (`domain/authoring/graph_routes.py:195`) names exact members, an all/any/quorum threshold on distinct
members and coverage subjects; selection is the first qualifying set in acceptance order, a quorum never waives
coverage, and an optional input still pending at release is omitted visibly.

**One bounded Revisit Region** (`domain/authoring/graph_routes.py:258`): entry, exit, `max_visits`, `until` facts or else
fulfillment of the region's required obligations, optional integer `progress` with `patience`, and `carry` of exit
outputs. It re-runs at the next workflow cycle when `revisit_view` (`domain/programs/interpreter.py:1668`) says `revisit` (patch
`oc-wi08-stagegraph-revisit-region`); the entry receives the prior visit's accepted exit output exactly; cap or
no-progress exhaustion is a governed outcome, never success, and an unmet required obligation then fails the
graph with `revisit-cap-exhausted:<region>:visit-N-of-M`. Not built from the target: per-stage visit caps and the
region's own wall-clock/budget guards.

**Operator path for a hold.** `route-exhausted:<route>` / `revisit-exhausted:<region>` appear in run inspection
(`projection.active_waits`) and as an actionable `blocked` notice. `cancel` ends the run; satisfying the wait is
recorded but cannot change pinned evidence, so the hold re-enters. The fix is a revision: [fork](precise-fork.md)
the run or submit a successor with corrected inputs, routes or facts ([revisions](revisions.md)). Compile refuses a
graph whose completed record would exceed the family mutation bound (`domain/programs/stagegraph_bounds.py`).

**Human gate and waits.** A stage named in `StageGraphRunInput.human_gates` runs the `mc.human_gate.v1` control
activation instead of an operation (patch `mp10-stagegraph-human-gate`); a denied gate fails the run
([human gates](human-gates.md)). An Event Wait stage is released by its implied watcher ([watchers](watchers.md)).

## 2. Output-contract obligations

Lowering turns every declared stage output into one `OutputObligation@2` owned by the stage's position
(`workflow` for the root; a nested body keeps its own path). Compiled completion is the conjunction of every
required promise; `unowned_goal` refuses a required goal no stage serves instead of assigning the last stage
(`domain/authoring/manifest_lowering.py:449`). A stage result is decided `ResultDecision.ADMIT | REJECT | QUARANTINE`
(`domain/programs/contracts.py:394`); a `StageGraphCompletionProposal` terminalizes only with required obligations
accepted, no pending dependency and no open producer liability. The decision mutation's fingerprint excludes
`decided_at` and restores set-valued fields on read-back so Postgres replay verifies in any process. Named stage
outputs settle through `application/programs/named_outputs.py`. Promotion, assessment and fulfillment are
separate facts: [output contracts](output-contracts.md), [completion](completion.md).

## 3. Context transfer

A first stage invents no predecessor. A dependent stage receives exactly its declared `from:` bindings through
`transfer_builders.dependent_stage` (`domain/context/transfer_builders.py:85`, called at
`application/programs/service.py:2852,2892`): accepted revisions only, every selected binding required unless the
authored binding is `required: false`; `release_omissions` in the sealed plan record what the release left out, so
surplus and late arrivals never enter a plan. The Context Packet carries host state ([context and
continuation](context-and-continuation.md)); queued instructions are claimed at the stage-admission boundary
([interventions](interventions.md)).

## 4. Agent runtime and capability configuration

Each stage carries `StageOperationSlot`s (`domain/authoring/contracts.py:388`): `allowed_variants` (operation
contract refs), `fallback_sequence`, `concurrency_slots`, `reservation`. The launch author
(`application/authoring/manifest_launch_inputs.py`) persists one frozen `OperationExecutionRequest` template per
stage under `semantic-input:manifest:{run_id}`: model policy, `agent_profile_ref`, capability grant, workspace,
secret refs, and one sealed `lane_binding` + `lane_dispatch` from the resolution seam (ADR-0063;
[agent configuration](agent-configuration.md), [mission manifest](mission-manifest.md)). The preparation service
(`StageGraphOperationPreparationService.materialize`, `application/programs/service.py:2151`) rebinds the live attempt coordinates at
admission without reading the lane's bytes. A fork may change a stage objective or admit templates compiled for a
new configuration, never copy old provider bytes (`application/programs/fork_templates.py`). Lane support:
`StageGraph: native` on Deep Agents (`adapters/deep_agents/describe.py:156`).

Built / specified / goal: scheduling, routes, groups, one revisit region, gates and nested bodies built and integrated locally (paid Deep Agents Qualia and AI Engineer graphs, control board `:32-87`), W1 not released; dynamic fan-out and provisional bindings specified only; mid-run policy mutation is a goal.

# Citations

- Spec (harvested, deleted pack at `66185d2e`): `workflow-types/01-STAGE_GRAPH.md` §§4-9, §11 (fan-out §9 not built); OUTPUT-CONTRACTS §7.
- Code: [interpreter](../../src/mission_control/domain/programs/interpreter.py), [routing](../../src/mission_control/domain/programs/routing.py),
  [routes and groups](../../src/mission_control/domain/authoring/graph_routes.py), [blueprint](../../src/mission_control/domain/authoring/contracts.py),
  [workflow](../../src/mission_control/adapters/temporal/workflows/stagegraph.py), [program service](../../src/mission_control/application/programs/service.py),
  [transfer builders](../../src/mission_control/domain/context/transfer_builders.py), [bounds](../../src/mission_control/domain/programs/stagegraph_bounds.py),
  [lowering](../../src/mission_control/domain/authoring/manifest_lowering.py), [fork templates](../../src/mission_control/application/programs/fork_templates.py).
- Tests: [Stage Graph v2](../../tests/unit/orchestration/test_stagegraph_v2.py), [routes and groups](../../tests/unit/orchestration/test_wi08_graph_routes.py),
  [Revisit Regions](../../tests/unit/orchestration/test_wi08_revisit_regions.py), [authoring](../../tests/unit/authoring/test_wi08_graph_authoring.py),
  [Temporal and replay](../../tests/integration/temporal/test_wi08_graph_routes_temporal.py), [legacy replay](../../tests/integration/temporal/test_wi08_legacy_stagegraph_replay.py),
  [failed producer behind a wait](../../tests/acceptance/mission_control/test_tracing_stream.py), [W2 fixtures](../../tests/fixtures/manifests/sprint-oc-w2/).
- Proof status: [control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) (`:69-87` Qualia seven-stage graph, `:32-58` AI Engineer, `:119-121` W1 unreleased).
