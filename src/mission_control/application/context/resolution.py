"""Exact report resolution for the first dependent invocation (Sprint V M04, design §8/§9).

:class:`ContentResolutionService` turns one selected report handle into the exact frozen
package the next invocation will receive, or refuses typed. It never guesses: a bare id is
``AMBIGUOUS_HANDLE``; the binding's ``knowledge.read`` must resolve the *exact* revision the
handle names (``EXACT_REVISION_UNAVAILABLE`` otherwise, also when the binding answers another
revision); the fetched manifest must digest to the read's ``resultRef``, name that exact
report, and the body and ledger bytes must digest and size exactly as the manifest says
(``DIGEST_MISMATCH``; a missing part is ``PARTIAL_PACKAGE``). A workspace file selected beside
the handle must be byte-identical to the report body (``REPORT_FILE_MISMATCH``).

Provenance (SP-10): the receiving invocation is the ``consumer`` of the exact ``revision``;
those facts are persisted when the delivery completes. Adoption is the *submitting*
invocation's act and is recorded by ``submit_output`` (never as production).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.operations import (
    KnowledgeCall,
    KnowledgeRefused,
    KnowledgeResult,
)
from mission_control.application.outputs.submission_service import (
    AmbiguousHandle,
    SelectedItem,
    report_ref,
)
from mission_control.contracts.knowledge_protocol import (
    REPORT_PACKAGE_SCHEMA,
    SELECTED_READ_CONTRACT,
    Governors,
    MembersSelection,
    Ref,
    ResearchReportPackage,
    RevisionSelection,
    SelectedReportRead,
    digest_bytes,
    digest_canonical,
)
from mission_control.domain.knowledge.lineage import (
    ActorKind,
    LineageFact,
    ProvenanceRole,
)

ResolutionCode = Literal[
    "AMBIGUOUS_HANDLE",
    "UNSUPPORTED_SELECTION",
    "EXACT_REVISION_UNAVAILABLE",
    "DIGEST_MISMATCH",
    "PARTIAL_PACKAGE",
    "REPORT_FILE_MISMATCH",
    "READ_REFUSED",
]
READ_CAPABILITY_PIN = "knowledge.read@1"


class ResolutionRefused(RuntimeError):
    def __init__(self, code: ResolutionCode, message: str, *, cause: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code: ResolutionCode = code
        self.cause = cause


@dataclass(frozen=True)
class ResolvedReport:
    """The exact, verified package of one selected report revision."""

    report: Ref
    result_ref: Ref
    manifest: dict[str, Any]
    body: bytes
    ledger: bytes
    handle: str
    provenance: tuple[LineageFact, ...]
    # The validated `research-report-package.v2` (its assertion and fragment handles).
    package: ResearchReportPackage

    @property
    def body_digest(self) -> str:
        return digest_bytes(self.body)

    @property
    def manifest_bytes(self) -> bytes:
        from mission_control.contracts.knowledge_protocol import canonical_json

        return canonical_json(self.manifest).encode("utf-8")


def _governors() -> Governors:
    return Governors(
        deadline="2099-01-01T00:00:00Z",
        maxItems=1,
        partialResults="forbid",
        budget={"calls": 0, "tokens": 0, "costUsd": "0"},  # type: ignore[arg-type]
    )


def selected_read(
    report: Ref,
    *,
    purpose: str,
    assertions: tuple[Ref, ...] | None = None,
    evidence: tuple[Ref, ...] | None = None,
) -> SelectedReportRead:
    """The one MC read client shape (KS ``readSelected``, ``selected-report-read/v2``): the exact
    report, the receiver's admitted purpose and either the whole revision or exact assertion and
    fragment handles (sorted by id, one per id)."""

    if assertions is None and evidence is None:
        selection: RevisionSelection | MembersSelection = RevisionSelection()
    else:
        selection = MembersSelection(
            assertions=tuple(sorted({h.id: h for h in assertions or ()}.values(), key=_by_id)),
            evidence=tuple(sorted({h.id: h for h in evidence or ()}.values(), key=_by_id)),
        )
    return SelectedReportRead(report=report, exact=True, purpose=purpose, selection=selection)


def _by_id(ref: Ref) -> str:
    return ref.id


def selected_read_payload(
    report: Ref,
    *,
    purpose: str,
    assertions: tuple[Ref, ...] | None = None,
    evidence: tuple[Ref, ...] | None = None,
) -> dict[str, Any]:
    """The canonical inline payload of :func:`selected_read`."""

    return selected_read(
        report, purpose=purpose, assertions=assertions, evidence=evidence
    ).model_dump(mode="json")


class ContentResolutionService:
    def __init__(self, gateway: KnowledgeGateway) -> None:
        self._gateway = gateway

    async def resolve(
        self,
        item: SelectedItem,
        access: InvocationAccess,
        *,
        companion_file_digest: str | None = None,
        produced_by_invocation: bool = False,
        purpose: str = "dependent_input",
        assertions: tuple[Ref, ...] | None = None,
        evidence: tuple[Ref, ...] | None = None,
        attempt_key: str | None = None,
    ) -> ResolvedReport:
        tenant = access.origin.tenant_id
        try:
            report = report_ref(item, tenant=tenant)
        except AmbiguousHandle as error:
            raise ResolutionRefused("AMBIGUOUS_HANDLE", str(error)) from None
        if report is None:
            raise ResolutionRefused("UNSUPPORTED_SELECTION", "M04 resolves report handles only")
        selected = selected_read(report, purpose=purpose, assertions=assertions, evidence=evidence)
        payload = selected.model_dump(mode="json")
        try:
            read = await self._gateway.invoke(
                KnowledgeCall(
                    operation="knowledge.read",
                    capability_pin=READ_CAPABILITY_PIN,
                    native_contract=dict(SELECTED_READ_CONTRACT),
                    payload=payload,
                    governors=_governors(),
                    upstream=(report,),
                    # A current-access re-read names its attempt, so it is never a cached answer.
                    request_key=(
                        f"read:{report.id}:{report.digest[7:23]}:{digest_canonical(payload)[7:19]}"
                        + ("" if attempt_key is None else f":{attempt_key[:64]}")
                    ),
                    subject_ref=item.ref,
                ),
                access,
            )
        except KnowledgeRefused as refused:
            raise ResolutionRefused("READ_REFUSED", str(refused), cause=refused.code) from None
        return await self.resolve_result(
            item, access, selected, read, companion_file_digest=companion_file_digest
        )

    async def resolve_result(
        self,
        item: SelectedItem,
        access: InvocationAccess,
        selected: SelectedReportRead,
        read: KnowledgeResult,
        *,
        companion_file_digest: str | None = None,
    ) -> ResolvedReport:
        """Verify and retrieve an already dispatched selected read, without invoking again."""
        report, purpose = selected.report, selected.purpose
        status = read.status
        if read.refusal_code == "EXACT_REVISION_UNAVAILABLE" or (
            status is not None
            and status.error is not None
            and status.error.code == "EXACT_REVISION_UNAVAILABLE"
        ):
            raise ResolutionRefused(
                "EXACT_REVISION_UNAVAILABLE", f"{item.ref} is not available at that revision"
            )
        if status is None or status.state != "succeeded" or status.resultRef is None:
            raise ResolutionRefused(
                "READ_REFUSED",
                f"knowledge.read ended {None if status is None else status.state}",
                cause=read.refusal_code,
            )
        try:
            package = await self._gateway.read_content(status.resultRef, access)
        except KnowledgeRefused as refused:
            code: ResolutionCode = (
                "EXACT_REVISION_UNAVAILABLE"
                if refused.code == "EXACT_REVISION_UNAVAILABLE"
                else "READ_REFUSED"
            )
            raise ResolutionRefused(code, str(refused), cause=refused.code) from None
        manifest = dict(package.manifest)
        if package.result_ref != status.resultRef or digest_canonical(manifest) != (
            status.resultRef.digest
        ):
            raise ResolutionRefused("DIGEST_MISMATCH", "package manifest is not the read result")
        try:
            exact = ResearchReportPackage.model_validate(manifest)
        except ValueError as error:
            raise ResolutionRefused(
                "DIGEST_MISMATCH", f"the package is not an exact {REPORT_PACKAGE_SCHEMA}"
            ) from error
        if exact.report != report:
            raise ResolutionRefused(
                "EXACT_REVISION_UNAVAILABLE", "the binding answered another report revision"
            )
        if exact.purpose != purpose or exact.request != selected.digest():
            raise ResolutionRefused("READ_REFUSED", "the package answers another request")
        if exact.selection != selected.selection:
            raise ResolutionRefused("READ_REFUSED", "the package answers another selection")
        if isinstance(selected.selection, MembersSelection):
            answered = (
                tuple(item.handle for item in exact.assertions),
                tuple(item.handle for item in exact.evidence),
            )
            if answered != (selected.selection.assertions, selected.selection.evidence):
                raise ResolutionRefused(
                    "PARTIAL_PACKAGE", "the package answers other members than were selected"
                )
        body_digest = digest_bytes(b"")
        if (exact.body is None) != (exact.ledger is None):
            raise ResolutionRefused("PARTIAL_PACKAGE", "body and ledger references must agree")
        if exact.body is None and (package.body or package.ledger):
            raise ResolutionRefused(
                "PARTIAL_PACKAGE", "unselected body or ledger bytes are not authorized content"
            )
        if exact.body is not None and exact.ledger is not None:
            body_digest, body_bytes = exact.body.digest, exact.body.bytes
            ledger_digest, ledger_bytes = exact.ledger.digest, exact.ledger.bytes
            if len(package.body) != body_bytes or len(package.ledger) != ledger_bytes:
                raise ResolutionRefused(
                    "PARTIAL_PACKAGE", "package bytes are shorter than declared"
                )
            if digest_bytes(package.body) != body_digest or digest_bytes(package.ledger) != (
                ledger_digest
            ):
                raise ResolutionRefused(
                    "DIGEST_MISMATCH", "package bytes differ from their digests"
                )
        if companion_file_digest is not None and companion_file_digest != body_digest:
            raise ResolutionRefused(
                "REPORT_FILE_MISMATCH", "the selected file is not the registered report body"
            )
        consumer = access.origin
        facts = [
            LineageFact(
                subject_handle=item.ref,
                role=ProvenanceRole.CONSUMER,
                actor_kind=ActorKind.ORIGIN,
                actor_ref=access.invocation_ref,
                actor_origin=consumer,
                fact={"result_ref": status.resultRef.model_dump(mode="json")},
            ),
            LineageFact(
                subject_handle=item.ref,
                role=ProvenanceRole.REVISION,
                actor_kind=ActorKind.REVISION,
                actor_ref=f"{report.binding}/report/{report.id}@{report.version}",
                fact={"digest": report.digest},
            ),
        ]
        return ResolvedReport(
            report=report,
            result_ref=status.resultRef,
            manifest=manifest,
            body=package.body,
            ledger=package.ledger,
            handle=item.ref,
            provenance=tuple(facts),
            package=exact,
        )


__all__ = [
    "READ_CAPABILITY_PIN",
    "ContentResolutionService",
    "ResolutionCode",
    "ResolutionRefused",
    "ResolvedReport",
    "selected_read",
    "selected_read_payload",
]
