"""A Managed Agents vault as the Secret Broker's `provider_vault` store (SPEC-06 section 4.1).

Prepare delivers the pack's credential values through `deliver_to_store` (ADR-0043), so each
write is recorded as a `SecretUse` and the values were resolved by the broker (and joined its
redaction registry). `ProviderVaultStore` (MO-11) serves the same channel through a pinned
SDK's credentials resource and only creates; prepare keeps one vault per secret-set digest
across syncs, so this store writes a value to the credential its name already has (`update`:
`secret_name` is immutable) and creates one otherwise, through the httpx client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.application.secrets.delivery import DeliveryChannel

CredentialAction = Literal["created", "refreshed"]


class ManagedVaultStore:
    """One vault as a `ProviderSecretStore`; `written` records each name's credential id and
    whether this store created or refreshed it."""

    channel = DeliveryChannel.PROVIDER_VAULT

    def __init__(
        self,
        client: ManagedAgentsClient,
        vault_id: str,
        *,
        allowed_hosts: Mapping[str, tuple[str, ...]],
        metadata: Mapping[str, str],
    ) -> None:
        self._client = client
        self._vault_id = vault_id
        self._allowed_hosts = allowed_hosts
        self._metadata = dict(metadata)
        self._held: dict[str, str] | None = None
        self.written: dict[str, tuple[str, CredentialAction]] = {}

    @property
    def target(self) -> str:
        return f"anthropic:vault:{self._vault_id}"

    async def put(self, name: str, value: str) -> None:
        hosts = self._allowed_hosts.get(name)
        if not hosts:
            # A placeholder is substituted only towards allowed hosts (ProviderVaultStore).
            raise ValueError(f"vault credential {name} names no allowed host")
        auth = {
            "type": "environment_variable",
            "secret_value": value,
            "networking": {"type": "limited", "allowed_hosts": list(hosts)},
        }
        held = await self._credentials()
        if name in held:
            await self._client.update_credential(self._vault_id, held[name], {"auth": auth})
            self.written[name] = (held[name], "refreshed")
            return
        created = await self._client.create_credential(
            self._vault_id,
            {
                "display_name": name,
                "auth": {**auth, "secret_name": name},
                "metadata": self._metadata,
            },
        )
        held[name] = str(created["id"])
        self.written[name] = (held[name], "created")

    async def names(self) -> frozenset[str]:
        return frozenset(await self._credentials())

    async def _credentials(self) -> dict[str, str]:
        """The unarchived credentials by secret name (listings never carry a value)."""

        if self._held is None:
            self._held = {
                str(credential["auth"]["secret_name"]): str(credential["id"])
                for credential in await self._client.list_credentials(self._vault_id)
                if credential.get("archived_at") is None
                and isinstance(credential.get("auth"), dict)
            }
        return self._held


__all__ = ["CredentialAction", "ManagedVaultStore"]
