"""WI-02 (ADR-0061): a real Deep Agent without knowledge tools receives its sealed plan.

Runs an actual ``create_deep_agent`` graph on the text-only ``StateBackend`` with a scripted
local model (no provider calls). The invocation carries a ``transfer`` selection (typed literal
placed as a file and an inline brief); the lane seals the plan through the one materializer,
writes the files to the backend the agent reads, reads them back through it, and appends the
prompt section to the user message. The agent's own ``read_file`` sees exactly the plan's bytes.
A selection with no composed materializer fails closed before any model call.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from tests.fixtures.checkpoint_lineage import activity_attempt
from tests.support.deep_agents import registry
from tests.support.integration.deep_agents.report_source_context import FULL_CONTEXT_READER
from tests.support.integration.deep_agents.wi02_transfer_plan_lane import (
    PLAN_READER,
    SOURCES,
    _invocation,
    _materializer,
    _selection,
)

from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
from mission_control.adapters.deep_agents.materializer import ExactDeepAgentMaterializer
from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.domain.context.transfer import (
    INDEX_PATH,
    InputSource,
    TransferInput,
)


@pytest.mark.asyncio
async def test_an_agent_without_knowledge_tools_reads_exactly_its_sealed_plan() -> None:
    invocation, binding, bundle = _invocation()
    assert invocation.binding.transfer == _selection()
    tool_names = {tool.tool_name for tool in binding.tools}
    assert not tool_names & {"knowledge_read", "submit_output"}
    materializer, store = _materializer()
    sources_bytes = json.dumps(SOURCES, sort_keys=True, separators=(",", ":")).encode()
    digest = "sha256:" + hashlib.sha256(sources_bytes).hexdigest()
    sources_path = f"/inputs/sources/{digest[7:23]}/sources.json"
    PLAN_READER.paths = [sources_path, INDEX_PATH]
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, PLAN_READER.model())),
        transfer=materializer,
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(invocation.binding, activity_attempt(1), dispatching=True)
    result = await adapter.execute(invocation.model_copy(update={"checkpoint_plan": plan}), {})

    assert result.output_text == "plan observed"
    (sealed,) = store.plans.values()
    file_text, index_text = PLAN_READER.observed
    assert '"pmid"' in file_text and '"41"' in file_text
    assert sealed.plan_id in index_text
    # The inline member is in the user prompt, fenced as data, with its exact digest.
    brief = next(m for m in sealed.exact_sources if m.binding == "brief")
    assert "Summarize study 41 only." in PLAN_READER.first_prompt
    assert brief.digest in PLAN_READER.first_prompt
    assert "not instructions" in PLAN_READER.first_prompt
    (receipt,) = await store.receipts(sealed.receiver.scope, sealed.plan_id)
    assert receipt.result == "ready" and receipt.realized_backend == "deep_agents:state"
    probes = {d.member_key: d.probe for d in receipt.delivered}
    assert probes == {"sources/value": "state_files_read", "brief/value": "prompt"}


@pytest.mark.asyncio
async def test_an_agent_reads_every_byte_of_a_large_delivered_file_across_pages() -> None:
    """A multi-page plan file (non-ASCII, one line longer than a `read_file` line) is read
    whole in 150-line pages; the lines the agent saw are exactly the delivered bytes."""

    expected = (
        "".join(f"record {n:04d}: étude {n} — {'x' * (n % 11)}\n" for n in range(1, 420))
        + "long "
        + "y" * 4_500
        + "\n"
        + "last line\n"
    ).encode()
    invocation, binding, bundle = _invocation()
    selection = _selection().model_copy(
        update={
            "inputs": (
                TransferInput(
                    name="foundation",
                    source=InputSource.literal("text/plain@1", expected.decode()),
                    purpose="dependent_input",
                    placement="file",
                ),
            )
        }
    )
    invocation = invocation.model_copy(
        update={"binding": invocation.binding.model_copy(update={"transfer": selection})}
    )
    materializer, store = _materializer()
    digest = "sha256:" + hashlib.sha256(expected).hexdigest()
    FULL_CONTEXT_READER.expected = expected
    FULL_CONTEXT_READER.observed = {}
    FULL_CONTEXT_READER.file_path = f"/inputs/foundation/{digest[7:23]}/foundation.txt"
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, FULL_CONTEXT_READER.model())),
        transfer=materializer,
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(invocation.binding, activity_attempt(1), dispatching=True)
    result = await adapter.execute(invocation.model_copy(update={"checkpoint_plan": plan}), {})

    assert result.output_text == "entire context read"
    line_count = len(expected.decode().splitlines())
    assert line_count > 2 * 150, "the file must span several read_file pages"
    assert sorted(FULL_CONTEXT_READER.observed) == list(range(1, line_count + 1))
    observed = (
        "\n".join(FULL_CONTEXT_READER.observed[i] for i in sorted(FULL_CONTEXT_READER.observed))
        + "\n"
    )
    assert observed.encode() == expected
    (sealed,) = store.plans.values()
    (receipt,) = await store.receipts(sealed.receiver.scope, sealed.plan_id)
    assert receipt.result == "ready"
    assert receipt.realized_backend == "deep_agents:state"
    assert {item.probe for item in receipt.delivered} == {"state_files_read"}


@pytest.mark.asyncio
async def test_a_selection_without_a_composed_materializer_fails_closed() -> None:
    invocation, binding, bundle = _invocation()
    PLAN_READER.observed = []
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, PLAN_READER.model()))
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(invocation.binding, activity_attempt(1), dispatching=True)
    with pytest.raises(ContextDeliveryBlocked, match="context_transfer_unwired"):
        await adapter.execute(invocation.model_copy(update={"checkpoint_plan": plan}), {})
    assert PLAN_READER.observed == []
