"""A run's estimated cost: its recorded model calls priced at the Model Catalog's list prices.

Pure and in memory: persisted-shape `usage` frames as the Deep Agents frame writer records
them (one per model call, with its model and token counts; a hook's usage event repeats the
call under the same `message_id`), the conformance Model Catalog and a catalog row with a
long-prompt tier. The estimate reaches `run inspect` through `enrich_inspection`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from mission_control.application.frames.cost import (
    CatalogUsagePrices,
    FrameRunCost,
    model_calls,
    run_cost,
)
from mission_control.application.missions.inspection import InspectionSources, enrich_inspection
from mission_control.application.resolution.registries import ModelCatalog
from mission_control.contracts.contracts import MissionInspection
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.resolution.profiles import ModelProfile
from tests.conformance.resolution.fixtures import MODELS
from tests.support.ids import SCOPE
from tests.support.provider_frames import FIXTURE_RUN, provider_frame

CHEAP = "priced-small"
TIERED = "priced-tiered"


def _profile(profile: str, model_id: str, **prices: Any) -> ModelProfile:
    row = MODELS[0].model_dump(mode="python")
    return ModelProfile.model_validate(
        row
        | {
            "profile": profile,
            "model_id": model_id,
            "cost_per_million_input": 0.10,
            "cost_per_million_output": 0.50,
            "price_tiers": (),
        }
        | prices
    )


def _prices() -> CatalogUsagePrices:
    tier = {
        "above_input_tokens": 1_000,
        "cost_per_million_input": 0.50,
        "cost_per_million_output": 2.50,
    }
    return CatalogUsagePrices(
        ModelCatalog(
            (
                _profile("small.a", CHEAP),
                # A second profile of the same model shares its price row.
                _profile("small.b", CHEAP),
                _profile("tiered", TIERED, price_tiers=(tier,)),
            )
        )
    )


def _usage(ordinal: int, message: str, model: str, tokens_in: int, tokens_out: int, **more: Any):
    return provider_frame(
        ordinal,
        FrameKind.USAGE,
        {
            "message_id": message,
            "model": model,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
            **more,
        },
    )


def test_each_model_call_is_priced_once_at_the_list_price() -> None:
    frames = [
        provider_frame(1, FrameKind.TURN_STARTED),
        # The hook's usage event and the message's own usage frame are one model call.
        _usage(2, "m-1", CHEAP, 6_569, 771, event="after_model", type="mc.usage"),
        _usage(3, "m-1", CHEAP, 6_569, 771),
        _usage(4, "m-2", CHEAP, 7_574, 144, cached_input_tokens=6_565),
        _usage(5, "m-2", CHEAP, 7_574, 144, cached_input_tokens=6_565),
        provider_frame(6, FrameKind.TURN_ENDED, {"input_tokens": 14_143, "output_tokens": 915}),
    ]

    assert len(model_calls(frames)) == 2
    cost = run_cost(frames, _prices())

    # (6569 + 7574) * 0.10 + (771 + 144) * 0.50 = 1414.3 + 457.5 micros.
    assert cost.disposition == "estimated" and cost.basis == "list_price"
    # Each call is priced exactly and the sum rounded once (1871.8 micros, not 1042 + 829).
    assert cost.estimated_micros == 1_872 and cost.estimated_usd == "0.001872"
    assert (cost.model_calls, cost.unpriced_calls) == (2, 0)
    assert (cost.input_tokens, cost.output_tokens, cost.cached_input_tokens) == (14_143, 915, 6_565)
    assert [(row.model_id, row.calls, row.estimated_micros) for row in cost.by_model] == [
        (CHEAP, 2, 1_872)
    ]
    # An estimate beside the budget account, never a charge on it.
    assert cost.budget_charged is False


def test_a_long_prompt_is_billed_whole_at_its_tier() -> None:
    prices = _prices()

    # At the threshold: base prices. Above it: the tier, for the whole request.
    assert prices.list_price_micros(TIERED, 1_000, 100) == Decimal(150)
    assert prices.list_price_micros(TIERED, 1_001, 100) == Decimal("750.5")
    assert prices.list_price_micros(CHEAP, 0, 0) == 0
    assert prices.list_price_micros("no-such-model", 10, 10) is None


def test_an_unpriced_model_is_never_counted_as_zero() -> None:
    priced = _usage(1, "m-1", CHEAP, 1_000, 100)
    unknown = _usage(2, "m-2", "vendor-model-without-a-row", 5_000, 500)

    partial = run_cost([priced, unknown], _prices())
    nothing = run_cost([unknown], _prices())
    no_calls = run_cost([provider_frame(1, FrameKind.TURN_STARTED)], _prices())

    assert partial.disposition == "partial" and partial.estimated_micros == 150
    assert (partial.model_calls, partial.unpriced_calls) == (2, 1)
    assert [row.estimated_micros for row in partial.by_model] == [150, None]
    assert nothing.disposition == "unknown" and nothing.estimated_micros is None
    assert nothing.estimated_usd is None and nothing.unpriced_calls == 1
    assert no_calls.disposition == "unknown" and no_calls.model_calls == 0


class _Frames:
    def __init__(self, frames: list[Any]) -> None:
        self.frames = frames
        self.asked: list[tuple[str, UUID, bool]] = []

    async def frames_for_run(
        self, request_scope: str, run_id: UUID, *, closing_only: bool = False, limit: int = 10_000
    ) -> tuple[Any, ...]:
        self.asked.append((request_scope, run_id, closing_only))
        return tuple(frame for frame in self.frames if frame.closing or not closing_only)


PUBLIC_RUN = "b42dd901-ab05-5085-8329-019c217811e4"


class _Runs:
    """The frame store keys a run by its own identity, not by the run id a caller names."""

    async def run_identity(self, request_scope: str, run_key: str) -> UUID | None:
        return FIXTURE_RUN if run_key == PUBLIC_RUN else None


async def test_the_reader_prices_the_runs_closing_frames_and_inspection_carries_it() -> None:
    frames = _Frames([_usage(1, "m-1", CHEAP, 1_000, 100)])
    reader = FrameRunCost(frames, _prices(), runs=_Runs())  # type: ignore[arg-type]

    cost = await reader.run_cost(SCOPE, PUBLIC_RUN)
    assert cost is not None and cost.estimated_micros == 150
    # The run is resolved as the Transcript resolves it, then its closing frames are read.
    assert frames.asked == [(SCOPE, FIXTURE_RUN, True)]
    assert await reader.run_cost(SCOPE, "not-a-run-id") is None
    assert await reader.run_cost(SCOPE, str(FIXTURE_RUN)) is None

    # The sections are assembled around whatever inspection the lifecycle service read.
    inspection = MissionInspection.model_construct(
        run_id=PUBLIC_RUN,
        version=3,
        execution_generation=1,
        lifecycle="completed",
        phase="completed",
        execution_outcome="completed",
    )
    actor = ActorContext(actor_id="reader", permissions=frozenset({"workflow_run.read"}))
    enriched = await enrich_inspection(
        inspection,
        request_scope=SCOPE,
        actor=actor,
        sources=InspectionSources(cost=reader),
        commands=(),
        mailbox=None,
    )
    without = await enrich_inspection(
        inspection,
        request_scope=SCOPE,
        actor=actor,
        sources=InspectionSources(),
        commands=(),
        mailbox=None,
    )

    assert enriched.cost is not None and enriched.cost.estimated_micros == 150
    assert enriched.cost.model_dump(mode="json")["schema_version"] == "mc.run_cost.v1"
    # A composition without a price source reports no cost (the section is left out).
    assert without.cost is None
