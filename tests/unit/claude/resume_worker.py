"""One worker process of the MO-73 cross-process resume proof (run as `python -m`).

`start` leases the workspace, starts a session, runs the first turn through the lane's harness
and dies without ending the session. `resume` is a *fresh* Python process: it rebuilds the lane
from what earlier processes persisted (the operation, the lease ledger, the session id),
reattaches by session id and runs the next turn, then dies the same way. With
`--without-cli-copy` it first deletes the CLI's own transcripts, as on a worker of another
host that has only the leased state root. Every phase drives the real pinned
`ClaudeSDKClient` over the lane's `ExplicitEnvironmentCliTransport` and
`StateRootSessionStore`; the Claude Code process is the FIXTURE `fake_cli.py`. Nothing calls a
model.

Usage: `python -m tests.unit.claude.resume_worker {start|resume} DIR [--without-cli-copy]`;
each phase records its outcome in `DIR/progress.json`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio

from mission_control.adapters.claude.harness import (
    ClaudeAgentSdkHarness,
    ClaudeLaneSettings,
    StaticAuthAdmitter,
)
from mission_control.adapters.claude.host import host_gate
from mission_control.adapters.claude.transport import SdkClientFactory
from mission_control.adapters.claude.workspace import config_dir, state_root
from mission_control.application.agentic_components.placement import (
    RenderedProjectionSource,
    static_rows,
)
from mission_control.application.execution.child_environment import provider_child_environment
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import (
    ObserveRequest,
    PrepareRequest,
    ReattachRequest,
    SendTurnRequest,
    SessionHandle,
    StartRequest,
)
from tests.unit.claude.fixtures import (
    PROFILE,
    FixtureWorkspace,
    claude_operation,
    fixture_admission,
    projection_rows,
)

FAKE_CLI = Path(__file__).with_name("fake_cli.py")
PROMPTS = (
    "FIRST: remember the codeword ORCHID.",
    "SECOND: which codeword did the first turn give?",
    "THIRD: repeat the codeword once more.",
)


async def spawn_fake_cli(cmd: list[str], **kwargs: Any) -> Any:
    # The SDK's own command line, run by the FIXTURE CLI instead of Claude Code.
    return await anyio.open_process([sys.executable, str(FAKE_CLI), *cmd[1:]], **kwargs)


def fake_cli_factory() -> SdkClientFactory:
    """The production client factory over the FIXTURE CLI, past the host gate (the lane runs
    on Linux, WSL 2 or macOS; this proof runs wherever the unit suite runs)."""

    gate = host_gate(system="Linux", release="6.8.0-fixture", event_loop="none")
    return SdkClientFactory(spawn=spawn_fake_cli, check_version=False, gate=lambda: gate)


def worker_environ(workdir: Path) -> dict[str, str]:
    """The worker environment: what a Python child needs to start, and a FIXTURE key for the
    admitted `api_key` route, which relocates `CLAUDE_CONFIG_DIR` under the lease."""

    keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP")
    environ = {name: os.environ[name] for name in keep if name in os.environ}
    return {**environ, "HOME": str(workdir / "home"), "ANTHROPIC_API_KEY": "sk-ant-FIXTURE-0000"}


class Worker:
    """The lane's harness as one worker process builds it, over the persisted lease ledger."""

    def __init__(self, workdir: Path, operation: OperationExecutionRequest) -> None:
        self.operation = operation
        self.identity = LaneExecutionIdentity.of(operation, PROFILE, 1)
        self.registry: dict[UUID, WorkspaceLease] = {}
        self._ledger = workdir / "leases.json"
        if self._ledger.is_file():
            for raw in json.loads(self._ledger.read_text(encoding="utf-8")):
                lease = WorkspaceLease.model_validate(raw)
                self.registry[lease.lease_id] = lease
        self.harness = ClaudeAgentSdkHarness(
            clients=fake_cli_factory(),
            workspaces=FixtureWorkspace(workdir / "leases", self.registry),
            projections=RenderedProjectionSource(
                static_rows(projection_rows()), projectors=HOST_PROJECTORS
            ),
            auth=StaticAuthAdmitter(fixture_admission(route="api_key", env_unset=())),
            child_environment=provider_child_environment,
            environ=worker_environ(workdir),
            settings=ClaudeLaneSettings(require_executables=False, init_timeout_s=30.0),
        )
        self.harness.stage(self.heid, operation)

    @property
    def heid(self) -> str:
        return str(self.identity.harness_execution_id)

    @property
    def lease_path(self) -> Path:
        (lease,) = self.registry.values()
        return Path(lease.path)

    def persist_leases(self) -> None:
        leases = [lease.model_dump(mode="json") for lease in self.registry.values()]
        self._ledger.write_text(json.dumps(leases), encoding="utf-8")

    def fields(self, key: str) -> dict[str, Any]:
        assert ProviderExecutionBinding.carried_by(self.operation) is not None
        return {
            "scope": harness_scope(self.identity.request_scope),
            "lane_profile": PROFILE,
            "harness_execution_id": self.heid,
            "binding_digest": ProviderExecutionBinding.carried_by(self.operation).binding_digest,
            "idempotency_key": f"{self.heid}:1:{key}",
            "generation": 1,
        }

    async def turn(self, session: SessionHandle, turn_no: int) -> str:
        """Send one turn and read its frames to the terminal `result`: its result text."""

        instruction = f"op:turn:{turn_no}"
        self.harness.stage_turn(self.heid, instruction, PROMPTS[turn_no - 1])
        handle = await self.harness.send_turn(
            SendTurnRequest(
                **self.fields(f"turn:{turn_no}"),
                session=session,
                turn_no=turn_no,
                instruction_ref=instruction,
            )
        )
        request = ObserveRequest(**self.fields(f"observe:{turn_no}"), turn=handle)
        frames = [frame async for frame in self.harness.observe(request)]
        assert frames[-1].terminal and frames[-1].raw_kind == "result", frames[-1]
        return str(frames[-1].body["result"])


async def start(workdir: Path) -> dict[str, Any]:
    operation = claude_operation()
    (workdir / "operation.json").write_text(operation.model_dump_json(), encoding="utf-8")
    worker = Worker(workdir, operation)
    prepared = await worker.harness.prepare(
        PrepareRequest(
            **worker.fields("prepare"),
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    worker.persist_leases()
    session = await worker.harness.start(StartRequest(**worker.fields("start"), prepared=prepared))
    reply = await worker.turn(session, 1)
    return {
        "session_id": session.native_session_ref,
        "lease_path": str(worker.lease_path),
        "replies": [reply],
    }


async def resume(workdir: Path, progress: dict[str, Any], *, without_cli_copy: bool) -> None:
    operation = OperationExecutionRequest.model_validate_json(
        (workdir / "operation.json").read_text(encoding="utf-8")
    )
    worker = Worker(workdir, operation)
    cli_projects = config_dir(state_root(worker.lease_path)) / "projects"
    if without_cli_copy:
        shutil.rmtree(cli_projects)
    turn_no = len(progress["replies"]) + 1
    session = await worker.harness.reattach(
        ReattachRequest(
            **worker.fields(f"reattach:{turn_no}"), native_session_ref=progress["session_id"]
        )
    )
    progress["resumed_session_id"] = session.native_session_ref
    progress["cli_files_at_resume"] = sorted(
        path.relative_to(cli_projects).as_posix()
        for path in cli_projects.rglob("*")
        if path.is_file()
    )
    progress["replies"].append(await worker.turn(session, turn_no))


async def _main(argv: list[str]) -> None:
    phase, workdir = argv[0], Path(argv[1])
    record = workdir / "progress.json"
    if phase == "start":
        progress = await start(workdir)
    else:
        progress = json.loads(record.read_text(encoding="utf-8"))
        await resume(workdir, progress, without_cli_copy="--without-cli-copy" in argv)
    record.write_text(json.dumps(progress), encoding="utf-8")
    # The worker dies here, inside its running loop: the session is never ended and nothing
    # is torn down, so the next process has only what was persisted.
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
