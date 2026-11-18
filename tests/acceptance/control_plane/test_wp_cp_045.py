from __future__ import annotations

import pytest
from tests.support.deep_agents import (
    GRAPH_BINDING_DIGEST,
    NOW,
    SERVED,
    DeterministicProvider,
    checkpoint,
    contract,
    request,
)
from tests.support.providers.agent_protocol import FakeAgentProtocolClient, install

from mission_control.adapters.deep_agents.async_subagents import (
    DeepAgentsAsyncSubagentAdapter,
)
from mission_control.application.subordinates.service import (
    AsyncSubagentError,
    AsyncSubagentService,
    AsyncSubagentSpawnRequest,
    InMemoryAsyncSubagentAuthority,
    InMemoryAsyncSubagentDetailRepository,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    AsyncSubagentDependencyClass,
    AsyncSubagentExecution,
    AsyncSubagentLifecycle,
)
from mission_control.domain.execution.delegation import (
    AsyncDelegationBoundary,
    classify_async_delegation,
)


class OrderedDetails(InMemoryAsyncSubagentDetailRepository):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    async def create_before_submit(self, *args: object, **kwargs: object) -> AsyncSubagentExecution:
        self._events.append("postgres.contract-link-execution")
        return await super().create_before_submit(*args, **kwargs)  # type: ignore[arg-type]


class OrderedAuthority(InMemoryAsyncSubagentAuthority):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    async def reserve_and_admit(
        self, spawn: AsyncSubagentSpawnRequest, child_execution_id: str, link_id: str
    ) -> None:
        self._events.append("postgres.reservation-link-admission")
        await super().reserve_and_admit(spawn, child_execution_id, link_id)


def fixture_service(
    dependency: AsyncSubagentDependencyClass = AsyncSubagentDependencyClass.REQUIRED_BLOCKING,
) -> tuple[
    AsyncSubagentService,
    InMemoryAsyncSubagentDetailRepository,
    InMemoryAsyncSubagentAuthority,
    DeterministicProvider,
    AsyncSubagentSpawnRequest,
]:
    events: list[str] = []
    details = OrderedDetails(events)
    authority = OrderedAuthority(events)
    provider = DeterministicProvider(events)
    return (
        AsyncSubagentService(details, authority, provider, allow_new_spawns=True),
        details,
        authority,
        provider,
        request(dependency),
    )


@pytest.mark.asyncio
async def test_spawn_persists_contract_link_and_reservation_before_provider_submission() -> None:
    service, details, authority, provider, spawn = fixture_service()
    execution = await service.spawn(spawn)

    assert provider.events[:4] == [
        "postgres.contract-link-execution",
        "postgres.reservation-link-admission",
        "provider.verify",
        "provider.start",
    ]
    assert execution.lifecycle == AsyncSubagentLifecycle.RUNNING
    assert execution.provider_thread_id == "provider-thread-1"
    assert (spawn.request_scope, execution.child_execution_id) in details.executions
    assert (spawn.request_scope, execution.child_execution_id) in authority.reservations
    fence = authority.fences[(spawn.request_scope, execution.child_execution_id)]
    assert fence["fence"] == 1 and fence["holder"] is None


@pytest.mark.asyncio
async def test_feature_gate_disables_new_spawn_without_disabling_reconciliation_service() -> None:
    details = InMemoryAsyncSubagentDetailRepository()
    authority = InMemoryAsyncSubagentAuthority()
    provider = DeterministicProvider([])
    service = AsyncSubagentService(details, authority, provider)
    with pytest.raises(AsyncSubagentError, match="feature-gated"):
        await service.spawn(request())
    assert provider.starts == 0


@pytest.mark.asyncio
async def test_retry_or_callback_poll_ambiguity_creates_one_effective_child() -> None:
    service, _, authority, provider, spawn = fixture_service()
    first = await service.spawn(spawn)
    second = await service.spawn(spawn)

    assert second == first
    assert provider.starts == 1
    facts_before = len(authority.facts)
    await service.reconcile(spawn.request_scope, first.child_execution_id)
    await service.reconcile(spawn.request_scope, first.child_execution_id)
    assert len(authority.facts) == facts_before


@pytest.mark.parametrize(
    ("dependency", "initial", "admitted", "rejected"),
    [
        (AsyncSubagentDependencyClass.REQUIRED_BLOCKING, "wait", "proceed", "wait"),
        (AsyncSubagentDependencyClass.DEGRADABLE_BLOCKING, "wait", "proceed", "degrade"),
        (AsyncSubagentDependencyClass.NONBLOCKING, "proceed", "proceed", "proceed"),
        (AsyncSubagentDependencyClass.ADVISORY, "proceed", "proceed", "proceed"),
    ],
)
def test_four_frozen_dependency_classes(
    dependency: AsyncSubagentDependencyClass,
    initial: str,
    admitted: str,
    rejected: str,
) -> None:
    link = fixture_service(dependency)[1].links
    assert not link
    base = request(dependency)
    from mission_control.domain.execution.contracts import ParentAsyncSubagentLink

    value = ParentAsyncSubagentLink(
        link_id="link",
        child_execution_id="child",
        parent_run_id=base.parent_run_id,
        parent_operation_id=base.parent_operation_id,
        dependency_class=dependency,
        timeout_at=NOW,
        cancellation_propagation="required",
        late_result_policy="quarantine",
        fallback_policy="degrade",
        result_admission_policy_ref="policy",
        created_at=NOW,
        updated_at=NOW,
    )
    assert AsyncSubagentService.parent_dependency(value) == initial
    assert (
        AsyncSubagentService.parent_dependency(
            value.model_copy(update={"result_decision": "admit"})
        )
        == admitted
    )
    assert (
        AsyncSubagentService.parent_dependency(
            value.model_copy(update={"result_decision": "reject"})
        )
        == rejected
    )


@pytest.mark.asyncio
async def test_messages_are_ordered_and_provider_receipts_do_not_replace_ledger() -> None:
    service, details, authority, _, spawn = fixture_service()
    execution = await service.spawn(spawn)
    one = await service.send_message(
        spawn.request_scope,
        execution.child_execution_id,
        payload_ref="ref:message:one",
        correlation_id="correlation-1",
        created_at=NOW,
    )
    two = await service.send_message(
        spawn.request_scope,
        execution.child_execution_id,
        payload_ref="ref:message:two",
        correlation_id="correlation-1",
        created_at=NOW,
    )

    assert [one.target_sequence, two.target_sequence] == [1, 2]
    assert [item[1].target_sequence for item in authority.messages] == [1, 2]
    link = await details.get_link(spawn.request_scope, execution.child_execution_id)
    assert [item.receipt for item in link.messages] == ["provider_applied", "provider_applied"]
    child_one = await service.receive_child_message(
        spawn.request_scope,
        execution.child_execution_id,
        payload_ref="ref:child-message:one",
        correlation_id="correlation-1",
        created_at=NOW,
    )
    child_two = await service.receive_child_message(
        spawn.request_scope,
        execution.child_execution_id,
        payload_ref="ref:child-message:two",
        correlation_id="correlation-1",
        created_at=NOW,
    )
    assert [child_one.target_sequence, child_two.target_sequence] == [1, 2]
    assert child_one.context_authority == "untrusted_observation"


@pytest.mark.asyncio
async def test_completed_output_cannot_change_parent_before_explicit_admission_or_when_late() -> (
    None
):
    service, details, authority, provider, spawn = fixture_service()
    execution = await service.spawn(spawn)
    provider.next_status = "success"
    completed = await service.reconcile(spawn.request_scope, execution.child_execution_id)

    assert completed.result_manifest is not None
    assert completed.result_manifest.provider_checkpoint == checkpoint()
    assert completed.result_manifest.checkpoint_ref == checkpoint().ref
    assert completed.result_manifest.usage.attributed_amounts == {
        "model.turns": 1,
        "tokens.total": 7,
    }
    assert completed.result_output_text == "canonical child result"
    link = await details.get_link(spawn.request_scope, execution.child_execution_id)
    assert link.result_decision is None
    assert not authority.decisions
    with pytest.raises(AsyncSubagentError, match="late or superseded"):
        await service.decide_result(
            spawn.request_scope,
            execution.child_execution_id,
            "admit",
            parent_open=False,
            current_generation=1,
            decided_at=NOW,
        )
    assert any(
        kind == "result" and ref.startswith("late_rejected:")
        for _scope, _child, kind, ref in authority.facts
    )
    admitted = await service.decide_result(
        spawn.request_scope,
        execution.child_execution_id,
        "admit",
        parent_open=True,
        current_generation=1,
        decided_at=NOW,
    )
    assert admitted.admitted_manifest_digest == completed.result_manifest.manifest_digest
    settled = await service.settle(
        spawn.request_scope,
        execution.child_execution_id,
        "settlement:child:1",
        NOW,
    )
    replayed = await service.settle(
        spawn.request_scope,
        execution.child_execution_id,
        "settlement:child:1",
        NOW,
    )
    assert settled.settled and replayed == settled
    assert authority.settlements == {
        (spawn.request_scope, execution.child_execution_id): "settlement:child:1"
    }


@pytest.mark.asyncio
async def test_cancellation_is_authorized_before_provider_and_acknowledgement_recorded() -> None:
    service, details, authority, provider, spawn = fixture_service()
    execution = await service.spawn(spawn)
    cancelled = await service.cancel(
        spawn.request_scope, execution.child_execution_id, "parent cancelled", NOW
    )
    assert cancelled.lifecycle == AsyncSubagentLifecycle.CANCELLED
    assert authority.cancellations[(spawn.request_scope, execution.child_execution_id)]
    assert provider.events[-1] == "provider.cancel"
    link = await details.get_link(spawn.request_scope, execution.child_execution_id)
    assert link.cancellation_requested
    assert link.cancellation_receipt == "provider_acknowledged"
    assert (
        spawn.request_scope,
        execution.child_execution_id,
        "cancellation",
        "provider_acknowledged",
    ) in authority.facts


@pytest.mark.parametrize(
    ("boundary", "route"),
    [
        (AsyncDelegationBoundary(), "subordinate"),
        (AsyncDelegationBoundary(durable_cross_operation_wait=True), "operation"),
        (AsyncDelegationBoundary(substantial_separate_budget=True), "operation"),
        (AsyncDelegationBoundary(recognized_workflow_type=True), "linked_run"),
        (AsyncDelegationBoundary(independent_authority=True), "linked_run"),
    ],
)
def test_governance_classifier_never_launches_hidden_work(
    boundary: AsyncDelegationBoundary, route: str
) -> None:
    assert classify_async_delegation(boundary).route == route


def test_actual_deep_agents_075_middleware_surface_is_wrapped_exactly() -> None:
    # RRM-009: the credential reference names a signing secret; the adapter mints a claim
    # bound to the parent's request scope, so the scope is required.
    adapter = DeepAgentsAsyncSubagentAdapter(
        now=lambda: NOW,
        secrets={"environment:AGENT_SERVER_TOKEN": "offline"},
        request_scope="tenant-a",
    )
    tools = adapter._tools(contract())  # qualification inspects the actual installed mechanism
    assert tuple(tools) == adapter.tool_names
    assert sha256_digest(tuple(tools)) == sha256_digest(adapter.tool_names)


@pytest.mark.asyncio
async def test_actual_middleware_start_and_check_are_governed_before_sdk_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline regression against the fake Agent Protocol client (never a live gate)."""

    client = FakeAgentProtocolClient(served=SERVED)
    install(monkeypatch, client)
    details = InMemoryAsyncSubagentDetailRepository()
    authority = InMemoryAsyncSubagentAuthority()
    secrets = {"environment:AGENT_SERVER_TOKEN": "offline-token"}
    provider = DeepAgentsAsyncSubagentAdapter(
        now=lambda: NOW, secrets=secrets, request_scope="tenant-a"
    )
    service = AsyncSubagentService(details, authority, provider, allow_new_spawns=True)

    execution = await service.spawn(request())
    assert authority.reservations
    assert client.calls[:3] == [
        "http.get:/belllabs/async-subagents/served-graphs",
        "sdk.threads.create",
        "sdk.runs.list",
    ]
    assert client.calls.count("sdk.runs.create") == 1
    created = client.runs_of(execution.child_execution_id)[0]
    assert created["metadata"]["belllabs_spawn_key"] == execution.child_execution_id
    assert created["multitask_strategy"] == "reject"
    await provider.start(contract(), execution, "retry after ambiguous provider response")
    assert client.calls.count("sdk.runs.create") == 1
    client.complete(execution.child_execution_id, "canonical child result")
    recovered_service = AsyncSubagentService(
        details,
        authority,
        DeepAgentsAsyncSubagentAdapter(now=lambda: NOW, secrets=secrets, request_scope="tenant-a"),
    )
    completed = await recovered_service.reconcile("tenant-a", execution.child_execution_id)
    assert completed.lifecycle == AsyncSubagentLifecycle.COMPLETED
    assert completed.result_manifest is not None
    assert completed.result_manifest.output_refs[0].startswith("ref:async-output:")
    assert completed.result_manifest.provider_checkpoint.graph_binding_digest == (
        GRAPH_BINDING_DIGEST
    )
    assert completed.result_manifest.usage.attribution == "provider_attributed"
    assert completed.result_manifest.usage.attributed_amounts == {
        "model.turns": 1,
        "tokens.total": 7,
    }
