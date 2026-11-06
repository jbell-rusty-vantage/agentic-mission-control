---
type: Concept
category: domain-model
title: Workflow systems as program-node behaviors
description: The three workflow-system behaviors the owner decided (Stage Graph, Goal Loop, Evaluator Optimizer on Goal Loop machinery), Parallel Swarm as a Stage Graph profile, linked workflows as mission chains, and one table giving each system's scheduling, output obligations, context transfer, runtime and capability configuration and built status.
tags: [mission-control, workflow-systems, programs, stage-graph, goal-loop, swarm, evaluator-optimizer]
aliases: [workflow types, program behaviors, workflow families, GoalDirected vs Goal Loop, linked workflows]
questions:
  - Which workflow systems exist and which does the code run?
  - Is Parallel Swarm its own workflow system or a Stage Graph profile?
  - How does Evaluator Optimizer reuse Goal Loop machinery?
  - What does each workflow system schedule, owe, transfer and configure?
  - Why does the code say four families when the decision says three?
updated: 2026-11-01
---

# Workflow systems as program-node behaviors

A mission's [Program](../../GLOSSARY.md) is a recursive tree of program nodes. Each node has exactly one
[Behavior](../../GLOSSARY.md): a workflow system, an executor (Agent or Deterministic), a durable control
(Event Wait, Timer, Human Gate, Proof Gate) or a child mission invocation. A workflow system composes child
work and owns its own lifecycle and governors; it pursues the enclosing mission's objectives and cannot add
independently governed goals (only another mission can, see [mission chains](mission-chains.md)).

## What was decided and what the code still says

OC-D204 (owner, 2026-10-29): "Swarm is a StageGraph composition/profile, not a separate workflow-system
primitive"; its group policies and proof obligations stay, and it uses common scheduling and transfer.
OC-D205 (owner, 2026-10-29): bounded produce/evaluate/accept-or-repair Evaluator Optimizer (EO) uses GoalDirected
machinery with distinct producer and evaluator node/execution/session identities, a sealed exact candidate,
rubric and evidence, full typed prior reports to the next producer, host acceptance, and unavailable evaluation
that waits or retries rather than rejecting. Wording: [decision register](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md)
(`:347-348`), [answers](../specs/provider-consolidation-2026-10/answers/SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md)
(`:21-22`), recorded in [ADR-0068](../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md).
So the decided behaviours are **three**: Stage Graph, Goal Loop, Evaluator Optimizer, plus Swarm as a Stage Graph profile.

The code still names **four families**, a vocabulary debt (code issue to file in Sprint OC, AS-D34) rather than a behaviour difference:
`Family = Literal["StageGraph", "GoalDirected", "ParallelSwarm", "EvaluatorOptimizer"]`
(`domain/resolution/configuration.py:53`), `FAMILY_OF_BEHAVIOR` (`application/authoring/manifest_v2_admission.py:86-91`)
and the lane declaration below. Only `StageGraph` and `GoalDirected` have blueprints, interpreters and Temporal
workflows (`WorkflowFamily = Literal["StageGraph", "GoalDirected"]`, `domain/programs/contracts.py:46`).

<!-- snippet: src/mission_control/adapters/deep_agents/describe.py:155-160 -->
```python
    families={
        "StageGraph": "native",
        "GoalDirected": "native",
        "ParallelSwarm": "unqualified",
        "EvaluatorOptimizer": "unqualified",
    },
```

## The table: each system at the four levels

| System | Scheduling | Output obligations | Context transfer | Runtime and capability configuration | Built status |
| --- | --- | --- | --- | --- | --- |
| [Stage Graph](stage-graph.md) | Temporal `belllabs.stagegraph` calls `StageGraphInterpreter.frontier`: stages release when joins (`all`/`any`/minimum), routes and release groups hold, up to `max_concurrency` (manifest `concurrency`, default 1) with fairness groups; one bounded revisit region; declared waits and human gates | Each declared stage output is one `OutputObligation@2` at the stage position; root outputs at `workflow`; completion is the conjunction of required promises; stage result `ADMIT/REJECT/QUARANTINE` | `dependent_stage`: exactly the declared `from: <producer>.<output>` bindings, accepted heads only, required unless authored optional; release omissions recorded in the sealed plan | One frozen `OperationExecutionRequest` template per stage (lane binding, model policy, capability grant, workspace, secrets) authored by `ManifestLaunchInputAuthor` from the node's resolved environment; Deep Agents `native` | implemented, tested, integrated (paid Deep Agents fixtures); W1 not released |
| [Goal Loop](goal-loop.md) (code: GoalDirected, a subset) | Temporal `belllabs.goal-directed`: executor then verifier per iteration, convergence decision by fixed precedence, session rollover, Continue-As-New every 20 iterations | Verifier judges the whole required set; `converge` decides declared promises before the verdict; acceptance only with every required promise fulfilled | `first_invocation`, `next_iteration` (prior outputs, optional), `evaluator` (nominated subject only), `repair`, typed `GoalHandoff` for a fresh session | Two templates (executor, verifier), each its own lane and model; verifier policy pins rubric and acceptance versions | implemented, tested, integrated; Loop Journal, Action Proposal and Authorization not built |
| [Parallel Swarm](parallel-swarm.md) (profile) | Decided: members and convergence are ordinary stages released under capacity; quorum/first-accepted/best-effort are release groups; surplus cancelled by profile default | Decided: ordinary per-member and convergence obligations; member exports only by explicit selection | Decided: selected exact outputs, findings and gaps through the common sealed plan; late arrivals never alter it | Decided: per-member variant (model, runtime, instruction) recorded with the member | specified; group and route mechanics exist in Stage Graph; no profile, no cancellation; Deep Agents `unqualified` |
| [Evaluator Optimizer](evaluator-optimizer.md) | Decided: Goal Loop machinery, producer = executor role, evaluator = verifier role, bounded rounds | Decided: hard gates computed by the host; accept-best cannot bypass required gates | Decided: evaluator gets exact candidate, rubric, evidence and full prior reports | Decided: distinct node/execution/session identities, optional model or runtime independence | specified; the verifier-with-rubric subset of Goal Loop runs; rounds, scores, patience, abstention not built; Deep Agents `unqualified` |
| Linked workflows ([mission chains](mission-chains.md)) | Chain reducer releases the next mission through the outbox in the commit that satisfies the link | Each member owes its own promises; delivery never adopts; explicit adoption is a separate act | `linked_mission` boundary: released exports frozen into the receiver's sealed plan | Each member is a whole mission with its own templates and lanes | implemented, tested, integrated locally (releases 1.10.0/1.11.0); not qualified |

Nested composition (a Goal Loop in a stage, a Stage Graph as an executor phase) is [recursive composition](recursive-composition.md);
the same boundary is the intended host of Swarm members and EO rounds.

## Executors and durable controls

Executors do the atomic work: an Agent Executor delegates bounded cognition to a lane through the operation
shell; a Deterministic Executor runs a registered kind with no model judgment. [Durable controls](durable-controls.md)
wait instead of working. Pause, cancel, retry and continuation are commands and policies, never node behaviors.
Every activation records `lifecycle`, a system `phase` and a late `terminal_outcome`; retry, revisit, iteration,
round and continuation are distinct counters (ADR-0011). Execution success is never acceptance ([completion](completion.md)).

## Specified, not built

- Stage Graph dynamic fan-out from a committed template and provisional bindings: only a `fan_out` governor
  (`domain/authoring/manifest.py:588`) and a `provisional` flag, always false (`domain/programs/contracts.py:501`).
- Deterministic Executor kinds (`coalesce`, `agreement_check`, `verification_dispatch`, ...) which Swarm convergence needs.
- Child Mission Invocation, Portals and Spawn Grants ([mission chains](mission-chains.md#child-mission-invocation-not-built)).
- Authoring accepts `behavior: parallel_swarm` and `evaluator_optimizer` nodes (free-form `params`,
  `domain/authoring/manifest.py:986-997`) but `manifest_lowering.py` has no path for them: such a root lowers to a one-stage Stage Graph with no blocker or warning
(`_stage_children`, `domain/authoring/manifest_lowering.py:709-712`), so an authored swarm silently runs as one agent stage (code defect).
- Unreviewed runtime branches `sprint-oc-wi14` (Swarm, `cf2575d6`) and `sprint-oc-wi15` (EO, `0c14071a`) implement them as
  separate families, the shape OC-D204/D205 reclassified; they are preserved source, not integrated.

Built / specified / goal: Stage Graph and Goal Loop subset built and integrated locally, not qualified; Swarm and EO decided and specified, not built; linked workflows built; per-policy mid-workflow mutation is a goal ([revisions](revisions.md)).

# Citations

- Decisions: [ADR-0068](../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md),
  [ADR-0011](../adr/0011-distinct-retry-counters-and-retry-classifier.md), [ADR-0029](../adr/0029-mission-chains-compile-to-linked-missions-released-by-outbox.md),
  [ADR-0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md) (family support stays `unqualified` until WI-14/15).
- Code: [program contracts](../../src/mission_control/domain/programs/contracts.py),
  [Stage Graph interpreter](../../src/mission_control/domain/programs/interpreter.py),
  [GoalDirected interpreter](../../src/mission_control/domain/programs/goal_directed.py),
  [family vocabulary](../../src/mission_control/domain/resolution/configuration.py),
  [behavior to family map](../../src/mission_control/application/authoring/manifest_v2_admission.py),
  [manifest behaviors](../../src/mission_control/domain/authoring/manifest.py),
  [lowering](../../src/mission_control/domain/authoring/manifest_lowering.py),
  [Deep Agents declaration](../../src/mission_control/adapters/deep_agents/describe.py).
- Tests: [Stage Graph](../../tests/unit/orchestration/test_stagegraph_v2.py),
  [GoalDirected](../../tests/unit/orchestration/test_wp_bp_020_goal_directed.py),
  [lane behavior support](../../tests/unit/authoring/test_manifest_compile.py) (`test_lane_support_matrix`),
  [every behavior parses](../../tests/unit/authoring/test_manifest_schema.py).
- Proof of integration (not qualification): [control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) (`:32-87` paid Deep Agents fixtures, `:119-121` W1 unreleased).
- Annexes harvested from the deleted spec pack at `66185d2e`: `workflow-types/00-09` (`git show 66185d2e:mission-control-general/workflow-types/<file>`).
