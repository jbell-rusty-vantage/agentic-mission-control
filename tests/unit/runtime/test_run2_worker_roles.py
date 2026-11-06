"""Lane workers never poll base queues or require base-worker authority."""

from types import SimpleNamespace

import pytest

from mission_control.adapters.temporal import worker
from mission_control.bootstrap.payload_custody import MARKER, verify_payload_custody
from tests.fixtures.isolated_settings import isolated_settings


def test_lane_role_only_registers_lane_activities(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "Worker", lambda client, **kw: calls.append(kw) or kw)
    monkeypatch.setattr(
        worker, "create_coordinator_workers", lambda *a, **kw: pytest.fail("base poller")
    )
    settings = isolated_settings(
        mission_control_worker_role="lane",
        mission_control_lane_task_queues=("wsl",),
        temporal_task_queue="mc",
    )
    composition = SimpleNamespace(
        coordinator=None, operation=SimpleNamespace(lane_activities=lambda: ("turn", "status"))
    )
    result = worker.create_production_workers(None, settings, composition)
    assert len(result.workers) == 1
    assert calls[0]["task_queue"] == "wsl"
    assert calls[0]["activities"] == ("turn", "status")
    assert result.coordinator is result.operation is result.artifacts is None


def test_lane_role_refuses_missing_queue(monkeypatch):
    settings = isolated_settings(mission_control_worker_role="lane", temporal_task_queue="mc")
    with pytest.raises(ValueError, match="explicit non-base"):
        worker.create_production_workers(None, settings, SimpleNamespace())


def test_split_host_requires_actual_marker_or_s3(tmp_path):
    settings = isolated_settings(
        mission_control_split_host=True, mission_control_payload_shared_id="shared-test"
    )
    with pytest.raises(ValueError, match="unavailable"):
        verify_payload_custody(settings, tmp_path)
    (tmp_path / MARKER).write_text("another-host")
    with pytest.raises(ValueError, match="differs"):
        verify_payload_custody(settings, tmp_path)
    (tmp_path / MARKER).write_text("shared-test\n")
    verify_payload_custody(settings, tmp_path)
    verify_payload_custody(
        settings.model_copy(update={"s3_bucket": "fixture-bucket"}), tmp_path / "absent"
    )
