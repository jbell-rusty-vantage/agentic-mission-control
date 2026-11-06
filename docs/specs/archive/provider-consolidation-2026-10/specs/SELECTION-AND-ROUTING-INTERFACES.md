---
type: Interface Sketch
title: "Selection and routing: interface sketches for the resolver, the registries and the ports"
description: "Types and protocols only, no implementations: the resolver seam, the lane adapter port, the three registries, the application and model profiles, the KS backend registration, and the refusal vocabulary. Frozen in R0 before parallel work."
tags: [mission-control, knowledge-services, architecture, interfaces, resolution]
date: 2026-10-27
status: archived
archived: 2026-11-02
archived_from: sprint-oc/SELECTION-AND-ROUTING-INTERFACES.md
archived_reason: "built R0-R7; ADR-0063"
---

> **Archived 2026-11-02** (built R0-R7; ADR-0063). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Interface sketches

Companion to the [design](SELECTION-AND-ROUTING-DESIGN.md). These are the shapes R0 freezes. Field
names follow the existing contracts where one exists (`LaneProfile`, `HookEvent`, `MaterializationReceipt`,
`AgentHarness`); everything marked *new* has no counterpart today. Pydantic models are frozen and
`extra="forbid"`, as the existing contracts are; Protocols are `runtime_checkable` only where the design
says the core asks `isinstance`.

## 1. Domain: the neutral configuration (`domain/resolution/`)

```python
# domain/resolution/configuration.py  (new; replaces domain/capabilities/features/configuration.py's role)
from typing import Literal, Protocol
from pydantic import BaseModel

Verdict = Literal["native", "emulated", "degraded", "unsupported"]
Vendor = Literal["anthropic", "openai"]            # grows by data in models.toml, validated by ModelCatalog
ConfigurationItemKind = Literal[
    "skill_bundle", "mcp_server", "tool", "hook_script", "subagent_profile",
    "environment_kit", "context_bundle", "middleware", "sandbox_profile",
]

class ConfigurationItem(BaseModel):
    kind: ConfigurationItemKind
    name: str                      # the manifest alias (`as:`), unique within the node
    pin: str                       # exact Capability Pin `<id>@<version>#sha256:<digest>`
    digest: str
    required: bool                 # from manifest `require:` and plugin expansion
    config: dict                   # kind-specific neutral configuration (tool subset, hook events, child kind...)
    config_digest: str

class ModelPin(BaseModel):         # exists as domain/execution/bindings.ModelPin; gains vendor and cost
    profile: str
    vendor: Vendor
    model_id: str
    context_window_tokens: int
    cost_per_million_input: float
    cost_per_million_output: float
    settings: dict                 # temperature, reasoning effort, ... vendor-neutral names only

class AgentConfiguration(BaseModel):          # mc.agent_configuration.v2
    schema_version: Literal["mc.agent_configuration.v2"]
    lane_profile: str              # validated by LaneRegistry, never a Literal of one lane
    node_ref: str
    instructions_ref: str          # the layered instruction overlay (ADR-0044), by digest
    model: ModelPin
    items: tuple[ConfigurationItem, ...]
    budgets: dict                  # tokens, cost, wall clock, iterations: neutral names
    data_class: Literal["public", "internal", "confidential", "phi", "secret"]
    configuration_digest: str
```

```python
# domain/resolution/selection.py  (new)
class RuntimeSelection(BaseModel):
    lane_profile: str
    model_profile: str
    family: Literal["StageGraph", "GoalDirected", "ParallelSwarm", "EvaluatorOptimizer"]
    node_role: str                 # executor, verifier, evaluator, convergence, ...
    application_id: str
    agent: AgentConfiguration      # built by the compiler before resolution; items unresolved to a lane
    requirements: tuple[str, ...]  # lane feature requirements (existing `requires`)
    lane_options: dict             # the lane's discriminated container (`provider_options[lane]`), opaque here
```

```python
# domain/resolution/resolved.py  (new)
class SealedLaneBinding(BaseModel):   # opaque to every caller except the lane that produced it
    lane_profile: str
    schema: str                    # e.g. mc.deep_agent_binding.v3, mc.execution_binding.v2
    digest: str
    payload: bytes                 # canonical JSON the lane alone parses

class KnowledgePortBinding(BaseModel):
    binding_id: str
    apply_contract_name: str
    apply_contract_version: str
    intent_schema_ref: str
    storage_class: Literal["relational", "graph"]
    write_atomicity: Literal["single_transaction", "marker_plus_outbox"]
    readback_capability: Literal["native", "unsupported"]

class OutputContractProfile(BaseModel):
    assessment_pin: str            # e.g. knowledge.report.assess@1
    required_review_classes: tuple[str, ...]
    consequential_signoff_classes: tuple[str, ...]
    allowed_forms: tuple[str, ...] # the eight forms, possibly narrowed by the application

class TransferProfile(BaseModel):
    custody_backend: str
    inline_bytes_ceiling: int
    file_capable: bool             # from the lane describe
    binary_capable: bool

class ResolvedRuntime(BaseModel):
    selection_digest: str
    agent: AgentConfiguration
    lane_binding: SealedLaneBinding
    knowledge: KnowledgePortBinding
    outputs: OutputContractProfile
    transfer: TransferProfile
    receipt: "MaterializationReceipt"   # exists: domain/execution/materialization_receipt.py
    runtime_digest: str

RefusalCode = Literal[
    "LANE_UNKNOWN", "LANE_UNQUALIFIED", "APPLICATION_UNKNOWN", "MODEL_UNKNOWN",
    "MODEL_ROUTE_UNSUPPORTED", "DATA_CLASS_NOT_ADMITTED", "BLUEPRINT_FAMILY_UNSUPPORTED",
    "ITEM_UNSUPPORTED_ON_LANE", "ITEM_PIN_UNSERVED", "APPLY_CONTRACT_MISMATCH",
    "LANE_OPTIONS_INVALID",
]

class ResolutionRefused(BaseModel):
    code: RefusalCode
    pointer: str                   # JSON pointer into the manifest or options block
    lane_profile: str | None
    reason: str
    remedy: str                    # what the author or operator can change
```

## 2. Domain: declarations as data (`domain/resolution/profiles.py`, new)

```python
class ModelRoute(BaseModel):
    vendor: Vendor
    verdict: Literal["native", "emulated", "unsupported"]
    mechanism: str                 # the lane's own word: "chat_anthropic_factory", "cli_native", "session_api"

class LaneDeclaration(BaseModel):          # the describe (mc.lane_describe.v2) plus three new sections
    describe: "LaneDescribe"       # exists: domain/execution/lanes.LaneDescribe
    model_routes: tuple[ModelRoute, ...]
    items: dict[ConfigurationItemKind, Literal["native", "emulated", "unsupported"]]
    families: dict[str, Literal["native", "unqualified", "unsupported"]]
    pins: dict[str, str]           # runtime/SDK/CLI pins the lane requires (today provider_launch.REQUIRED_PINS)

class ApplicationProfile(BaseModel):       # deployments/<app>/application.toml
    application_id: str
    revision: int
    knowledge: KnowledgePortBinding
    data_class_ceiling: Literal["public", "internal", "confidential", "phi", "secret"]
    outputs: OutputContractProfile
    transfer: TransferProfile
    hosted_session_retention_days: int

class ModelProfile(BaseModel):             # deployments/<app>/models.toml rows
    profile: str                   # e.g. producer.default, judge.default, auditor.default, child.default
    vendor: Vendor
    model_id: str
    context_window_tokens: int
    cost_per_million_input: float
    cost_per_million_output: float
    supports: tuple[Literal["structured_output", "tool_use", "images"], ...]
    data_class_ceiling: Literal["public", "internal", "confidential", "phi", "secret"]
```

## 3. Application: ports and registries (`application/resolution/`)

```python
# application/resolution/ports.py  (new)
from typing import Protocol

class LaneAdapter(Protocol):
    """Pure. One per provider package. Reads the neutral configuration and its own options; never another lane's."""
    profile: str
    def compile(self, agent: AgentConfiguration, lane_options: dict) -> tuple[SealedLaneBinding, "MaterializationReceipt"]: ...
    def project(self, agent: AgentConfiguration, repo_view: "RepoView | None") -> "HostProjection | None": ...
    # project() is None for in-process lanes (Deep Agents) and hosted API lanes without a file surface.

class LaneRegistration(BaseModel):
    profile: str
    declaration: LaneDeclaration
    adapter: LaneAdapter
    harness_factory: "Callable[[LaneRuntimeDependencies], AgentHarness]"   # AgentHarness exists
    conformance: "LaneConformance | DescribeOnlyConformance"            # exists in tests/conformance/lanes/contract.py

class LaneRegistry(Protocol):
    def register(self, registration: LaneRegistration) -> None: ...     # bootstrap only; duplicate profile is an error
    def get(self, profile: str) -> LaneRegistration: ...                # KeyError -> LANE_UNKNOWN
    def profiles(self) -> tuple[str, ...]: ...
    def harness(self, profile: str) -> AgentHarness: ...                # today LaneRegistry.lane_for

class ApplicationRegistry(Protocol):
    def register(self, profile: ApplicationProfile) -> None: ...
    def get(self, application_id: str) -> ApplicationProfile: ...      # KeyError -> APPLICATION_UNKNOWN

class ModelCatalog(Protocol):
    def register(self, profile: ModelProfile) -> None: ...
    def get(self, profile: str) -> ModelProfile: ...                    # KeyError -> MODEL_UNKNOWN
```

```python
# application/resolution/resolver.py  (new)
class RuntimeResolver:
    def __init__(self, lanes: LaneRegistry, applications: ApplicationRegistry, models: ModelCatalog,
                 allow_unqualified_lanes: bool) -> None: ...
    def resolve(self, selection: RuntimeSelection) -> ResolvedRuntime | ResolutionRefused: ...
    # The only public method. Six steps in the design §4. Pure over its registries.
```

Callers and their single call each:

| Caller | Call | What it does with the result |
| --- | --- | --- |
| `ManifestLaunchInputAuthor.bind` | `resolver.resolve(selection)` per node | Persists `OperationExecutionRequest(lane_binding=resolved.lane_binding, ...)` templates |
| Family services (Stage Graph, Goal Directed, later Swarm and EO) | none at run time | Rebind `lane_binding` per attempt by digest; never read its payload |
| Operation activity | `registry.harness(resolved.agent.lane_profile)` | Hands `SealedLaneBinding` to the lane |
| Knowledge gateway | reads `resolved.knowledge` | Builds the native intent from `apply_contract_*` and the schema ref |
| Context materializer (WI-02) | reads `resolved.transfer` and `resolved.agent.model.context_window_tokens` | Seals the transfer plan within the budget |
| Output and assessment services (WI-01, WI-03) | reads `resolved.outputs` | Enforces application minimums |

### 3.1 Coordinator-facing listing (R6, OC-D201)

```python
# interfaces/http/models.py (new) and interfaces/cli (missionctl model list|describe)
class ModelListing(BaseModel):          # GET /v1/applications/{app}/models
    profile: str
    vendor: Vendor
    model_id: str
    context_window_tokens: int
    cost_per_million_input: float
    cost_per_million_output: float
    routes: dict[str, Literal["native", "emulated", "unsupported"]]   # lane profile -> verdict
```

Read-only; built from `ModelCatalog` and every `LaneDeclaration.model_routes`. `lane describe` gains the
same `model_routes` block. This is Mission Control's vocabulary for seeding a workflow and is unrelated to
the AI Engineer knowledge schema's model entities.

## 4. Operation request: one lane slot (`domain/execution/contracts.py`, changed)

```python
class OperationExecutionRequest(BaseModel):
    ...
    lane_profile: str
    lane_binding: SealedLaneBinding     # replaces deep_agent_binding | cursor_binding | provider_binding
    execution_runtime: str              # unchanged vocabulary; derived from the registry, never set by callers
```

Pairing is a registry check: `registry.get(request.lane_profile).declaration.describe.runtime ==
request.execution_runtime` and `lane_binding.lane_profile == lane_profile`. `_verify_lane_pairing`'s
three branches disappear.

## 5. Knowledge Services: backend registration (`packages/host/src/knowledge-operation/`, TypeScript)

```typescript
// ports.ts (changed): capabilities replace nullable sub-ports
export type BackendCapability =
  | "research" | "apply" | "delivery" | "native_receipt_lookup" | "revocation" | "readback";

export interface KnowledgeOperationBackend {
  readonly application: string;
  readonly binding: string;
  readonly capabilities: ReadonlySet<BackendCapability>;
  readonly pinnedSchema: PinnedSchema;
  readonly coreSchemas: CoreSchemas;
  readonly writeAtomicity: "single_transaction" | "marker_plus_outbox";
  readonly nativeCancellation: boolean;
  readonly credentials: CredentialUseStore;
  research(): ResearchServices;        // throws BackendCapabilityMissing when not declared
  effects(): EffectLedger;
  apply(): KnowledgeApplyPort;
  delivery(): DeliveryReader;
  close(): Promise<void>;
}

// registry.ts (new)
export interface BackendRegistration {
  readonly id: string;                                   // "aiengineer-postgres", "biotech-graph", "in-memory"
  describe(): BackendDescriptor;                         // what `GET /describe` returns before any store is opened
  create(config: BindingConfig, injection: HostInjection): Promise<KnowledgeOperationBackend>;
}

export class BackendRegistry {
  constructor(registrations: readonly BackendRegistration[]) {}   // composed in the executor's serve.ts only
  get(id: string): BackendRegistration;                            // throws UnknownBinding
}
```

```typescript
// packages/bindings/aiengineer-postgres/src/backend.ts (new)   export const BACKEND: BackendRegistration = { id: "aiengineer-postgres", ... }
// packages/bindings/biotech-graph/src/backend.ts (new)         export const BACKEND: BackendRegistration = { id: "biotech-graph", ... }
// packages/host/src/knowledge-operation/in-memory.ts           export const BACKEND: BackendRegistration = { id: "in-memory", ... }
```

`config.ts` keeps parsing `KS_KNOWLEDGE_BINDINGS_JSON` and resolves `binding` through the registry; the
`z.enum` and the if/else go. The host's `package.json` no longer depends on either binding package; the
executor app does, because composition belongs to the executable.

## 6. Conformance fixture shapes (tests/conformance/, new parts)

```python
# tests/conformance/lanes/compile/fixtures.py
CANONICAL_ITEMS: tuple[ConfigurationItem, ...]      # the eight items, exact pins from the test catalog
VENDOR_PINS: dict[Vendor, ModelPin]                  # one per vendor

class CompileConformance(Protocol):                  # one per lane, beside the runtime LaneAdapter in adapters/<lane>.py
    profile: str
    def adapter(self) -> LaneAdapter: ...
    def options(self) -> dict: ...                   # a valid lane_options block for the fixtures
    exceptions: tuple["DeclaredException", ...]      # exists
```

```typescript
// packages/host/test/conformance/backends/contract.ts
export interface BackendConformance {
  readonly registration: BackendRegistration;
  openDisposable(): Promise<{ config: BindingConfig; close(): Promise<void> }>;   // pg17 container, neo4j-test
  readonly exceptions: readonly DeclaredException[];
}
```

## 7. What is deliberately absent

No `ProviderStrategy`, no `ApplicationAdapter` class, no plugin loader, no `is_<lane>` booleans, no
`Mechanism` enum in the core, no per-concern strategy interfaces, no second model registry, no
cross-application fields. If an implementer needs one of these, the design's two-lane rule (§8) says
where the field goes instead.

## 8. R0 freeze record (OVE-195, 2026-10-27)

The shapes above are built as types only, with no caller and no behavior change:
`src/mission_control/domain/resolution/` (`configuration.py`, `selection.py`, `resolved.py`,
`profiles.py`), `src/mission_control/application/resolution/ports.py`, the compile fixtures and suite
under `tests/conformance/lanes/compile/`, resolver fixtures under `tests/conformance/resolution/`, the
application-profile suite under `tests/conformance/applications/`, and KS
`packages/host/src/knowledge-operation/registry.ts` with its suite under
`packages/host/src/tests/conformance/backends/`. A stub lane and the in-memory backend pass them.
Deviations from the sketches, each preserving the sketched invariant:

| Shape | Built | Reason |
| --- | --- | --- |
| `SealedLaneBinding.schema` | `schema_id`; `digest` is the raw SHA-256 of `payload` and is checked | `schema` shadows a `BaseModel` attribute |
| `LaneRegistration.conformance` | absent; conformance stays keyed by profile in `tests/conformance/lanes/` (runtime and compile registries) | runtime code never imports tests; the registry tests already refuse an unexercised profile |
| `LaneRegistration` | frozen dataclass, checks profile = declaration = adapter | it holds a callable and a Protocol object, not data |
| `LaneRuntimeDependencies` | empty Protocol owned by bootstrap | its members are composition's; R1 composes it |
| `ApplicationRegistry`, `ModelCatalog` | gain `applications()` / `profiles()` | R6's listing and bootstrap validation enumerate them |
| `ResolvedRuntime` | gains `schema_version` and `application_revision`; digest covers selection, configuration, model pin, binding ref, application side, receipt digest and revision; `create()` seals it | design §4 step 6 names the application revision as a digest input |
| `ModelPin` | v2 shape in `domain/resolution/configuration.py`; `domain/execution/bindings.ModelPin` remains until R6 retires it | no caller changes in R0 |
| `LaneDeclaration` | validates one route per vendor and the full item-kind and family sets; `families` keyed by `Family` | describe honesty needs a complete declaration |
| receipt kinds | `MaterializationKind` gains `environment_kit` and `middleware`; `RECEIPT_KIND` maps every item kind to its receipt kind | v2 item kinds had no receipt name |
| refusal | `LaneCompileRefused(ResolutionRefused)` raised by a pure `compile` | a compile returns a tuple; the resolver converts the exception |
| KS `BackendDescriptor` | `id`, `capabilities`, `storageClass`, `writeAtomicity`, `nativeCancellation`, `nativeContract`, `researchStore`; `HostInjection` carries kinds, auditor, seal, apply and env; `servedCapabilities()` reads today's nullable sub-ports | R5 replaces the sub-ports; describe honesty is testable before it does |
| KS suite location | `packages/host/src/tests/conformance/backends/` | the host package's tests live under `src/tests/` |

Any later change to these shapes is a deviation row in the conformance record (IMPLEMENTATION §8).

Post-freeze deviations (R5, OVE-199, KS `sprint-oc` @ `0978a85`): `KnowledgeOperationBackend` exposes
`capabilities` plus throwing accessors `research()`, `effects()`, `revocation()` (new, so
`native_receipt_lookup` and `revocation` declare independently), `apply()`, `delivery()`;
`BackendDescriptor.conditionalCapabilities` (AI Engineer `apply` is conditional on a host-injected apply port);
`readback` is in the vocabulary but no backend declares it; the conformance entry carries env, injection, an
apply fixture and `storeUnavailable`, and the suite is exported from `./knowledge-operation/conformance`;
`createKnowledgeOperationSurfaceFromEnv(env, injection)` requires `injection.registry`. Each preserves describe
honesty; wire and describe output are unchanged for Mission Control.

Post-freeze deviations (R1, OVE-196, MC `9147f518`): `CompileCheck.RECEIPT_ITEM_DIGESTS` split from describe
honesty (Deep Agents receipts the digests it materialized and declares an exception); neutral item config keys in
`domain/resolution/item_config.py`; launch-time `UndeclaredModelProfile` (`declared=False`) until R6.
(R4, OVE-198, MC merge after `8cc5d834`): `AgentConfiguration.data_class_source: declared | ceiling_default`
(required, in the configuration digest; schema id stays `mc.agent_configuration.v2`, no persisted v2 payload
predates it); `application.toml` carries an `[installation]` table read only by bootstrap; `intent_schema_ref`
holds Mission Control payload-layout ids (`mc.knowledge_apply_payload.*`); `ApplicationRegistry.register`
validates the application minimums; `KnowledgeGateway(knowledge=KnowledgePortBinding)`.
(R6, OVE-200, MC `sprint-oc-r6`): `ModelListing.routes` values add `unregistered` (a lane profile
of the vocabulary without a package registration in the process; no verdict is invented), and
the listing adds `supports` and `data_class_ceiling`; `GET .../models/{profile}` returns
`ModelDescription` (the row plus `lanes: [{lane_profile, verdict, mechanism}]`); `models.toml`
is `mc.model_catalog.v1` with `[[models]]` rows; `describe_only_registry` gains
`registrations=`; `domain/execution/bindings.ModelPin` stays for the provider and Cursor lanes'
sealed bindings (their `providers.<profile>.model_profiles` move with R3); R1's
`UndeclaredModelProfile` is deleted. Review follow-up: `ModelProfile` and `ModelPin` gain
`max_input_tokens` (required, at most the window; what sizes a context) and
`price_tiers: tuple[PriceTier(above_input_tokens, cost_per_million_input,
cost_per_million_output), ...]`, and the listing carries both; `MaterializationItem` gains
optional `vendor` / `model_id` (model items only, omitted from the digest when absent);
`ServedComponents.model_vendors` (pin digest -> pinned vendor, compared:
`MODEL_PIN_VENDOR_MISMATCH`); the optional lane protocol `ChecksLaneOptions` and
`ManifestCompileService(lane_options=LaneOptionsChecks)` refuse bad `model_tools` at compile.
Final round: `ServedComponents.model_vendors` became `model_identities: {digest: ServedModel(vendor,
model_id)}` with an explicit `qualification` flag; `PinnedModel` gains a required `model_id`;
`DeploymentCapabilityComponents` gains `model_identities` and `qualification`; codes
`MODEL_PIN_MODEL_MISMATCH`, `MODEL_PIN_UNDECLARED`, `MODEL_FACTORY_COLLISION` join
`MODEL_PIN_VENDOR_MISMATCH` (composition, readiness and worker errors; not `RefusalCode`s).

Post-freeze deviations (R3, OVE-202, MC `sprint-oc-r3`): a multi-profile lane package exports
`lane.py::LANES: tuple[LaneRegistration, ...]` (Cursor, Claude, Codex: two profiles each; the
hosted APIs one), listed in `bootstrap/lanes.SESSION_LANES`; each `LaneDeclaration` lives in the
package's `describe.py` beside its matrix, and `application/execution/harness/describe.py`
aggregates them as the one application module allowed to import a lane package (domain-only data,
enforced by `tests/architecture`); the non-Deep-Agents lanes register
`application/resolution/describe_only.DescribeOnlyCompile` (`mc.describe_only_node_binding.v1`);
`RuntimeResolver` gains `admit(LaneAdmission) -> ResolutionRefused | None` (steps 1 and 2 without
a model catalog row: lane, application, declared vendor route, Data Class, family; lane
qualification stays the worker's) and `domain/resolution/selection.LaneAdmission`;
`LaneDispatch.boundary_controls` (`budget_gate`, `external_cost_settlement`) carries the facts the
families branch on; the compile suite compiles on the first vendor a lane routes and keeps the
narrow stub as a `SUITE_PROBES` entry; `LaneAdapter.project` stays `None` for every lane: the
writers are `LaneHostFiles` behind `HostProjectors` over resolved rows, not over
`AgentConfiguration@2`, until the provider sweep.

Post-freeze deviations (R7 review fixes, OVE-201, MC `sprint-oc-r7`): `RuntimeSelection.requirements`
is removed (no caller set it, the resolver never read it; the manifest's `requires` stays admitted by
`domain/execution/lane_requirements.admit_requirements` outside the seam). A run-control `Contract`
walks a nested sealed-binding envelope in place of its payload only when the payload decodes and
hashes to its `digest`, and then scans the decoded bytes (`domain/resolution/sealed.verified_serialized_binding`);
any other dict of that shape is scanned as data. `describe_only_registry` moved to bootstrap:
`bootstrap/lanes.describe_only_registry(bound=..., allow_unqualified, registrations)` with
`bound_lane_profiles(...)` / `settings_bound_lanes(settings)` naming each lane's credential once;
`application/resolution/registries.describe_only_lanes(published, registrations, allow_unqualified)`
is the lane-neutral half.

### 8.1 Recorded residuals (R7 review, 2026-10-27)

Each row is a fact the R7 review found that the round does not change, with the owner of the fix.
"OVE-203" is the provider sweep; "W2" is the transfer workstream; "WI-02" is the context work in
flight beside R7, whose files R7 does not edit.

| # | Residual | Where | Why it stays | Owner |
| --- | --- | --- | --- | --- |
| S2a | `RuntimeSelection.requirements` removed rather than wired: the manifest's `requires` is not a resolver admission input | `domain/resolution/selection.py`; would be passed at `application/authoring/manifest_launch_inputs.py` (`RuntimeSelection(...)`, ~789) | wiring needs the WI-02 launch-input file; admission today is `admit_requirements` at compile and launch | OVE-203 |
| S2b | `ApplicationProfile.hosted_session_retention_days` is declared and validated but read by nothing. The interval in force is `DEFAULT_SESSION_RETENTION_POLICY` (7 days): `adapters/temporal/hosted_lane_composition.py` builds `SessionRetentionService(scheduler)` with no policy, so the Application Binding's `hosted_agent_apis.session_retention_seconds` (`ApplicationBinding.session_retention`, `application/installations/registry.py`) is unread as well. `bootstrap/composition.py:269` (`RETENTION_DAYS`, 90, from `adapters/postgres/runtime/stage3_kernel_repository.py:42`) is fork-materialization retention, not session retention. The `deployments/*/application.toml` comments now say the value is not yet consumed | `domain/resolution/profiles.py::ApplicationProfile`; `deployments/{ai-engineer,biotech}/application.toml` | choosing which of the two declared sources wins, and passing it to the hosted lane composition, is a composition decision beside WI-02's `bootstrap/composition.py` | WI-02 / OVE-203 |
| S2c | `TransferProfile.file_capable` and `binary_capable` are carried into `ResolvedRuntime.transfer` and read by nothing | `domain/resolution/resolved.py::TransferProfile` | the transfer planner that would branch on them is W2's | WI-02 / W2 |
| S2d | `LaneDeclaration.pins` has one reader, and it is outside the seam: the provider-lane launch check `application/authoring/provider_launch.required_pins` (`declared_lane(profile).pins`) for `claude_agent_sdk`, `codex` and the hosted API lanes. The resolver never reads it; the Deep Agents pins (`dict(DEEP_AGENTS_DESCRIBE.versions)`) are read by nothing; Cursor declares none and keeps its own `cursor_launch.REQUIRED_CURSOR_PINS` | `domain/resolution/profiles.py::LaneDeclaration`; `adapters/*/describe.py` | the sweep makes the declaration the one pin check per lane | OVE-203 |
| S2e | Single-lane item kinds, deliberately: `context_bundle` is `unsupported` on every lane; `tool`, `middleware` and `sandbox_profile` are `native` on Deep Agents only | `adapters/*/describe.py` (`items=`) | the two-lane rule is met only when a second lane serves them; the sweep decides per lane | OVE-203 |
| S4a | `LaneProfileName` is a closed `Literal` and the lane tables (`LANE_PROFILES`, `LANE_OF_PROFILE`, `PLACEMENT_OF_PROFILE`, `RUNTIMES_OF_LANE`) are hard-coded in the domain | `domain/execution/lanes.py:52-163` | a new lane is still one literal plus table rows | OVE-203 |
| S4b | `CursorExecutionBinding` and `CursorCloudOptions` (lane types) live in the domain | `domain/execution/lanes.py:887`, `:934` | they move with the Cursor package in the sweep | OVE-203 |
| S4c | `isinstance(..., ClaudeManagedOptions)` branches in the provider binding (max list cost, `budget_gate` boundary control) | `domain/execution/bindings.py:443`, `:455` | a lane-option check in shared code; becomes a declared boundary control | OVE-203 |
| S4d | `manifest_launch_inputs.deep_agents_node`, `provider_node` and `cursor_node` survive beside the seam; only Deep Agents nodes resolve through `RuntimeResolver.resolve`, the rest through `admit` plus their own node builders | `application/authoring/manifest_launch_inputs.py` (WI-02's file) | OC-D199: the other lanes move mechanically now, fully in the sweep | OVE-203 |
| S4e | The generic runtime template guard refuses any operation whose `lane_profile` is not `None`/`deep_agents` or whose runtime is `cursor`/`claude`/`codex` | `application/prerequisites/preflight.py:734-737` | replacing it needs a lane-declared "owner prerequisites" fact, which no declaration carries yet; not a local change | OVE-203 |
| S4f | The `carried_by` / `unseal` readers outside lane packages | `tests/architecture/test_package_boundaries.py::SEALED_BINDING_READERS_OUTSIDE_LANES` (21 modules) | each is a lane-specific read the sweep moves into its package; the list fails when one disappears | OVE-203 |
| S3 | `application/resolution/registries.describe_only_registry` (one boolean per lane) survives only for the placement caller `bootstrap/manifests.py:210`; `tests/unit/harness/test_lane_registry.py` proves it publishes what the bootstrap registry publishes | `application/resolution/registries.py` | `bootstrap/manifests.py` is WI-02's file; at merge the caller becomes `bootstrap.lanes.describe_only_registry(bound=settings_bound_lanes(settings), allow_unqualified=False)` and the residual is deleted | WI-02 merge |
| N2 | Vendor is still spelled `provider` in: `PinnedModel.provider` (capability-pin files `infra/capability-pins/*.json`, read by `adapters/temporal/deployment_composition.py:469` and `bootstrap/manifests.py:273`); `DeepAgentModelComponent.provider` (`domain/execution/contracts.py:574`); `DeepAgentsProviderOptions.model_tools` keys (`domain/authoring/provider_options.py:87`); `EnvironmentBinding.provider` (`domain/execution/bindings.py:134`, which also lists `cursor`); and two `ModelPin` classes coexist (`domain/execution/bindings.py:92`, provider and Cursor bindings; `domain/resolution/configuration.py:161`, the seam). `Vendor` (`domain/resolution/configuration.py:36`) is the only vendor vocabulary meant to remain | as listed | the `PinnedModel` rename is not contained (`bootstrap/manifests.py` is WI-02's) and the others change sealed or persisted shapes | OVE-203 |
| B1 | The v1 `AgentConfiguration`, `FeatureAxis`, `Mechanism`, `ModelProvider` and the Deep Agents feature rows remain in `domain/capabilities/features/` and are imported by `DeepAgentExecutionBinding` (`domain/execution/contracts.py:19`, fields at `:1119` and `:1284`). The design's vocabulary rule (no `Mechanism` in the core, §7 above) is therefore not met for them; ADR-0063's decision text is unchanged | `domain/capabilities/features/`; `domain/execution/contracts.py` | they move with `DeepAgentExecutionBinding` into `adapters/deep_agents/` | OVE-203 |
| S6 | The fast-track missions (`tests/fixtures/manifests/fast-track/*`, with golden resolutions) and the fixture launch bindings (`tests/unit/authoring/manifest_launch_fixture.FIXTURE_MODEL_PROFILES`) still use the fixture names `frontier.default` / `frontier.long_context`; the deployment examples and cognition profiles use catalog rows | `tests/fixtures/manifests/`, `tests/fixtures/models.py` | renaming them regenerates golden digests; test-only | OVE-203 |

### 8.2 Current facts beside design §9.3 (R7, 2026-10-27)

The design is accepted and unchanged; these are the facts its §9.3 risks stand at after R1-R6 and
the R7 review.

- **Compile seam.** Exercised by one real lane: Deep Agents (`adapters/deep_agents/compile.py`) is the
  only lane whose compile produces a lane binding and a receipt; the other eight profiles register
  `DescribeOnlyCompile` and are admitted describe-only.
- **Families.** Two of four (StageGraph, GoalDirected) are qualified, on one real lane: Deep Agents.
  The describe-only lanes declare the same two `native`, but none of them compiles through the seam
  yet. ParallelSwarm and EvaluatorOptimizer are `unqualified` on Deep Agents and `unsupported` on
  every other lane.
- **Hosted lanes.** `claude_managed` and `codex_agents` declare only `skill_bundle` and `mcp_server`
  `native` and every other item kind `unsupported`; the `skill_bundle` native-not-degraded claim is
  unexercised (no hosted materialization has produced a receipt).
- **Knowledge Services.** Capability declarations are built and conformance-tested on the KS side
  (registry, capability-declared ports, conditional `apply`); `readback` is unservable by
  construction; the check of each Application Profile against the live `knowledge.describe` is W0's
  (offline: `tests/conformance/applications/ks_backend_descriptors.json`).
- **Older Biotech path.** Gone (OC-D202, 2026-10-27).
