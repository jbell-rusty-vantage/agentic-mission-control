"""Explicit operator-only bootstrap of one bounded, previously admitted probe operation."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import (
    ClaudeManagedOptions,
    CodexAgentsOptions,
    ProviderExecutionBinding,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lanes import LaneSegmentBounds
from mission_control.domain.graph_runtime.identities import (
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)


class BootstrapProbePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["mc.owner_bootstrap_probe.v1"] = "mc.owner_bootstrap_probe.v1"
    request_scope: str
    run_id: str
    semantic_input_binding_ref: str
    operation_request_key: str
    template_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    provider_binding_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    purpose: Literal["signed_webhook", "signal_receipt"]
    prerequisite_id: str
    prerequisite_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    max_cost_micros: int = Field(ge=1, le=1_000_000)
    timeout_seconds: int = Field(default=90, ge=10, le=120)


class BootstrapProbePort(Protocol):
    async def load(self, plan: BootstrapProbePlan) -> OperationExecutionRequest: ...
    async def start(self, plan: BootstrapProbePlan, request: OperationWorkflowRequest) -> str: ...
    async def prove(self, plan: BootstrapProbePlan, request: OperationWorkflowRequest) -> str: ...


def bootstrap_identity(plan: BootstrapProbePlan) -> str:
    # Multiple prerequisite checks may consume one actual bounded probe run.
    # Changing their target or paid allowance never buys a second execution.
    return sha256_digest(
        {"scope": plan.request_scope, "run": plan.run_id, "template": plan.template_digest}
    ).removeprefix("sha256:")


def bounded_probe_request(
    plan: BootstrapProbePlan, template: OperationExecutionRequest
) -> OperationWorkflowRequest:
    """No arbitrary operation, scope, unbounded budget or extra delegation enters this route."""
    provider = ProviderExecutionBinding.carried_by(template)
    if template.request_scope != plan.request_scope or template.identity.run_id != plan.run_id:
        raise ValueError("probe template belongs to a different scope or run")
    if sha256_digest(template) != plan.template_digest:
        raise ValueError("probe template no longer matches its reviewed digest")
    if template.effective_configuration_digest != plan.configuration_digest:
        raise ValueError("probe configuration no longer matches its reviewed digest")
    if provider is None or provider.binding_digest != plan.provider_binding_digest:
        raise ValueError("probe provider binding no longer matches its reviewed digest")
    if template.lane_profile not in {"claude_managed", "codex_agents"}:
        raise ValueError("bootstrap probe supports the two hosted API lanes only")
    if template.delegations or template.mcp_servers or template.tools or template.secret_refs:
        raise ValueError(
            "bootstrap probe cannot delegate or select additional tools, MCP or secrets"
        )
    limits = template.budget_limits
    cost = limits.get("currency.estimated_micros", 0)
    duration = limits.get("time.elapsed_ms", 0)
    tokens = limits.get("tokens.total", 0)
    calls = limits.get("tool.calls.total", 0)
    if not 0 < cost <= plan.max_cost_micros:
        raise ValueError("probe needs a finite admitted monetary budget within the paid cap")
    if (
        not 0 < duration <= plan.timeout_seconds * 1000
        or not 0 < tokens <= 4000
        or not 0 < calls <= 8
    ):
        raise ValueError("probe needs bounded admitted time, tokens and tool calls")
    if template.runtime_unit is not None:
        raise ValueError("bootstrap starts only a pristine immutable operation template")
    if template.model_policy.max_turns > 3:
        raise ValueError("bootstrap probe allows at most three model turns")
    if (
        provider.budgets.max_turns > 3
        or provider.budgets.max_segments != 1
        or provider.budgets.wall_clock_s > plan.timeout_seconds
    ):
        raise ValueError("sealed provider budgets exceed the bounded bootstrap policy")
    options = provider.provider_options
    if isinstance(options, ClaudeManagedOptions):
        if (
            options.multiagent
            or options.tool_placement != "cloud"
            or options.max_list_cost_minor_units * 10_000 > plan.max_cost_micros
        ):
            raise ValueError("Managed Agents provider session cap exceeds the reviewed paid budget")
    if isinstance(options, CodexAgentsOptions):
        if options.multi_agent or options.tool_placement != "openai_hosted":
            raise ValueError("bootstrap cannot select self-hosted or multiagent execution")
    unit = RuntimeUnitIdentity(
        request_scope=plan.request_scope,
        belllabs_run_id=plan.run_id,
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id=template.identity.operation_id,
        semantic_attempt=1,
        location=StageGraphUnitLocation(
            stage_id="owner-bootstrap",
            mapped_instance_id="once",
            workflow_cycle_ordinal=0,
            stage_cycle_ordinal=0,
            operation_slot_id=plan.operation_request_key,
        ),
    )
    operation = template.model_copy(update={"runtime_unit": unit})
    return OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        operation_kind="bound_operation",
        operation=operation,
        timeout_seconds=plan.timeout_seconds,
        heartbeat_timeout_seconds=10,
        segments=LaneSegmentBounds(
            max_duration_s=plan.timeout_seconds,
            max_frames=500,
            start_to_close_s=plan.timeout_seconds + 5,
            heartbeat_timeout_s=10,
            max_segments=1,
            status_poll_limit=3,
            status_poll_interval_s=1,
            busy_wait_s=1,
        ),
    )


class BootstrapProbeService:
    def __init__(self, port: BootstrapProbePort):
        self._port = port

    async def run(self, plan: BootstrapProbePlan, *, paid_budget_micros: int) -> dict[str, str]:
        if paid_budget_micros < plan.max_cost_micros:
            raise ValueError("explicit paid budget is below the reviewed bounded probe cap")
        request = bounded_probe_request(plan, await self._port.load(plan))
        workflow_id = await self._port.start(plan, request)
        evidence_ref = await self._port.prove(plan, request)
        return {"workflow_id": workflow_id, "evidence_ref": evidence_ref}
