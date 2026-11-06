---
type: Architecture Projection
title: "Selection and routing across the variation axes: one resolution seam, registries as the only place a variant is named"
description: "Design for how provider, model, blueprint and application variation is resolved into one runtime without callers branching: the chosen mechanism, the module map, the ports, the depth test on paper, the conformance strategy, the sprint breakdown along module boundaries, and the open questions. Nothing here is built."
tags: [mission-control, knowledge-services, architecture, lanes, applications, resolution, sprint]
date: 2026-10-27
status: archived
archived: 2026-11-02
archived_from: sprint-oc/SELECTION-AND-ROUTING-DESIGN.md
archived_reason: "built R0-R7; ADR-0063 and the model-catalog, lanes-and-harness and agent-configuration concepts"
---

> **Archived 2026-11-02** (built R0-R7; ADR-0063 and the model-catalog, lanes-and-harness and agent-configuration concepts). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Selection and routing across the variation axes

Owner request of 2026-10-27 (recorded as OC-D197 in [DECISIONS §5](../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md#5-sprint-start-operating-decisions-2026-10-27)):
decide the adaptation mechanism and design the deep modules for selection and routing **before** any
implementation or agent-team spawn, so that Deep Agents stays the optimized first lane without its
concepts shaping the shared interfaces, and so that AI Engineer and Biotech are two instances of one
application port rather than two code paths. Accepted by the owner the same day (OC-D198 to OC-D202, §14). Issues: [OVE-194](https://linear.app/overtonbell/issue/OVE-194) (parent); R0 [OVE-195](https://linear.app/overtonbell/issue/OVE-195), R1 [OVE-196](https://linear.app/overtonbell/issue/OVE-196), R2 [OVE-197](https://linear.app/overtonbell/issue/OVE-197), R3 [OVE-202](https://linear.app/overtonbell/issue/OVE-202), R4 [OVE-198](https://linear.app/overtonbell/issue/OVE-198), R5 [OVE-199](https://linear.app/overtonbell/issue/OVE-199), R6 [OVE-200](https://linear.app/overtonbell/issue/OVE-200), R7 [OVE-201](https://linear.app/overtonbell/issue/OVE-201). Companion files: [interface sketches](SELECTION-AND-ROUTING-INTERFACES.md) (types and protocols only) and the accepted [ADR-0063](../../../../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md).

Every "today" claim below was verified read-only on 2026-10-27 against MC `dcb3e772`, KS `b45adf5`,
AIDB `306efd7`, BKS `c398177`; `path:line` cites the file. "Proposed" names what this design adds.
It is a projection, not as-built documentation, and it changes no accepted ADR.

## 1. The four axes, as they exist today

| Axis | Vocabulary today | Where selection happens today | What is wrong with it |
| --- | --- | --- | --- |
| 1. Agent framework provider | `host_support.LaneProfile`, nine values (`domain/capabilities/host_support.py:20-34`); the harness protocol `AgentHarness` with nine operations (`application/execution/harness/protocol.py:69-89`); per-profile declared matrices `DECLARED_LANE_MATRICES` (`application/execution/harness/describe.py:862`) | **Runtime:** one router, `LaneRegistry.for_profile` (`application/execution/harness/registry.py:92`), clean. **Compile/launch:** three resolvers in one module, `ManifestLaunchResolver.node` / `provider_node` / `cursor_node` (`application/authoring/manifest_launch_inputs.py:584, 1020, 1337`), the lane switch in `render_host_files` (`application/agentic_components/projections.py:163-195`), and static behavior tables `LANE_BEHAVIORS` / `V2_LANE_BEHAVIORS` | Only Deep Agents has a dedicated compile adapter (`application/authoring/lanes/deep_agents.py`); every other lane's compile translation is a branch in shared code. Lane names branch in about thirty non-adapter files (survey §2). The neutral operation request carries three lane-shaped binding slots `deep_agent_binding`, `cursor_binding`, `provider_binding` (`domain/execution/contracts.py:1450-1456`). |
| 2. Model within a provider | The manifest names a **model profile** (`ModelSelection.profile`, `domain/authoring/manifest.py:542`); the concrete id lives in a deployment file, `mc.manifest_launch_bindings`: top-level `model_profiles` (Deep Agents only, `DeepAgentModelComponent(provider: Literal["openai","anthropic"])`) and `providers.<profile>.model_profiles` (`ModelPin`) per lane (`manifest_launch_inputs.py:359-377`, `provider_launch.py:104`) | Deep Agents: `ManifestLaunchResolver._model` (`:818-883`) then `materializer.model_factory_for(provider)` (`adapters/deep_agents/materializer.py:349`). Other lanes: `_provider_model` (`:1240-1275`). Async technical child: an environment variable (`adapters/agent_server/async_subagents/bindings.py:59-63`) | The same logical model is declared once per lane with `OWNER-SELECT` ids (`deployments/examples/manifest-launch-bindings.multi-provider.example.json:340-550`). `settings.anthropic_model` / `openai_model` are dead (`bootstrap/settings.py:91-92`). Model-vendor features (`domain/capabilities/features/anthropic.py`, `openai.py`) live inside the Deep Agents feature registry. |
| 3. Workflow blueprint | `Behavior` (`manifest.py:394-405`); lowering supports `StageGraph` and `GoalDirected` only (`manifest_lowering.py:78`); Swarm and Evaluator Optimizer are specified, not implemented | A blueprint stage carries no lane; lane and capabilities attach through `template_key(stage, slot, variant)` to an `OperationExecutionRequest` (`manifest_launch_inputs.py:244`) | Family code branches on provider: `goal_directed.py:1288-1291` (`claude_managed` budget wait), `application/programs/service.py:1776-1815` and `goal_directed.py:670, 1280-1297` (rebind only `deep_agent_binding`). |
| 4. Application and knowledge storage | `ApplicationBinding.application_id` (`application/installations/registry.py:58-83`); `settings.knowledge_binding_ids = {"ai-engineer": "aiengineer-postgres", "biotech": "biotech-graph"}` (`bootstrap/settings.py:330-335`); one `KnowledgeGateway` per binding (`application/knowledge/gateway.py:143`); KS `KnowledgeOperationBackend` (`packages/host/src/knowledge-operation/ports.ts:103-123`) | MC: `knowledge_configuration(settings, application_id)` (`bootstrap/composition.py:475-519`). KS: `config.ts:131-173` if/else over a closed `z.enum(["aiengineer-postgres","biotech-graph","in-memory"])` (`:58`) | `gateway.py:317-373` branches on the Biotech apply contract to build the native payload; `manifest.py:974` and `mission_definition.py:388` close the application set as `Literal["biotech","ai-engineer"]`; KS host imports both binding packages statically and keeps Biotech's apply port in shared code (`native-ports.ts:169-240`); the Biotech binding depends on the AI Engineer binding's `PostgresResearchBinding` (`bindings/biotech-graph/src/research-binding.ts:15`). No driver, ORM or SDK type reaches MC `application/` or `domain/` (survey §4): the leaks are names and branches, not types. |

Two facts shape everything below. First, the runtime router is already deep: nine operations behind
one protocol, a registry, declared matrices and a conformance suite keyed to those matrices
(`tests/conformance/lanes/README.md`). Second, the **Effective Run Configuration is not the effective
configuration of the agent**: lowering pins capability refs only; which model, tools, skills and
children an agent gets is decided at start by `ManifestLaunchResolver` from a deployment file
(survey 3, §2). The seam this design adds sits exactly there.

## 2. Decision: the adaptation mechanism

**Chosen: ports and adapters for behavior, declarations as data for what varies, registries as the only
place a variant is named, and one resolver that composes them.** Each pattern has one job:

| Pattern | Where it applies | Why here and nowhere else |
| --- | --- | --- |
| Port and adapter | One **Lane Adapter** per provider (compile translation plus runtime harness in one package); one **Knowledge Backend** per application on the KS side; the existing MC `KnowledgeBindingClient` as the MC side of the storage port | Behavior that truly differs: how a lane materializes skills, hooks, children, middleware and model routes; how a backend commits a native effect. Code, not data. |
| Capability declaration as data | The lane **describe** (exists: `mc.lane_describe.v2`), extended with model routes and compile-time item support; the **Application Profile** (new, `deployments/<app>/application.toml`); the **Model Profile** list (moved out of per-lane sections) | What varies but does not behave: which items a lane supports and how, which binding an app uses, which vendor and window a model has. Data, validated at load, read by the resolver. |
| Registry | `LaneRegistry` (exists), `ApplicationRegistry` and `ModelCatalog` (new), each populated **only** in bootstrap composition from explicit registrations | The one place a variant is named. No entry-point discovery, no import-time side effects, no string switch elsewhere. |
| Resolver (the seam) | `resolve_runtime(selection) -> ResolvedRuntime \| ResolutionRefused` in `application/resolution/` | The single function that takes (lane, model, blueprint, app) and returns a fully resolved runtime. Callers never branch. |

**Rejected alternatives**

- *Strategy objects per concern* (a `SkillStrategy`, `McpStrategy`, `SubagentStrategy` per lane). Rejected: it multiplies small objects, scatters one lane's knowledge over five classes, and still needs a selector per concern. One lane adapter with one `compile` is deeper.
- *Capability negotiation only* (every item declares what it needs; lanes declare what they offer; a matcher decides). Rejected as the sole mechanism: it has no owner for refusal and degradation decisions and tends to produce silent "best match". It is kept as data inside the describe, read by the resolver, which owns the decision.
- *Plugin discovery through entry points.* Rejected: implicit, unauditable, and the materialization receipt could not name why a lane was registered. Bootstrap registers lanes explicitly today (`adapters/temporal/deployment_composition.py:707-734`); that stays.
- *A provider abstraction that abstracts the agent lifecycle.* Rejected already by P1-S4 ([DESIGN §3.2](../../../provider-consolidation-2026-10/providers/deep_agents/DESIGN.md)): index the lifecycle, do not abstract it. The seam resolves configuration; it does not wrap `create_deep_agent`, the Claude Code CLI or a session API.
- *Pattern stacking* (registry plus strategy plus capability plus adapter for every axis). Rejected per the owner's constraint: each axis gets exactly one of the four roles above.

## 3. Decision: model is an independent axis as data, a dependent axis at admission

**Model is declared once, independently of provider, and paired with the lane at resolution time.**

- A **Model Profile** is one row: `vendor`, `model_id`, `context_window_tokens`, `cost_per_million`
  (input, output), `supports` (structured output, tool use, images), `data_class_ceiling`. It names no
  lane. The sprint's pins (PROOFS §6) are five such rows.
- A **lane describe** declares its **model routes**: `{vendor -> native | emulated | unsupported}` and,
  per route, the mechanism it uses (Deep Agents: in-process `ChatAnthropic` / `ChatOpenAI` factories;
  `claude_agent_sdk`: the vendor it is, routes for other vendors `unsupported`; `codex`: same;
  `claude_managed`: the vendor it is).
- The resolver pairs them: `(lane, model)` resolves when the lane has a `native` or `emulated` route for
  the model's vendor; otherwise `MODEL_ROUTE_UNSUPPORTED` at resolution time, pointed at the manifest's
  `model.profile`.

**Why not a sub-axis of provider.** (1) The same model appears on four lanes (`claude-sonnet-5-5` via
Deep Agents, Claude Agent SDK, Claude Cloud, Claude Managed); declaring it per lane duplicates vendor,
window and cost, which is exactly what the example bindings file does today with four `OWNER-SELECT`
entries. (2) Evaluator independence (annex §5, OC-D185) is a statement about **vendors and credentials**,
not lanes: the judge must be a different vendor from the producer. That is only checkable if vendor is a
first-class fact of the model axis. (3) Budget accounting (OC-D189) is per model. (4) The provider-model
interaction the owner names (Deep Agents plus OpenAI differs from Deep Agents plus Anthropic in middleware
and token accounting) is real, and it lives in the **lane adapter's route table**, which is where a
provider-specific behavior belongs; the core sees only `vendor` and `route`.

**Why not fully independent.** A model id without a route is not runnable; the pairing is a resolution
fact and must be refused loudly. So: independent in declaration, dependent at admission.

**Consequence for the Deep Agents feature registry.** Rows prefixed `anthropic.` and `openai.`
(`domain/capabilities/features/anthropic.py`, `openai.py`) are model-vendor features realized by Deep
Agents middleware. They move with the lane: the Deep Agents lane package owns a `routes.py` that maps
`(vendor, feature)` to its middleware. The core keeps no vendor feature registry.

**Coordinator exposure (OC-D201).** The string a coordinator agent writes in a manifest is a model profile
name; it must resolve to a vendor and id that the chosen lane can route. So the mapping model ↔ lane is
public and queryable: `GET /v1/applications/{app}/models` and `missionctl model list|describe` return
every profile with vendor, id, window, cost and the per-lane route verdict; `lane describe` carries
`model_routes`; the `mission-control-author` skill says "choose a model profile; the lane must route its
vendor" and shows the listing command. Two vocabularies are kept apart on purpose: Mission Control's
Model Profiles seed a workflow, and the AI Engineer knowledge schema's model entities (AIDB `corpus`
model, version, offering, benchmark) are knowledge that F3 ingests. Neither reads the other. The broader
coordinator search and documentation work (how a mission-control skill agent finds workflow types, model
choices, provider specifics and commands) is noted for the coordinator surface program; it is not part
of this seam.

## 4. The single resolution seam

```text
RuntimeSelection = (lane_profile, model_profile, blueprint: family + node role, application_id,
                    items: the node's effective capability selection, requirements, lane_options[lane])
resolve_runtime(selection) -> ResolvedRuntime | ResolutionRefused
ResolvedRuntime = { agent: AgentConfiguration@2 (neutral items + model pin + sandbox + budgets),
                    lane_binding: SealedLaneBinding (opaque to callers; lane adapter output),
                    knowledge: KnowledgePortBinding (binding id, apply contract, storage class, atomicity),
                    outputs: OutputContractProfile (forms, assessment pin, application minimums),
                    transfer: TransferProfile (backend byte capability, inline/file/handle bounds),
                    receipt: MaterializationReceipt (item -> native | emulated | degraded | unsupported) }
```

The resolver does six things, in order, and nothing else:

1. **Look up** the lane in `LaneRegistry`, the application in `ApplicationRegistry`, the model in
   `ModelCatalog`. Unknown is a refusal (`LANE_UNKNOWN`, `APPLICATION_UNKNOWN`, `MODEL_UNKNOWN`).
2. **Admit the pairing** against declarations: lane qualification or the local-proof flag
   (`LANE_UNQUALIFIED`), model route (`MODEL_ROUTE_UNSUPPORTED`), data class against the lane's policy and
   the application's ceiling (`DATA_CLASS_NOT_ADMITTED`, existing rule ADR-0050 §7), blueprint family
   against the lane's declared family support (`BLUEPRINT_FAMILY_UNSUPPORTED`; today only Deep Agents
   runs under the governed `operation.execute` path and session lanes under `lane.turn`).
3. **Build the neutral agent configuration**: `AgentConfiguration@2` with one `ConfigurationItem` per
   skill, MCP server (with tool subset), tool, hook script, subagent profile, environment kit, context
   bundle, the model pin and the sandbox profile. Each item carries `required: bool` from the manifest's
   `require:` and plugin expansion, and the exact pin and digest. No lane vocabulary: the current
   `FeatureAxis` / `Mechanism` fields (`domain/capabilities/features/configuration.py`) are Deep Agents
   registry concepts and do not survive into v2.
4. **Call the lane adapter**: `lane.compile(agent, lane_options) -> (SealedLaneBinding, MaterializationReceipt)`.
   The adapter translates every item into its native form, signs the receipt (PROCESS §2.2 rule 4) and
   refuses when a `required` item is `unsupported`. The resolver never inspects the binding payload.
5. **Compose the application side** from the Application Profile: `KnowledgePortBinding`,
   `OutputContractProfile`, `TransferProfile`. No code per application; data only.
6. **Seal and return.** The resolved runtime's digest covers the agent configuration, the lane binding
   digest, the application profile revision and the model pin, so a replay or a fork can verify that the
   same inputs produce the same runtime.

**Callers.** `ManifestLaunchInputAuthor.bind` calls the resolver per node and persists the templates as
today; `ManifestLaunchResolver.node/provider_node/cursor_node` are deleted. The Temporal family services
carry one `lane_binding` slot instead of three; the operation activity hands the sealed binding to
`LaneRegistry.lane_for(profile)`. The knowledge gateway reads `resolved.knowledge.apply_contract`
instead of `APPLY_CONTRACTS[binding]` and the Biotech branch. The context materializer (WI-02) reads
`resolved.transfer`. Nothing outside `adapters/<lane>/` and `bootstrap/` names a lane; nothing outside
`deployments/<app>/` and the KS binding package names an application.

**Failure policy.** Resolution-time, typed, with a JSON pointer into the manifest and the lane that
decided: `ResolutionRefused(code, pointer, lane_profile, reason, remedy)`. Degradation is allowed only
for an item the mission did not `require`, and then only as a `degraded` receipt row with a reason, which
the transcript and `lane describe` expose. There is no silent fallback and no retry with a different
lane: lane choice is the author's.

## 5. Module map

| Deep module | Interface (small) | Hidden mechanism (large) | Depth test |
| --- | --- | --- | --- |
| `application/resolution/resolver.py` | `resolve_runtime(selection)` | Registry lookups, pairing admission, neutral configuration build, lane call, application composition, digest | Interface is one function; implementation is the six steps and every refusal code. Callers see no variant. |
| `application/resolution/registries.py` | `LaneRegistry.get(profile)`, `ApplicationRegistry.get(app)`, `ModelCatalog.get(profile)` plus `register(...)` | Validation of declarations at registration, drift guards (vocabulary agreement, route coverage), caching of describes | Adding a variant is one `register` call in bootstrap. |
| `adapters/<lane>/` (one package per provider: `deep_agents`, `claude`, `codex`, `cursor`, `anthropic_managed`, `openai_agents`) | `LANE: LaneRegistration` exporting `describe`, `compile`, `harness_factory`, `conformance` | Everything provider-specific: native materialization, middleware stack, hook projection, subagent shapes, model route mechanics, usage and cost readers, bridge recovery | A caller uses `compile` and `AgentHarness` only. The Deep Agents package stays as optimized as it is (materializer, cognition points, time travel, async children) because none of that crosses the interface. |
| `deployments/<app>/application.toml` + `domain/resolution/application_profile.py` | `ApplicationProfile` (data) | Nothing; it is data. Validation is in the registry. | A second app is a file. |
| `application/knowledge/gateway.py` | unchanged public methods | Builds the native intent payload from `KnowledgePortBinding.apply_contract` and the contract's declared schema; no application branch | Adding an app adds no code here. |
| KS `packages/host/src/knowledge-operation/registry.ts` | `BackendRegistry.create(config)` | Resolves `binding` to a backend factory exported by its binding package | `config.ts` loses the enum and the if/else. |
| KS `packages/bindings/<binding>/` | `BACKEND: BackendRegistration` (`id`, `create`, `describe`) | Stores, apply port, atomicity, cancellation, delivery, native receipt lookup | `native-ports.ts` keeps only the neutral port types. |

What is **not** a module of this design: a universal "provider abstraction", a per-lane strategy
family, a new scheduler, a new verification engine, a product schema.

## 6. The two ports: exact responsibilities

### 6.1 Mission Control port (core to lane)

Two interfaces, one package per lane, both already partly in place:

- **Compile side (new, pure):** `LaneAdapter.compile(agent: AgentConfiguration@2, options: LaneOptions)
  -> (SealedLaneBinding, MaterializationReceipt)` and `LaneAdapter.project(agent, repo_view) -> HostProjection`
  for file lanes. `application/authoring/lanes/deep_agents.py` is the first `compile`; `render_host_files`'
  per-lane writers (`_cursor`, `_claude`, `_codex`, `_codex_cloud`, `_hosted_agent_api`) become each lane's
  `project`.
- **Runtime side (exists):** `AgentHarness` (nine operations) plus the optional capability protocols
  (`SessionLane`, `SteeringLane`, `CompactingLane`, `TimeTravelLane`, `OperationLane`, and the rest).
  `isinstance` on a capability protocol is the sanctioned way to ask "can this lane do X"; `lane == "codex"`
  is not.

**What crosses:** `AgentConfiguration@2`, `LaneOptions` (the lane's own discriminated container,
today `provider_options[lane]`), `SealedLaneBinding` (schema id, digest, bytes the lane alone reads),
`MaterializationReceipt`, and at runtime the `HarnessRequest` / `LaneFrame` envelopes
(`domain/execution/lanes.py:532-705`). **What never crosses:** LangChain tools, Deep Agents `SubAgent`
dicts, middleware classes, `ChatOpenAI` / `ChatAnthropic`, the Claude SDK `Message`, Codex JSON-RPC types,
Cursor bridge objects, LangGraph checkpoints. The core sees opaque bytes under a digest.

**Lane-owned things that leave the core** (today's leaks, moved behind the port): the describe matrices
(`application/execution/harness/describe.py` becomes an aggregator over each lane's `describe.py`),
`codex_usage.py`, `cursor_usage.py`, `cursor_costs.py`, `cursor_bridge_recovery.py`,
`deep_agents_harness.py`, `domain/execution/cursor_costs.py`, `features/{anthropic,openai,deep_agents}.py`,
`bootstrap/cursor_bridges.py`, the lane tables in `hook_runner.py` / `signal_hook.py` (each lane's
`native_output` becomes a method of its registration), `V2_LANE_BEHAVIORS` / `LANE_BEHAVIORS` (become
`describe.families` and `describe.items`), `provider_launch.REQUIRED_PINS` (becomes `describe.pins`).

### 6.2 Knowledge storage port (Mission Control to application knowledge)

Two layers, both existing, tightened:

- **MC side:** `KnowledgeBindingClient` (`application/ports/knowledge.py:81`) speaks K01
  `ks.knowledge_operation.v2` only; that stays the rule. The gateway gains a `KnowledgePortBinding` input
  from the resolver carrying `binding_id`, `apply_contract {name, version, intent_schema_ref}`,
  `storage_class: relational | graph`, `write_atomicity`, `readback_capability`. The native payload is
  built from the contract's declared schema, not from `if contract == biotech-knowledge-apply`.
- **KS side:** `KnowledgeOperationBackend` (`ports.ts:103-123`) is already the port a new application
  implements. Three changes: (1) `binding` becomes a registry id, not a closed enum; (2) the apply port
  and the research binding move into the binding packages (`bindings/aiengineer-postgres`,
  `bindings/biotech-graph`); the host keeps only the port types; (3) nullable sub-ports
  (`research | null`, `apply | null`, `delivery | null`) are replaced by a `capabilities` declaration on
  the backend descriptor so `describe` and the conformance suite say the same thing.

**What crosses:** authenticated origin, operation envelopes, exact handles and digests, receipts, the
report package (manifest, body, ledger), use decisions as opaque plans. **What never crosses:** `pg`
pools, the Neo4j driver, Cypher, AIDB table names, BKS SDL types, MC mission identifiers as foreign keys
(ADR-0059: co-location is not a join). The Biotech binding's reuse of `PostgresResearchBinding` is
binding-to-binding reuse of a Postgres implementation for the common operational component; it is kept,
and named in the binding's descriptor as its research store implementation.

### 6.3 What adapts per application, as data

The Application Profile carries what the annex says may differ per application and must not be
weakened by authors: the knowledge binding and apply contract, the data class ceiling (ADR-0050 §7),
output contract **minimums** (required assessment pin, required review classes, consequential human
sign-off classes; annex §5), the transfer profile defaults (custody backend, inline byte ceiling), the
retention interval for hosted sessions (HL-18), and the native readback capability. MC output,
assessment and transfer code read these fields from `ResolvedRuntime`; they never read `application_id`.

## 7. How provider-specific middleware plugs in without the core knowing

The core knows two vocabularies only: `HookEvent` (`domain/capabilities/hooks.py:38`, the one event
vocabulary of ADR-0026) and `ConfigurationItem` kinds. A lane adapter owns an ordered **slot table**:
kernel slots first (stop fence, kernel hooks, compaction observation), then catalog hook scripts, then
lane feature middleware, then model-route middleware. For Deep Agents that table is the materializer stack
(`adapters/deep_agents/materializer.py:461-476`) plus `_compile` (`adapter.py:1119-1168`); it does not
change. For a file lane the "middleware" is the projected hooks file; the same slot order renders as the
order of entries in `.claude/settings.json` or `.codex/hooks.json` (ADR-0044 already puts Mission
Control's entries first). The receipt names each slot and its mechanism, which is how `lane describe`
and the transcript can say "this hook ran as middleware on Deep Agents and as a command hook on Codex"
without the core having a `Mechanism` enum of its own.

`DeepAgentMiddlewareComponent` and `middleware_refs` on the neutral contracts (`domain/execution/contracts.py:590, 1098, 1246`;
`domain/authoring/contracts.py:1977`) are the one place a Deep Agents concept sits in the core today. In
v2 they become a `ConfigurationItem(kind="middleware")` whose pin only Deep Agents can honor; every other
lane returns `unsupported`, which is a refusal if required and a degraded row otherwise.

## 8. Keeping Deep Agents optimized without letting it shape the shared interfaces

Three rules, each checkable in review:

1. **Two-lane rule.** A field enters `AgentConfiguration@2`, `ResolvedRuntime` or a port only if at least
   two registered lanes can give it a `native` or `emulated` meaning. Otherwise it lives in that lane's
   `LaneOptions` (the discriminated container, PROCESS §2.2 rule 1). State slices, async graph bindings,
   `StateBackend` versus Docker sandboxes, checkpoint lineage and cognition points are Deep Agents facts
   and stay in `provider_options.deep_agents` and `adapters/deep_agents/`.
2. **Vocabulary rule.** The core's enums are `LaneProfile`, `HookEvent`, `ConfigurationItemKind`,
   `Verdict (native | emulated | degraded | unsupported)`, `Vendor`. The current `lane: Literal["deep_agents"]`
   on `AgentConfiguration` and the `FeatureAxis` / `Mechanism` / `ModelProvider` vocabulary imported from
   the Deep Agents feature registry (`features/configuration.py:93`, `:18-30`) are the concrete violation
   this design removes.
3. **Optional capability protocols, not flags.** Where Deep Agents can do something others cannot
   (time travel, seeded forks, check-time async child admission), it implements an optional protocol
   (`TimeTravelLane`, `OperationLane`) and the core asks `isinstance`. The describe declares the cell. No
   boolean `is_deep_agents` anywhere.

The Deep Agents lane keeps its full optimization budget: the materializer, the exact component registry,
the frame recorder, the async subagent middleware and the Agent Server graphs are untouched by this
design except for the move of `application/authoring/lanes/deep_agents.py` into the package as its
`compile`.

## 9. Depth test on paper

### 9.1 Adding Claude Code (`claude_agent_sdk`) as the second provider through the seam

Today, giving the Claude lane the same compile-time treatment Deep Agents has touches shared code in
`manifest_launch_inputs.py` (`provider_node`, `_provider_model`, `stage_templates` at `:1742`),
`projections.py` (`_claude`, `:1107`), `manifest_v2_admission.py` (`V2_LANE_BEHAVIORS`),
`provider_launch.py` (`REQUIRED_PINS`, `MODEL_PROVIDER`, `ProviderLanes` with one field per profile),
`hook_runner.py` / `signal_hook.py`, `preflight.py` and `describe.py`. That is the shallowness the owner
named: nine shared files for one lane.

With the seam, the files that change are:

| File | Change |
| --- | --- |
| `adapters/claude/lane.py` (new) | `compile`: skills to `.claude/skills`, subagent profiles to `.claude/agents/*.md`, hooks to `settings.json` entries in slot order, MCP to `.mcp.json`, model route `anthropic -> native`, every other vendor `unsupported`; signs the receipt. Mostly a move of today's `_claude` writer plus `provider_node` logic. |
| `adapters/claude/describe.py` (exists) | Owns its matrix instead of re-exporting; gains `model_routes`, `families`, `items`, `pins`. |
| `adapters/claude/__init__.py` | Exports `LANE = LaneRegistration(...)`. |
| `bootstrap/composition.py` or `deployment_composition.py` | One line: `registry.register(claude.LANE)` under its existing opt-in. |
| `tests/conformance/lanes/adapters/claude.py` (exists) | Adds the compile fixtures (§10). |

Core edits: **zero**. The resolver, the registries, the gateway, the family services and the Temporal
activities do not change.

### 9.2 Adding Biotech as the second application through the seam

| File | Change |
| --- | --- |
| `deployments/biotech/application.toml` (new) | `application_id = "biotech"`, `knowledge_binding = "biotech-graph"`, `storage_class = "graph"`, `apply_contract = {name = "biotech-knowledge-apply", version = "v1"}`, `write_atomicity = "marker_plus_outbox"`, data class ceiling, output minimums, transfer defaults, retention. |
| KS `packages/bindings/biotech-graph/src/index.ts` | Exports `BACKEND` (its factory, today `createBiotechGraphPostgresBackend` in the host's `backends.ts:603-635`, moved home) and takes `createBiotechApplyPort` from `native-ports.ts:169-240`. |
| KS executor configuration | `KS_KNOWLEDGE_BINDINGS_JSON` already lists the binding; nothing new. |

MC core edits: **zero** once the gateway reads the apply contract from the profile and the manifest's
application field validates against the registry. KS host edits: **zero** once `config.ts` resolves
through the registry.

### 9.3 Where this is still at risk of being shallow (said plainly)

- **The compile seam is exercised by one real lane, by decision.** `compile` exists for Deep Agents only;
  the file lanes' writers exist but have never produced a receipt. The owner chose (OC-D199) to touch other
  providers only mechanically in this sprint and to sweep all providers afterwards, so `LaneAdapter.compile`
  is proven on one data point until that sweep. The compile conformance suite, the eight-item fixtures and
  the registration shape exist now so the sweep adds lanes without touching the core; the "zero core edits"
  claim in §9.1 is a paper proof until then, and is stated as such.
- **The blueprint axis is proven for two of four families.** Swarm and Evaluator Optimizer are not
  implemented; `describe.families` will be declared from the Stage Graph and Goal Directed paths only
  until WI-14 and WI-15 land. A family support cell nobody has exercised is `unqualified`, and the resolver
  must say so rather than admit it.
- **Hosted agent API lanes cannot take files**, so `skill_bundle`, `hook_script` and `subagent_profile`
  degrade or refuse there by design. The receipt mechanism carries it, but it means "the same suite for
  every lane" is really "the same suite, with each lane's declared exceptions", which the existing
  `DeclaredException` already formalizes. Honest, not uniform.
- **The KS backend port has nullable sub-ports** today; moving to a capability declaration is a contract
  change in a TypeScript repository the agent team must make without a Python-style conformance habit.
  The KS conformance suite in §10 is the guard.
- **The older Biotech knowledge path is gone** (OC-D202, deleted 2026-10-27 with its envelope in Knowledge
  Services); the shared `ks.knowledge_operation.v2` path is the only path. The rest of `integrations/biotech`
  (schema grounding, reference research, Neo4j adapters, Temporal activities) stays an optional domain
  package plugged in through the runtime-options factory; none of it is a knowledge port instance.

## 10. Conformance and contract test strategy

Every variant is verified by the same suites, selected by its declarations, with declared exceptions
citing proof. This mirrors the existing lane suite and extends it in three directions.

| Suite | Location | Driven by | What it proves for every registered variant |
| --- | --- | --- | --- |
| Lane compile conformance (new) | `tests/conformance/lanes/compile/` | `describe.items`, `describe.model_routes`, `describe.families` | For a canonical `AgentConfiguration@2` fixture set (eight items: skill bundle, stdio MCP with tool subset, remote MCP, inherit child, seeded child, async child, hook script on three events, environment kit; and one model pin per vendor), `compile` returns a receipt whose verdict per item equals the describe's cell (describe honesty at compile), refuses a `required` unsupported item with the right code and pointer, is pure and idempotent (same input, same digest), and never emits a native object type across the port. |
| Lane runtime conformance (exists) | `tests/conformance/lanes/` | the declared matrix | Unchanged scenarios, plus one new scenario: a session started from a `SealedLaneBinding` the compile suite produced, so compile and runtime are proven on the same bytes. |
| Resolver conformance (new) | `tests/conformance/resolution/` | the three registries as fixtures | Every refusal code is reachable and pointed; unknown lane, app or model refuse; vendor pairing honors routes; data class and family admission; digest stability across registration order; a caller cannot obtain a `ResolvedRuntime` that names a lane the registry does not know. |
| Knowledge backend conformance (new, KS) | `packages/host/test/conformance/backends/` (vitest) | `BACKEND.describe().capabilities` | Against each registered backend on its disposable store (pg17 container for both; `neo4j-test` for Biotech): describe honesty, exact report register/read, apply with receipt, lost-acknowledgment reconciliation after a real commit (RV-06 at the port), revocation before dispatch, data class refusal, no driver type in any response. |
| Application profile conformance (new) | `tests/conformance/applications/` | every `deployments/*/application.toml` | Loads, names a binding the KS descriptor advertises (checked at W0 against the live `describe`), apply contract version equals the backend's `nativeContract`, minimums are not below the annex's required classes. |
| Knowledge protocol golden (exists) | `tests/conformance/test_knowledge_protocol_golden.py` | K01 vectors | Unchanged. |

Rule, as today: a lane, backend or application that does not pass its suite, or does not declare an
exception citing repository proof, does not merge. The conformance suites are fixtures-only (no network,
no credentials, no paid call); W1 and later gates add the real runs.

## 11. Proposed directory and module layout

```text
platform/mission-control/src/mission_control/
  domain/resolution/                 # pure types: RuntimeSelection, ResolvedRuntime, AgentConfiguration@2,
                                     # ConfigurationItem, ModelProfile, ApplicationProfile, refusal codes
  application/resolution/
    ports.py                         # LaneAdapter, LaneRegistration, registry Protocols
    registries.py                    # LaneRegistry (moved from execution/harness/registry.py),
                                     # ApplicationRegistry, ModelCatalog
    resolver.py                      # resolve_runtime: the seam
  application/execution/harness/     # protocol.py, lane_turns.py, registry re-export; the provider-named
                                     # modules leave (codex_usage, cursor_usage, cursor_costs,
                                     # cursor_bridge_recovery, deep_agents_harness)
  adapters/deep_agents/              # + lane.py (moved from application/authoring/lanes/deep_agents.py),
                                     # + routes.py (vendor features), describe.py owns its matrix
  adapters/claude/   adapters/codex/   adapters/cursor/
  adapters/anthropic_managed/   adapters/openai_agents/
                                     # each: lane.py (compile), describe.py (owner), harness.py, __init__ LANE
  bootstrap/composition.py           # registers lanes, applications (from deployments/*/application.toml)
                                     # and model profiles; the only place variants are named
platform/mission-control/deployments/<app>/
  target.toml                        # unchanged: installation identity
  application.toml                   # new: the Application Profile (data)
  models.toml                        # new: Model Profiles for this installation (vendor, id, window, cost)
platform/knowledge-services/packages/
  host/src/knowledge-operation/
    ports.ts                         # KnowledgeOperationBackend with `capabilities`; no app code
    registry.ts                      # BackendRegistry; config.ts resolves through it
  bindings/aiengineer-postgres/src/  # + backend.ts exporting BACKEND; ingestion apply port moves here
  bindings/biotech-graph/src/        # + backend.ts exporting BACKEND; biotech apply port moves here
  host/test/conformance/backends/    # the backend suite
```

Deleted, not shimmed, when the move lands: `application/authoring/lanes/`, the three per-lane resolvers in
`manifest_launch_inputs.py`, the lane switch in `render_host_files`, `V2_LANE_BEHAVIORS` / `LANE_BEHAVIORS`,
`settings.knowledge_binding_ids`, `settings.anthropic_model` / `openai_model`, `gateway.APPLY_CONTRACTS`,
the manifest `Literal["biotech","ai-engineer"]`, and the KS binding enum plus if/else.

## 12. Sprint breakdown along module boundaries

Interfaces freeze first so agents work in parallel without redesigning seams. All of this is deterministic
work: USD 0 of the sprint budget. It precedes WI-02 (the materializer consumes `ResolvedRuntime.transfer`),
WI-03 (application minimums), WI-23 (async child bindings come out of `compile`) and WI-24 (W0 installs
`application.toml` and checks it against the live KS describe). WI-01 (OVE-163) is independent and can
start the same day.

| Item | Owner | Scope and frozen interface | Verification | Blocks |
| --- | --- | --- | --- | --- |
| R0 Freeze | integrator | `domain/resolution/` types, `application/resolution/ports.py`, refusal codes, the eight-item compile fixture set, the KS `BackendRegistration` type and `capabilities` shape. No behavior change. One session. | Type checks; fixtures load; a stub lane and a stub backend pass the empty suites. | R1–R6 |
| R1 Resolver and registries | integrator | `resolver.py`, `registries.py`, `LaneRegistry` move, bootstrap registration of the six lane packages, Deep Agents `lane.py` move with no behavior change (its 956 lines and tests move as one). | Resolver conformance; existing Deep Agents launch tests unchanged; `make check`. | R2, R3 |
| R2 One lane binding slot | helper A | `OperationExecutionRequest.lane_binding: SealedLaneBinding` replaces the three slots; family services and the operation activity rebind through it; `_verify_lane_pairing` becomes a registry check. Direct cutover; histories disposable (SV-D11). | Temporal replay histories regenerated; integration tests on real Temporal; the three binding-slot grep hits are gone. | WI-02, WI-04 |
| R3 Mechanical relocation of the other lanes; compile conformance for Deep Agents (rescoped by OC-D199) | helper B | Each existing lane package owns its describe matrix, exports a `LaneRegistration` and registers with a describe-only compile and declared exceptions; the per-lane writers in `render_host_files` and `hook_runner` / `signal_hook` move into their packages unchanged; the provider-named harness modules leave shared code. No new behavior for any non-Deep-Agents lane; their full `compile` adapters belong to the post-sprint provider sweep. | Lane compile conformance passes for `deep_agents`; the other lanes register `DescribeOnlyConformance` with declared exceptions; runtime suite unchanged; `render_host_files` deleted. | W5 (C01) |
| R4 Application Profile | helper C | `application.toml` for both apps; `ApplicationRegistry`; manifest `application: str` validated by registry; gateway builds the native payload from the profile's contract; `knowledge_binding_ids` and `APPLY_CONTRACTS` deleted. | Application profile conformance; gateway unit and Postgres tests; the kernel leak list in survey §1 is empty except settings defaults, which move to the profiles. | WI-03, WI-24 |
| R5 KS backend registry | helper D (TypeScript) | `registry.ts`; `BACKEND` exports in both binding packages; apply ports and research bindings move home; `capabilities` replaces nullable sub-ports; the backend conformance suite on `sprint-v-pg17` and `neo4j-test`. | `corepack pnpm verify`; the suite passes for `aiengineer-postgres`, `biotech-graph`, `in-memory`; the host imports no binding package statically. | WI-03, WI-05 |
| R6 Model Catalog, routes and the coordinator-facing listing | helper E | `models.toml` with the PROOFS §6 pins; `ModelCatalog`; `model_routes` on every describe; Deep Agents `routes.py` absorbs `features/anthropic.py` and `openai.py`; `settings.anthropic_model` / `openai_model` deleted; the async technical child's model comes from the catalog, not an environment variable; `GET /v1/applications/{app}/models`, `missionctl model list|describe` and the author-skill guidance (§3, OC-D201). | Resolver conformance (vendor pairing); Deep Agents materializer tests; HTTP and CLI listing tests; one bounded availability probe per pin at W0 (the USD 1 of W0). | W1 |
| R7 Review and docs | reviewer (different agent) | Clean-code and spec review of R1–R6 against this document; OKF concepts `lanes-and-harness`, `capabilities`, `agent-configuration`, `knowledge-services` updated; glossary terms `Resolution Seam`, `Application Profile`, `Model Profile`; `check_docs.py`. | Review findings fixed and rerun. | WI-24 |

Parallelism: after R0, R1 and R5 start together (different repositories); R2, R3, R4, R6 start when R1's
registry interfaces merge (they are frozen in R0, so the helpers can write against them from day one and
integrate when R1 lands). Expected wall time: two integrator sessions. Tracker (OC-D198): [OVE-194](https://linear.app/overtonbell/issue/OVE-194) (parent); R0 [OVE-195](https://linear.app/overtonbell/issue/OVE-195), R1 [OVE-196](https://linear.app/overtonbell/issue/OVE-196), R2 [OVE-197](https://linear.app/overtonbell/issue/OVE-197), R3 [OVE-202](https://linear.app/overtonbell/issue/OVE-202), R4 [OVE-198](https://linear.app/overtonbell/issue/OVE-198), R5 [OVE-199](https://linear.app/overtonbell/issue/OVE-199), R6 [OVE-200](https://linear.app/overtonbell/issue/OVE-200), R7 [OVE-201](https://linear.app/overtonbell/issue/OVE-201). Native blockers: R2 blocks
OVE-164 and OVE-166; R4 blocks OVE-165 and OVE-168; R5 blocks OVE-165 and OVE-167; R6 blocks OVE-169; R3
blocks OVE-186; R7 blocks OVE-168; R0 blocks R1 and R5; R1 blocks R2, R3, R4 and R6; R7 is blocked by R1
to R6. The parent is related to OVE-162 and does not change the published 31-item graph.

## 13. Decision log with rejected alternatives

| # | Decision | Rejected | Why |
| --- | --- | --- | --- |
| D1 | One resolver function is the seam | A resolver class per axis; a pipeline of middlewares | Callers must not branch; one function with one result type is the smallest surface that can refuse loudly. |
| D2 | Registries are populated only in bootstrap, explicitly | Entry-point discovery; import-time registration decorators | Auditability: the receipt and `lane list` must say why a variant exists; today's explicit `compose_lane_registry` already works. |
| D3 | Model is an independent axis in data, paired at admission | Model as a sub-axis of provider; model fully independent (no pairing) | §3. |
| D4 | Lane adapter is one package owning compile, describe, harness and conformance | Compile adapters in `application/authoring/lanes/` separate from runtime adapters | A provider's knowledge in one place; adding a lane is one package and one registration line; the architecture invariant holds because the compile adapter is pure and implements an application-defined port. |
| D5 | `AgentConfiguration@2` drops the Deep Agents feature vocabulary | Keep `FeatureAxis` / `Mechanism` as the shared vocabulary | Those are one lane's realization concepts; the receipt carries mechanism per lane instead. |
| D6 | One `SealedLaneBinding` slot on the operation request | Keep the three typed slots; add a fourth per new lane | The neutral contract must not grow per lane; the lane reads its own bytes under a digest. |
| D7 | Application variation is data (`application.toml`), not code | An `ApplicationAdapter` class per app in MC | Survey §4 found no type leak, only names and branches; data removes the branches without inventing a class with one method. |
| D8 | KS binding registration is an export from the binding package | Keep the host's enum and factory switch; a plugin loader | Same auditability as D2; the host stops depending on both bindings statically. |
| D9 | Degradation only for non-required items, as receipt rows | Best-effort fallback to another lane; silent drop | PROCESS §2.2 rule 4; the author chose the lane. |
| D10 | Kits, context bundles and middleware are items with per-lane verdicts | Special-case kits as "file lanes only" in shared code | One verdict mechanism; Deep Agents returns `unsupported` for kits and `native` for middleware; the describe says so. |
| D11 | Hosted lanes and Cursor move mechanically, describe-only compile with declared exceptions | Defer them entirely; or give them full compile now | They must not block the seam, and they must not keep branches alive in shared code. |

## 14. Open questions for the owner, answered 2026-10-27

1. **Tracker placement.** A new parent issue "OC-R" with seven children blocking OVE-164/165/168/184, or
   seven more children under OVE-162? Recommendation: new parent, so the published 31-item graph stays
   intact and the seam is visibly a prerequisite.
2. **The `openai agents` axis value.** In the code base the OpenAI lane is `codex_agents`, the OpenAI
   Agents API with the Codex harness (`adapters/openai_agents/`); the application-run OpenAI Agents SDK is
   not a lane. Confirm that "openai agents" means `codex_agents`, and that no new lane is added this sprint.
3. **The one-slot cutover (R2).** It rewrites a neutral contract that Temporal histories carry. Under
   SV-D11 existing histories are disposable, so this is a direct cutover with regenerated replay fixtures.
   Confirm, or say the three slots stay for this sprint (then R2 becomes a wrapper and the leak remains).
4. **Model profiles as files, not catalog rows.** `deployments/<app>/models.toml` is the recommendation
   (data, versioned, no migration, read at bootstrap). The alternative is `model_profile` catalog rows in
   the database, searchable and digest-pinned, which costs a seed bundle and a migration. Confirm files.
5. **The older Biotech knowledge path** in `integrations/biotech` (`mc.knowledge_request.v1`, unwired by
   any committed factory). Recommendation: mark it historical in its AGENTS.md now and delete it in a later
   sprint; do not port it to the seam. Confirm.

**Answers (verbatim in [IA-10](../answer-sets/sprint-oc-start/claude-fable-5-1-2026-10-27/ANSWERS.md)):**
1 accepted (OC-D198, new parent OVE-194); 2 confirmed, and this sprint touches other providers only
mechanically with a full provider sweep after Deep Agents proves the workflows (OC-D199, R3 rescoped);
3 confirmed (OC-D200); 4 files, with the model ↔ provider mapping exposed to the coordinator and the AI
Engineer knowledge model entities kept apart (OC-D201, §3); 5 deleted the same day (OC-D202).

Everything else in this document is an engineering choice the integrator can make under the accepted
packet; none of it changes another accepted ADR, the annex, or the 31 published issues' acceptance text.
