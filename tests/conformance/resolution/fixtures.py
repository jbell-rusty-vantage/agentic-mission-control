"""Fixture registrations for resolver conformance (design §10): two applications and the sprint's
model pins (PROOFS §6) as data. R1's resolver conformance drives its registries with these.

The application fixtures mirror what R4's `deployments/<app>/application.toml` files must carry;
they are fixtures, not the installed profiles (their data class ceiling is `confidential`,
wider than the installed `internal`, so the ceiling refusals stay reachable). Model prices
and windows are fixture values.
"""

from __future__ import annotations

from typing import Final

from mission_control.domain.resolution.profiles import ApplicationProfile, ModelProfile
from mission_control.domain.resolution.resolved import (
    KnowledgePortBinding,
    OutputContractProfile,
    TransferProfile,
)

# The annex section 5 minimums every registered profile carries (OC-R4).
REVIEW_CLASSES: Final = ("official", "consequential")
SIGNOFF_CLASSES: Final = ("consequential",)

AI_ENGINEER: Final = ApplicationProfile(
    application_id="ai-engineer",
    revision=1,
    knowledge=KnowledgePortBinding(
        binding_id="aiengineer-postgres",
        apply_contract_name="knowledge-ingestion-intent",
        apply_contract_version="v1",
        intent_schema_ref="mc.knowledge_apply_payload.plan_with_exact_use.v1",
        storage_class="relational",
        write_atomicity="single_transaction",
        readback_capability="unsupported",
    ),
    data_class_ceiling="confidential",
    outputs=OutputContractProfile(
        assessment_pin="knowledge.report.assess@1",
        required_review_classes=REVIEW_CLASSES,
        consequential_signoff_classes=SIGNOFF_CLASSES,
    ),
    transfer=TransferProfile(
        custody_backend="supabase-storage",
        inline_bytes_ceiling=65_536,
        file_capable=True,
        binary_capable=True,
    ),
    hosted_session_retention_days=30,
)

BIOTECH: Final = ApplicationProfile(
    application_id="biotech",
    revision=1,
    knowledge=KnowledgePortBinding(
        binding_id="biotech-graph",
        apply_contract_name="biotech-knowledge-apply",
        apply_contract_version="v1",
        intent_schema_ref="mc.knowledge_apply_payload.intent_envelope.v1",
        storage_class="graph",
        write_atomicity="marker_plus_outbox",
        readback_capability="unsupported",
    ),
    data_class_ceiling="confidential",
    outputs=OutputContractProfile(
        assessment_pin="knowledge.report.assess@1",
        required_review_classes=REVIEW_CLASSES,
        consequential_signoff_classes=SIGNOFF_CLASSES,
    ),
    transfer=TransferProfile(
        custody_backend="supabase-storage",
        inline_bytes_ceiling=65_536,
        file_capable=True,
        binary_capable=True,
    ),
    hosted_session_retention_days=30,
)

APPLICATIONS: Final[tuple[ApplicationProfile, ...]] = (AI_ENGINEER, BIOTECH)


def _model(profile: str, vendor: str, model_id: str, window: int) -> ModelProfile:
    return ModelProfile.model_validate(
        {
            "profile": profile,
            "vendor": vendor,
            "model_id": model_id,
            "context_window_tokens": window,
            "max_input_tokens": window,
            "cost_per_million_input": 1.0,
            "cost_per_million_output": 5.0,
            "supports": ("structured_output", "tool_use"),
            "structured_output": "tool_auto" if "sonnet" in model_id else "tool_forced",
            "data_class_ceiling": "confidential",
        }
    )


MODELS: Final[tuple[ModelProfile, ...]] = (
    _model("producer.default", "anthropic", "claude-sonnet-5-5", 200_000),
    _model("judge.default", "openai", "gpt-5.6-terra", 400_000),
    _model("auditor.default", "anthropic", "claude-haiku-5-5", 200_000),
    _model("child.default", "anthropic", "claude-haiku-5-5", 200_000),
    _model("probe.default", "openai", "gpt-5.6-luna", 400_000),
)

__all__ = ["AI_ENGINEER", "APPLICATIONS", "BIOTECH", "MODELS"]
