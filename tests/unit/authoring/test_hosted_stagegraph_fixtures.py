"""F2-G2 (ITER-3-2026-11-06): the W1 hosted launch bindings and the F2/F3 Stage Graph fixtures.

Offline proof of the hosted path a live F2/F3 run takes, without a provider call:

- `scripts/hosted_launch_bindings.py` turns the W1 Deep Agents bindings (rebuilt here by the same
  `scripts/sprint_oc_w1_bindings.py` that wrote the live file) into `mc.manifest_launch_bindings.v2`
  with `providers.claude_managed` / `providers.codex_agents`, every v1 section unchanged;
- each fixture compiles startable, and the API's launch resolver
  (`compose_manifest_launch_resolver`, with the production hosted digest) seals every stage as a
  repository-less `mc.execution_binding.v2` routed to `mc-ai-engineer-lane-hosted`;
- the worker composes both hosted harnesses from that file (`compose_hosted_lanes`), and its
  `HostedProjectionSource` re-renders the sealed materialization digest exactly, so the lane's
  `CAPABILITY_DRIFT` check passes and no read-only repository proof is demanded.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from contextlib import AsyncExitStack
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import SecretStr

from mission_control.adapters.anthropic_managed.harness import ClaudeManagedHarness
from mission_control.adapters.anthropic_managed.pack import RenderedPack
from mission_control.adapters.openai_agents.harness import CodexAgentsHarness
from mission_control.adapters.openai_agents.pack import CodexAgentsPack
from mission_control.adapters.remote_session.projection import digest as hosted_digest
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.adapters.temporal.hosted_lane_composition import (
    HostedProjectionSource,
    compose_hosted_lanes,
)
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestLaunchBindingError,
    ManifestLaunchBindings,
)
from mission_control.application.authoring.provider_launch import (
    ProviderBindingRows,
    required_pins,
)
from mission_control.application.secrets.broker import SecretBroker
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.bootstrap.settings import Settings
from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from tests.fixtures.applications import installed_applications
from tests.fixtures.models import bindings_catalog
from tests.unit.authoring.test_manifest_v2_launch import SCOPE, compile_yaml, edited, served

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/fixtures/manifests/experiment-loop"
HOSTED_QUEUE = "mc-ai-engineer-lane-hosted"
CASES = {
    "claude_managed": ("f2-managed-stagegraph.mission.yml", "claude-haiku-5-5"),
    "codex_agents": ("f3-agents-stagegraph.mission.yml", "gpt-6.1-sol"),
}
AGENT_STAGES = {"collect_a", "collect_b", "synthesize"}
INSTALLATION = "01a103c0-9a9e-70f3-9398-eb1573a98324"


def _script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def w1_source() -> dict[str, Any]:
    """The W1 v1 file as `sprint_oc_w1_bindings.py` writes it for AI Engineer."""

    document: dict[str, Any] = _script("sprint_oc_w1_bindings").build(ROOT, "ai-engineer")
    return json.loads(json.dumps(document))


@pytest.fixture(scope="module")
def hosted_document(w1_source: dict[str, Any]) -> dict[str, Any]:
    return _script("hosted_launch_bindings").build(w1_source, root=ROOT)


@pytest.fixture(scope="module")
def hosted(hosted_document: dict[str, Any]) -> ManifestLaunchBindings:
    return ManifestLaunchBindings.model_validate(hosted_document)


def _resolver(bound: ManifestLaunchBindings) -> Any:
    return compose_manifest_launch_resolver(
        bound,
        served(bound),
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env={},
        # The production composition (`bootstrap/manifests.py`).
        hosted_digest=lambda profile, config, rows, environment: hosted_digest(
            profile, config, rows, installation_id="digest-only", environment=environment
        ),
        allow_unqualified_lanes=True,
    )


def _templates(text: str, bound: ManifestLaunchBindings) -> dict[str, Any]:
    compilation = compile_yaml(text)
    assert compilation.ok, [(item.pointer, item.message) for item in compilation.report.blockers]
    assert compilation.report.startable, compilation.report.start_blockers
    (definition,), (program,) = compilation.definitions, compilation.programs
    assert program.lowered.family == "StageGraph"
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-f2g2", program.configuration)
    return dict(_resolver(bound).stage_templates(definition, admitted))


def test_the_hosted_file_keeps_w1_and_adds_both_reviewed_hosted_lanes(
    w1_source: dict[str, Any], hosted_document: dict[str, Any], hosted: ManifestLaunchBindings
) -> None:
    assert hosted_document["schema_version"] == "mc.manifest_launch_bindings.v2"
    for key in ("capabilities", "deep_agents", "model_profiles", "sandbox_profiles"):
        assert hosted_document[key] == w1_source[key]
    assert hosted.providers is not None
    for profile, (_, model_id) in CASES.items():
        lane = hosted.providers.lane(profile)
        assert lane is not None and lane.hosted_projection is not None
        assert lane.task_queue == HOSTED_QUEUE
        assert lane.pins == dict(required_pins(profile))
        assert lane.model_profiles["hosted.default"].model_id == model_id
        assert {host.kind for host in lane.host_profiles.values()} == {"provider_hosted"}
        assert lane.repository_commits == {}
        assert lane.tracing_policy_ref == w1_source["deep_agents"]["tracing_policy_ref"]
    # Repository-less: the Agents API projection carries no repository credential.
    agents = hosted.providers.lane("codex_agents")
    assert agents is not None and agents.hosted_projection is not None
    document: Any = agents.hosted_projection["document"]
    assert document["vault"]["credentials"] == []


@pytest.mark.parametrize("profile", sorted(CASES))
def test_each_fixture_seals_repository_less_hosted_stages_on_the_hosted_queue(
    profile: str, hosted: ManifestLaunchBindings
) -> None:
    name, model_id = CASES[profile]
    templates = _templates((FIXTURES / name).read_text(encoding="utf-8"), hosted)
    stages = {key.split("/", 1)[0] for key in templates}
    assert stages >= AGENT_STAGES
    assert hosted.providers is not None
    lane = hosted.providers.lane(profile)
    assert lane is not None and lane.hosted_projection is not None
    for key, template in templates.items():
        assert template.lane_profile == profile
        assert template.lane_dispatch is not None
        assert template.lane_dispatch.task_queue == HOSTED_QUEUE
        binding = ProviderExecutionBinding.carried_by(template)
        assert binding is not None, key
        assert binding.task_queue == HOSTED_QUEUE
        assert (binding.repo_url, binding.repo_ref, binding.repo_commit) == (None, None, None)
        assert binding.environment.kind == "provider_hosted"
        assert binding.environment.environment_ref == "ai-engineer-knowledge"
        assert binding.model.model_id == model_id
        assert binding.materialization_digest == hosted_digest(
            profile, lane.hosted_projection, (), installation_id="any", environment=None
        )


def test_a_named_repository_still_needs_its_reviewed_commit(
    hosted: ManifestLaunchBindings,
) -> None:
    def with_repository(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["workspace"]["repo"] = {
            "url": "https://github.com/Overton77/mission-control-fixture",
            "ref": "main",
        }

    text = edited(FIXTURES / CASES["claude_managed"][0], with_repository)
    with pytest.raises(ManifestLaunchBindingError, match="repository_commits"):
        _templates(text, hosted)


def test_the_fixtures_share_one_shape_and_differ_only_in_their_lane() -> None:
    managed, agents = (
        load_manifest_yaml((FIXTURES / CASES[profile][0]).read_text(encoding="utf-8"))
        for profile in ("claude_managed", "codex_agents")
    )
    for document in (managed, agents):
        mission = document["mission"]
        assert mission["application"] == "ai-engineer" and mission["data_class"] == "internal"
        nodes = {node["key"]: node for node in mission["program"]["nodes"]}
        assert nodes["synthesize"]["depends_on"] == ["collect_a", "collect_b"]
        assert nodes["review"]["behavior"] == "human_gate"
        assert all(
            output["enforcement"] == "expected"
            for node in nodes.values()
            for output in node.get("outputs", ())
        )
    assert managed["mission"]["environment"]["lane"] == "claude_managed"
    assert agents["mission"]["environment"]["lane"] == "codex_agents"


def test_the_worker_composes_both_hosted_lanes_and_reprojects_the_sealed_digest(
    tmp_path: Path, hosted_document: dict[str, Any], hosted: ManifestLaunchBindings
) -> None:
    path = tmp_path / "w1-launch-bindings-hosted.json"
    path.write_text(json.dumps(hosted_document), encoding="utf-8")
    settings = Settings(
        _env_file=None,
        manifest_launch_bindings_path=path,
        mission_control_claude_managed_lane=True,
        mission_control_codex_agents_lane=True,
        anthropic_api_key=SecretStr("test-anthropic-not-a-key"),
        openai_api_key=SecretStr("test-openai-not-a-key"),
        temporal_task_queue="biotech-research-ingestion",
        mission_control_catalog_scope=f"mc/{INSTALLATION}/ai-engineer/catalog",
    )

    async def compose() -> tuple[Any, Any, dict[str, Any]]:
        async with AsyncExitStack() as resources:
            return compose_hosted_lanes(
                settings=settings,
                pool=object(),
                payloads=object(),  # type: ignore[arg-type]
                bundles=None,
                secrets=SecretBroker(environment=WorkerEnvironmentSource({})),
                broker=object(),  # type: ignore[arg-type]
                resources=resources,
                client=object(),  # type: ignore[arg-type]
                installation_id=INSTALLATION,
                signal_ingress=object(),  # type: ignore[arg-type]
            )

    managed, agents, deleters = asyncio.run(compose())
    assert isinstance(managed, ClaudeManagedHarness)
    assert isinstance(agents, CodexAgentsHarness)
    assert set(deleters) == {"claude_managed", "codex_agents"}

    async def no_rows(_pins: Any) -> dict[str, Any]:
        raise AssertionError("the fixtures pin no catalog capability")

    async def no_readonly_proof(*_args: Any) -> None:
        raise AssertionError("a repository-less hosted projection needs no read-only proof")

    source = HostedProjectionSource(
        ManifestLaunchBindings.load(path),
        ProviderBindingRows(no_rows),
        installation_id=INSTALLATION,
        readonly_evidence=no_readonly_proof,
    )
    for profile, (name, _) in CASES.items():
        templates = _templates((FIXTURES / name).read_text(encoding="utf-8"), hosted)
        template = templates["collect_a/execute/default"]
        binding = ProviderExecutionBinding.carried_by(template)
        assert binding is not None
        pack = asyncio.run(source(template))
        expected = RenderedPack if profile == "claude_managed" else CodexAgentsPack
        assert isinstance(pack, expected)
        actual = pack.materialization_digest if isinstance(pack, RenderedPack) else pack.digest
        assert actual == binding.materialization_digest
