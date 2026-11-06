"""Boundary builders and launch wiring of the receiver's transfer selection (WI-02 / OVE-164)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mission_control.application.execution.run_launch import RunLaunchRejected
from mission_control.application.outputs.launch import LaunchPromiseRegistrar
from mission_control.application.programs.goal_directed import _iteration_transfer
from mission_control.application.programs.service import _stage_transfer
from mission_control.domain.context import transfer_builders as builders
from mission_control.domain.context.transfer import (
    BackendCapabilities,
    Boundary,
    ResourceBounds,
    TransferSelection,
)
from mission_control.domain.outputs.contracts import OutputError, OutputErrorCode, OutputForm
from mission_control.domain.outputs.current_set import with_current_set_index
from mission_control.domain.resolution.resolved import (
    REPORT_REVIEW_FILE_BYTES,
    receiver_transfer_base,
)
from tests.unit.outputs.scenario import obligation, promises
from tests.unit.resolution.test_resolution_types import _runtime

BOUNDS = ResourceBounds(
    window_tokens=200_000,
    generation_reserve_tokens=8_000,
    tool_result_reserve_tokens=8_000,
    inline_bytes_ceiling=16_000,
    file_bytes_ceiling=1_000_000,
    file_count_ceiling=16,
)
BACKEND = BackendCapabilities(custody_backend="mc", file_capable=True, binary_capable=False)


def base(position: str = "review") -> TransferSelection:
    return builders.first_invocation(position, BOUNDS, BACKEND)


def test_a_first_invocation_carries_bounds_and_no_predecessor() -> None:
    selection = base()
    assert selection.boundary is Boundary.FIRST_INVOCATION and selection.inputs == ()


def test_a_dependent_stage_receives_exactly_its_declared_bindings() -> None:
    selection = builders.dependent_stage(base(), [("Draft Report", "draft", "draft.report")])
    assert selection.boundary is Boundary.DEPENDENT_STAGE
    (only,) = selection.inputs
    assert only.name == "draft-report" and only.source.position == "draft"
    assert only.source.output_key == "draft.report"
    assert only.accepted_statuses == ("accepted",)  # never the submitted fallback
    assert selection.digest != base().digest


def test_a_next_iteration_receives_its_predecessors_and_an_evaluator_only_its_subject() -> None:
    later = builders.next_iteration(base("goal"), [("goal", "goal.report")])
    assert later.boundary is Boundary.NEXT_ITERATION
    assert [item.purpose for item in later.inputs] == ["dependent_input"]
    judge = builders.evaluator(base("goal"), [("goal", "goal.report")])
    assert judge.isolation == "independent_evaluator"
    assert {item.purpose for item in judge.inputs} == {"evaluation_subject"}
    with pytest.raises(builders.TransferBoundaryUnsupported, match="EVALUATOR_SUBJECT_MISSING"):
        builders.evaluator(base("goal"), [])


def test_builders_revalidate_and_continuation_reuses_the_selection() -> None:
    prior = builders.dependent_stage(base(), [("draft", "draft", "draft.report")])
    assert builders.continuation(prior) is prior
    with pytest.raises(ValidationError, match="unique"):
        builders.dependent_stage(base(), [("draft", "a", "a.x"), ("draft", "b", "b.y")])


@pytest.mark.parametrize(
    ("builder", "code", "owner"),
    [
        (builders.nested_export, "NESTED_INPUT_UNSUPPORTED", "WI-13"),
        (builders.linked_mission, "LINK_EXPORT_MISSING", "host"),
    ],
)
def test_nested_and_link_inputs_refuse_typed_never_an_empty_plan(builder, code, owner) -> None:
    with pytest.raises(builders.TransferBoundaryUnsupported) as refused:
        builder(base())
    assert refused.value.code == code and refused.value.owner == owner


def test_the_base_selection_is_sized_by_the_resolved_model_input_limit() -> None:
    runtime = _runtime()
    selection = receiver_transfer_base(runtime, "draft")
    assert selection.bounds is not None
    assert selection.bounds.window_tokens == runtime.agent.model.max_input_tokens
    assert selection.bounds.inline_bytes_ceiling == runtime.transfer.inline_bytes_ceiling
    assert selection.bounds.file_bytes_ceiling == REPORT_REVIEW_FILE_BYTES
    assert selection.backend.file_capable == runtime.transfer.file_capable
    # A receiver without a declared budget keeps its position but admits no input.
    waiting = selection.model_copy(update={"bounds": None})
    assert builders.dependent_stage(waiting, [("d", "draft", "draft.report")]) is waiting
    with pytest.raises(ValidationError, match="declared model input limit"):
        TransferSelection.model_validate(
            waiting.model_dump(mode="python") | {"inputs": later_inputs()}
        )


def later_inputs() -> tuple:
    return builders.next_iteration(base("goal"), [("goal", "goal.report")]).inputs


def _template(selection: TransferSelection | None) -> SimpleNamespace:
    return SimpleNamespace(transfer=selection)


def test_families_attach_their_boundary_selection() -> None:
    stage = SimpleNamespace(
        proposal=SimpleNamespace(
            identity=SimpleNamespace(stage_id="review"), released_by=(), frozen_input_bindings=()
        ),
        authored_inputs=(
            SimpleNamespace(
                consumer_stage_id="review",
                producer_stage_id="draft",
                producer_output_slot_id="report",
                name="draft",
                expand="auto",
                required=True,
            ),
            SimpleNamespace(
                consumer_stage_id="other",
                producer_stage_id="draft",
                producer_output_slot_id="report",
                name="unrelated",
                expand="auto",
                required=True,
            ),
        ),
    )
    attached = _stage_transfer(
        _template(base()),
        stage,
        promises=promises(obligation("draft.report", OutputForm.REFERENCE)),
    )  # type: ignore[arg-type]
    assert attached is not None and [i.name for i in attached.inputs] == ["draft"]
    assert _stage_transfer(_template(None), stage) is None  # type: ignore[arg-type]
    later = builders.next_iteration(base("goal"), [("goal", "goal.report")])

    def goal(role: str, iteration: int) -> SimpleNamespace:
        return SimpleNamespace(operation_role=role, goal_iteration=iteration)

    first = _iteration_transfer(_template(later), goal("executor", 1))  # type: ignore[arg-type]
    assert first is not None and first.boundary is Boundary.FIRST_INVOCATION and not first.inputs
    # WI-07: a later executor and the verifier also receive the exact current-set index file.
    assert _iteration_transfer(_template(later), goal("executor", 2)) == with_current_set_index(
        builders.for_producer(later, "goal-iteration/1/executor"), purpose="current_set"
    )  # type: ignore[arg-type]
    judge = builders.evaluator(base("goal"), [("goal", "goal.report")])
    verifier = _iteration_transfer(_template(judge), goal("verifier", 1))  # type: ignore[arg-type]
    assert verifier == with_current_set_index(
        builders.for_producer(judge, "goal-iteration/1/executor"), purpose="evaluation_subject"
    )
    assert verifier is not None and [i.name for i in verifier.inputs][-1] == "current-set"
    index = verifier.inputs[-1]
    assert index.required and index.placement == "file"
    assert index.source.binding_pin == "mc.current-set@1"


class _Outputs:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str, str | None]] = []

    async def register_promises(self, access, run_id, promises, *, configuration_digest=None):  # type: ignore[no-untyped-def]
        self.calls.append((access.scope, run_id, configuration_digest))
        return self.answer


async def test_launch_registers_the_admitted_promises_and_refuses_a_conflict() -> None:
    outputs = _Outputs(())
    promises = object()
    await LaunchPromiseRegistrar(outputs)("s", "run-1", "sha256:x", promises)  # type: ignore[arg-type]
    assert outputs.calls == [("s", "run-1", "sha256:x")]
    conflict = _Outputs(
        OutputError(code=OutputErrorCode.PROMISES_CONFLICT, safe_message="another set")
    )
    with pytest.raises(RunLaunchRejected, match="PROMISES_CONFLICT"):
        await LaunchPromiseRegistrar(conflict)("s", "r", "d", promises)  # type: ignore[arg-type]
