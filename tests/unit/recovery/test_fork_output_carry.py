"""F1-G4: a reused Stage Graph unit carries the source's accepted named outputs, still accepted.

The source run accepted ``collect_a.notes_a``; the fork-derived run reuses ``collect_a``. The
carry adopts the exact accepted revision into the derived run under one host invocation of the
derived unit, finalizes it without an assessment handoff and promotes it, so the derived run's
accepted head carries the source's bytes and a consumer resolves it exactly. Nothing is
re-judged, an Activity retry records nothing new, and a source without an accepted head carries
nothing (the consumer's unresolved dependency is reported by the family).
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_knowledge_tools import MISSION, lane
from tests.unit.outputs.scenario import host_access, obligation, promises, text

from mission_control.application.knowledge.toolset import LiveInvocation
from mission_control.application.outputs.adoption import OutputAdoptionService
from mission_control.application.outputs.fulfillment import OutputFulfillmentService, PromoteOutput
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.recovery.fork_outputs import FORK_REUSE_LANE, ForkOutputCarry
from mission_control.domain.execution.contracts import ReusedResultRef
from mission_control.domain.graph_runtime.identities import StageGraphUnitLocation
from mission_control.domain.outputs.contracts import OutputForm, SubmitOutput
from mission_control.domain.policies.forks import ForkOutputsNotCarried

pytestmark = pytest.mark.asyncio

SOURCE = "33333333-3333-4333-8333-333333333333"
DERIVED = "66666666-6666-4666-8666-666666666666"
UNIT = "unit:derived/collect_a"
NOTE = "source: arxiv-2310.06825-abstract\nmistral-7b: 7-billion-parameter"


def promise_set() -> Any:
    return promises(
        obligation("collect_a.notes_a", OutputForm.TEXT, position="collect_a"),
        obligation("synthesize.synthesis", OutputForm.TEXT, position="synthesize"),
    )


def binding(scope: str) -> Any:
    location = StageGraphUnitLocation(
        stage_id="collect_a",
        mapped_instance_id="collect_a",
        workflow_cycle_ordinal=0,
        stage_cycle_ordinal=0,
        operation_slot_id="default",
    )
    return SimpleNamespace(
        request_scope=scope,
        run_id=DERIVED,
        operation_id="stage/collect_a/derived",
        operation_attempt=1,
        lane_dispatch=SimpleNamespace(execution_generation=1),
        runtime_unit=SimpleNamespace(location=location, unit_key=UNIT),
    )


def reused_ref() -> ReusedResultRef:
    return ReusedResultRef(
        fork_request_id="fork-request-1",
        source_run_id=SOURCE,
        source_unit_key="bl-unit-v1:" + "a" * 64,
        source_settlement_id="settlement-1",
        source_result_manifest_ref="result-manifest:1",
        source_result_manifest_digest="sha256:" + "c" * 64,
    )


async def stack(*, accept_source: bool = True) -> SimpleNamespace:
    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    h.locator.missions[SOURCE] = MISSION
    h.locator.missions[DERIVED] = MISSION
    fulfillment = OutputFulfillmentService(contracts, submissions, clock=h.clock)
    scope = toolset.access(h.live()).scope
    host = host_access(scope)
    for run in (SOURCE, DERIVED):
        registered = await fulfillment.register_promises(host, run, promise_set())
        assert isinstance(registered, tuple)
    source_live = await toolset.begin(
        LiveInvocation(
            request_scope=scope,
            run_id=SOURCE,
            operation_id="stage/collect_a/source",
            operation_attempt=1,
            execution_generation=1,
            lane="deep_agents",
            position="collect_a",
        )
    )
    ack = await submissions.submit_output(
        toolset.access(source_live),
        SubmitOutput(
            submission_key="call-1", obligation_key="collect_a.notes_a", items=(text("note", NOTE),)
        ),
        position="collect_a",
    )
    assert ack.status == "accepted", ack
    (source_revision,) = ack.revisions
    if accept_source:
        promoted = await fulfillment.promote_output(
            host,
            PromoteOutput(run_id=SOURCE, revision_id=source_revision.revision_id, generation=1),
        )
        assert promoted.status == "promoted"
    carry = ForkOutputCarry(
        invocations=toolset,
        finalization=submissions,
        adoption=OutputAdoptionService(
            outputs=contracts, submissions=submissions, lineage=toolset.lineage
        ),
        fulfillment=fulfillment,
        outputs=contracts,
        live_factory=LiveInvocation,
    )
    return SimpleNamespace(
        scope=scope,
        contracts=contracts,
        toolset=toolset,
        carry=carry,
        source_revision=source_revision,
    )


async def test_reused_unit_carries_the_source_accepted_revision_into_the_derived_run() -> None:
    s = await stack()
    carried = await s.carry.carry(binding(s.scope), reused_ref())

    (ref,) = carried.revisions
    (accepted,) = await s.contracts.accepted_outputs(s.scope, DERIVED)
    assert ref == f"output:{accepted.revision_id}@{accepted.content_digest}"
    source = await s.contracts.output_revision(s.scope, s.source_revision.revision_id)
    assert source is not None
    # Same bytes, same deliverable, now an accepted head of the derived run.
    assert accepted.run_id == DERIVED and accepted.obligation_key == "collect_a.notes_a"
    assert accepted.content_digest == source.content_digest
    assert accepted.candidate["text"] == NOTE and accepted.deliverable_id == "note"
    # Not re-judged: no assessment exists for the carried revision.
    assert not await s.contracts.output_assessments(s.scope, DERIVED)
    # The consumer-facing read of the reused unit's finalized submission sees it.
    finalized = await s.contracts.submitted_outputs(
        s.scope,
        DERIVED,
        "collect_a.notes_a",
        operation_ref="stage/collect_a/derived",
        operation_attempt=1,
        execution_generation=1,
    )
    assert [item.revision_id for item in finalized] == [accepted.revision_id]
    # The adoption is a lineage fact on the source naming the fork, never a producer fact.
    facts = await s.toolset.lineage.facts(
        s.scope, f"output:{source.revision_id}@{source.content_digest}"
    )
    assert [(fact.role.value, fact.fact["adoption"]) for fact in facts] == [
        ("adopter", "fork_reuse:fork-request-1")
    ]
    # The carried revision's producer is the derived unit's host invocation (lane fork_reuse).
    assert accepted.producer_origin_ref != source.producer_origin_ref
    assert FORK_REUSE_LANE == "fork_reuse"
    # The source run is unchanged.
    (source_head,) = await s.contracts.accepted_outputs(s.scope, SOURCE)
    assert source_head.revision_id == source.revision_id

    # An Activity retry records nothing new.
    again = await s.carry.carry(binding(s.scope), reused_ref())
    assert again.revisions == carried.revisions
    assert len(await s.contracts.accepted_outputs(s.scope, DERIVED)) == 1


async def test_a_source_without_an_accepted_head_carries_nothing() -> None:
    s = await stack(accept_source=False)
    carried = await s.carry.carry(binding(s.scope), reused_ref())
    assert carried.revisions == ()
    assert not await s.contracts.accepted_outputs(s.scope, DERIVED)


async def test_a_goal_directed_or_unitless_binding_carries_nothing() -> None:
    s = await stack()
    unitless = binding(s.scope)
    unitless.runtime_unit = None
    assert (await s.carry.carry(unitless, reused_ref())).revisions == ()


async def test_a_refused_adoption_is_terminal_and_typed() -> None:
    s = await stack()

    class Refusing:
        async def adopt(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(adopted=False, code="adoption_source_not_accepted", detail="x")

    s.carry._adoption = Refusing()
    with pytest.raises(ForkOutputsNotCarried) as raised:
        await s.carry.carry(binding(s.scope), reused_ref())
    assert raised.value.code == "fork_outputs_not_carried"
    assert raised.value.message.startswith("adoption_source_not_accepted")
