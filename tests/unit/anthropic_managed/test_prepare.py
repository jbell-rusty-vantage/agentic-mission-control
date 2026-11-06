"""Prepare against the fake Managed Agents API: created once, reused after, keyed by digest."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from mission_control.adapters.anthropic_managed.client import AgentVersionConflict
from mission_control.adapters.anthropic_managed.pack import (
    PackRefused,
    RenderedPack,
    load_pack,
    render_pack,
)
from mission_control.adapters.anthropic_managed.prepare import (
    METADATA_DIGEST,
    METADATA_INSTALLATION,
    METADATA_PACK,
    METADATA_SCOPE,
    ClaudeManagedPrepare,
    PackSecretMissing,
    PreparedPack,
    PreparedVault,
)
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.secrets.broker import SecretBroker
from mission_control.application.secrets.delivery import DeliveryChannel, SecretUse
from tests.fixtures.managed_agents import FakeManagedAgentsApi

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
AI_ENGINEER_PACK: Final = REPO_ROOT / "deployments/hosted-packs/ai-engineer/claude_managed"
FIRECRAWL_VALUE: Final = "fc-test-value-0123456789"


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(AI_ENGINEER_PACK, target)
    return target


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("# Repo rules\n\nCite every source.\n")
    return root


def render(pack_dir: Path, repo: Path, *, ingress: str = "ingress.example.com") -> RenderedPack:
    return render_pack(
        load_pack(pack_dir), installation_id="local", repo_root=repo, ingress_host=ingress
    )


def vault_of(result: PreparedPack) -> PreparedVault:
    assert result.vault is not None
    return result.vault


def prepare(
    api: FakeManagedAgentsApi,
    *,
    secrets: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    installation_id: str = "local",
    broker: SecretBroker | None = None,
) -> ClaudeManagedPrepare:
    environment = {"FIRECRAWL_API_KEY": FIRECRAWL_VALUE} if secrets is None else secrets
    return ClaudeManagedPrepare(
        api.client(),
        broker or SecretBroker(environment=WorkerEnvironmentSource(environment)),
        installation_id=installation_id,
        labels=labels,
    )


async def test_a_first_sync_creates_every_resource_once(pack_dir: Path, repo: Path) -> None:
    api = FakeManagedAgentsApi()

    result = await prepare(api).sync(render(pack_dir, repo))

    assert [
        api.creates(path) for path in ("/v1/skills", "/v1/environments", "/v1/vaults", "/v1/agents")
    ] == [1, 1, 1, 1]
    assert api.creates(f"/v1/vaults/{vault_of(result).vault_id}/credentials") == 1
    assert {result.agent.action, result.environment.action, vault_of(result).action} == {"created"}
    assert [skill.action for skill in result.skills] == ["created"]
    assert set(result.created()) == {
        result.skills[0].skill_id,
        result.environment.environment_id,
        vault_of(result).vault_id,
        result.agent.agent_id,
    }
    assert result.agent.version == 1 and result.task_queue == "mc-ai-engineer-lane-hosted"


async def test_a_second_sync_reuses_everything_and_only_refreshes_values(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()
    first = await prepare(api).sync(render(pack_dir, repo))
    writes_before = len(api.writes())

    second = await prepare(api).sync(render(pack_dir, repo))

    assert second.created() == ()
    assert second.agent.action == second.environment.action == "reused"
    assert second.vault is not None and second.vault.action == "reused"
    assert [skill.action for skill in second.skills] == ["reused"]
    new_writes = api.writes()[writes_before:]
    assert [(w.method, w.path) for w in new_writes] == [
        (
            "POST",
            f"/v1/vaults/{vault_of(first).vault_id}/credentials/"
            f"{vault_of(first).credentials[0].credential_id}",
        )
    ]
    assert second.vault.credentials[0].action == "refreshed"
    assert second.session_fields() == first.session_fields()
    assert second.projection_digests() == first.projection_digests()


async def test_sync_metadata_keys_every_resource_by_its_digest(pack_dir: Path, repo: Path) -> None:
    api = FakeManagedAgentsApi()
    rendered = render(pack_dir, repo)

    result = await prepare(api).sync(rendered)

    agent = api.agents[result.agent.agent_id]
    environment = api.environments[result.environment.environment_id]
    vault = api.vaults[vault_of(result).vault_id]
    for resource, digest in (
        (agent, rendered.materialization_digest),
        (environment, rendered.kit_digest),
        (vault, rendered.secret_set_digest),
    ):
        assert resource["metadata"][METADATA_DIGEST] == digest
        assert resource["metadata"][METADATA_PACK] == "ai-engineer/knowledge"
        assert resource["metadata"][METADATA_INSTALLATION] == "local"
        assert resource["metadata"][METADATA_SCOPE].startswith("sha256:")
    assert agent["metadata"]["application"] == "ai-engineer"
    assert environment["name"] == rendered.environment_name
    assert environment["config"]["networking"]["type"] == "limited"
    assert agent["skills"] == [
        {
            "type": "custom",
            "skill_id": result.skills[0].skill_id,
            "version": result.skills[0].version_id,
        }
    ]
    assert agent["system"] == rendered.system


async def test_changed_repository_rules_update_the_agent_under_its_version(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()
    first = await prepare(api).sync(render(pack_dir, repo))
    (repo / "AGENTS.md").write_text("# Repo rules\n\nCite every source twice.\n")

    second = await prepare(api).sync(render(pack_dir, repo))

    assert second.agent.agent_id == first.agent.agent_id
    assert (second.agent.action, second.agent.version) == ("updated", 2)
    assert second.agent.materialization_digest != first.agent.materialization_digest
    assert second.agent.readback_digest != first.agent.readback_digest
    update = next(
        r
        for r in api.requests
        if r.path == f"/v1/agents/{first.agent.agent_id}" and r.method == "POST"
    )
    assert update.body["version"] == 1
    assert second.environment.action == "reused" and api.creates("/v1/agents") == 1


async def test_a_new_kit_digest_is_a_new_environment(pack_dir: Path, repo: Path) -> None:
    api = FakeManagedAgentsApi()
    first = await prepare(api).sync(render(pack_dir, repo))

    second = await prepare(api).sync(render(pack_dir, repo, ingress="ingress2.example.com"))

    assert second.environment.action == "created"
    assert second.environment.environment_id != first.environment.environment_id
    assert first.environment.environment_id in api.environments  # never mutated or deleted
    assert second.agent.action == "reused"


async def test_a_changed_skill_is_a_new_skill_and_a_new_agent_version(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()
    first = await prepare(api).sync(render(pack_dir, repo))
    with (pack_dir / "skills/mission-control-signals/SKILL.md").open(
        "a", encoding="utf-8"
    ) as skill:
        skill.write("\n5. Keep outputs small.\n")

    second = await prepare(api).sync(render(pack_dir, repo))

    assert second.skills[0].action == "created"
    assert second.skills[0].skill_id != first.skills[0].skill_id
    assert (second.agent.action, second.agent.version) == ("updated", 2)
    assert api.agents[first.agent.agent_id]["skills"][0]["skill_id"] == second.skills[0].skill_id


async def test_a_skill_recreated_under_the_same_digest_repins_the_agent(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()
    first = await prepare(api).sync(render(pack_dir, repo))
    del api.skills[first.skills[0].skill_id]

    second = await prepare(api).sync(render(pack_dir, repo))

    assert second.skills[0].action == "created"
    assert second.agent.action == "updated"


async def test_a_concurrent_agent_writer_is_a_version_conflict(pack_dir: Path, repo: Path) -> None:
    api = FakeManagedAgentsApi()
    first = await prepare(api).sync(render(pack_dir, repo))
    (repo / "AGENTS.md").write_text("# Repo rules\n\nChanged.\n")
    rendered = render(pack_dir, repo)
    sync = prepare(api)
    real_list = api._agents

    def racing(method, rest, body, request):  # type: ignore[no-untyped-def]
        response = real_list(method, rest, body, request)
        if method == "GET" and not rest:
            api.agents[first.agent.agent_id]["version"] += 1  # another writer lands meanwhile
        return response

    api._agents = racing  # type: ignore[method-assign]

    with pytest.raises(AgentVersionConflict):
        await sync.sync(rendered)


async def test_labels_scope_resources_so_a_drill_never_reuses_production(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()
    production = await prepare(api).sync(render(pack_dir, repo))

    drill = await prepare(api, labels={"mc_run": "run1-HL-07"}).sync(render(pack_dir, repo))

    assert set(drill.created()).isdisjoint(production.created())
    assert len(drill.created()) == 4
    assert api.agents[drill.agent.agent_id]["metadata"]["mc_run"] == "run1-HL-07"
    assert drill.skills[0].display_name.startswith("mc-run1-HL-07-mission-control-signals-")
    assert drill.environment.name.startswith("mc-run1-HL-07-ai-engineer-knowledge-")
    assert api.agents[drill.agent.agent_id]["name"] == "mc-run1-HL-07-ai-engineer-knowledge"
    again = await prepare(api, labels={"mc_run": "run1-HL-07"}).sync(render(pack_dir, repo))
    assert again.created() == ()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"mc_run": "run1-HL-07"}, None),
        ({"mc_run": "run1-HL-07", "mc_unit": "a"}, {"mc_run": "run1-HL-07"}),
    ],
)
async def test_a_scope_never_adopts_a_scope_whose_labels_include_its_own(
    pack_dir: Path,
    repo: Path,
    first: Mapping[str, str],
    second: Mapping[str, str] | None,
) -> None:
    api = FakeManagedAgentsApi()
    drill = await prepare(api, labels=first).sync(render(pack_dir, repo))
    drill_agent = dict(api.agents[drill.agent.agent_id])

    other = await prepare(api, labels=second).sync(render(pack_dir, repo))

    assert len(other.created()) == 4
    assert set(other.created()).isdisjoint(drill.created())
    assert api.agents[drill.agent.agent_id] == drill_agent  # never renamed, re-pinned or relabelled


async def test_skills_are_scoped_to_their_installation(pack_dir: Path, repo: Path) -> None:
    api = FakeManagedAgentsApi()
    local = await prepare(api).sync(render(pack_dir, repo))

    hosted = await prepare(api, installation_id="hosted").sync(render(pack_dir, repo))

    assert hosted.skills[0].action == "created"
    assert hosted.skills[0].skill_id != local.skills[0].skill_id
    assert hosted.skills[0].display_name != local.skills[0].display_name


async def test_duplicates_from_a_lost_create_resolve_to_the_oldest(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()
    first = await prepare(api).sync(render(pack_dir, repo))
    client = api.client()
    duplicate = dict(api.environments[first.environment.environment_id])
    await client.create_environment(
        {
            "name": duplicate["name"],
            "config": duplicate["config"],
            "metadata": duplicate["metadata"],
        }
    )

    second = await prepare(api).sync(render(pack_dir, repo))

    assert second.environment.environment_id == first.environment.environment_id


async def test_missing_credential_values_refuse_before_any_provider_call(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()

    with pytest.raises(PackSecretMissing) as missing:
        await prepare(api, secrets={}).sync(render(pack_dir, repo))

    assert missing.value.names == ("FIRECRAWL_API_KEY",)
    assert api.requests == []


async def test_a_credential_value_in_the_payload_is_refused(pack_dir: Path, repo: Path) -> None:
    api = FakeManagedAgentsApi()
    (repo / "AGENTS.md").write_text(f"# Repo rules\n\nThe key is {FIRECRAWL_VALUE}.\n")

    with pytest.raises(PackRefused, match="credential value"):
        await prepare(api).sync(render(pack_dir, repo))

    assert api.requests == []


async def test_values_reach_the_vault_and_never_the_receipt(pack_dir: Path, repo: Path) -> None:
    api = FakeManagedAgentsApi()
    broker = SecretBroker(
        environment=WorkerEnvironmentSource({"FIRECRAWL_API_KEY": FIRECRAWL_VALUE})
    )

    result = await prepare(api, broker=broker).sync(render(pack_dir, repo))

    assert result.vault is not None
    assert result.vault.secret_uses == (
        SecretUse(
            "FIRECRAWL_API_KEY",
            DeliveryChannel.PROVIDER_VAULT,
            f"anthropic:vault:{result.vault.vault_id}",
        ),
    )
    assert FIRECRAWL_VALUE in broker.registry.values()  # frames, logs and receipts redact it
    assert api.secret_values == {(result.vault.vault_id, "FIRECRAWL_API_KEY"): FIRECRAWL_VALUE}
    credential = next(iter(api.credentials[result.vault.vault_id].values()))
    assert credential["auth"] == {
        "type": "environment_variable",
        "secret_name": "FIRECRAWL_API_KEY",
        "networking": {"type": "limited", "allowed_hosts": ["api.firecrawl.dev"]},
    }
    assert FIRECRAWL_VALUE not in result.model_dump_json()
    rotated = await prepare(api, secrets={"FIRECRAWL_API_KEY": "fc-rotated-value-9876"}).sync(
        render(pack_dir, repo)
    )
    assert (
        api.secret_values[(vault_of(rotated).vault_id, "FIRECRAWL_API_KEY")]
        == "fc-rotated-value-9876"
    )


async def test_a_pack_without_credentials_has_no_vault(pack_dir: Path, repo: Path) -> None:
    (pack_dir / "vault.yaml").write_text("credentials: []\n")
    api = FakeManagedAgentsApi()

    result = await prepare(api, secrets={}).sync(render(pack_dir, repo))

    assert result.vault is None and api.vaults == {}
    assert result.session_fields()["vault_ids"] == []


async def test_the_receipt_round_trips_and_names_the_session_pins(
    pack_dir: Path, repo: Path
) -> None:
    api = FakeManagedAgentsApi()
    result = await prepare(api).sync(render(pack_dir, repo))

    assert PreparedPack.model_validate_json(result.model_dump_json()) == result
    assert result.session_fields() == {
        "agent": {"type": "agent", "id": result.agent.agent_id, "version": 1},
        "environment_id": result.environment.environment_id,
        "vault_ids": [vault_of(result).vault_id],
    }
    assert set(result.projection_digests()) == {
        "materialization_digest",
        "agent_readback_digest",
        "kit_digest",
        "environment_readback_digest",
        "secret_set_digest",
        "vault_readback_digest",
    }


def test_labels_cannot_set_the_reserved_keys() -> None:
    with pytest.raises(ValueError, match="mc_pack"):
        prepare(FakeManagedAgentsApi(), labels={"mc_pack": "x"})
    with pytest.raises(ValueError, match="mc_scope"):
        prepare(FakeManagedAgentsApi(), labels={"mc_scope": "x"})


async def test_agent_metadata_beyond_the_provider_limit_is_refused(
    pack_dir: Path, repo: Path
) -> None:
    agent_yaml = pack_dir / "agent.yaml"
    # application + 12 keys + mc_installation, mc_scope, mc_pack and mc_digest = 17 pairs
    extra = "".join(f"  key{index}: value\n" for index in range(12))
    agent_yaml.write_text(
        agent_yaml.read_text(encoding="utf-8").replace("metadata:\n", f"metadata:\n{extra}"),
        encoding="utf-8",
    )
    api = FakeManagedAgentsApi()

    with pytest.raises(PackRefused, match="16 pairs"):
        await prepare(api).sync(render(pack_dir, repo))

    assert api.requests == []
