---
type: Concept
category: execution
title: "Deep Agents children: sync profiles, seeds and sealed async children"
description: How a Deep Agents node's children get capabilities and return results - sync children (SyncSubagentProfile; inherit or seeded; the discriminator and no implicit general-purpose child) and async children (AsyncSubagentContract; exact or sealed_child graph, custody, check-time admission, exact adoption into SubmitOutput@2).
tags: [mission-control, deep-agents, subagents, agent-server, output-contracts, sealed-binding, implementation]
aliases: [async-children, SyncSubagentProfile, sealed child binding, subagent profile, task tool]
questions:
  - How do a node's children get capabilities and return results?
  - What is the difference between an inherit and a seeded child?
  - How does an async child run from its own sealed binding?
  - How does a parent use an async child's result and fulfil a promise with it?
  - Why does a node with no agents have no task tool?
updated: 2026-11-01
---

# Deep Agents children

A `mc.subagent_profile.v1` (`domain/capabilities/subagents.py`) selected under a node's `agents:` becomes one of three children.
All run inside the parent's unit, under the parent's budget and Stop Fence; none schedules anything (Temporal does:
[temporal synthesis](temporal-synthesis.md)). Only Stage Graph and Goal Loop nodes run the lane today
([Deep Agents lane](deep-agents-lane.md)).

| Child | Contract | Runs | Result reaches the parent |
| --- | --- | --- | --- |
| sync, `capabilities: inherit` | `SyncSubagentProfile` with `inherits_parent` | in-process deepagents `SubAgent` (`task` tool) | `ToolMessage` of the `task` call |
| sync, `capabilities: seeded` (default) | `SyncSubagentProfile` with narrowed refs and `seeded_*` | in-process `SubAgent` | same |
| async, `kind: async` | `AsyncSubagentContract` (`belllabs.async-subagent-contract.v1`) | a graph on the Agent Server | `check_async_task` through check-time admission |

## Sync children

`SyncSubagentProfile` (`domain/execution/contracts.py:699`): `name`, `description`, `system_prompt_ref` (a prompt pinned by digest;
the text is served under that digest or carried inline in `system_prompt`, which must hash to it), `model`, `tool_refs`,
`skill_refs`, `mcp_server_refs`, `state_slice_id`, `context_slice_id`, `workspace_id`, `writable_paths`, `budget_limits`,
`interrupt_on`, and the shape fields `inherits_parent` and `seeded_tools|skills|mcp_servers`. A validator forbids an inheriting child
from naming components.

- **Inherit** is the provider's general child made explicit: every parent tool, MCP tool and Skill root, the parent's model, and the
  lane's default prompt `INHERIT_CHILD_PROMPT` (`adapters/deep_agents/lane.py:120`) when the profile has none.
- **Seeded** narrows the parent's components by name and may bring `seeds`: exact catalog pins (`skills`, `mcp_servers`, `plugins`,
  `tools`) of the child's own. A seed equal to a parent component folds into narrowing. The lane seals them as `seeded_*` components
  inside the delegation ceiling and the materializer connects the child's MCP servers and mounts its Skill bundles beside the parent's
  (`adapters/deep_agents/materializer.py::_materialize_subagents`, `child_files`).
- **The discriminator** (`application/authoring/subagent_discriminator.py`) runs on every `agents:` entry at compile: it reads the
  lane support table (`subagent_support.py`, the Deep Agents row `describe.DEEP_AGENTS_SUBAGENT_FIELDS`), turns non-native cells into
  pointed blockers or warnings, refuses `provider_overrides` for another lane (`domain/capabilities/subagent_overrides.py`) and
  queues the seeds as the child's capability requests. The launch author marks them `seed_of`; `DeepAgentsCompileAdapter._seeds`
  binds them ([agent configuration](agent-configuration.md)). `GET .../lanes/{profile}` serves the lane's `subagent_fields`.
- **No implicit child.** `adapter.py::_disable_implicit_general_purpose_child` (`:1318`) stops deepagents adding `general-purpose`:
  a node with no `agents:` has no `task` tool, and a parent's children are exactly the declared ones.
- **Stops and points.** `_subagent_specs` (`adapter.py:1350`) attaches the parent's turn stops and a stop-guarded summarizer to every
  child, drops child filesystem `permissions` beside an executable sandbox, and a child's checkpoints are walked up to
  `MAX_SUBAGENT_POINT_WALK` (512) per namespace. Parallel `task` calls bind to `tools:<task_id>` namespaces exactly.
- Context: deepagents 0.7.5 passes a child every parent state key except `messages`, `todos`, `structured_response` and private keys
  ([surface 0.7.5](../research/deep-agents/surface-0.7.5.md)); the profile's slices narrow what Mission Control hands over.

## Async children: two graphs a profile can be bound to

`ManifestLaunchBindings.deep_agents_async_graphs.<profile>` (`AsyncSubagentGraphBinding`, `manifest_launch_inputs.py:451`) names the
served graph, with a registered result admission policy (`parent_completion.py::ASYNC_RESULT_POLICIES`); the deployment credential joins
the operation's `secret_refs`; the spawn takes the strongest dependency class the contract allows (`spawn_dependency_class`).
`binding_mode: exact` (default) keeps a graph with one binding the server hosts, the technical child: the profile's own prompt,
model and tools do not reach it and the receipt says so. `binding_mode: sealed_child` binds the generic graph `belllabs_async_child`
(revision `sealed-child@1`); `missionctl lane async-graphs --graph belllabs_async_child` prints it from the running server.
`DeepAgentsAsyncSubagentAdapter` (`adapters/deep_agents/async_subagents.py`) starts, checks, updates, cancels and lists runs, verifies
the served graph identity before submission and on reconnect, uses the child execution id as the provider thread with a spawn key so an
existing run is found first, and records cancellation as `provider_acknowledged` or `ambiguous`; `BellLabsAsyncSubagentMiddleware`
presents the stock tool names while routing each call through the governed service, which reserves and links the child first (ADR-0006).

**Sealing at launch** (`lane.py::_seal_async_child`, `child_binding.py::seal_async_child_binding`): the shared domain compiler produces a
`SealedAsyncChildBinding` (`belllabs.async-child-binding.v1`, `contracts.py:1483`) from the child's own exact configuration: `inherit`
takes the parent's model, tools, Skills, MCP servers and the general prompt; `seeded` the named components plus seeds within the
delegation ceiling, and its own model profile when named. It adds the child's own state-backend features (`max_turns` becomes
`deep_agents.call_limits`), a remote-managed placement and a State sandbox of its own (`adapters/agent_server/async_subagents/bindings.py:254`),
refuses what a hosted child cannot honour (approval gates, a prompt bundle) and degrades what it runs correctly without (`readonly`,
`context_mode: fork`, plugin members other than Skills and MCP). The sealed digest covers prompt and binding and is the contract's
`graph_binding_digest`.

**Custody and server.** The governed spawn writes the contract to the immutable, scoped `mission_control.subordinate_contract` row
before any provider call; that row is the custody. The adapter ensures one Agent Server assistant per binding and scope
(`sealed_child_assistant_id(scope, digest)`). On the server `SealedChildGraphFactory` (`adapters/agent_server/async_subagents/sealed.py`)
takes the scope from the verified `bl1` claim, requires the run's assistant to be that scope's, reads the contract through
`PostgresSealedChildCustody` (forced RLS), re-verifies both digests, and compiles through the worker's own
`build_hosted_async_subagent_graph(..., sealed=...)`, cached per scope and digest (LRU of 128). Credentials are the server's
`environment:` variables, one model key per vendor. Spend stays per parent: usage is stamped, attributed at completion and settled
into the parent's budget. `deployment_auth.py` limits a subordinate to its own scope's assistant.

## Output obligations: admission, then adoption

`application/subordinates/admission.py::CheckTimeAdmission` runs inside the governed `check_async_task`: (1) the asker must be the
child's spawning run and binding under the sealed contract digest (`audience_mismatch`, `contract_digest_mismatch`); (2) an active or
in-doubt child is `pending`; (3) an undecided completed child is decided once through its registered policy with the live generation, and
concurrent checks serialize on the link row (`decide_link`, compare-and-set; one writer reports `newly_decided`); (4) an admitted result
returns its exact text and a `child_result_index` entry (`domain/execution/async_child_admission.py`). The parent boundary
(`parent_completion.py::AsyncChildCompletion`) settles the child once; a follow-up to a non-live child is refused before any journal
or provider call. **Admission makes output usable; it fulfils nothing.** `adopt_async_task_output` calls
`AsyncChildOutputAdoption`: only this parent's admitted child, with the manifest still naming those bytes, is offered unchanged as one
inline candidate of the parent's `SubmitOutput@2` with derivation `async-child-result:<child>@<manifest digest>`; the parent's pinned
promise, form and checks decide it ([output contracts](output-contracts.md), ADR-0058).

Proof: unit tests below; real PostgreSQL custody and admission; a real local Agent Server with real custody and a deterministic
model; a manifest-launched sealed child through Temporal whose admitted result the parent used. Paid observation with real models is
the W5 gate. The cross-tenant risk of the shared claim-signing key is unchanged (`async_subagents/auth.py`).

Specified, not built (owner spec pack, recovered from `HEAD`; no `mc.message.v1`, `mc.progress.v1` or memory-namespace symbol in `src/`): a parent/child message protocol with one sequence frontier per target
generation, durable messages read at a declared safe boundary, bounded parent messages (new context, answer, pause/stop, scope-preserving instruction) and child messages (progress, blocker, candidates); today
a message to a live async child goes through the governed `update_async_task`; stock async update uses the interrupt strategy, which the spec says queued delivery must not inherit (it waits for a qualified boundary).

Built / specified / goal: built and integrated locally; paid C10-C13 unrun; a child that is its own mission is a linked workflow
([mission chains](mission-chains.md)), not a subagent.

## Citations

- ADRs: [0006](../adr/0006-agent-server-required-execution-host-not-scheduler.md), [0058](../adr/0058-composable-output-obligations-and-one-submission-act.md). Design history: [SUBAGENTS](../specs/archive/provider-consolidation-2026-10/specs/SUBAGENTS.md), [ASYNC-SUBAGENTS-EXPLAINED](../specs/archive/provider-consolidation-2026-10/docs/ASYNC-SUBAGENTS-EXPLAINED.md).
- Code: [contracts](../../src/mission_control/domain/execution/contracts.py), [lane adapter](../../src/mission_control/adapters/deep_agents/lane.py), [child binding](../../src/mission_control/adapters/deep_agents/child_binding.py), [async subordinates](../../src/mission_control/adapters/deep_agents/async_subagents.py), [discriminator](../../src/mission_control/application/authoring/subagent_discriminator.py), [admission](../../src/mission_control/application/subordinates/admission.py), [adoption](../../src/mission_control/application/subordinates/adoption.py), [sealed graph](../../src/mission_control/adapters/agent_server/async_subagents/sealed.py), [custody read](../../src/mission_control/adapters/postgres/async_subagents/sealed_child_custody.py), [deployment auth](../../src/mission_control/adapters/agent_server/deployment_auth.py).
- Tests: [lane children](../../tests/unit/deep_agents/test_lane_adapter_children.py), [materializer children](../../tests/unit/deep_agents/test_materializer_children.py), [discriminator](../../tests/unit/authoring/test_subagent_discriminator.py), [seeds](../../tests/unit/authoring/test_subagent_seeds_compile_and_launch.py), [sealed binding](../../tests/unit/deep_agents/test_async_child_sealed_binding.py), [check-time admission](../../tests/unit/operations/test_async_child_check_time_admission.py), [sealed graph](../../tests/unit/agent_server/test_sealed_child_graph.py), [PostgreSQL](../../tests/integration/postgres/test_wi23_async_children_postgres.py), [real server](../../tests/integration/agent_server/test_wi23_sealed_child_server.py), [manifest async child](../../tests/acceptance/mission_control/test_manifest_async_child.py), [manifest sealed child](../../tests/acceptance/mission_control/test_manifest_sealed_async_child.py).
