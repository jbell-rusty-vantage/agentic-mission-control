"""HL21 projection migration preserves the exact resource keys, then reuses both APIs."""

from pathlib import Path

from mission_control.adapters.anthropic_managed.pack import RenderedPack, load_pack, render_pack
from mission_control.adapters.openai_agents.pack import CodexAgentsPack
from mission_control.adapters.openai_agents.pack import load_pack as load_agents
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.remote_session.projection import configuration, project
from tests.fixtures.managed_agents import FakeManagedAgentsApi
from tests.unit.anthropic_managed.test_prepare import AI_ENGINEER_PACK, prepare
from tests.unit.openai_agents.support import SHIPPED_PACK, FakeAgentsApi
from tests.unit.openai_agents.test_prepare import _preparer


async def test_managed_inline_projection_reuses_all_resources(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Rules\nCite sources.\n")
    original = render_pack(
        load_pack(AI_ENGINEER_PACK),
        installation_id="local",
        repo_root=repo,
        ingress_host="ingress.example.com",
    )
    projected = project("claude_managed", configuration(original), (), installation_id="local")
    assert isinstance(projected, RenderedPack)
    assert (
        projected.materialization_digest,
        projected.kit_digest,
        projected.secret_set_digest,
    ) == (original.materialization_digest, original.kit_digest, original.secret_set_digest)
    api = FakeManagedAgentsApi()
    preparer = prepare(api)
    first = await preparer.sync(original)
    second = await preparer.sync(projected)
    assert first.agent.agent_id == second.agent.agent_id
    assert second.agent.action == "reused" and second.environment.action == "reused"
    assert all(skill.action == "reused" for skill in second.skills)
    assert second.vault.action == "reused"


async def test_agents_inline_projection_reuses_all_resources():
    original = load_agents(SHIPPED_PACK)
    projected = project("codex_agents", configuration(original), (), installation_id="local")
    assert isinstance(projected, CodexAgentsPack)
    assert (projected.digest, projected.template_digest, projected.secret_set_digest) == (
        original.digest,
        original.template_digest,
        original.secret_set_digest,
    )
    api = FakeAgentsApi()
    preparer = _preparer(api)
    first = await preparer.sync(original)
    second = await preparer.sync(projected)
    assert first.agent.id == second.agent.id
    assert second.created == ()


def test_selected_catalog_skill_changes_the_api_projection():
    from tests.fixtures.projections.rows import skill_row

    original = load_agents(SHIPPED_PACK)
    projected = project(
        "codex_agents", configuration(original), (skill_row(),), installation_id="local"
    )
    assert projected.digest != original.digest
    assert projected.template_digest != original.template_digest
    assert "agent-browser" in {skill.name for skill in projected.skills}


def test_inline_bundle_tampering_is_refused():
    import base64

    import pytest

    original = load_agents(SHIPPED_PACK)
    config = configuration(original)
    config["skills"][0]["files"][0][1] = base64.b64encode(b"changed").decode()
    with pytest.raises(ValueError, match="digest"):
        project("codex_agents", config, (), installation_id="local")


def test_unsupported_catalog_callbacks_are_refused_before_provider_io():
    import pytest

    from tests.fixtures.projections.rows import hook_row

    original = load_agents(SHIPPED_PACK)
    with pytest.raises(ValueError, match="omitted selected behavior"):
        project("codex_agents", configuration(original), (hook_row(),), installation_id="local")


async def test_selected_secret_store_ref_uses_shared_broker_for_provider_vault():
    from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
    from mission_control.application.secrets.broker import SecretBroker
    from mission_control.domain.execution.bindings import EnvironmentBinding

    original = load_agents(SHIPPED_PACK)
    environment = EnvironmentBinding(
        kind="provider_hosted",
        provider="openai",
        environment_ref="reviewed",
        expected_revision="v1",
        secret_refs=("GITHUB_TOKEN=secret:github.readonly",),
    )
    projected = project(
        "codex_agents",
        configuration(original),
        (),
        installation_id="local",
        environment=environment,
    )
    token = "readonly-test-secret-ref-12345"
    empty = WorkerEnvironmentSource({})
    broker = SecretBroker(
        environment=empty, store=WorkerEnvironmentSource({"github.readonly": token})
    )
    api = FakeAgentsApi()
    result = await CodexAgentsPreparer(api.client(), empty, broker=broker).sync(projected)
    assert result.credentials_written == ("GITHUB_TOKEN",)
    assert token in broker.registry.values()


def test_org_key_source_ref_is_rejected_before_resolution():
    import pytest

    from mission_control.domain.execution.bindings import EnvironmentBinding

    original = load_agents(SHIPPED_PACK)
    environment = EnvironmentBinding(
        kind="provider_hosted",
        provider="openai",
        environment_ref="reviewed",
        expected_revision="v1",
        secret_refs=("MC_GITHUB_READONLY_TOKEN=environment:OPENAI_API_KEY",),
    )
    with pytest.raises(ValueError, match="organization and publication"):
        project(
            "codex_agents",
            configuration(original),
            (),
            installation_id="local",
            environment=environment,
        )
