"""Explicit exact adoption of an admitted async child output (OVE-184; OUTPUT-CONTRACTS §10).

An ordinary helper has no output obligation, and check-time admission only makes a child's
result usable in the parent's cognition. When the parent wants that exact output to count
toward one of its own promises, it adopts it explicitly: :meth:`AsyncChildOutputAdoption.adopt`
offers the admitted bytes, unchanged, as one inline candidate of the parent's ordinary
``SubmitOutput@2`` act, with the exact derivation reference
``async-child-result:<child>@<manifest digest>``. The parent's submission checks (pinned promise,
form, schema, cardinality, head) decide it like any other candidate and its assessment and
fulfillment stay the parent's; nothing here records an assessment or a fulfillment, and the
child's provenance is preserved as the derivation, never rewritten as the parent's production.

Refusals are closed: a child that is not this parent's, not admitted, or whose admitted
manifest no longer names these exact bytes is never offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.subordinates.service import (
    AsyncSubagentError,
    AsyncSubagentService,
)
from mission_control.domain.execution.async_child_admission import child_result_index_entry
from mission_control.domain.execution.contracts import OperationExecutionBinding
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    OutputObligation,
    SubmissionAck,
    SubmitOutput,
)
from mission_control.domain.outputs.rules import text_digest

AdoptionRefusalCode = Literal[
    "CHILD_UNKNOWN",
    "AUDIENCE_MISMATCH",
    "NOT_ADMITTED",
    "MANIFEST_MISMATCH",
    "OBLIGATION_UNDECLARED",
]


class OutputSubmissionPort(Protocol):
    """The parent's ordinary submission act (``OutputSubmissionService``)."""

    async def pinned_obligation(
        self, access: InvocationAccess, obligation_key: str
    ) -> OutputObligation | None: ...

    async def submit_output(
        self, access: InvocationAccess, request: SubmitOutput, *, position: str | None
    ) -> SubmissionAck: ...


@dataclass(frozen=True)
class AdoptionRefused:
    code: AdoptionRefusalCode
    message: str


@dataclass(frozen=True)
class AdoptionResult:
    """The parent's ordinary submission acknowledgement plus the exact derivation it carried."""

    ack: SubmissionAck
    derivation_ref: str
    output_digest: str


class AsyncChildOutputAdoption:
    def __init__(self, service: AsyncSubagentService, submissions: OutputSubmissionPort) -> None:
        self._service = service
        self._submissions = submissions

    async def adopt(
        self,
        parent: OperationExecutionBinding,
        *,
        access: InvocationAccess,
        position: str | None,
        child_execution_id: str,
        child_name: str,
        obligation_key: str,
        deliverable_id: str | None,
        submission_key: str,
    ) -> AdoptionResult | AdoptionRefused:
        scope = parent.request_scope
        try:
            execution = await self._service.execution(scope, child_execution_id)
            link = await self._service.link(scope, child_execution_id)
        except AsyncSubagentError:
            return AdoptionRefused("CHILD_UNKNOWN", "no async child with that task id")
        if execution.parent_run_id != parent.run_id or (
            execution.parent_binding_id != parent.binding_id
        ):
            return AdoptionRefused("AUDIENCE_MISMATCH", "the child belongs to another parent")
        if link.result_decision not in {"admit", "conditionally_admit"}:
            return AdoptionRefused(
                "NOT_ADMITTED", "only an admitted child result can be adopted; check it first"
            )
        try:
            entry = child_result_index_entry(
                execution, link, child_name=child_name, admitted_by="check_time"
            )
        except ValueError as error:
            return AdoptionRefused("MANIFEST_MISMATCH", str(error))
        obligation = await self._submissions.pinned_obligation(access, obligation_key)
        if obligation is None:
            return AdoptionRefused(
                "OBLIGATION_UNDECLARED",
                f"no admitted promise {obligation_key} is pinned for this invocation",
            )
        text = execution.result_output_text
        assert text is not None  # child_result_index_entry refuses a child without its text
        digest = text_digest(text)
        request = SubmitOutput(
            submission_key=submission_key,
            obligation_key=obligation_key,
            items=(
                CandidateRef(
                    deliverable_id=deliverable_id or obligation.key.rsplit(".", 1)[-1],
                    form=obligation.form,
                    kind="inline",
                    digest=digest,
                    text=text,
                ),
            ),
            derivation_refs=(entry.adoption_ref,),
        )
        ack = await self._submissions.submit_output(access, request, position=position)
        return AdoptionResult(ack=ack, derivation_ref=entry.adoption_ref, output_digest=digest)


__all__ = [
    "AdoptionRefused",
    "AdoptionResult",
    "AsyncChildOutputAdoption",
    "OutputSubmissionPort",
]
