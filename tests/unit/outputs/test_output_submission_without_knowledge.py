"""Output submission is Mission Control's own act: served without a knowledge binding.

A Deep Agents node whose manifest promises outputs submits them with ``submit_output`` on any
installation. Without a knowledge binding the toolset has no gateway: the act, the invocation
pin and the finalization are recorded in the output-contract store exactly as with one, no
knowledge effect can exist, and every other knowledge tool is refused by a typed code. The
served definition of ``submit_output`` (its definition digests) is the same with or without
the binding, so a launch author and a worker agree on it.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import (
    CURRENT_INVOCATION,
    KnowledgeLaneSupport,
    served_knowledge_tools,
    served_output_tools,
)
from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.outputs.contracts import Enforcement, OutputForm
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.support.knowledge import RUN, lane
from tests.unit.outputs.scenario import host_access, obligation, promises

pytestmark = pytest.mark.asyncio


def outputs_only():  # type: ignore[no-untyped-def]
    """The worker's composition where no knowledge binding is configured."""

    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, gateway=None, submissions=submissions, native=None)
    return h, contracts, submissions, toolset


async def test_a_text_promise_is_submitted_and_finalized_without_a_knowledge_binding() -> None:
    h, contracts, submissions, toolset = outputs_only()
    live = replace(h.live(), position="stage/draft", obligations=())
    registered = await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(toolset.access(live).scope),
        RUN,
        promises(
            obligation(
                "stage.report",
                OutputForm.TEXT,
                position="stage/draft",
                enforcement=Enforcement.OPTIONAL,
                media_type="text/plain",
            )
        ),
    )
    assert isinstance(registered, tuple)
    live = await toolset.begin(live)
    assert live.obligations == ("stage.report",)
    accepted = await toolset.dispatch(
        "submit_output",
        {
            "obligation": "stage.report",
            "items": [{"kind": "inline", "text": "requires_python >=3.11"}],
        },
        live,
        tool_call_id="call-1",
    )
    assert accepted["ok"], accepted
    assert accepted["result"]["status"] == "accepted"
    assert len(contracts.submissions.rows) == 1
    report = await toolset.settle(live)
    assert not report.blocked
    assert report.finalization_id is not None
    # Nothing reached a knowledge binding: no credential minted, nothing journaled.
    assert h.minter.minted == []
    assert h.journal.rows == {}


async def test_the_other_knowledge_tools_are_refused_without_a_binding() -> None:
    h, _contracts, _submissions, toolset = outputs_only()
    refused = await toolset.dispatch(
        "knowledge_read",
        {"handle": "kh:b/report/r@v1", "digest": "sha256:" + "a" * 64},
        h.live(),
        tool_call_id="call-2",
    )
    assert refused["ok"] is False
    assert refused["refusal"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert await toolset.cancel(h.live()) == []
    assert await toolset.reconcile(h.live()) == []


async def test_the_outputs_only_lane_projects_submit_output_alone() -> None:
    _h, _contracts, _submissions, toolset = outputs_only()
    support = KnowledgeLaneSupport(toolset, outputs_only=True)
    assert set(support.tools) == {"submit_output"}
    registry = support.registry_tools
    # The current and the admitted v1 schema of the one tool, with the digests a
    # knowledge-bound installation serves for it.
    assert set(registry) == set(served_output_tools())
    assert len(registry) == 2
    assert set(registry) <= set(served_knowledge_tools())
    assert {tool.name for tool in registry.values()} == {"submit_output"}


async def test_the_projected_tool_dispatches_through_the_outputs_only_toolset() -> None:
    h, contracts, submissions, toolset = outputs_only()
    live = replace(h.live(), position="stage/draft", obligations=())
    await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(toolset.access(live).scope),
        RUN,
        promises(obligation("stage.report", OutputForm.TEXT, position="stage/draft")),
    )
    support = KnowledgeLaneSupport(toolset, outputs_only=True)
    live = await toolset.begin(live)
    token = CURRENT_INVOCATION.set(live)
    try:
        message = await support.tools["submit_output"].ainvoke(
            {
                "name": "submit_output",
                "args": {
                    "obligation": "stage.report",
                    "items": [{"kind": "inline", "text": "the report"}],
                },
                "id": "call-3",
                "type": "tool_call",
            }
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    document = json.loads(message.content)
    assert document["ok"], document


async def test_the_worker_composes_output_submission_where_no_binding_is_configured() -> None:
    from typing import Any, cast

    from mission_control.bootstrap.composition import (
        compose_output_lane,
        knowledge_served_tools,
    )
    from tests.fixtures.isolated_settings import isolated_settings

    settings = isolated_settings()
    served = knowledge_served_tools(settings, application_id="ai-engineer")
    assert set(served) == set(served_output_tools())
    composed = compose_output_lane(settings, cast(Any, object()), application_id="ai-engineer")
    assert composed.toolset.gateway is None
    assert composed.support.outputs_only
    assert set(composed.registry_tools) == set(served)
