"""Validate host-selected Goal subjects and deliver complete persisted verifier feedback."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Protocol

from mission_control.application.execution.operations.semantic_operation_bindings import (
    SemanticOperationBindingRepository,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.packet import (
    ContextSourceKind,
    ContextTrust,
    ExpandMode,
    PackCandidate,
)
from mission_control.domain.context.transfer import ProducerAttempt
from mission_control.domain.execution.contracts import PromptSegment, PromptTrustClass
from mission_control.domain.graph_runtime.identities import GoalDirectedUnitLocation
from mission_control.domain.programs.goal_directed_runtime import GoalOperationPreparationRequest
from mission_control.domain.programs.runtime_units import goal_operation_id


class GoalContextDocuments(Protocol):
    async def load_iteration(
        self, request_scope: str, run_id: str, semantic_key: str
    ) -> dict[str, Any] | None: ...

    async def load_verification(
        self, request_scope: str, run_id: str, verification_id: str
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class GoalContext:
    subject: ProducerAttempt | None = None
    feedback: PromptSegment | None = None

    def candidates(self) -> tuple[PackCandidate, ...]:
        if self.feedback is None:
            return ()
        content = self.feedback.content.encode("utf-8")
        return (
            PackCandidate(
                source_kind=ContextSourceKind.PROGRESS_REVIEW,
                source_ref=self.feedback.source_ref,
                content_digest="sha256:" + sha256(content).hexdigest(),
                bytes=len(content),
                media_type="application/json",
                trust=ContextTrust.UNTRUSTED_CONTENT,
                mandatory=True,
                expand=ExpandMode.INLINE,
                text=self.feedback.content,
            ),
        )


async def resolve_goal_context(
    request: GoalOperationPreparationRequest,
    documents: GoalContextDocuments,
    bindings: SemanticOperationBindingRepository,
) -> GoalContext:
    source = request.subject_execution
    feedback = request.verification_feedback
    if source is None:
        return GoalContext()
    identity = source.identity.iteration
    expected_iteration = request.goal_iteration - (request.operation_role == "executor")
    # W1 D36: a verifier judges its own iteration's executor even when that executor failed
    # irrecoverably (`_executor_observation`: "the verifier sees the failure"); only an
    # executor's repair context needs a completed predecessor.
    settled = ("completed",) if request.operation_role == "executor" else ("completed", "failed")
    if (
        source.disposition not in settled
        or identity.run_id != request.run_id
        or identity.execution_epoch != request.execution_epoch
        or identity.goal_iteration != expected_iteration
        or expected_iteration < 1
    ):
        raise ValueError("Goal subject is not the exact completed producing iteration")
    stored = await documents.load_iteration(
        request.request_scope, request.run_id, source.identity.semantic_key
    )
    if (
        stored is None
        or stored.get("goal_revision_id") != identity.goal_revision_id
        or sha256_digest(stored.get("result")) != sha256_digest(source.to_payload())
    ):
        raise ValueError("Goal subject differs from its scoped immutable execution record")
    same_revision = identity.goal_revision_id == request.goal_revision_id
    successor = (
        feedback is not None
        and request.goal_revision.parent_revision_id == identity.goal_revision_id
        and feedback.proposed_revision == request.goal_revision
    )
    if not same_revision and not successor:
        raise ValueError("Goal subject does not belong to this revision or its exact predecessor")
    binding = await bindings.get_binding_by_id(
        source.operation_binding_ref, request_scope=request.request_scope
    )
    if binding is None:
        raise ValueError("Goal subject operation binding is unavailable")
    unit = binding.runtime_unit
    location = None if unit is None else unit.location
    if (
        binding.request_scope != request.request_scope
        or binding.run_id != request.run_id
        or binding.operation_id != goal_operation_id(expected_iteration, "executor")
        or binding.semantic_attempt_key != source.operation_identity
        or binding.effective_configuration_digest != request.effective_configuration_digest
        or binding.session_id != source.session_id
        or binding.workspace.workspace_id != source.workspace_id
        or unit is None
        or unit.execution_epoch != identity.execution_epoch
        or unit.unit_kind != "goal_executor"
        or not isinstance(location, GoalDirectedUnitLocation)
        or location.goal_iteration != expected_iteration
        or location.goal_revision_id != identity.goal_revision_id
        or location.operation_role != "executor"
        or location.agent_run != source.identity.agent_run
        or location.session_generation != source.identity.session_generation
        or binding.lane_dispatch is None
    ):
        raise ValueError("Goal subject binding does not prove the exact producer attempt")
    subject = ProducerAttempt(
        operation_ref=binding.operation_id,
        operation_attempt=binding.operation_attempt,
        execution_generation=binding.lane_dispatch.execution_generation,
    )
    if feedback is None:
        if request.operation_role == "executor":
            raise ValueError("Goal repair subject requires its complete verified feedback")
        return GoalContext(subject=subject)
    payload = asdict(feedback)
    digest_payload = {key: value for key, value in payload.items() if key != "verification_digest"}
    retained = await documents.load_verification(
        request.request_scope, request.run_id, feedback.verification_id
    )
    if (
        feedback.executor_identity != source.identity
        or feedback.verification_digest != sha256_digest(digest_payload)
        or retained is None
        or retained.get("goal_revision_id") != identity.goal_revision_id
        or sha256_digest(retained.get("verification")) != sha256_digest(payload)
    ):
        raise ValueError("Goal feedback differs from its exact scoped verification record")
    # Full findings and their subject/evidence identities are data, never new authority.
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return GoalContext(
        subject=subject,
        feedback=PromptSegment(
            source_ref=f"goal-verification:{feedback.verification_id}@{sha256_digest(payload)}",
            source_revision=identity.goal_iteration,
            trust_class=PromptTrustClass.UNTRUSTED_CONTENT,
            content=content,
            rendered_digest=sha256_digest(content),
        ),
    )
