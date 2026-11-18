"""Cursor cognition points (cross-provider control, 2026-11-05): the fold of a settled turn.

`cursor_local` over the replaying bridge and `cursor_cloud` over the fake Cloud Agents API
run one full turn through `lane.turn` with the in-memory lineage composed, so the settlement
writes the lane's points (`written_by: adapter`): one `session_cursor` point per step
boundary keyed by the bridge offset / SSE event id, roles, parents, running message count,
usage delta from the usage frames, the turn-close `workspace_snapshot` (the `cursor-snapshot:`
ref on local, `branch:<branch>@<sha>` on cloud) joined to the turn and named on the result
point. No Cursor agent is created.
"""

from __future__ import annotations

from pathlib import Path

from mission_control.adapters.cursor.cognition_points import (
    TURN_SNAPSHOT_FACT,
    cloud_step_ref,
    local_step_ref,
)
from mission_control.domain.execution.cognition_points import (
    SessionCursorPoint,
    WorkspaceSnapshotPoint,
)
from tests.support.lanes import (
    cursor_operation,
)
from tests.support.providers.cursor import cloud_stack, local_stack
from tests.support.unit.cursor.cognition_points import settled_points, unit_changes


async def test_a_local_turn_writes_one_point_per_step_keyed_by_bridge_offset(
    tmp_path: Path,
) -> None:
    stack = local_stack(tmp_path, operation_changes=unit_changes(cursor_operation()))
    rows, identity, lanes = await settled_points(stack, "cursor_local")

    steps = [row for row in rows if isinstance(row.coordinate.point, SessionCursorPoint)]
    snapshots = [row for row in rows if isinstance(row.coordinate.point, WorkspaceSnapshotPoint)]
    agent, run = stack.launcher.meta["agent_id"], stack.launcher.meta["run_id"]
    # full_run: tool completions at offsets 5 and 7, the assistant message at 8, the turn
    # end at 9 and the RunResult at 11 are the step boundaries (deltas, status, usage and
    # hook frames fold into the next boundary's frame range).
    assert [row.coordinate.locator for row in steps] == [
        f"{agent}#{run}#5",
        f"{agent}#{run}#7",
        f"{agent}#{run}#8",
        f"{agent}#{run}#9",
        f"{agent}#{run}#11",
    ]
    assert {row.written_by for row in rows} == {"adapter"}
    assert all(row.lane_profile == "cursor_local" for row in rows)
    assert steps[0].roles == ("intermediate",) and steps[-1].roles == ("leaf", "result")
    assert [row.parent_point_id for row in steps[1:]] == [row.point_id for row in steps[:-1]]
    assert steps[2].message_count == 1 and steps[-1].message_count == 1
    # The SDK `usage` message (offset 10) folds into the result point; the turn-ended counts
    # it repeats are not charged twice.
    assert (
        steps[-1].usage_delta["tokens.total"] == 2242 and "tokens.total" not in steps[3].usage_delta
    )
    assert steps[0].channel_facts["tool_name"] == "read"
    assert steps[1].channel_facts["tool_name"] == "shell"
    assert steps[2].channel_facts["message_role"] == "assistant"
    assert steps[-1].channel_facts["native_status"] == "finished"
    assert all(row.seedable for row in steps)
    assert all(
        row.coordinate.harness_execution_id == str(identity.harness_execution_id) for row in rows
    )
    # The turn-close snapshot joins the turn: every step names it, the result point carries
    # it as its workspace ref, and one workspace_snapshot point closes the turn.
    (lease,) = stack.leases._leases.values()
    assert lease.snapshot_ref is not None and lease.snapshot_ref.startswith("cursor-snapshot:")
    assert {row.channel_facts[TURN_SNAPSHOT_FACT] for row in steps} == {lease.snapshot_ref}
    assert steps[-1].workspace_checkpoint_ref == lease.snapshot_ref
    (snapshot,) = snapshots
    point = snapshot.coordinate.point
    assert isinstance(point, WorkspaceSnapshotPoint)
    assert (point.snapshot_ref, point.session_ref, point.turn_ref) == (
        lease.snapshot_ref,
        agent,
        run,
    )
    assert snapshot.parent_point_id == steps[-1].point_id
    assert snapshot.channel_facts["snapshot_kind"] == "cursor_snapshot"
    # Step refs are the persisted bridge offsets (synthetic frames keep the default ref).
    frames = sorted(
        lanes.frames._executions[identity.harness_execution_id].frames.values(),
        key=lambda f: f.arrival_ordinal,
    )
    assert [local_step_ref(frame) for frame in frames if frame.provider_key.endswith(":5")] == ["5"]


async def test_a_cloud_turn_writes_points_keyed_by_sse_event_id_and_the_branch_head(
    tmp_path: Path,
) -> None:
    base = cloud_stack(tmp_path)
    stack = cloud_stack(
        tmp_path, remote=base.remote, operation_changes=unit_changes(base.operation)
    )
    rows, identity, lanes = await settled_points(stack, "cursor_cloud")

    steps = [row for row in rows if isinstance(row.coordinate.point, SessionCursorPoint)]
    snapshots = [row for row in rows if isinstance(row.coordinate.point, WorkspaceSnapshotPoint)]
    (create,) = stack.api.creates
    agent, run = create["agentId"], stack.api.run_id
    # run_stream: tool completions at events 4 and 6, the turn end at 7 and the result at 8.
    assert [row.coordinate.locator for row in steps] == [
        f"{agent}#{run}#4",
        f"{agent}#{run}#6",
        f"{agent}#{run}#7",
        f"{agent}#{run}#8",
    ]
    assert steps[-1].roles == ("leaf", "result") and steps[0].roles == ("intermediate",)
    assert steps[2].usage_delta["tokens.total"] == 2780
    assert steps[0].channel_facts["tool_name"] == "read"
    # The cloud snapshot is the run branch at its recorded head.
    (snapshot,) = snapshots
    point = snapshot.coordinate.point
    assert isinstance(point, WorkspaceSnapshotPoint)
    assert point.snapshot_ref.startswith("branch:mc/") and "@" in point.snapshot_ref
    assert (point.session_ref, point.turn_ref) == (agent, run)
    assert snapshot.channel_facts["snapshot_kind"] == "branch"
    assert snapshot.channel_facts["repository"] == str(stack.remote)
    assert steps[-1].workspace_checkpoint_ref == point.snapshot_ref
    assert (
        steps[-1].channel_facts["branch"]
        == point.snapshot_ref.removeprefix("branch:").split("@")[0]
    )
    frames = lanes.frames._executions[identity.harness_execution_id].frames.values()
    assert {cloud_step_ref(frame) for frame in frames if frame.provider_key.startswith("sse:")} >= {
        "4",
        "6",
        "7",
        "8",
    }
