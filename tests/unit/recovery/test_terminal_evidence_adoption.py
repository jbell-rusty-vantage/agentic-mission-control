"""Real memory custody/frame/journal/run-control/family path; no provider controls."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from tests.fixtures.checkpoint_recovery import FixtureControlPlane
from tests.fixtures.lane_turns import RUN_UUID, SCOPE, cursor_operation, lane_stack
from tests.unit.operations.test_lane_admission_rejection import RejectionJournal
from tests.unit.orchestration.test_completion_validation_service import prepared
from tests.unit.run_control.test_run_control import actor, command

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    execution_start,
)
from mission_control.application.execution.harness.state import LaneExecutionUpdate
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    RunControlOperationAuthority,
    bind_operation_execution_request,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.recovery.terminal_evidence_adoption import (
    PERMISSION,
    TerminalAdoptionContext,
    TerminalAdoptionRequest,
    TerminalEvidenceAdoptionService,
)
from mission_control.application.recovery.terminal_evidence_capture import (
    RetainedTerminalCapture,
    capture_digest,
)
from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionAuthority,
    AdoptionIdentity,
    AdoptionInspectionRefused,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.frames.contracts import FrameKind, FrameObservation
from mission_control.domain.policies.contracts import CancelAction, CommandStatus


def adoption_actor():
    principal = actor()
    return principal.model_copy(update={"permissions": principal.permissions | {PERMISSION}})


class MemoryFencedFrames:
    def __init__(self, store, states):
        self.store, self.states = store, states

    async def last_cursor(self, *args, **kwargs):
        return await self.store.last_cursor(*args, **kwargs)

    async def append_fenced(self, frames, *, owner):
        for frame in frames:
            await self.states.assert_owner(
                frame.scope.request_scope, frame.harness_execution_id, owner
            )
            assert not owner.expired(datetime.now(UTC)) and frame.generation == owner.generation
            existing = await self.store.frames_for_execution(
                frame.scope.request_scope, frame.harness_execution_id, frame.generation
            )
            for prior in existing:
                if prior.provider_key == frame.provider_key:
                    assert prior.body_digest == frame.body_digest
        return await self.store.append(frames)


async def adoption_stack(*, currency=0, cost=None):
    fixture = await prepared(
        scope=SCOPE,
        operation_template=cursor_operation().model_copy(
            update={
                "budget_limits": {
                    "tokens.total": 1,
                    "operation.attempts": 1,
                    "concurrency.slots": 1,
                    **({"currency.estimated_micros": currency} if currency else {}),
                }
            }
        ),
        release_usage=False,
        currency_reservation=currency,
    )
    operation = fixture.operation
    assert operation is not None
    stack = lane_stack(operation=operation)
    binding = bind_operation_execution_request(operation)
    await stack.bindings.create_binding(binding)

    class ExistingJournal(RejectionJournal):
        async def get_claim(self, scope, claim_id):
            claim = self.claims.get(claim_id)
            return claim if claim is not None and claim.request_scope == scope else None

    journal, payloads = ExistingJournal(), InMemoryArtifactPayloadStore()
    coordinator = JournaledOperationExecutionCoordinator(
        journal=journal, run_control=fixture.run_control, results=payloads, actor=actor()
    )
    stack.boundary._journal = coordinator
    stack.boundary._authority = RunControlOperationAuthority(
        fixture.run_control, FixtureControlPlane(operation)
    )
    claim = await coordinator.acquire(binding, claimed_by="existing-native-fixture")
    assert claim.claim is not None
    current = await fixture.run_control.get_run(SCOPE, operation.identity.run_id)
    cancelled = await fixture.run_control.execute(
        command(current.run_id, current.version, "cancel-before-adopt", CancelAction()).model_copy(
            update={"request_scope": SCOPE}
        )
    )
    assert cancelled.status == CommandStatus.ACCEPTED
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    handle = await stack.frames.open_execution(
        execution_start(operation, identity, 1, "agent-existing")
    )
    await FrameWriter(stack.frames, handle).write(
        [
            FrameObservation(
                provider_key="native-start",
                raw_kind="native.turn-started",
                kind=FrameKind.TURN_STARTED,
                body={},
                native_turn_ref="native-run-existing",
            )
        ]
    )
    old = await stack.states.claim_owner(
        SCOPE,
        handle.harness_execution_id,
        owner_ref="expired-native-owner",
        generation=1,
        now=datetime.now(UTC) - timedelta(days=1),
        lease=timedelta(seconds=10),
    )
    await stack.states.record(
        SCOPE,
        handle.harness_execution_id,
        LaneExecutionUpdate(
            native_session_ref="agent-existing", native_turn_ref="native-run-existing"
        ),
        owner=old,
    )
    adopted = AdoptionIdentity(
        SCOPE,
        operation.identity.run_id,
        str(RUN_UUID),
        str(handle.harness_execution_id),
        1,
        "agent-existing",
        "native-run-existing",
    )
    response = b'{"summary":"retained native response"}'
    document = {
        "schema_version": "mc.terminal_lane_capture.v1",
        "identity": asdict(adopted),
        "native_status": "FINISHED",
        "result_digest": capture_digest(response),
        "result_size": len(response),
        "usage": {
            "inputTokens": 1,
            "outputTokens": 0,
            "totalTokens": 1,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
        },
        "cost_micros_usd": cost,
        "observed_at": datetime.now(UTC).isoformat(),
        "native_finished_at": (datetime.now(UTC) - timedelta(seconds=2)).isoformat(),
        "source_evidence_digest": "sha256:" + "a" * 64,
    }
    capture = RetainedTerminalCapture(json.dumps(document).encode(), response)

    class Captures:
        async def load_verified(self, identity, reference):
            assert identity == adopted and reference == "verified-private-fixture"
            return capture

    class Contexts:
        async def read(self, identity, family_digest):
            assert identity == adopted and family_digest == fixture.result.projection.digest
            run = await fixture.run_control.get_run(SCOPE, operation.identity.run_id)
            state = await stack.states.load(SCOPE, handle.harness_execution_id)
            assert state and state.owner
            budget = await fixture.run_control.get_budget(SCOPE, operation.identity.run_id)
            pending = any(item.pending_external_usage for item in journal.settlements.values())
            authority = AdoptionAuthority(
                adopted,
                run.version,
                run.phase.value,
                "ended"
                if journal.settlements
                or stack.frames.sessions(handle.harness_execution_id)
                .get("agent-existing", {})
                .get("state")
                == "closed"
                else "live",
                "reconciliation_required"
                if pending
                else "settled"
                if journal.settlements
                else "claimed",
                binding.binding_id,
                sha256_digest(binding),
                claim.claim.effect_claim_id,
                100 + state.owner.epoch,
                state.owner.epoch,
                100 + state.owner.epoch,
                "sha256:" + "d" * 64,
                True,
                (await fixture.journal()).next_projection_digest,
                "cancel-before-adopt",
                2,
                "delivered",
                bool(
                    currency
                    and (
                        budget.reservations.get(operation.budget_reservation_id, {}).get(
                            "currency.estimated_micros", 0
                        )
                        + budget.pending_settlement.get("currency.estimated_micros", 0)
                    )
                    >= currency
                ),
                currency,
            )
            return TerminalAdoptionContext(authority, operation, handle, fixture.result)

    contexts = Contexts()
    initial = await contexts.read(adopted, fixture.result.projection.digest)
    request = TerminalAdoptionRequest(
        str(uuid4()),
        adopted,
        sha256_digest(asdict(initial.authority)),
        fixture.result.projection.digest,
        "verified-private-fixture",
        capture_digest(capture.manifest),
    )
    service = TerminalEvidenceAdoptionService(
        contexts=contexts,
        captures=Captures(),
        states=stack.states,
        frames=MemoryFencedFrames(stack.frames, stack.states),
        reader=stack.frames,
        payloads=payloads,
        operations=stack.boundary,
        programs=fixture.service,
    )
    return service, request, fixture, stack, journal, payloads


async def test_finished_evidence_adopts_without_native_control_and_normal_family_quarantines():
    service, request, fixture, stack, journal, payloads = await adoption_stack()
    result = await service.adopt(request, adoption_actor())
    assert result.operation.status == "completed" and result.operation.usage.amounts == {
        "tokens.total": 1
    }
    assert result.family and result.family.proposal.decision.value == "quarantine"
    assert result.family.proposal.quarantine_reason == "run_cancelling"
    assert all(item.closed for item in result.family.projection.producer_liabilities.values())
    assert result.provider_acknowledged is False and stack.lane.calls == []
    assert len(journal.settlements) == 1
    assert not (
        await fixture.run_control.get_run(SCOPE, request.identity.public_run_key)
    ).accepted_output_evidence
    assert await payloads.retrieve(result.response) == b'{"summary":"retained native response"}'
    replay = await service.adopt(request, adoption_actor())
    assert replay.operation == result.operation and replay.family == result.family
    assert replay.frames.new == 0 and len(journal.settlements) == 1 and stack.lane.calls == []


async def test_changed_capture_or_authority_refuses_before_any_custody_or_native_action():
    service, request, _, stack, journal, payloads = await adoption_stack()
    for changed in (
        replace(request, capture_digest="sha256:" + "f" * 64),
        replace(request, expected_authority_digest="sha256:" + "e" * 64),
    ):
        with pytest.raises(AdoptionInspectionRefused):
            await service.adopt(changed, adoption_actor())
    assert not payloads.payloads and not journal.settlements and stack.lane.calls == []


@pytest.mark.parametrize(
    "drift",
    [
        None,
        "dispatch_digest",
        "cancel_command_id",
        "admitted_currency_micros",
        "family_head_digest",
    ],
)
async def test_crash_after_frames_replays_only_its_unchanged_authority(monkeypatch, drift):
    service, request, _fixture, stack, journal, _ = await adoption_stack()
    settle = stack.boundary.settle_lane_session

    async def crash(*args, **kwargs):
        raise RuntimeError("fixture crash after persisted frames")

    monkeypatch.setattr(stack.boundary, "settle_lane_session", crash)
    with pytest.raises(RuntimeError, match="fixture crash"):
        await service.adopt(request, adoption_actor())
    assert not journal.settlements
    before = await stack.frames.frames_for_execution(
        SCOPE, UUID(request.identity.harness_execution_id), 1
    )
    assert len(before) == 4
    monkeypatch.setattr(stack.boundary, "settle_lane_session", settle)
    if drift:
        read = service._contexts.read

        async def changed(*args):
            context = await read(*args)
            value = 100 if drift == "admitted_currency_micros" else "changed"
            return replace(context, authority=replace(context.authority, **{drift: value}))

        monkeypatch.setattr(service._contexts, "read", changed)
        with pytest.raises(AdoptionInspectionRefused):
            await service.adopt(request, adoption_actor())
        assert not journal.settlements
    else:
        recovered = await service.adopt(request, adoption_actor())
        assert recovered.frames.new == 0 and len(journal.settlements) == 1
        assert recovered.family and recovered.family.proposal.decision.value == "quarantine"
    assert stack.lane.calls == []
    assert len(
        await stack.frames.frames_for_execution(
            SCOPE, UUID(request.identity.harness_execution_id), 1
        )
    ) == len(before)


async def test_actor_permission_checked_before_capture_or_storage(monkeypatch):
    from mission_control.contracts.contracts import MissionControlRejected

    service, request, _, stack, journal, payloads = await adoption_stack()
    with pytest.raises(MissionControlRejected, match="required"):
        await service.adopt(request, actor())
    assert not payloads.payloads and not journal.settlements and stack.lane.calls == []


@pytest.mark.parametrize("seam", ["after_observation", "after_authority", "before_family"])
async def test_partial_real_authority_progress_replays_without_double_usage(monkeypatch, seam):
    from mission_control.domain.policies.contracts import ApplyAuthorityBatchAction

    service, request, fixture, stack, journal, _ = await adoption_stack()
    execute = fixture.run_control.execute
    decide = fixture.service.decide_result
    if seam == "after_observation":

        async def stopped(value):
            if isinstance(value.action, ApplyAuthorityBatchAction):
                raise RuntimeError("fixture authority seam")
            return await execute(value)

        monkeypatch.setattr(fixture.run_control, "execute", stopped)
    elif seam == "after_authority":
        journal.crash_settlement = True
    else:

        async def stopped_family(value):
            raise RuntimeError("fixture family seam")

        monkeypatch.setattr(fixture.service, "decide_result", stopped_family)
    with pytest.raises(RuntimeError):
        await service.adopt(request, adoption_actor())
    monkeypatch.setattr(fixture.run_control, "execute", execute)
    monkeypatch.setattr(fixture.service, "decide_result", decide)
    result = await service.adopt(request, adoption_actor())
    budget = await fixture.run_control.get_budget(SCOPE, request.identity.public_run_key)
    assert result.family and result.family.accepted
    assert len(journal.settlements) == 1
    assert len([item for item in budget.usage_records.values() if item.authority_ref]) == 1
    assert result.frames.new == 0 and stack.lane.calls == []


async def test_concurrent_run_version_advance_cannot_be_settled_as_current(monkeypatch):
    service, request, fixture, stack, journal, _ = await adoption_stack()
    execute = fixture.run_control.execute

    async def advance_then_execute(value):
        monkeypatch.setattr(fixture.run_control, "execute", execute)
        current = await fixture.run_control.get_run(SCOPE, request.identity.public_run_key)
        await execute(
            command(
                current.run_id, current.version, "concurrent-cancel", CancelAction()
            ).model_copy(update={"request_scope": SCOPE})
        )
        return await execute(value)

    monkeypatch.setattr(fixture.run_control, "execute", advance_then_execute)
    with pytest.raises(RuntimeError, match="effect observation"):
        await service.adopt(request, adoption_actor())
    budget = await fixture.run_control.get_budget(SCOPE, request.identity.public_run_key)
    assert not journal.settlements and not budget.usage_records
    assert stack.lane.calls == []


async def test_known_admitted_currency_discharges_and_replays_after_family_crash(monkeypatch):
    service, request, fixture, stack, journal, _ = await adoption_stack(currency=100, cost=20)
    decide = fixture.service.decide_result

    async def stopped(value):
        raise RuntimeError("family crash after currency settlement")

    monkeypatch.setattr(fixture.service, "decide_result", stopped)
    with pytest.raises(RuntimeError, match="family crash"):
        await service.adopt(request, adoption_actor())
    monkeypatch.setattr(fixture.service, "decide_result", decide)
    result = await service.adopt(request, adoption_actor())
    assert result.family and result.family.accepted
    budget = await fixture.run_control.get_budget(SCOPE, request.identity.public_run_key)
    assert budget.consumed["currency.estimated_micros"] == 20
    assert not budget.pending_settlement.get("currency.estimated_micros")
    assert len(journal.settlements) == 1 and stack.lane.calls == []


async def test_unknown_admitted_currency_remains_pending_on_exact_replay():
    service, request, fixture, stack, journal, _ = await adoption_stack(currency=100)
    first = await service.adopt(request, adoption_actor())
    replay = await service.adopt(request, adoption_actor())
    assert first.family is None and replay.family is None
    assert replay.remaining_liabilities == ("admitted_external_usage_pending",)
    budget = await fixture.run_control.get_budget(SCOPE, request.identity.public_run_key)
    assert budget.pending_settlement["currency.estimated_micros"] == 100
    assert len(journal.settlements) == 1 and stack.lane.calls == []
