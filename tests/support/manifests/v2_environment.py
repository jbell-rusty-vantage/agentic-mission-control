"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_manifest_v2_environment.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestLaunchResolver,
)
from mission_control.application.authoring.manifest_service import (
    CompiledMission,
    ManifestCompilation,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.authoring.mission_environment import KitRequirements
from mission_control.domain.execution.network_policy import NetworkHosts, ResolvedNetworkPolicy
from tests.support.applications import installed_applications
from tests.support.manifests.seeded_catalog import fast_track_catalog
from tests.support.manifests.v2_launch import SCOPE, bindings, example, served
from tests.support.model_catalog import bindings_catalog

AT = datetime(2026, 10, 13, tzinfo=UTC)
REPO = "https://github.com/jbell-rusty-vantage/mission-control-fixtures"


KIT_PIN = "envkit.python-uv-node@3#sha256:" + "1" * 64


CONFIG = {"knowledge_services.public_url": "https://knowledge.example.org"}
KIT = KitRequirements.from_requires(
    {
        "variables": ["LOG_LEVEL"],
        "secrets": ["FIRECRAWL_API_KEY", "OPTIONAL_TOKEN?"],
        "egress": ["pypi.org", "registry.npmjs.org"],
    }
)
# The Secret Broker's declaration entries (MO-11): a manifest secret reaches the agent only.
SECRET_REFS = (
    "FIRECRAWL_API_KEY=secret:firecrawl/api_key;agent",
    "MC_SIGNAL_TOKEN=mint:signal_token;agent",
)
# The installation's Signal Ingress host (MO-15) and the policy the example resolves to.
INGRESS = "mc-ingress.vercel.app"
RESOLVED = ResolvedNetworkPolicy(
    mode="allowlist",
    hosts=("api.firecrawl.dev", INGRESS, "pypi.org", "registry.npmjs.org"),
    signal_ingress=INGRESS,
    kit=KIT_PIN,
)
ENV = "/mission/environment"
NODE = "/mission/program/nodes/0/environment"


class Inputs:
    """FIXTURE: an installation's published kits and configuration, read offline."""

    def __init__(self, kits: dict[str, KitRequirements] | None = None) -> None:
        self.kits = {KIT_PIN: KIT} if kits is None else kits
        self.calls: list[str] = []

    async def kit_requirements(self, pin: str) -> KitRequirements | None:
        self.calls.append(pin)
        return self.kits.get(pin)

    async def config_value(self, key: str) -> str | None:
        return CONFIG.get(key)


def additions() -> dict[str, Any]:
    return {
        "kit": {"pin": KIT_PIN},
        "variables": [
            {"name": "LOG_LEVEL", "value": "info"},
            {"name": "KS_API_URL", "value_ref": "config:knowledge_services.public_url"},
        ],
        "secrets": [
            {"name": "FIRECRAWL_API_KEY", "ref": "secret:firecrawl/api_key"},
            {"name": "MC_SIGNAL_TOKEN", "ref": "mint:signal_token", "phases": ["agent"]},
        ],
        "network": {
            "mode": "allowlist",
            "allow": ["api.firecrawl.dev"],
            "include_signal_ingress": True,
        },
        "git": {
            "repos": [{"url": REPO, "ref": "main", "role": "target"}],
            "write": {"mode": "branch_and_pr", "pr": {"draft": True, "base": "main"}},
        },
    }


def _hosted(provider: str, environment_ref: str, strategy: dict[str, Any]) -> Callable[..., None]:
    def place(environment: dict[str, Any]) -> None:
        environment["execution_environment"] = {
            "kind": "provider_hosted",
            "provider": provider,
            "environment_ref": environment_ref,
        }
        environment["workspace"]["policy"] = {"mode": "provider_workspace", "reuse": "none"}
        environment["provider_environment"] = strategy
        environment.pop("continuation", None)
        if provider == "cursor":
            # The deployment's providers.cursor_cloud registry keys.
            environment["model"] = {"profile": "cursor.default"}
            environment["auth"] = {"profile": "cursor-cloud-key"}
        else:
            environment["execution_environment"]["expected_revision"] = "rev-1"
            # A hosted Claude/Codex lane cannot prove the example's lifecycle requirements.
            environment.pop("requires")

    return place


def _local(host_profile: str, *, path: bool = False) -> Callable[..., None]:
    def place(environment: dict[str, Any]) -> None:
        environment["execution_environment"] = {"kind": "local_workspace", "profile": host_profile}
        if path:
            environment["workspace"]["repo"]["path"] = "/srv/repos/mission-control-fixture"

    return place


# One manifest; only the lane, its placement and its provider strategy differ per profile.
PLACEMENTS: dict[str, Callable[..., None]] = {
    "claude_agent_sdk": _local("worker.linux.default"),
    "codex": _local("worker.linux.wsl"),
    "cursor_local": _local("worker.linux.wsl", path=True),
    "cursor_cloud": _hosted("cursor", "cursor-cloud.default", {"strategy": "sync"}),
    "claude_cloud": _hosted("anthropic", "env-fixture", {"strategy": "generate"}),
    "codex_cloud": _hosted("openai", "env-fixture", {"strategy": "bind", "ref": "env-fixture"}),
}


def manifest(
    profile: str = "claude_agent_sdk",
    change: Callable[..., None] | None = None,
    *,
    deep_agents_node: bool = False,
) -> str:
    """The checked Claude Agent SDK Stage Graph example with the additions mission-wide."""

    document = load_manifest_yaml(
        example("claude_agent_sdk", "stage-graph").read_text(encoding="utf-8")
    )
    environment = document["mission"]["environment"]
    environment.update(additions())
    environment["lane"] = profile
    PLACEMENTS[profile](environment)
    nodes = document["mission"]["program"]["nodes"]
    # The lane-specific requirements of the example's patch node are not under test here.
    nodes[1]["environment"].pop("requires")
    if not deep_agents_node:
        nodes.pop()
    if change is not None:
        change(document)
    return canonical_manifest_bytes(document).decode("utf-8")


async def _compile(text: str, inputs: Inputs | None) -> ManifestCompilation:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
        environment_inputs=inputs,
    )
    return await service.compile(text, ManifestScope(request_scope=SCOPE, actor_id="owner", at=AT))


def compile_text(text: str, inputs: Inputs | None = None) -> ManifestCompilation:
    return asyncio.run(_compile(text, inputs if inputs is not None else Inputs()))


def blockers(compilation: ManifestCompilation) -> dict[str, str]:
    return {item.pointer: str(item.reason) for item in compilation.report.blockers}


def _set(path: str, value: Any) -> Callable[..., None]:
    def change(document: dict[str, Any]) -> None:
        *parents, last = path.split("/")
        target: Any = document
        for part in parents:
            target = target[int(part)] if isinstance(target, list) else target[part]
        target[last] = value

    return change


def network_resolver(hosts: NetworkHosts | None = None) -> ManifestLaunchResolver:
    bound = bindings()
    return compose_manifest_launch_resolver(
        bound,
        served(bound),
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env={"openai": "OPENAI_API_KEY"},
        network_hosts=hosts if hosts is not None else NetworkHosts(signal_ingress=INGRESS),
    )


def launch_templates(
    program: CompiledMission,
    definition: MissionDefinition,
    *,
    hosts: NetworkHosts | None = None,
    kit_egress: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """The run's templates from a resolver composed with the installation's Signal Ingress host
    and the kits' resolved egress (what ``ManifestLaunchInputAuthor`` reads through its port)."""

    target = network_resolver(hosts)
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
    egress = kit_egress if kit_egress is not None else {KIT_PIN: KIT.egress}
    if program.lowered.family == "StageGraph":
        return dict(target.stage_templates(definition, admitted, kit_egress=egress))
    return dict(target.goal_templates(definition, admitted, kit_egress=egress))


def _sdk_templates(change: Callable[..., None] | None = None, **network: Any) -> dict[str, Any]:
    compilation = compile_text(manifest("claude_agent_sdk", change))
    assert compilation.ok, blockers(compilation)
    (definition,), (program,) = compilation.definitions, compilation.programs
    templates = launch_templates(program, definition, **network)
    assert templates
    return templates
