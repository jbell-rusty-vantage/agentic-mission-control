"""1.4.4 (TRACING-PROPOSAL P3.2, P3.8, TR-D7): joinable mission events, the `record_rollover`
action and the Temporal identity of a run, over the reducer and the in-memory repository."""

from __future__ import annotations

from uuid import UUID

import pytest

from mission_control.adapters.postgres.run_control.canonical import event_joinability
from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
    TemporalIdentityConflict,
)
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.domain.authoring.canonical import canonical_json, contract_fingerprint
from mission_control.domain.policies.contracts import (
    BOUNDARY_FACT_KINDS,
    CommandStatus,
    DomainEventEnvelope,
    LifecycleCommand,
    RecordRolloverAction,
    StartAction,
)
from mission_control.domain.policies.errors import RunControlNotFound
from mission_control.domain.policies.reducer import ACTION_PERMISSIONS, required_action_permissions
from tests.unit.run_control.test_run_control import (
    ALL_PERMISSIONS,
    actor,
    command,
    request,
    service,
)

UNIT_KEY = "bl-unit-v1:" + "0" * 64
ACTIVATION = "7d4f0c1e-1111-4a2b-9c3d-000000000003"
POINT = {"kind": "checkpoint", "thread_id": "t", "checkpoint_ns": "", "checkpoint_id": "c1"}


def _joinable(base: LifecycleCommand) -> LifecycleCommand:
    return base.model_copy(
        update={"unit_key": UNIT_KEY, "activation_id": ACTIVATION, "point_ref": POINT}
    )


def test_unset_joinability_keeps_existing_command_bytes_and_fingerprints() -> None:
    plain = command("run-1", 1, "start", StartAction())
    dumped = plain.model_dump(mode="json")
    assert not {"unit_key", "activation_id", "point_ref"} & set(dumped)
    assert b"unit_key" not in canonical_json(plain)
    assert contract_fingerprint(plain, exclude={"occurred_at"}) == contract_fingerprint(
        plain.model_copy(update={"unit_key": None}), exclude={"occurred_at"}
    )
    joinable = _joinable(plain)
    assert joinable.model_dump(mode="json")["unit_key"] == UNIT_KEY
    assert contract_fingerprint(joinable, exclude={"occurred_at"}) != contract_fingerprint(
        plain, exclude={"occurred_at"}
    )
    with pytest.raises(ValueError, match="unit_key"):
        LifecycleCommand.model_validate(
            {**plain.model_dump(mode="python"), "unit_key": "not-a-unit-key"}
        )


@pytest.mark.asyncio
async def test_reducer_stamps_the_command_joinability_on_its_events() -> None:
    run_service, _repository = service()
    admitted = await run_service.admit(request())
    assert admitted.run_id is not None
    run_id = admitted.run_id
    started = await run_service.execute(_joinable(command(run_id, 1, "start", StartAction())))
    assert started.status == CommandStatus.ACCEPTED
    events = [
        item.envelope
        for item in await run_service.pending_outbox("tenant-1")
        if item.envelope.event_type == "workflow_run.start"
    ]
    assert len(events) == 1
    event = events[0]
    assert (event.unit_key, event.activation_id, event.point_ref) == (UNIT_KEY, ACTIVATION, POINT)
    assert DomainEventEnvelope.model_validate(event.model_dump(mode="json")) == event
    # Run-level events without the fields keep them unset and unserialized.
    admission = next(
        item.envelope
        for item in await run_service.pending_outbox("tenant-1")
        if item.envelope.event_type != "workflow_run.start"
    )
    assert admission.unit_key is None and "unit_key" not in admission.model_dump(mode="json")


def test_event_joinability_binds_uuid_activations_and_json_points() -> None:
    base = {
        "event_id": "event-1",
        "event_type": "workflow_run.start",
        "aggregate_id": "run-1",
        "aggregate_version": 1,
        "sequence": 1,
        "occurred_at": "2026-10-21T00:00:00Z",
        "recorded_at": "2026-10-21T00:00:00Z",
        "actor": actor(),
        "correlation_id": "c",
        "payload": {},
    }
    joinable = DomainEventEnvelope.model_validate(
        {**base, "unit_key": UNIT_KEY, "activation_id": ACTIVATION, "point_ref": POINT}
    )
    activation, unit_key, point_ref = event_joinability(joinable)
    assert activation == UUID(ACTIVATION) and unit_key == UNIT_KEY
    assert point_ref is not None and '"checkpoint_id":"c1"' in point_ref.replace(" ", "")
    textual = DomainEventEnvelope.model_validate({**base, "activation_id": "activation-1"})
    assert event_joinability(textual) == (None, None, None)
    assert event_joinability(DomainEventEnvelope.model_validate(base)) == (None, None, None)


@pytest.mark.asyncio
async def test_record_rollover_writes_one_event_and_never_moves_the_phase() -> None:
    action = RecordRolloverAction(
        technical_segment=2,
        session_generation=3,
        rollover_count=1,
        handoff_ref="handoff-7",
        closing_temporal_run_id="temporal-run-1",
    )
    assert ACTION_PERMISSIONS["record_rollover"] == "workflow_run.control"
    assert required_action_permissions(action) == frozenset({"workflow_run.control"})
    assert "record_rollover" in BOUNDARY_FACT_KINDS
    assert "workflow_run.control" in orchestration_lifecycle_actor().permissions
    permitted = actor().model_copy(
        update={"permissions": ALL_PERMISSIONS | {"workflow_run.control"}}
    )

    run_service, _repository = service()
    admitted = await run_service.admit(request())
    assert admitted.run_id is not None
    run_id = admitted.run_id
    pending = await run_service.execute(
        command(run_id, 1, "rollover-0", action).model_copy(update={"actor": permitted})
    )
    assert pending.status == CommandStatus.REJECTED and pending.reason_code == "invalid_phase"
    started = await run_service.execute(command(run_id, 1, "start", StartAction()))
    assert started.status == CommandStatus.ACCEPTED
    rolled = await run_service.execute(
        command(run_id, 2, "rollover-1", action).model_copy(
            update={"actor": permitted, "unit_key": UNIT_KEY}
        )
    )
    assert rolled.status == CommandStatus.ACCEPTED
    assert rolled.phase == started.phase and rolled.resulting_run_version == 3
    events = [
        item.envelope
        for item in await run_service.pending_outbox("tenant-1")
        if item.envelope.event_type == "workflow_run.record_rollover"
    ]
    assert len(events) == 1
    payload = events[0].payload
    assert payload["technical_segment"] == 2 and payload["session_generation"] == 3
    assert payload["rollover_count"] == 1 and payload["handoff_ref"] == "handoff-7"
    assert payload["closing_temporal_run_id"] == "temporal-run-1"
    assert payload["prior_phase"] == payload["resulting_phase"] == "active"
    assert events[0].unit_key == UNIT_KEY
    # Idempotent through the command receipt: the same command returns the stored result.
    again = await run_service.execute(
        command(run_id, 2, "rollover-1", action).model_copy(
            update={"actor": permitted, "unit_key": UNIT_KEY}
        )
    )
    assert again == rolled
    # Without the permission the fact is refused.
    with pytest.raises(Exception, match="workflow_run.control"):
        await run_service.execute(command(run_id, 3, "rollover-2", action))


@pytest.mark.asyncio
async def test_in_memory_temporal_ids_are_write_once_and_idempotent_on_equal_values() -> None:
    run_service, repository = service()
    admitted = await run_service.admit(request())
    assert admitted.run_id is not None
    run_id = admitted.run_id
    assert isinstance(repository, InMemoryRunControlRepository)
    with pytest.raises(RunControlNotFound):
        await repository.record_temporal_ids(
            "tenant-1", "missing", workflow_id="w", temporal_run_id="r"
        )
    await repository.record_temporal_ids(
        "tenant-1", run_id, workflow_id="belllabs-run/x", temporal_run_id="run-a"
    )
    await repository.record_temporal_ids(
        "tenant-1", run_id, workflow_id="belllabs-run/x", temporal_run_id="run-a"
    )
    assert repository.temporal_ids("tenant-1", run_id) == ("belllabs-run/x", "run-a")
    with pytest.raises(TemporalIdentityConflict) as conflict:
        await repository.record_temporal_ids(
            "tenant-1", run_id, workflow_id="belllabs-run/x", temporal_run_id="run-b"
        )
    assert (conflict.value.recorded, conflict.value.offered) == ("run-a", "run-b")
    assert repository.temporal_ids("tenant-1", run_id) == ("belllabs-run/x", "run-a")
