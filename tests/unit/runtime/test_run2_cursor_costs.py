import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.cursor.costs import (
    CostContext,
    CursorCostReconciler,
)
from mission_control.adapters.postgres.cursor_costs import (
    MAX_BILLING_FRAMES,
    PostgresCursorCosts,
)
from mission_control.domain.execution.cursor_costs import (
    COST_DIMENSION,
    CostReadResult,
    CostRequest,
    NativeBillingRun,
)
from tests.fixtures.lane_bindings import lane_fields


class Repository:
    def __init__(self, pending=100, attributable=True):
        self.binding = SimpleNamespace(
            request_scope="scope",
            binding_id="binding",
            lane_profile="cursor_cloud",
            model_policy=SimpleNamespace(model="requested"),
        )
        self.initial = {
            "settlement_id": "immutable",
            "usage": {"pending_external_amounts": {COST_DIMENSION: pending}},
        }
        self.value = CostContext(
            self.binding,
            "claim",
            self.initial,
            pending,
            False,
            (NativeBillingRun(agent_id="agent", run_id="native"),),
            attributable,
        )
        self.receipts = {}

    async def context(self, request):
        return self.value

    async def observation(self, request, read_no):
        return self.receipts.get(read_no)

    async def record(self, request, read_no, result):
        return self.receipts.setdefault(read_no, result)


def service(repository, reader, coordinator):
    return CursorCostReconciler(
        repository, reader, coordinator, clock=lambda: datetime(2026, 10, 14, tzinfo=UTC)
    )


@pytest.mark.asyncio
async def test_unknown_delayed_all_runs_then_settle_once_original_unchanged():
    repo = Repository()
    repo.value = replace(
        repo.value,
        native_runs=(
            NativeBillingRun(agent_id="old-agent", run_id="old-run"),
            NativeBillingRun(agent_id="new-agent", run_id="new-run"),
        ),
    )
    digest = hashlib.sha256(json.dumps(repo.initial, sort_keys=True).encode()).hexdigest()
    reader = AsyncMock(side_effect=[10, None, 10, 30])
    coordinator = SimpleNamespace(settle_pending_usage=AsyncMock())
    reconciler = service(repo, reader, coordinator)
    request = CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    first = await reconciler.observe(request, 0)
    assert first.state == "unknown" and first.observed_micros is None
    assert first.native_costs_micros == (10, None)
    result = await reconciler.observe(request, 1)
    assert result.state == "settled" and result.observed_micros == 40
    assert coordinator.settle_pending_usage.call_args.kwargs["actual_amounts"] == {
        COST_DIMENSION: 40
    }
    assert coordinator.settle_pending_usage.call_args.kwargs["release_amounts"] == {
        COST_DIMENSION: 60
    }
    repo.value = replace(repo.value, settled=True, settled_micros=40)
    await reconciler.observe(request, 1)
    assert coordinator.settle_pending_usage.await_count == 1
    assert hashlib.sha256(json.dumps(repo.initial, sort_keys=True).encode()).hexdigest() == digest


@pytest.mark.asyncio
async def test_crash_after_observation_before_journal_replays_same_native_fact():
    repo = Repository()
    reader = AsyncMock(return_value=25)
    coordinator = SimpleNamespace(
        settle_pending_usage=AsyncMock(side_effect=[RuntimeError("crash"), None])
    )
    reconciler = service(repo, reader, coordinator)
    request = CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    with pytest.raises(RuntimeError, match="crash"):
        await reconciler.observe(request, 0)
    await reconciler.observe(request, 0)
    assert reader.await_count == 1
    assert (
        coordinator.settle_pending_usage.call_args_list[0]
        == coordinator.settle_pending_usage.call_args_list[1]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cost", "attributable", "state"),
    [
        (None, True, "unknown"),
        (None, False, "unattributable"),
        (101, True, "overage"),
        (0, True, "settled"),
    ],
)
async def test_unknown_unattributable_overage_no_release(cost, attributable, state):
    repo = Repository(attributable=attributable)
    coordinator = SimpleNamespace(settle_pending_usage=AsyncMock())
    result = await service(repo, AsyncMock(return_value=cost), coordinator).observe(
        CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane"), 0
    )
    assert result.state == state
    assert coordinator.settle_pending_usage.await_count == (1 if state == "settled" else 0)
    if not attributable:
        assert result.observed_micros is None


@pytest.mark.asyncio
async def test_duplicate_native_billing_run_debited_once():
    repo = Repository()
    repo.value = replace(repo.value, native_runs=repo.value.native_runs * 2)
    reader = AsyncMock(return_value=20)
    coordinator = SimpleNamespace(settle_pending_usage=AsyncMock())
    result = await service(repo, reader, coordinator).observe(
        CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane"), 0
    )
    assert result.observed_micros == 20 and reader.await_count == 1


@pytest.mark.asyncio
async def test_scope_refusal_before_provider_read():
    repo = Repository()
    reader = AsyncMock()
    with pytest.raises(ValueError, match="scope"):
        await service(repo, reader, None).observe(
            CostRequest(request_scope="other", binding_id="binding", activity_task_queue="lane"), 0
        )
    reader.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_only_two_bounded_timers_and_unknown_liability(monkeypatch):
    from mission_control.adapters.temporal.workflows import cursor_costs

    result = CostReadResult(
        state="unknown", pending_micros=100, recorded_at="2026-10-14T00:00:00+00:00"
    )
    execute, sleep = AsyncMock(return_value=result), AsyncMock()
    monkeypatch.setattr(cursor_costs.workflow, "execute_activity", execute)
    monkeypatch.setattr(cursor_costs.workflow, "sleep", sleep)
    assert (
        await cursor_costs.CursorCostsWorkflow().run(
            CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
        )
        == result
    )
    assert execute.await_count == 3
    assert [call.args[0].total_seconds() for call in sleep.call_args_list] == [300, 900]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("known", "observed", "state", "delta"),
    [(30, 70, "settled", 40), (70, 30, "conflict", None), (30, 150, "overage", None)],
)
async def test_partial_known_cost_uses_delta_without_clamping(known, observed, state, delta):
    repo = Repository()
    repo.value = replace(repo.value, initial_recorded_micros=known)
    coordinator = SimpleNamespace(settle_pending_usage=AsyncMock())
    result = await service(repo, AsyncMock(return_value=observed), coordinator).observe(
        CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane"), 0
    )
    assert result.state == state and result.observed_micros == observed
    if delta is None:
        coordinator.settle_pending_usage.assert_not_called()
    else:
        assert coordinator.settle_pending_usage.call_args.kwargs["actual_amounts"] == {
            COST_DIMENSION: delta
        }
        assert coordinator.settle_pending_usage.call_args.kwargs["release_amounts"] == {
            COST_DIMENSION: 100 - delta
        }


@pytest.mark.asyncio
async def test_reader_exception_becomes_sanitized_unknown_then_settles():
    repo = Repository()
    reader = AsyncMock(side_effect=[RuntimeError("secret-provider-body"), 20])
    coordinator = SimpleNamespace(settle_pending_usage=AsyncMock())
    reconciler = service(repo, reader, coordinator)
    request = CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    first = await reconciler.observe(request, 0)
    assert first.state == "unknown" and first.source == "cursor.charged_cents.read_failed"
    assert "secret" not in first.model_dump_json()
    assert (await reconciler.observe(request, 1)).state == "settled"
    assert coordinator.settle_pending_usage.await_count == 1


def postgres_cost_context(frames=(), *, failure=None, lane="cursor_cloud"):
    binding = SimpleNamespace(
        binding_id="binding",
        lane_profile=lane,
        request_scope="scope",
        run_id="run",
        operation_id="operation",
        runtime_unit=SimpleNamespace(unit_key="unit"),
        semantic_attempt_key="semantic",
        **lane_fields(
            SimpleNamespace(binding_digest="digest", lane_profile=lane),
            lane_profile=lane,
            schema_id="mc.cursor_binding.v2",
        ),
    )
    settlement = SimpleNamespace(
        settlement_id="settlement", usage=SimpleNamespace(amounts={COST_DIMENSION: 10})
    )
    repository = PostgresCursorCosts(None, AsyncMock(return_value=settlement))
    repository._bindings = SimpleNamespace(get_binding_by_id=AsyncMock(return_value=binding))
    repository._journal = SimpleNamespace(
        get_claim=AsyncMock(return_value="claim"),
        get_settlement=AsyncMock(
            return_value=SimpleNamespace(
                settlement_id="settlement",
                pending_external_usage={COST_DIMENSION: 90},
                settlement_revision=1,
                usage={COST_DIMENSION: 10},
            )
        ),
    )
    repository._frames = SimpleNamespace(
        frames_for_semantic_attempt=AsyncMock(return_value=frames, side_effect=failure)
    )
    return repository


def billing_frame(execution="execution", generation=1, run="run", subordinate=None):
    return SimpleNamespace(
        harness_execution_id=execution,
        generation=generation,
        native_session_ref="agent",
        native_turn_ref=run,
        subordinate_ref=subordinate,
    )


@pytest.mark.asyncio
async def test_postgres_context_uses_bounded_exact_semantic_reader_and_unique_top_level_runs():
    repository = postgres_cost_context(
        [
            billing_frame(generation=1, run="old"),
            billing_frame(generation=2, run="new"),
            billing_frame(generation=2, run="old"),
            billing_frame(generation=2, run="child", subordinate="s"),
            billing_frame(generation=2, run=None),
        ]
    )
    context = await repository.context(
        CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    )
    repository._frames.frames_for_semantic_attempt.assert_awaited_once_with(
        "scope", "run", "unit", "semantic", "digest", "cursor_cloud", limit=MAX_BILLING_FRAMES
    )
    assert context.attributable
    assert [run.run_id for run in context.native_runs] == ["new", "old"]
    assert context.pending_micros == 90 and context.initial_recorded_micros == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "predecessor",
    [
        billing_frame(generation=1, run=None),
        billing_frame(generation=1, run="child", subordinate="s"),
        billing_frame(execution="previous", generation=2, run=None),
        SimpleNamespace(
            harness_execution_id="execution",
            generation=2,
            native_session_ref="unidentified-agent",
            native_turn_ref=None,
            subordinate_ref=None,
        ),
    ],
)
async def test_postgres_context_refuses_partial_generation_or_execution_history(predecessor):
    repository = postgres_cost_context([predecessor, billing_frame(generation=2)])
    context = await repository.context(
        CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    )
    assert not context.attributable and context.native_runs == ()
    assert context.pending_micros == 90 and not context.settled


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "historical semantic-attempt attribution is unavailable",
        "semantic-attempt provider binding drift",
        "semantic-attempt predecessor observations unavailable",
        "semantic-attempt frame bound exceeded",
    ],
)
async def test_postgres_context_reader_refusal_preserves_pending_reservation(reason):
    repository = postgres_cost_context(failure=ValueError(reason))
    context = await repository.context(
        CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    )
    assert not context.attributable and context.native_runs == ()
    assert context.pending_micros == 90 and not context.settled


@pytest.mark.asyncio
async def test_postgres_context_database_failure_is_retryable_not_permanent_unattributable():
    repository = postgres_cost_context(failure=asyncpg.PostgresConnectionError("connection lost"))
    with pytest.raises(asyncpg.PostgresConnectionError):
        await repository.context(
            CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("native_run", "attributable"), [(str(uuid4()), True), ("client-label", False)]
)
async def test_postgres_context_local_requires_native_billing_uuid(native_run, attributable):
    repository = postgres_cost_context([billing_frame(run=native_run)], lane="cursor_local")
    context = await repository.context(
        CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    )
    assert context.attributable is attributable and context.pending_micros == 90


@pytest.mark.asyncio
async def test_local_http_delayed_cost_after_cleanup_preserves_multi_generation_charge_once():
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.cost import LocalHttpBillingReader

    agent, previous_run, current_run = (str(uuid4()) for _ in range(3))
    repo = Repository(pending=50_000)
    repo.binding.lane_profile = "cursor_local"
    # Complete history has already passed the scoped repository's generation fences.
    native_runs = tuple(
        NativeBillingRun(agent_id=agent, run_id=run) for run in (previous_run, current_run)
    )
    repo.value = replace(repo.value, native_runs=native_runs)
    original = json.dumps(repo.initial, sort_keys=True)
    seen = []

    def response(request):
        assert request.method == "GET"
        run = request.url.params["runId"]
        assert run in (previous_run, current_run)
        seen.append(run)
        cost = {} if len(seen) <= 2 else {"chargedCents": 1}
        return httpx.Response(200, json={"runs": [{"id": run, "cost": cost}]})

    reader = LocalHttpBillingReader(SecretStr("fixture"), transport=httpx.MockTransport(response))
    coordinator = SimpleNamespace(settle_pending_usage=AsyncMock())

    async def read(profile, native_agent, native_run):
        assert profile == "cursor_local"
        return await reader(native_agent, native_run)

    reconciler = service(repo, read, coordinator)
    request = CostRequest(request_scope="scope", binding_id="binding", activity_task_queue="lane")
    try:
        first = await reconciler.observe(request, 0)
        assert first.state == "unknown" and first.pending_micros == 50_000
        coordinator.settle_pending_usage.assert_not_called()
        settled = await reconciler.observe(request, 1)
        assert settled.state == "settled" and settled.observed_micros == 20_000
        repo.value = replace(repo.value, settled=True, settled_micros=20_000)
        assert (await reconciler.observe(request, 1)).pending_micros == 0
        assert len(seen) == 4
        assert coordinator.settle_pending_usage.await_count == 1
        assert coordinator.settle_pending_usage.call_args.kwargs["actual_amounts"] == {
            COST_DIMENSION: 20_000
        }
        assert json.dumps(repo.initial, sort_keys=True) == original
    finally:
        await reader.aclose()
