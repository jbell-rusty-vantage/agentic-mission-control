"""Fenced adoption of an existing FINISHED Cursor run; no native harness dependency.

Response custody, recovery frames and ordinary operation/family decisions form a
replayable sequence. Frames retain the exact request/capture intent before usage
settlement. A partial result is retained, never reversed or replaced by dispatch.
Production composition must supply trusted identity/capture readers explicitly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from mission_control.application.artifacts.artifact_promotion import (
    ArtifactPayloadAddress,
    ArtifactPayloadPort,
)
from mission_control.application.execution.harness.dispatch import SessionOwner
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.harness.state import (
    LaneExecutionStateStore,
    LaneExecutionUpdate,
)
from mission_control.application.execution.operations.operation_execution import (
    OperationExecutionService,
    bind_operation_execution_request,
)
from mission_control.application.frames.sink import FrameReader
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.programs.service import StageGraphDecisionService
from mission_control.application.recovery.terminal_evidence_capture import (
    TerminalCaptureReader,
    ValidatedTerminalCapture,
    validate_capture,
)
from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionAuthority,
    AdoptionIdentity,
    AdoptionInspectionRefused,
)
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.frames.contracts import (
    AppendReceipt,
    FrameKind,
    FrameObservation,
    HarnessExecutionHandle,
    ProviderCursor,
    ProviderFrame,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.contracts import (
    StageGraphResultActivityRequest,
    StageGraphResultActivityResult,
)

PERMISSION = "workflow_run.reconcile_unit"


@dataclass(frozen=True)
class PendingFamilyResult:
    """Trusted immutable Temporal activity input; never synthesize a replacement."""

    operation_temporal_run_id: str
    family_temporal_run_id: str
    scheduled_event_id: int
    activity_id: str
    task_queue: str
    request: StageGraphResultActivityRequest
    activity_attempt: int = 1

    @property
    def digest(self) -> str:
        return sha256_digest(asdict(self))


@dataclass(frozen=True)
class TerminalAdoptionContext:
    authority: AdoptionAuthority
    operation: OperationExecutionRequest
    handle: HarnessExecutionHandle
    # Original accepted family head/template, retrieved by its persisted digest
    # even on replay after the result decision advanced the current head.
    family: StageGraphResultActivityRequest
    pending_family_result: PendingFamilyResult | None = None


class TerminalAdoptionContextReader(Protocol):
    async def read(
        self, identity: AdoptionIdentity, family_digest: str
    ) -> TerminalAdoptionContext: ...


class FencedTerminalFrameStore(Protocol):
    async def append_fenced(
        self, frames: Sequence[ProviderFrame], *, owner: SessionOwner
    ) -> AppendReceipt: ...
    async def last_cursor(
        self, harness_execution_id: UUID, generation: int, *, request_scope: str
    ) -> ProviderCursor | None: ...


@dataclass(frozen=True)
class TerminalAdoptionRequest:
    request_id: str
    identity: AdoptionIdentity
    expected_authority_digest: str
    expected_family_digest: str
    capture_reference: str
    capture_digest: str
    # Non-None selects settlement only, bound to a separately verified live
    # family's original pending activity. It never authorizes family decisions.
    pending_family_result_digest: str | None = None


@dataclass(frozen=True)
class TerminalAdoptionResult:
    response: ArtifactPayloadAddress
    frames: AppendReceipt
    operation: OperationExecutionResult
    family: StageGraphResultActivityResult | None
    remaining_liabilities: tuple[str, ...]
    provider_acknowledged: bool = False


class _OwnedSink:
    def __init__(self, frames: FencedTerminalFrameStore, owner: SessionOwner) -> None:
        self.frames, self.owner = frames, owner

    async def append(self, frames: Sequence[ProviderFrame]) -> AppendReceipt:
        return await self.frames.append_fenced(frames, owner=self.owner)

    async def last_cursor(
        self, harness_execution_id: UUID, generation: int, *, request_scope: str
    ) -> ProviderCursor | None:
        return await self.frames.last_cursor(
            harness_execution_id, generation, request_scope=request_scope
        )


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise AdoptionInspectionRefused(reason)


class TerminalEvidenceAdoptionService:
    def __init__(
        self,
        *,
        contexts: TerminalAdoptionContextReader,
        captures: TerminalCaptureReader,
        states: LaneExecutionStateStore,
        frames: FencedTerminalFrameStore,
        reader: FrameReader,
        payloads: ArtifactPayloadPort,
        operations: OperationExecutionService,
        programs: StageGraphDecisionService,
        sessions: WorkerSessionManager | None = None,
    ) -> None:
        self._contexts, self._captures, self._states = contexts, captures, states
        self._frames, self._reader, self._payloads = frames, reader, payloads
        self._operations, self._programs = operations, programs
        # The lease exceeds the whole request bound; ordinary takeover cannot
        # interleave a different owner between the fenced frames and settlement.
        self._sessions = sessions or WorkerSessionManager(min_lease=timedelta(seconds=120))

    async def adopt(
        self, request: TerminalAdoptionRequest, actor: ActorContext
    ) -> TerminalAdoptionResult:
        if PERMISSION not in actor.permissions:
            raise MissionControlRejected("unauthorized", PERMISSION + " is required")
        UUID(request.request_id)
        try:
            async with asyncio.timeout(30):
                return await self._adopt(request)
        except TimeoutError:
            raise MissionControlRejected(
                "unavailable",
                "terminal adoption deadline; retain exact request/capture "
                "and read its evidence before retry",
            ) from None

    def _validate_context(
        self, context: TerminalAdoptionContext, request: TerminalAdoptionRequest
    ) -> None:
        identity, authority = request.identity, context.authority
        operation, handle = context.operation, context.handle
        binding = bind_operation_execution_request(operation)
        pending = context.pending_family_result
        _require(
            (pending.digest if pending else None) == request.pending_family_result_digest,
            "pending family mode or immutable activity input differs",
        )
        if pending is not None:
            _require(
                authority.cancel_state in {"delivered", "applied"}
                and authority.phase in {"cancelling", "terminal"}
                and pending.scheduled_event_id > 1
                and bool(pending.activity_id)
                and bool(pending.task_queue)
                and bool(pending.operation_temporal_run_id)
                and bool(pending.family_temporal_run_id)
                and type(pending.activity_attempt) is int
                and pending.activity_attempt >= 1
                and pending.request.request_scope == identity.request_scope
                and pending.request.run_id == identity.public_run_key
                and pending.request.projection.digest == request.expected_family_digest
                and pending.request.observation.identity.semantic_key
                == operation.identity.semantic_key
                and pending.request.observation.operation_disposition == "failed"
                and pending.request.observation.child_closed_or_quiesced,
                "live family settlement-only preconditions differ",
            )
        _require(
            authority.identity == identity
            and operation.request_scope == identity.request_scope
            and operation.identity.run_id == identity.public_run_key
            and str(handle.run_id) == identity.internal_run_id
            and str(handle.harness_execution_id) == identity.harness_execution_id
            and handle.request_scope == identity.request_scope
            and handle.generation == identity.generation
            and handle.native_session_ref == identity.native_session_ref,
            "adoption context identity differs",
        )
        _require(
            operation.execution_runtime == "cursor" and operation.lane_profile == "cursor_local",
            "this capture adoption supports only existing local Cursor evidence",
        )
        _require(
            binding.binding_id == authority.binding_id
            and sha256_digest(binding) == authority.binding_digest,
            "admitted operation binding differs",
        )
        _require(
            authority.dispatches_resolved
            and bool(authority.dispatch_digest)
            and bool(authority.claim_id)
            and bool(authority.family_head_digest),
            "adoption authority frontier missing",
        )
        _require(
            context.family.projection.digest == request.expected_family_digest
            and context.family.request_scope == identity.request_scope
            and context.family.run_id == identity.public_run_key
            and context.family.observation.identity.semantic_key == operation.identity.semantic_key,
            "original admitted family identity differs",
        )

    async def _intent(self, request: TerminalAdoptionRequest) -> dict | None:
        identity = request.identity
        frames = await self._reader.frames_for_execution(
            identity.request_scope,
            UUID(identity.harness_execution_id),
            identity.generation,
            limit=2048,
        )
        _require(len(frames) < 2048, "terminal adoption frame read bound")
        key = "mc.terminal-adoption:" + request.request_id + ":intent"
        matches = [frame for frame in frames if frame.provider_key == key]
        _require(len(matches) <= 1, "duplicate adoption intent")
        if not matches:
            return None
        frame = matches[0]
        _require(
            frame.body_bytes == len(frame.body_excerpt.encode()), "adoption intent body incomplete"
        )
        body = json.loads(frame.body_excerpt)
        _require(
            body.get("request_digest") == sha256_digest(asdict(request)),
            "adoption request identity reused",
        )
        return body

    async def _adopt(self, request: TerminalAdoptionRequest) -> TerminalAdoptionResult:
        identity = request.identity
        capture = validate_capture(
            await self._captures.load_verified(identity, request.capture_reference),
            identity,
            request.capture_digest,
        )
        context = await self._contexts.read(identity, request.expected_family_digest)
        self._validate_context(context, request)
        intent = await self._intent(request)
        if intent is None:
            _require(
                sha256_digest(asdict(context.authority)) == request.expected_authority_digest,
                "adoption authority advanced before intent",
            )
            _require(
                (
                    context.authority.phase,
                    context.authority.harness_lifecycle,
                    context.authority.claim_status,
                )
                == ("cancelling", "live", "claimed"),
                "unsupported adoption shape",
            )
        else:
            _require(
                context.authority.phase in {"cancelling", "terminal"}
                and context.authority.claim_status
                in {"claimed", "settled", "cancelled", "reconciliation_required"},
                "adoption replay authority differs",
            )
        state = await self._states.load(identity.request_scope, UUID(identity.harness_execution_id))
        _require(
            state is not None
            and state.native_session_ref == identity.native_session_ref
            and state.native_turn_ref == identity.native_turn_ref,
            "native state differs",
        )
        assert state is not None
        if intent is None:
            _require(
                state.owner is not None
                and state.owner.epoch == context.authority.owner_epoch
                and state.owner.expired(datetime.now(UTC)),
                "old owner expiry/epoch unproved",
            )
        response = (
            ArtifactPayloadAddress.model_validate(intent["response"])
            if intent
            else await self._payloads.stage(
                artifact_id="terminal-response:"
                + identity.harness_execution_id
                + ":"
                + capture.result_digest,
                content=capture.result,
                content_digest=capture.result_digest,
                media_type="text/plain; charset=utf-8",
            )
        )
        _require(
            response.content_digest == capture.result_digest
            and response.size_bytes == len(capture.result)
            and await self._payloads.retrieve(response) == capture.result,
            "terminal response custody differs",
        )
        facts = ClosingFacts(
            native_status="finished",
            result_excerpt=capture.result.decode()[:500],
            result_text_ref=response.object_ref,
            usage=capture.usage,
            cost_disposition="settled" if capture.usage.cost_micros_usd is not None else "unknown",
        )
        prior = await self._operations.read_lane_settlement(context.operation)
        if prior is not None:
            closing = [
                item["lane_closing_facts"]
                for item in prior.event_payloads
                if "lane_closing_facts" in item
            ]
            _require(
                prior.provider_run_id == identity.native_turn_ref
                and closing == [facts.model_dump(mode="json")],
                "existing settlement differs from captured terminal facts",
            )
        if intent is not None:
            original = intent.get("authority")
            _require(
                isinstance(original, dict)
                and sha256_digest(original) == request.expected_authority_digest,
                "adoption intent original authority missing",
            )
            assert isinstance(original, dict)
            current = asdict(context.authority)
            invariant = (
                "identity",
                "binding_id",
                "binding_digest",
                "claim_id",
                "dispatch_digest",
                "dispatches_resolved",
                "cancel_command_id",
                "admitted_currency_micros",
            )
            _require(
                all(current[key] == original[key] for key in invariant),
                "adoption replay invariant authority changed",
            )
            terminal_receipt = (
                prior is not None
                and current["phase"] == "terminal"
                and current["cancel_state"] == "applied"
            )
            admitted_currency = {
                key
                for key, amount in bind_operation_execution_request(
                    context.operation
                ).budget_limits.items()
                if key.startswith("currency.") and amount > 0
            }
            currency_discharged = (
                prior is not None
                and bool(admitted_currency)
                and facts.cost_disposition == "settled"
                and facts.usage.cost_micros_usd is not None
                and not prior.usage.pending_external_amounts
                and all(
                    prior.usage.amounts.get(key) == facts.usage.cost_micros_usd
                    for key in admitted_currency
                )
                and original["currency_liability_retained"] is True
                and current["currency_liability_retained"] is False
            )
            _require(
                terminal_receipt
                or (
                    all(
                        current[key] == original[key]
                        for key in (
                            "cancel_state",
                            "cancel_receipt_revision",
                        )
                    )
                    and (
                        current["currency_liability_retained"]
                        == original["currency_liability_retained"]
                        or currency_discharged
                    )
                ),
                "adoption replay cancellation or liability authority changed",
            )
            _require(
                current["claim_status"] != "reconciliation_required"
                or (prior is not None and bool(prior.usage.pending_external_amounts)),
                "reconciliation claim lacks its immutable pending usage settlement",
            )
            _require(
                current["run_version"] >= original["run_version"],
                "run authority regressed before retained evidence settlement",
            )
            if current["family_head_digest"] != original["family_head_digest"]:
                public = await self._operations.read_lane_result(context.operation)
                _require(public is not None, "family advanced before terminal settlement")
                assert public is not None
                decision = await self._programs.read_result_decision(
                    context.pending_family_result.request
                    if context.pending_family_result
                    else self._family_request(context, capture, public)
                )
                _require(
                    decision is not None
                    and decision.accepted
                    and decision.projection.digest == current["family_head_digest"],
                    "adoption replay family frontier differs from its persisted result",
                )
        if prior is not None and context.authority.phase == "terminal":
            result = await self._operations.read_lane_result(context.operation)
            assert result is not None
            return await self._family(
                context, capture, response, AppendReceipt(new=0, duplicate=0, stale=0), result
            )
        before = await self._contexts.read(identity, request.expected_family_digest)
        _require(before == context, "authority changed during capture custody")
        owner = await self._sessions.claim(
            self._states,
            identity.request_scope,
            UUID(identity.harness_execution_id),
            generation=identity.generation,
            now=datetime.now(UTC),
            heartbeat_timeout_s=60,
        )
        _require(
            owner.lease_expires_at - datetime.now(UTC) > timedelta(seconds=30),
            "adoption owner lease is shorter than request bound",
        )
        after = await self._contexts.read(identity, request.expected_family_digest)
        # The owner claim may change only owner/revision metadata, never accepted
        # binding/run/dispatch/family authority. The frame adapter checks ownership
        # again inside the actual insertion transaction.
        _require(
            replace(
                after.authority,
                owner_epoch=context.authority.owner_epoch,
                harness_revision=context.authority.harness_revision,
                dispatch_revision=context.authority.dispatch_revision,
            )
            == context.authority,
            "execution frontier changed during adoption ownership",
        )
        _require(
            after.authority.owner_epoch == owner.epoch, "new owner not authoritatively read back"
        )
        handle = context.handle.model_copy(
            update={
                "last_cursor": await self._frames.last_cursor(
                    UUID(identity.harness_execution_id),
                    identity.generation,
                    request_scope=identity.request_scope,
                )
            }
        )
        writer = FrameWriter(_OwnedSink(self._frames, owner), handle)
        body = {
            "request_digest": sha256_digest(asdict(request)),
            "capture_digest": capture.manifest_digest,
            "response": response.model_dump(mode="json"),
            "source_evidence_digest": capture.source_evidence_digest,
            "authority": intent["authority"] if intent else asdict(context.authority),
        }
        key = (
            "mc.terminal-adoption:"
            + identity.harness_execution_id
            + ":"
            + str(identity.generation)
            + ":"
            + identity.native_turn_ref
        )
        terminal = {
            "status": "finished",
            "usage": {
                "inputTokens": capture.usage.input_tokens,
                "outputTokens": capture.usage.output_tokens,
                "totalTokens": capture.usage.total_tokens,
                "cacheReadTokens": capture.usage.cache_read_tokens,
                "cacheWriteTokens": capture.usage.cache_write_tokens,
                **(
                    {"charged_micros": capture.usage.cost_micros_usd}
                    if capture.usage.cost_micros_usd is not None
                    else {}
                ),
            },
            "result_summary_ref": response.object_ref,
            "capture_manifest_digest": capture.manifest_digest,
            "recovered_observation": True,
        }
        observations = [
            FrameObservation(
                provider_key="mc.terminal-adoption:" + request.request_id + ":intent",
                raw_kind="mc.terminal-adoption.intent",
                kind=FrameKind.STATUS,
                body=body,
                native_turn_ref=identity.native_turn_ref,
                observed_at=capture.observed_at,
            ),
            FrameObservation(
                provider_key=key + ":result",
                raw_kind="mc.terminal-adoption.run-result",
                kind=FrameKind.RUN_RESULT,
                body=terminal,
                native_turn_ref=identity.native_turn_ref,
                provider_timestamp=capture.native_finished_at,
                observed_at=capture.observed_at,
            ),
            FrameObservation(
                provider_key=key + ":turn-ended",
                raw_kind="mc.terminal-adoption.turn-ended",
                kind=FrameKind.TURN_ENDED,
                body=terminal,
                native_turn_ref=identity.native_turn_ref,
                provider_timestamp=capture.native_finished_at,
                observed_at=capture.observed_at,
            ),
        ]
        receipt = await writer.write(observations)
        _require(not receipt.stale, "terminal evidence generation became stale")
        await self._states.assert_owner(
            identity.request_scope, UUID(identity.harness_execution_id), owner
        )
        result = await self._operations.settle_lane_session(
            context.operation,
            facts,
            native_turn_ref=identity.native_turn_ref,
            cancelled_by_command=False,
            final_text=capture.result.decode(),
            existing_claim_id=context.authority.claim_id,
            expected_run_version=(
                intent["authority"]["run_version"] if intent else context.authority.run_version
            ),
            settlement_time=capture.observed_at,
        )
        await self._states.record(
            identity.request_scope,
            UUID(identity.harness_execution_id),
            LaneExecutionUpdate(usage_disposition=facts.cost_disposition),
            owner=owner,
        )
        return await self._family(context, capture, response, receipt, result)

    async def _family(
        self,
        context: TerminalAdoptionContext,
        capture: ValidatedTerminalCapture,
        response: ArtifactPayloadAddress,
        receipt: AppendReceipt,
        result: OperationExecutionResult,
    ) -> TerminalAdoptionResult:
        if context.pending_family_result is not None:
            # The genuine scheduled activity owns its family journal identity.
            # Adopting another payload would poison its exact-request replay.
            return TerminalAdoptionResult(
                response,
                receipt,
                result,
                None,
                ("normal_family_activity_pending",)
                + (
                    ("admitted_external_usage_pending",)
                    if result.usage.pending_external_amounts
                    else ()
                ),
            )
        if result.usage.pending_external_amounts:
            return TerminalAdoptionResult(
                response, receipt, result, None, ("admitted_external_usage_pending",)
            )
        _require(
            result.status in {"completed", "failed"},
            "terminal adoption did not settle conclusively",
        )
        family = await self._programs.decide_result(self._family_request(context, capture, result))
        _require(family.accepted, "normal family decision was not accepted")
        return TerminalAdoptionResult(
            response, receipt, result, family, ("closed_workflow_terminalization_required",)
        )

    def _family_request(
        self,
        context: TerminalAdoptionContext,
        capture: ValidatedTerminalCapture,
        result: OperationExecutionResult,
    ) -> StageGraphResultActivityRequest:
        disposition: Literal["completed", "failed"]
        if result.status == "completed":
            disposition = "completed"
        elif result.status == "failed":
            disposition = "failed"
        else:
            raise AdoptionInspectionRefused("terminal adoption did not settle conclusively")
        payload = result.model_dump(mode="json")
        if isinstance(result.structured_output, dict):
            payload.update(result.structured_output)
        observation = replace(
            context.family.observation,
            operation_result=payload,
            operation_disposition=disposition,
            child_closed_or_quiesced=True,
            reservations_and_usage_settled=True,
            effects_settled=True,
            cancellation_reconciled=True,
        )
        return replace(context.family, observation=observation, occurred_at=capture.observed_at)
