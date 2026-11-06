"""The Managed Agents control-plane client: wire shapes and the typed error set."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from mission_control.adapters.anthropic_managed.client import (
    AgentVersionConflict,
    ManagedAgentsClient,
    ManagedAgentsError,
)
from mission_control.adapters.remote_session.errors import (
    AccessDenied,
    CapacityLimited,
    SessionNotFound,
)
from tests.fixtures.managed_agents import API_KEY, FakeManagedAgentsApi


async def test_managed_agents_paths_carry_the_beta_and_skills_do_not() -> None:
    api = FakeManagedAgentsApi()
    client = api.client()
    await client.create_environment({"name": "e", "config": {"type": "cloud"}})
    await client.create_skill("mc-s-0123", [("s/SKILL.md", b"---\nname: s\n---\n")])
    await client.list_skills()

    environment, skill, listing = api.requests
    assert environment.headers["anthropic-beta"] == "managed-agents-2026-04-01"
    assert environment.beta_query and environment.headers["x-api-key"] == API_KEY
    assert environment.headers["anthropic-version"] == "2023-06-01"
    assert "anthropic-beta" not in skill.headers and not skill.beta_query
    assert "anthropic-beta" not in listing.headers


async def test_skill_upload_is_multipart_files_under_one_directory() -> None:
    api = FakeManagedAgentsApi()
    created = await api.client().create_skill(
        "mc-signals-0123", [("signals/SKILL.md", b"# one\n"), ("signals/ref/notes.txt", b"two\n")]
    )

    assert created["display_name"] == "mc-signals-0123"
    assert api.skill_files[created["id"]] == [
        ("signals/SKILL.md", b"# one\n"),
        ("signals/ref/notes.txt", b"two\n"),
    ]


async def test_listings_follow_next_page_to_the_end() -> None:
    api = FakeManagedAgentsApi()
    client = api.client()
    for index in range(5):
        await client.create_vault({"display_name": f"v{index}"})

    vaults = await client.list_vaults()

    assert [vault["display_name"] for vault in vaults] == [f"v{index}" for index in range(5)]
    pages = [r for r in api.requests if r.method == "GET" and r.path == "/v1/vaults"]
    assert len(pages) == 3


async def test_a_stale_agent_version_is_a_version_conflict() -> None:
    api = FakeManagedAgentsApi()
    client = api.client()
    agent = await client.create_agent({"name": "a", "model": "claude-sonnet-5-5", "system": "x"})
    await client.update_agent(agent["id"], {"system": "y", "version": 1})

    with pytest.raises(AgentVersionConflict):
        await client.update_agent(agent["id"], {"system": "z", "version": 1})


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AccessDenied),
        (403, AccessDenied),
        (404, SessionNotFound),
        (429, CapacityLimited),
        (409, ManagedAgentsError),
        (500, ManagedAgentsError),
    ],
)
async def test_failures_map_to_the_typed_error_set(status: int, error: type[Exception]) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"Retry-After": "7"},
            json={"type": "error", "error": {"type": "x", "message": f"{API_KEY} leaked?"}},
        )

    client = ManagedAgentsClient(SecretStr(API_KEY), transport=httpx.MockTransport(refuse))

    with pytest.raises(error) as raised:
        await client.create_environment({"name": "e"})

    assert API_KEY not in str(raised.value)
    if isinstance(raised.value, CapacityLimited):
        assert raised.value.retry_after_s == 7


async def test_session_files_keep_managed_scope_beta_and_follow_files_cursor() -> None:
    seen = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert set(request.headers["anthropic-beta"].split(",")) == {
            "files-api-2025-04-14",
            "managed-agents-2026-04-01",
        }
        if request.url.path == "/v1/files":
            assert request.url.params["scope_id"] == "sesn_scope"
            if "after_id" not in request.url.params:
                return httpx.Response(
                    200,
                    json={"data": [{"id": "file_one"}], "has_more": True, "last_id": "file_one"},
                )
            assert request.url.params["after_id"] == "file_one"
            return httpx.Response(200, json={"data": [{"id": "file_two"}], "has_more": False})
        return httpx.Response(200, content=b"bundle" if request.method == "GET" else b"")

    client = ManagedAgentsClient(SecretStr(API_KEY), transport=httpx.MockTransport(serve))
    try:
        assert [item["id"] for item in await client.session_files("sesn_scope")] == [
            "file_one",
            "file_two",
        ]
        assert await client.download_file("file_two") == b"bundle"
        await client.delete_file("file_two")
        assert len(seen) == 4
    finally:
        await client.aclose()
