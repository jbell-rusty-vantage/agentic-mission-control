"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_stage_named_outputs.py.
"""

from mission_control.application.programs.named_outputs import NamedStageOutputs
from mission_control.domain.outputs.contracts import Cardinality, Enforcement, OutputForm
from mission_control.domain.programs.contracts import StageCandidateIdentity, StageExecutionIdentity
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.support.unit.outputs.output_fulfillment import invocation
from tests.unit.outputs.scenario import build_stack, obligation


def identity(attempt=1, generation=1):
    return StageExecutionIdentity(
        invocation().origin.run_id,
        1,
        StageCandidateIdentity("draft", 0, "NO_MAPPED_INSTANCE", 0, 0, "execute"),
        attempt,
        generation,
    )


async def setup(*, cardinality=None):
    store = InMemoryOutputContractStore()
    current = identity()
    stack = await build_stack(
        store,
        store.submissions,
        invocation(operation_id=current.operation_id),
        obligation("draft.summary", OutputForm.TEXT, cardinality=cardinality or Cardinality()),
        obligation("draft.optional", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL),
        obligation("later.summary", OutputForm.TEXT, position="later"),
    )
    return stack, NamedStageOutputs(store, stack.outputs), current
