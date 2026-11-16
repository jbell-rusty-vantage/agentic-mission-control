---
id: launch
title: Author and launch
summary: Compile, preflight, submit, start: what each does, what a refused compile means, and where to stop for approval.
---
Four steps, each its own call. The first two commit nothing.

| Step | Call | What it does |
| --- | --- | --- |
| Compile | {op:compile} | Validates the manifest and resolves every `search` entry to an exact pin. Returns the Validation Report and persists nothing. |
| Preflight | {op:preflight} | Lists the owner setup, freshness, degradations and readiness this manifest needs before it can spawn. |
| Submit | {op:submit} | Compiles again, commits the manifest as a revision and admits its run (or its chain). Starts nothing. Send a new UUID as `request_id`; repeating it returns the same identities. |
| Start | {op:start} | Launches the admitted run: the only step that runs agents and spends budget. It subscribes your coordinator inbox to the run first. |

## A refused compile

A report with `ok: false` is a refusal: the definition cannot be committed, and a submit would refuse it too. Each entry of `blockers` has a `code`, a `pointer` into the manifest, a `message` and often a `reason`. Fix the manifest at the pointer and compile again. The report is evidence; change the manifest, never the report.

| `code` | Means | Do |
| --- | --- | --- |
| `INVALID_DEFINITION` | The shape or a rule is broken; `reason` says which (`widens_authority`: a node widened the budget, governors or side effects it inherits). | Fix the field at `pointer`. Nodes may only narrow. |
| `CAPABILITY_UNAVAILABLE` | A `search` entry has no admitted hit, or a pin is not in the catalog, was retired or is not supported on the node's lane. | Search again (topic `capabilities`). |
| `CAPABILITY_DRIFT` | A pin's version or digest does not match the admitted row. | Pin the row the message names. |
| `UNSUPPORTED_BEHAVIOR` | The lane does not run that node's behaviour. | Choose another lane or behaviour (topic `workflows`). |
| `APPLICATION_FORBIDDEN` | `mission.application` is not this server's application. | Write this server's application id. |

For any other code, act on its `message` and `reason`.

`warnings` do not block: show every one to the user before submit. `start_blockers` and `startable: false` name what a start would refuse although the compile is valid. `resolution.resolved` names the exact pin each `search` became; copy one into the manifest as `pin` when the user wants it frozen.

## Stop for approval

Submit and start are consequential. Before each, show the user what will be committed or launched (goals, lane, model, budget ceiling, side effects, warnings) and wait for their yes. Start only when the user asked for the start.

After start, keep the `run_id` and the `subscription_id` of `coordinator_inbox` from the receipt, and continue with topic `observe`.
