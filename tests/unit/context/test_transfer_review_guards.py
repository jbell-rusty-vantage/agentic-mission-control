"""WI-02 review guards: evaluator isolation is enforced, the submitted fallback is marked and
restricted, and every launch route registers or refuses the run's named promises."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mission_control.application.context.materialization import ContextDeliveryBlocked
from mission_control.application.execution.run_launch import RunLaunchRejected, RunLaunchService
from mission_control.application.knowledge.toolset import ReadScope
from mission_control.domain.context import transfer_builders as builders
from mission_control.domain.context.transfer import Boundary, TransferInput
from mission_control.domain.outputs.contracts import (
    ExactOutput,
    OutputContract,
    OutputForm,
    OutputObligation,
)
from tests.unit.context.test_transfer_materializer import (
    REPORT_INPUT,
    RUN,
    FakeBackend,
    dependent,
    seam,
)
from tests.unit.knowledge.test_knowledge_tools import lane

# ---------------------------------------------------------------- B1 evaluator isolation


async def test_an_evaluator_with_no_subject_refuses_visibly() -> None:
    s = seam()
    s.outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    judge = builders.evaluator(
        builders.first_invocation("review", dependent().bounds, dependent().backend),
        [("draft", "draft.report")],
    )
    assert all(item.required for item in judge.inputs)
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await s.materializer.materialize(s.request(judge), FakeBackend())
    assert refused.value.refusals[0].code == "SOURCE_NOT_ACCEPTED"


async def test_omissions_are_rendered_even_with_nothing_placed() -> None:
    s = seam()
    s.outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    optional = REPORT_INPUT.model_copy(update={"required": False})
    result = await s.materializer.materialize(s.request(dependent(optional)), FakeBackend())
    assert result.plan.placements == ()
    assert result.prompt_section is not None
    assert "omitted `draft`: SOURCE_NOT_ACCEPTED" in result.prompt_section


async def test_an_isolated_receiver_cannot_read_an_unplanned_report() -> None:
    h = lane()
    planned = "kh:aiengineer-postgres/report/report-7@research-report.v2"
    digest = "sha256:" + "7" * 64
    live = h.live()
    scoped = live.__class__(
        **{
            **live.__dict__,
            "read_scope": ReadScope(
                purpose="evaluation_subject", isolated=True, reports={planned: digest}
            ),
        }
    )
    other = "kh:aiengineer-postgres/report/sibling-3@research-report.v2"
    refused = await h.toolset.dispatch(
        "knowledge_read", {"handle": other, "digest": digest}, scoped, tool_call_id="r-1"
    )
    assert not refused["ok"] and refused["refusal"]["code"] == "SCOPE_DENIED"
    assert not [c for c in h.fake.calls_of("invoke") if c.envelope is not None]
    await h.toolset.dispatch(
        "knowledge_read", {"handle": planned, "digest": digest}, scoped, tool_call_id="r-2"
    )
    (read,) = [c for c in h.fake.calls_of("invoke") if c.envelope is not None]
    assert read.envelope.input.inlinePayload["purpose"] == "evaluation_subject"  # type: ignore[union-attr,index]


async def test_the_read_tool_selects_exact_members() -> None:
    h = lane()
    report = "kh:aiengineer-postgres/report/report-7@research-report.v2"
    member = {
        "kind": "assertion",
        "id": "a-1",
        "version": "research-core.assertion.v2",
        "digest": "sha256:" + "8" * 64,
    }
    await h.toolset.dispatch(
        "knowledge_read",
        {"handle": report, "digest": "sha256:" + "7" * 64, "members": [member]},
        h.live(),
        tool_call_id="m-1",
    )
    (read,) = [c for c in h.fake.calls_of("invoke") if c.envelope is not None]
    selection = read.envelope.input.inlinePayload["selection"]  # type: ignore[union-attr,index]
    assert selection["mode"] == "members"
    assert [a["id"] for a in selection["assertions"]] == ["a-1"] and selection["evidence"] == []


# ---------------------------------------------------------------- B2 submitted fallback


def test_a_dependent_stage_never_takes_the_submitted_fallback() -> None:
    base = builders.first_invocation("review", dependent().bounds, dependent().backend)
    stage = builders.dependent_stage(base, [("draft", "draft", "draft.report")])
    assert stage.inputs[0].accepted_statuses == ("accepted",)
    with pytest.raises(ValidationError, match="accepted revisions only"):
        dependent(
            TransferInput(
                name="draft",
                source=REPORT_INPUT.source,
                purpose="dependent_input",
                accepted_statuses=("accepted", "submitted"),
            ),
            boundary=Boundary.DEPENDENT_STAGE,
        )


async def test_a_submitted_fallback_member_is_marked_in_plan_index_and_prompt() -> None:
    s = seam()
    s.outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    s.outputs.submitted.append(
        ExactOutput(
            revision_id="rev-report-1",
            run_id=RUN,
            obligation_key="draft.report",
            obligation_revision=1,
            deliverable_id="report",
            revision=1,
            form=OutputForm.REFERENCE,
            content_digest=s.package.report.digest,
            candidate={"kind": "handle", "ref": s.handle()},
            producer_origin_ref="mc-inv:draft",
        )
    )
    later = builders.next_iteration(
        builders.first_invocation("review", dependent().bounds, dependent().backend),
        [("draft", "draft.report")],
    )
    # R3: without the exact producing operation there is no fallback at all.
    fresh = seam()
    fresh.outputs.obligations.extend(s.outputs.obligations)
    fresh.outputs.submitted.extend(s.outputs.submitted)
    unbound = await fresh.materializer.materialize(fresh.request(later), FakeBackend())
    assert unbound.plan.exact_sources == () and fresh.outputs.producer_operations == []
    later = builders.for_producer(later, "goal-iteration/1/executor")
    result = await s.materializer.materialize(s.request(later), FakeBackend())
    assert s.outputs.producer_operations == ["goal-iteration/1/executor"]
    assert {m.admission for m in result.plan.exact_sources} == {"submitted"}
    assert {item["admission"] for item in result.index["inputs"]} == {"submitted"}
    assert "submitted" in (result.prompt_section or "")


# ---------------------------------------------------------------- B3 launch routes


async def test_a_launch_route_without_a_registrar_refuses_a_promising_run() -> None:
    service = RunLaunchService(run_control=SimpleNamespace(), submitter=SimpleNamespace())  # type: ignore[arg-type]
    promised = SimpleNamespace(
        blueprint={"output_promises": {"obligations": []}},
        effective_configuration_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(RunLaunchRejected) as refused:
        await service.register_promises("s", "run-1", promised)
    assert refused.value.code == "promises_unwired"
    silent = SimpleNamespace(blueprint={}, effective_configuration_digest="sha256:" + "0" * 64)
    await service.register_promises("s", "run-1", silent)  # promises nothing: launches


async def test_the_lane_binds_knowledge_read_to_an_evaluator_plan() -> None:
    from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION

    s = seam()
    s.accept_report()
    judge = builders.evaluator(
        builders.first_invocation("review", dependent().bounds, dependent().backend),
        [("draft", "draft.report")],
    )
    result = await s.materializer.materialize(s.request(judge), FakeBackend())
    h = lane()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        h.support.scope_reads(result.plan)
        scope = CURRENT_INVOCATION.get().read_scope  # type: ignore[union-attr]
    finally:
        CURRENT_INVOCATION.reset(token)
    assert scope is not None and scope.isolated and scope.purpose == "evaluation_subject"
    assert scope.allows(s.handle(), s.package.report.digest)
    assert not scope.allows("kh:aiengineer-postgres/report/sibling@x", s.package.report.digest)


def test_the_verifier_subject_needs_an_executor_that_can_submit() -> None:
    from mission_control.application.authoring.manifest_launch_inputs import (
        _submits_named_outputs,
    )

    def runtime(*items: tuple[str, str]) -> SimpleNamespace:
        return SimpleNamespace(
            agent=SimpleNamespace(
                items=tuple(SimpleNamespace(name=name, pin=pin) for name, pin in items)
            )
        )

    assert not _submits_named_outputs(runtime(("read_file", "tool.fs@1")))  # type: ignore[arg-type]
    assert _submits_named_outputs(  # type: ignore[arg-type]
        runtime(("tool.knowledge-submit-output", "tool.knowledge-submit-output@sha256:x"))
    )


def _isolated_live(h):  # type: ignore[no-untyped-def]
    live = h.live()
    return live.__class__(
        **{
            **live.__dict__,
            "read_scope": ReadScope(purpose="evaluation_subject", isolated=True, reports={}),
        }
    )


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("knowledge_read", {}),
        ("report_derive", {"mapping": {}}),
        ("verify_claims", {"claims": [{"id": "c-1"}]}),
    ],
)
async def test_a_plan_less_evaluator_reaches_no_report_by_any_tool(tool, arguments) -> None:
    """R1/R2: the evaluator role isolates reads with or without a plan, on every handle path."""

    from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION

    h = lane()
    base = builders.first_invocation("goal", dependent().bounds, dependent().backend)
    role = builders.isolated_evaluator(base)
    assert role.isolation == "independent_evaluator" and role.inputs == ()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        h.support.scope_role(role)
        live = CURRENT_INVOCATION.get()
    finally:
        CURRENT_INVOCATION.reset(token)
    assert live is not None and live.read_scope is not None and live.read_scope.isolated
    report = {
        "handle": "kh:aiengineer-postgres/report/anything@research-report.v2",
        "digest": "sha256:" + "5" * 64,
    }
    refused = await h.toolset.dispatch(tool, report | arguments, live, tool_call_id=f"{tool}-1")
    assert not refused["ok"] and refused["refusal"]["code"] == "SCOPE_DENIED"
    assert not [c for c in h.fake.calls_of("invoke") if c.envelope is not None]


def test_the_submit_tool_match_is_the_knowledge_capability_id() -> None:
    from mission_control.adapters.deep_agents.knowledge_tools import knowledge_capability_id

    assert knowledge_capability_id("submit_output") == "tool.knowledge-submit-output"
