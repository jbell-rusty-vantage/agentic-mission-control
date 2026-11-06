"""Cursor native-run accounting: a run is a key, never a summand per frame.

This is derived usage evidence, not a budget ledger. Unknown run/dimension values
are retained separately and cannot become a settled aggregate or a free run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mission_control.application.execution.harness.native_run_usage import (
    NativeRun,
    summarize_usage,
)
from mission_control.domain.execution.lanes import UsageReport
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame


def _counter(body: Mapping[str, Any], snake: str, camel: str) -> int | None:
    value = body.get(snake, body.get(camel))
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def cursor_token_usage(usage: Mapping[str, Any]) -> UsageReport:
    """Cursor SDK token semantics, shared by run frames and exact usage reads.

    Total includes both caches; reasoning is already a subset of output.
    Missing dimensions cannot be inferred as zero. An explicit vendor total,
    including zero, is authoritative and does not require reported cache fields.
    """
    inputs = _counter(usage, "input_tokens", "inputTokens")
    outputs = _counter(usage, "output_tokens", "outputTokens")
    read = _counter(usage, "cache_read_tokens", "cacheReadTokens")
    write = _counter(usage, "cache_write_tokens", "cacheWriteTokens")
    total = _counter(usage, "total_tokens", "totalTokens")
    if inputs is None or outputs is None:
        return UsageReport(disposition="unknown", cache_read_tokens=read, cache_write_tokens=write)
    if total is None:
        if read is None or write is None:
            return UsageReport(
                disposition="unknown", cache_read_tokens=read, cache_write_tokens=write
            )
        total = inputs + outputs + read + write
    return UsageReport(
        disposition="estimated",
        input_tokens=inputs,
        output_tokens=outputs,
        total_tokens=total,
        cache_read_tokens=read,
        cache_write_tokens=write,
    )


def observed_usage(frames: Iterable[ProviderFrame]) -> dict[NativeRun, UsageReport]:
    """Choose one attributable complete token observation per native session/run."""
    reports: dict[NativeRun, UsageReport] = {}
    for frame in frames:
        if (
            frame.subordinate_ref is not None
            or frame.native_session_ref is None
            or frame.native_turn_ref is None
        ):
            continue
        key = (frame.native_session_ref, frame.native_turn_ref)
        reports.setdefault(key, UsageReport(disposition="unknown"))
        # SDK 1.0.37 usage/turn-ended events are per model turn; native_turn_ref
        # identifies the entire send/run. Without complete stable turn identities,
        # those events cannot attest the run total, even when replayed identically.
        if frame.kind != FrameKind.RUN_RESULT:
            continue
        body = frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)
        usage = body.get("usage") if isinstance(body, dict) else None
        if not isinstance(usage, dict):
            continue
        report = cursor_token_usage(usage)
        if report.disposition != "unknown":
            reports[key] = report
    return reports


class CursorNativeRunUsage:
    """The Cursor lanes' `NativeRunUsageLane` rules (both harnesses inherit it).

    A cancelled turn's usage is its runs' complete cumulative run results; the closing facts
    replace the current run's observation unless they are unknown and a run result exists; the
    lane's exact per-run usage read replaces the observation; an unknown session settles as
    unknown (no reconciliation claim is retained).
    """

    def observed_usage(self, frames: Iterable[ProviderFrame]) -> dict[NativeRun, UsageReport]:
        return observed_usage(frames)

    def cancelled_turn_usage(
        self, frames: Iterable[ProviderFrame], turn_ref: str | None
    ) -> UsageReport:
        reports = {
            key: report
            for key, report in observed_usage(frames).items()
            if turn_ref is None or key[1] == turn_ref
        }
        return summarize_usage(reports).report

    def attribute_closing_usage(
        self, reports: dict[NativeRun, UsageReport], current: NativeRun, closing: UsageReport
    ) -> None:
        if closing.disposition != "unknown" or current not in reports:
            reports[current] = closing

    def attests_native_run(self, run: NativeRun) -> bool:
        return True

    def reconcile_reported_usage(self, observed: UsageReport, reported: UsageReport) -> UsageReport:
        return reported

    def unknown_usage_reconciliation_reason(self) -> str | None:
        return None


__all__ = ["CursorNativeRunUsage", "cursor_token_usage", "observed_usage"]
