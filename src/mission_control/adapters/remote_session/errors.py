"""The typed HTTP error set of provider session APIs (ADR-0052; SPEC-06 section 3).

A Remote Session Lane never branches on raw status codes. Each provider adapter declares an
ordered table of `ErrorRule`s (status, optional provider error code, the exception to raise)
and `raise_for_response` turns a failed response into the first matching typed error, or the
table's fallback. The neutral classes carry the meaning the lane base and Mission Control act
on:

- `CapacityLimited` (`429`, `Retry-After` in seconds): a capacity condition stated before any
  work was accepted. `capacity_signal` makes it the MP-05 `ProviderLimitSignal` a lane raises
  as `ProviderCapacityLimited`, so the workflow waits on a Temporal timer; it is never retried
  inside the lane;
- `SessionBusy` (`409`, the session's own active turn): `wait_then_send` at the boundary
  (ADR-0030), never a send retry; `CreateConflict` (`409`, a client-chosen create id already
  exists): reattach to it; `NotCancellable` (`409`): the turn is already terminal;
- `AccessDenied` (`401`/`403`): non-retryable. It is also a `ValueError`, so `lane.turn`
  rejects the activity instead of retrying a credential the provider refused;
- `SessionNotFound` (`404`), `StreamExpired` (`410`, the stream retention passed: reconcile
  from the turn record), `InvalidStreamCursor` (`400`, the resume cursor belongs to another
  turn: replay from the start), `FeatureUnavailable` (`403`, an optional request field the
  account cannot use).

Messages name the operation and the provider's error code only: never the API key, a request
body or provider prose.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import httpx

from mission_control.application.execution.harness.dispatch import ProviderCapacityLimited
from mission_control.application.execution.usage_admission import ProviderLimitSignal
from mission_control.domain.execution.lanes import LaneProfileName

NATIVE_CODE_LIMIT: Final = 128


class RemoteSessionError(RuntimeError):
    """A provider session API refused a request; subclasses say how the lane responds."""


class SessionNotFound(RemoteSessionError):
    """`404`: the provider has no such session (or turn) under this id."""


class SessionBusy(RemoteSessionError):
    """`409`: the session has an active turn; the send waits for the boundary."""


class CreateConflict(RemoteSessionError):
    """`409`: the client-chosen create id already exists; the lane reattaches to it."""


class NotCancellable(RemoteSessionError):
    """`409`: the turn is already terminal, so there is nothing to cancel."""


class StreamExpired(RemoteSessionError):
    """`410`: the stream's retention passed; the turn record is the terminal truth."""


class InvalidStreamCursor(RemoteSessionError):
    """`400`: the resume cursor belongs to another turn; replay the stream from the start."""


class FeatureUnavailable(RemoteSessionError):
    """`403`: an optional feature is not enabled for this account; recorded, not fatal."""


class AccessDenied(RemoteSessionError, ValueError):
    """`401`/`403`: the credential was refused. Non-retryable: `lane.turn` rejects it."""


class CapacityLimited(RemoteSessionError):
    """`429`: a provider limit refused the request before any work was accepted."""

    def __init__(self, operation: str, *, native_code: str, retry_after_s: int | None) -> None:
        super().__init__(f"{operation}: provider capacity limited ({native_code or '429'})")
        self.native_code = native_code
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class ErrorRule:
    """One row of a provider's error table: the first row matching status (and code, when
    given) names the exception; `message` follows `<operation>: ` in its text."""

    status: int
    error: type[Exception]
    message: str = ""
    code: str | None = None

    def matches(self, status: int, code: str) -> bool:
        return self.status == status and (self.code is None or self.code == code)


# The neutral rows every provider table ends with (provider-specific codes come first).
STANDARD_ERROR_RULES: Final[tuple[ErrorRule, ...]] = (
    ErrorRule(429, CapacityLimited),
    ErrorRule(401, AccessDenied, "the provider refused the credential"),
    ErrorRule(403, AccessDenied, "the provider refused the credential"),
    ErrorRule(404, SessionNotFound, "not found"),
    ErrorRule(410, StreamExpired, "the stream retention window has passed"),
)


def error_code(response: httpx.Response) -> str:
    """The provider's error code from `{"error": {"code"}}` or `{"code"}`, else empty."""

    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping) and error.get("code"):
            return str(error["code"])
        if body.get("code"):
            return str(body["code"])
    return ""


def retry_after_seconds(response: httpx.Response) -> int | None:
    """`Retry-After` in whole seconds; an HTTP date or anything else is not a stated reset."""

    value = response.headers.get("Retry-After", "").strip()
    return int(value) if value.isdigit() else None


def raise_for_response(
    response: httpx.Response,
    operation: str,
    rules: Sequence[ErrorRule],
    *,
    fallback: type[Exception] = RemoteSessionError,
) -> None:
    """Raise the typed error a failed response maps to; a success returns."""

    if response.is_success:
        return
    code = error_code(response)
    status = response.status_code
    for rule in rules:
        if not rule.matches(status, code):
            continue
        if issubclass(rule.error, CapacityLimited):
            raise rule.error(
                operation,
                native_code=code or "rate_limited",
                retry_after_s=retry_after_seconds(response),
            )
        raise rule.error(f"{operation}: {rule.message}" if rule.message else operation)
    raise fallback(f"{operation}: HTTP {status} {code}".rstrip())


def capacity_signal(
    error: CapacityLimited, *, lane_profile: LaneProfileName, now: datetime
) -> ProviderLimitSignal:
    """The MP-05 signal of a `429`: a rate limit with the provider-stated reset when
    `Retry-After` was given (numeric limits stay whatever the provider documents)."""

    return ProviderLimitSignal(
        lane_profile=lane_profile,
        kind="rate_limited",
        resets_at=(
            now + timedelta(seconds=error.retry_after_s)
            if error.retry_after_s is not None
            else None
        ),
        source=f"{lane_profile}.http_429",
        native_code=error.native_code[:NATIVE_CODE_LIMIT] if error.native_code else None,
    )


def capacity_limited(
    error: CapacityLimited, *, lane_profile: LaneProfileName, now: datetime
) -> ProviderCapacityLimited:
    """What a lane raises for a `429` at create or send: the dispatch is journaled
    `declined` and the workflow decides the wait (nothing is re-sent here)."""

    return ProviderCapacityLimited(capacity_signal(error, lane_profile=lane_profile, now=now))


__all__ = [
    "STANDARD_ERROR_RULES",
    "AccessDenied",
    "CapacityLimited",
    "CreateConflict",
    "ErrorRule",
    "FeatureUnavailable",
    "InvalidStreamCursor",
    "NotCancellable",
    "RemoteSessionError",
    "SessionBusy",
    "SessionNotFound",
    "StreamExpired",
    "capacity_limited",
    "capacity_signal",
    "error_code",
    "raise_for_response",
    "retry_after_seconds",
]
