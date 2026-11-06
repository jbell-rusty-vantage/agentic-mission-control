"""Minimal ``submit_output`` seam and independent assessment handoff (Sprint V M03; design §5, §8).

A submission is one act of one invocation for one obligation under a stable tool-call
``submission_key``: a retry with the same key and the same selection is the same submission;
the same key with a different selection is ``SUBMISSION_CONFLICT`` (MCE02); a new key is the
next revision. Selections (handles or paths with their exact digests) are frozen.

**Assessment handoff (design §8 "final submission always triggers the independent report
assessment under the host").** On finalize, for the latest submission of every obligation
whose selection names a report handle, the host starts the independent K01 ``report.assess``
operation through the knowledge gateway (request key ``assess:<submission id>``, so a retry is
the same assessment), records the remote handle on the submission (``pending -> assessing``,
release 1.6.0) and polls it within the gateway's bound. A terminal service verdict is recorded
(``succeeded`` -> ``assessed``; ``partial``/``held`` -> ``held``; ``rejected`` -> ``rejected``);
``failed``/``cancelled`` are not verdicts and leave the submission ``assessing`` with the error.

**Named promises (WI-01, OUTPUT-CONTRACTS §§2-4).** :meth:`SubmissionService.submit_output`
is the single authoritative progressive/final act: it resolves the run's admitted obligation
revision (an undeclared promise refuses), checks every candidate against its pinned contract
(form, exact bytes/value digest, schema version and shape, nested member refs, code-change
identity, control-record authority, bare-id resolution through exactly one admitted binding)
and records the submission row with one immutable output revision per deliverable. It never
promotes: an accepted head moves only through ``promote_output`` (``application/outputs/
fulfillment.py``), so a new draft never replaces an accepted head.

The finalization report iterates the host-declared obligations only (no fallback to whatever
rows were submitted) and counts an obligation as met only on an assessment verdict, never on
a submitted row. ``outcome_basis`` is ``assessed`` when every declared obligation has a
verdict, ``declared_obligations`` otherwise (open assessment handles named so a later
:meth:`SubmissionService.refresh_assessments` can settle them) and ``no_declared_obligations``
when the host declared none; submissions to undeclared obligations are reported, not counted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.knowledge.access import InvocationAccess, InvocationIdentity
from mission_control.application.knowledge.operations import KnowledgeCall, KnowledgeResult
from mission_control.application.ports.knowledge import (
    FinalizationCandidate,
    HandleRecord,
    JournalVersionConflict,
    OutputSubmissionStore,
    SubmissionCandidate,
    SubmissionClosed,
    SubmissionConflict,
    SubmissionRecord,
)
from mission_control.application.ports.outputs import (
    OutputContractStore,
    StaleHead,
    SubmissionAct,
    SubmittedItem,
)
from mission_control.contracts.knowledge_protocol import Governors, Origin, Ref
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.knowledge.handles import DIGEST_PATTERN
from mission_control.domain.outputs.contracts import (
    AdmittedBinding,
    Finding,
    OutputError,
    OutputErrorCode,
    OutputObligation,
    SubmissionAck,
    SubmitOutput,
    tagged_digest,
)
from mission_control.domain.outputs.rules import SchemaValidator, check_submission

FINALIZATION_REPORT_SCHEMA = "mc.finalization_report.v2"
ASSESSMENT_CAPABILITY_PIN = "knowledge.report.assess@1"
SubmissionRef = SubmissionRecord
_HANDLE = re.compile(
    r"^kh:(?P<binding>[a-z][a-z0-9_.-]{0,119})/(?P<kind>[a-z_]+)/"
    r"(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]{0,199})@(?P<version>[a-z][a-z0-9_.-]*\.v[0-9]+)$"
)
VERDICTS: dict[str, str] = {
    "succeeded": "assessed",
    "partial": "held",
    "held": "held",
    "rejected": "rejected",
}


class SelectedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["handle", "path"]
    ref: str = Field(min_length=1, max_length=2048)
    digest: str = Field(pattern=DIGEST_PATTERN)


class OutputSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[SelectedItem, ...] = Field(min_length=1)

    def document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def digest(self) -> str:
        return sha256_digest(self.document())


class PromisesRegistered(RuntimeError):
    """The run admitted named promises: only ``submit_output`` may record a submission."""


class AmbiguousHandle(ValueError):
    """A selection names a bare id or a handle no binding can resolve exactly."""


class UnsupportedReportSelection(ValueError):
    """A legacy (promise-free) selection names a report beside other items: that path has one
    assessment state per submission, so one report cannot attest other members (OVE-160). Runs
    with named promises assess collections per member instead (WI-07)."""


def report_ref(item: SelectedItem | dict[str, Any], *, tenant: str) -> Ref | None:
    """The exact K01 report ``Ref`` a selected handle names, ``None`` for a non-report item.

    A handle renders ``kh:<binding>/<kind>/<id>@<schema version>`` with the record digest
    beside it; anything else that claims to be a handle (a bare id) is ambiguous.
    """

    selected = item if isinstance(item, SelectedItem) else SelectedItem.model_validate(item)
    if selected.kind != "handle":
        return None
    match = _HANDLE.match(selected.ref)
    if match is None:
        raise AmbiguousHandle(f"selection names no exact handle: {selected.ref!r}")
    if match["kind"] != "report":
        return None
    return Ref(
        kind="report",
        id=match["id"],
        version=match["version"],
        digest=selected.digest,
        tenant=tenant,
        binding=match["binding"],
    )


class AssessmentGateway(Protocol):
    """The part of the knowledge gateway the assessment handoff needs."""

    @property
    def binding(self) -> str: ...

    async def invoke(self, call: KnowledgeCall, access: InvocationAccess) -> KnowledgeResult: ...

    async def poll(self, record: HandleRecord, caller: Origin, *, scope: str) -> HandleRecord: ...

    async def stored_handle(self, scope: str, operation_id: str) -> HandleRecord | None: ...


@dataclass(frozen=True)
class AssessmentSummary:
    state: str
    operation_id: str | None = None
    binding: str | None = None
    verdict_ref: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ObligationSummary:
    obligation_id: str
    submission_ids: tuple[str, ...]
    latest_revision: int | None
    latest_selection_digest: str | None
    covered: bool = False
    assessment: AssessmentSummary | None = None

    @property
    def assessed(self) -> bool:
        return self.assessment is not None and self.assessment.state in {
            "assessed",
            "held",
            "rejected",
        }


@dataclass(frozen=True)
class FinalizationReport:
    # ``None`` while settlement is blocked: nothing was recorded (see ``blocked_effects``).
    finalization_id: str | None
    invocation_ref: str
    outcome: str
    outcome_basis: str
    obligations: tuple[ObligationSummary, ...]
    assessment_state: str
    report_digest: str
    open_assessments: tuple[str, ...] = field(default_factory=tuple)
    # Effect keys still unresolved (e.g. `pending_dispatch`) after the node-end receipt-first
    # poll. Non-empty: the invocation is not finalized (outcome `blocked`); the recovery
    # lookup path settles the effects after the run, then the finalization is recorded once.
    blocked_effects: tuple[str, ...] = field(default_factory=tuple)
    native_effects: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_effects)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _governors(clock: Callable[[], datetime]) -> Governors:
    deadline = clock().astimezone(UTC).replace(microsecond=0)
    return Governors(
        deadline=(deadline.replace(year=deadline.year + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        maxItems=1,
        partialResults="forbid",
        budget={"calls": 0, "tokens": 0, "costUsd": "0"},  # type: ignore[arg-type]
    )


def json_schema_validator(schema: dict[str, Any], value: Any) -> list[str]:
    """Draft 2020-12 validation of one structured value (the bound schema body is pinned)."""

    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '/'}: {error.message}"[:300]
        for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    ]


def _selection_document(request: SubmitOutput, obligation_revision: int) -> dict[str, Any]:
    """The frozen selection row: exact handle/path items (what M04 delivery reads) beside the
    full canonical candidates the key binds."""

    return {
        "items": [
            {"kind": item.kind, "ref": item.ref, "digest": item.digest}
            for item in request.items
            if item.kind in {"handle", "path"} and item.ref is not None
        ],
        "submit": request.document(),
        "obligation_revision": obligation_revision,
    }


def _refused(error: OutputError, findings: tuple[Finding, ...] = ()) -> SubmissionAck:
    return SubmissionAck(status="refused", error=error, findings=findings)


class SubmissionService:
    def __init__(
        self,
        store: OutputSubmissionStore,
        *,
        assessor: AssessmentGateway | None = None,
        contracts: OutputContractStore | None = None,
        validate_schema: SchemaValidator | None = json_schema_validator,
        actor_ref: str = "mission-control:submissions",
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._assessor = assessor
        self._contracts = contracts
        self._validate_schema = validate_schema
        self._actor_ref = actor_ref
        self._clock = clock

    @property
    def validate_schema(self) -> SchemaValidator | None:
        """The schema validator every candidate check uses (association matches too)."""

        return self._validate_schema

    async def submit_output(
        self,
        access: InvocationAccess,
        request: SubmitOutput,
        *,
        position: str | None,
        bindings: tuple[AdmittedBinding, ...] = (),
        caller_origin_ref: str | None = None,
    ) -> SubmissionAck:
        """``SubmitOutput@2`` -> ``SubmissionAck@1``: the one authoritative submission act.

        The host supplies ``access`` (attribution), the invocation's ``position`` (required) and
        its admitted ``bindings``; the request cannot name an origin, grant authority or claim
        fulfillment. The promise revision is the one the invocation pinned at its start
        (``OutputFulfillmentService.pin_invocation``), so a successor activated later never
        changes an in-flight invocation's contract. Accepted means recorded drafts; promotion
        and fulfillment are separate.
        """

        contracts = self._contracts
        if contracts is None:
            raise RuntimeError("submit_output needs the output-contract store (release 1.7.0)")
        identity = access.identity()
        declared = {
            item.key for item in await contracts.active_obligations(identity.scope, identity.run_id)
        }
        obligation = None
        if request.obligation_key in declared:
            pins = await contracts.invocation_pins(identity.scope, identity.invocation_ref)
            pinned = pins.get(request.obligation_key)
            if pinned is None:
                return _refused(
                    OutputError(
                        code=OutputErrorCode.INVOCATION_UNPINNED,
                        position=position,
                        safe_message="the host pinned no promise revisions at invocation start",
                        retry_state="terminal",
                        recovery_owner="host",
                    )
                )
            obligation = await contracts.obligation_revision(
                identity.scope, identity.run_id, request.obligation_key, pinned
            )
        checked = check_submission(
            obligation,
            request,
            position=position,
            bindings=bindings,
            validate_schema=self._validate_schema,
        )
        if checked.error is not None or obligation is None:
            assert checked.error is not None
            return _refused(checked.error.model_copy(update={"position": position}))
        findings = tuple(item for decision in checked.decisions for item in decision.findings)
        resolved = SubmitOutput(
            submission_key=request.submission_key,
            obligation_key=request.obligation_key,
            mode=request.mode,
            expected_head=request.expected_head,
            items=tuple(decision.candidate for decision in checked.decisions),
            derivation_refs=request.derivation_refs,
        )
        # The key binds the request as offered: a retry is the same payload byte for byte.
        selection = _selection_document(request, obligation.revision)
        selection["resolved"] = [
            decision.resolution for decision in checked.decisions if decision.resolution
        ]
        try:
            recorded = await contracts.record_submission(
                SubmissionAct(
                    scope=identity.scope,
                    run_id=identity.run_id,
                    operation_ref=identity.operation_ref,
                    operation_attempt=identity.operation_attempt,
                    execution_generation=identity.execution_generation,
                    invocation_ref=identity.invocation_ref,
                    obligation_key=request.obligation_key,
                    obligation_revision=obligation.revision,
                    submission_key=request.submission_key,
                    selection=selection,
                    selection_digest=tagged_digest("mc.submit_output.v2", request.document()),
                    items=tuple(
                        SubmittedItem(
                            deliverable_id=item.deliverable_id,
                            form=item.form.value,
                            candidate=item.document(),
                            content_digest=item.digest,
                        )
                        for item in resolved.items
                    ),
                    producer_origin_ref=access.invocation_ref,
                    caller_origin_ref=caller_origin_ref or access.invocation_ref,
                    actor_ref=self._actor_ref,
                    at=self._clock(),
                    unit_key=identity.unit_key,
                )
            )
        except StaleHead as error:
            return _refused(
                OutputError(
                    code=OutputErrorCode.STALE_HEAD,
                    field_pointer="/expected_head",
                    safe_message=f"accepted head changed to {error.current}; inspect before repair",
                    available_actions=("inspect", "submit_output"),
                )
            )
        except SubmissionConflict:
            return _refused(
                OutputError(
                    code=OutputErrorCode.SUBMISSION_CONFLICT,
                    field_pointer="/submission_key",
                    safe_message="this submission key already names other bytes",
                    retry_state="terminal",
                )
            )
        except SubmissionClosed:
            return _refused(
                OutputError(
                    code=OutputErrorCode.INVOCATION_FINALIZED,
                    safe_message="the invocation is already finalized",
                    retry_state="terminal",
                    recovery_owner="host",
                )
            )
        return SubmissionAck(
            submission_id=recorded.submission_id,
            status="accepted",
            revisions=recorded.revisions,
            findings=findings,
            next_actions=("await_promotion",)
            if request.mode == "final"
            else ("submit_output", "await_promotion"),
        )

    async def pin_invocation(
        self, access: InvocationAccess, *, actor_ref: str
    ) -> Mapping[str, int]:
        """Pin the run's active promise revisions for this invocation (idempotent)."""

        assert self._contracts is not None
        identity = access.identity()
        return await self._contracts.pin_invocation(
            identity.scope,
            identity.run_id,
            identity.invocation_ref,
            actor_ref=actor_ref,
            at=self._clock(),
        )

    async def pinned_obligation(
        self, access: InvocationAccess, obligation_key: str
    ) -> OutputObligation | None:
        """The promise revision this invocation pinned for ``obligation_key``, if any."""

        if self._contracts is None:
            return None
        identity = access.identity()
        pinned = (
            await self._contracts.invocation_pins(identity.scope, identity.invocation_ref)
        ).get(obligation_key)
        if pinned is None:
            return None
        return await self._contracts.obligation_revision(
            identity.scope, identity.run_id, obligation_key, pinned
        )

    async def inspect_invocation(
        self, access: InvocationAccess, *, position: str | None, obligation_key: str | None = None
    ) -> dict[str, Any]:
        from mission_control.application.outputs.invocation_view import inspect_invocation

        return await inspect_invocation(
            self._contracts, self._store, access, position=position, obligation_key=obligation_key
        )

    async def promises_registered(self, scope: str, run_id: str) -> bool:
        """Whether the run admitted named promises (then ``submit_output`` is the only act)."""

        return (
            self._contracts is not None
            and await self._contracts.promise_set(scope, run_id) is not None
        )

    async def submit(
        self,
        access: InvocationAccess,
        obligation: str,
        selection: OutputSelection,
        submission_key: str,
    ) -> SubmissionRef:
        """Legacy report selection for a run with no registered promises.

        Its rows feed only the M03 assessment handoff at finalization; no receiver reads them
        (WI-02 retired the run-wide M04 delivery: inputs reach a receiver only through its sealed
        transfer plan).

        Once a run registered promises this path refuses (``PromisesRegistered``): the one
        writer is ``submit_output``.
        """

        if not obligation or not submission_key:
            raise ValueError("a submission names its obligation and stable submission key")
        _selection_report(selection, tenant=access.origin.tenant_id)
        identity = access.identity()
        if await self.promises_registered(identity.scope, identity.run_id):
            raise PromisesRegistered(f"run {identity.run_id} admitted named promises")
        return await self._store.record_selection(
            SubmissionCandidate(
                scope=identity.scope,
                run_id=identity.run_id,
                operation_ref=identity.operation_ref,
                operation_attempt=identity.operation_attempt,
                execution_generation=identity.execution_generation,
                invocation_ref=identity.invocation_ref,
                obligation_id=obligation,
                submission_key=submission_key,
                selection=selection.document(),
                selection_digest=selection.digest(),
                actor_ref=self._actor_ref,
                at=self._clock(),
                unit_key=identity.unit_key,
            )
        )

    async def submitted_obligations(self, scope: str, invocation_ref: str) -> frozenset[str]:
        """The obligations this invocation has made any submission act for."""

        return frozenset(
            item.obligation_id
            for item in await self._store.list_for_invocation(scope, invocation_ref)
        )

    async def finalize(
        self,
        invocation: InvocationIdentity,
        access: InvocationAccess | None = None,
        *,
        unresolved_effects: tuple[str, ...] = (),
        attempt_failed: bool = False,
        owes_nothing: bool = False,
    ) -> FinalizationReport:
        """Hand selected reports to the independent assessment, then finalize once.

        ``owes_nothing`` (W1 D27): the invocation is an independent evaluator, which by role
        declares no obligation; its empty finalization is ``fulfilled`` (nothing was owed), never
        an unfulfilled producer. Any other invocation with no declared obligation stays
        ``unfulfilled``.

        Settlement blocks on unresolved effects: with any, nothing is recorded and the report
        says ``blocked`` (basis ``unresolved_effects``), so a run never settles over an effect
        whose outcome is unknown.
        """

        submissions = await self._store.list_for_invocation(
            invocation.scope, invocation.invocation_ref
        )
        # Fail closed for old unsupported legacy collections too, even without an assessor; a
        # supported replacement revision can repair the obligation without rewriting history.
        # A named-promise act is never refused here: its members are assessed per revision.
        if not attempt_failed:
            for group in _by_obligation(submissions).values():
                _selected_report(max(group, key=lambda item: item.revision), tenant="validation")
        if access is not None and self._assessor is not None and not attempt_failed:
            submissions = await self._assess(invocation, access, submissions)
        # Only the host-declared obligations are owed; a submitted row never declares one.
        declared = invocation.obligations
        undeclared = sorted({item.obligation_id for item in submissions} - set(declared))
        summaries = tuple(_summary(name, submissions) for name in declared)
        assessed_all = bool(summaries) and all(summary.assessed for summary in summaries)
        if attempt_failed:
            # R2-MC O1: the attempt failed. Its outstanding effects were reconciled first; its
            # submissions are recorded as they stand and no assessment is started for them.
            basis = "attempt_failed"
            outcome = "unfulfilled"
        elif assessed_all:
            basis = "assessed"
            good = sum(
                1
                for summary in summaries
                if summary.assessment is not None and summary.assessment.state == "assessed"
            )
            outcome = _outcome(good, len(summaries))
        elif not summaries:
            basis = "no_declared_obligations"
            outcome = "fulfilled" if owes_nothing else "unfulfilled"
        else:
            # Coverage is not fulfillment: only a verdict counts.
            basis = "declared_obligations"
            good = sum(
                1
                for summary in summaries
                if summary.assessment is not None and summary.assessment.state == "assessed"
            )
            outcome = _outcome(good, len(summaries))
        open_assessments = tuple(
            summary.assessment.operation_id
            for summary in summaries
            if summary.assessment is not None
            and summary.assessment.state == "assessing"
            and summary.assessment.operation_id is not None
        )
        report: dict[str, Any] = {
            "schema": FINALIZATION_REPORT_SCHEMA,
            "invocation_ref": invocation.invocation_ref,
            "outcome_basis": basis,
            "obligations": [_summary_document(summary) for summary in summaries],
            "assessment": {
                "state": _overall(summaries),
                "open_operations": list(open_assessments),
            },
        }
        if undeclared:
            report["undeclared_submissions"] = undeclared
        if attempt_failed:
            report["unresolved_effects"] = sorted(unresolved_effects)
        elif unresolved_effects:
            blocked = report | {"outcome_basis": "unresolved_effects"}
            return FinalizationReport(
                finalization_id=None,
                invocation_ref=invocation.invocation_ref,
                outcome="blocked",
                outcome_basis="unresolved_effects",
                obligations=summaries,
                assessment_state=_overall(summaries),
                report_digest=sha256_digest(blocked),
                open_assessments=open_assessments,
                blocked_effects=tuple(sorted(unresolved_effects)),
            )
        recorded = await self._store.finalize(
            FinalizationCandidate(
                scope=invocation.scope,
                run_id=invocation.run_id,
                operation_ref=invocation.operation_ref,
                operation_attempt=invocation.operation_attempt,
                execution_generation=invocation.execution_generation,
                invocation_ref=invocation.invocation_ref,
                outcome=outcome,
                submission_ids=tuple(
                    submission.submission_id
                    for submission in sorted(submissions, key=lambda item: item.submission_id)
                ),
                report=report,
                report_digest=sha256_digest(report),
                actor_ref=self._actor_ref,
                at=self._clock(),
                outcome_basis=basis,
            )
        )
        stored = recorded.report
        return FinalizationReport(
            finalization_id=recorded.finalization_id,
            invocation_ref=recorded.invocation_ref,
            outcome=recorded.outcome,
            outcome_basis=recorded.outcome_basis,
            obligations=tuple(_summary_from_document(item) for item in stored["obligations"]),
            assessment_state=stored["assessment"]["state"],
            report_digest=recorded.report_digest,
            open_assessments=tuple(stored["assessment"].get("open_operations", ())),
        )

    async def refresh_assessments(
        self, invocation: InvocationIdentity, access: InvocationAccess
    ) -> tuple[ObligationSummary, ...]:
        """Poll open assessments of a finalized invocation and record late verdicts."""

        submissions = await self._store.list_for_invocation(
            invocation.scope, invocation.invocation_ref
        )
        if self._assessor is not None:
            submissions = await self._assess(invocation, access, submissions, start=False)
        return tuple(_summary(name, submissions) for name in invocation.obligations)

    # ------------------------------------------------------------------ assessment

    async def _assess(
        self,
        invocation: InvocationIdentity,
        access: InvocationAccess,
        submissions: list[SubmissionRecord],
        *,
        start: bool = True,
    ) -> list[SubmissionRecord]:
        assessor = self._assessor
        assert assessor is not None
        latest = {
            summary.obligation_id: summary
            for summary in (
                max(group, key=lambda item: item.revision)
                for group in _by_obligation(submissions).values()
            )
        }
        updated = {submission.submission_id: submission for submission in submissions}
        for submission in latest.values():
            report = _selected_report(submission, tenant=access.origin.tenant_id)
            if report is None:
                continue
            record = submission
            if record.assessment_state == "pending" and start:
                result = await assessor.invoke(
                    KnowledgeCall(
                        operation="report.assess",
                        capability_pin=ASSESSMENT_CAPABILITY_PIN,
                        native_contract={"name": "research-report-assessment", "version": "v1"},
                        payload={
                            "report": report.model_dump(mode="json"),
                            "obligation": record.obligation_id,
                            "submission": record.submission_id,
                        },
                        governors=_governors(self._clock),
                        upstream=(report,),
                        request_key=f"assess:{record.submission_id}",
                        subject_ref=f"submission:{record.submission_id}",
                    ),
                    access,
                )
                if result.handle_record is None:
                    continue  # refused before a handle existed: the submission stays pending
                record = await self._started(invocation, record, result.handle_record)
                record = await self._verdict(invocation, record, result.handle_record)
            elif record.assessment_state == "assessing" and record.assessment_operation_id:
                handle = await _stored_handle(assessor, invocation, record)
                if handle is not None:
                    handle = await assessor.poll(
                        handle, access.wire_origin(), scope=invocation.scope
                    )
                    record = await self._verdict(invocation, record, handle)
            updated[record.submission_id] = record
        return list(updated.values())

    async def _started(
        self, invocation: InvocationIdentity, record: SubmissionRecord, handle: HandleRecord
    ) -> SubmissionRecord:
        try:
            return await self._store.start_assessment(
                invocation.scope,
                record.submission_id,
                expected_version=record.version,
                operation_id=handle.handle.operationId,
                binding_id=handle.binding_id,
                actor_ref=self._actor_ref,
                at=self._clock(),
            )
        except JournalVersionConflict:
            current = await self._store.list_for_invocation(
                invocation.scope, invocation.invocation_ref
            )
            return next(item for item in current if item.submission_id == record.submission_id)

    async def _verdict(
        self, invocation: InvocationIdentity, record: SubmissionRecord, handle: HandleRecord
    ) -> SubmissionRecord:
        verdict = VERDICTS.get(handle.state)
        if verdict is None or record.assessment_state != "assessing":
            return record
        result = handle.result_ref
        return await self._store.record_assessment(
            invocation.scope,
            record.submission_id,
            expected_version=record.version,
            state=verdict,
            assessment_ref=(
                f"{handle.binding_id}/operation/{handle.handle.operationId}"
                if result is None
                else f"{result.binding}/{result.kind}/{result.id}@{result.version}"
            ),
            assessment_digest=None if result is None else result.digest,
            actor_ref=self._actor_ref,
            at=self._clock(),
        )


async def _stored_handle(
    assessor: AssessmentGateway, invocation: InvocationIdentity, record: SubmissionRecord
) -> HandleRecord | None:
    if record.assessment_operation_id is None:
        return None
    return await assessor.stored_handle(invocation.scope, record.assessment_operation_id)


def _selected_report(submission: SubmissionRecord, *, tenant: str) -> Ref | None:
    """The one report the K01 handoff assesses for this submission, if any.

    A ``submit_output`` act (WI-01; its row carries the canonical ``submit`` payload) records one
    exact output revision per item, so a report collection is assessed **per member**: each
    revision by the trusted settlement with its own exact digest (WI-07), never one report
    standing for the others. The single-report handoff applies to an act naming exactly one
    report and nothing else. A legacy selection row (no promises) keeps the OVE-160 refusal.
    """

    items = submission.selection.get("items") or ()
    if not items:
        return None  # an inline-only submit_output act selects no report handle
    selection = OutputSelection.model_validate({"items": items})
    if "submit" in submission.selection:
        reports = [
            ref for item in selection.items if (ref := report_ref(item, tenant=tenant)) is not None
        ]
        return reports[0] if len(reports) == 1 and len(selection.items) == 1 else None
    return _selection_report(selection, tenant=tenant)


def _selection_report(selection: OutputSelection, *, tenant: str) -> Ref | None:
    reports = [
        ref for item in selection.items if (ref := report_ref(item, tenant=tenant)) is not None
    ]
    if reports and len(selection.items) != 1:
        raise UnsupportedReportSelection(
            "a report must be the only selected item; collection assessment is unsupported"
        )
    return reports[0] if reports else None


def _by_obligation(submissions: list[SubmissionRecord]) -> dict[str, list[SubmissionRecord]]:
    groups: dict[str, list[SubmissionRecord]] = {}
    for submission in submissions:
        groups.setdefault(submission.obligation_id, []).append(submission)
    return groups


def _outcome(count: int, total: int) -> str:
    if count == 0:
        return "unfulfilled"
    return "fulfilled" if count == total else "partially_fulfilled"


def _overall(summaries: tuple[ObligationSummary, ...]) -> str:
    states = {summary.assessment.state for summary in summaries if summary.assessment}
    if not states:
        return "pending"
    if states <= {"assessed", "held", "rejected"} and all(s.assessment for s in summaries):
        return "assessed"
    return "assessing" if "assessing" in states else "pending"


def _summary(obligation: str, submissions: list[SubmissionRecord]) -> ObligationSummary:
    mine = sorted(
        (item for item in submissions if item.obligation_id == obligation),
        key=lambda item: item.revision,
    )
    latest = mine[-1] if mine else None
    assessment = None
    if latest is not None and latest.assessment_state != "pending":
        assessment = AssessmentSummary(
            state=latest.assessment_state,
            operation_id=latest.assessment_operation_id,
            binding=latest.assessment_binding,
            verdict_ref=latest.assessment_ref,
        )
    return ObligationSummary(
        obligation_id=obligation,
        submission_ids=tuple(item.submission_id for item in mine),
        latest_revision=latest.revision if latest else None,
        latest_selection_digest=latest.selection_digest if latest else None,
        covered=latest is not None,
        assessment=assessment,
    )


def _summary_document(summary: ObligationSummary) -> dict[str, Any]:
    assessment = summary.assessment
    return {
        "obligation_id": summary.obligation_id,
        "covered": summary.covered,
        "submission_ids": list(summary.submission_ids),
        "latest_revision": summary.latest_revision,
        "latest_selection_digest": summary.latest_selection_digest,
        "assessment": None
        if assessment is None
        else {
            "state": assessment.state,
            "operation_id": assessment.operation_id,
            "binding": assessment.binding,
            "verdict_ref": assessment.verdict_ref,
        },
    }


def _summary_from_document(item: dict[str, Any]) -> ObligationSummary:
    assessment = item.get("assessment")
    return ObligationSummary(
        obligation_id=item["obligation_id"],
        submission_ids=tuple(item["submission_ids"]),
        latest_revision=item["latest_revision"],
        latest_selection_digest=item["latest_selection_digest"],
        covered=bool(item.get("covered", item["submission_ids"])),
        assessment=None
        if assessment is None
        else AssessmentSummary(
            state=assessment["state"],
            operation_id=assessment.get("operation_id"),
            binding=assessment.get("binding"),
            verdict_ref=assessment.get("verdict_ref"),
        ),
    )


__all__ = [
    "ASSESSMENT_CAPABILITY_PIN",
    "FINALIZATION_REPORT_SCHEMA",
    "VERDICTS",
    "AmbiguousHandle",
    "AssessmentGateway",
    "AssessmentSummary",
    "FinalizationReport",
    "ObligationSummary",
    "OutputSelection",
    "PromisesRegistered",
    "SelectedItem",
    "SubmissionRef",
    "SubmissionService",
    "json_schema_validator",
    "report_ref",
]
