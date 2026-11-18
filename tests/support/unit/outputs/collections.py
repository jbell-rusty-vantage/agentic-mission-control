"""Builders, constants and fakes that other test files import.

Moved from tests/unit/outputs/test_collections.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.outputs.contracts import (
    CandidateRef,
    CoverageContract,
    MemberRef,
    OutputForm,
    OutputObligation,
    Requirement,
    collection_digest,
)
from tests.unit.outputs.scenario import digest_of, obligation

# A host-checkable member validator; the trusted-judgment pin is proven only by KS (review B2).
VERIFIED = Requirement(key="verified", validator="mc.check.member-verified@1", subject="member")
TRUSTED_PIN = "knowledge.report.assess@1"


def report(name: str) -> MemberRef:
    return MemberRef(
        ref=f"kh:aiengineer-postgres/report/{name}@research_report.v2", digest=digest_of(name)
    )


def collection(
    deliverable: str = "reports",
    members: tuple[MemberRef, ...] = (),
    *,
    subjects: dict[str, str] | None = None,
) -> CandidateRef:
    value: Any = None
    if subjects is not None:
        value = {
            "entries": [
                {"ref": item.ref, "digest": item.digest, "subject": subjects[item.ref]}
                for item in members
                if item.ref in subjects
            ]
        }
    return CandidateRef(
        deliverable_id=deliverable,
        form=OutputForm.COLLECTION,
        kind="inline",
        value=value if value is not None else {"kind": "report_collection"},
        members=members,
        digest=collection_digest(
            members, value if value is not None else {"kind": "report_collection"}
        ),
    )


def collection_promise(
    *,
    aggregate: dict[str, Any] | None = None,
    coverage: CoverageContract | None = None,
    validator: str | None = None,
    required: bool = True,
) -> OutputObligation:
    requirement = VERIFIED.model_copy(
        update={
            "parameters": aggregate or {},
            "validator": validator or VERIFIED.validator,
            "required": required,
        }
    )
    return obligation(
        "draft.reports",
        OutputForm.COLLECTION,
        requirements=(requirement,),
        coverage=coverage,
    )
