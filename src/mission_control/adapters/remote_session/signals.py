"""Trusted hosted custom-tool signals through the same scoped ingress service.

The worker retains the minted bearer. Neither the provider sandbox nor tool
arguments receive a credential, installation identity, scope or success receipt
that could authorize state transitions.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.hosted_tools import HostedCall
from mission_control.application.secrets.minting import (
    CredentialBinding,
    LaunchBinding,
    MintedToken,
)
from mission_control.application.secrets.redaction import SecretValueRegistry
from mission_control.application.signals.contracts import IngressRejected, Signal
from mission_control.application.signals.service import SignalIngressService


class HostedSignalMinter(Protocol):
    async def mint(
        self,
        purpose: str,
        binding: CredentialBinding | LaunchBinding,
        *,
        deadline: datetime | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> MintedToken: ...


class HostedSignalDelivery:
    def __init__(
        self,
        service: SignalIngressService,
        minter: HostedSignalMinter,
        registry: SecretValueRegistry,
    ) -> None:
        self._service, self._minter, self._registry = service, minter, registry
        self._tokens: dict[CredentialBinding, MintedToken] = {}

    async def __call__(self, identity: LaneExecutionIdentity, call: HostedCall) -> dict:
        binding = CredentialBinding(
            identity.request_scope, identity.run_key, identity.activation_key, identity.attempt_no
        )
        token = self._tokens.get(binding)
        if token is None or token.record.expires_at <= datetime.now(UTC):
            token = await self._minter.mint(
                "signal_token",
                binding,
                context={
                    "lane_profile": identity.lane_profile,
                    "harness_execution_id": str(identity.harness_execution_id),
                },
            )
            self._tokens[binding] = token
            self._registry.add((token.value,))
        try:
            data = call.arguments.get("data") or {}
            signal = Signal(
                signal_id=call.native_ref.removeprefix("sha256:"),
                type=str(call.arguments.get("name") or ""),
                data=data,
            )
            receipt = await self._service.signals(
                signal.model_dump_json().encode(), {"authorization": f"Bearer {token.value}"}
            )
        except IngressRejected as error:
            return {"error": error.code}
        except ValidationError:
            return {"error": "invalid_signal"}
        return receipt.model_dump(mode="json")
