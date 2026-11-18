"""OVE-238 G1: one manifest, compiled and launched by the real services, reaches one Deep Agents
turn exactly as it was authored; only the chat model is scripted.

The path is production code end to end below Temporal: `ManifestCompileService` over the
fast-track fixture catalog, the launch inputs (`ManifestLaunchResolver.stage_templates`, whose
Deep Agents template step seals the exact binding), the Stage Graph admission
(`StageGraphInterpreter` and `StageGraphOperationPreparationService`, which rebinds the
template to the live attempt), the harness decode (`DeepAgentsHarness.validate_request`), the
exact materializer and one real `create_deep_agent` turn through `DeepAgentRuntimeAdapter`.
The MCP server is the qualification stub (a local stdio process, no network); see
`tests/support/manifest_turn.py` for the deployment fixture.

What the agent receives is read where it receives it: the scripted model's input batches
(`seen`) and its `bind_tools` record (`bound`), the model component the materializer asked the
deployment's factory to build, and the exact binding the lane decoded.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from mission_control.adapters.deep_agents import DeepAgentRuntimeAdapter, ExactDeepAgentMaterializer
from mission_control.adapters.deep_agents.binding import execution_binding
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindingError
from mission_control.application.authoring.manifest_service import CompiledMission
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    RuntimeInvocation,
    RuntimeResult,
)
from tests.support.deep_agents import SKILL_TEXT
from tests.support.manifest_turn import (
    SKILL_CAPABILITY,
    Deployment,
    ModelRequests,
    admit_first_stage,
    catalog,
    compile_manifest,
    deployment,
    launch,
    launch_resolver,
    manifest_text,
    resolved_secrets,
    runtime_invocation,
    turn_registry,
)
from tests.support.models import ScriptedChatModel, tool_call, tool_messages

MANIFEST = "deep-agents-turn.yml"
# FIXTURE Model Catalog rows: each profile the manifest can select names its own model id.
MODELS = {"frontier.default": "g1-default-model", "frontier.long_context": "g1-long-context-model"}
SKILL_MD = "/skills/exact-binding-proof/SKILL.md"
MCP_TOOL = "lookup_binding_marker"
# deepagents 0.7.5's filesystem tools on the State backend (no `execute`): the lane's own
# surface. Neither `task` (the implicit general-purpose child) nor any unbound tool appears.
FILESYSTEM_TOOLS = ("ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep")
HOST_AUTHORITY = "BellLabs authority, budgets, lifecycle, and artifact admission remain host-owned."


@dataclass
class Turn:
    operation: OperationExecutionRequest
    invocation: RuntimeInvocation
    model: ScriptedChatModel
    requests: ModelRequests
    result: RuntimeResult


def survey(messages: list[BaseMessage], call: int) -> AIMessage:
    """Read the bound Skill, call the bound MCP tool, then answer."""

    del call
    observed = tool_messages(messages)
    if not observed:
        return tool_call("read_file", {"file_path": SKILL_MD, "limit": 1000}, "g1-skill")
    if len(observed) == 1:
        return tool_call(MCP_TOOL, {"code": "G1"}, "g1-mcp")
    return AIMessage(content="TURN-PROOF-DONE")


def answer(messages: list[BaseMessage], call: int) -> AIMessage:
    del messages, call
    return AIMessage(content="TURN-PROOF-DONE")


@pytest.fixture(scope="module")
def authored() -> tuple[MissionDefinition, CompiledMission]:
    return asyncio.run(compile_manifest(manifest_text(MANIFEST)))


async def _turn(
    definition: MissionDefinition,
    program: CompiledMission,
    script: Callable[[list[BaseMessage], int], AIMessage],
    target: Deployment | None = None,
) -> Turn:
    target = target or deployment(definition)
    admitted = launch(program)
    templates = launch_resolver(target, catalog(MODELS)).stage_templates(definition, admitted)
    operation = (await admit_first_stage(templates, admitted)).operation
    model = ScriptedChatModel(script=script, label="g1-scripted", max_calls=6)
    registry, requests = turn_registry(operation, target, model)
    harness = DeepAgentsHarness(DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(registry)))
    # The harness decode: the sealed bytes name exactly this operation's envelope.
    harness.validate_request(operation)
    invocation = await runtime_invocation(operation, program)
    result = await harness.execute(invocation, resolved_secrets(invocation))
    return Turn(operation, invocation, model, requests, result)


def _text(message: BaseMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block if isinstance(block, str) else str(block.get("text", "")) for block in message.content
    )


def _segment(operation: OperationExecutionRequest, source_ref: str) -> str:
    (segment,) = [item for item in operation.prompt_segments if item.source_ref == source_ref]
    return segment.content


def _tool_result(turn: Turn, call_id: str) -> str:
    (message,) = [
        item for item in tool_messages(turn.model.seen[-1]) if item.tool_call_id == call_id
    ]
    return _text(message)


async def test_one_manifest_reaches_the_scripted_turn_exactly_as_authored(
    authored: tuple[MissionDefinition, CompiledMission],
) -> None:
    turn = await _turn(*authored, survey)
    assert turn.result.output_text == "TURN-PROOF-DONE"
    assert not turn.result.budget_stop

    # The system message: the Purpose Card first, written from the authored brief and node,
    # then the fixed host-authority line; the authored instruction is not an instruction here.
    system, human = turn.model.seen[0][:2]
    assert (system.type, human.type) == ("system", "human")
    card = _segment(turn.operation, "host:purpose-card")
    system_text = _text(system)
    assert system_text.startswith(card)
    assert "TURN-PROOF-REQUEST: prove one Deep Agents turn receives what was authored." in card
    assert "- Node `survey`, behaviour `agent_executor`" in card
    assert "- MCP server `pubmed`\n- skill `lit_review`\n" in card
    assert "- Budget: usd 5; tokens 200000; tool_calls 7." in card
    assert HOST_AUTHORITY in system_text
    assert "TURN-PROOF-INSTRUCTION" not in system_text
    # The user message: the stage objective, then the node's authored instruction.
    assert _text(human) == (
        "Mission turn-proof stage survey: Map the evidence\n\n"
        "TURN-PROOF-INSTRUCTION: cite every claim with its PubMed id."
    )

    # Exactly the bound tools on every call: the lane's filesystem, the one MCP tool the bound
    # server serves, and no implicit general-purpose child (`task`).
    assert turn.model.bound and all(
        entry["tools"] == [*FILESYSTEM_TOOLS, MCP_TOOL] for entry in turn.model.bound
    )
    # Exactly the bound Skill: listed in the system prompt at its mount, read from that mount.
    sealed = execution_binding(turn.invocation.binding)
    assert [item.skill_name for item in sealed.skills] == ["exact-binding-proof"]
    assert SKILL_MD in system_text and "exact-binding-proof" in system_text
    assert "SKILL-MD-IN-MESSAGES-040" in _tool_result(turn, "g1-skill")
    assert "SKILL-MD-IN-MESSAGES-040" in SKILL_TEXT
    # The MCP tool call reached the bound qualification server.
    assert "MCP-BOUND::G1::EXACT" in _tool_result(turn, "g1-mcp")

    # The model: the catalog row the manifest's profile selects, with the authored settings.
    (built,) = turn.requests.built
    assert (built.model.provider, built.model.model_name) == ("openai", "g1-default-model")
    assert built.model.settings["temperature"] == 0.2
    assert turn.operation.model_policy.model == "g1-default-model"

    # The sealed budget inside the turn: the authored run budget's in-turn dimensions.
    assert turn.invocation.run_budget_remaining == {"tokens.total": 200000, "tool.calls.total": 7}
    assert turn.result.usage.amounts["tool.calls.total"] == 2
    assert turn.result.usage.amounts["model.turns"] == 3

    # The network grant: the authored allowlist, sealed into the live binding the lane decoded
    # and the configuration the materializer built from.
    for binding in (sealed, built):
        assert binding.capability_grant.network_hosts == frozenset({"eutils.ncbi.nlm.nih.gov"})
        assert binding.workspace.network_policy == "allowlisted"
    # And the turn ran on the live attempt, never on the template's coordinates.
    assert sealed.run_id == "run-manifest-turn" and "manifest-template/" not in sealed.operation_id


async def test_a_smaller_authored_tool_call_budget_stops_the_turn_before_its_mcp_call() -> None:
    definition, program = await compile_manifest(
        manifest_text(
            MANIFEST, **{"environment/budget": {"usd": 5, "tokens": 200000, "tool_calls": 1}}
        )
    )
    turn = await _turn(definition, program, survey)
    assert turn.invocation.run_budget_remaining["tool.calls.total"] == 1
    # The Skill read ran; the MCP call was refused before it ran, and the stop answered the
    # next model call (the scripted model was called twice, never a third time).
    assert turn.result.budget_stop == {"tool.calls.total": {"limit": 1, "spent": 2}}
    assert len(turn.model.calls) == 2
    assert not any(
        "MCP-BOUND::" in _text(item) for batch in turn.model.seen for item in tool_messages(batch)
    )
    assert turn.result.usage.amounts["tool.calls.total"] == 1


async def test_another_profile_and_no_mcp_server_change_what_the_agent_receives() -> None:
    definition, program = await compile_manifest(
        manifest_text(
            MANIFEST,
            **{
                "environment/model": {"profile": "frontier.long_context"},
                "environment/capabilities": [
                    {
                        "search": "biotech literature review procedure",
                        "kind": "skill_bundle",
                        "as": "lit_review",
                    }
                ],
            },
        )
    )
    turn = await _turn(definition, program, answer)
    (built,) = turn.requests.built
    assert built.model.model_name == "g1-long-context-model"
    assert all(entry["tools"] == list(FILESYSTEM_TOOLS) for entry in turn.model.bound)
    assert execution_binding(turn.invocation.binding).mcp_servers == ()
    assert "- MCP server `pubmed`" not in _text(turn.model.seen[0][0])


def test_a_capability_the_deployment_does_not_serve_refuses_at_its_manifest_pointer(
    authored: tuple[MissionDefinition, CompiledMission],
) -> None:
    definition, program = authored
    served = deployment(definition)
    unserved = replace(
        served,
        bindings=served.bindings.model_copy(
            update={
                "capabilities": {
                    key: value
                    for key, value in served.bindings.capabilities.items()
                    if key != SKILL_CAPABILITY
                }
            }
        ),
    )
    with pytest.raises(ManifestLaunchBindingError) as refused:
        launch_resolver(unserved, catalog(MODELS)).stage_templates(definition, launch(program))
    assert refused.value.pointer == "/mission/environment/capabilities/1"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PRODUCT GAP (OVE-238 G1): a node's `environment.budget` overlay is resolved into the "
        "MissionDefinition but never bounds the Deep Agents turn. The stage template seals the "
        "mission-level ceilings (application/authoring/manifest_launch_inputs.py:2491, "
        "`budget_limits=dict(admitted.authority.budgets.dimensions)`), the Stage Graph admission "
        "replaces them with the proposal reservation (application/programs/service.py:2344, "
        "`budget_limits: proposal.reservation`), and the in-turn run budget is the run account's "
        "(adapters/deep_agents/adapter.py:2134 `_turn_limits`). The codex, claude and cursor "
        "lanes narrow by the node budget (`_narrowed_budgets`, manifest_launch_inputs.py:3186)."
    ),
)
async def test_a_node_budget_overlay_bounds_that_nodes_turn() -> None:
    definition, program = await compile_manifest(
        manifest_text(MANIFEST, **{"program/nodes/0/environment": {"budget": {"tool_calls": 1}}})
    )
    (node,) = definition.program.nodes
    # Compile resolved the overlay onto the node (mission-level tool_calls is 7).
    assert node.environment.budget is not None and node.environment.budget.tool_calls == 1
    target = deployment(definition)
    admitted = launch(program)
    templates = launch_resolver(target, catalog(MODELS)).stage_templates(definition, admitted)
    operation = (await admit_first_stage(templates, admitted)).operation
    invocation = await runtime_invocation(operation, program)
    # What the turn's budget stop reads (`_turn_limits`): the tighter of the unit's sealed
    # reservation and the run budget the turn receives.
    bounds = [
        source["tool.calls.total"]
        for source in (invocation.binding.budget_limits, invocation.run_budget_remaining)
        if "tool.calls.total" in source
    ]
    assert min(bounds) == 1
