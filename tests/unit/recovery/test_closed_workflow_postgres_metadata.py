from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mission_control.adapters.postgres.closed_workflow import metadata_digest, validate_dispatches
from mission_control.application.execution.harness.dispatch import DispatchRecord
from mission_control.contracts.contracts import MissionControlRejected


def test_actual_uuid_and_datetime_metadata_are_canonical_json():
    value = {"session_id": uuid4(), "ended_at": datetime.now(UTC)}
    assert metadata_digest(value) == metadata_digest(
        {
            "session_id": str(value["session_id"]),
            "ended_at": value["ended_at"].isoformat().replace("+00:00", "Z"),
        }
    )


def record():
    return DispatchRecord(
        kind="create",
        idempotency_key="actual-key",
        expected_generation=1,
        instruction_digest="sha256:" + "a" * 64,
        owner_ref="owner",
        owner_epoch=1,
        intended_at=datetime.now(UTC),
        resolved_at=datetime.now(UTC),
        phase="acknowledged",
        native_ref="actual-native",
    )


def test_actual_production_dispatch_map_shape():
    item = record()
    validate_dispatches({"mc_dispatch": {item.key: item.model_dump(mode="json")}}, 1)


@pytest.mark.parametrize(
    "change", ["intended", "in_doubt", "wrong_key", "wrong_generation", "no_ref", "no_resolution"]
)
def test_unresolved_or_mismatched_native_dispatch_refuses(change):
    item = record()
    key = item.key
    updates = {
        "intended": {"phase": "intended"},
        "in_doubt": {"phase": "in_doubt"},
        "wrong_generation": {"expected_generation": 2},
        "no_ref": {"native_ref": None},
        "no_resolution": {"resolved_at": None},
    }.get(change, {})
    item = item.model_copy(update=updates)
    if change == "wrong_key":
        key = "unbound"
    with pytest.raises(MissionControlRejected):
        validate_dispatches({"mc_dispatch": {key: item.model_dump(mode="json")}}, 1)
