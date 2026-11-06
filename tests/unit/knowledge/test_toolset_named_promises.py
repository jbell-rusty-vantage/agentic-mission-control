"""WI-01 gap (b): with registered promises the lane tool enters ``submit_output`` only.

The toolset pins the promise revisions at invocation start (``begin``), refuses undeclared
promises and an unbound position with typed codes, never writes a legacy selection row, and
records adopter lineage for a selected report it did not produce.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.outputs.contracts import OutputForm
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_knowledge_tools import BINDING, RUN, lane
from tests.unit.outputs.scenario import host_access, obligation, promises

pytestmark = pytest.mark.asyncio


async def test_with_registered_promises_the_lane_tool_enters_submit_output_only() -> None:
    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    live = replace(h.live(), position="stage/draft")
    access = toolset.access(live)
    registered = await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(access.scope),
        RUN,
        promises(obligation("stage.report", OutputForm.REFERENCE, position="stage/draft")),
    )
    assert isinstance(registered, tuple)
    live = await toolset.begin(live)  # invocation start pins the promise revisions
    item = {
        "kind": "handle",
        "ref": f"kh:{BINDING}/report/report-7@research-report.v2",
        "digest": "sha256:" + "a" * 64,
    }
    accepted = await toolset.dispatch(
        "submit_output", {"obligation": "stage.report", "items": [item]}, live, tool_call_id="c-1"
    )
    assert accepted["ok"], accepted
    assert accepted["result"]["revisions"][0]["deliverable_id"] == "report"
    undeclared = await toolset.dispatch(
        "submit_output", {"obligation": "report", "items": [item]}, live, tool_call_id="c-2"
    )
    assert undeclared["refusal"]["code"] == "OBLIGATION_UNDECLARED"
    unbound = await toolset.dispatch(
        "submit_output",
        {"obligation": "stage.report", "items": [item]},
        replace(live, position=None),
        tool_call_id="c-3",
    )
    assert unbound["refusal"]["code"] == "POSITION_UNBOUND"
    # One writer: only the submit_output act wrote a submission row.
    assert len(contracts.submissions.rows) == 1
    # The adopted report keeps its adopter lineage on the named path too.
    assert toolset.lineage is not None
    facts = await toolset.lineage.facts(access.scope, item["ref"])
    assert [fact.role.value for fact in facts] == ["adopter"]
