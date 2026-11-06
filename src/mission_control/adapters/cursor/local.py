"""The `cursor_local` Lane Profile: Cursor's Python SDK bridge on the worker (SPEC-07 section 5).

One Session Turn of a bound operation, driven by `lane.turn` (FT-G2):

- `prepare` leases a git worktree at the binding's base ref under its workspace policy (the
  MP-04 allocator; MO-05), materializes the Context Packet
  (`.mission/`, `inputs/`, `outputs/`), places the FT-A4 Host Projection (Kernel Hooks first,
  fail-closed) plus `.mission/hooks/kernel.py` through `materialize_projection`, layered over
  the repository under the binding's `materialization` policy (MO-02: the repository's
  `AGENTS.md` stays, its `.cursor/hooks.json` and `.cursor/mcp.json` are merged), and refuses
  `CAPABILITY_DRIFT` (projection digests differ from the binding, or an unsafe path),
  `MATERIALIZATION_CONFLICT` (a conflict the policy refuses) or `UNSUPPORTED_BEHAVIOR`
  (sandbox requested on a host without it); a binding that pins an Environment Kit then runs
  its mission layer with the bridge's environment and refuses `ENVIRONMENT_NOT_PREPARED`
  short of a passing receipt (MO-12);
- `start` launches the bridge with a pinned `state_root` and the MO-04 allowlisted
  environment (the inherited platform names and the variables the projected
  `.cursor/mcp.json` reads; never the worker's whole environment), creates the agent with
  `setting_sources=["project"]`, then mints the hook task token (bound to scope, run, attempt,
  generation and harness execution; only its digest is stored) and writes it with mode 0600;
- `send_turn` associates the turn with the kernel dispatch key
  `<execution>:<generation>:turn:<n>`; the local SDK wire request omits the cloud-only key;
- `observe` maps `run.observe(after_offset)` envelopes to frames keyed
  `cursor_local_key("<run_id>:<offset>")`, synthesizing the terminal frame from the run record
  when a stream ends without one;
- `end_session` restores the repository files layering merged, stores the git patch (diff
  plus untracked files) and `outputs/`, closes the agent and the bridge, revokes the token,
  and releases the lease only after the patch is stored; `cleanup_workspace` removes the
  released worktree once the operation workflow settled the unit (MO-05).

`reattach` re-launches the bridge over the same lease and `state_root` and resumes the agent
(emulated: a turn the bridge store no longer knows raises `NativeTurnLost`), re-supplying the
options `Agent.resume` does not persist (tools, disallowed tools, inline MCP servers and
subagents: `cursor_sdk` 1.0.37 `_async_client.resume_agent(agent_id, options)`) and recording
what it re-applied in the handle (MP-09 option rehydration). Qualification stays false until
FT-G6 / OVE-55 records a real run (`describe().qualified=False`).

MP-09 host gate: the bridge is a subprocess, and the production worker pins a
SelectorEventLoop on Windows, so `prepare` and `start` consult the launcher's `host_gate()`
and refuse `LANE_UNSUPPORTED_OS` before leasing or spawning anything; the supported path is a
WSL 2 or Linux worker (docs/qualification/lanes/cursor_local/README.md).

MP-09 `reconcile_dispatch` (MP-06 `DispatchReconcilingLane`): local Send does not support
the SDK's cloud-only idempotency key or lookup by that key. A journaled send is `found`
from the remembered kernel-key/run association or a unique native run after its durable
dispatch anchor. Otherwise the lane answers `unknown`, which parks the unit `in_doubt`
rather than resending blindly. A journaled create is `found` only from the same memory.

FT-G4 controls (SPEC-07 section 7): cursors are turn-qualified (`<run_id>@<offset>`, so a
replacement or continuation turn never resumes from another run's offset); a later turn's text
is staged by its instruction ref (`stage_turn`: the injected item of a `cancel_and_replace`
replacement, a continuation's hydration prompt); `snapshot` freezes `mc.cursor_snapshot.v1`
(patch, untracked files, packet files with digests, native refs); `prepare` restores the
packet's `workspace` item (a fork) into the fresh lease before anything else is placed; the
`stop` hook asks once for missing declared outputs (`missing_output_policy` follow-up) and a
finished session that still lacks them closes with `missing_outputs`; a continuation hydrates
a fresh agent in the same lease (`CursorSessionHydrator`, `adapters/cursor/controls.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from mission_control.adapters.cursor import snapshot as snapshots
from mission_control.adapters.cursor.bridge import (
    LANE_UNSUPPORTED_OS,
    AgentBusy,
    CursorBridgeLauncher,
    CursorLocalBridge,
    FeatureUnavailable,
    HostGate,
    LocalAgentSpec,
    RunNotCancellable,
    RunNotFound,
    SandboxUnsupported,
    SdkBridgeLauncher,
    SdkLocalBridge,
)
from mission_control.adapters.cursor.cognition_points import cursor_turn_points
from mission_control.adapters.cursor.describe import CURSOR_LOCAL_DESCRIBE
from mission_control.adapters.cursor.discovery import setting_readback_report
from mission_control.adapters.cursor.frames import (
    closing_facts,
    final_lane_frame,
    local_lane_frame,
    offset_of,
    run_of,
)
from mission_control.adapters.cursor.frames import first as first
from mission_control.adapters.cursor.hooks_callback import install_hook_context, kernel_hook_script
from mission_control.adapters.cursor.projection import (
    network_projection,
    projection_digests,
    verify_projection,
)
from mission_control.adapters.cursor.time_travel import SEED_SNAPSHOT_REF, SEED_TRANSCRIPT_REF
from mission_control.adapters.cursor.usage import CursorNativeRunUsage
from mission_control.adapters.cursor.workspace import CURSOR_LOCAL_POLICY, GitWorktreeLeaser
from mission_control.application.agentic_components.layering import (
    MATERIALIZATION_CONFLICT,
    LayeringRefused,
    restore_repository_files,
)
from mission_control.application.agentic_components.materialization import (
    MaterializationRejected,
    ProjectionMaterialization,
    materialize_projection,
)
from mission_control.application.agentic_components.placement import (
    CAPABILITY_DRIFT,
    KERNEL_HOOK_PATH,
    OUTPUTS_DIR,
    STATE_ROOT,
    UNSUPPORTED_BEHAVIOR,
    DurableInputReader,
    LaneProjectionError,
    ProjectionSource,
    materialize_packet,
    packet_files,
    turn_text,
    write_files,
)
from mission_control.application.environments.discovery import discovery_expectation
from mission_control.application.environments.mission_layer import (
    EnvironmentNotPrepared,
    MissionLayerOutcome,
    MissionLayerService,
    run_mission_layer,
)
from mission_control.application.execution.child_environment import provider_child_environment
from mission_control.application.execution.harness.controls import SessionHandover
from mission_control.application.execution.harness.dispatch import DispatchLookup, DispatchRecord
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    HookTokenContext,
)
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    execution_start,
    harness_scope,
)
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.execution.harness.points import TurnPointsRequest
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.application.execution.operations.lane_outputs import LaneOutputCustody
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from mission_control.application.workspaces.errors import StaleWorkspaceLease
from mission_control.domain.agentic_components.projection import HostProjection, ProjectedFile
from mission_control.domain.authoring.canonical import sha256_digest, stable_json_digest
from mission_control.domain.context.render import INPUTS_MANIFEST_PATH
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.execution.cognition_points import CognitionPointObservation
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.discovery import DiscoveryReport
from mission_control.domain.execution.lane_turns import CleanupOutcome, ClosingFacts
from mission_control.domain.execution.lanes import (
    CancelReceipt,
    CancelTurnRequest,
    CleanupReceipt,
    CursorExecutionBinding,
    EndSessionRequest,
    HarnessRequest,
    LaneDescribe,
    LaneFrame,
    LaneSeedHead,
    ObserveRequest,
    PreparedSession,
    PrepareRequest,
    ProviderStatus,
    ReattachRequest,
    SendTurnRequest,
    SessionHandle,
    SnapshotManifest,
    SnapshotRequest,
    StartRequest,
    StatusRequest,
    TurnHandle,
    UsageReport,
    UsageRequest,
)

PROFILE = "cursor_local"


class LaneArtifactSink(Protocol):
    """Stores a lane artifact's bytes and returns a digest-bound durable reference."""

    async def stage(
        self, *, request_scope: str, name: str, content: bytes, media_type: str
    ) -> str: ...


@dataclass(frozen=True)
class CursorLocalSettings:
    lease_root: Path
    callback_base_url: str = "http://127.0.0.1:47555"
    token_ttl: timedelta = timedelta(hours=4)
    mount_root: str = ""
    # A worker-local checkout used when the binding names no repository (Mission 3 binds one).
    default_repository: str | None = None
    # FT-G4 `missing_output_policy`: one follow-up asking for the declared outputs (SPEC-07
    # user story 26); False closes a session without them `not_accepted` at once.
    missing_output_follow_up: bool = True
    # The worker environment the bridge's allowlisted names are read from (os.environ).
    worker_environ: Mapping[str, str] | None = None


@dataclass
class _Session:
    operation: OperationExecutionRequest
    binding: CursorExecutionBinding
    identity: LaneExecutionIdentity
    lease: WorkspaceLease | None = None
    projection: HostProjection | None = None
    # MO-02: what `prepare` placed, with the layering receipt (merged keys, discovery).
    materialization: ProjectionMaterialization | None = None
    digests: dict[str, str] = field(default_factory=dict)
    bridge: CursorLocalBridge | None = None
    agent_id: str | None = None
    run_id: str | None = None
    token_context: HookTokenContext | None = None
    signal_environment: dict[str, str] | None = field(default=None, repr=False)
    # FT-G4: staged texts of later turns (by instruction ref) and a hydrated continuation.
    turn_texts: dict[str, str] = field(default_factory=dict)
    handover: SessionHandover | None = None
    restored_snapshot: str | None = None
    # MP-09: the run each dispatch key produced in this process (the only reconcile anchor
    # the local SDK offers) and what the last reattach re-applied.
    sent_keys: dict[str, str] = field(default_factory=dict)
    rehydrated: tuple[str, ...] = ()
    force_next_send: bool = False
    # Cross-provider control (2026-11-05): the fork seed's reconstructed transcript, sent
    # as the prefix of the derived unit's first turn (the hydration turn), once.
    seed_hydration: str | None = None
    seed_applied: bool = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


FOLLOW_UP_TEXT = (
    "Before you stop: the mission declares outputs that are not written yet: {missing}. "
    "Write each declared output under outputs/ as described in .mission/context.md, "
    "then stop. Do not start other work."
)
TURNS_DIR = ".mission/turns"


def declared_outputs(
    operation: OperationExecutionRequest, *, mount_root: str = ""
) -> tuple[str, ...]:
    """The operation's declared outputs: its writable paths under `outputs/` (relative)."""

    declared: list[str] = []
    prefix = mount_root.rstrip("/")
    for path in operation.workspace.exclusive_write_paths:
        logical = path
        if prefix and logical.startswith(prefix + "/"):
            logical = logical[len(prefix) :]
        relative = logical.lstrip("/")
        if relative.startswith(OUTPUTS_DIR + "/"):
            declared.append(relative)
    return tuple(dict.fromkeys(declared))


def missing_outputs(root: Path, declared: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(path for path in declared if not (root / path).is_file())


def composite_cursor(run_id: str, offset: str) -> str:
    return f"{run_id}@{offset}"


def split_cursor(cursor: str | None, run_id: str) -> str | None:
    """The bridge offset a cursor names for `run_id`; another run's cursor resumes nothing."""

    if cursor is None:
        return None
    run, separator, offset = cursor.rpartition("@")
    if not separator:
        return cursor
    return offset if run == run_id and offset else None


class _StageOnly:
    """A sink without reads: snapshots are stored but cannot be restored from it."""

    def __init__(self, sink: LaneArtifactSink) -> None:
        self._sink = sink

    async def stage(self, *, request_scope: str, name: str, content: bytes, media_type: str) -> str:
        return await self._sink.stage(
            request_scope=request_scope, name=name, content=content, media_type=media_type
        )

    async def retrieve(self, durable_ref: str) -> bytes:
        raise LookupError(durable_ref)


class CursorLocalHarness(CursorNativeRunUsage):
    """`cursor_local` Session Lane over a `CursorBridgeLauncher` (the pinned SDK in production,
    a replaying fake in tests)."""

    def __init__(
        self,
        *,
        launcher: CursorBridgeLauncher,
        leaser: GitWorktreeLeaser,
        projections: ProjectionSource,
        hooks: HookCallbackService,
        artifacts: LaneArtifactSink,
        settings: CursorLocalSettings,
        inputs: DurableInputReader | None = None,
        describe: LaneDescribe = CURSOR_LOCAL_DESCRIBE,
        clock: Callable[[], datetime] = _utc_now,
        snapshot_store: snapshots.SnapshotArtifacts | None = None,
        outputs: LaneOutputCustody | None = None,
        mission_layer: MissionLayerService | None = None,
        secrets: ProcessSecretDelivery | None = None,
    ) -> None:
        if describe.lane_profile != PROFILE:
            raise ValueError("the Cursor local harness describes the cursor_local profile")
        self._launcher = launcher
        self._secrets = secrets
        # MO-12: a binding that pins an Environment Kit runs its mission layer before start.
        self._mission_layer = mission_layer
        # MP-20: declared outputs become workspace candidates of the operation when composed.
        self._outputs = outputs
        self._leaser = leaser
        self._projections = projections
        self._hooks = hooks
        self._artifacts = artifacts
        self._settings = settings
        self._inputs = inputs
        self._describe = describe
        self._clock = clock
        self._sessions: dict[str, _Session] = {}
        # Cross-provider control (2026-11-05): what `end_session` froze per execution (the
        # `cursor-snapshot:` ref, the base commit), read by `turn_points` at settlement.
        self._closed: dict[str, dict[str, str]] = {}
        # FT-G4: where snapshot bytes are staged and read back (fork, continuation).
        store = snapshot_store
        if store is None and hasattr(artifacts, "retrieve"):
            store = artifacts  # type: ignore[assignment]
        self._snapshots: snapshots.SnapshotArtifacts | None = store

    def describe(self) -> LaneDescribe:
        return self._describe

    # --- staging --------------------------------------------------------------------------------

    def stage(self, harness_execution_id: str, operation: OperationExecutionRequest) -> None:
        binding = CursorExecutionBinding.carried_by(operation)
        if binding is None or binding.lane_profile != PROFILE:
            raise ValueError("cursor_local runs only an operation with a cursor_local binding")
        current = self._sessions.get(harness_execution_id)
        if current is not None:
            if current.operation != operation:
                raise ValueError("harness execution is staged with another operation")
            return
        self._sessions[harness_execution_id] = _Session(
            operation=operation,
            binding=binding,
            identity=LaneExecutionIdentity.of(operation, PROFILE, 1),
        )

    def _session(self, request: HarnessRequest) -> _Session:
        session = self._sessions.get(request.harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {request.harness_execution_id} is not staged")
        if session.identity.attempt_no != request.generation:
            session.identity = LaneExecutionIdentity.of(
                session.operation, PROFILE, request.generation
            )
        return session

    # --- prepare ------------------------------------------------------------------------------

    def host_gate(self) -> HostGate | None:
        """The launcher's host gate (None for a launcher that spawns nothing, e.g. a replay)."""

        gate = getattr(self._launcher, "host_gate", None)
        return gate() if callable(gate) else None

    def _refuse_unsupported_host(self) -> None:
        gate = self.host_gate()
        if gate is not None and not gate.supported:
            raise LaneProjectionError(gate.code or LANE_UNSUPPORTED_OS, gate.message)

    async def prepare(self, request: PrepareRequest) -> PreparedSession:
        session = self._session(request)
        binding = session.binding
        # Refused before any lease exists: a Windows worker cannot spawn the bridge.
        self._refuse_unsupported_host()
        if binding.sandbox_enabled and not self._launcher.sandbox_supported():
            raise LaneProjectionError(
                UNSUPPORTED_BEHAVIOR, "the Cursor sandbox is not available on this worker host"
            )
        lease = await self._leaser.acquire(
            request_scope=session.identity.request_scope,
            lane_profile=PROFILE,
            harness_execution_id=UUID(request.harness_execution_id),
            generation=request.generation,
            run_id=request.run_id,
            attempt_no=request.attempt_no,
            repository=binding.workspace.repo_url or self._settings.default_repository,
            base_ref=binding.workspace.base_ref,
            policy=binding.workspace.policy or CURSOR_LOCAL_POLICY,
        )
        session.lease = lease
        root = Path(lease.path)
        # Cross-provider control (2026-11-05): a fork seeded at a cognition point restores
        # the source turn's snapshot into the fresh lease and stages the hydration prompt.
        if request.seed is not None:
            await self._restore_seed(session, root, request.seed)
        # A fork's (or continuation's) packet carries one `workspace` item: restore it into
        # the fresh lease first; the new packet and projection are placed over it.
        await self._restore_workspace_item(session, root)
        packet = await materialize_packet(
            root, session.operation, self._inputs, mount_root=self._settings.mount_root
        )
        # The pinned projection points at `.mission/context.md`; the packet is bound by its
        # own digests (recorded below), so the rule and hook digests stay the binding's.
        projection = await self._projections.project(
            session.operation, profile=PROFILE, packet_index=None
        )
        digests = projection_digests(projection)
        verify_projection(binding, digests)
        kernel = ProjectedFile(path=KERNEL_HOOK_PATH, content=kernel_hook_script(), mode=0o755)
        placed = projection.model_copy(update={"files": (*projection.files, kernel)})
        try:
            materialization = await asyncio.to_thread(
                materialize_projection, placed, root, policy=binding.materialization
            )
        except LayeringRefused as error:
            raise LaneProjectionError(MATERIALIZATION_CONFLICT, str(error)) from error
        except MaterializationRejected as error:
            raise LaneProjectionError(CAPABILITY_DRIFT, str(error)) from error
        written = [item.path for item in materialization.files]
        session.projection = projection
        session.materialization = materialization
        setup = await self._prepare_environment(session.binding, projection, root)
        session.digests = {
            **digests,
            "packet_digest": sha256_digest(packet),
            "materialization_digest": stable_json_digest(materialization),
            **(setup.digests() if setup is not None else {}),
        }
        return PreparedSession(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            workspace_ref=f"workspace_lease:{lease.lease_id}",
            projection_digests=session.digests,
            materialization_ref=sha256_digest(sorted(written)),
            discovery=discovery_expectation(
                PROFILE,
                materialization.layering,
                {item.path: item.digest for item in materialization.files},
            ),
        )

    async def _prepare_environment(
        self, binding: CursorExecutionBinding, projection: HostProjection, root: Path
    ) -> MissionLayerOutcome | None:
        """The bootstrap entrypoint: the kit's mission layer, run before the bridge starts with
        the environment the bridge gets (the Cursor binding carries no setup secrets)."""

        try:
            return await run_mission_layer(
                self._mission_layer,
                binding.setup_pin,
                root,
                environment=self._bridge_environment(projection),
            )
        except EnvironmentNotPrepared as error:
            raise LaneProjectionError(error.code, error.detail) from error

    async def _restore_workspace_item(self, session: _Session, root: Path) -> None:
        files = dict(
            await packet_files(
                session.operation, self._inputs, mount_root=self._settings.mount_root
            )
        )
        raw = files.get(INPUTS_MANIFEST_PATH)
        if raw is None:
            return
        try:
            workspace = json.loads(raw.decode("utf-8")).get("workspace")
        except (ValueError, AttributeError):
            return
        if not isinstance(workspace, dict) or not workspace.get("snapshot_ref"):
            return
        ref = str(workspace["snapshot_ref"])
        await self._restore_snapshot(
            session, root, ref, tuple(workspace.get("restore_paths") or ("/",))
        )

    async def _restore_seed(self, session: _Session, root: Path, seed: LaneSeedHead) -> None:
        """The seed head of a fork at a cognition point (`mc.lane_seed_head.v1`): restore the
        turn-close `cursor-snapshot:` into the lease (R2) when the seed names one, and read
        the reconstructed transcript the lane staged, sent as the first turn's prefix."""

        snapshot_ref = seed.native_artifacts.get(SEED_SNAPSHOT_REF)
        if snapshot_ref and snapshot_ref.startswith(snapshots.SNAPSHOT_REF_PREFIX):
            await self._restore_snapshot(session, root, snapshot_ref, ("/",))
        transcript_ref = seed.native_artifacts.get(SEED_TRANSCRIPT_REF)
        if transcript_ref:
            store = self._snapshots
            if store is None:
                raise LaneProjectionError(
                    snapshots.CHECKPOINT_INVALID, "no snapshot store is composed to read the seed"
                )
            try:
                session.seed_hydration = (await store.retrieve(transcript_ref)).decode("utf-8")
            except LookupError as error:
                raise LaneProjectionError(
                    snapshots.CHECKPOINT_INVALID, "the seed's transcript artifact is missing"
                ) from error
        elif seed.message:
            session.seed_hydration = f"[operator] {seed.message}\n"

    async def _restore_snapshot(
        self, session: _Session, root: Path, ref: str, restore_paths: tuple[str, ...]
    ) -> None:
        if session.restored_snapshot == ref:
            return
        if self._snapshots is None:
            raise LaneProjectionError(
                snapshots.CHECKPOINT_INVALID, "no snapshot store is composed to restore " + ref
            )
        manifest = await snapshots.load(ref, self._snapshots)
        restored = await snapshots.restore(
            manifest, root, self._snapshots, restore_paths=restore_paths
        )
        expected = {
            path: digest
            for path, digest in manifest.workspace_manifest().items()
            if path in restored or not path.startswith("/.mission/")
        }
        if any(restored.get(path) != digest for path, digest in expected.items()):
            raise LaneProjectionError(
                snapshots.CHECKPOINT_INVALID, "restored files differ from the snapshot digests"
            )
        session.restored_snapshot = ref

    def _spec(self, session: _Session, root: Path) -> LocalAgentSpec:
        binding = session.binding
        agents: tuple[dict[str, Any], ...] = ()
        if session.projection is not None:
            raw = session.projection.send_options.get("agents")
            items = raw if isinstance(raw, list | tuple) else ()
            agents = tuple(dict(item) for item in items if isinstance(item, dict))
        return LocalAgentSpec(
            model=binding.model_id,
            name=f"mc-{session.identity.run_key}-{session.identity.attempt_no}"[:100],
            cwd=str(root),
            mode=binding.mode,
            setting_sources=("project",),
            sandbox_enabled=binding.sandbox_enabled,
            agents=agents,
            disallowed_tools=binding.disallowed_tools,
        )

    # --- start, reattach ------------------------------------------------------------------------

    async def start(self, request: StartRequest) -> SessionHandle:
        session = self._session(request)
        if session.lease is None:
            raise ValueError("start requires a prepared workspace lease")
        await self._owned_lease(session, request)
        # Enforced where the lane spawns (the launcher refuses as well).
        self._refuse_unsupported_host()
        root = Path(session.lease.path)
        state_root = root / STATE_ROOT
        bridge = await self._launch_bridge(session, root)
        session.bridge = bridge
        try:
            agent_id = await bridge.create_agent(self._spec(session, root))
        except SandboxUnsupported as error:
            raise LaneProjectionError(UNSUPPORTED_BEHAVIOR, str(error)) from error
        session.agent_id = agent_id
        await self._write_hook_context(session, request, agent_id)
        return self._handle(request, agent_id, state_root)

    async def discover(self, session: SessionHandle) -> DiscoveryReport | None:
        """MO-34: the SDK's read-back of the agent and what its project source loads
        (`discovery.py`)."""

        state = self._sessions.get(session.harness_execution_id)
        agent_id = session.native_session_ref
        if state is None or state.bridge is None or state.lease is None or agent_id is None:
            return None
        root = Path(state.lease.path)
        readback = await state.bridge.agent_info(agent_id, cwd=str(root))
        return await asyncio.to_thread(setting_readback_report, readback, root)

    def _handle(self, request: HarnessRequest, agent_id: str, state_root: Path) -> SessionHandle:
        versions = self._launcher.versions
        details = {
            "cursor_sdk_version": versions.get("cursor_sdk", ""),
            "bridge_state_root": str(state_root),
            "hook_interpreter": str(Path(sys.executable).absolute()),
            "hook_interpreter_resolution": "bridge_inherited_path",
        }
        session = self._sessions.get(request.harness_execution_id)
        if session is not None:
            if session.rehydrated:
                details["rehydrated"] = ",".join(session.rehydrated)
            details.update(_network_details(session.binding))
        return SessionHandle(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            native_session_ref=agent_id,
            native_details=details,
        )

    def rehydration_receipt(self, harness_execution_id: str) -> tuple[str, ...]:
        """Which non-persisted options the last reattach re-applied (empty when nothing was)."""

        session = self._sessions.get(harness_execution_id)
        return () if session is None else session.rehydrated

    async def _write_hook_context(
        self, session: _Session, request: HarnessRequest, agent_id: str
    ) -> None:
        """Mint the task token once the native session exists (before any send, so before any
        hook can fire) and write it with the hook context into the lease."""

        assert session.lease is not None
        identity = session.identity
        root = Path(session.lease.path)
        context = HookTokenContext(
            request_scope=identity.request_scope,
            run_id=identity.run_key,
            attempt_no=identity.attempt_no,
            generation=request.generation,
            harness_execution_id=identity.harness_execution_id,
            lane_profile=PROFILE,
            execution_start=execution_start(
                session.operation, identity, request.generation, agent_id
            ),
            disallowed_tools=session.binding.disallowed_tools,
            workspace_root=str(root),
        )
        session.token_context = context
        await install_hook_context(
            self._hooks,
            context,
            root=root,
            callback_base_url=self._settings.callback_base_url,
            ttl=self._settings.token_ttl,
        )

    async def _owned_lease(self, session: _Session, request: HarnessRequest) -> WorkspaceLease:
        """Revalidate and renew the exact holder before touching a cached or detached bridge."""
        expected_scope = harness_scope(session.identity.request_scope, request.scope.actor_id)
        if (
            request.lane_profile != PROFILE
            or request.scope != expected_scope
            or request.binding_digest != session.binding.binding_digest
        ):
            raise NativeTurnLost("the workspace request does not match the staged session")
        lease = session.lease
        if lease is None:
            lease = await self._leaser.find(
                request_scope=session.identity.request_scope,
                lane_profile=PROFILE,
                harness_execution_id=UUID(request.harness_execution_id),
                generation=request.generation,
            )
        if (
            lease is None
            or lease.request_scope != session.identity.request_scope
            or lease.lane_profile != PROFILE
            or lease.harness_execution_id != UUID(request.harness_execution_id)
            or lease.generation != request.generation
            or lease.released
        ):
            raise NativeTurnLost("the workspace lease does not belong to this session generation")
        try:
            lease = await self._leaser.renew(lease)
        except (StaleWorkspaceLease, LookupError) as error:
            raise NativeTurnLost("the workspace lease of this session is no longer held") from error
        if not await asyncio.to_thread(Path(lease.path).is_dir):
            raise NativeTurnLost("the workspace lease of this session is gone")
        session.lease = lease
        return lease

    async def _bridge(self, session: _Session, request: HarnessRequest) -> CursorLocalBridge:
        """Connect to the same live run only while this session still owns its workspace."""
        lease = await self._owned_lease(session, request)
        if session.bridge is None:
            session.bridge = await self._launch_bridge(session, Path(lease.path))
        return session.bridge

    async def _launch_bridge(self, session: _Session, root: Path) -> CursorLocalBridge:
        """A bridge over the lease with the MO-04 allowlisted environment: the inherited
        platform names plus the variables the projected `.cursor/mcp.json` reads. The API key
        travels in agent options and contributes nothing here."""

        if session.projection is None:
            session.projection = await self._projections.project(
                session.operation, profile=PROFILE, packet_index=None
            )
        if session.signal_environment is None and self._secrets is not None:
            delivered = await self._secrets.environment(
                EnvironmentBinding(
                    kind="local_workspace",
                    host_profile=PROFILE,
                    in_environment_observation=session.binding.in_environment_observation,
                ),
                session.identity,
            )
            session.signal_environment = dict(delivered.values)
        return await self._launcher.launch(
            workspace=root,
            state_root=root / STATE_ROOT,
            environment={
                **self._bridge_environment(session.projection),
                **(session.signal_environment or {}),
            },
        )

    def _bridge_environment(self, projection: HostProjection) -> dict[str, str]:
        environ = self._settings.worker_environ
        environment = provider_child_environment(
            environ if environ is not None else os.environ,
            None,
            declared=projection.environment_names,
        )

        # Sealed hook commands stay unchanged; their inherited PATH resolves the selected
        # worker interpreter rather than a system python or a different virtualenv.
        directory = str(Path(sys.executable).absolute().parent)
        environment["PATH"] = directory + os.pathsep + environment.get("PATH", "")
        resolved = shutil.which("python", path=environment["PATH"])
        if resolved is None or Path(resolved).absolute() != Path(sys.executable).absolute():
            raise LaneProjectionError("UNSUPPORTED_BEHAVIOR", "hook interpreter resolution failed")
        return environment

    async def reattach(self, request: ReattachRequest) -> SessionHandle:
        session = self._session(request)
        if session.bridge is not None and session.agent_id == request.native_session_ref:
            await self._owned_lease(session, request)
            assert session.lease is not None
            return self._handle(
                request, request.native_session_ref, Path(session.lease.path) / STATE_ROOT
            )
        rehydrated = ["bridge"]
        if session.projection is None:
            session.projection = await self._projections.project(
                session.operation, profile=PROFILE, packet_index=None
            )
            rehydrated.append("projection")
        bridge = await self._bridge(session, request)
        assert session.lease is not None
        root = Path(session.lease.path)
        spec = self._spec(session, root)
        try:
            # Tools, disallowed tools, inline MCP servers and subagents are not persisted
            # across `Agent.resume`: the pinned spec is re-supplied on every resume
            # (cursor_sdk 1.0.37 `_async_client.AsyncClient.resume_agent(agent_id, options)`).
            agent_id = await bridge.resume_agent(request.native_session_ref, spec)
            if request.native_turn_ref is not None:
                await bridge.run_state(request.native_turn_ref)
        except RunNotFound as error:
            raise NativeTurnLost("the bridge store no longer knows this session") from error
        rehydrated.extend(_rehydrated_options(spec))
        session.rehydrated = tuple(dict.fromkeys((*session.rehydrated, *rehydrated)))
        session.agent_id = agent_id
        session.run_id = request.native_turn_ref
        return self._handle(request, agent_id, root / STATE_ROOT)

    # --- MP-06: reconcile an ambiguous create/send ------------------------------------------------

    async def reconcile_dispatch(
        self, record: DispatchRecord, *, session: SessionHandle | None
    ) -> DispatchLookup:
        """Reconcile remembered sends or one anchored successor; never assume a
        detached native run stopped when the worker process died."""

        harness_execution_id = record.idempotency_key.split(":", 1)[0]
        staged = self._sessions.get(harness_execution_id)
        if record.kind == "create":
            if staged is not None and staged.agent_id is not None and staged.bridge is not None:
                return DispatchLookup(outcome="found", native_ref=staged.agent_id)
            return DispatchLookup(
                outcome="unknown",
                detail="the local bridge store exposes no lookup of a create by key",
            )
        if staged is not None:
            remembered = staged.sent_keys.get(record.idempotency_key)
            if remembered is not None:
                return DispatchLookup(outcome="found", native_ref=remembered)
        if (
            staged is not None
            and isinstance(staged.bridge, SdkLocalBridge)
            and staged.agent_id
            and staged.lease
            and staged.run_id
        ):
            runs = await staged.bridge.list_runs(staged.agent_id, cwd=staged.lease.path)
            if staged.run_id in runs:
                newer = runs[: runs.index(staged.run_id)]
                acknowledged = set(staged.sent_keys.values()) | {staged.run_id}
                candidates = [ref for ref in newer if ref not in acknowledged]
                if len(candidates) == 1:
                    found = candidates[0]
                    staged.sent_keys[record.idempotency_key] = found
                    staged.run_id = found
                    staged.force_next_send = True
                    return DispatchLookup(outcome="found", native_ref=found)
        return DispatchLookup(
            outcome="unknown",
            detail=(
                "no unique native run follows the durable idempotency dispatch anchor; "
                "reconcile before resend"
            ),
        )

    # --- turn ---------------------------------------------------------------------------------

    async def send_turn(self, request: SendTurnRequest) -> TurnHandle:
        session = self._session(request)
        bridge = await self._bridge(session, request)
        agent_id = request.session.native_session_ref or session.agent_id
        if agent_id is None:
            raise ValueError("send_turn requires a started session")
        if request.instruction_ref is not None and (
            request.turn_no != 1
            or request.instruction_ref.startswith("continuation:")
            or request.instruction_ref in session.turn_texts
        ):
            if request.instruction_ref not in session.turn_texts:
                raise NativeTurnLost("required staged turn text is unavailable")
            text = session.turn_texts[request.instruction_ref]
        else:
            text = turn_text(session.operation)
        if session.seed_hydration is not None and not session.seed_applied:
            # The hydration turn of a fork seeded at a cognition point: the reconstructed
            # transcript (and the injected message) precede the unit's own instruction.
            text = f"{session.seed_hydration.rstrip()}\n\n{text}"
            session.seed_applied = True
        if request.instruction_ref in session.turn_texts:
            assert session.lease is not None and request.instruction_ref is not None
            name = sha256_digest(request.instruction_ref).removeprefix("sha256:")[:16]
            await asyncio.to_thread(
                write_files,
                Path(session.lease.path),
                (
                    ProjectedFile(
                        path=f"{TURNS_DIR}/{name}.md", content=text.encode("utf-8"), mode=0o444
                    ),
                ),
            )
        try:
            run_id = await bridge.send(
                agent_id,
                text,
                idempotency_key=request.idempotency_key,
                **(
                    {"force": session.force_next_send} if isinstance(bridge, SdkLocalBridge) else {}
                ),
            )
        except AgentBusy:
            return TurnHandle(session=request.session, turn_no=request.turn_no, status="busy")
        session.force_next_send = False
        session.run_id = run_id
        session.sent_keys[request.idempotency_key] = run_id
        return TurnHandle(session=request.session, turn_no=request.turn_no, native_turn_ref=run_id)

    def stage_turn(self, harness_execution_id: str, instruction_ref: str, text: str) -> None:
        """Stage later-turn text; send_turn writes it only after checking workspace ownership."""

        session = self._sessions.get(harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {harness_execution_id} is not staged")
        session.turn_texts[instruction_ref] = text

    async def observe(self, request: ObserveRequest) -> AsyncIterator[LaneFrame]:
        session = self._session(request)
        run_id = request.turn.native_turn_ref or session.run_id
        if run_id is None:
            raise NativeTurnLost("no native turn to observe")
        bridge = await self._bridge(session, request)
        after = split_cursor(request.after, run_id)
        cursor = request.after if after is not None else None
        try:
            async for event in bridge.observe(run_id, after_offset=after):
                frame = local_lane_frame(
                    event,
                    run_id=run_id,
                    harness_execution_id=request.harness_execution_id,
                    generation=request.generation,
                )
                frame = frame.model_copy(update={"cursor": composite_cursor(run_id, frame.cursor)})
                cursor = frame.cursor
                yield frame
                if frame.terminal:
                    return
            state = await bridge.run_state(run_id)
        except RunNotFound as error:
            raise NativeTurnLost("the bridge store no longer knows this run") from error
        if state.terminal:
            yield final_lane_frame(
                state,
                harness_execution_id=request.harness_execution_id,
                generation=request.generation,
                cursor=cursor,
            )

    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts:
        body = frame.body if isinstance(frame.body, dict) else {}
        facts = closing_facts(body)
        if facts.native_status != "finished":
            return facts
        session = self._sessions.get(turn.session.harness_execution_id)
        if session is None or session.lease is None:
            return facts
        # A native `finished` is never acceptance: declared outputs must be on disk.
        declared = declared_outputs(session.operation, mount_root=self._settings.mount_root)
        missing = missing_outputs(Path(session.lease.path), declared)
        return facts.model_copy(update={"missing_outputs": missing}) if missing else facts

    def final_text(self, turn: TurnHandle, frame: LaneFrame) -> str | None:
        """`FinalTextLane` (MP-20): the run's whole final text from the terminal frame body
        (the closing facts keep only a bounded excerpt of it)."""

        del turn
        body = frame.body if isinstance(frame.body, Mapping) else {}
        value = first(body, "result", "text")
        return value if isinstance(value, str) else None

    def resume_cursor(self, provider_key: str) -> str | None:
        offset = offset_of(provider_key)
        run = run_of(provider_key)
        if offset is None or run is None:
            return None
        return composite_cursor(run, offset)

    # --- FT-G4: missing_output_policy follow-up (Cursor `stop` hook) ---------------------------

    async def stop_followup(
        self, context: HookTokenContext, payload: Mapping[str, Any]
    ) -> str | None:
        """The follow-up a stopping agent gets when declared outputs are missing."""

        del payload
        if not self._settings.missing_output_follow_up:
            return None
        session = self._sessions.get(str(context.harness_execution_id))
        if session is None or context.workspace_root is None:
            return None
        declared = declared_outputs(session.operation, mount_root=self._settings.mount_root)
        missing = await asyncio.to_thread(missing_outputs, Path(context.workspace_root), declared)
        if not missing:
            return None
        return FOLLOW_UP_TEXT.format(missing=", ".join(missing))

    # --- FT-G4: continuation handover (a fresh agent in the same lease) -------------------------

    async def pending_handover(self, harness_execution_id: str) -> SessionHandover | None:
        session = self._sessions.get(harness_execution_id)
        return None if session is None else session.handover

    async def complete_handover(self, harness_execution_id: str, transfer_id: str) -> None:
        session = self._sessions.get(harness_execution_id)
        if session is not None and session.handover is not None:
            if session.handover.transfer_id == transfer_id:
                session.agent_id = session.handover.session.native_session_ref
                session.handover = None

    def live_session(self, agent_id: str) -> str | None:
        """The staged harness execution whose live agent is `agent_id` (a continuation's
        source), when its lease is on this worker."""

        for harness_execution_id, session in self._sessions.items():
            if session.agent_id == agent_id and session.lease is not None:
                return harness_execution_id
        return None

    def lease_path(self, harness_execution_id: str) -> str:
        lease = self._sessions[harness_execution_id].lease
        if lease is None:
            raise NativeTurnLost("the session holds no workspace lease")
        return lease.path

    async def open_bridge(self, harness_execution_id: str) -> CursorLocalBridge:
        session = self._sessions[harness_execution_id]
        return await self._bridge(
            session,
            HarnessRequest(
                scope=harness_scope(session.identity.request_scope),
                lane_profile=PROFILE,
                harness_execution_id=harness_execution_id,
                binding_digest=session.binding.binding_digest,
                idempotency_key=f"{harness_execution_id}:open_bridge",
                generation=session.identity.attempt_no,
            ),
        )

    def agent_spec(self, harness_execution_id: str) -> LocalAgentSpec:
        """The pinned agent options (tools are re-supplied on every create and resume)."""

        return self._spec(
            self._sessions[harness_execution_id], Path(self.lease_path(harness_execution_id))
        )

    def session_handle(self, harness_execution_id: str, agent_id: str) -> SessionHandle:
        session = self._sessions[harness_execution_id]
        root = Path(self.lease_path(harness_execution_id))
        return SessionHandle(
            lane_profile=PROFILE,
            harness_execution_id=harness_execution_id,
            generation=session.identity.attempt_no,
            native_session_ref=agent_id,
            native_details={
                "cursor_sdk_version": self._launcher.versions.get("cursor_sdk", ""),
                "bridge_state_root": str(root / STATE_ROOT),
                **_network_details(session.binding),
            },
        )

    def offer_handover(self, harness_execution_id: str, handover: SessionHandover) -> None:
        """A hydrated continuation: the next turn of this execution goes to its agent."""

        self._sessions[harness_execution_id].handover = handover

    @property
    def snapshot_store(self) -> snapshots.SnapshotArtifacts | None:
        return self._snapshots

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt:
        session = self._session(request)
        run_id = request.turn.native_turn_ref or session.run_id
        agent_id = request.turn.session.native_session_ref or session.agent_id
        if run_id is None or agent_id is None:
            return CancelReceipt(acknowledged=True, already_terminal=True, native_status="idle")
        try:
            bridge = await self._bridge(session, request)
        except NativeTurnLost:
            return CancelReceipt(acknowledged=False, native_status="unknown")
        already = False
        try:
            await bridge.cancel(run_id, agent_id=agent_id)
        except RunNotCancellable:
            already = True
        except RunNotFound:
            return CancelReceipt(acknowledged=False, native_status="unknown")
        try:
            state = await bridge.run_state(run_id)
        except RunNotFound:
            return CancelReceipt(acknowledged=True, already_terminal=already)
        return CancelReceipt(
            acknowledged=True, already_terminal=already, native_status=state.status
        )

    async def status(self, request: StatusRequest) -> ProviderStatus:
        session = self._session(request)
        run_id = (request.turn.native_turn_ref if request.turn else None) or session.run_id
        if run_id is None:
            return ProviderStatus(status="idle", terminal=False, idle=True)
        bridge = await self._bridge(session, request)
        try:
            state = await bridge.run_state(run_id)
        except RunNotFound as error:
            raise NativeTurnLost("the bridge store no longer knows this run") from error
        usage = (
            UsageReport(
                disposition="estimated",
                input_tokens=state.usage.get("input_tokens", 0),
                output_tokens=state.usage.get("output_tokens", 0),
                total_tokens=state.usage.get("total_tokens", 0),
            )
            if state.usage
            else None
        )
        return ProviderStatus(
            status=state.status, terminal=state.terminal, idle=state.terminal, usage=usage
        )

    async def usage(self, request: UsageRequest) -> UsageReport:
        """Tokens settle per turn; cost upgrades only when the provider reports it
        (`feature_unavailable` raises, and the closing usage stays `estimated`)."""

        session = self._session(request)
        agent_id = request.session.native_session_ref or session.agent_id
        if agent_id is None:
            return UsageReport(disposition="unknown")
        bridge = await self._bridge(session, request)
        try:
            if isinstance(bridge, SdkLocalBridge):
                usage = await bridge.usage(
                    agent_id, run_id=request.turn.native_turn_ref if request.turn else None
                )
            elif request.turn is not None and request.turn.native_turn_ref:
                state = await bridge.run_state(request.turn.native_turn_ref)
                tokens = state.usage
                if not tokens:
                    return UsageReport(disposition="unknown")
                return UsageReport(
                    disposition="settled",
                    cache_read_tokens=tokens.get("cache_read_tokens"),
                    cache_write_tokens=tokens.get("cache_write_tokens"),
                    **{
                        key: tokens.get(key, 0)
                        for key in ("input_tokens", "output_tokens", "total_tokens")
                    },
                )
            else:
                usage = await bridge.usage(agent_id)
        except FeatureUnavailable:
            raise
        if not usage.known:
            return UsageReport(disposition="unknown")
        return UsageReport(
            disposition="settled",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cost_micros_usd=usage.cost_micros_usd,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
        )

    # --- snapshot, end ------------------------------------------------------------------------

    def billing_reader(self, harness_execution_id: str) -> Any:
        """Exact billing UUID reader for an existing connection, never creates cognition."""
        from mission_control.adapters.cursor.cost import LocalBillingReader

        session = self._sessions.get(harness_execution_id)
        if session is None or not isinstance(session.bridge, SdkLocalBridge):
            return None
        return LocalBillingReader(session.bridge.client, session.bridge.api_key)

    def _excluded(self, session: _Session) -> tuple[str, ...]:
        projected = session.projection.paths() if session.projection is not None else ()
        return tuple(projected)

    async def conversation_export(self, harness_execution_id: str) -> bytes:
        from mission_control.adapters.cursor.conversation import conversation_export

        session = self._sessions[harness_execution_id]
        value: Any = None
        if isinstance(session.bridge, SdkLocalBridge) and session.run_id:
            with contextlib.suppress(FeatureUnavailable, RunNotFound):
                value = await session.bridge.conversation(session.run_id)
        secrets = tuple((session.signal_environment or {}).values())
        if isinstance(session.bridge, SdkLocalBridge):
            secrets += (session.bridge.api_key,)
        return conversation_export(
            value,
            session_ref=session.agent_id or "unknown",
            run_ref=session.run_id,
            source="sdk.run.conversation",
            secrets=secrets,
        )

    async def _freeze(
        self, session: _Session, request: HarnessRequest, reason: str
    ) -> snapshots.FrozenSnapshot:
        """`mc.cursor_snapshot.v1` of the lease: patch, untracked files, packet files, refs."""

        assert session.lease is not None
        lease = session.lease
        from mission_control.adapters.cursor.conversation import CONVERSATION_PATH

        export = await self.conversation_export(request.harness_execution_id)
        await asyncio.to_thread(
            write_files,
            Path(lease.path),
            (ProjectedFile(path=CONVERSATION_PATH, content=export, mode=0o444),),
        )
        patch = await self._leaser.capture_patch(lease, exclude=self._excluded(session))
        store = self._snapshots or _StageOnly(self._artifacts)
        return await snapshots.freeze(
            root=Path(lease.path),
            patch=patch,
            artifacts=store,
            request_scope=session.identity.request_scope,
            name=f"cursor-local/{request.harness_execution_id}/{request.generation}",
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            reason=reason,
            base_commit=lease.base_commit,
            base_ref=lease.base_ref,
            repository=lease.repository,
            native={"agent_id": session.agent_id or "", "run_id": session.run_id or ""},
        )

    async def snapshot(self, request: SnapshotRequest) -> SnapshotManifest:
        """Emulated: a frozen `mc.cursor_snapshot.v1` named by `cursor-snapshot:<ref>`."""

        session = self._session(request)
        if session.lease is None:
            raise ValueError("no leased workspace to snapshot")
        await self._owned_lease(session, request)
        frozen = await self._freeze(session, request, request.reason)
        refs = snapshots.manifest_refs(frozen)
        return SnapshotManifest(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            kind="git_patch",
            refs=refs,
            emulated=True,
            digest=sha256_digest(list(refs)),
        )

    async def end_session(self, request: EndSessionRequest) -> CleanupReceipt:
        session = self._session(request)
        if session.lease is None:
            session.lease = await self._leaser.find(
                request_scope=session.identity.request_scope,
                lane_profile=PROFILE,
                harness_execution_id=UUID(request.harness_execution_id),
                generation=request.generation,
            )
        if session.lease is None or session.lease.released:
            self._sessions.pop(request.harness_execution_id, None)
            return CleanupReceipt(released=False)
        await self._owned_lease(session, request)
        await asyncio.to_thread(restore_repository_files, Path(session.lease.path))
        channels = session.operation.workspace.output_channels
        collected: list[
            tuple[Literal["artifact_upload", "branch_commit", "provider_artifacts"], str, bytes]
        ] = []
        for channel in channels or ("artifact_upload",):
            files = (
                await self._leaser.committed_outputs(session.lease)
                if channel == "branch_commit"
                else await self._leaser.outputs(session.lease)
            )
            collected.extend((channel, path, content) for path, content in files)
        frozen = await self._freeze(session, request, f"end_session:{request.reason}")
        patch_ref = frozen.manifest.patch.ref
        outputs: list[str] = [frozen.snapshot_ref]
        for channel, path, content in collected:
            registered = (
                await self._outputs.register(
                    session.operation,
                    path,
                    content,
                    mount_root=self._settings.mount_root,
                    **({"channel": channel} if channels is not None else {}),
                )
                if self._outputs is not None
                else None
            )
            outputs.append(
                registered
                or await self._artifacts.stage(
                    request_scope=session.identity.request_scope,
                    name=(
                        f"cursor-local/{request.harness_execution_id}/{channel}/{path}"
                        if channels is not None
                        else f"cursor-local/{request.harness_execution_id}/{path}"
                    ),
                    content=content,
                    media_type="application/octet-stream",
                )
            )
        if session.bridge is not None:
            if session.agent_id is not None:
                try:
                    await session.bridge.close_agent(session.agent_id)
                finally:
                    await session.bridge.aclose()
            else:
                await session.bridge.aclose()
            session.bridge = None
        # Only real detached SDK launchers own a discovery file; replay bridges need none.
        if isinstance(self._launcher, SdkBridgeLauncher):
            from mission_control.adapters.cursor.bridge_spawn import shutdown_bridge

            await shutdown_bridge(
                Path(session.lease.path) / STATE_ROOT, workspace=Path(session.lease.path)
            )
        if session.token_context is not None:
            await self._hooks.revoke(session.token_context)
        # The lease is released only after the patch is stored (SPEC-07 section 5.3).
        await self._leaser.release(
            session.lease,
            patch_artifact_ref=patch_ref,
            snapshot_ref=frozen.snapshot_ref,
            exclude=self._excluded(session),
        )
        self._closed[request.harness_execution_id] = {
            "snapshot_ref": frozen.snapshot_ref,
            "repository": session.lease.repository or "",
            "base_commit": session.lease.base_commit,
        }
        self._sessions.pop(request.harness_execution_id, None)
        return CleanupReceipt(
            released=True, artifact_refs=(patch_ref, *outputs), patch_ref=patch_ref
        )

    async def cleanup_workspace(
        self, *, request_scope: str, harness_execution_id: str, generation: int
    ) -> CleanupOutcome:
        """MO-05 `WorkspaceLeasingLane`: remove the worktree this generation released."""

        return await self._leaser.cleanup(
            request_scope=request_scope,
            lane_profile=PROFILE,
            harness_execution_id=UUID(harness_execution_id),
            generation=generation,
        )

    # --- cross-provider control (2026-11-05): cognition points -------------------------------

    def turn_points(self, request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
        """`PointCollectingLane`: one `session_cursor` point per step of the run keyed by the
        bridge offset, plus the turn-close `workspace_snapshot` (`cursor-snapshot:` ref)."""

        closed = self._closed.get(request.harness_execution_id)
        if closed is not None and request.terminal:
            self._closed.pop(request.harness_execution_id, None)
        return cursor_turn_points(request, closed=closed)


def _network_details(binding: CursorExecutionBinding) -> dict[str, str]:
    network = network_projection(binding)
    return network.native_details() if network is not None else {}


def _rehydrated_options(spec: LocalAgentSpec) -> tuple[str, ...]:
    """The non-persisted option groups a resume re-supplied (names only, never values)."""

    applied = ["setting_sources", "mode", "sandbox"]
    if spec.agents:
        applied.append("agents")
    if spec.disallowed_tools:
        applied.append("disallowed_tools")
    if spec.mcp_servers:
        applied.append("mcp_servers")
    return tuple(applied)


__all__ = [
    "FOLLOW_UP_TEXT",
    "PROFILE",
    "CursorLocalHarness",
    "CursorLocalSettings",
    "LaneArtifactSink",
    "composite_cursor",
    "declared_outputs",
    "missing_outputs",
    "split_cursor",
]
