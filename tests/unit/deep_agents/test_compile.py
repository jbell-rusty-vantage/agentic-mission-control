"""The Deep Agents lane compile (OC-R1 / OVE-196): refusal codes and the sealed node binding; and
the lane's own bytes (OC-R2 / OVE-197): the template step that seals a template's `lane_binding`,
the per-attempt rebind, and the decode that checks the bytes against the operation envelope."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.adapters.deep_agents.binding import (
    DEEP_AGENTS_LANE_BINDINGS,
    execution_binding,
)
from mission_control.adapters.deep_agents.compile import (
    DEEP_AGENT_NODE_BINDING_SCHEMA,
    DeepAgentNodeBinding,
    DeepAgentsCompileAdapter,
)
from mission_control.adapters.deep_agents.harness import (
    DeepAgentsHarness,
)
from mission_control.application.execution.harness.protocol import (
    ValidatesOperationRequest,
)
from mission_control.application.resolution.lane_bindings import (
    LaneInvocation,
    LaneRebinders,
    LaneTemplateCoordinates,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    DeepAgentExecutionBinding,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    PromptSegment,
)
from mission_control.domain.execution.errors import DeepAgentMaterializationError
from mission_control.domain.execution.lanes import LaneDispatch
from mission_control.domain.execution.materialization import compile_deep_agent_execution_binding
from mission_control.domain.graph_runtime.identities import (
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)
from mission_control.domain.resolution import item_config
from mission_control.domain.resolution.configuration import AgentConfiguration, ConfigurationItem
from mission_control.domain.resolution.resolved import LaneCompileRefused, SealedLaneBinding
from tests.conformance.lanes.compile.deep_agents import authored, deep_agents_facts
from tests.conformance.lanes.compile.fixtures import CANONICAL_ITEMS, canonical_agent
from tests.unit.operations.test_operation_execution import operation_request, service_fixture

SUPPORTED = tuple(
    item for item in CANONICAL_ITEMS if item.kind not in {"hook_script", "environment_kit"}
)


def _agent(**changes: Any) -> AgentConfiguration:
    return authored(canonical_agent("deep_agents", items=changes.pop("items", SUPPORTED)))


def _refusal(agent: AgentConfiguration, options: dict[str, Any] | None = None) -> Any:
    with pytest.raises(LaneCompileRefused) as refused:
        DeepAgentsCompileAdapter(deep_agents_facts()).compile(agent, options or {})
    return refused.value.refusal


def _coordinates() -> LaneTemplateCoordinates:
    request = operation_request()
    return LaneTemplateCoordinates(
        run_id="run-r1",
        operation_id="manifest-template/stage/execute/default",
        operation_attempt=1,
        execution_generation=1,
        control_revision=1,
        erc_digest=sha256_digest("erc"),
        workspace=request.workspace,
        capabilities=frozenset({"research.read"}),
        reservation_id="reservation:run-r1:manifest-template",
    )


def _runtime_unit() -> RuntimeUnitIdentity:
    return RuntimeUnitIdentity(
        request_scope="installation:i/application:a/tenant:t",
        belllabs_run_id="run-r1",
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id="operation-1",
        semantic_attempt=2,
        location=StageGraphUnitLocation(
            stage_id="stage",
            mapped_instance_id="default",
            workflow_cycle_ordinal=0,
            stage_cycle_ordinal=0,
            operation_slot_id="execute",
        ),
    )


def test_the_payload_is_canonical_json_the_bridge_reads_back_exactly() -> None:
    adapter = DeepAgentsCompileAdapter(deep_agents_facts())
    sealed, receipt = adapter.compile(_agent(), {})

    assert sealed.schema_id == DEEP_AGENT_NODE_BINDING_SCHEMA
    document = json.loads(sealed.payload)
    assert list(document) == sorted(document)
    node = DeepAgentNodeBinding.model_validate_json(sealed.payload)
    assert node.canonical_bytes() == sealed.payload
    assert node.receipt == receipt
    assert [child.name for child in node.profile.sync_subagents] == ["summarizer", "verifier"]
    assert [child.name for child in node.profile.async_subagents] == ["async-verifier"]


def test_the_template_step_seals_the_exact_binding_for_the_template_coordinates() -> None:
    sealed, receipt = DeepAgentsCompileAdapter(deep_agents_facts()).compile(_agent(), {})
    coordinates = _coordinates()
    part = DEEP_AGENTS_LANE_BINDINGS(sealed, coordinates)
    node = DeepAgentNodeBinding.model_validate_json(sealed.payload)

    assert part.lane_binding.lane_profile == "deep_agents"
    assert part.lane_binding.schema_id == "belllabs.deep-agent-binding.v1"
    binding = DeepAgentExecutionBinding.unseal(part.lane_binding)
    assert part.lane_dispatch == binding.lane_dispatch()
    assert part.lane_dispatch.heartbeat_class == "deep_agent_async_children"
    assert binding.content_digest() == binding.binding_digest
    assert binding.materialization_receipt == receipt
    assert binding.workspace == coordinates.workspace
    assert binding.run_id == "run-r1"
    expected = compile_deep_agent_execution_binding(
        profile=node.profile,
        placement=node.placement,
        state_schema=node.state_schema,
        context_schema=node.context_schema,
        context_values=dict(binding.cognitive_context_values),
        run_id=coordinates.run_id,
        operation_id=coordinates.operation_id,
        operation_attempt=1,
        execution_generation=1,
        erc_digest=coordinates.erc_digest,
        control_revision=1,
        workspace=coordinates.workspace,
        capability_grant=part.capability_grant,
        reservation_id=coordinates.reservation_id,
        authority_refs=node.authority_refs,
        redaction_policy_ref=node.redaction_policy_ref,
        initial_context_manifest=node.initial_context_manifest,
        applied_degradations=receipt.degradations,
        materialization_receipt=receipt,
    )
    assert binding == expected
    assert part.capability_grant.mcp_server_ids == {"browser", "firecrawl"}
    assert part.capability_grant.capabilities == {"research.read"}
    assert part.model_policy.provider == "anthropic"
    assert part.execution_runtime == "deep_agent"


def test_the_template_step_reads_only_its_own_schema() -> None:
    other = SealedLaneBinding.seal(
        lane_profile="deep_agents", schema_id="mc.stub_lane_binding.v1", payload=b"{}"
    )
    with pytest.raises(ValueError, match=DEEP_AGENT_NODE_BINDING_SCHEMA):
        DEEP_AGENTS_LANE_BINDINGS(other, _coordinates())


def test_the_rebind_reseals_the_template_for_one_live_attempt_by_digest() -> None:
    sealed, _receipt = DeepAgentsCompileAdapter(deep_agents_facts()).compile(_agent(), {})
    part = DEEP_AGENTS_LANE_BINDINGS(sealed, _coordinates())
    template = DeepAgentExecutionBinding.unseal(part.lane_binding)
    unit = _runtime_unit()
    invocation = LaneInvocation(
        binding_id="deep-agent:live",
        run_id="run-r1",
        operation_id="operation-1",
        operation_attempt=2,
        execution_generation=3,
        erc_digest=template.erc_digest,
        control_revision=4,
        workspace=template.workspace,
        reservation_id="reservation-live",
        runtime_unit=unit,
        capability_grant=part.capability_grant,
    )
    rebinders = LaneRebinders({"deep_agents": DEEP_AGENTS_LANE_BINDINGS})

    rebound, dispatch = rebinders.rebind(part.lane_binding, part.lane_dispatch, invocation)

    live = DeepAgentExecutionBinding.unseal(rebound)
    assert rebound.digest != part.lane_binding.digest
    assert (live.operation_id, live.operation_attempt, live.execution_generation) == (
        "operation-1",
        2,
        3,
    )
    assert live.cognitive_context_values.get("operation_id", "operation-1") == "operation-1"
    assert dispatch == live.lane_dispatch() and dispatch.execution_generation == 3


def test_a_lane_without_a_rebinder_keeps_its_bytes_and_follows_the_generation() -> None:
    other = SealedLaneBinding.seal(
        lane_profile="cursor_local", schema_id="mc.cursor_binding.v2", payload=b"{}"
    )
    dispatch = LaneDispatch(task_queue="cursor-q", wall_clock_s=60)
    invocation = LaneInvocation(
        binding_id="b",
        run_id="run-r1",
        operation_id="operation-1",
        operation_attempt=1,
        execution_generation=2,
        erc_digest="sha256:" + "1" * 64,
        control_revision=1,
        workspace=_coordinates().workspace,
        reservation_id="r",
        runtime_unit=_runtime_unit(),
        capability_grant=CapabilityGrant(capabilities=frozenset()),
    )

    rebound, moved = LaneRebinders().rebind(other, dispatch, invocation)

    assert rebound == other
    assert moved == dispatch.model_copy(update={"execution_generation": 2})


def _template_request() -> tuple[OperationExecutionRequest, DeepAgentExecutionBinding, Any]:
    sealed, _receipt = DeepAgentsCompileAdapter(deep_agents_facts()).compile(_agent(), {})
    part = DEEP_AGENTS_LANE_BINDINGS(sealed, _coordinates())
    template = DeepAgentExecutionBinding.unseal(part.lane_binding)
    request = OperationExecutionRequest(
        identity=OperationAttemptIdentity(
            run_id=template.run_id,
            operation_id=template.operation_id,
            operation_attempt=template.operation_attempt,
        ),
        request_scope="installation:i/application:a/tenant:t",
        effective_configuration_digest=template.erc_digest,
        run_control_revision=template.control_revision,
        operation_contract_ref="operation-contract:test",
        prompt_segments=(
            PromptSegment(
                source_ref="objective",
                source_revision=1,
                trust_class="admitted_input",
                content="x",
                rendered_digest=sha256_digest("x"),
            ),
        ),
        model_policy=part.model_policy,
        agent_profile_ref=part.agent_profile_ref,
        capability_grant=part.capability_grant,
        workspace=template.workspace,
        execution_runtime="deep_agent",
        lane_binding=part.lane_binding,
        lane_dispatch=part.lane_dispatch,
        budget_reservation_id=template.reservation_id,
        budget_limits={},
        tracing_policy_ref=part.tracing_policy_ref,
        sensitive_data_policy_ref=part.sensitive_data_policy_ref,
        snapshot_policy_ref=part.snapshot_policy_ref,
        requested_at=datetime(2026, 10, 27, tzinfo=UTC),
        idempotency_key="k",
    )
    return request, template, part


# The authority envelope a sealed Deep Agents binding must name (each field a drift).
ENVELOPE_DRIFTS: tuple[dict[str, Any], ...] = (
    {"budget_reservation_id": "another-reservation"},
    {"run_control_revision": 9},
    {"effective_configuration_digest": sha256_digest("another-erc")},
    {
        "identity": OperationAttemptIdentity(
            run_id="run-r1", operation_id="other", operation_attempt=1
        )
    },
    {
        "identity": OperationAttemptIdentity(
            run_id="other-run", operation_id="x", operation_attempt=1
        )
    },
)


def test_the_lane_decode_refuses_bytes_outside_the_operation_envelope() -> None:
    request, template, part = _template_request()
    assert execution_binding(request) == template

    for drift in ENVELOPE_DRIFTS:
        with pytest.raises(DeepAgentMaterializationError, match="authority envelope"):
            execution_binding(request.model_copy(update=drift))
    with pytest.raises(DeepAgentMaterializationError, match="lane dispatch"):
        execution_binding(
            request.model_copy(
                update={"lane_dispatch": part.lane_dispatch.model_copy(update={"task_queue": "x"})}
            )
        )


@pytest.mark.parametrize("drift", ENVELOPE_DRIFTS)
async def test_admission_refuses_an_envelope_drift_before_authority_or_binding(
    drift: dict[str, Any],
) -> None:
    """OC-R2 review item 2: the Deep Agents harness's `ValidatesOperationRequest` hook runs
    before the operation service verifies authority and the budget reservation, binds or
    claims; a drifted envelope leaves no binding and asks the authority nothing."""

    request, _template, _part = _template_request()
    drifted = OperationExecutionRequest.model_validate(
        {**request.model_dump(mode="python"), **drift}
    )
    harness = DeepAgentsHarness(SimpleNamespace())  # type: ignore[arg-type]
    assert isinstance(harness, ValidatesOperationRequest)
    harness.validate_request(request)
    with pytest.raises(ValueError, match="authority envelope"):
        harness.validate_request(drifted)

    service, bindings, runtime, _events, _budget = service_fixture()
    verified: list[object] = []
    service._authority = SimpleNamespace(  # type: ignore[attr-defined]
        verify=lambda *args: verified.append(args)
    )
    with pytest.raises(ValueError, match="authority envelope"):
        await service.execute(drifted)
    assert verified == []
    assert runtime.invocations == []
    assert (
        await bindings.get_binding(
            drifted.identity.semantic_key, request_scope=drifted.request_scope
        )
        is None
    )


def test_an_unserved_pin_refuses_at_its_item() -> None:
    unknown = ConfigurationItem.create(
        kind="mcp_server",
        name="pubmed",
        pin="mcp.pubmed@1.0.0#" + sha256_digest("mcp.pubmed"),
        required=True,
    )
    agent = _agent(items=(*SUPPORTED, unknown))
    refusal = _refusal(agent)

    assert refusal.code == "ITEM_PIN_UNSERVED"
    assert refusal.pointer == f"/items/{[item.name for item in agent.items].index('pubmed')}"
    assert "has no deployment component binding" in refusal.reason


def test_a_drifted_pin_refuses_with_the_bound_revision() -> None:
    (skill,) = [item for item in SUPPORTED if item.kind == "skill_bundle"]
    drifted = skill.model_copy(
        update={
            "pin": skill.pin.split("#")[0] + "#" + sha256_digest("other"),
            "digest": sha256_digest("other"),
        }
    )
    refusal = _refusal(_agent(items=tuple(drifted if i is skill else i for i in SUPPORTED)))
    assert refusal.code == "ITEM_PIN_UNSERVED"
    assert "but the deployment binds" in refusal.reason


def test_invalid_provider_options_refuse_as_lane_options() -> None:
    refusal = _refusal(_agent(), {"no_such_option": True})
    assert refusal.code == "LANE_OPTIONS_INVALID"
    assert refusal.pointer.startswith("/provider_options/deep_agents")


def test_a_required_hook_script_is_unsupported_on_this_lane() -> None:
    (hook,) = [item for item in CANONICAL_ITEMS if item.kind == "hook_script"]
    agent = _agent(items=(*SUPPORTED, hook.model_copy(update={"required": True})))
    refusal = _refusal(agent)
    assert refusal.code == "ITEM_UNSUPPORTED_ON_LANE"
    assert " hook" in refusal.reason and "no Deep Agents launch binding" in refusal.reason


def test_an_unbound_async_graph_is_an_unserved_pin() -> None:
    renamed = SubagentProfile.model_validate(
        {
            "name": "unbound",
            "description": "No graph serves it.",
            "prompt": "Work.",
            "kind": "async",
            "placement": "agent_server",
        }
    )
    item = ConfigurationItem.create(
        kind="subagent_profile",
        name="unbound",
        pin="subagent.unbound@1.0.0#" + sha256_digest("subagent.unbound"),
        required=True,
        config={
            item_config.ROLE: "agent",
            item_config.PROFILE: renamed.model_dump(mode="json"),
            item_config.POSITION: 9,
        },
    )
    base = _agent()
    agent = AgentConfiguration.create(
        lane_profile=base.lane_profile,
        node_ref=base.node_ref,
        instructions_ref=base.instructions_ref,
        model=base.model,
        items=(*base.items, item),
        budgets=base.budgets,
        data_class=base.data_class,
        data_class_source=base.data_class_source,
    )
    refusal = _refusal(agent)
    assert refusal.code == "ITEM_PIN_UNSERVED"
    assert refusal.pointer == f"/items/{[i.name for i in agent.items].index('unbound')}"


def test_a_process_without_deployment_facts_compiles_nothing() -> None:
    with pytest.raises(LaneCompileRefused) as refused:
        DeepAgentsCompileAdapter(None).compile(_agent(), {})
    refusal = refused.value.refusal
    assert (refusal.code, refusal.pointer) == ("LANE_UNKNOWN", "/lane")
    assert "composes no deployment facts" in refusal.reason


def test_without_a_scaffold_every_node_refuses() -> None:
    facts = deep_agents_facts()
    adapter = DeepAgentsCompileAdapter(replace(facts, scaffold=None))
    with pytest.raises(LaneCompileRefused) as refused:
        adapter.compile(_agent(), {})
    refusal = refused.value.refusal
    assert (refusal.code, refusal.pointer) == ("ITEM_PIN_UNSERVED", "/lane")
    assert "no scaffold" in refusal.reason


def _member(kind: Any, name: str, *, plugin: str = "plugin.browser@1.0.0") -> ConfigurationItem:
    return ConfigurationItem.create(
        kind=kind,
        name=name,
        pin=f"{name}@1.0.0#" + sha256_digest(name),
        required=True,
        config={
            item_config.ROLE: "skill",
            item_config.PLUGIN_MEMBER_ROLE: "skill",
            item_config.PLUGIN: plugin,
        },
    )


def test_a_node_plugin_is_refused_at_its_row_after_hooks() -> None:
    member = _member("skill_bundle", "skill.plugin-member")
    agent = _agent(items=(*SUPPORTED, member))
    refusal = _refusal(agent)
    index = [item.name for item in agent.items].index("skill.plugin-member")
    assert refusal.pointer == f"/items/{index}/plugin"
    assert refusal.reason.startswith("plugin plugin.browser@1.0.0 has no deployment component")
    (hook,) = [item for item in CANONICAL_ITEMS if item.kind == "hook_script"]
    both = _agent(items=(*SUPPORTED, member, hook.model_copy(update={"required": True})))
    first = _refusal(both)
    assert first.pointer == f"/items/{[item.name for item in both.items].index('policy')}"


def test_a_daytona_sandbox_without_a_served_factory_refuses_at_compile() -> None:
    # OVE-216: no Daytona factory exists, so a sandbox profile bound to a Daytona component is
    # refused before any run (ITEM_PIN_UNSERVED), never at materialization time.
    from tests.conformance.lanes.compile.deep_agents import SANDBOX_PROFILE

    facts = deep_agents_facts()
    bound = facts.sandbox_profiles[SANDBOX_PROFILE]
    daytona = bound.model_copy(
        update={
            "backend": "daytona",
            "ref": bound.ref.model_copy(update={"digest": sha256_digest("daytona-sandbox")}),
        }
    )
    facts = replace(facts, sandbox_profiles={**facts.sandbox_profiles, SANDBOX_PROFILE: daytona})
    with pytest.raises(LaneCompileRefused) as refused:
        DeepAgentsCompileAdapter(facts).compile(_agent(), {})
    refusal = refused.value.refusal
    assert refusal.code == "ITEM_PIN_UNSERVED"
    assert "is not served by this deployment" in refusal.reason
