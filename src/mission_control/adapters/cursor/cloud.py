"""The `cursor_cloud` Lane Profile: Cursor Cloud Agents API v1 (SPEC-07 section 6; FT-G5).

One Session Turn of a bound operation, driven by `lane.turn` (FT-G2):

- `prepare` pushes branch `mc/<run_id>` from the binding's base ref carrying the Host
  Projection (rules, agents, command hooks, MCP; cloud agents read project config from the
  repository), layered over the base ref's own files under the binding's `materialization`
  policy (MO-02: the repository's `AGENTS.md` stays, its `.cursor/hooks.json` and
  `.cursor/mcp.json` are merged; a refused conflict is `MATERIALIZATION_CONFLICT`), and the
  Context Packet files, records the branch head and, when a
  `WorkspaceAllocator` is composed, the provider workspace lease (MP-04 `provider_workspace`
  policy: Mission Control holds the fenced record of branch and base commit). The commit is
  refused when it carries one of the run's secret values (MO-11 pre-commit scan). When the
  binding names a provider environment strategy (MO-13), the committed
  `.cursor/environment.json` on the default branch is checked first (a foreign file is refused
  unless bound), a `sync` provisions the kit's environment and its secrets by name, and the run
  branch carries the kit's mission layer (`.mission/setup/run`) for the environment's `start`;
- `start` creates the agent with a client-supplied `agentId` (`409 agent_id_conflict` means it
  already exists: reattach) or, when the binding needs `envVars`, with an `Idempotency-Key`
  (the envVars resolve through the Secret Broker and are checked against Cursor's limits);
  `metadata` that the account cannot use (`403 feature_unavailable`) is recorded, not fatal.
  The agent works on the pre-created branch (`startingRef` plus `workOnCurrentBranch`). The
  create request enqueues the first run, so turn 1 is that run;
- `send_turn` for later turns returns `busy` on `409 agent_busy` (`wait_then_send`,
  ADR-0030: the agent's own active run is a scheduling condition the workflow waits out at
  the boundary, never a send retry); a `429` is `ProviderCapacityLimited` (MP-05/06: the
  dispatch is journaled `declined`, the workflow waits on a Temporal timer, nothing is
  re-sent here);
- `observe` reads the run's SSE stream with `Last-Event-ID`: frames are keyed by the event id,
  the id-less leading `status` is deduplicated by content, heartbeats are not persisted, the
  retention header is recorded. After `410 stream_expired` the lane writes one `stream.expired`
  status frame, remembers the run as expired, and reconciles the terminal state from
  `GET .../runs/{runId}` (a `run.final` frame that names `observation.stream = "expired"`
  separately from the run's own `FINISHED` / `ERROR`); a run still running after expiry is
  polled through the run record at a bounded interval, with a status frame per change;
- `reconcile_dispatch` (MP-06 `DispatchReconcilingLane`): a journaled create is looked up by
  its deterministic client `agentId` (`404` is the provider's authoritative "not received"),
  a journaled send by the agent's `latestRunId` against the runs this lane acknowledged
  (the create enqueues turn 1; a later run that is not one of ours was accepted; the latest
  run being one of ours cannot rule out an in-flight lost send); anything the lane cannot
  anchor stays `unknown` and parks `in_doubt`;
- closing facts keep `git.branches[]` only when the agent's `latestRunId` is this run;
- `usage` settles tokens from `/usage?runId=` only when the API reports this run's usage, and
  cost only when a cost reader reports it; otherwise the usage stays `unknown`;
- `end_session` fetches the branch diff from the SCM as the patch, downloads artifacts through
  their presigned URLs and registers them with digests, records the branch head as the
  provider workspace snapshot (`branch:<branch>@<sha>`, the producer ADR-0037 asked for) and
  as a `mc.mission_branch_head.v1` head SHA artifact (MO-14), releases the lease after that
  custody, then archives the agent.

The provider-neutral machinery (staging, the stream-then-reconcile observe loop, dispatch
reconciliation routing and turn anchors, later-turn texts and the handover offer, the `429`
signal, usage settled only when reported, the provider workspace custody) is the Remote Session
Lane base in `adapters/remote_session/` (ADR-0052); this module supplies the Cloud Agents
mappings, the event classifier, the run-record reader and the Cursor wording.

Kernel Hooks cannot call the worker's loopback listener from the cloud VM, so the cloud
projection carries catalog command hooks only; an immediate cancel reaches the agent through
`POST .../cancel`. Qualification stays false until a recorded live drill (FT-G6 / OVE-55).

FT-G6 controls (SPEC-07 section 7, the describe-honesty suite): SSE events are keyed and
cursored per run (`sse:<run>:<id>`, cursor `<run>@<id>`), so a replacement or continuation
run never resumes with another run's `Last-Event-ID` (`400 invalid_last_event_id`) and never
collides with its frames; a later turn's text is staged by its instruction ref
(`cancel_and_replace` replacement, continuation prompt); `snapshot` names the branch's current
head (`branch:<branch>@<sha>`) and a fork's `prepare` publishes the derived run's branch from
it; a continuation commits the checkpoint packet's files to the branch and creates a fresh
agent on it (`CursorCloudSessionHydrator` in `adapters/cursor/controls.py`), whose first run is
the next turn.

A reattach after a lost worker rehydrates what the process no longer holds (MP-09 option
rehydration): the run branch from the remote (never re-published), the Host Projection paths
the patch excludes, the provider workspace lease (re-acquired by the same holder) and the
last acknowledged run as the reconcile anchor. Cloud agent options (`customSubagents`,
model, mode) live on the agent record itself and travel on every create, continuation creates
included. Cloud ignores `.cursor/mcp.json` and does not persist inline MCP servers, so the
projection's `mcpServers` travel on every create and every follow-up run (MO-30).
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from mission_control.adapters.cursor.bridge import (
    AgentArchived,
    AgentBusy,
    BridgeError,
    FeatureUnavailable,
    RunNotCancellable,
    RunNotFound,
)
from mission_control.adapters.cursor.cloud_api import (
    AgentIdConflict,
    AgentNotFound,
    CloudAgentsClient,
    CloudCapacityLimited,
)
from mission_control.adapters.cursor.cognition_points import cursor_turn_points
from mission_control.adapters.cursor.describe import CURSOR_CLOUD_DESCRIBE
from mission_control.adapters.cursor.discovery import committed_expectation
from mission_control.adapters.cursor.environments import (
    ENVIRONMENT_FILE,
    CursorEnvironmentProvisioner,
    ProvisionedEnvironment,
)
from mission_control.adapters.cursor.frames import closing_facts as body_closing_facts
from mission_control.adapters.cursor.frames import first
from mission_control.adapters.cursor.local import LaneArtifactSink, declared_outputs
from mission_control.adapters.cursor.projection import (
    network_projection,
    projection_digests,
    verify_projection,
)
from mission_control.adapters.cursor.scm import GitBranchPublisher, PublishedBranch
from mission_control.adapters.cursor.secrets import launch_env_vars
from mission_control.adapters.cursor.time_travel import SEED_SNAPSHOT_REF, SEED_TRANSCRIPT_REF
from mission_control.adapters.cursor.usage import CursorNativeRunUsage, cursor_token_usage
from mission_control.adapters.remote_session.custody import (
    ProviderWorkspaceCustody,
    parse_branch_snapshot,
)
from mission_control.adapters.remote_session.dispatch import (
    AnchorDetails,
    DispatchKeyParts,
    client_session_id,
    parse_dispatch_key,
)
from mission_control.adapters.remote_session.lane import (
    RECORD_POLL_INTERVAL_S,
    RECORD_POLL_LIMIT,
    Classified,
    ObservationNames,
    RemoteSession,
    RemoteSessionLane,
)
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import STREAM_START, StreamOpened
from mission_control.application.agentic_components.layering import (
    MATERIALIZATION_CONFLICT,
    LayeredProjection,
    LayeringRefused,
    TreeView,
    layer_projection,
    repository_roots,
)
from mission_control.application.agentic_components.placement import (
    DurableInputReader,
    LaneProjectionError,
    ProjectionSource,
    safe_relative,
    turn_text,
)
from mission_control.application.effects.branch_heads import (
    MissionBranchHead,
    record_branch_head,
)
from mission_control.application.environments.provider_environments import (
    ProviderEnvironmentRefused,
)
from mission_control.application.execution.harness.controls import SessionHandover
from mission_control.application.execution.harness.dispatch import DispatchLookup, DispatchRecord
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.execution.harness.points import TurnPointsRequest
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.application.execution.operations.lane_outputs import LaneOutputCustody
from mission_control.application.frames.kinds import cursor_cloud_final_key
from mission_control.application.workspaces.cloud_branches import (
    FETCH_INPUTS_SCRIPT,
    RUNTIME_INPUT_URLS,
    cloud_packet,
    mission_branch,
    runtime_input_urls,
)
from mission_control.application.workspaces.service import WorkspaceAllocator
from mission_control.application.workspaces.snapshots import CapturedSnapshot, branch_snapshot_ref
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.authoring.canonical import sha256_digest, stable_json_digest
from mission_control.domain.context.render import INPUTS_MANIFEST_PATH, bytes_digest
from mission_control.domain.context.snapshot_evidence import (
    CONVERSATION_MEDIA_TYPE,
    ConversationEnvelope,
    ConversationEvidence,
    ConversationOrigin,
)
from mission_control.domain.execution.bindings import WorkspacePolicyPin
from mission_control.domain.execution.cognition_points import CognitionPointObservation
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.history_reconciliation import (
    HistoryReplayComplete,
    HistoryReplayIncomplete,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
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

PROFILE: Final = "cursor_cloud"
_AGENT_NAMESPACE = UUID("8d6c1b2a-4f3e-4b5d-9a7c-0e1f2d3c4b5a")
_TERMINAL: Final = frozenset({"finished", "error", "cancelled", "expired"})
_REF_CHARS = re.compile(r"[^A-Za-z0-9._/-]")
# After `410 stream_expired` a run that is still running is reconciled through the run record
# at this cadence, at most this many times per observe call (the segment bound still applies).
EXPIRED_POLL_INTERVAL_S: Final = RECORD_POLL_INTERVAL_S
EXPIRED_POLL_LIMIT: Final = RECORD_POLL_LIMIT
# Each execution unit owns a branch; successive generations may reattach to that unit.
CURSOR_CLOUD_POLICY: Final = WorkspacePolicyPin(
    mode="provider_workspace",
    reuse="within_session",
    dirty_input="reject",
    cleanup="retain_until_artifacts_registered",
)

CloudEnvResolver = Callable[[str], Awaitable[Mapping[str, str]]]
SignalEnvironment = Callable[
    [OperationExecutionRequest, LaneExecutionIdentity], Awaitable[Mapping[str, str]]
]
CloudCostReader = Callable[[str, str], Awaitable[int | None]]


def client_agent_id(harness_execution_id: str, generation: int) -> str:
    """The deterministic `bc-<uuid>` a create sends, so a lost response never duplicates."""

    return client_session_id(_AGENT_NAMESPACE, harness_execution_id, generation, prefix="bc-")


def run_branch(binding: CursorExecutionBinding, run_id: str, unit_id: str | None = None) -> str:
    if unit_id is None:
        return binding.workspace.branch_prefix + _REF_CHARS.sub("-", run_id)
    return mission_branch(run_id, unit_id, prefix=binding.workspace.branch_prefix)


CHECKPOINT_INVALID: Final = "CHECKPOINT_INVALID"
# The repository's default branch: a bare mirror's `HEAD` is the remote's default branch.
DEFAULT_BRANCH_REF: Final = "HEAD"
# The Cloud Agents words: runs (not turns), the run record, `runId`, camelCase token fields.
_NAMES: Final = ObservationNames(
    record_source="run_record", final_kind="run.final", status_key="run-status"
)
_ANCHOR_DETAILS: Final = AnchorDetails(
    unanchored="no acknowledged run anchors this agent; the lost send cannot be told apart "
    "from an earlier turn",
    no_latest="the agent reports no latest run",
    acknowledged="the latest run is already acknowledged; the lost send may still be in flight",
)


def _status(value: Any) -> str:
    return str(value or "").lower()


@dataclass(kw_only=True)
class _CloudSession(RemoteSession):
    """`session_ref` is the cloud agent id; its turns are runs."""

    binding: CursorExecutionBinding
    projection: HostProjection | None = None
    branch: PublishedBranch | None = None
    initial_run_id: str | None = None
    # FT-G6: each hydrated continuation agent's first run (its create enqueued it).
    first_runs: dict[str, str] = field(default_factory=dict)
    metadata: str = "sent"
    forked_from: str | None = None
    # MP-09: the provider workspace lease and its last recorded custody.
    lease: WorkspaceLease | None = None
    custody: CapturedSnapshot | None = None
    # MO-11: the binding's launch envVars, resolved through the Secret Broker once per process.
    env_vars: dict[str, str] | None = field(default=None, repr=False)
    # MO-13: the provider environment the agent runs in, as `prepare` applied it.
    environment: ProvisionedEnvironment | None = None
    # Cross-provider control (2026-11-05): the fork seed's reconstructed transcript, the
    # prefix of the derived agent's first run prompt (the hydration turn).
    seed_hydration: str | None = None


class CursorCloudHarness(CursorNativeRunUsage, RemoteSessionLane[_CloudSession]):
    """`cursor_cloud` Session Lane over `CloudAgentsClient` (an HTTP fake in tests)."""

    profile = PROFILE
    terminal_statuses = _TERMINAL
    names = _NAMES

    def __init__(
        self,
        *,
        client: CloudAgentsClient,
        publisher: GitBranchPublisher,
        projections: ProjectionSource,
        artifacts: LaneArtifactSink,
        inputs: DurableInputReader | None = None,
        env_resolver: CloudEnvResolver | None = None,
        signal_environment: SignalEnvironment | None = None,
        cost_reader: CloudCostReader | None = None,
        archive_on_end: bool = True,
        describe: LaneDescribe = CURSOR_CLOUD_DESCRIBE,
        workspaces: WorkspaceAllocator | None = None,
        clock: Callable[[], datetime] | None = None,
        expired_poll_interval_s: float = EXPIRED_POLL_INTERVAL_S,
        expired_poll_limit: int = EXPIRED_POLL_LIMIT,
        outputs: LaneOutputCustody | None = None,
        environments: CursorEnvironmentProvisioner | None = None,
        missing_output_follow_up: bool = False,
    ) -> None:
        super().__init__(
            describe=describe,
            clock=clock,
            record_poll_interval_s=expired_poll_interval_s,
            record_poll_limit=expired_poll_limit,
        )
        self._client = client
        self._missing_output_follow_up = missing_output_follow_up
        self._cancel_observations: dict[str, dict[str, Any]] = {}
        # MP-20: downloaded `outputs/` artifacts become workspace candidates when composed.
        self._outputs = outputs
        self._publisher = publisher
        self._projections = projections
        self._artifacts = artifacts
        self._inputs = inputs
        self._env_resolver = env_resolver
        self._signal_environment = signal_environment
        self._environments = environments
        self._cost_reader = cost_reader
        self._archive = archive_on_end
        self._custody = ProviderWorkspaceCustody(
            workspaces, lane_profile=PROFILE, policy=CURSOR_CLOUD_POLICY
        )
        # Cross-provider control (2026-11-05): what `end_session` recorded per execution
        # (the `branch:<branch>@<sha>` head, the repository), read by `turn_points`.
        self._closed: dict[str, dict[str, str]] = {}

    def _new_session(self, operation: OperationExecutionRequest) -> _CloudSession:
        binding = CursorExecutionBinding.carried_by(operation)
        if binding is None or binding.lane_profile != PROFILE or binding.cloud is None:
            raise ValueError("cursor_cloud runs only an operation with a cursor_cloud binding")
        return _CloudSession(
            operation=operation,
            binding=binding,
            identity=LaneExecutionIdentity.of(operation, PROFILE, 1),
        )

    @staticmethod
    def _repository(binding: CursorExecutionBinding) -> str:
        assert binding.workspace.repo_url is not None
        return binding.workspace.repo_url

    # --- prepare --------------------------------------------------------------------------------

    async def prepare(self, request: PrepareRequest) -> PreparedSession:
        session = self._session(request)
        binding = session.binding
        projection = await self._projections.project(
            session.operation, profile=PROFILE, packet_index=None
        )
        digests = projection_digests(projection)
        verify_projection(binding, digests)
        cloud_inputs = await cloud_packet(session.operation, self._inputs)
        packet = list(cloud_inputs.files)
        urls = await runtime_input_urls(cloud_inputs, self._inputs)
        if urls is not None:
            if binding.cloud is not None and binding.cloud.client_agent_id:
                raise LaneProjectionError(
                    "PREREQUISITES_UNMET", "runtime input URLs require envVars launch support"
                )
            session.env_vars = {**(await self._env_vars(session) or {}), RUNTIME_INPUT_URLS: urls}
        base_ref = binding.workspace.base_ref
        if request.seed is not None:
            # Cross-provider control (2026-11-05): a fork seeded at a cognition point starts
            # the derived agent on the source turn's recorded branch head and prefixes the
            # reconstructed transcript to its first run.
            base_ref = await self._apply_seed(session, request.seed, base_ref)
        forked = _workspace_item(packet)
        if forked is not None:
            # A fork: the derived run's branch starts at the source branch's snapshot head.
            parsed = parse_branch_snapshot(forked)
            if parsed is None:
                raise LaneProjectionError(
                    CHECKPOINT_INVALID, f"{forked} is not a cursor_cloud branch snapshot"
                )
            base_ref = parsed[1]
            session.forked_from = forked
        environment = await self._provider_environment(binding)
        layered = await self._layered(binding, projection, base_ref)
        files = [(item.path, item.content) for item in layered.files] + packet
        if environment is not None:
            files += environment.files()
        branch = await self._publisher.publish(
            repository=self._repository(binding),
            base_ref=base_ref,
            branch=run_branch(binding, request.run_id, request.operation_id),
            files=files,
            secret_values=await self._run_secret_values(session),
        )
        session.projection = projection
        session.branch = branch
        session.environment = environment
        await self._allocate_workspace(
            session, request, base_ref=base_ref, branch=branch, run_id=request.run_id
        )
        return PreparedSession(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            workspace_ref=f"branch:{branch.branch}@{branch.head}",
            projection_digests={
                **digests,
                "packet_digest": sha256_digest(
                    sorted((path, bytes_digest(content)) for path, content in packet)
                ),
                "layering_digest": stable_json_digest(layered.receipt),
                **(environment.digests() if environment is not None else {}),
            },
            materialization_ref=branch.head,
            discovery=committed_expectation(
                layered.receipt, {item.path: item.content for item in layered.files}
            ),
        )

    async def _apply_seed(self, session: _CloudSession, seed: LaneSeedHead, base_ref: str) -> str:
        snapshot_ref = seed.native_artifacts.get(SEED_SNAPSHOT_REF)
        if snapshot_ref:
            parsed = parse_branch_snapshot(snapshot_ref)
            if parsed is None:
                raise LaneProjectionError(
                    CHECKPOINT_INVALID, f"{snapshot_ref} is not a cursor_cloud branch snapshot"
                )
            base_ref = parsed[1]
            session.forked_from = snapshot_ref
        transcript_ref = seed.native_artifacts.get(SEED_TRANSCRIPT_REF)
        if transcript_ref:
            reader: Any = self._inputs if self._inputs is not None else self._artifacts
            if not hasattr(reader, "retrieve"):
                raise LaneProjectionError(
                    CHECKPOINT_INVALID, "no artifact reader is composed to read the seed"
                )
            try:
                raw = await reader.retrieve(transcript_ref)
            except LookupError as error:
                raise LaneProjectionError(
                    CHECKPOINT_INVALID, "the seed's transcript artifact is missing"
                ) from error
            session.seed_hydration = bytes(raw).decode("utf-8")
        elif seed.message:
            session.seed_hydration = f"[operator] {seed.message}\n"
        return base_ref

    async def _provider_environment(
        self, binding: CursorExecutionBinding
    ) -> ProvisionedEnvironment | None:
        """MO-13: the binding's provider environment, applied before anything is published.
        Cursor resolves the environment from the repository, and its Builds use the committed
        file on the default branch (research/cursor.md section 1.2), whatever the run's base
        ref, so that file decides whether a saved environment can apply."""

        assert binding.cloud is not None
        if binding.cloud.provider_environment is None:
            return None
        if self._environments is None:
            raise LaneProjectionError(
                "UNSUPPORTED_BEHAVIOR",
                "the binding names a provider environment but no environments API is composed",
            )
        tree = await self._publisher.read_tree(
            repository=self._repository(binding), ref=DEFAULT_BRANCH_REF, roots=(ENVIRONMENT_FILE,)
        )
        try:
            return await self._environments.provision(binding, dict(tree).get(ENVIRONMENT_FILE))
        except ProviderEnvironmentRefused as error:
            raise LaneProjectionError(error.code, error.message) from error

    async def _layered(
        self, binding: CursorExecutionBinding, projection: HostProjection, base_ref: str
    ) -> LayeredProjection:
        """The projection layered over the repository files at ``base_ref`` (MO-02)."""

        tree = await self._publisher.read_tree(
            repository=self._repository(binding), ref=base_ref, roots=repository_roots(projection)
        )
        try:
            return layer_projection(projection, TreeView(dict(tree)), binding.materialization)
        except LayeringRefused as error:
            raise LaneProjectionError(MATERIALIZATION_CONFLICT, str(error)) from error

    async def _allocate_workspace(
        self,
        session: _CloudSession,
        request: HarnessRequest,
        *,
        base_ref: str,
        branch: PublishedBranch,
        run_id: str,
    ) -> None:
        """Record the run branch as the provider workspace (MP-04 `provider_workspace`)."""

        session.lease = await self._custody.allocate(
            session.identity,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            run_id=run_id,
            repository=self._repository(session.binding),
            base_ref=base_ref,
            branch=branch.branch,
            base_commit=branch.base_commit,
        )

    # --- start, reattach, send ------------------------------------------------------------------

    def _handle(self, request: HarnessRequest, session: _CloudSession) -> SessionHandle:
        assert session.session_ref is not None
        details = {"cloud_branch": "", "cloud_agent_url": session.session_url or ""}
        if session.branch is not None:
            details["cloud_branch"] = f"{session.branch.branch}@{session.branch.head}"
        if session.rehydrated:
            details["rehydrated"] = ",".join(session.rehydrated)
        network = network_projection(session.binding)
        if network is not None:
            details.update(network.native_details())
        if session.environment is not None:
            details.update(session.environment.applied.details())
        return SessionHandle(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            native_session_ref=session.session_ref,
            native_details={key: value for key, value in details.items() if value},
        )

    async def _inline_options(self, session: _CloudSession, *, create: bool) -> dict[str, Any]:
        """The projection's inline launch options, re-sent with every request that takes
        them: ``mcpServers`` on every create and run (cloud ignores ``.cursor/mcp.json`` and a
        run's list replaces the agent's), ``customSubagents`` on every create (a run takes
        none). The projection already holds them to the API limits. A session this process
        did not prepare renders the binding's projection again, as a reattach does."""

        if session.projection is None:
            session.projection = await self._projections.project(
                session.operation, profile=PROFILE, packet_index=None
            )
        sent = {"mcp_servers": "mcpServers"}
        if create:
            sent["agents"] = "customSubagents"
        options: dict[str, Any] = {}
        for option, key in sent.items():
            raw = session.projection.send_options.get(option)
            items = raw if isinstance(raw, list | tuple) else ()
            entries = [dict(item) for item in items if isinstance(item, dict)]
            if entries:
                options[key] = entries
        return options

    def _adopt_agent(self, session: _CloudSession, agent: Mapping[str, Any]) -> None:
        """An agent that already exists (an earlier attempt's create, reconciled)."""

        session.session_ref = str(agent["id"])
        session.session_url = agent.get("url")
        session.initial_run_id = session.initial_run_id or agent.get("latestRunId")
        if session.initial_run_id:
            session.turns.acknowledge(str(session.initial_run_id))

    async def _create_body(
        self, session: _CloudSession, *, prompt: str, agent_ref: str, key: str, name: str
    ) -> tuple[dict[str, Any], str | None]:
        binding = session.binding
        cloud = binding.cloud
        assert cloud is not None and session.branch is not None
        body: dict[str, Any] = {
            "prompt": {"text": prompt},
            "model": {"id": binding.model_id},
            "name": name[:100],
            "repos": [{"url": self._repository(binding), "startingRef": session.branch.branch}],
            "workOnCurrentBranch": True,
            "autoCreatePR": cloud.auto_create_pr,
            "mode": binding.mode,
            "metadata": {"mc_run_id": session.identity.run_key, **cloud.metadata},
        }
        if session.env_vars and RUNTIME_INPUT_URLS in session.env_vars:
            body["prompt"]["text"] = (
                f"Before reading mission inputs, run python {FETCH_INPUTS_SCRIPT}.\n\n" + prompt
            )
        if cloud.environment != "cloud":
            body["env"] = {"type": cloud.environment}
        body.update(await self._inline_options(session, create=True))
        if cloud.client_agent_id:
            body["agentId"] = agent_ref
            return body, None
        env_vars = await self._env_vars(session)
        if env_vars is not None:
            body["envVars"] = launch_env_vars(env_vars)
        return body, key

    async def start(self, request: StartRequest) -> SessionHandle:
        session = self._session(request)
        prompt = turn_text(session.operation)
        if session.seed_hydration is not None:
            prompt = f"{session.seed_hydration.rstrip()}\n\n{prompt}"
        body, idempotency_key = await self._create_body(
            session,
            prompt=prompt,
            agent_ref=client_agent_id(request.harness_execution_id, request.generation),
            key=f"{request.harness_execution_id}:{request.generation}:create",
            name=f"mc-{session.identity.run_key}-{session.identity.attempt_no}",
        )
        try:
            created = await self._create(body, idempotency_key, session)
        except AgentIdConflict:
            # Already created by an earlier attempt of this activity: reattach to it.
            agent = await self._client.get_agent(str(body["agentId"]))
            session.initial_run_id = agent.get("latestRunId")
            self._adopt_agent(session, agent)
            return self._handle(request, session)
        except CloudCapacityLimited as error:
            raise self._capacity(error) from error
        agent = created.get("agent") or {}
        run = created.get("run") or {}
        session.initial_run_id = str(run["id"]) if run.get("id") else agent.get("latestRunId")
        self._adopt_agent(session, agent)
        return self._handle(request, session)

    async def _env_vars(self, session: _CloudSession) -> dict[str, str] | None:
        """The binding's launch envVars (MO-06 `env_vars_ref`), resolved once per process."""

        cloud = session.binding.cloud
        if cloud is None:
            return session.env_vars
        if session.binding.signal_gates is not None and (
            self._signal_environment is None or cloud.client_agent_id
        ):
            raise LaneProjectionError(
                "UNSUPPORTED_BEHAVIOR",
                "signal gates require configured ingress delivery and client_agent_id=false",
            )
        if session.env_vars is None:
            values: dict[str, str] = {}
            if cloud.env_vars_ref is not None:
                if self._env_resolver is None:
                    raise LaneProjectionError(
                        "UNSUPPORTED_BEHAVIOR", "env vars are bound but no resolver is composed"
                    )
                values.update(await self._env_resolver(cloud.env_vars_ref))
            if self._signal_environment is not None:
                values.update(await self._signal_environment(session.operation, session.identity))
            if session.binding.signal_gates is not None and "MC_SIGNAL_TOKEN" not in values:
                raise LaneProjectionError(
                    "UNSUPPORTED_BEHAVIOR", "signal gates require a per-run ingress credential"
                )
            session.env_vars = values or None
        return session.env_vars

    async def _run_secret_values(self, session: _CloudSession) -> tuple[str, ...]:
        """What no Mission Control commit to the run branch may carry (MO-11 pre-commit scan):
        the values the broker resolved for this run, its launch envVars. Minted tokens are
        refused by shape; other runs' values are not this run's to refuse."""

        resolved = await self._env_vars(session) or {}
        return tuple(resolved.values())

    async def _create(
        self, body: dict[str, Any], idempotency_key: str | None, session: _CloudSession
    ) -> dict[str, Any]:
        try:
            return await self._client.create_agent(body, idempotency_key=idempotency_key)
        except FeatureUnavailable:
            # `metadata` is not enabled for this account: recorded, not fatal.
            session.metadata = "feature_unavailable"
            without = {key: value for key, value in body.items() if key != "metadata"}
            return await self._client.create_agent(without, idempotency_key=idempotency_key)

    async def reattach(self, request: ReattachRequest) -> SessionHandle:
        session = self._session(request)
        try:
            agent = await self._client.get_agent(request.native_session_ref)
            if request.native_turn_ref is not None:
                await self._client.get_run(request.native_session_ref, request.native_turn_ref)
        except (AgentNotFound, RunNotFound) as error:
            raise NativeTurnLost("the cloud agent or run no longer exists") from error
        session.session_ref = str(agent["id"])
        session.session_url = agent.get("url")
        session.initial_run_id = session.initial_run_id or agent.get("latestRunId")
        if request.native_turn_ref is not None:
            # The last run the journal acknowledged: the anchor a lost send reconciles against.
            session.turns.anchor(request.native_turn_ref)
        await self._rehydrate(session, request)
        return self._handle(request, session)

    async def _rehydrate(self, session: _CloudSession, request: HarnessRequest) -> None:
        """What a lost worker's process no longer holds: the run branch (resolved on the
        remote, never re-published), the projection (its paths are the patch exclusions) and
        the provider workspace lease; a missing branch loses the turn."""

        rehydrated: list[str] = []
        binding = session.binding
        packet = await cloud_packet(session.operation, self._inputs)
        urls = await runtime_input_urls(packet, self._inputs)
        if urls is not None:
            session.env_vars = {**(await self._env_vars(session) or {}), RUNTIME_INPUT_URLS: urls}
        if session.branch is None:
            branch = await self._publisher.resolve(
                repository=self._repository(binding),
                base_ref=binding.workspace.base_ref,
                branch=run_branch(
                    binding,
                    session.operation.identity.run_id,
                    session.operation.identity.operation_id,
                ),
            )
            if branch is None:
                raise NativeTurnLost("the run branch of this cloud session no longer exists")
            session.branch = branch
            rehydrated.append("branch")
        if session.projection is None:
            session.projection = await self._projections.project(
                session.operation, profile=PROFILE, packet_index=None
            )
            rehydrated.append("projection")
        if session.env_vars is None and binding.cloud and binding.cloud.env_vars_ref:
            # Redaction and the commit scan know the run's envVars in this process too.
            await self._env_vars(session)
            rehydrated.append("env_vars")
        if session.lease is None and self._custody.composed:
            await self._allocate_workspace(
                session,
                request,
                base_ref=binding.workspace.base_ref,
                branch=session.branch,
                run_id=session.operation.identity.run_id,
            )
            rehydrated.append("workspace_lease")
        session.record_rehydration(rehydrated)

    async def send_turn(self, request: SendTurnRequest) -> TurnHandle:
        session = self._session(request)
        agent_id = request.session.native_session_ref or session.session_ref
        if agent_id is None:
            raise ValueError("send_turn requires a created cloud agent")
        if (
            request.instruction_ref is not None
            and request.instruction_ref not in session.turn_texts
            and (request.turn_no != 1 or request.instruction_ref.startswith("continuation:"))
        ):
            raise NativeTurnLost("required staged turn text is unavailable")
        first_run = session.first_runs.get(agent_id)
        if first_run is not None and request.instruction_ref in session.turn_texts:
            # A continuation agent: its create request enqueued the continuation turn.
            session.turns.acknowledge(first_run, request.idempotency_key)
            session.turns.anchor(first_run)
            return TurnHandle(
                session=request.session, turn_no=request.turn_no, native_turn_ref=first_run
            )
        if request.turn_no == 1:
            # The create request enqueued the first run.
            run_id = session.initial_run_id
            if run_id is None:
                agent = await self._client.get_agent(agent_id)
                run_id = agent.get("latestRunId")
            if run_id is None:
                raise NativeTurnLost("the cloud agent reports no first run")
            session.turns.acknowledge(str(run_id), request.idempotency_key)
            session.turns.anchor(str(run_id))
            return TurnHandle(
                session=request.session, turn_no=request.turn_no, native_turn_ref=str(run_id)
            )
        if request.instruction_ref is not None:
            if request.instruction_ref not in session.turn_texts:
                raise NativeTurnLost("required staged turn text is unavailable")
            text = session.turn_texts[request.instruction_ref]
        else:
            text = turn_text(session.operation)
        body: dict[str, Any] = {"prompt": {"text": text}}
        body.update(await self._inline_options(session, create=False))
        try:
            run = await self._client.create_run(agent_id, body)
        except AgentBusy:
            # ADR-0030: this agent's own active run; `wait_then_send` at the boundary.
            return TurnHandle(session=request.session, turn_no=request.turn_no, status="busy")
        except CloudCapacityLimited as error:
            raise self._capacity(error) from error
        run_id = str(run["id"])
        session.turns.acknowledge(run_id, request.idempotency_key)
        session.turns.anchor(run_id)
        return TurnHandle(session=request.session, turn_no=request.turn_no, native_turn_ref=run_id)

    # --- MP-06: reconcile an ambiguous create/send by native identity ---------------------------

    async def reconcile_dispatch(
        self, record: DispatchRecord, *, session: SessionHandle | None
    ) -> DispatchLookup:
        result = await super().reconcile_dispatch(record, session=session)
        parts = parse_dispatch_key(record.idempotency_key)
        if record.kind == "send" and result.outcome == "found" and result.native_ref and parts:
            staged = self._sessions.get(parts.harness_execution_id)
            if staged is not None:
                # Custody follows the current acknowledged turn, including recovered sends.
                staged.turns.anchor(result.native_ref)
        return result

    async def _reconcile_create(
        self, record: DispatchRecord, parts: DispatchKeyParts, staged: _CloudSession | None
    ) -> DispatchLookup:
        if staged is None:
            return DispatchLookup(
                outcome="unknown", detail="the create binding is unavailable for reconciliation"
            )
        if staged.binding.cloud is not None and not staged.binding.cloud.client_agent_id:
            return DispatchLookup(
                outcome="unknown",
                detail="the create used an Idempotency-Key; the API has no read-back by key",
            )
        agent_ref = client_agent_id(parts.harness_execution_id, parts.generation)
        try:
            agent = await self._client.get_agent(agent_ref)
        except AgentNotFound:
            # The id is ours and deterministic: nothing exists under it, nothing was accepted.
            return DispatchLookup(
                outcome="not_received", detail="no agent exists under the client agent id"
            )
        except BridgeError as error:
            return DispatchLookup(outcome="unknown", detail=str(error)[:512])
        self._adopt_agent(staged, agent)
        return DispatchLookup(outcome="found", native_ref=str(agent["id"]))

    async def _reconcile_send(
        self,
        record: DispatchRecord,
        parts: DispatchKeyParts,
        staged: _CloudSession | None,
        session: SessionHandle | None,
    ) -> DispatchLookup:
        agent_id = (session.native_session_ref if session is not None else None) or (
            staged.session_ref if staged is not None else None
        )
        if staged is not None:
            remembered = staged.turns.sent.get(record.idempotency_key)
            if remembered is not None:
                return DispatchLookup(outcome="found", native_ref=remembered)
            if parts.kind == "continuation" and agent_id is not None:
                # The hydrated agent's create enqueued its continuation turn (in-process).
                hydrated_first = staged.first_runs.get(agent_id)
                if hydrated_first is not None:
                    return DispatchLookup(outcome="found", native_ref=hydrated_first)
        if agent_id is None:
            return DispatchLookup(outcome="unknown", detail="no cloud agent to query")
        try:
            agent = await self._client.get_agent(agent_id)
        except AgentNotFound:
            return DispatchLookup(outcome="unknown", detail="the cloud agent no longer exists")
        except BridgeError as error:
            return DispatchLookup(outcome="unknown", detail=str(error)[:512])
        if _status(agent.get("status")) == "archived":
            return DispatchLookup(outcome="unknown", detail="the cloud agent is archived")
        latest = agent.get("latestRunId")
        latest_ref = str(latest) if latest else None
        if parts.kind == "continuation":
            if latest_ref is not None:
                # A continuation agent exists only for its continuation turn: its latest
                # (and first) run is that turn.
                return DispatchLookup(outcome="found", native_ref=latest_ref)
            return DispatchLookup(outcome="unknown", detail="the continuation agent has no run")
        if parts.turn_no == 1:
            if latest_ref is None:
                return DispatchLookup(
                    outcome="unknown", detail="the agent reports no run for its create"
                )
            # The create enqueued turn 1: the agent's run is that turn.
            return DispatchLookup(outcome="found", native_ref=latest_ref)
        if staged is None:
            return DispatchLookup(outcome="unknown", detail=_ANCHOR_DETAILS.unanchored)
        # The v1 API has no read-back by send key: only a latest run that is none of ours
        # proves the lost send was accepted.
        return staged.turns.lookup_latest(
            record.idempotency_key, latest_ref, details=_ANCHOR_DETAILS
        )

    # --- observe: the Cloud Agents run stream and run record ------------------------------------

    async def reconcile_history(
        self, request: ObserveRequest
    ) -> AsyncIterator[LaneFrame | HistoryReplayComplete]:
        # Cursor has no finite event-history boundary. A terminal native run record is
        # authoritative; otherwise the owner reopens SSE from its persisted cursor.
        session = self._session(request)
        session_ref = request.turn.session.native_session_ref or session.session_ref
        turn_ref = request.turn.native_turn_ref
        if session_ref is None or turn_ref is None:
            raise NativeTurnLost("no provider turn to reconcile")
        async for frame in self._reconcile_turn(
            request, session_ref, turn_ref, request.after or STREAM_START, "ended"
        ):
            if frame.terminal:
                yield frame
                yield HistoryReplayComplete()
                return
        raise HistoryReplayIncomplete("native history remains active")

    def _events(
        self, session: _CloudSession, session_ref: str, turn_ref: str, after: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        return self._client.stream(session_ref, turn_ref, last_event_id=after)

    def _classify(self, event: SseEvent, body: Mapping[str, Any]) -> Classified:
        if event.event == "heartbeat":
            return Classified("skip")
        if event.event == "done":
            return Classified("end")
        if event.event == "interaction_update" and body.get("type") in {
            "text-delta",
            "thinking-delta",
            "tool-call-started",
            "tool-call-delta",
            "tool-call-completed",
        }:
            # Simplified SSE is the sole transcript vocabulary; retain the rich duplicate
            # verbatim under an explicitly raw-only kind (normalizes UNKNOWN).
            return Classified("frame", "raw.interaction_update")
        return Classified("terminal" if event.event == "result" else "frame", event.event)

    async def _read_turn(self, session_ref: str, turn_ref: str) -> Mapping[str, Any]:
        try:
            return await self._client.get_run(session_ref, turn_ref)
        except (AgentNotFound, RunNotFound) as error:
            raise NativeTurnLost("the cloud run no longer exists") from error

    def _final_key(self, turn_ref: str) -> str:
        return cursor_cloud_final_key(turn_ref)

    def _status_body(self, turn_ref: str, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "runId": turn_ref,
            "status": record.get("status"),
            "observation": self.names.record_source,
        }

    def _tool_call_ref(self, raw_kind: str, body: Mapping[str, Any]) -> str | None:
        return first(body, "callId", "call_id") if raw_kind == "tool_call" else None

    async def _on_terminal(self, session_ref: str, turn_ref: str, body: dict[str, Any]) -> None:
        """Attribute branch and outputs to the exact completed native run before archive."""
        session = next(
            (
                s
                for s in self._sessions.values()
                if s.session_ref == session_ref or session_ref in s.first_runs
            ),
            None,
        )
        try:
            agent = await self._client.get_agent(session_ref)
        except AgentNotFound:
            body["git_attributed"] = False
            return
        body["latestRunId"] = agent.get("latestRunId")
        body["git_attributed"] = agent.get("latestRunId") == turn_ref
        if body["git_attributed"]:
            if agent.get("prUrl"):
                body["prUrl"] = agent["prUrl"]
            if not body.get("git") and agent.get("git"):
                body["git"] = agent["git"]
        if session is None or not body["git_attributed"]:
            return
        if agent.get("prUrl") and session.branch is not None:
            candidate_git = body.get("git")
            git = candidate_git if isinstance(candidate_git, dict) else {}
            if not git.get("branches"):
                body["git"] = {
                    **git,
                    "branches": [
                        {
                            "repoUrl": self._repository(session.binding),
                            "branch": session.branch.branch,
                            "prUrl": agent["prUrl"],
                        }
                    ],
                }
        present: set[str] = set()
        channels = session.operation.workspace.output_channels or (
            "branch_commit",
            "artifact_upload",
        )
        if "branch_commit" in channels and session.branch is not None:
            repository = self._repository(session.binding)
            head = await self._publisher.head(repository=repository, branch=session.branch.branch)
            present.update(
                path
                for path, _ in await self._publisher.read_tree(
                    repository=repository, ref=head, roots=("outputs",)
                )
            )
            body["outputs_branch_head"] = head
        if any(channel != "branch_commit" for channel in channels):
            present.update(
                str(item.get("path", "")) for item in await self._client.list_artifacts(session_ref)
            )
        body["missing_outputs"] = tuple(
            path for path in declared_outputs(session.operation) if path not in present
        )

    async def missing_output_followup(self, turn: TurnHandle, facts: ClosingFacts) -> str | None:
        """An authored single allowance; the workflow must wait_then_send at its boundary."""
        if not self._missing_output_follow_up or not facts.missing_outputs or turn.turn_no != 1:
            return None
        return "Produce the missing declared outputs: " + ", ".join(facts.missing_outputs)

    def closing_facts(self, turn: TurnHandle, frame: LaneFrame) -> ClosingFacts:
        body = dict(frame.body) if isinstance(frame.body, dict) else {}
        if not body.get("git_attributed", False):
            body.pop("git", None)
        facts = body_closing_facts(body)
        return facts.model_copy(update={"missing_outputs": tuple(body.get("missing_outputs", ()))})

    # --- cross-provider control (2026-11-05): cognition points -------------------------------

    @property
    def branches(self) -> GitBranchPublisher:
        """The SCM reader the cloud time travel lists a turn's branch tree with (R2)."""

        return self._publisher

    def turn_points(self, request: TurnPointsRequest) -> tuple[CognitionPointObservation, ...]:
        """`PointCollectingLane`: one `session_cursor` point per step of the run keyed by the
        SSE event id, plus the turn-close `workspace_snapshot` (`branch:<branch>@<sha>`)."""

        closed = self._closed.get(request.harness_execution_id)
        if closed is not None and request.terminal:
            self._closed.pop(request.harness_execution_id, None)
        return cursor_turn_points(request, closed=closed)

    # --- FT-G6: continuation -------------------------------------------------------------------

    def live_session(self, agent_id: str) -> str | None:
        for harness_execution_id, session in self._sessions.items():
            if session.session_ref == agent_id and session.branch is not None:
                return harness_execution_id
        return None

    def session_branch(self, harness_execution_id: str) -> tuple[str, str]:
        session = self._sessions[harness_execution_id]
        assert session.branch is not None
        return self._repository(session.binding), session.branch.branch

    def session_lease(self, harness_execution_id: str) -> WorkspaceLease | None:
        session = self._sessions.get(harness_execution_id)
        return None if session is None else session.lease

    async def conversation_export(self, harness_execution_id: str) -> bytes:
        from mission_control.adapters.cursor.conversation import conversation_export

        session = self._sessions[harness_execution_id]
        value: Any = None
        if session.session_ref is not None:
            with contextlib.suppress(AgentNotFound, FeatureUnavailable, BridgeError):
                value = await self._client.conversation(session.session_ref)
        return conversation_export(
            value,
            session_ref=session.session_ref or "unknown",
            run_ref=session.turns.journal_anchor or session.initial_run_id,
            source="cursor.v0.conversation",
            secrets=await self._run_secret_values(session),
        )

    async def read_branch(
        self, harness_execution_id: str, roots: tuple[str, ...]
    ) -> list[tuple[str, bytes]]:
        repository, branch = self.session_branch(harness_execution_id)
        head = await self._publisher.head(repository=repository, branch=branch)
        return await self._publisher.read_tree(repository=repository, ref=head, roots=roots)

    async def hydrate_agent(
        self,
        harness_execution_id: str,
        *,
        transfer_id: str,
        files: list[tuple[str, bytes]],
        prompt: str,
        source_session_ref: str,
    ) -> tuple[str, dict[str, str]]:
        """Commit the continuation's files to the run branch, then create a fresh agent on
        it whose first run is the continuation turn; offer the handover. Returns the agent id
        and the restored digests read back from the pushed branch."""

        session = self._sessions[harness_execution_id]
        binding = session.binding
        cloud = binding.cloud
        assert cloud is not None and session.branch is not None
        repository, branch = self.session_branch(harness_execution_id)
        head = await self._publisher.commit_files(
            repository=repository,
            branch=branch,
            files=files,
            message=f"mission control: continuation {transfer_id}",
            secret_values=await self._run_secret_values(session),
        )
        agent_ref = client_agent_id(f"{harness_execution_id}:{transfer_id}", 1)
        body, idempotency_key = await self._create_body(
            session,
            prompt=prompt,
            agent_ref=agent_ref,
            key=f"{harness_execution_id}:{transfer_id}:create",
            name=f"mc-{session.identity.run_key}-continuation",
        )
        try:
            created = await self._create(body, idempotency_key, session)
            agent = created.get("agent") or {}
            run = created.get("run") or {}
            first_run = str(run.get("id") or agent.get("latestRunId"))
        except AgentIdConflict:
            agent = await self._client.get_agent(agent_ref)
            first_run = str(agent.get("latestRunId"))
        except CloudCapacityLimited as error:
            raise self._capacity(error) from error
        agent_id = str(agent["id"])
        if not first_run or first_run == "None":
            raise NativeTurnLost("continuation create reports no native first run; reconcile agent")
        instruction_ref = f"continuation:{transfer_id}"
        self.stage_turn(harness_execution_id, instruction_ref, prompt)
        session.first_runs[agent_id] = first_run
        session.turns.acknowledge(first_run)
        details = {"cloud_branch": f"{branch}@{head}"}
        network = network_projection(binding)
        if network is not None:
            details.update(network.native_details())
        session.handover = SessionHandover(
            transfer_id=transfer_id,
            session=SessionHandle(
                lane_profile=PROFILE,
                harness_execution_id=harness_execution_id,
                generation=session.identity.attempt_no,
                native_session_ref=agent_id,
                native_details=details,
            ),
            instruction_ref=instruction_ref,
            source_session_ref=source_session_ref,
        )
        restored = {
            f"/{safe_relative(path).as_posix()}": bytes_digest(content)
            for path, content in await self._publisher.read_tree(
                repository=repository, ref=head, roots=tuple(path for path, _ in files)
            )
        }
        return agent_id, restored

    async def complete_handover(self, harness_execution_id: str, transfer_id: str) -> None:
        session = self._sessions.get(harness_execution_id)
        if session is None or session.handover is None:
            return
        handover = session.handover
        if handover.transfer_id != transfer_id:
            return
        if handover.source_session_ref != handover.session.native_session_ref:
            # Archive before dropping the durable handover offer so a failed archive can retry.
            with contextlib.suppress(AgentNotFound, AgentArchived):
                await self._client.archive(handover.source_session_ref)
        await super().complete_handover(harness_execution_id, transfer_id)

    # --- controls -----------------------------------------------------------------------------

    async def status(self, request: StatusRequest) -> ProviderStatus:
        session = self._session(request)
        agent_id = request.session.native_session_ref or session.session_ref
        if agent_id is None:
            return ProviderStatus(status="not_started", terminal=False, idle=True)
        try:
            agent = await self._client.get_agent(agent_id)
            run = (
                await self._client.get_run(agent_id, request.turn.native_turn_ref)
                if request.turn is not None and request.turn.native_turn_ref
                else None
            )
        except (AgentNotFound, RunNotFound) as error:
            raise NativeTurnLost("the cloud agent or run no longer exists") from error
        agent_idle = _status(agent.get("status")) == "idle"
        if run is None:
            return ProviderStatus(
                status=_status(agent.get("status")), terminal=False, idle=agent_idle
            )
        status = _status(run.get("status"))
        terminal = status in _TERMINAL
        return ProviderStatus(status=status, terminal=terminal, idle=agent_idle or terminal)

    async def cancel_turn(self, request: CancelTurnRequest) -> CancelReceipt:
        session = self._session(request)
        agent_id = request.turn.session.native_session_ref or session.session_ref
        run_id = request.turn.native_turn_ref
        if agent_id is None or run_id is None:
            return CancelReceipt(acknowledged=True, already_terminal=True, native_status="idle")
        already = False
        try:
            acknowledgement = await self._client.cancel_run(agent_id, run_id)
            self._cancel_observations[run_id] = {
                "native_session_ref": agent_id,
                "native_turn_ref": run_id,
                "acknowledged_at": self._clock().isoformat(),
                "provider_date": acknowledgement.get("provider_date"),
                "source": "cursor_cloud.cancel_response",
            }
        except RunNotCancellable:
            already = True
        except (AgentNotFound, RunNotFound):
            return CancelReceipt(acknowledged=False, native_status="unknown")
        try:
            run = await self._client.get_run(agent_id, run_id)
        except (AgentNotFound, RunNotFound):
            return CancelReceipt(
                acknowledged=True, already_terminal=already, native_status="unknown"
            )
        return CancelReceipt(
            acknowledged=True, already_terminal=already, native_status=_status(run.get("status"))
        )

    def cancel_observation(self, native_turn_ref: str) -> Mapping[str, Any] | None:
        """Derived receipt, outside canonical CancelReceipt and binding digests."""
        observation = self._cancel_observations.get(native_turn_ref)
        return dict(observation) if observation is not None else None

    async def usage(self, request: UsageRequest) -> UsageReport:
        """Tokens settle from `GET /v1/agents/{id}/usage?runId=` only when the API reports
        this run's usage (`runs[].usage`, or `totalUsage` when no run is asked for); cost
        settles only when the cost reader (the SDK's `get_usage().cost`) reports a non-null
        value. Anything the provider does not report stays `unknown` (never zero)."""

        session = self._session(request)
        agent_id = request.session.native_session_ref or session.session_ref
        run_id = request.turn.native_turn_ref if request.turn is not None else None
        if agent_id is None:
            return UsageReport(disposition="unknown")
        cost = None
        if self._cost_reader is not None and run_id is not None:
            with contextlib.suppress(BridgeError):
                cost = await self._cost_reader(agent_id, run_id)
        try:
            usage = await self._client.usage(agent_id, run_id)
        except (FeatureUnavailable, AgentNotFound, RunNotFound):
            return UsageReport(disposition="unknown", cost_micros_usd=cost)
        tokens = _run_tokens(usage, run_id)
        if tokens is None or not all(key in tokens for key in ("inputTokens", "outputTokens")):
            return UsageReport(disposition="unknown", cost_micros_usd=cost)
        report = cursor_token_usage(tokens)
        return report.model_copy(
            update={
                "disposition": "settled" if report.disposition != "unknown" else "unknown",
                "cost_micros_usd": cost,
            }
        )

    # --- snapshot, end ------------------------------------------------------------------------

    def _excluded(self, session: _CloudSession) -> tuple[str, ...]:
        return session.projection.paths() if session.projection is not None else ()

    async def _record_head(self, session: _CloudSession, head: str) -> CapturedSnapshot | None:
        """The branch head read back from the remote, recorded on the provider workspace
        lease (`branch:<branch>@<sha>`): the producer of the restore convention."""

        conversation: ConversationEvidence | None = None
        if session.lease is not None and self._custody.composed:
            from mission_control.adapters.cursor.conversation import fork_conversation_export

            native = session.session_ref
            anchor = session.turns.journal_anchor or session.initial_run_id
            if native is None or anchor is None or session.branch is None:
                raise NativeTurnLost("conversation custody needs an identified native origin")
            repository = self._repository(session.binding)
            before = await self._client.get_agent(native)
            if before.get("latestRunId") != anchor:
                raise NativeTurnLost("conversation origin is no longer the acknowledged native run")
            origin = ConversationOrigin(
                request_scope=session.lease.request_scope,
                run_id=session.lease.run_id,
                repository=repository,
                branch=session.branch.branch,
                head_commit=head,
                session_ref=native,
                run_ref=anchor,
            )
            raw = fork_conversation_export(
                await self.conversation_export(str(session.identity.harness_execution_id)),
                origin=origin,
            )
            # Agent-wide conversation is anchored to the acknowledged latest native run.
            # Both the remote head and native anchor must stay fixed across the export.
            after = await self._client.get_agent(native)
            observed_head = await self._publisher.head(repository=repository, branch=origin.branch)
            if (
                observed_head != head
                or after.get("latestRunId") != anchor
                or session.session_ref != native
                or (session.turns.journal_anchor or session.initial_run_id) != anchor
            ):
                raise NativeTurnLost("conversation origin moved during capture")
            ref = await self._artifacts.stage(
                request_scope=origin.request_scope,
                name=f"cursor-cloud/{session.identity.harness_execution_id}/conversation/{bytes_digest(raw)}.json",
                content=raw,
                media_type=CONVERSATION_MEDIA_TYPE,
            )
            conversation = ConversationEvidence(
                origin=origin,
                disposition=ConversationEnvelope.model_validate_json(raw).conversation.disposition,
                durable_ref=ref,
                content_digest=bytes_digest(raw),
                content_bytes=len(raw),
            )
        captured = await self._custody.record_head(session.lease, head, conversation=conversation)
        if captured is not None:
            session.custody = captured
        return captured

    async def snapshot(self, request: SnapshotRequest) -> SnapshotManifest:
        session = self._session(request)
        if session.branch is None:
            raise ValueError("no published branch to snapshot")
        head = await self._publisher.head(
            repository=self._repository(session.binding), branch=session.branch.branch
        )
        refs = [branch_snapshot_ref(session.branch.branch, head)]
        captured = await self._record_head(session, head)
        if captured is not None and session.lease is not None:
            refs.append(f"workspace-lease:{session.lease.lease_id}")
        if session.session_ref is not None:
            refs += [
                f"artifact:{item.get('path')}"
                for item in await self._client.list_artifacts(session.session_ref)
            ]
        return SnapshotManifest(
            lane_profile=PROFILE,
            harness_execution_id=request.harness_execution_id,
            generation=request.generation,
            kind="branch",
            refs=tuple(refs),
            emulated=True,
            digest=sha256_digest(refs),
        )

    async def end_session(self, request: EndSessionRequest) -> CleanupReceipt:
        session = self._session(request)
        agent_id = request.session.native_session_ref or session.session_ref
        if session.branch is None and agent_id is not None:
            # A session ended by a worker that never prepared it (reattached after a loss).
            try:
                await self._rehydrate(session, request)
            except NativeTurnLost:
                session.branch = None
        if session.branch is None or agent_id is None:
            self._sessions.pop(request.harness_execution_id, None)
            return CleanupReceipt(released=False)
        scope = session.identity.request_scope
        name = f"cursor-cloud/{request.harness_execution_id}/{request.generation}"
        diff, head = await self._publisher.diff(
            repository=self._repository(session.binding),
            base=session.branch.base_commit,
            branch=session.branch.branch,
            exclude=self._excluded(session),
        )
        patch_ref = await self._artifacts.stage(
            request_scope=scope, name=f"{name}/patch.diff", content=diff, media_type="text/x-diff"
        )
        registered: list[dict[str, Any]] = []
        refs: list[str] = []
        channels = session.operation.workspace.output_channels
        items: list[dict[str, Any]] = []
        for channel in channels or ("branch_commit", "artifact_upload"):
            if channel == "branch_commit":
                branch_files = await self._publisher.read_tree(
                    repository=self._repository(session.binding), ref=head, roots=("outputs",)
                )
                items.extend(
                    {"path": path, "content": content, "channel": channel}
                    for path, content in branch_files
                )
            else:
                items.extend(
                    {**item, "channel": channel}
                    for item in await self._client.list_artifacts(agent_id)
                )
        for item in items:
            selected = item["channel"]
            path = str(item.get("path", ""))
            if not path:
                continue
            content = (
                item["content"]
                if selected == "branch_commit"
                else await self._client.download_artifact(agent_id, path)
            )
            candidate = (
                await self._outputs.register(
                    session.operation,
                    path,
                    content,
                    **({"channel": selected} if channels is not None else {}),
                )
                if self._outputs is not None
                else None
            )
            ref = candidate or await self._artifacts.stage(
                request_scope=scope,
                name=f"{name}/{path}",
                content=content,
                media_type="application/octet-stream",
            )
            refs.append(ref)
            registered.append(
                {
                    "path": path,
                    "digest": bytes_digest(content),
                    "size": len(content),
                    "ref": ref,
                    "channel": selected,
                    "source_head": head if selected == "branch_commit" else None,
                    "source_session_ref": agent_id,
                    "source_run_refs": sorted(session.turns.observed()),
                }
            )
        captured = await self._record_head(session, head)
        # MO-14: the branch head read back from the remote, as an immutable head SHA artifact.
        head_ref = await record_branch_head(
            self._artifacts,
            MissionBranchHead(
                run_id=session.identity.run_key,
                lane_profile=PROFILE,
                repository=self._repository(session.binding),
                branch=session.branch.branch,
                head_sha=head,
                source="branch_lookup",
                session_ref=session.session_url or agent_id,
                observed_at=self._clock(),
            ),
            request_scope=scope,
        )
        manifest = json.dumps(
            {
                "schema_version": "mc.cursor_session_capture.v1",
                "capture_kind": "artifact_capture",
                "captured_at": self._clock().isoformat(),
                "provider_artifact_scope": "agent",
                "resumable_execution_checkpoint": False,
                "provenance": {
                    "request_scope": scope,
                    "run_id": session.identity.run_key,
                    "activation_key": session.identity.activation_key,
                    "attempt_no": session.identity.attempt_no,
                    "harness_execution_id": request.harness_execution_id,
                    "generation": request.generation,
                    "lane_profile": PROFILE,
                    "provider_session_ref": agent_id,
                    "provider_url": session.session_url,
                    "observed_provider_run_refs": sorted(session.turns.observed()),
                },
                "branch": session.branch.branch,
                "base_commit": session.branch.base_commit,
                "head": head,
                "head_artifact_ref": head_ref,
                "artifacts": registered,
                "metadata": session.metadata,
                "stream_retention_seconds": session.retention_seconds,
                "expired_streams": dict(sorted(session.expired_streams.items())),
                "workspace_snapshot_ref": captured.snapshot_ref if captured else None,
                "workspace_lease_id": str(session.lease.lease_id) if session.lease else None,
            },
            sort_keys=True,
        ).encode("utf-8")
        manifest_ref = await self._artifacts.stage(
            request_scope=scope,
            name=f"{name}/session-manifest.json",
            content=manifest,
            media_type="application/json",
        )
        # The lease is released only after the patch, the artifacts and the head snapshot
        # are in custody (SPEC-01 step 8); the provider keeps the VM, nothing is deleted.
        session.lease = await self._custody.release(session.lease, captured)
        # Archived only after the patch and every artifact are registered; never deleted here.
        if self._archive:
            await self._client.archive(agent_id)
        self._closed[request.harness_execution_id] = {
            "snapshot_ref": (
                captured.snapshot_ref
                if captured is not None
                else branch_snapshot_ref(session.branch.branch, head)
            ),
            "repository": self._repository(session.binding),
            "branch": session.branch.branch,
            "head": head,
        }
        self._sessions.pop(request.harness_execution_id, None)
        return CleanupReceipt(
            released=True,
            artifact_refs=(patch_ref, *refs, head_ref, manifest_ref),
            patch_ref=patch_ref,
        )


def _run_tokens(usage: Mapping[str, Any], run_id: str | None) -> Mapping[str, Any] | None:
    """This run's token usage from the `/usage` response, or the agent total when no run is
    asked for; None when the API reports nothing for it (agent totals are never attributed
    to one run)."""

    if run_id is not None:
        for entry in usage.get("runs") or ():
            if (
                isinstance(entry, Mapping)
                and (entry.get("id") or entry.get("runId") or entry.get("run_id")) == run_id
            ):
                tokens = entry.get("usage")
                return tokens if isinstance(tokens, Mapping) and tokens else None
        return None
    tokens = usage.get("totalUsage")
    return tokens if isinstance(tokens, Mapping) and tokens else None


def _workspace_item(packet: list[tuple[str, bytes]]) -> str | None:
    """The snapshot ref of the packet's `workspace` item (`.mission/inputs.json`), if any."""

    raw = dict(packet).get(INPUTS_MANIFEST_PATH)
    if raw is None:
        return None
    try:
        workspace = json.loads(raw.decode("utf-8")).get("workspace")
    except (ValueError, AttributeError):
        return None
    if isinstance(workspace, dict) and workspace.get("snapshot_ref"):
        return str(workspace["snapshot_ref"])
    return None


__all__ = [
    "CURSOR_CLOUD_POLICY",
    "EXPIRED_POLL_INTERVAL_S",
    "EXPIRED_POLL_LIMIT",
    "PROFILE",
    "STREAM_START",
    "CursorCloudHarness",
    "DispatchKeyParts",
    "client_agent_id",
    "parse_branch_snapshot",
    "parse_dispatch_key",
    "run_branch",
]
