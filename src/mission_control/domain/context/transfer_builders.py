"""Boundary builders for the receiver's transfer selection (OUTPUT-CONTRACTS §6; WI-02).

One pure builder per boundary turns what the family admitted into the receiver's
``TransferSelection``; the one materializer seals it. A first invocation invents no predecessor;
a dependent stage receives exactly its declared ``from: <producer>.<output>`` bindings; a next
Goal Loop iteration receives exactly the admitted predecessor outputs; an independent evaluator
receives only its nominated subject; a continuation keeps the prior selection (its plan is
reused, never re-resolved). Nested-body exports and linked-mission inputs refuse typed until
their work items (WI-13, WI-16) deliver them: never an empty plan in their place.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from mission_control.domain.context.transfer import (
    BackendCapabilities,
    Boundary,
    InputSource,
    LinkedExport,
    Placement,
    ProducerAttempt,
    ReleaseOmission,
    ResourceBounds,
    TransferInput,
    TransferSelection,
)

# A dependent stage receives accepted revisions only; an evaluator subject and a next
# iteration's predecessors accept the producer's accepted head, else its newest finalized,
# unrejected submission (each member records which: `ExactMember.admission`).
DEPENDENT_STATUSES = ("accepted",)
PREDECESSOR_STATUSES = ("accepted", "submitted")
# A dependent stage's declared inputs are required (OVE-169, OVE-171 C): production composes
# the trusted settlement (WI-03), which promotes a passing submitted revision through
# `promote_output` and writes Fulfillment@1, and a demoted or held head is never admitted, so a
# consumer refuses to start on a non-accepted predecessor revision instead of running without
# its input. The only opt-out is authored: a `required: false` binding (visible omission).
DEPENDENT_INPUT_REQUIRED = True
# Next-iteration predecessor inputs stay optional: the Goal Loop executor workspace remains the
# receiver's authoritative host state, and an absent exact revision is a visible omission in the
# sealed plan, never a silent drop.
FAMILY_INPUT_REQUIRED = False


class TransferBoundaryUnsupported(ValueError):
    """A boundary whose inputs a later work item delivers; refused, never planned empty."""

    def __init__(self, code: str, owner: str, message: str) -> None:
        super().__init__(f"{code} ({owner}): {message}")
        self.code = code
        self.owner = owner


def _with(base: TransferSelection, **fields: object) -> TransferSelection:
    """A validated successor selection (``model_copy`` would skip the admission rules).

    A receiver with no declared budget keeps its base selection: it carries its owner
    position, admits no input and so seals no plan.
    """

    if base.bounds is None and fields.get("inputs"):
        return base
    return TransferSelection.model_validate({**base.model_dump(mode="python"), **fields})


def _name(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")
    return (cleaned or "input")[:64].strip("-") or "input"


def subject_input_name(output_key: str) -> str:
    """The transfer input name of an evaluator's subject (``evaluator``): ``subject-<key>``."""

    return _name(f"subject-{output_key}")


def first_invocation(
    position: str, bounds: ResourceBounds | None, backend: BackendCapabilities
) -> TransferSelection:
    """The template's base selection: bounds and backend from the resolved runtime, no inputs."""

    return TransferSelection(
        boundary=Boundary.FIRST_INVOCATION,
        receiver_position=position,
        inputs=(),
        bounds=bounds,
        backend=backend,
    )


def dependent_stage(
    base: TransferSelection,
    bindings: Sequence[tuple[str, str, str]],
    *,
    optional: Collection[str] = (),
    omitted: Sequence[tuple[str, str, str, str]] = (),
    placements: Mapping[str, Placement] | None = None,
) -> TransferSelection:
    """``(name, producer position, output key)`` per selected input binding of the stage.

    Every selected binding is required (an accepted revision only) unless its authored name is
    in ``optional``. ``omitted`` holds ``(name, producer, output, code)`` for each binding the
    stage's release left out (OVE-171): the sealed plan records it as a visible omission and
    never resolves it later, so a late arrival cannot alter the plan. ``placements`` holds
    the authored placement by binding name (L1-08: ``expand: materialize`` is a file); an
    unnamed binding keeps the profile default.
    """

    inputs = tuple(
        TransferInput(
            name=_name(name),
            source=InputSource.produced(producer, output),
            purpose="dependent_input",
            required=DEPENDENT_INPUT_REQUIRED and name not in optional,
            accepted_statuses=DEPENDENT_STATUSES,
            placement=(placements or {}).get(name),
        )
        for name, producer, output in bindings
    )
    release_omissions = tuple(
        ReleaseOmission.model_validate(
            {"binding": _name(name), "position": producer, "output_key": output, "code": code}
        )
        for name, producer, output, code in omitted
    )
    if base.bounds is None:
        # A receiver without a declared model input limit admits no input and seals no plan
        # (`_with`), so there is no plan for release omissions to appear in either: they are
        # dropped with the inputs, deliberately (the release still records them durably in
        # `released_by[].selection`).
        return base
    return _with(
        base,
        boundary=Boundary.DEPENDENT_STAGE,
        inputs=inputs,
        release_omissions=release_omissions,
    )


def next_iteration(
    base: TransferSelection, predecessors: Sequence[tuple[str, str]]
) -> TransferSelection:
    """``(position, output key)`` of each admitted predecessor output of the prior iteration."""

    inputs = tuple(
        TransferInput(
            name=_name(f"prior-{output}"),
            source=InputSource.produced(position, output),
            purpose="dependent_input",
            required=FAMILY_INPUT_REQUIRED,
            accepted_statuses=PREDECESSOR_STATUSES,
        )
        for position, output in predecessors
    )
    return _with(base, boundary=Boundary.NEXT_ITERATION, inputs=inputs)


def evaluator(base: TransferSelection, subjects: Sequence[tuple[str, str]]) -> TransferSelection:
    """Only the nominated ``(position, output key)`` subjects; nothing run-wide, no scratch."""

    if not subjects:
        raise TransferBoundaryUnsupported(
            "EVALUATOR_SUBJECT_MISSING", "host", "an independent evaluator needs its subject"
        )
    inputs = tuple(
        TransferInput(
            name=subject_input_name(output),
            source=InputSource.produced(position, output),
            purpose="evaluation_subject",
            # B1: an independent evaluator never runs without its nominated subject.
            required=True,
            accepted_statuses=PREDECESSOR_STATUSES,
        )
        for position, output in subjects
    )
    return _with(
        base, boundary=Boundary.EVALUATOR, isolation="independent_evaluator", inputs=inputs
    )


def for_producer(selection: TransferSelection, operation: str) -> TransferSelection:
    """Bind every input's `submitted` fallback to the exact producing operation (the current
    iteration's executor), never the newest submission across the run."""

    inputs = tuple(
        item.model_copy(update={"producer_operation": operation})
        if "submitted" in item.accepted_statuses
        else item
        for item in selection.inputs
    )
    return _with(selection, inputs=inputs) if selection.bounds is not None else selection


def authorized_subjects(
    selection: TransferSelection, producer: ProducerAttempt, *, repair: bool = False
) -> TransferSelection:
    """Bind host-validated finalized subjects without granting official accepted use."""
    if repair:
        if selection.boundary != Boundary.NEXT_ITERATION:
            raise ValueError("repair subjects require an admitted next-iteration selection")
    elif selection.boundary != Boundary.EVALUATOR or selection.isolation != "independent_evaluator":
        raise ValueError("evaluation subjects require an independent evaluator")
    inputs = tuple(
        item.model_copy(
            update={
                "subject_attempt": producer,
                "producer_operation": producer.operation_ref,
                "purpose": "repair" if repair else "evaluation_subject",
            }
        )
        if item.source.kind == "produced_output"
        else item
        for item in selection.inputs
    )
    return _with(
        selection, inputs=inputs, boundary=Boundary.REPAIR if repair else selection.boundary
    )


def isolated_evaluator(base: TransferSelection) -> TransferSelection:
    """An evaluator with no plan-borne subject (its executor cannot submit named outputs): it
    still carries the independent-evaluator role, so its knowledge reads stay scoped."""

    return _with(base, boundary=Boundary.EVALUATOR, isolation="independent_evaluator", inputs=())


def continuation(prior: TransferSelection) -> TransferSelection:
    """A continuation keeps the receiver's exact selection: its sealed plan is reused and each
    new session appends its own receipt (§6 "restart, compaction and redelivery")."""

    return prior


def nested_export(base: TransferSelection) -> TransferSelection:
    raise TransferBoundaryUnsupported(
        "NESTED_INPUT_UNSUPPORTED", "WI-13", "nested-body exports are delivered by WI-13"
    )


def linked_mission(
    base: TransferSelection, exports: Sequence[LinkedExport] = ()
) -> TransferSelection:
    """Freeze explicit released exports alongside this receiver's admitted local inputs."""
    if base.isolation != "shared":
        raise ValueError("linked exports are not automatically inherited by independent evaluators")
    if not exports:
        raise TransferBoundaryUnsupported("LINK_EXPORT_MISSING", "host", "no released export")
    if base.bounds is None:
        raise TransferBoundaryUnsupported(
            "LINK_BUDGET_MISSING", "host", "linked inputs need a budget"
        )
    if any(item.receiver_position != base.receiver_position for item in exports):
        raise ValueError("linked export belongs to another receiver position")
    inputs = tuple(
        TransferInput(
            name=item.input_name,
            source=InputSource.linked(item.export_id, item.digest),
            purpose=item.purpose,
            required=item.required,
            placement=item.placement,
            alternatives=item.alternatives,
            evidence_required=item.evidence_required,
        )
        for item in exports
    )
    boundary = (
        base.boundary
        if base.boundary in {Boundary.NEXT_ITERATION, Boundary.REPAIR}
        else Boundary.LINKED_MISSION
    )
    return _with(base, boundary=boundary, inputs=(*base.inputs, *inputs))


__all__ = [
    "DEPENDENT_INPUT_REQUIRED",
    "DEPENDENT_STATUSES",
    "FAMILY_INPUT_REQUIRED",
    "PREDECESSOR_STATUSES",
    "TransferBoundaryUnsupported",
    "authorized_subjects",
    "continuation",
    "dependent_stage",
    "evaluator",
    "first_invocation",
    "for_producer",
    "isolated_evaluator",
    "linked_mission",
    "nested_export",
    "next_iteration",
]
