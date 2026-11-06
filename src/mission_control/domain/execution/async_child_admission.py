"""Check-time admission of an async child's result into parent cognition (OVE-184).

OUTPUT-CONTRACTS §11: a parent's check/status path performs governed check-time result
admission so usable output reaches parent cognition; completion alone is not admission. §10:
technical result availability or check-time admission alone never fulfills the parent's
promise; only an explicit exact adoption offers the child's output to a parent obligation,
and the parent's own checks still decide it.

This module holds the closed result of one admission attempt, the `child_result_index`
entry an admitted result writes into the parent's state, and the exact derivation reference
an adoption carries. Pure: no provider, no database, no clock.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import AwareDatetime, Field, model_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    DIGEST_PATTERN,
    AsyncSubagentExecution,
    Contract,
    ParentAsyncSubagentLink,
)

ChildAdmissionStatus = Literal["admitted", "pending", "refused"]
ResultDecision = Literal["admit", "conditionally_admit", "reject", "defer"]
AdmittedBy = Literal["check_time", "parent_boundary"]

ADMITTED_DECISIONS: Final = frozenset({"admit", "conditionally_admit"})
ADOPTION_REF_PREFIX: Final = "async-child-result:"
CHILD_RESULT_INDEX_SCHEMA: Final = "belllabs.child-result-index-entry.v1"

# Why a check could not admit (yet). `pending_*` keep the child undecided; the rest are final
# for this parent (a refused child's text never reaches its cognition).
PendingReason = Literal[
    "child_active",
    "child_in_doubt",
    "admission_policy_not_registered",
]
RefusedReason = Literal[
    "audience_mismatch",
    "contract_digest_mismatch",
    "no_result",
    "decision_rejected",
    "decision_deferred",
    "manifest_mismatch",
    "late_result",
]


class ChildResultIndexEntry(Contract):
    """One admitted child result, as the parent's `child_result_index` channel records it.

    ``id`` is the child execution id, so the channel's `append_unique_by_id` reducer keeps
    exactly one entry per child however often the parent checks it (no duplicate admission).
    """

    schema_version: Literal["belllabs.child-result-index-entry.v1"] = CHILD_RESULT_INDEX_SCHEMA
    id: str = Field(min_length=1)
    child_name: str = Field(min_length=1)
    contract_digest: str = Field(pattern=DIGEST_PATTERN)
    manifest_digest: str = Field(pattern=DIGEST_PATTERN)
    output_ref: str = Field(min_length=1)
    output_digest: str = Field(pattern=DIGEST_PATTERN)
    checkpoint_ref: str = Field(min_length=1)
    usage_ref: str = Field(min_length=1)
    decision: Literal["admit", "conditionally_admit"]
    admitted_by: AdmittedBy
    adoption_ref: str = Field(min_length=1)


class ChildAdmission(Contract):
    """The closed outcome of one governed admission attempt for one child."""

    status: ChildAdmissionStatus
    child_execution_id: str = Field(min_length=1)
    lifecycle: str = Field(min_length=1)
    reason: PendingReason | RefusedReason | None = None
    decision: ResultDecision | None = None
    # True only for the attempt that recorded the decision; a later check reads it back.
    newly_decided: bool = False
    entry: ChildResultIndexEntry | None = None
    output_text: str | None = Field(default=None, max_length=200_000)
    decided_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def admitted_carries_its_result(self) -> ChildAdmission:
        admitted = self.status == "admitted"
        if admitted != (self.entry is not None) or admitted != (self.output_text is not None):
            raise ValueError("exactly an admitted child carries its index entry and text")
        if admitted and self.decision not in ADMITTED_DECISIONS:
            raise ValueError("an admitted child carries an admitting decision")
        if not admitted and self.reason is None:
            raise ValueError("a pending or refused admission names its reason")
        return self


def adoption_ref(child_execution_id: str, manifest_digest: str) -> str:
    """The exact derivation reference an adopted child output carries into a submission."""

    return f"{ADOPTION_REF_PREFIX}{child_execution_id}@{manifest_digest}"


def parse_adoption_ref(value: str) -> tuple[str, str] | None:
    """``(child_execution_id, manifest_digest)`` of an adoption reference, else ``None``."""

    if not value.startswith(ADOPTION_REF_PREFIX):
        return None
    child, separator, digest = value.removeprefix(ADOPTION_REF_PREFIX).rpartition("@")
    if not separator or not child or not digest.startswith("sha256:"):
        return None
    return child, digest


def child_result_index_entry(
    execution: AsyncSubagentExecution,
    link: ParentAsyncSubagentLink,
    *,
    child_name: str,
    admitted_by: AdmittedBy,
) -> ChildResultIndexEntry:
    """The index entry of an admitted child; refuses anything that is not exactly admitted."""

    manifest = execution.result_manifest
    if manifest is None or execution.result_output_text is None:
        raise ValueError("only a completed child with its result text is indexed")
    decision = link.result_decision
    if decision != "admit" and decision != "conditionally_admit":
        raise ValueError("only an admitted child result is indexed")
    if link.admitted_manifest_digest != manifest.manifest_digest:
        raise ValueError("the admitted manifest is not the child's result manifest")
    output_digest = sha256_digest(execution.result_output_text)
    if manifest.output_refs[:1] != ("ref:async-output:" + output_digest.removeprefix("sha256:"),):
        raise ValueError("the child's result text is not the manifest's output")
    return ChildResultIndexEntry(
        id=execution.child_execution_id,
        child_name=child_name,
        contract_digest=execution.contract_digest,
        manifest_digest=manifest.manifest_digest,
        output_ref=manifest.output_refs[0],
        output_digest=output_digest,
        checkpoint_ref=manifest.checkpoint_ref,
        usage_ref=manifest.usage_ref,
        decision=decision,
        admitted_by=admitted_by,
        adoption_ref=adoption_ref(execution.child_execution_id, manifest.manifest_digest),
    )


__all__ = [
    "ADMITTED_DECISIONS",
    "ADOPTION_REF_PREFIX",
    "AdmittedBy",
    "ChildAdmission",
    "ChildAdmissionStatus",
    "ChildResultIndexEntry",
    "PendingReason",
    "RefusedReason",
    "ResultDecision",
    "adoption_ref",
    "child_result_index_entry",
    "parse_adoption_ref",
]
