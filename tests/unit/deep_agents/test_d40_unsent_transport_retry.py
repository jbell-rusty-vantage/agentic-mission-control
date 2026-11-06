"""W1 D40 (OVE-169): a connection failure before the request reached the provider.

Live (session 12, run e947fa8e): a TLS/connect failure (`httpcore.ConnectError`, wrapped as
`anthropic.APIConnectionError`; nothing sent, nothing billed) failed the executor
`runtime_failed`, because the lane builds every model client with `max_retries=0`, and the
GoalDirected family then failed non-retryably on `goal_operation_unreported`.

The fix is the recovery ladder's L1 rung (FAULT-TOLERANCE-PROPOSAL section 6.2), built only for
this fault: inside the turn, a model call whose failure provably never reached the provider is
retried a bounded number of times; a request that may have been sent (and billed) never is.
What still fails settles with the typed code `transient_transport`.
"""

from __future__ import annotations

from typing import Any

import anthropic
import httpx
import openai
import pytest

from mission_control.adapters.deep_agents.model_retry import (
    GovernedModelRetryMiddleware,
    unsent_transport_failure,
)
from tests.fixtures.checkpoint_recovery import recovery_harness, stage_recovery_unit

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _wrapped(sdk_error: type[Exception], cause: BaseException) -> Exception:
    error = sdk_error(request=REQUEST)  # type: ignore[call-arg]
    error.__cause__ = cause
    return error


def unsent() -> Exception:
    """The live shape: the SDK wraps httpx, which wraps httpcore's connect failure."""

    return _wrapped(anthropic.APIConnectionError, httpx.ConnectError("tls handshake failed"))


def test_only_failures_that_never_reached_the_provider_are_unsent() -> None:
    assert unsent_transport_failure(unsent())
    assert unsent_transport_failure(
        _wrapped(openai.APIConnectionError, httpx.ConnectTimeout("connect timed out"))
    )
    assert unsent_transport_failure(
        _wrapped(anthropic.APIConnectionError, ConnectionRefusedError("refused"))
    )
    # Sent, or possibly sent: the provider may have processed and billed it.
    assert not unsent_transport_failure(
        _wrapped(anthropic.APIConnectionError, httpx.ReadTimeout("read timed out"))
    )
    assert not unsent_transport_failure(
        _wrapped(anthropic.APIConnectionError, httpx.RemoteProtocolError("closed mid-body"))
    )
    assert not unsent_transport_failure(
        _wrapped(anthropic.APIConnectionError, ConnectionResetError("reset"))
    )
    assert not unsent_transport_failure(anthropic.APITimeoutError(request=REQUEST))
    # A connection error of unknown cause, a provider answer (L4 owns 429), anything else.
    assert not unsent_transport_failure(anthropic.APIConnectionError(request=REQUEST))
    response = httpx.Response(429, request=REQUEST)
    assert not unsent_transport_failure(
        anthropic.RateLimitError("slow down", response=response, body=None)
    )
    assert not unsent_transport_failure(ValueError("bad output"))


class _Handler:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def __call__(self, request: Any) -> Any:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_an_unsent_call_is_retried_and_a_sent_one_never_is() -> None:
    retry = GovernedModelRetryMiddleware(initial_delay=0.0)
    handler = _Handler([unsent(), "answer"])
    assert await retry.awrap_model_call(object(), handler) == "answer"
    assert handler.calls == 2

    sent = _wrapped(anthropic.APIConnectionError, httpx.ReadTimeout("read timed out"))
    handler = _Handler([sent, "answer"])
    with pytest.raises(anthropic.APIConnectionError):
        await retry.awrap_model_call(object(), handler)
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_unsent_retries_are_bounded_and_the_failure_is_raised_not_answered() -> None:
    retry = GovernedModelRetryMiddleware(initial_delay=0.0)
    handler = _Handler([unsent() for _ in range(retry.max_retries + 2)])
    with pytest.raises(anthropic.APIConnectionError):
        await retry.awrap_model_call(object(), handler)
    assert handler.calls == retry.max_retries + 1
    # `on_failure="continue"` would turn the failure into the model's answer.
    assert retry.on_failure == "error"


@pytest.mark.asyncio
async def test_the_lane_retries_one_unsent_call_and_the_unit_completes() -> None:
    harness = await recovery_harness()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    harness.model.fail_on(2, unsent())
    result = await harness.run(request)
    assert result.status == "completed", result
    # Call 2 failed before sending; its retry (call 3) answered.
    assert len(harness.model.calls) == 3


@pytest.mark.asyncio
async def test_an_exhausted_unsent_failure_settles_with_its_typed_code() -> None:
    harness = await recovery_harness()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    for call in range(2, 2 + GovernedModelRetryMiddleware().max_retries + 1):
        harness.model.fail_on(call, unsent())
    result = await harness.run(request)
    assert result.status == "failed"
    assert result.failure_code == "transient_transport"
    assert result.failure_message == "APIConnectionError at governed operation boundary"
