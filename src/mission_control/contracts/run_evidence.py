"""Scoped, persisted run evidence; availability never implies fulfillment or resumability."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from mission_control.contracts.contracts import MissionInspection
from mission_control.domain.coordinator.launch import WorkflowResultRecord
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.workspace_closure import RunClosureSummary
from mission_control.domain.programs.bindings import RunSemanticInputBinding
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import GoalVerificationResult


class EvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HandlerInputEvidence(EvidenceContract):
    role: str
    handler_ref: str
    schema_ref: str
    payload_digest: str
    output_contract_ref: str
    operation_execution_binding_ref: str | None = None


class InputEvidence(EvidenceContract):
    status: Literal["recorded", "not_recorded", "unavailable"]
    binding_id: str | None = None
    binding_digest: str | None = None
    handlers: tuple[HandlerInputEvidence, ...] = ()
    native_template_count: int = 0


class NativeTemplateInput(EvidenceContract):
    binding_ref: str
    family: Literal["StageGraph", "GoalDirected"]
    template_key: str
    document_digest: str
    template: OperationExecutionRequest


class RunInputs(EvidenceContract):
    schema_version: Literal["mc.run_inputs.v1"] = "mc.run_inputs.v1"
    run_id: str
    status: Literal["recorded", "not_recorded", "unavailable"]
    binding: RunSemanticInputBinding | None = None
    native_templates: tuple[NativeTemplateInput, ...] = ()


class ResultEvidence(EvidenceContract):
    status: Literal["recorded", "pending", "missing_terminal_result", "unavailable"]
    record: WorkflowResultRecord | None = None


class CheckpointEvidence(EvidenceContract):
    checkpoint_id: str
    checkpoint_digest: str
    kind: Literal["continuation_manifest"] = "continuation_manifest"
    validator_result: Literal["valid", "invalid"]
    sealed_at: AwareDatetime
    transfer_status: str | None = None
    workspace_snapshot_ref: str | None = None
    sandbox_snapshot_ref: str | None = None
    context_packet_ref: str | None = None
    # A valid sealed manifest is not proof that its external bytes/runtime still exist.
    current_resumability: Literal["not_verified"] = "not_verified"


class CompletionDecisionEvidence(EvidenceContract):
    """One committed validation observation, never an inferred mission-wide verdict."""

    request_scope: str
    run_id: str
    family_version: int = Field(ge=1)
    mutation_id: str
    mutation_fingerprint: str
    exact_operation_request_ref: str
    decided_at: AwareDatetime
    # Preserve the writer's versioned checks, including pending/unavailable and legacy
    # not_evaluated records. Do not upgrade an old receipt into a new validator result.
    validation: CompletionValidation | dict[str, JsonValue]


class CompletionEvidencePage(EvidenceContract):
    schema_version: Literal["mc.completion_evidence.v1"] = "mc.completion_evidence.v1"
    run_id: str
    family_kind: Literal["stagegraph"] = "stagegraph"
    status: Literal["recorded", "not_recorded", "unavailable"]
    decisions: tuple[CompletionDecisionEvidence, ...] = ()
    next_after_family_version: int | None = None


class GoalValidationEvidence(EvidenceContract):
    run_id: str
    document_digest: str
    request_digest: str
    verification: GoalVerificationResult
    validation: CompletionValidation


class GoalCompletionEvidencePage(EvidenceContract):
    run_id: str
    status: Literal["recorded", "not_recorded", "unavailable"]
    decisions: tuple[GoalValidationEvidence, ...] = ()
    next_verification_id: str | None = None


class RunEvidence(EvidenceContract):
    schema_version: Literal["mc.run_evidence.v1"] = "mc.run_evidence.v1"
    run_id: str
    mission_id: str | None = None
    request_scope: str
    authority: Literal["persisted_mission_control_records"] = "persisted_mission_control_records"
    inspection: MissionInspection
    inputs: InputEvidence
    result: ResultEvidence
    completion: CompletionEvidencePage | None = None
    checkpoints_status: Literal["recorded", "not_recorded", "unavailable"]
    checkpoints: tuple[CheckpointEvidence, ...] = ()
    # OVE-204 slice 5: the run's Workspace Closures (count, incomplete, the newest: the
    # mission end's); `unavailable` when no closure reader is composed.
    closures_status: Literal["recorded", "not_recorded", "unavailable"] = "unavailable"
    closures: RunClosureSummary | None = None
    # These facts need their own provider/capture evidence, never an inferred URL or success.
    provider_urls_status: Literal["not_collected"] = "not_collected"
    trace_urls_status: Literal["not_collected"] = "not_collected"
    sandbox_state_status: Literal["not_verified"] = "not_verified"
    artifact_bytes_status: Literal["not_verified"] = "not_verified"
