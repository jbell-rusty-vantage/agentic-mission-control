"""Linked adoption checks authority/current use before the existing target submission act."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mission_control.application.context.materialization import ResolutionContext, SourceRefused
from mission_control.application.outputs.adoption import OutputAdoptionService
from mission_control.application.outputs.linked_adoption import LinkedOutputAdoptionService
from tests.unit.context.test_linked_transfer import RUN, setup
from tests.unit.context.test_transfer_materializer import _trusted
from tests.unit.orchestration.test_wi13_round2 import Lineage, Submissions


def preparation(monkeypatch, *, repair=False, refuse=False):
    h = setup(monkeypatch, repair=repair)
    h.revision = h.revision.model_copy(
        update={
            "candidate": {
                **h.revision.candidate,
                "deliverable_id": h.revision.deliverable_id,
                "form": h.revision.form,
                "digest": h.revision.content_digest,
            }
        }
    )
    h.rows[h.revision.revision_id] = h.revision
    h.s.outputs.accepted = [h.revision]
    submissions, lineage = Submissions(refuse=refuse), Lineage()
    service = LinkedOutputAdoptionService(
        h.resolver,
        OutputAdoptionService(outputs=h.s.outputs, submissions=submissions, lineage=lineage),
    )
    context = ResolutionContext(
        scope=h.export.request_scope,
        run_id=RUN,
        receiver_position="review",
        access=h.s.access(),
        boundary=h.selection.boundary,
        receiver_operation_id="op-review-1",
    )
    return h, service, context, submissions, lineage


async def invoke(h, service, context):
    return await service.adopt(
        h.selection.inputs[-1],
        context,
        target_obligation="review.adopted_report",
        at=datetime.now(UTC),
    )


async def test_exact_authorized_adoption_creates_submission_and_adopter_only(monkeypatch):
    h, service, context, submissions, lineage = preparation(monkeypatch)
    result = await invoke(h, service, context)
    assert result.adopted
    assert len(h.checks) == 1
    request, position = submissions.calls[0]
    assert position == "review"
    assert request.obligation_key == "review.adopted_report"
    assert request.items[0].digest == h.revision.content_digest
    assert request.derivation_refs == (
        f"output:{h.revision.revision_id}@{h.revision.content_digest}",
    )
    assert [row.fact.role.value for row in lineage.entries] == ["adopter"]
    assert h.s.outputs.accepted == [h.revision]  # no target promotion occurs here


@pytest.mark.parametrize("mismatch", ["run", "operation", "digest"])
async def test_wrong_receiver_or_frozen_export_refuses_before_submission(monkeypatch, mismatch):
    h, service, context, submissions, lineage = preparation(monkeypatch)
    if mismatch == "run":
        context = replace(context, run_id="sibling")
    elif mismatch == "operation":
        context = replace(context, receiver_operation_id="sibling-operation")
    else:
        h.exports.export = h.export.model_copy(update={"caller_ref": "tampered"})
    with pytest.raises(SourceRefused):
        await invoke(h, service, context)
    assert not submissions.calls and not lineage.entries


async def test_current_use_demoted_source_cannot_be_adopted(monkeypatch):
    h, service, context, submissions, lineage = preparation(monkeypatch)
    h.s.outputs.assessments.append(_trusted(h.revision, "review", 1, None))
    with pytest.raises(SourceRefused):
        await invoke(h, service, context)
    assert h.checks and not submissions.calls and not lineage.entries


async def test_held_repair_is_not_an_adoption_authority(monkeypatch):
    h, service, context, submissions, lineage = preparation(monkeypatch, repair=True)
    result = await invoke(h, service, context)
    assert not result.adopted and result.code == "linked_adoption_requires_accepted_use"
    assert not submissions.calls and not lineage.entries


async def test_target_ownership_refusal_remains_submission_authority(monkeypatch):
    h, service, context, submissions, lineage = preparation(monkeypatch, refuse=True)
    result = await invoke(h, service, context)
    assert not result.adopted and "adoption_refused" in result.code
    assert len(submissions.calls) == 1 and not lineage.entries
