"""Independent receiver access to a durable exact cross-run export, including redelivery."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from mission_control.application.context.linked_transfer import (
    LinkedExportAccess,
)
from mission_control.application.context.materialization import ContextDeliveryBlocked
from mission_control.domain.context.transfer import InputSource, LinkedExport
from mission_control.domain.context.transfer_builders import linked_mission
from tests.support.unit.context.linked_transfer import SOURCE, setup
from tests.support.unit.context.transfer_materializer import (
    RUN,
    FakeBackend,
    _trusted,
    dependent,
)


async def test_current_use_unavailable_cannot_redeliver_a_sealed_ready_plan():
    from mission_control.application.knowledge.judgment import EvaluatorUnavailable

    h = setup()
    first = await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    assert first.receipt.result == "ready"
    h.recheck.failure = EvaluatorUnavailable("current service unavailable")
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(h.selection, attempt=2), FakeBackend())
    assert "LINK_CURRENT_USE_UNAVAILABLE" in str(refused.value)
    assert not h.s.outputs.assessments  # no semantic rejection invented by unavailability


async def test_exact_export_delivers_and_redelivers_original_after_newer_source_head():
    h = setup()
    first = await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    assert h.s.package.body in dict(first.files).values()
    assert all(m.linked_source.source_run_id == SOURCE for m in first.plan.exact_sources)
    assert all(m.source_ref == h.revision.revision_id for m in first.plan.exact_sources)
    assert all(m.admission == "accepted" for m in first.plan.exact_sources)
    assert all(receiver == RUN and source == SOURCE for receiver, source, _ in h.checks)
    assert not h.s.outputs.accepted
    # New producer publication or cancellation does not replace already released, still-valid bytes.
    h.s.accept_report(number=2)
    second = await h.s.materializer.materialize(h.s.request(h.selection, attempt=2), FakeBackend())
    assert first.plan == second.plan
    assert h.s.package.body in dict(second.files).values()
    assert {revision for _, revision in h.reads} == {h.revision.revision_id}
    assert all(m.linked_source.export_digest == h.export.digest for m in second.plan.exact_sources)
    assert b'"source_run_id"' in next(
        data for path, data in second.files if path.endswith("transfer.json")
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"receiver_run_id": SOURCE}, "LINK_EXPORT_INVALID"),
        ({"receiver_position": "sibling"}, "LINK_EXPORT_DIGEST"),
        ({"request_scope": "other-scope"}, "LINK_EXPORT_DIGEST"),
        ({"gate_ref": "changed"}, "LINK_EXPORT_DIGEST"),
    ],
)
async def test_export_tampering_or_receiver_mismatch_refuses_before_bytes(change, code):
    h = setup()
    h.exports.export = h.export.model_copy(update=change)
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    assert refused.value.refusals[0].code == code
    assert not h.reads


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": RUN},
        {"content_digest": "sha256:" + "0" * 64},
        {"obligation_key": "sibling.report"},
        {"obligation_revision": 2},
    ],
)
async def test_wrong_exact_source_identity_refuses(change):
    h = setup()
    h.rows[h.revision.revision_id] = h.revision.model_copy(update=change)
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    assert refused.value.refusals[0].code == "LINK_OUTPUT_MISMATCH"


async def test_source_revocation_blocks_sealed_redelivery():
    h = setup()
    await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    h.s.outputs.assessments.append(_trusted(h.revision, "review", 1, None))
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(h.selection, attempt=2), FakeBackend())
    assert any(item.code == "LINK_OUTPUT_REVOKED" for item in refused.value.refusals)


async def test_repair_subject_delivers_held_bytes_and_full_findings_without_adoption():
    h = setup(repair=True)
    h.s.outputs.assessments.append(_trusted(h.revision, "review", 1, None))
    result = await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    assert h.s.package.body in dict(result.files).values()
    findings = [data for _, data in result.files if b"mc.linked-subject-findings.v1" in data]
    assert len(findings) == 1 and b'"official_use":false' in findings[0]
    assert b'"result":"review"' in findings[0]
    assert {item.admission for item in result.plan.exact_sources} == {"subject"}
    assert not h.s.outputs.accepted
    assert not h.checks  # held inspection is not an ordinary accepted-use recheck
    assert not any(entry.fact.role.value == "adopter" for _, entry in h.s.lineage.entries)


async def test_unreleased_export_and_foreign_receiver_access_refuse():
    h = setup()
    h.exports.export = None
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    assert refused.value.refusals[0].code == "LINK_EXPORT_UNRELEASED"
    h.exports.export = h.export
    request = h.s.request(h.selection)
    wrong = replace(
        request.access, origin=request.access.origin.model_copy(update={"run_id": SOURCE})
    )
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(replace(request, access=wrong), FakeBackend())
    assert refused.value.refusals[0].code == "LINK_RECEIVER_AUTHORITY"
    sibling = replace(
        request.access,
        origin=request.access.origin.model_copy(update={"operation_id": "op-sibling"}),
    )
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(replace(request, access=sibling), FakeBackend())
    assert refused.value.refusals[0].code == "LINK_RECEIVER_AUTHORITY"


def test_export_contract_and_additive_source_identity_are_closed():
    h = setup()
    with pytest.raises(ValidationError):
        InputSource.model_validate(
            {
                "kind": "linked_export",
                "export_id": "x",
                "digest": h.export.digest,
                "position": SOURCE,
            }
        )
    assert "export_id" not in InputSource.produced("draft", "draft.report").model_dump()
    with pytest.raises(ValidationError, match="acceptance gate"):
        LinkedExport.model_validate(h.export.model_dump() | {"admission": "subject"})
    with pytest.raises(ValidationError, match="unique"):
        linked_mission(dependent(), (h.export, h.export))


async def test_pinned_export_for_other_receiver_refuses_even_with_correct_digest():
    h = setup()
    foreign = h.export.model_copy(update={"receiver_run_id": "other-consumer"})
    h.exports.export = foreign
    selection = linked_mission(dependent(), (foreign,))
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(selection), FakeBackend())
    assert refused.value.refusals[0].code == "LINK_RECEIVER_MISMATCH"


async def test_source_owner_and_current_receiver_access_are_checked():
    from mission_control.application.context.materialization import AccessCheck

    h = setup()
    h.s.outputs.obligations[0] = h.s.outputs.obligations[0].model_copy(
        update={"owner_position": "sibling"}
    )
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())
    assert refused.value.refusals[0].code == "LINK_OUTPUT_OWNER"
    h.s.outputs.obligations[0] = h.s.outputs.obligations[0].model_copy(
        update={"owner_position": "draft"}
    )
    await h.s.materializer.materialize(h.s.request(h.selection), FakeBackend())

    class Revoked:
        async def check(self, member, context):
            assert context.access.origin.run_id == RUN
            return AccessCheck(ok=False, ref=member.access_ref, code="RECEIVER_ACCESS_REVOKED")

    # TODO(OVE-238): the shared seam() composes the materializer's access ports; swap this
    # private map entry for a constructor input when transfer_materializer moves to support.
    h.s.materializer._access["linked_export"] = LinkedExportAccess(h.resolver, Revoked())
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await h.s.materializer.materialize(h.s.request(h.selection, attempt=2), FakeBackend())
    assert any(item.code == "RECEIVER_ACCESS_REVOKED" for item in refused.value.refusals)


def test_goal_repair_preserves_own_subject_and_link_but_evaluator_never_inherits():
    from mission_control.domain.context import transfer_builders as builders
    from mission_control.domain.context.transfer import Boundary, ProducerAttempt

    h = setup()
    prior = builders.next_iteration(dependent(), [("root", "root.report")])
    repair = builders.authorized_subjects(
        prior,
        ProducerAttempt(
            operation_ref="goal-iteration/1/executor", operation_attempt=1, execution_generation=1
        ),
        repair=True,
    )
    linked = builders.linked_mission(repair, (h.export,))
    assert linked.boundary == Boundary.REPAIR
    assert linked.inputs[0] == repair.inputs[0]
    assert linked.inputs[-1].source.kind == "linked_export"
    evaluator = builders.evaluator(dependent(), [("root", "root.report")])
    with pytest.raises(ValueError, match="independent evaluators"):
        builders.linked_mission(evaluator, (h.export,))
