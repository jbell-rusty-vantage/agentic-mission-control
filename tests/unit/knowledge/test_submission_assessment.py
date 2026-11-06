"""M03 minimal assessment handoff (SPRINT-V-DESIGN §8, NEXT-SESSION checkpoint E).

Final submission triggers the independent ``report.assess`` under the host; the submission
records the remote handle (``pending -> assessing``); the finalization distinguishes coverage
from an assessed verdict; an assessment still running at finalize survives a restart in the
durable handle store and settles later.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta

import pytest

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.outputs.submission_service import (
    OutputSelection,
    SelectedItem,
    SubmissionService,
)
from tests.fixtures.knowledge_binding import (
    AUDIENCE,
    BINDING,
    FakeKnowledgeBinding,
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    InMemorySubmissionStore,
    Issuer,
    RecordingMinter,
    SteppingClock,
    knowledge_port,
    report_package,
)
from tests.unit.knowledge.test_gateway import TENANT, origin


@pytest.mark.parametrize(
    "members",
    [
        ("good", "held"),
        ("held", "good"),
        ("good", "rejected"),
        ("rejected", "good"),
        ("good", "good"),
        ("good", "path"),
    ],
)
async def test_report_collection_is_refused_before_persistence(members: tuple[str, ...]) -> None:
    h = handoff()
    items = tuple(
        SelectedItem(kind="path", ref="/outputs/notes.md", digest="sha256:" + "a" * 64)
        if name == "path"
        else report_selection(name).items[0]
        for name in members
    )
    with pytest.raises(ValueError, match="report must be the only selected item"):
        await h.service().submit(h.access(), "report", OutputSelection(items=items), "collection")
    assert not h.store.rows
    assert not h.fake.calls_of("invoke")


async def test_rejected_collection_revision_preserves_the_previous_selection() -> None:
    h = handoff()
    service, access = h.service(), h.access()
    first = await service.submit(access, "report", report_selection("good"), "first")
    with pytest.raises(ValueError, match="report must be the only selected item"):
        await service.submit(
            access,
            "report",
            OutputSelection(
                items=(
                    *report_selection("good").items,
                    *report_selection("revised").items,
                )
            ),
            "revision",
        )
    assert list(h.store.rows.values()) == [first]
    revised = await service.submit(access, "report", report_selection("revised"), "revision")
    assert revised.revision == 2
    h.fake.operation_statuses["report.assess"] = deque(["succeeded"])
    await service.finalize(access.identity(("report",)), access)
    (call,) = h.fake.calls_of("invoke")
    assert call.envelope is not None and call.envelope.input is not None
    assert call.envelope.input.upstream[0].id == "revised"


@pytest.mark.parametrize("with_assessor", [True, False])
async def test_stored_unsupported_collection_cannot_finalize(with_assessor: bool) -> None:
    from dataclasses import replace

    h = handoff()
    service = h.service() if with_assessor else SubmissionService(h.store)
    access = h.access()
    first = await service.submit(access, "report", report_selection("good"), "first")
    # Simulate a record admitted by the pre-repair writer, including its invalid verdict.
    h.store.rows[first.submission_id] = replace(
        first,
        assessment_state="assessed",
        selection={
            "items": [
                report_selection(name).items[0].model_dump() for name in ("good", "unchecked")
            ],
        },
    )
    with pytest.raises(ValueError, match="report must be the only selected item"):
        await service.finalize(access.identity(("report",)), access)
    assert not h.store.finalizations and not h.fake.calls_of("invoke")


async def test_path_collection_remains_coverage_only() -> None:
    h = handoff()
    access, service = h.access(), h.service()
    await service.submit(
        access,
        "files",
        OutputSelection(
            items=tuple(
                SelectedItem(kind="path", ref=f"/outputs/{name}.md", digest="sha256:" + "a" * 64)
                for name in ("one", "two")
            )
        ),
        "files",
    )
    report = await service.finalize(access.identity(("files",)), access)
    assert report.outcome_basis == "declared_obligations" and report.outcome == "unfulfilled"
    assert not h.fake.calls_of("invoke")


@dataclass
class Handoff:
    clock: SteppingClock
    fake: FakeKnowledgeBinding
    handles: InMemoryKnowledgeHandleStore
    store: InMemorySubmissionStore
    issuer: Issuer

    def gateway(self, max_polls: int = 3) -> KnowledgeGateway:
        async def sleep(_seconds: float) -> None:
            return None

        return KnowledgeGateway(
            client=self.fake,
            journal=InMemoryKnowledgeJournal(),
            handles=self.handles,
            minter=RecordingMinter(self.issuer.minter()),
            knowledge=knowledge_port(BINDING),
            audience=AUDIENCE,
            max_polls=max_polls,
            clock=self.clock,
            sleep=sleep,
        )

    def service(self, max_polls: int = 3) -> SubmissionService:
        return SubmissionService(self.store, assessor=self.gateway(max_polls), clock=self.clock)

    def access(self) -> InvocationAccess:
        return InvocationAccess(
            origin=origin(operation_id="op-draft-1"),
            subject="mission-control-runtime",
            invocation_id="inv-draft-1",
            authenticated_at=self.clock.now,
        )


def handoff() -> Handoff:
    clock = SteppingClock(step=timedelta(milliseconds=1))
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    return Handoff(clock, fake, InMemoryKnowledgeHandleStore(), InMemorySubmissionStore(), issuer)


def report_selection(report_id: str = "report-7") -> OutputSelection:
    package = report_package(report_id, "1", tenant=TENANT)
    report = package.report
    return OutputSelection(
        items=(
            SelectedItem(
                kind="handle",
                ref=f"kh:{report.binding}/report/{report.id}@{report.version}",
                digest=report.digest,
            ),
        )
    )


async def test_final_submission_triggers_the_independent_assessment() -> None:
    h = handoff()
    h.fake.operation_statuses["report.assess"] = deque(["running", "succeeded"])
    service = h.service()
    access = h.access()
    submitted = await service.submit(access, "report", report_selection(), "tool-call-1")
    assert submitted.assessment_state == "pending"

    report = await service.finalize(access.identity(("report",)), access)

    (start,) = [call for call in h.fake.calls_of("invoke") if call.envelope is not None]
    assert start.envelope is not None and start.envelope.operation == "report.assess"
    assert start.envelope.requestId == f"assess:{submitted.submission_id}"
    assert start.envelope.input is not None
    assert start.envelope.input.upstream[0].id == "report-7"
    # The producer never claims its own assessment: the host started it under its credential.
    assert start.claims.operations == ["report.assess"] and start.claims.effect is None
    stored = h.store.rows[submitted.submission_id]
    assert stored.assessment_state == "assessed"
    (handle,) = h.handles.rows.values()
    assert stored.assessment_operation_id == handle.handle.operationId
    assert stored.assessment_binding == BINDING and handle.state == "succeeded"
    assert handle.subject_ref == f"submission:{submitted.submission_id}"
    assert report.outcome_basis == "assessed" and report.outcome == "fulfilled"
    (obligation,) = report.obligations
    assert obligation.covered and obligation.assessed
    assert obligation.assessment is not None and obligation.assessment.state == "assessed"
    assert obligation.assessment.verdict_ref is not None


async def test_coverage_is_not_an_assessment_and_a_running_assessment_survives_restart() -> None:
    h = handoff()
    h.fake.operation_statuses["report.assess"] = deque(["running", "running", "held"])
    access = h.access()
    service = h.service(max_polls=1)
    submitted = await service.submit(access, "report", report_selection(), "tool-call-1")

    report = await service.finalize(access.identity(("report",)), access)
    # Coverage is not fulfillment: a submitted row without a verdict fulfills nothing.
    assert report.outcome_basis == "declared_obligations" and report.outcome == "unfulfilled"
    (obligation,) = report.obligations
    assert obligation.covered and not obligation.assessed
    assert obligation.assessment is not None and obligation.assessment.state == "assessing"
    assert report.open_assessments == (obligation.assessment.operation_id,)

    # Restart: a new service and gateway over the same durable stores settle it later.
    later = h.service(max_polls=3)
    (refreshed,) = await later.refresh_assessments(access.identity(("report",)), access)
    assert refreshed.assessed and refreshed.assessment is not None
    assert refreshed.assessment.state == "held"
    assert h.store.rows[submitted.submission_id].assessment_state == "held"
    assert len([c for c in h.fake.calls_of("invoke") if c.envelope is not None]) == 1


async def test_path_selections_stay_coverage_and_a_refused_start_stays_pending() -> None:
    h = handoff()
    access = h.access()
    service = h.service()
    path = OutputSelection(
        items=(SelectedItem(kind="path", ref="/outputs/notes.md", digest="sha256:" + "c" * 64),)
    )
    await service.submit(access, "notes", path, "tool-call-1")
    h.fake.invoke_script.clear()
    report = await service.finalize(access.identity(("notes",)), access)
    assert report.outcome_basis == "declared_obligations"
    assert h.fake.calls_of("invoke") == []

    refused = handoff()
    refused_access = refused.access()
    refused_service = refused.service()
    submitted = await refused_service.submit(
        refused_access, "report", report_selection("report-9"), "tool-call-1"
    )
    refused.fake.verifier = refused.issuer.verifier(audience="another-executor")
    report = await refused_service.finalize(refused_access.identity(("report",)), refused_access)
    assert refused.store.rows[submitted.submission_id].assessment_state == "pending"
    assert report.outcome_basis == "declared_obligations"
