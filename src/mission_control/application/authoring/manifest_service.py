"""Mission Manifest compile (SPEC-05 "Compile algorithm", FT-E2).

``ManifestCompileService.compile(manifest_yaml, scope)`` is deterministic and writes nothing:

1. parse and shape-validate (pointers into the YAML); 2. the file's ``application`` must equal
the authenticated scope (``APPLICATION_FORBIDDEN``); 3. plugins expand to their member pins
(provenance ``plugin:<alias>``; two versions of one capability id are ``INVALID_DEFINITION``);
4. every ``search`` resolves through Hybrid Search (``kind``, ``host_support`` of the lanes that
use the alias, ``max_results`` 5) to the top admitted hit (none: ``CAPABILITY_UNAVAILABLE``;
top two within 0.05 of the best attainable fused score: warning ``ambiguous_search``), every
``pin`` to its exact admitted row (missing or retired: ``CAPABILITY_UNAVAILABLE``; another
digest: ``CAPABILITY_DRIFT``; ``@latest``: the current row, recorded); 5. effective
environments (E1); 6. lane support per behavior, hook events per lane vocabulary (warning, or
blocker when ``fail_closed``; a ``fail_closed`` hook also needs a native event the lane can
enforce, MO-31), subagent overlays; 7. coverage (criterion evidence, ``from``,
``action_space``); 8. budgets (``oversubscribed_budget``) and the platform depth cap; 9. each
mission lowers onto the existing compiler and compiles through ``ControlPlaneService.compile``
against a dry-run overlay of the catalog, so the Compiled Program is produced and nothing is
persisted. ``ManifestProgramCompiler`` is the same lowering with ``persist=True`` for submit.

Lane behavior support is a static table here (marked for replacement): the G1 lane describe
(``mc.lane_describe.v1``) carries controls, hooks and subagents but no behavior matrix yet.

MP-02: step 1 dispatches on the document's ``manifest:`` literal. ``mission/v1`` takes the
exact v1 parser and every v1 step above unchanged; ``mission/v2`` parses the v2 model, checks
hook events on the provider lanes too, and admits every node role's ``requires`` against its
lane's declared matrix (V01, ``manifest_v2_admission``) before anything is lowered.

MO-10: a ``mission/v2`` environment's kit pins and ``config:`` references resolve through the
:class:`EnvironmentInputsPort` (offline: a catalog read and installation configuration, never a
provider). Without a composed port, a declared kit or ``value_ref`` is a pointed blocker.

HL-18: a ``mission/v2`` Data Class is admitted under the Application's policy (its Application
Binding's widening); a service composed without one admits only the defaults.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from mission_control.application.authoring.completion_support import launch_acceptance_issues
from mission_control.application.authoring.control_plane_repository import (
    DefinitionRepository,
    InMemoryDefinitionRepository,
)
from mission_control.application.authoring.manifest_v2_admission import (
    V2_LANE_BEHAVIORS,
    admit_mission,
    lane_behaviors,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.authoring.subagent_discriminator import (
    SEED_LANES_ATTRIBUTE,
    SEED_OF_ATTRIBUTE,
    discriminate_subagent,
)
from mission_control.application.authoring.subagent_support import subagent_field_support
from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.application.capabilities.capability_search_repository import (
    CapabilitySearchUnavailable,
)
from mission_control.application.capabilities.catalog import DEFAULT_PIN_MARGIN
from mission_control.application.chains.service import (
    CapabilityResolution,
    CapabilityResult,
    CompiledProgramSummary,
    DefinitionSummary,
    HookEventSupport,
    LaneSupport,
    ManifestResolution,
    ManifestValidationReport,
    MissionCapabilities,
    MissionLowering,
    PluginExpansion,
    ResolvedNode,
)
from mission_control.application.environments.requirements import readiness_requirements
from mission_control.application.execution.harness.describe import MISSION_V1_LANE_PROFILES
from mission_control.application.ports.payloads import ContentAddressedPayloadStore
from mission_control.application.prerequisites.preflight import (
    PreflightReport,
    PrerequisitePreflight,
)
from mission_control.application.prerequisites.setup import OwnerSetupService
from mission_control.application.resolution.lane_options import LaneOptionsChecks
from mission_control.application.workspaces.preferences import placement_documents
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    AliasBinding,
    AliasRef,
    ArtifactSchemaDefinition,
    AuthoringHead,
    CompilationContext,
    CompileInvocation,
    Definition,
    DefinitionKind,
    DefinitionSelector,
    EffectiveRunConfiguration,
    EnvironmentAvailability,
    ExactDefinitionRef,
    MCPToolDefinition,
    PluginDefinition,
    PublishedDefinition,
    PublishRequest,
    StageGraphBlueprint,
    SubagentProfileDefinition,
    WatcherDefinition,
)
from mission_control.domain.authoring.errors import (
    ControlPlaneError,
    DefinitionNotFound,
    ReferenceMismatch,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import (
    Behavior,
    CapabilityEntryBase,
    CapabilityKind,
    ContextEntry,
    Environment,
    Lane,
    ManifestErrorCode,
    ManifestIssue,
    ManifestRejected,
    ManifestStructure,
    MissionBlock,
    MissionManifest,
    NodeEnvironment,
    canonical_manifest_bytes,
    manifest_digest,
    resolve_environments,
    walk_program,
)
from mission_control.domain.authoring.manifest_lowering import (
    MANIFEST_RUN_CAPABILITIES,
    MANIFEST_RUNTIME_BINDING,
    LoweredMission,
    lower_mission,
    lowering_digests,
    unowned_stage_goals,
)
from mission_control.domain.authoring.manifest_v2 import (
    EnvironmentV2,
    is_v2,
    parse_manifest_yaml_versioned,
)
from mission_control.domain.authoring.mission_definition import (
    CapabilityPin,
    DefinitionCapability,
    MissionDefinition,
    manifest_to_definition,
)
from mission_control.domain.authoring.mission_environment import (
    KitRequirements,
    config_keys,
    is_secret_like_config_key,
)
from mission_control.domain.authoring.mission_watchers import compile_mission_watchers
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.hooks import HookMode, NativeHook, native_hook
from mission_control.domain.capabilities.host_support import CapabilityHostSupport, LaneProfile
from mission_control.domain.capabilities.plugins import PluginMemberRole
from mission_control.domain.composition.chain import compile_chain
from mission_control.domain.coordinator.contracts import (
    AuthorizationState,
    CapabilitySearchRequest,
)
from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY, DataClassPolicy
from mission_control.domain.programs.completion import OutputSchemaBinding
from mission_control.domain.programs.stagegraph_bounds import stagegraph_payload_problems
from mission_control.domain.programs.watchers import WatcherDescriptor, compile_watcher

MAX_RESULTS = 5
# OVE-204 slice 6: a mission resolving any of these is a knowledge mission, and compile mounts
# its application's knowledge charter skill (Application Profile `[knowledge] charter_skill`, its
# latest admitted row). `tool.knowledge-submit-output` alone does not qualify: every output
# obligation submits through it, knowledge work or not.
KNOWLEDGE_MISSION_CAPABILITIES = frozenset(
    {
        "plugin.cognition-knowledge",
        "plugin.cognition-mixed",
        "tool.knowledge-read",
        "tool.knowledge-apply",
        "tool.knowledge-report-register",
        "tool.knowledge-report-derive",
        "tool.knowledge-verify-claims",
    }
)
CHARTER_PROVENANCE = "application:charter"
# Fraction of the best attainable fused score (A8's pin margin): RRF compresses scores, so
# SPEC-05's 0.05 is applied to normalized scores and A8's 0.02 is the default.
AMBIGUITY_MARGIN = DEFAULT_PIN_MARGIN
PLATFORM_DEPTH_CAP = 8
COMPILE_ACTOR_FALLBACK = "service:mission-control-manifest"

# Manifest Capability Kind -> catalog Definition Kind (ADR-0020, ADR-0023). Assessments and
# deterministic executors are governed tool capabilities; context bundles are file bundles
# carried by skill rows.
CATALOG_KINDS: Mapping[CapabilityKind, DefinitionKind] = {
    CapabilityKind.MCP_SERVER: DefinitionKind.MCP_SERVER,
    CapabilityKind.MCP_TOOL: DefinitionKind.MCP_TOOL,
    CapabilityKind.SKILL_BUNDLE: DefinitionKind.SKILL,
    CapabilityKind.HOOK_SCRIPT: DefinitionKind.HOOK_SCRIPT,
    CapabilityKind.SUBAGENT_PROFILE: DefinitionKind.SUBAGENT_PROFILE,
    CapabilityKind.PLUGIN: DefinitionKind.PLUGIN,
    CapabilityKind.DETERMINISTIC_EXECUTOR: DefinitionKind.TOOL,
    CapabilityKind.ASSESSMENT: DefinitionKind.TOOL,
    CapabilityKind.MODEL_PROFILE: DefinitionKind.MODEL,
    CapabilityKind.SANDBOX_PROFILE: DefinitionKind.SANDBOX_PROFILE,
    CapabilityKind.CONTEXT_BUNDLE: DefinitionKind.SKILL,
    CapabilityKind.TOOL: DefinitionKind.TOOL,
}
# Three declared manifest kinds share the catalog `tool` definition kind. A search names its
# declared kind, so it admits only rows of that kind's catalog namespace (logical id prefix):
# an assessment search never ranks an executor or a host tool, and the reverse.
TOOL_NAMESPACES: Mapping[CapabilityKind, str] = {
    CapabilityKind.DETERMINISTIC_EXECUTOR: "executor.",
    CapabilityKind.ASSESSMENT: "assessment.",
    CapabilityKind.TOOL: "tool.",
}
ROLE_KINDS: Mapping[str, DefinitionKind] = {
    "skill": DefinitionKind.SKILL,
    "agent": DefinitionKind.SUBAGENT_PROFILE,
    "hook": DefinitionKind.HOOK_SCRIPT,
    "plugin": DefinitionKind.PLUGIN,
    "context": DefinitionKind.SKILL,
    "model": DefinitionKind.MODEL,
    "assessment": DefinitionKind.TOOL,
    "watcher": DefinitionKind.WATCHER,
}
HOST_FILTERED_KINDS = frozenset(
    {
        DefinitionKind.SKILL,
        DefinitionKind.MCP_SERVER,
        DefinitionKind.HOOK_SCRIPT,
        DefinitionKind.SUBAGENT_PROFILE,
        DefinitionKind.PLUGIN,
    }
)
MEMBER_ROLES: Mapping[PluginMemberRole, str] = {
    PluginMemberRole.SKILL: "skill",
    PluginMemberRole.MCP_SERVER: "capability",
    PluginMemberRole.HOOK: "hook",
    PluginMemberRole.SUBAGENT: "agent",
    PluginMemberRole.PROMPT: "capability",
    PluginMemberRole.RESOURCE: "context",
}
# `mission/v1` admits the FT-G1 profiles only (`describe.MISSION_V1_LANE_PROFILES`); each runs
# the behaviors its lane package declares (`lane_behaviors`, OC-R3). Every other profile is
# reserved there and needs `mission/v2`.
LANE_BEHAVIORS: Mapping[Lane, frozenset[Behavior]] = {
    lane: lane_behaviors(lane.value) if lane.value in MISSION_V1_LANE_PROFILES else frozenset()
    for lane in Lane
}
# Program behaviors a lane may declare but the compiler cannot lower yet (OVE-215, ADR-0068):
# Parallel Swarm becomes a Stage Graph profile (WI-14), Evaluator Optimizer runs on Goal Loop
# machinery (WI-15). Until then compile refuses them on every lane.
UNBUILT_PROGRAM_BEHAVIORS: frozenset[Behavior] = frozenset(
    {Behavior.PARALLEL_SWARM, Behavior.EVALUATOR_OPTIMIZER}
)
IMPLICIT_OUTPUTS: Mapping[Behavior, frozenset[str]] = {
    Behavior.HUMAN_GATE: frozenset({"resolution"}),
    Behavior.PROOF_GATE: frozenset({"disposition"}),
    Behavior.EVENT_WAIT: frozenset({"event"}),
}


class CatalogDefinitionsPort(Protocol):
    async def list_published_definitions(self) -> tuple[PublishedDefinition, ...]: ...

    async def get(self, ref: ExactDefinitionRef) -> PublishedDefinition: ...


class EnvironmentInputsPort(Protocol):
    """What a ``mission/v2`` environment needs resolved at compile, offline.

    ``kit_requirements`` reads an exact Environment Kit pin's ``requires`` (None: no such
    published kit); ``config_value`` reads one installation configuration value (None: unset).
    """

    async def kit_requirements(self, pin: str) -> KitRequirements | None: ...

    async def config_value(self, key: str) -> str | None: ...


@dataclass(frozen=True)
class ManifestScope:
    """The authenticated scope a compile runs under; the file never selects it."""

    request_scope: str
    actor_id: str = COMPILE_ACTOR_FALLBACK
    at: datetime | None = None

    @property
    def application_id(self) -> str:
        return parse_request_scope(self.request_scope).application_id

    @property
    def tenant_id(self) -> str:
        return str(parse_request_scope(self.request_scope).tenant_id)


@dataclass(frozen=True)
class CompiledMission:
    mission_key: str
    definition: MissionDefinition
    lowered: LoweredMission
    configuration: EffectiveRunConfiguration
    workflow_type_ref: ExactDefinitionRef


@dataclass(frozen=True)
class ManifestCompilation:
    """What ``compile`` returns: definitions, Compiled Programs, report and resolution."""

    manifest: MissionManifest | None
    manifest_yaml: str
    report: ManifestValidationReport
    resolution: ManifestResolution | None
    definitions: tuple[MissionDefinition, ...] = ()
    programs: tuple[CompiledMission, ...] = ()

    @property
    def ok(self) -> bool:
        return self.report.ok

    def program(self, mission_key: str) -> CompiledMission:
        return next(item for item in self.programs if item.mission_key == mission_key)


def _issue(
    code: ManifestErrorCode, pointer: str, message: str, reason: str | None = None
) -> ManifestIssue:
    return ManifestIssue(code=code, pointer=pointer, message=message, reason=reason)


def _hook_event_issue(
    alias: str, event: str, lane: str, native: NativeHook | None, *, fail_closed: bool
) -> tuple[bool, str, str] | None:
    """``(blocking, message, reason)`` for one manifest hook event on its lane, or ``None``
    when the event runs there as declared (``HOOK_EVENT_MAPPING``)."""

    if native is None:
        message = f"hook {alias} event {event} has no native event on lane {lane}"
        return fail_closed, message, "unsupported_on_lane"
    if not fail_closed or native.enforceable:
        return None
    cannot = "only observes" if native.mode is HookMode.OBSERVE else "has no fail-closed form for"
    message = (
        f"hook {alias} is fail_closed but lane {lane} {cannot} event {event} "
        f"({native.native_event})"
    )
    return True, message, "unenforceable_on_lane"


# ------------------------------------------------------------------------------------------
# Dry-run and persisting lowering onto ControlPlaneService.compile
# ------------------------------------------------------------------------------------------


class OverlayDefinitionRepository:
    """A ``DefinitionRepository`` that reads the base catalog and keeps its own writes.

    Lowered definitions and the compiled configuration live only in the overlay, so a
    compile produces a real Compiled Program without persisting anything.
    """

    def __init__(self, base: DefinitionRepository) -> None:
        self._base = base
        self._overlay = InMemoryDefinitionRepository()

    async def save_draft(self, *args: Any, **kwargs: Any) -> AuthoringHead:
        raise ReferenceMismatch("drafts are not part of a manifest compile")

    async def get_draft(self, kind: str, logical_id: str) -> AuthoringHead:
        return await self._base.get_draft(kind, logical_id)

    async def publish(
        self,
        definition: Definition,
        actor_id: str,
        published_at: datetime,
        expected_head_revision: int,
        expected_draft_revision: int | None = None,
    ) -> PublishedDefinition:
        del expected_head_revision, expected_draft_revision
        existing = await _existing(self._base, definition)
        if existing is not None:
            return existing
        existing = await _existing(self._overlay, definition)
        if existing is not None:
            return existing
        return await self._overlay.publish(definition, actor_id, published_at, 0)

    async def get(self, ref: ExactDefinitionRef) -> PublishedDefinition:
        try:
            return await self._overlay.get(ref)
        except DefinitionNotFound:
            return await self._base.get(ref)

    async def resolve(self, alias: AliasRef, *, selectable: bool = True) -> AliasBinding:
        return await self._base.resolve(alias, selectable=selectable)

    async def move_alias(self, *args: Any, **kwargs: Any) -> AliasBinding:
        raise ReferenceMismatch("aliases are not moved by a manifest compile")

    async def retire(self, *args: Any, **kwargs: Any) -> PublishedDefinition:
        raise ReferenceMismatch("definitions are not retired by a manifest compile")

    async def save_erc_record(self, record: dict[str, Any]) -> None:
        await self._overlay.save_erc_record(record)

    async def get_erc_record(self, digest: str) -> dict[str, Any]:
        try:
            return await self._overlay.get_erc_record(digest)
        except (DefinitionNotFound, KeyError, LookupError):
            return await self._base.get_erc_record(digest)

    async def list_projection_events(self) -> tuple[dict[str, Any], ...]:
        return ()


async def _existing(repository: Any, definition: Definition) -> PublishedDefinition | None:
    """The revision-1 row of a content-addressed lowered definition, if published."""

    ref = ExactDefinitionRef(
        kind=definition.kind,
        logical_id=definition.logical_id,
        revision=1,
        digest=sha256_digest(definition),
    )
    try:
        found: PublishedDefinition = await repository.get(ref)
    except (DefinitionNotFound, ReferenceMismatch, ControlPlaneError):
        return None
    return found


class ManifestProgramCompiler:
    """Publish a lowered mission's definitions and compile its Effective Run Configuration.

    ``persist=False`` (compile) publishes into a dry-run overlay; ``persist=True`` (submit)
    publishes into the catalog (idempotent: content-addressed rows are reused).
    """

    def __init__(
        self,
        repository: DefinitionRepository,
        extensions: ExtensionRegistry,
        payloads: ContentAddressedPayloadStore,
    ) -> None:
        self._repository = repository
        self._extensions = extensions
        self._payloads = payloads

    async def compile(
        self,
        lowered: LoweredMission,
        *,
        request_scope: str,
        actor_id: str,
        at: datetime,
        persist: bool,
        compilation_suffix: str | None = None,
    ) -> tuple[EffectiveRunConfiguration, ExactDefinitionRef]:
        repository: Any = (
            self._repository if persist else OverlayDefinitionRepository(self._repository)
        )
        control_plane = ControlPlaneService(repository, self._extensions, self._payloads)

        async def publish(definition: Definition) -> ExactDefinitionRef:
            existing = await _existing(repository, definition)
            if existing is not None:
                return existing.ref
            published = await control_plane.publish(
                PublishRequest(
                    definition=definition,
                    actor_id=actor_id,
                    published_at=at,
                    expected_head_revision=0,
                )
            )
            return published.ref

        blueprint_ref = await publish(lowered.blueprint)
        control_ref = await publish(lowered.control_profile(blueprint_ref))
        runtime_ref = await publish(lowered.runtime_profile)
        workspace_ref = await publish(lowered.workspace_template)
        evaluation_ref = await publish(lowered.evaluation_profile)
        workflow_ref = await publish(
            lowered.workflow_type(
                blueprint_ref=blueprint_ref,
                control_ref=control_ref,
                runtime_ref=runtime_ref,
                workspace_ref=workspace_ref,
                evaluation_ref=evaluation_ref,
            )
        )
        configuration = await control_plane.compile(
            CompileInvocation(
                workflow_type=DefinitionSelector(exact=workflow_ref),
                blueprint=DefinitionSelector(exact=blueprint_ref),
                control_profile=DefinitionSelector(exact=control_ref),
                runtime_profile=DefinitionSelector(exact=runtime_ref),
                workspace_template=DefinitionSelector(exact=workspace_ref),
                evaluation_profile=DefinitionSelector(exact=evaluation_ref),
                input_manifest=lowered.input_manifest,
                caller_authority=lowered.authority,
                environment=EnvironmentAvailability(
                    capabilities=MANIFEST_RUN_CAPABILITIES,
                    runtime_bindings=frozenset({MANIFEST_RUNTIME_BINDING}),
                ),
                context=CompilationContext(
                    # A persisted compile is unique per submit (the catalog keeps one ERC per
                    # compilation identity); a dry run reuses the lowering identity.
                    compilation_id=f"{lowered.base_id}.compile"
                    + (f".{compilation_suffix}" if compilation_suffix else ""),
                    compiled_at=at,
                    actor_id=actor_id,
                    authority_subject_id=actor_id,
                    authority_scope=request_scope,
                ),
            )
        )
        return configuration, workflow_ref


# ------------------------------------------------------------------------------------------
# The compile service
# ------------------------------------------------------------------------------------------


@dataclass
class _MissionState:
    pointer: str
    block: MissionBlock
    nodes: tuple[NodeEnvironment, ...]
    definition: MissionDefinition
    capabilities: list[DefinitionCapability] = field(default_factory=list)


class ManifestCompileService:
    def __init__(
        self,
        *,
        definitions: CatalogDefinitionsPort,
        search: CapabilitySearchService | None,
        programs: ManifestProgramCompiler | None = None,
        ambiguity_margin: float = AMBIGUITY_MARGIN,
        depth_cap: int = PLATFORM_DEPTH_CAP,
        catalog_scope: str | None = None,
        environment_inputs: EnvironmentInputsPort | None = None,
        data_class_policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
        placement_eligibility: Callable[[str, tuple[MissionDefinition, ...]], Awaitable[bool]]
        | None = None,
        applications: Collection[str] | None = None,
        lane_options: LaneOptionsChecks | None = None,
        charter_skills: Mapping[str, str] | None = None,
    ) -> None:
        self._definitions = definitions
        # OVE-204 slice 6: application id -> its knowledge charter skill id (the Application
        # Profiles' `[knowledge] charter_skill`). Absent (in-memory compiles): nothing is mounted.
        self._charter_skills = dict(charter_skills or {})
        # OC-R6: each registered lane's own check of its `provider_options` block (for Deep
        # Agents, its model tools); absent (in-memory compiles), the lane checks at launch.
        self._lane_options = lane_options
        # OC-R4: the installation's registered applications (`ApplicationRegistry`); a mission
        # naming another is refused at compile. Absent (in-memory compiles): not checked here,
        # the launch resolution still refuses an unknown application.
        self._applications = None if applications is None else frozenset(applications)
        self._search = search
        self._programs = programs
        self._environment_inputs = environment_inputs
        self._data_class_policy = data_class_policy
        self._margin = ambiguity_margin
        self._depth_cap = depth_cap
        # The installation catalog's search partition (`mc/<installation>/<app>/catalog`):
        # publication projects there and the public catalog search reads there, so compile
        # resolves there too. Absent (in-memory catalogs), the request scope is searched.
        self._catalog_scope = catalog_scope
        self._placement_eligibility = placement_eligibility

    def _lane_option_blockers(self, structure: ManifestStructure) -> list[ManifestIssue]:
        """Each lane's findings on its options block, at the environment that authored it."""

        if self._lane_options is None:
            return []
        found: dict[tuple[str, str], ManifestIssue] = {}
        for mission in structure.missions:
            for node in mission.nodes:
                options = node.effective_environment.provider_options or {}
                overlaid = any(
                    key.startswith("provider_options") and origin == "overlay"
                    for key, origin in node.field_provenance.items()
                )
                base = node.pointer if overlaid else mission.pointer
                for lane, payload in sorted(options.items()):
                    for relative, message in self._lane_options.check(lane, payload):
                        pointer = f"{base}/environment/provider_options/{lane}{relative}"
                        found.setdefault(
                            (pointer, message),
                            _issue(
                                ManifestErrorCode.INVALID_DEFINITION,
                                pointer,
                                message,
                                "provider_options_invalid",
                            ),
                        )
        return list(found.values())

    def configure_placement_eligibility(
        self, check: Callable[[str, tuple[MissionDefinition, ...]], Awaitable[bool]]
    ) -> None:
        self._placement_eligibility = check

    async def compile(self, manifest_yaml: str, scope: ManifestScope) -> ManifestCompilation:
        at = scope.at or datetime.now(UTC)
        try:
            # `mission/v1` takes the exact v1 parser; `mission/v2` the v2 model (MP-02).
            manifest, document = parse_manifest_yaml_versioned(manifest_yaml)
        except ManifestRejected as rejected:
            return ManifestCompilation(
                manifest=None,
                manifest_yaml=manifest_yaml,
                report=ManifestValidationReport(ok=False, blockers=rejected.issues),
                resolution=None,
            )
        if is_v2(manifest):
            try:
                alternatives = placement_documents(document)
            except ValueError as error:
                return ManifestCompilation(
                    manifest=manifest,
                    manifest_yaml=manifest_yaml,
                    resolution=None,
                    report=ManifestValidationReport(
                        ok=False,
                        blockers=(
                            _issue(
                                ManifestErrorCode.INVALID_DEFINITION,
                                "/",
                                str(error),
                                "placement_limit",
                            ),
                        ),
                    ),
                )
            if alternatives != [document]:
                for candidate in alternatives:
                    compilation = await self.compile(
                        canonical_manifest_bytes(candidate).decode("utf-8"), scope
                    )
                    if compilation.ok and self._placement_eligibility is not None:
                        if await self._placement_eligibility(
                            scope.request_scope, compilation.definitions
                        ):
                            return replace(
                                compilation,
                                manifest_yaml=manifest_yaml,
                                report=compilation.report.model_copy(
                                    update={"manifest_digest": manifest_digest(document)}
                                ),
                            )
                return ManifestCompilation(
                    manifest=manifest,
                    manifest_yaml=manifest_yaml,
                    resolution=None,
                    report=ManifestValidationReport(
                        ok=False,
                        manifest_digest=manifest_digest(document),
                        blockers=(
                            _issue(
                                ManifestErrorCode.INVALID_DEFINITION,
                                "/environment/lanes",
                                "PREREQUISITES_UNMET: no qualified candidate passed fresh "
                                "prerequisite and compile admission",
                                "placement_unavailable",
                            ),
                        ),
                    ),
                )
        structure = resolve_environments(manifest, document)
        chain = compile_chain(manifest)
        blockers: list[ManifestIssue] = [*structure.blockers, *chain.blockers]
        blockers += self._lane_option_blockers(structure)
        warnings: list[ManifestIssue] = [*structure.warnings, *chain.warnings]
        environments = {item.pointer: item for item in structure.missions}
        missions: list[_MissionState] = []
        for pointer, block in manifest.mission_blocks():
            env = environments[pointer]
            if self._applications is not None and block.application not in self._applications:
                blockers.append(
                    _issue(
                        ManifestErrorCode.APPLICATION_FORBIDDEN,
                        f"{pointer}/application",
                        f"mission application {block.application} has no Application Profile "
                        "in this installation (registered: "
                        f"{', '.join(sorted(self._applications)) or 'none'})",
                        "application_unknown",
                    )
                )
            elif block.application != scope.application_id:
                blockers.append(
                    _issue(
                        ManifestErrorCode.APPLICATION_FORBIDDEN,
                        f"{pointer}/application",
                        f"mission application {block.application} differs from the "
                        f"authenticated application {scope.application_id}",
                        "application_scope",
                    )
                )
            definition = manifest_to_definition(
                block, pointer=pointer, digest=structure.manifest_digest, environments=env
            )
            missions.append(
                _MissionState(
                    pointer=pointer,
                    block=block,
                    nodes=env.nodes,
                    definition=definition,
                    capabilities=list(definition.capabilities),
                )
            )
        if any(item.code is ManifestErrorCode.APPLICATION_FORBIDDEN for item in blockers):
            return self._finish(
                manifest,
                manifest_yaml,
                structure.manifest_digest,
                scope,
                at,
                missions,
                blockers,
                warnings,
                (),
                (),
                (),
                (),
                chain.resolution,
                (),
                (),
            )
        resolved: list[CapabilityResolution] = []
        plugins: list[PluginExpansion] = []
        for mission in missions:
            await self._resolve_mission(mission, scope, resolved, plugins, blockers, warnings)
            await self._watchers(mission, resolved, blockers, warnings)
        lane_support: list[LaneSupport] = []
        hook_events: list[HookEventSupport] = []
        v2 = is_v2(manifest)
        kits, configured = await self._environment_inputs_of(missions) if v2 else ({}, frozenset())
        for mission in missions:
            self._lanes(mission, lane_support, hook_events, blockers, warnings, v2=v2)
            self._coverage(mission, blockers, warnings)
            if v2:
                # V01: every node role's `requires` against its lane's declared matrix, and
                # its environment kit and configuration references (MO-10).
                admitted_blockers, admitted_warnings = admit_mission(
                    mission.block,
                    mission.pointer,
                    mission.nodes,
                    kits=kits,
                    config_keys=configured,
                    data_class_policy=self._data_class_policy,
                )
                blockers.extend(admitted_blockers)
                warnings.extend(admitted_warnings)
        programs: list[CompiledMission] = []
        lowerings: list[MissionLowering] = []
        resolved_definitions = [
            mission.definition.model_copy(update={"capabilities": tuple(mission.capabilities)})
            for mission in missions
        ]
        for mission, definition in zip(missions, resolved_definitions, strict=True):
            mission.definition = definition
        start_blockers: list[ManifestIssue] = []
        if not blockers:
            for mission in missions:
                output_schemas = await self._output_schemas(mission.definition)
                try:
                    lowered = lower_mission(
                        mission.definition,
                        capability_refs=self._capability_refs(mission.block.key, resolved),
                        output_schemas=output_schemas,
                    )
                except ValueError as error:
                    blockers.append(
                        _issue(
                            ManifestErrorCode.INVALID_DEFINITION,
                            f"{mission.pointer}/program",
                            f"lowering failed: {error}",
                            "lowering_failed",
                        )
                    )
                    continue
                if isinstance(lowered.blueprint, StageGraphBlueprint):
                    # OVE-171 (W1 D10): a graph whose family records would outgrow their
                    # bounds once it ran refuses here, typed, never as a decode loop later.
                    bound_problems = stagegraph_payload_problems(lowered.blueprint)
                    for problem in bound_problems:
                        blockers.append(
                            _issue(
                                ManifestErrorCode.INVALID_DEFINITION,
                                f"{mission.pointer}/program",
                                problem,
                                problem.partition(":")[0],
                            )
                        )
                    if bound_problems:
                        continue
                # Start refuses authored acceptance no runtime evaluator supports (fresh-launch
                # check, ``manifest_launch_inputs``); compile reports it with the same reason.
                start_blockers.extend(
                    launch_acceptance_issues(mission.definition, lowered.blueprint, output_schemas)
                )
                warnings.extend(lowered.warnings)
                digests = lowering_digests(lowered)
                lowerings.append(
                    MissionLowering(
                        mission_key=mission.block.key,
                        family=lowered.family,
                        lowering_version=digests["lowering_version"],
                        blueprint_digest=digests["blueprint_digest"],
                        runtime_profile_digest=digests["runtime_profile_digest"],
                        definition_digest=mission.definition.digest,
                    )
                )
                if self._programs is None:
                    continue
                try:
                    configuration, workflow_ref = await self._programs.compile(
                        lowered,
                        request_scope=scope.request_scope,
                        actor_id=scope.actor_id,
                        at=at,
                        persist=False,
                    )
                except (ControlPlaneError, ValueError) as error:
                    blockers.append(
                        _issue(
                            ManifestErrorCode.INVALID_DEFINITION,
                            f"{mission.pointer}/program",
                            f"lowering onto the compiler failed: {error}",
                            "lowering_failed",
                        )
                    )
                    continue
                programs.append(
                    CompiledMission(
                        mission_key=mission.block.key,
                        definition=mission.definition,
                        lowered=lowered,
                        configuration=configuration,
                        workflow_type_ref=workflow_ref,
                    )
                )
        return self._finish(
            manifest,
            manifest_yaml,
            structure.manifest_digest,
            scope,
            at,
            missions,
            blockers,
            warnings,
            resolved,
            plugins,
            lane_support,
            hook_events,
            chain.resolution,
            lowerings,
            programs,
            start_blockers,
        )

    async def _environment_inputs_of(
        self, missions: Sequence[_MissionState]
    ) -> tuple[dict[str, KitRequirements | None], frozenset[str]]:
        """Each distinct kit pin's requirements and the configuration keys that resolve."""

        # The mission environment too: a root node's kit switch compares against its kit.
        candidates = [
            environment
            for mission in missions
            for environment in (
                mission.block.environment,
                *(node.effective_environment for node in mission.nodes),
            )
        ]
        environments = [item for item in candidates if isinstance(item, EnvironmentV2)]
        pins = dict.fromkeys(item.kit.pin for item in environments if item.kit is not None)
        keys = config_keys(environments)
        port = self._environment_inputs
        if port is None:
            return dict.fromkeys(pins), frozenset()
        kits = {pin: await port.kit_requirements(pin) for pin in pins}
        # A secret-like key is refused on the key alone (admission): its value is never read.
        configured = [
            key
            for key in keys
            if not is_secret_like_config_key(key) and await port.config_value(key) is not None
        ]
        return kits, frozenset(configured)

    # -- report ------------------------------------------------------------------------

    @staticmethod
    def _finish(
        manifest: MissionManifest,
        manifest_yaml: str,
        digest: str,
        scope: ManifestScope,
        at: datetime,
        missions: Sequence[_MissionState],
        blockers: Sequence[ManifestIssue],
        warnings: Sequence[ManifestIssue],
        resolved: Sequence[CapabilityResolution],
        plugins: Sequence[PluginExpansion],
        lane_support: Sequence[LaneSupport],
        hook_events: Sequence[HookEventSupport],
        chain: Any,
        lowerings: Sequence[MissionLowering],
        programs: Sequence[CompiledMission],
        start_blockers: Sequence[ManifestIssue] = (),
    ) -> ManifestCompilation:
        unique_blockers = _unique(blockers)
        unique_start_blockers = _unique(start_blockers)
        unique_warnings = _unique(warnings)
        resolution = ManifestResolution(
            manifest_digest=digest,
            catalog_resolution="resolved",
            application_id=scope.application_id,
            tenant_id=scope.tenant_id,
            actor_ref=scope.actor_id,
            resolved_at=scope.at,
            capabilities=tuple(
                MissionCapabilities(
                    mission_key=mission.block.key, capabilities=tuple(mission.capabilities)
                )
                for mission in missions
            ),
            resolved=tuple(resolved),
            plugins=tuple(plugins),
            nodes=tuple(
                ResolvedNode(
                    mission_key=mission.block.key,
                    node_key=node.node_key,
                    role=node.role,
                    pointer=node.pointer,
                    lane=node.lane,
                    lane_changed_from=node.lane_changed_from,
                    effective_environment=node.effective_environment,
                    field_provenance=_with_plugin_provenance(node, plugins, mission.block.key),
                )
                for mission in missions
                for node in mission.nodes
            ),
            lane_support=tuple(lane_support),
            hook_events=tuple(hook_events),
            lowering=tuple(lowerings),
            chain=chain,
            blockers=unique_blockers,
            warnings=unique_warnings,
        )
        report = ManifestValidationReport(
            ok=not unique_blockers,
            manifest_digest=digest,
            blockers=unique_blockers,
            warnings=unique_warnings,
            start_blockers=unique_start_blockers,
            startable=not unique_blockers and not unique_start_blockers,
            definitions=tuple(
                DefinitionSummary(
                    mission_key=mission.block.key,
                    pointer=mission.pointer,
                    definition_digest=mission.definition.digest,
                    is_resolved=mission.definition.is_resolved,
                )
                for mission in missions
            ),
            programs=tuple(
                CompiledProgramSummary(
                    mission_key=item.mission_key,
                    family=item.lowered.family,
                    effective_configuration_digest=item.configuration.digest,
                    workflow_type_ref=item.workflow_type_ref,
                    blueprint_digest=item.lowered.blueprint_digest,
                    initial_goal=item.lowered.initial_goal,
                )
                for item in programs
            ),
            resolution=resolution,
            environment_readiness=tuple(
                requirement
                for mission in missions
                for requirement in readiness_requirements(mission.definition)
            ),
        )
        del at
        return ManifestCompilation(
            manifest=manifest,
            manifest_yaml=manifest_yaml,
            report=report,
            resolution=resolution,
            definitions=tuple(mission.definition for mission in missions),
            programs=tuple(programs),
        )

    async def _output_schemas(
        self, definition: MissionDefinition
    ) -> dict[str, OutputSchemaBinding]:
        """Only an explicitly named, published schema authority supplies an output schema
        (``catalog_output_schemas``)."""

        return await catalog_output_schemas(self._definitions, definition)

    @staticmethod
    def _capability_refs(
        mission_key: str, resolved: Sequence[CapabilityResolution]
    ) -> tuple[ExactDefinitionRef, ...]:
        return tuple(
            item.result.exact_ref
            for item in resolved
            if item.mission_key == mission_key and item.result is not None
        )

    # -- capability resolution ------------------------------------------------------------

    async def _resolve_mission(
        self,
        mission: _MissionState,
        scope: ManifestScope,
        resolved: list[CapabilityResolution],
        plugins: list[PluginExpansion],
        blockers: list[ManifestIssue],
        warnings: list[ManifestIssue],
    ) -> None:
        published = await self._definitions.list_published_definitions()
        by_id: dict[str, list[PublishedDefinition]] = {}
        for item in published:
            by_id.setdefault(item.ref.logical_id, []).append(item)
        final: list[DefinitionCapability] = []
        seen: dict[str, tuple[str, str]] = {}
        queue = list(mission.capabilities)
        index = 0
        knowledge = False
        charter_considered = False
        while True:
            if index == len(queue):
                # Every request is resolved: a knowledge mission now takes its application's
                # charter, through the same resolution, dedupe and conflict checks.
                charter = (
                    None
                    if charter_considered
                    else self._charter_request(mission, scope, seen, knowledge=knowledge)
                )
                charter_considered = True
                if charter is None:
                    break
                queue.append(charter)
            capability = queue[index]
            index += 1
            lanes = self._lanes_for(mission, capability)
            entry = await self._resolve_one(
                mission.block.key, capability, lanes, scope, by_id, warnings
            )
            resolved.append(entry)
            if entry.blocker is not None:
                blockers.append(entry.blocker)
                final.append(capability)
                continue
            result = entry.result
            assert result is not None
            knowledge = knowledge or result.capability_id in KNOWLEDGE_MISSION_CAPABILITIES
            prior = seen.get(result.capability_id)
            if prior is not None and prior[1] != result.digest:
                blockers.append(
                    _issue(
                        ManifestErrorCode.INVALID_DEFINITION,
                        capability.pointer,
                        f"{result.capability_id} resolves to two versions in mission "
                        f"{mission.block.key} ({prior[0]} and {result.pin})",
                        "conflicting_versions",
                    )
                )
            seen.setdefault(result.capability_id, (result.pin, result.digest))
            pin = CapabilityPin(
                capability_id=result.capability_id, version=result.version, digest=result.digest
            )
            final.append(capability.model_copy(update={"resolved": pin}))
            record = next(
                (
                    row
                    for row in by_id.get(result.capability_id, [])
                    if row.ref.digest == result.digest
                ),
                None,
            )
            if record is not None and isinstance(record.definition, PluginDefinition):
                members = record.definition.manifest.members
                plugins.append(
                    PluginExpansion(
                        mission_key=mission.block.key,
                        pointer=capability.pointer,
                        alias=capability.alias,
                        plugin_pin=result.pin,
                        members=tuple(member.pin.render() for member in members),
                    )
                )
                # A plugin seeded into a child carries the child onto its members, so the
                # launch resolver routes them to that child and not to the parent.
                inherited = {
                    key: capability.attributes[key]
                    for key in (SEED_OF_ATTRIBUTE, SEED_LANES_ATTRIBUTE)
                    if key in capability.attributes
                }
                for member_index, member in enumerate(members):
                    already = seen.get(member.pin.capability_id)
                    if already is not None and already[1] == member.pin.digest:
                        continue  # duplicate pins collapse
                    queue.append(
                        DefinitionCapability(
                            pointer=f"{capability.pointer}/members/{member_index}",
                            role=MEMBER_ROLES[member.role],
                            alias=None,
                            pin=CapabilityPin(
                                capability_id=member.pin.capability_id,
                                version=member.pin.version,
                                digest=member.pin.digest,
                            ),
                            attributes={
                                "provenance": f"plugin:{capability.alias or 'plugin'}",
                                "plugin_member_role": member.role.value,
                                "optional": member.optional,
                                **inherited,
                            },
                        )
                    )
            if (
                record is not None
                and capability.role == "agent"
                and isinstance(record.definition, SubagentProfileDefinition)
            ):
                # P1 subagents: classify the profile for every lane the node may run on and
                # queue its seeds as the child's own capability requests.
                discrimination = discriminate_subagent(
                    capability=capability,
                    profile=record.definition.profile,
                    lanes=lanes,
                    support=subagent_field_support,
                )
                blockers.extend(discrimination.blockers)
                warnings.extend(discrimination.warnings)
                # A seed is queued even when the parent pinned the same capability: it is
                # the child's own request at its own pointer, and the launch resolver routes
                # it to the child. Two different versions still fail as `conflicting_versions`.
                queue.extend(discrimination.seeds)
        mission.capabilities = final

    def _charter_request(
        self,
        mission: _MissionState,
        scope: ManifestScope,
        seen: Mapping[str, tuple[str, str]],
        *,
        knowledge: bool,
    ) -> DefinitionCapability | None:
        """The application's charter skill at ``@latest`` for a knowledge mission, unless the
        mission already resolved that skill (the author's pin wins). Its pointer is the
        mission's ``application``: an unavailable charter blocks there."""

        charter = self._charter_skills.get(scope.application_id)
        if charter is None or not knowledge or charter in seen:
            return None
        return DefinitionCapability(
            pointer=f"{mission.pointer}/application",
            role="skill",
            pin=CapabilityPin(capability_id=charter, version="latest"),
            attributes={"provenance": CHARTER_PROVENANCE},
        )

    async def _watchers(
        self,
        mission: _MissionState,
        resolved: Sequence[CapabilityResolution],
        blockers: list[ManifestIssue],
        warnings: list[ManifestIssue],
    ) -> None:
        """The mission's watcher descriptors, pinned templates included (SPEC-04 Â§5).

        A pinned entry takes its body from the resolved ``mc.watcher.v1`` row and may only
        narrow its limits; every descriptor is checked against the mission's waits, command
        grants and budget.
        """

        block, pointer = mission.block, mission.pointer
        templates: dict[int, WatcherDescriptor] = {}
        for pinned in compile_mission_watchers(block, pointer).pinned:
            result = next(
                (
                    item.result
                    for item in resolved
                    if item.mission_key == block.key and item.pointer == pinned.pointer
                ),
                None,
            )
            if result is None or result.exact_ref is None:
                continue  # resolution already reported the blocker
            row = await self._definitions.get(result.exact_ref)
            template = row.definition
            # The role `watcher` resolves watcher rows only: another kind is `pin_not_found`.
            assert isinstance(template, WatcherDefinition)
            try:
                templates[pinned.index] = compile_watcher(
                    template.spec,
                    watcher_id=pinned.declaration.id,
                    origin="catalog",
                    pointer=pinned.pointer,
                    template=result.pin,
                    overrides=pinned.declaration.limits,
                    until=pinned.declaration.until,
                )
            except ValueError as error:
                blockers.append(
                    _issue(
                        ManifestErrorCode.INVALID_DEFINITION,
                        f"{pinned.pointer}/limits",
                        str(error),
                        "widens_authority",
                    )
                )
        compiled = compile_mission_watchers(block, pointer, resolved=templates)
        blockers.extend(compiled.blockers)
        warnings.extend(compiled.warnings)
        policies = mission.definition.policies.model_copy(update={"watchers": compiled.descriptors})
        mission.definition = mission.definition.model_copy(update={"policies": policies})

    def _lanes_for(
        self, mission: _MissionState, capability: DefinitionCapability
    ) -> tuple[str, ...]:
        if capability.search is not None and capability.search.require:
            return tuple(sorted({lane.value for lane in capability.search.require}))
        seeded_lanes = capability.attributes.get(SEED_LANES_ATTRIBUTE)
        if isinstance(seeded_lanes, list) and seeded_lanes:
            return tuple(sorted(str(lane) for lane in seeded_lanes))
        lanes: set[str] = set()
        for node in mission.nodes:
            if _environment_names(node.effective_environment, capability):
                lanes.add(node.lane.value)
        if not lanes:
            lanes.add((mission.block.environment.lane or Lane.DEEP_AGENTS).value)
        return tuple(sorted(lanes))

    async def _resolve_one(
        self,
        mission_key: str,
        capability: DefinitionCapability,
        lanes: tuple[str, ...],
        scope: ManifestScope,
        by_id: Mapping[str, list[PublishedDefinition]],
        warnings: list[ManifestIssue],
    ) -> CapabilityResolution:
        kind = _kind_of(capability)
        request: dict[str, object] = {"kind": kind.value if kind is not None else None}
        if capability.search is not None:
            request["search"] = capability.search.query
            if capability.search.require:
                request["require"] = [lane.value for lane in capability.search.require]
        else:
            assert capability.pin is not None
            request["pin"] = _pin_text(capability.pin)
        base = CapabilityResolution(
            mission_key=mission_key,
            pointer=capability.pointer,
            role=capability.role,
            alias=capability.alias,
            request=request,
            lanes=lanes,
            provenance=str(capability.attributes.get("provenance"))
            if "provenance" in capability.attributes
            else None,
        )
        if capability.search is not None:
            return await self._resolve_search(base, capability, kind, lanes, scope, warnings)
        return self._resolve_pin(base, capability, kind, lanes, by_id)

    async def _resolve_search(
        self,
        base: CapabilityResolution,
        capability: DefinitionCapability,
        kind: DefinitionKind | None,
        lanes: tuple[str, ...],
        scope: ManifestScope,
        warnings: list[ManifestIssue],
    ) -> CapabilityResolution:
        assert capability.search is not None
        if self._search is None:
            return base.model_copy(
                update={
                    "blocker": _issue(
                        ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                        capability.pointer,
                        "capability search is not composed for this installation",
                        "search_unavailable",
                    )
                }
            )
        filtered = kind in HOST_FILTERED_KINDS
        try:
            response = await self._search.search(
                CapabilitySearchRequest(
                    query=capability.search.query,
                    kinds=frozenset({kind}) if kind is not None else frozenset(),
                    tenant_scope=self._catalog_scope or scope.request_scope,
                    host_profiles=(
                        frozenset(LaneProfile(lane) for lane in lanes) if filtered else frozenset()
                    ),
                    limit=MAX_RESULTS,
                )
            )
        except CapabilitySearchUnavailable as error:
            # W1 D7: a store refusal is a compile blocker naming its reason, never a 500.
            return base.model_copy(
                update={
                    "blocker": _issue(
                        ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                        capability.pointer,
                        str(error),
                        error.reason,
                    )
                }
            )
        namespace = None if capability.kind is None else TOOL_NAMESPACES.get(capability.kind)
        hits = [
            hit
            for hit in response.hits
            if hit.exact_ref is not None
            and hit.pin is not None
            and hit.authorization_state is AuthorizationState.SELECTABLE
            and (
                not filtered or set(lanes) <= {profile.value for profile in hit.supported_profiles}
            )
            and (namespace is None or hit.exact_ref.logical_id.startswith(namespace))
        ]
        candidates = tuple(str(hit.pin) for hit in hits)
        if not hits:
            return base.model_copy(
                update={
                    "candidates": candidates,
                    "blocker": _issue(
                        ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                        capability.pointer,
                        f"search {capability.search.query!r} ({kind.value if kind else 'any'}) "
                        f"has no admitted hit on lanes {list(lanes)}",
                        "search_no_admitted_hits",
                    ),
                }
            )
        best = self._search.max_fused_score(response.search_mode) or 1.0
        if len(hits) > 1 and (hits[0].fused_rank - hits[1].fused_rank) / best < self._margin:
            warnings.append(
                _issue(
                    ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                    capability.pointer,
                    f"search {capability.search.query!r} is ambiguous between {hits[0].pin} "
                    f"and {hits[1].pin}; the top hit was pinned",
                    "ambiguous_search",
                )
            )
        top = hits[0]
        assert top.exact_ref is not None and top.pin is not None
        return base.model_copy(
            update={
                "candidates": candidates,
                "result": _result(top.pin, top.exact_ref, top.host_support),
            }
        )

    def _resolve_pin(
        self,
        base: CapabilityResolution,
        capability: DefinitionCapability,
        kind: DefinitionKind | None,
        lanes: tuple[str, ...],
        by_id: Mapping[str, list[PublishedDefinition]],
    ) -> CapabilityResolution:
        assert capability.pin is not None
        pin = capability.pin
        rows = [
            row for row in by_id.get(pin.capability_id, []) if kind is None or row.ref.kind == kind
        ]
        admitted = [row for row in rows if row.retired_at is None]
        if pin.version == "latest" or pin.digest is None:
            if not admitted:
                return base.model_copy(
                    update={
                        "blocker": _issue(
                            ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                            capability.pointer,
                            f"no admitted row for {pin.capability_id}@latest",
                            "pin_not_found",
                        )
                    }
                )
            row = max(admitted, key=lambda item: item.ref.revision)
        else:
            exact = [row for row in rows if row.ref.digest == pin.digest]
            if not exact:
                if rows:
                    return base.model_copy(
                        update={
                            "blocker": _issue(
                                ManifestErrorCode.CAPABILITY_DRIFT,
                                capability.pointer,
                                f"{_pin_text(pin)} does not match the admitted digest of "
                                f"{pin.capability_id} ({capability_pin(rows[-1]).render()})",
                                "digest_mismatch",
                            )
                        }
                    )
                return base.model_copy(
                    update={
                        "blocker": _issue(
                            ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                            capability.pointer,
                            f"{_pin_text(pin)} is not in the catalog",
                            "pin_not_found",
                        )
                    }
                )
            row = exact[0]
            if row.retired_at is not None:
                return base.model_copy(
                    update={
                        "blocker": _issue(
                            ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                            capability.pointer,
                            f"{_pin_text(pin)} was retired",
                            "pin_revoked",
                        )
                    }
                )
            if capability_pin(row).version != pin.version:
                return base.model_copy(
                    update={
                        "blocker": _issue(
                            ManifestErrorCode.CAPABILITY_DRIFT,
                            capability.pointer,
                            f"{_pin_text(pin)} names version {pin.version}; the row with that "
                            f"digest is {capability_pin(row).render()}",
                            "version_mismatch",
                        )
                    }
                )
        rendered = capability_pin(row)
        support = getattr(row.definition, "host_support", None)
        support = support if isinstance(support, CapabilityHostSupport) else None
        if support is not None and row.ref.kind in HOST_FILTERED_KINDS:
            missing = [lane for lane in lanes if not support.supports(lane)]
            if missing:
                return base.model_copy(
                    update={
                        "result": _result(rendered.render(), row.ref, support),
                        "blocker": _issue(
                            ManifestErrorCode.CAPABILITY_UNAVAILABLE,
                            capability.pointer,
                            f"{rendered.render()} is not supported on lanes {missing}",
                            "pin_lane_unsupported",
                        ),
                    }
                )
        return base.model_copy(update={"result": _result(rendered.render(), row.ref, support)})

    # -- lanes, hooks, subagents --------------------------------------------------------------

    def _lanes(
        self,
        mission: _MissionState,
        lane_support: list[LaneSupport],
        hook_events: list[HookEventSupport],
        blockers: list[ManifestIssue],
        warnings: list[ManifestIssue],
        *,
        v2: bool = False,
    ) -> None:
        behaviors = V2_LANE_BEHAVIORS if v2 else LANE_BEHAVIORS
        for node in mission.nodes:
            supported = node.behavior in behaviors[node.lane]
            reason = None
            if not supported:
                reason = (
                    "lane_reserved_in_v1"
                    if not v2 and node.lane.value not in MISSION_V1_LANE_PROFILES
                    else "behavior_unsupported_on_lane"
                )
                blockers.append(
                    _issue(
                        ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                        node.pointer,
                        f"{node.behavior.value} is not supported on lane {node.lane.value}",
                        reason,
                    )
                )
            if supported and node.behavior in UNBUILT_PROGRAM_BEHAVIORS:
                # OVE-215 / ADR-0068: a lane may declare the family, but no lowering exists
                # yet; refuse instead of lowering to a one-stage Stage Graph.
                blockers.append(
                    _issue(
                        ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                        node.pointer,
                        f"{node.behavior.value} has no lowering yet (ADR-0068: WI-14/WI-15)",
                        "behavior_not_built",
                    )
                )
            lane_support.append(
                LaneSupport(
                    mission_key=mission.block.key,
                    node_key=node.node_key,
                    role=node.role,
                    behavior=node.behavior.value,
                    lane=node.lane.value,
                    supported=supported,
                    reason=reason,
                )
            )
            if not v2 and node.lane.value not in MISSION_V1_LANE_PROFILES:
                continue
            environment = node.effective_environment
            for index, hook in enumerate(environment.hooks or ()):
                for event in hook.events:
                    native = native_hook(node.lane.value, event.value)
                    hook_events.append(
                        HookEventSupport(
                            mission_key=mission.block.key,
                            node_key=node.node_key,
                            hook_alias=hook.as_,
                            event=event.value,
                            lane=node.lane.value,
                            native_event=native.native_event if native else None,
                            mode=native.mode if native else None,
                            unsupported_on_lane=native is None,
                        )
                    )
                    issue = _hook_event_issue(
                        hook.as_ or str(index),
                        event.value,
                        node.lane.value,
                        native,
                        fail_closed=hook.fail_closed,
                    )
                    if issue is not None:
                        blocking, message, reason = issue
                        (blockers if blocking else warnings).append(
                            _issue(
                                ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                                f"{node.pointer}/environment/hooks/{index}/events",
                                message,
                                reason,
                            )
                        )
            for index, agent in enumerate(environment.agents or ()):
                overlay = agent.overlay
                if (
                    node.lane is Lane.CURSOR_CLOUD
                    and overlay is not None
                    and (overlay.readonly is not None or overlay.is_background is not None)
                ):
                    warnings.append(
                        _issue(
                            ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                            f"{node.pointer}/environment/agents/{index}/overlay",
                            f"subagent {agent.as_ or index}: readonly/is_background are not "
                            f"supported inline on {node.lane.value}; projected as a file",
                            "projected_as_file",
                        )
                    )

    # -- coverage, budgets ---------------------------------------------------------------------

    def _coverage(
        self,
        mission: _MissionState,
        blockers: list[ManifestIssue],
        warnings: list[ManifestIssue],
    ) -> None:
        block = mission.block
        pointer = mission.pointer
        node_outputs: dict[str, set[str]] = {}
        node_behaviors: dict[str, Behavior] = {}
        visits = list(walk_program(block.program, f"{pointer}/program"))
        for visit in visits:
            behavior = Behavior(visit.node.behavior)
            node_behaviors[visit.node.key] = behavior
            node_outputs[visit.node.key] = {item.name for item in visit.node.outputs} | set(
                IMPLICIT_OUTPUTS.get(behavior, frozenset())
            )
        outputs = set().union(*node_outputs.values()) if node_outputs else set()
        for visit in visits:
            names = [item.name for item in visit.node.outputs]
            for name in sorted({name for name in names if names.count(name) > 1}):
                blockers.append(
                    _issue(
                        ManifestErrorCode.INVALID_DEFINITION,
                        f"{visit.pointer}/outputs",
                        f"output {name} is declared twice by {visit.node.key}",
                        "duplicate_output",
                    )
                )
        for goal_key in unowned_stage_goals(mission.definition):
            goal_index = next(
                index for index, goal in enumerate(block.goals) if goal.key == goal_key
            )
            blockers.append(
                _issue(
                    ManifestErrorCode.INVALID_DEFINITION,
                    f"{pointer}/goals/{goal_index}",
                    f"required goal {goal_key} has no owning stage: name it in a stage's "
                    "objectives or cite one of its declared outputs as criterion evidence; "
                    "the last stage never proves goals it does not serve",
                    "unowned_goal",
                )
            )
        for goal_index, goal in enumerate(block.goals):
            for criterion_index, criterion in enumerate(goal.criteria):
                for evidence_index, evidence in enumerate(criterion.evidence):
                    if "@" in evidence or evidence in outputs:
                        continue
                    blockers.append(
                        _issue(
                            ManifestErrorCode.INVALID_DEFINITION,
                            f"{pointer}/goals/{goal_index}/criteria/{criterion_index}/evidence/"
                            f"{evidence_index}",
                            f"criterion evidence {evidence} names no output of mission {block.key}",
                            "unknown_evidence",
                        )
                    )
        root_aliases = _context_aliases(block.environment) | {
            item.name for item in block.program.inputs
        }
        chain_missions: set[str] = set()
        for visit in visits:
            node = visit.node
            for index, binding in enumerate(node.inputs):
                if binding.from_ is None:
                    continue
                source, _, output = binding.from_.partition(".")
                if source in node_outputs:
                    if output in node_outputs[source]:
                        continue
                    if source == block.program.key and output in root_aliases:
                        continue  # a mission-level context alias or a root input
                elif source != block.key:
                    chain_missions.add(source)
                    continue  # a chain binding: SPEC-04 compile validates it
                blockers.append(
                    _issue(
                        ManifestErrorCode.INVALID_DEFINITION,
                        f"{visit.pointer}/inputs/{index}/from",
                        f"input from {binding.from_} names no declared output or context alias",
                        "unresolved_from",
                    )
                )
            action_space = getattr(node, "action_space", ())
            if action_space:
                environment = next(
                    (
                        item.effective_environment
                        for item in mission.nodes
                        if item.node_key == node.key and item.role == "node"
                    ),
                    block.environment,
                )
                aliases = (
                    _environment_aliases(environment)
                    | _environment_aliases(block.environment)
                    | set(node_behaviors)
                )
                for index, alias in enumerate(action_space):
                    if alias not in aliases:
                        blockers.append(
                            _issue(
                                ManifestErrorCode.INVALID_DEFINITION,
                                f"{visit.pointer}/action_space/{index}",
                                f"action_space alias {alias} names no capability, agent, "
                                "plugin or node of the mission",
                                "unresolved_action_space",
                            )
                        )
        for resolved_node in mission.nodes:
            governors = resolved_node.effective_environment.governors
            if governors is not None and governors.depth is not None:
                if governors.depth > self._depth_cap:
                    blockers.append(
                        _issue(
                            ManifestErrorCode.INVALID_DEFINITION,
                            f"{resolved_node.pointer}/environment/governors/depth",
                            f"depth {governors.depth} exceeds the platform cap {self._depth_cap}",
                            "depth_exceeds_platform_cap",
                        )
                    )
        self._budgets(mission, warnings)

    @staticmethod
    def _budgets(mission: _MissionState, warnings: list[ManifestIssue]) -> None:
        by_key = {node.node_key: node for node in mission.nodes if node.role == "node"}
        for visit in walk_program(mission.block.program, f"{mission.pointer}/program"):
            if Behavior(visit.node.behavior) is not Behavior.STAGE_GRAPH:
                continue
            parent = by_key[visit.node.key].effective_environment.budget
            members = [by_key[item.key] for item in getattr(visit.node, "nodes", ())]
            for name in ("usd", "tokens", "tool_calls"):
                limit = getattr(parent, name) if parent is not None else None
                if limit is None:
                    continue
                total = sum(
                    (
                        getattr(child.effective_environment.budget, name) or 0
                        for child in members
                        if child.effective_environment.budget is not None
                        and child.field_provenance.get(f"budget.{name}") == "overlay"
                    ),
                    start=0,
                )
                if total > limit:
                    warnings.append(
                        _issue(
                            ManifestErrorCode.INVALID_DEFINITION,
                            f"{visit.pointer}/environment/budget/{name}",
                            f"node budgets ({name} {total}) exceed the parent ({limit}); "
                            "release is governed at run time",
                            "oversubscribed_budget",
                        )
                    )


def _kind_of(capability: DefinitionCapability) -> DefinitionKind | None:
    if capability.kind is not None:
        return CATALOG_KINDS[capability.kind]
    return ROLE_KINDS.get(capability.role)


def _pin_text(pin: CapabilityPin) -> str:
    return f"{pin.capability_id}@{pin.version}" + (f"#{pin.digest}" if pin.digest else "")


def _result(
    pin: str, ref: ExactDefinitionRef, support: CapabilityHostSupport | None
) -> CapabilityResult:
    capability_id, _, rest = pin.partition("@")
    version, _, digest = rest.partition("#")
    return CapabilityResult(
        pin=pin,
        capability_id=capability_id,
        version=version,
        digest=digest or ref.digest,
        kind=ref.kind.value,
        exact_ref=ref,
        supported_profiles=tuple(profile.value for profile in support.supported_profiles())
        if support is not None
        else (),
    )


def _entries(environment: Environment) -> Iterable[CapabilityEntryBase | ContextEntry]:
    if environment.workspace is not None:
        yield from (
            item for item in environment.workspace.context or () if isinstance(item, ContextEntry)
        )
        yield from environment.workspace.skills or ()
    yield from environment.capabilities or ()
    yield from environment.agents or ()
    yield from environment.hooks or ()
    yield from environment.plugins or ()


def _environment_names(environment: Environment, capability: DefinitionCapability) -> bool:
    """Whether ``environment`` carries the capability request (by alias, or by its text)."""

    for entry in _entries(environment):
        if capability.alias is not None and entry.as_ == capability.alias:
            return True
        if capability.alias is None:
            if (
                capability.pin is not None
                and entry.pin is not None
                and entry.pin.startswith(f"{capability.pin.capability_id}@")
            ):
                return True
            if capability.search is not None and entry.search == capability.search.query:
                return True
    return False


def _environment_aliases(environment: Environment) -> set[str]:
    return {entry.as_ for entry in _entries(environment) if entry.as_ is not None}


def _context_aliases(environment: Environment) -> set[str]:
    if environment.workspace is None:
        return set()
    return {
        item.as_
        for item in environment.workspace.context or ()
        if isinstance(item, ContextEntry) and item.as_ is not None
    }


def _with_plugin_provenance(
    node: NodeEnvironment, plugins: Sequence[PluginExpansion], mission_key: str
) -> dict[str, str]:
    provenance = dict(node.field_provenance)
    aliases = {
        entry.as_ for entry in node.effective_environment.plugins or () if entry.as_ is not None
    }
    for plugin in plugins:
        if plugin.mission_key == mission_key and plugin.alias in aliases:
            for member in plugin.members:
                provenance[f"plugins.{plugin.alias}.{member.partition('@')[0]}"] = (
                    f"plugin:{plugin.alias}"
                )
    return provenance


def _unique(issues: Iterable[ManifestIssue]) -> tuple[ManifestIssue, ...]:
    seen: dict[tuple[str, str, str], ManifestIssue] = {}
    for issue in issues:
        seen.setdefault((issue.code.value, issue.pointer, issue.message), issue)
    return tuple(seen.values())


__all__ = [
    "ManifestCompilation",
    "ManifestCompileService",
    "ManifestProgramCompiler",
    "ManifestScope",
    "OverlayDefinitionRepository",
]


# ------------------------------------------------------------------------------------------
# The tenant-scoped facade the CLI (through HTTP), HTTP and MCP share
# ------------------------------------------------------------------------------------------

READ_GRANTS = frozenset({"workflow_run.read", "mission.read"})
CATALOG_GRANTS = frozenset({"catalog:read", "catalog.read"})


class ManifestPermissionDenied(PermissionError):
    code = "unauthorized"


def require_any(permissions: frozenset[str], grants: frozenset[str], what: str) -> None:
    if not permissions & grants:
        raise ManifestPermissionDenied(f"{what} requires one of {sorted(grants)}")


class ManifestLifecyclePort(Protocol):
    """Submit and start (FT-E3), composed beside compile when the installation allows them."""

    @property
    def request_scope(self) -> str: ...

    async def submit(self, request: Any) -> tuple[Any, bool]: ...

    async def start(
        self, run_id: str, actor: Any, *, family_input: dict[str, Any] | None = None
    ) -> Any: ...

    async def head_run(self, mission_id: Any) -> str | None: ...


class MissionManifestService:
    """Compile, submit and start Mission Manifests under one tenant scope."""

    def __init__(
        self,
        *,
        compiler: ManifestCompileService,
        request_scope: str,
        lifecycle: ManifestLifecyclePort | None = None,
        prerequisites: PrerequisitePreflight | None = None,
    ) -> None:
        parse_request_scope(request_scope)
        if lifecycle is not None and lifecycle.request_scope != request_scope:
            raise ValueError("submit and start must run under the compile scope")
        self._compiler = compiler
        self._scope = request_scope
        self.lifecycle = lifecycle
        self.prerequisites = prerequisites
        self.owner_setup = OwnerSetupService(prerequisites.repository) if prerequisites else None

    async def preflight(
        self, manifest_yaml: str, *, actor_id: str, permissions: frozenset[str]
    ) -> PreflightReport:
        compilation = await self.compile(manifest_yaml, actor_id=actor_id, permissions=permissions)
        if self.prerequisites is None:
            return PreflightReport(
                ready=False, blockers=("Owner prerequisite checks are not composed",)
            )
        report = await self.prerequisites.assess(self._scope, compilation.definitions)
        if not compilation.ok:
            return report.model_copy(
                update={
                    "ready": False,
                    "blockers": (
                        *report.blockers,
                        *(issue.message for issue in compilation.report.blockers),
                    ),
                }
            )
        return report

    @property
    def request_scope(self) -> str:
        return self._scope

    async def compile(
        self, manifest_yaml: str, *, actor_id: str, permissions: frozenset[str]
    ) -> ManifestCompilation:
        require_any(permissions, READ_GRANTS, "manifest compile")
        require_any(permissions, CATALOG_GRANTS, "manifest compile")
        return await self._compiler.compile(
            manifest_yaml, ManifestScope(request_scope=self._scope, actor_id=actor_id)
        )


async def catalog_output_schemas(
    definitions: Any, definition: MissionDefinition
) -> dict[str, OutputSchemaBinding]:
    """The output schemas a definition names, from their exact published catalog authority.

    This uses the existing catalog as authority. An artifact schema reference such as
    schema.s0-probe-report@1 or legacy MCP tool reference selects that exact revision;
    unknown names remain unavailable. OVE-176: a nested body's launch resolves the same map.
    """
    from mission_control.application.programs.artifact_validation import supported_schema

    requested: set[str] = set()

    def visit(node: Any) -> None:
        requested.update(
            output.schema_ref for output in node.outputs if output.schema_ref is not None
        )
        for child in node.nodes:
            visit(child)

    visit(definition.program)
    schemas: dict[str, OutputSchemaBinding] = {}
    authorities: set[str] = set()
    for row in await definitions.list_published_definitions():
        ref = f"{row.ref.logical_id}@{row.ref.revision}"
        if ref not in requested or row.retired_at is not None:
            continue
        body: dict[str, Any] | None
        if isinstance(row.definition, ArtifactSchemaDefinition):
            body = row.definition.json_schema
        elif isinstance(row.definition, MCPToolDefinition):
            body = row.definition.output_schema
        else:
            continue
        if ref in authorities:
            raise ValueError("catalog output schema reference has ambiguous authority")
        authorities.add(ref)
        if body is None or not supported_schema(body):
            continue
        if sha256_digest(row.definition) != row.ref.digest:
            raise ValueError("catalog output schema authority has an invalid digest")
        schemas[ref] = OutputSchemaBinding(
            schema_ref=ref,
            source_digest=row.ref.digest,
            schema_digest=sha256_digest(body),
            json_schema=body,
        )
    return schemas
