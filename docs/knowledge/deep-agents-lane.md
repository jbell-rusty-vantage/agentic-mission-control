---
type: Concept
category: execution
title: Deep Agents lane
description: How the Deep Agents lane runs one attempt as bounded cognition under Temporal - adapter, harness, exact materializer, the middleware stack in its built and required order, the sandbox backends (State, LangSmith, Docker built; Daytona admitted but unwired), turn stops, frames, closure - and which pieces are specified but not built.
tags: [mission-control, deep-agents, lanes, middleware, sandbox, turn-stops, implementation]
aliases: [DeepAgentRuntimeAdapter, exact materializer, deepagents lane, sandbox backends, turn stops]
questions:
  - How does the Deep Agents lane materialize and run an agent?
  - Which sandbox backends does Deep Agents actually support?
  - Why did a Deep Agents turn stop before the model answered?
  - What is mc.extension_profile.v1 and is it built?
updated: 2026-11-02
---

# Deep Agents lane

Deep Agents is the reference lane: the owner calls its configuration "a high quality representation of our agent
capability and workflow architecture", and every other provider follows its adapter shape ([lanes and
harness](lanes-and-harness.md)). It is bounded cognition over LangGraph, extended through public interfaces and never
forked (ADR-0005), pinned to `deepagents==0.7.5` and `langgraph==1.2.10` (`pyproject.toml:18,32`; research:
[surface 0.7.5](../research/deep-agents/surface-0.7.5.md)). Its describe flag `qualified=True`
(`adapters/deep_agents/describe.py:119`) means the WP-CP-040 parity suite passes, not that gate W1 is released
(`NEXT-SESSION.md:122`).

## Scheduling

Temporal alone schedules ([temporal synthesis](temporal-synthesis.md)). Stage Graph and Goal Loop (GoalDirected in code)
are the only families the lane declares `native`; `ParallelSwarm` and `EvaluatorOptimizer` are `unqualified`
(`describe.py:156-159`; [workflow systems](workflow-systems.md)). A unit runs inside `operation.execute` by default;
`MISSION_CONTROL_LANE_SEGMENT_LOOP=true` moves it onto the `lane.turn` loop (`bootstrap/settings.py:395`, default false).
`DeepAgentRuntimeAdapter.execute` (`adapter.py:296`) validates the exact binding, materializes it, classifies the unit
generation from the checkpointer, then submits, resumes or fails closed; it returns when cognition completes and the
boundary saves the result and settles it with no further model call ([saved-result settlement](saved-result-settlement.md)).
`DeepAgentsHarness` (`harness.py`) wraps the adapter in the neutral protocol (`snapshot` is emulated).

## Output-contract obligations

A node's output schema binds in the Model Catalog row's declared strategy (`response_format_for`, `ToolStrategy` or
`ProviderStrategy`; `tool_auto` binds the tool strategy with tool choice auto and adds `RequireStructuredResponse`,
`materializer.py:665-674`, W1 D18). `structured_response` is read only if this invocation wrote it
(`adapter.py::_structured_response_written`), because `create_agent` never clears the channel. Parent and child
results reach the Submission Act through `SubmitOutput@2`; the child side is in [deep-agents children](deep-agents-children.md)
and the obligations in [output contracts](output-contracts.md). At every settled, failed or cancelled boundary the lane
captures a workspace closure of what the agent could see ([workspace closure](workspace-closure.md)).

## Context transfer

The sealed transfer plan is delivered to the backend before the first model call (`/inputs/**` and `/.mission/**`:
a sandbox upload, or the `files` channel on the text-only State backend) and forgotten with the attempt
(`materializer.py:552`; [context and continuation](context-and-continuation.md)). Knowledge reads reach only what the
plan holds (`adapter.py:370-376`, `knowledge_tools.py`). Every root checkpoint is a cognition point
(`cognition_points.py::collect_points`); `time_travel.py` reads state as of a point and seeds a fork at R3
([recovery](recovery.md), [precise fork](precise-fork.md)).

## Runtime and capability configuration

`ExactDeepAgentMaterializer.prepare` (`materializer.py:527`) resolves every component by digest from an
`ExactComponentRegistry` (model factory, sandbox factory, tools, MCP servers, middleware, subordinate profiles,
checkpointer, store), mounts Skill bundles and rejects a runtime-version mismatch; a `hosted` binding leaves
checkpointer and store to the Agent Server. How a node's configuration reaches this point (resolution seam, compile,
sealed binding) is in [agent configuration](agent-configuration.md). The LangGraph saver and store bind to the private
`mission_control_runtime` schema ([persistence](persistence.md), ADR-0017).

### Middleware order

Built: the order Mission Control hands to `create_deep_agent(middleware=...)`:

<!-- snippet: src/mission_control/adapters/deep_agents/materializer.py:593-608 -->
```python
            middleware = (
                # Tracing Stage 2 (F-S2-9): a fenced run calls the model no more.
                FenceStopMiddleware(lambda: ports.stop_fence.run_fenced(hook_context)),
                HookScriptMiddleware(
                    dispatcher, mcp_tools=frozenset(tool.name for tool in mcp_tools)
                ),
                ObservedSummarizationMiddleware.observed(
                    model,
                    backend,
                    dispatcher,
                    trigger=summarization_trigger,
                    keep=summarization_keep,
                ),
                *catalog_middleware,
                *realized.middleware,
            )
```

`adapter.py::_compile` (`:1419-1423`) then appends, in order: `RequireStructuredResponse` (tool_auto only,
`materializer.py:671`), the governed async-subagent middleware when async children exist, `BudgetStopMiddleware` when
a bounded dimension is set (`adapter.py:402`), and a configured filesystem replacement. A hosted graph adds
`ServedGraphIdentityMiddleware` (`adapter.py:291`). deepagents wraps this list inside its own stack (Skills, Filesystem,
SubAgent, Summarization, PatchToolCalls, AsyncSubAgent, then user middleware: `surface-0.7.5.md`); the observed
summarizer therefore carries the turn stops itself (`adapter.py:1428-1430`). `HookScriptMiddleware` runs the four Kernel
Hooks (stop fence, operation intent, frame capture, usage) first, in fixed order, then catalog hook scripts
([capabilities](capabilities.md)); `ObservedSummarizationMiddleware` emits `before_compaction`/`after_compaction`
frames instead of compacting silently.

Required (specified, owner spec pack `CONTEXT-STATE-AND-CONTROL`, deleted 2026-11-01; recovered from `HEAD`): the
effective order is before-model (budget, stop, context selection), wrap-model (usage reservation and accounting),
before-tool (argument, authority and effect admission), wrap-tool (stable intent and receipt, bounded result offload),
after-tool (artifact custody), after-model (typed candidate extraction). The guards must cover native default tools,
shell/`execute`, dynamic subagent launch and background tasks, and replace stock `task` channel propagation with admitted
subordinate graphs. Built today: stop fence and budget stop (`wrap_model_call`), hook events for shell, file-edit and MCP tools
(`hooks.py:964-975,1143`) and governed async children; **not built**: a declarative effective-order profile. `mc.extension_profile.v1`, the sealed document that would declare and golden-test this order, has no hit in
`src/`, `packages/`, `tests/` or `deployments/` (checked 2026-11-01): specified, not built.

### Sandbox backends

`DeepAgentSandboxComponent.backend` is `Literal["langsmith", "daytona", "docker", "state"]`
(`domain/execution/contracts.py:686`); the placement lists the admitted ones (`sandbox_backends`, `:1207`). Factories
(`SandboxFactory`, `materializer.py:115`, registered by digest in `adapters/temporal/deployment_composition.py:514-529`):

| Backend | Factory | Isolation |
| --- | --- | --- |
| `state` | `StateSandboxFactory` (`materializer.py:282`) | in-memory `StateBackend`, no `execute` |
| `langsmith` | `LangSmithSandboxFactory` (`materializer.py:491`) | `SandboxClient.create_sandbox`, deleted on exit |
| `docker` | `DockerSandboxFactory` (`docker_sandbox.py:120`) | `--network none`, read-only root, tmpfs, `--cap-drop ALL`, 64 pids, 256m/0.5 cpu |
| `daytona` | **none** | admitted but unwired |

**Daytona is half-wired.** The contract admits it; closure names it (`adapters/deep_agents/workspace_closure.py:97`,
`domain/execution/workspace_closure.py:45`); the frame redactor hides `DAYTONA_API_KEY` (`domain/frames/body.py:41`); the
network projector knows Daytona tiers ([sandbox tiers](../research/daytona/sandbox-tiers.md)). But `materializer.py`
and `docker_sandbox.py` have no Daytona factory; deployment pins admit only `state`/`docker`/`langsmith` (`capability_pins.py:286`,
one factory each, exhaustive since OVE-216), so compile refuses a Daytona profile as `ITEM_PIN_UNSERVED` before any run (`compile.py:585`). `provider_options.deep_agents.sandbox_backend` omits it too
(`domain/authoring/provider_options.py:83`). Code issue for OVE; research: [sandbox providers](../research/deep-agents/sandbox-providers.md).

Network ([environments](environments.md)): exact worker-tool hosts are sealed into the operation grant (`network.py:389`, advisory); sandbox networking is unchanged.

**To add a sandbox provider across Stage Graph and Goal Loop:** (1) a factory and a `Literal` member (`contracts.py:686,1207`,
`provider_options.py:83`); (2) a branch in `deployment_composition.py` and a dependency; (3) a placement
`sandbox_backends` entry and a `sandbox_profiles` launch binding ([agent configuration](agent-configuration.md));
(4) closure and network rows (`workspace_closure.py`, `network.py`); (5) proofs: compile conformance
(`tests/conformance/lanes/compile/deep_agents.py`), launch inputs (`tests/unit/authoring/test_manifest_launch_inputs.py`),
`tests/acceptance/mission_control/test_overnight_stagegraph.py` and `test_overnight_goal_directed.py`, and async-child
`test_manifest_async_child.py` (children use their own State sandbox, `child_binding`; [children](deep-agents-children.md)).

### Turn stops and capture bounds

`BudgetStopMiddleware` (spend exceeds a bounded dimension, `>` as in the settlement; the limit is the tighter of the reservation and what the authored run budget leaves, and a tool call past `tool.calls.total` is refused before it runs, W1 D41) and `FenceStopMiddleware` (journaled cancel) end a turn at the next model call by answering with an `AIMessage` marked `mc_budget_stop` or `mc_fence_stop`
(`adapters/deep_agents/budget.py:41,57,89,135`). They wrap the model call and add no graph node, so step numbering
does not move; both guard the summarizer and are attached to every sync child (`adapter.py::_subagent_specs`). An unreadable fence fails open (the kernel hook still gates effects). Parallel `task` calls bind to their namespaces
exactly; nested point walks stop at 512 (`MAX_SUBAGENT_POINT_WALK`) and mark `points_status: incomplete`
([recovery](recovery.md)); settlement of a stopped turn: [budgets and usage](budgets-and-usage.md). **Open defect:** `describe.py:80` still declares `cancel: turn_boundary_guaranteed` and `:113` `usage.cost="estimated"`;
live fixtures showed an immediate cancel enforced at the next model call and cost unknown (tokens and turns only). The
corrected cells never shipped in a SQL release (OVE issue to file).

Frames key Provider Frames by root checkpoint ([provider frames](provider-frames-and-transcript.md)); children: [deep-agents children](deep-agents-children.md); Agent Host file generation executes nothing ([capabilities](capabilities.md)).
Built / specified / goal: built and integrated (live paid Qualia and AI Engineer fixtures, `NEXT-SESSION.md:32-98`); W1
qualification unreleased; `mc.extension_profile.v1` and the Daytona factory specified or admitted but not built; per-policy
mutation mid-workflow is a goal ([goals](goals.md)).

## Citations

- ADRs: [0005](../adr/0005-deep-agents-first-extend-not-fork.md), [0006](../adr/0006-agent-server-required-execution-host-not-scheduler.md), [0017](../adr/0017-agent-server-runtime-persistence-separate-database.md).
- Code: [adapter](../../src/mission_control/adapters/deep_agents/adapter.py), [harness](../../src/mission_control/adapters/deep_agents/harness.py), [materializer](../../src/mission_control/adapters/deep_agents/materializer.py), [Docker sandbox](../../src/mission_control/adapters/deep_agents/docker_sandbox.py), [turn stops](../../src/mission_control/adapters/deep_agents/budget.py), [hooks](../../src/mission_control/adapters/deep_agents/hooks.py), [describe](../../src/mission_control/adapters/deep_agents/describe.py), [composition](../../src/mission_control/adapters/temporal/deployment_composition.py), [contracts](../../src/mission_control/domain/execution/contracts.py), [network](../../src/mission_control/application/environments/network.py).
- Tests: [turn stops](../../tests/unit/deep_agents/test_turn_stops.py), [budget stop](../../tests/unit/deep_agents/test_budget_stop.py), [hooks](../../tests/unit/deep_agents/test_hook_middleware.py), [structured output](../../tests/unit/deep_agents/test_structured_output.py), [closure](../../tests/unit/deep_agents/test_workspace_closure.py), [StageGraph](../../tests/acceptance/mission_control/test_overnight_stagegraph.py), [Goal Loop](../../tests/acceptance/mission_control/test_overnight_goal_directed.py), [T0 cancel](../../tests/acceptance/mission_control/test_tracing_stream.py).
- Research and proof: [surface 0.7.5](../research/deep-agents/surface-0.7.5.md), [sandbox providers](../research/deep-agents/sandbox-providers.md), [change ledger](../specs/provider-consolidation-2026-10/providers/deep_agents/CHANGES.md), [control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md).
