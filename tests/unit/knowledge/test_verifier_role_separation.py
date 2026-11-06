"""W1 D27: the GoalDirected verifier never acts as the producer (OUTPUT-CONTRACTS, ADR-0058).

In run 9cc17684 the verifier inherited ``submit_output`` from the node environment and, bound to
the producer's owner position (both roles are templated at the root position), re-submitted the
producer's report as revision 2, which started a second assessment, decision and human review.
Position ownership could not refuse it: the position was the producer's. Now the launch author
leaves the producer's tools out of the verifier's agent configuration, and the host refuses them
for any invocation its sealed transfer plan binds as an independent evaluator.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_capability_id,
    live_invocation,
)
from mission_control.application.authoring import manifest_launch_inputs
from mission_control.application.authoring.manifest_launch_inputs import (
    ManifestLaunchBindingError,
)
from mission_control.application.knowledge.roles import (
    PRODUCER_TOOL_CAPABILITIES,
    PRODUCER_TOOLS,
)
from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.graph_runtime.identities import GoalDirectedUnitLocation
from mission_control.domain.outputs.contracts import OutputForm
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.authoring.test_manifest_launch_inputs import (  # noqa: F401 (fixture)
    admitted,
    chain,
    pubmed_resolver,
)
from tests.unit.knowledge.test_knowledge_tools import BINDING, RUN, lane
from tests.unit.outputs.scenario import host_access, obligation, promises

REPORT = {
    "kind": "handle",
    "ref": f"kh:{BINDING}/report/report-7@research-report.v2",
    "digest": "sha256:" + "a" * 64,
}


def test_the_producer_tools_are_named_once_for_tools_and_catalog_rows() -> None:
    assert {knowledge_capability_id(name) for name in PRODUCER_TOOLS} == PRODUCER_TOOL_CAPABILITIES
    assert "knowledge_read" not in PRODUCER_TOOLS and "verify_claims" not in PRODUCER_TOOLS


# -- the host ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_host_refuses_a_verifier_submission_for_the_producers_promise() -> None:
    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    producer = replace(h.live(), position="stage/draft")
    await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(toolset.access(producer).scope),
        RUN,
        promises(obligation("stage.report", OutputForm.REFERENCE, position="stage/draft")),
    )
    producer = await toolset.begin(producer)
    # The verifier: the same owner position (as GoalDirected templates it), evaluator role.
    verifier = replace(producer, operation_id="goal-iteration/1/verifier", evaluator=True)
    args = {"obligation": "stage.report", "items": [REPORT]}
    refused = await toolset.dispatch("submit_output", args, verifier, tool_call_id="v-1")
    assert refused["ok"] is False and refused["refusal"]["code"] == "ROLE_SEPARATION"
    for tool, arguments in (
        ("report_register", {"report": {"task": {}}}),
        ("knowledge_apply", {"decision": "kh:x/decision/d@1"}),
    ):
        other = await toolset.dispatch(tool, arguments, verifier, tool_call_id=f"v-{tool}")
        assert other["refusal"]["code"] == "ROLE_SEPARATION", other
    assert len(contracts.submissions.rows) == 0
    accepted = await toolset.dispatch("submit_output", args, producer, tool_call_id="p-1")
    assert accepted["ok"], accepted  # the producer keeps its act


def _invocation(isolation: str | None, role: str | None = None) -> Any:
    deep = SimpleNamespace(execution_generation=1, tools=())
    unit = (
        None
        if role is None
        else SimpleNamespace(
            location=GoalDirectedUnitLocation(
                goal_iteration=1,
                goal_revision_id="goal-revision-1",
                operation_role=role,  # type: ignore[arg-type]
                agent_run=1,
                session_generation=1,
            )
        )
    )
    transfer = (
        None
        if isolation is None
        else SimpleNamespace(receiver_position="root", isolation=isolation)
    )
    return SimpleNamespace(
        binding=SimpleNamespace(
            request_scope="mc/i/ai-engineer/t",
            run_id=RUN,
            operation_id="goal-iteration/1/verifier",
            operation_attempt=1,
            transfer=transfer,
            runtime_unit=unit,
            **lane_fields(deep),
        )
    )


def test_the_live_invocation_takes_the_evaluator_role_from_the_sealed_plan() -> None:
    assert live_invocation(_invocation("independent_evaluator")).evaluator is True
    assert live_invocation(_invocation("shared")).evaluator is False
    assert live_invocation(_invocation(None)).evaluator is False
    # Review item 3: without a transfer plan the sealed runtime unit's role decides (fail closed).
    assert live_invocation(_invocation(None, role="verifier")).evaluator is True
    assert live_invocation(_invocation(None, role="executor")).evaluator is False
    assert live_invocation(_invocation("shared", role="verifier")).evaluator is True


@pytest.mark.asyncio
async def test_the_verifier_declares_no_producer_promise_and_finalizes_as_owing_nothing() -> None:
    """Review item 4: the verifier pins nothing it owes; its finalization is
    `no_declared_obligations` / `fulfilled` (nothing owed), never an unfulfilled producer, and
    its settlement pass is done (no wait, no failure)."""

    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    producer = replace(h.live(), position="stage/draft", obligations=())
    await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(toolset.access(producer).scope),
        RUN,
        promises(obligation("stage.report", OutputForm.REFERENCE, position="stage/draft")),
    )
    verifier = replace(
        producer, operation_id="goal-iteration/1/verifier", evaluator=True, obligations=()
    )
    begun = await toolset.begin(verifier)
    assert begun.obligations == ()  # the producer's promise is not the verifier's
    report = await toolset.finalize(begun)
    assert (report.outcome_basis, report.outcome) == ("no_declared_obligations", "fulfilled")
    saved, open_reviews = await toolset.settle_saved(begun)
    assert saved.outcome == "fulfilled" and not saved.blocked and open_reviews == ()
    # The producer still declares and owes its promise.
    declared = await toolset.begin(producer)
    assert declared.obligations == ("stage.report",)
    assert (await toolset.finalize(declared)).outcome == "unfulfilled"


@pytest.mark.asyncio
async def test_a_child_agent_of_the_verifier_inherits_the_role_and_cannot_submit() -> None:
    """Review item 6: a sync child runs inside the verifier's bound context (the
    `CURRENT_INVOCATION` context variable is inherited by the child's nested agent run), so the
    evaluator role travels with it and the host refuses the producer's tools. A context without
    the binding (an async child on the Agent Server) has no live invocation at all."""

    import asyncio
    import json

    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, ToolMessage

    from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION

    class _Child(GenericFakeChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            del tools, kwargs
            return self

    def child() -> Any:
        call = {"obligation": "stage.report", "items": [REPORT]}
        return create_agent(
            _Child(
                messages=iter(
                    [
                        AIMessage(
                            content="",
                            tool_calls=[{"name": "submit_output", "args": call, "id": "c1"}],
                        ),
                        AIMessage(content="done"),
                    ]
                )
            ),
            tools=[h.support.tools["submit_output"]],
        )

    async def run_child() -> dict[str, Any]:
        result = await child().ainvoke({"messages": [{"role": "user", "content": "submit"}]})
        (message,) = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        return json.loads(str(message.content))

    h = lane()
    verifier = replace(h.live(), operation_id="goal-iteration/1/verifier", evaluator=True)
    token = CURRENT_INVOCATION.set(verifier)
    try:
        # A nested agent run in a task spawned from the verifier's context.
        inherited = await asyncio.create_task(run_child())
    finally:
        CURRENT_INVOCATION.reset(token)
    assert inherited["refusal"]["code"] == "ROLE_SEPARATION"
    unbound = await run_child()  # no binding in this context
    assert unbound["refusal"]["code"] == "SCOPE_DENIED"


# -- the launch author ---------------------------------------------------------------------------


def _items(definition: Any, program: Any, *, verifier: bool) -> list[str]:
    root = definition.program
    author = pubmed_resolver(definition)
    rows = author._configuration_items(
        definition,
        (root,),
        verifier=verifier,
        operation_binding_refs=admitted(program).operation_binding_refs,
        rows=None,
    )
    return [item.pin.split("@", 1)[0] for item, _pointer in rows]


def test_the_verifier_configuration_omits_inherited_producer_tools(
    chain: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definitions, programs = chain
    research = next(item for item in definitions if item.mission_key == "research")
    program = next(item for item in programs if item.mission_key == "research")
    (pubmed,) = [item for item in research.capabilities if item.alias == "pubmed"]
    pin = pubmed.resolved or pubmed.pin
    assert pin is not None
    # Stand in the fixture's inherited capability for a producer tool.
    monkeypatch.setattr(
        manifest_launch_inputs, "PRODUCER_TOOL_CAPABILITIES", frozenset({pin.capability_id})
    )
    assert pin.capability_id in _items(research, program, verifier=False)
    assert pin.capability_id not in _items(research, program, verifier=True)

    # Selected in the verifier's own environment, it refuses the launch.
    own = pubmed.model_copy(
        update={"pointer": f"{research.program.pointer}/verifier/environment/capabilities/0"}
    )
    monkeypatch.setattr(
        manifest_launch_inputs,
        "_selected_capabilities",
        lambda definition, path, *, verifier: [own],
    )
    with pytest.raises(ManifestLaunchBindingError, match="producer tool"):
        _items(research, program, verifier=True)


def test_a_real_goal_directed_verifier_template_lacks_the_producer_tools() -> None:
    """Review item 5a/5b: the real catalog rows (no monkeypatch), bound at mission level into a
    goal loop; the executor template carries all six knowledge tools, the verifier's sealed
    binding none of the producer's, and the verifier still binds its structured verdict."""

    import asyncio
    from dataclasses import replace as replace_served
    from pathlib import Path

    from mission_control.adapters.deep_agents.knowledge_tools import (
        knowledge_launch_bindings,
        knowledge_registry_tools,
        knowledge_tools,
    )
    from mission_control.application.knowledge.toolset import TOOL_NAMES
    from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
    from tests.fixtures.mission_control_common_db import canonical_scope
    from tests.unit.authoring.manifest_launch_fixture import fixture_bindings
    from tests.unit.authoring.test_manifest_launch_inputs import (
        compile_programs,
        fixture_served,
        resolver,
    )

    scope = canonical_scope("tenant-1", "ai-engineer")
    manifest = (
        Path(__file__).resolve().parents[2] / "fixtures/manifests/knowledge-tools-goal-loop.yml"
    )
    definitions, programs = asyncio.run(
        compile_programs(manifest.read_text(encoding="utf-8"), scope=scope)
    )
    definition, program = definitions[0], programs[0]
    pins = {
        item.resolved.capability_id: item.resolved.digest
        for item in definition.capabilities
        if item.resolved is not None
    }
    assert set(pins) >= PRODUCER_TOOL_CAPABILITIES  # the real rows, not a stand-in
    tools = knowledge_tools(cast(Any, None))
    bindings = fixture_bindings().model_copy(
        update={"capabilities": knowledge_launch_bindings(pins, tools)}
    )
    served = fixture_served(bindings)
    served = replace_served(served, tools=served.tools | frozenset(knowledge_registry_tools(tools)))
    templates = resolver(bindings, served=served).goal_templates(
        definition, admitted(program, scope=scope)
    )
    executor = DeepAgentExecutionBinding.carried_by(templates["executor"])
    verifier = DeepAgentExecutionBinding.carried_by(templates["verifier"])
    assert executor is not None and verifier is not None
    assert {tool.tool_name for tool in executor.tools} == set(TOOL_NAMES)
    assert {tool.tool_name for tool in verifier.tools} == set(TOOL_NAMES) - PRODUCER_TOOLS
    assert "submit_output" not in {tool.tool_name for tool in verifier.tools}
    # The verdict path is unchanged: the verifier binds its structured-output schema and its
    # sealed plan makes it an independent evaluator.
    assert templates["verifier"].output_schema is not None
    transfer = templates["verifier"].transfer
    assert transfer is not None and transfer.isolation == "independent_evaluator"
