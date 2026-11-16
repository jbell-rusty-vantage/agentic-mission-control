"""A run's estimated cost: its recorded model calls priced at the Model Catalog's list prices.

Where usage becomes cost. A lane's frame writer records one closing `usage` frame per model
call with the model and the provider-reported token counts; nothing charges those tokens to
the run budget's currency dimensions. This module reads the frames a run already holds and
prices each call with the `deployments/<app>/models.toml` row of its model (`UsagePrices`,
composed over the Model Catalog), so a finished run reports what it cost without a provider
call and without a new record. It prices at read time: an estimate at today's list prices,
never a settled charge, and it does not touch the budget account.

A model call recorded by more than one frame (a hook's usage event and the message's own usage
frame carry the same `message_id`) is counted once. A call whose model the catalog does not
price is reported as unpriced, never as zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol
from uuid import UUID

from mission_control.application.frames.sink import FrameReader
from mission_control.application.resolution.registries import ModelCatalog
from mission_control.contracts.contracts import ModelCostView, RunCostView
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame

MICROS = Decimal(1_000_000)


class UsagePrices(Protocol):
    """List prices by exact model id."""

    def list_price_micros(
        self, model_id: str, input_tokens: int, output_tokens: int
    ) -> Decimal | None:
        """One model call's list-price cost in USD micros, exact (`None`: the model is not
        priced). Callers sum the calls before they round."""
        ...


class RunCostReader(Protocol):
    """A run's estimated cost under one request scope (`None`: the run id names no run)."""

    async def run_cost(self, request_scope: str, run_id: str) -> RunCostView | None: ...


class CatalogUsagePrices:
    """`UsagePrices` over the Model Catalog: a model's row prices every call of that model id;
    a request whose prompt exceeds a row's long-prompt tier is billed whole at that tier, as
    the vendors price it. Profiles that share a model id share its prices (the first row in
    profile order answers)."""

    def __init__(self, models: ModelCatalog) -> None:
        self._rows: dict[str, tuple[float, float, tuple[tuple[int, float, float], ...]]] = {}
        for name in models.profiles():
            row = models.get(name)
            self._rows.setdefault(
                row.model_id,
                (
                    row.cost_per_million_input,
                    row.cost_per_million_output,
                    tuple(
                        (
                            tier.above_input_tokens,
                            tier.cost_per_million_input,
                            tier.cost_per_million_output,
                        )
                        for tier in row.price_tiers
                    ),
                ),
            )

    def list_price_micros(
        self, model_id: str, input_tokens: int, output_tokens: int
    ) -> Decimal | None:
        row = self._rows.get(model_id)
        if row is None:
            return None
        rate_in, rate_out, tiers = row
        for above, tier_in, tier_out in sorted(tiers):
            if input_tokens > above:
                rate_in, rate_out = tier_in, tier_out
        # USD per million tokens times tokens is USD micros.
        return Decimal(str(rate_in)) * input_tokens + Decimal(str(rate_out)) * output_tokens


def _whole(micros: Decimal) -> int:
    return int(micros.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _count(body: Mapping[str, Any], name: str) -> int:
    value = body.get(name)
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def model_calls(frames: Sequence[ProviderFrame]) -> tuple[Mapping[str, Any], ...]:
    """The distinct model calls a run's `usage` frames record: the bodies that name a model,
    one per `message_id` (the first frame of a call answers), in arrival order."""

    calls: dict[str, Mapping[str, Any]] = {}
    for frame in sorted(frames, key=lambda item: item.arrival_ordinal):
        if frame.kind is not FrameKind.USAGE:
            continue
        body = frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)
        if not isinstance(body.get("model"), str) or not body["model"]:
            continue
        calls.setdefault(str(body.get("message_id") or frame.frame_id), body)
    return tuple(calls.values())


def run_cost(frames: Sequence[ProviderFrame], prices: UsagePrices) -> RunCostView:
    """The run's model calls priced at list prices (see `RunCostView`)."""

    by_model: dict[str, dict[str, int]] = {}
    exact: dict[str, Decimal] = {}
    unpriced: set[str] = set()
    calls = model_calls(frames)
    cached = 0
    for body in calls:
        model = str(body["model"])
        tokens_in, tokens_out = _count(body, "input_tokens"), _count(body, "output_tokens")
        cached += _count(body, "cached_input_tokens")
        row = by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0})
        row["calls"] += 1
        row["input"] += tokens_in
        row["output"] += tokens_out
        micros = prices.list_price_micros(model, tokens_in, tokens_out)
        if micros is None:
            unpriced.add(model)
        else:
            exact[model] = exact.get(model, Decimal(0)) + micros
    # Each call is priced exactly and the sums are rounded once, to whole micros.
    priced = [amount for model, amount in exact.items() if model not in unpriced]
    total = _whole(sum(priced, Decimal(0))) if priced else None
    unpriced_calls = sum(row["calls"] for model, row in by_model.items() if model in unpriced)
    return RunCostView(
        disposition="unknown" if total is None else "partial" if unpriced else "estimated",
        estimated_micros=total,
        estimated_usd=None if total is None else format((Decimal(total) / MICROS).normalize(), "f"),
        model_calls=len(calls),
        unpriced_calls=unpriced_calls,
        input_tokens=sum(row["input"] for row in by_model.values()),
        output_tokens=sum(row["output"] for row in by_model.values()),
        cached_input_tokens=cached,
        by_model=tuple(
            ModelCostView(
                model_id=model,
                calls=row["calls"],
                input_tokens=row["input"],
                output_tokens=row["output"],
                estimated_micros=None if model in unpriced else _whole(exact[model]),
            )
            for model, row in sorted(by_model.items())
        ),
    )


class RunIdentities(Protocol):
    """The frame store's identity of a run, from the run id a caller names (the Transcript
    resolves a run the same way)."""

    async def run_identity(self, request_scope: str, run_key: str) -> UUID | None: ...


class FrameRunCost:
    """`RunCostReader` over the persisted frames of a run (closing frames only)."""

    def __init__(self, frames: FrameReader, prices: UsagePrices, *, runs: RunIdentities) -> None:
        self._frames = frames
        self._prices = prices
        self._runs = runs

    async def run_cost(self, request_scope: str, run_id: str) -> RunCostView | None:
        run = await self._runs.run_identity(request_scope, run_id)
        if run is None:
            return None
        frames = await self._frames.frames_for_run(request_scope, run, closing_only=True)
        return run_cost(frames, self._prices)


__all__ = [
    "CatalogUsagePrices",
    "FrameRunCost",
    "RunCostReader",
    "RunIdentities",
    "UsagePrices",
    "model_calls",
    "run_cost",
]
