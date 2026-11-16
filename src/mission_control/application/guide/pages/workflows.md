---
id: workflows
title: Workflow systems and Workflow Types
summary: The four workflow systems, which lane runs each, when to choose one, and how to list the published Workflow Types.
---
A workflow system is the behaviour of a program node. A manifest names it in `behavior`; a draft check names it in `family`.

| Workflow system | `behavior` | `family` | Choose it when |
| --- | --- | --- | --- |
| Stage Graph | `stage_graph` | `StageGraph` | The route is known: stages with dependencies, typed inputs and gates, released as their dependencies settle. |
| Goal Loop | `goal_loop` | `GoalDirected` | The route is unknown and a criterion can judge progress: it iterates until the goal is met or a governor stops it. It needs an `objective` and an `action_space`. |
| Parallel Swarm | `parallel_swarm` | `ParallelSwarm` | Several bounded, isolated variants should run side by side and the selected results converge. It is a Stage Graph composition. |
| Evaluator Optimizer | `evaluator_optimizer` | `EvaluatorOptimizer` | One deliverable should improve over bounded rounds, scored by an independent evaluator against a rubric. |

A Stage Graph may hold a Goal Loop, a human gate or another node as a stage, so start from a Stage Graph when the mission has a review step.

{{generated}}

Read the table as the lane's own declaration. `native`: the lane runs it. `unqualified`: implemented without a recorded qualification, admitted only where this installation allows unqualified lanes. `unsupported`: refused at compile (`UNSUPPORTED_BEHAVIOR`) and by the draft check.

## Workflow Types

A Workflow Type is a published catalog definition that fixes one workflow's purpose, contracts and authority ceiling: the capabilities, budgets and concurrency a run of that type may use. A manifest names a `behavior`, never a Workflow Type; the compiler assigns the type. Name one in a draft (`workflow_type`, the hit's `ref`) so {op:check} tells you whether each chosen capability fits under its authority ceiling.

List every published Workflow Type with {op:list_workflow_types}, search them with {op:search} and the facet `workflow_type`, and read one with {op:describe}.
