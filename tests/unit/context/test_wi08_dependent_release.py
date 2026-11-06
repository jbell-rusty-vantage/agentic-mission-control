"""OVE-171 / WI-08 slice C and the transfer side of B: a dependent stage's inputs are required
accepted revisions (a held predecessor revision refuses the consumer; an unrelated sibling is
never selected); what the release omitted (an optional input still pending, a surplus group
member) is a visible omission in the sealed plan; a late arrival cannot alter the plan and a
redelivery appends a receipt."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mission_control.application.context.materialization import ContextDeliveryBlocked
from mission_control.application.programs.service import _stage_transfer
from mission_control.domain.context import transfer_builders as builders
from mission_control.domain.context.transfer import ReleaseOmission, TransferSelection
from mission_control.domain.outputs.contracts import (
    ExactOutput,
    OutputContract,
    OutputForm,
    OutputObligation,
)
from mission_control.domain.programs.contracts import (
    StageAuthoredInput,
    StageInputBinding,
    StageReleasedBy,
)
from tests.fixtures.knowledge_binding import report_package
from tests.unit.context.test_transfer_materializer import (
    RUN,
    FakeBackend,
    dependent,
    seam,
)
from tests.unit.knowledge.test_gateway import TENANT
from tests.unit.outputs.scenario import obligation, promises


def _promises():
    return promises(
        *(
            obligation(f"{producer}.{slot}", OutputForm.REFERENCE, position=producer)
            for producer, slot in (
                ("safety_a", "out"),
                ("safety_b", "out"),
                ("efficacy", "out"),
                ("context", "out"),
                ("draft", "report"),
                ("critique", "verdict"),
            )
        )
    )


def _base() -> TransferSelection:
    return builders.first_invocation("review", dependent().bounds, dependent().backend)


def _held(s, key: str = "draft.report") -> ExactOutput:  # type: ignore[no-untyped-def]
    return ExactOutput(
        revision_id="rev-held-1",
        run_id=RUN,
        obligation_key=key,
        obligation_revision=1,
        deliverable_id="report",
        revision=1,
        form=OutputForm.REFERENCE,
        content_digest=s.package.report.digest,
        candidate={"kind": "handle", "ref": s.handle()},
        producer_origin_ref="mc-inv:draft",
    )


async def test_a_consumer_refuses_to_start_on_a_held_predecessor_revision() -> None:
    s = seam()
    s.outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    # Submitted (held for review) but never promoted: not an accepted head.
    s.outputs.submitted.append(_held(s))
    stage = builders.dependent_stage(_base(), [("draft", "draft", "draft.report")])
    assert builders.DEPENDENT_INPUT_REQUIRED and stage.inputs[0].required
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await s.materializer.materialize(s.request(stage), FakeBackend())
    assert refused.value.refusals[0].code == "SOURCE_NOT_ACCEPTED"
    assert s.outputs.producer_operations == []  # the held fallback is never consulted


async def test_an_unrelated_accepted_sibling_is_never_selected() -> None:
    s = seam()
    s.accept_report()
    sibling = s.fake.register_package(
        report_package("report-9", "1", tenant=TENANT, body=b"# Sibling\n")
    )
    s.accept(
        "sibling",
        "sibling.report",
        _held(s, "sibling.report").model_copy(
            update={
                "revision_id": "rev-sibling-1",
                "content_digest": sibling.report.digest,
                "candidate": {"kind": "handle", "ref": s.handle(sibling)},
                "producer_origin_ref": "mc-inv:sibling",
            }
        ),
    )
    stage = builders.dependent_stage(_base(), [("draft", "draft", "draft.report")])
    result = await s.materializer.materialize(s.request(stage), FakeBackend())
    assert {member.binding for member in result.plan.exact_sources} == {"draft"}
    assert sibling.body not in dict(result.files).values()


async def test_release_omissions_are_visible_and_a_late_arrival_cannot_alter_the_plan() -> None:
    s = seam()
    s.accept_report()
    stage = builders.dependent_stage(
        _base(),
        [("draft", "draft", "draft.report")],
        omitted=[("second", "second", "second.report", "RELEASE_SURPLUS")],
    )
    first = await s.materializer.materialize(s.request(stage), FakeBackend())
    assert [(o.binding, o.code) for o in first.plan.omissions] == [("second", "RELEASE_SURPLUS")]
    assert first.index["omissions"][0]["code"] == "RELEASE_SURPLUS"
    # The surplus producer's revision is accepted after the plan was sealed.
    late = s.fake.register_package(report_package("report-8", "1", tenant=TENANT, body=b"# L\n"))
    s.accept(
        "second",
        "second.report",
        _held(s, "second.report").model_copy(
            update={
                "revision_id": "rev-second-1",
                "content_digest": late.report.digest,
                "candidate": {"kind": "handle", "ref": s.handle(late)},
            }
        ),
    )
    again = await s.materializer.materialize(s.request(stage, attempt=2), FakeBackend("fake:b2"))
    assert again.plan.digest == first.plan.digest
    assert late.body not in dict(again.files).values()
    receipts = await s.store.receipts(s.access().scope, first.plan.plan_id)
    assert [item.sequence for item in receipts] == [1, 2]


def test_an_authored_optional_binding_is_the_only_opt_out() -> None:
    stage = builders.dependent_stage(
        _base(),
        [("draft", "draft", "draft.report"), ("context", "context", "context.note")],
        optional={"context"},
    )
    assert [(item.name, item.required) for item in stage.inputs] == [
        ("draft", True),
        ("context", False),
    ]
    with pytest.raises(ValueError, match="unique per receiver"):
        builders.dependent_stage(
            _base(),
            [("draft", "draft", "draft.report")],
            omitted=[("draft", "draft", "draft.report", "RELEASE_SURPLUS")],
        )


def _admission(released: tuple[StageReleasedBy, ...]) -> SimpleNamespace:
    inputs = (
        StageAuthoredInput("synth", "safety_a", "out", "safety_a"),
        StageAuthoredInput("synth", "safety_b", "out", "safety_b"),
        StageAuthoredInput("synth", "efficacy", "out", "efficacy"),
        StageAuthoredInput("synth", "context", "out", "context", required=False),
        StageAuthoredInput("other", "safety_a", "out", "unrelated"),
    )
    return SimpleNamespace(
        proposal=SimpleNamespace(
            identity=SimpleNamespace(stage_id="synth"),
            released_by=released,
            frozen_input_bindings=(),
        ),
        authored_inputs=inputs,
    )


def _released(producer: str, selection: str | None) -> StageReleasedBy:
    return StageReleasedBy(
        dependency_id=f"{producer}:to:synth",
        join_id="synth:group:reviews",
        producer_stage_id=producer,
        producer_output_slot_id="out",
        selection=selection,
    )


def test_the_stage_transfer_follows_the_frozen_release_selection() -> None:
    template = SimpleNamespace(transfer=_base())
    released = (
        _released("efficacy", "selected"),
        _released("safety_b", "selected"),
        _released("safety_a", "surplus"),
        _released("context", "omitted"),
    )
    selection = _stage_transfer(template, _admission(released), promises=_promises())  # type: ignore[arg-type]
    assert selection is not None
    assert [(item.name, item.required) for item in selection.inputs] == [
        ("safety-b", True),
        ("efficacy", True),
    ]
    assert [(item.binding, item.code) for item in selection.release_omissions] == [
        ("safety-a", "RELEASE_SURPLUS"),
        ("context", "RELEASE_OPTIONAL_PENDING"),
    ]
    assert all(isinstance(item, ReleaseOmission) for item in selection.release_omissions)
    assert {item.source.output_key for item in selection.inputs} == {"safety_b.out", "efficacy.out"}
    assert {item.output_key for item in selection.release_omissions} == {
        "safety_a.out",
        "context.out",
    }


@pytest.mark.parametrize("accepted", [False, True])
async def test_the_consumer_path_resolves_local_slot_to_exact_owned_promise(accepted) -> None:
    """A local slot reaches its exact accepted revision; a merely submitted held
    revision remains unavailable to the dependent consumer."""

    s = seam()
    s.outputs.obligations.append(
        OutputObligation(
            key="draft.report",
            owner_position="draft",
            contract=OutputContract(form=OutputForm.REFERENCE),
        )
    )
    s.outputs.submitted.append(_held(s))
    if accepted:
        s.accept_report()
    request = SimpleNamespace(
        proposal=SimpleNamespace(
            identity=SimpleNamespace(stage_id="review"),
            released_by=(
                StageReleasedBy(
                    dependency_id="draft:to:review",
                    join_id="review:inputs",
                    producer_stage_id="draft",
                    producer_output_slot_id="report",
                    selection="selected",
                ),
            ),
            frozen_input_bindings=(),
        ),
        authored_inputs=(StageAuthoredInput("review", "draft", "report", "draft"),),
    )
    selection = _stage_transfer(SimpleNamespace(transfer=_base()), request, promises=_promises())  # type: ignore[arg-type]
    assert selection is not None and [i.required for i in selection.inputs] == [True]
    assert selection.inputs[0].source.output_key == "draft.report"
    if accepted:
        materialized = await s.materializer.materialize(s.request(selection), FakeBackend())
        assert materialized.receipt.result == "ready"
        return
    with pytest.raises(ContextDeliveryBlocked) as refused:
        await s.materializer.materialize(s.request(selection), FakeBackend())
    assert refused.value.refusals[0].code == "SOURCE_NOT_ACCEPTED"


def test_a_revisited_entry_receives_the_carried_exit_output_as_a_required_input() -> None:
    carried = StageInputBinding(
        consumer_input_slot_id="carry:refine:verdict",
        producer_stage_key="critique",
        producer_output_slot_id="verdict",
        artifact_ref="artifact://critique/v1",
    )
    request = SimpleNamespace(
        proposal=SimpleNamespace(
            identity=SimpleNamespace(stage_id="draft"),
            released_by=(),
            frozen_input_bindings=(carried,),
        ),
        authored_inputs=(),
    )
    selection = _stage_transfer(SimpleNamespace(transfer=_base()), request, promises=_promises())  # type: ignore[arg-type]
    assert selection is not None
    assert [(i.name, i.required, i.source.position) for i in selection.inputs] == [
        ("carry-verdict", True, "critique")
    ]
    assert selection.inputs[0].source.output_key == "critique.verdict"


@pytest.mark.parametrize("case", ["missing", "sibling", "nested", "qualified-slot"])
def test_slot_mapping_refuses_unowned_or_nonlocal_sources(case):
    request = _admission((_released("safety_a", "selected"),))
    request.authored_inputs = (StageAuthoredInput("synth", "safety_a", "out", "report"),)
    source_promises = promises(
        obligation("safety_a.out", OutputForm.REFERENCE, position="safety_a")
    )
    if case == "missing":
        source_promises = None
    elif case in {"sibling", "nested"}:
        source_promises = promises(
            obligation(
                "safety_a.out",
                OutputForm.REFERENCE,
                position="safety_b" if case == "sibling" else "outer/safety_a",
            )
        )
    else:
        request.authored_inputs = (
            StageAuthoredInput("synth", "safety_a", "safety_a.out", "report"),
        )
    with pytest.raises(ValueError, match="no admitted owned output promise"):
        _stage_transfer(SimpleNamespace(transfer=_base()), request, promises=source_promises)


def test_a_receiver_without_bounds_seals_no_plan_so_release_omissions_drop_with_it() -> None:
    waiting = _base().model_copy(update={"bounds": None})
    kept = builders.dependent_stage(
        waiting,
        [("draft", "draft", "draft.report")],
        omitted=[("second", "second", "second.report", "RELEASE_SURPLUS")],
    )
    assert kept is waiting


def test_a_legacy_release_keeps_every_authored_input() -> None:
    template = SimpleNamespace(transfer=_base())
    released = tuple(
        _released(producer, None) for producer in ("safety_a", "safety_b", "efficacy", "context")
    )
    selection = _stage_transfer(template, _admission(released), promises=_promises())  # type: ignore[arg-type]
    assert selection is not None
    assert [item.name for item in selection.inputs] == [
        "safety-a",
        "safety-b",
        "efficacy",
        "context",
    ]
    assert selection.release_omissions == ()
    assert "release_omissions" not in selection.model_dump(mode="json")


@pytest.mark.parametrize(
    ("expand", "placement"),
    [("materialize", "file"), ("inline", "inline"), ("auto", None), ("reference", None)],
)
def test_an_authored_expansion_tier_becomes_the_inputs_placement(expand, placement) -> None:
    """L1-08 (E4 `map`): `expand: materialize` is a read-only file under
    `/inputs/<binding>/<revision>/` with the index pointing at it, never inline bytes."""

    from mission_control.domain.context.transfer import render_index
    from tests.unit.context.test_transfer_plan import member, seal

    request = SimpleNamespace(
        proposal=SimpleNamespace(
            identity=SimpleNamespace(stage_id="review"),
            released_by=(),
            frozen_input_bindings=(),
        ),
        authored_inputs=(StageAuthoredInput("review", "draft", "report", "notes", expand=expand),),
    )
    selection = _stage_transfer(SimpleNamespace(transfer=_base()), request, promises=_promises())  # type: ignore[arg-type]
    assert selection is not None
    (binding,) = selection.inputs
    assert binding.placement == placement and binding.alternatives == ()
    note = member("notes", "value", b"collected notes\n", media_type="text/plain")
    plan = seal(
        selection.model_copy(update={"bounds": dependent().bounds}),
        [note.model_copy(update={"file_name": "notes.txt"})],
        inline_texts={"notes/value": "collected notes\n"},
    )
    (placed,) = plan.placements
    if expand == "materialize":
        assert placed.placement == "file"
        assert placed.path == "/inputs/notes/r7_1/notes.txt"
        (entry,) = render_index(plan)["inputs"]
        assert (entry["path"], entry["read_with"]) == (placed.path, "read_file")
    else:
        assert placed.placement == "inline" and placed.path is None
