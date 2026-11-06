"""The `codex` Lane Profile: Codex app-server threads, turns and items on the worker (MP-08).

One Session Turn of a bound operation, driven by `lane.turn` (SPEC-01 "Codex local"):

- `prepare` leases a workspace at the binding's base ref under its `workspace_policy` (the
  MP-04 allocator; MO-05), materializes the Context Packet
  (`.mission/`, `inputs/`, `outputs/`), writes the pinned Host Projection through MP-03's
  `materialize_projection` (digest-checked against `binding.materialization_digest`:
  `CAPABILITY_DRIFT` otherwise; layered over the repository under the binding's
  `materialization` policy, MO-02: a refused conflict is `MATERIALIZATION_CONFLICT`, and no
  `AGENTS.md` is written) and prepares `CODEX_HOME`: isolated per session, with the
  project trust the projection requires (`report.requires_trust`) and the hash trust of
  every handler of the placed `.codex/hooks.json` (`hook_trust`; SPEC-02 §5, Q-X2) written to
  its `config.toml`, or the owner's home with the project trust passed as a `-c` override (no
  projected hooks then: 0.162.1 honours hook trust only from the home's `config.toml`);
  with Kernel Hooks projected it writes `.mission/hooks/kernel.py` (G11);
- `start` launches `codex app-server` with the MO-04 allowlisted child environment
  (`launcher.child_environment` over the admitted auth route and the variables the projected
  MCP servers read, plus the values the Secret Broker delivers for the binding's declared
  secrets, MO-11) and the binding's resolved network policy as the workspace-write sandbox's
  `network_access` `-c` override (MO-15; recorded with the thread as the lane enforces it),
  runs `initialize` /
  `initialized`, checks with `hooks/list` that Codex reports every placed hook trusted
  (`HOOK_TRUST_UNVERIFIED` otherwise; on every launch), then `thread/start` (cwd = the lease,
  approvals routed to `user`, the binding's sandbox and approval policy, the mission overlay
  as `developerInstructions`), records the thread id and, with Kernel Hooks, mints the hook
  task token and writes it with `.mission/hooks/context.json` exactly as `cursor_local` does,
  before any send;
- `send_turn` serializes new-turn admission: it reads the thread status and sends
  `turn/start` only on an idle thread (a `turn/start` on an active thread would steer it), with
  `clientUserMessageId` = the dispatch idempotency key; an active thread answers `busy`
  (`wait_then_send`); a limit refusal raises `ProviderCapacityLimited`;
- `steer` (`SteeringLane`) sends `turn/steer` with `expectedTurnId` = the exact active turn; a
  turn that completed first, a server refusal or a mismatching reply is a typed `stale_target`;
- `cancel_turn` sends `turn/interrupt` and observes the terminal `turn/completed`
  (`interrupted`) before it reports;
- `observe` maps every notification and server request after the cursor to frames (MP-13
  mapping; unknown methods stay `unknown`). A turn started on the live connection is observed
  from just before its `turn/start` (never the whole connection buffer again); a cursor from
  another app-server launch, or none, resynchronizes from `thread/read` history (items and the
  terminal turn, paged by history cursors) before going live; a turn already terminal whose
  completion the cursor has passed resynchronizes too (it never waits on a finished turn);
- `reconcile_dispatch` (`DispatchReconcilingLane`) answers a journaled send from the live
  session or from `thread/read` history by `UserMessageThreadItem.clientId`; an idle thread
  without the key is the authoritative `not_received`, anything less is `unknown`;
- `reattach` relaunches the app-server over the same lease and `thread/resume` (emulated);
  every launch recovers the approval correlations earlier connections held (MP-11);
- `compact` (MP-12 `CompactingLane`) runs `thread/compact/start` on an idle thread under the
  admission lock and waits (bounded) for `thread/compacted` / a `contextCompaction` item;
  `context_occupancy` (`ContextOccupancyLane`) reads the last `thread/tokenUsage/updated`
  against its `modelContextWindow` (never the cumulative total; `unknown` without a window
  or after a compaction until the next usage update);
- `end_session` restores the repository files layering merged, stores the patch and
  `outputs/`, terminates the app-server, revokes the hook token and releases the lease only
  after the patch is stored; `cleanup_workspace` removes the released worktree once the
  operation workflow settled the unit (MO-05).

Approvals: every approval-class server request is served by `CodexApprovals` over MP-11's
`ApprovalBroker` in its own task (bound and persisted first, then the tool gate, then a
bounded wait), so the background event pump never blocks on a human; refused request kinds
get a JSON-RPC error. `pause` holds approval answers at the tool gate (`pause_at_tool_gate`)
after their binding is persisted. Without a broker the lane fails closed.

Cross-provider control (2026-11-05): `turn_points` (`PointCollectingLane`) folds a settled
turn's frames into `thread_item` points (`cognition_points.py`); `thread_history` and
`fork_thread` are the provider ports `time_travel.CodexTimeTravel` reads R3 state and seeds
forks through (`thread/read`, `thread/fork` with `lastTurnId` on a thread this process holds);
`prepare`/`start` honour `request.seed` (`LaneSeedHead`): a forked thread is `thread/resume`d
(its rollout copied into the isolated `CODEX_HOME` when the seed carries it), otherwise a
fresh thread starts and the staged hydration preamble (reconstructed steps plus the injected
message) travels ahead of the first turn's text. The source thread is never written.

`describe().qualified` stays False: only the owner-run drill in
docs/qualification/lanes/codex/README.md can change that.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from mission_control.adapters.codex import cognition_points as points_fold
from mission_control.adapters.codex import frames as framing
from mission_control.adapters.codex.approvals import (
    DEFAULT_APPROVAL_DEADLINE,
    DEFAULT_APPROVAL_REVIEWERS,
    DEFAULT_APPROVAL_WAIT_SECONDS,
    ApprovalContext,
    CodexApprovals,
    fail_closed_response,
)
from mission_control.adapters.codex.auth_preflight import require_auth_home
from mission_control.adapters.codex.discovery import app_server_report
from mission_control.adapters.codex.hook_trust import (
    HOOK_TRUST_UNVERIFIED,
    HOOKS_FILE,
    HookTrustRecord,
    HookTrustUnverified,
    hook_trust_records,
    hook_trust_toml,
    verify_listed_trust,
)
from mission_control.adapters.codex.launcher import (
    AppServerLauncher,
    LaunchedAppServer,
    LaunchSpec,
    child_environment,
    shell_environment_overrides,
)
from mission_control.adapters.codex.protocol import (
    APPROVAL_REQUEST_METHODS,
    CLIENT_NAME,
    ERR_REFUSED_BY_MISSION_CONTROL,
    M_ACCOUNT_LOGIN_START,
    M_ACCOUNT_READ,
    M_CONFIG_READ,
    M_HOOKS_LIST,
    M_INITIALIZE,
    M_INITIALIZED,
    M_SKILLS_LIST,
    M_THREAD_COMPACT_START,
    M_THREAD_FORK,
    M_THREAD_READ,
    M_THREAD_RESUME,
    M_THREAD_START,
    M_TURN_INTERRUPT,
    M_TURN_START,
    M_TURN_STEER,
    N_ERROR,
    N_ITEM_COMPLETED,
    N_THREAD_COMPACTED,
    N_THREAD_STATUS_CHANGED,
    N_TURN_COMPLETED,
    N_TURN_STARTED,
    N_USAGE_UPDATED,
    PINNED_CODEX_CLI_VERSION,
    PINNED_SCHEMA_SHA256,
    TERMINAL_TURN_STATUSES,
    ApiKeyLoginParams,
    ApiKeyLoginResponse,
    AskForApproval,
    ClientInfo,
    ErrorNotification,
    InitializeCapabilities,
    InitializeParams,
    InitializeResponse,
    ItemNotification,
    TextUserInput,
    Thread,
    ThreadCompactStartParams,
    ThreadForkParams,
    ThreadForkResponse,
    ThreadReadParams,
    ThreadReadResponse,
    ThreadResumeParams,
    ThreadResumeResponse,
    ThreadStartParams,
    ThreadStartResponse,
    ThreadStatus,
    ThreadTokenUsage,
    TokenUsageNotification,
    Turn,
    TurnInterruptParams,
    TurnNotification,
    TurnStartParams,
    TurnStartResponse,
    TurnSteerParams,
    TurnSteerResponse,
    codex_local_describe,
    limit_signal_from_rpc_error,
)
from mission_control.adapters.codex.time_travel import (
    A_DERIVED_THREAD,
    A_HYDRATION_REF,
    A_ROLLOUT_REF,
    A_ROLLOUT_RELPATH,
    A_SOURCE_THREAD,
    ForkedThread,
)
from mission_control.adapters.codex.transport import (
    AppServerConnection,
    AppServerError,
    CursorExpired,
    InboundEvent,
    ResponseLost,
    TransportClosed,
)
from mission_control.adapters.codex.usage import CodexNativeRunUsage
from mission_control.adapters.cursor.hooks_callback import install_hook_context, kernel_hook_script
from mission_control.application.agentic_components.layering import (
    MATERIALIZATION_CONFLICT,
    LayeringRefused,
    restore_repository_files,
)
from mission_control.application.agentic_components.materialization import (
    MaterializationRejected,
    ProjectionMaterialization,
    materialize_projection,
    required_executables,
)
from mission_control.application.agentic_components.placement import (
    CAPABILITY_DRIFT,
    HOOK_CONTEXT_PATH,
    KERNEL_HOOK_PATH,
    OUTPUTS_DIR,
    TOKEN_PATH,
    UNSUPPORTED_BEHAVIOR,
    DurableInputReader,
    LaneProjectionError,
    ProjectionSource,
    RowsResolver,
    materialize_packet,
    safe_relative,
    turn_text,
    write_files,
)
from mission_control.application.context.lane_continuation import continuation_instruction_ref
from mission_control.application.context.lane_support import (
    CompactionReceipt,
    CompactionRequest,
)
from mission_control.application.environments.discovery import discovery_expectation
from mission_control.application.environments.mission_layer import (
    EnvironmentNotPrepared,
    MissionLayerOutcome,
    MissionLayerService,
    prepare_lane_environment,
)
from mission_control.application.environments.network import (
    LaneNetworkContext,
    NetworkProjection,
    project_network_policy,
)
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.auth_admission import AuthAdmission
from mission_control.application.execution.child_environment import ChildEnvironmentBuilder
from mission_control.application.execution.harness.controls import SessionHandover
from mission_control.application.execution.harness.dispatch import (
    DispatchLookup,
    DispatchRecord,
    ProviderCapacityLimited,
    SteerResult,
)
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
from mission_control.application.frames.kinds import UNKNOWN_KINDS, UnknownKindCounter
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from mission_control.domain.agentic_components.projection import (
    KERNEL_HOOK_SCRIPT,
    HostProjection,
    ProjectedFile,
)
from mission_control.domain.authoring.canonical import sha256_digest, stable_json_digest
from mission_control.domain.context.pressure import ContextOccupancy
from mission_control.domain.execution.bindings import (
    CodexAppServerOptions,
    ProviderExecutionBinding,
    WorkspacePolicyPin,
    WorkspaceSnapshot,
)
from mission_control.domain.execution.cognition_points import CognitionPointObservation
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.discovery import DiscoveryReport
from mission_control.domain.execution.lane_turns import CleanupOutcome, ClosingFacts
from mission_control.domain.execution.lanes import (
    CancelReceipt,
    CancelTurnRequest,
    CleanupReceipt,
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

_LOGGER = logging.getLogger(__name__)
PROFILE = "codex"
STATE_DIR = ".mission/state/codex"
CODEX_HOME_DIR = f"{STATE_DIR}/codex-home"
TURNS_DIR = ".mission/turns"
DEFAULT_HOOK_CALLBACK_BASE_URL = "http://127.0.0.1:47555"
CodexHomeMode = Literal["isolated", "owner"]


# --- ports --------------------------------------------------------------------------------------


class WorkspaceLeaser(Protocol):
    """What the lane needs from a workspace leaser (`adapters/cursor/workspace.GitWorktreeLeaser`
    in production; a temporary-directory fake in tests)."""

    async def acquire(
        self,
        *,
        request_scope: str,
        lane_profile: str,
        harness_execution_id: UUID,
        generation: int,
        run_id: str,
        attempt_no: int,
        repository: str | None,
        base_ref: str,
        policy: WorkspacePolicyPin,
    ) -> WorkspaceLease: ...

    async def find(
        self,
        *,
        request_scope: str,
        lane_profile: str,
        harness_execution_id: UUID,
        generation: int,
    ) -> WorkspaceLease | None: ...

    async def capture_patch(self, lease: WorkspaceLease, *, exclude: Sequence[str] = ()) -> Any: ...

    async def outputs(self, lease: WorkspaceLease) -> list[tuple[str, bytes]]: ...

    async def release(
        self,
        lease: WorkspaceLease,
        *,
        patch_artifact_ref: str | None,
        snapshot_ref: str | None = None,
        exclude: Sequence[str] = (),
    ) -> WorkspaceLease: ...

    async def cleanup(
        self,
        *,
        request_scope: str,
        lane_profile: str,
        harness_execution_id: UUID,
        generation: int,
    ) -> CleanupOutcome: ...


class ArtifactSink(Protocol):
    async def stage(
        self, *, request_scope: str, name: str, content: bytes, media_type: str
    ) -> str: ...


class AuthAdmissionSource(Protocol):
    """Admits the binding's auth profile for the `codex` profile (MP-05) before any launch."""

    async def admit(self, binding: ProviderExecutionBinding) -> AuthAdmission: ...


@dataclass(frozen=True)
class CodexLocalSettings:
    lease_root: Path
    codex_home_mode: CodexHomeMode = "isolated"
    # Required for `owner` mode: where the owner's `codex login` lives (never copied).
    owner_codex_home: Path | None = None
    default_repository: str | None = None
    mount_root: str = ""
    # MP-03: the projection's hook interpreters / stdio MCP launchers must be on PATH (checked
    # only when the harness has a `rows` resolver to derive them from).
    require_executables: bool = True
    # How long `cancel_turn` waits for the terminal `turn/completed` after `turn/interrupt`.
    interrupt_settle_s: float = 10.0
    status_timeout_s: float = 30.0
    # How long `compact` waits for `thread/compacted` / a `contextCompaction` item.
    compaction_timeout_s: float = 120.0
    # MP-11: the approval task's informational deadline, the bounded native wait (keep it
    # below the `lane.turn` segment budget) and the reviewers of codex approval tasks.
    approval_deadline: timedelta | None = DEFAULT_APPROVAL_DEADLINE
    approval_wait_seconds: float = DEFAULT_APPROVAL_WAIT_SECONDS
    approval_reviewers: tuple[str, ...] = DEFAULT_APPROVAL_REVIEWERS
    client_version: str = "0.1.0"
    # G11: the worker's loopback hook callback listener and the hook task token lifetime.
    hook_callback_base_url: str = DEFAULT_HOOK_CALLBACK_BASE_URL
    hook_token_ttl: timedelta = timedelta(hours=4)
    # The worker environment the child's allow-listed names are read from (os.environ).
    worker_environ: Mapping[str, str] | None = None
    cursor_key_memory: int = 50_000


@dataclass
class _TurnState:
    turn_id: str
    status: str = "inProgress"
    epoch: str = ""
    # The connection epoch this turn was started on (live `turn/start` or `turn/started`);
    # history absorbed from a relaunch never sets it, so an observer resynchronizes first.
    started_epoch: str = ""
    # The connection's last sequence when `turn/start` was sent: the turn's own events follow.
    start_seq: int = 0
    # Where this connection delivered the turn's `turn/completed` (epoch, seq), if it did.
    completed_at: tuple[str, int] | None = None
    last_agent_text: str | None = None
    usage: ThreadTokenUsage | None = None
    last_error: str | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_TURN_STATUSES


@dataclass
class _PendingHandover:
    """MP-12: a fresh thread on a fresh app-server, hydrated for a continuation and not yet
    adopted (the source connection keeps running until its turn boundary)."""

    handover: SessionHandover
    launched: LaunchedAppServer
    thread_id: str
    model: str | None


@dataclass
class _Session:
    operation: OperationExecutionRequest
    binding: ProviderExecutionBinding
    options: CodexAppServerOptions
    identity: LaneExecutionIdentity
    lease: WorkspaceLease | None = None
    codex_home: Path | None = None
    config_overrides: tuple[str, ...] = ()
    projection_paths: tuple[str, ...] = ()
    # SPEC-02 §5: the trust records of the projected `.codex/hooks.json`, and whether it
    # runs Kernel Hooks (`kernel.py`, `context.json` and the task token are then in the lease).
    hook_trust: tuple[HookTrustRecord, ...] = ()
    kernel_hooks: bool = False
    token_context: HookTokenContext | None = None
    # MO-04: the variables the projected MCP servers read (None until projected here).
    environment_names: tuple[str, ...] | None = None
    # MO-02: the mission overlay `thread/start` sends as `developerInstructions`, and what
    # `prepare` placed with the layering receipt (merged keys, discovery).
    developer_instructions: str | None = None
    materialization: ProjectionMaterialization | None = None
    # MO-11: the values the Secret Broker delivered (resolved once; a relaunch reuses them).
    delivered: dict[str, str] | None = field(default=None, repr=False)
    # MO-15: the binding's network policy as this lane projects it (None: none declared).
    network: NetworkProjection | None = None
    digests: dict[str, str] = field(default_factory=dict)
    admission: AuthAdmission | None = None
    launched: LaunchedAppServer | None = None
    pump: asyncio.Task[None] | None = None
    thread_id: str | None = None
    thread_status: str = "notLoaded"
    model: str | None = None
    turns: dict[str, _TurnState] = field(default_factory=dict)
    active_turn: str | None = None
    sent: dict[str, str] = field(default_factory=dict)
    turn_texts: dict[str, str] = field(default_factory=dict)
    admission_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # `pause_at_tool_gate`: set while approval answers may go out; cleared while held.
    unheld: asyncio.Event = field(default_factory=asyncio.Event)
    held_waiters: int = 0
    approval_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    # MP-12 continuation: the hydrated target awaiting adoption, and the cached `prepare`.
    pending: _PendingHandover | None = None
    prepared: PreparedSession | None = None
    connection_lost: str | None = None
    # The last event sequence the pump absorbed (turn admission waits for it to catch up).
    absorbed_seq: int = 0
    # Per connection epoch: every event up to this sequence was taken by an observer.
    observed_through: dict[str, int] = field(default_factory=dict)
    # The execution's binding digest as `LaneTurnService` records it (`binding_digest` of
    # every harness request = `harness_execution.intended_binding_digest`): the approval
    # policy digest `PostgresApprovalContextProbe` revalidates against.
    binding_digest: str | None = None
    # MP-12: a session-wide event clock orders the last usage update against compactions.
    event_clock: int = 0
    last_usage: ThreadTokenUsage | None = None
    usage_clock: int = 0
    compaction_clock: int = 0
    usage_tracker: framing.TurnUsageTracker = field(default_factory=framing.TurnUsageTracker)
    # Cross-provider control: the seed head a forked unit's first session continues from,
    # the hydration preamble its first turn carries (consumed once), the restore level the
    # start reached (`R3`: the forked thread resumed; `R1`: a fresh thread with the
    # preamble) and the source thread it was forked from.
    seed: LaneSeedHead | None = None
    seed_prefix: str | None = None
    seed_restore: str | None = None
    forked_from: str | None = None

    def __post_init__(self) -> None:
        self.unheld.set()

    @property
    def hold_approvals(self) -> bool:
        return not self.unheld.is_set()

    @property
    def connection(self) -> AppServerConnection | None:
        if self.launched is None or self.launched.connection.closed:
            return None
        return self.launched.connection

    @property
    def root(self) -> Path:
        if self.lease is None:
            raise NativeTurnLost("the session holds no workspace lease")
        return Path(self.lease.path)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _write_private(target: Path, content: bytes) -> None:
    """A rollout copy under the session's own CODEX_HOME (owner-only, never a secret file)."""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    with suppress(OSError):
        target.chmod(0o600)


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _developer_instructions(send_options: Mapping[str, object]) -> str | None:
    """The projected mission overlay (SPEC-02 §4: inline on `thread/start`, never a file)."""

    value = send_options.get("developer_instructions")
    return value if isinstance(value, str) else None


def trust_config_toml(workspace: Path, hooks: Sequence[HookTrustRecord] = ()) -> str:
    """The `[projects."<path>"] trust_level = "trusted"` table of a CODEX_HOME `config.toml`
    (learn.chatgpt.com/docs/config-file/config-advanced: project `.codex/` layers load only for
    trusted projects) and the `[hooks.state]` trust of the projected hooks. The path is the
    host's own form: codex-cli 0.162.1 on Windows does not trust a forward-slash path."""

    return (
        "# Generated by Mission Control for one codex session. Do not edit.\n"
        f"[projects.{_toml_string(str(workspace))}]\n"
        'trust_level = "trusted"\n'
    ) + hook_trust_toml(hooks)


def trust_override(workspace: Path) -> str:
    """The same trust as a documented `-c key=value` dotted override of the owner's config."""

    return f"projects.{_toml_string(str(workspace))}.trust_level={_toml_string('trusted')}"


def network_projection(
    binding: ProviderExecutionBinding, options: CodexAppServerOptions
) -> NetworkProjection | None:
    """MO-15: the binding's resolved network policy as the bound sandbox enforces it."""

    policy = binding.environment.network
    if policy is None:
        return None
    return project_network_policy(
        PROFILE, policy, LaneNetworkContext(codex_sandbox=options.sandbox_mode)
    )


def network_overrides(projection: NetworkProjection | None) -> tuple[str, ...]:
    """The projection's sandbox settings as `-c key=value` overrides (TOML values)."""

    if projection is None:
        return ()
    return tuple(f"{key}={json.dumps(value)}" for key, value in sorted(projection.settings.items()))


def projected_hooks(
    projection: HostProjection, root: Path
) -> tuple[tuple[HookTrustRecord, ...], bool]:
    """The trust records of the projected `.codex/hooks.json` in the lease at `root`, and
    whether it runs Kernel Hooks (`python .mission/hooks/kernel.py ...`).

    The records cover the file as placed: layering (MO-02) merges the projected handlers into
    the repository's own, which shifts the keys Codex derives from handler positions. A file
    changed after `prepare` no longer matches the trust written then, so `hooks/list` refuses."""

    hooks_file = next((item for item in projection.files if item.path == HOOKS_FILE), None)
    if hooks_file is None:
        return (), False
    placed = root / HOOKS_FILE
    content = placed.read_bytes() if placed.is_file() else hooks_file.content
    records = hook_trust_records(content, placed)
    return records, KERNEL_HOOK_SCRIPT.encode("utf-8") in content


def admitted_approval_policy(options: CodexAppServerOptions) -> AskForApproval:
    """The binding's approval policy as the pinned `AskForApproval` enum (the contract admits
    exactly `untrusted | on-request | never`, the pin's string variants)."""

    return options.approval_policy


def execution_binding_digest(operation: OperationExecutionRequest) -> str:
    """The digest `LaneTurnService` records as the execution's `intended_binding_digest`
    (its `_binding_digest`): until a harness request names it, approvals bind with this. A
    codex unit records its effective configuration digest (only a Cursor runtime records its
    own binding digest there)."""

    return operation.effective_configuration_digest


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


class CodexLocalHarness(CodexNativeRunUsage):
    # `CancelledCloseLane`: the interrupted turn's `turn/completed` carries its usage, and a
    # cancelled observation may already have stored it (OC-R3).
    cancelled_close: Final = "observe_or_stored"
    """`codex` Session Lane over an `AppServerLauncher` (the CLI subprocess in production, an
    in-process fixture app-server in tests)."""

    def __init__(
        self,
        *,
        launcher: AppServerLauncher,
        leaser: WorkspaceLeaser,
        projections: ProjectionSource,
        artifacts: ArtifactSink,
        auth: AuthAdmissionSource,
        settings: CodexLocalSettings,
        child_environment: ChildEnvironmentBuilder,
        inputs: DurableInputReader | None = None,
        rows: RowsResolver | None = None,
        broker: ApprovalBroker | None = None,
        describe: LaneDescribe | None = None,
        clock: Callable[[], datetime] = _utc_now,
        unknown_kinds: UnknownKindCounter | None = UNKNOWN_KINDS,
        outputs: LaneOutputCustody | None = None,
        hooks: HookCallbackService | None = None,
        secrets: ProcessSecretDelivery | None = None,
        mission_layer: MissionLayerService | None = None,
    ) -> None:
        self._launcher = launcher
        # G11: the worker's Kernel Hook callback service; a projection with Kernel Hooks is
        # refused without one (its fail-closed hooks would deny every tool).
        self._hooks = hooks
        # MP-20: declared outputs become workspace candidates of the operation when composed.
        self._outputs = outputs
        self._leaser = leaser
        self._projections = projections
        self._artifacts = artifacts
        self._auth = auth
        self._settings = settings
        self._child_environment = child_environment
        # MO-11: the binding's declared secrets reach app-server through the Secret Broker.
        self._secrets = secrets
        # MO-12: a binding that pins an Environment Kit runs its mission layer before start.
        self._mission_layer = mission_layer
        self._inputs = inputs
        self._rows = rows
        # MP-11: approvals bind through the worker's broker; none composed = fail closed.
        self._approvals = CodexApprovals(
            broker=broker,
            wait_seconds=settings.approval_wait_seconds,
            reviewers=settings.approval_reviewers,
            deadline=settings.approval_deadline,
        )
        self._describe = describe or codex_local_describe()
        if self._describe.lane_profile != PROFILE:
            raise ValueError("the Codex local harness describes the codex profile")
        self._clock = clock
        self._counter = unknown_kinds
        self._sessions: dict[str, _Session] = {}
        # Cross-provider control: `thread/fork` receipts per fork request (idempotent).
        self._forks: dict[str, ForkedThread] = {}
        self._cursor_keys: OrderedDict[str, str] = OrderedDict()
        # Per native turn: the cursor of the last frame `observe` yielded.
        self._yielded: OrderedDict[str, str] = OrderedDict()

    def describe(self) -> LaneDescribe:
        return self._describe

    @property
    def approvals(self) -> CodexApprovals:
        return self._approvals

    # --- staging ------------------------------------------------------------------------------

    def stage(self, harness_execution_id: str, operation: OperationExecutionRequest) -> None:
        binding = ProviderExecutionBinding.carried_by(operation)
        if binding is None or binding.lane_profile != PROFILE:
            raise ValueError("codex runs only an operation with a codex mc.execution_binding.v2")
        options = binding.provider_options
        if not isinstance(options, CodexAppServerOptions):
            raise ValueError("a codex binding carries codex_app_server provider options")
        if (
            binding.pins.get("cli.codex") != PINNED_CODEX_CLI_VERSION
            or binding.pins.get("schema.app_server_v2") != PINNED_SCHEMA_SHA256
            or options.app_server_schema_version != f"v2@{PINNED_CODEX_CLI_VERSION}"
        ):
            raise LaneProjectionError(
                "PROVIDER_PIN_MISMATCH",
                "the sealed Codex binding does not match this adapter's CLI/schema pin; "
                "preserve the old binding and explicitly author a new selection",
            )
        current = self._sessions.get(harness_execution_id)
        if current is not None:
            if current.operation != operation:
                raise ValueError("harness execution is staged with another operation")
            return
        self._sessions[harness_execution_id] = _Session(
            operation=operation,
            binding=binding,
            options=options,
            identity=LaneExecutionIdentity.of(operation, PROFILE, 1),
            binding_digest=execution_binding_digest(operation),
            network=network_projection(binding, options),
        )

    def _session(self, request: HarnessRequest) -> _Session:
        session = self._sessions.get(request.harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {request.harness_execution_id} is not staged")
        # The digest the service recorded on the harness execution (the approval policy).
        session.binding_digest = request.binding_digest
        if session.identity.attempt_no != request.generation:
            session.identity = LaneExecutionIdentity.of(
                session.operation, PROFILE, request.generation
            )
        return session

    # --- prepare ------------------------------------------------------------------------------

    async def prepare(self, request: PrepareRequest) -> PreparedSession:
        session = self._session(request)
        prepared = session.prepared
        if (
            prepared is not None
            and session.lease is not None
            and prepared.generation == request.generation
        ):
            # Idempotent per generation: a later turn (an MP-12 continuation turn on the
            # hydrated target) never re-materializes the packet over the continuation
            # packet the hydrator wrote into the lease.
            return prepared
        binding = session.binding
        admitted_approval_policy(session.options)
        if session.admission is None:
            session.admission = await self._auth.admit(binding)
        require_auth_home(
            session.admission.route, self._settings.codex_home_mode, self._settings.owner_codex_home
        )
        if self._settings.codex_home_mode == "owner" and self._settings.owner_codex_home is None:
            raise LaneProjectionError(
                UNSUPPORTED_BEHAVIOR, "owner CODEX_HOME mode needs settings.owner_codex_home"
            )
        lease = await self._leaser.acquire(
            request_scope=session.identity.request_scope,
            lane_profile=PROFILE,
            harness_execution_id=UUID(request.harness_execution_id),
            generation=request.generation,
            run_id=request.run_id,
            attempt_no=request.attempt_no,
            repository=binding.repo_url or self._settings.default_repository,
            base_ref=binding.repo_ref or "main",
            policy=binding.workspace_policy,
        )
        session.lease = lease
        root = Path(lease.path)
        packet = await materialize_packet(
            root, session.operation, self._inputs, mount_root=self._settings.mount_root
        )
        projection = await self._projections.project(
            session.operation, profile=PROFILE, packet_index=None
        )
        executables: dict[str, tuple[str, ...]] | None = None
        if self._rows is not None:
            # MP-03: the launch executables the bound capabilities need (hook interpreters,
            # stdio MCP launchers) must be on the worker's PATH before anything starts.
            executables = required_executables(await self._rows(session.operation), PROFILE)
        try:
            receipt = await asyncio.to_thread(
                materialize_projection,
                projection,
                root,
                expected_digest=binding.materialization_digest,
                executables=executables,
                require_executables=self._settings.require_executables,
                policy=binding.materialization,
            )
        except LayeringRefused as error:
            raise LaneProjectionError(MATERIALIZATION_CONFLICT, str(error)) from error
        except MaterializationRejected as error:
            raise LaneProjectionError(CAPABILITY_DRIFT, str(error)) from error
        session.projection_paths = projection.paths()
        session.environment_names = projection.environment_names
        session.developer_instructions = _developer_instructions(projection.send_options)
        session.materialization = receipt
        await self._place_hooks(session, projection, root)
        trust_required = bool(projection.report.requires_trust)
        session.codex_home, session.config_overrides = await asyncio.to_thread(
            self._prepare_codex_home, root, trust_required, session.hook_trust
        )
        await self._place_seed(session, request.seed)
        setup = await self._prepare_environment(session, root)
        session.digests = {
            "projection_digest": receipt.projection_digest,
            "packet_digest": sha256_digest(packet),
            "materialization_digest": stable_json_digest(receipt),
            **(setup.digests() if setup is not None else {}),
        }
        session.prepared = PreparedSession(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            workspace_ref=f"workspace_lease:{lease.lease_id}",
            projection_digests=session.digests,
            materialization_ref=sha256_digest(sorted(item.path for item in receipt.files)),
            discovery=discovery_expectation(
                PROFILE, receipt.layering, {item.path: item.digest for item in receipt.files}
            ),
        )
        return session.prepared

    async def _prepare_environment(
        self, session: _Session, root: Path
    ) -> MissionLayerOutcome | None:
        """The bootstrap entrypoint: the kit's mission layer, run before app-server starts."""

        try:
            return await prepare_lane_environment(
                self._mission_layer,
                session.binding.environment,
                root,
                identity=session.identity,
                environ=(
                    self._settings.worker_environ
                    if self._settings.worker_environ is not None
                    else os.environ
                ),
                child_environment=self._child_environment,
                secrets=self._secrets,
            )
        except EnvironmentNotPrepared as error:
            raise LaneProjectionError(error.code, error.detail) from error

    async def _place_hooks(self, session: _Session, projection: HostProjection, root: Path) -> None:
        """SPEC-02 §5: record the trust of every projected hook handler and, with Kernel Hooks,
        write `.mission/hooks/kernel.py` (G11). Hooks are refused where they cannot run: in the
        owner's CODEX_HOME (Mission Control never writes its trust there) and, for Kernel
        Hooks, without the worker's callback service."""

        try:
            session.hook_trust, session.kernel_hooks = projected_hooks(projection, root)
        except ValueError as error:
            # A repository handler layering kept that Mission Control cannot hash-trust.
            raise LaneProjectionError(HOOK_TRUST_UNVERIFIED, str(error)) from error
        if session.hook_trust and self._settings.codex_home_mode == "owner":
            raise LaneProjectionError(
                HOOK_TRUST_UNVERIFIED,
                "projected Codex hooks need an isolated CODEX_HOME: codex-cli honours hook "
                "trust only from the home's config.toml, never from a -c override",
            )
        if not session.kernel_hooks:
            return
        if self._hooks is None:
            raise LaneProjectionError(
                UNSUPPORTED_BEHAVIOR,
                "the projection runs Kernel Hooks but no hook callback service is composed",
            )
        await asyncio.to_thread(
            write_files,
            root,
            (ProjectedFile(path=KERNEL_HOOK_PATH, content=kernel_hook_script(), mode=0o755),),
        )

    def _prepare_codex_home(
        self, root: Path, trust_required: bool, hooks: Sequence[HookTrustRecord] = ()
    ) -> tuple[Path, tuple[str, ...]]:
        if self._settings.codex_home_mode == "owner":
            assert self._settings.owner_codex_home is not None
            overrides = (trust_override(root),) if trust_required else ()
            return self._settings.owner_codex_home, overrides
        home = root / CODEX_HOME_DIR
        home.mkdir(parents=True, exist_ok=True)
        if trust_required or hooks:
            (home / "config.toml").write_text(trust_config_toml(root, hooks), encoding="utf-8")
        return home, ()

    # --- launch, start, reattach ----------------------------------------------------------------

    async def _launch(self, session: _Session) -> AppServerConnection:
        launched = await self._spawn(session)
        await self._attach(session, launched)
        return launched.connection

    async def _spawn(self, session: _Session) -> LaunchedAppServer:
        """A new `codex app-server` over the session's lease, initialized, not yet attached."""

        if session.admission is None:
            session.admission = await self._auth.admit(session.binding)
        require_auth_home(
            session.admission.route, self._settings.codex_home_mode, self._settings.owner_codex_home
        )
        root = session.root
        if session.codex_home is None:
            session.codex_home, session.config_overrides = await asyncio.to_thread(
                self._prepare_codex_home, root, False
            )
        codex_home = session.codex_home
        if codex_home is None:
            raise NativeTurnLost("CODEX_HOME was not prepared for this session")
        if session.environment_names is None:
            # Not prepared by this process (a reattach): the pinned projection names the
            # variables to forward and the hooks whose trust the launch must confirm.
            projection = await self._projections.project(
                session.operation, profile=PROFILE, packet_index=None
            )
            session.environment_names = projection.environment_names
            session.developer_instructions = _developer_instructions(projection.send_options)
            session.hook_trust, session.kernel_hooks = projected_hooks(projection, root)
        if session.delivered is None and self._secrets is not None:
            delivered = await self._secrets.environment(
                session.binding.environment, session.identity
            )
            session.delivered = dict(delivered.values)
        env = child_environment(
            self._settings.worker_environ
            if self._settings.worker_environ is not None
            else os.environ,
            session.admission,
            codex_home=codex_home,
            builder=self._child_environment,
            declared=session.environment_names,
            extra=session.delivered,
        )
        api_key_params: ApiKeyLoginParams | None = None
        auth_overrides: tuple[str, ...] = ()
        if session.admission.route == "api_key" and self._settings.codex_home_mode == "isolated":
            reference = session.admission.credential_ref or ""
            name = reference.removeprefix("env:") if reference.startswith("env:") else ""
            key = env.get(name)
            if not key or not key.strip():
                raise LaneProjectionError(
                    "CODEX_API_KEY_UNAVAILABLE", "admitted Codex API-key credential is unavailable"
                )
            api_key_params = ApiKeyLoginParams(api_key=key)
            # The pinned native default otherwise persists auth.json inside CODEX_HOME.
            auth_overrides = ('cli_auth_credentials_store="ephemeral"',)
        launched = await self._launcher.launch(
            LaunchSpec(
                cwd=root,
                env=env,
                codex_home=codex_home,
                sensitive_values=tuple(
                    dict.fromkeys(
                        (
                            *((api_key_params.api_key,) if api_key_params is not None else ()),
                            *(session.delivered or {}).values(),
                        )
                    )
                ),
                config_overrides=(
                    *session.config_overrides,
                    *network_overrides(session.network),
                    *auth_overrides,
                    *shell_environment_overrides(
                        env,
                        session.admission,
                        agent_names=session.delivered or {},
                    ),
                ),
            )
        )
        connection = launched.connection
        InitializeResponse.model_validate(
            await connection.request(
                M_INITIALIZE,
                InitializeParams(
                    client_info=ClientInfo(
                        name=CLIENT_NAME,
                        title="Mission Control",
                        version=self._settings.client_version,
                    ),
                    capabilities=InitializeCapabilities(experimental_api=False),
                ).params(),
            )
            or {}
        )
        await connection.notify(M_INITIALIZED)
        if api_key_params is not None:
            try:
                ApiKeyLoginResponse.model_validate(
                    await connection.request(M_ACCOUNT_LOGIN_START, api_key_params.params())
                )
                account = await connection.request(M_ACCOUNT_READ, {"refreshToken": False})
                if (
                    not isinstance(account, Mapping)
                    or not isinstance(account.get("account"), Mapping)
                    or account["account"].get("type") != "apiKey"
                ):
                    raise ValueError("native API-key route not confirmed")
            except BaseException as error:
                await launched.terminate()
                if isinstance(error, asyncio.CancelledError):
                    raise
                # Native errors can reflect request material; never expose their text or cause.
                raise LaneProjectionError(
                    "CODEX_API_KEY_LOGIN_UNCONFIRMED",
                    "Codex API-key initialization was not confirmed; process terminated",
                ) from None
        if session.hook_trust:
            try:
                await self._verify_hook_trust(connection, root, session.hook_trust)
            except BaseException:
                await launched.terminate()
                raise
        return launched

    async def _verify_hook_trust(
        self, connection: AppServerConnection, root: Path, records: Sequence[HookTrustRecord]
    ) -> None:
        """Before any thread exists, Codex must report every projected hook trusted at the
        recorded hash (Q-X2): a Kernel Hook it would skip is never silently absent."""

        listed = await connection.request(M_HOOKS_LIST, {"cwds": [str(root)]})
        try:
            verify_listed_trust(listed or {}, records, root / HOOKS_FILE)
        except HookTrustUnverified as error:
            raise LaneProjectionError(HOOK_TRUST_UNVERIFIED, str(error)) from error

    async def _attach(self, session: _Session, launched: LaunchedAppServer) -> None:
        """Make `launched` the session's connection: recover, then pump its events."""

        session.launched = launched
        session.connection_lost = None
        connection = launched.connection
        # MP-11: a new process is a new connection; every live approval correlation an
        # earlier connection held is lost (never reused) before anything is (re)dispatched.
        await self._approvals.recover(
            session.identity.request_scope,
            str(session.identity.harness_execution_id),
            connection.epoch,
        )
        session.pump = asyncio.create_task(
            self._pump(session, connection), name=f"codex-pump-{session.identity.run_key}"
        )

    def _thread_start_params(self, session: _Session) -> dict[str, Any]:
        return ThreadStartParams(
            cwd=session.root.as_posix(),
            model=session.binding.model.model_id,
            approval_policy=admitted_approval_policy(session.options),
            approvals_reviewer="user",
            sandbox=session.options.sandbox_mode,
            ephemeral=False,
            developer_instructions=session.developer_instructions,
        ).params()

    async def start(self, request: StartRequest) -> SessionHandle:
        session = self._session(request)
        if session.lease is None:
            raise ValueError("start requires a prepared workspace lease")
        if request.seed is not None and session.seed is None:
            await self._place_seed(session, request.seed)
        connection = await self._launch(session)
        resumed = await self._resume_seeded_thread(session, connection)
        if resumed is None:
            params = self._thread_start_params(session)
            try:
                response = ThreadStartResponse.model_validate(
                    await connection.request(M_THREAD_START, params)
                )
            except AppServerError as error:
                self._raise_if_limited(error, source="codex.thread_start")
                raise
            thread, model = response.thread, response.model
            if session.seed is not None:
                session.seed_restore = "R1"
        else:
            thread, model = resumed
            session.seed_restore = "R3"
        session.thread_id = thread.id
        session.usage_tracker.start_thread(thread.id)
        session.thread_status = thread.status.type
        session.model = model or thread.model
        if session.kernel_hooks:
            await self._install_hook_context(session, request, thread.id)
        return self._handle(request, session)

    # --- cross-provider control: seeds, points and the time-travel ports ---------------------

    async def _place_seed(self, session: _Session, seed: LaneSeedHead | None) -> None:
        """Keep the seed head and, when it carries the forked thread's rollout, write it into
        this session's isolated `CODEX_HOME` so `thread/resume` finds it; stage the hydration
        preamble the first turn carries. Nothing of the source thread is written."""

        if seed is None:
            return
        session.seed = seed
        session.forked_from = seed.native_artifacts.get(A_SOURCE_THREAD)
        artifacts = seed.native_artifacts
        rollout_ref = artifacts.get(A_ROLLOUT_REF)
        relpath = artifacts.get(A_ROLLOUT_RELPATH)
        if (
            rollout_ref
            and relpath
            and self._inputs is not None
            and session.codex_home is not None
            and self._settings.codex_home_mode == "isolated"
        ):
            content = await self._inputs.retrieve(rollout_ref)
            target = session.codex_home.joinpath(*safe_relative(relpath).parts)
            await asyncio.to_thread(_write_private, target, content)
        prefix: list[str] = []
        hydration_ref = artifacts.get(A_HYDRATION_REF)
        if hydration_ref and self._inputs is not None:
            prefix.append((await self._inputs.retrieve(hydration_ref)).decode("utf-8", "replace"))
        elif seed.message is not None:
            prefix.append(seed.message)
        session.seed_prefix = "\n\n".join(part for part in prefix if part) or None

    async def _resume_seeded_thread(
        self, session: _Session, connection: AppServerConnection
    ) -> tuple[Thread, str | None] | None:
        """`thread/resume` of the forked thread a seed names; None when there is no such
        thread or the server cannot load it (the start then falls back to a fresh thread)."""

        seed = session.seed
        derived = seed.native_artifacts.get(A_DERIVED_THREAD) if seed is not None else None
        if not derived:
            return None
        params = ThreadResumeParams(
            thread_id=derived,
            cwd=session.root.as_posix(),
            model=session.binding.model.model_id,
            approval_policy=admitted_approval_policy(session.options),
            approvals_reviewer="user",
            sandbox=session.options.sandbox_mode,
        ).params()
        try:
            response = ThreadResumeResponse.model_validate(
                await connection.request(M_THREAD_RESUME, params)
            )
        except AppServerError as error:
            _LOGGER.warning(
                "forked thread %s cannot be resumed (%s); a fresh thread starts with the preamble",
                derived,
                error.message,
            )
            return None
        thread = response.thread
        session.usage_tracker.resume_thread(thread.id)
        self._absorb_history(session, thread, connection.epoch)
        return thread, response.model

    def turn_points(self, request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
        """`PointCollectingLane`: one `thread_item` point per step boundary of the turn."""

        return points_fold.turn_points(request)

    async def thread_history(self, thread_id: str) -> Thread | None:
        """`CodexThreadReader`: `thread/read` with turns of a thread this process holds."""

        heid = self.live_session(thread_id)
        session = self._sessions.get(heid) if heid is not None else None
        connection = session.connection if session is not None else None
        if session is None or connection is None:
            return None
        try:
            return await self._read_thread(session, connection, include_turns=True)
        except (AppServerError, ResponseLost, TransportClosed):
            return None

    async def fork_thread(
        self, thread_id: str, *, last_turn_id: str | None, fork_request_id: str
    ) -> ForkedThread | None:
        """`CodexThreadForker`: `thread/fork` of a thread this process holds, through
        `last_turn_id` (inclusive). Idempotent per fork request; None when the thread is not
        live here or the server refuses (the seed then falls back to a transcript)."""

        known = self._forks.get(fork_request_id)
        if known is not None:
            return known
        heid = self.live_session(thread_id)
        session = self._sessions.get(heid) if heid is not None else None
        connection = session.connection if session is not None else None
        if session is None or connection is None:
            return None
        params = ThreadForkParams(
            thread_id=thread_id,
            last_turn_id=last_turn_id,
            cwd=session.root.as_posix(),
            model=session.binding.model.model_id,
            approval_policy=admitted_approval_policy(session.options),
            approvals_reviewer="user",
            sandbox=session.options.sandbox_mode,
            ephemeral=False,
            developer_instructions=session.developer_instructions,
            exclude_turns=True,
        ).params()
        try:
            response = ThreadForkResponse.model_validate(
                await connection.request(M_THREAD_FORK, params)
            )
        except (AppServerError, ResponseLost, TransportClosed) as error:
            _LOGGER.warning("thread/fork of %s refused: %s", thread_id, error)
            return None
        forked = ForkedThread(
            thread_id=response.thread.id,
            rollout_path=response.thread.path,
            codex_home=str(session.codex_home) if session.codex_home is not None else None,
        )
        self._forks[fork_request_id] = forked
        return forked

    async def _install_hook_context(
        self, session: _Session, request: HarnessRequest, thread_id: str
    ) -> None:
        """G11, as `cursor_local` does: the task token is minted once the native thread
        exists (before any turn, so before any permission hook can fire)."""

        assert self._hooks is not None
        identity = session.identity
        context = HookTokenContext(
            request_scope=identity.request_scope,
            run_id=identity.run_key,
            attempt_no=identity.attempt_no,
            generation=request.generation,
            harness_execution_id=identity.harness_execution_id,
            lane_profile=PROFILE,
            execution_start=execution_start(
                session.operation, identity, request.generation, thread_id
            ),
            workspace_root=str(session.root),
        )
        session.token_context = context
        await install_hook_context(
            self._hooks,
            context,
            root=session.root,
            callback_base_url=self._settings.hook_callback_base_url,
            ttl=self._settings.hook_token_ttl,
        )

    async def discover(self, session: SessionHandle) -> DiscoveryReport | None:
        """MO-34: what the app-server loaded for the workspace once the thread exists
        (`skills/list`, `hooks/list`, `config/read`; `discovery.py`)."""

        state = self._sessions.get(session.harness_execution_id)
        connection = state.connection if state is not None else None
        if state is None or connection is None:
            return None
        root = str(state.root)
        try:
            skills = await connection.request(M_SKILLS_LIST, {"cwds": [root]})
            hooks = await connection.request(M_HOOKS_LIST, {"cwds": [root]})
            config = await connection.request(M_CONFIG_READ, {"cwd": root})
        except AppServerError as error:
            self._raise_if_limited(error, source="codex.discover")
            raise
        return app_server_report(
            skills or {},
            hooks or {},
            config or {},
            source=f"app_server:{session.native_session_ref}",
        )

    def _handle(self, request: HarnessRequest, session: _Session) -> SessionHandle:
        assert session.thread_id is not None
        launched = session.launched
        details = {
            "codex_cli_version": (launched.versions.get("codex_cli", "") if launched else ""),
            "codex_home": str(session.codex_home or ""),
            "app_server_epoch": launched.connection.epoch if launched else "",
            "app_server_schema_sha256": PINNED_SCHEMA_SHA256,
            # Q-X2 evidence: how many projected hooks `hooks/list` reported trusted.
            "hooks_trusted": str(len(session.hook_trust)) if session.hook_trust else "",
            # Cross-provider control: how far the seeded start restored, and from what.
            "seed_restore": session.seed_restore or "",
            "forked_from": session.forked_from or "",
            **(session.network.native_details() if session.network is not None else {}),
        }
        return SessionHandle(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            native_session_ref=session.thread_id,
            native_details={key: value for key, value in details.items() if value},
        )

    async def _reconnect(
        self, session: _Session, request: HarnessRequest, thread_id: str
    ) -> Thread:
        """Relaunch over the same lease and resume the thread from disk (emulated reattach)."""

        if session.lease is None:
            session.lease = await self._leaser.find(
                request_scope=session.identity.request_scope,
                lane_profile=PROFILE,
                harness_execution_id=UUID(request.harness_execution_id),
                generation=request.generation,
            )
        if session.lease is None or session.lease.released:
            raise NativeTurnLost("the workspace lease of this session is gone")
        if not await asyncio.to_thread(session.root.is_dir):
            raise NativeTurnLost("the workspace of this session is gone")
        await self._terminate(session)
        session.usage_tracker.resume_thread(thread_id)
        connection = await self._launch(session)
        params = ThreadResumeParams(
            thread_id=thread_id,
            cwd=session.root.as_posix(),
            model=session.binding.model.model_id,
            approval_policy=admitted_approval_policy(session.options),
            approvals_reviewer="user",
            sandbox=session.options.sandbox_mode,
        ).params()
        try:
            response = ThreadResumeResponse.model_validate(
                await connection.request(M_THREAD_RESUME, params)
            )
        except AppServerError as error:
            raise NativeTurnLost(
                f"thread {thread_id} cannot be resumed: {error.message}"
            ) from error
        thread = response.thread
        session.thread_id = thread.id
        session.thread_status = thread.status.type
        session.model = response.model or thread.model or session.model
        self._absorb_history(session, thread, connection.epoch)
        return thread

    def _absorb_history(self, session: _Session, thread: Thread, epoch: str) -> None:
        if session.usage_tracker.current_turn is None and thread.turns:
            # History supplies turn identity, never an invented usage counter/baseline.
            session.usage_tracker.current_turn = thread.turns[-1].id
        for turn in thread.turns:
            state = session.turns.setdefault(turn.id, _TurnState(turn.id))
            state.status = turn.status
            state.epoch = epoch
            state.last_agent_text = framing.agent_text(turn.items) or state.last_agent_text
            if state.terminal:
                state.done.set()
            elif session.active_turn is None:
                session.active_turn = turn.id
        if thread.status.type != "active":
            session.active_turn = None

    async def reattach(self, request: ReattachRequest) -> SessionHandle:
        session = self._session(request)
        pending = session.pending
        if pending is not None and pending.thread_id == request.native_session_ref:
            # MP-12: the activated continuation target (recorded as the execution's native
            # session) is the hydrated fresh thread: adopt it, never resume the source.
            await self._adopt(session)
        if session.connection is not None and session.thread_id == request.native_session_ref:
            return self._handle(request, session)
        thread = await self._reconnect(session, request, request.native_session_ref)
        if request.native_turn_ref is not None and request.native_turn_ref not in {
            turn.id for turn in thread.turns
        }:
            raise NativeTurnLost(
                f"thread {thread.id} history does not contain turn {request.native_turn_ref}"
            )
        return self._handle(request, session)

    async def _ensure_connection(
        self, session: _Session, request: HarnessRequest, thread_id: str | None
    ) -> AppServerConnection:
        connection = session.connection
        if connection is not None:
            return connection
        resolved = thread_id or session.thread_id
        if resolved is None:
            raise NativeTurnLost("no native thread to reconnect to")
        await self._reconnect(session, request, resolved)
        connection = session.connection
        assert connection is not None
        return connection

    # --- the event pump: turn lifecycle and approvals, with or without an observer --------------

    async def _pump(self, session: _Session, connection: AppServerConnection) -> None:
        try:
            async for event in connection.events(0):
                try:
                    await self._absorb(session, connection, event)
                except TransportClosed:
                    raise
                except Exception:
                    _LOGGER.exception("codex event %s was not absorbed", event.method)
                finally:
                    session.absorbed_seq = event.seq
        except TransportClosed as closed:
            session.connection_lost = closed.reason
            for state in session.turns.values():
                state.done.set()
        except asyncio.CancelledError:
            raise

    async def _pump_caught_up(
        self, session: _Session, connection: AppServerConnection, *, timeout_s: float = 2.0
    ) -> None:
        """Turn admission reads lifecycle state the pump derives from the event stream:
        wait (bounded) until it has absorbed every event received so far."""

        deadline = asyncio.get_running_loop().time() + timeout_s
        while session.absorbed_seq < connection.last_seq and not connection.closed:
            if asyncio.get_running_loop().time() >= deadline:
                return
            await asyncio.sleep(0.005)

    async def _absorb(
        self, session: _Session, connection: AppServerConnection, event: InboundEvent
    ) -> None:
        session.event_clock += 1
        if event.kind == "server_request":
            await self._answer_server_request(session, connection, event)
            return
        root = session.thread_id
        method, params = event.method, event.params
        if method == N_TURN_STARTED:
            started = TurnNotification.model_validate(params)
            if started.thread_id == root:
                session.usage_tracker.begin(started.turn.id)
                state = session.turns.setdefault(started.turn.id, _TurnState(started.turn.id))
                state.status = started.turn.status
                state.epoch = state.epoch or connection.epoch
                state.started_epoch = state.started_epoch or connection.epoch
                session.active_turn = started.turn.id
                session.thread_status = "active"
        elif method == N_TURN_COMPLETED:
            completed = TurnNotification.model_validate(params)
            if completed.thread_id == root:
                turn = completed.turn
                state = session.turns.setdefault(turn.id, _TurnState(turn.id))
                state.status = turn.status
                state.completed_at = (connection.epoch, event.seq)
                state.last_agent_text = framing.agent_text(turn.items) or state.last_agent_text
                state.done.set()
                if session.active_turn == turn.id:
                    session.active_turn = None
                    session.thread_status = "idle"
        elif method == N_THREAD_STATUS_CHANGED:
            if params.get("threadId") == root:
                status = ThreadStatus.model_validate(params.get("status") or {})
                session.thread_status = status.type
                if status.type != "active":
                    session.active_turn = None
        elif method == N_ITEM_COMPLETED:
            item_note = ItemNotification.model_validate(params)
            item_type = item_note.item.get("type")
            if item_note.thread_id == root and item_type == "agentMessage":
                text = item_note.item.get("text")
                if isinstance(text, str) and text:
                    turn_id = item_note.turn_id
                    session.turns.setdefault(turn_id, _TurnState(turn_id)).last_agent_text = text
            elif item_note.thread_id == root and item_type == "contextCompaction":
                session.compaction_clock = session.event_clock
        elif method == N_THREAD_COMPACTED:
            if params.get("threadId") == root:
                session.compaction_clock = session.event_clock
        elif method == N_USAGE_UPDATED:
            usage_note = TokenUsageNotification.model_validate(params)
            if usage_note.thread_id == root:
                turn_id = usage_note.turn_id
                session.usage_tracker.record(
                    turn_id, usage_note.token_usage, epoch=connection.epoch, seq=event.seq
                )
                session.turns.setdefault(
                    turn_id, _TurnState(turn_id)
                ).usage = usage_note.token_usage
                session.last_usage = usage_note.token_usage
                session.usage_clock = session.event_clock
        elif method == N_ERROR:
            error_note = ErrorNotification.model_validate(params)
            if error_note.thread_id == root:
                turn_id = error_note.turn_id
                session.turns.setdefault(
                    turn_id, _TurnState(turn_id)
                ).last_error = error_note.error.message

    async def _answer_server_request(
        self, session: _Session, connection: AppServerConnection, event: InboundEvent
    ) -> None:
        assert event.request_id is not None
        if event.method not in APPROVAL_REQUEST_METHODS:
            # Credentials, attestations, dynamic tools and legacy approvals are never answered
            # with an effect of the lane's own.
            await connection.respond_error(
                event.request_id,
                ERR_REFUSED_BY_MISSION_CONTROL,
                f"{event.method} is not answered by mission control",
            )
            return
        # Each request is served in its own task: a human wait of minutes never stalls the
        # pump (turn lifecycle, status and other requests keep being absorbed).
        task = asyncio.create_task(
            self._serve_approval(session, connection, event),
            name=f"codex-approval-{connection.epoch}-{event.request_id}",
        )
        session.approval_tasks.add(task)
        task.add_done_callback(session.approval_tasks.discard)

    def _approval_context(
        self, session: _Session, connection: AppServerConnection
    ) -> ApprovalContext:
        return ApprovalContext(
            request_scope=session.identity.request_scope,
            run_id=session.identity.run_key,
            harness_execution_id=str(session.identity.harness_execution_id),
            generation=session.identity.attempt_no,
            native_session_ref=session.thread_id,
            policy_digest=session.binding_digest or execution_binding_digest(session.operation),
            connection_epoch=connection.epoch,
        )

    async def _serve_approval(
        self, session: _Session, connection: AppServerConnection, event: InboundEvent
    ) -> None:
        assert event.request_id is not None

        async def gate() -> None:
            # Bound (persisted) already; held here while the lane is paused at the tool gate.
            if session.unheld.is_set():
                return
            session.held_waiters += 1
            try:
                await session.unheld.wait()
            finally:
                session.held_waiters -= 1

        try:
            answer = await self._approvals.serve(
                event, self._approval_context(session, connection), gate=gate
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Nothing could be bound or decided (store or probe failure): fail closed.
            _LOGGER.exception("codex approval %s failed; answered fail-closed", event.method)
            answer = fail_closed_response(event.method, f"approval failed: {error}"[:512])
        try:
            if answer.is_error:
                assert answer.error_code is not None
                await connection.respond_error(
                    event.request_id, answer.error_code, answer.error_message
                )
            else:
                await connection.respond(event.request_id, answer.result)
        except TransportClosed as closed:
            # The request died with its connection; the decision stays on the durable task as
            # evidence and the next launch's `recover` closes whatever correlation is live.
            _LOGGER.warning("codex approval answer not delivered: %s", closed.reason)

    async def hold_approvals(self, harness_execution_id: str, held: bool) -> int:
        """`pause_at_tool_gate`: hold (or release) approval answers; the turn waits at its
        tool gate meanwhile (every request is bound and persisted before it is held).
        Returns the number of held requests released."""

        session = self._sessions.get(harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {harness_execution_id} is not staged")
        if held:
            session.unheld.clear()
            return 0
        released = session.held_waiters
        session.unheld.set()
        return released

    # --- turns ----------------------------------------------------------------------------------

    def _raise_if_limited(self, error: AppServerError, *, source: str) -> None:
        signal = limit_signal_from_rpc_error(error.data, source=source)
        if signal is not None:
            raise ProviderCapacityLimited(signal) from error

    async def _read_thread(
        self, session: _Session, connection: AppServerConnection, *, include_turns: bool
    ) -> Thread:
        assert session.thread_id is not None
        response = ThreadReadResponse.model_validate(
            await connection.request(
                M_THREAD_READ,
                ThreadReadParams(thread_id=session.thread_id, include_turns=include_turns).params(),
                timeout_s=self._settings.status_timeout_s,
            )
        )
        session.thread_status = response.thread.status.type
        return response.thread

    async def send_turn(self, request: SendTurnRequest) -> TurnHandle:
        session = self._session(request)
        pending = session.pending
        if pending is not None and request.session.native_session_ref == pending.thread_id:
            # The continuation turn goes to the hydrated target: adopt it first.
            await self._adopt(session)
        thread_id = request.session.native_session_ref or session.thread_id
        if thread_id is None:
            raise ValueError("send_turn requires a started session")
        async with session.admission_lock:
            known = session.sent.get(request.idempotency_key)
            if known is not None:
                return TurnHandle(
                    session=request.session, turn_no=request.turn_no, native_turn_ref=known
                )
            connection = await self._ensure_connection(session, request, thread_id)
            await self._pump_caught_up(session, connection)
            thread = await self._read_thread(session, connection, include_turns=False)
            if thread.status.type == "active" or session.active_turn is not None:
                # A `turn/start` on an active thread steers it: never from a queued send.
                return TurnHandle(session=request.session, turn_no=request.turn_no, status="busy")
            if thread.status.type == "systemError":
                raise NativeTurnLost(f"thread {thread_id} is in systemError")
            text = session.turn_texts.get(request.instruction_ref) or turn_text(session.operation)
            if session.seed_prefix is not None and not session.sent:
                # The seed's hydration preamble travels ahead of the first turn only.
                text = f"{session.seed_prefix}\n\n{text}"
            params = TurnStartParams(
                thread_id=thread_id,
                input=(TextUserInput(text=text),),
                client_user_message_id=request.idempotency_key,
                effort=session.options.reasoning_effort,
            ).params()
            # Every event of the new turn arrives after this point of the connection.
            seq_before = connection.last_seq
            try:
                response = TurnStartResponse.model_validate(
                    await connection.request(M_TURN_START, params)
                )
            except AppServerError as error:
                self._raise_if_limited(error, source="codex.turn_start")
                raise
            turn_id = response.turn.id
            session.usage_tracker.begin(turn_id)
            state = session.turns.setdefault(turn_id, _TurnState(turn_id))
            state.status = response.turn.status
            state.epoch = connection.epoch
            state.started_epoch = connection.epoch
            state.start_seq = seq_before
            session.active_turn = turn_id if not state.terminal else None
            session.sent[request.idempotency_key] = turn_id
            session.seed_prefix = None
            return TurnHandle(
                session=request.session, turn_no=request.turn_no, native_turn_ref=turn_id
            )

    def stage_turn(self, harness_execution_id: str, instruction_ref: str, text: str) -> None:
        """The text a later turn (or a steer) sends by instruction ref (`TurnTextStaging`)."""

        session = self._sessions.get(harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {harness_execution_id} is not staged")
        session.turn_texts[instruction_ref] = text
        if session.lease is not None:
            name = sha256_digest(instruction_ref).removeprefix("sha256:")[:16]
            write_files(
                session.root,
                (
                    ProjectedFile(
                        path=f"{TURNS_DIR}/{name}.md", content=text.encode("utf-8"), mode=0o444
                    ),
                ),
            )

    async def steer(self, turn: TurnHandle, *, instruction_ref: str) -> SteerResult:
        """`cooperative_inject`: steer exactly `turn`; anything else is `stale_target`."""

        session = self._sessions.get(turn.session.harness_execution_id)
        if session is None:
            return SteerResult(outcome="stale_target", detail="session is not staged")
        target = turn.native_turn_ref
        if target is None:
            return SteerResult(outcome="stale_target", detail="turn has no native identity")
        text = session.turn_texts.get(instruction_ref)
        if text is None:
            # The instruction's text was not staged for this lane: requeue it for the next
            # boundary rather than steer blind (never a different instruction).
            return SteerResult(outcome="stale_target", detail="instruction text not staged")
        state = session.turns.get(target)
        if session.active_turn != target or (state is not None and state.terminal):
            return SteerResult(
                outcome="stale_target", target_turn_ref=None, detail="turn is not active"
            )
        connection = session.connection
        if connection is None:
            return SteerResult(outcome="stale_target", detail="no live app-server")
        params = TurnSteerParams(
            thread_id=session.thread_id or turn.session.native_session_ref or "",
            expected_turn_id=target,
            input=(TextUserInput(text=text),),
            client_user_message_id=f"{instruction_ref}:steer:{target}"[:512],
        ).params()
        try:
            response = TurnSteerResponse.model_validate(
                await connection.request(M_TURN_STEER, params)
            )
        except AppServerError as error:
            return SteerResult(
                outcome="stale_target", detail=f"refused ({error.code}): {error.message}"[:512]
            )
        except (ResponseLost, TransportClosed) as error:
            return SteerResult(outcome="stale_target", detail=str(error)[:512])
        if response.turn_id != target:
            return SteerResult(
                outcome="stale_target",
                target_turn_ref=response.turn_id,
                detail="the server steered another turn",
            )
        return SteerResult(outcome="applied", target_turn_ref=response.turn_id)

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt:
        session = self._session(request)
        turn_id = request.turn.native_turn_ref
        thread_id = request.turn.session.native_session_ref or session.thread_id
        if turn_id is None or thread_id is None:
            return CancelReceipt(acknowledged=True, already_terminal=True, native_status="idle")
        state = session.turns.get(turn_id)
        if state is not None and state.terminal:
            return CancelReceipt(
                acknowledged=True, already_terminal=True, native_status=state.status
            )
        try:
            connection = await self._ensure_connection(session, request, thread_id)
        except NativeTurnLost:
            return CancelReceipt(acknowledged=False, native_status="unknown")
        already = False
        try:
            await connection.request(
                M_TURN_INTERRUPT,
                TurnInterruptParams(thread_id=thread_id, turn_id=turn_id).params(),
            )
        except AppServerError as error:
            state = session.turns.get(turn_id)
            if state is not None and state.terminal:
                already = True
            else:
                return CancelReceipt(acknowledged=False, native_status=f"refused:{error.code}"[:64])
        except (ResponseLost, TransportClosed):
            return CancelReceipt(acknowledged=False, native_status="unknown")
        state = session.turns.setdefault(turn_id, _TurnState(turn_id))
        # Terminal completion after interruption is observed, never assumed.
        with suppress(TimeoutError):
            await asyncio.wait_for(state.done.wait(), self._settings.interrupt_settle_s)
        status = state.status if state.terminal else "interrupting"
        return CancelReceipt(acknowledged=True, already_terminal=already, native_status=status)

    # --- observe --------------------------------------------------------------------------------

    def _remember_cursor(self, provider_key: str, cursor: str) -> None:
        self._cursor_keys[provider_key] = cursor
        self._cursor_keys.move_to_end(provider_key)
        while len(self._cursor_keys) > self._settings.cursor_key_memory:
            self._cursor_keys.popitem(last=False)

    def _yielding(self, turn_id: str, frame: LaneFrame) -> LaneFrame:
        self._yielded[turn_id] = frame.cursor
        self._yielded.move_to_end(turn_id)
        while len(self._yielded) > 1_024:
            self._yielded.popitem(last=False)
        return frame

    def final_text(self, turn: TurnHandle, frame: LaneFrame) -> str | None:
        """`FinalTextLane` (MP-20): the turn's whole final agent message, as the pump recorded
        it, else from the terminal `turn/completed` body (never the bounded excerpt)."""

        session = self._sessions.get(turn.session.harness_execution_id)
        state = (
            session.turns.get(turn.native_turn_ref)
            if session is not None and turn.native_turn_ref is not None
            else None
        )
        if state is not None and state.last_agent_text:
            return state.last_agent_text
        body = frame.body if isinstance(frame.body, Mapping) else {}
        payload = body.get("turn")
        if not isinstance(payload, Mapping):
            return None
        try:
            return framing.agent_text(Turn.model_validate(payload).items)
        except ValueError:
            return None

    def resume_cursor(self, provider_key: str) -> str | None:
        """Where a later segment resumes when `provider_key` is the last STORED frame.

        Only when that frame is also the last one `observe` yielded for its turn, and (live
        cursors) its app-server process is still connected. Otherwise frames after it were
        taken as duplicates (a history resync, a re-read event) or never taken, and `None`
        lets `LaneTurnService` fall back to its own last-taken cursor (heartbeat or recorded
        segment cursor, written only after the frames it names were persisted): resuming at
        the stored key would re-take those duplicates in every segment (a livelock under a
        small `max_frames`), exactly as after a worker restart.
        """

        cursor = self._cursor_keys.get(provider_key)
        parsed = framing.parse_cursor(cursor)
        if cursor is None or parsed is None:
            return None
        if self._yielded.get(parsed.turn_id) != cursor:
            return None
        if parsed.history is not None:
            return cursor
        live = {
            session.launched.connection.epoch
            for session in self._sessions.values()
            if session.launched is not None and not session.launched.connection.closed
        }
        return cursor if parsed.epoch in live else None

    def _frames_of(
        self,
        session: _Session,
        request: ObserveRequest,
        event: InboundEvent,
        epoch: str,
        turn_id: str,
        *,
        history_from: int | None = None,
    ) -> list[LaneFrame]:
        """The frames of one event with their cursors (see `frames` for the cursor rules)."""

        root = session.thread_id or request.turn.session.native_session_ref or ""
        if event.method == N_TURN_STARTED and event.params.get("threadId") == root:
            session.usage_tracker.begin(TurnNotification.model_validate(event.params).turn.id)
        completed_ours = (
            event.method == N_TURN_COMPLETED
            and event.params.get("threadId") == root
            and isinstance(event.params.get("turn"), Mapping)
            and event.params["turn"].get("id") == turn_id
        )
        if completed_ours:
            # The observer and the pump read the same stream; either may see the end first.
            turn = Turn.model_validate(event.params["turn"])
            state = session.turns.setdefault(turn.id, _TurnState(turn.id))
            state.status = turn.status
            if history_from is None:
                state.completed_at = (epoch, event.seq)
            state.last_agent_text = framing.agent_text(turn.items) or state.last_agent_text
            state.done.set()
            if session.active_turn == turn.id:
                session.active_turn = None
        observations = framing.observations_for(
            event,
            root_thread_id=root,
            counter=self._counter,
            # Live events carry the connection epoch; history replays keep stable keys.
            epoch=epoch if history_from is None else None,
        )
        if event.method == N_USAGE_UPDATED and event.params.get("threadId") == root:
            note = TokenUsageNotification.model_validate(event.params)
            attribution = session.usage_tracker.record(
                note.turn_id, note.token_usage, epoch=epoch, seq=event.seq
            )
            observations = (
                *observations,
                framing.attributed_usage_observation(observations[0], attribution),
            )
        frames: list[LaneFrame] = []
        for index, observation in enumerate(observations):
            if history_from is not None:
                cursor = framing.history_cursor(turn_id, epoch, history_from + index + 1)
            elif index < len(observations) - 1:
                # Failure B: one event, several frames (`turn/completed` -> TURN_ENDED and the
                # terminal RUN_RESULT). A segment may end between them, so every frame but the
                # last resumes BEFORE the event, past the frames already taken: the next
                # segment re-reads the event instead of skipping the rest of it.
                cursor = framing.composite_cursor(turn_id, epoch, event.seq, index + 1)
            else:
                cursor = framing.composite_cursor(turn_id, epoch, event.seq)
            terminal = completed_ours and observation.raw_kind.endswith(framing.RESULT_SUFFIX)
            frame = framing.lane_frame(
                observation,
                harness_execution_id=request.harness_execution_id,
                generation=request.generation,
                cursor=cursor,
                terminal=terminal,
            )
            self._remember_cursor(frame.provider_key, cursor)
            frames.append(frame)
        return frames

    @staticmethod
    def _observed(session: _Session, epoch: str, seq: int) -> None:
        """Every frame of the event at `seq` was taken (the consumer asked for more)."""

        if seq > session.observed_through.get(epoch, 0):
            session.observed_through[epoch] = seq

    @staticmethod
    def _completion_ahead(state: _TurnState, connection: AppServerConnection, after: int) -> bool:
        """Whether this connection still holds the turn's `turn/completed` after `after`."""

        if state.completed_at is None:
            return False
        epoch, seq = state.completed_at
        return epoch == connection.epoch and seq > after and seq >= connection.first_seq

    async def observe(self, request: ObserveRequest) -> AsyncIterator[LaneFrame]:
        session = self._session(request)
        turn_id = request.turn.native_turn_ref
        if turn_id is None:
            raise NativeTurnLost("no native turn to observe")
        thread_id = request.turn.session.native_session_ref or session.thread_id
        connection = await self._ensure_connection(session, request, thread_id)
        epoch = connection.epoch
        parsed = framing.parse_cursor(request.after)
        if parsed is not None and parsed.turn_id != turn_id:
            # Another turn's position (the previous turn of a continuing segment) says
            # nothing about where this turn's events start.
            parsed = None
        state = session.turns.get(turn_id)
        start_seq, skip = 0, 0
        # Live: frames of one event a previous segment already took (`<seq>/<k>` cursors).
        partial: tuple[int, int] | None = None
        if parsed is not None and parsed.history is not None:
            # Paging through the thread history (positions belong to the thread).
            resync, skip = True, parsed.history
        elif parsed is not None and parsed.epoch == epoch:
            resync, start_seq = False, parsed.resume_after
            if parsed.taken:
                partial = (parsed.seq, parsed.taken)
        elif parsed is None and state is not None and state.started_epoch == epoch:
            # Unresolved 7: a turn started on this connection is observed from just before
            # its `turn/start`, or from the first event no observer took yet (a compaction
            # between turns), never by replaying the whole connection buffer again.
            floor = session.observed_through.get(epoch, 0)
            resync, start_seq = False, min(state.start_seq, floor)
        else:
            # A cursor of another app-server launch, or no state: history first.
            resync = True
        if (
            not resync
            and state is not None
            and state.terminal
            and not self._completion_ahead(state, connection, start_seq)
        ):
            # The turn is finished and this connection will not deliver its completion after
            # the cursor (passed, or another launch saw it): never wait on a finished turn.
            resync = True
        emitted = 0
        while True:
            if resync:
                thread = await self._read_thread(session, connection, include_turns=True)
                history = next((turn for turn in thread.turns if turn.id == turn_id), None)
                if history is None:
                    raise NativeTurnLost(f"turn {turn_id} is not in thread {thread.id} history")
                self._absorb_history(session, thread, epoch)
                events = [
                    framing.item_completed_event(0, thread.id, turn_id, item)
                    for item in history.items
                ]
                if history.terminal:
                    events.append(framing.turn_completed_event(0, thread.id, history.wire()))
                position = 0
                for event in events:
                    frames = self._frames_of(
                        session, request, event, epoch, turn_id, history_from=position
                    )
                    for frame in frames:
                        position += 1
                        if position <= skip and not frame.terminal:
                            continue  # taken by an earlier segment
                        yield self._yielding(turn_id, frame)
                        emitted += 1
                        if frame.terminal:
                            return
                        if emitted >= request.max_frames:
                            return
                # Live from the retained buffer: what the history snapshot missed (deduped).
                resync, skip, start_seq = False, 0, max(connection.first_seq - 1, 0)
            try:
                async for event in connection.events(start_seq):
                    frames = self._frames_of(session, request, event, epoch, turn_id)
                    if partial is not None and event.seq == partial[0]:
                        # Taken by the previous segment (a terminal frame is always last).
                        frames = frames[partial[1] :]
                    partial = None
                    for frame in frames:
                        yield self._yielding(turn_id, frame)
                        emitted += 1
                        if frame.terminal:
                            return
                    # Resumed after the event's last frame: the consumer took all of them.
                    self._observed(session, epoch, event.seq)
                    if emitted >= request.max_frames:
                        return
            except CursorExpired:
                resync, skip, partial = True, 0, None
                continue
            except TransportClosed as closed:
                # The app-server is gone: the segment ends here; the next one reattaches.
                session.connection_lost = closed.reason
                _LOGGER.warning("codex app-server connection ended: %s", closed.reason)
                return

    # --- closing facts, status, usage ---------------------------------------------------------

    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts:
        body = frame.body if isinstance(frame.body, Mapping) else {}
        raw = body.get("turn")
        parsed = (
            Turn.model_validate(raw)
            if isinstance(raw, Mapping)
            else Turn(id=turn.native_turn_ref or "?", status="failed")
        )
        session = self._sessions.get(turn.session.harness_execution_id)
        state = session.turns.get(parsed.id) if session is not None else None
        facts = framing.closing_facts(
            parsed,
            usage=state.usage if state is not None else None,
            last_agent_text=state.last_agent_text if state is not None else None,
            model=session.model if session is not None else None,
            attributed_usage=session.usage_tracker.report(parsed.id)
            if session is not None
            else None,
        )
        if facts.native_status != "finished" or session is None or session.lease is None:
            return facts
        # A native `finished` is never acceptance: the declared outputs must be on disk
        # (FT-G4, as the other worker-hosted lanes; MP-12 continues a session that lacks them).
        declared = declared_outputs(session.operation, mount_root=self._settings.mount_root)
        root = Path(session.lease.path)
        missing = tuple(path for path in declared if not (root / path).is_file())
        return facts.model_copy(update={"missing_outputs": missing}) if missing else facts

    async def status(self, request: StatusRequest) -> ProviderStatus:
        session = self._session(request)
        thread_id = request.session.native_session_ref or session.thread_id
        connection = await self._ensure_connection(session, request, thread_id)
        turn_id = request.turn.native_turn_ref if request.turn is not None else None
        state = session.turns.get(turn_id) if turn_id is not None else None
        thread = await self._read_thread(
            session, connection, include_turns=state is None and turn_id is not None
        )
        if turn_id is not None and state is None:
            self._absorb_history(session, thread, connection.epoch)
            state = session.turns.get(turn_id)
            if state is None:
                raise NativeTurnLost(f"turn {turn_id} is not known to thread {thread.id}")
        idle = thread.status.type == "idle"
        if state is None:
            return ProviderStatus(status=thread.status.type, terminal=False, idle=idle)
        return ProviderStatus(
            status=state.status,
            terminal=state.terminal,
            idle=idle or state.terminal,
            usage=session.usage_tracker.report(turn_id),
        )

    async def usage(self, request: UsageRequest) -> UsageReport:
        """Usage attributable to this native turn; an unobserved baseline stays unknown."""

        session = self._session(request)
        turn_id = request.turn.native_turn_ref if request.turn is not None else None
        if turn_id is None:
            return UsageReport(disposition="unknown")
        if session.connection is not None:
            await self._pump_caught_up(session, session.connection)
        return session.usage_tracker.report(turn_id)

    # --- MP-12: explicit compaction and context occupancy -------------------------------------

    async def compact(self, request: CompactionRequest) -> CompactionReceipt:
        """`CompactingLane`: `thread/compact/start` on an idle thread, serialized with turn
        admission, then a bounded wait for the provider's own completion report.

        DRILL (docs/qualification/lanes/codex/README.md step 5) must verify on codex-cli
        0.162.0: that `thread/compact/start` on an idle thread is accepted and refused (typed
        error) while a turn is active; which completion the server emits (`thread/compacted`,
        deprecated, and/or an `item/completed` with a `contextCompaction` item) and its
        `turnId`; how long a compaction takes (`compaction_timeout_s`); whether a
        `thread/tokenUsage/updated` follows it (the remeasured occupancy); and that the next
        `turn/start` continues the same thread with the compacted context.
        """

        session = self._sessions.get(request.harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {request.harness_execution_id} is not staged")
        thread_id = session.thread_id or request.session.native_session_ref
        connection = session.connection
        if connection is None or thread_id is None:
            return CompactionReceipt(completed=False, detail="no live app-server to compact")
        async with session.admission_lock:
            await self._pump_caught_up(session, connection)
            if session.active_turn is not None:
                return CompactionReceipt(
                    completed=False,
                    detail="a turn is active; compaction waits for the turn boundary",
                )
            try:
                thread = await self._read_thread(session, connection, include_turns=False)
                if thread.status.type != "idle":
                    return CompactionReceipt(
                        completed=False,
                        detail=f"thread is {thread.status.type}; compaction needs an idle thread",
                    )
                seq_before = connection.last_seq
                await connection.request(
                    M_THREAD_COMPACT_START,
                    ThreadCompactStartParams(thread_id=thread_id).params(),
                )
            except AppServerError as error:
                return CompactionReceipt(
                    completed=False, detail=f"refused ({error.code}): {error.message}"[:512]
                )
            except (ResponseLost, TransportClosed) as error:
                return CompactionReceipt(completed=False, detail=str(error)[:512])
            seen = await self._await_compaction(connection, thread_id, seq_before)
            if seen is None:
                return CompactionReceipt(
                    completed=False,
                    detail=(
                        f"no thread/compacted or contextCompaction item within "
                        f"{self._settings.compaction_timeout_s:g}s"
                    ),
                )
            seq, usage = seen
            occupancy = framing.occupancy_from_usage(usage) if usage is not None else None
            return CompactionReceipt(
                completed=True,
                native_ref=f"{thread_id}@{connection.epoch}:{seq}"[:1_024],
                occupancy_after=occupancy if occupancy is not None and occupancy.known else None,
                detail=f"epoch {request.epoch}: compaction reported by the app-server",
            )

    async def _await_compaction(
        self, connection: AppServerConnection, thread_id: str, seq_before: int
    ) -> tuple[int, ThreadTokenUsage | None] | None:
        """The sequence of the first compaction report for `thread_id` after `seq_before`
        (and a token usage update seen after it, if any), or None on timeout/disconnect."""

        found: int | None = None
        usage: ThreadTokenUsage | None = None
        try:
            async with asyncio.timeout(self._settings.compaction_timeout_s):
                async for event in connection.events(max(seq_before, connection.first_seq - 1)):
                    params = event.params
                    if params.get("threadId") != thread_id:
                        continue
                    item = params.get("item")
                    if event.method == N_THREAD_COMPACTED or (
                        event.method == N_ITEM_COMPLETED
                        and isinstance(item, Mapping)
                        and item.get("type") == "contextCompaction"
                    ):
                        found = event.seq if found is None else found
                        break
        except (TimeoutError, TransportClosed, CursorExpired):
            return None
        if found is None:
            return None
        for event in connection.buffered(found):
            if event.method == N_USAGE_UPDATED and event.params.get("threadId") == thread_id:
                usage = TokenUsageNotification.model_validate(event.params).token_usage
        return found, usage

    async def context_occupancy(
        self, harness_execution_id: str, session: SessionHandle, turn: TurnHandle | None
    ) -> ContextOccupancy | None:
        """`ContextOccupancyLane`: the last `thread/tokenUsage/updated` of the session against
        its `modelContextWindow` (never the cumulative total); `unknown` without a window,
        before any usage update, or after a compaction until the next update reports the
        compacted context."""

        del session, turn
        staged = self._sessions.get(harness_execution_id)
        if staged is None:
            return ContextOccupancy.unknown("the session is not staged on this worker")
        connection = staged.connection
        if connection is not None:
            await self._pump_caught_up(staged, connection)
        if staged.last_usage is not None and staged.compaction_clock > staged.usage_clock:
            return ContextOccupancy.unknown(
                "compacted since the last thread/tokenUsage/updated; not remeasured yet"
            )
        return framing.occupancy_from_usage(staged.last_usage)

    # --- MP-12 continuation: a fresh thread on a fresh app-server ------------------------------

    async def hydrate_session(
        self,
        harness_execution_id: str,
        *,
        transfer_id: str,
        prompt_text: str,
        source_session_ref: str,
    ) -> SessionHandover:
        """Start a *fresh* app-server and a fresh `thread/start` in the same lease (no
        `thread/resume` of the source, no `thread/fork`: nothing of the source conversation is
        claimed to carry over; the sealed continuation packet is the only carrier), stage the
        continuation turn's text and offer the handover. The source connection keeps running
        until its turn boundary; the next `lane.turn` (or the in-segment handover) sends the
        continuation turn to the target and adopts it. Idempotent per transfer.

        DRILL: a thread created by `thread/start` but given no turn yet must survive an
        app-server restart (`thread/resume`) for a target hydrated before a worker loss.
        """

        session = self._sessions.get(harness_execution_id)
        if session is None:
            raise NativeTurnLost(f"harness execution {harness_execution_id} is not staged")
        pending = session.pending
        if pending is not None:
            if pending.handover.transfer_id == transfer_id:
                return pending.handover
            raise NativeTurnLost(
                f"continuation {pending.handover.transfer_id} is hydrated and not adopted yet"
            )
        if session.thread_id != source_session_ref or session.lease is None:
            raise NativeTurnLost(f"thread {source_session_ref} is not live in this process")
        launched = await self._spawn(session)
        try:
            response = ThreadStartResponse.model_validate(
                await launched.connection.request(
                    M_THREAD_START, self._thread_start_params(session)
                )
            )
        except BaseException:
            with suppress(Exception):
                await launched.terminate()
            raise
        target = response.thread.id
        instruction_ref = continuation_instruction_ref(transfer_id)
        self.stage_turn(harness_execution_id, instruction_ref, prompt_text)
        details = {
            "codex_cli_version": launched.versions.get("codex_cli", ""),
            "codex_home": str(session.codex_home or ""),
            "app_server_epoch": launched.connection.epoch,
            "app_server_schema_sha256": PINNED_SCHEMA_SHA256,
            "conversation": "fresh",
            **(session.network.native_details() if session.network is not None else {}),
        }
        handover = SessionHandover(
            transfer_id=transfer_id,
            session=SessionHandle(
                lane_profile=PROFILE,
                harness_execution_id=harness_execution_id,
                generation=session.identity.attempt_no,
                native_session_ref=target,
                native_details={key: value for key, value in details.items() if value},
            ),
            instruction_ref=instruction_ref,
            source_session_ref=source_session_ref,
        )
        session.pending = _PendingHandover(
            handover=handover,
            launched=launched,
            thread_id=target,
            model=response.model or response.thread.model,
        )
        return handover

    async def _adopt(self, session: _Session) -> None:
        """The hydrated target becomes the session: the source app-server is terminated
        (its turn is finished; its live approval correlations become `lost`)."""

        pending = session.pending
        if pending is None:
            return
        await self._terminate(session, with_pending=False)
        session.pending = None
        session.thread_id = pending.thread_id
        session.usage_tracker.start_thread(pending.thread_id)
        session.thread_status = "idle"
        session.active_turn = None
        session.model = pending.model or session.model
        await self._attach(session, pending.launched)

    async def pending_handover(self, harness_execution_id: str) -> SessionHandover | None:
        session = self._sessions.get(harness_execution_id)
        if session is None or session.pending is None:
            return None
        return session.pending.handover

    async def complete_handover(self, harness_execution_id: str, transfer_id: str) -> None:
        session = self._sessions.get(harness_execution_id)
        if session is None or session.pending is None:
            return
        if session.pending.handover.transfer_id == transfer_id:
            await self._adopt(session)

    async def workspace_patch(self, harness_execution_id: str) -> bytes:
        """The lease's git patch, excluding the projection and the lane's state root
        (`.mission/state/codex/**`, which holds `CODEX_HOME`)."""

        session = self._sessions.get(harness_execution_id)
        if session is None or session.lease is None:
            raise NativeTurnLost(f"harness execution {harness_execution_id} holds no lease")
        patch = await self._leaser.capture_patch(session.lease, exclude=self._excluded(session))
        return bytes(getattr(patch, "diff", b"") or b"")

    # --- dispatch reconciliation ----------------------------------------------------------------

    async def reconcile_dispatch(
        self, record: DispatchRecord, *, session: SessionHandle | None
    ) -> DispatchLookup:
        staged = self._sessions.get(session.harness_execution_id) if session is not None else None
        if staged is None and session is not None:
            return DispatchLookup(outcome="unknown", detail="session is not staged on this worker")
        if record.kind == "create":
            if staged is not None and staged.thread_id is not None:
                return DispatchLookup(outcome="found", native_ref=staged.thread_id)
            return DispatchLookup(outcome="unknown", detail="no thread identity was recorded")
        assert staged is not None and session is not None
        known = staged.sent.get(record.idempotency_key)
        if known is not None:
            return DispatchLookup(outcome="found", native_ref=known)
        thread_id = session.native_session_ref or staged.thread_id
        if thread_id is None:
            return DispatchLookup(outcome="unknown", detail="no thread to read")
        try:
            connection = await self._ensure_connection(
                staged,
                ReattachRequest(
                    scope=harness_scope(staged.identity.request_scope, "codex-reconcile"),
                    lane_profile=PROFILE,
                    harness_execution_id=session.harness_execution_id,
                    binding_digest=staged.binding_digest
                    or execution_binding_digest(staged.operation),
                    idempotency_key=f"{session.harness_execution_id}:reconcile",
                    generation=session.generation,
                    native_session_ref=thread_id,
                ),
                thread_id,
            )
            thread = await self._read_thread(staged, connection, include_turns=True)
        except (NativeTurnLost, AppServerError, ResponseLost, TransportClosed) as error:
            return DispatchLookup(outcome="unknown", detail=str(error)[:512])
        self._absorb_history(staged, thread, connection.epoch)
        for turn in thread.turns:
            for item in turn.items:
                if item.get("type") == "userMessage" and item.get("clientId") == (
                    record.idempotency_key
                ):
                    staged.sent[record.idempotency_key] = turn.id
                    return DispatchLookup(outcome="found", native_ref=turn.id)
        if thread.status.type == "idle":
            return DispatchLookup(
                outcome="not_received", detail="thread history holds no user message for the key"
            )
        return DispatchLookup(
            outcome="unknown", detail=f"thread is {thread.status.type}; history inconclusive"
        )

    # --- snapshot, end -------------------------------------------------------------------------

    def _excluded(self, session: _Session) -> tuple[str, ...]:
        kernel = (KERNEL_HOOK_PATH, HOOK_CONTEXT_PATH, TOKEN_PATH) if session.kernel_hooks else ()
        return (*session.projection_paths, STATE_DIR, *kernel)

    async def _freeze(
        self, session: _Session, request: HarnessRequest, reason: str
    ) -> tuple[str, str]:
        """Store the git patch and an `mc.workspace_snapshot.v1`: (patch_ref, snapshot_ref)."""

        assert session.lease is not None
        lease = session.lease
        patch = await self._leaser.capture_patch(lease, exclude=self._excluded(session))
        scope = session.identity.request_scope
        prefix = f"codex-local/{request.harness_execution_id}/{request.generation}"
        patch_ref = await self._artifacts.stage(
            request_scope=scope,
            name=f"{prefix}/patch.diff",
            content=bytes(getattr(patch, "diff", b"") or b""),
            media_type="text/x-diff",
        )
        untracked = tuple(getattr(patch, "untracked", ()) or ())
        snapshot = WorkspaceSnapshot(
            lane_profile=PROFILE,
            base_commit=lease.base_commit,
            branch=lease.branch,
            patch_artifact_ref=patch_ref,
            exclusions=self._excluded(session),
            manifest_digest=sha256_digest(
                {"patch": patch_ref, "untracked": list(untracked), "reason": reason}
            ),
            producer_lease_id=str(lease.lease_id),
            producer_generation=request.generation,
            captured_at=self._clock(),
            emulated=True,
        )
        snapshot_ref = await self._artifacts.stage(
            request_scope=scope,
            name=f"{prefix}/workspace-snapshot.json",
            content=snapshot.model_dump_json().encode("utf-8"),
            media_type="application/json",
        )
        return patch_ref, snapshot_ref

    async def snapshot(self, request: SnapshotRequest) -> SnapshotManifest:
        session = self._session(request)
        if session.lease is None:
            raise ValueError("no leased workspace to snapshot")
        patch_ref, snapshot_ref = await self._freeze(session, request, request.reason)
        refs = (patch_ref, snapshot_ref)
        return SnapshotManifest(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            kind="git_patch",
            refs=refs,
            emulated=True,
            digest=sha256_digest(list(refs)),
        )

    async def _terminate(self, session: _Session, *, with_pending: bool = True) -> None:
        if with_pending and session.pending is not None:
            with suppress(Exception):
                await session.pending.launched.terminate()
            session.pending = None
        # Pending approval waits die with their connection: their correlations stay live
        # until the next launch's `recover` marks them lost (never reused).
        for task in tuple(session.approval_tasks):
            task.cancel()
        for task in tuple(session.approval_tasks):
            with suppress(asyncio.CancelledError, Exception):
                await task
        if session.pump is not None:
            session.pump.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await session.pump
            session.pump = None
        if session.launched is not None:
            with suppress(Exception):
                await session.launched.terminate()
            session.launched = None

    async def _revoke_hook_token(self, session: _Session) -> None:
        if self._hooks is not None and session.token_context is not None:
            await self._hooks.revoke(session.token_context)
            session.token_context = None

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
            await self._terminate(session)
            await self._revoke_hook_token(session)
            self._sessions.pop(request.harness_execution_id, None)
            return CleanupReceipt(released=False)
        await asyncio.to_thread(restore_repository_files, session.root)
        patch_ref, snapshot_ref = await self._freeze(
            session, request, f"end_session:{request.reason}"
        )
        outputs: list[str] = [snapshot_ref]
        for path, content in await self._leaser.outputs(session.lease):
            registered = (
                await self._outputs.register(
                    session.operation, path, content, mount_root=self._settings.mount_root
                )
                if self._outputs is not None
                else None
            )
            outputs.append(
                registered
                or await self._artifacts.stage(
                    request_scope=session.identity.request_scope,
                    name=f"codex-local/{request.harness_execution_id}/{path}",
                    content=content,
                    media_type="application/octet-stream",
                )
            )
        await self._terminate(session)
        await self._revoke_hook_token(session)
        # The lease is released only after the patch is stored.
        await self._leaser.release(
            session.lease,
            patch_artifact_ref=patch_ref,
            snapshot_ref=snapshot_ref,
            exclude=self._excluded(session),
        )
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

    # --- introspection for tests and the continuation hydrator ----------------------------------

    def live_session(self, thread_id: str) -> str | None:
        for harness_execution_id, session in self._sessions.items():
            if session.thread_id == thread_id and session.lease is not None:
                return harness_execution_id
        return None

    def lease_path(self, harness_execution_id: str) -> str:
        return str(self._sessions[harness_execution_id].root)

    def active_turn(self, harness_execution_id: str) -> str | None:
        session = self._sessions.get(harness_execution_id)
        return None if session is None else session.active_turn

    def turn_status(self, harness_execution_id: str, turn_id: str) -> str | None:
        session = self._sessions.get(harness_execution_id)
        if session is None or turn_id not in session.turns:
            return None
        return session.turns[turn_id].status

    def outputs_dir(self, harness_execution_id: str) -> Path:
        return self._sessions[harness_execution_id].root / OUTPUTS_DIR


__all__ = [
    "CODEX_HOME_DIR",
    "DEFAULT_HOOK_CALLBACK_BASE_URL",
    "PROFILE",
    "STATE_DIR",
    "ArtifactSink",
    "AuthAdmissionSource",
    "CodexLocalHarness",
    "CodexLocalSettings",
    "WorkspaceLeaser",
    "admitted_approval_policy",
    "declared_outputs",
    "execution_binding_digest",
    "network_overrides",
    "network_projection",
    "trust_config_toml",
    "trust_override",
]
