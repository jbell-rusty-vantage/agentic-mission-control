"""Scoped public forms of inherited runtime recovery, without expanded feature claims."""

from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, model_validator

from mission_control.contracts.contracts import ContentRef, Contract, InlineText
from mission_control.domain.policies.contracts import ReconcileUnitAction
from mission_control.domain.policies.forks import (
    AnyCognitiveSeed,
    ForkAt,
    ForkPatchChange,
    FrontierPolicy,
    RunForkReceipt,
)


class MissionSnapshotRequest(Contract):
    schema_version: Literal["mc.runtime_snapshot.v1"] = "mc.runtime_snapshot.v1"
    expected_version: int = Field(ge=1)


class MissionForkRequest(Contract):
    """`ForkPayload` (SPEC-06): a Snapshot (`snapshot_id`, also accepted as
    `from_snapshot_id`; omitted means the latest safe Snapshot, taking one when none exists),
    an optional `instruction` that becomes the forked Run's first mailbox entry, a typed patch
    and the sponsorship that pays for the new Run."""

    schema_version: Literal["mc.runtime_fork.v1"] = "mc.runtime_fork.v1"
    request_id: UUID
    snapshot_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        validation_alias=AliasChoices("snapshot_id", "from_snapshot_id"),
    )
    # Bound when given; otherwise the resolved Snapshot's own digest.
    snapshot_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    changes: tuple[ForkPatchChange, ...] = ()
    invalidation_frontier: tuple[str, ...] = ()
    cognitive_seed: AnyCognitiveSeed | None = None
    baseline_reservations: dict[str, int] = Field(default_factory=dict)
    # 1.4.4 (P5.1): `message` is the one injected message; `instruction` is its deprecated
    # alias (a request naming only `instruction` reads back with `message` set to it).
    instruction: ContentRef | InlineText | None = None
    message: ContentRef | InlineText | None = None
    # 1.4.4 (P5.1): the family position the fork resumes at (derived from the seed point
    # when omitted) and the frontier policy (`close` records the closure; `strict` refuses a
    # frontier narrower than its closure).
    at: ForkAt | None = None
    frontier_policy: FrontierPolicy = "close"
    sponsorship_ref: str = Field(min_length=1)
    approval_refs: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def alias_instruction(cls, value: object) -> object:
        if isinstance(value, dict):
            if value.get("message") is None and value.get("instruction") is not None:
                return {**value, "message": value["instruction"]}
            if value.get("instruction") is None and value.get("message") is not None:
                return {**value, "instruction": value["message"]}
        return value


class ForkSeedView(Contract):
    """FT-F4: what the forked Run's own mailbox received (Command ids; receipts are in its
    command ledger). Nothing of the source Run's mailbox or Commands is copied."""

    derived_run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    workspace_command_id: str = Field(min_length=1)
    instruction_command_id: str | None = None


class MissionForkReceipt(Contract):
    schema_version: Literal["mc.runtime_fork_receipt.v1"] = "mc.runtime_fork_receipt.v1"
    request_id: UUID
    receipt: RunForkReceipt
    seed: ForkSeedView | None = None


class MissionReconciliationRequest(Contract):
    schema_version: Literal["mc.unit_reconciliation.v1"] = "mc.unit_reconciliation.v1"
    request_id: UUID
    expected_version: int = Field(ge=1)
    action: ReconcileUnitAction
    reason: str = Field(min_length=1, max_length=4096)


class ClosedWorkflowRecoveryRequest(Contract):
    """No caller-supplied closure, settlement or authority facts."""

    schema_version: Literal["mc.closed_workflow_recovery.v1"] = "mc.closed_workflow_recovery.v1"
    request_id: UUID
    expected_version: int = Field(ge=1)
