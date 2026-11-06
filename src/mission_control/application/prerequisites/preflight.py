"""Pre-spawn owner checks shared by CLI, HTTP, MCP and manifest launch."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.environments.requirements import (
    _role_template,
    readiness_requirements,
)
from mission_control.application.execution.run_launch import RunLaunchRejected, RunLaunchRequest
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.generators import (
    GenerationInputs,
    PrerequisiteEnvironment,
    PrerequisiteGenerationError,
    generate_owner_prerequisites,
)
from mission_control.application.prerequisites.oauth import OAuthRequirement, require_oauth
from mission_control.application.prerequisites.service import OwnerPrerequisiteRepository
from mission_control.application.workspaces.policy import admit_policy, policy_pin
from mission_control.domain.authoring.manifest import Behavior, Environment
from mission_control.domain.authoring.mission_definition import (
    DefinitionNode,
    EnvironmentSelections,
    MissionDefinition,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.environment_preparation import ReadinessRequirement
from mission_control.domain.execution.lanes import CursorExecutionBinding, CursorWorkspace
from mission_control.domain.execution.network_policy import (
    NetworkHosts,
    requires_signal_ingress,
    resolve_network_policy,
)
from mission_control.domain.prerequisites import (
    OwnerPrerequisite,
    PrerequisiteAssessment,
    PrerequisiteScope,
    assess_prerequisite,
)
from mission_control.domain.prerequisites.runtime_definition import RuntimeRequestDefinition
from mission_control.domain.programs.contracts import GoalDirectedRunInput, StageGraphRunInput

if TYPE_CHECKING:
    from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindings


class PreflightItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prerequisite: OwnerPrerequisite
    assessment: PrerequisiteAssessment


class PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["mc.preflight.v1"] = "mc.preflight.v1"
    ready: bool
    items: tuple[PreflightItem, ...] = ()
    degradations: tuple[str, ...] = ()
    readiness: tuple[ReadinessRequirement, ...] = ()
    blockers: tuple[str, ...] = ()


class PrerequisitesUnmet(RunLaunchRejected):
    code = "PREREQUISITES_UNMET"

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        super().__init__(self.code, "Complete the reported owner prerequisites before launching.")


class BoundCodexPrerequisiteIdentity:
    """Resolve the same selected profile identities before a run has sealed templates."""

    def __init__(self, bindings: ManifestLaunchBindings):
        self._bindings = bindings

    def __call__(self, node: DefinitionNode, verifier: bool) -> Mapping[str, object]:
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment
            else node.environment
        )
        selections = (
            node.verifier_selections if verifier and node.verifier_selections else node.selections
        )
        lane = self._bindings.providers.codex if self._bindings.providers else None
        if lane is None or selections is None:
            raise ValueError("Codex prerequisite identity needs its deployment and selections")
        model_selection = environment.model
        model_profile = model_selection.profile if model_selection else None
        model = lane.model_profiles.get(model_profile) if isinstance(model_profile, str) else None
        auth = lane.auth_profiles.get(selections.auth.profile) if selections.auth else None
        placement = selections.execution_environment
        host = (
            lane.host_profiles.get(placement.profile)
            if (placement and placement.kind == "local_workspace" and placement.profile)
            else None
        )
        cli = lane.pins.get("cli.codex")
        if model is None or auth is None or host is None or not cli:
            raise ValueError(
                "selected Codex model, auth, host and CLI must have exact deployment pins"
            )
        return {
            "workspace": lane.workspace.model_dump(mode="json", exclude_none=True),
            "host_profile": host.host_profile,
            "auth": auth.model_dump(mode="json", exclude_none=True),
            "cli_version": cli,
            "model_id": model.model_id,
        }


class BoundClaudePrerequisiteIdentity:
    """Selected Claude SDK host/configuration before templates have been sealed."""

    def __init__(self, bindings: ManifestLaunchBindings):
        self._bindings = bindings

    def __call__(self, node: DefinitionNode, verifier: bool) -> Mapping[str, object]:
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment
            else node.environment
        )
        selections = (
            node.verifier_selections if verifier and node.verifier_selections else node.selections
        )
        lane = self._bindings.providers.claude_agent_sdk if self._bindings.providers else None
        if lane is None or selections is None:
            raise ValueError("Claude host identity needs its deployment and selections")
        model_profile = environment.model.profile if environment.model else None
        model = lane.model_profiles.get(model_profile) if isinstance(model_profile, str) else None
        auth = lane.auth_profiles.get(selections.auth.profile) if selections.auth else None
        placement = selections.execution_environment
        host = (
            lane.host_profiles.get(placement.profile)
            if placement and placement.kind == "local_workspace" and placement.profile
            else None
        )
        cli, sdk = lane.pins.get("cli.claude_code"), lane.pins.get("sdk.claude_agent_sdk")
        if model is None or auth is None or host is None or not cli or not sdk:
            raise ValueError("selected Claude model, auth, host, SDK and CLI need exact pins")
        if auth.billing_mode != "api":
            raise ValueError("native Claude host proof supports only the selected API-key route")
        return {
            "workspace": lane.workspace.model_dump(mode="json", exclude_none=True),
            "host_profile": host.host_profile,
            "auth": auth.model_dump(mode="json", exclude_none=True),
            "cli_version": cli,
            "sdk_version": sdk,
            "host_configuration_digest": "sha256:"
            + sha256(
                json.dumps(
                    host.model_dump(mode="json", exclude_none=True),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "auth_route": "api_key",
            "model_id": model.model_id,
            "provider_options": lane.provider_options.model_dump(mode="json"),
            "agent_profile_ref": lane.agent_profile_ref.model_dump(mode="json"),
        }


def _public_digest(value: object) -> str:
    return (
        "sha256:"
        + sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


def cursor_sealed_configuration(binding: CursorExecutionBinding) -> dict[str, object]:
    """Only fields the existing Cursor binding actually seals; no auth/host assertion."""
    from mission_control.application.prerequisites.probes import NativeCursorConfiguration

    if binding.lane_profile != "cursor_local" or binding.hook_callback is None:
        raise ValueError("native Cursor C9 needs the local hook callback")
    return NativeCursorConfiguration(
        pins=binding.pins,
        model_id=binding.model_id,
        workspace=binding.workspace,
        mode=binding.mode,
        sandbox_enabled=binding.sandbox_enabled,
        disallowed_tools=binding.disallowed_tools,
        hook_callback_digest=_public_digest(binding.hook_callback.model_dump(mode="json")),
    ).model_dump(mode="json")


class BoundCursorPrerequisiteIdentity:
    """C9 selected host admission identity, alongside the existing sealed Cursor subset."""

    def __init__(self, bindings: ManifestLaunchBindings):
        self._bindings = bindings

    def __call__(self, node: DefinitionNode, verifier: bool) -> Mapping[str, object]:
        from mission_control.application.prerequisites.probes import NativeCursorConfiguration

        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment
            else node.environment
        )
        selections = (
            node.verifier_selections if verifier and node.verifier_selections else node.selections
        )
        lane = self._bindings.providers.cursor_local if self._bindings.providers else None
        if lane is None or selections is None:
            raise ValueError("Cursor C9 identity needs exact deployment and selections")
        model_profile = environment.model.profile if environment.model else None
        model = lane.model_profiles.get(model_profile) if isinstance(model_profile, str) else None
        auth = lane.auth_profiles.get(selections.auth.profile) if selections.auth else None
        placement = selections.execution_environment
        host = (
            lane.host_profiles.get(placement.profile)
            if placement and placement.kind == "local_workspace" and placement.profile
            else None
        )
        if model is None or auth is None or host is None or not lane.lease_root:
            raise ValueError(
                "selected Cursor model, auth, host and lease root need exact deployment pins"
            )
        if auth.billing_mode != "api":
            raise ValueError("native Cursor C9 supports only the selected API-key route")
        repo = environment.workspace.repo if environment.workspace else None
        repository_key = (repo.path or repo.url) if repo else None
        repository = lane.repositories.get(repository_key) if repository_key is not None else None
        if repo is None or repository is None or repository.repo_url is None:
            raise ValueError("native Cursor C9 needs an explicitly bound repository root")
        base_ref = repo.ref or repository.base_refs[0]
        if base_ref not in repository.base_refs:
            raise ValueError("native Cursor C9 repository ref is not admitted")
        configuration = NativeCursorConfiguration(
            pins=lane.pins,
            model_id=model.model_id,
            workspace=CursorWorkspace(
                repo_url=repository.repo_url,
                base_ref=base_ref,
                lease_root=lane.lease_root,
                branch_prefix=repository.branch_prefix,
                policy=admit_policy("cursor_local", policy_pin(selections.workspace_policy)),
            ),
            mode=lane.mode,
            sandbox_enabled=lane.sandbox_enabled,
            disallowed_tools=lane.disallowed_tools,
            hook_callback_digest=_public_digest(lane.hook_callback.model_dump(mode="json")),
        )
        return {
            "workspace": lane.workspace.model_dump(mode="json", exclude_none=True),
            "host_profile": host.host_profile,
            "host_configuration_digest": _public_digest(
                host.model_dump(mode="json", exclude_none=True)
            ),
            "auth": auth.model_dump(mode="json", exclude_none=True),
            "auth_route": "api_key",
            "agent_profile_ref": lane.agent_profile_ref.model_dump(mode="json"),
            "cursor_configuration": configuration.model_dump(mode="json"),
        }


class BoundLocalPrerequisiteIdentity:
    def __init__(self, bindings: ManifestLaunchBindings):
        self._codex = BoundCodexPrerequisiteIdentity(bindings)
        self._claude = BoundClaudePrerequisiteIdentity(bindings)
        self._cursor = BoundCursorPrerequisiteIdentity(bindings)

    def __call__(self, node: DefinitionNode, verifier: bool) -> Mapping[str, object]:
        environment = (
            node.verifier_environment
            if verifier and node.verifier_environment
            else node.environment
        )
        if (environment.lane or node.lane) == LaneProfile.CURSOR_LOCAL.value:
            return self._cursor(node, verifier)
        return (
            self._claude(node, verifier)
            if (environment.lane or node.lane) == LaneProfile.CLAUDE_AGENT_SDK.value
            else self._codex(node, verifier)
        )


def node_roles(node: DefinitionNode) -> Iterator[tuple[DefinitionNode, bool]]:
    if node.behavior is Behavior.STAGE_GRAPH:
        for child in node.nodes:
            yield from node_roles(child)
    else:
        yield node, False
        if node.behavior is Behavior.GOAL_LOOP:
            yield node, True


def scope_prerequisite(
    prerequisite: OwnerPrerequisite,
    environment: Environment,
    selections: EnvironmentSelections | None,
    knowledge_repository: object | None = None,
    native_identity: Mapping[str, object] | None = None,
) -> OwnerPrerequisite:
    """Do not reuse another selected account, repository or host's setup evidence."""
    identity: dict[str, object] = {}
    if prerequisite.id in {"codex.owner.x4", "codex.owner.x6"} and native_identity:
        identity["native_codex"] = native_identity
    if prerequisite.id == "claude_agent_sdk.owner.a8" and native_identity:
        identity["native_claude"] = native_identity
    if prerequisite.id == "cursor_local.owner.c9" and native_identity:
        identity["native_cursor"] = native_identity
    if selections and selections.auth:
        identity["auth_profile"] = selections.auth.profile
    if prerequisite.scope is PrerequisiteScope.REPO and environment.workspace:
        repo = environment.workspace.repo
        if repo:
            identity["repository"] = repo.url or repo.path
    if prerequisite.scope is PrerequisiteScope.REPO and selections:
        workspace = selections.knowledge_workspace
        if workspace is not None:
            identity["knowledge_workspace"] = workspace.model_dump(mode="json", exclude_none=True)
            identity["knowledge_repository"] = knowledge_repository
    if prerequisite.scope in {PrerequisiteScope.HOST, PrerequisiteScope.ENVIRONMENT}:
        if selections and selections.execution_environment:
            identity["execution_environment"] = selections.execution_environment.model_dump(
                mode="json", exclude_none=True
            )
    if not identity:
        return prerequisite
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    suffix = sha256(encoded.encode()).hexdigest()[:24]
    updates: dict[str, Any] = {"id": f"{prerequisite.id}.{suffix}"}
    if "native_codex" in identity:
        native_bytes = json.dumps(native_identity, sort_keys=True, separators=(",", ":")).encode()
        updates["why"] = (
            prerequisite.why + " Native Codex identity: sha256:" + sha256(native_bytes).hexdigest()
        )
        auth = native_identity.get("auth") if native_identity else None
        if prerequisite.id == "codex.owner.x4" and isinstance(auth, dict):
            if auth.get("billing_mode") == "api":
                updates["steps"] = (
                    "Verify the selected API-key profile with native ephemeral account login "
                    "and account/read, plus read-only access to the selected model metadata. "
                    "Keep credentials in the Secret Broker; do not create workspace auth.json.",
                )
    if "native_claude" in identity:
        native_bytes = json.dumps(native_identity, sort_keys=True, separators=(",", ":")).encode()
        updates["why"] = (
            prerequisite.why
            + " Native Claude host identity: sha256:"
            + sha256(native_bytes).hexdigest()
        )
        updates["steps"] = (
            "Verify the selected pinned SDK/bundled CLI and exact local host configuration. "
            "The API-key route requires broker delivery configuration; key resolution is M4. "
            "This file check does not prove API authentication or model entitlement.",
        )
    if "native_cursor" in identity:
        updates["why"] = (
            prerequisite.why + " Native Cursor host identity: " + _public_digest(native_identity)
        )
        updates["steps"] = (
            "Verify the pinned SDK, archive/protocol/Node closure, selected host configuration "
            "and actual repository-root-preserving cleanup fixture. Auth and host scope "
            "admission; they are not fields of the sealed Cursor binding. API delivery "
            "configuration is not authentication or model entitlement; M4 remains separate.",
        )
    return prerequisite.model_copy(update=updates)


class PrerequisitePreflight:
    def __init__(
        self,
        repository: OwnerPrerequisiteRepository,
        *,
        kits: EnvironmentKitCatalog | None = None,
        bundles: BundleMaterializer | None = None,
        network_hosts: NetworkHosts | None = None,
        installation_check: Callable[[], Awaitable[tuple[str, ...]]] | None = None,
        knowledge_repository: object | None = None,
        oauth_requirements: Callable[[MissionDefinition], Awaitable[tuple[OAuthRequirement, ...]]]
        | None = None,
        native_identity: Callable[[DefinitionNode, bool], Mapping[str, object]] | None = None,
    ) -> None:
        self.repository = repository
        self._kits = kits
        self._bundles = bundles
        self._hosts = network_hosts or NetworkHosts()
        self._installation_check = installation_check
        self._knowledge_repository = knowledge_repository
        self._oauth_requirements = oauth_requirements
        self._native_identity = native_identity

    async def assess(
        self,
        request_scope: str,
        definitions: Sequence[MissionDefinition],
        *,
        templates: Mapping[str, OperationExecutionRequest] | None = None,
    ) -> PreflightReport:
        items: dict[str, PreflightItem] = {}
        blockers: list[str] = []
        if self._installation_check is not None:
            blockers.extend(await self._installation_check())
        degradations: list[str] = []
        requirements: list[ReadinessRequirement] = []
        for definition in definitions:
            oauth: tuple[OAuthRequirement, ...] | None = None
            uses_managed = any(
                LaneProfile(
                    (
                        node.verifier_environment
                        if verifier and node.verifier_environment
                        else node.environment
                    ).lane
                    or node.lane
                )
                is LaneProfile.CLAUDE_MANAGED
                for node, verifier in node_roles(definition.program)
            )
            if self._oauth_requirements is not None and uses_managed:
                try:
                    oauth = await self._oauth_requirements(definition)
                except (ValueError, LookupError) as error:
                    blockers.append(str(error))
            requirements.extend(readiness_requirements(definition, templates=templates))
            for node, verifier in node_roles(definition.program):
                env = (
                    node.verifier_environment
                    if verifier and node.verifier_environment
                    else node.environment
                )
                profile = LaneProfile(env.lane or node.lane)
                if profile is LaneProfile.DEEP_AGENTS:
                    continue
                selections = (
                    node.verifier_selections
                    if verifier and node.verifier_selections
                    else node.selections
                )
                prerequisites = list(account_prerequisites(profile))
                if profile is LaneProfile.CLAUDE_MANAGED and oauth is not None:
                    prerequisites = [
                        require_oauth(item, oauth) if item.id.endswith(".ma5") else item
                        for item in prerequisites
                        if not item.id.endswith(".ma5") or oauth
                    ]
                try:
                    inputs = await self._inputs(selections)
                    prerequisites.extend(generate_owner_prerequisites(profile, inputs))
                except (ValueError, LookupError) as error:
                    # A missing kit/host/custody is never replaced with invented provider data.
                    blockers.append(f"{profile.value} {node.key}: {error}")
                for prerequisite in prerequisites:
                    native_identity = None
                    if (
                        profile
                        in {
                            LaneProfile.CODEX,
                            LaneProfile.CLAUDE_AGENT_SDK,
                            LaneProfile.CURSOR_LOCAL,
                        }
                        and self._native_identity is not None
                    ):
                        try:
                            native_identity = self._native_identity(node, verifier)
                        except (ValueError, LookupError) as error:
                            blockers.append(f"{profile.value} {node.key}: {error}")
                    if profile is LaneProfile.CURSOR_LOCAL:
                        if native_identity is None:
                            blockers.append(
                                f"{profile.value} {node.key}: "
                                "native Cursor C9 identity is unavailable"
                            )
                        if templates:
                            template = _role_template(definition, templates, node, verifier)
                            cursor = (
                                CursorExecutionBinding.carried_by(template)
                                if template is not None
                                else None
                            )
                            if template is None or cursor is None or native_identity is None:
                                blockers.append(
                                    f"{profile.value} {node.key}: "
                                    "sealed Cursor C9 identity is unavailable"
                                )
                            else:
                                # Auth/host remain scoped deployment admission facts. Compare only
                                # the actual sealed subset; projection/materialization retain their
                                # existing binding/approval-seal verification, unchanged.
                                try:
                                    configuration = cursor_sealed_configuration(cursor)
                                except ValueError:
                                    blockers.append(
                                        f"{profile.value} {node.key}: "
                                        "sealed Cursor C9 configuration is invalid"
                                    )
                                    continue
                                sealed_identity = dict(native_identity)
                                sealed_identity.update(
                                    workspace={
                                        key: getattr(template.workspace, key)
                                        for key in (
                                            "provider",
                                            "runtime_digest",
                                            "image_digest",
                                            "package_digest",
                                            "environment_digest",
                                            "network_policy",
                                        )
                                    },
                                    agent_profile_ref=template.agent_profile_ref.model_dump(
                                        mode="json"
                                    ),
                                    cursor_configuration=configuration,
                                )
                                if native_identity != sealed_identity:
                                    blockers.append(
                                        f"{profile.value} {node.key}: "
                                        "sealed native identity differs from deployment"
                                    )
                                native_identity = sealed_identity
                    if profile in {LaneProfile.CODEX, LaneProfile.CLAUDE_AGENT_SDK} and templates:
                        template = _role_template(definition, templates, node, verifier)
                        provider = (
                            ProviderExecutionBinding.carried_by(template)
                            if template is not None
                            else None
                        )
                        if template is not None and provider is not None:
                            sealed_identity = {
                                "workspace": {
                                    key: getattr(template.workspace, key)
                                    for key in (
                                        "provider",
                                        "runtime_digest",
                                        "image_digest",
                                        "package_digest",
                                        "environment_digest",
                                        "network_policy",
                                    )
                                },
                                "host_profile": provider.environment.host_profile,
                                "auth": provider.auth.model_dump(mode="json", exclude_none=True),
                                "cli_version": provider.pins.get(
                                    "cli.codex"
                                    if profile is LaneProfile.CODEX
                                    else "cli.claude_code"
                                ),
                                "model_id": provider.model.model_id,
                            }
                            if profile is LaneProfile.CLAUDE_AGENT_SDK:
                                if provider.auth.billing_mode != "api":
                                    blockers.append(
                                        f"{profile.value} {node.key}: "
                                        "native host proof requires the API-key route"
                                    )
                                    continue
                                sealed_identity.update(
                                    sdk_version=provider.pins.get("sdk.claude_agent_sdk"),
                                    host_configuration_digest="sha256:"
                                    + sha256(
                                        json.dumps(
                                            provider.environment.model_dump(
                                                mode="json", exclude_none=True
                                            ),
                                            sort_keys=True,
                                            separators=(",", ":"),
                                        ).encode()
                                    ).hexdigest(),
                                    auth_route="api_key",
                                    provider_options=provider.provider_options.model_dump(
                                        mode="json"
                                    ),
                                    agent_profile_ref=template.agent_profile_ref.model_dump(
                                        mode="json"
                                    ),
                                )
                            if native_identity is not None and native_identity != sealed_identity:
                                blockers.append(
                                    f"{profile.value} {node.key}: sealed native identity "
                                    "differs from deployment"
                                )
                            native_identity = sealed_identity
                    prerequisite = scope_prerequisite(
                        prerequisite,
                        env,
                        selections,
                        self._knowledge_repository,
                        native_identity=native_identity,
                    )
                    record = await self.repository.register(request_scope, prerequisite)
                    assessment = assess_prerequisite(record, now=datetime.now(UTC))
                    item = PreflightItem(prerequisite=prerequisite, assessment=assessment)
                    prior = items.get(prerequisite.id)
                    if prior and prior.prerequisite.digest != prerequisite.digest:
                        blockers.append(
                            f"{prerequisite.id}: node roles require different setup; "
                            "select separate environments"
                        )
                    items[prerequisite.id] = item
                if profile is LaneProfile.CODEX_CLOUD:
                    degradations.append(
                        "codex_cloud has no native in-environment hooks; "
                        "readiness needs explicit signals"
                    )
        return PreflightReport(
            ready=not blockers and not any(item.assessment.blocking for item in items.values()),
            items=tuple(items[key] for key in sorted(items)),
            degradations=tuple(dict.fromkeys(degradations)),
            readiness=tuple(requirements),
            blockers=tuple(dict.fromkeys(blockers)),
        )

    async def require(
        self,
        request_scope: str,
        definition: MissionDefinition,
        *,
        templates: Mapping[str, OperationExecutionRequest] | None = None,
    ) -> None:
        report = await self.assess(request_scope, (definition,), templates=templates)
        if not report.ready:
            raise PrerequisitesUnmet(report)

    async def _inputs(self, selections: EnvironmentSelections | None) -> GenerationInputs:
        pin = selections.kit.pin if selections and selections.kit else None
        kit = await self._kits.resolve(pin) if pin and self._kits else None
        if pin and kit is None:
            raise PrerequisiteGenerationError(f"Environment Kit {pin} is unavailable")
        files: dict[str, bytes] = {}
        if kit is not None:
            if self._bundles is None:
                raise PrerequisiteGenerationError("Environment Kit bundle custody is unavailable")
            files = dict(await self._bundles.files(kit))
        network = None
        if selections and selections.network:
            network = resolve_network_policy(
                selections.network,
                kit=selections.kit,
                kit_egress=None if kit is None else kit.kit.requires.egress,
                hosts=self._hosts,
                signal_ingress=requires_signal_ingress(selections),
            )
        return GenerationInputs(
            PrerequisiteEnvironment(
                setup_pin=pin,
                network=network,
                network_policy_ref=None if network is None else network.digest,
                secret_refs=tuple(item.binding_ref for item in selections.secrets or ())
                if selections
                else (),
            ),
            kit=kit,
            base_files=files,
            strategy=selections.provider_environment.strategy
            if selections and selections.provider_environment
            else None,
        )


class StoredPrerequisiteLaunchGuard:
    """Prevent direct run-start and chain routes bypassing manifest owner checks."""

    def __init__(
        self,
        definitions: Callable[[str, str], Awaitable[Any]],
        preflight: PrerequisitePreflight,
        *,
        runtime_templates: Callable[[str, str], Awaitable[Sequence[OperationExecutionRequest]]]
        | None = None,
    ) -> None:
        self._definitions = definitions
        self._preflight = preflight
        self._runtime_templates = runtime_templates

    async def __call__(self, request_scope: str, run_id: str) -> None:
        await self._check(request_scope, run_id, None)

    async def require_launch(
        self, request: RunLaunchRequest, workflow_input: StageGraphRunInput | GoalDirectedRunInput
    ) -> None:
        await self._check(request.request_scope, request.run_id, workflow_input)

    async def _check(
        self,
        request_scope: str,
        run_id: str,
        workflow_input: StageGraphRunInput | GoalDirectedRunInput | None,
    ) -> None:
        stored = await self._definitions(request_scope, run_id)
        if stored is not None:
            body = stored["definition"]
            if isinstance(body, dict) and body.get("contract") == "mc.run-request-definition/1":
                definition = RuntimeRequestDefinition.model_validate(body)
                if definition.request_scope != request_scope:
                    raise RunLaunchRejected(
                        "identity_mismatch", "runtime definition names another scope"
                    )
                if workflow_input is None:
                    raise RunLaunchRejected(
                        "invalid_family_input", "generic runtime guard needs validated family input"
                    )
                if (
                    definition.effective_configuration_digest
                    != workflow_input.effective_configuration_digest
                ):
                    raise RunLaunchRejected(
                        "configuration_mismatch", "runtime definition names another configuration"
                    )
                # Generic runtime snapshots do not carry manifest provider selections.
                # Native runtime admission remains supported; provider operations must use
                # an authored manifest so their owner checks can be regenerated exactly.
                if self._runtime_templates is None:
                    raise RunLaunchRejected(
                        "prerequisites_unavailable",
                        "generic runtime template guard is not composed",
                    )
                operations = list(
                    await self._runtime_templates(
                        request_scope, workflow_input.semantic_input_binding_ref
                    )
                )
                if isinstance(workflow_input, StageGraphRunInput):
                    operations.extend(
                        item.operation for item in workflow_input.operation_requests.values()
                    )
                if any(
                    operation.lane_profile not in {None, "deep_agents"}
                    or operation.execution_runtime in {"cursor", "claude", "codex"}
                    for operation in operations
                ):
                    raise PrerequisitesUnmet(
                        PreflightReport(
                            ready=False,
                            blockers=(
                                "provider operations require a manifest definition with "
                                "scoped owner prerequisites",
                            ),
                        )
                    )
                report = await self._preflight.assess(request_scope, ())
                if not report.ready:
                    raise PrerequisitesUnmet(report)
                return
            await self._preflight.require(request_scope, MissionDefinition.model_validate(body))
