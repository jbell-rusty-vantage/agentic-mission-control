"""`cursor_local` (replaying bridge) and `cursor_cloud` (fake Cloud Agents API) for the suite.

FIXTURES: `tests/fixtures/cursor_local.py` and `tests/fixtures/cursor_cloud.py` run the real
`CursorLocalHarness` / `CursorCloudHarness` over recorded-shape provider fakes inside a real
Run (`tests/fixtures/cursor_controls.py`). No Cursor agent is created.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mission_control.adapters.cursor.controls import (
    CursorCloudSessionHydrator,
    CursorCloudWorkspaceSnapshots,
    CursorSessionHydrator,
    CursorWorkspaceSnapshots,
)
from mission_control.adapters.cursor.workspace import git
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.domain.execution.contracts import OperationAttemptIdentity
from mission_control.domain.execution.lanes import SnapshotManifest
from tests.conformance.lanes.contract import (
    ContinuationPorts,
    ForkedSession,
    LaneAdapter,
    LaneFake,
    Script,
)
from tests.fixtures.cursor_cloud import cloud_stack, load_sse
from tests.fixtures.cursor_controls import (
    cloud_control_stack,
    control_stack,
    fork_packet,
    fork_stack_from,
    register_run,
    started_session,
)
from tests.fixtures.cursor_local import local_stack

# Bridge offsets / SSE event ids at which the fixture run holds with a tool call running.
_LOCAL_TOOL_RUNNING = 6
_CLOUD_TOOL_RUNNING = "5"


class CursorLocalFake(LaneFake):
    def sends(self) -> list[tuple[str, str]]:
        launcher = self.control.local.launcher
        pairs = zip(launcher.sent_to, launcher.sends, strict=True)
        return [(agent, text) for agent, (_key, text) in pairs]

    async def until_held(self) -> None:
        await self.control.local.launcher.held.wait()

    def release(self) -> None:
        self.control.local.launcher.release.set()

    def cancels(self) -> int:
        return len(self.control.local.launcher.cancelled_runs)

    def ended(self) -> bool:
        leases = self.control.local.leases._leases.values()
        return bool(leases) and all(lease.released for lease in leases)


class CursorCloudFake(LaneFake):
    def sends(self) -> list[tuple[str, str]]:
        api = self.control.local.api
        return [
            (api.runs[run]["agentId"], api.run_prompts.get(run, "")) for run in api.created_runs
        ]

    async def until_held(self) -> None:
        await self.control.local.api.held.wait()

    def release(self) -> None:
        self.control.local.api.release.set()

    def cancels(self) -> int:
        return len(self.control.local.api.cancelled)

    def ended(self) -> bool:
        return bool(self.control.local.api.archived)


def _without_usage(value: Any) -> Any:
    """A bridge record with every reported usage removed (the `usage` answer stays
    `feature_unavailable`, as the recorded fixture has it)."""

    if isinstance(value, dict):
        return {key: _without_usage(item) for key, item in value.items() if key != "usage"}
    if isinstance(value, list):
        return [_without_usage(item) for item in value]
    return value


class CursorLocalConformance(LaneAdapter):
    profile = "cursor_local"

    def harness(self, tmp_path: Path) -> AgentHarness:
        return local_stack(tmp_path).harness

    async def open(
        self,
        tmp_path: Path,
        script: Script,
        *,
        operation_changes: Mapping[str, Any] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> LaneFake:
        del broker  # cursor-sdk 1.0.37 exposes no provider permission to bind
        held = script in {Script.HELD_TURN, Script.INTERRUPTIBLE_TURN, Script.CONTINUATION}
        replacement = script in {Script.INTERRUPTIBLE_TURN, Script.CONTINUATION}
        control = await control_stack(
            tmp_path,
            "inject_run" if replacement else "full_run",
            launcher_changes={"hold_at": _LOCAL_TOOL_RUNNING} if held else None,
            operation_changes=operation_changes,
        )
        if script is Script.NO_USAGE:
            launcher = control.local.launcher
            launcher.records = [
                record if record["kind"] == "usage" else _without_usage(record)
                for record in launcher.records
            ]
        return CursorLocalFake(control)

    def continuation_ports(self, fake: LaneFake) -> ContinuationPorts:
        harness = fake.control.local.harness
        return ContinuationPorts(
            snapshots=CursorWorkspaceSnapshots(harness, fake.control.local.artifacts),
            hydrator=CursorSessionHydrator(harness),
        )

    async def write_workspace(self, fake: LaneFake, path: str, content: bytes) -> None:
        root = Path(fake.control.local.harness.lease_path(str(fake.identity.harness_execution_id)))
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def fork(
        self, fake: LaneFake, snapshot: SnapshotManifest, tmp_path: Path, path: str
    ) -> ForkedSession:
        derived, _manifest = fork_stack_from(
            tmp_path, fake.control.local, snapshot.refs[0], agent_base="agent-forked-0001"
        )
        register_run(derived)
        heid, session = await started_session(derived)
        assert session.native_session_ref is not None
        restored = Path(derived.harness.lease_path(heid)) / path
        return ForkedSession(
            native_session_ref=session.native_session_ref,
            restored=restored.read_bytes().replace(b"\r\n", b"\n") if restored.is_file() else None,
        )


class CursorCloudConformance(LaneAdapter):
    profile = "cursor_cloud"

    def harness(self, tmp_path: Path) -> AgentHarness:
        return cloud_stack(tmp_path).harness

    async def open(
        self,
        tmp_path: Path,
        script: Script,
        *,
        operation_changes: Mapping[str, Any] | None = None,
        broker: ApprovalBroker | None = None,
    ) -> LaneFake:
        del broker  # the Cloud Agents API run stream carries no permission request
        api: dict[str, Any] = {}
        if script in {Script.HELD_TURN, Script.INTERRUPTIBLE_TURN, Script.CONTINUATION}:
            api["hold_after"] = _CLOUD_TOOL_RUNNING
        if script is Script.INTERRUPTIBLE_TURN:
            api["after_cancel"] = load_sse("interrupted_after_cancel")
        if script in {Script.INTERRUPTIBLE_TURN, Script.CONTINUATION}:
            api["later"] = [load_sse("replacement_stream")]
        if script is Script.NO_USAGE:
            api["usage_shape"] = "empty"
        control = await cloud_control_stack(
            tmp_path, api_changes=api, operation_changes=operation_changes
        )
        return CursorCloudFake(control)

    def continuation_ports(self, fake: LaneFake) -> ContinuationPorts:
        harness = fake.control.local.harness
        artifacts = fake.control.local.artifacts
        return ContinuationPorts(
            snapshots=CursorCloudWorkspaceSnapshots(harness, artifacts),
            hydrator=CursorCloudSessionHydrator(harness, artifacts),
        )

    async def write_workspace(self, fake: LaneFake, path: str, content: bytes) -> None:
        """The cloud agent's work: a commit pushed to the run branch on the remote."""

        stack = fake.control.local
        _repository, branch = stack.harness.session_branch(str(fake.identity.harness_execution_id))
        with tempfile.TemporaryDirectory(prefix="agent-push-") as scratch:
            work = Path(scratch) / "clone"
            git(
                "clone",
                "--quiet",
                "--branch",
                branch,
                str(stack.remote),
                str(work),
                cwd=work.parent,
            )
            target = work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            git("add", "--all", cwd=work)
            git(
                "-c",
                "user.name=Agent",
                "-c",
                "user.email=agent@localhost",
                "commit",
                "--quiet",
                "-m",
                "mid-run work",
                cwd=work,
            )
            git("push", "--quiet", "origin", branch, cwd=work)

    async def fork(
        self, fake: LaneFake, snapshot: SnapshotManifest, tmp_path: Path, path: str
    ) -> ForkedSession:
        """A derived run's agent starts on a branch created at the snapshot head."""

        source = fake.control.local
        workspace, inputs, _manifest = fork_packet(source.operation, snapshot.refs[0])
        derived = cloud_stack(
            tmp_path,
            remote=source.remote,
            operation_changes={
                "workspace": workspace,
                "identity": OperationAttemptIdentity(
                    run_id="run-forked", operation_id="op-forked", operation_attempt=1
                ),
            },
            inputs=inputs,
        )
        heid, session = await started_session(derived)
        assert session.native_session_ref is not None
        _repository, branch = derived.harness.session_branch(heid)
        listing = git("ls-tree", "-r", "--name-only", branch, cwd=source.remote).splitlines()
        restored = (
            git("show", f"{branch}:{path}", cwd=source.remote).encode("utf-8")
            if path in listing
            else None
        )
        return ForkedSession(native_session_ref=session.native_session_ref, restored=restored)


__all__ = ["CursorCloudConformance", "CursorLocalConformance"]
