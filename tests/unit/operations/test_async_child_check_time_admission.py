"""OVE-184: governed check-time admission, the sealed child's wire path and exact adoption.

Offline (T0): the fake Agent Protocol client stands in for the Agent Server and an in-memory
run control stands in for PostgreSQL; the Postgres proof is
``tests/integration/postgres/test_wi23_async_children_postgres.py``.

- Completion alone is not admission; the parent's check admits a completed child through the
  contract's registered policy, exactly once, and the admitted text and its
  ``child_result_index`` entry reach the parent's cognition.
- A foreign parent, another contract, a superseded generation or an unregistered policy never
  admit; a child admitted at check time is settled once at the parent boundary.
- A sealed child runs against its own assistant (one per binding and scope) whose
  configuration and every run name the binding digest; its final content blocks are text.
- Adoption offers the exact admitted bytes to one of the parent's own promises through its
  ordinary submission act, with the child's derivation; it never fulfills anything itself.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain.tools import ToolRuntime
from langgraph.types import Command

from mission_control.adapters.deep_agents.async_subagents import (
    ADOPT_TOOL,
    BellLabsAsyncSubagentMiddleware,
    DeepAgentsAsyncSubagentAdapter,
    final_message_text,
)
from mission_control.adapters.deep_agents.child_binding import seal_async_child_binding
from mission_control.adapters.deep_agents.routes import AGENT_FEATURES
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.subordinates.admission import CheckTimeAdmission
from mission_control.application.subordinates.adoption import (
    AdoptionRefused,
    AdoptionResult,
    AsyncChildOutputAdoption,
)
from mission_control.application.subordinates.parent_completion import (
    ASYNC_RESULT_POLICIES,
    AsyncChildCompletion,
    admit_typed_manifest,
)
from mission_control.application.subordinates.parent_effects import RunControlAsyncChildEffects
from mission_control.application.subordinates.service import (
    AsyncSubagentService,
    InMemoryAsyncSubagentAuthority,
    InMemoryAsyncSubagentDetailRepository,
    ProviderAsyncObservation,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.features import resolve_agent_configuration
from mission_control.domain.execution.async_child_admission import (
    adoption_ref,
    parse_adoption_ref,
)
from mission_control.domain.execution.async_subagent_reconciliation import (
    SEALED_BINDING_DIGEST_KEY,
    SEALED_CONTRACT_DIGEST_KEY,
    AsyncServedGraphIdentity,
    sealed_child_assistant_id,
)
from mission_control.domain.execution.contracts import (
    AsyncSubagentContract,
    AsyncSubagentDependencyClass,
    AsyncSubagentLifecycle,
    CapabilityGrant,
    DeepAgentExecutionBinding,
    OperationExecutionBinding,
)
from mission_control.domain.outputs.contracts import OutputForm, SubmissionAck
from mission_control.domain.outputs.rules import text_digest
from tests.acceptance.control_plane.test_wp_cp_040 import (
    exact_fixture,
    planned_invocation,
    unit_bound,
)
from tests.acceptance.control_plane.test_wp_cp_045 import DeterministicProvider
from tests.fixtures.fake_agent_protocol import FakeAgentProtocolClient, install
from tests.unit.operations.test_async_child_parent_budget import admitted_parent, spawn
from tests.unit.operations.test_async_child_parent_completion import Lineage
from tests.unit.run_control.test_run_control import actor

POLICY = "policy:async-result:v1"
SECRETS = {"environment:BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN": "offline-signing-secret"}
TEXT = "canonical child result"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


class ExactProvider(DeterministicProvider):
    """The deterministic provider with the adapter's exact output address for its text."""

    @staticmethod
    def _observation(
        status: str, run_id: str = "provider-run-1", receipt: str | None = None
    ) -> ProviderAsyncObservation:
        observation = DeterministicProvider._observation(status, run_id, receipt)
        if status != "success":
            return observation
        return observation.model_copy(
            update={
                "output_ref": "ref:async-output:" + sha256_digest(TEXT).removeprefix("sha256:"),
                "output_text": TEXT,
            }
        )


def _parent(run_id: str, binding_id: str = "binding-1") -> OperationExecutionBinding:
    return cast(
        OperationExecutionBinding,
        SimpleNamespace(request_scope="tenant-1", run_id=run_id, binding_id=binding_id),
    )


async def _governed() -> tuple[AsyncSubagentService, ExactProvider, Any, str, Any]:
    run_control, run_id = await admitted_parent()
    provider = ExactProvider([])
    service = AsyncSubagentService(
        InMemoryAsyncSubagentDetailRepository(),
        InMemoryAsyncSubagentAuthority(),
        provider,
        parent_effects=RunControlAsyncChildEffects(run_control, actor=actor()),  # type: ignore[arg-type]
        allow_new_spawns=True,
    )
    request = spawn(run_id)
    await service.spawn(request)
    return service, provider, run_control, run_id, request


@pytest.mark.asyncio
async def test_completion_alone_is_not_admission_and_the_check_admits_exactly_once() -> None:
    service, provider, run_control, run_id, request = await _governed()
    contract = request.contract
    admission = CheckTimeAdmission(service, policies={POLICY: admit_typed_manifest})
    child_id = (await service.reconcile("tenant-1", _child(service))).child_execution_id

    running = await service.reconcile("tenant-1", child_id)
    pending = await admission.admit(_parent(run_id), contract, running, current_generation=1)
    assert (pending.status, pending.reason, pending.output_text) == (
        "pending",
        "child_active",
        None,
    )

    provider.next_status = "success"
    completed = await service.reconcile("tenant-1", child_id)
    assert completed.lifecycle == AsyncSubagentLifecycle.COMPLETED
    assert (await service.link("tenant-1", child_id)).result_decision is None  # not admission

    first = await admission.admit(_parent(run_id), contract, completed, current_generation=1)
    assert first.status == "admitted" and first.newly_decided
    assert first.output_text == TEXT
    assert first.entry is not None and first.entry.id == child_id
    assert first.entry.admitted_by == "check_time"
    manifest = completed.result_manifest
    assert manifest is not None
    assert first.entry.adoption_ref == adoption_ref(child_id, manifest.manifest_digest)
    assert parse_adoption_ref(first.entry.adoption_ref) == (child_id, manifest.manifest_digest)

    again = await admission.admit(_parent(run_id), contract, completed, current_generation=1)
    assert again.status == "admitted" and not again.newly_decided
    assert again.entry == first.entry  # one index entry per child, however often checked

    # The parent boundary finds the decision, never decides again, and settles once.
    (record,) = await AsyncChildCompletion(
        service, Lineage(child_id), policies={POLICY: admit_typed_manifest}, wait_seconds=0
    ).complete(_parent(run_id), execution_generation=1)
    assert (record.result_decision, record.usage_disposition) == ("admit", "settled")
    link = await service.link("tenant-1", child_id)
    assert link.settled and link.settlement_revision == 1
    run = await run_control.get_run("tenant-1", run_id)
    (child,) = [item for item in run.async_children if item.child_execution_id == child_id]
    assert len(child.decisions) == 1  # one decision, whether checked once or twice


def _child(service: AsyncSubagentService) -> str:
    details = cast(InMemoryAsyncSubagentDetailRepository, service._details)
    (child_id,) = {key[1] for key in details.executions}
    return child_id


@pytest.mark.asyncio
async def test_foreign_parents_other_contracts_late_results_and_unknown_policies_refuse() -> None:
    service, provider, _run_control, run_id, request = await _governed()
    provider.next_status = "success"
    child_id = _child(service)
    completed = await service.reconcile("tenant-1", child_id)
    contract = request.contract

    unregistered = CheckTimeAdmission(service, policies={})
    pending = await unregistered.admit(_parent(run_id), contract, completed, current_generation=1)
    assert (pending.status, pending.reason) == ("pending", "admission_policy_not_registered")

    admission = CheckTimeAdmission(service, policies={POLICY: admit_typed_manifest})
    foreign = await admission.admit(
        _parent(run_id, "another-binding"), contract, completed, current_generation=1
    )
    assert (foreign.status, foreign.reason) == ("refused", "audience_mismatch")
    other = AsyncSubagentContract.create(
        **{
            **contract.model_dump(mode="python", exclude={"contract_digest"}),
            "description": "another configuration",
        }
    )
    assert (
        await admission.admit(_parent(run_id), other, completed, current_generation=1)
    ).reason == "contract_digest_mismatch"
    late = await admission.admit(_parent(run_id), contract, completed, current_generation=2)
    assert (late.status, late.reason) == ("refused", "late_result")
    assert (await service.link("tenant-1", child_id)).result_decision is None


def _sealed_contract(model: Any, url: str = "http://agent-server.invalid") -> AsyncSubagentContract:
    configuration, _ = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider=model.provider,
        sandbox_backend="state",
        lane_features=None,
        model_tools=None,
    )
    sealed = seal_async_child_binding(
        name="researcher",
        shape="seeded",
        system_prompt="Answer exactly what the objective asks.",
        model=model,
        tools=(),
        skills=(),
        mcp_servers=(),
        agent_configuration=configuration,
        authority_refs=("authority:parent-operation",),
        budget_limits={"tokens.total": 20},
    )
    return AsyncSubagentContract.create(
        contract_id=f"async-subagent:researcher:{sealed.sealed_digest}",
        name="researcher",
        description="Bounded background research",
        graph_id="belllabs_async_child",
        graph_revision="sealed-child@1",
        graph_binding_digest=sealed.sealed_digest,
        agent_protocol_url=url,
        deployment_credential_ref="environment:BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN",
        objective_schema_ref="schema:async-objective@1",
        result_schema_ref="schema:async-result@1",
        context_slice_id="context:child",
        state_slice_id="state:child",
        capability_ceiling=CapabilityGrant(capabilities=frozenset()),
        authority_refs=("authority:parent-operation",),
        budget_limits={"tokens.total": 20},
        dependency_classes=frozenset(
            {AsyncSubagentDependencyClass.NONBLOCKING, AsyncSubagentDependencyClass.ADVISORY}
        ),
        timeout_seconds=600,
        cancellation_propagation="required",
        late_result_policy="quarantine",
        fallback_policy="degrade",
        result_admission_policy_ref="policy:async-result:typed-manifest@1",
        child_binding=sealed,
    )


class RecordingAdopter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def adopt(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"tool": ADOPT_TOOL, "ok": True}


def _runtime(call_id: str, state: dict[str, Any]) -> ToolRuntime:
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _value: None,
        tool_call_id=call_id,
        store=None,
        tools=[],
    )


@pytest.mark.asyncio
async def test_a_sealed_child_runs_on_its_own_assistant_and_its_result_reaches_cognition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, _profile, _bundle = exact_fixture()
    contract = _sealed_contract(base.model)
    host = AsyncServedGraphIdentity(
        graph_id="belllabs_async_child",
        graph_revision="sealed-child@1",
        graph_binding_digest=sha256_digest("host-template"),
        deepagents_version="0.7.5",
        binding_mode="sealed_child",
    )
    client = FakeAgentProtocolClient(served=host, content_blocks=True)
    install(monkeypatch, client)
    binding = DeepAgentExecutionBinding.create(
        **{
            **base.model_dump(mode="python", exclude={"binding_digest", "async_subagents"}),
            "async_subagents": (contract,),
        }
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    operation = (await planned_invocation(unit_bound(binding), lineage)).binding
    scope = operation.request_scope
    provider = DeepAgentsAsyncSubagentAdapter(secrets=SECRETS, request_scope=scope)
    service = AsyncSubagentService(
        InMemoryAsyncSubagentDetailRepository(),
        InMemoryAsyncSubagentAuthority(),
        provider,
        allow_new_spawns=True,
    )
    adopter = RecordingAdopter()
    middleware = BellLabsAsyncSubagentMiddleware(
        service=service,
        adapter=provider,
        binding=operation,
        contracts=(contract,),
        admission=CheckTimeAdmission(service, policies=ASYNC_RESULT_POLICIES),
        adopter=adopter,
    )
    assert [tool.name for tool in middleware.tools][-1] == ADOPT_TOOL

    started = await middleware._start("Reply PONG", "researcher", _runtime("call-start", {}))
    assert isinstance(started, Command)
    tasks = cast(dict[str, Any], started.update)["async_tasks"]
    (child_id,) = tasks
    assistant_id = sealed_child_assistant_id(scope, contract.graph_binding_digest)
    assistant = client.assistants_store[assistant_id]
    sealed_keys = {
        SEALED_BINDING_DIGEST_KEY: contract.graph_binding_digest,
        SEALED_CONTRACT_DIGEST_KEY: contract.contract_digest,
    }
    assert assistant["graph_id"] == "belllabs_async_child"
    assert assistant["config"] == {"configurable": sealed_keys}
    assert assistant["metadata"]["request_scope"] == scope
    (run,) = client.runs_of(child_id)
    assert run["assistant_id"] == assistant_id
    assert sealed_keys.items() <= run["metadata"].items()
    assert run["metadata"]["belllabs_spawn_key"] == child_id

    state = {"async_tasks": tasks}
    checked = await middleware._check(child_id, _runtime("call-check-1", state))
    assert isinstance(checked, Command)
    assert '"status": "running"' in str(cast(dict[str, Any], checked.update)["messages"][0].content)

    # A follow-up while the child runs is a new run on the same sealed assistant.
    await middleware._update(child_id, "Now reply PING", _runtime("call-update", state))
    follow_up = client.runs_of(child_id)[-1]
    assert follow_up["assistant_id"] == assistant_id
    assert sealed_keys.items() <= follow_up["metadata"].items()
    assert follow_up["multitask_strategy"] == "interrupt"

    # The server stamps the exact sealed binding digest into the thread it ran.
    client.served = host.model_copy(update={"graph_binding_digest": contract.graph_binding_digest})
    client.complete(child_id, "PONG")
    admitted = await middleware._check(child_id, _runtime("call-check-2", state))
    assert isinstance(admitted, Command)
    update = cast(dict[str, Any], admitted.update)
    payload = json.loads(update["messages"][0].content)
    assert payload["status"] == "success" and payload["result"] == "PONG"
    assert payload["admission"]["decision"] == "admit"
    (entry,) = update["child_result_index"]
    assert entry["id"] == child_id and entry["decision"] == "admit"
    link = await service.link(scope, child_id)
    assert link.result_decision == "admit"
    assert link.admitted_manifest_digest == entry["manifest_digest"]

    second = await middleware._check(child_id, _runtime("call-check-3", state))
    assert cast(dict[str, Any], cast(Command, second).update)["child_result_index"] == [entry]

    adopted = await middleware._adopt(child_id, "report.final", _runtime("call-adopt", state))
    assert adopter.calls == [
        {
            "child_execution_id": child_id,
            "child_name": "researcher",
            "obligation_key": "report.final",
            "deliverable_id": None,
            "submission_key": "call-adopt",
        }
    ]
    assert '"ok": true' in adopted

    refused = await middleware._update(child_id, "Again", _runtime("call-update-2", state))
    assert isinstance(refused, str) and "accepts no message" in refused
    assert len(client.runs_of(child_id)) == 2  # nothing reached the provider
    assert client.calls.count("sdk.assistants.create") == 1


def test_the_final_message_text_joins_text_blocks_only() -> None:
    blocks = [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "PO"}, "NG"]
    assert final_message_text([{"type": "ai", "content": blocks}]) == "PONG"
    assert final_message_text([{"type": "ai", "content": "plain"}]) == "plain"
    assert final_message_text([], fallback="stock") == "stock"


class FakeSubmissions:
    def __init__(self, *, declared: bool = True) -> None:
        self.declared = declared
        self.requests: list[Any] = []

    async def pinned_obligation(self, access: Any, obligation_key: str) -> Any:
        del access
        if not self.declared:
            return None
        return SimpleNamespace(key=obligation_key, form=OutputForm.TEXT)

    async def submit_output(self, access: Any, request: Any, *, position: str | None) -> Any:
        del access
        self.requests.append((request, position))
        return SubmissionAck(submission_id="submission-1", status="accepted")


@pytest.mark.asyncio
async def test_adoption_offers_the_exact_admitted_bytes_and_never_fulfills() -> None:
    service, provider, _run_control, run_id, request = await _governed()
    child_id = _child(service)
    submissions = FakeSubmissions()
    adoption = AsyncChildOutputAdoption(service, submissions)
    access = cast(Any, object())

    async def adopt(parent: OperationExecutionBinding) -> AdoptionResult | AdoptionRefused:
        return await adoption.adopt(
            parent,
            access=access,
            position="executor",
            child_execution_id=child_id,
            child_name="researcher",
            obligation_key="report.final",
            deliverable_id=None,
            submission_key="call-adopt",
        )

    refused = await adopt(_parent(run_id))
    assert isinstance(refused, AdoptionRefused) and refused.code == "NOT_ADMITTED"
    provider.next_status = "success"
    completed = await service.reconcile("tenant-1", child_id)
    await CheckTimeAdmission(service, policies={POLICY: admit_typed_manifest}).admit(
        _parent(run_id), request.contract, completed, current_generation=1
    )
    foreign = await adopt(_parent(run_id, "another-binding"))
    assert isinstance(foreign, AdoptionRefused) and foreign.code == "AUDIENCE_MISMATCH"

    result = await adopt(_parent(run_id))
    assert isinstance(result, AdoptionResult) and result.ack.status == "accepted"
    ((submitted, position),) = submissions.requests
    assert position == "executor"
    (item,) = submitted.items
    assert (item.kind, item.text, item.digest) == ("inline", TEXT, text_digest(TEXT))
    assert item.deliverable_id == "final"
    manifest = completed.result_manifest
    assert manifest is not None
    assert submitted.derivation_refs == (adoption_ref(child_id, manifest.manifest_digest),)
    assert result.derivation_ref == submitted.derivation_refs[0]

    undeclared = await AsyncChildOutputAdoption(service, FakeSubmissions(declared=False)).adopt(
        _parent(run_id),
        access=access,
        position="executor",
        child_execution_id=child_id,
        child_name="researcher",
        obligation_key="report.other",
        deliverable_id=None,
        submission_key="call-adopt-2",
    )
    assert isinstance(undeclared, AdoptionRefused) and undeclared.code == "OBLIGATION_UNDECLARED"


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", sorted(ASYNC_RESULT_POLICIES))
async def test_the_boundary_never_redecides_a_child_admitted_at_check_under_either_policy(
    policy: str,
) -> None:
    """Review N2: both registered keys (the technical-child name and its typed-manifest
    alias) admit at check time once; the parent boundary only settles."""

    service, provider, run_control, run_id, request = await _governed()
    child_id = _child(service)
    details = cast(InMemoryAsyncSubagentDetailRepository, service._details)
    key = (request.request_scope, child_id)
    details.links[key] = details.links[key].model_copy(
        update={"result_admission_policy_ref": policy}
    )
    provider.next_status = "success"
    completed = await service.reconcile("tenant-1", child_id)
    admitted = await CheckTimeAdmission(service, policies=ASYNC_RESULT_POLICIES).admit(
        _parent(run_id), request.contract, completed, current_generation=1
    )
    assert admitted.status == "admitted" and admitted.newly_decided
    (record,) = await AsyncChildCompletion(
        service, Lineage(child_id), policies=ASYNC_RESULT_POLICIES, wait_seconds=0
    ).complete(_parent(run_id), execution_generation=1)
    assert (record.result_decision, record.usage_disposition) == ("admit", "settled")
    run = await run_control.get_run("tenant-1", run_id)
    (child,) = [item for item in run.async_children if item.child_execution_id == child_id]
    assert len(child.decisions) == 1


@pytest.mark.asyncio
async def test_adopting_the_same_tool_call_twice_submits_once() -> None:
    """Review S3: the tool call id is the submission key; a retry is the same act."""

    from mission_control.application.knowledge.access import InvocationAccess
    from tests.fixtures.output_contracts import InMemoryOutputContractStore
    from tests.unit.knowledge.test_gateway import origin
    from tests.unit.outputs.scenario import build_stack, obligation

    service, provider, _run_control, run_id, request = await _governed()
    child_id = _child(service)
    provider.next_status = "success"
    completed = await service.reconcile("tenant-1", child_id)
    await CheckTimeAdmission(service, policies={POLICY: admit_typed_manifest}).admit(
        _parent(run_id), request.contract, completed, current_generation=1
    )
    store = InMemoryOutputContractStore()
    access = InvocationAccess(
        origin=origin(),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=NOW,
    )
    stack = await build_stack(
        store, store.submissions, access, obligation("report.final", OutputForm.TEXT)
    )
    adoption = AsyncChildOutputAdoption(service, stack.submissions)
    results = [
        await adoption.adopt(
            _parent(run_id),
            access=access,
            position="draft",
            child_execution_id=child_id,
            child_name="researcher",
            obligation_key="report.final",
            deliverable_id=None,
            submission_key="call-adopt",
        )
        for _ in range(2)
    ]
    assert all(isinstance(item, AdoptionResult) for item in results)
    first, second = cast(list[AdoptionResult], results)
    assert first.ack.status == second.ack.status == "accepted", first.ack.error
    assert first.ack.submission_id == second.ack.submission_id
    assert len(store.outputs) == 1 and len(store.by_submission) == 1
