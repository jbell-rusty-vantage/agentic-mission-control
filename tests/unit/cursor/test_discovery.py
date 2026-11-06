"""MO-34: the Cursor Discovery Proofs.

- `cursor_local`: the SDK's read-back of the agent (`get_agent`) proves the project setting
  source is the leased workspace; only then does the report list its skills and digest the
  overlay and hook config there. Through `lane.turn` (replaying bridge, real git worktree) the
  lane reads back once the agent exists, the report is a persisted frame and the environment is
  `discovered`.
- `cursor_cloud`: the prepare records what the mission branch commits; the Telemetry Hook Pack's
  first signal (`materialization.observed`, MO-41's data, simulated here by reading a clone of
  the published branch the way the pack reads the VM's disk) lifts the environment from
  `delivered` to `prepared` and `discovered`; an overlay changed in the VM fails the proof.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from mission_control.adapters.cursor.bridge import AgentReadback
from mission_control.adapters.cursor.discovery import setting_readback_report
from mission_control.adapters.cursor.workspace import git
from mission_control.application.environments import (
    EnvironmentPreparationService,
    InMemoryEnvironmentPreparationRepository,
)
from mission_control.application.environments.discovery import (
    DISCOVERY_RAW_KIND,
    materialization_signal_report,
    observed_files,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.signals.contracts import Signal
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import DiscoveryItem, discovery_gaps
from mission_control.domain.execution.environment_preparation import (
    ReadinessLevel,
    preparation_id,
)
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding, PrepareRequest
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.cursor_cloud import cloud_rows, cloud_stack
from tests.fixtures.cursor_controls import harness_fields
from tests.fixtures.cursor_local import local_stack
from tests.fixtures.lane_turns import RecordingSignals, lane_stack
from tests.fixtures.projections.rows import skill_row

OVERLAY = ".cursor/rules/mc-mission.mdc"
HOOKS = ".cursor/hooks.json"


def _workspace(root: Path) -> Path:
    (root / ".cursor/skills/agent-browser").mkdir(parents=True)
    (root / ".cursor/skills/agent-browser/SKILL.md").write_text("---\nname: agent-browser\n---\n")
    (root / ".cursor/skills/notes").mkdir()  # no SKILL.md: not a skill
    (root / ".cursor/rules").mkdir()
    (root / OVERLAY).write_bytes(b"overlay")
    return root


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


# --- cursor_local -------------------------------------------------------------------------------


def test_the_read_back_of_an_agent_rooted_in_the_workspace_reports_its_project_files(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path / "lease")
    report = setting_readback_report(AgentReadback("agent-1", "local", str(root)), root)
    assert report.mechanism == "setting_readback" and report.source == "sdk:get_agent:agent-1"
    assert report.items == (DiscoveryItem(kind="skill", name="agent-browser"),)
    assert report.digests == {OVERLAY: _digest(b"overlay"), HOOKS: None}
    assert observed_files(LaneProfile.CURSOR_LOCAL) == (OVERLAY, HOOKS)


def test_an_agent_rooted_elsewhere_or_not_local_reports_nothing(tmp_path: Path) -> None:
    root = _workspace(tmp_path / "lease")
    for readback in (
        AgentReadback("agent-1", "local", str(tmp_path / "elsewhere")),
        AgentReadback("agent-1", "cloud", str(root)),
        AgentReadback("agent-1", None, ""),
    ):
        report = setting_readback_report(readback, root)
        assert report.items == () and report.digests == {}


async def test_a_cursor_local_turn_reads_the_agent_back_and_is_discovered(
    tmp_path: Path,
) -> None:
    stack = local_stack(tmp_path)
    repository = InMemoryEnvironmentPreparationRepository()
    lanes = lane_stack(
        stack.harness,
        frames=stack.frames,
        operation=stack.operation,
        preparations=EnvironmentPreparationService(repository),
    )
    identity = LaneExecutionIdentity.of(stack.operation, "cursor_local", 1)
    request = LaneTurnRequest.model_validate(
        {"operation": stack.operation, "lane_profile": "cursor_local", "generation": 1}
    )
    result = await lanes.service.turn(
        request, RecordingSignals(stack.frames, identity.harness_execution_id)
    )
    assert result.done
    stored = await repository.get(
        identity.request_scope,
        preparation_id(identity.request_scope, identity.harness_execution_id, 1),
    )
    assert stored is not None and stored.discovery is not None
    assert stored.discovery.mechanism == "setting_readback"
    assert set(stored.discovery.digests) == {OVERLAY, HOOKS}
    discovered = stored.mark(ReadinessLevel.DISCOVERED)
    assert discovered is not None and discovered.evidence_ref.startswith("frame:discovery:")
    assert stored.readiness is ReadinessLevel.DISCOVERED
    frames = stack.frames._executions[identity.harness_execution_id].frames.values()
    (frame,) = [item for item in frames if item.raw_kind == DISCOVERY_RAW_KIND]
    assert frame.kind is FrameKind.STATUS


# --- cursor_cloud -------------------------------------------------------------------------------


def _observed_in_vm(checkout: Path, skills_root: str = ".cursor/skills") -> dict[str, Any]:
    """MO-41's `materialization.observed` data: the policy's files as read from disk and the
    skill directory listing."""

    def digest(path: Path) -> str | None:
        return _digest(path.read_bytes()) if path.is_file() else None

    skills = checkout / skills_root
    return {
        "files": {path: digest(checkout / path) for path in (OVERLAY, HOOKS)},
        "skills": sorted(entry.name for entry in skills.iterdir() if (entry / "SKILL.md").is_file())
        if skills.is_dir()
        else [],
    }


async def _prepared_cloud(tmp_path: Path) -> tuple[Any, Any, LaneExecutionIdentity, Path]:
    stack = cloud_stack(tmp_path, rows=(skill_row(), *cloud_rows()))
    operation = stack.operation
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    heid = str(identity.harness_execution_id)
    fields = harness_fields(operation, heid, "cursor_cloud")
    stack.harness.stage(heid, operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **fields,
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    assert prepared.workspace_ref is not None
    branch = prepared.workspace_ref.removeprefix("branch:").split("@", 1)[0]
    checkout = tmp_path / "vm"
    # The VM checks the branch out byte for byte (no host line-ending conversion).
    git(
        "-c",
        "core.autocrlf=false",
        "clone",
        "--quiet",
        "--branch",
        branch,
        str(stack.remote),
        str(checkout),
        cwd=tmp_path,
    )
    return stack, prepared, identity, checkout


def _signal(data: dict[str, Any]) -> Signal:
    return Signal(signal_id="spool-2", type="materialization.observed", seq=2, data=data)


async def test_cursor_cloud_is_prepared_and_discovered_by_the_first_in_vm_signal(
    tmp_path: Path,
) -> None:
    stack, prepared, identity, checkout = await _prepared_cloud(tmp_path)
    expectation = prepared.discovery
    assert expectation is not None and expectation.mechanism == "materialization_signal"
    assert DiscoveryItem(kind="skill", name="agent-browser") in expectation.items
    assert set(expectation.digests) == {OVERLAY, HOOKS}
    service = EnvironmentPreparationService(InMemoryEnvironmentPreparationRepository())
    binding = CursorExecutionBinding.carried_by(stack.operation)
    record = await service.admit_start(identity, binding, prepared)
    assert record.readiness is ReadinessLevel.DELIVERED

    report = materialization_signal_report("cursor_cloud", _signal(_observed_in_vm(checkout)))
    assert report is not None and discovery_gaps(expectation, report) == ()
    outcome = await service.discovered(identity, report, evidence_ref="signal:spool-2")

    assert outcome.gaps == () and outcome.preparation is not None
    assert outcome.preparation.readiness is ReadinessLevel.DISCOVERED
    assert outcome.preparation.receipt_digest == report.digest


async def test_an_overlay_changed_in_the_vm_fails_the_proof(tmp_path: Path) -> None:
    stack, prepared, identity, checkout = await _prepared_cloud(tmp_path)
    (checkout / OVERLAY).write_bytes(b"not what the mission committed")
    service = EnvironmentPreparationService(InMemoryEnvironmentPreparationRepository())
    await service.admit_start(
        identity, CursorExecutionBinding.carried_by(stack.operation), prepared
    )

    report = materialization_signal_report("cursor_cloud", _signal(_observed_in_vm(checkout)))
    assert report is not None
    outcome = await service.discovered(identity, report, evidence_ref="signal:spool-2")

    assert outcome.preparation is not None
    assert outcome.preparation.readiness is ReadinessLevel.DELIVERED
    (gap,) = outcome.gaps
    assert gap.startswith(f"{OVERLAY} reads sha256:")
