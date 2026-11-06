"""MO-13: Cursor environments REST adapter, `sync`/`bind` and the committed-file check.

Everything runs against the FIXTURE environments API (`tests/fixtures/cursor_environments.py`,
the shapes the MO-13 drill observed). SPEC-01 section 7 and section 10 (`cursor_cloud` with
`sync`): an environment `mc-<kit>-<digest8>` is created once and a second mission with the same
kit and repository reuses it without an update, while another repository gets its own; secrets
are synced by name; a foreign committed `.cursor/environment.json` (a marker over content that
is not the kit's rendering included) is refused unless the manifest binds it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from pydantic import SecretStr

from mission_control.adapters.cursor.environments import (
    ENVIRONMENT_FILE,
    CursorEnvironmentNotFound,
    CursorEnvironmentsClient,
    EnvironmentNameConflict,
    render_environment_json,
)
from mission_control.adapters.cursor.secrets import CursorSecretsClient
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.environments.provider_environments import (
    PROVIDER_ENVIRONMENT_DRIFT,
    PROVIDER_ENVIRONMENT_REFUSED,
    AppliedEnvironment,
    EnvironmentFileCheck,
    EnvironmentFileState,
    ProviderEnvironmentRefused,
    ProviderEnvironmentService,
    check_environment_file,
    config_digest,
    synced_environment_name,
)
from mission_control.application.secrets.broker import SecretBroker
from mission_control.application.secrets.delivery import DeliveryChannel
from mission_control.domain.authoring.environment_kits import EnvironmentKitManifest
from tests.fixtures.cursor_environments import API_KEY, FakeEnvironmentsApi, cursor_environments

REPO = "https://github.com/acme/repo"
OTHER_REPO = "https://github.com/acme/other"
KIT_ID = "envkit.python-uv"
MARKER = "mc:envkit.python-uv@1"
FIRECRAWL = "mo13-firecrawl-value-91c2"
TAVILY = "mo13-tavily-value-4b7e"
SECRETS = (
    "FIRECRAWL_API_KEY=secret:firecrawl/api_key",
    "TAVILY_API_KEY=environment:TAVILY_API_KEY;agent",
    "MC_SIGNAL_TOKEN=mint:signal_token;agent",
)
INSTALL = b"#!/usr/bin/env bash\nset -euo pipefail\nuv python install 3.12\n"


class DictSource:
    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = dict(values)

    async def read(self, key: str) -> str | None:
        return self.values.get(key)


def kit(**changes: object) -> EnvironmentKitManifest:
    document: dict[str, object] = {
        "id": KIT_ID,
        "version": "1",
        "title": "Python with uv",
        "description": "Python 3.12 projects managed by uv.",
        "toolchains": {"python": "3.12", "uv": "0.12"},
        "base": {"install": "base/install.sh"},
        "requires": {"secrets": ["FIRECRAWL_API_KEY"], "egress": ["pypi.org"]},
        "host_support": {"local": "full", "cursor_cloud": "full"},
    }
    document.update(changes)
    return EnvironmentKitManifest.model_validate(document)


EGRESS = {"egressMode": "network_settings_only", "egressAllowlist": ["pypi.org"]}
CONFIG = render_environment_json(kit(), install=INSTALL, egress=EGRESS)


def broker(**values: str) -> SecretBroker:
    return SecretBroker(
        environment=WorkerEnvironmentSource({"TAVILY_API_KEY": values.get("tavily", TAVILY)}),
        store=DictSource({"firecrawl/api_key": values.get("firecrawl", FIRECRAWL)}),
    )


def service(api: FakeEnvironmentsApi, **values: str) -> ProviderEnvironmentService:
    return ProviderEnvironmentService(cursor_environments(api), broker=broker(**values))


ABSENT = check_environment_file(ENVIRONMENT_FILE, None, expected_marker=MARKER)


async def sync(api: FakeEnvironmentsApi, repo: str = REPO, **values: str) -> AppliedEnvironment:
    return await service(api, **values).apply(
        strategy="sync",
        file=ABSENT,
        kit_id=KIT_ID,
        config=CONFIG,
        secret_refs=SECRETS,
        repositories=(repo,),
    )


# --- the REST adapter ------------------------------------------------------------------------


async def test_environment_crud_reads_the_configuration_back_from_the_version_history() -> None:
    api = FakeEnvironmentsApi()
    client = CursorEnvironmentsClient(SecretStr(API_KEY), transport=api.transport())
    created = await client.create(name="mc-probe", environment_json=CONFIG, repositories=(REPO,))
    environment_id = created["id"]
    assert "environmentJson" not in await client.get(environment_id)

    with pytest.raises(EnvironmentNameConflict) as conflict:
        await client.create(name="mc-probe", environment_json=CONFIG)
    assert conflict.value.environment_id == environment_id

    await client.update(environment_id, environment_json='{"start":"true"}')
    (current, earlier) = await client.history(environment_id)
    assert (current["current"], current["kind"], current["source"]) == (True, "updated", "api")
    assert earlier["environmentJson"] == CONFIG and not earlier["current"]

    await client.create(name="mc-other", environment_json=CONFIG)
    assert [item["name"] for item in await client.list_environments()] == ["mc-probe", "mc-other"]

    await client.delete(environment_id)
    with pytest.raises(CursorEnvironmentNotFound):
        await client.get(environment_id)


async def test_secrets_put_list_and_delete_by_name() -> None:
    api = FakeEnvironmentsApi()
    environments = cursor_environments(api)
    environment = await environments.create("mc-probe", CONFIG, repositories=())
    store = environments.secrets(environment.environment_id)
    await store.put("MC_PROBE", "probe-value")
    assert await store.names() == {"MC_PROBE"}
    assert await store.delete("MC_PROBE") is True
    assert await store.delete("MC_PROBE") is False, "secret_not_found is already deleted"
    assert await store.names() == frozenset()


async def test_an_inaccessible_repository_is_a_named_refusal() -> None:
    api = FakeEnvironmentsApi(inaccessible={REPO})
    with pytest.raises(ProviderEnvironmentRefused, match="Git integration") as refused:
        await sync(api)
    assert refused.value.code == PROVIDER_ENVIRONMENT_REFUSED
    assert api.environments == {}


# --- sync ------------------------------------------------------------------------------------


async def test_sync_creates_the_kit_environment_once_and_a_second_mission_reuses_it() -> None:
    api = FakeEnvironmentsApi()
    first = await sync(api)
    assert first.action == "created"
    assert first.environment is not None
    name = synced_environment_name(KIT_ID, config_digest(CONFIG) or "", (REPO,))
    assert first.environment.name == name and name.startswith(f"mc-{KIT_ID}-")
    assert len(name) == len(f"mc-{KIT_ID}-") + 8
    assert first.environment.config_digest == config_digest(CONFIG)
    assert first.environment.version_id is not None and first.environment.source == "api"
    # Secret names synced; the per-run minted credential never enters a shared environment.
    stored = api.secrets[first.environment.environment_id]
    assert stored == {"FIRECRAWL_API_KEY": FIRECRAWL, "TAVILY_API_KEY": TAVILY}
    assert first.secrets_written == ("FIRECRAWL_API_KEY", "TAVILY_API_KEY")
    assert {use.channel for use in first.secret_uses} == {DeliveryChannel.CURSOR_ENVIRONMENT}
    assert first.omitted_secrets == ("MC_SIGNAL_TOKEN",)
    details = first.details()
    assert details["provider_environment"] == "sync:created"
    assert details["provider_environment_secrets"] == "FIRECRAWL_API_KEY,TAVILY_API_KEY"
    assert details["provider_environment_secrets_written"] == "FIRECRAWL_API_KEY,TAVILY_API_KEY"
    assert details["provider_environment_secrets_omitted"] == "MC_SIGNAL_TOKEN"
    assert FIRECRAWL not in json.dumps(details)

    writes = len(api.writes())
    second = await sync(api)
    assert second.action == "reused"
    assert second.environment == first.environment
    assert second.secrets_written == ()
    assert "provider_environment_secrets_written" not in second.details()
    # Only the refused create: no PATCH and no secret PUT.
    assert api.writes()[writes:] == [("POST", "/v1/environments")]
    assert len(api.environments) == 1


async def test_another_repository_with_the_same_kit_gets_its_own_environment() -> None:
    """Cursor resolves an environment from the repositories it covers, so one created for a
    repository never stands in for another: the target repository is part of the name."""

    api = FakeEnvironmentsApi()
    first = await sync(api)
    other = await sync(api, repo=OTHER_REPO)
    assert (first.action, other.action) == ("created", "created")
    assert first.environment is not None and other.environment is not None
    assert first.environment.name != other.environment.name
    assert first.environment.repositories == (REPO,)
    assert other.environment.repositories == (OTHER_REPO,)
    # The same repository spelled with `.git` and a trailing slash is the same environment.
    again = await sync(api, repo=REPO.upper() + ".git/")
    assert (again.action, again.environment) == ("reused", first.environment)
    assert sorted(item["repos"][0]["url"] for item in api.environments.values()) == sorted(
        (REPO, OTHER_REPO)
    )


async def test_a_reused_environment_that_no_longer_covers_the_repository_is_drift() -> None:
    api = FakeEnvironmentsApi()
    first = await sync(api)
    assert first.environment is not None
    api.environments[first.environment.environment_id]["repos"] = [{"url": OTHER_REPO}]
    writes = len(api.writes())
    with pytest.raises(ProviderEnvironmentRefused, match="does not cover") as drift:
        await sync(api)
    assert drift.value.code == PROVIDER_ENVIRONMENT_DRIFT
    assert api.writes()[writes:] == [("POST", "/v1/environments")], "no PATCH, no secret PUT"


async def test_a_reused_environment_receives_only_the_names_it_lacks() -> None:
    api = FakeEnvironmentsApi()
    first = await sync(api)
    assert first.environment is not None
    environment_id = first.environment.environment_id
    del api.secrets[environment_id]["TAVILY_API_KEY"]
    again = await sync(api, firecrawl="rotated-value-not-written", tavily="tavily-again")
    assert again.action == "reused"
    assert again.secrets_written == ("TAVILY_API_KEY",)
    assert api.secrets[environment_id] == {
        "FIRECRAWL_API_KEY": FIRECRAWL,
        "TAVILY_API_KEY": "tavily-again",
    }


async def test_a_dashboard_edit_is_replaced_and_every_value_written_again() -> None:
    api = FakeEnvironmentsApi()
    first = await sync(api)
    assert first.environment is not None
    environment_id = first.environment.environment_id
    api.dashboard_edit(environment_id, '{"start":"echo edited"}')
    repaired = await sync(api, firecrawl="rotated-firecrawl")
    assert repaired.action == "updated"
    assert repaired.environment is not None
    assert repaired.environment.config_digest == config_digest(CONFIG)
    assert repaired.environment.version_id != first.environment.version_id
    assert ("PATCH", f"/v1/environments/{environment_id}") in api.writes()
    assert api.secrets[environment_id]["FIRECRAWL_API_KEY"] == "rotated-firecrawl"


async def test_a_configuration_that_reads_back_differently_is_drift() -> None:
    api = FakeEnvironmentsApi(rewrite={CONFIG: '{"start":"rewritten"}'})
    with pytest.raises(ProviderEnvironmentRefused) as drift:
        await sync(api)
    assert drift.value.code == PROVIDER_ENVIRONMENT_DRIFT


async def test_a_missing_required_secret_fails_before_anything_is_written() -> None:
    api = FakeEnvironmentsApi()
    bare = ProviderEnvironmentService(
        cursor_environments(api),
        broker=SecretBroker(environment=WorkerEnvironmentSource({}), store=DictSource({})),
    )
    with pytest.raises(LookupError, match="FIRECRAWL_API_KEY"):
        await bare.apply(
            strategy="sync",
            file=ABSENT,
            kit_id=KIT_ID,
            config=CONFIG,
            secret_refs=SECRETS[:1],
        )
    assert api.requests == [], "nothing reaches the provider"


# --- the committed file and bind --------------------------------------------------------------


def owned_file(content: bytes) -> EnvironmentFileCheck:
    return check_environment_file(
        ENVIRONMENT_FILE, content, expected_marker=MARKER, expected_digest=config_digest(CONFIG)
    )


def test_the_committed_file_is_mc_owned_foreign_or_absent() -> None:
    # The kit's rendering, committed with other spacing and key order, is mc-owned, and its
    # digest is the one a provider read-back of the same configuration has.
    committed = json.dumps(json.loads(CONFIG), indent=2).encode()
    owned = owned_file(committed)
    assert owned.state == EnvironmentFileState.MC_OWNED and owned.marker == MARKER
    assert owned.digest == config_digest(CONFIG)

    # The marker over stale or hand-edited content is not the kit's base layer.
    stale = owned_file(
        json.dumps({"name": MARKER, "install": "echo stale", "egressMode": "allow_all"}).encode()
    )
    assert stale.state == EnvironmentFileState.FOREIGN and stale.marker == MARKER
    assert "is not the kit's rendering" in stale.reason
    marker_only = check_environment_file(ENVIRONMENT_FILE, committed, expected_marker=MARKER)
    assert marker_only.state == EnvironmentFileState.FOREIGN, "no rendering, nothing mc-owned"

    foreign = check_environment_file(
        ENVIRONMENT_FILE, b'{"name": "Biotech backend"}', expected_marker=MARKER
    )
    assert foreign.state == EnvironmentFileState.FOREIGN
    assert "no Mission Control kit marker" in foreign.reason
    other_kit = check_environment_file(
        ENVIRONMENT_FILE, b'{"name": "mc:envkit/mission-control-dev@1"}', expected_marker=MARKER
    )
    assert other_kit.state == EnvironmentFileState.FOREIGN
    assert "marks mc:envkit/mission-control-dev@1" in other_kit.reason
    unreadable = check_environment_file(ENVIRONMENT_FILE, b"// note\n{", expected_marker=MARKER)
    assert unreadable.state == EnvironmentFileState.FOREIGN

    assert ABSENT.state == EnvironmentFileState.ABSENT


async def test_a_foreign_file_is_refused_unless_the_manifest_binds_it() -> None:
    api = FakeEnvironmentsApi()
    foreign = check_environment_file(
        ENVIRONMENT_FILE, b'{"name": "Biotech backend"}', expected_marker=MARKER
    )
    for strategy in ("sync", "generate"):
        with pytest.raises(ProviderEnvironmentRefused, match="overrides every saved environment"):
            await service(api).apply(strategy=strategy, file=foreign, kit_id=KIT_ID, config=CONFIG)
    with pytest.raises(ProviderEnvironmentRefused):
        await service(api).apply(strategy="bind", file=foreign, ref="mc-other")
    bound = await service(api).apply(strategy="bind", file=foreign, ref=ENVIRONMENT_FILE)
    assert (bound.action, bound.environment) == ("bound", None)
    assert api.requests == [], "nothing reaches the provider for a committed file"


async def test_an_mc_owned_file_is_the_base_layer_and_shadows_saved_environments() -> None:
    api = FakeEnvironmentsApi()
    owned = owned_file(CONFIG.encode())
    applied = await service(api).apply(
        strategy="sync", file=owned, kit_id=KIT_ID, config=CONFIG, secret_refs=SECRETS
    )
    assert (applied.action, applied.environment) == ("repo_file", None)
    with pytest.raises(ProviderEnvironmentRefused, match="bind .cursor/environment.json instead"):
        await service(api).apply(strategy="bind", file=owned, ref="mc-saved")
    assert api.requests == []


async def test_bind_reads_the_named_environment_and_writes_nothing() -> None:
    api = FakeEnvironmentsApi()
    created = await sync(api)
    assert created.environment is not None
    writes = len(api.writes())
    bound = await service(api).apply(strategy="bind", file=ABSENT, ref=created.environment.name)
    assert bound.action == "bound"
    assert bound.environment == created.environment
    assert len(api.writes()) == writes
    with pytest.raises(ProviderEnvironmentRefused, match="no provider environment is named"):
        await service(api).apply(strategy="bind", file=ABSENT, ref="mc-missing")
    generated = await service(api).apply(strategy="generate", file=ABSENT)
    assert (generated.action, generated.environment) == ("generated", None)


# --- the rendered base layer ------------------------------------------------------------------


def test_the_rendered_environment_is_deterministic_and_names_only_variables() -> None:
    config = json.loads(CONFIG)
    assert config["name"] == MARKER
    assert config["start"] == (
        "if [ -f .mission/setup/run ]; then bash .mission/setup/run --phase start; fi"
    )
    assert config["agentCanUpdateSnapshot"] is False
    assert config["install"].startswith("bash -c '#!/usr/bin/env bash")
    assert config["egressMode"] == "network_settings_only"
    assert render_environment_json(kit(), install=INSTALL, egress=EGRESS) == CONFIG
    widened = render_environment_json(kit(), install=INSTALL, egress={"egressMode": "allow_all"})
    assert synced_environment_name(
        KIT_ID, config_digest(widened) or "", (REPO,)
    ) != synced_environment_name(KIT_ID, config_digest(CONFIG) or "", (REPO,))
    with pytest.raises(ProviderEnvironmentRefused, match="base services"):
        render_environment_json(
            kit(base={"services": [{"name": "pg", "start": "s.sh", "health": "h.sh"}]}),
            install=None,
        )


async def test_the_secrets_client_refuses_reserved_names_before_any_request() -> None:
    api = FakeEnvironmentsApi()
    client = CursorSecretsClient(SecretStr(API_KEY), transport=api.transport())
    with pytest.raises(ValueError, match="reserves"):
        await client.put_environment_secret("env", "HTTPS_PROXY", "x")
    assert api.requests == []
