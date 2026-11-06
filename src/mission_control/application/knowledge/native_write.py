"""Native write of an accepted report inside ONE invocation (Sprint OC W1; ADR-0059/0060).

A native write's KS decision must bind the exact native digest of the invocation that applies
it: the AIDB plan binds the originating origin (`knowledge-db/src/ingestion/plan.ts`
`plannedEffect`), the Biotech intent envelope is checked against it (`apply_payload`), and the
gateway accepts an apply only from the originating invocation (`gateway._recovery_for`). So the
host runs the whole sequence inside the invocation whose agent called ``knowledge_apply`` with a
REPORT member of its sealed plan:

1. the report member is in the receiver's sealed plan and currently officially usable
   (``TrustedReferenceUses``' predicate, so delivery, fulfillment and apply agree);
2. the application's native intent is built from the exact report records through the
   application's EXISTING schema (``NativeIntentBuilder``; MC invents no report->domain mapping,
   ESCALATION H11: AI Engineer has ``claim.materialize`` with inline evidence claims, Biotech has
   no report/record intent and refuses ``SCHEMA_UNSUPPORTED``);
3. the exact native digest for this invocation (``NativePlanPreview``: computed in MC for the
   intent-envelope layout, answered by the KS ``knowledge.plan_preview`` operation for AIDB);
4. ``report.decide`` (plan level, official, that digest) through the trusted bridge;
5. ``record_apply_decision`` (0059 + 0072 ``subject_ref``/``invocation_ref``);
6. apply through the existing ``apply_decision`` path, or, when the decision waits on a
   qualified review, a typed ``pending_review`` answer: the same invocation's saved-result
   settlement pass (same origin identity) applies once KS reports the decision usable
   (integrator decision, provisional under ESCALATION H12).

Replay preserves immutable decision history. A decide-before-record crash with an unchanged
digest reuses the stable decide request. A changed digest leaves the earlier KS decision as
harmless retained lineage, with no MC apply admission: only recorded decisions can apply.
Fresh resolutions observe review/revocation changes. A recorded applied or uncertain effect
is recovered from its journal before any new preview, preventing duplicate dispatch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from mission_control.application.context.resolution import ContentResolutionService
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.judgment import TrustedJudgmentBridge, _governors
from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.application.knowledge.trusted_settlement import TrustedAssessmentPlans
from mission_control.application.outputs.submission_service import SelectedItem
from mission_control.application.ports.knowledge import RecordedUseDecision
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.contracts.knowledge_assessment import DecisionResolution
from mission_control.contracts.knowledge_protocol import (
    Ref,
    bound_effect_digest,
    canonical_json,
    digest_bytes,
    digest_canonical,
)
from mission_control.domain.knowledge.judgment import official_use_evidence
from mission_control.domain.outputs.contracts import ExactOutput
from mission_control.domain.resolution.resolved import KnowledgePortBinding

NATIVE_DECISION_VERSION = "use-decision.v1"
# KS `normalizedValuesDigest({})` (research-core ports/oracle.ts: the canonical digest of `{}`): the
# plan decision is requested with empty normalized values, so the preview must echo exactly this.
EMPTY_NORMALIZED_VALUES = digest_canonical({})
PLAN_PREVIEW_CAPABILITY = "knowledge.plan-preview@1"


@dataclass(frozen=True)
class NativePlanDigest:
    """The exact native plan digest of one invocation (the KS ``knowledge.plan_preview``
    answer, or the MC computation for the intent-envelope layout)."""

    semantic_payload_digest: str
    bound_effect_digest: str
    plan_id: str | None = None
    normalized_values_digest: str | None = None
    processed_epoch: int | None = None
    migration_head: str | None = None


class NativePlanPreview(Protocol):
    async def preview(
        self, plan: Mapping[str, Any], *, effect_key: str, access: InvocationAccess
    ) -> NativePlanDigest: ...


class LocalIntentEnvelopePreview:
    """The intent-envelope layout: the bound digest is over the plan's canonical bytes and this
    invocation's origin, exactly what ``apply_payload._intent_envelope`` checks at apply."""

    async def preview(
        self, plan: Mapping[str, Any], *, effect_key: str, access: InvocationAccess
    ) -> NativePlanDigest:
        del effect_key
        native = canonical_json(dict(plan)).encode("utf-8")
        return NativePlanDigest(
            semantic_payload_digest=digest_bytes(native),
            bound_effect_digest=bound_effect_digest(native, access.wire_origin()),
        )


class KnowledgePlanPreview:
    """AIDB: the KS ``knowledge.plan_preview`` operation (read-only, no write). The request is the
    same native payload MC sends for ``knowledge.apply`` (plan-with-exact-use layout) without the
    use-decision fields; the answer names the plan's exact digests for this caller."""

    def __init__(
        self,
        gateway: Any,
        *,
        capability_pin: str = PLAN_PREVIEW_CAPABILITY,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._gateway = gateway
        self._pin = capability_pin
        self._clock = clock

    async def preview(
        self, plan: Mapping[str, Any], *, effect_key: str, access: InvocationAccess
    ) -> NativePlanDigest:
        payload = dict(plan) | {
            "exactUse": {
                "effectKey": effect_key,
                "originatingOrigin": access.wire_origin().model_dump(mode="json"),
            }
        }
        answer = await self._gateway.plan_preview(
            payload,
            access,
            capability_pin=self._pin,
            governors=_governors(self._clock),
            # Each call is a new dispatch (fresh credential nonce); the key only names it.
            request_key="plan-preview-" + digest_canonical(payload)[7:47],
        )
        if answer.normalizedValuesDigest != EMPTY_NORMALIZED_VALUES:
            # The plan decision binds no normalized values (KS echoes the intent's digest, else
            # the digest of `{}`): any other echo would never pass exact-use admission.
            raise KnowledgeRefused(
                "SCHEMA_UNSUPPORTED",
                "the native plan binds normalized values this decision does not declare",
            )
        return NativePlanDigest(
            semantic_payload_digest=answer.semanticPayloadDigest,
            bound_effect_digest=answer.boundEffectDigest,
            plan_id=answer.planId,
            normalized_values_digest=answer.normalizedValuesDigest,
            processed_epoch=answer.processedEpoch,
            migration_head=answer.migrationHead,
        )


@dataclass(frozen=True)
class ReportRecords:
    """The exact accepted report revision a native intent is built from."""

    handle: str
    digest: str
    run_id: str
    assertions: tuple[tuple[str, str], ...]  # (assertion id, proposition)


class NativeIntentBuilder(Protocol):
    def build(
        self, report: ReportRecords, *, access: InvocationAccess, use: str, audience: str
    ) -> dict[str, Any]: ...


class ClaimMaterializeIntentBuilder:
    # The intent schema version is the profile's apply contract (`<name>.<version>`): the kernel
    # names no application contract (bootstrap passes it from the knowledge port).

    """The AIDB ingestion intent layout (its schema's existing kinds): one
    ``claim.materialize`` proposal naming every report assertion as an inline evidence claim of
    the report's KS run (``evidence.claims``/``verificationRuns``), admitted by AIDB only under
    the exact-use decision (``exactUseEvidenceOracle``). A 1:1 copy of records the schema defines:
    assertion id -> claim id, proposition -> statement; no domain mapping, no entity resolution."""

    def __init__(self, schema_version: str) -> None:
        self._schema_version = schema_version

    def build(
        self, report: ReportRecords, *, access: InvocationAccess, use: str, audience: str
    ) -> dict[str, Any]:
        if not report.assertions:
            raise KnowledgeRefused("SCHEMA_UNSUPPORTED", "the report states no assertion to write")
        identity = digest_canonical(
            {"report": report.handle, "digest": report.digest, "origin": access.origin.digest()}
        )
        claims = [
            {
                "runId": report.run_id,
                "claimId": claim_id,
                "claimType": "attribute",
                "statement": proposition,
            }
            for claim_id, proposition in report.assertions
        ]
        return {
            "schemaVersion": self._schema_version,
            "intentId": "mc-" + identity[7:47],
            "context": {
                "tenantId": access.origin.tenant_id,
                "actor": {"kind": "agent", "id": access.origin.operation_id[:200]},
            },
            "evidence": {"verificationRuns": [{"runId": report.run_id}], "claims": claims},
            "proposals": [
                {
                    "proposalId": "report-claims",
                    "kind": "claim.materialize",
                    "claimIds": [claim_id for claim_id, _ in report.assertions],
                    "runId": report.run_id,
                }
            ],
            "declaredUse": {"use": use, "audience": audience},
        }


class NoNativeIntent:
    """An application whose native schema has no report/record intent (Biotech): MC invents no
    report->domain mapping (ESCALATION H11), so the native write refuses typed."""

    def build(
        self, report: ReportRecords, *, access: InvocationAccess, use: str, audience: str
    ) -> dict[str, Any]:
        raise KnowledgeRefused(
            "SCHEMA_UNSUPPORTED",
            "this application's native schema has no intent for report records; a report->"
            "domain mapping is product schema MC does not invent (ESCALATION H11)",
        )


@dataclass(frozen=True)
class NativeWriteOutcome:
    """``applied``/``refused`` carry the apply result; ``pending_review`` the exact decision."""

    state: Literal["applied", "noop", "partial", "pending_review", "pending_effect", "refused"]
    decision: RecordedUseDecision
    pending_reviews: tuple[str, ...] = ()
    result: Any = None
    refusal_code: str | None = None

    def document(self) -> dict[str, Any]:
        result = self.result.document() if hasattr(self.result, "document") else {}
        return {
            "decision": self.decision.handle,
            "subject_ref": self.decision.subject_ref,
            "state": self.state,
            "refusal_code": self.refusal_code,
            **result,
        }


@dataclass(frozen=True)
class NativeSettlement:
    outcomes: tuple[NativeWriteOutcome, ...] = field(default_factory=tuple)

    @property
    def pending_reviews(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(ref for row in self.outcomes for ref in row.pending_reviews))


def decision_handle(binding: str, decision_id: str) -> str:
    return f"kh:{binding}/decision/{decision_id}@{NATIVE_DECISION_VERSION}"


class NativeWriteService:
    """The in-invocation native write sequence (see the module docstring)."""

    def __init__(
        self,
        *,
        bridge: TrustedJudgmentBridge,
        plans: TrustedAssessmentPlans,
        outputs: OutputContractStore,
        reports: ContentResolutionService,
        port: KnowledgePortBinding,
        builder: NativeIntentBuilder,
        preview: NativePlanPreview,
        decisions: Any,
        existing_effect: Any = None,
    ) -> None:
        self._bridge = bridge
        self._plans = plans
        self._outputs = outputs
        self._reports = reports
        self._port = port
        self._builder = builder
        self._preview = preview
        self._decisions = decisions
        self._existing_effect = existing_effect

    async def eligible_revision(
        self, access: InvocationAccess, handle: str, digest: str, plan_reports: Mapping[str, str]
    ) -> tuple[ExactOutput, str]:
        """The accepted, officially usable revision the sealed plan delivered (else refused)."""

        if plan_reports.get(handle) != digest:
            raise KnowledgeRefused(
                "SCOPE_DENIED", "the report member is not in this invocation's sealed plan"
            )
        heads = [
            item
            for item in await self._outputs.accepted_outputs(access.scope, access.origin.run_id)
            if item.candidate.get("ref") == handle and item.content_digest == digest
        ]
        assessments = await self._outputs.output_assessments(access.scope, access.origin.run_id)
        for head in heads:
            evidence = official_use_evidence(assessments, head.revision_id, head.content_digest)
            if evidence is not None:
                return head, evidence
        raise KnowledgeRefused(
            "STALE_DECISION",
            "the report revision has no current official use (held, revoked or not accepted)",
        )

    async def write(
        self,
        access: InvocationAccess,
        handle: str,
        digest: str,
        *,
        plan_reports: Mapping[str, str],
        attempt: int,
        apply: Any,
    ) -> NativeWriteOutcome:
        if plan_reports.get(handle) != digest:
            raise KnowledgeRefused("SCOPE_DENIED", "report is outside this sealed plan")
        subject_ref = f"{handle}#{digest}"
        recorded = [
            item
            for item in await self._decisions.for_invocation(access.scope, access.invocation_ref)
            if item.subject_ref == subject_ref
        ]
        # An applied or uncertain journal row wins before a new preview: drift cannot
        # turn a crash-after-commit into a second native effect.
        for decision in recorded:
            if self._existing_effect is not None:
                existing = await self._existing_effect(decision.handle, access)
                if existing is not None and not self._retryable_rejection(existing):
                    return self._outcome(decision, existing)
        revision, evidence = await self.eligible_revision(access, handle, digest, plan_reports)
        intent, native, report_ref, use, report_run = await self._prepare(
            access, revision, evidence, attempt=attempt
        )
        matching = [
            row for row in recorded if row.bound_effect_digest == native.bound_effect_digest
        ]
        decision = (
            max(matching, key=lambda row: (row.processed_epoch, row.handle)) if matching else None
        )
        if decision is None:
            decision = await self._decide(
                access,
                revision,
                evidence,
                subject_ref,
                attempt=attempt,
                prepared=(intent, native, report_ref, use, report_run),
            )
        try:
            return await self._apply_if_usable(
                access,
                decision,
                report=report_ref,
                report_run=report_run,
                attempt=attempt,
                apply=apply,
            )
        except KnowledgeRefused as refusal:
            if refusal.code not in {"EFFECT_CONFLICT", "STALE_DECISION"}:
                raise
            # One bounded refresh closes preview-to-apply drift. If nothing changed,
            # retain the refusal rather than manufacture another decision or spin.
            prepared = await self._prepare(access, revision, evidence, attempt=attempt)
            if prepared[1].bound_effect_digest == decision.bound_effect_digest:
                raise
            successor = await self._decide(
                access, revision, evidence, subject_ref, attempt=attempt, prepared=prepared
            )
            return await self._apply_if_usable(
                access,
                successor,
                report=prepared[2],
                report_run=prepared[4],
                attempt=attempt,
                apply=apply,
            )

    async def settle(
        self, access: InvocationAccess, *, attempt: int, apply: Any
    ) -> NativeSettlement:
        """Reconstruct outcomes from immutable decisions and the durable effect journal.

        Each subject is independent. Refusals are visible and cannot suppress another
        subject's dispatch. Old decisions remain immutable; only the current preview
        selects which digest is eligible for an unapplied subject.
        """
        subjects: dict[str, list[RecordedUseDecision]] = {}
        for row in await self._decisions.for_invocation(access.scope, access.invocation_ref):
            if row.subject_ref is not None:
                subjects.setdefault(row.subject_ref, []).append(row)
        outcomes: list[NativeWriteOutcome] = []
        for subject, rows in sorted(subjects.items()):
            representative = max(rows, key=lambda row: (row.processed_epoch, row.handle))
            try:
                handle, digest = subject.rsplit("#", 1)
                outcome = await self.write(
                    access,
                    handle,
                    digest,
                    plan_reports={handle: digest},
                    attempt=attempt,
                    apply=apply,
                )
            except KnowledgeRefused as refusal:
                outcome = NativeWriteOutcome("refused", representative, refusal_code=refusal.code)
            outcomes.append(outcome)
        return NativeSettlement(tuple(outcomes))

    @staticmethod
    def _outcome(decision: RecordedUseDecision, result: Any) -> NativeWriteOutcome:
        from mission_control.domain.knowledge.effects import JournalState

        state = getattr(result, "state", None)
        refusal = getattr(result, "refusal_code", None)
        if state is JournalState.NOOP:
            return NativeWriteOutcome("noop", decision, result=result)
        if state is JournalState.PARTIAL:
            return NativeWriteOutcome("partial", decision, result=result)
        if refusal is not None or state is JournalState.REJECTED:
            return NativeWriteOutcome(
                "refused", decision, result=result, refusal_code=refusal or "STALE_DECISION"
            )
        return NativeWriteOutcome(
            "applied" if state is None or state is JournalState.APPLIED else "pending_effect",
            decision,
            result=result,
        )

    async def _prepare(
        self, access: InvocationAccess, revision: ExactOutput, evidence: str, *, attempt: int
    ) -> tuple[dict[str, Any], NativePlanDigest, Ref, Any, str]:
        report_ref = _report_ref(revision, access.origin.tenant_id)
        cited = evidence.removeprefix("ks-use-decision:")
        decision_id, sep, decision_digest = cited.partition("@")
        if not sep:
            raise KnowledgeRefused("SCHEMA_UNSUPPORTED", "report decision lacks its exact digest")
        resolved_decision = await self._bridge.resolve(
            access,
            Ref(
                kind="use_decision",
                id=decision_id,
                version="research-core.use_decision.v2",
                digest=decision_digest,
                tenant=access.origin.tenant_id,
                binding=self._port.binding_id,
            ),
            attempt=attempt,
            fresh=True,
        )
        if resolved_decision.report != report_ref or not resolved_decision.officially_usable:
            raise KnowledgeRefused(
                "STALE_DECISION", "report decision no longer admits this revision"
            )
        run_id = resolved_decision.runId
        if run_id is None:
            raise KnowledgeRefused(
                "SCHEMA_UNSUPPORTED", "KS resolution names no authoritative runId"
            )
        resolved = await self._reports.resolve(
            SelectedItem(
                kind="handle", ref=str(revision.candidate["ref"]), digest=revision.content_digest
            ),
            access,
            purpose="official",
        )
        records = ReportRecords(
            handle=str(revision.candidate["ref"]),
            digest=revision.content_digest,
            run_id=run_id,
            assertions=tuple(
                (str(item.record.get("id")), str(item.record.get("proposition")))
                for item in resolved.package.assertions
                if isinstance(item.record.get("id"), str)
                and isinstance(item.record.get("proposition"), str)
            ),
        )
        plan = await self._plans.plan(access, revision)
        intent = self._builder.build(
            records, access=access, use=plan.use.use, audience=plan.use.audience
        )
        intent = await self._successor_intent(access, revision, intent)
        effect_key = (
            "preview-"
            + digest_canonical({"intent": intent, "origin": access.origin.digest()})[7:47]
        )
        native = await self._preview.preview(intent, effect_key=effect_key, access=access)
        return intent, native, report_ref, plan.use, run_id

    @staticmethod
    def _retryable_rejection(result: Any) -> bool:
        from mission_control.domain.knowledge.effects import JournalState

        return result.state is JournalState.REJECTED and result.refusal_code in {
            "STALE_DECISION",
            "EFFECT_CONFLICT",
        }

    async def _successor_intent(
        self, access: InvocationAccess, revision: ExactOutput, intent: dict[str, Any]
    ) -> dict[str, Any]:
        """A new admitted intent only after the prior native effect rejected before commit.

        The journal terminal fence rules out a late commit. Unknown/partial/noop/applied
        effects are recovered before this method is reached. The lineage uses immutable
        plan+decision identities, so crash/replay selects the same successor without a
        mutable head or a clock. No domain proposal is changed.
        """
        if self._existing_effect is None:
            return intent
        subject = f"{revision.candidate['ref']}#{revision.content_digest}"
        rows = [
            row
            for row in await self._decisions.for_invocation(access.scope, access.invocation_ref)
            if row.subject_ref == subject
        ]
        current = intent.get("intentId")
        for _ in range(len(rows) + 1):
            rejected = []
            for row in rows:
                if row.plan.get("intentId") != current:
                    continue
                effect = await self._existing_effect(row.handle, access)
                if effect is not None and self._retryable_rejection(effect):
                    rejected.append(row)
            if not rejected:
                return intent
            if not isinstance(current, str) or "idempotencyKey" in intent:
                raise KnowledgeRefused(
                    "SCHEMA_UNSUPPORTED", "this native intent has no supported successor identity"
                )
            # Multiple decisions over the same intent may have all rejected. Every candidate
            # is harmless; this deterministic choice is independent of store iteration order.
            prior = max(rejected, key=lambda row: (row.processed_epoch, row.handle))
            current = (
                "mc-retry-"
                + digest_canonical(
                    {
                        "prior_intent": current,
                        "rejected_decision": prior.handle,
                        "bound_digest": prior.bound_effect_digest,
                    }
                )[7:47]
            )
            intent = dict(intent) | {"intentId": current}
        raise KnowledgeRefused("EFFECT_CONFLICT", "native rejection lineage could not resolve")

    async def _decide(
        self,
        access: InvocationAccess,
        revision: ExactOutput,
        evidence: str,
        subject_ref: str,
        *,
        attempt: int,
        prepared: tuple[dict[str, Any], NativePlanDigest, Ref, Any, str] | None = None,
    ) -> RecordedUseDecision:
        intent, native, report_ref, use, _report_run = prepared or await self._prepare(
            access, revision, evidence, attempt=attempt
        )
        decision, resolution = await self._bridge.decide_native_plan(
            access,
            report_ref,
            use,
            revision_id=revision.revision_id,
            bound_effect_digest=native.bound_effect_digest,
            target_schema=f"{self._port.apply_contract_name}.{self._port.apply_contract_version}",
            attempt=attempt,
        )
        return await self._bridge.record_apply_decision(
            access,
            RecordedUseDecision(
                handle=decision_handle(self._port.binding_id, decision.id),
                binding_id=self._port.binding_id,
                tenant_id=access.origin.tenant_id,
                use_decision_id=decision.id,
                bound_effect_digest=native.bound_effect_digest,
                processed_epoch=max(resolution.revocationEpoch, native.processed_epoch or 0),
                plan=intent,
                normalized_values_digest=native.normalized_values_digest,
                use=use.use,
                audience=use.audience,
                subject_ref=subject_ref,
                invocation_ref=access.invocation_ref,
                decision_digest=decision.digest,
            ),
        )

    async def _apply_if_usable(
        self,
        access: InvocationAccess,
        decision: RecordedUseDecision,
        *,
        report: Ref,
        report_run: str,
        attempt: int,
        apply: Any,
    ) -> NativeWriteOutcome:
        if decision.invocation_ref != access.invocation_ref:
            raise KnowledgeRefused(
                "ORIGIN_MISMATCH", "a plan decision is applied only by the invocation it binds"
            )
        ref = Ref(
            kind="use_decision",
            id=decision.use_decision_id,
            version="research-core.use_decision.v2",
            digest=decision.decision_digest or "",
            tenant=decision.tenant_id,
            binding=decision.binding_id,
        )
        resolution = await self._bridge.resolve(access, ref, attempt=attempt, fresh=True)
        self._check_resolution(decision, ref, resolution, report=report, report_run=report_run)
        if not resolution.reviewPending and not resolution.officially_usable:
            raise KnowledgeRefused(
                "STALE_DECISION", "Knowledge Services no longer admits the native plan"
            )
        if resolution.reviewPending:
            return NativeWriteOutcome(
                "pending_review",
                decision,
                pending_reviews=(
                    f"ks-use-decision:{resolution.current.id}@{resolution.current.digest}",
                ),
            )
        # The root identifies the logical effect forever. Only fresh successor admission
        # authority changes; the native executor checks the original digest/epoch/values.
        result = (
            await apply(decision.handle)
            if resolution.current == ref
            else await apply(decision.handle, admission=resolution.current)
        )
        refusal = getattr(result, "refusal_code", None)
        if refusal in {"EFFECT_CONFLICT", "STALE_DECISION"}:
            raise KnowledgeRefused(refusal, "native plan changed before apply")
        return self._outcome(decision, result)

    @staticmethod
    def _check_resolution(
        decision: RecordedUseDecision,
        root: Ref,
        resolution: DecisionResolution,
        *,
        report: Ref,
        report_run: str,
    ) -> None:
        chain = resolution.chain
        valid = (
            resolution.requested == root
            and chain[0] == root
            and chain[-1] == resolution.current
            and len({item.id for item in chain}) == len(chain)
            and all(
                item.kind == "use_decision"
                and item.tenant == root.tenant
                and item.binding == root.binding
                and item.version == root.version
                for item in chain
            )
            and resolution.report == report
            and resolution.subject == report
            and resolution.use == decision.use
            and resolution.audience == decision.audience
            and resolution.runId == report_run
        )
        if not valid:
            raise KnowledgeRefused(
                "STALE_DECISION", "native admission resolution differs from root context"
            )


def _report_ref(revision: ExactOutput, tenant: str) -> Ref:
    from mission_control.application.knowledge.trusted_settlement import report_ref

    ref = report_ref(revision, tenant=tenant)
    if ref is None:
        raise KnowledgeRefused("SCHEMA_UNSUPPORTED", "the member names no exact KS report")
    return ref


__all__ = [
    "PLAN_PREVIEW_CAPABILITY",
    "ClaimMaterializeIntentBuilder",
    "KnowledgePlanPreview",
    "LocalIntentEnvelopePreview",
    "NativeIntentBuilder",
    "NativePlanDigest",
    "NativePlanPreview",
    "NativeWriteOutcome",
    "NativeWriteService",
    "NoNativeIntent",
    "ReportRecords",
    "decision_handle",
]
