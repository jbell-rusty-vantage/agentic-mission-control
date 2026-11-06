"""M03 report package extension seam: exact resolution (SPRINT-V-DESIGN §9 row "M03/M04").

Exact resolve of one selected report revision over the verifying fake binding (real Ed25519
credentials). Cases: adoption is not production, an ambiguous bare id, a file/report mismatch,
a partial package, a missing exact revision, full digests, and the executor artifacts route.
Placement, delivery, receipts and readiness belong to the one transfer materializer (WI-02):
``tests/unit/context/test_transfer_plan.py`` and ``test_transfer_materializer.py``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta

import pytest

from mission_control.application.context.resolution import (
    ContentResolutionService,
    ResolutionRefused,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.outputs.submission_service import (
    OutputSelection,
    SelectedItem,
    SubmissionService,
)
from mission_control.contracts.knowledge_protocol import digest_bytes
from mission_control.domain.knowledge.lineage import (
    ADOPTION_ACT,
    ActorKind,
    LineageFact,
    ProvenanceRole,
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
    StoredPackage,
    knowledge_port,
    report_package,
)
from tests.unit.knowledge.test_gateway import TENANT, origin


@dataclass
class Seam:
    clock: SteppingClock
    fake: FakeKnowledgeBinding
    gateway: KnowledgeGateway
    resolver: ContentResolutionService
    package: StoredPackage

    def access(self, attempt: int = 1, operation: str = "op-review-1") -> InvocationAccess:
        return InvocationAccess(
            origin=origin(attempt, operation_id=operation),
            subject="mission-control-runtime",
            invocation_id="inv-review-1",
            authenticated_at=self.clock.now,
        )

    def item(self, package: StoredPackage | None = None) -> SelectedItem:
        report = (package or self.package).report
        return SelectedItem(
            kind="handle",
            ref=f"kh:{report.binding}/report/{report.id}@{report.version}",
            digest=report.digest,
        )


def seam() -> Seam:
    clock = SteppingClock(step=timedelta(milliseconds=1))
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    fake.operation_statuses["knowledge.read"] = deque(["succeeded"] * 8)
    package = fake.register_package(report_package("report-7", "1", tenant=TENANT))
    gateway = KnowledgeGateway(
        client=fake,
        journal=InMemoryKnowledgeJournal(),
        handles=InMemoryKnowledgeHandleStore(),
        minter=RecordingMinter(issuer.minter()),
        content=fake,
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=clock,
        sleep=_no_sleep,
    )
    return Seam(clock, fake, gateway, ContentResolutionService(gateway), package)


async def _no_sleep(_seconds: float) -> None:
    return None


async def test_full_digests_resolve_the_exact_selected_revision_with_its_purpose() -> None:
    s = seam()
    resolved = await s.resolver.resolve(s.item(), s.access(), purpose="evaluation_subject")
    assert resolved.body == s.package.body and resolved.ledger == s.package.ledger
    assert resolved.body_digest == digest_bytes(s.package.body)
    # The read was an exact-revision knowledge.read whose result is the package manifest.
    (read,) = [call for call in s.fake.calls_of("invoke") if call.envelope is not None]
    assert read.envelope is not None and read.envelope.operation == "knowledge.read"
    assert read.envelope.input is not None
    assert read.envelope.input.upstream == [s.package.report]
    # readSelected: the receiver's admitted purpose travels with the exact report.
    payload = read.envelope.input.inlinePayload
    assert isinstance(payload, dict) and payload["purpose"] == "evaluation_subject"


async def test_resolution_names_consumption_and_adoption_is_never_production() -> None:
    """A resolved report is a consumer + revision fact of the receiver (the materializer
    persists consumption only for a ready receipt); a producer fact never carries adoption."""

    s = seam()
    resolved = await s.resolver.resolve(s.item(), s.access())
    roles = {fact.role for fact in resolved.provenance}
    assert roles == {ProvenanceRole.CONSUMER, ProvenanceRole.REVISION}
    with pytest.raises(ValueError, match="producer"):
        LineageFact(
            subject_handle=resolved.handle,
            role=ProvenanceRole.PRODUCER,
            actor_kind=ActorKind.ORIGIN,
            actor_ref="mc-inv:review",
            actor_origin=s.access().origin,
            fact={"act": ADOPTION_ACT},
        )


async def test_an_ambiguous_bare_id_is_refused_and_never_submitted() -> None:
    s = seam()
    bare = SelectedItem(kind="handle", ref="report-7", digest=s.package.report.digest)
    with pytest.raises(ResolutionRefused) as refused:
        await s.resolver.resolve(bare, s.access())
    assert refused.value.code == "AMBIGUOUS_HANDLE"
    service = SubmissionService(InMemorySubmissionStore())
    with pytest.raises(ValueError, match="exact handle"):
        await service.submit(s.access(), "report", OutputSelection(items=(bare,)), "call-1")
    assert s.fake.calls == []


async def test_a_selected_file_that_is_not_the_report_body_is_refused() -> None:
    s = seam()
    with pytest.raises(ResolutionRefused) as refused:
        await s.resolver.resolve(
            s.item(), s.access(), companion_file_digest=digest_bytes(b"an edited copy")
        )
    assert refused.value.code == "REPORT_FILE_MISMATCH"
    resolved = await s.resolver.resolve(
        s.item(), s.access(), companion_file_digest=digest_bytes(s.package.body)
    )
    assert resolved.body_digest == digest_bytes(s.package.body)


async def test_a_missing_exact_revision_is_refused() -> None:
    s = seam()
    unknown = report_package("report-7", "2", tenant=TENANT, body=b"# a newer revision\n")
    with pytest.raises(ResolutionRefused) as refused:
        await s.resolver.resolve(s.item(unknown), s.access())
    assert refused.value.code == "EXACT_REVISION_UNAVAILABLE"


async def test_a_partial_package_is_refused() -> None:
    s = seam()
    truncated = report_package("report-8", "1", tenant=TENANT)
    truncated.served_body = truncated.body[:-3]  # the manifest still declares the full size
    s.fake.register_package(truncated)
    with pytest.raises(ResolutionRefused) as refused:
        await s.resolver.resolve(s.item(truncated), s.access())
    assert refused.value.code == "PARTIAL_PACKAGE"


async def test_selected_members_are_exact_and_refusals_stay_typed() -> None:
    """readSelected members mode: only the selected handles come back with their records; an
    undeclared purpose or a handle whose digest is not this revision's member refuses."""

    s = seam()
    (handle, record), *_ = s.package.member_handles("assertion")
    members = await s.resolver.resolve(
        s.item(), s.access(), purpose="evaluation_evidence", assertions=(handle,)
    )
    assert [item.handle for item in members.package.assertions] == [handle]
    assert members.package.assertions[0].record == record
    assert members.body == b"" and members.package.body is None
    stale = handle.model_copy(update={"digest": "sha256:" + "1" * 64})
    with pytest.raises(ResolutionRefused) as mismatch:
        await s.resolver.resolve(s.item(), s.access(), assertions=(stale,), attempt_key="m")
    assert mismatch.value.cause == "EXACT_REVISION_UNAVAILABLE" or (
        mismatch.value.code == "EXACT_REVISION_UNAVAILABLE"
    )
    s.fake.read_purposes = frozenset({"dependent_input"})
    with pytest.raises(ResolutionRefused) as undeclared:
        await s.resolver.resolve(s.item(), s.access(), purpose="evaluation_subject")
    assert undeclared.value.code == "READ_REFUSED"


async def test_exact_bytes_travel_over_the_executor_artifacts_route() -> None:
    """The HTTP client and `HttpExactContentReader` (executor `artifacts/{id}?digest=`)
    deliver the same exact package as the in-process reader; a wrong digest refuses."""

    from mission_control.adapters.knowledge.http_client import HttpExactContentReader
    from tests.fixtures.knowledge_binding import http_client_over

    s = seam()
    http = http_client_over(s.fake)
    gateway = KnowledgeGateway(
        client=http,
        journal=InMemoryKnowledgeJournal(),
        handles=InMemoryKnowledgeHandleStore(),
        minter=s.gateway._minter,
        content=HttpExactContentReader(http),
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=s.clock,
        sleep=_no_sleep,
    )
    resolved = await ContentResolutionService(gateway).resolve(s.item(), s.access())
    assert resolved.body == s.package.body and resolved.ledger == s.package.ledger
    from mission_control.application.ports.knowledge import KnowledgeProtocolRefusal

    with pytest.raises(KnowledgeProtocolRefusal) as refused:
        await http.artifact(s.package.result_ref.id, "sha256:" + "0" * 64, "not-a-token")
    assert refused.value.error.code == "SCOPE_DENIED"
