"""Recovery 2026-10-09: a worker serves the lane task queues its launch bindings route to.

Cursor, Claude and Codex bindings carry the `task_queue` their `lane.*` activities run on;
production polled only `<base>.agent-cognitive`, so a binding routed to a dedicated lane queue
was never served. `MISSION_CONTROL_LANE_TASK_QUEUES` names the extra queues of this worker.
A lane-role worker serves only those queues with lane activities, and a split host needs the
shared payload custody marker (or S3).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.adapters.temporal import worker as module
from mission_control.bootstrap.payload_custody import MARKER, verify_payload_custody
from tests.fixtures.isolated_settings import isolated_settings


def _record(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    queues: list[str] = []

    def cognitive(_client: Any, *, task_queue: str, **_values: Any) -> str:
        queues.append(task_queue)
        return task_queue

    monkeypatch.setattr(module, "create_agent_cognitive_worker", cognitive)
    monkeypatch.setattr(
        module, "create_coordinator_workers", lambda *_a, **_k: SimpleNamespace(workers=())
    )
    return queues


def test_lane_queues_are_polled_with_the_cognitive_activities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queues = _record(monkeypatch)
    settings = isolated_settings(
        temporal_task_queue="mc",
        mission_control_lane_task_queues=("mc-lane-claude", "mc-lane-codex", "mc-lane-claude"),
    )
    composition = SimpleNamespace(coordinator=object(), operation=object(), artifacts=None)
    workers = module.create_production_workers(None, settings, composition)  # type: ignore[arg-type]
    cognitive = module.BellLabsTaskQueues.from_base("mc").agent_cognitive
    assert queues == [cognitive, "mc-lane-claude", "mc-lane-codex"]
    assert workers.lanes == ("mc-lane-claude", "mc-lane-codex")
    assert workers.workers[-2:] == ("mc-lane-claude", "mc-lane-codex")


def test_no_lane_queue_and_the_cognitive_queue_itself_add_no_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queues = _record(monkeypatch)
    cognitive = module.BellLabsTaskQueues.from_base("mc").agent_cognitive
    settings = isolated_settings(
        temporal_task_queue="mc", mission_control_lane_task_queues=(cognitive,)
    )
    composition = SimpleNamespace(coordinator=object(), operation=object(), artifacts=None)
    workers = module.create_production_workers(None, settings, composition)  # type: ignore[arg-type]
    assert queues == [cognitive] and workers.lanes == ()


def test_a_lane_role_worker_registers_only_lane_activities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run 2: a lane worker never polls the base queues or needs base-worker authority."""

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(module, "Worker", lambda client, **kw: calls.append(kw) or kw)
    monkeypatch.setattr(
        module, "create_coordinator_workers", lambda *a, **kw: pytest.fail("base poller")
    )
    settings = isolated_settings(
        mission_control_worker_role="lane",
        mission_control_lane_task_queues=("wsl",),
        temporal_task_queue="mc",
    )
    composition = SimpleNamespace(
        coordinator=None, operation=SimpleNamespace(lane_activities=lambda: ("turn", "status"))
    )
    result = module.create_production_workers(None, settings, composition)  # type: ignore[arg-type]
    assert len(result.workers) == 1
    assert calls[0]["task_queue"] == "wsl"
    assert calls[0]["activities"] == ("turn", "status")
    assert result.coordinator is result.operation is result.artifacts is None


def test_a_lane_role_worker_refuses_a_missing_lane_queue() -> None:
    settings = isolated_settings(mission_control_worker_role="lane", temporal_task_queue="mc")
    with pytest.raises(ValueError, match="explicit non-base"):
        module.create_production_workers(None, settings, SimpleNamespace())  # type: ignore[arg-type]


def test_a_split_host_requires_the_actual_payload_custody_marker_or_s3(tmp_path: Path) -> None:
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
