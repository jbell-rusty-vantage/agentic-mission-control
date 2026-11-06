"""The persisted Stop Fence of an immediate cancel (ADR-0008, ADR-0032; SPEC-06; FT-F3).

`cancel` with `urgency: immediate` persists a Stop Fence for the run and its execution
generation before any provider cancel is attempted. From then on every Kernel Hook (the
Deep Agents `wrap_tool_call` kernel layer, the Cursor hook callback) asks the fence before
admitting a side effect, and a fenced admission is denied with `STOP_FENCED`. The fence is
insert-only: it is never deleted, and a later generation's fence leaves earlier rows for
audit.

`stop_now` guarantees that no *new* effect is admitted after the fence; it does not halt a
remote tool that was already dispatched. Every Delivery Report says so.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.policies.contracts import RunOutcome, RunPhase, RunProjection

STOP_FENCED: Final = "STOP_FENCED"
FENCED_FRAME_REASON: Final = "fenced"
STOP_NOW_NOTE: Final = (
    "stop_now guarantees no new side effect is admitted after the fence; a remote tool "
    "dispatched before the fence may still complete (ADR-0008)"
)
IMMEDIATE_CANCEL_ADMIN_PERMISSION: Final = "workflow_run.admin"
IMMEDIATE_CANCEL_PERMISSION: Final = "workflow_run.cancel"
# Phases in which side-effecting work may be executing.
_ACTIVE_PHASES: Final = frozenset({"active", "waiting", "cancelling"})

EffectKind = Literal["shell", "mcp", "file", "task", "model", "other"]
FenceMilestone = Literal["provider_acknowledged", "settled"]


class StopFenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StopFence(StopFenceContract):
    """One persisted fence: run, generation, the immediate cancel command that wrote it."""

    request_scope: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2_048)
    requested_at: AwareDatetime
    fenced_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def fenced_after_request(self) -> StopFence:
        if self.fenced_at is not None and self.fenced_at < self.requested_at:
            raise ValueError("a fence cannot be persisted before it was requested")
        return self

    def covers(self, generation: int) -> bool:
        """A fence stops its own generation and every earlier one."""

        return generation <= self.generation


def run_fence_generation(run: RunProjection | None) -> int:
    """Tracing Stage 3 (R1-F5): the generation a run's Stop Fence is written for and read
    against, the run's execution-target generation (`ExecutionTarget.execution_generation`,
    1 while no target is bound; nothing advances it today, `FAMILY_EXECUTION_GENERATION`).

    It is not a unit's `execution_generation`: that axis is per unit and advances with a
    `start_new_generation` reconciliation of that one unit, so comparing it with the fence
    (as the Stage 2 readers did with `==`) let a generation-2 unit escape the fence. Every
    reader asks `fence.covers(run_fence_generation(run))`; without the run at hand a reader
    passes None, which is the generation the writer stores for such a run.
    """

    if run is None or run.execution_target is None:
        return 1
    return run.execution_target.execution_generation


def cancel_journaled(run: RunProjection) -> bool:
    """Tracing Stage 3 (R1-F1): whether run control holds an accepted cancel of the run (it is
    `cancelling`, or terminal `cancelled`). The fence is written before the cancel command is
    recorded (ADR-0008), so a fence whose cancel the reducer then rejected stays behind
    (insert-only); a reader that ends work on the fence alone checks this first."""

    return run.phase == RunPhase.CANCELLING or run.terminal_outcome == RunOutcome.CANCELLED


def run_fence_stops(fence: StopFence | None, run: RunProjection) -> bool:
    """A persisted fence covering the run's generation and backed by a journaled cancel."""

    return (
        fence is not None
        and fence.fenced_at is not None
        and fence.covers(run_fence_generation(run))
        and cancel_journaled(run)
    )


class EffectAdmission(StopFenceContract):
    """A Kernel Hook's request to admit one side effect (`effect_ref` is the provider's
    stable effect identity: `tool_use_id`, `call_id`, or a digest of a shell command)."""

    request_scope: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    effect_ref: str = Field(min_length=1, max_length=512)
    effect_kind: EffectKind = "other"
    lane_profile: str = Field(default="deep_agents", min_length=1)


class FenceVerdict(StopFenceContract):
    decision: Literal["allow", "deny"]
    reason_code: Literal["STOP_FENCED"] | None = None
    effect_ref: str = Field(min_length=1)
    fence_command_id: str | None = None
    message: str | None = None

    @model_validator(mode="after")
    def deny_names_the_fence(self) -> FenceVerdict:
        if (self.decision == "deny") != (self.reason_code == STOP_FENCED):
            raise ValueError("a fenced denial carries STOP_FENCED and nothing else does")
        if self.decision == "deny" and self.fence_command_id is None:
            raise ValueError("a fenced denial names the fencing command")
        return self

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


def fence_verdict(fence: StopFence | None, admission: EffectAdmission) -> FenceVerdict:
    """Pure decision: deny when a fence of this run covers the admission's generation."""

    if fence is not None and (
        fence.run_id != admission.run_id or fence.request_scope != admission.request_scope
    ):
        raise ValueError("fence and admission belong to different runs")
    if fence is not None and fence.covers(admission.generation):
        return FenceVerdict(
            decision="deny",
            reason_code=STOP_FENCED,
            effect_ref=admission.effect_ref,
            fence_command_id=fence.command_id,
            message=f"run is stop-fenced by immediate cancel {fence.command_id}",
        )
    return FenceVerdict(decision="allow", effect_ref=admission.effect_ref)


def immediate_cancel_permissions(phase: str) -> frozenset[str]:
    """`mission.admin` when side-effecting work may be active, `mission.command` otherwise."""

    if phase in _ACTIVE_PHASES:
        return frozenset({IMMEDIATE_CANCEL_PERMISSION, IMMEDIATE_CANCEL_ADMIN_PERMISSION})
    return frozenset({IMMEDIATE_CANCEL_PERMISSION})


class ImmediateCancelReport(StopFenceContract):
    """The Delivery Report of an immediate cancel: four separate timestamps."""

    command_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    delivery_semantics: Literal["turn_boundary_guaranteed"] = "turn_boundary_guaranteed"
    requested_at: AwareDatetime
    fence_persisted_at: AwareDatetime
    provider_acknowledged_at: AwareDatetime | None = None
    settled_at: AwareDatetime | None = None
    note: str = STOP_NOW_NOTE

    @model_validator(mode="after")
    def ordered(self) -> ImmediateCancelReport:
        if self.fence_persisted_at < self.requested_at:
            raise ValueError("fence persisted before the cancel was requested")
        if self.settled_at is not None and self.settled_at < self.fence_persisted_at:
            raise ValueError("settlement cannot precede the fence")
        return self

    @property
    def state(self) -> Literal["fence_persisted", "provider_acknowledged", "settled"]:
        if self.settled_at is not None:
            return "settled"
        if self.provider_acknowledged_at is not None:
            return "provider_acknowledged"
        return "fence_persisted"


__all__ = [
    "FENCED_FRAME_REASON",
    "IMMEDIATE_CANCEL_ADMIN_PERMISSION",
    "STOP_FENCED",
    "STOP_NOW_NOTE",
    "EffectAdmission",
    "FenceMilestone",
    "FenceVerdict",
    "ImmediateCancelReport",
    "StopFence",
    "cancel_journaled",
    "fence_verdict",
    "immediate_cancel_permissions",
    "run_fence_generation",
    "run_fence_stops",
]
