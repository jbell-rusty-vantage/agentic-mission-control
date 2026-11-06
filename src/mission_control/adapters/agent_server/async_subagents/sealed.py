"""The generic sealed-child graph: one served graph, a child's exact binding per run (OVE-184).

The parent seals each dynamic child's configuration into its ``AsyncSubagentContract``
(``child_binding``); the governed spawn writes that contract to custody
(``mission_control.subordinate_contract``) before any provider call, ensures one assistant
per binding and request scope whose configuration names the binding and contract digests, and
posts the run against that assistant. For every run the server calls
:class:`SealedChildGraphFactory` with the run's configuration, which:

1. takes the request scope from the authenticated caller (the verified ``bl1`` scope claim;
   never from the payload) and requires exactly one;
2. requires the run's assistant to be ``sealed_child_assistant_id(scope, binding digest)``,
   so a run cannot name another scope's or another binding's assistant (audience);
3. fetches the contract from custody **under that scope** (forced row-level security), and
   requires its sealed binding digest and the contract digest to be exactly the configured
   ones (the contract and binding validators recompute both digests on load);
4. compiles the sealed binding with the shared materializer and adapter (the worker's own
   path, ``DeepAgentRuntimeAdapter.build_hosted_async_subagent_graph``), stamping the binding
   digest into thread state so the parent verifies every run exactly, and caches the compiled
   graph per (scope, digest).

Every failure refuses the run before any model call; nothing falls back to another graph.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import logging
import os
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import replace
from functools import lru_cache
from typing import Any, Final, Protocol

from langchain_core.runnables import RunnableConfig

from mission_control.adapters.deep_agents.child_binding import SEALED_CHILD_SANDBOX
from mission_control.adapters.deep_agents.materializer import (
    ExactComponentRegistry,
    ExactModelFactory,
    StateSandboxFactory,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.async_subagent_reconciliation import (
    SEALED_BINDING_DIGEST_KEY,
    SEALED_CONTRACT_DIGEST_KEY,
    AsyncServedGraphIdentity,
    sealed_child_assistant_id,
)
from mission_control.domain.execution.contracts import (
    ASYNC_CHILD_BINDING_SCHEMA,
    AsyncSubagentContract,
    SealedAsyncChildBinding,
)

logger = logging.getLogger(__name__)

SEALED_CHILD_GRAPH: Final = "belllabs_async_child"
# The compiled sealed graphs one server process keeps (review S1), and how long an evicted
# graph's lifecycles stay open for a run that already holds it: past the longest run any
# contract allows (`AsyncSubagentContract.timeout_seconds` <= 604 800 s) plus an hour, so no
# live run loses its MCP sessions. Lifecycles awaiting that close are bounded by the evictions
# in that window; shutdown closes them all (`aclose`).
DEFAULT_MAX_COMPILED: Final = 128
DEFAULT_EVICTION_GRACE_SECONDS: Final = 604_800.0 + 3_600.0
SEALED_CHILD_GRAPH_REVISION: Final = "sealed-child@1"
_SCOPE_PERMISSION: Final = "request_scope:"
_PROVIDER_CREDENTIALS: Final[Mapping[str, str]] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class SealedChildRefused(PermissionError):
    """The run's sealed child binding cannot be served (audience, custody or digest)."""


def sealed_child_served_identity() -> AsyncServedGraphIdentity:
    """What ``/belllabs/async-subagents/served-graphs`` reports for the sealed-child graph.

    Its digest names the host template (graph, revision, binding schema, materializer); the
    per-run digest a parent verifies is the one the run stamps into thread state.
    """

    version = importlib.metadata.version("deepagents")
    return AsyncServedGraphIdentity(
        graph_id=SEALED_CHILD_GRAPH,
        graph_revision=SEALED_CHILD_GRAPH_REVISION,
        graph_binding_digest=sha256_digest(
            {
                "graph_id": SEALED_CHILD_GRAPH,
                "graph_revision": SEALED_CHILD_GRAPH_REVISION,
                "binding_schema": ASYNC_CHILD_BINDING_SCHEMA,
                "materializer": "ExactDeepAgentMaterializer",
                "deepagents": version,
            }
        ),
        deepagents_version=version,
        binding_mode="sealed_child",
    )


class SealedChildCustody(Protocol):
    """Reads one sealed contract from Mission Control custody under a verified scope."""

    async def contract(
        self, request_scope: str, contract_digest: str
    ) -> AsyncSubagentContract | None: ...


GraphBuilder = Callable[
    [SealedAsyncChildBinding, AsyncServedGraphIdentity, AsyncExitStack], Awaitable[Any]
]


def caller_scope(configurable: Mapping[str, Any]) -> str:
    """The one request scope the authenticated caller holds (from the verified claim)."""

    permissions = configurable.get("langgraph_auth_permissions")
    if permissions is None:
        user = configurable.get("langgraph_auth_user")
        permissions = getattr(user, "permissions", None)
        if permissions is None and isinstance(user, Mapping):
            permissions = user.get("permissions")
    scopes = {
        str(item).removeprefix(_SCOPE_PERMISSION)
        for item in (permissions or ())
        if str(item).startswith(_SCOPE_PERMISSION)
    }
    if len(scopes) != 1:
        raise SealedChildRefused("a sealed child run needs exactly one authenticated scope")
    return next(iter(scopes))


class SealedChildGraphFactory:
    """The server's graph factory for :data:`SEALED_CHILD_GRAPH` (see the module doc)."""

    def __init__(
        self,
        custody: SealedChildCustody,
        build: GraphBuilder,
        *,
        max_entries: int = DEFAULT_MAX_COMPILED,
        eviction_grace_seconds: float = DEFAULT_EVICTION_GRACE_SECONDS,
    ) -> None:
        if max_entries < 1 or eviction_grace_seconds < 0:
            raise ValueError("the compiled-graph cache needs a positive bound and grace")
        self._custody = custody
        self._build = build
        # Least recently used first. Each compiled graph owns the lifecycles (MCP sessions,
        # sandboxes) its materialization opened, on its own stack (review S1).
        self._compiled: OrderedDict[tuple[str, str], tuple[Any, AsyncExitStack]] = OrderedDict()
        self._max_entries = max_entries
        self._grace = eviction_grace_seconds
        self._closing: set[asyncio.Task[None]] = set()
        # Evicted stacks not closed yet (their grace has not elapsed), closed by `aclose`.
        self._evicted: set[AsyncExitStack] = set()
        self._lock = asyncio.Lock()

    async def resolve(self, config: RunnableConfig) -> SealedAsyncChildBinding:
        """The exact sealed binding this run may materialize, or a refusal."""

        configurable = dict(config.get("configurable") or {})
        scope = caller_scope(configurable)
        digest = configurable.get(SEALED_BINDING_DIGEST_KEY)
        contract_digest = configurable.get(SEALED_CONTRACT_DIGEST_KEY)
        if not isinstance(digest, str) or not isinstance(contract_digest, str):
            raise SealedChildRefused("the run's assistant names no sealed child binding")
        assistant = configurable.get("assistant_id")
        if assistant is not None and str(assistant) != sealed_child_assistant_id(scope, digest):
            raise SealedChildRefused("the run's assistant is not this scope's sealed binding")
        contract = await self._custody.contract(scope, contract_digest)
        if contract is None:
            raise SealedChildRefused("no sealed child contract is in custody for this scope")
        sealed = contract.child_binding
        if (
            sealed is None
            or contract.contract_digest != contract_digest
            or contract.graph_binding_digest != digest
            or sealed.sealed_digest != digest
            or contract.graph_id != SEALED_CHILD_GRAPH
            or contract.graph_revision != SEALED_CHILD_GRAPH_REVISION
        ):
            raise SealedChildRefused("the custody contract does not name this sealed binding")
        return sealed

    async def __call__(self, config: RunnableConfig) -> Any:
        sealed = await self.resolve(config)
        scope = caller_scope(dict(config.get("configurable") or {}))
        key = (scope, sealed.sealed_digest)
        async with self._lock:
            entry = self._compiled.get(key)
            if entry is not None:
                self._compiled.move_to_end(key)
                return entry[0]
            served = sealed_child_served_identity().model_copy(
                update={"graph_binding_digest": sealed.sealed_digest}
            )
            stack = AsyncExitStack()
            try:
                compiled = await self._build(sealed, served, stack)
            except BaseException:
                await stack.aclose()
                raise
            self._compiled[key] = (compiled, stack)
            while len(self._compiled) > self._max_entries:
                _evicted, (_graph, evicted_stack) = self._compiled.popitem(last=False)
                self._close_later(evicted_stack)
            return compiled

    @property
    def cached(self) -> tuple[tuple[str, str], ...]:
        """The (scope, digest) keys compiled now, least recently used first."""

        return tuple(self._compiled)

    def _close_later(self, stack: AsyncExitStack) -> None:
        """Close an evicted graph's lifecycles after a grace period.

        A run that already holds the evicted graph keeps its MCP sessions for the grace
        period; the next run of that binding recompiles it. The bound keeps a long-lived
        server from accumulating one open lifecycle set per binding and scope forever.
        """

        self._evicted.add(stack)

        async def close() -> None:
            await asyncio.sleep(self._grace)
            await self._close_stack(stack)

        task = asyncio.get_running_loop().create_task(close())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def aclose(self) -> None:
        """Close every compiled graph's lifecycles now (server shutdown)."""

        for task in tuple(self._closing):
            task.cancel()
        stacks = [*self._evicted, *(stack for _graph, stack in self._compiled.values())]
        self._compiled.clear()
        for stack in stacks:
            await self._close_stack(stack)

    async def _close_stack(self, stack: AsyncExitStack) -> None:
        """Close one graph's lifecycles once; never raise into the server.

        The stack was entered by the run task that compiled the graph and is closed from the
        eviction or shutdown task. A lifecycle bound to its entering task (an anyio cancel
        scope) may refuse that; the failure is logged, the resource is left to process exit.
        """

        if stack in self._evicted:
            self._evicted.discard(stack)
        try:
            await stack.aclose()
        except Exception:
            logger.warning("closing a sealed child graph's lifecycles failed", exc_info=True)


def sealed_child_registry(
    sealed: SealedAsyncChildBinding, base: ExactComponentRegistry
) -> ExactComponentRegistry:
    """The deployment's exact registry plus this child's prompt and own state backend."""

    return replace(
        base,
        prompts={**base.prompts, sealed.system_prompt_ref.digest: sealed.system_prompt},
        sandbox_factories={
            **base.sandbox_factories,
            SEALED_CHILD_SANDBOX.ref.digest: StateSandboxFactory(),
        },
    )


def sealed_child_secrets(
    sealed: SealedAsyncChildBinding, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Server-side credentials for the child's model and MCP servers (``environment:`` only).

    The model credential is the vendor's server variable; MCP credential references resolve
    from the server environment by name. Anything else refuses: a hosted child never receives
    a credential through its configuration.
    """

    environment = dict(os.environ if environ is None else environ)
    binding = sealed.binding
    variable = _PROVIDER_CREDENTIALS.get(binding.model.provider)
    if variable is None or not environment.get(variable):
        raise SealedChildRefused(
            f"the server has no credential for model provider {binding.model.provider!r}"
        )
    secrets = {f"environment:{variable}": environment[variable]}
    for server in binding.mcp_servers:
        for ref in server.credential_refs:
            if ref.provider != "environment" or not environment.get(ref.key):
                raise SealedChildRefused(
                    f"MCP credential {ref.provider}:{ref.key} is not resolvable on the server"
                )
            secrets[f"environment:{ref.key}"] = environment[ref.key]
    return secrets


def pinned_base_registry() -> ExactComponentRegistry:
    """The deployment's pinned models and Skill bundles (the worker's own pin file)."""

    from mission_control.adapters.capabilities.capability_bundles import DirectoryBundleStore
    from mission_control.adapters.capabilities.capability_pins import CapabilityPins
    from mission_control.bootstrap.settings import get_settings

    settings = get_settings()
    pins = CapabilityPins.from_settings(settings)
    store = (
        DirectoryBundleStore(settings.capability_bundle_local_root)
        if settings.capability_bundle_local_root is not None
        else None
    )
    return ExactComponentRegistry(
        model_factories={
            model.ref.digest: ExactModelFactory(
                served_vendor=model.provider, served_model_id=model.model_id
            )
            for model in pins.models
        },
        skill_bundles={skill.bundle_digest: skill.bundle(store=store) for skill in pins.skills},
    )


class _ApplicationCustody:
    """The application PostgreSQL custody, connected on the first sealed run (import-safe)."""

    def __init__(self) -> None:
        self._pool: Any = None
        self._lock = asyncio.Lock()

    async def contract(
        self, request_scope: str, contract_digest: str
    ) -> AsyncSubagentContract | None:
        from mission_control.adapters.postgres.async_subagents.sealed_child_custody import (
            PostgresSealedChildCustody,
        )

        async with self._lock:
            if self._pool is None:
                from mission_control.adapters.postgres.connections import (
                    create_application_postgres_pool,
                )
                from mission_control.bootstrap.settings import get_settings

                self._pool = await create_application_postgres_pool(get_settings())
        return await PostgresSealedChildCustody(self._pool).contract(request_scope, contract_digest)


@lru_cache(maxsize=1)
def _base_registry() -> ExactComponentRegistry:
    return pinned_base_registry()


async def build_sealed_child_graph(
    sealed: SealedAsyncChildBinding, served: AsyncServedGraphIdentity, stack: AsyncExitStack
) -> Any:
    """Compile one sealed child with the worker's own adapter and materializer."""

    from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
    from mission_control.adapters.deep_agents.materializer import ExactDeepAgentMaterializer

    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(sealed_child_registry(sealed, _base_registry()))
    )
    return await adapter.build_hosted_async_subagent_graph(
        sealed.binding,
        sealed_child_secrets(sealed),
        system_prompt=sealed.system_prompt,
        served=served,
        stack=stack,
        sealed=sealed,
    )


SEALED_CHILD_FACTORY_ENV: Final = "MISSION_CONTROL_SEALED_CHILD_FACTORY"


async def close_default_sealed_child_factory() -> None:
    """Server shutdown: close the deployment factory's lifecycles if it was ever built."""

    if default_sealed_child_factory.cache_info().currsize:
        await default_sealed_child_factory().aclose()
        default_sealed_child_factory.cache_clear()


@lru_cache(maxsize=1)
def default_sealed_child_factory() -> SealedChildGraphFactory:
    """The deployment's sealed-child factory: application custody, pinned components.

    A trusted deployment hook (``MISSION_CONTROL_SEALED_CHILD_FACTORY=module:callable``, the
    sibling of ``MISSION_CONTROL_AGENT_HOSTING_FACTORY``) may supply another factory, for
    example a deterministic model for an unpaid local proof; it is never selected by a request.
    """

    specification = os.environ.get(SEALED_CHILD_FACTORY_ENV, "")
    if specification:
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", specification):
            raise ValueError("the sealed child factory must be an installed module:callable")
        module, name = specification.split(":")
        factory = getattr(importlib.import_module(module), name)()
        if not isinstance(factory, SealedChildGraphFactory):
            raise TypeError("the sealed child factory hook must return SealedChildGraphFactory")
        return factory
    return SealedChildGraphFactory(_ApplicationCustody(), build_sealed_child_graph)


__all__ = [
    "SEALED_BINDING_DIGEST_KEY",
    "SEALED_CHILD_GRAPH",
    "SEALED_CHILD_GRAPH_REVISION",
    "SEALED_CONTRACT_DIGEST_KEY",
    "SealedChildCustody",
    "SealedChildGraphFactory",
    "SealedChildRefused",
    "build_sealed_child_graph",
    "caller_scope",
    "close_default_sealed_child_factory",
    "default_sealed_child_factory",
    "pinned_base_registry",
    "sealed_child_registry",
    "sealed_child_secrets",
    "sealed_child_served_identity",
]
