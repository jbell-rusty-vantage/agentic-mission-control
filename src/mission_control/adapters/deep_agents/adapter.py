from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Annotated, Any, NotRequired, Protocol, cast
from uuid import UUID

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol
from deepagents.backends.state import StateBackend
from deepagents.backends.utils import file_data_to_string
from deepagents.middleware.filesystem import FilesystemPermission
from deepagents.middleware.subagents import SubAgent
from deepagents.profiles.harness.harness_profiles import _harness_profile_for_model
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.runtime import Runtime
from langgraph.types import StateSnapshot
from pydantic import BaseModel
from typing_extensions import TypedDict

from mission_control.adapters.deep_agents.binding import execution_binding
from mission_control.adapters.deep_agents.budget import (
    BUDGET_STOP,
    TOOL_CALLS,
    BudgetStopMiddleware,
    FenceStopMiddleware,
    TurnStop,
    is_turn_stop,
    refused_tool_call,
)
from mission_control.adapters.deep_agents.capability_lineage import capability_lineage
from mission_control.adapters.deep_agents.checkpoint_reads import (
    MAX_LINEAGE_WALK,
    checkpoint_parent_id,
    root_checkpoint_config,
)
from mission_control.adapters.deep_agents.cognition_points import (
    DEFAULT_POINTS_WALK_BUDGET_MS,
    collect_points,
    files_channel_digest,
)
from mission_control.adapters.deep_agents.compaction import (
    ObservedSummarizationMiddleware,
    StopGuardedSummarizationMiddleware,
)
from mission_control.adapters.deep_agents.features import filesystem_replacement
from mission_control.adapters.deep_agents.frames import (
    NS_SEP,
    SOURCE_SANDBOX_UPLOAD,
    SOURCE_STATE_CHANNEL,
    TASK_TOOL,
    DeepAgentFrameRecorder,
    ManifestFile,
    materialization_manifest,
)
from mission_control.adapters.deep_agents.knowledge_tools import KnowledgeLaneSupport
from mission_control.adapters.deep_agents.materializer import (
    ExactDeepAgentMaterializer,
    MaterializedDeepAgentArguments,
    seed_backend_files,
)
from mission_control.adapters.deep_agents.model_retry import (
    TRANSIENT_TRANSPORT,
    GovernedModelRetryMiddleware,
    unsent_transport_failure,
)
from mission_control.adapters.deep_agents.steering import (
    OperatorSteerMiddleware,
    SteerInbox,
    SteerItem,
)
from mission_control.adapters.deep_agents.transfer import (
    DeepAgentReceiverBackend,
    materialize_transfer,
    measured_overhead,
)
from mission_control.adapters.deep_agents.workspace_closure import (
    WorkspaceClosurePort,
    capture_closure,
    retain_until,
)
from mission_control.adapters.langsmith.tracing import trace_deep_agent_execute
from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
    MaterializedTransfer,
    TransferMaterializer,
)
from mission_control.application.execution.operations.invocation_settlement import (
    InvocationSettler,
)
from mission_control.application.execution.operations.operation_progress import (
    register_checkpoint_reader,
)
from mission_control.application.frames.capture_policy import STANDARD_PROFILE, FrameCapture
from mission_control.application.frames.reducer import FrameFactProjector, FrameFactTarget
from mission_control.application.frames.sink import (
    FrameStore,
    HarnessExecutionNotFound,
    harness_execution_id,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.refs import workspace_candidate_ref
from mission_control.domain.context.render import bytes_digest, is_context_input_slot
from mission_control.domain.execution.async_subagent_reconciliation import (
    AsyncServedGraphIdentity,
)
from mission_control.domain.execution.checkpoint_lineage import (
    ROOT_CHECKPOINT_NS,
    STAMP_ATTEMPT_REF,
    STAMP_STATE_SCHEMA_DIGEST,
    CheckpointCapture,
    CheckpointClassification,
    CheckpointInvocationPlan,
    CheckpointLineageError,
    CheckpointLineageInDoubt,
    IncompatibleCheckpointSchema,
)
from mission_control.domain.execution.cognition_points import CognitionPointObservation
from mission_control.domain.execution.contracts import (
    IN_TURN_RUN_DIMENSIONS,
    AsyncSubagentContract,
    CapturedWorkspaceCandidate,
    DeepAgentExecutionBinding,
    OperationExecutionBinding,
    PromptSegment,
    RuntimeInvocation,
    RuntimeResult,
    RuntimeUsage,
    SealedAsyncChildBinding,
)
from mission_control.domain.execution.errors import (
    DeepAgentMaterializationError,
    DeepAgentRuntimeDrift,
    RuntimeInvocationFailure,
)
from mission_control.domain.execution.invocation_settlement import SettlementOutcome
from mission_control.domain.execution.workspace_closure import ClosureBoundary
from mission_control.domain.frames.contracts import (
    DEFAULT_EXCERPT_CAP_BYTES,
    HarnessExecutionStart,
    LaneProfile,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.resolution.profiles import WorkspaceClosureProfile

logger = logging.getLogger(__name__)


class AsyncSubagentMiddlewareFactory(Protocol):
    """Builds the governed async-subagent middleware for one parent operation binding."""

    def middleware(
        self,
        binding: OperationExecutionBinding,
        contracts: tuple[AsyncSubagentContract, ...],
        resolved_secrets: Mapping[str, str],
    ) -> AgentMiddleware[Any, Any, Any]: ...


class WorkspaceOutputCapturePort(Protocol):
    """Captures a file the agent wrote into one of its exclusive writable slots (RRM-009).

    REQ-CP-DA-014: capture makes the bytes and descriptor durable as a workspace candidate;
    only the governed promotion decision makes them a consumable artifact.
    """

    async def capture(
        self, binding: OperationExecutionBinding, logical_path: str, content: bytes
    ) -> CapturedWorkspaceCandidate: ...


class DurableInputReader(Protocol):
    """Reads a read-only durable workspace input (``<object_ref>#<sha256>:<size>``)."""

    async def retrieve(self, durable_ref: str) -> bytes: ...


MAX_CAPTURED_OUTPUT_FILES = 64
MAX_CAPTURED_OUTPUT_BYTES = 4_000_000
MAX_CAPTURE_LISTING_DEPTH = 4


class DeepAgentRuntimeAdapter:
    """The sole production `create_deep_agent` composition root."""

    def __init__(
        self,
        materializer: ExactDeepAgentMaterializer,
        *,
        async_subagents: AsyncSubagentMiddlewareFactory | None = None,
        workspace_outputs: WorkspaceOutputCapturePort | None = None,
        frames: FrameStore | None = None,
        frame_excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
        frame_facts: FrameFactProjector | None = None,
        context_inputs: DurableInputReader | None = None,
        drop_unregistered_output_refs: bool = False,
        frame_capture: FrameCapture | None = None,
        saver_locators: Mapping[str, str] | None = None,
        points_walk_budget_ms: int = DEFAULT_POINTS_WALK_BUDGET_MS,
        knowledge: KnowledgeLaneSupport | None = None,
        transfer: TransferMaterializer | None = None,
        settlers: Sequence[InvocationSettler] = (),
        closures: WorkspaceClosurePort | None = None,
        closure_policy: WorkspaceClosureProfile | None = None,
    ) -> None:
        self._materializer = materializer
        # OVE-204 slice 5: the Workspace Closure store and the Application Profile's
        # `[workspace]` caps and retention; no store (or a disabled profile) records none.
        self._closures = closures
        self._closure_policy = closure_policy or WorkspaceClosureProfile()
        # WI-04: the post-execution settlement of a saved result; the knowledge support settles
        # invocations with knowledge tools, a composed settler (a durable-wait double) others.
        self._settlers: tuple[InvocationSettler, ...] = (
            *settlers,
            *((knowledge,) if knowledge is not None else ()),
        )
        # WI-02 (ADR-0061): the one transfer materializer every receiving invocation uses.
        self._transfer = transfer
        # Sprint V SV-16 (M02/M06): the knowledge tools read the live invocation this binds
        # around each attempt's cognition; a completed attempt finalizes its submissions.
        self._knowledge = knowledge
        # 1.4.4 (P6): where each pinned checkpointer lives (its locator digest, stamped on
        # every point key) and the wall-clock budget of the points walk at settlement.
        self._saver_locators = dict(saver_locators or {})
        self._points_walk_budget_ms = points_walk_budget_ms
        self._async_subagents = async_subagents
        self._workspace_outputs = workspace_outputs
        # SPEC-03 (C1): the Native Event Store. When configured, cognition streams through
        # `astream` v2 and every observed provider event is persisted before derivation.
        self._frames = frames
        self._frame_excerpt_cap = frame_excerpt_cap_bytes
        # 1.4.4 (TR-D2): the capture profile and the body promoter composition chose; the
        # profile's cap replaces `frame_excerpt_cap_bytes` and its name is recorded on the
        # harness execution so a Transcript reader knows what was captured.
        self._frame_capture = frame_capture
        # SPEC-03 (C2): facts derived from the persisted closing frames become mission events.
        self._frame_facts = frame_facts
        # FT-B2: reads the Context Packet's verified read-only inputs for backend seeding.
        self._context_inputs = context_inputs
        # FT-B2: strict mode drops model-emitted output refs that this attempt did not
        # register; the default keeps them (with provenance warnings) for families and
        # fixtures that still consume model-emitted refs. Either way the Context Packer only
        # materializes registered refs.
        self._drop_unregistered_output_refs = drop_unregistered_output_refs
        # Owner 2026-11-06 (steer with context): `cooperative_inject` into the running turn.
        self._steer = SteerInbox()
        self._steer_leftover: dict[str, list[SteerItem]] = {}

    # -- steer with context (cooperative_inject) -------------------------------------------

    async def inject(self, invocation: RuntimeInvocation, content: PromptSegment) -> None:
        """Hand a steer to the running turn of this binding (`CooperativeInjectLane`).

        The turn's `OperatorSteerMiddleware` appends it before the next model call. With no
        turn running (it just ended), the steer waits for `undelivered` to run it as a
        follow-up turn; it is never dropped.
        """

        key = invocation.binding.binding_id
        item = SteerItem(delivery_key=content.source_ref, segment=content)
        if not self._steer.put(key, item):
            self._steer_leftover.setdefault(key, []).append(item)

    def undelivered(self, invocation: RuntimeInvocation) -> tuple[PromptSegment, ...]:
        """Steers the binding's finished turn never drained, oldest first (removed)."""

        items = self._steer_leftover.pop(invocation.binding.binding_id, [])
        return tuple(item.segment for item in items)

    async def build_hosted_async_subagent_graph(
        self,
        binding: DeepAgentExecutionBinding,
        resolved_secrets: Mapping[str, str],
        *,
        system_prompt: str,
        served: AsyncServedGraphIdentity,
        stack: AsyncExitStack,
        sealed: SealedAsyncChildBinding | None = None,
    ) -> Any:
        """Compile the graph an Agent Server serves for one exact async subagent binding.

        REQ-CP-DA-019: the graph is materialized from the exact binding through the canonical
        materializer and compiled here, the only `create_deep_agent` site. The server owns the
        checkpointer, the store and scheduling; the graph stamps its served identity into the
        thread state so the parent can verify it on every observation. Provider lifecycles the
        materializer opens stay open on `stack` for the server process's lifetime.

        OVE-184: a sealed child (`sealed`) is served under its sealed digest, which covers its
        prompt text as well as `binding`; the prompt must be the sealed one.
        """

        if sealed is not None:
            if (
                sealed.binding != binding
                or sealed.system_prompt != system_prompt
                or served.graph_binding_digest != sealed.sealed_digest
                or served.binding_mode != "sealed_child"
            ):
                raise DeepAgentMaterializationError(
                    "served graph identity does not name this exact sealed child binding"
                )
        elif served.graph_binding_digest != binding.binding_digest:
            raise DeepAgentMaterializationError(
                "served graph identity does not name this exact binding"
            )
        materialized = await stack.enter_async_context(
            self._materializer.prepare(binding, resolved_secrets, hosted=True)
        )
        return _compile(
            materialized,
            binding,
            system_prompt=system_prompt,
            extra_middleware=[ServedGraphIdentityMiddleware(served)],
            name=f"belllabs-async-{binding.operation_id}",
        )

    @trace_deep_agent_execute
    async def execute(
        self,
        invocation: RuntimeInvocation,
        resolved_secrets: Mapping[str, str],
    ) -> RuntimeResult:
        try:
            return await self._execute_turn(invocation, resolved_secrets)
        finally:
            # Steers the turn never drained (it ended after its last model call) wait for
            # the inject service's follow-up turn (`undelivered`).
            left = self._steer.close(invocation.binding.binding_id)
            if left:
                self._steer_leftover.setdefault(invocation.binding.binding_id, []).extend(left)

    async def _execute_turn(
        self,
        invocation: RuntimeInvocation,
        resolved_secrets: Mapping[str, str],
    ) -> RuntimeResult:
        knowledge = self._knowledge
        if knowledge is None or not knowledge.uses_knowledge(invocation):
            return await self._execute(invocation, resolved_secrets)
        # Before any model call: host recovery grants for a retry attempt (R2-MC D2). The
        # receiver's inputs arrive only through its sealed transfer plan (WI-02), realized in
        # `_execute` on the actual backend for every invocation, with or without these tools.
        live = await knowledge.begin(invocation)
        with knowledge.bind(invocation, live):
            try:
                result = await self._execute(invocation, resolved_secrets)
            except asyncio.CancelledError:
                # A stop during cognition: cancel its open handles and reconcile, then keep
                # cancelling.
                await asyncio.shield(knowledge.stop(invocation))
                raise
            except Exception:
                # R2-MC O1: a failed attempt still reconciles its outstanding effects and
                # records its finalization (basis `attempt_failed`) before the failure surfaces.
                await asyncio.shield(knowledge.fail(invocation, live))
                raise
        # WI-04: completed cognition returns at once. The operation boundary saves this result
        # and only then runs `settle_invocation` (assessment handoff, effect receipts, reviews),
        # so no settlement wait can lose it or dispatch it again.
        return result

    async def settle_invocation(
        self, invocation: RuntimeInvocation, *, fenced: bool = False
    ) -> SettlementOutcome:
        """WI-04 (`SettlesInvocation`): one settlement pass over a saved result.

        No model is called and nothing is materialized: the composed settler (the knowledge
        lane support for an invocation with knowledge tools) reconciles and finalizes, and its
        outcome is returned typed (settled, or waiting on a review or an effect). An
        invocation no settler applies to settles at once.
        """

        for settler in self._settlers:
            if settler.applies(invocation):
                return await settler.settle(invocation, fenced=fenced)
        return SettlementOutcome.done()

    async def _execute(
        self,
        invocation: RuntimeInvocation,
        resolved_secrets: Mapping[str, str],
    ) -> RuntimeResult:
        # OC-R2: the lane decodes its own sealed bytes and checks them against the envelope.
        binding = execution_binding(invocation.binding)
        plan = _validated_plan(invocation, binding)
        output_binding = invocation.binding.output_schema
        async with self._materializer.prepare(
            binding,
            resolved_secrets,
            output_schema_digest=(
                output_binding.schema_digest if output_binding is not None else None
            ),
        ) as materialized:
            system_prompt, user_prompt = _prompts(invocation)
            if materialized.checkpointer is None or materialized.store is None:
                raise DeepAgentMaterializationError(
                    "local-in-worker cognition requires the registered checkpointer and store"
                )
            # WI-02 (ADR-0061): the receiver's sealed plan, realized on this attempt's backend
            # before any model call; prompt section and files are rendered from it alone.
            transferred = await self._transfer_inputs(
                invocation, materialized, system_prompt, user_prompt
            )
            if transferred is not None and transferred[0].prompt_section:
                user_prompt = f"{user_prompt}\n\n{transferred[0].prompt_section}"
            if transferred is not None and self._knowledge is not None:
                # B1: knowledge_read reaches what the sealed plan holds, under its purpose.
                self._knowledge.scope_reads(transferred[0].plan)
            elif invocation.binding.transfer is not None and self._knowledge is not None:
                # R1: an evaluator without a plan still reads in isolation (nothing reachable).
                self._knowledge.scope_role(invocation.binding.transfer)
            # REQ-CP-DA-008: async subagents reach the Agent Server only through the governed
            # middleware, which reserves and links each child before any provider submission.
            governed_async: list[AgentMiddleware[Any, Any, Any]] = (
                [
                    self._async_subagents.middleware(
                        invocation.binding, binding.async_subagents, resolved_secrets
                    )
                ]
                if self._async_subagents is not None and binding.async_subagents
                else []
            )
            permissions = _effective_permissions(materialized, binding)
            model_calls = _ModelCallObserver()
            # Tracing Stage 2 (F-S2-7): the operation budget ends the turn at the cap, read
            # from the same observer the settlement charges (Tracing Stage 3, R3-F4: plus
            # what a resumed lineage already spent). W1 D41: the cap is the tighter of the
            # reservation and what the authored run budget leaves, tool calls included.
            turn_spend = _TurnSpend(model_calls)
            turn_limits = _turn_limits(invocation)
            budget_stop: list[AgentMiddleware[Any, Any, Any]] = (
                [BudgetStopMiddleware(turn_limits, turn_spend, admit_tool_call=turn_spend.admit)]
                if turn_limits
                else []
            )
            steer_key = invocation.binding.binding_id
            self._steer.open(steer_key)
            agent = _compile(
                materialized,
                binding,
                system_prompt=system_prompt,
                extra_middleware=[
                    *governed_async,
                    *budget_stop,
                    OperatorSteerMiddleware(self._steer, steer_key),
                ],
                name=f"belllabs-{binding.operation_id}",
            )
            state = {
                **materialized.initial_state,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            # FT-B2 (SPEC-02): `/inputs/**` and `.mission/**` are on the backend before the
            # first model call (sandbox upload, or `files` input on the text-only backend).
            context_files = await self._context_seed_files(invocation)
            seeded = await seed_backend_files(materialized.backend, context_files)
            if transferred is not None:
                # The text-only backend reads the plan's files from the `files` channel.
                seeded = {**seeded, **transferred[1].state_files}
            if seeded:
                state["files"] = {**cast(dict[str, object], state.get("files", {})), **seeded}
            transfer_files = () if transferred is None else transferred[0].files
            disclosure_observer = _SkillDisclosureObserver(binding)
            callbacks: list[BaseCallbackHandler] = [disclosure_observer, model_calls]
            checkpointer = materialized.checkpointer
            # REQ-CP-DA-018: classify the unit generation from the checkpointer before any
            # provider work, then act exactly as `CON-CP-CHECKPOINT-LINEAGE-V1` prescribes:
            # submit once, resume without input, reconstruct without invocation, or fail
            # closed as `in_doubt` with typed candidates.
            classified = await _classify(checkpointer, agent, plan)
            source_key = classified.source_key
            # FT-F2: a replacement turn continues the interrupted (or just finished) lineage
            # with the injected item as one more user message, never re-running the prompt.
            follow_up = invocation.follow_up
            captured_as = classified
            queued_follow_up = invocation.follow_up_kind == "queued_instruction"
            queued_message_id = (
                "queued-turn:" + sha256_digest(invocation.follow_up_key)[7:]
                if queued_follow_up and invocation.follow_up_key is not None
                else None
            )
            if queued_follow_up and queued_message_id is None:
                raise ValueError("queued follow-up requires its durable delivery key")
            # A crash can occur after the native input checkpoint but before the mailbox
            # receipt. Reconstruct/resume that same turn; never append its input twice.
            if (
                queued_message_id is not None
                and classified.leaf_snapshot is not None
                and any(
                    getattr(message, "id", None) == queued_message_id
                    for message in classified.leaf_snapshot.values.get("messages", [])
                )
            ):
                follow_up = None
            if follow_up is not None:
                follow_message = {
                    "role": "user",
                    "content": follow_up.content,
                    **({"id": queued_message_id} if queued_message_id is not None else {}),
                }
                if classified.kind == CheckpointClassification.NOT_SUBMITTED:
                    state["messages"] = [
                        {"role": "user", "content": user_prompt},
                        follow_message,
                    ]
                else:
                    captured_as = _follow_up_capture(classified, plan)
            recorder = await self._frame_recorder(invocation, binding, plan, resolved_secrets)
            if recorder is not None:
                # 1.4.4 (P3.4): the exact model input of every call, at the chat-model
                # boundary (after every middleware), beside the two existing observers.
                callbacks.append(_ModelRequestObserver(recorder, follow_up=follow_up is not None))
                # Tracing Stage 3 (R3-F5): each `task` call names the namespace its child runs in.
                callbacks.append(_TaskNamespaceObserver(recorder))
            manifest_digest: str | None = None
            thread_config: RunnableConfig = {
                "configurable": {
                    "thread_id": plan.namespace,
                    "checkpoint_ns": ROOT_CHECKPOINT_NS,
                }
            }
            prior_messages: list[BaseMessage] = []
            queued_usage_remainder: dict[str, int] = {}
            # RRM-008: the Activity heartbeat reads the latest durable root checkpoint of the
            # namespace while cognition runs (keys only; REQ-CP-EXEC-008 step 3).
            register_checkpoint_reader(_latest_checkpoint_reader(checkpointer, plan))
            try:
                if recorder is not None:
                    await recorder.begin(
                        body={
                            "classification": classified.kind.value,
                            "operation_id": binding.operation_id,
                        }
                    )
                    # 1.4.4 (P3.7): the environment the attempt starts from, as one frame.
                    manifest_digest = await recorder.environment(
                        materialization_manifest(
                            getattr(materialized, "manifest_facts", None) or {},
                            _context_manifest_files(
                                invocation, materialized, (*context_files, *transfer_files)
                            ),
                        )
                    )
                if source_key is not None:
                    prior_snapshot = await agent.aget_state(
                        root_checkpoint_config(plan.namespace, source_key.checkpoint_id)
                    )
                    prior_messages = cast(
                        list[BaseMessage], prior_snapshot.values.get("messages", [])
                    )
                queued_source = invocation.follow_up_source_checkpoint
                if queued_source is not None:
                    if (
                        queued_source.thread_id != plan.namespace
                        or not queued_source.is_root
                        or queued_source.checkpointer_ref_digest != plan.checkpointer_ref_digest
                    ):
                        raise CheckpointLineageError(
                            "queued turn source is outside its admitted lineage"
                        )
                    queued_snapshot = await agent.aget_state(
                        root_checkpoint_config(
                            plan.namespace,
                            queued_source.checkpoint_id,
                        )
                    )
                    if not all(
                        (queued_snapshot.metadata or {}).get(key) == value
                        for key, value in plan.metadata_stamps().items()
                    ):
                        raise CheckpointLineageError("queued turn source checkpoint stamps differ")
                    native_usage = _usage(
                        invocation,
                        cast(
                            list[BaseMessage],
                            queued_snapshot.values.get("messages", []),
                        )[len(prior_messages) :],
                    )
                    # Parent messages already carry their usage. Sync children do not;
                    # retain that previously observed remainder through continuation/replay.
                    queued_usage_remainder = {
                        dimension: max(0, amount - native_usage.amounts.get(dimension, 0))
                        for dimension, amount in invocation.follow_up_prior_usage.items()
                    }
                if classified.leaf_snapshot is not None:
                    turn_spend.resume_from(
                        invocation,
                        cast(
                            list[BaseMessage],
                            classified.leaf_snapshot.values.get("messages", []),
                        ),
                        prior_messages,
                        usage_remainder=queued_usage_remainder,
                    )
                if (
                    follow_up is not None
                    and classified.kind != CheckpointClassification.NOT_SUBMITTED
                ):
                    follow_config: RunnableConfig = {
                        "configurable": {
                            **thread_config["configurable"],
                            "checkpoint_id": classified.leaf_id,
                        },
                        "metadata": plan.invocation_metadata(),
                        "callbacks": callbacks,
                    }
                    result = await _invoke(
                        agent,
                        {"messages": [follow_message]},
                        context=materialized.context,
                        config=follow_config,
                        recorder=recorder,
                    )
                    snapshot = await agent.aget_state(
                        await _own_result_config(checkpointer, plan, captured_as)
                    )
                elif classified.kind == CheckpointClassification.TERMINAL_UNOBSERVED:
                    # Terminal reconstruction: the result is the stamped leaf's state.
                    assert classified.leaf_snapshot is not None
                    snapshot = classified.leaf_snapshot
                    result = cast(dict[str, Any], dict(snapshot.values))
                else:
                    pinned = (
                        classified.leaf_id
                        if classified.kind == CheckpointClassification.INTERRUPTED
                        else (source_key.checkpoint_id if source_key is not None else None)
                    )
                    # REQ-CP-DA-016/017: exact namespace thread, root checkpoint_ns, pinned
                    # to the expected source (submit) or to the interrupted leaf (resume),
                    # and scalar stamps copied onto every checkpoint.
                    config: RunnableConfig = {
                        "configurable": {
                            **thread_config["configurable"],
                            **({"checkpoint_id": pinned} if pinned is not None else {}),
                        },
                        "metadata": plan.invocation_metadata(),
                        "callbacks": callbacks,
                    }
                    # A resume never re-appends the submitted input: it continues the
                    # pending tasks of the pinned checkpoint with no input.
                    invoke_input = (
                        None if classified.kind == CheckpointClassification.INTERRUPTED else state
                    )
                    result = await _invoke(
                        agent,
                        invoke_input,
                        context=materialized.context,
                        config=config,
                        recorder=recorder,
                    )
                    # Capture this attempt's own result tip, never the thread's latest
                    # checkpoint (which a superseded attempt may have written).
                    snapshot = await agent.aget_state(
                        await _own_result_config(checkpointer, plan, classified)
                    )
                actual_state = cast(dict[str, Any], snapshot.values)
                messages = cast(
                    list[BaseMessage], actual_state.get("messages", result.get("messages", []))
                )
                capture = await _capture_result(
                    checkpointer,
                    plan,
                    source_key,
                    snapshot_config=snapshot.config,
                    pending=bool(snapshot.next or snapshot.interrupts),
                    classification=captured_as.kind,
                    summary={
                        "state_keys": sorted(actual_state),
                        "message_count": len(messages),
                        "step": (snapshot.metadata or {}).get("step"),
                    },
                )
                final = next(
                    (item for item in reversed(messages) if isinstance(item, AIMessage)), None
                )
                output_text = _message_text(final) if final is not None else ""
                # Tracing Stage 3 (R3-F1): `structured_response` persists in the thread across
                # invocations; only one this unit's lineage wrote is its answer.
                structured = _structured_output(
                    (
                        result.get("structured_response", actual_state.get("structured_response"))
                        if await _structured_response_written(
                            checkpointer, plan, source_key, snapshot.config
                        )
                        else None
                    ),
                    output_text,
                )
                inspection = _inspect_state(
                    binding,
                    actual_state,
                    messages,
                    materialized.resolved_attachments,
                    disclosure_observer.disclosed_skills,
                    permissions is not None,
                )
                # RRM-009 (REQ-CP-DA-014): the agent's writable-slot files become durable
                # workspace candidates before the result settles; a capture failure after a
                # terminal checkpoint is classified by the narrowed post-dispatch rule.
                captured = await self._capture_workspace_outputs(
                    materialized.backend, invocation.binding, actual_state
                )
                inspection["workspace_candidates"] = captured
                # OVE-204 slice 5: everything the agent could see at this settled boundary,
                # digested by raw bytes; bodies within the profile's caps. Never raises.
                closure_ref = await self._record_closure(
                    materialized.backend,
                    binding,
                    actual_state,
                    boundary="attempt_settled",
                    result_key=capture.result_key,
                    resolved_secrets=resolved_secrets,
                    candidates=captured,
                )
                if closure_ref is not None:
                    inspection["workspace_closure"] = closure_ref
                # FT-B2: output refs name only what this attempt registered; model-emitted
                # refs that are not this attempt's captures are dropped with a warning.
                output_refs, structured, warnings = _attempt_output_refs(
                    captured,
                    structured if isinstance(structured, dict) else None,
                    drop_unregistered=self._drop_unregistered_output_refs,
                )
                if warnings:
                    inspection["provenance_warnings"] = warnings
                own_messages = messages[len(prior_messages) :]
                # REQ-CP-DA-007: in-process sync subagents spend the parent's reservation, so
                # their model calls (observed at the chat-model boundary; they never enter the
                # parent's messages) are part of the operation's observed usage.
                subordinate_calls = model_calls.calls_outside(messages)
                usage = _usage(
                    invocation,
                    own_messages,
                    subordinate_calls,
                    subordinate_tool_calls=model_calls.tool_calls_outside(messages),
                )
                if queued_usage_remainder:
                    usage = usage.model_copy(
                        update={
                            "amounts": {
                                dimension: usage.amounts.get(dimension, 0)
                                + queued_usage_remainder.get(dimension, 0)
                                for dimension in usage.amounts.keys()
                                | queued_usage_remainder.keys()
                            }
                        }
                    )
                inspection["capability_lineage"] = capability_lineage(
                    binding,
                    own_messages,
                    usage_amounts=usage.amounts,
                    model_calls=(
                        *_message_usage(own_messages),
                        *({**call, "scope": "subordinate"} for call in subordinate_calls),
                    ),
                    disclosed_skills=disclosure_observer.disclosed_skills,
                    operation_secret_refs=invocation.binding.secret_refs,
                )
                if recorder is not None:
                    await recorder.finish(
                        messages=messages,
                        own_messages=own_messages,
                        output_text=output_text,
                        structured_keys=sorted(structured) if isinstance(structured, dict) else (),
                        checkpoint_id=capture.result_key.checkpoint_id,
                    )
                    await self._project_frame_facts(recorder, binding)
                # P1 turn 4: one `CognitionPointObservation` per root checkpoint this attempt's
                # lineage wrote (source exclusive, result inclusive), folded from the saver;
                # 1.4.4: plus the nested checkpoints of every sync subagent the recorder saw,
                # the manifest digest on the input point and the workspace candidates on the
                # result point.
                points = await self._collect_points(
                    checkpointer,
                    plan,
                    capture,
                    recorder,
                    interrupted_leaf=(
                        classified.leaf_id
                        if follow_up is not None
                        and not queued_follow_up
                        and classified.kind != CheckpointClassification.NOT_SUBMITTED
                        else None
                    ),
                    manifest_digest=manifest_digest,
                    workspace_checkpoint_ref=closure_ref,
                )
                return RuntimeResult(
                    output_text=output_text,
                    structured_output=structured,
                    output_refs=output_refs,
                    usage=usage,
                    provider_run_id=_provider_run_id(messages),
                    event_payloads=(inspection,),
                    checkpoint=capture,
                    cognition_points=points,
                    # W1 D41: a turn the budget ended settles `budget_exceeded`, typed.
                    budget_stop=_budget_stop_of(own_messages),
                )
            except CheckpointLineageError as error:
                if recorder is not None:
                    await recorder.fail(error, unknown_state=True)
                    await self._project_frame_facts(recorder, binding)
                raise
            except Exception as error:
                # The settlement keeps only the error type; the worker log (already secret-
                # redacted, `install_log_redaction`) keeps the traceback for the operator.
                logger.warning(
                    "deep agents invocation %s failed: %s",
                    plan.invocation_id,
                    type(error).__name__,
                    exc_info=error,
                )
                if recorder is not None:
                    await recorder.fail(error, unknown_state=False)
                    await self._project_frame_facts(recorder, binding)
                # REQ-CP-RUN-007 (narrowed): report whether a terminal result exists after the
                # failure, so the boundary settles `failed` only when none does. RRM-008: the
                # latest durable checkpoint of a unique stamped lineage travels with the
                # failure, so the settlement advances the namespace head over the partial
                # lineage instead of stranding it.
                terminal, candidates, latest = await _terminal_result_may_exist(
                    checkpointer, agent, plan
                )
                partial_points: tuple[CognitionPointObservation, ...] = ()
                if isinstance(latest, CheckpointCapture):
                    try:
                        # OVE-204 slice 5: the workspace at the failed attempt's latest
                        # durable checkpoint, best effort (the sandbox is still alive).
                        failed_ref = await self._record_closure_at(
                            agent,
                            plan,
                            materialized.backend,
                            binding,
                            latest.result_key,
                            boundary="attempt_failed",
                            resolved_secrets=resolved_secrets,
                        )
                        partial_points = await self._collect_points(
                            checkpointer,
                            plan,
                            latest,
                            recorder,
                            workspace_checkpoint_ref=failed_ref,
                        )
                    except Exception:  # the failure is the outcome; points are best effort
                        # Tracing Stage 3 (R3-F16): the operator gets the traceback.
                        logger.warning(
                            "points of failed invocation %s", plan.invocation_id, exc_info=True
                        )
                raise RuntimeInvocationFailure(
                    type(error).__name__,
                    terminal_result_observed=terminal,
                    # W1 D40: what the L1 retry could not recover, typed for the boundary.
                    failure_class=(
                        TRANSIENT_TRANSPORT if unsent_transport_failure(error) else None
                    ),
                    candidates=candidates,
                    latest_capture=latest,
                    usage=_observed_usage(invocation, model_calls, spent=turn_spend()),
                    cognition_points=partial_points,
                ) from error
            finally:
                register_checkpoint_reader(None)

    async def observe_latest(
        self,
        invocation: RuntimeInvocation,
        resolved_secrets: Mapping[str, str],
    ) -> RuntimeResult:
        """RRM-008 (REQ-CP-EXEC-008 step 3): the latest durable checkpoint of a unit generation
        that is being cancelled, with the usage its completed model calls already incurred.

        No cognition is invoked and nothing is resumed. A unit classified `interrupted` or
        `terminal_unobserved` yields its stamped leaf as the result checkpoint (the partial
        evidence); a `not_submitted` unit yields no checkpoint. Anything ambiguous raises
        `CheckpointLineageInDoubt` exactly as a dispatch would.
        """

        # OC-R2: the lane decodes its own sealed bytes and checks them against the envelope.
        binding = execution_binding(invocation.binding)
        plan = _validated_plan(invocation, binding)
        async with self._materializer.prepare(binding, resolved_secrets) as materialized:
            if materialized.checkpointer is None or materialized.store is None:
                raise DeepAgentMaterializationError(
                    "local-in-worker cognition requires the registered checkpointer and store"
                )
            system_prompt, _user_prompt = _prompts(invocation)
            agent = _compile(
                materialized,
                binding,
                system_prompt=system_prompt,
                extra_middleware=[],
                name=f"belllabs-{binding.operation_id}",
            )
            checkpointer = materialized.checkpointer
            classified = await _classify(checkpointer, agent, plan)
            if classified.kind == CheckpointClassification.NOT_SUBMITTED:
                return RuntimeResult(output_text="", checkpoint=None)
            assert classified.leaf_snapshot is not None
            snapshot = classified.leaf_snapshot
            messages = cast(list[BaseMessage], dict(snapshot.values).get("messages", []))
            prior: list[BaseMessage] = []
            if classified.source_key is not None:
                prior_snapshot = await agent.aget_state(
                    root_checkpoint_config(plan.namespace, classified.source_key.checkpoint_id)
                )
                prior = cast(list[BaseMessage], prior_snapshot.values.get("messages", []))
            capture = await _capture_result(
                checkpointer,
                plan,
                classified.source_key,
                snapshot_config=snapshot.config,
                pending=bool(snapshot.next or snapshot.interrupts),
                classification=classified.kind,
                summary={
                    "state_keys": sorted(dict(snapshot.values)),
                    "message_count": len(messages),
                    "step": (snapshot.metadata or {}).get("step"),
                },
                allow_pending=True,
            )
            # OVE-204 slice 5: the cancelled unit's workspace at its stamped leaf, best effort;
            # the closure row names the result point the reconciler records.
            await self._record_closure(
                materialized.backend,
                binding,
                dict(snapshot.values),
                boundary="attempt_cancelled",
                result_key=capture.result_key,
                resolved_secrets=resolved_secrets,
            )
            final = next((item for item in reversed(messages) if isinstance(item, AIMessage)), None)
            return RuntimeResult(
                output_text=_message_text(final) if final is not None else "",
                usage=_usage(invocation, messages[len(prior) :]),
                provider_run_id=_provider_run_id(messages),
                checkpoint=capture,
            )

    async def _record_closure(
        self,
        backend: BackendProtocol,
        binding: DeepAgentExecutionBinding,
        state: Mapping[str, Any],
        *,
        boundary: ClosureBoundary,
        result_key: QualifiedCheckpointKey,
        resolved_secrets: Mapping[str, str],
        candidates: Sequence[Mapping[str, object]] = (),
    ) -> str | None:
        """Capture and record the attempt's Workspace Closure; its ref, or None (OVE-204).

        Best effort at every boundary: a closure that cannot be captured or recorded is
        logged and the attempt's outcome is unchanged (the result point then has no ref).
        """

        unit = binding.runtime_unit
        policy = self._closure_policy
        if self._closures is None or unit is None or not policy.closure_enabled:
            return None
        try:
            captured = await capture_closure(
                backend,
                binding.workspace,
                state,
                run_id=unit.belllabs_run_id,
                unit_key=unit.unit_key,
                execution_generation=binding.execution_generation,
                harness_execution_id=str(
                    harness_execution_id(
                        request_scope=unit.request_scope,
                        run_key=unit.belllabs_run_id,
                        activation_key=unit.unit_key,
                        attempt_no=binding.execution_generation,
                        lane=LaneProfile.DEEP_AGENTS.value,
                    )
                ),
                result_key=result_key,
                boundary=boundary,
                policy=policy,
                secret_values=tuple(value for value in resolved_secrets.values() if value),
                candidates=candidates,
                files_digest_channel=files_channel_digest(state.get("files")),
            )
            if captured is None:
                return None
            closure = captured.closure
            await self._closures.put(
                closure,
                captured.bodies,
                request_scope=unit.request_scope,
                retain_until=retain_until(policy, closure.recorded_at),
            )
        except Exception:
            logger.warning(
                "workspace closure of %s at %s was not recorded",
                unit.unit_key,
                boundary,
                exc_info=True,
            )
            return None
        return closure.ref

    async def _record_closure_at(
        self,
        agent: Any,
        plan: CheckpointInvocationPlan,
        backend: BackendProtocol,
        binding: DeepAgentExecutionBinding,
        key: QualifiedCheckpointKey,
        *,
        boundary: ClosureBoundary,
        resolved_secrets: Mapping[str, str],
    ) -> str | None:
        """The closure at one durable root checkpoint (the failed attempt's latest)."""

        if self._closures is None or not self._closure_policy.closure_enabled:
            return None
        try:
            snapshot = await agent.aget_state(
                root_checkpoint_config(plan.namespace, key.checkpoint_id)
            )
        except Exception:
            logger.warning("workspace closure state of %s unreadable", key, exc_info=True)
            return None
        return await self._record_closure(
            backend,
            binding,
            cast(Mapping[str, Any], snapshot.values),
            boundary=boundary,
            result_key=key,
            resolved_secrets=resolved_secrets,
        )

    async def _collect_points(
        self,
        checkpointer: BaseCheckpointSaver[Any],
        plan: CheckpointInvocationPlan,
        capture: CheckpointCapture,
        recorder: DeepAgentFrameRecorder | None,
        **facts: Any,
    ) -> tuple[CognitionPointObservation, ...]:
        """The attempt's points with this adapter's saver locator and walk budget."""

        return await collect_points(
            checkpointer,
            plan,
            capture,
            recorder=recorder,
            saver_locator_digest=self._saver_locators.get(plan.checkpointer_ref_digest),
            budget_seconds=self._points_walk_budget_ms / 1000,
            **facts,
        )

    async def _frame_recorder(
        self,
        invocation: RuntimeInvocation,
        binding: DeepAgentExecutionBinding,
        plan: CheckpointInvocationPlan,
        resolved_secrets: Mapping[str, str],
    ) -> DeepAgentFrameRecorder | None:
        """Open this attempt's harness execution in the Native Event Store (SPEC-03).

        One harness execution per runtime-unit attempt (attempt = execution generation);
        the native session is the cognitive namespace (thread) and the native turn is the
        invocation. Every resolved secret value is redacted from every frame body.
        """

        unit = binding.runtime_unit
        if self._frames is None or unit is None:
            return None
        lane = LaneProfile.DEEP_AGENTS
        capture = self._frame_capture
        policy = capture.policy if capture is not None else None
        excerpt_cap = policy.excerpt_cap_bytes if policy is not None else self._frame_excerpt_cap
        start = HarnessExecutionStart(
            harness_execution_id=harness_execution_id(
                request_scope=unit.request_scope,
                run_key=unit.belllabs_run_id,
                activation_key=unit.unit_key,
                attempt_no=binding.execution_generation,
                lane=lane.value,
            ),
            request_scope=unit.request_scope,
            run_key=unit.belllabs_run_id,
            activation_key=unit.unit_key,
            attempt_no=binding.execution_generation,
            generation=binding.execution_generation,
            lane_profile=lane,
            native_session_ref=plan.namespace,
            runtime_kind="deep_agent",
            provider_kind="langgraph",
            placement_kind=binding.placement,
            intended_binding_digest=binding.binding_digest,
            launch_key=plan.invocation_id,
            native_identity={
                "checkpointer_ref_digest": plan.checkpointer_ref_digest,
                "operation_id": binding.operation_id,
                "binding_id": invocation.binding.binding_id,
                "frame_capture_profile": policy.name if policy is not None else "none",
            },
        )
        try:
            handle = await self._frames.open_execution(start)
        except HarnessExecutionNotFound as error:
            raise DeepAgentMaterializationError(
                "provider frames require the recorded runtime unit attempt"
            ) from error
        secrets = tuple(value for value in resolved_secrets.values() if value)
        writer = FrameWriter(
            self._frames,
            handle,
            excerpt_cap_bytes=excerpt_cap,
            secret_values=secrets,
            promoter=capture.promoter if capture is not None else None,
            capture=policy if policy is not None else STANDARD_PROFILE,
        )
        return DeepAgentFrameRecorder(
            writer,
            thread_id=plan.namespace,
            invocation_id=plan.invocation_id,
            secret_values=secrets,
            excerpt_cap_bytes=excerpt_cap,
        )

    async def _project_frame_facts(
        self, recorder: DeepAgentFrameRecorder, binding: DeepAgentExecutionBinding
    ) -> None:
        """Apply this attempt's closing-frame facts to run state, best effort.

        Frames are already durable, so a projection failure only delays the derived mission
        events: the next projection re-derives every fact from the frames and applies the
        unapplied ones. The attempt outcome of a provider `finished` is deferred to the
        operation settlement, which owns the Deep Agents Completion Candidate.
        """

        unit = binding.runtime_unit
        if self._frame_facts is None or unit is None:
            return
        try:
            await self._frame_facts.project(
                FrameFactTarget.from_handle(
                    recorder.handle, run_key=unit.belllabs_run_id, unit_key=unit.unit_key
                ),
                completion_policy="deferred",
            )
        except Exception:
            logger.warning(
                "frame facts were not applied; the next projection re-derives them",
                exc_info=True,
            )

    async def _context_seed_files(
        self, invocation: RuntimeInvocation
    ) -> tuple[tuple[str, bytes], ...]:
        """Verified bytes of the Context Packet's read-only slots, by logical path."""

        slots = [
            slot
            for slot in invocation.binding.workspace.slot_bindings
            if is_context_input_slot(slot)
        ]
        if not slots:
            return ()
        if self._context_inputs is None:
            raise DeepAgentMaterializationError(
                "context packet inputs are bound but no durable input reader is composed"
            )
        files: list[tuple[str, bytes]] = []
        sources = [(slot.logical_path, slot.durable_ref, slot.content_digest) for slot in slots]
        for logical_path, durable_ref, content_digest in sources:
            assert durable_ref is not None and content_digest is not None
            content = await self._context_inputs.retrieve(durable_ref)
            if bytes_digest(content) != content_digest:
                raise DeepAgentMaterializationError(
                    f"context input digest mismatch for {logical_path}"
                )
            files.append((logical_path, content))
        return tuple(files)

    async def _transfer_inputs(
        self,
        invocation: RuntimeInvocation,
        materialized: MaterializedDeepAgentArguments,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[MaterializedTransfer, DeepAgentReceiverBackend] | None:
        selection = invocation.binding.transfer
        if selection is None or not selection.inputs:
            # No admitted input (a first invocation): the host state alone, nothing invented.
            return None
        if self._transfer is None:
            # A selection with no composed materializer never fails open.
            raise ContextDeliveryBlocked("context_transfer_unwired")
        reserved = [
            slot.logical_path
            for slot in invocation.binding.workspace.slot_bindings
            if is_context_input_slot(slot)
        ]
        return await materialize_transfer(
            self._transfer,
            invocation,
            backend=materialized.backend,
            overhead=measured_overhead(
                system_prompt, user_prompt, materialized.tools, materialized.skills
            ),
            tool_names=[tool.name for tool in materialized.tools],
            reserved_paths=reserved,
            access=(
                None if self._knowledge is None else await self._knowledge.access_for(invocation)
            ),
        )

    async def _capture_workspace_outputs(
        self,
        backend: BackendProtocol,
        binding: OperationExecutionBinding,
        state: dict[str, Any],
    ) -> list[dict[str, object]]:
        if self._workspace_outputs is None:
            return []
        captured: list[dict[str, object]] = []
        for logical_path, content in await _slot_files(
            backend, binding.workspace.exclusive_write_paths, state
        ):
            candidate = await self._workspace_outputs.capture(binding, logical_path, content)
            captured.append(
                {
                    "logical_path": candidate.logical_path,
                    "output_slot": candidate.output_slot,
                    "candidate_id": candidate.candidate_id,
                    "content_digest": candidate.content_digest,
                    "size_bytes": candidate.size_bytes,
                    "media_type": candidate.media_type,
                }
            )
        return captured


def _context_manifest_files(
    invocation: RuntimeInvocation,
    materialized: MaterializedDeepAgentArguments,
    context_files: Sequence[tuple[str, bytes]],
) -> tuple[ManifestFile, ...]:
    """The Context Packet files the adapter seeded, with their slot and where they went:
    the `files` state channel on the text-only backend, a sandbox upload otherwise."""

    destination = (
        SOURCE_STATE_CHANNEL
        if isinstance(materialized.backend, StateBackend)
        else SOURCE_SANDBOX_UPLOAD
    )
    slots = {
        slot.logical_path: slot.slot_name
        for slot in invocation.binding.workspace.slot_bindings
        if is_context_input_slot(slot)
    }
    return tuple(
        ManifestFile(path=path, slot=slots.get(path), content=content, destination=destination)
        for path, content in context_files
    )


async def _invoke(
    agent: Any,
    invoke_input: Any,
    *,
    context: Any,
    config: RunnableConfig,
    recorder: DeepAgentFrameRecorder | None,
) -> dict[str, Any]:
    """Run one invocation; with a frame recorder, stream it and persist every part.

    The streamed form returns exactly what `ainvoke` returns: the root graph's latest
    values, with LangGraph interrupts under `__interrupt__`.
    """

    if recorder is None:
        return cast(
            dict[str, Any],
            await agent.ainvoke(invoke_input, context=context, config=config, durability="sync"),
        )
    latest: Any = None
    interrupts: list[Any] = []
    async for part in agent.astream(
        invoke_input,
        config,
        context=context,
        # P1 turn 4: `checkpoints` keys every step's frames by the root checkpoint it wrote.
        stream_mode=["updates", "messages", "custom", "values", "checkpoints"],
        subgraphs=True,
        version="v2",
        durability="sync",
    ):
        if part.get("type") == "values":
            if not part.get("ns"):
                latest = part.get("data")
                interrupts.extend(part.get("interrupts") or ())
            continue
        await recorder.observe(part)
    await recorder.flush()
    result = dict(latest) if isinstance(latest, Mapping) else {}
    if interrupts:
        result["__interrupt__"] = interrupts
    return result


def _attempt_output_refs(
    captured: list[dict[str, object]],
    structured: dict[str, object] | None,
    *,
    drop_unregistered: bool = False,
) -> tuple[tuple[str, ...], dict[str, object] | None, list[dict[str, object]]]:
    """This attempt's output refs, the reconciled structured output and provenance warnings.

    Registered refs are the durable refs of the workspace candidates this attempt captured
    (custody evidence; promotion stays a governed decision). Every model-emitted
    ``output_refs`` entry that is not one of them gets a provenance warning. With
    ``drop_unregistered`` the key is rewritten to the registered refs only (so the family's
    merge of structured output cannot reintroduce unregistered strings); otherwise the
    structured output is left untouched (a family that reads the model's key keeps reading
    it) and only ``RuntimeResult.output_refs`` carries the registered refs.
    """

    own = tuple(
        sorted(
            {
                workspace_candidate_ref(str(item["candidate_id"]))
                for item in captured
                if item.get("candidate_id")
            }
        )
    )
    warnings: list[dict[str, object]] = []
    if structured is None or "output_refs" not in structured:
        return own, structured, warnings
    emitted = structured.get("output_refs")
    values = emitted if isinstance(emitted, list | tuple) else [emitted]
    emitted_refs = [str(value) for value in values if value is not None]
    for value in emitted_refs:
        if value not in own:
            warnings.append(
                {
                    "kind": "provenance",
                    ("dropped_output_ref" if drop_unregistered else "unregistered_output_ref"): (
                        value
                    ),
                    "reason": "not_registered_by_this_attempt",
                }
            )
    if drop_unregistered:
        return own, {**structured, "output_refs": list(own)}, warnings
    return own, structured, warnings


def _effective_permissions(
    materialized: MaterializedDeepAgentArguments, binding: DeepAgentExecutionBinding
) -> list[FilesystemPermission] | None:
    """Framework filesystem permissions apply only without an executable sandbox."""

    if isinstance(materialized.backend, SandboxBackendProtocol):
        return None
    return _permissions(binding)


_IMPLICIT_CHILD_DISABLED: set[str] = set()
_NO_IMPLICIT_CHILD = HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
)


def _disable_implicit_general_purpose_child(model: BaseChatModel, provider: str) -> None:
    """Keep deepagents from auto-adding its `general-purpose` child (P1 subagents, Q2).

    deepagents 0.7.5 inserts a `general-purpose` SubAgent with every parent tool into any
    agent whose harness profile does not disable it. Mission Control declares and receipts
    its children explicitly (a `capabilities: inherit` profile is that child's explicit form),
    so the implicit one is switched off through the harness profile registry under the keys
    `create_deep_agent` consults for a pre-built model: the binding's provider and the
    provider the model reports for tracing (the two agree for ChatOpenAI; a deterministic
    test model reports its class). Registrations merge additively, so a provider profile
    deepagents ships keeps its other settings. The lookup is then replayed and a profile that
    would still add the child is a runtime drift, never a silent extra child.
    """

    keys = {provider}
    try:
        reported = model._get_ls_params().get("ls_provider")
    except Exception:  # pragma: no cover - a model without tracing params
        reported = None
    if reported:
        keys.add(str(reported))
    for key in sorted(keys - _IMPLICIT_CHILD_DISABLED):
        register_harness_profile(key, _NO_IMPLICIT_CHILD)
        _IMPLICIT_CHILD_DISABLED.add(key)
    effective = _harness_profile_for_model(model, None).general_purpose_subagent
    if effective is None or effective.enabled is not False:
        raise DeepAgentRuntimeDrift(
            "deepagents would add an implicit general-purpose child; Mission Control runs "
            "declared children only"
        )


def _subagent_specs(
    materialized: MaterializedDeepAgentArguments,
    stops: Sequence[AgentMiddleware[Any, Any, Any]] = (),
) -> list[SubAgent]:
    """Sync subagent specs; their framework permissions follow the parent's rule.

    deepagents refuses filesystem permissions beside an executable sandbox, so a child's
    rules apply only without one (the parent's `_effective_permissions` rule).

    Tracing Stage 3 (sync-child stops): every child also runs the parent's turn stops (the
    invocation's budget, whose spend already includes the children's calls, and the Stop
    Fence), so a cancelled or exhausted turn stops inside a running child too, and its own
    summarizer checks them before it would summarize (R3-F2 in the child). deepagents keeps
    a spec's middleware when it recompiles a child for a dynamic response format.
    """

    specs: list[SubAgent] = []
    sandboxed = isinstance(materialized.backend, SandboxBackendProtocol)
    for raw in materialized.subagents:
        spec = dict(raw)
        if sandboxed:
            spec.pop("permissions", None)
        if stops:
            model = spec.get("model", materialized.model)
            guard = (
                [
                    StopGuardedSummarizationMiddleware.guarding(
                        model, materialized.backend, cast(Sequence[TurnStop], stops)
                    )
                ]
                if isinstance(model, BaseChatModel)
                else []
            )
            spec["middleware"] = [*cast(Sequence[Any], spec.get("middleware", ())), *guard, *stops]
        specs.append(cast(SubAgent, spec))
    return specs


def _turn_stops(
    middleware: Sequence[AgentMiddleware[Any, Any, Any]],
) -> list[AgentMiddleware[Any, Any, Any]]:
    """The turn stops in a middleware list, in order (the fence first, then the budget)."""

    return [
        item for item in middleware if isinstance(item, FenceStopMiddleware | BudgetStopMiddleware)
    ]


def _compile(
    materialized: MaterializedDeepAgentArguments,
    binding: DeepAgentExecutionBinding,
    *,
    system_prompt: str,
    extra_middleware: list[AgentMiddleware[Any, Any, Any]],
    name: str,
) -> Any:
    """The only `create_deep_agent` call: local cognition and hosted async graphs share it.

    A hosted graph has no checkpointer or store (the Agent Server owns them) and no structured
    response; local cognition always has the registered pair.
    """

    _disable_implicit_general_purpose_child(materialized.model, binding.model.provider)
    permissions = _effective_permissions(materialized, binding)
    # Sprint B: a configured `deep_agents.filesystem` replaces the stock middleware by name;
    # it needs the effective permissions, which only this compile step knows.
    filesystem = filesystem_replacement(
        getattr(binding, "agent_configuration", None), materialized.backend, permissions
    )
    middleware = [
        *materialized.middleware,
        *extra_middleware,
        *([filesystem] if filesystem is not None else []),
        # W1 D40 (L1): innermost, inside the fence and budget stops, so a stopped turn is
        # never retried; only a model call that never reached the provider is.
        GovernedModelRetryMiddleware(),
    ]
    stops = _turn_stops(middleware)
    # Tracing Stage 3 (R3-F2): deepagents puts Mission Control's middleware inside its core
    # stack, i.e. inside the summarization slot the observed summarizer takes, so that
    # summarizer checks the turn stops before it would make its own paid call.
    for item in middleware:
        if isinstance(item, ObservedSummarizationMiddleware):
            item.stops = cast(tuple[TurnStop, ...], tuple(stops))
    return create_deep_agent(
        model=materialized.model,
        system_prompt=system_prompt,
        # Sprint B: provider-executed dict tools ride beside the agent's own tools.
        tools=[*materialized.tools, *getattr(materialized, "provider_tools", ())],
        middleware=middleware,
        subagents=_subagent_specs(materialized, stops),
        skills=list(materialized.skills),
        permissions=permissions,
        backend=materialized.backend,
        state_schema=materialized.state_schema,
        context_schema=materialized.context_schema,
        checkpointer=materialized.checkpointer,
        store=materialized.store,
        response_format=materialized.response_format,
        name=name,
    )


def _validated_plan(
    invocation: RuntimeInvocation, binding: DeepAgentExecutionBinding
) -> CheckpointInvocationPlan:
    plan = invocation.checkpoint_plan
    if plan is None or binding.cognitive_session_namespace is None:
        raise DeepAgentMaterializationError(
            "Deep Agent invocations require a frozen namespace and checkpoint lineage plan"
        )
    unit = binding.runtime_unit
    if (
        unit is None
        or plan.unit_key != unit.unit_key
        or plan.execution_generation != binding.execution_generation
        or plan.namespace != binding.cognitive_session_namespace
        or plan.binding_digest != binding.binding_digest
        or plan.state_schema_digest != binding.cognitive_state_schema.schema_digest
        or plan.checkpointer_ref_digest != binding.checkpointer_ref.digest
    ):
        raise DeepAgentMaterializationError(
            "checkpoint lineage plan does not match the exact Deep Agent binding"
        )
    return plan


@dataclass(frozen=True)
class _Classified:
    kind: CheckpointClassification
    source_key: QualifiedCheckpointKey | None
    leaf_id: str | None = None
    leaf_snapshot: StateSnapshot | None = None


def _qualified(plan: CheckpointInvocationPlan, item: CheckpointTuple) -> QualifiedCheckpointKey:
    return QualifiedCheckpointKey(
        checkpointer_ref_digest=plan.checkpointer_ref_digest,
        thread_id=plan.namespace,
        checkpoint_ns=ROOT_CHECKPOINT_NS,
        checkpoint_id=str(item.config["configurable"]["checkpoint_id"]),
        parent_checkpoint_id=checkpoint_parent_id(item),
    )


def _stamped(item: CheckpointTuple, plan: CheckpointInvocationPlan) -> bool:
    return all(item.metadata.get(key) == value for key, value in plan.metadata_stamps().items())


async def _classify(
    checkpointer: BaseCheckpointSaver[Any],
    agent: Any,
    plan: CheckpointInvocationPlan,
) -> _Classified:
    """`CON-CP-CHECKPOINT-LINEAGE-V1` classification of one unit generation.

    Descendants of the expected source are the root-namespace checkpoints whose parent chain
    reaches it (for a new namespace, every root checkpoint). None means `not_submitted`.
    Exactly one stamped lineage with no unstamped or foreign descendant is `interrupted`
    when its leaf has pending tasks and `terminal_unobserved` when it has none. Anything
    else, including a pending LangGraph interrupt, is `in_doubt`. An operator-accepted
    descendant (`accept_descendant`) is classified as if it were the unique leaf; stamped
    descendants it has since gained (a resumed run) are followed to their unique leaf.
    """

    source = plan.expected_source
    thread_config: RunnableConfig = {
        "configurable": {"thread_id": plan.namespace, "checkpoint_ns": ROOT_CHECKPOINT_NS}
    }
    source_key: QualifiedCheckpointKey | None = None
    if source is not None:
        recorded = await checkpointer.aget_tuple(
            root_checkpoint_config(plan.namespace, source.checkpoint_id)
        )
        if recorded is None:
            raise CheckpointLineageInDoubt(
                "the recorded source checkpoint is missing", reason="missing_checkpoint"
            )
        if recorded.metadata.get(STAMP_STATE_SCHEMA_DIGEST) != plan.state_schema_digest:
            raise IncompatibleCheckpointSchema(
                "source checkpoint state-schema stamp differs from the binding (REQ-CP-CS-007)"
            )
        if checkpoint_parent_id(recorded) != source.parent_checkpoint_id:
            raise CheckpointLineageInDoubt(
                "the source checkpoint's ancestry differs from its record",
                reason="ancestry_mismatch",
            )
        source_key = _qualified(plan, recorded)
    items: dict[str, CheckpointTuple] = {}
    # 1.4.4 (P6.1): the saver lists newest first and checkpoint ids are time-ordered, so
    # the walk stops at the expected source: only the suffix after it can descend from it.
    stop_at = source.checkpoint_id if source is not None else None
    async for item in checkpointer.alist(thread_config, limit=MAX_LINEAGE_WALK + 1):
        checkpoint_id = str(item.config["configurable"]["checkpoint_id"])
        if stop_at is not None and checkpoint_id < stop_at:
            break
        if len(items) >= MAX_LINEAGE_WALK:
            raise CheckpointLineageInDoubt(
                "the checkpointer lineage cannot be classified", reason="unclassifiable"
            )
        items[checkpoint_id] = item
    parents = {checkpoint_id: checkpoint_parent_id(item) for checkpoint_id, item in items.items()}

    def descends(checkpoint_id: str, ancestor: str | None) -> bool:
        cursor = parents.get(checkpoint_id)
        for _ in range(len(parents) + 1):
            if cursor == ancestor:
                return True
            if cursor is None:
                return False
            cursor = parents.get(cursor)
        return False

    root_id = source.checkpoint_id if source is not None else None
    descendants = {
        checkpoint_id
        for checkpoint_id in items
        if checkpoint_id != root_id and descends(checkpoint_id, root_id)
    }
    if not descendants:
        return _Classified(CheckpointClassification.NOT_SUBMITTED, source_key)
    stamped = {
        checkpoint_id for checkpoint_id in descendants if _stamped(items[checkpoint_id], plan)
    }
    scope = descendants
    if plan.accepted_leaf is not None:
        accepted = plan.accepted_leaf.checkpoint_id
        path_ok = accepted in stamped and _qualified(plan, items[accepted]) == plan.accepted_leaf
        cursor = parents.get(accepted) if path_ok else None
        while path_ok and cursor != root_id:
            if cursor is None or cursor not in stamped:
                path_ok = False
                break
            cursor = parents.get(cursor)
        if not path_ok:
            raise CheckpointLineageInDoubt(
                "the accepted descendant is not a stamped root-namespace descendant of the source",
                reason="accepted_descendant_invalid",
            )
        scope = {accepted} | {
            checkpoint_id for checkpoint_id in descendants if descends(checkpoint_id, accepted)
        }
    leaves = sorted(
        checkpoint_id
        for checkpoint_id in scope
        if not any(parents.get(other) == checkpoint_id for other in scope)
    )
    candidates = tuple(
        _qualified(plan, items[checkpoint_id])
        for checkpoint_id in leaves
        if checkpoint_id in stamped
    )
    if scope - stamped:
        raise CheckpointLineageInDoubt(
            "a root checkpoint descending from the source is not this unit generation's",
            reason="foreign_descendant",
            candidates=candidates,
        )
    if len(leaves) != 1:
        raise CheckpointLineageInDoubt(
            "more than one stamped leaf descends from the source",
            reason="multiple_stamped_leaves",
            candidates=candidates,
        )
    leaf_id = leaves[0]
    snapshot = await agent.aget_state(root_checkpoint_config(plan.namespace, leaf_id))
    if snapshot.interrupts or any(task.interrupts for task in snapshot.tasks):
        raise CheckpointLineageInDoubt(
            "the stamped leaf holds a pending LangGraph interrupt",
            reason="pending_interrupt",
            candidates=candidates,
        )
    return _Classified(
        (
            CheckpointClassification.INTERRUPTED
            if snapshot.next
            else CheckpointClassification.TERMINAL_UNOBSERVED
        ),
        source_key,
        leaf_id=leaf_id,
        leaf_snapshot=snapshot,
    )


def _follow_up_capture(classified: _Classified, plan: CheckpointInvocationPlan) -> _Classified:
    """How a replacement turn's result is verified (FT-F2).

    A leaf this attempt wrote itself (it interrupted its own turn) is part of the attempt's own
    lineage, which then runs unbroken from the expected source: verify it like a submission.
    A leaf an earlier attempt wrote is resumed like an interrupted unit: pinned to that leaf.
    """

    snapshot = classified.leaf_snapshot
    own = (
        snapshot is not None
        and plan.attempt_ref is not None
        and (snapshot.metadata or {}).get(STAMP_ATTEMPT_REF) == plan.attempt_ref
    )
    if own:
        return _Classified(CheckpointClassification.NOT_SUBMITTED, classified.source_key)
    return _Classified(
        CheckpointClassification.INTERRUPTED,
        classified.source_key,
        leaf_id=classified.leaf_id,
        leaf_snapshot=snapshot,
    )


async def _own_result_config(
    checkpointer: BaseCheckpointSaver[Any],
    plan: CheckpointInvocationPlan,
    classified: _Classified,
) -> RunnableConfig:
    """The unique tip this attempt wrote, descending from what it classified and pinned."""

    thread_config: RunnableConfig = {
        "configurable": {"thread_id": plan.namespace, "checkpoint_ns": ROOT_CHECKPOINT_NS}
    }
    if plan.attempt_ref is None:
        return thread_config  # adapter-level harnesses without a lease holder
    pinned = (
        classified.leaf_id
        if classified.kind == CheckpointClassification.INTERRUPTED
        else (classified.source_key.checkpoint_id if classified.source_key else None)
    )
    own: dict[str, str | None] = {}
    # 1.4.4 (P6.1): bounded to the suffix after the pinned checkpoint (ids are time-ordered).
    async for item in checkpointer.alist(thread_config, limit=MAX_LINEAGE_WALK + 1):
        checkpoint_id = str(item.config["configurable"]["checkpoint_id"])
        if pinned is not None and checkpoint_id < pinned:
            break  # the pinned checkpoint itself is scanned: an own stamp on it is a drift
        if item.metadata.get(STAMP_ATTEMPT_REF) == plan.attempt_ref:
            own[checkpoint_id] = checkpoint_parent_id(item)
    tips = [checkpoint_id for checkpoint_id in own if checkpoint_id not in own.values()]
    if len(tips) != 1:
        raise CheckpointLineageInDoubt(
            "this attempt's invocation has no unique result tip", reason="unclassifiable"
        )
    cursor = own[tips[0]]
    while cursor in own:
        cursor = own[cursor]
    if cursor != pinned:
        raise CheckpointLineageInDoubt(
            "the captured result does not descend from the checkpoint this attempt pinned",
            reason="ancestry_mismatch",
        )
    return root_checkpoint_config(plan.namespace, tips[0])


async def _terminal_result_may_exist(
    checkpointer: BaseCheckpointSaver[Any], agent: Any, plan: CheckpointInvocationPlan
) -> tuple[bool, tuple[QualifiedCheckpointKey, ...], CheckpointCapture | None]:
    """After a failure: whether a terminal stamped result may exist, with its candidates, and
    the latest durable checkpoint of a unique stamped lineage (RRM-008) if there is one."""

    try:
        classified = await _classify(checkpointer, agent, plan)
    except CheckpointLineageInDoubt as error:
        return True, error.candidates, None
    except Exception:
        return True, (), None
    if classified.kind == CheckpointClassification.NOT_SUBMITTED:
        return False, (), None
    assert classified.leaf_id is not None and classified.leaf_snapshot is not None
    snapshot = classified.leaf_snapshot
    try:
        latest: CheckpointCapture | None = await _capture_result(
            checkpointer,
            plan,
            classified.source_key,
            snapshot_config=snapshot.config,
            pending=bool(snapshot.next or snapshot.interrupts),
            classification=classified.kind,
            summary={
                "state_keys": sorted(dict(snapshot.values)),
                "message_count": len(dict(snapshot.values).get("messages", [])),
                "step": (snapshot.metadata or {}).get("step"),
            },
            allow_pending=True,
        )
    except CheckpointLineageError:
        latest = None
    if classified.kind != CheckpointClassification.TERMINAL_UNOBSERVED:
        return False, (), latest
    leaf = await checkpointer.aget_tuple(root_checkpoint_config(plan.namespace, classified.leaf_id))
    return True, ((_qualified(plan, leaf),) if leaf is not None else ()), latest


def _latest_checkpoint_reader(
    checkpointer: BaseCheckpointSaver[Any], plan: CheckpointInvocationPlan
) -> Any:
    """A reader of the namespace's latest durable root checkpoint, keys only (heartbeat)."""

    thread_config: RunnableConfig = {
        "configurable": {"thread_id": plan.namespace, "checkpoint_ns": ROOT_CHECKPOINT_NS}
    }

    async def read() -> dict[str, str | None] | None:
        latest = await checkpointer.aget_tuple(thread_config)
        if latest is None:
            return None
        return {
            "checkpointer_ref_digest": plan.checkpointer_ref_digest,
            "thread_id": plan.namespace,
            "checkpoint_ns": ROOT_CHECKPOINT_NS,
            "checkpoint_id": str(latest.config["configurable"]["checkpoint_id"]),
            "parent_checkpoint_id": checkpoint_parent_id(latest),
        }

    return read


def _within(path: str, slot: str) -> bool:
    normalized = slot.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


async def _slot_files(
    backend: BackendProtocol, slots: tuple[str, ...], state: dict[str, Any]
) -> list[tuple[str, bytes]]:
    """Every file under the exclusive writable slots, from the state or the sandbox."""

    files: list[tuple[str, bytes]] = []
    if isinstance(backend, StateBackend):
        state_files = state.get("files", {})
        for path in sorted(state_files):
            if not any(_within(path, slot) for slot in slots):
                continue
            file_data = state_files[path]
            text = file_data_to_string(file_data)
            content = (
                text.encode("utf-8")
                if file_data.get("encoding", "utf-8") == "utf-8"
                else base64.standard_b64decode(text)
            )
            files.append((path, content))
    elif isinstance(backend, SandboxBackendProtocol):
        paths: list[str] = []
        for slot in slots:
            paths.extend(await _list_sandbox_files(backend, slot, depth=0))
        downloaded = (
            await backend.adownload_files(sorted(paths))
            if hasattr(backend, "adownload_files")
            else backend.download_files(sorted(paths))
        )
        for item in downloaded:
            if item.error is None and item.content is not None:
                files.append((item.path, item.content))
    # OVE-204 slice 5: past the candidate bound the capture degrades (the first files by
    # path within both caps become candidates) instead of failing the attempt; the Workspace
    # Closure still lists every file with its digest.
    kept: list[tuple[str, bytes]] = []
    total = 0
    for path, content in files:
        if (
            len(kept) >= MAX_CAPTURED_OUTPUT_FILES
            or total + len(content) > MAX_CAPTURED_OUTPUT_BYTES
        ):
            continue
        kept.append((path, content))
        total += len(content)
    if len(kept) < len(files):
        logger.warning(
            "writable-slot outputs exceed the candidate bound (%d files, %d bytes): "
            "%d of %d captured",
            MAX_CAPTURED_OUTPUT_FILES,
            MAX_CAPTURED_OUTPUT_BYTES,
            len(kept),
            len(files),
        )
    return kept


async def _list_sandbox_files(
    backend: SandboxBackendProtocol, path: str, *, depth: int
) -> list[str]:
    if depth > MAX_CAPTURE_LISTING_DEPTH:
        return []
    listing = await backend.als(path) if hasattr(backend, "als") else backend.ls(path)
    if listing.error is not None or not listing.entries:
        return []
    found: list[str] = []
    for entry in listing.entries:
        entry_path = str(entry["path"])
        if entry.get("is_dir"):
            found.extend(await _list_sandbox_files(backend, entry_path, depth=depth + 1))
        else:
            found.append(entry_path)
    return found


async def _capture_result(
    checkpointer: BaseCheckpointSaver[Any],
    plan: CheckpointInvocationPlan,
    source_key: QualifiedCheckpointKey | None,
    *,
    snapshot_config: RunnableConfig,
    pending: bool,
    summary: dict[str, object],
    classification: CheckpointClassification = CheckpointClassification.NOT_SUBMITTED,
    allow_pending: bool = False,
) -> CheckpointCapture:
    """Capture the result config and verify a fully stamped root lineage to the source.

    `allow_pending` (RRM-008) captures the latest durable checkpoint of an interrupted unit
    as the result checkpoint of a `cancelled` or `failed` settlement: partial evidence is
    preserved and the namespace head advances, but nothing is resumed or promoted.
    """

    if pending and not allow_pending:
        raise CheckpointLineageInDoubt(
            "the invocation ended with pending tasks or interrupts; it is not terminal"
        )
    configurable = snapshot_config.get("configurable", {})
    result_id = configurable.get("checkpoint_id")
    if configurable.get("checkpoint_ns", ROOT_CHECKPOINT_NS) != ROOT_CHECKPOINT_NS or not result_id:
        raise CheckpointLineageInDoubt("no root result checkpoint was captured")
    stamps = plan.metadata_stamps()
    stop_at = source_key.checkpoint_id if source_key is not None else None
    cursor: str | None = str(result_id)
    result_parent: str | None = None
    stamped = 0
    while cursor != stop_at:
        if cursor is None or stamped >= MAX_LINEAGE_WALK:
            raise CheckpointLineageInDoubt("result checkpoint does not descend from the source")
        item = await checkpointer.aget_tuple(root_checkpoint_config(plan.namespace, cursor))
        if item is None:
            raise CheckpointLineageInDoubt("a checkpoint in the result lineage is missing")
        if any(item.metadata.get(key) != value for key, value in stamps.items()):
            raise CheckpointLineageInDoubt(
                "a checkpoint between source and result lacks this invocation's stamps"
            )
        if stamped == 0:
            result_parent = checkpoint_parent_id(item)
        stamped += 1
        cursor = checkpoint_parent_id(item)
    if result_parent is None:
        raise CheckpointLineageInDoubt("the result checkpoint has no parent")
    result_key = QualifiedCheckpointKey(
        checkpointer_ref_digest=plan.checkpointer_ref_digest,
        thread_id=plan.namespace,
        checkpoint_ns=ROOT_CHECKPOINT_NS,
        checkpoint_id=str(result_id),
        parent_checkpoint_id=result_parent,
    )
    return CheckpointCapture(
        namespace=plan.namespace,
        invocation_id=plan.invocation_id,
        source_key=source_key,
        result_key=result_key,
        ancestry_verified=True,
        stamped_checkpoint_count=stamped,
        classification=classification,
        redacted_summary_digest=sha256_digest(
            {
                "namespace": plan.namespace,
                "result_checkpoint_id": result_key.checkpoint_id,
                "parent_checkpoint_id": result_parent,
                "stamped_checkpoint_count": stamped,
                **summary,
            }
        ),
    )


STRUCTURED_RESPONSE_CHANNEL = "structured_response"


async def _structured_response_written(
    checkpointer: BaseCheckpointSaver[Any],
    plan: CheckpointInvocationPlan,
    source_key: QualifiedCheckpointKey | None,
    result_config: RunnableConfig,
) -> bool:
    """Whether the unit's lineage after its source wrote `structured_response` (Tracing
    Stage 3, R3-F1).

    `create_agent` writes the channel only when a turn produced a structured answer and never
    clears it, so it persists in the thread checkpoint and every later turn of the session
    (units share the thread) would read an earlier turn's answer. The channel's version at
    the result checkpoint differs from its version at the source exactly when this lineage
    wrote it; the values themselves are never compared.
    """

    result = await checkpointer.aget_tuple(result_config)
    if result is None:
        return False
    written = (result.checkpoint.get("channel_versions") or {}).get(STRUCTURED_RESPONSE_CHANNEL)
    if written is None:
        return False
    if source_key is None:
        return True
    source = await checkpointer.aget_tuple(
        root_checkpoint_config(plan.namespace, source_key.checkpoint_id)
    )
    before = (
        (source.checkpoint.get("channel_versions") or {}).get(STRUCTURED_RESPONSE_CHANNEL)
        if source is not None
        else None
    )
    return written != before


def _provider_run_id(messages: Sequence[BaseMessage]) -> str | None:
    """The id of the last model answer; a turn stop Mission Control answered instead of the
    model is not a provider run (Tracing Stage 3, R3-F9)."""

    final = next(
        (
            item
            for item in reversed(messages)
            if isinstance(item, AIMessage) and not is_turn_stop(item)
        ),
        None,
    )
    return str(final.id) if final is not None and final.id else None


def _structured_output(value: object, output_text: str) -> object:
    if isinstance(value, dict):
        return value
    # Tracing Stage 2 (F-S2-1): `create_agent`'s structured-output strategies leave the
    # validated schema instance (a pydantic model for a pydantic `response_format`) in
    # `structured_response`; the final message then carries a tool call, not JSON text.
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else None
    try:
        decoded = json.loads(output_text)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _prompts(invocation: RuntimeInvocation) -> tuple[str, str]:
    system_parts: list[str] = []
    user_parts: list[str] = []
    for segment in invocation.prompt_segments:
        if segment.trust_class.value in {"system_authority", "authored_instruction"}:
            system_parts.append(segment.content)
        else:
            user_parts.append(segment.content)
    if not user_parts:
        raise DeepAgentMaterializationError("Deep Agent invocation has no admitted user objective")
    system_parts.append(
        "BellLabs authority, budgets, lifecycle, and artifact admission remain host-owned. "
        "Use only the exact attached tools, Skills, MCP surface, and writable workspace slots."
    )
    return "\n\n".join(system_parts), "\n\n".join(user_parts)


def _permissions(binding: DeepAgentExecutionBinding) -> list[FilesystemPermission]:
    permissions: list[FilesystemPermission] = []
    if binding.skills:
        permissions.append(
            FilesystemPermission(
                operations=["read"],
                paths=sorted({str(item.mount_root) for item in binding.skills}),
                mode="allow",
            )
        )
    if binding.workspace.read_mounts:
        permissions.append(
            FilesystemPermission(
                operations=["read"],
                paths=[mount.logical_path for mount in binding.workspace.read_mounts],
                mode="allow",
            )
        )
    permissions.append(
        FilesystemPermission(
            operations=["read", "write"],
            paths=list(binding.workspace.exclusive_write_paths),
            mode="allow",
        )
    )
    permissions.append(
        FilesystemPermission(
            operations=["read", "write"],
            paths=["/"],
            mode="deny",
        )
    )
    return permissions


def _message_text(message: BaseMessage | None) -> str:
    if message is None:
        return ""
    if isinstance(message.content, str):
        return message.content
    parts = []
    for block in message.content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def _charged_dimensions(invocation: RuntimeInvocation) -> frozenset[str]:
    """W1 D38: the dimensions a turn's spend is reported on: those its reservation bounds and
    the run's in-turn dimensions (a Goal Loop iteration reserves only `goal.iterations`)."""

    return frozenset(IN_TURN_RUN_DIMENSIONS) & (
        frozenset(invocation.binding.budget_limits) | frozenset(invocation.run_budget_dimensions)
    )


def _turn_limits(invocation: RuntimeInvocation) -> dict[str, int]:
    """W1 D41: per in-turn dimension, the tighter of the unit's reservation and what the
    authored run budget leaves; a dimension neither bounds is unlimited (absent)."""

    limits: dict[str, int] = {}
    for dimension in IN_TURN_RUN_DIMENSIONS:
        bounds = [
            int(source[dimension])
            for source in (invocation.binding.budget_limits, invocation.run_budget_remaining)
            if dimension in source
        ]
        if bounds:
            limits[dimension] = min(bounds)
    return limits


def _budget_stop_of(messages: list[BaseMessage]) -> dict[str, dict[str, int]]:
    """The exhausted dimensions of the budget stop that ended the turn, or `{}` (W1 D41)."""

    for message in reversed(messages):
        if isinstance(message, AIMessage) and BUDGET_STOP in (message.additional_kwargs or {}):
            payload = message.additional_kwargs[BUDGET_STOP]
            if not isinstance(payload, Mapping):
                return {}
            return {
                str(dimension): {
                    "limit": int(value.get("limit", 0)),
                    "spent": int(value.get("spent", 0)),
                }
                for dimension, value in payload.items()
                if isinstance(value, Mapping)
            }
    return {}


def _usage(
    invocation: RuntimeInvocation,
    messages: list[BaseMessage],
    subordinate_calls: tuple[dict[str, object], ...] = (),
    *,
    subordinate_tool_calls: int = 0,
) -> RuntimeUsage:
    turns = 0
    total_tokens = 0
    tool_calls = subordinate_tool_calls
    for message in messages:
        if isinstance(message, ToolMessage):
            # W1 D41: a tool call that ran; a refused one (budget, hook DENY) never did.
            tool_calls += 0 if refused_tool_call(message) else 1
            continue
        if not isinstance(message, AIMessage) or is_turn_stop(message):
            continue
        turns += 1
        metadata: Mapping[str, Any] = message.usage_metadata or {}
        total_tokens += int(metadata.get("total_tokens", 0))
    for call in subordinate_calls:
        turns += 1
        total_tokens += int(cast(int, call["total_tokens"]))
    spent = {"model.turns": turns, "tokens.total": total_tokens, TOOL_CALLS: tool_calls}
    charged = _charged_dimensions(invocation)
    return RuntimeUsage(
        amounts={dimension: amount for dimension, amount in spent.items() if dimension in charged}
    )


def _observed_usage(
    invocation: RuntimeInvocation,
    calls: _ModelCallObserver,
    *,
    spent: Mapping[str, int] | None = None,
) -> RuntimeUsage:
    """The usage of every model call the observer saw complete (F-S2-11), in the charged
    dimensions only (W1 D38), as `_usage` reports a completed turn."""

    spent = calls.spent() if spent is None else spent
    charged = _charged_dimensions(invocation)
    return RuntimeUsage(
        amounts={dimension: amount for dimension, amount in spent.items() if dimension in charged}
    )


def _inspect_state(
    binding: DeepAgentExecutionBinding,
    state: dict[str, Any],
    messages: list[BaseMessage],
    resolved_attachments: tuple[dict[str, str], ...],
    disclosed_skills: tuple[dict[str, str], ...],
    framework_permissions_enforced: bool,
) -> dict[str, object]:
    calls: dict[str, dict[str, object]] = {}
    called_tools: list[str] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                calls[str(tool_call.get("id", ""))] = cast(dict[str, object], tool_call)
                called_tools.append(str(tool_call.get("name", "")))
    skill_messages = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        resolved_call = calls.get(str(message.tool_call_id), {})
        arguments = resolved_call.get("args", {})
        path = str(arguments.get("file_path", "")) if isinstance(arguments, dict) else ""
        if str(resolved_call.get("name", "")) == "read_file" and path.endswith("/SKILL.md"):
            content = _message_text(message)
            skill_messages.append(
                {
                    "path": path,
                    "content": content,
                    "content_digest": sha256_digest(content),
                    "message_id": str(message.id or ""),
                }
            )
    return {
        "kind": "deep_agent.materialization_inspection.v1",
        "binding_id": binding.binding_id,
        "binding_digest": binding.binding_digest,
        "state_schema_digest": binding.cognitive_state_schema.schema_digest,
        "context_schema_digest": binding.cognitive_context_schema.schema_digest,
        "state_keys": sorted(state),
        "artifact_index": state.get("artifact_index", {}),
        "context_manifest": state.get("context_manifest", {}),
        "child_result_index": state.get("child_result_index", []),
        # Deep Agents 0.7.5 marks skills_metadata as PrivateStateAttr. These
        # records are therefore captured at the actual chat-model boundary,
        # while the public checkpoint snapshot above remains unmodified.
        "skills_metadata": list(disclosed_skills),
        "skills_metadata_state_visibility": "private_middleware_channel",
        "skill_instruction_messages": skill_messages,
        "called_tools": called_tools,
        "mcp_tools_called": sorted(
            set(called_tools)
            & {tool.tool_name for server in binding.mcp_servers for tool in server.tools}
        ),
        "sandbox_execute_called": "execute" in called_tools,
        "framework_permissions_enforced": framework_permissions_enforced,
        "authority_enforcement": (
            "framework_filesystem_permissions"
            if framework_permissions_enforced
            else "immutable_host_binding_executable_sandbox"
        ),
        "message_count": len(messages),
        "resolved_attachments": list(resolved_attachments),
    }


def _message_usage(messages: list[BaseMessage]) -> tuple[dict[str, object], ...]:
    # Tracing Stage 3 (R3-F9): a turn stop is not a model call.
    return tuple(
        {
            "message_id": str(message.id or ""),
            "scope": "operation",
            **_token_counts(message.usage_metadata or {}),
        }
        for message in messages
        if isinstance(message, AIMessage) and not is_turn_stop(message)
    )


def _token_counts(metadata: Mapping[str, Any]) -> dict[str, int]:
    return {
        "input_tokens": int(metadata.get("input_tokens", 0)),
        "output_tokens": int(metadata.get("output_tokens", 0)),
        "total_tokens": int(metadata.get("total_tokens", 0)),
    }


class _ModelCallObserver(BaseCallbackHandler):
    """Every chat-model completion of the invocation, parent and in-process children alike.

    Recorded at the model boundary with the provider-reported token counts and the message
    identity, never the content. `run_inline` keeps the handler on the event loop thread.
    """

    run_inline = True

    def __init__(self) -> None:
        super().__init__()
        self._calls: dict[str, dict[str, object]] = {}
        # W1 D41: every tool call that ran or was admitted (parent and in-process children).
        self.tool_calls: set[str] = set()

    def on_tool_start(self, serialized: Any, input_str: str, *, run_id: Any, **kwargs: Any) -> None:
        del serialized, input_str
        self.tool_calls.add(str(kwargs.get("tool_call_id") or f"run:{run_id}"))

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        del kwargs
        for generations in getattr(response, "generations", ()):
            for generation in generations:
                message = getattr(generation, "message", None)
                if not isinstance(message, AIMessage) or not message.id:
                    continue
                self._calls[str(message.id)] = {
                    "message_id": str(message.id),
                    **_token_counts(message.usage_metadata or {}),
                }

    def spent(self) -> dict[str, int]:
        """What the invocation has spent so far, as the settlement counts it."""

        return {
            "tokens.total": sum(
                int(cast(int, call["total_tokens"])) for call in self._calls.values()
            ),
            "model.turns": len(self._calls),
            TOOL_CALLS: len(self.tool_calls),
        }

    def tool_calls_outside(self, messages: list[BaseMessage]) -> int:
        """The tool calls that ran without a result in the parent's state (a sync child's)."""

        parent = {
            str(message.tool_call_id) for message in messages if isinstance(message, ToolMessage)
        }
        return len(self.tool_calls - parent)

    def calls_outside(self, messages: list[BaseMessage]) -> tuple[dict[str, object], ...]:
        """The observed calls whose message never entered the parent's state."""

        parent = {str(message.id) for message in messages if message.id}
        return tuple(
            self._calls[identity] for identity in sorted(self._calls) if identity not in parent
        )


class _TurnSpend:
    """What the budget stop reads: the invocation's observed calls plus what the resumed
    lineage already spent (Tracing Stage 3, R3-F4).

    The settlement charges every own message after the source (`own_messages`), which for a
    resume or a follow-up includes the interrupted part before the leaf; the observer sees
    only this invocation's calls. `resume_from` adds the leaf's messages after the source,
    counted by the same `_usage` rule, so the stop and the settlement agree on the cap.
    """

    def __init__(self, calls: _ModelCallObserver) -> None:
        self._calls = calls
        self._resumed: dict[str, int] = {}

    def resume_from(
        self,
        invocation: RuntimeInvocation,
        leaf_messages: list[BaseMessage],
        prior_messages: list[BaseMessage],
        *,
        usage_remainder: Mapping[str, int] | None = None,
    ) -> None:
        self._resumed = dict(_usage(invocation, leaf_messages[len(prior_messages) :]).amounts)
        for dimension, amount in (usage_remainder or {}).items():
            self._resumed[dimension] = self._resumed.get(dimension, 0) + amount

    def __call__(self) -> dict[str, int]:
        spent = self._calls.spent()
        return {
            dimension: spent.get(dimension, 0) + self._resumed.get(dimension, 0)
            for dimension in sorted({*spent, *self._resumed})
        }

    def admit(self, tool_call_id: str, limit: int) -> bool:
        """W1 D41: admit one tool call when the calls already spent (resumed lineage, every
        call that ran or was admitted) leave room under `limit`; it then counts as spent
        before it runs, so parallel calls cannot overrun the cap together."""

        if tool_call_id in self._calls.tool_calls:
            return True
        if len(self._calls.tool_calls) + self._resumed.get(TOOL_CALLS, 0) >= limit:
            return False
        self._calls.tool_calls.add(tool_call_id)
        return True


class _ModelRequestObserver(BaseCallbackHandler):
    """The exact input of every chat-model call, parent and in-process children alike (P3.4).

    A callback, not a middleware: a middleware passed through `create_deep_agent` sits before
    the prompt-caching, memory and tool-exclusion tail, so it never sees the final
    `model_settings`, memory text or tool exclusion; the chat-model boundary sees the literal
    provider input after every middleware (TRACING-PROPOSAL A.2 last row, A.3 R1). LangGraph
    stamps `langgraph_step`, `langgraph_node` and `langgraph_checkpoint_ns` on the callback
    metadata of every task (installed `langgraph/pregel/_algo.py:655-659`), and the chat model
    passes its bound `invocation_params` (identifying params, `stop`, and the bound `tools`,
    `tool_choice`, ... from `bind_tools`; `langchain_core/language_models/chat_models.py:868,
    886-893, 1465-1471`) plus the `ls_provider` / `ls_model_name` tracing metadata. The
    callback runs inline on the event loop before the model is called and queues the capture
    on the recorder, which writes the `model_request` frame before the next stream part, so
    its arrival ordinal precedes the response frames of the call.
    """

    run_inline = True

    def __init__(self, recorder: DeepAgentFrameRecorder, *, follow_up: bool) -> None:
        super().__init__()
        self._recorder = recorder
        self._follow_up = follow_up
        # Calls within one (namespace, step): one per model call, retries included.
        self._calls: dict[tuple[str, int | None], int] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, run_id, parent_run_id, tags
        meta: Mapping[str, Any] = metadata or {}
        checkpoint_ns = str(meta.get("langgraph_checkpoint_ns") or "")
        # The task's own `node:task_id` segment is dropped, as the `messages` stream does.
        ns = tuple(checkpoint_ns.split(NS_SEP))[:-1] if checkpoint_ns else ()
        raw_step = meta.get("langgraph_step")
        step = raw_step if isinstance(raw_step, int) and not isinstance(raw_step, bool) else None
        node = meta.get("langgraph_node")
        key = (NS_SEP.join(ns), step)
        index = self._calls.get(key, 0) + 1
        self._calls[key] = index
        params = kwargs.get("invocation_params")
        self._recorder.capture_model_request(
            list(messages[0]) if messages else [],
            ns=ns,
            step=step,
            node=str(node) if node is not None else None,
            checkpoint_ns=checkpoint_ns,
            invocation_params=params if isinstance(params, Mapping) else {},
            metadata=meta,
            call_index=index,
            follow_up=self._follow_up,
        )


class _TaskNamespaceObserver(BaseCallbackHandler):
    """Binds each `task` tool call to the namespace its sync child runs in (Tracing Stage 3,
    R3-F5).

    The tools node sends one task per tool call, so parallel `task` calls run concurrently,
    each under its own `tools:<task_id>` checkpoint namespace, which LangGraph stamps on the
    tool run's callback metadata (`langgraph_checkpoint_ns`) beside the `tool_call_id` the
    tool passes to `on_tool_start`. The child graph streams under exactly that namespace.
    `run_inline` keeps the binding on the event loop before the child starts.
    """

    run_inline = True

    def __init__(self, recorder: DeepAgentFrameRecorder) -> None:
        super().__init__()
        self._recorder = recorder

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del input_str, run_id, parent_run_id, tags, inputs
        call_id = kwargs.get("tool_call_id")
        checkpoint_ns = (metadata or {}).get("langgraph_checkpoint_ns")
        if (serialized or {}).get("name") != TASK_TOOL or not call_id or not checkpoint_ns:
            return
        self._recorder.bind_task_namespace(str(call_id), str(checkpoint_ns))


class _SkillDisclosureObserver(BaseCallbackHandler):
    """Attest exact Skill metadata that reached the model without retaining prompts."""

    def __init__(self, binding: DeepAgentExecutionBinding) -> None:
        super().__init__()
        self._skills = tuple(binding.skills)
        self._disclosed: dict[str, dict[str, str]] = {}

    @property
    def disclosed_skills(self) -> tuple[dict[str, str], ...]:
        return tuple(self._disclosed[name] for name in sorted(self._disclosed))

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        del serialized, kwargs
        observed = "\n".join(_message_text(message) for batch in messages for message in batch)
        for skill in self._skills:
            path = f"{str(skill.mount_root).rstrip('/')}/SKILL.md"
            if skill.skill_name in observed and path in observed:
                self._disclosed[skill.skill_name] = {
                    "name": skill.skill_name,
                    "path": path,
                    "bundle_digest": skill.bundle_digest,
                    "skill_md_digest": skill.skill_md_digest,
                }


def _append_usage(
    existing: list[dict[str, Any]] | None, update: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = list(existing or [])
    seen = {str(item.get("message_id")) for item in merged}
    merged.extend(item for item in update if str(item.get("message_id")) not in seen)
    return merged


class _ServedGraphState(TypedDict):
    belllabs_served_graph: NotRequired[dict[str, Any]]
    belllabs_provider_usage: Annotated[NotRequired[list[dict[str, Any]]], _append_usage]


class ServedGraphIdentityMiddleware(AgentMiddleware[Any, Any, Any]):
    """Stamp the hosted graph's exact identity and its model usage into every thread it serves.

    REQ-CP-DA-019: the parent reads `belllabs_served_graph` from the provider's thread state
    to verify the served identity on every reconnect and to qualify the result checkpoint.
    REQ-CP-DA-011: `belllabs_provider_usage` records each model call's provider-reported
    token usage (keyed by message id) inside the server process, where it is present; the
    Agent Server's serialized message payloads omit `usage_metadata`, so the parent attributes
    usage from this channel and treats its absence as pending, never as zero.
    """

    state_schema = _ServedGraphState

    def __init__(self, served: AsyncServedGraphIdentity) -> None:
        super().__init__()
        self._stamp = served.model_dump(mode="json")

    def before_agent(self, state: Any, runtime: Runtime[Any]) -> dict[str, Any] | None:
        del state, runtime
        return {"belllabs_served_graph": dict(self._stamp)}

    async def abefore_agent(self, state: Any, runtime: Runtime[Any]) -> dict[str, Any] | None:
        del state, runtime
        return {"belllabs_served_graph": dict(self._stamp)}

    def after_model(self, state: Any, runtime: Runtime[Any]) -> dict[str, Any] | None:
        del runtime
        return _usage_stamp(state)

    async def aafter_model(self, state: Any, runtime: Runtime[Any]) -> dict[str, Any] | None:
        del runtime
        return _usage_stamp(state)


def _usage_stamp(state: Any) -> dict[str, Any] | None:
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return None
    last = messages[-1]
    if not isinstance(last, AIMessage) or not last.usage_metadata:
        return None
    usage: Mapping[str, Any] = last.usage_metadata
    return {
        "belllabs_provider_usage": [
            {
                "message_id": str(last.id or ""),
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            }
        ]
    }
