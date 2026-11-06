"""The goal-wide current-set index (WI-07; OUTPUT-CONTRACTS §7, OC-D133).

The Goal Loop verifier assesses the whole required current set and a later executor sees the
current accepted work, not only the latest executor refs. Inline state stays bounded; the
complete exact index of the current set is a readable **file** of the receiver's sealed plan
(``mc.current_set_index.v1``), never inline context. It names, per declared promise:

* every accepted head of the pinned set (``OutputSet``) with its exact revision, digest and the
  standing judgment of every requirement (and, for a collection, of every member);
* the distinct count against the promised cardinality (revisions of one deliverable count once)
  and the promised coverage subjects still missing;
* finalized candidates that are not heads, labelled ``held``, ``rejected``, ``waiting`` or
  ``pending`` (their content is loaded only when a task selects it).

The index is a projection: it never decides fulfillment (the convergence boundary does, with the
form evidence ports) and it carries no authority. Its bytes are canonical JSON, so the sealed
member digest is stable for the same set and judgments.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from mission_control.domain.context.transfer import InputSource, TransferInput, TransferSelection
from mission_control.domain.outputs.collections import MEMBER_LABELS, member_outcomes
from mission_control.domain.outputs.contracts import (
    Assessment,
    ExactOutput,
    MemberDecisions,
    OutputForm,
    OutputObligation,
    OutputSet,
    TrustedValidators,
)
from mission_control.domain.outputs.fulfillment import judged
from mission_control.domain.outputs.rules import pointer_get

CURRENT_SET_INDEX_SCHEMA: Final = "mc.current_set_index.v1"
# The application-selector binding pin the host registers for the index (no application data).
CURRENT_SET_BINDING: Final = "mc.current-set@1"
CURRENT_SET_INPUT: Final = "current-set"
CURRENT_SET_FILE: Final = "current-set.json"
Judgment = Literal["pass", "fail", "review", "unavailable", "unassessed"]
_LABEL: dict[str, str] = MEMBER_LABELS


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IndexMember(_Closed):
    """One exact member of a collection head and its standing per-member judgment."""

    ref: str
    digest: str
    judgment: Judgment
    label: str


class IndexRevision(_Closed):
    """One exact revision: an accepted head, or a finalized candidate that is not one."""

    deliverable_id: str
    revision_id: str
    revision: int
    content_digest: str
    form: OutputForm
    ref: str | None = None
    obligation_revision: int
    status: Literal["accepted", "candidate"]
    judgment: Judgment
    label: str
    requirements: dict[str, Judgment] = Field(default_factory=dict)
    members: tuple[IndexMember, ...] = ()


class IndexPromise(_Closed):
    key: str
    revision: int
    owner_position: str
    enforcement: str
    evaluation_scope: str
    form: OutputForm
    cardinality: dict[str, int]
    distinct_count: int
    heads: tuple[IndexRevision, ...] = ()
    candidates: tuple[IndexRevision, ...] = ()
    missing_coverage: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()


class CurrentSetIndex(_Closed):
    schema_version: Literal["mc.current_set_index.v1"] = CURRENT_SET_INDEX_SCHEMA
    run_id: str
    set_id: str
    set_revision: int
    membership_digest: str
    promises: tuple[IndexPromise, ...]
    note: str = (
        "Exact current accepted set and labelled non-head candidates. A projection only: "
        "fulfillment is decided by the host at convergence; held and rejected candidates are "
        "listed, not loaded."
    )

    def document(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")

    def render(self) -> bytes:
        """Sorted-key compact UTF-8 JSON of the document (stable bytes for the same index)."""

        return json.dumps(
            self.document(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")


_SEVERITY: dict[str, int] = {"pass": 0, "unassessed": 1, "review": 2, "unavailable": 3, "fail": 4}


def _worst(states: Sequence[Judgment]) -> Judgment:
    if not states:
        return "unassessed"
    return max(states, key=_SEVERITY.__getitem__)


def _revision(
    obligation: OutputObligation,
    output: ExactOutput,
    assessments: Sequence[Assessment],
    status: Literal["accepted", "candidate"],
    trusted_validators: TrustedValidators,
    member_decisions: MemberDecisions | None,
) -> IndexRevision:
    requirements: dict[str, Judgment] = {}
    for requirement in obligation.contract.requirements:
        if requirement.subject != "deliverable":
            continue
        result, _ = judged(
            assessments,
            "output_revision",
            output.revision_id,
            output.content_digest,
            requirement.key,
        )
        requirements[requirement.key] = result or "unassessed"
    members: tuple[IndexMember, ...] = ()
    if obligation.contract.form is OutputForm.COLLECTION:
        members = tuple(
            IndexMember(ref=item.ref, digest=item.digest, judgment=item.state, label=item.label)
            for item in member_outcomes(
                obligation,
                output,
                assessments,
                trusted_validators=trusted_validators,
                member_decisions=member_decisions,
            )
        )
    states = [*requirements.values(), *(item.judgment for item in members)]
    # A head with nothing to judge is accepted by its promotion; a candidate stays pending.
    judgment: Judgment = (
        _worst(states) if states else ("pass" if status == "accepted" else "unassessed")
    )
    ref = output.candidate.get("ref")
    return IndexRevision(
        deliverable_id=output.deliverable_id,
        revision_id=output.revision_id,
        revision=output.revision,
        content_digest=output.content_digest,
        form=output.form,
        ref=ref if isinstance(ref, str) else None,
        obligation_revision=output.obligation_revision,
        status=status,
        judgment=judgment,
        label="accepted" if status == "accepted" and judgment == "pass" else _LABEL[judgment],
        requirements=requirements,
        members=members,
    )


def _covered(
    obligation: OutputObligation, heads: Sequence[IndexRevision], outputs: dict[str, ExactOutput]
) -> set[str]:
    coverage = obligation.contract.coverage
    if coverage is None:
        return set()
    subjects: set[str] = set()
    for head in heads:
        found, entries = pointer_get(
            outputs[head.revision_id].candidate.get("value"), coverage.pointer
        )
        if not found or not isinstance(entries, list):
            continue
        passing = {(m.ref, m.digest) for m in head.members if m.judgment == "pass"}
        for entry in entries:
            if isinstance(entry, str) and obligation.contract.form is not OutputForm.COLLECTION:
                subjects.add(entry)
            elif isinstance(entry, dict) and coverage.key is not None:
                value = entry.get(coverage.key)
                if not isinstance(value, str):
                    continue
                if obligation.contract.form is OutputForm.COLLECTION and (
                    (entry.get("ref"), entry.get("digest")) not in passing
                ):
                    continue
                subjects.add(value)
    return subjects


def build_current_set_index(
    run_id: str,
    obligations: Sequence[OutputObligation],
    output_set: OutputSet,
    assessments: Sequence[Assessment],
    candidates: Sequence[ExactOutput] = (),
    *,
    trusted_validators: TrustedValidators,
    member_decisions: MemberDecisions | None = None,
) -> CurrentSetIndex:
    """Index ``output_set`` (the pinned current accepted set) under its pinned promise revisions.

    ``candidates`` are finalized revisions of the run (any status); those that are not the head
    of their deliverable are listed per promise with their label, newest revision per deliverable.
    """

    outputs: dict[str, ExactOutput] = {item.revision_id: item for item in output_set.members}
    head_ids = set(outputs)
    promises: list[IndexPromise] = []
    for obligation in obligations:
        mine = [m for m in output_set.members if m.obligation_key == obligation.key]
        heads = tuple(
            _revision(
                obligation, item, assessments, "accepted", trusted_validators, member_decisions
            )
            for item in sorted(mine, key=lambda m: m.deliverable_id)
        )
        newest: dict[str, ExactOutput] = {}
        for item in candidates:
            if item.obligation_key != obligation.key or item.revision_id in head_ids:
                continue
            prior = newest.get(item.deliverable_id)
            if prior is None or item.revision > prior.revision:
                newest[item.deliverable_id] = item
        listed = tuple(
            _revision(
                obligation,
                newest[key],
                assessments,
                "candidate",
                trusted_validators,
                member_decisions,
            )
            for key in sorted(newest)
        )
        current = [h for h in heads if h.obligation_revision == obligation.revision]
        distinct = len({h.deliverable_id for h in current})
        gaps: list[str] = []
        if distinct < obligation.cardinality.min:
            gaps.append(
                f"{distinct} of at least {obligation.cardinality.min} distinct "
                "deliverables accepted"
            )
        if distinct > obligation.cardinality.max:
            gaps.append(
                f"{distinct} distinct deliverables exceed the maximum {obligation.cardinality.max}"
            )
        for head in current:
            if head.judgment != "pass":
                gaps.append(f"head {head.deliverable_id} stands {head.label}")
        missing: tuple[str, ...] = ()
        if obligation.contract.coverage is not None:
            missing = tuple(
                sorted(
                    set(obligation.contract.coverage.subjects)
                    - _covered(obligation, current, outputs)
                )
            )
            if missing:
                gaps.append("promised subjects not covered: " + ", ".join(missing))
        promises.append(
            IndexPromise(
                key=obligation.key,
                revision=obligation.revision,
                owner_position=obligation.owner_position,
                enforcement=obligation.enforcement.value,
                evaluation_scope=obligation.evaluation_scope.value,
                form=obligation.contract.form,
                cardinality={"min": obligation.cardinality.min, "max": obligation.cardinality.max},
                distinct_count=distinct,
                heads=heads,
                candidates=listed,
                missing_coverage=missing,
                gaps=tuple(item[:300] for item in gaps),
            )
        )
    return CurrentSetIndex(
        run_id=run_id,
        set_id=output_set.set_id,
        set_revision=output_set.revision,
        membership_digest=output_set.membership_digest,
        promises=tuple(promises),
    )


def current_set_input(purpose: str) -> TransferInput:
    """The receiver's required index binding: one exact file, sealed with its plan."""

    return TransferInput(
        name=CURRENT_SET_INPUT,
        source=InputSource.application(CURRENT_SET_BINDING, {"view": "goal"}),
        purpose=purpose,
        required=True,
        placement="file",
    )


def with_current_set_index(selection: TransferSelection, *, purpose: str) -> TransferSelection:
    """Add the index to a receiver that already receives produced outputs (a run with named
    promises and an admitted budget); any other selection is returned unchanged."""

    if selection.bounds is None or not any(
        item.source.kind == "produced_output" for item in selection.inputs
    ):
        return selection
    if any(item.name == CURRENT_SET_INPUT for item in selection.inputs):
        return selection
    return TransferSelection.model_validate(
        {
            **selection.model_dump(mode="python"),
            "inputs": (*selection.inputs, current_set_input(purpose)),
        }
    )


__all__ = [
    "CURRENT_SET_BINDING",
    "CURRENT_SET_FILE",
    "CURRENT_SET_INDEX_SCHEMA",
    "CURRENT_SET_INPUT",
    "CurrentSetIndex",
    "IndexMember",
    "IndexPromise",
    "IndexRevision",
    "build_current_set_index",
    "current_set_input",
    "with_current_set_index",
]
