"""The explicit adoption act: an exact accepted revision becomes a submission of another
obligation (OVE-176 nested exports; the same act WI-16 links use).

OUTPUT-CONTRACTS §§9-10 (OC-D56, OC-D80): explicit exports with required provenance and explicit
obligation adoption. ``OutputAdoptionService.adopt`` takes the receiving invocation's host access
(the parent unit attempt), its bound position, the target obligation and the exact source
revisions (run, revision id, content digest). It:

1. verifies each source is the *accepted* head of its source run with exactly that digest
   (a draft, a held or rejected revision, a superseded head or another digest refuses);
2. submits the source's exact candidate bytes for the target obligation through the one
   submission act (``SubmissionService.submit_output``) under the receiving invocation, with the
   source revision as a derivation ref, so the target's own contract checks apply unchanged;
3. records an ``adopter`` lineage fact (0051, actor kind ``obligation``) on each source revision:
   adoption is never a producer fact.

Adoption grants nothing: the new revision is a draft of the target run, and the target's own
assessment, promotion and fulfillment decide it (no implicit approval). Idempotent: the
submission key binds the exact sources, so a redelivery returns the recorded revisions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.ports.knowledge import ContentLineageStore, LineageEntry
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.knowledge.lineage import (
    ADOPTION_ACT,
    ActorKind,
    LineageFact,
    ProvenanceRole,
)
from mission_control.domain.outputs.contracts import (
    AdmittedBinding,
    CandidateRef,
    ExactOutput,
    SubmissionAck,
    SubmitOutput,
)


@dataclass(frozen=True)
class AdoptionSource:
    """One exact revision to adopt: ``output:<revision_id>@<content_digest>`` of ``run_id``."""

    run_id: str
    revision_id: str
    content_digest: str

    @classmethod
    def parse(cls, run_id: str, ref: str) -> AdoptionSource:
        body = ref.removeprefix("output:")
        revision, separator, digest = body.partition("@")
        if not ref.startswith("output:") or not separator or not revision:
            raise ValueError(f"{ref} is not an exact output revision ref")
        return cls(run_id=run_id, revision_id=revision, content_digest=digest)


@dataclass(frozen=True)
class AdoptionResult:
    adopted: bool
    revisions: tuple[str, ...] = ()
    code: str = ""
    detail: str = ""


class AcceptedOutputs(Protocol):
    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]: ...


class SubmissionAct(Protocol):
    async def submit_output(
        self,
        access: InvocationAccess,
        request: SubmitOutput,
        *,
        position: str | None,
        bindings: tuple[AdmittedBinding, ...] = (),
        caller_origin_ref: str | None = None,
    ) -> SubmissionAck: ...


def exact_ref(output: ExactOutput) -> str:
    return f"output:{output.revision_id}@{output.content_digest}"


class OutputAdoptionService:
    def __init__(
        self,
        *,
        outputs: AcceptedOutputs,
        submissions: SubmissionAct,
        lineage: ContentLineageStore | None = None,
        actor_ref: str = "mission-control:adoption",
    ) -> None:
        self._outputs = outputs
        self._submissions = submissions
        self._lineage = lineage
        self._actor = actor_ref

    async def adopt(
        self,
        access: InvocationAccess,
        *,
        position: str | None,
        target_obligation: str,
        sources: Sequence[AdoptionSource],
        act: str,
        at: datetime,
    ) -> AdoptionResult:
        if not sources:
            return AdoptionResult(False, code="adoption_without_source")
        scope = access.scope
        exact: list[ExactOutput] = []
        for source in sources:
            accepted = {
                item.revision_id: item
                for item in await self._outputs.accepted_outputs(scope, source.run_id)
            }
            found = accepted.get(source.revision_id)
            if found is None or found.content_digest != source.content_digest:
                return AdoptionResult(
                    False,
                    code="adoption_source_not_accepted",
                    detail=f"output:{source.revision_id} is not an accepted head of "
                    f"{source.run_id} with digest {source.content_digest}",
                )
            exact.append(found)
        items = tuple(CandidateRef.model_validate(item.candidate) for item in exact)
        if any(
            item.digest != output.content_digest for item, output in zip(items, exact, strict=True)
        ):
            return AdoptionResult(False, code="adoption_digest_mismatch")
        derivations = tuple(exact_ref(item) for item in exact)
        key = (
            "adopt:"
            + sha256_digest(
                {"act": act, "target": target_obligation, "sources": list(derivations)}
            ).removeprefix("sha256:")[:48]
        )
        ack = await self._submissions.submit_output(
            access,
            SubmitOutput(
                submission_key=key,
                obligation_key=target_obligation,
                mode="final",
                items=items,
                derivation_refs=derivations,
            ),
            position=position,
        )
        if ack.status != "accepted":
            error = ack.error
            return AdoptionResult(
                False,
                code=f"adoption_refused:{error.code.value if error is not None else 'unknown'}",
                detail=error.safe_message if error is not None else "",
            )
        revisions = tuple(
            f"output:{item.revision_id}@{item.content_digest}" for item in ack.revisions
        )
        if self._lineage is not None:
            await self._lineage.record(
                scope,
                [
                    LineageEntry(
                        fact=LineageFact(
                            subject_handle=exact_ref(output),
                            role=ProvenanceRole.ADOPTER,
                            actor_kind=ActorKind.OBLIGATION,
                            actor_ref=f"{access.origin.run_id}:{target_obligation}",
                            fact={
                                "act": ADOPTION_ACT,
                                "adoption": act,
                                "submission_key": key,
                                "revisions": list(revisions),
                            },
                        ),
                        subject_kind="output",
                        subject_digest=output.content_digest,
                        run_id=output.run_id,
                    )
                    for output in exact
                ],
                actor_ref=self._actor,
                at=at,
            )
        return AdoptionResult(True, revisions=revisions)


__all__ = [
    "AdoptionResult",
    "AdoptionSource",
    "OutputAdoptionService",
    "exact_ref",
]
