"""Knowledge tools in the Deep Agents lane (SV-16 deliverable 4; design §8, M02/M06).

The six tools are LangChain tools over the lane-neutral toolset. They are resolved through
the existing exact-component path (registry digest + schema digest) and receipted like other
host tools; every call reads the live invocation bound for the attempt and the toolset builds
a fresh access for it; arguments cannot carry an origin; outputs are structured documents
with typed refusal codes; ``submit_output`` submits under the tool-call id and the attempt's
completion hands the selected report to the independent assessment.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.adapters.deep_agents.knowledge_tools import (
    CURRENT_INVOCATION,
    KnowledgeLaneSupport,
    knowledge_registry_tools,
    knowledge_tool_components,
    live_invocation,
)
from mission_control.adapters.deep_agents.lane import _component_items
from mission_control.adapters.deep_agents.materializer import (
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
)
from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
from mission_control.adapters.knowledge.invocation_locator import InMemoryInvocationLocator
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.toolset import (
    TOOL_NAMES,
    KnowledgeToolset,
    LiveInvocation,
)
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.ports.knowledge import RecordedUseDecision
from mission_control.contracts.knowledge_protocol import digest_bytes
from mission_control.domain.knowledge.effects import JournalState
from mission_control.domain.knowledge.origin import MissionIdentityUnavailable
from tests.fixtures.knowledge_binding import (
    AUDIENCE,
    BINDING,
    FakeKnowledgeBinding,
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    InMemoryLineageStore,
    InMemorySubmissionStore,
    Issuer,
    RecordingMinter,
    SteppingClock,
    knowledge_port,
    model_report,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.knowledge.test_gateway import INSTALLATION, TENANT

RUN = "22222222-2222-4222-8222-222222222222"
# Provenance slice 1: the run's ledger mission and the activation row of its runtime unit.
MISSION = "44444444-4444-4444-8444-444444444444"
UNIT = "unit:stage/draft"
ACTIVATION = "55555555-5555-4555-8555-555555555555"


@dataclass
class Lane:
    clock: SteppingClock
    fake: FakeKnowledgeBinding
    journal: InMemoryKnowledgeJournal
    store: InMemorySubmissionStore
    minter: RecordingMinter
    support: KnowledgeLaneSupport
    toolset: KnowledgeToolset
    decisions: InMemoryUseDecisionStore
    sleeps: list[float]
    locator: InMemoryInvocationLocator

    def live(self, attempt: int = 1, generation: int = 1) -> LiveInvocation:
        """The located live attempt (the ids the locator resolves for RUN and UNIT)."""

        return LiveInvocation(
            request_scope=f"mc/{INSTALLATION}/biotech/{TENANT}",
            run_id=RUN,
            operation_id="stage/draft",
            operation_attempt=attempt,
            execution_generation=generation,
            lane="deep_agents",
            obligations=("report",),
            mission_id=MISSION,
            activation_id=ACTIVATION,
            unit_key=UNIT,
        )

    async def decide(self, name: str) -> str:
        """The host records an exact use decision (a trusted step); the agent gets its handle."""

        handle = f"kh:{BINDING}/decision/{name}@use-decision.v1"
        await self.decisions.record(
            self.toolset.access(self.live()).scope,
            RecordedUseDecision(
                handle=handle,
                binding_id=BINDING,
                tenant_id=TENANT,
                use_decision_id=name,
                bound_effect_digest=digest_bytes(name.encode()),
                processed_epoch=0,
                plan={
                    "schemaVersion": "knowledge-ingestion-intent.v1",
                    "intentId": name,
                    "context": {"tenantId": TENANT},
                    "proposals": [{"kind": "claim.add", "claim": name}],
                },
                normalized_values_digest=digest_bytes(b"normalized"),
            ),
        )
        return handle

    async def call(self, name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
        message = await self.support.tools[name].ainvoke(
            {"name": name, "args": args, "id": call_id, "type": "tool_call"}
        )
        return json.loads(message.content)


def lane() -> Lane:
    clock = SteppingClock(step=timedelta(milliseconds=1))
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    journal = InMemoryKnowledgeJournal()
    minter = RecordingMinter(issuer.minter())

    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    decisions = InMemoryUseDecisionStore()
    gateway = KnowledgeGateway(
        client=fake,
        journal=journal,
        handles=InMemoryKnowledgeHandleStore(),
        minter=minter,
        content=fake,
        decisions=decisions,
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=clock,
        sleep=sleep,
    )
    store = InMemorySubmissionStore()
    locator = InMemoryInvocationLocator({RUN: MISSION}, {(RUN, UNIT): ACTIVATION})
    toolset = KnowledgeToolset(
        gateway=gateway,
        submissions=SubmissionService(store, assessor=gateway, clock=clock),
        issuer="mission-control",
        clock=clock,
        lineage=InMemoryLineageStore(),
        sleep=sleep,
        locator=locator,
    )
    return Lane(
        clock,
        fake,
        journal,
        store,
        minter,
        KnowledgeLaneSupport(toolset),
        toolset,
        decisions,
        sleeps,
        locator,
    )


def test_model_facing_schemas_have_no_origin_and_refuse_one() -> None:
    tools = lane().support.tools
    assert set(tools) == set(TOOL_NAMES)
    for tool in tools.values():
        properties = tool.tool_call_schema.model_json_schema()["properties"]
        assert not {"origin", "tenant", "credential", "tool_call_id"} & set(properties)


async def test_a_forged_origin_argument_is_refused_before_any_dispatch() -> None:
    h = lane()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        with pytest.raises(ValidationError):
            await h.call("report_register", {"report": {"x": 1}, "origin": {"x": 1}}, "c-0")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert h.fake.calls == []


async def test_every_dispatch_refreshes_the_live_access_and_journals_first() -> None:
    h = lane()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        registered = await h.call("report_register", {"report": model_report("report-7")}, "c-1")
        applied = await h.call("knowledge_apply", {"decision": await h.decide("d-1")}, "c-2")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert registered["ok"] and registered["result"]["journal_state"] == "applied"
    assert registered["result"]["receipt_digest"] is not None
    assert applied["ok"]
    first, second = (call.claims for call in h.fake.calls_of("invoke"))
    assert first.origin.invocationId != second.origin.invocationId
    assert first.origin.mission is not None and first.origin.mission.operationAttempt == 1
    for key in h.fake.committed:
        assert [
            state
            for _old, state in h.journal.history[next(k for k in h.journal.history if k[1] == key)]
        ] == [
            JournalState.PREPARED,
            JournalState.DISPATCHED,
            JournalState.APPLIED,
        ]

    retry = CURRENT_INVOCATION.set(h.live(attempt=2, generation=2))
    try:
        await h.call("knowledge_apply", {"decision": await h.decide("d-3")}, "c-3")
    finally:
        CURRENT_INVOCATION.reset(retry)
    third = h.fake.calls_of("invoke")[-1].claims
    assert third.origin.mission is not None
    assert (third.origin.mission.operationAttempt, third.origin.mission.executionGeneration) == (
        2,
        2,
    )


async def test_submit_output_uses_the_tool_call_key_and_completion_starts_assessment() -> None:
    h = lane()
    h.fake.operation_statuses["report.assess"] = deque(["running", "succeeded"])
    token = CURRENT_INVOCATION.set(h.live())
    try:
        registered = await h.call("report_register", {"report": model_report("report-7")}, "c-1")
        receipt = next(iter(h.fake.committed.values()))
        (report,) = receipt.affectedRefs
        item = {
            "kind": "handle",
            "ref": f"kh:{report.binding}/report/{report.id}@{report.version}",
            "digest": report.digest,
        }
        first = await h.call("submit_output", {"obligation": "report", "items": [item]}, "c-9")
        replay = await h.call("submit_output", {"obligation": "report", "items": [item]}, "c-9")
        bare = await h.call(
            "submit_output",
            {"obligation": "report", "items": [item | {"ref": "report-7"}]},
            "c-10",
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    assert registered["ok"] and first["ok"] and replay == first
    assert first["result"]["revision"] == 1
    assert bare["ok"] is False and bare["refusal"]["code"] == "SCHEMA_UNSUPPORTED"
    (submission,) = h.store.rows.values()
    assert submission.submission_key == "c-9"

    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    assert h.support.uses_knowledge(invocation)
    report_out = await h.support.complete(invocation)
    # The lane binding declares no obligations yet (wiring the compiled promises into the
    # Deep Agents live invocation is follow-up work): the submitted row is reported as
    # undeclared and never counted, while the independent assessment still ran.
    assert report_out is not None and report_out.outcome_basis == "no_declared_obligations"
    assert report_out.outcome == "unfulfilled" and report_out.obligations == ()
    assert h.store.rows[submission.submission_id].assessment_state == "assessed"


async def test_no_bound_invocation_is_a_typed_refusal() -> None:
    h = lane()
    out = await h.call("knowledge_apply", {"decision": "kh:x/decision/d@v1"}, "c-1")
    assert out == {
        "tool": "knowledge_apply",
        "ok": False,
        "result": None,
        "refusal": {"code": "SCOPE_DENIED", "message": "no live invocation is bound"},
    }


def test_tools_resolve_by_exact_digest_and_are_receipted_like_host_tools() -> None:
    tools = lane().support.tools
    components = knowledge_tool_components(tools)
    assert [component.tool_name for component in components] == list(TOOL_NAMES)
    materializer = ExactDeepAgentMaterializer(
        ExactComponentRegistry(model_factories={}, tools=knowledge_registry_tools(tools))
    )
    for component in components:
        resolved = materializer._resolve_tool(
            component.ref.digest, component.schema_digest, component.tool_name
        )
        assert resolved is tools[component.tool_name]
    rows = _component_items((), (), components)
    assert {(row.kind, row.name, row.verdict) for row in rows} == {
        ("tool", name, "native") for name in TOOL_NAMES
    }
    assert {row.digest for row in rows} == {component.schema_digest for component in components}


def test_the_live_invocation_is_the_bound_attempt() -> None:
    h = lane()
    invocation = _runtime_invocation(h.live(attempt=3, generation=2), tool_names=("submit_output",))
    live = live_invocation(invocation)  # type: ignore[arg-type]
    assert (live.run_id, live.operation_id, live.operation_attempt, live.execution_generation) == (
        RUN,
        "stage/draft",
        3,
        2,
    )
    with h.support.bind(invocation) as bound:  # type: ignore[arg-type]
        assert CURRENT_INVOCATION.get() == bound
    assert CURRENT_INVOCATION.get() is None
    plain = _runtime_invocation(h.live(), tool_names=("write_file",))
    assert not h.support.uses_knowledge(plain)  # type: ignore[arg-type]


def _runtime_invocation(live: LiveInvocation, *, tool_names: tuple[str, ...]) -> Any:
    deep = SimpleNamespace(
        execution_generation=live.execution_generation,
        tools=tuple(SimpleNamespace(tool_name=name) for name in tool_names),
    )
    return SimpleNamespace(
        binding=SimpleNamespace(
            request_scope=live.request_scope,
            run_id=live.run_id,
            operation_id=live.operation_id,
            operation_attempt=live.operation_attempt,
            transfer=None,
            runtime_unit=None if live.unit_key is None else SimpleNamespace(unit_key=live.unit_key),
            **lane_fields(deep),
        )
    )


async def test_stop_during_review_cancels_and_completion_reconciles_uncertain_effects() -> None:
    h = lane()
    h.fake.operation_statuses["verify.claims"] = deque(["running"] + ["waiting_review"] * 20)
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    token = CURRENT_INVOCATION.set(h.live())
    try:
        started = await h.call("verify_claims", {"claims": [{"id": "c-1"}]}, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert started["ok"] and started["result"]["status"] == "waiting_review"
    await h.support.stop(invocation)
    await h.support.stop(invocation)  # idempotent: one cancel reaches the binding
    (cancel,) = h.fake.calls_of("operation.cancel")
    assert cancel.claims.operations == ["operation.cancel"]
    (operation,) = h.fake.operations.values()
    assert operation.status.state == "cancelled"
    assert operation.status.cancelRequestId == f"stop:{RUN}:stage/draft:1"

    later = lane()
    later.fake.invoke_script.append("lost")
    later.fake.lookups.append("not_found")
    token = CURRENT_INVOCATION.set(later.live())
    try:
        lost = await later.call(
            "knowledge_apply", {"decision": await later.decide("d-lost")}, "c-1"
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    assert lost["result"]["journal_state"] == "uncertain"
    assert lost["refusal"]["code"] == "UNRESOLVED_EFFECT"
    await later.support.complete(_runtime_invocation(later.live(), tool_names=TOOL_NAMES))
    (row,) = later.journal.rows.values()
    assert row.state is JournalState.APPLIED and row.reconciled
    recovery = later.fake.calls_of("receipt.get")[-1].claims
    assert recovery.origin.kind == "recovery" and recovery.recovery is not None
    assert recovery.recovery.scope == "read_only"


async def test_lineage_production_by_the_registrar_and_adoption_by_another_invocation() -> None:
    from mission_control.domain.knowledge.lineage import ProvenanceRole

    h = lane()
    lineage = h.toolset.lineage
    assert lineage is not None
    token = CURRENT_INVOCATION.set(h.live())
    try:
        await h.call("report_register", {"report": model_report("report-7")}, "c-1")
        (report,) = next(iter(h.fake.committed.values())).affectedRefs
        handle = f"kh:{report.binding}/report/{report.id}@{report.version}"
        item = {"kind": "handle", "ref": handle, "digest": report.digest}
        await h.call("submit_output", {"obligation": "report", "items": [item]}, "c-2")
    finally:
        CURRENT_INVOCATION.reset(token)
    scope = h.toolset.access(h.live()).scope
    own = await lineage.facts(scope, handle)
    assert sorted(fact.role.value for fact in own) == ["caller", "producer", "receipt"]
    producer = next(fact for fact in own if fact.role is ProvenanceRole.PRODUCER)
    assert producer.actor_origin is not None and producer.actor_origin.operation_id == "stage/draft"

    # Another operation selecting the same report adopts it (never a second producer).
    other = LiveInvocation(**{**h.live().__dict__, "operation_id": "stage/review"})
    token = CURRENT_INVOCATION.set(other)
    try:
        adopted = await h.call("submit_output", {"obligation": "report", "items": [item]}, "c-3")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert adopted["ok"]
    facts = await lineage.facts(scope, handle)
    assert sorted(fact.role.value for fact in facts) == ["adopter", "caller", "producer", "receipt"]
    adopter = next(fact for fact in facts if fact.role is ProvenanceRole.ADOPTER)
    assert adopter.fact["act"] == "adoption" and adopter.actor_ref.endswith(":report")


async def test_apply_names_a_decision_handle_and_the_host_supplies_the_exact_use() -> None:
    h = lane()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        handle = await h.decide("d-exact")
        applied = await h.call("knowledge_apply", {"decision": handle}, "c-1")
        unknown = await h.call(
            "knowledge_apply", {"decision": f"kh:{BINDING}/decision/none@use-decision.v1"}, "c-2"
        )
        with pytest.raises(ValidationError):  # an agent-typed intent is not an argument
            await h.call("knowledge_apply", {"intent": {"add": ["c-1"]}}, "c-3")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert applied["ok"] and applied["result"]["journal_state"] == "applied"
    (call,) = h.fake.calls_of("invoke")
    envelope = call.envelope
    assert envelope is not None and envelope.effect is not None and envelope.input is not None
    assert envelope.input.nativeContract.name == "knowledge-ingestion-intent"
    payload = envelope.input.inlinePayload
    assert isinstance(payload, dict)
    exact = payload["exactUse"]
    # The recorded decision, never typed by the agent: id, plan-level digest, epoch,
    # normalized-values digest, plus the bound effect key and originating origin.
    assert exact["useDecisionId"] == "d-exact"
    assert exact["boundEffectDigest"] == envelope.effect.boundEffectDigest
    assert exact["boundEffectDigest"] == digest_bytes(b"d-exact")
    assert exact["effectKey"] == envelope.effect.effectKey
    assert exact["originatingOrigin"] == envelope.effect.originatingOrigin.model_dump(mode="json")
    assert unknown["ok"] is False and unknown["refusal"]["code"] == "NOT_FOUND"
    assert len(h.fake.calls_of("invoke")) == 1


async def test_node_end_polls_a_pending_effect_then_settlement_blocks_until_delivery() -> None:
    h = lane()
    h.fake.invoke_script.append("pending")
    token = CURRENT_INVOCATION.set(h.live())
    try:
        pending = await h.call("knowledge_apply", {"decision": await h.decide("d-queued")}, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert pending["ok"] and pending["result"]["pending_delivery"] is True
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    blocked = await h.support.complete(invocation)
    assert blocked is not None and blocked.blocked and blocked.outcome == "blocked"
    assert blocked.finalization_id is None and blocked.outcome_basis == "unresolved_effects"
    ((key, row),) = h.journal.rows.items()
    assert blocked.blocked_effects == (row.effect_key,)
    assert row.state is JournalState.UNCERTAIN
    # Bounded receipt-first poll: one lookup per attempt, backoff between, then stop.
    attempts = h.toolset.reconcile_attempts
    assert len(h.fake.calls_of("receipt.get")) == attempts
    assert h.sleeps == [0.5, 1.0, 2.0, 4.0][: attempts - 1]
    assert h.store.finalizations == {}
    assert len(h.fake.calls_of("invoke")) == 1  # never redispatched

    # The recovery path after the run: delivery reported, the effect settles, then the
    # finalization is recorded once.
    h.fake.lookups.append("delivery:applied")
    settled = await h.toolset.settle(h.live())
    assert not settled.blocked and settled.finalization_id is not None
    assert h.journal.rows[key].state is JournalState.APPLIED
    assert len(h.store.finalizations) == 1


# ---------------------------------------------------------------- R2-MC D1 / D2 / O1


async def _register_and_finalize(h: Lane, live: LiveInvocation) -> dict[str, Any]:
    h.fake.operation_statuses["report.assess"] = deque(["succeeded"] * 4)
    token = CURRENT_INVOCATION.set(live)
    try:
        await h.call("report_register", {"report": model_report("report-9")}, "c-reg")
        (report,) = next(iter(h.fake.committed.values())).affectedRefs
        item = {
            "kind": "handle",
            "ref": f"kh:{report.binding}/report/{report.id}@{report.version}",
            "digest": report.digest,
        }
        await h.call("submit_output", {"obligation": "report", "items": [item]}, "c-sub")
    finally:
        CURRENT_INVOCATION.reset(token)
    report_out = await h.support.complete(_runtime_invocation(live, tool_names=TOOL_NAMES))
    assert report_out is not None and report_out.finalization_id is not None
    return item


async def test_no_run_wide_report_loading_survives_in_the_knowledge_lane() -> None:
    """WI-02: a finalized upstream report never reaches another invocation through the
    knowledge toolset; inputs arrive only through the receiver's sealed transfer plan."""

    from dataclasses import replace

    h = lane()
    await _register_and_finalize(h, h.live())
    assert not hasattr(h.toolset, "deliver_inputs") and not hasattr(h.toolset, "delivery")
    review = replace(h.live(), operation_id="stage/review")
    begun = await h.support.begin(_runtime_invocation(review, tool_names=TOOL_NAMES))
    assert begun.operation_id == "stage/review"  # only the live attempt, no inputs


async def test_report_collection_tool_refusal_is_structured_and_advertised() -> None:
    from mission_control.application.knowledge.toolset import TOOL_ARGUMENTS, TOOL_DESCRIPTIONS
    from tests.unit.knowledge.test_submission_assessment import report_selection

    h = lane()
    item = report_selection().items[0].model_dump()
    result = await h.toolset.dispatch(
        "submit_output",
        {"obligation": "report", "items": [item, item]},
        h.live(),
        tool_call_id="duplicate",
    )
    assert not result["ok"] and result["refusal"]["code"] == "SCHEMA_UNSUPPORTED"
    assert not h.store.rows
    assert "unsupported" in TOOL_DESCRIPTIONS["submit_output"]
    schema = TOOL_ARGUMENTS["submit_output"].model_json_schema()
    assert "unsupported" in schema["properties"]["items"]["description"]


async def test_a_retry_attempt_gets_a_host_grant_and_resends_the_uncertain_effect() -> None:
    h = lane()
    h.fake.invoke_script.append("lost")  # committed natively, the answer is lost
    h.fake.lookups.extend(["not_found", "not_found"])  # both lookups race the commit
    first = h.live()
    token = CURRENT_INVOCATION.set(first)
    try:
        lost = await h.call("report_register", {"report": model_report("report-r")}, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert lost["result"]["journal_state"] == "uncertain"
    ((key, row),) = h.journal.rows.items()

    # Without host authority a later attempt is refused before anything is sent.
    plain = h.live(attempt=2, generation=2)
    token = CURRENT_INVOCATION.set(plain)
    try:
        refused = await h.call("report_register", {"report": model_report("report-r")}, "c-2")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert refused["refusal"]["code"] == "ORIGIN_MISMATCH"
    assert len(h.fake.calls_of("invoke")) == 1

    # The host mints one effect-scoped grant for exactly that effect at attempt start.
    retry = await h.toolset.begin(h.live(attempt=2, generation=2))
    (grant,) = retry.recovery_grants
    assert (grant.effect_key, grant.bound_effect_digest) == (
        row.effect_key,
        row.bound_effect_digest,
    )
    h.fake.lookups.append("not_found")
    token = CURRENT_INVOCATION.set(retry)
    try:
        resent = await h.call("report_register", {"report": model_report("report-r")}, "c-3")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert resent["ok"] and resent["result"]["journal_state"] == "applied"
    claims = h.fake.calls_of("invoke")[-1].claims
    assert claims.recovery is not None and claims.recovery.scope == "effect"
    assert claims.recovery.authorityRef == grant.authority_ref
    assert claims.origin.mission is not None and claims.origin.mission.operationAttempt == 2
    # Same receipt (native deduplication), recorded under the grant.
    (receipt,) = h.fake.committed.values()
    assert resent["result"]["receipt_digest"] == receipt.digest
    assert h.journal.rows[key].recovery_authority_ref == grant.authority_ref
    # Attempt 1 itself, or an attempt with nothing unresolved, gets no grant.
    assert (await h.toolset.begin(first)).recovery_grants == ()
    assert (await h.toolset.begin(h.live(attempt=3, generation=3))).recovery_grants == ()


async def test_a_failed_attempt_reconciles_and_records_attempt_failed() -> None:
    h = lane()
    h.fake.invoke_script.append("lost")
    h.fake.lookups.append("not_found")
    token = CURRENT_INVOCATION.set(h.live())
    try:
        await h.call("knowledge_apply", {"decision": await h.decide("d-failed")}, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    await h.support.fail(invocation)
    ((_, row),) = h.journal.rows.items()
    assert row.state is JournalState.APPLIED and row.reconciled  # reconciled before recording
    ((_, finalization),) = h.store.finalizations.items()
    assert finalization.outcome_basis == "attempt_failed"
    assert finalization.outcome == "unfulfilled"


async def test_register_declares_the_task_use_and_audience_on_the_envelope() -> None:
    h = lane()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        task = {"use": "knowledge_ingestion.fact_assert_state", "audience": "official"}
        await h.call(
            "report_register",
            {"report": model_report("report-u", **task)},
            "c-1",
        )
        bare = {"report": model_report("report-v")}
        await h.call("report_register", bare, "c-2")
    finally:
        CURRENT_INVOCATION.reset(token)
    declared, undeclared = (call.envelope for call in h.fake.calls_of("invoke"))
    assert declared is not None and undeclared is not None
    assert declared.use == "knowledge_ingestion.fact_assert_state"
    assert declared.audience == "official"
    assert (undeclared.use, undeclared.audience) == (None, None)
    assert "use" not in undeclared.model_dump(mode="json")  # absent on the wire and in the digest


# --- Provenance slice 1 (OVE-204): the true mission origin -------------------------------------


async def test_the_lane_origin_names_the_ledger_mission_and_activation() -> None:
    """(a)/(c): the Deep Agents path resolves the run's ledger mission id and the activation row
    of the binding's runtime unit; the K01 wire coordinates carry those ids (never the run id
    as mission, never a derived activation)."""

    h = lane()
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    unresolved = live_invocation(invocation)
    assert (unresolved.mission_id, unresolved.activation_id, unresolved.unit_key) == (
        None,
        None,
        UNIT,
    )
    begun = await h.support.begin(invocation)
    assert (begun.mission_id, begun.activation_id) == (MISSION, ACTIVATION)
    access = h.toolset.access(begun)
    assert (access.origin.mission_id, access.origin.run_id, access.origin.activation_id) == (
        MISSION,
        RUN,
        ACTIVATION,
    )
    wire = access.wire_origin().mission
    assert wire is not None
    assert (wire.missionId, wire.runId, wire.activationId) == (MISSION, RUN, ACTIVATION)
    # The unit key is Mission Control side only: journal coordinates and identity, no origin.
    assert access.unit_key == UNIT
    assert access.coordinates().unit_key == UNIT and access.identity().unit_key == UNIT
    assert "unit_key" not in access.origin.model_dump()
    # Inside the bound attempt, the transfer-plan access reuses the located attempt.
    calls = len(h.locator.calls)
    with h.support.bind(invocation, begun):  # type: ignore[arg-type]
        plan_access = await h.support.access_for(invocation)  # type: ignore[arg-type]
    assert len(h.locator.calls) == calls
    assert plan_access.invocation_ref == access.invocation_ref


async def test_a_runtime_unit_without_an_activation_row_names_no_activation() -> None:
    h = lane()
    h.locator.activations.clear()
    begun = await h.support.begin(_runtime_invocation(h.live(), tool_names=TOOL_NAMES))
    origin = h.toolset.access(begun).origin
    assert (origin.mission_id, origin.activation_id) == (MISSION, None)


async def test_every_settlement_pass_of_one_attempt_has_the_same_invocation_ref() -> None:
    """(b)/(d)/(e): begin, settle and settle_saved (a fresh worker re-locating from the binding
    alone) present one origin digest; the journal row of a dispatched effect has its unit key;
    the producer's lineage actor ref is that invocation ref."""

    h = lane()
    prepared: list[Any] = []
    prepare = h.journal.prepare

    async def recording(request: Any) -> Any:
        prepared.append(request.coordinates)
        return await prepare(request)

    h.journal.prepare = recording  # type: ignore[method-assign]
    invocation = _runtime_invocation(h.live(), tool_names=TOOL_NAMES)
    begun = await h.support.begin(invocation)
    ref = h.toolset.access(begun).invocation_ref
    decision = await h.decide("d-1")
    with h.support.bind(invocation, begun):  # type: ignore[arg-type]
        applied = await h.call("knowledge_apply", {"decision": decision}, "c-1")
    assert applied["ok"]
    (coordinates,) = prepared
    assert (coordinates.mission_id, coordinates.activation_id, coordinates.unit_key) == (
        MISSION,
        ACTIVATION,
        UNIT,
    )
    (row,) = h.journal.rows.values()
    assert row.originating_origin.mission is not None
    assert row.originating_origin.mission.missionId == MISSION

    # A fresh worker after a restart re-locates from the binding alone: the same origin.
    fresh = KnowledgeLaneSupport(h.toolset)
    relocated = await h.toolset.locate(live_invocation(invocation))
    assert h.toolset.access(relocated).invocation_ref == ref
    outcome = await fresh.settle(invocation)  # type: ignore[arg-type]
    assert outcome.state == "settled"
    assert {key[1] for key in h.store.finalizations} == {ref}


async def test_access_refuses_an_unresolved_live_attempt() -> None:
    """(f): fail closed: no origin without the ledger mission id (no locator, unknown run)."""

    h = lane()
    unresolved = live_invocation(_runtime_invocation(h.live(), tool_names=TOOL_NAMES))
    with pytest.raises(MissionIdentityUnavailable):
        h.toolset.access(unresolved)
    h.toolset.locator = None
    with pytest.raises(MissionIdentityUnavailable):
        await h.toolset.locate(unresolved)
    h.toolset.locator = InMemoryInvocationLocator()
    with pytest.raises(MissionIdentityUnavailable):
        await h.toolset.begin(unresolved)
    # A tool dispatch inside an attempt bound without its located live attempt refuses too.
    with pytest.raises(MissionIdentityUnavailable):
        await h.toolset.dispatch(
            "knowledge_read",
            {"handle": "kh:x/report/r@1", "digest": "sha256:" + "0" * 64},
            unresolved,
            tool_call_id="c-1",
        )
