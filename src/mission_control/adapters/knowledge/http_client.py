"""``KnowledgeBindingClient`` over HTTP: the K01 ``ks.knowledge_operation.v2`` surface.

Routes (the Knowledge Services executor, design §4; bodies are exactly the K01 schemas):

=====================================================  =====================================
``POST {base}/knowledge-operation/v2/invoke``          ``operation-envelope.v2`` ->
                                                       ``operation-receipt.v2`` (synchronous
                                                       effect) or ``operation-handle.v2``
``GET  {base}/knowledge-operation/v2/operations/{id}``  ``operation-status.v2``
``POST {base}/knowledge-operation/v2/operations/{id}/cancel``  ``{"cancelRequestId"}`` ->
                                                       ``operation-status.v2`` (idempotent)
``GET  {base}/knowledge-operation/v2/receipts/{key}``  ``receipt-lookup.v2``
``GET  {base}/knowledge-operation/v2/describe``        ``binding-descriptor.v2``
=====================================================  =====================================

``{id}`` is the handle's ``operationId`` and ``{key}`` the effect key, each one URL path
segment (percent-encoded); the tenant, application and binding of a handle are the
credential's, which the executor checks against the handle it stores.

Every 2xx body is validated strictly against the K01 result models; a body outside the
protocol is a :class:`KnowledgeTransportError` (the host cannot know what happened). A 4xx or
5xx with a ``protocol-error.v2`` body raises :class:`KnowledgeProtocolRefusal` with that
typed error; any failure without a protocol body (connect, timeout, 5xx, a proxy's 4xx) is a
:class:`KnowledgeTransportError`. ``invoke`` is never retried here (the gateway's journal owns
effect retries). Status polls and cancellation are idempotent, so a ``429``/``503`` with
``Retry-After`` is honoured, bounded, and a transport failure on cancel is retried (within the
idempotent bound) with the same cancel request id. The bearer credential is passed per call
and never stored, logged or rendered: the client's ``repr`` names only its base URL.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Final, Self, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from mission_control.application.ports.knowledge import (
    Credential,
    KnowledgeProtocolRefusal,
    KnowledgeTransportError,
    ReportPackage,
)
from mission_control.contracts.knowledge_protocol import (
    RESULT_OPERATIONS,
    TERMINAL_STATES,
    KnowledgePlanPreview,
    KnowledgeReadIntentResult,
    OperationEnvelope,
    OperationHandle,
    Ref,
    digest_bytes,
)
from mission_control.contracts.knowledge_protocol_results import (
    RECEIPT_LOOKUP,
    BindingDescriptor,
    OperationReceipt,
    OperationStatus,
    ProtocolError,
    ReceiptFound,
    ReceiptNotFound,
    ReceiptUnresolved,
    protocol_error,
)

PREFIX: Final = "/knowledge-operation/v2"
RETRYABLE_STATUS: Final = frozenset({429, 503})
Model = TypeVar("Model", bound=BaseModel)
Sleep = Callable[[float], Awaitable[None]]


def _segment(value: str) -> str:
    return quote(value, safe="")


class HttpKnowledgeBindingClient:
    """K01 binding client for one executor base URL (no credential is ever held)."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        max_retry_after_seconds: float = 5.0,
        idempotent_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("knowledge binding URL must be http(s)")
        self._base_url = base_url.rstrip("/")
        self._max_retry_after = max_retry_after_seconds
        self._retries = idempotent_retries
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return f"HttpKnowledgeBindingClient({self._base_url!r})"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------ protocol

    async def invoke(
        self, envelope: OperationEnvelope, credential: str
    ) -> OperationHandle | OperationReceipt | KnowledgePlanPreview | KnowledgeReadIntentResult:
        response = await self._send(
            "POST",
            f"{PREFIX}/invoke",
            credential,
            json=envelope.model_dump(mode="json"),
            idempotent=False,
        )
        if envelope.operation == "knowledge.read_intent":
            # OVE-204 slice 4: the recorded read answers its result document in the call.
            return self._model(KnowledgeReadIntentResult, response)
        if envelope.operation in RESULT_OPERATIONS:
            # W1 native write: the read-only plan preview answers its document in the call.
            return self._model(KnowledgePlanPreview, response)
        body = self._json(response)
        if isinstance(body, dict) and "outcome" in body:
            return self._model(OperationReceipt, response)
        return self._model(OperationHandle, response)

    async def operation_get(
        self, handle: OperationHandle, credential: Credential
    ) -> OperationStatus:
        response = await self._send(
            "GET", f"{PREFIX}/operations/{_segment(handle.operationId)}", credential
        )
        return self._status(response, handle)

    async def operation_cancel(
        self, handle: OperationHandle, cancel_request_id: str, credential: Credential
    ) -> OperationStatus:
        response = await self._send(
            "POST",
            f"{PREFIX}/operations/{_segment(handle.operationId)}/cancel",
            credential,
            json={"cancelRequestId": cancel_request_id},
            retry_transport=True,
        )
        status = self._status(response, handle)
        # A cancel of an already-terminal handle answers its terminal status unchanged (no
        # cancel happened, so no request id is recorded): an idempotent no-op, not an error.
        if status.cancelRequestId is None and status.state not in TERMINAL_STATES:
            raise KnowledgeTransportError("cancel answered without its request id")
        return status

    async def receipt(
        self, effect_key: str, credential: Credential
    ) -> ReceiptFound | ReceiptNotFound | ReceiptUnresolved:
        response = await self._send("GET", f"{PREFIX}/receipts/{_segment(effect_key)}", credential)
        try:
            return RECEIPT_LOOKUP.validate_json(response.content)
        except ValidationError:
            raise KnowledgeTransportError("receipt lookup answered outside K01") from None

    async def describe(self, credential: Credential) -> BindingDescriptor:
        response = await self._send("GET", f"{PREFIX}/describe", credential)
        return self._model(BindingDescriptor, response)

    async def artifact(self, artifact_id: str, digest: str, credential: Credential) -> bytes:
        """Exact custody bytes (executor extension); refused unless they digest as named."""

        response = await self._send(
            "GET", f"{PREFIX}/artifacts/{_segment(artifact_id)}?digest={quote(digest)}", credential
        )
        content = response.content
        if digest_bytes(content) != digest:
            raise KnowledgeTransportError("artifact bytes differ from the named digest")
        return content

    # ------------------------------------------------------------ transport

    async def _send(
        self,
        method: str,
        path: str,
        credential: Credential,
        *,
        json: dict[str, Any] | None = None,
        idempotent: bool = True,
        retry_transport: bool = False,
    ) -> httpx.Response:
        # K07 `jti` is single use: a retried transmission carries a fresh credential from the
        # caller-supplied source; a fixed token is sent once and never resent (R2-MC O5).
        retries = self._retries if callable(credential) else 0
        attempts = 1 + (retries if idempotent or retry_transport else 0)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            token = credential() if callable(credential) else credential
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            try:
                response = await self._http.request(method, path, json=json, headers=headers)
            except httpx.HTTPError as error:
                if retry_transport and not last:
                    continue
                # The URL and error class only; never the request headers.
                raise KnowledgeTransportError(
                    f"{method} {path} failed: {type(error).__name__}"
                ) from None
            if idempotent and not last and response.status_code in RETRYABLE_STATUS:
                delay = self._retry_after(response)
                if delay is not None:
                    await self._sleep(delay)
                    continue
            if response.is_success:
                return response
            raise self._failure(response)
        raise KnowledgeTransportError(f"{method} {path} failed")  # pragma: no cover

    def _retry_after(self, response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        return min(max(seconds, 0.0), self._max_retry_after)

    def _failure(self, response: httpx.Response) -> Exception:
        try:
            error = ProtocolError.model_validate_json(response.content)
        except ValidationError:
            return KnowledgeTransportError(
                f"binding answered HTTP {response.status_code} without a protocol error"
            )
        return KnowledgeProtocolRefusal(error)

    @staticmethod
    def _json(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError:
            raise KnowledgeTransportError("binding answered a non-JSON body") from None

    @staticmethod
    def _model(model: type[Model], response: httpx.Response) -> Model:
        try:
            return model.model_validate_json(response.content)
        except ValidationError:
            raise KnowledgeTransportError(
                f"binding answered outside K01 ({model.__name__})"
            ) from None

    def _status(self, response: httpx.Response, handle: OperationHandle) -> OperationStatus:
        status = self._model(OperationStatus, response)
        if status.handle != handle:
            raise KnowledgeTransportError("status names another handle")
        return status


class HttpExactContentReader:
    """``ExactContentReader`` over the executor's ``artifacts/{id}?digest=`` extension.

    Fetches the package manifest named by the read's ``resultRef`` (its bytes must digest to
    it), then the body and ledger artifacts the manifest names, each by exact id and digest
    under its own fresh ``knowledge.read`` credential. Any byte that does not digest as named
    is refused here; the resolution service re-verifies sizes and the report ref.
    """

    def __init__(self, client: HttpKnowledgeBindingClient) -> None:
        self._client = client

    async def fetch(self, result_ref: Ref, credentials: Callable[[], str]) -> ReportPackage:
        manifest_bytes = await self._client.artifact(result_ref.id, result_ref.digest, credentials)
        try:
            manifest = json.loads(manifest_bytes)
            parts = (manifest["body"], manifest["ledger"])
        except (ValueError, KeyError, TypeError):
            raise KnowledgeTransportError("package manifest names no body or ledger") from None
        if parts == (None, None):
            # research-report-package.v2 members read: records only, no body or ledger bytes.
            return ReportPackage(result_ref=result_ref, manifest=manifest, body=b"", ledger=b"")
        try:
            body_ref, ledger_ref = parts[0]["artifact"], parts[1]["artifact"]
        except (KeyError, TypeError):
            raise KnowledgeTransportError(
                "package manifest names no body or ledger artifact"
            ) from None
        body = await self._client.artifact(
            str(body_ref["id"]), str(body_ref["digest"]), credentials
        )
        ledger = await self._client.artifact(
            str(ledger_ref["id"]), str(ledger_ref["digest"]), credentials
        )
        return ReportPackage(result_ref=result_ref, manifest=manifest, body=body, ledger=ledger)


class UnavailableExactContentReader:
    """``ExactContentReader`` for an executor that publishes no exact-bytes route.

    K01 v2 defines how ``knowledge.read`` resolves an exact revision but no route that returns
    its frozen bytes (open question recorded for SV-16). Until it does, a real binding refuses
    typed instead of guessing a route; the parity fake supplies its own reader.
    """

    def __init__(self, *, clock: Callable[[], str]) -> None:
        self._clock = clock

    async def fetch(self, result_ref: Ref, credentials: Callable[[], str]) -> ReportPackage:
        del credentials
        raise KnowledgeProtocolRefusal(
            protocol_error(
                "CAPABILITY_UNAVAILABLE",
                "the binding publishes no exact content route for "
                f"{result_ref.kind}/{result_ref.id}",
                occurred_at=self._clock(),
            )
        )


__all__ = [
    "PREFIX",
    "HttpExactContentReader",
    "HttpKnowledgeBindingClient",
    "UnavailableExactContentReader",
]
