"""K01 HTTP binding client (SV-16 deliverable 1) against in-process fake HTTP servers.

``httpx.MockTransport`` servers replay the golden K01 vectors and scripted failures: the client
sends the golden envelope bytes unchanged, validates every 2xx strictly, maps protocol-error
bodies to typed refusals and everything else to transport errors, honours a bounded
``Retry-After`` only on idempotent calls, retries cancellation with the same request id, and
never exposes the bearer credential.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from mission_control.adapters.knowledge.http_client import HttpKnowledgeBindingClient
from mission_control.application.ports.knowledge import (
    KnowledgeProtocolRefusal,
    KnowledgeTransportError,
)
from mission_control.contracts.knowledge_protocol import OperationEnvelope, OperationHandle
from mission_control.contracts.knowledge_protocol_results import protocol_error
from tests.fixtures.knowledge_binding import describe_document

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "knowledge_protocol"
GOLDEN = json.loads(
    (FIXTURES / "knowledge-operation-protocol.v2.golden.json").read_text(encoding="utf-8")
)
VECTORS = {vector["id"]: vector for vector in GOLDEN["vectors"]}
TOKEN = "eyJhbGciOiJFZERTQSJ9.c2VjcmV0LWNsYWltcw.c2lnbmF0dXJl"
HANDLE = OperationHandle(
    protocolVersion="ks.knowledge_operation.v2",
    tenant="tenant-1",
    application="ai-engineer",
    binding="aiengineer-postgres",
    operationId="op/1:a",
)


def status(state: str = "running", **updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "handle": HANDLE.model_dump(mode="json"),
        "state": state,
        "revision": 2,
        "createdAt": "2026-10-25T10:00:00Z",
        "updatedAt": "2026-10-25T10:00:01Z",
        "progressRef": None,
        "pendingReviewRef": None,
        "resultRef": None,
        "error": None,
        "unresolvedEffects": [],
        "retryAfterMs": 100,
        "cancelRequestId": None,
    }
    return document | updates


def client(handler: Callable[[httpx.Request], httpx.Response], **options: object):
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return (
        HttpKnowledgeBindingClient(
            "http://ks.test/", transport=httpx.MockTransport(handler), sleep=sleep, **options
        ),
        sleeps,
    )


async def test_invoke_sends_the_golden_envelope_and_parses_a_handle() -> None:
    seen: list[httpx.Request] = []
    envelope = OperationEnvelope.model_validate(VECTORS["apply-envelope"]["envelope"])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json=HANDLE.model_dump(mode="json"))

    http, _ = client(handler)
    answer = await http.invoke(envelope, TOKEN)
    assert answer == HANDLE
    (request,) = seen
    assert request.method == "POST" and request.url.path == "/knowledge-operation/v2/invoke"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    sent = OperationEnvelope.model_validate_json(request.content)
    assert sent == envelope and sent.digest() == VECTORS["apply-envelope"]["envelopeDigest"]


async def test_routes_encode_operation_ids_and_effect_keys_as_one_segment() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.raw_path.decode())
        if "/receipts/" in request.url.path:
            return httpx.Response(
                200, json={"disposition": "not_found", "checkedAt": "2026-10-25T10:00:00Z"}
            )
        if request.url.path.endswith("/describe"):
            return httpx.Response(200, json=describe_document("aiengineer-postgres", "biotech"))
        return httpx.Response(200, json=status())

    http, _ = client(handler)
    await http.operation_get(HANDLE, TOKEN)
    lookup = await http.receipt("ek1:abc/def", TOKEN)
    assert lookup.disposition == "not_found"
    assert (await http.describe(TOKEN)).binding == "aiengineer-postgres"
    assert paths == [
        "/knowledge-operation/v2/operations/op%2F1%3Aa",
        "/knowledge-operation/v2/receipts/ek1%3Aabc%2Fdef",
        "/knowledge-operation/v2/describe",
    ]


async def test_protocol_error_bodies_are_typed_refusals_and_other_failures_are_transport() -> None:
    error = protocol_error(
        "EXACT_REVISION_UNAVAILABLE", "no such revision", occurred_at="2026-10-25T10:00:00Z"
    )
    answers = iter(
        [
            httpx.Response(409, json=error.model_dump(mode="json")),
            httpx.Response(500, text="<html>proxy</html>"),
            httpx.Response(401, json={"detail": "not K01"}),
            httpx.Response(200, json={"handle": "not a status"}),
            httpx.Response(
                200, json=status(handle=HANDLE.model_dump(mode="json") | {"operationId": "other"})
            ),
            httpx.Response(200, json=status("succeeded")),  # terminal with a retry hint
        ]
    )
    http, _ = client(lambda _request: next(answers), idempotent_retries=0)
    with pytest.raises(KnowledgeProtocolRefusal) as refused:
        await http.operation_get(HANDLE, TOKEN)
    assert refused.value.error.code == "EXACT_REVISION_UNAVAILABLE"
    for _ in range(5):
        with pytest.raises(KnowledgeTransportError) as failed:
            await http.operation_get(HANDLE, TOKEN)
        assert TOKEN not in str(failed.value)


async def test_connect_and_timeout_failures_never_reveal_the_credential() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    http, _ = client(handler)
    envelope = OperationEnvelope.model_validate(VECTORS["apply-envelope"]["envelope"])
    with pytest.raises(KnowledgeTransportError) as failed:
        await http.invoke(envelope, TOKEN)
    assert TOKEN not in str(failed.value) and TOKEN not in repr(http)
    assert "ConnectTimeout" in str(failed.value)


async def test_retry_after_is_bounded_and_only_honoured_on_idempotent_calls() -> None:
    calls: list[str] = []
    bearers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        bearers.append(request.headers["Authorization"])
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "120"})
        return httpx.Response(200, json=status())

    minted = iter(["token-1", "token-2"])
    http, sleeps = client(handler, max_retry_after_seconds=2.0)
    assert (await http.operation_get(HANDLE, lambda: next(minted))).state == "running"
    assert sleeps == [2.0] and calls == ["GET", "GET"]
    # K07 `jti` is single use: the retry presents a freshly minted credential (R2-MC O5).
    assert bearers == ["Bearer token-1", "Bearer token-2"]

    # A fixed token is sent once and never resent.
    calls.clear()
    http, sleeps = client(handler, max_retry_after_seconds=2.0)
    with pytest.raises(KnowledgeTransportError):
        await http.operation_get(HANDLE, TOKEN)
    assert calls == ["GET"] and sleeps == []

    effects: list[str] = []

    def busy(request: httpx.Request) -> httpx.Response:
        effects.append(request.method)
        return httpx.Response(503, headers={"Retry-After": "1"})

    http, sleeps = client(busy)
    envelope = OperationEnvelope.model_validate(VECTORS["apply-envelope"]["envelope"])
    with pytest.raises(KnowledgeTransportError):
        await http.invoke(envelope, TOKEN)
    assert effects == ["POST"] and sleeps == []  # an effect is never re-sent by the client


async def test_cancel_is_retried_once_with_the_same_request_id() -> None:
    bodies: list[dict[str, object]] = []
    bearers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        bearers.append(request.headers["Authorization"])
        if len(bodies) == 1:
            raise httpx.ReadError("reset", request=request)
        return httpx.Response(
            200, json=status("cancelled", retryAfterMs=None, cancelRequestId="cancel-1")
        )

    minted = iter(["cancel-token-1", "cancel-token-2"])
    http, _ = client(handler)
    answer = await http.operation_cancel(HANDLE, "cancel-1", lambda: next(minted))
    assert answer.state == "cancelled" and answer.cancelRequestId == "cancel-1"
    assert bodies == [{"cancelRequestId": "cancel-1"}, {"cancelRequestId": "cancel-1"}]
    assert bearers == ["Bearer cancel-token-1", "Bearer cancel-token-2"]
