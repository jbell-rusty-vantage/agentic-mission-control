---
id: manifest
title: The Mission Manifest
summary: The required fields per workflow system, the allowed values, what each lane requires, which acceptance can start, and where the full reference is.
---
A Mission Manifest is one YAML document: the mission's goals, its `environment` and its `program`. Start from a template (topic `templates`). Read every field with {op:describe_manifest} and one mapping with {op:describe_manifest_section}.

## How the keys refer to each other

- A `key` is a slug you choose: on the mission, each goal, objective, criterion and node. Node keys are unique in the mission.
- A node's `objectives` name goal or objective keys. Every goal needs a stage that names it, or whose output its criterion cites.
- A criterion's `evidence` is a list of output names that nodes declare under `outputs`.
- `acceptance` is a typed expression, never free text.
- `action_space` aliases name a capability's, agent's or plugin's `as`, or a node key.
- `depends_on` names sibling stages. An input's `from` and a gate's `packet` name `<node key>.<output name>`.
- A node's `environment` may only narrow the budget, governors and side effects it inherits.

{{generated}}

A goal is owned by the last stage whose `objectives` name it or one of its objectives. `schema` starts only where every `evidence` output is a structured output of the owning node with that schema, and the schema is a published `artifact_schema`. A refused operator still compiles: the report says `ok: true` and `startable: false` and names it in `start_blockers` (`completion_evaluator_unavailable`). To accept text by review, end a Stage Graph with a `human_gate` whose `objectives` name every goal.

On a lane that requires `sandbox`, a node starts only when `sandbox.profile` names a bound sandbox profile. List them with {op:list_sandboxes}.
