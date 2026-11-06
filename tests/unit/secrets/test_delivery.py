"""MO-11: per-lane delivery channels move values to exactly one place and record names only.

- provider stores: provider-held names are verified, resolved values are written through the
  store's API (Cursor environment and team secrets over a `MockTransport`; Anthropic and OpenAI
  vault credentials through fakes of the pinned SDKs' credentials resources);
- Cursor launch `envVars`: Cursor's documented limits refuse before the create;
- the process environment of local children: the binding's declarations for the agent phase,
  provider-held secrets refused.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from mission_control.adapters.cursor.secrets import (
    CursorEnvironmentSecrets,
    CursorSecretRefused,
    CursorSecretsClient,
    CursorTeamSecrets,
    launch_env_vars,
)
from mission_control.adapters.secrets.minted import InMemoryMintedCredentialStore
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.adapters.secrets.vaults import ProviderVaultStore
from mission_control.application.secrets.broker import (
    ResolvedSecrets,
    SecretBroker,
    SecretUnavailable,
)
from mission_control.application.secrets.delivery import (
    DeliveryChannel,
    ProcessSecretDelivery,
    ProviderHeldSecretMissing,
    SecretUse,
    deliver_to_store,
)
from mission_control.application.secrets.minting import CredentialMinter
from mission_control.domain.execution.bindings import EnvironmentBinding

VALUE = "fc-delivered-value-0001"


# --- Cursor environment and team secrets ----------------------------------------------------


@dataclass
class CursorSecretsApi:
    held: dict[str, list[str]] = field(default_factory=dict)
    refuse: tuple[int, str] | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.refuse is not None:
            status, code = self.refuse
            return httpx.Response(status, json={"error": {"code": code, "message": VALUE}})
        scope = "team" if request.url.path.startswith("/v1/team/") else "environment"
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"name": n} for n in self.held[scope]]})
        name = request.url.path.rsplit("/", 1)[-1]
        self.held.setdefault(scope, []).append(name)
        return httpx.Response(200, json={"name": name})

    def client(self) -> CursorSecretsClient:
        return CursorSecretsClient(
            SecretStr("cursor-test-key"), transport=httpx.MockTransport(self.handler)
        )


async def test_cursor_environment_secrets_verify_held_names_then_put_runtime_secrets() -> None:
    api = CursorSecretsApi(held={"environment": ["CURSOR_HELD_KEY"]})
    client = api.client()
    store = CursorEnvironmentSecrets(client, "env-123")
    resolved = ResolvedSecrets(values={"FIRECRAWL_API_KEY": VALUE}, held=("cursor_held_key",))
    uses = await deliver_to_store(resolved, store)
    await client.aclose()

    listed, put = api.requests
    assert listed.method == "GET" and listed.url.path == "/v1/environments/env-123/secrets"
    assert put.method == "PUT"
    assert put.url.path == "/v1/environments/env-123/secrets/FIRECRAWL_API_KEY"
    assert json.loads(put.content) == {"value": VALUE, "type": "runtime_secret"}
    assert put.headers["Authorization"] == "Bearer cursor-test-key"
    assert uses == (
        SecretUse(
            "FIRECRAWL_API_KEY", DeliveryChannel.CURSOR_ENVIRONMENT, "cursor:environment:env-123"
        ),
        SecretUse(
            "cursor_held_key",
            DeliveryChannel.CURSOR_ENVIRONMENT,
            "cursor:environment:env-123",
            held=True,
        ),
    )
    assert VALUE not in repr(uses)


async def test_a_missing_provider_held_name_refuses_before_any_write() -> None:
    api = CursorSecretsApi(held={"team": ["OTHER_KEY"]})
    client = api.client()
    resolved = ResolvedSecrets(values={"FIRECRAWL_API_KEY": VALUE}, held=("TEAM_KEY",))
    with pytest.raises(
        ProviderHeldSecretMissing, match="cursor:team holds no secret named TEAM_KEY"
    ):
        await deliver_to_store(resolved, CursorTeamSecrets(client))
    await client.aclose()
    assert [request.method for request in api.requests] == ["GET"]


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (403, "key_not_supported", "this key type cannot manage secrets"),
        (403, "repository_access", "repository-limited key"),
        (403, "team_admin_required", "restricts secret changes to admins"),
        (400, "validation_error", "refused the secret"),
    ],
)
async def test_cursor_refusals_are_typed_and_never_echo_provider_text(
    status: int, code: str, message: str
) -> None:
    api = CursorSecretsApi(refuse=(status, code))
    client = api.client()
    with pytest.raises(CursorSecretRefused, match=message) as refused:
        await client.put_team_secret("FIRECRAWL_API_KEY", "fc-another-value")
    await client.aclose()
    assert VALUE not in str(refused.value) and "fc-another-value" not in str(refused.value)


async def test_cursor_limits_refuse_before_the_request() -> None:
    api = CursorSecretsApi()
    client = api.client()
    for name, value in (("HTTPS_PROXY", "proxy-value"), ("MY_CURSOR_SANDBOX_X", "v" * 8)):
        with pytest.raises(CursorSecretRefused, match="reserves"):
            await client.put_environment_secret("env-1", name, value)
    with pytest.raises(CursorSecretRefused, match="4,096 bytes"):
        await client.put_environment_secret("env-1", "BIG", "x" * 4097)
    await client.aclose()
    assert api.requests == []

    assert launch_env_vars({"MC_SIGNAL_TOKEN": "mct_value"}) == {"MC_SIGNAL_TOKEN": "mct_value"}
    with pytest.raises(CursorSecretRefused, match="CURSOR_"):
        launch_env_vars({"CURSOR_TOKEN": "value"})
    with pytest.raises(CursorSecretRefused, match="at most 50"):
        launch_env_vars({f"VAR_{index}": "value" for index in range(51)})
    with pytest.raises(CursorSecretRefused, match="255 bytes"):
        launch_env_vars({"V" * 256: "value"})
    with pytest.raises(CursorSecretRefused, match="4,096 bytes"):
        launch_env_vars({"BIG": "x" * 4097})
    # Only the documented launch limits apply: the stored-secret reservations do not.
    documented = {"HTTPS_PROXY": "http://proxy.internal:3128", "EMPTY": ""}
    assert launch_env_vars(documented) == documented


# --- provider vaults ------------------------------------------------------------------------


@dataclass
class FakeCredentials:
    """The shape of `client.beta.vaults.credentials` / `client.beta.agents.vaults.credentials`."""

    listed: list[Any] = field(default_factory=list)
    created: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def create(self, vault_id: str, **params: Any) -> Any:
        self.created.append((vault_id, params))
        return SimpleNamespace(id=f"cred-{len(self.created)}")

    async def _items(self) -> AsyncIterator[Any]:
        for item in self.listed:
            yield item

    def list(self, vault_id: str) -> AsyncIterator[Any]:
        return self._items()


def _credential(name: str, *, archived: bool = False) -> Any:
    auth = SimpleNamespace(type="environment_variable", secret_name=name)
    return SimpleNamespace(auth=auth, archived_at="2026-10-13T00:00:00Z" if archived else None)


@pytest.mark.parametrize(
    ("provider", "name_field"), [("anthropic", "display_name"), ("openai", "name")]
)
async def test_vault_credentials_carry_the_value_to_its_allowed_hosts_only(
    provider: str, name_field: str
) -> None:
    credentials = FakeCredentials(
        listed=[_credential("GITHUB_TOKEN"), _credential("ARCHIVED_KEY", archived=True)]
    )
    store = ProviderVaultStore(
        credentials,
        "vault_01",
        provider=provider,  # type: ignore[arg-type]
        allowed_hosts={"FIRECRAWL_API_KEY": ("api.firecrawl.dev",)},
        metadata={"mc_run": "run1-MO-11"},
    )
    resolved = ResolvedSecrets(values={"FIRECRAWL_API_KEY": VALUE}, held=("GITHUB_TOKEN",))
    uses = await deliver_to_store(resolved, store)

    ((vault_id, params),) = credentials.created
    assert vault_id == "vault_01"
    assert params == {
        name_field: "FIRECRAWL_API_KEY",
        "auth": {
            "type": "environment_variable",
            "secret_name": "FIRECRAWL_API_KEY",
            "secret_value": VALUE,
            "networking": {"type": "limited", "allowed_hosts": ["api.firecrawl.dev"]},
        },
        "metadata": {"mc_run": "run1-MO-11"},
    }
    assert {use.channel for use in uses} == {DeliveryChannel.PROVIDER_VAULT}
    assert uses[0].target == f"{provider}:vault:vault_01"

    with pytest.raises(ProviderHeldSecretMissing, match="ARCHIVED_KEY"):
        await deliver_to_store(ResolvedSecrets(held=("ARCHIVED_KEY",)), store)
    with pytest.raises(ValueError, match="names no allowed host"):
        await store.put("UNHOSTED_KEY", VALUE)


# --- process environment --------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    request_scope: str = "scope"
    run_key: str = "run-1"
    activation_key: str = "unit-1"
    attempt_no: int = 2


def _environment(*entries: str) -> EnvironmentBinding:
    return EnvironmentBinding(kind="local_workspace", host_profile="worker", secret_refs=entries)


async def test_a_local_child_receives_its_agent_phase_declarations() -> None:
    store = InMemoryMintedCredentialStore()
    broker = SecretBroker(
        environment=WorkerEnvironmentSource({"FIRECRAWL_API_KEY": VALUE}),
        minter=CredentialMinter(store),
    )
    delivered = await ProcessSecretDelivery(broker).environment(
        _environment(
            "FIRECRAWL_API_KEY=environment:FIRECRAWL_API_KEY",
            "MC_SIGNAL_TOKEN=mint:signal_token;agent",
            "SETUP_ONLY=environment:FIRECRAWL_API_KEY;setup",
        ),
        Identity(),
    )
    assert set(delivered.values) == {"FIRECRAWL_API_KEY", "MC_SIGNAL_TOKEN"}
    assert delivered.values["FIRECRAWL_API_KEY"] == VALUE
    (record,) = store._records.values()
    assert (record.binding.run_id, record.binding.unit_id, record.binding.generation) == (
        "run-1",
        "unit-1",
        2,
    )
    assert delivered.uses == (
        SecretUse("FIRECRAWL_API_KEY", DeliveryChannel.PROCESS_ENVIRONMENT),
        SecretUse("MC_SIGNAL_TOKEN", DeliveryChannel.PROCESS_ENVIRONMENT),
    )
    assert VALUE not in repr(delivered)


async def test_a_provider_held_secret_cannot_reach_a_local_process() -> None:
    broker = SecretBroker(
        environment=WorkerEnvironmentSource({}),
        store=WorkerEnvironmentSource({}),
        provider_held=("cursor/team_key",),
    )
    with pytest.raises(SecretUnavailable, match="cannot reach a local process"):
        await ProcessSecretDelivery(broker).environment(
            _environment("TEAM_KEY=secret:cursor/team_key"), Identity()
        )
