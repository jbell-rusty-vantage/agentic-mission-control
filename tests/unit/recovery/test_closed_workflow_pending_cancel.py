"""Exact pending cancel eligibility; the real terminalizing commit owns receipts."""

from copy import deepcopy
from uuid import uuid4

import pytest
from tests.unit.recovery.test_closed_workflow import setup_recovery
from tests.unit.run_control.test_run_control import NOW, actor

from mission_control.adapters.postgres.closed_workflow import (
    command_allows_cancelled_terminalization,
)
from mission_control.domain.policies.contracts import CommandStatus, ReceiptState


def stored_row(status):
    record, first = status.command, status.receipts[0]
    return {
        # This physical UUID intentionally differs from the public command identity.
        "command_id": uuid4(),
        "lifecycle": status.state.value,
        "command_kind": record.kind,
        "payload": {
            "record": record.model_dump(mode="json"),
            "initial_receipt": first.model_dump(mode="json"),
        },
        "payload_digest": record.payload_digest,
        "target_kind": record.target.kind,
        "target_ref": record.target.target_ref,
        "target_generation": record.target.execution_generation,
        "target_version": record.accepted_run_version,
        "target_sequence": record.target_sequence,
        "sequence_space": record.target.sequence_space,
    }


async def cancel_status(controls, run_id):
    return next(
        item
        for item in await controls.list_boundary_commands("tenant-1", run_id)
        if item.command.kind == "cancel"
    )


@pytest.mark.parametrize("delivered", [False, True])
async def test_pending_cancel_finishes_through_real_terminal_commit(delivered):
    recovery, controls, _, authority, _, body, run_id = await setup_recovery()
    status = await cancel_status(controls, run_id)
    if delivered:
        status = await controls.record_boundary_receipt(
            "tenant-1",
            status.receipts[0].model_copy(
                update={"state": ReceiptState.DELIVERED, "ordinal": 2, "recorded_at": NOW}
            ),
        )
    row = stored_row(status)
    original = authority.read.return_value

    async def exact_pending_cancel(run):
        assert command_allows_cancelled_terminalization(row, run)
        return original

    authority.read.side_effect = exact_pending_cancel
    result = await recovery.recover("tenant-1", run_id, body, actor())
    assert result.status == CommandStatus.ACCEPTED
    applied = await cancel_status(controls, run_id)
    assert applied.state == ReceiptState.APPLIED
    assert applied.receipts[-1].applied_run_version == result.resulting_run_version
    assert applied.receipts[-1].recorded_by == "run_control"
    assert "provider_acknowledged" not in str(applied.model_dump())
    assert await recovery.recover("tenant-1", run_id, body, actor()) == result
    assert await cancel_status(controls, run_id) == applied


@pytest.mark.parametrize(
    "change",
    [
        "pause",
        "foreign_scope",
        "foreign_run",
        "generation",
        "epoch",
        "target",
        "sequence",
        "sequence_space",
        "digest",
        "initial_identity",
        "initial_state",
        "future_version",
        "payload_missing",
        "queued",
        "active_run",
    ],
)
async def test_other_pending_or_tampered_commands_refuse(change):
    _, controls, _, _, _, _, run_id = await setup_recovery()
    run = await controls.get_run("tenant-1", run_id)
    row = deepcopy(stored_row(await cancel_status(controls, run_id)))
    record = row["payload"]["record"]
    if change == "pause":
        record.update(kind="pause", action={"kind": "pause"})
        row["command_kind"] = "pause"
    elif change in {"foreign_scope", "foreign_run"}:
        record["request_scope" if change == "foreign_scope" else "run_id"] = "foreign"
    elif change in {"generation", "epoch", "target"}:
        key = {
            "generation": "execution_generation",
            "epoch": "execution_epoch",
            "target": "target_ref",
        }[change]
        record["target"][key] = "wrong" if key == "target_ref" else 99
    elif change == "sequence":
        row["target_sequence"] += 1
    elif change == "sequence_space":
        row["sequence_space"] = "execution"
    elif change == "digest":
        row["payload_digest"] = "sha256:" + "f" * 64
    elif change == "initial_identity":
        row["payload"]["initial_receipt"]["command_id"] = "other"
    elif change == "initial_state":
        row["payload"]["initial_receipt"]["state"] = "delivered"
    elif change == "future_version":
        record["accepted_run_version"] = run.version + 1
    elif change == "payload_missing":
        row["payload"] = {}
    elif change == "queued":
        row["lifecycle"] = "queued"
    elif change == "active_run":
        run = run.model_copy(update={"phase": "active"})
    assert not command_allows_cancelled_terminalization(row, run)
