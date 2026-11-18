"""Run-control repository contract: `InMemoryRunControlRepository` versus PostgreSQL.

Every scenario drives the repository through the real `RunControlService` (which decides the
mutations) and through the repository's own methods, and asserts what a caller observes:
admission and command decisions, idempotent replays, refusals, the outbox, consumer cursors,
the Temporal identity and scoping by tenant. The runners are
`tests/unit/run_control/test_run_control_contract.py` (in memory) and
`tests/integration/postgres/test_run_control_contract_postgres.py` (PostgreSQL).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest

from mission_control.application.execution.run_control_repository import (
    AdmissionMutation,
    CommandMutation,
    RunControlRepository,
    TemporalIdentityConflict,
)
from mission_control.application.execution.service import (
    RunControlService,
    accepted_admission_mutation,
)
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    ConsumerApplyStatus,
    DecisionStatus,
    LifecycleCommand,
    RunRequest,
    StartAction,
)
from mission_control.domain.policies.errors import (
    IdempotencyConflict,
    RunControlNotFound,
    RunVersionConflict,
)
from tests.support.run_control import NOW, ConfigurationVerifier, service
from tests.support.run_control import command as unit_command
from tests.support.run_control import request as unit_request

ADMISSION_EVENTS = ["workflow_run.admitted", "workflow_run.start_requested"]


class _Recording:
    """Delegates to the repository under test and keeps the mutations the service commits,
    so a scenario can replay an exact mutation against the repository itself."""

    def __init__(self, inner: RunControlRepository) -> None:
        self._inner = inner
        self.admissions: list[AdmissionMutation] = []
        self.commands: list[CommandMutation] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def commit_admission(self, mutation: AdmissionMutation) -> Any:
        self.admissions.append(mutation)
        return await self._inner.commit_admission(mutation)

    async def commit_command(self, mutation: CommandMutation) -> Any:
        self.commands.append(mutation)
        return await self._inner.commit_command(mutation)


@dataclass
class RunControlSubject:
    """The repository under test and two tenant scopes of one installation."""

    repository: RunControlRepository
    scope: str
    other_scope: str

    def service(self) -> tuple[RunControlService, _Recording]:
        recording = _Recording(self.repository)
        run_service, _ = service(recording)  # type: ignore[arg-type]
        return run_service, recording

    def request(self, request_id: str, *, scope: str | None = None, **kwargs: Any) -> RunRequest:
        return unit_request(request_scope=scope or self.scope, request_id=request_id, **kwargs)

    def command(
        self, run_id: str, version: int, command_id: str, action: object
    ) -> LifecycleCommand:
        return unit_command(run_id, version, command_id, action).model_copy(
            update={"request_scope": self.scope}
        )


Scenario = Callable[[RunControlSubject], Awaitable[None]]


async def _admit(subject: RunControlSubject, request_id: str) -> tuple[RunControlService, str]:
    run_service, _ = subject.service()
    decision = await run_service.admit(subject.request(request_id))
    assert decision.status == DecisionStatus.ACCEPTED
    assert decision.run_id is not None
    return run_service, decision.run_id


async def admission_is_recorded_and_readable(subject: RunControlSubject) -> None:
    repository = subject.repository
    run_service, _ = subject.service()
    decision = await run_service.admit(subject.request("admission-read"))
    assert decision.status == DecisionStatus.ACCEPTED and decision.run_id is not None
    run_id = decision.run_id

    assert await repository.get_admission_decision(subject.scope, "operator", "admission-read") == (
        decision
    )
    projection = await repository.get_run(subject.scope, run_id)
    assert (projection.run_id, projection.request_scope, projection.version) == (
        run_id,
        subject.scope,
        1,
    )
    assert (await repository.get_budget(subject.scope, run_id)).run_id == run_id
    assert (await repository.get_effects(subject.scope, run_id)).run_id == run_id
    transitions = await repository.list_transitions(subject.scope, run_id)
    assert [item.resulting_projection for item in transitions] == [projection]
    assert await repository.list_effect_ledger(subject.scope, run_id) == ()
    outbox = await repository.list_outbox(subject.scope)
    assert [item.envelope.event_type for item in outbox] == ADMISSION_EVENTS
    assert all(item.envelope.aggregate_id == run_id for item in outbox)
    # Outbox positions are strictly increasing, and the cursor pages forward.
    assert outbox[0].cursor.position < outbox[1].cursor.position
    assert await repository.list_outbox(subject.scope, limit=1) == outbox[:1]
    assert await repository.list_outbox(subject.scope, after=outbox[0].cursor) == outbox[1:]
    with pytest.raises(RunControlNotFound):
        await repository.get_run(subject.scope, "run-that-was-never-admitted")


async def admission_retry_is_idempotent(subject: RunControlSubject) -> None:
    repository = subject.repository
    run_service, recording = subject.service()
    first = await run_service.admit(subject.request("admission-retry"))
    assert first.status == DecisionStatus.ACCEPTED
    assert await run_service.admit(subject.request("admission-retry")) == first
    # The exact committed mutation replayed against the repository returns the same decision
    # and writes nothing new.
    assert await repository.commit_admission(recording.admissions[-1]) == first
    assert [
        item.envelope.event_type for item in await repository.list_outbox(subject.scope)
    ] == ADMISSION_EVENTS
    second = await run_service.admit(subject.request("admission-retry-other"))
    assert second.run_id not in {None, first.run_id}


async def admission_conflicting_retry_is_refused(subject: RunControlSubject) -> None:
    repository = subject.repository
    run_service, _ = subject.service()
    first = await run_service.admit(subject.request("admission-conflict"))
    changed = subject.request("admission-conflict", hard_cap=90)
    with pytest.raises(IdempotencyConflict):
        await run_service.admit(changed)
    mutation = accepted_admission_mutation(changed, await ConfigurationVerifier().verify(changed))
    with pytest.raises(IdempotencyConflict):
        await repository.commit_admission(mutation)
    assert (
        await repository.get_admission_decision(subject.scope, "operator", "admission-conflict")
        == first
    )
    assert len(await repository.list_outbox(subject.scope)) == len(ADMISSION_EVENTS)


async def command_is_accepted_and_replayed(subject: RunControlSubject) -> None:
    repository = subject.repository
    run_service, recording = subject.service()
    _, run_id = await _admit(subject, "command-replay")
    start = subject.command(run_id, 1, "start", StartAction())
    started = await run_service.execute(start)
    assert started.status == CommandStatus.ACCEPTED
    assert started.resulting_run_version == 2
    assert (await repository.get_run(subject.scope, run_id)).version == 2
    assert await repository.get_command_result(subject.scope, run_id, "operator", "start") == (
        started
    )
    assert await run_service.execute(start) == started
    # The exact committed mutation replays to the stored result without advancing the run.
    assert await repository.commit_command(recording.commands[-1]) == started
    assert (await repository.get_run(subject.scope, run_id)).version == 2
    assert len(await repository.list_transitions(subject.scope, run_id)) == 2
    assert await repository.get_command_result(subject.scope, run_id, "operator", "absent") is None
    assert (
        await repository.get_command_result(
            subject.scope, "run-never-admitted", "operator", "start"
        )
        is None
    )


async def command_conflicting_retry_is_refused(subject: RunControlSubject) -> None:
    repository = subject.repository
    run_service, recording = subject.service()
    _, run_id = await _admit(subject, "command-conflict")
    started = await run_service.execute(subject.command(run_id, 1, "start", StartAction()))
    with pytest.raises(IdempotencyConflict):
        await run_service.execute(subject.command(run_id, 1, "start", CancelAction()))
    committed = recording.commands[-1]
    changed = dataclasses.replace(
        committed,
        result=committed.result.model_copy(update={"command_fingerprint": "sha256:" + "f" * 64}),
    )
    with pytest.raises(IdempotencyConflict):
        await repository.commit_command(changed)
    assert await repository.get_command_result(subject.scope, run_id, "operator", "start") == (
        started
    )


async def command_against_a_moved_run_is_refused(subject: RunControlSubject) -> None:
    repository = subject.repository
    run_service, recording = subject.service()
    _, run_id = await _admit(subject, "command-stale")
    await run_service.execute(subject.command(run_id, 1, "start", StartAction()))
    accepted = recording.commands[-1]
    # An accepted mutation decided against version 1 cannot commit once the run is at 2.
    moved = dataclasses.replace(
        accepted,
        result=accepted.result.model_copy(update={"command_id": "start-again"}),
    )
    with pytest.raises(RunVersionConflict):
        await repository.commit_command(moved)
    assert (await repository.get_run(subject.scope, run_id)).version == 2
    assert await repository.get_command_result(
        subject.scope, run_id, "operator", "start-again"
    ) is (None)
    # A rejected command decided against an old version is recorded as stale.
    stale = await run_service.execute(subject.command(run_id, 1, "cancel-old", CancelAction()))
    assert stale.status in {CommandStatus.STALE, CommandStatus.REJECTED}
    assert stale.resulting_run_version == 2
    assert (await repository.get_run(subject.scope, run_id)).version == 2


async def scopes_are_isolated(subject: RunControlSubject) -> None:
    repository = subject.repository
    run_service, _ = subject.service()
    _, run_id = await _admit(subject, "isolated")
    await run_service.execute(subject.command(run_id, 1, "start", StartAction()))
    other = subject.other_scope
    for read in (
        repository.get_run,
        repository.get_budget,
        repository.get_effects,
        repository.list_transitions,
        repository.list_budget_ledger,
        repository.list_effect_ledger,
    ):
        with pytest.raises(RunControlNotFound):
            await read(other, run_id)
    # A command lookup is a scoped read: another tenant finds nothing.
    assert await repository.get_command_result(other, run_id, "operator", "start") is None
    assert await repository.get_admission_decision(other, "operator", "isolated") is None
    assert await repository.list_outbox(other) == ()
    event_id = (await repository.list_outbox(subject.scope))[0].envelope.event_id
    with pytest.raises(RunControlNotFound):
        await repository.mark_outbox_delivered(other, event_id, NOW)
    # The same request identity in another tenant admits a distinct run.
    elsewhere = await run_service.admit(subject.request("isolated", scope=other))
    assert elsewhere.status == DecisionStatus.ACCEPTED
    assert elsewhere.run_id not in {None, run_id}
    assert (await repository.get_run(subject.scope, run_id)).version == 2


async def outbox_delivery_and_consumer_cursor(subject: RunControlSubject) -> None:
    repository = subject.repository
    await _admit(subject, "outbox")
    first, second = await repository.list_outbox(subject.scope)
    # A consumer applies each authoritative event once, in order; a skipped event is a gap.
    gap = await repository.apply_consumer_event(subject.scope, "projector", second.envelope)
    assert gap.status == ConsumerApplyStatus.GAP
    applied = await repository.apply_consumer_event(subject.scope, "projector", first.envelope)
    assert applied.status == ConsumerApplyStatus.APPLIED
    duplicate = await repository.apply_consumer_event(subject.scope, "projector", first.envelope)
    assert duplicate.status == ConsumerApplyStatus.DUPLICATE
    assert duplicate.cursor == applied.cursor
    following = await repository.apply_consumer_event(subject.scope, "projector", second.envelope)
    assert following.status == ConsumerApplyStatus.APPLIED
    forged = first.envelope.model_copy(update={"payload": {"forged": True}})
    with pytest.raises(RunControlNotFound):
        await repository.apply_consumer_event(subject.scope, "projector", forged)

    await repository.mark_outbox_delivered(subject.scope, first.envelope.event_id, NOW)
    pending = await repository.list_outbox(subject.scope)
    assert [item.envelope.event_id for item in pending] == [second.envelope.event_id]
    with pytest.raises(RunControlNotFound):
        await repository.mark_outbox_delivered(subject.scope, "event-that-does-not-exist", NOW)


async def temporal_identity_is_written_once(subject: RunControlSubject) -> None:
    repository = subject.repository
    _, run_id = await _admit(subject, "temporal")
    await repository.record_temporal_ids(
        subject.scope, run_id, workflow_id="workflow-1", temporal_run_id="temporal-1"
    )
    # An equal identity and a re-launch that does not know the run id are no-ops.
    await repository.record_temporal_ids(
        subject.scope, run_id, workflow_id="workflow-1", temporal_run_id="temporal-1"
    )
    await repository.record_temporal_ids(
        subject.scope, run_id, workflow_id="workflow-1", temporal_run_id=None
    )
    with pytest.raises(TemporalIdentityConflict):
        await repository.record_temporal_ids(
            subject.scope, run_id, workflow_id="workflow-1", temporal_run_id="temporal-2"
        )
    with pytest.raises(RunControlNotFound):
        await repository.record_temporal_ids(
            subject.other_scope, run_id, workflow_id="workflow-1", temporal_run_id="temporal-1"
        )
    # A workflow id recorded without its run id still binds the run to that workflow.
    _, unbound = await _admit(subject, "temporal-unbound")
    await repository.record_temporal_ids(
        subject.scope, unbound, workflow_id="workflow-a", temporal_run_id=None
    )
    await repository.record_temporal_ids(
        subject.scope, unbound, workflow_id="workflow-a", temporal_run_id="temporal-a"
    )
    with pytest.raises(TemporalIdentityConflict):
        await repository.record_temporal_ids(
            subject.scope, unbound, workflow_id="workflow-b", temporal_run_id="temporal-b"
        )
    _, rebound = await _admit(subject, "temporal-rebound")
    await repository.record_temporal_ids(
        subject.scope, rebound, workflow_id="workflow-c", temporal_run_id=None
    )
    with pytest.raises(TemporalIdentityConflict):
        await repository.record_temporal_ids(
            subject.scope, rebound, workflow_id="workflow-d", temporal_run_id="temporal-d"
        )


SCENARIOS: tuple[Scenario, ...] = (
    admission_is_recorded_and_readable,
    admission_retry_is_idempotent,
    admission_conflicting_retry_is_refused,
    command_is_accepted_and_replayed,
    command_conflicting_retry_is_refused,
    command_against_a_moved_run_is_refused,
    scopes_are_isolated,
    outbox_delivery_and_consumer_cursor,
    temporal_identity_is_written_once,
)

__all__ = ["SCENARIOS", "RunControlSubject", "Scenario"]
