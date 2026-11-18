"""OVE-238 G2: a manifest's named output promise, in memory from compile to fulfillment.

One chain of production code, with only the chat model scripted:

1. compile (`ManifestCompileService`): the stage's `outputs:` entry becomes the blueprint's
   `survey.claims` promise, pinned to the published `claim_table@1` schema;
2. launch: `LaunchPromiseRegistrar` registers the admitted promises; the launch inputs bind the
   pinned `tool.knowledge-submit-output` row to the served tool; the Stage Graph admission binds
   the receiver position;
3. the Deep Agents tool projection: the outputs-only lane of an installation without a
   knowledge binding (`bootstrap.composition.compose_output_lane`, here over the src
   in-memory output-contract store and invocation locator), whose `submit_output` is the real
   `StructuredTool` the materializer binds to the model;
4. one scripted `create_deep_agent` turn that calls `submit_output`;
5. settlement: the lane's saved-result settlement pass (`DeepAgentsHarness.settle_invocation`);
6. fulfillment: the Stage Graph's named-output reconciliation (`NamedStageOutputs`), which
   validates, promotes and decides the stage's promises.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import StructuredTool

from mission_control.adapters.deep_agents import DeepAgentRuntimeAdapter, ExactDeepAgentMaterializer
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.deep_agents.knowledge_tools import (
    KnowledgeLaneSupport,
    knowledge_launch_bindings,
    served_tool_definitions,
)
from mission_control.adapters.knowledge.invocation_locator import InMemoryInvocationLocator
from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
from mission_control.application.authoring.manifest_service import CompiledMission
from mission_control.application.knowledge.toolset import KnowledgeToolset
from mission_control.application.outputs.fulfillment import OutputFulfillmentService, OutputSetRef
from mission_control.application.outputs.launch import LaunchPromiseRegistrar
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.programs.named_outputs import (
    NamedStageOutputs,
    NamedStageReconciliation,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.invocation_settlement import SettlementOutcome
from mission_control.domain.outputs.contracts import FulfillmentResult
from tests.support.manifest_turn import (
    admit_first_stage,
    capability_digest,
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
from tests.unit.outputs.scenario import CLAIMS_SCHEMA, codes, fulfillment, host_access

MANIFEST = "deep-agents-promises.yml"
PROMISE = "survey.claims"
SUBMIT_TOOL = "tool.knowledge-submit-output"
MODELS = {"frontier.default": "g2-model", "frontier.long_context": "g2-long-context-model"}
MISSION = "44444444-4444-4444-8444-444444444444"
ACTIVATION = "55555555-5555-4555-8555-555555555555"
NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
VALUE = {"claims": [{"study": "PMID:41", "claim": "supported"}]}
# `claim` is required by claim_table@1.
INVALID = {"claims": [{"study": "PMID:41"}]}
FILESYSTEM_TOOLS = ("ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep")


def submits(value: dict[str, Any]) -> Callable[[list[BaseMessage], int], AIMessage]:
    def script(messages: list[BaseMessage], call: int) -> AIMessage:
        del call
        if not tool_messages(messages):
            return tool_call(
                "submit_output",
                {
                    "action": "submit",
                    "obligation": PROMISE,
                    "items": [{"kind": "inline", "value": value}],
                },
                "g2-submit",
            )
        return AIMessage(content="submitted")

    return script


def stops(messages: list[BaseMessage], call: int) -> AIMessage:
    del messages, call
    return AIMessage(content="nothing to submit")


@dataclass
class Run:
    store: InMemoryOutputContractStore
    outputs: OutputFulfillmentService
    lane: KnowledgeLaneSupport
    model: ScriptedChatModel
    acks: list[dict[str, Any]]
    settlement: SettlementOutcome
    reconciliation: NamedStageReconciliation
    reconcile: Callable[[], Any]
    scope: str
    run_id: str


@pytest.fixture(scope="module")
def authored() -> tuple[MissionDefinition, CompiledMission]:
    return asyncio.run(
        compile_manifest(manifest_text(MANIFEST), output_schemas={"claim_table@1": CLAIMS_SCHEMA})
    )


async def _run(
    authored: tuple[MissionDefinition, CompiledMission],
    script: Callable[[list[BaseMessage], int], AIMessage],
) -> Run:
    definition, program = authored
    admitted = launch(program)
    store = InMemoryOutputContractStore()
    submissions = SubmissionService(store.submissions, contracts=store, clock=lambda: NOW)
    outputs = OutputFulfillmentService(store, submissions, clock=lambda: NOW)
    promises = admitted.blueprint.output_promises
    assert promises is not None
    await LaunchPromiseRegistrar(outputs)(
        admitted.request_scope, admitted.run_id, admitted.configuration_digest, promises
    )
    # The deployment binds the pinned catalog row to the served `submit_output` definition.
    target = deployment(
        definition,
        extra=knowledge_launch_bindings(
            {SUBMIT_TOOL: capability_digest(definition, SUBMIT_TOOL)}, served_tool_definitions()
        ),
    )
    templates = launch_resolver(target, catalog(MODELS)).stage_templates(definition, admitted)
    admission = await admit_first_stage(templates, admitted)
    operation = admission.operation
    assert operation.runtime_unit is not None
    lane = KnowledgeLaneSupport(
        KnowledgeToolset(
            gateway=None,
            submissions=submissions,
            issuer="mission-control.biotech",
            clock=lambda: NOW,
            locator=InMemoryInvocationLocator(
                {admitted.run_id: MISSION},
                {(admitted.run_id, operation.runtime_unit.unit_key): ACTIVATION},
            ),
        ),
        outputs_only=True,
    )
    model = ScriptedChatModel(script=script, label="g2-scripted", max_calls=4)
    registry, _requests = turn_registry(operation, target, model, tools=lane.registry_tools)
    harness = DeepAgentsHarness(
        DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(registry), knowledge=lane)
    )
    harness.validate_request(operation)
    invocation = await runtime_invocation(operation, program)
    await harness.execute(invocation, resolved_secrets(invocation))
    acks = [json.loads(str(item.content)) for item in tool_messages(model.seen[-1])]
    settlement = await harness.settle_invocation(invocation)
    (stage,) = admitted.blueprint.stages
    named = NamedStageOutputs(store, outputs)

    async def reconcile() -> NamedStageReconciliation:
        return await named.reconcile_with_validation(
            admitted.request_scope, admission.request.proposal.identity, stage, {"output_refs": []}
        )

    return Run(
        store=store,
        outputs=outputs,
        lane=lane,
        model=model,
        acks=acks,
        settlement=settlement,
        reconciliation=await reconcile(),
        reconcile=reconcile,
        scope=admitted.request_scope,
        run_id=admitted.run_id,
    )


async def _frontier(run: Run) -> FulfillmentResult:
    """The host's decision over the run's accepted set (what a convergence boundary pins)."""

    host = host_access(run.scope)
    pinned = await run.outputs.pin_frontier(host, run.run_id)
    return await run.outputs.evaluate_frontier(
        host, OutputSetRef(run_id=run.run_id, set_id=pinned.set_id)
    )


def _decisions(run: Run, disposition: str) -> list[Any]:
    return [
        item
        for item in run.store.fulfillments.values()
        if item.obligation_key == PROMISE and item.disposition == disposition
    ]


async def test_a_submitted_promise_is_fulfilled_exactly_once_with_its_content_and_digest(
    authored: tuple[MissionDefinition, CompiledMission],
) -> None:
    run = await _run(authored, submits(VALUE))
    digest = sha256_digest(VALUE)

    # The model saw the real tool and was told the act: the lane's filesystem plus the one
    # projected `submit_output` StructuredTool, and the stage's declared contract.
    assert all(entry["tools"] == [*FILESYSTEM_TOOLS, "submit_output"] for entry in run.model.bound)
    assert isinstance(run.lane.tools["submit_output"], StructuredTool)
    user = str(run.model.seen[0][1].content)
    assert '"schema_ref": "claim_table@1"' in user
    assert (
        "Submit each declared output with the submit_output tool, one call per output "
        f"(obligation {PROMISE})"
    ) in user

    # The submission act: accepted as a draft at the host-computed digest, never fulfilled yet.
    (ack,) = run.acks
    assert ack["ok"] and ack["result"]["meaning"] == "recorded_draft", ack
    (revision,) = ack["result"]["revisions"]
    assert revision["content_digest"] == digest
    # Settlement finalized the invocation; nothing is promoted by settlement itself.
    assert run.settlement.state == "settled" and run.settlement.finalization_ref is not None
    assert run.settlement.fulfillment_refs == (f"obligation:{PROMISE}",)

    # Fulfillment: validated, promoted and decided once, bound to exactly the submitted bytes.
    reconciled = run.reconciliation
    assert reconciled.validation is not None and reconciled.validation.status == "satisfied"
    (ref,) = reconciled.result["output_bindings"]["claims"]
    assert ref.endswith(f"#digest={digest}")
    (exact,) = reconciled.fulfilled.values()
    assert exact.obligation_key == PROMISE and exact.content_digest == digest
    assert exact.candidate["value"] == VALUE
    (decided,) = _decisions(run, "fulfilled")
    assert decided.eligible_members == (exact.revision_id,)
    # Exactly once: reconciling the same attempt again records no second decision or head.
    again = await run.reconcile()
    assert again.result["output_bindings"] == reconciled.result["output_bindings"]
    assert len(_decisions(run, "fulfilled")) == 1
    head = await run.store.accepted_head(run.scope, run.run_id, PROMISE, exact.deliverable_id)
    assert head is not None and head.revision_id == exact.revision_id
    assert len(run.store.submissions.rows) == 1


@pytest.mark.parametrize(
    ("script", "refusal"),
    [(submits(INVALID), "SCHEMA_INVALID"), (stops, None)],
    ids=["schema-violation", "no-submission"],
)
async def test_a_refused_or_missing_submission_leaves_the_promise_open(
    authored: tuple[MissionDefinition, CompiledMission],
    script: Callable[[list[BaseMessage], int], AIMessage],
    refusal: str | None,
) -> None:
    run = await _run(authored, script)
    if refusal is None:
        assert run.acks == []
    else:
        (ack,) = run.acks
        assert ack["ok"] is False and ack["refusal"]["code"] == refusal
        assert ack["refusal"]["retry_state"] == "repairable"
    # Nothing was recorded, so nothing is bound, promoted or fulfilled.
    assert not run.store.submissions.rows
    assert run.reconciliation.result.get("output_bindings", {}).get("claims", []) == []
    assert not run.reconciliation.fulfilled
    assert _decisions(run, "fulfilled") == []
    # The promise stays open: the host's decision over the run reports it missing.
    decided = fulfillment(await _frontier(run), PROMISE)
    assert decided.disposition == "unfulfilled"
    assert codes(await _frontier(run), PROMISE) == ["MISSING"]
