"""Held subjects are exact inspection inputs, never accepted dependency outputs."""

import pytest

from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
    ProducedOutputResolver,
    ResolutionContext,
    SourceRefused,
)
from mission_control.domain.context import transfer_builders
from mission_control.domain.context.transfer import Boundary, ProducerAttempt
from tests.unit.context.test_transfer_materializer import (
    REPORT_INPUT,
    FakeBackend,
    _trusted,
    dependent,
    seam,
)
from tests.unit.orchestration.test_stage_named_outputs import setup
from tests.unit.outputs.scenario import text

ATTEMPT = ProducerAttempt(
    operation_ref="goal:1:executor", operation_attempt=2, execution_generation=3
)


def selection(*, repair=False):
    item = REPORT_INPUT.model_copy(update={"purpose": "evaluation_subject"})
    base = dependent(
        item,
        boundary=Boundary.NEXT_ITERATION if repair else Boundary.EVALUATOR,
        isolation="shared" if repair else "independent_evaluator",
    )
    return transfer_builders.authorized_subjects(base, ATTEMPT, repair=repair)


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("verdict", ["review", "fail"])
async def test_held_subject_bytes_findings_and_replay_are_exact(monkeypatch, repair, verdict):
    s = seam()
    s.accept_report()
    head = s.outputs.accepted.pop()
    s.outputs.assessments.append(_trusted(head, verdict, 1, None))
    calls = []

    async def subjects(scope, run_id, obligation_key, **coordinates):
        calls.append(coordinates)
        return (head,)

    monkeypatch.setattr(s.outputs, "finalized_subject_outputs", subjects, raising=False)
    request = s.request(selection(repair=repair))
    result = await s.materializer.materialize(request, FakeBackend())
    assert calls == [ATTEMPT.model_dump()]
    assert s.package.body in dict(result.files).values()
    assert {m.admission for m in result.plan.exact_sources} == {"subject"}
    assert {m.source_ref for m in result.plan.exact_sources} == {head.revision_id}
    findings = [content for _, content in result.files if b"mc.subject-findings.v1" in content]
    findings += [(result.prompt_section or "").encode()]
    findings = [content for content in findings if b"mc.subject-findings.v1" in content]
    assert findings and b'"official_use":false' in findings[0]
    assert verdict.encode() in findings[0]
    assert not s.outputs.accepted
    s.outputs.assessments.clear()
    again = await s.materializer.materialize(request, FakeBackend())
    assert again.plan == result.plan and len(calls) == 1
    with pytest.raises(ContextDeliveryBlocked):
        await s.materializer.materialize(s.request(dependent(REPORT_INPUT)), FakeBackend())


async def test_purpose_string_cannot_authorize_subject(monkeypatch):
    s = seam()
    s.accept_report()
    binding = selection().inputs[0]
    resolver = ProducedOutputResolver(s.outputs)
    with pytest.raises(SourceRefused) as refused:
        await resolver.resolve(binding, ResolutionContext("scope", "run", "receiver"))
    assert refused.value.refusal.code == "SUBJECT_NOT_AUTHORIZED"


@pytest.mark.parametrize("wrong", ["missing", "revision", "run"])
async def test_exact_subject_cannot_fall_back_to_accepted_head(monkeypatch, wrong):
    s = seam()
    s.accept_report()
    head = s.outputs.accepted[0]

    async def subjects(*args, **kwargs):
        if wrong == "missing":
            return ()
        return (
            head.model_copy(
                update={"obligation_revision": 2}
                if wrong == "revision"
                else {"run_id": "sibling-run"}
            ),
        )

    monkeypatch.setattr(s.outputs, "finalized_subject_outputs", subjects, raising=False)
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await s.materializer.materialize(s.request(selection()), FakeBackend())
    assert refused.value.refusals[0].code == "SOURCE_NOT_FINALIZED"


@pytest.mark.parametrize("failed", [False, True])
async def test_subject_store_requires_exact_successful_finalization(failed):
    stack, _, current = await setup()
    await stack.submit("submit", "draft.summary", text("note", "actual subject"))
    kwargs = {
        "operation_ref": current.operation_id,
        "operation_attempt": 1,
        "execution_generation": 1,
    }
    read = stack.store.finalized_subject_outputs
    assert not await read(stack.access.scope, stack.run_id, "draft.summary", **kwargs)
    await stack.submissions.finalize(
        stack.access.identity(("draft.summary",)), attempt_failed=failed
    )
    assert (
        bool(await read(stack.access.scope, stack.run_id, "draft.summary", **kwargs)) is not failed
    )
    for key in ("operation_attempt", "execution_generation"):
        assert not await read(
            stack.access.scope, stack.run_id, "draft.summary", **(kwargs | {key: 2})
        )
    assert not await read("sibling-scope", stack.run_id, "draft.summary", **kwargs)


@pytest.mark.parametrize("verdict", ["review", "fail"])
async def test_subject_query_keeps_negative_assessment_without_loosening_submission(verdict):
    stack, _, current = await setup()
    await stack.submit("held", "draft.summary", text("note", "held exact bytes"))
    await stack.submissions.finalize(stack.access.identity(("draft.summary",)))
    coordinates = {
        "operation_ref": current.operation_id,
        "operation_attempt": 1,
        "execution_generation": 1,
    }
    subjects = await stack.store.finalized_subject_outputs(
        stack.access.scope, stack.run_id, "draft.summary", **coordinates
    )
    head = subjects[0]
    stack.store.recorded_assessments.append(
        (stack.access.scope, stack.run_id, _trusted(head, verdict, 1, None))
    )
    assert (
        await stack.store.finalized_subject_outputs(
            stack.access.scope, stack.run_id, "draft.summary", **coordinates
        )
        == subjects
    )
    assert not await stack.store.submitted_outputs(
        stack.access.scope, stack.run_id, "draft.summary", **coordinates
    )
    assert not await stack.store.accepted_outputs(stack.access.scope, stack.run_id)


@pytest.mark.parametrize("boundary", [Boundary.DEPENDENT_STAGE, Boundary.FIRST_INVOCATION])
def test_builder_refuses_ordinary_boundary(boundary):
    with pytest.raises(ValueError):
        transfer_builders.authorized_subjects(dependent(REPORT_INPUT, boundary=boundary), ATTEMPT)
