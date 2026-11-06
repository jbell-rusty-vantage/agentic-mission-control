---
type: Concept
category: domain-model
title: Recursive composition and nested family bodies
description: How a Goal Loop inside a Stage Graph stage, or a Stage Graph as a Goal Loop's executor phase, compiles to a sealed nested body and runs as its own child run with exact exports, contained budget and governed control lineage; the boundary Swarm members and Evaluator Optimizer rounds are decided to reuse.
tags: [mission-control, workflow-systems, programs, recursion, nested-bodies, implementation]
aliases: [nested body, nested family body, nested goal loop, child run, exports adopt_into]
questions:
  - How do I nest a Goal Loop inside a Stage Graph stage?
  - What does a nested body export and how is it adopted?
  - How are budget and cancellation contained across a nested body?
  - Why does a nested body refuse inherited inputs?
  - What boundary will Swarm members and Evaluator Optimizer rounds reuse?
updated: 2026-11-02
---

# Recursive composition and nested family bodies

A nested workflow system pursues the enclosing mission's objectives with its own activation,
governors, state and lineage; flattening is insufficient, internal artifacts stay internal unless
exported, and an early export never accepts an incomplete composite (OUTPUT-CONTRACTS §9 and
`00-EXECUTION_PROGRAM_MODEL.md` §5, harvested from the deleted spec pack at `66185d2e`). OVE-176 (WI-13)
implements this for the two families the kernel runs ([workflow systems](workflow-systems.md)).

At the four levels. **Scheduling:** the parent admits the hosting unit as an operation, then starts one child run per
unit attempt (own run control, family state, governors, journal). **Obligations:** the parent owes only the
composite's declared outputs at the stage position; the body's own run owes what it produces; exports are adopted
explicitly. **Context transfer:** a body reads nothing from outside itself (inherited inputs refuse at compile,
`NESTED_INPUT_UNSUPPORTED` in `domain/context/transfer_builders.py:224`); exact exports reach the parent only through the export
receipt and adoption. **Runtime:** the body's budget is the unit's reservation; its lanes, models and capabilities come
from its own derived sub-definition.

## Authoring and compile

- A Stage Graph stage whose node is a `goal_loop` or a `stage_graph`, and a `goal_loop` whose
  `nodes` holds one `stage_graph` or `goal_loop` (its executor phase), are nested bodies
  (`domain/authoring/manifest.py`: `GoalLoopNode.nodes`, `exports` on both composite nodes).
- Every declared output of the composite is exported, final by default. `exports: [{output,
  from: <stage>.<output>, timing: final|early}]` names a subgraph's inner producer and marks an
  early export. A Goal Loop exports its own outputs. Undeclared inner outputs never cross.
- `lower_mission` compiles each boundary to one `NestedBody` (`domain/authoring/nested_bodies.py`)
  on the host blueprint (`StageGraphBlueprint.nested_bodies` keyed by stage,
  `GoalDirectedBlueprint.nested_bodies` hosted by `executor`; both digest-neutral when empty).
  The body is the derived sub-definition `nested_definition` (`nested_lowering.py`: the node as
  root, the goals its subtree serves, criteria narrowed to its outputs or its exports), sealed by
  `definition_digest` and its own lowering's `blueprint_digest`, lowered recursively one level
  deeper with its absolute `position` (`refine/pass`), so its promises keep their nesting
  identity (`refine/pass/draft`). The parent owes only the composite's declared outputs at the
  stage position; the body's own run owes what it produces.
- Bounded statically: `depth` counts composite ancestors and never exceeds `max_depth`
  (`governors.depth` within `MAX_NESTING_DEPTH` 4). Typed refusals: `nested_depth_exceeded`,
  `nested_inherited_input_unsupported` (a body reading a producer outside itself),
  `nested_export_unknown_output` / `_unknown_source` / `_unbound`, `unsupported_nested_body`,
  `unsupported_graph_position` (exports on a Goal Loop root, or early exports on a Stage Graph root; a Stage Graph
  root's `exports` name the stages its mission outputs come from, OVE-169). The old warning
  `nested_goal_loop_lowered_as_stage` is gone.

## Runtime: one child run per unit attempt

The parent admits the hosting unit exactly as an operation (the reservation is the body's
allocated budget), then calls `start_nested_body` (`adapters/temporal/workflows/nested_body.py`)
instead of starting an operation child, behind patch `oc-wi13-nested-body` (only blueprints with
nested bodies reach it, so recorded histories replay unchanged):

1. `nested_program.activate` → `NestedProgramService.activate`
   (`application/programs/nested_bodies.py`) admits the child run through a `NestedRunLauncher`
   (deterministic request id `nested_request_id(parent run, host, semantic attempt)`, so restart
   and replay re-attach while a revisit or retry activates a new child), refuses an uncontained
   budget (`contained_ceiling`: never above the unit's reservation) and records lineage.
2. The child's `mc.mission_run.v1` root starts as a Temporal child workflow with its own
   deterministic id (`mission_root_id`) and `REQUEST_CANCEL` parent-close policy; its family runs
   with its own run control, family state, governors and journal.
3. `nested_program.settle` maps the child's end to the shared Terminal Outcome (`child_terminal`),
   reads the child's accepted heads (`NestedOutputs`) and computes the export receipt
   (`project_exports`, `mc.nested_export_receipt.v1`): only declared exports, only accepted
   revisions; the composite is accepted only when the child was accepted and every required final
   export holds refs; early exports of an incomplete composite are receipt lineage only. It then
   settles the unit's reservation on the child's actual usage.

A Stage Graph host stage completes with exactly the exported refs (`stage_result`), is cancelled,
or fails (its consumers stay unreleased). A Goal Loop executor phase completes for any governed
end (`executor_result`; a non-accepted body is a failed iteration the convergence policy
decides), and `goaldirected.reconcile_nested_executor` turns the receipt and settlement into the
iteration's execution result and `GoalOperationSettlement`.

## Control lineage

The family's cancellation saga and slow-sibling cancellation call `cancel()` on every active
unit; a `NestedBodyHandle` delivers it through the child run's own run control
(`nested_program.propagate`, `NestedControls`), so the child runs its own saga, and cancels the
Temporal child only when the governed path is unavailable. An applied parent pause or resume
whose scope covers the host stage is propagated the same way. A refused activation starts nothing and releases the reservation.

## Composition, launch and adoption

`compose_nested_program_activities` (`bootstrap/nested_programs.py`, wired from
`deployment_composition`) serves the activities on both family workers with the PostgreSQL lineage
(`mission_control.nested_activation`, release 1.13.0, `scripts/release_1130/0071_nested_program_activations.sql`; the unreviewed `sprint-oc-wi15` also claims key 0071 for `0071_evaluator_optimizer_rounds.sql`, a migration-key collision to resolve at integration), the child output
reader and governed child controls (run control plus boundary delivery). The launcher
(`application/programs/nested_launch.py`) needs the manifest launch author; adoption needs the
knowledge toolset; without them a body refuses `nested_execution_unavailable` or settles without
adoption. `ManifestNestedRunLauncher` checks the parent's activation chain places the body at its
compiled depth (`nested_depth_lineage_mismatch`), derives the body from the parent revision's
definition at its position (`nested_definition_at`), refuses unless both sealed digests match
(`nested_body_digest_mismatch`), compiles, verifies and admits the child into the parent's mission
revision (`PostgresNestedRunAdmissions`) with spend capped at the unit's reservation (the hosting
stage or iteration reserves the body's own budget at compile), records lineage, authors the launch
input through `NestedRunDefinitions` (a child run reads as its body), registers its promises and
returns the root. Its launch input comes from the body alone (inherited inputs refuse at compile).

Adoption (`application/outputs/adoption.py`, the act WI-16 links reuse): each accepted export with
an `adopt_into` obligation (the composite's own promise, or the hosting loop's same-named one) is
re-submitted as the exact source candidate (revision and digest verified as an accepted head) for
that obligation under the hosting unit's invocation, with an `adopter` lineage fact (0051); the
invocation is then settled like any unit. It grants nothing: the parent's assessment, promotion and
fulfillment decide the adopted revision. A refused adoption leaves the composite not accepted.

## Extension points for Parallel Swarm and Evaluator Optimizer

OC-D204/D205 decided that Swarm is a Stage Graph profile and EO runs on Goal Loop machinery, so these are
extension points for hosted members and rounds, not for new families. Nothing below is built; the preserved branches
`sprint-oc-wi14`/`wi15` (unreviewed) used the separate-family shape.

<!-- snippet: src/mission_control/domain/authoring/nested_bodies.py:47-51 -->
```python
# Behaviors that execute recursively as their own family, and the family each runs as.
RECURSIVE_BEHAVIORS: Final[dict[Behavior, NestedFamily]] = {
    Behavior.GOAL_LOOP: "GoalDirected",
    Behavior.STAGE_GRAPH: "StageGraph",
}
```

A hosted behavior is added to `RECURSIVE_BEHAVIORS` with a runtime; compile boundary, digests, exports and the depth
governor are shared. A Swarm member or convergence body or an EO producer or evaluator round would be one hosted unit
with its own `host_id` (`member:<n>`, `round:<r>:producer`) through the same `NestedActivationRequest`,
`NestedProjection` and `NestedControlRequest`: one deterministic child per attempt, isolated inputs and budget, exact
export per member or round; surplus cancellation is `handle.cancel()`, quorum selection reads `NestedProjection`s and
an EO hard gate reads the evaluator round's receipt, never the producer's.

## Failure, restart and limits

An activation or settlement activity that cannot complete fails the unit typed
(`nested_activation_error`) after a best-effort settlement; a cancel before the child started never
starts it; controls arriving before the start are held and delivered on attach; a control the child cannot
take is recorded typed, never raised; a redelivered settlement returns the recorded receipt. The
`REQUEST_CANCEL` parent-close policy only covers an abnormally closed parent. Limits: a body reading a parent sibling refuses
at compile; exports are not released to running parent consumers early; other readers of run definitions
(human-gate admission) see a child run as the whole revision; the child root starts without search attributes.

Built / specified / goal: nested Goal Loop and Stage Graph bodies built, tested on real Temporal and PostgreSQL with deterministic cognition (no paid or composed-launcher end-to-end run); Swarm and EO hosting specified only.

# Citations

- Spec (harvested at `66185d2e`): OUTPUT-CONTRACTS §9; `00-EXECUTION_PROGRAM_MODEL.md` §§5-6.
- Code: `domain/authoring/{nested_bodies,nested_lowering,manifest_lowering}.py`, `domain/programs/nested.py`,
  `application/programs/nested_bodies.py`, `adapters/temporal/workflows/{nested_body,stagegraph,goal_directed}.py`.
- Tests: `tests/unit/authoring/test_wi13_nested_authoring.py`, `tests/unit/orchestration/test_wi13_nested_runtime.py`,
  `test_wi13_round2.py`, `test_wi13_nested_goal_executor.py`, `tests/integration/temporal/test_wi13_nested_temporal.py`,
  `tests/integration/postgres/test_wi13_nested_activations_postgres.py`; fixtures `tests/fixtures/manifests/sprint-oc-w5/`.
