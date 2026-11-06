"""FT-G6: the Cursor-only describe cells, exercised against fixtures.

The cells every lane shares (the declared matrix and its frozen tables, implemented and refused
operations, start/observe/settle, reattach, `wait_then_send`, cancel, `cancel_and_replace`,
fork, `request_continuation`, unknown usage, pause, hooks, the qualification gate) run for both
Cursor profiles in the lane conformance suite (`tests/conformance/lanes`, SPEC-06 section 3).
What stays here is Cursor's own: the SPEC-07 section 7 values of its matrix, cost settled only
from the cost reader, the snapshot kind of each placement, where its fail-closed Kernel Hooks
run, its per-run cursors, its instruction channel, subagent files and placement, and the live
drill record its qualification writes. `qualified` stays false: only a recorded live drill
(docs/qualification/lanes) may flip it.

No network, no credentials, no paid call.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.cursor.workspace import git
from mission_control.application.execution.harness.describe import DECLARED_LANE_MATRICES
from mission_control.domain.execution.contracts import OperationExecutionResult
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import SessionHandle, SnapshotRequest
from tests.conformance.lanes.records import live_drills
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import (
    ControlStack,
    cloud_control_stack,
    control_stack,
    harness_fields,
    register_run,
    source_agent,
    started_session,
)
from tests.fixtures.cursor_local import local_stack
from tests.fixtures.lane_turns import RecordingSignals, lane_stack

PROFILES = ("cursor_local", "cursor_cloud")
# Bridge offsets / SSE event ids at which the fixture run holds after its turn ended.
TURN_ENDED = {"cursor_local": 10, "cursor_cloud": "7"}


@pytest.mark.parametrize("profile", PROFILES)
def test_the_declared_matrix_is_section_7_and_never_qualified_by_fixtures(profile: str) -> None:
    describe = DECLARED_LANE_MATRICES[profile]  # type: ignore[index]
    assert describe.delivery_semantics == {
        "queue_instruction": "wait_then_send",
        "interrupt_and_inject": "cancel_and_replace",
        "pause": "unsupported",
        "hard_pause": "unsupported",
        "resume": "wait_then_send",
        "cancel": "turn_boundary_guaranteed",
        "fork": "emulated",
        "request_continuation": "emulated",
    }
    assert describe.controls["pause"] == "unsupported"
    assert describe.controls["snapshot"] == "emulated" and describe.controls["fork"] == "emulated"
    assert describe.controls["reattach"] == ("emulated" if profile == "cursor_local" else "native")
    assert describe.qualified is False


def _single_turn(operation: Any, profile: str) -> LaneTurnRequest:
    return LaneTurnRequest.model_validate(
        {"operation": operation, "lane_profile": profile, "generation": 1}
    )


@pytest.mark.parametrize("profile", PROFILES)
async def test_cost_settles_only_when_the_provider_reports_it(tmp_path: Path, profile: str) -> None:
    if profile == "cursor_local":
        stack: Any = local_stack(tmp_path, "error_run")  # get_usage reports cost 2100 micros
        lanes = lane_stack(stack.harness, frames=stack.frames, operation=stack.operation)
    else:
        stack = cloud_stack(tmp_path, cost=4_200)
        lanes = lane_stack(stack.harness, operation=stack.operation)
    result = await lanes.service.turn(
        _single_turn(stack.operation, profile), RecordingSignals(lanes.frames)
    )
    assert result.closing_facts is not None
    # Local fixture billing is agent-scoped, not attributable to its synthetic run label.
    expected = "unknown" if profile == "cursor_local" else "settled"
    assert result.closing_facts.cost_disposition == expected
    if profile == "cursor_local":
        assert result.closing_facts.usage.cost_micros_usd is None


async def _held_stack(tmp_path: Path, profile: str) -> tuple[ControlStack, asyncio.Task[Any]]:
    """A Run whose first turn holds right after its turn ended."""

    if profile == "cursor_local":
        stack = await control_stack(
            tmp_path, launcher_changes={"hold_at": TURN_ENDED["cursor_local"]}
        )
        held = stack.local.launcher.held
    else:
        stack = await cloud_control_stack(
            tmp_path, api_changes={"hold_after": TURN_ENDED["cursor_cloud"]}
        )
        held = stack.local.api.held
    signals = RecordingSignals(stack.lanes.frames, stack.identity.harness_execution_id)
    task = asyncio.create_task(stack.service.turn(stack.turn(), signals))
    await asyncio.wait_for(held.wait(), timeout=20)
    return stack, task


@pytest.mark.parametrize("profile", PROFILES)
async def test_the_snapshot_kind_follows_the_placement(tmp_path: Path, profile: str) -> None:
    stack, task = await _held_stack(tmp_path, profile)
    heid = str(stack.identity.harness_execution_id)
    manifest = await stack.local.harness.snapshot(
        SnapshotRequest(
            **harness_fields(stack.operation, heid),
            session=SessionHandle(
                lane_profile=stack.profile,
                harness_execution_id=heid,
                generation=1,
                native_session_ref=source_agent(stack),
            ),
            reason="snapshot",
        )
    )
    if profile == "cursor_local":
        stack.local.launcher.release.set()
        assert manifest.kind == "git_patch" and manifest.refs[0].startswith("cursor-snapshot:")
    else:
        stack.local.api.release.set()
        assert manifest.kind == "branch" and manifest.refs[0].startswith("branch:")
    result = await asyncio.wait_for(task, timeout=30)
    assert OperationExecutionResult.model_validate(result.operation_result).status == "completed"


# --- hooks, identity, instruction channel, subagents, placement ----------------------------------


@pytest.mark.parametrize("profile", PROFILES)
async def test_hooks_fail_closed_only_where_kernel_hooks_run(tmp_path: Path, profile: str) -> None:
    describe = DECLARED_LANE_MATRICES[profile]  # type: ignore[index]
    stack: Any = local_stack(tmp_path) if profile == "cursor_local" else cloud_stack(tmp_path)
    projection = await stack.harness._projections.project(
        stack.operation, profile=profile, packet_index=None
    )
    hooks = json.loads(projection.file(".cursor/hooks.json").content)["hooks"]
    kernel = [
        entry
        for entries in hooks.values()
        for entry in entries
        if "kernel.py" in str(entry.get("command", ""))
    ]
    fail_closed = any(entry.get("failClosed") for entry in kernel)
    assert fail_closed is describe.hooks.fail_closed
    if profile == "cursor_cloud":
        assert kernel == [], "the cloud VM cannot reach the loopback callback"


@pytest.mark.parametrize("profile", PROFILES)
async def test_identity_and_cursor_are_per_run_and_resumable(tmp_path: Path, profile: str) -> None:
    stack = await (
        control_stack(tmp_path) if profile == "cursor_local" else cloud_control_stack(tmp_path)
    )
    result = await stack.service.turn(stack.turn(), RecordingSignals(stack.lanes.frames))
    run = result.native.turn_ref
    assert run is not None
    execution = stack.lanes.frames._executions[stack.identity.harness_execution_id]
    keyed = [frame for frame in execution.frames.values() if frame.native_turn_ref == run]
    cursors = {stack.local.harness.resume_cursor(frame.provider_key) for frame in keyed}
    cursors.discard(None)
    assert cursors and all(cursor.startswith(f"{run}@") for cursor in cursors)
    describe = stack.local.harness.describe()
    expected = "bridge_offset" if profile == "cursor_local" else "sse_event_id"
    assert describe.identity.cursor == expected
    assert describe.identity.session_ref == "agent_id" and describe.identity.turn_ref == "run_id"


@pytest.mark.parametrize("profile", PROFILES)
async def test_instruction_channel_subagents_and_placement(tmp_path: Path, profile: str) -> None:
    describe = DECLARED_LANE_MATRICES[profile]  # type: ignore[index]
    if profile == "cursor_local":
        stack = local_stack(tmp_path)
        register_run(stack)
        heid, _session = await started_session(stack)
        root = Path(stack.harness.lease_path(heid))
        present = {
            path
            for path in ("AGENTS.md", ".cursor/rules/mc-mission.mdc")
            if (root / path).is_file()
        }
        assert any((root / ".cursor/agents").glob("*.md"))
        repository_guide = (root / "AGENTS.md").read_bytes()
        assert str(root).startswith(str(stack.lease_root)), "worker_hosted lease"
        assert "prompt_prefix" in describe.instruction_channel
        assert stack.launcher.created[0].setting_sources == ("project",)
    else:
        cloud = cloud_stack(tmp_path)
        heid, _session = await started_session(cloud)
        _repository, branch = cloud.harness.session_branch(heid)
        listing = git("ls-tree", "-r", "--name-only", branch, cwd=cloud.remote).splitlines()
        present = {
            path for path in ("AGENTS.md", ".cursor/rules/mc-mission.mdc") if path in listing
        }
        assert any(path.startswith(".cursor/agents/") for path in listing)
        repository_guide = git("show", f"{branch}:AGENTS.md", cwd=cloud.remote).encode()
        assert "prompt_prefix" not in describe.instruction_channel
    assert (
        present
        == {"AGENTS.md", ".cursor/rules/mc-mission.mdc"}
        <= set(describe.instruction_channel)
    )
    # MO-02: the rule carries the mission; AGENTS.md is the repository's own, never rewritten.
    assert repository_guide == b"Repository guide (owned by the repository).\n"
    assert describe.subagents.file == ".cursor/agents/*.md"
    assert describe.subagents.readonly_supported_inline is False
    assert describe.placement == ("worker_hosted" if profile == "cursor_local" else "cloud")


# --- the live drill record the qualification gate reads ------------------------------------------


def test_the_live_drill_record_is_what_the_gate_reads(tmp_path: Path) -> None:
    from tests.integration.cursor.live_drill import UNVERIFIED, DrillOutcome, Spend, write_record

    passed = DrillOutcome("cursor_local", Spend(budget_usd=2.0))
    passed.checks["full_turn_settles_from_closing_facts"] = True
    passed.settle("run_request_id", "refuted", "cursor-sdk 1.0.37 source")
    write_record(passed, root=tmp_path)
    assert len(live_drills("cursor_local", tmp_path)) == 1
    text = next(tmp_path.glob("cursor_local-*.md")).read_text("utf-8")
    assert all(f"| {item} |" in text for item in UNVERIFIED)
    ambiguous = DrillOutcome("cursor_cloud", Spend(budget_usd=2.0, unknown=["agent?"]))
    ambiguous.checks["full_turn_settles_from_closing_facts"] = True
    write_record(ambiguous, root=tmp_path)
    assert live_drills("cursor_cloud", tmp_path) == [], "an ambiguous paid effect never qualifies"
    with pytest.raises(ValueError):
        passed.settle("not-an-item", "verified", "")


def test_the_live_drill_refuses_without_an_approved_finite_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("lane_qualify", root / "scripts/lane_qualify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("CURSOR_API_KEY", "MC_PAID_BUDGET_USD", "MC_CURSOR_CLOUD_REPO"):
        monkeypatch.delenv(name, raising=False)
    assert len(module._live_preconditions("cursor_cloud")) == 3
    monkeypatch.setenv("CURSOR_API_KEY", "not-a-real-key")
    monkeypatch.setenv("MC_PAID_BUDGET_USD", "inf")
    assert module._live_preconditions("cursor_local") == [
        "MC_PAID_BUDGET_USD (a finite, owner-approved amount)"
    ]
    monkeypatch.setenv("MC_PAID_BUDGET_USD", "1.5")
    assert module._live_preconditions("cursor_local") == []
    from tests.integration.cursor.live_drill import live_enabled

    monkeypatch.delenv("MC_LIVE_CURSOR_QUALIFICATION", raising=False)
    assert not live_enabled(), "never without the explicit opt-in flag"
