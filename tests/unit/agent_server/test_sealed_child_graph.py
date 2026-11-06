"""OVE-184: the Agent Server's generic sealed-child graph (offline, T0).

One served graph materializes each run's own sealed child binding: the scope comes from the
verified claim, the run's assistant must be that scope's assistant of that exact binding, the
contract comes from custody under the scope and both digests are re-verified, the graph is
compiled through the worker's own adapter and materializer (cached per scope and digest) and
stamps the binding digest; every mismatch refuses before any model call.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import pytest
from langgraph_sdk import Auth

from mission_control.adapters.agent_server import deployment, deployment_auth
from mission_control.adapters.agent_server.async_subagents.sealed import (
    SEALED_CHILD_GRAPH,
    SealedChildGraphFactory,
    SealedChildRefused,
    build_sealed_child_graph,
    caller_scope,
    sealed_child_registry,
    sealed_child_secrets,
    sealed_child_served_identity,
)
from mission_control.adapters.deep_agents import adapter as adapter_module
from mission_control.adapters.deep_agents.materializer import ExactComponentRegistry
from mission_control.domain.authoring.contracts import SecretRef
from mission_control.domain.execution.async_subagent_reconciliation import (
    SEALED_BINDING_DIGEST_KEY,
    SEALED_CONTRACT_DIGEST_KEY,
    AsyncServedGraphIdentity,
    sealed_child_assistant_id,
)
from mission_control.domain.execution.contracts import AsyncSubagentContract
from mission_control.domain.execution.errors import DeepAgentMaterializationError
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.unit.agent_server.test_async_subagent_server_offline import ScriptedChildModel
from tests.unit.operations.test_async_child_check_time_admission import _sealed_contract

SCOPE = "tenant-1"


def _contract() -> AsyncSubagentContract:
    base, _profile, _bundle = exact_fixture()
    return _sealed_contract(base.model)


def _config(contract: AsyncSubagentContract, *, scope: str = SCOPE, **extra: Any) -> Any:
    configurable: dict[str, Any] = {
        "langgraph_auth_permissions": (f"request_scope:{scope}", "role:operator"),
        SEALED_BINDING_DIGEST_KEY: contract.graph_binding_digest,
        SEALED_CONTRACT_DIGEST_KEY: contract.contract_digest,
        "assistant_id": sealed_child_assistant_id(scope, contract.graph_binding_digest),
    }
    configurable.update(extra)
    return {"configurable": configurable}


class Custody:
    def __init__(self, contracts: dict[tuple[str, str], AsyncSubagentContract]) -> None:
        self.contracts = contracts
        self.reads: list[tuple[str, str]] = []

    async def contract(self, request_scope: str, contract_digest: str) -> Any:
        self.reads.append((request_scope, contract_digest))
        return self.contracts.get((request_scope, contract_digest))


@pytest.mark.asyncio
async def test_a_run_resolves_exactly_its_scopes_sealed_binding_and_is_compiled_once() -> None:
    contract = _contract()
    custody = Custody({(SCOPE, contract.contract_digest): contract})
    built: list[tuple[str, AsyncServedGraphIdentity]] = []

    async def build(sealed: Any, served: AsyncServedGraphIdentity, stack: Any) -> object:
        del stack
        built.append((sealed.sealed_digest, served))
        return object()

    factory = SealedChildGraphFactory(custody, build)
    first = await factory(_config(contract))
    assert await factory(_config(contract)) is first
    ((digest, served),) = built
    assert digest == contract.graph_binding_digest
    assert served.binding_mode == "sealed_child" and served.matches(contract)


@pytest.mark.asyncio
async def test_every_audience_custody_or_digest_mismatch_refuses_before_compiling() -> None:
    contract = _contract()
    other = _contract().model_copy()
    custody = Custody({(SCOPE, contract.contract_digest): contract})

    async def build(*_args: object) -> object:
        raise AssertionError("never compiled")

    factory = SealedChildGraphFactory(custody, build)
    # Another scope's assistant, no scope, two scopes, no binding digest.
    with pytest.raises(SealedChildRefused, match="assistant"):
        await factory(_config(contract, assistant_id=sealed_child_assistant_id("tenant-2", "x")))
    with pytest.raises(SealedChildRefused, match="exactly one"):
        await factory(_config(contract, langgraph_auth_permissions=("role:operator",)))
    with pytest.raises(SealedChildRefused, match="exactly one"):
        await factory(
            _config(
                contract,
                langgraph_auth_permissions=("request_scope:tenant-1", "request_scope:tenant-2"),
            )
        )
    with pytest.raises(SealedChildRefused, match="names no sealed"):
        await factory(_config(contract, **{SEALED_BINDING_DIGEST_KEY: None}))
    # Custody is read under the caller's scope: another scope sees nothing.
    with pytest.raises(SealedChildRefused, match="custody"):
        await factory(_config(contract, scope="tenant-2"))
    # A contract in custody that names another binding than the run's assistant.
    swapped = Custody({(SCOPE, contract.contract_digest): other})
    swapped.contracts[(SCOPE, contract.contract_digest)] = contract.model_copy(
        update={"graph_binding_digest": "sha256:" + "1" * 64}
    )
    with pytest.raises(SealedChildRefused, match="does not name"):
        await SealedChildGraphFactory(swapped, build)(_config(contract))
    assert caller_scope({"langgraph_auth_permissions": ["request_scope:a"]}) == "a"


@pytest.mark.asyncio
async def test_the_sealed_child_compiles_through_the_worker_adapter_and_stamps_its_digest() -> None:
    contract = _contract()
    sealed = contract.child_binding
    assert sealed is not None
    model = ScriptedChildModel()
    base = ExactComponentRegistry(
        model_factories={sealed.binding.model.ref.digest: lambda *_: model}
    )
    registry = sealed_child_registry(sealed, base)
    assert registry.prompts[sealed.system_prompt_ref.digest] == sealed.system_prompt
    served = sealed_child_served_identity().model_copy(
        update={"graph_binding_digest": sealed.sealed_digest}
    )
    runtime = adapter_module.DeepAgentRuntimeAdapter(
        adapter_module.ExactDeepAgentMaterializer(registry)
    )
    async with AsyncExitStack() as stack:
        graph = await runtime.build_hosted_async_subagent_graph(
            sealed.binding,
            {},
            system_prompt=sealed.system_prompt,
            served=served,
            stack=stack,
            sealed=sealed,
        )
        result = await graph.ainvoke({"messages": [{"role": "user", "content": "say PONG"}]})
        with pytest.raises(DeepAgentMaterializationError, match="sealed child"):
            await runtime.build_hosted_async_subagent_graph(
                sealed.binding,
                {},
                system_prompt="another prompt",
                served=served,
                stack=stack,
                sealed=sealed,
            )
    stamp = AsyncServedGraphIdentity.model_validate(result["belllabs_served_graph"])
    assert stamp.matches(contract)
    assert result["messages"][-1].content == "PONG" and model.calls == 1
    assert build_sealed_child_graph  # the deployment's builder composes the same two steps


def test_server_side_credentials_resolve_from_the_environment_only() -> None:
    contract = _contract()
    sealed = contract.child_binding
    assert sealed is not None
    variable = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[
        sealed.binding.model.provider
    ]
    assert sealed_child_secrets(sealed, {variable: "k"}) == {f"environment:{variable}": "k"}
    with pytest.raises(SealedChildRefused, match="no credential"):
        sealed_child_secrets(sealed, {})
    server = (
        exact_fixture(include_mcp=True)[0]
        .mcp_servers[0]
        .model_copy(update={"credential_refs": (SecretRef(provider="vault", key="x"),)})
    )
    with_mcp = sealed.model_copy(
        update={"binding": sealed.binding.model_copy(update={"mcp_servers": (server,)})}
    )
    with pytest.raises(SealedChildRefused, match="not resolvable"):
        sealed_child_secrets(with_mcp, {variable: "k"})


def test_only_the_callers_own_sealed_assistant_may_be_created_or_run() -> None:
    contract = _contract()
    digest = contract.graph_binding_digest
    mine = sealed_child_assistant_id(SCOPE, digest)
    metadata = {
        SEALED_BINDING_DIGEST_KEY: digest,
        SEALED_CONTRACT_DIGEST_KEY: contract.contract_digest,
    }
    scopes = frozenset({SCOPE})
    assert SEALED_CHILD_GRAPH in deployment.allowed_graphs()
    deployment.require_assistant(mine, request_scopes=scopes, metadata=metadata)
    deployment.require_assistant(deployment.CHILD_GRAPH)  # the static graph stays served
    for assistant, caller, meta in (
        (mine, frozenset({"tenant-2"}), metadata),
        (mine, scopes, {}),
        (sealed_child_assistant_id(SCOPE, "sha256:" + "2" * 64), scopes, metadata),
    ):
        with pytest.raises(Auth.exceptions.HTTPException):
            deployment.require_assistant(assistant, request_scopes=caller, metadata=meta)
    value = {
        "graph_id": SEALED_CHILD_GRAPH,
        "assistant_id": mine,
        "config": {"configurable": dict(metadata)},
        "metadata": dict(metadata),
    }
    assert deployment_auth.sealed_assistant_create(value, scopes) == {"request_scope": SCOPE}
    assert value["metadata"]["request_scope"] == SCOPE
    for bad in (
        {**value, "graph_id": deployment.CHILD_GRAPH},
        {**value, "assistant_id": sealed_child_assistant_id("tenant-2", digest)},
        {**value, "config": {"configurable": {SEALED_BINDING_DIGEST_KEY: digest}}},
    ):
        with pytest.raises(Auth.exceptions.HTTPException):
            deployment_auth.sealed_assistant_create(dict(bad), scopes)


def test_the_served_graphs_report_the_sealed_child_host_template() -> None:
    contract = _contract()
    served = sealed_child_served_identity()
    assert (served.graph_id, served.binding_mode) == (SEALED_CHILD_GRAPH, "sealed_child")
    assert served.admits(contract) and not served.matches(contract)


@pytest.mark.asyncio
async def test_the_compiled_graph_cache_is_bounded_and_closes_evicted_lifecycles() -> None:
    """Review S1: least recently used graphs are evicted and their lifecycles closed."""

    first = _contract()
    custody = Custody(
        {(SCOPE, first.contract_digest): first, ("tenant-2", first.contract_digest): first}
    )
    closed: list[str] = []

    async def build(sealed: Any, served: AsyncServedGraphIdentity, stack: Any) -> object:
        del sealed
        label = f"graph-{len(closed)}-{served.graph_binding_digest[-4:]}"
        stack.callback(closed.append, label)
        return object()

    factory = SealedChildGraphFactory(custody, build, max_entries=1, eviction_grace_seconds=0)
    await factory(_config(first))
    await factory(_config(first, scope="tenant-2"))
    assert factory.cached == (("tenant-2", first.graph_binding_digest),)
    await asyncio.sleep(0.05)  # the grace-0 close task runs
    assert len(closed) == 1
    await factory.aclose()
    assert len(closed) == 2 and factory.cached == ()


@pytest.mark.asyncio
async def test_shutdown_closes_evicted_lifecycles_still_in_their_grace() -> None:
    """Review S-S1a: an evicted graph whose grace has not elapsed is closed by aclose()."""

    first = _contract()
    custody = Custody(
        {(SCOPE, first.contract_digest): first, ("tenant-2", first.contract_digest): first}
    )
    closed: list[str] = []

    async def build(sealed: Any, served: AsyncServedGraphIdentity, stack: Any) -> object:
        del sealed, served
        stack.callback(closed.append, f"graph-{len(closed)}")
        return object()

    factory = SealedChildGraphFactory(custody, build, max_entries=1, eviction_grace_seconds=3600)
    await factory(_config(first))
    await factory(_config(first, scope="tenant-2"))  # evicts the first; its grace is an hour
    assert closed == []
    await factory.aclose()
    assert len(closed) == 2
