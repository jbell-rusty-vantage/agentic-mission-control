---
type: Concept
category: execution
title: Deep Agents agent configuration
description: How a Deep Agents node is configured from manifest to sealed binding - the deployment launch bindings, the lane compile path with its refusals, sandbox profile and model resolution, lane features and model tools in provider_options, the neutral mc.agent_configuration.v2, charter mount and the v1 residual.
tags: [mission-control, deep-agents, configuration, compile, sandbox, models, features, implementation]
aliases: [lane compile, DeepAgentsCompileAdapter, manifest launch bindings, provider_options.deep_agents, sealed lane binding]
questions:
  - How is a Deep Agents node configured, from manifest to sealed binding?
  - Where is a node's sandbox profile resolved and what makes it refuse?
  - How does a node get its model and which features and model tools can it select?
  - What does mc.manifest_launch_bindings bind, and who checks it?
  - Which refusal codes can a Deep Agents compile return?
updated: 2026-11-01
---

# Deep Agents agent configuration

A node's configuration is a chain of four steps, each pure over the one before. Use the [selection
workspace](selection-workspace.md) first: `missionctl workspace check` runs the same admission read-only.

1. **Author** (manifest, [mission manifest](mission-manifest.md)): `environment` selects the lane, model profile,
   sandbox (`SandboxSelection{profile, egress}`, `domain/authoring/manifest.py:602`), capabilities and
   `provider_options.deep_agents`.
2. **Resolve** (the seam, ADR-0063): `ManifestLaunchResolver.deep_agents_node`
   (`application/authoring/manifest_launch_inputs.py:766`) builds the neutral `mc.agent_configuration.v2` (below) and calls
   `RuntimeResolver.resolve`, which asks the lane to compile.
3. **Compile** (`adapters/deep_agents/compile.py::DeepAgentsCompileAdapter.compile`): maps every item to an exact
   deployment component and seals `mc.deep_agent_node_binding.v1` with a signed `mc.materialization_receipt.v1`.
4. **Bind** (`adapters/deep_agents/binding.py::DeepAgentsLaneBindings`, the `LaneTemplateBinder` bootstrap injects): adds the
   author's template coordinates and seals the `DeepAgentExecutionBinding` (`belllabs.deep-agent-binding.v1`) as the template's
   `lane_binding` plus `lane_dispatch`; each family rebinds it per attempt (`rebind`, SV-01). Every reader decodes it with
   `binding.execution_binding`, which refuses bytes outside the operation's authority envelope (OC-R2). The materializer
   realizes it ([Deep Agents lane](deep-agents-lane.md)).

Scheduling of the node is the family's ([workflow systems](workflow-systems.md): only Stage Graph and Goal Loop are `native`
here, `describe.py:156-159`). Output obligations bind through the model's structured-output strategy (below) and the
[output contracts](output-contracts.md); context reaches the node through the sealed transfer plan
([context and continuation](context-and-continuation.md)).

## Deployment facts: `mc.manifest_launch_bindings`

The operator-reviewed file (`ManifestLaunchBindings`, `manifest_launch_inputs.py:502`, schema `.v1`, or `.v2` with a
`providers` section) holds what the deployment serves: `deep_agents` (`DeepAgentScaffold`: profile, placement, state and
context schemas, policy refs), `model_profiles`, `sandbox_profiles` (`:514`, name to `DeepAgentSandboxComponent`), `capabilities` (exact MCP server, Skill or tool
components keyed by capability id), `deep_agents_async_graphs`. Example: `deployments/examples/manifest-launch-bindings.deep-agents.example.json`.
Bootstrap composes it with the served components into `DeepAgentsDeploymentFacts` (`compile.py:118`); a process with no facts
executes sealed bindings and compiles none (`LANE_UNKNOWN`). Preflight refuses a binding whose sandbox, model or component digest is
not served (`bootstrap/preflight.py:533`, `COMPONENT_UNPINNED`, `AUTH_SECRET_ENV_UNDECLARED`).

## The compile path and its refusals

`compile` (`compile.py:380`) runs, in order: `_model`, `_sandbox`, `_components`, `_unsupported`, `_middleware`, `_subagents`, then
`DeepAgentsLaneAdapter().adapt` (`lane.py`) which parses `provider_options.deep_agents`, builds children and the receipt. Refusals
are `ResolutionRefused` with a pointer and a remedy (`domain/resolution/resolved.py:212`):

- `ITEM_PIN_UNSERVED`: a pin with no deployment binding, or bound but not served, or pinned at a different digest than bound; no
  scaffold; a middleware not on the scaffold profile.
- `ITEM_UNSUPPORTED_ON_LANE`: a hook script, context bundle, environment kit or node-level plugin member (the lane has no launch
  binding for them, `describe.py:134-153`); not exactly one sandbox profile; a sandbox backend the placement does not qualify.
- `LANE_OPTIONS_INVALID`: a bad `provider_options.deep_agents` block. `MODEL_ROUTE_UNSUPPORTED`: the route does not realize the row's
  structured-output strategy. `LANE_UNQUALIFIED`/`LANE_UNKNOWN`: admission.

**Sandbox.** The manifest's profile name becomes an item of kind `sandbox_profile` (`manifest_launch_inputs.py:815-833`).
`_sandbox` (`compile.py:561-600`) requires exactly one, looks the name up in `facts.sandbox_profiles`, checks its digest in
`facts.served.sandboxes`, and checks `component.backend` against `scaffold.placement.sandbox_backends`. If
`provider_options.deep_agents.sandbox_backend` is set it must equal the profile's backend (`lane.py:338-348`; `contracts.py:1377`);
that option's `Literal` omits `daytona` (`provider_options.py:83`). Children use their own State sandbox ([children](deep-agents-children.md)).
The capability matrix declares `sandbox_profile: native` (`describe.py:153`), and the Selection Workspace has a `sandbox_profile`
facet (`application/selection/workspace.py:79-116,585-616`). Which backends have factories: [Deep Agents lane](deep-agents-lane.md#sandbox-backends).

**Model bindings.** The vendor and model id come only from the resolved [Model Catalog](model-catalog.md) pin; the deployment's
`model_profiles` binding names the served definition ref and default settings (`catalog_model_components`, `compile.py:218`).
A served definition whose declared vendor or model id differs from the row fails composition (`MODEL_PIN_VENDOR_MISMATCH`,
`MODEL_PIN_MODEL_MISMATCH`, `MODEL_PIN_UNDECLARED`, `compile.py:164-166`); a row with `api_surface = responses` forces
`use_responses_api` and refuses a contrary setting. `ExactModelFactory` builds the client for the pinned vendor;
`AnthropicExactModelFactory` maps `max_completion_tokens` to `max_tokens`, `minimal` effort to `low`, defaults `max_tokens` to 8192
and refuses `verbosity`, `service_tier` and `use_responses_api`. A route's structured-output strategies are `tool_forced`,
`provider_native` and `tool_auto` (`routes.py:61-76`).

## `provider_options.deep_agents` (`mc.provider_options.deep_agents.v1`)

Parsed at manifest compile (`domain/authoring/provider_options.py:59`): `sandbox_backend`, `summarization` (`trigger_messages` or
`trigger_tokens`, `keep_messages`), `interrupt_on` (parks the unit `in_doubt`, receipt `degraded`, until the human-control binding
lands), `lane_features` and `model_tools`. The first three are validated by the domain; model tools are validated by the lane at launch.

The **feature registry** (`domain/capabilities/features/`, rows in `deep_agents.py` and the vendor rows in
`adapters/deep_agents/routes.py`, composed as `AGENT_FEATURES`) says per row: lane feature or model tool, domain and facet,
mechanism (`middleware`, `provider_tool`, `model_setting`), where a call is observed, and status. Lane features:
`filesystem`, `bash`, `todo_list`, `context_editing`, `summarization`, `call_limits`, `filesystem_permissions`, `memory`, `rubric`,
`code_interpreter`. Model tools: `anthropic.{prompt_caching, web_search, web_fetch, code_execution, bash, memory, clear_tool_uses,
compaction, text_editor}`, `openai.{web_search, file_search, code_interpreter, compaction, moderation, auto_mode, model_router}`.
`DeepAgentsLaneAdapter._agent_configuration` (`resolve_agent_configuration`, `features/configuration.py`) inserts defaults, refuses
unknown, unavailable or wrong-provider rows, seals `mc.agent_configuration.v1` in the binding and writes one receipt item per
selection. The materializer realizes them (`features/builders.py`): middleware after Mission Control's own in rank order,
provider tools as dict tools beside the agent's (a provider-executed call does not appear in the tool node), model settings merged
into the model component before the factory runs. Whether the registry becomes catalog rows is a proposal
([AC-D1..D12](../specs/provider-consolidation-2026-10/AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23.md)). Deep Agents grants network
hosts as advisory worker-tool hosts only ([lane](deep-agents-lane.md#sandbox-backends)).

## The neutral configuration (`mc.agent_configuration.v2`)

`domain/resolution/configuration.py::AgentConfiguration` is built by the launch author and sealed under `configuration_digest`: the
`lane_profile`, `node_ref`, `instructions_ref`, the `model` pin (profile, vendor, model id, window, input limit, prices, settings),
`items` of nine kinds (`skill_bundle`, `mcp_server`, `tool`, `hook_script`, `subagent_profile`, `environment_kit`, `context_bundle`,
`middleware`, `sandbox_profile`), `budgets`, `data_class` and `data_class_source` (`declared` or `ceiling_default`, OC-R4). It carries
no lane vocabulary. **Charter mount** (tested, not run live): a knowledge mission gets its application's charter Skill at `@latest`
unless it pinned one (`manifest_service.py:1156`).

**Residual B1.** The v1 `AgentConfiguration`, `FeatureAxis`, `Mechanism` and the Deep Agents rows still live in
`domain/capabilities/features/` because `DeepAgentExecutionBinding` imports them (`contracts.py:1154,1319`); they move with the
provider sweep (OVE-203, [residuals](../specs/archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-INTERFACES.md#81-recorded-residuals-r7-review-2026-10-27)).

Built / specified / goal: compile, bindings and features built and tested; paid live test exists but its run is unverified; mutation of a
configuration mid-workflow is a goal ([revisions](revisions.md)).

## Citations

- ADR: [0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md).
- Code: [compile](../../src/mission_control/adapters/deep_agents/compile.py), [lane adapter](../../src/mission_control/adapters/deep_agents/lane.py), [binding](../../src/mission_control/adapters/deep_agents/binding.py), [routes](../../src/mission_control/adapters/deep_agents/routes.py), [builders](../../src/mission_control/adapters/deep_agents/features/builders.py), [launch inputs](../../src/mission_control/application/authoring/manifest_launch_inputs.py), [provider options](../../src/mission_control/domain/authoring/provider_options.py), [neutral configuration](../../src/mission_control/domain/resolution/configuration.py), [registry](../../src/mission_control/domain/capabilities/features/registry.py), [preflight](../../src/mission_control/bootstrap/preflight.py).
- Tests: [compile](../../tests/unit/deep_agents/test_compile.py), [compile conformance](../../tests/conformance/lanes/compile/deep_agents.py), [launch inputs](../../tests/unit/authoring/test_manifest_launch_inputs.py), [registry](../../tests/unit/capability/test_agent_feature_registry.py), [lane features](../../tests/unit/deep_agents/test_lane_adapter_features.py), [materialization](../../tests/unit/deep_agents/test_agent_configuration_materialization.py), [paid live proof](../../tests/integration/deep_agents/test_agent_configuration_live.py).
- Related: [Deep Agents lane](deep-agents-lane.md), [model catalog](model-catalog.md), [capabilities](capabilities.md).
