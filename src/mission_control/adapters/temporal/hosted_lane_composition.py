"""Production hosted lanes: exact projection, durable approvals, scoped signals and retention."""

from __future__ import annotations

import base64
import json
import os
import shlex
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from temporalio.client import Client

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.anthropic_managed.harness import (
    ClaudeManagedHarness,
    ManagedSessionDeleter,
)
from mission_control.adapters.anthropic_managed.pack import RenderedPack
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare
from mission_control.adapters.anthropic_managed.publication import ManagedPublishExecutor
from mission_control.adapters.anthropic_managed.time_travel import ClaudeManagedTimeTravel
from mission_control.adapters.anthropic_managed.tools import ManagedTools
from mission_control.adapters.github import GitHubRestClient, github_credentials
from mission_control.adapters.github.governed_comment import MissionPrCommentExecutor
from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.openai_agents.harness import AgentsSessionDeleter, CodexAgentsHarness
from mission_control.adapters.openai_agents.pack import CodexAgentsPack
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.openai_agents.time_travel import CodexAgentsTimeTravel
from mission_control.adapters.openai_agents.tools import AgentsTools
from mission_control.adapters.postgres.approvals.context import PostgresApprovalContextProbe
from mission_control.adapters.postgres.approvals.intents import PostgresGovernedIntentRepository
from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.lanes.hook_tokens import PostgresHookIntentLedger
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.remote_session.function_custody import (
    CustodiedBundlePublishExecutor,
    HostedArtifactUploadExecutor,
)
from mission_control.adapters.remote_session.projection import project
from mission_control.adapters.remote_session.signals import HostedSignalDelivery
from mission_control.adapters.remote_session.time_travel import ScopedFrameReader
from mission_control.adapters.storage.context_files import PayloadContextFiles
from mission_control.adapters.temporal.activities.session_retention import (
    TemporalSessionDeletionScheduler,
)
from mission_control.adapters.temporal.local_signals import ScopedSecretMinter
from mission_control.adapters.temporal.registration.task_queues import maintenance_task_queue
from mission_control.adapters.workspaces.bundle_publication import GitBundlePublisher
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadPort
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindings
from mission_control.application.authoring.provider_launch import (
    CatalogProjectionRows,
    ProviderBindingRows,
)
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.effects.ports import GitCredential
from mission_control.application.effects.repo_pr import RepoPullRequestExecutor
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.approvals_governed import (
    GOVERNED_EFFECT_PERMISSION,
    GovernedEffectService,
    GovernedTool,
    GovernedToolPolicy,
    GovernedToolRegistry,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.retention import (
    HostedSessionDeleter,
    SessionRetentionService,
)
from mission_control.application.execution.harness.time_travel import TimeTravelLane
from mission_control.application.execution.hosted_tools import (
    HostedGovernedTools,
    HostedToolGate,
)
from mission_control.application.frames.sink import FrameReader
from mission_control.application.secrets.broker import SecretBroker
from mission_control.application.secrets.references import BrokerRef, SecretDeclaration
from mission_control.application.signals.service import SignalIngressService
from mission_control.bootstrap.hosted_readonly import HostedReadonlyVerifier
from mission_control.bootstrap.settings import Settings
from mission_control.domain.authoring.environment_kits import render_mission_layer
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.contracts import ActorContext


class BrokerEnvironment:
    def __init__(self, broker: SecretBroker) -> None:
        self.broker = broker

    async def read(self, key: str) -> str | None:
        result = await self.broker.resolve_declarations(
            (
                SecretDeclaration(
                    name=key,
                    ref=BrokerRef(scheme="environment", key=key),
                    phases=("agent",),
                    required=False,
                ),
            )
        )
        return result.values.get(key)


class ConfiguredGitCredentials:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def credential(self, repository: str) -> GitCredential:
        # No ambient gh fallback. The configured App is repository restricted by the adapter.
        return await github_credentials(os.environ, self.http).credential(repository)


class HostedProjectionSource:
    def __init__(
        self,
        bindings: ManifestLaunchBindings,
        rows: ProviderBindingRows,
        *,
        installation_id: str,
        readonly_evidence: Callable[
            [OperationExecutionRequest, tuple[BrokerRef, ...]], Awaitable[None]
        ]
        | None = None,
    ) -> None:
        self.bindings, self.rows, self.installation_id = bindings, rows, installation_id
        self.readonly_evidence = readonly_evidence

    async def __call__(
        self, operation: OperationExecutionRequest
    ) -> RenderedPack | CodexAgentsPack:
        binding = ProviderExecutionBinding.carried_by(operation)
        if binding is None or self.bindings.providers is None:
            raise ValueError("hosted provider binding unavailable")
        lane = self.bindings.providers.lane(binding.lane_profile)
        if lane is None or lane.hosted_projection is None:
            raise ValueError("reviewed hosted projection unavailable")
        projected = project(
            binding.lane_profile,
            lane.hosted_projection,
            tuple(await self.rows(operation)),
            installation_id=self.installation_id,
            environment=binding.environment,
        )
        selected = {item.name: item.ref for item in projected.secret_declarations}
        refs = []
        if isinstance(projected, RenderedPack):
            for item in projected.pack.vault.credentials:
                if any(
                    host in {"github.com", "api.github.com", "raw.githubusercontent.com"}
                    for host in item.allowed_hosts
                ):
                    refs.append(selected.get(item.name, BrokerRef("environment", item.name)))
        else:
            for credential in projected.document.vault.credentials:
                if any(
                    host in {"github.com", "api.github.com", "raw.githubusercontent.com"}
                    for host in credential.allowed_hosts
                ):
                    refs.append(
                        selected.get(
                            credential.name, BrokerRef("environment", credential.source_env)
                        )
                    )
        if refs:
            if self.readonly_evidence is None:
                raise ValueError(
                    "hosted repository credentials require exact trusted readonly evidence"
                )
            await self.readonly_evidence(operation, tuple(refs))
        return projected


async def hosted_setup_commands(
    operation: OperationExecutionRequest,
    identity: LaneExecutionIdentity,
    kits: EnvironmentKitCatalog,
) -> tuple[str, ...]:
    commands = []
    binding = ProviderExecutionBinding.carried_by(operation)
    assert binding is not None
    if binding.repo_url and binding.repo_commit:
        branch = mission_branch(identity.run_key, identity.activation_key)
        commands.append(
            "set -e; git clone --no-checkout "
            + shlex.quote(binding.repo_url)
            + " /workspace/repo; cd /workspace/repo; git fetch origin "
            + shlex.quote(binding.repo_commit)
            + "; git checkout -b "
            + shlex.quote(branch)
            + " "
            + shlex.quote(binding.repo_commit)
        )
    if binding.environment.setup_pin:
        kit = await kits.resolve(binding.environment.setup_pin)
        if kit is None:
            raise ValueError("admitted Environment Kit unavailable")
        layer = render_mission_layer(kit.kit, pin=binding.environment.setup_pin)
        payload = base64.b64encode(json.dumps(layer.files).encode()).decode()
        script = (
            "import base64,json,pathlib; files=json.loads(base64.b64decode('"
            + payload
            + "')); [(p.parent.mkdir(parents=True,exist_ok=True),p.write_text(v)) "
            + "for k,v in files.items() for p in [pathlib.Path(k)]]"
        )
        commands.append(
            "set -e; cd /workspace/repo; python3 -c "
            + shlex.quote(script)
            + "; bash .mission/setup/run --phase setup"
        )
    return tuple(commands)


class ProjectedManagedTools(ManagedTools):
    def __init__(
        self, source: HostedProjectionSource, kits: EnvironmentKitCatalog, **kwargs: Any
    ) -> None:
        self.source, self.kits, self.kwargs = source, kits, kwargs

    async def answer_pending(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        session_id: str,
        turn_id: str,
        idle: Mapping[str, Any],
    ) -> None:
        pack = await self.source(operation)
        assert isinstance(pack, RenderedPack)
        commands = await hosted_setup_commands(operation, identity, self.kits)
        tools = ManagedTools(
            client=self.kwargs["client"],
            gate=self.kwargs["gate"],
            governed=self.kwargs["governed"],
            signal=self.kwargs["signal"],
            artifacts=self.kwargs["artifacts"],
            setup_commands=commands,
            steady_tools=pack.agent_body([])["tools"],
        )
        await tools.answer_pending(operation, identity, session_id, turn_id, idle)


def compose_hosted_time_travel(
    *,
    frames: FrameReader,
    request_scope: str,
    claude_managed: bool = True,
    codex_agents: bool = True,
) -> dict[str, TimeTravelLane]:
    """Cross-provider control (2026-11-05): the hosted lanes' `TimeTravelLane`s, keyed by
    lane profile, for a `TimeTravelRegistry` (`_worker_time_travel`, `bootstrap/api.py`,
    `bootstrap/runtime_control.py` register them beside `deep_agents`).

    Both lanes read and seed at R1 over the persisted frames, so they need only the frame
    reader and the request scope the deployment serves (the frame store is tenant-scoped;
    the registry is not): no provider client, no credential, no paid call.
    """

    reader = ScopedFrameReader(frames, request_scope=request_scope)
    lanes: dict[str, TimeTravelLane] = {}
    if claude_managed:
        lanes["claude_managed"] = ClaudeManagedTimeTravel(reader)
    if codex_agents:
        lanes["codex_agents"] = CodexAgentsTimeTravel(reader)
    return lanes


def compose_hosted_lanes(
    *,
    settings: Settings,
    pool: asyncpg.Pool,
    payloads: ArtifactPayloadPort,
    bundles: BundleMaterializer | None,
    secrets: SecretBroker,
    broker: ApprovalBroker,
    resources: AsyncExitStack,
    client: Client,
    installation_id: str,
    signal_ingress: SignalIngressService | None,
) -> tuple[ClaudeManagedHarness | None, CodexAgentsHarness | None, dict[str, HostedSessionDeleter]]:
    profiles = (
        settings.mission_control_claude_managed_lane,
        settings.mission_control_codex_agents_lane,
    )
    if not any(profiles):
        return None, None, {}
    if settings.manifest_launch_bindings_path is None or signal_ingress is None:
        raise ValueError(
            "hosted lanes require reviewed manifest bindings and restricted signal ingress"
        )
    bindings = ManifestLaunchBindings.load(settings.manifest_launch_bindings_path)
    definitions = PostgresDefinitionRepository(
        pool, catalog_scope=settings.mission_control_catalog_scope or ""
    )
    source = HostedProjectionSource(
        bindings,
        ProviderBindingRows(CatalogProjectionRows(definitions, bundles=bundles)),
        installation_id=installation_id,
        readonly_evidence=HostedReadonlyVerifier(settings, pool).verify_hosted_readonly,
    )

    async def managed_projection(operation: OperationExecutionRequest) -> RenderedPack:
        pack = await source(operation)
        assert isinstance(pack, RenderedPack)
        return pack

    async def agents_projection(operation: OperationExecutionRequest) -> CodexAgentsPack:
        pack = await source(operation)
        assert isinstance(pack, CodexAgentsPack)
        return pack

    artifacts = PayloadContextFiles(payloads)
    retention = SessionRetentionService(
        TemporalSessionDeletionScheduler(
            client, task_queue=maintenance_task_queue(settings.task_queue_base)
        )
    )
    gate = HostedToolGate(
        fences=PostgresStopFenceRepository(pool),
        intents=PostgresHookIntentLedger(pool),
        broker=broker,
        reviewers=settings.mission_control_approval_reviewers,
        allowed_tools=frozenset(
            {
                "bash",
                "read",
                "write",
                "edit",
                "glob",
                "grep",
                "web_fetch",
                "web_search",
                "mc_prepare",
                "mc_signal",
                "mc_record_intent",
                "mc_request_approval",
                "mc_publish",
                "mc_open_pr",
                "mc_upload_artifact",
                "mc_comment",
            }
        ),
        wait_seconds=10,
    )
    signal = HostedSignalDelivery(signal_ingress, ScopedSecretMinter(pool), secrets.registry)
    http = httpx.AsyncClient(timeout=30)
    resources.push_async_callback(http.aclose)
    credentials = ConfiguredGitCredentials(http)
    host = GitHubRestClient(http, credentials)
    publisher = GitBundlePublisher(
        (settings.deep_agent_sandbox_workspace_root or Path(".workspaces")) / "hosted-publication",
        credentials,
    )
    managed = agents = None
    deleters: dict[str, HostedSessionDeleter] = {}
    if profiles[0]:
        if settings.anthropic_api_key is None:
            raise ValueError("claude_managed requires an explicit Anthropic API key")
        api = ManagedAgentsClient(settings.anthropic_api_key)
        resources.push_async_callback(api.aclose)

        def governed(
            operation: OperationExecutionRequest, identity: LaneExecutionIdentity
        ) -> GovernedEffectService:
            registry = GovernedToolRegistry(
                [
                    GovernedTool(
                        "mc_publish",
                        ManagedPublishExecutor(
                            client=api,
                            publisher=publisher,
                            host=host,
                            artifacts=artifacts,
                            operation=operation,
                            identity=identity,
                        ),
                        GovernedToolPolicy(reviewers=settings.mission_control_approval_reviewers),
                        effect_kind="other",
                        family="repo",
                    ),
                    GovernedTool(
                        "repo_pr",
                        RepoPullRequestExecutor(host, artifacts),
                        GovernedToolPolicy(reviewers=settings.mission_control_approval_reviewers),
                        effect_kind="other",
                        family="repo",
                    ),
                ]
            )
            return GovernedEffectService(
                PostgresGovernedIntentRepository(pool),
                PostgresApprovalTaskRepository(pool),
                registry,
                request_scope=identity.request_scope,
                probe=PostgresApprovalContextProbe(pool),
                fences=PostgresStopFenceRepository(pool),
            )

        tools = ProjectedManagedTools(
            source,
            EnvironmentKitCatalog(definitions, bundles=bundles),
            client=api,
            gate=gate,
            signal=signal,
            artifacts=artifacts,
            custody_wait_seconds=10,
            governed=HostedGovernedTools(
                governed,
                ActorContext(
                    actor_id="hosted-runtime", permissions=frozenset({GOVERNED_EFFECT_PERMISSION})
                ),
                wait_seconds=300,
            ),
        )
        managed = ClaudeManagedHarness(
            client=api,
            preparer=ClaudeManagedPrepare(api, secrets, installation_id=installation_id),
            pack=managed_projection,
            artifacts=artifacts,
            retention=retention,
            tools=tools,
        )
        deleters["claude_managed"] = ManagedSessionDeleter(api)
    if profiles[1]:
        if settings.openai_api_key is None:
            raise ValueError("codex_agents requires an explicit OpenAI API key")
        api_agents = AgentsApiClient(settings.openai_api_key)
        resources.push_async_callback(api_agents.aclose)

        def agents_governed(
            operation: OperationExecutionRequest, identity: LaneExecutionIdentity
        ) -> GovernedEffectService:
            intents = PostgresGovernedIntentRepository(pool)
            review = GovernedToolPolicy(reviewers=settings.mission_control_approval_reviewers)
            registry = GovernedToolRegistry(
                [
                    GovernedTool(
                        "mc_upload_artifact",
                        HostedArtifactUploadExecutor(artifacts, identity),
                        GovernedToolPolicy(requires_approval=False),
                        effect_kind="file",
                        family="artifacts",
                    ),
                    GovernedTool(
                        "mc_publish",
                        CustodiedBundlePublishExecutor(
                            artifacts=artifacts,
                            intents=intents,
                            publisher=publisher,
                            host=host,
                            operation=operation,
                            identity=identity,
                            secret_values=secrets.registry.values(),
                        ),
                        review,
                        effect_kind="other",
                        family="repo",
                    ),
                    GovernedTool(
                        "repo_pr",
                        RepoPullRequestExecutor(host, artifacts),
                        review,
                        effect_kind="other",
                        family="repo",
                    ),
                    GovernedTool(
                        "mc_comment",
                        MissionPrCommentExecutor(host, operation, identity),
                        review,
                        effect_kind="other",
                        family="repo",
                    ),
                ]
            )
            return GovernedEffectService(
                intents,
                PostgresApprovalTaskRepository(pool),
                registry,
                request_scope=identity.request_scope,
                probe=PostgresApprovalContextProbe(pool),
                fences=PostgresStopFenceRepository(pool),
            )

        async def agents_setup(
            operation: OperationExecutionRequest, identity: LaneExecutionIdentity
        ) -> tuple[str, ...]:
            return await hosted_setup_commands(
                operation, identity, EnvironmentKitCatalog(definitions, bundles=bundles)
            )

        agents_tools = AgentsTools(
            client=api_agents,
            gate=gate,
            governed=HostedGovernedTools(
                agents_governed,
                ActorContext(
                    actor_id="hosted-runtime", permissions=frozenset({GOVERNED_EFFECT_PERMISSION})
                ),
                wait_seconds=300,
            ),
            signal=signal,
            artifacts=artifacts,
            secrets=secrets.registry,
            setup_commands=agents_setup,
        )
        agents = CodexAgentsHarness(
            client=api_agents,
            preparer=CodexAgentsPreparer(api_agents, BrokerEnvironment(secrets), broker=secrets),
            pack=agents_projection,
            artifacts=artifacts,
            retention=retention,
            tools=agents_tools,
        )
        deleters["codex_agents"] = AgentsSessionDeleter(api_agents)
    return managed, agents, deleters
