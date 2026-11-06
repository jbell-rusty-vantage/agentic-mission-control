"""HL-11: a `codex_agents` pack syncs once and is reused by digest afterwards (fake Agents API).

The live drill of the same claim waits on DECISIONS R27; these tests prove it against a stateful
fake that serves the pinned `openai` 3.29.0 request shapes.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from mission_control.adapters.openai_agents.client import AGENTS_API_ERRORS
from mission_control.adapters.openai_agents.pack import load_pack
from mission_control.adapters.openai_agents.prepare import (
    CodexAgentsPreparer,
    prewarm_idempotency_key,
)
from mission_control.adapters.remote_session.errors import AccessDenied, CapacityLimited
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.secrets.broker import SecretUnavailable
from tests.unit.openai_agents.support import API_KEY, SHIPPED_PACK, FakeAgentsApi, copy_pack

TOKEN = "github-readonly-test-value-7f3a"
WORKER = {"MC_AI_ENGINEER_GITHUB_READONLY_TOKEN": TOKEN}
LABELS = {"mc_run": "run1-HL-11"}


def _preparer(api: FakeAgentsApi, worker: dict[str, str] | None = None) -> CodexAgentsPreparer:
    environment = WorkerEnvironmentSource(WORKER if worker is None else worker)
    return CodexAgentsPreparer(api.client(), environment, labels=LABELS)


async def test_the_first_sync_creates_every_resource_with_the_pack_bodies() -> None:
    api, pack = FakeAgentsApi(), load_pack(SHIPPED_PACK)

    prepared = await _preparer(api).sync(pack)

    assert prepared.created == ("agent", "environment_template", "vault")
    assert prepared.credentials_written == ("GITHUB_TOKEN",)
    assert (prepared.task_queue, prepared.data_class) == ("mc-ai-engineer-lane-hosted", "internal")
    [agent] = api.agents.values()
    assert agent["model"] == "gpt-6-luna"
    assert agent["instructions"] == pack.instructions
    assert agent["multi_agent"] == {"enabled": False}
    assert agent["metadata"] == {"mc_app": "ai-engineer", "mc_pack": pack.digest, **LABELS}
    assert {tool["name"] for tool in agent["tools"]} == {
        "mc_signal",
        "mc_request_approval",
        "mc_upload_artifact",
    }
    [template] = api.templates.values()
    assert template["name"] == pack.template_name
    assert template["network"] == {
        "access": "restricted",
        "allowed_domains": ["api.github.com", "pypi.org", "files.pythonhosted.org"],
    }
    assert template["setup_commands"] == [
        {"command": "mkdir -p /workspace/outputs", "cwd": "/workspace"}
    ]
    assert [skill["name"] for skill in template["skills"]] == ["cited-findings"]
    [vault] = api.vaults.values()
    assert vault["metadata"] == {
        "mc_app": "ai-engineer",
        "mc_secret_set": pack.secret_set_digest,
        **LABELS,
    }
    [credential] = api.credentials[vault["id"]].values()
    assert credential["name"] == "GITHUB_TOKEN"
    assert credential["auth"] == {
        "type": "environment_variable",
        "secret_name": "GITHUB_TOKEN",
        "secret_value": TOKEN,
        "networking": {"type": "limited", "allowed_hosts": ["api.github.com"]},
    }
    assert credential["metadata"]["mc_run"] == "run1-HL-11"


async def test_every_request_carries_the_agents_beta_header_and_the_key() -> None:
    api = FakeAgentsApi()

    await _preparer(api).sync(load_pack(SHIPPED_PACK))

    assert api.requests
    for request in api.requests:
        assert request.headers["OpenAI-Beta"] == "agents=v1"
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"


async def test_a_second_sync_reuses_everything_by_digest_and_creates_nothing() -> None:
    api, pack = FakeAgentsApi(), load_pack(SHIPPED_PACK)
    first = await _preparer(api).sync(pack)
    api.requests.clear()

    second = await _preparer(api, worker={}).sync(load_pack(SHIPPED_PACK))

    assert second.created == ()
    assert second.credentials_written == ()
    assert [item.outcome for item in second.resources] == ["reused", "reused", "reused"]
    assert [item.id for item in second.resources] == [item.id for item in first.resources]
    assert [item.readback_digest for item in second.resources] == [
        item.readback_digest for item in first.resources
    ]
    assert api.creates() == []
    assert {request.method for request in api.requests} == {"GET"}


async def test_a_labelled_drill_reuses_an_unlabelled_sync() -> None:
    api, pack = FakeAgentsApi(), load_pack(SHIPPED_PACK)
    first = await CodexAgentsPreparer(api.client(), WorkerEnvironmentSource(WORKER)).sync(pack)

    second = await _preparer(api).sync(pack)

    assert second.created == ()
    assert second.agent.id == first.agent.id


async def test_a_skill_edit_makes_a_new_template_and_agent_but_keeps_the_vault(
    tmp_path: Path,
) -> None:
    api, directory = FakeAgentsApi(), copy_pack(tmp_path)
    first = await _preparer(api).sync(load_pack(directory))
    skill = directory / "skills" / "cited-findings" / "SKILL.md"
    skill.write_bytes(skill.read_bytes() + b"\n5. Keep it short.\n")

    second = await _preparer(api).sync(load_pack(directory))

    assert second.created == ("agent", "environment_template")
    assert first.vault is not None and second.vault is not None
    assert (second.vault.id, second.vault.outcome) == (first.vault.id, "reused")
    assert second.pack_digest != first.pack_digest
    assert len(api.agents) == 2 and len(api.templates) == 2 and len(api.vaults) == 1


async def test_reuse_finds_resources_beyond_the_first_page() -> None:
    api, pack = FakeAgentsApi(page_size=1), load_pack(SHIPPED_PACK)
    api.agents["agent_0900"] = {"id": "agent_0900", "metadata": {"mc_app": "other"}}
    api.templates["envtpl_0900"] = {"id": "envtpl_0900", "name": "someone-else"}
    first = await _preparer(api).sync(pack)

    second = await _preparer(api).sync(pack)

    assert second.created == ()
    assert second.agent.id == first.agent.id
    assert any(request.params.get("after") == "agent_0900" for request in api.requests)


async def test_a_missing_worker_variable_refuses_before_anything_is_written() -> None:
    api = FakeAgentsApi()

    with pytest.raises(SecretUnavailable) as refused:
        await _preparer(api, worker={}).sync(load_pack(SHIPPED_PACK))

    assert "MC_AI_ENGINEER_GITHUB_READONLY_TOKEN" in str(refused.value)
    assert api.creates() == []


async def test_only_the_credentials_a_vault_lacks_are_written() -> None:
    api, pack = FakeAgentsApi(), load_pack(SHIPPED_PACK)
    prepared = await _preparer(api).sync(pack)
    assert prepared.vault is not None
    api.credentials[prepared.vault.id].clear()

    again = await _preparer(api).sync(pack)

    assert again.created == ()
    assert again.credentials_written == ("GITHUB_TOKEN",)
    assert len(api.credentials[prepared.vault.id]) == 1


async def test_the_secret_value_travels_only_in_the_credential_create() -> None:
    api = FakeAgentsApi()

    prepared = await _preparer(api).sync(load_pack(SHIPPED_PACK))

    assert prepared.vault is not None
    carrying = [request for request in api.requests if TOKEN in json.dumps(request.body)]
    assert [(request.method, request.path) for request in carrying] == [
        ("POST", f"/vaults/{prepared.vault.id}/credentials")
    ]
    assert TOKEN not in repr(prepared)


async def test_prewarm_sends_a_stable_idempotency_key_and_a_retry_reattaches() -> None:
    api = FakeAgentsApi()
    preparer = _preparer(api)
    prepared = await preparer.sync(load_pack(SHIPPED_PACK))

    first = await preparer.prewarm(prepared, launch_key="run-7:unit-1:1")
    retried = await preparer.prewarm(prepared, launch_key="run-7:unit-1:1")
    other = await preparer.prewarm(prepared, launch_key="run-7:unit-2:1")

    assert retried == first and other.id != first.id
    assert len(api.environments) == 2
    prewarms = [request for request in api.requests if request.path == "/agents/environments"]
    assert prewarms[0].headers["Idempotency-Key"] == prewarm_idempotency_key(
        prepared.pack_digest, "run-7:unit-1:1"
    )
    assert prewarms[0].body == {
        "environment": {
            "type": "openai_hosted",
            "environment_template_id": prepared.template.id,
        },
        "vault_ids": prepared.vault_ids,
    }


async def test_the_session_environment_uses_the_prewarm_or_the_template() -> None:
    prepared = await _preparer(FakeAgentsApi()).sync(load_pack(SHIPPED_PACK))

    assert prepared.session_environment() == {
        "type": "openai_hosted",
        "environment_template_id": prepared.template.id,
        "container_size": "small",
    }
    assert prepared.session_environment("env_9") == {
        "type": "openai_hosted",
        "environment_id": "env_9",
    }


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401, json={"error": {"code": "invalid_api_key"}}), AccessDenied),
        (httpx.Response(403, json={}), AccessDenied),
        (httpx.Response(429, json={}, headers={"Retry-After": "7"}), CapacityLimited),
    ],
)
async def test_provider_refusals_are_typed_and_name_no_secret(
    response: httpx.Response, expected: type[Exception]
) -> None:
    api = FakeAgentsApi(fail={("GET", "/vaults"): response})

    with pytest.raises(expected) as refused:
        await _preparer(api).sync(load_pack(SHIPPED_PACK))

    assert API_KEY not in str(refused.value) and TOKEN not in str(refused.value)
    assert api.creates() == []
    assert expected in {rule.error for rule in AGENTS_API_ERRORS}


@pytest.mark.parametrize("labels", [{"mc_pack": "x"}, {"Bad-Key": "x"}, {"mc_run": "x" * 513}])
def test_labels_cannot_shadow_lookup_keys_or_break_metadata_limits(labels: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="reserved or malformed"):
        CodexAgentsPreparer(FakeAgentsApi().client(), WorkerEnvironmentSource({}), labels=labels)


def test_inline_skill_archives_decode_to_the_pack_bytes() -> None:
    pack = load_pack(SHIPPED_PACK)
    [skill] = pack.template_body()["skills"]

    data = base64.b64decode(skill["source"]["data"])
    assert data == pack.skills[0].archive()


async def test_created_resource_waits_for_exact_index_readback(monkeypatch) -> None:
    from mission_control.adapters.openai_agents.prepare import _visible_created

    created = {"id": "agent-1", "metadata": {"mc_app": "app", "mc_pack": "digest"}}
    calls = []

    async def listing():
        calls.append(1)
        if len(calls) >= 3:
            yield {**created, "updated_at": "later"}

    async def sleep(_):
        pass

    monkeypatch.setattr("mission_control.adapters.openai_agents.prepare.asyncio.sleep", sleep)
    assert (await _visible_created(listing, created))["id"] == "agent-1"
    assert len(calls) == 3


async def test_created_resource_rejects_changed_or_missing_index_readback(monkeypatch) -> None:
    from mission_control.adapters.openai_agents.prepare import _visible_created

    created = {"id": "agent-1", "metadata": {"mc_app": "app", "mc_pack": "digest"}}

    async def changed():
        yield {**created, "metadata": {"mc_pack": "other"}}

    async def missing():
        raise TimeoutError
        if False:
            yield {}

    async def sleep(_):
        pass

    monkeypatch.setattr("mission_control.adapters.openai_agents.prepare.asyncio.sleep", sleep)
    with pytest.raises(ValueError, match="readback changed"):
        await _visible_created(changed, created)
    with pytest.raises(ValueError, match="not visible"):
        await _visible_created(missing, created)
