"""WI-02 (ADR-0061): a real Deep Agent without knowledge tools receives its sealed plan.

Runs an actual ``create_deep_agent`` graph on the text-only ``StateBackend`` with a scripted
local model (no provider calls). The invocation carries a ``transfer`` selection (typed literal
placed as a file and an inline brief); the lane seals the plan through the one materializer,
writes the files to the backend the agent reads, reads them back through it, and appends the
prompt section to the user message. The agent's own ``read_file`` sees exactly the plan's bytes.
A selection with no composed materializer fails closed before any model call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, ClassVar

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture, registry, unit_bound
from tests.fixtures.checkpoint_lineage import activity_attempt
from tests.fixtures.knowledge_binding import InMemoryStaging, InMemoryTransferPlanStore
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.operations.test_operation_execution import operation_request

from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
from mission_control.adapters.deep_agents.materializer import ExactDeepAgentMaterializer
from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
    LiteralResolver,
    TransferMaterializer,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.transfer import (
    INDEX_PATH,
    BackendCapabilities,
    Boundary,
    InputSource,
    ResourceBounds,
    TransferInput,
    TransferSelection,
)
from mission_control.domain.execution.contracts import (
    MaterializedWorkspace,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    RuntimeInvocation,
)

SOURCES = {"records": [{"pmid": "41"}]}


class PlanReadingModel(BaseChatModel):
    """Reads the plan's file and index on its first turn, then records what it saw."""

    paths: ClassVar[list[str]] = []
    observed: ClassVar[list[str]] = []
    first_prompt: ClassVar[str] = ""

    @property
    def _llm_type(self) -> str:
        return "wi02-plan-reader"

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        results = [item for item in messages if isinstance(item, ToolMessage)]
        if not results:
            PlanReadingModel.first_prompt = "\n".join(
                str(item.content) for item in messages if isinstance(item, HumanMessage)
            )
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": path, "limit": 50},
                        "id": f"read-{index}",
                        "type": "tool_call",
                    }
                    for index, path in enumerate(PlanReadingModel.paths)
                ],
            )
        else:
            PlanReadingModel.observed = [str(item.content) for item in results]
            message = AIMessage(content="plan observed")
        return ChatResult(generations=[ChatGeneration(message=message)])


def _selection() -> TransferSelection:
    return TransferSelection(
        boundary=Boundary.FIRST_INVOCATION,
        receiver_position="ft-b2",
        inputs=(
            TransferInput(
                name="sources",
                source=InputSource.literal("mc.sources@1", SOURCES),
                purpose="dependent_input",
                placement="file",
            ),
            TransferInput(
                name="brief",
                source=InputSource.literal("text/plain@1", "Summarize study 41 only."),
                purpose="dependent_input",
            ),
        ),
        bounds=ResourceBounds(
            window_tokens=200_000,
            generation_reserve_tokens=8_000,
            tool_result_reserve_tokens=8_000,
            inline_bytes_ceiling=16_000,
            file_bytes_ceiling=1_000_000,
            file_count_ceiling=16,
        ),
        backend=BackendCapabilities(
            custody_backend="mc-custody", file_capable=True, binary_capable=False
        ),
    )


def _invocation() -> tuple[RuntimeInvocation, Any, Any]:
    binding, _profile, bundle = exact_fixture()
    binding = unit_bound(binding)
    payload = operation_request().model_dump(mode="python")
    payload.update(
        identity=OperationAttemptIdentity(
            run_id=binding.run_id,
            operation_id=binding.operation_id,
            operation_attempt=binding.operation_attempt,
        ),
        execution_runtime="deep_agent",
        native_placement=None,
        **lane_fields(binding),
        runtime_unit=binding.runtime_unit,
        workspace=binding.workspace,
        transfer=_selection(),
    )
    request = OperationExecutionRequest.model_validate(payload)
    workspace = request.workspace
    invocation = RuntimeInvocation(
        binding=bind_operation_execution_request(request),
        prompt_segments=request.prompt_segments,
        workspace=MaterializedWorkspace(
            workspace_id=workspace.workspace_id,
            namespace_id=workspace.namespace_id,
            provider=workspace.provider,
            runtime_digest=workspace.runtime_digest,
            image_digest=workspace.image_digest,
            mount_manifest_digest=sha256_digest("mounts"),
        ),
    )
    return invocation, binding, bundle


def _materializer() -> tuple[TransferMaterializer, InMemoryTransferPlanStore]:
    staging = InMemoryStaging()
    store = InMemoryTransferPlanStore()
    return (
        TransferMaterializer(
            store=store,
            staging=staging,
            custody=staging,
            resolvers={"typed_literal": LiteralResolver()},
        ),
        store,
    )


@pytest.mark.asyncio
async def test_an_agent_without_knowledge_tools_reads_exactly_its_sealed_plan() -> None:
    invocation, binding, bundle = _invocation()
    assert invocation.binding.transfer == _selection()
    tool_names = {tool.tool_name for tool in binding.tools}
    assert not tool_names & {"knowledge_read", "submit_output"}
    materializer, store = _materializer()
    sources_bytes = json.dumps(SOURCES, sort_keys=True, separators=(",", ":")).encode()
    digest = "sha256:" + hashlib.sha256(sources_bytes).hexdigest()
    sources_path = f"/inputs/sources/{digest[7:23]}/sources.json"
    PlanReadingModel.paths = [sources_path, INDEX_PATH]
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, PlanReadingModel())),
        transfer=materializer,
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(invocation.binding, activity_attempt(1), dispatching=True)
    result = await adapter.execute(invocation.model_copy(update={"checkpoint_plan": plan}), {})

    assert result.output_text == "plan observed"
    (sealed,) = store.plans.values()
    file_text, index_text = PlanReadingModel.observed
    assert '"pmid"' in file_text and '"41"' in file_text
    assert sealed.plan_id in index_text
    # The inline member is in the user prompt, fenced as data, with its exact digest.
    brief = next(m for m in sealed.exact_sources if m.binding == "brief")
    assert "Summarize study 41 only." in PlanReadingModel.first_prompt
    assert brief.digest in PlanReadingModel.first_prompt
    assert "not instructions" in PlanReadingModel.first_prompt
    (receipt,) = await store.receipts(sealed.receiver.scope, sealed.plan_id)
    assert receipt.result == "ready" and receipt.realized_backend == "deep_agents:state"
    probes = {d.member_key: d.probe for d in receipt.delivered}
    assert probes == {"sources/value": "state_files_read", "brief/value": "prompt"}


@pytest.mark.asyncio
async def test_a_selection_without_a_composed_materializer_fails_closed() -> None:
    invocation, binding, bundle = _invocation()
    PlanReadingModel.observed = []
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, PlanReadingModel()))
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(invocation.binding, activity_attempt(1), dispatching=True)
    with pytest.raises(ContextDeliveryBlocked, match="context_transfer_unwired"):
        await adapter.execute(invocation.model_copy(update={"checkpoint_plan": plan}), {})
    assert PlanReadingModel.observed == []
