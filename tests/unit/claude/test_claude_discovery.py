"""MO-34: the `claude_agent_sdk` Discovery Proof through `lane.turn` (FIXTURE client).

The lane emits what `system/init` reports loaded as a `materialization.discovered` frame right
after the init frame; `lane.turn` hands it to the preparation service, which compares it with
the expectation the prepare recorded. An init that names every placed skill, subagent and
connected MCP server raises the environment to `discovered`; the stock fixture init, which names
none of them, proves nothing (the init frame alone never did). The recorded CLI init is proven
in `tests/unit/agentic_components/test_adapter_discovery.py`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from mission_control.application.environments import (
    EnvironmentPreparationService,
    InMemoryEnvironmentPreparationRepository,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.environment_preparation import (
    EnvironmentPreparation,
    ReadinessLevel,
    preparation_id,
)
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from tests.fixtures.lane_turns import RecordingSignals, lane_stack
from tests.unit.claude.fixtures import PROFILE, ClaudeStack, claude_stack

SEGMENT = {"heartbeat_timeout_s": 60, "max_frames": 200}
# What the stack's projection rows place (skill_row, tavily_row, verifier_row).
LOADED = {
    "skills": ["agent-browser", "repo-notes"],
    "agents": ["general-purpose", "verifier"],
    "mcp_servers": [{"name": "mc-tavily", "status": "connected"}],
}


async def _turn(stack: ClaudeStack) -> EnvironmentPreparation | None:
    repository = InMemoryEnvironmentPreparationRepository()
    lanes = lane_stack(
        stack.harness,
        frames=stack.frames,
        operation=stack.operation,
        preparations=EnvironmentPreparationService(repository),
    )
    identity = LaneExecutionIdentity.of(stack.operation, PROFILE, 1)
    request = LaneTurnRequest.model_validate(
        {"operation": stack.operation, "lane_profile": PROFILE, "generation": 1, "segment": SEGMENT}
    )
    result = await lanes.service.turn(
        request, RecordingSignals(stack.frames, identity.harness_execution_id)
    )
    assert result.done
    return await repository.get(
        identity.request_scope,
        preparation_id(identity.request_scope, identity.harness_execution_id, 1),
    )


def _init_reports(stack: ClaudeStack, loaded: dict[str, Any]) -> None:
    script = stack.factory.script
    script.records[:] = [
        dataclasses.replace(record, message={**record.message, **loaded})
        if record.message is not None and record.message.get("subtype") == "init"
        else record
        for record in script.records
    ]


async def test_an_init_that_names_what_was_placed_discovers_the_environment(
    tmp_path: Path,
) -> None:
    stack = claude_stack(tmp_path)
    _init_reports(stack, LOADED)

    stored = await _turn(stack)

    assert stored is not None and stored.discovery is not None
    assert stored.discovery.mechanism == "session_init"
    assert {(item.kind, item.name) for item in stored.discovery.items} >= {
        ("skill", "agent-browser"),
        ("mcp_server", "mc-tavily"),
    }
    mark = stored.mark(ReadinessLevel.DISCOVERED)
    assert mark is not None and mark.evidence_ref.startswith("frame:claude:")


async def test_an_init_that_names_none_of_it_proves_nothing(tmp_path: Path) -> None:
    stored = await _turn(claude_stack(tmp_path))

    assert stored is not None and stored.mark(ReadinessLevel.DISCOVERED) is None
