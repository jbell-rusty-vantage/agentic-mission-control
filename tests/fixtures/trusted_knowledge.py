"""A deterministic double of the KS trusted assessment transport (WI-03; never a production path).

It follows the KS rules MC relies on (``knowledge-services`` ``host/src/knowledge-operation/
assessment.ts``, proven store-backed by its ``trusted_assessment`` conformance check): the role is
the credential's ``evaluation`` grant, the producer's subject cannot observe, a sealed run takes no
observation, a decision follows the seal, an ungrounded disagreement holds, a contradiction with
evidence rejects, review needs a live grant and exact digests, a superseded decision is stale and
``decision.resolve`` answers the current successor. :class:`TrustedKnowledgeState` is the durable
store: a "restart" builds new MC objects over the same state.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tests.fixtures.knowledge_binding import stamp

from mission_control.application.ports.knowledge import (
    KnowledgeProtocolRefusal,
    KnowledgeTransportError,
)
from mission_control.contracts.knowledge_assessment import RESULT_VERSIONS
from mission_control.contracts.knowledge_protocol import (
    OperationEnvelope,
    OperationHandle,
    Ref,
    digest_bytes,
    digest_canonical,
    trusted_operation_id,
)
from mission_control.contracts.knowledge_protocol_results import (
    CredentialClaims,
    OperationStatus,
    protocol_error,
)


def ks_ref(kind: str, item_id: str, tenant: str, binding: str, version: str) -> Ref:
    return Ref(
        kind=kind,  # type: ignore[arg-type]
        id=item_id,
        version=version,
        digest=digest_canonical({"kind": kind, "id": item_id}),
        tenant=tenant,
        binding=binding,
    )


@dataclass
class ReportState:
    producer_subject: str
    verdicts: list[tuple[str, str]] = field(default_factory=list)  # (role, verdict)
    census: bool = False
    sealed: bool = False
    observed_roles: set[str] = field(default_factory=set)


@dataclass
class TrustedKnowledgeState:
    """What KS keeps durably: reports, decisions, grants, operations and result bytes."""

    reports: dict[str, ReportState] = field(default_factory=dict)
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    superseded_by: dict[str, str] = field(default_factory=dict)
    grants: set[str] = field(default_factory=set)
    review_required: bool = True
    operations: dict[str, OperationStatus] = field(default_factory=dict)
    requests: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    calls: list[tuple[str, str | None, str]] = field(default_factory=list)  # (op, role, subject)
    gets: list[str] = field(default_factory=list)  # operation.get reads, by operation id
    unreachable: bool = False
    # W1 D25: KS refuses report.seal (code, message, reason) until the seal key is registered.
    seal_refusal: tuple[str, str, str] | None = None
    # Decisions whose current eligibility a revocation (epoch advance) withdrew.
    revoked: set[str] = field(default_factory=set)


class TrustedKnowledgeDouble:
    """Implements the ``KnowledgeBindingClient`` routes the trusted bridge uses."""

    def __init__(
        self,
        state: TrustedKnowledgeState,
        *,
        verify: Callable[[str], CredentialClaims],
        clock: Callable[[], datetime],
        binding: str,
    ) -> None:
        self.state = state
        self._verifier = verify
        self._clock = clock
        self.binding = binding

    def _verify(self, credential: str | Callable[[], str]) -> CredentialClaims:
        return self._verifier(credential() if callable(credential) else credential)

    def _refuse(self, code: str, message: str, reason: str) -> None:
        error = protocol_error(code, message, occurred_at=stamp(self._clock()))  # type: ignore[arg-type]
        raise KnowledgeProtocolRefusal(error.model_copy(update={"details": {"reason": reason}}))

    async def invoke(self, envelope: OperationEnvelope, credential: Any) -> OperationHandle:
        if self.state.unreachable:
            raise KnowledgeTransportError("knowledge services unreachable")
        claims = self._verify(credential)
        operation = envelope.operation
        if operation not in claims.operations:
            self._refuse("SCOPE_DENIED", "operation not granted", "grant_missing")
        payload = envelope.input.inlinePayload if envelope.input else None
        assert isinstance(payload, dict)
        request_digest = digest_canonical(
            {
                "payload": payload,
                "evaluation": None
                if claims.evaluation is None
                else claims.evaluation.model_dump(mode="json"),
                "caller": claims.sub,
            }
        )
        prior = self.state.requests.get((operation, envelope.requestId))
        if prior is not None:
            if prior[1] != request_digest:
                self._refuse(
                    "EFFECT_CONFLICT", "request id names another request", "request_conflict"
                )
            return self.state.operations[prior[0]].handle
        role = None if claims.evaluation is None else claims.evaluation.role
        self.state.calls.append((operation, role, claims.sub))
        document = self._compute(operation, payload, claims)
        # KS's deterministic trusted operation id (a replay of the request id is the operation).
        operation_id = trusted_operation_id(envelope.tenant, operation, envelope.requestId)
        handle = OperationHandle(
            protocolVersion="ks.knowledge_operation.v2",
            tenant=envelope.tenant,
            application=envelope.application,
            binding=self.binding,
            operationId=operation_id,
        )
        data = json.dumps(document, sort_keys=True).encode("utf-8")
        artifact_id = f"result-{operation_id}"
        self.state.artifacts[artifact_id] = data
        at = stamp(self._clock())
        result = Ref(
            kind="artifact",
            id=artifact_id,
            version=RESULT_VERSIONS[operation],
            digest=digest_bytes(data),
            tenant=envelope.tenant,
            binding=self.binding,
        )
        self.state.operations[operation_id] = OperationStatus(
            handle=handle,
            state="succeeded",
            revision=3,
            createdAt=at,
            updatedAt=at,
            progressRef=None,
            pendingReviewRef=None,
            resultRef=result,
            error=None,
            unresolvedEffects=[],
            retryAfterMs=None,
            cancelRequestId=None,
        )
        self.state.requests[(operation, envelope.requestId)] = (operation_id, request_digest)
        return handle

    async def operation_get(self, handle: OperationHandle, credential: Any) -> OperationStatus:
        if self.state.unreachable:
            raise KnowledgeTransportError("knowledge services unreachable")
        self._verify(credential)
        self.state.gets.append(handle.operationId)
        status = self.state.operations.get(handle.operationId)
        if status is None:
            self._refuse("NOT_FOUND", "no such operation", "operation_unknown")
        assert status is not None
        return status

    async def artifact(self, artifact_id: str, digest: str, credential: Any) -> bytes:
        self._verify(credential)
        return self.state.artifacts[artifact_id]

    # ---------------------------------------------------------------- the KS rules

    def _report(self, payload: dict[str, Any]) -> tuple[Ref, ReportState]:
        report = Ref.model_validate(payload["report"])
        state = self.state.reports.get(report.id)
        if state is None:
            self._refuse("EXACT_REVISION_UNAVAILABLE", "unknown revision", "revision_unavailable")
        assert state is not None
        return report, state

    def _compute(
        self, operation: str, payload: dict[str, Any], claims: CredentialClaims
    ) -> dict[str, Any]:
        if operation == "report.observe":
            return self._observe(payload, claims)
        if operation == "report.seal":
            report, state = self._report(payload)
            if self.state.seal_refusal is not None:
                self._refuse(*self.state.seal_refusal)  # no operation is stored (KS: compute threw)
            state.sealed = True
            run = ks_ref(
                "verification_run",
                f"run-{report.id}",
                report.tenant,
                report.binding,
                "research-core.verification_run.v2",
            )
            return {
                "schema": "report-seal-result.v1",
                "report": report.model_dump(mode="json"),
                "run": run.model_dump(mode="json"),
            }
        if operation == "report.decide":
            return self._decide(payload)
        if operation == "report.review":
            return self._review(payload, claims)
        return self._resolve(payload)

    def _observe(self, payload: dict[str, Any], claims: CredentialClaims) -> dict[str, Any]:
        evaluation = claims.evaluation
        if evaluation is None or evaluation.role == "human_reviewer":
            self._refuse("ORIGIN_MISMATCH", "observer grant required", "evaluator_role_required")
        assert evaluation is not None
        report, state = self._report(payload)
        if state.sealed:
            self._refuse("EFFECT_CONFLICT", "sealed", "run_sealed")
        if claims.sub == state.producer_subject:
            self._refuse("INDEPENDENCE_UNPROVEN", "producer", "evaluator_is_producer")
        if evaluation.role in state.observed_roles:
            self._refuse("EFFECT_CONFLICT", "role observed", "evaluator_role_observed")
        state.observed_roles.add(evaluation.role)
        for observation in payload["observations"]:
            if observation["evaluator"]["role"] != evaluation.role:
                self._refuse("ORIGIN_MISMATCH", "role conflict", "evaluator_identity_conflict")
            state.verdicts.append((evaluation.role, observation["verdict"]))
        if payload["census"] is not None:
            if evaluation.role != "auditor":
                self._refuse("ORIGIN_MISMATCH", "auditor only", "census_requires_auditor")
            state.census = True
        return {
            "schema": "report-observation-result.v1",
            "report": report.model_dump(mode="json"),
            "role": evaluation.role,
        }

    def _decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        report, state = self._report(payload)
        if not state.sealed:
            self._refuse("EXACT_REVISION_UNAVAILABLE", "unsealed", "run_not_sealed")
        verdicts = {verdict for _role, verdict in state.verdicts}
        conditions: list[str] = []
        if "contradiction" in verdicts:
            disposition = "rejected"
            conditions.append("unmet_required:claims")
        elif len(verdicts) > 1 or not state.census or verdicts != {"full_support"}:
            disposition = "held"
            conditions.append("disputed_verdict:1" if len(verdicts) > 1 else "held_required:claims")
        else:
            disposition = "admitted"
            if self.state.review_required:
                conditions.append("review_required")
        decision_id = f"ud-{report.id}-{len(self.state.decisions) + 1}"
        document = {
            "id": decision_id,
            "subject": payload["subject"],
            "report": payload["report"],
            "use": payload["use"],
            "audience": payload["audience"],
            "boundEffectDigest": payload["boundEffectDigest"],
            "disposition": disposition,
            "conditions": conditions,
            "reviewer": None,
            "revocationEpoch": 0,
        }
        self.state.decisions[decision_id] = document
        ref = self._decision_ref(decision_id, report)
        return {
            "schema": "use-decision-result.v1",
            "purpose": payload["purpose"],
            "decision": ref.model_dump(mode="json"),
            "document": document,
            "reviewPending": disposition == "admitted" and "review_required" in conditions,
        }

    def _decision_ref(self, decision_id: str, report: Ref) -> Ref:
        return Ref(
            kind="use_decision",
            id=decision_id,
            version="research-core.use_decision.v2",
            digest=digest_canonical(self.state.decisions[decision_id]),
            tenant=report.tenant,
            binding=report.binding,
        )

    def _review(self, payload: dict[str, Any], claims: CredentialClaims) -> dict[str, Any]:
        if claims.evaluation is None or claims.evaluation.role != "human_reviewer":
            self._refuse("ORIGIN_MISMATCH", "reviewer grant required", "evaluator_role_required")
        decision = Ref.model_validate(payload["decision"])
        stored = self.state.decisions.get(decision.id)
        if stored is None:
            self._refuse("NOT_FOUND", "unknown decision", "decision_unknown")
        assert stored is not None
        if decision.id in self.state.superseded_by:
            self._refuse("STALE_DECISION", "superseded", "decision_superseded")
        if claims.sub not in self.state.grants:
            self._refuse("SCOPE_DENIED", "no live grant", "reviewer_not_qualified")
        if payload["boundEffectDigest"] != stored["boundEffectDigest"]:
            self._refuse("STALE_DECISION", "other digests", "review_binding_mismatch")
        report = Ref.model_validate(stored["report"])
        adjudication = ks_ref(
            "adjudication",
            f"adj-{decision.id}",
            report.tenant,
            report.binding,
            "research-core.adjudication.v1",
        )
        outcome = payload["outcome"]
        successor_id = f"{decision.id}-rv"
        self.state.decisions[successor_id] = stored | {
            "id": successor_id,
            "disposition": {"approve": stored["disposition"], "hold": "held", "reject": "rejected"}[
                outcome
            ],
            "conditions": [*stored["conditions"], f"reviewed:{adjudication.id}"],
            "reviewer": adjudication.model_dump(mode="json"),
        }
        self.state.superseded_by[decision.id] = successor_id
        successor = self._decision_ref(successor_id, report)
        return {
            "schema": "report-review-result.v1",
            "successor": successor.model_dump(mode="json"),
            "adjudication": adjudication.model_dump(mode="json"),
        }

    def _resolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested = Ref.model_validate(payload["decision"])
        if requested.id not in self.state.decisions:
            self._refuse("NOT_FOUND", "unknown decision", "decision_unknown")
        report = Ref.model_validate(self.state.decisions[requested.id]["report"])
        chain = [requested.id]
        while chain[-1] in self.state.superseded_by:
            chain.append(self.state.superseded_by[chain[-1]])
        current = self.state.decisions[chain[-1]]
        disposition = current["disposition"]
        review_missing = "review_required" in current["conditions"] and current["reviewer"] is None
        if disposition == "rejected":
            admissibility = {"status": "rejected", "reason": "decision_rejected"}
        elif disposition == "held":
            admissibility = {"status": "held", "reason": "decision_held"}
        elif chain[-1] in self.state.revoked:
            admissibility = {"status": "held", "reason": "stale_epoch"}
        elif review_missing:
            admissibility = {"status": "held", "reason": "review_required"}
        else:
            admissibility = {"status": "admitted", "reason": None}
        refs = [self._decision_ref(item, report).model_dump(mode="json") for item in chain]
        return {
            "schema": "use-decision-resolution.v1",
            "requested": refs[0],
            "current": refs[-1],
            "chain": refs,
            "report": current["report"],
            "subject": current["subject"],
            "use": current["use"],
            "audience": current["audience"],
            "useClass": "official" if current["audience"] == "official" else "internal",
            "disposition": disposition,
            "conditions": current["conditions"],
            "admissibility": admissibility,
            "reviewPending": disposition == "admitted" and review_missing,
            "reviewer": current["reviewer"],
            "judgment": [],
            "revocationEpoch": 0,
            "checkedAt": stamp(self._clock()),
        }
