---
id: lanes
title: Lanes: where an agent runs
summary: Every lane this installation binds, what each supports, and how to read one lane in full.
---
A lane is one harness that runs agent cognition; a lane profile is one placement of it. A manifest names a lane profile in `environment.lane`; a node may overlay it. Only the lanes listed here are bound on this installation: a manifest that names another is refused.

Choose by what the node needs, in this order:

1. The workflow system: the lane must run the node's `behavior` (topic `workflows`).
2. The model: the lane must route the Model Profile's vendor (topic `models`).
3. The capabilities: the lane must support each item kind you attach, and each capability must support the lane (topic `capabilities`).
4. The controls you will need during the run: how the lane delivers an instruction, an interrupt, a cancel and a fork (topic `control`).

Prefer a qualified lane. An unqualified lane is implemented without a recorded qualification and is admitted only where the installation allows it.

{{generated}}

In the table, a name alone is `native`; a prefix marks the weaker verdicts (`emulated`, `unqualified`). What is absent is unsupported.

Read one lane in full with {op:describe_lane}: its `controls`, `delivery_semantics`, `time_travel`, hook events, approval modes, subagent field support and `model_routes`. List the lanes with {op:list_lanes}; narrow a search to one lane with {op:search_lane}.

A feature is provider-specific behaviour a node switches on in `environment.provider_options.<lane profile>`: `lane_features` by name, or `model_tools` by vendor then name. Read one feature's configuration schema, status and what it needs with {op:describe_feature}. A feature whose status is not `available` is refused when selected.
