"""``mc.materialization_receipt.v1``: what a lane did with each configured item (P1-S1).

A mission declares its agent configuration once, lane-neutrally. Each lane adapter turns that
declaration into its native form and signs a receipt: one row per item saying whether the lane
materialized it ``native`` (the provider's own mechanism), ``emulated`` (Mission Control
supplies the behaviour), ``degraded`` (materialized with a documented loss) or ``unsupported``
(not materialized; refused when the mission required it). The receipt is sealed into the
exact binding, so the ledger, the describe matrix and a coordinator read the same facts, and
"observed in use" (C01) is checked against it rather than against a wish list.

The receipt names items by ``kind`` (the configuration vocabulary of DESIGN §1) and ``name``
(the alias or component the mission used). It never carries secrets or prompt text.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from mission_control.domain.authoring.canonical import sha256_digest

MATERIALIZATION_RECEIPT_SCHEMA: Final = "mc.materialization_receipt.v1"
PLACEHOLDER_DIGEST: Final = "sha256:" + "0" * 64

MaterializationVerdict = Literal["native", "emulated", "degraded", "unsupported"]

# The item kinds a receipt may name: the shared configuration vocabulary (DESIGN §1).
MaterializationKind = Literal[
    "instructions",
    "model",
    "tool",
    "mcp_server",
    "skill",
    "plugin",
    "hook",
    "subagent",
    "memory",
    "sandbox",
    "workspace",
    "secret",
    "network",
    "context_packet",
    "output_contract",
    "budget",
    "compaction",
    "human_control",
    "observation",
    "placement",
    # Sprint B: one row per selected lane feature and model tool (`mc.agent_configuration.v1`).
    "feature",
    "model_tool",
    # Sprint OC R0: the `mc.agent_configuration.v2` kinds with no earlier receipt name.
    "environment_kit",
    "middleware",
]


class MaterializationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: MaterializationKind
    name: str = Field(min_length=1, max_length=256)
    verdict: MaterializationVerdict
    # Where the lane put it, in the lane's own terms (a mount path, a tool name, a graph id).
    native_locator: str | None = Field(default=None, max_length=512)
    # The content digest of what was materialized, when the item has one.
    digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    # Why the verdict is not `native`; required for degraded and unsupported items.
    reason: str | None = Field(default=None, max_length=1_000)
    # OC-R6: a `model` item states the vendor and model id the lane calls (the resolved Model
    # Catalog pin) beside the served definition it materialized (`name`, `digest`). Absent
    # fields are not dumped, so receipts without them keep their digests.
    vendor: str | None = Field(
        default=None, min_length=1, max_length=64, exclude_if=lambda value: value is None
    )
    model_id: str | None = Field(
        default=None, min_length=1, max_length=256, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def losses_are_explained(self) -> MaterializationItem:
        if self.verdict in {"degraded", "unsupported"} and not self.reason:
            raise ValueError(f"a {self.verdict} materialization item needs a reason")
        if (self.vendor is not None or self.model_id is not None) and self.kind != "model":
            raise ValueError("only a model item states a vendor and model id")
        return self


class MaterializationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.materialization_receipt.v1"] = MATERIALIZATION_RECEIPT_SCHEMA
    lane_profile: str = Field(min_length=1, max_length=64)
    items: tuple[MaterializationItem, ...] = ()
    receipt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_receipt(self, info: ValidationInfo) -> MaterializationReceipt:
        keys = [(item.kind, item.name) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("a materialization receipt names each (kind, name) once")
        if (
            not (info.context or {}).get("allow_placeholder_digest")
            and self.content_digest() != self.receipt_digest
        ):
            raise ValueError("materialization receipt digest mismatch")
        return self

    def content_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="python", exclude={"receipt_digest"}))

    @classmethod
    def create(
        cls, *, lane_profile: str, items: Iterable[MaterializationItem]
    ) -> MaterializationReceipt:
        ordered = tuple(sorted(items, key=lambda item: (item.kind, item.name)))
        draft = cls.model_validate(
            {
                "lane_profile": lane_profile,
                "items": ordered,
                "receipt_digest": PLACEHOLDER_DIGEST,
            },
            context={"allow_placeholder_digest": True},
        )
        return cls(
            lane_profile=draft.lane_profile,
            items=draft.items,
            receipt_digest=draft.content_digest(),
        )

    def with_verdict(self, *verdicts: MaterializationVerdict) -> tuple[MaterializationItem, ...]:
        return tuple(item for item in self.items if item.verdict in verdicts)

    @property
    def degradations(self) -> tuple[str, ...]:
        """One line per non-native item, for bindings that carry only strings."""

        return tuple(
            f"{item.kind}:{item.name}:{item.verdict}:{item.reason}"
            for item in self.items
            if item.verdict != "native"
        )


__all__ = [
    "MATERIALIZATION_RECEIPT_SCHEMA",
    "MaterializationItem",
    "MaterializationKind",
    "MaterializationReceipt",
    "MaterializationVerdict",
]
