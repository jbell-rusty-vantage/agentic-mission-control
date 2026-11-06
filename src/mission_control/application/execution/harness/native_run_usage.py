"""Native-run usage accounting: a run is a key, never a summand per frame.

Lane-neutral aggregation over the per-native-run usage reports a `NativeRunUsageLane`
observes in its provider frames (moved from the Cursor usage module by OC-R3; the Codex
lane uses it too). This is derived usage evidence, not a budget ledger. Unknown run or
dimension values are retained separately and cannot become a settled aggregate or a free
run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mission_control.domain.execution.lanes import UsageReport

# (native session ref, native run ref): one provider run of a session.
NativeRun = tuple[str, str]


@dataclass(frozen=True)
class NativeRunUsageSummary:
    report: UsageReport
    cost_disposition: str
    per_run: Mapping[NativeRun, UsageReport]
    unknown_runs: tuple[NativeRun, ...]
    partial_token_totals: Mapping[str, int]


def summarize_usage(reports: Mapping[NativeRun, UsageReport]) -> NativeRunUsageSummary:
    """Complete aggregate only; keep partial known totals as explicit derived evidence."""
    values = tuple(reports.values())
    unknown = tuple(
        sorted(key for key, report in reports.items() if report.disposition == "unknown")
    )
    totals = {
        field: sum(getattr(value, field) for value in values if value.disposition != "unknown")
        for field in ("input_tokens", "output_tokens", "total_tokens")
    }
    known_cost = bool(values) and all(value.cost_micros_usd is not None for value in values)
    cost = sum(value.cost_micros_usd or 0 for value in values) if known_cost else None
    caches = {
        field: sum(getattr(value, field) for value in values)
        if values and all(getattr(value, field) is not None for value in values)
        else None
        for field in ("cache_read_tokens", "cache_write_tokens")
    }
    disposition = (
        "unknown"
        if not values or unknown
        else "settled"
        if all(value.disposition == "settled" for value in values)
        else "estimated"
    )
    report = UsageReport(
        disposition=disposition,
        **(totals if disposition != "unknown" else {}),
        cost_micros_usd=cost,
        **caches,
    )
    return NativeRunUsageSummary(
        report,
        "settled"
        if known_cost
        else "estimated"
        if any(value.disposition != "unknown" for value in values)
        else "unknown",
        dict(reports),
        unknown,
        totals,
    )
