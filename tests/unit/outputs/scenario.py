"""Shared WI-01 scenario builders: obligations, candidates and a wired service stack.

Used by the unit proof (in-memory store) and the PostgreSQL proof (real 1.7.0 tables), so both
observe the same refused / waiting / fulfilled results through the ordinary handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import (
    HostAccess,
    OutputFulfillmentService,
    OutputSetRef,
    PromoteOutput,
)
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.outputs.contracts import (
    AllOf,
    CandidateRef,
    Cardinality,
    CoverageContract,
    Enforcement,
    FulfillmentResult,
    ObligationLeaf,
    OutputContract,
    OutputForm,
    OutputObligation,
    OutputPromiseSet,
    Requirement,
    SchemaPin,
    SubmissionAck,
    SubmitOutput,
)
from mission_control.domain.outputs.rules import code_change_digest, text_digest

CLAIMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["study", "claim"],
                "properties": {"study": {"type": "string"}, "claim": {"type": "string"}},
            },
        }
    },
}
INDEX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["members"],
    "properties": {"members": {"type": "array"}},
}
NOTE_SCHEMA: dict[str, Any] = {"type": "object", "required": ["finding"]}
REPO = "github.com/overtonbell/mission-control"
TRUSTED_VALIDATORS = frozenset({"knowledge.report.assess@1"})
BASE = "a" * 40
HEAD = "b" * 40


def schema(ref: str, body: dict[str, Any]) -> SchemaPin:
    return SchemaPin(ref=ref, digest=sha256_digest(body), body=body)


def obligation(
    key: str,
    form: OutputForm,
    *,
    enforcement: Enforcement = Enforcement.REQUIRED,
    position: str = "draft",
    **contract: Any,
) -> OutputObligation:
    cardinality = contract.pop("cardinality", Cardinality())
    return OutputObligation(
        key=key,
        owner_position=position,
        enforcement=enforcement,
        cardinality=cardinality,
        contract=OutputContract(form=form, **contract),
    )


def eight_forms() -> tuple[OutputObligation, ...]:
    return (
        obligation("draft.summary", OutputForm.TEXT, media_type="text/markdown"),
        obligation(
            "draft.claims",
            OutputForm.STRUCTURED,
            schema_pin=schema("claim_table@1", CLAIMS_SCHEMA),
            coverage=CoverageContract(subjects=("s1", "s2"), pointer="/claims", key="study"),
        ),
        obligation("draft.figure", OutputForm.FILE, media_type="image/png"),
        obligation("draft.dataset", OutputForm.COLLECTION),
        obligation("draft.source", OutputForm.REFERENCE),
        obligation(
            "draft.patch",
            OutputForm.CODE_CHANGE,
            repository=REPO,
            requirements=(
                Requirement(key="tests", validator="mc.check.command@1"),
                Requirement(key="lint", validator="mc.check.command@1"),
            ),
        ),
        obligation("draft.ingest", OutputForm.EFFECT_RECEIPT),
        obligation(
            "draft.note",
            OutputForm.CONTROL_RECORD,
            schema_pin=schema("finding_note@1", NOTE_SCHEMA),
        ),
    )


def promises(*items: OutputObligation, completion: Any = None, **vocab: Any) -> OutputPromiseSet:
    return OutputPromiseSet(
        obligations=items,
        completion=completion
        or AllOf(items=tuple(ObligationLeaf(obligation=item.key) for item in items)),
        **vocab,
    )


def text(deliverable: str, body: str, **extra: Any) -> CandidateRef:
    return CandidateRef(
        deliverable_id=deliverable,
        form=OutputForm.TEXT,
        kind="inline",
        text=body,
        digest=extra.pop("digest", text_digest(body)),
        **extra,
    )


def structured(
    deliverable: str, value: Any, *, schema_ref: str = "claim_table@1", **extra: Any
) -> CandidateRef:
    form = extra.pop("form", OutputForm.STRUCTURED)
    return CandidateRef(
        deliverable_id=deliverable,
        form=form,
        kind="inline",
        value=value,
        schema_ref=schema_ref,
        digest=extra.pop("digest", sha256_digest(value)),
        **extra,
    )


def code_change(deliverable: str = "change-1", **extra: Any) -> CandidateRef:
    fields: dict[str, Any] = {
        "repository": REPO,
        "base": BASE,
        "head": HEAD,
        "changed_paths": ("src/a.py",),
    } | extra
    draft = CandidateRef(
        deliverable_id=deliverable,
        form=OutputForm.CODE_CHANGE,
        kind="inline",
        digest="sha256:" + "0" * 64,
        **fields,
    )
    return draft.model_copy(update={"digest": code_change_digest(draft)})


def digest_of(label: str) -> str:
    return sha256_digest({"label": label})


@dataclass
class Stack:
    store: OutputContractStore
    submissions: SubmissionService
    outputs: OutputFulfillmentService
    access: InvocationAccess
    host: HostAccess
    assessor: HostAccess

    @property
    def run_id(self) -> str:
        return self.access.origin.run_id

    async def start(self, access: InvocationAccess) -> Stack:
        """Another invocation of the same run: the host pins its promises at start."""

        await self.outputs.pin_invocation(self.host, access)
        return Stack(self.store, self.submissions, self.outputs, access, self.host, self.assessor)

    async def judge(
        self, subject_id: str, digest: str, *, kind: str = "output_revision", **results: str
    ) -> Any:
        """The independent assessor records one judgment; returns the receipt."""

        from mission_control.application.outputs.fulfillment import AssessmentInput

        index = results.pop("index_revision_id", None)
        supersedes = results.pop("supersedes", None)
        method = results.pop("method_pin", "mc.method.check@1")
        return await self.outputs.record_assessment(
            self.assessor,
            AssessmentInput(
                run_id=self.run_id,
                subject_kind=kind,  # type: ignore[arg-type]
                subject_id=subject_id,
                subject_digest=digest,
                requirement_results=results,  # type: ignore[arg-type]
                method_pin=method,
                policy_pin="mc.policy.default@1",
                index_revision_id=index,
                supersedes=supersedes,
            ),
        )

    async def submit(
        self, key: str, obligation_key: str, *items: CandidateRef, **kw: Any
    ) -> SubmissionAck:
        position = kw.pop("position", "draft")
        bindings = kw.pop("bindings", ())
        return await self.submissions.submit_output(
            self.access,
            SubmitOutput(submission_key=key, obligation_key=obligation_key, items=items, **kw),
            position=position,
            bindings=bindings,
        )

    async def accept(self, ack: SubmissionAck, obligation_key: str, *, generation: int = 1) -> str:
        """Promote every revision of an accepted act (the host's separate promotion act)."""

        assert ack.status == "accepted", ack.error
        for revision in ack.revisions:
            head = await self.store.accepted_head(
                self.host.scope, self.run_id, obligation_key, revision.deliverable_id
            )
            result = await self.outputs.promote_output(
                self.host,
                PromoteOutput(
                    run_id=self.run_id,
                    revision_id=revision.revision_id,
                    expected_head=None if head is None else head.revision_id,
                    generation=generation,
                ),
            )
            assert result.status == "promoted", result.error
        return ack.revisions[0].revision_id

    async def evaluate(self, **kw: Any) -> FulfillmentResult:
        pinned = await self.outputs.pin_frontier(self.host, self.run_id)
        return await self.outputs.evaluate_frontier(
            self.host, OutputSetRef(run_id=self.run_id, set_id=pinned.set_id), **kw
        )


def fulfillment(result: FulfillmentResult, key: str):  # type: ignore[no-untyped-def]
    return next(item for item in result.fulfillments if item.obligation_key == key)


def codes(result: FulfillmentResult, key: str) -> list[str]:
    return [item.code for item in fulfillment(result, key).unmet]


def host_access(
    scope: str, *, role: str = "host", origin: str = "mc-host:settlement"
) -> HostAccess:
    return HostAccess(scope=scope, actor_ref=f"{role}:test", origin_ref=origin, role=role)  # type: ignore[arg-type]


async def build_stack(
    store: OutputContractStore,
    submission_store: Any,
    access: InvocationAccess,
    *obligations: OutputObligation,
    completion: Any = None,
    clock: Any = None,
    **vocab: Any,
) -> Stack:
    """Wire the services, register the admitted promises and pin the first invocation."""

    now = clock or (lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    submissions = SubmissionService(submission_store, contracts=store, clock=now)
    # The applications' trusted-judgment pin (application.toml `assessment_pin`, WI-07 N1).
    outputs = OutputFulfillmentService(
        store, submissions, clock=now, trusted_validators=TRUSTED_VALIDATORS
    )
    stack = Stack(
        store=store,
        submissions=submissions,
        outputs=outputs,
        access=access,
        host=host_access(access.scope),
        assessor=host_access(access.scope, role="assessor", origin="mc-assessor:judge-1"),
    )
    registered = await outputs.register_promises(
        stack.host, stack.run_id, promises(*obligations, completion=completion, **vocab)
    )
    assert isinstance(registered, tuple), registered
    await outputs.pin_invocation(stack.host, access)
    return stack
