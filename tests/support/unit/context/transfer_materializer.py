"""Builders, constants and fakes that other test files import.

Moved from tests/unit/context/test_transfer_materializer.py.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from mission_control.adapters.knowledge.memory import (
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    InMemoryLineageStore,
    InMemoryTransferPlanStore,
)
from mission_control.application.context.materialization import (
    ApplicationSelectorResolver,
    ArtifactResolver,
    KnowledgeReadAccess,
    LiteralResolver,
    MaterializeRequest,
    ProducedOutputResolver,
    TransferMaterializer,
)
from mission_control.application.context.pack_service import ArtifactContent
from mission_control.application.context.resolution import ContentResolutionService
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.domain.context.transfer import (
    BackendCapabilities,
    Boundary,
    HostOverhead,
    InputSource,
    ReceiverAttempt,
    ReceiverRef,
    ResourceBounds,
    TransferInput,
    TransferSelection,
)
from mission_control.domain.outputs.contracts import (
    Assessment,
    ExactOutput,
    OutputContract,
    OutputForm,
    OutputObligation,
)
from tests.support.knowledge.binding import FakeKnowledgeBinding
from tests.support.knowledge.content import StoredPackage, report_package
from tests.support.knowledge.credentials import (
    AUDIENCE,
    BINDING,
    Issuer,
    RecordingMinter,
    SteppingClock,
    knowledge_port,
)
from tests.support.knowledge.gateway import TENANT, origin
from tests.support.knowledge.stores import InMemoryStaging

RUN = "22222222-2222-4222-8222-222222222222"
OVERHEAD = HostOverhead(host_state_tokens=800, tool_schema_tokens=400, skill_tokens=100)
SANDBOX = BackendCapabilities(custody_backend="mc-custody", file_capable=True, binary_capable=True)


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


async def _no_sleep(_seconds: float) -> None:
    return None


@dataclass
class FakeOutputs:
    """The two ``OutputContractStore`` reads the produced-output resolver uses."""

    obligations: list[OutputObligation] = field(default_factory=list)
    accepted: list[ExactOutput] = field(default_factory=list)
    submitted: list[ExactOutput] = field(default_factory=list)
    producer_operations: list[str] = field(default_factory=list)
    assessments: list[Assessment] = field(default_factory=list)
    reads: int = 0

    async def active_obligations(self, scope: str, run_id: str) -> tuple[OutputObligation, ...]:
        self.reads += 1
        return tuple(self.obligations)

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        return tuple(self.accepted)

    async def output_assessments(self, scope: str, run_id: str) -> tuple[Assessment, ...]:
        return tuple(self.assessments)

    async def submitted_outputs(
        self,
        scope: str,
        run_id: str,
        obligation_key: str,
        *,
        operation_ref: str,
        operation_attempt: int | None = None,
        execution_generation: int | None = None,
    ) -> tuple[ExactOutput, ...]:
        self.producer_operations.append(operation_ref)
        return tuple(item for item in self.submitted if item.obligation_key == obligation_key)


class FakeBackend:
    """A receiving backend: what it stores is what its read returns (optionally failing)."""

    def __init__(self, name: str = "fake:sandbox", *, unreadable: Sequence[str] = ()) -> None:
        self.realized_backend = name
        self.files: dict[str, bytes] = {}
        self.unreadable = set(unreadable)

    async def write(self, files: Sequence[tuple[str, bytes]]) -> None:
        self.files.update(files)

    async def read(self, path: str) -> bytes | None:
        if any(path.endswith(suffix) for suffix in self.unreadable):
            return None
        return self.files.get(path)


class FakeArtifacts:
    def __init__(self, staging: InMemoryStaging) -> None:
        self.staging = staging
        self.items: dict[str, ArtifactContent] = {}

    async def add(self, ref: str, content: bytes, media_type: str, name: str) -> str:
        durable = await self.staging.stage(
            request_scope="s", name=name, content=content, media_type=media_type
        )
        self.items[ref] = ArtifactContent(
            source_ref=ref,
            durable_ref=durable,
            content_digest=_digest(content),
            size_bytes=len(content),
            media_type=media_type,
            file_name=name,
        )
        return _digest(content)

    async def capture(
        self, source_ref: str, *, request_scope: str, max_text_bytes: int
    ) -> ArtifactContent | None:
        return self.items.get(source_ref)


@dataclass
class Seam:
    clock: SteppingClock
    fake: FakeKnowledgeBinding
    package: StoredPackage
    outputs: FakeOutputs
    staging: InMemoryStaging
    store: InMemoryTransferPlanStore
    artifacts: FakeArtifacts
    lineage: InMemoryLineageStore
    materializer: TransferMaterializer

    def access(self, attempt: int = 1) -> InvocationAccess:
        return InvocationAccess(
            origin=origin(attempt, operation_id="op-review-1"),
            subject="mission-control-runtime",
            invocation_id=f"inv-review-{attempt}",
            authenticated_at=self.clock.now,
        )

    def handle(self, package: StoredPackage | None = None) -> str:
        report = (package or self.package).report
        return f"kh:{report.binding}/report/{report.id}@{report.version}"

    def accept(self, position: str, key: str, revision: ExactOutput) -> None:
        if not any(item.key == key for item in self.outputs.obligations):
            self.outputs.obligations.append(
                OutputObligation(
                    key=key,
                    owner_position=position,
                    contract=OutputContract(form=revision.form),
                )
            )
        self.outputs.accepted = [
            item for item in self.outputs.accepted if item.obligation_key != key
        ] + [revision]

    def accept_report(self, package: StoredPackage | None = None, *, number: int = 1) -> None:
        stored = package or self.package
        self.accept(
            "draft",
            "draft.report",
            ExactOutput(
                revision_id=f"rev-report-{number}",
                run_id=RUN,
                obligation_key="draft.report",
                obligation_revision=1,
                deliverable_id="report",
                revision=number,
                form=OutputForm.REFERENCE,
                content_digest=stored.report.digest,
                candidate={"kind": "handle", "ref": self.handle(stored)},
                producer_origin_ref="mc-inv:draft",
            ),
        )

    def request(
        self,
        selection: TransferSelection,
        *,
        attempt: int = 1,
        overhead: HostOverhead = OVERHEAD,
        tools: tuple[str, ...] = (),
    ) -> MaterializeRequest:
        access = self.access(attempt)
        return MaterializeRequest(
            receiver=ReceiverRef(scope=access.scope, run_id=RUN, operation_id="op-review-1"),
            attempt=ReceiverAttempt(
                operation_attempt=attempt, execution_generation=1, invocation_ref=f"inv-{attempt}"
            ),
            selection=selection,
            configuration_ref="erc:sha256:" + "0" * 64,
            host_state_ref="context-packet:p1@sha256:" + "1" * 64,
            overhead=overhead,
            retrieval_tools=tools,
            access=access,
        )


def seam(*, selectors: dict[str, object] | None = None) -> Seam:
    clock = SteppingClock(step=timedelta(milliseconds=1))
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    fake.operation_statuses["knowledge.read"] = deque(["succeeded"] * 32)
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
    reports = ContentResolutionService(gateway)
    staging = InMemoryStaging()
    outputs = FakeOutputs()
    artifacts = FakeArtifacts(staging)
    artifact_resolver = ArtifactResolver(artifacts, staging)
    store = InMemoryTransferPlanStore()
    lineage = InMemoryLineageStore()
    materializer = TransferMaterializer(
        store=store,
        staging=staging,
        custody=staging,
        resolvers={
            "produced_output": ProducedOutputResolver(
                outputs,  # type: ignore[arg-type]
                reports=reports,
                artifacts=artifact_resolver,
            ),
            "exact_artifact": artifact_resolver,
            "typed_literal": LiteralResolver(),
            "application_selector": ApplicationSelectorResolver(selectors or {}),  # type: ignore[arg-type]
        },
        access={"produced_output": KnowledgeReadAccess(reports)},
        lineage=lineage,
        clock=clock,
    )
    return Seam(clock, fake, package, outputs, staging, store, artifacts, lineage, materializer)


def bounds(**overrides: int) -> ResourceBounds:
    return ResourceBounds(
        **(
            {
                "window_tokens": 64_000,
                "generation_reserve_tokens": 4_000,
                "tool_result_reserve_tokens": 2_000,
                "inline_bytes_ceiling": 16_000,
                "file_bytes_ceiling": 512_000,
                "file_count_ceiling": 16,
            }
            | overrides
        )
    )


def dependent(*inputs: TransferInput, **fields: object) -> TransferSelection:
    return TransferSelection.model_validate(
        {
            "boundary": fields.pop("boundary", Boundary.DEPENDENT_STAGE),
            "receiver_position": "review",
            "inputs": inputs,
            "bounds": fields.pop("bounds", bounds()),
            "backend": SANDBOX,
            **fields,
        }
    )


REPORT_INPUT = TransferInput(
    name="draft", source=InputSource.produced("draft", "draft.report"), purpose="dependent_input"
)


def _trusted(revision: ExactOutput, result: str, number: int, supersedes: str | None) -> Assessment:
    return Assessment(
        assessment_id=f"assess-{number}",
        subject_kind="output_revision",
        subject_id=revision.revision_id,
        subject_digest=revision.content_digest,
        requirement_results={"trusted_assessment": result},  # type: ignore[dict-item]
        result=result,  # type: ignore[arg-type]
        assessor_origin_ref=f"ks:biotech-graph/use_decision/decision-{number}",
        method_pin="knowledge.report.assess@1",
        policy_pin="policy-1@research-core.policy.v1",
        evidence_refs=(f"ks-use-decision:decision-{number}@sha256:{'b' * 64}",),
        supersedes=supersedes,
    )
