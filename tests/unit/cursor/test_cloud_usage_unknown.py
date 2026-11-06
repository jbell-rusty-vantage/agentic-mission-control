"""MP-09: unknown usage remains unknown on `cursor_cloud` (FIXTURE Cloud API).

`/usage` answers that omit this run (agent totals only, an empty body, `403
feature_unavailable`) never settle as zero tokens; cost settles only from a reported value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.domain.execution.lanes import SessionHandle, TurnHandle, UsageRequest
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import harness_fields
from tests.unit.cursor.support import heid_of, lanes_for, signals, turn

PROFILE = "cursor_cloud"


@pytest.mark.parametrize("shape", ["totals_only", "empty", "unavailable"])
async def test_usage_the_provider_does_not_report_for_this_run_stays_unknown(
    tmp_path: Path, shape: str
) -> None:
    stack = cloud_stack(tmp_path, cost=1_250_000, api_changes={"usage_shape": shape})
    lanes = lanes_for(stack)
    result = await lanes.service.turn(turn(stack, PROFILE), signals(lanes, stack, PROFILE))
    assert result.done and result.closing_facts is not None
    facts = result.closing_facts
    assert facts.usage.disposition == "unknown" and facts.usage.total_tokens == 0
    assert facts.cost_disposition == "settled", "exact-run cost is independent of unknown tokens"
    assert facts.usage.cost_micros_usd == 1_250_000
    assert result.usage_estimate is not None and result.usage_estimate.disposition == "unknown"


async def test_reported_usage_settles_and_the_agent_total_is_never_attributed_to_a_run(
    tmp_path: Path,
) -> None:
    stack = cloud_stack(tmp_path, cost=1_250_000)
    lanes = lanes_for(stack)
    result = await lanes.service.turn(turn(stack, PROFILE), signals(lanes, stack, PROFILE))
    assert result.done and result.closing_facts is not None
    assert result.closing_facts.usage.disposition == "settled"
    assert result.closing_facts.usage.total_tokens == 2780
    assert result.closing_facts.cost_disposition == "settled"
    heid = heid_of(stack, PROFILE)
    agent_id = next(iter(stack.api.agents))
    stack.harness.stage(heid, stack.operation)
    session = SessionHandle(
        lane_profile=PROFILE, harness_execution_id=heid, generation=1, native_session_ref=agent_id
    )
    fields = harness_fields(stack.operation, heid, PROFILE)
    stack.api.usage_shape = "totals_only"
    for_run = await stack.harness.usage(
        UsageRequest(
            **fields,
            session=session,
            turn=TurnHandle(session=session, turn_no=1, native_turn_ref=stack.api.run_id),
        )
    )
    assert for_run.disposition == "unknown"
    for_agent = await stack.harness.usage(UsageRequest(**fields, session=session, turn=None))
    assert for_agent.disposition == "settled" and for_agent.total_tokens == 2780


@pytest.mark.parametrize(
    ("shape", "expected", "disposition"),
    [("cache", 39, "settled"), ("missing", 0, "unknown"), ("zero", 0, "settled")],
)
async def test_exact_cloud_usage_uses_cursor_cache_total_policy(shape, expected, disposition):
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.cloud import CursorCloudHarness
    from mission_control.adapters.cursor.cloud_api import CloudAgentsClient
    from tests.fixtures.lane_turns import cursor_operation

    tokens = {"inputTokens": 10, "outputTokens": 5}
    if shape == "cache":
        tokens.update(cacheReadTokens=20, cacheWriteTokens=4, reasoningTokens=2)
    if shape == "zero":
        tokens["totalTokens"] = 0

    def respond(request):
        assert request.method == "GET" and request.url.params["runId"] == "run"
        return httpx.Response(200, json={"runs": [{"id": "run", "usage": tokens}]})

    client = CloudAgentsClient(SecretStr("fixture-only"), transport=httpx.MockTransport(respond))

    async def cost_reader(agent, run):
        assert (agent, run) == ("agent", "run")
        return 19

    harness = CursorCloudHarness(
        client=client, publisher=None, projections=None, artifacts=None, cost_reader=cost_reader
    )
    operation = cursor_operation(PROFILE)
    from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity

    heid = str(LaneExecutionIdentity.of(operation, PROFILE, 1).harness_execution_id)
    harness.stage(heid, operation)
    session = SessionHandle(
        lane_profile=PROFILE, harness_execution_id=heid, generation=1, native_session_ref="agent"
    )
    try:
        report = await harness.usage(
            UsageRequest(
                **harness_fields(operation, heid, PROFILE),
                session=session,
                turn=TurnHandle(session=session, turn_no=1, native_turn_ref="run"),
            )
        )
        assert (report.total_tokens, report.disposition) == (expected, disposition)
        assert report.cost_micros_usd == 19
    finally:
        await client.aclose()
