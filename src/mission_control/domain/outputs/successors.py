"""Governed output-contract successors and missing-submission association (OUTPUT-CONTRACTS §3).

A successor names its expected prior revision; tightening is admitted on ordinary authority,
any weakening needs explicit delegated weakening authority and can never be self-waived by
an executor. Activation is a compare-and-set at a recorded safe future boundary; in-flight
frontiers keep their pinned revision. Transfer successors are a typed seam for WI-02.

The association rule gives a missing required submission one reminder, then auto-associates
only one unambiguous registered candidate or exact named-capability receipt, then allows one
ambiguity repair before blocking. It never searches arbitrary workspace outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.authoring.canonical import stable_json_dump
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    OutputObligation,
    tagged_digest,
)

SAFE_BOUNDARIES: Final = frozenset(
    {"before_activation", "between_iterations", "between_stages", "before_invocation"}
)


class SuccessorInvalid(ValueError):
    """The proposal does not describe a successor of the named obligation."""


class TransferSuccessorSeam(BaseModel):
    """Typed seam: a transfer-policy successor travels with a contract successor (WI-02)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transfer_policy_ref: str = Field(min_length=1)
    expected_prior_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ContractRevisionProposal(BaseModel):
    """A governed output-contract revision: who, why, under what authority, and when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    obligation_key: str = Field(min_length=1)
    expected_prior_revision: int = Field(ge=1)
    successor: OutputObligation
    actor_id: str = Field(min_length=1)
    actor_role: Literal["author", "operator", "coordinator", "executor"]
    reason: str = Field(min_length=1, max_length=2000)
    # Every proposal records the delegation it acts under (who authorised the author).
    delegation_ref: str = Field(min_length=1)
    weakening_authority_ref: str | None = Field(default=None, min_length=1)
    boundary: str = Field(min_length=1)
    boundary_ref: str = Field(min_length=1)
    affected_work: tuple[str, ...] = ()
    transfer_successor: TransferSuccessorSeam | None = None

    def document(self) -> dict[str, object]:
        return stable_json_dump(self, exclude={"successor"}) | {
            "successor_digest": self.successor.digest
        }

    @property
    def digest(self) -> str:
        return tagged_digest("mc.contract_revision_proposal.v1", self.document())


@dataclass(frozen=True)
class SuccessorChange:
    weakenings: tuple[str, ...]
    tightenings: tuple[str, ...]

    @property
    def weakens(self) -> bool:
        return bool(self.weakenings)


def classify_successor(prior: OutputObligation, successor: OutputObligation) -> SuccessorChange:
    """Which promised layers the successor weakens or tightens (form/key/owner are fixed).

    Fail closed: only recognised tightenings (stronger enforcement, a higher minimum or lower
    maximum cardinality, added required requirements, added coverage subjects under the same
    pointer and key) are tightenings; every other difference anywhere in the obligation
    (scope, identity rule, text checks, templates, schema ref/digest/body, coverage pointer or
    key, nested guarantees, media type, repository, receipt capabilities) is a weakening.
    """

    if successor.key != prior.key or successor.owner_position != prior.owner_position:
        raise SuccessorInvalid("a successor keeps the obligation key and owner position")
    if successor.revision != prior.revision + 1:
        raise SuccessorInvalid(f"a successor of revision {prior.revision} is {prior.revision + 1}")
    if successor.form is not prior.form:
        raise SuccessorInvalid("a successor keeps the output form; declare a new obligation")
    old = prior.model_dump(mode="json", exclude={"revision"})
    new = successor.model_dump(mode="json", exclude={"revision"})
    weak: list[str] = []
    tight: list[str] = []
    before, after = prior.enforcement.strength, successor.enforcement.strength
    if after != before:
        (tight if after > before else weak).append(
            f"enforcement {prior.enforcement}->{successor.enforcement}"
        )
    new["enforcement"] = old["enforcement"]
    for bound, stronger in (("min", 1), ("max", -1)):
        delta = (new["cardinality"][bound] - old["cardinality"][bound]) * stronger
        if delta:
            (tight if delta > 0 else weak).append(f"cardinality.{bound} changed")
        new["cardinality"][bound] = old["cardinality"][bound]
    old_requirements = {item["key"]: item for item in old["contract"]["requirements"]}
    new_requirements = {item["key"]: item for item in new["contract"]["requirements"]}
    for key in sorted(old_requirements.keys() | new_requirements.keys()):
        was, now = old_requirements.get(key), new_requirements.get(key)
        if was == now:
            continue
        if was is None and now is not None and now["required"]:
            tight.append(f"requirement {key} added")
        else:
            weak.append(f"requirement {key} {'removed' if now is None else 'changed'}")
    new["contract"]["requirements"] = old["contract"]["requirements"]
    old_cov, new_cov = old["contract"]["coverage"], new["contract"]["coverage"]
    if old_cov != new_cov:
        if old_cov is None:
            tight.append("coverage added")
        elif new_cov is None or (old_cov["pointer"], old_cov["key"]) != (
            new_cov["pointer"],
            new_cov["key"],
        ):
            weak.append("coverage closure changed")
        else:
            removed = set(old_cov["subjects"]) - set(new_cov["subjects"])
            added = set(new_cov["subjects"]) - set(old_cov["subjects"])
            if removed:
                weak.append("coverage subjects removed")
            if added:
                tight.append("coverage subjects added")
    new["contract"]["coverage"] = old_cov
    for field in sorted(set(old) | set(new)):
        if field == "contract":
            continue
        if old.get(field) != new.get(field):
            weak.append(f"{field} changed")
    for field in sorted(set(old["contract"]) | set(new["contract"])):
        if old["contract"].get(field) != new["contract"].get(field):
            weak.append(f"contract.{field} changed")
    return SuccessorChange(tuple(weak), tuple(tight))


class WeakeningGrant(BaseModel):
    """Explicit delegated authority to weaken one run's promise (or every promise of the run)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    obligation_key: str | None = None

    def covers(self, scope: str, run_id: str, obligation_key: str) -> bool:
        return (
            self.scope == scope
            and self.run_id == run_id
            and self.obligation_key in {None, obligation_key}
        )


# ---------------------------------------------------------------- missing-submission association

AssociationStep = Literal["reminder", "auto_associated", "repair_requested", "blocked"]


class RegisteredCandidate(BaseModel):
    """A candidate the host registered for this invocation (never a workspace search hit)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: CandidateRef
    source: Literal["registered_output", "named_capability_receipt"]
    capability_ref: str | None = None


@dataclass(frozen=True)
class AssociationDecision:
    action: Literal["remind", "associate", "request_repair", "block"]
    candidate: CandidateRef | None = None
    ambiguous: tuple[CandidateRef, ...] = ()


def next_association(
    taken: frozenset[str], matching: tuple[RegisteredCandidate, ...]
) -> AssociationDecision:
    """One reminder, one unambiguous auto-association, one ambiguity repair, then block."""

    if "blocked" in taken or "auto_associated" in taken or "repair_requested" in taken:
        # The association was tried (or the one repair was granted) and the promise is still
        # unmet: it stays unmet and blocks; no second reminder, guess or repair.
        return AssociationDecision("block")
    if "reminder" not in taken:
        return AssociationDecision("remind")
    if len(matching) == 1:
        return AssociationDecision("associate", candidate=matching[0].candidate)
    if not matching:
        return AssociationDecision("block")
    return AssociationDecision(
        "request_repair", ambiguous=tuple(item.candidate for item in matching)
    )


__all__ = [
    "SAFE_BOUNDARIES",
    "AssociationDecision",
    "AssociationStep",
    "ContractRevisionProposal",
    "RegisteredCandidate",
    "SuccessorChange",
    "SuccessorInvalid",
    "TransferSuccessorSeam",
    "WeakeningGrant",
    "classify_successor",
    "next_association",
]
