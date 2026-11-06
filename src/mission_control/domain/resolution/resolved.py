"""What the resolution seam returns: one resolved runtime, or one typed refusal (ADR-0063).

`resolve_runtime(selection) -> ResolvedRuntime | ResolutionRefused`. The resolved runtime carries
the neutral agent configuration, the lane's opaque :class:`SealedLaneBinding`, and the
application side as data (knowledge port, output minimums, transfer profile). Its digest covers
every input that shapes the runtime, so a replay or fork can verify that the same inputs produce
the same runtime. A refusal names its code, a JSON pointer into the manifest or options block,
the lane that decided, and what the author or operator can change.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.transfer import (
    BackendCapabilities,
    ResourceBounds,
    TransferSelection,
)
from mission_control.domain.context.transfer_builders import first_invocation
from mission_control.domain.execution.materialization_receipt import MaterializationReceipt
from mission_control.domain.resolution.configuration import DIGEST_PATTERN, AgentConfiguration
from mission_control.domain.resolution.sealed import (
    SealedLaneBinding,
    canonical_contract_bytes,
    payload_digest,
)

RESOLVED_RUNTIME_SCHEMA: Final = "mc.resolved_runtime.v1"
PLACEHOLDER_DIGEST: Final = "sha256:" + "0" * 64


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KnowledgePortBinding(_Frozen):
    """Which KS binding and apply contract an application's native effects go through."""

    binding_id: str = Field(min_length=1, max_length=128)
    apply_contract_name: str = Field(min_length=1, max_length=128)
    apply_contract_version: str = Field(min_length=1, max_length=64)
    intent_schema_ref: str = Field(min_length=1, max_length=512)
    storage_class: Literal["relational", "graph"]
    write_atomicity: Literal["single_transaction", "marker_plus_outbox"]
    readback_capability: Literal["native", "unsupported"]
    # The application's knowledge charter skill (`skill.<app>-knowledge-charter`): what its
    # knowledge holds, the evidence bar and the write path. Compile mounts its latest admitted
    # row on every knowledge mission (`ManifestCompileService`). Left out of dumps when unset,
    # so a profile without one keeps its runtime digest.
    charter_skill: str | None = Field(
        default=None, pattern=r"^skill\.[a-z0-9-]+$", exclude_if=lambda value: value is None
    )


OutputForm = Literal[
    "text",
    "structured",
    "file",
    "reference",
    "collection",
    "code_change",
    "effect_receipt",
    "control_record",
]
OUTPUT_FORMS: Final[tuple[OutputForm, ...]] = (
    "text",
    "structured",
    "file",
    "reference",
    "collection",
    "code_change",
    "effect_receipt",
    "control_record",
)


class OutputContractProfile(_Frozen):
    """An application's output-contract minimums; authors cannot weaken them (annex §5)."""

    # e.g. `knowledge.report.assess@1`.
    assessment_pin: str = Field(min_length=1, max_length=256)
    required_review_classes: tuple[str, ...] = ()
    consequential_signoff_classes: tuple[str, ...] = ()
    # The eight forms, possibly narrowed by the application.
    allowed_forms: tuple[OutputForm, ...] = OUTPUT_FORMS

    @model_validator(mode="after")
    def unique_forms(self) -> OutputContractProfile:
        if len(set(self.allowed_forms)) != len(self.allowed_forms) or not self.allowed_forms:
            raise ValueError("allowed_forms is a non-empty set of output forms")
        return self


class TransferProfile(_Frozen):
    """An application's transfer defaults and the receiving backend's byte capability."""

    custody_backend: str = Field(min_length=1, max_length=128)
    inline_bytes_ceiling: int = Field(ge=0)
    # From the lane describe.
    file_capable: bool
    binary_capable: bool


class ResolvedRuntime(_Frozen):
    """One node's fully resolved runtime: what every caller reads instead of branching."""

    schema_version: Literal["mc.resolved_runtime.v1"] = RESOLVED_RUNTIME_SCHEMA
    selection_digest: str = Field(pattern=DIGEST_PATTERN)
    agent: AgentConfiguration
    lane_binding: SealedLaneBinding
    knowledge: KnowledgePortBinding
    outputs: OutputContractProfile
    transfer: TransferProfile
    receipt: MaterializationReceipt
    # Application Profile revision folded into the digest (design §4 step 6).
    application_revision: int = Field(ge=1)
    runtime_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def exact_runtime(self, info: ValidationInfo) -> ResolvedRuntime:
        if self.lane_binding.lane_profile != self.agent.lane_profile:
            raise ValueError("the sealed lane binding belongs to another lane")
        if self.receipt.lane_profile != self.agent.lane_profile:
            raise ValueError("the materialization receipt was signed by another lane")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and self.content_digest() != self.runtime_digest
        ):
            raise ValueError("resolved runtime digest mismatch")
        return self

    def content_digest(self) -> str:
        return sha256_digest(_digest_basis(self))

    @classmethod
    def create(cls, **fields: Any) -> ResolvedRuntime:
        draft = cls.model_validate(
            {**fields, "runtime_digest": PLACEHOLDER_DIGEST},
            context={"allow_placeholder_digest": True},
        )
        return cls.model_validate(
            {**draft.model_dump(mode="python"), "runtime_digest": draft.content_digest()}
        )


def _digest_basis(runtime: ResolvedRuntime) -> Mapping[str, Any]:
    # The payload bytes are covered by the binding digest (raw SHA-256, see `payload_digest`);
    # the basis names the binding by reference so it stays JSON-safe.
    return {
        "schema_version": runtime.schema_version,
        "selection_digest": runtime.selection_digest,
        "configuration_digest": runtime.agent.configuration_digest,
        "model": runtime.agent.model.model_dump(mode="python"),
        "lane_binding": runtime.lane_binding.ref(),
        "knowledge": runtime.knowledge.model_dump(mode="python"),
        "outputs": runtime.outputs.model_dump(mode="python"),
        "transfer": runtime.transfer.model_dump(mode="python"),
        "receipt_digest": runtime.receipt.receipt_digest,
        "application_revision": runtime.application_revision,
    }


# report-review@v1 resource defaults (OUTPUT-CONTRACTS §3): the aggregate file allowance and
# count of one invocation, and the reserve fractions when the model declares no output limit.
REPORT_REVIEW_FILE_BYTES: Final = 4 * 1024 * 1024
REPORT_REVIEW_FILE_COUNT: Final = 64


def receiver_transfer_base(runtime: ResolvedRuntime, position: str) -> TransferSelection:
    """The receiver's base ``TransferSelection`` (first invocation, no inputs): its owner position,
    the application's transfer profile and bounds sized by the resolved model's
    ``max_input_tokens`` (OC-R6: a context is sized by the input limit, never the window).

    Generation reserve: the model's declared ``max_output_tokens`` setting, else a quarter of
    the input limit; tool-result reserve: an eighth of it.
    """

    profile = runtime.transfer
    model = runtime.agent.model
    limit = model.max_input_tokens
    declared_output = model.settings.get("max_output_tokens")
    generation = declared_output if isinstance(declared_output, int) else limit // 4
    return first_invocation(
        position,
        ResourceBounds(
            window_tokens=limit,
            generation_reserve_tokens=generation,
            tool_result_reserve_tokens=limit // 8,
            inline_bytes_ceiling=profile.inline_bytes_ceiling,
            file_bytes_ceiling=REPORT_REVIEW_FILE_BYTES,
            file_count_ceiling=REPORT_REVIEW_FILE_COUNT,
        ),
        BackendCapabilities(
            custody_backend=profile.custody_backend,
            file_capable=profile.file_capable,
            binary_capable=profile.binary_capable,
        ),
    )


RefusalCode = Literal[
    "LANE_UNKNOWN",
    "LANE_UNQUALIFIED",
    "APPLICATION_UNKNOWN",
    "MODEL_UNKNOWN",
    "MODEL_ROUTE_UNSUPPORTED",
    "DATA_CLASS_NOT_ADMITTED",
    "BLUEPRINT_FAMILY_UNSUPPORTED",
    "ITEM_UNSUPPORTED_ON_LANE",
    "ITEM_PIN_UNSERVED",
    "APPLY_CONTRACT_MISMATCH",
    "LANE_OPTIONS_INVALID",
]
REFUSAL_CODES: Final[tuple[RefusalCode, ...]] = (
    "LANE_UNKNOWN",
    "LANE_UNQUALIFIED",
    "APPLICATION_UNKNOWN",
    "MODEL_UNKNOWN",
    "MODEL_ROUTE_UNSUPPORTED",
    "DATA_CLASS_NOT_ADMITTED",
    "BLUEPRINT_FAMILY_UNSUPPORTED",
    "ITEM_UNSUPPORTED_ON_LANE",
    "ITEM_PIN_UNSERVED",
    "APPLY_CONTRACT_MISMATCH",
    "LANE_OPTIONS_INVALID",
)


class ResolutionRefused(_Frozen):
    """A resolution-time refusal: typed, pointed, attributed and actionable."""

    code: RefusalCode
    # JSON pointer into the manifest or the lane options block.
    pointer: str = Field(pattern=r"^(/[^/]*)*$", max_length=1_024)
    lane_profile: str | None = Field(default=None, max_length=64)
    reason: str = Field(min_length=1, max_length=2_000)
    # What the author or operator can change.
    remedy: str = Field(min_length=1, max_length=2_000)


class LaneCompileRefused(ValueError):
    """Raised by a pure `LaneAdapter.compile`; the resolver converts it to `ResolutionRefused`."""

    def __init__(self, refusal: ResolutionRefused) -> None:
        super().__init__(f"{refusal.code} at {refusal.pointer or '/'}: {refusal.reason}")
        self.refusal = refusal


__all__ = [
    "OUTPUT_FORMS",
    "REFUSAL_CODES",
    "RESOLVED_RUNTIME_SCHEMA",
    "KnowledgePortBinding",
    "LaneCompileRefused",
    "OutputContractProfile",
    "OutputForm",
    "RefusalCode",
    "ResolutionRefused",
    "ResolvedRuntime",
    "SealedLaneBinding",
    "TransferProfile",
    "canonical_contract_bytes",
    "payload_digest",
    "receiver_transfer_base",
]
