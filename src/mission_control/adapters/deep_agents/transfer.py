"""The Deep Agents lane realizes the receiver's sealed transfer plan (Sprint OC WI-02; ADR-0061).

Every invocation whose binding carries a ``transfer`` selection is materialized through the one
:class:`~mission_control.application.context.materialization.TransferMaterializer`, whether or
not the agent has knowledge tools: the plan is sealed (or the stored one reused), its files are
written to the *actual* backend the agent reads (sandbox upload, or the ``files`` state channel
of the text-only backend) and read back through that backend, and the prompt section and files
the agent receives are rendered from the plan alone. The measured overhead is the invocation's
own system and user prompt, bound tool schemas and Skill metadata.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from deepagents.backends.protocol import BackendProtocol
from deepagents.backends.state import StateBackend
from deepagents.backends.utils import create_file_data, file_data_to_string

from mission_control.adapters.deep_agents.hook_contributions import remember_transfer_plan
from mission_control.application.context.materialization import (
    MaterializedTransfer,
    MaterializeRequest,
    TransferMaterializer,
)
from mission_control.application.knowledge.toolset import TOOL_NAMES
from mission_control.domain.context.packet import ConservativeTokenCounter
from mission_control.domain.context.transfer import HostOverhead, ReceiverAttempt, ReceiverRef
from mission_control.domain.execution.contracts import RuntimeInvocation

# The knowledge tool that reads qualified assertion/evidence handles on demand.
RETRIEVAL_TOOLS = frozenset({"knowledge_read"}) & frozenset(TOOL_NAMES)


class DeepAgentReceiverBackend:
    """The attempt's actual backend: what it writes is what the agent's file tools read."""

    def __init__(self, backend: BackendProtocol) -> None:
        self._backend = backend
        self.state_files: dict[str, object] = {}

    @property
    def realized_backend(self) -> str:
        if isinstance(self._backend, StateBackend):
            return "deep_agents:state"
        return f"deep_agents:{type(self._backend).__name__}"

    @property
    def read_probe(self) -> str:
        """How a read back is made: the files channel the agent's file tools read (text-only
        backend), or a read through the sandbox backend."""

        return "state_files_read" if isinstance(self._backend, StateBackend) else "backend_read"

    async def write(self, files: Sequence[tuple[str, bytes]]) -> None:
        if isinstance(self._backend, StateBackend):
            for path, content in files:
                # Text-only channel: a binary member was refused at sealing on this backend.
                self.state_files[path] = create_file_data(content.decode("utf-8"))
            return
        responses = await self._backend.aupload_files(list(files))
        failed = [item.path for item in responses if item.error]
        if failed:
            raise OSError(f"sandbox refused {len(failed)} input file(s)")

    async def read(self, path: str) -> bytes | None:
        if isinstance(self._backend, StateBackend):
            data = self.state_files.get(path)
            if data is None:
                return None
            return file_data_to_string(data).encode("utf-8")  # type: ignore[arg-type]
        responses = await self._backend.adownload_files([path])
        if not responses or responses[0].error or responses[0].content is None:
            return None
        return responses[0].content


def measured_overhead(
    system_prompt: str, user_prompt: str, tools: Sequence[Any], skills: Sequence[str]
) -> HostOverhead:
    """Host/task/state prompt, tool schemas and Skill metadata of this invocation."""

    counter = ConservativeTokenCounter()
    schemas = []
    for tool in tools:
        schema: Any = getattr(tool, "args_schema", None)
        body: Any = schema
        dump = getattr(schema, "model_json_schema", None)
        if callable(dump):
            try:
                body = dump()
            except (TypeError, ValueError):
                body = None
        schemas.append(
            {
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "schema": body if isinstance(body, dict) else {},
            }
        )
    return HostOverhead(
        host_state_tokens=counter.count(system_prompt) + counter.count(user_prompt),
        tool_schema_tokens=counter.count(json.dumps(schemas, sort_keys=True, default=str)),
        skill_tokens=counter.count("\n".join(skills)),
    )


async def materialize_transfer(
    materializer: TransferMaterializer,
    invocation: RuntimeInvocation,
    *,
    backend: BackendProtocol,
    overhead: HostOverhead,
    tool_names: Sequence[str],
    reserved_paths: Sequence[str] = (),
    access: Any = None,
) -> tuple[MaterializedTransfer, DeepAgentReceiverBackend] | None:
    """Seal (or reuse) and deliver this invocation's plan; ``None`` without a selection."""

    binding = invocation.binding
    selection = binding.transfer
    if selection is None:
        return None
    dispatch = binding.lane_dispatch
    receiver_backend = DeepAgentReceiverBackend(backend)
    request = MaterializeRequest(
        receiver=ReceiverRef(
            scope=binding.request_scope, run_id=binding.run_id, operation_id=binding.operation_id
        ),
        attempt=ReceiverAttempt(
            operation_attempt=binding.operation_attempt,
            execution_generation=dispatch.execution_generation if dispatch is not None else 1,
            invocation_ref=binding.binding_id,
        ),
        selection=selection,
        configuration_ref=f"erc:{binding.effective_configuration_digest}",
        host_state_ref=_host_state_ref(invocation),
        overhead=overhead,
        retrieval_tools=tuple(sorted(RETRIEVAL_TOOLS & set(tool_names))),
        access=access,
        correlation_id=f"{binding.binding_id}:{binding.operation_attempt}",
        reserved_paths=frozenset(reserved_paths),
    )
    materialized = await materializer.materialize(request, receiver_backend)
    # WI-17: a hook's `transfer_input` read verifies against this exact plan.
    remember_transfer_plan(backend, materialized.plan)
    return materialized, receiver_backend


def _host_state_ref(invocation: RuntimeInvocation) -> str | None:
    """The Context Packet the host rendered for this invocation (its authoritative state)."""

    for segment in invocation.prompt_segments:
        if segment.source_ref.startswith("context-packet:"):
            return f"{segment.source_ref}@{segment.rendered_digest}"
    return None


__all__ = [
    "RETRIEVAL_TOOLS",
    "DeepAgentReceiverBackend",
    "materialize_transfer",
    "measured_overhead",
]
