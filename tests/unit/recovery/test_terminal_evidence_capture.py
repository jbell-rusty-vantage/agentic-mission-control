import json
from dataclasses import asdict

import pytest

from mission_control.application.recovery.terminal_evidence_capture import (
    RetainedTerminalCapture,
    capture_digest,
    validate_capture,
)
from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionIdentity,
    AdoptionInspectionRefused,
)

IDENTITY = AdoptionIdentity("scope", "public", "internal", "harness", 1, "agent", "run")


def captured(**changes):
    result = b"private terminal result"
    body = {
        "schema_version": "mc.terminal_lane_capture.v1",
        "identity": asdict(IDENTITY),
        "native_status": "FINISHED",
        "result_digest": capture_digest(result),
        "result_size": len(result),
        "usage": {
            "inputTokens": 456013,
            "outputTokens": 14072,
            "totalTokens": 926070,
            "cacheReadTokens": 417705,
            "cacheWriteTokens": 38280,
        },
        "cost_micros_usd": None,
        "observed_at": "2026-10-16T16:15:31+00:00",
        "native_finished_at": "2026-10-16T08:20:51.998+00:00",
        "source_evidence_digest": "sha256:" + "a" * 64,
        **changes,
    }
    manifest = json.dumps(body).encode()
    return RetainedTerminalCapture(manifest, result), capture_digest(manifest)


def test_exact_retained_bytes_and_explicit_total_are_preserved_without_invoice():
    retained, digest = captured()
    evidence = validate_capture(retained, IDENTITY, digest)
    assert evidence.usage.total_tokens == 926070 and evidence.usage.cost_micros_usd is None
    assert evidence.usage.input_tokens == 456013 and evidence.usage.cache_read_tokens == 417705
    assert evidence.result == retained.result


@pytest.mark.parametrize(
    "changes",
    [
        {"native_status": "CANCELLED"},
        {"identity": {}},
        {"result_digest": "sha256:" + "b" * 64},
        {"result_size": True},
        {"usage": {"inputTokens": 1, "outputTokens": 2}},
        {
            "usage": {
                "inputTokens": True,
                "outputTokens": 2,
                "totalTokens": 3,
                "cacheReadTokens": 0,
                "cacheWriteTokens": 0,
            }
        },
        {"cost_micros_usd": True},
        {"observed_at": "2026-10-16T16:15:31"},
        {"native_finished_at": "2026-10-17T00:00:00+00:00"},
        {"source_evidence_digest": "missing"},
        {"source_evidence_digest": "sha256:" + "z" * 64},
    ],
)
def test_unattributable_or_changed_capture_refuses(changes):
    retained, digest = captured(**changes)
    with pytest.raises(AdoptionInspectionRefused):
        validate_capture(retained, IDENTITY, digest)


def test_manifest_pin_and_duplicate_members_refuse():
    retained, _digest = captured()
    with pytest.raises(AdoptionInspectionRefused):
        validate_capture(retained, IDENTITY, "sha256:" + "f" * 64)
    duplicate = retained.manifest[:-1] + b',"native_status":"FINISHED"}'
    with pytest.raises(AdoptionInspectionRefused):
        validate_capture(
            RetainedTerminalCapture(duplicate, retained.result), IDENTITY, capture_digest(duplicate)
        )
