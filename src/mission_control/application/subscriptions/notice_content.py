"""Bounded coordinator content from exact accepted revisions (OUTPUT-CONTRACTS §12, WI-19).

The candidates are the run's accepted heads of the designated promises (WI-01), never a search:
inline text and structured values are read from the exact revision and checked against its
content digest; a Knowledge Services report handle is read only through the admitted
:class:`KnowledgeExcerptReader` under the coordinator's purpose (absent: refused, never a
fallback). Every other form is referenced, not excerpted. The grant is the existing result-body
permission; the budgets and the selection are the pure :func:`plan_excerpts`.
"""

from __future__ import annotations

from typing import Final

from mission_control.application.frames.artifact_bodies import ARTIFACT_READ_PERMISSION
from mission_control.application.subscriptions.coordinator_ports import (
    AcceptedOutputs,
    ExcerptRefused,
    KnowledgeExcerptReader,
)
from mission_control.domain.authoring.canonical import canonical_json
from mission_control.domain.coordinator.attention import (
    ExcerptBundle,
    ExcerptCandidate,
    NoticeContent,
    Omission,
    plan_excerpts,
)
from mission_control.domain.outputs.contracts import ExactOutput
from mission_control.domain.outputs.rules import text_digest, value_digest
from mission_control.domain.policies.contracts import ActorContext

CONTENT_PERMISSION: Final = ARTIFACT_READ_PERMISSION
KS_HANDLE_PREFIX: Final = "kh:"
MC_ISSUER: Final = "mission-control"
KS_ISSUER: Final = "knowledge-services"


class NoticeContentService:
    def __init__(
        self, outputs: AcceptedOutputs, *, knowledge: KnowledgeExcerptReader | None = None
    ) -> None:
        self._outputs = outputs
        self._knowledge = knowledge

    async def bundle(
        self,
        scope: str,
        run_id: str,
        policy: NoticeContent,
        *,
        purpose: str,
        actor: ActorContext,
        budget: int | None = None,
    ) -> ExcerptBundle:
        """The bounded excerpts ``policy`` admits for ``actor`` (a missing grant omits all);
        ``budget`` is what remains of a page's aggregate character budget."""

        if CONTENT_PERMISSION not in actor.permissions:
            return ExcerptBundle(
                purpose=purpose,
                omissions=tuple(
                    Omission(obligation_key=key, code="GRANT_MISSING") for key in policy.obligations
                ),
                max_total_chars=policy.max_total_chars,
            )
        accepted = await self._outputs.accepted_outputs(scope, run_id)
        wanted = set(policy.obligations)
        candidates = [
            await self._candidate(output, purpose=purpose, actor=actor)
            for output in accepted
            if output.obligation_key in wanted
        ]
        return plan_excerpts(candidates, policy, purpose=purpose, budget=budget)

    async def _candidate(
        self, output: ExactOutput, *, purpose: str, actor: ActorContext
    ) -> ExcerptCandidate:
        candidate = output.candidate
        text: str | None = None
        refusal: str | None = None
        issuer = MC_ISSUER
        ref = candidate.get("ref")
        if isinstance(candidate.get("text"), str):
            text = str(candidate["text"])
            if text_digest(text) != output.content_digest:
                text, refusal = None, "DIGEST_MISMATCH"
        elif "value" in candidate and candidate.get("value") is not None:
            if value_digest(candidate["value"]) != output.content_digest:
                refusal = "DIGEST_MISMATCH"
            else:
                text = canonical_json(candidate["value"]).decode("utf-8")
        elif isinstance(ref, str) and ref.startswith(KS_HANDLE_PREFIX):
            issuer = KS_ISSUER
            if self._knowledge is None:
                refusal = "KNOWLEDGE_ACCESS_UNAVAILABLE"
            else:
                try:
                    text = await self._knowledge.read_text(
                        ref, output.content_digest, purpose=purpose, actor=actor
                    )
                except ExcerptRefused as refused:
                    refusal = refused.code
        else:
            refusal = "NOT_TEXTUAL"
        return ExcerptCandidate(
            obligation_key=output.obligation_key,
            deliverable_id=output.deliverable_id,
            revision_id=output.revision_id,
            revision=output.revision,
            form=output.form.value,
            content_digest=output.content_digest,
            status="accepted",
            issuer=issuer,
            attribution=output.producer_origin_ref,
            text=text,
            refusal=refusal,
        )


__all__ = ["CONTENT_PERMISSION", "KS_HANDLE_PREFIX", "NoticeContentService"]
