"""Per-lane delivery of resolved secrets (SPEC-01 section 4 delivery table; ADR-0043).

A channel moves values from the broker to exactly one place, and its use is recorded as names
and the channel only (`SecretUse`, what the Materialization Receipt cites):

* `process_environment` (cursor_local, claude_agent_sdk, codex): `ProcessSecretDelivery`
  resolves the binding's declarations for the agent phase into values the lane passes as
  `extra` to `provider_child_environment`, so the child's environment is the allowlist plus
  exactly these values. A provider-held secret cannot reach a local process and is refused.
* provider stores (`cursor_environment_secret`, `cursor_team_secret`, `provider_vault`):
  `deliver_to_store` verifies every provider-held name exists in the store, then writes each
  resolved value through the store's own API (Cursor's environment or team secrets, an
  Anthropic or OpenAI vault credential). The store never returns a value.
* `cursor_launch_env_vars`: per-run values on the agent create request (the `cursor_cloud`
  lane's env resolver, through the broker).

`claude_cloud` and `codex_cloud` have no per-run channel: their secrets are owner
prerequisites (SPEC-05), so nothing is delivered here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from mission_control.application.secrets.broker import (
    ResolvedSecrets,
    SecretBroker,
    SecretUnavailable,
)
from mission_control.application.secrets.minting import CredentialBinding
from mission_control.application.secrets.references import SecretPhase, declarations
from mission_control.domain.execution.bindings import EnvironmentBinding


class DeliveryChannel(StrEnum):
    PROCESS_ENVIRONMENT = "process_environment"
    CURSOR_LAUNCH_ENV_VARS = "cursor_launch_env_vars"
    CURSOR_ENVIRONMENT = "cursor_environment_secret"
    CURSOR_TEAM = "cursor_team_secret"
    PROVIDER_VAULT = "provider_vault"


@dataclass(frozen=True)
class SecretUse:
    """One secret's use: its variable name, the channel and the channel's target (an
    environment or vault id), and whether its value was held by the provider."""

    name: str
    channel: DeliveryChannel
    target: str | None = None
    held: bool = False


class ProviderHeldSecretMissing(LookupError):
    def __init__(self, target: str, names: tuple[str, ...]) -> None:
        super().__init__(f"{target} holds no secret named {', '.join(names)}")
        self.names = names


class ProviderSecretStore(Protocol):
    """A provider's secret store reached through its API (write-only values)."""

    @property
    def channel(self) -> DeliveryChannel: ...

    @property
    def target(self) -> str: ...

    async def put(self, name: str, value: str) -> None: ...

    async def names(self) -> frozenset[str]:
        """The secret names the store holds (case as the provider reports it)."""
        ...


async def deliver_to_store(
    resolved: ResolvedSecrets, store: ProviderSecretStore
) -> tuple[SecretUse, ...]:
    """Verify the provider-held names, then write every resolved value to `store`."""

    if resolved.held:
        present = {name.upper() for name in await store.names()}
        missing = tuple(name for name in resolved.held if name.upper() not in present)
        if missing:
            raise ProviderHeldSecretMissing(store.target, missing)
    for name, value in resolved.values.items():
        await store.put(name, value)
    return (
        *(SecretUse(name, store.channel, store.target) for name in resolved.values),
        *(SecretUse(name, store.channel, store.target, held=True) for name in resolved.held),
    )


class AttemptIdentity(Protocol):
    """What a lane knows of its attempt (`LaneExecutionIdentity`)."""

    @property
    def request_scope(self) -> str: ...

    @property
    def run_key(self) -> str: ...

    @property
    def activation_key(self) -> str: ...

    @property
    def attempt_no(self) -> int: ...


def credential_binding(identity: AttemptIdentity) -> CredentialBinding:
    """The binding a lane attempt's minted credentials carry (its scope, run, unit and
    generation)."""

    return CredentialBinding(
        request_scope=identity.request_scope,
        run_id=identity.run_key,
        unit_id=identity.activation_key,
        generation=identity.attempt_no,
    )


@dataclass(frozen=True)
class DeliveredEnvironment:
    values: Mapping[str, str] = field(default_factory=dict, repr=False)
    uses: tuple[SecretUse, ...] = ()


class ProcessSecretDelivery:
    """`process_environment`: the values a local provider child receives beyond the
    allowlist, from the binding's declarations for one phase."""

    def __init__(self, broker: SecretBroker) -> None:
        self._broker = broker

    async def environment(
        self,
        environment: EnvironmentBinding,
        identity: AttemptIdentity,
        *,
        phase: SecretPhase = "agent",
        deadline: datetime | None = None,
    ) -> DeliveredEnvironment:
        resolved = await self._broker.resolve_declarations(
            declarations(environment.secret_refs),
            phase=phase,
            binding=credential_binding(identity),
            deadline=deadline,
        )
        if resolved.held:
            raise SecretUnavailable(
                f"{', '.join(resolved.held)} are held by a provider and cannot reach a local "
                "process"
            )
        return DeliveredEnvironment(
            values=dict(resolved.values),
            uses=tuple(
                SecretUse(name, DeliveryChannel.PROCESS_ENVIRONMENT) for name in resolved.values
            ),
        )


__all__ = [
    "AttemptIdentity",
    "DeliveredEnvironment",
    "DeliveryChannel",
    "ProcessSecretDelivery",
    "ProviderHeldSecretMissing",
    "ProviderSecretStore",
    "SecretUse",
    "credential_binding",
    "deliver_to_store",
]
