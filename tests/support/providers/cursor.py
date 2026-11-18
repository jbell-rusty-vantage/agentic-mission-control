"""The one Cursor fake per API: the local bridge (`ReplayBridge`), the Cloud Agents API
(`FakeCloudApi`) and the environments API (`FakeEnvironmentsApi`), with their lane stacks.

Formerly `tests/fixtures/cursor_local.py`:

FT-G3 fixtures: a replaying Cursor local bridge, git repositories and the lane stack.

`ReplayBridgeLauncher` stands in for the pinned `cursor-sdk` bridge. It replays a recorded
(or hand-authored, marked synthetic) JSONL fixture under `tests/integration/cursor/fixtures/
local/`: `event` records are `ObserveRun` envelopes with their durable offsets, `hook` records
are Cursor hook invocations it fires through the kernel hook path while the run progresses
(as Cursor does), `workspace_write` records are files the agent writes, `run_state` and
`usage` answer `GetRun` and `GetUsage`. No Cursor agent is created and nothing is paid for.

FT-G4: a fixture may hold several runs (records carry `"run"`; absent means the meta run):
the first send returns the meta `run_id`, later sends the meta `later_runs` in order (a
replacement or continuation turn), and every `Agent.create` after the first returns a new
agent id (a fork or a continuation). Events marked `after_cancel` are delivered only once the
held run was cancelled (a tool call that completes during the cancel), unless the launcher
drops them (a tool call that never closes).

Formerly `tests/fixtures/cursor_cloud.py`:

FT-G5 fixtures: a Cloud Agents API v1 fake behind `httpx.MockTransport`, a bare remote.

`FakeCloudApi` replays the recorded shapes in `tests/integration/cursor/fixtures/cloud/`
(hand-authored from research/cursor-platform.md section 4, marked synthetic): agent create
with client `agentId` and `Idempotency-Key`, `409 agent_id_conflict`, `409 agent_busy`,
`403 feature_unavailable` on `metadata`, run reads, the SSE stream honoring `Last-Event-ID`
(optionally dropping the connection mid-stream, or answering `410 stream_expired`), cancel,
artifacts through presigned URLs that must not carry the API key, usage and archive. When a run
reaches its result the fake pushes the agent's commit to `mc/<run>` on the bare remote, as the
cloud agent would. No network is touched.

FT-G6: a stream can be held open after an event id (`hold_after`; released by a cancel or by
the test), deliver `after_cancel` events when the held run was cancelled (a tool call that
completes during the cancel), and later runs (`POST .../runs`, a continuation agent's create)
replay their own event lists (`later`), so every SPEC-07 section 7 control replays offline.

MO-41: `vm` stands in for the cloud VM's hook engine. Before the agent's commit it runs a
scripted sequence of Cursor hook events through the checked-out branch's `.cursor/hooks.json`
(`run_cursor_hooks`), with the create request's `envVars` in the hook environment.

Formerly `tests/fixtures/cursor_environments.py`:

MO-13 FIXTURE: Cursor's `/v1/environments` and environment secrets behind `httpx.MockTransport`.

The shapes follow what the MO-13 drill observed on 2026-10-14 (research/cursor.md section 1.5):
`POST` answers `201` without the configuration, a taken name is `409
environment_name_conflict` with the existing `environmentId`, `GET` carries `versionId` but
not `environmentJson`, the configuration is the version-history entry with `current: true`,
`PATCH` answers `204` and adds an `updated` entry, secrets list `{id, name, type, repos}` and
an unknown secret deletes as `404 secret_not_found`. `dashboard_edit` changes a configuration
the way a person in the dashboard would. Values are kept only to assert what was written.
`kit_in_custody` publishes a kit whose base-layer bytes the lane reads back from custody.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import SecretStr

from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.adapters.cursor.bridge import (
    AgentBusy,
    AgentReadback,
    BridgeEvent,
    FeatureUnavailable,
    LocalAgentSpec,
    RunNotCancellable,
    RunNotFound,
    RunState,
    SandboxUnsupported,
    UsageState,
)
from mission_control.adapters.cursor.cloud import CloudEnvResolver, CursorCloudHarness
from mission_control.adapters.cursor.cloud_api import RETENTION_HEADER, CloudAgentsClient
from mission_control.adapters.cursor.environments import (
    CursorEnvironments,
    CursorEnvironmentsClient,
)
from mission_control.adapters.cursor.hooks_callback import CursorHookMapper
from mission_control.adapters.cursor.local import CursorLocalHarness, CursorLocalSettings
from mission_control.adapters.cursor.projection import projection_digests
from mission_control.adapters.cursor.scm import GitBranchPublisher
from mission_control.adapters.cursor.secrets import CursorSecretsClient
from mission_control.adapters.cursor.workspace import GitWorktreeLeaser, git
from mission_control.adapters.remote_session.sse import SseEvent, parse_sse_text, render_sse
from mission_control.adapters.workspaces.git_workspaces import GitWorkspaceBackend
from mission_control.application.agentic_components.placement import (
    RenderedProjectionSource,
    operating_contract,
    static_rows,
)
from mission_control.application.capabilities.bundle_custody import (
    BundleCustodyService,
    BundleMaterializer,
)
from mission_control.application.environments.mission_layer import MissionLayerService
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    InMemoryHookIntentLedger,
    InMemoryHookTokenStore,
    KernelHookCall,
)
from mission_control.application.execution.harness.leases import InMemoryWorkspaceLeaseStore
from mission_control.application.execution.stop_fence import (
    InMemoryStopFenceRepository,
    KernelHookFenceGate,
)
from mission_control.application.frames.sink import InMemoryFrameStore
from mission_control.application.workspaces.service import WorkspaceAllocator
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.contracts.hooks import HookResult, merge_results
from mission_control.domain.agentic_components.projection import ResolvedCapability
from mission_control.domain.authoring.contracts import PublishedDefinition
from mission_control.domain.capabilities.bundles import build_bundle_manifest
from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.capabilities.hooks import KERNEL_HOOK_EVENTS, KERNEL_HOOK_IDS, HookEvent
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from tests.fixtures.environment_kits import kit_files, published_kit
from tests.fixtures.lane_turns import cursor_binding, cursor_operation
from tests.support.artifacts import MemoryArtifacts

LOCAL_FIXTURES = (
    Path(__file__).resolve().parents[2] / "integration" / "cursor" / "fixtures" / "local"
)


def load_fixture(name: str) -> list[dict[str, Any]]:
    lines = (LOCAL_FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def make_repository(root: Path) -> Path:
    """A small git repository with one commit on `main` (the target repository)."""

    root.mkdir(parents=True, exist_ok=True)
    git("init", "--quiet", "--initial-branch=main", cwd=root)
    (root / "README.md").write_text("# target\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "Repository guide (owned by the repository).\n", encoding="utf-8"
    )
    git("add", "--all", cwd=root)
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@localhost",
        "commit",
        "--quiet",
        "-m",
        "base",
        cwd=root,
    )
    return root


HookInvoker = Callable[[dict[str, Any], Path], Awaitable[HookResult]]


@dataclass
class ReplayBridge:
    launcher: ReplayBridgeLauncher
    workspace: Path
    state_root: Path

    async def create_agent(self, spec: LocalAgentSpec) -> str:
        self.launcher.created.append(spec)
        if spec.sandbox_enabled and not self.launcher.sandbox:
            raise SandboxUnsupported("the Cursor sandbox is unavailable on this host")
        agent_id = self.launcher.next_agent()
        self.launcher.agent_roots[agent_id] = spec.cwd
        return agent_id

    async def resume_agent(self, agent_id: str, spec: LocalAgentSpec) -> str:
        self.launcher.resumed.append((agent_id, spec))
        if self.launcher.lost or agent_id not in self.launcher.known_agents():
            raise RunNotFound("unknown agent")
        return agent_id

    async def send(self, agent_id: str, text: str, *, idempotency_key: str) -> str:
        if self.launcher.busy_sends > 0:
            self.launcher.busy_sends -= 1
            raise AgentBusy("busy")
        prior = self.launcher.sent_runs.get(idempotency_key)
        if prior is not None:
            return prior  # the bridge deduplicates a send by its idempotency key
        self.launcher.sends.append((idempotency_key, text))
        self.launcher.sent_to.append(agent_id)
        run_id = self.launcher.next_run()
        self.launcher.sent_runs[idempotency_key] = run_id
        return run_id

    async def observe(self, run_id: str, *, after_offset: str | None) -> AsyncIterator[BridgeEvent]:
        self.launcher.observed_after.append(after_offset)
        after = int(after_offset) if after_offset else 0
        pending_hooks: list[dict[str, Any]] = []
        held_run = run_id == self.launcher.first_run
        draining = False
        for record in self.launcher.run_records(run_id):
            if record["kind"] == "hook":
                pending_hooks.append(record)
                continue
            if record["kind"] != "event":
                continue
            offset = int(record["offset"])
            envelope = record["envelope"]
            if record.get("after_cancel") and not draining:
                continue
            if offset <= after:
                pending_hooks.clear()
                continue
            for hook in pending_hooks:
                await self.launcher.fire(hook, self.workspace)
            pending_hooks.clear()
            if self.launcher.fail_at is not None and offset == self.launcher.fail_at:
                self.launcher.fail_at = None
                raise ConnectionError("bridge stream dropped")
            if "result" in envelope:
                await asyncio.to_thread(self.launcher.write_files, self.workspace, run_id)
            if (
                held_run
                and not draining
                and self.launcher.hold_at is not None
                and offset >= self.launcher.hold_at
            ):
                self.launcher.held.set()
                await self.launcher.release.wait()
                if run_id in self.launcher.cancelled_runs:
                    if self.launcher.drop_after_cancel:
                        return
                    draining = True
                    after = offset - 1
                    continue
            if draining and not record.get("after_cancel"):
                continue
            yield BridgeEvent(offset=str(offset), envelope=envelope)
        if draining:
            return
        for hook in pending_hooks:
            await self.launcher.fire(hook, self.workspace)

    async def run_state(self, run_id: str) -> RunState:
        if self.launcher.lost:
            raise RunNotFound("unknown run")
        state = next(r for r in self.launcher.run_records(run_id) if r["kind"] == "run_state")
        status = "cancelled" if run_id in self.launcher.cancelled_runs else state["status"]
        return RunState(
            run_id=run_id,
            agent_id=str(self.launcher.meta["agent_id"]),
            status=status,
            result=state.get("result", ""),
            duration_ms=state.get("duration_ms", 0),
            model=state.get("model"),
            usage=state.get("usage"),
        )

    async def cancel(self, run_id: str, *, agent_id: str) -> None:
        self.launcher.cancel_calls += 1
        state = next(
            (r for r in self.launcher.run_records(run_id) if r["kind"] == "run_state"), None
        )
        finished = (
            state is not None
            and run_id not in self.launcher.cancelled_runs
            and self.launcher.finished_runs.get(run_id, False)
        )
        if run_id in self.launcher.cancelled_runs or finished:
            raise RunNotCancellable("already terminal")
        self.launcher.cancelled_runs.add(run_id)
        if run_id == self.launcher.first_run:
            self.launcher.cancelled = True
        self.launcher.release.set()

    async def usage(self, agent_id: str) -> UsageState:
        usage = next(r for r in self.launcher.records if r["kind"] == "usage")
        if usage.get("feature_unavailable"):
            raise FeatureUnavailable("local usage is not enabled")
        return UsageState(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
            cost_micros_usd=usage.get("cost_micros_usd"),
        )

    async def agent_info(self, agent_id: str, *, cwd: str) -> AgentReadback:
        """As `get_agent` reports a local agent: rooted where it was created."""

        if agent_id not in self.launcher.agent_roots:
            raise RunNotFound("unknown agent")
        return AgentReadback(
            agent_id=agent_id, runtime="local", cwd=self.launcher.agent_roots[agent_id]
        )

    async def close_agent(self, agent_id: str) -> None:
        self.launcher.closed.append(agent_id)

    async def aclose(self) -> None:
        self.launcher.bridges_closed += 1


@dataclass
class ReplayBridgeLauncher:
    records: list[dict[str, Any]]
    hook_invoker: HookInvoker | None = None
    sandbox: bool = True
    busy_sends: int = 0
    lost: bool = False
    fail_at: int | None = None
    hold_at: int | None = None
    launches: list[tuple[Path, Path]] = field(default_factory=list)
    # The process environment each launch was given (MO-04 allowlist).
    environments: list[dict[str, str]] = field(default_factory=list)
    created: list[LocalAgentSpec] = field(default_factory=list)
    resumed: list[tuple[str, LocalAgentSpec]] = field(default_factory=list)
    sends: list[tuple[str, str]] = field(default_factory=list)
    observed_after: list[str | None] = field(default_factory=list)
    hook_results: list[tuple[str, str, HookResult]] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    bridges_closed: int = 0
    cancel_calls: int = 0
    cancelled: bool = False
    held: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    fired: set[int] = field(default_factory=set)
    # FT-G4: several agents and runs per fixture.
    drop_after_cancel: bool = False
    agents: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    sent_to: list[str] = field(default_factory=list)
    sent_runs: dict[str, str] = field(default_factory=dict)
    cancelled_runs: set[str] = field(default_factory=set)
    finished_runs: dict[str, bool] = field(default_factory=dict)
    agent_base: str | None = None
    # MO-34: each agent's project root as the SDK read-back reports it.
    agent_roots: dict[str, str] = field(default_factory=dict)

    @property
    def meta(self) -> dict[str, Any]:
        return next(r for r in self.records if r["kind"] == "meta")

    @property
    def first_run(self) -> str:
        return str(self.meta["run_id"])

    def next_agent(self) -> str:
        base = self.agent_base or str(self.meta["agent_id"])
        agent = base if not self.agents else f"{base}-{len(self.agents) + 1}"
        self.agents.append(agent)
        return agent

    def known_agents(self) -> set[str]:
        return {self.agent_base or str(self.meta["agent_id"]), *self.agents}

    def next_run(self) -> str:
        later = [str(item) for item in self.meta.get("later_runs", ())]
        order = [self.first_run, *later]
        index = len(self.runs)
        run = order[index] if index < len(order) else f"{self.first_run}-{index + 1}"
        self.runs.append(run)
        return run

    def run_records(self, run_id: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records
            if record["kind"] in {"event", "hook", "run_state", "workspace_write"}
            and str(record.get("run", self.first_run)) == run_id
        ]

    @property
    def versions(self) -> Mapping[str, str]:
        return {"cursor_sdk": "1.0.37", "bridge": "1.0.37", "protocol": "sdk.v1"}

    def sandbox_supported(self) -> bool:
        return self.sandbox

    async def launch(
        self, *, workspace: Path, state_root: Path, environment: Mapping[str, str]
    ) -> ReplayBridge:
        self.launches.append((workspace, state_root))
        self.environments.append(dict(environment))
        return ReplayBridge(self, workspace, state_root)

    async def fire(self, record: dict[str, Any], workspace: Path) -> None:
        if id(record) in self.fired or self.hook_invoker is None:
            return
        self.fired.add(id(record))
        payload = _substitute(record["payload"], str(workspace))
        result = await self.hook_invoker({**record, "payload": payload}, workspace)
        self.hook_results.append((record["native_event"], record.get("expect", "allow"), result))

    def write_files(self, workspace: Path, run_id: str | None = None) -> None:
        if run_id is not None:
            self.finished_runs[run_id] = True
        records = self.records if run_id is None else self.run_records(run_id)
        for record in records:
            if record["kind"] == "workspace_write":
                target = workspace / record["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(record["content"], encoding="utf-8")


def _substitute(value: Any, workspace: str) -> Any:
    if isinstance(value, dict):
        return {key: _substitute(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, workspace) for item in value]
    if isinstance(value, str):
        return value.replace("<workspace>", workspace)
    return value


def service_hook_invoker(service: HookCallbackService) -> HookInvoker:
    """Run every kernel hook Cursor runs for one native event, through the callback service,
    with the token the lane wrote into the lease (as `.mission/hooks/kernel.py` does)."""

    async def invoke(record: dict[str, Any], workspace: Path) -> HookResult:
        context = json.loads((workspace / ".mission/hooks/context.json").read_text("utf-8"))
        token = (workspace / ".mission/bin/.token").read_text("utf-8")
        event = HookEvent(record["mc_event"])
        results = []
        for hook_id in KERNEL_HOOK_IDS:
            if event not in KERNEL_HOOK_EVENTS[hook_id]:
                continue
            call = KernelHookCall(
                kernel_hook_id=hook_id,
                event=event,
                scope=context["scope"],
                harness_execution_id=context["harness_execution_id"],
                generation=context["generation"],
                payload=record["payload"],
            )
            results.append(await service.handle(call, token))
        return merge_results(results)

    return invoke


def projection_rows() -> tuple[ResolvedCapability, ...]:
    from tests.fixtures.projections.rows import hook_row, skill_row, tavily_row, verifier_row

    return (skill_row(), tavily_row(), hook_row(), verifier_row())


def pinned_binding(
    *,
    rows: tuple[ResolvedCapability, ...],
    operation_contract: str,
    repository: Path | None,
    policy: Mapping[str, str] | None = None,
    **changes: Any,
) -> CursorExecutionBinding:
    projection = HOST_PROJECTORS.render(rows, "cursor_local", operation_contract, None)
    digests = projection_digests(projection)
    workspace: dict[str, Any] = {"base_ref": "main"}
    if repository is not None:
        workspace["repo_url"] = str(repository)
    if policy is not None:
        workspace["policy"] = dict(policy)
    return cursor_binding(
        "cursor_local",
        projections={**digests},
        workspace=workspace,
        **changes,
    )


@dataclass
class LocalStack:
    harness: CursorLocalHarness
    launcher: ReplayBridgeLauncher
    hooks: HookCallbackService
    tokens: InMemoryHookTokenStore
    intents: InMemoryHookIntentLedger
    fences: InMemoryStopFenceRepository
    frames: InMemoryFrameStore
    leases: InMemoryWorkspaceLeaseStore
    artifacts: MemoryArtifacts
    operation: OperationExecutionRequest
    lease_root: Path


def local_stack(
    tmp_path: Path,
    fixture: str = "full_run",
    *,
    repository: bool = True,
    binding_changes: Mapping[str, Any] | None = None,
    launcher_changes: Mapping[str, Any] | None = None,
    frames: InMemoryFrameStore | None = None,
    drift: bool = False,
    operation_changes: Mapping[str, Any] | None = None,
    artifacts: MemoryArtifacts | None = None,
    inputs: Any = None,
    settings_changes: Mapping[str, Any] | None = None,
    lease_dir: str = "leases",
    mission_layer: MissionLayerService | None = None,
) -> LocalStack:
    records = load_fixture(fixture)
    rows = projection_rows()
    base = cursor_operation()
    from mission_control.application.agentic_components.placement import operating_contract

    repo = make_repository(tmp_path / "repo") if repository else None
    changes = dict(binding_changes or {})
    meta = next(r for r in records if r["kind"] == "meta")
    if meta.get("disallowed_tools") and "disallowed_tools" not in changes:
        changes["disallowed_tools"] = tuple(meta["disallowed_tools"])
    binding = pinned_binding(
        rows=rows, operation_contract=operating_contract(base), repository=repo, **changes
    )
    if drift:
        binding = cursor_binding(
            "cursor_local",
            projections={**binding.projections.model_dump(), "hooks_digest": "sha256:" + "f" * 64},
            workspace=binding.workspace.model_dump(exclude_none=True),
            **changes,
        )
    operation = cursor_operation(binding=binding)
    if operation_changes:
        operation = OperationExecutionRequest.model_validate(
            {**operation.model_dump(mode="python"), **dict(operation_changes)}
        )
    frames = frames or InMemoryFrameStore()
    tokens = InMemoryHookTokenStore()
    intents = InMemoryHookIntentLedger()
    fences = InMemoryStopFenceRepository()

    def context_reader(context: Any) -> str | None:
        path = Path(context.workspace_root or "") / ".mission/context.md"
        return path.read_text("utf-8") if path.is_file() else "packet index"

    hooks = HookCallbackService(
        tokens=tokens,
        intents=intents,
        mapper=CursorHookMapper(),
        fences=KernelHookFenceGate(fences),
        frames=frames,
        context_reader=context_reader,
    )
    launcher = ReplayBridgeLauncher(
        records, hook_invoker=service_hook_invoker(hooks), **dict(launcher_changes or {})
    )
    leases = InMemoryWorkspaceLeaseStore()
    artifacts = artifacts or MemoryArtifacts()
    lease_root = tmp_path / lease_dir
    harness = CursorLocalHarness(
        launcher=launcher,
        leaser=GitWorktreeLeaser(leases, lease_root=lease_root, artifacts=artifacts),
        projections=RenderedProjectionSource(static_rows(rows), projectors=HOST_PROJECTORS),
        hooks=hooks,
        artifacts=artifacts,
        inputs=inputs,
        settings=CursorLocalSettings(lease_root=lease_root, **dict(settings_changes or {})),
        mission_layer=mission_layer,
    )
    # FT-G4: the stop hook's `missing_output_policy` follow-up knows the declared outputs.
    hooks.set_stop_policy(harness)
    return LocalStack(
        harness,
        launcher,
        hooks,
        tokens,
        intents,
        fences,
        frames,
        leases,
        artifacts,
        operation,
        lease_root,
    )


CLOUD_FIXTURES = (
    Path(__file__).resolve().parents[2] / "integration" / "cursor" / "fixtures" / "cloud"
)
_HOOK_ENV = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")
API_KEY = "cursor-test-key-not-real"
PRESIGNED = "https://s3.fake.invalid/presigned"


def load_sse(name: str) -> list[SseEvent]:
    return parse_sse_text((CLOUD_FIXTURES / f"{name}.sse").read_text(encoding="utf-8"))


def load_cloud_fixture(
    stream: str = "run_stream", record: str = "run_record"
) -> tuple[list[SseEvent], dict[str, Any]]:
    events = load_sse(stream)
    loaded = json.loads((CLOUD_FIXTURES / f"{record}.json").read_text(encoding="utf-8"))
    return events, loaded


class _HeldStream(httpx.AsyncByteStream):
    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        aclose = getattr(self._chunks, "aclose", None)
        if aclose is not None:
            await aclose()


@dataclass(frozen=True)
class HookRun:
    native_event: str
    command: str
    exit_code: int
    stdout: str


def run_cursor_hooks(
    root: Path, events: Sequence[tuple[str, Mapping[str, Any]]], env: Mapping[str, str]
) -> list[HookRun]:
    """FIXTURE stand-in for Cursor's hook engine (research/cursor.md section 5.1): for each
    `(native event, payload)`, every `.cursor/hooks.json` command of that event runs in order
    in the workspace with the JSON payload on stdin (`python` is this interpreter)."""

    hooks = json.loads((root / ".cursor" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    environment = {key: os.environ[key] for key in _HOOK_ENV if key in os.environ} | dict(env)
    runs: list[HookRun] = []
    for native, payload in events:
        body = json.dumps({"hook_event_name": native, **payload})
        for entry in hooks.get(native, ()):
            argv = shlex.split(entry["command"])
            if argv[0] == "python":
                argv[0] = sys.executable
            done = subprocess.run(
                argv,
                input=body,
                capture_output=True,
                text=True,
                cwd=root,
                env=environment,
                timeout=entry.get("timeout", 30) + 30,
                check=False,
            )
            runs.append(HookRun(native, entry["command"], done.returncode, done.stdout))
    return runs


def make_remote(root: Path) -> Path:
    """A bare `origin` with one `main` commit (the target repository the cloud agent clones)."""

    source = make_repository(root / "source")
    bare = root / "remote.git"
    git("clone", "--quiet", "--bare", str(source), str(bare), cwd=root)
    return bare


@dataclass
class FakeCloudApi:
    events: list[SseEvent]
    record: dict[str, Any]
    remote: Path
    metadata_unavailable: bool = False
    busy: bool = False
    expire_after: str | None = None
    cut_after: str | None = None
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    stream_requests: list[str | None] = field(default_factory=list)
    creates: list[dict[str, Any]] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    pushed: bool = False
    # FT-G6 controls.
    hold_after: str | None = None
    after_cancel: list[SseEvent] = field(default_factory=list)
    later: list[list[SseEvent]] = field(default_factory=list)
    run_events: dict[str, list[SseEvent]] = field(default_factory=dict)
    created_runs: list[str] = field(default_factory=list)
    run_prompts: dict[str, str] = field(default_factory=dict)
    held: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    hold_done: bool = False
    # MP-09 controls (FIXTURE): `429` refusals before any work is accepted, run creates whose
    # response is lost after the provider accepted, a stream that expires while the run is
    # still running (`GET run` reports RUNNING for `running_reads` more reads), and usage
    # responses that omit this run.
    rate_limited_creates: int = 0
    rate_limited_runs: int = 0
    retry_after_s: int | None = 7
    lose_run_responses: int = 0
    running_reads: int = 0
    usage_shape: str = "per_run"  # per_run | totals_only | empty | unavailable
    # `400 invalid_last_event_id` for a cursor that is not one of this run's event ids.
    reject_foreign_cursor: bool = False
    run_reads: int = 0
    rate_limit_refusals: int = 0
    expired_served: bool = False
    # MO-41: the hook events the VM fires before the agent's commit, and what they did.
    vm: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    hook_runs: list[HookRun] = field(default_factory=list)
    # Conversation export controls (FIXTURE): the export is absent (`404`), or the native origin
    # moves while the export is read: `branch` pushes a foreign commit to the agent's branch
    # (its head is `foreign_head`), `native` points the agent at a foreign run.
    conversation_missing: bool = False
    conversation_moves: str | None = None  # branch | native
    foreign_head: str | None = None
    # The provider forgets a run once it is cancelled: `GET run` then answers `404`.
    forget_cancelled_runs: bool = False

    @property
    def run_id(self) -> str:
        return str(self.record["run"]["id"])

    def _rate_limited(self) -> httpx.Response:
        self.rate_limit_refusals += 1
        headers = {"Retry-After": str(self.retry_after_s)} if self.retry_after_s else {}
        return httpx.Response(
            429,
            headers=headers,
            json={"error": {"code": "rate_limited", "message": "too many requests"}},
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @staticmethod
    def _error(status: int, code: str) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": code, "message": code}})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if url.host == "s3.fake.invalid":
            assert "authorization" not in {key.lower() for key in request.headers}
            self.downloads.append(url.path)
            path = url.params.get("path", "")
            return httpx.Response(200, content=self.record["artifacts"][path].encode("utf-8"))
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        parts = url.path.strip("/").split("/")
        method = request.method
        if parts[:2] == ["v1", "agents"] and len(parts) == 2 and method == "POST":
            return self._create(request)
        if parts[:2] == ["v0", "agents"] and parts[3:] == ["conversation"]:
            if self.conversation_missing:
                return self._error(404, "agent_not_found")
            self._move_origin(parts[2])
            return httpx.Response(200, json={"messages": []})
        agent_id = parts[2]
        agent = self.agents.get(agent_id)
        if agent is None:
            return self._error(404, "agent_not_found")
        rest = parts[3:]
        if not rest and method == "GET":
            return httpx.Response(200, json={"agent": agent})
        if rest == ["runs"] and method == "POST":
            if self.rate_limited_runs > 0:
                self.rate_limited_runs -= 1
                return self._rate_limited()
            run = self.runs[agent["latestRunId"]]
            if self.busy or run["status"] not in {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}:
                return self._error(409, "agent_busy")
            new = {"id": f"run-{uuid4()}", "agentId": agent_id, "status": "CREATING"}
            self._register_run(new, json.loads(request.content))
            agent["latestRunId"] = new["id"]
            agent["status"] = "ACTIVE"
            if self.lose_run_responses > 0:
                # The provider accepted the run; the response never reaches the caller.
                self.lose_run_responses -= 1
                raise httpx.ReadError("connection reset after the provider accepted the run")
            return httpx.Response(200, json={"run": new})
        if len(rest) >= 2 and rest[0] == "runs":
            run = self.runs.get(rest[1])
            if run is None:
                return self._error(404, "run_not_found")
            if len(rest) == 2 and method == "GET":
                self.run_reads += 1
                if self.running_reads > 0 and run["status"] != "CANCELLED":
                    # The stream retention passed while the run kept running.
                    self.running_reads -= 1
                    return httpx.Response(200, json={"run": {**run, "status": "RUNNING"}})
                if self.expired_served and run["status"] in {"CREATING", "RUNNING"}:
                    # The retention window passed while the run kept running; it is final now.
                    self._finish(agent, run)
                return httpx.Response(200, json={"run": run})
            if rest[2:] == ["cancel"] and method == "POST":
                if run["status"] in {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}:
                    return self._error(409, "run_not_cancellable")
                run["status"] = "CANCELLED"
                agent["status"] = "IDLE"
                self.cancelled.append(rest[1])
                self.release.set()
                if self.forget_cancelled_runs:
                    del self.runs[rest[1]]
                return httpx.Response(200, json={"run": run})
            if rest[2:] == ["stream"] and method == "GET":
                return self._stream(request, agent, run)
        if rest == ["artifacts"] and method == "GET":
            items = [
                {"path": path, "sizeBytes": len(content), "updatedAt": "2026-10-08T12:00:00Z"}
                for path, content in self.record["artifacts"].items()
            ]
            return httpx.Response(200, json={"items": items})
        if rest == ["artifacts", "download"] and method == "GET":
            path = url.params["path"]
            return httpx.Response(
                200, json={"url": f"{PRESIGNED}?path={path}&sig=abc", "expiresAt": "later"}
            )
        if rest == ["usage"] and method == "GET":
            if url.params.get("runId") not in {None, *self.runs}:
                return self._error(404, "run_not_found")
            if self.usage_shape == "unavailable":
                return self._error(403, "feature_unavailable")
            if self.usage_shape == "empty":
                return httpx.Response(200, json={})
            if self.usage_shape == "totals_only":
                return httpx.Response(
                    200, json={"totalUsage": self.record["usage"]["totalUsage"], "runs": []}
                )
            return httpx.Response(200, json=self.record["usage"])
        if rest == ["archive"] and method == "POST":
            self.archived.append(agent_id)
            agent["status"] = "ARCHIVED"
            return httpx.Response(200, json={})
        return self._error(404, "route_not_found")

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.creates.append(body)
        if self.rate_limited_creates > 0:
            self.rate_limited_creates -= 1
            return self._rate_limited()
        key = request.headers.get("Idempotency-Key")
        if key is not None and key in self.idempotency:
            return httpx.Response(200, json=self.idempotency[key])
        if "metadata" in body and self.metadata_unavailable:
            return self._error(403, "feature_unavailable")
        agent_id = body.get("agentId") or f"bc-{uuid4()}"
        if agent_id in self.agents:
            return self._error(409, "agent_id_conflict")
        run_id = self.run_id if self.run_id not in self.runs else f"run-{uuid4()}"
        run = {"id": run_id, "agentId": agent_id, "status": "CREATING"}
        agent = {
            "id": agent_id,
            "name": body.get("name"),
            "status": "ACTIVE",
            "url": f"https://cursor.com/agents/{agent_id}",
            "latestRunId": run["id"],
            "repos": body.get("repos"),
        }
        self.agents[agent_id] = agent
        self._register_run(run, body)
        response = {"agent": agent, "run": run}
        if key is not None:
            self.idempotency[key] = response
        return httpx.Response(200, json=response)

    def _register_run(self, run: dict[str, Any], body: dict[str, Any]) -> None:
        self.runs[run["id"]] = run
        self.created_runs.append(run["id"])
        prompt = (body.get("prompt") or {}).get("text")
        if prompt is not None:
            self.run_prompts[run["id"]] = str(prompt)
        if run["id"] != self.run_id and self.later:
            self.run_events[run["id"]] = self.later.pop(0)

    def _stream(
        self, request: httpx.Request, agent: dict[str, Any], run: dict[str, Any]
    ) -> httpx.Response:
        last = request.headers.get("Last-Event-ID")
        self.stream_requests.append(last)
        events_of_run = self.run_events.get(run["id"], self.events)
        if (
            self.reject_foreign_cursor
            and last is not None
            and last not in {event.id for event in events_of_run if event.id is not None}
        ):
            return self._error(400, "invalid_last_event_id")
        if (
            self.expire_after is not None
            and last is not None
            and int(last) >= int(self.expire_after)
        ):
            self.expired_served = True
            if self.running_reads <= 0:
                self._finish(agent, run)
            return self._error(410, "stream_expired")
        events = self.run_events.get(run["id"], self.events)
        held = run["id"] == self.run_id and self.hold_after is not None and not self.hold_done

        async def chunks() -> AsyncIterator[bytes]:
            if run["status"] == "CANCELLED" and run["id"] in self.cancelled:
                # A cancelled run's stream drains what closed during the cancel, then ends.
                for event in events:
                    if event.id is None and event.event == "status":
                        yield render_sse([event]).encode("utf-8")
                        break
                for extra in self.after_cancel:
                    if last is None or extra.id is None or int(extra.id) > int(last):
                        yield render_sse([extra]).encode("utf-8")
                return
            seen_last = last is None
            for event in events:
                if event.id is None:
                    # The leading status has no id and is re-sent on every reconnect.
                    if event.event == "status" or seen_last:
                        yield render_sse([event]).encode("utf-8")
                    continue
                if not seen_last:
                    seen_last = event.id == last
                    continue
                if event.event == "result":
                    # The run is final (and the agent's commit pushed) before the client
                    # reads the result event: the reader may close the stream right after it.
                    self._finish(agent, run)
                yield render_sse([event]).encode("utf-8")
                if self.cut_after is not None and event.id == self.cut_after:
                    self.cut_after = None
                    return
                if held and event.id == self.hold_after:
                    self.held.set()
                    await self.release.wait()
                    self.hold_done = True
                    if run["status"] == "CANCELLED":
                        for extra in self.after_cancel:
                            yield render_sse([extra]).encode("utf-8")
                        return

        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/event-stream",
                RETENTION_HEADER: str(self.record["retention_seconds"]),
            },
            stream=_HeldStream(chunks()),
        )

    def _finish(self, agent: dict[str, Any], run: dict[str, Any]) -> None:
        if run.get("status") == "CANCELLED":
            agent["status"] = "IDLE"
            return
        final = self.record["run"]
        run.update({key: value for key, value in final.items() if key != "id"})
        agent["status"] = "IDLE"
        if not self.pushed:
            self._push_agent_commit(run)
            self.pushed = True

    def _move_origin(self, agent_id: str) -> None:
        moves, self.conversation_moves = self.conversation_moves, None
        if moves == "native":
            self.agents[agent_id]["latestRunId"] = "foreign-run"
        elif moves == "branch":
            branch = next(repo["startingRef"] for repo in self.agents[agent_id]["repos"])
            self._push_commit(branch, {"path": "FOREIGN.md", "content": "foreign\n"}, vm=False)
            self.foreign_head = git("rev-parse", branch, cwd=self.remote).strip()

    def _push_agent_commit(self, run: dict[str, Any]) -> None:
        branch = next(
            (repo.get("startingRef") for agent in self.agents.values() for repo in agent["repos"]),
            None,
        )
        if branch is None:
            return
        self._push_commit(branch, self.record["agent_branch_commit"], vm=True)

    def _push_commit(self, branch: str, commit: dict[str, Any], *, vm: bool) -> None:
        with tempfile.TemporaryDirectory(prefix="fake-cloud-agent-") as scratch:
            work = Path(scratch) / "clone"
            git(
                "clone",
                "--quiet",
                "--branch",
                branch,
                str(self.remote),
                str(work),
                cwd=Path(scratch),
            )
            if vm and self.vm:
                env_vars = next((body.get("envVars") or {} for body in self.creates), {})
                self.hook_runs.extend(run_cursor_hooks(work, self.vm, env_vars))
            target = work / commit["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(commit["content"], encoding="utf-8")
            git("add", "--all", cwd=work)
            git(
                "-c",
                "user.name=Cursor Agent",
                "-c",
                "user.email=agent@localhost",
                "commit",
                "--quiet",
                "-m",
                "agent work",
                cwd=work,
            )
            git("push", "--quiet", "origin", branch, cwd=work)


def cloud_rows() -> tuple[ResolvedCapability, ...]:
    from tests.fixtures.projections.rows import hook_row, tavily_row, verifier_row

    return (tavily_row(), hook_row(), verifier_row())


@dataclass
class CloudStack:
    harness: CursorCloudHarness
    api: FakeCloudApi
    client: CloudAgentsClient
    artifacts: MemoryArtifacts
    operation: OperationExecutionRequest
    remote: Path
    # MP-09: the provider workspace ledger the harness records its branch leases in.
    leases: InMemoryWorkspaceLeaseStore | None = None
    workspaces: WorkspaceAllocator | None = None


def cloud_operation(
    remote: Path | str,
    rows: tuple[ResolvedCapability, ...],
    *,
    gates: SignalGatePolicy | None = None,
    **cloud_changes: Any,
) -> OperationExecutionRequest:
    base = cursor_operation("cursor_cloud")
    projection = HOST_PROJECTORS.render(
        rows, "cursor_cloud", operating_contract(base), None, (), gates=gates
    )
    binding = cursor_binding(
        "cursor_cloud",
        projections=projection_digests(projection),
        workspace={"base_ref": "main", "repo_url": str(remote)},
        cloud={"auto_create_pr": False, **cloud_changes},
        signal_gates=gates,
    )
    return cursor_operation("cursor_cloud", binding=binding)


def cloud_stack(
    tmp_path: Path,
    *,
    cloud_changes: dict[str, Any] | None = None,
    api_changes: dict[str, Any] | None = None,
    cost: int | None = None,
    env_vars: dict[str, str] | None = None,
    stream: str = "run_stream",
    record: str = "run_record",
    operation_changes: dict[str, Any] | None = None,
    remote: Path | None = None,
    inputs: Any = None,
    artifacts: MemoryArtifacts | None = None,
    workspaces: bool = True,
    harness_changes: dict[str, Any] | None = None,
    env_resolver: CloudEnvResolver | None = None,
    rows: tuple[ResolvedCapability, ...] | None = None,
    gates: SignalGatePolicy | None = None,
) -> CloudStack:
    events, record_body = load_cloud_fixture(stream, record)
    remote = remote or make_remote(tmp_path)
    rows = rows or cloud_rows()
    operation = cloud_operation(remote, rows, gates=gates, **(cloud_changes or {}))
    if operation_changes:
        operation = OperationExecutionRequest.model_validate(
            {**operation.model_dump(mode="python"), **operation_changes}
        )
    api = FakeCloudApi(events, record_body, remote, **(api_changes or {}))
    client = CloudAgentsClient(SecretStr(API_KEY), transport=api.transport())
    artifacts = artifacts or MemoryArtifacts()

    async def cost_reader(agent_id: str, run_id: str) -> int | None:
        return cost

    async def fixed_env_vars(ref: str) -> dict[str, str]:
        return dict(env_vars or {})

    leases: InMemoryWorkspaceLeaseStore | None = None
    allocator: WorkspaceAllocator | None = None
    if workspaces:
        leases = InMemoryWorkspaceLeaseStore()
        root = tmp_path / "provider-workspaces"
        allocator = WorkspaceAllocator(
            ledger=leases,
            backend=GitWorkspaceBackend(root),
            root=root,
            allocator_ref="fixture:cursor-cloud",
        )
    harness = CursorCloudHarness(
        client=client,
        publisher=GitBranchPublisher(tmp_path / "mirrors"),
        projections=RenderedProjectionSource(
            static_rows(rows), kernel_hooks=(), projectors=HOST_PROJECTORS
        ),
        artifacts=artifacts,
        inputs=inputs,
        cost_reader=cost_reader,
        env_resolver=env_resolver or fixed_env_vars,
        workspaces=allocator,
        expired_poll_interval_s=0.01,
        **dict(harness_changes or {}),
    )
    return CloudStack(harness, api, client, artifacts, operation, remote, leases, allocator)


@dataclass
class FakeEnvironmentsApi:
    environments: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    secrets: dict[str, dict[str, str]] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)
    # A repository the account's Git integration does not grant (`400 repository_access`).
    inaccessible: set[str] = field(default_factory=set)
    # Configurations the provider stores differently from what it was sent (read-back drift).
    rewrite: dict[str, str] = field(default_factory=dict)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path in self.requests if method != "GET"]

    @staticmethod
    def _error(status: int, code: str, **extra: Any) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": code, "message": code, **extra}})

    def _version(self, environment_id: str, config: str, *, kind: str, source: str) -> None:
        for entry in self.history[environment_id]:
            entry["current"] = False
        self.history[environment_id].insert(
            0,
            {
                "id": str(uuid4()),
                "kind": kind,
                "source": source,
                "current": True,
                "environmentJson": self.rewrite.get(config, config),
            },
        )
        self.environments[environment_id]["versionId"] = str(uuid4())

    def dashboard_edit(self, environment_id: str, config: str) -> None:
        self._version(environment_id, config, kind="updated", source="dashboard")

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        self.requests.append((request.method, request.url.path))
        parts = request.url.path.strip("/").split("/")
        method = request.method
        if parts == ["v1", "environments"]:
            return self._create(request) if method == "POST" else self._list(request)
        environment_id = parts[2]
        environment = self.environments.get(environment_id)
        if environment is None:
            return self._error(404, "environment_not_found")
        rest = parts[3:]
        if not rest:
            if method == "GET":
                return httpx.Response(200, json=environment)
            if method == "PATCH":
                body = json.loads(request.content)
                self._version(environment_id, body["environmentJson"], kind="updated", source="api")
                return httpx.Response(204)
            if method == "DELETE":
                del self.environments[environment_id]
                return httpx.Response(200, json={"id": environment_id})
        if rest == ["history"]:
            return httpx.Response(200, json={"items": self.history[environment_id]})
        stored = self.secrets.setdefault(environment_id, {})
        if rest == ["secrets"]:
            items = [
                {"id": f"secv_{name}", "name": name, "type": "runtime_secret", "repos": []}
                for name in stored
            ]
            return httpx.Response(200, json={"items": items, "nextCursor": None})
        if rest[0] == "secrets" and len(rest) == 2:
            name = rest[1]
            if method == "PUT":
                body = json.loads(request.content)
                assert body["type"] == "runtime_secret"
                stored[name] = body["value"]
                return httpx.Response(201, json={"id": f"secv_{name}", "name": name})
            if method == "DELETE":
                if name not in stored:
                    return self._error(404, "secret_not_found")
                del stored[name]
                return httpx.Response(200, json={"name": name})
        return self._error(404, "route_not_found")

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        for existing in self.environments.values():
            if existing["name"] == body["name"] and existing["owner"] == body["owner"]:
                return self._error(409, "environment_name_conflict", environmentId=existing["id"])
        for repo in body["repos"]:
            if repo["url"] in self.inaccessible:
                return self._error(400, "repository_access")
        environment_id = str(uuid4())
        self.environments[environment_id] = {
            "id": environment_id,
            "name": body["name"],
            "owner": body["owner"],
            "repos": body["repos"],
        }
        self.history[environment_id] = []
        self._version(environment_id, body["environmentJson"], kind="created", source="api")
        created = {
            key: value
            for key, value in self.environments[environment_id].items()
            if key != "versionId"
        }
        return httpx.Response(201, json=created)

    def _list(self, request: httpx.Request) -> httpx.Response:
        items = [
            {key: value for key, value in item.items() if key != "versionId"}
            for item in self.environments.values()
        ]
        # One item per page, so the client's paging is exercised.
        start = int(request.url.params.get("cursor") or 0)
        page = items[start : start + 1]
        cursor = str(start + 1) if start + 1 < len(items) else None
        return httpx.Response(200, json={"items": page, "nextCursor": cursor})


def cursor_environments(api: FakeEnvironmentsApi) -> CursorEnvironments:
    transport = api.transport()
    return CursorEnvironments(
        CursorEnvironmentsClient(SecretStr(API_KEY), transport=transport),
        CursorSecretsClient(SecretStr(API_KEY), transport=transport),
    )


async def kit_in_custody(
    root: Path, document: dict[str, Any], *files: tuple[str, bytes]
) -> tuple[PublishedDefinition, BundleMaterializer]:
    """A published kit whose bundle bytes are in a filesystem custody store, and the
    materializer that reads them back verified (what `prepare` uses for the base layer)."""

    published = published_kit(document, *files)
    store = FilesystemBundleObjectStore(root)
    manifest = build_bundle_manifest(
        kit_files(document, *files),
        application_id="biotech",
        kind="environment_kit",
        capability_id=document["id"],
        version=document["version"],
    )
    await BundleCustodyService(store=store).upload(manifest, kit_files(document, *files))
    return published, BundleMaterializer(store, FilesystemBundleFetcher(store))
