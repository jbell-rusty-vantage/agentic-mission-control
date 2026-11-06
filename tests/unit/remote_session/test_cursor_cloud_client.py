"""HL-04: `cursor_cloud` is the first client of the Remote Session Lane base.

The Cursor suites prove its behaviour unchanged; this module proves the wiring: the Cloud
Agents errors are the base's neutral errors and the harness is a `RemoteSessionLane` in the
Cursor words.
"""

from __future__ import annotations

import httpx
import pytest

from mission_control.adapters.cursor import cloud_api
from mission_control.adapters.cursor.bridge import (
    AgentBusy,
    BridgeError,
    ProviderAccessDenied,
    RunNotFound,
)
from mission_control.adapters.cursor.cloud import (
    EXPIRED_POLL_INTERVAL_S,
    EXPIRED_POLL_LIMIT,
    CursorCloudHarness,
)
from mission_control.adapters.remote_session import errors
from mission_control.adapters.remote_session.lane import (
    RECORD_POLL_INTERVAL_S,
    RECORD_POLL_LIMIT,
    RemoteSessionLane,
)


@pytest.mark.parametrize(
    ("cursor_error", "neutral"),
    [
        (cloud_api.AgentIdConflict, errors.CreateConflict),
        (cloud_api.StreamExpired, errors.StreamExpired),
        (cloud_api.AgentNotFound, errors.SessionNotFound),
        (cloud_api.InvalidLastEventId, errors.InvalidStreamCursor),
        (cloud_api.CloudCapacityLimited, errors.CapacityLimited),
    ],
)
def test_cloud_agents_errors_are_bridge_errors_and_base_errors(
    cursor_error: type[Exception], neutral: type[Exception]
) -> None:
    assert issubclass(cursor_error, BridgeError) and issubclass(cursor_error, neutral)


@pytest.mark.parametrize(
    ("status", "code", "expected", "message"),
    [
        (409, "agent_id_conflict", cloud_api.AgentIdConflict, "agent id already exists"),
        (409, "agent_busy", AgentBusy, "the agent has an active run"),
        (410, "stream_expired", cloud_api.StreamExpired, "retention window has passed"),
        (404, "run_not_found", RunNotFound, "run not found"),
        (404, "", cloud_api.AgentNotFound, "not found"),
        (400, "invalid_last_event_id", cloud_api.InvalidLastEventId, "another run"),
        (401, "", ProviderAccessDenied, "provider refused credential"),
        (403, "forbidden", ProviderAccessDenied, "provider refused access"),
    ],
)
def test_the_cloud_agents_table_keeps_the_documented_mapping(
    status: int, code: str, expected: type[Exception], message: str
) -> None:
    response = httpx.Response(status, json={"error": {"code": code}} if code else {})
    with pytest.raises(expected) as raised:
        errors.raise_for_response(
            response, "get run", cloud_api.CLOUD_AGENTS_ERRORS, fallback=BridgeError
        )
    assert type(raised.value) is expected and message in str(raised.value)


def test_a_cloud_agents_429_keeps_its_retry_after() -> None:
    response = httpx.Response(429, json={}, headers={"Retry-After": "3"})
    with pytest.raises(cloud_api.CloudCapacityLimited) as raised:
        errors.raise_for_response(response, "create run", cloud_api.CLOUD_AGENTS_ERRORS)
    assert (raised.value.native_code, raised.value.retry_after_s) == ("rate_limited", 3)


def test_the_harness_is_a_remote_session_lane_in_the_cursor_words() -> None:
    assert issubclass(CursorCloudHarness, RemoteSessionLane)
    assert CursorCloudHarness.profile == "cursor_cloud"
    assert CursorCloudHarness.names.record_source == "run_record"
    assert CursorCloudHarness.names.final_kind == "run.final"
    assert CursorCloudHarness.terminal_statuses == {"finished", "error", "cancelled", "expired"}
    assert (EXPIRED_POLL_INTERVAL_S, EXPIRED_POLL_LIMIT) == (
        RECORD_POLL_INTERVAL_S,
        RECORD_POLL_LIMIT,
    )
