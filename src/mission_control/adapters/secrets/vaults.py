"""Provider vault delivery: Anthropic Managed Agents and OpenAI Agents API vaults (SPEC-06).

A hosted session never receives a secret value: each value becomes a vault
`environment_variable` credential, and the sandbox sees a placeholder the provider substitutes
in outbound request headers to the credential's allowed hosts only. The request shape is the
one HL-23 sent live through the pinned SDKs (research/provider-smoke-2026-10.md sections 2.1
and 3.1): `auth = {type: environment_variable, secret_name, secret_value,
networking: {type: limited, allowed_hosts}}` plus `metadata`, created through
`client.beta.vaults.credentials` (anthropic 1.13.0, `display_name`) or
`client.beta.agents.vaults.credentials` (openai 3.29.0, `name`, required there).

The lanes compose this store with their own pinned client's credentials resource, so this
module imports no provider SDK. Credential listings report `auth.secret_name` and never a value
(verified for anthropic's `BetaManagedAgentsCredential`; the OpenAI listing's field names are
UNVERIFIED and read the same way).
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Mapping
from typing import Any, Literal, Protocol

from mission_control.application.secrets.delivery import DeliveryChannel

VaultProvider = Literal["anthropic", "openai"]

# The keyword each pinned SDK names a credential by.
_NAME_FIELD: Mapping[VaultProvider, str] = {"anthropic": "display_name", "openai": "name"}


class VaultCredentials(Protocol):
    """A pinned SDK's async vault credentials resource."""

    async def create(self, vault_id: str, **params: Any) -> Any: ...

    def list(self, vault_id: str) -> AsyncIterable[Any]: ...


class ProviderVaultStore:
    """One provider vault as a `ProviderSecretStore`."""

    channel = DeliveryChannel.PROVIDER_VAULT

    def __init__(
        self,
        credentials: VaultCredentials,
        vault_id: str,
        *,
        provider: VaultProvider,
        allowed_hosts: Mapping[str, tuple[str, ...]],
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self._credentials = credentials
        self._vault_id = vault_id
        self._provider = provider
        self._allowed_hosts = allowed_hosts
        self._metadata = dict(metadata or {})

    @property
    def target(self) -> str:
        return f"{self._provider}:vault:{self._vault_id}"

    async def put(self, name: str, value: str) -> None:
        hosts = self._allowed_hosts.get(name)
        if not hosts:
            # A placeholder is substituted only towards allowed hosts; a credential with none
            # would never reach its service (`credential_host_unreachable_error`).
            raise ValueError(f"vault credential {name} names no allowed host")
        await self._credentials.create(
            self._vault_id,
            **{_NAME_FIELD[self._provider]: name},
            auth={
                "type": "environment_variable",
                "secret_name": name,
                "secret_value": value,
                "networking": {"type": "limited", "allowed_hosts": list(hosts)},
            },
            metadata=self._metadata,
        )

    async def names(self) -> frozenset[str]:
        held: set[str] = set()
        async for credential in self._credentials.list(self._vault_id):
            auth = getattr(credential, "auth", None)
            name = getattr(auth, "secret_name", None)
            if getattr(credential, "archived_at", None) is None and isinstance(name, str):
                held.add(name)
        return frozenset(held)


__all__ = ["ProviderVaultStore", "VaultCredentials", "VaultProvider"]
