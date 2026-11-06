"""HL-04: the typed HTTP error set and per-provider error tables of the Remote Session Lane base."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from mission_control.adapters.remote_session.errors import (
    STANDARD_ERROR_RULES,
    AccessDenied,
    CapacityLimited,
    CreateConflict,
    ErrorRule,
    FeatureUnavailable,
    RemoteSessionError,
    SessionBusy,
    SessionNotFound,
    StreamExpired,
    capacity_limited,
    capacity_signal,
    error_code,
    raise_for_response,
    retry_after_seconds,
)
from mission_control.application.execution.harness.dispatch import ProviderCapacityLimited

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
PROVIDER_RULES = (
    ErrorRule(409, CreateConflict, "the session id already exists", code="id_conflict"),
    ErrorRule(409, SessionBusy, "the session has an active turn", code="session_busy"),
    ErrorRule(403, FeatureUnavailable, "feature unavailable", code="feature_unavailable"),
    *STANDARD_ERROR_RULES,
)


def _response(
    status: int, body: Any = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def _raised(response: httpx.Response, **kwargs: Any) -> Exception:
    with pytest.raises(Exception) as caught:
        raise_for_response(response, "send turn", PROVIDER_RULES, **kwargs)
    return caught.value


def test_a_success_raises_nothing() -> None:
    raise_for_response(_response(200, {}), "send turn", PROVIDER_RULES)


def test_the_provider_error_code_is_read_from_either_documented_shape() -> None:
    assert error_code(_response(409, {"error": {"code": "session_busy"}})) == "session_busy"
    assert error_code(_response(409, {"code": "id_conflict"})) == "id_conflict"
    assert error_code(httpx.Response(500, text="<html>")) == ""
    assert error_code(_response(500, ["not", "a", "mapping"])) == ""


def test_the_first_matching_rule_names_the_error_by_status_and_code() -> None:
    conflict = _raised(_response(409, {"error": {"code": "id_conflict"}}))
    assert type(conflict) is CreateConflict
    assert str(conflict) == "send turn: the session id already exists"
    assert type(_raised(_response(409, {"code": "session_busy"}))) is SessionBusy
    assert type(_raised(_response(403, {"code": "feature_unavailable"}))) is FeatureUnavailable
    assert type(_raised(_response(404, {}))) is SessionNotFound
    assert type(_raised(_response(410, {}))) is StreamExpired


def test_an_unmatched_status_is_the_fallback_with_status_and_code_only() -> None:
    other = _raised(_response(409, {"error": {"code": "something_new", "message": "secret"}}))
    assert type(other) is RemoteSessionError
    assert str(other) == "send turn: HTTP 409 something_new"
    assert "secret" not in str(other)

    class ProviderError(RuntimeError):
        pass

    assert type(_raised(_response(500, {}), fallback=ProviderError)) is ProviderError


def test_a_refused_credential_is_non_retryable() -> None:
    for status in (401, 403):
        denied = _raised(_response(status, {"error": {"code": "unauthorized"}}))
        assert type(denied) is AccessDenied
        # `lane.turn` rejects a ValueError non-retryable instead of retrying the credential.
        assert isinstance(denied, ValueError) and isinstance(denied, RemoteSessionError)


def test_a_429_carries_the_stated_reset_and_the_providers_code() -> None:
    limited = _raised(_response(429, {"code": "too_many"}, {"Retry-After": "7"}))
    assert isinstance(limited, CapacityLimited)
    assert (limited.native_code, limited.retry_after_s) == ("too_many", 7)
    assert str(limited) == "send turn: provider capacity limited (too_many)"
    unstated = _raised(_response(429, {}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))
    assert isinstance(unstated, CapacityLimited)
    assert (unstated.native_code, unstated.retry_after_s) == ("rate_limited", None)


def test_retry_after_is_whole_seconds_only() -> None:
    assert retry_after_seconds(_response(429, headers={"Retry-After": " 12 "})) == 12
    assert retry_after_seconds(_response(429, headers={"Retry-After": "1.5"})) is None
    assert retry_after_seconds(_response(429)) is None


def test_the_capacity_signal_is_a_rate_limit_for_the_lane_profile() -> None:
    error = CapacityLimited("create", native_code="x" * 200, retry_after_s=30)
    signal = capacity_signal(error, lane_profile="cursor_cloud", now=NOW)
    assert signal.lane_profile == "cursor_cloud" and signal.kind == "rate_limited"
    assert signal.resets_at == NOW + timedelta(seconds=30)
    assert signal.source == "cursor_cloud.http_429"
    assert signal.native_code == "x" * 128
    unstated = capacity_signal(
        CapacityLimited("create", native_code="", retry_after_s=None),
        lane_profile="codex_cloud",
        now=NOW,
    )
    assert unstated.resets_at is None and unstated.native_code is None
    raised = capacity_limited(error, lane_profile="cursor_cloud", now=NOW)
    assert isinstance(raised, ProviderCapacityLimited) and raised.signal == signal
