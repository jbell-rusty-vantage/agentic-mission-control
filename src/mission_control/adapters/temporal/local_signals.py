"""Run-bound signal credentials delivered only to local provider child processes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import asyncpg

from mission_control.adapters.postgres.ingress import PostgresMintedCredentialStore
from mission_control.application.secrets.broker import SecretBroker, SecretUnavailable
from mission_control.application.secrets.delivery import (
    AttemptIdentity,
    DeliveredEnvironment,
    DeliveryChannel,
    ProcessSecretDelivery,
    SecretUse,
    credential_binding,
)
from mission_control.application.secrets.minting import (
    CredentialBinding,
    CredentialMinter,
    LaunchBinding,
    MintedToken,
)
from mission_control.application.secrets.references import SecretPhase, declarations
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding


def gate_context(identity: AttemptIdentity) -> dict[str, Any]:
    lane = getattr(identity, "lane_profile", None)
    harness = getattr(identity, "harness_execution_id", None)
    return {"lane_profile": lane, "harness_execution_id": str(harness)} if lane and harness else {}


class ScopedSecretMinter:
    """Route a broker mint to the same scoped credential table the ingress reads."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def mint(
        self,
        purpose: str,
        binding: CredentialBinding | LaunchBinding,
        *,
        deadline: datetime | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> MintedToken:
        minter = CredentialMinter(PostgresMintedCredentialStore(self._pool, binding.request_scope))
        if isinstance(binding, CredentialBinding):
            await minter.revoke_superseded(binding)
        return await minter.mint(purpose, binding, deadline=deadline, context=context)


class LocalSignalDelivery(ProcessSecretDelivery):
    """The broker's normal declarations plus a scoped local telemetry credential.

    The listener URL is installation configuration; neither a mission variable nor an
    inherited worker environment can redirect the bearer to another host.
    """

    def __init__(self, broker: SecretBroker, pool: asyncpg.Pool, *, port: int) -> None:
        super().__init__(broker)
        self._broker = broker
        self._pool = pool
        self._port = port

    async def environment(
        self,
        environment: EnvironmentBinding,
        identity: AttemptIdentity,
        *,
        phase: SecretPhase = "agent",
        deadline: datetime | None = None,
    ) -> DeliveredEnvironment:
        for declaration in declarations(environment.secret_refs):
            if (
                declaration.name == "MC_SIGNAL_TOKEN"
                and str(declaration.ref) != "mint:signal_token"
            ):
                raise SecretUnavailable("MC_SIGNAL_TOKEN must reference mint:signal_token")
            if declaration.name == "MC_SIGNAL_URL":
                raise SecretUnavailable("MC_SIGNAL_URL is the configured local ingress URL")
        declared_environment = environment
        if phase == "agent" and environment.in_environment_observation is not False:
            declared_environment = environment.model_copy(
                update={
                    "secret_refs": tuple(
                        declaration.binding_entry
                        for declaration in declarations(environment.secret_refs)
                        if declaration.name != "MC_SIGNAL_TOKEN"
                    )
                }
            )
        delivered = await super().environment(
            declared_environment, identity, phase=phase, deadline=deadline
        )
        if phase != "agent" or environment.in_environment_observation is False:
            return delivered
        scope = parse_request_scope(identity.request_scope)
        minter = CredentialMinter(PostgresMintedCredentialStore(self._pool, identity.request_scope))
        binding = credential_binding(identity)
        await minter.revoke_superseded(binding)
        token = await minter.mint(
            "signal_token", binding, deadline=deadline, context=gate_context(identity)
        )
        value = token.value
        self._broker.registry.add((value,))
        return DeliveredEnvironment(
            values={
                **delivered.values,
                "MC_SIGNAL_URL": f"http://127.0.0.1:{self._port}/v1/ingress/{scope.application_id}/signals",
                "MC_SIGNAL_TOKEN": value,
            },
            uses=(
                *delivered.uses,
                SecretUse("MC_SIGNAL_TOKEN", DeliveryChannel.PROCESS_ENVIRONMENT),
            ),
        )


class RemoteSignalDelivery:
    """Per-attempt launch envVars; the public HTTPS origin is explicit installation config."""

    def __init__(self, broker: SecretBroker, pool: asyncpg.Pool, *, origin: str) -> None:
        target = urlsplit(origin)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target.query
            or target.fragment
            or target.path not in {"", "/"}
        ):
            raise ValueError("remote signal ingress origin must be a credential-free HTTPS origin")
        self._origin = origin.rstrip("/")
        self._host = target.hostname
        self._broker = broker
        self._minter = ScopedSecretMinter(pool)

    async def __call__(
        self, operation: OperationExecutionRequest, identity: AttemptIdentity
    ) -> Mapping[str, str]:
        binding = CursorExecutionBinding.carried_by(operation)
        if binding is None or binding.in_environment_observation is False:
            return {}
        if binding.signal_gates is not None and binding.network is None:
            raise SecretUnavailable("remote signal gates require a pinned ingress egress policy")
        if binding.network is not None and not binding.network.allows(self._host):
            raise SecretUnavailable("the remote ingress origin is outside the pinned egress policy")
        scope = parse_request_scope(identity.request_scope)
        context = gate_context(identity)
        context["disallowed_tools"] = list(binding.disallowed_tools)
        token = await self._minter.mint(
            "signal_token", credential_binding(identity), context=context
        )
        self._broker.registry.add((token.value,))
        return {
            "MC_SIGNAL_URL": f"{self._origin}/v1/ingress/{scope.application_id}/signals",
            "MC_SIGNAL_TOKEN": token.value,
        }
