"""Cursor Cloud Agents API v1 client (research/cursor-platform.md section 4; FT-G5).

A thin `httpx.AsyncClient` adapter over the public-beta REST surface the `cursor_cloud` lane
uses: create an agent (its first run is enqueued with it), follow-up runs, run reads, the run
SSE stream with `Last-Event-ID`, cancel, artifacts (listed, then downloaded through presigned
URLs without the API key), usage, archive. Provider errors become typed exceptions by their
documented codes (`agent_id_conflict`, `agent_busy`, `run_not_cancellable`, `stream_expired`,
`feature_unavailable`, `run_not_found`) through the `CLOUD_AGENTS_ERRORS` table of the Remote
Session Lane base (ADR-0052): each Cursor error is also the base's neutral error, so the shared
observe loop handles expiry and foreign cursors. Messages never carry the API key or provider
text.

Tests drive it through `httpx.MockTransport`; nothing here calls the network by itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

import httpx
from pydantic import SecretStr

from mission_control.adapters.cursor.bridge import (
    AgentArchived,
    AgentBusy,
    BridgeError,
    FeatureUnavailable,
    ProviderAccessDenied,
    ProviderTransient,
    RunNotCancellable,
    RunNotFound,
)
from mission_control.adapters.remote_session.errors import (
    CapacityLimited,
    CreateConflict,
    ErrorRule,
    InvalidStreamCursor,
    SessionNotFound,
    raise_for_response,
)
from mission_control.adapters.remote_session.errors import StreamExpired as RemoteStreamExpired
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import StreamOpened, open_event_stream

CLOUD_API_BASE = "https://api.cursor.com"
RETENTION_HEADER = "X-Cursor-Stream-Retention-Seconds"


class AgentIdConflict(BridgeError, CreateConflict):
    """`409 agent_id_conflict`: the client-supplied agent id already exists (reattach)."""


class StreamExpired(BridgeError, RemoteStreamExpired):
    """`410 stream_expired`: read the terminal state from `GET .../runs/{runId}` instead."""


class AgentNotFound(BridgeError, SessionNotFound):
    """`404`: the agent (or its run) does not exist."""


class InvalidLastEventId(BridgeError, InvalidStreamCursor):
    """`400 invalid_last_event_id`: the cursor belongs to another run."""


class CloudCapacityLimited(BridgeError, CapacityLimited):
    """`429` (standard rate limiting on every Cloud Agents endpoint, `Retry-After` in
    seconds per the Cursor API overview): a capacity condition the provider stated before
    any work was accepted. The lane turns it into `ProviderCapacityLimited` so the workflow
    waits on a Temporal timer (MP-05/06); it is never retried here. Distinct from
    `409 agent_busy` (`AgentBusy`), which is this agent's own active run (`wait_then_send`,
    ADR-0030)."""


# The Cloud Agents error table, in match order; anything else is a `BridgeError`.
CLOUD_AGENTS_ERRORS: Final[tuple[ErrorRule, ...]] = (
    ErrorRule(409, AgentIdConflict, "agent id already exists", code="agent_id_conflict"),
    ErrorRule(409, AgentBusy, "the agent has an active run", code="agent_busy"),
    ErrorRule(409, RunNotCancellable, "the run is already terminal", code="run_not_cancellable"),
    ErrorRule(410, StreamExpired, "the stream retention window has passed"),
    ErrorRule(
        403, FeatureUnavailable, "feature unavailable for this account", code="feature_unavailable"
    ),
    ErrorRule(404, RunNotFound, "run not found", code="run_not_found"),
    ErrorRule(404, AgentNotFound, "not found"),
    ErrorRule(
        400,
        InvalidLastEventId,
        "the stream cursor belongs to another run",
        code="invalid_last_event_id",
    ),
    ErrorRule(429, CloudCapacityLimited),
    ErrorRule(409, AgentArchived, "agent is archived", code="agent_archived"),
    ErrorRule(401, ProviderAccessDenied, "provider refused credential"),
    ErrorRule(403, ProviderAccessDenied, "provider refused access"),
    *(
        ErrorRule(status, ProviderTransient, "provider server unavailable")
        for status in range(500, 600)
    ),
)


def _raise(response: httpx.Response, operation: str) -> None:
    try:
        raise_for_response(response, operation, CLOUD_AGENTS_ERRORS, fallback=BridgeError)
    except Exception as error:
        import re

        if type(error) is BridgeError:
            error = BridgeError(f"{operation}: Cursor HTTP {response.status_code}")
        request_id = response.headers.get("x-request-id", "")
        if isinstance(error, BridgeError):
            error.request_id = (
                request_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) else None
            )
        raise error from None


class _CursorHttpClient(httpx.AsyncClient):
    async def send(self, request: httpx.Request, *args: Any, **kwargs: Any) -> httpx.Response:
        try:
            return await super().send(request, *args, **kwargs)
        except httpx.TransportError:
            raise ProviderTransient(
                "Cursor HTTP transport failed; reconcile native dispatch"
            ) from None


def api_client(
    api_key: SecretStr,
    *,
    base_url: str = CLOUD_API_BASE,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: httpx.Timeout | float = 30,
) -> httpx.AsyncClient:
    """An `httpx.AsyncClient` for the Cursor API: bearer authentication, no redirects (the
    agents, environments and secrets clients share it)."""

    return _CursorHttpClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
    )


class CloudAgentsClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = CLOUD_API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 30,
    ) -> None:
        self._client = api_client(
            api_key,
            base_url=base_url,
            transport=transport,
            timeout=httpx.Timeout(timeout_s, read=None),
        )
        # Presigned artifact URLs never receive the API key.
        self._downloads = _CursorHttpClient(
            transport=transport, timeout=timeout_s, follow_redirects=False
        )

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._downloads.aclose()

    async def create_agent(
        self, body: Mapping[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = await self._client.post("/v1/agents", json=dict(body), headers=headers)
        _raise(response, "create agent")
        result: dict[str, Any] = response.json()
        return result

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/v1/agents/{agent_id}")
        _raise(response, "get agent")
        result: dict[str, Any] = response.json()
        return result.get("agent", result) if isinstance(result.get("agent"), dict) else result

    async def create_run(self, agent_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._client.post(f"/v1/agents/{agent_id}/runs", json=dict(body))
        _raise(response, "create run")
        result: dict[str, Any] = response.json()
        run = result.get("run", result)
        return dict(run)

    async def get_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/v1/agents/{agent_id}/runs/{run_id}")
        _raise(response, "get run")
        result: dict[str, Any] = response.json()
        run = result.get("run", result)
        return dict(run)

    async def cancel_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
        response = await self._client.post(f"/v1/agents/{agent_id}/runs/{run_id}/cancel")
        _raise(response, "cancel run")
        body = response.json() if response.content else {}
        return {
            "response": body if isinstance(body, dict) else {},
            "provider_date": response.headers.get("Date"),
        }

    async def stream(
        self, agent_id: str, run_id: str, *, last_event_id: str | None
    ) -> AsyncIterator[SseEvent | StreamOpened]:
        """The run's SSE events; the first item reports the retention window."""

        async for item in open_event_stream(
            self._client,
            f"/v1/agents/{agent_id}/runs/{run_id}/stream",
            operation="stream run",
            rules=CLOUD_AGENTS_ERRORS,
            fallback=BridgeError,
            last_event_id=last_event_id,
            retention_header=RETENTION_HEADER,
        ):
            yield item

    async def list_artifacts(self, agent_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(f"/v1/agents/{agent_id}/artifacts")
        _raise(response, "list artifacts")
        items = response.json().get("items") or []
        return [dict(item) for item in items if isinstance(item, Mapping)]

    async def download_artifact(self, agent_id: str, path: str) -> bytes:
        response = await self._client.get(
            f"/v1/agents/{agent_id}/artifacts/download", params={"path": path}
        )
        _raise(response, "artifact download url")
        url = str(response.json()["url"])
        download = await self._downloads.get(url)
        _raise(download, "artifact download")
        return download.content

    async def usage(self, agent_id: str, run_id: str | None = None) -> dict[str, Any]:
        params = {"runId": run_id} if run_id else None
        response = await self._client.get(f"/v1/agents/{agent_id}/usage", params=params)
        _raise(response, "usage")
        result: dict[str, Any] = response.json()
        return result

    async def conversation(self, agent_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(f"/v0/agents/{agent_id}/conversation")
        _raise(response, "conversation export")
        messages = response.json().get("messages", [])
        return [dict(item) for item in messages if isinstance(item, Mapping)]

    async def archive(self, agent_id: str) -> None:
        response = await self._client.post(f"/v1/agents/{agent_id}/archive")
        _raise(response, "archive agent")


__all__ = [
    "CLOUD_AGENTS_ERRORS",
    "CLOUD_API_BASE",
    "RETENTION_HEADER",
    "AgentIdConflict",
    "AgentNotFound",
    "CloudAgentsClient",
    "CloudCapacityLimited",
    "InvalidLastEventId",
    "StreamExpired",
    "StreamOpened",
    "api_client",
]
