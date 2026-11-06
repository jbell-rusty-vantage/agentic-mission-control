"""Active startup recovery inspects and hints only; no native create/send/cleanup."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from temporalio.client import WorkflowExecutionStatus

from mission_control.adapters.cursor import bridge_spawn
from mission_control.adapters.cursor.bridge_recovery import ActiveBridgeContext
from mission_control.application.agentic_components.placement import STATE_ROOT
from mission_control.application.execution.harness.dispatch import DispatchRecord
from mission_control.application.execution.harness.state import LaneExecutionState
from mission_control.bootstrap import cursor_bridges
from tests.unit.cursor.test_run2_released_bridge_sweep import lease


def context(root):
    candidate = lease(root, released_at=None, observed_state="active")
    acknowledged = DispatchRecord(
        kind="send",
        idempotency_key="send",
        expected_generation=1,
        instruction_digest="digest",
        owner_ref="prior",
        owner_epoch=1,
        intended_at=datetime.now(UTC),
        phase="acknowledged",
        native_ref="run-1",
    )
    return ActiveBridgeContext(
        lease=candidate,
        state=LaneExecutionState(
            harness_execution_id=candidate.harness_execution_id,
            native_session_ref="agent",
            native_turn_ref="run-1",
            dispatches={acknowledged.key: acknowledged},
        ),
        lifecycle="live",
        workflow_id="operation",
        root_workflow_id="root",
        temporal_address="127.0.0.1:7233",
        temporal_namespace="default",
        temporal_target="local",
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, "recovery_notified"),
        ({"lifecycle": "ended"}, "custody_required"),
        ({"temporal_address": "other"}, "custody_required"),
        ({"parent": "foreign"}, "custody_required"),
        ({"closed": True}, "custody_required"),
        ({"anchor": False}, "ambiguous_anchor"),
        ({"native": "ambiguous_anchor"}, "ambiguous_anchor"),
        ({"native": "unavailable"}, "unavailable"),
    ],
)
async def test_only_exact_existing_running_child_is_notified(
    tmp_path, monkeypatch, change, expected
):
    value = context(tmp_path)
    value = replace(
        value,
        **{key: val for key, val in change.items() if key in {"lifecycle", "temporal_address"}},
    )
    if change.get("anchor") is False:
        value = replace(value, state=value.state.model_copy(update={"dispatches": {}}))
    calls = []

    async def native(**kwargs):
        calls.append("inspect")
        return change.get("native", "aligned")

    monkeypatch.setattr(cursor_bridges, "inspect_active_bridge", native)

    class Client:
        namespace = "default"

        def get_workflow_handle(self, workflow, *, run_id=None):
            assert workflow == "operation"
            calls.append(("handle", run_id))
            return self

        async def describe(self):
            return SimpleNamespace(
                id="operation",
                run_id="execution-1",
                parent_id=change.get("parent", "root"),
                status=WorkflowExecutionStatus.COMPLETED
                if change.get("closed")
                else WorkflowExecutionStatus.RUNNING,
            )

        async def signal(self, name, receipt):
            assert name == "ingress_wake" and receipt.startswith("cursor-recovery:")
            calls.append("signal")

    settings = SimpleNamespace(
        temporal_address="127.0.0.1:7233", temporal_namespace="default", temporal_target="local"
    )
    assert await cursor_bridges.inspect_active_cursor_context(value, settings, Client()) == expected
    assert ("signal" in calls) == (expected == "recovery_notified")
    if "signal" in calls:
        assert calls[-2] == ("handle", "execution-1")
    assert not value.lease.released and value.lease.workspace_snapshot is None


@pytest.mark.parametrize(
    ("runs", "pending", "expected"),
    [
        (["run-1"], False, "aligned"),
        (["new", "run-1"], True, "aligned"),
        (["new", "run-1"], False, "ambiguous_anchor"),
        (["new", "other", "run-1"], True, "ambiguous_anchor"),
        (["foreign"], False, "ambiguous_anchor"),
    ],
)
async def test_native_probe_matches_bounded_journal_anchor(
    tmp_path, monkeypatch, runs, pending, expected
):
    state = tmp_path / STATE_ROOT
    state.mkdir(parents=True)
    (state / bridge_spawn.DISCOVERY_FILE).write_text("fixture")
    calls = []
    monkeypatch.setattr(
        bridge_spawn,
        "_load_endpoint",
        lambda *a, **kw: SimpleNamespace(url="http://127.0.0.1:1", auth_token="fixture"),
    )

    class Client:
        async def get_agent(self, agent, **kwargs):
            return SimpleNamespace(agent_id=agent, runtime="local", cwd=str(tmp_path))

        async def list_runs(self, agent, **kwargs):
            assert kwargs["limit"] == 65
            return SimpleNamespace(items=[SimpleNamespace(id=run) for run in runs])

        async def get_run(self, run):
            return SimpleNamespace(id=run, agent_id="agent", status="running")

        async def aclose(self):
            calls.append("closed")

    monkeypatch.setattr(bridge_spawn.AsyncClient, "connect", lambda *a, **kw: Client())
    assert (
        await bridge_spawn.inspect_active_bridge(
            workspace=tmp_path, agent_id="agent", anchor="run-1", ambiguous_send=pending
        )
        == expected
    )
    assert calls == ["closed"]
    assert (state / bridge_spawn.DISCOVERY_FILE).exists()


async def test_missing_discovery_is_retained_without_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bridge_spawn.AsyncClient, "connect", lambda *a, **kw: pytest.fail("no discovery")
    )
    assert (
        await bridge_spawn.inspect_active_bridge(
            workspace=tmp_path, agent_id="agent", anchor="run-1", ambiguous_send=False
        )
        == "unavailable"
    )
