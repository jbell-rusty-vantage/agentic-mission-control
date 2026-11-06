"""Attributed Codex turn snapshots; raw per-call counters are not turn totals."""

from __future__ import annotations

from collections.abc import Iterable

from mission_control.application.execution.harness.controls import usage_from_frames
from mission_control.application.execution.harness.native_run_usage import NativeRun
from mission_control.domain.execution.lanes import UsageReport
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import FrameKind, LaneProfile, ProviderFrame

ATTRIBUTION_SCHEMA = "mc.codex.turn_usage.v1"
_REQUIRED = ("inputTokens", "outputTokens", "totalTokens")
_OPTIONAL = ("cachedInputTokens", "cacheWriteInputTokens")


def _counter(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    names = (*_REQUIRED, *(name for name in _OPTIONAL if name in value))
    if any(type(value.get(name)) is not int or value[name] < 0 for name in names):
        return None
    if value["totalTokens"] != value["inputTokens"] + value["outputTokens"]:
        return None
    return {name: value[name] for name in names}


def observed_usage(frames: Iterable[ProviderFrame]) -> dict[NativeRun, UsageReport]:
    """One snapshot per native turn, including interrupted and predecessor turns.

    An unaccounted subordinate remains unknown. Raw notifications and terminal
    frames establish turn existence but cannot manufacture a cumulative baseline.
    """
    turns: set[NativeRun] = set()
    closed: set[NativeRun] = set()
    invalid: set[NativeRun] = set()
    baselines: dict[NativeRun, dict[str, int]] = {}
    current: dict[NativeRun, dict[str, int]] = {}
    seen: dict[NativeRun, list[dict[str, int]]] = {}
    for frame in frames:
        if frame.lane_profile != LaneProfile.CODEX or not frame.native_turn_ref:
            continue
        session = frame.subordinate_ref or frame.native_session_ref
        if not session:
            continue
        key = (session, frame.native_turn_ref)
        turns.add(key)
        if frame.kind in {FrameKind.TURN_ENDED, FrameKind.RUN_RESULT}:
            closed.add(key)
        if frame.kind != FrameKind.USAGE:
            continue
        body = frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)
        provenance = body.get("codex_usage_provenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("schema_version") != ATTRIBUTION_SCHEMA
        ):
            continue
        if (
            body.get("turnId") != frame.native_turn_ref
            or body.get("threadId") != frame.native_session_ref
            or provenance.get("root_thread_id") != frame.native_session_ref
            or frame.subordinate_ref is not None
        ):
            invalid.add(key)
            continue
        invalidated = provenance.get("invalidates_turn_ref")
        if isinstance(invalidated, str) and invalidated:
            invalid.add((session, invalidated))
        latest = _counter(provenance.get("current_total"))
        if provenance.get("monotonic") is not True or latest is None:
            invalid.add(key)
            continue
        baseline_value = provenance.get("baseline_total")
        if baseline_value is not None:
            baseline = _counter(baseline_value)
            if baseline is None or provenance.get("baseline_source") not in {
                "fresh_thread",
                "previous_turn_total",
            }:
                invalid.add(key)
                continue
            if provenance.get("baseline_source") == "fresh_thread" and any(baseline.values()):
                invalid.add(key)
                continue
            if key in baselines and baselines[key] != baseline:
                invalid.add(key)
                continue
            baselines[key] = baseline
        # Exact repeated snapshots are replay, not another model call. A new
        # decreasing counter is unresolved even if a later replay looks valid.
        if latest not in seen.setdefault(key, []):
            prior = current.get(key)
            if prior is not None and any(
                latest[name] < prior[name] for name in latest.keys() & prior.keys()
            ):
                invalid.add(key)
            current[key] = latest
            seen[key].append(latest)
    # An incomplete persisted tail is evidence of consumption, not a complete
    # settlement. It must be reconciled durably before the operation can settle.
    reports = {key: UsageReport(disposition="unknown") for key in turns}
    for key in turns - invalid:
        baseline, latest = baselines.get(key), current.get(key)
        if key not in closed or baseline is None or latest is None:
            continue
        common = baseline.keys() & latest.keys()
        if any(latest[name] < baseline[name] for name in common):
            continue
        delta = {name: latest[name] - baseline[name] for name in common}
        if delta["totalTokens"] <= 0:
            continue
        reports[key] = UsageReport(
            disposition="estimated",
            input_tokens=delta["inputTokens"],
            output_tokens=delta["outputTokens"],
            total_tokens=delta["totalTokens"],
            cache_read_tokens=delta.get("cachedInputTokens"),
            cache_write_tokens=delta.get("cacheWriteInputTokens"),
        )
    return reports


_TOTALS = ("input_tokens", "output_tokens", "total_tokens")
# Codex provider child threads; the root thread's usage read cannot attest them.
_CHILD_THREAD_PREFIX = "codex:thread:"


class CodexNativeRunUsage:
    """The `codex` lane's `NativeRunUsageLane` rules (the harness inherits it).

    A cancelled turn's usage is the frames' turn usage; the complete durable tail of turn
    snapshots is the authority, so closing facts or a usage read that contradict it make the
    run unknown, and a natively completed session whose usage stays unknown keeps its claim for
    reconciliation.
    """

    def observed_usage(self, frames: Iterable[ProviderFrame]) -> dict[NativeRun, UsageReport]:
        return observed_usage(frames)

    def cancelled_turn_usage(
        self, frames: Iterable[ProviderFrame], turn_ref: str | None
    ) -> UsageReport:
        return usage_from_frames(frames, turn_ref)

    def attribute_closing_usage(
        self, reports: dict[NativeRun, UsageReport], current: NativeRun, closing: UsageReport
    ) -> None:
        reports.setdefault(current, UsageReport(disposition="unknown"))
        if closing.disposition != "unknown" and any(
            getattr(closing, name) != getattr(reports[current], name) for name in _TOTALS
        ):
            reports[current] = UsageReport(disposition="unknown")

    def attests_native_run(self, run: NativeRun) -> bool:
        return not run[0].startswith(_CHILD_THREAD_PREFIX)

    def reconcile_reported_usage(self, observed: UsageReport, reported: UsageReport) -> UsageReport:
        # The complete durable tail is the authority. A newer or smaller live estimate cannot
        # replace missing, regressed or contradictory provenance and silently release its claim.
        if reported.disposition != "unknown" and any(
            getattr(reported, name) != getattr(observed, name) for name in _TOTALS
        ):
            return UsageReport(disposition="unknown")
        return observed

    def unknown_usage_reconciliation_reason(self) -> str | None:
        # Native completion does not erase unknown consumption.
        return "codex_usage_requires_reconciliation"


__all__ = ["ATTRIBUTION_SCHEMA", "CodexNativeRunUsage", "observed_usage"]
