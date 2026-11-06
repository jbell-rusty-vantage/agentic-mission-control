"""Pinned output schemas and replayable completion-validation evidence."""

from collections.abc import Collection
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import sha256_digest

ValidationStatus = Literal["satisfied", "unsatisfied", "pending", "unavailable"]


def output_binding_errors(
    result: dict[str, Any], allowed_slots: Collection[str], *, require_explicit: bool = False
) -> tuple[str, ...]:
    """Account for every candidate reference before reading or accepting any artifact."""
    refs = result.get("output_refs", ())
    if not isinstance(refs, list | tuple) or any(
        not isinstance(ref, str) or not ref.strip() for ref in refs
    ):
        return ("invalid_output_refs",)
    bindings = result.get("output_bindings")
    if bindings is None:
        return ("output_bindings_required",) if require_explicit else ()
    if not isinstance(bindings, dict) or not set(bindings) <= set(allowed_slots):
        return ("invalid_output_bindings",)
    for values in bindings.values():
        if not isinstance(values, list | tuple) or any(
            not isinstance(ref, str) or ref not in refs for ref in values
        ):
            return ("unregistered_output_binding",)
    if set(refs) != {ref for values in bindings.values() for ref in values}:
        return ("unbound_output_ref",)
    return ()


class CompletionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OutputSchemaBinding(CompletionModel):
    schema_ref: str = Field(min_length=1)
    source_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    json_schema: dict[str, Any]

    @model_validator(mode="after")
    def exact_schema(self) -> "OutputSchemaBinding":
        if sha256_digest(self.json_schema) != self.schema_digest:
            raise ValueError("output schema body differs from its pinned digest")
        return self


class SchemaCriterion(CompletionModel):
    criterion_key: str
    obligation_ref: str | None = None
    schema_ref: str
    output_slots: tuple[str, ...] = Field(min_length=1)


class ArtifactValidationCheck(CompletionModel):
    output_slot: str
    schema_ref: str
    schema_digest: str | None = None
    artifact_ref: str | None = None
    artifact_digest: str | None = None
    status: ValidationStatus
    reason_code: str
    evidence_digest: str


class CriterionValidationCheck(CompletionModel):
    criterion_key: str
    obligation_ref: str | None = None
    status: ValidationStatus
    evidence_digests: tuple[str, ...] = ()
    reason_code: str


class CompletionValidation(CompletionModel):
    schema_version: Literal["mc.stage_completion_validation.v2"] = (
        "mc.stage_completion_validation.v2"
    )
    execution_disposition: str
    status: ValidationStatus
    candidate_digest: str
    reason_codes: tuple[str, ...] = ()
    checks: tuple[ArtifactValidationCheck, ...] = ()
    criteria: tuple[CriterionValidationCheck, ...] = ()
