"""Validate a trusted retained capture; caller supplied closing facts are never used."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionIdentity,
    AdoptionInspectionRefused,
)
from mission_control.domain.execution.lanes import UsageReport

MAX_CAPTURE_BYTES = 64 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class RetainedTerminalCapture:
    manifest: bytes
    result: bytes


class TerminalCaptureReader(Protocol):
    async def load_verified(
        self, identity: AdoptionIdentity, reference: str
    ) -> RetainedTerminalCapture:
        """Resolve approved custody/provenance for this identity, never an arbitrary path.

        Implementations must verify capture-origin authority, not merely fetch any
        caller-authored JSON from an object store. This service has no fallback reader.
        """
        ...


@dataclass(frozen=True)
class ValidatedTerminalCapture:
    manifest_digest: str
    result_digest: str
    result: bytes
    usage: UsageReport
    observed_at: datetime
    native_finished_at: datetime
    source_evidence_digest: str


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AdoptionInspectionRefused("duplicate capture member")
        result[key] = value
    return result


def _counter(body: dict[str, object], snake: str, camel: str) -> int | None:
    value = body.get(snake, body.get(camel))
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _captured_usage(usage: dict[str, object]) -> UsageReport:
    """The capture contract's native token counters (`mc.terminal_lane_capture.v1`, the
    Cursor SDK token semantics it records): total includes both caches, a missing dimension
    is never zero and an explicit total is authoritative."""

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


def capture_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def validate_capture(
    retained: RetainedTerminalCapture, identity: AdoptionIdentity, expected_digest: str
) -> ValidatedTerminalCapture:
    """Only an exact FINISHED native run with explicit complete counters is supported.

    The raw provider total is authoritative; caches are never guessed or added
    to that total. Unknown dollars stay None and do not become token uncertainty.
    """
    if (
        not 0 < len(retained.manifest) <= MAX_CAPTURE_BYTES
        or not 0 < len(retained.result) <= MAX_RESULT_BYTES
    ):
        raise AdoptionInspectionRefused("terminal capture size bound")
    if capture_digest(retained.manifest) != expected_digest:
        raise AdoptionInspectionRefused("capture manifest digest differs")
    try:
        body = json.loads(retained.manifest, object_pairs_hook=_object)
        if (
            not isinstance(body, dict)
            or body.get("schema_version") != "mc.terminal_lane_capture.v1"
        ):
            raise AdoptionInspectionRefused("unsupported capture contract")
        if body.get("identity") != asdict(identity) or body.get("native_status") != "FINISHED":
            raise AdoptionInspectionRefused("capture native identity/status differs")
        result_digest = capture_digest(retained.result)
        if (
            body.get("result_digest") != result_digest
            or type(body.get("result_size")) is not int
            or body["result_size"] != len(retained.result)
        ):
            raise AdoptionInspectionRefused("captured result bytes differ")
        retained.result.decode("utf-8", errors="strict")
        usage = body.get("usage")
        if not isinstance(usage, dict) or any(
            type(usage.get(key)) is not int or not 0 <= usage[key] < 2**63
            for key in (
                "inputTokens",
                "outputTokens",
                "totalTokens",
                "cacheReadTokens",
                "cacheWriteTokens",
            )
        ):
            raise AdoptionInspectionRefused("complete explicit native token counters required")
        report = _captured_usage(usage)
        cost = body.get("cost_micros_usd")
        if cost is not None and (type(cost) is not int or not 0 <= cost < 2**63):
            raise AdoptionInspectionRefused("invalid attributable currency amount")
        report = report.model_copy(update={"cost_micros_usd": cost})
        observed_at = datetime.fromisoformat(body["observed_at"])
        finished_at = datetime.fromisoformat(body["native_finished_at"])
        if (
            observed_at.utcoffset() is None
            or finished_at.utcoffset() is None
            or finished_at > observed_at
        ):
            raise AdoptionInspectionRefused("capture timestamps are not attributable")
        source = body["source_evidence_digest"]
        if not isinstance(source, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", source) is None:
            raise AdoptionInspectionRefused("capture source provenance missing")
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise AdoptionInspectionRefused("terminal capture contract refused") from error
    return ValidatedTerminalCapture(
        expected_digest, result_digest, retained.result, report, observed_at, finished_at, source
    )
