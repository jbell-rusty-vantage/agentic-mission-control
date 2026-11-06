"""Evaluate frozen StageGraph artifact requirements before family admission."""

from collections.abc import Mapping
from typing import Any, cast

from mission_control.application.context.pack_service import ArtifactBytesPort
from mission_control.application.programs.artifact_validation import (
    validate_artifact,
    validate_output_revision,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import GoalDirectedBlueprint, StageNode
from mission_control.domain.outputs.contracts import ExactOutput
from mission_control.domain.programs.completion import (
    ArtifactValidationCheck,
    CompletionValidation,
    CriterionValidationCheck,
    ValidationStatus,
    output_binding_errors,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter


class ArtifactPublicationPending(RuntimeError):
    """Retry the durable result activity; no producer settlement has been committed."""


def _status(values: list[ValidationStatus]) -> ValidationStatus:
    for value in ("unavailable", "unsatisfied", "pending"):
        if value in values:
            return cast(ValidationStatus, value)
    return "satisfied"


async def validate_completion(
    artifacts: ArtifactBytesPort | None,
    *,
    request_scope: str,
    stage: StageNode | GoalDirectedBlueprint,
    interpreter: StageGraphInterpreter | None,
    operation_result: dict[str, Any],
    registered_outputs: Mapping[str, tuple[ExactOutput, ...]] | None = None,
    registered_run_id: str | None = None,
) -> CompletionValidation:
    if isinstance(stage, GoalDirectedBlueprint):
        errors = output_binding_errors(
            operation_result,
            {slot.output_slot_id for slot in stage.output_slots},
            require_explicit=len(stage.output_slots) > 1,
        )
        if errors:
            return CompletionValidation(
                execution_disposition="completed",
                candidate_digest=sha256_digest(operation_result),
                status="unsatisfied",
                reason_codes=errors,
                criteria=tuple(
                    CriterionValidationCheck(
                        criterion_key=item.criterion_key,
                        obligation_ref=item.obligation_ref,
                        status="unsatisfied",
                        reason_code="criterion_unsatisfied",
                    )
                    for item in stage.schema_criteria
                ),
            )
    checks: list[ArtifactValidationCheck] = []
    required_by_criteria = {name for item in stage.schema_criteria for name in item.output_slots}
    for slot in stage.output_slots:
        binding = slot.validation_schema
        if isinstance(stage, StageNode) and registered_outputs is None:
            if interpreter is None:
                raise ValueError("StageGraph validator requires its interpreter")
            refs = interpreter.output_slot_refs(
                stage.stage_id, slot.output_slot_id, operation_result
            )
        else:
            bindings = operation_result.get("output_bindings")
            refs = tuple(
                bindings.get(slot.output_slot_id, ())
                if isinstance(bindings, dict)
                else operation_result.get("output_refs", ())
            )
        if not refs and not slot.required and slot.output_slot_id not in required_by_criteria:
            continue
        if binding is None:
            if refs or slot.required or slot.output_slot_id in required_by_criteria:
                checks.append(
                    ArtifactValidationCheck(
                        output_slot=slot.output_slot_id,
                        schema_ref=slot.output_contract_ref,
                        status="unavailable",
                        reason_code="schema_binding_unavailable",
                        evidence_digest=sha256_digest(
                            {"slot": slot.output_slot_id, "reason": "schema_binding_unavailable"}
                        ),
                    )
                )
            continue
        if registered_outputs is not None:
            if not isinstance(stage, StageNode) or registered_run_id is None:
                raise ValueError("named stage validation requires its host-bound run identity")
            selected = {
                f"output-revision:{item.revision_id}#digest={item.content_digest}": item
                for item in registered_outputs.get(slot.output_slot_id, ())
            }
            if not refs:
                checks.append(
                    ArtifactValidationCheck(
                        output_slot=slot.output_slot_id,
                        schema_ref=binding.schema_ref,
                        schema_digest=binding.schema_digest,
                        status="unsatisfied",
                        reason_code="output_missing",
                        evidence_digest=sha256_digest(
                            {
                                "slot": slot.output_slot_id,
                                "schema": binding.schema_digest,
                                "reason": "output_missing",
                            }
                        ),
                    )
                )
            for ref in sorted(set(refs)):
                if ref not in selected:
                    raise ValueError("named completion reference was not selected by the host")
                checks.append(
                    validate_output_revision(
                        selected[ref],
                        request_scope=request_scope,
                        run_id=registered_run_id,
                        obligation_key=f"{stage.stage_id}.{slot.output_slot_id}",
                        output_slot=slot.output_slot_id,
                        schema_ref=binding.schema_ref,
                        schema_digest=binding.schema_digest,
                        json_schema=binding.json_schema,
                    )
                )
            continue
        reason = "output_missing" if not refs else "artifact_reader_unavailable"
        if not refs or artifacts is None:
            status: ValidationStatus = "unsatisfied" if not refs else "unavailable"
            checks.append(
                ArtifactValidationCheck(
                    output_slot=slot.output_slot_id,
                    schema_ref=binding.schema_ref,
                    schema_digest=binding.schema_digest,
                    status=status,
                    reason_code=reason,
                    evidence_digest=sha256_digest(
                        {
                            "slot": slot.output_slot_id,
                            "schema": binding.schema_digest,
                            "reason": reason,
                        }
                    ),
                )
            )
            continue
        for ref in sorted(set(refs)):
            checks.append(
                await validate_artifact(
                    artifacts,
                    request_scope=request_scope,
                    output_slot=slot.output_slot_id,
                    schema_ref=binding.schema_ref,
                    schema_digest=binding.schema_digest,
                    json_schema=binding.json_schema,
                    artifact_ref=ref,
                )
            )
    criteria: list[CriterionValidationCheck] = []
    for criterion in stage.schema_criteria:
        relevant = [
            check
            for check in checks
            if check.output_slot in criterion.output_slots
            and check.schema_ref == criterion.schema_ref
        ]
        missing = set(criterion.output_slots) - {check.output_slot for check in relevant}
        status = "unavailable" if missing else _status([check.status for check in relevant])
        criteria.append(
            CriterionValidationCheck(
                criterion_key=criterion.criterion_key,
                obligation_ref=criterion.obligation_ref,
                status=status,
                evidence_digests=tuple(check.evidence_digest for check in relevant),
                reason_code="criterion_satisfied"
                if status == "satisfied"
                else "criterion_" + status,
            )
        )
    return CompletionValidation(
        execution_disposition="completed",
        candidate_digest=sha256_digest(operation_result),
        status=_status([check.status for check in checks] + [item.status for item in criteria]),
        reason_codes=tuple(
            sorted(
                {check.reason_code for check in checks if check.status != "satisfied"}
                | {item.reason_code for item in criteria if item.status != "satisfied"}
            )
        ),
        checks=tuple(checks),
        criteria=tuple(criteria),
    )


def validated_result(result: dict[str, Any], validation: CompletionValidation) -> dict[str, Any]:
    """Schema-owned obligations are derived from checks, never provider assertions."""
    owned = {item.obligation_ref for item in validation.criteria if item.obligation_ref is not None}
    existing = result.get("obligation_refs", ())
    if not isinstance(existing, (list, tuple)) or any(not isinstance(ref, str) for ref in existing):
        return result  # Preserve malformed claims for structural validation to reject.
    accepted = {
        ref
        for ref in owned
        if all(
            item.status == "satisfied" for item in validation.criteria if item.obligation_ref == ref
        )
    }
    return {**result, "obligation_refs": sorted((set(existing) - owned) | accepted)}


def expire_pending(
    validation: CompletionValidation, *, reason: str = "artifact_publication_deadline_exceeded"
) -> CompletionValidation:
    """Persist a final unmet result when the fixed publication grace period expires."""
    checks = tuple(
        check.model_copy(
            update={
                "status": "unsatisfied",
                "reason_code": reason,
                "evidence_digest": sha256_digest(
                    {
                        "pending_evidence": check.evidence_digest,
                        "reason": reason,
                    }
                ),
            }
        )
        if check.status == "pending"
        else check
        for check in validation.checks
    )
    criteria = tuple(
        item.model_copy(
            update={
                "status": "unsatisfied",
                "reason_code": "criterion_unsatisfied",
                "evidence_digests": tuple(
                    check.evidence_digest
                    for check in checks
                    if check.output_slot
                    in {
                        original.output_slot
                        for original in validation.checks
                        if original.evidence_digest in item.evidence_digests
                    }
                ),
            }
        )
        if item.status == "pending"
        else item
        for item in validation.criteria
    )
    return validation.model_copy(
        update={
            "checks": checks,
            "criteria": criteria,
            "status": "unsatisfied",
            "reason_codes": (reason,),
        }
    )
