"""OVE-169 experiment loop E4: a Stage Graph supplier can supply a linked chain.

A chain binding names the supplier's promise (``output_key``) and the position that owns it
(``source_position``). The binding is only real when an invocation of the supplier can submit
that promise through the one ``submit_output`` act: the owning position must be a stage of the
blueprint, and that stage's invocation must declare the promise. Before the fix a Stage Graph
root output became a promise owned by ``workflow``, which no stage invocation declares, so the
producing stage's submission was refused ``OBLIGATION_UNDECLARED`` and the link never released.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.manifest_lowering import output_promises
from mission_control.domain.composition.chain import compile_chain
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.authoring.test_experiment_loop_fixtures import FIXTURES, compiled
from tests.unit.knowledge.test_knowledge_tools import RUN, lane
from tests.unit.outputs.scenario import host_access

pytestmark = pytest.mark.asyncio

E4 = FIXTURES[3]


async def test_the_e4_supplier_stage_owns_and_can_submit_the_chained_promise() -> None:
    compilation = await compiled(E4)
    assert compilation.manifest is not None
    chain = compile_chain(compilation.manifest)
    assert chain.resolution is not None, chain.blockers
    (link,) = chain.resolution.links
    (binding,) = link.bindings
    supplier = next(item for item in compilation.definitions if item.mission_key == "e4-evidence")
    blueprint = compilation.program("e4-evidence").lowered.blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    # The binding's owner is a real stage: the one the manifest names as the producer.
    assert binding.source_position == "map"
    assert binding.source_position in {stage.stage_id for stage in blueprint.stages}
    promises = output_promises(supplier)
    assert promises is not None
    owners = {item.key: item.owner_position for item in promises.obligations}
    assert binding.output_key is not None
    assert owners[binding.output_key] == binding.source_position
    assert "workflow" not in owners.values()  # no promise nobody can submit

    # That stage's invocation declares the promise and the one submission act accepts it.
    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    live = replace(h.live(), operation_id="map", position=binding.source_position)
    access = toolset.access(live)
    registered = await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(access.scope), RUN, promises
    )
    assert isinstance(registered, tuple)
    live = await toolset.begin(live)
    live = await toolset.with_declared_obligations(live)
    assert binding.output_key in live.obligations
    accepted = await toolset.dispatch(
        "submit_output",
        {
            "obligation": binding.output_key,
            "items": [{"kind": "inline", "text": "| model | quoted size | source id |"}],
        },
        live,
        tool_call_id="c-1",
    )
    assert accepted["ok"], accepted
