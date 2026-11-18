"""Builders, constants and fakes that other test files import.

Moved from tests/integration/deep_agents/test_wi02_transfer_plan_lane.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from mission_control.adapters.knowledge.memory import InMemoryTransferPlanStore
from mission_control.application.context.materialization import (
    LiteralResolver,
    TransferMaterializer,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.transfer import (
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
from tests.fixtures.lane_bindings import lane_fields
from tests.support.deep_agents import exact_fixture, unit_bound
from tests.support.knowledge.stores import InMemoryStaging
from tests.support.operations import operation_request

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
