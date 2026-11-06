"""OpenAI Agents API client for the prepare step (SPEC-06 section 5.1; HL-11).

A thin `httpx.AsyncClient` adapter over the resources a `codex_agents` pack is prepared into:
saved agents, environment templates, prewarmed environments, vaults and vault credentials.
Paths, bodies and headers follow the pinned `openai` 3.29.0 source (the SDK HL-23 drove live,
research/provider-smoke-2026-10.md section 3): every call sends `OpenAI-Beta: agents=v1`.
The SDK's `client.beta.agents.vaults` namespace posts to `/vaults`, so vaults live at
`/v1/vaults`, not `/v1/agents/vaults` as the smoke note says. Listings are cursor pages
(`data`, `has_more`, next page `after=<last id>`). Of these creates only a prewarm takes an
`Idempotency-Key` header. Provider errors become the Remote Session Lane base's typed errors
(ADR-0052). Messages never carry the API key, a secret value or provider prose.

Tests drive it through `httpx.MockTransport`; nothing here calls the network by itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx
from pydantic import SecretStr

from mission_control.adapters.remote_session.errors import (
    STANDARD_ERROR_RULES,
    ErrorRule,
    RemoteSessionError,
    SessionBusy,
    raise_for_response,
)
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import StreamOpened, open_event_stream

AGENTS_API_BASE: Final = "https://api.openai.com/v1"
AGENTS_BETA_HEADER: Final = {"OpenAI-Beta": "agents=v1"}
PAGE_LIMIT: Final = 100


class AgentsApiError(RemoteSessionError):
    """The Agents API refused a request with a status no rule names."""


# The prepare calls meet only the neutral rows; the session rows arrive with the lane (HL-12).
AGENTS_API_ERRORS: Final[tuple[ErrorRule, ...]] = (
    ErrorRule(409, SessionBusy, "the session's active turn changed"),
    ErrorRule(
        400, SessionBusy, "the active turn cannot be steered", code="active_turn_not_steerable"
    ),
    *STANDARD_ERROR_RULES,
)


def _raise(response: httpx.Response, operation: str) -> None:
    raise_for_response(response, operation, AGENTS_API_ERRORS, fallback=AgentsApiError)


def _json(response: httpx.Response) -> dict[str, Any]:
    result: dict[str, Any] = response.json()
    return result


@dataclass(frozen=True)
class CredentialAuth:
    secret_name: str | None


@dataclass(frozen=True)
class ListedCredential:
    """A vault credential as a listing reports it: never a value."""

    id: str
    name: str
    auth: CredentialAuth


class VaultCredentials:
    """The vault credentials resource in the shape `ProviderVaultStore` writes through."""

    def __init__(self, client: AgentsApiClient) -> None:
        self._client = client

    async def create(self, vault_id: str, **params: Any) -> dict[str, Any]:
        return await self._client.post(
            f"/vaults/{vault_id}/credentials", params, operation="create vault credential"
        )

    async def list(self, vault_id: str) -> AsyncIterator[ListedCredential]:
        async for item in self._client.pages(
            f"/vaults/{vault_id}/credentials", operation="list vault credentials"
        ):
            auth = item.get("auth")
            secret_name = auth.get("secret_name") if isinstance(auth, Mapping) else None
            yield ListedCredential(
                id=str(item["id"]),
                name=str(item.get("name", "")),
                auth=CredentialAuth(secret_name if isinstance(secret_name, str) else None),
            )


class AgentsApiClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = AGENTS_API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 30,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}", **AGENTS_BETA_HEADER},
            transport=transport,
            timeout=timeout_s,
            follow_redirects=False,
        )
        self.credentials = VaultCredentials(self)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def retrieve(self, path: str, *, operation: str) -> dict[str, Any]:
        response = await self._client.get(path)
        _raise(response, operation)
        return _json(response)

    async def create_session(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.post("/agents/sessions", body, operation="create session")

    async def retrieve_session(self, session_id: str) -> dict[str, Any]:
        return await self.retrieve(f"/agents/sessions/{session_id}", operation="retrieve session")

    def sessions(self, agent_id: str) -> AsyncIterator[dict[str, Any]]:
        return self.pages(
            "/agents/sessions", operation="list sessions", params={"agent_id": agent_id}
        )

    def turns(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        return self.pages(f"/agents/sessions/{session_id}/turns", operation="list turns")

    async def retrieve_turn(self, session_id: str, turn_id: str) -> dict[str, Any]:
        return await self.retrieve(
            f"/agents/sessions/{session_id}/turns/{turn_id}", operation="retrieve turn"
        )

    def items(
        self, session_id: str, *, turn_id: str | None = None, after: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        return self.pages(
            (
                f"/agents/sessions/{session_id}/turns/{turn_id}/items"
                if turn_id is not None
                else f"/agents/sessions/{session_id}/items"
            ),
            operation="list items",
            params={"after": after} if after else None,
        )

    def artifacts(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        return self.pages(
            f"/agents/sessions/{session_id}/artifacts", operation="list session artifacts"
        )

    async def artifact_content(
        self, session_id: str, artifact_id: str, *, max_bytes: int = 8 * 1024 * 1024
    ) -> bytes:
        async with self._client.stream(
            "GET", f"/agents/sessions/{session_id}/artifacts/{artifact_id}/content"
        ) as response:
            _raise(response, "download session artifact")
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("session artifact exceeds custody size limit")
                chunks.append(chunk)
            return b"".join(chunks)

    async def send_events(
        self, session_id: str, events: list[dict[str, Any]], *, idempotency_key: str
    ) -> None:
        # The API acknowledges input with an empty 202, not a turn or event body.
        response = await self._client.post(
            f"/agents/sessions/{session_id}/events",
            json={"events": events},
            headers={"Idempotency-Key": idempotency_key},
        )
        _raise(response, "send session events")

    def stream_events(self, session_id: str) -> AsyncIterator[SseEvent | StreamOpened]:
        return open_event_stream(
            self._client,
            f"/agents/sessions/{session_id}/events",
            operation="stream session events",
            rules=AGENTS_API_ERRORS,
            fallback=AgentsApiError,
            params={"stream": "true"},
        )

    async def delete_session(self, session_id: str) -> None:
        await self.delete(f"/agents/sessions/{session_id}", operation="delete session")

    async def post(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        operation: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = await self._client.post(path, json=dict(body), headers=headers)
        _raise(response, operation)
        return _json(response)

    async def delete(self, path: str, *, operation: str) -> None:
        _raise(await self._client.delete(path), operation)

    async def pages(
        self, path: str, *, operation: str, params: Mapping[str, str] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Every item of a cursor-paged listing, oldest first."""

        query: dict[str, str | int] = {**(params or {}), "limit": PAGE_LIMIT, "order": "asc"}
        while True:
            response = await self._client.get(path, params=query)
            _raise(response, operation)
            page = _json(response)
            items = [item for item in page.get("data") or [] if isinstance(item, Mapping)]
            for item in items:
                yield dict(item)
            if not items or page.get("has_more") is False:
                return
            query["after"] = str(items[-1]["id"])

    def agents(self) -> AsyncIterator[dict[str, Any]]:
        return self.pages("/agents", operation="list agents")

    async def create_agent(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.post("/agents", body, operation="create agent")

    async def delete_agent(self, agent_id: str) -> None:
        await self.delete(f"/agents/{agent_id}", operation="delete agent")

    def environment_templates(self) -> AsyncIterator[dict[str, Any]]:
        return self.pages("/agents/environments/templates", operation="list environment templates")

    async def create_environment_template(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Templates take no `Idempotency-Key` (openai 3.29.0); a lost response is found again
        by its digest-carrying name."""

        return await self.post(
            "/agents/environments/templates", body, operation="create environment template"
        )

    async def delete_environment_template(self, template_id: str) -> None:
        await self.delete(
            f"/agents/environments/templates/{template_id}",
            operation="delete environment template",
        )

    async def prewarm_environment(
        self, body: Mapping[str, Any], *, idempotency_key: str
    ) -> dict[str, Any]:
        return await self.post(
            "/agents/environments",
            body,
            operation="prewarm environment",
            idempotency_key=idempotency_key,
        )

    def vaults(self, metadata: Mapping[str, str]) -> AsyncIterator[dict[str, Any]]:
        """Active vaults whose metadata holds every pair (the filter is eventually consistent,
        so callers match the metadata again)."""

        params = {f"metadata[{key}]": value for key, value in metadata.items()}
        return self.pages("/vaults", operation="list vaults", params={**params, "status": "active"})

    async def create_vault(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.post("/vaults", body, operation="create vault")

    async def delete_vault(self, vault_id: str) -> None:
        await self.delete(f"/vaults/{vault_id}", operation="delete vault")


__all__ = [
    "AGENTS_API_BASE",
    "AGENTS_API_ERRORS",
    "AGENTS_BETA_HEADER",
    "AgentsApiClient",
    "AgentsApiError",
    "CredentialAuth",
    "ListedCredential",
    "VaultCredentials",
]
