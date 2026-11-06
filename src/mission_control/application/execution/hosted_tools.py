"""Shared Stop Fence, Operation Intent and human review for hosted function tools.

Provider adapters supply wire mappers. This service retains no provider object,
credential or client-supplied claim that an effect or approval succeeded.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mission_control.application.execution.approvals_broker import (
    ApprovalBroker,
    NativeApprovalRequest,
)
from mission_control.application.execution.approvals_governed import (
    GovernedEffectService,
    GovernedPrepareRequest,
)
from mission_control.application.execution.harness.hook_callbacks import (
    HookEffectIntent,
    HookIntentLedger,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.stop_fence import StopFenceRepository
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.approvals import NativeApprovalCorrelation
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.policies.stop_fence import EffectAdmission, EffectKind


@dataclass(frozen=True)
class HostedCall:
    session_id: str
    turn_id: str
    call_id: str
    name: str
    arguments: Mapping[str, Any]

    @property
    def native_ref(self) -> str:
        return sha256_digest((self.session_id, self.turn_id, self.call_id))


class HostedToolGate:
    """The worker's trusted gate, with its existing persisted repositories and broker."""

    def __init__(
        self,
        *,
        fences: StopFenceRepository,
        intents: HookIntentLedger,
        broker: ApprovalBroker,
        reviewers: tuple[str, ...],
        allowed_tools: frozenset[str],
        wait_seconds: float = 1.0,
    ) -> None:
        if not reviewers or not 0 < wait_seconds <= 30:
            raise ValueError("hosted approvals name reviewers and use a bounded wait")
        self._fences, self._intents, self._broker = fences, intents, broker
        self._reviewers, self._wait = reviewers, wait_seconds
        self._allowed_tools = allowed_tools

    async def admit(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
        kind: EffectKind = "other",
    ) -> bool:
        admission = EffectAdmission(
            request_scope=identity.request_scope,
            run_id=identity.run_key,
            generation=identity.attempt_no,
            effect_ref=call.native_ref,
            effect_kind=kind,
            lane_profile=identity.lane_profile,
        )
        verdict = await self._fences.admit_effect(admission)
        if not verdict.allowed:
            return False
        binding = ProviderExecutionBinding.carried_by(operation)
        if binding is None or call.name not in self._allowed_tools:
            return False
        await self._intents.record(
            HookEffectIntent(
                request_scope=identity.request_scope,
                run_id=identity.run_key,
                generation=identity.attempt_no,
                harness_execution_id=identity.harness_execution_id,
                effect_ref=call.native_ref,
                effect_kind=kind,
                hook_event="before_tool",
                lane_profile=identity.lane_profile,
                input_digest=sha256_digest({"tool": call.name, "arguments": dict(call.arguments)}),
                recorded_at=datetime.now(UTC),
            )
        )
        return True

    async def permission(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
        kind: EffectKind = "other",
    ) -> dict[str, Any] | None:
        if not await self.admit(operation, identity, call, kind):
            return {"result": "deny", "deny_message": "Mission Control refused this effect"}
        assert operation.lane_binding is not None
        bound = await self._broker.bind(
            NativeApprovalRequest(
                request_scope=identity.request_scope,
                run_id=identity.run_key,
                lane_profile=identity.lane_profile,
                origin="provider_permission",
                harness_execution_id=str(identity.harness_execution_id),
                generation=identity.attempt_no,
                native=NativeApprovalCorrelation(
                    native_session_ref=call.session_id,
                    native_turn_ref=call.turn_id,
                    native_request_ref=call.call_id,
                    tool_call_ref=call.call_id,
                    connection_scoped=False,
                ),
                tool_name=call.name,
                arguments=dict(call.arguments),
                effect_kind=kind,
                policy_digest=operation.effective_configuration_digest,
                reviewers=self._reviewers,
                prompt=f"Hosted agent requests permission to use {call.name}",
                replay_strategy="reissue_native_request",
            )
        )
        outcome = bound.immediate or await self._broker.wait(bound, wait_seconds=self._wait)
        if outcome.status == "expired":
            return None  # The durable task stays open and the provider still holds its request.
        reply = outcome.reply
        allowed = (
            reply.action == "allow"
            and reply.reason == "human_decision"
            and reply.updated_arguments is None
        )
        if allowed:
            allowed = await self.admit(operation, identity, call, kind)
        if allowed:
            return {"result": "allow"}
        return {
            "result": "deny",
            "deny_message": reply.message or "Denied; edited inputs are unsupported on this lane",
        }


GovernedFactory = Callable[
    [OperationExecutionRequest, LaneExecutionIdentity], GovernedEffectService
]


class HostedGovernedTools:
    """Execute one native function call through the existing durable governed gateway."""

    def __init__(
        self, service: GovernedFactory, actor: ActorContext, *, wait_seconds: float = 0
    ) -> None:
        if not 0 <= wait_seconds <= 300:
            raise ValueError("hosted review wait must be between zero and 300 seconds")
        self._service, self._actor, self._wait = service, actor, wait_seconds

    async def execute(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
        *,
        tool_name: str | None = None,
    ) -> dict[str, Any] | None:
        service = self._service(operation, identity)
        state = await service.prepare(
            GovernedPrepareRequest(
                run_id=identity.run_key,
                harness_execution_id=str(identity.harness_execution_id),
                generation=identity.attempt_no,
                lane_profile=identity.lane_profile,
                tool_name=tool_name or call.name,
                arguments=dict(call.arguments),
                native_call_ref=call.native_ref,
            ),
            self._actor,
        )
        state = await service.execute(state.intent_id, self._actor)
        deadline = asyncio.get_running_loop().time() + self._wait
        while state.status == "pending_approval" and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(min(0.1, max(0, deadline - asyncio.get_running_loop().time())))
            state = await service.execute(state.intent_id, self._actor)
        if state.status in {"pending_approval", "ready", "executing"}:
            return None
        return state.public()


HostedSignal = Callable[[LaneExecutionIdentity, HostedCall], Awaitable[dict[str, Any]]]
