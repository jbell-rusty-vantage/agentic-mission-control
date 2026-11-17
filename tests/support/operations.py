"""Builders, constants and fakes shared from tests/unit/operations/test_operation_execution.py."""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.operations.conformance import (
    ConformanceAssetVerifier,
    ConformanceAuthority,
    ConformanceBudgetAuthority,
    ConformanceEventSink,
    ConformanceRuntime,
    ConformanceSandbox,
    ConformanceSecretResolver,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
    OperationExecutionJournalPort,
    OperationExecutionService,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef, SecretRef
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    ImmutableAssetBinding,
    MCPServerBinding,
    ModelPolicy,
    NativeOperationExecutionPlacement,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
    PromptSegment,
    PromptTrustClass,
    WorkspaceContract,
)

NOW = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
MCP_DIGEST = "sha256:" + "b" * 64
SKILL_DIGEST = "sha256:" + "c" * 64
SECRET_VALUE = "must-never-be-persisted"


def exact(kind: DefinitionKind, logical_id: str, digest: str = DIGEST) -> ExactDefinitionRef:
    return ExactDefinitionRef(kind=kind, logical_id=logical_id, revision=1, digest=digest)


def operation_request(
    *, attempt: int = 1, prompt: str = "Return BINDING-OK"
) -> OperationExecutionRequest:
    return OperationExecutionRequest(
        identity=OperationAttemptIdentity(
            run_id="run-operation",
            operation_id="sandbox-agent",
            operation_attempt=attempt,
        ),
        request_scope="tenant-1",
        effective_configuration_digest=DIGEST,
        run_control_revision=4,
        operation_contract_ref="operation:sandbox-agent@1",
        prompt_segments=(
            PromptSegment(
                source_ref="prompt:system@1",
                source_revision=1,
                trust_class=PromptTrustClass.SYSTEM_AUTHORITY,
                content="Use only the exact bound capabilities.",
                rendered_digest=sha256_digest("Use only the exact bound capabilities."),
            ),
            PromptSegment(
                source_ref="input:manifest@1",
                source_revision=1,
                trust_class=PromptTrustClass.ADMITTED_INPUT,
                content=prompt,
                rendered_digest=sha256_digest(prompt),
            ),
        ),
        model_policy=ModelPolicy(
            provider="openai",
            model="gpt-5-mini",
            reasoning_effort="minimal",
            verbosity="low",
            max_turns=2,
        ),
        mcp_servers=(
            MCPServerBinding(
                server_id="fixture-mcp",
                revision=1,
                transport="streamable_http",
                endpoint_ref="secretless-fixture://mcp",
                allowed_tools=frozenset({"lookup_fixture"}),
                schema_digest=MCP_DIGEST,
                approval_policy="always",
            ),
        ),
        skills=(
            ImmutableAssetBinding(
                ref=exact(DefinitionKind.SKILL, "fixture.skill", SKILL_DIGEST),
                manifest_digest=SKILL_DIGEST,
                mount_path="/skills/fixture/SKILL.md",
            ),
        ),
        agent_profile_ref=exact(DefinitionKind.AGENT_PROFILE, "fixture.agent"),
        capability_grant=CapabilityGrant(
            capabilities=frozenset({"model.invoke", "sandbox.execute", "mcp.call"}),
            mcp_server_ids=frozenset({"fixture-mcp"}),
        ),
        workspace=WorkspaceContract(
            namespace_id="workspace-namespace:run-operation",
            workspace_id=f"workspace:run-operation:attempt:{attempt}",
            provider="conformance-sandbox",
            template_ref=exact(DefinitionKind.WORKSPACE_TEMPLATE, "fixture.workspace"),
            exclusive_write_paths=("/workspace/output",),
            runtime_digest=DIGEST,
            image_digest=DIGEST,
            package_digest=DIGEST,
            environment_digest=DIGEST,
        ),
        secret_refs=(SecretRef(provider="environment", key="OPENAI_API_KEY"),),
        budget_reservation_id="reservation:operation",
        budget_limits={"model.turns": 2, "tokens.total": 20},
        tracing_policy_ref="tracing:no-sensitive-data@1",
        sensitive_data_policy_ref="sensitive:redact@1",
        snapshot_policy_ref="snapshot:on-failure@1",
        native_placement=NativeOperationExecutionPlacement.create(
            placement_id="native.conformance",
            revision=1,
            task_queue="operation-execution-conformance",
            qualification_refs=("QUAL-CP-TEMPORAL-REPLAY-RECOVERY",),
        ),
        prior_binding_id=None if attempt == 1 else "prior-binding",
        requested_at=NOW,
        idempotency_key=f"side-effect:run-operation:sandbox-agent:{attempt}",
    )


def service_fixture(
    *,
    assets: ConformanceAssetVerifier | None = None,
    runtime: ConformanceRuntime | None = None,
    journal: OperationExecutionJournalPort | None = None,
    lineage: CheckpointLineageService | None = None,
    authority: ConformanceAuthority | None = None,
) -> tuple[
    OperationExecutionService,
    InMemoryOperationBindingRepository,
    ConformanceRuntime,
    ConformanceEventSink,
    ConformanceBudgetAuthority,
]:
    request = operation_request()
    bindings = InMemoryOperationBindingRepository()
    runtime = runtime or ConformanceRuntime()
    events = ConformanceEventSink()
    budget = ConformanceBudgetAuthority()
    asset_verifier = assets or ConformanceAssetVerifier(
        mcp_schema_digests={"fixture-mcp": MCP_DIGEST},
        asset_manifest_digests={"skill:fixture.skill:1": SKILL_DIGEST},
    )
    service = OperationExecutionService(
        authority=authority
        or ConformanceAuthority(
            accepted_run_id=request.identity.run_id,
            configuration_digest=request.effective_configuration_digest,
            control_revision=request.run_control_revision,
            reservation_id=request.budget_reservation_id,
        ),
        bindings=bindings,
        lanes=LaneRegistry([DeepAgentsHarness(runtime)]),
        sandbox=ConformanceSandbox(),
        assets=asset_verifier,
        mcp=asset_verifier,
        secrets=ConformanceSecretResolver({"environment:OPENAI_API_KEY": SECRET_VALUE}),
        events=events,
        budget=budget,
        journal=journal,
        lineage=lineage,
    )
    return service, bindings, runtime, events, budget


def _workflow_request() -> OperationWorkflowRequest:
    operation = operation_request()
    return OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        operation_kind="bound_operation",
        operation=operation,
    )
