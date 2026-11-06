"""WI-07 / OVE-170: the verifier and a later executor receive the whole current set.

The one transfer materializer over the in-memory output store (1.7.0 rules): the produced-output
binding keeps every accepted head of the goal and adds the exact producing operation's newer
finalized revision in its deliverable's place; held and rejected revisions are never admitted;
the goal-wide current-set index is a required sealed **file** (``/inputs/current-set/...``), never
inline, and a redelivery of the same receiver reads the same index bytes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from mission_control.application.context.materialization import (
    ApplicationSelectorResolver,
    ContextDeliveryBlocked,
    LiteralResolver,
    MaterializeRequest,
    ProducedOutputResolver,
    TransferMaterializer,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.current_set import CurrentSetIndexResolver
from mission_control.domain.context import transfer_builders as builders
from mission_control.domain.context.transfer import (
    BackendCapabilities,
    HostOverhead,
    ReceiverAttempt,
    ReceiverRef,
    ResourceBounds,
)
from mission_control.domain.outputs.contracts import Cardinality, OutputForm, Requirement
from mission_control.domain.outputs.current_set import (
    CURRENT_SET_BINDING,
    CURRENT_SET_FILE,
    with_current_set_index,
)
from tests.fixtures.knowledge_binding import InMemoryStaging, InMemoryTransferPlanStore
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import (
    TRUSTED_VALIDATORS,
    Stack,
    build_stack,
    obligation,
    text,
)

pytestmark = pytest.mark.asyncio
AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
RUN = "22222222-2222-4222-8222-222222222222"
SANDBOX = BackendCapabilities(custody_backend="mc-custody", file_capable=True, binary_capable=True)
OVERHEAD = HostOverhead(host_state_tokens=800, tool_schema_tokens=400, skill_tokens=100)
ASSESSED = Requirement(key="assessed", validator="knowledge.report.assess@1")


def invocation(operation: str, attempt: int = 1) -> InvocationAccess:
    return InvocationAccess(
        origin=origin(attempt, operation_id=operation),
        subject="mission-control-runtime",
        invocation_id="inv-" + operation.replace("/", "-") + f"-{attempt}",
        authenticated_at=AT,
    )


def executor(iteration: int) -> str:
    return f"goal-iteration/{iteration}/executor"


class Backend:
    realized_backend = "fake:sandbox"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def write(self, files) -> None:  # type: ignore[no-untyped-def]
        self.files.update(files)

    async def read(self, path: str) -> bytes | None:
        return self.files.get(path)


def bounds() -> ResourceBounds:
    return ResourceBounds(
        window_tokens=64_000,
        generation_reserve_tokens=4_000,
        tool_result_reserve_tokens=2_000,
        inline_bytes_ceiling=16_000,
        file_bytes_ceiling=512_000,
        file_count_ceiling=16,
    )


async def goal_stack() -> Stack:
    store = InMemoryOutputContractStore()
    reports = obligation(
        "goal.reports",
        OutputForm.TEXT,
        position="goal",
        cardinality=Cardinality(min=3, max=3),
        requirements=(ASSESSED,),
    )
    return await build_stack(store, store.submissions, invocation(executor(1)), reports)


def materializer(stack: Stack, store: InMemoryTransferPlanStore) -> TransferMaterializer:
    staging = InMemoryStaging()
    return TransferMaterializer(
        store=store,
        staging=staging,
        custody=staging,
        resolvers={
            "produced_output": ProducedOutputResolver(stack.store),
            "typed_literal": LiteralResolver(),
            "application_selector": ApplicationSelectorResolver(
                {
                    CURRENT_SET_BINDING: CurrentSetIndexResolver(
                        stack.store, clock=lambda: AT, trusted_validators=TRUSTED_VALIDATORS
                    )
                }
            ),
        },
        clock=lambda: AT,
    )


def verifier_selection(iteration: int):  # type: ignore[no-untyped-def]
    base = builders.first_invocation("goal", bounds(), SANDBOX)
    judge = builders.evaluator(base, [("goal", "goal.reports")])
    return with_current_set_index(
        builders.for_producer(judge, executor(iteration)), purpose="evaluation_subject"
    )


def request(stack: Stack, selection, operation: str, attempt: int = 1) -> MaterializeRequest:  # type: ignore[no-untyped-def]
    access = invocation(operation, attempt)
    return MaterializeRequest(
        receiver=ReceiverRef(scope=stack.host.scope, run_id=RUN, operation_id=operation),
        attempt=ReceiverAttempt(
            operation_attempt=attempt, execution_generation=1, invocation_ref=f"inv-{attempt}"
        ),
        selection=selection,
        configuration_ref="erc:sha256:" + "0" * 64,
        host_state_ref="context-packet:p1@sha256:" + "1" * 64,
        overhead=OVERHEAD,
        access=access,
    )


async def iteration(stack: Stack, number: int, *items: tuple[str, str]) -> list[str]:
    """One executor iteration submits its reports and finalizes; returns revision ids."""

    access = invocation(executor(number))
    worker = await stack.start(access)
    ids: list[str] = []
    for deliverable, body in items:
        ack = await worker.submit(
            f"{number}-{deliverable}", "goal.reports", text(deliverable, body), position="goal"
        )
        assert ack.status == "accepted", ack.error
        ids.append(ack.revisions[0].revision_id)
    await stack.submissions.finalize(access.identity(("goal.reports",)))
    return ids


async def judge(stack: Stack, revision_id: str, verdict: str) -> None:
    revision = await stack.store.output_revision(stack.host.scope, revision_id)
    assert revision is not None
    receipt = await stack.judge(revision_id, revision.content_digest, assessed=verdict)
    assert receipt.status == "recorded", receipt.error


async def promote(stack: Stack, revision_id: str) -> None:
    from mission_control.application.outputs.fulfillment import PromoteOutput

    revision = await stack.store.output_revision(stack.host.scope, revision_id)
    assert revision is not None
    head = await stack.store.accepted_head(
        stack.host.scope, RUN, revision.obligation_key, revision.deliverable_id
    )
    result = await stack.outputs.promote_output(
        stack.host,
        PromoteOutput(
            run_id=RUN,
            revision_id=revision_id,
            expected_head=None if head is None else head.revision_id,
            generation=1,
        ),
    )
    assert result.status == "promoted", result.error


async def test_the_verifier_reads_every_accepted_head_plus_this_iterations_subject() -> None:
    stack = await goal_stack()
    (a1,) = await iteration(stack, 1, ("report-a", "A"))
    await judge(stack, a1, "pass")
    await promote(stack, a1)
    (b2,) = await iteration(stack, 2, ("report-b", "B"))
    await judge(stack, b2, "pass")
    await promote(stack, b2)
    c3, a3 = await iteration(stack, 3, ("report-c", "C"), ("report-a", "A revised"))
    host = materializer(stack, InMemoryTransferPlanStore())
    backend = Backend()
    result = await host.materialize(
        request(stack, verifier_selection(3), "goal-iteration/3/verifier"), backend
    )
    produced = {
        member.source_ref: member.admission
        for member in result.plan.exact_sources
        if member.source_kind == "produced_output"
    }
    # Earlier successes retained (b2), this iteration's subjects admitted as submitted (c3, and
    # a3 in place of the older accepted a1).
    assert produced == {b2: "accepted", c3: "submitted", a3: "submitted"}
    (index_member,) = (m for m in result.plan.exact_sources if m.binding == "current-set")
    placements = {member.member_key: placed.placement for placed, member in _placed(result.plan)}
    assert placements[index_member.member_key] == "file"
    path = next(p for p in backend.files if p.endswith("/" + CURRENT_SET_FILE))
    index = json.loads(backend.files[path])
    assert index["schema_version"] == "mc.current_set_index.v1"
    (promise,) = index["promises"]
    assert [h["deliverable_id"] for h in promise["heads"]] == ["report-a", "report-b"]
    assert [c["deliverable_id"] for c in promise["candidates"]] == ["report-a", "report-c"]
    assert promise["distinct_count"] == 2 and promise["gaps"]
    # The prompt names the file and its digest; the index content itself is never inline.
    assert path in (result.prompt_section or "")
    assert '"promises"' not in (result.prompt_section or "")
    # Redelivery reads the sealed index bytes, even after the set moved on.
    await judge(stack, c3, "pass")
    await promote(stack, c3)
    again = await host.materialize(
        request(stack, verifier_selection(3), "goal-iteration/3/verifier", attempt=2), Backend()
    )
    assert again.plan.plan_id == result.plan.plan_id
    assert {m.digest for m in again.plan.exact_sources} == {
        m.digest for m in result.plan.exact_sources
    }


async def test_held_and_rejected_revisions_are_labelled_not_admitted() -> None:
    stack = await goal_stack()
    (a1,) = await iteration(stack, 1, ("report-a", "A"))
    await judge(stack, a1, "pass")
    await promote(stack, a1)
    held, rejected = await iteration(stack, 2, ("report-b", "B"), ("report-c", "C"))
    await judge(stack, held, "review")
    await judge(stack, rejected, "fail")
    backend = Backend()
    result = await materializer(stack, InMemoryTransferPlanStore()).materialize(
        request(stack, verifier_selection(2), "goal-iteration/2/verifier"), backend
    )
    produced = {
        m.source_ref for m in result.plan.exact_sources if m.source_kind == "produced_output"
    }
    assert produced == {a1}
    index = json.loads(next(v for p, v in backend.files.items() if p.endswith(CURRENT_SET_FILE)))
    labels = {c["deliverable_id"]: c["label"] for c in index["promises"][0]["candidates"]}
    assert labels == {"report-b": "held", "report-c": "rejected"}


async def test_a_run_without_promises_refuses_the_index_instead_of_an_empty_file() -> None:
    store = InMemoryOutputContractStore()
    stack = await goal_stack()
    bare = Stack(store, stack.submissions, stack.outputs, stack.access, stack.host, stack.assessor)
    selection = verifier_selection(1)
    with pytest.raises(ContextDeliveryBlocked):
        await materializer(bare, InMemoryTransferPlanStore()).materialize(
            request(bare, selection, "goal-iteration/1/verifier"), Backend()
        )


def _placed(plan):  # type: ignore[no-untyped-def]
    for placement in ("inline", "file", "handle"):
        yield from plan.placed(placement)


def test_the_production_materializer_registers_the_current_set_selector() -> None:
    from mission_control.adapters.temporal.deployment_composition import (
        compose_transfer_materializer,
    )

    composed = compose_transfer_materializer(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        trusted_validators=TRUSTED_VALIDATORS,
    )
    selectors = composed._resolvers["application_selector"]._selectors
    assert set(selectors) == {CURRENT_SET_BINDING}
    assert isinstance(selectors[CURRENT_SET_BINDING], CurrentSetIndexResolver)


@pytest.mark.parametrize(
    ("aggregate", "delivered"), [({}, False), ({"aggregate": "at_least", "minimum": 1}, True)]
)
async def test_a_collection_blocked_by_held_or_rejected_members_is_not_a_delivered_subject(
    aggregate: dict[str, object], delivered: bool
) -> None:
    """Review S1: under `all`, a rejected member keeps the manifest out of the verifier's subjects
    (the index labels it); an authored `at_least 1` rule tolerates it, so it is delivered."""

    from tests.unit.outputs.test_collections import VERIFIED, collection, report

    store = InMemoryOutputContractStore()
    promise = obligation(
        "goal.reports",
        OutputForm.COLLECTION,
        position="goal",
        requirements=(VERIFIED.model_copy(update={"parameters": aggregate}),),
    )
    stack = await build_stack(store, store.submissions, invocation(executor(1)), promise)
    access = invocation(executor(1))
    worker = await stack.start(access)
    a, b = report("a"), report("b")
    ack = await worker.submit(
        "c1",
        "goal.reports",
        collection(members=(a, b)).model_copy(update={"deliverable_id": "reports"}),
        position="goal",
    )
    assert ack.status == "accepted", ack.error
    await stack.submissions.finalize(access.identity(("goal.reports",)))
    manifest = ack.revisions[0].revision_id
    await stack.judge(a.ref, a.digest, kind="member", index_revision_id=manifest, verified="pass")
    await stack.judge(b.ref, b.digest, kind="member", index_revision_id=manifest, verified="fail")
    base = builders.first_invocation("goal", bounds(), SANDBOX)
    judge = builders.evaluator(base, [("goal", "goal.reports")])
    selection = with_current_set_index(
        builders.for_producer(judge, executor(1)), purpose="evaluation_subject"
    )
    host = materializer(stack, InMemoryTransferPlanStore())
    if not delivered:
        with pytest.raises(ContextDeliveryBlocked, match="SOURCE_NOT_ACCEPTED"):
            await host.materialize(
                request(stack, selection, "goal-iteration/1/verifier"), Backend()
            )
        return
    result = await host.materialize(
        request(stack, selection, "goal-iteration/1/verifier"), Backend()
    )
    assert manifest in {m.source_ref for m in result.plan.exact_sources}


def test_the_trusted_pin_comes_from_the_application_profile_and_never_defaults() -> None:
    """Review N1: the pin is the Application Profile's `assessment_pin`; an unresolvable
    application yields None, which every consumer treats as fail closed."""

    from pathlib import Path

    from mission_control.bootstrap.application_profiles import trusted_assessment_validators

    root = Path(__file__).resolve().parents[3] / "deployments"
    for application in ("ai-engineer", "biotech"):
        assert trusted_assessment_validators(root, application) == frozenset(
            {"knowledge.report.assess@1"}
        )
    assert trusted_assessment_validators(root, None) is None
    assert trusted_assessment_validators(root, "no-such-application") is None
