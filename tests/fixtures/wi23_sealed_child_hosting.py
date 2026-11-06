"""Unpaid sealed-child hosting for the local Agent Server proof (OVE-184, T0).

``MISSION_CONTROL_SEALED_CHILD_FACTORY=tests.fixtures.wi23_sealed_child_hosting:factory``
makes the local ``langgraph dev`` serve the production :class:`SealedChildGraphFactory` (scope
from the verified claim, assistant audience, custody read under the scope from real PostgreSQL
at ``WI23_TEST_CUSTODY_DSN`` or in the file ``WI23_TEST_CUSTODY_DSN_FILE`` names, digest
checks, the worker's adapter and materializer, the stamp)
with one substitution: the sealed binding's model is a deterministic local model, so nothing is
paid and no provider credential is needed. Everything else is the production path.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import asyncpg
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from mission_control.adapters.agent_server.async_subagents.sealed import (
    SealedChildGraphFactory,
    sealed_child_registry,
)
from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
from mission_control.adapters.deep_agents.materializer import (
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
)
from mission_control.adapters.postgres.async_subagents.sealed_child_custody import (
    PostgresSealedChildCustody,
)
from mission_control.domain.execution.async_subagent_reconciliation import (
    AsyncServedGraphIdentity,
)
from mission_control.domain.execution.contracts import (
    AsyncSubagentContract,
    SealedAsyncChildBinding,
)


class SealedLocalChild(BaseChatModel):
    """Answers with a marker when its system prompt carries the sealed prompt, and the objective."""

    expected_prompt: str = ""

    @property
    def _llm_type(self) -> str:
        return "wi23-sealed-local-child"

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> BaseChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        del stop, run_manager, kwargs
        system = " ".join(
            str(item.content) for item in messages if getattr(item, "type", "") == "system"
        )
        human = [str(item.content) for item in messages if isinstance(item, HumanMessage)]
        sealed = bool(self.expected_prompt) and self.expected_prompt in system
        marker = "SEALED-PROMPT-SEEN" if sealed else ""
        reply = f"{marker} PONG for: {human[-1] if human else ''}".strip()
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=[{"type": "text", "text": reply}],
                        usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    )
                )
            ]
        )


class _Custody:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def contract(
        self, request_scope: str, contract_digest: str
    ) -> AsyncSubagentContract | None:
        async with self._lock:
            if self._pool is None:
                dsn = (
                    os.environ.get("WI23_TEST_CUSTODY_DSN")
                    or (
                        await asyncio.to_thread(
                            Path(os.environ["WI23_TEST_CUSTODY_DSN_FILE"]).read_text,
                            encoding="utf-8",
                        )
                    ).strip()
                )
                self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        return await PostgresSealedChildCustody(self._pool).contract(request_scope, contract_digest)


async def _build(
    sealed: SealedAsyncChildBinding, served: AsyncServedGraphIdentity, stack: AsyncExitStack
) -> Any:
    base = ExactComponentRegistry(
        model_factories={
            sealed.binding.model.ref.digest: lambda _b, _s: SealedLocalChild(
                expected_prompt=sealed.system_prompt
            )
        }
    )
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(sealed_child_registry(sealed, base))
    )
    return await adapter.build_hosted_async_subagent_graph(
        sealed.binding,
        {},
        system_prompt=sealed.system_prompt,
        served=served,
        stack=stack,
        sealed=sealed,
    )


def factory() -> SealedChildGraphFactory:
    return SealedChildGraphFactory(_Custody(), _build)
