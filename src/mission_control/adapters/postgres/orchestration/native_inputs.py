"""Read frozen templates through run-scoped, admitted family binding references."""

import json
from collections.abc import Awaitable, Callable

import asyncpg

from mission_control.adapters.postgres.documents import PostgresDocumentStore
from mission_control.contracts.run_evidence import NativeTemplateInput
from mission_control.domain.execution.contracts import OperationExecutionRequest


class PostgresNativeInputReader:
    def __init__(
        self,
        pool: asyncpg.Pool,
        binding: Callable[[str, str, str], Awaitable[tuple[str, str] | None]],
    ) -> None:
        self._documents = PostgresDocumentStore(pool)
        self._binding = binding

    async def read(
        self, request_scope: str, run_id: str, configuration_digest: str
    ) -> tuple[NativeTemplateInput, ...]:
        # The durable root input binds arbitrary native/fork/manifest reference names
        # to this run. Template skeletons themselves may contain placeholders.
        admitted = await self._binding(request_scope, run_id, configuration_digest)
        if admitted is None:
            return ()
        inputs = []
        for family, reference in (admitted,):
            if family not in {"StageGraph", "GoalDirected"}:
                raise ValueError("unsupported native template family")
            contract = "stagegraph.template/1" if family == "StageGraph" else "goal.template/1"
            for document in await self._documents.list(
                request_scope=request_scope, contract=contract
            ):
                binding, key = json.loads(document.identity)
                if binding != reference:
                    continue
                template = OperationExecutionRequest.model_validate(document.payload)
                if template.request_scope != request_scope:
                    raise ValueError("native template differs from admitted run scope")
                inputs.append(
                    NativeTemplateInput(
                        binding_ref=binding,
                        family="StageGraph" if family == "StageGraph" else "GoalDirected",
                        template_key=key,
                        document_digest=document.digest,
                        template=template,
                    )
                )
        return tuple(
            sorted(inputs, key=lambda item: (item.family, item.binding_ref, item.template_key))
        )
